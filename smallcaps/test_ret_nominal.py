#!/usr/bin/env python3
"""Si el locate se paga por exposicion SIMULTANEA, cuantos tramos convienen?

El bug que esto explora: la senal de swing entra varias veces en la misma bajada
y todos los tramos se sostienen hasta el cierre, asi que el locate hay que
reservarlo para la SUMA, no para el mayor. Con eso el punto de muerte del sistema
cayo de 31% a 5,8%.

La pregunta ahora es si limitar la cantidad de tramos concurrentes lo recupera:
menos tramos = menos nominal reservado = menos locate, pero tambien menos bruto.
Hay un optimo y no se adivina.
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
    print(f"\n  {lab.upper()} — cuantos tramos como maximo\n")
    print(encabezado()); print("  " + "-"*104)
    for mt in (1, 2, 3, 5, 10):
        print(linea(evaluar(f"tramos{mt}·{lab}", d10, dias=dias, familia="tramos",
                            stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                            max_trades=mt, notas=f"maximo {mt} tramos")))

print("\n  Y SI SE FUERZA LA SALIDA para que no se solapen\n")
print(encabezado()); print("  " + "-"*104)
for h in (11.0, 12.0, 13.0):
    for lab, ap, ex in (("fade·exp150", "fade", 150), ("reclaim·exp100", "reclaim", 100)):
        print(linea(evaluar(f"sal{int(h)}·{lab}", d10, dias=dias, familia="salida-pico",
                            stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                            salida_h=h, notas=f"cierra {h:.0f}:00")))
