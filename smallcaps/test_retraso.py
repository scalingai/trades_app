#!/usr/bin/env python3
"""¿Qué cuesta entrar tarde? El costo de mirar una pantalla en vez de un bot.

El backtest entra al CIERRE de la vela que dispara la señal. En vivo eso es
imposible: la vela cierra, el indicador la escribe, la pantalla la levanta hasta
20 segundos después, y recién ahí Agus pone la orden. Entre la señal y el fill
real pasan entre 30 y 90 segundos.

Esto mide exactamente eso: correr la MISMA estrategia pero entrando al cierre de
la vela siguiente (+1 minuto), la subsiguiente (+2) y +3. Si el edge se
evapora con un minuto de retraso, la operativa semiautomática no sirve y hay que
saberlo antes de poner plata, no después.
"""
import sys
sys.path.insert(0, ".")

from motor import universo, poblacion, jornada, _nominal_pico
from chavineta import clasificar_apertura as _cl
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RIESGO, PISO, STOP, MAXT = 400.0, 2.0, 45.0, 40
MIN_ORDEN, POR_ACCION = 0.75, 0.005


def comision(acc):
    return 2 * max(MIN_ORDEN, acc * POR_ACCION)


def sig_con_retraso(k, piso):
    """Las mismas señales, pero entrando k velas después.

    Se filtra por precio en la vela donde REALMENTE se entra, no en la de la
    señal: si el piso se chequeara en la vela original se estaria usando un
    precio que a la hora de entrar ya no existe.
    """
    def f(d):
        out, visto = [], set()
        for i in señales_swing(d, desde=10.0):
            j = i + k
            if j >= len(d.bars) or j in visto:
                continue
            if (d.bars[j][4] or 0) < piso:
                continue
            visto.add(j)
            out.append(j)
        return out
    return f


def correr(k):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0, min_dolar=0.0,
                    max_float=47e6)
    pob = [d for d in pob if _cl(d, hasta=10.0) == "reclaim"]
    bruto = com = nom = 0.0
    ses = tr = 0
    for d in pob:
        j = jornada(d, sig_con_retraso(k, PISO), lado="short", stop_pct=STOP,
                    riesgo=RIESGO, max_trades=MAXT)
        if not j:
            continue
        b = j["pnl"]
        for t in j["detalle"]:
            b += t["acciones"] * 0.04          # devolver el costo del motor
            com += comision(t["acciones"])
        bruto += b
        nom += j["nominal"]
        tr += j["trades"]
        ses += 1
    neto = bruto - com
    return {"ses": ses, "tr": tr, "bruto": bruto, "com": com, "neto": neto,
            "nom": nom, "ret": 100 * neto / nom if nom else 0.0}


print("\n  QUE CUESTA ENTRAR TARDE\n")
print("  {:>9} {:>6} {:>7} {:>11} {:>10} {:>11} {:>9}".format(
    "retraso", "ses", "trades", "bruto", "comision", "neto", "ret/nom"))
print("  " + "-" * 70)
base = None
for k in (0, 1, 2, 3):
    r = correr(k)
    if base is None:
        base = r["neto"]
    delta = "" if k == 0 else "  ({:+.0f}%)".format(
        100 * (r["neto"] - base) / abs(base)) if base else ""
    etiqueta = "al cierre" if k == 0 else "+{} min".format(k)
    print("  {:>9} {:>6} {:>7} ${:>10.0f} ${:>9.0f} ${:>10.0f} {:>8.2f}%{}".format(
        etiqueta, r["ses"], r["tr"], r["bruto"], r["com"], r["neto"],
        r["ret"], delta))
print()
