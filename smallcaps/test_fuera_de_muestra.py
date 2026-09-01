#!/usr/bin/env python3
"""La prueba dura: elegir mirando SOLO P1, medir en P2.

Todo lo que encontramos en las ultimas horas —filtro de volumen, corte de float,
umbral de expansion al 150%, stop al 45%— se eligio mirando la muestra COMPLETA.
Eso no es evidencia, es descripcion. La unica forma honesta de saber si hay algo
ahi es congelar la decision con la primera mitad y ver que pasa en la segunda,
que en el momento de decidir no existia.

Si el umbral que gana en P1 tambien gana en P2, es una propiedad.
Si gana otro, encontre ruido y lo llame hallazgo.
"""
import statistics, sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
from dias import cargar
from sesion import jornada

CORTE = "2025-08-17"
db=sqlite3.connect(config.bars_db_path()); flo={}
for t,d,so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
    if so: flo[(t,d)]=so
db.close()

def serie(umbral, stop, minvol=137e6, maxfloat=47e6):
    pf=defaultdict(list)
    for dia in cargar():
        if (dia.ratio_volumen or 0)<3 or (dia.expansion_pct or 0)<umbral: continue
        if sum((b[5] or 0)*(b[4] or 0) for b in dia.bars)<=minvol: continue
        f=flo.get((dia.ticker,dia.d))
        if f is not None and f>maxfloat: continue
        pf[dia.d].append(dia)
    out=[]
    for d in sorted(pf):
        c=pf[d]; cu=50.0/len(c); pnl=nom=0.0; hubo=False
        for dia in c:
            j=jornada(dia,riesgo_dia=cu,riesgo_trade=cu/3,objetivo=0,stop_pct=stop,
                      costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo="swing",
                      stop_modo="fijo",colchon=1.0,tope_stop=max(50.0,stop))
            if not j: continue
            hubo=True; pnl+=j["pnl"]; mx=0.0
            for t in (j.get("detalle") or []):
                mx=max(mx,(t.get("acciones") or 0)*(t.get("precio") or 0))
            nom+=mx
        if hubo: out.append((d, pnl/50.0, nom/50.0))
    return out

def rn(g):
    if len(g)<20: return None
    m=statistics.mean(x[1] for x in g); n=statistics.mean(x[2] for x in g)
    return len(g), 100*m/n, m-0.20*n     # ret/nom y neto por sesion al 20%

print("="*92)
print("  FUERA DE MUESTRA — decidir con P1, medir en P2")
print(f"  corte {CORTE}. P2 no existia cuando se eligieron estos parametros.")
print("="*92)

print("\n  A) UMBRAL DE EXPANSION\n")
print(f"  {'umbral':>9} " + " ".join(f"{c:>22}" for c in ("P1 (decidir)","P2 (verificar)")))
print(f"  {'':>9} " + " ".join(f"{'n':>5}{'ret/nom':>9}{'neto R':>8}" for _ in range(2)))
print("  "+"-"*56)
mejor_p1=(None,-9); mejor_p2=(None,-9)
for u in (50,75,100,150,200):
    s=serie(u,45)
    a=rn([x for x in s if x[0]<CORTE]); b=rn([x for x in s if x[0]>=CORTE])
    def c(x): return f"{x[0]:>5}{x[1]:>8.1f}%{x[2]:>+8.3f}" if x else f"{'corta':>21}"
    mark=""
    if a and a[2]>mejor_p1[1]: mejor_p1=(u,a[2])
    if b and b[2]>mejor_p2[1]: mejor_p2=(u,b[2])
    print(f"  {u:>8}% {c(a)} {c(b)}")
print(f"\n  mejor en P1: expansion >= {mejor_p1[0]}%   ·   mejor en P2: "
      f"expansion >= {mejor_p2[0]}%")

print("\n  B) ANCHO DEL STOP\n")
print(f"  {'stop':>9} " + " ".join(f"{'n':>5}{'ret/nom':>9}{'neto R':>8}" for _ in range(2)))
print("  "+"-"*56)
s1=(None,-9); s2=(None,-9)
for st in (25,35,45,55):
    s=serie(150,st)
    a=rn([x for x in s if x[0]<CORTE]); b=rn([x for x in s if x[0]>=CORTE])
    def c(x): return f"{x[0]:>5}{x[1]:>8.1f}%{x[2]:>+8.3f}" if x else f"{'corta':>21}"
    if a and a[2]>s1[1]: s1=(st,a[2])
    if b and b[2]>s2[1]: s2=(st,b[2])
    print(f"  {st:>8}% {c(a)} {c(b)}")
print(f"\n  mejor en P1: stop {s1[0]}%   ·   mejor en P2: stop {s2[0]}%")

print("\n  C) LO QUE IMPORTA: la config elegida en P1, corrida en P2\n")
s=serie(mejor_p1[0], s1[0])
a=rn([x for x in s if x[0]<CORTE]); b=rn([x for x in s if x[0]>=CORTE])
print(f"    elegida mirando P1:  expansion >= {mejor_p1[0]}% · stop {s1[0]}%")
print(f"    en P1 (donde se eligio):  n={a[0]:>3}  ret/nom {a[1]:.1f}%  neto {a[2]:+.3f} R")
print(f"    en P2 (nunca vista):      n={b[0]:>3}  ret/nom {b[1]:.1f}%  neto {b[2]:+.3f} R")
caida = 100*(1 - b[2]/a[2]) if a[2] else 0
print(f"\n    degradacion fuera de muestra: {caida:+.0f}%")
print("""
    La tolerancia medida antes era hasta 60% del backtest. Si la degradacion
    fuera de muestra supera el 40%, la config no sobrevive a si misma.""")
