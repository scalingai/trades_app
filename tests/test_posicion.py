"""
Pruebas del backtest de posición continua.

Dos cosas se comprueban por encima del resto: que la posición del período t se
decida con información de t−1, y que el coste se cobre sobre cada cambio de
tamaño y no sólo al abrir y cerrar.
"""

import numpy as np
import pandas as pd
import pytest

from backtest import posicion


def serie(precios, freq="10s"):
    idx = pd.date_range("2026-01-01", periods=len(precios), freq=freq, tz="UTC")
    return pd.Series(np.asarray(precios, dtype=float), index=idx)


SIN_COSTES = posicion.ConfigPosicion(coste_por_lado=0.0, capital=1000.0)


# ========================
# ANTICIPACIÓN
# ========================

def test_la_posicion_va_un_periodo_por_detras_de_la_conviccion():
    """La convicción de t se calcula con el cierre de t: no se puede operar a ese cierre."""
    p = serie([100, 100, 110, 110])
    c = serie([0.0, 1.0, 0.0, 0.0])
    r = posicion.ejecutar(p, c, SIN_COSTES)
    assert r.posicion.tolist() == [0.0, 0.0, 1.0, 0.0]
    # La subida ocurre en el índice 2 y la posición ya estaba puesta: se cobra.
    assert r.retorno_bruto.iloc[2] == pytest.approx(0.10)


def test_una_conviccion_futura_no_cambia_el_pasado():
    p = serie(100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.001, 500))))
    c1 = serie(np.full(500, 0.5))
    c2 = c1.copy(); c2.iloc[250:] = -1.0
    a = posicion.ejecutar(p, c1, SIN_COSTES)
    b = posicion.ejecutar(p, c2, SIN_COSTES)
    assert np.allclose(a.equity.iloc[:250], b.equity.iloc[:250])


# ========================
# COSTES
# ========================

def test_el_coste_se_cobra_sobre_el_cambio_de_posicion():
    p = serie([100, 100, 100, 100])
    c = serie([1.0, 1.0, 0.0, 0.0])
    cfg = posicion.ConfigPosicion(coste_por_lado=0.001, capital=1000.0)
    r = posicion.ejecutar(p, c, cfg)
    # posiciones: 0, 1, 1, 0  -> cambios 0, 1, 0, 1
    assert r.costes.tolist() == pytest.approx([0.0, 0.001, 0.0, 0.001])


def test_ajustar_el_tamano_tambien_cuesta():
    """Pasar de 0,3 a 0,8 paga por el 0,5 de diferencia, no por la posición entera."""
    p = serie([100] * 4)
    c = serie([0.3, 0.8, 0.8, 0.8])
    cfg = posicion.ConfigPosicion(coste_por_lado=0.01, capital=1000.0)
    r = posicion.ejecutar(p, c, cfg)
    assert r.costes.iloc[2] == pytest.approx(0.5 * 0.01)


def test_dar_la_vuelta_cuesta_el_doble():
    p = serie([100] * 4)
    c = serie([1.0, -1.0, -1.0, -1.0])
    cfg = posicion.ConfigPosicion(coste_por_lado=0.01, capital=1000.0)
    r = posicion.ejecutar(p, c, cfg)
    assert r.costes.iloc[2] == pytest.approx(2.0 * 0.01)


def test_mas_coste_nunca_mejora():
    rng = np.random.default_rng(5)
    p = serie(100 * np.exp(np.cumsum(rng.normal(0, 0.001, 2000))))
    c = serie(rng.uniform(-1, 1, 2000))
    barato = posicion.ejecutar(p, c, posicion.ConfigPosicion(coste_por_lado=0.0001))
    caro = posicion.ejecutar(p, c, posicion.ConfigPosicion(coste_por_lado=0.01))
    assert caro.equity.iloc[-1] < barato.equity.iloc[-1]


# ========================
# COHERENCIA
# ========================

def test_conviccion_maxima_constante_equivale_a_comprar_y_mantener():
    rng = np.random.default_rng(1)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 1000)))
    p = serie(precios)
    r = posicion.ejecutar(p, serie(np.ones(1000)), SIN_COSTES)
    # Entra en el período 1, así que replica desde ahí.
    assert r.equity.iloc[-1] / 1000.0 - 1 == pytest.approx(precios[-1] / precios[0] - 1, rel=1e-6)


def test_conviccion_cero_no_hace_nada():
    p = serie([100, 120, 90, 110])
    r = posicion.ejecutar(p, serie(np.zeros(4)), SIN_COSTES)
    assert (r.posicion == 0).all()
    assert r.equity.iloc[-1] == pytest.approx(1000.0)


def test_la_conviccion_invertida_da_el_resultado_opuesto():
    rng = np.random.default_rng(2)
    p = serie(100 * np.exp(np.cumsum(rng.normal(0, 0.001, 500))))
    c = serie(rng.uniform(-1, 1, 500))
    a = posicion.ejecutar(p, c, SIN_COSTES)
    b = posicion.ejecutar(p, -c, SIN_COSTES)
    assert a.retorno_bruto.sum() == pytest.approx(-b.retorno_bruto.sum())


def test_la_posicion_respeta_el_apalancamiento():
    p = serie([100] * 100)
    c = serie(np.full(100, 5.0))          # muy por encima de 1
    cfg = posicion.ConfigPosicion(apalancamiento=2.0, coste_por_lado=0.0)
    r = posicion.ejecutar(p, c, cfg)
    assert r.posicion.abs().max() == pytest.approx(2.0)


# ========================
# ZONA MUERTA Y SUAVIZADO
# ========================

def test_la_zona_muerta_anula_las_convicciones_debiles():
    p = serie([100] * 10)
    c = serie([0.1] * 5 + [0.9] * 5)
    cfg = posicion.ConfigPosicion(zona_muerta=0.5, coste_por_lado=0.0)
    r = posicion.ejecutar(p, c, cfg)
    assert r.posicion.iloc[3] == 0.0
    assert r.posicion.iloc[-1] > 0.5


def test_el_suavizado_reduce_la_rotacion():
    rng = np.random.default_rng(3)
    p = serie(100 * np.exp(np.cumsum(rng.normal(0, 0.001, 3000))))
    c = serie(rng.uniform(-1, 1, 3000))
    bruto = posicion.ejecutar(p, c, posicion.ConfigPosicion(coste_por_lado=0.0))
    suave = posicion.ejecutar(p, c, posicion.ConfigPosicion(coste_por_lado=0.0, suavizado=50))
    assert suave.rotacion_anual < bruto.rotacion_anual


# ========================
# ENSEMBLE
# ========================

def test_la_conviccion_del_conjunto_esta_acotada():
    idx = pd.date_range("2026-01-01", periods=100, freq="10s", tz="UTC")
    rng = np.random.default_rng(4)
    p = {f"m{i}": pd.Series(rng.uniform(0, 1, 100), index=idx) for i in range(5)}
    c = posicion.conviccion_de_ensemble(p)
    assert c.min() >= -1.0 and c.max() <= 1.0


def test_modelos_en_desacuerdo_se_cancelan():
    idx = pd.date_range("2026-01-01", periods=10, freq="10s", tz="UTC")
    p = {"a": pd.Series(1.0, index=idx), "b": pd.Series(0.0, index=idx)}
    assert posicion.conviccion_de_ensemble(p).abs().max() == pytest.approx(0.0)


def test_unanimidad_da_conviccion_maxima():
    idx = pd.date_range("2026-01-01", periods=10, freq="10s", tz="UTC")
    p = {"a": pd.Series(1.0, index=idx), "b": pd.Series(1.0, index=idx)}
    assert posicion.conviccion_de_ensemble(p).min() == pytest.approx(1.0)


def test_el_filtro_de_sesion_anula_fuera_de_hora():
    idx = pd.date_range("2026-01-01", periods=24 * 6, freq="10min", tz="UTC")
    c = pd.Series(1.0, index=idx)
    f = posicion.filtrar_sesion(c, [20, 21])
    assert (f[f.index.hour.isin([20, 21])] == 1.0).all()
    assert (f[~f.index.hour.isin([20, 21])] == 0.0).all()


def test_las_metricas_no_revientan_sin_operaciones():
    p = serie([100] * 50)
    m = posicion.ejecutar(p, serie(np.zeros(50)), SIN_COSTES).metricas()
    assert m["rotacion_anual"] == 0.0
    assert m["retorno_total"] == pytest.approx(0.0)
