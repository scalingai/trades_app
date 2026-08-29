#!/usr/bin/env python3
"""¿La primera semana del mes anticipa el régimen del resto? (Módulo 3 del informe)

El informe de NotebookLM afirma que el régimen se diagnostica en la primera
semana del mes: si los gaps FALLAN en sostener, el mes es de *fading* (entorno
de cortos); si RECLAMAN niveles y siguen, hay que neutralizar los cortos.

Es la afirmación más barata de testear del documento entero y una de las más
valiosas si es cierta: sería un interruptor de encendido/apagado mensual que no
depende de nada intradía.

Se testea sobre las barras DIARIAS —87.943 eventos, no los 775 días con
minutos—, así que es la prueba con más muestra de todo el proyecto.

Definición, fijada antes de correr:
  · "fade" de un día = el cierre quedó por debajo de la apertura
  · semana 1 = días 1 a 7 del mes calendario
  · régimen del mes = % de eventos que fadearon del día 8 en adelante

La pregunta es una sola: ¿el % de la semana 1 correlaciona con el del resto?

    python test_regimen.py
    python test_regimen.py --min-gap 50
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def correlacion(xs, ys):
    """Pearson a mano — no vale traer numpy para esto."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Régimen mensual de fading")
    ap.add_argument("--min-gap", type=float, default=20.0)
    ap.add_argument("--min-dollar-vol", type=float, default=1e6)
    ap.add_argument("--min-eventos", type=int, default=15,
                    help="mínimo de eventos en la semana 1 para que el mes cuente")
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    filas = db.execute(
        "SELECT d, gap_pct, intraday_pct FROM events "
        "WHERE gap_pct >= ? AND dollar_volume >= ? AND intraday_pct IS NOT NULL",
        (args.min_gap, args.min_dollar_vol)).fetchall()
    db.close()

    sem1 = defaultdict(list)
    resto = defaultdict(list)
    for d, _gap, intra in filas:
        mes = d[:7]
        (sem1 if int(d[8:10]) <= 7 else resto)[mes].append(intra)

    meses = sorted(m for m in sem1
                   if len(sem1[m]) >= args.min_eventos and len(resto.get(m, [])) >= 30)

    print("=" * 84)
    print(f"  RÉGIMEN MENSUAL — ¿la semana 1 anticipa el resto del mes?")
    print(f"  gaps >= +{args.min_gap:.0f}%, volumen >= ${args.min_dollar_vol/1e6:.0f}M  ·  "
          f"{len(filas):,} eventos  ·  {len(meses)} meses con muestra")
    print("  'fade' = el cierre quedó por debajo de la apertura")
    print("=" * 84)

    print(f"\n  {'mes':9} {'n sem1':>7} {'fade sem1':>10} {'n resto':>8} {'fade resto':>11} "
          f"{'mediana resto':>14}")
    print("  " + "-" * 66)
    xs, ys = [], []
    for m in meses:
        a, b = sem1[m], resto[m]
        fa = 100 * sum(1 for x in a if x < 0) / len(a)
        fb = 100 * sum(1 for x in b if x < 0) / len(b)
        xs.append(fa)
        ys.append(fb)
        print(f"  {m:9} {len(a):>7} {fa:>9.0f}% {len(b):>8} {fb:>10.0f}% "
              f"{statistics.median(b):>+13.2f}%")

    r = correlacion(xs, ys)
    print("\n  " + "-" * 66)
    print(f"  correlación semana 1 ↔ resto del mes:  r = {r:+.3f}" if r is not None
          else "  muestra insuficiente")

    if r is not None:
        # La prueba que importa: ¿operar solo los meses "de fading" mejora algo?
        mediana_sem1 = statistics.median(xs)
        buenos = [i for i, x in enumerate(xs) if x >= mediana_sem1]
        malos = [i for i, x in enumerate(xs) if x < mediana_sem1]
        rb = [v for i in buenos for v in resto[meses[i]]]
        rm = [v for i in malos for v in resto[meses[i]]]
        print(f"\n  SI SE FILTRA POR EL DIAGNÓSTICO DE LA SEMANA 1")
        print(f"  {'':28} {'n':>7} {'mediana':>9} {'% que fadea':>12}")
        print("  " + "-" * 60)
        for lab, g in (("meses diagnosticados fading", rb),
                       ("meses diagnosticados reclaim", rm)):
            print(f"  {lab:28} {len(g):>7} {statistics.median(g):>+8.2f}% "
                  f"{100*sum(1 for x in g if x<0)/len(g):>11.0f}%")
        print(f"\n  Diferencia de medianas: "
              f"{statistics.median(rb) - statistics.median(rm):+.2f} puntos.")
        print("  Si el diagnóstico sirviera, los meses 'fading' tendrían que fadear")
        print("  MÁS que los 'reclaim' — y por un margen que valga apagar el sistema.")

    print("\n  Nota: 'fade' acá es cierre < apertura sobre barras diarias. El informe")
    print("  habla de gaps que fallan en SOSTENER, que es más fino. Esta es la versión")
    print("  medible con lo que hay; si el resultado fuera fuerte, valdría refinarla.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
