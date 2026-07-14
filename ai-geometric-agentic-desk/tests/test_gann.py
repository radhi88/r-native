"""Tests for Gann Square-of-9 and angle geometry."""
from core import gann


def test_square_of_9_levels():
    levels = gann.square_of_9(100.0, (360,))
    assert levels["+360"] == 144.0  # (sqrt(100)+2)^2
    assert levels["-360"] == 64.0   # (sqrt(100)-2)^2


def test_nearest_sq9_within_atr():
    levels = gann.square_of_9(100.0, (360,))
    hit = gann.nearest_sq9(143.0, levels, atr=2.0)
    assert hit is not None and hit[0] == "+360"
    assert gann.nearest_sq9(120.0, levels, atr=1.0) is None


def test_gann_1x1_slope():
    p = gann.GannPivot(price=100.0, bar_index=0, direction=1)
    fan = gann.gann_angles(p, unit=1.0, bar_index=10)
    assert fan["1x1"] == 110.0  # 1 unit/bar * 10 bars
    assert fan["1x2"] == 105.0
    assert fan["2x1"] == 120.0
