"""
Estrategias clásicas parametrizables.

Cada una declara su espacio de parámetros, que es lo que recorre el
optimizador. Todas aceptan además stop y objetivo en múltiplos de ATR, para
que la gestión de la posición se pueda optimizar junto con las reglas de
entrada.

Sirven de referencia y de punto de partida; el generador genético
(generador.py) construye estrategias nuevas sin partir de ninguna de éstas.
"""

from dataclasses import dataclass, field

import numpy as np

from . import indicadores as ind
from .motor import Senales

REGISTRO = {}


@dataclass
class Estrategia:
    nombre: str
    fn: callable
    espacio: dict = field(default_factory=dict)
    descripcion: str = ""

    def senales(self, contexto, **params):
        return self.fn(contexto, **params)


def _registrar(nombre, espacio, descripcion=""):
    def envoltura(fn):
        REGISTRO[nombre] = Estrategia(nombre, fn, espacio, descripcion)
        return fn
    return envoltura


def _distancias(contexto, stop_atr, objetivo_atr, periodo_atr=14):
    """Convierte múltiplos de ATR en distancias de precio absolutas."""
    if not stop_atr and not objetivo_atr:
        return None, None
    atr = contexto.ind("atr", periodo_atr)
    dist_stop = atr * stop_atr if stop_atr else None
    dist_obj = atr * objetivo_atr if objetivo_atr else None
    return dist_stop, dist_obj


# Parámetros de gestión comunes a todas las estrategias.
GESTION = {
    "stop_atr": [0, 1.5, 2.0, 3.0, 4.0],
    "objetivo_atr": [0, 2.0, 3.0, 4.0, 6.0],
}


# ========================
# SEGUIMIENTO DE TENDENCIA
# ========================

@_registrar("cruce_medias", {
    "rapida": [5, 10, 15, 20, 30, 40, 50],
    "lenta": [30, 50, 80, 100, 150, 200],
    "tipo": ["sma", "ema"],
    **GESTION,
}, "Cruce de medias móviles: largo cuando la rápida cruza al alza la lenta.")
def cruce_medias(contexto, rapida=20, lenta=100, tipo="sma", stop_atr=0, objetivo_atr=0):
    if rapida >= lenta:
        return None                      # combinación sin sentido: el optimizador la descarta
    r = contexto.ind(tipo, rapida)
    l = contexto.ind(tipo, lenta)
    arriba = ind.cruza_arriba(r, l)
    abajo = ind.cruza_abajo(r, l)
    dist_stop, dist_obj = _distancias(contexto, stop_atr, objetivo_atr)
    return Senales(entrada_larga=arriba, salida_larga=abajo,
                   entrada_corta=abajo, salida_corta=arriba,
                   dist_stop=dist_stop, dist_objetivo=dist_obj)


@_registrar("ruptura_canal", {
    "entrada": [10, 20, 30, 55, 80, 120],
    "salida": [5, 10, 20, 30],
    **GESTION,
}, "Ruptura de canal de Donchian, al estilo de las tortugas.")
def ruptura_canal(contexto, entrada=20, salida=10, stop_atr=0, objetivo_atr=0):
    if salida >= entrada:
        return None
    # El máximo se desplaza una barra: romper el máximo previo, no el que
    # incluye la barra actual (eso sería mirar el futuro dentro de la propia barra).
    maximo = np.concatenate(([np.nan], ind.maximo_movil(contexto.high, entrada)[:-1]))
    minimo = np.concatenate(([np.nan], ind.minimo_movil(contexto.low, entrada)[:-1]))
    max_sal = np.concatenate(([np.nan], ind.maximo_movil(contexto.high, salida)[:-1]))
    min_sal = np.concatenate(([np.nan], ind.minimo_movil(contexto.low, salida)[:-1]))
    cierre = contexto.close
    dist_stop, dist_obj = _distancias(contexto, stop_atr, objetivo_atr)
    return Senales(entrada_larga=cierre > maximo, salida_larga=cierre < min_sal,
                   entrada_corta=cierre < minimo, salida_corta=cierre > max_sal,
                   dist_stop=dist_stop, dist_objetivo=dist_obj)


@_registrar("momentum", {
    "periodo": [10, 20, 30, 50, 80, 120],
    "umbral": [0, 2, 5, 10],
    **GESTION,
}, "Momentum: largo si la variación de N barras supera un umbral.")
def momentum(contexto, periodo=30, umbral=2, stop_atr=0, objetivo_atr=0):
    variacion = contexto.ind("roc", periodo)
    dist_stop, dist_obj = _distancias(contexto, stop_atr, objetivo_atr)
    return Senales(entrada_larga=variacion > umbral, salida_larga=variacion < 0,
                   entrada_corta=variacion < -umbral, salida_corta=variacion > 0,
                   dist_stop=dist_stop, dist_objetivo=dist_obj)


# ========================
# REVERSIÓN A LA MEDIA
# ========================

@_registrar("rsi_reversion", {
    "periodo": [7, 14, 21, 30],
    "sobreventa": [20, 25, 30, 35],
    "sobrecompra": [65, 70, 75, 80],
    **GESTION,
}, "Reversión con RSI: compra en sobreventa, vende en sobrecompra.")
def rsi_reversion(contexto, periodo=14, sobreventa=30, sobrecompra=70,
                  stop_atr=0, objetivo_atr=0):
    if sobreventa >= sobrecompra:
        return None
    r = contexto.ind("rsi", periodo)
    dist_stop, dist_obj = _distancias(contexto, stop_atr, objetivo_atr)
    return Senales(entrada_larga=ind.cruza_arriba(r, np.full(len(r), sobreventa)),
                   salida_larga=r > sobrecompra,
                   entrada_corta=ind.cruza_abajo(r, np.full(len(r), sobrecompra)),
                   salida_corta=r < sobreventa,
                   dist_stop=dist_stop, dist_objetivo=dist_obj)


@_registrar("bollinger_reversion", {
    "periodo": [10, 20, 30, 50],
    **GESTION,
}, "Reversión con bandas de Bollinger: compra al perforar la banda inferior.")
def bollinger_reversion(contexto, periodo=20, stop_atr=0, objetivo_atr=0):
    cierre = contexto.close
    inferior = contexto.ind("bollinger_inf", periodo)
    superior = contexto.ind("bollinger_sup", periodo)
    media = contexto.ind("sma", periodo)
    dist_stop, dist_obj = _distancias(contexto, stop_atr, objetivo_atr)
    return Senales(entrada_larga=ind.cruza_arriba(cierre, inferior),
                   salida_larga=cierre > media,
                   entrada_corta=ind.cruza_abajo(cierre, superior),
                   salida_corta=cierre < media,
                   dist_stop=dist_stop, dist_objetivo=dist_obj)


def obtener(nombre):
    if nombre not in REGISTRO:
        disponibles = ", ".join(sorted(REGISTRO))
        raise KeyError(f"Estrategia desconocida: {nombre!r}. Disponibles: {disponibles}")
    return REGISTRO[nombre]
