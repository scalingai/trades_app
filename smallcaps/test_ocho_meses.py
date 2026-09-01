#!/usr/bin/env python3
"""$20.000 en 8 meses: que combinacion de tamano y cantidad de cuentas llega.

OJO: el calendario es el del MERCADO. Una estrategia que opera 6 veces al mes
recibe 6 oportunidades, no 21 — eso es lo que limita la velocidad hacia la meta.

La palanca que no estaba mirando: el RIESGO POR SESION es f x tope de drawdown,
y el tope es el 5% del buying power del plan. O sea que el resultado en dolares
escala LINEAL con el tamano del plan, mientras el edge por unidad de riesgo no
cambia. Un plan de $100k rinde 5 veces lo que uno de $20k con la misma estrategia.

Lo que sube con el tamano es el precio de la evaluacion, no el riesgo relativo:
el piso sigue siendo perder la evaluacion, nada mas.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import cartera as C

ests = C.cargar()
cal = C.calendario_real()   # dias habiles del mercado, no dias operados
base = [ests[n] for n in sorted(ests)]

# (buying power, tope de drawdown 5%, precio de la evaluacion, reparto)
PLANES = [(20_000, 1_000, 97, .70), (40_000, 2_000, 197, .70),
          (60_000, 3_000, 300, .60), (100_000, 5_000, 475, .70),
          (200_000, 10_000, 1240, .80)]

print("  META $20.000 — cuanto tarda cada configuracion (locate 20%, f=0.40)\n")
print(f"  {'plan':>10} {'tope DD':>9} {'eval c/u':>9} {'cuentas':>8} {'invertis':>10} "
      f"{'MESES':>8} {'p90':>6} {'llega 24m':>10}")
print("  " + "-"*80)
mejores=[]
for bp, tope, ev, sp in PLANES:
    for n_cta in (3, 5, 8):
        combo = [base[i % len(base)] for i in range(n_cta)]
        res=[C.simular(combo, cal, .20, 20_000, 24, s, f=.40,
                       tope=tope, eval_usd=ev, split=sp) for s in range(500)]
        llego=[r[0] for r in res if r[0] is not None]
        if not llego:
            print(f"  {('$'+format(bp,',')):>10} {('$'+format(tope,',')):>9} "
                  f"{('$'+str(ev)):>9} {n_cta:>8} {('$'+format(ev*n_cta,',')):>10} "
                  f"{'no llega':>8}"); continue
        med=statistics.median(llego); p90=sorted(llego)[int(.9*len(llego))]
        marca=" <<<" if med<=8 else ""
        print(f"  {('$'+format(bp,',')):>10} {('$'+format(tope,',')):>9} "
              f"{('$'+str(ev)):>9} {n_cta:>8} {('$'+format(ev*n_cta,',')):>10} "
              f"{med:>7.1f} {p90:>6.0f} {100*len(llego)/len(res):>9.0f}%{marca}")
        if med<=8: mejores.append((bp,n_cta,ev*n_cta,med,p90))
print()
if mejores:
    print("  LLEGAN EN 8 MESES O MENOS:")
    for bp,n,inv,med,p90 in sorted(mejores,key=lambda x:x[2]):
        print(f"    {n} cuentas de ${bp:,}  ·  invertis ${inv:,}  ·  "
              f"{med:.1f} meses (p90 {p90:.0f})")
else:
    print("  NINGUNA configuracion llega a $20.000 en 8 meses con las estrategias de hoy.")
