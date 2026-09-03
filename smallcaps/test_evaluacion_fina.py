#!/usr/bin/env python3
"""El barrido fino de la evaluación FLEX, después del grueso de `evaluacion.py`.

QUE DEJO EL GRUESO. Dos cosas:

  · MAX está muerta por el plazo. Con 60 días calendario y una estrategia que
    opera 2 a 7 veces por mes, entre el 60% y el 100% de los arranques VENCEN
    antes de llegar a $1.500. La cuenta que arreglaba el retiro (sin regla de
    3 días de 0,5%) es inalcanzable en evaluación. Se sale del barrido.

  · En FLEX el tope por símbolo funciona pero al 95% del límite SE PASA: el
    mejor símbolo-día daba 52% del objetivo con límite 50%, porque el cierre se
    ejecuta al close de la vela y una vela grande sobrepasa el tope. Un pase
    con 52% no es un pase. Hay que dejar más aire.

QUE PRUEBA ESTE. Sólo FLEX, con:
  · riesgo más fino: 100 a 250
  · tope más ajustado: 70%, 80%, 90% del límite de consistencia
  · 1 papel por día vs todos
  · CON y SIN el corte de las 11:00. El corte protege el drawdown; a $100 el
    drawdown va sobrado (0% de quemas) y el corte cuesta plata. Si sacarlo
    acelera sin quemar, en evaluación no hace falta.

    python test_evaluacion_fina.py
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


def cab():
    print("  {:<30} {:>4} {:>6} {:>7} {:>6} {:>6} {:>5} {:>6} {:>5} {:>7} {:>7}".format(
        "config", "n", "pasa", "limpia", "quema", "p25d", "días", "p75", "ses",
        "mejor%", "$/pase"))
    print("  " + "-" * 100)


def fila(etq, r, p25):
    f = lambda v: ("—" if v is None else f"{v:.0f}")
    print("  {:<30} {:>4} {:>6} {:>7} {:>6} {:>6} {:>5} {:>6} {:>5} {:>7} {:>7}".format(
        etq, r["n"], f"{100 * r['pasa']:.0f}%", f"{100 * r['limpia']:.0f}%",
        f"{100 * r['quema']:.0f}%", f(p25), f(r["dias"]), f(r["dias_p75"]),
        f(r["ses"]), (f"{r['mejor']:.0f}%" if r["mejor"] is not None else "—"),
        ("$" + f(r["costo"]) if r["costo"] else "—")))


def correr_p25(pre, por_fecha, fechas, **kw):
    """Igual que E.correr, pero también el p25 de días — el caso bueno."""
    r = E.correr(pre, por_fecha, fechas, **kw)
    plan = E.PLANES[kw["plan_nombre"]]
    esc = kw["riesgo"] / E.R_REF
    tope = (kw["tope_frac"] * plan["consistencia"] * E.PODER * plan["objetivo"]
            if kw["tope_frac"] else None)
    dias = E.construir_dias(pre, por_fecha, escala=esc, tope=tope,
                            lim_dia=E.PODER * plan["dia"], papeles=kw["papeles"])
    res = [E.evaluar_desde(i, fechas, dias, plan) for i in range(len(fechas))]
    lim = sorted(x["dias"] for x in res if x["res"] == "pasa" and x["limpia"])
    p25 = lim[int(0.25 * len(lim))] if lim else None
    return r, p25


if __name__ == "__main__":
    dias_u = universo()
    pob = [d for d in poblacion(dias_u, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))

    print(f"\n  EVALUACION FLEX, BARRIDO FINO · {len(pob)} días reclaim · "
          f"cuenta ${E.PODER:,.0f} · objetivo $1.500 · consistencia 50%\n")

    for corte in (True, False):
        pre = E.precomputar(pob, corte=corte)
        por_fecha = defaultdict(list)
        for tk, f in sorted(pre):
            por_fecha[f].append(tk)
        fechas = sorted(por_fecha)
        print(f"\n  ===== {'CON' if corte else 'SIN'} corte de las 11:00 · "
              f"{len(fechas)} fechas · {len(pre)} papeles-día =====")
        for papeles in ("1", "todos"):
            print(f"\n  -- {papeles} papel(es) por día --")
            cab()
            for tope_frac in (0.70, 0.80, 0.90):
                for riesgo in (100, 125, 150, 175, 200, 250):
                    r, p25 = correr_p25(pre, por_fecha, fechas, plan_nombre="flex",
                                        riesgo=riesgo, tope_frac=tope_frac,
                                        papeles=papeles)
                    fila(f"${riesgo} tope {tope_frac:.0%}", r, p25)

    print("""
  COMO SE LEE
  Lo único que cuenta es 'limpia': llegar a $1.500 sin que ningún símbolo-día
  supere el 50% del objetivo. 'p25d / días / p75' son días CALENDARIO hasta el
  pase limpio (caso bueno / mediana / caso malo). '$/pase' = 97 / P(limpia).
""")
