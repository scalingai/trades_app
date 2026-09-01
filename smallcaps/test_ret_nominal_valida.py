#!/usr/bin/env python3
"""¿Los filtros de retorno-sobre-nominal replican, o los elegí mirando la tabla?

**Por qué existe.** Cuando el locate se cobra como % del NOMINAL, la función
objetivo deja de ser el PnL y pasa a ser el retorno sobre nominal — es lo que hay
que comparar contra el 20% de Espes. Pero los cortes (float < 47M, volumen entre
$137M y $470M, precio > $0.90) los elegí DESPUÉS de ver los cuartiles. Eso es
sobreajuste hasta que se demuestre lo contrario.

Dos pruebas, las de siempre en este proyecto:
  1. ¿Replica en los dos períodos por separado?
  2. ¿Es meseta o pico? Un óptimo rodeado de celdas malas es suerte.

    SMALLCAPS_CENSO=1 python test_ret_nominal_valida.py
"""

from __future__ import annotations

import sqlite3
import statistics
import sys

import config
from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE = "2025-08-17"


def cargar_filas():
    """Una fila por sesión operada, CON su fecha — el bug de la corrida anterior
    fue emparejar dos listas de largos distintos."""
    db = sqlite3.connect(config.bars_db_path())
    flo = {}
    for t, d, so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
        if so:
            flo[(t, d)] = so
    db.close()

    filas = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        j = jornada(dia, riesgo_dia=50, riesgo_trade=50 / 3, objetivo=0, stop_pct=15,
                    costo_accion=0.04, max_trades=10, min_liquidez=2.5e5, modo="swing",
                    stop_modo="estructural", colchon=1.0, tope_stop=30)
        if not j:
            continue
        nom = 0.0
        for t in (j.get("detalle") or []):
            nom = max(nom, (t.get("acciones") or 0) * (t.get("precio") or 0))
        filas.append({"d": dia.d, "tk": dia.ticker, "pnl": j["pnl"], "nom": nom,
                      "float": flo.get((dia.ticker, dia.d)),
                      "dolar": sum((b[5] or 0) * (b[4] or 0) for b in dia.bars),
                      "precio": dia.bars[0][4] if dia.bars else None})
    return filas


def rn(g):
    """(n, media, retorno sobre nominal %). None si la muestra no alcanza."""
    if len(g) < 25:
        return None
    m = statistics.mean(x["pnl"] for x in g)
    n = statistics.mean(x["nom"] for x in g)
    return len(g), m, 100 * m / n if n else 0.0


FILTROS = [
    ("sin filtro", lambda f: True),
    ("float < 47M", lambda f: f["float"] and f["float"] <= 47e6),
    ("volumen > $137M", lambda f: f["dolar"] and f["dolar"] > 137e6),
    ("volumen $137M-$470M", lambda f: f["dolar"] and 137e6 < f["dolar"] <= 470e6),
    ("precio $0.90-$2.30", lambda f: f["precio"] and 0.9 <= f["precio"] <= 2.3),
    ("vol $137-470M + precio>$0.90",
     lambda f: f["dolar"] and 137e6 < f["dolar"] <= 470e6
     and f["precio"] and f["precio"] > 0.9),
]


def main() -> int:
    filas = cargar_filas()
    p1 = [f for f in filas if f["d"] < CORTE]
    p2 = [f for f in filas if f["d"] >= CORTE]
    print("=" * 92)
    print(f"  VALIDACIÓN DEL RETORNO SOBRE NOMINAL — {len(filas)} sesiones "
          f"(P1 {len(p1)} · P2 {len(p2)})")
    print(f"  Corte de período: {CORTE}. La fecha viaja EN la fila, no emparejada aparte.")
    print("=" * 92)

    print("\n  1) ¿REPLICA EN LOS DOS PERÍODOS?\n")
    print(f"  {'filtro':>30} {'todo':>16} {'P1':>16} {'P2':>16} {'brecha':>8}")
    print("  " + "-" * 90)
    for lab, p in FILTROS:
        t, a, b = rn([f for f in filas if p(f)]), rn([f for f in p1 if p(f)]), \
            rn([f for f in p2 if p(f)])
        def c(x):
            return f"n={x[0]:>3} {x[2]:>7.1f}%" if x else f"{'muestra corta':>14}"
        br = (f"{abs(a[2]-b[2]):>7.1f}p" if a and b else f"{'—':>8}")
        print(f"  {lab:>30} {c(t):>16} {c(a):>16} {c(b):>16} {br}")

    print("\n  2) ¿MESETA O PICO? barrido del corte de volumen (piso y techo)\n")
    print(f"  {'piso':>12} {'n':>5} {'ret/nom':>9}    {'techo':>12} {'n':>5} {'ret/nom':>9}")
    print("  " + "-" * 68)
    for lo, hi in zip((50e6, 100e6, 137e6, 200e6, 250e6, 300e6),
                      (300e6, 400e6, 470e6, 600e6, 900e6, 1e15)):
        a = rn([f for f in filas if f["dolar"] and f["dolar"] > lo])
        b = rn([f for f in filas if f["dolar"] and f["dolar"] <= hi])
        print(f"  {'> $'+format(int(lo/1e6))+'M':>12} {a[0]:>5} {a[2]:>8.1f}%    "
              f"{('< $'+format(int(hi/1e6))+'M') if hi < 1e14 else 'sin techo':>12} "
              f"{b[0]:>5} {b[2]:>8.1f}%")

    print("\n  3) EL CORTE DE FLOAT, barrido — es acantilado o pendiente?\n")
    print(f"  {'float máximo':>14} {'n':>5} {'ret/nom':>9} {'% del PnL':>10}")
    print("  " + "-" * 44)
    tot = sum(f["pnl"] for f in filas if f["float"])
    for hi in (5e6, 15e6, 30e6, 47e6, 80e6, 200e6, 1e15):
        g = [f for f in filas if f["float"] and f["float"] <= hi]
        r = rn(g)
        if not r:
            continue
        print(f"  {('< '+format(int(hi/1e6))+'M') if hi < 1e14 else 'sin tope':>14} "
              f"{r[0]:>5} {r[2]:>8.1f}% "
              f"{100*sum(x['pnl'] for x in g)/tot:>9.1f}%")

    print("""
  Cómo leerlo: la 'brecha' de la primera tabla es la diferencia entre períodos.
  Un filtro con brecha chica replica; uno con brecha grande fue elegido mirando
  el ruido. Y en los barridos, una curva suave es una propiedad de los datos —
  un pico aislado es suerte.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
