#!/usr/bin/env python3
"""
Backtesting local sobre los datos que descarga descargar_datos.py.

Subcomandos, en el orden en que tiene sentido usarlos:

    simple       ejecuta una estrategia con unos parámetros concretos
    grid         barre el espacio de parámetros con separación in/out-of-sample
    walkforward  reoptimiza por ventanas y mide sólo lo que no vio el ajuste
    matriz       repite el walk-forward con varios tamaños de ventana
    montecarlo   robustez ante variaciones aleatorias
    generar      construye estrategias desde cero por programación genética

Ejemplos:
    python backtestear.py simple --datos data/BTCUSDT_4h_binance.csv \\
        --estrategia cruce_medias -p rapida=20 -p lenta=100 -p tipo=ema

    python backtestear.py grid --datos data/BTCUSDT_4h_binance.csv \\
        --estrategia rsi_reversion --procesos 4

    python backtestear.py walkforward --datos data/BTCUSDT_4h_binance.csv \\
        --estrategia cruce_medias --dias-is 365 --dias-oos 90

    python backtestear.py generar --datos data/BTCUSDT_4h_binance.csv \\
        --poblacion 120 --generaciones 25 --guardar banco.json
"""

import argparse
import sys

import pandas as pd

import backtest as bt
from backtest import estrategias, generador, metricas, montecarlo, optimizar, walkforward
from backtest.indicadores import Contexto


def _valor(texto):
    """Convierte 'rapida=20' respetando enteros, decimales y textos."""
    for conversion in (int, float):
        try:
            return conversion(texto)
        except ValueError:
            continue
    return texto


def _parametros(lista):
    params = {}
    for item in lista or []:
        if "=" not in item:
            raise SystemExit(f"Parámetro mal formado: {item!r}. Usa nombre=valor")
        clave, valor = item.split("=", 1)
        params[clave.strip()] = _valor(valor.strip())
    return params


def _config(args):
    return bt.Config(
        comision=args.comision, slippage=args.slippage, capital=args.capital,
        permitir_cortos=not args.solo_largos,
    )


def _cargar(args):
    datos = bt.cargar(args.datos, args.intervalo)
    print(f"📈 {args.datos}: {len(datos):,} velas de {datos.intervalo}")
    return datos


# ========================
# SUBCOMANDOS
# ========================

def cmd_simple(args):
    datos = _cargar(args)
    config = _config(args)
    estrategia = estrategias.obtener(args.estrategia)
    params = _parametros(args.param)

    senales = estrategia.senales(Contexto(datos), **params)
    if senales is None:
        raise SystemExit("La estrategia rechaza esa combinación de parámetros.")

    resultado = bt.ejecutar(datos, senales, config)
    m = metricas.calcular(resultado, datos.intervalo, config.capital)

    print(f"\n🎯 {args.estrategia}  {params}")
    print(metricas.formatear(m))

    if args.operaciones:
        print(f"\n📋 Primeras {args.operaciones} operaciones:")
        print(resultado.operaciones_df().head(args.operaciones).to_string(index=False))
    return 0


def cmd_grid(args):
    datos = _cargar(args)
    config = _config(args)

    print(f"\n🔍 Barriendo {args.estrategia} (fitness: {args.fitness}, "
          f"out-of-sample: {args.oos:.0%})")
    tabla = optimizar.grid(datos, args.estrategia, config, fitness=args.fitness,
                           fraccion_oos=args.oos, min_operaciones=args.min_operaciones,
                           procesos=args.procesos)
    if tabla.empty:
        print("❌ Ninguna combinación válida.")
        return 1

    print("\n" + optimizar.resumen(tabla, args.fitness))

    utiles = tabla[~tabla["descartada"]]
    espacio = estrategias.obtener(args.estrategia).espacio
    columnas = ([c for c in espacio if c in utiles.columns]
                + ["is_fitness", "is_cagr", "is_max_drawdown", "is_n_operaciones",
                   "oos_fitness", "oos_cagr", "oos_max_drawdown"])
    print(f"\n🏆 Mejores {args.top} por fitness in-sample:")
    print(utiles[columnas].head(args.top).to_string(index=False))

    if args.guardar:
        tabla.to_csv(args.guardar, index=False)
        print(f"\n💾 Tabla completa en {args.guardar}")
    return 0


def cmd_walkforward(args):
    datos = _cargar(args)
    config = _config(args)
    print(f"\n🚶 Walk-forward de {args.estrategia}: {args.dias_is}d de ajuste + "
          f"{args.dias_oos}d de validación por ventana\n")
    resultado = walkforward.analizar(
        datos, args.estrategia, config, fitness=args.fitness,
        dias_is=args.dias_is, dias_oos=args.dias_oos,
        min_operaciones=args.min_operaciones, procesos=args.procesos)
    print("\n" + walkforward.formatear(resultado))
    if args.guardar and resultado.ventanas:
        resultado.tabla().to_csv(args.guardar, index=False)
        print(f"\n💾 Detalle por ventana en {args.guardar}")
    return 0


def cmd_matriz(args):
    datos = _cargar(args)
    config = _config(args)
    print(f"\n🔲 Matriz walk-forward de {args.estrategia}. "
          f"Busca una zona amplia de celdas buenas, no la mejor celda.\n")
    tabla = walkforward.matriz(datos, args.estrategia, config, fitness=args.fitness,
                               min_operaciones=args.min_operaciones, procesos=args.procesos)
    if tabla.empty:
        print("❌ Ninguna configuración de ventanas cabe en esta serie.")
        return 1
    print(tabla.to_string(index=False))
    print(f"\n  celdas con eficiencia > 0,5: {(tabla['eficiencia'] > 0.5).sum()} de {len(tabla)}")
    return 0


def cmd_montecarlo(args):
    datos = _cargar(args)
    config = _config(args)
    estrategia = estrategias.obtener(args.estrategia)
    params = _parametros(args.param)

    generar = lambda ctx: estrategia.senales(ctx, **params)
    senales = generar(Contexto(datos))
    if senales is None:
        raise SystemExit("La estrategia rechaza esa combinación de parámetros.")
    resultado = bt.ejecutar(datos, senales, config)

    print(f"\n🎲 Monte Carlo de {args.estrategia} {params}")
    print(f"   backtest original: {resultado.n_operaciones} operaciones, "
          f"{resultado.equity[-1] / config.capital - 1:+.1%}\n")
    print(montecarlo.informe(resultado, datos, generar, config,
                             n_operaciones=args.simulaciones,
                             n_datos=max(args.simulaciones // 10, 20),
                             capital=config.capital))
    return 0


def cmd_generar(args):
    datos = _cargar(args)
    config = _config(args)

    print(f"\n🧬 Generando estrategias: población {args.poblacion}, "
          f"{args.generaciones} generaciones, fitness {args.fitness}")
    print(f"   La evolución sólo ve el {1 - args.oos:.0%} inicial de la serie.\n")

    candidatas = generador.evolucionar(
        datos, config, criterio=args.fitness, poblacion=args.poblacion,
        generaciones=args.generaciones, min_operaciones=args.min_operaciones,
        fraccion_oos=args.oos, semilla=args.semilla, banco_max=args.banco)

    if not candidatas:
        print("\n❌ Ninguna estrategia alcanzó fitness positivo.")
        return 1

    print(f"\n📚 Banco de {len(candidatas)} estrategias:")
    print(generador.tabla(candidatas).head(args.top).to_string(index=False))

    supervivientes = generador.filtrar(candidatas, datos, config,
                                       max_dd_p95=args.max_drawdown)
    if supervivientes:
        print(f"\n✅ {len(supervivientes)} estrategia(s) pasaron todos los filtros:\n")
        for c in supervivientes[:args.top]:
            print(c.genoma.describir())
            m = c.metricas_oos
            print(f"    fuera de muestra: retorno {m['retorno_total']:+.1%}, "
                  f"CAGR {m['cagr']:+.1%}, DD {m['max_drawdown']:.1%}, "
                  f"{m['n_operaciones']} ops")
            print(f"    Monte Carlo: drawdown p95 {c.mc.percentiles()['drawdown'][95]:.1%}\n")
    else:
        print("\n  Ninguna sobrevivió a los filtros. Es el resultado más habitual y")
        print("  es información, no un fallo: significa que lo que encontró la")
        print("  evolución no se sostiene fuera del tramo en que se optimizó.")

    if args.guardar:
        generador.guardar(candidatas, args.guardar)
        print(f"💾 Banco completo en {args.guardar}")
    return 0


# ========================
# CLI
# ========================

def main():
    parser = argparse.ArgumentParser(
        description="Backtesting local de estrategias sobre datos históricos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ejemplos:")[-1])

    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--datos", required=True, help="CSV descargado con descargar_datos.py")
    comun.add_argument("--intervalo", default=None,
                       help="Intervalo de las velas (por defecto se deduce del nombre)")
    comun.add_argument("--comision", type=float, default=0.0004, help="Por lado (0.0004 = 0,04 %%)")
    comun.add_argument("--slippage", type=float, default=0.0002, help="Por lado")
    comun.add_argument("--capital", type=float, default=10_000.0)
    comun.add_argument("--solo-largos", action="store_true", help="Desactiva las posiciones cortas")

    optim = argparse.ArgumentParser(add_help=False)
    optim.add_argument("--fitness", default="return_dd", choices=sorted(optimizar.FITNESS))
    optim.add_argument("--min-operaciones", type=int, default=30)
    optim.add_argument("--procesos", type=int, default=1, help="Procesos en paralelo")
    optim.add_argument("--top", type=int, default=10)
    optim.add_argument("--guardar", default=None)

    subs = parser.add_subparsers(dest="comando", required=True)

    p = subs.add_parser("simple", parents=[comun], help="Ejecuta una estrategia concreta")
    p.add_argument("--estrategia", required=True, choices=sorted(estrategias.REGISTRO))
    p.add_argument("-p", "--param", action="append", help="nombre=valor (repetible)")
    p.add_argument("--operaciones", type=int, default=0, help="Muestra las N primeras operaciones")
    p.set_defaults(fn=cmd_simple)

    p = subs.add_parser("grid", parents=[comun, optim], help="Barrido de parámetros")
    p.add_argument("--estrategia", required=True, choices=sorted(estrategias.REGISTRO))
    p.add_argument("--oos", type=float, default=0.3, help="Fracción out-of-sample")
    p.set_defaults(fn=cmd_grid)

    p = subs.add_parser("walkforward", parents=[comun, optim], help="Walk-forward analysis")
    p.add_argument("--estrategia", required=True, choices=sorted(estrategias.REGISTRO))
    p.add_argument("--dias-is", type=int, default=365)
    p.add_argument("--dias-oos", type=int, default=90)
    p.set_defaults(fn=cmd_walkforward)

    p = subs.add_parser("matriz", parents=[comun, optim], help="Matriz de walk-forward")
    p.add_argument("--estrategia", required=True, choices=sorted(estrategias.REGISTRO))
    p.set_defaults(fn=cmd_matriz)

    p = subs.add_parser("montecarlo", parents=[comun], help="Pruebas de robustez")
    p.add_argument("--estrategia", required=True, choices=sorted(estrategias.REGISTRO))
    p.add_argument("-p", "--param", action="append", help="nombre=valor (repetible)")
    p.add_argument("--simulaciones", type=int, default=2000)
    p.set_defaults(fn=cmd_montecarlo)

    p = subs.add_parser("generar", parents=[comun, optim],
                        help="Genera estrategias por programación genética")
    p.add_argument("--poblacion", type=int, default=120)
    p.add_argument("--generaciones", type=int, default=25)
    p.add_argument("--oos", type=float, default=0.3)
    p.add_argument("--semilla", type=int, default=42)
    p.add_argument("--banco", type=int, default=50, help="Tamaño máximo del banco")
    p.add_argument("--max-drawdown", type=float, default=0.6,
                   help="Drawdown p95 máximo admitido en Monte Carlo")
    p.set_defaults(fn=cmd_generar, fitness="compuesto")

    args = parser.parse_args()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
