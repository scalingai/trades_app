#!/usr/bin/env python3
"""Las dos correcciones de Agus, juntas: no perseguir + tomar ganancia.

Las dos salieron de mirar UN grafico en la bitacora, y las dos dieron por
separado. Aca la grilla completa para ver si se suman o se pisan, y cual es el
punto de muerte de cada celda — que es lo unico que decide si esto es negocio.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, evaluar
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
dias = universo()
L = {"min_ratio_vol": 0.0, "min_dolar": 0.0}
VENT = (0, 15, 30, 45, 60, 90, 999)
OBJS = (None, 10, 15, 20, 30)


def ventana(mins):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx:
            return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= mins / 60.0]
    return f


for lab, ap, ex in (("reclaim·exp100", "reclaim", 100), ("fade·exp150", "fade", 150)):
    print(f"\n  {lab.upper()}  ·  PUNTO DE MUERTE (% de locate que aguanta)\n")
    print(f"  {'agrega hasta':>14} " + " ".join(
        f"{('sin obj' if o is None else 'obj '+str(o)):>10}" for o in OBJS))
    print("  " + "-"*(16 + 11*len(OBJS)))
    tabla = {}
    for v in VENT:
        fila = []
        for o in OBJS:
            r = evaluar(f"comb·{v}·{o}·{lab}", ventana(v), dias=dias, familia="combo",
                        stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                        objetivo_pct=o, guardar=(v in (60, 999) and o is None))
            if "error" in r:
                fila.append(None); continue
            tabla[(v, o)] = (r["bruto_R"], r["nom_R"], r["replica"])
            fila.append(r["ret_nom"])
        et = "solo el 1ro" if v == 0 else ("sin tope" if v == 999 else f"{v} min")
        print(f"  {et:>14} " + " ".join(
            f"{x:>9.1f}%" if x is not None else f"{'—':>10}" for x in fila))

    print(f"\n  {lab.upper()}  ·  NETO POR SESION segun el locate real\n")
    print(f"  {'locate':>8} {'mejor configuracion':>34} {'neto R':>9} {'brecha':>8}")
    print("  " + "-"*64)
    for loc in (.05, .10, .125, .15, .175, .20):
        mejor = None
        for (v, o), (b, nn, rep) in tabla.items():
            val = b - loc*nn
            if mejor is None or val > mejor[0]:
                mejor = (val, v, o, rep)
        val, v, o, rep = mejor
        et = "solo el 1ro" if v == 0 else ("sin tope" if v == 999 else f"agrega {v} min")
        eo = "sin objetivo" if o is None else f"objetivo {o}%"
        print(f"  {loc:>7.1%} {f'{et} · {eo}':>34} {val:>+9.3f} "
              f"{(rep or 0):>6.1f}p" + ("   NEGOCIO" if val > 0 else ""))
