"""microstructure.py — fast price-action triggers the trader uses for the AGGRESSIVE modes:

  • detect_gap(r)        → fair-value-gap / price-jump (قفزة سعرية). 3-candle imbalance; gaps tend to fill.
  • detect_momentum(r)   → strong one-direction impulse (الغوص مع القفزة) → dive same way, high lot.
  • detect_wick_rev(r)   → liquidity sweep + long rejection wick (ظهور الذيل) → reverse entry.
  • sweep_level(r, dir)  → the swing high/low to place a STOP pending order beyond (أوامر معلقة).

All pure functions over MT5 rate rows (dict-like with open/high/low/close). No MT5 calls, no I/O.
"""
from __future__ import annotations


def _atr(r, n=14):
    t = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
            abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(t[-n:]) / min(n, len(t)) if t else 0.0


def detect_gap(r, k=1.2):
    """Fair-value gap: candle1.high < candle3.low (bullish) or candle1.low > candle3.high (bearish),
    with candle2 the impulse. Returns (dir, size_atr, fill_to) or (0,0,None).
    fill_to = the gap edge price (where price is 'pulled' to refill)."""
    if r is None or len(r) < 4:
        return 0, 0.0, None
    a, b, c = r[-3], r[-2], r[-1]
    atr = _atr(r) or 1e-9
    if a["high"] < c["low"]:                      # bullish FVG (jump up, unfilled gap below)
        gap = c["low"] - a["high"]
        if gap >= k * atr * 0.25:
            return 1, gap / atr, a["high"]
    if a["low"] > c["high"]:                      # bearish FVG (jump down, unfilled gap above)
        gap = a["low"] - c["high"]
        if gap >= k * atr * 0.25:
            return -1, gap / atr, a["low"]
    return 0, 0.0, None


def detect_momentum(r, body_atr=1.1, run=2):
    """One-direction impulse: last `run` candles same colour, last body >= body_atr*ATR.
    Returns (dir, strength) — strength≈body in ATRs (drives the dive lot boost)."""
    if r is None or len(r) < run + 15:
        return 0, 0.0
    atr = _atr(r) or 1e-9
    last = r[-1]
    body = last["close"] - last["open"]
    d = 1 if body > 0 else -1
    if abs(body) < body_atr * atr:
        return 0, 0.0
    for i in range(2, run + 1):                    # confirm a same-direction run (no chop)
        c = r[-i]
        if (c["close"] - c["open"]) * d <= 0:
            return 0, 0.0
    return d, abs(body) / atr


def detect_wick_rev(r, wick_ratio=0.6, lookback=20):
    """Liquidity sweep + rejection wick (the ذيل): last candle pokes BEYOND the prior swing
    high/low (sweeps stops) then closes back inside with a long rejection wick on that side.
    Returns (dir, depth_atr) where dir = REVERSE direction to trade, or (0,0)."""
    if r is None or len(r) < lookback + 3:
        return 0, 0.0
    atr = _atr(r) or 1e-9
    last = r[-1]
    rng = last["high"] - last["low"] or 1e-9
    prior = r[-lookback - 1:-1]
    swing_hi = max(c["high"] for c in prior)
    swing_lo = min(c["low"] for c in prior)
    up_wick = last["high"] - max(last["open"], last["close"])
    dn_wick = min(last["open"], last["close"]) - last["low"]
    # swept the highs then rejected (long upper wick) → REVERSE SHORT
    if last["high"] > swing_hi and up_wick / rng >= wick_ratio and last["close"] < swing_hi:
        return -1, up_wick / atr
    # swept the lows then rejected (long lower wick) → REVERSE LONG
    if last["low"] < swing_lo and dn_wick / rng >= wick_ratio and last["close"] > swing_lo:
        return 1, dn_wick / atr
    return 0, 0.0


def sweep_level(r, direction, lookback=20):
    """Swing extreme to place a STOP pending order beyond, in `direction` (1 buy-stop above, -1 sell-stop below)."""
    if r is None or len(r) < lookback + 1:
        return None
    prior = r[-lookback - 1:-1]
    return max(c["high"] for c in prior) if direction > 0 else min(c["low"] for c in prior)


def opposing_wick(r, position_is_buy, wick_ratio=0.55):
    """For trade MANAGEMENT: a rejection wick AGAINST an open position (lock/exit the dive).
    Returns True if a strong opposite-side rejection wick just printed."""
    if r is None or len(r) < 3:
        return False
    last = r[-1]
    rng = last["high"] - last["low"] or 1e-9
    up_wick = last["high"] - max(last["open"], last["close"])
    dn_wick = min(last["open"], last["close"]) - last["low"]
    return (up_wick / rng >= wick_ratio) if position_is_buy else (dn_wick / rng >= wick_ratio)
