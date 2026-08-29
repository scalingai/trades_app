#!/usr/bin/env python3
"""El radar sobre TODOS los eventos diarios, no solo los que tienen minutos.

**Por qué existe.** `radar.py` solo puede mirar los días con barras de minuto
bajadas, y eso dejó el resultado en n=39 — el reparo más serio que tiene. Pero
cuatro de los cinco filtros no necesitan minutos: precio, gap, float e historial
salen de las barras diarias y de EDGAR, que están para los 87.943 eventos.

La sustitución y su costo: el filtro de **volumen pre-market ≥ 3M acciones** se
reemplaza por **volumen en dólares del día**. No es lo mismo y hay que decirlo:
el volumen pre-market es observable a las 09:30 y el del día no lo es. Acá se
usa para SELECCIONAR la población histórica, no como criterio de entrada — el
mismo rol que tenía `range_pct` en la muestra vieja, con el mismo reparo. La
versión observable de este filtro vive en `radar.py` y necesita los minutos.

Lo que sí gana: n de 39 a 173, y la posibilidad de partir por período.

    python radar_historico.py
    python radar_historico.py --min-gap 50 --float-max 20e6
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

import config
from radar import _FICHAS, _cargar_fichas, ficha_empresa

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"


def historial_completo(db, *, min_gap=20.0):
    """Tasa de fallo previa por (ticker, fecha), point-in-time."""
    previos = defaultdict(lambda: [0, 0])
    out = {}
    for t, d, intra in db.execute(
        "SELECT ticker, d, intraday_pct FROM events WHERE gap_pct >= ? "
        "AND intraday_pct IS NOT NULL ORDER BY ticker, d", (min_gap,)
    ):
        n, fall = previos[t]
        out[(t, d)] = (100.0 * fall / n, n) if n else (None, 0)
        previos[t] = [n + 1, fall + (1 if intra < 0 else 0)]
    return out


def resumen(vals, lab, ancho=38):
    if len(vals) < 8:
        print(f"  {lab:{ancho}} n={len(vals):>4}   (insuficiente)")
        return None
    m = statistics.median(vals)
    print(f"  {lab:{ancho}} n={len(vals):>4}  mediana {m:>+7.2f}%  "
          f"media {statistics.mean(vals):>+7.2f}%  cae {100*sum(1 for x in vals if x<0)/len(vals):>3.0f}%")
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Radar sobre el universo diario completo")
    ap.add_argument("--precio-min", type=float, default=0.70)
    ap.add_argument("--precio-max", type=float, default=5.00)
    ap.add_argument("--min-gap", type=float, default=70.0)
    ap.add_argument("--float-max", type=float, default=10e6)
    ap.add_argument("--min-dollar-vol", type=float, default=1e6)
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())
    hist = historial_completo(db)

    filas = db.execute(
        "SELECT e.ticker, e.d, e.open, e.gap_pct, e.intraday_pct, e.dollar_volume, "
        "       s.shares_outstanding, s.dilution_12m_pct, s.reverse_splits_12m "
        "FROM events e LEFT JOIN event_structure s "
        "  ON s.ticker = e.ticker AND s.d = e.d "
        "WHERE e.intraday_pct IS NOT NULL AND e.open IS NOT NULL "
        "  AND e.dollar_volume >= ?", (args.min_dollar_vol,)).fetchall()

    embudo = Counter()
    candidatos, poblacion = [], []
    for t, d, o, gap, intra, _dv, acc, dil, rs in filas:
        poblacion.append(intra)
        pasos = {
            "precio": args.precio_min <= o <= args.precio_max,
            "gap": gap is not None and gap >= args.min_gap,
            "float": bool(acc and acc <= args.float_max),
        }
        for k, v in pasos.items():
            if not v:
                embudo[k] += 1
        if all(pasos.values()):
            h, n_h = hist.get((t, d), (None, 0))
            candidatos.append({"t": t, "d": d, "intra": intra, "gap": gap,
                               "precio": o, "acc": acc, "dil": dil, "rs": rs,
                               "hist": h, "n_hist": n_h,
                               "per": "P1" if d < CORTE_PERIODO else "P2"})

    # Ficha de EDGAR solo para los que sobrevivieron: 130 tickers, no 32.000.
    fichas = _cargar_fichas()
    tickers = sorted({c["t"] for c in candidatos})
    faltan = [t for t in tickers if t not in fichas]
    if faltan:
        print(f"  fichando {len(faltan)} tickers en EDGAR…", flush=True)
    for t in tickers:
        f = ficha_empresa(t, fichas)
        for c in candidatos:
            if c["t"] == t:
                c["china"], c["biotech"] = f["china"], f["biotech"]
    _FICHAS.write_text(json.dumps(fichas), encoding="utf-8")

    print("=" * 92)
    print("  RADAR SOBRE EL UNIVERSO DIARIO COMPLETO")
    print(f"  ${args.precio_min:.2f}-${args.precio_max:.2f} · gap >= {args.min_gap:.0f}% · "
          f"float <= {args.float_max/1e6:.0f}M · vol$ >= ${args.min_dollar_vol/1e6:.0f}M")
    print(f"  {len(filas):,} eventos evaluados → {len(candidatos)} candidatos")
    print("=" * 92)

    print("\n  DÓNDE SE CAEN")
    for k, v in embudo.most_common():
        print(f"    no pasa {k:10} {v:>7,}")

    print("\n  RETORNO APERTURA → CIERRE")
    resumen(poblacion, "toda la población de eventos")
    resumen([c["intra"] for c in candidatos], "CANDIDATOS")
    print()
    for lab, f in (
        ("  + historial de fallo >= 60%", lambda c: (c["hist"] or 0) >= 60),
        ("  + historial >= 60% y n>=3", lambda c: (c["hist"] or 0) >= 60 and c["n_hist"] >= 3),
        ("  + dilución 12m > 100%", lambda c: (c["dil"] or 0) > 100),
        ("  + reverse split en 12m", lambda c: (c["rs"] or 0) > 0),
        ("  + empresa china", lambda c: c.get("china")),
        ("  + biotech", lambda c: c.get("biotech")),
    ):
        resumen([c["intra"] for c in candidatos if f(c)], lab)

    print("\n  REPLICACIÓN")
    for per in ("P1", "P2"):
        resumen([c["intra"] for c in candidatos if c["per"] == per], f"  {per}")

    print("\n  COLA — lo que decide si sobrevivís")
    v = sorted(c["intra"] for c in candidatos)
    if v:
        print(f"    peor (para el short) {v[-1]:>+8.1f}%   ·   p90 {v[int(.9*len(v))]:>+7.1f}%")
        print(f"    media sin el 5% superior: "
              f"{statistics.mean(v[:int(.95*len(v))]):+.2f}%")

    print("\n  Sustitución declarada: el filtro de volumen PRE-MARKET del protocolo")
    print("  se reemplazó por volumen en dólares del día, que NO es observable a las")
    print("  09:30. Sirve para seleccionar la población histórica, no para entrar.")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
