"""
Backtest de posición continua: el tamaño es proporcional a la convicción.

El motor de motor.py abre y cierra operaciones enteras. Aquí la posición es un
número entre −1 y +1 que se ajusta en cada vela, así que se puede ir agregando
cuando la convicción sube, recortando cuando baja y dando la vuelta cuando
cambia de signo, que es como funciona una señal continua.

El cambio importante no es de implementación sino de estadística. Un umbral
binario "operar sólo con unanimidad" usa el 1 % de las velas, y sobre ventanas
que se solapan eso son unas pocas decenas de episodios independientes: no
alcanza para creerse nada. Dimensionar la posición de forma proporcional usa
TODAS las velas, así que la misma relación se mide sobre una muestra miles de
veces mayor. Menos espectacular por operación, muchísimo más fiable.

El coste se cobra sobre el cambio de posición, no por operación:

    coste(t) = |posición(t) − posición(t−1)| · coste_por_lado

Eso hace que la rotación sea el enemigo principal. Una señal que se mueve mucho
paga costes continuamente aunque acierte, y por eso el informe destaca la
rotación anualizada tanto como el retorno.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEGUNDOS_POR_ANIO = 365.25 * 24 * 3600


@dataclass
class ConfigPosicion:
    coste_por_lado: float = 0.0006     # comisión + slippage
    apalancamiento: float = 1.0        # posición máxima en múltiplos del capital
    zona_muerta: float = 0.0           # convicción por debajo de la cual no se opera
    suavizado: int = 0                 # velas de EMA sobre la posición objetivo
    capital: float = 10_000.0


@dataclass
class ResultadoPosicion:
    equity: pd.Series
    posicion: pd.Series
    retorno_bruto: pd.Series
    costes: pd.Series
    intervalo_seg: int

    @property
    def rotacion_anual(self):
        """Cuántas veces al año se da la vuelta a la cartera entera."""
        cambios = self.posicion.diff().abs().sum()
        anios = len(self.posicion) * self.intervalo_seg / SEGUNDOS_POR_ANIO
        return float(cambios / anios) if anios > 0 else 0.0

    def metricas(self):
        neto = self.retorno_bruto - self.costes
        anios = max(len(neto) * self.intervalo_seg / SEGUNDOS_POR_ANIO, 1e-9)
        por_anio = SEGUNDOS_POR_ANIO / self.intervalo_seg

        final = float(self.equity.iloc[-1])
        total = final / self.equity.iloc[0] - 1
        desv = neto.std()
        maximos = self.equity.cummax()
        return {
            "retorno_total": float(total),
            "cagr": float((1 + total) ** (1 / anios) - 1) if total > -1 else -1.0,
            "sharpe": float(neto.mean() / desv * np.sqrt(por_anio)) if desv > 0 else 0.0,
            "max_drawdown": float(((maximos - self.equity) / maximos).max()),
            "bruto_anual": float(self.retorno_bruto.mean() * por_anio),
            "coste_anual": float(self.costes.mean() * por_anio),
            "rotacion_anual": self.rotacion_anual,
            "exposicion_media": float(self.posicion.abs().mean()),
            "anios": float(anios),
        }


def ejecutar(precios, conviccion, config=None, intervalo_seg=10):
    """
    Simula una posición proporcional a la convicción.

    `conviccion` va entre −1 y +1: +1 es máxima confianza alcista. La posición
    del período t se decide con la convicción de t−1, porque la de t se calcula
    con el cierre de t y ejecutar a ese mismo cierre sería operar con
    información que todavía no está disponible.
    """
    config = config or ConfigPosicion()

    objetivo = conviccion.clip(-1, 1) * config.apalancamiento
    if config.zona_muerta > 0:
        # Fuera de la zona muerta se reescala para que no haya un salto brusco
        # justo en el umbral.
        signo = np.sign(objetivo)
        magnitud = (objetivo.abs() - config.zona_muerta).clip(lower=0)
        objetivo = signo * magnitud / max(1 - config.zona_muerta, 1e-9)
    if config.suavizado > 1:
        objetivo = objetivo.ewm(span=config.suavizado, adjust=False).mean()

    # Aquí está la única línea que separa un backtest honesto de uno inventado.
    posicion = objetivo.shift(1).fillna(0.0)

    retorno = precios.pct_change().fillna(0.0)
    bruto = posicion * retorno
    costes = posicion.diff().abs().fillna(posicion.abs()) * config.coste_por_lado

    equity = config.capital * (1 + bruto - costes).cumprod()
    return ResultadoPosicion(equity=equity, posicion=posicion, retorno_bruto=bruto,
                             costes=costes, intervalo_seg=intervalo_seg)


def conviccion_de_ensemble(probabilidades, pesos=None):
    """
    Convierte un conjunto de probabilidades en una convicción entre −1 y +1.

    Cada modelo aporta 2·(p − 0,5), que vale 0 cuando no opina y ±1 cuando está
    seguro. El promedio ponderado conserva ese rango, así que la convicción del
    conjunto no puede superar a la del modelo más convencido.
    """
    p = pd.DataFrame(probabilidades)
    señales = 2 * (p - 0.5)
    if pesos is None:
        return señales.mean(axis=1)
    w = pd.Series(pesos, dtype=float)
    w = w / w.abs().sum()
    return (señales[w.index] * w).sum(axis=1)


def filtrar_sesion(conviccion, horas):
    """Anula la convicción fuera de las horas UTC indicadas."""
    if not horas:
        return conviccion
    dentro = conviccion.index.hour.isin(list(horas))
    return conviccion.where(dentro, 0.0)


def formatear(resultado, etiqueta=""):
    m = resultado.metricas()
    cabecera = f"  {etiqueta}\n" if etiqueta else ""
    veredicto = ""
    if m["bruto_anual"] > 0 and m["coste_anual"] > m["bruto_anual"]:
        veredicto = ("\n    ⚠️  Los costes se comen todo el bruto: la señal acierta pero "
                     "rota demasiado.")
    return (
        f"{cabecera}"
        f"    retorno total {m['retorno_total']:>9.1%}   CAGR {m['cagr']:>8.1%}\n"
        f"    Sharpe        {m['sharpe']:>9.2f}   max DD {m['max_drawdown']:>6.1%}\n"
        f"    bruto anual   {m['bruto_anual']:>9.1%}   costes anuales {m['coste_anual']:>7.1%}\n"
        f"    rotación      {m['rotacion_anual']:>9.0f}x/año   exposición media "
        f"{m['exposicion_media']:>5.1%}"
        f"{veredicto}"
    )
