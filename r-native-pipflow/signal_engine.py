"""signal_engine.py — unified entry-signal logic (spec section 5).

Two layers that must AGREE before an entry fires:

  1) Confluence — every ENABLED indicator points the same way
                  (live_indicators.aggregate_signal).
  2) Structure  — the SMC engine confirms the same direction with
                  confidence >= strategy.risk.minConfidence.

When both agree -> LONG/SHORT entry with ATR-based SL + T1/T2/T3 targets.
Reused by the Prompt-Trading preview (Feature 1) and the live monitor
(Feature 4). Pure logic — bars + a Strategy in, a decision dict out.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from r_native.strategy_types import Strategy
from r_native import live_indicators as li


def _atr_from_bars(bars, n: int = 14) -> float:
    o, h, l, c = li._ohlc(bars)
    if len(c) < 2:
        return 0.0
    tr = [h[i] - l[i] for i in range(len(c))]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    k = min(n, len(tr))
    return float(np.mean(tr[-k:]))


def _structure_confirm(bars, direction: str) -> tuple[bool, float, str]:
    """Use smc_engine to confirm direction. Returns (confirms, confidence, note).
    confidence 0..100 derived from BOS/CHoCH alignment + OB presence."""
    try:
        from r_native import smc_engine as se
    except Exception:
        try:
            import smc_engine as se
        except Exception:
            return True, 70.0, "smc engine unavailable (neutral pass)"
    snap = se.compute_offline(bars)
    want = "UP" if direction == "LONG" else "DOWN"
    conf = 50.0
    notes = []
    bos = snap.get("last_bos")
    if bos and bos.get("direction") == want:
        conf += 20; notes.append(f"BOS {want}")
    elif bos and bos.get("direction") != want:
        conf -= 20; notes.append(f"BOS opposes ({bos['direction']})")
    ch = snap.get("last_choch")
    if ch and ch.get("direction") == want:
        conf += 10; notes.append(f"CHoCH {want}")
    # Fresh OB on the right side
    if direction == "LONG" and snap.get("fresh_ob_below"):
        conf += 12; notes.append("demand OB below")
    if direction == "SHORT" and snap.get("fresh_ob_above"):
        conf += 12; notes.append("supply OB above")
    # Liquidity sweep reclaim aligning
    sw = snap.get("recent_liq_sweep")
    if sw and sw.get("reclaim"):
        sweep_dir = "LONG" if sw["side"] == "SELL" else "SHORT"
        if sweep_dir == direction:
            conf += 8; notes.append("liquidity sweep reclaim")
    conf = max(0.0, min(100.0, conf))
    return conf >= 50.0, conf, "; ".join(notes) or "no structure events"


def evaluate_entry(strategy: Strategy, bars, *,
                   current_price: Optional[float] = None) -> dict:
    """Return the unified entry decision for one strategy on one symbol's bars.

    {
      decision: "LONG"|"SHORT"|"NONE",
      confluence: {...}, signal: "LONG"|"SHORT"|"NONE",
      structure: {confirms, confidence, note},
      confidence: float,            # final (structure conf, gated by minConf)
      entry, stop, targets:[t1,t2,t3], rr,
      reasons: [str],
    }
    """
    enabled_map = {i.key: i.enabled for i in strategy.indicators}
    inds = li.compute_indicators(bars, enabled=enabled_map)
    signal = li.aggregate_signal(inds)
    conf_info = li.confluence_score(inds)
    reasons = [f"confluence {conf_info['bullish']}↑/{conf_info['bearish']}↓ "
               f"of {conf_info['enabled']} enabled"]

    result = {
        "decision": "NONE", "signal": signal, "confluence": conf_info,
        "structure": {}, "confidence": 0.0,
        "entry": 0.0, "stop": 0.0, "targets": [0.0, 0.0, 0.0],
        "rr": 0.0, "reasons": reasons,
    }

    if signal == "NONE":
        reasons.append("no full indicator confluence -> skip")
        return result

    direction = signal  # LONG or SHORT
    confirms, conf, note = _structure_confirm(bars, direction)
    result["structure"] = {"confirms": confirms, "confidence": round(conf, 1),
                           "note": note}
    result["confidence"] = round(conf, 1)
    reasons.append(f"structure {('confirms' if confirms else 'rejects')} "
                   f"{direction} (conf {conf:.0f}): {note}")

    min_conf = strategy.risk.minConfidence
    if not confirms or conf < min_conf:
        reasons.append(f"confidence {conf:.0f} < min {min_conf:.0f} -> skip")
        return result

    # Both layers agree -> build levels
    o, h, l, c = li._ohlc(bars)
    entry = float(current_price if current_price else c[-1])
    atr = _atr_from_bars(bars, strategy.risk.atrLength) or (entry * 0.001)
    sl_dist = strategy.risk.slAtrMult * atr
    tps = strategy.risk.tpAtrMults
    if direction == "LONG":
        stop = entry - sl_dist
        targets = [entry + m * atr for m in tps]
    else:
        stop = entry + sl_dist
        targets = [entry - m * atr for m in tps]
    rr = abs(targets[-1] - entry) / sl_dist if sl_dist > 0 else 0.0

    result.update({
        "decision": direction, "entry": round(entry, 5),
        "stop": round(stop, 5),
        "targets": [round(t, 5) for t in targets],
        "rr": round(rr, 2),
    })
    reasons.append(f"{direction} entry {entry:.5f} SL {stop:.5f} "
                   f"T1/T2/T3 {targets[0]:.5f}/{targets[1]:.5f}/{targets[2]:.5f} "
                   f"(R:R {rr:.1f})")
    return result
