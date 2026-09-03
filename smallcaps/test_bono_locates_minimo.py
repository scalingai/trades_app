#!/usr/bin/env python3
"""El locate con MINIMO de 100 acciones por pedido: ¿cuánto sube el punto de muerte?

Apareció investigando: "most brokers require a minimum request — usually 100
shares". Nosotros, a $75 de riesgo, necesitamos 57 acciones por papel-día (la
mediana). Si el pedido mínimo es 100, pagamos 100. Eso multiplica el locate
efectivo por ~1,75 en el papel mediano y por más en los papeles caros, donde
las acciones son pocas.

Se remide `test_bono_locates.py` cobrando max(pico, 100) acciones por papel-día.

    python test_bono_locates_minimo.py
"""

from __future__ import annotations

import statistics
import sys

sys.path.insert(0, ".")

import test_bono_locates as L
from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

MINIMO = 100.0


def anual_min(base_pd, fechas_tk, esc, *, loc_accion=0.0):
    tot = 0.0
    meses = set()
    for f, tk in fechas_tk:
        b = base_pd[(tk, f)]
        neto = b["bruto"] * esc - 2 * L.COMISION * b["acciones"] * esc
        neto -= loc_accion * max(b["pico"] * esc, MINIMO)
        tot += neto
        meses.add(f[:7])
    return tot / (len(meses) / 12.0)


if __name__ == "__main__":
    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    base_pd = L.base(pob)
    fechas_tk = sorted(((f, tk) for tk, f in base_pd))

    print(f"\n  LOCATE CON MINIMO DE {MINIMO:.0f} ACCIONES POR PEDIDO · "
          f"{len(base_pd)} papeles-día · sin corte · sin tope · plataforma ${L.PLATAFORMA_ANUAL:,.0f}/año\n")
    for riesgo in (50, 60, 75, 100):
        esc = riesgo / L.R_REF
        picos = [b["pico"] * esc for b in base_pd.values()]
        bajo_min = 100 * sum(1 for p in picos if p < MINIMO) / len(picos)
        print(f"  -- ${riesgo} por papel · pico mediano {statistics.median(picos):.0f} acc · "
              f"{bajo_min:.0f}% de los papeles-día por debajo del mínimo --")
        print("  {:>10} {:>12} {:>16} {:>12} {:>16}".format(
            "$/acción", "sin mínimo", "tras plataforma", "con mín 100", "tras plataforma"))
        print("  " + "-" * 72)
        for la in (0.01, 0.02, 0.03, 0.05, 0.10, 0.15, 0.20):
            sin = L.anual(base_pd, fechas_tk, esc, loc_accion=la)
            con = anual_min(base_pd, fechas_tk, esc, loc_accion=la)
            m = "  <== muere" if con - L.PLATAFORMA_ANUAL <= 0 else ""
            print("  {:>10} ${:>11,.0f} ${:>15,.0f} ${:>11,.0f} ${:>15,.0f}{}".format(
                f"${la:.2f}", sin, sin - L.PLATAFORMA_ANUAL, con, con - L.PLATAFORMA_ANUAL, m))
        lo, hi = 0.0, 2.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if anual_min(base_pd, fechas_tk, esc, loc_accion=mid) - L.PLATAFORMA_ANUAL > 0:
                lo = mid
            else:
                hi = mid
        print(f"\n  punto de muerte a ${riesgo} con mínimo de 100: ${lo:.3f} por acción\n")
