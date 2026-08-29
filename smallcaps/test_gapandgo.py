#!/usr/bin/env python3
"""El Gap and Go: los días que hoy DESCARTAMOS, medidos como long.

**Aclaración de vocabulario, porque cambia qué se busca.** En el informe, *Gap
and Go* es el escenario del RECLAIM: el papel rompe el máximo de pre-market con
volumen, lo sostiene como soporte y hace nuevos máximos, obligando a cubrir a
los cortos atrapados. Es un **squeeze al alza**, no el derrumbe.

Lo que veníamos buscando es lo contrario — el *Gap and Crap*: el gap que falla
en sostener el máximo de pre-market y se desinfla. `chavineta.py` descarta el
**38% de los días** justamente por ser reclaim.

Este script mide qué habría pasado operando esos días **del lado largo**, que es
lo que nunca se probó. Si funcionan, el 38% descartado deja de ser basura y pasa
a ser la otra mitad del negocio.

Entrada: el minuto en que se confirma el reclaim —cierra sobre el máximo de
pre-market por N minutos seguidos y hace un máximo nuevo—. No es el máximo del
día ni nada que se sepa después.

    python test_gapandgo.py
    python test_gapandgo.py --min-expansion 50
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"


def confirmacion_reclaim(dia, *, minutos=5, hasta=12.0):
    """Índice del minuto que confirma el reclaim, o None.

    Confirmar = cerrar por encima del máximo de pre-market `minutos` seguidos.
    Se mira hasta el mediodía: un reclaim a las 15:00 no es el setup.
    """
    pmh = dia.pm_high
    if not pmh:
        return None
    seguidos = 0
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h < APERTURA_RTH or h > hasta:
            continue
        seguidos = seguidos + 1 if (b[4] and b[4] > pmh) else 0
        if seguidos >= minutos:
            return i
    return None


def _simular_long(dia, i, target_pct, stop_pct):
    """Long desde la barra `i`. Devuelve (retorno %, motivo).

    Camina minuto a minuto. Si en el mismo minuto se tocan target y stop, gana
    el STOP — misma convención conservadora que el resto del proyecto.
    """
    p = dia.bars[i][4]
    if not p:
        return None
    p_stop = p * (1 - stop_pct / 100)
    p_tgt = p * (1 + target_pct / 100)
    for b in dia.bars[i + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        if b[3] and b[3] <= p_stop:
            return -stop_pct, "stop"
        if b[2] and b[2] >= p_tgt:
            return target_pct, "target"
    c = dia.rth_close
    return ((c / p - 1) * 100, "cierre") if c else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gap and Go: los reclaim como long")
    ap.add_argument("--min-expansion", type=float, default=100.0)
    ap.add_argument("--min-n", type=int, default=25)
    args = ap.parse_args(argv)

    dias = [d for d in cargar()
            if (d.ratio_volumen or 0) >= 3
            and (d.expansion_pct or 0) >= args.min_expansion]

    filas = []
    for dia in dias:
        i = confirmacion_reclaim(dia)
        if i is None:
            continue
        p = dia.bars[i][4]
        c = dia.rth_close
        if not p or not c:
            continue
        post = [b for b in dia.bars[i + 1:] if hora(b) <= CIERRE_RTH]
        if len(post) < 20:
            continue
        alto = max(b[2] for b in post if b[2])
        bajo = min(b[3] for b in post if b[3])
        f = {"t": dia.ticker, "d": dia.d, "dia": dia, "i": i,
             "h": hora(dia.bars[i]), "precio": p,
             "cierre": (c / p - 1) * 100,
             "mfe": (alto / p - 1) * 100,     # lo mejor que llegó a estar
             "mae": (1 - bajo / p) * 100,     # lo peor
             "per": "P1" if dia.d < CORTE_PERIODO else "P2"}
        for dh, lab in ((0.5, "+30m"), (1.0, "+60m"), (2.0, "+120m")):
            q = dia.precio_en(hora(dia.bars[i]) + dh)
            f[lab] = (q / p - 1) * 100 if q else None
        filas.append(f)

    print("=" * 96)
    print(f"  GAP AND GO — el long en los días que la Chavineta descarta")
    print(f"  {len(dias)} días de expansión >= {args.min_expansion:.0f}% · "
          f"{len(filas)} confirman reclaim antes del mediodía "
          f"({100*len(filas)/max(1,len(dias)):.0f}%)")
    print("  Entrada: el minuto que confirma (5 cierres seguidos sobre el máx pre-market)")
    print("=" * 96)

    if len(filas) < args.min_n:
        print(f"\n  muestra insuficiente ({len(filas)})")
        return 1

    def linea(lab, vals):
        v = [x for x in vals if x is not None]
        if len(v) < args.min_n:
            print(f"  {lab:26} n={len(v):>4}   (insuficiente)")
            return
        print(f"  {lab:26} n={len(v):>4}  mediana {statistics.median(v):>+7.2f}%  "
              f"media {statistics.mean(v):>+7.2f}%  gana "
              f"{100*sum(1 for x in v if x>0)/len(v):>3.0f}%")

    print("\n  EL LONG DESDE LA CONFIRMACIÓN")
    for lab in ("+30m", "+60m", "+120m"):
        linea(f"  hasta {lab}", [f[lab] for f in filas])
    linea("  hasta el cierre", [f["cierre"] for f in filas])

    print("\n  CUÁNTO LLEGA A ESTAR A FAVOR, Y CUÁNTO EN CONTRA")
    mfe = sorted(f["mfe"] for f in filas)
    mae = sorted(f["mae"] for f in filas)
    print(f"  mejor excursión (MFE)   mediana {statistics.median(mfe):>6.1f}%  "
          f"p75 {mfe[int(.75*len(mfe))]:>6.1f}%  p90 {mfe[int(.90*len(mfe))]:>6.1f}%")
    print(f"  peor excursión  (MAE)   mediana {statistics.median(mae):>6.1f}%  "
          f"p75 {mae[int(.75*len(mae))]:>6.1f}%  p90 {mae[int(.90*len(mae))]:>6.1f}%")

    print("\n  CON TOMA DE GANANCIA CORTA — recorrido barra por barra")
    print(f"  {'target':>8} {'stop':>6} {'n':>5} {'media':>9} {'gana':>6} "
          f"{'%target':>8} {'%stop':>7} {'%cierre':>8}")
    print("  " + "-" * 62)
    for stop in (10, 15, 25):
        for tgt in (5, 10, 20, 30):
            res, mot = [], {"target": 0, "stop": 0, "cierre": 0}
            for f in filas:
                r = _simular_long(f["dia"], f["i"], tgt, stop)
                if r is None:
                    continue
                res.append(r[0])
                mot[r[1]] += 1
            if len(res) < args.min_n:
                continue
            n = len(res)
            print(f"  {('+' + str(tgt) + '%'):>8} {(str(stop) + '%'):>6} {n:>5} "
                  f"{statistics.mean(res):>+8.2f}% "
                  f"{100 * sum(1 for x in res if x > 0) / n:>5.0f}% "
                  f"{100 * mot['target'] / n:>7.0f}% {100 * mot['stop'] / n:>6.0f}% "
                  f"{100 * mot['cierre'] / n:>7.0f}%")
        print()
    print("  Recorrido minuto a minuto. Si en el mismo minuto se tocan target y")
    print("  stop, gana el STOP: no se sabe el orden dentro de la barra y asumir")
    print("  lo favorable sería inventar plata. Misma convención que test_rr.py.")

    print("\n  REPLICACIÓN (hasta el cierre)")
    for per in ("P1", "P2"):
        linea(f"  {per}", [f["cierre"] for f in filas if f["per"] == per])

    hs = sorted(f["h"] for f in filas)
    hm = statistics.median(hs)
    print(f"\n  hora mediana de confirmación: {int(hm):02d}:{int((hm%1)*60):02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
