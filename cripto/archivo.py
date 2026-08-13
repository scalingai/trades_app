"""Cliente del archivo público de Binance — el único punto que toca la red.

Misma disciplina que `edgar/client.py`: throttle, reintentos y cache en disco
centralizados en un solo módulo, para que ningún otro archivo tenga que
acordarse de hacerlo bien.

Dos decisiones que importan:

**Se usa el listado S3 y no el endpoint REST.** `fapi.binance.com` devuelve 451
en varias regiones, y además solo lista lo que cotiza HOY. El listado del
bucket enumera todo lo que alguna vez existió, deslistados incluidos — que es
justamente lo que evita el sesgo de supervivencia (RESEARCH.md §1.1).

**Un 404 no es un error.** Un símbolo no tiene archivo para los meses en que no
existía, y eso es información: es como se deriva la fecha de listado. Se
distingue de un fallo de red, que sí se reintenta.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import config

ARCHIVO = "https://data.binance.vision"
LISTADO = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

_TIMEOUT = 30
_REINTENTOS = 4
_PAUSA_BASE = 1.5

_sesion: requests.Session | None = None


def sesion() -> requests.Session:
    global _sesion
    if _sesion is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "algotrade-cripto/0.1"})
        _sesion = s
    return _sesion


class NoExiste(Exception):
    """El archivo no está porque el símbolo no existía en ese período.

    Se separa de los errores de red a propósito: esto no se reintenta y no es
    un fallo, es un dato.
    """


def _pedir(url: str) -> bytes:
    ultimo = None
    for intento in range(_REINTENTOS):
        try:
            r = sesion().get(url, timeout=_TIMEOUT)
            if r.status_code == 404:
                raise NoExiste(url)
            if r.status_code == 200:
                return r.content
            # 429 y 5xx: vale la pena esperar. 4xx restantes, no.
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code} en {url}")
            ultimo = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            ultimo = e
        time.sleep(_PAUSA_BASE * (2 ** intento))
    raise RuntimeError(f"fallo tras {_REINTENTOS} intentos: {url} ({ultimo})")


# ───────────────────────────────── universo ────────────────────────────────


def listar_simbolos(mercado: str = "futures/um") -> list[str]:
    """Todos los símbolos con historia en el archivo, incluidos los muertos."""
    prefijo = f"data/{mercado}/monthly/klines/"
    url = f"{LISTADO}?delimiter=/&prefix={prefijo}"
    texto = _pedir(url).decode("utf-8", "replace")
    simbolos = re.findall(
        rf"<Prefix>{re.escape(prefijo)}([^/]+)/</Prefix>", texto)
    if "<IsTruncated>true</IsTruncated>" in texto:
        # No debería pasar con ~1.000 símbolos, pero si el universo crece y
        # esto se ignora, el estudio quedaría con un universo truncado en
        # silencio — el peor tipo de error.
        raise RuntimeError(
            "el listado vino truncado: hay que paginar con marker")
    return sorted(simbolos)


# ─────────────────────────────────── velas ─────────────────────────────────

# Esquema de las klines de Binance. Las últimas dos columnas del CSV son
# 'taker_buy_quote' e 'ignore'; se documentan todas para no contar mal.
COLUMNAS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _meses(desde: date, hasta: date):
    m = date(desde.year, desde.month, 1)
    fin = date(hasta.year, hasta.month, 1)
    while m <= fin:
        yield m
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def _ruta_klines(simbolo: str, intervalo: str, mes: date,
                 mercado: str = "futures/um") -> str:
    ym = mes.strftime("%Y-%m")
    return (f"{ARCHIVO}/data/{mercado}/monthly/klines/{simbolo}/{intervalo}/"
            f"{simbolo}-{intervalo}-{ym}.zip")


def _cache_path(simbolo: str, intervalo: str, mes: date) -> Path:
    d = config.cache_dir() / "klines" / simbolo / intervalo
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{mes.strftime('%Y-%m')}.csv"


def klines_mes(simbolo: str, intervalo: str, mes: date,
               mercado: str = "futures/um") -> list[list[str]]:
    """Velas de un mes. Cachea en disco; devuelve [] si el mes no existe.

    El cache guarda el CSV crudo y no el parseado, para que un cambio en cómo
    se interpretan las columnas no obligue a volver a bajar 6.000 archivos.
    """
    cache = _cache_path(simbolo, intervalo, mes)
    marca_vacio = cache.with_suffix(".vacio")

    if marca_vacio.exists():
        return []
    if cache.exists():
        texto = cache.read_text(encoding="utf-8")
    else:
        try:
            crudo = _pedir(_ruta_klines(simbolo, intervalo, mes, mercado))
        except NoExiste:
            # Se marca el hueco para no volver a preguntar. Sin esto, cada
            # corrida repite miles de peticiones que ya sabemos que dan 404.
            marca_vacio.write_text("")
            return []
        with zipfile.ZipFile(io.BytesIO(crudo)) as z:
            texto = z.read(z.namelist()[0]).decode("utf-8", "replace")
        cache.write_text(texto, encoding="utf-8")

    filas = []
    for linea in texto.splitlines():
        if not linea or linea[0] not in "0123456789":
            continue  # los archivos de 2025+ traen cabecera
        filas.append(linea.split(","))
    return filas


def _ts_a_fecha(raw: str) -> date:
    """Timestamp de Binance a fecha UTC.

    Los archivos posteriores a 2025-01 vienen en MICROsegundos y los anteriores
    en milisegundos, sin avisar. Se detecta por magnitud: un valor en
    microsegundos de una fecha razonable tiene 16 dígitos.
    """
    v = int(raw)
    if v > 1e15:
        v //= 1000
    return datetime.fromtimestamp(v / 1000, tz=timezone.utc).date()


def barras_diarias(simbolo: str, desde: date, hasta: date) -> list[dict]:
    """Velas diarias de un símbolo en un rango, ya parseadas.

    La última vela puede estar a medio formar; el que consume decide si la
    descarta (ver `descargar.py`).
    """
    salida = []
    for mes in _meses(desde, hasta):
        for f in klines_mes(simbolo, "1d", mes):
            try:
                d = _ts_a_fecha(f[0])
            except (ValueError, IndexError):
                continue
            if d < desde or d > hasta:
                continue
            try:
                salida.append({
                    "d": d.isoformat(),
                    "open": float(f[1]), "high": float(f[2]),
                    "low": float(f[3]), "close": float(f[4]),
                    "volume": float(f[5]),
                    "quote_volume": float(f[7]),
                    "trades": int(float(f[8])),
                    "taker_buy_quote": float(f[10]),
                })
            except (ValueError, IndexError):
                continue  # fila corrupta: se saltea, no se inventa
    return salida


def meses_con_datos(simbolo: str, desde: date, hasta: date) -> list[str]:
    """Qué meses tienen archivo. Es como se deriva la fecha de listado."""
    return [m.strftime("%Y-%m") for m in _meses(desde, hasta)
            if klines_mes(simbolo, "1d", m)]
