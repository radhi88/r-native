"""shared/footprint_features.py — Deep order-flow features from CLAUDE_FOOTPRINT_v4.

Born 2026-05-28: "ج — نستغل المؤشر اللي بنيناه أكثر".

CLAUDE_FOOTPRINT_v4.mq5 exports rich order-flow data to
<Common>/Files/footprint_cells.json:
  cum_delta · svp_poc (Point of Control) · svp_vah/val (Value Area)
  · signal_value (-100..+100) · sd_zones (supply/demand) · per-bar delta.

This distills them into normalized ML features the brain attaches and
ml_clone learns from:

  fp_cum_delta      — net aggressor flow, normalized (sellers vs buyers)
  fp_poc_dist       — distance from price to POC / ATR (mean-reversion pull)
  fp_va_position    — +1 above VAH (rich), -1 below VAL (cheap), 0 inside
  fp_signal         — the footprint's own signal (-1..+1)
  fp_delta_div      — price↑ but delta↓ (bearish) / price↓ delta↑ (bullish): ±1
  fp_supply_prox    — proximity to nearest supply zone (sell pressure)
  fp_demand_prox    — proximity to nearest demand zone (buy pressure)
"""
from __future__ import annotations
import json
import time
from pathlib import Path

CELLS = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files\footprint_cells.json")
MAX_AGE_S = 300          # ignore footprint older than 5 min
_CACHE: dict = {}
_CACHE_TS = 0.0


def _load() -> dict | None:
    if not CELLS.exists():
        return None
    try:
        age = time.time() - CELLS.stat().st_mtime
        if age > MAX_AGE_S:
            return None
        return json.loads(CELLS.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def footprint_features(price: float, atr: float) -> dict:
    """Compute normalized footprint features for the current price. Cached 5s."""
    global _CACHE, _CACHE_TS
    now = time.time()
    if now - _CACHE_TS < 5.0 and _CACHE:
        return _CACHE
    d = _load()
    out = {
        "fp_cum_delta": 0.0, "fp_poc_dist": 0.0, "fp_va_position": 0.0,
        "fp_signal": 0.0, "fp_delta_div": 0.0,
        "fp_supply_prox": 0.0, "fp_demand_prox": 0.0, "fp_fresh": 0.0,
    }
    if not d:
        _CACHE = out; _CACHE_TS = now
        return out
    out["fp_fresh"] = 1.0
    atr = atr or 1.0

    # cumulative delta — clamp ±50k → ±1
    out["fp_cum_delta"] = max(-1.0, min(1.0, float(d.get("cum_delta") or 0) / 50000.0))

    # POC distance (signed): price - POC, in ATR units. >0 = above POC.
    poc = d.get("svp_poc")
    if poc and price:
        out["fp_poc_dist"] = max(-3.0, min(3.0, (price - poc) / atr)) / 3.0

    # Value-area position
    vah, val = d.get("svp_vah"), d.get("svp_val")
    if vah and val and price:
        if price > vah:   out["fp_va_position"] = 1.0
        elif price < val: out["fp_va_position"] = -1.0
        else:             out["fp_va_position"] = 0.0

    # Footprint's own signal (-100..+100 → -1..+1)
    out["fp_signal"] = max(-1.0, min(1.0, float(d.get("signal_value") or 0) / 100.0))

    # Delta divergence from per-bar data: last 3 bars price change vs delta sum sign
    bars = d.get("bars") or []
    if len(bars) >= 3:
        last3 = bars[-3:]
        try:
            price_chg = last3[-1]["c"] - last3[0]["o"]
            delta_sum = sum(b.get("delta", b.get("d", 0)) or 0 for b in last3)
            if price_chg > 0 and delta_sum < 0:   out["fp_delta_div"] = -1.0  # bearish div
            elif price_chg < 0 and delta_sum > 0: out["fp_delta_div"] = 1.0   # bullish div
        except Exception:
            pass

    # Supply/demand zone proximity
    zones = d.get("sd_zones") or []
    sup_d, dem_d = 9e9, 9e9
    for z in zones:
        try:
            mid = (z.get("top", 0) + z.get("bot", 0)) / 2
            dist = abs(price - mid)
            if z.get("is_supply"):
                sup_d = min(sup_d, dist)
            else:
                dem_d = min(dem_d, dist)
        except Exception:
            continue
    if sup_d < 9e9: out["fp_supply_prox"] = max(0.0, 1.0 - sup_d / (atr * 3))
    if dem_d < 9e9: out["fp_demand_prox"] = max(0.0, 1.0 - dem_d / (atr * 3))

    _CACHE = out; _CACHE_TS = now
    return out


FP_KEYS = ["fp_cum_delta", "fp_poc_dist", "fp_va_position", "fp_signal",
           "fp_delta_div", "fp_supply_prox", "fp_demand_prox"]

__all__ = ["footprint_features", "FP_KEYS"]
