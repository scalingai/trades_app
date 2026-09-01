#!/usr/bin/env python3
"""El peor dia. Es lo unico que decide si esto sobrevive en una cuenta fondeada.

UNA CUENTA DE FONDEO NO SE PIERDE POR RENTABILIDAD MEDIA, se pierde por un dia.
Los limites del plan son perdida diaria maxima y drawdown maximo: un solo dia
que los perfore liquida la cuenta y todo el retorno promedio deja de existir.

La piramide arma posiciones ocho veces mas grandes que la base. Con stop en
breakeven eso "no deberia" perder — pero breakeven no es una garantia: es un
precio, y en un papel que salta 10% en un minuto el precio se cruza sin pasar
por el medio. Este archivo mide cuanto se pierde el peor dia de cada variante.
"""
import statistics
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import COSTO_ACCION, jornada, poblacion, universo
from test_piramide import (MAXT, PODER_COMPRA, RIESGO, STOP, comision,
                           piramide, sig)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LIMITE_DIA, DRAWDOWN = -400.0, -1000.0

dias = universo()
POB = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]


def por_dia_base():
    acum = {}
    for d in POB:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                    max_trades=MAXT)
        if not j:
            continue
        b = j["pnl"]
        c = 0.0
        for t in j["detalle"]:
            b += t["acciones"] * COSTO_ACCION
            c += comision(t["acciones"])
        acum[d.d] = acum.get(d.d, 0.0) + b - c
    return acum


def por_dia_pir(gatillo, asegura, objetivo, reentrada):
    acum = {}
    for d in POB:
        r = piramide(d, riesgo=RIESGO, stop_pct=STOP, gatillo=gatillo,
                     asegura=asegura, max_tramos=MAXT, objetivo=objetivo,
                     reentrada=reentrada)
        if not r:
            continue
        acum[d.d] = acum.get(d.d, 0.0) + r["pnl"] - r["com"]
    return acum


def informe(nombre, acum):
    v = sorted(acum.values())
    peor = v[0] if v else 0.0
    p05 = v[max(0, int(0.05 * len(v)))] if v else 0.0
    rompe = sum(1 for x in v if x < LIMITE_DIA)
    ruina = sum(1 for x in v if x < DRAWDOWN)
    # Racha peor: la caida maxima del acumulado dia a dia, que es lo que mira
    # el drawdown de la cuenta y no la suma de dias sueltos.
    corr, pico, dd = 0.0, 0.0, 0.0
    for f in sorted(acum):
        corr += acum[f]
        pico = max(pico, corr)
        dd = min(dd, corr - pico)
    print("  {:<30} {:>6} ${:>9,.0f} ${:>9,.0f} {:>7} {:>7} ${:>10,.0f}".format(
        nombre, len(v), peor, p05, rompe, ruina, dd))


print("\n  EL PEOR DIA DE CADA VARIANTE\n")
print("  {:<30} {:>6} {:>11} {:>11} {:>7} {:>7} {:>12}".format(
    "variante", "dias", "peor dia", "p05", ">$400", ">$1000", "drawdown"))
print("  " + "-" * 92)

informe("BASE (tramos sueltos)", por_dia_base())
informe("piramide BE, sin objetivo", por_dia_pir(15.0, 0.0, None, False))
informe("piramide BE + obj 12%", por_dia_pir(15.0, 0.0, 12.0, True))
informe("piramide stop-profit +5%", por_dia_pir(15.0, 5.0, None, False))

print()
print("  '>$400' son los dias que perforan la perdida diaria del plan y '>$1000'")
print("  los que se llevan la cuenta entera. 'drawdown' es la peor caida del")
print("  acumulado, que es lo que mide la cuenta — no la suma de dias sueltos.")
