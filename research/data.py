"""
Descarga y cachea klines historicos de Binance.

Usa el mirror publico data-api.binance.vision porque api.binance.com devuelve
451 desde varias regiones. No requiere API key.

El cache en disco es importante: las pruebas se corren muchas veces y bajar
dos anos de velas de tres activos en cada corrida es lento y ademas hace que
los resultados dependan del momento de la descarga.
"""
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

BASE = "https://data-api.binance.vision/api/v3/klines"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
      "1d": 86_400_000}

COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def _get(url: str, retries: int = 4):
    for i in range(retries):
        try:
            return json.load(urllib.request.urlopen(url, timeout=30))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)
    raise RuntimeError("unreachable")


def fetch(symbol: str, interval: str, n_candles: int = 17_000, use_cache: bool = True) -> pd.DataFrame:
    """Descarga las ultimas n_candles velas, paginando hacia atras."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{n_candles}.csv")
    if use_cache and os.path.exists(path):
        return pd.read_csv(path, parse_dates=["dt"])

    step = MS[interval]
    end = int(time.time() * 1000)
    chunks = []
    remaining = n_candles

    while remaining > 0:
        limit = min(1000, remaining)
        start = end - limit * step
        rows = _get(f"{BASE}?symbol={symbol}&interval={interval}&limit={limit}&startTime={start}&endTime={end}")
        if not rows:
            break
        chunks.append(rows)
        remaining -= len(rows)
        end = int(rows[0][0]) - 1
        if len(rows) < limit:
            break
        time.sleep(0.15)

    raw = [r for c in reversed(chunks) for r in c]
    df = pd.DataFrame(raw, columns=COLS)
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base"]:
        df[c] = df[c].astype(float)
    df["trades"] = df["trades"].astype(int)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df[["dt", "open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base"]]
    df = df.drop_duplicates(subset="dt").sort_values("dt").reset_index(drop=True)

    df.to_csv(path, index=False)
    return df


def load_all(symbols: list[str], interval: str, n_candles: int = 17_000) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        df = fetch(s, interval, n_candles)
        out[s] = df
        span = (df["dt"].iloc[-1] - df["dt"].iloc[0]).days
        print(f"  {s:<9} {interval:>4}  {len(df):>6} velas  {df['dt'].iloc[0]:%Y-%m-%d} -> "
              f"{df['dt'].iloc[-1]:%Y-%m-%d}  ({span} dias)")
    return out


def log_returns(df: pd.DataFrame) -> np.ndarray:
    return np.diff(np.log(df["close"].to_numpy()))


def align(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Alinea varios activos por timestamp. Devuelve closes en columnas."""
    merged = None
    for sym, df in dfs.items():
        s = df[["dt", "close"]].rename(columns={"close": sym})
        merged = s if merged is None else merged.merge(s, on="dt", how="inner")
    return merged.reset_index(drop=True)
