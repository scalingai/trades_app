#!/usr/bin/env python3
"""¿Hasta dónde escala? El edge contra el impacto de mercado.

**La pregunta que nunca medí y que decide si esto es un negocio.** Todos los
resultados asumen que la orden se ejecuta al precio de la barra. Eso es cierto
con $50 de riesgo y falso con $50.000: una orden que es una fracción grande del
volumen del minuto mueve el precio en contra antes de llenarse.

Sin este número, "ratio anual 3,71" no significa nada — un edge de $2.800 al año
que muere al escalarlo es un pasatiempo caro.

MODELO DE IMPACTO, declarado antes de correr:

    slippage_% = k · sqrt( valor_orden / volumen_en_dólares_del_minuto )

La raíz cuadrada es el consenso empírico desde Almgren-Chriss: el impacto crece
con la raíz de la participación, no linealmente. `k` se reporta en grilla porque
no lo podemos medir con barras de un minuto — se necesita el libro. Con k=0,1 y
una orden del 10% del volumen del minuto, el slippage es 3,2%.

Se cobra DOS VECES por trade (entrar y salir), y se suma al costo por acción que
ya estaba.

**Lo que este modelo NO captura:** que una orden grande en un papel de float
chico puede directamente no encontrar contraparte, y que en un halt no hay
precio. El impacto real es peor que la raíz cuadrada en la cola.

    python test_escala.py
    python test_escala.py --k 0.2
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys

from chavineta import clasificar_apertura
from dias import CIERRE_RTH, cargar, hora
from sesion import señales_swing, stop_estructural

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGOS = (50, 250, 1_000, 5_000, 25_000, 100_000)


def trade_con_impacto(dia, i, p, stop_pct, riesgo, costo_accion, k, liq_min):
    """Short con slippage proporcional a la raíz de la participación."""
    nominal = riesgo / (stop_pct / 100.0)
    acciones = nominal / p
    # Participación sobre el volumen en dólares del minuto de la entrada.
    part = nominal / liq_min if liq_min > 0 else 1.0
    slip_pct = k * math.sqrt(part) * 100.0
    # Entrar corto con impacto: te llenan MÁS BAJO de lo que querías.
    p_eff = p * (1 - slip_pct / 100.0)
    p_stop = p_eff * (1 + stop_pct / 100.0)
    salida = None
    for b in dia.bars[i + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        if b[2] and b[2] >= p_stop:
            salida = p_stop
            break
    if salida is None:
        salida = dia.rth_close
    if not salida:
        return None
    # Y al cubrir, el impacto va en contra otra vez: pagás más caro.
    salida_eff = salida * (1 + slip_pct / 100.0)
    return acciones * (p_eff - salida_eff) - acciones * costo_accion, part, slip_pct


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Escalabilidad contra impacto")
    ap.add_argument("--k", type=float, default=0.1, help="coeficiente de impacto")
    ap.add_argument("--costo", type=float, default=0.04)
    ap.add_argument("--min-liquidez", type=float, default=2.5e5)
    ap.add_argument("--tope-stop", type=float, default=30.0)
    ap.add_argument("--max-trades", type=int, default=10)
    args = ap.parse_args(argv)

    entradas = []
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
            continue
        if clasificar_apertura(dia) != "fade":
            continue
        for i in señales_swing(dia, min_liquidez=args.min_liquidez)[:args.max_trades]:
            p = dia.bars[i][4]
            sp = stop_estructural(dia, i, maximo=args.tope_stop)
            liq = dia.liquidez_en(hora(dia.bars[i]))
            if p and sp and liq:
                entradas.append((dia, i, p, sp, liq))

    print("=" * 96)
    print(f"  ESCALABILIDAD — {len(entradas):,} entradas · impacto k={args.k}")
    print("  slippage = k · sqrt(nominal / volumen del minuto), cobrado a la ida y a la vuelta")
    print("=" * 96)

    if len(entradas) < 200:
        print(f"\n  muestra insuficiente ({len(entradas)})")
        return 1

    print(f"\n  {'riesgo/trade':>14} {'nominal med':>12} {'% del minuto':>13} "
          f"{'slippage':>10} {'media $':>11} {'sobre riesgo':>13} {'PF':>6}")
    print("  " + "-" * 84)
    for riesgo in RIESGOS:
        res, parts, slips = [], [], []
        for dia, i, p, sp, liq in entradas:
            r = trade_con_impacto(dia, i, p, sp, riesgo, args.costo, args.k, liq)
            if not r:
                continue
            res.append(r[0])
            parts.append(r[1])
            slips.append(r[2])
        if len(res) < 200:
            continue
        gan = [x for x in res if x > 0]
        per = [x for x in res if x <= 0]
        pf = (sum(gan) / abs(sum(per))) if per and sum(per) else None
        nominal_med = statistics.median(
            [riesgo / (sp / 100.0) for _, _, _, sp, _ in entradas])
        print(f"  {('$'+format(riesgo, ',')):>14} {('$'+format(int(nominal_med), ',')):>12} "
              f"{100*statistics.median(parts):>12.1f}% "
              f"{statistics.median(slips):>9.2f}% "
              f"{statistics.mean(res):>+10.2f} "
              f"{100*statistics.mean(res)/riesgo:>+12.1f}% "
              f"{(f'{pf:.2f}' if pf else '—'):>6}")

    print("""
  'sobre riesgo' es la media por trade dividida por lo arriesgado: es la métrica
  que hay que mirar para escalar, porque es lo único invariante al tamaño. Si se
  mantiene, el sistema escala; si cae, el impacto se está comiendo el edge.

  Lo que el modelo NO captura: que una orden grande en un float chico puede no
  encontrar contraparte, y que en un halt no hay precio. En la cola el impacto
  real es peor que la raíz cuadrada.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
