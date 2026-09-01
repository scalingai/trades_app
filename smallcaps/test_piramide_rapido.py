#!/usr/bin/env python3
"""Cerrar antes: si el tamaño se cuadruplicó, alcanza un cuarto del movimiento.

LA IDEA DE AGUS, SEGUNDA PARTE. Achicar el stop dio cuatro veces el tamaño. Con
cuatro veces el tamaño hace falta un cuarto del recorrido para la misma plata —
asi que se puede salir antes, y volver a entrar con el profit ya tomado.

QUE SE MIDE ACA, Y QUE NO. Se mide plata neta, retorno sobre el nominal, y el
TAMAÑO de la posicion, porque el tamaño es lo que decide si esto se puede
ejecutar: la variante sin objetivo llegaba al 9% del volumen de un minuto, que
es el borde donde el fill al precio exacto deja de ser creible.
"""
import statistics
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, jornada, poblacion, universo
from test_piramide import (MAXT, PISO, PODER_COMPRA, RIESGO, STOP, comision,
                           piramide, sig)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def vol_min(dia):
    v = [b[5] for b in dia.bars if b[5] and 9.5 <= hora(b) <= CIERRE_RTH]
    return statistics.median(v) if v else 0.0


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


dias = universo()
POB = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]
VM = {d.d + d.ticker: vol_min(d) for d in POB}


def correr(gatillo, asegura, objetivo, reentrada):
    bruto = com = nom = 0.0
    ses = tr = 0
    accs, fracs = [], []
    cierres = {"stop": 0, "objetivo": 0, "cierre": 0}
    for d in POB:
        r = piramide(d, riesgo=RIESGO, stop_pct=STOP, gatillo=gatillo,
                     asegura=asegura, max_tramos=MAXT, objetivo=objetivo,
                     reentrada=reentrada)
        if not r:
            continue
        bruto += r["pnl"]
        com += r["com"]
        nom += r["pico"] * (d.rth_close or 0)
        tr += r["entradas"]
        ses += 1
        accs.append(r["pico"])
        vm = VM.get(d.d + d.ticker) or 0
        if vm:
            fracs.append(100.0 * r["pico"] / vm)
        for s in r["salidas"]:
            cierres[s["motivo"]] = cierres.get(s["motivo"], 0) + 1
    neto = bruto - com
    return {"ses": ses, "tr": tr, "neto": neto,
            "ret": 100 * neto / nom if nom else 0.0,
            "acc90": pct(accs, .9), "frac90": pct(fracs, .9),
            "c": cierres}


def base():
    bruto = com = nom = 0.0
    ses = tr = 0
    for d in POB:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                    max_trades=MAXT)
        if not j:
            continue
        b = j["pnl"]
        for t in j["detalle"]:
            b += t["acciones"] * COSTO_ACCION
            com += comision(t["acciones"])
        bruto += b
        nom += j["nominal"]
        tr += j["trades"]
        ses += 1
    neto = bruto - com
    return {"ses": ses, "tr": tr, "neto": neto,
            "ret": 100 * neto / nom if nom else 0.0,
            "acc90": 992, "frac90": 1.0, "c": {}}


print("\n  CERRAR ANTES CON POSICION MAS GRANDE\n")
print("  {:<28} {:>6} {:>11} {:>9} {:>9} {:>8} {:>18}".format(
    "variante", "adds", "neto", "ret/nom", "acc p90", "% min", "stop/obj/cierre"))
print("  " + "-" * 100)

b = base()
print("  {:<28} {:>6} ${:>10,.0f} {:>8.2f}% {:>9.0f} {:>7.0f}% {:>18}".format(
    "BASE (tramos sueltos)", b["tr"], b["neto"], b["ret"], b["acc90"],
    b["frac90"], "—"))

for objetivo, reent in ((None, False), (3.0, True), (5.0, True), (8.0, True),
                        (12.0, True), (5.0, False)):
    r = correr(15.0, 0.0, objetivo, reent)
    etq = ("sin objetivo" if objetivo is None
           else f"obj {objetivo:.0f}%" + (" + reentra" if reent else " sin reentrar"))
    c = r["c"]
    print("  {:<28} {:>6} ${:>10,.0f} {:>8.2f}% {:>9.0f} {:>7.0f}% {:>6}/{:<5}/{:<5}".format(
        "gat 15%->BE · " + etq, r["tr"], r["neto"], r["ret"], r["acc90"],
        r["frac90"], c.get("stop", 0), c.get("objetivo", 0), c.get("cierre", 0)))

print()
print("  'acc p90' y '% min' son el tamaño: la posicion contra el volumen de un")
print("  minuto tipico. Arriba de ~10% el fill al precio exacto es ficcion.")
