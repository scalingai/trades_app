#!/usr/bin/env python3
"""El locate: ¿a qué precio por acción deja de haber negocio en el bono de $2.000?

**LO QUE FALTABA.** `test_bono_2000.py` midió drawdown, poder de compra y
comisión contra las reglas de una prop de depósito. NO midió el locate, y en
small caps el locate es el costo que decide. Agus lo marcó: "testeaste la
estrategia con esos límites?". Con el locate, no.

**LO QUE EL PROYECTO YA SABIA.** Commit 1813036: "el punto de muerte es el
locate al 5% del nominal". Pero eso se midió sobre la estrategia VIEJA (swing +
stop estructural, $50/día, ret/nom bajo). La de hoy —reclaim, sin corte, sin
tope— devuelve ~9-10% sobre el nominal, así que el punto de muerte es otro y
hay que remedirlo, no recordarlo.

**COMO SE COBRA EL LOCATE, y por qué importa modelarlo bien.** Zimtra pasa el
costo del vendor a precio de mercado: se cobra POR ACCION al aceptar las
acciones —se usen o no—, vale para el día, y en hard-to-borrow puede ir de
centavos a dólares por acción. La regla que este proyecto ya había fijado
(`test_locate_nominal.py`): se paga UNA vez por papel por día, sobre las
acciones que hacen falta para el PICO de exposición simultánea del día — se
reserva a la mañana y sirve para todos los tramos de ese papel. Se mide en
dólares por acción, que es la unidad real, y también como % del nominal, que
es como se compara entre papeles de distinto precio.

**LA SELECCION ADVERSA es el riesgo de fondo**, y hay que decirlo antes de mirar
la tabla: lo que hace a un papel hard-to-borrow —float chico, +100% en el día,
todo el mundo queriendo shortearlo— es exactamente lo que lo hace candidato
nuestro. El locate caro y el buen setup son la misma cosa. Este test dice a qué
precio muere el negocio; NO dice qué precio vamos a pagar. Eso solo lo dice
Zimtra, papel por papel, y hay que preguntárselo.

    python test_bono_locates.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")

import evaluacion as E
from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

R_REF = E.R_REF
COMISION = 0.0015
PLATAFORMA_ANUAL = 12 * 100.0    # ~$100/mes de plataforma y datos


def acciones_pico(det):
    """Las acciones simultáneas máximas del día: es lo que hay que localizar."""
    ev = []
    for t in det:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)
    return pico


def base(pob):
    out = {}
    for d in pob:
        j = jornada(d, E.sig, lado="short", stop_pct=E.STOP, riesgo=R_REF,
                    max_trades=E.MAXT, corte_h=None)
        if not j:
            continue
        det = j["detalle"]
        pico = acciones_pico(det)
        # El precio al que se localiza: el de la primera entrada del día.
        p0 = min(det, key=lambda t: t["h_ent"])["p_ent"]
        out[(d.ticker, d.d)] = {
            "bruto": sum(t["acciones"] * (t["p_ent"] - t["p_sal"]) for t in det),
            "acciones": sum(t["acciones"] for t in det),
            "pico": pico, "precio": p0, "nominal_pico": pico * p0,
        }
    return out


def anual(base_pd, fechas_tk, esc, *, loc_accion=0.0, loc_pct=0.0):
    """Neto por año con locate por acción o como % del nominal pico."""
    tot = 0.0
    meses = set()
    for f, tk in fechas_tk:
        b = base_pd[(tk, f)]
        neto = b["bruto"] * esc
        neto -= 2 * COMISION * b["acciones"] * esc
        neto -= loc_accion * b["pico"] * esc
        neto -= loc_pct * b["nominal_pico"] * esc
        tot += neto
        meses.add(f[:7])
    return tot / (len(meses) / 12.0)


if __name__ == "__main__":
    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: (d.d, d.ticker))
    base_pd = base(pob)
    fechas_tk = sorted(((f, tk) for tk, f in base_pd))

    precios = [b["precio"] for b in base_pd.values()]
    picos = [b["pico"] for b in base_pd.values()]
    print(f"\n  EL LOCATE CONTRA EL BONO DE $2.000 · {len(base_pd)} papeles-día · "
          f"todos los papeles · sin corte · sin tope")
    print(f"  precio de entrada mediano ${statistics.median(precios):.2f} · "
          f"acciones a localizar por papel-día (mediana) a $75: "
          f"{statistics.median(picos) * 0.75:.0f}")
    print(f"  Un locate de $0,10/acción es el {100 * 0.10 / statistics.median(precios):.1f}% "
          f"del nominal en nuestro papel mediano.\n")

    for riesgo in (50, 60, 75):
        esc = riesgo / R_REF
        sin = anual(base_pd, fechas_tk, esc)
        print(f"  -- ${riesgo} por papel · sin locate: ${sin:,.0f}/año bruto, "
              f"${sin - PLATAFORMA_ANUAL:,.0f} después de plataforma --")
        print("  {:>14} {:>11} {:>16}   {:>14} {:>11} {:>16}".format(
            "$/acción", "neto/año", "tras plataforma",
            "% nominal", "neto/año", "tras plataforma"))
        print("  " + "-" * 92)
        por_acc = [0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.20]
        por_pct = [0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.20]
        for la, lp in zip(por_acc, por_pct):
            na = anual(base_pd, fechas_tk, esc, loc_accion=la)
            np_ = anual(base_pd, fechas_tk, esc, loc_pct=lp)
            m1 = "  <== muere" if na - PLATAFORMA_ANUAL <= 0 else ""
            m2 = "  <== muere" if np_ - PLATAFORMA_ANUAL <= 0 else ""
            print("  {:>14} ${:>10,.0f} ${:>15,.0f}{:<12} {:>13} ${:>10,.0f} ${:>15,.0f}{}".format(
                f"${la:.3f}", na, na - PLATAFORMA_ANUAL, m1,
                f"{100 * lp:.1f}%", np_, np_ - PLATAFORMA_ANUAL, m2))
        # El punto de muerte exacto, por bisección sobre el % del nominal.
        lo, hi = 0.0, 0.5
        for _ in range(40):
            mid = (lo + hi) / 2
            if anual(base_pd, fechas_tk, esc, loc_pct=mid) - PLATAFORMA_ANUAL > 0:
                lo = mid
            else:
                hi = mid
        lo_a, hi_a = 0.0, 2.0
        for _ in range(40):
            mid = (lo_a + hi_a) / 2
            if anual(base_pd, fechas_tk, esc, loc_accion=mid) - PLATAFORMA_ANUAL > 0:
                lo_a = mid
            else:
                hi_a = mid
        print(f"\n  punto de muerte a ${riesgo}: locate al {100 * lo:.1f}% del nominal, "
              f"o ${lo_a:.3f} por acción (con ${PLATAFORMA_ANUAL:,.0f}/año de plataforma)\n")

    print("""  COMO SE LEE
  El locate se cobra una vez por papel por día sobre las acciones del pico de
  exposición, al precio de la primera entrada. 'muere' es cuando el neto anual,
  después de ~$100/mes de plataforma, deja de ser positivo. El número que falta
  —qué cobra Zimtra por NUESTROS papeles— solo lo tiene Zimtra.
""")
