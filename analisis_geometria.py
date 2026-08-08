#!/usr/bin/env python3
"""
Geometría de la señal: ratio, bracket escalado por volatilidad y tres estados.

La señal de partida es la única que sobrevivió al contraste de ventanas: dentro
de un tramo horario, si el precio perfora el extremo del rango anterior,
**continúa** en esa dirección en vez de revertir. Sobre la ventana 01:00-04:00
de Nueva York da un exceso de +0,043 sobre la fórmula del paseo aleatorio, con
acuerdo en 40 de 55 meses, y queda primera de las veinticuatro ventanas de tres
horas del día.

Lo que falta es saber si la geometría con la que se explota está bien elegida,
y hasta ahora se probó una sola: 1:1. Eso importa más de lo que parece. Si el
exceso sobre S/(S+T) es `e`, el stop es `S` y el ratio es `r`:

    p = 1/(1+r) + e
    EV = p·rS − (1−p)·S − coste = S·e·(1+r) − coste

El ratio multiplica la ventaja **linealmente**. Con e = 0,043 y S = 0,5 %, un
1:1 necesita e = 0,080 y un 1:3 necesita 0,040. La misma señal que no llega a
uno llegaría al otro… si el exceso aguantase al alejar el objetivo. Casi
seguro no aguanta entero, porque un objetivo lejano exige una trayectoria más
larga y más persistente. Cuánto se pierde es lo que hay que medir.

Tres pasos:

**1. Barrido de ratio y stop.** Con la fórmula al lado, para ver si el exceso
que se pierde al alejar el objetivo compensa el (1+r) que se gana.

**2. Bracket escalado por sigma.** Medio por ciento es un mundo a las cuatro de
la mañana y no es nada en la apertura de Nueva York. Un bracket fijo compra
regímenes distintos con la misma vara. Escalarlo por la desviación típica del
horizonte, estimada sólo con el pasado, iguala la vara.

**3. Tres estados.** No hay que casarse con reversión ni con continuación: hay
que decidir si toca una, la otra o ninguna. Se puntúa cada aparición por
confluencia y se mide el exceso en cada tramo de confianza. Lo que interesa no
es el número de arriba, sino si crece de forma ordenada al subir la exigencia:
si crece, hay señal y se puede esperar al momento bueno; si salta sin orden,
es ruido.

    python analisis_geometria.py
    python analisis_geometria.py --inicio 22 --horas 3
"""

import argparse
import sys
from datetime import time

import numpy as np
import pandas as pd

from backtest import barreras, ventanas
from descargar_datos import cargar_datos

MERCADOS = {
    "futuros-limite": barreras.Comisiones.futuros_limite(),
    "futuros-mercado": barreras.Comisiones.futuros_mercado(),
    "contado": barreras.Comisiones.plana(0.0012),
}
# Ventana móvil para estimar sigma sin mirar al futuro: 30 días de velas de 10 s.
VENTANA_SIGMA = 259200


def sigma_causal(cierre, barras, ventana=VENTANA_SIGMA):
    """Desviación típica del retorno a `barras`, estimada sólo con el pasado."""
    r = cierre.pct_change(barras)
    return r.rolling(ventana, min_periods=ventana // 10).std()


def senal(d, alto, bajo, zona, inicio, horas, previa):
    """Apariciones de la ventana y dirección de continuación de cada una."""
    fin = time((inicio + horas) % 24, 0)
    m = ventanas.mascara_ventana(d.index, time(inicio, 0), fin, zona)
    primeras = ventanas.ocurrencias(m, "primera", marcas=d.index)
    ultimas = ventanas.ocurrencias(m, "ultima", marcas=d.index)
    n = min(len(primeras), len(ultimas))
    primeras, ultimas = primeras[:n], ultimas[:n]
    # El signo es el del barrido; continuación es ir a favor, no en contra.
    lado = ventanas.direccion_por_barrido(alto, bajo, primeras, ultimas, previa)
    hay = lado != 0
    return primeras[hay], ultimas[hay], -lado[hay]


def ejecutar(alto, bajo, cierre, entradas, lado, stop, objetivo, horizonte):
    """Recorre las barreras separando por lado y devuelve un solo desenlace."""
    trozos = []
    for direccion in (1, -1):
        sel = lado == direccion
        if not sel.any():
            continue
        s = stop[sel] if np.ndim(stop) else stop
        o = objetivo[sel] if np.ndim(objetivo) else objetivo
        trozos.append(barreras.recorrer(alto, bajo, cierre, entradas[sel], s, o,
                                        horizonte, direccion))
    if not trozos:
        return None
    return barreras.Desenlaces(
        np.concatenate([t.entrada for t in trozos]),
        np.concatenate([t.salida for t in trozos]),
        np.concatenate([t.motivo for t in trozos]),
        np.concatenate([t.retorno for t in trozos]),
        np.concatenate([np.full(len(t), t.direccion) for t in trozos]))


def resumen(des, ratio, comisiones, marcas):
    r = barreras.contraste(des, 1.0, ratio, comisiones, marcas)
    if r:
        r["consistencia"] = ventanas.consistencia(
            marcas[des.entrada], barreras.neto(des, comisiones, marcas))
    return r


# ========================
# 1. RATIO Y STOP
# ========================

def paso_ratio(d, alto, bajo, cierre, entradas, lado, comisiones, horizonte,
               stops, ratios):
    print("[1] Barrido de ratio y stop\n")
    print(f"     {'stop':>6} {'ratio':>6} {'n':>6} {'%res':>6} {'acierto':>8} "
          f"{'exceso':>8} {'nec.':>7} {'neto':>9} {'meses':>9}")
    filas = []
    for stop in stops:
        for ratio in ratios:
            des = ejecutar(alto, bajo, cierre, entradas, lado, stop,
                           stop * ratio, horizonte)
            if des is None or len(des) < 100:
                continue
            r = resumen(des, ratio, comisiones, d.index)
            # Exceso que haría falta para que EV = S·e·(1+r) − coste sea cero.
            coste = (comisiones.del_ganador() + comisiones.del_perdedor()) / 2
            necesario = coste / (stop * (1 + ratio))
            c = r["consistencia"]
            filas.append({"stop": stop, "ratio": ratio, "necesario": necesario, **r})
            marca = "  ←" if r["neto_medio"] > 0 else ""
            print(f"     {stop:>6.3%} {ratio:>6.2f} {r['n']:>6,} "
                  f"{1 - r['frac_tiempo']:>5.0%} {r['p_real']:>8.4f} "
                  f"{r['exceso']:>+8.4f} {necesario:>7.4f} "
                  f"{r['neto_medio']:>+8.4%} {c['a_favor']:>3}/{c['periodos']:<4}{marca}")
    print()
    return pd.DataFrame(filas)


# ========================
# 2. BRACKET ESCALADO
# ========================

def paso_sigma(d, alto, bajo, cierre, entradas, lado, comisiones, horizonte,
               ratios, kas):
    print("[2] Bracket escalado por la volatilidad del momento\n")
    s = sigma_causal(d["close"], horizonte).to_numpy()
    valido = np.isfinite(s[entradas]) & (s[entradas] > 0)
    ent, lad = entradas[valido], lado[valido]
    print(f"     sigma a {horizonte * 10 / 60:.0f} min: mediana "
          f"{np.nanmedian(s[ent]):.4%}, rango "
          f"{np.nanpercentile(s[ent], 5):.4%} a {np.nanpercentile(s[ent], 95):.4%}")
    print(f"     ({len(entradas) - len(ent)} entradas descartadas por falta de historia)\n")

    print(f"     {'k·σ':>6} {'ratio':>6} {'n':>6} {'stop medio':>11} {'%res':>6} "
          f"{'acierto':>8} {'exceso':>8} {'neto':>9} {'meses':>9}")
    filas = []
    for k in kas:
        stop = s[ent] * k
        for ratio in ratios:
            des = ejecutar(alto, bajo, cierre, ent, lad, stop, stop * ratio,
                           horizonte)
            if des is None or len(des) < 100:
                continue
            r = resumen(des, ratio, comisiones, d.index)
            c = r["consistencia"]
            filas.append({"k": k, "ratio": ratio, **r})
            marca = "  ←" if r["neto_medio"] > 0 else ""
            print(f"     {k:>6.2f} {ratio:>6.2f} {r['n']:>6,} {stop.mean():>10.3%} "
                  f"{1 - r['frac_tiempo']:>5.0%} {r['p_real']:>8.4f} "
                  f"{r['exceso']:>+8.4f} {r['neto_medio']:>+8.4%} "
                  f"{c['a_favor']:>3}/{c['periodos']:<4}{marca}")
    print()
    return pd.DataFrame(filas)


# ========================
# 3. TRES ESTADOS
# ========================

def confluencia(d, alto, bajo, cierre, primeras, ultimas, horizonte):
    """
    Puntúa cada aparición por cuántas condiciones favorables se juntan.

    Ninguna de las tres decide sola; la pregunta es si al apilarlas el exceso
    sube de forma ordenada. Todas se calculan con información anterior a la
    vela de entrada.
    """
    s = sigma_causal(d["close"], horizonte).to_numpy()
    puntos = np.zeros(len(primeras))

    # Cuánto recorrió la ventana medido en sigmas: un barrido violento no es lo
    # mismo que uno que apenas asoma la nariz.
    recorrido = np.array([
        (max(alto[a:b + 1].max() - cierre[a], cierre[a] - bajo[a:b + 1].min())
         / cierre[a]) for a, b in zip(primeras, ultimas)])
    with np.errstate(invalid="ignore", divide="ignore"):
        en_sigmas = recorrido / s[ultimas]
    puntos += np.nan_to_num(en_sigmas > np.nanmedian(en_sigmas)).astype(float)

    # Que el cierre quede en el extremo de la ventana, no en el medio: es la
    # diferencia entre haber barrido y seguir, y haber barrido y volver.
    posicion = np.array([
        ((cierre[b] - bajo[a:b + 1].min())
         / max(alto[a:b + 1].max() - bajo[a:b + 1].min(), 1e-12))
        for a, b in zip(primeras, ultimas)])
    puntos += ((posicion > 0.7) | (posicion < 0.3)).astype(float)

    # Expansión reciente por encima de su mediana: con más recorrido el coste
    # pesa menos.
    expansion = d["close"].pct_change().abs().rolling(360).mean().to_numpy()
    puntos += (expansion[ultimas] > np.nanmedian(expansion[ultimas])).astype(float)
    return puntos, en_sigmas, posicion


def paso_estados(d, alto, bajo, cierre, primeras, ultimas, lado, comisiones,
                 horizonte, geometrias):
    print("[3] Tres estados: continuación, reversión o esperar\n")
    puntos, _, _ = confluencia(d, alto, bajo, cierre, primeras, ultimas, horizonte)

    filas = []
    for stop, ratio in geometrias:
        print(f"     stop {stop:.2%}, ratio {ratio:.1f}")
        print(f"     {'confluencia':<14} {'sentido':>12} {'n':>6} {'cobert.':>8} "
              f"{'%res':>6} {'acierto':>8} {'exceso':>8} {'neto':>9} {'meses':>9}")
        for minimo in (0, 1, 2, 3):
            sel = puntos >= minimo
            if sel.sum() < 100:
                continue
            for signo, etiqueta in ((1, "continuación"), (-1, "reversión")):
                des = ejecutar(alto, bajo, cierre, ultimas[sel], lado[sel] * signo,
                               stop, stop * ratio, horizonte)
                if des is None or len(des) < 100:
                    continue
                r = resumen(des, ratio, comisiones, d.index)
                c = r["consistencia"]
                filas.append({"stop": stop, "ratio": ratio, "minimo": minimo,
                              "sentido": etiqueta, "cobertura": float(sel.mean()), **r})
                marca = "  ←" if r["neto_medio"] > 0 else ""
                print(f"     {'≥ ' + str(minimo) + ' de 3':<14} {etiqueta:>12} "
                      f"{r['n']:>6,} {sel.mean():>7.0%} {1 - r['frac_tiempo']:>5.0%} "
                      f"{r['p_real']:>8.4f} {r['exceso']:>+8.4f} "
                      f"{r['neto_medio']:>+8.4%} {c['a_favor']:>3}/{c['periodos']:<4}"
                      f"{marca}")
        print()

    t = pd.DataFrame(filas)
    if t.empty:
        print("     (muestra insuficiente)\n")
        return t

    ordenadas = 0
    for (stop, ratio), g in t[t["sentido"] == "continuación"].groupby(["stop", "ratio"]):
        if len(g) > 1 and g.sort_values("minimo")["exceso"].is_monotonic_increasing:
            ordenadas += 1
    total = t[t["sentido"] == "continuación"].groupby(["stop", "ratio"]).ngroups
    print(f"     El exceso crece de forma ordenada en {ordenadas} de {total} "
          f"geometrías.")
    print(f"     Esa monotonía es la prueba que importa: un cruce suelto que sale")
    print(f"     positivo entre muchos aparece por azar, pero que el exceso suba")
    print(f"     escalón a escalón al exigir más confluencia, no.")
    print()
    return t


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--zona", default="nueva-york", choices=sorted(ventanas.ZONAS))
    parser.add_argument("--inicio", type=int, default=1, help="Hora local de arranque")
    parser.add_argument("--horas", type=int, default=3, help="Ancho de la ventana")
    parser.add_argument("--previa", type=int, default=480,
                        help="Minutos de referencia para el barrido")
    parser.add_argument("--horizonte", type=int, default=2160,
                        help="Velas de 10 s (2160 = 6 h)")
    parser.add_argument("--mercado", default="futuros-limite", choices=sorted(MERCADOS))
    args = parser.parse_args()
    comisiones = MERCADOS[args.mercado]

    d = cargar_datos(args.datos)
    print(f"{len(d):,} velas de 10 s   {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}")
    alto = d["high"].to_numpy(dtype=float)
    bajo = d["low"].to_numpy(dtype=float)
    cierre = d["close"].to_numpy(dtype=float)

    primeras, ultimas, lado = senal(d, alto, bajo, args.zona, args.inicio,
                                    args.horas, args.previa * 6)
    print(f"Señal: ventana {args.inicio:02d}:00-{(args.inicio + args.horas) % 24:02d}:00 "
          f"({args.zona}), barrido sobre {args.previa / 60:.0f} h previas")
    print(f"  {len(primeras):,} apariciones con barrido de un solo lado")
    print(f"  horizonte {args.horizonte * 10 / 3600:.0f} h, comisiones {args.mercado} "
          f"(gana {comisiones.del_ganador():.2%}, pierde {comisiones.del_perdedor():.2%})\n")

    ratios = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
    paso_ratio(d, alto, bajo, cierre, ultimas, lado, comisiones, args.horizonte,
               stops=[0.003, 0.005, 0.01], ratios=ratios)
    paso_sigma(d, alto, bajo, cierre, ultimas, lado, comisiones, args.horizonte,
               ratios=ratios, kas=[0.5, 1.0, 1.5])
    paso_estados(d, alto, bajo, cierre, primeras, ultimas, lado, comisiones,
                 args.horizonte,
                 geometrias=[(0.005, 0.5), (0.005, 1.0), (0.005, 2.0), (0.01, 1.0)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
