#!/usr/bin/env python3
"""Verificacion de la identidad que reporto Franco. Es algebra, pero hay que verla.

Con tamano por riesgo:
    acciones = riesgo / (precio * stop%)
    nominal  = acciones * precio = riesgo / stop%     <- NO depende del precio
    pnl      = acciones * precio * caida%
    ret/nom  = pnl / nominal = caida%                 <- NO depende del precio
    $/accion = pnl / acciones = precio * caida%       <- SI depende del precio

Consecuencia: `ret/nom` es CIEGO al precio por construccion. Dos papeles que
caen 12% dan el mismo ret/nom valgan $1 o $10 — y el de $10 deja diez veces mas
centavos para pagar el locate, que se cobra por accion.

Todos los barridos de precio del proyecto se hicieron con ret/nom. Por eso
ninguno encontro nada: la metrica borraba justo la variable que se barria.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
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
S = []
for d in pob:
    j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0, max_trades=10)
    if not j: continue
    ev = []
    for t in j["detalle"]:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pa = 0.0
    for _, da in ev:
        a += da; pa = max(pa, a)
    S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "nom": j["nominal"],
              "precio": statistics.median(t["p_ent"] for t in j["detalle"])})

def met(g):
    if len(g) < 12: return None
    b = statistics.mean(x["pnl"] for x in g)
    acc = statistics.mean(x["acc"] for x in g)
    nom = statistics.mean(x["nom"] for x in g)
    pr = statistics.median(x["precio"] for x in g)
    return {"n": len(g), "pr": pr, "cents": 100*b/acc if acc else 0,
            "rn": 100*b/nom if nom else 0, "bruto": b,
            "ses_mes": len({x["d"] for x in g})/MESES}

print("  BANDAS DISJUNTAS DE PRECIO — reclaim·exp100\n")
print(f"  {'banda':>12} {'n':>4} {'ses/mes':>8} {'$ entrada':>10} "
      f"{'ret/nom':>9} {'muerte c/accion':>16} {'predicho':>10}")
print("  " + "-"*76)
for lo, hi in ((0, 2), (2, 4), (4, 8), (8, 1e9)):
    g = [x for x in S if lo <= x["precio"] < hi]
    etiqueta = f"${lo:.0f} - ${hi:.0f}" if hi < 1e9 else f"${lo:.0f} +"
    r = met(g)
    if not r:
        print(f"  {etiqueta:>12} {len(g):>4}   (muestra corta)")
        continue
    pred = r["pr"] * r["rn"]          # identidad: precio x ret/nom
    print(f"  {etiqueta:>12} {r['n']:>4} "
          f"{r['ses_mes']:>8.1f} {r['pr']:>10.2f} {r['rn']:>8.1f}% "
          f"{r['cents']:>15.1f}c {pred:>9.1f}c")

print("\n  PISOS DE PRECIO — lo que se gana y lo que se paga\n")
print(f"  {'piso':>7} {'ses/mes':>8} {'n':>4} {'ret/nom':>9} {'muerte c/acc':>14} "
      f"{'P1':>8} {'P2':>8} {'brecha':>8}")
print("  " + "-"*70)
for piso in (0, 1, 1.5, 2, 3, 5):
    g = [x for x in S if x["precio"] >= piso]
    r = met(g)
    if not r: continue
    a = met([x for x in g if x["d"] < motor.CORTE])
    b = met([x for x in g if x["d"] >= motor.CORTE])
    fa = f"{a['cents']:>7.0f}c" if a else f"{'sin mitad':>8}"
    fb = f"{b['cents']:>7.0f}c" if b else f"{'sin mitad':>8}"
    br = f"{abs(a['cents']-b['cents']):>7.0f}c" if (a and b) else f"{'—':>8}"
    print(f"  {('$'+format(piso,'.1f')):>7} {r['ses_mes']:>8.1f} {r['n']:>4} "
          f"{r['rn']:>8.1f}% {r['cents']:>13.1f}c {fa} {fb} {br}")
