#!/usr/bin/env python3
"""¿Cuánto tarda de verdad pasar la evaluación, CONTANDO los reintentos?

El barrido fino dio dos tipos de configuración:

  · las que pasan limpio el 100% y nunca queman — pero tardan 165-180 días
  · las que queman el 8-30% — pero cuando pasan tardan 76-136 días

Compararlas por "días de la mediana" es trampa: una quema no es gratis, cuesta
$97 y, sobre todo, cuesta los DIAS que pasaron hasta quemar. Lo que hay que
comparar es el tiempo esperado hasta un pase limpio con los reintentos adentro:

    E[T] = E[días de un intento fallido] · (1-p)/p  +  E[días del pase]

con p = probabilidad de pase limpio. Y el costo esperado, 97/p.

Se asume que después de quemar se compra otra evaluación y se arranca al día
siguiente — que es lo que se haría.

    python test_evaluacion_reintentos.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")

import evaluacion as E
from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CANDIDATAS = [
    # (corte, papeles, riesgo, tope_frac, etiqueta)
    (True,  "todos", 175, 0.70, "CON corte · todos · $175 · tope 70%"),
    (True,  "1",     200, 0.80, "CON corte · 1 · $200 · tope 80%"),
    (True,  "todos", 200, 0.70, "CON corte · todos · $200 · tope 70%"),
    (False, "1",     100, 0.70, "SIN corte · 1 · $100 · tope 70%"),
    (False, "1",     150, 0.70, "SIN corte · 1 · $150 · tope 70%"),
    (False, "1",     175, 0.70, "SIN corte · 1 · $175 · tope 70%"),
    (False, "todos", 100, 0.80, "SIN corte · todos · $100 · tope 80%"),
    (False, "todos", 125, 0.80, "SIN corte · todos · $125 · tope 80%"),
    (False, "todos", 150, 0.80, "SIN corte · todos · $150 · tope 80%"),
    (False, "todos", 200, 0.70, "SIN corte · todos · $200 · tope 70%"),
]


def medir(pre, por_fecha, fechas, papeles, riesgo, tope_frac):
    plan = E.PLANES["flex"]
    OBJ = E.PODER * plan["objetivo"]
    dias = E.construir_dias(pre, por_fecha, escala=riesgo / E.R_REF,
                            tope=tope_frac * plan["consistencia"] * OBJ,
                            lim_dia=E.PODER * plan["dia"], papeles=papeles)
    res = [E.evaluar_desde(i, fechas, dias, plan) for i in range(len(fechas))]
    cerr = [r for r in res if r["res"] != "abierta"]
    ok = [r for r in cerr if r["res"] == "pasa" and r["limpia"]]
    mal = [r for r in cerr if not (r["res"] == "pasa" and r["limpia"])]
    p = len(ok) / len(cerr)
    d_ok = statistics.mean(r["dias"] for r in ok) if ok else 0.0
    # Un pase SUCIO (rompió consistencia) también es un intento perdido: se
    # cuenta con sus días, como una quema.
    d_mal = statistics.mean(r["dias"] for r in mal) if mal else 0.0
    esp = d_mal * (1 - p) / p + d_ok if p else None
    return {"n": len(cerr), "p": p, "d_ok": d_ok, "d_mal": d_mal,
            "esp": esp, "costo": 97 / p if p else None,
            "p75": sorted(r["dias"] for r in ok)[int(0.75 * len(ok))] if ok else None,
            "mal_n": len(mal)}


if __name__ == "__main__":
    dias_u = universo()
    pob = [d for d in poblacion(dias_u, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    pres = {}
    for corte in (True, False):
        pre = E.precomputar(pob, corte=corte)
        pf = defaultdict(list)
        for tk, f in sorted(pre):
            pf[f].append(tk)
        pres[corte] = (pre, pf, sorted(pf))

    print("\n  EVALUACION FLEX · TIEMPO ESPERADO A UN PASE LIMPIO, CON REINTENTOS\n")
    print("  {:<40} {:>7} {:>9} {:>10} {:>11} {:>8} {:>8}".format(
        "configuración", "limpia", "días pase", "días fallo", "E[T] días", "p75", "$ esp."))
    print("  " + "-" * 98)
    filas = []
    for corte, papeles, riesgo, tope, etq in CANDIDATAS:
        pre, pf, fechas = pres[corte]
        m = medir(pre, pf, fechas, papeles, riesgo, tope)
        filas.append((m["esp"] or 9e9, etq, m))
        print("  {:<40} {:>6.0f}% {:>9.0f} {:>10} {:>11} {:>8} {:>8}".format(
            etq, 100 * m["p"], m["d_ok"],
            (f"{m['d_mal']:.0f}" if m["mal_n"] else "—"),
            (f"{m['esp']:.0f}" if m["esp"] else "—"),
            (f"{m['p75']:.0f}" if m["p75"] else "—"),
            (f"${m['costo']:.0f}" if m["costo"] else "—")))
    filas.sort(key=lambda x: x[0])
    print(f"\n  La más rápida contando reintentos: {filas[0][1]} "
          f"→ {filas[0][0]:.0f} días esperados")
    print("""
  'días pase' es el promedio de días calendario de los intentos que pasaron
  limpios; 'días fallo', el de los que quemaron o pasaron sucios. 'E[T]' junta
  las dos con la probabilidad de cada una: es lo que uno debería esperar tardar
  desde que compra la primera evaluación hasta que tiene una cuenta fondeada.
""")
