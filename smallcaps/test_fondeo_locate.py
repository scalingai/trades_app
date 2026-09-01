"""El locate es un costo FIJO por día. Eso es lo que mata a la cuenta chica."""
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
serie=[]; acc=[]; papeles=[]
for d in sorted(por_fecha):
    cands=por_fecha[d]; cuota=R/len(cands); tot=0.0; hubo=False; sh=0.0
    for dia in cands:
        j=jornada(dia,riesgo_dia=cuota,riesgo_trade=cuota/3,objetivo=0,stop_pct=15,
                  costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo='swing',
                  stop_modo='estructural',colchon=1.0,tope_stop=30)
        if j:
            tot+=j['pnl']; hubo=True
            sh=max(sh,max((t.get('acciones') or 0) for t in (j.get('detalle') or [{}])) or 0)
    if hubo: serie.append(tot); acc.append(sh); papeles.append(len(cands))
med=statistics.mean(serie)/R
acc_med=statistics.median([a for a in acc if a])
pap=statistics.mean(papeles)
print(f'  media {med:+.3f} R/sesión · {pap:.1f} papeles a reservar por día')
print(f'  acciones por trade con R=$50: mediana {acc_med:.0f}\n')
print('  El locate tiene DOS componentes y para tamaño chico manda el mínimo:')
print('     · mínimo por pedido  (~$2-$5, no escala)')
print('     · por acción         (~$0.01-$0.05, escala lineal)\n')
print(f"  {'cuenta':>9} {'R':>7} {'acc':>7} {'bruto':>8} {'tras 80%':>9} "
      f"{'loc min':>8} {'loc x/acc':>10} {'NETO':>9} {'año(150)':>10}")
print('  '+'-'*84)
peor=6.9
for c in (5_000,10_000,20_000,50_000,100_000,200_000):
    r=min(.02*c,.05*c/peor); esc=r/R
    bruto=med*r; tras=bruto*.8
    n_acc=acc_med*esc
    lmin=pap*3.5                       # $3.50 de mínimo por papel reservado
    lacc=pap*n_acc*0.02                # $0.02 por acción
    loc=max(lmin,lmin+lacc-lmin) if lacc>lmin else lmin
    loc=max(lmin,lacc)
    neto=tras-loc
    print(f"  {('$'+format(c,',')):>9} {('$'+format(int(r),',')):>7} {n_acc:>7.0f} "
          f"{bruto:>+7.2f} {tras:>+8.2f} {lmin:>7.2f} {lacc:>9.2f} "
          f"{neto:>+8.2f} {('$'+format(int(neto*150),',')):>10}")
print("""
  Leer la columna NETO de arriba hacia abajo: es la misma estrategia, el mismo
  edge por unidad de riesgo. Lo único que cambia es que el costo fijo del locate
  se reparte entre más tamaño.""")
