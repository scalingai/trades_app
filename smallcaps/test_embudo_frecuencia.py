#!/usr/bin/env python3
"""Cuantas oportunidades hay de verdad, y donde las estamos tirando.

'8 al mes' son SESIONES, no trades. Pero la pregunta de fondo es correcta:
el censo trae 1.985 dias y terminamos operando 177. Este script muestra el
embudo completo con lo que cuesta cada corte, en dias Y en dolares.
"""
import statistics, sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
from dias import cargar
from sesion import jornada

MESES = 22.5   # censo 2024-10-02 -> 2026-08-10

db=sqlite3.connect(config.bars_db_path()); flo={}
for t,d,so in db.execute("SELECT ticker,d,shares_outstanding FROM event_structure"):
    if so: flo[(t,d)]=so
db.close()

todos=[]
for dia in cargar():
    dolar=sum((b[5] or 0)*(b[4] or 0) for b in dia.bars)
    todos.append({"dia":dia,"d":dia.d,"rv":dia.ratio_volumen or 0,
                  "exp":dia.expansion_pct or 0,"dolar":dolar,
                  "float":flo.get((dia.ticker,dia.d))})

def fechas(g): return len({x["d"] for x in g})
print("  EL EMBUDO — de que se cae cada oportunidad\n")
print(f"  {'etapa':>36} {'eventos':>9} {'fechas':>8} {'fechas/mes':>11}")
print("  "+"-"*68)
etapas=[("censo observable (gap>=25%, liquidez previa)", lambda x: True),
        ("+ ratio de volumen >= 3", lambda x: x["rv"]>=3),
        ("+ expansion premarket >= 100%", lambda x: x["rv"]>=3 and x["exp"]>=100),
        ("+ volumen del dia > $137M", lambda x: x["rv"]>=3 and x["exp"]>=100 and x["dolar"]>137e6),
        ("+ float < 47M", lambda x: x["rv"]>=3 and x["exp"]>=100 and x["dolar"]>137e6
                                     and (x["float"] is None or x["float"]<=47e6))]
for lab,p in etapas:
    g=[x for x in todos if p(x)]
    print(f"  {lab:>36} {len(g):>9} {fechas(g):>8} {fechas(g)/MESES:>10.1f}")

print("\n  Y CUANTOS TRADES SON, de verdad\n")
pf=defaultdict(list)
for x in todos:
    if x["rv"]>=3 and x["exp"]>=100 and x["dolar"]>137e6 and (x["float"] is None or x["float"]<=47e6):
        pf[x["d"]].append(x["dia"])
tr=[]; ses=0
for d in sorted(pf):
    c=pf[d]; cu=50.0/len(c); n=0
    for dia in c:
        j=jornada(dia,riesgo_dia=cu,riesgo_trade=cu/3,objetivo=0,stop_pct=45,
                  costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo="swing",
                  stop_modo="fijo",colchon=1.0,tope_stop=50)
        if j: n+=len(j.get("detalle") or [])
    if n: ses+=1; tr.append(n)
print(f"    sesiones operables         {ses}   ({ses/MESES:.1f} por mes)")
print(f"    trades por sesion          mediana {statistics.median(tr):.0f} · "
      f"media {statistics.mean(tr):.1f} · max {max(tr)}")
print(f"    TRADES POR MES             {sum(tr)/MESES:.0f}")
print(f"    trades en total            {sum(tr)}")

print("\n  QUE PASA SI BAJAMOS EL CORTE DE EXPANSION (el que mas corta)\n")
print(f"  {'expansion >=':>14} {'fechas/mes':>11} {'bruto R':>9} {'nominal R':>10} "
      f"{'muerte':>8} {'trades/mes':>11}")
print("  "+"-"*70)
for umbral in (0,25,50,75,100,150,200):
    pf2=defaultdict(list)
    for x in todos:
        if x["rv"]>=3 and x["exp"]>=umbral and x["dolar"]>137e6 and (x["float"] is None or x["float"]<=47e6):
            pf2[x["d"]].append(x["dia"])
    rs=[]; nt=0
    for d in sorted(pf2):
        c=pf2[d]; cu=50.0/len(c); pnl=nom=0.0; hubo=False
        for dia in c:
            j=jornada(dia,riesgo_dia=cu,riesgo_trade=cu/3,objetivo=0,stop_pct=45,
                      costo_accion=0.04,max_trades=10,min_liquidez=2.5e5,modo="swing",
                      stop_modo="fijo",colchon=1.0,tope_stop=50)
            if not j: continue
            hubo=True; pnl+=j["pnl"]; nt+=len(j.get("detalle") or []); mx=0.0
            for t in (j.get("detalle") or []):
                mx=max(mx,(t.get("acciones") or 0)*(t.get("precio") or 0))
            nom+=mx
        if hubo: rs.append((pnl/50.0,nom/50.0))
    if len(rs)<40: continue
    m=statistics.mean(x[0] for x in rs); n=statistics.mean(x[1] for x in rs)
    print(f"  {umbral:>13}% {len(rs)/MESES:>10.1f} {m:>+8.3f} {n:>10.2f} "
          f"{100*m/n:>7.1f}% {nt/MESES:>10.0f}")
