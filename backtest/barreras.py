"""
Primer paso por barrera: qué pasa entre abrir con stop y objetivo, y cerrar.

El resultado que ordena todo este módulo es el siguiente. Sobre un paseo
aleatorio sin deriva, la probabilidad de tocar un objetivo a distancia T antes
que un stop a distancia S es exactamente

    P = S / (S + T)

y por lo tanto el valor esperado de la operación es

    EV = P·T − (1−P)·S − coste = −coste

Sale exactamente menos el coste, **para cualquier ratio**. Poner el objetivo
lejos baja la probabilidad justo lo necesario para compensar; ponerlo cerca la
sube justo lo necesario. No hay ratio bueno ni malo: sobre un paseo aleatorio
todos pierden lo mismo.

De ahí se deduce lo único que importa medir: **cuánto se desvía el mercado real
de esa fórmula**. Si BTC toca el objetivo más a menudo de lo que predice
S/(S+T), hay persistencia de trayectoria; si lo toca menos, hay reversión. Esa
desviación es la ventaja, y es lo que hay que buscar.

Es además una prueba mucho más sensible que mirar el signo del retorno al cabo
de N barras. El signo final resume toda la trayectoria en un bit y descarta el
recorrido; la barrera mira el camino, que es donde vive la diferencia entre
tendencia y rango.

El horizonte añade un tercer desenlace: que no se toque ninguna barrera y haya
que cerrar a mercado. Esas operaciones tienen su propia distribución de
resultados y se contabilizan aparte.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

OBJETIVO, STOP, TIEMPO = 0, 1, 2
NOMBRES = {OBJETIVO: "objetivo", STOP: "stop", TIEMPO: "tiempo"}


@dataclass
class Desenlaces:
    """Resultado de cada operación simulada."""
    entrada: np.ndarray
    salida: np.ndarray
    motivo: np.ndarray
    retorno: np.ndarray      # bruto, sin costes
    direccion: int

    def __len__(self):
        return len(self.entrada)

    def reparto(self):
        """
        Fracción de operaciones que acabó en cada desenlace.

        Las claves llevan prefijo a propósito: sin él chocan con los nombres de
        los parámetros (stop, objetivo) al volcarlas en la misma fila de una
        tabla, y los pisan sin avisar.
        """
        if len(self) == 0:
            return {}
        return {f"frac_{NOMBRES[m]}": float((self.motivo == m).mean())
                for m in (OBJETIVO, STOP, TIEMPO)}


def teorica(stop, objetivo):
    """
    P(tocar objetivo antes que stop) sobre un paseo sin deriva y sin límite de
    tiempo. Es la referencia contra la que se compara todo.
    """
    return stop / (stop + objetivo)


def recorrer(alto, bajo, cierre, entradas, stop, objetivo, max_barras, direccion=1):
    """
    Para cada entrada, busca qué barrera se toca primero dentro del horizonte.

    Se entra al cierre de la barra indicada y se empieza a mirar en la
    siguiente. Si en la misma barra se tocan las dos, se cuenta el stop: no se
    sabe cuál llegó antes y suponer lo contrario es regalarse resultados.
    """
    n = len(cierre)
    sal, mot, ret = [], [], []
    validas = []

    for i in entradas:
        fin = min(i + max_barras, n - 1)
        if fin <= i:
            continue
        precio = cierre[i]
        if direccion > 0:
            nivel_obj, nivel_stop = precio * (1 + objetivo), precio * (1 - stop)
            toca_obj = alto[i + 1:fin + 1] >= nivel_obj
            toca_stop = bajo[i + 1:fin + 1] <= nivel_stop
        else:
            nivel_obj, nivel_stop = precio * (1 - objetivo), precio * (1 + stop)
            toca_obj = bajo[i + 1:fin + 1] <= nivel_obj
            toca_stop = alto[i + 1:fin + 1] >= nivel_stop

        j_obj = int(np.argmax(toca_obj)) if toca_obj.any() else -1
        j_stop = int(np.argmax(toca_stop)) if toca_stop.any() else -1

        if j_stop >= 0 and (j_obj < 0 or j_stop <= j_obj):
            motivo, j, r = STOP, j_stop, -stop
        elif j_obj >= 0:
            motivo, j, r = OBJETIVO, j_obj, objetivo
        else:
            motivo, j = TIEMPO, fin - i - 1
            r = (cierre[fin] / precio - 1) * direccion

        validas.append(i)
        sal.append(i + 1 + j)
        mot.append(motivo)
        ret.append(r)

    return Desenlaces(np.array(validas, dtype=int), np.array(sal, dtype=int),
                      np.array(mot, dtype=int), np.array(ret), direccion)


def contraste(desenlaces, stop, objetivo, coste=0.0012):
    """
    Compara lo observado con lo que predice la fórmula del paseo aleatorio.

    `exceso` es la cifra que importa: cuántos puntos porcentuales más (o menos)
    se toca el objetivo respecto a S/(S+T). Positivo significa que la
    trayectoria persiste; negativo, que revierte. Cero significa que el mercado
    se comporta como un paseo y no hay nada que extraer.
    """
    if len(desenlaces) == 0:
        return {}
    reparto = desenlaces.reparto()
    resueltas = desenlaces.motivo != TIEMPO
    n_res = int(resueltas.sum())

    p_teorica = teorica(stop, objetivo)
    p_real = (float((desenlaces.motivo[resueltas] == OBJETIVO).mean())
              if n_res else float("nan"))

    bruto = float(desenlaces.retorno.mean())
    return {
        "n": len(desenlaces),
        "resueltas": n_res,
        **reparto,
        "p_teorica": p_teorica,
        "p_real": p_real,
        "exceso": p_real - p_teorica if n_res else float("nan"),
        "bruto_medio": bruto,
        "neto_medio": bruto - coste,
    }


def barrido(datos, stops, ratios, horizontes, cada=360, coste=0.0012, direccion=1):
    """
    Recorre combinaciones de stop, ratio y horizonte, y devuelve el contraste
    de cada una.

    `cada` es el espaciado entre entradas candidatas. Conviene que sea al menos
    tan grande como el horizonte para que las operaciones no se solapen y las
    observaciones sean razonablemente independientes.
    """
    alto = datos["high"].to_numpy(dtype=float)
    bajo = datos["low"].to_numpy(dtype=float)
    cierre = datos["close"].to_numpy(dtype=float)
    entradas = np.arange(0, len(cierre) - 1, cada)

    filas = []
    for stop in stops:
        for ratio in ratios:
            objetivo = stop * ratio
            for h in horizontes:
                d = recorrer(alto, bajo, cierre, entradas, stop, objetivo, h, direccion)
                fila = contraste(d, stop, objetivo, coste)
                if fila:
                    filas.append({"stop": stop, "ratio": ratio, "objetivo": objetivo,
                                  "horizonte": h, **fila})
    return pd.DataFrame(filas)
