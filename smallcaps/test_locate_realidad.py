#!/usr/bin/env python3
"""Es plausible el 20% del nominal para NUESTROS papeles? Chequeo de realidad.

Agus: "no me hace sentido que sea tanta plata, estamos ganando profit".

Tiene razon en desconfiar. El locate no se cobra como porcentaje: se cobra POR
ACCION. El porcentaje es una consecuencia del precio del papel. Un locate de
$0.10 por accion es el 10% del nominal en un papel de $1 y el 1% en uno de $10.

O sea que "20% del nominal" no es un numero del mercado, es un numero que
depende de que papeles opera cada uno. Aca se traduce a dolares por accion, que
es la unidad en la que existe de verdad, y se compara contra lo que se sabe que
cuestan los locates.
"""
import statistics, sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config, motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
R = 50.0

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
filas = []
for d in pob:
    j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=R, max_trades=10)
    if not j: continue
    # acciones en el PICO de exposicion simultanea
    ev = []
    for t in j["detalle"]:
        ev.append((t["h_ent"], +t["acciones"], +t["nominal"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                   -t["acciones"], -t["nominal"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    acc = nom = pacc = pnom = 0.0
    for _, da, dn in ev:
        acc += da; nom += dn
        if nom > pnom: pnom, pacc = nom, acc
    precio = statistics.median(t["p_ent"] for t in j["detalle"])
    filas.append({"pnl": j["pnl"], "nom": pnom, "acc": pacc, "precio": precio})

n = len(filas)
pnl = statistics.mean(f["pnl"] for f in filas)
nom = statistics.mean(f["nom"] for f in filas)
acc = statistics.mean(f["acc"] for f in filas)
print(f"  {n} jornadas · riesgo ${R:.0f} por dia\n")
print("  UNA JORNADA PROMEDIO, EN DOLARES\n")
print(f"    ganancia bruta                 ${pnl:>8.2f}")
print(f"    exposicion simultanea maxima   ${nom:>8.2f}")
print(f"    acciones en ese pico           {acc:>9.0f}")
print(f"    precio mediano del papel       ${statistics.median(f['precio'] for f in filas):>8.2f}")
print(f"    retorno sobre lo desplegado    {100*pnl/nom:>8.1f}%  en unas horas")

print("\n  QUE SIGNIFICA CADA NIVEL DE LOCATE, EN DOLARES POR ACCION\n")
print(f"  {'% del nominal':>14} {'costo del dia':>14} {'$ por accion':>14} {'queda':>9}")
print("  " + "-"*58)
for pct in (0.01, 0.02, 0.05, 0.10, 0.164, 0.20):
    costo = pct*nom
    print(f"  {pct:>13.1%} {costo:>14.2f} {costo/acc:>14.3f} {pnl-costo:>+9.2f}"
          + ("   <- punto de muerte" if abs(pct-0.164) < .005 else ""))

print("""
  REFERENCIA DE MERCADO. Un locate en un papel dificil de prestar se cobra
  entre $0.01 y $0.50 por accion segun cuan escaso este. Los de $0.30-$0.50
  son los casos extremos: float minimo, todo el mundo queriendo el mismo papel.
""")
print("  DISTRIBUCION DE PRECIOS DE LOS PAPELES QUE OPERAMOS\n")
pr = sorted(f["precio"] for f in filas)
q = lambda p: pr[int(p*(len(pr)-1))]
print(f"    p10 ${q(.10):.2f}  ·  p25 ${q(.25):.2f}  ·  mediana ${q(.50):.2f}  ·  "
      f"p75 ${q(.75):.2f}  ·  p90 ${q(.90):.2f}")
print(f"\n  El 20% del nominal en un papel de ${q(.50):.2f} es "
      f"${0.20*q(.50):.2f} POR ACCION de locate.")
print(f"  El punto de muerte (16,4%) es ${0.164*q(.50):.2f} por accion.")

print("\n  Y AL REVES: que ret/nom hace falta segun lo que cueste el locate\n")
print(f"  {'$/accion':>10} {'% del nominal':>15} {'neto/jornada':>14} {'anual (3,2/mes)':>17}")
print("  " + "-"*60)
med = statistics.median(f["precio"] for f in filas)
for cps in (0.01, 0.02, 0.05, 0.10, 0.20, 0.40):
    pct = cps/med
    neto = pnl - pct*nom
    print(f"  {('$'+format(cps,'.2f')):>10} {pct:>14.1%} {neto:>+14.2f} "
          f"{('$'+format(int(neto*3.2*12),',')):>17}")
