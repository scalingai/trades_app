#!/usr/bin/env python3
"""Segunda ronda: 3 señales de estructura ICT, y la combinación de las tres capas.

**Declarado como segunda ronda.** La lista de la primera estaba cerrada; agregar
señales después de ver resultados es lo que quedamos en no hacer. Esta lista se
cierra ANTES de correr, con las mismas reglas: cero parámetros, se reportan
todas, se exige replicación en los dos períodos.

Advertencia que no se resetea entre rondas: el riesgo de comparaciones
múltiples se ACUMULA. Van 8 señales de la primera ronda más 3 de esta.

Las tres:
  1. barrido del máximo PRE-MARKET que falló
  2. barrido del máximo del DÍA PREVIO que falló
  3. fair value gap bajista sin rellenar

Un "barrido fallido" es: superó el nivel después de las 09:30 y al corte volvió
a estar por debajo. Cero parámetros — el nivel lo pone el mercado, no nosotros.
(La versión con «rango de apertura» se descartó: obligaba a elegir 15 o 30
minutos, que es un parámetro disfrazado de convención.)

    python test_ict.py
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from datetime import date

import config
from massive.minutes import MinuteStore
from test_signals import APERTURA_RTH, señales

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def ict(bars, hora_corte: float, max_dia_previo: float | None) -> dict | None:
    def h(b):
        return b[0].hour + b[0].minute / 60.0

    antes = [b for b in bars if h(b) < hora_corte]
    if len(antes) < 20:
        return None
    precio = antes[-1][4]
    if not precio:
        return None

    pre = [b for b in antes if h(b) < APERTURA_RTH]
    rth = [b for b in antes if h(b) >= APERTURA_RTH]
    if not rth:
        return None

    # 1. Barrido del máximo pre-market que falló.
    max_pre = max((b[2] for b in pre if b[2]), default=None)
    barrio_pre = bool(max_pre and any(b[2] and b[2] > max_pre for b in rth))
    barrido_pre_fallido = bool(barrio_pre and precio < max_pre)

    # 2. Barrido del máximo del día previo que falló.
    barrido_prev_fallido = False
    if max_dia_previo:
        barrio = any(b[2] and b[2] > max_dia_previo for b in rth)
        barrido_prev_fallido = bool(barrio and precio < max_dia_previo)

    # 3. FVG bajista sin rellenar: en 3 barras consecutivas el mínimo de la
    # primera queda por encima del máximo de la tercera, y el precio no volvió
    # a entrar en ese hueco.
    fvg = False
    for a, b, c in zip(rth, rth[1:], rth[2:]):
        if a[3] and c[2] and a[3] > c[2]:
            # ¿alguien rellenó el hueco después?
            idx = rth.index(c)
            if not any(x[2] and x[2] >= a[3] for x in rth[idx + 1:]):
                fvg = True
                break

    return {
        "barrido_premarket_fallido": barrido_pre_fallido,
        "barrido_dia_previo_fallido": barrido_prev_fallido,
        "fvg_bajista_sin_rellenar": fvg,
    }


def _r(vals):
    return (statistics.median(vals), 100 * sum(1 for x in vals if x < 0) / len(vals), len(vals))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Segunda ronda: señales ICT + combinación")
    ap.add_argument("--hora", type=float, default=12.0)
    ap.add_argument("--corte", default="2025-08-17")
    ap.add_argument("--min-n", type=int, default=25)
    args = ap.parse_args(argv)

    store = MinuteStore()
    db = sqlite3.connect(config.bars_db_path())
    dil = {(t, d): x for t, d, x in db.execute(
        "SELECT ticker,d,dilution_12m_pct FROM event_structure "
        "WHERE dilution_12m_pct IS NOT NULL")}

    datos = []
    for t, d in store.conn.execute("SELECT ticker,d FROM minute_log WHERE status='ok'"):
        prev = db.execute(
            "SELECT h FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
            (t, d)).fetchone()
        bars = store.day_bars(t, date.fromisoformat(d))
        s = señales(bars, args.hora)
        i = ict(bars, args.hora, prev[0] if prev else None)
        if not s or not i:
            continue
        datos.append({**s, **i, "_p": "P1" if d < args.corte else "P2",
                      "_dil": dil.get((t, d))})

    print("=" * 86)
    print(f"  SEGUNDA RONDA — 3 señales ICT · corte {int(args.hora):02d}:00 · n={len(datos)}")
    print("  Lista cerrada antes de correr. El riesgo de comparaciones múltiples")
    print("  se ACUMULA con la primera ronda (van 11 señales en total).")
    print("=" * 86)

    base = [d["_ret"] for d in datos]
    if len(base) < args.min_n * 2:
        print(f"\n  muestra insuficiente ({len(base)})")
        store.close()
        return 1
    m, neg, n = _r(base)
    print(f"\n  LÍNEA DE BASE  n={n}  mediana={m:+.2f}%  baja el {neg:.0f}%\n")

    print(f"  {'señal ICT':38} {'n sí':>5} {'med sí':>8} {'Δ':>7} {'P1':>7} {'P2':>7}")
    print("  " + "-" * 76)
    for k, lab in (("barrido_premarket_fallido", "barrido del máximo pre-market falló"),
                   ("barrido_dia_previo_fallido", "barrido del máximo día previo falló"),
                   ("fvg_bajista_sin_rellenar", "FVG bajista sin rellenar")):
        si = [d["_ret"] for d in datos if d[k]]
        no = [d["_ret"] for d in datos if not d[k]]
        if len(si) < args.min_n or len(no) < args.min_n:
            print(f"  {lab:38} {len(si):>5}  (insuficiente)")
            continue
        ds = []
        for p in ("P1", "P2"):
            a = [d["_ret"] for d in datos if d[k] and d["_p"] == p]
            b = [d["_ret"] for d in datos if not d[k] and d["_p"] == p]
            ds.append(statistics.median(a) - statistics.median(b)
                      if len(a) >= 15 and len(b) >= 15 else None)
        f = lambda x: f"{x:+.1f}" if x is not None else "  —"  # noqa: E731
        print(f"  {lab:38} {len(si):>5} {statistics.median(si):>+7.2f}% "
              f"{statistics.median(si)-statistics.median(no):>+6.1f} "
              f"{f(ds[0]):>7} {f(ds[1]):>7}")

    print("\n  LAS TRES CAPAS COMBINADAS")
    print(f"  {'capas':52} {'n':>5} {'mediana':>9}")
    print("  " + "-" * 68)
    capas = [
        ("sin filtro", lambda d: True),
        ("técnico: debajo de la apertura", lambda d: d["bajo_apertura"]),
        ("+ fundamental: diluyó >50%", lambda d: d["bajo_apertura"] and (d["_dil"] or 0) > 50),
        ("+ ICT: barrido pre-market fallido",
         lambda d: d["bajo_apertura"] and (d["_dil"] or 0) > 50 and d["barrido_premarket_fallido"]),
    ]
    for lab, f in capas:
        g = [d["_ret"] for d in datos if f(d)]
        if len(g) < 10:
            print(f"  {lab:52} {len(g):>5}   n insuficiente para medir")
            continue
        print(f"  {lab:52} {len(g):>5} {statistics.median(g):>+8.2f}%")

    print("\n  Si la última fila dice 'insuficiente', no es un resultado negativo:")
    print("  es que combinar tres capas deja muy pocos días y hace falta más muestra.")
    store.close()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
