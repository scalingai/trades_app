"""La cuota discrecional, en una tabla.

**El problema que esto resuelve.** El sistema mide features que YO elegí:
distancia al VWAP, volatilidad, expansión. Lo que ve un discrecional mirando el
gráfico —"esto es un short", "esto es una trampa"— no está en ninguna columna,
y mientras no esté no se puede saber si aporta información o si es una historia
que uno se cuenta.

La única forma honesta de meterlo es la misma que ya se usó con el LLM en la
Capa 1 del plan: **que emita una ETIQUETA, no un número**, y después medir esa
etiqueta contra el resultado. Si los minutos marcados a mano rinden mejor que
los que el modelo elegiría solo, la discreción aporta y se puede empezar a
buscar qué feature la aproxima. Si rinden igual, no aporta — y eso también es
un resultado.

Se marca desde el visor, sobre el gráfico. La tabla es append-only: una marca
equivocada se corrige agregando otra, nunca editando la historia.

    from etiquetas import Etiquetas
    et = Etiquetas()
    et.marcar("NAMI", "2026-08-07", 10.5, "entrada_short", "perdió el VWAP con volumen")
    et.de_dia("NAMI", "2026-08-07")
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import config

# Vocabulario cerrado a propósito. Un campo de texto libre se llena de sinónimos
# en dos semanas y deja de ser agrupable. La nota libre está aparte.
TIPOS = {
    "entrada_short": "acá entraría corto",
    "entrada_long": "acá entraría largo",
    "no_va": "esto NO se opera",
    "salida": "acá salgo",
    "patron": "el patrón está acá",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS etiquetas (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    hora   REAL NOT NULL,          -- hora ET decimal, la misma clave que `momentos`
    tipo   TEXT NOT NULL,
    nota   TEXT,
    autor  TEXT NOT NULL DEFAULT 'agus',
    creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_et_dia ON etiquetas(ticker, d);
"""


class Etiquetas:
    def __init__(self, path=None):
        self.path = path or config.data_dir() / "etiquetas.sqlite"
        self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def marcar(self, ticker: str, d: str, hora: float, tipo: str,
               nota: str = "", autor: str = "agus") -> int:
        if tipo not in TIPOS:
            raise ValueError(f"tipo desconocido: {tipo}. Válidos: {sorted(TIPOS)}")
        cur = self.conn.execute(
            "INSERT INTO etiquetas (ticker,d,hora,tipo,nota,autor,creado) "
            "VALUES (?,?,?,?,?,?,?)",
            (ticker, d, round(float(hora), 5), tipo, nota or None, autor,
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()
        return cur.lastrowid

    def borrar(self, id_: int) -> None:
        self.conn.execute("DELETE FROM etiquetas WHERE id=?", (id_,))
        self.conn.commit()

    def de_dia(self, ticker: str, d: str) -> list[dict]:
        cols = ("id", "hora", "tipo", "nota", "autor", "creado")
        return [dict(zip(cols, r)) for r in self.conn.execute(
            f"SELECT {','.join(cols)} FROM etiquetas WHERE ticker=? AND d=? "
            "ORDER BY hora", (ticker, d))]

    def todas(self) -> list[dict]:
        cols = ("id", "ticker", "d", "hora", "tipo", "nota", "autor", "creado")
        return [dict(zip(cols, r)) for r in self.conn.execute(
            f"SELECT {','.join(cols)} FROM etiquetas ORDER BY d, ticker, hora")]

    def resumen(self) -> dict[str, int]:
        return dict(self.conn.execute(
            "SELECT tipo, COUNT(*) FROM etiquetas GROUP BY tipo"))

    def close(self) -> None:
        self.conn.close()
