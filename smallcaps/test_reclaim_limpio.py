#!/usr/bin/env python3
"""El hallazgo del reclaim, verificado con TODAS las fugas tapadas.

Dos fugas encontradas hoy, las dos por subagentes distintos:
  1. `clasificar_apertura` etiqueta con barras hasta las 10:00, pero las
     senales entran desde las 09:45. 22-27% de los trades saben el futuro.
  2. `ratio_volumen` compara el volumen del DIA COMPLETO contra el dia previo.
     A las 09:30 ese numero no existe. Mismo problema que `min_dolar`, que si
     estaba documentado.

Aca se tapan las dos a la vez, de la forma mas conservadora posible:
  · etiqueta a las 10:00 Y entradas desde las 10:00 (nunca antes de saber)
  · sin filtro de ratio de volumen (min_ratio_vol=0)
  · sin filtro de dolar del dia (min_dolar=0)

Lo que sobreviva a esto es lo unico que se puede operar de verdad.
"""
import sys, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, evaluar, linea, encabezado, correlacion
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl

# etiqueta a las 10:00 (la definicion original, con barras suficientes)
motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
desde10 = lambda d: señales_swing(d, desde=10.0)

dias = universo()
LIMPIO = {"min_ratio_vol": 0.0, "min_dolar": 0.0}
print("  TODO CON ENTRADAS DESDE LAS 10:00, SIN FILTROS DEL DIA COMPLETO\n")
print(encabezado()); print("  " + "-"*104)
R = {}
CASOS = [
  ("fade·exp150",   "fade",    {"min_expansion":150, **LIMPIO}),
  ("fade·exp100",   "fade",    {"min_expansion":100, **LIMPIO}),
  ("reclaim·exp100","reclaim", {"min_expansion":100, **LIMPIO}),
  ("reclaim·exp150","reclaim", {"min_expansion":150, **LIMPIO}),
  ("reclaim·todo",  "reclaim", {"min_expansion":0,   **LIMPIO}),
  ("sin-apertura",  None,      {"min_expansion":150, **LIMPIO}),
  ("fade·conRV",    "fade",    {"min_expansion":150, "min_dolar":0.0}),
]
for nom, ap, pob in CASOS:
    r = evaluar(f"limpio·{nom}", desde10, dias=dias, familia="limpio",
                stop=45.0, pob=pob, apertura=ap,
                notas="entradas 10:00, sin datos del dia completo")
    if "error" in r: print(f"  {nom:<38} {r['error']}"); continue
    R[nom] = r; print(linea(r))

print("\n  CORRELACION Y COINCIDENCIA DE DIAS MALOS\n")
ns = list(R)
print("        " + " ".join(f"{n[:13]:>14}" for n in ns))
for a in ns:
    fila=[]
    for b in ns:
        c = 1.0 if a==b else correlacion(R[a]["serie"], R[b]["serie"])
        fila.append(f"{c:>14.2f}" if c is not None else f"{'sin solape':>14}")
    print(f"  {a[:6]:>6} " + " ".join(fila))

print("\n  LO QUE DECIDE UNA CUENTA DE FONDEO: dias en que las DOS pierden\n")
base = R.get("fade·exp150")
if base:
    for nom in ns:
        if nom == "fade·exp150": continue
        o = R[nom]
        com = set(base["serie"]) & set(o["serie"])
        juntos = sum(1 for d in com if base["serie"][d] < 0 and o["serie"][d] < 0)
        peor = min((base["serie"][d] + o["serie"][d] for d in com), default=0)
        print(f"  fade·exp150 + {nom:<16} comparten {len(com):>3} fechas · "
              f"ambas en rojo {juntos:>3} · peor jornada conjunta {peor:+.2f} R")
