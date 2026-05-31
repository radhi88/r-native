"""Tests for strategy_types + strategy_store + live_indicators (pure logic)."""
from __future__ import annotations

import os
import sys
import tempfile
import importlib.util
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# Register under the r_native package names the modules import from each other
import types as _t
if "r_native" not in sys.modules:
    pkg = _t.ModuleType("r_native"); pkg.__path__ = [REPO]; sys.modules["r_native"] = pkg
st  = _load("r_native.strategy_types",  os.path.join(REPO, "strategy_types.py"))
sys.modules["r_native"].strategy_types = st
store = _load("r_native.strategy_store", os.path.join(REPO, "strategy_store.py"))
li  = _load("r_native.live_indicators",  os.path.join(REPO, "live_indicators.py"))


# ─── strategy_types ──────────────────────────────────────────────
def test_strategy_roundtrip():
    s = st.Strategy.default("My Gold Strat")
    s.pairs = ["XAUUSDm"]; s.timeframe = "1h"
    d = s.to_dict()
    s2 = st.Strategy.from_dict(d)
    assert s2.name == "My Gold Strat"
    assert s2.pairs == ["XAUUSDm"]
    assert len(s2.indicators) == 11
    assert s2.risk.tpAtrMults == [1.0, 2.0, 3.0]
    print("OK test_strategy_roundtrip")


def test_riskconfig_coerces_targets():
    r = st.RiskConfig.from_dict({"tpAtrMults": [2, 4]})  # only 2 -> pad to 3
    assert len(r.tpAtrMults) == 3
    r2 = st.RiskConfig.from_dict({"trailAtrMult": "null"})
    assert r2.trailAtrMult is None
    print("OK test_riskconfig_coerces_targets")


def test_chart_analysis_targets_padding():
    ca = st.ChartAnalysis.from_dict({"symbol": "X", "timeframe": "1h",
                                      "targets": [1.0]})
    assert len(ca.targets) == 3
    print("OK test_chart_analysis_targets_padding")


# ─── strategy_store ──────────────────────────────────────────────
def test_store_crud():
    store.set_data_root(Path(tempfile.mkdtemp()))
    s = st.Strategy.default("Persisted")
    store.save_strategy(s)
    loaded = store.load_strategy(s.id)
    assert loaded is not None and loaded.name == "Persisted"
    lst = store.list_strategies()
    assert any(d["id"] == s.id for d in lst)
    # status change
    store.set_status(s.id, "ACTIVE")
    assert store.load_strategy(s.id).status == "ACTIVE"
    # delete
    assert store.delete_strategy(s.id) is True
    assert store.load_strategy(s.id) is None
    print("OK test_store_crud")


def test_store_log_feed():
    store.set_data_root(Path(tempfile.mkdtemp()))
    store.emit_log("ok", "Signal", "LONG_ENTRY @ 2400")
    store.emit_log("warn", "Risk", "skip — conf 0.61 < 0.70")
    logs = store.recent_logs(10)
    assert len(logs) == 2
    only_risk = store.recent_logs(10, tag="Risk")
    assert len(only_risk) == 1 and only_risk[0]["tag"] == "Risk"
    print("OK test_store_log_feed")


# ─── live_indicators ─────────────────────────────────────────────
def _bars_trend(n=120, up=True, slope=0.4):
    bars = []
    price = 100.0
    for i in range(n):
        o = price
        c = price + (slope if up else -slope)
        h = max(o, c) + 0.15
        l = min(o, c) - 0.15
        bars.append({"time": i, "open": o, "high": h, "low": l, "close": c})
        price = c
    return bars


def _bars_range(n=120, amp=1.0):
    bars = []
    for i in range(n):
        mid = 100.0 + amp * np.sin(i / 4.0)
        o = mid; c = mid + (0.05 if i % 2 == 0 else -0.05)
        bars.append({"time": i, "open": o, "high": max(o, c) + 0.3,
                     "low": min(o, c) - 0.3, "close": c})
    return bars


def test_indicators_bullish_trend():
    inds = li.compute_indicators(_bars_trend(up=True))
    assert len(inds) == 11
    bulls = sum(1 for i in inds if i.status == "BULLISH")
    # A clean uptrend should make MOST indicators bullish
    assert bulls >= 7, f"only {bulls}/11 bullish on uptrend"
    print(f"OK test_indicators_bullish_trend ({bulls}/11 bullish)")


def test_indicators_bearish_trend():
    inds = li.compute_indicators(_bars_trend(up=False))
    bears = sum(1 for i in inds if i.status == "BEARISH")
    assert bears >= 7, f"only {bears}/11 bearish on downtrend"
    print(f"OK test_indicators_bearish_trend ({bears}/11 bearish)")


def test_aggregate_signal_full_confluence():
    inds = li.compute_indicators(_bars_trend(up=True, slope=0.6))
    sig = li.aggregate_signal(inds)
    # If not all 11 align we expect NONE; verify the rule itself with a forced set
    for i in inds: i.status = "BULLISH"
    assert li.aggregate_signal(inds) == "LONG"
    for i in inds: i.status = "BEARISH"
    assert li.aggregate_signal(inds) == "SHORT"
    inds[0].status = "NEUTRAL"
    assert li.aggregate_signal(inds) == "NONE"
    print(f"OK test_aggregate_signal_full_confluence (live trend -> {sig})")


def test_confluence_score():
    inds = li.compute_indicators(_bars_trend(up=True))
    cs = li.confluence_score(inds)
    assert cs["enabled"] == 11
    assert cs["bullish"] + cs["bearish"] + cs["neutral"] == 11
    assert cs["dominant"] in ("LONG", "SHORT", "NONE")
    print(f"OK test_confluence_score (bull={cs['bullish']} bear={cs['bearish']})")


def test_disabled_indicator_excluded():
    inds = li.compute_indicators(_bars_trend(up=True))
    for i in inds: i.status = "BULLISH"
    inds[0].status = "BEARISH"
    inds[0].enabled = False        # disable the dissenter
    assert li.aggregate_signal(inds) == "LONG"
    print("OK test_disabled_indicator_excluded")


def test_indicators_no_crash_on_short_input():
    inds = li.compute_indicators([{"time": 0, "open": 1, "high": 1, "low": 1, "close": 1}])
    assert len(inds) == 11
    assert all(i.status in ("BULLISH", "BEARISH", "NEUTRAL") for i in inds)
    print("OK test_indicators_no_crash_on_short_input")


if __name__ == "__main__":
    test_strategy_roundtrip()
    test_riskconfig_coerces_targets()
    test_chart_analysis_targets_padding()
    test_store_crud()
    test_store_log_feed()
    test_indicators_bullish_trend()
    test_indicators_bearish_trend()
    test_aggregate_signal_full_confluence()
    test_confluence_score()
    test_disabled_indicator_excluded()
    test_indicators_no_crash_on_short_input()
    print("\n✓ all strategy-core tests passed")
