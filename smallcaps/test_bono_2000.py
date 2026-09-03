#!/usr/bin/env python3
"""¿Entra la estrategia en un bono de $2.000 de una prop de depósito (Zimtra)?

**LA PREGUNTA DE AGUS**: "si tuviera 2000 dólares podríamos hacerlo". Con
$2.000 propios en un broker retail no: PDT (3 day trades cada 5 días con menos
de $25k), margen mínimo de $2.000 justo, y locates que no te dan. Pero existe
otro modelo: la prop de DEPOSITO. Zimtra (Cayman, no acepta residentes de EE.UU.,
sí extranjeros) pide un "performance bond" de $2.000 y da:

    sin PDT · sin regla de consistencia · sin días mínimos ganadores
    pago 100% de la ganancia (tier Intermediate) o 90% (Elite)
    shorts con 2:1 de poder de compra mientras el bono sea < $10.000
    no se puede shortear nada a $1 o menos (nuestro piso es $2: no molesta)
    comisión $0,0015 por acción (Pro/Elite), plataforma a costo
    la cuenta puede caer hasta el 40-50% del bono; ahí cierran posiciones
    paga cualquier ganancia arriba de $500 por mes

O sea, exactamente las reglas que a Trade The Pool le faltaban — a cambio de
poner $2.000 de verdad, que se pueden perder hasta el 50%.

**QUE SE MIDE.** Sobre el censo reclaim, la estrategia completa —sin corte, sin
tope, sostiene al cierre— a distintos riesgos por papel:

  · el DRAWDOWN de la curva de equity, de fin de día e intradía, contra los
    $800 (40%) y $1.000 (50%) que permite el bono
  · la EXPOSICION nominal pico por día contra los $4.000 de poder de compra
    (2:1 sobre $2.000): si no entra, hay tramos que no se pueden abrir
  · el NETO anual después de la comisión de $0,0015/acción por lado
  · cuántos meses superan los $500 de ganancia que hacen falta para cobrar

Con UN papel por día y con todos, porque acá no hay regla que lo limite.

    python test_bono_2000.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")

import evaluacion as E
from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo, _nominal_pico

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BONO = 2000.0
PODER_SHORT = 2 * BONO            # 2:1 mientras el bono sea < $10.000
DD_40, DD_50 = 0.40 * BONO, 0.50 * BONO
COMISION = 0.0015                 # por acción, por lado (tier Pro/Elite)
MIN_PAGO = 500.0                  # ganancia mínima del mes para cobrar
R_REF = E.R_REF


def base(pob):
    """Por (ticker, fecha), a riesgo R_REF: pnl bruto, acciones totales y
    exposición nominal pico. Todo escala lineal con el riesgo."""
    out = {}
    for d in pob:
        j = jornada(d, E.sig, lado="short", stop_pct=E.STOP, riesgo=R_REF,
                    max_trades=E.MAXT, corte_h=None)
        if not j:
            continue
        det = j["detalle"]
        bruto = sum(t["acciones"] * (t["p_ent"] - t["p_sal"]) for t in det)
        out[(d.ticker, d.d)] = {
            "bruto": bruto,
            "acciones": sum(t["acciones"] for t in det),
            "nominal": _nominal_pico(det),
        }
    return out


def medir(base_pd, pre, por_fecha, fechas, *, riesgo, papeles):
    esc = riesgo / R_REF
    serie, nominales, meses = [], [], defaultdict(float)
    dias_cfg = E.construir_dias(pre, por_fecha, escala=esc, tope=None,
                                lim_dia=1e12, papeles=papeles)
    for f in fechas:
        tks = por_fecha[f] if papeles == "todos" else por_fecha[f][:1]
        neto = 0.0
        nominal = 0.0
        for tk in tks:
            b = base_pd.get((tk, f))
            if not b:
                continue
            neto += b["bruto"] * esc - 2 * COMISION * b["acciones"] * esc
            nominal += b["nominal"] * esc
        serie.append((f, neto))
        nominales.append(nominal)
        meses[f[:7]] += neto
    # drawdown fin de día
    acum = pico = dd = 0.0
    for _, v in serie:
        acum += v
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    # drawdown intradía: la curva del día sumada al acumulado
    acum = pico = ddi = 0.0
    for f, v in serie:
        d = dias_cfg.get(f)
        if d is not None:
            eq = acum + d["eq"]
            runmax = np.maximum.accumulate(np.maximum(eq, pico))
            ddi = min(ddi, float((eq - runmax).min()))
            pico = max(pico, float(eq.max()))
        acum += v
        pico = max(pico, acum)
    total = sum(v for _, v in serie)
    años = (len({f[:7] for f, _ in serie})) / 12.0
    return {
        "neto_anual": total / años if años else 0.0,
        "dd": dd, "ddi": ddi,
        "nominal_p50": statistics.median(nominales) if nominales else 0.0,
        "nominal_max": max(nominales) if nominales else 0.0,
        "no_entra": 100 * sum(1 for x in nominales if x > PODER_SHORT) / len(nominales),
        "meses": len(meses),
        "meses_cobra": sum(1 for v in meses.values() if v >= MIN_PAGO),
        "meses_rojo": sum(1 for v in meses.values() if v < 0),
    }


if __name__ == "__main__":
    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    base_pd = base(pob)
    pre = E.precomputar(pob, corte=False)
    por_fecha = defaultdict(list)
    for tk, f in sorted(base_pd):
        por_fecha[f].append(tk)
    fechas = sorted(por_fecha)

    print(f"\n  UN BONO DE ${BONO:,.0f} EN UNA PROP DE DEPOSITO · {len(pob)} días reclaim · "
          f"{len(fechas)} fechas con sesión")
    print(f"  drawdown permitido: ${DD_40:,.0f} (40%) a ${DD_50:,.0f} (50%) · poder de "
          f"compra en shorts ${PODER_SHORT:,.0f} · comisión ${COMISION}/acc por lado · "
          f"paga meses > ${MIN_PAGO:.0f}\n")
    for papeles in ("1", "todos"):
        print(f"  -- {papeles} papel(es) por día --")
        print("  {:>7} {:>11} {:>10} {:>11} {:>10} {:>10} {:>9} {:>12} {:>9}".format(
            "riesgo", "neto/año", "dd cierre", "dd intradía", "nominal p50",
            "nominal máx", "no entra", "meses cobra", "en rojo"))
        print("  " + "-" * 100)
        for riesgo in (25, 40, 50, 60, 75, 100):
            r = medir(base_pd, pre, por_fecha, fechas, riesgo=riesgo, papeles=papeles)
            ok = ("  <== entra" if abs(r["ddi"]) < DD_40 and r["no_entra"] < 5 else
                  "  (entra al 50%)" if abs(r["ddi"]) < DD_50 and r["no_entra"] < 5 else "")
            print("  {:>6} ${:>10,.0f} ${:>9,.0f} ${:>10,.0f} ${:>9,.0f} ${:>9,.0f} {:>8.0f}% "
                  "{:>6}/{:<4} {:>9}{}".format(
                      f"${riesgo}", r["neto_anual"], r["dd"], r["ddi"],
                      r["nominal_p50"], r["nominal_max"], r["no_entra"],
                      r["meses_cobra"], r["meses"], r["meses_rojo"], ok))
        print()
    print("""  COMO SE LEE
  'dd intradía' es la peor caída de la equity con posiciones abiertas, que es
  lo que mira la firma para cerrarte. 'no entra' es el % de días cuya exposición
  pico supera el poder de compra: esos tramos no se podrían abrir. 'meses cobra'
  son los meses con ganancia > $500, que es el mínimo para que te paguen.
""")
