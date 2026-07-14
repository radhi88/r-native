"""Tests for Williams fractal detection."""
import numpy as np

from core import fractals


def test_detects_swing_high_and_low():
    highs = np.array([1, 2, 3, 5, 3, 2, 1], dtype=float)
    lows = np.array([5, 4, 3, 1, 3, 4, 5], dtype=float)
    fr = fractals.williams_fractals(highs, lows)
    kinds = {(f.index, f.kind) for f in fr}
    assert (3, "bear") in kinds  # apex high at index 3
    assert (3, "bull") in kinds  # trough low at index 3


def test_state_neutral_when_few():
    assert fractals.fractal_state([]) == "neutral"
