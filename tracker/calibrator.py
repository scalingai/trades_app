"""
Auto-calibration of scoring weights based on actual trade results.
Analyzes which factors correlate with winning trades and adjusts weights.
"""
import ast
import pandas as pd
from tracker.performance import _ensure_file, RESULTS_FILE, RESULTS_COLUMNS


def analyze_factor_correlation() -> dict:
    """Analyze which factors appear most in winning vs losing trades.

    Returns correlation scores per factor:
    - Positive = factor correlates with wins
    - Negative = factor correlates with losses
    """
    df = _ensure_file(RESULTS_FILE, RESULTS_COLUMNS)
    if len(df) < 10:
        return {"message": f"Need at least 10 trades for calibration (have {len(df)})", "ready": False}

    factor_wins = {}
    factor_losses = {}
    factor_total = {}

    for _, row in df.iterrows():
        try:
            factors = ast.literal_eval(row["factors"]) if isinstance(row["factors"], str) else row["factors"]
        except (ValueError, SyntaxError):
            continue

        if not isinstance(factors, dict):
            continue

        for factor_name in factors:
            factor_total[factor_name] = factor_total.get(factor_name, 0) + 1
            if row["result"] == "win":
                factor_wins[factor_name] = factor_wins.get(factor_name, 0) + 1
            elif row["result"] == "loss":
                factor_losses[factor_name] = factor_losses.get(factor_name, 0) + 1

    correlations = {}
    for factor, total in factor_total.items():
        wins = factor_wins.get(factor, 0)
        losses = factor_losses.get(factor, 0)
        # Win rate when this factor is active
        win_rate = wins / total * 100 if total > 0 else 0
        correlations[factor] = {
            "total_appearances": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "correlation": round((wins - losses) / total, 3) if total > 0 else 0,
        }

    return {
        "correlations": correlations,
        "total_trades_analyzed": len(df),
        "ready": True,
    }


def suggest_new_weights(current_weights: dict) -> dict:
    """Suggest new weights based on factor correlation analysis.

    Factors with higher win rate get more weight.
    """
    analysis = analyze_factor_correlation()
    if not analysis.get("ready"):
        return {"message": analysis.get("message"), "weights": current_weights}

    correlations = analysis["correlations"]
    total_weight = sum(current_weights.values())

    # Map factor names between scoring and tracking
    suggested = {}
    for factor_name, current_weight in current_weights.items():
        if factor_name in correlations:
            corr = correlations[factor_name]
            # Adjust weight: multiply by (win_rate / 50) so 50% win rate = no change
            multiplier = max(0.3, min(2.0, corr["win_rate"] / 50))
            suggested[factor_name] = round(current_weight * multiplier)
        else:
            suggested[factor_name] = current_weight

    # Normalize to maintain same total weight
    suggested_total = sum(suggested.values())
    if suggested_total > 0:
        for k in suggested:
            suggested[k] = round(suggested[k] * total_weight / suggested_total)

    return {
        "current_weights": current_weights,
        "suggested_weights": suggested,
        "correlations": correlations,
        "total_trades": analysis["total_trades_analyzed"],
    }
