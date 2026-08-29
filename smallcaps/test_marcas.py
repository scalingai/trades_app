#!/usr/bin/env python3
"""Mide las marcas a mano contra lo que pasó después.

**La única forma honesta de saber si la capa discrecional aporta.** El sistema
mide los features que elegí yo; lo que ve un operador mirando el gráfico no está
en ninguna columna. Marcar y después medir es la manera de convertir eso en un
dato en vez de una discusión.

Cada marca se evalúa por lo que pasó DESPUÉS de ella: a +15, +30 y +60 minutos,
y hasta el cierre de la sesión regular. Para un `entrada_short` gana si el
precio bajó; para un `entrada_long`, si subió.

**Lo que este script NO puede contestar todavía:** si el criterio del operador
es mejor que el del motor. Para eso hacen falta marcas en días que el motor SÍ
operó y en días que descartó, y suficientes de cada uno. Con menos de 40 marcas
cualquier diferencia es ruido — el script lo dice en vez de esconderlo.

    python test_marcas.py
    python test_marcas.py --ticker AUUD
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from chavineta import operar
from dias import CIERRE_RTH, cargar, hora
from etiquetas import Etiquetas

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HORIZONTES = ((0.25, "+15m"), (0.5, "+30m"), (1.0, "+60m"))


def _hhmm(h: float) -> str:
    return f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"


def evaluar(dia, marca):
    """Retorno a favor de la marca, en %. Positivo = la marca acertó."""
    h = marca["hora"]
    p = dia.precio_en(h)
    if not p:
        return None
    corto = marca["tipo"] == "entrada_short"
    out = {"precio": p}
    for dh, lab in HORIZONTES:
        q = dia.precio_en(h + dh)
        out[lab] = ((p / q - 1) if corto else (q / p - 1)) * 100 if q else None
    # Hasta el cierre de la sesión regular, o la última barra si ya pasó.
    post = [b for b in dia.bars if hora(b) > h and hora(b) <= CIERRE_RTH and b[4]]
    if not post:
        post = [b for b in dia.bars if hora(b) > h and b[4]]
    if post:
        q = post[-1][4]
        out["cierre"] = ((p / q - 1) if corto else (q / p - 1)) * 100
        alto = max(b[2] for b in post if b[2])
        bajo = min(b[3] for b in post if b[3])
        out["mae"] = ((alto / p - 1) if corto else (1 - bajo / p)) * 100
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluación de las marcas a mano")
    ap.add_argument("--ticker")
    args = ap.parse_args(argv)

    et = Etiquetas()
    marcas = [m for m in et.todas()
              if m["tipo"] in ("entrada_short", "entrada_long")
              and (not args.ticker or m["ticker"] == args.ticker)]
    if not marcas:
        print("  no hay marcas de entrada todavía. Se marca desde el visor.")
        return 0

    claves = {(m["ticker"], m["d"]) for m in marcas}
    dias = {(d.ticker, d.d): d for d in cargar(solo=claves)}
    db = sqlite3.connect(config.bars_db_path())

    print("=" * 96)
    print(f"  MARCAS A MANO — {len(marcas)} entradas en {len(claves)} días")
    print("  'a favor' = el precio se movió en la dirección de la marca")
    print("=" * 96)

    filas = []
    for (t, d) in sorted(claves):
        dia = dias.get((t, d))
        if not dia:
            print(f"\n  {t} {d}: sin barras")
            continue
        prev = db.execute(
            "SELECT h FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
            (t, d)).fetchone()
        r = operar(dia, prev[0] if prev else None, costo_accion=0.003,
                   tope_perdida=20.0, quita_locate=0.20, gradual=True,
                   costo_salida=0.03)
        del_dia = [m for m in marcas if m["ticker"] == t and m["d"] == d]

        print(f"\n  ── {t} {d} · expansión {dia.expansion_pct:+.0f}% · "
              f"apertura→cierre {(dia.rth_close/dia.rth_open-1)*100:+.1f}%")
        if r.get("operado"):
            ini = r["registro"][0]
            print(f"     EL MOTOR: 1 ciclo · entró {ini['ts'].strftime('%H:%M')} "
                  f"${ini['precio']:.2f} · salió por {r['motivo']} · {r['neto']:+.2f}%")
        else:
            print(f"     EL MOTOR: no operó ({r.get('motivo')})")
        print(f"     VOS: {len(del_dia)} entradas")
        print(f"     {'hora':>6} {'tipo':>6} {'precio':>8} "
              + " ".join(f"{lab:>8}" for _, lab in HORIZONTES)
              + f" {'cierre':>8} {'MAE':>7}")
        for m in sorted(del_dia, key=lambda x: x["hora"]):
            e = evaluar(dia, m)
            if not e:
                continue
            f = lambda k: (f"{e[k]:+7.2f}%" if e.get(k) is not None else "      —")  # noqa: E731
            print(f"     {_hhmm(m['hora']):>6} "
                  f"{'short' if m['tipo']=='entrada_short' else 'long':>6} "
                  f"{e['precio']:>8.2f} "
                  + " ".join(f(lab) for _, lab in HORIZONTES)
                  + f" {f('cierre')} {e.get('mae', 0):>6.1f}%")
            filas.append({**e, "tipo": m["tipo"], "t": t, "d": d})

    db.close()
    print("\n" + "=" * 96)
    print("  AGREGADO")
    print("=" * 96)
    print(f"\n  {'':22} {'n':>4} " + " ".join(f"{lab:>9}" for _, lab in HORIZONTES)
          + f" {'cierre':>9}")
    for lab, cond in (("todas las entradas", lambda x: True),
                      ("solo shorts", lambda x: x["tipo"] == "entrada_short"),
                      ("solo longs", lambda x: x["tipo"] == "entrada_long")):
        g = [x for x in filas if cond(x)]
        if not g:
            continue
        vals = []
        for _, h in HORIZONTES:
            v = [x[h] for x in g if x.get(h) is not None]
            vals.append(f"{statistics.median(v):+8.2f}%" if v else "        —")
        v = [x["cierre"] for x in g if x.get("cierre") is not None]
        vals.append(f"{statistics.median(v):+8.2f}%" if v else "        —")
        print(f"  {lab:22} {len(g):>4} " + " ".join(vals))

    n = len(filas)
    print(f"""
  QUÉ SE PUEDE CONCLUIR CON {n} MARCAS: muy poco. Los horizontes cortos y el
  cierre miden cosas distintas —el operador cierra cuando quiere, no a las
  16:00— así que la columna 'cierre' es una cota, no su resultado.

  Para contestar si tu criterio le gana al motor hacen falta marcas en días que
  el motor SÍ operó y en días que descartó. Con menos de 40 de cada lado
  cualquier diferencia es ruido.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
