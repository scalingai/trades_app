"""
Order Flow Strategy — Delta Volume, Absorption, Liquidations, Funding Rate.
"""
from strategies.base import Strategy, Signal


class OrderFlowStrategy(Strategy):
    name = "order_flow"
    param_grid = {
        "delta_period": [5, 10, 20],
        "absorption_threshold": [2.0, 3.0, 5.0],
        "funding_weight": [0.0, 0.5, 1.0],
        "liq_cluster_distance_pct": [0.5, 1.0, 2.0],
    }

    def evaluate(self, snapshot: dict, params: dict) -> Signal:
        symbol = snapshot["symbol"]
        vid = self.variant_id(params)

        score = 0
        direction = "neutral"
        factors = {}
        current_price = snapshot.get("current_price", 0)

        # --- Factor 1: Delta Volume (25 pts) ---
        delta_data = snapshot.get("delta_volume", {})
        if isinstance(delta_data, dict):
            delta_values = delta_data.get("deltas", [])
        else:
            delta_values = []

        if delta_values:
            period = params["delta_period"]
            recent_deltas = delta_values[-period:]
            avg_delta = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0
            cumulative = sum(recent_deltas)

            if cumulative > 0:
                score += 25
                factors["delta"] = f"bullish (cum={round(cumulative, 2)})"
                direction = "long"
            elif cumulative < 0:
                score += 25
                factors["delta"] = f"bearish (cum={round(cumulative, 2)})"
                direction = "short"

        # --- Factor 2: Absorption (20 pts) ---
        absorption = snapshot.get("absorption", {})
        absorptions_count = absorption.get("absorptions_detected", 0)
        if absorptions_count > 0:
            score += 20
            factors["absorption"] = f"{absorptions_count} detected"

        # --- Factor 3: Order Book Imbalance (15 pts) ---
        order_book = snapshot.get("order_book", {})
        imbalance = order_book.get("imbalance", 0)

        if imbalance > 0.3 and direction in ("long", "neutral"):
            score += 15
            factors["ob_imbalance"] = f"bid_heavy ({round(imbalance, 3)})"
            if direction == "neutral":
                direction = "long"
        elif imbalance < -0.3 and direction in ("short", "neutral"):
            score += 15
            factors["ob_imbalance"] = f"ask_heavy ({round(imbalance, 3)})"
            if direction == "neutral":
                direction = "short"

        # --- Factor 4: Liquidations (20 pts) ---
        liq_data = snapshot.get("liquidations", {})
        if liq_data.get("available"):
            # Cluster distance check
            factors["liquidations"] = "data_available"
            score += 10  # Base points for having liq data

        # --- Factor 5: Funding Rate (10 pts × weight) ---
        funding = snapshot.get("funding_rate", {})
        sentiment = funding.get("sentiment", "unavailable")
        weight = params["funding_weight"]

        if sentiment == "bullish" and direction == "long":
            score += int(10 * weight)
            factors["funding"] = f"bullish (w={weight})"
        elif sentiment == "bearish" and direction == "short":
            score += int(10 * weight)
            factors["funding"] = f"bearish (w={weight})"
        elif sentiment in ("bullish", "bearish"):
            # Contrarian signal
            score += int(5 * weight)
            factors["funding"] = f"contrarian_{sentiment} (w={weight})"

        # --- Factor 6: Bid/Ask Walls (10 pts) ---
        bid_walls = order_book.get("bid_walls", [])
        ask_walls = order_book.get("ask_walls", [])

        if bid_walls and direction == "long":
            score += 10
            factors["walls"] = f"{len(bid_walls)} bid walls"
        elif ask_walls and direction == "short":
            score += 10
            factors["walls"] = f"{len(ask_walls)} ask walls"

        confidence = min(score, 100)

        if score < 30:
            direction = "neutral"

        entry = stop = target = rr = None
        if direction == "long" and score >= 55:
            entry = current_price
            stop = entry * 0.985
            target = entry + (entry - stop) * 2.5
            rr = 2.5
        elif direction == "short" and score >= 55:
            entry = current_price
            stop = entry * 1.015
            target = entry - (stop - entry) * 2.5
            rr = 2.5

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
