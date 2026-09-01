#!/usr/bin/env python3
"""La estructura de costos REAL de Trade The Pool, sacada de sus terminos.

Todo el proyecto modelo el costo como \$0,04 por accion y el locate como un
porcentaje del nominal. Los dos numeros eran inventados. Los reales, de la
pagina de terminos de la firma:

    comision:  1/2 centavo por accion, MINIMO \$0,75 POR ORDEN CUMPLIDA
    locate:    no figura en los terminos (una resena dice que no cobran)

Y eso da vuelta la optimizacion entera. El minimo por orden es un costo FIJO:
por debajo de 150 acciones se paga \$0,75 sin importar cuantas sean. O sea que
la variable que manda deja de ser "cuantas acciones" y pasa a ser "cuantas
ORDENES", y el tamano por orden se vuelve gratis hasta 150 acciones.

Es exactamente al reves de como veniamos optimizando: durante dos dias buscamos
minimizar acciones porque el locate se cobraba por accion.

Cada trade son DOS ordenes: abrir y cerrar.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9
MIN_ORDEN, POR_ACCION = 0.75, 0.005

def comision(acciones):
    """Dos ordenes por trade, cada una con su minimo."""
    return 2 * max(MIN_ORDEN, acciones * POR_ACCION)

def sig(piso):
    return lambda d: [i for i in señales_swing(d, desde=10.0)
                      if (d.bars[i][4] or 0) >= piso]

def correr(ap, ex, piso, riesgo):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    S = []
    for d in pob:
        j = jornada(d, sig(piso), lado="short", stop_pct=45.0, riesgo=riesgo,
                    max_trades=40)
        if not j: continue
        # El motor ya cobro \$0,04/accion una vez por trade. Se revierte y se
        # cobra la comision real, que son dos ordenes con su minimo cada una.
        bruto = j["pnl"]
        com_real = 0.0
        for t in j["detalle"]:
            bruto += t["acciones"] * 0.04          # devolver lo que cobro el motor
            com_real += comision(t["acciones"])
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da; pa = max(pa, a)
        S.append({"d": d.d, "bruto": bruto, "com": com_real, "acc": pa,
                  "tr": j["trades"],
                  "acc_orden": statistics.mean(t["acciones"] for t in j["detalle"])})
    return S

print("  LA COMISION REAL vs LA QUE MODELABAMOS\n")
print(f"  {'riesgo/dia':>11} {'acc/orden':>10} {'modelo \$0,04':>13} {'real (min \$0,75)':>17} {'razon':>8}")
print("  " + "-"*66)
for riesgo in (50, 100, 200, 400, 800, 2000):
    S = correr("reclaim", 100.0, 2.0, riesgo)
    if not S: continue
    ao = statistics.mean(x["acc_orden"] for x in S)
    viejo = statistics.mean(sum(t*0.04 for t in [x["acc_orden"]]*x["tr"]) for x in S)
    real = statistics.mean(x["com"] for x in S)
    print(f"  {('\$'+str(riesgo)):>11} {ao:>10.0f} {viejo:>12.2f} {real:>16.2f} "
          f"{real/viejo if viejo else 0:>7.1f}x")

print(f"\n  y el punto donde el minimo deja de aplicar: "
      f"{MIN_ORDEN/POR_ACCION:.0f} acciones por orden\n")

print("  LA ECONOMIA, CON LOS COSTOS REALES Y SIN LOCATE\n")
print("  plan \$20.000 -> tope de drawdown 4% = \$800 (dato de sus terminos)")
print("  f=0,40 -> riesgo \$320/dia · reparto 70/30\n")
print(f"  {'config':<26} {'ses/m':>6} {'tr/m':>5} {'bruto/m':>9} {'comision':>9} "
      f"{'neto/m':>9} {'tuyo 70%':>9} {'al ano':>10}")
print("  " + "-"*88)
for lab, ap, ex, piso in (("reclaim exp>=100 · \$2","reclaim",100.0,2.0),
                          ("reclaim sin exp · \$2","reclaim",0.0,2.0),
                          ("reclaim sin exp · sin piso","reclaim",0.0,0.0),
                          ("sin apertura exp>=50 · \$2",None,50.0,2.0)):
    S = correr(ap, ex, piso, 320.0)
    if len(S) < 15: continue
    ses = len({x["d"] for x in S})/MESES
    b = statistics.mean(x["bruto"] for x in S); c = statistics.mean(x["com"] for x in S)
    tr = sum(x["tr"] for x in S)/MESES
    neto = (b-c)*ses
    print(f"  {lab:<26} {ses:>6.1f} {tr:>5.0f} {b*ses:>+9.2f} {-c*ses:>9.2f} "
          f"{neto:>+9.2f} {neto*0.70:>+9.2f} {('\$'+format(int(neto*0.70*12),',')):>10}")
