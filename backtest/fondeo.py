"""
Cuentas de fondeo: pasar la evaluación es un problema de primera barrera.

Una cuenta de fondeo no pide maximizar el retorno. Pide **llegar al objetivo
antes de tocar el umbral de pérdida**, que es exactamente el problema que ya
resuelve `barreras.py`, sólo que aplicado a la curva de capital en vez de al
precio. Y la geometría de la cuenta pesa tanto como la estrategia.

Con umbral fijo, la probabilidad de pasar tirando una moneda es la conocida

    P = S / (S + T)

Pero Apex no usa umbral fijo: usa **umbral por rastro sobre el pico**, y el
pico se mide sobre el capital no realizado, o sea que cuenta lo que una
operación llegó a dar aunque después lo devolviera. Ese cambio no es un
detalle. La probabilidad pasa a ser

    P = e^(−T/S)

y la diferencia es brutal: con objetivo de 3.000 y umbral de 2.500, el fijo da
45,6 % y el arrastrado 30,9 %. Quince puntos perdidos sin haber operado
todavía, sólo por cómo está definida la cuenta.

La derivación es corta y conviene verla, porque explica qué hacer. Estando en
el máximo, avanzar el máximo un poco más (δ) antes de retroceder S es un
problema de ruina clásico: sale S/(S+δ). Para avanzar de 0 a T en n pasos de
δ = T/n hay que encadenar n de esos:

    P = [S/(S + T/n)]^n  →  e^(−T/S)   cuando n → ∞

Lo importante es lo que sigue de ahí: **el castigo no lo cobra la pérdida, lo
cobra la varianza del recorrido**. Cada oscilación hacia arriba que después se
devuelve sube el umbral y no vuelve a bajar. Por eso, con una ventaja real, la
posición más chica que sea práctica es la que más probabilidad de pasar da —
lo contrario de lo que sugiere la intuición de "necesito llegar rápido al
objetivo".

Los números por defecto son los de una cuenta de 50.000 según lo que publica
Apex, pero **conviene confirmarlos**: las firmas los cambian seguido y todo
aquí está parametrizado para que se ajusten sin tocar código.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Reglas:
    """
    Geometría de una cuenta de fondeo.

    `bloqueo` es el nivel de beneficio a partir del cual el umbral deja de
    arrastrarse y se queda quieto. Apex lo fija un poco por encima del saldo
    inicial.

    Parece la concesión que salva la evaluación y no lo es. Para que el bloqueo
    entre hay que haber llegado antes al pico que lo activa, y eso ya cuesta
    e^(−2600/2500) = 0,353; de ahí al objetivo queda una ruina fija que sale
    2500/2900 = 0,862. El producto es 0,304, contra 0,301 del arrastre puro:
    **tres décimas de punto**. El bloqueo protege la cuenta una vez fondeada,
    que es otra cosa, pero para pasar no regala prácticamente nada.
    """
    saldo: float = 50_000
    objetivo: float = 3_000
    umbral: float = 2_500
    bloqueo: float | None = 2_600      # umbral congelado al llegar a este beneficio
    arrastra: bool = True
    dias_minimos: int = 7
    consistencia: float | None = 0.30  # ningún día puede ser más del 30 % del total


def teorica_fija(objetivo, umbral):
    """Probabilidad de pasar sin ventaja, con umbral fijo."""
    return umbral / (umbral + objetivo)


def teorica_arrastrada(objetivo, umbral):
    """
    Probabilidad de pasar sin ventaja, con umbral que sigue al pico y nunca
    baja. Vale mientras el umbral arrastre durante todo el recorrido; con
    bloqueo, la real queda por encima de ésta.
    """
    return float(np.exp(-objetivo / umbral))


PASA, MUERE, SE_ACABA = "pasa", "muere", "se_acaba"


def recorrer_cuenta(resultados, excursiones, reglas):
    """
    Camina una secuencia de operaciones y devuelve en qué acabó la cuenta.

    Los tres desenlaces se distinguen a propósito. Quedarse sin operaciones no
    es lo mismo que reventar, y devolver lo mismo para los dos esconde
    justamente el caso que más informa: la cuenta que sobrevive pero no llega,
    que con umbral por rastro es muy común y no aparece si sólo se mira
    "pasó o no pasó".

    `excursiones` es lo que cada operación llegó a dar a favor antes de
    cerrarse. Hace falta porque el umbral sigue al capital **no realizado**: una
    operación que sube 800 y cierra en 100 deja el umbral 800 más arriba, y esa
    es la diferencia entre este modelo y uno que sólo mire el resultado final.
    """
    capital = 0.0
    pico = 0.0
    for r, mfe in zip(resultados, excursiones):
        # Primero el máximo que tocó la operación mientras estaba abierta.
        pico = max(pico, capital + max(mfe, 0.0))
        capital += r

        if reglas.arrastra:
            tope = min(pico, reglas.bloqueo) if reglas.bloqueo is not None else pico
            suelo = tope - reglas.umbral
        else:
            suelo = -reglas.umbral

        if capital <= suelo:
            return MUERE, capital
        if capital >= reglas.objetivo:
            return PASA, capital
    return SE_ACABA, capital


def simular(reglas, acierto, riesgo, ratio=1.0, mfe_perdedor=0.5,
            operaciones=2000, cuentas=20000, semilla=0):
    """
    Probabilidad de pasar con una ventaja y un tamaño de posición dados.

    `mfe_perdedor` es qué fracción del objetivo llega a dar, en promedio, una
    operación que después se va al stop. Importa mucho más de lo que parece: es
    justo el recorrido que sube el umbral sin dejar nada en la cuenta.
    """
    rng = np.random.default_rng(semilla)
    objetivo_trade = riesgo * ratio
    pasa = 0
    for _ in range(cuentas):
        gana = rng.random(operaciones) < acierto
        resultados = np.where(gana, objetivo_trade, -riesgo)
        # La ganadora llega por definición hasta su objetivo; la perdedora
        # llega hasta donde le tocó antes de darse la vuelta.
        excursiones = np.where(
            gana, objetivo_trade,
            rng.random(operaciones) * objetivo_trade * 2 * mfe_perdedor)
        estado, _ = recorrer_cuenta(resultados, excursiones, reglas)
        pasa += estado == PASA
    return pasa / cuentas


def barrido_riesgo(reglas, acierto, riesgos, ratio=1.0, **kw):
    """Probabilidad de pasar según cuánto se arriesgue por operación."""
    return {r: simular(reglas, acierto, r, ratio, **kw) for r in riesgos}
