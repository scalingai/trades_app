"""
Pruebas de la búsqueda de separadores.

La que sostiene el módulo es la de la permutación: buscar el máximo entre
varios candidatos encuentra algo aunque no haya nada, y si el nulo no
incorpora esa búsqueda, el contraste declara hallazgos donde sólo hay ruido.
"""

import numpy as np
import pytest

from backtest import separador


def muestra(n=800, semilla=0):
    rng = np.random.default_rng(semilla)
    return rng, rng.random(n)


# ========================
# TASAS POR GRUPO
# ========================

def test_una_variable_que_lo_sabe_todo_separa_del_todo():
    v = np.arange(400, dtype=float)
    gana = v >= 200
    assert separador.separacion(v, gana) == pytest.approx(1.0)


def test_una_variable_invertida_separa_al_reves():
    v = np.arange(400, dtype=float)
    gana = v < 200
    assert separador.separacion(v, gana) == pytest.approx(-1.0)


def test_una_variable_ciega_no_separa():
    rng, v = muestra(4000, semilla=1)
    gana = rng.random(4000) < 0.5
    assert abs(separador.separacion(v, gana)) < 0.06


def test_los_grupos_reparten_la_muestra():
    v = np.arange(1000, dtype=float)
    gana = np.zeros(1000, dtype=bool)
    gana[::2] = True
    t = separador.tasa_por_grupo(v, gana, grupos=4)
    assert len(t) == 4
    assert np.all(np.abs(t - 0.5) < 0.05)


def test_los_nan_no_participan():
    """Una característica que no se pudo calcular no puede opinar."""
    v = np.arange(400, dtype=float)
    v[:100] = np.nan
    gana = v >= 250
    assert np.isfinite(separador.separacion(v, gana))


def test_muestra_diminuta_devuelve_nan():
    assert np.isnan(separador.separacion(np.arange(5.0), np.ones(5, dtype=bool)))


def test_una_variable_constante_no_revienta():
    gana = np.zeros(400, dtype=bool)
    gana[:200] = True
    s = separador.separacion(np.ones(400), gana)
    assert np.isnan(s) or abs(s) < 1e-9


# ========================
# BÚSQUEDA
# ========================

def test_la_busqueda_pone_primera_a_la_que_mas_separa():
    rng, _ = muestra(semilla=2)
    n = 1200
    util = rng.random(n)
    gana = util > 0.5
    caracteristicas = {
        "ruido_a": rng.random(n),
        "util": util,
        "ruido_b": rng.random(n),
    }
    t = separador.buscar(caracteristicas, gana)
    assert t["variable"].iloc[0] == "util"


# ========================
# PERMUTACIÓN
# ========================

def test_sobre_puro_ruido_la_permutacion_no_encuentra_nada():
    """
    Ocho variables sin relación con el resultado. La mejor de las ocho separa
    algo por azar, y el contraste tiene que decir que eso es justamente lo
    normal en vez de cantar un hallazgo.
    """
    rng = np.random.default_rng(3)
    n = 800
    gana = rng.random(n) < 0.5
    caracteristicas = {f"v{k}": rng.random(n) for k in range(8)}
    _, veredicto = separador.contraste(caracteristicas, gana, repeticiones=200)
    assert veredicto["p"] > 0.1, \
        f"p = {veredicto['p']:.3f} sobre ruido: el contraste canta hallazgos falsos"
    assert veredicto["nulo_medio"] > 0.02, \
        "el nulo debería recoger que buscar el máximo de ocho ya separa algo"


def test_un_separador_plantado_sobrevive_a_la_permutacion():
    """Control positivo: si la relación existe, tiene que salir."""
    rng = np.random.default_rng(4)
    n = 800
    util = rng.random(n)
    # Relación clara pero no perfecta.
    gana = rng.random(n) < (0.3 + 0.4 * util)
    caracteristicas = {f"ruido{k}": rng.random(n) for k in range(7)}
    caracteristicas["util"] = util
    tabla, veredicto = separador.contraste(caracteristicas, gana, repeticiones=200)
    assert tabla["variable"].iloc[0] == "util"
    assert veredicto["p"] < 0.05
    assert veredicto["mejor"] > veredicto["nulo_p95"]


def test_una_variable_inevaluable_no_borra_la_distribucion_nula():
    """
    Regresión. Si una candidata devuelve NaN y ese NaN se propaga al máximo, la
    distribución nula queda en NaN entera y la comparación `nulo >= real` sale
    falsa siempre: p = 0. O sea que el contraste cantaría un hallazgo justo
    cuando se quedó sin nada con qué comparar, que es el peor error posible.
    """
    rng = np.random.default_rng(6)
    n = 600
    gana = rng.random(n) < 0.5
    caracteristicas = {
        "rota": np.full(n, np.nan),
        "a": rng.random(n),
        "b": rng.random(n),
    }
    _, veredicto = separador.contraste(caracteristicas, gana, repeticiones=100)
    assert np.isfinite(veredicto["nulo_medio"])
    assert veredicto["repeticiones"] == 100
    assert veredicto["p"] > 0.1


def test_una_variable_binaria_parte_por_su_valor():
    """Una bandera de sí o no tiene que separar sus dos grupos, no colapsar."""
    bandera = np.zeros(600)
    bandera[300:] = 1.0
    gana = np.zeros(600, dtype=bool)
    gana[300:] = True
    assert separador.separacion(bandera, gana) == pytest.approx(1.0)


def test_el_nulo_crece_con_el_numero_de_candidatos():
    """
    Cuantos más candidatos se prueben, más separa el mejor por azar. Es la
    razón de ser del contraste, y si no se cumpliera estaría mal construido.
    """
    rng = np.random.default_rng(5)
    n = 600
    gana = rng.random(n) < 0.5
    pocos = {f"v{k}": rng.random(n) for k in range(2)}
    muchos = {f"v{k}": rng.random(n) for k in range(20)}
    n_pocos = separador.permutacion(pocos, gana, repeticiones=120, semilla=1).mean()
    n_muchos = separador.permutacion(muchos, gana, repeticiones=120, semilla=1).mean()
    assert n_muchos > n_pocos
