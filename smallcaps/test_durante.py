#!/usr/bin/env python3
"""¿Lo que pasa DURANTE el trade dice si se va a seguir derrumbando o revertir?

LA IDEA DE AGUS, Y POR QUE ES DISTINTA A TODO LO ANTERIOR. Los doce intentos de
salida que fallaron eran MECANICOS: objetivo fijo, trailing, breakeven. Todos
salen por el mismo criterio siempre, sin mirar nada. Esto es otra cosa: leer el
estado del papel en el minuto t y, si la probabilidad de que siga cayendo bajo,
recien ahi asegurar.

Y es distinta al filtro de EDGAR que acaba de morir: aquel elegia QUE dia
operar antes de entrar; este elige CUANDO salir de un dia en el que ya estas.

QUE SE MIDE. Para cada minuto con posicion abierta, se calculan rasgos con
barras HASTA ESE MINUTO, y se mide el movimiento que viene DESPUES, del minuto t
al cierre. Si algun rasgo separa "sigue cayendo" de "se da vuelta", hay una
regla de salida. Si ninguno separa, no la hay — y eso tambien es una respuesta.

Mismos controles que siempre: corte por mediana (nunca un umbral optimizado),
nulo por permutacion, correccion por multiples pruebas, y las dos mitades del
tiempo. Un rasgo que cambia de signo entre mitades es ruido.

    python test_durante.py
"""

from __future__ import annotations

import random
import statistics
import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DESDE = 10.0
PERMUTACIONES = 2000
random.seed(20260901)


def observaciones(dia):
    """Un renglón por minuto de la rueda, con rasgos de ANTES y futuro de DESPUES."""
    i10 = dia.idx_en(DESDE)
    if i10 is None:
        return []
    px10 = dia.bars[i10][4]
    cierre = dia.rth_close
    if not px10 or not cierre:
        return []

    out = []
    minimo = None
    maximo = None
    for i in range(i10, len(dia.bars)):
        b = dia.bars[i]
        h = hora(b)
        if h > CIERRE_RTH:
            break
        px = b[4]
        if not px:
            continue
        lo, hi = b[3], b[2]
        minimo = lo if minimo is None else min(minimo, lo or minimo)
        maximo = hi if maximo is None else max(maximo, hi or maximo)

        # No tiene sentido preguntarse si conviene salir en el ultimo minuto.
        if i >= len(dia.bars) - 5 or h > CIERRE_RTH - 0.25:
            continue

        ventana = dia.bars[max(i10, i - 14):i + 1]
        vols = [x[5] or 0 for x in ventana]
        vol_prev = [x[5] or 0 for x in dia.bars[i10:i + 1]]
        prom_vol = statistics.mean(vol_prev) if vol_prev else 0.0
        altos = [x[2] for x in ventana if x[2]]
        bajos = [x[3] for x in ventana if x[3]]

        rasgos = {
            # Cuanto ya cayo desde las 10:00. Es el rasgo obvio: ¿el que ya
            # dio mucho sigue dando, o se agota?
            "ya_cayo_pct": 100.0 * (px10 - px) / px10,
            # Cuanto rebotó desde el minimo del dia. Es el candidato fuerte
            # para "se esta dando vuelta".
            "rebote_desde_min": (100.0 * (px - minimo) / minimo
                                 if minimo else None),
            # Contra el VWAP: por encima es fuerza compradora.
            "vs_vwap": (100.0 * (px - dia.vwap[i]) / dia.vwap[i]
                        if dia.vwap and dia.vwap[i] else None),
            # Volumen de los ultimos 15' contra el promedio del dia: ¿se seca
            # o entra plata nueva?
            "vol_rel_15": (statistics.mean(vols) / prom_vol
                           if prom_vol and vols else None),
            # Rango de los ultimos 15': volatilidad expandiendo o muriendo.
            "rango_15_pct": (100.0 * (max(altos) - min(bajos)) / px
                             if altos and bajos else None),
            # Que tan cerca esta del maximo del dia.
            "vs_max_dia": (100.0 * (px - maximo) / maximo if maximo else None),
            "hora": h,
        }
        # LO QUE VIENE DESPUES, que es lo que se quiere predecir: cuanto mas
        # cae de aca al cierre. Positivo = sigue cayendo (bueno para un short).
        futuro = 100.0 * (px - cierre) / px
        out.append((dia.d, rasgos, futuro))
    return out


def separa(vals, objs):
    pares = [(v, o) for v, o in zip(vals, objs) if v is not None]
    if len(pares) < 200:
        return None
    med = statistics.median(v for v, _ in pares)
    alto = [o for v, o in pares if v > med]
    bajo = [o for v, o in pares if v <= med]
    if len(alto) < 80 or len(bajo) < 80:
        return None
    return {"n": len(pares), "alto": statistics.mean(alto),
            "bajo": statistics.mean(bajo),
            "delta": statistics.mean(alto) - statistics.mean(bajo)}


def p_perm(vals, objs, delta):
    pares = [(v, o) for v, o in zip(vals, objs) if v is not None]
    obs = [o for _, o in pares]
    med = statistics.median(v for v, _ in pares)
    n_alto = sum(1 for v, _ in pares if v > med)
    if n_alto == 0 or n_alto == len(obs):
        return 1.0
    ex = 0
    for _ in range(PERMUTACIONES):
        random.shuffle(obs)
        if abs(statistics.mean(obs[:n_alto])
               - statistics.mean(obs[n_alto:])) >= abs(delta):
            ex += 1
    return (ex + 1) / (PERMUTACIONES + 1)


dias = universo()
pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                max_float=47e6)
pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]

filas = []
for d in pob:
    filas.extend(observaciones(d))
filas.sort(key=lambda f: f[0])

campos = list(filas[0][1].keys())
umbral = 0.05 / len(campos)
corte = len(filas) // 2

print("\n  LO QUE PASA DURANTE: ¿PREDICE LO QUE FALTA?\n")
print(f"  {len(filas):,} minutos con posición, de {len(pob)} sesiones reclaim.")
print(f"  Objetivo: cuánto MÁS cae del minuto t al cierre "
      f"(media {statistics.mean(f[2] for f in filas):+.2f}%).")
print(f"  {len(campos)} rasgos -> umbral corregido {umbral:.4f}")
print()
print("  {:<20} {:>8} {:>9} {:>9} {:>9} {:>9} {:>9}".format(
    "rasgo", "n", "alto", "bajo", "delta", "p", "P1/P2"))
print("  " + "-" * 80)

res = []
for campo in campos:
    vals = [f[1].get(campo) for f in filas]
    objs = [f[2] for f in filas]
    s = separa(vals, objs)
    if not s:
        continue
    p = p_perm(vals, objs, s["delta"])
    signos = []
    for sub in (filas[:corte], filas[corte:]):
        s2 = separa([f[1].get(campo) for f in sub], [f[2] for f in sub])
        signos.append(None if not s2 else (s2["delta"] > 0))
    coherente = signos[0] is not None and signos[0] == signos[1]
    res.append((p, campo, s, coherente))

res.sort()
for p, campo, s, coh in res:
    marca = ""
    if p < umbral and coh:
        marca = "  <== SOBREVIVE"
    elif p < 0.05 and not coh:
        marca = "  (cambia de signo)"
    print("  {:<20} {:>8,} {:>+8.2f}% {:>+8.2f}% {:>+8.2f}% {:>9.4f} {:>9}{}".format(
        campo, s["n"], s["alto"], s["bajo"], s["delta"], p,
        "igual" if coh else "distinto", marca))

print()
print("  'alto'/'bajo' es cuánto sigue cayendo después, según la mitad alta o")
print("  baja del rasgo. Un delta NEGATIVO grande significa que cuando el rasgo")
print("  está alto, lo que queda de rueda ya no da — o sea, momento de asegurar.")
