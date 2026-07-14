"""
friday_fractals.py — Bill Williams Fractal engine for XAUUSDm M1.

Fractal rule (5-bar pattern):
  UP   fractal: bar[i].high > bar[i-2].high and bar[i].high > bar[i-1].high
                and bar[i].high > bar[i+1].high and bar[i].high > bar[i+2].high
  DOWN fractal: bar[i].low  < bar[i-2].low  and bar[i].low  < bar[i-1].low
                and bar[i].low  < bar[i+1].low  and bar[i].low  < bar[i+2].low

A fractal is "broken" when price closes beyond it on a subsequent bar.

Output: friday_fractals.json (written every 5 s)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import MetaTrader5 as mt5
import numpy as np

ROOT       = Path(r"C:\Users\Radhi\MT5")
OUTPUT     = ROOT / "friday_fractals.json"
SYMBOL     = "XAUUSDm"
TF         = mt5.TIMEFRAME_M1
BARS_BACK  = 200
KEEP       = 30          # fractals to keep in JSON
UPDATE_S   = 5


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class FractalPoint(TypedDict):
    time:   str    # ISO-8601 UTC
    price:  float
    type:   str    # "UP" | "DOWN"
    broken: bool


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def detect_fractals(bars: np.ndarray) -> list[FractalPoint]:
    """
    bars: structured numpy array from mt5.copy_rates_*
    Returns list of FractalPoint dicts sorted oldest → newest.
    Only considers bars[2:-2] so we have 2 bars on each side.
    A fractal is marked broken if any later close goes past it.
    """
    results: list[FractalPoint] = []

    highs  = bars["high"]
    lows   = bars["low"]
    closes = bars["close"]
    times  = bars["time"]      # Unix timestamps

    n = len(bars)
    for i in range(2, n - 2):
        h = highs[i]
        l = lows[i]

        is_up   = (h > highs[i-2] and h > highs[i-1]
                   and h > highs[i+1] and h > highs[i+2])
        is_down = (l < lows[i-2] and l < lows[i-1]
                   and l < lows[i+1] and l < lows[i+2])

        if is_up:
            # broken when a later close exceeds this high
            broken = bool(np.any(closes[i+1:] > h))
            results.append(FractalPoint(
                time=datetime.fromtimestamp(int(times[i]), tz=timezone.utc).isoformat(),
                price=float(h),
                type="UP",
                broken=broken,
            ))

        if is_down:
            # broken when a later close falls below this low
            broken = bool(np.any(closes[i+1:] < l))
            results.append(FractalPoint(
                time=datetime.fromtimestamp(int(times[i]), tz=timezone.utc).isoformat(),
                price=float(l),
                type="DOWN",
                broken=broken,
            ))

    # sort by time ascending (bars are already oldest-first, but UP+DOWN can interleave)
    results.sort(key=lambda x: x["time"])
    return results


def market_direction(fractals: list[FractalPoint]) -> str:
    """
    Determine market direction from the most recent *broken* fractals.

    Logic:
      - Find last broken UP fractal  → last_broken_up
      - Find last broken DOWN fractal → last_broken_down
      - If last_broken_up is more recent → UP (price broke above supply → bullish)
      - If last_broken_down is more recent → DOWN
      - If neither broken → FLAT
    """
    last_up   = next((f for f in reversed(fractals) if f["type"] == "UP"   and f["broken"]), None)
    last_down = next((f for f in reversed(fractals) if f["type"] == "DOWN" and f["broken"]), None)

    if last_up is None and last_down is None:
        return "FLAT"
    if last_up is None:
        return "DOWN"
    if last_down is None:
        return "UP"

    return "UP" if last_up["time"] > last_down["time"] else "DOWN"


# ---------------------------------------------------------------------------
# MT5 data fetch + JSON writer
# ---------------------------------------------------------------------------

def _init_mt5() -> bool:
    if not mt5.initialize():
        return False
    return True


def _fetch_bars() -> np.ndarray | None:
    bars = mt5.copy_rates_from_pos(SYMBOL, TF, 0, BARS_BACK)
    if bars is None or len(bars) < 5:
        return None
    return bars


def compute_once() -> dict:
    """
    Single-shot computation. Initializes MT5, fetches bars, computes fractals.
    Returns the state dict (same structure as what write_state() writes to JSON).
    Does NOT write to disk.
    """
    if not _init_mt5():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")

    bars = _fetch_bars()
    if bars is None:
        raise RuntimeError(f"Failed to fetch bars: {mt5.last_error()}")

    fractals  = detect_fractals(bars)
    direction = market_direction(fractals)

    last_broken_up   = next((f for f in reversed(fractals) if f["type"] == "UP"   and f["broken"]), None)
    last_broken_down = next((f for f in reversed(fractals) if f["type"] == "DOWN" and f["broken"]), None)

    return {
        "updated_at":       datetime.now(tz=timezone.utc).isoformat(),
        "symbol":           SYMBOL,
        "bars_analyzed":    int(len(bars)),
        "direction":        direction,
        "fractal_count":    len(fractals),
        "last_broken_up":   last_broken_up,
        "last_broken_down": last_broken_down,
        "fractals":         fractals[-KEEP:],   # keep newest 30
    }


def write_state() -> None:
    """Compute and atomically write friday_fractals.json."""
    state = compute_once()
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[friday_fractals] starting — writing to {OUTPUT} every {UPDATE_S}s")
    while True:
        try:
            write_state()
        except Exception as exc:
            print(f"[friday_fractals] ERROR: {exc}")
        time.sleep(UPDATE_S)


if __name__ == "__main__":
    main()
