"""
Pytest configuration file for MT5 tests
Automatically sets up directory structure on import
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

# ── Bootstrap sys.path so that:
#   - importlib.import_module("scripts.prepare_sequences") resolves (project root on path)
#   - "from _bootstrap import bootstrap" inside scripts/ resolves (scripts/ dir on path)
# Both entries are added early, before any test collection or imports.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_PROJECT_ROOT, _PROJECT_ROOT / "scripts", _PROJECT_ROOT / "src"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)


# Auto-create directory structure
def pytest_configure(config):
    """Called before test collection"""
    base_path = Path(__file__).parent.parent / "src" / "mt5_ai"
    directories = [
        "strategies",
        "learning",
        "genetics",
        "integrations",
        "interfaces",
        "utils"
    ]

    for directory in directories:
        dir_path = base_path / directory
        dir_path.mkdir(parents=True, exist_ok=True)

# Also execute when imported directly
base_path = Path(__file__).parent.parent / "src" / "mt5_ai"
directories = [
    "strategies",
    "learning",
    "genetics",
    "integrations",
    "interfaces",
    "utils"
]

for directory in directories:
    dir_path = base_path / directory
    dir_path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Phase 9 — Volatility-Regime Test Scaffold
# Synthetic deterministic M1 OHLCV fixture (no MT5, no TensorFlow).
#
# Design:
#   90 M1 bars = 6 complete M15 buckets (15 bars each).
#   Within each group of 15:
#     - open  = first bar's open  (group * 10 + 1.0)
#     - high  = max of group      (group * 10 + 15.0)  <- last bar's open is the max
#     - low   = min of group      (group * 10 + 1.0)   <- first bar is the min
#     - close = last bar's close  (group * 10 + 15.5)
#     - tick_volume = sum         = 15 * (group + 1)
#   Hand-verifiable expected M15 OHLCV per bucket is deterministic from group index.
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_m1_df():
    """
    Deterministic M1 OHLCV DataFrame: 90 bars, 6 full M15 groups of 15.

    Per group g (0-indexed):
      open  of bar i in group g: g * 10 + (i % 15) + 1
      high  of bar i            : open + 0.5
      low   of bar i            : open - 0.5
      close of bar i            : open + 0.3
      tick_volume               : g + 1   (all bars in the group share the same vol)

    Expected M15 aggregation per group g:
      open  = g * 10 + 1            (first bar's open)
      high  = g * 10 + 15.5         (last bar's open + 0.5)
      low   = g * 10 + 0.5          (first bar's open - 0.5)
      close = g * 10 + 15.3         (last bar's close = last open + 0.3)
      tick_volume = 15 * (g + 1)    (sum of all bars)
    """
    n_groups = 6
    bars_per_group = 15
    n_bars = n_groups * bars_per_group

    base_time = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    times = [base_time + pd.Timedelta(minutes=i) for i in range(n_bars)]

    records = []
    for i in range(n_bars):
        g = i // bars_per_group          # group index (0-5)
        pos = i % bars_per_group         # position within group (0-14)
        o = g * 10 + pos + 1             # e.g. group 0: 1..15, group 1: 11..25
        records.append({
            "time": times[i],
            "open": float(o),
            "high": float(o) + 0.5,
            "low": float(o) - 0.5,
            "close": float(o) + 0.3,
            "tick_volume": float(g + 1),
        })

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df
