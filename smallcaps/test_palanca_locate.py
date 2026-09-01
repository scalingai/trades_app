"""Con el locate al 20%, el edge neto es fino. Dos palancas: abrir el stop
(baja el nominal -> baja el locate) y bajar f (el edge fino no banca f alto)."""
import sqlite3, statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
from dias import cargar
from sesion import jornada
import simulacion_2anios as S

db=sqlite3.connect(config.bars_db_path()); flo={}
for t,d,so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
    if so: flo[(t,d)]=so
db.close()

def serie(stop_pct, tope):
    pf=defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0)<3 or (dia.expansion_pct or 0)<100: continue
        dolar=sum((b[5] or 0)*(b[4] or 0) for b in dia.bars)
        f=flo.get((dia.ticker,dia.d))
        if dolar<=137e6: continue
        if f is not None and f>47e6: continue
        pf[dia.d].append(dia)
    out=[]
    for d in sorted(pf):
        c=pf[d]; cu=50.0/len(c); pnl=nom=0.0; hubo=False
        for dia in c:
            j=jornada(dia,riesgo_dia=cu,riesgo_trade=cu/3,objetivo=0,
                      stop_pct=(stop_pct or 15),costo_accion=0.04,max_trades=10,
                      min_liquidez=2.5e5,modo="swing",
                      stop_modo=("estructural" if stop_pct is None else "fijo"),
                      colchon=1.0,tope_stop=tope)
            if not j: continue
            hubo=True; pnl+=j["pnl"]; mx=0.0
            for t in (j.get("detalle") or []):
                mx=max(mx,(t.get("acciones") or 0)*(t.get("precio") or 0))
            nom+=mx
        if hubo: out.append((pnl/50.0, nom/50.0))
    return out

print("  ABRIR EL STOP baja el nominal, y el locate se cobra sobre el nominal\n")
print(f"  {'stop':>18} {'ses':>5} {'bruto R':>9} {'nominal R':>10} {'neto@20% R':>11} "
      f"{'muerte':>8}")
print("  "+"-"*68)
cache={}
for sp,tp in ((None,30),(None,40),(35,40),(45,50),(55,60),(65,70)):
    rs=serie(sp,tp); cache[(sp,tp)]=rs
    if len(rs)<60: continue
    m=statistics.mean(x[0] for x in rs); n=statistics.mean(x[1] for x in rs)
    lab=f"estruct tope {tp}%" if sp is None else f"{sp}% fijo"
    print(f"  {lab:>18} {len(rs):>5} {m:>+8.3f} {n:>10.2f} {m-.2*n:>+11.3f} "
          f"{100*m/n:>7.1f}%")

print("\n  DOS AÑOS, 3 CUENTAS, locate 20% — mejor stop x mejor f\n")
print(f"  {'stop':>18} " + " ".join(f"{('f='+format(f,'.2f')):>11}" for f in (.10,.16,.22,.28)))
print("  "+"-"*68)
for (sp,tp),rs in cache.items():
    if len(rs)<60: continue
    sm=max(4,round(len(rs)/22)); fila=[]
    for f in (.10,.16,.22,.28):
        w=sorted(S.correr(rs,sm,f,.20,24,s)[0] for s in range(400))
        fila.append(f"{('$'+format(int(w[len(w)//2]),',')):>11}")
    lab=f"estruct tope {tp}%" if sp is None else f"{sp}% fijo"
    print(f"  {lab:>18} " + " ".join(fila))
