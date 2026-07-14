"""Smart Money Concepts — causal, self-contained detectors.

Implements the SMC primitives the desk trades on: market structure swings,
BOS (break of structure), CHoCH (change of character), order blocks, fair
value gaps, and liquidity sweeps. Every detector is right-confirmed so a
backtest is free of look-ahead.

Honesty note: in this project's own out-of-sample research SMC was NO_EDGE
net of cost (only BTC liquidity-sweep beat random, and spread still ate it).
These detectors are therefore surfaced as *measured features* to the
confluence matrix and exam, not trusted as standalone signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.fractals import Fractal, williams_fractals


@dataclass
class SMCSnapshot:
    """SMC features extracted from a closed-bar window.

    Attributes:
        bos: ``+1`` bullish break, ``-1`` bearish break, ``0`` none.
        choch: ``+1`` / ``-1`` change of character, ``0`` none.
        ob_zone: ``(low, high)`` of the freshest order block, or ``None``.
        fvg_zone: ``(low, high)`` of the freshest fair value gap, or ``None``.
        liq_sweep: ``+1`` swept lows (bullish), ``-1`` swept highs, ``0`` none.
        bias: Net structural bias in ``{-1, 0, +1}``.
    """

    bos: int = 0
    choch: int = 0
    ob_zone: tuple[float, float] | None = None
    fvg_zone: tuple[float, float] | None = None
    liq_sweep: int = 0
    bias: int = 0


def _swings(highs: np.ndarray, lows: np.ndarray) -> list[Fractal]:
    return williams_fractals(highs, lows)


def _bos_choch(closes: np.ndarray, swings: list[Fractal]) -> tuple[int, int]:
    """Detect the latest BOS and CHoCH from confirmed swings.

    Returns:
        ``(bos, choch)`` each in ``{-1, 0, +1}``.
    """
    bears = [f for f in swings if f.kind == "bear"]
    bulls = [f for f in swings if f.kind == "bull"]
    if not bears or not bulls:
        return 0, 0
    last = closes[-1]
    bos = 0
    if last > bears[-1].price:
        bos = 1
    elif last < bulls[-1].price:
        bos = -1
    # CHoCH: BOS against the prior structural direction
    prior = 0
    if len(bulls) >= 2:
        prior = 1 if bulls[-1].price > bulls[-2].price else -1
    choch = bos if (bos != 0 and prior != 0 and bos != prior) else 0
    return bos, choch


def _last_fvg(highs: np.ndarray, lows: np.ndarray) -> tuple[float, float] | None:
    """Most recent 3-candle fair value gap as ``(low, high)``."""
    for i in range(len(highs) - 2, 1, -1):
        # bullish gap: low[i+1] > high[i-1]
        if lows[i + 1] > highs[i - 1]:
            return (float(highs[i - 1]), float(lows[i + 1]))
        if highs[i + 1] < lows[i - 1]:
            return (float(highs[i + 1]), float(lows[i - 1]))
    return None


def _last_ob(opens: np.ndarray, closes: np.ndarray, highs: np.ndarray,
             lows: np.ndarray, bos: int) -> tuple[float, float] | None:
    """Last opposite-color candle before the latest impulse, as ``(low, high)``."""
    if bos == 0:
        return None
    want_red = bos > 0  # bullish break → last down candle is the OB
    for i in range(len(closes) - 2, 1, -1):
        is_red = closes[i] < opens[i]
        if is_red == want_red:
            return (float(lows[i]), float(highs[i]))
    return None


def _liq_sweep(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
               swings: list[Fractal]) -> int:
    """Detect a wick beyond a swing extreme that closes back inside."""
    bears = [f for f in swings if f.kind == "bear"]
    bulls = [f for f in swings if f.kind == "bull"]
    hi, lo, cl = highs[-1], lows[-1], closes[-1]
    if bears and hi > bears[-1].price and cl < bears[-1].price:
        return -1
    if bulls and lo < bulls[-1].price and cl > bulls[-1].price:
        return 1
    return 0


def compute_smc(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                closes: np.ndarray) -> SMCSnapshot:
    """Extract a full SMC snapshot from a closed-bar window.

    Args:
        opens, highs, lows, closes: Equal-length OHLC arrays, oldest first.

    Returns:
        A populated :class:`SMCSnapshot`.
    """
    if len(closes) < 10:
        return SMCSnapshot()
    swings = _swings(highs, lows)
    bos, choch = _bos_choch(closes, swings)
    snap = SMCSnapshot(
        bos=bos,
        choch=choch,
        ob_zone=_last_ob(opens, closes, highs, lows, bos),
        fvg_zone=_last_fvg(highs, lows),
        liq_sweep=_liq_sweep(highs, lows, closes, swings),
    )
    snap.bias = int(np.sign(bos + choch + snap.liq_sweep))
    return snap
