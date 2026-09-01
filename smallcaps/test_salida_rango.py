#!/usr/bin/env python3
"""Salir cuando el rango se seca: ¿deja más plata, o sólo sale antes?

LO QUE YA SE SABE. `test_durante.py` midió que cuando el rango de los últimos 15
minutos se achica, lo que queda de rueda no da: +3,26% de caída si el rango está
ancho contra -0,29% si está angosto, con el mismo signo en las dos mitades del
tiempo. Eso es un hecho sobre el mercado.

LO QUE ESTE ARCHIVO PREGUNTA. Si eso se convierte en una regla de salida, ¿la
estrategia gana más? No es la misma pregunta. Salir antes cambia TODO: se cobra
menos de los días que seguían, se evita parte de los que se daban vuelta, y se
paga una comisión extra por cerrar.

EL UMBRAL NO PUEDE SALIR DE MIRAR TODO. Un umbral elegido sobre la misma muestra
que después lo valida es sobreajuste con otro nombre. Acá el rango se compara
contra el PROMEDIO DEL PROPIO DIA hasta ese minuto: es una medida relativa, sin
ningún parámetro estimado sobre el conjunto. Cada día se normaliza solo.

EL PLACEBO, QUE ES LO QUE DECIDE. Para cada día, si la regla real sale en el
minuto k, el placebo sale en un minuto AL AZAR del mismo rango. Así el placebo
tiene la misma cantidad de salidas y la misma distribución de "qué tan temprano"
— lo único que no tiene es el criterio. Si la regla real no le gana, lo que
mejoró no fue mirar el rango: fue salir antes, y eso lo hace cualquiera.

    python test_salida_rango.py
"""

from __future__ import annotations

import random
import statistics
import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT, DESDE = 400.0, 2.0, 45.0, 40, 10.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005
PLACEBOS = 200
random.seed(20260901)


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def señales(d):
    return set(i for i in señales_swing(d, desde=DESDE)
               if (d.bars[i][4] or 0) >= PISO)


def rangos_relativos(dia, i10):
    """Rango de los últimos 15' sobre el promedio del propio día, minuto a minuto.

    Relativo al día y no a un umbral global: un papel de $2 que se mueve 3% por
    minuto y uno de $8 que se mueve 0,5% no se pueden comparar con el mismo
    número absoluto, y estimar ese número sobre la muestra sería sobreajuste.
    """
    out = {}
    acumulado = []
    for i in range(i10, len(dia.bars)):
        b = dia.bars[i]
        if hora(b) > CIERRE_RTH:
            break
        px = b[4]
        if not px:
            continue
        ventana = dia.bars[max(i10, i - 14):i + 1]
        altos = [x[2] for x in ventana if x[2]]
        bajos = [x[3] for x in ventana if x[3]]
        if not altos or not bajos:
            continue
        r = 100.0 * (max(altos) - min(bajos)) / px
        acumulado.append(r)
        prom = statistics.mean(acumulado)
        out[i] = r / prom if prom else None
    return out


def jornada_con_salida(dia, *, salir_en=None):
    """La estrategia de siempre, pero con una salida global opcional.

    `salir_en` es el índice de barra en el que se cierra TODO lo abierto. None
    es el comportamiento actual: sostener al cierre.

    El resto es idéntico al motor —mismo sizing por riesgo, mismo stop del 45%
    por tramo, mismo presupuesto marcado a mercado— para que la única diferencia
    medida sea la salida.
    """
    idx = sorted(señales(dia))
    if not idx:
        return None
    r_trade = RIESGO / 3.0
    cierre = dia.rth_close
    if not cierre:
        return None

    abiertos, detalle = [], []
    for i in idx:
        if len(detalle) >= MAXT:
            break
        if salir_en is not None and i >= salir_en:
            break
        p = dia.bars[i][4]
        if not p:
            continue
        # Presupuesto marcado a mercado en ESTE minuto, igual que el motor.
        equity = 0.0
        for t in detalle:
            if t["i_sal"] is not None and t["i_sal"] <= i:
                equity += t["pnl"]
            else:
                equity += t["acciones"] * (t["p_ent"] - p)
        if equity - r_trade < -RIESGO:
            break

        acciones = r_trade / (p * STOP / 100.0)
        p_stop = p * (1 + STOP / 100.0)
        i_sal, p_sal, motivo = None, None, None
        fin = salir_en if salir_en is not None else len(dia.bars)
        for k in range(i + 1, min(fin + 1, len(dia.bars))):
            bk = dia.bars[k]
            if hora(bk) > CIERRE_RTH:
                break
            if bk[2] and bk[2] >= p_stop:
                i_sal, p_sal, motivo = k, p_stop, "stop"
                break
            if salir_en is not None and k >= salir_en:
                i_sal, p_sal, motivo = k, bk[4] or p, "rango"
                break
        if i_sal is None:
            p_sal, motivo = cierre, "cierre"
        pnl = acciones * (p - p_sal) - acciones * COSTO_ACCION
        detalle.append({"acciones": acciones, "p_ent": p, "pnl": pnl,
                        "i_ent": i, "i_sal": i_sal, "motivo": motivo})
        abiertos.append(i)

    if not detalle:
        return None
    bruto = sum(t["pnl"] + t["acciones"] * COSTO_ACCION for t in detalle)
    com = sum(comision(t["acciones"]) for t in detalle)
    # Pico simultáneo, que es lo que hay que localizar.
    ev = []
    for t in detalle:
        ev.append((t["i_ent"], +t["acciones"]))
        ev.append((t["i_sal"] if t["i_sal"] is not None else 10 ** 9,
                   -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)
    return {"neto": bruto - com, "nominal": pico * cierre,
            "trades": len(detalle)}


def correr(dias, umbral=None, azar=False):
    """umbral=None -> base. umbral=x -> salir cuando rango_rel < x. azar -> placebo."""
    neto = nom = 0.0
    ses = tr = 0
    por_dia = {}
    for d in dias:
        i10 = d.idx_en(DESDE)
        if i10 is None:
            continue
        salir = None
        if umbral is not None:
            rel = rangos_relativos(d, i10)
            candidatos = [i for i in sorted(rel)
                          if rel[i] is not None and rel[i] < umbral
                          and i > i10 + 20]
            if candidatos:
                salir = (random.choice(range(i10 + 21, len(d.bars)))
                         if azar else candidatos[0])
        r = jornada_con_salida(d, salir_en=salir)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    return {"ses": ses, "tr": tr, "neto": neto,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0,
            "peor": min(por_dia.values()) if por_dia else 0.0}


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]

print("\n  SALIR CUANDO EL RANGO SE SECA\n")
b = correr(pob)
print(f"  BASE (sostener al cierre): {b['ses']} sesiones · ${b['neto']:,.0f} · "
      f"{b['ret']:.2f}% ret/nom · ${b['por_ses']:.0f}/sesión · "
      f"peor día ${b['peor']:,.0f}")
print()
print("  {:<16} {:>5} {:>7} {:>10} {:>9} {:>10} {:>22}".format(
    "umbral", "ses", "trades", "neto", "ret/nom", "$/sesion", "placebo (misma salida)"))
print("  " + "-" * 88)

for u in (0.5, 0.6, 0.7, 0.8):
    r = correr(pob, umbral=u)
    pl = [correr(pob, umbral=u, azar=True)["por_ses"] for _ in range(20)]
    pl.sort()
    p95 = pl[int(0.95 * len(pl)) - 1]
    gana = r["por_ses"] > p95
    print("  rango < {:<8.1f} {:>5} {:>7} ${:>9,.0f} {:>8.2f}% ${:>9.0f} "
          "{:>10} {}".format(
              u, r["ses"], r["tr"], r["neto"], r["ret"], r["por_ses"],
              f"${p95:.0f}", "<== GANA" if gana else "no gana"))

print()
print("  El placebo sale en un minuto AL AZAR del mismo rango: misma cantidad")
print("  de salidas y misma distribución de qué tan temprano. Lo único que no")
print("  tiene es el criterio. Si la regla no le gana, lo que mejoró no fue")
print("  mirar el rango — fue salir antes, y eso lo hace cualquiera.")
