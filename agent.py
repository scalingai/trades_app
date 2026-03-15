"""
Trading Agent CLI — Opus 4.6 as final judge.

Modes:
  python agent.py              → Interactive mode
  python agent.py --scan       → Single scan of all pairs
  python agent.py --monitor    → Continuous monitoring loop
  python agent.py --performance → Show performance stats
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

from config import WATCHLIST, MONITOR_INTERVAL_SECONDS, SCORING_CATEGORIES
from engine import scan_symbol, scan_all, collect_snapshot, run_all_strategies, calculate_consensus
from tracker.performance import (
    log_proposal, update_proposal_status, get_performance, get_variant_ranking,
)
from tracker.calibrator import analyze_factor_correlation, suggest_new_weights
from config import SCORING_WEIGHTS


def print_header():
    print("\n" + "=" * 60)
    print("  WAR ROOM — Trading Agent (Opus 4.6 Judge)")
    print("  Strategies: ICT Pure | Order Flow | Volume Profile | Hybrid")
    print("=" * 60)


def print_scan_result(result: dict):
    """Pretty print a scan result."""
    symbol = result["symbol"]
    price = result.get("current_price", "?")
    consensus = result.get("consensus", {})
    direction = consensus.get("dominant_direction", "neutral")
    pct = consensus.get("consensus_pct", 0)
    avg_score = consensus.get("avg_score", 0)
    escalate = consensus.get("escalate", False)
    session = result.get("session", "?")

    # Category
    cat = "NO OPERAR"
    for cat_name, min_score in sorted(SCORING_CATEGORIES.items(), key=lambda x: x[1], reverse=True):
        if avg_score >= min_score:
            cat = cat_name
            break

    # Direction indicator
    dir_icon = {"long": "▲", "short": "▼", "neutral": "—"}.get(direction, "?")

    # Color-like emphasis via text
    escalate_tag = " *** ESCALAR A OPUS ***" if escalate else ""

    print(f"\n  {symbol} | ${price} | {dir_icon} {direction.upper()} | "
          f"Consenso: {pct}% | Score: {avg_score} | Cat: {cat} | "
          f"Session: {session}{escalate_tag}")

    if consensus.get("top_signals"):
        print(f"    Top signals:")
        for sig in consensus["top_signals"][:3]:
            factors_str = ", ".join(f"{k}" for k in sig.get("factors", {}).keys())
            print(f"      {sig['strategy']}({sig['variant'][:30]}): "
                  f"score={sig['score']} dir={sig['direction']} "
                  f"[{factors_str}]")

    if result.get("errors"):
        print(f"    Errors: {len(result['errors'])}")

    return escalate, consensus


def handle_escalation(symbol: str, consensus: dict):
    """Handle escalation to Opus 4.6 — propose trade and wait for user approval."""
    top_signal = consensus["top_signals"][0] if consensus.get("top_signals") else None
    if not top_signal:
        return

    direction = consensus["dominant_direction"]
    entry = top_signal.get("entry")
    stop = top_signal.get("stop")
    target = top_signal.get("target")
    rr = top_signal.get("rr")

    print(f"\n  {'=' * 50}")
    print(f"  TRADE PROPOSAL — {symbol}")
    print(f"  {'=' * 50}")
    print(f"  Direction: {direction.upper()}")
    print(f"  Entry:     ${entry}")
    print(f"  Stop:      ${stop}")
    print(f"  Target:    ${target}")
    print(f"  RR:        1:{rr}")
    print(f"  Score:     {top_signal['score']}/100")
    print(f"  Consensus: {consensus['consensus_pct']}%")
    print(f"  Strategy:  {top_signal['strategy']}")
    print(f"  Factors:   {json.dumps(top_signal.get('factors', {}), indent=2)}")
    print(f"  {'=' * 50}")

    # Log proposal
    proposal_id = log_proposal(
        symbol=symbol,
        direction=direction,
        entry=entry or 0,
        stop=stop or 0,
        target=target or 0,
        rr=rr or 0,
        score=top_signal["score"],
        confidence=top_signal.get("confidence", 0),
        strategy=top_signal["strategy"],
        variant=top_signal.get("variant", ""),
        consensus_pct=consensus["consensus_pct"],
        factors=top_signal.get("factors", {}),
    )

    # Wait for user decision
    print(f"\n  [A]probar | [R]echazar | [S]altear")
    try:
        choice = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "s"

    if choice == "a":
        update_proposal_status(proposal_id, "approved")
        print(f"  Trade APROBADO ({proposal_id})")
    elif choice == "r":
        update_proposal_status(proposal_id, "rejected")
        print(f"  Trade RECHAZADO")
    else:
        print(f"  Salteado")


def mode_scan():
    """Single scan of all pairs."""
    print_header()
    print(f"\n  Scanning {len(WATCHLIST)} pairs at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}...")

    results = scan_all()
    for result in results:
        escalate, consensus = print_scan_result(result)
        if escalate:
            handle_escalation(result["symbol"], consensus)

    print(f"\n  Scan complete.")


def mode_monitor():
    """Continuous monitoring loop."""
    print_header()
    print(f"  Monitor mode — scanning every {MONITOR_INTERVAL_SECONDS}s")
    print(f"  Press Ctrl+C to stop\n")

    cycle = 0
    while True:
        cycle += 1
        print(f"\n{'─' * 60}")
        print(f"  Cycle #{cycle} — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        print(f"{'─' * 60}")

        for symbol in WATCHLIST:
            try:
                result = scan_symbol(symbol)
                escalate, consensus = print_scan_result(result)
                if escalate:
                    handle_escalation(symbol, consensus)
            except Exception as e:
                print(f"  {symbol}: ERROR — {e}")

        print(f"\n  Next scan in {MONITOR_INTERVAL_SECONDS}s...")
        try:
            time.sleep(MONITOR_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\n  Monitor stopped.")
            break


def mode_performance():
    """Show performance stats."""
    print_header()
    print("\n  PERFORMANCE REPORT")
    print(f"  {'=' * 40}")

    stats = get_performance()
    if stats.get("total_trades", 0) == 0:
        print("  No trades recorded yet.")
        return

    print(f"  Total trades:  {stats['total_trades']}")
    print(f"  Wins:          {stats['wins']}")
    print(f"  Losses:        {stats['losses']}")
    print(f"  Win Rate:      {stats['win_rate']}%")
    print(f"  Avg RR:        {stats['avg_rr']}")
    print(f"  Total P&L:     {stats['total_pnl_pct']}%")
    print(f"  Best trade:    {stats['best_trade_pnl']}%")
    print(f"  Worst trade:   {stats['worst_trade_pnl']}%")

    print(f"\n  VARIANT RANKING")
    print(f"  {'=' * 40}")
    rankings = get_variant_ranking()
    for i, r in enumerate(rankings[:10], 1):
        print(f"  {i}. {r['variant'][:40]}")
        print(f"     trades={r['trades']} wr={r['win_rate']}% rr={r['avg_rr']} pnl={r['total_pnl_pct']}%")

    # Factor correlation
    print(f"\n  FACTOR CORRELATION")
    print(f"  {'=' * 40}")
    analysis = analyze_factor_correlation()
    if analysis.get("ready"):
        for factor, data in sorted(
            analysis["correlations"].items(),
            key=lambda x: x[1]["win_rate"],
            reverse=True,
        ):
            print(f"  {factor}: wr={data['win_rate']}% "
                  f"(wins={data['wins']} losses={data['losses']} "
                  f"total={data['total_appearances']})")

        # Suggest new weights
        suggestion = suggest_new_weights(SCORING_WEIGHTS)
        print(f"\n  SUGGESTED WEIGHT ADJUSTMENTS")
        print(f"  {'=' * 40}")
        for k, v in suggestion.get("suggested_weights", {}).items():
            current = SCORING_WEIGHTS.get(k, 0)
            change = v - current
            arrow = "↑" if change > 0 else "↓" if change < 0 else "="
            print(f"  {k}: {current} → {v} {arrow}")
    else:
        print(f"  {analysis.get('message', 'Not enough data')}")


def mode_interactive():
    """Interactive mode — user asks questions, agent responds."""
    print_header()
    print("  Interactive mode. Type 'help' for commands.\n")

    while True:
        try:
            user_input = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("help", "h"):
            print("  Commands:")
            print("    scan                — Scan all watchlist pairs")
            print("    scan <SYMBOL>       — Scan specific symbol (e.g., scan BTCUSDT)")
            print("    performance / perf  — Show performance stats")
            print("    calibrate           — Show factor correlation & weight suggestions")
            print("    watchlist           — Show current watchlist")
            print("    quit / exit         — Exit")

        elif cmd == "scan":
            mode_scan()

        elif cmd.startswith("scan "):
            symbol = cmd.split()[1].upper()
            print(f"\n  Scanning {symbol}...")
            try:
                result = scan_symbol(symbol)
                escalate, consensus = print_scan_result(result)
                if escalate:
                    handle_escalation(symbol, consensus)
            except Exception as e:
                print(f"  Error: {e}")

        elif cmd in ("performance", "perf"):
            mode_performance()

        elif cmd == "calibrate":
            analysis = analyze_factor_correlation()
            if analysis.get("ready"):
                suggestion = suggest_new_weights(SCORING_WEIGHTS)
                print(json.dumps(suggestion, indent=2))
            else:
                print(f"  {analysis.get('message')}")

        elif cmd == "watchlist":
            print(f"  Watchlist: {', '.join(WATCHLIST)}")

        elif cmd in ("quit", "exit", "q"):
            print("  Bye!")
            break

        else:
            print(f"  Unknown command: {cmd}. Type 'help' for commands.")


def main():
    parser = argparse.ArgumentParser(description="Trading Agent — War Room CLI")
    parser.add_argument("--scan", action="store_true", help="Single scan of all pairs")
    parser.add_argument("--monitor", action="store_true", help="Continuous monitoring")
    parser.add_argument("--performance", action="store_true", help="Show performance stats")
    args = parser.parse_args()

    if args.scan:
        mode_scan()
    elif args.monitor:
        mode_monitor()
    elif args.performance:
        mode_performance()
    else:
        mode_interactive()


if __name__ == "__main__":
    main()
