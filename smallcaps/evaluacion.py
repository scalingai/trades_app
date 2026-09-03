#!/usr/bin/env python3
"""La evaluación, lo más agresiva que se pueda SIN romper las reglas.

**LA PREGUNTA DE AGUS**: "la evaluación debería ser lo más agresivo que pueda y
tenga sentido sin romper las reglas". La evaluación y la cuenta fondeada tienen
reglas distintas —la consistencia sólo aplica en evaluación, los 3 días de 0,5%
sólo en fondeada— así que la configuración óptima de cada fase es distinta.
Esto mide la de la evaluación.

**QUE ES "AGRESIVO" ACA.** Llegar a los $1.500 del objetivo en la menor cantidad
de días posible, con la mayor probabilidad posible, y pagando la menor cantidad
de evaluaciones de $97. Tres palancas:

  · RIESGO POR PAPEL. Más riesgo = más rápido y más chance de quemar. El
    drawdown se mide INTRADIA y TREPA con el pico (confirmado por Agus y por
    los términos), así que el margen real es menor que el que sugería el
    cierre.
  · PAPELES POR DIA. Hoy cada cuenta toma UN papel. En evaluación puede tomar
    todos los del día: acumula más rápido y, como la consistencia es POR
    SIMBOLO, repartir en más símbolos es exactamente lo que la regla premia.
    El costo es la pérdida diaria: varios papeles perdiendo el mismo día suman.
  · TOPE POR SIMBOLO. La consistencia dice que la mejor POSICION —el total en
    un símbolo, con los tramos sumados— no puede ser más del 50% (FLEX) o 30%
    (MAX) del objetivo. Nuestra estrategia vive de la cola derecha: el mejor
    papel-día ronda el 115% del objetivo. La única forma de cumplir es CERRAR
    el símbolo cuando su ganancia del día toca el tope. Cuesta la cola —pero
    en evaluación la cola no sirve, porque rompe la regla.

**LAS REGLAS**, verificadas en tradethepool.com/the-program y /program-terms:

    plan    objetivo   drawdown   pérdida/día   consistencia   mín pos   plazo
    FLEX      6%         4%          2%             50%          10      ilimitado
    MAX       6%         3%          1%             30%          20      60 días

  Drawdown: intradía sobre equity proyectada (posiciones abiertas incluidas),
  trepa con el pico, y una vez que la equity llega a 3× la pérdida diaria el
  piso se clava en el balance inicial. Pérdida diaria: intradía; al tocarla se
  cierra todo y no se opera hasta el día siguiente (Daily Pause).

**COMO SE MIDE: ARRANQUES RODANTES.** Una sola corrida desde enero es UN camino.
Acá cada fecha con sesión del censo es un punto de partida, y se sigue hasta
pasar, quemar o vencer el plazo. Lo que sale es una DISTRIBUCION: qué porcentaje
pasa, cuántos días tarda la mediana, cuánto cuesta en evaluaciones.

**LA CUENTA ES SEPARABLE POR ESCALA**, y eso es lo que hace tratable el barrido.
`acciones = riesgo / (precio × stop%)`: la curva de equity de un papel-día a
riesgo R es la de riesgo 100 multiplicada por R/100, con los MISMOS tramos en
los mismos minutos (verificado: 1.044 tramos a $400 y a $250). Se calcula una
vez a riesgo 100 y se escala. Lo único que no escala es la comisión mínima de
$0,75 por orden, que se cobra aparte.

    python evaluacion.py
"""

from __future__ import annotations

import datetime as dt
import statistics
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

R_REF = 100.0
PISO, STOP, MAXT, DESDE = 2.0, 45.0, 40, 10.0
CORTE_H, CORTE_UMBRAL = 11.0, 5.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005
PODER = 25_000.0
EVAL_USD = 97.0

PLANES = {
    "flex": dict(objetivo=0.06, dd=0.04, dia=0.02, consistencia=0.50,
                 min_pos=10, dias_max=None),
    "max":  dict(objetivo=0.06, dd=0.03, dia=0.01, consistencia=0.30,
                 min_pos=20, dias_max=60),
}


def sig(d):
    return [i for i in señales_swing(d, desde=DESDE)
            if (d.bars[i][4] or 0) >= PISO]


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


# ------------------------------------------------------------ precomputo

def precomputar(pob, *, corte=True):
    """Por (ticker, fecha): la curva BRUTA por minuto a riesgo R_REF y los tramos.

    Bruta = marcada a mercado, sin comisiones ni el slippage del motor: la
    comisión real se cobra al final y depende de cuántos tramos llegaron a
    existir, que con un tope por símbolo puede ser menos que todos.
    """
    out = {}
    for d in pob:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=R_REF,
                    max_trades=MAXT, corte_h=CORTE_H if corte else None,
                    corte_umbral=CORTE_UMBRAL)
        if not j:
            continue
        det = j["detalle"]
        i0 = min((d.idx_en(t["h_ent"]) or 0) for t in det)
        mins, eqs = [], []
        for k in range(i0, len(d.bars)):
            b = d.bars[k]
            h = hora(b)
            if h > CIERRE_RTH:
                break
            px = b[4]
            if not px:
                continue
            eq = 0.0
            for t in det:
                if t["h_ent"] > h:
                    continue
                if t["h_sal"] is not None and t["h_sal"] <= h:
                    eq += t["acciones"] * (t["p_ent"] - t["p_sal"])
                else:
                    eq += t["acciones"] * (t["p_ent"] - px)
            mins.append(int(round(h * 60)))
            eqs.append(eq)
        if not mins:
            continue
        out[(d.ticker, d.d)] = {
            "min": np.array(mins, dtype=np.int64),
            "eq": np.array(eqs, dtype=np.float64),
            "tramos": [(int(round(t["h_ent"] * 60)), t["acciones"]) for t in det],
        }
    return out


# ------------------------------------------------------------ por config

def _papel(pre, escala, tope):
    """Un papel-día a este riesgo, con el tope por símbolo aplicado.

    Si la equity del símbolo toca `tope`, se cierra todo ahí y el símbolo no se
    opera más ese día. Los tramos que habrían entrado después no existen.
    """
    eq = pre["eq"] * escala
    mins = pre["min"]
    capado = False
    if tope is not None:
        hit = np.nonzero(eq >= tope)[0]
        if len(hit):
            k = int(hit[0])
            eq, mins, capado = eq[:k + 1], mins[:k + 1], True
    m_fin = int(mins[-1])
    tramos = [(m, a * escala) for m, a in pre["tramos"] if m <= m_fin]
    return {"min": mins, "eq": eq, "tramos": tramos, "capado": capado}


def _rellenar(grid, mins, eq):
    """La curva de un papel sobre la grilla del día: 0 antes de entrar, el
    último valor después de salir. Es lo que vale la posición en cada minuto."""
    idx = np.searchsorted(mins, grid, side="right") - 1
    return np.where(idx < 0, 0.0, eq[np.clip(idx, 0, len(eq) - 1)])


def dia_config(pres, escala, tope, lim_dia):
    """Todos los papeles que toma la cuenta ese día, sumados minuto a minuto,
    con la Daily Pause aplicada. Devuelve lo que la cuenta ve."""
    papeles = [_papel(p, escala, tope) for p in pres]
    m0 = min(int(p["min"][0]) for p in papeles)
    m1 = max(int(p["min"][-1]) for p in papeles)
    grid = np.arange(m0, m1 + 1)
    curvas = [_rellenar(grid, p["min"], p["eq"]) for p in papeles]
    total = np.sum(curvas, axis=0)

    pausado = False
    pausa = np.nonzero(total <= -lim_dia)[0]
    if len(pausa):
        k = int(pausa[0])
        grid, total = grid[:k + 1], total[:k + 1]
        curvas = [c[:k + 1] for c in curvas]
        pausado = True
    m_fin = int(grid[-1])
    bruto = float(total[-1])
    com = sum(comision(a) for p in papeles for m, a in p["tramos"] if m <= m_fin)
    n_tramos = sum(1 for p in papeles for m, _ in p["tramos"] if m <= m_fin)
    mejor = max(float(c[-1]) for c in curvas)
    return {"eq": total, "neto": bruto - com, "mejor": mejor,
            "tramos": n_tramos, "pausado": pausado,
            "capados": sum(p["capado"] for p in papeles)}


def construir_dias(pre, por_fecha, *, escala, tope, lim_dia, papeles):
    """La vista de la cuenta para cada fecha con sesión, bajo esta config."""
    out = {}
    for f, tks in por_fecha.items():
        pres = [pre[(tk, f)] for tk in tks if (tk, f) in pre]
        if not pres:
            continue
        if papeles != "todos":
            pres = pres[:int(papeles)]
        out[f] = dia_config(pres, escala, tope, lim_dia)
    return out


# ------------------------------------------------------------ la cuenta

def evaluar_desde(i0, fechas, dias, plan):
    """Una evaluación que arranca en fechas[i0] y sigue hasta terminar."""
    OBJ = PODER * plan["objetivo"]
    TOPE = PODER * plan["dd"]
    LIM = PODER * plan["dia"]
    LOCK = 3 * LIM
    f0 = dt.date.fromisoformat(fechas[i0])
    balance = pico = 0.0
    mejor = 0.0
    tramos = sesiones = pausas = 0
    for i in range(i0, len(fechas)):
        f = fechas[i]
        cal = (dt.date.fromisoformat(f) - f0).days
        if plan["dias_max"] and cal > plan["dias_max"]:
            return {"res": "vencida", "dias": cal, "sesiones": sesiones}
        d = dias.get(f)
        if d is None:
            continue
        eq = balance + d["eq"]
        # El piso TREPA con el pico y, una vez que la equity llegó a 3×DL, se
        # clava en el balance inicial. Confirmado por Agus y por los términos.
        runmax = np.maximum.accumulate(np.maximum(eq, pico))
        piso = np.where(runmax >= LOCK, 0.0, runmax - TOPE)
        if np.any(eq <= piso):
            return {"res": "quema", "dias": cal, "sesiones": sesiones + 1}
        pico = max(pico, float(eq.max()))
        balance += d["neto"]
        pico = max(pico, balance)
        mejor = max(mejor, d["mejor"])
        tramos += d["tramos"]
        pausas += 1 if d["pausado"] else 0
        sesiones += 1
        if balance >= OBJ:
            return {"res": "pasa", "dias": cal, "sesiones": sesiones,
                    "mejor_pct": 100 * mejor / OBJ,
                    "limpia": mejor <= plan["consistencia"] * OBJ
                              and tramos >= plan["min_pos"],
                    "tramos": tramos, "pausas": pausas}
    return {"res": "abierta", "dias": None, "sesiones": sesiones}


def correr(pre, por_fecha, fechas, *, plan_nombre, riesgo, tope_frac, papeles):
    plan = PLANES[plan_nombre]
    OBJ = PODER * plan["objetivo"]
    escala = riesgo / R_REF
    tope = tope_frac * plan["consistencia"] * OBJ if tope_frac else None
    dias = construir_dias(pre, por_fecha, escala=escala, tope=tope,
                          lim_dia=PODER * plan["dia"], papeles=papeles)
    res = [evaluar_desde(i, fechas, dias, plan) for i in range(len(fechas))]
    # Los arranques que quedaron abiertos (se acabó la muestra) no cuentan
    # ni a favor ni en contra: no se sabe cómo terminaban.
    cerr = [r for r in res if r["res"] != "abierta"]
    n = len(cerr) or 1
    pasa = [r for r in cerr if r["res"] == "pasa"]
    limpia = [r for r in pasa if r["limpia"]]
    quema = sum(1 for r in cerr if r["res"] == "quema")
    venc = sum(1 for r in cerr if r["res"] == "vencida")
    p_limpia = len(limpia) / n
    return {
        "n": len(cerr), "pasa": len(pasa) / n, "limpia": p_limpia,
        "quema": quema / n, "vencida": venc / n,
        "dias": statistics.median(r["dias"] for r in limpia) if limpia else None,
        "dias_p75": (sorted(r["dias"] for r in limpia)[int(0.75 * len(limpia))]
                     if limpia else None),
        "ses": statistics.median(r["sesiones"] for r in limpia) if limpia else None,
        "mejor": statistics.median(r["mejor_pct"] for r in pasa) if pasa else None,
        # Cuántas evaluaciones hay que comprar, en promedio, para pasar una
        # limpia. Es el costo real de la agresividad.
        "costo": EVAL_USD / p_limpia if p_limpia else None,
    }


def fila(etq, r):
    f = lambda v, d=0: ("—" if v is None else f"{v:.{d}f}")
    print("  {:<28} {:>4} {:>6} {:>7} {:>6} {:>6} {:>7} {:>6} {:>6} {:>7} {:>8}".format(
        etq, r["n"], f"{100 * r['pasa']:.0f}%", f"{100 * r['limpia']:.0f}%",
        f"{100 * r['quema']:.0f}%", f"{100 * r['vencida']:.0f}%",
        f(r["dias"]), f(r["dias_p75"]), f(r["ses"]),
        (f"{r['mejor']:.0f}%" if r["mejor"] is not None else "—"),
        ("$" + f(r["costo"]) if r["costo"] else "—")))


def cabecera():
    print("  {:<28} {:>4} {:>6} {:>7} {:>6} {:>6} {:>7} {:>6} {:>6} {:>7} {:>8}".format(
        "config", "n", "pasa", "limpia", "quema", "vence", "días", "p75",
        "ses", "mejor%", "$/pase"))
    print("  " + "-" * 104)


if __name__ == "__main__":
    dias_u = universo()
    pob = [d for d in poblacion(dias_u, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    print(f"\n  LA EVALUACION, LO MAS AGRESIVA QUE SE PUEDA · {len(pob)} días "
          f"reclaim del censo · cuenta ${PODER:,.0f}")
    print("  cada fecha con sesión es un arranque; se sigue hasta pasar, quemar "
          "o vencer el plazo.\n")

    pre = precomputar(pob, corte=True)
    por_fecha = defaultdict(list)
    for tk, f in sorted(pre):
        por_fecha[f].append(tk)
    fechas = sorted(por_fecha)
    print(f"  {len(fechas)} fechas con sesión · {len(pre)} papeles-día\n")

    for plan in ("flex", "max"):
        p = PLANES[plan]
        print(f"\n  ===== {plan.upper()} · objetivo ${PODER * p['objetivo']:,.0f} · "
              f"drawdown ${PODER * p['dd']:,.0f} · día ${PODER * p['dia']:,.0f} · "
              f"consistencia {p['consistencia']:.0%} · mín {p['min_pos']} posiciones"
              + (f" · {p['dias_max']} días" if p["dias_max"] else "") + " =====")
        for papeles in ("1", "2", "todos"):
            print(f"\n  -- {papeles} papel(es) por día --")
            cabecera()
            for tope_frac in (None, 0.95):
                for riesgo in (100, 150, 200, 300, 400, 500):
                    r = correr(pre, por_fecha, fechas, plan_nombre=plan,
                               riesgo=riesgo, tope_frac=tope_frac, papeles=papeles)
                    etq = f"${riesgo} " + ("tope 95%" if tope_frac else "sin tope")
                    fila(etq, r)

    print("""
  COMO SE LEE
  'pasa' es llegar al objetivo. 'limpia' es llegar SIN que el mejor símbolo-día
  supere el límite de consistencia y con las posiciones mínimas — es la única
  que cuenta. 'mejor%' es cuánto del objetivo puso el mejor símbolo-día (límite:
  50% FLEX, 30% MAX). '$/pase' es cuántos dólares en evaluaciones cuesta, en
  promedio, conseguir un pase limpio: 97 / P(limpia).
""")
