"""
Pruebas de la descomposición en patas.

La que sostiene el módulo es la de repintado: un pivote sólo puede darse por
confirmado con información que existía en ese momento. Si falla, cualquier
estudio de ondas construido encima es una ilusión.
"""

import numpy as np
import pytest

from backtest import ondas


def zigzag(alturas, pasos=40):
    """Serie triangular que sube y baja entre los valores dados."""
    tramos = []
    for a, b in zip(alturas, alturas[1:]):
        tramos.append(np.linspace(a, b, pasos, endpoint=False))
    return np.concatenate(tramos + [np.array([alturas[-1]])])


# ========================
# REPINTADO
# ========================

def test_el_pivote_se_confirma_despues_de_ocurrir():
    """Nunca se puede saber que hubo un máximo en el mismo instante del máximo."""
    patas = ondas.detectar(zigzag([100, 110, 100, 112]), umbral=0.02)
    assert len(patas) >= 2
    assert np.all(patas.confirmada_en > patas.fin)
    assert np.all(patas.retardo > 0)


def test_alterar_el_futuro_no_cambia_las_patas_ya_confirmadas():
    """
    Se corta la serie en dos y se destroza la segunda mitad. Las patas
    confirmadas antes del corte tienen que salir idénticas.
    """
    base = zigzag([100, 108, 101, 110, 102, 112, 103])
    corte = len(base) // 2
    alterada = base.copy()
    alterada[corte:] *= 3

    a = ondas.detectar(base, 0.02)
    b = ondas.detectar(alterada, 0.02)

    seguras = a.confirmada_en < corte
    n = int(seguras.sum())
    assert n >= 2, "hacen falta patas confirmadas antes del corte"
    assert np.array_equal(a.fin[:n], b.fin[:n])
    assert np.array_equal(a.confirmada_en[:n], b.confirmada_en[:n])
    assert np.allclose(a.precio_fin[:n], b.precio_fin[:n])


def test_las_patas_encadenan_sin_huecos():
    patas = ondas.detectar(zigzag([100, 110, 100, 110, 100]), 0.02)
    assert len(patas) >= 3
    # El final de una pata es el arranque de la siguiente.
    assert np.array_equal(patas.fin[:-1], patas.inicio[1:])


def test_las_direcciones_alternan():
    patas = ondas.detectar(zigzag([100, 110, 100, 110, 100]), 0.02)
    assert np.all(patas.direccion[1:] == -patas.direccion[:-1])


def test_la_direccion_coincide_con_el_movimiento():
    patas = ondas.detectar(zigzag([100, 110, 100, 110]), 0.02)
    subidas = patas.direccion == 1
    assert np.all(patas.precio_fin[subidas] > patas.precio_inicio[subidas])
    assert np.all(patas.precio_fin[~subidas] < patas.precio_inicio[~subidas])


# ========================
# ESCALA
# ========================

def test_un_umbral_mayor_da_menos_patas():
    rng = np.random.default_rng(0)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 20000)))
    fino = ondas.detectar(precios, 0.003)
    grueso = ondas.detectar(precios, 0.03)
    assert len(fino) > len(grueso)
    assert fino.tamano.mean() < grueso.tamano.mean()


def test_una_serie_plana_no_tiene_patas():
    assert len(ondas.detectar(np.full(500, 100.0), 0.01)) == 0


def test_serie_demasiado_corta_no_revienta():
    assert len(ondas.detectar(np.array([100.0, 101.0]), 0.01)) == 0


def test_el_tamano_es_el_recorrido_relativo():
    patas = ondas.detectar(zigzag([100, 110, 100]), 0.02)
    assert patas.tamano[0] == pytest.approx(0.10, abs=0.01)


# ========================
# FIBONACCI CONTRA EL AZAR
# ========================

def test_cerca_de_fibonacci_detecta_los_niveles():
    exactas = np.array([0.382, 0.618, 1.618])
    assert ondas.cerca_de_fibonacci(exactas) == pytest.approx(1.0)
    lejos = np.array([0.05, 0.15, 0.30])
    assert ondas.cerca_de_fibonacci(lejos) == 0.0


def test_cerca_de_fibonacci_sin_datos():
    assert ondas.cerca_de_fibonacci(np.array([])) == 0.0


def test_el_paseo_equivalente_conserva_la_volatilidad():
    rng = np.random.default_rng(1)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 5000)))
    falso = ondas.paseo_equivalente(precios, semilla=2)
    v_real = np.diff(np.log(precios)).std()
    v_falso = np.diff(np.log(falso)).std()
    assert v_falso == pytest.approx(v_real, rel=0.1)
    assert len(falso) == len(precios)


def test_sobre_un_paseo_aleatorio_el_exceso_de_fibonacci_es_casi_cero():
    """
    Un paseo aleatorio no tiene estructura de ondas, así que sus proporciones
    no pueden caer en niveles de Fibonacci más que las de otro paseo aleatorio.
    Si este test falla, el contraste está sesgado y sus resultados no valen.
    """
    rng = np.random.default_rng(7)
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, 300000)))
    tabla = ondas.contraste_fibonacci(precios, umbrales=(0.005, 0.01), repeticiones=4)
    assert not tabla.empty
    assert tabla["exceso"].abs().max() < 0.05, \
        f"exceso de {tabla['exceso'].abs().max():.3f} sobre ruido: el contraste está sesgado"


# ========================
# EXPANSIÓN ENCADENADA
# ========================

def test_predice_la_siguiente_necesita_muestra():
    patas = ondas.detectar(zigzag([100, 110, 100]), 0.02)
    assert ondas.predice_la_siguiente(patas, minimo=50) == {}


def test_el_umbral_le_pone_suelo_al_tamano_de_las_patas():
    """
    Por construcción toda pata recorre al menos el umbral, y por eso el tamaño
    apenas distingue regímenes: lo que cambia entre ellos es la velocidad.
    """
    rng = np.random.default_rng(9)
    n = 100000
    tranquilo = 30000 * np.exp(np.cumsum(rng.normal(0, 0.0003, n)))
    agitado = 30000 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    pa = ondas.detectar(tranquilo, 0.005)
    pb = ondas.detectar(agitado, 0.005)
    assert pa.tamano.min() >= 0.005 * 0.9
    # El tamaño medio se parece; la velocidad no.
    assert pb.tamano.mean() / pa.tamano.mean() < 3
    assert pb.velocidad.mean() / pa.velocidad.mean() > 5


def test_detecta_el_encadenamiento_de_velocidad():
    """
    Control positivo: en una serie donde la volatilidad viene por rachas, las
    patas rápidas tienen que venir seguidas de patas rápidas.
    """
    rng = np.random.default_rng(3)
    n = 400000
    # Regímenes de volatilidad parecidos a propósito. Con regímenes muy
    # dispares el tramo agitado genera cien veces más patas que el tranquilo y
    # la mediana queda dominada por uno solo, así que el corte no separa nada.
    vol = np.where((np.arange(n) // 20000) % 2 == 0, 0.0008, 0.0024)
    precios = 30000 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    patas = ondas.detectar(precios, 0.005)
    r = ondas.predice_la_siguiente(patas, magnitud="velocidad")
    assert r, "no detectó patas suficientes"
    assert r["correlacion"] > 0.15, \
        f"correlación {r['correlacion']:.2f}: no vio el encadenamiento"
    assert r["ratio"] > 1.2, f"ratio {r['ratio']:.2f}"
