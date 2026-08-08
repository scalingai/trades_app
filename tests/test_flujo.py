"""
Pruebas del flujo de órdenes y del modelo de probabilidad.

La que importa por encima de todas es la de anticipación: si una sola
característica usa información posterior a su vela, el AUC sube, el modelo
parece brillante y no sirve para nada.
"""

import numpy as np
import pandas as pd
import pytest

from backtest import flujo


def serie_flujo(n=5000, semilla=0):
    """Velas de 10 s sintéticas con volumen comprador y vendedor coherentes."""
    rng = np.random.default_rng(semilla)
    idx = pd.date_range("2026-01-01", periods=n, freq="10s", tz="UTC")
    cierre = 60000 * np.exp(np.cumsum(rng.normal(0, 0.0002, n)))
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    rango = cierre * rng.uniform(0.00005, 0.0005, n)
    volumen = rng.gamma(2.0, 1.5, n)
    return pd.DataFrame({
        "open": apertura,
        "high": np.maximum(apertura, cierre) + rango,
        "low": np.minimum(apertura, cierre) - rango,
        "close": cierre,
        "volume": volumen,
        "trades": rng.integers(5, 400, n).astype(float),
        # El comprador agresivo es siempre una fracción del volumen total.
        "taker_buy": volumen * rng.beta(2, 2, n),
    }, index=idx)


# ========================
# ANTICIPACIÓN
# ========================

def test_ninguna_caracteristica_usa_el_futuro():
    """
    Se destroza la segunda mitad de la serie. Ningún valor de la primera puede
    moverse: si se mueve, esa característica mira hacia delante.
    """
    base = serie_flujo(4000)
    corte = 2000
    alterada = base.copy()
    for col in ("open", "high", "low", "close"):
        alterada.iloc[corte:, alterada.columns.get_loc(col)] *= 5
    for col in ("volume", "trades", "taker_buy"):
        alterada.iloc[corte:, alterada.columns.get_loc(col)] *= 20

    a, b = flujo.construir(base), flujo.construir(alterada)
    for col in a.columns:
        assert np.allclose(a[col].iloc[:corte], b[col].iloc[:corte], equal_nan=True), \
            f"{col} usa datos del futuro"


def test_el_objetivo_si_mira_al_futuro():
    """El target tiene que ser estrictamente futuro; si no, no se predice nada."""
    df = serie_flujo(1000)
    y, futuro = flujo.objetivo(df, horizonte=1)
    esperado = df["close"].shift(-1) / df["close"] - 1
    assert np.allclose(futuro.dropna(), esperado.dropna())
    assert np.isnan(y.iloc[-1])          # la última vela no tiene futuro


def test_el_objetivo_con_umbral_descarta_el_ruido():
    df = serie_flujo(2000)
    y_sin, _ = flujo.objetivo(df, horizonte=1, umbral=0.0)
    y_con, _ = flujo.objetivo(df, horizonte=1, umbral=0.0005)
    assert y_con.notna().sum() < y_sin.notna().sum()
    assert set(y_con.dropna().unique()) <= {0.0, 1.0}


# ========================
# DESEQUILIBRIO
# ========================

def test_el_desequilibrio_esta_acotado():
    x = flujo.construir(serie_flujo(3000))
    d = x["dsq"].dropna()
    assert d.min() >= -1.0 - 1e-9 and d.max() <= 1.0 + 1e-9


def test_desequilibrio_extremo_en_los_dos_sentidos():
    """Todo comprador agresivo -> +1. Nada comprador -> -1."""
    df = serie_flujo(500)
    todo = df.copy(); todo["taker_buy"] = todo["volume"]
    nada = df.copy(); nada["taker_buy"] = 0.0
    assert flujo.construir(todo)["dsq"].iloc[10:].max() == pytest.approx(1.0)
    assert flujo.construir(nada)["dsq"].iloc[10:].min() == pytest.approx(-1.0)


def test_el_volumen_cero_no_rompe_nada():
    df = serie_flujo(500)
    df.iloc[100:120, df.columns.get_loc("volume")] = 0.0
    df.iloc[100:120, df.columns.get_loc("taker_buy")] = 0.0
    df.iloc[100:120, df.columns.get_loc("trades")] = 0.0
    x = flujo.construir(df)
    assert np.isfinite(x["dsq"].to_numpy()).all()
    assert np.isfinite(x["tamano_rel"].to_numpy()).all()


def test_faltan_columnas_de_flujo_da_error_claro():
    df = serie_flujo(100).drop(columns=["taker_buy"])
    with pytest.raises(ValueError, match="flujo"):
        flujo.construir(df)


def test_la_hora_es_ciclica():
    """Las 23:59 y las 00:00 tienen que quedar cerca, no en extremos opuestos."""
    x = flujo.construir(serie_flujo(9000))
    r = np.hypot(x["hora_sin"], x["hora_cos"])
    assert np.allclose(r, 1.0)


# ========================
# MODELO
# ========================

def test_sobre_ruido_puro_el_auc_ronda_0_5():
    """
    Sin señal que aprender, un modelo honesto no distingue nada. Un AUC alto
    aquí significaría fuga de información, no habilidad.
    """
    df = serie_flujo(20000, semilla=3)
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df, horizonte=1)
    corte = 14000
    modelo = flujo.entrenar(x.iloc[:corte], y.iloc[:corte])
    r = flujo.evaluar(modelo, x.iloc[corte:], y.iloc[corte:], df.index[corte:])
    assert 0.44 < r["auc"] < 0.56, f"AUC {r['auc']:.3f} sobre ruido: hay fuga"


def test_con_señal_inyectada_el_modelo_la_encuentra():
    """Control positivo: si el desequilibrio predice de verdad, tiene que verse."""
    rng = np.random.default_rng(7)
    n = 20000
    idx = pd.date_range("2026-01-01", periods=n, freq="10s", tz="UTC")
    volumen = rng.gamma(2.0, 1.5, n)
    fraccion = rng.beta(2, 2, n)
    desequilibrio = 2 * fraccion - 1
    # El retorno siguiente depende del desequilibrio de ESTA vela.
    pasos = 0.0002 * desequilibrio + rng.normal(0, 0.0002, n)
    cierre = 60000 * np.exp(np.cumsum(np.concatenate(([0.0], pasos[:-1]))))
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    df = pd.DataFrame({
        "open": apertura, "high": np.maximum(apertura, cierre) * 1.0001,
        "low": np.minimum(apertura, cierre) * 0.9999, "close": cierre,
        "volume": volumen, "trades": rng.integers(5, 400, n).astype(float),
        "taker_buy": volumen * fraccion,
    }, index=idx)

    x = flujo.construir(df)
    y, _ = flujo.objetivo(df, horizonte=1)
    corte = 14000
    modelo = flujo.entrenar(x.iloc[:corte], y.iloc[:corte])
    r = flujo.evaluar(modelo, x.iloc[corte:], y.iloc[corte:], df.index[corte:])
    assert r["auc"] > 0.6, f"AUC {r['auc']:.3f}: no encontró una señal que existe"


def test_la_probabilidad_esta_entre_0_y_1():
    df = serie_flujo(8000)
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df)
    modelo = flujo.entrenar(x.iloc[:6000], y.iloc[:6000])
    p = modelo.probabilidad(x)
    assert len(p) == len(x)
    assert p.min() >= 0.0 and p.max() <= 1.0


def test_las_filas_incompletas_dan_probabilidad_neutra():
    """Las primeras velas no tienen ventanas llenas: no se debe inventar señal."""
    df = serie_flujo(8000)
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df)
    modelo = flujo.entrenar(x.iloc[:6000], y.iloc[:6000])
    p = modelo.probabilidad(x)
    assert p[0] == 0.5


def test_auc_casos_extremos():
    perfecto = np.array([0.1, 0.2, 0.8, 0.9])
    assert flujo.auc(perfecto, np.array([0.0, 0.0, 1.0, 1.0])) == pytest.approx(1.0)
    assert flujo.auc(perfecto, np.array([1.0, 1.0, 0.0, 0.0])) == pytest.approx(0.0)
    assert np.isnan(flujo.auc(perfecto, np.array([1.0, 1.0, 1.0, 1.0])))


def test_el_desglose_por_hora_cubre_el_dia():
    df = serie_flujo(30000)
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df)
    modelo = flujo.entrenar(x.iloc[:20000], y.iloc[:20000])
    r = flujo.evaluar(modelo, x.iloc[20000:], y.iloc[20000:], df.index[20000:])
    assert not r["por_hora"].empty
    assert r["por_hora"]["auc"].between(0, 1).all()


def test_la_importancia_lista_todas_las_caracteristicas():
    df = serie_flujo(8000)
    x = flujo.construir(df)
    y, _ = flujo.objetivo(df)
    modelo = flujo.entrenar(x.iloc[:6000], y.iloc[:6000])
    imp = flujo.importancia(modelo)
    assert len(imp) == len(x.columns)
    assert imp["coeficiente"].abs().is_monotonic_decreasing
