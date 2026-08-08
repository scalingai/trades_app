#!/usr/bin/env python3
"""
¿Hay dos poblaciones dentro del barrido, o una sola?

Todo lo medido hasta aquí dice que tras un barrido el precio **continúa**, con
un exceso de +0,04 sobre la fórmula del paseo aleatorio. Pero ese número es el
promedio de la muestra entera, y un promedio no distingue entre una población
homogénea que continúa un poquito y una mezcla de rupturas que continúan
fuerte con barridos que revierten fuerte.

Hay además un motivo concreto para sospechar que es lo segundo: la regla que
detecta el barrido mira **sólo el mínimo**, nunca dónde cerró el precio.

    barrio_suelo = bajo[ventana].min() < suelo

Con eso, el día que rompe el mínimo previo y se hunde un dos por ciento más y
el día que lo rompe, se da vuelta y cierra otra vez dentro del rango reciben la
misma etiqueta. El segundo es el barrido de manual; el primero no lo llama
barrido nadie. Estando mezclados, y siendo las rupturas más numerosas, el
promedio se inclina a continuación por construcción.

Así que la pregunta no es "qué condiciones mejoran la continuación" —eso ya se
probó y da mejoras pequeñas— sino **qué variable parte la muestra en dos
grupos de signo contrario**. Un puntaje sube el grupo bueno; un separador sube
el bueno Y baja el malo a la vez. Son búsquedas distintas.

Cuatro reglas de higiene, todas aprendidas a golpes en este proyecto:

1. **Se mide el exceso, no el neto.** El neto de una operación que cierra por
   tiempo se lleva dentro la deriva de fondo de BTC, y con horizontes largos
   eso llegó a producir celdas con exceso negativo y neto positivo a la vez.
   El exceso sólo cuenta las que tocaron barrera y es inmune a la deriva.
2. **Se exige que la mayoría se resuelva por barrera.** Si demasiadas cierran
   por tiempo, el exceso deja de describir la muestra.
3. **Largo y corto por separado.** Un efecto que sólo aparece en el lado largo
   sobre un histórico alcista es la subida, no el efecto.
4. **Permutación.** Buscar el mejor de ocho candidatos encuentra algo siempre.

    python analisis_separador.py
    python analisis_separador.py --inicio 22 --grupos 4
"""

import argparse
import sys
from datetime import time

import numpy as np
import pandas as pd

from backtest import barreras, separador, ventanas
from descargar_datos import cargar_datos

VENTANA_SIGMA = 259200


def sigma_causal(cierre, barras, ventana=VENTANA_SIGMA):
    return cierre.pct_change(barras).rolling(
        ventana, min_periods=ventana // 10).std()


def apariciones(d, alto, bajo, zona, inicio, horas, previa):
    """Ventanas con barrido de un solo lado, con su nivel roto."""
    fin = time((inicio + horas) % 24, 0)
    m = ventanas.mascara_ventana(d.index, time(inicio, 0), fin, zona)
    ini = ventanas.ocurrencias(m, "primera", marcas=d.index)
    fin_ = ventanas.ocurrencias(m, "ultima", marcas=d.index)
    n = min(len(ini), len(fin_))
    ini, fin_ = ini[:n], fin_[:n]
    lado = ventanas.direccion_por_barrido(alto, bajo, ini, fin_, previa)
    hay = lado != 0
    return ini[hay], fin_[hay], lado[hay]


def caracteristicas(d, alto, bajo, cierre, ini, fin, barrido, previa, horizonte):
    """
    Todo lo que se sabía al cerrar la ventana, una fila por aparición.

    `barrido` vale +1 cuando se perforó el mínimo previo y −1 cuando el máximo.
    Las variables se firman con ese signo cuando corresponde, para que "mucho"
    signifique lo mismo en los dos lados y los dos se puedan medir juntos.
    """
    s = sigma_causal(d["close"], horizonte).to_numpy()
    volumen = d["volume"].to_numpy(dtype=float)
    vol_medio = d["volume"].rolling(8640).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        presion = ((2 * d["taker_buy"] - d["volume"]) / d["volume"]).replace(
            [np.inf, -np.inf], np.nan).fillna(0.0).to_numpy()

    f = {k: np.full(len(ini), np.nan) for k in (
        "cierre_dentro", "penetracion", "retroceso", "velocidad", "volumen_rel",
        "recorrido_sigma", "presion", "posicion_cierre", "toques")}

    for k, (a, b, lado) in enumerate(zip(ini, fin, barrido)):
        desde = max(int(a) - previa, 0)
        if desde >= a:
            continue
        techo, suelo = alto[desde:a].max(), bajo[desde:a].min()
        nivel = suelo if lado > 0 else techo
        alto_v, bajo_v = alto[a:b + 1].max(), bajo[a:b + 1].min()
        extremo = bajo_v if lado > 0 else alto_v
        c = cierre[b]
        sigma = s[b] if np.isfinite(s[b]) and s[b] > 0 else np.nan

        # La condición del modelo que faltaba: ¿el cierre volvió adentro del
        # rango anterior, o se quedó del otro lado?
        f["cierre_dentro"][k] = float(c > nivel if lado > 0 else c < nivel)

        # Cuánto se pasó de largo, en sigmas. Asomar la nariz no es romper.
        f["penetracion"][k] = abs(nivel - extremo) / nivel / sigma

        # Qué parte de la excursión devolvió antes de cerrar. Es la variable
        # que separa "barrió y volvió" de "barrió y siguió".
        excursion = abs(extremo - nivel)
        f["retroceso"][k] = (abs(c - extremo) / excursion
                             if excursion > 0 else np.nan)

        # Velocidad del barrido: una cascada de stops es vertical, un reprecio
        # de verdad se toma su tiempo.
        j = int(np.argmin(bajo[a:b + 1]) if lado > 0 else np.argmax(alto[a:b + 1]))
        f["velocidad"][k] = abs(extremo - cierre[a]) / cierre[a] / max(j, 1)

        f["volumen_rel"][k] = (volumen[a:b + 1].mean() / vol_medio[b]
                               if np.isfinite(vol_medio[b]) and vol_medio[b] > 0
                               else np.nan)
        f["recorrido_sigma"][k] = (alto_v - bajo_v) / c / sigma
        # Presión firmada: positiva significa "a favor del barrido".
        f["presion"][k] = presion[a:b + 1].mean() * (-lado)
        f["posicion_cierre"][k] = ((c - bajo_v) / (alto_v - bajo_v)
                                   if alto_v > bajo_v else np.nan)
        # Cuántas veces se rozó el nivel antes: el tercer intento no es el primero.
        cerca = (np.abs(bajo[desde:a] - nivel) / nivel < 0.001 if lado > 0
                 else np.abs(alto[desde:a] - nivel) / nivel < 0.001)
        f["toques"][k] = float(cerca.sum())

    return f


def regimen(d, ruta_funding=None, ruta_metricas=None):
    """
    Contexto de fondo en el que cae cada operación, todo causal.

    Un efecto que aparece en veintitrés meses de cuarenta y ocho puede ser
    inestable o puede ser dependiente del régimen, y son cosas distintas: lo
    primero no se puede operar y lo segundo sí, filtrando. Distinguirlas es el
    mismo contraste que separar rupturas de barridos, con otras candidatas.

    Se usan los indicadores nativos del mercado en vez de series
    macroeconómicas porque son los que existen a esta frecuencia y porque para
    BTC dicen más: el funding y el interés abierto describen cuánto
    apalancamiento hay y de qué lado, que es lo que decide si un movimiento se
    alimenta solo.
    """
    r = {}
    dia = 8640                                  # velas de 10 s en un día
    cierre = d["close"]

    # Tendencia de fondo: dónde está el precio respecto de su media larga.
    media = cierre.rolling(200 * dia, min_periods=30 * dia).mean()
    r["tendencia"] = (cierre / media - 1).to_numpy()

    # Régimen de volatilidad: la de esta semana contra la del último año.
    vol = cierre.pct_change().abs().rolling(7 * dia, min_periods=dia).mean()
    r["vol_regimen"] = (vol / vol.rolling(365 * dia, min_periods=30 * dia).mean()
                        ).to_numpy()

    # Caída desde el máximo histórico conocido hasta ese momento.
    r["caida_desde_max"] = (cierre / cierre.cummax() - 1).to_numpy()

    if ruta_funding:
        f = pd.read_csv(ruta_funding)
        f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True, format="ISO8601")
        s = f.set_index("timestamp")["funding"].sort_index()
        # Sólo el último corte ya pagado: el siguiente todavía no se conoce.
        r["funding"] = s.reindex(d.index, method="ffill").to_numpy()
        r["funding_medio"] = s.rolling(21).mean().reindex(
            d.index, method="ffill").to_numpy()

    if ruta_metricas:
        m = pd.read_csv(ruta_metricas, usecols=["timestamp", "open_interest"])
        m["timestamp"] = pd.to_datetime(m["timestamp"], utc=True, format="ISO8601")
        oi = m.set_index("timestamp")["open_interest"].sort_index()
        oi = oi.reindex(d.index, method="ffill")
        # Variación semanal del interés abierto: apalancamiento entrando o saliendo.
        r["oi_semanal"] = (oi / oi.shift(7 * dia) - 1).to_numpy()

    return r


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--zona", default="nueva-york", choices=sorted(ventanas.ZONAS))
    parser.add_argument("--inicio", type=int, default=1)
    parser.add_argument("--horas", type=int, default=3)
    parser.add_argument("--previa", type=int, default=480)
    parser.add_argument("--stop", type=float, default=0.005)
    parser.add_argument("--ratio", type=float, default=1.0)
    parser.add_argument("--horizonte", type=int, default=2160)
    parser.add_argument("--grupos", type=int, default=2)
    parser.add_argument("--repeticiones", type=int, default=300)
    parser.add_argument("--funding", default="data/BTCUSDT_funding_binance.csv")
    parser.add_argument("--metricas", default="data/BTCUSDT_metrics_binance.csv")
    parser.add_argument("--sin-regimen", action="store_true",
                        help="Probar sólo las variables del propio barrido")
    args = parser.parse_args()

    d = cargar_datos(args.datos)
    alto = d["high"].to_numpy(dtype=float)
    bajo = d["low"].to_numpy(dtype=float)
    cierre = d["close"].to_numpy(dtype=float)
    previa = args.previa * 6

    ini, fin, barrido = apariciones(d, alto, bajo, args.zona, args.inicio,
                                    args.horas, previa)
    print(f"{len(d):,} velas   ventana {args.inicio:02d}:00-"
          f"{(args.inicio + args.horas) % 24:02d}:00 ({args.zona})")
    print(f"{len(ini):,} apariciones con barrido de un solo lado\n")

    # Se opera SIEMPRE a favor de la continuación. Lo que se busca no es la
    # dirección buena, sino la variable que dice cuándo esa dirección falla:
    # si un grupo acierta mucho y el otro poco, ahí hay dos poblaciones.
    lado = -barrido
    trozos = []
    orden = []
    for direccion in (1, -1):
        sel = np.flatnonzero(lado == direccion)
        if len(sel) == 0:
            continue
        trozos.append(barreras.recorrer(alto, bajo, cierre, fin[sel], args.stop,
                                        args.stop * args.ratio, args.horizonte,
                                        direccion))
        orden.append(sel)
    des = barreras.Desenlaces(
        np.concatenate([t.entrada for t in trozos]),
        np.concatenate([t.salida for t in trozos]),
        np.concatenate([t.motivo for t in trozos]),
        np.concatenate([t.retorno for t in trozos]),
        np.concatenate([np.full(len(t), t.direccion) for t in trozos]))
    # `recorrer` puede descartar entradas sin horizonte por delante; se realinea
    # por posición de entrada para no cruzar características con otra operación.
    posicion = {int(v): k for k, v in enumerate(fin)}
    fila = np.array([posicion[int(e)] for e in des.entrada])

    f = caracteristicas(d, alto, bajo, cierre, ini, fin, barrido, previa,
                        args.horizonte)
    f = {k: v[fila] for k, v in f.items()}
    n_barrido = len(f)
    if not args.sin_regimen:
        # El contexto se lee en la vela de entrada, no en la de salida.
        reg = regimen(d, args.funding, args.metricas)
        f.update({k: v[des.entrada] for k, v in reg.items()})

    resueltas = des.motivo != barreras.TIEMPO
    gana = des.motivo[resueltas] == barreras.OBJETIVO
    p_teo = barreras.teorica(args.stop, args.stop * args.ratio)
    print(f"Bracket {args.stop:.2%} a {args.ratio:.1f}, horizonte "
          f"{args.horizonte * 10 / 3600:.0f} h")
    print(f"  {resueltas.mean():.0%} se resuelve por barrera "
          f"({'suficiente' if resueltas.mean() > 0.85 else 'INSUFICIENTE, el exceso no es fiable'})")
    print(f"  acierto global {gana.mean():.4f}, paseo aleatorio {p_teo:.4f}, "
          f"exceso {gana.mean() - p_teo:+.4f}")
    largo = des.direccion[resueltas] > 0
    print(f"  por lado: largo {gana[largo].mean():+.4f} ({largo.sum()}), "
          f"corto {gana[~largo].mean():+.4f} ({(~largo).sum()})\n")

    cand = {k: v[resueltas] for k, v in f.items()}
    tabla, veredicto = separador.contraste(cand, gana, args.grupos,
                                           args.repeticiones)

    print(f"Separación por variable (acierto del grupo alto menos el del bajo)")
    print(f"  {n_barrido} del propio barrido, {len(cand) - n_barrido} de contexto\n")
    cols = [f"g{k}" for k in range(args.grupos)]
    print(f"     {'variable':<18} {'separación':>11}  " +
          " ".join(f"{c:>7}" for c in cols))
    for _, r in tabla.iterrows():
        grupos = " ".join(f"{r[c]:>7.4f}" if np.isfinite(r[c]) else f"{'—':>7}"
                          for c in cols)
        # Cambio de signo: un grupo por encima del paseo y el otro por debajo.
        flip = ("  ← cambia de signo"
                if np.isfinite(r["g0"]) and np.isfinite(r[cols[-1]])
                and (r["g0"] - p_teo) * (r[cols[-1]] - p_teo) < 0 else "")
        print(f"     {r['variable']:<18} {r['separacion']:>+11.4f}  {grupos}{flip}")

    print(f"\n  El paseo aleatorio da {p_teo:.4f}: un grupo por encima y otro por")
    print(f"  debajo es lo que significa que hay dos poblaciones.\n")
    print(f"  Permutación con {veredicto['repeticiones']} barajadas:")
    print(f"    mejor separación real       {veredicto['mejor']:.4f}")
    print(f"    mejor separación por azar   {veredicto['nulo_medio']:.4f} de media, "
          f"{veredicto['nulo_p95']:.4f} en el percentil 95")
    print(f"    p = {veredicto['p']:.4f}")
    if veredicto["p"] < 0.05:
        print(f"\n  Hay separación por encima de lo que produce buscar el máximo\n"
              f"  entre {len(cand)} candidatas sobre datos sin relación.")
    else:
        print(f"\n  No hay separación por encima del azar. Con estas variables, la\n"
              f"  muestra se comporta como una sola población y no como una mezcla.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
