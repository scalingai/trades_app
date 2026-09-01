#!/usr/bin/env python3
"""Sacar el tope de tramos duplica los trades. Replica, o es otra celda con suerte?

Con el presupuesto honesto, no topear la ventana de agregado ni la cantidad de
tramos sube el bruto mensual 70% y cuesta 15 centavos de margen. Antes de
aplicarlo hay que pasarlo por lo mismo que todo lo demas: se sostiene en las dos
mitades, o aparecio en una sola?

Ojo con un detalle de la medicion: el punto de muerte esta en CENTAVOS POR
ACCION, no en ret/nom. Es la unidad en la que se cobra el locate, y es la unica
que hace comparable un papel de $2 con uno de $12.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada, CORTE
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=100.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]

def cosechar(ventana, mt, piso=2.0):
    S = []
    for d in pob:
        j = jornada(d, vent(ventana), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=mt)
        if not j: continue
        pr = statistics.median(t["p_ent"] for t in j["detalle"])
        if pr < piso: continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da; pa = max(pa, a)
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"]})
    return S

def met(S):
    if len(S) < 12: return None
    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)
    ses = len({x["d"] for x in S})/MESES
    return {"n": len(S), "ses": ses, "tr": sum(x["tr"] for x in S)/MESES,
            "cents": 100*b/acc if acc else 0, "mes": b*ses}

print("  REPLICACION DEL CAMBIO — punto de muerte en centavos por accion\n")
print(f"  {'variante':<28} {'n':>4} {'tr/mes':>7} {'muerte':>8} {'P1':>9} {'P2':>9} "
      f"{'brecha':>8} {'bruto/mes':>10}")
print("  " + "-"*84)
for lab, v, mt in (("60 min · max 10 (actual)", 60, 10),
                   ("120 min · max 10", 120, 10),
                   ("sin ventana · max 10", 999, 10),
                   ("sin ventana · max 20", 999, 20),
                   ("sin ventana · max 40", 999, 40)):
    S = cosechar(v, mt)
    r = met(S)
    if not r: print(f"  {lab:<28}   (muestra corta)"); continue
    a = met([x for x in S if x["d"] < CORTE])
    b = met([x for x in S if x["d"] >= CORTE])
    fa = f"{a['cents']:>8.0f}c" if a else f"{'sin mitad':>9}"
    fb = f"{b['cents']:>8.0f}c" if b else f"{'sin mitad':>9}"
    br = f"{abs(a['cents']-b['cents']):>7.0f}c" if (a and b) else f"{'—':>8}"
    print(f"  {lab:<28} {r['n']:>4} {r['tr']:>7.0f} {r['cents']:>7.0f}c "
          f"{fa} {fb} {br} {r['mes']:>+10.2f}")

print("""
  Lo que decide: la brecha entre mitades. Si el cambio sube el bruto en una
  mitad y no en la otra, es ruido; si sube en las dos, es una propiedad.
""")
