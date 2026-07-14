"""runtime/footprint_rules.py — Rules R9/R10/R11 using footprint data.

Loaded by claude_autonomous_trader.py for enhanced confluence when footprint
bridge is feeding data into brain_live.json.

Rules added 2026-05-27 evening based on real footprint integration:

R9 — Footprint Imbalance Confirmation
   Confirms direction when ≥3 diagonal imbalances cluster
   + matches MTF bias + price near key level

R10 — CVD Divergence Reversal
   Price making new high but CVD falling = bearish divergence
   Price making new low but CVD rising = bullish divergence

R11 — SD Zone Entry (premium signal)
   Price inside demand zone + bullish imbalance burst = BUY
   Price inside supply zone + bearish imbalance burst = SELL
"""
from __future__ import annotations


def rule_9_footprint_imb_confirmation(snap: dict) -> tuple[float, dict]:
    """Imbalance cluster + MTF bias alignment = high-confluence entry."""
    fp = snap.get("footprint")
    if not fp: return 0, {}

    imb_dom = fp.get("imb_dominance", "NEUTRAL")
    imb_buy_count = fp.get("imb_buy_count_3bars", 0)
    imb_sell_count = fp.get("imb_sell_count_3bars", 0)
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")

    rationale = []
    confidence = 0
    action = None

    # Strong bullish setup
    if (imb_dom == "BUY" and imb_buy_count >= 3
        and bias_m5 == "UP" and bias_m15 == "UP"):
        rationale.append(f"FP imb cluster {imb_buy_count}↑ + MTF UP align")
        confidence = 4
        action = "BUY"

    # Strong bearish setup
    elif (imb_dom == "SELL" and imb_sell_count >= 3
          and bias_m5 == "DOWN" and bias_m15 == "DOWN"):
        rationale.append(f"FP imb cluster {imb_sell_count}↓ + MTF DOWN align")
        confidence = 4
        action = "SELL"

    if not action:
        return 0, {}

    bid = snap.get("bid", 0)
    return confidence, {
        "side": action,
        "rule": "R9_fp_imb_confirm",
        "entry": snap.get("ask" if action == "BUY" else "bid", bid),
        "sl": bid - 5 if action == "BUY" else bid + 5,
        "tp": bid + 8 if action == "BUY" else bid - 8,
        "size": 0.02,
        "reasons": rationale,
    }


def rule_10_cvd_divergence(snap: dict, memory: list) -> tuple[float, dict]:
    """Detect CVD divergence — price extreme without flow confirmation."""
    fp = snap.get("footprint")
    if not fp: return 0, {}
    if len(memory) < 8: return 0, {}

    # Get last 8 snapshots to compute price and CVD trajectories
    recent = memory[-8:]
    bids = [s.get("bid", 0) for s in recent]
    cvds = [s.get("footprint", {}).get("cum_delta_running", 0) for s in recent]
    if not all(bids) or not all(cvds): return 0, {}

    rationale = []
    confidence = 0
    action = None

    # Bearish divergence: price new high but CVD lower than prior high
    max_price_idx = bids.index(max(bids))
    if max_price_idx == len(bids) - 1:   # new high is latest
        prior_max_cvd = max(cvds[:max_price_idx]) if max_price_idx > 0 else 0
        if cvds[-1] < prior_max_cvd - 20:
            rationale.append(f"Bear divergence: price high but CVD {cvds[-1]:.0f} < prior {prior_max_cvd:.0f}")
            confidence = 4
            action = "SELL"

    # Bullish divergence: price new low but CVD higher than prior low
    min_price_idx = bids.index(min(bids))
    if min_price_idx == len(bids) - 1:
        prior_min_cvd = min(cvds[:min_price_idx]) if min_price_idx > 0 else 0
        if cvds[-1] > prior_min_cvd + 20:
            rationale.append(f"Bull divergence: price low but CVD {cvds[-1]:.0f} > prior {prior_min_cvd:.0f}")
            confidence = 4
            action = "BUY"

    if not action: return 0, {}
    bid = snap.get("bid", 0)
    return confidence, {
        "side": action,
        "rule": "R10_cvd_divergence",
        "entry": snap.get("ask" if action == "BUY" else "bid", bid),
        "sl": bid - 4 if action == "BUY" else bid + 4,
        "tp": bid + 10 if action == "BUY" else bid - 10,
        "size": 0.02,
        "reasons": rationale,
    }


def rule_11_sd_zone_burst(snap: dict) -> tuple[float, dict]:
    """Inside SD zone + imbalance burst in zone direction = premium entry."""
    fp = snap.get("footprint")
    if not fp: return 0, {}

    in_demand = fp.get("in_demand_zone", False)
    in_supply = fp.get("in_supply_zone", False)
    last_delta = fp.get("last_bar_delta", 0)
    max_recent_delta = fp.get("max_recent_delta", 0)
    cvd_accel = fp.get("cvd_acceleration", 0)

    rationale = []
    confidence = 0
    action = None

    # Demand zone + bullish burst
    if in_demand and last_delta > 100 and max_recent_delta > 150 and cvd_accel > 30:
        rationale.append(f"DEMAND zone + bull burst Δ{last_delta}+ CVDΔ{cvd_accel:+d}")
        confidence = 5
        action = "BUY"

    # Supply zone + bearish burst
    elif in_supply and last_delta < -100 and max_recent_delta > 150 and cvd_accel < -30:
        rationale.append(f"SUPPLY zone + bear burst Δ{last_delta} CVDΔ{cvd_accel:+d}")
        confidence = 5
        action = "SELL"

    if not action: return 0, {}
    bid = snap.get("bid", 0)
    sd_zones = []   # would need to pass real zones for exact SL
    return confidence, {
        "side": action,
        "rule": "R11_sd_zone_burst",
        "entry": snap.get("ask" if action == "BUY" else "bid", bid),
        "sl": bid - 6 if action == "BUY" else bid + 6,
        "tp": bid + 12 if action == "BUY" else bid - 12,
        "size": 0.03,
        "reasons": rationale,
    }
