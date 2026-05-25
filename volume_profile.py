"""volume_profile.py — J.22 — Order flow / volume profile filter.

MT5 tick_volume per bar is a proxy for real volume. Compute:
- HVN (High Volume Node) — price levels with concentrated activity (support/resistance)
- LVN (Low Volume Node) — price levels with sparse activity (rejection zones)
- POC (Point of Control) — single highest-volume price of session

Trade gate filter: reject entries that fight HVN walls (e.g. BUY into a strong
overhead HVN is asking for rejection).

Usage:
  from r_native.volume_profile import profile_for_session
  vp = profile_for_session("BTCUSDm", session="NYO")
  if hits_hvn_wall(entry, side, vp): skip_trade()
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timezone, timedelta


def profile_for_period(symbol: str, hours: int = 8,
                       price_buckets: int = 50) -> dict:
    """Build a volume profile for the last N hours.

    Returns: {
      "poc":      <price of highest-volume bucket>,
      "hvn":      [<price>, ...]  (top 10% by volume),
      "lvn":      [<price>, ...]  (bottom 10% by volume),
      "bucket_size": <price units>,
      "histogram": [(price_low, price_high, volume), ...]
    }
    """
    try:
        import MetaTrader5 as mt5
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "missing deps"}

    if not mt5.initialize(): return {"ok": False, "error": "mt5 init"}

    # Pull M5 bars for the requested window
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, hours * 12)
    if bars is None or len(bars) < 10:
        return {"ok": False, "error": "no bars"}

    low_all  = min(b["low"]  for b in bars)
    high_all = max(b["high"] for b in bars)
    if high_all <= low_all:
        return {"ok": False, "error": "no range"}

    bucket_size = (high_all - low_all) / price_buckets
    histogram = [0.0] * price_buckets

    for b in bars:
        # Distribute bar's volume across the price range it touched
        low_idx  = min(price_buckets - 1, max(0, int((b["low"]  - low_all) / bucket_size)))
        high_idx = min(price_buckets - 1, max(0, int((b["high"] - low_all) / bucket_size)))
        n_buckets = max(1, high_idx - low_idx + 1)
        per_bucket = (b["tick_volume"]) / n_buckets
        for i in range(low_idx, high_idx + 1):
            histogram[i] += per_bucket

    # POC = highest bucket
    poc_idx = histogram.index(max(histogram))
    poc_price = low_all + (poc_idx + 0.5) * bucket_size

    # HVN: top 10% buckets by volume
    sorted_idx = sorted(range(price_buckets), key=lambda i: -histogram[i])
    hvn_count = max(1, price_buckets // 10)
    hvn_prices = sorted([low_all + (i + 0.5) * bucket_size
                          for i in sorted_idx[:hvn_count]])
    # LVN: bottom 20% but excluding the extreme tails (which have no activity)
    nonzero = [i for i in range(price_buckets) if histogram[i] > 0]
    if nonzero:
        cutoff = sorted([histogram[i] for i in nonzero])[len(nonzero) // 5]
        lvn_prices = sorted([low_all + (i + 0.5) * bucket_size
                              for i in nonzero if histogram[i] <= cutoff])
    else:
        lvn_prices = []

    return {
        "ok":          True,
        "symbol":      symbol,
        "hours":       hours,
        "poc":         round(poc_price, 5),
        "hvn":         [round(p, 5) for p in hvn_prices],
        "lvn":         [round(p, 5) for p in lvn_prices],
        "bucket_size": round(bucket_size, 5),
        "low":         round(low_all, 5),
        "high":        round(high_all, 5),
        "histogram":   [{"price_low":  round(low_all + i * bucket_size, 5),
                          "price_high": round(low_all + (i + 1) * bucket_size, 5),
                          "volume":     round(histogram[i], 1)}
                         for i in range(price_buckets)],
    }


def hits_hvn_wall(entry: float, side: str, vp: dict,
                  proximity_atr: float = 0.5, atr_value: float = None) -> dict:
    """Check if an entry would slam into a HVN within `proximity_atr × ATR`.

    Args:
        entry:        proposed entry price
        side:         "BUY" or "SELL"
        vp:           output of profile_for_period
        proximity_atr: how close (in ATRs) to consider a wall blocking
        atr_value:    current ATR (price units)

    Returns: {"blocked": bool, "wall_price": float|None, "distance": float|None}
    """
    if not vp.get("ok") or not vp.get("hvn"): return {"blocked": False}
    if not atr_value: atr_value = vp.get("bucket_size", 0.01) * 3
    threshold = atr_value * proximity_atr

    # For BUY: walls above us are bad. For SELL: walls below us are bad.
    walls = [h for h in vp["hvn"] if
             (side == "BUY" and entry < h < entry + threshold) or
             (side == "SELL" and entry - threshold < h < entry)]
    if not walls:
        return {"blocked": False, "wall_price": None, "distance": None}
    closest = min(walls, key=lambda w: abs(w - entry))
    return {
        "blocked":    True,
        "wall_price": closest,
        "distance":   round(abs(closest - entry), 5),
        "reason":     f"HVN wall at {closest:.5f} ({abs(closest-entry):.5f} from entry)",
    }


def session_str_to_hours(session: str) -> int:
    return {"TO": 4, "LO": 4, "NYO": 4, "Tokyo": 9, "London": 9, "NY": 9,
            "Any": 24}.get(session, 8)


# ───────────────────────────────────────────────────────────────────────
# Value Area + nPOC extensions (consumed by genome signal helpers below)
# ───────────────────────────────────────────────────────────────────────

import time as _time
_VP_CACHE_EXT: dict = {}    # {(sym, hours): (ts, extended_vp)}
_CACHE_TTL_S = 300


def extended_profile(symbol: str, hours: int = 24, price_buckets: int = 40) -> dict:
    """Extend profile_for_period with VAH/VAL (70% value area) + nPOC detection.
    Cached 5 min per (symbol, hours)."""
    now = _time.time()
    key = (symbol, hours)
    cached = _VP_CACHE_EXT.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]

    base = profile_for_period(symbol, hours=hours, price_buckets=price_buckets)
    if not base.get("ok"):
        return base

    histogram = base.get("histogram") or []
    if not histogram:
        return base

    # Compute Value Area: grow out from POC until cumulative volume ≥ 70% of total
    volumes = [h["volume"] for h in histogram]
    total = sum(volumes) or 1
    target = total * 0.70
    poc_idx = volumes.index(max(volumes))
    va_set = {poc_idx}
    accum = volumes[poc_idx]
    lo, hi = poc_idx, poc_idx
    n = len(volumes)
    while accum < target and (lo > 0 or hi < n - 1):
        lo_v = volumes[lo - 1] if lo > 0 else -1
        hi_v = volumes[hi + 1] if hi < n - 1 else -1
        if hi_v >= lo_v and hi < n - 1:
            hi += 1; va_set.add(hi); accum += volumes[hi]
        elif lo > 0:
            lo -= 1; va_set.add(lo); accum += volumes[lo]
        else:
            break
    vah = histogram[hi]["price_high"]
    val = histogram[lo]["price_low"]

    # nPOC: split lookback in half, find POC of older half, check if recent
    # price range revisited it
    npoc: list = []
    try:
        import MetaTrader5 as mt5
        bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, hours * 12)
        if bars is not None and len(bars) >= 40:
            mid = len(bars) // 2
            old_low  = min(b["low"]  for b in bars[:mid])
            old_high = max(b["high"] for b in bars[:mid])
            if old_high > old_low:
                old_bucket = (old_high - old_low) / price_buckets
                old_hist = [0.0] * price_buckets
                for b in bars[:mid]:
                    lo_i = min(price_buckets - 1, max(0, int((b["low"]  - old_low) / old_bucket)))
                    hi_i = min(price_buckets - 1, max(0, int((b["high"] - old_low) / old_bucket)))
                    nb = max(1, hi_i - lo_i + 1)
                    for i in range(lo_i, hi_i + 1):
                        old_hist[i] += b["tick_volume"] / nb
                old_poc = old_low + (old_hist.index(max(old_hist)) + 0.5) * old_bucket
                recent_lo = min(b["low"]  for b in bars[mid:])
                recent_hi = max(b["high"] for b in bars[mid:])
                if not (recent_lo <= old_poc <= recent_hi):
                    npoc.append(round(old_poc, 5))
    except Exception: pass

    out = {
        **base,
        "vah":  round(vah, 5),
        "val":  round(val, 5),
        "npoc": npoc,
    }
    _VP_CACHE_EXT[key] = (now, out)
    return out


# ───────────────────────────────────────────────────────────────────────
# Signal helpers — return (vote, reason) for genome_signal.py
# ───────────────────────────────────────────────────────────────────────

def _within(price, level, tol=0.0008):
    if not price or not level: return False
    return abs(price - level) / level < tol


def _snap_price(snap):
    return (snap.get("bid")
            or (snap.get("h1") or {}).get("current")
            or 0)


def _snap_symbol(snap):
    # snap may carry symbol directly OR via h1.symbol — pull from anywhere
    return snap.get("symbol") or (snap.get("h1") or {}).get("symbol")


def vp_signal_poc_bounce(snap: dict) -> tuple[int, str]:
    """+1 BUY when price bounces off POC from below (with up slope).
    -1 SELL when price rejects POC from above (with down slope)."""
    sym = _snap_symbol(snap); bid = _snap_price(snap)
    if not (sym and bid): return 0, "no price"
    vp = extended_profile(sym)
    if not vp.get("ok"): return 0, "vp unavailable"
    poc = vp.get("poc")
    if not poc or not _within(bid, poc, 0.0010):
        return 0, f"not near POC"
    slope = (snap.get("h1") or {}).get("slope_atr", 0) or 0
    if slope > 0.3:  return +1, f"POC bounce BUY @ {poc} (slope +{slope:.2f})"
    if slope < -0.3: return -1, f"POC reject SELL @ {poc} (slope {slope:.2f})"
    return 0, "POC touch but flat slope"


def vp_signal_vah_resist(snap: dict) -> tuple[int, str]:
    """-1 SELL when price tests the upper value-area boundary."""
    sym = _snap_symbol(snap); bid = _snap_price(snap)
    if not (sym and bid): return 0, "no price"
    vp = extended_profile(sym)
    if not vp.get("ok"): return 0, "vp unavailable"
    vah = vp.get("vah")
    if vah and _within(bid, vah, 0.0012):
        return -1, f"at VAH resistance {vah}"
    return 0, ""


def vp_signal_val_support(snap: dict) -> tuple[int, str]:
    """+1 BUY when price tests the lower value-area boundary."""
    sym = _snap_symbol(snap); bid = _snap_price(snap)
    if not (sym and bid): return 0, "no price"
    vp = extended_profile(sym)
    if not vp.get("ok"): return 0, "vp unavailable"
    val = vp.get("val")
    if val and _within(bid, val, 0.0012):
        return +1, f"at VAL support {val}"
    return 0, ""


def vp_signal_lvn_breakout(snap: dict) -> tuple[int, str]:
    """±1 when price enters a low-volume node — expect fast directional move."""
    sym = _snap_symbol(snap); bid = _snap_price(snap)
    if not (sym and bid): return 0, "no price"
    vp = extended_profile(sym)
    if not vp.get("ok"): return 0, "vp unavailable"
    for lvn in (vp.get("lvn") or []):
        if _within(bid, lvn, 0.0008):
            slope = (snap.get("h1") or {}).get("slope_atr", 0) or 0
            if slope > 0.5:  return +1, f"LVN breakout BUY through {lvn}"
            if slope < -0.5: return -1, f"LVN breakout SELL through {lvn}"
    return 0, ""


def vp_signal_npoc_magnet(snap: dict) -> tuple[int, str]:
    """Directional bias toward unfilled prior POC (price-magnet behavior)."""
    sym = _snap_symbol(snap); bid = _snap_price(snap)
    if not (sym and bid): return 0, "no price"
    vp = extended_profile(sym)
    if not vp.get("ok"): return 0, "vp unavailable"
    npocs = vp.get("npoc") or []
    if not npocs: return 0, "no naked POC"
    target = npocs[0]
    dist_pct = (target - bid) / bid
    if abs(dist_pct) < 0.003: return 0, "naked POC too close"
    return (+1, f"naked POC magnet UP → {target}") if dist_pct > 0 \
           else (-1, f"naked POC magnet DOWN → {target}")
