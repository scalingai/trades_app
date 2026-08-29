#!/usr/bin/env python3
"""La anatomía del día medida desde los EXTREMOS, no desde el reloj.

**Objeción de Agus, y es de fondo.** Todo lo medido hasta acá entra a una hora
fija: 09:30, 10:00, el mediodía. Eso contesta "¿qué pasa si entro a las diez?"
pero no "¿dónde está la oportunidad?". Un papel que hace su máximo a las 11:40 y
otro que lo hace a las 14:10 tienen la misma forma y quedan en baldes distintos
solo por el reloj.

Acá el día se describe por su estructura:

  · cuándo se hace el máximo y cuándo el mínimo
  · cuánto hay entre uno y otro — el recorrido que se podría capturar
  · qué fracción del rango queda DESPUÉS del máximo
  · cuánto tarda en recorrerlo

Nada de esto es operable tal cual: el máximo se conoce cuando ya pasó. Sirve
para saber **cuánta oportunidad hay y dónde vive**, que es el techo contra el
cual comparar cualquier estrategia. Si el recorrido máximo-a-mínimo es del 40% y
la estrategia captura 3%, el problema no es el edge: es la captura.

    python test_extremos.py
    python test_extremos.py --min-expansion 100
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def anatomia(dia):
    """Los extremos del día y lo que hay entre ellos."""
    rth = [b for b in dia.bars if APERTURA_RTH <= hora(b) <= CIERRE_RTH]
    if len(rth) < 60:
        return None
    altos = [(b[2], hora(b), i) for i, b in enumerate(rth) if b[2]]
    bajos = [(b[3], hora(b), i) for i, b in enumerate(rth) if b[3]]
    if not altos or not bajos:
        return None
    hi, h_hi, i_hi = max(altos)
    lo, h_lo, i_lo = min(bajos)

    # El mínimo POSTERIOR al máximo: es el recorrido que un short podría tomar.
    post = [(b[3], hora(b), i) for i, b in enumerate(rth) if i > i_hi and b[3]]
    lo_post, h_lo_post = (min(post)[0], min(post)[1]) if post else (None, None)

    o, c = rth[0][1], rth[-1][4]
    return {
        "ticker": dia.ticker, "d": dia.d,
        "hora_max": h_hi, "hora_min": h_lo,
        "max": hi, "min": lo, "open": o, "close": c,
        "rango": (hi / lo - 1) * 100 if lo else None,
        # el recorrido del short perfecto: del máximo al mínimo posterior
        "caida": (hi / lo_post - 1) * 100 if lo_post else None,
        "minutos_caida": (h_lo_post - h_hi) * 60 if h_lo_post else None,
        "max_antes_del_min": h_hi < h_lo,
        # cuánto del rango queda después del máximo
        "frac_post_max": ((hi - lo_post) / (hi - lo) * 100)
        if (lo_post and hi > lo) else None,
        "expansion": dia.expansion_pct,
    }


def dist(vals, lab, suf="%"):
    v = sorted(x for x in vals if x is not None)
    if len(v) < 20:
        print(f"  {lab:32} (n={len(v)} insuficiente)")
        return
    q = lambda p: v[int(p * len(v))]  # noqa: E731
    print(f"  {lab:32} p10 {q(.10):>7.1f}{suf}  mediana {statistics.median(v):>7.1f}{suf}  "
          f"p75 {q(.75):>7.1f}{suf}  p90 {q(.90):>7.1f}{suf}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Anatomía del día desde los extremos")
    ap.add_argument("--min-expansion", type=float, default=100.0)
    args = ap.parse_args(argv)

    filas = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3:
            continue
        if (dia.expansion_pct or 0) < args.min_expansion:
            continue
        a = anatomia(dia)
        if a:
            filas.append(a)

    print("=" * 92)
    print(f"  ANATOMÍA DEL DÍA — {len(filas)} días de expansión >= {args.min_expansion:.0f}%")
    print("  Nada de esto es operable: el máximo se conoce cuando ya pasó.")
    print("  Es el TECHO contra el cual comparar cualquier estrategia.")
    print("=" * 92)

    print("\n  CUÁNTA OPORTUNIDAD HAY")
    dist([f["rango"] for f in filas], "rango del día (máx/mín)")
    dist([f["caida"] for f in filas], "del máximo al mínimo POSTERIOR")
    dist([f["frac_post_max"] for f in filas], "% del rango que queda tras el máximo")

    print("\n  CUÁNDO PASA")
    for lab, k in (("hora del máximo", "hora_max"), ("hora del mínimo", "hora_min")):
        v = sorted(f[k] for f in filas)
        q = lambda p: v[int(p * len(v))]  # noqa: E731
        fmt = lambda h: f"{int(h):02d}:{int((h % 1) * 60):02d}"  # noqa: E731
        print(f"  {lab:32} p10 {fmt(q(.10))}  mediana {fmt(statistics.median(v))}  "
              f"p75 {fmt(q(.75))}  p90 {fmt(q(.90))}")
    dist([f["minutos_caida"] for f in filas], "minutos del máximo al mínimo", " min")

    n_ord = sum(1 for f in filas if f["max_antes_del_min"])
    print(f"\n  el máximo llega ANTES que el mínimo en {n_ord} de {len(filas)} "
          f"({100*n_ord/len(filas):.0f}%)")

    print("\n  DÓNDE SE HACE EL MÁXIMO, Y QUÉ QUEDA DESPUÉS")
    print(f"  {'el máximo del día se hace':28} {'n':>5} {'caída posterior':>16} "
          f"{'% del rango':>13}")
    print("  " + "-" * 66)
    for lo, hi, lab in ((9.5, 10.0, "09:30-10:00"), (10.0, 11.0, "10:00-11:00"),
                        (11.0, 13.0, "11:00-13:00"), (13.0, 16.01, "después de 13:00")):
        g = [f for f in filas if lo <= f["hora_max"] < hi]
        if len(g) < 15:
            print(f"  {lab:28} {len(g):>5}   (insuficiente)")
            continue
        c = [f["caida"] for f in g if f["caida"] is not None]
        fr = [f["frac_post_max"] for f in g if f["frac_post_max"] is not None]
        print(f"  {lab:28} {len(g):>5} {statistics.median(c):>15.1f}% "
              f"{statistics.median(fr):>12.0f}%")

    print("\n  EL TECHO CONTRA LA REALIDAD")
    c = statistics.median([f["caida"] for f in filas if f["caida"]])
    print(f"""
  El short perfecto —vender el máximo exacto, cubrir el mínimo posterior— captura
  {c:.1f}% de mediana. Las estrategias medidas capturan entre 1% y 10%.

  O sea que el problema NO es que no haya movimiento: hay {c:.0f} puntos de
  mediana sobre la mesa. El problema es la captura, y la captura se define por
  dónde entrás y cuánto nominal tenés puesto — no por el filtro.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
