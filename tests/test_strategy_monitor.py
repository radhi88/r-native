"""Tests for strategy_monitor — evaluate_strategy_once emits the right log
feed without MT5 (bars injected)."""
from __future__ import annotations

import os
import sys
import types
import tempfile
import importlib.util
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _ensure_pkg():
    if "r_native" not in sys.modules:
        pkg = types.ModuleType("r_native"); pkg.__path__ = [REPO]
        sys.modules["r_native"] = pkg


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec); sys.modules[modname] = m
    spec.loader.exec_module(m)
    parent, _, child = modname.rpartition(".")
    if parent in sys.modules:
        setattr(sys.modules[parent], child, m)
    return m


_ensure_pkg()
_load("r_native.strategy_types",  os.path.join(REPO, "strategy_types.py"))
_load("r_native.live_indicators", os.path.join(REPO, "live_indicators.py"))
_load("r_native.smc_engine",      os.path.join(REPO, "smc_engine.py"))
_load("r_native.signal_engine",   os.path.join(REPO, "signal_engine.py"))
store = _load("r_native.strategy_store", os.path.join(REPO, "strategy_store.py"))
mon   = _load("r_native.strategy_monitor", os.path.join(REPO, "strategy_monitor.py"))
st    = sys.modules["r_native.strategy_types"]

store.set_data_root(Path(tempfile.mkdtemp()))


def _bars_trend(n=140, up=True, slope=0.6):
    bars = []; price = 100.0
    for i in range(n):
        o = price; c = price + (slope if up else -slope)
        bars.append({"time": i, "open": o, "high": max(o, c) + 0.15,
                     "low": min(o, c) - 0.15, "close": c})
        price = c
    return bars


def test_paused_strategy_skipped():
    s = st.Strategy.default("Paused"); s.status = "PAUSED"; s.pairs = ["XAUUSDm"]
    logs = mon.evaluate_strategy_once(s)
    assert len(logs) == 1
    assert "status PAUSED" in logs[0]["text"]
    print("OK test_paused_strategy_skipped")


def test_no_pairs_warns():
    s = st.Strategy.default("NoPairs"); s.status = "ACTIVE"; s.pairs = []
    logs = mon.evaluate_strategy_once(s)
    assert logs[0]["level"] == "warn"
    print("OK test_no_pairs_warns")


def test_active_evaluation_emits_feed():
    s = st.Strategy.default("Live"); s.status = "ACTIVE"; s.pairs = ["XAUUSDm"]
    s.risk.minConfidence = 0.0      # force the entry branch to exercise the OK log
    bars = {"XAUUSDm": _bars_trend(up=True)}
    logs = mon.evaluate_strategy_once(s, bars_by_symbol=bars)
    texts = [l["text"] for l in logs]
    assert any("Evaluating XAUUSDm" in t for t in texts)
    assert any("confluence" in t for t in texts)
    # With minConfidence 0 and a clean uptrend we expect an ENTRY or a no-setup,
    # but never a crash; if entry fired, it's tagged ok.
    print(f"OK test_active_evaluation_emits_feed ({len(logs)} lines)")


def test_insufficient_bars_warns():
    s = st.Strategy.default("Short"); s.status = "ACTIVE"; s.pairs = ["XAUUSDm"]
    logs = mon.evaluate_strategy_once(s, bars_by_symbol={"XAUUSDm": _bars_trend(n=10)})
    assert any(l["level"] == "warn" for l in logs)
    print("OK test_insufficient_bars_warns")


def test_feed_persisted_to_store():
    s = st.Strategy.default("Persist"); s.status = "ACTIVE"; s.pairs = ["XAUUSDm"]
    mon.evaluate_strategy_once(s, bars_by_symbol={"XAUUSDm": _bars_trend()})
    feed = store.recent_logs(50)
    assert len(feed) >= 1
    print(f"OK test_feed_persisted_to_store ({len(feed)} in ring)")


if __name__ == "__main__":
    test_paused_strategy_skipped()
    test_no_pairs_warns()
    test_active_evaluation_emits_feed()
    test_insufficient_bars_warns()
    test_feed_persisted_to_store()
    print("\n✓ all strategy-monitor tests passed")
