#!/usr/bin/env python3
"""A las 11:00 y perdiendo: ¿cortar siempre, o mirar si el movimiento sigue vivo?

**DE DONDE VIENE.** Dos resultados que se cruzan:

  · El corte de las 11:00 es lo único que hizo la estrategia operable en una
    cuenta de fondeo. Pero `test_salida_rango_seco.py` mostró que NO está
    comprando plata: un placebo que sale en un minuto al azar da $147-$165 por
    sesión contra los $110 del corte. Lo único que el corte compra es
    drawdown: -$1.229 contra -$3.684.

  · El rango de los últimos 15 minutos es el único rasgo del proyecto que le
    ganó a un placebo de la misma frecuencia (p=0.00 en la muestra entera).
    Cuando el rango se seca, lo que queda de rueda ya no da (-0,29%: en
    promedio SUBE). Cuando sigue ancho, sí da (+3,26%).

**LA IDEA.** No reemplazar el corte —eso ya se probó y su drawdown es peor—
sino CONDICIONARLO. A las 11:00, con la posición perdiendo:

    hoy          cortar siempre
    la idea      cortar sólo si además el rango se secó. Si el rango sigue
                 ancho, el movimiento está vivo y se aguanta.

Conserva lo único que el corte compra (sacar del medio los días muertos) y le
suma la única señal que superó un placebo.

**LOS CONTROLES, declarados antes de correr:**

  1. CONTROL DE SIGNO. Se mide también la regla al revés —aguantar cuando el
     rango se SECO y cortar cuando sigue ancho—. Si las dos "mejoran", lo que
     mejora es cortar menos y el rango es decoración.
  2. PLACEBO DE LA MISMA FRECUENCIA. Aguantar al azar la MISMA proporción de
     perdedores que aguanta la regla. Si rinde igual, lo que ayuda es cortar
     menos veces, no elegir cuáles.
  3. GRILLA DE UMBRALES, no el mejor, y las dos mitades del tiempo.

**LA METRICA QUE DECIDE ES EL DRAWDOWN.** Si esto gana plata y empeora el
drawdown, es la misma respuesta que ya tuvimos tres veces: plata que la cuenta
no llega a cobrar.

    python test_corte_condicionado.py
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
from test_salida_rango_seco import (MAXT, PISO, RIESGO, STOP, DESDE,
                                    comision, rangos)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_H, UMBRAL = 11.0, 5.0
REPES = 25


def jornada(dia, *, rango=None, modo="siempre", seco=None, tasa_corte=None):
    """El corte de las 11:00, con la decisión sobre los PERDEDORES abierta.

    `modo`:
      "nunca"    — sostener al cierre. La base.
      "siempre"  — cortar todo perdedor. Lo que hace hoy el sistema.
      "seco"     — cortar sólo si el rango de los últimos 15' < `seco`.
      "ancho"    — al revés: cortar sólo si el rango >= `seco`. Control de signo.
      "azar"     — cortar con probabilidad `tasa_corte`. El placebo.

    OJO CON EL NOMBRE DE ESE PARAMETRO. La primera version se llamaba
    `aguantar` y hacia `random.random() >= aguantar` pasandole la tasa de
    CORTE: con 9 cortes sobre 133 perdedores, el placebo cortaba el 93% en vez
    del 7%. O sea competia contra el corte-siempre y la regla real le "ganaba"
    con p=0.00 sin haber ganado nada. Un placebo mal armado no falla ruidoso:
    devuelve el resultado que uno queria ver.

    Todo lo demás es idéntico entre modos: mismas entradas, mismo stop, mismo
    presupuesto. La única diferencia es a quién se le perdona el corte.
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

    perdiendo = cortado = False
    if modo != "nunca":
        i_c = dia.idx_en(CORTE_H)
        px = dia.bars[i_c][4] if i_c is not None else None
        vivos = [t for t in detalle if t["i_ent"] < i_c
                 and (t["i_sal"] is None or t["i_sal"] > i_c)] if px else []
        if px and vivos:
            acc = sum(t["acciones"] for t in vivos)
            prom = sum(t["p_ent"] * t["acciones"] for t in vivos) / acc
            perdiendo = 100.0 * (prom - px) / prom < UMBRAL
            if perdiendo:
                r = rango[i_c] if rango else None
                if modo == "siempre":
                    cortado = True
                elif modo == "seco":
                    cortado = r is not None and r < seco
                elif modo == "ancho":
                    cortado = r is not None and r >= seco
                elif modo == "azar":
                    cortado = random.random() < tasa_corte
            if cortado:
                for t in vivos:
                    t["i_sal"], t["p_sal"], t["motivo"] = i_c, px, "corte"
                    t["pnl"] = (t["acciones"] * (t["p_ent"] - px)
                                - t["acciones"] * COSTO_ACCION)
                detalle = [t for t in detalle if t["i_ent"] <= i_c]

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
            "trades": len(detalle), "perdiendo": perdiendo, "cortado": cortado}


def correr(dias, rango_de, **kw):
    neto = nom = 0.0
    ses = tr = perd = cort = 0
    por_dia = {}
    for d in dias:
        r = jornada(d, rango=rango_de.get(d.d + d.ticker), **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        perd += 1 if r["perdiendo"] else 0
        cort += 1 if r["cortado"] else 0
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]
    acum = pico = dd = 0.0
    for f in sorted(por_dia):
        acum += por_dia[f]
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return {"ses": ses, "tr": tr, "neto": neto, "dd": dd,
            "perd": perd, "cort": cort,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0}


def fila(etq, r, extra=""):
    print("  {:<28} {:>5} {:>7} ${:>9,.0f} {:>7.2f}% ${:>7.0f} ${:>10,.0f}  {}"
          .format(etq, r["ses"], r["tr"], r["neto"], r["ret"], r["por_ses"],
                  r["dd"], extra))


def bloque(dias, rango_de, umbrales, titulo):
    print(f"\n  {titulo}  ({len(dias)} días)")
    print("  {:<28} {:>5} {:>7} {:>10} {:>8} {:>8} {:>11}".format(
        "variante", "ses", "trades", "neto", "ret/nom", "$/ses", "drawdown"))
    print("  " + "-" * 92)
    fila("sostiene al cierre", correr(dias, rango_de, modo="nunca"))
    hoy = correr(dias, rango_de, modo="siempre")
    fila("corta SIEMPRE  (hoy)", hoy,
         f"perdiendo a las 11 en {hoy['perd']} · corta {hoy['cort']}")
    print()
    for u in umbrales:
        r = correr(dias, rango_de, modo="seco", seco=u)
        if not r["perd"]:
            continue
        # Placebo con la MISMA proporcion de perdonados.
        tasa = r["cort"] / r["perd"]
        pl = []
        for s in range(REPES):
            random.seed(s)
            pl.append(correr(dias, rango_de, modo="azar", tasa_corte=tasa))
        pl_ses = statistics.mean(p["por_ses"] for p in pl)
        pl_dd = statistics.mean(p["dd"] for p in pl)
        gana = sum(1 for p in pl if p["por_ses"] >= r["por_ses"]) / REPES
        fila(f"corta si rango < {u:.2f}%", r,
             f"corta {r['cort']}/{r['perd']} · placebo ${pl_ses:.0f}"
             f" dd ${pl_dd:,.0f} · p={gana:.2f}"
             + ("  <== le gana" if gana < 0.05 else ""))
        c = correr(dias, rango_de, modo="ancho", seco=u)
        fila(f"   al revés (control)", c,
             f"corta {c['cort']}/{c['perd']}")


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]
pob.sort(key=lambda d: d.d)
rango_de = {d.d + d.ticker: rangos(d) for d in pob}
todos = sorted(v for rg in rango_de.values() for v in rg if v is not None)
qs = [0.25, 0.40, 0.55, 0.70]
umbrales = [round(todos[int(q * len(todos))], 2) for q in qs]

print("\n  A LAS 11:00 Y PERDIENDO: ¿CORTAR SIEMPRE O MIRAR SI SIGUE VIVO?")
print(f"  {len(pob)} días reclaim · umbrales = percentiles "
      f"{[int(q * 100) for q in qs]} del rango: {umbrales}")

bloque(pob, rango_de, umbrales, "TODA LA MUESTRA")
mitad = len(pob) // 2
bloque(pob[:mitad], rango_de, umbrales,
       f"PRIMERA MITAD ({pob[0].d} a {pob[mitad - 1].d})")
bloque(pob[mitad:], rango_de, umbrales,
       f"SEGUNDA MITAD ({pob[mitad].d} a {pob[-1].d})")

print("\n  COMO SE LEE")
print("  Sirve sólo si: baja o empata el drawdown del corte de hoy, le gana al")
print("  placebo de la misma frecuencia, el control al revés NO mejora, y todo")
print("  eso pasa en las DOS mitades. Con tres de cuatro, no alcanza.")
