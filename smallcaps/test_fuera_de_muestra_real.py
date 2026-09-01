#!/usr/bin/env python3
"""La prueba honesta: días que no existían cuando se tomaron las decisiones.

**Por qué esta prueba vale más que todo lo anterior.** Los cortes P1/P2 parten
una muestra que ya estaba entera sobre la mesa: por más disciplina que uno tenga,
las decisiones se tomaron habiendo visto los dos períodos. Acá no. El censo
termina el 2026-08-12 y estos días son posteriores — no existían cuando se
eligió el umbral de expansión, el ancho del stop, la ventana de agregado ni el
filtro de apertura.

Es lo más parecido a operar en vivo que se puede hacer sin poner plata.

LA CONFIGURACIÓN SE CONGELA ACÁ Y NO SE TOCA. Está escrita como constante, no
como parámetro, a propósito: si el resultado sale mal y me dan ganas de mover
algo, mover algo es exactamente lo que invalida la prueba. Lo que salga, sale.

    SMALLCAPS_CENSO=1 python test_fuera_de_muestra_real.py
"""

from __future__ import annotations

import sqlite3
import statistics
import sys

import config
import motor
from chavineta import clasificar_apertura as _clasificar
from dias import hora
from motor import evaluar, jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- CONGELADO
CORTE_CENSO = "2026-08-12"     # última fecha que el sistema llegó a ver
EXPANSION = 100.0              # umbral de expansión premarket
APERTURA = "reclaim"           # el hallazgo: los días que descartábamos
STOP = 45.0                    # ancho del stop, en %
DESDE = 10.0                   # no entrar antes de las 10:00 (la etiqueta se
                               # conoce recién ahí — sin eso hay look-ahead)
VENTANA_MIN = 60               # sólo agregar durante 60 min desde el 1er tramo
LOCATE = 0.20                  # el pesimista de Espes, para el neto

# Lo que el sistema PREDICE para estos días, medido sobre 2024-10 → 2026-08.
# Se escribe antes de mirar el resultado: sin una predicción explícita, cualquier
# número que salga después se puede racionalizar.
ESPERADO = {"ret_nom": 17.0, "bruto_R": 0.640, "nom_R": 3.77,
            "ses_mes": 3.2, "positivas": 65}


def ventana(mins):
    """Sólo los tramos dentro de `mins` minutos del primero del día."""
    def f(d):
        idx = señales_swing(d, desde=DESDE)
        if not idx:
            return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= mins / 60.0]
    return f


def main() -> int:
    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo(refrescar=True)          # relee el censo, ya extendido
    nuevos = [d for d in dias if d.d > CORTE_CENSO]
    viejos = [d for d in dias if d.d <= CORTE_CENSO]

    print("=" * 96)
    print("  FUERA DE MUESTRA REAL — días posteriores al censo")
    print(f"  el sistema vio hasta {CORTE_CENSO}. Todo lo de abajo es posterior.")
    print("=" * 96)
    print(f"\n  universo: {len(viejos):,} días vistos · {len(nuevos):,} NUEVOS")
    if not nuevos:
        print("\n  Todavía no hay días nuevos descargados. Corré primero:")
        print("    python backfill_daily.py --days 25")
        print("    python detect_events.py")
        print("    python poblacion_observable.py")
        return 1
    print(f"  fechas nuevas: {min(d.d for d in nuevos)} → {max(d.d for d in nuevos)}")

    pob = poblacion(nuevos, min_ratio_vol=0.0, min_expansion=EXPANSION,
                    min_dolar=0.0, max_float=47e6)
    pob = [d for d in pob if _clasificar(d, hasta=10.0) == APERTURA]
    print(f"  de esos, califican para la estrategia: {len(pob)}")
    for d in sorted(pob, key=lambda x: x.d):
        print(f"    {d.d}  {d.ticker:<6} expansión {d.expansion_pct:>6.0f}%  "
              f"cierre previo ${d.prev_close:.2f}")

    if not pob:
        print("\n  Ningún día nuevo califica. No es un resultado malo ni bueno:")
        print("  la estrategia opera 3,2 veces por mes y la ventana es corta.")
        return 0

    sig = ventana(VENTANA_MIN)
    filas = []
    for d in sorted(pob, key=lambda x: x.d):
        j = jornada(d, sig, lado="short", stop_pct=STOP, riesgo=motor.R_BASE,
                    max_trades=10)
        if not j:
            print(f"    {d.d} {d.ticker}: sin señal de entrada")
            continue
        filas.append((d, j))

    if not filas:
        print("\n  Calificaron días pero ninguno dio señal de entrada.")
        return 0

    print(f"\n  LAS JORNADAS, UNA POR UNA\n")
    print(f"  {'fecha':>11} {'papel':>7} {'trades':>7} {'pnl $':>9} {'pnl R':>8} "
          f"{'nom R':>7} {'ret/nom':>9} {'neto@20%':>10}")
    print("  " + "-" * 76)
    for d, j in filas:
        pR, nR = j["pnl"] / motor.R_BASE, j["nominal"] / motor.R_BASE
        print(f"  {d.d:>11} {d.ticker:>7} {j['trades']:>7} {j['pnl']:>+9.2f} "
              f"{pR:>+8.3f} {nR:>7.2f} {100*pR/nR if nR else 0:>8.1f}% "
              f"{pR - LOCATE*nR:>+10.3f}")

    pnl = [j["pnl"] / motor.R_BASE for _, j in filas]
    nom = [j["nominal"] / motor.R_BASE for _, j in filas]
    m, nn = statistics.mean(pnl), statistics.mean(nom)
    pos = 100 * sum(1 for x in pnl if x > 0) / len(pnl)

    print(f"\n  RESULTADO vs LO PREDICHO\n")
    print(f"  {'métrica':>16} {'predicho':>10} {'real':>10} {'':>4}")
    print("  " + "-" * 44)
    for k, lab, real in (("bruto_R", "bruto R", m), ("nom_R", "nominal R", nn),
                         ("ret_nom", "ret/nom %", 100 * m / nn if nn else 0),
                         ("positivas", "positivas %", pos)):
        e = ESPERADO[k]
        marca = "ok" if (abs(real - e) <= abs(e) * 0.5) else "<<"
        print(f"  {lab:>16} {e:>10.2f} {real:>10.2f}  {marca}")
    print(f"\n  neto por sesión con locate al {LOCATE:.0%}: {m - LOCATE*nn:+.3f} R")
    print(f"  punto de muerte medido en estos días: {100*m/nn if nn else 0:.1f}%")

    print(f"""
  CÓMO LEER ESTO, y qué NO se puede concluir. Con {len(filas)} jornadas no se
  valida ni se refuta nada: la desviación por sesión es de ~0,9 R, así que el
  error de la media con esta muestra es enorme. Sirve para una cosa sola y es
  suficiente — ver si el sistema, corrido sobre días que nunca vio, produce
  algo que se parece a lo que dijo que iba a producir, o algo de otro planeta.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
