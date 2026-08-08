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
# BRACKET VARIABLE
# ========================

def test_cada_operacion_puede_llevar_su_propio_bracket():
    """
    Dos entradas idénticas con stops distintos tienen que dar desenlaces
    distintos: la de stop estrecho salta y la de stop ancho aguanta.
    """
    df = marco([100, 100, 100, 100], alto=[100, 100, 100, 100],
               bajo=[100, 98, 100, 100])
    d = barreras.recorrer(*arrays(df), np.array([0, 0]),
                          stop=np.array([0.01, 0.05]),
                          objetivo=np.array([0.01, 0.05]), max_barras=3)
    assert d.motivo[0] == barreras.STOP
    assert d.motivo[1] != barreras.STOP
    assert d.retorno[0] == pytest.approx(-0.01)


def test_un_bracket_escalar_y_uno_repetido_dan_lo_mismo():
    rng = np.random.default_rng(12)
    n = 30000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = marco(precios, alto=precios * 1.001, bajo=precios * 0.999)
    entradas = np.arange(0, n - 1, 300)
    escalar = barreras.recorrer(*arrays(df), entradas, 0.01, 0.02, 500)
    vector = barreras.recorrer(*arrays(df), entradas,
                               np.full(len(entradas), 0.01),
                               np.full(len(entradas), 0.02), 500)
    assert np.array_equal(escalar.motivo, vector.motivo)
    assert np.allclose(escalar.retorno, vector.retorno)


def test_con_bracket_variable_y_ratio_fijo_se_sigue_cumpliendo_la_formula():
    """
    Escalar el bracket operación a operación no puede sesgar el medidor
    mientras el ratio se mantenga: sobre un paseo, S/(S+T) tiene que seguir
    saliendo. Si esto falla, cualquier mejora que aporte escalar por
    volatilidad será del sesgo y no del mercado.
    """
    rng = np.random.default_rng(13)
    n = 1_500_000
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    df = marco(precios, alto=precios * 1.0002, bajo=precios * 0.9998)
    entradas = np.arange(0, n - 1, 500)
    stops = rng.uniform(0.005, 0.02, len(entradas))
    d = barreras.recorrer(*arrays(df), entradas, stops, stops * 2.0, 200_000)
    r = barreras.contraste(d, 1.0, 2.0)
    assert r["resueltas"] > 2000
    assert abs(r["exceso"]) < 0.04, \
        f"exceso {r['exceso']:+.3f} con bracket variable: el medidor está sesgado"


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


# ========================
# COMISIONES DE FUTUROS
# ========================

def test_el_perdedor_cuesta_mas_que_el_ganador():
    """
    El objetivo es una orden límite y cobra de maker; el stop sale a mercado y
    cobra de taker, más deslizamiento. Cobrarles lo mismo abarata al perdedor.
    """
    c = barreras.Comisiones.futuros_limite(deslizamiento=0.0001)
    assert c.del_perdedor() > c.del_ganador()
    assert c.del_ganador() == pytest.approx(0.0004)
    assert c.del_perdedor() == pytest.approx(0.0008)


def test_una_comision_plana_reproduce_el_calculo_viejo():
    """Puente con lo medido antes: una cifra plana tiene que dar lo mismo."""
    df = marco([100, 100, 100], alto=[100, 100, 103], bajo=[100, 100, 100])
    d = barreras.recorrer(*arrays(df), np.array([0]), 0.02, 0.02, 5)
    plano = barreras.contraste(d, 0.02, 0.02, coste=0.0012)
    objeto = barreras.contraste(d, 0.02, 0.02, coste=barreras.Comisiones.plana(0.0012))
    assert objeto["neto_medio"] == pytest.approx(plano["neto_medio"])


def test_el_neto_descuenta_segun_como_salio():
    gana = marco([100, 100, 100], alto=[100, 100, 103], bajo=[100, 100, 100])
    pierde = marco([100, 100, 100], alto=[100, 100, 100], bajo=[100, 100, 97])
    c = barreras.Comisiones.futuros_limite(deslizamiento=0.0001)

    dg = barreras.recorrer(*arrays(gana), np.array([0]), 0.02, 0.02, 5)
    dp = barreras.recorrer(*arrays(pierde), np.array([0]), 0.02, 0.02, 5)
    assert barreras.neto(dg, c)[0] == pytest.approx(0.02 - 0.0004)
    assert barreras.neto(dp, c)[0] == pytest.approx(-0.02 - 0.0008)


def test_el_funding_solo_se_cobra_si_se_cruza_un_corte():
    """El perpetuo liquida a las 00, 08 y 16 UTC. Sin cruzar, no se paga."""
    dentro = pd.to_datetime(["2026-03-02T09:00:00Z", "2026-03-02T13:00:00Z"])
    cruza = pd.to_datetime(["2026-03-02T15:00:00Z", "2026-03-02T17:00:00Z"])
    assert barreras.cortes_de_funding(dentro[:1], dentro[1:])[0] == 0
    assert barreras.cortes_de_funding(cruza[:1], cruza[1:])[0] == 1


def test_el_largo_paga_el_funding_y_el_corto_lo_cobra():
    marcas = pd.to_datetime([f"2026-03-02T{h:02d}:00:00Z" for h in range(24)])
    d = barreras.Desenlaces(np.array([15]), np.array([17]),
                            np.array([barreras.TIEMPO]), np.array([0.0]), 1)
    c = barreras.Comisiones(0, 0, 0, 0, 0.0, funding=0.0001)
    largo = barreras.neto(d, c, marcas)[0]
    corto = barreras.neto(d, c, marcas, direcciones=np.array([-1]))[0]
    assert largo == pytest.approx(-0.0001)
    assert corto == pytest.approx(+0.0001)


def test_contraste_sin_operaciones():
    vacio = barreras.Desenlaces(np.array([]), np.array([]), np.array([]), np.array([]), 1)
    assert barreras.contraste(vacio, 0.01, 0.01) == {}
