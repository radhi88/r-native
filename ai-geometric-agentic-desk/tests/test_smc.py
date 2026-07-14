"""Tests for the SMC detectors."""
import numpy as np

from core import smc


def _series(n=40):
    rng = np.random.default_rng(3)
    c = 100 + rng.normal(0, 1, n).cumsum()
    o = c + rng.normal(0, 0.2, n)
    h = np.maximum(o, c) + 0.5
    l = np.minimum(o, c) - 0.5
    return o, h, l, c


def test_snapshot_shape_and_bias():
    o, h, l, c = _series()
    snap = smc.compute_smc(o, h, l, c)
    assert snap.bos in (-1, 0, 1)
    assert snap.choch in (-1, 0, 1)
    assert snap.liq_sweep in (-1, 0, 1)
    assert snap.bias in (-1, 0, 1)


def test_short_window_is_empty():
    o = h = l = c = np.array([1.0, 2.0, 3.0])
    snap = smc.compute_smc(o, h, l, c)
    assert snap.bos == 0 and snap.bias == 0


def test_bullish_fvg_detected():
    # bar i+1 low strictly above bar i-1 high -> bullish gap
    o = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 5.0])
    h = np.array([1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 6.0])
    l = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3.0])
    c = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 5.5])
    zone = smc._last_fvg(h, l)
    assert zone is not None
