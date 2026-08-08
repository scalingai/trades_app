"""
Walk-forward analysis.

Optimiza en una ventana, opera la siguiente con los parámetros elegidos sin
volver a tocarlos, avanza y repite. Todo lo que se mide sale de tramos que el
optimizador no vio, así que es lo más parecido a operar en real que se puede
hacer sobre histórico.

Responde a una pregunta distinta de la del barrido simple. El barrido pregunta
"¿qué parámetros funcionaron?"; el walk-forward pregunta "¿sirve de algo
reoptimizar cada cierto tiempo?". Una estrategia puede tener parámetros
buenísimos en el pasado y una eficiencia walk-forward pésima, y eso significa
que los parámetros no se sostienen de un periodo al siguiente.

La matriz repite el proceso con muchos tamaños de ventana. Si sólo funciona
con una combinación concreta de ventanas, eso también es sobreajuste: lo que
se busca es una zona amplia de configuraciones que funcionen parecido.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import metricas as mod_metricas
from .indicadores import Contexto
from .metricas import INTERVALOS_SEG
from .motor import Config, ejecutar
from . import estrategias as mod_estrategias
from .optimizar import buscar_mejor


def barras_por_dia(intervalo):
    return 86400 / INTERVALOS_SEG.get(intervalo, 3600)


@dataclass
class VentanaWF:
    indice: int
    desde_is: int
    hasta_is: int
    hasta_oos: int
    params: dict
    fitness_is: float
    metricas_is: dict
    metricas_oos: dict
    retorno_oos: float


@dataclass
class ResultadoWF:
    ventanas: list = field(default_factory=list)
    equity: np.ndarray = None
    metricas: dict = field(default_factory=dict)
    eficiencia: float = 0.0
    estabilidad_params: float = 0.0

    def tabla(self):
        """Una fila por ventana, para ver cómo se mueven los parámetros elegidos."""
        if not self.ventanas:
            return pd.DataFrame()
        filas = []
        for v in self.ventanas:
            fila = {"ventana": v.indice, **v.params,
                    "is_cagr": v.metricas_is["cagr"],
                    "is_return_dd": v.metricas_is["return_dd"],
                    "oos_retorno": v.retorno_oos,
                    "oos_operaciones": v.metricas_oos["n_operaciones"]}
            filas.append(fila)
        return pd.DataFrame(filas)


def _estabilidad_parametros(ventanas):
    """
    Fracción de ventanas en que el optimizador repitió la elección anterior.

    Cerca de 1 significa que los parámetros óptimos son estables en el tiempo;
    cerca de 0, que cada periodo pide unos distintos y por tanto no hay nada
    que llevarse al siguiente.
    """
    if len(ventanas) < 2:
        return 0.0
    repite = sum(1 for a, b in zip(ventanas, ventanas[1:]) if a.params == b.params)
    return repite / (len(ventanas) - 1)


def analizar(datos, nombre_estrategia, config=None, espacio=None, fitness="return_dd",
             dias_is=365, dias_oos=90, min_operaciones=20, procesos=1, verboso=True):
    """Ejecuta el walk-forward completo y devuelve el resultado agregado."""
    config = config or Config()
    por_dia = barras_por_dia(datos.intervalo)
    barras_is = int(dias_is * por_dia)
    barras_oos = int(dias_oos * por_dia)
    n = len(datos)

    if barras_is + barras_oos > n:
        raise ValueError(
            f"La serie tiene {n} barras y la configuración pide {barras_is + barras_oos} "
            f"({dias_is}d de ajuste + {dias_oos}d de validación). Usa ventanas más cortas "
            f"o un timeframe menor.")

    estrategia = mod_estrategias.obtener(nombre_estrategia)
    espacio = espacio or estrategia.espacio

    ventanas = []
    tramos_equity = []
    capital = config.capital
    inicio = 0
    indice = 0

    while inicio + barras_is + barras_oos <= n:
        fin_is = inicio + barras_is
        fin_oos = min(fin_is + barras_oos, n)

        datos_is = datos.tramo(inicio, fin_is)
        params, m_is = buscar_mejor(datos_is, nombre_estrategia, config, espacio,
                                    fitness, min_operaciones, procesos)

        if params is None:
            # Ninguna combinación llegó al mínimo de operaciones: la ventana se
            # queda fuera de mercado, que es lo que pasaría en real.
            if verboso:
                print(f"  ventana {indice}: sin combinación válida, fuera de mercado")
            tramos_equity.append(np.full(fin_oos - fin_is, capital))
            inicio += barras_oos
            indice += 1
            continue

        datos_oos = datos.tramo(fin_is, fin_oos)
        senales = estrategia.senales(Contexto(datos_oos), **params)
        resultado = ejecutar(datos_oos, senales, Config(**{**config.__dict__,
                                                          "capital": capital}))
        m_oos = mod_metricas.calcular(resultado, datos.intervalo, capital)

        tramos_equity.append(resultado.equity)
        retorno_oos = resultado.equity[-1] / capital - 1
        capital = float(resultado.equity[-1])

        ventanas.append(VentanaWF(indice, inicio, fin_is, fin_oos, params,
                                  m_is["return_dd"], m_is, m_oos, retorno_oos))
        if verboso:
            resumen_params = " ".join(f"{k}={v}" for k, v in params.items())
            print(f"  ventana {indice}: {resumen_params} → OOS {retorno_oos:+7.1%} "
                  f"({m_oos['n_operaciones']} ops)")

        inicio += barras_oos
        indice += 1

    if not tramos_equity:
        return ResultadoWF()

    equity = np.concatenate(tramos_equity)

    # Métricas sobre la curva encadenada de todos los tramos out-of-sample.
    class _Falso:
        pass
    falso = _Falso()
    falso.equity = equity
    falso.retorno = np.array([v.retorno_oos for v in ventanas])
    falso.entrada_idx = np.zeros(len(ventanas), dtype=int)
    falso.salida_idx = np.zeros(len(ventanas), dtype=int)
    falso.n_operaciones = len(ventanas)
    falso.datos = None
    m = mod_metricas.calcular(falso, datos.intervalo, config.capital)
    m["n_operaciones"] = int(sum(v.metricas_oos["n_operaciones"] for v in ventanas))
    m["exposicion"] = float(np.mean([v.metricas_oos["exposicion"] for v in ventanas]))

    # Eficiencia walk-forward: cuánto del rendimiento in-sample se conserva
    # fuera de muestra. Por encima de ~0,5 se considera aceptable; por debajo,
    # la optimización está capturando ruido.
    cagr_is = np.mean([v.metricas_is["cagr"] for v in ventanas])
    eficiencia = float(m["cagr"] / cagr_is) if cagr_is > 0 else 0.0

    return ResultadoWF(ventanas=ventanas, equity=equity, metricas=m,
                       eficiencia=eficiencia,
                       estabilidad_params=_estabilidad_parametros(ventanas))


def matriz(datos, nombre_estrategia, config=None, espacio=None, fitness="return_dd",
           dias_is_lista=(180, 365, 545), dias_oos_lista=(30, 60, 90, 120),
           min_operaciones=20, procesos=1):
    """
    Repite el walk-forward con varias combinaciones de ventanas.

    Lo que se busca no es la celda mejor, sino una zona amplia con resultados
    parecidos. Una única celda buena rodeada de celdas malas es ruido, igual
    que un único juego de parámetros bueno en un barrido.
    """
    filas = []
    for dias_is in dias_is_lista:
        for dias_oos in dias_oos_lista:
            try:
                r = analizar(datos, nombre_estrategia, config, espacio, fitness,
                             dias_is, dias_oos, min_operaciones, procesos, verboso=False)
            except ValueError:
                continue                     # ventanas más largas que la serie
            if not r.ventanas:
                continue
            filas.append({
                "dias_is": dias_is,
                "dias_oos": dias_oos,
                "ventanas": len(r.ventanas),
                "retorno": r.metricas["retorno_total"],
                "cagr": r.metricas["cagr"],
                "max_dd": r.metricas["max_drawdown"],
                "eficiencia": r.eficiencia,
                "estab_params": r.estabilidad_params,
            })
    return pd.DataFrame(filas)


def formatear(resultado):
    """Resumen legible del walk-forward."""
    if not resultado.ventanas:
        return "No se pudo completar ninguna ventana."

    m = resultado.metricas
    aviso = ""
    if resultado.eficiencia < 0.5:
        aviso = ("\n  ⚠️  Eficiencia baja: fuera de muestra se conserva menos de la mitad\n"
                 "      del rendimiento del ajuste. La optimización está cogiendo ruido.")
    if resultado.estabilidad_params < 0.3:
        aviso += ("\n  ⚠️  Los parámetros elegidos cambian casi en cada ventana, así que\n"
                  "      no hay un óptimo estable que llevarse al periodo siguiente.")

    return (
        f"  ventanas                {len(resultado.ventanas):>8}\n"
        f"  retorno out-of-sample   {m['retorno_total']:>8.1%}\n"
        f"  CAGR out-of-sample      {m['cagr']:>8.1%}\n"
        f"  max drawdown            {m['max_drawdown']:>8.1%}\n"
        f"  operaciones             {m['n_operaciones']:>8}\n"
        f"  eficiencia walk-forward {resultado.eficiencia:>8.2f}\n"
        f"  estabilidad parámetros  {resultado.estabilidad_params:>8.0%}"
        f"{aviso}"
    )
