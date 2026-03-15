"""
ICT / Smart Money Concepts — implementación propia.
Fair Value Gaps (FVG), Order Blocks (OB), Liquidity Sweeps,
Break of Structure (BOS), Change of Character (CHoCH), Swing Levels.
"""
import pandas as pd
import numpy as np
from tools.market_data import get_klines


def _ensure_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Get klines and ensure proper column names."""
    df = get_klines(symbol, interval, limit)
    return df


def get_swing_levels(symbol: str, interval: str = "15m", swing_length: int = 10) -> dict:
    """Detect swing highs and swing lows."""
    df = _ensure_klines(symbol, interval)
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_highs = []
    swing_lows = []

    for i in range(swing_length, n - swing_length):
        # Swing high: highest in window
        if highs[i] == max(highs[i - swing_length:i + swing_length + 1]):
            swing_highs.append({
                "index": i,
                "time": str(df.iloc[i]["open_time"]),
                "price": float(highs[i]),
            })
        # Swing low: lowest in window
        if lows[i] == min(lows[i - swing_length:i + swing_length + 1]):
            swing_lows.append({
                "index": i,
                "time": str(df.iloc[i]["open_time"]),
                "price": float(lows[i]),
            })

    return {
        "symbol": symbol,
        "interval": interval,
        "swing_highs": swing_highs[-10:],  # Last 10
        "swing_lows": swing_lows[-10:],
    }


def detect_fvg(symbol: str, interval: str = "15m", min_gap_pct: float = 0.05) -> dict:
    """Detect Fair Value Gaps (3-candle imbalance pattern).

    Bullish FVG: candle[i].low > candle[i-2].high (gap up)
    Bearish FVG: candle[i].high < candle[i-2].low (gap down)
    """
    df = _ensure_klines(symbol, interval)
    bullish_fvgs = []
    bearish_fvgs = []

    for i in range(2, len(df)):
        c0 = df.iloc[i - 2]  # First candle
        c2 = df.iloc[i]      # Third candle

        # Bullish FVG: gap between c0.high and c2.low
        if c2["low"] > c0["high"]:
            gap_pct = (c2["low"] - c0["high"]) / c0["high"] * 100
            if gap_pct >= min_gap_pct:
                bullish_fvgs.append({
                    "time": str(df.iloc[i - 1]["open_time"]),
                    "top": float(c2["low"]),
                    "bottom": float(c0["high"]),
                    "gap_pct": round(gap_pct, 4),
                    "mitigated": float(df.iloc[-1]["low"]) <= float(c2["low"]),
                })

        # Bearish FVG: gap between c2.high and c0.low
        if c2["high"] < c0["low"]:
            gap_pct = (c0["low"] - c2["high"]) / c0["low"] * 100
            if gap_pct >= min_gap_pct:
                bearish_fvgs.append({
                    "time": str(df.iloc[i - 1]["open_time"]),
                    "top": float(c0["low"]),
                    "bottom": float(c2["high"]),
                    "gap_pct": round(gap_pct, 4),
                    "mitigated": float(df.iloc[-1]["high"]) >= float(c0["low"]),
                })

    return {
        "symbol": symbol,
        "interval": interval,
        "bullish_fvgs": [f for f in bullish_fvgs if not f["mitigated"]][-5:],
        "bearish_fvgs": [f for f in bearish_fvgs if not f["mitigated"]][-5:],
        "total_active_bullish": len([f for f in bullish_fvgs if not f["mitigated"]]),
        "total_active_bearish": len([f for f in bearish_fvgs if not f["mitigated"]]),
    }


def detect_order_blocks(symbol: str, interval: str = "15m", lookback: int = 50) -> dict:
    """Detect Order Blocks.

    Bullish OB: Last bearish candle before a strong bullish move.
    Bearish OB: Last bullish candle before a strong bearish move.
    """
    df = _ensure_klines(symbol, interval, lookback + 20)
    bullish_obs = []
    bearish_obs = []

    closes = df["close"].values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values

    avg_body = np.mean(np.abs(closes - opens))

    for i in range(1, len(df) - 1):
        current_body = abs(closes[i] - opens[i])
        prev_body = abs(closes[i - 1] - opens[i - 1])

        # Strong bullish move (>2x average body)
        if closes[i] > opens[i] and current_body > avg_body * 2:
            # Previous candle was bearish = bullish OB
            if closes[i - 1] < opens[i - 1]:
                current_price = closes[-1]
                ob_top = float(opens[i - 1])
                ob_bottom = float(closes[i - 1])
                # OB is relevant if price is above it (support zone)
                if current_price >= ob_bottom:
                    bullish_obs.append({
                        "time": str(df.iloc[i - 1]["open_time"]),
                        "top": ob_top,
                        "bottom": ob_bottom,
                        "strength": round(current_body / avg_body, 2),
                        "volume": float(df.iloc[i - 1]["volume"]),
                    })

        # Strong bearish move
        if closes[i] < opens[i] and current_body > avg_body * 2:
            # Previous candle was bullish = bearish OB
            if closes[i - 1] > opens[i - 1]:
                current_price = closes[-1]
                ob_top = float(closes[i - 1])
                ob_bottom = float(opens[i - 1])
                if current_price <= ob_top:
                    bearish_obs.append({
                        "time": str(df.iloc[i - 1]["open_time"]),
                        "top": ob_top,
                        "bottom": ob_bottom,
                        "strength": round(current_body / avg_body, 2),
                        "volume": float(df.iloc[i - 1]["volume"]),
                    })

    return {
        "symbol": symbol,
        "interval": interval,
        "bullish_obs": bullish_obs[-5:],
        "bearish_obs": bearish_obs[-5:],
    }


def detect_liquidity_sweeps(symbol: str, interval: str = "15m", swing_length: int = 10) -> dict:
    """Detect liquidity sweeps — price wicks through swing level then closes back.

    Bullish sweep: price wicks below swing low but closes above it.
    Bearish sweep: price wicks above swing high but closes below it.
    """
    df = _ensure_klines(symbol, interval)
    swings = get_swing_levels(symbol, interval, swing_length)

    sweeps = []

    # Check last 20 candles for sweeps of known swing levels
    for i in range(max(0, len(df) - 20), len(df)):
        candle = df.iloc[i]

        # Check bearish sweeps (wick above swing high, close below)
        for sh in swings["swing_highs"]:
            if sh["index"] < i and candle["high"] > sh["price"] and candle["close"] < sh["price"]:
                sweeps.append({
                    "type": "bearish_sweep",
                    "time": str(candle["open_time"]),
                    "sweep_level": sh["price"],
                    "wick_high": float(candle["high"]),
                    "close": float(candle["close"]),
                })

        # Check bullish sweeps (wick below swing low, close above)
        for sl in swings["swing_lows"]:
            if sl["index"] < i and candle["low"] < sl["price"] and candle["close"] > sl["price"]:
                sweeps.append({
                    "type": "bullish_sweep",
                    "time": str(candle["open_time"]),
                    "sweep_level": sl["price"],
                    "wick_low": float(candle["low"]),
                    "close": float(candle["close"]),
                })

    return {
        "symbol": symbol,
        "interval": interval,
        "sweeps": sweeps[-10:],
        "recent_bullish_sweeps": len([s for s in sweeps if s["type"] == "bullish_sweep"]),
        "recent_bearish_sweeps": len([s for s in sweeps if s["type"] == "bearish_sweep"]),
    }


def detect_bos_choch(symbol: str, interval: str = "15m", swing_length: int = 10) -> dict:
    """Detect Break of Structure (BOS) and Change of Character (CHoCH).

    BOS: Price breaks a swing level in the direction of the trend (continuation).
    CHoCH: Price breaks a swing level against the trend (reversal signal).
    """
    df = _ensure_klines(symbol, interval)
    swings = get_swing_levels(symbol, interval, swing_length)

    events = []
    sh_list = swings["swing_highs"]
    sl_list = swings["swing_lows"]

    if len(sh_list) < 2 or len(sl_list) < 2:
        return {"symbol": symbol, "interval": interval, "events": [], "trend": "undefined"}

    # Determine trend: higher highs + higher lows = bullish
    last_highs = [h["price"] for h in sh_list[-3:]]
    last_lows = [l["price"] for l in sl_list[-3:]]

    uptrend = len(last_highs) >= 2 and last_highs[-1] > last_highs[-2]
    downtrend = len(last_lows) >= 2 and last_lows[-1] < last_lows[-2]

    current_price = float(df.iloc[-1]["close"])

    # Check last candles for structure breaks
    for i in range(max(0, len(df) - 10), len(df)):
        candle = df.iloc[i]

        # Break above swing high
        for sh in sh_list[-5:]:
            if sh["index"] < i and float(candle["close"]) > sh["price"]:
                event_type = "BOS_bullish" if uptrend else "CHoCH_bullish"
                events.append({
                    "type": event_type,
                    "time": str(candle["open_time"]),
                    "broken_level": sh["price"],
                    "close": float(candle["close"]),
                })

        # Break below swing low
        for sl in sl_list[-5:]:
            if sl["index"] < i and float(candle["close"]) < sl["price"]:
                event_type = "BOS_bearish" if downtrend else "CHoCH_bearish"
                events.append({
                    "type": event_type,
                    "time": str(candle["open_time"]),
                    "broken_level": sl["price"],
                    "close": float(candle["close"]),
                })

    trend = "bullish" if uptrend else "bearish" if downtrend else "ranging"

    return {
        "symbol": symbol,
        "interval": interval,
        "trend": trend,
        "events": events[-10:],
    }
