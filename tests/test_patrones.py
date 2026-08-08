"""
Pruebas del descubrimiento de patrones.

Las dos que sostienen todo lo demás: que las dimensiones de régimen no miren
al futuro, y que sobre ruido puro el número de hallazgos coincida con lo que
predice el azar. Si lo segundo falla, cualquier lista de patrones que produzca
el módulo es basura.
"""

import numpy as np
import pandas as pd
import pytest

from backtest import patrones


def serie(n=60000, semilla=0, deriva=0.0):
    rng = np.random.default_rng(semilla)
    idx = pd.date_range("2025-01-01", periods=n, freq="10s", tz="UTC")
    cierre = 60000 * np.exp(np.cumsum(rng.normal(deriva, 0.0002, n)))
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    rango = cierre * rng.uniform(0.00005, 0.0005, n)
    volumen = rng.gamma(2.0, 1.5, n)
    return pd.DataFrame({
        "open": apertura, "high": np.maximum(apertura, cierre) + rango,
        "low": np.minimum(apertura, cierre) - rango, "close": cierre,
        "volume": volumen, "trades": rng.integers(5, 400, n).astype(float),
        "taker_buy": volumen * rng.beta(2, 2, n),
    }, index=idx)


# ========================
# CAUSALIDAD
# ========================

def test_las_dimensiones_no_miran_al_futuro():
    base = serie(40000)
    corte = 20000
    alterada = base.copy()
    for col in ("open", "high", "low", "close"):
        alterada.iloc[corte:, alterada.columns.get_loc(col)] *= 6
    for col in ("volume", "trades", "taker_buy"):
        alterada.iloc[corte:, alterada.columns.get_loc(col)] *= 30

    a, b = patrones.dimensiones(base), patrones.dimensiones(alterada)
    for col in a.columns:
        assert np.allclose(a[col].iloc[:corte], b[col].iloc[:corte], equal_nan=True), \
            f"{col} usa datos del futuro"


def test_los_tramos_de_regimen_son_relativos_a_la_ventana():
    """Multiplicar todo el volumen por mil no puede cambiar la clasificación."""
    df = serie(30000)
    escalado = df.copy()
    escalado["volume"] *= 1000
    escalado["taker_buy"] *= 1000
    a = patrones.dimensiones(df)["liquidez"]
    b = patrones.dimensiones(escalado)["liquidez"]
    assert np.allclose(a.dropna(), b.dropna())


def test_las_dimensiones_de_calendario_son_las_esperadas():
    df = serie(20000)
    d = patrones.dimensiones(df)
    assert (d["hora"] == df.index.hour).all()
    assert (d["finde"] == (df.index.dayofweek >= 5).astype(int)).all()
    assert set(d["liquidez"].dropna().unique()) <= {0, 1, 2}


# ========================
# CRUCE
# ========================

def test_el_cruce_respeta_el_minimo_de_episodios():
    df = serie(50000)
    d = patrones.dimensiones(df)
    laxo = patrones.cruzar(df, d, ["hora"], horizonte=360, min_episodios=1, por="D")
    estricto = patrones.cruzar(df, d, ["hora"], horizonte=360, min_episodios=1000, por="D")
    assert len(estricto) < len(laxo)


def test_los_episodios_no_son_velas():
    """El tamaño de muestra descuenta el solapamiento de las ventanas."""
    df = serie(50000)
    d = patrones.dimensiones(df)
    celdas = patrones.cruzar(df, d, ["finde"], horizonte=360, min_episodios=1, por="D")
    for c in celdas:
        assert c.episodios == pytest.approx(c.n / 360)
        assert c.episodios < c.n


def test_cruzar_varias_dimensiones_genera_mas_celdas():
    df = serie(60000)
    d = patrones.dimensiones(df)
    una = patrones.cruzar(df, d, ["hora"], horizonte=180, min_episodios=1, por="D")
    dos = patrones.cruzar(df, d, ["hora", "liquidez"], horizonte=180, min_episodios=1, por="D")
    assert len(dos) > len(una)


def test_el_acuerdo_se_mide_contra_el_signo_del_efecto():
    """Un patrón consistentemente negativo es tan patrón como uno positivo."""
    c = patrones.Celda(claves={"x": 1}, n=3600, episodios=10, efecto=-0.01,
                       periodos_positivos=1, periodos_total=10)
    assert c.acuerdo == pytest.approx(0.9)
    c2 = patrones.Celda(claves={"x": 1}, n=3600, episodios=10, efecto=0.01,
                        periodos_positivos=9, periodos_total=10)
    assert c2.acuerdo == pytest.approx(0.9)


# ========================
# REFERENCIA DE AZAR
# ========================

def test_sobre_ruido_los_hallazgos_no_superan_al_azar():
    """
    La prueba que valida el módulo entero. Sin estructura, el número de celdas
    consistentes tiene que quedarse en el entorno de lo que predice el azar.
    """
    df = serie(120000, semilla=11)
    d = patrones.dimensiones(df)
    celdas = patrones.cruzar(df, d, ["hora", "liquidez"], horizonte=360,
                             min_episodios=5, por="ME")
    if len(celdas) < 20:
        pytest.skip("muestra sintética insuficiente")
    t = patrones.tabla(celdas)
    hallazgos = (t["p"] <= 0.05).sum()
    azar = patrones.esperadas_por_azar(celdas, 0.05)
    assert hallazgos <= max(3 * azar, 5), \
        f"{hallazgos} hallazgos contra {azar:.1f} esperados: el módulo inventa estructura"


def test_el_azar_esperado_crece_con_el_numero_de_celdas():
    pocas = [patrones.Celda({"x": i}, 3600, 10, 0.0, 5, 10) for i in range(10)]
    muchas = [patrones.Celda({"x": i}, 3600, 10, 0.0, 5, 10) for i in range(100)]
    assert patrones.esperadas_por_azar(muchas) > patrones.esperadas_por_azar(pocas)


def test_el_mismo_acuerdo_pesa_mas_con_mas_periodos():
    """80 % de acuerdo sobre 10 períodos es anecdótico; sobre 50 es evidencia."""
    corta = patrones.Celda({"x": 1}, 3600, 10, 0.01, 8, 10)
    larga = patrones.Celda({"x": 1}, 3600, 10, 0.01, 40, 50)
    assert corta.acuerdo == pytest.approx(larga.acuerdo)
    assert larga.p_valor < corta.p_valor


def test_el_p_valor_en_los_extremos():
    unanime = patrones.Celda({"x": 1}, 3600, 10, 0.01, 20, 20)
    empate = patrones.Celda({"x": 1}, 3600, 10, 0.01, 10, 20)
    assert unanime.p_valor < 1e-5
    assert empate.p_valor == pytest.approx(1.0)


def test_el_resumen_avisa_cuando_no_hay_estructura():
    df = serie(80000, semilla=21)
    d = patrones.dimensiones(df)
    celdas = patrones.cruzar(df, d, ["hora"], horizonte=360, min_episodios=3, por="D")
    texto = patrones.resumen(celdas)
    assert "azar" in texto


def test_el_resumen_no_revienta_sin_celdas():
    assert "Ninguna" in patrones.resumen([])


# ========================
# CONTROL POSITIVO
# ========================

def test_una_estructura_inyectada_aparece_como_consistente():
    """
    Si a una hora concreta se le mete deriva positiva de verdad, esa celda
    tiene que salir con acuerdo alto en todos los períodos.
    """
    rng = np.random.default_rng(5)
    n = 200000
    idx = pd.date_range("2025-01-01", periods=n, freq="10s", tz="UTC")
    pasos = rng.normal(0, 0.0002, n)
    # Las 03:00 UTC suben siempre, mes tras mes.
    pasos[idx.hour == 3] += 0.0006
    cierre = 60000 * np.exp(np.cumsum(pasos))
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    volumen = rng.gamma(2.0, 1.5, n)
    df = pd.DataFrame({
        "open": apertura, "high": np.maximum(apertura, cierre) * 1.0001,
        "low": np.minimum(apertura, cierre) * 0.9999, "close": cierre,
        "volume": volumen, "trades": rng.integers(5, 400, n).astype(float),
        "taker_buy": volumen * rng.beta(2, 2, n),
    }, index=idx)

    d = patrones.dimensiones(df)
    celdas = patrones.cruzar(df, d, ["hora"], horizonte=180, min_episodios=3, por="D")
    t = patrones.tabla(celdas)
    fila = t[t["hora"] == 3].iloc[0]
    assert fila["efecto"] > 0
    assert fila["acuerdo"] >= 0.8, "no detectó una estructura que existe"
