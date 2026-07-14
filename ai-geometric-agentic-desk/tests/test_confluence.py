"""Tests for the confluence matrix gate."""
from core.confluence import evaluate
from core.smc import SMCSnapshot


def test_no_trade_without_confluences():
    dec = evaluate(price=100.0, atr=1.0, smc=SMCSnapshot(), fractal="neutral",
                   ml_dir=0, ml_conf=0.5, pivot_price=100.0, pivot_bar=0,
                   bar_index=10)
    assert dec.trade is False
    assert dec.direction == 0


def test_aligned_signals_can_trade():
    snap = SMCSnapshot(bos=1, liq_sweep=1, bias=1)
    dec = evaluate(price=100.0, atr=5.0, smc=snap, fractal="bull",
                   ml_dir=1, ml_conf=0.8, pivot_price=100.0, pivot_bar=0,
                   bar_index=10)
    assert dec.direction == 1
    assert dec.count >= 3
    assert dec.trade is True
