#!/usr/bin/env python3
"""Un registro por MOMENTO de mercado, no por día.

**El cambio de unidad de análisis.** Hasta acá cada día era una fila y la
entrada era una hora fija (10:00, 12:00). Eso contesta "¿qué pasa si entro al
mediodía?" pero no contesta "¿dónde estuvo el patrón?". Para eso hace falta
describir CADA momento con lo que se sabía en ese momento, y ver qué pasó
después.

Cada 5 minutos de sesión regular se guarda:
  · el estado observable   — distancia al VWAP, al máximo del día, volatilidad
    realizada, volumen relativo, densidad de barras
  · el resultado del short — pero NO en porcentaje: en múltiplos del riesgo

**Por qué en múltiplos de riesgo y no en %.** Agus opera ratios cortos (1:1 o
menos) con el stop atado a la volatilidad del día. Un stop del 8% es enorme en
un papel quieto y ajustado en uno que se mueve 4% por minuto. Medir en % mezcla
las dos cosas; medir en R las separa.

El stop se define como `m × rango típico del minuto`, donde el rango típico es
la MEDIANA de las últimas 30 barras. Con el rango típico en 1,38% (mediana de
la muestra), m=5 es un stop del ~7%.

**El truco que hace esto barato:** en vez de simular cada combinación de
stop × target, se guarda la **máxima excursión favorable ANTES de que salte el
stop**, en unidades de R. De ese único número sale el resultado de CUALQUIER
target: el target R se toca si y solo si esa excursión llegó a R. Cambiar la
grilla de ratios después no cuesta nada — no hay que volver a caminar las
barras.

Convención conservadora, la misma de `test_rr.py`: si en el mismo minuto se
tocan stop y target, **gana el stop**. No se sabe el orden dentro de la barra y
asumir lo favorable sería inventar plata.

    python momentos.py              # construye la tabla
    python momentos.py --stats
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
import time

import config
from dias import CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Múltiplos de volatilidad para el stop. Se guardan los cuatro: elegir uno acá
# sería fijar un parámetro antes de mirar, que es lo que venimos evitando.
MULTIPLOS = (3, 5, 8, 12)
VENTANA = 30          # barras para la referencia de volatilidad y volumen
PASO_MIN = 5          # una entrada cada 5 minutos
DESDE, HASTA = 9.75, 15.5   # 09:45 a 15:30 ET

_SCHEMA = """
CREATE TABLE IF NOT EXISTS momentos (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    hora   REAL NOT NULL,          -- hora ET decimal (10.5 = 10:30)
    precio REAL,
    -- estado del DÍA (constante), para poder filtrar sin joins
    exp_premarket REAL,            -- máx pre-market vs cierre previo, en %
    ratio_volumen REAL,            -- volumen del día vs el del día previo
    -- estado del MOMENTO (todo con barras anteriores a este minuto)
    dist_vwap   REAL,              -- (precio/vwap - 1) * 100
    dist_max    REAL,              -- (precio/máximo corriente - 1) * 100
    edad_max    REAL,              -- minutos desde que se hizo el máximo
    volatilidad REAL,              -- mediana del rango de las 30 barras, en %
    vol_rel     REAL,              -- volumen 30 barras vs las 30 anteriores
    densidad    REAL,              -- barras existentes de las últimas 30
    -- resultado del SHORT, en múltiplos del riesgo, uno por múltiplo de stop
    m3_stop  INTEGER, m3_mfe  REAL, m3_cierre  REAL,
    m5_stop  INTEGER, m5_mfe  REAL, m5_cierre  REAL,
    m8_stop  INTEGER, m8_mfe  REAL, m8_cierre  REAL,
    m12_stop INTEGER, m12_mfe REAL, m12_cierre REAL,
    PRIMARY KEY (ticker, d, hora)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_mom_exp  ON momentos(exp_premarket);
CREATE INDEX IF NOT EXISTS ix_mom_vol  ON momentos(volatilidad);
CREATE INDEX IF NOT EXISTS ix_mom_hora ON momentos(hora);
"""


def _ruta() -> str:
    return str(config.data_dir() / "momentos.sqlite")


def estado(dia, i) -> dict | None:
    """Lo observable en la barra `i`. Solo mira barras anteriores."""
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

    return {
        "precio": p,
        "dist_vwap": (p / dia.vwap[i] - 1) * 100 if dia.vwap[i] else None,
        "dist_max": (p / dia.max_corriente[i] - 1) * 100 if dia.max_corriente[i] else None,
        "edad_max": dia.edad_max[i],
        "volatilidad": statistics.median(rangos),
        "vol_rel": vol_ahora / vol_antes if vol_antes else None,
        # Densidad: cuántos de los últimos 30 MINUTOS tienen barra. En micro
        # caps la barra existe solo si hubo trade, así que es una medida de
        # actividad, no un hueco de datos.
        "densidad": len(prev) / max(1e-9, (prev[-1][0] - prev[0][0]).total_seconds() / 60.0)
        if len(prev) > 1 else None,
    }


def recorrer(dia, i, precio, volatilidad):
    """Camina hacia adelante UNA vez y resuelve los cuatro múltiplos de stop.

    Devuelve {m: (tocó_stop, mfe_en_R, retorno_al_cierre_en_R)}.
    `mfe` es la máxima excursión FAVORABLE alcanzada antes del stop: de ahí sale
    el resultado de cualquier target sin volver a caminar.
    """
    dists = {m: precio * volatilidad * m / 100.0 for m in MULTIPLOS}
    if any(d <= 0 for d in dists.values()):
        return None
    pend = set(MULTIPLOS)
    mfe = {m: 0.0 for m in MULTIPLOS}
    stop = {m: 0 for m in MULTIPLOS}
    cierre = {m: None for m in MULTIPLOS}
    minimo = precio
    ultimo = precio

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
                    stop[m] = 1
                    cierre[m] = -1.0
                    pend.discard(m)
        if bajo and bajo < minimo:
            minimo = bajo
        for m in pend:
            mfe[m] = max(mfe[m], (precio - minimo) / dists[m])
        if not pend:
            break

    for m in pend:  # llegaron al cierre sin tocar el stop
        cierre[m] = (precio - ultimo) / dists[m]
    return {m: (stop[m], mfe[m], cierre[m]) for m in MULTIPLOS}


def construir(*, filtro_split: bool = True) -> int:
    conn = sqlite3.connect(_ruta(), timeout=120)
    conn.executescript(_SCHEMA)
    conn.commit()

    t0 = time.time()
    filas, n_dias = [], 0
    for dia in cargar():
        if filtro_split and (dia.ratio_volumen or 0) < 3:
            continue
        n_dias += 1
        marcas = [DESDE + k * PASO_MIN / 60.0
                  for k in range(int((HASTA - DESDE) * 60 / PASO_MIN) + 1)]
        usados = set()
        for h in marcas:
            i = dia.idx_en(h)
            if i is None or i in usados:
                continue
            usados.add(i)
            e = estado(dia, i)
            if not e or e["volatilidad"] <= 0:
                continue
            r = recorrer(dia, i, e["precio"], e["volatilidad"])
            if not r:
                continue
            fila = [dia.ticker, dia.d, round(h, 4), e["precio"],
                    dia.expansion_pct, dia.ratio_volumen,
                    e["dist_vwap"], e["dist_max"], e["edad_max"],
                    e["volatilidad"], e["vol_rel"], e["densidad"]]
            for m in MULTIPLOS:
                fila += list(r[m])
            filas.append(fila)
        if n_dias % 100 == 0:
            print(f"  {n_dias} días · {len(filas):,} momentos · "
                  f"{time.time()-t0:.0f}s", flush=True)

    conn.execute("DELETE FROM momentos")
    conn.executemany(
        "INSERT OR REPLACE INTO momentos VALUES (" + ",".join("?" * 24) + ")", filas)
    conn.commit()
    conn.close()
    print(f"\n  {len(filas):,} momentos de {n_dias:,} días en "
          f"{time.time()-t0:.0f}s → {_ruta()}")
    return len(filas)


def estadisticas() -> None:
    conn = sqlite3.connect(_ruta())
    n, nd = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker||d) FROM momentos").fetchone()
    print(f"  {n:,} momentos · {nd:,} días")
    print("\n  volatilidad (rango típico del minuto, % del precio)")
    for q, lab in ((.10, "p10"), (.50, "mediana"), (.90, "p90")):
        v = conn.execute(
            "SELECT volatilidad FROM momentos ORDER BY volatilidad "
            f"LIMIT 1 OFFSET CAST(? * (SELECT COUNT(*) FROM momentos) AS INT)",
            (q,)).fetchone()
        print(f"    {lab:8} {v[0]:.2f}%")
    print("\n  cuántas veces salta el stop, por múltiplo")
    for m in MULTIPLOS:
        r = conn.execute(f"SELECT AVG(m{m}_stop)*100, AVG(m{m}_mfe) FROM momentos").fetchone()
        print(f"    stop = {m:>2}× volatilidad  →  salta el {r[0]:.0f}%  ·  "
              f"excursión favorable media {r[1]:.2f}R")
    conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dataset por momento de mercado")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--sin-filtro-split", action="store_true")
    args = ap.parse_args(argv)
    if args.stats:
        estadisticas()
        return 0
    construir(filtro_split=not args.sin_filtro_split)
    estadisticas()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
