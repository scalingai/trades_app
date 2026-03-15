"""
Volume Profile analysis — VPOC, Value Area High/Low.
Pure numpy implementation, no external dependencies.
"""
import numpy as np
import pandas as pd
from tools.market_data import get_klines


def get_volume_profile(symbol: str, interval: str = "15m", periods: int = 100, bins: int = 50) -> dict:
    """Volume distribution by price level.

    Returns histogram of volume at each price bin.
    """
    df = get_klines(symbol, interval, periods)

    prices = df["close"].values
    volumes = df["volume"].values
    highs = df["high"].values
    lows = df["low"].values

    price_min = float(lows.min())
    price_max = float(highs.max())
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    vol_profile = np.zeros(bins)

    # Distribute each candle's volume across its price range
    for i in range(len(df)):
        candle_low = lows[i]
        candle_high = highs[i]
        candle_vol = volumes[i]

        # Find bins that overlap with this candle's range
        for j in range(bins):
            bin_low = bin_edges[j]
            bin_high = bin_edges[j + 1]
            if bin_high >= candle_low and bin_low <= candle_high:
                # Proportional volume allocation
                overlap = min(candle_high, bin_high) - max(candle_low, bin_low)
                candle_range = candle_high - candle_low
                if candle_range > 0:
                    vol_profile[j] += candle_vol * (overlap / candle_range)

    profile_data = [
        {"price": round(float(bin_centers[i]), 2), "volume": round(float(vol_profile[i]), 2)}
        for i in range(bins)
    ]

    return {
        "symbol": symbol,
        "interval": interval,
        "periods": periods,
        "price_range": {"min": round(price_min, 2), "max": round(price_max, 2)},
        "profile": profile_data,
    }


def get_vpoc(symbol: str, interval: str = "15m", periods: int = 100) -> dict:
    """Point of Control — price level with highest volume."""
    profile = get_volume_profile(symbol, interval, periods)
    if not profile["profile"]:
        return {"symbol": symbol, "vpoc": None}

    max_entry = max(profile["profile"], key=lambda x: x["volume"])
    current_price = get_klines(symbol, interval, 1).iloc[-1]["close"]

    return {
        "symbol": symbol,
        "vpoc_price": max_entry["price"],
        "vpoc_volume": max_entry["volume"],
        "current_price": float(current_price),
        "distance_to_vpoc_pct": round((float(current_price) - max_entry["price"]) / max_entry["price"] * 100, 4),
    }


def get_value_area(symbol: str, interval: str = "15m", periods: int = 100, pct: float = 0.70) -> dict:
    """Value Area — price range containing X% of total volume.

    VAH = Value Area High, VAL = Value Area Low.
    """
    profile = get_volume_profile(symbol, interval, periods)
    if not profile["profile"]:
        return {"symbol": symbol, "vah": None, "val": None}

    entries = sorted(profile["profile"], key=lambda x: x["volume"], reverse=True)
    total_vol = sum(e["volume"] for e in entries)
    target_vol = total_vol * pct

    accumulated = 0
    selected_prices = []
    for entry in entries:
        accumulated += entry["volume"]
        selected_prices.append(entry["price"])
        if accumulated >= target_vol:
            break

    vah = max(selected_prices)
    val = min(selected_prices)
    vpoc = entries[0]["price"]
    current_price = float(get_klines(symbol, interval, 1).iloc[-1]["close"])

    position = "above_vah" if current_price > vah else "below_val" if current_price < val else "inside_va"

    return {
        "symbol": symbol,
        "vah": round(vah, 2),
        "val": round(val, 2),
        "vpoc": round(vpoc, 2),
        "value_area_pct": pct,
        "current_price": round(current_price, 2),
        "position": position,
    }
