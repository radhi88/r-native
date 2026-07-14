"""Volume Profile — POC / Value Area High / Value Area Low.

Builds a price histogram weighted by bar volume and derives the Point of
Control (most-traded price) and the value area enclosing a target share of
volume (70% by convention). These populate the ``poc/vah/val`` columns of the
tick registry and feed the crypto profile's volume-based confluence.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class VolumeProfile:
    """Result of a volume-profile computation.

    Attributes:
        poc: Point of Control price.
        vah: Value Area High.
        val: Value Area Low.
    """

    poc: float
    vah: float
    val: float


def compute(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            volume: np.ndarray, bins: int = 50,
            value_area: float = 0.70) -> VolumeProfile:
    """Compute POC/VAH/VAL over a bar window.

    Args:
        high, low, close: OHLC arrays.
        volume: Per-bar volume.
        bins: Number of price buckets.
        value_area: Fraction of volume the value area must enclose.

    Returns:
        A :class:`VolumeProfile`. Degenerate inputs collapse all three to the
        last close.
    """
    if len(close) == 0:
        return VolumeProfile(0.0, 0.0, 0.0)
    lo, hi = float(np.min(low)), float(np.max(high))
    if hi <= lo:
        c = float(close[-1])
        return VolumeProfile(c, c, c)

    edges = np.linspace(lo, hi, bins + 1)
    centres = (edges[:-1] + edges[1:]) / 2.0
    tp = (high + low + close) / 3.0
    idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
    hist = np.zeros(bins)
    np.add.at(hist, idx, volume)

    poc_i = int(np.argmax(hist))
    total = hist.sum() + 1e-12
    target = total * value_area
    lo_i = hi_i = poc_i
    acc = hist[poc_i]
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left = hist[lo_i - 1] if lo_i > 0 else -1
        right = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1
            acc += hist[hi_i]
        else:
            lo_i -= 1
            acc += hist[lo_i]
    return VolumeProfile(round(centres[poc_i], 6),
                         round(centres[hi_i], 6), round(centres[lo_i], 6))
