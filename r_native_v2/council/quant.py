"""council/quant.py — indicator-stack agreement check.

Looks at the snapshot's MTF frames and asks:
  • Does M15 trend align with the proposed direction?
  • Is M5 in a retracement (good entry zone)?
  • Does M1 show a confirmation trigger (engulfing, RSI bounce)?
  • Is ATR meaningful (not consolidation noise)?
"""
from __future__ import annotations
from .types import Proposal, Verdict


def quant_review(proposal: Proposal, snapshot, account) -> Verdict:
    p = proposal
    tfs = snapshot.tfs

    m1 = tfs.get("M1"); m5 = tfs.get("M5"); m15 = tfs.get("M15")
    if not (m1 and m5 and m15):
        return Verdict(False, "missing TF frame (M1/M5/M15)", 100)

    side_up = (p.side == "BUY")
    score = 0
    reasons = []

    # 1. M15 trend (the boss)
    if side_up and m15.bias == "UP":   score += 40; reasons.append("M15-UP✓")
    elif side_up and m15.bias == "RANGE": score += 10; reasons.append("M15-RANGE")
    elif side_up and m15.bias == "DOWN":
        return Verdict(False, "M15 DOWN vs BUY proposal — counter-trend", 90)
    elif (not side_up) and m15.bias == "DOWN": score += 40; reasons.append("M15-DOWN✓")
    elif (not side_up) and m15.bias == "RANGE": score += 10; reasons.append("M15-RANGE")
    elif (not side_up) and m15.bias == "UP":
        return Verdict(False, "M15 UP vs SELL proposal — counter-trend", 90)

    # 2. M5 setup quality
    if side_up and m5.last_close < m5.ema9:
        score += 20; reasons.append("M5 below EMA9 (pullback)")
    elif (not side_up) and m5.last_close > m5.ema9:
        score += 20; reasons.append("M5 above EMA9 (pullback)")
    else:
        score += 5

    # 3. M1 trigger
    if side_up and m1.bull_engulf:
        score += 25; reasons.append("M1 bull-engulf✓")
    elif side_up and m1.pin_bot:
        score += 20; reasons.append("M1 bottom-pin✓")
    elif side_up and m1.rsi < 35:
        score += 15; reasons.append(f"M1 RSI {m1.rsi} oversold")
    elif (not side_up) and m1.bear_engulf:
        score += 25; reasons.append("M1 bear-engulf✓")
    elif (not side_up) and m1.pin_top:
        score += 20; reasons.append("M1 top-pin✓")
    elif (not side_up) and m1.rsi > 65:
        score += 15; reasons.append(f"M1 RSI {m1.rsi} overbought")
    else:
        return Verdict(False, "no M1 entry trigger (engulf/pin/extreme RSI)", 80)

    # 4. ATR meaningful — avoid dead-flat consolidation
    if m1.atr < 0.5:    # gold: $0.50 ATR = noise
        return Verdict(False, f"M1 ATR {m1.atr:.2f} too tight — consolidation", 75)

    approve = score >= 60
    return Verdict(approve, f"score={score} · " + " · ".join(reasons), min(score, 100))
