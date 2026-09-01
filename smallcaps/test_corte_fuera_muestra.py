#!/usr/bin/env python3
"""El corte de las 11:00, partido en dos mitades del tiempo.

POR QUE ESTE ARCHIVO EXISTE. Es UNA medicion sobre las mismas 209 sesiones que
este proyecto viene exprimiendo desde el principio, y ya van ~450 estrategias
probadas sobre ellas. La probabilidad de que algo se vea bien por azar es alta.

El minimo indispensable antes de decir "esta es la estrategia": que el efecto
aparezca en las DOS mitades del tiempo por separado. No prueba que funcione en
el futuro —nada lo prueba— pero descarta que sea un artefacto de un tramo.
"""
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo
from test_corte_por_hora import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

dias = universo()
POB = sorted([d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                   min_dolar=0.0, max_float=47e6)
              if _cl(d, hasta=10.0) == "reclaim"], key=lambda d: d.d)
CORTE = len(POB) // 2
MITADES = [("P1", POB[:CORTE]), ("P2", POB[CORTE:]), ("todo", POB)]


def medir(dias_, **kw):
    neto = nom = 0.0
    ses = 0
    por_dia = {}
    for d in dias_:
        r = jornada(d, **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    corr = pico = dd = 0.0
    for f in sorted(por_dia):
        corr += por_dia[f]
        pico = max(pico, corr)
        dd = min(dd, corr - pico)
    return {"ses": ses, "neto": neto, "dd": dd,
            "ret": 100 * neto / nom if nom else 0.0,
            "peor": min(por_dia.values()) if por_dia else 0.0}


VARIANTES = [
    ("BASE (sostener al cierre)", {}),
    ("11:00 si no gano 5%", dict(corte_h=11.0, modo="si_flojo", umbral=5.0)),
    ("11:00 si no va a favor", dict(corte_h=11.0, modo="si_flojo", umbral=0.0)),
]

print("\n  EL CORTE DE LAS 11:00 EN LAS DOS MITADES DEL TIEMPO\n")
print("  {:<28} {:>6} {:>6} {:>10} {:>9} {:>10} {:>11}".format(
    "variante", "mitad", "ses", "neto", "ret/nom", "peor dia", "drawdown"))
print("  " + "-" * 86)
for nombre, kw in VARIANTES:
    for etq, sub in MITADES:
        m = medir(sub, **kw)
        print("  {:<28} {:>6} {:>6} ${:>9,.0f} {:>8.2f}% ${:>9,.0f} ${:>10,.0f}".format(
            nombre if etq == "P1" else "", etq, m["ses"], m["neto"], m["ret"],
            m["peor"], m["dd"]))
    print()
print("  Lo que hay que mirar: si el drawdown mejora en LAS DOS mitades. Que")
print("  mejore en una sola es lo que hace cualquier cosa probada 450 veces.")
