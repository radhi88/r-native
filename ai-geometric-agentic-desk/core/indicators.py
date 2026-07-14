"""Classic technical indicators used across market profiles.

Pure-NumPy, causal implementations of EMA, Wilder ATR/RSI, and a session VWAP.
These feed the indices/forex profiles (VWAP + structure) and the regime
classifier. Every function returns a full-length array aligned to the input.
"""
from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average.

    Args:
        values: Input series.
        period: EMA span.

    Returns:
        EMA array the same length as ``values``.
    """
    if len(values) == 0:
        return values
    k = 2.0 / (period + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14) -> np.ndarray:
    """Wilder's Average True Range.

    Args:
        high, low, close: OHLC arrays.
        period: Smoothing period.

    Returns:
        ATR array aligned to the inputs (early bars use the running mean).
    """
    n = len(close)
    if n < 2:
        return np.zeros(n)
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    out = np.empty(n)
    out[0] = tr[0]
    a = 1.0 / period
    for i in range(1, n):
        out[i] = out[i - 1] * (1 - a) + tr[i] * a
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's Relative Strength Index in ``[0, 100]``."""
    n = len(close)
    if n < 2:
        return np.full(n, 50.0)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag, al = np.zeros(n), np.zeros(n)
    ag[0], al[0] = gain[0], loss[0]
    a = 1.0 / period
    for i in range(1, n):
        ag[i] = ag[i - 1] * (1 - a) + gain[i] * a
        al[i] = al[i - 1] * (1 - a) + loss[i] * a
    rs = ag / (al + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         volume: np.ndarray) -> np.ndarray:
    """Cumulative volume-weighted average price over the window.

    Args:
        high, low, close: OHLC arrays.
        volume: Per-bar volume.

    Returns:
        Running VWAP array.
    """
    tp = (high + low + close) / 3.0
    cum_v = np.cumsum(volume) + 1e-12
    return np.cumsum(tp * volume) / cum_v
