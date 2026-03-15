"""
ICT Pure Strategy — Fair Value Gaps, Order Blocks, Liquidity Sweeps, BOS/CHoCH.
"""
from strategies.base import Strategy, Signal


class ICTPureStrategy(Strategy):
    name = "ict_pure"
    param_grid = {
        "fvg_timeframe": ["5m", "15m", "1h"],
        "ob_lookback": [20, 50],
        "swing_length": [5, 10, 20],
        "require_bos": [True, False],
        "require_sweep_before_entry": [True, False],
    }

    def evaluate(self, snapshot: dict, params: dict) -> Signal:
        symbol = snapshot["symbol"]
        vid = self.variant_id(params)
        tf = params["fvg_timeframe"]

        score = 0
        confidence = 0
        direction = "neutral"
        factors = {}

        # Get data for this timeframe
        fvg_data = snapshot.get(f"fvg_{tf}", {})
        ob_data = snapshot.get(f"ob_{tf}", {})
        sweep_data = snapshot.get(f"sweep_{tf}", {})
        bos_data = snapshot.get(f"bos_{tf}", {})
        current_price = snapshot.get("current_price", 0)

        # --- Factor 1: FVG (25 pts) ---
        bullish_fvgs = fvg_data.get("bullish_fvgs", [])
        bearish_fvgs = fvg_data.get("bearish_fvgs", [])

        fvg_near_bullish = any(
            f["bottom"] <= current_price <= f["top"] * 1.005
            for f in bullish_fvgs
        )
        fvg_near_bearish = any(
            f["bottom"] * 0.995 <= current_price <= f["top"]
            for f in bearish_fvgs
        )

        if fvg_near_bullish:
            score += 25
            factors["fvg"] = "bullish_nearby"
            direction = "long"
        elif fvg_near_bearish:
            score += 25
            factors["fvg"] = "bearish_nearby"
            direction = "short"

        # --- Factor 2: Order Block (25 pts) ---
        bullish_obs = ob_data.get("bullish_obs", [])
        bearish_obs = ob_data.get("bearish_obs", [])

        ob_bullish = any(
            o["bottom"] <= current_price <= o["top"] * 1.002
            for o in bullish_obs
        )
        ob_bearish = any(
            o["bottom"] * 0.998 <= current_price <= o["top"]
            for o in bearish_obs
        )

        if ob_bullish and direction in ("long", "neutral"):
            score += 25
            factors["order_block"] = "bullish"
            direction = "long"
        elif ob_bearish and direction in ("short", "neutral"):
            score += 25
            factors["order_block"] = "bearish"
            direction = "short"

        # --- Factor 3: Liquidity Sweep (20 pts) ---
        sweeps = sweep_data.get("sweeps", [])
        recent_bullish_sweep = any(s["type"] == "bullish_sweep" for s in sweeps[-3:])
        recent_bearish_sweep = any(s["type"] == "bearish_sweep" for s in sweeps[-3:])

        if recent_bullish_sweep and direction == "long":
            score += 20
            factors["liquidity_sweep"] = "bullish_confirmed"
        elif recent_bearish_sweep and direction == "short":
            score += 20
            factors["liquidity_sweep"] = "bearish_confirmed"

        if params["require_sweep_before_entry"] and not (recent_bullish_sweep or recent_bearish_sweep):
            score = min(score, 40)  # Cap score if sweep required but not found

        # --- Factor 4: BOS/CHoCH (15 pts) ---
        events = bos_data.get("events", [])
        trend = bos_data.get("trend", "undefined")

        has_bos = any("BOS" in e.get("type", "") for e in events[-3:])
        has_choch = any("CHoCH" in e.get("type", "") for e in events[-3:])

        if has_bos and trend == "bullish" and direction == "long":
            score += 15
            factors["structure"] = "BOS_bullish"
        elif has_bos and trend == "bearish" and direction == "short":
            score += 15
            factors["structure"] = "BOS_bearish"
        elif has_choch:
            score += 10
            factors["structure"] = "CHoCH_reversal"

        if params["require_bos"] and not has_bos:
            score = min(score, 50)

        # --- Factor 5: Trend alignment (15 pts) ---
        if (trend == "bullish" and direction == "long") or (trend == "bearish" and direction == "short"):
            score += 15
            factors["trend"] = trend

        # Calculate confidence
        max_possible = 100
        confidence = min(score / max_possible * 100, 100)

        # Reset to neutral if score too low
        if score < 30:
            direction = "neutral"

        # Entry/Stop/Target estimation
        entry = stop = target = rr = None
        if direction == "long" and score >= 55:
            entry = current_price
            # Stop below nearest OB or swing low
            stop = entry * 0.99  # 1% default stop
            target = entry + (entry - stop) * 2  # 1:2 RR
            rr = 2.0
        elif direction == "short" and score >= 55:
            entry = current_price
            stop = entry * 1.01
            target = entry - (stop - entry) * 2
            rr = 2.0

        return Signal(
            strategy_name=self.name,
            variant_id=vid,
            symbol=symbol,
            direction=direction,
            score=score,
            confidence=round(confidence, 1),
            entry=round(entry, 2) if entry else None,
            stop=round(stop, 2) if stop else None,
            target=round(target, 2) if target else None,
            rr=rr,
            factors_active=factors,
        )
