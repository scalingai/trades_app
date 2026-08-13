"""Mapeo ticker <-> CIK usando el archivo oficial de la SEC."""

from __future__ import annotations

from functools import lru_cache

from .client import fetch_json

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, int], dict[int, str]]:
    raw = fetch_json(_TICKERS_URL, cache_hours=24 * 7)
    by_ticker: dict[str, int] = {}
    by_cik: dict[int, str] = {}
    for row in raw.values():
        ticker = str(row["ticker"]).upper()
        cik = int(row["cik_str"])
        by_ticker[ticker] = cik
        # Una CIK puede tener varias clases (BRK.A/BRK.B). Nos quedamos con
        # el primero, que en el archivo de la SEC es la clase principal.
        by_cik.setdefault(cik, ticker)
    return by_ticker, by_cik


def cik_for(ticker: str) -> int:
    """CIK numérica para un ticker. KeyError si no existe."""
    by_ticker, _ = _load()
    key = ticker.upper().strip()
    if key not in by_ticker:
        raise KeyError(f"ticker desconocido en EDGAR: {ticker!r}")
    return by_ticker[key]


def ticker_for(cik: int) -> str | None:
    _, by_cik = _load()
    return by_cik.get(int(cik))


def cik10(cik: int | str) -> str:
    """CIK con padding a 10 dígitos, el formato que piden los endpoints XBRL."""
    return f"{int(cik):010d}"


def all_tickers() -> dict[str, int]:
    by_ticker, _ = _load()
    return dict(by_ticker)
