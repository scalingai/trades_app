#!/usr/bin/env python3
"""La cartera final: solo las estrategias con las dos fugas tapadas.

De las ~450 variantes medidas por las cinco familias, entran SOLO las que se
midieron con entradas desde las 10:00 y sin filtros que usen datos del dia
completo (familia 'limpio'). Todo lo demas esta inflado por look-ahead y no se
puede operar.
"""
import itertools, statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import cartera as C

todas = C.cargar(max_brecha=1e9)
ests = {k: v for k, v in todas.items() if k.startswith("limpio·")}
cal = C.calendario_real()
print(f"  {len(ests)} estrategias limpias · calendario {len(cal)} dias ({len(cal)/22.5:.1f}/mes)\n")
print(f"  {'estrategia':<30} {'ses/m':>6} {'ret/nom':>8} {'bruto R':>8} {'neto20':>8} {'brecha':>7}")
print("  "+"-"*72)
for v in sorted(ests.values(), key=lambda x:-x["ret_nom"]):
    print(f"  {v['nombre'][7:]:<30} {v['ses_mes']:>6.1f} {v['ret_nom']:>7.1f}% "
          f"{v['bruto_R']:>+8.3f} {v['bruto_R']-.2*v['nom_R']:>+8.3f} "
          f"{(v['replica'] or 0):>6.1f}p")

# Solo las que replican (brecha < 15) y sobreviven el locate
vi = {k:v for k,v in ests.items()
      if (v["replica"] or 0) < 15 and v["bruto_R"]-.2*v["nom_R"] > 0}
print(f"\n  {len(vi)} pasan replica (<15p) y locate 20%\n")

PLANES=[(20_000,1_000,97,.70),(40_000,2_000,197,.70),(100_000,5_000,475,.70)]
print(f"  META $20.000 — mejores combinaciones por plan\n")
print(f"  {'plan':>9} {'n':>3} {'invertis':>9} {'MESES':>7} {'p90':>5} {'llega':>7}  combinacion")
print("  "+"-"*96)
for bp,tope,ev,sp in PLANES:
    filas=[]
    for k in (1,2,3):
        for combo_n in itertools.combinations(vi,k):
            combo=[vi[n] for n in combo_n]
            res=[C.simular(combo,cal,.20,20_000,24,s,f=.40,tope=tope,
                           eval_usd=ev,split=sp) for s in range(300)]
            ll=[r[0] for r in res if r[0] is not None]
            if not ll: continue
            filas.append((statistics.median(ll), sorted(ll)[int(.9*len(ll))],
                          100*len(ll)/len(res), k, combo_n))
    filas.sort()
    for med,p90,pl,k,cn in filas[:3]:
        marca=" <<<" if med<=8 else ""
        print(f"  {('$'+format(bp,',')):>9} {k:>3} {('$'+format(ev*k,',')):>9} "
              f"{med:>6.1f} {p90:>5.0f} {pl:>6.0f}%  "
              + " + ".join(n[7:20] for n in cn) + marca)
    print()
