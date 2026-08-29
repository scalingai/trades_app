#!/usr/bin/env python3
"""¿El historial de gaps de un ticker predice el próximo? (Capa 3 del protocolo)

El protocolo dice: si un ticker gapeó 10 veces y en 7 terminó en rojo, tenés una
ventaja estadística en ESE activo. Es una afirmación fuerte y barata de testear
sobre las barras diarias — no hace falta un solo dato nuevo.

**Es una hipótesis, no una regla.** Puede fallar por dos razones distintas y
conviene tenerlas separadas antes de mirar el resultado:

  1. Reversión a la media. Que un papel haya fallado 7 de 10 veces puede ser
     azar: con 10 tiradas, el 17% de las monedas justas sacan 7 caras o más.
  2. Que sea el mismo efecto que ya mide la dilución. Un diluidor serial falla
     seguido PORQUE diluye; si es así, el historial no agrega nada sobre la
     ficha de EDGAR y es un feature redundante disfrazado de nuevo.

Las dos se controlan acá: la primera exigiendo un mínimo de gaps previos y
mirando si el gradiente es monotónico; la segunda cruzando contra la dilución.

**Todo es point-in-time.** Para el evento del 2025-06-10 solo se cuentan los
gaps ANTERIORES a esa fecha. Un historial calculado sobre la serie completa
tendría el futuro adentro, que es el error que este proyecto ya cometió una vez
con el share count.

    python test_historial.py
    python test_historial.py --min-gap 70 --min-previos 5
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Historial de fallo del gapeador")
    ap.add_argument("--min-gap", type=float, default=50.0)
    ap.add_argument("--min-dollar-vol", type=float, default=5e5)
    ap.add_argument("--min-previos", type=int, default=3,
                    help="gaps anteriores necesarios para que el historial cuente")
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    filas = db.execute(
        "SELECT ticker, d, gap_pct, intraday_pct, dollar_volume FROM events "
        "WHERE gap_pct >= ? AND dollar_volume >= ? AND intraday_pct IS NOT NULL "
        "ORDER BY ticker, d", (args.min_gap, args.min_dollar_vol)).fetchall()
    dil = {(t, d): x for t, d, x in db.execute(
        "SELECT ticker,d,dilution_12m_pct FROM event_structure "
        "WHERE dilution_12m_pct IS NOT NULL")}
    db.close()

    # Historial acumulado POR TICKER, recorriendo en orden cronológico. Al
    # llegar a un evento, el contador tiene solo lo anterior — que es
    # exactamente lo que se sabría ese día.
    previos = defaultdict(lambda: [0, 0])   # ticker -> [gaps, fallidos]
    datos = []
    for t, d, gap, intra, _dv in filas:
        n, fall = previos[t]
        if n >= args.min_previos:
            datos.append({
                "t": t, "d": d, "gap": gap, "intra": intra,
                "tasa": 100.0 * fall / n, "n_previos": n,
                "dil": dil.get((t, d)),
                "per": "P1" if d < CORTE_PERIODO else "P2",
            })
        previos[t] = [n + 1, fall + (1 if intra < 0 else 0)]

    print("=" * 88)
    print(f"  HISTORIAL DEL GAPEADOR  ·  gaps >= +{args.min_gap:.0f}%  ·  "
          f"{len(filas):,} eventos  ·  {len(datos):,} con >= {args.min_previos} previos")
    print("  'falló' = el evento cerró por debajo de su apertura")
    print("  Todo point-in-time: para cada evento solo se cuentan los gaps ANTERIORES.")
    print("=" * 88)

    if len(datos) < 100:
        print(f"\n  muestra insuficiente ({len(datos)})")
        return 1

    base = [x["intra"] for x in datos]
    print(f"\n  LÍNEA DE BASE  n={len(base)}  mediana={statistics.median(base):+.2f}%  "
          f"falla el {100*sum(1 for x in base if x<0)/len(base):.0f}%")

    bandas = [("falló < 40% de las veces", 0, 40),
              ("falló 40-60%", 40, 60),
              ("falló 60-80%", 60, 80),
              ("falló >= 80%", 80, 101)]
    print(f"\n  {'historial previo del ticker':30} {'n':>5} {'mediana':>9} {'falla':>7} "
          f"{'P1':>9} {'P2':>9}")
    print("  " + "-" * 76)
    for lab, lo, hi in bandas:
        g = [x for x in datos if lo <= x["tasa"] < hi]
        if len(g) < 30:
            print(f"  {lab:30} {len(g):>5}   (n insuficiente)")
            continue
        v = [x["intra"] for x in g]
        f = lambda p: (statistics.median([x["intra"] for x in g if x["per"] == p])  # noqa: E731
                       if sum(1 for x in g if x["per"] == p) >= 20 else None)
        fmt = lambda x: f"{x:+8.2f}%" if x is not None else "       —"  # noqa: E731
        print(f"  {lab:30} {len(g):>5} {statistics.median(v):>+8.2f}% "
              f"{100*sum(1 for x in v if x<0)/len(v):>6.0f}% "
              f"{fmt(f('P1'))} {fmt(f('P2'))}")

    print("\n  ¿ES EL MISMO EFECTO QUE LA DILUCIÓN, O APORTA APARTE?")
    print(f"  {'':30} {'dil <= 100%':>16} {'dil > 100%':>16}")
    print("  " + "-" * 64)
    for lab, lo, hi in (("historial < 60%", 0, 60), ("historial >= 60%", 60, 101)):
        fila = []
        for dlo, dhi in ((None, 100), (100, None)):
            g = [x["intra"] for x in datos
                 if lo <= x["tasa"] < hi and x["dil"] is not None
                 and (dlo is None or x["dil"] > dlo)
                 and (dhi is None or x["dil"] <= dhi)]
            fila.append(f"{statistics.median(g):+8.2f}% (n={len(g)})"
                        if len(g) >= 25 else f"{'—':>8} (n={len(g)})")
        print(f"  {lab:30} {fila[0]:>16} {fila[1]:>16}")

    print("\n  Si las dos columnas se mueven igual, el historial es la dilución con")
    print("  otro nombre. Si el gradiente aparece DENTRO de cada columna, aporta aparte.")

    tickers = len({x["t"] for x in datos})
    print(f"\n  {tickers} tickers distintos · mediana de gaps previos por evento: "
          f"{statistics.median([x['n_previos'] for x in datos]):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
