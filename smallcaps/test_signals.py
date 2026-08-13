#!/usr/bin/env python3
"""Las 8 señales de CERO parámetros, evaluadas de a una.

Cero parámetros significa que no hay ningún número que yo pueda elegir. Cada
señal es un hecho binario: pasó o no pasó. Sin umbral que tocar, no se puede
ajustar al ruido ni sin querer.

Reglas acordadas antes de correr esto:
  1. Lista CERRADA. No se agregan señales después de ver resultados.
  2. Se reportan TODAS, incluidas las que fallan.
  3. Se prueban de a UNA. Combinar viene después, solo con las que sobrevivan.
  4. Tiene que replicar en los dos períodos. Una señal que anda en 2025 y no en
     2026 no existe.

Todas se calculan con barras ANTERIORES al corte. El resultado que se mide es
lo que pasó después, del corte al cierre de la sesión regular.

    python test_signals.py
    python test_signals.py --hora 11
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

# La apertura de la sesión regular. No es un parámetro elegido: es la hora a la
# que abre el mercado.
APERTURA_RTH = 9.5
# Duración de una pausa LULD, fijada por regla del mercado, no por nosotros.
MINUTOS_HALT = 5


def señales(bars, hora_corte: float) -> dict | None:
    def h(b):
        return b[0].hour + b[0].minute / 60.0

    antes = [b for b in bars if h(b) < hora_corte]
    despues = [b for b in bars if hora_corte <= h(b) <= 16.0]
    if len(antes) < 20 or len(despues) < 10:
        return None

    precio = antes[-1][4]
    cierre = despues[-1][4]
    if not precio or not cierre:
        return None

    t0, t1 = h(antes[0]), h(antes[-1])
    medio = (t0 + t1) / 2.0  # mitad del tiempo transcurrido, no un umbral elegido
    prim = [b for b in antes if h(b) < medio]
    seg = [b for b in antes if h(b) >= medio]
    if not prim or not seg:
        return None

    apertura_rth = next((b[1] for b in antes if h(b) >= APERTURA_RTH), antes[0][1])

    altos = [(b[2], h(b)) for b in antes if b[2]]
    max_precio, hora_max = max(altos)
    vols = [(b[5] or 0, h(b)) for b in antes]
    _, hora_climax = max(vols)

    vol_total = sum(v for v, _ in vols) or 1
    vwap = sum((b[4] or 0) * (b[5] or 0) for b in antes) / vol_total

    # Halt: hueco de >=5 minutos consecutivos sin barra dentro de la sesión
    # regular. Los 5 minutos salen de la regla LULD, no de una elección nuestra.
    rth = [b for b in antes if h(b) >= APERTURA_RTH]
    hubo_halt = False
    for a, b in zip(rth, rth[1:]):
        if (b[0] - a[0]).total_seconds() / 60.0 >= MINUTOS_HALT:
            hubo_halt = True
            break

    estuvo_arriba = any((b[4] or 0) > vwap for b in prim)

    return {
        "bajo_vwap": precio < vwap,
        "perdio_vwap": estuvo_arriba and precio < vwap,
        "max_precio_1a_mitad": hora_max < medio,
        "max_en_premarket": hora_max < APERTURA_RTH,
        "climax_vol_1a_mitad": hora_climax < medio,
        "volumen_decreciente": sum(b[5] or 0 for b in seg) < sum(b[5] or 0 for b in prim),
        "densidad_cayendo": len(seg) < len(prim),
        "bajo_apertura": precio < (apertura_rth or precio),
        "_ret": (cierre / precio - 1.0) * 100.0,
    }


_NOMBRES = [
    ("bajo_vwap", "precio debajo del VWAP"),
    ("perdio_vwap", "estuvo arriba del VWAP y lo perdió"),
    ("max_precio_1a_mitad", "el máximo de precio fue en la 1ª mitad"),
    ("max_en_premarket", "el máximo fue en pre-market"),
    ("climax_vol_1a_mitad", "el pico de volumen fue en la 1ª mitad"),
    ("volumen_decreciente", "el volumen viene cayendo"),
    ("densidad_cayendo", "opera en menos minutos que antes"),
    ("bajo_apertura", "precio debajo de la apertura"),
]


def _resumen(vals):
    if not vals:
        return None
    return statistics.median(vals), 100 * sum(1 for x in vals if x < 0) / len(vals), len(vals)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Las 8 señales de cero parámetros")
    ap.add_argument("--hora", type=float, default=12.0)
    ap.add_argument("--corte", default="2025-08-17")
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args(argv)

    store = MinuteStore()
    datos = []
    for t, d in store.conn.execute("SELECT ticker,d FROM minute_log WHERE status='ok'"):
        s = señales(store.day_bars(t, date.fromisoformat(d)), args.hora)
        if s:
            s["_periodo"] = "P1" if d < args.corte else "P2"
            datos.append(s)

    print("=" * 88)
    print(f"  8 SEÑALES DE CERO PARÁMETROS · corte {int(args.hora):02d}:00 ET · n={len(datos)}")
    print("  Se reportan TODAS, incluidas las que fallan.")
    print("=" * 88)

    base = [d["_ret"] for d in datos]
    if len(base) < args.min_n * 2:
        print(f"\n  muestra insuficiente ({len(base)}). Esperar más descarga.")
        store.close()
        return 1
    m, neg, n = _resumen(base)
    print(f"\n  LÍNEA DE BASE   n={n}  mediana={m:+.2f}%  baja el {neg:.0f}%")
    print("  Una señal sirve solo si su lado 'SÍ' mejora esto Y replica en P1 y P2.\n")

    print(f"  {'señal':38} {'n sí':>5} {'med sí':>8} {'med no':>8} {'Δ':>7} {'P1':>7} {'P2':>7}")
    print("  " + "-" * 84)
    for key, label in _NOMBRES:
        si = [d["_ret"] for d in datos if d[key]]
        no = [d["_ret"] for d in datos if not d[key]]
        if len(si) < args.min_n or len(no) < args.min_n:
            print(f"  {label:38} {len(si):>5}  (muestra insuficiente)")
            continue
        msi, _, _ = _resumen(si)
        mno, _, _ = _resumen(no)
        deltas = []
        for p in ("P1", "P2"):
            a = [d["_ret"] for d in datos if d[key] and d["_periodo"] == p]
            b = [d["_ret"] for d in datos if not d[key] and d["_periodo"] == p]
            deltas.append(statistics.median(a) - statistics.median(b)
                          if len(a) >= args.min_n and len(b) >= args.min_n else None)
        fmt = lambda x: f"{x:+.1f}" if x is not None else "  —"  # noqa: E731
        print(f"  {label:38} {len(si):>5} {msi:>+7.2f}% {mno:>+7.2f}% "
              f"{msi-mno:>+6.1f} {fmt(deltas[0]):>7} {fmt(deltas[1]):>7}")

    print("\n  Δ negativo = la señal identifica las que caen más.")
    print("  Sirve solo si Δ es negativo Y P1 y P2 coinciden en signo.")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
