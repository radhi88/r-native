"""End-to-end: polish -> create -> activate -> evaluate -> decision feed.

Stubs agents/llm + injects bars so it runs with no Ollama/Claude/MT5.
Mirrors the path the 4 dashboard pages drive through the /api endpoints.
"""
from __future__ import annotations

import os
import sys
import types
import json
import tempfile
import importlib.util
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _pkg():
    if "r_native" not in sys.modules:
        p = types.ModuleType("r_native"); p.__path__ = [REPO]; sys.modules["r_native"] = p
    if "r_native.agents" not in sys.modules:
        a = types.ModuleType("r_native.agents"); a.__path__ = [os.path.join(REPO, "agents")]
        sys.modules["r_native.agents"] = a; sys.modules["r_native"].agents = a


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec); sys.modules[modname] = m
    spec.loader.exec_module(m)
    parent, _, child = modname.rpartition(".")
    if parent in sys.modules: setattr(sys.modules[parent], child, m)
    return m


_pkg()
_load("r_native.strategy_types",  os.path.join(REPO, "strategy_types.py"))
_load("r_native.live_indicators", os.path.join(REPO, "live_indicators.py"))
_load("r_native.smc_engine",      os.path.join(REPO, "smc_engine.py"))
_load("r_native.signal_engine",   os.path.join(REPO, "signal_engine.py"))

# Fake LLM that returns a valid strategy JSON
fake = types.ModuleType("r_native.agents.llm")
fake.ask = lambda prompt="", system="", preferred_backend="auto", model=None, temperature=0.3, ollama_fallback_models=None: {
    "ok": True, "backend": "fake",
    "text": json.dumps({
        "name": "E2E Strat", "systemPrompt": "buy demand OBs",
        "methodology": "SMC", "pairs": ["XAUUSDm"], "timeframe": "15m",
        "indicators": [{"key": "rsi", "label": "RSI", "enabled": True}],
        "entryConditions": [{"side": "BUY", "text": "bullish BOS", "confidence": 80}],
        "risk": {"minConfidence": 0, "tpAtrMults": [1, 2, 3]},
    })}
fake.extract_json = lambda t: json.loads(t[t.find("{"):]) if t and "{" in t else None
sys.modules["r_native.agents.llm"] = fake; sys.modules["r_native.agents"].llm = fake

sb    = _load("r_native.strategy_builder",  os.path.join(REPO, "strategy_builder.py"))
store = _load("r_native.strategy_store",    os.path.join(REPO, "strategy_store.py"))
mon   = _load("r_native.strategy_monitor",  os.path.join(REPO, "strategy_monitor.py"))
st    = sys.modules["r_native.strategy_types"]

store.set_data_root(Path(tempfile.mkdtemp()))


def _bars(up=True, n=140, slope=0.6):
    out=[];p=100.0
    for i in range(n):
        o=p;c=p+(slope if up else -slope)
        out.append({"time":i,"open":o,"high":max(o,c)+0.15,"low":min(o,c)-0.15,"close":c});p=c
    return out


def test_full_lifecycle():
    # 1) Polish (Claude Call A)
    res = sb.polish_strategy("buy gold dips", name_hint="Gold", pairs_hint=["XAUUSDm"])
    assert res["ok"] is True
    strat = st.Strategy.from_dict(res["strategy"])
    assert len(strat.indicators) == 11

    # 2) Create (persist)
    saved = store.save_strategy(strat)
    assert store.load_strategy(strat.id) is not None

    # 3) Activate
    store.set_status(strat.id, "ACTIVE")
    assert store.load_strategy(strat.id).status == "ACTIVE"

    # 4) Evaluate (with injected bars, minConfidence 0 to exercise entry path)
    active = store.load_strategy(strat.id)
    logs = mon.evaluate_strategy_once(active, bars_by_symbol={"XAUUSDm": _bars(up=True)})
    assert any("Evaluating XAUUSDm" in l["text"] for l in logs)

    # 5) Decision feed visible
    feed = store.recent_logs(50)
    assert len(feed) >= 2
    print(f"OK test_full_lifecycle ({len(logs)} eval lines, {len(feed)} in feed)")


def test_list_reflects_status_changes():
    s = st.Strategy.default("Toggle Me"); store.save_strategy(s)
    store.set_status(s.id, "ACTIVE")
    lst = store.list_strategies()
    row = [d for d in lst if d["id"] == s.id][0]
    assert row["status"] == "ACTIVE"
    store.set_status(s.id, "STOPPED")
    row2 = [d for d in store.list_strategies() if d["id"] == s.id][0]
    assert row2["status"] == "STOPPED"
    print("OK test_list_reflects_status_changes")


if __name__ == "__main__":
    test_full_lifecycle()
    test_list_reflects_status_changes()
    print("\n✓ all pipflow-e2e tests passed")
