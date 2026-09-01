#!/usr/bin/env python3
"""Scalping sobre los mismos dias: muchos viajes de ida y vuelta, uno por vez.

**La idea es de Agus y ataca el problema por donde no lo habiamos atacado.**
Hasta ahora el filtro decidia dos cosas a la vez: que dias operar Y como
operarlos (acumular tramos, sostener al cierre). La propuesta es separarlos:
que el filtro arme la WATCHLIST —los dias que valen la pena mirar— y buscar
adentro de esos dias una mecanica distinta, de mas frecuencia.

Y hay una razon mecanica fuerte, que es la que me convence de probarlo:

    el locate se paga por la EXPOSICION SIMULTANEA MAXIMA del dia

Hoy acumulamos hasta 25 tramos abiertos al mismo tiempo: el pico es enorme y
por eso el punto de muerte queda en ~86 centavos. Si en cambio se entra y se
sale, con UNA posicion por vez, el pico es el de un solo tramo — once veces
menos. Los mismos trades (o mas) sobre una fraccion del papel reservado.

El contraargumento honesto: en este proyecto acortar la tenencia empeoro DIEZ
veces. Pero esas diez fueron cortar temprano una posicion que igual se sostenia
—el resto del dia seguia con capital desplegado— y aca la comparacion es otra:
se resigna cola derecha y se compra pico chico. Nunca se midio asi.

    SMALLCAPS_CENSO=1 python fam_scalping.py
"""

from __future__ import annotations

import statistics
import sys

import motor
from chavineta import clasificar_apertura as _cl
from dias import CIERRE_RTH, hora
from motor import _trade, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9
R = 50.0


def jornada_scalp(dia, señal, *, stop_pct, riesgo, objetivo_pct=None,
                  minutos=None, max_trades=40, solapar=False):
    """Una jornada de scalping: NO se abre un tramo si hay otro vivo.

    `solapar=True` reproduce el comportamiento actual (acumular), para que la
    comparacion sea contra el mismo motor y no contra otra implementacion.
    """
    idx = señal(dia)
    if not idx:
        return None
    r_trade = riesgo / 3.0
    detalle, n, libre_desde = [], 0, -1.0
    for i in idx:
        if n >= max_trades:
            break
        h = hora(dia.bars[i])
        if not solapar and h < libre_desde:
            continue                     # todavia hay una posicion abierta
        # Presupuesto honesto: equity a mercado en este minuto.
        px = dia.bars[i][4]
        eq = 0.0
        for t in detalle:
            if t["h_sal"] is not None and t["h_sal"] <= h:
                eq += t["pnl"]
            elif px:
                eq += t["acciones"] * (t["p_ent"] - px)
        if eq - r_trade < -riesgo:
            break
        r = _trade(dia, i, lado="short", stop_pct=stop_pct, riesgo=r_trade,
                   objetivo_pct=objetivo_pct,
                   salida_h=(h + minutos / 60.0) if minutos else None)
        if not r:
            continue
        detalle.append(r)
        n += 1
        libre_desde = r["h_sal"] if r["h_sal"] is not None else CIERRE_RTH
    if not n:
        return None
    return {"pnl": sum(t["pnl"] for t in detalle), "trades": n,
            "nominal": motor._nominal_pico(detalle), "detalle": detalle}


def medir(pob, **kw):
    S = []
    for d in pob:
        j = jornada_scalp(d, lambda x: [i for i in señales_swing(x, desde=10.0)
                                        if (x.bars[i][4] or 0) >= 2.0],
                          stop_pct=45.0, riesgo=R, **kw)
        if not j:
            continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                       -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da
            pa = max(pa, a)
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"]})
    if len(S) < 12:
        return None
    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)
    ses = len({x["d"] for x in S}) / MESES
    return {"n": len(S), "ses": ses, "tr": sum(x["tr"] for x in S) / MESES,
            "bruto": b, "acc": acc, "cents": 100 * b / acc if acc else 0,
            "mes": b * ses,
            "P1": [x for x in S if x["d"] < motor.CORTE],
            "P2": [x for x in S if x["d"] >= motor.CORTE]}


def cents(S):
    if len(S) < 12:
        return None
    b = statistics.mean(x["pnl"] for x in S)
    a = statistics.mean(x["acc"] for x in S)
    return 100 * b / a if a else 0


def main() -> int:
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=100.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    print(f"  WATCHLIST: {len(pob)} dias de reclaim con expansion >=100%")
    print("  La pregunta no es que dias operar —eso ya esta— sino que hacer "
          "adentro.\n")
    print(f"  {'mecanica':<38} {'ses/m':>6} {'tr/mes':>7} {'acc pico':>9} "
          f"{'muerte':>8} {'P1':>7} {'P2':>7} {'bruto/mes':>10}")
    print("  " + "-" * 96)

    CASOS = [
        ("ACUMULAR — lo de hoy", dict(solapar=True)),
        ("secuencial · al cierre", dict()),
        ("secuencial · objetivo 5%", dict(objetivo_pct=5)),
        ("secuencial · objetivo 10%", dict(objetivo_pct=10)),
        ("secuencial · objetivo 20%", dict(objetivo_pct=20)),
        ("secuencial · 15 min", dict(minutos=15)),
        ("secuencial · 30 min", dict(minutos=30)),
        ("secuencial · 60 min", dict(minutos=60)),
        ("secuencial · obj 10% o 30 min", dict(objetivo_pct=10, minutos=30)),
        ("secuencial · obj 20% o 60 min", dict(objetivo_pct=20, minutos=60)),
    ]
    for lab, kw in CASOS:
        r = medir(pob, **kw)
        if not r:
            print(f"  {lab:<38}   (muestra corta)")
            continue
        p1, p2 = cents(r["P1"]), cents(r["P2"])
        f1 = f"{p1:>6.0f}c" if p1 is not None else f"{'s/dato':>7}"
        f2 = f"{p2:>6.0f}c" if p2 is not None else f"{'s/dato':>7}"
        print(f"  {lab:<38} {r['ses']:>6.1f} {r['tr']:>7.0f} {r['acc']:>9.0f} "
              f"{r['cents']:>7.0f}c {f1} {f2} {r['mes']:>+10.2f}")

    print("""
  'acc pico' es lo que hay que tener localizado. Si el scalping lo baja mucho
  y el bruto no cae en la misma proporcion, el punto de muerte sube y el
  sistema aguanta locates mas caros — que es todo lo que importa.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
