"""
Pruebas del modo intradía de ratio 1:1 y de las métricas de efectividad.

Con ratio fijo el win rate deja de ser una curiosidad y pasa a ser lo único
que decide, así que tiene que estar bien medido y bien comparado contra el
umbral que imponen los costes.
"""

import numpy as np
import pandas as pd
import pytest

from backtest import generador, metricas
from backtest.indicadores import Contexto
from backtest.motor import Config, Datos, Senales, ejecutar


def serie(n=6000, semilla=0):
    rng = np.random.default_rng(semilla)
    fechas = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    cierre = 40000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    rango = cierre * rng.uniform(0.0005, 0.004, n)
    apertura = np.concatenate(([cierre[0]], cierre[:-1]))
    return Datos(fechas.to_numpy(), apertura,
                 np.maximum(apertura, cierre) + rango,
                 np.minimum(apertura, cierre) - rango,
                 cierre, np.ones(n), "15m")


# ========================
# MÉTRICAS DE EFECTIVIDAD
# ========================

def test_wilson_penaliza_la_muestra_corta():
    """El mismo 65 % vale mucho menos con 20 operaciones que con 500."""
    corta = metricas.wilson_inferior(13, 20)
    larga = metricas.wilson_inferior(325, 500)
    assert corta < larga
    assert corta < 0.50 < larga           # con 20 ni siquiera se distingue de una moneda


def test_wilson_converge_al_win_rate_con_muchas_operaciones():
    assert metricas.wilson_inferior(6000, 10000) == pytest.approx(0.60, abs=0.02)


def test_wilson_sin_operaciones_es_cero():
    assert metricas.wilson_inferior(0, 0) == 0.0


def test_equilibrio_es_50_por_ciento_en_un_uno_a_uno_sin_costes():
    retornos = np.array([0.01, -0.01, 0.01, -0.01, 0.01])
    assert metricas.win_rate_equilibrio(retornos) == pytest.approx(0.5)


def test_los_costes_empujan_el_equilibrio_por_encima_del_50():
    """Ganar 0,94 % y perder 1,06 % (stop 1 % con 0,12 % de coste) pide 53 %."""
    retornos = np.array([0.0094, -0.0106, 0.0094, -0.0106])
    assert metricas.win_rate_equilibrio(retornos) == pytest.approx(0.53, abs=0.005)


def test_el_equilibrio_baja_si_las_ganancias_son_mayores():
    """Con ratio 2:1 basta con acertar un tercio de las veces."""
    retornos = np.array([0.02, -0.01, 0.02, -0.01])
    assert metricas.win_rate_equilibrio(retornos) == pytest.approx(1 / 3, abs=0.01)


def test_equilibrio_indefinido_sin_ganadoras_o_sin_perdedoras():
    assert np.isnan(metricas.win_rate_equilibrio(np.array([0.01, 0.02])))
    assert np.isnan(metricas.win_rate_equilibrio(np.array([-0.01, -0.02])))


def test_el_margen_de_acierto_aparece_en_las_metricas():
    datos = serie(3000)
    rng = np.random.default_rng(1)
    entradas = np.zeros(len(datos), dtype=bool)
    entradas[rng.choice(len(datos) - 2, 200, replace=False)] = True
    atr = Contexto(datos).ind("atr", 14)
    res = ejecutar(datos, Senales(entrada_larga=entradas, dist_stop=atr * 2,
                                  dist_objetivo=atr * 2), Config())
    m = metricas.calcular(res, "15m")
    assert m["margen_acierto"] == pytest.approx(m["win_rate"] - m["win_rate_equilibrio"])
    assert 0 <= m["win_rate_inf"] <= m["win_rate"]


# ========================
# MODO BRACKET 1:1
# ========================

def test_el_modo_bracket_iguala_objetivo_y_stop():
    opciones = generador.Opciones(modo="bracket")
    rng = np.random.default_rng(0)
    for _ in range(200):
        g = generador.genoma_aleatorio(rng, opciones=opciones)
        assert g.objetivo_atr == g.stop_atr
        assert g.salida == []


def test_el_modo_bracket_sobrevive_a_las_mutaciones():
    """Una mutación no puede romper la simetría del ratio."""
    opciones = generador.Opciones(modo="bracket")
    rng = np.random.default_rng(1)
    g = generador.genoma_aleatorio(rng, opciones=opciones)
    for _ in range(300):
        g = generador.mutar(g, rng, opciones=opciones)
        assert g.objetivo_atr == g.stop_atr
        assert g.salida == []


def test_el_modo_bracket_sobrevive_al_cruce():
    opciones = generador.Opciones(modo="bracket")
    rng = np.random.default_rng(2)
    for _ in range(100):
        a = generador.genoma_aleatorio(rng, opciones=opciones)
        b = generador.genoma_aleatorio(rng, opciones=opciones)
        hijo = generador.cruzar(a, b, rng, opciones)
        assert hijo.objetivo_atr == hijo.stop_atr
        assert hijo.salida == []


def test_el_modo_libre_no_impone_la_simetria():
    rng = np.random.default_rng(3)
    genomas = [generador.genoma_aleatorio(rng) for _ in range(200)]
    assert any(g.objetivo_atr != g.stop_atr for g in genomas)


def test_las_opciones_respetan_los_stops_pedidos():
    opciones = generador.Opciones(modo="bracket", stops_atr=(1.5,), max_barras=(96,))
    rng = np.random.default_rng(4)
    for _ in range(100):
        g = generador.mutar(generador.genoma_aleatorio(rng, opciones=opciones),
                            rng, opciones=opciones)
        assert g.stop_atr == 1.5 and g.objetivo_atr == 1.5
        assert g.max_barras == 96


def test_en_bracket_las_salidas_son_solo_stop_objetivo_o_tiempo():
    """Sin condiciones de salida, toda operación acaba en una de las tres."""
    datos = serie(4000, semilla=5)
    opciones = generador.Opciones(modo="bracket", stops_atr=(2.0,), max_barras=(96,))
    rng = np.random.default_rng(6)
    ctx = Contexto(datos)
    for _ in range(15):
        g = generador.genoma_aleatorio(rng, opciones=opciones)
        _, res = generador.evaluar(g, ctx, Config(), "15m")
        # 0 = señal. No puede aparecer si no hay condiciones de salida.
        assert 0 not in set(res.motivo.tolist())


# ========================
# CONTEXTO SEMANAL EN EL GENERADOR
# ========================

def test_los_bloques_semanales_estan_en_el_catalogo():
    assert generador.NOMBRES_SEMANALES <= set(generador.BLOQUES)
    assert "sem_pivote" in generador.BLOQUES
    assert generador.BLOQUES["sem_pos_rango"]["escala"] == "osc100"


def test_el_contexto_resuelve_las_caracteristicas_semanales():
    datos = serie(4000)
    ctx = Contexto(datos)
    valor = ctx.ind("sem_pivote", 0)
    assert len(valor) == len(datos)
    assert ctx.ind("sem_pivote", 0) is valor            # cacheado


def test_las_semanales_no_se_comparan_con_osciladores_intradia():
    """sem_pivote es de escala precio; nunca debe medirse contra un RSI."""
    rng = np.random.default_rng(7)
    for _ in range(400):
        g = generador.mutar(generador.genoma_aleatorio(rng), rng)
        for c in list(g.entrada) + list(g.salida):
            escalas = []
            for lado in (c["izq"], c["der"]):
                if lado["clase"] == "indicador":
                    escalas.append(generador.BLOQUES[lado["nombre"]]["escala"])
                elif lado["clase"] == "precio":
                    escalas.append("precio")
            if len(escalas) == 2:
                assert escalas[0] == escalas[1]


def test_una_estrategia_con_filtro_semanal_se_ejecuta():
    datos = serie(6000, semilla=8)
    genoma = generador.Genoma(
        entrada=[
            {"izq": {"clase": "precio", "campo": "close"}, "op": "cruza_arriba",
             "der": {"clase": "indicador", "nombre": "sem_pivote", "periodo": 0}},
        ],
        stop_atr=2.0, objetivo_atr=2.0, max_barras=96,
    )
    m, res = generador.evaluar(genoma, Contexto(datos), Config(), "15m")
    assert res.n_operaciones > 0
    assert np.isfinite(m["win_rate"])


def test_el_filtro_semanal_no_introduce_anticipacion():
    """
    Cambiar el futuro no puede alterar las operaciones ya cerradas de una
    estrategia que usa contexto semanal.
    """
    base = serie(6000, semilla=9)
    corte = 4000
    alterada = Datos(base.fechas, base.open.copy(), base.high.copy(), base.low.copy(),
                     base.close.copy(), base.volume, base.intervalo)
    for campo in ("open", "high", "low", "close"):
        getattr(alterada, campo)[corte:] *= 4

    genoma = generador.Genoma(
        entrada=[{"izq": {"clase": "precio", "campo": "close"}, "op": ">",
                  "der": {"clase": "indicador", "nombre": "sem_ant_close", "periodo": 0}}],
        stop_atr=2.0, objetivo_atr=2.0, max_barras=96,
    )
    _, a = generador.evaluar(genoma, Contexto(base), Config(), "15m")
    _, b = generador.evaluar(genoma, Contexto(alterada), Config(), "15m")

    # Operaciones cerradas holgadamente antes del corte: idénticas en ambas.
    seguras_a = a.salida_idx < corte - 200
    seguras_b = b.salida_idx < corte - 200
    n = min(seguras_a.sum(), seguras_b.sum())
    assert n > 5
    assert np.allclose(a.retorno[:n], b.retorno[:n])
    assert np.array_equal(a.entrada_idx[:n], b.entrada_idx[:n])
