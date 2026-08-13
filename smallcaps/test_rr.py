#!/usr/bin/env python3
"""Simulación de stop/target con costos, sobre la señal que sobrevivió.

Entrada: short al mediodía en los días que cumplen «precio debajo de la
apertura», cruzado con la firma de dilución. Se camina minuto a minuto hasta
las 16:00 y se ve qué toca primero.

**Tres honestidades sobre esta simulación:**

1. **El spread NO se mide, se asume.** Las barras traen OHLCV, no bid/ask. Se
   parametriza y se reporta la sensibilidad. Es el supuesto más grande acá.

2. **Si el stop y el target caen en el mismo minuto, gana el STOP.** No se sabe
   el orden dentro de la barra; asumir lo favorable sería inventar plata.

3. **La grilla de stop/target NO se optimiza.** Se reporta entera. Elegir la
   celda que mejor da sería exactamente el sobreajuste que venimos evitando —
   la grilla sirve para ver la FORMA del costo, no para elegir parámetros.

Además el stop se asume ejecutado a su precio exacto. En small caps que haltean
eso es optimista: el fill real suele ser peor. Se puede castigar con --slip-stop.

    python test_rr.py
    python test_rr.py --spread-cents 3 --comision 0.005 --locate 0.01
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from datetime import date

import config
from massive.minutes import MinuteStore
from test_signals import señales

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def simular(bars, hora, entrada, stop_pct, target_pct, slip_stop_pct):
    """Short desde `entrada`. Devuelve retorno bruto % y qué pasó."""
    def h(b):
        return b[0].hour + b[0].minute / 60.0

    post = [b for b in bars if hora <= h(b) <= 16.0]
    if not post:
        return None
    p_stop = entrada * (1 + stop_pct / 100.0)
    p_target = entrada * (1 - target_pct / 100.0)

    for b in post:
        alto, bajo = b[2], b[3]
        # Conservador: si en el mismo minuto se tocan los dos, gana el stop.
        if alto and alto >= p_stop:
            salida = p_stop * (1 + slip_stop_pct / 100.0)
            return (entrada / salida - 1.0) * 100.0, "stop"
        if bajo and bajo <= p_target:
            return (entrada / p_target - 1.0) * 100.0, "target"
    return (entrada / post[-1][4] - 1.0) * 100.0, "cierre"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stop/target con costos")
    ap.add_argument("--hora", type=float, default=12.0)
    ap.add_argument("--spread-cents", type=float, default=2.0,
                    help="spread asumido en centavos (round trip)")
    ap.add_argument("--comision", type=float, default=0.005,
                    help="comisión por acción, por lado")
    ap.add_argument("--locate", type=float, default=0.01,
                    help="fee de locate por acción (short, se paga siempre)")
    ap.add_argument("--slip-stop", type=float, default=0.0,
                    help="castigo extra %% sobre el precio del stop")
    ap.add_argument("--min-n", type=int, default=25)
    args = ap.parse_args(argv)

    store = MinuteStore()
    bars_db = sqlite3.connect(config.bars_db_path())
    dil = {(t, d): x for t, d, x in bars_db.execute(
        "SELECT ticker,d,dilution_12m_pct FROM event_structure "
        "WHERE dilution_12m_pct IS NOT NULL")}

    casos = []
    for t, d in store.conn.execute("SELECT ticker,d FROM minute_log WHERE status='ok'"):
        bars = store.day_bars(t, date.fromisoformat(d))
        s = señales(bars, args.hora)
        if not s or not s["bajo_apertura"]:
            continue  # la única señal que sobrevivió
        def hh(b):
            return b[0].hour + b[0].minute / 60.0
        antes = [b for b in bars if hh(b) < args.hora]
        if not antes:
            continue
        casos.append({"t": t, "d": d, "bars": bars, "entrada": antes[-1][4],
                      "dil": dil.get((t, d))})

    con_dil = [c for c in casos if c["dil"] is not None and c["dil"] > 50]
    print("=" * 92)
    print(f"  SHORT AL MEDIODÍA · señal «debajo de la apertura» · corte {int(args.hora):02d}:00")
    print(f"  días que cumplen la señal: {len(casos)}   ·   además con dilución >50%: {len(con_dil)}")
    print(f"  costos: spread {args.spread_cents}c + comisión {args.comision}/acc x2 "
          f"+ locate {args.locate}/acc")
    print("=" * 92)

    for grupo, etiqueta in ((casos, "TODOS los que cumplen la señal"),
                            (con_dil, "SOLO los que además diluyeron >50%")):
        if len(grupo) < args.min_n:
            print(f"\n  {etiqueta}: n={len(grupo)}, insuficiente")
            continue
        precio_med = statistics.median(c["entrada"] for c in grupo)
        # Costo por acción -> % sobre el precio típico de entrada
        costo_acc = args.spread_cents / 100.0 + args.comision * 2 + args.locate
        costo_pct = costo_acc / precio_med * 100.0

        print(f"\n  {etiqueta}   n={len(grupo)}   precio mediano ${precio_med:.2f}")
        print(f"  costo total ida y vuelta: ${costo_acc:.3f}/acción = "
              f"{costo_pct:.2f}% del precio")
        print(f"\n  {'stop':>6} {'target':>7} {'R:R':>6} {'gana':>6} "
              f"{'bruto':>9} {'NETO':>9} {'stops':>6} {'cierre':>7}")
        print("  " + "-" * 74)

        for stop in (3, 5, 8, 12):
            for target in (3, 5, 8, 12, 20):
                res = [simular(c["bars"], args.hora, c["entrada"], stop, target,
                               args.slip_stop) for c in grupo]
                res = [r for r in res if r]
                if len(res) < args.min_n:
                    continue
                rets = [r[0] for r in res]
                bruto = statistics.mean(rets)
                neto = bruto - costo_pct
                gana = 100 * sum(1 for r in rets if r > 0) / len(rets)
                n_stop = 100 * sum(1 for r in res if r[1] == "stop") / len(res)
                n_cie = 100 * sum(1 for r in res if r[1] == "cierre") / len(res)
                marca = "  <-" if neto > 0 else ""
                print(f"  {stop:>5}% {target:>6}% {target/stop:>5.1f} {gana:>5.0f}% "
                      f"{bruto:>+8.2f}% {neto:>+8.2f}% {n_stop:>5.0f}% {n_cie:>6.0f}%{marca}")

    print("\n  NOTA: la grilla se reporta ENTERA. Elegir la mejor celda sería")
    print("  sobreajuste — sirve para ver la forma del costo, no para fijar parámetros.")
    store.close()
    bars_db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
