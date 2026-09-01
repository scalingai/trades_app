#!/usr/bin/env python3
"""Todo, medido en CENTAVOS POR ACCIÓN — que es la unidad en la que existe el costo.

**El cambio de unidad.** El proyecto venía midiendo contra `ret/nom` y un locate
de "20% del nominal". El 20% salía de un infoproducto que opera papeles de ~$1,
y el locate no se cobra como fracción del nominal: se cobra **por acción**. La
mediana de nuestro censo son $3,08, así que el mismo costo en dólares es un
tercio del porcentaje. La pregunta correcta no es "¿llegamos a 20 puntos de
ret/nom?" sino **"¿cuántos centavos por acción aguanta esto?"**.

POR QUÉ EL CAMBIO DE UNIDAD NO ES COSMÉTICO
-------------------------------------------
    $/acción  =  Σ pnl / acciones_pico  =  los DÓLARES que cae el papel, por
                                           acción prestada al mismo tiempo
    ret/nom   =  Σ pnl / nominal_pico   =  el PORCENTAJE que cae el papel

`ret/nom` **es ciego al precio por construcción**: dos papeles que caen 12% dan
el mismo número valgan $1 o $10, pero el de $10 deja diez veces más centavos
para pagar el locate. Todos los barridos de precio del proyecto se hicieron con
la métrica que borra justo esa variable, y por eso ninguno encontró nada. Este
archivo los rehace.

LA PREDICCIÓN, ESCRITA ANTES DE MEDIR
-------------------------------------
Si el % que cae el papel no depende del precio, entonces el punto de muerte en
$/acción tiene que escalar **linealmente con el precio de entrada**:

    punto de muerte ≈ precio de entrada × (% que cae)

Con la mediana de entrada en ~$3 y un 12% de caída en el reclaim, eso da ~$0,36.
Predicción operativa: **subir el piso de precio de $3 a $10 debería multiplicar
el punto de muerte por ~3**, si el edge porcentual aguanta.

Y el mecanismo que juega en contra, declarado también antes: en un gapper de
small cap el precio alto suele venir con más capitalización, más float
institucional y menos pólvora minorista, así que la caída porcentual podría
deteriorarse con el precio. Si se deteriora en la misma proporción, el punto de
muerte queda plano y **el precio no es una palanca**. Las dos hipótesis predicen
cosas distintas y la medición las separa. Lo que NO vale es mirar la tabla
primero y elegir la historia después.

LO QUE SE MIDE
--------------
  A) control de la unidad nueva (regla 4: métrica nueva, identidad que la ate)
  B) la línea de base en $/acción
  C) el barrido de precio — la prueba de la predicción de arriba
  D) los mecanismos de exposición, remedidos en $/acción: reducir posición en
     DÓLARES y reducirla en ACCIONES no son la misma operación
  E) el techo: cuánto daría con la salida perfecta, que acota todo lo demás

    python centavos.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict

import motor
from chavineta import clasificar_apertura as _clasificar
from dias import CIERRE_RTH, hora
from exposicion import acciones_pico, jornada_exp, ventana
from motor import COSTO_ACCION, R_BASE, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_CENSO = "2026-08-12"
CORTE_P = "2025-08-17"
LIMPIO = {"min_ratio_vol": 0.0, "min_dolar": 0.0}
CASOS = [("reclaim·exp100", "reclaim", 100.0, 60),
         ("fade·exp150", "fade", 150.0, 999)]


# --------------------------------------------------------------------------

def señal_con_piso(vm, piso=0.0, techo=None):
    """La señal de siempre, pero sin entrar si el papel cotiza fuera de la banda.

    El filtro es sobre el precio **de la barra de entrada**, no sobre el
    pre-market: es lo que se ve en pantalla en el minuto en que se decide, así
    que es observable sin ninguna licencia. Un filtro sobre el precio del día
    anterior sería más cómodo y menos honesto.
    """
    base = ventana(vm)

    def f(d):
        out = []
        for i in base(d):
            p = d.bars[i][4]
            if not p or p < piso or (techo is not None and p > techo):
                continue
            out.append(i)
        return out
    return f


def sesiones(dias, ap, ex, sig, *, presupuesto="mtm", pob_extra=None, pob_dia=None):
    """Una fila por sesión: (fecha, ticker, pnl$, nominal$, acciones_pico, precio).

    Se replica la cuota de `motor.evaluar`: cuando dos papeles califican el mismo
    día el riesgo se reparte, porque el presupuesto es del día y no del papel.
    """
    pob = poblacion(dias, min_expansion=ex, **LIMPIO, **(pob_extra or {}))
    if ap:
        pob = [d for d in pob if _clasificar(d, hasta=10.0) == ap]
    if pob_dia:
        pob = [d for d in pob if pob_dia(d)]
    por_fecha = defaultdict(list)
    for d in pob:
        por_fecha[d.d].append(d)

    filas = []
    for f in sorted(por_fecha):
        cands = por_fecha[f]
        cuota = R_BASE / len(cands)
        pnl = nom = acc = 0.0
        precios, tickers = [], []
        for d in cands:
            j = jornada_exp(d, sig, lado="short", stop_pct=45.0, riesgo=cuota,
                            max_trades=10, presupuesto=presupuesto)
            if not j:
                continue
            pnl += j["pnl"]
            nom += j["nominal"]
            acc += j["acciones"]
            precios += [t["p_ent"] for t in j["detalle"]]
            tickers.append(d.ticker)
        if tickers:
            filas.append((f, "+".join(sorted(set(tickers))), pnl, nom, acc,
                          statistics.median(precios)))
    return filas


def metricas(filas):
    """Las dos unidades sobre las mismas sesiones, más lo que hace falta leerlas."""
    if len(filas) < 20:
        return None
    pnl = statistics.mean(x[2] for x in filas)
    nom = statistics.mean(x[3] for x in filas)
    acc = statistics.mean(x[4] for x in filas)
    return {
        "n": len(filas),
        "ses_mes": len(filas) / motor.MESES,
        "pnl": pnl,
        "acc": acc,
        "muerte_c": 100 * pnl / acc if acc else 0.0,     # centavos por acción
        "ret_nom": 100 * pnl / nom if nom else 0.0,
        "precio": statistics.median(x[5] for x in filas),
        "pos": 100 * sum(1 for x in filas if x[2] > 0) / len(filas),
    }


def brecha(filas):
    """La diferencia de punto de muerte entre mitades, en centavos.

    Se reporta en la MISMA unidad que el número principal y no en puntos de
    ret/nom: comparar la réplica en una unidad y decidir en otra es cómo se
    cuelan los hallazgos que no replican.
    """
    a = metricas([x for x in filas if x[0] < CORTE_P])
    b = metricas([x for x in filas if x[0] >= CORTE_P])
    if not a or not b:
        return None, None, None
    return a["muerte_c"], b["muerte_c"], abs(a["muerte_c"] - b["muerte_c"])


CAB = (f"  {'':<24} {'ses/m':>6} {'n':>5} {'$ ent':>7} {'acc pico':>9} "
       f"{'$/ses':>8} {'MUERTE':>9} {'ret/nom':>9} {'P1':>7} {'P2':>7} {'brecha':>8}")


def fila(et, filas):
    m = metricas(filas)
    if not m:
        return f"  {et:<24} muestra corta ({len(filas)})"
    p1, p2, br = brecha(filas)
    # Una mitad con menos de 20 sesiones NO tiene brecha, y hay que escribir que
    # no la tiene. Poner un 0,0 ahí —que es lo que hacía la primera versión de
    # esta función— se lee como "replica perfecto", que es exactamente lo
    # contrario de lo que pasa: no se sabe. Es el mismo tipo de mentira por
    # formato que el `0.0` de las columnas P1/P2 vacías.
    c1 = f"{p1:>6.1f}c" if p1 is not None else f"{'—':>7}"
    c2 = f"{p2:>6.1f}c" if p2 is not None else f"{'—':>7}"
    cb = f"{br:>7.1f}c" if br is not None else f"{'sin mitad':>8}"
    return (f"  {et:<24} {m['ses_mes']:>6.1f} {m['n']:>5} {m['precio']:>7.2f} "
            f"{m['acc']:>9.0f} {m['pnl']:>+8.2f} {m['muerte_c']:>7.1f}c "
            f"{m['ret_nom']:>8.1f}% {c1} {c2} {cb}")


# --------------------------------------------------------------------------
# A) Control de la unidad nueva
# --------------------------------------------------------------------------

def control(dias):
    """Tres identidades que atan `acciones_pico` a algo que se puede verificar a mano.

    Regla 4 del proyecto aplicada a una métrica en vez de a un mecanismo: si se
    agrega un número nuevo, hay que agregar la identidad que lo ate. Un
    `acciones_pico` mal calculado no se nota — da un número plausible — y se
    llevaría puesta toda la tabla.
    """
    print("\n  A) CONTROL DE LA UNIDAD NUEVA\n")
    pob = poblacion(dias, min_expansion=150.0, **LIMPIO)
    pob = [d for d in pob if _clasificar(d, hasta=10.0) == "fade"]
    sig = ventana(999)
    ok = True

    # 1) un tramo solo: acciones_pico tiene que ser exactamente riesgo/(p·stop%)
    peor = 0.0
    n1 = 0
    for d in pob:
        if len(sig(d)) != 1:
            continue
        j = jornada_exp(d, sig, lado="short", stop_pct=45.0, riesgo=R_BASE,
                        max_trades=10, presupuesto="mtm")
        if not j:
            continue
        t = j["detalle"][0]
        esperado = (R_BASE / 3.0) / (t["p_ent"] * 0.45)
        peor = max(peor, abs(j["acciones"] - esperado))
        n1 += 1
    print(f"  {'OK  ' if peor < 1e-9 else 'FALLA'} un tramo: acciones_pico == "
          f"riesgo/(p·stop)      n={n1:<4} peor delta {peor:.2e}")
    ok &= peor < 1e-9

    # 2) un tramo solo: el punto de muerte ES el movimiento en dólares por acción
    peor = 0.0
    for d in pob:
        if len(sig(d)) != 1:
            continue
        j = jornada_exp(d, sig, lado="short", stop_pct=45.0, riesgo=R_BASE,
                        max_trades=10, presupuesto="mtm")
        if not j:
            continue
        t = j["detalle"][0]
        esperado = (t["p_ent"] - t["p_sal"]) - COSTO_ACCION
        peor = max(peor, abs(j["pnl"] / j["acciones"] - esperado))
    print(f"  {'OK  ' if peor < 1e-9 else 'FALLA'} un tramo: $/acción == caída "
          f"en dólares − costo   {'':<9} peor delta {peor:.2e}")
    ok &= peor < 1e-9

    # 3) el pico de acciones nunca puede superar la suma de todos los tramos, ni
    #    ser menor que el tramo más grande. Es flojo pero atrapa un barrido roto.
    malos = 0
    for d in pob[:400]:
        j = jornada_exp(d, sig, lado="short", stop_pct=45.0, riesgo=R_BASE,
                        max_trades=10, presupuesto="mtm")
        if not j:
            continue
        tot = sum(t["acciones"] for t in j["detalle"])
        mx = max(t["acciones"] for t in j["detalle"])
        if not (mx - 1e-9 <= j["acciones"] <= tot + 1e-9):
            malos += 1
    print(f"  {'OK  ' if not malos else 'FALLA'} pico entre el tramo más grande "
          f"y la suma        {'':<9} sesiones fuera de rango {malos}")
    ok &= not malos
    print(f"\n  {'TODOS OK' if ok else 'CONTROL EN ROJO — no leer las tablas'}")
    return ok


# --------------------------------------------------------------------------
# E) El techo
# --------------------------------------------------------------------------

def techo(dias, ap, ex, sig):
    """Cuánto daría el mismo censo con la salida PERFECTA. Es la cota de todo.

    Se sale en el mínimo posterior a la entrada, que nadie puede acertar. No es
    una estrategia: es el número que dice si el problema es de ejecución (hay
    plata en la mesa y hay que ir a buscarla) o de materia prima (el papel no se
    mueve lo suficiente y no hay salida que lo arregle).

    Se reporta también el techo de ENTRADA —entrar en el máximo de la rueda
    posterior a las 10:00— por la misma razón: separa "elegimos mal el minuto"
    de "el día no daba".
    """
    pob = poblacion(dias, min_expansion=ex, **LIMPIO)
    if ap:
        pob = [d for d in pob if _clasificar(d, hasta=10.0) == ap]
    real, perf_sal, perf_todo = [], [], []
    for d in pob:
        idx = sig(d)
        if not idx:
            continue
        i = idx[0]
        p = d.bars[i][4]
        post = [b for b in d.bars[i + 1:] if hora(b) <= CIERRE_RTH]
        if not p or not post:
            continue
        bajo = min(b[3] for b in post if b[3])
        real.append(p - (d.rth_close or p) - COSTO_ACCION)
        perf_sal.append(p - bajo - COSTO_ACCION)
        # techo total: entrar en el máximo de la rueda desde las 10:00 y salir
        # en el mínimo POSTERIOR a ese máximo
        rth = [b for b in d.bars if 10.0 <= hora(b) <= CIERRE_RTH]
        mejor = 0.0
        piso = None
        for b in reversed(rth):
            if b[3]:
                piso = b[3] if piso is None else min(piso, b[3])
            if b[2] and piso is not None:
                mejor = max(mejor, b[2] - piso)
        perf_todo.append(mejor - COSTO_ACCION)
    if not real:
        return
    print(f"  {'salida al cierre (lo real)':<34} {100*statistics.mean(real):>8.1f}c "
          f"por acción   mediana {100*statistics.median(real):>7.1f}c")
    print(f"  {'salida PERFECTA, misma entrada':<34} {100*statistics.mean(perf_sal):>8.1f}c "
          f"por acción   mediana {100*statistics.median(perf_sal):>7.1f}c")
    print(f"  {'entrada Y salida perfectas':<34} {100*statistics.mean(perf_todo):>8.1f}c "
          f"por acción   mediana {100*statistics.median(perf_todo):>7.1f}c")


# --------------------------------------------------------------------------

def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    vistos = [d for d in dias if d.d <= CORTE_CENSO]

    print("=" * 112)
    print("  TODO EN CENTAVOS POR ACCIÓN — la unidad en la que se cobra el locate")
    print("=" * 112)
    if not control(dias):
        return 1

    print("\n" + "=" * 112)
    print("  B) LA LÍNEA DE BASE, EN LAS DOS UNIDADES")
    print("=" * 112 + "\n")
    print(CAB)
    print("  " + "-" * 110)
    for lab, ap, ex, vm in CASOS:
        print(fila(lab, sesiones(vistos, ap, ex, ventana(vm))))

    print("\n" + "=" * 112)
    print("  C) BARRIDO DE PRECIO — la predicción es que el punto de muerte")
    print("     escala LINEALMENTE con el precio de entrada")
    print("=" * 112)
    for lab, ap, ex, vm in CASOS:
        print(f"\n  {lab.upper()}\n")
        print(CAB)
        print("  " + "-" * 110)
        for piso, tope in ((0, None), (0, 1.0), (1.0, 3.0), (3.0, 6.0),
                           (6.0, 12.0), (12.0, None), (2.0, None), (3.0, None),
                           (5.0, None), (10.0, None)):
            if tope is None:
                et = "todo" if piso == 0 else f"precio >= ${piso:.0f}"
            else:
                et = f"${piso:.0f} - ${tope:.0f}"
            print(fila(et, sesiones(vistos, ap, ex,
                                    señal_con_piso(vm, piso, tope))))

    print("\n" + "=" * 112)
    print("  D) MECANISMOS DE EXPOSICIÓN, EN $/ACCIÓN")
    print("     Reducir posición en dólares y reducirla en ACCIONES no son lo mismo.")
    print("=" * 112)
    POL = [("acumular", {}), ("rolar", dict(modo="rolar")),
           ("tope 2 · saltea", dict(modo="tope", tope=2)),
           ("tope 3 · saltea", dict(modo="tope", tope=3)),
           ("tope 2 · rola", dict(modo="tope-rolar", tope=2)),
           ("escala decreciente", dict(escala="decreciente")),
           ("escala mitad", dict(escala="mitad")),
           ("condicional", dict(modo="condicional"))]
    for lab, ap, ex, vm in CASOS:
        print(f"\n  {lab.upper()}\n")
        print(CAB)
        print("  " + "-" * 110)
        for pn, pol in POL:
            pob = poblacion(vistos, min_expansion=ex, **LIMPIO)
            if ap:
                pob = [d for d in pob if _clasificar(d, hasta=10.0) == ap]
            por_fecha = defaultdict(list)
            for d in pob:
                por_fecha[d.d].append(d)
            filas = []
            sig = ventana(vm)
            for f in sorted(por_fecha):
                cands = por_fecha[f]
                cuota = R_BASE / len(cands)
                pnl = nom = acc = 0.0
                precios, tk = [], []
                for d in cands:
                    j = jornada_exp(d, sig, lado="short", stop_pct=45.0,
                                    riesgo=cuota, max_trades=10,
                                    presupuesto="mtm", **pol)
                    if not j:
                        continue
                    pnl += j["pnl"]
                    nom += j["nominal"]
                    acc += j["acciones"]
                    precios += [t["p_ent"] for t in j["detalle"]]
                    tk.append(d.ticker)
                if tk:
                    filas.append((f, "+".join(sorted(set(tk))), pnl, nom, acc,
                                  statistics.median(precios)))
            print(fila(pn, filas))

    print("\n" + "=" * 112)
    print("  E) EL TECHO — cuánto habría con la salida perfecta")
    print("=" * 112)
    for lab, ap, ex, vm in CASOS:
        print(f"\n  {lab.upper()}\n")
        techo(vistos, ap, ex, ventana(vm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
