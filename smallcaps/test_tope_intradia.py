#!/usr/bin/env python3
"""¿Un tope duro de pérdida diaria salva la variante que gana más?

**LA PREGUNTA DE AGUS.** La regla que aguanta a los perdedores con rango ancho
gana $172/sesión contra $110 del corte de hoy, pero su drawdown es -$3.180
contra un tope de cuenta de $1.000. "¿No le podemos poner otra salida dura que
no rompa esa regla de 1000?"

**POR QUE VALE LA PENA MEDIRLO AUNQUE YA HAYA UN ANTECEDENTE EN CONTRA.**
`test_caja_diaria.py` midió que forzar el cierre diario EMPEORA el drawdown de
la base (-$3.684 a -$3.788), porque el minuto en que tu equity toca el piso es,
por definición, el peor precio del día. Ese antecedente está bien medido — pero
es sobre otra estrategia:

    base            3 de 172 días peores que -$400 · exceso total -$39
    rango < 7,70%  14 de 172 días peores que -$400 · exceso total -$1.672

En la base el tope casi no ata nada, así que lo único que hace es empeorar la
ejecución de tres días. Acá ata catorce veces y hay $1.672 de exceso sobre la
mesa. Es otra pregunta con el mismo nombre.

Y el drawdown de esta variante NO es un goteo: son tres bombas. -$1.055, -$944
y -$874 explican $2.873 de los $3.180, en una racha de cinco días operados.

**COMO SE APLICA EL TOPE.** Barra a barra, con la equity marcada a mercado —lo
cerrado a valor final y lo abierto contra el precio de esa barra—. En el primer
minuto en que la equity toca -`tope`, se cierra TODO a ese precio y el día
termina. Es lo que hace la plataforma de fondeo cuando perforás el límite
diario, así que no es una regla que elegimos: es la que nos van a aplicar.

Se mide contra el corte de las 11:00, que es el campeón, y en las dos mitades.

    python test_tope_intradia.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, poblacion, universo
from sesion import señales_swing
from test_salida_rango_seco import (MAXT, PISO, RIESGO, STOP, DESDE,
                                    comision, rangos)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_H, UMBRAL = 11.0, 5.0


def jornada(dia, *, rango=None, modo="siempre", seco=None, tope=None):
    """Las entradas de siempre, con dos salidas duras posibles.

    `modo`  — "nunca" sostiene al cierre · "siempre" corta todo perdedor a las
              11:00 (hoy) · "seco" corta sólo los que además dejaron de moverse.
    `tope`  — dólares de pérdida marcada a mercado que terminan el día.

    Las dos pueden disparar el mismo día; gana la que llegue PRIMERO, que es lo
    que pasa en la realidad.
    """
    idx = [i for i in señales_swing(dia, desde=DESDE)
           if (dia.bars[i][4] or 0) >= PISO]
    if not idx:
        return None
    cierre = dia.rth_close
    if not cierre:
        return None
    r_trade = RIESGO / 3.0

    detalle = []
    for i in idx:
        if len(detalle) >= MAXT:
            break
        p = dia.bars[i][4]
        if not p:
            continue
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

    # ---- donde dispara el corte de las 11:00 -------------------------------
    i_corte = None
    if modo != "nunca":
        i_c = dia.idx_en(CORTE_H)
        px = dia.bars[i_c][4] if i_c is not None else None
        vivos = [t for t in detalle if t["i_ent"] < i_c
                 and (t["i_sal"] is None or t["i_sal"] > i_c)] if px else []
        if px and vivos:
            acc = sum(t["acciones"] for t in vivos)
            prom = sum(t["p_ent"] * t["acciones"] for t in vivos) / acc
            if 100.0 * (prom - px) / prom < UMBRAL:
                r = rango[i_c] if rango else None
                if modo == "siempre" or (modo == "seco" and r is not None
                                         and r < seco):
                    i_corte = i_c

    # ---- donde dispara el tope duro ----------------------------------------
    # Barra a barra con la equity a mercado. Es la unica forma honesta: el
    # limite no lo toca el PnL final del dia, lo toca el peor minuto.
    i_tope = None
    if tope is not None:
        for k in range(detalle[0]["i_ent"], len(dia.bars)):
            bk = dia.bars[k]
            if hora(bk) > CIERRE_RTH:
                break
            px = bk[4]
            if not px:
                continue
            eq = 0.0
            for t in detalle:
                if t["i_ent"] > k:
                    continue
                if t["i_sal"] is not None and t["i_sal"] <= k:
                    eq += t["pnl"]
                else:
                    eq += t["acciones"] * (t["p_ent"] - px)
            if eq <= -tope:
                i_tope = k
                break

    # Gana la que llegue primero.
    cand = [x for x in (i_corte, i_tope) if x is not None]
    i_salida = min(cand) if cand else None
    topeado = i_tope is not None and i_salida == i_tope

    if i_salida is not None:
        px = dia.bars[i_salida][4]
        if px:
            for t in detalle:
                if t["i_ent"] < i_salida and (t["i_sal"] is None
                                              or t["i_sal"] > i_salida):
                    t["i_sal"], t["p_sal"] = i_salida, px
                    t["motivo"] = "tope" if topeado else "corte"
                    t["pnl"] = (t["acciones"] * (t["p_ent"] - px)
                                - t["acciones"] * COSTO_ACCION)
            detalle = [t for t in detalle if t["i_ent"] <= i_salida]

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
            "trades": len(detalle), "topeado": topeado}


def correr(dias, rango_de, **kw):
    neto = nom = 0.0
    ses = tr = top = 0
    por_dia = {}
    for d in dias:
        r = jornada(d, rango=rango_de.get(d.d + d.ticker), **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        top += 1 if r["topeado"] else 0
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    acum = pico = dd = 0.0
    for f in sorted(por_dia):
        acum += por_dia[f]
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    peor = min(por_dia.values()) if por_dia else 0.0
    return {"ses": ses, "tr": tr, "neto": neto, "dd": dd, "top": top,
            "peor": peor, "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0}


def fila(etq, r, extra=""):
    print("  {:<30} {:>5} ${:>9,.0f} {:>7.2f}% ${:>7.0f} ${:>10,.0f} ${:>9,.0f} {}"
          .format(etq, r["ses"], r["neto"], r["ret"], r["por_ses"], r["dd"],
                  r["peor"], extra))


def bloque(dias, rango_de, titulo):
    print(f"\n  {titulo}  ({len(dias)} días)")
    print("  {:<30} {:>5} {:>10} {:>8} {:>8} {:>11} {:>10}".format(
        "variante", "ses", "neto", "ret/nom", "$/ses", "drawdown", "peor día"))
    print("  " + "-" * 96)
    fila("corta SIEMPRE 11:00  (hoy)", correr(dias, rango_de, modo="siempre"))
    fila("rango < 7,70%, sin tope", correr(dias, rango_de, modo="seco", seco=7.7))
    print()
    for tope in (300, 400, 500, 700, 1000):
        r = correr(dias, rango_de, modo="seco", seco=7.7, tope=tope)
        fila(f"rango < 7,70% + tope ${tope}", r,
             f"topea {r['top']} días")
    print()
    for tope in (400, 700):
        r = correr(dias, rango_de, modo="siempre", tope=tope)
        fila(f"corte de hoy + tope ${tope}", r, f"topea {r['top']} días")


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]
pob.sort(key=lambda d: d.d)
rango_de = {d.d + d.ticker: rangos(d) for d in pob}

print("\n  ¿UN TOPE DURO DE PERDIDA DIARIA SALVA LA VARIANTE QUE GANA MAS?")
print(f"  {len(pob)} días reclaim · el tope cierra TODO en el primer minuto en")
print("  que la equity marcada a mercado lo toca. No es una regla que elegimos:")
print("  es la que la plataforma de fondeo aplica cuando perforás el límite.")

bloque(pob, rango_de, "TODA LA MUESTRA")
mitad = len(pob) // 2
bloque(pob[:mitad], rango_de, f"PRIMERA MITAD ({pob[0].d} a {pob[mitad - 1].d})")
bloque(pob[mitad:], rango_de, f"SEGUNDA MITAD ({pob[mitad].d} a {pob[-1].d})")

print("\n  COMO SE LEE")
print("  El tope sirve si baja el drawdown POR DEBAJO de -$1.000 sin comerse la")
print("  ventaja de plata. Ojo con la trampa: topear cierra en el peor minuto")
print("  del día, así que puede bajar el peor día y NO bajar el drawdown.")
