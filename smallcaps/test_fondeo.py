"""¿El sistema pasa una evaluación de fondeo? Simulación con las reglas reales.

Las reglas de una prop de acciones no son cosméticas: son un filtro que mata
sistemas rentables. Tres a la vez:
  · límite de pérdida DIARIA   (te sacan el día)
  · drawdown máximo ESTÁTICO   (te sacan la cuenta)
  · objetivo de ganancia       (hay que llegar antes de romper el drawdown)
Más la regla de consistencia: ningún trade puede ser >30% del profit total.

Se mide en unidades de R = riesgo diario. Así vale para cualquier tamaño.
"""
import statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dias import cargar
from sesion import jornada

R = 50.0
# PnL por FECHA de calendario, repartiendo el riesgo diario entre los candidatos
# del día. Es lo que realmente pasa: el límite es por cuenta, no por papel.
por_fecha = defaultdict(list)
for dia in cargar():
    if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
        continue
    por_fecha[dia.d].append(dia)

serie, trades_todos = [], []
for d in sorted(por_fecha):
    cands = por_fecha[d]
    cuota = R / len(cands)
    tot = 0.0
    for dia in cands:
        j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota/3, objetivo=0,
                    stop_pct=15, costo_accion=0.04, max_trades=10,
                    min_liquidez=2.5e5, modo='swing', stop_modo='estructural',
                    colchon=1.0, tope_stop=30)
        if j:
            tot += j['pnl']
            trades_todos += [t['pnl'] for t in (j.get('detalle') or [])]
    if tot or any(jornada is not None for _ in ()):
        serie.append((d, tot))

v = [x for _, x in serie]
print(f'  sesiones operables: {len(v)}   ·   R = ${R:.0f} de riesgo por día')
print(f'  media/sesión ${statistics.mean(v):+.2f} = {statistics.mean(v)/R:+.3f} R')
print(f'  sesiones positivas: {100*sum(1 for x in v if x>0)/len(v):.0f}%')

# Drawdown en R sobre la serie cronológica real.
acum, pico, dd, peor_dia = 0.0, 0.0, 0.0, 0.0
for _, x in serie:
    acum += x; pico = max(pico, acum); dd = max(dd, pico - acum)
    peor_dia = min(peor_dia, x)
print(f'\n  DRAWDOWN MÁXIMO histórico: ${dd:.2f} = {dd/R:.1f} R')
print(f'  peor sesión suelta:        ${peor_dia:.2f} = {peor_dia/R:.1f} R')
print(f'  total del período:         ${acum:+.2f} = {acum/R:+.1f} R')

# Regla de consistencia: el trade más grande contra el profit total.
if trades_todos:
    mx = max(trades_todos)
    print(f'\n  CONSISTENCIA — trade más grande ${mx:.2f} sobre profit total '
          f'${sum(x for x in trades_todos if x>0):.0f} bruto')

print('\n  ¿PASA LA EVALUACIÓN? objetivo +6%, DD máx -5%, pérdida diaria -2%')
print('  (bloques cronológicos consecutivos, sin reciclar el mismo tramo)\n')
print(f"  {'cuenta':>10} {'R usable':>10} {'objetivo':>10} {'DD tope':>9} "
      f"{'DD real':>9} {'pasa?':>8} {'sesiones':>9}")
print('  ' + '-'*72)
for cuenta in (5_000, 10_000, 20_000, 50_000, 100_000):
    tope_dia = 0.02*cuenta; tope_dd = 0.05*cuenta; obj = 0.06*cuenta
    # El riesgo diario usable es el menor entre nuestro R escalado y el límite.
    # Escalamos R para que el DD histórico entre en el tope, con 30% de margen.
    r_us = min(tope_dia/1.0, tope_dd*0.7/(dd/R))
    esc = r_us / R
    # ¿En cuántas sesiones se llega al objetivo sin romper el DD?
    ok, ses = 0, []
    n = len(serie)
    for ini in range(0, n-40, 10):
        a, p, d2 = 0.0, 0.0, 0.0
        for k in range(ini, n):
            a += serie[k][1]*esc; p = max(p, a); d2 = max(d2, p-a)
            if d2 >= tope_dd: break
            if a >= obj: ok += 1; ses.append(k-ini+1); break
    tot_b = len(range(0, n-40, 10))
    print(f"  {('$'+format(cuenta,',')):>10} {('$'+format(int(r_us),',')):>10} "
          f"{('$'+format(int(obj),',')):>10} {('$'+format(int(tope_dd),',')):>9} "
          f"{('$'+format(int(dd*esc),',')):>9} {100*ok/max(1,tot_b):>7.0f}% "
          f"{(f'{statistics.median(ses):.0f}' if ses else '—'):>9}")
