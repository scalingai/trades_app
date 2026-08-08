#!/usr/bin/env python3
"""
Estrategia de posición continua guiada por un conjunto de modelos de flujo.

Junta las tres piezas: un modelo por temporalidad sobre las mismas velas de 10
segundos, una convicción agregada a partir de sus probabilidades, y una
posición proporcional a esa convicción que se ajusta en cada vela.

Frente al enfoque de umbral ("operar sólo con unanimidad"), dimensionar de
forma proporcional usa todas las velas en vez del 1 % de la cola, así que la
misma relación se mide sobre una muestra miles de veces mayor. Ése es el punto
de todo esto.

La tensión que decide el resultado es entre señal y rotación. La convicción se
mueve en cada vela de 10 segundos, y perseguirla paga costes continuamente. El
suavizado la calma y baja la rotación, pero también borra parte de la señal.
El barrido busca si existe algún punto donde lo que queda de señal paga lo que
cuesta seguirla.

    python estrategia_ensemble.py --coste 0.0006
    python estrategia_ensemble.py --coste 0.0002 --sesiones 20 21
"""

import argparse
import itertools
import sys

import numpy as np
import pandas as pd

from analisis_ensemble import MARCOS, modelo_de_marco
from backtest import flujo, posicion
from descargar_datos import cargar_datos


def construir_convicciones(df, fraccion_is=0.7, verboso=True):
    """Entrena un modelo por temporalidad y devuelve sus probabilidades alineadas."""
    corte = int(len(df) * fraccion_is)
    probabilidades = {}

    if verboso:
        print("Entrenando un modelo por temporalidad:")
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df, horizonte=1)
    modelo = flujo.entrenar(x.iloc[:corte], y.iloc[:corte])
    probabilidades["10s"] = pd.Series(modelo.probabilidad(x), index=df.index)
    if verboso:
        auc = flujo.auc(probabilidades["10s"].iloc[corte:].to_numpy(),
                        y.iloc[corte:].to_numpy())
        print(f"     10s  {len(df):>10,} velas  AUC OOS {auc:.4f}")
    del x, y

    for nombre, seg in MARCOS.items():
        probabilidades[nombre], _ = modelo_de_marco(df, seg, fraccion_is, verboso)
    return probabilidades, corte


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--coste", type=float, default=0.0006,
                        help="Coste por lado (0.0006 = taker Binance con slippage)")
    parser.add_argument("--oos", type=float, default=0.3)
    parser.add_argument("--sesiones", type=int, nargs="*", default=None,
                        help="Horas UTC a operar; sin esto, todas")
    parser.add_argument("--apalancamiento", type=float, default=1.0)
    args = parser.parse_args()

    print(f"Cargando {args.datos} ...")
    df = cargar_datos(args.datos)
    print(f"{len(df):,} velas de 10 s   {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}\n")

    probabilidades, corte = construir_convicciones(df, 1 - args.oos)

    # Todo lo que sigue es fuera de muestra.
    oos = df.iloc[corte:]
    p_oos = {k: v.iloc[corte:] for k, v in probabilidades.items()}
    conviccion = posicion.conviccion_de_ensemble(p_oos)
    if args.sesiones:
        conviccion = posicion.filtrar_sesion(conviccion, args.sesiones)

    anios = len(oos) * 10 / (365.25 * 24 * 3600)
    print(f"\nValidación: {len(oos):,} velas ({anios:.2f} años), "
          f"{oos.index[0]:%Y-%m-%d} → {oos.index[-1]:%Y-%m-%d}")
    print(f"Coste por lado {args.coste:.4%}   "
          f"sesiones {args.sesiones or 'todas'}\n")

    referencia = oos['close'].iloc[-1] / oos['close'].iloc[0] - 1
    print(f"Comprar y mantener en el mismo tramo: {referencia:+.1%}\n")

    zonas = (0.0, 0.1, 0.25, 0.5)
    suavizados = (0, 30, 180, 720, 2160)          # 0, 5min, 30min, 2h, 6h
    print(f"{'zona':>6} {'suavizado':>10} {'neto anual':>12} {'bruto':>9} {'costes':>9} "
          f"{'rotación':>10} {'Sharpe':>8}")

    filas = []
    for zona, suave in itertools.product(zonas, suavizados):
        cfg = posicion.ConfigPosicion(
            coste_por_lado=args.coste, apalancamiento=args.apalancamiento,
            zona_muerta=zona, suavizado=suave)
        r = posicion.ejecutar(oos["close"], conviccion, cfg)
        m = r.metricas()
        neto = m["bruto_anual"] - m["coste_anual"]
        etiqueta = "sin" if suave == 0 else f"{suave*10//60}min"
        print(f"{zona:>6.2f} {etiqueta:>10} {neto:>11.1%} {m['bruto_anual']:>8.1%} "
              f"{m['coste_anual']:>8.1%} {m['rotacion_anual']:>9.0f}x {m['sharpe']:>8.2f}")
        filas.append({"zona": zona, "suavizado": suave, "neto": neto, **m})

    tabla = pd.DataFrame(filas)
    positivas = (tabla["neto"] > 0).sum()
    print(f"\n{positivas} de {len(tabla)} configuraciones dan neto positivo.")

    mejor = tabla.loc[tabla["neto"].idxmax()]
    print(f"\nMejor: zona {mejor['zona']:.2f}, suavizado {int(mejor['suavizado'])} velas")
    print(f"  neto anual {mejor['neto']:+.1%}   bruto {mejor['bruto_anual']:+.1%}   "
          f"costes {mejor['coste_anual']:.1%}")
    print(f"  Sharpe {mejor['sharpe']:.2f}   max DD {mejor['max_drawdown']:.1%}   "
          f"rotación {mejor['rotacion_anual']:.0f}x/año")

    print(f"\n  Se probaron {len(tabla)} configuraciones sobre el mismo tramo, así que la")
    print(f"  mejor está elegida después de mirar. Lo que informa no es su cifra sino")
    print(f"  cuántas dan positivo: {positivas}/{len(tabla)}.")
    if mejor["bruto_anual"] <= 0:
        print("\n  El bruto ya es negativo: no hay coste lo bastante bajo que lo salve.")
    elif mejor["neto"] <= 0:
        umbral = args.coste * mejor["bruto_anual"] / max(mejor["coste_anual"], 1e-9)
        print(f"\n  La señal gana {mejor['bruto_anual']:.1%} bruto pero rota "
              f"{mejor['rotacion_anual']:.0f} veces al año.")
        print(f"  Haría falta un coste por lado por debajo de {umbral:.5%} "
              f"({umbral*10000:.2f} pb) para que quedara algo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
