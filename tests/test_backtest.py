"""
Pruebas de indicadores, métricas, optimizador, Monte Carlo y generador.

Las del motor van aparte, en test_motor.py.
"""

import numpy as np
import pytest

from backtest import generador, indicadores as ind, metricas, montecarlo, optimizar
from backtest.motor import Config, Datos, Senales, ejecutar


def serie_sintetica(n=1200, semilla=0, deriva=0.0003, vol=0.02):
    """Paseo aleatorio con estructura OHLC coherente."""
    rng = np.random.default_rng(semilla)
    cierre = 100 * np.exp(np.cumsum(rng.normal(deriva, vol, n)))
    rango = cierre * rng.uniform(0.002, 0.02, n)
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    return Datos(
        fechas=np.arange(n), open=apertura,
        high=np.maximum(apertura, cierre) + rango,
        low=np.minimum(apertura, cierre) - rango,
        close=cierre, volume=np.ones(n), intervalo="1d",
    )


# ========================
# INDICADORES
# ========================

def test_sma_valores_conocidos():
    r = ind.sma([1, 2, 3, 4, 5], 3)
    assert np.isnan(r[:2]).all()
    assert r[2:] == pytest.approx([2, 3, 4])


def test_rsi_es_100_en_serie_solo_alcista():
    r = ind.rsi(np.arange(1, 60, dtype=float), 14)
    assert r[-1] == pytest.approx(100.0)


def test_rsi_es_0_en_serie_solo_bajista():
    r = ind.rsi(np.arange(60, 1, -1, dtype=float), 14)
    assert r[-1] == pytest.approx(0.0)


def test_maximo_y_minimo_moviles():
    assert ind.maximo_movil([1, 5, 3, 2, 8], 3)[2:] == pytest.approx([5, 5, 8])
    assert ind.minimo_movil([1, 5, 3, 2, 8], 3)[2:] == pytest.approx([1, 2, 2])


def test_cruces_detectan_el_cambio_de_lado():
    a = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    b = np.full(5, 2.5)
    assert ind.cruza_arriba(a, b).tolist() == [False, False, True, False, False]
    assert ind.cruza_abajo(a, b).tolist() == [False, False, False, True, False]


def test_indicadores_no_miran_al_futuro():
    """
    Cambiar el final de la serie no puede alterar el valor de un indicador en
    una barra anterior. Es la comprobación que descarta el error más caro.
    """
    base = np.linspace(100, 200, 300)
    alterada = base.copy()
    alterada[200:] *= 3

    for nombre in ("sma", "ema", "wma", "rsi", "roc", "macd", "bollinger_sup", "maximo"):
        a = ind.calcular(nombre, {"close": base, "high": base, "low": base}, 20)
        b = ind.calcular(nombre, {"close": alterada, "high": alterada, "low": alterada}, 20)
        iguales = np.isclose(a[:200], b[:200], equal_nan=True)
        assert iguales.all(), f"{nombre} usa datos posteriores a la barra evaluada"


def test_el_contexto_cachea():
    datos = serie_sintetica(300)
    ctx = ind.Contexto(datos)
    primera = ctx.ind("sma", 20)
    assert ctx.ind("sma", 20) is primera          # misma instancia: vino de la caché
    assert ctx.ind("sma", 21) is not primera


# ========================
# MÉTRICAS
# ========================

def test_max_drawdown_conocido():
    assert metricas.max_drawdown(np.array([100, 120, 60, 90])) == pytest.approx(0.5)
    assert metricas.max_drawdown(np.array([100, 110, 120])) == 0.0


def test_estabilidad_maxima_en_crecimiento_exponencial_puro():
    equity = np.exp(np.linspace(0, 2, 200))       # recta perfecta en logaritmos
    assert metricas.estabilidad(equity) == pytest.approx(1.0)


def test_estabilidad_baja_cuando_todo_viene_de_un_salto():
    equity = np.concatenate([np.full(100, 100.0), np.full(100, 300.0)])
    assert metricas.estabilidad(equity) < 0.8


def test_racha_perdedora():
    assert metricas.racha_perdedora(np.array([1, -1, -1, -1, 1, -1])) == 3


def test_barras_por_anio():
    assert metricas.barras_por_anio("1d") == pytest.approx(365.25)
    assert metricas.barras_por_anio("1h") == pytest.approx(365.25 * 24)


# ========================
# OPTIMIZADOR
# ========================

def test_combinaciones_cubre_el_producto_cartesiano():
    combos = optimizar.combinaciones({"a": [1, 2, 3], "b": ["x", "y"]})
    assert len(combos) == 6
    assert {"a": 2, "b": "y"} in combos


def test_particion_no_solapa_y_cubre_toda_la_serie():
    datos = serie_sintetica(1000)
    p = optimizar.partir(datos, 0.3)
    assert len(p.entrenamiento) == 700
    assert len(p.validacion) == 300
    # La primera barra de validación es la siguiente a la última de ajuste.
    assert p.validacion.close[0] == datos.close[700]
    assert p.entrenamiento.close[-1] == datos.close[699]


def test_el_grid_evalua_los_dos_tramos_por_separado():
    datos = serie_sintetica(1500, semilla=5)
    espacio = {"rapida": [5, 10], "lenta": [30, 50], "tipo": ["sma"]}
    tabla = optimizar.grid(datos, "cruce_medias", espacio=espacio, min_operaciones=1)

    assert len(tabla) == 4
    assert {"is_cagr", "oos_cagr", "is_fitness", "oos_fitness"} <= set(tabla.columns)
    # El orden lo manda el fitness in-sample; el out-of-sample no interviene.
    utiles = tabla[~tabla["descartada"]]
    assert utiles["is_fitness"].is_monotonic_decreasing


def test_el_grid_descarta_combinaciones_incoherentes():
    """cruce_medias devuelve None si la media rápida no es más rápida."""
    datos = serie_sintetica(800)
    tabla = optimizar.grid(datos, "cruce_medias",
                           espacio={"rapida": [50], "lenta": [10], "tipo": ["sma"]},
                           min_operaciones=1)
    assert tabla.empty


def test_buscar_mejor_respeta_el_minimo_de_operaciones():
    datos = serie_sintetica(1200, semilla=9)
    espacio = {"rapida": [5, 20], "lenta": [50, 100], "tipo": ["sma"]}
    params, m = optimizar.buscar_mejor(datos, "cruce_medias", espacio=espacio,
                                       min_operaciones=10_000)
    assert params is None and m is None


# ========================
# MONTE CARLO
# ========================

def _resultado_de_prueba(semilla=0):
    datos = serie_sintetica(1500, semilla=semilla)
    rng = np.random.default_rng(semilla)
    entradas = np.zeros(len(datos), dtype=bool)
    entradas[rng.choice(len(datos) - 2, 120, replace=False)] = True
    salidas = np.zeros(len(datos), dtype=bool)
    salidas[5::12] = True
    return ejecutar(datos, Senales(entrada_larga=entradas, salida_larga=salidas), Config())


def test_barajar_no_cambia_el_retorno_final():
    """
    El producto de los retornos no depende del orden, así que barajar sólo
    puede mover el drawdown. Si el retorno variase, la simulación estaría mal.
    """
    res = _resultado_de_prueba()
    mc = montecarlo.sobre_operaciones(res, n=200, tipo="barajar", capital=10_000.0)
    assert mc.retornos.std() == pytest.approx(0.0, abs=1e-9)
    assert mc.drawdowns.std() > 0


def test_remuestrear_si_cambia_el_retorno():
    res = _resultado_de_prueba()
    mc = montecarlo.sobre_operaciones(res, n=300, tipo="remuestrear", capital=10_000.0)
    assert mc.retornos.std() > 0


def test_el_slippage_extra_siempre_empeora():
    res = _resultado_de_prueba()
    base = res.equity[-1] / 10_000.0 - 1
    mc = montecarlo.sobre_operaciones(res, n=200, tipo="slippage",
                                      slippage_extra=0.001, capital=10_000.0)
    assert mc.retornos.max() < base


def test_montecarlo_sin_operaciones_no_revienta():
    datos = serie_sintetica(100)
    res = ejecutar(datos, Senales(entrada_larga=np.zeros(100, dtype=bool)), Config())
    mc = montecarlo.sobre_operaciones(res, n=50, tipo="barajar")
    assert mc.n == 0


# ========================
# GENERADOR
# ========================

def test_la_misma_semilla_da_el_mismo_banco():
    datos = serie_sintetica(1500, semilla=11)
    kwargs = dict(poblacion=12, generaciones=3, min_operaciones=5, verboso=False)
    a = generador.evolucionar(datos, semilla=7, **kwargs)
    b = generador.evolucionar(datos, semilla=7, **kwargs)
    assert [c.huella for c in a] == [c.huella for c in b]


def test_los_genomas_generados_no_comparan_un_operando_consigo_mismo():
    rng = np.random.default_rng(3)
    for _ in range(400):
        g = generador.mutar(generador.genoma_aleatorio(rng), rng)
        for c in list(g.entrada) + list(g.salida):
            assert c["izq"] != c["der"]


def test_los_genomas_generados_siempre_tienen_entrada_y_stop():
    rng = np.random.default_rng(4)
    for _ in range(200):
        g = generador.genoma_aleatorio(rng)
        assert len(g.entrada) >= 1
        assert g.stop_atr > 0          # sin stop, la evolución premia no cerrar nunca


def test_solo_se_comparan_operandos_de_la_misma_escala():
    """Comparar un RSI con una media móvil no significa nada."""
    def escala(op):
        if op["clase"] == "indicador":
            return generador.BLOQUES[op["nombre"]]["escala"]
        return "precio" if op["clase"] == "precio" else None

    rng = np.random.default_rng(5)
    for _ in range(400):
        g = generador.mutar(generador.genoma_aleatorio(rng), rng)
        for c in list(g.entrada) + list(g.salida):
            izq, der = escala(c["izq"]), escala(c["der"])
            if izq and der:
                assert izq == der, f"compara {izq} con {der}"


def test_el_canonico_iguala_genomas_equivalentes():
    """Con una sola condición, el operador lógico no cambia el comportamiento."""
    condicion = {"izq": {"clase": "precio", "campo": "close"}, "op": ">",
                 "der": {"clase": "indicador", "nombre": "sma", "periodo": 50}}
    a = generador.Genoma(entrada=[condicion], logico_entrada="y")
    b = generador.Genoma(entrada=[condicion], logico_entrada="o")
    assert a.huella() == b.huella()


def test_el_canonico_ignora_el_orden_de_las_condiciones():
    c1 = {"izq": {"clase": "precio", "campo": "close"}, "op": ">",
          "der": {"clase": "indicador", "nombre": "sma", "periodo": 50}}
    c2 = {"izq": {"clase": "indicador", "nombre": "rsi", "periodo": 14}, "op": "<",
          "der": {"clase": "constante", "valor": 30.0}}
    a = generador.Genoma(entrada=[c1, c2], logico_entrada="y")
    b = generador.Genoma(entrada=[c2, c1], logico_entrada="y")
    assert a.huella() == b.huella()


def test_el_canonico_distingue_genomas_distintos():
    c1 = {"izq": {"clase": "precio", "campo": "close"}, "op": ">",
          "der": {"clase": "indicador", "nombre": "sma", "periodo": 50}}
    a = generador.Genoma(entrada=[c1], stop_atr=2.0)
    b = generador.Genoma(entrada=[c1], stop_atr=3.0)
    assert a.huella() != b.huella()


def test_el_lado_corto_es_el_reflejo_del_largo():
    datos = serie_sintetica(600, semilla=2)
    ctx = ind.Contexto(datos)
    condicion = {"izq": {"clase": "precio", "campo": "close"}, "op": ">",
                 "der": {"clase": "indicador", "nombre": "sma", "periodo": 20}}
    senales = generador.senales_de(generador.Genoma(entrada=[condicion]), ctx)
    media = ctx.ind("sma", 20)
    valido = ~np.isnan(media)
    # Donde hay dato, largo y corto son excluyentes y cubren todos los casos.
    assert not (senales.entrada_larga & senales.entrada_corta)[valido].any()
    assert (senales.entrada_larga | senales.entrada_corta)[valido].all()


def test_el_genoma_va_y_vuelve_de_json():
    rng = np.random.default_rng(6)
    g = generador.genoma_aleatorio(rng)
    assert generador.Genoma.desde_dict(g.como_dict()).huella() == g.huella()


def test_la_evolucion_solo_ve_el_tramo_in_sample():
    """
    Cambiar únicamente el tramo out-of-sample no puede alterar el banco que
    produce la evolución: si lo alterara, la validación estaría contaminada.
    """
    datos = serie_sintetica(1600, semilla=13)
    alterados = Datos(
        fechas=datos.fechas, open=datos.open.copy(), high=datos.high.copy(),
        low=datos.low.copy(), close=datos.close.copy(), volume=datos.volume,
        intervalo=datos.intervalo,
    )
    corte = int(len(datos) * 0.7)
    for campo in ("open", "high", "low", "close"):
        getattr(alterados, campo)[corte:] *= 5      # sólo el out-of-sample

    kwargs = dict(poblacion=12, generaciones=3, min_operaciones=5,
                  fraccion_oos=0.3, semilla=21, verboso=False)
    a = generador.evolucionar(datos, **kwargs)
    b = generador.evolucionar(alterados, **kwargs)
    assert [c.huella for c in a] == [c.huella for c in b]
    assert [c.fitness_is for c in a] == pytest.approx([c.fitness_is for c in b])
