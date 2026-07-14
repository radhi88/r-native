"""Tests for the micro-equity survival calculus."""
from core import micro_equity as me


def test_kelly_is_capped_and_floored():
    assert me.modified_kelly(0.6, 2.0) == 0.15  # raw 0.4 -> capped
    assert me.modified_kelly(0.4, 1.0) == 0.0   # negative -> floored
    assert 0.0 <= me.modified_kelly(0.55, 1.5) <= 0.15


def test_atr_stop_clamped():
    assert me.atr_stop_distance(10.0, 3.0) == 20.0  # k clamped to 2.0
    assert me.atr_stop_distance(10.0, 1.0) == 14.0  # k clamped to 1.4


def test_ten_dollar_survival_reject():
    # min lot risks 20% of a $10 account -> must reject, not size down
    r = me.size_position(equity=10.0, sl_dist=2.0, kelly_f=0.1,
                         tick_size=0.01, tick_value=1.0, vol_min=0.01,
                         vol_step=0.01, free_margin=10.0, margin_per_lot=1.0)
    assert r.accepted is False
    assert "survival" in r.reason


def test_accepts_when_risk_fits():
    r = me.size_position(equity=1000.0, sl_dist=0.0010, kelly_f=0.1,
                         tick_size=0.00001, tick_value=1.0, vol_min=0.01,
                         vol_step=0.01, free_margin=1000.0, margin_per_lot=1.0)
    assert r.accepted is True
    assert r.volume >= 0.01
    assert r.risk_pct <= me.config.MAX_RISK_PER_TRADE + 1e-9
