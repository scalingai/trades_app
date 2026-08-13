#!/usr/bin/env python3
"""La prueba fuera de muestra: ¿el efecto replica en dos períodos independientes?

Es la prueba más dura que se le puede hacer a un hallazgo sin datos nuevos. Un
patrón que aparece en dos años distintos, sin superposición, es difícil de
explicar como ruido. Uno que aparece solo en uno, casi seguro lo era.

**Lo que mide y lo que no.** Reporta MEDIANAS: el caso típico. La mediana no es
el P&L — las medias de estos retornos están cerca de cero porque la cola de
squeezes se come la ventaja del caso típico. Que la mediana replique valida el
FEATURE, no la rentabilidad de operarlo.

    python test_out_of_sample.py
    python test_out_of_sample.py --corte 2025-08-17
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_GRUPOS = (
    (100, 1e18, "diluyó >100%"),
    (25, 100, "diluyó 25-100%"),
    (-1e18, 25, "diluyó <25%"),
)

_Q = """
    SELECT e.intraday_pct, h.ret_t5, s.dilution_12m_pct
    FROM events e
    JOIN event_structure s ON s.ticker=e.ticker AND s.d=e.d
    LEFT JOIN horizons h   ON h.ticker=e.ticker AND h.d=e.d
    WHERE e.gap_pct > ? AND e.dollar_volume >= ?
      AND s.dilution_12m_pct IS NOT NULL AND e.intraday_pct IS NOT NULL
      AND e.d {op} ?
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prueba fuera de muestra")
    ap.add_argument("--corte", default="2025-08-17", help="fecha que parte los períodos")
    ap.add_argument("--gap", type=float, default=20.0)
    ap.add_argument("--min-dollar-vol", type=float, default=1e6)
    ap.add_argument("--min-n", type=int, default=40)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path())
    medianas: dict[str, list] = {}

    for etiqueta, op in (("PERÍODO 1 (antes del corte)", "<"),
                         ("PERÍODO 2 (desde el corte)", ">=")):
        data = conn.execute(_Q.format(op=op),
                            (args.gap, args.min_dollar_vol, args.corte)).fetchall()
        print(f"\n=== {etiqueta}   corte={args.corte}   n={len(data):,} ===")
        print(f"  {'grupo':22} {'n':>5} {'intradía':>26} {'T+5':>12}")
        meds = []
        for lo, hi, lab in _GRUPOS:
            g = [r for r in data if lo <= r[2] < hi]
            if len(g) < args.min_n:
                print(f"  {lab:22} {len(g):>5}  (insuficiente)")
                meds.append(None)
                continue
            intra = [r[0] for r in g]
            t5 = [r[1] for r in g if r[1] is not None]
            baja = sum(1 for x in intra if x < 0)
            m = statistics.median(intra)
            meds.append(m)
            s5 = f"{statistics.median(t5):>7.2f}%" if len(t5) >= args.min_n else "      —"
            print(f"  {lab:22} {len(g):>5}  med={m:>7.2f}%  baja el {100*baja/len(intra):>3.0f}%"
                  f"  {s5:>12}")
        medianas[etiqueta] = meds

    print("\n=== ¿SE MANTIENE EL ORDEN EN LOS DOS PERÍODOS? ===")
    todos_ok = True
    for etiqueta, meds in medianas.items():
        # Monotónico = más dilución previa, más se desinfla. Es la predicción
        # del mecanismo, fijada antes de mirar: no se acepta cualquier orden.
        ok = all(m is not None for m in meds) and meds[0] < meds[1] < meds[2]
        todos_ok &= ok
        vals = [f"{m:.2f}%" if m is not None else "—" for m in meds]
        print(f"  {etiqueta:30} {vals}   monotónico: {'SÍ' if ok else 'NO'}")

    print("\n  " + ("REPLICA en ambos períodos." if todos_ok
                    else "NO replica — tratar el hallazgo como ruido."))
    print("  Recordatorio: son MEDIANAS. Validan el feature, no la rentabilidad.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
