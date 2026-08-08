"""
Pruebas de la cuenta de fondeo.

Las dos que sostienen el módulo son las fórmulas: con umbral fijo el simulador
tiene que reproducir S/(S+T) y con umbral por rastro e^(−T/S). Si no las
reproduce, cualquier conclusión sobre cuánto arriesgar sale de un simulador
sesgado y no de la cuenta.
"""

import numpy as np
import pytest

from backtest import fondeo


def sin_ventaja(umbral, objetivo, arrastra, bloqueo=None):
    return fondeo.Reglas(objetivo=objetivo, umbral=umbral, arrastra=arrastra,
                         bloqueo=bloqueo)


# ========================
# FÓRMULAS
# ========================

def test_el_fijo_reproduce_la_formula_del_paseo():
    r = sin_ventaja(2500, 3000, arrastra=False)
    p = fondeo.simular(r, acierto=0.5, riesgo=50, mfe_perdedor=0.5,
                       operaciones=20000, cuentas=4000)
    assert p == pytest.approx(fondeo.teorica_fija(3000, 2500), abs=0.03)


def test_el_arrastrado_reproduce_el_exponencial():
    """
    La derivación encadena ruinas: avanzar el máximo δ antes de retroceder S
    sale S/(S+δ), y encadenar n de esos da e^(−T/S). Sin bloqueo, el simulador
    tiene que caer ahí.
    """
    r = sin_ventaja(2500, 3000, arrastra=True, bloqueo=None)
    p = fondeo.simular(r, acierto=0.5, riesgo=50, mfe_perdedor=0.5,
                       operaciones=20000, cuentas=4000)
    assert p == pytest.approx(fondeo.teorica_arrastrada(3000, 2500), abs=0.03)


def test_el_rastro_siempre_es_peor_que_el_fijo():
    for objetivo, umbral in [(3000, 2500), (3000, 3000), (6000, 2500)]:
        assert (fondeo.teorica_arrastrada(objetivo, umbral)
                < fondeo.teorica_fija(objetivo, umbral))


def test_un_objetivo_mas_lejano_baja_la_probabilidad():
    assert (fondeo.teorica_arrastrada(6000, 2500)
            < fondeo.teorica_arrastrada(3000, 2500))


# ========================
# MECÁNICA
# ========================

def test_llegar_al_objetivo_pasa():
    r = fondeo.Reglas(objetivo=1000, umbral=500, arrastra=False)
    estado, _ = fondeo.recorrer_cuenta([600, 600], [600, 600], r)
    assert estado == fondeo.PASA


def test_tocar_el_umbral_mata():
    r = fondeo.Reglas(objetivo=1000, umbral=500, arrastra=False)
    estado, _ = fondeo.recorrer_cuenta([-600], [0], r)
    assert estado == fondeo.MUERE


def test_quedarse_sin_operaciones_no_es_reventar():
    """
    Regresión de diseño: los dos devolvían lo mismo, y con eso la cuenta que
    sobrevive pero no llega —que con umbral por rastro es el caso más común—
    quedaba indistinguible de la que revienta.
    """
    r = fondeo.Reglas(objetivo=1000, umbral=500, arrastra=False)
    estado, capital = fondeo.recorrer_cuenta([10, -10], [0, 0], r)
    assert estado == fondeo.SE_ACABA
    assert capital == pytest.approx(0.0)


def test_lo_no_realizado_sube_el_umbral_aunque_se_devuelva():
    """
    El corazón del asunto. Dos cuentas con el mismo resultado cerrado: una
    operación que sube 900 y cierra en cero deja el umbral 900 más arriba que
    otra que nunca se movió, y con eso la siguiente pérdida la mata.
    """
    r = fondeo.Reglas(objetivo=5000, umbral=1000, arrastra=True, bloqueo=None)
    quieta, _ = fondeo.recorrer_cuenta([0, -900], [0, 0], r)
    devuelta, _ = fondeo.recorrer_cuenta([0, -900], [900, 0], r)
    assert quieta == fondeo.SE_ACABA      # sin excursión sobrevive
    assert devuelta == fondeo.MUERE       # con excursión devuelta, no


def test_el_bloqueo_del_umbral_casi_no_ayuda_a_pasar():
    """
    Parece la concesión que salva la evaluación y no lo es. Para que el bloqueo
    entre hay que llegar antes al pico que lo activa —e^(−2600/2500) = 0,353— y
    de ahí al objetivo queda una ruina fija de 2500/2900 = 0,862. El producto es
    0,304 contra 0,301 del arrastre puro.

    Se deja escrito como prueba porque es contraintuitivo y porque protege
    contra "mejorarlo" apoyándose en el bloqueo, que no da nada.
    """
    sin = fondeo.simular(sin_ventaja(2500, 3000, True, None), 0.5, 50,
                         operaciones=20000, cuentas=3000)
    con = fondeo.simular(sin_ventaja(2500, 3000, True, 2600), 0.5, 50,
                         operaciones=20000, cuentas=3000)
    assert con >= sin
    assert con - sin < 0.02, "si el bloqueo diera mucho, la cuenta de arriba está mal"
    assert con == pytest.approx(0.353 * 0.862, abs=0.03)


def test_sin_arrastre_el_pico_no_influye():
    r = fondeo.Reglas(objetivo=5000, umbral=1000, arrastra=False)
    a, _ = fondeo.recorrer_cuenta([0, -900], [0, 0], r)
    b, _ = fondeo.recorrer_cuenta([0, -900], [900, 0], r)
    assert a == b == fondeo.SE_ACABA


# ========================
# LO QUE DECIDE
# ========================

def test_con_ventaja_arriesgar_menos_pasa_mas():
    """
    La conclusión que da vuelta la intuición: con ventaja real, achicar la
    posición sube la probabilidad de pasar, porque el umbral por rastro no
    cobra la pérdida sino la oscilación.
    """
    r = fondeo.Reglas()
    grande = fondeo.simular(r, acierto=0.55, riesgo=500, operaciones=3000, cuentas=3000)
    chico = fondeo.simular(r, acierto=0.55, riesgo=100, operaciones=3000, cuentas=3000)
    assert chico > grande


def test_sin_ventaja_achicar_no_salva():
    """Contraste del anterior: si no hay ventaja, el tamaño no arregla nada."""
    r = fondeo.Reglas()
    grande = fondeo.simular(r, acierto=0.50, riesgo=500, operaciones=5000, cuentas=3000)
    chico = fondeo.simular(r, acierto=0.50, riesgo=100, operaciones=5000, cuentas=3000)
    assert abs(chico - grande) < 0.10


def test_devolver_mas_de_cada_operacion_perdedora_baja_la_probabilidad():
    r = fondeo.Reglas()
    limpio = fondeo.simular(r, 0.55, 200, mfe_perdedor=0.1,
                            operaciones=3000, cuentas=3000)
    sucio = fondeo.simular(r, 0.55, 200, mfe_perdedor=0.9,
                           operaciones=3000, cuentas=3000)
    assert limpio > sucio
