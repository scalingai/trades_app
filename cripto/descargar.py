#!/usr/bin/env python3
"""Etapa 0 — universo y barras diarias de todos los perpetuos, vivos y muertos.

Baja las velas diarias de cada símbolo USDT del archivo público y las guarda en
SQLite. Resumable: los meses ya bajados quedan en cache y los huecos quedan
marcados, así que relanzar continúa donde quedó sin repetir peticiones.

**Se bajan también los deslistados.** Es el punto entero del ejercicio: los
perpetuos que Binance sacó del listado no son una muestra aleatoria, son los
que peor terminaron. Mirar solo lo que cotiza hoy es el sesgo de supervivencia
que `smallcaps/RESEARCH.md` §3.1 llama "el asesino silencioso".

    python descargar.py                  # universo + barras
    python descargar.py --stats          # qué hay bajado
    python descargar.py --hilos 24
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import archivo
import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Ventana de descarga. Arranca antes que la ventana de estudio porque el
# detector necesita 20 días previos de volumen para el RVOL, y el resultado
# necesita días posteriores para T+1 y T+5.
DESDE = date(2025, 6, 1)
HASTA = date.today()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS barras (
    simbolo TEXT NOT NULL,
    d       TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL,
    quote_volume REAL,          -- volumen en USDT ya calculado por Binance
    trades INTEGER,
    taker_buy_quote REAL,       -- cuánto del volumen fue comprador agresivo
    PRIMARY KEY (simbolo, d)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_barras_d ON barras(d);

CREATE TABLE IF NOT EXISTS universo (
    simbolo    TEXT PRIMARY KEY,
    primer_dia TEXT,
    ultimo_dia TEXT,
    n_dias     INTEGER,
    vivo       INTEGER          -- 1 si tiene datos en los últimos 7 días
);
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path(), timeout=60)
    con.executescript(_SCHEMA)
    # WAL para que varios hilos puedan leer mientras el principal escribe.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def simbolos_objetivo() -> list[str]:
    """Perpetuos USDT del archivo.

    Se excluyen BUSD (moneda discontinuada, todos muertos) y USDC (casi todos
    duplican un par USDT del mismo token, y contarlos dos veces inflaría el n
    con observaciones que no son independientes).
    """
    todos = archivo.listar_simbolos()
    return [s for s in todos if s.endswith("USDT")]


def _bajar_uno(simbolo: str) -> tuple[str, list[dict]]:
    try:
        return simbolo, archivo.barras_diarias(simbolo, DESDE, HASTA)
    except Exception as e:
        print(f"  ! {simbolo}: {type(e).__name__}: {e}", flush=True)
        return simbolo, []


def descargar(hilos: int = 16) -> None:
    con = conectar()
    simbolos = simbolos_objetivo()
    print(f"universo: {len(simbolos)} perpetuos USDT en el archivo")

    # Los que ya están completos hasta la última fecha se saltean.
    ya = dict(con.execute(
        "SELECT simbolo, MAX(d) FROM barras GROUP BY simbolo").fetchall())
    limite = (HASTA - timedelta(days=2)).isoformat()
    pendientes = [s for s in simbolos if ya.get(s, "") < limite]
    print(f"pendientes: {len(pendientes)}  (ya completos: {len(simbolos)-len(pendientes)})")
    if not pendientes:
        print("nada que bajar")
        return

    hecho = filas_tot = 0
    with ThreadPoolExecutor(hilos) as ex:
        futuros = [ex.submit(_bajar_uno, s) for s in pendientes]
        for fut in as_completed(futuros):
            simbolo, barras = fut.result()
            hecho += 1
            if barras:
                con.executemany(
                    "INSERT OR REPLACE INTO barras "
                    "(simbolo,d,open,high,low,close,volume,quote_volume,trades,taker_buy_quote)"
                    " VALUES (:simbolo,:d,:open,:high,:low,:close,:volume,"
                    ":quote_volume,:trades,:taker_buy_quote)",
                    [dict(b, simbolo=simbolo) for b in barras])
                con.commit()
                filas_tot += len(barras)
            if hecho % 50 == 0 or hecho == len(pendientes):
                print(f"  {hecho}/{len(pendientes)} símbolos · {filas_tot:,} barras",
                      flush=True)

    _refrescar_universo(con)
    print(f"\nlisto: {filas_tot:,} barras nuevas")


def _refrescar_universo(con: sqlite3.Connection) -> None:
    """Deriva del propio dataset la fecha de listado y si sigue vivo.

    La fecha de listado es un feature (S5 en RESEARCH.md §3) y sale gratis de
    acá: no hay que pedírsela a nadie.
    """
    corte = (date.today() - timedelta(days=7)).isoformat()
    con.execute("DELETE FROM universo")
    con.execute("""
        INSERT INTO universo (simbolo, primer_dia, ultimo_dia, n_dias, vivo)
        SELECT simbolo, MIN(d), MAX(d), COUNT(*), MAX(d) >= ?
          FROM barras GROUP BY simbolo
    """, (corte,))
    con.commit()


def estadisticas() -> None:
    con = conectar()
    fila = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT simbolo), MIN(d), MAX(d) FROM barras"
    ).fetchone()
    if not fila[0]:
        print("no hay barras todavía — corré `python descargar.py`")
        return
    n, nsym, d0, d1 = fila
    print(f"barras     : {n:,}")
    print(f"símbolos   : {nsym}")
    print(f"rango      : {d0} → {d1}")

    vivos = con.execute("SELECT SUM(vivo), COUNT(*) FROM universo").fetchone()
    if vivos and vivos[1]:
        muertos = vivos[1] - (vivos[0] or 0)
        print(f"vivos      : {vivos[0]}   muertos: {muertos}"
              f"   ({100*muertos/vivos[1]:.1f}% del universo)")
        print("             ← esos muertos son los que un estudio ingenuo pierde")

    print("\nsímbolos con datos por mes:")
    for mes, c in con.execute(
        "SELECT substr(d,1,7) m, COUNT(DISTINCT simbolo) FROM barras "
        "GROUP BY m ORDER BY m"
    ).fetchall():
        print(f"  {mes}  {c:>4}  {'█' * (c // 20)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stats", action="store_true")
    p.add_argument("--hilos", type=int, default=16)
    args = p.parse_args()

    if args.stats:
        estadisticas()
    else:
        descargar(args.hilos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
