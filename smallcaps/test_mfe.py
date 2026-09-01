#!/usr/bin/env python3
"""¿Hasta dónde llegan a favor estos trades? El dato para la línea de proyección.

NO ES UN TAKE PROFIT. El sistema no tiene: se midió once veces que asegurar
empeora el resultado, y sostener al cierre quedó como la regla. Esto es otra
cosa — cuánto llegó a moverse a favor un trade típico antes de terminar — y
sirve para dibujar en la pantalla hasta dónde es razonable esperar que llegue,
que es distinto de dónde hay que salir.

`mfe_pct` ya lo devuelve `_trade`, medido sobre las barras posteriores a la
entrada. Acá sólo se agrega por percentiles.
"""
import statistics
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT = 400.0, 2.0, 45.0, 40


def sig(d):
    return [i for i in señales_swing(d, desde=10.0)
            if (d.bars[i][4] or 0) >= PISO]


dias = universo()
pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                max_float=47e6)
pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]

mfes, maes, por_dia = [], [], []
for d in pob:
    j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                max_trades=MAXT)
    if not j:
        continue
    m = [t["mfe_pct"] for t in j["detalle"]]
    mfes.extend(m)
    maes.extend(t["mae_pct"] for t in j["detalle"])
    if m:
        por_dia.append(max(m))

def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]

print(f"\n  HASTA DONDE LLEGAN A FAVOR  ({len(mfes)} trades, {len(por_dia)} sesiones)\n")
print("  POR TRADE (excursión máxima a favor, en % del precio de entrada)")
for q in (0.25, 0.50, 0.75, 0.90):
    print(f"    p{int(q*100):<3} {pct(mfes, q):>6.2f}%")
print(f"    media  {statistics.mean(mfes):>6.2f}%")
print()
print("  POR SESION (el mejor tramo del día)")
for q in (0.25, 0.50, 0.75):
    print(f"    p{int(q*100):<3} {pct(por_dia, q):>6.2f}%")
print()
print("  EN CONTRA (MAE), para contrastar con el stop de 45%")
for q in (0.25, 0.50, 0.75, 0.90):
    print(f"    p{int(q*100):<3} {pct([-x for x in maes], q):>6.2f}%")
print()
print("  La mediana del MFE es lo que se dibuja como proyección: es donde")
print("  llegó la mitad de los trades, no un objetivo al que haya que salir.")
