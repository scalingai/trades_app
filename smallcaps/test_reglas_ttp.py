#!/usr/bin/env python3
"""Las reglas reales del programa, contra nuestra estrategia.

Datos de la pantalla del producto (plan Day Trading Max, 25k, USD 97):

    Trade Duration          min 30 segundos
    Trade Range             min 10 centavos
    Consistency Rule        50%
    Minimum Withdrawal      14 dias
    Min 0.5% Profit Days    3
    Real Time Market Data   gratis
    PDT Rule                sin restriccion

Dos de esas pueden matarnos y nunca las medimos:

  · CONSISTENCIA 50% — ningun dia puede aportar mas de la mitad de la ganancia
    total. Nuestro PnL esta concentrado en pocas jornadas por construccion: la
    estrategia opera 2 a 7 veces al mes. Con dos sesiones, una buena es mas del
    50% casi por definicion.

  · MIN 3 DIAS CON 0,5% DE GANANCIA — hacen falta tres jornadas que rindan al
    menos 0,5% de la cuenta. Con 2,1 sesiones al mes eso es mes y medio en el
    mejor caso, y solo si las tres son buenas.

Las otras dos no molestan y conviene decirlo: nuestros trades duran horas (min
30 segundos) y con piso de precio de $2 y caidas del 20% el recorrido es de
dolares, no de centavos (min 10 centavos).
"""
import statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9
CUENTA = 25_000.0          # buying power del plan de USD 97
TOPE_DD = CUENTA * 0.04    # 4%, del ejemplo de sus terminos
UMBRAL_DIA = CUENTA * 0.005   # el 0,5% que exige la regla
MIN_ORDEN, POR_ACCION = 0.75, 0.005

def comision(a):
    return 2 * max(MIN_ORDEN, a * POR_ACCION)

def sig(piso):
    return lambda d: [i for i in señales_swing(d, desde=10.0)
                      if (d.bars[i][4] or 0) >= piso]

def correr(ap, ex, piso, riesgo):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    por_fecha = defaultdict(float)
    rango_min = []
    for d in pob:
        j = jornada(d, sig(piso), lado="short", stop_pct=45.0, riesgo=riesgo,
                    max_trades=40)
        if not j: continue
        neto = j["pnl"]
        for t in j["detalle"]:
            neto += t["acciones"] * 0.04 - comision(t["acciones"])
            rango_min.append(abs(t["p_ent"] - t["p_sal"]))
        por_fecha[d.d] += neto
    return por_fecha, rango_min

print(f"  cuenta {CUENTA:,.0f} · tope de drawdown 4% = ${TOPE_DD:,.0f} · "
      f"umbral del dia 0,5% = ${UMBRAL_DIA:,.0f}\n")
print(f"  {'configuracion':<26} {'ses/m':>6} {'dias >=0,5%':>12} {'meses p/ 3':>11} "
      f"{'peor dia %':>11} {'consistencia':>13}")
print("  " + "-"*86)
for lab, ap, ex, piso in (("reclaim exp>=100 · $2", "reclaim", 100.0, 2.0),
                          ("reclaim sin exp · $2", "reclaim", 0.0, 2.0),
                          ("reclaim sin exp · sin piso", "reclaim", 0.0, 0.0),
                          ("sin apertura exp>=50 · $2", None, 50.0, 2.0)):
    # riesgo = 40% del tope de drawdown
    pf, rangos = correr(ap, ex, piso, TOPE_DD * 0.40)
    if len(pf) < 15: continue
    ses = len(pf)/MESES
    buenos = [d for d, v in pf.items() if v >= UMBRAL_DIA]
    # meses hasta juntar 3 dias buenos, en orden cronologico
    ordenados = sorted(pf)
    cuenta_b, idx3 = 0, None
    for k, d in enumerate(ordenados):
        if pf[d] >= UMBRAL_DIA:
            cuenta_b += 1
            if cuenta_b == 3:
                idx3 = k + 1
                break
    meses3 = (idx3/ses) if idx3 else None
    # consistencia: el mejor dia sobre el total, en ventanas de 3 meses
    peor = 0.0
    fechas = sorted(pf)
    for i in range(len(fechas)):
        vent = [pf[d] for d in fechas[i:i+int(ses*3)]]
        tot = sum(x for x in vent if x > 0)
        if tot > 0 and len(vent) >= 4:
            peor = max(peor, 100*max(vent)/tot)
    ok = "PASA" if peor <= 50 else "NO PASA"
    print(f"  {lab:<26} {ses:>6.1f} {len(buenos):>12} "
          f"{(f'{meses3:.1f}' if meses3 else 'nunca'):>11} {peor:>10.0f}% {ok:>13}")

print(f"""
  'peor dia %' es la mayor participacion de UNA jornada en la ganancia de una
  ventana de tres meses. La regla exige que no pase del 50%.
  'meses p/ 3' es cuanto tarda en juntar los tres dias de 0,5% que piden para
  poder retirar.
""")
_, rangos = correr("reclaim", 0.0, 2.0, TOPE_DD*0.40)
if rangos:
    rangos.sort()
    print(f"  RECORRIDO POR TRADE (la regla pide minimo 10 centavos)")
    print(f"    p5 ${rangos[int(.05*len(rangos))]:.2f} · mediana "
          f"${rangos[len(rangos)//2]:.2f} · "
          f"{100*sum(1 for x in rangos if x < 0.10)/len(rangos):.1f}% por debajo de 10c")
