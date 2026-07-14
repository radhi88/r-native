"""Market regime classification.

A deterministic classifier that labels the current window as ``trend_up``,
``trend_down``, ``range``, or ``volatile`` from EMA slope and ATR-normalised
dispersion. The regime gates strategy selection and is stored in the tick
registry's ``regime`` column.
"""
from __future__ import annotations

import numpy as np

from core.indicators import atr, ema


def classify_regime(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                    ema_period: int = 50, slope_atr: float = 0.10) -> str:
    """Classify the prevailing regime over the window.

    Args:
        high, low, close: OHLC arrays.
        ema_period: EMA span for the trend filter.
        slope_atr: Minimum EMA slope (in ATR/bar) to call a trend.

    Returns:
        One of ``"trend_up"``, ``"trend_down"``, ``"range"``, ``"volatile"``.
    """
    if len(close) < ema_period + 5:
        return "range"
    e = ema(close, ema_period)
    a = atr(high, low, close)[-1] + 1e-12
    slope = (e[-1] - e[-5]) / 5.0 / a  # ATR-normalised slope per bar
    recent_atr = atr(high, low, close)[-20:].mean()
    long_atr = atr(high, low, close).mean() + 1e-12
    if recent_atr > 1.8 * long_atr:
        return "volatile"
    if slope > slope_atr:
        return "trend_up"
    if slope < -slope_atr:
        return "trend_down"
    return "range"


def regime_direction(regime: str) -> int:
    """Map a regime label to a directional bias in ``{-1, 0, +1}``."""
    return {"trend_up": 1, "trend_down": -1}.get(regime, 0)
