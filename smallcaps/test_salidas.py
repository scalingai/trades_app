#!/usr/bin/env python3
"""¿Sirve salir por anomalía de volumen/volatilidad medida DURANTE el trade?

**Pregunta de Agus.** La idea: en vez de un stop fijo en precio, vigilar el
tape minuto a minuto y salir cuando aparece algo anómalo —un pico de volumen
en contra, una expansión de rango— antes de que el precio te lo cobre.

Es una hipótesis con mecanismo: el stop de precio se entera TARDE (ya perdiste
el 15%), mientras que el volumen anómalo aparece en el minuto en que entra el
flujo que te da vuelta el trade. Si eso es cierto, la cola izquierda se acorta
sin resignar la mediana.

DECLARADO ANTES DE CORRER:
  · Tres trades base, los tres se reportan.
  · Cinco reglas de salida, se reportan TODAS incluidas las que empeoran.
  · El multiplicador k de la anomalía se reporta en grilla (3/5/10). NO se elige
    el mejor: la grilla muestra la forma, no un parámetro óptimo.
  · La métrica que decide es el percentil 10 (la cola izquierda), no la mediana.
    Una regla que sube la mediana y no acorta la cola no sirve para lo que se
    pidió.

Referencia de anomalía: la MEDIANA de las 30 barras previas, no el promedio.
Con promedio, un pico previo sube la vara y esconde el siguiente — que es justo
el caso que interesa.

    python test_salidas.py
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

VENTANA = 30  # barras previas para la referencia de "normal"


def _ret(direccion, entrada, salida):
    return (salida / entrada - 1) * 100 if direccion == "long" else (entrada / salida - 1) * 100


def simular(dia, h_entrada, direccion, regla, *, k=5.0, stop_pct=15.0):
    """Camina minuto a minuto desde la entrada. Devuelve (ret%, motivo, MAE%, minutos)."""
    i0 = dia.idx_en(h_entrada)
    if i0 is None:
        return None
    entrada = dia.bars[i0][4]
    if not entrada:
        return None
    post = [(i, b) for i, b in enumerate(dia.bars) if i > i0 and hora(b) <= CIERRE_RTH]
    if len(post) < 30:
        return None

    mae = 0.0
    t0 = dia.bars[i0][0]
    for i, b in post:
        o, hi, lo, c, v = b[1], b[2], b[3], b[4], (b[5] or 0.0)
        if not c:
            continue
        # Excursión adversa realizada hasta este minuto.
        adverso = (hi / entrada - 1) * 100 if direccion == "short" else (1 - lo / entrada) * 100
        mae = max(mae, adverso)

        # Referencia de normalidad: mediana de las 30 barras previas a ESTA.
        prev = dia.bars[max(0, i - VENTANA):i]
        vols = [x[5] or 0.0 for x in prev]
        rangos = [(x[2] - x[3]) / x[4] * 100 for x in prev if x[2] and x[3] and x[4]]
        med_v = statistics.median(vols) if vols else 0.0
        med_r = statistics.median(rangos) if rangos else 0.0
        rango = (hi - lo) / c * 100 if hi and lo else 0.0
        # ¿La barra fue en contra? Para un short, cerrar arriba de la apertura.
        en_contra = (c > o) if direccion == "short" else (c < o)
        mal_lado = c > dia.vwap[i] if direccion == "short" else c < dia.vwap[i]

        salir = motivo = None
        if regla == "stop_fijo":
            if adverso >= stop_pct:
                salir = entrada * (1 + stop_pct / 100) if direccion == "short" \
                    else entrada * (1 - stop_pct / 100)
                motivo = "stop"
        elif regla == "vwap":
            if mal_lado:
                salir, motivo = c, "vwap"
        elif regla == "vol_anomalo":
            if med_v > 0 and v >= k * med_v and en_contra:
                salir, motivo = c, "volumen"
        elif regla == "rango_anomalo":
            if med_r > 0 and rango >= k * med_r and en_contra:
                salir, motivo = c, "rango"
        elif regla == "combo":
            if med_v > 0 and v >= k * med_v and en_contra:
                salir, motivo = c, "volumen"
            elif mal_lado:
                salir, motivo = c, "vwap"

        if salir:
            return (_ret(direccion, entrada, salir), motivo, mae,
                    (b[0] - t0).total_seconds() / 60.0)

    ultimo = post[-1][1]
    return (_ret(direccion, entrada, ultimo[4]), "cierre", mae,
            (ultimo[0] - t0).total_seconds() / 60.0)


def _p(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def evaluar(dias, h, direccion, filtro, regla, **kw):
    res = [simular(d, h, direccion, regla, **kw) for d in dias if filtro(d, h)]
    res = [r for r in res if r]
    if len(res) < 25:
        return None
    r = [x[0] for x in res]
    return dict(n=len(r), med=statistics.median(r), media=statistics.mean(r),
                p10=_p(r, .10), peor=min(r),
                gana=100 * sum(1 for x in r if x > 0) / len(r),
                mae=statistics.median([x[2] for x in res]),
                mae90=_p([x[2] for x in res], .90),
                mins=statistics.median([x[3] for x in res]))


def tabla(titulo, dias, h, direccion, filtro):
    print(f"\n  {titulo}")
    print(f"  {'regla de salida':26} {'n':>5} {'med':>8} {'media':>8} {'p10':>8} "
          f"{'peor':>9} {'gana':>6} {'MAE p50':>8} {'MAE p90':>8} {'min':>5}")
    print("  " + "-" * 104)
    filas = [("sostener al cierre", "nada", {}),
             ("stop fijo 15%", "stop_fijo", {"stop_pct": 15.0}),
             ("stop fijo 25%", "stop_fijo", {"stop_pct": 25.0}),
             ("cruce de VWAP", "vwap", {})]
    filas += [(f"volumen anómalo k={k}", "vol_anomalo", {"k": float(k)}) for k in (3, 5, 10)]
    filas += [(f"rango anómalo k={k}", "rango_anomalo", {"k": float(k)}) for k in (3, 5, 10)]
    filas.append(("volumen k=5 o VWAP", "combo", {"k": 5.0}))
    for lab, regla, kw in filas:
        r = evaluar(dias, h, direccion, filtro, regla, **kw)
        if not r:
            print(f"  {lab:26}  (n insuficiente)")
            continue
        print(f"  {lab:26} {r['n']:>5} {r['med']:>+7.2f}% {r['media']:>+7.2f}% "
              f"{r['p10']:>+7.2f}% {r['peor']:>+8.1f}% {r['gana']:>5.0f}% "
              f"{r['mae']:>7.1f}% {r['mae90']:>7.1f}% {r['mins']:>5.0f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Salidas por anomalía de volumen/volatilidad")
    ap.add_argument("--sin-filtro-split", action="store_true")
    args = ap.parse_args(argv)

    dias = [d for d in cargar() if args.sin_filtro_split or (d.ratio_volumen or 0) >= 3]

    print("=" * 108)
    print(f"  SALIDA POR ANOMALÍA MEDIDA DURANTE EL TRADE  ·  {len(dias)} días de evento")
    print("  La métrica que decide es p10 (cola izquierda). Subir la mediana sin")
    print("  acortar la cola no sirve para lo que se pidió.")
    print("=" * 108)

    tabla("A. FRONT-SIDE LONG a las 10:00  (precio >= VWAP)",
          dias, 10.0, "long", lambda d, h: d.estado_en(h) == "front")

    tabla("B. BACK-SIDE SHORT a las 12:00  (precio < VWAP)",
          dias, 12.0, "short", lambda d, h: d.estado_en(h) == "back")

    tabla("C. BACK-SIDE SHORT a las 12:00, solo expansión pre-market > +100%",
          dias, 12.0, "short",
          lambda d, h: d.estado_en(h) == "back" and (d.expansion_pct or 0) > 100)

    print("\n  MAE acá es la excursión adversa HASTA LA SALIDA, no hasta el cierre:")
    print("  si la regla sirve, ese número tiene que bajar respecto de 'sostener'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
