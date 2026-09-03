#!/usr/bin/env python3
"""¿Salir cuando el movimiento se muere gana más que salir a las 11:00?

**EL PASO QUE `test_durante.py` DEJO ESCRITO Y NUNCA SE HIZO.** Aquel test
midió, sobre 119.621 minutos con posición de 365 sesiones reclaim, qué rasgos
predicen cuánto MAS cae el papel del minuto t al cierre. Cuatro sobrevivieron
con el mismo signo en las dos mitades del tiempo, y el más fuerte por lejos fue
el rango de los últimos 15 minutos:

    rango ancho   +3,26% más de caída      rango angosto   -0,29% (sube)

O sea: **cuando la volatilidad se seca, lo que queda de rueda ya no da.** Y el
commit de ese test terminaba diciendo lo que faltaba, textual: "separar no es
ganar plata. El próximo paso es convertir esto en una regla de salida y medirla
contra un placebo de la misma frecuencia". Esto es eso.

**POR QUE PUEDE FUNCIONAR CUANDO DOCE INTENTOS FALLARON.** Los doce eran
winner-cutters: objetivo fijo, trailing, breakeven. Salen cuando el trade va a
favor, y la estrategia vive de la cola derecha —los pocos días que se derrumban
en serio—, así que cortarlos la mata. Esto es otra cosa: corta lo que DEJO DE
MOVERSE, gane o pierda. Es la misma forma que el corte de las 11:00, que es lo
único que funcionó en todo el proyecto — con la diferencia de que el corte lo
decide por RELOJ y esto lo decide por ESTADO.

**LOS TRES CONTROLES, declarados antes de correr:**

  1. PLACEBO DE LA MISMA FRECUENCIA. Por cada día en que la regla real dispara,
     el placebo dispara también — pero en un minuto al azar de ese mismo día.
     Misma cantidad de salidas, mismo día, timing sorteado. Si el placebo rinde
     igual, lo que ayuda es SALIR ANTES y no la señal. Es el control que mató
     al filtro de EDGAR y a trece mecanismos.
  2. GRILLA DE UMBRALES, no el mejor. Se reportan todos. Un umbral que gana
     rodeado de umbrales que pierden es ruido, no un óptimo.
  3. LAS DOS MITADES DEL TIEMPO. Lo que no aparece en las dos, no existe.

**LA METRICA QUE DECIDE ES EL DRAWDOWN**, no la plata. La cuenta de fondeo se
liquida por caída de equity contra un tope de $1.000; una variante que gana más
con peor drawdown es peor variante.

    python test_salida_rango_seco.py
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
VENTANA = 15          # minutos de la ventana de rango, igual que test_durante
REPES = 25            # sorteos del placebo


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def rangos(dia):
    """`rango_15_pct` barra por barra, con la MISMA definición que test_durante.

    Sólo mira `bars[:i+1]`: es un rasgo observable en el minuto, no una
    reconstrucción posterior.
    """
    out = [None] * len(dia.bars)
    for i in range(len(dia.bars)):
        if hora(dia.bars[i]) < DESDE:
            continue
        px = dia.bars[i][4]
        if not px:
            continue
        ventana = dia.bars[max(0, i - VENTANA + 1):i + 1]
        altos = [x[2] for x in ventana if x[2]]
        bajos = [x[3] for x in ventana if x[3]]
        if altos and bajos:
            out[i] = 100.0 * (max(altos) - min(bajos)) / px
    return out


def jornada(dia, *, corte_h=None, umbral_corte=5.0,
            seco=None, rango=None, i_azar=None):
    """La estrategia de siempre con UNA salida opcional.

    `corte_h`  — el corte por reloj de hoy (cerrar si no gana `umbral_corte`%).
    `seco`     — cortar en el primer minuto con `rango_15_pct` < `seco`.
    `i_azar`   — cortar en ese índice, sea cual sea. Es el placebo.

    Las tres son excluyentes y salen por el mismo camino, para que la única
    diferencia entre ellas sea CUANDO se decide y no cómo se ejecuta.
    """
    idx = [i for i in señales_swing(dia, desde=DESDE)
           if (dia.bars[i][4] or 0) >= PISO]
    if not idx:
        return None
    cierre = dia.rth_close
    if not cierre:
        return None
    r_trade = RIESGO / 3.0

    detalle = []
    for i in idx:
        if len(detalle) >= MAXT:
            break
        p = dia.bars[i][4]
        if not p:
            continue
        equity = 0.0
        for t in detalle:
            if t["i_sal"] is not None and t["i_sal"] <= i:
                equity += t["pnl"]
            else:
                equity += t["acciones"] * (t["p_ent"] - p)
        if equity - r_trade < -RIESGO:
            break
        detalle.append({"acciones": r_trade / (p * STOP / 100.0), "p_ent": p,
                        "i_ent": i, "i_sal": None, "p_sal": None,
                        "pnl": 0.0, "motivo": None})
        t = detalle[-1]
        p_stop = p * (1 + STOP / 100.0)
        for k in range(i + 1, len(dia.bars)):
            bk = dia.bars[k]
            if hora(bk) > CIERRE_RTH:
                break
            if bk[2] and bk[2] >= p_stop:
                t["i_sal"], t["p_sal"], t["motivo"] = k, p_stop, "stop"
                break
        if t["i_sal"] is None:
            t["p_sal"], t["motivo"] = cierre, "cierre"
        t["pnl"] = t["acciones"] * (p - t["p_sal"]) - t["acciones"] * COSTO_ACCION

    if not detalle:
        return None

    # ---- donde cae la salida, si hay alguna --------------------------------
    i_salida = None
    if i_azar is not None:
        i_salida = i_azar
    elif seco is not None and rango:
        # PRIMER minuto en que el rango se seca CON POSICION ABIERTA. Buscar
        # antes de la primera entrada daria una salida antes de entrar.
        i0 = detalle[0]["i_ent"]
        for k in range(i0 + 1, len(dia.bars)):
            if hora(dia.bars[k]) > CIERRE_RTH:
                break
            if rango[k] is not None and rango[k] < seco:
                i_salida = k
                break
    elif corte_h is not None:
        i_c = dia.idx_en(corte_h)
        if i_c is not None:
            px = dia.bars[i_c][4]
            vivos = [t for t in detalle if t["i_ent"] < i_c
                     and (t["i_sal"] is None or t["i_sal"] > i_c)]
            if px and vivos:
                acc = sum(t["acciones"] for t in vivos)
                prom = sum(t["p_ent"] * t["acciones"] for t in vivos) / acc
                if 100.0 * (prom - px) / prom < umbral_corte:
                    i_salida = i_c

    if i_salida is not None:
        px = dia.bars[i_salida][4]
        if px:
            for t in detalle:
                if t["i_ent"] < i_salida and (t["i_sal"] is None
                                              or t["i_sal"] > i_salida):
                    t["i_sal"], t["p_sal"], t["motivo"] = i_salida, px, "salida"
                    t["pnl"] = (t["acciones"] * (t["p_ent"] - px)
                                - t["acciones"] * COSTO_ACCION)
            # El dia se cerro: los tramos posteriores no existen.
            detalle = [t for t in detalle if t["i_ent"] <= i_salida]

    if not detalle:
        return None
    bruto = sum(t["pnl"] + t["acciones"] * COSTO_ACCION for t in detalle)
    com = sum(comision(t["acciones"]) for t in detalle)
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
            "trades": len(detalle), "disparo": i_salida is not None,
            "i_ent0": detalle[0]["i_ent"]}


def correr(dias, rango_de, **kw):
    neto = nom = 0.0
    ses = tr = disp = 0
    por_dia = {}
    for d in dias:
        r = jornada(d, rango=rango_de.get(d.d + d.ticker), **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        disp += 1 if r["disparo"] else 0
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    acum = pico = dd = 0.0
    for f in sorted(por_dia):
        acum += por_dia[f]
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return {"ses": ses, "tr": tr, "neto": neto, "dd": dd, "disp": disp,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0}


def placebo(dias, rango_de, seco, semilla):
    """Dispara en los MISMOS días que la regla real, en un minuto al azar.

    Misma frecuencia, mismo día, timing sorteado. Si esto rinde igual que la
    regla, lo que ayuda es salir antes y la señal es decoración.
    """
    rnd = random.Random(semilla)
    neto = nom = 0.0
    ses = tr = 0
    por_dia = {}
    for d in dias:
        rg = rango_de.get(d.d + d.ticker)
        real = jornada(d, seco=seco, rango=rg)
        if not real:
            continue
        i_az = None
        if real["disparo"]:
            # Minutos elegibles: con posicion abierta y antes del cierre.
            lo = real["i_ent0"] + 1
            hi = max(lo, (d.idx_en(CIERRE_RTH) or len(d.bars) - 1))
            i_az = rnd.randint(lo, hi) if hi > lo else None
        r = jornada(d, i_azar=i_az) if i_az is not None else jornada(d)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    acum = pico = dd = 0.0
    for f in sorted(por_dia):
        acum += por_dia[f]
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return {"neto": neto, "dd": dd,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0}


def fila(etq, r, extra=""):
    print("  {:<26} {:>5} {:>7} ${:>9,.0f} {:>7.2f}% ${:>7.0f} ${:>10,.0f} {}"
          .format(etq, r["ses"], r["tr"], r["neto"], r["ret"], r["por_ses"],
                  r["dd"], extra))


def bloque(dias, rango_de, umbrales, titulo):
    print(f"\n  {titulo}  ({len(dias)} días)")
    print("  {:<26} {:>5} {:>7} {:>10} {:>8} {:>8} {:>11}".format(
        "variante", "ses", "trades", "neto", "ret/nom", "$/ses", "drawdown"))
    print("  " + "-" * 88)
    fila("sostiene al cierre", correr(dias, rango_de))
    fila("corte 11:00 si <5%  (hoy)", correr(dias, rango_de, corte_h=11.0))
    print()
    for u in umbrales:
        r = correr(dias, rango_de, seco=u)
        pl = [placebo(dias, rango_de, u, s) for s in range(REPES)]
        pl_ses = statistics.mean(p["por_ses"] for p in pl)
        pl_dd = statistics.mean(p["dd"] for p in pl)
        gana = sum(1 for p in pl if p["por_ses"] >= r["por_ses"])
        veredicto = (f"placebo ${pl_ses:.0f} · p={gana / REPES:.2f}"
                     + ("  <== le gana" if gana / REPES < 0.05 else ""))
        fila(f"rango seco < {u:.2f}%", r,
             f"disparo {100 * r['disp'] / max(1, r['ses']):.0f}% · {veredicto}")
        print(" " * 28 + f"placebo mismo n: ${pl_ses:.0f}/ses · "
              f"dd ${pl_dd:,.0f}")


# El analisis corre SOLO como script. Sin esto, `from test_salida_rango_seco
# import rangos` en otro test dispara las 300 simulaciones de aca de
# nuevo — que es lo que paso, y por eso el test siguiente tardo el doble.
if __name__ == "__main__":
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: d.d)
    rango_de = {d.d + d.ticker: rangos(d) for d in pob}

    # La grilla sale de la DISTRIBUCION del rasgo, no de probar numeros lindos.
    todos = [v for rg in rango_de.values() for v in rg if v is not None]
    todos.sort()
    qs = [0.15, 0.25, 0.35, 0.50]
    umbrales = [round(todos[int(q * len(todos))], 2) for q in qs]

    print(f"\n  SALIR CUANDO EL MOVIMIENTO SE MUERE")
    print(f"  {len(pob)} días reclaim · rango_15_pct medido en "
          f"{len(todos):,} minutos con posición")
    print(f"  umbrales = percentiles {[int(q * 100) for q in qs]} del rasgo: "
          f"{umbrales}")

    bloque(pob, rango_de, umbrales, "TODA LA MUESTRA")
    mitad = len(pob) // 2
    bloque(pob[:mitad], rango_de, umbrales,
           f"PRIMERA MITAD ({pob[0].d} a {pob[mitad - 1].d})")
    bloque(pob[mitad:], rango_de, umbrales,
           f"SEGUNDA MITAD ({pob[mitad].d} a {pob[-1].d})")

    print("\n  COMO SE LEE")
    print("  Para que esto sirva tiene que pasar TRES cosas a la vez: ganarle al")
    print("  corte de las 11:00, ganarle al placebo de la misma frecuencia, y")
    print("  hacerlo en las DOS mitades. Con dos de tres, no alcanza.")
