#!/usr/bin/env python3
"""
Descarga de índices y divisas desde el archivo público de Dukascopy.

Todo lo medido en BTC chocó siempre contra lo mismo: el peaje. Un bracket de
200 puntos sobre BTC arriesga un 0,307 % y la comisión de ida y vuelta se lleva
un 0,12 %, o sea el 39 % de lo arriesgado. Con eso hace falta acertar siete de
cada diez sólo para empatar, y ninguna señal medida llegó ni cerca.

En futuros de índices la aritmética es otra. Un contrato de Nasdaq a 21.800
puntos son unos 436.000 dólares de nocional, la comisión de ida y vuelta ronda
los 4 dólares y el diferencial del CME es de un tick. Sobre un stop de 20
puntos —un 0,09 %— el coste pesa alrededor del 2 %, no del 39. El listón baja
de acertar el 69,5 % a rondar el 51 %.

Por eso vale la pena traer estos datos: no porque la señal vaya a ser mejor,
sino porque la misma señal ya alcanza.

**Formato.** Dukascopy publica ticks en archivos de una hora comprimidos con
LZMA, veinte bytes por tick: milisegundos desde el comienzo de la hora, ask,
bid, y volumen de cada lado. El mes va indexado desde cero en la URL, cosa que
cuesta un rato descubrir porque pedir enero devuelve diciembre sin quejarse.

**Qué es y qué no.** Son cotizaciones de CFD, no del contrato del CME. El
camino del precio es fiel porque está arbitrado contra el futuro, pero el
diferencial es el del bróker y es varias veces más ancho que el del mercado
real. Se guarda igual, en su propia columna, para poder ver cuándo se abre,
pero **no debe usarse como coste**: para eso están los costes reales del CME.

**El dólar.** No hay un instrumento del índice, así que se reconstruye con su
fórmula oficial a partir de los seis cruces que lo componen. Sale idéntico y
además a resolución de tick, que ningún proveedor gratuito da hecho.

    python descargar_indices.py NQ --desde 2023-01-01
    python descargar_indices.py NQ US30 SP500 --desde 2024-01-01 --barra 10s
    python descargar_indices.py DXY --desde 2024-01-01
"""

import argparse
import lzma
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/{sim}/{a:04d}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"

# El factor convierte el entero del archivo a precio. Los índices llevan tres
# decimales y los cruces con yen dos; el resto, cinco.
INSTRUMENTOS = {
    "NQ":     ("USATECHIDXUSD", 1000),
    "US30":   ("USA30IDXUSD", 1000),
    "SP500":  ("USA500IDXUSD", 1000),
    "EURUSD": ("EURUSD", 100000),
    "USDJPY": ("USDJPY", 1000),
    "GBPUSD": ("GBPUSD", 100000),
    "USDCAD": ("USDCAD", 100000),
    "USDSEK": ("USDSEK", 100000),
    "USDCHF": ("USDCHF", 100000),
}

# Fórmula oficial del índice dólar: media geométrica ponderada de seis cruces.
# Los exponentes van con signo negativo cuando el dólar es la moneda cotizada.
DXY_CONSTANTE = 50.14348112
DXY_PESOS = {
    "EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119,
    "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036,
}

TICK = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
                 ("vol_ask", ">f4"), ("vol_bid", ">f4")])
CABECERAS = {"User-Agent": "Mozilla/5.0"}


def descargar_hora(simbolo, factor, momento, reintentos=6, cache=None):
    """
    Ticks de una hora concreta, ya decodificados.

    Una hora sin datos devuelve un archivo vacío y no es un error: el mercado
    cierra los fines de semana y en los festivos, y de madrugada hay tramos sin
    una sola cotización.

    El servidor limita la tasa y responde 503 en cuanto se le pide de más, así
    que hay que reintentar con espera creciente en vez de darlo por perdido: a
    dos hilos ya rebota una de cada tres peticiones. Y como cada archivo cuesta
    su tiempo, se guardan en disco: reanudar una descarga cortada o cambiar el
    tamaño de barra no vuelve a pedir nada.
    """
    if cache is not None:
        guardado = cache / simbolo / f"{momento:%Y%m%d_%H}.bi5"
        if guardado.exists():
            crudo = guardado.read_bytes()
            return _decodificar(crudo, factor, momento)

    url = URL.format(sim=simbolo, a=momento.year, m=momento.month - 1,
                     d=momento.day, h=momento.hour)
    crudo = None
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=CABECERAS), timeout=60) as r:
                crudo = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                crudo = b""
                break
            if intento == reintentos - 1:
                return None
            time.sleep(min(2 ** intento, 30))
        except Exception:
            if intento == reintentos - 1:
                return None
            time.sleep(min(2 ** intento, 30))

    if cache is not None and crudo is not None:
        guardado.parent.mkdir(parents=True, exist_ok=True)
        guardado.write_bytes(crudo)
    return _decodificar(crudo, factor, momento)


def _decodificar(crudo, factor, momento):
    if not crudo:
        return None

    try:
        datos = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(crudo)
    except lzma.LZMAError:
        return None
    if len(datos) < TICK.itemsize:
        return None

    a = np.frombuffer(datos[:len(datos) // TICK.itemsize * TICK.itemsize], dtype=TICK)
    return pd.DataFrame({
        "timestamp": momento + pd.to_timedelta(a["ms"].astype("int64"), unit="ms"),
        "ask": a["ask"] / factor,
        "bid": a["bid"] / factor,
        "vol": a["vol_ask"].astype("float64") + a["vol_bid"].astype("float64"),
    })


def a_barras(ticks, barra="10s"):
    """
    Agrega ticks a velas sobre el punto medio.

    Se usa el medio y no el bid ni el ask porque el medio es el precio de
    referencia y no arrastra el margen del bróker. El diferencial se guarda
    aparte: es una señal por derecho propio —se abre en los momentos de
    tensión— pero no es el coste que pagaría quien opere el contrato del CME.
    """
    if ticks is None or ticks.empty:
        return pd.DataFrame()
    t = ticks.set_index("timestamp")
    medio = (t["ask"] + t["bid"]) / 2
    g = medio.resample(barra)
    salida = pd.DataFrame({
        "open": g.first(), "high": g.max(), "low": g.min(), "close": g.last(),
        "volume": t["vol"].resample(barra).sum(),
        "trades": medio.resample(barra).count(),
        "spread": (t["ask"] - t["bid"]).resample(barra).mean(),
    })
    return salida.dropna(subset=["close"])


def horas_utiles(desde, hasta, franja=None):
    """
    Horas a pedir, saltándose el fin de semana y, si se indica, las horas
    muertas del día.

    Para índices americanos la actividad se concentra entre la apertura europea
    y el cierre de Nueva York. Recortar el resto no pierde nada operable y baja
    la descarga casi a la mitad, que con este servidor es la diferencia entre
    una hora y dos.
    """
    h = pd.date_range(desde, hasta, freq="h", tz="UTC")
    h = h[h.dayofweek < 5]
    if franja:
        a, b = franja
        h = h[(h.hour >= a) & (h.hour < b)]
    return h


def descargar(clave, desde, hasta, barra="10s", hilos=4, verboso=True,
              franja=None, cache=None):
    """Serie de barras de un instrumento entre dos fechas."""
    simbolo, factor = INSTRUMENTOS[clave]
    horas = horas_utiles(desde, hasta, franja)
    if verboso:
        print(f"{clave} ({simbolo}): {len(horas):,} horas "
              f"{desde:%Y-%m-%d} → {hasta:%Y-%m-%d}"
              + (f", franja {franja[0]:02d}-{franja[1]:02d} UTC" if franja else ""))

    trozos, vacias, hechas = [], 0, 0
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for t in pool.map(lambda h: descargar_hora(simbolo, factor, h, cache=cache),
                          horas):
            hechas += 1
            if t is None or t.empty:
                vacias += 1
            else:
                trozos.append(t)
            if verboso and hechas % 500 == 0:
                ritmo = hechas / max(time.time() - inicio, 1)
                print(f"  {hechas:,}/{len(horas):,}  ({vacias:,} sin datos, "
                      f"{ritmo:.1f} horas/s, faltan "
                      f"{(len(horas) - hechas) / max(ritmo, 0.01) / 60:.0f} min)")

    if not trozos:
        return pd.DataFrame()
    ticks = pd.concat(trozos, ignore_index=True).sort_values("timestamp")
    if verboso:
        print(f"  {len(ticks):,} ticks, {vacias:,} horas sin datos "
              f"(fines de semana y festivos)")
    return a_barras(ticks, barra)


def construir_dxy(desde, hasta, barra="10s", hilos=4, verboso=True,
                  franja=None, cache=None):
    """
    Reconstruye el índice dólar con su fórmula oficial.

    Cada cruce se descarga por separado y se alinean por marca de tiempo antes
    de combinarlos. El relleno hacia delante es imprescindible porque los seis
    no cotizan en el mismo instante, y es causal: cada uno aporta su última
    cotización conocida y nunca una futura.
    """
    partes = {}
    for par in DXY_PESOS:
        d = descargar(par, desde, hasta, barra, hilos, verboso, franja, cache)
        if d.empty:
            raise RuntimeError(f"sin datos de {par}, no se puede armar el DXY")
        partes[par] = d["close"]

    juntos = pd.concat(partes, axis=1).ffill().dropna()
    indice = pd.Series(DXY_CONSTANTE, index=juntos.index)
    for par, peso in DXY_PESOS.items():
        indice *= juntos[par] ** peso

    return pd.DataFrame({
        "open": indice, "high": indice, "low": indice, "close": indice,
        "volume": 0.0, "trades": 1, "spread": 0.0,
    })


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("claves", nargs="+",
                        help=f"Instrumentos: {', '.join(INSTRUMENTOS)} o DXY")
    parser.add_argument("--desde", default="2023-01-01")
    parser.add_argument("--hasta", default=None, help="Por defecto, ayer")
    parser.add_argument("--barra", default="10s")
    parser.add_argument("--hilos", type=int, default=10,
                        help="Medido: 8 hilos van más rápido y fallan menos que 2, "
                             "así que los rebotes son intermitentes y no saturación")
    parser.add_argument("--franja", default="7-22",
                        help="Horas UTC a pedir, p. ej. 7-22. 'todo' para las 24")
    parser.add_argument("--cache", default="data/cache_dukascopy")
    parser.add_argument("--salida", default="data")
    args = parser.parse_args()

    desde = pd.Timestamp(args.desde, tz="UTC")
    hasta = (pd.Timestamp(args.hasta, tz="UTC") if args.hasta
             else pd.Timestamp(datetime.now(timezone.utc).date() - timedelta(days=1),
                               tz="UTC"))
    Path(args.salida).mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache) if args.cache else None
    franja = None
    if args.franja and args.franja != 'todo':
        a, b = args.franja.split('-')
        franja = (int(a), int(b))

    for clave in args.claves:
        if clave != "DXY" and clave not in INSTRUMENTOS:
            print(f"{clave}: desconocido. Disponibles: {', '.join(INSTRUMENTOS)}, DXY")
            continue
        inicio = time.time()
        d = (construir_dxy(desde, hasta, args.barra, args.hilos, True, franja, cache)
             if clave == "DXY" else
             descargar(clave, desde, hasta, args.barra, args.hilos, True,
                       franja, cache))
        if d.empty:
            print(f"{clave}: sin datos\n")
            continue

        ruta = Path(args.salida) / f"{clave}_{args.barra}_dukascopy.csv"
        d.to_csv(ruta, index_label="timestamp")
        print(f"  {len(d):,} barras de {args.barra}  "
              f"{d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}")
        print(f"  {ruta}  ({ruta.stat().st_size / 1e6:.0f} MB, "
              f"{time.time() - inicio:.0f} s)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
