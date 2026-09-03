#!/usr/bin/env python3
"""Si hubiéramos arrancado con cuentas de fondeo el 2 de enero, ¿dónde estaríamos?

QUE SIMULA. El ciclo de vida completo: comprar evaluaciones, pasarlas o
quemarlas, operar las que pasan, y volver a comprar cuando una muere. Día por
día, con la estrategia de `OPERATIVA.md` y el corte de las 11:00 puesto.

LAS TRES CUENTAS NO SON TRES VECES LA MISMA, y esa es la única razón por la que
tener tres no es lo mismo que tener una con el triple de riesgo. Si las tres
copiaran los mismos trades estarían perfectamente correlacionadas: pasan juntas
y se queman juntas. Acá cada cuenta toma UN papel distinto los días de varios
papeles, y recién los días de un solo papel se superponen. Es lo único que las
decorrelaciona de verdad.

LOS PARAMETROS SON SUPUESTOS, NO REGLAS CONFIRMADAS. Salen de leer la web y de
`cartera_fondeo.py`, no de una respuesta de Trade The Pool. El mail sigue sin
mandarse. Si el tope de drawdown fuera más chico, todo esto se redimensiona.

    python cuentas.py
    python cuentas.py --cuentas 1 --desde 2026-01-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import hora
from motor import COSTO_ACCION, jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# --- la estrategia, la de OPERATIVA.md -------------------------------------
PISO, STOP, MAXT, DESDE = 2.0, 45.0, 40, 10.0
CORTE_H, CORTE_UMBRAL = 11.0, 5.0
CORTE_REENTRA = False
RIESGO_PAPEL = 250.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005

# --- el plan de fondeo -----------------------------------------------------
#
# LOS PORCENTAJES SON DEL PRODUCTO, verificados el 2026-09-03 contra
# tradethepool.com/the-program. Lo que sigue SIN confirmar es qué poder de
# compra compra la evaluación de US$97 — de ahí sale todo lo demás.
#
# EL PODER DE COMPRA ES $25.000, verificado contra la tabla de precios: los
# US$97 son la cuenta Advanced de $25.000 —objetivo $1.500, drawdown $1.000,
# pérdida diaria $500—. No los $20.000 que asumíamos.
#
# Eso deja dos correcciones encadenadas, y la segunda es mía de hoy. `TOPE_DD`
# decía $1.000, que era CORRECTO, y yo lo "arreglé" a $800 razonando sobre una
# cuenta de $20.000 que no es la nuestra. Los que estaban mal eran el objetivo
# ($1.200 en vez de $1.500) y el límite diario ($400 en vez de $500).
#
# Moraleja del episodio: derivar de una base equivocada da tres números
# equivocados en vez de uno. Ahora la base está verificada y todo cuelga de
# ella, así que un solo dato la corrige entera.
PODER = 25_000.0        # cuenta Advanced de US$97. Verificado.
PLAN = "flex"           # flex | max

_PLANES = {
    #        objetivo  drawdown  día    consistencia   días buenos p/retirar
    "flex": (0.06,     0.04,     0.02,  0.50,          3),
    "max":  (0.06,     0.03,     0.01,  0.30,          0),
}
_o, _dd, _d, _cons, _buenos = _PLANES[PLAN]
OBJETIVO = PODER * _o           # profit para pasar la evaluación
TOPE_DD = PODER * _dd           # drawdown máximo
LIM_DIA = PODER * _d            # pérdida diaria máxima: bloquea el día
CONSISTENCIA = _cons            # la mejor POSICION vs el objetivo, en evaluación
EVAL_USD = 97.0                 # lo que sale cada evaluación
SPLIT = 0.70                    # el reparto una vez fondeada

# --- las reglas de retiro, verificadas en tradethepool.com -----------------
# "You can request a withdrawal 14 days after the account's inception date or
#  after a previous withdrawal, provided you have a minimum of $300 in profits."
# "To be eligible to withdraw profits from your FLEX account, you must earn at
#  least 0.5% of your buying power in profit on 3 separate trading days within
#  any 14-day period. These days do not need to be consecutive."
#
# Hasta hoy el simulador sacaba el 70% del balance apenas hubiera algo, cada 14
# DIAS OPERADOS. Eso adelanta la caja y esconde el caso que importa: una cuenta
# que gana en pocos golpes grandes puede no juntar nunca los tres días de 0,5%
# y quedarse sin poder cobrar aunque el balance esté arriba.
MIN_RETIRO = 300.0              # mínimo de profit para pedir un retiro
DIAS_ENTRE_RETIROS = 14         # días CALENDARIO, no operados
DIA_BUENO = 0.005 * PODER       # el 0,5% del poder de compra
BUENOS_PEDIDOS = _buenos        # cuántos hacen falta (FLEX 3, MAX 0)
VENTANA_BUENOS = 14             # días calendario en los que tienen que caer

# ¿EL PISO TREPA CON EL PICO, O ES FIJO HASTA EL LOCK? Los términos dicen las
# dos cosas según cómo se lean. El texto habla de un drawdown que sigue a la
# cuenta; el EJEMPLO que dan es de piso fijo: "$100.000 inicial, $4.000 de max
# drawdown (equity mínima $96.000); una vez que la equity llega a $106.000 la
# equity mínima pasa a $100.000". Si trepara con el pico, a $106.000 el piso
# sería $102.000, no $96.000.
#
# No se puede resolver leyendo. Se deja el interruptor y se miden las dos: la
# diferencia entre ambas ES la pregunta para soporte.
DD_TRAILING = True


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def sig(d):
    return [i for i in señales_swing(d, desde=DESDE) if (d.bars[i][4] or 0) >= PISO]


def pnl_de(dia):
    """Lo que dejó ese papel ese día, con el detalle que la página necesita.

    Devuelve el neto, el DRAWDOWN INTRADIA de la posición, y los tramos. El
    drawdown no es un adorno: el plan mide desde el pico, así que un día que
    cierra en +$50 después de haber ido -$300 gastó $300 del tope de $800 y el
    PnL final no lo dice.
    """
    j = jornada(dia, sig, lado="short", stop_pct=STOP, riesgo=RIESGO_PAPEL,
                max_trades=MAXT, corte_h=CORTE_H, corte_umbral=CORTE_UMBRAL,
                corte_reentra=CORTE_REENTRA)
    if not j:
        return None
    b = j["pnl"]
    for t in j["detalle"]:
        # El motor cobra $0,04/acción; se revierte y se cobra la comisión real
        # de Trade The Pool, que son dos órdenes con su mínimo de $0,75.
        b += t["acciones"] * COSTO_ACCION - comision(t["acciones"])

    # LA CURVA INTRADIA, marcada a mercado barra a barra.
    #
    # NO ES UN ADORNO NI UN MAXIMO: es la serie completa, y hace falta entera
    # porque las dos reglas duras del plan se miden ASI, verificado en
    # tradethepool.com/program-terms:
    #
    #   "The account Daily Loss is the current equity (projected balance) at
    #    each moment minus the balance (realized) at the start of the day"
    #   "once the account has reached 3 x DLs in equity (i.e. 'projected
    #    balance' including unrealized profits) the max drawdown will move to
    #    the initial balance"
    #
    # O sea: equity PROYECTADA, con las posiciones abiertas adentro, en cada
    # momento. Un maximo por dia no alcanza — hace falta saber en que ORDEN
    # paso, porque el pico que sube el piso puede ser antes o despues del pozo.
    #
    # Se mide SIN comisiones: son un offset chico y constante, y meterlas
    # barra a barra fingiria una precision que no tenemos.
    i0 = min((dia.idx_en(t["h_ent"]) or 0) for t in j["detalle"])
    curva = []
    for k in range(i0, len(dia.bars)):
        pk = dia.bars[k][4]
        if not pk:
            continue
        hk = hora(dia.bars[k])
        eq = 0.0
        for t in j["detalle"]:
            if t["h_ent"] > hk:
                continue
            if t["h_sal"] is not None and t["h_sal"] <= hk:
                eq += t["pnl"]
            else:
                eq += t["acciones"] * (t["p_ent"] - pk)
        curva.append(round(eq, 2))
    pico = 0.0
    dd = 0.0
    for eq in curva:
        pico = max(pico, eq)
        dd = min(dd, eq - pico)
    return {"pnl": b, "dd": dd, "tramos": len(j["detalle"]), "curva": curva}


class Cuenta:
    """Una cuenta con su ciclo: evaluación -> fondeada -> quemada -> otra vez."""

    def __init__(self, n):
        self.n = n
        self.estado = "evaluacion"
        self.balance = 0.0          # PnL acumulado DESDE que arrancó esta vida
        self.pico = 0.0             # para el drawdown, que es contra el máximo
        self.gastado = EVAL_USD     # lo que costó ponerla a andar
        self.retirado = 0.0         # lo que salió a tu bolsillo (ya con el 70%)
        self.pasadas = 0
        self.quemadas = 0
        self.dias_fondeada = 0
        self.historia = []          # un dict por dia operado, con el papel
        # El peor drawdown que atravesó. Sin esto el informe dice "0 quemadas"
        # y no se sabe si fue por lejos o por un pelo, que es toda la diferencia.
        self.peor_dd = 0.0
        self.peor_dia = 0.0
        # Para las reglas de retiro. Fechas CALENDARIO, no dias operados: el
        # plan cuenta 14 dias de almanaque y una cuenta que opera dos veces por
        # mes tarda meses en juntar 14 dias OPERADOS. Contarlos mal adelanta la
        # caja meses enteros.
        self.desde_fondeada = None   # cuando empezo esta vida fondeada
        self.ultimo_retiro_f = None  # fecha del ultimo retiro
        self.buenos = []             # dias con >= 0,5% del poder de compra
        self.bloqueado = 0           # veces que quiso retirar y no pudo
        # POR QUE se bloqueo, contado. Sin esto el simulador dice "retiraste
        # menos" y no dice si fue por los 14 dias —que se destraban solos— o
        # por los tres dias de 0,5% —que pueden no llegar nunca—. Son dos
        # problemas distintos y uno solo tiene arreglo.
        self.motivos = defaultdict(int)

    TOPEAR_DIA = False

    def dia(self, fecha, pnl, ticker=None, dd_dia=0.0, tramos=0, curva=None):
        """Un día, minuto a minuto y con las reglas duras del plan aplicadas.

        ESTO SE MEDIA AL CIERRE Y ESTABA MAL. `tradethepool.com/program-terms`
        es explícito: la pérdida diaria es "the current equity (projected
        balance) AT EACH MOMENT minus the balance at the start of the day", y
        el drawdown se aplica "instantly based on intraday projected balance".
        Las dos con las posiciones ABIERTAS adentro.

        La diferencia no es teórica. El 2026-07-21 VIVK cerró en +$2.882 —el
        mejor día de la muestra— después de haber ido -$1.048 contra un tope de
        $800. Medido al cierre ese día es una fiesta; medido como lo mide el
        plan, las tres cuentas estaban liquidadas.

        DOS REGLAS, y hacen cosas distintas:

          · DAILY PAUSE. Si la equity del día toca -`LIM_DIA`, "all open
            positions and orders are closed and the account is prevented from
            opening trades until the opening of the next trading day". No es un
            stop que te deja clavado en -$400: te cierran a mercado en ESE
            minuto, que es el peor del día por definición.

          · DRAWDOWN. El piso trepa con el pico y, una vez que la equity toca
            3×DL, "the max drawdown will move to the initial balance". Ahí deja
            de trepar y queda clavado en breakeven.
        """
        if self.estado == "quemada":
            return
        base = self.balance          # balance realizado al abrir el día
        muerto = pausado = False
        real = pnl                   # lo que termina contando para el balance

        if curva:
            for eq in curva:
                equity = base + eq
                self.pico = max(self.pico, equity)
                # El piso: trepa con el pico hasta que la cuenta llega a 3×DL,
                # y ahí se clava en el balance inicial.
                if self.pico >= 3 * LIM_DIA:
                    piso = 0.0
                elif DD_TRAILING:
                    piso = self.pico - TOPE_DD
                else:
                    piso = -TOPE_DD
                if equity <= piso:
                    muerto = True
                    real = eq
                    break
                if eq <= -LIM_DIA:
                    # Daily Pause: se cierra TODO a mercado en este minuto.
                    pausado = True
                    real = eq
                    break
        self.balance = base + real
        self.pico = max(self.pico, self.balance)
        self.peor_dd = min(self.peor_dd, self.balance - self.pico)
        self.peor_dia = min(self.peor_dia, real)
        if self.estado == "fondeada":
            self.dias_fondeada += 1
            if real >= DIA_BUENO:
                self.buenos.append(fecha)

        if muerto:
            self.quemadas += 1
            self.estado = "evaluacion"
            self.balance = self.pico = 0.0
            self.gastado += EVAL_USD
        elif self.estado == "evaluacion" and self.balance >= OBJETIVO:
            self.pasadas += 1
            self.estado = "fondeada"
            self.desde_fondeada = fecha
            self.ultimo_retiro_f = None
            self.buenos = []
            # Al pasar, el contador arranca de nuevo: lo de la evaluación es
            # virtual, no es plata que se cobre.
            self.balance = self.pico = 0.0
        # Se guarda el TICKER y el drawdown de ese papel ese dia. Sin el
        # ticker la pagina no puede bajar de la cuenta al papel, que es
        # justamente lo que hay que poder auditar.
        self.historia.append({
            "f": fecha, "tk": ticker, "pnl": round(real, 2),
            "dd": round(dd_dia, 2), "tramos": tramos,
            "estado": self.estado, "balance": round(self.balance, 2),
            "retirado": round(self.retirado, 2),
            "pausado": pausado, "muerto": muerto})

    def puede_retirar(self, fecha):
        """Las tres condiciones del plan, verificadas en tradethepool.com.

        Devuelve None si se puede, o el motivo por el que no. Devolver el
        MOTIVO y no un booleano es lo que deja contar despues cual de las tres
        es la que muerde — que es la unica razon por la que este metodo existe.
        """
        if self.estado != "fondeada":
            return "no fondeada"
        if self.balance < MIN_RETIRO:
            return f"menos de ${MIN_RETIRO:.0f}"
        # 14 dias calendario desde que se fondeo, o desde el ultimo retiro.
        base = self.ultimo_retiro_f or self.desde_fondeada
        if base:
            d = (dt.date.fromisoformat(fecha) - dt.date.fromisoformat(base)).days
            if d < DIAS_ENTRE_RETIROS:
                return f"faltan {DIAS_ENTRE_RETIROS - d} dias"
        if BUENOS_PEDIDOS:
            # "3 dias con 0,5% dentro de CUALQUIER ventana de 14 dias", y no
            # hace falta que sean consecutivos. Se busca si existe una ventana
            # de 14 dias corridos que contenga tres.
            fs = sorted(dt.date.fromisoformat(x) for x in self.buenos)
            hay = any(sum(1 for y in fs if 0 <= (y - x).days < VENTANA_BUENOS)
                      >= BUENOS_PEDIDOS for x in fs)
            if not hay:
                return f"{len(fs)}/{BUENOS_PEDIDOS} dias de 0,5%"
        return None

    def retirar(self, fecha):
        """El 70% de lo ganado estando fondeada, SI el plan lo permite.

        Antes esto sacaba plata apenas hubiera balance, cada 14 dias OPERADOS.
        Con eso la proyeccion de caja adelantaba meses y, peor, escondia el
        caso que importa: una cuenta que gana en pocos golpes grandes puede no
        juntar nunca los tres dias de 0,5% y quedarse sin poder cobrar aunque
        el balance este arriba.
        """
        motivo = self.puede_retirar(fecha)
        if motivo:
            if motivo != "no fondeada":
                self.bloqueado += 1
                # Se agrupa por TIPO, no por el texto con el numero adentro.
                clave = ("faltan días" if motivo.startswith("faltan")
                         else "días de 0,5%" if "0,5%" in motivo
                         else motivo)
                self.motivos[clave] += 1
            return 0.0
        sacar = self.balance * SPLIT
        self.retirado += sacar
        self.balance = 0.0
        self.pico = 0.0
        self.ultimo_retiro_f = fecha
        # NO se reinician los dias buenos. El plan dice "3 separate trading
        # days within ANY 14-day period": es una condicion sobre la historia de
        # la cuenta, no un contador que arranca de cero con cada cobro.
        # Reiniciarlo era una lectura mia, mas estricta que la regla.
        return sacar


class _Vista:
    """Los campos de una `Cuenta` como objeto.

    Existe para que el reporte de terminal —que itera objetos— no haya que
    reescribirlo ahora que `simular` devuelve diccionarios.
    """

    def __init__(self, d):
        self.__dict__.update(d)


def simular(*, n_cuentas=3, desde="2026-01-01", riesgo=None,
            reentra=False, topear=False, sin_hoy=False):
    """El ciclo de vida completo, devuelto como DATOS en vez de impreso.

    Se extrajo de `main` para que la pagina de portafolio y la terminal miren
    exactamente lo mismo. Es la misma razon por la que `_papel_vivo` es una
    sola funcion para hoy y para un dia pasado: dos caminos que calculan lo
    mismo se separan solos, y en una proyeccion de plata eso no se puede.
    """
    global CORTE_REENTRA, RIESGO_PAPEL
    CORTE_REENTRA = reentra
    if riesgo is not None:
        RIESGO_PAPEL = riesgo
    Cuenta.TOPEAR_DIA = topear

    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0,
                                min_expansion=0.0, min_dolar=0.0,
                                max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim" and d.d >= desde]
    por_fecha = defaultdict(list)
    for d in pob:
        por_fecha[d.d].append(d)

    # HOY NO ESTA EN EL CENSO: el censo se arma de barras historicas y termina
    # ayer. El dia de hoy sale del feed que escribe la plataforma, que es el
    # mismo camino que usa la pantalla en vivo.
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

    fechas = sorted(por_fecha)
    cuentas = [Cuenta(i + 1) for i in range(n_cuentas)]
    for f in fechas:
        papeles = sorted(por_fecha[f], key=lambda d: d.ticker)
        pnls = [(d.ticker, pnl_de(d)) for d in papeles]
        pnls = [(tk, r) for tk, r in pnls if r is not None]
        if not pnls:
            continue
        # REPARTO: cada cuenta un papel distinto. Con menos papeles que cuentas
        # se superponen — es lo que pasa de verdad los dias de un solo gapper.
        for i, c in enumerate(cuentas):
            tk, r = pnls[i % len(pnls)]
            c.dia(f, r["pnl"], ticker=tk, dd_dia=r["dd"],
                  tramos=r["tramos"], curva=r.get("curva"))
            c.retirar(f)

    return {
        "desde": desde, "fechas": fechas, "avisos": avisos,
        "riesgo": RIESGO_PAPEL,
        "plan": {"nombre": PLAN, "poder": PODER, "objetivo": OBJETIVO,
                 "tope_dd": TOPE_DD, "lim_dia": LIM_DIA, "eval": EVAL_USD,
                 "split": SPLIT, "consistencia": CONSISTENCIA,
                 "min_retiro": MIN_RETIRO, "dias_entre": DIAS_ENTRE_RETIROS,
                 "dia_bueno": DIA_BUENO, "buenos_pedidos": BUENOS_PEDIDOS,
                 "ventana_buenos": VENTANA_BUENOS},
        "cuentas": [{
            "n": c.n, "estado": c.estado, "balance": round(c.balance, 2),
            "retirado": round(c.retirado, 2), "gastado": round(c.gastado, 2),
            "pasadas": c.pasadas, "quemadas": c.quemadas,
            "dias_fondeada": c.dias_fondeada,
            "peor_dd": round(c.peor_dd, 2), "peor_dia": round(c.peor_dia, 2),
            "bloqueado": c.bloqueado, "motivos": dict(c.motivos),
            "historia": c.historia,
        } for c in cuentas],
    }


def main(argv=None) -> int:
    # `global` tiene que ir antes de cualquier uso del nombre en la funcion, y
    # `RIESGO_PAPEL` se usa como default del argumento unas lineas abajo.
    global CORTE_REENTRA, RIESGO_PAPEL
    ap = argparse.ArgumentParser(description="Cuentas de fondeo, día por día")
    ap.add_argument("--cuentas", type=int, default=3)
    ap.add_argument("--desde", default="2026-01-01")
    ap.add_argument("--retiro-cada", type=int, default=14,
                    help="días fondeada entre retiros (el mínimo del plan)")
    ap.add_argument("--riesgo", type=float, default=RIESGO_PAPEL,
                    help="riesgo por papel y por dia")
    ap.add_argument("--reentra", action="store_true",
                    help="volver a entrar despues del corte de las 11:00")
    ap.add_argument("--topear-dia", action="store_true",
                    help="topear la perdida diaria en el limite (optimista)")
    ap.add_argument("--sin-hoy", action="store_true",
                    help="no leer el feed en vivo (el censo termina ayer)")
    args = ap.parse_args(argv)

    r = simular(n_cuentas=args.cuentas, desde=args.desde, riesgo=args.riesgo,
                reentra=args.reentra, topear=args.topear_dia,
                sin_hoy=args.sin_hoy)
    for a in r["avisos"]:
        print(f"  ({a})")
    fechas = r["fechas"]
    if not fechas:
        print(f"  No hay sesiones desde {args.desde}.")
        return 1
    cuentas = [_Vista(d) for d in r["cuentas"]]

    hoy = fechas[-1]
    d_hoy = dt.date.fromisoformat(hoy)
    semana = (d_hoy - dt.timedelta(days=d_hoy.weekday())).isoformat()
    mes = hoy[:7]

    def suma(desde_f):
        return sum(h["pnl"] for c in cuentas for h in c.historia
                   if h["f"] >= desde_f)

    print(f"\n  CUENTAS DE FONDEO DESDE {args.desde}")
    print(f"  {len(fechas)} días operados · último {hoy} · "
          f"{args.cuentas} cuentas\n")

    print("  {:<10} {:>12} {:>12} {:>12}".format("período", "resultado", "días", "cuentas"))
    print("  " + "-" * 50)
    for etq, desde_f in (("hoy", hoy), ("esta semana", semana), ("este mes", mes),
                         ("desde enero", args.desde)):
        dd = sorted({h["f"] for c in cuentas for h in c.historia
                     if h["f"] >= desde_f})
        print("  {:<10} ${:>11,.0f} {:>12} {:>12}".format(
            etq, suma(desde_f), len(dd), args.cuentas))

    print()
    print("  {:<7} {:>10} {:>9} {:>9} {:>4} {:>4} {:>10} {:>10}".format(
        "cuenta", "estado", "balance", "retirado", "pasa", "quem", "peor dd",
        "peor dia"))
    print("  " + "-" * 74)
    for c in cuentas:
        margen = 100 * (1 - abs(c.peor_dd) / TOPE_DD)
        print("  {:<7} {:>10} ${:>8,.0f} ${:>8,.0f} {:>4} {:>4} ${:>9,.0f} "
              "${:>9,.0f}   ({:.0f}% de margen)".format(
                  f"#{c.n}", c.estado, c.balance, c.retirado, c.pasadas,
                  c.quemadas, c.peor_dd, c.peor_dia, margen))

    ret = sum(c.retirado for c in cuentas)
    bal = sum(c.balance for c in cuentas)
    gas = sum(c.gastado for c in cuentas)
    fond = sum(1 for c in cuentas if c.estado == "fondeada")
    peor = min(c.peor_dd for c in cuentas)
    print("  " + "-" * 74)
    print("  {:<7} {:>10} ${:>8,.0f} ${:>8,.0f} {:>4} {:>4} ${:>9,.0f}".format(
        "TOTAL", f"{fond} fond.", bal, ret, sum(c.pasadas for c in cuentas),
        sum(c.quemadas for c in cuentas), peor))
    print()
    print(f"  Poder de compra gestionado: ${fond * PODER:,.0f} "
          f"({fond} cuentas fondeadas × ${PODER:,.0f})")
    print(f"  En el bolsillo: ${ret:,.0f} retirado − ${gas:,.0f} de "
          f"evaluaciones = ${ret - gas:+,.0f}")
    print()
    # AHORA LA PAUSA DIARIA ESTA SIMULADA, no contada despues. `dia()` cierra
    # todo en el minuto en que la equity toca el limite, asi que estos son los
    # dias que el plan efectivamente corto.
    pausados = sum(1 for c in cuentas for h in c.historia if h.get("pausado"))
    muertos = sum(1 for c in cuentas for h in c.historia if h.get("muerto"))
    if pausados or muertos:
        print(f"  {pausados} día(s)-cuenta cortados por la pausa diaria de "
              f"${LIM_DIA:.0f} · {muertos} liquidación(es) por drawdown.")
    dias_pasados = 0
    if dias_pasados:
        print("  Cada uno bloquea la operativa de ese día. No liquidan la")
        print("  cuenta —eso lo hace el drawdown— pero el plan los mira.")
        print()
    # POR QUE NO SE RETIRO MAS. Es la pregunta que el simulador no contestaba.
    tot_bloq = defaultdict(int)
    for c in cuentas:
        for k, v in c.motivos.items():
            tot_bloq[k] += v
    if tot_bloq:
        print()
        print("  Días en que se quiso retirar y el plan no dejó:")
        for k, v in sorted(tot_bloq.items(), key=lambda x: -x[1]):
            print(f"    {v:>4} · {k}")
        print(f"    (las reglas: mínimo ${MIN_RETIRO:.0f} · {DIAS_ENTRE_RETIROS}"
              f" días calendario entre retiros · {BUENOS_PEDIDOS} días con"
              f" ${DIA_BUENO:.0f} en {VENTANA_BUENOS} días)")
    print()

    print("  ⚠️ Parámetros SUPUESTOS, no confirmados con Trade The Pool: tope de")
    print(f"  drawdown ${TOPE_DD:,.0f} · objetivo ${OBJETIVO:,.0f} · evaluación "
          f"${EVAL_USD:.0f} · reparto {SPLIT:.0%}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
