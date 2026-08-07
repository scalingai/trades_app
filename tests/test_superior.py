"""
Pruebas del contexto semanal.

Todas giran alrededor de lo mismo: que ninguna característica use información
posterior a la vela en que se evalúa. Es el error que hace que un backtest
multi-timeframe dé resultados fantásticos y completamente falsos, y no se
detecta mirando la curva de capital: hay que provocarlo.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.motor import Datos
from backtest.superior import ContextoSemanal, disponibles


def serie_horaria(semanas=30, semilla=0):
    """Serie horaria que arranca un lunes, para que las semanas queden enteras."""
    n = semanas * 7 * 24
    rng = np.random.default_rng(semilla)
    fechas = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")  # lunes
    cierre = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    rango = cierre * rng.uniform(0.001, 0.01, n)
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    return Datos(
        fechas=fechas.to_numpy(), open=apertura,
        high=np.maximum(apertura, cierre) + rango,
        low=np.minimum(apertura, cierre) - rango,
        close=cierre, volume=np.ones(n), intervalo="1h",
    )


def test_ninguna_caracteristica_mira_al_futuro():
    """
    Se altera brutalmente la segunda mitad de la serie. Ningún valor de la
    primera mitad puede cambiar: si cambia, esa característica está leyendo
    velas que en ese momento no habían ocurrido.
    """
    base = serie_horaria(30)
    corte = len(base) // 2

    alterada = Datos(
        fechas=base.fechas, open=base.open.copy(), high=base.high.copy(),
        low=base.low.copy(), close=base.close.copy(), volume=base.volume,
        intervalo=base.intervalo,
    )
    for campo in ("open", "high", "low", "close"):
        getattr(alterada, campo)[corte:] *= 7

    ctx_a, ctx_b = ContextoSemanal(base), ContextoSemanal(alterada)
    for nombre in disponibles():
        a = ctx_a.calcular(nombre, 4)
        b = ctx_b.calcular(nombre, 4)
        # Se compara hasta el inicio de la semana del corte: dentro de esa
        # semana los acumulados sí incorporan velas ya alteradas, y deben.
        semana_corte = ctx_a._codigos[corte]
        hasta = int(np.flatnonzero(ctx_a._codigos == semana_corte)[0])
        assert np.allclose(a[:hasta], b[:hasta], equal_nan=True), \
            f"{nombre} usa datos del futuro"


def test_el_cierre_semanal_anterior_no_es_el_de_la_semana_en_curso():
    """
    La comprobación que más veces se hace mal: dentro de una semana, el
    'cierre semanal' tiene que ser el de la semana ANTERIOR, no el de ésta.
    """
    datos = serie_horaria(10)
    ctx = ContextoSemanal(datos)
    valores = ctx.calcular("sem_ant_close")
    codigos = ctx._codigos

    for semana in range(2, int(codigos.max()) + 1):
        velas = np.flatnonzero(codigos == semana)
        cierre_previo = ctx._ohlc["close"][semana - 1]
        cierre_propio = ctx._ohlc["close"][semana]
        assert np.allclose(valores[velas], cierre_previo)
        if not np.isclose(cierre_previo, cierre_propio):
            assert not np.allclose(valores[velas], cierre_propio)


def test_la_primera_semana_no_tiene_datos_previos():
    datos = serie_horaria(5)
    ctx = ContextoSemanal(datos)
    primera = np.flatnonzero(ctx._codigos == 0)
    assert np.isnan(ctx.calcular("sem_ant_close")[primera]).all()
    assert np.isnan(ctx.calcular("sem_pivote")[primera]).all()


def test_la_apertura_semanal_es_constante_dentro_de_la_semana():
    datos = serie_horaria(8)
    ctx = ContextoSemanal(datos)
    apertura = ctx.calcular("sem_open")
    for semana in range(int(ctx._codigos.max()) + 1):
        velas = np.flatnonzero(ctx._codigos == semana)
        assert np.allclose(apertura[velas], apertura[velas[0]])
        assert apertura[velas[0]] == datos.open[velas[0]]


def test_los_extremos_de_la_semana_en_curso_son_acumulados():
    """El máximo hasta ahora nunca decrece dentro de la semana y reinicia al cambiar."""
    datos = serie_horaria(6)
    ctx = ContextoSemanal(datos)
    maximo = ctx.calcular("sem_high_hasta")
    minimo = ctx.calcular("sem_low_hasta")

    for semana in range(int(ctx._codigos.max()) + 1):
        velas = np.flatnonzero(ctx._codigos == semana)
        assert np.all(np.diff(maximo[velas]) >= -1e-9)      # no decrece
        assert np.all(np.diff(minimo[velas]) <= 1e-9)       # no crece
        assert maximo[velas[0]] == datos.high[velas[0]]     # reinicia cada semana
        assert maximo[velas[-1]] == datos.high[velas].max()
        assert np.all(maximo[velas] >= minimo[velas])


def test_el_maximo_acumulado_nunca_supera_al_maximo_real_de_la_semana():
    datos = serie_horaria(6)
    ctx = ContextoSemanal(datos)
    maximo = ctx.calcular("sem_high_hasta")
    for semana in range(int(ctx._codigos.max()) + 1):
        velas = np.flatnonzero(ctx._codigos == semana)
        assert maximo[velas].max() <= datos.high[velas].max() + 1e-9


def test_el_pivote_sale_de_la_semana_anterior():
    datos = serie_horaria(8)
    ctx = ContextoSemanal(datos)
    pivote = ctx.calcular("sem_pivote")
    semana = 4
    velas = np.flatnonzero(ctx._codigos == semana)
    esperado = (ctx._ohlc["high"][semana - 1] + ctx._ohlc["low"][semana - 1]
                + ctx._ohlc["close"][semana - 1]) / 3
    assert pivote[velas] == pytest.approx(esperado)


def test_r1_por_encima_del_pivote_y_s1_por_debajo():
    datos = serie_horaria(8)
    ctx = ContextoSemanal(datos)
    pivote = ctx.calcular("sem_pivote")
    valido = ~np.isnan(pivote)
    assert np.all(ctx.calcular("sem_r1")[valido] >= pivote[valido])
    assert np.all(ctx.calcular("sem_s1")[valido] <= pivote[valido])


def test_la_media_semanal_solo_usa_semanas_cerradas():
    datos = serie_horaria(20)
    ctx = ContextoSemanal(datos)
    media = ctx.calcular("sem_sma", 4)
    semana = 10
    velas = np.flatnonzero(ctx._codigos == semana)
    # Media de las 4 semanas cerradas anteriores: 6,7,8,9. La 10 no entra.
    esperado = ctx._ohlc["close"][semana - 4:semana].mean()
    assert media[velas] == pytest.approx(esperado)


def test_la_posicion_en_el_rango_semanal_esta_normalizada():
    datos = serie_horaria(10)
    ctx = ContextoSemanal(datos)
    pos = ctx.calcular("sem_pos_semana")
    valido = ~np.isnan(pos)
    # Dentro de la semana en curso el precio siempre está en su propio rango.
    assert np.all(pos[valido] >= -1e-6) and np.all(pos[valido] <= 100 + 1e-6)


def test_todas_las_caracteristicas_devuelven_el_largo_de_la_serie():
    datos = serie_horaria(6)
    ctx = ContextoSemanal(datos)
    for nombre in disponibles():
        assert len(ctx.calcular(nombre, 4)) == len(datos)


def test_el_contexto_semanal_cachea():
    ctx = ContextoSemanal(serie_horaria(4))
    primera = ctx.calcular("sem_pivote")
    assert ctx.calcular("sem_pivote") is primera


def test_funciona_aunque_la_serie_no_empiece_en_lunes():
    """Los datos reales empiezan cualquier día; la primera semana es parcial."""
    n = 24 * 40
    fechas = pd.date_range("2024-01-04", periods=n, freq="h", tz="UTC")   # jueves
    precios = np.linspace(100, 200, n)
    datos = Datos(fechas.to_numpy(), precios, precios + 1, precios - 1,
                  precios, np.ones(n), "1h")
    ctx = ContextoSemanal(datos)
    assert len(ctx.calcular("sem_ant_close")) == n
    assert np.diff(ctx._codigos).min() >= 0        # los códigos no retroceden
