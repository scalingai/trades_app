#!/usr/bin/env python3
"""¿La posición que arma la pirámide se puede ejecutar de verdad?

EL SIMULADOR LLENA TODA LA POSICION AL PRECIO EXACTO DEL STOP, sin deslizamiento.
Esa licencia es tolerable con 40 acciones y es una fantasia con 6000: en un papel
que opera 400.000 acciones en el dia, salir de 6000 en el minuto en que se toca
el stop te mueve el precio vos mismo.

Este archivo NO mide rentabilidad. Mide TAMAÑO: cuantas acciones llega a tener
la posicion y que fraccion del volumen representa. Si ese numero es grande, el
resultado de `test_piramide.py` no describe nada que se pueda operar.
"""
import statistics
import sys
sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import jornada, poblacion, universo
from sesion import señales_swing
from test_piramide import PODER_COMPRA, RIESGO, STOP, MAXT, PISO, piramide, sig

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def volumen_minuto_tipico(dia):
    """Mediana del volumen por minuto en la rueda."""
    v = [b[5] for b in dia.bars if b[5] and 9.5 <= hora(b) <= CIERRE_RTH]
    return statistics.median(v) if v else 0.0


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


dias = universo()
pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                max_float=47e6)
pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]

print("\n  QUE TAMAÑO ARMA CADA VARIANTE, Y SI ENTRA EN EL MERCADO\n")
print("  {:<24} {:>10} {:>10} {:>12} {:>14}".format(
    "variante", "acc p50", "acc p90", "nominal p90", "% del minuto p90"))
print("  " + "-" * 76)

filas = []

# BASE: el pico simultaneo del motor actual.
acc_b, nom_b, frac_b = [], [], []
for d in pob:
    j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                max_trades=MAXT)
    if not j:
        continue
    ev = []
    for t in j["detalle"]:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)
    vm = volumen_minuto_tipico(d)
    acc_b.append(pico)
    nom_b.append(pico * (d.rth_close or 0))
    if vm:
        frac_b.append(100.0 * pico / vm)
filas.append(("BASE (tramos sueltos)", acc_b, nom_b, frac_b))

for gat, aseg, etq in ((15.0, 0.0, "gatillo 15% -> BE"),
                       (20.0, 0.0, "gatillo 20% -> BE"),
                       (15.0, 5.0, "gatillo 15% -> +5%")):
    acc, nom, frac = [], [], []
    for d in pob:
        r = piramide(d, riesgo=RIESGO, stop_pct=STOP, gatillo=gat,
                     asegura=aseg, max_tramos=MAXT)
        if not r:
            continue
        vm = volumen_minuto_tipico(d)
        acc.append(r["pico"])
        nom.append(r["pico"] * (d.rth_close or 0))
        if vm:
            frac.append(100.0 * r["pico"] / vm)
    filas.append((etq, acc, nom, frac))

for etq, acc, nom, frac in filas:
    print("  {:<24} {:>10.0f} {:>10.0f} ${:>11,.0f} {:>13.0f}%".format(
        etq, pct(acc, .5), pct(acc, .9), pct(nom, .9), pct(frac, .9)))

print()
print("  '% del minuto' = las acciones de la posicion sobre el volumen MEDIANO")
print("  de un minuto de ese papel. Arriba de ~10% el fill al precio exacto")
print("  del stop deja de ser una licencia y pasa a ser ficcion.")
