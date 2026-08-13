#!/usr/bin/env python3
"""Etapa C.3 — el cruce: pegarle a cada evento la ficha de papel de ESE día.

Hoy hay dos capas que no se hablan: la tabla `events` (precio y volumen) y
EDGAR (estructura de papel). Este script las une en una sola tabla.

**Lo que lo hace no-trivial:** no sirve la dilución de HOY. Hay que usar la que
se conocía el día del evento. Si a un evento de 2024 le pegás el share count de
2026, metiste el futuro adentro del feature central. Por eso cada fila se
resuelve con `as_of = fecha del evento`.

El costo es por TICKER, no por evento: se carga EDGAR una vez por ticker y se
resuelven todas sus fechas. ~8.000 tickers × 2 pedidos con throttle de 10/s.

**Resumable**: se puede cortar y relanzar.

    python join_structure.py
    python join_structure.py --stats
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date

import config
from edgar.facts import CompanyFacts
from edgar.filings import load_filings
from edgar.structure import build_from
from edgar.tickers import cik_for

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_structure (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    cik    INTEGER,
    shares_outstanding REAL,
    shares_stale_days  INTEGER,
    dilution_3m_pct    REAL,
    dilution_12m_pct   REAL,
    reverse_splits_12m INTEGER,
    cash_usd           REAL,
    runway_months      REAL,
    pricing_filings_12m     INTEGER,
    days_since_last_pricing INTEGER,
    shelf_effective    INTEGER,
    dilutive_8k_12m    INTEGER,
    n_warnings         INTEGER,
    PRIMARY KEY (ticker, d)
) WITHOUT ROWID;

-- Un ticker resuelto es un ticker que no hay que volver a pedirle a la SEC.
-- 'no_cik' = warrants (.WS), units (.U), ETFs: no son emisores con filings.
CREATE TABLE IF NOT EXISTS ticker_resolution (
    ticker   TEXT PRIMARY KEY,
    cik      INTEGER,
    status   TEXT NOT NULL,   -- ok | no_cik | no_data | error
    n_events INTEGER,
    detail   TEXT
);
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cruce eventos × estructura de papel")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit-tickers", type=int, default=0,
                    help="procesar solo N tickers (para probar)")
    args = ap.parse_args(argv)

    db = config.bars_db_path()
    conn = sqlite3.connect(db, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()

    if args.stats:
        _stats(conn)
        conn.close()
        return 0

    # Tickers con eventos, los de más eventos primero: si hay que cortar,
    # conviene tener resueltos los que más filas aportan.
    todos = conn.execute(
        "SELECT ticker, COUNT(*) n FROM events GROUP BY ticker ORDER BY n DESC"
    ).fetchall()
    ya = {r[0] for r in conn.execute("SELECT ticker FROM ticker_resolution")}
    pend = [(t, n) for t, n in todos if t not in ya]
    if args.limit_tickers:
        # Contar los ya resueltos ANTES de recortar, si no el recorte se
        # reporta como si estuviera hecho.
        pend = pend[:args.limit_tickers]

    print("=" * 64)
    print("  CRUCE — eventos × estructura de papel point-in-time")
    print(f"  tickers con eventos: {len(todos):,}   ya resueltos: {len(ya):,}")
    print(f"  pendientes: {len(pend):,}   → ~{len(pend) * 2 / 8 / 60:.0f} min")
    print("=" * 64, flush=True)

    t0 = time.time()
    stats = {"ok": 0, "no_cik": 0, "no_data": 0, "error": 0}
    filas = 0

    for i, (ticker, n_ev) in enumerate(pend, 1):
        fechas = [
            date.fromisoformat(r[0])
            for r in conn.execute("SELECT d FROM events WHERE ticker=?", (ticker,))
        ]
        status, cik, detail = "ok", None, None
        rows: list[tuple] = []

        try:
            cik = cik_for(ticker)
        except KeyError:
            # Warrants (.WS), units (.U), ETFs: no son emisores con filings.
            status, detail = "no_cik", "sin CIK en EDGAR"

        if status == "ok":
            try:
                # full=False: `recent` trae los últimos 1000 filings, de sobra
                # para una ventana de 12 meses, y evita pedidos extra por
                # ticker con historia larga.
                cf = CompanyFacts.load(cik, cache_hours=24 * 7)
                fil = load_filings(cik, cache_hours=24 * 7, full=False)
            except FileNotFoundError:
                status, detail = "no_data", "sin companyfacts XBRL"
            except Exception as exc:  # noqa: BLE001 — un ticker roto no frena el cruce
                status, detail = "error", f"{type(exc).__name__}: {exc}"
            else:
                for f in fechas:
                    try:
                        ps = build_from(cf, fil, ticker=ticker, cik=cik, as_of=f)
                    except Exception:  # noqa: BLE001
                        continue
                    rows.append((
                        ticker, f.isoformat(), cik,
                        ps.shares_outstanding, ps.shares_stale_days,
                        ps.dilution_3m_pct, ps.dilution_12m_pct,
                        ps.reverse_splits_12m, ps.cash_usd, ps.runway_months,
                        ps.pricing_filings_12m, ps.days_since_last_pricing,
                        1 if ps.shelf_effective else 0, ps.dilutive_8k_12m,
                        len(ps.warnings),
                    ))

        # Filas + marca de resolución en UNA transacción: si entra una sin la
        # otra, el próximo run duplica trabajo o da el ticker por hecho vacío.
        try:
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO event_structure VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            conn.execute(
                "INSERT OR REPLACE INTO ticker_resolution VALUES (?,?,?,?,?)",
                (ticker, cik, status, n_ev, detail))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        stats[status] += 1
        filas += len(rows)

        if i % 250 == 0 or i == len(pend):
            el = time.time() - t0
            print(f"  [{i:>5}/{len(pend)}] {filas:>8,} filas  ·  "
                  f"ok {stats['ok']:,} · sin CIK {stats['no_cik']:,} · "
                  f"sin datos {stats['no_data']:,} · error {stats['error']:,}  ·  "
                  f"faltan ~{(el/i)*(len(pend)-i)/60:.0f} min", flush=True)

    print(f"\n  {filas:,} filas en {(time.time()-t0)/60:.1f} min")
    _stats(conn)
    conn.close()
    return 0


def _stats(conn: sqlite3.Connection) -> None:
    tot_ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con = conn.execute("SELECT COUNT(*) FROM event_structure").fetchone()[0]
    print(f"\n  eventos totales          {tot_ev:,}")
    print(f"  eventos con ficha        {con:,}  ({100*con/max(1,tot_ev):.0f}%)")
    print("\n  RESOLUCIÓN POR TICKER")
    for st, n, ev in conn.execute(
        "SELECT status, COUNT(*), SUM(n_events) FROM ticker_resolution "
        "GROUP BY status ORDER BY COUNT(*) DESC"
    ):
        print(f"    {st:10} {n:>6,} tickers  ·  {ev or 0:>8,} eventos")
    dil = conn.execute(
        "SELECT COUNT(*) FROM event_structure WHERE dilution_12m_pct IS NOT NULL"
    ).fetchone()[0]
    if con:
        print(f"\n  con dilución 12m calculable  {dil:,}  ({100*dil/con:.0f}% de los que tienen ficha)")


if __name__ == "__main__":
    raise SystemExit(main())
