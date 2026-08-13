#!/usr/bin/env python3
"""Etapa A — perfil del universo: ¿estos features discriminan?

La pregunta que contesta: si el 80% de las micro caps tiene runway corto y
shelf efectivo, entonces eso NO es un filtro — es una descripción del asset
class, y no sirve para elegir nada. Hay que saberlo antes de gastar en data.

El universo sale de `dei:EntityPublicFloat` vía el frames API de XBRL: público
float bajo $75M es el umbral del *baby shelf rule*, o sea el criterio
regulatorio real, no un corte inventado.

    python profile_universe.py --sample 150
    python profile_universe.py --max-float 75e6 --sample 400 --out data/universe_profile.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

from edgar.client import fetch_json
from edgar.structure import build
from edgar.tickers import ticker_for

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_FRAMES = "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/{q}.json"

# EntityPublicFloat se reporta en la carátula del 10-K, así que cada frame
# trimestral solo captura a las empresas con ese cierre fiscal. Hay que unir
# varios trimestres para cubrir el mercado.
_QUARTERS = [
    "CY2024Q2I", "CY2024Q3I", "CY2024Q4I", "CY2025Q1I",
    "CY2025Q2I", "CY2025Q3I", "CY2025Q4I", "CY2026Q1I",
]


def build_universe(max_float: float) -> list[dict]:
    """CIKs con public float positivo bajo el umbral, dato más reciente por empresa."""
    best: dict[int, dict] = {}
    for q in _QUARTERS:
        try:
            payload = fetch_json(_FRAMES.format(q=q), cache_hours=24 * 7)
        except Exception as exc:  # noqa: BLE001 — un frame faltante no frena
            print(f"  frame {q}: {type(exc).__name__}", file=sys.stderr)
            continue
        for row in payload.get("data", []):
            cik = int(row["cik"])
            prev = best.get(cik)
            if prev is None or row.get("end", "") > prev.get("end", ""):
                best[cik] = row

    out = []
    for cik, row in best.items():
        val = float(row["val"])
        if not (0 < val < max_float):
            continue
        tk = ticker_for(cik)
        if not tk:
            continue  # sin ticker en EDGAR no lo podemos cruzar con precio después
        out.append({"cik": cik, "ticker": tk, "public_float": val,
                    "name": row.get("entityName", ""), "float_asof": row.get("end")})
    out.sort(key=lambda r: r["public_float"])
    return out


def _pctiles(vals: list[float]) -> str:
    if not vals:
        return "sin datos"
    s = sorted(vals)
    def p(q: float) -> float:
        return s[min(len(s) - 1, int(q * len(s)))]
    return (f"p10={p(.10):,.1f}  p25={p(.25):,.1f}  mediana={statistics.median(s):,.1f}  "
            f"p75={p(.75):,.1f}  p90={p(.90):,.1f}")


def _share(flags: list[bool]) -> str:
    if not flags:
        return "sin datos"
    n = sum(flags)
    return f"{n}/{len(flags)} = {100 * n / len(flags):.0f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Etapa A — perfil del universo micro cap")
    ap.add_argument("--max-float", type=float, default=75e6,
                    help="umbral de public float (default 75e6 = baby shelf rule)")
    ap.add_argument("--sample", type=int, default=150,
                    help="cuántas empresas perfilar (0 = todas)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    print(f"construyendo universo (public float < ${args.max_float/1e6:,.0f}M)…")
    universe = build_universe(args.max_float)
    print(f"  {len(universe)} empresas con ticker\n")

    targets = universe
    if args.sample and args.sample < len(universe):
        random.Random(args.seed).shuffle(targets := list(universe))
        targets = targets[:args.sample]

    rows, failures = [], 0
    for i, u in enumerate(targets, 1):
        try:
            ps = build(u["ticker"], cache_hours=24 * 7)
        except Exception:  # noqa: BLE001 — un ticker roto no frena el perfil
            failures += 1
            continue
        d = ps.to_dict()
        d["public_float"] = u["public_float"]
        rows.append(d)
        if i % 25 == 0:
            print(f"  {i}/{len(targets)}…", file=sys.stderr)

    if not rows:
        print("no se perfiló ninguna empresa", file=sys.stderr)
        return 1

    # --- el resultado que decide si la tesis sigue en pie ---
    dil12 = [r["dilution_12m_pct"] for r in rows if r["dilution_12m_pct"] is not None]
    runway = [r["runway_months"] for r in rows if r["runway_months"] is not None]

    print(f"\n{'=' * 68}")
    print(f"  PERFIL DEL UNIVERSO — {len(rows)} empresas ({failures} fallaron)")
    print("=" * 68)
    print(f"\n  dilución 12m (%)      {_pctiles(dil12)}   [n={len(dil12)}]")
    print(f"  runway (meses)        {_pctiles(runway)}   [n={len(runway)}]")
    print("\n  ¿QUÉ FRACCIÓN CUMPLE CADA CONDICIÓN?")
    print(f"    runway < 6 meses          {_share([r < 6 for r in runway])}")
    print(f"    runway < 12 meses         {_share([r < 12 for r in runway])}")
    print(f"    dilución 12m > 25%        {_share([d > 25 for d in dil12])}")
    print(f"    dilución 12m > 100%       {_share([d > 100 for d in dil12])}")
    print(f"    shelf efectivo            {_share([r['shelf_effective'] for r in rows])}")
    print(f"    >=1 pricing en 12m        {_share([r['pricing_filings_12m'] >= 1 for r in rows])}")
    print(f"    >=1 reverse split 12m     {_share([r['reverse_splits_12m'] >= 1 for r in rows])}")
    print(f"    >=3 8-K dilutivos 12m     {_share([r['dilutive_8k_12m'] >= 3 for r in rows])}")

    print("\n  LECTURA: un feature que cumple ~todo el universo NO discrimina.")
    print("  Los útiles son los que caen en la cola, no los que describen la clase.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n→ {len(rows)} filas en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
