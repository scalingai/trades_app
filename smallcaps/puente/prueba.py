#!/usr/bin/env python3
"""Prueba del puente: reproduce una jornada real por el MISMO camino del vivo.

No alcanza con que `vivo.py` corra sin excepciones. Lo que hay que probar es que
el camino nuevo —feed JSONL -> parseo -> Dia armado a mano— produzca EXACTAMENTE
las mismas senales que el camino del backtest, que arma el Dia desde sqlite.

Si difieren, lo que se opere en vivo no es lo que se midio.
"""
import json, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.pop("SMALLCAPS_CENSO", None)

from dias import cargar, hora
from sesion import señales_swing
from chavineta import clasificar_apertura
import puente.vivo as V

TICKER, FECHA = "WETO", "2026-08-14"
dia_real = next(iter(cargar(solo={(TICKER, FECHA)})), None)
if dia_real is None:
    print("  no hay datos de ese dia"); raise SystemExit(1)

# 1) Escribir el feed como lo escribiria el indicador C#
tmp = Path(os.environ.get("TEMP", "/tmp")) / "feed_prueba.jsonl"
with open(tmp, "w", encoding="utf-8") as fh:
    for b in dia_real.bars:
        fh.write(json.dumps({
            "t": b[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "s": TICKER,
            "o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": b[5] or 0,
            "pc": dia_real.prev_close}) + "\n")
print(f"  feed simulado: {len(dia_real.bars)} barras -> {tmp.name}")

# 2) Leerlo por el camino del vivo. OJO: el C# escribe UTC y vivo.py convierte
#    a NY. Aca las barras ya vienen en hora NY, asi que se neutraliza el huso
#    para que la comparacion sea del PARSEO, no del reloj.
import datetime as dt
V.NY = dt.timezone.utc
por_papel = V.leer_feed(tmp)
clave = (TICKER, FECHA)
if clave not in por_papel:
    print(f"  el feed no produjo {clave}. claves: {list(por_papel)[:3]}")
    raise SystemExit(1)
dia_vivo = V.armar_dia(TICKER, FECHA, por_papel[clave])

# 3) Comparar los dos caminos
print(f"\n  {'':22} {'backtest':>14} {'vivo':>14} {'':>4}")
print("  " + "-"*58)
def cmp(lab, a, b, tol=1e-9):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        ok = abs(a - b) < tol
    else:
        ok = a == b
    fa = f"{a:>14.4f}" if isinstance(a,(int,float)) else f"{str(a):>14}"
    fb = f"{b:>14.4f}" if isinstance(b,(int,float)) else f"{str(b):>14}"
    print(f"  {lab:<22} {fa} {fb} {'ok' if ok else '<<< DIFIERE':>4}")
    return ok

todo = True
todo &= cmp("barras", len(dia_real.bars), len(dia_vivo.bars))
todo &= cmp("cierre previo", dia_real.prev_close, dia_vivo.prev_close)
todo &= cmp("maximo premarket", dia_real.pm_high, dia_vivo.pm_high)
todo &= cmp("expansion %", dia_real.expansion_pct, dia_vivo.expansion_pct)
todo &= cmp("apertura RTH", dia_real.rth_open, dia_vivo.rth_open)
todo &= cmp("vwap final", dia_real.vwap[-1], dia_vivo.vwap[-1])
todo &= cmp("max corriente final", dia_real.max_corriente[-1], dia_vivo.max_corriente[-1])
a = clasificar_apertura(dia_real, hasta=10.0); b = clasificar_apertura(dia_vivo, hasta=10.0)
todo &= cmp("apertura", a, b)

sr = señales_swing(dia_real, desde=10.0); sv = señales_swing(dia_vivo, desde=10.0)
todo &= cmp("senales", len(sr), len(sv))
if len(sr) == len(sv):
    difs = sum(1 for x,y in zip(sr,sv) if abs(hora(dia_real.bars[x])-hora(dia_vivo.bars[y]))>1e-9)
    todo &= cmp("senales en distinta hora", difs, 0)
    pr = [round(dia_real.bars[i][4],6) for i in sr]
    pv = [round(dia_vivo.bars[i][4],6) for i in sv]
    todo &= cmp("precios de entrada iguales", 1 if pr==pv else 0, 1)

print()
print("  " + ("LOS DOS CAMINOS COINCIDEN — lo que se opere es lo que se midio"
              if todo else "DIFIEREN: no usar el puente hasta arreglarlo"))
