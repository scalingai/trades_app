"""Cuanto hay que operar para que la concentracion baje del 50%."""
import statistics, sys, random
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES=22.9; CUENTA=25_000.0; TOPE=CUENTA*0.04
MIN_ORDEN,POR_ACCION=0.75,0.005
def com(a): return 2*max(MIN_ORDEN, a*POR_ACCION)
def sig(p): return lambda d: [i for i in señales_swing(d, desde=10.0) if (d.bars[i][4] or 0)>=p]
def serie(ap,ex,piso,riesgo):
    dias=universo()
    pob=poblacion(dias,min_ratio_vol=0.0,min_expansion=ex,min_dolar=0.0,max_float=47e6)
    if ap: pob=[d for d in pob if _cl(d,hasta=10.0)==ap]
    pf=defaultdict(float)
    for d in pob:
        j=jornada(d, sig(piso), lado='short', stop_pct=45.0, riesgo=riesgo, max_trades=40)
        if not j: continue
        n=j['pnl']
        for t in j['detalle']: n += t['acciones']*0.04 - com(t['acciones'])
        pf[d.d]+=n
    return [pf[d] for d in sorted(pf)]

print("  CUANTAS JORNADAS HACEN FALTA PARA QUE EL MEJOR DIA BAJE DEL 50%\n")
print(f"  {'configuracion':<26} {'ses/m':>6} " + " ".join(f"{n:>7}" for n in (5,10,15,20,30,40)))
print(f"  {'':<26} {'':>6} " + " ".join(f"{'jorn':>7}" for _ in range(6)))
print("  "+"-"*80)
guard={}
for lab,ap,ex,piso in (("reclaim exp>=100 · $2","reclaim",100.0,2.0),
                       ("reclaim sin exp · $2","reclaim",0.0,2.0),
                       ("reclaim sin exp · sin piso","reclaim",0.0,0.0),
                       ("sin apertura exp>=50 · $2",None,50.0,2.0)):
    S=serie(ap,ex,piso,TOPE*0.40)
    if len(S)<20: continue
    guard[lab]=S
    ses=len(S)/MESES
    fila=[]
    for n in (5,10,15,20,30,40):
        # mediana de la participacion del mejor dia sobre ventanas de n jornadas
        vals=[]
        for i in range(0,len(S)-n+1):
            v=S[i:i+n]; tot=sum(x for x in v if x>0)
            if tot>0: vals.append(100*max(v)/tot)
        fila.append(f"{statistics.median(vals):>6.0f}%" if vals else f"{'—':>7}")
    print(f"  {lab:<26} {ses:>6.1f} " + " ".join(fila))

print("""
  Cada celda es la MEDIANA de la participacion del mejor dia sobre una ventana
  de N jornadas. La regla exige <=50%.
""")
print("  Y CUANTOS MESES SON ESAS JORNADAS:\n")
print(f"  {'configuracion':<26} {'ses/m':>6} {'jorn p/ <50%':>13} {'meses':>8} {'% de ventanas OK':>18}")
print("  "+"-"*76)
for lab,S in guard.items():
    ses=len(S)/MESES
    objetivo=None
    for n in range(4,60):
        vals=[]
        for i in range(0,len(S)-n+1):
            v=S[i:i+n]; tot=sum(x for x in v if x>0)
            if tot>0: vals.append(100*max(v)/tot)
        if vals and statistics.median(vals)<=50:
            objetivo=n; break
    if objetivo:
        vals=[]
        for i in range(0,len(S)-objetivo+1):
            v=S[i:i+objetivo]; tot=sum(x for x in v if x>0)
            if tot>0: vals.append(100*max(v)/tot)
        ok=100*sum(1 for x in vals if x<=50)/len(vals)
        print(f"  {lab:<26} {ses:>6.1f} {objetivo:>13} {objetivo/ses:>7.1f} {ok:>17.0f}%")
    else:
        print(f"  {lab:<26} {ses:>6.1f} {'nunca <=50%':>13}")
