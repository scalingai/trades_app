#!/usr/bin/env python3
"""¿Conviene bajar el gap del censo de 25% a 20%?

LA PREGUNTA VIENE DE UN DIA PUNTUAL, Y ESO YA ES UNA ADVERTENCIA. El 2026-09-09
IRD gapeo +23%, quedo afuera por dos puntos y termino dando +$19. Bajar un
umbral porque el papel que quedo afuera gano es ajustar la regla al resultado.
Por eso esto NO se contesta con ese dia: se contesta con los 759 eventos de la
banda 20-25% que nunca se habian mirado, en los dos periodos del corte.

QUE COMPARA. La misma operativa —reclaim, sin corte, sin tope, riesgo $75 por
papel, sin stop— sobre dos poblaciones:

    25%   el censo de siempre
    20%   el censo mas la banda 20-25%

Y por separado la BANDA SOLA, que es lo unico realmente nuevo: si la banda no
se paga a si misma, bajar el umbral solo agrega ruido y dias operados.

    python test_umbral_gap.py
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# El umbral se prende ANTES de importar el motor: `universo()` elige el pickle
# de cache segun el umbral, y si se importa antes de setearlo lee el de 25%.
os.environ["SMALLCAPS_MIN_GAP"] = "20"

import motor  # noqa: E402
from chavineta import clasificar_apertura as _cl  # noqa: E402
from dias import hora  # noqa: E402
from motor import jornada, poblacion, universo  # noqa: E402
from sesion import señales_swing  # noqa: E402

DESDE, PISO, RIESGO, STOP = 10.0, 2.05, 75.0, 45.0
CORTE = motor.CORTE
TZ_MIN = 0.49


def sig(d):
    return [i for i in señales_swing(d, desde=DESDE) if (d.bars[i][4] or 0) >= PISO]


def gap_de(d):
    rth = [b for b in d.bars if hora(b) >= 9.5]
    if not rth or not d.prev_close:
        return None
    return (rth[0][1] / d.prev_close - 1.0) * 100.0


def correr(dias):
    """PnL por dia de cuenta, neto de la comision real del broker."""
    por_dia = defaultdict(float)
    n = 0
    for d in dias:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                    max_trades=40, corte_h=None, tope_usd=None, usar_stop=False)
        if not j:
            continue
        tr = j["detalle"]
        com = sum(2 * max(TZ_MIN, t["acciones"] * 0.005) for t in tr)
        por_dia[d.d] += j["pnl"] - com
        n += len(tr)
    return por_dia, n


def resumen(por_dia):
    dias = [por_dia[k] for k in sorted(por_dia)]
    if not dias:
        return {"bruto": 0.0, "ndias": 0, "peor": 0.0, "dd": 0.0, "verde": 0.0}
    pico = acum = dd = 0.0
    for x in dias:
        acum += x
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return {"bruto": sum(dias), "ndias": len(dias), "peor": min(dias), "dd": dd,
            "verde": 100 * sum(1 for x in dias if x > 0) / len(dias)}


print("  cargando el censo ampliado (gap >= 20%)...", flush=True)
todo = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                             min_dolar=0.0, max_float=47e6)
        if _cl(d, hasta=10.0) == "reclaim"]
for d in todo:
    d._gap = gap_de(d)
todo = [d for d in todo if d._gap is not None]
todo.sort(key=lambda d: (d.d, d.ticker))

viejo = [d for d in todo if d._gap >= 25.0]
banda = [d for d in todo if 20.0 <= d._gap < 25.0]
print(f"  {len(todo)} sesiones reclaim · {len(viejo)} del censo viejo · "
      f"{len(banda)} de la banda 20-25%\n")

grupos = {"censo 25% (el de hoy)": viejo,
          "censo 20% (ampliado)": todo,
          "SOLO la banda 20-25%": banda}

print(f"  {'poblacion':>24} {'ses':>5} {'dias':>5} {'tramos':>7} {'neto':>10} "
      f"{'$/dia':>8} {'peor dia':>9} {'drawdown':>10} {'verde':>7}")
print("  " + "-" * 96)
res = {}
for et, ds in grupos.items():
    pd, n = correr(ds)
    r = resumen(pd)
    res[et] = (pd, r)
    pdia = r["bruto"] / r["ndias"] if r["ndias"] else 0.0
    print(f"  {et:>24} {len(ds):>5} {r['ndias']:>5} {n:>7} {r['bruto']:>+10.0f} "
          f"{pdia:>+8.2f} {r['peor']:>+9.0f} {r['dd']:>+10.0f} {r['verde']:>6.0f}%")

print(f"\n  FUERA DE MUESTRA · corte {CORTE}\n")
print(f"  {'poblacion':>24} {'antes del corte':>17} {'desde el corte':>17}")
print("  " + "-" * 62)
for et in grupos:
    pd, _ = res[et]
    a = sum(v for k, v in pd.items() if k < CORTE)
    b = sum(v for k, v in pd.items() if k >= CORTE)
    print(f"  {et:>24} {a:>+17.0f} {b:>+17.0f}")

pd_b, r_b = res["SOLO la banda 20-25%"]
a = sum(v for k, v in pd_b.items() if k < CORTE)
b = sum(v for k, v in pd_b.items() if k >= CORTE)
print("\n  EL VEREDICTO se lee en la banda sola, que es lo unico nuevo:")
if r_b["bruto"] <= 0:
    print("    pierde plata -> NO bajar el umbral.")
elif a <= 0 or b <= 0:
    print("    gana en total pero NO replica en los dos periodos -> no alcanza.")
else:
    print("    gana en los dos periodos -> candidato real; falta ver si el")
    print("    drawdown y los dias operados de mas lo justifican.")
