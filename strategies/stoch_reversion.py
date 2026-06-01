"""strategies/stoch_reversion.py — the M3 gold Stochastic mean-reversion
strategy reverse-engineered from the user's MT5 screenshot.

Setup (from the chart):
  Indicator   : Stochastic Oscillator  (%K=14, %D=3, slowing=3)
  Entries     : SELL when %D crosses DOWN through 90 or 85
                BUY  when %D crosses UP   through 10 or 15
  Exit        : TP when %D crosses 50 (mean reversion to midline)
  Symbol      : XAUUSD on M3
  Lot         : 0.01 fixed
  Magic       : 20260605 (R_MAGIC)

Reverse-engineering notes:
  • The screenshot oscillator has both a histogram component AND a smooth
    line, peaking near 90 when price topped and troughing near 15 — that
    matches Stochastic with %K rendered as histogram and %D as the line.
  • The MACD/MACD-histogram claim from the IG comments is mathematically
    impossible: MACD on gold @ $4530 produces values in the range -1.3
    to +1.2, so 90/85/50/15/10 cannot be its levels.
  • SL is not visible in the screenshot. We add a conservative ATR-based
    SL so a runaway candle doesn't blow the account.
"""
from __future__ import annotations

import numpy as np
from typing import Optional

from r_native.strategy_types import (
    Strategy, RiskConfig, IndicatorStatus, EntryCondition,
    INDICATOR_KEYS, INDICATOR_LABELS,
)


# ─── Strategy definition (saveable into strategy_store) ──────────
def build_stoch_reversion_strategy() -> Strategy:
    """Build the Strategy object you can drop into strategy_store."""
    inds = [IndicatorStatus(k, INDICATOR_LABELS[k], enabled=(k == "stochastic"))
            for k in INDICATOR_KEYS]
    return Strategy(
        id=Strategy.new_id(),
        name="Gold M3 — Stochastic Reversion",
        rawPrompt=("Mean-reversion on Gold M3 with Stochastic. SELL when %D "
                    "hits 85 or 90 (pyramid), BUY when %D hits 10 or 15, exit "
                    "on midline 50 crossing. Conservative ATR SL."),
        systemPrompt=(
            "Stochastic mean-reversion strategy on XAUUSD M3. Enter SHORT on "
            "%D cross-down through 85 (light) or 90 (heavy). Enter LONG on "
            "%D cross-up through 15 (light) or 10 (heavy). Exit on %D crossing "
            "the 50 midline (mean reversion to equilibrium). Add a hard ATR "
            "stop-loss to survive trend continuation episodes when Stochastic "
            "lingers in OB/OS for many bars."
        ),
        methodology="TECHNICAL",
        pairs=["XAUUSDm"],
        timeframe="5m",   # store enum lacks "3m"; the EA itself runs on M3
        indicators=inds,
        entryConditions=[
            EntryCondition("SELL", "%D crosses DOWN through 90", 85),
            EntryCondition("SELL", "%D crosses DOWN through 85", 75),
            EntryCondition("BUY",  "%D crosses UP through 15",   75),
            EntryCondition("BUY",  "%D crosses UP through 10",   85),
        ],
        risk=RiskConfig(
            maxPerTradePct=1.0, dailyLossLimitPct=5.0,
            maxOpenTrades=2, maxPerSymbol=2,    # pyramid: 2 SELL at 85 + 90
            atrLength=14, slAtrMult=2.5,        # SL 2.5x ATR (loose: lets Stoch breathe)
            tpAtrMults=[0.0, 0.0, 0.0],          # TP is dynamic (%D=50), not ATR
            trailAtrMult=None, minConfidence=0.0,
        ),
        status="PAUSED",
    )


# ─── Pure-Python evaluator (used by tests + the live monitor) ────
STOCH_K_PERIOD   = 14
STOCH_D_PERIOD   = 3
STOCH_SLOWING    = 3
OB_HEAVY = 90.0   # primary SELL
OB_LIGHT = 85.0   # pyramid SELL
OS_HEAVY = 10.0   # primary BUY
OS_LIGHT = 15.0   # pyramid BUY
MIDLINE  = 50.0   # mean-reversion exit


def stochastic_kd(bars: list, k_period: int = STOCH_K_PERIOD,
                  d_period: int = STOCH_D_PERIOD,
                  slowing: int = STOCH_SLOWING) -> tuple[np.ndarray, np.ndarray]:
    """Return (%K_slow, %D) arrays — same length as bars, NaN before warmup."""
    h = np.array([float(b["high"])  for b in bars])
    l = np.array([float(b["low"])   for b in bars])
    c = np.array([float(b["close"]) for b in bars])
    n = len(c)
    raw_k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        hi = h[i - k_period + 1: i + 1].max()
        lo = l[i - k_period + 1: i + 1].min()
        if hi > lo:
            raw_k[i] = (c[i] - lo) / (hi - lo) * 100.0
        else:
            raw_k[i] = 50.0
    # Slowing: SMA of raw %K
    slow_k = np.full(n, np.nan)
    for i in range(k_period - 1 + slowing - 1, n):
        slow_k[i] = np.nanmean(raw_k[i - slowing + 1: i + 1])
    # %D = SMA of slow %K over d_period
    d_line = np.full(n, np.nan)
    for i in range(k_period + slowing + d_period - 3, n):
        d_line[i] = np.nanmean(slow_k[i - d_period + 1: i + 1])
    return slow_k, d_line


def evaluate_signal(prev_d: float, cur_d: float) -> Optional[dict]:
    """Given the previous and current %D values, emit the entry/exit
    decision per the screenshot strategy.

    Returns None for "do nothing" or a dict
    {action: 'SELL'|'BUY'|'CLOSE', level: float, tier: 'HEAVY'|'LIGHT'|'MID'}.
    """
    if np.isnan(prev_d) or np.isnan(cur_d):
        return None

    # Mean-reversion exit: %D crosses through 50 in either direction
    if (prev_d > MIDLINE >= cur_d) or (prev_d < MIDLINE <= cur_d):
        return {"action": "CLOSE", "level": MIDLINE, "tier": "MID"}

    # SELL entries (only on cross-down through threshold)
    if prev_d >= OB_HEAVY > cur_d:
        return {"action": "SELL", "level": OB_HEAVY, "tier": "HEAVY"}
    if prev_d >= OB_LIGHT > cur_d:
        return {"action": "SELL", "level": OB_LIGHT, "tier": "LIGHT"}

    # BUY entries (only on cross-up through threshold)
    if prev_d <= OS_HEAVY < cur_d:
        return {"action": "BUY", "level": OS_HEAVY, "tier": "HEAVY"}
    if prev_d <= OS_LIGHT < cur_d:
        return {"action": "BUY", "level": OS_LIGHT, "tier": "LIGHT"}
    return None


def backtest(bars: list, *, atr_sl_mult: float = 2.5, lot_value_per_unit: float = 1.0,
              atr_period: int = 14) -> dict:
    """Walk bars left-to-right, emit signals, simulate fills + exits + SLs.
    Returns {trades:[...], summary:{...}, equity_curve:[...]}.

    Each trade: {idx_open, idx_close, side, entry, exit, sl, profit, exit_reason, tier}
    """
    slow_k, d_line = stochastic_kd(bars)
    n = len(bars)

    # ATR for SL distance
    h = np.array([float(b["high"]) for b in bars])
    l = np.array([float(b["low"])  for b in bars])
    c = np.array([float(b["close"]) for b in bars])
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.full(n, tr[0])
    if n > atr_period:
        atr[atr_period - 1] = tr[:atr_period].mean()
        for i in range(atr_period, n):
            atr[i] = (atr[i - 1] * (atr_period - 1) + tr[i]) / atr_period

    open_positions = []   # [{side, entry, idx_open, sl, tier}, ...]
    trades = []
    equity = 0.0
    equity_curve = []

    for i in range(1, n):
        bar = bars[i]
        bar_h = float(bar["high"]); bar_l = float(bar["low"])
        bar_c = float(bar["close"])

        # ─ Check SL hits on open positions (intrabar pessimistic)
        still_open = []
        for pos in open_positions:
            hit_sl = (pos["side"] == "BUY"  and bar_l <= pos["sl"]) or \
                     (pos["side"] == "SELL" and bar_h >= pos["sl"])
            if hit_sl:
                exit_px = pos["sl"]
                pnl = ((exit_px - pos["entry"]) if pos["side"] == "BUY"
                       else (pos["entry"] - exit_px)) * lot_value_per_unit
                equity += pnl
                trades.append({
                    "idx_open": pos["idx_open"], "idx_close": i,
                    "side": pos["side"], "entry": pos["entry"],
                    "exit": exit_px, "sl": pos["sl"], "profit": pnl,
                    "exit_reason": "SL", "tier": pos["tier"],
                })
                continue
            still_open.append(pos)
        open_positions = still_open

        # ─ Read the signal for this bar
        signal = evaluate_signal(d_line[i - 1], d_line[i])
        if signal is None:
            equity_curve.append({"i": i, "eq": equity}); continue

        if signal["action"] == "CLOSE":
            # Close every open position at the bar close
            for pos in open_positions:
                exit_px = bar_c
                pnl = ((exit_px - pos["entry"]) if pos["side"] == "BUY"
                       else (pos["entry"] - exit_px)) * lot_value_per_unit
                equity += pnl
                trades.append({
                    "idx_open": pos["idx_open"], "idx_close": i,
                    "side": pos["side"], "entry": pos["entry"],
                    "exit": exit_px, "sl": pos["sl"], "profit": pnl,
                    "exit_reason": "TP_midline", "tier": pos["tier"],
                })
            open_positions = []
        else:
            # OPEN a position with ATR-based SL
            entry = bar_c
            sl_dist = atr_sl_mult * atr[i]
            if signal["action"] == "BUY":
                sl = entry - sl_dist
            else:
                sl = entry + sl_dist
            # Cap concurrent positions per side (pyramid 2 max)
            same_side = [p for p in open_positions if p["side"] == signal["action"]]
            if len(same_side) >= 2:
                pass  # already maxed pyramid — skip duplicate
            else:
                open_positions.append({
                    "side": signal["action"], "entry": entry,
                    "idx_open": i, "sl": sl, "tier": signal["tier"],
                })
        equity_curve.append({"i": i, "eq": equity})

    # Force-close any still-open at the end (using last close)
    for pos in open_positions:
        exit_px = float(bars[-1]["close"])
        pnl = ((exit_px - pos["entry"]) if pos["side"] == "BUY"
               else (pos["entry"] - exit_px)) * lot_value_per_unit
        equity += pnl
        trades.append({
            "idx_open": pos["idx_open"], "idx_close": n - 1,
            "side": pos["side"], "entry": pos["entry"],
            "exit": exit_px, "sl": pos["sl"], "profit": pnl,
            "exit_reason": "EOD", "tier": pos["tier"],
        })

    # Summary
    wins   = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] < 0]
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = abs(sum(t["profit"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.99 if gross_win > 0 else 0.0)
    summary = {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate":      round(len(wins) / max(len(trades), 1) * 100, 1),
        "profit_factor": round(pf, 2),
        "net_pnl":       round(equity, 2),
        "avg_win":       round(np.mean([t["profit"] for t in wins]),   2) if wins   else 0,
        "avg_loss":      round(np.mean([t["profit"] for t in losses]), 2) if losses else 0,
        "best":          round(max([t["profit"] for t in trades]), 2) if trades else 0,
        "worst":         round(min([t["profit"] for t in trades]), 2) if trades else 0,
        "exit_breakdown": {
            "TP_midline": sum(1 for t in trades if t["exit_reason"] == "TP_midline"),
            "SL":         sum(1 for t in trades if t["exit_reason"] == "SL"),
            "EOD":        sum(1 for t in trades if t["exit_reason"] == "EOD"),
        },
    }
    return {"trades": trades, "summary": summary,
            "stoch_d": d_line.tolist(), "stoch_k": slow_k.tolist(),
            "equity_curve": equity_curve}
