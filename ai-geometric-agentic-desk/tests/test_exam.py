"""Tests for the walk-forward exam harness."""
import numpy as np

from exam.backtest import score_exam


def _ohlc(n=320, seed=11):
    rng = np.random.default_rng(seed)
    c = 2000 + rng.normal(0, 1, n).cumsum()
    o = c + rng.normal(0, 0.3, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.5, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.5, n))
    return o, h, l, c


def test_score_bounds_and_fields():
    o, h, l, c = _ohlc()
    res = score_exam(o, h, l, c, profile_k=2.0, sq9_deg=(90, 180, 360),
                     spread_price=0.3)
    assert 0.0 <= res.score <= 100.0
    assert res.trades >= 0
    assert res.profit_factor >= 0.0
    assert isinstance(res.notes, str)


def test_random_data_does_not_pass_gate():
    # Pure noise must not earn a deployable score net of spread.
    o, h, l, c = _ohlc(seed=99)
    res = score_exam(o, h, l, c, profile_k=2.0, sq9_deg=(90, 180, 360),
                     spread_price=0.5)
    assert res.score < 95.0
