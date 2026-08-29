#!/usr/bin/env python3
"""Entrada simple vs CONSTRUCCIÓN de posición, por hora de arranque.

Este script existe porque el resultado que compara las dos cosas se corrió
inline la primera vez y quedó en RESEARCH.md sin código detrás. Un número que
no se puede volver a correr no es un resultado, es una anécdota.

LAS DOS REGLAS, EXPLÍCITAS

  **simple** — se vende TODO el nominal a la hora de arranque. Se cubre todo a
  la hora de salida. Sin stop, sin target: mide el movimiento del papel entre
  dos horas, con el nominal completo puesto desde el minuto uno.

  **escalonado** — se vende el 20% del nominal a la hora de arranque. Cada vez
  que el papel hace un MÁXIMO NUEVO del día se vende otro 20%, hasta cinco
  tramos. No se reduce nada en el camino. Se cubre todo a la hora de salida.

CÓMO SE CONTABILIZA, QUE ES LA PARTE QUE SE PRESTA A ENGAÑO

El resultado del escalonado se multiplica por `tramos abiertos / 5`. O sea: un
día en el que solo se abrió el núcleo cuenta como **un quinto** del movimiento,
porque solo se puso un quinto del capital. Sin ese ajuste el escalonado ganaría
por comparar un 20% de posición contra un 100%.

La consecuencia es que la MEDIANA de las dos no es directamente comparable —el
escalonado despliega menos capital cuando el papel no hace máximos—. Lo que sí
es comparable directo es el **win rate** y el **MAE**, porque el riesgo máximo
comprometido es el mismo en las dos: cinco tramos de 20%.

LO QUE ESTA SIMULACIÓN NO TIENE

Ni stop, ni target, ni costos, ni locate. Es a propósito: la pregunta es si
construir cambia el signo del resultado, no cuánto se gana. Un stop metido acá
mezclaría dos efectos y no se sabría cuál manda.

    python test_construccion.py
    python test_construccion.py --salida 16.0
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TRAMOS = 5
CORTE_PERIODO = "2025-08-17"


def simple(dia, h0, h1):
    """Nominal completo desde h0. Devuelve (retorno del short %, MAE %)."""
    p = dia.precio_en(h0)
    q = dia.precio_en(h1)
    if not p or not q or h1 <= h0:
        return None
    post = [b for b in dia.bars if h0 < hora(b) <= h1 and b[2]]
    mae = (max(b[2] for b in post) / p - 1) * 100 if post else 0.0
    return (p / q - 1) * 100, mae, 1


def escalonado(dia, h0, h1):
    """Núcleo del 20% en h0, un tramo más por cada máximo nuevo, hasta 5."""
    i0 = dia.idx_en(h0)
    if i0 is None:
        return None
    p0 = dia.bars[i0][4]
    q = dia.precio_en(h1)
    if not p0 or not q or h1 <= h0:
        return None

    abiertos = [p0]
    mx = dia.max_corriente[i0]
    mae = 0.0
    for i, b in enumerate(dia.bars):
        if i <= i0 or hora(b) > h1:
            continue
        if b[2] and b[2] > mx:
            if len(abiertos) < TRAMOS:
                abiertos.append(b[2])
            mx = b[2]
        if b[2]:
            medio = sum(abiertos) / len(abiertos)
            mae = max(mae, (b[2] / medio - 1) * 100 * len(abiertos) / TRAMOS)
    medio = sum(abiertos) / len(abiertos)
    # Escalado por el nominal efectivamente desplegado. Sin esto, comparar
    # contra `simple` sería comparar un 20% de posición contra un 100%.
    return (medio / q - 1) * 100 * len(abiertos) / TRAMOS, mae, len(abiertos)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Entrada simple vs construcción")
    ap.add_argument("--min-expansion", type=float, default=100.0)
    ap.add_argument("--salida", type=float, default=11.5)
    ap.add_argument("--min-n", type=int, default=40)
    args = ap.parse_args(argv)

    dias = [d for d in cargar()
            if (d.ratio_volumen or 0) >= 3
            and (d.expansion_pct or 0) >= args.min_expansion]

    print("=" * 96)
    print(f"  ENTRADA SIMPLE vs CONSTRUCCIÓN DE POSICIÓN  ·  "
          f"expansión >= {args.min_expansion:.0f}%  ·  {len(dias)} días")
    print(f"  salida: {int(args.salida):02d}:{int(args.salida%1*60):02d} ET  ·  "
          "sin stop, sin target, sin costos — mide si CONSTRUIR cambia el signo")
    print("=" * 96)
    print(f"\n  {'arranque':>9} {'método':>12} {'n':>5} {'mediana':>9} {'media':>9} "
          f"{'gana':>6} {'MAE p90':>9} {'tramos':>7}   {'P1':>9} {'P2':>9}")
    print("  " + "-" * 94)

    for h0, lab in ((6.5, "06:30"), (7.0, "07:00"), (8.0, "08:00"),
                    (8.5, "08:30"), (9.0, "09:00"), (9.5, "09:30"),
                    (10.0, "10:00")):
        if h0 >= args.salida:
            continue
        for nombre, fn in (("simple", simple), ("escalonado", escalonado)):
            rs = []
            for d in dias:
                r = fn(d, h0, args.salida)
                if r:
                    rs.append((d.d, *r))
            if len(rs) < args.min_n:
                continue
            v = [x[1] for x in rs]
            maes = sorted(x[2] for x in rs)
            tr = statistics.mean(x[3] for x in rs)
            per = []
            for p in ("P1", "P2"):
                g = [x[1] for x in rs if (x[0] < CORTE_PERIODO) == (p == "P1")]
                per.append(f"{statistics.median(g):+8.2f}%" if len(g) >= 20 else "       —")
            print(f"  {lab:>9} {nombre:>12} {len(v):>5} {statistics.median(v):>+8.2f}% "
                  f"{statistics.mean(v):>+8.2f}% "
                  f"{100*sum(1 for x in v if x>0)/len(v):>5.0f}% "
                  f"{maes[int(.9*len(maes))]:>8.1f}% {tr:>7.1f}   {per[0]} {per[1]}")
        print()

    print("  'tramos' = cuántos de los 5 se llegaron a abrir, en promedio. Cuando")
    print("  es cerca de 1, el escalonado NO escalonó: el papel no hizo máximos")
    print("  nuevos y quedó el núcleo solo. Ahí la mediana es baja por eso y no")
    print("  porque el método falle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
