#!/usr/bin/env python3
"""El punto ciego: los eventos que el RVOL en ACCIONES no ve.

`detect_events.py` mide el volumen relativo en acciones. Un reverse split 1:45
divide el volumen por 45, así que el día del pump posterior da RVOL ≈ 1 y **no
entra como evento**. ELPW 2026-08-11 —el día que arrancó toda esta
investigación— no está entre los 87.943 por exactamente eso.

El RVOL en dólares no tiene ese problema: un reverse split conserva el volumen
en dólares aproximadamente, así que un pump de verdad lo multiplica igual.

Este script no reescribe el detector: recorre las barras diarias, calcula las
dos versiones del RVOL sobre la misma ventana de 20 días, y **mide la población
que la versión en acciones se pierde**. Si esa población se comporta distinto,
el arreglo del detector deja de ser higiene y pasa a ser una fuente de setups.

    python test_rvol_dolares.py
    python test_rvol_dolares.py --min-rvol 5 --min-dollar-vol 2e6
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from itertools import groupby

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LOOKBACK = 20


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RVOL en dólares vs en acciones")
    ap.add_argument("--min-rvol", type=float, default=5.0)
    ap.add_argument("--min-dollar-vol", type=float, default=1e6)
    ap.add_argument("--min-precio", type=float, default=0.30)
    ap.add_argument("--max-precio", type=float, default=20.0)
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    ya = {(t, d) for t, d in db.execute("SELECT ticker,d FROM events")}

    filas = db.execute(
        "SELECT ticker, d, o, h, l, c, v, vw FROM bars_daily ORDER BY ticker, d")

    solo_dolares, ambos, solo_acciones = [], [], []
    for ticker, grupo in groupby(filas, key=lambda r: r[0]):
        barras = list(grupo)
        for i in range(LOOKBACK, len(barras)):
            _t, d, o, _h, _l, c, v, vw = barras[i]
            if not (o and c and v):
                continue
            if not (args.min_precio <= o <= args.max_precio):
                continue
            prev = barras[i - LOOKBACK:i]
            vols = [x[6] for x in prev if x[6]]
            dvs = [(x[6] or 0) * (x[7] or x[5] or 0) for x in prev]
            if len(vols) < LOOKBACK or not any(dvs):
                continue
            med_v = statistics.median(vols)
            med_dv = statistics.median(dvs)
            dv = v * (vw or c)
            if dv < args.min_dollar_vol or med_v <= 0 or med_dv <= 0:
                continue

            rvol_acc = v / med_v
            rvol_dol = dv / med_dv
            prev_close = barras[i - 1][5]
            gap = (o / prev_close - 1) * 100 if prev_close else None
            intra = (c / o - 1) * 100

            fila = {"t": ticker, "d": d, "gap": gap, "intra": intra,
                    "rvol_acc": rvol_acc, "rvol_dol": rvol_dol,
                    "en_events": (ticker, d) in ya, "precio": o}
            if rvol_dol >= args.min_rvol and rvol_acc < args.min_rvol:
                solo_dolares.append(fila)
            elif rvol_dol >= args.min_rvol and rvol_acc >= args.min_rvol:
                ambos.append(fila)
            elif rvol_acc >= args.min_rvol:
                solo_acciones.append(fila)

    def resumen(g, lab):
        if len(g) < 20:
            print(f"  {lab:38} n={len(g):>6}   (insuficiente)")
            return
        v = [x["intra"] for x in g]
        print(f"  {lab:38} n={len(g):>6}  mediana {statistics.median(v):>+7.2f}%  "
              f"media {statistics.mean(v):>+7.2f}%  cae {100*sum(1 for x in v if x<0)/len(v):>3.0f}%")

    print("=" * 88)
    print(f"  RVOL EN DÓLARES vs EN ACCIONES  ·  umbral {args.min_rvol:.0f}×  ·  "
          f"vol$ >= ${args.min_dollar_vol/1e6:.0f}M")
    print("=" * 88)
    print("\n  POBLACIONES")
    resumen(ambos, "las ve las dos")
    resumen(solo_dolares, "SOLO el RVOL en dólares (el punto ciego)")
    resumen(solo_acciones, "solo el RVOL en acciones")

    n_no = sum(1 for x in solo_dolares if not x["en_events"])
    print(f"\n  De las {len(solo_dolares):,} que solo ve el RVOL en dólares, "
          f"{n_no:,} NO están en la tabla `events`.")

    print("\n  LAS DEL PUNTO CIEGO, POR TAMAÑO DEL GAP")
    for lo, hi, lab in ((-1e9, 20, "gap < 20%"), (20, 70, "gap 20-70%"),
                        (70, 1e9, "gap >= 70%")):
        resumen([x for x in solo_dolares if x["gap"] is not None and lo <= x["gap"] < hi],
                f"  {lab}")

    print("\n  ¿SON REVERSE SPLITS? — el RVOL en acciones muy bajo es la firma")
    for lo, hi, lab in ((0, 0.5, "rvol acciones < 0,5× (bajó el volumen)"),
                        (0.5, 2, "0,5-2×"), (2, 5, "2-5×")):
        resumen([x for x in solo_dolares if lo <= x["rvol_acc"] < hi], f"  {lab}")

    print("\n  Los 15 casos más extremos del punto ciego:")
    print(f"  {'ticker':7} {'fecha':11} {'precio':>7} {'gap':>8} "
          f"{'rvol $':>8} {'rvol acc':>9} {'intra':>8} {'en events':>10}")
    print("  " + "-" * 74)
    for x in sorted(solo_dolares, key=lambda z: -z["rvol_dol"])[:15]:
        gap_txt = f"{x['gap']:+.0f}%" if x["gap"] is not None else "—"
        print(f"  {x['t']:7} {x['d']:11} {x['precio']:>7.2f} "
              f"{gap_txt:>8} "
              f"{x['rvol_dol']:>7.0f}× {x['rvol_acc']:>8.2f}× {x['intra']:>+7.1f}% "
              f"{'sí' if x['en_events'] else 'NO':>10}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
