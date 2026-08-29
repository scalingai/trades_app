#!/usr/bin/env python3
"""La "Chavineta": ¿el reciclaje de posición da 78-80% de aciertos? (Módulo 2)

El informe afirma que escalonar la posición —núcleo del 20%, adiciones contra
tendencia, reducciones en micro-reversiones— produce un **win rate del 77,8% al
80%** aceptando una relación riesgo-beneficio nominalmente negativa, y que la
ventaja está en la reducción de varianza, no en la esperanza.

Es la afirmación más importante del documento porque **contradice el modelo con
el que veníamos midiendo**: todo lo anterior asume UNA entrada y UNA salida. Si
el reciclaje cambia la distribución, todas las tablas de `test_ratios.py` están
midiendo otra cosa.

MODELO, fijado antes de correr (simplificado pero fiel a la descripción):

  1. Núcleo: se abre el 20% del nominal.
  2. Adición: cada vez que el precio sube `paso` × volatilidad por encima de la
     última adición, se agrega otro 20%, hasta 5 tramos. Sube el precio medio
     ponderado, que es el objetivo declarado de la técnica.
  3. Reducción: cuando el precio cae `paso` × volatilidad por debajo del precio
     medio, se cierra el tramo más caro con ganancia y se libera poder de compra.
  4. Stop del conjunto: si la pérdida no realizada supera `stop_total` % del
     nominal, se cierra TODO. Sin esto no es una estrategia, es una martingala.
  5. Al cierre de la sesión se liquida lo que quede.

**Lo que este modelo NO captura, y hay que tenerlo presente:** el operador
humano decide DÓNDE agrega mirando estructura, no a pasos fijos de volatilidad.
Un resultado negativo acá refuta "escalonar mecánicamente", no "escalonar con
criterio". Lo segundo requiere las etiquetas de `etiquetas.py`.

    python test_reciclaje.py
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TRAMOS = 5
CORTE_PERIODO = "2025-08-17"


def volatilidad_en(dia, i, ventana=30):
    prev = dia.bars[max(0, i - ventana):i]
    r = [(x[2] - x[3]) / x[4] * 100 for x in prev if x[2] and x[3] and x[4]]
    return statistics.median(r) if r else None


def reciclar(dia, i0, *, paso, stop_total, costo_accion):
    """Short escalonado. Devuelve (pnl_% del nominal, tramos_usados, max_adverso_%)."""
    vol = volatilidad_en(dia, i0)
    p0 = dia.bars[i0][4]
    if not vol or vol <= 0 or not p0:
        return None
    d = p0 * paso * vol / 100.0          # distancia entre tramos, en precio

    abiertos = [p0]                       # precios de entrada de cada tramo vivo
    realizado = 0.0                       # en dólares por acción, sobre el nominal
    acciones_op = 1.0                     # tramos abiertos+cerrados, para el costo
    proximo_add = p0 + d
    peor = 0.0

    for b in dia.bars[i0 + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        alto, bajo, c = b[2], b[3], b[4]
        if not c:
            continue
        medio = sum(abiertos) / len(abiertos)

        # Pérdida no realizada peor del día, en % del nominal comprometido.
        if alto:
            adverso = (alto / medio - 1) * 100 * len(abiertos) / TRAMOS
            peor = max(peor, adverso)
            # Stop del conjunto: se mide contra el nominal COMPLETO, no contra
            # lo abierto, porque si no el stop se afloja cuando más expuesto estás.
            if adverso >= stop_total:
                realizado += sum(medio - alto for _ in abiertos) / TRAMOS
                return ((realizado / p0) * 100
                        - acciones_op / TRAMOS * costo_accion / p0 * 100,
                        len(abiertos), peor)

        # Adición: el precio siguió en contra y hay tramos libres.
        if alto and len(abiertos) < TRAMOS and alto >= proximo_add:
            abiertos.append(proximo_add)
            acciones_op += 1
            proximo_add += d
            medio = sum(abiertos) / len(abiertos)

        # Reducción: micro-reversión a favor → se cierra el tramo más caro.
        if bajo and len(abiertos) > 1 and bajo <= medio - d:
            caro = max(abiertos)
            abiertos.remove(caro)
            realizado += (caro - (medio - d)) / TRAMOS
            acciones_op += 1

    ultimo = next((b[4] for b in reversed(dia.bars)
                   if hora(b) <= CIERRE_RTH and b[4]), p0)
    realizado += sum(p - ultimo for p in abiertos) / TRAMOS
    return ((realizado / p0) * 100 - acciones_op / TRAMOS * costo_accion / p0 * 100,
            len(abiertos), peor)


def simple(dia, i0, *, stop_pct, costo_accion):
    """La referencia: una entrada, tamaño completo, stop fijo, salida al cierre."""
    p0 = dia.bars[i0][4]
    if not p0:
        return None
    peor = 0.0
    for b in dia.bars[i0 + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        if b[2]:
            peor = max(peor, (b[2] / p0 - 1) * 100)
            if (b[2] / p0 - 1) * 100 >= stop_pct:
                return -stop_pct - costo_accion / p0 * 100, peor
    ultimo = next((b[4] for b in reversed(dia.bars)
                   if hora(b) <= CIERRE_RTH and b[4]), p0)
    return (p0 / ultimo - 1) * 100 - costo_accion / p0 * 100, peor


def resumen(vals):
    if len(vals) < 30:
        return None
    return {
        "n": len(vals),
        "gana": 100 * sum(1 for x in vals if x > 0) / len(vals),
        "med": statistics.median(vals),
        "media": statistics.mean(vals),
        "desvio": statistics.pstdev(vals),
        "p10": sorted(vals)[int(.10 * len(vals))],
        "peor": min(vals),
    }


def linea(lab, r):
    if not r:
        print(f"  {lab:34}  (n insuficiente)")
        return
    print(f"  {lab:34} {r['n']:>5} {r['gana']:>6.1f}% {r['med']:>+8.2f}% "
          f"{r['media']:>+8.2f}% {r['desvio']:>8.2f} {r['p10']:>+8.2f}% {r['peor']:>+9.1f}%")


def cabecera():
    print(f"\n  {'':34} {'n':>5} {'gana':>7} {'mediana':>9} {'media':>9} "
          f"{'desvío':>8} {'p10':>9} {'peor':>10}")
    print("  " + "-" * 96)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reciclaje de posición vs entrada simple")
    ap.add_argument("--hora", type=float, default=11.0)
    ap.add_argument("--spread-cents", type=float, default=2.0)
    ap.add_argument("--comision", type=float, default=0.005)
    ap.add_argument("--locate", type=float, default=0.01)
    args = ap.parse_args(argv)
    costo = args.spread_cents / 100 + 2 * args.comision + args.locate

    dias = [d for d in cargar() if (d.ratio_volumen or 0) >= 3]
    print("=" * 100)
    print(f"  RECICLAJE DE POSICIÓN vs ENTRADA SIMPLE · short a las {args.hora:.0f}:00 · "
          f"{len(dias)} días")
    print(f"  costo {costo*100:.1f}c por acción y POR TRAMO — escalonar multiplica el costo")
    print("  El informe afirma 77,8-80% de aciertos con R:R nominal negativo.")
    print("=" * 100)

    filas = []
    for dia in dias:
        i0 = dia.idx_en(args.hora)
        if i0 is None or i0 < 30:
            continue
        fila = {"d": dia.d, "per": "P1" if dia.d < CORTE_PERIODO else "P2"}
        for paso in (1.5, 3.0):
            for st in (10.0, 20.0):
                r = reciclar(dia, i0, paso=paso, stop_total=st, costo_accion=costo)
                fila[f"rec_{paso}_{st}"] = r[0] if r else None
                fila[f"tramos_{paso}_{st}"] = r[1] if r else None
        for st in (10.0, 20.0):
            s = simple(dia, i0, stop_pct=st, costo_accion=costo)
            fila[f"sim_{st}"] = s[0] if s else None
        filas.append(fila)

    cabecera()
    for st in (10.0, 20.0):
        linea(f"simple · stop {st:.0f}%",
              resumen([f[f"sim_{st}"] for f in filas if f.get(f"sim_{st}") is not None]))
    print("  " + "·" * 96)
    for paso in (1.5, 3.0):
        for st in (10.0, 20.0):
            k = f"rec_{paso}_{st}"
            linea(f"reciclaje · paso {paso}x vol · stop {st:.0f}%",
                  resumen([f[k] for f in filas if f.get(k) is not None]))

    print("\n  REPLICACIÓN")
    cabecera()
    for per in ("P1", "P2"):
        sub = [f for f in filas if f["per"] == per]
        linea(f"{per} · simple stop 20%",
              resumen([f["sim_20.0"] for f in sub if f.get("sim_20.0") is not None]))
        linea(f"{per} · reciclaje 1.5x stop 20%",
              resumen([f["rec_1.5_20.0"] for f in sub if f.get("rec_1.5_20.0") is not None]))

    usados = [f["tramos_1.5_20.0"] for f in filas if f.get("tramos_1.5_20.0")]
    if usados:
        print(f"\n  Tramos abiertos al final (paso 1.5x, stop 20%): "
              f"mediana {statistics.median(usados):.0f} de {TRAMOS}")

    print("""
  CÓMO LEER ESTO
  El informe vende win rate y varianza, no esperanza. Entonces las columnas que
  deciden son 'gana' y 'desvío', no 'media'. Si el reciclaje sube el win rate y
  baja el desvío, la técnica hace lo que promete — aunque la media empeore.

  LO QUE ESTE MODELO NO CAPTURA
  El humano decide dónde agrega mirando ESTRUCTURA, no a pasos fijos de
  volatilidad. Un resultado negativo refuta 'escalonar mecánicamente', no
  'escalonar con criterio'. Para lo segundo hacen falta las marcas a mano.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
