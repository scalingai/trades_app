#!/usr/bin/env python3
"""Riesgo por activo, pero con un techo duro para la cuenta.

EL AGUJERO QUE SE ARREGLA. `motor.jornada` respeta su `riesgo` dentro de UN día
de UN papel, y se corre una vez por (papel, fecha). Si tres papeles califican el
mismo día, la cuenta arriesga tres veces el límite sin que nada avise. El 1 de
septiembre operamos BIAF y DAIC juntos: $800, no $400.

EL DISEÑO, COMO LO PIDIO AGUS. El riesgo sigue siendo POR ACTIVO —un día de tres
papeles arriesga más que uno de un papel, y está bien que así sea— pero la
cuenta tiene un TECHO que no se cruza. Cuando la pérdida marcada a mercado de
TODOS los papeles juntos toca el límite diario, se cierra todo y el día terminó.

No es repartir la caja entre los papeles: es dejarlos operar con su riesgo
propio y cortar de arriba. Repartir exigiría saber a las 10:00 cuántos papeles
van a calificar, y uno puede aparecer a las 10:40 — usar ese número sería el
mismo look-ahead que ya costó doce puntos en este proyecto.

POR QUE ESTA SIMULACION CAMINA BARRA POR BARRA. El techo se puede tocar en
cualquier minuto, no sólo cuando hay una señal. Y un tramo puede morir por el
techo ANTES de llegar a su stop, así que su salida no se puede precalcular:
depende de lo que hagan los otros papeles.

    python test_caja_diaria.py
"""

from __future__ import annotations

import sys
from collections import defaultdict

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import APERTURA_RTH, CIERRE_RTH, hora
from motor import COSTO_ACCION, jornada as jornada_motor, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PISO, STOP, MAXT, DESDE = 2.0, 45.0, 40, 10.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def correr_dia(papeles, *, riesgo_papel, techo_dia=None, corte_h=None,
               umbral=5.0):
    """Un día de CUENTA: varios papeles, cada uno con su riesgo, un solo techo.

    `techo_dia=None` reproduce lo que hay hoy — cada papel con su caja y la
    cuenta sin límite. Es la fila de control: tiene que dar lo mismo que el
    motor, y si no da, el arnés está mal.
    """
    series = []
    for d in papeles:
        idx = set(i for i in señales_swing(d, desde=DESDE)
                  if (d.bars[i][4] or 0) >= PISO)
        if idx and d.rth_close:
            series.append((d, idx))
    if not series:
        return None

    r_tramo = riesgo_papel / 3.0
    abiertos = defaultdict(list)     # ticker -> tramos vivos
    cerrados = []
    n_tramos = defaultdict(int)
    corte_hecho = set()
    muerto = False

    # Todas las horas de la rueda, de todos los papeles, en orden. El techo se
    # puede tocar en cualquier minuto, no sólo cuando hay señal.
    horas = sorted({hora(b) for d, _ in series for b in d.bars
                    if APERTURA_RTH <= hora(b) <= CIERRE_RTH})

    def px_de(d, h):
        j = d.idx_en(h)
        return d.bars[j][4] if j is not None else None

    def equity(h, solo=None):
        """Marcado a mercado. `solo` limita a un papel; None es la cuenta."""
        tot = sum(t["pnl"] for t in cerrados
                  if solo is None or t["ticker"] == solo)
        for tk, ts in abiertos.items():
            if solo is not None and tk != solo:
                continue
            for t in ts:
                p = px_de(t["dia"], h)
                if p:
                    tot += t["acciones"] * (t["p_ent"] - p)
        return tot

    def cerrar(t, h, p, motivo):
        t["h_sal"], t["p_sal"], t["motivo"] = h, p, motivo
        t["pnl"] = t["acciones"] * (t["p_ent"] - p) - t["acciones"] * COSTO_ACCION
        cerrados.append(t)

    for h in horas:
        if muerto:
            break

        # 1) ¿Algún tramo tocó su stop en esta barra? Se resuelve antes que
        #    nada: es la salida que ya estaba puesta en el mercado.
        for tk in list(abiertos):
            quedan = []
            for t in abiertos[tk]:
                j = t["dia"].idx_en(h)
                b = t["dia"].bars[j] if j is not None else None
                if b and hora(b) == h and b[2] and b[2] >= t["p_stop"]:
                    cerrar(t, h, t["p_stop"], "stop")
                else:
                    quedan.append(t)
            abiertos[tk] = quedan

        # 2) EL TECHO DE LA CUENTA. Si la pérdida de todos los papeles juntos
        #    lo toca, se cierra TODO y el día terminó. Es la regla del plan, no
        #    una preferencia: pasarlo liquida la cuenta.
        if techo_dia is not None and equity(h) <= -techo_dia:
            for tk in list(abiertos):
                for t in abiertos[tk]:
                    p = px_de(t["dia"], h)
                    if p:
                        cerrar(t, h, p, "techo")
                abiertos[tk] = []
            muerto = True
            break

        # 3) El corte de las 11:00, por papel y condicional.
        if corte_h is not None and h >= corte_h:
            for tk in list(abiertos):
                if tk in corte_hecho or not abiertos[tk]:
                    continue
                corte_hecho.add(tk)
                d = abiertos[tk][0]["dia"]
                p = px_de(d, h)
                if not p:
                    continue
                acc = sum(t["acciones"] for t in abiertos[tk])
                prom = sum(t["p_ent"] * t["acciones"] for t in abiertos[tk]) / acc
                if 100.0 * (prom - p) / prom < umbral:
                    for t in abiertos[tk]:
                        cerrar(t, h, p, "corte")
                    abiertos[tk] = []
                    n_tramos[tk] = MAXT      # y no se vuelve a entrar

        # 4) Señales de esta hora. El riesgo es POR PAPEL.
        for d, idx in series:
            tk = d.ticker
            j = d.idx_en(h)
            if j is None or hora(d.bars[j]) != h or j not in idx:
                continue
            if n_tramos[tk] >= MAXT:
                continue
            p = d.bars[j][4]
            if not p:
                continue
            # Presupuesto del PAPEL, marcado a mercado, igual que el motor.
            if equity(h, solo=tk) - r_tramo < -riesgo_papel:
                n_tramos[tk] = MAXT          # ese papel cerró su día
                continue
            # Y el techo de la cuenta, que manda por encima del papel.
            if techo_dia is not None and equity(h) - r_tramo < -techo_dia:
                continue
            acciones = r_tramo / (p * STOP / 100.0)
            abiertos[tk].append({
                "dia": d, "ticker": tk, "acciones": acciones, "p_ent": p,
                "h_ent": h, "p_stop": p * (1 + STOP / 100.0),
                "h_sal": None, "p_sal": None, "motivo": None, "pnl": 0.0})
            n_tramos[tk] += 1

    # Lo que quede vivo, al cierre de su papel.
    for tk in list(abiertos):
        for t in abiertos[tk]:
            cerrar(t, CIERRE_RTH, t["dia"].rth_close, "cierre")
        abiertos[tk] = []

    if not cerrados:
        return None
    bruto = sum(t["pnl"] + t["acciones"] * COSTO_ACCION for t in cerrados)
    com = sum(comision(t["acciones"]) for t in cerrados)
    # Pico simultáneo por papel: es lo que hay que localizar en cada uno.
    nominal = 0.0
    por_tk = defaultdict(list)
    for t in cerrados:
        por_tk[t["ticker"]].append(t)
    for tk, ts in por_tk.items():
        ev = []
        for t in ts:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"], -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pico = 0.0
        for _, da in ev:
            a += da
            pico = max(pico, a)
        nominal += pico * (ts[0]["dia"].rth_close or 0)
    return {"neto": bruto - com, "nominal": nominal, "trades": len(cerrados),
            "papeles": len(por_tk), "murio": muerto}


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]
POR_FECHA = defaultdict(list)
for d in pob:
    POR_FECHA[d.d].append(d)

n = [len(v) for v in POR_FECHA.values()]
print(f"\n  {len(pob)} sesiones en {len(POR_FECHA)} días de calendario.")
print(f"  1 papel en {sum(1 for x in n if x == 1)} días · "
      f"2 en {sum(1 for x in n if x == 2)} · "
      f"3+ en {sum(1 for x in n if x >= 3)} · máximo {max(n)}.")


def medir(**kw):
    neto = nom = 0.0
    por_dia, murieron = {}, 0
    for f, ps in POR_FECHA.items():
        r = correr_dia(ps, **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        por_dia[f] = r["neto"]
        murieron += 1 if r["murio"] else 0
    corr = pico = dd = 0.0
    for f in sorted(por_dia):
        corr += por_dia[f]
        pico = max(pico, corr)
        dd = min(dd, corr - pico)
    v = sorted(por_dia.values())
    return {"dias": len(por_dia), "neto": neto, "dd": dd, "techo": murieron,
            "ret": 100 * neto / nom if nom else 0.0,
            "peor": v[0] if v else 0.0,
            "rompe": sum(1 for x in v if x < -400)}


# CONTROL DE ARNES: sin techo tiene que dar lo mismo que el motor. Si no da,
# la simulacion esta mal y todo lo de abajo no vale nada.
ctl = 0.0
for d in pob:
    j = jornada_motor(d, lambda x: [i for i in señales_swing(x, desde=DESDE)
                                    if (x.bars[i][4] or 0) >= PISO],
                      lado="short", stop_pct=STOP, riesgo=400.0, max_trades=MAXT)
    if j:
        b = j["pnl"]
        for t in j["detalle"]:
            b += t["acciones"] * COSTO_ACCION - comision(t["acciones"])
        ctl += b
sin_techo = medir(riesgo_papel=400.0, techo_dia=None)
print(f"\n  Control: motor ${ctl:,.0f}  ·  este arnés sin techo "
      f"${sin_techo['neto']:,.0f}  ·  diferencia "
      f"{100 * abs(ctl - sin_techo['neto']) / abs(ctl):.1f}%")

print()
print("  {:<40} {:>10} {:>8} {:>10} {:>10} {:>6} {:>6}".format(
    "configuracion", "neto", "ret/nom", "peor dia", "drawdown", ">$400", "techo"))
print("  " + "-" * 96)

CONFIGS = [
    ("HOY: $400/papel, sin techo", dict(riesgo_papel=400.0)),
    ("HOY + corte 11:00", dict(riesgo_papel=400.0, corte_h=11.0)),
    ("$400/papel, techo $400", dict(riesgo_papel=400.0, techo_dia=400.0)),
    ("$400/papel, techo $400 + corte", dict(riesgo_papel=400.0, techo_dia=400.0,
                                            corte_h=11.0)),
    ("$200/papel, techo $400", dict(riesgo_papel=200.0, techo_dia=400.0)),
    ("$200/papel, techo $400 + corte", dict(riesgo_papel=200.0, techo_dia=400.0,
                                            corte_h=11.0)),
    ("$400/papel, techo $600 + corte", dict(riesgo_papel=400.0, techo_dia=600.0,
                                            corte_h=11.0)),
    # La comparacion que decide: el corte SOLO, a la mitad de riesgo. Si iguala
    # a las que llevan techo, el techo no esta comprando nada.
    ("$200/papel + corte, SIN techo", dict(riesgo_papel=200.0, corte_h=11.0)),
    ("$150/papel + corte, SIN techo", dict(riesgo_papel=150.0, corte_h=11.0)),
]
for nombre, kw in CONFIGS:
    m = medir(**kw)
    print("  {:<40} ${:>9,.0f} {:>7.2f}% ${:>9,.0f} ${:>9,.0f} {:>6} {:>6}".format(
        nombre, m["neto"], m["ret"], m["peor"], m["dd"], m["rompe"], m["techo"]))

print()
print("  'techo' es en cuántos días se tocó el límite y se cerró todo. '>$400'")
print("  son los días que igual perforaron el límite — con techo puesto deberían")
print("  ser cero, y si no lo son es que el techo se cruzó dentro de una vela.")
