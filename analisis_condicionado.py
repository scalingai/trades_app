#!/usr/bin/env python3
"""
Barreras condicionadas: ¿hay estados del mercado donde BTC deja de cumplir
S/(S+T)?

El barrido incondicional ya dio su respuesta: sobre 14 millones de velas y
dieciocho geometrías de bracket, el exceso sobre la fórmula del paseo
aleatorio es de −0,002 a −0,010 y el bruto medio es cero. La geometría no crea
ventaja.

Queda una sola vía: que existan ESTADOS en los que el mercado sí se desvíe.
Este script prueba los tres candidatos que quedaron medidos a lo largo de la
investigación, más el único dato que nunca se había cruzado.

**Contraste libro contra ejecutado.** Es el candidato nuevo y la razón de haber
bajado el libro. Todo lo demás que se midió es una transformación del precio;
el libro es lo único que dice qué hay ESPERANDO en vez de qué ya pasó. La
hipótesis concreta: cuando el volumen agresivo empuja en una dirección y del
otro lado el libro está delgado, no hay quien absorba y el precio debería
recorrer más de lo que predice la fórmula. Si eso es cierto, el exceso tiene
que salir positivo justo en ese estado.

**Expansión alta.** Ya está medido que el decil superior se mueve 4,3 veces más
que el inferior. Con más recorrido, el coste pesa menos.

**Sesión 20-21 UTC.** Aparece por tres métodos independientes: sesgo de
retornos horarios, AUC del modelo de flujo y repetibilidad mes a mes.

Y todo se corre en largo y en corto por separado, porque con el basis negativo
el 87 % del tiempo no hay razón para suponer que los dos lados se comporten
igual.

    python analisis_condicionado.py --stop 0.02
"""

import argparse
import sys

import numpy as np
import pandas as pd

from backtest import barreras
from descargar_datos import cargar_datos

COSTE = 0.0012


def cargar_estado(ruta_spot, ruta_libro):
    """Serie de 10 s con el estado de flujo, libro y expansión en cada vela."""
    d = cargar_datos(ruta_spot)

    libro = pd.read_csv(ruta_libro, usecols=["timestamp", "libro_deseq", "libro_deseq_1pc"])
    libro["timestamp"] = pd.to_datetime(libro["timestamp"], utc=True, format="ISO8601")
    libro = libro.set_index("timestamp").sort_index()
    # Cada instantánea se conoce en su marca de tiempo, así que se extiende
    # hacia delante y nunca hacia atrás.
    libro = libro.reindex(d.index, method="ffill")

    d = d.join(libro).dropna(subset=["libro_deseq_1pc"])

    # Presión ejecutada: qué parte del volumen entró comprando a mercado.
    with np.errstate(divide="ignore", invalid="ignore"):
        dsq = ((2 * d["taker_buy"] - d["volume"]) / d["volume"]).replace(
            [np.inf, -np.inf], np.nan).fillna(0.0)
    d["presion"] = dsq.ewm(span=30, adjust=False).mean()        # 5 minutos

    # Expansión reciente como aproximación causal del régimen.
    d["expansion"] = d["close"].pct_change().abs().rolling(360).mean()

    return d.dropna(subset=["presion", "expansion"])


def condiciones(d):
    """
    Estados a contrastar. Cada uno devuelve una máscara booleana alineada con d.

    El contraste libro/ejecutado se define por cuartiles para que "presión
    alta" y "libro delgado" signifiquen lo mismo en 2023 que en 2026.
    """
    pres_alta = d["presion"] >= d["presion"].quantile(0.75)
    pres_baja = d["presion"] <= d["presion"].quantile(0.25)
    # libro_deseq_1pc negativo = más profundidad del lado vendedor.
    venta_delgada = d["libro_deseq_1pc"] >= d["libro_deseq_1pc"].quantile(0.75)
    compra_delgada = d["libro_deseq_1pc"] <= d["libro_deseq_1pc"].quantile(0.25)
    exp_alta = d["expansion"] >= d["expansion"].quantile(0.75)
    sesion = d.index.hour.isin([20, 21])

    return {
        "(sin condición)": np.ones(len(d), dtype=bool),
        "compra agresiva": pres_alta.to_numpy(),
        "venta agresiva": pres_baja.to_numpy(),
        "libro: venta delgada": venta_delgada.to_numpy(),
        "libro: compra delgada": compra_delgada.to_numpy(),
        "compra agresiva + venta delgada": (pres_alta & venta_delgada).to_numpy(),
        "venta agresiva + compra delgada": (pres_baja & compra_delgada).to_numpy(),
        "expansión alta": exp_alta.to_numpy(),
        "sesión 20-21 UTC": sesion,
        "expansión alta + sesión": (exp_alta.to_numpy() & sesion),
        "las tres apiladas": (pres_alta & venta_delgada).to_numpy() & exp_alta.to_numpy() & sesion,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spot", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--libro", default="data/BTCUSDT_libro_binance.csv")
    parser.add_argument("--stop", type=float, default=0.02)
    parser.add_argument("--ratio", type=float, default=1.0)
    parser.add_argument("--horizonte", type=int, default=8640, help="Velas de 10 s (8640 = 24 h)")
    parser.add_argument("--cada", type=int, default=720, help="Espaciado entre entradas")
    args = parser.parse_args()

    print(f"Cargando y alineando libro con contado...")
    d = cargar_estado(args.spot, args.libro)
    print(f"{len(d):,} velas de 10 s   {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}\n")

    objetivo = args.stop * args.ratio
    p_teo = barreras.teorica(args.stop, objetivo)
    necesario = 0.5 + COSTE / (2 * args.stop) if args.ratio == 1.0 else None

    print(f"Bracket: stop {args.stop:.1%}, objetivo {objetivo:.1%}, "
          f"horizonte {args.horizonte * 10 / 3600:.0f} h")
    print(f"P teórica del paseo aleatorio: {p_teo:.4f}")
    if necesario:
        print(f"P necesaria para cubrir el coste de {COSTE:.2%}: {necesario:.4f} "
              f"(exceso de {necesario - p_teo:+.4f})")
    print()

    alto = d["high"].to_numpy(dtype=float)
    bajo = d["low"].to_numpy(dtype=float)
    cierre = d["close"].to_numpy(dtype=float)
    candidatas = np.arange(0, len(d) - 1, args.cada)

    print(f"{'condición':<34} {'lado':>6} {'n':>7} {'%tiempo':>8} {'p_real':>8} "
          f"{'exceso':>8} {'neto':>9}")
    filas = []
    for nombre, mascara in condiciones(d).items():
        entradas = candidatas[mascara[candidatas]]
        if len(entradas) < 200:
            print(f"{nombre:<34} {'—':>6} {len(entradas):>7}   (muestra insuficiente)")
            continue
        for direccion, etiqueta in ((1, "largo"), (-1, "corto")):
            des = barreras.recorrer(alto, bajo, cierre, entradas, args.stop,
                                    objetivo, args.horizonte, direccion)
            r = barreras.contraste(des, args.stop, objetivo, COSTE)
            if not r:
                continue
            filas.append({"condicion": nombre, "lado": etiqueta, **r})
            marca = ""
            if r["neto_medio"] > 0:
                marca = "  ← neto positivo"
            print(f"{nombre:<34} {etiqueta:>6} {r['n']:>7,} "
                  f"{mascara.mean():>7.1%} {r['p_real']:>8.4f} {r['exceso']:>+8.4f} "
                  f"{r['neto_medio']:>+8.4%}{marca}")

    t = pd.DataFrame(filas)
    positivos = t[t["neto_medio"] > 0]
    print(f"\n  {len(positivos)} de {len(t)} combinaciones dan neto positivo.")
    print(f"  Se probaron {len(t)} combinaciones, así que ~{len(t) * 0.05:.1f} saldrían")
    print(f"  positivas por azar aunque no hubiera nada. Y las entradas están")
    print(f"  espaciadas {args.cada * 10 / 3600:.1f} h con horizonte de "
          f"{args.horizonte * 10 / 3600:.0f} h, así que se solapan y la muestra")
    print(f"  efectiva es menor que la n que aparece.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
