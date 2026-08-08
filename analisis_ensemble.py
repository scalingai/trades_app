#!/usr/bin/env python3
"""
¿Sirve el ACUERDO entre modelos de distintas temporalidades?

Es una pregunta distinta de la que respondió el análisis anterior. Allí se
acumulaba la salida de un único modelo de 10 segundos, y no agregaba nada: la
predictibilidad era local a los próximos segundos. Aquí cada temporalidad tiene
su propio modelo, entrenado sobre sus propias velas para predecir su propio
horizonte, y lo que se mide es qué pasa cuando varios coinciden.

Todo se construye remuestreando la misma serie de 10 s, así que las cuatro
temporalidades comparten las mismas características de flujo de órdenes y la
comparación es limpia.

La alineación es la parte delicada. La probabilidad de una vela de 1 hora que
abre a las 14:00 se calcula con su cierre, que no se conoce hasta las 15:00,
así que sobre la rejilla de 10 s ese valor sólo puede aplicarse a partir de las
15:00. Si se aplicase desde las 14:00 el resultado sería espectacular y falso.

    python analisis_ensemble.py --horizontes 30min 1h 3h
"""

import argparse
import sys

import numpy as np
import pandas as pd

from descargar_datos import cargar_datos, remuestrear
from backtest import flujo

# Temporalidades a combinar, en segundos.
MARCOS = {"1min": 60, "5min": 300, "30min": 1800, "1h": 3600}

COSTE = 0.0012          # ida y vuelta, taker de Binance con slippage
SESIONES_BUENAS = [20, 21]


def modelo_de_marco(df10s, segundos, fraccion_is=0.7, verboso=True):
    """
    Entrena un modelo sobre una temporalidad y devuelve su probabilidad
    alineada causalmente sobre la rejilla de 10 segundos.

    El horizonte de predicción de cada marco es una vela suya: el modelo de 1
    hora predice la hora siguiente, el de 1 minuto el minuto siguiente.
    """
    base = df10s.reset_index().rename(columns={"index": "timestamp"})
    if "timestamp" not in base.columns:
        base = base.rename(columns={base.columns[0]: "timestamp"})
    marco = remuestrear(base, segundos).set_index("timestamp")

    x = flujo.construir(marco)
    y, _ = flujo.objetivo(marco, horizonte=1)
    corte = int(len(marco) * fraccion_is)
    modelo = flujo.entrenar(x.iloc[:corte], y.iloc[:corte])

    p = pd.Series(modelo.probabilidad(x), index=marco.index)
    auc = flujo.auc(p.iloc[corte:].to_numpy(), y.iloc[corte:].to_numpy())
    if verboso:
        print(f"  {segundos:>5}s  {len(marco):>9,} velas  AUC OOS {auc:.4f}")

    # Causalidad: la probabilidad de la vela que abre en T se conoce al
    # cerrarla, o sea en T + duración. Se desplaza el índice antes de
    # extenderla sobre la rejilla fina.
    p.index = p.index + pd.Timedelta(seconds=segundos)
    return p.reindex(df10s.index, method="ffill"), auc


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--horizontes", nargs="+", default=["30min", "1h", "3h"])
    parser.add_argument("--oos", type=float, default=0.3)
    args = parser.parse_args()

    horizontes = {"5min": 30, "30min": 180, "1h": 360, "3h": 1080}
    pedidos = {h: horizontes[h] for h in args.horizontes if h in horizontes}

    print(f"Cargando {args.datos} ...")
    df = cargar_datos(args.datos)
    print(f"{len(df):,} velas de 10 s\n")

    print("Entrenando un modelo por temporalidad:")
    probabilidades = {"10s": None}
    x10 = flujo.construir(df)
    y10, _ = flujo.objetivo(df, horizonte=1)
    corte = int(len(df) * (1 - args.oos))
    m10 = flujo.entrenar(x10.iloc[:corte], y10.iloc[:corte])
    p10 = pd.Series(m10.probabilidad(x10), index=df.index)
    print(f"  {10:>5}s  {len(df):>9,} velas  "
          f"AUC OOS {flujo.auc(p10.iloc[corte:].to_numpy(), y10.iloc[corte:].to_numpy()):.4f}")
    probabilidades["10s"] = p10

    for nombre, seg in MARCOS.items():
        probabilidades[nombre], _ = modelo_de_marco(df, seg, 1 - args.oos)

    # Sólo fuera de muestra a partir de aquí.
    oos = df.iloc[corte:]
    p = pd.DataFrame({k: v.iloc[corte:] for k, v in probabilidades.items()})

    # Acuerdo: cuántos modelos apuntan al alza. 0 = todos a la baja.
    alcistas = (p > 0.5).sum(axis=1)
    n_modelos = p.shape[1]

    print(f"\n{'='*74}")
    print(f"RETORNO FUTURO SEGÚN CUÁNTOS DE LOS {n_modelos} MODELOS COINCIDEN")
    print(f"{'='*74}")

    for etiqueta, barras in pedidos.items():
        fwd = oos["close"].shift(-barras) / oos["close"] - 1
        d = pd.DataFrame({"a": alcistas, "f": fwd}).dropna()
        print(f"\nHorizonte {etiqueta}   (coste ida y vuelta {COSTE:.2%})")
        print(f"  {'de acuerdo':>11} {'velas':>10} {'episodios':>9} {'ret medio':>11} "
              f"{'% verde':>9}   {'sólo 20-21 UTC':>15} {'episod':>8}")
        for k in range(n_modelos + 1):
            sel = d["a"] == k
            if sel.sum() < 500:
                continue
            sub = d.loc[sel, "f"]
            ses = d[(d["a"] == k) & d.index.hour.isin(SESIONES_BUENAS)]["f"]
            texto_ses = f"{ses.mean():>14.4%}" if len(ses) >= 200 else f"{'—':>14}"
            # Episodios independientes: las ventanas calculadas cada 10 s se
            # solapan casi por completo, así que el número de filas exagera
            # muchísimo la muestra real. Sin esta columna la tabla engaña.
            print(f"  {k:>11} {len(sub):>10,} {len(sub)/barras:>9.0f} "
                  f"{sub.mean():>10.4%} {(sub > 0).mean():>8.1%}   "
                  f"{texto_ses} {len(ses)/barras:>8.1f}")

        # El extremo alcista contra el bajista es lo que se podría capturar
        # operando los dos lados.
        arriba = d.loc[d["a"] == n_modelos, "f"]
        abajo = d.loc[d["a"] == 0, "f"]
        if len(arriba) >= 500 and len(abajo) >= 500:
            spread = arriba.mean() - abajo.mean()
            ses_a = d[(d["a"] == n_modelos) & d.index.hour.isin(SESIONES_BUENAS)]["f"]
            ses_b = d[(d["a"] == 0) & d.index.hour.isin(SESIONES_BUENAS)]["f"]
            linea = f"  unanimidad alcista − bajista: {spread:>8.4%}"
            if len(ses_a) >= 200 and len(ses_b) >= 200:
                linea += f"   en 20-21 UTC: {ses_a.mean() - ses_b.mean():>8.4%}"
            print(linea)
            episodios = min(len(arriba), len(abajo)) / barras
            juicio = "supera el coste" if spread > COSTE else "NO llega al coste"
            print(f"  {juicio}, sobre ~{episodios:.0f} episodios independientes"
                  f"{'  <- muestra insuficiente para creerselo' if episodios < 30 else ''}")

    print(f"\n{'='*74}")
    print("Dos avisos que hay que leer antes que la tabla:")
    print()
    print("1. Los episodios, no las velas, son la muestra. Una ventana de 3 h")
    print("   medida cada 10 s se solapa un 99,1 % con la siguiente, así que")
    print("   11.000 velas son unos 10 episodios independientes.")
    print("2. El acuerdo entre modelos no es independiente: todos comparten las")
    print("   mismas características de flujo sobre la misma serie, así que")
    print("   coinciden más de lo que coincidirían cuatro opiniones separadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
