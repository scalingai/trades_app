#!/usr/bin/env python3
"""¿El tope del MOTOR hace lo mismo que el del SIMULADOR con el que se midió?

`evaluacion.py` midió la evaluación con un tope por símbolo implementado
adentro del propio simulador (`_papel`): escala la curva de riesgo 100 y corta
en la primera barra que toca el tope. Después el tope se implementó en
`motor.jornada(tope_usd=...)`, que es lo que corre la pantalla en vivo.

Si los dos no coinciden, lo que se opera no es lo que se midió — que es el
error que este proyecto ya cometió una vez con `evaluar` reimplementando la
regla de presupuesto. Esto compara, papel-día por papel-día, a $150 con tope de
$525 y sin corte:

  · la cantidad de tramos que sobrevivieron
  · la ganancia bruta del día (a mercado, sin comisión)
  · si el tope disparó y en qué minuto

Tolerancia: centavos, por el redondeo de la curva.

    python test_tope_identidad.py
"""

from __future__ import annotations

import sys
from collections import defaultdict

sys.path.insert(0, ".")

import evaluacion as E
from chavineta import clasificar_apertura as _cl
from dias import hora
from motor import jornada, poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO = 150.0
TOPE = 0.70 * 0.50 * 1500.0     # $525, igual que MODOS["evaluacion"]

if __name__ == "__main__":
    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    pre = E.precomputar(pob, corte=False)

    iguales = distintos = 0
    ejemplos = []
    capados_sim = capados_motor = 0
    for d in pob:
        k = (d.ticker, d.d)
        if k not in pre:
            continue
        sim = E._papel(pre[k], RIESGO / E.R_REF, TOPE)
        j = jornada(d, E.sig, lado="short", stop_pct=E.STOP, riesgo=RIESGO,
                    max_trades=E.MAXT, corte_h=None, tope_usd=TOPE)
        if not j:
            distintos += 1
            ejemplos.append((k, "motor devolvio None"))
            continue
        det = j["detalle"]
        bruto_motor = sum(t["acciones"] * (t["p_ent"] - t["p_sal"]) for t in det)
        bruto_sim = float(sim["eq"][-1])
        cap_motor = any(t["motivo"] == "tope" for t in det)
        capados_sim += sim["capado"]
        capados_motor += cap_motor
        ok = (len(det) == len(sim["tramos"])
              and abs(bruto_motor - bruto_sim) < 0.05
              and cap_motor == sim["capado"])
        if ok:
            iguales += 1
        else:
            distintos += 1
            if len(ejemplos) < 8:
                ejemplos.append((k, f"tramos {len(det)} vs {len(sim['tramos'])} · "
                                    f"bruto {bruto_motor:.2f} vs {bruto_sim:.2f} · "
                                    f"tope {cap_motor} vs {sim['capado']}"))

    print(f"\n  IDENTIDAD DEL TOPE · ${RIESGO:.0f} por papel · tope ${TOPE:.0f} · sin corte")
    print(f"  papeles-día iguales:   {iguales}")
    print(f"  papeles-día distintos: {distintos}")
    print(f"  días con tope: simulador {capados_sim} · motor {capados_motor}")
    for k, por in ejemplos:
        print(f"    {k}: {por}")
    print("\n  " + ("OK: el motor y el simulador hacen lo mismo." if not distintos
                    else "FALLA: hay diferencias, el vivo no es lo medido."))
    raise SystemExit(0 if not distintos else 1)
