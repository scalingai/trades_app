"""
Volume Profile Strategy — VPOC rejection, Value Area extremes, Volume anomalies.
"""
from strategies.base import Strategy, Signal


class VolumeProfileStrategy(Strategy):
    name = "volume_profile"
    param_grid = {
        "profile_periods": [50, 100, 200],
        "value_area_pct": [0.68, 0.70, 0.80],
        "vpoc_rejection_candles": [3, 5, 10],
        "volume_anomaly_multiplier": [1.5, 2.0, 3.0],
    }

    def evaluate(self, snapshot: dict, params: dict) -> Signal:
        symbol = snapshot["symbol"]
        vid = self.variant_id(params)

        score = 0
        direction = "neutral"
        factors = {}
        current_price = snapshot.get("current_price", 0)

        # --- Factor 1: Value Area position (30 pts) ---
        va_data = snapshot.get("value_area", {})
        vah = va_data.get("vah")
        val = va_data.get("val")
        position = va_data.get("position", "unknown")

        if position == "below_val" and val:
            score += 30
            direction = "long"
            factors["value_area"] = f"below_VAL ({val})"
        elif position == "above_vah" and vah:
            score += 30
            direction = "short"
            factors["value_area"] = f"above_VAH ({vah})"
        elif position == "inside_va":
            score += 5
            factors["value_area"] = "inside"

        # --- Factor 2: VPOC rejection (25 pts) ---
        vpoc_data = snapshot.get("vpoc", {})
        vpoc_price = vpoc_data.get("vpoc_price")
        distance_pct = abs(vpoc_data.get("distance_to_vpoc_pct", 999))

        if vpoc_price and distance_pct < 0.3:  # Within 0.3% of VPOC
            score += 25
            factors["vpoc"] = f"near_VPOC ({vpoc_price}, dist={round(distance_pct, 3)}%)"

        # --- Factor 3: Volume anomaly (25 pts) ---
        klines = snapshot.get("klines", [])
        if klines:
            volumes = [k.get("volume", 0) for k in klines[-30:]]
            if volumes:
                avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
                current_vol = volumes[-1]
                multiplier = params["volume_anomaly_multiplier"]

                if avg_vol > 0 and current_vol > avg_vol * multiplier:
                    score += 25
                    factors["volume_anomaly"] = f"{round(current_vol / avg_vol, 1)}x average"

        # --- Factor 4: Session context (10 pts) ---
        is_key_session = snapshot.get("is_key_session", False)
        if is_key_session:
            score += 10
            factors["session"] = snapshot.get("current_session", "key_session")

        # --- Factor 5: EMA alignment (10 pts) ---
        ema_data = snapshot.get("emas", {})
        ema_20 = ema_data.get("ema_20", {}).get("distance_pct", 0)

        if ema_20 < -2 and direction == "long":  # Price 2%+ below EMA20
            score += 10
            factors["ema_overext"] = f"oversold ({round(ema_20, 2)}% below EMA20)"
        elif ema_20 > 2 and direction == "short":
            score += 10
            factors["ema_overext"] = f"overbought ({round(ema_20, 2)}% above EMA20)"

        confidence = min(score, 100)

        if score < 30:
            direction = "neutral"

        entry = stop = target = rr = None
        if direction == "long" and score >= 55:
            entry = current_price
            stop_level = val if val else entry * 0.985
            stop = float(stop_level) * 0.998
            target = vpoc_price if vpoc_price and vpoc_price > entry else entry * 1.03
            rr = (target - entry) / (entry - stop) if entry > stop else 0
        elif direction == "short" and score >= 55:
            entry = current_price
            stop_level = vah if vah else entry * 1.015
            stop = float(stop_level) * 1.002
            target = vpoc_price if vpoc_price and vpoc_price < entry else entry * 0.97
            rr = (entry - target) / (stop - entry) if stop > entry else 0

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
            rr=round(rr, 2) if rr else None,
            factors_active=factors,
        )
