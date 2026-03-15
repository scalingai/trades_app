"""
Hybrid Strategy — Combines all data sources with configurable weight sets.
Uses the 100-point scoring system with auto-calibratable weights.
"""
from strategies.base import Strategy, Signal
from config import SCORING_WEIGHTS

# Different weight distributions for parameter grid
WEIGHT_SETS = {
    "balanced": SCORING_WEIGHTS,
    "ict_heavy": {
        "liquidations_cluster": 10,
        "fvg_or_ob_in_zone": 20,
        "overextension": 10,
        "delta_volume_absorption": 10,
        "rsi_divergence": 5,
        "vwap_vpoc_rejection": 10,
        "volume_anomaly": 5,
        "liquidity_sweep": 20,
        "key_session": 10,
    },
    "flow_heavy": {
        "liquidations_cluster": 20,
        "fvg_or_ob_in_zone": 5,
        "overextension": 10,
        "delta_volume_absorption": 20,
        "rsi_divergence": 5,
        "vwap_vpoc_rejection": 10,
        "volume_anomaly": 15,
        "liquidity_sweep": 5,
        "key_session": 10,
    },
}


class HybridStrategy(Strategy):
    name = "hybrid"
    param_grid = {
        "weight_set": ["balanced", "ict_heavy", "flow_heavy"],
        "min_score": [55, 65, 75],
        "min_factors": [3, 4, 5],
    }

    def evaluate(self, snapshot: dict, params: dict) -> Signal:
        symbol = snapshot["symbol"]
        vid = self.variant_id(params)
        weights = WEIGHT_SETS[params["weight_set"]]

        score = 0
        factors = {}
        bull_signals = 0
        bear_signals = 0

        current_price = snapshot.get("current_price", 0)

        # --- 1. Liquidations cluster ---
        liq_data = snapshot.get("liquidations", {})
        if liq_data.get("available"):
            score += weights["liquidations_cluster"]
            factors["liquidations_cluster"] = True
            # Direction from liquidation data would need more analysis

        # --- 2. FVG or OB in zone ---
        for tf in ["5m", "15m", "1h"]:
            fvg = snapshot.get(f"fvg_{tf}", {})
            ob = snapshot.get(f"ob_{tf}", {})

            if fvg.get("bullish_fvgs"):
                for f in fvg["bullish_fvgs"]:
                    if f["bottom"] <= current_price <= f["top"] * 1.005:
                        score += weights["fvg_or_ob_in_zone"]
                        factors["fvg_or_ob_in_zone"] = f"bullish_fvg_{tf}"
                        bull_signals += 1
                        break

            if fvg.get("bearish_fvgs"):
                for f in fvg["bearish_fvgs"]:
                    if f["bottom"] * 0.995 <= current_price <= f["top"]:
                        score += weights["fvg_or_ob_in_zone"]
                        factors["fvg_or_ob_in_zone"] = f"bearish_fvg_{tf}"
                        bear_signals += 1
                        break

            if "fvg_or_ob_in_zone" not in factors:
                if ob.get("bullish_obs"):
                    for o in ob["bullish_obs"]:
                        if o["bottom"] <= current_price <= o["top"] * 1.002:
                            score += weights["fvg_or_ob_in_zone"]
                            factors["fvg_or_ob_in_zone"] = f"bullish_ob_{tf}"
                            bull_signals += 1
                            break
                if ob.get("bearish_obs"):
                    for o in ob["bearish_obs"]:
                        if o["bottom"] * 0.998 <= current_price <= o["top"]:
                            score += weights["fvg_or_ob_in_zone"]
                            factors["fvg_or_ob_in_zone"] = f"bearish_ob_{tf}"
                            bear_signals += 1
                            break

            if "fvg_or_ob_in_zone" in factors:
                break

        # --- 3. Overextension ---
        ema_data = snapshot.get("emas", {})
        ema_20_dist = ema_data.get("ema_20", {}).get("distance_pct", 0)
        if abs(ema_20_dist) > 2:
            score += weights["overextension"]
            factors["overextension"] = round(ema_20_dist, 2)
            if ema_20_dist > 2:
                bear_signals += 1
            else:
                bull_signals += 1

        # --- 4. Delta volume absorption ---
        absorption = snapshot.get("absorption", {})
        if absorption.get("absorptions_detected", 0) > 0:
            score += weights["delta_volume_absorption"]
            factors["delta_volume_absorption"] = True

        delta_data = snapshot.get("delta_volume", {})
        deltas = delta_data.get("deltas", [])
        if deltas:
            recent_delta_sum = sum(deltas[-5:])
            if recent_delta_sum > 0:
                bull_signals += 1
            else:
                bear_signals += 1

        # --- 5. RSI divergence ---
        rsi_div = snapshot.get("rsi_divergence", {})
        if rsi_div.get("has_bullish_div"):
            score += weights["rsi_divergence"]
            factors["rsi_divergence"] = "bullish"
            bull_signals += 1
        elif rsi_div.get("has_bearish_div"):
            score += weights["rsi_divergence"]
            factors["rsi_divergence"] = "bearish"
            bear_signals += 1

        # --- 6. VWAP/VPOC rejection ---
        vwap = snapshot.get("vwap", {})
        vpoc = snapshot.get("vpoc", {})
        vwap_dist = abs(vwap.get("distance_pct", 999))
        vpoc_dist = abs(vpoc.get("distance_to_vpoc_pct", 999))

        if vwap_dist < 0.3 or vpoc_dist < 0.3:
            score += weights["vwap_vpoc_rejection"]
            factors["vwap_vpoc_rejection"] = f"vwap={round(vwap_dist, 3)}% vpoc={round(vpoc_dist, 3)}%"

        # --- 7. Volume anomaly ---
        klines = snapshot.get("klines", [])
        if klines:
            volumes = [k.get("volume", 0) for k in klines[-30:]]
            if len(volumes) > 1:
                avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
                if avg_vol > 0 and volumes[-1] > avg_vol * 2:
                    score += weights["volume_anomaly"]
                    factors["volume_anomaly"] = f"{round(volumes[-1] / avg_vol, 1)}x"

        # --- 8. Liquidity sweep ---
        for tf in ["5m", "15m"]:
            sweep = snapshot.get(f"sweep_{tf}", {})
            sweeps_list = sweep.get("sweeps", [])
            if sweeps_list:
                recent = sweeps_list[-1]
                score += weights["liquidity_sweep"]
                factors["liquidity_sweep"] = recent.get("type", "detected")
                if "bullish" in recent.get("type", ""):
                    bull_signals += 1
                else:
                    bear_signals += 1
                break

        # --- 9. Key session ---
        if snapshot.get("is_key_session"):
            score += weights["key_session"]
            factors["key_session"] = snapshot.get("current_session", "active")

        # Determine direction from signal count
        if bull_signals > bear_signals:
            direction = "long"
        elif bear_signals > bull_signals:
            direction = "short"
        else:
            direction = "neutral"

        # Check minimum factors
        active_count = len(factors)
        if active_count < params["min_factors"]:
            score = min(score, params["min_score"] - 1)

        if score < params["min_score"]:
            direction = "neutral"

        confidence = min(score, 100)

        entry = stop = target = rr = None
        if direction == "long" and score >= params["min_score"]:
            entry = current_price
            stop = entry * 0.985
            target = entry + (entry - stop) * 2
            rr = 2.0
        elif direction == "short" and score >= params["min_score"]:
            entry = current_price
            stop = entry * 1.015
            target = entry - (stop - entry) * 2
            rr = 2.0

        return Signal(
            strategy_name=self.name,
            variant_id=vid,
            symbol=symbol,
            direction=direction,
            score=min(score, 100),
            confidence=round(confidence, 1),
            entry=round(entry, 2) if entry else None,
            stop=round(stop, 2) if stop else None,
            target=round(target, 2) if target else None,
            rr=rr,
            factors_active=factors,
            details=f"bull={bull_signals} bear={bear_signals} factors={active_count}",
        )
