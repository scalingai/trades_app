"""
Barrido de parámetros con separación in-sample / out-of-sample.

La regla que hace útil a esto: los parámetros se eligen mirando SÓLO el tramo
in-sample, y el out-of-sample se mira una vez, al final, para ver si lo elegido
sobrevive. En cuanto se usa el out-of-sample para decidir, deja de ser
out-of-sample y el barrido vuelve a ser un ejercicio de sobreajuste.

Probar N combinaciones y quedarse con la mejor infla el resultado aunque no
haya ninguna señal real: es el problema de comparaciones múltiples. Por eso
`resumen()` informa de cuántas combinaciones se probaron y de qué porcentaje
salió rentable, que es la referencia contra la que hay que juzgar a la ganadora.
"""

import itertools
import multiprocessing as mp
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import estrategias as mod_estrategias
from . import metricas as mod_metricas
from .indicadores import Contexto
from .motor import Config, ejecutar

# Criterios de puntuación. Todos "más alto es mejor".
FITNESS = {
    "return_dd": lambda m: m["return_dd"],
    "cagr": lambda m: m["cagr"],
    "sharpe": lambda m: m["sharpe"],
    "sortino": lambda m: m["sortino"],
    "profit_factor": lambda m: 0.0 if np.isinf(m["profit_factor"]) else m["profit_factor"],
    "estabilidad": lambda m: m["estabilidad"],
    # Combinado: premia rentabilidad sostenida y penaliza la curva irregular.
    "compuesto": lambda m: m["return_dd"] * max(m["estabilidad"], 0.0),
    # Para estrategias de ratio fijo: lo que importa es cuánto supera el
    # acierto al de equilibrio. Se usa el suelo del intervalo de confianza y no
    # el acierto crudo, para que una muestra de 25 operaciones no gane a una de
    # 400 sólo por tener menos con qué equivocarse.
    "acierto": lambda m: (m["win_rate_inf"] - m["win_rate_equilibrio"]
                          if np.isfinite(m["win_rate_equilibrio"]) else -np.inf),
    "expectativa": lambda m: m["retorno_medio"],
}


@dataclass
class Particion:
    """Corte temporal entre el tramo de ajuste y el de validación."""
    entrenamiento: object
    validacion: object
    corte: int


def partir(datos, fraccion_oos=0.3):
    """Parte la serie en dos tramos consecutivos. El out-of-sample es el más reciente."""
    if not 0 < fraccion_oos < 1:
        raise ValueError("fraccion_oos tiene que estar entre 0 y 1")
    corte = int(len(datos) * (1 - fraccion_oos))
    return Particion(datos.tramo(0, corte), datos.tramo(corte, len(datos)), corte)


def combinaciones(espacio):
    """Producto cartesiano del espacio de parámetros, como lista de dicts."""
    if not espacio:
        return [{}]
    claves = list(espacio)
    valores = [v if isinstance(v, (list, tuple)) else [v] for v in espacio.values()]
    return [dict(zip(claves, combo)) for combo in itertools.product(*valores)]


def evaluar(contexto, estrategia, params, config, intervalo):
    """
    Evalúa una combinación. Devuelve None si la estrategia la rechaza por
    incoherente (p.ej. media rápida más lenta que la lenta).
    """
    senales = estrategia.senales(contexto, **params)
    if senales is None:
        return None
    resultado = ejecutar(contexto.datos, senales, config)
    return mod_metricas.calcular(resultado, intervalo, config.capital)


# El pool de procesos comparte estado por proceso: cada worker construye su
# Contexto una sola vez y reaprovecha la caché de indicadores en todas sus
# combinaciones. Sin esto, paralelizar sale más caro que no hacerlo.
_ESTADO = {}


def _iniciar_worker(datos, nombre_estrategia, config, intervalo):
    _ESTADO["contexto"] = Contexto(datos)
    _ESTADO["estrategia"] = mod_estrategias.obtener(nombre_estrategia)
    _ESTADO["config"] = config
    _ESTADO["intervalo"] = intervalo


def _evaluar_worker(params):
    m = evaluar(_ESTADO["contexto"], _ESTADO["estrategia"], params,
                _ESTADO["config"], _ESTADO["intervalo"])
    return params, m


def evaluar_muchas(datos, nombre_estrategia, lista_params, config, intervalo, procesos=1):
    """Evalúa muchas combinaciones sobre la misma serie, opcionalmente en paralelo."""
    if procesos and procesos > 1 and len(lista_params) > procesos * 4:
        with mp.Pool(procesos, initializer=_iniciar_worker,
                     initargs=(datos, nombre_estrategia, config, intervalo)) as pool:
            return pool.map(_evaluar_worker, lista_params, chunksize=8)

    contexto = Contexto(datos)
    estrategia = mod_estrategias.obtener(nombre_estrategia)
    return [(p, evaluar(contexto, estrategia, p, config, intervalo)) for p in lista_params]


def buscar_mejor(datos, nombre_estrategia, config=None, espacio=None, fitness="return_dd",
                 min_operaciones=30, procesos=1):
    """
    Mejor combinación sobre TODA la serie que se le pase, sin partirla.

    Es la pieza que usa el walk-forward dentro de cada ventana de ajuste: allí
    el corte in-sample / out-of-sample lo pone la propia ventana.
    """
    config = config or Config()
    estrategia = mod_estrategias.obtener(nombre_estrategia)
    espacio = espacio or estrategia.espacio
    puntuar = FITNESS[fitness]

    mejor_params, mejor_metricas, mejor_valor = None, None, -np.inf
    for params, m in evaluar_muchas(datos, nombre_estrategia, combinaciones(espacio),
                                    config, datos.intervalo, procesos):
        if m is None or m["n_operaciones"] < min_operaciones:
            continue
        valor = puntuar(m)
        if np.isfinite(valor) and valor > mejor_valor:
            mejor_params, mejor_metricas, mejor_valor = params, m, valor
    return mejor_params, mejor_metricas


def grid(datos, nombre_estrategia, config=None, espacio=None, fitness="return_dd",
         fraccion_oos=0.3, min_operaciones=30, procesos=1):
    """
    Recorre el espacio de parámetros sobre el tramo in-sample y evalúa todas
    las combinaciones supervivientes también en out-of-sample.

    Devuelve un DataFrame ordenado por fitness in-sample, con las métricas de
    los dos tramos. Las columnas is_* son con las que se elige; las oos_* son
    las que dicen si la elección valía algo.
    """
    config = config or Config()
    if fitness not in FITNESS:
        raise ValueError(f"fitness desconocido: {fitness}. Opciones: {', '.join(FITNESS)}")

    estrategia = mod_estrategias.obtener(nombre_estrategia)
    espacio = espacio or estrategia.espacio
    lista = combinaciones(espacio)

    particion = partir(datos, fraccion_oos)
    intervalo = datos.intervalo

    dentro = evaluar_muchas(particion.entrenamiento, nombre_estrategia, lista,
                            config, intervalo, procesos)
    validos = [(p, m) for p, m in dentro if m is not None]

    fuera = dict()
    if validos:
        params_validos = [p for p, _ in validos]
        for p, m in evaluar_muchas(particion.validacion, nombre_estrategia, params_validos,
                                   config, intervalo, procesos):
            fuera[tuple(sorted(p.items()))] = m

    filas = []
    for params, m_is in validos:
        m_oos = fuera.get(tuple(sorted(params.items())))
        fila = dict(params)
        fila["is_fitness"] = FITNESS[fitness](m_is)
        # Una estrategia con cuatro operaciones puede tener métricas
        # espectaculares y no significar nada.
        fila["descartada"] = m_is["n_operaciones"] < min_operaciones
        for clave in ("retorno_total", "cagr", "max_drawdown", "return_dd", "sharpe",
                      "profit_factor", "win_rate", "n_operaciones", "estabilidad"):
            fila[f"is_{clave}"] = m_is[clave]
            fila[f"oos_{clave}"] = m_oos[clave] if m_oos else np.nan
        fila["oos_fitness"] = FITNESS[fitness](m_oos) if m_oos else np.nan
        filas.append(fila)

    tabla = pd.DataFrame(filas)
    if tabla.empty:
        return tabla
    # Las descartadas se quedan en la tabla pero al final, para que se vea
    # cuántas combinaciones se filtraron y por qué.
    return tabla.sort_values(["descartada", "is_fitness"],
                             ascending=[True, False]).reset_index(drop=True)


def resumen(tabla, fitness="return_dd"):
    """Contexto estadístico del barrido: sin esto, la fila ganadora engaña."""
    if tabla.empty:
        return "Ninguna combinación válida."

    utiles = tabla[~tabla["descartada"]]
    if utiles.empty:
        return (f"{len(tabla)} combinaciones probadas, ninguna llegó al mínimo de "
                f"operaciones exigido.")

    rentables_is = (utiles["is_retorno_total"] > 0).mean()
    rentables_oos = (utiles["oos_retorno_total"] > 0).mean()
    mejor = utiles.iloc[0]

    # Si la ganadora in-sample se desploma fuera de muestra, el barrido ajustó ruido.
    degradacion = ""
    if np.isfinite(mejor["oos_fitness"]) and mejor["is_fitness"] > 0:
        ratio = mejor["oos_fitness"] / mejor["is_fitness"]
        degradacion = f"\n  la mejor conserva el {ratio:>6.0%} de su fitness fuera de muestra"
        if ratio < 0.3:
            degradacion += "  ← se cayó al salir del tramo de ajuste"

    return (
        f"  {len(tabla)} combinaciones probadas, {len(utiles)} con operaciones suficientes\n"
        f"  rentables in-sample:  {rentables_is:>6.0%}\n"
        f"  rentables out-of-sample: {rentables_oos:>6.0%}"
        f"{degradacion}\n"
        f"  Con {len(utiles)} combinaciones probadas, que la mejor destaque es lo esperable\n"
        f"  incluso sin señal real. Lo que cuenta es la columna oos_, y aun así\n"
        f"  sólo se puede mirar una vez."
    )
