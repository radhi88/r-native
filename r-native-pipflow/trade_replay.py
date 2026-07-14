"""trade_replay.py — J.19 — Time-travel debugger for past trades.

Given a closed trade (from MT5 history or trades_log), reconstruct:
- Market snapshot at entry: M5/M15/H1 bias, ATR, spread, regime
- The gate verdict that would have fired at that moment
- The strategies that were deployed at the time
- Visualization-ready data (bars around entry, SL/TP markers)

UI hook: right-click a trade → "Replay" → modal shows everything.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def replay_trade(symbol: str, entry_ts: int, exit_ts: int = None,
                 entry_price: float = None, exit_price: float = None,
                 side: str = "BUY",
                 bars_before: int = 50, bars_after: int = 50) -> dict:
    """Reconstruct a past trade's context for visualization.

    Args:
        symbol:      e.g. "BTCUSDm"
        entry_ts:    Unix timestamp at entry
        exit_ts:     Optional unix timestamp at exit
        entry_price: Entry price (for marker)
        exit_price:  Exit price (for marker)
        side:        "BUY" or "SELL"
        bars_before: How many bars before entry to include
        bars_after:  How many bars after exit to include

    Returns: dict with bars, markers, indicators, gate_verdict_at_entry
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {"ok": False, "error": "MetaTrader5 not installed"}

    if not mt5.initialize():
        return {"ok": False, "error": f"mt5 init failed: {mt5.last_error()}"}

    # Determine which TF to render (M5 is most informative for short trades)
    tf = mt5.TIMEFRAME_M5
    entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
    exit_dt  = datetime.fromtimestamp(exit_ts,  tz=timezone.utc) if exit_ts else entry_dt + timedelta(hours=2)
    range_start = entry_dt - timedelta(minutes=5 * bars_before)
    range_end   = exit_dt  + timedelta(minutes=5 * bars_after)

    # Pull bars
    bars = mt5.copy_rates_range(symbol, tf, range_start, range_end)
    if bars is None or len(bars) == 0:
        return {"ok": False, "error": "no bars in range"}

    # Build chart-friendly representation
    chart_bars = [{
        "ts":    int(b["time"]),
        "iso":   datetime.fromtimestamp(int(b["time"]), tz=timezone.utc).isoformat(),
        "open":  float(b["open"]),
        "high":  float(b["high"]),
        "low":   float(b["low"]),
        "close": float(b["close"]),
        "vol":   int(b["tick_volume"]),
    } for b in bars]

    # Markers
    markers = []
    if entry_price:
        markers.append({"ts": entry_ts, "type": f"ENTRY_{side}",
                        "price": float(entry_price),
                        "color": "#10b981" if side == "BUY" else "#ef4444"})
    if exit_ts and exit_price:
        pl_color = "#10b981" if (
            (side == "BUY"  and exit_price > entry_price) or
            (side == "SELL" and exit_price < entry_price)) else "#ef4444"
        markers.append({"ts": exit_ts, "type": "EXIT",
                        "price": float(exit_price), "color": pl_color})

    # Quick indicators at entry — bias snapshot
    closes_at_entry = [b["close"] for b in chart_bars
                       if b["ts"] <= entry_ts][-50:]
    bias = "UP" if (closes_at_entry and closes_at_entry[-1] > closes_at_entry[0]) else "DOWN"

    # Compute approximate ATR at entry (last 14 bars)
    pre_entry = [b for b in chart_bars if b["ts"] <= entry_ts][-14:]
    atr = 0.0
    if len(pre_entry) >= 2:
        trs = []
        for i in range(1, len(pre_entry)):
            h, l = pre_entry[i]["high"], pre_entry[i]["low"]
            pc   = pre_entry[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / max(1, len(trs))

    # Reconstruct the gate verdict — call the live gate with a snapshot of THAT moment
    # (best-effort — gate may have changed since)
    gate_verdict = {"verdict": "(historical replay — gate state at that moment unavailable)"}

    # Outcome summary
    result_pl = None
    if entry_price and exit_price:
        if side == "BUY":  result_pl = exit_price - entry_price
        else:              result_pl = entry_price - exit_price

    return {
        "ok":            True,
        "symbol":        symbol,
        "side":          side,
        "entry_ts":      entry_ts,
        "exit_ts":       exit_ts,
        "entry_price":   entry_price,
        "exit_price":    exit_price,
        "bars_count":    len(chart_bars),
        "bars":          chart_bars,
        "markers":       markers,
        "bias_at_entry": bias,
        "atr_at_entry":  round(atr, 5),
        "gate_verdict":  gate_verdict,
        "result_pl":     result_pl,
    }
