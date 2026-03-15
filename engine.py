"""
Strategy Engine — Orchestrates data collection, runs all strategy variants,
calculates consensus, and determines if Opus should be consulted.
"""
from datetime import datetime, timezone

from config import (
    WATCHLIST, TIMEFRAMES, KEY_SESSIONS,
    CONSENSUS_MIN_PCT, CONSENSUS_MIN_AVG_SCORE,
)
from strategies.base import Signal
from strategies.ict_pure import ICTPureStrategy
from strategies.order_flow_strategy import OrderFlowStrategy
from strategies.volume_profile_strategy import VolumeProfileStrategy
from strategies.hybrid import HybridStrategy

from tools import market_data, order_flow, volume_profile, technical, liquidations, smart_money


ALL_STRATEGIES = [
    ICTPureStrategy(),
    OrderFlowStrategy(),
    VolumeProfileStrategy(),
    HybridStrategy(),
]


def _is_key_session() -> tuple[bool, str]:
    """Check if current time is during a key trading session."""
    now = datetime.now(timezone.utc)
    current_time = now.strftime("%H:%M")

    for session_name, times in KEY_SESSIONS.items():
        if times["start"] <= current_time <= times["end"]:
            return True, session_name
    return False, "off_session"


def collect_snapshot(symbol: str) -> dict:
    """Collect all market data for a symbol into a single snapshot dict.
    This is called ONCE per cycle per symbol — all strategies read from it.
    """
    snapshot = {"symbol": symbol, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Current price
    try:
        price_data = market_data.get_price(symbol)
        snapshot["current_price"] = price_data["price"]
        snapshot["price_data"] = price_data
    except Exception as e:
        snapshot["current_price"] = 0
        snapshot["errors"] = snapshot.get("errors", []) + [f"price: {e}"]

    # Klines for multiple timeframes
    for tf in TIMEFRAMES:
        try:
            klines_df = market_data.get_klines(symbol, tf, 200)
            snapshot[f"klines_{tf}"] = klines_df
            # Also store as list of dicts for strategies that need it
            if tf == "15m":
                snapshot["klines"] = klines_df.to_dict("records")
        except Exception as e:
            snapshot["errors"] = snapshot.get("errors", []) + [f"klines_{tf}: {e}"]

    # Order flow
    try:
        snapshot["order_book"] = order_flow.get_order_book(symbol)
    except Exception as e:
        snapshot["order_book"] = {}
        snapshot["errors"] = snapshot.get("errors", []) + [f"order_book: {e}"]

    try:
        delta_df = order_flow.calculate_delta_volume(symbol, "15m", 50)
        snapshot["delta_volume"] = {
            "deltas": delta_df["delta"].tolist(),
            "cumulative": float(delta_df["cumulative_delta"].iloc[-1]),
            "last_delta_pct": float(delta_df["delta_pct"].iloc[-1]),
        }
    except Exception as e:
        snapshot["delta_volume"] = {}
        snapshot["errors"] = snapshot.get("errors", []) + [f"delta: {e}"]

    try:
        snapshot["funding_rate"] = order_flow.get_funding_rate(symbol)
    except Exception as e:
        snapshot["funding_rate"] = {}

    try:
        snapshot["absorption"] = order_flow.detect_absorption(symbol)
    except Exception as e:
        snapshot["absorption"] = {}

    # Smart Money Concepts (for each timeframe)
    for tf in TIMEFRAMES:
        try:
            snapshot[f"fvg_{tf}"] = smart_money.detect_fvg(symbol, tf)
        except Exception:
            snapshot[f"fvg_{tf}"] = {}

        try:
            snapshot[f"ob_{tf}"] = smart_money.detect_order_blocks(symbol, tf)
        except Exception:
            snapshot[f"ob_{tf}"] = {}

        try:
            snapshot[f"sweep_{tf}"] = smart_money.detect_liquidity_sweeps(symbol, tf)
        except Exception:
            snapshot[f"sweep_{tf}"] = {}

        try:
            snapshot[f"bos_{tf}"] = smart_money.detect_bos_choch(symbol, tf)
        except Exception:
            snapshot[f"bos_{tf}"] = {}

    # Volume Profile
    try:
        snapshot["vpoc"] = volume_profile.get_vpoc(symbol)
    except Exception:
        snapshot["vpoc"] = {}

    try:
        snapshot["value_area"] = volume_profile.get_value_area(symbol)
    except Exception:
        snapshot["value_area"] = {}

    # Technical indicators
    try:
        snapshot["emas"] = technical.get_ema(symbol).get("emas", {})
    except Exception:
        snapshot["emas"] = {}

    try:
        snapshot["rsi"] = technical.get_rsi(symbol)
    except Exception:
        snapshot["rsi"] = {}

    try:
        snapshot["rsi_divergence"] = technical.detect_rsi_divergence(symbol)
    except Exception:
        snapshot["rsi_divergence"] = {}

    try:
        snapshot["vwap"] = technical.get_vwap(symbol)
    except Exception:
        snapshot["vwap"] = {}

    try:
        snapshot["ta_summary"] = technical.get_ta_summary(symbol)
    except Exception:
        snapshot["ta_summary"] = {}

    # Liquidations (Coinglass)
    try:
        snapshot["liquidations"] = liquidations.get_liquidations(symbol)
    except Exception:
        snapshot["liquidations"] = {"available": False}

    # Session context
    is_key, session_name = _is_key_session()
    snapshot["is_key_session"] = is_key
    snapshot["current_session"] = session_name

    return snapshot


def run_all_strategies(snapshot: dict) -> list[Signal]:
    """Run all strategy variants against the snapshot."""
    all_signals = []
    for strategy in ALL_STRATEGIES:
        signals = strategy.run_all_variants(snapshot)
        all_signals.extend(signals)
    return all_signals


def calculate_consensus(signals: list[Signal]) -> dict:
    """Calculate consensus across all strategy variants.

    Returns consensus info + whether to escalate to Opus.
    """
    if not signals:
        return {"escalate": False, "reason": "no_signals"}

    # Count directions
    longs = [s for s in signals if s.direction == "long"]
    shorts = [s for s in signals if s.direction == "short"]
    neutrals = [s for s in signals if s.direction == "neutral"]
    total = len(signals)

    long_pct = len(longs) / total
    short_pct = len(shorts) / total

    # Average scores for non-neutral signals
    long_avg_score = sum(s.score for s in longs) / len(longs) if longs else 0
    short_avg_score = sum(s.score for s in shorts) / len(shorts) if shorts else 0

    # Determine dominant direction
    if long_pct > short_pct and long_pct >= CONSENSUS_MIN_PCT:
        dominant = "long"
        dominant_pct = long_pct
        dominant_avg = long_avg_score
        dominant_signals = longs
    elif short_pct > long_pct and short_pct >= CONSENSUS_MIN_PCT:
        dominant = "short"
        dominant_pct = short_pct
        dominant_avg = short_avg_score
        dominant_signals = shorts
    else:
        dominant = "neutral"
        dominant_pct = 0
        dominant_avg = 0
        dominant_signals = []

    # Top signals (highest scores)
    top_signals = sorted(signals, key=lambda s: s.score, reverse=True)[:5]

    # Should we escalate to Opus?
    escalate = (
        dominant in ("long", "short")
        and dominant_pct >= CONSENSUS_MIN_PCT
        and dominant_avg >= CONSENSUS_MIN_AVG_SCORE
    )

    return {
        "dominant_direction": dominant,
        "consensus_pct": round(dominant_pct * 100, 1),
        "avg_score": round(dominant_avg, 1),
        "total_variants": total,
        "longs": len(longs),
        "shorts": len(shorts),
        "neutrals": len(neutrals),
        "long_avg_score": round(long_avg_score, 1),
        "short_avg_score": round(short_avg_score, 1),
        "top_signals": [s.to_dict() for s in top_signals],
        "escalate": escalate,
        "reason": f"consensus={round(dominant_pct * 100)}% avg_score={round(dominant_avg)}" if escalate else "below_threshold",
    }


def scan_symbol(symbol: str) -> dict:
    """Full scan of a single symbol: collect data → run strategies → consensus."""
    snapshot = collect_snapshot(symbol)
    signals = run_all_strategies(snapshot)
    consensus = calculate_consensus(signals)

    return {
        "symbol": symbol,
        "timestamp": snapshot["timestamp"],
        "current_price": snapshot.get("current_price"),
        "session": snapshot.get("current_session"),
        "consensus": consensus,
        "errors": snapshot.get("errors", []),
    }


def scan_all() -> list[dict]:
    """Scan all symbols in watchlist."""
    results = []
    for symbol in WATCHLIST:
        result = scan_symbol(symbol)
        results.append(result)
    return results
