#!/usr/bin/env python3
"""Etapa 2 — detector de eventos y retornos neutralizados.

Dos cosas, sobre las barras locales y sin tocar la red.

**El detector.** Traslado de `smallcaps/detect_events.py`. No alcanza con RVOL:
un token que normalmente opera $3.000 y hoy operó $300.000 tiene RVOL=100 y es
inoperable. El volumen en dólares define si el evento existe como oportunidad.
Se usa `quote_volume`, que Binance ya calcula por vela y equivale al volumen
por VWAP — no `volumen × cierre`, que en acciones invirtió el signo del
agregado.

**El horizonte, y por qué NO es el intradía.** El detector necesita el volumen
del día completo, así que recién al cierre de D se sabe que D fue un evento.
Medir el retorno apertura→cierre de D sería mirar el futuro: esa información no
estaba disponible cuando el día abrió. El resultado operable es de D en
adelante:

    r_t1 = cierre[D+1] / cierre[D] - 1
    r_t5 = cierre[D+5] / cierre[D] - 1

El intradía de D se guarda igual, marcado como NO operable, porque sirve para
describir el evento.

**La neutralización.** RESEARCH.md §4: la medida primaria no es el retorno sino
el percentil del token entre TODOS los perpetuos vivos ese día. Si BTC arrastra
a las 500, arrastra también a la mediana, y el percentil queda limpio. No
estima betas y no agrega ningún parámetro.

    python eventos.py                 # calcula retornos + detecta
    python eventos.py --stats
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

VENTANA_RVOL = 20        # días previos para la referencia de volumen
MIN_DIAS_PREVIOS = 20

# Permisivos a propósito: se guardan más eventos de los que se van a usar para
# poder re-filtrar hacia arriba sin recomputar. Los umbrales de verdad salen
# del dataset, no de una intuición de hoy.
MIN_RVOL = 4.0
MIN_VOL_USD = 1_000_000
MIN_RANGO_PCT = 10.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retornos (
    simbolo TEXT NOT NULL,
    d       TEXT NOT NULL,
    close   REAL,
    r_t1    REAL,          -- cierre D+1 vs cierre D  (operable)
    r_t5    REAL,          -- cierre D+5 vs cierre D  (operable)
    mae_t5  REAL,          -- peor excursión en contra del corto, D+1..D+5
    pct_t1  REAL,          -- percentil de r_t1 entre todos los vivos ese día
    pct_t5  REAL,
    PRIMARY KEY (simbolo, d)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS eventos (
    simbolo TEXT NOT NULL,
    d       TEXT NOT NULL,
    close REAL, quote_volume REAL,
    rvol REAL,
    rango_pct REAL,        -- (max-min)/cierre previo
    gap_pct REAL,          -- apertura vs cierre previo
    intradia_pct REAL,     -- cierre vs apertura de D — NO operable, descriptivo
    med_quote_volume REAL,
    n_previos INTEGER,
    PRIMARY KEY (simbolo, d)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_ev_d ON eventos(d);
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path(), timeout=60)
    con.executescript(_SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _percentiles(valores: list[float]) -> list[float]:
    """Percentil de cada valor dentro de su lista, con empates promediados.

    Se usa el rango medio en los empates porque muchos perpetuos ilíquidos
    cierran planos y asignarles percentiles distintos sería inventar orden.
    """
    n = len(valores)
    if n < 2:
        return [0.5] * n
    orden = sorted(range(n), key=lambda i: valores[i])
    pct = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        medio = (i + j) / 2.0
        for k in range(i, j + 1):
            pct[orden[k]] = medio / (n - 1)
        i = j + 1
    return pct


def calcular(con: sqlite3.Connection) -> None:
    print("cargando barras…")
    filas = con.execute(
        "SELECT simbolo, d, open, high, low, close, quote_volume "
        "FROM barras ORDER BY simbolo, d").fetchall()
    print(f"  {len(filas):,} barras")

    por_simbolo: dict[str, list] = defaultdict(list)
    for f in filas:
        por_simbolo[f[0]].append(f)

    retornos, eventos = [], []
    for simbolo, barras in por_simbolo.items():
        cierres = [b[5] for b in barras]
        for i, b in enumerate(barras):
            _, d, ap, hi, lo, cl, qv = b
            if not cl:
                continue

            # ── retornos hacia adelante ──
            r1 = (cierres[i + 1] / cl - 1) if i + 1 < len(barras) and cl else None
            r5 = (cierres[i + 5] / cl - 1) if i + 5 < len(barras) and cl else None
            # Máxima excursión adversa para un CORTO abierto al cierre de D:
            # el peor punto es el máximo alcanzado en la ventana.
            mae = None
            if i + 5 < len(barras) and cl:
                pico = max(barras[k][3] for k in range(i + 1, i + 6))
                mae = pico / cl - 1
            retornos.append((simbolo, d, cl, r1, r5, mae, None, None))

            # ── evento ──
            if i < MIN_DIAS_PREVIOS:
                continue
            previos = [barras[k][6] for k in range(i - VENTANA_RVOL, i)
                       if barras[k][6]]
            if len(previos) < MIN_DIAS_PREVIOS:
                continue
            med = statistics.median(previos)
            if not med or not qv:
                continue
            rvol = qv / med
            prev_cl = cierres[i - 1]
            if not prev_cl or not ap:
                continue
            rango = (hi - lo) / prev_cl * 100
            if rvol < MIN_RVOL or qv < MIN_VOL_USD or rango < MIN_RANGO_PCT:
                continue
            eventos.append((simbolo, d, cl, qv, rvol, rango,
                            (ap / prev_cl - 1) * 100, (cl / ap - 1) * 100,
                            med, len(previos)))

    print(f"  retornos: {len(retornos):,}   eventos: {len(eventos):,}")

    # ── neutralización: percentil dentro del día, sobre TODO el universo ──
    print("neutralizando contra el arrastre del mercado…")
    por_dia: dict[str, list[int]] = defaultdict(list)
    for idx, r in enumerate(retornos):
        por_dia[r[1]].append(idx)

    retornos = [list(r) for r in retornos]
    for d, idxs in por_dia.items():
        for col, destino in ((3, 6), (4, 7)):
            validos = [i for i in idxs if retornos[i][col] is not None]
            if len(validos) < 20:
                continue  # con pocos vivos el percentil no significa nada
            pcts = _percentiles([retornos[i][col] for i in validos])
            for i, p in zip(validos, pcts):
                retornos[i][destino] = p

    con.execute("DELETE FROM retornos")
    con.executemany("INSERT INTO retornos VALUES (?,?,?,?,?,?,?,?)", retornos)
    con.execute("DELETE FROM eventos")
    con.executemany("INSERT INTO eventos VALUES (?,?,?,?,?,?,?,?,?,?)", eventos)
    con.commit()
    print("guardado")


def estadisticas(con: sqlite3.Connection) -> None:
    n, nsym, d0, d1 = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT simbolo), MIN(d), MAX(d) "
        "FROM eventos").fetchone()
    if not n:
        print("no hay eventos — corré `python eventos.py`")
        return
    dias = con.execute("SELECT COUNT(DISTINCT d) FROM barras").fetchone()[0]
    print(f"eventos     : {n:,}  sobre {nsym} símbolos")
    print(f"rango       : {d0} → {d1}")
    print(f"por día     : {n/max(1,dias):.1f}")

    print("\nfiltrando más fuerte (como en acciones):")
    for rv, vol, rg in ((5, 2e6, 15), (10, 5e6, 20), (10, 1e7, 30)):
        c = con.execute(
            "SELECT COUNT(*) FROM eventos WHERE rvol>=? AND quote_volume>=? "
            "AND rango_pct>=?", (rv, vol, rg)).fetchone()[0]
        print(f"  RVOL≥{rv:<3} vol≥${vol/1e6:>4.0f}M rango≥{rg:<3}% → "
              f"{c:>6,} eventos ({c/max(1,dias):.1f}/día)")

    print("\nlos 8 eventos más extremos por RVOL:")
    for s, d, rv, v, rg in con.execute(
        "SELECT simbolo,d,rvol,quote_volume,rango_pct FROM eventos "
        "ORDER BY rvol DESC LIMIT 8"
    ):
        print(f"  {s:<16} {d}  RVOL {rv:>7.0f}  ${v/1e6:>7.1f}M  rango {rg:>6.1f}%")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()
    con = conectar()
    if not args.stats:
        calcular(con)
    estadisticas(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
