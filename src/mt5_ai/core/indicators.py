"""Shared market indicator helpers for runtime code."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def atr(df: Any, period: int = 14) -> float:
    """Return the latest average true range value for OHLC data."""
    close_prev = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - close_prev).abs(),
            (df["low"] - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = float(true_range.rolling(period).mean().iloc[-1])
    return value if math.isfinite(value) else 0.0
