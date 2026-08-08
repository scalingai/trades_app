"""
Descomposición del precio en patas (swings) y contraste de las proporciones
de Fibonacci contra lo que produciría el azar.

La idea de fondo es que el precio no se mueve de forma homogénea sino a
tirones, y que esos tirones se anidan: dentro de una pata grande hay patas
pequeñas con la misma forma. Si eso es cierto, descomponer la serie en patas a
varios umbrales da una descripción fractal de la expansión, que es justo lo que
resultó ser predecible cuando la dirección no lo era.

Dos cosas hacen que este análisis se haga mal casi siempre:

**El zigzag repinta.** Un máximo sólo se sabe que era máximo cuando el precio
ya retrocedió lo suficiente. Marcar el pivote en la barra donde ocurrió es usar
información que en ese momento no existía, y produce backtests espectaculares
e imposibles de reproducir en real. Aquí cada pivote guarda dos cosas: dónde
ocurrió y en qué barra se confirmó. Todo lo que se mide usa la segunda.

**Las proporciones de Fibonacci se dan por buenas sin contraste.** Cualquier
serie, incluido un paseo aleatorio, produce retrocesos repartidos entre 0 y 1,
y por pura forma de la distribución habrá masa cerca de 0,5 y de 0,618. La
pregunta que importa no es si aparecen, sino si aparecen MÁS que en una serie
sin estructura. Por eso el módulo compara siempre contra un paseo aleatorio con
la misma volatilidad.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Proporciones que la teoría considera especiales.
FIBONACCI = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
TOLERANCIA = 0.02          # una proporción "cae en" un nivel si está a ±0,02


@dataclass
class Patas:
    """
    Patas detectadas. Cada una va de un pivote al siguiente.

    `confirmada_en` es la barra en la que se supo que la pata había terminado,
    que siempre es posterior a `fin`. Cualquier medición que quiera ser honesta
    tiene que usar `confirmada_en`.
    """
    inicio: np.ndarray          # índice de barra donde arranca
    fin: np.ndarray             # índice donde está el extremo
    confirmada_en: np.ndarray   # índice donde se supo
    precio_inicio: np.ndarray
    precio_fin: np.ndarray
    direccion: np.ndarray       # +1 al alza, -1 a la baja

    def __len__(self):
        return len(self.inicio)

    @property
    def tamano(self):
        """Recorrido relativo de cada pata."""
        return np.abs(self.precio_fin - self.precio_inicio) / self.precio_inicio

    @property
    def duracion(self):
        return np.maximum(self.fin - self.inicio, 1)

    @property
    def velocidad(self):
        """
        Recorrido por barra.

        Es la magnitud que de verdad lleva la información de régimen. El umbral
        del zigzag impone un mínimo al tamaño de toda pata, así que el tamaño
        sale parecido en mercados tranquilos y agitados: lo que cambia es
        cuántas barras tarda en recorrerse. Medir la expansión por el tamaño de
        la pata, y no por su velocidad, es no medir nada.
        """
        return self.tamano / self.duracion

    @property
    def retardo(self):
        """Barras entre que la pata terminó y que se supo que había terminado."""
        return self.confirmada_en - self.fin

    def proporciones(self):
        """Tamaño de cada pata dividido por el de la anterior."""
        t = self.tamano
        if len(t) < 2:
            return np.array([])
        with np.errstate(divide="ignore", invalid="ignore"):
            r = t[1:] / t[:-1]
        return r[np.isfinite(r)]


def detectar(precios, umbral=0.005):
    """
    Zigzag causal: marca un pivote sólo cuando el precio ya retrocedió
    `umbral` desde el extremo, y registra en qué barra se supo.

    Cambiando `umbral` se obtiene la misma serie descrita a distinta escala,
    que es lo que permite mirarla como fractal: umbrales pequeños dan muchas
    patas cortas y umbrales grandes dan pocas patas largas.
    """
    precios = np.asarray(precios, dtype=float)
    n = len(precios)
    if n < 3 or umbral <= 0:
        return Patas(*[np.array([], dtype=int)] * 3, *[np.array([])] * 2,
                     np.array([], dtype=int))

    inicio, fin, confirmada, p_ini, p_fin, direccion = [], [], [], [], [], []

    idx_ancla = 0                 # arranque de la pata en curso
    idx_extremo = 0               # extremo alcanzado desde el ancla
    sentido = 0                   # 0 = todavía sin definir

    for i in range(1, n):
        p = precios[i]
        extremo = precios[idx_extremo]

        if sentido >= 0 and p > extremo:
            idx_extremo = i
            extremo = p
        elif sentido <= 0 and p < extremo:
            idx_extremo = i
            extremo = p

        if sentido == 0:
            # Aún no hay dirección: se define con el primer movimiento que
            # supere el umbral desde el arranque.
            variacion = (p - precios[idx_ancla]) / precios[idx_ancla]
            if abs(variacion) >= umbral:
                sentido = 1 if variacion > 0 else -1
                idx_extremo = i
            continue

        # Retroceso desde el extremo, medido en la dirección contraria.
        retroceso = (extremo - p) / extremo if sentido > 0 else (p - extremo) / extremo
        if retroceso >= umbral:
            # Aquí, en la barra i, se confirma que idx_extremo era el final.
            inicio.append(idx_ancla)
            fin.append(idx_extremo)
            confirmada.append(i)
            p_ini.append(precios[idx_ancla])
            p_fin.append(precios[idx_extremo])
            direccion.append(sentido)

            idx_ancla = idx_extremo
            sentido = -sentido
            idx_extremo = i

    return Patas(np.array(inicio, dtype=int), np.array(fin, dtype=int),
                 np.array(confirmada, dtype=int), np.array(p_ini), np.array(p_fin),
                 np.array(direccion, dtype=int))


def cerca_de_fibonacci(proporciones, niveles=FIBONACCI, tolerancia=TOLERANCIA):
    """Fracción de proporciones que cae a menos de `tolerancia` de algún nivel."""
    if len(proporciones) == 0:
        return 0.0
    p = np.asarray(proporciones)
    cerca = np.zeros(len(p), dtype=bool)
    for nivel in niveles:
        cerca |= np.abs(p - nivel) <= tolerancia
    return float(cerca.mean())


def paseo_equivalente(precios, semilla=0):
    """
    Paseo aleatorio con la misma volatilidad y el mismo largo que la serie real.

    Es la referencia: si las proporciones de Fibonacci aparecen igual de a
    menudo aquí que en el precio real, no dicen nada del mercado, dicen algo de
    la aritmética de dividir dos números positivos.
    """
    precios = np.asarray(precios, dtype=float)
    rng = np.random.default_rng(semilla)
    retornos = np.diff(np.log(precios))
    simulados = rng.normal(retornos.mean(), retornos.std(), len(retornos))
    return precios[0] * np.exp(np.concatenate(([0.0], np.cumsum(simulados))))


def contraste_fibonacci(precios, umbrales=(0.002, 0.005, 0.01, 0.02), repeticiones=5):
    """
    Compara, a varias escalas, cuántas proporciones caen en niveles de
    Fibonacci en la serie real frente a paseos aleatorios equivalentes.
    """
    filas = []
    for umbral in umbrales:
        patas = detectar(precios, umbral)
        proporciones = patas.proporciones()
        if len(proporciones) < 30:
            continue
        real = cerca_de_fibonacci(proporciones)

        azar = []
        for s in range(repeticiones):
            falso = detectar(paseo_equivalente(precios, semilla=s), umbral)
            r = falso.proporciones()
            if len(r) >= 30:
                azar.append(cerca_de_fibonacci(r))

        filas.append({
            "umbral": umbral,
            "patas": len(patas),
            "tamano_medio": float(patas.tamano.mean()),
            "retardo_medio": float(patas.retardo.mean()),
            "fib_real": real,
            "fib_azar": float(np.mean(azar)) if azar else float("nan"),
            "exceso": real - (float(np.mean(azar)) if azar else np.nan),
        })
    return pd.DataFrame(filas)


def predice_la_siguiente(patas, magnitud="velocidad", minimo=50):
    """
    ¿Una pata dice algo de la siguiente?

    Por defecto mide la velocidad, no el tamaño, por el motivo explicado en
    Patas.velocidad: el umbral del zigzag le pone un suelo al tamaño y borra
    casi toda la diferencia entre regímenes.
    """
    valores = getattr(patas, magnitud)
    if len(valores) < minimo:
        return {}
    actual, siguiente = valores[:-1], valores[1:]
    with np.errstate(invalid="ignore"):
        corr = float(np.corrcoef(np.log(actual + 1e-12), np.log(siguiente + 1e-12))[0, 1])

    mediana = np.median(actual)
    altas = siguiente[actual >= mediana].mean()
    bajas = siguiente[actual < mediana].mean()
    return {
        "magnitud": magnitud,
        "n": len(actual),
        "correlacion": corr,
        "tras_pata_alta": float(altas),
        "tras_pata_baja": float(bajas),
        "ratio": float(altas / bajas) if bajas > 0 else float("nan"),
    }
