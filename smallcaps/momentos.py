#!/usr/bin/env python3
"""Un registro por MINUTO de mercado, no por día.

**El cambio de unidad de análisis.** Hasta acá cada día era una fila y la
entrada una hora fija. Eso contesta "¿qué pasa si entro al mediodía?" pero no
"¿dónde estuvo el patrón?". Para eso hace falta describir CADA minuto con lo
que se sabía en ese minuto, y ver qué pasó después.

La primera versión muestreaba cada 5 minutos y estaba mal: 5 minutos es una
elección arbitraria y encima descarta 4 de cada 5 momentos de decisión. Ahora
el paso es **1 minuto**, que es la resolución más chica que tenemos —las barras
vienen de agregados de 1 minuto, no de ticks—. Bajar de ahí necesita datos de
trades, que es otro plan del proveedor.

Cada minuto se guarda:
  · el estado observable   — VWAP, EMAs, RSI, perfil de volumen, volatilidad
    realizada, volumen relativo, estructura de máximos
  · la distancia a cada NIVEL estructural — los candidatos a target
  · el resultado del short en múltiplos del riesgo

**Por qué los niveles y no un ratio fijo.** Un target de "1:1" es un número que
elegimos nosotros. Un target en el VWAP, en el POC o en el mínimo del día lo
pone el mercado, y el ratio sale como CONSECUENCIA de dónde está la estructura:
si el nivel está cerca el ratio es corto, si está lejos es largo. Eso es lo que
hace un discrecional cuando dice "acá tengo 1:1 y allá tengo 1:3".

**El truco que hace esto barato:** en vez de simular cada combinación de
stop × target, se guarda la **máxima excursión favorable ANTES de que salte el
stop**, en unidades de R. De ese único número sale el resultado de CUALQUIER
target —fijo o estructural— sin volver a caminar las barras.

Convención conservadora, la misma de `test_rr.py`: si en el mismo minuto se
tocan stop y target, **gana el stop**.

    python momentos.py              # construye la tabla (paso 1 minuto)
    python momentos.py --paso 5     # más rápido, para probar
    python momentos.py --stats
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
import time

import config
import indicadores
from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Múltiplos de volatilidad para el stop. Se guardan los cuatro: elegir uno acá
# sería fijar un parámetro antes de mirar.
MULTIPLOS = (3, 5, 8, 12)
VENTANA = 30          # barras para la referencia de volatilidad y volumen
DESDE, HASTA = 9.75, 15.5   # 09:45 a 15:30 ET

ESTADO = ["dist_vwap", "dist_max", "edad_max", "volatilidad", "vol_rel", "densidad",
          "dist_ema9", "dist_ema20", "rsi", "dist_poc", "vol_arriba", "max_dec"]
# Distancia HACIA ABAJO hasta cada nivel, en % del precio. Positiva = el nivel
# está debajo, o sea que sirve como target de un short.
NIVELES = ["niv_vwap", "niv_poc", "niv_ema20", "niv_min_dia", "niv_pm_low",
           "niv_prev_close"]
RESULTADO = [f"m{m}_{k}" for m in MULTIPLOS for k in ("stop", "mfe", "cierre")]
COLUMNAS = (["ticker", "d", "hora", "precio", "exp_premarket", "ratio_volumen"]
            + ESTADO + NIVELES + RESULTADO)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS momentos (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    hora   REAL NOT NULL,
    precio REAL,
    exp_premarket REAL,
    ratio_volumen REAL,
    {', '.join(c + ' REAL' for c in ESTADO)},
    {', '.join(c + ' REAL' for c in NIVELES)},
    {', '.join((c + ' INTEGER') if c.endswith('_stop') else (c + ' REAL')
               for c in RESULTADO)},
    PRIMARY KEY (ticker, d, hora)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_mom_exp  ON momentos(exp_premarket);
CREATE INDEX IF NOT EXISTS ix_mom_vol  ON momentos(volatilidad);
CREATE INDEX IF NOT EXISTS ix_mom_hora ON momentos(hora);
"""


def _ruta():
    return config.data_dir() / "momentos.sqlite"


def _dist(precio, nivel):
    """Distancia hacia abajo hasta el nivel, en % del precio. None si está arriba."""
    if not precio or nivel is None:
        return None
    d = (precio - nivel) / precio * 100.0
    return d if d > 0 else None


def estado(dia, ind, i):
    """Lo observable en la barra `i`. Solo mira barras anteriores o la actual."""
    b = dia.bars[i]
    p = b[4]
    if not p or i < VENTANA:
        return None
    prev = dia.bars[i - VENTANA:i]
    ant = dia.bars[max(0, i - 2 * VENTANA):i - VENTANA]
    rangos = [(x[2] - x[3]) / x[4] * 100 for x in prev if x[2] and x[3] and x[4]]
    if not rangos:
        return None
    vol_ahora = sum(x[5] or 0 for x in prev)
    vol_antes = sum(x[5] or 0 for x in ant)
    minutos = (prev[-1][0] - prev[0][0]).total_seconds() / 60.0

    e = {
        "precio": p,
        "dist_vwap": (p / dia.vwap[i] - 1) * 100 if dia.vwap[i] else None,
        "dist_max": (p / dia.max_corriente[i] - 1) * 100 if dia.max_corriente[i] else None,
        "edad_max": dia.edad_max[i],
        "volatilidad": statistics.median(rangos),
        "vol_rel": vol_ahora / vol_antes if vol_antes else None,
        "densidad": len(prev) / minutos if minutos > 0 else None,
        "dist_ema9": (p / ind["ema9"][i] - 1) * 100 if ind["ema9"][i] else None,
        "dist_ema20": (p / ind["ema20"][i] - 1) * 100 if ind["ema20"][i] else None,
        "rsi": ind["rsi"][i],
        "dist_poc": (p / ind["poc"][i] - 1) * 100 if ind["poc"][i] else None,
        "vol_arriba": ind["vol_arriba"][i],
        "max_dec": ind["max_dec"][i],
    }
    e.update({
        "niv_vwap": _dist(p, dia.vwap[i]),
        "niv_poc": _dist(p, ind["poc"][i]),
        "niv_ema20": _dist(p, ind["ema20"][i]),
        "niv_min_dia": _dist(p, ind["min_dia"][i]),
        "niv_pm_low": _dist(p, ind["pm_low"]),
        "niv_prev_close": _dist(p, dia.prev_close),
    })
    return e


def recorrer(dia, i, precio, volatilidad):
    """Camina hacia adelante UNA vez y resuelve los cuatro múltiplos de stop.

    Devuelve {m: (tocó_stop, mfe_en_R, retorno_al_cierre_en_R)}. `mfe` es la
    máxima excursión favorable alcanzada antes del stop: de ahí sale el
    resultado de cualquier target sin volver a caminar.
    """
    dists = {m: precio * volatilidad * m / 100.0 for m in MULTIPLOS}
    if any(d <= 0 for d in dists.values()):
        return None
    pend = set(MULTIPLOS)
    mfe = {m: 0.0 for m in MULTIPLOS}
    stop = {m: 0 for m in MULTIPLOS}
    cierre = {m: None for m in MULTIPLOS}
    minimo = ultimo = precio

    for b in dia.bars[i + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        alto, bajo, c = b[2], b[3], b[4]
        if c:
            ultimo = c
        # Conservador: el stop se evalúa ANTES de acreditar el mínimo de esta
        # barra. Si en el mismo minuto se tocan los dos, gana el stop.
        if alto:
            for m in list(pend):
                if alto >= precio + dists[m]:
                    stop[m], cierre[m] = 1, -1.0
                    pend.discard(m)
        if bajo and bajo < minimo:
            minimo = bajo
        for m in pend:
            mfe[m] = max(mfe[m], (precio - minimo) / dists[m])
        if not pend:
            break

    for m in pend:
        cierre[m] = (precio - ultimo) / dists[m]
    return {m: (stop[m], mfe[m], cierre[m]) for m in MULTIPLOS}


def construir(*, paso: int = 1, filtro_split: bool = True) -> int:
    conn = sqlite3.connect(_ruta(), timeout=120)
    conn.execute("DROP TABLE IF EXISTS momentos")
    conn.executescript(_SCHEMA)
    conn.commit()

    t0 = time.time()
    total, n_dias = 0, 0
    lote = []
    for dia in cargar():
        if filtro_split and (dia.ratio_volumen or 0) < 3:
            continue
        n_dias += 1
        ind = indicadores.calcular(dia)
        for i, b in enumerate(dia.bars):
            h = hora(b)
            if not (DESDE <= h <= HASTA):
                continue
            if paso > 1 and int(round(h * 60)) % paso:
                continue
            e = estado(dia, ind, i)
            if not e or e["volatilidad"] <= 0:
                continue
            r = recorrer(dia, i, e["precio"], e["volatilidad"])
            if not r:
                continue
            fila = [dia.ticker, dia.d, round(h, 5), e["precio"],
                    dia.expansion_pct, dia.ratio_volumen]
            fila += [e[c] for c in ESTADO] + [e[c] for c in NIVELES]
            for m in MULTIPLOS:
                fila += list(r[m])
            lote.append(fila)
        if len(lote) >= 20000:
            conn.executemany(
                f"INSERT OR REPLACE INTO momentos VALUES ({','.join('?'*len(COLUMNAS))})",
                lote)
            conn.commit()
            total += len(lote)
            lote = []
        if n_dias % 100 == 0:
            print(f"  {n_dias} días · {total + len(lote):,} momentos · "
                  f"{time.time()-t0:.0f}s", flush=True)
    if lote:
        conn.executemany(
            f"INSERT OR REPLACE INTO momentos VALUES ({','.join('?'*len(COLUMNAS))})", lote)
        conn.commit()
        total += len(lote)
    conn.close()
    print(f"\n  {total:,} momentos de {n_dias:,} días en {time.time()-t0:.0f}s "
          f"→ {_ruta()}")
    return total


def estadisticas() -> None:
    conn = sqlite3.connect(_ruta())
    n, nd = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker||d) FROM momentos").fetchone()
    print(f"  {n:,} momentos · {nd:,} días")
    print("\n  cuántas veces salta el stop, por múltiplo de volatilidad")
    for m in MULTIPLOS:
        r = conn.execute(f"SELECT AVG(m{m}_stop)*100, AVG(m{m}_mfe) FROM momentos").fetchone()
        print(f"    stop = {m:>2}×  →  salta el {r[0]:.0f}%  ·  "
              f"excursión favorable media {r[1]:.2f}R")
    print("\n  ratio IMPLÍCITO por nivel (mediana), con stop de 8× volatilidad")
    print("  = a qué ratio te obliga cada nivel, en vez de elegirlo vos")
    for niv in NIVELES:
        r = conn.execute(
            f"SELECT COUNT(*), AVG({niv} IS NOT NULL)*100 FROM momentos").fetchone()
        med = conn.execute(
            f"SELECT {niv}/(8*volatilidad) FROM momentos WHERE {niv} IS NOT NULL "
            f"ORDER BY {niv}/(8*volatilidad) LIMIT 1 "
            f"OFFSET (SELECT COUNT(*)/2 FROM momentos WHERE {niv} IS NOT NULL)").fetchone()
        print(f"    {niv:16} disponible el {r[1]:>3.0f}% de los minutos · "
              f"ratio mediano 1:{med[0]:.2f}" if med else f"    {niv:16} —")
    conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dataset por minuto de mercado")
    ap.add_argument("--paso", type=int, default=1, help="minutos entre momentos")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--sin-filtro-split", action="store_true")
    args = ap.parse_args(argv)
    if args.stats:
        estadisticas()
        return 0
    construir(paso=args.paso, filtro_split=not args.sin_filtro_split)
    estadisticas()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
