#!/usr/bin/env python3
"""Tercera ronda: ¿el front side es de menor riesgo que el back side?

**Pregunta de Agus, y es la correcta.** Todo lo medido hasta acá short-ea el
back side —la parte de atrás, después del máximo— y ahí el riesgo medido es
enorme: MAE mediana 21,6% y p90 de 83%. La hipótesis es que el front side
—mientras todavía sube— tiene mejor relación riesgo/beneficio.

DECLARADO ANTES DE CORRER (van 11 señales de las rondas 1 y 2; esto suma 1
definición de estado × 2 direcciones × 4 horas = 8 celdas más):

  front = precio >= VWAP acumulado del día     back = precio < VWAP

Cero parámetros: el nivel lo pone el flujo, no nosotros. Como control se
reporta una segunda definición —el máximo corriente se hizo hace menos de 30
minutos— que SÍ tiene un parámetro, y por eso es control y no la principal.

Se reporta TODO: las cuatro combinaciones de lado × dirección, en las cuatro
horas, con MAE. Una celda con mediana linda y MAE de 80% no es una estrategia.

    python test_lados.py
    python test_lados.py --sin-filtro-split
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HORAS = (10.0, 11.0, 12.0, 13.0)
CORTE_PERIODO = "2025-08-17"


def _p(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def recolectar(*, filtro_split: bool):
    filas = []
    for dia in cargar():
        if filtro_split and (dia.ratio_volumen or 0) < 3:
            continue
        cierre = dia.rth_close
        if not cierre:
            continue
        base = dict(t=dia.ticker, d=dia.d, exp=dia.expansion_pct,
                    per="P1" if dia.d < CORTE_PERIODO else "P2")
        for h in HORAS:
            p = dia.precio_en(h)
            est = dia.estado_en(h)
            if not p or not est:
                continue
            mae_l, mae_s = dia.excursion(h)
            i = dia.idx_en(h)
            filas.append({**base, "h": h, "estado": est, "precio": p,
                          "edad_max": dia.edad_max[i],
                          "ret_long": (cierre / p - 1) * 100.0,
                          "ret_short": (p / cierre - 1) * 100.0,
                          "mae_long": mae_l, "mae_short": mae_s})
    return filas


def bloque(titulo, filas, clave_estado):
    print(f"\n  {titulo}")
    print(f"  {'hora':>5} {'lado':>6} {'n':>5} │ {'LONG med':>9} {'MAE p50':>8} {'MAE p90':>8}"
          f" │ {'SHORT med':>10} {'MAE p50':>8} {'MAE p90':>8}")
    print("  " + "-" * 88)
    for h in HORAS:
        for lado in ("front", "back"):
            g = [f for f in filas if f["h"] == h and clave_estado(f) == lado]
            if len(g) < 25:
                print(f"  {h:>5.1f} {lado:>6} {len(g):>5} │  (n insuficiente)")
                continue
            rl = [f["ret_long"] for f in g]
            rs = [f["ret_short"] for f in g]
            ml = [f["mae_long"] for f in g]
            ms = [f["mae_short"] for f in g]
            print(f"  {h:>5.1f} {lado:>6} {len(g):>5} │ {statistics.median(rl):>+8.2f}% "
                  f"{statistics.median(ml):>7.1f}% {_p(ml, .90):>7.1f}% │ "
                  f"{statistics.median(rs):>+9.2f}% {statistics.median(ms):>7.1f}% "
                  f"{_p(ms, .90):>7.1f}%")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Front side vs back side")
    ap.add_argument("--sin-filtro-split", action="store_true",
                    help="no descartar los días con volumen < 3x el previo")
    args = ap.parse_args(argv)

    filas = recolectar(filtro_split=not args.sin_filtro_split)
    dias = len({(f["t"], f["d"]) for f in filas})

    print("=" * 92)
    print(f"  FRONT SIDE vs BACK SIDE  ·  {dias} días de evento  ·  {len(filas)} observaciones")
    print("  MAE = cuánto se movió EN CONTRA antes del cierre. Es el riesgo, no el resultado.")
    print("=" * 92)

    bloque("DEFINICIÓN PRINCIPAL — front = precio ≥ VWAP del día  (cero parámetros)",
           filas, lambda f: f["estado"])
    bloque("CONTROL — front = el máximo corriente se hizo hace menos de 30 min",
           filas, lambda f: "front" if f["edad_max"] < 30 else "back")

    print("\n  SOLO LOS DÍAS DE EXPANSIÓN GRANDE (máximo pre-market > +100% vs cierre previo)")
    bloque("front = precio ≥ VWAP", [f for f in filas if (f["exp"] or 0) > 100],
           lambda f: f["estado"])

    print("\n  REPLICACIÓN EN LOS DOS PERÍODOS (entrada 11:00, definición principal)")
    print(f"  {'lado':>6} {'dir':>6} {'P1 n':>6} {'P1 med':>8} {'P2 n':>6} {'P2 med':>8}")
    print("  " + "-" * 50)
    for lado in ("front", "back"):
        for direc in ("long", "short"):
            out = []
            for per in ("P1", "P2"):
                g = [f[f"ret_{direc}"] for f in filas
                     if f["h"] == 11.0 and f["estado"] == lado and f["per"] == per]
                out.append((len(g), statistics.median(g) if len(g) >= 25 else None))
            fmt = lambda x: f"{x:+.2f}%" if x is not None else "     —"  # noqa: E731
            print(f"  {lado:>6} {direc:>6} {out[0][0]:>6} {fmt(out[0][1]):>8} "
                  f"{out[1][0]:>6} {fmt(out[1][1]):>8}")

    print("\n  Recordatorio de sesgo: la muestra se sorteó de días con rango DIARIO > 40%,")
    print("  que a las 10:00 no se conoce. Las comparaciones entre celdas son válidas;")
    print("  los niveles absolutos están inflados por esa selección.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
