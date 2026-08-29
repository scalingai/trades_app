#!/usr/bin/env python3
"""¿El radar está en una meseta o en un pico de suerte?

**El chequeo que faltaba.** El radar usa los umbrales que declararon los
operadores —$0,70-$5, gap ≥ 70%, float ≤ 10M— y no los calibré yo. Eso es bueno
para el sesgo de búsqueda, pero no dice nada sobre si el resultado es ROBUSTO.

Un resultado sano vive en una meseta: mover un umbral 20% cambia el número
poco. Un resultado de suerte vive en un pico: la celda exacta rinde y las de al
lado no. La diferencia se ve moviendo un parámetro por vez y mirando la
superficie entera, no la celda elegida.

**Esto NO es optimizar.** No se elige la mejor celda: se mira la FORMA. Si el
mejor valor resultara ser otro, tampoco se cambiaría — mover un umbral después
de ver el resultado es exactamente lo que este proyecto viene evitando. La
superficie sirve para saber cuánta confianza merece el número, no para mejorarlo.

    python test_sensibilidad.py
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from radar_historico import historial_completo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE = "2025-08-17"
BASE = {"precio_min": 0.70, "precio_max": 5.00, "gap": 70.0, "float_max": 10e6}


def cargar(db):
    return db.execute(
        "SELECT e.ticker, e.d, e.open, e.gap_pct, e.intraday_pct, "
        "       s.shares_outstanding "
        "FROM events e LEFT JOIN event_structure s "
        "  ON s.ticker = e.ticker AND s.d = e.d "
        "WHERE e.intraday_pct IS NOT NULL AND e.open IS NOT NULL "
        "  AND e.dollar_volume >= 1e6").fetchall()


def evaluar(filas, *, precio_min, precio_max, gap, float_max):
    v = [intra for _t, _d, o, g, intra, acc in filas
         if precio_min <= o <= precio_max and g is not None and g >= gap
         and acc and acc <= float_max]
    if len(v) < 15:
        return None
    return {"n": len(v), "med": statistics.median(v),
            "media": statistics.mean(v),
            "cae": 100 * sum(1 for x in v if x < 0) / len(v)}


def barrido(filas, nombre, valores, clave):
    print(f"\n  {nombre}")
    print(f"  {'valor':>12} {'n':>6} {'mediana':>9} {'media':>9} {'cae':>6}   {'':>4}")
    print("  " + "-" * 52)
    for val in valores:
        args = dict(BASE)
        args[clave] = val
        r = evaluar(filas, **args)
        marca = "  <- el del protocolo" if val == BASE[clave] else ""
        if not r:
            print(f"  {val:>12} {'—':>6}   (n insuficiente){marca}")
            continue
        print(f"  {val:>12} {r['n']:>6} {r['med']:>+8.2f}% {r['media']:>+8.2f}% "
              f"{r['cae']:>5.0f}%{marca}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sensibilidad del radar a sus umbrales")
    ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    filas = cargar(db)
    hist = historial_completo(db)

    base = evaluar(filas, **BASE)
    print("=" * 72)
    print("  SENSIBILIDAD DEL RADAR A SUS PROPIOS UMBRALES")
    print(f"  celda del protocolo: n={base['n']}  mediana {base['med']:+.2f}%  "
          f"cae {base['cae']:.0f}%")
    print("  Se mueve UN parámetro por vez. Meseta = robusto. Pico = suerte.")
    print("=" * 72)

    barrido(filas, "GAP MÍNIMO", [40.0, 50.0, 60.0, 70.0, 80.0, 100.0, 130.0], "gap")
    barrido(filas, "FLOAT MÁXIMO (acciones)",
            [3e6, 5e6, 10e6, 20e6, 50e6, 200e6], "float_max")
    barrido(filas, "PRECIO MÁXIMO", [2.0, 3.0, 5.0, 8.0, 12.0, 20.0], "precio_max")
    barrido(filas, "PRECIO MÍNIMO", [0.20, 0.50, 0.70, 1.0, 2.0, 3.0], "precio_min")

    print("\n" + "=" * 72)
    print("  EL FILTRO DE FLOAT, MIRADO SOLO")
    print("  Es el que más eventos descarta. ¿Discrimina, o solo achica la muestra?")
    print("=" * 72)
    print(f"\n  {'banda de acciones':>22} {'n':>6} {'mediana':>9} {'media':>9} {'cae':>6}")
    print("  " + "-" * 58)
    for lo, hi, lab in ((0, 3e6, "< 3M"), (3e6, 10e6, "3-10M"), (10e6, 30e6, "10-30M"),
                        (30e6, 100e6, "30-100M"), (100e6, 1e15, "> 100M")):
        v = [intra for _t, _d, o, g, intra, acc in filas
             if BASE["precio_min"] <= o <= BASE["precio_max"]
             and g is not None and g >= BASE["gap"] and acc and lo <= acc < hi]
        if len(v) < 15:
            print(f"  {lab:>22} {len(v):>6}   (insuficiente)")
            continue
        print(f"  {lab:>22} {len(v):>6} {statistics.median(v):>+8.2f}% "
              f"{statistics.mean(v):>+8.2f}% "
              f"{100*sum(1 for x in v if x<0)/len(v):>5.0f}%")

    print("\n" + "=" * 72)
    print("  ESTABILIDAD EN EL TIEMPO — la celda del protocolo, trimestre a trimestre")
    print("=" * 72)
    cand = [(d, intra) for _t, d, o, g, intra, acc in filas
            if BASE["precio_min"] <= o <= BASE["precio_max"]
            and g is not None and g >= BASE["gap"] and acc and acc <= BASE["float_max"]]
    por_trim = {}
    for d, intra in cand:
        t = f"{d[:4]}-T{(int(d[5:7])-1)//3 + 1}"
        por_trim.setdefault(t, []).append(intra)
    print(f"\n  {'trimestre':>12} {'n':>5} {'mediana':>9} {'cae':>6}")
    print("  " + "-" * 36)
    for t in sorted(por_trim):
        v = por_trim[t]
        if len(v) < 8:
            print(f"  {t:>12} {len(v):>5}   (pocos)")
            continue
        print(f"  {t:>12} {len(v):>5} {statistics.median(v):>+8.2f}% "
              f"{100*sum(1 for x in v if x<0)/len(v):>5.0f}%")

    print("\n  Un edge real no tiene por qué dar todos los trimestres, pero sí")
    print("  tiene que no depender de uno solo. Si sacando el mejor trimestre el")
    print("  agregado se cae, era ese trimestre y no el filtro.")
    todos = [x for v in por_trim.values() for x in v]
    peor_sin = None
    for t in por_trim:
        resto = [x for k, v in por_trim.items() if k != t for x in v]
        if len(resto) > 30:
            m = statistics.median(resto)
            if peor_sin is None or m > peor_sin[1]:
                peor_sin = (t, m)
    if peor_sin:
        print(f"\n  con todos: {statistics.median(todos):+.2f}%  ·  "
              f"sacando {peor_sin[0]} (el que más aporta): {peor_sin[1]:+.2f}%")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
