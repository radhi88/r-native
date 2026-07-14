"""Williams fractal geometry — causal swing detection.

A bearish (up) fractal at bar ``i`` requires ``H[i]`` to be the highest of the
five-bar window ``i-2 .. i+2``; a bullish (down) fractal mirrors it on lows.
Detection is right-confirmed (needs the two bars after ``i``), so it never
peeks into the future during a backtest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Fractal:
    """A confirmed Williams fractal.

    Attributes:
        index: Bar index of the fractal apex.
        price: High (bearish) or low (bullish) at the apex.
        kind: ``"bear"`` (swing high) or ``"bull"`` (swing low).
    """

    index: int
    price: float
    kind: str


def williams_fractals(highs: np.ndarray, lows: np.ndarray) -> list[Fractal]:
    """Detect all confirmed Williams fractals in a bar series.

    Args:
        highs: Array of bar highs.
        lows: Array of bar lows.

    Returns:
        Chronological list of confirmed :class:`Fractal` objects.
    """
    out: list[Fractal] = []
    n = len(highs)
    for i in range(2, n - 2):
        h = highs[i]
        if h > highs[i - 1] and h > highs[i - 2] and h > highs[i + 1] and h > highs[i + 2]:
            out.append(Fractal(i, float(h), "bear"))
        lo = lows[i]
        if lo < lows[i - 1] and lo < lows[i - 2] and lo < lows[i + 1] and lo < lows[i + 2]:
            out.append(Fractal(i, float(lo), "bull"))
    return out


def fractal_state(fractals: list[Fractal]) -> str:
    """Summarise the latest fractal context into a regime label.

    Args:
        fractals: Output of :func:`williams_fractals`.

    Returns:
        ``"bull"``, ``"bear"`` or ``"neutral"`` from the two most recent
        fractals (higher-low/higher-high → bull, etc.).
    """
    if len(fractals) < 2:
        return "neutral"
    last, prev = fractals[-1], fractals[-2]
    bulls = [f for f in fractals if f.kind == "bull"]
    bears = [f for f in fractals if f.kind == "bear"]
    if len(bulls) >= 2 and bulls[-1].price > bulls[-2].price:
        return "bull"
    if len(bears) >= 2 and bears[-1].price < bears[-2].price:
        return "bear"
    return "bull" if last.kind == "bull" else "bear"
