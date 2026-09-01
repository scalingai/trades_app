#!/usr/bin/env python3
"""¿El reclaim aguanta, o es un artefacto de tener pocas sesiones?

**Por qué esta prueba y no otra.** `apertura="reclaim"` con `min_expansion=100`
es el único número del proyecto que se acercaba a hacerlo viable, y es también
el de muestra más chica: ~72 sesiones contra 144 del fade. Un número alto sobre
pocas sesiones es la forma que tiene el ruido de parecerse a un hallazgo. Acá se
lo somete a todos los cortes que se me ocurrieron, y cada uno tiene declarado de
antemano qué resultado lo mataría.

TODO CORRE CON EL PRESUPUESTO HONESTO (`mtm`). Con el presupuesto viejo el
reclaim daba 16,5%; el 4,8 de diferencia era el look-ahead del corte por riesgo
(ver `test_presupuesto.py`). Validar el número inflado no tendría sentido: lo
que hay que saber es si aguanta el 11,7% que queda.

LOS SEIS CORTES, y qué mata a cada uno
--------------------------------------
  1. **Bootstrap sobre sesiones.** Se remuestrean las sesiones con reposición
     10.000 veces y se mira el intervalo del ret/nom. MATA: que el percentil 5
     esté abajo de cero. Ojo con leerlo al revés — que el intervalo no toque el
     cero NO prueba que el edge exista fuera de esta muestra, sólo que dentro de
     ella no viene de dos o tres sesiones.
  2. **Dejar afuera el mejor día**, y los mejores 2, 3, 5. MATA: que sacar un
     puñado de días se lleve más de la mitad del ret/nom.
  3. **Por ticker.** MATA: que un solo papel aporte la mayoría, o que la mediana
     de los tickers esté muy abajo de la media (la media la puede hacer uno).
  4. **Por mes.** MATA: que los meses positivos sean minoría, o que todo el
     resultado viva en un trimestre.
  5. **Bootstrap por BLOQUES de ticker.** Los días del mismo papel no son
     independientes —la misma historia de dilución dura semanas—, así que el
     bootstrap por sesión sobreestima la precisión. Este remuestrea papeles
     enteros. MATA: lo mismo que 1, con el intervalo más ancho que corresponde.
  6. **La ventana fuera de muestra real**, posterior al 2026-08-12. No valida
     nada por tamaño; sirve para ver si está en el mismo planeta.

CONTROL DE CORDURA. El mismo tratamiento se le aplica al `fade·exp150`, que
tiene el doble de sesiones y un número mucho más bajo. Si los cortes del reclaim
se ven mejor que los del fade en TODAS las dimensiones, es señal de que los
cortes miden lo que dicen. Si el fade —que nadie cree que sea un hallazgo— pasa
los mismos filtros, entonces los filtros no separan nada y esta prueba no vale.

    python test_reclaim_aguanta.py
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

import motor
from chavineta import clasificar_apertura as _clasificar
from dias import hora
from exposicion import jornada_exp, ventana
from motor import R_BASE, poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_CENSO = "2026-08-12"     # última fecha que el sistema llegó a ver
CORTE_P = "2025-08-17"
LIMPIO = {"min_ratio_vol": 0.0, "min_dolar": 0.0}
SEMILLA = 20260901             # fija, para que la corrida sea reproducible
B = 10_000

CASOS = [
    ("reclaim·exp100", "reclaim", 100.0, 60),
    ("fade·exp150 (control)", "fade", 150.0, 999),
]


def sesiones(dias, ap, ex, vm, *, presupuesto="mtm"):
    """Una fila por sesión operada: (fecha, ticker, pnl_R, nominal_R).

    Se arma a mano en vez de por `motor.evaluar` porque los remuestreos
    necesitan la fila cruda, no la métrica agregada. Se replica la cuota de
    `evaluar`: cuando dos papeles califican el mismo día, el riesgo del día se
    reparte entre ellos, así que un día con dos candidatos no despliega el doble
    de nominal — el presupuesto es del día, no del papel.
    """
    pob = poblacion(dias, min_expansion=ex, **LIMPIO)
    pob = [d for d in pob if _clasificar(d, hasta=10.0) == ap]
    por_fecha = defaultdict(list)
    for d in pob:
        por_fecha[d.d].append(d)

    sig = ventana(vm)
    filas = []
    for f in sorted(por_fecha):
        cands = por_fecha[f]
        cuota = R_BASE / len(cands)
        pnl = nom = 0.0
        tickers = []
        for d in cands:
            j = jornada_exp(d, sig, lado="short", stop_pct=45.0, riesgo=cuota,
                            max_trades=10, presupuesto=presupuesto)
            if not j:
                continue
            pnl += j["pnl"]
            nom += j["nominal"]
            tickers.append(d.ticker)
        if tickers:
            filas.append((f, "+".join(sorted(set(tickers))),
                          pnl / R_BASE, nom / R_BASE))
    return filas


def ret_nom(filas):
    """El estimador del proyecto: cociente de las MEDIAS, no media de cocientes.

    Es la definición correcta para esto: lo que se paga de locate es el nominal
    total del período y lo que se cobra es el PnL total, así que el número que
    decide es la razón de los agregados. Una media de razones le daría el mismo
    peso a una sesión de un tramo que a una de diez.
    """
    if not filas:
        return None
    n = statistics.mean(x[3] for x in filas)
    return 100 * statistics.mean(x[2] for x in filas) / n if n else None


def pct(v, p):
    v = sorted(v)
    return v[max(0, min(len(v) - 1, int(p * len(v))))]


# --------------------------------------------------------------------- 1 y 5

def bootstrap(filas, *, bloques=False, rng=None):
    rng = rng or random.Random(SEMILLA)
    if bloques:
        grupos = defaultdict(list)
        for x in filas:
            grupos[x[1]].append(x)
        claves = list(grupos)
        muestras = []
        for _ in range(B):
            m = []
            for _ in range(len(claves)):
                m.extend(grupos[rng.choice(claves)])
            r = ret_nom(m)
            if r is not None:
                muestras.append(r)
        return muestras
    return [r for r in (ret_nom([rng.choice(filas) for _ in filas])
                        for _ in range(B)) if r is not None]


def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    vistos = [d for d in dias if d.d <= CORTE_CENSO]
    nuevos = [d for d in dias if d.d > CORTE_CENSO]

    for lab, ap, ex, vm in CASOS:
        filas = sesiones(vistos, ap, ex, vm)
        base = ret_nom(filas)
        print("=" * 96)
        print(f"  {lab.upper()}   ·   {len(filas)} sesiones   ·   ret/nom {base:.1f}%")
        print("=" * 96)

        # --- 1 y 5: bootstrap ------------------------------------------
        print("\n  1+5) BOOTSTRAP — 10.000 remuestreos\n")
        print(f"  {'unidad':>22} {'p5':>8} {'p50':>8} {'p95':>8} {'P(>0)':>8} {'P(>20%)':>9}")
        print("  " + "-" * 70)
        for et, blo in (("sesión", False), ("ticker entero", True)):
            m = bootstrap(filas, bloques=blo, rng=random.Random(SEMILLA))
            print(f"  {et:>22} {pct(m, .05):>7.1f}% {pct(m, .50):>7.1f}% "
                  f"{pct(m, .95):>7.1f}% {100*sum(1 for x in m if x > 0)/len(m):>7.0f}% "
                  f"{100*sum(1 for x in m if x > 20)/len(m):>8.0f}%")

        # --- 2: dejar afuera los mejores días ---------------------------
        print("\n  2) DEJANDO AFUERA LOS MEJORES DÍAS\n")
        orden = sorted(filas, key=lambda x: -x[2])
        print(f"  {'se sacan':>16} {'n':>5} {'ret/nom':>9}  {'días sacados'}")
        print("  " + "-" * 74)
        for k in (0, 1, 2, 3, 5):
            resto = orden[k:]
            sacados = ", ".join(f"{x[0]} {x[1]}" for x in orden[:k]) or "—"
            print(f"  {('ninguno' if not k else f'los {k} mejores'):>16} "
                  f"{len(resto):>5} {ret_nom(resto):>8.1f}%  {sacados[:52]}")
        peor = sorted(filas, key=lambda x: x[2])
        print(f"  {'el PEOR día':>16} {len(peor)-1:>5} {ret_nom(peor[1:]):>8.1f}%  "
              f"{peor[0][0]} {peor[0][1]}")

        # --- 3: por ticker ----------------------------------------------
        print("\n  3) POR TICKER\n")
        g = defaultdict(list)
        for x in filas:
            g[x[1]].append(x)
        orden_t = sorted(g.items(), key=lambda kv: -sum(y[2] for y in kv[1]))
        print(f"  {'ticker':>10} {'ses':>5} {'pnl R tot':>11} {'ret/nom':>9}")
        print("  " + "-" * 40)
        for t, xs in orden_t[:6]:
            print(f"  {t:>10} {len(xs):>5} {sum(y[2] for y in xs):>+11.3f} "
                  f"{ret_nom(xs):>8.1f}%")
        if len(orden_t) > 8:
            print(f"  {'…':>10}")
        for t, xs in orden_t[-2:]:
            print(f"  {t:>10} {len(xs):>5} {sum(y[2] for y in xs):>+11.3f} "
                  f"{ret_nom(xs):>8.1f}%")
        rn_t = [ret_nom(xs) for _, xs in orden_t if ret_nom(xs) is not None]
        pos = sum(1 for _, xs in orden_t if sum(y[2] for y in xs) > 0)
        print(f"\n  {len(orden_t)} papeles distintos · {pos} en verde "
              f"({100*pos/len(orden_t):.0f}%) · mediana del ret/nom por papel "
              f"{statistics.median(rn_t):.1f}%")
        sin_mejor = [x for x in filas if x[1] != orden_t[0][0]]
        print(f"  sacando el papel que más aporta ({orden_t[0][0]}, "
              f"{len(orden_t[0][1])} ses): ret/nom {ret_nom(sin_mejor):.1f}%")

        # --- 4: por mes --------------------------------------------------
        print("\n  4) POR MES\n")
        gm = defaultdict(list)
        for x in filas:
            gm[x[0][:7]].append(x)
        meses = sorted(gm)
        linea = ""
        for m in meses:
            r = ret_nom(gm[m])
            linea += f"  {m} {r:>+6.1f}%({len(gm[m])})"
            if len(linea) > 88:
                print("  " + linea)
                linea = ""
        if linea:
            print("  " + linea)
        rn_m = [ret_nom(gm[m]) for m in meses]
        verdes = sum(1 for r in rn_m if r > 0)
        print(f"\n  {len(meses)} meses · {verdes} en verde ({100*verdes/len(meses):.0f}%) "
              f"· mediana {statistics.median(rn_m):>+.1f}% "
              f"· meses arriba de 20%: {sum(1 for r in rn_m if r > 20)}")
        peor_m = min(meses, key=lambda m: sum(y[2] for y in gm[m]))
        print(f"  sacando el mejor mes: "
              f"{ret_nom([x for x in filas if x[0][:7] != max(meses, key=lambda m: sum(y[2] for y in gm[m]))]):.1f}%"
              f"  · sacando el peor ({peor_m}): "
              f"{ret_nom([x for x in filas if x[0][:7] != peor_m]):.1f}%")

        # --- 6: fuera de muestra real ------------------------------------
        print("\n  6) FUERA DE MUESTRA REAL — posterior al censo\n")
        fw = sesiones(nuevos, ap, ex, vm)
        if fw:
            print(f"  {len(fw)} sesiones ({min(x[0] for x in fw)} → "
                  f"{max(x[0] for x in fw)}) · ret/nom {ret_nom(fw):.1f}%")
            for x in fw:
                print(f"    {x[0]}  {x[1]:<12} pnl {x[2]:>+7.3f} R  "
                      f"nom {x[3]:>6.2f} R  {100*x[2]/x[3] if x[3] else 0:>7.1f}%")
            m = bootstrap(filas, rng=random.Random(SEMILLA))
            dentro = sum(1 for x in m if x <= ret_nom(fw)) / len(m)
            print(f"\n  el resultado fuera de muestra cae en el percentil "
                  f"{100*dentro:.0f} de lo que predecía la muestra vieja")
        else:
            print("  sin sesiones nuevas que califiquen")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
