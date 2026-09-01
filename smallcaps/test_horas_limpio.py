#!/usr/bin/env python3
"""Las ventanas horarias, remedidas SIN el look-ahead de la apertura.

El hallazgo del subagente —"el edge se concentra entre 09:30 y 10:00"— es
sospechoso justo por su forma: el sesgo que encontramos vive en ese mismo tramo.
`clasificar_apertura` miraba hasta las 10:00 para etiquetar el dia como "fade",
asi que entrar entre 09:30 y 10:00 en dias etiquetados fade es, literalmente,
entrar sabiendo como termino esa media hora.

Aca se remide de dos formas, las dos limpias:
  · sin filtro de apertura (apertura=None): no hay etiqueta, no hay sesgo posible
  · con etiqueta a las 09:45, y entradas SOLO desde las 09:45

Si el gradiente horario sobrevive, era real. Si se aplana, era el sesgo.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from motor import universo, evaluar, linea, encabezado, correlacion
from sesion import señales_swing
from dias import hora

dias = universo()
VENT = [("0930-1000", 9.5, 10.0), ("1000-1100", 10.0, 11.0),
        ("1100-1230", 11.0, 12.5), ("1230-1400", 12.5, 14.0),
        ("1400-1530", 14.0, 15.5), ("manana", 9.5, 11.0),
        ("post1100", 11.0, 16.0), ("dia", 9.5, 16.0)]

def sig(desde, hasta):
    return lambda d: [i for i in señales_swing(d, desde=9.5, hasta=15.9)
                      if desde <= hora(d.bars[i]) < hasta]

print("  A) SIN FILTRO DE APERTURA — cero look-ahead posible\n")
print(encabezado()); print("  " + "-"*104)
res = {}
for nom, a, b in VENT:
    r = evaluar(f"horaL·{nom}", sig(a, b), dias=dias, familia="hora-limpia",
                stop=45.0, pob={"min_expansion": 150}, apertura=None,
                notas=f"ventana {nom}, sin etiqueta de apertura")
    if "error" not in r:
        res[nom] = r; print(linea(r))

print("\n  B) CON ETIQUETA A LAS 09:45, entradas desde 09:45\n")
print(encabezado()); print("  " + "-"*104)
for nom, a, b in VENT:
    if a < 9.75: a = 9.75
    if a >= b: continue
    r = evaluar(f"horaF·{nom}", sig(a, b), dias=dias, familia="hora-fade",
                stop=45.0, pob={"min_expansion": 150}, apertura="fade",
                notas=f"ventana {nom}, etiqueta 09:45")
    if "error" not in r: print(linea(r))

print("\n  C) CORRELACION entre ventanas limpias\n")
ns = [n for n, _, _ in VENT if n in res and n not in ("dia",)]
print("       " + " ".join(f"{n[:9]:>10}" for n in ns))
for a in ns:
    fila = []
    for b in ns:
        c = 1.0 if a == b else correlacion(res[a]["serie"], res[b]["serie"])
        fila.append(f"{c:>10.2f}" if c is not None else f"{'—':>10}")
    print(f"  {a[:9]:>5} " + " ".join(fila))
