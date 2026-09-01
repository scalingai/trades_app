#!/usr/bin/env python3
"""Si hubieramos abierto la cuenta de fondeo hace 30 dias, que habria pasado.

No es una simulacion con remuestreo: son LOS DIAS QUE PASARON, del 2026-08-02
al 2026-08-31, con el resultado que la estrategia habria producido en cada uno.

Una aclaracion que cambia como se lee: del 02 al 12 de agosto esos dias estaban
en el censo (el sistema los vio al calibrarse); del 13 al 31 no existian. La
segunda mitad es la unica limpia, y se marca.
"""
import sys, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
DESDE, HASTA, FRESCO = "2026-08-02", "2026-08-31", "2026-08-12"
TOPE, OBJ, EVAL, SPLIT = 1000.0, 1.2, 97.0, 0.70

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

dias = [d for d in universo() if DESDE <= d.d <= HASTA]
print(f"  ventana {DESDE} -> {HASTA}  ·  {len(dias)} eventos en el censo")
print(f"  de esos, posteriores al calibrado ({FRESCO}): "
      f"{sum(1 for d in dias if d.d > FRESCO)}\n")

CONF = [("reclaim·exp100 (la elegida)", "reclaim", 100),
        ("fade·exp150", "fade", 150),
        ("fade·exp100", "fade", 100),
        ("sin filtro de apertura·exp100", None, 100)]

RES = {}
for lab, ap, ex in CONF:
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    filas = []
    for d in sorted(pob, key=lambda x: x.d):
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if j:
            filas.append((d.d, d.ticker, j["trades"], j["pnl"]/50.0,
                          j["nominal"]/50.0))
    RES[lab] = filas
    print(f"  {lab}")
    if not filas:
        print("    ninguna jornada operable en el mes\n"); continue
    print(f"    {'fecha':>11} {'papel':>7} {'tr':>3} {'pnl R':>8} {'nom R':>7} "
          f"{'ret/nom':>9} {'':>6}")
    for f in filas:
        marca = "fresco" if f[0] > FRESCO else "visto"
        print(f"    {f[0]:>11} {f[1]:>7} {f[2]:>3} {f[3]:>+8.3f} {f[4]:>7.2f} "
              f"{100*f[3]/f[4] if f[4] else 0:>8.1f}% {marca:>6}")
    m = statistics.mean(x[3] for x in filas); nn = statistics.mean(x[4] for x in filas)
    print(f"    {'':>11} {'TOTAL':>7} {sum(x[2] for x in filas):>3} "
          f"{sum(x[3] for x in filas):>+8.3f} {'':>7} "
          f"{100*m/nn if nn else 0:>8.1f}%\n")

print("\n  LA CUENTA: 3 cuentas de $20.000 abiertas el 02/08\n")
print("  El objetivo de la evaluacion es +6% del plan ($1.200) sin tocar -5% ($1.000).")
print(f"  {'estrategia':>30} {'ses':>4} {'f':>6} {'locate':>7} {'ganado $':>10} "
      f"{'% del objetivo':>15} {'estado':>12}")
print("  " + "-"*92)
for lab, filas in RES.items():
    if not filas: continue
    for f in (0.28, 0.40):
        for loc in (0.05, 0.20):
            eq = 0.0; muerta = False
            for _, _, _, pR, nR in filas:
                eq += (pR - loc*nR) * f
                if eq <= -1.0: muerta = True; break
            ganado = eq * TOPE
            estado = ("REVENTADA" if muerta else
                      "PASA" if eq >= OBJ else "en evaluacion")
            print(f"  {lab[:30]:>30} {len(filas):>4} {f:>6.2f} {loc:>6.0%} "
                  f"{ganado:>+10.0f} {100*eq/OBJ:>14.0f}% {estado:>12}")
    print()

print("""  Lo que dice la ultima columna: con 3-6 jornadas en un mes no se llega a
  ninguna parte. El objetivo son +1,2 unidades de tope y una jornada tipica
  mueve 0,1-0,2. La evaluacion necesita ~13 sesiones operables, o sea entre
  dos y cuatro meses de calendario. Un mes no es una muestra, es una anecdota.""")
