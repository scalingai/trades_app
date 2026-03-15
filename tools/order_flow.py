"""
Order flow analysis using Binance API.
Order book depth, recent trades, delta volume, funding rate, absorption detection.
"""
import pandas as pd
import numpy as np
from binance.client import Client
from tools.market_data import get_client, get_klines


def get_order_book(symbol: str, limit: int = 100) -> dict:
    """Bid/ask depth with imbalance analysis."""
    client = get_client()
    book = client.get_order_book(symbol=symbol, limit=limit)

    bids = [(float(p), float(q)) for p, q in book["bids"]]
    asks = [(float(p), float(q)) for p, q in book["asks"]]

    total_bid_vol = sum(q for _, q in bids)
    total_ask_vol = sum(q for _, q in asks)
    imbalance = (total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) if (total_bid_vol + total_ask_vol) > 0 else 0

    return {
        "symbol": symbol,
        "best_bid": bids[0][0] if bids else None,
        "best_ask": asks[0][0] if asks else None,
        "total_bid_volume": total_bid_vol,
        "total_ask_volume": total_ask_vol,
        "imbalance": round(imbalance, 4),  # +1 = all bids, -1 = all asks
        "bid_levels": bids[:20],
        "ask_levels": asks[:20],
        "bid_walls": [(p, q) for p, q in bids if q > total_bid_vol * 0.05],
        "ask_walls": [(p, q) for p, q in asks if q > total_ask_vol * 0.05],
    }


def get_recent_trades(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Recent trades with buyer_is_maker flag (taker direction)."""
    client = get_client()
    trades = client.get_recent_trades(symbol=symbol, limit=limit)
    df = pd.DataFrame(trades)
    df["price"] = df["price"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["quoteQty"] = df["quoteQty"].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


def get_aggr_trades_window(symbol: str, start_time: int, end_time: int) -> pd.DataFrame:
    """Aggregated trades in a specific time window (for key session analysis)."""
    client = get_client()
    trades = client.get_aggregate_trades(
        symbol=symbol,
        startTime=start_time,
        endTime=end_time,
    )
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df.rename(columns={"a": "id", "p": "price", "q": "qty", "T": "time", "m": "is_buyer_maker"}, inplace=True)
    df["price"] = df["price"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


def calculate_delta_volume(symbol: str, interval: str = "15m", limit: int = 50) -> pd.DataFrame:
    """Delta volume (buy vol - sell vol) per candle.
    Uses taker_buy_volume from klines data.
    Delta > 0 = net buying, Delta < 0 = net selling.
    """
    df = get_klines(symbol, interval, limit)
    df["sell_volume"] = df["volume"] - df["taker_buy_volume"]
    df["delta"] = df["taker_buy_volume"] - df["sell_volume"]
    df["delta_pct"] = (df["delta"] / df["volume"] * 100).round(2)
    df["cumulative_delta"] = df["delta"].cumsum()
    return df[["open_time", "close", "volume", "taker_buy_volume", "sell_volume",
               "delta", "delta_pct", "cumulative_delta"]]


def get_funding_rate(symbol: str) -> dict:
    """Current funding rate (futures) — market sentiment indicator."""
    client = get_client()
    try:
        funding = client.futures_funding_rate(symbol=symbol, limit=1)
        if funding:
            rate = float(funding[-1]["fundingRate"])
            return {
                "symbol": symbol,
                "funding_rate": rate,
                "funding_pct": round(rate * 100, 4),
                "sentiment": "bearish" if rate > 0.01 else "bullish" if rate < -0.01 else "neutral",
            }
    except Exception:
        pass
    return {"symbol": symbol, "funding_rate": None, "sentiment": "unavailable"}


def detect_absorption(symbol: str, interval: str = "15m", lookback: int = 20, threshold: float = 3.0) -> dict:
    """Detect large limit orders absorbing market orders.
    High volume candle with small body = absorption.
    """
    df = get_klines(symbol, interval, lookback + 10)
    df["body"] = abs(df["close"] - df["open"])
    df["range"] = df["high"] - df["low"]
    df["body_ratio"] = df["body"] / df["range"].replace(0, np.nan)

    avg_vol = df["volume"].rolling(lookback).mean()
    df["vol_ratio"] = df["volume"] / avg_vol

    # Absorption: high volume + small body relative to range
    last = df.iloc[-1]
    absorptions = df[
        (df["vol_ratio"] > threshold) & (df["body_ratio"] < 0.3)
    ].tail(5)

    return {
        "symbol": symbol,
        "current_vol_ratio": round(float(last["vol_ratio"]) if pd.notna(last["vol_ratio"]) else 0, 2),
        "current_body_ratio": round(float(last["body_ratio"]) if pd.notna(last["body_ratio"]) else 0, 2),
        "absorptions_detected": len(absorptions),
        "absorption_candles": absorptions[["open_time", "close", "volume", "vol_ratio", "body_ratio"]].to_dict("records") if len(absorptions) > 0 else [],
    }
