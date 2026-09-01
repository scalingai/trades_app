#!/usr/bin/env python3
"""La idea de Agus: agregar más posición achicando el stop hasta BE o mejor.

QUÉ CAMBIA RESPECTO DE LA BASE. Hoy cada tramo es una posición independiente
con su propio stop al 45% de SU precio de entrada, y el presupuesto se reparte
en tres partes iguales. Acá el día es UNA posición: un precio promedio, un solo
stop, y todo cierra junto si ese stop se toca.

POR QUÉ LA IDEA SE FINANCIA SOLA. El tamaño sale de `riesgo / distancia al
stop`. Si el stop se acerca al promedio, la distancia baja y la MISMA plata de
riesgo compra más acciones. Achicar el stop no es sólo defensa: es lo que paga
el tamaño extra. Por eso las dos mitades de la propuesta —agregar más y achicar
el stop— son la misma cosa, no dos.

DÓNDE PUEDE MORDER. Once mediciones distintas de este proyecto dicen que
asegurar empeora el resultado. La diferencia es que aquellas movían el stop de
un tramo suelto; ésta mueve el de la posición entera Y usa el margen liberado
para agrandarla. Es una hipótesis nueva, no una repetida — pero la sospecha
previa es fuerte y por eso se mide contra la base con el mismo harness.

EL RIESGO DE ESTO, DICHO ANTES DE VER EL RESULTADO. Un stop en breakeven sobre
una posición grande no es gratis: en un papel que respira 10% en un minuto, BE
se toca por ruido y te saca de un trade que iba bien. Y como el tamaño creció
justamente por tener el stop cerca, cada barrida cuesta más comisión y más
locate que antes.

    python test_piramide.py
"""

from __future__ import annotations

import statistics
import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT = 400.0, 2.0, 45.0, 40

# EL PODER DE COMPRA ES EL LIMITE VERDADERO, Y ESTO NO ES UN DETALLE.
#
# El tamaño sale de `riesgo / distancia al stop`. Cuando el stop llega a
# breakeven la distancia tiende a CERO y el tamaño tiende a INFINITO: la primera
# corrida devolvio $147 billones de "ganancia", que no es un error de tipeo sino
# la idea llevada al limite. Con riesgo cero, el riesgo deja de acotar nada.
#
# Lo que acota en la realidad es la plata: el plan de $20.000 de poder de compra
# de Trade The Pool. Sin este tope el modelo no describe ninguna cuenta que
# exista.
PODER_COMPRA = 20000.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def sig(d):
    return [i for i in señales_swing(d, desde=10.0)
            if (d.bars[i][4] or 0) >= PISO]


def piramide(dia, *, riesgo, stop_pct, gatillo, asegura, max_tramos,
             objetivo=None, reentrada=False):
    """Un día como UNA posición corta, con stop sobre el promedio.

    `gatillo`  — cuánto tiene que haber ido a favor (en % del promedio) para
                 mover el stop. None = nunca se mueve.
    `asegura`  — dónde queda el stop cuando se dispara, en % del promedio:
                 0 es breakeven exacto, 5 es stop-profit del 5%.
    `objetivo` — cerrar TODO cuando la posición va X% a favor del promedio.
                 La otra mitad de la idea: si el stop achicado te dio cuatro
                 veces el tamaño, alcanza con un cuarto del movimiento para la
                 misma plata — y salís antes.
    `reentrada`— volver a armar posición con la señal siguiente después de
                 haber cerrado. Sin esto, tomar profit temprano deja el resto
                 del día sin operar y el "salir antes" no compra nada.

    DISCIPLINA DE BARRA, la misma que el resto del motor: primero se chequea si
    la barra tocó el stop que venía de ANTES, y recién después se actualiza el
    nivel con el extremo de esa misma barra. Al revés, el stop se movería con
    información de la barra que lo está ejecutando — y ese fue exactamente el
    bug que dio 104% de retorno con el trailing.
    """
    idx = set(sig(dia))
    if not idx:
        return None

    acciones = 0.0          # posición corta viva
    nominal = 0.0           # suma de precio*acciones de las entradas
    stop_lvl = None         # precio al que muere TODO
    mejor = None            # el mínimo visto desde que hay posición
    entradas, salidas = [], []
    pico_acc = 0.0

    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h > CIERRE_RTH:
            break
        px_c, hi, lo = b[4], b[2], b[3]

        # 1) ¿Esta barra mata la posición con el stop que ya estaba puesto?
        if acciones > 0 and stop_lvl is not None and hi and hi >= stop_lvl:
            pnl = acciones * (nominal / acciones - stop_lvl) \
                - acciones * COSTO_ACCION
            salidas.append({"h": h, "p": stop_lvl, "acc": acciones,
                            "pnl": pnl, "motivo": "stop"})
            acciones = nominal = 0.0
            stop_lvl = mejor = None
            if not reentrada:
                break         # cerrado el día: no se reabre
            continue

        # 1b) ¿Llegó al objetivo? Cierra todo, y con reentrada el día sigue.
        #     Si en el mismo minuto se tocan stop y objetivo gana el STOP —el
        #     bloque de arriba corre primero—: no se sabe cuál vino antes dentro
        #     de la barra, y esa convención conservadora rige en todo el motor.
        if acciones > 0 and objetivo is not None and lo:
            prom = nominal / acciones
            p_obj = prom * (1 - objetivo / 100.0)
            if lo <= p_obj:
                salidas.append({"h": h, "p": p_obj, "acc": acciones,
                                "pnl": acciones * (prom - p_obj)
                                - acciones * COSTO_ACCION,
                                "motivo": "objetivo"})
                acciones = nominal = 0.0
                stop_lvl = mejor = None
                if not reentrada:
                    break
                continue

        # 2) Con la barra ya cerrada, se actualiza el mejor precio y el stop.
        if acciones > 0 and lo:
            mejor = lo if mejor is None else min(mejor, lo)
            prom = nominal / acciones
            base = prom * (1 + stop_pct / 100.0)
            if gatillo is not None and mejor is not None:
                favor = 100.0 * (prom - mejor) / prom
                if favor >= gatillo:
                    # Nunca aflojar: el stop sólo se mueve hacia el promedio.
                    base = min(base, prom * (1 - asegura / 100.0))
            stop_lvl = base

        # 3) ¿Hay señal? Se agrega hasta donde el riesgo lo permita.
        if i in idx and len(entradas) < max_tramos and px_c and px_c >= PISO:
            prom_ac = nominal / acciones if acciones else px_c
            # El stop que regiría con la posición ampliada.
            nuevo_prom = ((nominal + px_c * 1) / (acciones + 1)) if acciones else px_c
            lvl = stop_lvl if stop_lvl is not None else \
                nuevo_prom * (1 + stop_pct / 100.0)
            dist = lvl - nuevo_prom
            if dist <= 0:
                # El stop ya quedó por DEBAJO del promedio (stop-profit): la
                # posición no puede perder, asi que el riesgo no acota el
                # tamaño. Se usa la distancia base para no dimensionar infinito.
                dist = nuevo_prom * stop_pct / 100.0
            tope = riesgo / dist              # acciones que caben en el riesgo
            # ...y las que caben en la cuenta, que es lo que manda cuando el
            # stop se acerca al promedio y el riesgo deja de acotar.
            tope = min(tope, PODER_COMPRA / px_c)
            agregar = max(0.0, tope - acciones)
            if agregar > 0:
                acciones += agregar
                nominal += px_c * agregar
                pico_acc = max(pico_acc, acciones)
                entradas.append({"h": h, "p": px_c, "acc": agregar})
                prom = nominal / acciones
                stop_lvl = prom * (1 + stop_pct / 100.0)
                if gatillo is not None and mejor is not None:
                    favor = 100.0 * (prom - mejor) / prom
                    if favor >= gatillo:
                        stop_lvl = min(stop_lvl, prom * (1 - asegura / 100.0))

    # Lo que quede vivo, al cierre.
    if acciones > 0:
        c = dia.rth_close
        if c:
            pnl = acciones * (nominal / acciones - c) - acciones * COSTO_ACCION
            salidas.append({"h": CIERRE_RTH, "p": c, "acc": acciones,
                            "pnl": pnl, "motivo": "cierre"})

    if not entradas:
        return None
    bruto = sum(s["pnl"] for s in salidas)
    com = sum(comision(e["acc"]) for e in entradas) \
        + sum(comision(s["acc"]) for s in salidas)
    return {"pnl": bruto, "com": com, "pico": pico_acc,
            "entradas": len(entradas), "salidas": salidas}


def correr(gatillo, asegura):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                    max_float=47e6)
    pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]
    bruto = com = nom = 0.0
    ses = tr = 0
    stops = 0
    for d in pob:
        r = piramide(d, riesgo=RIESGO, stop_pct=STOP, gatillo=gatillo,
                     asegura=asegura, max_tramos=MAXT)
        if not r:
            continue
        bruto += r["pnl"]
        com += r["com"]
        # El locate se reserva por el PICO de acciones, igual que en la base.
        nom += r["pico"] * (d.rth_close or 0)
        tr += r["entradas"]
        ses += 1
        stops += sum(1 for s in r["salidas"] if s["motivo"] == "stop")
    neto = bruto - com
    return {"ses": ses, "tr": tr, "neto": neto, "nom": nom, "stops": stops,
            "ret": 100 * neto / nom if nom else 0.0}


def base():
    """La configuración vigente, para tener contra qué comparar."""
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                    max_float=47e6)
    pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]
    bruto = com = nom = 0.0
    ses = tr = 0
    for d in pob:
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=RIESGO,
                    max_trades=MAXT)
        if not j:
            continue
        b = j["pnl"]
        for t in j["detalle"]:
            b += t["acciones"] * COSTO_ACCION
            com += comision(t["acciones"])
        bruto += b
        nom += j["nominal"]
        tr += j["trades"]
        ses += 1
    neto = bruto - com
    return {"ses": ses, "tr": tr, "neto": neto, "nom": nom, "stops": None,
            "ret": 100 * neto / nom if nom else 0.0}


def linea(nombre, r, ref=None):
    d = ""
    if ref and ref["neto"]:
        d = "  ({:+.0f}%)".format(100 * (r["neto"] - ref["neto"]) / abs(ref["neto"]))
    st = "—" if r["stops"] is None else str(r["stops"])
    print("  {:<26} {:>5} {:>7} {:>9} ${:>10.0f} {:>8.2f}%{}".format(
        nombre, r["ses"], r["tr"], st, r["neto"], r["ret"], d))


print("\n  AGREGAR MAS ACHICANDO EL STOP\n")
print("  {:<26} {:>5} {:>7} {:>9} {:>11} {:>9}".format(
    "variante", "ses", "adds", "stopeados", "neto", "ret/nom"))
print("  " + "-" * 78)

b = base()
linea("BASE (tramos sueltos)", b)

# Una posicion, un solo stop, sin mover nada: aisla el efecto de manejarlo
# junto, antes de tocar el stop. Sin esto no se sabe que parte del cambio es
# por unificar y que parte por asegurar.
linea("una posicion, stop fijo", correr(None, 0.0), b)

for gat in (5.0, 10.0, 15.0, 20.0):
    for aseg in (0.0, 5.0):
        etiqueta = f"gatillo {gat:.0f}% -> " + ("BE" if aseg == 0 else f"+{aseg:.0f}%")
        linea(etiqueta, correr(gat, aseg), b)

print()
print("  'stopeados' es cuantas sesiones murieron por stop. Si sube mucho con")
print("  el gatillo, es que BE se toca por ruido y saca de trades que iban bien.")
