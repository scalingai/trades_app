import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import test_3meses as T
print("  SE PUEDE APURAR? f mas alto pasa mas rapido pero revienta mas.")
print("  (limite duro: perdida diaria 2% de $20.000 = $400 -> f max ~0.40)\n")
for meses in (3,4,6):
    print(f"  --- {meses} meses, 3 cuentas, locate 20% ---")
    print(f"  {'f':>6} {'$/dia riesgo':>13} {'mediana':>10} {'p90':>10} "
          f"{'cobraste?':>11} {'en rojo':>8}")
    print("  "+"-"*64)
    for f in (.22,.28,.35,.40):
        r=T.corrida(3,meses,.20,f=f,N=2500); v=sorted(x[0] for x in r)
        q=lambda p: v[int(p*(len(v)-1))]
        print(f"  {f:>6.2f} {('$'+format(int(f*1000),',')):>13} "
              f"{('$'+format(int(q(.50)),',')):>10} {('$'+format(int(q(.90)),',')):>10} "
              f"{100*sum(1 for x in r if x[2]>0)/len(r):>10.0f}% "
              f"{100*sum(1 for x in v if x<0)/len(v):>7.0f}%")
    print()

print("  Y SI AFLOJAMOS EL FILTRO PARA TENER MAS SESIONES?")
print("  El filtro sube el retorno sobre nominal (pelea el locate) pero corta dias.\n")
import simulacion_2anios as S, sqlite3, config
from collections import defaultdict
from dias import cargar
from sesion import jornada
db=sqlite3.connect(config.bars_db_path()); flo={}
for t,d,so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
    if so: flo[(t,d)]=so
db.close()
def serie(minvol, maxfloat):
    pf=defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0)<3 or (dia.expansion_pct or 0)<100: continue
        if sum((b[5] or 0)*(b[4] or 0) for b in dia.bars)<=minvol: continue
        f=flo.get((dia.ticker,dia.d))
        if f is not None and f>maxfloat: continue
        pf[dia.d].append(dia)
    out=[]
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
        if hubo: out.append((pnl/50.0,nom/50.0))
    return out
print(f"  {'filtro':>28} {'ses/mes':>8} {'muerte':>8} {'mediana 6m':>12} {'cobro? 6m':>11}")
print("  "+"-"*72)
for lab,mv,mf in (("validado: >$137M, <47M",137e6,47e6),
                  ("solo float <47M",0,47e6),
                  ("solo volumen >$137M",137e6,9e15),
                  ("sin filtro",0,9e15)):
    rs=serie(mv,mf); T.rs=rs; T.sm=max(4,round(len(rs)/22))
    m=statistics.mean(x[0] for x in rs); n=statistics.mean(x[1] for x in rs)
    r=T.corrida(3,6,.20,N=1500); v=sorted(x[0] for x in r)
    print(f"  {lab:>28} {T.sm:>8} {100*m/n:>7.1f}% "
          f"{('$'+format(int(v[len(v)//2]),',')):>12} "
          f"{100*sum(1 for x in r if x[2]>0)/len(r):>10.0f}%")
