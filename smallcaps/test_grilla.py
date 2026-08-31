#!/usr/bin/env python3
"""La grilla stop × target sobre la variante que gana: agotamiento.

**Hipótesis de Agus:** con menos recorrido —stop más corto Y target más corto—
se gana más. Y tiene una razón mecánica que las pruebas anteriores no aislaron:
**con tamaño por riesgo, un stop más corto significa una posición más grande.**
Un 1:1 con stop del 5% mueve seis veces más nominal que un 1:1 con stop del 30%,
así que los dos ganan lo mismo en R pero no en dólares por unidad de tiempo ni
de exposición.

Lo que probé antes fue siempre **target corto con stop largo**, que es la peor
combinación posible: pagás la puntería sin cobrar el tamaño.

Acá la grilla entera, sin elegir celda. Cada entrada es una señal de agotamiento
de volumen con el filtro de liquidez, sobre días que abrieron *fade* con
expansión ≥ 100%. El tamaño sale del riesgo fijo por trade.

Convención de siempre: si en el mismo minuto se tocan stop y target, gana el
stop.

    python test_grilla.py
    python test_grilla.py --riesgo 16.67 --costo 0.04
"""

from __future__ import annotations

import argparse
import statistics
import sys

from chavineta import clasificar_apertura
from dias import CIERRE_RTH, cargar, hora
from sesion import señales

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"
STOPS = (3, 5, 8, 12, 20, 30)
TARGETS = (3, 5, 8, 12, 20, 30, 0)      # 0 = sin target, sostener al cierre


def simular(dia, i, p, stop_pct, target_pct, riesgo, costo_accion):
    """Short desde `i`. Devuelve (pnl $, motivo). Tamaño por riesgo."""
    acciones = riesgo / (p * stop_pct / 100.0)
    p_stop = p * (1 + stop_pct / 100.0)
    p_tgt = p * (1 - target_pct / 100.0) if target_pct else None
    costo = acciones * costo_accion
    for b in dia.bars[i + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        if b[2] and b[2] >= p_stop:
            return -riesgo - costo, "stop"
        if p_tgt and b[3] and b[3] <= p_tgt:
            return acciones * (p - p_tgt) - costo, "target"
    c = dia.rth_close
    if not c:
        return None
    return acciones * (p - c) - costo, "cierre"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Grilla stop × target")
    ap.add_argument("--riesgo", type=float, default=16.67)
    ap.add_argument("--costo", type=float, default=0.04)
    ap.add_argument("--min-liquidez", type=float, default=2.5e5)
    ap.add_argument("--min-expansion", type=float, default=100.0)
    ap.add_argument("--max-por-dia", type=int, default=10)
    args = ap.parse_args(argv)

    entradas = []
    dias_ok = 0
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < args.min_expansion:
            continue
        if clasificar_apertura(dia) != "fade":
            continue
        ses = señales(dia, min_liquidez=args.min_liquidez)[:args.max_por_dia]
        if not ses:
            continue
        dias_ok += 1
        for i in ses:
            p = dia.bars[i][4]
            if p:
                entradas.append((dia, i, p))

    print("=" * 104)
    print(f"  GRILLA STOP × TARGET — {len(entradas):,} entradas en {dias_ok:,} días")
    print(f"  agotamiento de volumen · liquidez >= ${args.min_liquidez/1e3:.0f}k/min · "
          f"expansión >= {args.min_expansion:.0f}% · abrió fade")
    print(f"  ${args.riesgo:.2f} de riesgo por trade — el TAMAÑO sale del stop, "
          "así que un stop corto es una posición grande")
    print("=" * 104)

    if len(entradas) < 200:
        print(f"\n  muestra insuficiente ({len(entradas)})")
        return 1

    tabla = {}
    for s in STOPS:
        for t in TARGETS:
            res = []
            for dia, i, p in entradas:
                r = simular(dia, i, p, s, t, args.riesgo, args.costo)
                if r:
                    res.append(r)
            if len(res) < 200:
                continue
            v = [x[0] for x in res]
            gan = [x for x in v if x > 0]
            per = [x for x in v if x <= 0]
            tabla[(s, t)] = {
                "media": statistics.mean(v),
                "total": sum(v),
                "gana": 100 * len(gan) / len(v),
                "pf": (sum(gan) / abs(sum(per))) if per and sum(per) else None,
            }

    def cuadro(clave, titulo, fmt):
        print(f"\n  {titulo}")
        print(f"  {'stop \\\\ target':>14} "
              + " ".join(f"{(str(t)+'%' if t else 'sin tgt'):>9}" for t in TARGETS))
        print("  " + "-" * (16 + 10 * len(TARGETS)))
        for s in STOPS:
            fila = []
            for t in TARGETS:
                c = tabla.get((s, t))
                fila.append(fmt.format(c[clave]) if c and c[clave] is not None
                            else f"{'—':>9}")
            print(f"  {(str(s)+'%'):>14} " + " ".join(fila))

    cuadro("media", "MEDIA POR TRADE, en dólares", "{:>+9.3f}")
    cuadro("pf", "PROFIT FACTOR  (debajo de 1 pierde)", "{:>9.2f}")
    cuadro("gana", "ACIERTOS %", "{:>8.0f}%")

    mejor = max(tabla.items(), key=lambda kv: kv[1]["media"])
    peor = min(tabla.items(), key=lambda kv: kv[1]["media"])
    print(f"""
  mejor celda: stop {mejor[0][0]}% · target {mejor[0][1] or 'sin'}  →  "
        media ${mejor[1]['media']:+.3f}  ·  PF {mejor[1]['pf']:.2f}  ·  gana {mejor[1]['gana']:.0f}%
  peor celda:  stop {peor[0][0]}% · target {peor[0][1] or 'sin'}  →  "
        media ${peor[1]['media']:+.3f}  ·  PF {peor[1]['pf']:.2f}  ·  gana {peor[1]['gana']:.0f}%

  NO se elige la mejor celda. La grilla está entera para ver la FORMA: si el
  óptimo es un pico rodeado de celdas malas, es suerte; si es una meseta, es una
  propiedad de los datos. Elegir la celda después de verla es exactamente el
  sobreajuste que este proyecto viene evitando.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
