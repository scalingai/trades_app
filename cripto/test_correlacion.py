#!/usr/bin/env python3
"""Etapa 3 — ¿cuántos eventos independientes hay de verdad?

Corre ANTES del contraste, a propósito. Saber el n efectivo después de ver un
resultado que gustó invita a aceptar un factor generoso; saberlo antes, no.

**El problema.** En acciones el agrupamiento era chico: 4 trades el mismo día
equivalían a ~3,5 independientes. Acá se espera que sea peor, porque el día que
BTC cae 8% caen las 500. Un dataset de 3.000 eventos puede valer, en
información, como 300 — y con n nominal cualquier test da significativo.

**La medición.** Si los eventos del mismo día fueran independientes, la
varianza del promedio de k de ellos sería var/k. Se compara la varianza
observada contra esa predicción; el cociente es el factor de inflación.

    n_efectivo = n_nominal / factor

**Winsorizado.** En acciones la cola tapaba el efecto: con retornos crudos los
cocientes salían sin patrón y recortando al p95 aparecía. Se reporta crudo y
winsorizado, porque la diferencia entre los dos es en sí misma información.

    python test_correlacion.py
    python test_correlacion.py --columna pct_t1
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics
import sys
from collections import defaultdict

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def _winsorizar(xs: list[float], p: float = 0.95) -> list[float]:
    if len(xs) < 20:
        return xs
    orden = sorted(xs)
    lo = orden[int((1 - p) * len(orden))]
    hi = orden[int(p * len(orden)) - 1]
    return [min(max(x, lo), hi) for x in xs]


def cargar(con: sqlite3.Connection, columna: str, filtro: str
           ) -> dict[str, list[float]]:
    sql = f"""
        SELECT e.d, r.{columna}
          FROM eventos e JOIN retornos r
            ON r.simbolo = e.simbolo AND r.d = e.d
         WHERE r.{columna} IS NOT NULL AND {filtro}
    """
    por_dia: dict[str, list[float]] = defaultdict(list)
    for d, v in con.execute(sql):
        por_dia[d].append(v)
    return por_dia


def medir(por_dia: dict[str, list[float]], ks=(2, 3, 4, 5, 6)) -> dict:
    todos = [v for vs in por_dia.values() for v in vs]
    if len(todos) < 100:
        return {}
    var_global = statistics.pvariance(todos)
    salida = {}
    for k in ks:
        # Promedio de k eventos del mismo día, tomados sin reposición.
        medias = []
        for vs in por_dia.values():
            if len(vs) >= k:
                muestra = random.sample(vs, k)
                medias.append(sum(muestra) / k)
        if len(medias) < 30 or var_global == 0:
            continue
        esperada = var_global / k          # lo que predice la independencia
        observada = statistics.pvariance(medias)
        salida[k] = (observada / esperada, len(medias))
    return salida


def permutacion(por_dia: dict[str, list[float]], k: int = 4,
                n_perm: int = 400) -> float | None:
    """¿El agrupamiento se distingue de barajar los eventos entre días?

    Mantiene la cantidad de eventos por día y reasigna al azar cuál cayó en
    cuál. Si el cociente real queda en la cola de la distribución barajada, el
    agrupamiento es del día y no del tamaño de los grupos.
    """
    real = medir(por_dia, ks=(k,)).get(k)
    if not real:
        return None
    todos = [v for vs in por_dia.values() for v in vs]
    tamaños = [len(vs) for vs in por_dia.values()]
    mayores = 0
    for _ in range(n_perm):
        random.shuffle(todos)
        barajado, i = {}, 0
        for j, t in enumerate(tamaños):
            barajado[str(j)] = todos[i:i + t]
            i += t
        r = medir(barajado, ks=(k,)).get(k)
        if r and r[0] >= real[0]:
            mayores += 1
    return 1 - mayores / n_perm


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--columna", default="pct_t1",
                   choices=["pct_t1", "pct_t5", "r_t1", "r_t5"])
    p.add_argument("--filtro", default="e.rvol>=5 AND e.quote_volume>=2e6")
    p.add_argument("--semilla", type=int, default=7)
    args = p.parse_args()

    random.seed(args.semilla)
    con = sqlite3.connect(config.db_path(), timeout=60)

    print(f"columna: {args.columna}   filtro: {args.filtro}\n")
    por_dia = cargar(con, args.columna, args.filtro)
    n = sum(len(v) for v in por_dia.values())
    if n < 100:
        print(f"muestra insuficiente ({n} eventos)")
        return 1

    print(f"eventos      : {n:,}")
    print(f"días con ≥1  : {len(por_dia)}")
    print(f"eventos/día  : {n/len(por_dia):.1f}\n")

    crudo = medir(por_dia)
    wins = medir({d: _winsorizar(v) for d, v in por_dia.items()})

    print("cociente varianza observada / varianza si fueran independientes")
    print("  (1,00 = independientes · >1 = agrupados · n_efectivo = n / cociente)\n")
    print(f"  {'k':>3}  {'crudo':>8}  {'winsorizado':>12}  {'muestras':>9}")
    factores = []
    for k in sorted(set(crudo) | set(wins)):
        c = crudo.get(k, (None, 0))
        w = wins.get(k, (None, 0))
        cs = f"{c[0]:.2f}" if c[0] else "—"
        ws = f"{w[0]:.2f}" if w[0] else "—"
        print(f"  {k:>3}  {cs:>8}  {ws:>12}  {max(c[1], w[1]):>9}")
        if w[0]:
            factores.append(w[0])

    if factores:
        factor = statistics.median(factores)
        print(f"\n  factor de agrupamiento (mediana, winsorizado): {factor:.2f}")
        print(f"  n nominal {n:,}  →  n EFECTIVO ≈ {int(n/factor):,}")
        print(f"  los intervalos de confianza se ensanchan ×{factor**0.5:.2f}")

    pval = permutacion(por_dia)
    if pval is not None:
        print(f"\n  prueba de permutación (k=4): p ≈ {pval:.3f}")
        print("  (bajo = el agrupamiento es del día, no del tamaño de los grupos)")

    print("\nEste factor corrige TODO lo que reporte contraste.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
