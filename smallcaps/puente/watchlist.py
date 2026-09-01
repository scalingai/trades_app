#!/usr/bin/env python3
"""Qué papeles mirar hoy. La lista que va a los gráficos de la plataforma.

QUÉ FILTRA Y QUÉ NO. De todo el embudo del sistema, acá sólo se aplica lo que
se puede saber ANTES de la apertura:

  · precio >= $2            (el piso, que es el mismo del backtest)
  · gap contra el cierre previo, hacia arriba
  · volumen en dólares suficiente para que el evento exista como oportunidad
  · float <= 47M            (el único filtro previo que sobrevivió al embudo)

Todo lo demás —expansión contra el máximo premarket, apertura reclaim, las
señales— lo decide `vivo.py` a las 10:00 con las barras que manda la
plataforma. Esta lista NO dice qué operar: dice qué mirar.

EL FLOAT SALE DE DATOS VIEJOS. `shares_outstanding` viene de EDGAR y se cachea
por (ticker, día de evento). Para un papel que nunca vimos, no hay dato — y
entonces NO se descarta, se marca. Descartar por falta de dato dejaría afuera
justamente a los debutantes, que son varios de los mejores días del censo.

    python puente/watchlist.py
    python puente/watchlist.py --min-gap 20 --top 12
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from massive.client import MassiveClient

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

NY = ZoneInfo("America/New_York")
MAX_FLOAT = 47e6
PISO = 2.0


def floats_conocidos():
    """El último `shares_outstanding` visto por ticker, de la base local."""
    try:
        c = sqlite3.connect(config.bars_db_path())
    except Exception:
        return {}
    out = {}
    try:
        for tk, sh in c.execute(
                "SELECT ticker, shares_outstanding FROM event_structure "
                "WHERE shares_outstanding IS NOT NULL ORDER BY d"):
            out[tk] = sh
    except sqlite3.Error:
        pass
    c.close()
    return out


def candidatos(min_gap, min_dolar, piso, max_float):
    """El snapshot de hoy, filtrado. Una sola llamada a la API."""
    cli = MassiveClient()
    d = cli.get("/v2/snapshot/locale/us/markets/stocks/tickers")
    filas = d.get("tickers") or []
    if not filas:
        raise RuntimeError(
            "el snapshot vino vacío — puede que el plan no lo cubra "
            f"(status={d.get('status')!r})")

    flo = floats_conocidos()
    out = []
    for t in filas:
        dia = t.get("day") or {}
        prev = t.get("prevDay") or {}
        # Antes de la apertura `day` viene en cero: se usa el último precio.
        px = dia.get("c") or (t.get("lastTrade") or {}).get("p") or 0
        pc = prev.get("c") or 0
        vol_d = dia.get("v") or 0
        if not px or not pc or px < piso:
            continue
        gap = 100.0 * (px - pc) / pc
        if gap < min_gap:
            continue
        dolar = px * vol_d
        if dolar < min_dolar:
            continue
        tk = t.get("ticker") or ""
        f = flo.get(tk)
        if f is not None and f > max_float:
            continue
        out.append({"ticker": tk, "precio": px, "prev": pc, "gap": gap,
                    "dolar": dolar, "float": f})
    out.sort(key=lambda x: -x["gap"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="La watchlist de hoy")
    ap.add_argument("--min-gap", type=float, default=20.0, help="%% contra el cierre previo")
    ap.add_argument("--min-dolar", type=float, default=5e6)
    ap.add_argument("--piso", type=float, default=PISO)
    ap.add_argument("--max-float", type=float, default=MAX_FLOAT)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args(argv)

    ahora = datetime.now(NY)
    print(f"\n  WATCHLIST · {ahora:%Y-%m-%d %H:%M} NY")
    print(f"  gap >= {args.min_gap:.0f}% · $ >= {args.min_dolar/1e6:.0f}M · "
          f"precio >= ${args.piso:.0f} · float <= {args.max_float/1e6:.0f}M\n")

    try:
        c = candidatos(args.min_gap, args.min_dolar, args.piso, args.max_float)
    except Exception as e:
        print(f"  no se pudo: {e}")
        return 1

    if not c:
        print("  ningún papel pasa el filtro hoy.")
        return 0

    print("  {:<7} {:>9} {:>9} {:>8} {:>11} {:>12}".format(
        "papel", "precio", "previo", "gap", "vol $", "float"))
    print("  " + "-" * 62)
    for x in c[:args.top]:
        fl = ("{:.1f}M".format(x["float"] / 1e6) if x["float"] is not None
              else "sin dato")
        print("  {:<7} ${:>8.2f} ${:>8.2f} {:>7.0f}% ${:>9.1f}M {:>12}".format(
            x["ticker"], x["precio"], x["prev"], x["gap"],
            x["dolar"] / 1e6, fl))

    print(f"\n  {len(c)} candidato(s). Un gráfico de 1 minuto por cada uno,")
    print("  con sesión extendida, y el indicador TTPFeed en cada gráfico.")
    print("  Qué operar de estos lo decide vivo.py a las 10:00, no esta lista.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
