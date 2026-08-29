#!/usr/bin/env python3
"""El candidato que sale de la tercera ronda: front-side LONG con stop fijo.

Se aísla acá porque es el único de las tres rondas que mejora la MEDIA al
agregarle el control de riesgo, en vez de pagarlo. Y porque un long no necesita
locate: es la primera cosa medida en este proyecto que se puede ejecutar.

Lo que se controla acá y no en `test_salidas.py`:
  · replicación en los dos períodos
  · banda de precio (el costo por acción pesa distinto en $1 que en $10)
  · costos explícitos: spread + comisión, sin locate porque es long
  · el gradiente por expansión pre-market — la sospecha es que se da vuelta
    en las expansiones extremas, donde el front side es una trampa

    python test_frontlong.py
    python test_frontlong.py --spread-cents 3 --comision 0.005
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"


def trade(dia, h, stop_pct):
    """Long desde `h` con stop fijo. Devuelve (entrada, ret_bruto%, motivo)."""
    i0 = dia.idx_en(h)
    if i0 is None:
        return None
    e = dia.bars[i0][4]
    if not e:
        return None
    post = [b for b in dia.bars if hora(b) > h and hora(b) <= CIERRE_RTH]
    if len(post) < 30:
        return None
    p_stop = e * (1 - stop_pct / 100)
    for b in post:
        if b[3] and b[3] <= p_stop:
            return e, -stop_pct, "stop"
    return e, (post[-1][4] / e - 1) * 100, "cierre"


def _p(v, q):
    s = sorted(v)
    return s[min(len(s) - 1, int(q * len(s)))]


def resumen(rows):
    if len(rows) < 20:
        return None
    r = [x["neto"] for x in rows]
    return dict(n=len(r), med=statistics.median(r), media=statistics.mean(r),
                p10=_p(r, .10), peor=min(r),
                gana=100 * sum(1 for x in r if x > 0) / len(r),
                costo=statistics.median([x["costo"] for x in rows]),
                stops=100 * sum(1 for x in rows if x["motivo"] == "stop") / len(rows))


def linea(lab, r):
    if not r:
        print(f"  {lab:30}  (n insuficiente)")
        return
    print(f"  {lab:30} {r['n']:>5} {r['med']:>+7.2f}% {r['media']:>+7.2f}% "
          f"{r['p10']:>+7.2f}% {r['peor']:>+7.1f}% {r['gana']:>5.0f}% "
          f"{r['costo']:>6.2f}% {r['stops']:>5.0f}%")


def cabecera(t):
    print(f"\n  {t}")
    print(f"  {'':30} {'n':>5} {'med':>8} {'media':>8} {'p10':>8} {'peor':>8} "
          f"{'gana':>6} {'costo':>7} {'stops':>6}")
    print("  " + "-" * 92)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Front-side long con stop fijo")
    ap.add_argument("--hora", type=float, default=10.0)
    ap.add_argument("--stop", type=float, default=15.0)
    ap.add_argument("--spread-cents", type=float, default=2.0,
                    help="spread asumido, round trip, en centavos")
    ap.add_argument("--comision", type=float, default=0.005,
                    help="comisión por acción por lado")
    args = ap.parse_args(argv)

    rows = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3:
            continue
        if dia.estado_en(args.hora) != "front":
            continue
        r = trade(dia, args.hora, args.stop)
        if not r:
            continue
        e, bruto, motivo = r
        # Costo por acción: spread (una vez, round trip) + comisión los dos lados.
        costo_pct = (args.spread_cents / 100 + 2 * args.comision) / e * 100
        rows.append(dict(t=dia.ticker, d=dia.d, precio=e, bruto=bruto,
                         costo=costo_pct, neto=bruto - costo_pct, motivo=motivo,
                         exp=dia.expansion_pct,
                         per="P1" if dia.d < CORTE_PERIODO else "P2"))

    print("=" * 96)
    print(f"  FRONT-SIDE LONG  ·  entrada {args.hora:.0f}:00 ET  ·  stop {args.stop:.0f}%  "
          f"·  n={len(rows)}")
    print(f"  costos: spread {args.spread_cents:.0f}c round trip + "
          f"{args.comision*100:.1f}c/accion x2. Sin locate: es long.")
    print("=" * 96)

    cabecera("TOTAL Y REPLICACION")
    linea("todo", resumen(rows))
    for per in ("P1", "P2"):
        linea(f"  {per}", resumen([x for x in rows if x["per"] == per]))

    cabecera("POR BANDA DE PRECIO  (el costo por accion pesa distinto)")
    for lab, lo, hi in (("$0,50-1", .5, 1), ("$1-3", 1, 3), ("$3-5", 3, 5),
                        ("$5-10", 5, 10), ("$10+", 10, 1e9)):
        linea(lab, resumen([x for x in rows if lo <= x["precio"] < hi]))

    cabecera("POR EXPANSION PRE-MARKET  (la sospecha: se da vuelta en la cola)")
    for lab, lo, hi in (("< +25%", -1e9, 25), ("+25 a +50%", 25, 50),
                        ("+50 a +100%", 50, 100), ("+100 a +200%", 100, 200),
                        ("> +200%", 200, 1e9)):
        linea(lab, resumen([x for x in rows if lo <= (x["exp"] or 0) < hi]))

    cabecera("SENSIBILIDAD AL STOP")
    for s in (10, 15, 20, 30, 100):
        sub = []
        for dia in cargar():
            if (dia.ratio_volumen or 0) < 3 or dia.estado_en(args.hora) != "front":
                continue
            r = trade(dia, args.hora, s)
            if not r:
                continue
            e, bruto, motivo = r
            c = (args.spread_cents / 100 + 2 * args.comision) / e * 100
            sub.append(dict(neto=bruto - c, costo=c, motivo=motivo))
        linea(f"stop {s}%" if s < 100 else "sin stop", resumen(sub))

    print("\n  Sesgo de la muestra: se sorteo de dias con rango DIARIO > 40%, que a las")
    print("  10:00 no se conoce. Las comparaciones entre filas valen; el nivel absoluto no.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
