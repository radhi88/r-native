"""Gann Square-of-9 and Gann-angle geometry.

Square of 9: numbers spiral out from a centre; moving 360 degrees around the
spiral squares the next odd root. A price level at angle ``d`` from a base is
``(sqrt(base) +/- d/180)^2``. Gann angles project price/time fans (1x1, 1x2,
2x1) from a pivot, with the price-per-bar unit anchored to ATR so the geometry
adapts per market.

These are *measured* levels, surfaced to the confluence matrix as features.
They are not assumed predictive on their own.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def square_of_9(price: float, degrees: tuple[float, ...] = (90, 180, 360, 720)) -> dict[str, float]:
    """Project Square-of-9 support/resistance levels around ``price``.

    Args:
        price: The base price (a recent swing pivot works well).
        degrees: Rotations to project, in degrees.

    Returns:
        Mapping like ``{"+90": 1.234, "-90": 1.230, ...}`` of projected levels.
        Returns an empty mapping for non-positive prices.
    """
    if price <= 0:
        return {}
    root = math.sqrt(price)
    out: dict[str, float] = {}
    for d in degrees:
        step = d / 180.0
        out[f"+{int(d)}"] = round((root + step) ** 2, 6)
        out[f"-{int(d)}"] = round((root - step) ** 2, 6) if root > step else 0.0
    return out


def nearest_sq9(price: float, levels: dict[str, float], atr: float) -> tuple[str, float, float] | None:
    """Find the closest Square-of-9 level within one ATR of ``price``.

    Args:
        price: Current price.
        levels: Output of :func:`square_of_9`.
        atr: ATR used as the proximity tolerance.

    Returns:
        ``(label, level, distance)`` for the nearest level inside one ATR,
        or ``None`` if price is not near any projected level.
    """
    best: tuple[str, float, float] | None = None
    for label, lvl in levels.items():
        if lvl <= 0:
            continue
        dist = abs(price - lvl)
        if dist <= atr and (best is None or dist < best[2]):
            best = (label, lvl, dist)
    return best


@dataclass
class GannPivot:
    """Anchor for a Gann-angle fan."""

    price: float
    bar_index: int
    direction: int  # +1 up-fan from a low, -1 down-fan from a high


def gann_angles(pivot: GannPivot, unit: float, bar_index: int) -> dict[str, float]:
    """Project 1x1 / 1x2 / 2x1 Gann-angle prices at ``bar_index``.

    The 1x1 line moves one ``unit`` of price per bar. 1x2 is half slope
    (slower), 2x1 is double slope (steeper).

    Args:
        pivot: Origin of the fan.
        unit: Price moved per bar for the 1x1 line (ATR is a good choice).
        bar_index: Bar at which to evaluate the fan lines.

    Returns:
        Mapping ``{"1x1": p, "1x2": p, "2x1": p}`` of fan-line prices.
    """
    dt = max(0, bar_index - pivot.bar_index)
    s = pivot.direction
    return {
        "1x1": round(pivot.price + s * unit * dt, 6),
        "1x2": round(pivot.price + s * (unit * 0.5) * dt, 6),
        "2x1": round(pivot.price + s * (unit * 2.0) * dt, 6),
    }


def active_angle(price: float, fan: dict[str, float], atr: float) -> str | None:
    """Return the fan line ``price`` is currently riding, if any.

    Args:
        price: Current price.
        fan: Output of :func:`gann_angles`.
        atr: Proximity tolerance.

    Returns:
        The label of the nearest fan line within one ATR, else ``None``.
    """
    best: tuple[str, float] | None = None
    for label, lvl in fan.items():
        dist = abs(price - lvl)
        if dist <= atr and (best is None or dist < best[1]):
            best = (label, dist)
    return best[0] if best else None
