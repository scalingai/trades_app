#!/usr/bin/env python3
"""
Descarga de datos históricos OHLCV (Bitcoin y cualquier otro par) para
backtesting local. No necesita API key: usa endpoints públicos.

Fuentes disponibles:
  - binance  : histórico completo de BTCUSDT desde 2017-08-17. Para rangos
               largos usa los archivos mensuales de data.binance.vision
               (mucho más rápido que pedir vela por vela).
  - coinbase : BTC-USD desde 2015. Útil como respaldo si Binance está
               bloqueado en tu región (responde HTTP 451).

Ejemplos:
    # Velas de 1 hora desde 2020 (lo típico para empezar)
    python descargar_datos.py --intervalo 1h --desde 2020-01-01

    # Todo el histórico diario disponible
    python descargar_datos.py --intervalo 1d

    # Velas de 1 minuto de un semestre concreto
    python descargar_datos.py --intervalo 1m --desde 2024-01-01 --hasta 2024-06-30

    # Añadir las velas nuevas a un archivo ya descargado
    python descargar_datos.py --intervalo 1h --actualizar

    # Respaldo si Binance no responde desde tu país
    python descargar_datos.py --fuente coinbase --par BTC-USD --intervalo 1h
"""

import argparse
import io
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# ========================
# CONFIGURACIÓN
# ========================

DIR_DATOS = "data"

COLUMNAS = ["timestamp", "open", "high", "low", "close", "volume"]

# Duración de cada vela en segundos. Sirve para paginar las peticiones y para
# detectar huecos en la serie descargada.
INTERVALOS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800,
}

# api.binance.com devuelve 451 en varias regiones (EE.UU. entre ellas).
# data-api.binance.vision expone los mismos endpoints de market data sin
# restricción geográfica, así que sirve de respaldo automático.
HOSTS_BINANCE = ["https://api.binance.com", "https://data-api.binance.vision"]
ARCHIVO_BINANCE = "https://data.binance.vision/data/spot"
LIMITE_BINANCE = 1000          # velas por petición REST

URL_COINBASE = "https://api.exchange.coinbase.com"
LIMITE_COINBASE = 300          # velas por petición
# Coinbase sólo acepta estas granularidades (en segundos).
GRANULARIDADES_COINBASE = {60, 300, 900, 3600, 21600, 86400}

CABECERAS = {"User-Agent": "trades_app/1.0 (backtesting local)"}


# ========================
# UTILIDADES
# ========================

def _fecha_utc(texto):
    """Convierte 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM' a datetime UTC."""
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Fecha no reconocida: {texto!r} (usa YYYY-MM-DD)")


def _ms(dt):
    """datetime -> milisegundos epoch."""
    return int(dt.timestamp() * 1000)


def _normalizar_ms(valor):
    """
    Los archivos de data.binance.vision posteriores a 2025-01-01 traen los
    timestamps en microsegundos en lugar de milisegundos. Se detecta por
    magnitud y se corrige.
    """
    valor = int(valor)
    return valor // 1000 if valor > 1e14 else valor


def _pedir(sesion, url, params=None, intentos=5, binario=False):
    """GET con reintentos y espera exponencial. Devuelve None si es 404."""
    espera = 1.0
    for intento in range(intentos):
        try:
            resp = sesion.get(url, params=params, timeout=30)
            if resp.status_code == 404:
                return None
            # 429 = rate limit, 418 = IP baneada temporalmente por Binance.
            if resp.status_code in (418, 429) or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            # El resto de errores 4xx (par inexistente, parámetro inválido...) no
            # se arreglan reintentando: se cortan aquí.
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"El servidor rechazó la petición (HTTP {resp.status_code}). "
                    f"Revisa que el par y el intervalo existan en esa fuente.\n   {resp.text[:200]}"
                )
            return resp.content if binario else resp.json()
        except (requests.RequestException, ValueError) as err:
            if intento == intentos - 1:
                raise RuntimeError(f"Fallo al pedir {url}: {err}") from err
            time.sleep(espera)
            espera *= 2
    return None


def _host_binance(sesion):
    """Devuelve el primer host de Binance que responda desde esta red."""
    for host in HOSTS_BINANCE:
        try:
            resp = sesion.get(f"{host}/api/v3/ping", timeout=15)
            if resp.status_code == 200:
                return host
            print(f"  · {host} responde HTTP {resp.status_code}, probando el siguiente",
                  file=sys.stderr)
        except requests.RequestException as err:
            print(f"  · {host} no responde ({err}), probando el siguiente", file=sys.stderr)
    raise RuntimeError(
        "Ningún host de Binance está disponible. Prueba con --fuente coinbase."
    )


# ========================
# BINANCE
# ========================

def _klines_a_filas(crudas):
    """Convierte la respuesta de Binance al esquema canónico."""
    return [
        (_normalizar_ms(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
        for k in crudas
    ]


def _binance_rest(sesion, host, par, intervalo, inicio_ms, fin_ms):
    """Descarga velas por el API REST, paginando de 1000 en 1000."""
    filas = []
    cursor = inicio_ms
    paso = INTERVALOS[intervalo] * 1000
    while cursor < fin_ms:
        datos = _pedir(sesion, f"{host}/api/v3/klines", params={
            "symbol": par,
            "interval": intervalo,
            "startTime": cursor,
            "endTime": fin_ms,
            "limit": LIMITE_BINANCE,
        })
        if not datos:
            break
        filas.extend(_klines_a_filas(datos))
        cursor = _normalizar_ms(datos[-1][0]) + paso
        if len(datos) < LIMITE_BINANCE:
            break
        time.sleep(0.12)   # margen cómodo frente al rate limit
    return filas


def _binance_archivo_mes(sesion, par, intervalo, anio, mes):
    """
    Descarga el ZIP mensual de data.binance.vision. Devuelve None si ese mes
    todavía no está publicado (el archivo mensual aparece unos días después
    de cerrar el mes).
    """
    nombre = f"{par}-{intervalo}-{anio:04d}-{mes:02d}"
    url = f"{ARCHIVO_BINANCE}/monthly/klines/{par}/{intervalo}/{nombre}.zip"
    contenido = _pedir(sesion, url, binario=True)
    if contenido is None:
        return None

    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        with zf.open(zf.namelist()[0]) as csv_bruto:
            crudo = csv_bruto.read()

    # Los archivos antiguos no traen cabecera y los nuevos sí.
    primera = crudo.split(b"\n", 1)[0].split(b",")[0].strip().strip(b'"')
    tiene_cabecera = not primera.isdigit()

    df = pd.read_csv(
        io.BytesIO(crudo),
        header=0 if tiene_cabecera else None,
        usecols=range(6),
        names=None if tiene_cabecera else COLUMNAS,
    )
    df.columns = COLUMNAS
    df["timestamp"] = df["timestamp"].map(_normalizar_ms)
    return df


def descargar_binance(par, intervalo, inicio, fin):
    """
    Estrategia mixta: los meses ya cerrados se bajan como ZIP (una petición
    por mes en vez de miles) y el tramo final se completa por REST.
    """
    if intervalo not in INTERVALOS:
        raise ValueError(f"Intervalo no soportado por Binance: {intervalo}")

    sesion = requests.Session()
    sesion.headers.update(CABECERAS)
    host = _host_binance(sesion)
    print(f"  · usando {host}", file=sys.stderr)

    partes = []
    # Los ZIP mensuales sólo compensan a partir de velas de 1 día o menores;
    # para 3d/1w hay pocas velas y el REST las trae de una sola vez.
    usar_archivo = INTERVALOS[intervalo] <= 86400
    cursor = inicio

    if usar_archivo:
        # Primer día del mes siguiente al actual: frontera de los meses cerrados.
        hoy = datetime.now(timezone.utc)
        limite_archivo = datetime(hoy.year, hoy.month, 1, tzinfo=timezone.utc)
        mes = datetime(inicio.year, inicio.month, 1, tzinfo=timezone.utc)
        vacios_seguidos = 0

        while mes < min(fin, limite_archivo):
            df_mes = _binance_archivo_mes(sesion, par, intervalo, mes.year, mes.month)
            if df_mes is not None and not df_mes.empty:
                partes.append(df_mes)
                cursor = mes + timedelta(days=32)
                cursor = datetime(cursor.year, cursor.month, 1, tzinfo=timezone.utc)
                vacios_seguidos = 0
                print(f"  · archivo {mes:%Y-%m}: {len(df_mes)} velas", file=sys.stderr)
            else:
                vacios_seguidos += 1
                # Varios meses seguidos sin archivo = el par aún no cotizaba o
                # el histórico se acabó; el resto lo resuelve el REST.
                if vacios_seguidos >= 3 and partes:
                    break
            siguiente = mes + timedelta(days=32)
            mes = datetime(siguiente.year, siguiente.month, 1, tzinfo=timezone.utc)

    if cursor < fin:
        print(f"  · completando desde {cursor:%Y-%m-%d} por API REST", file=sys.stderr)
        filas = _binance_rest(sesion, host, par, intervalo, _ms(cursor), _ms(fin))
        if filas:
            partes.append(pd.DataFrame(filas, columns=COLUMNAS))

    if not partes:
        return pd.DataFrame(columns=COLUMNAS)
    return pd.concat(partes, ignore_index=True)


# ========================
# COINBASE
# ========================

def descargar_coinbase(par, intervalo, inicio, fin):
    """Descarga velas de Coinbase Exchange, de 300 en 300."""
    granularidad = INTERVALOS.get(intervalo)
    if granularidad not in GRANULARIDADES_COINBASE:
        validos = sorted(k for k, v in INTERVALOS.items() if v in GRANULARIDADES_COINBASE)
        raise ValueError(f"Coinbase sólo admite estos intervalos: {', '.join(validos)}")

    sesion = requests.Session()
    sesion.headers.update(CABECERAS)

    filas = []
    cursor = inicio
    tramo = timedelta(seconds=granularidad * LIMITE_COINBASE)

    while cursor < fin:
        hasta = min(cursor + tramo, fin)
        datos = _pedir(sesion, f"{URL_COINBASE}/products/{par}/candles", params={
            "granularity": granularidad,
            "start": cursor.isoformat().replace("+00:00", "Z"),
            "end": hasta.isoformat().replace("+00:00", "Z"),
        })
        if datos:
            # Coinbase devuelve [time, low, high, open, close, volume] descendente.
            filas.extend(
                (int(v[0]) * 1000, float(v[3]), float(v[2]), float(v[1]), float(v[4]), float(v[5]))
                for v in datos
            )
            print(f"\r  · {cursor:%Y-%m-%d} → {len(filas)} velas", end="", file=sys.stderr)
        cursor = hasta
        time.sleep(0.2)   # el límite público ronda las 10 peticiones/s

    print("", file=sys.stderr)
    return pd.DataFrame(filas, columns=COLUMNAS)


# ========================
# NORMALIZACIÓN Y CONTROL DE CALIDAD
# ========================

def normalizar(df, intervalo, inicio, fin, alinear=True):
    """Ordena, quita duplicados, recorta al rango pedido y pasa a UTC."""
    if df.empty:
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    if alinear:
        # Tras algunas paradas largas (p.ej. el mantenimiento de Binance del
        # 8-9/02/2018) el exchange reanuda las velas desfasadas respecto a la
        # rejilla horaria. Un índice irregular rompe resample() y las medias
        # móviles, así que se cuadra cada vela a su casilla.
        rejilla = df["timestamp"].dt.floor(f"{INTERVALOS[intervalo]}s")
        df["desalineada"] = rejilla != df["timestamp"]
        df["timestamp"] = rejilla
        # Si al cuadrar coincide con una vela ya alineada, se conserva ésta.
        df = df.sort_values(["timestamp", "desalineada"])

    df = df.drop_duplicates(subset="timestamp", keep="first").sort_values("timestamp")
    df = df[(df["timestamp"] >= inicio) & (df["timestamp"] < fin)]
    return df.reset_index(drop=True)


def revisar_calidad(df, intervalo):
    """Avisa de huecos y de velas incoherentes antes de usar los datos."""
    if df.empty:
        print("⚠️  No se descargó ninguna vela.", file=sys.stderr)
        return

    paso = pd.Timedelta(seconds=INTERVALOS[intervalo])
    diferencias = df["timestamp"].diff().dropna()
    huecos = diferencias[diferencias > paso]

    incoherentes = df[
        (df["high"] < df["low"])
        | (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
    ]

    print(f"\n📊 {len(df):,} velas · {df['timestamp'].iloc[0]:%Y-%m-%d %H:%M} → "
          f"{df['timestamp'].iloc[-1]:%Y-%m-%d %H:%M} UTC")
    print(f"   precio: mín {df['low'].min():,.2f} · máx {df['high'].max():,.2f} · "
          f"último {df['close'].iloc[-1]:,.2f}")

    desalineadas = int(df["desalineada"].sum()) if "desalineada" in df else 0
    if desalineadas:
        print(f"ℹ️  {desalineadas} vela(s) venían desfasadas de la rejilla y se han "
              f"cuadrado a su casilla de {intervalo}.")

    if len(huecos):
        velas_faltantes = int(((huecos - paso) / paso).sum())
        print(f"⚠️  {len(huecos)} hueco(s) en la serie (~{velas_faltantes:,} velas ausentes). "
              f"Mayor hueco: {huecos.max()}")
        print("   Es normal: son paradas de mantenimiento del exchange. Tenlo en cuenta "
              "si tu estrategia asume continuidad.")
    else:
        print("   ✅ serie continua, sin huecos")

    if len(incoherentes):
        print(f"⚠️  {len(incoherentes)} vela(s) con OHLC incoherente")

    # La última vela suele estar a medio formar: su cierre no es un cierre real.
    if df["timestamp"].iloc[-1] + paso > pd.Timestamp.now(tz="UTC"):
        print(f"ℹ️  La última vela ({df['timestamp'].iloc[-1]:%Y-%m-%d %H:%M}) aún se está "
              f"formando. Descártala al backtestear o vuelve a lanzar --actualizar luego.")


# ========================
# GUARDADO Y CARGA
# ========================

def ruta_archivo(par, intervalo, fuente, formato="csv"):
    return os.path.join(DIR_DATOS, f"{par}_{intervalo}_{fuente}.{formato}")


def guardar(df, ruta):
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    df = df[COLUMNAS]        # descarta columnas auxiliares del control de calidad
    if ruta.endswith(".parquet"):
        df.to_parquet(ruta, index=False)
    else:
        df.to_csv(ruta, index=False)
    tamanio = os.path.getsize(ruta) / 1024
    unidad = f"{tamanio:,.0f} KB" if tamanio < 1024 else f"{tamanio / 1024:,.1f} MB"
    print(f"💾 Guardado en {ruta} ({unidad})")


def cargar_datos(ruta):
    """Carga un archivo descargado listo para backtestear (índice temporal UTC)."""
    if ruta.endswith(".parquet"):
        df = pd.read_parquet(ruta)
    else:
        df = pd.read_csv(ruta)
    # format="ISO8601" tolera que unas filas lleven fracción de segundo y otras no.
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp").set_index("timestamp")


# ========================
# CLI
# ========================

def main():
    parser = argparse.ArgumentParser(
        description="Descarga datos históricos OHLCV para backtesting local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ejemplos:")[-1],
    )
    parser.add_argument("--fuente", choices=["binance", "coinbase"], default="binance")
    parser.add_argument("--par", default=None,
                        help="Par a descargar (por defecto BTCUSDT en Binance, BTC-USD en Coinbase)")
    parser.add_argument("--intervalo", default="1h", choices=sorted(INTERVALOS),
                        help="Tamaño de vela (por defecto 1h)")
    parser.add_argument("--desde", type=_fecha_utc, default=None,
                        help="Fecha inicial UTC YYYY-MM-DD (por defecto, todo el histórico)")
    parser.add_argument("--hasta", type=_fecha_utc, default=None,
                        help="Fecha final UTC YYYY-MM-DD (por defecto, ahora)")
    parser.add_argument("--salida", default=None, help="Ruta del archivo de salida")
    parser.add_argument("--formato", choices=["csv", "parquet"], default="csv")
    parser.add_argument("--actualizar", action="store_true",
                        help="Continúa un archivo existente desde su última vela")
    parser.add_argument("--sin-alinear", dest="alinear", action="store_false",
                        help="Conserva los timestamps tal cual los publica el exchange, "
                             "sin cuadrarlos a la rejilla del intervalo")
    args = parser.parse_args()

    par = args.par or ("BTCUSDT" if args.fuente == "binance" else "BTC-USD")
    salida = args.salida or ruta_archivo(par, args.intervalo, args.fuente, args.formato)

    # Mejor avisar ahora que tras media hora de descarga.
    if salida.endswith(".parquet"):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            print("❌ El formato parquet necesita pyarrow: pip install pyarrow", file=sys.stderr)
            return 1

    # Binance publica BTCUSDT desde el 17/08/2017; Coinbase BTC-USD desde 2015.
    inicio = args.desde or datetime(2017, 8, 17, tzinfo=timezone.utc)
    fin = args.hasta or datetime.now(timezone.utc)

    previo = None
    if args.actualizar and os.path.exists(salida):
        previo = cargar_datos(salida).reset_index()
        # Se reanuda EN la última vela, no después: la que se guardó pudo quedar a
        # medio formar y hay que reemplazarla por su versión ya cerrada.
        inicio = previo["timestamp"].iloc[-1].to_pydatetime()
        print(f"🔄 Actualizando {salida} desde {inicio:%Y-%m-%d %H:%M} UTC")
        if inicio >= fin:
            print("✅ Ya está al día, no hay velas nuevas.")
            return 0

    print(f"⬇️  Descargando {par} {args.intervalo} de {args.fuente}: "
          f"{inicio:%Y-%m-%d} → {fin:%Y-%m-%d} UTC")

    descargar = descargar_binance if args.fuente == "binance" else descargar_coinbase
    try:
        df = descargar(par, args.intervalo, inicio, fin)
    except (RuntimeError, ValueError) as err:
        print(f"❌ {err}", file=sys.stderr)
        return 1

    df = normalizar(df, args.intervalo, inicio, fin, alinear=args.alinear)

    if previo is not None and not previo.empty:
        # keep="last": ante un timestamp repetido gana lo recién descargado.
        df = pd.concat([previo, df], ignore_index=True)
        df = (df.drop_duplicates(subset="timestamp", keep="last")
                .sort_values("timestamp").reset_index(drop=True))

    if df.empty:
        print("❌ No se obtuvo ninguna vela. Revisa el par, el rango o prueba otra fuente.",
              file=sys.stderr)
        return 1

    revisar_calidad(df, args.intervalo)
    guardar(df, salida)
    print(f"\n▶️  Para usarlo:  from descargar_datos import cargar_datos; "
          f"df = cargar_datos({salida!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
