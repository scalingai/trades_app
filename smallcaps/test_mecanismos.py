#!/usr/bin/env python3
"""Filtros con MECANISMO, medidos todos igual sobre la sesión.

**Por qué existe.** La estrategia actual se armó a fuerza de medir: expansión,
swings, liquidez, stop estructural. Todo funciona, pero ninguno de esos cuatro
es un mecanismo — son propiedades del movimiento del precio, y un patrón de
precio que funciona sin causa conocida es un patrón que puede dejar de funcionar
sin aviso.

La tesis original del proyecto SÍ tenía mecanismo y quedó fuera del sistema:
**la empresa vende acciones contra la fuerza**. El ATM que se activa, el shelf
que quedó efectivo, el reverse split que resetea el precio para volver a diluir.
Eso es un shock de oferta real, no una correlación.

Acá cada filtro se declara con su mecanismo ANTES de medirlo, y se mide igual
que todos los demás: como filtro sobre la jornada, con el mismo riesgo, el mismo
costo y el mismo motor. Se reportan todos, incluidos los que no aportan.

Los datos de estructura son point-in-time (`event_structure`), así que el filtro
usa lo que se sabía ese día.

    python test_mecanismos.py
    SMALLCAPS_CENSO=1 python test_mecanismos.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys

import config
from dias import cargar
from sesion import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"

# (etiqueta, mecanismo declarado, predicado sobre la ficha del día)
# El mecanismo se escribe ANTES de ver el número. Si no se puede escribir uno,
# el filtro no entra: eso es lo que separa esto de probar columnas al azar.
MECANISMOS = [
    ("dilución 12m > 100%",
     "la empresa YA demostró que emite papel; el que corre lo vende",
     lambda f: (f.get("dilution_12m_pct") or -999) > 100),
    ("dilución 12m > 25%",
     "misma tesis, umbral más laxo",
     lambda f: (f.get("dilution_12m_pct") or -999) > 25),
    ("reverse split en 12m",
     "diluidor serial: el split resetea el precio para poder volver a emitir",
     lambda f: (f.get("reverse_splits_12m") or 0) > 0),
    ("shelf efectivo",
     "el registro está habilitado: puede vender mañana sin trámite",
     lambda f: bool(f.get("shelf_effective"))),
    ("runway < 6 meses",
     "se queda sin caja: tiene que emitir, no es opcional",
     lambda f: 0 < (f.get("runway_months") or 999) < 6),
    ("pricing en los últimos 90 días",
     "ya está vendiendo AHORA, no es capacidad sino conducta en curso",
     lambda f: 0 <= (f.get("days_since_last_pricing") or 9999) <= 90),
    ("≥3 8-K dilutivos 12m",
     "cadencia alta de operaciones dilutivas fuera de registro (PIPEs, notas)",
     lambda f: (f.get("dilutive_8k_12m") or 0) >= 3),
    ("float < 10M acciones",
     "la oferta se satura rápido; el desequilibrio es más violento en los dos sentidos",
     lambda f: 0 < (f.get("shares_outstanding") or 9e12) < 10e6),
    ("biotech",
     "el binario regulatorio ya se resolvió: el catalizador no se repite mañana",
     lambda f: bool(f.get("biotech"))),
    ("china / offshore",
     "CONTRA-filtro: cola derecha letal, buena mediana y media positiva",
     lambda f: bool(f.get("china"))),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Filtros con mecanismo")
    ap.add_argument("--riesgo", type=float, default=50.0)
    ap.add_argument("--min-n", type=int, default=40)
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    est = {}
    for r in db.execute(
        "SELECT ticker,d,dilution_12m_pct,reverse_splits_12m,shelf_effective,"
        "runway_months,days_since_last_pricing,dilutive_8k_12m,shares_outstanding "
        "FROM event_structure"
    ):
        est[(r[0], r[1])] = dict(zip(
            ("dilution_12m_pct", "reverse_splits_12m", "shelf_effective",
             "runway_months", "days_since_last_pricing", "dilutive_8k_12m",
             "shares_outstanding"), r[2:]))
    db.close()

    ruta = config.data_dir() / "fichas_empresa.json"
    fichas = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}

    filas = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        j = jornada(dia, riesgo_dia=args.riesgo, riesgo_trade=args.riesgo / 3,
                    objetivo=0, stop_pct=15, costo_accion=0.04, max_trades=10,
                    min_liquidez=2.5e5, modo="swing", stop_modo="estructural",
                    colchon=1.0, tope_stop=30)
        if not j:
            continue
        f = dict(est.get((dia.ticker, dia.d)) or {})
        fe = fichas.get(dia.ticker) or {}
        f["biotech"] = fe.get("biotech")
        f["china"] = fe.get("china")
        f["_cobertura"] = bool(est.get((dia.ticker, dia.d)))
        filas.append((j, f))

    base = [j["pnl"] for j, _ in filas]
    cob = 100 * sum(1 for _, f in filas if f["_cobertura"]) / max(1, len(filas))

    print("=" * 100)
    print(f"  FILTROS CON MECANISMO — {len(filas)} jornadas · "
          f"{cob:.0f}% con ficha de estructura point-in-time")
    print("  El mecanismo se declara ANTES del número. Sin mecanismo, el filtro no entra.")
    print("=" * 100)
    print(f"\n  LÍNEA DE BASE (sin filtro)   n={len(base)}  "
          f"media ${statistics.mean(base):+.2f}  mediana ${statistics.median(base):+.2f}  "
          f"positivos {100*sum(1 for x in base if x>0)/len(base):.0f}%")

    print(f"\n  {'filtro':30} {'n':>5} {'media':>9} {'Δ vs base':>10} {'mediana':>9} "
          f"{'pos':>5} {'P1':>8} {'P2':>8}")
    print("  " + "-" * 92)
    resultados = []
    for lab, mec, pred in MECANISMOS:
        g = [(j, f) for j, f in filas if pred(f)]
        v = [j["pnl"] for j, _ in g]
        if len(v) < args.min_n:
            print(f"  {lab:30} {len(v):>5}   (n insuficiente)")
            continue
        per = []
        for p in ("P1", "P2"):
            h = [j["pnl"] for j, _ in g if j["per"] == p]
            per.append(f"{statistics.mean(h):+7.2f}" if len(h) >= 20 else "      —")
        m = statistics.mean(v)
        print(f"  {lab:30} {len(v):>5} {m:>+8.2f} {m-statistics.mean(base):>+9.2f} "
              f"{statistics.median(v):>+8.2f} "
              f"{100*sum(1 for x in v if x>0)/len(v):>4.0f}% {per[0]} {per[1]}")
        resultados.append((lab, mec, m - statistics.mean(base), len(v)))

    print("\n  LOS MECANISMOS, ORDENADOS POR APORTE")
    for lab, mec, d, n in sorted(resultados, key=lambda x: -x[2]):
        signo = "+" if d > 0 else " "
        print(f"   {signo} {lab:28} {d:>+7.2f}  (n={n})")
        print(f"       {mec}")

    print("""
  Un filtro con mecanismo que no aporta es tan informativo como uno que aporta:
  descarta la tesis, no solo el filtro. Y un filtro que aporta SIN mecanismo
  declarado no entra en esta tabla por construcción — es la única defensa contra
  probar columnas hasta que una dé.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
