#!/usr/bin/env python3
"""¿Las 11:00 son especiales, o cualquier hora de esa zona sirve igual?

**DE DONDE SALE LA PREGUNTA.** Agus, mirando CHPT el 2026-09-03: tres tramos
abiertos a las 10:00, 10:29 y 10:39, y el corte los cerró a las 11:00 — o sea,
veintiún minutos después de agregar la última posición. "Me parece raro. ¿Y si
probamos 11:05, 11:10, 11:15? Porque a las 11 sé que puede haber volatilidad."

La intuición tiene fundamento: las horas redondas concentran órdenes y el
minuto 11:00 puede ser un pico de ruido. Si el resultado del corte depende de
caer justo ahí, no es una regla — es un accidente.

**PERO PROBAR TRES HORARIOS Y QUEDARSE CON EL MEJOR ES SOBREAJUSTE**, y por eso
este script NO hace eso. Barre la zona entera minuto a minuto y mira la FORMA:

  · Si hay una MESETA —todo el rango rinde parecido— la elección de las 11:00
    es robusta y da igual moverla. La respuesta a Agus es "no cambia nada".
  · Si hay un PICO en un horario suelto, ese horario es ruido y NO hay que
    mudarse a él: es exactamente el número que no va a repetirse.
  · Si hay una PENDIENTE clara, ahí sí hay señal y vale moverse.

La prueba de que una meseta es meseta y no casualidad: se parte la muestra en
dos mitades por tiempo y se mira si las dos dibujan la misma forma. Un pico que
aparece en una mitad y no en la otra es ruido, sin importar cuánto "gane".

    python test_corte_minuto.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from motor import poblacion, universo
from test_corte_por_hora import jornada

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def correr(dias, **kw):
    """Igual que el de `test_corte_por_hora`, pero devuelve el DRAWDOWN.

    Es la métrica que decide: la cuenta de fondeo se liquida por caída de
    equity, no por PnL final. Una variante que gana más con peor drawdown es
    peor variante, aunque la tabla de plata diga lo contrario.
    """
    neto = nom = 0.0
    ses = tr = 0
    por_dia = {}
    for d in dias:
        r = jornada(d, **kw)
        if not r:
            continue
        neto += r["neto"]
        nom += r["nominal"]
        tr += r["trades"]
        ses += 1
        por_dia[d.d] = por_dia.get(d.d, 0.0) + r["neto"]

    # Drawdown sobre la curva de equity en orden CRONOLOGICO.
    acum = pico = 0.0
    dd = 0.0
    for f in sorted(por_dia):
        acum += por_dia[f]
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
    return {"ses": ses, "tr": tr, "neto": neto, "dd": dd,
            "ret": 100 * neto / nom if nom else 0.0,
            "por_ses": neto / ses if ses else 0.0,
            "dias": len(por_dia)}


def tabla(pob, horas, titulo):
    print(f"\n  {titulo}")
    print("  {:<9} {:>5} {:>7} {:>10} {:>8} {:>9} {:>11}".format(
        "corte", "ses", "trades", "neto", "ret/nom", "$/ses", "drawdown"))
    print("  " + "-" * 68)
    base = correr(pob)
    print("  {:<9} {:>5} {:>7} ${:>9,.0f} {:>7.2f}% ${:>8.0f} ${:>10,.0f}".format(
        "sin corte", base["ses"], base["tr"], base["neto"], base["ret"],
        base["por_ses"], base["dd"]))
    print()
    filas = []
    for h in horas:
        r = correr(pob, corte_h=h, modo="si_flojo", umbral=5.0)
        filas.append((h, r))
        hh = f"{int(h):02d}:{round((h % 1) * 60):02d}"
        print("  {:<9} {:>5} {:>7} ${:>9,.0f} {:>7.2f}% ${:>8.0f} ${:>10,.0f}".format(
            hh, r["ses"], r["tr"], r["neto"], r["ret"], r["por_ses"], r["dd"]))
    return base, filas


def forma(filas, clave):
    """El rango de la métrica en la meseta, para decir si el pico es real."""
    vs = [r[clave] for _, r in filas]
    lo, hi = min(vs), max(vs)
    mejor = max(filas, key=lambda x: x[1][clave])[0]
    return lo, hi, mejor


dias = universo()
pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                            min_dolar=0.0, max_float=47e6)
       if _cl(d, hasta=10.0) == "reclaim"]
pob.sort(key=lambda d: d.d)
print(f"\n  CORTE MINUTO A MINUTO · {len(pob)} días reclaim del censo")
print("  Corte = cerrar si la posición no gana 5% a esa hora. Igual que hoy,")
print("  lo único que se mueve es el reloj.")

HORAS = [10.5 + i / 12.0 for i in range(19)]      # 10:30 a 12:00 cada 5 min

base, filas = tabla(pob, HORAS, "TODA LA MUESTRA")

lo, hi, mejor = forma(filas, "por_ses")
lo_d, hi_d, _ = forma(filas, "dd")
print(f"\n  $/sesión en el rango: ${lo:.0f} a ${hi:.0f}"
      f"  ·  drawdown: ${hi_d:,.0f} a ${lo_d:,.0f}")
print(f"  El mejor horario de la muestra es {int(mejor):02d}:"
      f"{round((mejor % 1) * 60):02d} — pero eso NO es una recomendación:")
print("  el mejor de 19 pruebas es el mejor de 19 pruebas. Lo que decide es si")
print("  las dos mitades de abajo lo confirman.")

# ---- LA PRUEBA DE VERDAD: ¿las dos mitades dibujan la misma forma? ---------
mitad = len(pob) // 2
tabla(pob[:mitad], HORAS, f"PRIMERA MITAD ({pob[0].d} a {pob[mitad - 1].d})")
tabla(pob[mitad:], HORAS, f"SEGUNDA MITAD ({pob[mitad].d} a {pob[-1].d})")

print("\n  COMO LEER ESTO")
print("  Si las dos mitades tienen su máximo en horarios DISTINTOS, la zona es")
print("  una meseta y el horario exacto no importa: quedarse en 11:00 está")
print("  bien y moverse a 11:05 también. Si las dos coinciden en el mismo")
print("  horario y le sacan ventaja clara al resto, ahí sí hay algo que mover.")
