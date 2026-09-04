#!/usr/bin/env python3
"""La cuenta propia en TradeZero: si hubiéramos depositado el 2 de enero, ¿dónde estaríamos?

QUE SIMULA. Una sola cuenta con plata nuestra, día por día, con la estrategia
de `OPERATIVA.md` en modo **propia**: todos los papeles del día, sin corte, sin
tope. No hay evaluación que pasar, ni consistencia, ni días mínimos, ni reparto.
Lo que hay es lo que cobra el broker, que en small caps es lo que decide:

  · COMISION. $0 si la orden es de 100+ acciones a más de $1; si no, 0,5¢ por
    acción con MINIMO $0,49 por orden. Nuestros tramos son de 3 a 23 acciones,
    así que casi todos pagan el mínimo. Se cobra por ORDEN, no por tramo: los
    tramos de un papel que cierran en la misma barra por el mismo motivo —el
    cierre de las 16:00— son una sola orden. Los stops disparan cada uno por su
    cuenta y son órdenes distintas.
  · LOCATE. Por acción, una vez por papel por día, sobre las acciones del pico
    de exposición y con un pedido mínimo de 100 (supuesto de la industria, no
    confirmado con TradeZero). El precio sale de lo que se ANOTA en `/vivo`,
    columna `loc`, para ese papel y ese día; si no hay anotación se usa el
    supuesto de la página. Cuántos días usaron un precio real y cuántos el
    supuesto se informa, porque hasta que la mayoría sea real esto es una
    hipótesis con forma de número.
  · PLATAFORMA. $0 con TZ1 web; ZeroPro son $59/mes. Se cobra el primer día
    operado de cada mes.
  · PODER DE COMPRA. 4:1 con menos de $2.500 de equity, 6:1 desde $2.500. Si el
    nominal que la estrategia necesita ese día supera el poder de compra, el
    día se opera con el riesgo RECORTADO en proporción y se marca. Es lo que
    hace honesta la pregunta "¿y si opero $75 con $500?": la respuesta no es
    "gana menos", es "no te dejan".

CUANDO SE PARA. Un broker no te liquida por perder tu plata; te quedás sin
poder de compra y listo. Lo que corta acá es un stop-out PERSONAL: si la
equity cae por debajo de una fracción del depósito, se deja de operar y se
revisa. Es una regla nuestra y está a la vista como parámetro.

EL DRAWDOWN se mide intradía y trepando —equity marcada a mercado barra a
barra, contra el pico histórico—, igual que en `cuentas.py`. No porque una prop
lo exija, sino porque es lo que uno ve en la pantalla a las 11:40 y lo que
decide si aguanta la posición o no.

    python propia.py
    python propia.py --deposito 2000 --riesgo 75
    python propia.py --locate 0.10          # el supuesto para los días sin anotación
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")

import config
from chavineta import clasificar_apertura as _cl
from cuentas import curva_intradia, drawdown
from dias import CIERRE_RTH
from motor import COSTO_ACCION, jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# --- la estrategia, modo propia (OPERATIVA.md §0) ---------------------------
PISO, STOP, MAXT, DESDE = 2.05, 45.0, 40, 10.0

# --- TradeZero International, leído en tradezero.co el 2026-09-03 -----------
COMISION_ACC = 0.005            # 0,5¢ por acción...
COMISION_MIN = 0.49             # ...con mínimo por orden
ORDEN_GRATIS_ACC = 100          # 100+ acciones y más de $1: $0
ORDEN_GRATIS_PRECIO = 1.0
APALANCAMIENTO = ((2_500.0, 6.0), (0.0, 4.0))   # desde $2.500 6:1, si no 4:1
LOCATE_MIN_ACC = 100.0          # SUPUESTO: pedido mínimo de la industria
LOCATE_SUPUESTO = 0.05          # $/acción cuando no hay anotación en /vivo
PLATAFORMA_MES = 0.0            # TZ1 web. ZeroPro: 59
PARAR_EN = 0.5                  # stop-out personal: fracción del depósito

# Los dos escenarios que se comparan siempre, medidos en `test_bono_2000.py`:
# $20 es lo que aguanta una cuenta de $500 (drawdown ~40% del depósito) y
# $75 la de ~$2.000-2.500. La página los muestra lado a lado porque la
# diferencia entre los dos ES la razón de "con $500 se mide, no se opera".
ESCENARIOS = ((500.0, 20.0), (2_000.0, 75.0))

_POB = None


def _poblacion():
    """El censo, levantado una vez por proceso: es lo que tarda."""
    global _POB
    if _POB is None:
        pob = [d for d in poblacion(universo(), min_ratio_vol=0.0,
                                    min_expansion=0.0, min_dolar=0.0,
                                    max_float=47e6)
               if _cl(d, hasta=10.0) == "reclaim"]
        pob.sort(key=lambda d: (d.d, d.ticker))
        _POB = pob
    return _POB


def sig(d):
    return [i for i in señales_swing(d, desde=DESDE) if (d.bars[i][4] or 0) >= PISO]


def apalancamiento(equity):
    for umbral, veces in APALANCAMIENTO:
        if equity >= umbral:
            return veces
    return APALANCAMIENTO[-1][1]


def orden(acciones, precio):
    """Lo que cobra TradeZero por UNA orden."""
    if acciones >= ORDEN_GRATIS_ACC and precio > ORDEN_GRATIS_PRECIO:
        return 0.0
    return max(COMISION_MIN, acciones * COMISION_ACC)


def ordenes_de(detalle):
    """Las órdenes de un papel en el día: una por entrada, y las salidas
    agrupadas por barra y motivo. Devuelve (cantidad, comisión)."""
    n, com = 0, 0.0
    for t in detalle:
        n += 1
        com += orden(t["acciones"], t["p_ent"])
    salidas = defaultdict(lambda: [0.0, 0.0])
    for t in detalle:
        k = (round(t["h_sal"], 4) if t["h_sal"] is not None else None, t["motivo"])
        salidas[k][0] += t["acciones"]
        salidas[k][1] = t["p_sal"] or 0.0
    for acc, p in salidas.values():
        n += 1
        com += orden(acc, p)
    return n, com


def pico_acciones(detalle):
    """Las acciones simultáneas máximas: es lo que hay que localizar."""
    ev = []
    for t in detalle:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)
    return pico


def locates_anotados():
    """(fecha, ticker) -> $/acción, de lo que se cargó en /vivo."""
    ruta = config.data_dir() / "locates.jsonl"
    out = {}
    if not ruta.exists():
        return out
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(linea)
            out[(r["f"], r["tk"])] = float(r["locate"])
        except Exception:
            continue
    return out


def papel(dia, riesgo, locate_acc, real):
    """Un papel un día: lo que dejó y lo que costó, con el detalle que la
    página necesita. `locate_acc` es el precio del locate por acción y
    `real` si salió de una anotación o del supuesto."""
    j = jornada(dia, sig, lado="short", stop_pct=STOP, riesgo=riesgo,
                max_trades=MAXT, corte_h=None)
    if not j:
        return None
    det = j["detalle"]
    # El motor cobra $0,04/acción de fricción; se revierte y se cobra lo real.
    bruto = j["pnl"] + sum(t["acciones"] * COSTO_ACCION for t in det)
    n_ord, comision = ordenes_de(det)
    pico = pico_acciones(det)
    p0 = min(det, key=lambda t: t["h_ent"])["p_ent"]
    loc_acc = max(pico, LOCATE_MIN_ACC)
    locate = loc_acc * locate_acc
    curva = curva_intradia(dia, det)
    motivos = defaultdict(int)
    for t in det:
        motivos[t["motivo"]] += 1
    return {
        "tk": dia.ticker, "bruto": round(bruto, 2), "comision": round(comision, 2),
        "locate": round(locate, 2), "locate_acc": locate_acc, "locate_real": real,
        "locate_acciones": round(loc_acc), "neto": round(bruto - comision - locate, 2),
        "tramos": len(det), "ordenes": n_ord, "motivos": dict(motivos),
        "pico_acciones": round(pico, 1), "nominal": round(pico * p0, 2),
        "precio": round(p0, 2), "dd": round(drawdown([e for _, e in curva]), 2),
        "curva": curva,
    }


class Cuenta:
    """La cuenta propia: equity, pico, y lo que se fue en costos."""

    def __init__(self, deposito, parar_en, plataforma_mes):
        self.deposito = deposito
        self.equity = deposito
        self.pico = deposito
        self.parar_en = parar_en
        self.plataforma_mes = plataforma_mes
        self.estado = "operando"
        self.bruto = self.comision = self.locates = self.plataforma = 0.0
        self.peor_dd = 0.0          # intradía, trepando, en $
        self.peor_dia = 0.0
        self.historia = []
        self._mes_cobrado = None

    def dia(self, fecha, papeles):
        """Un día: el locate se paga a la mañana, la equity se marca barra a
        barra sumando las curvas de todos los papeles, y al cierre se cobran
        las comisiones. `papeles` ya viene recortado al poder de compra."""
        if self.estado != "operando":
            return
        base = self.equity
        plataforma = 0.0
        if self.plataforma_mes and self._mes_cobrado != fecha[:7]:
            plataforma = self.plataforma_mes
            self._mes_cobrado = fecha[:7]
        locates = sum(p["locate"] for p in papeles)
        arranque = base - locates - plataforma

        por_minuto = defaultdict(float)
        for p in papeles:
            for h, eq in p["curva"]:
                por_minuto[h] += eq
        dd_dia = 0.0
        pico_dia = 0.0
        # LA CURVA DE LA CUENTA, barra a barra: es lo que se dibuja. Arranca en
        # el balance menos el locate —que se paga a la mañana— y termina en la
        # equity bruta del cierre; las comisiones se descuentan al cerrar el
        # dia, asi que el primer punto del dia siguiente esta un escalon abajo.
        curva = []
        for h in sorted(por_minuto):
            eq = por_minuto[h]
            pico_dia = max(pico_dia, eq)
            dd_dia = min(dd_dia, eq - pico_dia)
            equity = arranque + eq
            self.pico = max(self.pico, equity)
            self.peor_dd = min(self.peor_dd, equity - self.pico)
            # Despues de las 16:00 no queda nada abierto y la linea es plana:
            # cuatro horas de post-market por dia que no dicen nada.
            if h <= CIERRE_RTH:
                curva.append((h, round(equity, 2)))

        bruto = sum(p["bruto"] for p in papeles)
        comision = sum(p["comision"] for p in papeles)
        neto = bruto - comision - locates - plataforma
        self.equity = base + neto
        self.pico = max(self.pico, self.equity)
        self.peor_dd = min(self.peor_dd, self.equity - self.pico)
        self.peor_dia = min(self.peor_dia, neto)
        self.bruto += bruto
        self.comision += comision
        self.locates += locates
        self.plataforma += plataforma
        parada = self.equity < self.deposito * self.parar_en
        if parada:
            self.estado = "parada"
        self.historia.append({
            "f": fecha, "bruto": round(bruto, 2), "comision": round(comision, 2),
            "locates": round(locates, 2), "plataforma": round(plataforma, 2),
            "neto": round(neto, 2), "dd": round(dd_dia, 2),
            "equity": round(self.equity, 2), "parada": parada,
            "curva": curva,
            "papeles": [{k: v for k, v in p.items() if k != "curva"}
                        for p in papeles],
        })


def _dias(desde, sin_hoy):
    """Los papeles reclaim por fecha, del censo y —si se pide— del feed de hoy."""
    por_fecha = defaultdict(list)
    for d in _poblacion():
        if d.d >= desde:
            por_fecha[d.d].append(d)
    avisos = []
    if not sin_hoy:
        try:
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(
                os.path.abspath(__file__)), "puente"))
            import vivo as _v
            for (tk, f), datos in _v.leer_feed().items():
                if f < desde or f in por_fecha:
                    continue
                dia = _v.armar_dia(tk, f, datos)
                if dia and _cl(dia, hasta=10.0) == "reclaim":
                    por_fecha[f].append(dia)
        except Exception as e:
            avisos.append(f"sin feed en vivo: {e}")
    return por_fecha, avisos


def _correr(por_fecha, *, deposito, riesgo, locate, plataforma, parar_en, anotados):
    c = Cuenta(deposito, parar_en, plataforma)
    recortados = 0
    for f in sorted(por_fecha):
        if c.estado != "operando":
            break
        dias_f = sorted(por_fecha[f], key=lambda d: d.ticker)

        def armar(r):
            out = []
            for d in dias_f:
                la = anotados.get((f, d.ticker))
                p = papel(d, r, la if la is not None else locate, la is not None)
                if p:
                    out.append(p)
            return out

        papeles = armar(riesgo)
        if not papeles:
            continue
        # EL PODER DE COMPRA. Si el nominal del día no entra, se recorta el
        # riesgo en proporción. Se suma el pico de cada papel: es conservador
        # —dos papeles pueden tocar su pico en minutos distintos— y a
        # propósito, porque el margen se pide al abrir, no al promedio.
        poder = c.equity * apalancamiento(c.equity)
        nominal = sum(p["nominal"] for p in papeles)
        factor = 1.0
        if nominal > poder > 0:
            factor = poder / nominal
            papeles = armar(riesgo * factor)
            recortados += 1
        c.dia(f, papeles)
        c.historia[-1]["poder"] = round(poder, 2)
        c.historia[-1]["nominal"] = round(nominal, 2)
        c.historia[-1]["factor"] = round(factor, 3)
    return c, recortados


def simular(*, deposito=500.0, desde="2026-01-01", riesgo=20.0,
            locate=LOCATE_SUPUESTO, plataforma=PLATAFORMA_MES,
            parar_en=PARAR_EN, sin_hoy=False, escenarios=True):
    """La cuenta propia, devuelta como DATOS: la página y la terminal miran
    exactamente lo mismo."""
    por_fecha, avisos = _dias(desde, sin_hoy)
    anotados = locates_anotados()
    fechas = sorted(por_fecha)
    c, recortados = _correr(por_fecha, deposito=deposito, riesgo=riesgo,
                            locate=locate, plataforma=plataforma,
                            parar_en=parar_en, anotados=anotados)
    # Meses de ALMANAQUE entre la primera y la ultima sesion, no meses
    # distintos: contar septiembre entero con tres dias de datos achica el
    # "al año" un 15%.
    if len(fechas) >= 2:
        import datetime as _dt
        _d = (_dt.date.fromisoformat(fechas[-1]) - _dt.date.fromisoformat(fechas[0])).days
        meses = max(1.0, _d / 30.4375)
    else:
        meses = 1.0
    reales = sum(1 for h in c.historia for p in h["papeles"] if p["locate_real"])
    supuestos = sum(1 for h in c.historia for p in h["papeles"] if not p["locate_real"])
    neto = c.equity - deposito

    def resumen(cta, rec):
        n = cta.equity - cta.deposito
        return {
            "deposito": cta.deposito, "estado": cta.estado,
            "equity": round(cta.equity, 2), "neto": round(n, 2),
            "anual": round(n * 12 / meses, 2),
            "bruto": round(cta.bruto, 2), "comision": round(cta.comision, 2),
            "locates": round(cta.locates, 2), "plataforma": round(cta.plataforma, 2),
            "peor_dd": round(cta.peor_dd, 2),
            "peor_dd_pct": round(100 * cta.peor_dd / cta.deposito, 1),
            "peor_dia": round(cta.peor_dia, 2), "dias": len(cta.historia),
            "recortados": rec,
        }

    out = {
        "desde": desde, "fechas": fechas, "avisos": avisos, "meses": round(meses, 1),
        "params": {"deposito": deposito, "riesgo": riesgo, "locate": locate,
                   "plataforma": plataforma, "parar_en": parar_en},
        "broker": {"comision_acc": COMISION_ACC, "comision_min": COMISION_MIN,
                   "orden_gratis": ORDEN_GRATIS_ACC, "locate_min": LOCATE_MIN_ACC,
                   "apalancamiento": APALANCAMIENTO, "piso": PISO},
        "cuenta": {**resumen(c, recortados),
                   "retirable": round(max(0.0, neto), 2),
                   "locates_reales": reales, "locates_supuestos": supuestos,
                   "historia": c.historia},
        "escenarios": [],
    }
    if escenarios:
        for dep, r in ESCENARIOS:
            if (dep, r) == (deposito, riesgo):
                out["escenarios"].append({"riesgo": r, **resumen(c, recortados)})
                continue
            ce, rec = _correr(por_fecha, deposito=dep, riesgo=r, locate=locate,
                              plataforma=plataforma, parar_en=parar_en,
                              anotados=anotados)
            out["escenarios"].append({"riesgo": r, **resumen(ce, rec)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="La cuenta propia en TradeZero, día por día")
    ap.add_argument("--deposito", type=float, default=500.0)
    ap.add_argument("--riesgo", type=float, default=20.0, help="por papel y por día")
    ap.add_argument("--desde", default="2026-01-01")
    ap.add_argument("--locate", type=float, default=LOCATE_SUPUESTO,
                    help="$/acción para los días sin anotación en /vivo")
    ap.add_argument("--plataforma", type=float, default=PLATAFORMA_MES, help="$/mes")
    ap.add_argument("--parar-en", type=float, default=PARAR_EN,
                    help="stop-out personal, fracción del depósito")
    ap.add_argument("--sin-hoy", action="store_true")
    args = ap.parse_args(argv)

    r = simular(deposito=args.deposito, riesgo=args.riesgo, desde=args.desde,
                locate=args.locate, plataforma=args.plataforma,
                parar_en=args.parar_en, sin_hoy=args.sin_hoy)
    for a in r["avisos"]:
        print(f"  ({a})")
    c = r["cuenta"]
    if not r["fechas"]:
        print(f"  No hay sesiones desde {args.desde}.")
        return 1
    print()
    print(f"  CUENTA PROPIA EN TRADEZERO · ${args.deposito:,.0f} depositados el "
          f"{args.desde} · ${args.riesgo:,.0f} de riesgo por papel")
    print(f"  {c['dias']} días operados en {r['meses']:.1f} meses · estado: {c['estado']}")
    print()
    print(f"  {'equity hoy':<22} ${c['equity']:>10,.2f}")
    print(f"  {'resultado neto':<22} ${c['neto']:>+10,.2f}   (${c['anual']:+,.0f}/año)")
    print(f"  {'bruto':<22} ${c['bruto']:>+10,.2f}")
    print(f"  {'comisiones':<22} ${-c['comision']:>10,.2f}")
    print(f"  {'locates':<22} ${-c['locates']:>10,.2f}   "
          f"({c['locates_reales']} anotados, {c['locates_supuestos']} a "
          f"${args.locate:.2f} supuestos)")
    if c["plataforma"]:
        print(f"  {'plataforma':<22} ${-c['plataforma']:>10,.2f}")
    print(f"  {'peor drawdown':<22} ${c['peor_dd']:>10,.2f}   "
          f"({c['peor_dd_pct']:.0f}% del depósito, intradía)")
    print(f"  {'peor día':<22} ${c['peor_dia']:>10,.2f}")
    if c["recortados"]:
        print(f"  {c['recortados']} día(s) con el riesgo recortado por poder de compra.")
    print()
    print("  {:<10} {:>7} {:>9} {:>9} {:>9} {:>9} {:>8}".format(
        "escenario", "riesgo", "neto", "al año", "peor dd", "% dep", "estado"))
    print("  " + "-" * 68)
    for e in r["escenarios"]:
        print("  {:<10} {:>7} {:>9} {:>9} {:>9} {:>8}% {:>8}".format(
            f"${e['deposito']:,.0f}", f"${e['riesgo']:.0f}", f"${e['neto']:+,.0f}",
            f"${e['anual']:+,.0f}", f"${e['peor_dd']:,.0f}", f"{e['peor_dd_pct']:.0f}",
            e["estado"]))
    print()
    print("  {:<11} {:>7} {:>9} {:>9} {:>9} {:>9}  papeles".format(
        "día", "papeles", "bruto", "costos", "neto", "equity"))
    print("  " + "-" * 70)
    for h in c["historia"]:
        costos = h["comision"] + h["locates"] + h["plataforma"]
        tks = " ".join(p["tk"] for p in h["papeles"])
        print("  {:<11} {:>7} {:>+9,.0f} {:>9,.0f} {:>+9,.0f} {:>9,.0f}  {}{}".format(
            h["f"], len(h["papeles"]), h["bruto"], -costos, h["neto"], h["equity"],
            tks, "  ← recortado" if h.get("factor", 1) < 1 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
