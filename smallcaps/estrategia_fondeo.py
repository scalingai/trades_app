#!/usr/bin/env python3
"""Optimizar para PASAR la evaluación, que no es lo mismo que ganar plata.

**Por qué es otro problema.** Con cuenta propia el objetivo es el valor esperado:
si la media por sesión es positiva, con tiempo ganás. Con una cuenta de fondeo el
objetivo es P(llegar a +6% antes de tocar -5%) — un problema de primer paso, no
de esperanza. Y ahí el riesgo por sesión tiene un ÓPTIMO INTERIOR:

  · muy chico → la deriva no alcanza a mover la cuenta antes de que la varianza
    te haga tocar el drawdown por acumulación de ruido
  · muy grande → una racha normal de 3-4 sesiones malas te saca

El óptimo no se adivina: se mide. Todo en unidades de DD (el tope de drawdown),
así vale para cualquier tamaño de cuenta.

    python estrategia_fondeo.py
"""
from __future__ import annotations
import argparse, random, statistics, sys
from collections import defaultdict

from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

R_BASE = 50.0


def serie_sesiones(riesgo=R_BASE):
    """PnL por fecha de calendario, repartiendo el riesgo entre los candidatos."""
    por_fecha = defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        por_fecha[dia.d].append(dia)
    out = []
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = riesgo / len(cands)
        tot, hubo = 0.0, False
        for dia in cands:
            j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota / 3, objetivo=0,
                        stop_pct=15, costo_accion=0.04, max_trades=10,
                        min_liquidez=2.5e5, modo="swing", stop_modo="estructural",
                        colchon=1.0, tope_stop=30)
            if j:
                tot += j["pnl"]; hubo = True
        if hubo:
            out.append(tot / riesgo)      # en unidades de R
    return out


def evaluar(rs, f, objetivo=1.2, tope=1.0, max_ses=250, recorte=None, semilla=0):
    """Una corrida. `f` = riesgo por sesión como fracción del tope de drawdown.

    Devuelve (pasó?, sesiones). `recorte` reduce el riesgo cuando ya se perdió
    parte del colchón — la defensa clásica, que acá se MIDE en vez de suponerse.
    """
    rnd = random.Random(semilla)
    eq = 0.0
    for k in range(max_ses):
        riesgo = f
        if recorte is not None and eq < 0:
            # queda `tope+eq` de colchón; escalar el riesgo a lo que queda
            riesgo = f * max(recorte, (tope + eq) / tope)
        eq += rnd.choice(rs) * riesgo
        if eq <= -tope:
            return False, k + 1
        if eq >= objetivo:
            return True, k + 1
    return False, max_ses


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Optimizar para pasar la evaluación")
    ap.add_argument("--corridas", type=int, default=6000)
    ap.add_argument("--objetivo", type=float, default=1.2, help="target / tope DD")
    args = ap.parse_args(argv)

    rs = serie_sesiones()
    med = statistics.mean(rs)
    print("=" * 92)
    print(f"  ESTRATEGIA DE FONDEO — {len(rs)} sesiones · media {med:+.3f} R · "
          f"objetivo {args.objetivo:.1f}× el tope de drawdown")
    print("  Todo en unidades del TOPE DE DRAWDOWN. Vale para cualquier cuenta.")
    print("=" * 92)

    print(f"\n  {'riesgo/sesión':>14} {'(cuenta 20k)':>13} {'PASA':>7} {'revienta':>9} "
          f"{'no llega':>9} {'ses. mediana':>13} {'ses. p90':>9}")
    print("  " + "-" * 80)
    filas = []
    for f in (.04, .06, .08, .10, .12, .145, .18, .22, .28, .35):
        res = [evaluar(rs, f, args.objetivo, semilla=s) for s in range(args.corridas)]
        ok = [r for r in res if r[0]]
        p = 100 * len(ok) / len(res)
        rev = 100 * sum(1 for r in res if not r[0] and r[1] < 250) / len(res)
        ses = sorted(r[1] for r in ok)
        # cuenta de $20.000 → tope DD 5% = $1.000
        print(f"  {f:>13.3f} {('$'+format(int(f*1000),',')):>13} {p:>6.0f}% "
              f"{rev:>8.0f}% {100-p-rev:>8.0f}% "
              f"{(f'{statistics.median(ses):.0f}' if ses else '—'):>13} "
              f"{(f'{ses[int(.9*len(ses))]:.0f}' if ses else '—'):>9}")
        filas.append((f, p, statistics.median(ses) if ses else None))

    mejor = max(filas, key=lambda x: x[1])
    print(f"\n  ÓPTIMO: riesgo {mejor[0]:.3f} del tope → pasa {mejor[1]:.0f}% "
          f"en {mejor[2]:.0f} sesiones (mediana)")

    print("\n  ¿SIRVE RECORTAR EL RIESGO CUANDO VAS PERDIENDO?")
    print(f"  {'variante':>28} {'PASA':>7} {'revienta':>9} {'ses. mediana':>13}")
    print("  " + "-" * 60)
    f = mejor[0]
    for lab, rec in (("riesgo fijo", None), ("proporcional al colchón", 0.0),
                     ("proporcional, piso 50%", 0.5),
                     ("proporcional, piso 25%", 0.25)):
        res = [evaluar(rs, f, args.objetivo, recorte=rec, semilla=s)
               for s in range(args.corridas)]
        ok = [r for r in res if r[0]]
        rev = 100 * sum(1 for r in res if not r[0] and r[1] < 250) / len(res)
        ses = sorted(r[1] for r in ok)
        print(f"  {lab:>28} {100*len(ok)/len(res):>6.0f}% {rev:>8.0f}% "
              f"{(f'{statistics.median(ses):.0f}' if ses else '—'):>13}")

    print("""
  'no llega' es agotar 250 sesiones sin tocar ninguno de los dos bordes: no te
  sacan, pero tampoco cobrás. Con riesgo muy chico es el destino más probable, y
  es la trampa de "voy conservador" — la cuenta no revienta, simplemente no pasa.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
