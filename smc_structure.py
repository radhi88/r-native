"""smc_structure.py — ICT/SMC structure detectors from the user's video (@CYBORG_JD reel):
CISD (Change in State of Delivery), CHoCH (Change of Character), IFVG (Inverse Fair Value Gap).

Built to TEST the video's claims honestly: each returns a directional vote (-1/0/+1) computed
causally (no lookahead) on close/high/low arrays, then its REAL per-symbol hit-rate is measured
OOS like every other indicator — the learned weighting promotes it if it works, buries it if the
video was hindsight. NOTE: candle "open" is approximated by the previous close (vote engines don't
carry opens); fine for continuous markets, stated honestly.
"""
from __future__ import annotations


def _color(close, i):
    """+1 bullish / -1 bearish candle (open ≈ prev close)."""
    if i <= 0:
        return 0
    d = close[i] - close[i - 1]
    return 1 if d > 0 else -1 if d < 0 else 0


def cisd(close, high, low, max_leg=8):
    """Change in State of Delivery: a final same-color delivery leg, then a CLOSE beyond the
    leg's origin → state flips. Bearish CISD (vote -1): final up-leg, close < leg origin.
    Bullish CISD (vote +1): final down-leg, close > leg origin."""
    n = len(close)
    if n < max_leg + 4:
        return 0
    i = n - 2                                  # the leg ends on the bar BEFORE current
    c0 = _color(close, i)
    if c0 == 0:
        return 0
    start = i
    while start - 1 > 0 and _color(close, start - 1) == c0 and (i - start) < max_leg:
        start -= 1
    if (i - start) + 1 < 2:                    # need a real leg (>=2 candles)
        return 0
    origin = close[start - 1]                  # leg origin ≈ open of first leg candle
    cur = close[-1]
    if c0 > 0 and cur < origin:                # up-delivery broken → bearish flip
        return -1
    if c0 < 0 and cur > origin:                # down-delivery broken → bullish flip
        return 1
    return 0


def _pivots(high, low, w=3):
    """Swing highs/lows (confirmed only — pivot needs w bars on both sides → causal lag)."""
    ph, pl = [], []
    for i in range(w, len(high) - w):
        seg_h = high[i - w:i + w + 1]; seg_l = low[i - w:i + w + 1]
        if high[i] == max(seg_h):
            ph.append((i, high[i]))
        if low[i] == min(seg_l):
            pl.append((i, low[i]))
    return ph, pl


def choch(close, high, low, lookback=50):
    """Change of Character: in an up-structure (ascending swing highs), a CLOSE below the most
    recent confirmed swing low → vote -1. Mirror for down-structure → vote +1."""
    n = len(close)
    if n < lookback:
        return 0
    h = high[-lookback:]; l = low[-lookback:]; c = close[-1]
    ph, pl = _pivots(h, l, 3)
    if len(ph) < 2 or len(pl) < 2:
        return 0
    up_struct = ph[-1][1] > ph[-2][1]          # higher highs
    dn_struct = pl[-1][1] < pl[-2][1]          # lower lows
    if up_struct and c < pl[-1][1]:            # broke last higher-low → character changed DOWN
        return -1
    if dn_struct and c > ph[-1][1]:            # broke last lower-high → character changed UP
        return 1
    return 0


def ifvg(close, high, low, lookback=40):
    """Inverse FVG: the most recent FVG that price CLOSED through flips its role; when price
    trades back into the violated zone, expect rejection in the breakout's direction."""
    n = len(close)
    if n < lookback + 3:
        return 0
    cur = close[-1]
    for i in range(n - 3, max(2, n - lookback), -1):
        lo_b, hi_b = None, None; bull = None
        if high[i - 2] < low[i]:               # bullish FVG (gap up)
            lo_b, hi_b, bull = high[i - 2], low[i], True
        elif low[i - 2] > high[i]:             # bearish FVG (gap down)
            lo_b, hi_b, bull = high[i], low[i - 2], False
        else:
            continue
        post = close[i + 1:]
        if bull and any(x < lo_b for x in post):       # bullish gap VIOLATED → now resistance
            if lo_b <= cur <= hi_b:
                return -1
            continue                                    # هذه الفجوة انتُهكت لكن السعر خارجها → افحص أقدم
        if (not bull) and any(x > hi_b for x in post):  # bearish gap VIOLATED → now support
            if lo_b <= cur <= hi_b:
                return 1
            continue
        continue                                        # فجوة لم تُنتهك بعد → افحص أقدم (كان return 0 يقتل الحلقة)
    return 0
