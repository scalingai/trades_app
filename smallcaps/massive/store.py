"""Almacén SQLite de barras diarias.

SQLite y no JSON gzipeado: son ~7,5M de filas (500 días × ~15k tickers) y la
etapa siguiente necesita consultarlas por ticker y por fecha. Un directorio de
500 archivos JSON no se puede consultar sin leerlo entero.

`ingest_log` es lo que hace el backfill **resumable**: un job de 100 minutos
que no se puede retomar es un job que hay que correr dos veces.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_daily (
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,          -- YYYY-MM-DD (día de trading, ET)
    o REAL, h REAL, l REAL, c REAL,
    v  REAL,                       -- volumen
    vw REAL,                       -- precio promedio ponderado por volumen
    n  INTEGER,                    -- cantidad de transacciones
    PRIMARY KEY (ticker, d)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_bars_d ON bars_daily(d);

-- Qué fechas ya se bajaron. 'empty' = feriado o día sin datos: se marca para
-- no volver a pedirlo nunca.
CREATE TABLE IF NOT EXISTS ingest_log (
    d          TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    n_tickers  INTEGER NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('ok','empty','error'))
);
"""


class BarStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.bars_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=60)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL en vez de FULL: si se corta la luz podemos perder la última
        # transacción, y eso cuesta 12 segundos de re-descarga. A cambio, el
        # backfill entero es varias veces más rápido.
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "BarStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # --- escritura ---

    def save_day(self, day: date, rows: list[dict], *, status: str = "ok") -> int:
        """Guarda las barras de un día + marca la fecha como procesada, en 1 TXN.

        Atómico a propósito: si el insert de barras entra pero el log no, el
        próximo run vuelve a bajar el día y duplica trabajo; al revés, el día
        queda marcado sin datos y se pierde para siempre.
        """
        d = day.isoformat()
        payload = [
            (
                r["T"], d,
                r.get("o"), r.get("h"), r.get("l"), r.get("c"),
                r.get("v"), r.get("vw"), r.get("n"),
            )
            for r in rows
            if r.get("T")
        ]
        with self._tx() as cx:
            if payload:
                cx.executemany(
                    "INSERT OR REPLACE INTO bars_daily "
                    "(ticker,d,o,h,l,c,v,vw,n) VALUES (?,?,?,?,?,?,?,?,?)",
                    payload,
                )
            cx.execute(
                "INSERT OR REPLACE INTO ingest_log (d,fetched_at,n_tickers,status) "
                "VALUES (?,?,?,?)",
                (d, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 len(payload), status if payload else "empty"),
            )
        return len(payload)

    # --- lectura ---

    def done_dates(self) -> set[str]:
        """Fechas ya procesadas (ok o empty). Lo que hace el job resumable."""
        cur = self._conn.execute(
            "SELECT d FROM ingest_log WHERE status IN ('ok','empty')"
        )
        return {r[0] for r in cur}

    def stats(self) -> dict:
        cx = self._conn
        bars = cx.execute("SELECT COUNT(*) FROM bars_daily").fetchone()[0]
        tickers = cx.execute("SELECT COUNT(DISTINCT ticker) FROM bars_daily").fetchone()[0]
        days = cx.execute(
            "SELECT COUNT(*), MIN(d), MAX(d) FROM ingest_log WHERE status='ok'"
        ).fetchone()
        empty = cx.execute(
            "SELECT COUNT(*) FROM ingest_log WHERE status='empty'"
        ).fetchone()[0]
        return {
            "barras": bars,
            "tickers_distintos": tickers,
            "dias_con_datos": days[0],
            "dias_vacios": empty,
            "desde": days[1],
            "hasta": days[2],
            "db_mb": self.path.stat().st_size / 1e6 if self.path.exists() else 0.0,
        }
