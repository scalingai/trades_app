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
from motor import COSTO_ACCION, jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# --- la estrategia, la de OPERATIVA.md -------------------------------------
PISO, STOP, MAXT, DESDE = 2.0, 45.0, 40, 10.0
CORTE_H, CORTE_UMBRAL = 11.0, 5.0
RIESGO_PAPEL = 400.0
MIN_ORDEN, POR_ACCION = 0.75, 0.005

# --- el plan de fondeo. SUPUESTOS, ver el docstring ------------------------
TOPE_DD = 1000.0        # drawdown máximo, cuenta de $20.000 de poder de compra
OBJETIVO = 1200.0       # profit para pasar la evaluación
EVAL_USD = 97.0         # lo que sale cada evaluación
LIM_DIA = 400.0         # pérdida diaria máxima: bloquea el día, no liquida
SPLIT = 0.70            # el reparto de las ganancias una vez fondeada


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def sig(d):
    return [i for i in señales_swing(d, desde=DESDE) if (d.bars[i][4] or 0) >= PISO]


def pnl_de(dia):
    """Lo que dejó ese papel ese día, neto de comisiones reales."""
    j = jornada(dia, sig, lado="short", stop_pct=STOP, riesgo=RIESGO_PAPEL,
                max_trades=MAXT, corte_h=CORTE_H, corte_umbral=CORTE_UMBRAL)
    if not j:
        return None
    b = j["pnl"]
    for t in j["detalle"]:
        # El motor cobra $0,04/acción; se revierte y se cobra la comisión real
        # de Trade The Pool, que son dos órdenes con su mínimo de $0,75.
        b += t["acciones"] * COSTO_ACCION - comision(t["acciones"])
    return b


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
        self.historia = []          # (fecha, pnl_dia, estado_al_cierre)
        # El peor drawdown que atravesó. Sin esto el informe dice "0 quemadas"
        # y no se sabe si fue por lejos o por un pelo, que es toda la diferencia.
        self.peor_dd = 0.0
        self.peor_dia = 0.0

    TOPEAR_DIA = False

    def dia(self, fecha, pnl):
        if self.estado == "quemada":
            return
        # TOPEAR LA PERDIDA DIARIA ES OPTIMISTA, y por eso viene apagado.
        #
        # El limite diario del plan no es un stop que te deja en $-400 clavado:
        # es un BLOQUEO. Cuando lo tocas te liquidan las posiciones a mercado, y
        # entre que se cruza el umbral y se ejecuta la salida se pierde mas. Y
        # `test_caja_diaria.py` midio que forzar ese cierre EMPEORA el drawdown
        # (de $-3.684 a $-3.788), porque cierra en el peor momento del dia.
        #
        # Toparlo aca daria un informe mas lindo y menos cierto.
        if Cuenta.TOPEAR_DIA:
            pnl = max(pnl, -LIM_DIA)
        self.balance += pnl
        self.pico = max(self.pico, self.balance)
        self.peor_dd = min(self.peor_dd, self.balance - self.pico)
        self.peor_dia = min(self.peor_dia, pnl)
        if self.estado == "fondeada":
            self.dias_fondeada += 1

        if self.balance - self.pico <= -TOPE_DD:
            # Drawdown perforado: la cuenta muere. Se compra otra y se arranca
            # de cero — incluido el objetivo, aunque estuviera por pasarla.
            self.quemadas += 1
            self.estado = "evaluacion"
            self.balance = self.pico = 0.0
            self.gastado += EVAL_USD
        elif self.estado == "evaluacion" and self.balance >= OBJETIVO:
            self.pasadas += 1
            self.estado = "fondeada"
            # Al pasar, el contador arranca de nuevo: lo de la evaluación es
            # virtual, no es plata que se cobre.
            self.balance = self.pico = 0.0
        self.historia.append((fecha, pnl, self.estado))

    def retirar(self):
        """Lo que se puede sacar hoy: el 70% de lo ganado estando fondeada.

        Se deja $1 de colchón: retirar hasta el último peso deja el drawdown
        pegado al tope y cualquier día malo liquida la cuenta.
        """
        if self.estado != "fondeada" or self.balance <= 0:
            return 0.0
        sacar = self.balance * SPLIT
        self.retirado += sacar
        self.balance = 0.0
        self.pico = 0.0
        return sacar


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cuentas de fondeo, día por día")
    ap.add_argument("--cuentas", type=int, default=3)
    ap.add_argument("--desde", default="2026-01-01")
    ap.add_argument("--retiro-cada", type=int, default=14,
                    help="días fondeada entre retiros (el mínimo del plan)")
    ap.add_argument("--topear-dia", action="store_true",
                    help="topear la perdida diaria en el limite (optimista)")
    ap.add_argument("--sin-hoy", action="store_true",
                    help="no leer el feed en vivo (el censo termina ayer)")
    args = ap.parse_args(argv)

    pob = [d for d in poblacion(universo(), min_ratio_vol=0.0,
                                min_expansion=0.0, min_dolar=0.0,
                                max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim" and d.d >= args.desde]
    por_fecha = defaultdict(list)
    for d in pob:
        por_fecha[d.d].append(d)

    # HOY NO ESTA EN EL CENSO: el censo se arma de barras historicas y termina
    # ayer. El dia de hoy sale del feed que escribe la plataforma, que es el
    # mismo camino que usa la pantalla en vivo.
    if not args.sin_hoy:
        try:
            sys.path.insert(0, "puente")
            import vivo as _v
            for (tk, f), datos in _v.leer_feed().items():
                if f < args.desde or f in por_fecha:
                    continue
                dia = _v.armar_dia(tk, f, datos)
                if dia and _cl(dia, hasta=10.0) == "reclaim":
                    por_fecha[f].append(dia)
        except Exception as e:
            print(f"  (sin feed en vivo: {e})")
    fechas = sorted(por_fecha)
    if not fechas:
        print(f"  No hay sesiones desde {args.desde}.")
        return 1

    Cuenta.TOPEAR_DIA = args.topear_dia
    cuentas = [Cuenta(i + 1) for i in range(args.cuentas)]
    ultimo_retiro = {c.n: 0 for c in cuentas}

    for f in fechas:
        papeles = sorted(por_fecha[f], key=lambda d: d.ticker)
        pnls = [(d.ticker, pnl_de(d)) for d in papeles]
        pnls = [(tk, p) for tk, p in pnls if p is not None]
        if not pnls:
            continue
        # REPARTO: cada cuenta un papel distinto. Con menos papeles que cuentas
        # se superponen — es lo que pasa de verdad los días de un solo gapper, y
        # es exactamente cuando las tres cuentas dejan de estar diversificadas.
        for i, c in enumerate(cuentas):
            tk, p = pnls[i % len(pnls)]
            c.dia(f, p)
            if (c.estado == "fondeada"
                    and c.dias_fondeada - ultimo_retiro[c.n] >= args.retiro_cada):
                if c.retirar():
                    ultimo_retiro[c.n] = c.dias_fondeada

    hoy = fechas[-1]
    d_hoy = dt.date.fromisoformat(hoy)
    semana = (d_hoy - dt.timedelta(days=d_hoy.weekday())).isoformat()
    mes = hoy[:7]

    def suma(desde_f):
        return sum(p for c in cuentas for fe, p, _ in c.historia if fe >= desde_f)

    print(f"\n  CUENTAS DE FONDEO DESDE {args.desde}")
    print(f"  {len(fechas)} días operados · último {hoy} · "
          f"{args.cuentas} cuentas\n")

    print("  {:<10} {:>12} {:>12} {:>12}".format("período", "resultado", "días", "cuentas"))
    print("  " + "-" * 50)
    for etq, desde_f in (("hoy", hoy), ("esta semana", semana), ("este mes", mes),
                         ("desde enero", args.desde)):
        dd = sorted({fe for c in cuentas for fe, _, _ in c.historia if fe >= desde_f})
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
    print(f"  Poder de compra gestionado: ${fond * 20000:,.0f} "
          f"({fond} cuentas fondeadas × $20.000)")
    print(f"  En el bolsillo: ${ret:,.0f} retirado − ${gas:,.0f} de "
          f"evaluaciones = ${ret - gas:+,.0f}")
    print()
    dias_pasados = sum(1 for c in cuentas for _, p, _ in c.historia
                       if p < -LIM_DIA)
    if dias_pasados:
        print(f"  ⚠️ {dias_pasados} día(s)-cuenta perdieron más que el límite "
              f"diario de ${LIM_DIA:.0f}.")
        print("  Cada uno bloquea la operativa de ese día. No liquidan la")
        print("  cuenta —eso lo hace el drawdown— pero el plan los mira.")
        print()
    print("  ⚠️ Parámetros SUPUESTOS, no confirmados con Trade The Pool: tope de")
    print(f"  drawdown ${TOPE_DD:,.0f} · objetivo ${OBJETIVO:,.0f} · evaluación "
          f"${EVAL_USD:.0f} · reparto {SPLIT:.0%}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
