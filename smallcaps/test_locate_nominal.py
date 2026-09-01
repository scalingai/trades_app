#!/usr/bin/env python3
"""Si el locate es un % del NOMINAL, el stop ancho deja de ser gratis.

Espes, en las fuentes: "les pongo como un 20% de comisión para intentar ponerme
en el lado pesimista... me cuestan como un 20% de lo que pongo [en el trade]".

Todo lo medido en este proyecto hasta hoy asumió costo POR ACCIÓN o costo FIJO
por día. Con costo proporcional al nominal cambia el álgebra, porque el tamaño
sale del riesgo y del stop:

    nominal = riesgo / (stop_pct / 100)

Un stop del 30% mueve SEIS VECES más nominal que uno del 5% para el mismo riesgo
en dólares. Con costo por acción eso era casi gratis — por eso el stop estructural
ancho ganaba. Con locate al 20% del nominal, el stop ancho paga seis veces más.

O sea: el hallazgo de que el stop ancho era el mejor se midió con la estructura
de costos equivocada. Acá se remide cobrando el locate como fracción del nominal,
UNA VEZ por papel por día — se reserva a la mañana y sirve para todos los trades
del día en ese papel, que es como funciona de verdad.

    SMALLCAPS_CENSO=1 python test_locate_nominal.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict

from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO_DIA = 50.0
STOPS = (5, 8, 12, 18, 25, None)      # None = stop estructural (el actual)


def correr(stop_pct, tope_stop=30.0):
    """Devuelve por fecha: (pnl bruto, nominal máximo reservado por papel)."""
    por_fecha = defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        por_fecha[dia.d].append(dia)

    filas = []
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = RIESGO_DIA / len(cands)
        pnl, nominal, hubo = 0.0, 0.0, False
        for dia in cands:
            j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota / 3, objetivo=0,
                        stop_pct=(stop_pct or 15), costo_accion=0.04, max_trades=10,
                        min_liquidez=2.5e5, modo="swing",
                        stop_modo=("estructural" if stop_pct is None else "fijo"),
                        colchon=1.0, tope_stop=tope_stop)
            if not j:
                continue
            hubo = True
            pnl += j["pnl"]
            # El locate se reserva por el MAYOR nominal que se va a necesitar
            # en ese papel durante el día.
            mx = 0.0
            for t in (j.get("detalle") or []):
                mx = max(mx, (t.get("acciones") or 0) * (t.get("precio") or 0))
            nominal += mx
        if hubo:
            filas.append((pnl, nominal))
    return filas


def main() -> int:
    print("=" * 98)
    print(f"  LOCATE COMO % DEL NOMINAL — riesgo ${RIESGO_DIA:.0f}/día · "
          "reservado una vez por papel por día")
    print("  El nominal es riesgo/stop: stop angosto = posición chica = menos locate.")
    print("=" * 98)

    tabla = {}
    for sp in STOPS:
        f = correr(sp)
        if len(f) < 50:
            continue
        pnl = [x[0] for x in f]
        nom = [x[1] for x in f]
        tabla[sp] = (statistics.mean(pnl), statistics.mean(nom), len(f))

    print(f"\n  {'stop':>14} {'sesiones':>9} {'bruto/ses':>11} {'nominal res.':>13} "
          f"{'retorno/nominal':>16} {'locate de muerte':>17}")
    print("  " + "-" * 88)
    for sp, (m, n, k) in tabla.items():
        lab = "estructural" if sp is None else f"{sp}% fijo"
        print(f"  {lab:>14} {k:>9} {m:>+10.2f} {('$' + format(int(n), ',')):>13} "
              f"{100 * m / n:>15.2f}% {100 * m / n:>16.2f}%")

    print("\n  PNL NETO POR SESIÓN SEGÚN CUÁNTO SEA EL LOCATE\n")
    locs = (0.0, .01, .02, .05, .10, .15, .20)
    print(f"  {'stop':>14} " + " ".join(f"{(format(100*l, '.0f') + '%'):>9}" for l in locs))
    print("  " + "-" * (16 + 10 * len(locs)))
    for sp, (m, n, k) in tabla.items():
        lab = "estructural" if sp is None else f"{sp}% fijo"
        print(f"  {lab:>14} " + " ".join(f"{m - l * n:>+9.2f}" for l in locs))

    print("""
  'locate de muerte' = el % del nominal donde el neto llega a cero. Es igual al
  retorno sobre nominal, por construcción.

  Leer la última tabla por columnas, no por filas: la columna del 20% dice cuál
  —si alguna— de las variantes sobrevive al número de Espes. Y ojo con que un
  stop más angosto no es gratis: te sacan más seguido. El bruto de la primera
  tabla ya tiene eso adentro.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
