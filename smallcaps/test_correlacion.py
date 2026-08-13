#!/usr/bin/env python3
"""¿Los trades son independientes? El supuesto que sostenía el dimensionamiento.

La simulación de riesgo remuestrea trades de a uno, asumiendo independencia. Si
los eventos de small caps se agrupan —cuando el sector se calienta corren muchas
a la vez— entonces varias posiciones el mismo día son **una sola apuesta
disfrazada de tres**, las rachas son peores que lo simulado, y el tamaño
recomendado queda corto de conservador.

**Por qué NO se mide sobre la muestra de minutos:** al sortear 1.500 eventos al
azar se rompió el agrupamiento por día a propósito (para que la muestra fuera
representativa). Medir correlación ahí daría artificialmente baja. Se usa la
tabla completa de eventos diarios.

El número que importa es el **ratio de varianza**: cuánto más varía el
resultado de un día con k trades comparado con lo que predeciría la
independencia. Ratio 1 = independientes. Ratio 3 = tres trades pesan como uno.

    python test_correlacion.py
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Correlación entre trades del mismo día")
    ap.add_argument("--min-precio", type=float, default=3.0)
    ap.add_argument("--gap", type=float, default=20.0)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path())
    rows = conn.execute(
        "SELECT d, ticker, intraday_pct FROM events "
        "WHERE gap_pct>? AND dollar_volume>=1e6 AND close>=? AND intraday_pct IS NOT NULL",
        (args.gap, args.min_precio)).fetchall()

    por_dia = defaultdict(list)
    for d, t, r in rows:
        por_dia[d].append(r)

    todos = [r for _, _, r in rows]
    var_single = statistics.pvariance(todos)
    media = statistics.mean(todos)

    print("=" * 78)
    print(f"  ¿SON INDEPENDIENTES?  n={len(todos):,} eventos en {len(por_dia):,} días")
    print("=" * 78)
    print(f"\n  media por trade {media:+.2f}%   ·   desvío {var_single**0.5:.2f}%")
    ks = sorted(len(v) for v in por_dia.values())
    print(f"  eventos por día: mediana {statistics.median(ks):.0f}  ·  "
          f"p90 {ks[int(len(ks)*.9)]}  ·  máximo {max(ks)}")

    # Correlación intraclase: cuánta de la varianza total se explica por el DÍA.
    # Si los días no importan, es 0 y los trades son independientes.
    grupos = [v for v in por_dia.values() if len(v) >= 2]
    n_tot = sum(len(v) for v in grupos)
    entre = sum(len(v) * (statistics.mean(v) - media) ** 2 for v in grupos) / n_tot
    dentro = sum(sum((x - statistics.mean(v)) ** 2 for x in v) for v in grupos) / n_tot
    icc = entre / (entre + dentro) if (entre + dentro) else 0.0
    print(f"\n  CORRELACIÓN INTRACLASE (cuánto explica el día): {icc:.3f}")
    print("    0 = independientes   ·   1 = todos los del día hacen lo mismo")

    print(f"\n  RATIO DE VARIANZA — cuánto pesa de verdad tomar k trades el mismo día")
    print(f"    {'k':>3} {'días':>7} {'var real':>11} {'si fueran indep.':>18} {'ratio':>8}")
    for k in (2, 3, 4, 5, 8):
        g = [v for v in por_dia.values() if len(v) >= k]
        if len(g) < 30:
            print(f"    {k:>3} {len(g):>7}   muestra insuficiente")
            continue
        # Suma de k trades tomados el mismo día (los primeros k, sin elegir).
        sumas = [sum(v[:k]) for v in g]
        real = statistics.pvariance(sumas)
        indep = k * var_single
        print(f"    {k:>3} {len(g):>7} {real:>10.0f} {indep:>17.0f} {real/indep:>8.2f}")

    print(f"\n  DÍAS EN QUE TODOS LOS TRADES VAN PARA EL MISMO LADO")
    print(f"    {'k':>3} {'días':>7} {'todos igual':>13} {'si fueran indep.':>18}")
    for k in (2, 3, 4):
        g = [v[:k] for v in por_dia.values() if len(v) >= k]
        if len(g) < 30:
            continue
        iguales = sum(1 for v in g if all(x < 0 for x in v) or all(x >= 0 for x in v))
        p = sum(1 for x in todos if x < 0) / len(todos)
        esperado = p ** k + (1 - p) ** k
        print(f"    {k:>3} {len(g):>7} {100*iguales/len(g):>12.0f}% {100*esperado:>17.0f}%")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
