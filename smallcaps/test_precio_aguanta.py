#!/usr/bin/env python3
"""El gradiente de precio: ¿es la palanca que faltaba o es una celda con suerte?

QUÉ PASÓ. Al cambiar la unidad de `ret/nom` a centavos por acción apareció lo que
parece la palanca más grande del proyecto: en el reclaim, subir el piso de precio
de entrada de $0 a $5 lleva el punto de muerte de 23,9c a 211c por acción. Casi
diez veces.

POR QUÉ NO SE PUEDE CREER TODAVÍA. La predicción escrita antes de medir
(`centavos.py`) era que el punto de muerte escalara **linealmente con el precio**:
la posición se dimensiona por riesgo, así que un papel tres veces más caro se
shortea con un tercio de las acciones, y el mismo porcentaje de caída deja tres
veces más centavos. Esa parte es aritmética y no hace falta creerla, se deduce.

Lo medido la supera por casi 3x: entre $3,04 y $9,43 de precio mediano el
componente mecánico predice ~74c y salieron 211c. La diferencia es que el
`ret/nom` también sube —de 12,0% a 23,4%—, o sea que estaría diciendo que **los
gappers caros caen MÁS en porcentaje**. Eso es una afirmación sobre el mercado,
no sobre la aritmética, y es la contraria del mecanismo que declaré esperar (más
precio → más capitalización → menos pólvora minorista → menos derrumbe).

Cuando lo medido supera lo predicho por 3x y encima en la dirección que el
mecanismo declarado no explica, la regla 4 del proyecto dice qué es: hasta que se
demuestre lo contrario, un artefacto.

LAS CINCO PRUEBAS, con el resultado que mata a cada una
------------------------------------------------------
  1. **Descomposición mecánico / excedente.** Cuánto del salto explica la
     aritmética del tamaño y cuánto queda sin explicar. MATA: nada por sí sola;
     es la que dice cuánto hay que justificar en las otras cuatro.
  2. **Bandas DISJUNTAS con bootstrap.** Los cortes "≥ $X" son subconjuntos
     anidados y su monotonía casi no es evidencia — el de $5 está adentro del de
     $3. Las bandas separadas sí lo son. MATA: que el intervalo de la banda cara
     se pise con el de la barata.
  3. **Precio de referencia FIJO del día contra precio entrada-a-entrada.** Es
     el control que más me preocupaba: filtrar por el precio de CADA entrada
     selecciona, dentro de un mismo día que cae, las entradas tempranas para las
     bandas caras y las tardías para las baratas. Eso solo ya fabricaría un
     gradiente sin que exista ninguna propiedad de la población. El control usa
     el precio a las 10:00, uno por día, que no puede tener ese sesgo. MATA: que
     el gradiente se aplane con el precio fijo.
  4. **Partición P1/P2 dentro de la banda cara.** MATA: brecha grande, o una
     mitad sola sosteniendo todo.
  5. **De dónde sale la plata.** Cuántas sesiones aportan el excedente. MATA:
     que sacando dos o tres sesiones el gradiente desaparezca.

    python test_precio_aguanta.py
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

import motor
from centavos import (CORTE_CENSO, CORTE_P, metricas, sesiones, señal_con_piso,
                      ventana)
from chavineta import clasificar_apertura as _clasificar
from motor import universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SEMILLA = 20260901
B = 10_000
CASOS = [("reclaim·exp100", "reclaim", 100.0, 60),
         ("fade·exp150", "fade", 150.0, 999)]
BANDAS = [("$0 – $2", 0.0, 2.0), ("$2 – $4", 2.0, 4.0), ("$4 – $8", 4.0, 8.0),
          ("$8 en adelante", 8.0, None)]


def ref_10(a, b=None):
    """Filtro de DÍA por el precio a las 10:00 — uno solo por sesión.

    Es la contracara de `señal_con_piso`, que filtra entrada por entrada. La
    diferencia entre los dos es justo el sesgo que hay que descartar.
    """
    def f(d):
        p = d.precio_en(10.0)
        return bool(p) and p >= a and (b is None or p < b)
    return f


def muerte(filas):
    if not filas:
        return None
    acc = statistics.mean(x[4] for x in filas)
    return 100 * statistics.mean(x[2] for x in filas) / acc if acc else None


def boot(filas, rng):
    out = []
    for _ in range(B):
        m = muerte([rng.choice(filas) for _ in filas])
        if m is not None:
            out.append(m)
    return sorted(out)


def p(v, q):
    return v[max(0, min(len(v) - 1, int(q * len(v))))]


def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    vistos = [d for d in dias if d.d <= CORTE_CENSO]

    for lab, ap, ex, vm in CASOS:
        base = sesiones(vistos, ap, ex, señal_con_piso(vm, 0.0))
        mb = metricas(base)
        print("=" * 100)
        print(f"  {lab.upper()}   ·   base: {mb['n']} sesiones · precio mediano "
              f"${mb['precio']:.2f} · muerte {mb['muerte_c']:.1f}c · "
              f"ret/nom {mb['ret_nom']:.1f}%")
        print("=" * 100)

        # --- 1) descomposición ------------------------------------------
        print("\n  1) MECÁNICO vs EXCEDENTE — cuánto explica la aritmética del tamaño\n")
        print(f"  {'piso':>12} {'n':>5} {'$ ent':>7} {'muerte':>9} "
              f"{'predicho':>10} {'excedente':>11} {'ret/nom':>9}")
        print("  " + "-" * 70)
        for piso in (0.0, 2.0, 3.0, 5.0, 8.0):
            f = sesiones(vistos, ap, ex, señal_con_piso(vm, piso))
            m = metricas(f)
            if not m:
                print(f"  {('>= $%.0f' % piso):>12} {len(f):>5}   muestra corta")
                continue
            # el mecánico: mismo ret/nom que la base, sólo cambia el precio
            pred = mb["muerte_c"] * m["precio"] / mb["precio"]
            print(f"  {('todo' if not piso else '>= $%.0f' % piso):>12} {m['n']:>5} "
                  f"{m['precio']:>7.2f} {m['muerte_c']:>8.1f}c {pred:>9.1f}c "
                  f"{m['muerte_c']/pred if pred else 0:>10.2f}x {m['ret_nom']:>8.1f}%")

        # --- 2) bandas disjuntas con bootstrap ---------------------------
        print("\n  2) BANDAS DISJUNTAS — bootstrap de 10.000 sobre cada una\n")
        print(f"  {'banda':>16} {'n':>5} {'$ ent':>7} {'muerte':>9} "
              f"{'p5':>9} {'p95':>9} {'P(>0)':>8} {'ret/nom':>9}")
        print("  " + "-" * 80)
        rng = random.Random(SEMILLA)
        for et, a, b in BANDAS:
            f = sesiones(vistos, ap, ex, señal_con_piso(vm, a, b))
            if len(f) < 12:
                print(f"  {et:>16} {len(f):>5}   muestra corta")
                continue
            # `metricas` exige 20 sesiones y estas bandas tienen 14-18. Se
            # calcula igual a mano PORQUE ESTÁ DECLARADO que la muestra es
            # corta; lo que no se puede hacer es escribir un 0,0 en la columna
            # de ret/nom, que se lee como "no rinde" cuando lo que pasa es que
            # el atajo no lo calculó.
            nomm = statistics.mean(x[3] for x in f)
            m = {"muerte_c": muerte(f), "n": len(f),
                 "precio": statistics.median(x[5] for x in f),
                 "ret_nom": 100 * statistics.mean(x[2] for x in f) / nomm if nomm else 0.0}
            bs = boot(f, random.Random(SEMILLA))
            print(f"  {et:>16} {len(f):>5} {m['precio']:>7.2f} "
                  f"{muerte(f):>8.1f}c {p(bs,.05):>8.1f}c {p(bs,.95):>8.1f}c "
                  f"{100*sum(1 for x in bs if x>0)/len(bs):>7.0f}% "
                  f"{m['ret_nom']:>8.1f}%")

        # --- 3) precio fijo del día vs precio entrada-a-entrada -----------
        print("\n  3) CONTROL DEL CONFUNDIDOR — precio de referencia FIJO (10:00)\n")
        print(f"  {'banda':>16} {'entrada-a-entrada':>26}   {'referencia fija 10:00':>26}")
        print(f"  {'':>16} {'n':>5} {'$ ent':>7} {'muerte':>9}   {'n':>5} {'$ ent':>7} {'muerte':>9}")
        print("  " + "-" * 76)
        for et, a, b in BANDAS + [("todo", 0.0, None)]:
            fe = sesiones(vistos, ap, ex, señal_con_piso(vm, a, b))
            fr = sesiones(vistos, ap, ex, ventana(vm), pob_dia=ref_10(a, b))
            def _c(f):
                if len(f) < 8:
                    return f"{'muestra corta':>25}"
                return (f"{len(f):>5} {statistics.median(x[5] for x in f):>7.2f} "
                        f"{muerte(f):>8.1f}c")
            print(f"  {et:>16} {_c(fe)}   {_c(fr)}")

        # --- 4) P1/P2 dentro de la banda cara ----------------------------
        print("\n  4) PARTICIÓN P1/P2 DENTRO DE CADA PISO\n")
        print(f"  {'piso':>12} {'n P1':>6} {'muerte P1':>11} {'n P2':>6} "
              f"{'muerte P2':>11}")
        print("  " + "-" * 52)
        for piso in (0.0, 3.0, 5.0):
            f = sesiones(vistos, ap, ex, señal_con_piso(vm, piso))
            f1 = [x for x in f if x[0] < CORTE_P]
            f2 = [x for x in f if x[0] >= CORTE_P]
            m1, m2 = muerte(f1), muerte(f2)
            print(f"  {('todo' if not piso else '>= $%.0f' % piso):>12} "
                  f"{len(f1):>6} {(f'{m1:.1f}c' if m1 is not None else '—'):>11} "
                  f"{len(f2):>6} {(f'{m2:.1f}c' if m2 is not None else '—'):>11}")

        # --- 5) de dónde sale la plata -----------------------------------
        print("\n  5) DE DÓNDE SALE — sacando las mejores sesiones del piso de $5\n")
        f = sesiones(vistos, ap, ex, señal_con_piso(vm, 5.0))
        if len(f) >= 12:
            orden = sorted(f, key=lambda x: -x[2])
            for k in (0, 1, 2, 3, 5):
                r = orden[k:]
                sac = ", ".join(f"{x[0]} {x[1]}" for x in orden[:k]) or "—"
                print(f"  {('ninguna' if not k else f'las {k} mejores'):>16} "
                      f"n={len(r):>3} muerte {muerte(r):>7.1f}c   {sac[:44]}")
            top = sum(x[2] for x in orden[:3])
            tot = sum(x[2] for x in orden)
            print(f"\n  las 3 mejores sesiones aportan {100*top/tot:.0f}% del PnL "
                  f"de las {len(orden)}")
        else:
            print("  muestra corta")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
