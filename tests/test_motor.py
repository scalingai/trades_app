"""
Pruebas del motor de backtesting.

Un motor con un off-by-one o con sesgo de anticipación no da resultados
"algo optimistas": da resultados inventados. Estas pruebas fijan las
convenciones de ejecución sobre series construidas a mano, donde el resultado
correcto se puede calcular a mano.
"""

import numpy as np
import pytest

from backtest import metricas
from backtest.motor import Config, Datos, Senales, ejecutar


def serie(precios, altos=None, bajos=None, aperturas=None):
    """Serie sintética; por defecto O=H=L=C para que no haya recorrido intrabarra."""
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    return Datos(
        fechas=np.arange(n),
        open=np.asarray(aperturas, dtype=float) if aperturas is not None else precios.copy(),
        high=np.asarray(altos, dtype=float) if altos is not None else precios.copy(),
        low=np.asarray(bajos, dtype=float) if bajos is not None else precios.copy(),
        close=precios,
        volume=np.ones(n),
        intervalo="1d",
    )


def marcas(n, indices):
    m = np.zeros(n, dtype=bool)
    for i in indices:
        m[i] = True
    return m


SIN_COSTES = Config(comision=0.0, slippage=0.0, capital=1000.0)


# ========================
# EJECUCIÓN Y ANTICIPACIÓN
# ========================

def test_entrada_en_la_apertura_siguiente_a_la_senal():
    """La señal de la barra t se ejecuta en la apertura de t+1, nunca en la t."""
    datos = serie([100, 110, 120, 130, 140])
    senales = Senales(entrada_larga=marcas(5, [1]), salida_larga=marcas(5, [3]))
    res = ejecutar(datos, senales, SIN_COSTES)

    assert res.n_operaciones == 1
    assert res.entrada_idx[0] == 2          # señal en 1 -> entra en 2
    assert res.precio_entrada[0] == 120
    assert res.salida_idx[0] == 4           # señal de salida en 3 -> sale en 4
    assert res.precio_salida[0] == 140


def test_no_usa_el_precio_de_la_barra_de_la_senal():
    """
    Si sólo cambia el cierre de la barra que dispara la señal, el resultado no
    puede moverse: el motor no debe haber mirado ese precio para operar.
    """
    senales = Senales(entrada_larga=marcas(5, [1]), salida_larga=marcas(5, [3]))
    base = ejecutar(serie([100, 110, 120, 130, 140]), senales, SIN_COSTES)
    alterada = ejecutar(serie([100, 999, 120, 130, 140]), senales, SIN_COSTES)
    assert base.retorno[0] == pytest.approx(alterada.retorno[0])


def test_no_reentra_antes_de_cerrar_la_posicion():
    """Con la señal de entrada activa en todas las barras, no puede haber solape."""
    datos = serie(list(range(100, 140)))
    senales = Senales(entrada_larga=np.ones(40, dtype=bool), salida_larga=marcas(40, [5, 20]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.n_operaciones >= 2
    assert np.all(res.entrada_idx[1:] >= res.salida_idx[:-1])
    assert np.all(res.salida_idx >= res.entrada_idx)


# ========================
# STOP Y OBJETIVO
# ========================

def test_stop_salta_al_precio_del_stop():
    """Con el mínimo perforando el stop, se sale al precio del stop, no al cierre."""
    datos = serie(precios=[100, 100, 100, 100], bajos=[100, 100, 100, 80])
    senales = Senales(entrada_larga=marcas(4, [0]), dist_stop=np.full(4, 10.0))
    res = ejecutar(datos, senales, SIN_COSTES)

    assert res.n_operaciones == 1
    assert res.precio_entrada[0] == 100
    assert res.precio_salida[0] == 90            # 100 - 10
    assert res.retorno[0] == pytest.approx(-0.10)


def test_objetivo_salta_al_precio_del_objetivo():
    datos = serie(precios=[100, 100, 100, 100], altos=[100, 100, 100, 130])
    senales = Senales(entrada_larga=marcas(4, [0]), dist_objetivo=np.full(4, 20.0))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.precio_salida[0] == 120
    assert res.retorno[0] == pytest.approx(0.20)


def test_stop_gana_al_objetivo_en_la_misma_barra():
    """No se sabe cuál se tocó antes dentro de la barra: se asume el peor caso."""
    datos = serie(precios=[100, 100], altos=[100, 150], bajos=[100, 50])
    senales = Senales(entrada_larga=marcas(2, [0]),
                      dist_stop=np.full(2, 10.0), dist_objetivo=np.full(2, 20.0))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.precio_salida[0] == 90
    assert res.retorno[0] < 0


def test_hueco_de_apertura_ejecuta_peor_que_el_stop():
    """Si la vela abre por debajo del stop, se sale a la apertura real."""
    datos = serie(precios=[100, 100, 70], altos=[100, 100, 75],
                  bajos=[100, 100, 65], aperturas=[100, 100, 70])
    senales = Senales(entrada_larga=marcas(3, [0]), dist_stop=np.full(3, 10.0))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.precio_entrada[0] == 100
    assert res.precio_salida[0] == 70            # no 90: el hueco se saltó el stop
    assert res.retorno[0] == pytest.approx(-0.30)


def test_la_senal_manda_sobre_el_stop_de_la_misma_barra():
    """La apertura ocurre antes que el recorrido de la barra."""
    datos = serie(precios=[100, 100, 100], bajos=[100, 100, 50], aperturas=[100, 100, 100])
    senales = Senales(entrada_larga=marcas(3, [0]), salida_larga=marcas(3, [1]),
                      dist_stop=np.full(3, 10.0))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.precio_salida[0] == 100           # salida por señal en la apertura
    assert res.motivo[0] == 0                    # SENAL


def test_max_barras_cierra_la_posicion():
    datos = serie(list(range(100, 120)))
    senales = Senales(entrada_larga=marcas(20, [0]))
    res = ejecutar(datos, senales, Config(comision=0, slippage=0, max_barras=5))
    assert res.salida_idx[0] - res.entrada_idx[0] == 5


def test_posicion_abierta_al_final_se_cierra_con_el_ultimo_cierre():
    datos = serie([100, 110, 120])
    senales = Senales(entrada_larga=marcas(3, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.salida_idx[0] == 2
    assert res.precio_salida[0] == 120
    assert res.motivo[0] == 4                    # FIN_DATOS


# ========================
# CORTOS
# ========================

def test_corto_gana_cuando_el_precio_baja():
    datos = serie([100, 100, 80])
    senales = Senales(entrada_larga=np.zeros(3, dtype=bool), entrada_corta=marcas(3, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.direccion[0] == -1
    assert res.retorno[0] == pytest.approx(0.20)


def test_stop_de_corto_salta_hacia_arriba():
    datos = serie(precios=[100, 100, 100], altos=[100, 100, 130])
    senales = Senales(entrada_larga=np.zeros(3, dtype=bool), entrada_corta=marcas(3, [0]),
                      dist_stop=np.full(3, 10.0))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.precio_salida[0] == 110
    assert res.retorno[0] == pytest.approx(-0.10)


def test_el_corto_no_puede_ganar_mas_del_100_por_ciento():
    """Aunque el precio se vaya a casi cero, un corto a 1x gana como mucho el nominal."""
    datos = serie([100, 100, 0.01])
    senales = Senales(entrada_larga=np.zeros(3, dtype=bool), entrada_corta=marcas(3, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.retorno[0] < 1.0
    assert res.retorno[0] == pytest.approx(0.9999)


def test_el_corto_se_arruina_si_el_precio_se_duplica():
    datos = serie([100, 100, 200])
    senales = Senales(entrada_larga=np.zeros(3, dtype=bool), entrada_corta=marcas(3, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.retorno[0] == pytest.approx(-1.0)


def test_cortos_desactivados_se_ignoran():
    datos = serie([100, 100, 80])
    senales = Senales(entrada_larga=np.zeros(3, dtype=bool), entrada_corta=marcas(3, [0]))
    res = ejecutar(datos, senales, Config(permitir_cortos=False))
    assert res.n_operaciones == 0


# ========================
# COSTES
# ========================

def test_los_costes_se_cobran_en_los_dos_lados():
    datos = serie([100, 100, 100])
    senales = Senales(entrada_larga=marcas(3, [0]))
    config = Config(comision=0.001, slippage=0.0, capital=1000.0)
    res = ejecutar(datos, senales, config)
    # Precio plano: la pérdida es exactamente el coste de entrar y salir.
    esperado = (100 * 0.999) / (100 * 1.001) - 1
    assert res.retorno[0] == pytest.approx(esperado)
    assert res.retorno[0] < 0


def test_mas_costes_nunca_mejoran_el_resultado():
    rng = np.random.default_rng(7)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    datos = serie(precios)
    entradas = np.zeros(400, dtype=bool); entradas[::20] = True
    salidas = np.zeros(400, dtype=bool); salidas[10::20] = True
    senales = Senales(entrada_larga=entradas, salida_larga=salidas)

    barato = ejecutar(datos, senales, Config(comision=0.0001, slippage=0.0))
    caro = ejecutar(datos, senales, Config(comision=0.005, slippage=0.0))
    assert caro.equity[-1] < barato.equity[-1]


# ========================
# COHERENCIA GLOBAL
# ========================

def test_siempre_dentro_equivale_a_comprar_y_mantener():
    """Una posición larga única sin costes tiene que replicar el buy & hold."""
    rng = np.random.default_rng(3)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    datos = serie(precios)
    senales = Senales(entrada_larga=marcas(500, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)

    esperado = precios[-1] / precios[1] - 1      # entra en la apertura de la barra 1
    assert res.retorno[0] == pytest.approx(esperado)
    m = metricas.calcular(res, "1d", 1000.0)
    assert m["retorno_total"] == pytest.approx(esperado)


def test_el_capital_compone_entre_operaciones():
    datos = serie([100, 100, 200, 200, 100])
    #        entra en 1 (100), sale en 2 (200) -> +100 %
    #        entra en 3 (200), sale en 4 (100) -> -50 %
    senales = Senales(entrada_larga=marcas(5, [0, 2]), salida_larga=marcas(5, [1, 3]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.n_operaciones == 2
    assert res.retorno[0] == pytest.approx(1.0)
    assert res.retorno[1] == pytest.approx(-0.5)
    assert res.equity[-1] == pytest.approx(1000.0)      # 1000 * 2 * 0,5


def test_la_curva_de_capital_marca_a_mercado_dentro_de_la_operacion():
    """El drawdown tiene que recoger la caída aunque la operación acabe en verde."""
    datos = serie([100, 100, 50, 120])
    senales = Senales(entrada_larga=marcas(4, [0]))
    res = ejecutar(datos, senales, SIN_COSTES)
    assert res.retorno[0] > 0
    assert metricas.max_drawdown(res.equity) == pytest.approx(0.5)


def test_sin_senales_no_hay_operaciones():
    datos = serie([100, 101, 102])
    res = ejecutar(datos, Senales(entrada_larga=np.zeros(3, dtype=bool)), SIN_COSTES)
    assert res.n_operaciones == 0
    assert res.equity[-1] == SIN_COSTES.capital
    m = metricas.calcular(res, "1d", SIN_COSTES.capital)
    assert m["n_operaciones"] == 0 and m["retorno_total"] == 0.0
