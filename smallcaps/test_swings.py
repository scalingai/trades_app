#!/usr/bin/env python3
"""¿Cuántas oportunidades hay por día? Descomposición del día en swings.

**Pregunta de Agus mirando BJDX 2026-08-05:** "¿no ves acá varias oportunidades
por acción de precio?". Sí — y la forma de contestarlo es contarlas, no mirarlas.

`test_extremos.py` midió el recorrido del máximo al mínimo posterior: 57,3% de
mediana. Pero eso es UNA oportunidad, la más grande. Un día con tres bajadas del
20% separadas por rebotes ofrece 60 puntos que ese número no ve.

Acá el día se parte en swings con un umbral: mientras el precio siga bajando el
swing continúa; cuando rebota más de θ% desde el mínimo, el swing terminó y
empieza uno al alza. Es un zigzag, y θ es su único parámetro — se reporta en
grilla en vez de elegirse.

Lo que interesa es la diferencia entre **la bajada más grande** y **la suma de
todas las bajadas**: esa diferencia es exactamente la materia prima que una
estrategia de un solo trade por día deja sobre la mesa.

    python test_swings.py
    python test_swings.py --umbral 10
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def swings(bars, umbral):
    """Zigzag: lista de (dirección, desde, hasta, %) con reversión de `umbral`%.

    Un swing bajista sigue vivo mientras el precio haga mínimos nuevos; muere
    cuando rebota `umbral`% desde ese mínimo. El extremo se marca donde estuvo
    el mínimo, no donde se confirmó la reversión — por eso esto mide la
    OPORTUNIDAD disponible, no lo que capturaría una regla en vivo.
    """
    if len(bars) < 10:
        return []
    out = []
    dir_ = 0            # 0 sin definir, +1 subiendo, -1 bajando
    ext = bars[0][4]
    ini = bars[0]
    for b in bars[1:]:
        alto, bajo, c = b[2], b[3], b[4]
        if not c:
            continue
        if dir_ >= 0 and alto and alto > ext:
            ext, ini_ext = alto, b
            if dir_ == 0:
                dir_ = 1
            continue
        if dir_ <= 0 and bajo and bajo < ext:
            ext, ini_ext = bajo, b
            if dir_ == 0:
                dir_ = -1
            continue
        if dir_ == 1 and bajo and (1 - bajo / ext) * 100 >= umbral:
            out.append((1, ini, ext))
            dir_, ini, ext = -1, b, bajo
        elif dir_ == -1 and alto and (alto / ext - 1) * 100 >= umbral:
            out.append((-1, ini, ext))
            dir_, ini, ext = 1, b, alto
    return out


def analizar(dia, umbral):
    rth = [b for b in dia.bars if APERTURA_RTH <= hora(b) <= CIERRE_RTH]
    if len(rth) < 60:
        return None
    sw = swings(rth, umbral)
    if not sw:
        return None
    # Reconstruir los tramos con su magnitud: de un extremo al siguiente.
    tramos = []
    for (d1, _b1, e1), (_d2, _b2, e2) in zip(sw, sw[1:]):
        if not e1 or not e2:
            continue
        pct = (e1 / e2 - 1) * 100 if d1 == 1 else (e2 / e1 - 1) * 100
        tramos.append((d1, abs(pct)))
    bajadas = [p for d, p in tramos if d == 1]      # tras un máximo viene bajada
    subidas = [p for d, p in tramos if d == -1]
    if not bajadas:
        return None
    altos = [b[2] for b in rth if b[2]]
    bajos = [b[3] for b in rth if b[3]]
    return {
        "n_bajadas": len(bajadas),
        "mayor": max(bajadas),
        "suma": sum(bajadas),
        "mediana_swing": statistics.median(bajadas),
        "n_subidas": len(subidas),
        "rango": (max(altos) / min(bajos) - 1) * 100 if bajos else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Descomposición del día en swings")
    ap.add_argument("--min-expansion", type=float, default=100.0)
    args = ap.parse_args(argv)

    dias = [d for d in cargar()
            if (d.ratio_volumen or 0) >= 3
            and (d.expansion_pct or 0) >= args.min_expansion]

    print("=" * 92)
    print(f"  DESCOMPOSICIÓN EN SWINGS — {len(dias)} días de expansión >= "
          f"{args.min_expansion:.0f}%")
    print("  El umbral es el único parámetro; se reporta la grilla, no se elige uno.")
    print("=" * 92)
    print(f"\n  {'umbral':>8} {'n':>5} {'bajadas/día':>12} {'la mayor':>10} "
          f"{'SUMA':>9} {'suma÷mayor':>12} {'swing típico':>13}")
    print("  " + "-" * 76)

    guardado = {}
    for u in (3, 5, 8, 10, 15, 20):
        res = [analizar(d, u) for d in dias]
        res = [r for r in res if r]
        if len(res) < 30:
            continue
        guardado[u] = res
        print(f"  {(str(u)+'%'):>8} {len(res):>5} "
              f"{statistics.median(r['n_bajadas'] for r in res):>11.0f}  "
              f"{statistics.median(r['mayor'] for r in res):>9.1f}% "
              f"{statistics.median(r['suma'] for r in res):>8.1f}% "
              f"{statistics.median(r['suma']/r['mayor'] for r in res):>11.2f}x "
              f"{statistics.median(r['mediana_swing'] for r in res):>12.1f}%")

    if 10 in guardado:
        res = guardado[10]
        print("\n  CON UMBRAL DEL 10% — cuántos días ofrecen más de una bajada")
        from collections import Counter
        c = Counter(min(r["n_bajadas"], 6) for r in res)
        for k in sorted(c):
            lab = f"{k}+" if k == 6 else str(k)
            print(f"    {lab} bajada(s): {c[k]:>4} días ({100*c[k]/len(res):>3.0f}%)")

        print("\n  LO QUE DEJA SOBRE LA MESA UNA ESTRATEGIA DE UN SOLO TRADE")
        may = statistics.median(r["mayor"] for r in res)
        sm = statistics.median(r["suma"] for r in res)
        print(f"""
    la bajada más grande del día        {may:>6.1f}%
    la suma de TODAS las bajadas       {sm:>6.1f}%     ({sm/may:.1f}× más)

  Un trade por día tiene como techo la primera cifra, y sólo si lo agarra
  entero. La segunda es el techo de operar los swings. La diferencia —{sm-may:.0f}
  puntos de mediana— es lo que Agus está viendo en el gráfico y el motor no
  toma, porque abre una vez y sostiene.

  ADVERTENCIA QUE NO SE PUEDE OMITIR: el zigzag marca los extremos DONDE
  ESTUVIERON, no donde se confirmaron. En vivo, un swing del 10% se reconoce
  cuando ya rebotó 10%, así que de esos {sm:.0f} puntos una regla real captura una
  fracción. Es el techo de la oportunidad, no una promesa.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
