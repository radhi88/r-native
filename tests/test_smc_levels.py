"""Unit checks for SMC liquidity-sweep and order-block detection in r_levels.

Runs with plain asserts (no pytest, no MT5 terminal needed):
    PYTHONPATH=tests/stubs python tests/test_smc_levels.py
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "stubs"))   # MetaTrader5 stub


def load_r_levels():
    spec = importlib.util.spec_from_file_location(
        "r_levels", ROOT / "friday_v3" / "algory" / "r_levels.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r_levels"] = mod          # dataclass introspection needs this
    spec.loader.exec_module(mod)
    return mod


def make_bars(o, h, l, c):
    dt = np.dtype([("time", "i8"), ("open", "f8"), ("high", "f8"),
                   ("low", "f8"), ("close", "f8"), ("tick_volume", "i8"),
                   ("spread", "i4"), ("real_volume", "i8")])
    n = len(o)
    bars = np.zeros(n, dtype=dt)
    bars["time"] = np.arange(n) * 3600
    bars["open"], bars["high"], bars["low"], bars["close"] = o, h, l, c
    bars["tick_volume"] = 1000
    return bars


def flat_ohlc(n, price=100.0, wobble=0.2):
    o = np.full(n, price); c = np.full(n, price)
    h = o + wobble; l = o - wobble
    return o, h, l, c


def test_sweep_above(rl):
    # Swing high at bar 10 (price 105), then a recent bar wicks to 106
    # but closes back at 100 → sweep_above.
    o, h, l, c = flat_ohlc(30)
    h[10] = 105.0                                   # prior swing high
    h[26] = 106.0                                   # the sweep wick
    res = rl._sweeps_from_bars(make_bars(o, h, l, c))
    assert res["sweep_above"], res
    assert res["sweep_above_level"] == 105.0, res
    assert not res["sweep_below"], res


def test_sweep_below(rl):
    o, h, l, c = flat_ohlc(30)
    l[12] = 95.0                                    # prior swing low
    h[12] = 100.1   # slightly below neighbors so ties don't mark it a swing high
    l[27] = 94.0                                    # sweep wick below it
    res = rl._sweeps_from_bars(make_bars(o, h, l, c))
    assert res["sweep_below"], res
    assert res["sweep_below_level"] == 95.0, res
    assert not res["sweep_above"], res


def test_no_sweep_when_no_reversal(rl):
    # Break of the high with closes STAYING above = breakout, not a sweep.
    o, h, l, c = flat_ohlc(30)
    h[10] = 105.0
    for j in range(26, 30):                          # sustained break
        o[j] = 107.0; c[j] = 107.5; h[j] = 108.0; l[j] = 106.5
    res = rl._sweeps_from_bars(make_bars(o, h, l, c))
    assert not res["sweep_above"], res


def test_bull_order_block(rl):
    # Down-close candle at bar 15, then a 3-bar rally far beyond ATR.
    o, h, l, c = flat_ohlc(25)
    o[15], c[15], h[15], l[15] = 100.0, 99.0, 100.2, 98.8   # bearish candle
    for k, j in enumerate(range(16, 19), start=1):           # impulse up
        o[j] = 99.0 + 2*(k-1); c[j] = 99.0 + 2*k
        h[j] = c[j] + 0.2; l[j] = o[j] - 0.2
    for j in range(19, 25):                                  # stay high → unmitigated
        o[j] = c[j] = 105.0; h[j] = 105.2; l[j] = 104.8
    res = rl._order_blocks_from_bars(make_bars(o, h, l, c))
    assert res["OB_bull"], res
    ob = res["OB_bull"][-1]
    assert ob["bottom"] == 98.8 and ob["top"] == 100.2, ob
    assert ob["mitigated"] is False, ob


def test_bear_order_block_mitigated(rl):
    # Up-close candle at bar 15, impulsive drop, then price returns into zone.
    o, h, l, c = flat_ohlc(25)
    o[15], c[15], h[15], l[15] = 100.0, 101.0, 101.2, 99.8   # bullish candle
    for k, j in enumerate(range(16, 19), start=1):           # impulse down
        o[j] = 101.0 - 2*(k-1); c[j] = 101.0 - 2*k
        h[j] = o[j] + 0.2; l[j] = c[j] - 0.2
    for j in range(19, 25):                                  # return INTO the zone
        o[j] = c[j] = 100.5; h[j] = 100.7; l[j] = 100.3
    res = rl._order_blocks_from_bars(make_bars(o, h, l, c))
    assert res["OB_bear"], res
    ob = res["OB_bear"][-1]
    assert ob["mitigated"] is True, ob


def test_quiet_market_has_no_obs(rl):
    o, h, l, c = flat_ohlc(40)
    res = rl._order_blocks_from_bars(make_bars(o, h, l, c))
    assert res["OB_bull"] == [] and res["OB_bear"] == [], res


def main():
    rl = load_r_levels()
    test_sweep_above(rl)
    test_sweep_below(rl)
    test_no_sweep_when_no_reversal(rl)
    test_bull_order_block(rl)
    test_bear_order_block_mitigated(rl)
    test_quiet_market_has_no_obs(rl)
    print("smc levels: all checks pass")


if __name__ == "__main__":
    main()
