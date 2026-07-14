"""monte_carlo.py — J.9 — Bootstrap risk simulation.

Take the trade distribution from a genome's backtest. Run 1000 random sequences
(sample with replacement). Compute:
- Worst-case drawdown across all sims (5th/50th/95th percentile)
- Max losing streak distribution
- Probability of ruin (account → 0)
- 95% confidence band for terminal balance
- Required win rate to break even

This catches genomes that look great in one backtest but would have failed
in 50% of alternate market sequences.

Usage:
    from r_native.monte_carlo import simulate
    result = simulate(trades_log, starting_balance=100, n_sims=1000)
    print(result["dd_p95"], result["prob_of_ruin"])
"""
from __future__ import annotations

import random
import statistics
from typing import Iterable


def simulate(trades: list[dict], starting_balance: float = 100.0,
             ruin_threshold: float = 50.0, n_sims: int = 1000,
             seed: int | None = None) -> dict:
    """Run Monte Carlo bootstrap on a trade sequence.

    Args:
        trades:         list of trade dicts (each with 'profit' field) OR list of floats
        starting_balance: starting account balance
        ruin_threshold: balance below which = ruin (e.g. 50% drawdown = 50)
        n_sims:         number of bootstrap sequences to run
        seed:           optional random seed for reproducibility

    Returns: dict with percentile stats + probability of ruin
    """
    if seed is not None: random.seed(seed)

    # Extract profits
    profits = []
    for t in trades:
        if isinstance(t, dict):
            p = t.get("profit") or t.get("pl") or 0
        else:
            p = float(t)
        profits.append(float(p))

    if not profits:
        return {"ok": False, "error": "no trades"}

    n = len(profits)
    # Run N sims
    terminal_balances = []
    max_dds            = []
    max_loss_streaks   = []
    ruin_count         = 0

    for _ in range(n_sims):
        # Bootstrap sample (with replacement)
        sequence = [random.choice(profits) for _ in range(n)]

        bal = starting_balance
        peak = bal
        dd = 0.0
        streak = 0
        max_streak = 0
        ruined = False

        for p in sequence:
            bal += p
            peak = max(peak, bal)
            dd = max(dd, peak - bal)
            if p < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
            if bal <= ruin_threshold and not ruined:
                ruined = True
                ruin_count += 1
                # don't break — let it finish for terminal_balance stats

        terminal_balances.append(bal)
        max_dds.append(dd)
        max_loss_streaks.append(max_streak)

    # Percentiles
    terminal_balances.sort()
    max_dds.sort()
    max_loss_streaks.sort()
    def pct(arr, p):
        if not arr: return 0
        return arr[max(0, min(len(arr) - 1, int(len(arr) * p / 100)))]

    # Win rate baseline
    n_wins  = sum(1 for p in profits if p > 0)
    win_rate = n_wins / len(profits) * 100
    avg_win  = sum(p for p in profits if p > 0) / max(1, n_wins)
    avg_loss = abs(sum(p for p in profits if p < 0) / max(1, len(profits) - n_wins))
    rr_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0
    # Break-even WR: 1 / (1 + rr_ratio)
    breakeven_wr = (1 / (1 + rr_ratio) * 100) if rr_ratio > 0 else 50

    return {
        "ok":              True,
        "n_sims":          n_sims,
        "n_trades_per_sim": n,
        "starting_balance": starting_balance,
        "ruin_threshold":   ruin_threshold,
        # Terminal balance distribution
        "terminal_p05":     round(pct(terminal_balances, 5),  2),
        "terminal_p50":     round(pct(terminal_balances, 50), 2),
        "terminal_p95":     round(pct(terminal_balances, 95), 2),
        "terminal_mean":    round(statistics.mean(terminal_balances), 2),
        # Drawdown distribution
        "dd_p50":           round(pct(max_dds, 50), 2),
        "dd_p95":           round(pct(max_dds, 95), 2),
        "dd_worst":         round(max(max_dds) if max_dds else 0, 2),
        # Losing streak distribution
        "loss_streak_p50":  pct(max_loss_streaks, 50),
        "loss_streak_p95":  pct(max_loss_streaks, 95),
        "loss_streak_worst": max(max_loss_streaks) if max_loss_streaks else 0,
        # Ruin
        "ruin_count":       ruin_count,
        "prob_of_ruin_pct": round(ruin_count / n_sims * 100, 2),
        # Edge baseline
        "actual_win_rate":  round(win_rate, 1),
        "breakeven_win_rate": round(breakeven_wr, 1),
        "edge_pct":         round(win_rate - breakeven_wr, 1),
        "avg_win":          round(avg_win, 4),
        "avg_loss":         round(-avg_loss, 4),
        "rr_ratio":         round(rr_ratio, 2),
    }


def verdict(sim_result: dict) -> str:
    """Human-readable verdict for a simulation result."""
    if not sim_result.get("ok"): return f"⚠️ {sim_result.get('error', 'failed')}"
    por  = sim_result["prob_of_ruin_pct"]
    dd95 = sim_result["dd_p95"]
    edge = sim_result["edge_pct"]
    if por > 5:       return f"🚨 HIGH RISK — {por:.1f}% chance of ruin"
    if dd95 > 30:     return f"⚠️ DRAWDOWN RISK — 95th percentile DD ${dd95:.2f}"
    if edge < 5:      return f"😬 THIN EDGE — only {edge:.1f}% over breakeven WR"
    if por < 1 and edge > 15: return f"🏆 ROBUST — edge {edge:.1f}%, ruin {por:.2f}%"
    return f"✅ ACCEPTABLE — edge {edge:.1f}%, ruin {por:.2f}%, DD95 ${dd95:.2f}"
