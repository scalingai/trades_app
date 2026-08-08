"""
Pruebas del primer paso por barrera.

La central es la del paseo aleatorio: sobre una serie sin estructura, la
proporción de objetivos alcanzados tiene que coincidir con S/(S+T). Si no
coincide, el medidor está sesgado y cualquier "exceso" que reporte sobre datos
reales será el sesgo y no el mercado.
"""

import numpy as np
import pandas as pd
import pytest

from backtest import barreras


def marco(cierre, alto=None, bajo=None):
    c = np.asarray(cierre, dtype=float)
    return pd.DataFrame({
        "high": np.asarray(alto, dtype=float) if alto is not None else c,
        "low": np.asarray(bajo, dtype=float) if bajo is not None else c,
        "close": c,
    })


def arrays(df):
    return (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())


# ========================
# FÓRMULA
# ========================

def test_la_teorica_es_simetrica_en_uno_a_uno():
    assert barreras.teorica(0.01, 0.01) == pytest.approx(0.5)


def test_objetivo_lejano_baja_la_probabilidad():
    assert barreras.teorica(0.01, 0.02) == pytest.approx(1 / 3)
    assert barreras.teorica(0.01, 0.03) == pytest.approx(0.25)


def test_objetivo_cercano_la_sube():
    assert barreras.teorica(0.02, 0.01) == pytest.approx(2 / 3)


# ========================
# MECÁNICA
# ========================

def test_toca_el_objetivo():
    df = marco([100, 100, 100], alto=[100, 100, 103], bajo=[100, 100, 100])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 5)
    assert d.motivo[0] == barreras.OBJETIVO
    assert d.retorno[0] == pytest.approx(0.02)


def test_toca_el_stop():
    df = marco([100, 100, 100], alto=[100, 100, 100], bajo=[100, 100, 97])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 5)
    assert d.motivo[0] == barreras.STOP
    assert d.retorno[0] == pytest.approx(-0.02)


def test_con_las_dos_en_la_misma_barra_manda_el_stop():
    """No se sabe cuál llegó antes; suponer lo contrario es regalarse resultados."""
    df = marco([100, 100], alto=[100, 105], bajo=[100, 95])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 5)
    assert d.motivo[0] == barreras.STOP


def test_sin_tocar_nada_cierra_por_tiempo():
    df = marco([100, 100.5, 101])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.05, 0.05, 2)
    assert d.motivo[0] == barreras.TIEMPO
    assert d.retorno[0] == pytest.approx(0.01, abs=0.002)


def test_no_se_opera_en_la_barra_de_entrada():
    """La entrada es al cierre de esa barra: su propio recorrido ya pasó."""
    df = marco([100, 100], alto=[110, 100], bajo=[90, 100])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 1)
    assert d.motivo[0] == barreras.TIEMPO


def test_el_corto_invierte_las_barreras():
    df = marco([100, 100], alto=[100, 100], bajo=[100, 97])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 5, direccion=-1)
    assert d.motivo[0] == barreras.OBJETIVO       # bajar es ganar en corto
    assert d.retorno[0] == pytest.approx(0.02)


def test_entradas_sin_horizonte_se_descartan():
    df = marco([100, 100, 100])
    d = barreras.recorrer(*arrays(df), np.array([2]), 0.02, 0.02, 5)
    assert len(d) == 0


# ========================
# EL CONTRASTE CONTRA EL PASEO ALEATORIO
# ========================

@pytest.mark.parametrize("ratio", [0.5, 1.0, 2.0])
def test_sobre_un_paseo_aleatorio_se_cumple_la_formula(ratio):
    """
    Sin estructura, la proporción observada tiene que coincidir con S/(S+T).
    Es la prueba que valida el medidor entero.
    """
    rng = np.random.default_rng(4)
    n = 2_000_000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    df = marco(precios, alto=precios * 1.0002, bajo=precios * 0.9998)

    stop = 0.01
    objetivo = stop * ratio
    entradas = np.arange(0, n - 1, 500)
    # Horizonte muy largo para que casi todas se resuelvan por barrera.
    d = barreras.recorrer(*arrays(df), entradas, stop, objetivo, 200_000)
    r = barreras.contraste(d, stop, objetivo)

    assert r["resueltas"] > 2000
    assert abs(r["exceso"]) < 0.04, \
        f"exceso {r['exceso']:+.3f} sobre un paseo: el medidor está sesgado"


def test_el_valor_esperado_de_un_paseo_es_menos_el_coste():
    """
    Corolario de la fórmula: sobre un paseo, cualquier bracket pierde
    exactamente el coste. Si sale otra cosa, el cálculo está mal.
    """
    rng = np.random.default_rng(6)
    n = 1_500_000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    df = marco(precios, alto=precios * 1.0002, bajo=precios * 0.9998)
    d = barreras.recorrer(*arrays(df), np.arange(0, n - 1, 500), 0.01, 0.01, 200_000)
    r = barreras.contraste(d, 0.01, 0.01, coste=0.0012)
    assert abs(r["bruto_medio"]) < 0.0012, \
        f"bruto {r['bruto_medio']:+.4%} sobre un paseo: debería rondar cero"


def test_una_serie_con_tendencia_da_exceso_positivo():
    """Control positivo: si el precio persiste, el objetivo se toca de más."""
    rng = np.random.default_rng(8)
    n = 800_000
    pasos = rng.normal(0.00015, 0.0008, n)      # deriva clara al alza
    precios = 30000 * np.exp(np.cumsum(pasos))
    df = marco(precios, alto=precios * 1.0002, bajo=precios * 0.9998)
    d = barreras.recorrer(*arrays(df), np.arange(0, n - 1, 500), 0.01, 0.01, 200_000)
    r = barreras.contraste(d, 0.01, 0.01)
    assert r["exceso"] > 0.05, f"exceso {r['exceso']:+.3f}: no vio una deriva que existe"


# ========================
# BARRIDO
# ========================

def test_las_claves_del_reparto_no_pisan_los_parametros():
    """
    Regresión: el reparto usaba las claves stop/objetivo, que son también los
    nombres de los parámetros, y al volcarlo en la misma fila los machacaba.
    La tabla salía con la fracción de paradas en la columna de la distancia.
    """
    rng = np.random.default_rng(11)
    n = 40000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = marco(precios, alto=precios * 1.001, bajo=precios * 0.999)
    t = barreras.barrido(df, stops=[0.007], ratios=[1.5], horizontes=[360], cada=360)
    assert t["stop"].iloc[0] == pytest.approx(0.007)
    assert t["objetivo"].iloc[0] == pytest.approx(0.0105)
    assert {"frac_objetivo", "frac_stop", "frac_tiempo"} <= set(t.columns)


def test_el_barrido_cubre_todas_las_combinaciones():
    rng = np.random.default_rng(2)
    n = 60000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = marco(precios, alto=precios * 1.001, bajo=precios * 0.999)
    t = barreras.barrido(df, stops=[0.005, 0.01], ratios=[1.0, 2.0],
                         horizontes=[360, 720], cada=360)
    assert len(t) == 8
    assert {"stop", "ratio", "horizonte", "exceso", "neto_medio"} <= set(t.columns)


def test_el_reparto_suma_uno():
    rng = np.random.default_rng(3)
    n = 50000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = marco(precios, alto=precios * 1.001, bajo=precios * 0.999)
    d = barreras.recorrer(*arrays(df), np.arange(0, n - 1, 500), 0.01, 0.01, 360)
    assert sum(d.reparto().values()) == pytest.approx(1.0)


def test_contraste_sin_operaciones():
    vacio = barreras.Desenlaces(np.array([]), np.array([]), np.array([]), np.array([]), 1)
    assert barreras.contraste(vacio, 0.01, 0.01) == {}
