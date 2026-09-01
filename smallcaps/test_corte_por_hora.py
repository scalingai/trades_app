#!/usr/bin/env python3
"""Si a las X no funcionó, salir. ¿Evita el golpe en contra o corta lo bueno?

POR QUE ESTA PREGUNTA NO ES LA MISMA QUE LAS ANTERIORES. Los trece intentos de
"asegurar" que fallaron cortaban GANADORES: salían cuando el trade iba a favor,
y el argumento de por qué fallan es que la estrategia vive de la cola derecha —
los pocos días que se derrumban en serio— y cortarlos la mata.

Esto corta PERDEDORES: los que a media rueda no hicieron nada. La cola derecha
no se toca, así que aquel argumento no aplica y hay que medirlo de nuevo.

EL PLACEBO ACA NO ES AL AZAR, ES EL CORTE INCONDICIONAL. Si "cerrar a las 12:00
cuando no hay profit" mejora, hay que compararlo contra "cerrar a las 12:00
siempre". Si el incondicional rinde igual, lo que ayudó fue acortar la
exposición horaria y no la condición — y entonces la condición es decoración.

Se prueba también el corte al revés (salir sólo si VA a favor) como control de
signo: si las dos direcciones "mejoran", lo que mejora es salir, no el criterio.

    python test_corte_por_hora.py
"""

from __future__ import annotations

import statistics
import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT, DESDE = 400.0, 2.0, 45.0, 40, 10.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def jornada(dia, *, corte_h=None, modo=None, umbral=0.0):
    """La estrategia de siempre con un corte por hora opcional.

    `modo`:
      None        — sostener al cierre (la base).
      "siempre"   — cerrar todo a `corte_h`, pase lo que pase. El placebo.
      "si_flojo"  — cerrar sólo si el no-realizado está por DEBAJO de `umbral`
                    (% del promedio de entrada). La idea de Agus.
      "si_bueno"  — cerrar sólo si está por ENCIMA. Control de signo.

    El resto —sizing por riesgo, stop del 45% por tramo, presupuesto marcado a
    mercado— es idéntico al motor, para que la única diferencia sea el corte.
    """
    idx = [i for i in señales_swing(dia, desde=DESDE)
           if (dia.bars[i][4] or 0) >= PISO]
    if not idx:
        return None
    cierre = dia.rth_close
    if not cierre:
        return None
    i_corte = dia.idx_en(corte_h) if corte_h is not None else None
    r_trade = RIESGO / 3.0

    detalle = []
    for i in idx:
        if len(detalle) >= MAXT:
            break
        p = dia.bars[i][4]
        if not p:
            continue
        # Presupuesto a mercado en ESTE minuto, igual que `motor.jornada`.
        equity = 0.0
        for t in detalle:
            if t["i_sal"] is not None and t["i_sal"] <= i:
                equity += t["pnl"]
            else:
                equity += t["acciones"] * (t["p_ent"] - p)
        if equity - r_trade < -RIESGO:
            break
        detalle.append({"acciones": r_trade / (p * STOP / 100.0), "p_ent": p,
                        "i_ent": i, "i_sal": None, "p_sal": None,
                        "pnl": 0.0, "motivo": None})
        # Se resuelve el tramo hasta su stop natural; el corte se aplica después,
        # porque decidirlo acá necesitaría saber el estado del corte antes de
        # tiempo.
        t = detalle[-1]
        p_stop = p * (1 + STOP / 100.0)
        for k in range(i + 1, len(dia.bars)):
            bk = dia.bars[k]
            if hora(bk) > CIERRE_RTH:
                break
            if bk[2] and bk[2] >= p_stop:
                t["i_sal"], t["p_sal"], t["motivo"] = k, p_stop, "stop"
                break
        if t["i_sal"] is None:
            t["p_sal"], t["motivo"] = cierre, "cierre"
        t["pnl"] = t["acciones"] * (p - t["p_sal"]) - t["acciones"] * COSTO_ACCION

    if not detalle:
        return None

    # ---- el corte, decidido con lo que se sabe EN ese minuto ----------------
    if i_corte is not None and modo:
        px = dia.bars[i_corte][4]
        vivos = [t for t in detalle
                 if t["i_ent"] < i_corte
                 and (t["i_sal"] is None or t["i_sal"] > i_corte)]
        if px and vivos:
            acc = sum(t["acciones"] for t in vivos)
            prom = sum(t["p_ent"] * t["acciones"] for t in vivos) / acc
            favor = 100.0 * (prom - px) / prom      # + = va a favor del short
            cortar = (modo == "siempre"
                      or (modo == "si_flojo" and favor < umbral)
                      or (modo == "si_bueno" and favor >= umbral))
            if cortar:
                for t in vivos:
                    t["i_sal"], t["p_sal"], t["motivo"] = i_corte, px, "corte"
                    t["pnl"] = (t["acciones"] * (t["p_ent"] - px)
                                - t["acciones"] * COSTO_ACCION)
                # Los tramos que entrarían DESPUES del corte no existen: el día
                # se cerró. Sin esto, el corte no cortaria nada.
                detalle = [t for t in detalle if t["i_ent"] <= i_corte]

    if not detalle:
        return None
    bruto = sum(t["pnl"] + t["acciones"] * COSTO_ACCION for t in detalle)
    com = sum(comision(t["acciones"]) for t in detalle)
    ev = []
    for t in detalle:
        ev.append((t["i_ent"], +t["acciones"]))
        ev.append((t["i_sal"] if t["i_sal"] is not None else 10 ** 9,
                   -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)
    return {"neto": bruto - com, "nominal": pico * cierre,
            "trades": len(detalle)}


def correr(dias, **kw):
    neto = nom = 0.0
    ses = tr = 0
    por_dia = {}
    for d in dias:
        r = jornada(d, **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    v = sorted(por_dia.values())
    return {"ses": ses, "tr": tr, "neto": neto,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0,
            "peor": v[0] if v else 0.0,
            "p05": v[max(0, int(0.05 * len(v)))] if v else 0.0}


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]

b = correr(pob)
print("\n  CORTAR A LAS X SI NO FUNCIONO\n")
print(f"  BASE: {b['ses']} ses · ${b['neto']:,.0f} · {b['ret']:.2f}% · "
      f"${b['por_ses']:.0f}/ses · peor ${b['peor']:,.0f} · p05 ${b['p05']:,.0f}")
print()
print("  {:<34} {:>5} {:>7} {:>10} {:>8} {:>9} {:>10} {:>9}".format(
    "variante", "ses", "trades", "neto", "ret/nom", "$/ses", "peor dia", "p05"))
print("  " + "-" * 100)

for h in (11.0, 12.0, 13.0, 14.0):
    hh = f"{int(h):02d}:00"
    filas = [
        (f"{hh} siempre (placebo)", dict(corte_h=h, modo="siempre")),
        (f"{hh} si no va a favor", dict(corte_h=h, modo="si_flojo", umbral=0.0)),
        (f"{hh} si no gano 5%", dict(corte_h=h, modo="si_flojo", umbral=5.0)),
        (f"{hh} si SI va a favor (control)", dict(corte_h=h, modo="si_bueno")),
    ]
    for etq, kw in filas:
        r = correr(pob, **kw)
        marca = ""
        if "no va" in etq or "no gano" in etq:
            pl = correr(pob, corte_h=h, modo="siempre")
            if r["por_ses"] > pl["por_ses"] and r["por_ses"] > b["por_ses"]:
                marca = "  <== gana a base Y placebo"
            elif r["por_ses"] > b["por_ses"]:
                marca = "  (gana a base, no al placebo)"
        print("  {:<34} {:>5} {:>7} ${:>9,.0f} {:>7.2f}% ${:>8.0f} ${:>9,.0f} ${:>8,.0f}{}".format(
            etq, r["ses"], r["tr"], r["neto"], r["ret"], r["por_ses"],
            r["peor"], r["p05"], marca))
    print()

print("  'peor dia' y 'p05' son lo que importa para la cuenta de fondeo: no")
print("  alcanza con ganar mas, hay que ganar mas SIN dias que la liquiden.")
