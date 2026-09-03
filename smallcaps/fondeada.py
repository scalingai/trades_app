#!/usr/bin/env python3
"""La cuenta FLEX ya fondeada: ¿se puede COBRAR, y con qué configuración?

**DE DONDE VIENE.** `cuentas.py` mostró que con un papel por día la cuenta
fondeada acumula plata que no se puede retirar: la regla de "3 días con 0,5%
($125) dentro de cualquier ventana de 14 días" no se cumple nunca, porque la
estrategia opera 2 a 7 veces por mes y los días buenos caen demasiado
separados. Con más riesgo se cumple, pero quema.

**LA PALANCA QUE FALTABA PROBAR: MAS PAPELES POR DIA.** Un día con tres papeles
suma sus resultados: es más fácil que el TOTAL del día pase de $125 aunque cada
papel dé poco. Y son más días con operativa. El costo es el de siempre —más
exposición el mismo día contra la pérdida diaria de $500 y el drawdown de
$1.000, intradía y trepando con el pico.

**COMO SE MIDE.** Arranques rodantes, igual que en `evaluacion.py`: cada fecha
con sesión es una cuenta que acaba de fondearse, y se la sigue 180 días
calendario. Sale la probabilidad de cobrar al menos una vez, cuánto, cuándo, y
cuántas se queman.

**UN SUPUESTO QUE HAY QUE DECIR.** Qué pasa con el piso del drawdown después de
un retiro no está escrito con claridad. Acá se asume que el pico vuelve a
medirse desde el nuevo balance (cero) — o sea, que retirar "reinicia" el
drawdown. Si en realidad el piso quedara clavado en breakeven (como dice el
lock de 3×DL), retirar dejaría la cuenta a un mal día de morir, y eso cambiaría
la estrategia de retiro entera. Es la pregunta 5 para soporte, si algún día se
manda el mail.

    python fondeada.py
"""

from __future__ import annotations

import datetime as dt
import statistics
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")

import evaluacion as E
from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PODER = E.PODER
TOPE_DD = PODER * 0.04
LIM_DIA = PODER * 0.02
LOCK = 3 * LIM_DIA
SPLIT = 0.70
MIN_RETIRO = 300.0
DIAS_ENTRE = 14
DIA_BUENO = 0.005 * PODER
BUENOS = 3
VENTANA = 14
HORIZONTE = 180          # días calendario que se sigue a cada cuenta


def puede(fecha, balance, base, buenos):
    if balance < MIN_RETIRO:
        return "menos de $300"
    if (dt.date.fromisoformat(fecha) - dt.date.fromisoformat(base)).days < DIAS_ENTRE:
        return "faltan días"
    fs = sorted(dt.date.fromisoformat(x) for x in buenos)
    if not any(sum(1 for y in fs if 0 <= (y - x).days < VENTANA) >= BUENOS
               for x in fs):
        return "días de 0,5%"
    return None


def fondeada_desde(i0, fechas, dias):
    f0 = fechas[i0]
    d0 = dt.date.fromisoformat(f0)
    balance = pico = 0.0
    base = f0
    buenos = []
    retirado = 0.0
    n_ret = 0
    primer = None
    trabas = defaultdict(int)
    pausas = 0
    for i in range(i0, len(fechas)):
        f = fechas[i]
        cal = (dt.date.fromisoformat(f) - d0).days
        if cal > HORIZONTE:
            break
        d = dias.get(f)
        if d is None:
            continue
        eq = balance + d["eq"]
        runmax = np.maximum.accumulate(np.maximum(eq, pico))
        piso = np.where(runmax >= LOCK, 0.0, runmax - TOPE_DD)
        if np.any(eq <= piso):
            return {"res": "quema", "dias": cal, "retirado": retirado,
                    "n_ret": n_ret, "primer": primer, "trabas": trabas}
        pico = max(pico, float(eq.max()))
        balance += d["neto"]
        pico = max(pico, balance)
        pausas += 1 if d["pausado"] else 0
        if d["neto"] >= DIA_BUENO:
            buenos.append(f)
        m = puede(f, balance, base, buenos)
        if m is None:
            sacar = balance * SPLIT
            retirado += sacar
            n_ret += 1
            primer = primer if primer is not None else cal
            balance = pico = 0.0      # supuesto: el drawdown se reinicia
            base = f
        else:
            trabas[m] += 1
    return {"res": "viva", "dias": HORIZONTE, "retirado": retirado,
            "n_ret": n_ret, "primer": primer, "trabas": trabas, "final": balance}


def correr(pre, por_fecha, fechas, *, riesgo, papeles):
    dias = E.construir_dias(pre, por_fecha, escala=riesgo / E.R_REF, tope=None,
                            lim_dia=LIM_DIA, papeles=papeles)
    # Sólo arranques con 180 días de datos por delante: los últimos no se
    # pueden seguir entero y sesgarían "cuánto se cobra en 180 días".
    ult = dt.date.fromisoformat(fechas[-1])
    res = [fondeada_desde(i, fechas, dias) for i in range(len(fechas))
           if (ult - dt.date.fromisoformat(fechas[i])).days >= HORIZONTE]
    n = len(res) or 1
    cobra = [r for r in res if r["n_ret"] > 0]
    trabas = defaultdict(int)
    for r in res:
        for k, v in r["trabas"].items():
            trabas[k] += v
    return {
        "n": len(res),
        "cobra": len(cobra) / n,
        "quema": sum(1 for r in res if r["res"] == "quema") / n,
        "retirado": statistics.median(r["retirado"] for r in res),
        "retirado_p75": sorted(r["retirado"] for r in res)[int(0.75 * len(res))],
        "primer": statistics.median(r["primer"] for r in cobra) if cobra else None,
        "n_ret": statistics.mean(r["n_ret"] for r in res),
        "trabas": dict(trabas),
    }


if __name__ == "__main__":
    dias_u = universo()
    pob = [d for d in poblacion(dias_u, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    print(f"\n  CUENTA FLEX FONDEADA · {HORIZONTE} días desde el fondeo · cuenta "
          f"${PODER:,.0f} · drawdown ${TOPE_DD:,.0f} intradía trepando · "
          f"día ${LIM_DIA:,.0f}")
    print(f"  retiro: mín ${MIN_RETIRO:.0f} · {DIAS_ENTRE} días · {BUENOS} días de "
          f"${DIA_BUENO:.0f} en {VENTANA} · reparto {SPLIT:.0%}\n")

    for corte in (True, False):
        pre = E.precomputar(pob, corte=corte)
        pf = defaultdict(list)
        for tk, f in sorted(pre):
            pf[f].append(tk)
        fechas = sorted(pf)
        print(f"\n  ===== {'CON' if corte else 'SIN'} corte de las 11:00 =====")
        print("  {:<22} {:>4} {:>7} {:>7} {:>10} {:>10} {:>9} {:>7}  {}".format(
            "config", "n", "cobra", "quema", "retirado", "p75", "1er ret.",
            "retiros", "por qué no (días bloqueados)"))
        print("  " + "-" * 110)
        for papeles in ("1", "2", "todos"):
            for riesgo in (100, 150, 200, 250, 300):
                r = correr(pre, pf, fechas, riesgo=riesgo, papeles=papeles)
                tr = " · ".join(f"{v} {k}" for k, v in
                                sorted(r["trabas"].items(), key=lambda x: -x[1]))
                print("  {:<22} {:>4} {:>6.0f}% {:>6.0f}% {:>10} {:>10} {:>9} {:>7.1f}  {}".format(
                    f"{papeles} papel · ${riesgo}", r["n"], 100 * r["cobra"],
                    100 * r["quema"], f"${r['retirado']:,.0f}",
                    f"${r['retirado_p75']:,.0f}",
                    (f"{r['primer']:.0f}d" if r["primer"] is not None else "—"),
                    r["n_ret"], tr))

    print("""
  COMO SE LEE
  'cobra' es la fracción de cuentas que retiró al menos una vez en 180 días.
  'retirado' es la mediana de lo que llegó al bolsillo (ya con el 70%) en esos
  180 días; 'p75', el caso bueno. '1er ret.' es cuántos días tardó la mediana
  en cobrar por primera vez. Las trabas dicen POR QUE los días en que había
  plata no se pudo retirar — 'días de 0,5%' es la que no se destraba sola.
""")
