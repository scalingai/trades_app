#!/usr/bin/env python3
"""
Calibración del pipeline contra datos sin ninguna señal explotable.

Genera series de precio puramente aleatorias, lanza sobre cada una el mismo
proceso completo (evolución → out-of-sample → Monte Carlo) y cuenta cuántas
veces el filtro deja pasar algo. Como en esas series no hay nada que
encontrar, todo superviviente es un falso positivo.

Para qué sirve el número que sale: es la tasa base contra la que hay que
comparar los resultados sobre datos reales. Si sobre ruido el filtro deja
pasar una estrategia el 20 % de las veces, encontrar una estrategia que
sobrevive sobre bitcoin no significa gran cosa por sí solo. Es la pregunta
que casi nadie se hace antes de poner dinero, y es barata de responder.

    python validar_pipeline.py --series 10 --poblacion 60 --generaciones 12
"""

import argparse
import sys

import numpy as np

from backtest import generador
from backtest.motor import Config, Datos


def serie_aleatoria(semilla, n=19645, precio_inicial=4000.0, vol=0.012, deriva=0.0):
    """
    Paseo aleatorio geométrico con estructura OHLC coherente.

    Con deriva cero el rendimiento esperado es nulo, pero cada realización
    concreta sube o baja por azar: eso es justamente lo que hace difícil el
    problema y por lo que conviene repetir sobre muchas series en vez de sacar
    conclusiones de una sola.
    """
    rng = np.random.default_rng(semilla)
    cierre = precio_inicial * np.exp(np.cumsum(rng.normal(deriva, vol, n)))
    rango = cierre * rng.uniform(0.002, 0.02, n)
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    return Datos(
        fechas=np.arange(n), open=apertura,
        high=np.maximum(apertura, cierre) + rango,
        low=np.minimum(apertura, cierre) - rango,
        close=cierre, volume=np.ones(n), intervalo="4h",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Mide la tasa de falsos positivos del pipeline sobre ruido.")
    parser.add_argument("--series", type=int, default=10)
    parser.add_argument("--poblacion", type=int, default=60)
    parser.add_argument("--generaciones", type=int, default=12)
    parser.add_argument("--barras", type=int, default=19645)
    parser.add_argument("--max-drawdown", type=float, default=0.6)
    parser.add_argument("--min-operaciones", type=int, default=40)
    args = parser.parse_args()

    config = Config()
    total_supervivientes = 0
    series_con_superviviente = 0

    print(f"Lanzando el pipeline sobre {args.series} series aleatorias "
          f"de {args.barras:,} barras.\n")
    print(f"{'serie':>6} {'buy&hold':>10} {'banco':>7} {'mejor IS':>10} "
          f"{'med. OOS':>10} {'sobreviven':>11}")
    print("-" * 60)

    for i in range(args.series):
        datos = serie_aleatoria(1000 + i, n=args.barras)
        buy_hold = datos.close[-1] / datos.close[0] - 1

        candidatas = generador.evolucionar(
            datos, config, poblacion=args.poblacion, generaciones=args.generaciones,
            min_operaciones=args.min_operaciones, semilla=1000 + i, verboso=False)

        if not candidatas:
            print(f"{i:>6} {buy_hold:>9.0%} {0:>7} {'—':>10} {'—':>10} {0:>11}")
            continue

        tabla = generador.tabla(candidatas)
        supervivientes = generador.filtrar(candidatas, datos, config,
                                           max_dd_p95=args.max_drawdown, verboso=False)
        total_supervivientes += len(supervivientes)
        series_con_superviviente += 1 if supervivientes else 0

        med_oos = tabla["oos_cagr"].median() if "oos_cagr" in tabla else float("nan")
        print(f"{i:>6} {buy_hold:>9.0%} {len(candidatas):>7} "
              f"{tabla['is_cagr'].max():>9.0%} {med_oos:>9.0%} {len(supervivientes):>11}")

    tasa = series_con_superviviente / args.series
    print("-" * 60)
    print(f"\n  series con al menos un superviviente: {series_con_superviviente}/{args.series} "
          f"({tasa:.0%})")
    print(f"  supervivientes totales: {total_supervivientes}")
    print()
    if tasa >= 0.2:
        print("  Ésa es la tasa base sobre ruido. Encontrar una estrategia que sobrevive")
        print("  sobre datos reales no es, por sí solo, evidencia de que haya un edge:")
        print("  hay que compararlo contra este número. Para bajarlo: exigir más")
        print("  operaciones, endurecer el máximo de drawdown, o validar además en")
        print("  otro timeframe y otro par.")
    else:
        print("  El filtro deja pasar poco ruido con esta configuración. Aun así,")
        print("  sobrevivir aquí es condición necesaria y no suficiente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
