"""Descarga y almacén de barras de 1 minuto.

Se separa de `store.py` porque el volumen es otro: las diarias son ~15.000
tickers × 1 fila; las de minuto son 1 ticker × ~900 filas por día. Y el patrón
de acceso es distinto — acá siempre se consulta un ticker en un día concreto.

Cobertura verificada con la sonda: 04:00 a 20:00 ET, o sea que incluye
pre-market y after-hours. En micro caps las barras son RALAS: la vela existe
solo si hubo un trade, así que un hueco significa "no operó", no "falta el
dato". La densidad de barras es, en sí misma, una medida de actividad.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config

from .client import MassiveClient, MassiveError, NotAuthorized

ET = ZoneInfo("America/New_York")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_minute (
    ticker TEXT NOT NULL,
    ts     INTEGER NOT NULL,   -- epoch ms (UTC). Se convierte a ET al leer.
    o REAL, h REAL, l REAL, c REAL, v REAL, vw REAL, n INTEGER,
    PRIMARY KEY (ticker, ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_min_ticker ON bars_minute(ticker);

-- Qué (ticker, día de evento) ya se bajó. Hace la descarga resumable.
CREATE TABLE IF NOT EXISTS minute_log (
    ticker  TEXT NOT NULL,
    d       TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    n_bars  INTEGER NOT NULL,
    status  TEXT NOT NULL,
    PRIMARY KEY (ticker, d)
);
"""


class MinuteStore:
    def __init__(self, path=None) -> None:
        self.path = path or config.data_dir() / "minutes.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=120)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def done(self) -> set[tuple[str, str]]:
        return {(t, d) for t, d in
                self.conn.execute("SELECT ticker, d FROM minute_log WHERE status='ok'")}

    def save(self, ticker: str, d: date, bars: list[dict], status: str = "ok") -> int:
        rows = [(ticker, b["t"], b.get("o"), b.get("h"), b.get("l"), b.get("c"),
                 b.get("v"), b.get("vw"), b.get("n")) for b in bars if b.get("t")]
        try:
            if rows:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO bars_minute VALUES (?,?,?,?,?,?,?,?,?)", rows)
            self.conn.execute(
                "INSERT OR REPLACE INTO minute_log VALUES (?,?,?,?,?)",
                (ticker, d.isoformat(),
                 datetime.now(tz=ET).isoformat(timespec="seconds"),
                 len(rows), status if rows else "empty"))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(rows)

    def day_bars(self, ticker: str, d: date) -> list[tuple]:
        """Barras de un ticker en un día ET, ordenadas. Devuelve (hora_ET, o,h,l,c,v)."""
        ini = int(datetime(d.year, d.month, d.day, 0, 0, tzinfo=ET).timestamp() * 1000)
        fin = int((datetime(d.year, d.month, d.day, 0, 0, tzinfo=ET)
                   + timedelta(days=1)).timestamp() * 1000)
        out = []
        for ts, o, h, l, c, v in self.conn.execute(
            "SELECT ts,o,h,l,c,v FROM bars_minute WHERE ticker=? AND ts>=? AND ts<? ORDER BY ts",
            (ticker, ini, fin)
        ):
            out.append((datetime.fromtimestamp(ts / 1000, tz=ET), o, h, l, c, v))
        return out


def fetch_event(client: MassiveClient, store: MinuteStore, ticker: str, d: date,
                *, dias_extra: int = 4) -> tuple[int, str]:
    """Baja el día del evento y los siguientes en UNA llamada.

    Un rango de ~4 días calendario garantiza cubrir el día hábil siguiente aunque
    caiga fin de semana o feriado — que es el que necesita la hipótesis del
    barrido.
    """
    hasta = d + timedelta(days=dias_extra)
    try:
        res = client.get(
            f"/v2/aggs/ticker/{ticker}/range/1/minute/{d.isoformat()}/{hasta.isoformat()}",
            adjusted="false", sort="asc", limit=50000)
    except NotAuthorized:
        store.save(ticker, d, [], status="no_auth")
        return 0, "no_auth"
    except MassiveError as exc:
        store.save(ticker, d, [], status="error")
        return 0, f"error: {exc}"

    bars = res.get("results") or []
    n = store.save(ticker, d, bars)
    return n, "ok" if n else "empty"
