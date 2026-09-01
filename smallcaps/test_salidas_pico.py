#!/usr/bin/env python3
"""Las salidas, remedidas con el nominal = exposicion SIMULTANEA.

**Por que hay que rehacerlo.** El estudio de ayer concluyo que ninguna salida
mejora, y su argumento estructural era textual:

    "nominal = riesgo*100/stop -- el precio se cancela y la salida NO entra en
     la formula. La familia de salidas no tiene ninguna palanca sobre el
     denominador."

Eso era cierto con el nominal viejo (el trade mas grande). Con el nominal
correcto es FALSO: la senal de swing abre varios tramos y todos se sostienen
hasta el cierre, asi que cerrar antes hace que se SOLAPEN MENOS, y el pico de
exposicion baja. La salida si tiene palanca sobre el denominador — la mas
directa de todas.

Y el numerador tambien esta en juego: se devuelve el 44% del maximo a favor.

    SMALLCAPS_CENSO=1 python test_salidas_pico.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, evaluar, linea, encabezado
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
d10 = lambda d: señales_swing(d, desde=10.0)
dias = universo()
L = {"min_ratio_vol": 0.0, "min_dolar": 0.0}

for lab, ap, ex in (("fade·exp150", "fade", 150), ("reclaim·exp100", "reclaim", 100)):
    print(f"\n  {lab.upper()} — objetivo de toma de ganancia\n")
    print(encabezado()); print("  " + "-"*104)
    for obj in (None, 5, 8, 10, 15, 20, 30, 50):
        nm = "sin-objetivo" if obj is None else f"obj{obj}"
        print(linea(evaluar(f"pico·{nm}·{lab}", d10, dias=dias, familia="salida-pico",
                            stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                            objetivo_pct=obj,
                            notas="nominal = exposicion simultanea")))

print("""
  La columna que decide es ret/nom: cerrar antes resigna cola derecha (baja el
  bruto) pero achica el solape entre tramos (baja el nominal). Cual gana no se
  puede razonar, hay que mirarlo.
""")
