#!/usr/bin/env python3
"""¿Cuánto se puede arriesgar por papel sin quemar la cuenta ni romper consistencia?

**LA PREGUNTA DE AGUS**, textual: "cuál es el drawdown máximo del día que
podemos permitirnos para que en la peor racha de días no quememos la cuenta, y
cuando ganemos no rompamos las reglas de consistencia".

Son dos restricciones que tiran para lados opuestos, y por una razón que no es
obvia:

  · ARRIESGAR MAS quema la cuenta antes. El drawdown escala con el tamaño: si
    duplicás el riesgo por papel, duplicás la peor racha. Contra un tope de
    $1.000, eso es una división.

  · ARRIESGAR MENOS rompe la consistencia. La regla del programa —50%— exige
    que ninguna jornada aporte más de la mitad de la ganancia. Y acá está lo
    que no se ve a simple vista: la RELACION entre un día y el total es
    invariante al tamaño —escalar todo por dos no cambia ninguna proporción—
    pero el CAMINO no lo es. Con riesgo grande llegás a los $1.200 del
    objetivo en pocas jornadas, y con pocas jornadas una sola es más de la
    mitad casi por definición. Con riesgo chico tardás más días, y la ganancia
    se reparte.

O sea: el tamaño no se elige por cuánto querés ganar. Se elige por cuántos días
necesitás para llegar, que es lo que decide si el programa te deja cobrar.

**LAS REGLAS**, de la pantalla del producto (ver test_reglas_ttp.py):

    drawdown máximo     $1.000   (4% de $25.000 de poder de compra)
    pérdida diaria      $400     (bloquea el día, no liquida)
    objetivo            $1.200   para pasar la evaluación
    consistencia        50%      ningún día > la mitad de la ganancia
    mínimo 3 días con 0,5% de la cuenta

**ESTAS CONSTANTES SIGUEN SIN CONFIRMAR CON SOPORTE** y todo el
dimensionamiento cuelga de ellas. Es el pendiente de `MAIL-SOPORTE.md`. Lo que
sigue es correcto CONDICIONADO a que sean estas; si soporte contesta otra cosa,
se vuelve a correr y cambian los números, no el método.

    python test_cuanto_arriesgar.py
"""

from __future__ import annotations

import sys
from collections import defaultdict

sys.path.insert(0, ".")

import motor
from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TOPE_DD = 1000.0
LIM_DIA = 400.0
OBJETIVO = 1200.0
CONSISTENCIA = 50.0
CUENTA = 25_000.0
UMBRAL_BUENO = CUENTA * 0.005      # los "3 días con 0,5%"

STOP, PISO, DESDE, MAXT = 45.0, 2.0, 10.0, 40
CORTE_H, CORTE_UMBRAL = 11.0, 5.0


def serie_diaria(pob, riesgo):
    """PnL por fecha, sumando los papeles de esa fecha. En orden cronológico."""
    por_fecha = defaultdict(float)
    señal = lambda d: [i for i in señales_swing(d, desde=DESDE)
                       if (d.bars[i][4] or 0) >= PISO]
    for d in pob:
        j = jornada(d, señal, lado="short", stop_pct=STOP, riesgo=riesgo,
                    max_trades=MAXT, corte_h=CORTE_H,
                    corte_umbral=CORTE_UMBRAL)
        if j:
            por_fecha[d.d] += j["pnl"]
    return [(f, por_fecha[f]) for f in sorted(por_fecha)]


def drawdown(serie):
    acum = pico = dd = 0.0
    for _, v in serie:
        acum += v
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return dd


def evaluaciones(serie):
    """Simula pasar la evaluación una y otra vez, con las reglas del programa.

    Devuelve por cada intento: días usados, si la quemó, y la participación de
    la mejor jornada en la ganancia — que es la regla de consistencia.
    """
    out = []
    bal = pico = 0.0
    dias = []
    for f, v in serie:
        # El límite diario BLOQUEA el día: no te deja perder más, pero tampoco
        # te salva de lo que ya perdiste antes de que salte.
        v = max(v, -LIM_DIA)
        bal += v
        dias.append(v)
        pico = max(pico, bal)
        if bal - pico <= -TOPE_DD:
            out.append({"dias": len(dias), "quemada": True, "conc": None})
            bal = pico = 0.0
            dias = []
        elif bal >= OBJETIVO:
            ganancia = sum(x for x in dias if x > 0)
            conc = 100 * max(dias) / ganancia if ganancia > 0 else 100.0
            buenos = sum(1 for x in dias if x >= UMBRAL_BUENO)
            out.append({"dias": len(dias), "quemada": False,
                        "conc": conc, "buenos": buenos})
            bal = pico = 0.0
            dias = []
    return out


# El barrido corre SOLO como script. Es la segunda vez que me olvido de
# esto en el dia: sin el guard, `from test_cuanto_arriesgar import
# serie_diaria` reejecuta las 365 simulaciones antes de darte la funcion.
if __name__ == "__main__":
    motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    pob.sort(key=lambda d: d.d)

    print(f"\n  CUANTO ARRIESGAR POR PAPEL · {len(pob)} días reclaim del censo")
    print(f"  reglas: drawdown ${TOPE_DD:,.0f} · día ${LIM_DIA:.0f} · objetivo "
          f"${OBJETIVO:,.0f} · consistencia {CONSISTENCIA:.0f}%")
    print(f"  (sin confirmar con soporte — es el pendiente de MAIL-SOPORTE.md)\n")

    print("  {:>8} {:>10} {:>11} {:>9} {:>8} {:>9} {:>13} {:>9}".format(
        "riesgo", "peor dia", "drawdown", "margen", "pasadas", "quemadas",
        "días p/pasar", "peor día%"))
    print("  " + "-" * 88)

    filas = []
    for riesgo in (100, 150, 200, 250, 300, 400, 500):
        serie = serie_diaria(pob, float(riesgo))
        dd = drawdown(serie)
        peor = min(v for _, v in serie)
        ev = evaluaciones(serie)
        pasadas = [e for e in ev if not e["quemada"]]
        quemadas = [e for e in ev if e["quemada"]]
        margen = 100 * (1 - abs(dd) / TOPE_DD)
        d_prom = (sum(e["dias"] for e in pasadas) / len(pasadas)) if pasadas else None
        conc = max((e["conc"] for e in pasadas), default=None)
        ok_dd = abs(dd) < TOPE_DD
        ok_cons = conc is not None and conc <= CONSISTENCIA
        marca = ""
        if ok_dd and ok_cons:
            marca = "  <== pasa las dos"
        elif ok_dd:
            marca = "  (no pasa consistencia)"
        elif ok_cons:
            marca = "  (quema la cuenta)"
        filas.append((riesgo, dd, conc, ok_dd, ok_cons))
        print("  {:>7.0f} {:>10,.0f} {:>11,.0f} {:>8.0f}% {:>8} {:>9} {:>13} "
              "{:>8}{}".format(
                  riesgo, peor, dd, margen, len(pasadas), len(quemadas),
                  f"{d_prom:.0f}" if d_prom else "—",
                  f"{conc:.0f}%" if conc is not None else "—", marca))

    print("\n  'margen' es cuánto sobra del tope de $1.000 en la peor racha medida.")
    print("  'peor día%' es la mayor participación de UNA jornada en la ganancia de")
    print("  una evaluación: la regla del programa exige que no pase del 50%.")
    print("\n  LO QUE NO SE VE EN LA TABLA: la relación entre un día y el total es")
    print("  INVARIANTE al tamaño — escalar todo por dos no cambia ninguna")
    print("  proporción. Lo que cambia con el tamaño es el CAMINO: con riesgo")
    print("  grande llegás a los $1.200 en pocas jornadas, y con pocas jornadas una")
    print("  sola es más de la mitad casi por definición.")
