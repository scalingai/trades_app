#!/usr/bin/env python3
"""Simulador de SESIÓN: riesgo en dólares por día, varios trades, y se cierra.

**El esquema que pidió Agus.** En vez de medir trades sueltos en porcentaje, se
opera una jornada con un presupuesto: *arriesgo hasta $R en el día y busco ganar
al menos $R. Puede salir en varios trades. Cuando llego, cierro y espero otra
oportunidad.*

Eso cambia tres cosas respecto de todo lo anterior:

  1. **Nominal completo en cada entrada**, no una escalera. Está medido que la
     escalera despliega más capital cuando falla que cuando acierta.
  2. **El tamaño lo fija el riesgo, no el capital.** Con un stop del 15% y $50 de
     riesgo, la posición es de $333 — el precio del papel no decide el tamaño.
  3. **La jornada tiene principio y fin.** Se corta por objetivo o por límite, y
     lo que se mide es el resultado del DÍA, que es la unidad en la que se vive.

Las entradas salen de las señales de agotamiento de volumen, con el filtro de
liquidez y una separación mínima entre trades para no reentrar en el mismo
movimiento.

    python sesion.py
    python sesion.py --riesgo 50 --objetivo 50 --stop 15
    python sesion.py --objetivo 0        # sin objetivo: correr hasta el cierre
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import Counter

import config
from chavineta import clasificar_apertura
from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"


def señales(dia, *, caida=0.5, sin_maximo=10, separacion=0.5,
            desde=9.75, hasta=15.0, min_liquidez=2.5e5):
    """Todos los minutos de agotamiento de volumen, separados entre sí."""
    climax, ultimo, out = 0.0, -99.0, []
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h < APERTURA_RTH:
            continue
        v = b[5] or 0.0
        if v > climax:
            climax = v
        if h < desde or h > hasta or climax <= 0 or h - ultimo < separacion:
            continue
        prev = dia.bars[max(0, i - 4):i + 1]
        if sum(x[5] or 0 for x in prev) / len(prev) >= caida * climax:
            continue
        if dia.edad_max[i] < sin_maximo:
            continue
        if min_liquidez > 0 and (dia.liquidez_en(h) or 0) < min_liquidez:
            continue
        ultimo = h
        out.append(i)
    return out


def trade(dia, i, *, stop_pct, riesgo, costo_accion):
    """Short con nominal dimensionado por el riesgo. Devuelve (pnl $, motivo)."""
    p = dia.bars[i][4]
    if not p or stop_pct <= 0:
        return None
    # El tamaño sale del riesgo, no del capital: si el stop es 15% y arriesgo
    # $50, la posición vale $333 sin importar si el papel vale $1 o $12.
    acciones = riesgo / (p * stop_pct / 100.0)
    p_stop = p * (1 + stop_pct / 100.0)
    for b in dia.bars[i + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        if b[2] and b[2] >= p_stop:
            return -riesgo - acciones * costo_accion, "stop", acciones
    c = dia.rth_close
    if not c:
        return None
    return acciones * (p - c) - acciones * costo_accion, "cierre", acciones


def jornada(dia, *, riesgo_dia, riesgo_trade, objetivo, stop_pct, costo_accion,
            max_trades, min_liquidez):
    """Opera un día completo con presupuesto. Devuelve el resultado de la jornada."""
    if clasificar_apertura(dia) != "fade":
        return None
    ses = señales(dia, min_liquidez=min_liquidez)
    if not ses:
        return None

    pnl, n, motivos = 0.0, 0, []
    for i in ses:
        if n >= max_trades:
            break
        # No abrir un trade que pueda pasarse del límite del día.
        if pnl - riesgo_trade < -riesgo_dia:
            motivos.append("limite")
            break
        r = trade(dia, i, stop_pct=stop_pct, riesgo=riesgo_trade,
                  costo_accion=costo_accion)
        if not r:
            continue
        pnl += r[0]
        n += 1
        motivos.append(r[1])
        if objetivo > 0 and pnl >= objetivo:
            motivos.append("objetivo")
            break
    if n == 0:
        return None
    return {"ticker": dia.ticker, "d": dia.d, "pnl": pnl, "trades": n,
            "cierre_por": motivos[-1],
            "per": "P1" if dia.d < CORTE_PERIODO else "P2"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Simulador de sesión con presupuesto")
    ap.add_argument("--riesgo", type=float, default=50.0,
                    help="dólares máximos a perder en el día")
    ap.add_argument("--riesgo-trade", type=float, default=0.0,
                    help="riesgo por trade (0 = un tercio del diario)")
    ap.add_argument("--objetivo", type=float, default=50.0,
                    help="dólares a los que se cierra la jornada (0 = sin objetivo)")
    ap.add_argument("--stop", type=float, default=15.0)
    ap.add_argument("--max-trades", type=int, default=3)
    ap.add_argument("--min-expansion", type=float, default=100.0)
    ap.add_argument("--min-liquidez", type=float, default=2.5e5)
    ap.add_argument("--costo", type=float, default=0.04,
                    help="costo por acción, round trip (spread+comisión+locate)")
    args = ap.parse_args(argv)
    rt = args.riesgo_trade or args.riesgo / 3.0

    db = sqlite3.connect(config.bars_db_path())
    jornadas = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3:
            continue
        if (dia.expansion_pct or 0) < args.min_expansion:
            continue
        j = jornada(dia, riesgo_dia=args.riesgo, riesgo_trade=rt,
                    objetivo=args.objetivo, stop_pct=args.stop,
                    costo_accion=args.costo, max_trades=args.max_trades,
                    min_liquidez=args.min_liquidez)
        if j:
            jornadas.append(j)
    db.close()

    if len(jornadas) < 20:
        print(f"  muestra insuficiente ({len(jornadas)} jornadas)")
        return 1

    v = [j["pnl"] for j in jornadas]
    fechas = sorted({j["d"] for j in jornadas})
    años = max(0.5, (int(fechas[-1][:4]) * 12 + int(fechas[-1][5:7])
                     - int(fechas[0][:4]) * 12 - int(fechas[0][5:7])) / 12)

    print("=" * 92)
    print("  SIMULADOR DE SESIÓN — presupuesto en dólares, nominal completo")
    print(f"  riesgo/día ${args.riesgo:.0f} · riesgo/trade ${rt:.0f} · "
          f"objetivo ${args.objetivo:.0f} · stop {args.stop:.0f}% · "
          f"máx {args.max_trades} trades")
    print(f"  costo ${args.costo:.2f}/acción · liquidez >= "
          f"${args.min_liquidez/1e3:.0f}k/min · expansión >= {args.min_expansion:.0f}%")
    print("=" * 92)

    print(f"\n  {len(jornadas)} jornadas operables en {años:.1f} años "
          f"({len(jornadas)/años:.0f} por año, {len(jornadas)/años/12:.1f} por mes)")
    print(f"\n  RESULTADO POR JORNADA")
    print(f"    mediana        ${statistics.median(v):>+8.2f}")
    print(f"    media          ${statistics.mean(v):>+8.2f}")
    print(f"    desvío         ${statistics.pstdev(v):>8.2f}")
    print(f"    días positivos  {100*sum(1 for x in v if x > 0)/len(v):>7.0f}%")
    s = sorted(v)
    print(f"    peor jornada   ${s[0]:>+8.2f}    p10 ${s[int(.10*len(s))]:>+8.2f}"
          f"    p90 ${s[int(.90*len(s))]:>+8.2f}")
    print(f"\n    ACUMULADO      ${sum(v):>+8.2f} en {años:.1f} años "
          f"= ${sum(v)/años:>+8.2f} por año")

    print(f"\n  CÓMO CIERRA LA JORNADA")
    for k, n in Counter(j["cierre_por"] for j in jornadas).most_common():
        g = [j["pnl"] for j in jornadas if j["cierre_por"] == k]
        print(f"    {k:10} {n:>4} ({100*n/len(jornadas):>3.0f}%)  "
              f"media ${statistics.mean(g):>+7.2f}")

    print(f"\n  TRADES POR JORNADA: mediana "
          f"{statistics.median([j['trades'] for j in jornadas]):.0f}  ·  "
          f"total {sum(j['trades'] for j in jornadas)}")

    print(f"\n  REPLICACIÓN")
    for per in ("P1", "P2"):
        g = [j["pnl"] for j in jornadas if j["per"] == per]
        if len(g) >= 20:
            print(f"    {per}  n={len(g):>4}  mediana ${statistics.median(g):>+7.2f}  "
                  f"media ${statistics.mean(g):>+7.2f}  "
                  f"positivos {100*sum(1 for x in g if x>0)/len(g):>3.0f}%")

    print(f"""
  CÓMO LEERLO: con ${args.riesgo:.0f} de riesgo diario, la unidad es la jornada y no
  el trade. Una media de ${statistics.mean(v):+.2f} por jornada operable, con
  {len(jornadas)/años:.0f} jornadas al año, son ${sum(v)/años:+.0f} anuales — antes de decidir
  cuánto capital hace falta para sostener el peor tramo.

  Lo que NO está: borrow (un short sin locate rinde cero), el slippage del stop
  en un papel que haltea, y el sesgo de la muestra de minutos.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
