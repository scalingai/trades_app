#!/usr/bin/env python3
"""Cuando el corte dispara, ¿que nos perdimos? La prima del seguro, dia por dia.

EL 31 DE AGOSTO EL CORTE COSTO $1.138 EN UNA SOLA SESION. WETO venia en contra a
las 11:00 —el sistema habia shorteado seis veces mientras SUBIA— y el corte
cerro todo en $13,00. Despues el papel se derrumbo a $5,87: un -58% desde el
maximo, exactamente el dia para el que existe la estrategia.

La pregunta que abre eso no es "el corte sirve o no" —eso ya esta medido, es lo
unico que hace la cuenta sobrevivir— sino SI ESTA BIEN CALIBRADO. Si la mayoria
de los dias cortados eran perdedores de verdad, el seguro es barato. Si la mitad
eran WETOs, es demasiado romo y hay margen para afinarlo.
"""
import statistics
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import COSTO_ACCION, jornada, poblacion, universo
from cuentas import CORTE_H, CORTE_UMBRAL, MAXT, RIESGO_PAPEL, STOP, comision, sig

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"): _s.reconfigure(encoding="utf-8", errors="replace")


def neto(d, **kw):
    j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO_PAPEL,
                max_trades=MAXT, **kw)
    if not j:
        return None, None
    n = j["pnl"]
    for t in j["detalle"]:
        n += t["acciones"] * COSTO_ACCION - comision(t["acciones"])
    return n, j


pob = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]

cortados, no_cortados = [], []
for d in pob:
    con, jc = neto(d, corte_h=CORTE_H, corte_umbral=CORTE_UMBRAL)
    sin, _ = neto(d)
    if con is None or sin is None:
        continue
    if any(t["motivo"] == "corte" for t in jc["detalle"]):
        cortados.append((d, con, sin, sin - con))
    else:
        no_cortados.append((d, con, sin))

cortados.sort(key=lambda x: -x[3])
n = len(cortados)
print(f"\n  EL CORTE DISPARO EN {n} DE {len(pob)} SESIONES ({100*n/len(pob):.0f}%)\n")

perdidos = [x[3] for x in cortados]
salvados = [x for x in perdidos if x < 0]
costados = [x for x in perdidos if x > 0]
print(f"  De esas {n}:")
print(f"    en {len(costados)} el corte COSTO plata  (total ${sum(costados):>9,.0f})")
print(f"    en {len(salvados)} el corte SALVO plata  (total ${-sum(salvados):>9,.0f})")
print(f"    neto de la prima: ${-sum(perdidos):>+9,.0f}")
print()
print(f"    mediana de lo que costo/salvo cada corte: ${statistics.median(perdidos):+,.0f}")
print(f"    peor caso (lo que mas costo): ${max(perdidos):+,.0f}")
print(f"    mejor caso (lo que mas salvo): ${min(perdidos):+,.0f}")

print("\n  LOS 8 QUE MAS COSTARON — los WETO\n")
print("  {:<7} {:<12} {:>9} {:>9} {:>10} {:>9}".format(
    "papel", "fecha", "con corte", "sin corte", "costo", "cierre%"))
print("  " + "-" * 62)
for d, con, sin, dif in cortados[:8]:
    mov = 100 * (d.rth_close - d.prev_close) / d.prev_close
    print("  {:<7} {:<12} ${:>8,.0f} ${:>8,.0f} ${:>9,.0f} {:>8.0f}%".format(
        d.ticker, d.d, con, sin, dif, mov))

print("\n  LOS 8 QUE MAS SALVARON\n")
print("  {:<7} {:<12} {:>9} {:>9} {:>10} {:>9}".format(
    "papel", "fecha", "con corte", "sin corte", "salvo", "cierre%"))
print("  " + "-" * 62)
for d, con, sin, dif in cortados[-8:]:
    mov = 100 * (d.rth_close - d.prev_close) / d.prev_close
    print("  {:<7} {:<12} ${:>8,.0f} ${:>8,.0f} ${:>9,.0f} {:>8.0f}%".format(
        d.ticker, d.d, con, sin, -dif, mov))
