"""
Motor de backtesting.

Convenciones (importan, porque son la diferencia entre un backtest honesto y
uno que se engaña a sí mismo):

- Una señal se calcula con el cierre de la barra t y se ejecuta a la apertura
  de t+1. Nunca se opera con información de la propia barra que la generó.
- El stop y el objetivo se comprueban dentro de la barra (con su máximo y su
  mínimo), desde la barra de entrada incluida.
- Si en la misma barra se tocan stop y objetivo, se asume que saltó el stop.
  No se sabe cuál se tocó antes, así que se elige el peor caso.
- Una salida por señal se ejecuta a la apertura de la barra siguiente; si en
  esa misma barra también salta el stop, manda la señal, porque la apertura
  ocurre antes que el recorrido de la barra.
- Comisión y slippage se cobran en cada lado de la operación.

En vez de recorrer barra a barra (inviable con 900.000 velas y miles de
estrategias), el motor itera sobre operaciones y busca cada salida en bloques
crecientes, de forma que las operaciones cortas se resuelven en pocas
comparaciones.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Motivos de salida
SENAL, STOP, OBJETIVO, MAX_BARRAS, FIN_DATOS = 0, 1, 2, 3, 4
NOMBRES_MOTIVO = {
    SENAL: "señal", STOP: "stop", OBJETIVO: "objetivo",
    MAX_BARRAS: "max_barras", FIN_DATOS: "fin_datos",
}

LARGO, CORTO = 1, -1


@dataclass
class Datos:
    """Serie OHLCV en arrays de numpy, lista para evaluar muchas veces."""
    fechas: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    intervalo: str = "1h"

    def __len__(self):
        return len(self.close)

    def como_dict(self):
        return {"open": self.open, "high": self.high, "low": self.low,
                "close": self.close, "volume": self.volume}

    def tramo(self, desde, hasta):
        """Recorta por posición, conservando el intervalo."""
        return Datos(
            self.fechas[desde:hasta], self.open[desde:hasta], self.high[desde:hasta],
            self.low[desde:hasta], self.close[desde:hasta], self.volume[desde:hasta],
            self.intervalo,
        )


def desde_dataframe(df, intervalo="1h"):
    """Construye un Datos a partir del DataFrame que devuelve cargar_datos()."""
    return Datos(
        fechas=df.index.to_numpy(),
        open=df["open"].to_numpy(dtype=float),
        high=df["high"].to_numpy(dtype=float),
        low=df["low"].to_numpy(dtype=float),
        close=df["close"].to_numpy(dtype=float),
        volume=df["volume"].to_numpy(dtype=float),
        intervalo=intervalo,
    )


@dataclass
class Config:
    """Costes y reglas de gestión. Los valores por defecto son taker de Binance."""
    comision: float = 0.0004        # 0,04 % por lado
    slippage: float = 0.0002        # 0,02 % por lado
    capital: float = 10_000.0
    max_barras: int | None = None   # cierre forzoso tras N barras
    permitir_cortos: bool = True

    @property
    def coste(self):
        return self.comision + self.slippage


@dataclass
class Senales:
    """
    Señales de una estrategia. Los arrays son booleanos y del largo de la serie.
    dist_stop y dist_objetivo son distancias de precio absolutas medidas desde
    el precio de entrada (permite stops en % o en múltiplos de ATR sin que el
    motor tenga que saber cuál se usó).
    """
    entrada_larga: np.ndarray
    salida_larga: np.ndarray | None = None
    entrada_corta: np.ndarray | None = None
    salida_corta: np.ndarray | None = None
    dist_stop: np.ndarray | None = None
    dist_objetivo: np.ndarray | None = None


@dataclass
class Resultado:
    """Operaciones y curva de capital. Los arrays van en paralelo, una fila por operación."""
    entrada_idx: np.ndarray
    salida_idx: np.ndarray
    direccion: np.ndarray
    precio_entrada: np.ndarray
    precio_salida: np.ndarray
    retorno: np.ndarray          # neto de costes, por operación
    motivo: np.ndarray
    equity: np.ndarray           # curva de capital barra a barra
    datos: Datos = field(repr=False, default=None)

    @property
    def n_operaciones(self):
        return len(self.retorno)

    def operaciones_df(self):
        """Las operaciones como DataFrame. Sólo para informes: construirlo es caro."""
        if self.n_operaciones == 0:
            return pd.DataFrame(columns=[
                "entrada", "salida", "direccion", "precio_entrada",
                "precio_salida", "retorno", "barras", "motivo"])
        return pd.DataFrame({
            "entrada": self.datos.fechas[self.entrada_idx],
            "salida": self.datos.fechas[self.salida_idx],
            "direccion": np.where(self.direccion == LARGO, "largo", "corto"),
            "precio_entrada": self.precio_entrada,
            "precio_salida": self.precio_salida,
            "retorno": self.retorno,
            "barras": self.salida_idx - self.entrada_idx,
            "motivo": [NOMBRES_MOTIVO[m] for m in self.motivo],
        })


def _primer_indice(mascara, desde, hasta):
    """
    Primer True de `mascara` en [desde, hasta). Busca en bloques que crecen
    para no recorrer toda la serie cuando la salida está a pocas barras.
    """
    pos = desde
    tamano = 64
    while pos < hasta:
        tope = min(pos + tamano, hasta)
        trozo = mascara[pos:tope]
        if trozo.any():
            return pos + int(np.argmax(trozo))
        pos = tope
        tamano = min(tamano * 4, 262_144)
    return -1


def _primer_umbral(serie, umbral, desde, hasta, por_debajo):
    """Igual que _primer_indice pero comparando contra un umbral escalar."""
    pos = desde
    tamano = 64
    while pos < hasta:
        tope = min(pos + tamano, hasta)
        trozo = serie[pos:tope]
        golpe = trozo <= umbral if por_debajo else trozo >= umbral
        if golpe.any():
            return pos + int(np.argmax(golpe))
        pos = tope
        tamano = min(tamano * 4, 262_144)
    return -1


def ejecutar(datos, senales, config=None):
    """Recorre las señales y devuelve las operaciones resultantes con su curva de capital."""
    config = config or Config()
    n = len(datos)
    apertura, alto, bajo, cierre = datos.open, datos.high, datos.low, datos.close

    entrada_larga = np.asarray(senales.entrada_larga, dtype=bool)
    entrada_corta = (np.asarray(senales.entrada_corta, dtype=bool)
                     if senales.entrada_corta is not None and config.permitir_cortos
                     else np.zeros(n, dtype=bool))
    salida_larga = (np.asarray(senales.salida_larga, dtype=bool)
                    if senales.salida_larga is not None else np.zeros(n, dtype=bool))
    salida_corta = (np.asarray(senales.salida_corta, dtype=bool)
                    if senales.salida_corta is not None else np.zeros(n, dtype=bool))

    coste = config.coste
    max_barras = config.max_barras

    ent_idx, sal_idx, dirs, p_ent, p_sal, rets, motivos = [], [], [], [], [], [], []

    capital = config.capital
    equity = np.full(n, capital, dtype=float)
    ultimo_cierre_equity = 0
    barra = 0

    while barra < n - 1:
        # La señal de la barra `barra` se ejecuta en la apertura de `barra + 1`.
        idx_l = _primer_indice(entrada_larga, barra, n - 1)
        idx_c = _primer_indice(entrada_corta, barra, n - 1)

        if idx_l < 0 and idx_c < 0:
            break
        if idx_c < 0 or (0 <= idx_l <= idx_c):
            senal_barra, direccion = idx_l, LARGO
            salida_propia = salida_larga
        else:
            senal_barra, direccion = idx_c, CORTO
            salida_propia = salida_corta

        e = senal_barra + 1                      # barra de ejecución de la entrada
        precio_entrada = apertura[e]
        if not np.isfinite(precio_entrada) or precio_entrada <= 0:
            barra = e
            continue

        # Stop y objetivo se fijan con la distancia vigente en la barra de la señal.
        stop_precio = objetivo_precio = None
        if senales.dist_stop is not None:
            d = senales.dist_stop[senal_barra]
            if np.isfinite(d) and d > 0:
                stop_precio = precio_entrada - d if direccion == LARGO else precio_entrada + d
        if senales.dist_objetivo is not None:
            d = senales.dist_objetivo[senal_barra]
            if np.isfinite(d) and d > 0:
                objetivo_precio = precio_entrada + d if direccion == LARGO else precio_entrada - d

        # Búsqueda de la salida más temprana entre las cuatro posibles.
        barra_stop = barra_obj = barra_senal = barra_tope = n
        if stop_precio is not None:
            serie, por_debajo = (bajo, True) if direccion == LARGO else (alto, False)
            hallado = _primer_umbral(serie, stop_precio, e, n, por_debajo)
            if hallado >= 0:
                barra_stop = hallado
        if objetivo_precio is not None:
            serie, por_debajo = (alto, False) if direccion == LARGO else (bajo, True)
            hallado = _primer_umbral(serie, objetivo_precio, e, n, por_debajo)
            if hallado >= 0:
                barra_obj = hallado
        hallado = _primer_indice(salida_propia, e, n - 1)
        if hallado >= 0:
            barra_senal = hallado + 1            # se ejecuta en la apertura siguiente
        if max_barras:
            barra_tope = min(e + max_barras, n - 1)

        # Empate a la misma barra: primero la señal (abre la barra), luego el
        # stop y por último el objetivo (peor caso).
        candidatos = [(barra_senal, SENAL, 0), (barra_stop, STOP, 1),
                      (barra_obj, OBJETIVO, 2), (barra_tope, MAX_BARRAS, 3)]
        barra_salida, motivo, _ = min(candidatos, key=lambda c: (c[0], c[2]))

        if barra_salida >= n:                    # se acabaron los datos con la posición abierta
            barra_salida, motivo = n - 1, FIN_DATOS

        if motivo == STOP:
            precio_salida = stop_precio
        elif motivo == OBJETIVO:
            precio_salida = objetivo_precio
        elif motivo == FIN_DATOS:
            precio_salida = cierre[barra_salida]
        else:
            precio_salida = apertura[barra_salida]

        # Un hueco de apertura puede saltarse el stop: se ejecuta al precio real.
        if motivo == STOP:
            if direccion == LARGO and apertura[barra_salida] < stop_precio:
                precio_salida = apertura[barra_salida]
            elif direccion == CORTO and apertura[barra_salida] > stop_precio:
                precio_salida = apertura[barra_salida]

        if direccion == LARGO:
            retorno = (precio_salida * (1 - coste)) / (precio_entrada * (1 + coste)) - 1
        else:
            # En corto se vende al entrar y se recompra al salir, así que el
            # resultado se mide sobre el nominal vendido. Con esta fórmula una
            # caída del 100 % gana el 100 % y una subida del 100 % arruina la
            # posición, que es lo que pasa de verdad a apalancamiento 1x.
            retorno = (precio_entrada * (1 - coste) - precio_salida * (1 + coste)) / precio_entrada

        # Capital marcado a mercado mientras la posición está abierta, para que
        # el drawdown recoja lo que pasó dentro de la operación y no sólo al cerrar.
        equity[ultimo_cierre_equity:e] = capital
        if barra_salida > e:
            tramo = cierre[e:barra_salida]
            if direccion == LARGO:
                curva = (tramo * (1 - coste)) / (precio_entrada * (1 + coste)) - 1
            else:
                curva = (precio_entrada * (1 - coste) - tramo * (1 + coste)) / precio_entrada
            equity[e:barra_salida] = capital * (1 + curva)

        capital *= (1 + retorno)
        equity[barra_salida] = capital
        ultimo_cierre_equity = barra_salida

        ent_idx.append(e)
        sal_idx.append(barra_salida)
        dirs.append(direccion)
        p_ent.append(precio_entrada)
        p_sal.append(precio_salida)
        rets.append(retorno)
        motivos.append(motivo)

        barra = barra_salida         # no se reabre hasta la barra de cierre

    equity[ultimo_cierre_equity:] = capital

    return Resultado(
        entrada_idx=np.array(ent_idx, dtype=int),
        salida_idx=np.array(sal_idx, dtype=int),
        direccion=np.array(dirs, dtype=int),
        precio_entrada=np.array(p_ent, dtype=float),
        precio_salida=np.array(p_sal, dtype=float),
        retorno=np.array(rets, dtype=float),
        motivo=np.array(motivos, dtype=int),
        equity=equity,
        datos=datos,
    )
