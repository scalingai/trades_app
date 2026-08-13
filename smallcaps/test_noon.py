#!/usr/bin/env python3
"""La prueba honesta: al mediodía, ¿se puede saber si se va a desinflar?

**La regla que hace válido esto:** cada feature se calcula usando SOLO barras
anteriores a las 12:00. Nada del futuro. El resultado que se mide es lo que
pasó DESPUÉS — de las 12:00 al cierre de la sesión regular.

Es la diferencia entre la observación anterior ("las que cayeron habían techado
temprano", que es retrospectiva) y una regla operable ("a las 11:59 puedo
distinguirlas").

    python test_noon.py
    python test_noon.py --hora 11
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from datetime import date

import config
from massive.minutes import MinuteStore

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def features(bars, hora_corte: float):
    """Features al corte + resultado posterior. Ninguna mira más allá del corte."""
    def h(b):
        return b[0].hour + b[0].minute / 60.0

    antes = [b for b in bars if h(b) < hora_corte]
    despues = [b for b in bars if hora_corte <= h(b) <= 16.0]
    if len(antes) < 20 or len(despues) < 10:
        return None

    precio = antes[-1][4]
    if not precio:
        return None

    altos = [(b[2], h(b)) for b in antes if b[2]]
    if not altos:
        return None
    maximo, hora_max = max(altos)

    vol_total = sum(b[5] or 0 for b in antes) or 1
    vol_hasta_max = sum(b[5] or 0 for b in antes if h(b) <= hora_max)
    pv = sum((b[4] or 0) * (b[5] or 0) for b in antes)
    vwap = pv / vol_total if vol_total else precio

    cierre = despues[-1][4]
    if not cierre:
        return None

    return {
        # --- solo información previa al corte ---
        "hora_max": hora_max,
        "frac_vol_antes_max": vol_hasta_max / vol_total,
        "desde_max_pct": (precio / maximo - 1.0) * 100.0,
        "vs_vwap_pct": (precio / vwap - 1.0) * 100.0,
        "horas_desde_max": hora_corte - hora_max,
        # --- resultado posterior ---
        "ret_post": (cierre / precio - 1.0) * 100.0,
    }


def bucket(datos, key, cortes, labels, titulo):
    print(f"\n  {titulo}")
    for i, lab in enumerate(labels):
        lo = cortes[i - 1] if i else -1e18
        hi = cortes[i] if i < len(cortes) else 1e18
        g = [d["ret_post"] for d in datos if lo <= d[key] < hi]
        if len(g) < 8:
            print(f"    {lab:30} n={len(g):>4}  (insuficiente)")
            continue
        neg = sum(1 for x in g if x < 0)
        print(f"    {lab:30} n={len(g):>4}  mediana={statistics.median(g):>7.2f}%  "
              f"media={statistics.mean(g):>7.2f}%  baja el {100*neg/len(g):>3.0f}%")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Test: predicción al mediodía")
    ap.add_argument("--hora", type=float, default=12.0, help="hora ET de corte")
    args = ap.parse_args(argv)

    store = MinuteStore()
    eventos = store.conn.execute(
        "SELECT ticker, d FROM minute_log WHERE status='ok'").fetchall()

    datos = []
    for t, d in eventos:
        bars = store.day_bars(t, date.fromisoformat(d))
        f = features(bars, args.hora)
        if f:
            datos.append(f)

    print("=" * 78)
    print(f"  ¿SE PUEDE PREDECIR A LAS {int(args.hora):02d}:00 ET?")
    print(f"  n = {len(datos)} eventos  ·  features solo con datos ANTERIORES al corte")
    print("=" * 78)

    if len(datos) < 30:
        print(f"\n  muestra insuficiente ({len(datos)}). Esperar más descarga.")
        store.close()
        return 1

    todos = [d["ret_post"] for d in datos]
    neg = sum(1 for x in todos if x < 0)
    print(f"\n  LÍNEA DE BASE (sin ninguna regla): mediana={statistics.median(todos):>7.2f}%  "
          f"media={statistics.mean(todos):>7.2f}%  baja el {100*neg/len(todos):.0f}%")
    print("  Cualquier feature tiene que MEJORAR esto para valer algo.")

    bucket(datos, "hora_max", [8, 10, 11],
           ["máximo antes de 08:00", "máximo 08:00-10:00",
            "máximo 10:00-11:00", "máximo después de 11:00"],
           "A) ¿A qué hora fue el máximo hasta el corte?")

    bucket(datos, "frac_vol_antes_max", [0.25, 0.60],
           ["<25% del volumen antes del máx", "25-60%", ">60%"],
           "B) ¿Cuánto volumen había pasado cuando hizo el máximo?")

    bucket(datos, "desde_max_pct", [-30, -15, -5],
           ["ya cayó >30% del máximo", "cayó 15-30%",
            "cayó 5-15%", "está a menos de 5% del máximo"],
           "C) ¿Qué tan lejos del máximo está al corte?")

    bucket(datos, "vs_vwap_pct", [-5, 0, 10],
           ["muy por debajo del VWAP", "algo debajo del VWAP",
            "hasta 10% sobre VWAP", ">10% sobre VWAP"],
           "D) ¿Está arriba o abajo del VWAP?")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
