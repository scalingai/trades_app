"""Distribución del drawdown, no el máximo suelto. Y la economía después del reparto."""
import statistics, sys, random
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dias import cargar
from sesion import jornada

R = 50.0
por_fecha = defaultdict(list)
for dia in cargar():
    if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < 100:
        continue
    por_fecha[dia.d].append(dia)

serie = []
for d in sorted(por_fecha):
    cands = por_fecha[d]; cuota = R/len(cands); tot = 0.0; hubo = False
    for dia in cands:
        j = jornada(dia, riesgo_dia=cuota, riesgo_trade=cuota/3, objetivo=0,
                    stop_pct=15, costo_accion=0.04, max_trades=10,
                    min_liquidez=2.5e5, modo='swing', stop_modo='estructural',
                    colchon=1.0, tope_stop=30)
        if j: tot += j['pnl']; hubo = True
    if hubo: serie.append(tot)

def dd_de(v):
    a=p=d=0.0
    for x in v:
        a+=x; p=max(p,a); d=max(d,p-a)
    return d

print(f'  {len(serie)} sesiones · media {statistics.mean(serie)/R:+.3f} R\n')
print('  DRAWDOWN: el histórico es UNA muestra. Remuestreando el orden')
print('  (bootstrap, 4000 corridas de 244 sesiones) sale la distribución real:\n')
random.seed(7)
dds = sorted(dd_de(random.choices(serie, k=len(serie)))/R for _ in range(4000))
q = lambda p: dds[int(p*len(dds))]
print(f"     histórico  {dd_de(serie)/R:.1f} R")
for p,lab in ((.50,'mediana'),(.75,'p75'),(.90,'p90'),(.95,'p95'),(.99,'p99')):
    print(f"     {lab:9}  {q(p):.1f} R")
print(f"     peor       {dds[-1]:.1f} R")

peor = q(.99)
print(f'\n  Dimensionar con el p99 ({peor:.1f} R), no con el histórico (3.2 R):')
print(f"\n  {'cuenta':>10} {'DD tope 5%':>11} {'R seguro':>10} {'$/sesión':>10} "
      f"{'x150 ses':>10} {'tuyo 80%':>10}")
print('  '+'-'*68)
med = statistics.mean(serie)/R
for c in (5_000, 10_000, 20_000, 50_000, 100_000):
    tope = .05*c
    r_seg = min(.02*c, tope/peor)          # sin margen extra: el p99 YA es el margen
    ses = med*r_seg
    print(f"  {('$'+format(c,',')):>10} {('$'+format(int(tope),',')):>11} "
          f"{('$'+format(int(r_seg),',')):>10} {ses:>+9.2f} "
          f"{('$'+format(int(ses*150),',')):>10} {('$'+format(int(ses*150*.8),',')):>10}")
print("""
  'x150 ses' = un año: 244 sesiones operables en el censo, pero no todas
  se pueden operar en vivo, así que 150 es la cuenta conservadora.
  'tuyo 80%' descuenta el reparto típico de la prop. Falta la cuota mensual
  y el locate — los dos van contra ese número.""")
