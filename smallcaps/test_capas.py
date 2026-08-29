#!/usr/bin/env python3
"""¿Las tres capas COMPONEN, o se estorban?

El protocolo asume que las capas se apilan: el régimen del mes decide si operás,
el escáner decide qué, la viabilidad decide cuál. Pero este proyecto ya midió
dos veces que **apilar filtros mejora el trade y empeora el año** —el edge sube
y la frecuencia se desploma más rápido—. Así que la pregunta no es si cada capa
mejora la mediana: es si el NEGOCIO mejora.

Se mide todo en dos monedas a la vez:
  · por trade — la mediana, que es lo que mira el operador
  · por año   — mediana × frecuencia, que es lo que paga el alquiler

Un filtro que duplica el edge y divide la frecuencia por cinco es un mal
negocio, y en la tabla de "por trade" se ve como una mejora.

    python test_capas.py
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict

import config
from radar import regimen
from radar_historico import historial_completo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Composición de las tres capas")
    ap.add_argument("--precio-min", type=float, default=0.70)
    ap.add_argument("--precio-max", type=float, default=20.0,
                    help="20 por defecto: el barrido mostró que $5-$20 es plano")
    ap.add_argument("--min-gap", type=float, default=70.0)
    ap.add_argument("--float-max", type=float, default=10e6)
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    hist = historial_completo(db)

    filas = db.execute(
        "SELECT e.ticker, e.d, e.open, e.gap_pct, e.intraday_pct, "
        "       s.shares_outstanding, s.dilution_12m_pct "
        "FROM events e LEFT JOIN event_structure s "
        "  ON s.ticker = e.ticker AND s.d = e.d "
        "WHERE e.intraday_pct IS NOT NULL AND e.open IS NOT NULL "
        "  AND e.dollar_volume >= 1e6").fetchall()

    # Régimen de cada mes, calculado una vez.
    meses = sorted({d[:7] for _t, d, *_ in filas})
    reg = {m: regimen(db, m) for m in meses}
    dias_totales = len({d for _t, d, *_ in filas})
    años = dias_totales / 252.0

    cand = []
    for t, d, o, gap, intra, acc, dil in filas:
        if not (args.precio_min <= o <= args.precio_max):
            continue
        if gap is None or gap < args.min_gap:
            continue
        if not acc or acc > args.float_max:
            continue
        h, n_h = hist.get((t, d), (None, 0))
        cand.append({"t": t, "d": d, "intra": intra, "hist": h, "n_hist": n_h,
                     "dil": dil, "reg": reg.get(d[:7], {}).get("veredicto")})

    print("=" * 96)
    print("  ¿LAS CAPAS COMPONEN?")
    print(f"  {len(filas):,} eventos · {len(cand)} candidatos · "
          f"{años:.1f} años de datos")
    print("  'por año' = mediana × trades por año. Es la moneda que importa.")
    print("=" * 96)

    def linea(lab, g, base_n=None):
        if len(g) < 12:
            print(f"  {lab:44} n={len(g):>4}   (insuficiente)")
            return
        v = [x["intra"] for x in g]
        m = statistics.median(v)
        por_año = len(g) / años
        print(f"  {lab:44} n={len(g):>4}  med {m:>+7.2f}%  "
              f"{por_año:>5.1f} trades/año  →  {m*por_año:>+8.0f}%/año  "
              f"cae {100*sum(1 for x in v if x<0)/len(v):>3.0f}%")

    print(f"\n  {'':44} {'':>7}  {'por trade':>12}  {'frecuencia':>16}  {'por año':>10}")
    print("  " + "-" * 94)
    linea("CAPA 2 sola — el escáner", cand)
    print()
    linea("  + capa 1: solo meses 'fading'",
          [c for c in cand if c["reg"] == "fading"])
    linea("  + capa 1: meses 'fading' o 'mixto'",
          [c for c in cand if c["reg"] in ("fading", "mixto")])
    print()
    linea("  + capa 3: historial de fallo >= 60%",
          [c for c in cand if (c["hist"] or 0) >= 60])
    linea("  + capa 3: dilución 12m > 100%",
          [c for c in cand if (c["dil"] or 0) > 100])
    print()
    linea("  LAS TRES: fading + historial >= 60%",
          [c for c in cand if c["reg"] == "fading" and (c["hist"] or 0) >= 60])
    linea("  LAS TRES + dilución > 100%",
          [c for c in cand if c["reg"] == "fading" and (c["hist"] or 0) >= 60
           and (c["dil"] or 0) > 100])

    print("\n" + "=" * 96)
    print("  CUÁNTOS TICKERS DISTINTOS, Y CUÁNTO SE REPITEN")
    print("=" * 96)
    por_ticker = defaultdict(list)
    for c in cand:
        por_ticker[c["t"]].append(c["d"])
    repetidos = {t: v for t, v in por_ticker.items() if len(v) > 1}
    print(f"\n  {len(por_ticker)} tickers distintos para {len(cand)} candidatos")
    print(f"  {len(repetidos)} aparecen más de una vez "
          f"({100*len(repetidos)/max(1,len(por_ticker)):.0f}%)")
    v_rep = [c["intra"] for c in cand if len(por_ticker[c["t"]]) > 1]
    v_uni = [c["intra"] for c in cand if len(por_ticker[c["t"]]) == 1]
    if len(v_rep) >= 12 and len(v_uni) >= 12:
        print(f"\n  reincidentes  n={len(v_rep):>4}  mediana {statistics.median(v_rep):+.2f}%")
        print(f"  primerizos    n={len(v_uni):>4}  mediana {statistics.median(v_uni):+.2f}%")
        print("\n  Si los reincidentes rinden más, el historial de la capa 3 está")
        print("  capturando algo real y no solo azar de muestra chica.")

    print("\n" + "=" * 96)
    print("  LA CUENTA DEL NEGOCIO")
    print("=" * 96)
    n_año = len(cand) / años
    print(f"""
  El escáner produce {n_año:.0f} candidatos por año — menos de uno cada dos
  semanas. Los operadores del informe hacen 12 a 30 trades POR DÍA sobre 2-4
  tickers.

  No es la misma actividad, y la diferencia no es de calibración: ellos operan
  el mismo papel muchas veces en el día (re-entradas, reciclaje), mientras que
  esto cuenta UN trade por evento. Para llegar a su frecuencia hay que
  multiplicar por las re-entradas, que es justamente la parte que no está
  medida acá.

  Lo que sí dice esta tabla: con {n_año:.0f} eventos al año, la varianza anual la
  define un puñado de trades. Cualquier cosa que reduzca más la frecuencia
  —apilar otra capa— hay que justificarla contra eso, no contra la mediana.
""")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
