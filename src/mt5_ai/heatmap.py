"""
heatmap.py — Volume Profile + SMC Book Map data for the web UI.

Returns JSON-ready dicts for Canvas rendering:
  - volume_profile : price levels with volume intensity (Heat Map)
  - ob_zones       : Order Block zones (Book Map)
  - fvg_zones      : Fair Value Gaps
  - liquidity      : Swing highs/lows with sweep count
  - current_price  : latest close
"""

import numpy as np
import pandas as pd


def _round_price(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)


def volume_profile(df: pd.DataFrame, bins: int = 80, lookback: int = 300) -> list[dict]:
    """
    Divide the price range into `bins` equal buckets and sum tick_volume
    for each candle whose midpoint falls in that bucket.
    Returns list sorted by price ascending, each item:
        {price, volume, intensity}   intensity ∈ [0.0, 1.0]
    """
    tail = df.tail(lookback).copy()
    lo = tail["low"].min()
    hi = tail["high"].max()
    if hi <= lo:
        return []

    tick = (hi - lo) / bins
    edges = np.linspace(lo, hi, bins + 1)
    buckets = np.zeros(bins, dtype=float)

    mids = (tail["high"].values + tail["low"].values) / 2
    vols = tail["volume"].values

    for mid, vol in zip(mids, vols):
        idx = int((mid - lo) / tick)
        idx = max(0, min(bins - 1, idx))
        buckets[idx] += vol

    max_vol = buckets.max() or 1.0
    result = []
    for i in range(bins):
        result.append({
            "price":     round(float(edges[i] + tick / 2), 3),
            "volume":    float(buckets[i]),
            "intensity": float(buckets[i] / max_vol),
        })
    return result


def ob_zones(df: pd.DataFrame) -> list[dict]:
    """Extract the most recent active OB zones."""
    zones = []
    last = df.iloc[-1]

    bull_lo = last.get("bullish_ob_low", float("nan"))
    bull_hi = last.get("bullish_ob_high", float("nan"))
    bear_lo = last.get("bearish_ob_low", float("nan"))
    bear_hi = last.get("bearish_ob_high", float("nan"))

    if not (np.isnan(bull_lo) or np.isnan(bull_hi)):
        zones.append({"type": "bull_ob", "low": round(float(bull_lo), 3),
                      "high": round(float(bull_hi), 3), "label": "Demand OB"})
    if not (np.isnan(bear_lo) or np.isnan(bear_hi)):
        zones.append({"type": "bear_ob", "low": round(float(bear_lo), 3),
                      "high": round(float(bear_hi), 3), "label": "Supply OB"})
    return zones


def fvg_zones(df: pd.DataFrame, lookback: int = 50) -> list[dict]:
    """Collect open FVG gaps from the last `lookback` bars."""
    tail = df.tail(lookback)
    zones = []
    current = float(df["close"].iloc[-1])

    for i, row in tail.iterrows():
        if row.get("bullish_fvg", 0) == 1:
            fvg_lo = float(row["high"]) if "high" in row else 0
            fvg_hi = float(df.loc[i - 2, "low"]) if (i - 2) in df.index else 0
            if fvg_lo and fvg_hi and fvg_hi > fvg_lo:
                zones.append({
                    "type": "bull_fvg",
                    "low": round(fvg_lo, 3),
                    "high": round(fvg_hi, 3),
                    "filled": current < fvg_lo,
                    "label": "Bull FVG",
                })
        if row.get("bearish_fvg", 0) == 1:
            fvg_hi = float(row["low"]) if "low" in row else 0
            fvg_lo = float(df.loc[i - 2, "high"]) if (i - 2) in df.index else 0
            if fvg_lo and fvg_hi and fvg_hi > fvg_lo:
                zones.append({
                    "type": "bear_fvg",
                    "low": round(fvg_lo, 3),
                    "high": round(fvg_hi, 3),
                    "filled": current > fvg_hi,
                    "label": "Bear FVG",
                })

    return zones[-10:]  # last 10 gaps only


def liquidity_levels(df: pd.DataFrame) -> list[dict]:
    """Return key liquidity pools: swing highs/lows + sweep flags."""
    last = df.iloc[-1]
    levels = []

    liq_hi = last.get("liquidity_high", float("nan"))
    liq_lo = last.get("liquidity_low",  float("nan"))
    swh    = last.get("prev_swing_high", float("nan"))
    swl    = last.get("prev_swing_low",  float("nan"))

    if not np.isnan(liq_hi):
        levels.append({"type": "buy_side_liq", "price": round(float(liq_hi), 3),
                        "label": "Buy-Side Liq", "swept": bool(last.get("buy_side_liquidity_sweep", 0))})
    if not np.isnan(liq_lo):
        levels.append({"type": "sell_side_liq", "price": round(float(liq_lo), 3),
                        "label": "Sell-Side Liq", "swept": bool(last.get("sell_side_liquidity_sweep", 0))})
    if not np.isnan(swh):
        levels.append({"type": "swing_high", "price": round(float(swh), 3),
                        "label": "Swing High", "swept": False})
    if not np.isnan(swl):
        levels.append({"type": "swing_low", "price": round(float(swl), 3),
                        "label": "Swing Low", "swept": False})
    return levels


def build_heatmap_payload(df: pd.DataFrame, bins: int = 80, lookback: int = 300) -> dict:
    """
    Master function — returns everything the frontend needs in one call.
    `df` must already have market structure columns (from add_market_structure).
    """
    last = df.iloc[-1]
    atr  = float(last.get("atr", 0)) * float(last.get("close", 1))  # atr is stored as pct

    return {
        "current_price":  round(float(last["close"]), 3),
        "atr_points":     round(atr, 3),
        "volume_profile": volume_profile(df, bins=bins, lookback=lookback),
        "ob_zones":       ob_zones(df),
        "fvg_zones":      fvg_zones(df),
        "liquidity":      liquidity_levels(df),
        "bias":           int(last.get("smc_bias", 0)) if "smc_bias" in last.index else 0,
    }
