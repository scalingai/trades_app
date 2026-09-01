#!/usr/bin/env python3
"""Dos años operando tres cuentas de fondeo, mes a mes.

Simula el ciclo completo y lo imprime como un libro mayor: comprar las
evaluaciones, pasarlas (o reventarlas y volver a comprar), operar la cuenta ya
fondeada, cobrar, y pagar los costos que existen aunque no se hable de ellos.

QUÉ MODELA, y de dónde sale cada número:

  · Serie de sesiones     medida sobre el censo (1.985 días observables) con el
                          filtro validado: volumen del día > $137M y float < 47M.
                          Replica entre períodos con 1,6 puntos de brecha.
  · Riesgo por sesión     f = 0,28 del tope de drawdown. Óptimo medido para
                          maximizar P(pasar), no el valor esperado.
  · Locate                20% del nominal — el número pesimista de Espes. Se
                          reserva UNA VEZ por papel por día.
  · Datos de mercado      CERO: la prop pone plataforma y feed. El $200/mes de
                          Espes era su terminal propia operando capital propio, no
                          aplica acá. Con --data se puede cargar el costo de un
                          escáner premarket propio, que la firma NO da.
  · Reparto               70/30. Evaluación $97, reembolsada con el primer cobro.
  · Colchón al cobrar     0,25 del tope. Retirar todo deja la cuenta pegada al piso.
  · Primer cobro          no en el mismo mes en que se fondea (espera de la firma).

QUÉ NO MODELA, y hay que tenerlo presente al leer:
  · Ejecuciones reales. Todo son velas de un minuto; nunca se probó un fill.
  · Que el operador es una persona y va a cambiar el tamaño cuando vaya perdiendo.
  · Reglas de días mínimos de operación que algunas firmas exigen.

    SMALLCAPS_CENSO=1 python simulacion_2anios.py
    SMALLCAPS_CENSO=1 python simulacion_2anios.py --locate 0.10
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics
import sys
from collections import defaultdict

import config
from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

R_BASE = 50.0
TOPE_USD = 1000.0      # tope de drawdown de la cuenta de $20.000 (5%)
OBJ = 1.2              # objetivo +6% contra tope -5%
EVAL_USD = 97.0
DATA_MES = 0.0    # la prop pone plataforma y datos; se pisa con --data
SPLIT = 0.70
CUSHION = 0.25


def serie_filtrada(stop_pct=None, tope=30.0):
    """(pnl en R, nominal en R) por fecha de calendario, con el filtro validado."""
    db = sqlite3.connect(config.bars_db_path())
    flo = {}
    for t, d, so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
        if so:
            flo[(t, d)] = so
    db.close()

    por_fecha = defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        dolar = sum((b[5] or 0) * (b[4] or 0) for b in dia.bars)
        f = flo.get((dia.ticker, dia.d))
        if dolar <= 137e6:                       # filtro validado: liquidez
            continue
        if f is not None and f > 47e6:           # filtro validado: float
            continue
        por_fecha[dia.d].append(dia)

    out = []
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = R_BASE / len(cands)
        pnl, nom, hubo = 0.0, 0.0, False
        for dia in cands:
            j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota / 3, objetivo=0,
                        stop_pct=(stop_pct or 15), costo_accion=0.04, max_trades=10,
                        min_liquidez=2.5e5, modo="swing",
                        stop_modo=("estructural" if stop_pct is None else "fijo"),
                        colchon=1.0, tope_stop=tope)
            if not j:
                continue
            hubo = True
            pnl += j["pnl"]
            mx = 0.0
            for t in (j.get("detalle") or []):
                mx = max(mx, (t.get("acciones") or 0) * (t.get("precio") or 0))
            nom += mx
        if hubo:
            out.append((pnl / R_BASE, nom / R_BASE))
    return out


def correr(rs, ses_mes, f, locate, meses=24, semilla=0, diario=False):
    """Una corrida. Si `diario`, devuelve además el libro mayor mes a mes."""
    rnd = random.Random(semilla)
    n = len(rs)
    camino = []
    while len(camino) < meses * ses_mes + 20:
        i = rnd.randrange(0, max(1, n - 15))
        camino += rs[i:i + 15]

    # estado: "eval" | "fondeada" | (muerta se recompra al mes siguiente)
    estado = ["eval"] * 3
    eq = [0.0] * 3
    fondeada_este_mes = [False] * 3
    caja = -3 * EVAL_USD          # las tres evaluaciones, pagadas el día uno
    evals = 3
    libro, k = [], 0

    for mes in range(1, meses + 1):
        bruto = loc_mes = 0.0
        muertes, pases = 0, 0
        fondeada_este_mes = [False] * 3
        for _ in range(ses_mes):
            x, nom = camino[k % len(camino)]
            k += 1
            for c in range(3):
                if estado[c] == "muerta":
                    continue
                ret = x * f - locate * nom * f          # todo en unidades de tope
                eq[c] += ret
                bruto += x * f * TOPE_USD
                loc_mes += locate * nom * f * TOPE_USD
                if eq[c] <= -1.0:
                    estado[c] = "muerta"
                    muertes += 1
                elif estado[c] == "eval" and eq[c] >= OBJ:
                    estado[c] = "fondeada"
                    eq[c] = 0.0
                    fondeada_este_mes[c] = True
                    pases += 1

        cobro = 0.0
        for c in range(3):
            if estado[c] == "fondeada" and not fondeada_este_mes[c] and eq[c] > CUSHION:
                cobro += (eq[c] - CUSHION) * TOPE_USD * SPLIT
                eq[c] = CUSHION
        recompras = sum(1 for c in range(3) if estado[c] == "muerta")
        caja += cobro - DATA_MES - recompras * EVAL_USD
        evals += recompras
        for c in range(3):
            if estado[c] == "muerta":
                estado[c] = "eval"
                eq[c] = 0.0

        if diario:
            libro.append({"mes": mes, "bruto": bruto, "locate": loc_mes,
                          "cobro": cobro, "caja": caja, "pases": pases,
                          "muertes": muertes, "recompras": recompras,
                          "estado": [e for e in estado],
                          "eq": [round(x, 2) for x in eq]})
    return caja, evals, libro


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dos años con tres cuentas de fondeo")
    ap.add_argument("--locate", type=float, default=0.20)
    ap.add_argument("--f", type=float, default=0.28)
    ap.add_argument("--meses", type=int, default=24)
    ap.add_argument("--corridas", type=int, default=2000)
    ap.add_argument("--stop", type=float, default=45.0,
                    help="stop fijo en %; 0 = estructural")
    ap.add_argument("--data", type=float, default=0.0,
                    help="costo mensual de datos propios (la prop pone la plataforma)")
    args = ap.parse_args(argv)
    global DATA_MES
    DATA_MES = args.data

    rs = serie_filtrada(args.stop or None, max(50.0, args.stop))
    ses_mes = max(4, round(len(rs) / 22))       # el censo cubre ~22 meses
    med = statistics.mean(x[0] for x in rs)
    nm = statistics.mean(x[1] for x in rs)

    print("=" * 100)
    print(f"  DOS AÑOS · 3 CUENTAS DE FONDEO · locate {args.locate:.0%} del nominal · "
          f"f = {args.f:.2f}")
    print(f"  stop {(str(int(args.stop)) + '% fijo') if args.stop else 'estructural'} · "
          f"{len(rs)} sesiones en el censo · {ses_mes}/mes · "
          f"bruto {med:+.3f} R · nominal {nm:.2f} R · "
          f"punto de muerte {100*med/nm:.1f}%")
    print(f"  Tope de drawdown ${TOPE_USD:,.0f} · reparto {SPLIT:.0%} · "
          f"evaluación ${EVAL_USD:.0f} · data ${DATA_MES:.0f}/mes")
    print("=" * 100)

    # La corrida de ejemplo: la MEDIANA por caja final, no la mejor.
    corridas = [(correr(rs, ses_mes, args.f, args.locate, args.meses, s)[0], s)
                for s in range(args.corridas)]
    corridas.sort()
    _, semilla_med = corridas[len(corridas) // 2]
    caja, evals, libro = correr(rs, ses_mes, args.f, args.locate, args.meses,
                                semilla_med, diario=True)

    print("\n  EJEMPLO — la corrida MEDIANA de "
          f"{args.corridas:,} (ni la buena ni la mala)\n")
    print(f"  {'mes':>4} {'bruto':>9} {'locate':>9} {'cobro':>9} {'data':>7} "
          f"{'caja acum':>11}  {'cuentas':>22}  {'evento'}")
    print("  " + "-" * 104)
    for r in libro:
        est = " ".join({"eval": "eval", "fondeada": "FOND"}[e] for e in r["estado"])
        ev = []
        if r["pases"]:
            ev.append(f"pasa {r['pases']}")
        if r["muertes"]:
            ev.append(f"revienta {r['muertes']}")
        if r["recompras"]:
            ev.append(f"recompra {r['recompras']}")
        print(f"  {r['mes']:>4} {r['bruto']:>+8.0f} {-r['locate']:>+8.0f} "
              f"{r['cobro']:>+8.0f} {-DATA_MES:>+6.0f} "
              f"{('$' + format(int(r['caja']), ',')):>11}  {est:>22}  "
              f"{', '.join(ev)}")

    tot_b = sum(r["bruto"] for r in libro)
    tot_l = sum(r["locate"] for r in libro)
    tot_c = sum(r["cobro"] for r in libro)
    print(f"\n  {'':>4} {tot_b:>+8.0f} {-tot_l:>+8.0f} {tot_c:>+8.0f} "
          f"{-DATA_MES*args.meses:>+6.0f} {('$' + format(int(caja), ',')):>11}   "
          f"← {evals} evaluaciones compradas en total")

    print(f"\n  Lectura: de ${tot_b:,.0f} brutos de trading, ${tot_l:,.0f} se van en")
    print(f"  locates y el 30% del resto se lo queda la firma. Te quedan "
          f"${caja:,.0f} en el bolsillo.")

    print(f"\n  LA DISTRIBUCIÓN — la corrida de arriba es UNA de {args.corridas:,}\n")
    v = [c for c, _ in corridas]
    print(f"  {'peor':>10} {'p10':>10} {'p25':>10} {'MEDIANA':>10} {'p75':>10} "
          f"{'p90':>10} {'mejor':>10}")
    print("  " + "-" * 76)
    q = lambda p: v[int(p * (len(v) - 1))]
    print("  " + " ".join(f"{('$' + format(int(x), ',')):>10}" for x in
                          (v[0], q(.10), q(.25), q(.50), q(.75), q(.90), v[-1])))
    print(f"\n  probabilidad de terminar los 2 años en rojo: "
          f"{100*sum(1 for x in v if x < 0)/len(v):.0f}%")

    print(f"\n  SENSIBILIDAD AL LOCATE — lo único que no sabemos\n")
    print(f"  {'locate':>8} {'mediana 2 años':>16} {'p10':>12} {'p90':>12} {'en rojo':>9}")
    print("  " + "-" * 62)
    for loc in (0.0, .05, .10, .15, .20, .25):
        w = sorted(correr(rs, ses_mes, args.f, loc, args.meses, s)[0]
                   for s in range(600))
        print(f"  {loc:>7.0%} {('$' + format(int(w[len(w)//2]), ',')):>16} "
              f"{('$' + format(int(w[int(.1*len(w))]), ',')):>12} "
              f"{('$' + format(int(w[int(.9*len(w))]), ',')):>12} "
              f"{100*sum(1 for x in w if x < 0)/len(w):>8.0f}%")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
