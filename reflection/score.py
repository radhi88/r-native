"""score.py - grade a window of realized FRIDAY trades against goal.json.

score(trades, goal) -> dict with composite in [-1, +1] plus a full breakdown.

Stdlib only. Pure / deterministic given the inputs (no MT5, no I/O).
A trade is a dict with at least: {"profit": float, "time_epoch": int, "result": str}.
"""
from __future__ import annotations

import math
from typing import Any


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _span_days(trades: list[dict[str, Any]]) -> float:
    times = [int(t.get("time_epoch") or 0) for t in trades if t.get("time_epoch")]
    if len(times) < 2:
        return 0.0
    return max(0.0, (max(times) - min(times)) / 86400.0)


def _drawdown(profits: list[float], equity_base: float) -> float:
    """Peak-to-trough drawdown of the cumulative-PnL equity curve, as a fraction."""
    equity = equity_base
    peak = equity_base
    max_dd = 0.0
    for p in profits:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def _sharpe(returns: list[float]) -> float | None:
    """Per-trade Sharpe = mean / stdev of per-trade returns. None if < 3 trades."""
    n = len(returns)
    if n < 3:
        return None
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return None
    return mean / std


def score(trades: list[dict[str, Any]], goal: dict[str, Any]) -> dict[str, Any]:
    equity_base = float(goal.get("account_equity_base", 10000.0)) or 10000.0
    target = float(goal.get("target_return_30d", 0.05))
    max_dd = float(goal.get("max_drawdown", 0.08))
    min_sharpe = float(goal.get("min_sharpe", 1.2))
    fail_return = float(goal.get("failure_below_return", -0.04))

    profits = [float(t.get("profit") or 0.0) for t in trades]
    n = len(profits)

    if n == 0:
        return {
            "composite": 0.0,
            "n_trades": 0,
            "confidence": "none",
            "breakdown": {
                "return_window": 0.0, "return_30d": 0.0, "return_score": 0.0,
                "drawdown": 0.0, "drawdown_score": 0.0,
                "sharpe": None, "sharpe_score": 0.0,
                "span_days": 0.0, "total_pnl": 0.0,
            },
            "notes": ["No realized trades yet - nothing to score."],
        }

    total_pnl = sum(profits)
    return_window = total_pnl / equity_base

    # Project the window return to 30 days, but cap extrapolation from short samples.
    span = _span_days(trades)
    if span >= 1.0:
        scale = min(4.0, 30.0 / span)  # never extrapolate more than 4x
        return_30d = return_window * scale
    else:
        return_30d = return_window  # < 1 day of data: report raw, don't fabricate a month

    # --- sub-score 1: return vs target  (target -> +1, 0 -> 0, -target -> -1) ---
    if target > 0:
        ratio = return_30d / target
    else:
        ratio = 0.0
    return_score = _clamp(ratio)

    # --- sub-score 2: drawdown vs max  (0 dd -> +1, max_dd -> -1, beyond -> -1) ---
    dd = _drawdown(profits, equity_base)
    drawdown_score = _clamp(1.0 - 2.0 * (dd / max_dd)) if max_dd > 0 else 0.0

    # --- sub-score 3: sharpe vs min ---
    returns = [p / equity_base for p in profits]
    sharpe = _sharpe(returns)
    if sharpe is None:
        sharpe_score = 0.0  # neutral until enough trades
    else:
        sharpe_score = _clamp(sharpe / min_sharpe) if min_sharpe > 0 else 0.0

    composite = 0.40 * return_score + 0.35 * drawdown_score + 0.25 * sharpe_score

    notes: list[str] = []

    # --- hard floors (the brakes) ---
    if dd > max_dd:
        composite = min(composite, -0.90)
        notes.append(f"DRAWDOWN BREACH: {dd:.1%} > max {max_dd:.1%} -> hard fail.")
    if return_30d < fail_return:
        composite = min(composite, -0.80)
        notes.append(f"RETURN below failure floor: {return_30d:.1%} < {fail_return:.1%} -> steeply negative.")

    confidence = "low" if n < 10 else ("medium" if n < 25 else "high")

    return {
        "composite": round(_clamp(composite), 4),
        "n_trades": n,
        "confidence": confidence,
        "breakdown": {
            "return_window": round(return_window, 4),
            "return_30d": round(return_30d, 4),
            "return_score": round(return_score, 4),
            "drawdown": round(dd, 4),
            "drawdown_score": round(drawdown_score, 4),
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "sharpe_score": round(sharpe_score, 4),
            "span_days": round(span, 2),
            "total_pnl": round(total_pnl, 2),
        },
        "notes": notes,
    }
