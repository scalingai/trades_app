#!/usr/bin/env python3
"""Etapa C.1 — backfill de barras diarias de TODO el mercado US.

Una llamada por día de trading trae ~15.000 tickers. Con el tier free
(5 llamadas/min) son ~100 minutos para 2 años.

**Resumable**: se puede cortar y relanzar cuando sea; arranca donde quedó.

    python backfill_daily.py                 # 2 años hacia atrás
    python backfill_daily.py --days 90       # solo los últimos 90 días
    python backfill_daily.py --stats         # ver qué hay sin bajar nada
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta

import config
from massive import BarStore, MassiveClient, MassiveError, NotAuthorized

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# El tier free cubre 2 años. Dejamos margen para no chocar el borde y comerse
# un 403 en cada una de las últimas fechas.
_FREE_TIER_DAYS = 365 * 2 - 10


def trading_days(since: date, until: date) -> list[date]:
    """Días hábiles del rango, del más reciente al más viejo.

    No filtramos feriados: la API responde vacío y eso se marca como 'empty',
    que además nos da el calendario real de feriados gratis. Codificar un
    calendario a mano sería una fuente de bugs sin ninguna ventaja.
    """
    out, d = [], until
    while d >= since:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill diario de barras (Massive)")
    ap.add_argument("--days", type=int, default=_FREE_TIER_DAYS,
                    help=f"cuántos días hacia atrás (default {_FREE_TIER_DAYS} = plan free)")
    ap.add_argument("--stats", action="store_true", help="solo mostrar estado")
    ap.add_argument("--no-otc", action="store_true",
                    help="excluir OTC (muchas micro caps cotizan ahí — no recomendado)")
    args = ap.parse_args(argv)

    store = BarStore()
    if args.stats:
        for k, v in store.stats().items():
            print(f"  {k:20} {v:,}" if isinstance(v, (int, float)) else f"  {k:20} {v}")
        store.close()
        return 0

    try:
        client = MassiveClient()
    except config.MissingConfig as exc:
        print(exc, file=sys.stderr)
        store.close()
        return 1

    hoy = date.today()
    todos = trading_days(hoy - timedelta(days=args.days), hoy)
    ya = store.done_dates()
    pendientes = [d for d in todos if d.isoformat() not in ya]

    print("=" * 64)
    print("  BACKFILL DIARIO — mercado US completo")
    print(f"  rango:      {todos[-1]} → {todos[0]}  ({len(todos)} días hábiles)")
    print(f"  ya bajados: {len(todos) - len(pendientes)}")
    print(f"  pendientes: {len(pendientes)}")
    print(f"  throttle:   {config.polygon_rate_limit()} llamadas/min "
          f"→ ~{len(pendientes) * 60 / max(1, config.polygon_rate_limit()) / 60:.0f} min")
    print(f"  destino:    {store.path}")
    print("=" * 64, flush=True)

    if not pendientes:
        print("  nada pendiente.")
        store.close()
        return 0

    t0 = time.time()
    ok = vacios = errores = recientes_omitidos = 0
    filas = 0

    for i, d in enumerate(pendientes, 1):
        try:
            rows = client.grouped_daily(d, include_otc=not args.no_otc)
        except NotAuthorized:
            # Un 403 significa dos cosas OPUESTAS según dónde caiga, y el
            # barrido va de nuevo a viejo:
            #   · antes del primer éxito → la fecha es DEMASIADO RECIENTE
            #     (el tier free tiene delay de end-of-day). Saltear y seguir.
            #   · después del primer éxito → cruzamos el borde del histórico
            #     del plan. Todo lo más viejo falla igual: cortar.
            # NO se escribe en ingest_log: la fecha queda pendiente para que un
            # run futuro la agarre cuando el dato ya esté publicado.
            if ok or vacios:
                print(f"\n  {d}: fuera del histórico del plan — corto acá.", flush=True)
                break
            recientes_omitidos += 1
            print(f"  {d}: aún no publicado (delay EOD del plan) — salteo.", flush=True)
            continue
        except MassiveError as exc:
            errores += 1
            print(f"  {d}: ERROR {exc}", flush=True)
            continue

        n = store.save_day(d, rows)
        filas += n
        if n:
            ok += 1
        else:
            vacios += 1

        if i % 10 == 0 or i == len(pendientes):
            transcurrido = time.time() - t0
            resta = (transcurrido / i) * (len(pendientes) - i)
            print(f"  [{i:>3}/{len(pendientes)}] {d}  "
                  f"{n:>6,} tickers  ·  acumulado {filas:>10,} barras  ·  "
                  f"faltan ~{resta/60:.0f} min", flush=True)

    st = store.stats()
    print("\n" + "=" * 64)
    print(f"  días con datos {st['dias_con_datos']:,}  ·  vacíos {st['dias_vacios']:,}"
          f"  ·  errores {errores}  ·  aún no publicados {recientes_omitidos}")
    print(f"  {st['barras']:,} barras  ·  {st['tickers_distintos']:,} tickers distintos")
    print(f"  rango: {st['desde']} → {st['hasta']}")
    print(f"  base:  {st['db_mb']:,.0f} MB en {store.path}")
    print(f"  llamadas usadas: {client.calls_made}  ·  {(time.time()-t0)/60:.1f} min")
    print("=" * 64)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
