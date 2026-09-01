"""Menos dias pero mejores: gana o pierde? La evaluacion necesita SESIONES."""
import statistics, sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config, simulacion_2anios as S, test_3meses as T
from dias import cargar
from sesion import jornada
S.DATA_MES=0.0
MESES=22.5
db=sqlite3.connect(config.bars_db_path()); flo={}
for t,d,so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
    if so: flo[(t,d)]=so
db.close()
cache={}
for u in (50,75,100,150,200):
    pf=defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0)<3 or (dia.expansion_pct or 0)<u: continue
        if sum((b[5] or 0)*(b[4] or 0) for b in dia.bars)<=137e6: continue
        f=flo.get((dia.ticker,dia.d))
        if f is not None and f>47e6: continue
        pf[dia.d].append(dia)
    rs=[]
    for d in sorted(pf):
        c=pf[d]; cu=50.0/len(c); pnl=nom=0.0; hubo=False
        for dia in c:
            j=jornada(dia,riesgo_dia=cu,riesgo_trade=cu/3,objetivo=0,stop_pct=45,
                      costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo="swing",
                      stop_modo="fijo",colchon=1.0,tope_stop=50)
            if not j: continue
            hubo=True; pnl+=j["pnl"]; mx=0.0
            for t in (j.get("detalle") or []):
                mx=max(mx,(t.get("acciones") or 0)*(t.get("precio") or 0))
            nom+=mx
        if hubo: rs.append((pnl/50.0,nom/50.0))
    cache[u]=rs

print("  3 cuentas · f=0.40 · locate 20% · sin costo de data\n")
print(f"  {'expansion':>10} {'ses/mes':>8} {'muerte':>8}   " +
      "  ".join(f"{('med '+str(m)+'m'):>10}" for m in (3,6,12,24)) + f"{'rojo 12m':>10}")
print("  "+"-"*88)
for u,rs in cache.items():
    sm=max(2,round(len(rs)/MESES))
    m=statistics.mean(x[0] for x in rs); n=statistics.mean(x[1] for x in rs)
    T.rs=rs; T.sm=sm; fila=[]
    for meses in (3,6,12,24):
        r=T.corrida(3,meses,.20,f=.40,N=1200); v=sorted(x[0] for x in r)
        fila.append(f"{('$'+format(int(v[len(v)//2]),',')):>10}")
        if meses==12: rojo=100*sum(1 for x in v if x<0)/len(v)
    print(f"  {u:>9}% {sm:>8} {100*m/n:>7.1f}%   " + "  ".join(fila) + f"{rojo:>9.0f}%")
