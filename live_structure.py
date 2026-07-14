"""live_structure.py — قراءة بنية لحظية دقيقة وسريعة (بلا LLM، أجزاء من الثانية).

What chart_read.py does NOT do, this does — fast and precise, every cycle:
  • forming-candle OHLC (open/high/low/close-so-far of the live bar)
  • swing highs / lows (pivots) from recent bars
  • SUPPORT / RESISTANCE accumulation: pivots clustered into levels with a
    TOUCH COUNT (more touches = stronger level) — "تراكم دعم/مقاومة"
  • nearest support & resistance + distance in ATR units
  • a conviction(side) helper: buying near support / selling near resistance
    RAISES conviction; buying INTO resistance / selling INTO support LOWERS it.

Pure stdlib (no numpy/LLM) so it stays sub-millisecond on ~200 bars and never
stalls a 2s scalp loop. Read-only: computes, never trades.
"""
from __future__ import annotations
from typing import Any


def _atr(o, h, l, c, n: int = 14) -> float:
    tr = []
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return sum(tr[-n:]) / min(n, len(tr)) if tr else 0.0


def _pivots(h, l, k: int = 2):
    """Pivot highs/lows: a bar whose high/low is the extreme of its ±k neighbours."""
    hi, lo = [], []
    for i in range(k, len(h) - k):
        if h[i] >= max(h[i - k:i + k + 1]):
            hi.append(h[i])
        if l[i] <= min(l[i - k:i + k + 1]):
            lo.append(l[i])
    return hi, lo


def _cluster(prices: list[float], tol: float) -> list[dict[str, Any]]:
    """Group nearby pivot prices into levels; each level carries a touch count."""
    if not prices or tol <= 0:
        return []
    pts = sorted(prices)
    levels: list[dict[str, Any]] = []
    grp = [pts[0]]
    for p in pts[1:]:
        if p - grp[-1] <= tol:
            grp.append(p)
        else:
            levels.append({"price": sum(grp) / len(grp), "touches": len(grp)})
            grp = [p]
    levels.append({"price": sum(grp) / len(grp), "touches": len(grp)})
    return levels


def read(mt5, symbol: str, tf_const, bars: int = 200) -> dict[str, Any] | None:
    r = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)
    if r is None or len(r) < 30:
        return None
    o = [float(x["open"]) for x in r]; h = [float(x["high"]) for x in r]
    l = [float(x["low"]) for x in r];  c = [float(x["close"]) for x in r]
    price = c[-1]
    atr = _atr(o, h, l, c)
    if atr <= 0:
        atr = (max(h[-20:]) - min(l[-20:])) / 20.0 or 1e-6

    hi, lo = _pivots(h, l)
    levels = _cluster(hi + lo, atr * 0.5)            # cluster within ½·ATR
    res = sorted([lv for lv in levels if lv["price"] > price], key=lambda z: z["price"])
    sup = sorted([lv for lv in levels if lv["price"] < price], key=lambda z: -z["price"])
    nr = res[0] if res else None
    ns = sup[0] if sup else None

    return {
        "symbol": symbol, "price": round(price, 5), "atr": round(atr, 5),
        "forming":     {"o": o[-1], "h": h[-1], "l": l[-1], "c": c[-1]},   # live bar
        "last_closed": {"o": o[-2], "h": h[-2], "l": l[-2], "c": c[-2]},
        "swing_high": round(max(h[-30:]), 5), "swing_low": round(min(l[-30:]), 5),
        "resistance": res[:5], "support": sup[:5],
        "nearest_resistance": nr, "nearest_support": ns,
        "dist_res_atr": round((nr["price"] - price) / atr, 2) if nr else None,
        "dist_sup_atr": round((price - ns["price"]) / atr, 2) if ns else None,
    }


def conviction(struct: dict[str, Any] | None, want: int) -> tuple[float, str]:
    """Conviction delta in ~[-0.3,+0.3] + note, from S/R proximity vs trade side.
    want: +1 BUY, -1 SELL. Touch count weights the level's strength."""
    if not struct:
        return 0.0, "struct?"
    near = 0.6  # within this many ATR = "at" the level
    delta = 0.0; notes = []
    nr, ns = struct.get("nearest_resistance"), struct.get("nearest_support")
    dr, dsx = struct.get("dist_res_atr"), struct.get("dist_sup_atr")

    def w(level):  # stronger (more touches) → bigger effect, capped
        return min(1.0, 0.4 + 0.2 * float(level.get("touches", 1)))

    if want > 0:  # BUY
        if ns and dsx is not None and dsx <= near:
            delta += 0.25 * w(ns); notes.append(f"@دعم×{ns['touches']}")     # buy the bounce
        if nr and dr is not None and dr <= near:
            delta -= 0.25 * w(nr); notes.append(f"تحت مقاومة×{nr['touches']}")  # buying into a wall
    elif want < 0:  # SELL
        if nr and dr is not None and dr <= near:
            delta += 0.25 * w(nr); notes.append(f"@مقاومة×{nr['touches']}")
        if ns and dsx is not None and dsx <= near:
            delta -= 0.25 * w(ns); notes.append(f"فوق دعم×{ns['touches']}")
    return round(max(-0.3, min(0.3, delta)), 3), (" ".join(notes) or "mid-range")
