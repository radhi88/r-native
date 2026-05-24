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
