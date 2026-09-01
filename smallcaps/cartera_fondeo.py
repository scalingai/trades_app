#!/usr/bin/env python3
"""Una cuenta, dos o tres. Sincrónicas o escalonadas. Cuán agresivo.

**La trampa que hay que ver antes de comprar nada.** Tres cuentas corriendo la
MISMA señal al MISMO tiempo están perfectamente correlacionadas: son una sola
cuenta al triple. El día que revienta una revientan las tres. Comprar tres así
no compra seguridad — compra apalancamiento y lo disfraza de diversificación.

Las formas de romper esa correlación son cuatro y se miden distinto:

  A · sincrónicas, mismo riesgo  correlación 1. Todo o nada.
  B · secuenciales               la 2ª arranca recién cuando la 1ª pasa.
                                 Decorrelaciona en el tiempo, pero es lento y
                                 el tiempo es justamente el recurso escaso.
  C · señales repartidas         cada cuenta toma trades distintos del mismo día.
                                 Decorrelaciona de verdad, a costa de menos
                                 trades por cuenta (más varianza en cada una).
  D · riesgo escalonado          misma señal, distinta agresividad por cuenta.
                                 La agresiva fondea rápido, la conservadora es
                                 el seguro contra que la agresiva se caiga.

El recurso escaso NO es la plata ($97 la evaluación, y encima la devuelven) sino
el TIEMPO: hay 10 sesiones operables por mes. Por eso la agresividad se elige
contra el reloj, no contra el bolsillo.

UNIDADES: todo en múltiplos del tope de drawdown. Con la cuenta de $20.000 ese
tope es $1.000, así que 1.0 = $1.000. Vale para cualquier tamaño de cuenta.

    python cartera_fondeo.py
    SMALLCAPS_CENSO=1 python cartera_fondeo.py
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from collections import defaultdict

from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

R_BASE = 50.0          # riesgo con el que se mide la serie base
SES_MES = 10           # sesiones operables por mes (mediana medida)
TOPE_USD = 1000.0      # tope de drawdown en dólares (cuenta de $20.000, 5%)
OBJ = 1.2              # objetivo = 1.2x el tope (6% contra 5%)
EVAL_USD = 97.0        # costo de una evaluación
LOCATE = 6.99 / TOPE_USD   # locate por sesión, FIJO en dólares -> en unidades de tope
SPLIT = 0.70


def series():
    """(serie completa, serie repartida en 3) por sesión, en unidades de R."""
    por_fecha = defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        por_fecha[dia.d].append(dia)

    todas, part = [], []
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = R_BASE / len(cands)
        tot, hubo, trades = 0.0, False, []
        for dia in cands:
            j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota / 3, objetivo=0,
                        stop_pct=15, costo_accion=0.04, max_trades=10,
                        min_liquidez=2.5e5, modo="swing", stop_modo="estructural",
                        colchon=1.0, tope_stop=30)
            if j:
                tot += j["pnl"]
                hubo = True
                trades += [t["pnl"] for t in (j.get("detalle") or [])]
        if hubo:
            todas.append(tot / R_BASE)
            # Reparto alternado: la cuenta c se queda con los trades c, c+3, c+6...
            # Se reescala x3 porque cada cuenta usa su presupuesto diario COMPLETO
            # repartido entre un tercio de los trades.
            g = [0.0, 0.0, 0.0]
            for k, p in enumerate(trades):
                g[k % 3] += p
            part.append([x * 3 / R_BASE for x in g])
    return todas, part


def simular(rs, part, modo, f, n_cuentas, meses=12, cushion=0.5, semilla=0):
    """Una corrida de `meses`. Devuelve (cobrado $, fondeadas, evaluaciones pagadas).

    Todas las cuentas ven el MISMO mercado (mismo camino de sesiones): es lo que
    pasa en la realidad y es lo que hace que la correlación importe.
    """
    rnd = random.Random(semilla)
    n = len(rs)
    largo = meses * SES_MES

    camino, cam_part = [], []
    while len(camino) < largo:                      # bootstrap por bloques
        i = rnd.randrange(0, n - 15)
        camino += rs[i:i + 15]
        cam_part += part[i:i + 15]
    camino, cam_part = camino[:largo], cam_part[:largo]

    fs = {"A": [f] * n_cuentas,
          "B": [f] * n_cuentas,
          "C": [f] * n_cuentas,
          "D": ([f * 1.6, f, f * 0.6])[:n_cuentas]}[modo]

    # En B sólo arranca la primera; las demás esperan a que pase la anterior.
    activa = [True] + [modo != "B"] * (n_cuentas - 1)
    estado = ["eval"] * n_cuentas
    eq = [0.0] * n_cuentas
    cobrado = 0.0
    pagadas = sum(1 for a in activa if a)

    for k, x in enumerate(camino):
        for c in range(n_cuentas):
            if not activa[c] or estado[c] == "muerta":
                continue
            ret = (cam_part[k][c] if modo == "C" else x) * fs[c] - LOCATE
            eq[c] += ret
            if eq[c] <= -1.0:
                estado[c] = "muerta"
                activa[c] = False
                continue
            if estado[c] == "eval" and eq[c] >= OBJ:
                estado[c] = "fondeada"
                eq[c] = 0.0                          # el piso se recalcula al fondear
                if modo == "B":                      # destraba la siguiente
                    for j2 in range(n_cuentas):
                        if not activa[j2] and estado[j2] == "eval":
                            activa[j2] = True
                            pagadas += 1
                            break
        if (k + 1) % SES_MES == 0:                   # cobro mensual
            for c in range(n_cuentas):
                if estado[c] == "fondeada" and eq[c] > cushion:
                    cobrado += (eq[c] - cushion) * TOPE_USD * SPLIT
                    eq[c] = cushion

    return cobrado - pagadas * EVAL_USD, sum(1 for e in estado if e == "fondeada"), pagadas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cartera de cuentas de fondeo")
    ap.add_argument("--corridas", type=int, default=3000)
    ap.add_argument("--meses", type=int, default=12)
    args = ap.parse_args(argv)

    rs, part = series()
    print("=" * 96)
    print(f"  CARTERA DE FONDEO — {len(rs)} sesiones · {SES_MES} operables/mes · "
          f"horizonte {args.meses} meses · reparto {SPLIT:.0%}")
    print(f"  Tope de drawdown = ${TOPE_USD:,.0f}. Cobrado ya NETO del costo de las "
          "evaluaciones.")
    print("=" * 96)

    nombres = {"A": "sincrónicas, mismo riesgo",
               "B": "secuenciales (la 2ª tras pasar la 1ª)",
               "C": "señales repartidas entre cuentas",
               "D": "riesgo escalonado 1.6 / 1.0 / 0.6"}

    print("\n  ¿CUÁNTAS CUENTAS, Y CÓMO ARMARLAS? (f = 0.22)\n")
    print(f"  {'armado':>38} {'n':>3} {'fondeadas':>10} {'cobrado 12m':>12} "
          f"{'P(cero)':>8} {'peor 10%':>10}")
    print("  " + "-" * 86)
    for N in (1, 2, 3):
        for modo in (["A"] if N == 1 else ["A", "B", "C", "D"]):
            r = [simular(rs, part, modo, .22, N, args.meses, semilla=s)
                 for s in range(args.corridas)]
            cob = sorted(x[0] for x in r)
            fon = [x[1] for x in r]
            print(f"  {nombres[modo]:>38} {N:>3} {statistics.mean(fon):>10.2f} "
                  f"{('$' + format(int(statistics.mean(cob)), ',')):>12} "
                  f"{100 * sum(1 for x in fon if x == 0) / len(fon):>7.0f}% "
                  f"{('$' + format(int(cob[int(.1 * len(cob))]), ',')):>10}")

    print("\n  ¿CUÁN AGRESIVO? (3 cuentas, riesgo escalonado)\n")
    print(f"  {'f':>6} {'fondeadas':>10} {'cobrado 12m':>12} {'P(cero)':>8} "
          f"{'P(las 3)':>9} {'peor 10%':>10} {'mejor 10%':>11}")
    print("  " + "-" * 74)
    for f in (.10, .145, .22, .28, .35, .45):
        r = [simular(rs, part, "D", f, 3, args.meses, semilla=s)
             for s in range(args.corridas)]
        cob = sorted(x[0] for x in r)
        fon = [x[1] for x in r]
        print(f"  {f:>6.3f} {statistics.mean(fon):>10.2f} "
              f"{('$' + format(int(statistics.mean(cob)), ',')):>12} "
              f"{100 * sum(1 for x in fon if x == 0) / len(fon):>7.0f}% "
              f"{100 * sum(1 for x in fon if x == 3) / len(fon):>8.0f}% "
              f"{('$' + format(int(cob[int(.1 * len(cob))]), ',')):>10} "
              f"{('$' + format(int(cob[int(.9 * len(cob))]), ',')):>11}")

    print("\n  ¿CUÁNTO DEJAR DE COLCHÓN AL COBRAR? (3 cuentas, f = 0.22)")
    print("  Retirar todo deja la cuenta pegada al piso: el mes siguiente cualquier")
    print("  racha normal la mata. Dejar mucho es no cobrar.\n")
    print(f"  {'colchón':>10} {'cobrado 12m':>12} {'fondeadas al final':>20} "
          f"{'P(cero)':>9}")
    print("  " + "-" * 56)
    for cu in (0.0, .25, .50, .75, 1.0):
        r = [simular(rs, part, "D", .22, 3, args.meses, cushion=cu, semilla=s)
             for s in range(args.corridas)]
        fon = [x[1] for x in r]
        print(f"  {cu:>10.2f} "
              f"{('$' + format(int(statistics.mean(x[0] for x in r)), ',')):>12} "
              f"{statistics.mean(fon):>20.2f} "
              f"{100 * sum(1 for x in fon if x == 0) / len(fon):>8.0f}%")

    print("""
  'P(cero)' es terminar el año sin NINGUNA cuenta fondeada. Es el riesgo real de
  la operación y es lo único que hay que mirar antes de elegir agresividad — el
  promedio no sirve para decidir cuando la cola izquierda te saca del juego.

  'peor 10%' es el percentil 10 del cobrado: el año malo, no el catastrófico.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
