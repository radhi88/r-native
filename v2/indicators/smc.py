"""indicators/smc.py — Smart Money Concepts detection for genomes.

Same logic as live_pulse uses, packaged so any genome can ask
the snapshot: "is this price in a Bear OB? Where's the nearest
BULL FVG? What's the M1 buyer/seller pressure right now?"

User mandate 2026-05-27: codify the discipline of waiting for FVG
retest + watching pressure flip + rejecting marubozu bear into the
genome's DNA — so Claude-Apex (and all genomes after it) won't
chase tops or buy into rejection bars.
"""
from __future__ import annotations
from typing import Optional


# ─── Order Block detection ───
def find_order_block(bars: list, lookback: int = 10) -> Optional[dict]:
    """Last opposite-color bar before a STRONG impulse. Returns dict
    {low, high, type:'BULL_OB'|'BEAR_OB', age_bars}. Only the most
    recent OB within lookback bars."""
    if len(bars) < 5: return None
    for i in range(len(bars) - 2, max(0, len(bars) - lookback - 2), -1):
        cur, nxt = bars[i], bars[i+1]
        cur_bull = cur["close"] > cur["open"]
        nxt_body = abs(nxt["close"] - nxt["open"])
        nxt_rng  = max(nxt["high"] - nxt["low"], 1e-9)
        nxt_bull = nxt["close"] > nxt["open"]
        strong = (nxt_body / nxt_rng) > 0.6
        if strong and cur_bull != nxt_bull:
            return {
                "low":  float(cur["low"]),
                "high": float(cur["high"]),
                "type": "BULL_OB" if nxt_bull else "BEAR_OB",
                "age_bars": len(bars) - 1 - i,
            }
    return None


def price_inside(price: float, zone: Optional[dict]) -> bool:
    if not zone: return False
    return zone["low"] <= price <= zone["high"]


# ─── Fair Value Gap detection ───
def find_fvgs(bars: list, lookback: int = 20) -> tuple[Optional[dict], Optional[dict]]:
    """Return (bull_fvg, bear_fvg) most-recent unfilled. Each is
    {top, bot, gap, age_bars} or None."""
    bull = None; bear = None
    n = min(lookback, len(bars) - 2)
    for i in range(len(bars) - 2, len(bars) - n - 2, -1):
        if i < 1: break
        a, b, c = bars[i-1], bars[i], bars[i+1]
        if bull is None and c["low"] > a["high"]:
            bull = {"top": float(c["low"]), "bot": float(a["high"]),
                     "gap": float(c["low"] - a["high"]),
                     "age_bars": len(bars) - 1 - (i+1)}
        if bear is None and c["high"] < a["low"]:
            bear = {"top": float(a["low"]), "bot": float(c["high"]),
                     "gap": float(a["low"] - c["high"]),
                     "age_bars": len(bars) - 1 - (i+1)}
        if bull and bear: break
    return bull, bear


# ─── Buyer/seller pressure ───
def pressure_score(bars: list, n: int = 10) -> dict:
    """Net body $ of last n closed bars. Positive = bulls dominated.
    Returns {net, bull_total, bear_total, direction, bar_count}."""
    last = bars[-(n+1):-1] if len(bars) > n else bars[:-1]
    bull = sum(b["close"]-b["open"] for b in last if b["close"]>b["open"])
    bear = sum(b["open"]-b["close"] for b in last if b["close"]<b["open"])
    net = bull - bear
    direction = "BUY+" if net > 1.5 else ("SELL+" if net < -1.5 else "FLAT")
    return {"net": round(net, 2), "bull_total": round(bull, 2),
            "bear_total": round(bear, 2), "direction": direction,
            "bar_count": len(last)}


# ─── Marubozu rejection (last N bars) ───
def recent_marubozu_bear(bars: list, lookback: int = 3,
                          body_pct_min: float = 0.80) -> Optional[dict]:
    """Was there a strong bearish marubozu in the last `lookback` bars?
    Returns the bar info if yes — telling Claude-Apex: don't buy into
    that level, sellers just won there."""
    for b in reversed(bars[-lookback-1:-1]):     # exclude forming bar
        body = abs(b["close"] - b["open"])
        rng  = max(b["high"] - b["low"], 1e-9)
        body_pct = body / rng
        bearish = b["close"] < b["open"]
        upper_wick = b["high"] - max(b["open"], b["close"])
        if (bearish and body_pct >= body_pct_min
                and upper_wick / max(body, 1e-9) < 0.20):
            return {
                "close": float(b["close"]),
                "body_pct": round(body_pct, 2),
                "age_bars": list(bars).index(b) if b in list(bars) else -1,
            }
    return None


def recent_marubozu_bull(bars: list, lookback: int = 3,
                          body_pct_min: float = 0.80) -> Optional[dict]:
    for b in reversed(bars[-lookback-1:-1]):
        body = abs(b["close"] - b["open"])
        rng  = max(b["high"] - b["low"], 1e-9)
        body_pct = body / rng
        bullish = b["close"] > b["open"]
        lower_wick = min(b["open"], b["close"]) - b["low"]
        if (bullish and body_pct >= body_pct_min
                and lower_wick / max(body, 1e-9) < 0.20):
            return {"close": float(b["close"]), "body_pct": round(body_pct, 2)}
    return None


# ─── Bar quality (for entry-trigger confirmation) ───
def classify_candle(bar: dict) -> dict:
    """Body-pct + wick analysis. Returns kind label (hammer/star/
    marubozu/doji/normal/strong) + is_bull/is_bear flags."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = abs(c - o); rng = max(h - l, 1e-9)
    upper = h - max(o, c); lower = min(o, c) - l
    body_pct = body / rng
    bullish = c > o
    # Wick-dominant patterns FIRST (otherwise a tiny-body hammer gets
    # mislabeled "doji" — saw this 2026-05-27 on the XAU 08:00 bar:
    # body 4%, upper $0.07, lower $2.04 = clear HAMMER, not doji).
    kind = "neutral"
    if lower >= 2 * max(body, rng * 0.05) and upper < max(body, rng * 0.10):
        kind = "hammer" if bullish or body_pct < 0.15 else "hanging_man"
    elif upper >= 2 * max(body, rng * 0.05) and lower < max(body, rng * 0.10):
        kind = "shooting_star" if not bullish or body_pct < 0.15 else "inverted_hammer"
    elif body_pct < 0.15: kind = "doji"
    elif body_pct >= 0.80:
        kind = "marubozu_bull" if bullish else "marubozu_bear"
    elif body_pct >= 0.60:
        kind = "strong_bull" if bullish else "strong_bear"
    elif body_pct >= 0.30:
        kind = "normal_bull" if bullish else "normal_bear"
    else:
        kind = "small_bull" if bullish else "small_bear"
    return {"kind": kind, "body_pct": round(body_pct*100, 0),
            "is_bull": bullish, "upper": round(upper, 2), "lower": round(lower, 2)}


def is_bullish_engulfing(bars: list) -> bool:
    if len(bars) < 2: return False
    a, b = bars[-2], bars[-1]
    return (a["close"] < a["open"] and b["close"] > b["open"]
             and b["close"] > a["open"] and b["open"] < a["close"])


def is_bearish_engulfing(bars: list) -> bool:
    if len(bars) < 2: return False
    a, b = bars[-2], bars[-1]
    return (a["close"] > a["open"] and b["close"] < b["open"]
             and b["close"] < a["open"] and b["open"] > a["close"])
