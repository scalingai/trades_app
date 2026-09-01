#!/usr/bin/env python3
"""Barrido completo de poblaciones en CENTAVOS POR ACCION. Nunca se hizo.

Todos los barridos de poblacion del proyecto usaron `ret/nom`, que por
construccion es ciego al precio del papel. Y el costo real —el locate— se cobra
POR ACCION. O sea que hemos estado buscando con una linterna que apagaba justo
la variable que decide.

Lo que se busca ahora es distinto: una poblacion con MUCHA FRECUENCIA y
suficientes centavos. La actual tiene 2,1 sesiones/mes y 87 centavos; hace falta
algo del orden de 15-20 sesiones/mes aunque tenga la mitad de centavos, porque
la plata mensual es el producto de las dos cosas.

Se cruzan: apertura x expansion x piso de precio. El piso va sobre el precio de
ENTRADA (operable: a las 10:00 mirás y decidís), no sobre el del papel al abrir.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9
R = 50.0

def sig(piso):
    return lambda d: [i for i in señales_swing(d, desde=10.0)
                      if (d.bars[i][4] or 0) >= piso]

def medir(pob, piso):
    S = []
    for d in pob:
        j = jornada(d, sig(piso), lado="short", stop_pct=45.0, riesgo=R,
                    max_trades=40)
        if not j: continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da; pa = max(pa, a)
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"]})
    if len(S) < 15: return None
    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)
    ses = len({x["d"] for x in S})/MESES
    def c(g):
        if len(g) < 12: return None
        bb = statistics.mean(x["pnl"] for x in g); aa = statistics.mean(x["acc"] for x in g)
        return 100*bb/aa if aa else 0
    return {"n": len(S), "ses": ses, "tr": sum(x["tr"] for x in S)/MESES,
            "cents": 100*b/acc if acc else 0, "mes": b*ses,
            "p1": c([x for x in S if x["d"] < motor.CORTE]),
            "p2": c([x for x in S if x["d"] >= motor.CORTE])}

dias = universo()
POB = [("reclaim exp>=100", "reclaim", 100), ("reclaim exp>=50", "reclaim", 50),
       ("reclaim todo",     "reclaim",   0), ("fade exp>=150", "fade", 150),
       ("fade exp>=100",    "fade",    100), ("fade exp>=50", "fade", 50),
       ("fade todo",        "fade",      0), ("sin apertura exp>=100", None, 100),
       ("sin apertura exp>=50", None,   50), ("sin apertura todo", None, 0)]
PISOS = (0.0, 2.0, 3.0, 5.0)

print("  BARRIDO EN CENTAVOS POR ACCION — poblacion x piso de precio de entrada\n")
print(f"  {'poblacion':<24} {'piso':>6} {'ses/m':>6} {'tr/m':>6} {'muerte':>8} "
      f"{'P1':>7} {'P2':>7} {'bruto/mes':>10}")
print("  " + "-"*82)
mejores = []
for lab, ap, ex in POB:
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    for piso in PISOS:
        r = medir(pob, piso)
        if not r: continue
        f1 = f"{r['p1']:>6.0f}c" if r["p1"] is not None else f"{'s/dato':>7}"
        f2 = f"{r['p2']:>6.0f}c" if r["p2"] is not None else f"{'s/dato':>7}"
        marca = "  <<<" if (r["ses"] >= 8 and r["cents"] >= 40) else ""
        print(f"  {lab:<24} {('$'+format(piso,'.0f')):>6} {r['ses']:>6.1f} "
              f"{r['tr']:>6.0f} {r['cents']:>7.0f}c {f1} {f2} {r['mes']:>+10.2f}{marca}")
        mejores.append((r["mes"], lab, piso, r))
    print()

print("  ORDENADAS POR PLATA MENSUAL (que es el producto de frecuencia x centavos)\n")
print(f"  {'#':>3} {'poblacion':<24} {'piso':>6} {'ses/m':>6} {'muerte':>8} {'bruto/mes':>10}")
print("  " + "-"*64)
for i, (m, lab, piso, r) in enumerate(sorted(mejores, reverse=True)[:10], 1):
    print(f"  {i:>3} {lab:<24} {('$'+format(piso,'.0f')):>6} {r['ses']:>6.1f} "
          f"{r['cents']:>7.0f}c {m:>+10.2f}")
