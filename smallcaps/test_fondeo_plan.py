"""Cuántas sesiones por mes, cuánto sale cada cuenta, y qué pasa con varias."""
import statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dias import cargar
from sesion import jornada

R=50.0
por_fecha=defaultdict(list)
for dia in cargar():
    if (dia.ratio_volumen or 0)<3 or (dia.expansion_pct or 0)<100: continue
    por_fecha[dia.d].append(dia)
fechas=[]; rs=[]; nom=[]
for d in sorted(por_fecha):
    cands=por_fecha[d]; cuota=R/len(cands); tot=0.0; hubo=False; mx=0.0
    for dia in cands:
        j=jornada(dia,riesgo_dia=cuota,riesgo_trade=cuota/3,objetivo=0,stop_pct=15,
                  costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo='swing',
                  stop_modo='estructural',colchon=1.0,tope_stop=30)
        if j:
            tot+=j['pnl']; hubo=True
            for t in (j.get('detalle') or []):
                mx=max(mx,(t.get('acciones') or 0)*(t.get('precio') or 0))
    if hubo: fechas.append(d); rs.append(tot/R); nom.append(mx)
med=statistics.mean(rs)
meses=defaultdict(int)
for d in fechas: meses[d[:7]]+=1
ses_mes=statistics.median(meses.values())
print(f'  período {fechas[0]} → {fechas[-1]}  ·  {len(fechas)} sesiones operables')
print(f'  sesiones operables por mes: mediana {ses_mes:.0f}  (rango {min(meses.values())}-{max(meses.values())})')
print(f'  nominal máximo por trade con R=$50: mediana ${statistics.median([x for x in nom if x]):.0f}\n')

print('  UNA CUENTA DE $20.000 (tope DD $1.000), reparto 70/30\n')
print(f"  {'f':>6} {'R/sesión':>9} {'bruto/ses':>10} {'-locate':>9} {'tuyo 70%':>9} "
      f"{'$/mes':>9} {'ses. p/ pasar':>14}")
print('  '+'-'*72)
for f,sp in ((.10,46),(.145,31),(.22,21),(.35,13)):
    r=f*1000; bruto=med*r; neto=(bruto-6.99)*.70
    print(f"  {f:>6.3f} {('$'+format(int(r),',')):>9} {bruto:>+9.2f} "
          f"{bruto-6.99:>+8.2f} {neto:>+8.2f} {('$'+format(int(neto*ses_mes),',')):>9} "
          f"{sp:>10} ≈{sp/ses_mes:.0f} m")

print('\n  VARIAS CUENTAS EN PARALELO — las mismas señales, N veces')
print('  El límite no es el edge, es cuánto nominal entra en el minuto.\n')
nm=statistics.median([x for x in nom if x])
print(f"  {'cuentas':>8} {'nominal/min':>12} {'% del min':>10} {'$/mes':>9} {'$/año':>9} {'costo eval':>11}")
print('  '+'-'*66)
f=.145; r=f*1000; neto=(med*r-6.99)*.70
for N in (1,2,3,5,8,12):
    n_tot=nm*(r/R)*N
    print(f"  {N:>8} {('$'+format(int(n_tot),',')):>12} {100*n_tot/2.5e5:>9.1f}% "
          f"{('$'+format(int(neto*ses_mes*N),',')):>9} "
          f"{('$'+format(int(neto*ses_mes*12*N),',')):>9} {('$'+format(97*N,',')):>11}")
print("""
  '% del min' es el nominal contra el piso de liquidez que ya exigimos
  ($250k/min). Mientras eso quede en un dígito bajo, el impacto de mercado
  es despreciable — es la misma razón por la que una cuenta chica escala mal
  pero muchas cuentas chicas escalan bien.""")
