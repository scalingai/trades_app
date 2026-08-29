#!/usr/bin/env python3
"""Ratios cortos en short, con el stop atado a la volatilidad del momento.

**Lo que pidió Agus:** solo short, ratios 1:1 o menos, con el stop dependiendo
del día y de la volatilidad. Esto lo mide sobre los 50.330 momentos de
`momentos.py`.

La aritmética que decide todo, y conviene tenerla a mano antes de mirar
cualquier tabla:

    ratio 1:2   →  hay que acertar el 33% para empatar
    ratio 1:1   →  hay que acertar el 50%
    ratio 1:0,5 →  hay que acertar el 67%
    ratio 1:0,25→  hay que acertar el 80%

**Un ratio corto no es más seguro: es un préstamo.** Cambia riesgo de ruina por
exigencia de puntería, y el umbral sube más rápido de lo que baja el ratio. La
pregunta empírica es si la puntería alcanza.

Los costos entran en R, no en %. Un centavo de spread sobre un stop del 3% es
un tercio del riesgo; sobre uno del 15% es un veinteavo. Por eso la tabla
muestra el costo mediano en R al lado del resultado: en los papeles baratos con
stop corto el costo se come el trade entero antes de empezar.

    python test_ratios.py
    python test_ratios.py --spread-cents 3 --locate 0.02
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from momentos import MULTIPLOS

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RATIOS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
COLS = (["ticker", "d", "hora", "precio", "exp_premarket", "dist_vwap",
         "dist_max", "edad_max", "volatilidad", "vol_rel"] +
        [f"m{m}_{k}" for m in MULTIPLOS for k in ("stop", "mfe", "cierre")])


def cargar_momentos(conn):
    q = f"SELECT {','.join(COLS)} FROM momentos"
    return [dict(zip(COLS, r)) for r in conn.execute(q)]


def bruto(fila, m, ratio):
    """Resultado en múltiplos de R, sin costos. Acotado a [-1, ratio]."""
    if fila[f"m{m}_mfe"] >= ratio:
        return ratio
    if fila[f"m{m}_stop"]:
        return -1.0
    return fila[f"m{m}_cierre"]


def costo_r(fila, m, costo_accion):
    stop_pct = m * fila["volatilidad"]
    if stop_pct <= 0 or not fila["precio"]:
        return None
    return (costo_accion / fila["precio"] * 100.0) / stop_pct


# Arriba de esto el costo fijo se come una fracción absurda del riesgo y el
# trade no existe como trade. No es un parámetro de la estrategia: es la
# frontera de lo ejecutable, y por eso se reporta cuántos momentos deja afuera.
COSTO_MAX_R = 0.25


def evaluar(filas, m, ratio, costo_accion, costo_max=COSTO_MAX_R):
    todos = b = 0
    netos, gan = [], 0
    for f in filas:
        k = costo_r(f, m, costo_accion)
        if k is None:
            continue
        todos += 1
        if k > costo_max:
            continue
        b += 1
        netos.append(bruto(f, m, ratio) - k)
        if f[f"m{m}_mfe"] >= ratio:
            gan += 1
    if b < 200:
        return None
    brutos = [n + costo_r(f, m, costo_accion)
              for n, f in zip(netos, [x for x in filas
                                      if (costo_r(x, m, costo_accion) or 9) <= costo_max])]
    return {"n": b, "descartado": 100 * (todos - b) / todos,
            "acierta": 100 * gan / b,
            "umbral": 100 / (1 + ratio),
            "bruto": statistics.mean(brutos),
            "neto": statistics.mean(netos)}


def tabla(titulo, filas, costo, *, multiplos=MULTIPLOS, ratios=RATIOS):
    n = len(filas)
    dias = len({(f["ticker"], f["d"]) for f in filas})
    print(f"\n  {titulo}   ({n:,} momentos · {dias} días)")
    cab = " ".join(f"{'1:'+f'{r:g}':>11}" for r in ratios)
    ancho = 20 + 12 * len(ratios)
    print(f"  {'':>18} │ {cab}")
    print(f"  {'hay que acertar':>18} │ " + " ".join(f"{100/(1+r):>10.0f}%" for r in ratios))
    print("  " + "-" * ancho)
    for m in multiplos:
        vs = [evaluar(filas, m, r, costo) for r in ratios]
        if not any(vs):
            continue
        f = lambda k, fmt: " ".join(  # noqa: E731
            (fmt.format(v[k]) if v else f"{'—':>11}") for v in vs)
        print(f"  {f'stop {m}x · acierta':>18} │ " + f("acierta", "{:>10.0f}%"))
        print(f"  {'esperanza bruta':>18} │ " + f("bruto", "{:>+11.3f}"))
        print(f"  {'ESPERANZA NETA':>18} │ " + f("neto", "{:>+11.3f}"))
        print(f"  {'descartado x costo':>18} │ " + f("descartado", "{:>10.0f}%"))
        print("  " + "·" * ancho)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ratios cortos en short")
    ap.add_argument("--spread-cents", type=float, default=2.0)
    ap.add_argument("--comision", type=float, default=0.005)
    ap.add_argument("--locate", type=float, default=0.01)
    ap.add_argument("--solo", default="", help="una sola sección, por substring")
    args = ap.parse_args(argv)
    costo = args.spread_cents / 100 + 2 * args.comision + args.locate

    conn = sqlite3.connect(config.data_dir() / "momentos.sqlite")
    filas = cargar_momentos(conn)
    conn.close()

    print("=" * 96)
    print("  SHORT CON RATIOS CORTOS · stop = múltiplo de la volatilidad del momento")
    print(f"  costo asumido {costo*100:.1f} centavos/acción "
          f"(spread {args.spread_cents:.0f}c round trip + comisión ×2 + locate)")
    print(f"  'hay que acertar' = puntería para empatar SIN costos.")
    print(f"  Se descartan los momentos donde el costo supera {COSTO_MAX_R:.2f}R: ahí no hay")
    print("  trade posible, y el % descartado va en la última fila de cada bloque.")
    print("=" * 96)

    tabla("TODOS LOS MOMENTOS", filas, costo)

    secciones = [
        ("POR BANDA DE PRECIO — donde el costo decide", [
            ("$0,50–1", lambda f: f["precio"] < 1),
            ("$1–3", lambda f: 1 <= f["precio"] < 3),
            ("$3–10", lambda f: 3 <= f["precio"] < 10),
            ("$10+", lambda f: f["precio"] >= 10),
        ]),
        ("POR ESTADO DEL MOMENTO", [
            ("debajo del VWAP (back side)", lambda f: (f["dist_vwap"] or 0) < 0),
            ("arriba del VWAP (front side)", lambda f: (f["dist_vwap"] or 0) >= 0),
            ("el máximo del día tiene > 2h", lambda f: (f["edad_max"] or 0) > 120),
            ("a menos de 3% del máximo", lambda f: (f["dist_max"] or -99) > -3),
        ]),
        ("POR VOLATILIDAD DEL MOMENTO", [
            ("< 1% por minuto", lambda f: f["volatilidad"] < 1),
            ("1–2,5% por minuto", lambda f: 1 <= f["volatilidad"] <= 2.5),
            ("> 2,5% por minuto", lambda f: f["volatilidad"] > 2.5),
        ]),
        ("POR EXPANSIÓN PRE-MARKET", [
            ("< +25%", lambda f: (f["exp_premarket"] or 0) < 25),
            ("+25 a +100%", lambda f: 25 <= (f["exp_premarket"] or 0) < 100),
            ("> +100%", lambda f: (f["exp_premarket"] or 0) >= 100),
        ]),
        ("POR HORA", [
            ("antes de 11:00", lambda f: f["hora"] < 11),
            ("11:00 a 14:00", lambda f: 11 <= f["hora"] < 14),
            ("después de 14:00", lambda f: f["hora"] >= 14),
        ]),
    ]
    for titulo, cortes in secciones:
        if args.solo and args.solo.lower() not in titulo.lower():
            continue
        print("\n" + "=" * 96)
        print(f"  {titulo}")
        print("=" * 96)
        for lab, cond in cortes:
            sub = [f for f in filas if cond(f)]
            if len(sub) < 500:
                print(f"\n  {lab}: n={len(sub)} insuficiente")
                continue
            tabla(lab, sub, costo, multiplos=(5, 8), ratios=(0.5, 1.0, 2.0))

    print("\n" + "=" * 96)
    print("  ADVERTENCIAS QUE NO SE PUEDEN SALTEAR")
    print("=" * 96)
    print("""
  1. Los momentos del mismo día NO son trades independientes: se solapan y
     comparten el mismo régimen. El n grande es de OBSERVACIONES. Los días
     distintos son 775, y ese es el n que manda.

  2. La muestra se sorteó por rango DIARIO > 40%, que en el momento de entrar
     no se conoce. Los niveles absolutos están inflados.

  3. El stop se asume ejecutado a su precio exacto. Con ratios cortos eso pesa
     el doble: el stop es chico y cualquier deslizamiento es una fracción
     grande de R. En un papel que haltea, el fill es peor.

  4. Un short que no consigue locate tiene retorno CERO, no negativo. Acá
     entran todos.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
