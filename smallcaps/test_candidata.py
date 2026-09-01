#!/usr/bin/env python3
"""La configuración candidata, con todos los cortes encima y en la unidad del costo.

QUÉ ES LA CANDIDATA Y POR QUÉ ESTAS DOS COSAS Y NO CINCO
--------------------------------------------------------
    reclaim · expansión ≥ 100% · entradas desde las 10:00 · ventana de agregado
    de 60 min · stop 45% · presupuesto marcado a mercado · **precio ≥ $2**

Lo único que agrego yo es el piso de precio. Todo lo demás ya estaba. Y agrego
uno solo a propósito: apilar filtros después de haber visto la tabla es cómo se
fabrica una estrategia que existe únicamente en el archivo donde se la fabricó.
El tope de 2 tramos concurrentes también mejora (26,6c contra 23,9c) y se reporta
abajo por separado, **sin sumarlo a la candidata**, para que se vea que es un
efecto chico y no parte del número principal.

EL MECANISMO DEL PISO DE PRECIO, declarado antes de medirlo
-----------------------------------------------------------
El locate se cobra por acción. La posición se dimensiona por riesgo, así que
`acciones = riesgo / (precio · stop%)`: un papel de $1 se shortea con diez veces
más acciones que uno de $10 para el mismo riesgo. El mismo porcentaje de caída
deja diez veces menos centavos por acción para pagar el locate. **En un papel de
$1, un locate de 5 centavos es el 5% del nominal; en uno de $10 es el 0,5%.**
Abajo de cierto precio no hay caída porcentual que alcance.

La predicción era que el punto de muerte escalara linealmente con el precio y que
el `ret/nom` quedara plano. Se cumplió, y se cumplió con una forma que no
esperaba: no es un gradiente, es un **escalón en $2**. Arriba de $2 el `ret/nom`
es plano en 20-22% en las tres bandas; abajo de $2 es −3,8% y el bootstrap le da
26% de probabilidad de ser positivo. O sea que el piso de precio hace dos cosas a
la vez, y sólo una era la esperada: saca la banda donde el edge no existe, y
además multiplica los centavos en la que sí.

LO QUE ESTA PRUEBA NO PUEDE DECIR
---------------------------------
45 sesiones en 22,5 meses son 2 por mes. Con esa frecuencia, un año de operación
real son ~24 sesiones: menos de las que hay acá. Nada de lo que sigue reemplaza
a operarlo, y el intervalo de confianza que se reporta es lo único honesto que se
puede decir sobre el número.

    python test_candidata.py
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

import motor
from centavos import CORTE_CENSO, CORTE_P, sesiones, señal_con_piso
from chavineta import clasificar_apertura as _clasificar
from exposicion import jornada_exp, ventana
from motor import R_BASE, poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SEMILLA = 20260901
B = 10_000
PISO = 2.0

CONFIGS = [
    ("CANDIDATA  reclaim·exp100·precio>=$2", "reclaim", 100.0, 60, PISO),
    ("referencia reclaim·exp100 (sin piso)", "reclaim", 100.0, 60, 0.0),
    ("control    fade·exp150·precio>=$2", "fade", 150.0, 999, PISO),
    ("control    fade·exp150 (sin piso)", "fade", 150.0, 999, 0.0),
]


def muerte(filas):
    if not filas:
        return None
    acc = statistics.mean(x[4] for x in filas)
    return 100 * statistics.mean(x[2] for x in filas) / acc if acc else None


def boot(filas, rng, *, bloques=False):
    if bloques:
        g = defaultdict(list)
        for x in filas:
            g[x[1]].append(x)
        cl = list(g)
        out = []
        for _ in range(B):
            m = []
            for _ in range(len(cl)):
                m.extend(g[rng.choice(cl)])
            v = muerte(m)
            if v is not None:
                out.append(v)
        return sorted(out)
    return sorted(v for v in (muerte([rng.choice(filas) for _ in filas])
                              for _ in range(B)) if v is not None)


def q(v, x):
    return v[max(0, min(len(v) - 1, int(x * len(v))))]


def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    vistos = [d for d in dias if d.d <= CORTE_CENSO]
    nuevos = [d for d in dias if d.d > CORTE_CENSO]

    print("=" * 100)
    print("  LAS CUATRO, LADO A LADO — punto de muerte en centavos por acción")
    print("=" * 100 + "\n")
    print(f"  {'':<38} {'ses/m':>6} {'n':>4} {'$ent':>6} {'acc':>5} "
          f"{'$/ses':>8} {'MUERTE':>9} {'ret/nom':>8}")
    print("  " + "-" * 96)
    todo = {}
    for et, ap, ex, vm, piso in CONFIGS:
        f = sesiones(vistos, ap, ex, señal_con_piso(vm, piso))
        todo[et] = f
        nom = statistics.mean(x[3] for x in f)
        print(f"  {et:<38} {len(f)/motor.MESES:>6.1f} {len(f):>4} "
              f"{statistics.median(x[5] for x in f):>6.2f} "
              f"{statistics.mean(x[4] for x in f):>5.0f} "
              f"{statistics.mean(x[2] for x in f):>+8.2f} {muerte(f):>7.1f}c "
              f"{100*statistics.mean(x[2] for x in f)/nom:>7.1f}%")

    for et, ap, ex, vm, piso in CONFIGS[:1] + CONFIGS[2:3]:
        filas = todo[et]
        print("\n" + "=" * 100)
        print(f"  {et}   ·   {len(filas)} sesiones   ·   muerte {muerte(filas):.1f}c")
        print("=" * 100)

        print("\n  BOOTSTRAP — 10.000 remuestreos\n")
        print(f"  {'unidad':>16} {'p5':>9} {'p50':>9} {'p95':>9} {'P(>0)':>8} "
              f"{'P(>10c)':>9} {'P(>25c)':>9} {'P(>50c)':>9}")
        print("  " + "-" * 84)
        for lab, blo in (("sesión", False), ("ticker entero", True)):
            bs = boot(filas, random.Random(SEMILLA), bloques=blo)
            print(f"  {lab:>16} {q(bs,.05):>8.1f}c {q(bs,.50):>8.1f}c "
                  f"{q(bs,.95):>8.1f}c "
                  + " ".join(f"{100*sum(1 for x in bs if x > u)/len(bs):>7.0f}%"
                             for u in (0, 10, 25, 50)))

        print("\n  ROBUSTEZ\n")
        orden = sorted(filas, key=lambda x: -x[2])
        for k in (1, 2, 3, 5):
            print(f"  sacando las {k} mejores sesiones     n={len(orden)-k:>3}  "
                  f"muerte {muerte(orden[k:]):>7.1f}c")
        peor = sorted(filas, key=lambda x: x[2])
        print(f"  sacando la PEOR sesión              n={len(peor)-1:>3}  "
              f"muerte {muerte(peor[1:]):>7.1f}c")
        f1 = [x for x in filas if x[0] < CORTE_P]
        f2 = [x for x in filas if x[0] >= CORTE_P]
        m1, m2 = muerte(f1), muerte(f2)
        print(f"\n  P1 (hasta {CORTE_P})  n={len(f1):>3}  muerte {m1:>7.1f}c")
        print(f"  P2 (desde {CORTE_P})  n={len(f2):>3}  muerte {m2:>7.1f}c"
              f"     brecha {abs(m1-m2):.1f}c")

        gm = defaultdict(list)
        for x in filas:
            gm[x[0][:7]].append(x)
        rn = [(m, muerte(gm[m])) for m in sorted(gm)]
        verdes = sum(1 for _, v in rn if v > 0)
        print(f"\n  POR MES: {len(rn)} meses · {verdes} en verde "
              f"({100*verdes/len(rn):.0f}%) · mediana {statistics.median(v for _, v in rn):>+.1f}c")
        linea = ""
        for m, v in rn:
            linea += f"  {m} {v:>+7.1f}c"
            if len(linea) > 84:
                print("  " + linea)
                linea = ""
        if linea:
            print("  " + linea)

        print("\n  FUERA DE MUESTRA REAL — posterior al censo\n")
        fw = sesiones(nuevos, ap, ex, señal_con_piso(vm, piso))
        if fw:
            print(f"  {len(fw)} sesiones · muerte {muerte(fw):.1f}c")
            for x in fw:
                print(f"    {x[0]}  {x[1]:<12} pnl ${x[2]:>+7.2f}  "
                      f"acc pico {x[4]:>5.0f}  {100*x[2]/x[4]:>7.1f}c")
        else:
            print("  ninguna sesión nueva califica")

    print("\n" + "=" * 100)
    print("  EL TOPE DE 2 TRAMOS, APARTE — no está sumado a la candidata")
    print("=" * 100 + "\n")
    print(f"  {'':<38} {'n':>4} {'acc':>5} {'MUERTE':>9}")
    print("  " + "-" * 62)
    for et, ap, ex, vm, piso in CONFIGS[:1] + CONFIGS[1:2]:
        for pn, pol in (("sin tope", {}), ("tope 2 concurrentes",
                                           dict(modo="tope", tope=2))):
            pob = poblacion(vistos, min_expansion=ex, min_ratio_vol=0.0,
                            min_dolar=0.0)
            pob = [d for d in pob if _clasificar(d, hasta=10.0) == ap]
            pf = defaultdict(list)
            for d in pob:
                pf[d.d].append(d)
            sig = señal_con_piso(vm, piso)
            filas = []
            for f in sorted(pf):
                c = pf[f]
                cuota = R_BASE / len(c)
                pnl = acc = 0.0
                tk = []
                for d in c:
                    j = jornada_exp(d, sig, lado="short", stop_pct=45.0,
                                    riesgo=cuota, max_trades=10,
                                    presupuesto="mtm", **pol)
                    if not j:
                        continue
                    pnl += j["pnl"]
                    acc += j["acciones"]
                    tk.append(d.ticker)
                if tk:
                    filas.append((f, "+".join(sorted(set(tk))), pnl, 0.0, acc, 0.0))
            print(f"  {et.split()[1] + ' · ' + pn:<38} {len(filas):>4} "
                  f"{statistics.mean(x[4] for x in filas):>5.0f} "
                  f"{muerte(filas):>7.1f}c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
