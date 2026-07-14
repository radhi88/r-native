"""Confluence matrix — the trade-or-pass decision.

Aggregates SMC structure, Williams fractal state, Gann/Square-of-9 level
proximity, and the ML vote into a single directional decision. A trade is
only proposed when at least :data:`config.MIN_CONFLUENCES` independent signals
agree on direction AND the ML confidence clears :data:`config.ML_CONFIDENCE_GATE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from core.gann import active_angle, gann_angles, nearest_sq9, square_of_9, GannPivot
from core.smc import SMCSnapshot


@dataclass
class Decision:
    """Output of the confluence matrix.

    Attributes:
        direction: ``+1`` long, ``-1`` short, ``0`` no trade.
        count: Number of aligned confluences.
        confluences: Human-readable list of what aligned.
        ml_conf: ML confidence carried through to the gate.
        trade: Whether all gates pass.
    """

    direction: int = 0
    count: int = 0
    confluences: list[str] = field(default_factory=list)
    ml_conf: float = 0.5
    trade: bool = False


def evaluate(
    price: float,
    atr: float,
    smc: SMCSnapshot,
    fractal: str,
    ml_dir: int,
    ml_conf: float,
    pivot_price: float,
    pivot_bar: int,
    bar_index: int,
    sq9_degrees: tuple[float, ...] = (90, 180, 360, 720),
) -> Decision:
    """Score confluences and decide whether to trade.

    Args:
        price: Current price.
        atr: Working-timeframe ATR (proximity tolerance).
        smc: SMC snapshot from :func:`core.smc.compute_smc`.
        fractal: Fractal regime from :func:`core.fractals.fractal_state`.
        ml_dir: ML signal direction.
        ml_conf: ML confidence in ``[0.5, 1.0]``.
        pivot_price: Anchor price for the Gann fan and Sq9 base.
        pivot_bar: Bar index of the pivot.
        bar_index: Current bar index.
        sq9_degrees: Square-of-9 rotations to project.

    Returns:
        A :class:`Decision`.
    """
    votes: dict[int, list[str]] = {1: [], -1: []}

    if smc.bias != 0:
        tag = "SMC " + ("BOS" if smc.bos else "CHoCH" if smc.choch else "sweep")
        votes[smc.bias].append(tag)
    if smc.liq_sweep != 0:
        votes[smc.liq_sweep].append("Liq-Sweep")
    if fractal == "bull":
        votes[1].append("Bull-Fractal")
    elif fractal == "bear":
        votes[-1].append("Bear-Fractal")

    levels = square_of_9(pivot_price, sq9_degrees)
    near = nearest_sq9(price, levels, atr)
    if near is not None:
        # near a level → mean-reversion bias toward the prevailing structure
        side = smc.bias if smc.bias != 0 else ml_dir
        if side != 0:
            votes[side].append(f"Sq9 {near[0]}deg")

    fan_dir = 1 if price >= pivot_price else -1
    fan = gann_angles(GannPivot(pivot_price, pivot_bar, fan_dir), atr, bar_index)
    angle = active_angle(price, fan, atr)
    if angle is not None and smc.bias != 0:
        votes[smc.bias].append(f"Gann {angle}")

    if ml_dir != 0 and ml_conf >= config.ML_CONFIDENCE_GATE:
        votes[ml_dir].append(f"ML {ml_conf:.0%}")

    long_n, short_n = len(votes[1]), len(votes[-1])
    if long_n >= short_n and long_n > 0:
        direction, conf = 1, votes[1]
    elif short_n > 0:
        direction, conf = -1, votes[-1]
    else:
        return Decision(0, 0, [], ml_conf, False)

    trade = (len(conf) >= config.MIN_CONFLUENCES
             and ml_conf >= config.ML_CONFIDENCE_GATE
             and ml_dir == direction)
    return Decision(direction, len(conf), conf, ml_conf, trade)
