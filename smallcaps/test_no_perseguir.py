#!/usr/bin/env python3
"""Los dos puntos de Agus mirando la bitacora del 02/10 en TIGR.

  1. "tendrias que haber cerrado en profit"  -> el objetivo optimo NO es fijo:
     depende del locate, porque cerrar antes achica el pico de exposicion.
  2. "le volviste a agregar y saliste casi BE" -> el segundo tramo entro a las
     11:55, DESPUES del minimo del dia. Perseguir tarde.

El punto 2 se prueba acotando cuanto tiempo despues del PRIMER tramo se puede
seguir agregando. Es una regla observable en vivo (no mira el futuro) y ataca
justo lo que el vio.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, evaluar, linea, encabezado
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
dias = universo()
L = {"min_ratio_vol": 0.0, "min_dolar": 0.0}


def ventana(mins):
    """Solo agrega tramos dentro de `mins` minutos del primero."""
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx:
            return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= mins / 60.0]
    return f


print("  1) EL OBJETIVO OPTIMO SEGUN CUANTO SEA EL LOCATE\n")
res = {}
for lab, ap, ex in (("fade·exp150", "fade", 150), ("reclaim·exp100", "reclaim", 100)):
    res[lab] = {}
    for obj in (None, 5, 8, 10, 15, 20, 30, 50):
        r = evaluar(f"tmp·{obj}·{lab}", lambda d: señales_swing(d, desde=10.0),
                    dias=dias, familia="tmp", stop=45.0,
                    pob={"min_expansion": ex, **L}, apertura=ap,
                    objetivo_pct=obj, guardar=False)
        if "error" not in r:
            res[lab][obj] = (r["bruto_R"], r["nom_R"])
for lab in res:
    print(f"  {lab}")
    print(f"    {'locate':>8} " + " ".join(
        f"{('sin' if o is None else str(o)+'%'):>8}" for o in res[lab]))
    print("    " + "-"*(9 + 9*len(res[lab])))
    for loc in (0.0, .05, .10, .15, .20, .25):
        fila, mejor = [], None
        for o, (b, nn) in res[lab].items():
            v = b - loc*nn
            fila.append(v)
            if mejor is None or v > mejor[1]: mejor = (o, v)
        print(f"    {loc:>7.0%} " + " ".join(f"{v:>+8.3f}" for v in fila)
              + f"   mejor: {'sin' if mejor[0] is None else str(mejor[0])+'%'}"
              + ("  POSITIVO" if mejor[1] > 0 else ""))
    print()

print("\n  2) NO PERSEGUIR: hasta cuando conviene seguir agregando\n")
print(encabezado()); print("  " + "-"*104)
for lab, ap, ex in (("fade·exp150", "fade", 150), ("reclaim·exp100", "reclaim", 100)):
    for mins in (0, 15, 30, 45, 60, 120, 999):
        et = "solo-1" if mins == 0 else ("sin-tope" if mins == 999 else f"{mins}min")
        print(linea(evaluar(f"vent·{et}·{lab}", ventana(mins), dias=dias,
                            familia="ventana", stop=45.0,
                            pob={"min_expansion": ex, **L}, apertura=ap,
                            notas=f"agrega hasta {mins} min del primer tramo")))
    print()
