#!/usr/bin/env python3
"""¿Dónde está la plata en el día? El perfil hora por hora, 04:00 a 16:00.

**El dato que rompe todo lo anterior.** Los operadores del informe trabajan de
06:30 a 11:30 hora de Nueva York: tres horas de PRE-MARKET y solo las dos
primeras de sesión regular. Vitale registra que el 85% de su profit histórico
sale de esa ventana.

Todo lo medido en este proyecto hasta hoy usa 09:30–16:00, y la mayoría de las
entradas se probaron al mediodía. Si el informe tiene razón, estuve midiendo la
mitad menos interesante del día — y encima la mitad que ellos ya abandonaron.

Se puede contestar con los datos que ya hay: las barras cubren 04:00 a 20:00 ET.

Tres cosas por franja de 15 minutos:
  · el retorno del short a +60 min, +120 min y al cierre de RTH
  · la excursión adversa (el riesgo de estar ahí)
  · el volumen en dólares (si es operable o es un desierto)

El volumen NO es un detalle: un retorno lindo en una franja donde se operan
$20.000 no es una oportunidad, es un gráfico.

    python test_ventana.py
    python test_ventana.py --min-expansion 100
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict

from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DESDE, HASTA = 4.0, 15.5
PASO = 0.25   # franjas de 15 minutos


def etiqueta(h):
    return f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Perfil horario del short")
    ap.add_argument("--min-expansion", type=float, default=None,
                    help="solo días con expansión pre-market >= X%%")
    ap.add_argument("--min-dias", type=int, default=40)
    args = ap.parse_args(argv)

    ret60 = defaultdict(list)
    ret120 = defaultdict(list)
    retcierre = defaultdict(list)
    mae60 = defaultdict(list)
    dolares = defaultdict(float)
    n_dias = 0

    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3:
            continue
        if args.min_expansion is not None and (dia.expansion_pct or 0) < args.min_expansion:
            continue
        n_dias += 1
        cierre_rth = dia.rth_close

        # Volumen en dólares por franja: la prueba de si la franja es operable.
        for b in dia.bars:
            h = hora(b)
            if DESDE <= h <= 20.0 and b[4]:
                dolares[round(h // PASO * PASO, 2)] += (b[5] or 0) * b[4]

        h = DESDE
        while h <= HASTA:
            i = dia.idx_en(h)
            if i is None:
                h += PASO
                continue
            p = dia.bars[i][4]
            if not p:
                h += PASO
                continue
            k = round(h, 2)

            for delta, destino in ((1.0, ret60), (2.0, ret120)):
                j = dia.idx_en(h + delta)
                if j is not None and j > i and dia.bars[j][4]:
                    destino[k].append((p / dia.bars[j][4] - 1) * 100)
            if cierre_rth and h < CIERRE_RTH:
                retcierre[k].append((p / cierre_rth - 1) * 100)

            post = [b for b in dia.bars[i + 1:] if hora(b) <= h + 1.0]
            altos = [b[2] for b in post if b[2]]
            if altos:
                mae60[k].append((max(altos) / p - 1) * 100)
            h += PASO

    print("=" * 94)
    print(f"  PERFIL HORARIO DEL SHORT  ·  {n_dias} días"
          + (f"  ·  solo expansión >= {args.min_expansion:.0f}%"
             if args.min_expansion is not None else ""))
    print("  retorno del short (positivo = ganás) · MAE = cuánto sube en contra en 1 h")
    print("  La franja sombreada es la ventana que declaran: 06:30–11:30 ET")
    print("=" * 94)
    print(f"\n  {'franja':8} {'n':>5} {'+60 min':>9} {'+120 min':>9} {'al cierre':>10} "
          f"{'MAE 1h':>8} {'vol $/día':>11}  ")
    print("  " + "-" * 78)

    total_dolares = sum(dolares.values()) or 1
    h = DESDE
    while h <= HASTA:
        k = round(h, 2)
        n = len(ret60.get(k, []))
        if n < args.min_dias:
            h += PASO
            continue
        f = lambda d: (f"{statistics.median(d[k]):+8.2f}%"  # noqa: E731
                       if len(d.get(k, [])) >= args.min_dias else "        —")
        marca = "◀" if 6.5 <= h <= 11.5 else " "
        vol = dolares[k] / n_dias
        print(f"  {etiqueta(h):8} {n:>5} {f(ret60)} {f(ret120)} {f(retcierre):>10} "
              f"{statistics.median(mae60[k]):>7.1f}% "
              f"${vol/1e3:>9,.0f}k {marca}")
        h += PASO

    print("\n  REPARTO DEL VOLUMEN DEL DÍA")
    bloques = [("pre-market temprano 04:00-06:30", 4.0, 6.5),
               ("pre-market de ellos 06:30-09:30", 6.5, 9.5),
               ("RTH primeras 2 h  09:30-11:30", 9.5, 11.5),
               ("RTH resto        11:30-16:00", 11.5, 16.0),
               ("after hours      16:00-20:00", 16.0, 20.0)]
    print(f"  {'bloque':34} {'% del volumen en $':>20}")
    print("  " + "-" * 56)
    for lab, a, b in bloques:
        s = sum(v for kk, v in dolares.items() if a <= kk < b)
        print(f"  {lab:34} {100*s/total_dolares:>19.1f}%")

    print("\n  Un retorno lindo en una franja sin volumen no es una oportunidad.")
    print("  Las dos columnas hay que leerlas juntas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
