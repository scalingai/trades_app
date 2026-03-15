"""
Market data provider using Binance API.
Prices, klines (OHLCV), and ticker info.
"""
import pandas as pd
from binance.client import Client
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, KLINES_DEFAULT_LIMIT

_client = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
    return _client


def get_price(symbol: str) -> dict:
    """Current price, 24h change %, and volume."""
    client = get_client()
    ticker = client.get_ticker(symbol=symbol)
    return {
        "symbol": symbol,
        "price": float(ticker["lastPrice"]),
        "price_change_pct": float(ticker["priceChangePercent"]),
        "volume": float(ticker["volume"]),
        "quote_volume": float(ticker["quoteVolume"]),
        "high_24h": float(ticker["highPrice"]),
        "low_24h": float(ticker["lowPrice"]),
    }


def get_klines(symbol: str, interval: str = "15m", limit: int = KLINES_DEFAULT_LIMIT) -> pd.DataFrame:
    """OHLCV candlestick data as DataFrame."""
    client = get_client()
    interval_map = {
        "1m": Client.KLINE_INTERVAL_1MINUTE,
        "3m": Client.KLINE_INTERVAL_3MINUTE,
        "5m": Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
        "30m": Client.KLINE_INTERVAL_30MINUTE,
        "1h": Client.KLINE_INTERVAL_1HOUR,
        "4h": Client.KLINE_INTERVAL_4HOUR,
        "1d": Client.KLINE_INTERVAL_1DAY,
    }
    klines = client.get_klines(
        symbol=symbol,
        interval=interval_map.get(interval, interval),
        limit=limit,
    )
    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_volume", "taker_buy_quote_volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df


def get_ticker_info(symbol: str) -> dict:
    """General ticker info: best bid/ask, 24h stats."""
    client = get_client()
    book = client.get_order_book(symbol=symbol, limit=5)
    ticker = client.get_ticker(symbol=symbol)
    return {
        "symbol": symbol,
        "bid": float(book["bids"][0][0]) if book["bids"] else None,
        "ask": float(book["asks"][0][0]) if book["asks"] else None,
        "spread_pct": ((float(book["asks"][0][0]) - float(book["bids"][0][0])) / float(book["bids"][0][0]) * 100) if book["bids"] and book["asks"] else None,
        "volume_24h": float(ticker["volume"]),
        "trades_24h": int(ticker["count"]),
    }
