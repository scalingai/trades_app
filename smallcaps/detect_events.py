#!/usr/bin/env python3
"""Etapa C.2 — detector de volumen anómalo sobre las barras diarias locales.

Cero llamadas a la API: todo sale del SQLite del backfill.

**Qué es un evento.** No alcanza con RVOL. Un ticker que normalmente opera 500
acciones y hoy operó 50.000 tiene RVOL=100 y es inoperable: son $2.500. El
volumen en dólares no es un filtro secundario, es el que define si el evento
existe como oportunidad.

**Umbrales permisivos a propósito.** Se guardan más eventos de los que se van a
usar, para poder re-filtrar hacia arriba sin recomputar. Los umbrales de verdad
salen del dataset en Fase 3, no de una intuición de hoy. Guardar barato ahora
es lo que permite no tener que adivinar.

    python detect_events.py                    # corre con los defaults
    python detect_events.py --min-rvol 5 --min-dollar-vol 1e6
    python detect_events.py --stats            # qué hay detectado
    python detect_events.py --top 20           # los eventos más extremos
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

# Ventana para la referencia de volumen "normal".
_LOOKBACK = 20

# MEDIANA, no promedio: con promedio, un solo pico previo infla la referencia y
# esconde los picos siguientes — justo en los tickers que más nos interesan,
# que son los que pican seguido.
_MIN_PRIOR_DAYS = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL,
    dollar_volume REAL,
    prev_close REAL,
    gap_pct       REAL,   -- apertura vs cierre previo
    day_return_pct REAL,  -- cierre vs cierre previo
    intraday_pct  REAL,   -- cierre vs apertura (cuánto se dio vuelta el día)
    range_pct     REAL,   -- (max-min) / cierre previo
    close_pos     REAL,   -- (c-min)/(max-min): 1=cerró en máximos, 0=en mínimos
    med_volume    REAL,   -- mediana de volumen de los 20 días PREVIOS
    rvol          REAL,
    med_dollar_volume REAL,
    n_prior_days  INTEGER,
    PRIMARY KEY (ticker, d)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_ev_d     ON events(d);
CREATE INDEX IF NOT EXISTS ix_ev_rvol  ON events(rvol);
"""


def _pct(a: float, b: float) -> float | None:
    """Variación de b a a, en %. None si la base no sirve."""
    if b is None or a is None or b <= 0:
        return None
    return (a / b - 1.0) * 100.0


def compute(conn: sqlite3.Connection, *, min_rvol: float, min_dollar_vol: float,
            min_price: float, max_price: float, min_move_pct: float = 0.0,
            lookback: int = _LOOKBACK) -> int:
    conn.executescript(_SCHEMA)
    conn.commit()

    # Un solo scan ordenado por (ticker, d) y agrupado en Python. Evita 20.000
    # queries separadas y mantiene la memoria acotada a un ticker por vez.
    cur = conn.execute(
        "SELECT ticker, d, o, h, l, c, v, vw FROM bars_daily "
        "WHERE c IS NOT NULL AND v IS NOT NULL ORDER BY ticker, d"
    )

    batch: list[tuple] = []
    n_events = 0
    n_rows = 0

    for ticker, rows in groupby(cur, key=lambda r: r[0]):
        serie = list(rows)
        n_rows += len(serie)
        vols = [r[6] for r in serie]
        closes = [r[5] for r in serie]
        # Serie de precios para el volumen en dólares: VWAP con fallback a cierre.
        prices = [(r[7] if (r[7] is not None and r[7] > 0) else r[5]) for r in serie]

        for i in range(len(serie)):
            if i < lookback:
                continue  # sin historia previa suficiente no hay referencia

            _, d, o, h, l, c, v, vw = serie[i]

            # POINT-IN-TIME: la ventana es [i-20, i-1], estrictamente ANTERIOR.
            # Incluir el día i en su propia referencia diluiría el pico que
            # justamente estamos tratando de detectar.
            prev_vols = vols[max(0, i - lookback):i]
            if not prev_vols:
                continue
            med_v = statistics.median(prev_vols)
            if med_v <= 0:
                continue

            rvol = v / med_v
            # VWAP, no cierre. El cierre es un proxy y se desvía justo en los
            # eventos que importan: los que corren hacia el cierre lo
            # sobreestiman hasta 4x (MCLE operó $0,34M reales, no $1,57M).
            # Fallback al cierre en el 0,5% de barras sin vw.
            dollar_vol = v * (vw if (vw is not None and vw > 0) else (c or 0))

            # Filtros de EXISTENCIA del evento (no de calidad):
            # sin liquidez en dólares no hay oportunidad, la haya o no en RVOL.
            if rvol < min_rvol or dollar_vol < min_dollar_vol:
                continue
            if c is None or not (min_price <= c <= max_price):
                continue

            prev_c = closes[i - 1]

            # Volumen inusual SIN movimiento de precio no es el evento que
            # buscamos: la ventana de financiamiento existe porque la acción
            # corrió. Sin este filtro, la mitad de los eventos son tickers con
            # volumen errático y precio clavado — ruido que infla el dataset.
            # Se mide por rango intradía O por retorno: un día que sube 40% y
            # se da vuelta cierra plano pero es exactamente lo que queremos.
            if min_move_pct > 0:
                ret = _pct(c, prev_c)
                rng = ((h - l) / prev_c * 100.0) if (h is not None and l is not None and prev_c) else 0.0
                if max(abs(ret or 0.0), rng or 0.0) < min_move_pct:
                    continue

            med_dv = statistics.median(
                [vols[j] * prices[j] for j in range(max(0, i - lookback), i)]
            )
            rango = (h - l) if (h is not None and l is not None) else None

            batch.append((
                ticker, d, o, h, l, c, v, dollar_vol, prev_c,
                _pct(o, prev_c), _pct(c, prev_c), _pct(c, o),
                (rango / prev_c * 100.0) if (rango is not None and prev_c) else None,
                ((c - l) / rango) if (rango and rango > 0) else None,
                med_v, rvol, med_dv, min(i, lookback),
            ))
            n_events += 1

            if len(batch) >= 5000:
                _flush(conn, batch)
                batch.clear()

    if batch:
        _flush(conn, batch)
    conn.commit()
    print(f"  escaneadas {n_rows:,} barras", file=sys.stderr)
    return n_events


def _flush(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO events (ticker,d,open,high,low,close,volume,"
        "dollar_volume,prev_close,gap_pct,day_return_pct,intraday_pct,range_pct,"
        "close_pos,med_volume,rvol,med_dollar_volume,n_prior_days) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )


def show_stats(conn: sqlite3.Connection) -> None:
    try:
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    except sqlite3.OperationalError:
        print("  no hay eventos todavía — corré el detector sin --stats")
        return
    if not n:
        print("  0 eventos")
        return
    tk, d0, d1 = conn.execute(
        "SELECT COUNT(DISTINCT ticker), MIN(d), MAX(d) FROM events"
    ).fetchone()
    dias = conn.execute("SELECT COUNT(DISTINCT d) FROM events").fetchone()[0]
    print(f"  eventos            {n:,}")
    print(f"  tickers distintos  {tk:,}")
    print(f"  rango              {d0} → {d1}  ({dias} días con al menos 1)")
    print(f"  eventos por día    {n/max(1,dias):.1f} promedio")
    print("\n  DISTRIBUCIÓN")
    for col, label, unit in (
        ("rvol", "RVOL", "x"),
        ("dollar_volume", "volumen $", "$"),
        ("day_return_pct", "retorno del día", "%"),
        ("gap_pct", "gap", "%"),
    ):
        vals = [r[0] for r in conn.execute(
            f"SELECT {col} FROM events WHERE {col} IS NOT NULL ORDER BY {col}"
        )]
        if not vals:
            continue
        def p(q):
            return vals[min(len(vals) - 1, int(q * len(vals)))]
        if unit == "$":
            fmt = lambda x: f"${x/1e6:,.1f}M"  # noqa: E731
        else:
            fmt = lambda x: f"{x:,.1f}{unit}"  # noqa: E731
        print(f"    {label:16} p25={fmt(p(.25)):>10}  mediana={fmt(p(.5)):>10}  "
              f"p75={fmt(p(.75)):>10}  p95={fmt(p(.95)):>10}")


def show_top(conn: sqlite3.Connection, n: int) -> None:
    rows = conn.execute(
        "SELECT ticker,d,close,rvol,dollar_volume,day_return_pct,gap_pct,close_pos "
        "FROM events ORDER BY rvol DESC LIMIT ?", (n,)
    ).fetchall()
    if not rows:
        print("  sin eventos")
        return
    print(f"  {'ticker':8} {'fecha':11} {'cierre':>8} {'RVOL':>8} {'vol $':>10} "
          f"{'día':>8} {'gap':>8} {'cierre en rango':>16}")
    for t, d, c, rv, dv, ret, gap, cp in rows:
        print(f"  {t:8} {d:11} {c:>8.2f} {rv:>7.0f}x {dv/1e6:>9,.1f}M "
              f"{(f'{ret:+.0f}%' if ret is not None else '—'):>8} "
              f"{(f'{gap:+.0f}%' if gap is not None else '—'):>8} "
              f"{(f'{cp:.2f}' if cp is not None else '—'):>16}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detector de volumen anómalo")
    ap.add_argument("--min-rvol", type=float, default=3.0,
                    help="RVOL mínimo (default 3 — permisivo a propósito)")
    ap.add_argument("--min-dollar-vol", type=float, default=250_000,
                    help="volumen en dólares mínimo (default 250k = piso de operabilidad)")
    ap.add_argument("--min-move", type=float, default=10.0,
                    help="movimiento mínimo en %% (retorno absoluto O rango intradía). "
                         "Default 10 — volumen sin movimiento no es el evento buscado")
    ap.add_argument("--min-price", type=float, default=0.30)
    ap.add_argument("--max-price", type=float, default=50.0)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--lookback", type=int, default=_LOOKBACK,
                    help=f"días previos para la mediana de referencia (default {_LOOKBACK})")
    args = ap.parse_args(argv)

    db = config.bars_db_path()
    if not db.exists():
        print(f"no existe {db} — corré antes `python backfill_daily.py`", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        if args.stats:
            show_stats(conn)
            return 0
        if args.top:
            show_top(conn, args.top)
            return 0

        print("=" * 64)
        print("  DETECTOR DE VOLUMEN ANÓMALO")
        print(f"  RVOL >= {args.min_rvol}  ·  volumen $ >= ${args.min_dollar_vol:,.0f}  "
              f"·  precio ${args.min_price}-${args.max_price}  "
              f"·  movimiento >= {args.min_move}%")
        print(f"  referencia: mediana de {args.lookback} días PREVIOS")
        print("=" * 64, flush=True)

        n = compute(conn, min_rvol=args.min_rvol, min_dollar_vol=args.min_dollar_vol,
                    min_price=args.min_price, max_price=args.max_price,
                    min_move_pct=args.min_move, lookback=args.lookback)
        print(f"\n  {n:,} eventos detectados\n")
        show_stats(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
