#!/usr/bin/env python3
"""¿Filtrar por la salud de la empresa mejora la estrategia, o sólo el gráfico?

QUE SE PROBO ANTES. `test_quien_se_derrumba.py` encontró que los días de
empresas con poca caja, mucha dilución y float chico se derrumban bastante más:
22,9% contra 10,8% en el caso de la caja. Eso es un hecho sobre el mercado.

QUE FALTA, Y ES LO QUE DECIDE. Que una variable separe no significa que filtrar
por ella deje más plata. Filtrar recorta la muestra, y una estrategia que opera
la mitad de las sesiones necesita ganar el doble por sesión para empatar. Acá se
corre la estrategia REAL sobre la población filtrada y se compara contra:

  · la base sin filtrar,
  · un PLACEBO: un filtro al azar que deja pasar la misma cantidad de días.

El placebo es el control que mató catorce familias en este proyecto. Sin él,
cualquier filtro que reduzca la muestra parece mejorar algo por pura varianza.

Y todo partido en dos mitades por fecha: lo que no aguanta la segunda mitad del
tiempo no existe.

    python test_filtro_edgar.py
"""

from __future__ import annotations

import random
import statistics
import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import COSTO_ACCION, jornada, poblacion, universo
from sesion import señales_swing
from test_quien_se_derrumba import estructura, estructura_de

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT = 400.0, 2.0, 45.0, 40
MIN_ORDEN, POR_ACCION = 0.75, 0.005
PLACEBOS = 200
random.seed(20260901)


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def sig(d):
    return [i for i in señales_swing(d, desde=10.0)
            if (d.bars[i][4] or 0) >= PISO]


def correr(dias):
    """La estrategia vigente sobre un conjunto de días. Números netos reales."""
    bruto = com = nom = 0.0
    ses = tr = 0
    por_dia = {}
    for d in dias:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                    max_trades=MAXT)
        if not j:
            continue
        b = j["pnl"]
        c = 0.0
        for t in j["detalle"]:
            b += t["acciones"] * COSTO_ACCION
            c += comision(t["acciones"])
        bruto += b
        com += c
        nom += j["nominal"]
        tr += j["trades"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + b - c
    neto = bruto - com
    peor = min(por_dia.values()) if por_dia else 0.0
    return {"ses": ses, "tr": tr, "neto": neto, "peor": peor,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0}


def placebo(dias, cuantos, n=PLACEBOS):
    """Filtros al azar de la MISMA frecuencia. Devuelve el percentil 95.

    Si el filtro real no supera al mejor 5% del azar, lo que se encontró es la
    búsqueda, no el mercado.
    """
    rets, netos = [], []
    for _ in range(n):
        m = correr(random.sample(dias, min(cuantos, len(dias))))
        rets.append(m["ret"])
        netos.append(m["por_ses"])
    rets.sort()
    netos.sort()
    k = int(0.95 * len(rets))
    return {"ret95": rets[min(k, len(rets) - 1)],
            "ses95": netos[min(k, len(netos) - 1)],
            "ret_med": statistics.median(rets)}


# ------------------------------------------------------------------ población

dias = universo()
pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                max_float=47e6)
pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]
est = estructura()
for d in pob:
    d._est = estructura_de(est, d.ticker, d.d)
pob.sort(key=lambda d: d.d)

CORTE = len(pob) // 2
MITADES = [("P1", pob[:CORTE]), ("P2", pob[CORTE:]), ("todo", pob)]

# Cada filtro: (nombre, campo, "alto" o "bajo"). El corte es la MEDIANA del
# conjunto, nunca un umbral elegido a mano — un umbral optimizado sobre el
# mismo dato que lo valida ya es sobreajuste.
FILTROS = [
    ("poca caja", "cash_usd", "bajo"),
    ("float chico", "shares_outstanding", "bajo"),
    ("mucha dilucion 12m", "dilution_12m_pct", "alto"),
    ("mucha dilucion 3m", "dilution_3m_pct", "alto"),
    ("mas reverse splits", "reverse_splits_12m", "alto"),
    ("mas avisos", "n_warnings", "alto"),
    ("mas pricings 12m", "pricing_filings_12m", "alto"),
    ("poco runway", "runway_months", "bajo"),
]


def aplicar(dias_, campo, lado):
    vals = [d._est.get(campo) for d in dias_ if d._est.get(campo) is not None]
    if len(vals) < 40:
        return None
    med = statistics.median(vals)
    if lado == "alto":
        return [d for d in dias_ if (d._est.get(campo) or -1e18) > med]
    return [d for d in dias_ if d._est.get(campo) is not None
            and d._est[campo] <= med]


print("\n  FILTRAR POR LA SALUD DE LA EMPRESA\n")
base_todo = correr(pob)
print(f"  BASE sin filtrar: {base_todo['ses']} sesiones · "
      f"${base_todo['neto']:,.0f} · {base_todo['ret']:.2f}% ret/nom · "
      f"${base_todo['por_ses']:.0f} por sesión · peor día ${base_todo['peor']:,.0f}")
print()
print("  {:<22} {:>5} {:>6} {:>10} {:>8} {:>10} {:>10} {:>9}".format(
    "filtro", "ses", "mitad", "neto", "ret/nom", "$/sesion", "placebo p95", "peor dia"))
print("  " + "-" * 92)

for nombre, campo, lado in FILTROS:
    for etq, sub in MITADES:
        f = aplicar(sub, campo, lado)
        if not f or len(f) < 25:
            continue
        m = correr(f)
        if not m["ses"]:
            continue
        pl = placebo(sub, len(f)) if etq == "todo" else None
        marca = ""
        if pl:
            gana = m["por_ses"] > pl["ses95"] and m["ret"] > pl["ret95"]
            marca = "  <== supera al azar" if gana else "  (no supera al azar)"
        print("  {:<22} {:>5} {:>6} ${:>9,.0f} {:>7.2f}% ${:>9.0f} {:>10} ${:>8,.0f}{}".format(
            nombre if etq == "P1" else "", m["ses"], etq, m["neto"], m["ret"],
            m["por_ses"],
            f"${pl['ses95']:.0f}" if pl else "—", m["peor"], marca))
    print()

print("  'placebo p95' es lo que gana por sesión el mejor 5% de 200 filtros AL")
print("  AZAR con la misma cantidad de días. Un filtro que no lo supera no está")
print("  eligiendo días: está eligiendo menos días, que es otra cosa.")
