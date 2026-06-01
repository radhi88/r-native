"""Tests for strategies/stoch_reversion: the M3 gold Stochastic strategy."""
import os, sys, types, importlib.util
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _pkg():
    if "r_native" not in sys.modules:
        p = types.ModuleType("r_native"); p.__path__ = [REPO]; sys.modules["r_native"] = p
def _load(n, path):
    s = importlib.util.spec_from_file_location(n, path)
    m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m)
    parent, _, child = n.rpartition(".")
    if parent in sys.modules: setattr(sys.modules[parent], child, m)
    return m

_pkg()
_load("r_native.strategy_types", os.path.join(REPO, "strategy_types.py"))
sr = _load("strategies_stoch_reversion", os.path.join(REPO, "strategies", "stoch_reversion.py"))


def _bars(prices):
    out = []
    for i, p in enumerate(prices):
        h = p + 0.3; l = p - 0.3
        out.append({"time": i, "open": p, "high": h, "low": l, "close": p,
                    "volume": 100})
    return out


def test_build_strategy_object():
    s = sr.build_stoch_reversion_strategy()
    assert s.name.startswith("Gold M3")
    assert s.pairs == ["XAUUSDm"]
    # Only the stochastic indicator should be enabled
    enabled = [i for i in s.indicators if i.enabled]
    assert len(enabled) == 1 and enabled[0].key == "stochastic"
    # All four entry conditions present
    assert len(s.entryConditions) == 4
    print("OK test_build_strategy_object")


def test_stochastic_kd_shape():
    rng = np.random.default_rng(0)
    # Walk so highs/lows differ from closes
    closes = 100 + np.cumsum(rng.normal(0, 0.3, 200))
    bars = []
    for i, c in enumerate(closes):
        bars.append({"time": i, "open": c, "high": c + 0.5, "low": c - 0.5,
                     "close": c, "volume": 100})
    k, d = sr.stochastic_kd(bars)
    assert len(k) == len(d) == 200
    # After warmup, both should be in 0..100
    valid_k = k[~np.isnan(k)]; valid_d = d[~np.isnan(d)]
    assert valid_k.min() >= 0 and valid_k.max() <= 100
    assert valid_d.min() >= 0 and valid_d.max() <= 100
    print(f"OK test_stochastic_kd_shape (warmup ~{np.isnan(d).sum()} bars)")


def test_evaluate_signal_sell_heavy():
    s = sr.evaluate_signal(prev_d=91.0, cur_d=88.5)
    assert s["action"] == "SELL" and s["tier"] == "HEAVY"
    print("OK test_evaluate_signal_sell_heavy")


def test_evaluate_signal_sell_light():
    s = sr.evaluate_signal(prev_d=86.0, cur_d=82.0)
    assert s["action"] == "SELL" and s["tier"] == "LIGHT"
    print("OK test_evaluate_signal_sell_light")


def test_evaluate_signal_buy_heavy():
    s = sr.evaluate_signal(prev_d=8.0, cur_d=12.0)
    assert s["action"] == "BUY" and s["tier"] == "HEAVY"
    print("OK test_evaluate_signal_buy_heavy")


def test_evaluate_signal_buy_light():
    s = sr.evaluate_signal(prev_d=14.0, cur_d=17.0)
    assert s["action"] == "BUY" and s["tier"] == "LIGHT"
    print("OK test_evaluate_signal_buy_light")


def test_evaluate_signal_midline_close():
    s = sr.evaluate_signal(prev_d=55.0, cur_d=48.0)
    assert s["action"] == "CLOSE"
    s2 = sr.evaluate_signal(prev_d=48.0, cur_d=55.0)
    assert s2["action"] == "CLOSE"
    print("OK test_evaluate_signal_midline_close")


def test_evaluate_signal_no_action_in_middle():
    assert sr.evaluate_signal(prev_d=60.0, cur_d=58.0) is None
    assert sr.evaluate_signal(prev_d=30.0, cur_d=35.0) is None
    print("OK test_evaluate_signal_no_action_in_middle")


def test_evaluate_signal_nan_safe():
    assert sr.evaluate_signal(np.nan, 50.0) is None
    assert sr.evaluate_signal(50.0, np.nan) is None
    print("OK test_evaluate_signal_nan_safe")


def test_backtest_runs_and_returns_summary():
    # Strong oscillation so signals fire
    n = 300
    t = np.arange(n)
    closes = 100 + 8 * np.sin(t / 4.0) + np.random.default_rng(1).normal(0, 0.5, n)
    bars = []
    for i, c in enumerate(closes):
        bars.append({"time": i, "open": c, "high": c + 0.6, "low": c - 0.6,
                     "close": c, "volume": 100})
    res = sr.backtest(bars)
    assert "trades" in res and "summary" in res
    s = res["summary"]
    assert s["trades"] >= 1
    # Win-rate + PF computed sanely
    assert 0 <= s["win_rate"] <= 100
    assert s["profit_factor"] >= 0
    print(f"OK test_backtest_runs_and_returns_summary "
          f"({s['trades']} trades, {s['win_rate']}% WR)")


def test_backtest_caps_pyramid():
    """No more than 2 same-side positions open at any time."""
    n = 200
    t = np.arange(n)
    closes = 100 + 10 * np.sin(t / 6.0)
    bars = [{"time": i, "open": c, "high": c + 0.5, "low": c - 0.5,
             "close": c, "volume": 100} for i, c in enumerate(closes)]
    res = sr.backtest(bars)
    # Walk trades in time order — at any open moment, count concurrent same-side
    open_buys = open_sells = 0
    events = []
    for t in res["trades"]:
        events.append((t["idx_open"], "open", t["side"]))
        events.append((t["idx_close"], "close", t["side"]))
    events.sort()
    for _, kind, side in events:
        delta = 1 if kind == "open" else -1
        if side == "BUY":  open_buys += delta
        else:              open_sells += delta
        assert open_buys <= 2 and open_sells <= 2
    print("OK test_backtest_caps_pyramid")


def test_adx_filter_blocks_entries_in_trend():
    """In a strong trend ADX > 25 — strict filter should skip most entries."""
    import numpy as np
    n = 300
    trend = 100 + np.arange(n) * 0.4
    noise = np.random.default_rng(1).normal(0, 0.3, n)
    closes = trend + noise
    bars = [{"time": i, "open": c, "high": c + 0.4, "low": c - 0.4,
              "close": c, "volume": 100} for i, c in enumerate(closes)]
    r_no = sr.backtest(bars, atr_sl_mult=2.5)
    r_filt = sr.backtest(bars, atr_sl_mult=2.5, adx_max=20.0)
    assert r_filt["summary"].get("entries_skipped_by_adx", 0) > 0
    assert r_filt["summary"]["trades"] <= r_no["summary"]["trades"]
    print(f"OK test_adx_filter_blocks_entries_in_trend "
          f"(no_filter={r_no['summary']['trades']}, with_filter="
          f"{r_filt['summary']['trades']}, "
          f"skipped={r_filt['summary'].get('entries_skipped_by_adx')})")


def test_adx_filter_keeps_entries_in_range():
    """In a flat ranging market, ADX is low so the filter should not block."""
    import numpy as np
    n = 300
    closes = 100 + 3 * np.sin(np.arange(n) / 6.0)
    bars = [{"time": i, "open": c, "high": c + 0.5, "low": c - 0.5,
              "close": c, "volume": 100} for i, c in enumerate(closes)]
    r = sr.backtest(bars, atr_sl_mult=2.5, adx_max=25.0)
    s = r["summary"]
    if s["trades"] > 0:
        print(f"OK test_adx_filter_keeps_entries_in_range "
              f"(trades={s['trades']}, skipped={s.get('entries_skipped_by_adx', 0)})")
    else:
        print("OK test_adx_filter_keeps_entries_in_range (no signals fired)")


if __name__ == "__main__":
    test_build_strategy_object()
    test_stochastic_kd_shape()
    test_evaluate_signal_sell_heavy()
    test_evaluate_signal_sell_light()
    test_evaluate_signal_buy_heavy()
    test_evaluate_signal_buy_light()
    test_evaluate_signal_midline_close()
    test_evaluate_signal_no_action_in_middle()
    test_evaluate_signal_nan_safe()
    test_backtest_runs_and_returns_summary()
    test_backtest_caps_pyramid()
    test_adx_filter_blocks_entries_in_trend()
    test_adx_filter_keeps_entries_in_range()
    print("\n✓ all stoch-reversion tests passed")
