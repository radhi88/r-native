"""adversarial_backtest.py — J.25 — Stress test deployed genome against worst-case markets.

Take real historical bars, then apply hostile transformations:
1. Spread widening (1.5×, 2×, 3× spread) — broker quality degradation
2. Slippage injection (random ±N points on each fill)
3. Bar gap simulation — random 0.5-2% gaps between bars (weekend opens)
4. News spike injection — random ATR×3 bars
5. Reverse the sequence (does the genome work in mirror markets?)
6. Bootstrap shuffle (random reorder — does sequence matter?)

A robust genome survives all 6. A fragile genome dies on at least one.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone


# ── Stress transforms ────────────────────────────────────────────────
def _widen_spread(bars, multiplier: float):
    """Increase H-L spread by `multiplier`."""
    import numpy as np
    out = bars.copy()
    for b in out:
        center = (b["high"] + b["low"]) / 2
        half = (b["high"] - b["low"]) / 2 * multiplier
        b["high"] = center + half
        b["low"]  = center - half
    return out


def _inject_slippage(bars, slippage_points: int):
    """Add random small noise to open/close (simulates fill slippage)."""
    out = bars.copy()
    for b in out:
        noise = random.uniform(-slippage_points, slippage_points) * 0.0001
        b["open"]  += noise
        b["close"] += noise * 0.5
    return out


def _inject_gap(bars, gap_pct: float = 0.01, frequency: float = 0.05):
    """Insert random gaps between bars (simulates weekend opens)."""
    out = bars.copy()
    for i in range(1, len(out)):
        if random.random() < frequency:
            direction = random.choice([-1, 1])
            gap = out[i-1]["close"] * gap_pct * direction
            out[i]["open"]  += gap
            out[i]["high"]  += gap
            out[i]["low"]   += gap
            out[i]["close"] += gap
    return out


def _inject_news_spike(bars, n_spikes: int = 3):
    """Replace `n_spikes` random bars with extreme-ATR spikes."""
    import numpy as np
    out = bars.copy()
    avg_range = sum(b["high"] - b["low"] for b in out) / len(out)
    indices = random.sample(range(len(out)), min(n_spikes, len(out)))
    for i in indices:
        center = (out[i]["high"] + out[i]["low"]) / 2
        spike_range = avg_range * 3
        # Random direction
        if random.random() < 0.5:
            out[i]["high"] = center + spike_range
            out[i]["low"]  = center - spike_range * 0.3
            out[i]["close"] = out[i]["high"] - spike_range * 0.2
        else:
            out[i]["low"]  = center - spike_range
            out[i]["high"] = center + spike_range * 0.3
            out[i]["close"] = out[i]["low"] + spike_range * 0.2
    return out


def _reverse(bars):
    """Reverse the price action (mirror market)."""
    out = bars.copy()
    if len(out) == 0: return out
    # Pivot around mean
    closes = [b["close"] for b in out]
    pivot  = sum(closes) / len(closes)
    for b in out:
        for field in ("open", "high", "low", "close"):
            b[field] = 2 * pivot - b[field]
        # high/low swap if mirror flipped them
        if b["high"] < b["low"]: b["high"], b["low"] = b["low"], b["high"]
    return out


def _shuffle(bars):
    """Bootstrap shuffle (random order)."""
    out = bars.copy()
    indices = list(range(len(out)))
    random.shuffle(indices)
    return out[indices]


# ── Master stress test ───────────────────────────────────────────────
def stress_test(genome: dict, symbol: str, tf: str,
                n_bars: int = 4000, seed: int = 42) -> dict:
    """Run genome through 7 scenarios: clean + 6 hostile.

    Returns dict with stats from each scenario + verdict (robust/fragile)."""
    random.seed(seed)
    try:
        import MetaTrader5 as mt5
        from r_native.ga_simulator import simulate_genome
        if not mt5.initialize():
            return {"ok": False, "error": "mt5 init"}
        tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                  "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
        sym_info = mt5.symbol_info(symbol)
        if not sym_info: return {"ok": False, "error": f"no symbol {symbol}"}
        bars = mt5.copy_rates_from_pos(symbol, tf_map.get(tf, mt5.TIMEFRAME_M5),
                                        0, n_bars)
        if bars is None or len(bars) < 100:
            return {"ok": False, "error": "no bars"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    scenarios = {
        "clean":           bars,
        "spread_2x":       _widen_spread(bars, 2.0),
        "spread_3x":       _widen_spread(bars, 3.0),
        "slippage_high":   _inject_slippage(bars, 50),
        "gappy_market":    _inject_gap(bars, gap_pct=0.015, frequency=0.05),
        "news_spikes":     _inject_news_spike(bars, n_spikes=5),
        "reversed":        _reverse(bars),
        "shuffled":        _shuffle(bars),
    }

    results = {}
    for name, modified_bars in scenarios.items():
        try:
            stats = simulate_genome(genome, modified_bars, sym_info)
            results[name] = {
                "trades":   stats.get("trades", 0),
                "pf":       stats.get("profit_factor", 0),
                "wr":       stats.get("win_rate", 0),
                "return":   stats.get("total_return_pct", 0),
                "max_dd":   stats.get("max_drawdown_pct", 0),
                "sharpe":   stats.get("sharpe", 0),
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    # Score robustness: count scenarios where PF > 1.2 and DD < 15%
    survived = sum(1 for r in results.values()
                   if isinstance(r, dict) and not r.get("error")
                   and r.get("pf", 0) > 1.2 and r.get("max_dd", 100) < 15)
    score = survived / len(scenarios) * 100

    if   score >= 85: verdict = "🛡️ BATTLE-TESTED — robust across hostile markets"
    elif score >= 65: verdict = "✅ ROBUST — survives most stress"
    elif score >= 40: verdict = "⚠️ FRAGILE — fails in some scenarios"
    else:             verdict = "🚨 NOT DEPLOYABLE — collapses under stress"

    return {
        "ok":              True,
        "genome_id":       genome.get("id"),
        "symbol":          symbol,
        "tf":              tf,
        "tested_at":       datetime.now(timezone.utc).isoformat(),
        "scenarios":       results,
        "survived_count":  survived,
        "total_scenarios": len(scenarios),
        "robustness_pct":  round(score, 1),
        "verdict":         verdict,
    }
