#!/usr/bin/env python3
"""¿Y si en vez de un trade largo por día hacemos varios cortos?

Todo lo anterior probó UNA entrada al mediodía con hold de 1 a 4 horas. Eso da
~19 a 257 operaciones por año según cuántos filtros se apilen. La objeción de
Agus es válida: no puede ser tan poco.

Acá se prueba lo contrario: entradas en varios momentos del día y holds cortos.

**El argumento a favor, que sale de la aritmética de costos:** los targets
chicos fallaban por el costo de 1,38% sobre un precio mediano de $2,89. Pero
arriba de $5 el costo es 0,46%, y ahí un scalp de 2% sí puede pagar. Por eso
todo se reporta separado por banda de precio.

**Lo que hay que tener presente:** varias entradas en el MISMO día y el MISMO
ticker no son trades independientes. Suman frecuencia pero no diversifican
riesgo — si el día sale mal, salen mal todas juntas.

    python test_scalping.py
    python test_scalping.py --spread-cents 3
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date

from massive.minutes import MinuteStore
from test_signals import APERTURA_RTH

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Momentos de entrada candidatos: cada media hora de la sesión regular.
HORAS = [10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0]


def dia(bars, costo_acc: float, holds: tuple[int, ...], target_pct: float,
        stop_pct: float) -> list[dict]:
    """Todas las operaciones que el día genera, en cada horario y cada hold."""
    def h(b):
        return b[0].hour + b[0].minute / 60.0

    rth = [b for b in bars if h(b) >= APERTURA_RTH]
    if len(rth) < 60:
        return []
    apertura = rth[0][1]
    if not apertura:
        return []

    out = []
    for hora in HORAS:
        prev = [b for b in rth if h(b) <= hora]
        if len(prev) < 10:
            continue
        entrada = prev[-1][4]
        # La única señal que sobrevivió: precio debajo de la apertura.
        if not entrada or entrada >= apertura:
            continue
        post = [b for b in rth if h(b) > hora]
        if not post:
            continue
        costo_pct = costo_acc / entrada * 100.0

        for mins in holds:
            ventana = post[:mins]
            if len(ventana) < max(5, mins // 3):
                continue
            ps = entrada * (1 + stop_pct / 100.0)
            pt = entrada * (1 - target_pct / 100.0)
            salida, motivo = None, "tiempo"
            for b in ventana:
                if b[2] and b[2] >= ps:
                    salida, motivo = ps, "stop"
                    break
                if b[3] and b[3] <= pt:
                    salida, motivo = pt, "target"
                    break
            if salida is None:
                salida = ventana[-1][4]
            if not salida:
                continue
            bruto = (entrada / salida - 1.0) * 100.0
            out.append({"hold": mins, "hora": hora, "precio": entrada,
                        "bruto": bruto, "neto": bruto - costo_pct, "motivo": motivo})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scalping: más trades, más cortos")
    ap.add_argument("--spread-cents", type=float, default=2.0)
    ap.add_argument("--comision", type=float, default=0.005)
    ap.add_argument("--locate", type=float, default=0.01)
    ap.add_argument("--target", type=float, default=3.0)
    ap.add_argument("--stop", type=float, default=3.0)
    args = ap.parse_args(argv)

    costo_acc = args.spread_cents / 100.0 + args.comision * 2 + args.locate
    holds = (15, 30, 60, 120)

    store = MinuteStore()
    eventos = store.conn.execute(
        "SELECT ticker,d FROM minute_log WHERE status='ok'").fetchall()
    trades, n_dias = [], 0
    for t, d in eventos:
        ops = dia(store.day_bars(t, date.fromisoformat(d)), costo_acc,
                  holds, args.target, args.stop)
        if ops:
            n_dias += 1
        trades.extend(ops)

    print("=" * 90)
    print(f"  SCALPING · target {args.target}% / stop {args.stop}% · costo "
          f"${costo_acc:.3f}/acción")
    print(f"  {len(eventos)} días analizados · {n_dias} generaron operaciones · "
          f"{len(trades)//len(holds) if holds else 0} entradas por hold")
    print("=" * 90)

    factor = 1500 / max(1, len(eventos)) / 2  # a muestra completa, por año

    for banda, lo, hi in (("$1-3", 1, 3), ("$3-5", 3, 5), ("$5+", 5, 1e9)):
        sub = [x for x in trades if lo <= x["precio"] < hi]
        if len(sub) < 60:
            print(f"\n  {banda}: n={len(sub)}, insuficiente")
            continue
        pm = statistics.median(x["precio"] for x in sub)
        print(f"\n  BANDA {banda}   precio mediano ${pm:.2f}   "
              f"costo {costo_acc/pm*100:.2f}% por trade")
        print(f"    {'hold':>6} {'trades':>7} {'/año':>7} {'bruto':>8} {'NETO':>8} "
              f"{'gana':>6} {'acum/año':>9}")
        for m in holds:
            g = [x for x in sub if x["hold"] == m]
            if len(g) < 30:
                continue
            neto = statistics.mean(x["neto"] for x in g)
            bruto = statistics.mean(x["bruto"] for x in g)
            gana = 100 * sum(1 for x in g if x["neto"] > 0) / len(g)
            por_año = len(g) * factor
            marca = "  <-" if neto > 0 else ""
            print(f"    {m:>5}m {len(g):>7} {por_año:>7.0f} {bruto:>+7.2f}% "
                  f"{neto:>+7.2f}% {gana:>5.0f}% {neto*por_año:>+8.0f}%{marca}")

    print("\n  'acum/año' = neto por trade x trades por año. Es una cota OPTIMISTA:")
    print("  varias entradas en el mismo día no son independientes y no se pueden")
    print("  tomar todas con el mismo capital.")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
