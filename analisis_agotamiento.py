#!/usr/bin/env python3
"""
Agotamiento: ¿tras un desplazamiento extremo que barre liquidez, el mercado
deja de cumplir S/(S+T)?

Es una condición distinta de las probadas antes. Aquellas miraban el estado
contemporáneo: cómo está el libro ahora, cuánta expansión hay ahora. Ésta mira
**cuán extendido ya está el movimiento**, y lo mide en unidades de la
desviación típica que corresponde a ese horizonte.

La estructura temporal de BTC, medida sobre 14,4 millones de velas:

    30 s   0,0505 %      15 min  0,2726 %
     1 min 0,0717 %      30 min  0,3834 %
     3 min 0,1240 %       1 h    0,5408 %
     6 min 0,1745 %       4 h    1,0712 %

que escala casi exactamente como la raíz del tiempo. Eso permite decir "este
movimiento va por cuatro desviaciones" de forma comparable entre horizontes y
entre épocas.

A eso se le suma el recuento de barridos: cuántos mínimos o máximos previos ya
confirmados ha atravesado el precio. Son los sitios donde se acumulan órdenes
pendientes, y atravesarlos es lo que dispara las cascadas de stops.

La hipótesis a contrastar: tras un desplazamiento de varias sigmas que además
barre varios pools de liquidez, el movimiento está agotado y el precio revierte
más de lo que predice la fórmula del paseo aleatorio. Si es cierto, el exceso
tiene que salir positivo entrando CONTRA el desplazamiento.

    python analisis_agotamiento.py --stop 0.005 --ventana 30
"""

import argparse
import sys

import numpy as np
import pandas as pd

from backtest import barreras, ondas
from descargar_datos import cargar_datos

COSTE = 0.0012
# Ventana para estimar sigma de forma causal: 30 días de velas de 10 s.
VENTANA_SIGMA = 259200


def desplazamiento(cierre, barras, ventana=VENTANA_SIGMA):
    """
    Movimiento reciente medido en desviaciones típicas de ese mismo horizonte.

    La sigma se estima con una ventana móvil que sólo mira hacia atrás, así que
    "cuatro desviaciones" significa lo mismo en 2022 que en 2026 aunque la
    volatilidad de fondo haya cambiado por completo.
    """
    r = cierre.pct_change(barras)
    sigma = r.rolling(ventana, min_periods=ventana // 10).std()
    return (r / sigma).replace([np.inf, -np.inf], np.nan)


def barridos_en(patas, indices, cierre, lookback, buscar_minimos=True):
    """
    Cuántos pivotes previos ya confirmados ha atravesado el precio.

    Sólo cuentan los pivotes CONFIRMADOS antes de la barra evaluada: un mínimo
    del que todavía no se sabe que era mínimo no es un sitio donde nadie haya
    dejado órdenes.
    """
    if buscar_minimos:
        # Una pata bajista termina en un mínimo.
        sel = patas.direccion == -1
    else:
        sel = patas.direccion == 1
    conf = patas.confirmada_en[sel]
    precio = patas.precio_fin[sel]
    orden = np.argsort(conf)
    conf, precio = conf[orden], precio[orden]

    salida = np.zeros(len(indices), dtype=int)
    for k, i in enumerate(indices):
        hasta = np.searchsorted(conf, i, side="left")
        desde = np.searchsorted(conf, max(i - lookback, 0), side="left")
        if hasta <= desde:
            continue
        tramo = precio[desde:hasta]
        # Barrido: el precio actual quedó por debajo de un mínimo previo
        # (o por encima de un máximo previo).
        salida[k] = int((tramo > cierre[i]).sum() if buscar_minimos
                        else (tramo < cierre[i]).sum())
    return salida


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--ventana", type=int, default=30,
                        help="Barras de 10 s sobre las que medir el desplazamiento (30 = 5 min)")
    parser.add_argument("--stop", type=float, default=0.005)
    parser.add_argument("--ratio", type=float, default=1.0)
    parser.add_argument("--horizonte", type=int, default=360, help="24 h = 8640")
    parser.add_argument("--cada", type=int, default=180)
    parser.add_argument("--umbral-pivote", type=float, default=0.002)
    args = parser.parse_args()

    d = cargar_datos(args.datos)
    print(f"{len(d):,} velas de 10 s   {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}")

    cierre = d["close"]
    print(f"Midiendo desplazamiento sobre {args.ventana * 10 / 60:.0f} min...")
    z = desplazamiento(cierre, args.ventana).to_numpy()

    print(f"Detectando pivotes con umbral {args.umbral_pivote:.1%}...")
    patas = ondas.detectar(cierre.to_numpy(), args.umbral_pivote)
    print(f"  {len(patas):,} patas\n")

    alto = d["high"].to_numpy(dtype=float)
    bajo = d["low"].to_numpy(dtype=float)
    cie = cierre.to_numpy(dtype=float)
    cand = np.arange(args.ventana + 10, len(d) - 1, args.cada)
    cand = cand[np.isfinite(z[cand])]

    # Presión de compra ejecutada, para la parte de balance compras/ventas.
    with np.errstate(divide="ignore", invalid="ignore"):
        dsq = ((2 * d["taker_buy"] - d["volume"]) / d["volume"]).replace(
            [np.inf, -np.inf], np.nan).fillna(0.0)
    presion = dsq.ewm(span=args.ventana, adjust=False).mean().to_numpy()

    lookback = args.ventana * 12
    barr_min = barridos_en(patas, cand, cie, lookback, True)
    barr_max = barridos_en(patas, cand, cie, lookback, False)

    objetivo = args.stop * args.ratio
    p_teo = barreras.teorica(args.stop, objetivo)
    necesario = 0.5 + COSTE / (2 * args.stop) if args.ratio == 1.0 else None
    print(f"Bracket {args.stop:.1%} / {objetivo:.1%}, horizonte "
          f"{args.horizonte * 10 / 60:.0f} min")
    print(f"P teórica {p_teo:.4f}" + (f", necesaria {necesario:.4f} "
          f"(exceso +{necesario - p_teo:.4f})" if necesario else "") + "\n")

    zc = z[cand]
    casos = [
        ("todo", np.ones(len(cand), dtype=bool), 1),
        ("caída ≥ 2σ", zc <= -2, 1),
        ("caída ≥ 3σ", zc <= -3, 1),
        ("caída ≥ 4σ", zc <= -4, 1),
        ("caída ≥ 3σ + 2 mínimos barridos", (zc <= -3) & (barr_min >= 2), 1),
        ("caída ≥ 3σ + 4 mínimos barridos", (zc <= -3) & (barr_min >= 4), 1),
        ("caída ≥ 3σ + barridos + compra", (zc <= -3) & (barr_min >= 2) & (presion[cand] > 0), 1),
        ("subida ≥ 3σ", zc >= 3, -1),
        ("subida ≥ 4σ", zc >= 4, -1),
        ("subida ≥ 3σ + 2 máximos barridos", (zc >= 3) & (barr_max >= 2), -1),
        ("subida ≥ 3σ + barridos + venta", (zc >= 3) & (barr_max >= 2) & (presion[cand] < 0), -1),
    ]

    print(f"{'condición':<36} {'lado':>6} {'n':>7} {'%res':>6} {'p_real':>8} "
          f"{'exceso':>8} {'neto':>9}")
    filas = []
    for nombre, mascara, direccion in casos:
        entradas = cand[mascara]
        if len(entradas) < 150:
            print(f"{nombre:<36} {'—':>6} {len(entradas):>7}   (muestra insuficiente)")
            continue
        des = barreras.recorrer(alto, bajo, cie, entradas, args.stop, objetivo,
                                args.horizonte, direccion)
        r = barreras.contraste(des, args.stop, objetivo, COSTE)
        etiqueta = "largo" if direccion > 0 else "corto"
        marca = "  ← neto positivo" if r["neto_medio"] > 0 else ""
        print(f"{nombre:<36} {etiqueta:>6} {r['n']:>7,} "
              f"{1 - r['frac_tiempo']:>5.0%} {r['p_real']:>8.4f} {r['exceso']:>+8.4f} "
              f"{r['neto_medio']:>+8.4%}{marca}")
        filas.append({"condicion": nombre, **r})

    t = pd.DataFrame(filas)
    print(f"\n  {(t['neto_medio'] > 0).sum()} de {len(t)} dan neto positivo "
          f"(~{len(t) * 0.05:.1f} por azar).")
    print(f"  La columna %res es qué fracción se resuelve por barrera: por debajo")
    print(f"  del 70 % el exceso deja de medir el paso por barrera y no es fiable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
