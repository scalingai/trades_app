"""
Descubrimiento de patrones repetibles, no de estrategias rentables.

La diferencia importa. Buscar rentabilidad sobre un histórico siempre encuentra
algo: con suficientes cruces de parámetros aparece una combinación que habría
ganado dinero, y casi siempre es ruido. Buscar repetibilidad es otra pregunta:
¿este efecto aparece una y otra vez en trozos del histórico que no comparten
nada entre sí?

Por eso la métrica principal de este módulo no es el retorno de la celda sino
la **consistencia**: en cuántos períodos independientes el efecto tiene el
mismo signo. Un patrón que sale +2 % en un mes y plano en once no es un patrón.
Uno que sale positivo en once de doce meses, aunque sea con efectos pequeños,
es estructura.

Y como se cruzan miles de celdas, el módulo calcula además cuántas superarían
el listón sólo por azar. Sin ese número de referencia, una lista de "patrones
significativos" no dice nada: con 2.000 celdas y un corte al 5 %, cien salen
significativas aunque los datos sean ruido puro.

Todas las dimensiones son causales: las que miran al pasado usan ventanas
móviles y las de calendario no miran nada.
"""

from dataclasses import dataclass, field
from math import comb

import numpy as np
import pandas as pd

# Ventana para clasificar régimen. Con velas de 10 s, 8.640 son 24 horas.
VENTANA_REGIMEN = 8640


def _cuantil_movil(serie, ventana, cortes):
    """
    Clasifica cada valor en tramos según su percentil dentro de la ventana
    reciente. Causal: sólo mira hacia atrás, así que un valor no sabe si más
    tarde será alto o bajo.
    """
    rango = serie.rolling(ventana, min_periods=ventana // 4).rank(pct=True)
    return pd.cut(rango, bins=[0] + list(cortes) + [1.0], labels=False,
                  include_lowest=True)


def dimensiones(df, ventana=VENTANA_REGIMEN):
    """
    Construye las dimensiones por las que se pueden cruzar patrones.

    Calendario: hora UTC y día de la semana, que es donde vive el sesgo de
    sesión. Régimen: liquidez, actividad, tamaño de orden, volatilidad, rango y
    flujo, todos como tramos relativos a las últimas 24 horas, para que
    "mucho volumen" signifique lo mismo en 2022 que en 2026.
    """
    d = pd.DataFrame(index=df.index)
    d["hora"] = df.index.hour
    d["dia_semana"] = df.index.dayofweek
    # Fin de semana: la liquidez institucional desaparece y el mercado cambia.
    d["finde"] = (df.index.dayofweek >= 5).astype(int)

    tercios = (1 / 3, 2 / 3)
    d["liquidez"] = _cuantil_movil(df["volume"], ventana, tercios)
    d["actividad"] = _cuantil_movil(df["trades"], ventana, tercios)

    tamano = df["volume"] / df["trades"].replace(0, np.nan)
    d["tamano_orden"] = _cuantil_movil(tamano.fillna(0), ventana, tercios)

    retorno = df["close"].pct_change().fillna(0.0)
    d["volatilidad"] = _cuantil_movil(retorno.rolling(180).std().fillna(0), ventana, tercios)
    d["rango"] = _cuantil_movil(((df["high"] - df["low"]) / df["close"]).fillna(0),
                                ventana, tercios)

    # Desequilibrio de flujo suavizado a 30 minutos.
    with np.errstate(divide="ignore", invalid="ignore"):
        dsq = ((2 * df["taker_buy"] - df["volume"]) / df["volume"]).replace(
            [np.inf, -np.inf], np.nan).fillna(0.0)
    d["flujo"] = _cuantil_movil(dsq.ewm(span=180, adjust=False).mean(), ventana, tercios)

    # Tendencia: por encima o por debajo de la media de las últimas 24 horas.
    d["tendencia"] = (df["close"] > df["close"].rolling(ventana).mean()).astype(float)
    d.loc[df["close"].rolling(ventana).mean().isna(), "tendencia"] = np.nan

    return d


@dataclass
class Celda:
    """Un patrón: una combinación de valores de dimensiones y su efecto."""
    claves: dict
    n: int
    episodios: float
    efecto: float                  # retorno medio futuro
    periodos_positivos: int
    periodos_total: int
    consistencia: float = field(init=False)

    def __post_init__(self):
        self.consistencia = (self.periodos_positivos / self.periodos_total
                             if self.periodos_total else 0.0)

    @property
    def acuerdo(self):
        """Fracción de períodos que coinciden con el signo global del efecto."""
        return self.consistencia if self.efecto >= 0 else 1 - self.consistencia

    @property
    def p_valor(self):
        """
        Probabilidad de ver un acuerdo así de alto lanzando una moneda.

        Un umbral fijo de acuerdo no sirve, porque lo exigente que es depende
        de cuántos períodos haya: coincidir en 8 de 10 es fácil, en 40 de 50 es
        casi imposible. El p-valor lo normaliza y permite comparar celdas con
        distinto número de períodos.
        """
        return _p_binomial(self.periodos_positivos, self.periodos_total)


def _p_binomial(aciertos, total):
    """P(al menos este desequilibrio) con moneda equilibrada, a dos colas."""
    if total == 0:
        return 1.0
    k = max(aciertos, total - aciertos)
    cola = sum(comb(total, i) for i in range(k, total + 1)) / 2 ** total
    return float(min(2 * cola, 1.0))


# Cómo se trocea el histórico en períodos independientes. Cuanto más largo el
# período, más independientes son entre sí, pero menos votos hay para medir
# consistencia. Con menos de 3 períodos no se puede hablar de repetibilidad.
PERIODOS = {"D": "D", "W": "W", "ME": "M", "QE": "Q", "YE": "Y"}
MINIMO_PERIODOS = 3


def _periodos(indice, por="ME"):
    """Etiqueta cada vela con el período independiente al que pertenece."""
    if por not in PERIODOS:
        raise ValueError(f"Período desconocido: {por!r}. Opciones: {', '.join(PERIODOS)}")
    # to_period descarta la zona horaria; se quita antes para no avisar de algo
    # que aquí da igual, porque todo está ya en UTC.
    limpio = indice.tz_convert("UTC").tz_localize(None) if indice.tz else indice
    return limpio.to_period(PERIODOS[por])


def cruzar(df, dims, columnas, horizonte=360, min_episodios=20, por="ME"):
    """
    Cruza las dimensiones indicadas y devuelve una celda por combinación.

    `horizonte` va en velas. El tamaño de muestra se cuenta en episodios
    independientes y no en velas, porque ventanas solapadas de una hora medidas
    cada 10 segundos no son observaciones distintas.
    """
    futuro = df["close"].shift(-horizonte) / df["close"] - 1
    base = dims[columnas].copy()
    base["_f"] = futuro
    base["_p"] = _periodos(df.index, por)
    base = base.dropna()

    celdas = []
    descartadas_por_periodos = 0
    for valores, grupo in base.groupby(columnas, observed=True):
        episodios = len(grupo) / horizonte
        if episodios < min_episodios:
            continue
        # Un efecto por período independiente; el signo de cada uno es el voto.
        por_periodo = grupo.groupby("_p", observed=True)["_f"].mean()
        if len(por_periodo) < MINIMO_PERIODOS:
            descartadas_por_periodos += 1
            continue
        claves = dict(zip(columnas, valores if isinstance(valores, tuple) else (valores,)))
        celdas.append(Celda(
            claves=claves, n=len(grupo), episodios=episodios,
            efecto=float(grupo["_f"].mean()),
            periodos_positivos=int((por_periodo > 0).sum()),
            periodos_total=int(len(por_periodo)),
        ))

    if not celdas and descartadas_por_periodos:
        abarca = (df.index[-1] - df.index[0]).days
        raise ValueError(
            f"Ninguna celda llegó a {MINIMO_PERIODOS} períodos de tipo {por!r}: la serie "
            f"abarca {abarca} días. Usa un período más corto (por=\"D\" o \"W\") o más "
            f"histórico; sin varios períodos no se puede medir repetibilidad.")
    return celdas


def tabla(celdas):
    if not celdas:
        return pd.DataFrame()
    filas = []
    for c in celdas:
        filas.append({**c.claves, "episodios": round(c.episodios), "efecto": c.efecto,
                      "periodos": c.periodos_total, "a_favor": (c.periodos_positivos
                                                                if c.efecto >= 0
                                                                else c.periodos_total - c.periodos_positivos),
                      "acuerdo": c.acuerdo, "p": c.p_valor})
    return pd.DataFrame(filas).sort_values(["p", "acuerdo"], ascending=[True, False])


def esperadas_por_azar(celdas, alfa=0.05):
    """
    Cuántas celdas quedarían por debajo de `alfa` sin que exista ninguna
    estructura: simplemente el número de celdas por alfa.

    Es la referencia contra la que hay que leer cualquier lista de hallazgos.
    Con 2.000 celdas y un corte al 5 %, cien salen "significativas" aunque los
    datos sean ruido puro. Como el p-valor binomial es discreto, esta cuenta es
    algo conservadora: la cifra real suele ser menor.
    """
    return len(celdas) * alfa


def resumen(celdas, alfa=0.05, top=15):
    """Informe legible: hallazgos, referencia de azar y veredicto."""
    if not celdas:
        return "Ninguna celda alcanzó el mínimo de episodios."

    t = tabla(celdas)
    consistentes = t[t["p"] <= alfa]
    azar = esperadas_por_azar(celdas, alfa)

    lineas = [
        f"  {len(celdas)} celdas con muestra suficiente",
        f"  {len(consistentes)} con p ≤ {alfa:.0%} (acuerdo entre períodos)",
        f"  {azar:.1f} es lo que daría el azar puro con ese número de celdas",
    ]
    if azar > 0:
        ratio = len(consistentes) / azar
        lineas.append(f"  ratio hallazgos/azar: {ratio:.1f}x"
                      + ("   ← hay estructura" if ratio >= 2
                         else "   ← indistinguible del azar"))
    if not consistentes.empty:
        lineas.append("")
        lineas.append(consistentes.head(top).to_string(index=False))
    return "\n".join(lineas)
