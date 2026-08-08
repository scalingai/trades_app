"""
Contexto de marco temporal superior (semanal) alineado sobre velas intradía.

Aquí vive el error más caro de todo el backtesting multi-timeframe: usar datos
de la vela semanal EN CURSO estando dentro de ella. El cierre de la semana no
se conoce hasta el domingo por la noche, así que un lunes no se puede filtrar
por "la semana cierra alcista". Un backtest que lo hace da resultados
espectaculares y absolutamente falsos.

Este módulo separa las dos cosas que sí son legítimas:

- Lo de las semanas YA CERRADAS: cierre, máximo, mínimo, rango, variación,
  pivotes. Se conoce entero y se puede usar desde el primer minuto de la
  semana siguiente.
- Lo de la semana EN CURSO acumulado hasta la vela actual: apertura (se sabe
  al abrir la semana) y el máximo y mínimo recorridos HASTA AHORA. Es causal
  porque sólo mira hacia atrás.

Todo lo que devuelve este módulo está desplazado o acumulado de forma causal, y
hay pruebas en tests/test_superior.py que lo verifican cambiando el futuro y
comprobando que el pasado no se mueve.
"""

import numpy as np
import pandas as pd

# Escala de cada característica, para que el generador no compare peras con
# manzanas (ver generador.BLOQUES).
ESCALAS = {
    "sem_ant_close": "precio", "sem_ant_high": "precio", "sem_ant_low": "precio",
    "sem_ant_open": "precio", "sem_ant_medio": "precio",
    "sem_open": "precio", "sem_high_hasta": "precio", "sem_low_hasta": "precio",
    "sem_pivote": "precio", "sem_r1": "precio", "sem_s1": "precio",
    "sem_sma": "precio",
    "sem_pos_rango": "osc100", "sem_pos_semana": "osc100",
    "sem_var": "pct",
}

# Las que aceptan periodo (en semanas); el resto lo ignoran.
CON_PERIODO = {"sem_sma", "sem_var"}


def _codigos_semana(fechas):
    """Índice entero de semana (lunes a domingo) para cada vela."""
    idx = pd.DatetimeIndex(fechas)
    # Los periodos se calculan sobre horas UTC sin zona: los datos ya vienen en
    # UTC, y quitarla explícitamente deja claro que el corte semanal es el de
    # UTC y no el de ninguna zona local.
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    codigos, _ = pd.factorize(idx.to_period("W"), sort=True)
    return np.asarray(codigos, dtype=int)


def _agregados_por_semana(codigos, apertura, alto, bajo, cierre):
    """OHLC de cada semana completa, indexado por código de semana."""
    n_semanas = int(codigos.max()) + 1
    inicio = np.zeros(n_semanas, dtype=int)
    fin = np.zeros(n_semanas, dtype=int)
    # codigos es no decreciente, así que los límites salen de los cambios.
    cambios = np.flatnonzero(np.diff(codigos)) + 1
    bordes = np.concatenate(([0], cambios, [len(codigos)]))
    for k in range(len(bordes) - 1):
        semana = codigos[bordes[k]]
        inicio[semana] = bordes[k]
        fin[semana] = bordes[k + 1]

    ohlc = {
        "open": np.array([apertura[inicio[s]] for s in range(n_semanas)]),
        "close": np.array([cierre[fin[s] - 1] for s in range(n_semanas)]),
        "high": np.array([alto[inicio[s]:fin[s]].max() for s in range(n_semanas)]),
        "low": np.array([bajo[inicio[s]:fin[s]].min() for s in range(n_semanas)]),
    }
    return ohlc, inicio, fin


def _acumulado_por_semana(valores, codigos, fn):
    """Máximo o mínimo acumulado desde el inicio de cada semana hasta cada vela."""
    salida = np.empty(len(valores), dtype=float)
    cambios = np.flatnonzero(np.diff(codigos)) + 1
    bordes = np.concatenate(([0], cambios, [len(codigos)]))
    for k in range(len(bordes) - 1):
        desde, hasta = bordes[k], bordes[k + 1]
        salida[desde:hasta] = fn(valores[desde:hasta])
    return salida


class ContextoSemanal:
    """
    Calcula y cachea las características semanales de una serie intradía.

    Se construye una vez por serie. Al recortar los datos (walk-forward,
    particiones) hay que construir uno nuevo, igual que con Contexto.
    """

    def __init__(self, datos):
        self.datos = datos
        self._cache = {}
        self._codigos = _codigos_semana(datos.fechas)
        self._ohlc, self._inicio, self._fin = _agregados_por_semana(
            self._codigos, datos.open, datos.high, datos.low, datos.close)
        self._n_semanas = len(self._ohlc["close"])

    def _de_semana_anterior(self, campo):
        """
        Valor de la semana YA CERRADA anterior, repetido en todas las velas de
        la semana en curso. NaN durante la primera semana, que no tiene previa.
        """
        por_semana = self._ohlc[campo]
        desplazado = np.concatenate(([np.nan], por_semana[:-1]))
        return desplazado[self._codigos]

    def _semanal_desplazado(self, serie_por_semana):
        """Alinea una serie indexada por semana usando sólo semanas cerradas."""
        desplazado = np.concatenate(([np.nan], serie_por_semana[:-1]))
        return desplazado[self._codigos]

    def calcular(self, nombre, periodo=4):
        clave = (nombre, int(periodo) if nombre in CON_PERIODO else 0)
        if clave in self._cache:
            return self._cache[clave]
        self._cache[clave] = self._construir(nombre, int(periodo))
        return self._cache[clave]

    def _construir(self, nombre, periodo):
        d = self.datos

        if nombre == "sem_ant_close":
            return self._de_semana_anterior("close")
        if nombre == "sem_ant_open":
            return self._de_semana_anterior("open")
        if nombre == "sem_ant_high":
            return self._de_semana_anterior("high")
        if nombre == "sem_ant_low":
            return self._de_semana_anterior("low")
        if nombre == "sem_ant_medio":
            return (self._de_semana_anterior("high") + self._de_semana_anterior("low")) / 2

        if nombre == "sem_open":
            # La apertura de la semana en curso se conoce al abrirla.
            return self._ohlc["open"][self._codigos]

        if nombre == "sem_high_hasta":
            return _acumulado_por_semana(d.high, self._codigos, np.maximum.accumulate)
        if nombre == "sem_low_hasta":
            return _acumulado_por_semana(d.low, self._codigos, np.minimum.accumulate)

        if nombre in ("sem_pivote", "sem_r1", "sem_s1"):
            alto = self._de_semana_anterior("high")
            bajo = self._de_semana_anterior("low")
            cierre = self._de_semana_anterior("close")
            pivote = (alto + bajo + cierre) / 3
            if nombre == "sem_pivote":
                return pivote
            return 2 * pivote - bajo if nombre == "sem_r1" else 2 * pivote - alto

        if nombre == "sem_sma":
            # Media de los cierres semanales, contando sólo semanas cerradas.
            cierres = self._ohlc["close"]
            media = np.full(self._n_semanas, np.nan)
            if periodo <= self._n_semanas:
                acumulado = np.concatenate(([0.0], np.cumsum(cierres)))
                media[periodo - 1:] = (acumulado[periodo:] - acumulado[:-periodo]) / periodo
            return self._semanal_desplazado(media)

        if nombre == "sem_var":
            # Variación porcentual entre cierres semanales cerrados.
            cierres = self._ohlc["close"]
            variacion = np.full(self._n_semanas, np.nan)
            if periodo < self._n_semanas:
                previo = cierres[:-periodo]
                with np.errstate(divide="ignore", invalid="ignore"):
                    variacion[periodo:] = np.where(previo != 0,
                                                   100 * (cierres[periodo:] - previo) / previo,
                                                   0.0)
            return self._semanal_desplazado(variacion)

        if nombre == "sem_pos_rango":
            # Dónde está el precio dentro del rango de la semana anterior.
            # 0 = en su mínimo, 100 = en su máximo. Puede salirse de [0,100]
            # cuando rompe el rango, que es justo la señal interesante.
            alto = self._de_semana_anterior("high")
            bajo = self._de_semana_anterior("low")
            rango = alto - bajo
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(rango > 0, 100 * (d.close - bajo) / rango, 50.0)

        if nombre == "sem_pos_semana":
            # Dónde está el precio dentro del recorrido de la semana EN CURSO
            # hasta ahora. Causal: el máximo y el mínimo son acumulados.
            alto = _acumulado_por_semana(d.high, self._codigos, np.maximum.accumulate)
            bajo = _acumulado_por_semana(d.low, self._codigos, np.minimum.accumulate)
            rango = alto - bajo
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(rango > 0, 100 * (d.close - bajo) / rango, 50.0)

        raise KeyError(f"Característica semanal desconocida: {nombre!r}")


def disponibles():
    return sorted(ESCALAS)
