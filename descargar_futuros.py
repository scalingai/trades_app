#!/usr/bin/env python3
"""
Descarga datos de futuros: basis, funding, open interest y profundidad de libro.

Todo lo medido hasta ahora salía de una única fuente, el precio y el flujo de
BTCUSDT al contado. Cinco modelos leyendo lo mismo coinciden en lo mismo, y por
eso su acuerdo valía menos de lo que parecía. Esto trae información que el
contado no contiene:

  basis        diferencia entre el precio del futuro perpetuo y el contado.
               Dice si el apalancamiento está pagando por estar largo o corto.
  funding      lo que efectivamente se pagan largos y cortos cada 8 horas.
               Es el precio de mantener la posición, y cuando se dispara suele
               anteceder a que alguien tenga que cerrarla.
  open interest cuántos contratos hay abiertos. Su caída brusca junto a un
               movimiento de precio es el rastro de una cascada de
               liquidaciones.
  ratios       cómo están posicionados los traders grandes frente al resto.
  profundidad  cuánto volumen hay en el libro a cada distancia porcentual del
               precio. Es liquidez real, no volumen ya ejecutado.

Sobre las liquidaciones: Binance publicaba un archivo histórico de
liquidaciones y lo discontinuó; la carpeta existe pero está vacía. Sólo se
pueden capturar en directo por websocket. El sustituto es la caída de open
interest, que es el rastro que dejan y sí está disponible con historia.

    python descargar_futuros.py --desde 2022-01-01
    python descargar_futuros.py --solo metrics funding basis
"""

import argparse
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from descargar_datos import CABECERAS, DIR_DATOS, _pedir, guardar

ARCHIVO = "https://data.binance.vision/data/futures/um"

# El perpetuo empezó antes, pero estas son las coberturas reales del archivo.
DESDE_MINIMO = {"basis": "2020-01", "funding": "2020-01",
                "metrics": "2020-09", "libro": "2023-01"}


def _meses(inicio, fin):
    mes = datetime(inicio.year, inicio.month, 1, tzinfo=timezone.utc)
    while mes < fin:
        yield mes
        siguiente = mes + timedelta(days=32)
        mes = datetime(siguiente.year, siguiente.month, 1, tzinfo=timezone.utc)


def _dias(inicio, fin):
    dia = datetime(inicio.year, inicio.month, inicio.day, tzinfo=timezone.utc)
    while dia < fin:
        yield dia
        dia += timedelta(days=1)


def _leer_zip(sesion, url, **kwargs):
    """Descarga un ZIP del archivo y devuelve su CSV como DataFrame, o None si no existe."""
    contenido = _pedir(sesion, url, binario=True)
    if contenido is None:
        return None
    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            crudo = f.read()
    if not crudo.strip():
        return None
    return pd.read_csv(io.BytesIO(crudo), **kwargs)


# ========================
# BASIS
# ========================

def descargar_basis(sesion, par, inicio, fin, spot):
    """
    Precio del futuro perpetuo, y su diferencia relativa con el contado.

    El basis positivo significa que el perpetuo cotiza por encima del contado,
    o sea que hay más presión compradora apalancada que vendedora.
    """
    partes = []
    for mes in _meses(inicio, fin):
        url = (f"{ARCHIVO}/monthly/klines/{par}/1m/"
               f"{par}-1m-{mes:%Y-%m}.zip")
        df = _leer_zip(sesion, url, header=None, usecols=[0, 4],
                       names=["timestamp", "futuro"])
        if df is None or df.empty:
            continue
        # Los archivos nuevos traen cabecera; se detecta y se descarta.
        if not str(df["timestamp"].iloc[0]).replace(".", "").isdigit():
            df = df.iloc[1:]
        partes.append(df)
        print(f"  · basis {mes:%Y-%m}: {len(df):,} minutos", file=sys.stderr)
    if not partes:
        return None

    df = pd.concat(partes, ignore_index=True)
    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype("int64").map(lambda v: v // 1000 if v > 1e14 else v),
        unit="ms", utc=True)
    df["futuro"] = pd.to_numeric(df["futuro"], errors="coerce")
    df = df.dropna().drop_duplicates("timestamp").sort_values("timestamp")

    # Se cruza con el contado en la misma marca de minuto.
    contado = spot["close"].resample("1min").last().rename("contado")
    df = df.set_index("timestamp").join(contado, how="inner")
    df["basis"] = (df["futuro"] - df["contado"]) / df["contado"]
    return df[["futuro", "contado", "basis"]].reset_index()


# ========================
# FUNDING
# ========================

def descargar_funding(sesion, par, inicio, fin):
    """Tasa de financiación, que se liquida cada 8 horas."""
    partes = []
    for mes in _meses(inicio, fin):
        url = f"{ARCHIVO}/monthly/fundingRate/{par}/{par}-fundingRate-{mes:%Y-%m}.zip"
        df = _leer_zip(sesion, url)
        if df is None or df.empty:
            continue
        partes.append(df)
    if not partes:
        return None
    df = pd.concat(partes, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
    df = df.rename(columns={"last_funding_rate": "funding"})
    print(f"  · funding: {len(df):,} liquidaciones de tasa", file=sys.stderr)
    return df[["timestamp", "funding"]].drop_duplicates("timestamp").sort_values("timestamp")


# ========================
# METRICS
# ========================

def descargar_metrics(sesion, par, inicio, fin):
    """
    Open interest y ratios de posicionamiento, cada 5 minutos.

    La caída brusca de open interest junto a un movimiento fuerte de precio es
    el rastro de una cascada de liquidaciones, que es lo más cerca que se puede
    estar del dato de liquidaciones sin capturarlo en directo.
    """
    partes = []
    for dia in _dias(inicio, fin):
        url = f"{ARCHIVO}/daily/metrics/{par}/{par}-metrics-{dia:%Y-%m-%d}.zip"
        df = _leer_zip(sesion, url)
        if df is None or df.empty:
            continue
        partes.append(df)
        if dia.day == 1:
            print(f"  · metrics {dia:%Y-%m}", file=sys.stderr)
    if not partes:
        return None

    df = pd.concat(partes, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["create_time"], utc=True)
    df = df.rename(columns={
        "sum_open_interest": "open_interest",
        "sum_open_interest_value": "open_interest_usd",
        "count_toptrader_long_short_ratio": "ratio_top_cuentas",
        "sum_toptrader_long_short_ratio": "ratio_top_posiciones",
        "count_long_short_ratio": "ratio_todos",
        "sum_taker_long_short_vol_ratio": "ratio_taker",
    })
    columnas = ["timestamp", "open_interest", "open_interest_usd", "ratio_top_cuentas",
                "ratio_top_posiciones", "ratio_todos", "ratio_taker"]
    return df[columnas].drop_duplicates("timestamp").sort_values("timestamp")


# ========================
# PROFUNDIDAD DE LIBRO
# ========================

def descargar_libro(sesion, par, inicio, fin):
    """
    Profundidad del libro a distintas distancias del precio.

    Cada instantánea trae, para cada porcentaje de distancia, cuánto volumen
    hay esperando. Se resume en el desequilibrio entre el lado comprador y el
    vendedor, que es lo que dice hacia dónde hay menos resistencia.
    """
    partes = []
    for dia in _dias(inicio, fin):
        url = f"{ARCHIVO}/daily/bookDepth/{par}/{par}-bookDepth-{dia:%Y-%m-%d}.zip"
        df = _leer_zip(sesion, url)
        if df is None or df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        # Los porcentajes negativos son el lado comprador y los positivos el vendedor.
        compra = df[df["percentage"] < 0].groupby("timestamp")["notional"].sum()
        venta = df[df["percentage"] > 0].groupby("timestamp")["notional"].sum()
        # Cerca del precio: sólo el primer 1 %, que es lo que se ejecuta primero.
        cerca_c = df[df["percentage"] == -1].set_index("timestamp")["notional"]
        cerca_v = df[df["percentage"] == 1].set_index("timestamp")["notional"]
        resumen = pd.DataFrame({
            "libro_compra": compra, "libro_venta": venta,
            "libro_compra_1pc": cerca_c, "libro_venta_1pc": cerca_v,
        }).dropna()
        partes.append(resumen.reset_index())
        if dia.day == 1:
            print(f"  · libro {dia:%Y-%m}", file=sys.stderr)
    if not partes:
        return None

    df = pd.concat(partes, ignore_index=True)
    total = df["libro_compra"] + df["libro_venta"]
    df["libro_deseq"] = (df["libro_compra"] - df["libro_venta"]) / total.replace(0, pd.NA)
    cerca = df["libro_compra_1pc"] + df["libro_venta_1pc"]
    df["libro_deseq_1pc"] = ((df["libro_compra_1pc"] - df["libro_venta_1pc"])
                             / cerca.replace(0, pd.NA))
    return df.drop_duplicates("timestamp").sort_values("timestamp")


# ========================
# CLI
# ========================

FUENTES = {"basis": descargar_basis, "funding": descargar_funding,
           "metrics": descargar_metrics, "libro": descargar_libro}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--par", default="BTCUSDT")
    parser.add_argument("--desde", default="2022-01-01")
    parser.add_argument("--hasta", default=None)
    parser.add_argument("--solo", nargs="+", choices=sorted(FUENTES), default=None)
    parser.add_argument("--spot", default="data/BTCUSDT_10s_binance.csv",
                        help="Serie al contado, necesaria para calcular el basis")
    args = parser.parse_args()

    inicio = datetime.strptime(args.desde, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    fin = (datetime.strptime(args.hasta, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if args.hasta else datetime.now(timezone.utc))
    pedidas = args.solo or list(FUENTES)

    sesion = requests.Session()
    sesion.headers.update(CABECERAS)

    spot = None
    if "basis" in pedidas:
        from descargar_datos import cargar_datos
        print(f"Cargando el contado desde {args.spot} (hace falta para el basis)...")
        spot = cargar_datos(args.spot)

    for nombre in pedidas:
        minimo = DESDE_MINIMO[nombre]
        arranque = max(inicio, datetime.strptime(minimo, "%Y-%m").replace(tzinfo=timezone.utc))
        if arranque > inicio:
            print(f"\n⚠️  {nombre}: el archivo empieza en {minimo}, "
                  f"así que se descarga desde ahí y no desde {inicio:%Y-%m}.")
        print(f"\n⬇️  {nombre}: {arranque:%Y-%m-%d} → {fin:%Y-%m-%d}")

        fn = FUENTES[nombre]
        df = fn(sesion, args.par, arranque, fin, spot) if nombre == "basis" \
            else fn(sesion, args.par, arranque, fin)
        if df is None or df.empty:
            print(f"❌ {nombre}: no se obtuvo nada.", file=sys.stderr)
            continue

        ruta = f"{DIR_DATOS}/{args.par}_{nombre}_binance.csv"
        guardar(df, ruta)
        print(f"   {len(df):,} filas · {df['timestamp'].iloc[0]:%Y-%m-%d} → "
              f"{df['timestamp'].iloc[-1]:%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
