#!/usr/bin/env python3
"""La economia real: el locate cobrado POR ACCION, que es como se cobra.

El error que esto corrige. Espes dice que paga "20% de lo que pongo". Tomamos
ese porcentaje como si fuera una constante del mercado y lo aplicamos a nuestro
nominal. Pero el locate NO es un porcentaje: es un precio por accion. El
porcentaje sale de dividir ese precio por el precio del papel.

Espes opera papeles de ~$1 con float minimo. $0.20 por accion ahi es el 20%.
Nuestra mediana es $3.08. El MISMO costo en dolares es el 6,5%.

Aca se cobra por accion, jornada por jornada, con las acciones y el precio que
esa jornada tuvo — no con promedios, porque el papel barato y el caro pagan
distinto y el promedio esconde justo eso.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
R = 50.0
TOPE, OBJ, SPLIT, EVAL = 1000.0, 1.2, 0.70, 97.0

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

def cosechar(ap, ex):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    out = []
    for d in sorted(pob, key=lambda x: x.d):
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=R, max_trades=10)
        if not j: continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"], +t["nominal"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                       -t["acciones"], -t["nominal"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = n = pa = pn = 0.0
        for _, da, dn in ev:
            a += da; n += dn
            if n > pn: pn, pa = n, a
        out.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "nom": pn})
    return out

for lab, ap, ex in (("reclaim·exp100", "reclaim", 100),
                    ("fade·exp150", "fade", 150),
                    ("sin-apertura·exp100", None, 100)):
    S = cosechar(ap, ex)
    if len(S) < 20: continue
    ses_mes = len(S)/22.9
    print(f"\n  {lab.upper()}  ·  {len(S)} jornadas  ·  {ses_mes:.1f}/mes\n")
    print(f"  {'locate':>10} {'bruto/ses':>10} {'locate/ses':>11} {'neto/ses':>10} "
          f"{'% que queda':>12} {'muerte a':>11}")
    print("  " + "-"*70)
    bruto = statistics.mean(x["pnl"] for x in S)
    for cps in (0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50):
        costos = [cps*x["acc"] for x in S]
        c = statistics.mean(costos)
        neto = bruto - c
        print(f"  {('$'+format(cps,'.3f')+'/acc'):>10} {bruto:>+10.2f} {-c:>11.2f} "
              f"{neto:>+10.2f} {100*neto/bruto if bruto else 0:>11.0f}% "
              + ("     —" if neto > 0 else "  PIERDE"))
    # el costo por accion que lleva el neto a cero
    accm = statistics.mean(x["acc"] for x in S)
    print(f"\n    punto de muerte: ${bruto/accm:.3f} por accion "
          f"({accm:.0f} acciones promedio en el pico)")

print("""
  ================================================================
  LA CUENTA DE FONDEO, con locate realista
  ================================================================
  Plan de $20.000 (tope de drawdown $1.000), f=0,40 -> riesgo $400/dia.
  Todo lo de arriba esta medido con riesgo $50, asi que escala x8.
""")
S = cosechar("reclaim", 100)
bruto = statistics.mean(x["pnl"] for x in S)
ses_mes = len(S)/22.9
print(f"  {'locate':>12} {'neto/ses $50':>14} {'x8 (R=$400)':>13} {'x{:.1f} ses/mes'.format(ses_mes):>15} "
      f"{'tuyo 70%':>10} {'al ano':>10}")
print("  " + "-"*80)
for cps in (0.01, 0.02, 0.05, 0.10, 0.20, 0.40):
    c = statistics.mean(cps*x["acc"] for x in S)
    neto = bruto - c
    esc = neto*8
    mes = esc*ses_mes
    print(f"  {('$'+format(cps,'.2f')+'/acc'):>12} {neto:>+14.2f} {esc:>+13.2f} "
          f"{mes:>+15.2f} {mes*SPLIT:>+10.2f} {('$'+format(int(mes*SPLIT*12),',')):>10}")
print("""
  'tuyo 70%' ya descuenta el reparto con la firma. Una sola cuenta.
  Con tres cuentas decorrelacionadas se multiplica, y ahi si la correlacion
  que medimos ayer pasa a servir para algo.
""")
