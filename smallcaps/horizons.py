#!/usr/bin/env python3
"""Etapa C.4 — retornos multi-horizonte + máxima excursión adversa (MAE).

Dos preguntas que no se pueden contestar con lo que había:

1. **¿En qué horizonte vive el efecto?** Todo lo medido hasta acá es intradía.
   La literatura del efecto MAX (Bali, Cakici & Whitelaw 2011, JFE) documenta
   el fenómeno a horizonte MENSUAL. Puede que estemos mirando el plazo
   equivocado.

2. **¿Cuánto se fue en contra en el PEOR momento?** Un límite de pérdida diaria
   no mira dónde terminó el trade, mira por dónde pasó. Un trade que cierra en
   -13% pero llegó a +40% te sacó de la cuenta antes de cobrarlo. Eso es la
   MAE, y decide la compatibilidad con cualquier cuenta con reglas de riesgo.

**Nota de honestidad sobre el punto de entrada.** El evento se define usando el
volumen del día COMPLETO, así que en la apertura todavía no sabés que es un
evento — medir desde la apertura tiene look-ahead. Por eso:

  · intradía  → entrada en la apertura. Queda marcado como COTA SUPERIOR:
                requiere confirmación con volumen pre-market (datos de minuto).
  · T+1/5/20  → entrada en el CIERRE del día del evento. Ahí ya se conoce todo.
                Limpio, sin look-ahead.

    python horizons.py            # calcula y reporta
    python horizons.py --report   # solo reporta lo ya calculado
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

_HORIZONS = (1, 5, 20)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS horizons (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    entry_close REAL,
    ret_intraday REAL,
    mae_short_intraday REAL,
    mae_long_intraday  REAL,
    ret_t1 REAL,  mae_short_t1 REAL,  mae_long_t1 REAL,  n_t1 INTEGER,
    ret_t5 REAL,  mae_short_t5 REAL,  mae_long_t5 REAL,  n_t5 INTEGER,
    ret_t20 REAL, mae_short_t20 REAL, mae_long_t20 REAL, n_t20 INTEGER,
    PRIMARY KEY (ticker, d)
) WITHOUT ROWID;
"""


def compute(conn: sqlite3.Connection) -> int:
    conn.executescript(_SCHEMA)
    conn.commit()

    eventos: dict[str, set[str]] = {}
    for t, d in conn.execute("SELECT ticker, d FROM events"):
        eventos.setdefault(t, set()).add(d)

    cur = conn.execute(
        "SELECT ticker, d, o, h, l, c FROM bars_daily "
        "WHERE c IS NOT NULL ORDER BY ticker, d"
    )
    batch: list[tuple] = []
    n = 0

    for ticker, rows in groupby(cur, key=lambda r: r[0]):
        serie = list(rows)
        fechas = eventos.get(ticker)
        if not fechas:
            continue
        idx = {r[1]: i for i, r in enumerate(serie)}

        for d in fechas:
            i = idx.get(d)
            if i is None:
                continue
            _, _, o, h, l, c = serie[i]
            if not o or not c:
                continue

            # --- intradía: entrada en la apertura (cota superior, ver docstring)
            ret_in = (c / o - 1.0) * 100.0
            # MAE del short = cuánto SUBIÓ contra vos. Del largo = cuánto bajó.
            mae_s_in = ((h / o - 1.0) * 100.0) if h else None
            mae_l_in = ((1.0 - l / o) * 100.0) if l else None

            fila = [ticker, d, c, ret_in, mae_s_in, mae_l_in]

            # --- multi-día: entrada en el CIERRE del evento. Sin look-ahead.
            for k in _HORIZONS:
                ventana = serie[i + 1: i + 1 + k]
                if not ventana:
                    fila += [None, None, None, 0]
                    continue
                salida = ventana[-1][5]
                altos = [b[3] for b in ventana if b[3] is not None]
                bajos = [b[4] for b in ventana if b[4] is not None]
                ret = ((salida / c - 1.0) * 100.0) if salida else None
                # La MAE recorre TODA la ventana: el peor momento puede caer
                # en cualquier día intermedio, no solo al final.
                mae_s = ((max(altos) / c - 1.0) * 100.0) if altos else None
                mae_l = ((1.0 - min(bajos) / c) * 100.0) if bajos else None
                fila += [ret, mae_s, mae_l, len(ventana)]

            batch.append(tuple(fila))
            n += 1
            if len(batch) >= 5000:
                _flush(conn, batch)
                batch.clear()

    if batch:
        _flush(conn, batch)
    conn.commit()
    return n


def _flush(conn, batch):
    conn.executemany(
        "INSERT OR REPLACE INTO horizons VALUES (" + ",".join("?" * 18) + ")", batch)


def _stat(vals: list[float], label: str, min_n: int = 40) -> None:
    vals = [v for v in vals if v is not None]
    if len(vals) < min_n:
        print(f"    {label:24} n={len(vals):>5}  (insuficiente)")
        return
    s = sorted(vals)
    def p(q):
        return s[min(len(s) - 1, int(q * len(s)))]
    print(f"    {label:24} n={len(s):>5}  mediana={statistics.median(s):>7.2f}%  "
          f"media={statistics.mean(s):>7.2f}%  p75={p(.75):>7.2f}%  p90={p(.90):>7.2f}%")


def report(conn: sqlite3.Connection) -> None:
    base = """
      FROM events e
      JOIN horizons h        ON h.ticker=e.ticker AND h.d=e.d
      JOIN event_structure s ON s.ticker=e.ticker AND s.d=e.d
      WHERE e.gap_pct>20 AND e.dollar_volume>=1e6 AND s.dilution_12m_pct IS NOT NULL
    """
    print("=" * 78)
    print("  RETORNOS POR HORIZONTE — gaps >+20%, vol $>1M")
    print("  signo positivo = el precio SUBIÓ (o sea: pérdida para un short)")
    print("=" * 78)

    for col, etiqueta, nota in (
        ("h.ret_intraday", "INTRADÍA (apertura→cierre)", "COTA SUPERIOR: tiene look-ahead, necesita confirmar con pre-market"),
        ("h.ret_t1", "T+1  (cierre→cierre+1d)", "limpio"),
        ("h.ret_t5", "T+5  (cierre→cierre+5d)", "limpio"),
        ("h.ret_t20", "T+20 (cierre→cierre+20d)", "limpio"),
    ):
        print(f"\n  {etiqueta}   [{nota}]")
        for lo, hi, lab in ((100, 1e18, "dilución >100%"), (25, 100, "dilución 25-100%"),
                            (-1e18, 25, "dilución <25%")):
            vals = [r[0] for r in conn.execute(
                f"SELECT {col} {base} AND s.dilution_12m_pct>=? AND s.dilution_12m_pct<?",
                (lo, hi))]
            _stat(vals, lab)

    print("\n" + "=" * 78)
    print("  MÁXIMA EXCURSIÓN ADVERSA — cuánto se fue EN CONTRA en el peor momento")
    print("  (es lo que decide si sobrevivís a un límite de pérdida diaria)")
    print("=" * 78)
    for col, etiqueta in (
        ("h.mae_short_intraday", "SHORT · intradía"),
        ("h.mae_short_t1", "SHORT · T+1"),
        ("h.mae_short_t5", "SHORT · T+5"),
        ("h.mae_long_intraday", "LARGO · intradía"),
        ("h.mae_long_t5", "LARGO · T+5"),
    ):
        print(f"\n  {etiqueta}")
        for lo, hi, lab in ((100, 1e18, "dilución >100%"), (-1e18, 25, "dilución <25%")):
            vals = [r[0] for r in conn.execute(
                f"SELECT {col} {base} AND s.dilution_12m_pct>=? AND s.dilution_12m_pct<?",
                (lo, hi))]
            _stat(vals, lab)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Multi-horizonte + MAE")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path(), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        if not args.report:
            print("calculando horizontes y MAE…", flush=True)
            n = compute(conn)
            print(f"  {n:,} eventos con horizontes\n")
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
