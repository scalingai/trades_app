"""
Pruebas de las ventanas horarias de minuto exacto.

Las dos que sostienen el módulo son la del horario de verano —una ventana
definida en hora de Nueva York cae en horas UTC distintas según la época del
año, y confundirlas desplaza la medición una hora entera— y la del barrido,
que no puede usar nada posterior a la vela de entrada.
"""

from datetime import time

import numpy as np
import pandas as pd
import pytest

from backtest import ventanas


def indice(inicio, horas, frecuencia="10s"):
    n = int(horas * 3600 / pd.Timedelta(frecuencia).total_seconds())
    return pd.date_range(inicio, periods=n, freq=frecuencia, tz="UTC")


# ========================
# HORA LOCAL
# ========================

def test_la_zona_fija_resta_cuatro_horas():
    i = pd.DatetimeIndex(["2026-01-15T12:00:00Z"])
    assert ventanas.hora_local(i, "fija")[0].hour == 8


def test_nueva_york_cambia_con_el_horario_de_verano():
    """
    El mismo instante UTC es una hora distinta en Nueva York en enero y en
    julio. Es exactamente la diferencia que separa las dos lecturas de "GMT-4".
    """
    invierno = pd.DatetimeIndex(["2026-01-15T14:00:00Z"])
    verano = pd.DatetimeIndex(["2026-07-15T14:00:00Z"])
    assert ventanas.hora_local(invierno, "nueva-york")[0].hour == 9
    assert ventanas.hora_local(verano, "nueva-york")[0].hour == 10


def test_en_verano_las_dos_zonas_coinciden():
    i = pd.DatetimeIndex(["2026-07-15T14:00:00Z"])
    assert (ventanas.hora_local(i, "fija")[0].hour
            == ventanas.hora_local(i, "nueva-york")[0].hour)


# ========================
# MÁSCARA
# ========================

def test_la_ventana_es_semiabierta():
    """09:55-10:05 incluye el primer minuto y excluye el que cierra la caja."""
    i = pd.DatetimeIndex(["2026-07-15T13:54:50Z", "2026-07-15T13:55:00Z",
                          "2026-07-15T14:04:50Z", "2026-07-15T14:05:00Z"])
    m = ventanas.mascara_ventana(i, time(9, 55), time(10, 5), "fija")
    assert list(m) == [False, True, True, False]


def test_la_ventana_de_nueva_york_se_desplaza_en_invierno():
    """
    En julio 09:55 de Nueva York son las 13:55 UTC; en enero, las 14:55. Medir
    con hora UTC fija erraría la ventana por completo medio año.
    """
    julio = pd.DatetimeIndex(["2026-07-15T13:55:00Z", "2026-07-15T14:55:00Z"])
    enero = pd.DatetimeIndex(["2026-01-15T13:55:00Z", "2026-01-15T14:55:00Z"])
    m_julio = ventanas.mascara_ventana(julio, time(9, 55), time(10, 5), "nueva-york")
    m_enero = ventanas.mascara_ventana(enero, time(9, 55), time(10, 5), "nueva-york")
    assert list(m_julio) == [True, False]
    assert list(m_enero) == [False, True]


def test_una_ventana_que_cruza_medianoche():
    i = pd.DatetimeIndex(["2026-07-15T03:00:00Z",    # 23:00 local
                          "2026-07-15T05:00:00Z",    # 01:00 local
                          "2026-07-15T12:00:00Z"])   # 08:00 local
    m = ventanas.mascara_ventana(i, time(22, 0), time(2, 0), "fija")
    assert list(m) == [True, True, False]


def test_la_ventana_de_tres_horas_dura_tres_horas():
    i = indice("2026-07-01T00:00:00Z", horas=48)
    m = ventanas.mascara_ventana(i, time(1, 0), time(4, 0), "fija")
    # Dos apariciones de tres horas, en velas de 10 s.
    assert m.sum() == 2 * 3 * 360


# ========================
# OCURRENCIAS
# ========================

def test_una_ocurrencia_por_dia():
    i = indice("2026-07-01T00:00:00Z", horas=72)
    m = ventanas.mascara_ventana(i, time(9, 55), time(10, 5), "fija")
    primeras = ventanas.ocurrencias(m, "primera")
    ultimas = ventanas.ocurrencias(m, "ultima")
    assert len(primeras) == len(ultimas) == 3
    # Diez minutos en velas de 10 s son sesenta velas.
    assert np.all(ultimas - primeras == 59)


def test_las_ocurrencias_caen_dentro_de_la_ventana():
    i = indice("2026-07-01T00:00:00Z", horas=48)
    m = ventanas.mascara_ventana(i, time(9, 55), time(10, 5), "fija")
    for k in ventanas.ocurrencias(m, "primera"):
        assert m[k]
        assert k == 0 or not m[k - 1]


def test_ocurrencias_con_la_mascara_pegada_a_los_bordes():
    m = np.array([True, True, False, True])
    assert list(ventanas.ocurrencias(m, "primera")) == [0, 3]
    assert list(ventanas.ocurrencias(m, "ultima")) == [1, 3]


def test_ocurrencias_sin_nada_marcado():
    assert len(ventanas.ocurrencias(np.zeros(10, dtype=bool))) == 0


def test_un_dia_que_falta_no_pega_dos_apariciones():
    """La misma trampa que en `tramos`, por la vía de la máscara."""
    i = pd.DatetimeIndex(["2026-07-15T13:55:00Z", "2026-07-15T13:55:10Z",
                          "2026-07-16T13:55:00Z", "2026-07-16T13:55:10Z"])
    m = ventanas.mascara_ventana(i, time(9, 55), time(10, 5), "fija")
    assert m.all()
    assert len(ventanas.ocurrencias(m, "primera")) == 1
    assert list(ventanas.ocurrencias(m, "primera", marcas=i)) == [0, 2]
    assert list(ventanas.ocurrencias(m, "ultima", marcas=i)) == [1, 3]


def test_ocurrencias_rechaza_un_modo_desconocido():
    with pytest.raises(ValueError):
        ventanas.ocurrencias(np.array([True]), "cualquiera")


# ========================
# TRAMOS
# ========================

def test_los_tramos_cubren_la_serie_entera():
    i = indice("2026-07-01T00:00:00Z", horas=24)
    b = ventanas.bucket_local(i, minutos=10)
    ini, fin, etiqueta = ventanas.tramos(b)
    assert len(ini) == len(fin) == len(etiqueta) == 144
    assert ini[0] == 0 and fin[-1] == len(i) - 1
    # Sin huecos: el final de un tramo es la vela anterior al principio del siguiente.
    assert np.array_equal(fin[:-1] + 1, ini[1:])


def test_el_desfase_hace_que_la_ventana_sea_un_tramo_exacto():
    """
    Sin desfase, 09:55-10:05 se parte entre dos tramos de la rejilla y se
    compararía contra algo que no es ella. Con desfase 5 es un tramo entero.
    """
    i = pd.DatetimeIndex(["2026-07-15T13:55:00Z", "2026-07-15T14:04:50Z",
                          "2026-07-15T14:05:00Z"])
    b0 = ventanas.bucket_local(i, minutos=10, desfase=0)
    b5 = ventanas.bucket_local(i, minutos=10, desfase=5)
    assert b0[0] != b0[1]                 # la rejilla en punto la parte
    assert b5[0] == b5[1] != b5[2]        # la desfasada la respeta
    assert ventanas.inicio_de_bucket(b5[0], 10, 5) == "09:55"
    assert ventanas.inicio_de_bucket(b0[0], 10, 0) == "09:50"


def test_el_desfase_no_cambia_el_numero_de_tramos():
    i = indice("2026-07-01T00:00:00Z", horas=48)
    for desfase in (0, 5, 7):
        assert len(set(ventanas.bucket_local(i, 10, desfase=desfase))) == 144


def test_cada_tramo_lleva_su_propia_etiqueta():
    i = indice("2026-07-01T00:00:00Z", horas=24)
    b = ventanas.bucket_local(i, minutos=10)
    ini, _, etiqueta = ventanas.tramos(b)
    assert np.array_equal(b[ini], etiqueta)


def test_un_hueco_separa_las_apariciones_de_dos_dias():
    """
    Regresión: si falta un día entero, las velas de la misma franja horaria de
    dos días distintos quedan pegadas en el array. Sin mirar las marcas de
    tiempo se medirían como una sola aparición de veinticuatro horas.
    """
    i = pd.DatetimeIndex(["2026-07-15T13:55:00Z", "2026-07-15T13:55:10Z",
                          "2026-07-16T13:55:00Z", "2026-07-16T13:55:10Z"])
    b = ventanas.bucket_local(i, minutos=10)
    assert len(set(b)) == 1     # las cuatro caen en la misma franja

    sin_marcas = ventanas.tramos(b)[0]
    con_marcas = ventanas.tramos(b, marcas=i)[0]
    assert len(sin_marcas) == 1
    assert list(con_marcas) == [0, 2]


def test_tramos_sin_datos():
    ini, fin, etiqueta = ventanas.tramos(np.array([], dtype=int))
    assert len(ini) == len(fin) == len(etiqueta) == 0


# ========================
# PERFIL
# ========================

def marco(indice, precios=None, volumen=1.0):
    n = len(indice)
    c = np.full(n, 100.0) if precios is None else np.asarray(precios, dtype=float)
    return pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999,
                         "close": c, "volume": np.full(n, volumen)}, index=indice)


def test_el_perfil_tiene_un_tramo_por_bucket():
    i = indice("2026-07-01T00:00:00Z", horas=48)
    p = ventanas.perfil(marco(i), minutos=10)
    assert len(p) == 144
    assert p["hora"].iloc[0] == "00:00"
    assert p["hora"].iloc[-1] == "23:50"


def test_el_perfil_encuentra_el_tramo_agitado():
    """Control positivo: si se mete movimiento en una franja, tiene que salir."""
    i = indice("2026-07-01T00:00:00Z", horas=24 * 10)
    rng = np.random.default_rng(0)
    ruido = rng.normal(0, 0.0001, len(i))
    caliente = ventanas.mascara_ventana(i, time(9, 55), time(10, 5), "fija")
    ruido[caliente] *= 20
    d = marco(i, 100 * np.exp(np.cumsum(ruido)))

    p = ventanas.perfil(d, minutos=10)
    assert p.loc[p["exp_bp"].idxmax(), "hora"] == "09:50"


def test_el_percentil_ordena():
    assert ventanas.percentil([1, 2, 3, 4], 3.5) == pytest.approx(0.75)
    assert ventanas.percentil([1, 2, 3, 4], 0) == 0.0


# ========================
# BARRIDO
# ========================

def test_perforar_el_minimo_previo_da_senal_alcista():
    alto = np.array([105.0, 105, 105, 101, 101])
    bajo = np.array([100.0, 100, 100, 98, 99])
    d = ventanas.direccion_por_barrido(alto, bajo, [3], [4], previa=3)
    assert d[0] == 1


def test_perforar_el_maximo_previo_da_senal_bajista():
    alto = np.array([105.0, 105, 105, 107, 106])
    bajo = np.array([100.0, 100, 100, 104, 104])
    d = ventanas.direccion_por_barrido(alto, bajo, [3], [4], previa=3)
    assert d[0] == -1


def test_perforar_los_dos_extremos_no_da_senal():
    alto = np.array([105.0, 105, 105, 108])
    bajo = np.array([100.0, 100, 100, 97])
    assert ventanas.direccion_por_barrido(alto, bajo, [3], [3], previa=3)[0] == 0


def test_quedarse_dentro_del_rango_no_da_senal():
    alto = np.array([105.0, 105, 105, 103])
    bajo = np.array([100.0, 100, 100, 102])
    assert ventanas.direccion_por_barrido(alto, bajo, [3], [3], previa=3)[0] == 0


def test_el_barrido_no_mira_despues_de_la_entrada():
    """
    Regresión de mirada al futuro: lo que pase tras la última vela de la
    ventana no puede cambiar la señal, por violento que sea.
    """
    alto = np.array([105.0, 105, 105, 101, 500, 500])
    bajo = np.array([100.0, 100, 100, 98, 0.5, 0.5])
    d = ventanas.direccion_por_barrido(alto, bajo, [3], [3], previa=3)
    assert d[0] == 1


def test_sin_tramo_previo_no_hay_senal():
    alto = np.array([105.0, 101])
    bajo = np.array([100.0, 98])
    assert ventanas.direccion_por_barrido(alto, bajo, [0], [1], previa=5)[0] == 0


# ========================
# CONSISTENCIA Y ARITMÉTICA
# ========================

def test_un_efecto_repetido_todos_los_meses_sale_significativo():
    marcas = pd.date_range("2024-01-15", periods=24, freq="MS", tz="UTC")
    r = ventanas.consistencia(marcas, np.full(24, 0.01))
    assert r["a_favor"] == r["periodos"] == 24
    assert r["p"] < 0.001


def test_un_efecto_que_alterna_de_signo_no_sale_significativo():
    marcas = pd.date_range("2024-01-15", periods=24, freq="MS", tz="UTC")
    valores = np.where(np.arange(24) % 2 == 0, 0.01, -0.009)
    r = ventanas.consistencia(marcas, valores)
    assert r["p"] > 0.5


def test_consistencia_sin_datos():
    assert ventanas.consistencia([], []) == {}


def test_el_bracket_pequeno_exige_un_acierto_altisimo():
    """
    La aritmética que decide si la geometría del gráfico es discutible: 200
    puntos sobre 65.000 son un 0,31 %, y con coste de taker hace falta acertar
    casi siete de cada diez.
    """
    p = ventanas.win_rate_necesario(0.00307, 0.00307, coste=0.0012)
    assert p == pytest.approx(0.695, abs=0.005)


def test_sin_costes_el_uno_a_uno_pide_la_mitad():
    assert ventanas.win_rate_necesario(0.01, 0.01, coste=0.0) == pytest.approx(0.5)


def test_con_comisiones_de_maker_el_liston_baja_mucho():
    p = ventanas.win_rate_necesario(0.00307, 0.00307, coste=0.00024)
    assert p == pytest.approx(0.539, abs=0.005)
