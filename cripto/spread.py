#!/usr/bin/env python3
"""Etapa 5.c — el spread neutral al mercado, y por qué NO pasa la validación.

**La idea, que era correcta.** Lo que H1 valida es un efecto de RANKING: dentro
de un mismo día, los tokens que más diluyeron rinden peor que los que menos.
Convertir eso en "shorteá el balde alto" es un trade direccional, y ahí el
resultado queda a merced del mercado y de la cola. Un ranking se explota mejor
como spread: largo el balde bajo, corto el balde alto, capital partido en dos.

Estructuralmente es mejor y se nota en los números: el factor común se cancela
entre las patas, el funding se cancela en parte, y la media deja de depender
de la cola (media 1,068% contra mediana 1,072% en el decil 10 — simétrica, que
es justo lo que el short direccional no lograba).

**Y aun así no pasa.** Los criterios de §6 de RESEARCH.md fijaban, ante la
falta de fuera de muestra temporal real, partir el universo en dos mitades por
símbolo y exigir que el efecto apareciera en las dos. Con deslizamiento de
0,10% por lado:

    partición temporal      1ª mitad +0,710%/día   2ª mitad +1,026%/día   ✅
    partición por símbolo   grupo A  −0,174%/día   grupo B  +0,944%/día   ❌

Que aguante en el tiempo pero no entre símbolos es informativo: dice que el
resultado no es una propiedad general de la población sino que lo carga un
subconjunto de tokens. Con otro sorteo de símbolos, la mitad de las veces no
está.

**Además el corte se eligió después de mirar.** Se probaron cuatro (terciles,
deciles 8-10, 9-10 y 10) y se reportó el mejor. El p de permutación del decil
10 ya era marginal por sí solo —0,0233, a 1,79 desvíos, contra 0,0000 y 3,03
desvíos del efecto de ranking— y con cuatro comparaciones deja de sostenerse.

**Lo que esto NO invalida.** H1 sigue en pie con todo su respaldo. Lo que falla
es esta forma concreta de cobrarlo, no el hallazgo.

    python spread.py
    python spread.py --slip 0.002
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys
from collections import defaultdict

import config
from contraste import cargar
from costos import TAKER, _mapa_funding, funding_del_trade

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Cortes de dilución por decil, calculados sobre la muestra completa.
DECIL_10, DECIL_9, DECIL_8, TERCIL = 19.5, 10.3, 4.2, 2.5


def cargar_con_funding(con):
    filas = [x for x in cargar(con, "t1", 5.0, 2e6, False)
             if x["raw"] is not None]
    fmap = _mapa_funding(con)
    for x in filas:
        x["fnd"] = funding_del_trade(fmap.get(x["simbolo"], []), x["d"], 1)
    return filas


def serie_diaria(datos, alto: float, bajo: float, slip: float):
    """Retorno diario del spread. Solo cuentan los días con AMBAS patas.

    Un día con solo una pata no es neutral al mercado, y contarlo metería de
    vuelta el arrastre que toda la estructura existe para cancelar.
    """
    dias = defaultdict(lambda: {"a": [], "b": []})
    for x in datos:
        if x["crec"] >= alto:
            dias[x["d"]]["a"].append(x)
        elif x["crec"] <= bajo:
            dias[x["d"]]["b"].append(x)
    salida = []
    for d, g in sorted(dias.items()):
        if not g["a"] or not g["b"]:
            continue
        corto = st.fmean([-x["raw"] + x["fnd"] for x in g["a"]])
        largo = st.fmean([x["raw"] - x["fnd"] for x in g["b"]])
        # Cuatro lados de comisión y de deslizamiento: dos patas, ida y vuelta.
        salida.append((d, (corto + largo) / 2 - 2 * TAKER - 2 * slip))
    return salida


def _resumen(rs: list[float]) -> tuple:
    if len(rs) < 2:
        return (0, 0, 0, 0)
    desvio = st.pstdev(rs) or 1e-9
    return (st.fmean(rs), st.median(rs),
            100 * sum(1 for x in rs if x > 0) / len(rs),
            st.fmean(rs) / desvio * (252 ** 0.5))


def correr(slip: float, semilla: int) -> None:
    con = sqlite3.connect(config.db_path(), timeout=60)
    filas = cargar_con_funding(con)

    print("=" * 76)
    print("  SPREAD NEUTRAL — largo dilución baja / corto dilución alta")
    print("=" * 76)
    print(f"\neventos          : {len(filas):,}")
    print(f"deslizamiento    : {slip*100:.2f}% por lado (4 lados en total)")

    print("\n\nAFINAR EL CORTE — ¿crece el spread al ir al extremo?\n")
    print(f"  {'corte':<24}{'días':>6}{'media':>10}{'mediana':>10}"
          f"{'gana':>7}{'Sharpe':>9}")
    for etq, alto in (("terciles", TERCIL), ("deciles 8-10", DECIL_8),
                      ("deciles 9-10", DECIL_9), ("decil 10", DECIL_10)):
        rs = [r for _, r in serie_diaria(filas, alto, 0.0, slip)]
        if len(rs) < 50:
            continue
        m, med, g, sh = _resumen(rs)
        print(f"  {etq:<24}{len(rs):>6}{m*100:>9.3f}%{med*100:>9.3f}%"
              f"{g:>6.0f}%{sh:>9.2f}")
    print("\n  Crece monotónicamente y la media se parece a la mediana: la")
    print("  estructura de spread SÍ resuelve la dependencia de la cola que")
    print("  tenía el short direccional.")

    print("\n\nVALIDACIÓN — los dos cortes que exige RESEARCH.md §6\n")
    todo = serie_diaria(filas, DECIL_10, 0.0, slip)
    fechas = [d for d, _ in todo]
    corte = fechas[len(fechas) // 2]

    print(f"  {'partición':<24}{'días':>6}{'media':>10}{'mediana':>10}"
          f"{'gana':>7}{'Sharpe':>9}")
    for etq, sub in (("temporal · 1ª mitad", [r for d, r in todo if d < corte]),
                     ("temporal · 2ª mitad", [r for d, r in todo if d >= corte])):
        m, med, g, sh = _resumen(sub)
        print(f"  {etq:<24}{len(sub):>6}{m*100:>9.3f}%{med*100:>9.3f}%"
              f"{g:>6.0f}%{sh:>9.2f}")

    random.seed(semilla)
    simbolos = sorted({x["simbolo"] for x in filas})
    random.shuffle(simbolos)
    mitad = set(simbolos[:len(simbolos) // 2])
    veredicto = []
    for etq, sub in (("símbolos · grupo A",
                      [x for x in filas if x["simbolo"] in mitad]),
                     ("símbolos · grupo B",
                      [x for x in filas if x["simbolo"] not in mitad])):
        rs = [r for _, r in serie_diaria(sub, DECIL_10, 0.0, slip)]
        if len(rs) < 40:
            print(f"  {etq:<24}{len(rs):>6}   (pocos días)")
            continue
        m, med, g, sh = _resumen(rs)
        veredicto.append(m)
        print(f"  {etq:<24}{len(rs):>6}{m*100:>9.3f}%{med*100:>9.3f}%"
              f"{g:>6.0f}%{sh:>9.2f}")

    print()
    if len(veredicto) == 2 and min(veredicto) > 0:
        print("  → aguanta en las dos mitades de símbolos")
    else:
        print("  → NO aguanta: una mitad de los símbolos da negativo.")
        print("    El criterio pre-registrado exigía que apareciera en las dos.")
        print("    Que aguante en el tiempo pero no entre símbolos dice que el")
        print("    resultado lo carga un subconjunto de tokens, no la población.")

    print("\n\nY EL CORTE SE ELIGIÓ DESPUÉS DE MIRAR")
    print("  Se probaron cuatro cortes y se reportó el mejor. El p de")
    print("  permutación del decil 10 ya era marginal solo: 0,0233 a 1,79")
    print("  desvíos, contra 0,0000 y 3,03 del efecto de ranking. Con cuatro")
    print("  comparaciones no se sostiene.")
    print("\n  H1 no se toca: lo que falla es esta forma de cobrarlo.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slip", type=float, default=0.001)
    p.add_argument("--semilla", type=int, default=31)
    args = p.parse_args()
    correr(args.slip, args.semilla)
    return 0


if __name__ == "__main__":
    sys.exit(main())
