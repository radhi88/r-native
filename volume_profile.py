"""volume_profile.py — POC / VAH / VAL (Volume Profile) for the chart + gene.

POC  = Point of Control: price level with the most traded (tick) volume — the magnet.
VAH  = Value Area High  : top of the 70% value area around POC.
VAL  = Value Area Low   : bottom of the 70% value area.

Method (standard): bin the lookback range into `bins`, distribute each bar's
tick_volume across [low, high], find the POC bin, then expand up/down from POC
adding the larger-neighbour bin until 70% of total volume is enclosed → VAH/VAL.

Used by:
  • the dashboard (draws POC/VAH/VAL rays) — see /api/chart
  • the gap gene (confluence: sell from VAH toward POC/VAL/gap)
"""
from __future__ import annotations


def compute_profile(rates, bins: int = 50, value_area: float = 0.70) -> dict:
    """rates: MT5 rates array (struct with high/low/tick_volume). Returns POC/VAH/VAL."""
    import numpy as np
    if rates is None or len(rates) < 10:
        return {}
    high = np.array([float(r["high"]) for r in rates])
    low = np.array([float(r["low"]) for r in rates])
    vol = np.array([float(r["tick_volume"]) for r in rates])
    lo, hi = float(low.min()), float(high.max())
    if hi <= lo:
        return {}
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    hist = np.zeros(bins)
    # distribute each bar's volume evenly across the bins its range spans
    for h, l, v in zip(high, low, vol):
        b0 = max(0, int((l - lo) / (hi - lo) * bins) if hi > lo else 0)
        b1 = min(bins - 1, int((h - lo) / (hi - lo) * bins) if hi > lo else 0)
        span = max(1, b1 - b0 + 1)
        hist[b0:b1 + 1] += v / span
    total = hist.sum()
    if total <= 0:
        return {}
    poc_i = int(np.argmax(hist))
    # expand value area from POC
    lo_i = hi_i = poc_i
    acc = hist[poc_i]
    target = total * value_area
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        up = hist[hi_i + 1] if hi_i < bins - 1 else -1
        dn = hist[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1; acc += max(up, 0)
        else:
            lo_i -= 1; acc += max(dn, 0)
    digits = 5
    return {
        "poc": round(float(centers[poc_i]), digits),
        "vah": round(float(centers[hi_i]), digits),
        "val": round(float(centers[lo_i]), digits),
        "range_high": round(hi, digits), "range_low": round(lo, digits),
        "bins": bins, "value_area": value_area, "n_bars": len(rates),
    }


def profile_for(symbol: str, timeframe="M15", n_bars: int = 150) -> dict:
    """Convenience: pull bars from MT5 and compute the profile."""
    import MetaTrader5 as mt5
    TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
          "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    own = not mt5.initialize()
    r = mt5.copy_rates_from_pos(symbol, TF.get(timeframe, mt5.TIMEFRAME_M15), 0, n_bars)
    return compute_profile(r)


if __name__ == "__main__":
    import sys, json
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M15"
    import MetaTrader5 as mt5
    mt5.initialize()
    print(json.dumps(profile_for(sym, tf), ensure_ascii=False))
    mt5.shutdown()
