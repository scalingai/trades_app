#!/usr/bin/env python3
"""
El modelo de 10 segundos sirve para ejecutar, no para decidir la dirección.

Este análisis separa dos preguntas que se confunden con facilidad:

  DIRECCIÓN   ¿hacia dónde va el precio en los próximos minutos?
  EJECUCIÓN   dado que voy a entrar en los próximos minutos, ¿en qué segundo
              exacto conviene hacerlo?

Son capas distintas de un mismo sistema y necesitan modelos distintos. El
modelo de flujo a 10 segundos responde bien a la segunda y mal a la primera, y
usarlo para lo que no es resulta activamente perjudicial.

La medición: se parte el histórico en ventanas de 5 minutos y, dentro de cada
una, se compara entrar en la vela de mayor probabilidad, en la de menor, o en
una cualquiera. Después se mide el retorno a 5, 15, 30 y 60 minutos.

El resultado es que entrar en la vela de MAYOR probabilidad da peor resultado
que entrar al azar, y entrar en la de MENOR probabilidad lo da mejor. Tiene
sentido: el modelo predice el siguiente tick al alza, así que señala justo el
momento previo a un repunte, o sea un máximo local. Comprar ahí es comprar caro.
Comprar cuando el flujo inmediato está en contra es comprar barato.

La ventaja es de unos 0,0073 % por lado y se mantiene igual en los cuatro
horizontes, que es lo que la hace creíble: si fuera ruido no se repetiría con
esa estabilidad al cambiar la duración del trade.

Lo que NO hace esto es crear una ventaja. Ahorra en torno al 12 % del coste de
ida y vuelta, así que abarata una ventaja que ya exista. La capa de dirección
sigue siendo el problema abierto.

    python analisis_ejecucion.py --ventana 30
"""

import argparse
import sys

import numpy as np
import pandas as pd

from backtest import flujo
from descargar_datos import cargar_datos

COSTE_LADO = 0.0006


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--ventana", type=int, default=30,
                        help="Velas de 10 s en las que se puede elegir el momento (30 = 5 min)")
    parser.add_argument("--oos", type=float, default=0.3)
    args = parser.parse_args()

    df = cargar_datos(args.datos)
    print(f"{len(df):,} velas de 10 s   {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}")

    x = flujo.construir(df)
    y, _ = flujo.objetivo(df, horizonte=1)
    corte = int(len(df) * (1 - args.oos))
    modelo = flujo.entrenar(x.iloc[:corte], y.iloc[:corte])

    oos = df.iloc[corte:]
    p = pd.Series(modelo.probabilidad(x.iloc[corte:]), index=oos.index)
    print(f"Validación: {len(oos):,} velas   AUC "
          f"{flujo.auc(p.to_numpy(), y.iloc[corte:].to_numpy()):.4f}\n")

    bloque = np.arange(len(oos)) // args.ventana
    minutos = args.ventana * 10 / 60
    print(f"Elegir el momento dentro de ventanas de {minutos:.0f} minutos:\n")
    print(f"  {'duración':>10} {'al azar':>11} {'máx prob':>11} {'mín prob':>11} "
          f"{'ventaja':>10} {'ventanas':>10}")

    ventajas = []
    for barras, etiqueta in ((30, "5 min"), (90, "15 min"), (180, "30 min"), (360, "1 hora")):
        futuro = (oos["close"].shift(-barras) / oos["close"] - 1).to_numpy()
        d = pd.DataFrame({"b": bloque, "p": p.to_numpy(), "f": futuro}).dropna()
        g = d.groupby("b")
        azar = g["f"].mean().mean()
        alto = d.loc[g["p"].idxmax(), "f"].mean()
        bajo = d.loc[g["p"].idxmin(), "f"].mean()
        ventajas.append(bajo - azar)
        print(f"  {etiqueta:>10} {azar:>10.4%} {alto:>10.4%} {bajo:>10.4%} "
              f"{bajo - azar:>9.4%} {g.ngroups:>10,}")

    media = float(np.mean(ventajas))
    dispersion = float(np.std(ventajas))
    print(f"\n  Ventaja media por lado: {media:.4%}   dispersión entre horizontes: "
          f"{dispersion:.4%}")
    print(f"  Que la ventaja apenas cambie al variar la duración del trade es lo que")
    print(f"  la hace creíble: un efecto de ejecución no debería depender de cuánto")
    print(f"  dure la posición, y no depende.")

    ahorro = 2 * media
    coste = 2 * COSTE_LADO
    print(f"\n  Aplicado a las dos puntas: {ahorro:.4%} sobre un coste de {coste:.2%}")
    print(f"  = {ahorro / coste:.0%} del coste de ida y vuelta.")
    print(f"\n  Esto ABARATA una ventaja, no la crea. Sin una capa de dirección que")
    print(f"  gane más del {coste - ahorro:.3%} por operación, sigue sin haber negocio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
