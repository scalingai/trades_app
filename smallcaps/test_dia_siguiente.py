#!/usr/bin/env python3
"""El dia DESPUES del gap: sigue habiendo edge, y cuanta frecuencia agrega?

Idea de Agus: "tal vez ese gap paso hace 1 o 2 dias". Es la unica avenida que
queda para subir la frecuencia, porque ya medimos que el universo (el corte de
gap) no es lo que limita — lo que limita es la expansion, y esa se mide contra
el cierre de AYER, asi que un papel que gapeo el lunes el martes ya no gapea
aunque siga caliente y con volumen.

Se probo antes y dio nada. Pero fue con el motor que miraba el futuro en el
presupuesto (error #7) y con el nominal mal calculado. Los dos estan arreglados,
asi que la medicion anterior no vale y hay que rehacerla.

Los dias siguientes YA ESTAN DESCARGADOS: cada evento se bajo con `dias_extra=4`
justamente para esto. No hace falta bajar nada.

Como se selecciona, sin mirar el futuro: el dia D califica como evento (se sabe
a las 09:30 de D). Entonces D+1 y D+2 son operables por ser el dia siguiente a
un evento — informacion disponible desde el cierre de D.
"""
import statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import jornada, poblacion
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import cargar, hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES = 22.9

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

# OJO con dos trampas de `cargar`:
#  · `censo=True` filtra a los dias del censo y con eso BORRA los vecinos, que
#    es justo lo que queremos medir. Hay que cargar sin censo y filtrar aca.
#  · la variable de entorno SMALLCAPS_CENSO lo fuerza igual, asi que se saca.
import os
os.environ.pop("SMALLCAPS_CENSO", None)
print("  cargando TODO lo bajado: censo + vecinos (esto tarda)...", flush=True)
todos = list(cargar(incluir_vecinos=True, censo=False))

# `cargar` no agrega los features que arma `motor.universo()`. Se completan aca
# porque `motor.poblacion` los pide.
import sqlite3 as _sq
import config as _cfg
_db = _sq.connect(_cfg.bars_db_path())
_flo = {(t, d): so for t, d, so in _db.execute(
    "SELECT ticker,d,shares_outstanding FROM event_structure") if so}
_db.close()
for _d in todos:
    _d.dolar_dia = sum((b[5] or 0) * (b[4] or 0) for b in _d.bars)
    _d.float_acciones = _flo.get((_d.ticker, _d.d))
print(f"  {len(todos)} dias en total\n")

# indice: por ticker, las fechas ordenadas
por_tk = defaultdict(list)
for d in todos:
    por_tk[d.ticker].append(d)
for tk in por_tk:
    por_tk[tk].sort(key=lambda x: x.d)

# eventos = los que estan en el censo (poblacion_obs). Los vecinos NO lo estan.
import sqlite3, config
c = sqlite3.connect(config.bars_db_path())
censo = {(t, d) for t, d in c.execute("SELECT ticker,d FROM poblacion_obs")}
c.close()

grupos = {"D  (el evento)": [], "D+1": [], "D+2": []}
for tk, lista in por_tk.items():
    for i, d in enumerate(lista):
        if (tk, d.d) not in censo:
            continue
        grupos["D  (el evento)"].append(d)
        for k, etiqueta in ((1, "D+1"), (2, "D+2")):
            if i + k < len(lista):
                sig = lista[i + k]
                if (tk, sig.d) not in censo:      # si es evento propio, ya cuenta en D
                    grupos[etiqueta].append(sig)

def medir(pool, ap=None, ex=0.0):
    pob = poblacion(pool, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    S = []
    for d in pob:
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if not j: continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da; pa = max(pa, a)
        S.append((d.d, j["pnl"], pa))
    if len(S) < 20: return None
    fechas = len({x[0] for x in S})
    b = statistics.mean(x[1] for x in S); acc = statistics.mean(x[2] for x in S)
    return {"n": len(S), "ses_mes": fechas/MESES, "bruto": b,
            "muerte": b/acc if acc else 0, "mensual": b*fechas/MESES,
            "pos": 100*sum(1 for x in S if x[1] > 0)/len(S)}

print(f"  {'grupo':<22} {'dias':>6} {'n':>5} {'ses/mes':>8} {'bruto/ses':>10} "
      f"{'muerte $/acc':>13} {'bruto/mes':>10} {'pos':>5}")
print("  " + "-"*86)
for etiqueta, pool in grupos.items():
    for lab, ap, ex in ((" · reclaim exp>=100", "reclaim", 100),
                        (" · sin filtro", None, 0)):
        r = medir(pool, ap, ex)
        nm = (etiqueta + lab)[:22]
        if not r:
            print(f"  {nm:<22} {len(pool):>6} {'(muestra corta)':>20}"); continue
        print(f"  {nm:<22} {len(pool):>6} {r['n']:>5} {r['ses_mes']:>8.1f} "
              f"{r['bruto']:>+10.2f} {('$'+format(r['muerte'],'.3f')):>13} "
              f"{r['mensual']:>+10.2f} {r['pos']:>4.0f}%")
    print()
