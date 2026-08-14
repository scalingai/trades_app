#!/usr/bin/env python3
"""Etapa 5.b — stop y objetivo: ¿cambia el resultado gestionar la posición?

El análisis de `costos.py` mide un trade SIN gestión: entra al cierre de D y
sale al cierre de D+1 pase lo que pase. Con esa forma, la media depende del 1%
de mejores operaciones y las peores no tienen límite. En acciones esto fue
justamente lo que dio vuelta el resultado: la celda ancha de `test_rr.py` daba
media +3,24% y, a diferencia de todo lo demás, NO dependía de la cola.

**Tres honestidades del simulador**, las mismas que se fijaron en la rama de
bitcoin y por las mismas razones:

1. **Si stop y objetivo caen en la misma barra, gana el STOP.** Con barras
   diarias no se sabe cuál se tocó antes, y asumir lo favorable sería inventar
   plata.
2. **Si la barra abre pasada el stop, se ejecuta en la apertura real**, no al
   precio del stop. Un hueco en contra no respeta la orden.
3. **La grilla se reporta ENTERA.** Elegir la mejor celda es el sobreajuste que
   venimos evitando; el número tiene que hablar solo.

**Costos por desenlace.** El objetivo puede ser una orden límite porque es un
precio al que uno espera: paga maker. El stop no: cuando salta hay que cruzar
el diferencial pagando taker y con deslizamiento. Cobrar un costo plano abarata
justo al perdedor, que es el que más pesa.

    python bracket.py
    python bracket.py --dias 10 --slip 0.002
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics as st
import sys
from collections import defaultdict

import config
from contraste import _baldes, cargar
from costos import MAKER, TAKER, _mapa_funding, funding_del_trade

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

STOP, OBJETIVO, TIEMPO = "stop", "objetivo", "tiempo"


def barras_por_simbolo(con) -> dict[str, list[tuple]]:
    m: dict[str, list[tuple]] = defaultdict(list)
    for s, d, hi, lo, cl, op in con.execute(
            "SELECT simbolo, d, high, low, close, open FROM barras "
            "ORDER BY simbolo, d"):
        m[s].append((d, hi, lo, cl, op))
    return m


def simular(entrada: float, futuras: list[tuple], stop_pct: float,
            objetivo_pct: float) -> tuple[float, str, int]:
    """Corto con bracket. Devuelve (retorno bruto del corto, motivo, días).

    Para un corto, el stop está ARRIBA y el objetivo ABAJO.
    """
    p_stop = entrada * (1 + stop_pct)
    p_obj = entrada * (1 - objetivo_pct)

    for i, (d, hi, lo, cl, op) in enumerate(futuras, start=1):
        # Hueco en contra: la orden no se respeta, se ejecuta donde abrió.
        if op >= p_stop:
            return (entrada - op) / entrada, STOP, i
        toca_stop = hi >= p_stop
        toca_obj = lo <= p_obj
        if toca_stop:
            # Si ambos caen en la misma barra, gana el stop: no se conoce el
            # orden intra-barra y asumir lo favorable sería inventar plata.
            return -stop_pct, STOP, i
        if toca_obj:
            return objetivo_pct, OBJETIVO, i
    if not futuras:
        return 0.0, TIEMPO, 0
    return (entrada - futuras[-1][3]) / entrada, TIEMPO, len(futuras)


def coste_de(motivo: str, slip: float) -> float:
    """Entrada siempre a mercado. La salida depende de por dónde se cerró."""
    salida = MAKER if motivo == OBJETIVO else TAKER + slip
    return TAKER + slip + salida


def correr(dias: int, slip: float, min_rvol: float, min_vol: float,
           solo_alta: bool) -> None:
    con = sqlite3.connect(config.db_path(), timeout=60)
    filas = cargar(con, "t1", min_rvol, min_vol, False)
    barras = barras_por_simbolo(con)
    fmap = _mapa_funding(con)

    if solo_alta:
        filas = _baldes(filas, "crec")[2]
        etiqueta = "balde de dilución ALTA"
    else:
        etiqueta = "todos los eventos"

    # Índice de fecha → posición, por símbolo, para tomar las barras futuras.
    idx = {s: {b[0]: i for i, b in enumerate(bs)} for s, bs in barras.items()}

    print("=" * 78)
    print(f"  BRACKET — corto al cierre de D, {etiqueta}")
    print("=" * 78)
    print(f"\neventos       : {len(filas):,}")
    print(f"horizonte máx : {dias} días (después sale por tiempo)")
    print(f"deslizamiento : {slip*100:.2f}% por lado")
    print(f"costos        : entrada taker; objetivo maker; stop/tiempo taker+slip")

    stops = [0.05, 0.08, 0.12, 0.20, 0.30]
    objetivos = [0.05, 0.10, 0.15, 0.20, 0.30]

    print("\n\nMEDIA NETA por celda (%) — la grilla entera, sin elegir")
    print("\n  " + "stop \\ obj".rjust(10), end="")
    for o in objetivos:
        print(f"{o*100:>9.0f}%", end="")
    print()

    detalle = {}
    for sp in stops:
        print(f"  {sp*100:>9.0f}%", end="")
        for ob in objetivos:
            netos, motivos = [], []
            for f in filas:
                bs = barras.get(f["simbolo"])
                if not bs:
                    continue
                i = idx[f["simbolo"]].get(f["d"])
                if i is None:
                    continue
                entrada = bs[i][3]
                futuras = bs[i + 1:i + 1 + dias]
                if not futuras:
                    continue
                bruto, motivo, n = simular(entrada, futuras, sp, ob)
                fnd = funding_del_trade(fmap.get(f["simbolo"], []), f["d"], n)
                netos.append(bruto - coste_de(motivo, slip) + fnd)
                motivos.append(motivo)
            if netos:
                detalle[(sp, ob)] = (netos, motivos)
                print(f"{st.fmean(netos)*100:>9.2f}", end="")
            else:
                print(f"{'—':>9}", end="")
        print()

    print("\n\nMEDIA NETA SIN EL 1% MEJOR (%) — ¿depende de la cola?")
    print("\n  " + "stop \\ obj".rjust(10), end="")
    for o in objetivos:
        print(f"{o*100:>9.0f}%", end="")
    print()
    for sp in stops:
        print(f"  {sp*100:>9.0f}%", end="")
        for ob in objetivos:
            par = detalle.get((sp, ob))
            if not par:
                print(f"{'—':>9}", end="")
                continue
            ordenados = sorted(par[0])
            sin = ordenados[:int(len(ordenados) * 0.99)]
            print(f"{st.fmean(sin)*100:>9.2f}", end="")
        print()

    print("\n  Una celda que se mantiene parecida entre las dos tablas NO")
    print("  depende de la cola. Esa es la propiedad que se busca, no el")
    print("  número más alto.")

    print("\n\nDESGLOSE de las celdas con media positiva en AMBAS tablas")
    print(f"\n  {'stop':>5} {'obj':>5} {'media':>8} {'sin1%':>8} {'gana':>6} "
          f"{'días':>6}  {'objetivo/stop/tiempo':>22}")
    hubo = False
    for (sp, ob), (netos, motivos) in sorted(detalle.items()):
        ordenados = sorted(netos)
        sin = st.fmean(ordenados[:int(len(ordenados) * 0.99)])
        media = st.fmean(netos)
        if media <= 0 or sin <= 0:
            continue
        hubo = True
        gana = 100 * sum(1 for x in netos if x > 0) / len(netos)
        fr = {m: 100 * motivos.count(m) / len(motivos)
              for m in (OBJETIVO, STOP, TIEMPO)}
        print(f"  {sp*100:>4.0f}% {ob*100:>4.0f}% {media*100:>7.2f}% "
              f"{sin*100:>7.2f}% {gana:>5.0f}% {'':>6}  "
              f"{fr[OBJETIVO]:>5.0f}% {fr[STOP]:>5.0f}% {fr[TIEMPO]:>5.0f}%")
    if not hubo:
        print("\n  NINGUNA celda queda positiva en las dos tablas.")
        print("  Con estos costos y este deslizamiento, la gestión no salva")
        print("  el trade: lo que se ve en bruto se lo come el peaje.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dias", type=int, default=5)
    p.add_argument("--slip", type=float, default=0.001)
    p.add_argument("--min-rvol", type=float, default=5.0)
    p.add_argument("--min-vol", type=float, default=2e6)
    p.add_argument("--todos", action="store_true",
                   help="no filtrar por dilución alta")
    args = p.parse_args()
    correr(args.dias, args.slip, args.min_rvol, args.min_vol,
           solo_alta=not args.todos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
