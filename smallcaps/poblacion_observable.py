#!/usr/bin/env python3
"""La población completa seleccionada por lo que se sabe ANTES de la apertura.

**Esto elimina el sesgo, no lo mitiga.** La muestra de `backfill_minutes.py` se
sorteó de días con `range_pct > 40` —el rango del día COMPLETO—, que a las 09:30
no se conoce. Ese sesgo está anotado abajo de cada tabla del proyecto y hasta
ahora no se podía sacar, solo declarar.

Los dos criterios de acá son observables antes de que suene la campana:

  · `gap_pct`           apertura vs cierre previo — se conoce a las 09:30
  · `med_dollar_volume` mediana en dólares de los 20 días PREVIOS
  · `prev_close`        el precio de ayer, para la banda

Ninguno usa nada del día. Y con umbrales de gap ≥ 25% y liquidez previa ≥ $150k
la población entera son ~2.000 eventos: **entra completa**. No hay muestreo, así
que tampoco hay sesgo de muestreo — es el censo de la población objetivo.

Es resumable: relanzar sigue donde quedó. Con el tier free son ~6 horas.

    python poblacion_observable.py --stats
    python poblacion_observable.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date

import config
from massive import MassiveClient
from massive.minutes import MinuteStore, fetch_event

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS poblacion_obs (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    gap_pct REAL,
    med_dollar_volume REAL,
    prev_close REAL,
    PRIMARY KEY (ticker, d)
);
"""

_CONSULTA = """
    SELECT ticker, d, gap_pct, med_dollar_volume, prev_close FROM events
    WHERE gap_pct >= ?
      AND med_dollar_volume >= ?
      AND prev_close BETWEEN ? AND ?
      AND d < date('now', ?)
    ORDER BY d, ticker
"""

# Diez días de margen: los agregados diarios de los últimos días se corrigen
# (splits tardíos, trades fuera de hora que entran después), así que un evento
# recién ocurrido puede cambiar de gap o de liquidez. Para el censo histórico
# eso es contaminación; para una prueba hacia adelante sobre días recientes es
# un costo aceptable y explícito. De ahí que sea parámetro y no constante.
MARGEN_DEFECTO = "-10 day"


def definir(conn, *, min_gap, min_liq, precio_min, precio_max,
            margen=MARGEN_DEFECTO) -> int:
    conn.executescript(_SCHEMA)
    filas = conn.execute(
        _CONSULTA, (min_gap, min_liq, precio_min, precio_max, margen)).fetchall()
    conn.executemany(
        "INSERT OR IGNORE INTO poblacion_obs VALUES (?,?,?,?,?)", filas)
    conn.commit()
    return len(filas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Descarga de la población observable")
    ap.add_argument("--min-gap", type=float, default=25.0)
    ap.add_argument("--min-liq", type=float, default=1.5e5)
    ap.add_argument("--precio-min", type=float, default=0.20)
    ap.add_argument("--precio-max", type=float, default=20.0)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--margen", default=MARGEN_DEFECTO,
                    help="cuánto esperar antes de admitir un día "
                         "(default -10 day; usar '-0 day' sólo para pruebas)")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path(), timeout=120)
    store = MinuteStore()
    n = definir(conn, min_gap=args.min_gap, min_liq=args.min_liq,
                precio_min=args.precio_min, precio_max=args.precio_max,
                margen=args.margen)
    pob = [(t, d) for t, d in conn.execute("SELECT ticker,d FROM poblacion_obs")]
    ya = {(t, d) for t, d in store.conn.execute("SELECT ticker,d FROM minute_log")}
    pend = [x for x in pob if x not in ya]

    print("=" * 72)
    print("  POBLACIÓN OBSERVABLE — el censo, no una muestra")
    print(f"  gap >= {args.min_gap:.0f}%  ·  liquidez previa >= ${args.min_liq/1e3:.0f}k  ·  "
          f"precio ${args.precio_min:.2f}-${args.precio_max:.0f}")
    print(f"  {n:,} eventos  ·  {len(pob)-len(pend):,} ya bajados  ·  "
          f"{len(pend):,} pendientes (~{len(pend)/5/60:.1f} h)")
    print("=" * 72, flush=True)

    if args.stats or not pend:
        store.close()
        conn.close()
        return 0

    client = MassiveClient()
    t0 = time.time()
    barras = ok = vacios = err = 0
    # El ETA se estima con las últimas 25, no con el promedio acumulado: un solo
    # stall de la API (429 con backoff, o un timeout) envenena el promedio para
    # siempre y el número deja de servir para decidir si seguir esperando.
    t_tramo = t0
    for i, (t, d) in enumerate(pend, 1):
        nb, st = fetch_event(client, store, t, date.fromisoformat(d))
        barras += nb
        ok += st == "ok"
        vacios += st == "empty"
        err += st not in ("ok", "empty")
        if i % 25 == 0 or i == len(pend):
            ahora = time.time()
            por_evento = (ahora - t_tramo) / 25
            t_tramo = ahora
            print(f"  [{i:>5}/{len(pend)}] {barras:>9,} barras · ok {ok:,} · "
                  f"vacíos {vacios:,} · errores {err:,} · "
                  f"{por_evento:.0f} s/evento · "
                  f"faltan ~{por_evento*(len(pend)-i)/3600:.1f} h "
                  f"(acumulado {(ahora-t0)/3600:.1f} h)", flush=True)

    print(f"\n  {barras:,} barras en {(time.time()-t0)/3600:.1f} h")
    store.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
