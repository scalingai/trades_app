"""
Flujo de órdenes y probabilidad direccional a escala de segundos.

Las velas de Binance traen dos columnas que el OHLCV no tiene: el número de
operaciones y el volumen que entró comprando a mercado. Con eso se calcula el
**desequilibrio de flujo**:

    desequilibrio = (2 · volumen_comprador − volumen) / volumen

Vale +1 si todo el volumen entró comprando agresivo, −1 si todo entró
vendiendo, 0 si estuvo repartido. Es la medida más directa de presión
compradora que se puede obtener sin pagar por datos de libro de órdenes, y a
escala de 10 segundos dice cosas que ningún indicador de precio puede decir,
porque el precio a esa escala casi no se mueve.

Un aviso que conviene tener presente antes de usar esto:

    En 10 segundos el movimiento mediano de BTC es del 0,0000 % y el percentil
    95 es del 0,018 %. El coste de ida y vuelta es del 0,12 %. Ni las ventanas
    más movidas cubren una fracción del coste.

Es decir: **esto no sirve para entrar**. Ninguna predicción a 10 segundos, por
buena que sea, paga la comisión. Sirve para dos cosas donde no se paga un
round trip extra:

  1. Decidir CUÁNDO salir de una posición que ya está abierta y que se iba a
     cerrar igual. Ahí la precisión de la salida es gratis.
  2. Decidir EN QUÉ SESIONES operar, midiendo dónde hay predictibilidad real.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Ventanas en número de velas. Con velas de 10 s: 6 = 1 min, 30 = 5 min,
# 180 = 30 min, 360 = 1 hora.
VENTANAS = (6, 30, 180, 360)


def _ema(serie, periodo):
    return serie.ewm(span=periodo, adjust=False, min_periods=periodo).mean()


def _seguro(numerador, denominador, defecto=0.0):
    """División que no explota cuando el denominador es cero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        salida = numerador / denominador
    return salida.replace([np.inf, -np.inf], np.nan).fillna(defecto)


def construir(df):
    """
    Calcula las características a partir de un DataFrame con flujo.

    Todas usan sólo información hasta la vela actual incluida. La comprobación
    está en tests/test_flujo.py: alterar el futuro no puede mover ningún valor
    del pasado.
    """
    faltan = {"taker_buy", "trades", "volume"} - set(df.columns)
    if faltan:
        raise ValueError(
            f"Faltan columnas de flujo: {sorted(faltan)}. Descarga con --flujo.")

    x = pd.DataFrame(index=df.index)
    cierre = df["close"]

    # --- desequilibrio de flujo ---
    # El volumen vendedor agresivo es el resto: volume - taker_buy.
    desequilibrio = _seguro(2 * df["taker_buy"] - df["volume"], df["volume"])
    x["dsq"] = desequilibrio
    for v in VENTANAS:
        x[f"dsq_ema{v}"] = _ema(desequilibrio, v)
        # Desequilibrio acumulado ponderado por volumen: distingue "muchas
        # velas poco compradoras" de "una vela muy compradora".
        neto = (2 * df["taker_buy"] - df["volume"]).rolling(v).sum()
        x[f"dsq_vol{v}"] = _seguro(neto, df["volume"].rolling(v).sum())

    # --- actividad ---
    x["vol_rel"] = _seguro(df["volume"], _ema(df["volume"], 360), 1.0)
    x["trades_rel"] = _seguro(df["trades"], _ema(df["trades"], 360), 1.0)
    # Tamaño medio de operación: sube cuando entra dinero grande.
    tamano = _seguro(df["volume"], df["trades"])
    x["tamano_rel"] = _seguro(tamano, _ema(tamano, 360), 1.0)

    # --- precio ---
    retorno = cierre.pct_change().fillna(0.0)
    x["ret1"] = retorno
    for v in (6, 30, 180):
        x[f"ret{v}"] = cierre.pct_change(v).fillna(0.0)
    x["vola"] = retorno.rolling(180).std().fillna(0.0)
    # Dónde cierra la vela dentro de su propio rango: 1 = en máximos.
    x["cierre_en_rango"] = _seguro(cierre - df["low"], df["high"] - df["low"], 0.5)
    x["rango_rel"] = _seguro(_seguro(df["high"] - df["low"], cierre),
                             _ema(_seguro(df["high"] - df["low"], cierre), 360), 1.0)

    # --- momento del día, en forma cíclica para que las 23:59 y las 00:00
    # queden juntas y no en extremos opuestos ---
    horas = df.index.hour + df.index.minute / 60
    x["hora_sin"] = np.sin(2 * np.pi * horas / 24)
    x["hora_cos"] = np.cos(2 * np.pi * horas / 24)

    return x.replace([np.inf, -np.inf], np.nan)


def objetivo(df, horizonte=1, umbral=0.0):
    """
    Etiqueta a predecir: si el precio sube en las próximas `horizonte` velas.

    Con umbral > 0 sólo cuentan los movimientos que lo superan, y las velas
    que se quedan en medio salen como NaN y no entrenan. Sirve para no pedirle
    al modelo que acierte el ruido del spread.
    """
    futuro = df["close"].shift(-horizonte) / df["close"] - 1
    if umbral <= 0:
        y = (futuro > 0).astype(float)
    else:
        y = pd.Series(np.nan, index=df.index)
        y[futuro > umbral] = 1.0
        y[futuro < -umbral] = 0.0
    y[futuro.isna()] = np.nan
    return y, futuro


@dataclass
class Modelo:
    """Regresión logística entrenada sobre el tramo in-sample."""
    columnas: list
    media: np.ndarray
    escala: np.ndarray
    coeficientes: np.ndarray
    intercepto: float
    horizonte: int = 1
    umbral: float = 0.0
    metricas: dict = field(default_factory=dict)

    def probabilidad(self, x):
        """P(sube) para cada fila. Devuelve 0,5 donde falten datos."""
        m = x[self.columnas].to_numpy(dtype=float)
        validas = np.isfinite(m).all(axis=1)
        z = np.full(len(m), 0.0)
        if validas.any():
            normal = (m[validas] - self.media) / self.escala
            z[validas] = normal @ self.coeficientes + self.intercepto
        p = 1 / (1 + np.exp(-z))
        p[~validas] = 0.5
        return p


def entrenar(x, y, horizonte=1, umbral=0.0, regularizacion=1.0):
    """
    Ajusta una regresión logística. Se usa un modelo lineal a propósito: con
    millones de filas y decenas de características, un modelo flexible
    encuentra estructura donde no la hay, y aquí lo que importa es saber si
    existe señal, no exprimirla.
    """
    from sklearn.linear_model import LogisticRegression

    columnas = list(x.columns)
    m = x.to_numpy(dtype=float)
    etiquetas = y.to_numpy(dtype=float)
    ok = np.isfinite(m).all(axis=1) & np.isfinite(etiquetas)
    if ok.sum() < 1000:
        raise ValueError(f"Sólo {ok.sum()} filas utilizables; hacen falta más datos.")

    m, etiquetas = m[ok], etiquetas[ok]
    media, escala = m.mean(axis=0), m.std(axis=0)
    escala[escala == 0] = 1.0
    normal = (m - media) / escala

    modelo = LogisticRegression(C=regularizacion, max_iter=1000, solver="lbfgs")
    modelo.fit(normal, etiquetas)

    return Modelo(columnas=columnas, media=media, escala=escala,
                  coeficientes=modelo.coef_[0], intercepto=float(modelo.intercept_[0]),
                  horizonte=horizonte, umbral=umbral)


def auc(probabilidades, etiquetas):
    """
    Área bajo la curva ROC. 0,5 = no distingue nada; por encima, algo distingue.

    Se calcula con rangos en vez de con sklearn para poder aplicarla por
    sesiones sin arrastrar dependencias en cada corte.
    """
    ok = np.isfinite(probabilidades) & np.isfinite(etiquetas)
    p, e = probabilidades[ok], etiquetas[ok]
    positivos, negativos = (e == 1).sum(), (e == 0).sum()
    if positivos == 0 or negativos == 0:
        return float("nan")
    rangos = pd.Series(p).rank().to_numpy()
    return float((rangos[e == 1].sum() - positivos * (positivos + 1) / 2)
                 / (positivos * negativos))


def evaluar(modelo, x, y, indice):
    """Rendimiento global y desglosado por hora UTC."""
    p = modelo.probabilidad(x)
    e = y.to_numpy(dtype=float)

    global_auc = auc(p, e)
    ok = np.isfinite(p) & np.isfinite(e)
    acierto = float(((p > 0.5) == (e == 1))[ok].mean()) if ok.any() else float("nan")

    filas = []
    horas = indice.hour
    for h in range(24):
        sel = horas == h
        if sel.sum() < 500:
            continue
        filas.append({
            "hora": h,
            "n": int((sel & ok).sum()),
            "auc": auc(p[sel], e[sel]),
            "acierto": float(((p > 0.5) == (e == 1))[sel & ok].mean()),
        })
    return {"auc": global_auc, "acierto": acierto,
            "por_hora": pd.DataFrame(filas)}


def importancia(modelo):
    """Coeficientes ordenados por magnitud, sobre características estandarizadas."""
    return (pd.DataFrame({"caracteristica": modelo.columnas,
                          "coeficiente": modelo.coeficientes})
            .assign(magnitud=lambda d: d["coeficiente"].abs())
            .sort_values("magnitud", ascending=False)
            .drop(columns="magnitud")
            .reset_index(drop=True))
