#!/usr/bin/env python3
"""¿Se puede saber ANTES cuáles se derrumban? Una variable por vez, con nulo.

LA PREGUNTA. El sistema opera todos los días `reclaim`. La mitad se derrumba
lindo y la otra mitad no. Si supiéramos cuáles antes de entrar, el retorno
cambia de escala. La sospecha del proyecto es que eso no está en el técnico
—catorce familias murieron ahí— sino en la ESTRUCTURA: cuánto diluyó la empresa,
cuánta caja le queda, si tiene shelf efectivo. Eso vive en EDGAR y ya está en la
base.

CÓMO SE MIDE, Y POR QUÉ ASÍ. Con ~450 estrategias probadas en este proyecto, la
probabilidad de encontrar algo por azar es enorme. Entonces:

  · Una variable POR VEZ. Nada de combinar: combinar es donde vive el
    sobreajuste, y sin significancia univariada no hay nada que combinar.
  · Corte por MEDIANA, no por un umbral optimizado. Un umbral elegido mirando el
    resultado ya es sobreajuste aunque la variable no sirva.
  · NULO POR PERMUTACIÓN: se baraja la variable contra los resultados mil veces
    y se mira dónde cae la diferencia real. Es la única forma de saber si un
    número lindo es señal o es haber mirado muchas veces.
  · CORRECCIÓN POR MÚLTIPLES PRUEBAS: con N variables, el umbral de p no es
    0,05 sino 0,05/N. Sin esto, probar veinte variables garantiza encontrar una.
  · DENTRO Y FUERA DE MUESTRA por fecha. Lo que no sobrevive la segunda mitad
    del tiempo no existe.

QUÉ ES "DERRUMBARSE". La caída máxima desde el precio de las 10:00 hasta el
mínimo del resto de la rueda, en % — que es literalmente de dónde sale la plata
de un short. No se usa el PnL de la estrategia a propósito: eso mezclaría el
mérito de la variable con el de la gestión de stops.

    python test_quien_se_derrumba.py
"""

from __future__ import annotations

import random
import sqlite3
import statistics
import sys

sys.path.insert(0, ".")

import config
from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PERMUTACIONES = 2000
DESDE = 10.0
random.seed(20260901)      # reproducible: el nulo no puede cambiar entre corridas


# ---------------------------------------------------------------- estructura

def estructura():
    """Lo último que EDGAR sabía de cada ticker ANTES de cada día de evento.

    Se indexa por ticker y se busca la fila más reciente con fecha <= al día.
    Tomar la fila del propio día ya sería mirar un dato que puede haberse
    publicado después de la apertura.
    """
    c = sqlite3.connect(config.bars_db_path())
    cols = [x[1] for x in c.execute("PRAGMA table_info(event_structure)")]
    por_ticker = {}
    for fila in c.execute(f"SELECT {','.join(cols)} FROM event_structure ORDER BY d"):
        r = dict(zip(cols, fila))
        por_ticker.setdefault(r["ticker"], []).append(r)
    c.close()
    return por_ticker


def estructura_de(por_ticker, ticker, d):
    prev = None
    for r in por_ticker.get(ticker, []):
        if r["d"] <= d:
            prev = r
        else:
            break
    return prev or {}


# -------------------------------------------------------------------- rasgos

def rasgos(dia, est):
    """Todo lo que se sabe a las 10:00. Ni un dato de después."""
    i10 = dia.idx_en(DESDE)
    if i10 is None:
        return None
    px10 = dia.bars[i10][4]
    if not px10:
        return None

    pm = [b for b in dia.bars if hora(b) < 9.5]
    vol_pm = sum((b[5] or 0) for b in pm)
    dol_pm = sum((b[5] or 0) * (b[4] or 0) for b in pm)
    rth_hasta_10 = [b for b in dia.bars if 9.5 <= hora(b) <= DESDE]
    vol_10 = sum((b[5] or 0) for b in rth_hasta_10)

    r = {
        "expansion": dia.expansion_pct,
        "gap": (100.0 * (dia.rth_open - dia.prev_close) / dia.prev_close
                if dia.rth_open and dia.prev_close else None),
        "precio": px10,
        "vs_pm_high": (100.0 * (px10 - dia.pm_high) / dia.pm_high
                       if dia.pm_high else None),
        "vs_vwap": (100.0 * (px10 - dia.vwap[i10]) / dia.vwap[i10]
                    if dia.vwap and dia.vwap[i10] else None),
        "vol_premarket": vol_pm,
        "dolar_premarket": dol_pm,
        "vol_primera_media_hora": vol_10,
        "ratio_volumen": dia.ratio_volumen,
    }
    for k in ("shares_outstanding", "dilution_3m_pct", "dilution_12m_pct",
              "reverse_splits_12m", "cash_usd", "runway_months",
              "pricing_filings_12m", "days_since_last_pricing",
              "shelf_effective", "dilutive_8k_12m", "n_warnings"):
        r[k] = est.get(k)
    return r


def derrumbe(dia):
    """Caída máxima desde el precio de las 10:00 hasta el mínimo de la rueda."""
    i10 = dia.idx_en(DESDE)
    if i10 is None:
        return None
    px10 = dia.bars[i10][4]
    if not px10:
        return None
    lows = [b[3] for b in dia.bars[i10 + 1:]
            if b[3] and hora(b) <= CIERRE_RTH]
    if not lows:
        return None
    return 100.0 * (px10 - min(lows)) / px10


# ------------------------------------------------------------------ el test

def separa(valores, objetivos):
    """Diferencia de derrumbe medio entre la mitad alta y la baja."""
    pares = [(v, o) for v, o in zip(valores, objetivos) if v is not None]
    if len(pares) < 40:
        return None
    med = statistics.median(v for v, _ in pares)
    alto = [o for v, o in pares if v > med]
    bajo = [o for v, o in pares if v <= med]
    if len(alto) < 15 or len(bajo) < 15:
        return None
    return {"n": len(pares), "alto": statistics.mean(alto),
            "bajo": statistics.mean(bajo),
            "delta": statistics.mean(alto) - statistics.mean(bajo)}


def p_permutacion(valores, objetivos, delta_real):
    """¿Cuántas veces el azar da una diferencia así de grande?"""
    pares = [(v, o) for v, o in zip(valores, objetivos) if v is not None]
    obs = [o for _, o in pares]
    vals = [v for v, _ in pares]
    med = statistics.median(vals)
    mascara = [v > med for v in vals]
    n_alto = sum(mascara)
    if n_alto == 0 or n_alto == len(obs):
        return 1.0
    extremos = 0
    for _ in range(PERMUTACIONES):
        random.shuffle(obs)
        a = statistics.mean(obs[:n_alto])
        b = statistics.mean(obs[n_alto:])
        if abs(a - b) >= abs(delta_real):
            extremos += 1
    return (extremos + 1) / (PERMUTACIONES + 1)


def evaluar(dias, nombre):
    est = estructura()
    filas = []
    for d in dias:
        y = derrumbe(d)
        if y is None:
            continue
        x = rasgos(d, estructura_de(est, d.ticker, d.d))
        if x is None:
            continue
        filas.append((d.d, x, y))
    if len(filas) < 60:
        print(f"\n  {nombre}: sólo {len(filas)} días, no alcanza para medir.")
        return

    filas.sort(key=lambda f: f[0])
    corte = len(filas) // 2
    mitades = {"P1 (primera mitad)": filas[:corte],
               "P2 (segunda mitad)": filas[corte:]}
    campos = list(filas[0][1].keys())
    umbral = 0.05 / len(campos)

    print(f"\n\n  {nombre}  ·  {len(filas)} días  ·  "
          f"derrumbe medio {statistics.mean(y for _, _, y in filas):.1f}%")
    print(f"  {len(campos)} variables probadas -> umbral de p corregido: "
          f"{umbral:.4f}  (0,05/{len(campos)})")
    print()
    print("  {:<26} {:>7} {:>9} {:>9} {:>9} {:>9} {:>8}".format(
        "variable", "n", "alto", "bajo", "delta", "p", "P1/P2"))
    print("  " + "-" * 84)

    resultados = []
    for campo in campos:
        vals = [x.get(campo) for _, x, _ in filas]
        objs = [y for _, _, y in filas]
        s = separa(vals, objs)
        if not s:
            continue
        p = p_permutacion(vals, objs, s["delta"])
        # ¿El signo se repite en las dos mitades del tiempo?
        signos = []
        for _, sub in mitades.items():
            s2 = separa([x.get(campo) for _, x, _ in sub],
                        [y for _, _, y in sub])
            signos.append(None if not s2 else (s2["delta"] > 0))
        coherente = (signos[0] is not None and signos[0] == signos[1])
        resultados.append((p, campo, s, coherente))

    resultados.sort()
    for p, campo, s, coherente in resultados:
        marca = ""
        if p < umbral and coherente:
            marca = "  <== SOBREVIVE"
        elif p < 0.05 and not coherente:
            marca = "  (cambia de signo)"
        print("  {:<26} {:>7} {:>8.1f}% {:>8.1f}% {:>+8.1f}% {:>9.4f} {:>8}{}".format(
            campo, s["n"], s["alto"], s["bajo"], s["delta"], p,
            "igual" if coherente else "distinto", marca))


universo_dias = universo()
pob = poblacion(universo_dias, min_ratio_vol=0.0, min_expansion=0.0,
                min_dolar=0.0, max_float=None)
evaluar(pob, "TODOS LOS DIAS DE EVENTO")

reclaim = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]
evaluar(reclaim, "SOLO LOS DIAS RECLAIM (los que operamos)")

print()
print("  'delta' es cuánto MAS se derrumba la mitad alta de la variable.")
print("  'P1/P2' dice si el signo se repite en las dos mitades del tiempo:")
print("  una variable que cambia de signo entre mitades no es una variable,")
print("  es ruido que en una mitad salió para un lado.")
