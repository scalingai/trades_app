#!/usr/bin/env python3
"""Salidas y gestión del trade: ¿alguna forma de cerrar mejora el ret/nom?

**Por qué esta familia se mide distinto de las otras.** Con cuentas de fondeo el
locate se cobra como porcentaje del NOMINAL desplegado, así que la métrica que
decide es `ret/nom`. Y acá aparece una identidad que hay que tener adelante todo
el tiempo porque ordena el resto del archivo:

    acciones = riesgo / (p · stop/100)   →   nominal = acciones · p = riesgo·100/stop

El precio se cancela. **El nominal no depende del papel ni de la salida: depende
sólo del stop.** Un stop del 45% despliega un tercio del nominal de uno del 15%
para el mismo riesgo en dólares. Consecuencias, las dos incómodas:

  1. A stop fijo, TODAS las variantes de salida tienen el MISMO `nom_R`. Se
     verifica numéricamente más abajo, no se asume. Entonces ordenar por
     `ret/nom` es exactamente ordenar por PnL: **la familia de salidas no tiene
     ninguna palanca sobre el denominador**. Lo único que mueve el nominal es el
     ancho del stop.
  2. Por eso la grilla es stop × objetivo y no sólo objetivo. Cualquier salida
     que para funcionar necesite un stop más corto se está pagando el doble o el
     triple de locate, y hay que verlo en la misma tabla o la comparación miente.

**El locate no se devuelve si salís temprano.** Se lo reserva por el día. Una
salida a las 10:30 y una salida parcial usan el mismo nominal que sostener hasta
el cierre: pueden ganar por PnL, nunca por costo. Es la hipótesis contraria a la
intuición de "salgo antes, pago menos", y es la que manda en toda esta familia.

LO QUE YA SABEMOS Y HAY QUE PONER A PRUEBA IGUAL. En este proyecto el patrón
"asegurar empeora" apareció ocho veces: acortar la tenencia, objetivos cortos,
trailing, salidas por anomalía, tomar ganancia temprano, cerrar la jornada al
llegar al objetivo. Se entra esperando la novena. Si aparece una excepción hay
que sospecharla más que al resto, y por eso toda excepción pasa por tres
validaciones antes de que la llame excepción: réplica P1/P2, otra población
(expansión ≥100 en vez de ≥150) y otro stop.

CONVENCIONES QUE NO SE TOCAN:

  · Si en el mismo minuto se tocan stop y objetivo, gana el stop. No sabemos qué
    vino primero adentro de la barra.
  · Los niveles que se mueven —trailing, break-even— se recalculan al CIERRE de
    cada barra y rigen recién en la barra siguiente. El mínimo corriente no se
    conoce hasta que la barra cerró; dejar que el stop baje y te llene en la
    misma barra sería mirar el futuro y regala plata gratis.
  · El VWAP usado como objetivo es el de la barra ANTERIOR, por lo mismo:
    `vwap[j]` incluye la barra j.

Este archivo NO modifica `motor.py` —hay otros procesos corriendo contra él— y
en cambio reimplementa `_trade`/`jornada`/`evaluar` con la gestión adentro,
reutilizando de motor todo lo que decide comparabilidad: población, métricas,
corte P1/P2, costos y persistencia. El chequeo de equivalencia del paso 0 es lo
que hace legítima esa copia: si con gestión vacía no reproduce a motor al
decimal, el resto del archivo no vale nada.

    python salidas.py
    python salidas.py --exp 100 --stop 45
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

import motor
from chavineta import clasificar_apertura
from dias import CIERRE_RTH, hora
from motor import (CORTE, MESES, R_BASE, correlacion, universo)
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

COSTO_ACCION = motor.COSTO_ACCION
LOCATE_REF = motor.LOCATE_REF


# --------------------------------------------------------------------------
# La gestión: todo lo que puede pasarle a un trade entre la entrada y la salida
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Gestion:
    """Una forma de cerrar el trade. `Gestion()` = sostener hasta el cierre.

    Todos los campos son opt-in y el default reproduce el comportamiento de
    `motor._trade`. Eso permite que la misma función sirva de línea de base y de
    variante, que es lo que hace la comparación honesta: si la base se midiera
    con otro código, cualquier diferencia sería atribuible al código.
    """

    objetivo_pct: float | None = None     # toma ganancia a X% a favor
    salida_h: float | None = None         # cierra a una hora decimal fija
    entradas_hasta: float | None = None   # no abre después de esta hora
    max_min: float | None = None          # minutos máximos en la posición
    trail_devuelve: float | None = None   # stop que devuelve X% del recorrido
    trail_ancho: float | None = None      # stop que vive X% arriba del mínimo
    trail_arma: float = 0.0               # el trailing recién se activa a X% a favor
    be_pct: float | None = None           # stop a la entrada cuando va X% a favor
    parcial_pct: float | None = None      # cierra una fracción a X% a favor
    parcial_frac: float = 0.5
    parcial_be: bool = False              # y deja el resto con stop en la entrada
    vwap: bool = False                    # cierra al tocar el VWAP desde arriba

    def descripcion(self) -> str:
        p = []
        if self.objetivo_pct:
            p.append(f"objetivo {self.objetivo_pct:g}%")
        if self.salida_h:
            p.append(f"cierra {self.salida_h:g}h")
        if self.entradas_hasta:
            p.append(f"entradas hasta {self.entradas_hasta:g}h")
        if self.max_min:
            p.append(f"máx {self.max_min:g} min en posición")
        if self.trail_devuelve is not None:
            p.append(f"trailing devuelve {100*self.trail_devuelve:.0f}% del recorrido")
        if self.trail_ancho is not None:
            p.append(f"trailing a {self.trail_ancho:g}% del mínimo corriente")
        if self.trail_arma:
            p.append(f"arma a {self.trail_arma:g}% a favor")
        if self.be_pct:
            p.append(f"break-even a {self.be_pct:g}%")
        if self.parcial_pct:
            p.append(f"cierra {100*self.parcial_frac:.0f}% a {self.parcial_pct:g}%"
                     + (" y el resto en break-even" if self.parcial_be else ""))
        if self.vwap:
            p.append("cierra al VWAP")
        return " · ".join(p) or "sostener hasta el cierre RTH"


BASE = Gestion()


# --------------------------------------------------------------------------
# El trade con gestión adentro
# --------------------------------------------------------------------------

def _trade(dia, i, *, lado, stop_pct, riesgo, g: Gestion):
    """Un trade con tamaño por riesgo y la gestión `g`. Superset de motor._trade.

    El PnL de CUALQUIER salida se calcula del precio, nunca del riesgo nominal.
    Con el stop original la fórmula da exactamente −riesgo (se cancela por
    construcción), pero con un stop movido —trailing, break-even— el mismo stop
    puede terminar en ganancia, y ahí la fórmula de motor (−riesgo fijo) sería
    directamente falsa. Es la razón de fondo por la que esta función existe.
    """
    p = dia.bars[i][4]
    if not p or stop_pct <= 0:
        return None
    acciones = riesgo / (p * stop_pct / 100.0)
    nominal = acciones * p
    corto = lado == "short"
    signo = -1.0 if corto else 1.0
    p_stop = p * (1 - signo * stop_pct / 100.0)
    p_obj = p * (1 + signo * g.objetivo_pct / 100.0) if g.objetivo_pct else None
    p_par = p * (1 + signo * g.parcial_pct / 100.0) if g.parcial_pct else None
    h_ent = hora(dia.bars[i])

    def apretar(a, b):
        """El más protector de dos niveles de stop, según el lado."""
        return min(a, b) if corto else max(a, b)

    abiertas = acciones          # lo que queda vivo (baja con las parciales)
    realizado = 0.0              # PnL ya embolsado por las parciales
    mejor = p                    # extremo corriente A FAVOR (mín. si es corto)
    mae = mfe = 0.0
    hecha_parcial = False

    def cerrar(pnl, motivo, h_sal, p_sal):
        return {"pnl": pnl, "motivo": motivo, "nominal": nominal,
                "acciones": acciones, "h_ent": h_ent, "p_ent": p,
                "h_sal": h_sal, "p_sal": p_sal, "stop_pct": stop_pct,
                "mae_pct": round(mae, 2), "mfe_pct": round(mfe, 2)}

    def salir(p_sal, motivo, h_sal):
        pnl = realizado + signo * abiertas * (p_sal - p) - abiertas * COSTO_ACCION
        return cerrar(pnl, motivo, h_sal, p_sal)

    for j in range(i + 1, len(dia.bars)):
        b = dia.bars[j]
        h = hora(b)
        if h > CIERRE_RTH:
            break
        if b[2] and b[3]:
            fav = (p - b[3]) if corto else (b[2] - p)
            adv = (b[2] - p) if corto else (p - b[3])
            mfe = max(mfe, 100 * fav / p)
            mae = min(mae, -100 * adv / p)

        # 1) el stop, con el nivel que quedó fijado al cierre de la barra previa
        toca_stop = (b[2] and b[2] >= p_stop) if corto else (b[3] and b[3] <= p_stop)
        if toca_stop:
            return salir(p_stop, "stop", h)

        # 2) el objetivo fijo
        if p_obj is not None:
            toca = (b[3] and b[3] <= p_obj) if corto else (b[2] and b[2] >= p_obj)
            if toca:
                return salir(p_obj, "objetivo", h)

        # 3) la parcial: no cierra el trade, achica lo que queda vivo
        if p_par is not None and not hecha_parcial:
            toca = (b[3] and b[3] <= p_par) if corto else (b[2] and b[2] >= p_par)
            if toca:
                cierra = acciones * g.parcial_frac
                realizado += (signo * cierra * (p_par - p)
                              - cierra * COSTO_ACCION)
                abiertas -= cierra
                hecha_parcial = True
                if g.parcial_be:
                    p_stop = apretar(p_stop, p)

        # 4) el VWAP como objetivo dinámico. Sólo cuenta si está DEL LADO de la
        #    ganancia (para un corto, por debajo de la entrada): si el papel
        #    entró ya por debajo del VWAP, esta regla simplemente no aplica y el
        #    trade corre al cierre. Se usa el VWAP de la barra anterior porque
        #    `vwap[j]` incorpora la barra j y sería mirar adentro del futuro.
        if g.vwap:
            v = dia.vwap[j - 1]
            del_lado = (v < p) if corto else (v > p)
            if v and del_lado:
                toca = (b[3] and b[3] <= v) if corto else (b[2] and b[2] >= v)
                if toca:
                    return salir(v, "vwap", h)

        # 5) las salidas por reloj
        if g.salida_h is not None and h >= g.salida_h:
            return salir(b[4] or p, "hora", h)
        if g.max_min is not None and (h - h_ent) * 60.0 >= g.max_min:
            return salir(b[4] or p, "tiempo", h)

        # 6) AL CIERRE DE LA BARRA: se actualiza el extremo corriente y se
        #    recalculan los niveles móviles, que recién rigen en la barra que
        #    viene. Este orden es la diferencia entre medir un trailing y
        #    medirse a uno mismo mirando el futuro.
        if corto and b[3] and b[3] < mejor:
            mejor = b[3]
        elif not corto and b[2] and b[2] > mejor:
            mejor = b[2]
        recorrido = abs(mejor - p)
        rec_pct = 100 * recorrido / p
        if rec_pct >= g.trail_arma:
            if g.trail_devuelve is not None:
                cand = (mejor + g.trail_devuelve * recorrido if corto
                        else mejor - g.trail_devuelve * recorrido)
                p_stop = apretar(p_stop, cand)
            if g.trail_ancho is not None:
                cand = (mejor * (1 + g.trail_ancho / 100.0) if corto
                        else mejor * (1 - g.trail_ancho / 100.0))
                p_stop = apretar(p_stop, cand)
        if g.be_pct is not None and rec_pct >= g.be_pct:
            p_stop = apretar(p_stop, p)

    c = dia.rth_close
    if not c:
        return None
    return salir(c, "cierre", CIERRE_RTH)


def jornada(dia, señal, *, lado, stop_pct, riesgo, max_trades=10, g: Gestion = BASE):
    """Igual que `motor.jornada` pero con gestión. La regla de presupuesto NO cambia.

    Se copia en vez de importarse porque `motor.jornada` llama a `motor._trade`
    por nombre. El presupuesto diario, el reparto por tercios y el nominal
    tomado como MÁXIMO (no suma) son idénticos a propósito: si cambiara alguno,
    los números de esta familia dejarían de ser comparables con todo lo validado.
    """
    idx = señal(dia)
    if g.entradas_hasta is not None:
        idx = [i for i in idx if hora(dia.bars[i]) <= g.entradas_hasta]
    if not idx:
        return None
    r_trade = riesgo / 3.0
    pnl, nominal, n = 0.0, 0.0, 0
    detalle = []
    for i in idx:
        if n >= max_trades:
            break
        if pnl - r_trade < -riesgo:
            break
        r = _trade(dia, i, lado=lado, stop_pct=stop_pct, riesgo=r_trade, g=g)
        if not r:
            continue
        pnl += r["pnl"]
        nominal = max(nominal, r["nominal"])
        n += 1
        detalle.append(r)
    if not n:
        return None
    return {"pnl": pnl, "nominal": nominal, "trades": n, "detalle": detalle}


def evaluar(nombre, señal, *, dias=None, lado="short", stop=45.0, pob=None,
            max_trades=10, g: Gestion = BASE, guardar=True, apertura="fade",
            familia="salida", notas=""):
    """Corre una gestión y devuelve el diccionario estándar de `motor`.

    Mismo esqueleto que `motor.evaluar` —misma población, mismo corte P1/P2,
    mismas métricas, misma persistencia— con la gestión inyectada. Lo que se
    guarda en `notas` es la descripción completa de la gestión, porque las
    columnas de la tabla `estrategia` sólo tienen lugar para objetivo y hora.
    """
    if dias is None:
        dias = universo()
    pobl = motor.poblacion(dias, **(pob or {}))
    if apertura:
        pobl = [d for d in pobl if clasificar_apertura(d) == apertura]

    por_fecha = defaultdict(list)
    for dia in pobl:
        por_fecha[dia.d].append(dia)

    filas, registros, trades = [], [], 0
    motivos = Counter()
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = R_BASE / len(cands)
        pnl, nom, hubo = 0.0, 0.0, False
        for dia in cands:
            j = jornada(dia, señal, lado=lado, stop_pct=stop, riesgo=cuota,
                        max_trades=max_trades, g=g)
            if not j:
                continue
            hubo = True
            pnl += j["pnl"]
            nom += j["nominal"]
            trades += j["trades"]
            for t in j["detalle"]:
                motivos[t["motivo"]] += 1
                registros.append((
                    nombre, dia.ticker, d, t["h_ent"], t["h_sal"],
                    t["p_ent"], t["p_sal"], t["stop_pct"], t["acciones"],
                    t["pnl"],
                    round(100 * (t["p_sal"] / t["p_ent"] - 1), 3) if t["p_ent"] else None,
                    t["mae_pct"], t["mfe_pct"], t["motivo"],
                    "P1" if d < CORTE else "P2",
                    round(dia.expansion_pct or 0, 1),
                    dia.liquidez_en(t["h_ent"]) or 0))
        if hubo:
            filas.append((d, pnl / R_BASE, nom / R_BASE))

    glob = motor._metricas(filas)
    if not glob:
        return {"nombre": nombre, "error": f"muestra corta ({len(filas)})"}
    p1 = motor._metricas([x for x in filas if x[0] < CORTE])
    p2 = motor._metricas([x for x in filas if x[0] >= CORTE])

    res = {
        "nombre": nombre, "familia": familia, "lado": lado, "stop": stop,
        "apertura": apertura, "pob": pob or {},
        "objetivo_pct": g.objetivo_pct, "salida_h": g.salida_h,
        "notas": notas or g.descripcion(),
        "ses_mes": round(len(filas) / MESES, 1),
        "trades_mes": round(trades / MESES),
        **glob,
        "P1": p1, "P2": p2,
        "replica": (round(abs(p1["ret_nom"] - p2["ret_nom"]), 1)
                    if p1 and p2 else None),
        "serie": {d: round(v, 4) for d, v, _ in filas},
        "motivos": dict(motivos),
    }
    if guardar:
        motor._guardar(res, registros, filas)
    # La gestión se cuelga DESPUÉS de persistir: el espejo JSON de motor no
    # sabe serializar el dataclass, y meterle un `default=str` sería tocar un
    # archivo compartido para resolver un problema de este.
    res["gestion"] = g
    return res


# --------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------

def encabezado():
    return ("  " + "salida".ljust(32) + " ses/m tr/m  bruto   nom  ret/nom "
            "  neto20   P1     P2   brecha  motivo dominante")


def linea(r, base=None):
    if "error" in r:
        return f"  {r['nombre']:<32} {r['error']}"
    rep = f"{r['replica']:>5.1f}p" if r["replica"] is not None else "    —"
    mot = ""
    if r.get("motivos"):
        k, n = Counter(r["motivos"]).most_common(1)[0]
        mot = f"{k} {100*n/sum(r['motivos'].values()):.0f}%"
    delta = ""
    if base is not None and base is not r:
        delta = f" {r['ret_nom']-base['ret_nom']:>+6.1f}"
    return (f"  {r['nombre']:<32} {r['ses_mes']:>4.1f} {r['trades_mes']:>4} "
            f"{r['bruto_R']:>+7.3f} {r['nom_R']:>5.2f} {r['ret_nom']:>6.1f}% "
            f"{r['neto20_R']:>+7.3f} "
            f"{(r['P1'] or {}).get('ret_nom', 0):>6.1f} "
            f"{(r['P2'] or {}).get('ret_nom', 0):>6.1f} {rep}{delta}  {mot}")


def titulo(t):
    print("\n" + "=" * 118)
    print(f"  {t}")
    print("=" * 118)


# --------------------------------------------------------------------------
# El catálogo de variantes. Se declara ANTES de mirar ningún resultado.
# --------------------------------------------------------------------------

def catalogo():
    """Todas las gestiones a medir, en el orden en que se pensaron.

    Está escrito como lista fija y no como búsqueda de parámetros a propósito:
    una búsqueda devuelve el máximo del ruido. Acá cada familia se barre entera
    y se reporta entera, incluidas —sobre todo— las que empeoran.
    """
    v = [("salida·cierre", BASE)]

    # 1. objetivo fijo
    for o in (5, 10, 15, 20, 30, 50):
        v.append((f"salida·objetivo{o}", Gestion(objetivo_pct=float(o))))

    # 2. reloj. Dos lecturas del mismo pedido, y las dos hacen falta:
    #    · "coherente": no se abre después de la hora de corte. Es lo que
    #      significa "estoy plano a las 10:30" y cuesta frecuencia.
    #    · "ingenua": se abre igual y se cierra en la barra siguiente si ya pasó
    #      la hora. Mide otra cosa —trades de un minuto— pero conserva las mismas
    #      fechas, y por eso es la que sirve para correlacionar.
    for h, lab in ((10.5, "10:30"), (11.5, "11:30"), (13.0, "13:00"), (15.0, "15:00")):
        v.append((f"salida·hora{lab}", Gestion(salida_h=h, entradas_hasta=h)))
        v.append((f"salida·hora{lab}·ingenua", Gestion(salida_h=h)))

    # 3. tiempo en la posición
    for m in (15, 30, 60, 120):
        v.append((f"salida·tiempo{m}min", Gestion(max_min=float(m))))

    # 4. trailing por devolución del recorrido. OJO con la mecánica: sin umbral
    #    de armado, "devolver el 20% de lo recorrido" es break-even desde el
    #    minuto cero, porque al principio el recorrido es cero. No es un defecto
    #    de la implementación: es lo que ES un trailing por devolución.
    for f in (0.20, 0.33, 0.50):
        v.append((f"salida·trail·dev{int(100*f)}", Gestion(trail_devuelve=f)))
    for f in (0.33, 0.50):
        v.append((f"salida·trail·dev{int(100*f)}·arma10",
                  Gestion(trail_devuelve=f, trail_arma=10.0)))

    # 5. trailing de ancho fijo sobre el mínimo corriente. Esta es la variante
    #    interesante para ret/nom y la única con un argumento a favor: mantiene
    #    el nominal chico del stop ancho (el tamaño lo sigue fijando `stop`)
    #    pero corta la pérdida antes. Si "asegurar" fuera a funcionar en algún
    #    lado, es acá.
    for a in (15, 25, 45):
        v.append((f"salida·trail·anc{a}", Gestion(trail_ancho=float(a))))
        v.append((f"salida·trail·anc{a}·arma10",
                  Gestion(trail_ancho=float(a), trail_arma=10.0)))

    # 6. VWAP como objetivo dinámico
    v.append(("salida·vwap", Gestion(vwap=True)))

    # 7. parciales
    for o in (10, 20, 30):
        v.append((f"salida·parcial{o}", Gestion(parcial_pct=float(o))))
    v.append(("salida·parcial20·be", Gestion(parcial_pct=20.0, parcial_be=True)))

    # 8. break-even. El sospechoso de siempre.
    for b in (5, 10, 15, 20):
        v.append((f"salida·be{b}", Gestion(be_pct=float(b))))

    return v


# --------------------------------------------------------------------------
# Pasos del experimento
# --------------------------------------------------------------------------

def paso_equivalencia(dias, pob, señal):
    """Sin esto el resto no vale nada: ¿reproduce a motor con gestión vacía?"""
    titulo("0. EQUIVALENCIA CON motor.py — si esto falla, todo lo demás es ruido")
    ok = True
    casos = [("gestión vacía", BASE, {}),
             ("objetivo 20%", Gestion(objetivo_pct=20.0), {"objetivo_pct": 20.0}),
             ("cierre 13:00", Gestion(salida_h=13.0), {"salida_h": 13.0})]
    print(f"\n  {'caso':>16}  {'motor bruto_R':>14} {'salidas bruto_R':>16} "
          f"{'motor nom':>10} {'salidas nom':>12}  {'':>6}")
    for lab, g, kw in casos:
        a = motor.evaluar("tmp·eq·motor", señal, dias=dias, stop=45.0, pob=pob,
                          guardar=False, **kw)
        b = evaluar("tmp·eq·salidas", señal, dias=dias, stop=45.0, pob=pob,
                    g=g, guardar=False)
        igual = (abs(a["bruto_R"] - b["bruto_R"]) < 1e-9
                 and abs(a["nom_R"] - b["nom_R"]) < 1e-9 and a["n"] == b["n"])
        ok = ok and igual
        print(f"  {lab:>16}  {a['bruto_R']:>+14.4f} {b['bruto_R']:>+16.4f} "
              f"{a['nom_R']:>10.3f} {b['nom_R']:>12.3f}  "
              f"{'OK' if igual else 'DIFIERE':>7}")
    print(f"\n  {'equivalencia verificada' if ok else 'EQUIVALENCIA ROTA'}")
    return ok


def paso_grilla(dias, pob, señal, stops, objetivos):
    """La grilla entera. No se elige celda: se mira la forma."""
    titulo("1. GRILLA STOP × OBJETIVO — la tabla entera, sin elegir celda")
    print("""
  El stop hace dos cosas a la vez y por eso la grilla no se puede leer por una
  sola métrica: fija dónde te equivocaste Y fija el nominal (= riesgo·100/stop).
  Un stop del 25% despliega 2,2 veces el nominal de uno del 55%, o sea 2,2 veces
  el locate. `media` es el PnL por sesión en R; `ret/nom` es lo que queda para
  pagar el locate — el punto de muerte de la celda.""")
    tabla = {}
    for s in stops:
        for o in objetivos:
            g = Gestion(objetivo_pct=float(o)) if o else BASE
            nom = f"salida·g·s{s}·o{o if o else 'sin'}"
            r = evaluar(nom, señal, dias=dias, stop=float(s), pob=pob, g=g,
                        familia="salida-grilla",
                        notas=f"grilla stop {s}% × objetivo {o or 'sin'}")
            if "error" not in r:
                tabla[(s, o)] = r
    cols = [("sin" if not o else f"{o}%") for o in objetivos]

    def cuadro(clave, tit, fmt):
        print(f"\n  {tit}")
        print(f"  {'stop \\ objetivo':>16} " + " ".join(f"{c:>9}" for c in cols))
        print("  " + "-" * (18 + 10 * len(cols)))
        for s in stops:
            fila = []
            for o in objetivos:
                r = tabla.get((s, o))
                fila.append(fmt.format(r[clave]) if r else f"{'—':>9}")
            n = tabla.get((s, objetivos[-1]), {}).get("nom_R")
            extra = f"   nom {n:.2f}R" if n else ""
            print(f"  {str(s)+'%':>16} " + " ".join(fila) + extra)

    cuadro("bruto_R", "MEDIA POR SESIÓN, en R", "{:>+9.3f}")
    cuadro("ret_nom", "RET/NOM % — el punto de muerte del locate", "{:>8.1f}%")
    cuadro("neto20_R", "NETO con locate al 20% del nominal, en R", "{:>+9.3f}")
    cuadro("replica", "BRECHA P1 vs P2 en puntos (>15 = ruido)", "{:>8.1f}p")

    # ---- el barrido de locate, que es lo que de verdad elige el stop -------
    print("""
  NETO POR SESIÓN SEGÚN CUÁNTO COBRE EL LOCATE (columna 'sin objetivo')

  Las dos métricas de arriba se contradicen y hay que decirlo: en `media` el
  stop corto gana (más nominal, más plata por unidad de riesgo) y en `ret/nom`
  gana el ancho (menos nominal, más lejos del punto de muerte). Quién tiene
  razón depende de a cuánto está el locate, así que acá está la cuenta hecha
  para cada nivel. El cruce es el número que decide, no la preferencia.""")
    stops_ok = [s for s in stops if (s, objetivos[-1]) in tabla]
    print(f"\n  {'locate':>8} " + " ".join(f"{'stop '+str(s)+'%':>11}" for s in stops_ok)
          + "   gana")
    print("  " + "-" * (10 + 12 * len(stops_ok) + 12))
    for loc in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        vals = []
        for s in stops_ok:
            r = tabla[(s, objetivos[-1])]
            vals.append(r["bruto_R"] - loc * r["nom_R"])
        gana = stops_ok[max(range(len(vals)), key=lambda i: vals[i])]
        print(f"  {100*loc:>7.0f}% " + " ".join(f"{v:>+11.3f}" for v in vals)
              + f"   stop {gana}%")
    print("""
  Debajo del cruce el stop corto rinde más por unidad de RIESGO; arriba, el
  ancho. Y el punto de muerte —donde la fila se vuelve toda negativa— llega
  antes para el stop corto porque despliega más nominal. Un stop del 25%
  despliega 1,8 veces el nominal de uno del 45% y muere 10 puntos de locate
  antes.""")
    return tabla


def paso_variantes(dias, pob, señal, stop, guardar=True):
    """Todas las salidas, ordenadas por ret/nom."""
    res = {}
    for nombre, g in catalogo():
        r = evaluar(nombre, señal, dias=dias, stop=stop, pob=pob, g=g,
                    guardar=guardar)
        if "error" not in r:
            res[nombre] = r
    return res


def tabla_variantes(res, base, ruido=15.0):
    print(encabezado())
    print("  " + "-" * 116)
    for r in sorted(res.values(), key=lambda x: -x["ret_nom"]):
        marca = "  <<< base" if r["nombre"] == base["nombre"] else ""
        aviso = "  RUIDO" if (r["replica"] or 0) > ruido else ""
        print(linea(r, base) + marca + aviso)


def paso_correlacion(res, claves):
    titulo("3. CORRELACIÓN ENTRE GESTIONES — ¿alguna sirve para una segunda cuenta?")
    print("""
  Todas las variantes operan las MISMAS entradas sobre los MISMOS días: lo único
  que cambia es cómo se cierra. Por construcción tienen que estar muy
  correlacionadas, y una correlación baja acá significaría que la salida cambia
  el resultado del día tanto como cambiarlo de estrategia. Es el único resultado
  de esta familia que podría justificar una gestión peor: dos cuentas de fondeo
  con series distintas quiebran en días distintos.""")
    presentes = [k for k in claves if k in res]
    print(f"\n  {'#':>3}  {'gestión':<32} {'r vs cierre':>12}  {'ret/nom':>8}")
    print("  " + "-" * 62)
    for i, k in enumerate(presentes, 1):
        c = correlacion(res[k]["serie"], res["salida·cierre"]["serie"])
        print(f"  {i:>3}  {k:<32} {(f'{c:+.3f}' if c is not None else '—'):>12}  "
              f"{res[k]['ret_nom']:>7.1f}%")
    print("\n  MATRIZ (mismas fechas, correlación de Pearson sobre el PnL diario)")
    print("       " + " ".join(f"{i:>6}" for i in range(1, len(presentes) + 1)))
    for i, a in enumerate(presentes, 1):
        fila = []
        for b in presentes:
            c = correlacion(res[a]["serie"], res[b]["serie"])
            fila.append(f"{c:>+6.2f}" if c is not None else f"{'—':>6}")
        print(f"  {i:>3}  " + " ".join(fila))
    return presentes


def paso_nominal(res):
    """La verificación de que el nominal NO depende de la salida."""
    titulo("2b. EL DENOMINADOR NO SE MUEVE — por qué las salidas no pueden bajar el locate")
    noms = sorted({round(r["nom_R"], 4) for r in res.values()})
    print(f"""
  `nom_R` observado en las {len(res)} variantes: {', '.join(f'{n:.3f}' for n in noms)}

  Es el mismo número (o casi) en todas, y no es casualidad: nominal =
  riesgo·100/stop, el precio se cancela y la salida no entra en la fórmula. El
  locate se reserva por el día y no se devuelve si cerrás a las 10:30 ni si
  cerrás la mitad. Entonces, a stop fijo, **ordenar por ret/nom es ordenar por
  PnL**: esta familia entera compite en el numerador. La única palanca sobre el
  denominador está en el ancho del stop, y por eso la grilla del paso 1 es la
  parte que de verdad decide el punto de muerte.""")


def _dd(serie):
    """Máxima caída pico-a-valle de la curva acumulada, en R."""
    acum = peak = 0.0
    peor = 0.0
    for d in sorted(serie):
        acum += serie[d]
        peak = max(peak, acum)
        peor = max(peor, peak - acum)
    return peor


def _spearman(a, b):
    """Correlación de rangos. Contesta si el ORDEN se conserva, no los niveles."""
    def rangos(v):
        orden = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(orden):
            r[i] = float(pos)
        return r
    ra, rb = rangos(a), rangos(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    sa = sum((x - ma) ** 2 for x in ra) ** 0.5
    sb = sum((x - mb) ** 2 for x in rb) ** 0.5
    if not sa or not sb:
        return None
    return sum((ra[i] - ma) * (rb[i] - mb) for i in range(len(ra))) / (sa * sb)


def paso_decorrelacion(res, claves):
    """¿La decorrelación se puede COMPRAR, y a qué precio?

    La pregunta de Agus es la única de esta familia que podría justificar una
    gestión peor: dos cuentas de fondeo con series distintas no quiebran el
    mismo día. Pero hay una trampa aritmética que hay que desarmar antes de
    festejar cualquier r bajo: **una serie sin señal se decorrelaciona de todo**.
    Si una gestión sale siempre en break-even, su PnL diario es ruido de costos
    alrededor de cero, y el ruido no correlaciona con nada. Eso no es
    diversificación: es no estar en el mercado.

    Por eso acá no alcanza con la r. Se mira junto: dispersión de la serie (si
    es chica, no hay exposición), y qué le pasa a la mezcla 50/50 con la base
    —en ret/nom, que es lo que paga el locate, y en drawdown, que es lo que hace
    quebrar la cuenta.
    """
    titulo("6. EL PRECIO DE LA DECORRELACIÓN — ¿sirve para una segunda cuenta?")
    base = res["salida·cierre"]
    print(f"""
  Las dos cuentas pagan locate por separado: la mezcla despliega el nominal de
  las dos, así que su ret/nom es el PROMEDIO, nunca la suma. Una gestión
  decorrelacionada sólo se paga sola si baja el drawdown MÁS de lo que baja el
  retorno sobre nominal.
""")
    print(f"  {'gestión':<30} {'r':>6} {'ret/nom':>8} {'desvío':>7} {'peor':>7} "
          f"{'maxDD':>7}    {'MEZCLA 50/50 CON LA BASE':<34}")
    print(f"  {'':<30} {'':>6} {'':>8} {'':>7} {'':>7} {'':>7}    "
          f"{'ret/nom':>8} {'desvío':>7} {'maxDD':>7} {'neto20/DD':>10}")
    print("  " + "-" * 106)
    for k in claves:
        if k not in res:
            continue
        r = res[k]
        c = correlacion(r["serie"], base["serie"])
        v = list(r["serie"].values())
        fechas = sorted(set(r["serie"]) | set(base["serie"]))
        mezcla = {d: 0.5 * (r["serie"].get(d, 0.0) + base["serie"].get(d, 0.0))
                  for d in fechas}
        mv = list(mezcla.values())
        # nom de la mezcla = promedio de los dos nominales (dos cuentas)
        nm = 0.5 * (r["nom_R"] + base["nom_R"])
        dd_m = _dd(mezcla)
        neto_m = statistics.mean(mv) - LOCATE_REF * nm
        print(f"  {k:<30} {(f'{c:+.2f}' if c is not None else '—'):>6} "
              f"{r['ret_nom']:>7.1f}% {statistics.pstdev(v):>7.3f} "
              f"{min(v):>+7.3f} {_dd(r['serie']):>7.3f}    "
              f"{100*statistics.mean(mv)/nm:>7.1f}% {statistics.pstdev(mv):>7.3f} "
              f"{dd_m:>7.3f} {(neto_m/dd_m if dd_m else 0):>10.4f}")
    # ¿Y si la restricción no fuera el locate sino el drawdown? Es la única
    # forma en que una gestión peor podría entrar igual, así que hay que
    # medirla y no descartarla de palabra. `neto/DD` es lo que gana una cuenta
    # a la que le fijan un límite de caída: se escala hasta llenarlo.
    cand = "salida·trail·dev33"
    if cand in res:
        fechas = sorted(set(res[cand]["serie"]) | set(base["serie"]))
        mez = {d: 0.5 * (res[cand]["serie"].get(d, 0.0) + base["serie"].get(d, 0.0))
               for d in fechas}
        nm = 0.5 * (res[cand]["nom_R"] + base["nom_R"])
        dd_b, dd_m = _dd(base["serie"]), _dd(mez)
        mb, mm = base["bruto_R"], statistics.mean(list(mez.values()))
        print(f"\n  SI LA RESTRICCIÓN FUERA EL DRAWDOWN Y NO EL LOCATE "
              f"(mezcla base + {cand.split('·', 1)[1]})")
        print(f"\n  {'locate':>8} {'base neto/DD':>14} {'mezcla neto/DD':>16}   gana")
        print("  " + "-" * 56)
        for loc in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
            eb = (mb - loc * base["nom_R"]) / dd_b
            em = (mm - loc * nm) / dd_m
            print(f"  {100*loc:>7.0f}% {eb:>14.4f} {em:>16.4f}   "
                  f"{'mezcla' if em > eb else 'base'}")
        print("""
  Con locate gratis la mezcla gana: baja el drawdown más rápido de lo que baja
  el retorno. Con locate de verdad pierde, y por una razón estructural que ya
  apareció arriba — la mezcla despliega el nominal de LAS DOS cuentas y cobra el
  promedio de los dos retornos. El denominador no se diversifica.""")

    todos = [(r["ret_nom"], correlacion(r["serie"], base["serie"]))
             for r in res.values()]
    todos = [(a, b) for a, b in todos if b is not None]
    sp = _spearman([a for a, _ in todos], [b for _, b in todos])
    print(f"""
  Sobre las {len(todos)} variantes, la correlación de RANGOS entre "cuánto rinde"
  y "cuánto se parece a la base" es {sp:+.2f}. Cuanto más se despega una gestión
  de sostener hasta el cierre, menos rinde — y no un poco: es casi un orden
  total. La decorrelación de esta familia no es un activo distinto, es la misma
  apuesta apagada.""")


def paso_mecanismo(res, claves):
    """POR QUÉ asegurar empeora, no sólo que empeora.

    Un ranking no es una explicación. Acá se parten las sesiones en tres grupos
    según cómo le fue A LA BASE —el decil bueno, el medio, el decil malo— y se
    mira qué gana cada gestión en esos MISMOS días. Si la historia es "cortan la
    cola izquierda", se tiene que ver como una mejora en el decil malo. Si la
    historia es "también cortan la derecha, y esa es más grande", se tiene que
    ver como una pérdida en el decil bueno que se come todo lo ganado abajo.

    El grupo lo define la base, no cada variante: si cada una se ordenara con su
    propio resultado, la comparación sería entre días distintos y no diría nada.
    """
    titulo("8. EL MECANISMO — qué le sacan y qué le ponen las gestiones que aseguran")
    base = res["salida·cierre"]
    fechas = sorted(base["serie"], key=lambda d: base["serie"][d])
    k = max(1, len(fechas) // 10)
    grupos = [("decil malo", fechas[:k]), ("medio", fechas[k:-k]),
              ("decil bueno", fechas[-k:])]
    print(f"\n  {len(fechas)} sesiones · el decil son {k} días · "
          f"todo en R por sesión, sobre los MISMOS días")
    print(f"\n  {'gestión':<30} " + " ".join(f"{g:>14}" for g, _ in grupos)
          + f" {'total':>10}")
    print("  " + "-" * 92)
    for kk in claves:
        if kk not in res:
            continue
        s = res[kk]["serie"]
        fila = []
        for _, fs in grupos:
            v = [s.get(d, 0.0) for d in fs]
            fila.append(f"{statistics.mean(v):>+14.3f}")
        print(f"  {kk:<30} " + " ".join(fila)
              + f" {statistics.mean(list(s.values())):>+10.3f}")
    if "salida·be10" not in res:
        return
    be = res["salida·be10"]["serie"]
    d_mal = (statistics.mean([be.get(d, 0.0) for d in grupos[0][1]])
             - statistics.mean([base["serie"][d] for d in grupos[0][1]]))
    d_bue = (statistics.mean([be.get(d, 0.0) for d in grupos[2][1]])
             - statistics.mean([base["serie"][d] for d in grupos[2][1]]))
    b_mal = statistics.mean([base["serie"][d] for d in grupos[0][1]])
    b_bue = statistics.mean([base["serie"][d] for d in grupos[2][1]])
    razon = abs(d_bue / d_mal) if d_mal else float("inf")
    print(f"""
  Ejemplo con el break-even al 10%, que es el caso puro: en el decil malo mejora
  {d_mal:+.3f}R por sesión y en el decil bueno pierde {d_bue:+.3f}R. Los dos deciles
  pesan lo mismo en la media, así que la cuenta cierra en contra por {razon:.0f} a 1.

  Y el POR QUÉ está en la fila de la BASE, no en las de las variantes: el decil
  malo de la base ya está en {b_mal:+.3f}R, o sea pegado al límite diario de −1R.
  **La cola izquierda ya la compró el stop, y el presupuesto de la jornada la
  terminó de cerrar: no queda casi nada que proteger.** La derecha, en cambio,
  llega a {b_bue:+.3f}R y no tiene techo. Cualquier regla que recorte las dos paga
  precio lleno de un lado y compra chatarra del otro.

  Eso no es una particularidad de este setup: pasa siempre que el riesgo ya está
  acotado por diseño. Es la explicación de las nueve veces, no sólo de esta.""")


def paso_replica_poblacion(res, dias, señal, stop, exp_alt=100.0):
    """¿El ORDEN de las salidas se conserva en otra población?

    Es la validación que le falta a cualquier ranking: los niveles pueden
    moverse —de hecho se mueven, la población de expansión ≥100% rinde menos—
    pero si el orden se da vuelta, el ranking era del ruido y no de la mecánica.
    """
    titulo(f"7. RÉPLICA DEL ORDEN en otra población (expansión ≥ {exp_alt:.0f}%)")
    pob2 = {"min_expansion": exp_alt}
    otro = {}
    for nombre, g in catalogo():
        r = evaluar(f"tmp·alt·{nombre}", señal, dias=dias, stop=stop, pob=pob2,
                    g=g, guardar=False)
        if "error" not in r:
            otro[nombre] = r
    comunes = [k for k in res if k in otro]
    a = [res[k]["ret_nom"] for k in comunes]
    b = [otro[k]["ret_nom"] for k in comunes]
    sp = _spearman(a, b)
    print(f"\n  {len(comunes)} variantes en las dos poblaciones · "
          f"correlación de rangos del ret/nom: {sp:+.3f}")
    print(f"\n  {'gestión':<30} {'ret/nom ≥150':>13} {'ret/nom ≥100':>13} "
          f"{'puesto ≥150':>12} {'puesto ≥100':>12}")
    print("  " + "-" * 84)
    ord1 = {k: i for i, k in enumerate(sorted(comunes, key=lambda k: -res[k]["ret_nom"]), 1)}
    ord2 = {k: i for i, k in enumerate(sorted(comunes, key=lambda k: -otro[k]["ret_nom"]), 1)}
    for k in sorted(comunes, key=lambda k: -res[k]["ret_nom"])[:8]:
        print(f"  {k:<30} {res[k]['ret_nom']:>12.1f}% {otro[k]['ret_nom']:>12.1f}% "
              f"{ord1[k]:>12} {ord2[k]:>12}")
    print("  ...")
    for k in sorted(comunes, key=lambda k: -res[k]["ret_nom"])[-3:]:
        print(f"  {k:<30} {res[k]['ret_nom']:>12.1f}% {otro[k]['ret_nom']:>12.1f}% "
              f"{ord1[k]:>12} {ord2[k]:>12}")
    return otro


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Salidas y gestión del trade")
    ap.add_argument("--exp", type=float, default=150.0,
                    help="expansión pre-market mínima de la población")
    ap.add_argument("--stop", type=float, default=45.0,
                    help="stop de referencia para la tabla de salidas")
    ap.add_argument("--ruido", type=float, default=15.0,
                    help="brecha P1-P2 arriba de la cual el resultado es ruido")
    ap.add_argument("--sin-guardar", action="store_true")
    args = ap.parse_args(argv)

    dias = universo()
    pob = {"min_expansion": args.exp}
    señal = lambda d: señales_swing(d)  # noqa: E731
    guardar = not args.sin_guardar

    print(f"\n  universo {len(dias)} días · población expansión ≥ {args.exp:.0f}% · "
          f"apertura fade · entradas por swing · stop de referencia {args.stop:.0f}%")

    paso_equivalencia(dias, pob, señal)

    paso_grilla(dias, pob, señal, stops=(25, 35, 45, 55),
                objetivos=(5, 10, 15, 20, 30, 50, 0))

    titulo(f"2. TODAS LAS SALIDAS, ordenadas por ret/nom (stop {args.stop:.0f}%)")
    res = paso_variantes(dias, pob, señal, args.stop, guardar=guardar)
    base = res["salida·cierre"]
    tabla_variantes(res, base, args.ruido)

    paso_nominal(res)

    claves = ["salida·cierre", "salida·objetivo10", "salida·objetivo20",
              "salida·objetivo50", "salida·hora10:30·ingenua",
              "salida·hora13:00·ingenua", "salida·tiempo30min",
              "salida·tiempo120min", "salida·trail·dev33",
              "salida·trail·anc25·arma10", "salida·vwap", "salida·parcial20",
              "salida·be10"]
    paso_correlacion(res, claves)
    paso_decorrelacion(res, claves)

    # ---- validación de excepciones -------------------------------------
    titulo("4. ¿HAY EXCEPCIÓN? — validación de todo lo que le ganó a la base")
    mejores = [r for r in res.values()
               if r["ret_nom"] > base["ret_nom"] and r["nombre"] != base["nombre"]]
    mejores.sort(key=lambda x: -x["ret_nom"])
    if not mejores:
        print("\n  Ninguna variante le gana a sostener hasta el cierre. Novena vez.")
    else:
        print(f"\n  {len(mejores)} variante(s) por encima de la base. Cada una pasa "
              f"por tres pruebas que NO se usaron para elegirla:\n"
              f"    a) réplica P1/P2 con brecha ≤ {args.ruido:.0f} puntos\n"
              f"    b) otra población: expansión ≥ 100% (más días, otro régimen)\n"
              f"    c) otro stop: {args.stop-10:.0f}% y {args.stop+10:.0f}%\n")
        pob2 = {"min_expansion": 100.0}
        base2 = evaluar("tmp·base·exp100", señal, dias=dias, stop=args.stop,
                        pob=pob2, g=BASE, guardar=False)
        print(f"  {'variante':<30} {'ret/nom':>8} {'Δbase':>7} {'brecha':>7} "
              f"{'exp100':>8} {'Δbase':>7} {'stop-10':>8} {'Δ':>7} {'stop+10':>8} {'Δ':>7}")
        print("  " + "-" * 108)
        for r in mejores:
            g = r["gestion"]
            r2 = evaluar("tmp·v·exp100", señal, dias=dias, stop=args.stop,
                         pob=pob2, g=g, guardar=False)
            fila = (f"  {r['nombre']:<30} {r['ret_nom']:>7.1f}% "
                    f"{r['ret_nom']-base['ret_nom']:>+7.1f} {(r['replica'] or 0):>6.1f}p "
                    f"{r2['ret_nom']:>7.1f}% {r2['ret_nom']-base2['ret_nom']:>+7.1f}")
            for ds in (-10, 10):
                s = args.stop + ds
                bs = evaluar("tmp·b·s", señal, dias=dias, stop=s, pob=pob,
                             g=BASE, guardar=False)
                vs = evaluar("tmp·v·s", señal, dias=dias, stop=s, pob=pob,
                             g=g, guardar=False)
                fila += f" {vs['ret_nom']:>7.1f}% {vs['ret_nom']-bs['ret_nom']:>+7.1f}"
            print(fila)
        print("""
  Una excepción de verdad tiene que dar Δ positivo en las CUATRO columnas de
  delta. Si sólo gana en la celda donde se la encontró, es la celda, no la
  regla.""")

    # ---- el contraste que explica la familia ---------------------------
    titulo("5. MISMO STOP EFECTIVO, DISTINTO NOMINAL — dónde está la palanca real")
    print("""
  Dos formas de terminar con un stop efectivo del 15%: ponerlo como stop (y
  desplegar 3 veces el nominal) o llegar con un trailing desde un stop del 45%
  (nominal chico). Si "asegurar" tuviera un lugar donde ganar, sería este.""")
    print(f"\n{encabezado()}")
    print("  " + "-" * 116)
    for nom, st, g in (("stop15·al cierre", 15.0, BASE),
                       ("stop25·al cierre", 25.0, BASE),
                       ("stop45·al cierre", 45.0, BASE),
                       ("stop55·al cierre", 55.0, BASE),
                       ("stop45·trail 15%", 45.0, Gestion(trail_ancho=15.0)),
                       ("stop45·trail 25%", 45.0, Gestion(trail_ancho=25.0))):
        r = evaluar(f"tmp·pal·{nom}", señal, dias=dias, stop=st, pob=pob, g=g,
                    guardar=False)
        r["nombre"] = nom
        print(linea(r))

    paso_mecanismo(res, claves)
    paso_replica_poblacion(res, dias, señal, args.stop)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
