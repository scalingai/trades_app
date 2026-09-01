#!/usr/bin/env python3
"""La frontera frecuencia vs margen: donde se van las sesiones y que cuestan.

Agus: "no pueden ser tan pocas sesiones por mes, se opera casi todos los dias".

Tiene razon en la objecion. 3,3 sesiones/mes no sostiene una operativa ni junta
muestra ni pasa una evaluacion de fondeo, que necesita ~13. Pero la respuesta
no es simplemente aflojar filtros: una estrategia con esperanza negativa operada
mas seguido pierde mas rapido, no menos.

Lo que hay que ver es la FRONTERA. Cada corte compra margen y paga frecuencia,
y la pregunta es si existe algun punto con las dos cosas. Se mide en la unidad
correcta: el punto de muerte en DOLARES POR ACCION, que es como se cobra el
locate, y no en porcentaje del nominal.
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

def medir(ap, ex, maxf=47e6, ventana=60):
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=maxf)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    S = []
    for d in pob:
        j = jornada(d, vent(ventana), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if not j: continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da; pa = max(pa, a)
        S.append((d.d, j["pnl"], pa, j["nominal"]))
    if len(S) < 20: return None
    fechas = len({x[0] for x in S})
    b = statistics.mean(x[1] for x in S); acc = statistics.mean(x[2] for x in S)
    nom = statistics.mean(x[3] for x in S)
    return {"n": len(S), "fechas": fechas, "ses_mes": fechas/MESES,
            "bruto": b, "acc": acc, "muerte_cps": b/acc if acc else 0,
            "ret_nom": 100*b/nom if nom else 0,
            "mensual": b*fechas/MESES}

print("  LA FRONTERA — cada fila afloja un corte\n")
print(f"  {'configuracion':<34} {'ses/mes':>8} {'bruto/ses':>10} "
      f"{'muerte $/acc':>13} {'bruto/mes':>10}")
print("  " + "-"*82)
CASOS = [
  ("reclaim · exp>=150",            "reclaim", 150, 47e6),
  ("reclaim · exp>=100  (la actual)","reclaim", 100, 47e6),
  ("reclaim · exp>=50",             "reclaim",  50, 47e6),
  ("reclaim · sin corte de exp",    "reclaim",   0, 47e6),
  ("reclaim · exp>=100 · sin float","reclaim", 100, None),
  ("fade · exp>=150",               "fade",    150, 47e6),
  ("fade · exp>=100",               "fade",    100, 47e6),
  ("fade · sin corte de exp",       "fade",      0, 47e6),
  ("sin apertura · exp>=150",       None,      150, 47e6),
  ("sin apertura · exp>=100",       None,      100, 47e6),
  ("sin apertura · sin corte",      None,        0, 47e6),
  ("sin apertura · sin nada",       None,        0, None),
]
res = {}
for lab, ap, ex, mf in CASOS:
    r = medir(ap, ex, mf)
    if not r: 
        print(f"  {lab:<34} {'(muestra corta)':>8}"); continue
    res[lab] = r
    marca = "  <<<" if r["ses_mes"] >= 10 and r["muerte_cps"] >= 0.10 else ""
    print(f"  {lab:<34} {r['ses_mes']:>8.1f} {r['bruto']:>+10.2f} "
          f"{('$'+format(r['muerte_cps'],'.3f')):>13} {r['mensual']:>+10.2f}{marca}")

print("""
  'bruto/mes' es lo que produce la configuracion en un mes ENTERO, que es lo que
  de verdad importa: una estrategia que rinde el triple pero opera un sexto de
  las veces produce la mitad. 'muerte $/acc' es cuanto locate por accion aguanta.
""")

print("  LO MISMO, PERO NETO, SEGUN EL LOCATE REAL\n")
print(f"  {'configuracion':<34} {'ses/mes':>8} " + " ".join(
    f"{('$'+format(c,'.2f')):>9}" for c in (0.02, 0.05, 0.10, 0.20)))
print("  " + "-"*82)
for lab in res:
    r = res[lab]
    fila = [f"{(r['bruto']-c*r['acc'])*r['ses_mes']:>+9.2f}"
            for c in (0.02, 0.05, 0.10, 0.20)]
    print(f"  {lab:<34} {r['ses_mes']:>8.1f} " + " ".join(fila))
print("""
  Cada celda es el bruto MENSUAL neto de locate, con riesgo $50/dia. Escala
  lineal con el riesgo: en una cuenta de fondeo con R=$400 se multiplica por 8.
""")
