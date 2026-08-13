#!/usr/bin/env python3
"""Diseño de gestión de riesgo, derivado de la distribución medida.

No se puede diseñar esto desde la teoría. La estrategia tiene **mediana
negativa y media positiva**: se pierde la mayoría de las veces y se gana en las
pocas. Eso produce rachas perdedoras largas, y una cuenta con límite de
drawdown muere en la racha aunque la estrategia sea buena.

Entonces la pregunta de diseño no es «cuánto puedo ganar» sino **«qué tamaño
sobrevive a la peor racha que esta distribución produce»**.

Método: se toman los retornos REALES de los trades (no una distribución
teórica) y se remuestrean miles de veces para ver la forma de las rachas y la
probabilidad de tocar cada límite.

Reglas de la cuenta que se modelan:
  · límite de pérdida diaria — si se toca, no se opera más ese día
  · drawdown máximo total — si se toca, la cuenta muere

    python riesgo.py
    python riesgo.py --buying-power 25000 --limite-diario 2 --dd-max 4
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from datetime import date

from massive.minutes import MinuteStore
from test_signals import señales

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

STOP_PCT = 12.0
TARGET_PCT = 20.0
FRAC_TARGET = 0.5  # se toma la mitad en el target y el resto corre a break-even


def retornos_reales(min_precio: float) -> list[float]:
    """Retornos brutos de cada trade, con la salida escalonada."""
    store = MinuteStore()

    def h(b):
        return b[0].hour + b[0].minute / 60.0

    out = []
    for t, d in store.conn.execute("SELECT ticker,d FROM minute_log WHERE status='ok'"):
        bars = store.day_bars(t, date.fromisoformat(d))
        s = señales(bars, 12.0)
        if not s or not s["bajo_apertura"]:
            continue
        antes = [b for b in bars if h(b) < 12.0]
        if not antes or not antes[-1][4] or antes[-1][4] < min_precio:
            continue
        e = antes[-1][4]
        post = [b for b in bars if 12.0 <= h(b) <= 16.0]
        if not post:
            continue
        ps, pt = e * (1 + STOP_PCT / 100), e * (1 - TARGET_PCT / 100)
        r, tomo = 0.0, False
        for b in post:
            if b[2] and b[2] >= ps:
                r += (0.0 if tomo else 1.0) * (e / ps - 1) * 100
                break
            if not tomo and b[3] and b[3] <= pt:
                r += FRAC_TARGET * (e / pt - 1) * 100
                tomo, ps = True, e   # el resto corre con stop en break-even
        else:
            r += (1 - FRAC_TARGET if tomo else 1.0) * (e / post[-1][4] - 1) * 100
        out.append(r)
    store.close()
    return out


def simular(rets, riesgo_pct, bp, limite_diario_pct, dd_max_pct,
            trades_por_dia, dias, rng):
    """Una corrida de `dias` días. Devuelve (retorno %, murió, días operados)."""
    equity = bp
    pico = bp
    limite_d = bp * limite_diario_pct / 100
    dd_max = bp * dd_max_pct / 100
    riesgo = bp * riesgo_pct / 100
    operados = 0

    for _ in range(dias):
        perdida_hoy = 0.0
        for _ in range(trades_por_dia):
            if perdida_hoy >= limite_d:
                break
            g = rng.choice(rets)
            # Con stop de 12%, arriesgar `riesgo` implica posición riesgo/0.12.
            pnl = riesgo * (g / STOP_PCT)
            equity += pnl
            operados += 1
            if pnl < 0:
                perdida_hoy += -pnl
            pico = max(pico, equity)
            if pico - equity >= dd_max:
                return (equity / bp - 1) * 100, True, operados
    return (equity / bp - 1) * 100, False, operados


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diseño de gestión de riesgo")
    ap.add_argument("--buying-power", type=float, default=25000)
    ap.add_argument("--limite-diario", type=float, default=2.0)
    ap.add_argument("--dd-max", type=float, default=4.0)
    ap.add_argument("--min-precio", type=float, default=3.0)
    ap.add_argument("--dias", type=int, default=120)
    ap.add_argument("--corridas", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)

    rets = retornos_reales(args.min_precio)
    if len(rets) < 50:
        print(f"muestra insuficiente ({len(rets)})", file=sys.stderr)
        return 1

    s = sorted(rets)
    perdedores = sum(1 for x in rets if x < 0)
    print("=" * 84)
    print(f"  DISTRIBUCIÓN REAL DE LOS TRADES  (precio >= ${args.min_precio:.0f}, n={len(rets)})")
    print("=" * 84)
    print(f"  media {statistics.mean(rets):+.2f}%   ·   mediana {statistics.median(rets):+.2f}%"
          f"   ·   pierden el {100*perdedores/len(rets):.0f}%")
    print(f"  peor {min(rets):+.1f}%   ·   mejor {max(rets):+.1f}%")

    rng = random.Random(args.seed)
    rachas = []
    for _ in range(2000):
        racha = mx = 0
        for _ in range(100):
            if rng.choice(rets) < 0:
                racha += 1
                mx = max(mx, racha)
            else:
                racha = 0
        rachas.append(mx)
    rachas.sort()
    print(f"\n  RACHAS PERDEDORAS en 100 trades: típica {statistics.median(rachas):.0f} seguidas"
          f"  ·  p95 {rachas[int(len(rachas)*.95)]:.0f}  ·  peor {max(rachas)}")

    print(f"\n{'=' * 84}")
    print(f"  SIMULACIÓN · buying power ${args.buying_power:,.0f} · límite diario "
          f"{args.limite_diario}% · drawdown máx {args.dd_max}%")
    print(f"  {args.corridas:,} corridas de {args.dias} días hábiles (~6 meses)")
    print("=" * 84)
    print(f"\n  {'riesgo/trade':>13} {'posición':>10} {'trades/día':>11} "
          f"{'MURIÓ':>8} {'ret. mediano':>13} {'p10':>9} {'p90':>9}")
    print("  " + "-" * 78)

    for riesgo_pct in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        for tpd in (1, 2, 3):
            res = [simular(rets, riesgo_pct, args.buying_power, args.limite_diario,
                           args.dd_max, tpd, args.dias, random.Random(args.seed + i))
                   for i in range(args.corridas)]
            muertos = 100 * sum(1 for r in res if r[1]) / len(res)
            finales = sorted(r[0] for r in res)
            pos = args.buying_power * riesgo_pct / 100 / (STOP_PCT / 100)
            marca = "  <-" if muertos < 10 and statistics.median(finales) > 0 else ""
            print(f"  {riesgo_pct:>12.2f}% ${pos:>9,.0f} {tpd:>11} {muertos:>7.0f}% "
                  f"{statistics.median(finales):>+12.1f}% "
                  f"{finales[int(len(finales)*.10)]:>+8.1f}% "
                  f"{finales[int(len(finales)*.90)]:>+8.1f}%{marca}")

    print("\n  'MURIÓ' = % de corridas que tocaron el drawdown máximo y perdieron la cuenta.")
    print("  Marcadas con <- las que mueren en menos del 10% de los casos Y dan positivo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
