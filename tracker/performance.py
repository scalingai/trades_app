"""
Performance tracking per strategy variant.
Tracks wins, losses, RR achieved, and factor correlation.
"""
import os
import pandas as pd
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PROPOSALS_FILE = os.path.join(DATA_DIR, "trade_proposals.csv")
RESULTS_FILE = os.path.join(DATA_DIR, "trade_results.csv")
VARIANT_STATS_FILE = os.path.join(DATA_DIR, "variant_stats.csv")

PROPOSALS_COLUMNS = [
    "id", "timestamp", "symbol", "direction", "entry", "stop", "target", "rr",
    "score", "confidence", "strategy", "variant", "consensus_pct",
    "factors", "status",  # proposed, approved, rejected, expired
]

RESULTS_COLUMNS = [
    "id", "proposal_id", "timestamp", "symbol", "direction",
    "entry_price", "exit_price", "pnl_pct", "rr_achieved",
    "result",  # win, loss, breakeven
    "strategy", "variant", "factors",
]


def _ensure_file(filepath: str, columns: list) -> pd.DataFrame:
    if os.path.exists(filepath):
        return pd.read_csv(filepath)
    df = pd.DataFrame(columns=columns)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)
    return df


def log_proposal(
    symbol: str, direction: str, entry: float, stop: float, target: float,
    rr: float, score: float, confidence: float, strategy: str, variant: str,
    consensus_pct: float, factors: dict,
) -> str:
    """Log a trade proposal. Returns proposal ID."""
    df = _ensure_file(PROPOSALS_FILE, PROPOSALS_COLUMNS)
    proposal_id = f"P{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}"

    new_row = {
        "id": proposal_id,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": rr,
        "score": score,
        "confidence": confidence,
        "strategy": strategy,
        "variant": variant,
        "consensus_pct": consensus_pct,
        "factors": str(factors),
        "status": "proposed",
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(PROPOSALS_FILE, index=False)
    return proposal_id


def update_proposal_status(proposal_id: str, status: str):
    """Update proposal status: approved, rejected, expired."""
    df = _ensure_file(PROPOSALS_FILE, PROPOSALS_COLUMNS)
    df.loc[df["id"] == proposal_id, "status"] = status
    df.to_csv(PROPOSALS_FILE, index=False)


def log_result(
    proposal_id: str, symbol: str, direction: str,
    entry_price: float, exit_price: float,
    strategy: str, variant: str, factors: dict,
) -> str:
    """Log trade result. Calculates P&L and RR achieved."""
    df = _ensure_file(RESULTS_FILE, RESULTS_COLUMNS)

    if direction == "long":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100

    # Get proposal to calculate RR achieved
    proposals = _ensure_file(PROPOSALS_FILE, PROPOSALS_COLUMNS)
    proposal = proposals[proposals["id"] == proposal_id]
    if not proposal.empty:
        stop = float(proposal.iloc[0]["stop"])
        risk = abs(entry_price - stop)
        rr_achieved = abs(exit_price - entry_price) / risk if risk > 0 else 0
        if pnl_pct < 0:
            rr_achieved = -rr_achieved
    else:
        rr_achieved = 0

    result = "win" if pnl_pct > 0.1 else "loss" if pnl_pct < -0.1 else "breakeven"

    result_id = f"R{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}"
    new_row = {
        "id": result_id,
        "proposal_id": proposal_id,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": round(pnl_pct, 4),
        "rr_achieved": round(rr_achieved, 2),
        "result": result,
        "strategy": strategy,
        "variant": variant,
        "factors": str(factors),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(RESULTS_FILE, index=False)
    return result_id


def get_performance(strategy: str = None, variant: str = None) -> dict:
    """Get performance stats, optionally filtered by strategy/variant."""
    df = _ensure_file(RESULTS_FILE, RESULTS_COLUMNS)

    if df.empty:
        return {"total_trades": 0, "message": "No trades recorded yet"}

    if strategy:
        df = df[df["strategy"] == strategy]
    if variant:
        df = df[df["variant"] == variant]

    if df.empty:
        return {"total_trades": 0, "message": "No trades for this filter"}

    total = len(df)
    wins = len(df[df["result"] == "win"])
    losses = len(df[df["result"] == "loss"])
    be = len(df[df["result"] == "breakeven"])

    win_rate = wins / total * 100 if total > 0 else 0
    avg_rr = df["rr_achieved"].mean()
    total_pnl = df["pnl_pct"].sum()

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven": be,
        "win_rate": round(win_rate, 1),
        "avg_rr": round(avg_rr, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "best_trade_pnl": round(df["pnl_pct"].max(), 2),
        "worst_trade_pnl": round(df["pnl_pct"].min(), 2),
    }


def get_variant_ranking() -> list[dict]:
    """Rank all strategy variants by performance."""
    df = _ensure_file(RESULTS_FILE, RESULTS_COLUMNS)
    if df.empty:
        return []

    rankings = []
    for variant, group in df.groupby("variant"):
        total = len(group)
        wins = len(group[group["result"] == "win"])
        rankings.append({
            "variant": variant,
            "trades": total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_rr": round(group["rr_achieved"].mean(), 2),
            "total_pnl_pct": round(group["pnl_pct"].sum(), 2),
        })

    return sorted(rankings, key=lambda x: x["total_pnl_pct"], reverse=True)
