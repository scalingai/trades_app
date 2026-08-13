#!/usr/bin/env python3
"""CLI de Fase 0 — arma la estructura de papel de uno o varios tickers.

    python ingest.py HSCS
    python ingest.py HSCS MULN NVDA --json
    python ingest.py --file universe.txt --as-of 2026-01-15 --out data/structures.jsonl

Salida por defecto: ficha legible. Con `--out`, JSONL append-only (el dataset).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from edgar import build
from edgar.structure import PaperStructure

HERE = Path(__file__).resolve().parent

# La consola de Windows arranca en cp1252 y rompe los acentos de la ficha.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _fmt_num(v: float | None, *, pct: bool = False, money: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v:+,.1f}%"
    if money:
        if abs(v) >= 1e6:
            return f"${v / 1e6:,.1f}M"
        return f"${v:,.0f}"
    return f"{v:,.0f}"


def render(ps: PaperStructure) -> str:
    L = []
    L.append(f"\n{'=' * 66}")
    L.append(f"  {ps.ticker}  ·  {ps.entity_name}")
    L.append(f"  CIK {ps.cik}  ·  point-in-time al {ps.as_of}")
    L.append("=" * 66)

    L.append("\n  ESTRUCTURA DE PAPEL")
    L.append(f"    acciones en circulación   {_fmt_num(ps.shares_outstanding)}")
    if ps.shares_as_of:
        L.append(
            f"    medido al                 {ps.shares_as_of}"
            f"   (público desde {ps.shares_known_at}, {ps.shares_stale_days}d)"
        )
    L.append(f"    dilución 3m               {_fmt_num(ps.dilution_3m_pct, pct=True)}")
    L.append(f"    dilución 12m              {_fmt_num(ps.dilution_12m_pct, pct=True)}")
    L.append(
        f"    dilución desde inicio     {_fmt_num(ps.dilution_since_inception_pct, pct=True)}"
    )
    if ps.reverse_splits:
        L.append(f"    reverse splits            {len(ps.reverse_splits)} detectados "
                 f"({ps.reverse_splits_12m} en 12m)")
        for s in ps.reverse_splits[-3:]:
            L.append(
                f"        ~1:{s.approx_ratio:.0f}  entre {s.detected_between[0]} "
                f"y {s.detected_between[1]}"
            )

    L.append("\n  CAJA")
    L.append(f"    caja                      {_fmt_num(ps.cash_usd, money=True)}"
             f"   (al {ps.cash_as_of or '—'})")
    L.append(f"    burn mensual              {_fmt_num(ps.monthly_burn_usd, money=True)}"
             f"   [{ps.data_quality.get('burn', '?')}]")
    runway = f"{ps.runway_months:.1f} meses" if ps.runway_months is not None else "—"
    L.append(f"    runway                    {runway}")

    L.append("\n  CADENCIA DE OFERTAS")
    L.append(f"    pricings (424B*) 12m      {ps.pricing_filings_12m}")
    L.append(
        f"    último pricing            "
        f"{ps.last_pricing_form or '—'}"
        + (f"  hace {ps.days_since_last_pricing}d" if ps.days_since_last_pricing is not None else "")
    )
    L.append(f"    shelfs (S-3/F-3) 12m      {ps.shelf_filings_12m}")
    L.append(f"    último shelf              {ps.last_shelf_filed or '—'}")
    L.append(f"    último EFFECT             {ps.last_effect_filed or '—'}")
    L.append(
        f"    shelf disparable          "
        f"{'SÍ — registro efectivo' if ps.shelf_effective else 'no consta EFFECT posterior'}"
    )
    L.append(f"    8-K dilutivos 12m         {ps.dilutive_8k_12m}")

    if ps.warnings:
        L.append("\n  ADVERTENCIAS")
        for w in ps.warnings:
            L.append(f"    ! {w}")

    dq = ", ".join(f"{k}={v}" for k, v in sorted(ps.data_quality.items()))
    L.append(f"\n  data_quality: {dq}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fase 0 — estructura de papel desde EDGAR")
    p.add_argument("tickers", nargs="*", help="tickers a procesar")
    p.add_argument("--file", type=Path, help="archivo con un ticker por línea")
    p.add_argument("--as-of", type=date.fromisoformat, default=None,
                   help="fecha point-in-time (YYYY-MM-DD). Default: hoy")
    p.add_argument("--out", type=Path, help="append JSONL a este archivo")
    p.add_argument("--json", action="store_true", help="imprime JSON en vez de la ficha")
    p.add_argument("--cache-hours", type=float, default=12.0)
    args = p.parse_args(argv)

    tickers = list(args.tickers)
    if args.file:
        tickers += [
            ln.strip().upper()
            for ln in args.file.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
    if not tickers:
        p.error("hay que pasar al menos un ticker (o --file)")

    results: list[PaperStructure] = []
    failures: list[tuple[str, str]] = []

    for t in tickers:
        try:
            ps = build(t, as_of=args.as_of, cache_hours=args.cache_hours)
        except KeyError as exc:
            failures.append((t, f"no está en EDGAR: {exc}"))
            continue
        except FileNotFoundError as exc:
            failures.append((t, f"sin datos XBRL: {exc}"))
            continue
        except Exception as exc:  # noqa: BLE001 — un ticker roto no frena el batch
            failures.append((t, f"{type(exc).__name__}: {exc}"))
            continue

        results.append(ps)
        if args.json:
            print(json.dumps(ps.to_dict(), ensure_ascii=False))
        else:
            print(render(ps))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as fh:
            for ps in results:
                fh.write(json.dumps(ps.to_dict(), ensure_ascii=False) + "\n")
        print(f"\n→ {len(results)} filas append a {args.out}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} fallaron:", file=sys.stderr)
        for t, why in failures:
            print(f"  {t}: {why}", file=sys.stderr)

    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
