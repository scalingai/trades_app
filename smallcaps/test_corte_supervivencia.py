#!/usr/bin/env python3
"""¿Cuál de estas variantes SOBREVIVE en una cuenta de fondeo?

`test_corte_por_hora.py` mostro que cortar los trades que a media rueda no
funcionaron NO gana mas plata que sostener al cierre —$169 contra $175 por
sesion en el mejor caso— pero baja el peor dia de $-1.618 a $-505.

En una cuenta normal eso seria un mal negocio: menos plata por menos riesgo que
no hacia falta. En una cuenta DE FONDEO es al reves, porque el riesgo no es
simetrico: un dia que perfora el drawdown no te cuesta ese dia, te cuesta la
cuenta y todo lo que venia despues.

Este archivo mide lo unico que decide eso: la peor caida del acumulado (que es
lo que mira el plan) y cuantas veces se hubiera liquidado la cuenta.
"""
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo
from test_corte_por_hora import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LIM_DIA, LIM_DD = -400.0, -1000.0

dias = universo()
POB = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]


def curva(**kw):
    por_dia = {}
    for d in POB:
        r = jornada(d, **kw)
        if r:
            por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    return por_dia


def informe(nombre, por_dia):
    v = list(por_dia.values())
    if not v:
        return
    # Drawdown del acumulado, que es lo que mide el plan — no la suma de dias
    # sueltos.
    # Drawdown desde el pico, que es lo que mide el plan. Se saco una columna
    # de "liquidaciones" que daba 0 en todas las variantes: la logica de reset
    # estaba mal pensada, y un numero en el que no confio es peor que ninguno.
    corr = pico = dd = 0.0
    for f in sorted(por_dia):
        corr += por_dia[f]
        pico = max(pico, corr)
        dd = min(dd, corr - pico)
    total = sum(v)
    # Con el riesgo a la mitad, todo escala a la mitad: es la palanca real
    # para meter una variante debajo del tope de drawdown del plan.
    print("  {:<32} ${:>9,.0f} {:>8} {:>8} ${:>10,.0f} ${:>11,.0f} {:>9}".format(
        nombre, total, sum(1 for x in v if x < LIM_DIA),
        sum(1 for x in v if x < LIM_DD), dd, dd / 2,
        "si" if dd / 2 > LIM_DD else "NO"))


print("\n  QUE SOBREVIVE EN UNA CUENTA DE FONDEO\n")
print("  {:<32} {:>10} {:>8} {:>8} {:>11} {:>12} {:>9}".format(
    "variante", "neto", ">$400", ">$1000", "drawdown", "dd a 1/2", "sobrevive"))
print("  " + "-" * 96)

informe("BASE (sostener al cierre)", curva())
for h in (11.0, 12.0, 13.0):
    informe(f"{int(h):02d}:00 si no va a favor",
            curva(corte_h=h, modo="si_flojo", umbral=0.0))
    informe(f"{int(h):02d}:00 si no gano 5%",
            curva(corte_h=h, modo="si_flojo", umbral=5.0))

print()
print("  'dd a 1/2' es el drawdown con la mitad del riesgo por sesion ($200 en")
print("  vez de $400): todo escala lineal. 'sobrevive' es si ese numero entra")
print("  en el tope de $-1.000 del plan — que es la pregunta que decide.")
