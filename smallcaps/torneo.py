#!/usr/bin/env python3
"""Todas las estrategias candidatas, sobre la MISMA población y la misma vara.

**El problema que resuelve.** Cada estrategia se midió con su propio script,
su propia población y su propio modelo de costos. Los números quedaron en el
mismo documento pero no eran comparables: el −13,27% del radar no tiene stop, el
−0,99% de la Chavineta paga comisión por ejecución, el +8,39% de la entrada
simple no paga nada. Poner tres números así en una tabla es peor que no tenerla.

Acá corren todas contra:

  · la MISMA población de días
  · el MISMO modelo de costos
  · el MISMO riesgo máximo comprometido (el nominal completo)
  · y se reportan en las dos monedas: por trade y por año

**La moneda que decide es la de por año.** Este proyecto ya midió cuatro veces
que seleccionar más mejora el trade y empeora el negocio. Una estrategia que
gana 20% por trade y opera seis veces al año pierde contra una que gana 4% y
opera doscientas.

    python torneo.py
    python torneo.py --poblacion radar
    python torneo.py --spread-cents 3 --locate 0.02
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from chavineta import operar as chavineta_operar
from dias import CIERRE_RTH, cargar, hora
from test_construccion import escalonado, simple

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"
DIAS_HABILES_AÑO = 252


# --------------------------------------------------------------- estrategias
# Cada una devuelve (retorno bruto % del nominal, MAE %, ejecuciones) o None.
# El costo se aplica afuera, igual para todas, para que la comparación sea justa.

def _stop_y_cierre(dia, h0, stop_pct, h1=CIERRE_RTH):
    """Short a h0 con stop fijo; sale por stop o a h1."""
    p = dia.precio_en(h0)
    if not p:
        return None
    peor = 0.0
    for b in dia.bars:
        if hora(b) <= h0 or hora(b) > h1:
            continue
        if b[2]:
            peor = max(peor, (b[2] / p - 1) * 100)
            if (b[2] / p - 1) * 100 >= stop_pct:
                return -stop_pct, peor, 2
    q = dia.precio_en(h1)
    return ((p / q - 1) * 100, peor, 2) if q else None


def _volatilidad(dia, h0, ventana=30):
    i = dia.idx_en(h0)
    if i is None or i < ventana:
        return None
    r = [(x[2] - x[3]) / x[4] * 100 for x in dia.bars[i - ventana:i]
         if x[2] and x[3] and x[4]]
    return statistics.median(r) if r else None


def _stop_volatilidad(dia, h0, mult, h1=CIERRE_RTH):
    v = _volatilidad(dia, h0)
    return _stop_y_cierre(dia, h0, mult * v, h1) if v and v > 0 else None


def _swing(dia, db):
    """Short al cierre del evento, cubre al cierre de T+5. Usa barras diarias."""
    r = db.execute("SELECT ret_t5, mae_short_t5 FROM horizons WHERE ticker=? AND d=?",
                   (dia.ticker, dia.d)).fetchone()
    if not r or r[0] is None:
        return None
    return -r[0], (r[1] or 0.0), 2


ESTRATEGIAS = [
    ("short simple 09:30 → cierre", lambda d, db: simple(d, 9.5, CIERRE_RTH)),
    ("short simple 09:30 → 11:30", lambda d, db: simple(d, 9.5, 11.5)),
    ("short 09:30, stop 8× vol → cierre", lambda d, db: _stop_volatilidad(d, 9.5, 8)),
    ("short 09:30, stop 15% → cierre", lambda d, db: _stop_y_cierre(d, 9.5, 15.0)),
    ("short 10:00, stop 8× vol → cierre", lambda d, db: _stop_volatilidad(d, 10.0, 8)),
    ("escalonado 06:30 → 11:30", lambda d, db: escalonado(d, 6.5, 11.5)),
    ("escalonado 08:30 → 11:30", lambda d, db: escalonado(d, 8.5, 11.5)),
    ("escalonado 08:30 → cierre", lambda d, db: escalonado(d, 8.5, CIERRE_RTH)),
    ("swing: cierre → T+5", _swing),
]


def _chavineta(dia, db, costo):
    prev = db.execute(
        "SELECT h FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
        (dia.ticker, dia.d)).fetchone()
    r = chavineta_operar(dia, prev[0] if prev else None, costo_accion=0.005,
                         tope_perdida=20.0, quita_locate=0.0, minutos_reclaim=2,
                         costo_salida=costo, gradual=True)
    if not r.get("operado"):
        return None
    return r["bruto"], r["peor"], r["ejecuciones"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Torneo de estrategias")
    ap.add_argument("--poblacion", choices=("parabolicas", "radar"),
                    default="parabolicas")
    ap.add_argument("--spread-cents", type=float, default=2.0)
    ap.add_argument("--comision", type=float, default=0.005)
    ap.add_argument("--locate", type=float, default=0.01)
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args(argv)
    costo_accion = args.spread_cents / 100 + 2 * args.comision + args.locate

    db = sqlite3.connect(config.bars_db_path())
    acciones = {(t, d): n for t, d, n in db.execute(
        "SELECT ticker,d,shares_outstanding FROM event_structure "
        "WHERE shares_outstanding IS NOT NULL")}

    dias = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        if args.poblacion == "radar":
            p = dia.rth_open or 0
            acc = acciones.get((dia.ticker, dia.d))
            gap = (p / dia.prev_close - 1) * 100 if (p and dia.prev_close) else 0
            if not (0.70 <= p <= 20 and gap >= 70 and acc and acc <= 10e6):
                continue
        dias.append(dia)

    fechas = {d.d for d in dias}
    años = len(fechas) / DIAS_HABILES_AÑO if fechas else 1
    # Con una muestra de días de evento salteados, "por año" se estima con la
    # cantidad de días de CALENDARIO que cubre la muestra, no con los días con
    # evento. Si no, cualquier estrategia parecería operar todos los días.
    if fechas:
        rango = (max(fechas), min(fechas))
        from datetime import date
        d1, d0 = date.fromisoformat(rango[0]), date.fromisoformat(rango[1])
        años = max(0.5, (d1 - d0).days / 365.25)

    print("=" * 104)
    print(f"  TORNEO — todas contra la misma población y la misma vara")
    print(f"  población: {args.poblacion} · {len(dias)} días · "
          f"{años:.1f} años de calendario")
    print(f"  costo {costo_accion*100:.1f}c/acción por ejecución "
          f"(spread {args.spread_cents:.0f}c + comisión ×2 + locate)")
    print("  Todas son SHORT y todas comprometen el mismo nominal máximo.")
    print("=" * 104)
    print(f"\n  {'estrategia':36} {'n':>5} {'med':>8} {'media':>8} {'gana':>6} "
          f"{'MAE p90':>8} {'x/MAE':>7} {'/año':>5} {'MEDIA×AÑO':>10}")
    print("  " + "-" * 100)

    filas = list(ESTRATEGIAS) + [("chavineta (filtro+niveles+reclaim)",
                                  lambda d, db: _chavineta(d, db, costo_accion))]
    resultados = []
    for nombre, fn in filas:
        rs = []
        for dia in dias:
            try:
                r = fn(dia, db)
            except Exception:
                r = None
            if not r:
                continue
            bruto, mae, ejec = r
            p = dia.precio_en(9.5) or dia.rth_open or 1
            neto = bruto - ejec * costo_accion / p * 100
            rs.append((dia.d, neto, mae))
        if len(rs) < args.min_n:
            print(f"  {nombre:36} {len(rs):>5}   (n insuficiente)")
            continue
        v = [x[1] for x in rs]
        maes = sorted(x[2] for x in rs)
        por_año = len(v) / años
        per = []
        for pp in ("P1", "P2"):
            g = [x[1] for x in rs if (x[0] < CORTE_PERIODO) == (pp == "P1")]
            per.append(f"{statistics.median(g):+7.2f}%" if len(g) >= 15 else "      —")
        media = statistics.mean(v)
        mae90 = maes[int(.9 * len(maes))]
        # Retorno por unidad de peor caso. Es tosco a propósito: no hay forma de
        # dimensionar una estrategia cuyo p90 adverso es del 100% del nominal,
        # así que la media sola no alcanza para ordenarlas.
        ratio = media / mae90 if mae90 > 0 else 0.0
        print(f"  {nombre:36} {len(v):>5} {statistics.median(v):>+7.2f}% "
              f"{media:>+7.2f}% {100*sum(1 for x in v if x>0)/len(v):>5.0f}% "
              f"{mae90:>7.1f}% {ratio:>+7.2f} {por_año:>5.0f} "
              f"{media*por_año:>+9.0f}%")
        resultados.append((nombre, media * por_año, media, len(v), mae90, ratio))

    print("\n  MEDIA×AÑO = media por trade × trades por año. No es el P&L —las medias")
    print("  no se suman así— pero es la única columna que castiga perder frecuencia.")

    if resultados:
        print("\n  ORDEN POR NEGOCIO ANUAL (ignora el riesgo — leer junto a la de abajo)")
        for i, r in enumerate(sorted(resultados, key=lambda x: -x[1])[:4], 1):
            print(f"    {i}. {r[0]:38} {r[1]:>+8.0f}%/año  · MAE p90 {r[4]:>5.0f}%")
        print("\n  ORDEN POR RETORNO SOBRE PEOR CASO (media ÷ MAE p90)")
        for i, r in enumerate(sorted(resultados, key=lambda x: -x[5])[:4], 1):
            print(f"    {i}. {r[0]:38} {r[5]:>+8.2f}   · media {r[2]:>+6.2f}% · "
                  f"MAE p90 {r[4]:>5.0f}%")

        # ¿Cada punto de retorno cuesta MAE? Si la correlación es alta no hay una
        # estrategia mejor: hay una recta de compensación y cada una elige dónde
        # pararse. Eso cambia la pregunta de "cuál gana" a "cuánto riesgo aguantás".
        xs = [r[4] for r in resultados]
        ys = [r[2] for r in resultados]
        if len(xs) >= 5:
            mx, my = statistics.mean(xs), statistics.mean(ys)
            num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
            dx = sum((a - mx) ** 2 for a in xs) ** 0.5
            dy = sum((b - my) ** 2 for b in ys) ** 0.5
            rc = num / (dx * dy) if dx and dy else 0.0
            print(f"\n  CORRELACIÓN entre media y MAE p90 de las {len(xs)} estrategias:"
                  f"  r = {rc:+.2f}")
            print("  Alta = no hay estrategia mejor, hay una recta de compensación.")
            print("  Baja = alguna rompe el trade-off, y esa es la que importa.")

    print("\n  REPARO QUE VA ARRIBA DE TODO: la población sale de la muestra de")
    print("  minutos sesgada (rango DIARIO > 40%). Las comparaciones ENTRE filas")
    print("  valen porque comparten población; los niveles absolutos no.")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
