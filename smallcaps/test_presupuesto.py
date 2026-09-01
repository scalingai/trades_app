#!/usr/bin/env python3
"""El presupuesto de riesgo miraba el futuro. Acá está el número y la remedición.

EL ERROR (el séptimo del proyecto)
----------------------------------
`motor.jornada` decide si abre el tramo N con esta línea:

    if pnl - r_trade < -riesgo:          # el límite diario, sobre el acumulado
        break

`pnl` es la suma del PnL **final** de los tramos anteriores. Pero el 80% de los
tramos se abren con otro tramo **todavía vivo** —842 de 1.037 en fade·exp150,
310 de 387 en reclaim·exp100— así que para decidir si abre el tramo N el motor
ya sabe cómo va a terminar algo que a esa hora sigue abierto.

Eso no es un límite de riesgo. Es un filtro que saca exactamente los tramos que
iban a perder. El tell está en la cantidad de trades: la versión que mira el
futuro es la que MENOS opera y la que MÁS gana.

LO QUE SE MIDE ACÁ
------------------
  A) el costo del error, con lo único que cambia siendo la regla de presupuesto
  B) la grilla de ventana de agregado, remedida honesta (era el último hallazgo
     bueno del proyecto: 14,5% → 17,0%, y acorta justo la ventana donde vive el
     oráculo)
  C) la grilla de cantidad de tramos, remedida honesta
  D) "esperar el tramo k": saltear las primeras señales del día. Sale de que
     todos los mecanismos que reducen exposición bajan el ret/nom menos éste,
     que la reduce sin tocar los tramos que quedan.

CONTROL DE CORDURA. Antes de leer cualquier fila hay que haber corrido
`python exposicion.py --control`: incluye la identidad `acumular + presupuesto
futuro == motor.jornada` sesión por sesión. Si esa falla, esta tabla no compara
lo que dice comparar.

    python test_presupuesto.py
"""

from __future__ import annotations

import sys

import motor
from chavineta import clasificar_apertura as _clasificar
from dias import hora
from exposicion import con_politica, ventana
from motor import evaluar, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LIMPIO = {"min_ratio_vol": 0.0, "min_dolar": 0.0}
CASOS = [("fade·exp150", "fade", 150.0, 999), ("reclaim·exp100", "reclaim", 100.0, 60)]
PRESUPUESTOS = [
    ("futuro (lo de hoy)", "futuro"),
    ("mtm — cerrados + vivos a mercado", "mtm"),
    ("realizado — sólo cerrados", "realizado"),
    ("ninguno — sin límite diario", "ninguno"),
]


def desde_tramo(k, mins=999):
    """La señal, salteando los primeros `k` tramos del día.

    Es la única forma de bajar la exposición que no toca los tramos que quedan:
    un tope o un rolado cambian el trade (lo cierran antes o no lo abren), y
    esto sólo corre el arranque. Si el ret/nom sube, el edge no está en el
    primer swing del día; si baja, sí está y hay que entrar temprano.
    """
    base = ventana(mins)

    def f(d):
        return base(d)[k:]
    return f


def fila(etiqueta, r, ancho=34):
    if "error" in r:
        return f"  {etiqueta:<{ancho}} {r['error']}"
    return (f"  {etiqueta:<{ancho}} {r['ses_mes']:>6.1f} {r['trades_mes']:>7} "
            f"{r['bruto_R']:>+9.3f} {r['nom_R']:>7.2f} {r['ret_nom']:>8.1f}% "
            f"{r['neto20_R']:>+10.3f} "
            f"{(r['P1'] or {}).get('ret_nom', 0):>6.1f}% "
            f"{(r['P2'] or {}).get('ret_nom', 0):>6.1f}% "
            f"{(r['replica'] if r['replica'] is not None else 0):>7.1f}p")


def cabecera(ancho=34):
    return (f"  {'':<{ancho}} {'ses/m':>6} {'trades':>7} {'bruto R':>9} {'nom R':>7} "
            f"{'ret/nom':>9} {'neto@20%':>10} {'P1':>7} {'P2':>7} {'brecha':>8}")


def correr(nombre, sig, *, dias, ap, ex, presupuesto, guardar=False, **pol):
    motor.jornada = con_politica(presupuesto=presupuesto, **pol)
    return evaluar(nombre, sig, dias=dias, familia="presupuesto", stop=45.0,
                   apertura=ap, pob={"min_expansion": ex, **LIMPIO},
                   guardar=guardar, notas=f"presupuesto {presupuesto}")


def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    orig = motor.jornada
    try:
        print("=" * 108)
        print("  A) CUÁNTO VALÍA EL ORÁCULO — cambia SÓLO la regla de presupuesto")
        print("=" * 108)
        for lab, ap, ex, vm in CASOS:
            print(f"\n  {lab.upper()}\n")
            print(cabecera())
            print("  " + "-" * 106)
            for et, pres in PRESUPUESTOS:
                r = correr(f"presu·{pres}·{lab}", ventana(vm), dias=dias, ap=ap,
                           ex=ex, presupuesto=pres, guardar=True)
                print(fila(et, r))

        print("\n" + "=" * 108)
        print("  B) VENTANA DE AGREGADO, REMEDIDA HONESTA (presupuesto=mtm)")
        print("     El hallazgo de ayer era 60 min = 17,0% contra 14,5% sin tope.")
        print("=" * 108)
        for lab, ap, ex, _ in CASOS:
            print(f"\n  {lab.upper()}\n")
            print(cabecera(ancho=20))
            print("  " + "-" * 92)
            for vm in (15, 30, 45, 60, 90, 120, 999):
                et = "sin tope" if vm == 999 else f"agrega {vm} min"
                r = correr(f"vent-h·{vm}·{lab}", ventana(vm), dias=dias, ap=ap,
                           ex=ex, presupuesto="mtm")
                print(fila(et, r, ancho=20))

        print("\n" + "=" * 108)
        print("  C) CANTIDAD MÁXIMA DE TRAMOS, REMEDIDA HONESTA (presupuesto=mtm)")
        print("=" * 108)
        for lab, ap, ex, vm in CASOS:
            print(f"\n  {lab.upper()}\n")
            print(cabecera(ancho=20))
            print("  " + "-" * 92)
            for mt in (1, 2, 3, 5, 10):
                motor.jornada = con_politica(presupuesto="mtm")
                r = evaluar(f"tramos-h·{mt}·{lab}", ventana(vm), dias=dias,
                            familia="presupuesto", stop=45.0, apertura=ap,
                            max_trades=mt, pob={"min_expansion": ex, **LIMPIO},
                            guardar=False, notas="presupuesto mtm")
                print(fila(f"máx {mt} tramos", r, ancho=20))

        print("\n" + "=" * 108)
        print("  D) ESPERAR EL TRAMO k — saltear las primeras señales del día")
        print("     Reduce exposición sin cambiar los tramos que quedan.")
        print("=" * 108)
        for lab, ap, ex, vm in CASOS:
            print(f"\n  {lab.upper()}\n")
            print(cabecera(ancho=20))
            print("  " + "-" * 92)
            for k in (0, 1, 2, 3, 4):
                et = "desde el 1ro" if k == 0 else f"desde el {k+1}º"
                r = correr(f"desde-h·{k}·{lab}", desde_tramo(k, vm), dias=dias,
                           ap=ap, ex=ex, presupuesto="mtm")
                print(fila(et, r, ancho=20))
    finally:
        motor.jornada = orig
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
