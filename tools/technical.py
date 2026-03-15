"""
Technical indicators via tradingview-ta and local calculations.
RSI, EMA, VWAP, MACD, and more.
"""
import numpy as np
import pandas as pd
from tradingview_ta import TA_Handler, Interval, Exchange
from tools.market_data import get_klines


INTERVAL_MAP = {
    "1m": Interval.INTERVAL_1_MINUTE,
    "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR,
    "4h": Interval.INTERVAL_4_HOURS,
    "1d": Interval.INTERVAL_1_DAY,
}


def _symbol_for_ta(symbol: str) -> str:
    """Convert BTCUSDT to BTCUSDT.P for futures or keep as-is."""
    return symbol


def get_ta_summary(symbol: str, interval: str = "15m") -> dict:
    """Full technical analysis summary from TradingView."""
    try:
        handler = TA_Handler(
            symbol=_symbol_for_ta(symbol),
            screener="crypto",
            exchange="BINANCE",
            interval=INTERVAL_MAP.get(interval, Interval.INTERVAL_15_MINUTES),
        )
        analysis = handler.get_analysis()
        return {
            "symbol": symbol,
            "interval": interval,
            "summary": {
                "recommendation": analysis.summary["RECOMMENDATION"],
                "buy": analysis.summary["BUY"],
                "sell": analysis.summary["SELL"],
                "neutral": analysis.summary["NEUTRAL"],
            },
            "oscillators": {
                "recommendation": analysis.oscillators["RECOMMENDATION"],
                "buy": analysis.oscillators["BUY"],
                "sell": analysis.oscillators["SELL"],
                "neutral": analysis.oscillators["NEUTRAL"],
            },
            "moving_averages": {
                "recommendation": analysis.moving_averages["RECOMMENDATION"],
                "buy": analysis.moving_averages["BUY"],
                "sell": analysis.moving_averages["SELL"],
                "neutral": analysis.moving_averages["NEUTRAL"],
            },
            "indicators": analysis.indicators,
            "available": True,
        }
    except Exception as e:
        return {"symbol": symbol, "interval": interval, "error": str(e), "available": False}


def get_rsi(symbol: str, interval: str = "15m", period: int = 14) -> dict:
    """RSI calculated from klines data."""
    df = get_klines(symbol, interval, period + 50)
    closes = df["close"].values

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = pd.Series(gains).rolling(period).mean().values
    avg_loss = pd.Series(losses).rolling(period).mean().values

    rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))

    current_rsi = float(rsi[-1]) if not np.isnan(rsi[-1]) else None
    prev_rsi = float(rsi[-2]) if len(rsi) > 1 and not np.isnan(rsi[-2]) else None

    condition = "overbought" if current_rsi and current_rsi > 70 else "oversold" if current_rsi and current_rsi < 30 else "neutral"

    return {
        "symbol": symbol,
        "rsi": round(current_rsi, 2) if current_rsi else None,
        "prev_rsi": round(prev_rsi, 2) if prev_rsi else None,
        "condition": condition,
    }


def get_ema(symbol: str, interval: str = "15m", periods: list = None) -> dict:
    """EMA values for multiple periods."""
    if periods is None:
        periods = [9, 20, 50, 200]

    df = get_klines(symbol, interval, max(periods) + 50)
    current_price = float(df.iloc[-1]["close"])

    emas = {}
    for p in periods:
        ema = df["close"].ewm(span=p, adjust=False).mean()
        ema_val = float(ema.iloc[-1])
        emas[f"ema_{p}"] = {
            "value": round(ema_val, 2),
            "distance_pct": round((current_price - ema_val) / ema_val * 100, 4),
        }

    return {
        "symbol": symbol,
        "current_price": round(current_price, 2),
        "emas": emas,
    }


def detect_rsi_divergence(symbol: str, interval: str = "15m", lookback: int = 30) -> dict:
    """Detect RSI divergence (price vs RSI direction mismatch).

    Bullish divergence: price makes lower low, RSI makes higher low.
    Bearish divergence: price makes higher high, RSI makes lower high.
    """
    df = get_klines(symbol, interval, lookback + 50)
    closes = df["close"].values

    # Calculate RSI series
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = pd.Series(gains).rolling(14).mean().values
    avg_loss = pd.Series(losses).rolling(14).mean().values
    rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))

    # Find recent swing lows/highs in price and RSI
    n = min(lookback, len(closes) - 1, len(rsi))
    price_slice = closes[-n:]
    rsi_slice = rsi[-n:]

    divergences = []

    # Simple check: compare first half vs second half
    mid = n // 2
    if mid < 3:
        return {"symbol": symbol, "divergences": [], "has_bullish_div": False, "has_bearish_div": False}

    first_price_low = float(np.min(price_slice[:mid]))
    second_price_low = float(np.min(price_slice[mid:]))
    first_rsi_at_low = float(rsi_slice[np.argmin(price_slice[:mid])])
    second_rsi_at_low = float(rsi_slice[mid + np.argmin(price_slice[mid:])])

    # Bullish divergence
    if second_price_low < first_price_low and second_rsi_at_low > first_rsi_at_low:
        divergences.append({
            "type": "bullish",
            "price_low_1": round(first_price_low, 2),
            "price_low_2": round(second_price_low, 2),
            "rsi_low_1": round(first_rsi_at_low, 2),
            "rsi_low_2": round(second_rsi_at_low, 2),
        })

    first_price_high = float(np.max(price_slice[:mid]))
    second_price_high = float(np.max(price_slice[mid:]))
    first_rsi_at_high = float(rsi_slice[np.argmax(price_slice[:mid])])
    second_rsi_at_high = float(rsi_slice[mid + np.argmax(price_slice[mid:])])

    # Bearish divergence
    if second_price_high > first_price_high and second_rsi_at_high < first_rsi_at_high:
        divergences.append({
            "type": "bearish",
            "price_high_1": round(first_price_high, 2),
            "price_high_2": round(second_price_high, 2),
            "rsi_high_1": round(first_rsi_at_high, 2),
            "rsi_high_2": round(second_rsi_at_high, 2),
        })

    return {
        "symbol": symbol,
        "divergences": divergences,
        "has_bullish_div": any(d["type"] == "bullish" for d in divergences),
        "has_bearish_div": any(d["type"] == "bearish" for d in divergences),
    }


def get_vwap(symbol: str, interval: str = "15m", periods: int = 50) -> dict:
    """Calculate VWAP (Volume Weighted Average Price)."""
    df = get_klines(symbol, interval, periods)

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    vwap = cumulative_tp_vol / cumulative_vol

    current_price = float(df.iloc[-1]["close"])
    current_vwap = float(vwap.iloc[-1])

    return {
        "symbol": symbol,
        "vwap": round(current_vwap, 2),
        "current_price": round(current_price, 2),
        "distance_pct": round((current_price - current_vwap) / current_vwap * 100, 4),
        "position": "above" if current_price > current_vwap else "below",
    }
