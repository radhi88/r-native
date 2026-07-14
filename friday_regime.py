"""
friday_regime.py — Market regime classifier.

Detects whether the market is:
  • TREND       — sustained directional move, good for breakout strategies
  • RANGE       — sideways chop, kill zone for scalpers
  • EVENT       — wild spread/volatility spike (news), no trade
  • DEAD        — too quiet, ATR too small to cover spread

Trade gate: brain consults this BEFORE every decision.
"""
from __future__ import annotations
import statistics
from datetime import datetime, timezone

import MetaTrader5 as mt5


SYMBOL = "XAUUSDm"


def classify_regime() -> dict:
    """Returns {regime, score, reasons, allow_trade, recommended_strategy}"""
    if not mt5.initialize():
        return {"regime": "UNKNOWN", "allow_trade": False,
                "reasons": ["MT5 init failed"], "score": 0}

    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 60)
    tick  = mt5.symbol_info_tick(SYMBOL)
    sym   = mt5.symbol_info(SYMBOL)
    if rates is None or len(rates) < 20 or not tick or not sym:
        mt5.shutdown()
        return {"regime": "UNKNOWN", "allow_trade": False, "reasons": ["no data"], "score": 0}

    # Compute features
    closes = [r["close"] for r in rates]
    highs  = [r["high"]  for r in rates]
    lows   = [r["low"]   for r in rates]
    ranges = [highs[i] - lows[i] for i in range(len(rates))]

    atr_pt        = statistics.mean(ranges[-14:]) * 100   # for gold, point=0.01
    spread_pt     = sym.spread
    spread_atr    = spread_pt / atr_pt if atr_pt > 0 else 999

    # Trend strength: how directional is the last 20 bars?
    net_move      = abs(closes[-1] - closes[-20])
    total_path    = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    efficiency    = net_move / total_path if total_path > 0 else 0   # 1.0=perfect trend, 0=noise

    # Range %: how much of recent range vs ATR
    last20_high   = max(highs[-20:])
    last20_low    = min(lows[-20:])
    last20_range  = (last20_high - last20_low) * 100   # points
    range_atr     = last20_range / atr_pt if atr_pt > 0 else 0

    # Volatility surge: current bar range vs avg
    surge         = ranges[-1] / statistics.mean(ranges[-30:]) if len(ranges) >= 30 else 1

    reasons = []
    allow   = True
    regime  = "UNKNOWN"
    strategy_hint = ""

    # ── EVENT detection (highest priority) ──
    if surge > 3.0 or spread_pt > 600:
        regime = "EVENT"
        allow  = False
        reasons.append(f"event: surge={surge:.1f}x or spread={spread_pt}pt > 600")
        strategy_hint = "wait for spread to normalize"

    # ── DEAD detection ──
    elif spread_atr > 0.5:
        regime = "DEAD"
        allow  = False
        reasons.append(f"spread/ATR = {spread_atr:.2f} > 0.5 — spread eats the move")
        strategy_hint = "no trading possible — wait for higher volatility"

    # ── TREND ──
    elif efficiency > 0.30 and range_atr > 3:
        regime = "TREND"
        allow  = True
        reasons.append(f"trend efficiency={efficiency:.2f}, range_atr={range_atr:.1f}")
        strategy_hint = "breakout / momentum follow"

    # ── RANGE ──
    elif efficiency < 0.15:
        regime = "RANGE"
        allow  = False  # MOST losses happen here
        reasons.append(f"ranging: efficiency={efficiency:.2f} (too noisy)")
        strategy_hint = "fade extremes only OR wait for breakout"

    # ── CHOP ──
    else:
        regime = "CHOP"
        allow  = False
        reasons.append(f"choppy: eff={efficiency:.2f}, range_atr={range_atr:.1f}")
        strategy_hint = "wait for cleaner setup"

    mt5.shutdown()

    # Score 0-100: how favorable for trading
    score = 0
    if regime == "TREND": score = min(100, int(efficiency * 200))
    elif regime == "RANGE": score = max(0, int((1 - efficiency) * 50))  # range gets some score
    else: score = 20

    return {
        "regime":              regime,
        "score":               score,
        "allow_trade":         allow,
        "reasons":             reasons,
        "strategy_hint":       strategy_hint,
        "atr_pt":              round(atr_pt, 1),
        "spread_pt":           spread_pt,
        "spread_atr_ratio":    round(spread_atr, 3),
        "efficiency":          round(efficiency, 3),
        "range_atr_ratio":     round(range_atr, 2),
        "current_bar_surge":   round(surge, 2),
        "ts":                  datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(classify_regime(), ensure_ascii=False, indent=2))
