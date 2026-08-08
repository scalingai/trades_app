"""
Separadores: variables que parten la muestra en dos grupos de signo contrario.

Toda la medición del proyecto hasta aquí buscó **puntajes**: condiciones que
hacen que el promedio mejore. Eso da por supuesto que la población es una sola
y que hay que encontrarle el mejor filtro. Pero un promedio de +0,04 es
compatible con dos mundos que no se parecen en nada:

- **Uno.** Todas las apariciones continúan un poquito. Ventaja chica y pareja,
  se la come el coste, no hay nada que hacer.
- **Dos.** El ochenta por ciento son rupturas que continúan fuerte y el veinte
  por ciento son barridos que revierten fuerte. El promedio de la mezcla da lo
  mismo, pero cada grupo por separado es mucho más grande y de signo contrario.

En el primer mundo no hay estrategia. En el segundo hay una muy buena
esperando a quien pueda decir a qué grupo pertenece cada caso. Y el promedio
no distingue entre los dos.

Este módulo busca lo segundo. La diferencia con un puntaje es concreta: no
interesa que el grupo bueno mejore, interesa que **el grupo malo empeore al
mismo tiempo**. Un separador de verdad hace las dos cosas; recortar la muestra
por ruido sólo hace la primera.

Y como buscar el mejor separador entre varios candidatos siempre encuentra
algo —con ocho variables y ochocientos casos, la mejor separación por azar no
es cero—, la búsqueda va acompañada de su propia distribución nula por
permutación. Sin eso el número de arriba no significa nada.
"""

import numpy as np
import pandas as pd


def tasa_por_grupo(valores, gana, grupos=2):
    """
    Acierto de cada grupo al partir la muestra por los cuantiles de `valores`.

    Devuelve un vector con una tasa por grupo, de menor a mayor valor de la
    variable. Los NaN se descartan: una característica que no se pudo calcular
    no puede opinar.
    """
    v = np.asarray(valores, dtype=float)
    g = np.asarray(gana, dtype=bool)
    ok = np.isfinite(v)
    if ok.sum() < grupos * 10:
        return np.full(grupos, np.nan)

    v, g = v[ok], g[ok]
    # Los cuantiles empatados colapsan grupos; se rellenan con NaN en vez de
    # inventar una tasa a partir de dos casos.
    bordes = np.quantile(v, np.linspace(0, 1, grupos + 1))
    bordes[0], bordes[-1] = -np.inf, np.inf
    idx = np.clip(np.searchsorted(bordes, v, side="right") - 1, 0, grupos - 1)

    tasas = np.full(grupos, np.nan)
    for k in range(grupos):
        sel = idx == k
        if sel.sum() >= 10:
            tasas[k] = g[sel].mean()
    return tasas


def separacion(valores, gana, grupos=2):
    """
    Cuánto separa una variable: acierto del grupo de arriba menos el de abajo.

    El signo importa tanto como la magnitud. Positivo grande significa que la
    variable alta va con el objetivo y la baja con el stop; negativo grande,
    al revés. Cerca de cero significa que la variable no sabe nada.
    """
    t = tasa_por_grupo(valores, gana, grupos)
    if np.isnan(t[0]) or np.isnan(t[-1]):
        return float("nan")
    return float(t[-1] - t[0])


def buscar(caracteristicas, gana, grupos=2):
    """
    Recorre todas las características y las ordena por poder de separación.

    `caracteristicas` es un diccionario de nombre a vector, todos alineados con
    `gana` y todos calculables antes de entrar.
    """
    filas = []
    for nombre, valores in caracteristicas.items():
        t = tasa_por_grupo(valores, gana, grupos)
        filas.append({
            "variable": nombre,
            "separacion": separacion(valores, gana, grupos),
            **{f"g{k}": t[k] for k in range(grupos)},
        })
    t = pd.DataFrame(filas)
    return t.reindex(t["separacion"].abs().sort_values(ascending=False).index)


def permutacion(caracteristicas, gana, grupos=2, repeticiones=200, semilla=0):
    """
    Distribución de la mejor separación cuando no hay ninguna relación.

    Se baraja el resultado —no las variables— y se repite la búsqueda entera,
    incluida la elección de la mejor. Así el nulo incorpora el hecho de que se
    está eligiendo el máximo de varios candidatos, que es exactamente el sesgo
    del que hay que defenderse.
    """
    rng = np.random.default_rng(semilla)
    g = np.asarray(gana, dtype=bool)
    mejores = np.full(repeticiones, np.nan)
    for i in range(repeticiones):
        barajado = rng.permutation(g)
        # Una variable que no se puede evaluar se salta. Dejarla propagar un
        # NaN al máximo borraría la distribución nula entera y el contraste
        # daría p = 0 por no tener con qué comparar, que es el peor error
        # posible aquí: declararía hallazgo justo cuando no hay medición.
        valores = [abs(separacion(v, barajado, grupos))
                   for v in caracteristicas.values()]
        valores = [x for x in valores if np.isfinite(x)]
        if valores:
            mejores[i] = max(valores)
    return mejores


def contraste(caracteristicas, gana, grupos=2, repeticiones=200, semilla=0):
    """
    La tabla de separaciones junto con el veredicto de la permutación.

    `p` es la fracción de barajadas en las que la mejor separación falsa iguala
    o supera a la real. Si sale alta, lo encontrado es lo que encuentra
    cualquiera revolviendo números sin relación entre sí.
    """
    tabla = buscar(caracteristicas, gana, grupos)
    real = float(tabla["separacion"].abs().max())
    nulo = permutacion(caracteristicas, gana, grupos, repeticiones, semilla)
    nulo = nulo[np.isfinite(nulo)]
    if not np.isfinite(real) or len(nulo) == 0:
        return tabla, {"mejor": real, "nulo_medio": float("nan"),
                       "nulo_p95": float("nan"), "p": float("nan"),
                       "repeticiones": 0}
    return tabla, {
        "mejor": real,
        "nulo_medio": float(nulo.mean()),
        "nulo_p95": float(np.quantile(nulo, 0.95)),
        "p": float((nulo >= real).mean()),
        "repeticiones": int(len(nulo)),
    }
