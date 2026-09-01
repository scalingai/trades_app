#!/usr/bin/env python3
"""Indicadores técnicos como FILTRO de entrada, medidos en centavos por acción.

**Por qué se rehace algo que ya dio que no.** La familia de mecanismos se midió
en agosto y concluyó que el gatillo no importa —un placebo por reloj le ganó a
14 de 16—. Esa conclusión tiene dos vicios que la invalidan en parte: el motor
tenía look-ahead en el presupuesto de riesgo, y la métrica era `ret/nom`, que
por construcción es ciega al precio del papel. Con el motor arreglado y la
métrica correcta, la pregunta vuelve a estar abierta.

**Y por qué esto es peligroso.** Combinar indicadores es el camino clásico al
sobreajuste: con suficientes combinaciones siempre aparece una que se ve bien.
Ya probamos ~450 variantes y el p-valor de permutación del hallazgo principal
(0,6%) NO sobrevive la corrección por búsqueda múltiple. Agregar combinatoria
sin control empeora eso, no lo mejora.

Por eso el nulo está adentro del experimento desde el principio: por cada
indicador con tesis se generan FILTROS ALEATORIOS que aceptan la misma
proporción de entradas. Si el mejor indicador real no le gana al mejor de los
azarosos, lo que encontramos es la búsqueda y no una señal.

Los filtros aplican SOBRE la señal de swing, no la reemplazan: aceptan o
rechazan cada entrada candidata. Todos miran sólo `bars[:i+1]`.

    SMALLCAPS_CENSO=1 python fam_indicadores.py
"""

from __future__ import annotations

import itertools
import random
import statistics
import sys

import motor
from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES, R, PISO = 22.9, 50.0, 2.0


# --------------------------------------------------------------- indicadores
# Cada uno recibe (dia, i) y devuelve True si ACEPTA la entrada. Sólo mira
# barras hasta `i` inclusive. La tesis va en el docstring, ANTES del número.

def _cierres(dia, i, n):
    return [b[4] for b in dia.bars[max(0, i - n + 1):i + 1] if b[4]]


def _vols(dia, i, n):
    return [b[5] or 0 for b in dia.bars[max(0, i - n + 1):i + 1]]


def ind_bajo_vwap(dia, i):
    """El precio ya perdió el VWAP: el promedio del día juega en contra."""
    return bool(dia.bars[i][4] and dia.bars[i][4] < dia.vwap[i])


def ind_sobre_vwap(dia, i):
    """El contrario. Se incluye para que el par sea simétrico y el resultado no
    dependa de qué lado se le ocurrió probar a uno."""
    return bool(dia.bars[i][4] and dia.bars[i][4] > dia.vwap[i])


def ind_max_viejo(dia, i):
    """El máximo del día tiene más de 20 minutos: el impulso se agotó."""
    return dia.edad_max[i] >= 20


def ind_rsi_alto(dia, i, n=14, umbral=70):
    """RSI sobrecomprado: la subida fue rápida y sin pausa."""
    c = _cierres(dia, i, n + 1)
    if len(c) < n + 1:
        return False
    sub = sum(max(0.0, c[k] - c[k - 1]) for k in range(1, len(c)))
    baj = sum(max(0.0, c[k - 1] - c[k]) for k in range(1, len(c)))
    if sub + baj == 0:
        return False
    return 100 * sub / (sub + baj) >= umbral


def ind_lejos_ma20(dia, i, pct=10):
    """El precio está >10% arriba de su media de 20 minutos: extendido."""
    c = _cierres(dia, i, 20)
    if len(c) < 20 or not dia.bars[i][4]:
        return False
    ma = statistics.mean(c)
    return ma > 0 and (dia.bars[i][4] / ma - 1) * 100 >= pct


def ind_volumen_cae(dia, i):
    """El volumen de los últimos 5 minutos cayó contra los 20 previos: el
    interés se retira mientras el precio todavía está arriba."""
    v5, v20 = _vols(dia, i, 5), _vols(dia, i, 20)
    if len(v20) < 20:
        return False
    return statistics.mean(v5) < statistics.mean(v20) * 0.7


def ind_volumen_sube(dia, i):
    """El contrario del anterior, por la misma razón de simetría."""
    v5, v20 = _vols(dia, i, 5), _vols(dia, i, 20)
    if len(v20) < 20:
        return False
    return statistics.mean(v5) > statistics.mean(v20) * 1.3


def ind_rango_ancho(dia, i, n=10):
    """La barra tiene rango mayor al doble de la mediana reciente: volatilidad
    expandiéndose, que suele marcar el clímax."""
    r = [(b[2] - b[3]) for b in dia.bars[max(0, i - n):i] if b[2] and b[3]]
    b = dia.bars[i]
    if len(r) < n // 2 or not (b[2] and b[3]):
        return False
    m = statistics.median(r)
    return m > 0 and (b[2] - b[3]) >= 2 * m


def ind_cierra_abajo(dia, i):
    """La barra cierra en el tercio inferior de su rango: los vendedores se
    quedaron con el minuto."""
    b = dia.bars[i]
    if not (b[2] and b[3] and b[4]) or b[2] <= b[3]:
        return False
    return (b[4] - b[3]) / (b[2] - b[3]) <= 0.33


def ind_dos_rojas(dia, i):
    """Dos minutos consecutivos cerrando por debajo del anterior."""
    c = _cierres(dia, i, 3)
    return len(c) == 3 and c[2] < c[1] < c[0]


INDICADORES = [
    ("bajo vwap", ind_bajo_vwap),
    ("sobre vwap", ind_sobre_vwap),
    ("maximo viejo (20m)", ind_max_viejo),
    ("rsi >= 70", ind_rsi_alto),
    ("lejos de ma20 (>10%)", ind_lejos_ma20),
    ("volumen cae", ind_volumen_cae),
    ("volumen sube", ind_volumen_sube),
    ("rango ancho", ind_rango_ancho),
    ("cierra en el tercio bajo", ind_cierra_abajo),
    ("dos rojas seguidas", ind_dos_rojas),
]


# ------------------------------------------------------------------ medición
def señal(filtros):
    def f(d):
        out = []
        for i in señales_swing(d, desde=10.0):
            if (d.bars[i][4] or 0) < PISO:
                continue
            if all(fn(d, i) for fn in filtros):
                out.append(i)
        return out
    return f


def medir(pob, filtros):
    S, aceptadas, totales = [], 0, 0
    for d in pob:
        cand = [i for i in señales_swing(d, desde=10.0)
                if (d.bars[i][4] or 0) >= PISO]
        totales += len(cand)
        aceptadas += sum(1 for i in cand if all(fn(d, i) for fn in filtros))
        j = jornada(d, señal(filtros), lado="short", stop_pct=45.0, riesgo=R,
                    max_trades=40)
        if not j:
            continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                       -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da
            pa = max(pa, a)
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"]})
    if len(S) < 15:
        return None

    def c(g):
        if len(g) < 12:
            return None
        b = statistics.mean(x["pnl"] for x in g)
        a = statistics.mean(x["acc"] for x in g)
        return 100 * b / a if a else 0

    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)
    ses = len({x["d"] for x in S}) / MESES
    return {"n": len(S), "ses": ses, "tr": sum(x["tr"] for x in S) / MESES,
            "cents": 100 * b / acc if acc else 0, "mes": b * ses,
            "tasa": aceptadas / totales if totales else 0,
            "p1": c([x for x in S if x["d"] < motor.CORTE]),
            "p2": c([x for x in S if x["d"] >= motor.CORTE])}


def filtro_azar(tasa, semilla):
    """Acepta al azar la misma proporción de entradas que el indicador real.

    Es el control que hace honesto todo lo demás: si un indicador con tesis no
    le gana a una moneda que descarta la misma cantidad de entradas, lo que
    mide no es la tesis sino cuántas entradas saca. La decisión se memoiza por
    (ticker, día, barra) para que sea determinística dentro de una corrida.
    """
    rnd = random.Random(semilla)
    memo = {}

    def f(dia, i):
        k = (dia.ticker, dia.d, i)
        if k not in memo:
            memo[k] = rnd.random() < tasa
        return memo[k]
    return f


def fila(lab, r, marca=""):
    f1 = f"{r['p1']:>6.0f}c" if r["p1"] is not None else f"{'s/dato':>7}"
    f2 = f"{r['p2']:>6.0f}c" if r["p2"] is not None else f"{'s/dato':>7}"
    return (f"  {lab:<32} {r['tasa']:>6.0%} {r['ses']:>6.1f} {r['tr']:>6.0f} "
            f"{r['cents']:>7.0f}c {f1} {f2} {r['mes']:>+10.2f}{marca}")


def main() -> int:
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    print(f"  POBLACIÓN: reclaim · sin filtro de expansión · precio ≥ ${PISO:.0f}")
    print(f"  {len(pob)} días. Los filtros ACEPTAN o RECHAZAN cada entrada del swing.\n")
    cab = (f"  {'filtro':<32} {'acepta':>6} {'ses/m':>6} {'tr/m':>6} {'muerte':>8} "
           f"{'P1':>7} {'P2':>7} {'bruto/mes':>10}")
    print(cab)
    print("  " + "-" * 92)

    base = medir(pob, [])
    print(fila("SIN FILTRO (la base)", base))
    print()

    solos = {}
    for lab, fn in INDICADORES:
        r = medir(pob, [fn])
        if not r:
            print(f"  {lab:<32}   (muestra corta)")
            continue
        solos[lab] = (r, fn)
        print(fila(lab, r))

    print("\n  EL NULO: filtros al azar que aceptan la misma proporción\n")
    nulos = []
    for t in sorted({round(r["tasa"], 2) for r, _ in solos.values()}):
        for s in range(12):
            r = medir(pob, [filtro_azar(t, s * 7 + int(t * 100))])
            if r:
                nulos.append(r["cents"])
    nulos.sort()
    if nulos and solos:
        q = lambda p: nulos[int(p * (len(nulos) - 1))]
        print(f"  {len(nulos)} filtros aleatorios  ·  p50 {q(.50):.0f}c  "
              f"p90 {q(.90):.0f}c  p95 {q(.95):.0f}c  MÁXIMO {nulos[-1]:.0f}c")
        mejor = max(solos.items(), key=lambda kv: kv[1][0]["cents"])
        print(f"\n  mejor indicador con tesis:  {mejor[0]:<28} {mejor[1][0]['cents']:.0f}c")
        print(f"  mejor filtro al azar:        {'(sin tesis)':<28} {nulos[-1]:.0f}c")
        print("  -> " + ("le gana al azar" if mejor[1][0]["cents"] > nulos[-1]
                         else "NO le gana al azar"))

    print("\n  COMBINACIONES DE DOS\n")
    print(cab)
    print("  " + "-" * 92)
    pares = []
    for (a, fa), (b, fb) in itertools.combinations(INDICADORES, 2):
        r = medir(pob, [fa, fb])
        if r and r["ses"] >= 2.0:
            pares.append((r["cents"], f"{a} + {b}", r))
    pares.sort(reverse=True)
    for c, lab, r in pares[:10]:
        print(fila(lab, r))
    if pares and nulos:
        print(f"""
  El mejor par da {pares[0][0]:.0f}c contra {nulos[-1]:.0f}c del mejor filtro al azar.
  Pero se probaron {len(pares)} pares y sólo {len(nulos)} nulos: para que la
  comparación sea justa hay que enfrentar máximo contra máximo con el MISMO
  número de intentos. Con más intentos, el máximo del azar sube.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
