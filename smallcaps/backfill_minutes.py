#!/usr/bin/env python3
"""Etapa C.5 — descarga de barras de 1 minuto sobre una muestra ALEATORIA.

**Aleatoria es el punto, no un detalle.** La prueba anterior eligió los eventos
por cómo terminó el día, y eso hace circular cualquier medición posterior. Acá
la muestra se sortea con semilla fija: reproducible, y sin relación con el
resultado.

La muestra se persiste en una tabla. Si se corta y se relanza, sigue con LOS
MISMOS eventos — si se re-sorteara en cada corrida, el resumir cambiaría la
muestra y el experimento dejaría de ser el mismo.

Sobre la población: se filtra por rango del día completo, que en rigor no se
conoce al mediodía. Eso está bien para ADQUIRIR datos, pero el análisis
posterior tiene que seleccionar por lo observable a la hora de la decisión
(rango hasta las 12:00, no del día entero). La adquisición y el criterio de
entrada son dos cosas distintas.

    python backfill_minutes.py --sample 1500
    python backfill_minutes.py --stats
"""

from __future__ import annotations

import argparse
import random
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

_POBLACION = """
    SELECT ticker, d FROM events
    WHERE range_pct > 40
      AND dollar_volume >= 1e6
      AND close BETWEEN 1 AND 20
      AND d < date('now','-10 day')
    ORDER BY ticker, d
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS minute_sample (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    seed   INTEGER NOT NULL,
    PRIMARY KEY (ticker, d)
);
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill de minutos, muestra aleatoria")
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path(), timeout=120)
    conn.executescript(_SCHEMA)
    conn.commit()
    store = MinuteStore()

    if args.stats:
        n_s = conn.execute("SELECT COUNT(*) FROM minute_sample").fetchone()[0]
        n_ok = store.conn.execute(
            "SELECT COUNT(*) FROM minute_log WHERE status='ok'").fetchone()[0]
        n_b = store.conn.execute("SELECT COUNT(*) FROM bars_minute").fetchone()[0]
        mb = store.path.stat().st_size / 1e6 if store.path.exists() else 0
        print(f"  muestra sorteada   {n_s:,}")
        print(f"  ya bajados         {n_ok:,}")
        print(f"  barras de minuto   {n_b:,}")
        print(f"  base               {mb:,.0f} MB en {store.path}")
        store.close(); conn.close()
        return 0

    # Sortear una sola vez y persistir: relanzar no debe cambiar la muestra.
    ya_sorteada = conn.execute("SELECT ticker, d FROM minute_sample").fetchall()
    if not ya_sorteada:
        poblacion = conn.execute(_POBLACION).fetchall()
        print(f"población: {len(poblacion):,} eventos")
        rng = random.Random(args.seed)
        muestra = rng.sample(poblacion, min(args.sample, len(poblacion)))
        conn.executemany(
            "INSERT OR IGNORE INTO minute_sample VALUES (?,?,?)",
            [(t, d, args.seed) for t, d in muestra])
        conn.commit()
        print(f"muestra sorteada con semilla {args.seed}: {len(muestra):,} eventos")
    else:
        muestra = ya_sorteada
        print(f"muestra ya sorteada: {len(muestra):,} eventos (se reutiliza)")

    ya = store.done()
    pend = [(t, d) for t, d in muestra if (t, d) not in ya]

    print("=" * 64)
    print("  BACKFILL DE MINUTOS — muestra aleatoria")
    print(f"  pendientes: {len(pend):,}  ·  ~{len(pend)/5/60:.1f} h a "
          f"{config.polygon_rate_limit()}/min")
    print(f"  destino: {store.path}")
    print("=" * 64, flush=True)

    if not pend:
        print("  nada pendiente.")
        store.close(); conn.close()
        return 0

    client = MassiveClient()
    t0 = time.time()
    barras = ok = vacios = err = 0

    for i, (t, d) in enumerate(pend, 1):
        n, st = fetch_event(client, store, t, date.fromisoformat(d))
        barras += n
        if st == "ok":
            ok += 1
        elif st == "empty":
            vacios += 1
        else:
            err += 1
        if i % 25 == 0 or i == len(pend):
            el = time.time() - t0
            print(f"  [{i:>5}/{len(pend)}] {barras:>9,} barras  ·  ok {ok:,} · "
                  f"vacíos {vacios:,} · errores {err:,}  ·  "
                  f"faltan ~{(el/i)*(len(pend)-i)/3600:.1f} h", flush=True)

    mb = store.path.stat().st_size / 1e6
    print(f"\n  {barras:,} barras en {(time.time()-t0)/3600:.1f} h  ·  {mb:,.0f} MB")
    store.close(); conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
