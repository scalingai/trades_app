"""
Indicadores técnicos vectorizados sobre numpy.

Todos devuelven un array del mismo largo que la entrada, con NaN en las
primeras barras que aún no tienen histórico suficiente. Trabajan sobre numpy
y no sobre pandas porque el generador genético los evalúa miles de veces y la
diferencia de velocidad importa.
"""

import numpy as np

# Nombre -> (función, nº de periodos que necesita). El generador genético usa
# este catálogo para saber qué bloques puede combinar.
CATALOGO = {}


def _registrar(nombre, minimo=2, maximo=200):
    def envoltura(fn):
        CATALOGO[nombre] = {"fn": fn, "min": minimo, "max": maximo}
        return fn
    return envoltura


def _serie(datos, campo="close"):
    return datos[campo] if isinstance(datos, dict) else datos


# ========================
# MEDIAS Y TENDENCIA
# ========================

@_registrar("sma")
def sma(precios, periodo):
    """Media móvil simple."""
    precios = np.asarray(precios, dtype=float)
    if periodo < 1 or periodo > len(precios):
        return np.full(len(precios), np.nan)
    acumulado = np.concatenate(([0.0], np.cumsum(precios)))
    salida = np.full(len(precios), np.nan)
    salida[periodo - 1:] = (acumulado[periodo:] - acumulado[:-periodo]) / periodo
    return salida


@_registrar("ema")
def ema(precios, periodo):
    """Media móvil exponencial, arrancando con la SMA del primer tramo."""
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    salida = np.full(n, np.nan)
    if periodo < 1 or periodo > n:
        return salida
    alfa = 2.0 / (periodo + 1.0)
    valor = precios[:periodo].mean()
    salida[periodo - 1] = valor
    for i in range(periodo, n):
        valor = alfa * precios[i] + (1 - alfa) * valor
        salida[i] = valor
    return salida


@_registrar("wma")
def wma(precios, periodo):
    """Media móvil ponderada linealmente."""
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    if periodo < 1 or periodo > n:
        return np.full(n, np.nan)
    pesos = np.arange(1, periodo + 1, dtype=float)
    pesos /= pesos.sum()
    salida = np.full(n, np.nan)
    salida[periodo - 1:] = np.convolve(precios, pesos[::-1], mode="valid")
    return salida


@_registrar("macd")
def macd(precios, periodo):
    """
    Línea MACD (rápida - lenta). El periodo define la media rápida; la lenta
    se toma como el doble, manteniendo la proporción clásica 12/26.
    """
    rapida = ema(precios, periodo)
    lenta = ema(precios, max(periodo * 2, periodo + 1))
    return rapida - lenta


# ========================
# OSCILADORES
# ========================

@_registrar("rsi", minimo=2, maximo=100)
def rsi(precios, periodo):
    """RSI de Wilder (suavizado exponencial con alfa = 1/periodo)."""
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    salida = np.full(n, np.nan)
    if periodo < 1 or periodo >= n:
        return salida

    delta = np.diff(precios)
    subidas = np.where(delta > 0, delta, 0.0)
    bajadas = np.where(delta < 0, -delta, 0.0)

    media_sub = subidas[:periodo].mean()
    media_baj = bajadas[:periodo].mean()
    salida[periodo] = 100.0 if media_baj == 0 else 100 - 100 / (1 + media_sub / media_baj)

    for i in range(periodo, n - 1):
        media_sub = (media_sub * (periodo - 1) + subidas[i]) / periodo
        media_baj = (media_baj * (periodo - 1) + bajadas[i]) / periodo
        salida[i + 1] = 100.0 if media_baj == 0 else 100 - 100 / (1 + media_sub / media_baj)
    return salida


@_registrar("estocastico", minimo=3, maximo=100)
def estocastico(datos, periodo):
    """%K del oscilador estocástico: dónde cierra dentro del rango reciente."""
    alto, bajo, cierre = datos["high"], datos["low"], datos["close"]
    maximo = maximo_movil(alto, periodo)
    minimo = minimo_movil(bajo, periodo)
    rango = maximo - minimo
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(rango > 0, 100.0 * (cierre - minimo) / rango, 50.0)


@_registrar("roc", minimo=1, maximo=200)
def roc(precios, periodo):
    """Rate of change: variación porcentual respecto a N barras atrás."""
    precios = np.asarray(precios, dtype=float)
    salida = np.full(len(precios), np.nan)
    if periodo < 1 or periodo >= len(precios):
        return salida
    previo = precios[:-periodo]
    with np.errstate(divide="ignore", invalid="ignore"):
        salida[periodo:] = np.where(previo != 0, 100.0 * (precios[periodo:] - previo) / previo, 0.0)
    return salida


@_registrar("cci", minimo=3, maximo=100)
def cci(datos, periodo):
    """Commodity Channel Index sobre el precio típico."""
    tipico = (datos["high"] + datos["low"] + datos["close"]) / 3.0
    media = sma(tipico, periodo)
    n = len(tipico)
    desviacion = np.full(n, np.nan)
    for i in range(periodo - 1, n):
        ventana = tipico[i - periodo + 1:i + 1]
        desviacion[i] = np.abs(ventana - ventana.mean()).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(desviacion > 0, (tipico - media) / (0.015 * desviacion), 0.0)


# ========================
# VOLATILIDAD Y RANGO
# ========================

def rango_verdadero(datos):
    """True Range: el mayor de (alto-bajo), |alto-cierre previo|, |bajo-cierre previo|."""
    alto, bajo, cierre = datos["high"], datos["low"], datos["close"]
    previo = np.concatenate(([cierre[0]], cierre[:-1]))
    return np.maximum(alto - bajo, np.maximum(np.abs(alto - previo), np.abs(bajo - previo)))


@_registrar("atr", minimo=2, maximo=100)
def atr(datos, periodo):
    """Average True Range con suavizado de Wilder."""
    tr = rango_verdadero(datos)
    n = len(tr)
    salida = np.full(n, np.nan)
    if periodo < 1 or periodo > n:
        return salida
    valor = tr[:periodo].mean()
    salida[periodo - 1] = valor
    for i in range(periodo, n):
        valor = (valor * (periodo - 1) + tr[i]) / periodo
        salida[i] = valor
    return salida


@_registrar("bollinger_sup", minimo=5, maximo=200)
def bollinger_sup(precios, periodo):
    """Banda superior de Bollinger (2 desviaciones típicas)."""
    media = sma(precios, periodo)
    return media + 2.0 * desviacion_movil(precios, periodo)


@_registrar("bollinger_inf", minimo=5, maximo=200)
def bollinger_inf(precios, periodo):
    """Banda inferior de Bollinger (2 desviaciones típicas)."""
    media = sma(precios, periodo)
    return media - 2.0 * desviacion_movil(precios, periodo)


def desviacion_movil(precios, periodo):
    """Desviación típica móvil, calculada por sumas acumuladas."""
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    if periodo < 2 or periodo > n:
        return np.full(n, np.nan)
    suma = np.concatenate(([0.0], np.cumsum(precios)))
    suma2 = np.concatenate(([0.0], np.cumsum(precios ** 2)))
    salida = np.full(n, np.nan)
    media = (suma[periodo:] - suma[:-periodo]) / periodo
    medio2 = (suma2[periodo:] - suma2[:-periodo]) / periodo
    salida[periodo - 1:] = np.sqrt(np.maximum(medio2 - media ** 2, 0.0))
    return salida


# ========================
# EXTREMOS
# ========================

def _extremo_movil(precios, periodo, fn):
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    if periodo < 1 or periodo > n:
        return np.full(n, np.nan)
    # Vista deslizante: evita el bucle en Python y es O(n * periodo) en C.
    ventanas = np.lib.stride_tricks.sliding_window_view(precios, periodo)
    salida = np.full(n, np.nan)
    salida[periodo - 1:] = fn(ventanas, axis=1)
    return salida


@_registrar("maximo", minimo=2, maximo=200)
def maximo_movil(precios, periodo):
    """Máximo de las últimas N barras (canal de Donchian superior)."""
    return _extremo_movil(precios, periodo, np.max)


@_registrar("minimo", minimo=2, maximo=200)
def minimo_movil(precios, periodo):
    """Mínimo de las últimas N barras (canal de Donchian inferior)."""
    return _extremo_movil(precios, periodo, np.min)


# ========================
# HELPERS DE SEÑAL
# ========================

def cruza_arriba(a, b):
    """True en la barra en que a pasa de estar por debajo de b a por encima."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    previo = np.concatenate(([np.nan], a[:-1] - b[:-1]))
    actual = a - b
    return (previo <= 0) & (actual > 0)


def cruza_abajo(a, b):
    """True en la barra en que a pasa de estar por encima de b a por debajo."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    previo = np.concatenate(([np.nan], a[:-1] - b[:-1]))
    actual = a - b
    return (previo >= 0) & (actual < 0)


def calcular(nombre, datos, periodo):
    """
    Evalúa un indicador del catálogo por nombre. Los que necesitan OHLC
    completo reciben el dict; los que sólo necesitan precio, el cierre.
    """
    entrada = CATALOGO[nombre]["fn"]
    if nombre in ("atr", "estocastico", "cci"):
        return entrada(datos, periodo)
    return entrada(datos["close"], periodo)


class Contexto:
    """
    Envuelve una serie y memoiza los indicadores ya calculados.

    Un barrido de parámetros o una población genética piden la misma SMA(20)
    cientos de veces; calcularla una sola vez cambia por completo el tiempo
    total. Hay que crear un Contexto por serie: al recortar los datos para
    walk-forward, hay que crear uno nuevo.
    """

    def __init__(self, datos):
        self.datos = datos
        self._campos = datos.como_dict()
        self._cache = {}

    def ind(self, nombre, periodo):
        clave = (nombre, int(periodo))
        valor = self._cache.get(clave)
        if valor is None:
            valor = calcular(nombre, self._campos, int(periodo))
            self._cache[clave] = valor
        return valor

    @property
    def close(self):
        return self._campos["close"]

    @property
    def high(self):
        return self._campos["high"]

    @property
    def low(self):
        return self._campos["low"]

    def __len__(self):
        return len(self.datos)
