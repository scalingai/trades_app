#!/usr/bin/env python3
"""¿La pantalla en vivo dice lo mismo que el backtest? Test de identidad.

**Por qué existe.** Todo el proyecto vale por una sola razón: lo que se opera
tiene que ser exactamente lo que se midió. Si el camino en vivo decidiera aunque
sea un poco distinto, los ocho meses de mediciones dejan de significar nada y no
habría forma de enterarse hasta perder plata.

Este archivo pasa datos reales del censo por el MISMO archivo JSONL que escribe
el indicador de la plataforma, los levanta con `vivo.leer_feed`, y compara el
resultado contra `motor.jornada` corrido directo sobre el día. Si difieren en un
solo centavo, el puente no se usa.

La primera versión de `vivo.evaluar` copiaba a mano la regla de presupuesto del
motor y ya divergía: mostraba 14 tramos donde el motor abría menos, y marcaba a
mercado tramos que ya habían saltado por stop. Por eso ahora `evaluar` llama a
`jornada` en vez de reimplementarla, y por eso este test corre siempre.

    python puente/identidad.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dias import cargar
from motor import jornada
from sesion import señales_swing

import vivo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Días elegidos a propósito para que no todos sean lindos: WETO es el caso
# base, DAIC es un día PERDEDOR (si el test sólo mirara días ganadores no
# probaría el camino del stop), PRFX es el de 20 tramos donde apareció el bug
# del nominal concurrente.
CASOS = [("WETO", "2026-08-14"), ("DAIC", "2026-08-25"),
         ("BYAH", "2026-08-06"), ("EZRA", "2026-08-03"),
         ("PRFX", "2024-12-19")]

RIESGO, PISO = 400.0, 2.0


def como_lo_escribe_la_plataforma(d, tk, ruta):
    """El día del censo, escrito como lo escribiría el indicador en C#.

    Las horas van a UTC con la 'Z' del formato ISO, que es lo que manda el
    indicador; si la conversión de vuelta a Nueva York estuviera mal, las
    señales caerían en otra hora y el test lo vería.

    El UTC se deriva de la propia barra con `astimezone`, NO sumando un offset
    fijo. Con +4 fijo este test pasaba en verano y fallaba en diciembre, que es
    exactamente por qué PRFX (2024-12-19) está en la lista: es el único día de
    invierno, y fue el que delató que `vivo.py` tenía el huso hardcodeado.
    """
    with open(ruta, "w", encoding="utf-8") as fh:
        for b in d.bars:
            utc = b[0].astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(json.dumps({"t": utc, "s": tk, "o": b[1], "h": b[2],
                                 "l": b[3], "c": b[4], "v": b[5] or 0,
                                 "pc": d.prev_close}) + "\n")


def main() -> int:
    ruta = Path(tempfile.gettempdir()) / "identidad_feed.jsonl"
    print("\n  EL CAMINO VIVO CONTRA EL BACKTEST\n")
    print("  {:<7} {:<11} {:>11} {:>24} {:>10}".format(
        "papel", "fecha", "tramos", "pnl del dia", "pico acc"))
    print("  " + "-" * 68)

    todo_ok, corridos = True, 0
    for tk, fecha in CASOS:
        d = next(iter(cargar(solo={(tk, fecha)})), None)
        if not d:
            print("  {:<7} {:<11}  sin datos en el censo".format(tk, fecha))
            continue

        def sig(x):
            return [i for i in señales_swing(x, desde=vivo.DESDE)
                    if (x.bars[i][4] or 0) >= PISO]

        j = jornada(d, sig, lado="short", stop_pct=vivo.STOP_PCT,
                    riesgo=RIESGO, max_trades=vivo.MAX_TRAMOS,
                    corte_h=vivo.CORTE_H, corte_umbral=vivo.CORTE_UMBRAL)

        como_lo_escribe_la_plataforma(d, tk, ruta)
        feed = vivo.leer_feed(ruta)
        dv = vivo.armar_dia(tk, fecha, feed[(tk, fecha)])
        r = vivo.evaluar(dv, RIESGO, PISO)

        tb, tv = (j["trades"] if j else 0), len(r.get("tramos") or [])
        pb, pv = (j["pnl"] if j else 0.0), r.get("equity", 0.0)
        ok = (tb == tv) and abs(pb - pv) < 1e-9
        todo_ok = todo_ok and ok
        corridos += 1
        print("  {:<7} {:<11} {:>4} vs {:<4} {:>+10.4f} vs {:>+10.4f} "
              "{:>8.0f}  {}".format(tk, fecha, tb, tv, pb, pv,
                                    r.get("pico", 0), "ok" if ok else "DIFIERE"))

    print()
    if not corridos:
        print("  NO SE CORRIO NINGUN CASO — el censo no tiene estos dias")
        return 1
    if todo_ok:
        print("  IDENTICOS — lo que muestra la pantalla es lo que se midio")
        return 0
    print("  HAY DIVERGENCIA: no operar hasta resolverla")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
