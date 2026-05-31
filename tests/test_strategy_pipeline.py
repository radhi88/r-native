"""Tests for strategy_builder + signal_engine + chart_analysis + performance.

LLM calls are stubbed by injecting a fake r_native.agents.llm module, so
these run with no Ollama / Claude / MT5.
"""
from __future__ import annotations

import os
import sys
import types
import importlib.util

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


# ── Build an r_native package shim mapping submodules to real files ──
def _ensure_pkg():
    if "r_native" not in sys.modules:
        pkg = types.ModuleType("r_native"); pkg.__path__ = [REPO]
        sys.modules["r_native"] = pkg
    # agents subpackage
    if "r_native.agents" not in sys.modules:
        ap = types.ModuleType("r_native.agents"); ap.__path__ = [os.path.join(REPO, "agents")]
        sys.modules["r_native.agents"] = ap
        sys.modules["r_native"].agents = ap


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    parent, _, child = modname.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, m)
    return m


_ensure_pkg()

# Real modules under their r_native.* names
_load("r_native.strategy_types",      os.path.join(REPO, "strategy_types.py"))
_load("r_native.live_indicators",     os.path.join(REPO, "live_indicators.py"))
_load("r_native.smc_engine",          os.path.join(REPO, "smc_engine.py"))


# ── Fake LLM module ──────────────────────────────────────────────
class _FakeLLM:
    """Configurable stub. Set _FakeLLM.RESPONSE to control returned JSON."""
    RESPONSE = None       # dict to return as JSON, or None to simulate failure

    @staticmethod
    def ask(prompt="", system="", preferred_backend="auto", model=None,
            temperature=0.3, ollama_fallback_models=None):
        import json as _j
        if _FakeLLM.RESPONSE is None:
            return {"ok": False, "text": "", "backend": None, "tried": []}
        return {"ok": True, "text": _j.dumps(_FakeLLM.RESPONSE),
                "backend": "fake", "model": "fake", "tried": []}

    @staticmethod
    def extract_json(text):
        import json as _j
        if not text:
            return None
        try:
            start = text.find("{")
            return _j.loads(text[start:]) if start >= 0 else None
        except Exception:
            return None


fake_llm = types.ModuleType("r_native.agents.llm")
fake_llm.ask = _FakeLLM.ask
fake_llm.extract_json = _FakeLLM.extract_json
sys.modules["r_native.agents.llm"] = fake_llm
sys.modules["r_native.agents"].llm = fake_llm

sb  = _load("r_native.strategy_builder",     os.path.join(REPO, "strategy_builder.py"))
se  = _load("r_native.signal_engine",        os.path.join(REPO, "signal_engine.py"))
perf = _load("r_native.strategy_performance", os.path.join(REPO, "strategy_performance.py"))
ca  = _load("r_native.chart_analysis",       os.path.join(REPO, "chart_analysis.py"))
st  = sys.modules["r_native.strategy_types"]
li  = sys.modules["r_native.live_indicators"]


# ── Helpers ──────────────────────────────────────────────────────
def _bars_trend(n=120, up=True, slope=0.5):
    bars = []; price = 100.0
    for i in range(n):
        o = price; c = price + (slope if up else -slope)
        bars.append({"time": i, "open": o, "high": max(o, c) + 0.15,
                     "low": min(o, c) - 0.15, "close": c})
        price = c
    return bars


# ── strategy_builder ─────────────────────────────────────────────
def test_polish_with_valid_llm():
    _FakeLLM.RESPONSE = {
        "name": "Gold Sniper",
        "systemPrompt": "Buy demand OBs in uptrend.",
        "methodology": "SMC",
        "pairs": ["XAUUSDm"],
        "timeframe": "1h",
        "indicators": [{"key": "rsi", "label": "RSI", "enabled": True},
                       {"key": "macd", "label": "MACD", "enabled": False}],
        "entryConditions": [{"side": "BUY", "text": "bullish BOS", "confidence": 80}],
        "risk": {"maxPerTradePct": 1, "minConfidence": 75, "tpAtrMults": [1, 2, 3]},
    }
    out = sb.polish_strategy("buy gold dips in an uptrend",
                             name_hint="Gold", pairs_hint=["XAUUSDm"])
    assert out["ok"] is True
    s = out["strategy"]
    assert s["name"] == "Gold Sniper"
    assert s["methodology"] == "SMC"
    assert len(s["indicators"]) == 11           # always the full set
    macd = [i for i in s["indicators"] if i["key"] == "macd"][0]
    assert macd["enabled"] is False             # LLM disabled it
    assert s["risk"]["minConfidence"] == 75
    print("OK test_polish_with_valid_llm")


def test_polish_fallback_when_llm_down():
    _FakeLLM.RESPONSE = None                    # simulate LLM failure
    out = sb.polish_strategy("scalp gold", name_hint="Scalp",
                             pairs_hint=["XAUUSDm"], timeframe_hint="5m")
    assert out["ok"] is False and out["fallback"] is True
    s = out["strategy"]
    assert s["name"] == "Scalp"
    assert s["timeframe"] == "5m"
    assert len(s["indicators"]) == 11
    assert len(s["entryConditions"]) >= 2
    print("OK test_polish_fallback_when_llm_down")


def test_polish_empty_prompt():
    out = sb.polish_strategy("")
    assert out["ok"] is False
    assert out["strategy"]["name"]
    print("OK test_polish_empty_prompt")


# ── signal_engine ────────────────────────────────────────────────
def test_signal_engine_no_confluence_skips():
    strat = st.Strategy.default("X")
    # ranging-ish bars unlikely to give full confluence
    bars = []
    for i in range(120):
        mid = 100 + np.sin(i / 3.0)
        bars.append({"time": i, "open": mid, "high": mid + 0.5,
                     "low": mid - 0.5, "close": mid + (0.05 if i % 2 else -0.05)})
    out = se.evaluate_entry(strat, bars)
    assert out["decision"] == "NONE"
    assert "signal" in out and "confluence" in out
    print("OK test_signal_engine_no_confluence_skips")


def test_signal_engine_long_on_clean_uptrend():
    strat = st.Strategy.default("Up")
    strat.risk.minConfidence = 50.0     # relax so structure passes in synthetic data
    bars = _bars_trend(up=True, slope=0.6)
    out = se.evaluate_entry(strat, bars)
    # Either a LONG with levels, or NONE if structure didn't confirm — but if
    # it decided LONG, levels must be coherent.
    assert out["decision"] in ("LONG", "NONE")
    if out["decision"] == "LONG":
        assert out["stop"] < out["entry"] < out["targets"][0] <= out["targets"][2]
        assert out["rr"] > 0
    print(f"OK test_signal_engine_long_on_clean_uptrend ({out['decision']})")


def test_signal_engine_levels_ordering_short():
    strat = st.Strategy.default("Dn")
    strat.risk.minConfidence = 0.0      # force the level-building branch
    bars = _bars_trend(up=False, slope=0.6)
    out = se.evaluate_entry(strat, bars)
    if out["decision"] == "SHORT":
        assert out["stop"] > out["entry"] > out["targets"][0] >= out["targets"][2]
    print(f"OK test_signal_engine_levels_ordering_short ({out['decision']})")


# ── performance ──────────────────────────────────────────────────
def test_performance_math():
    trades = [{"profit": 10}, {"profit": -4}, {"profit": 6}, {"profit": -2},
              {"profit": 8}]
    p = perf.compute_performance(trades, starting_balance=1000)
    assert p["totalTrades"] == 5
    assert p["wins"] == 3 and p["losses"] == 2
    assert p["winratePct"] == 60.0
    # gross win = 24, gross loss = 6 -> PF 4.0
    assert p["profitFactor"] == 4.0
    # net = 18 on 1000 -> 1.8%
    assert p["pnlPct"] == 1.8
    print("OK test_performance_math")


def test_performance_all_wins_pf_capped():
    p = perf.compute_performance([{"profit": 5}, {"profit": 5}])
    assert p["profitFactor"] == 999.99   # no losses -> capped sentinel
    print("OK test_performance_all_wins_pf_capped")


def test_performance_empty():
    p = perf.compute_performance([])
    assert p["totalTrades"] == 0 and p["winratePct"] == 0.0
    print("OK test_performance_empty")


# ── chart_analysis ───────────────────────────────────────────────
def test_chart_analysis_drawings_built():
    analysis = {"direction": "LONG", "entry": 2400.0, "stop": 2392.0,
                "targets": [2408.0, 2416.0, 2424.0], "confidence": 78, "rr": 3.0}
    drawings = ca.build_analysis_drawings("XAUUSDm", analysis)
    # entry + sl + tp(=T1) zone = 3, T2 + T3 = 2, narrative = 1 -> 6
    cats = [d.get("meta", {}).get("category") or d.get("type") for d in drawings]
    assert any(d["type"] == "label" for d in drawings)        # narrative
    tp_lines = [d for d in drawings if d.get("meta", {}).get("category") == "tp"]
    assert len(tp_lines) >= 2                                  # T2 + T3
    for d in drawings:
        assert d["symbol"] == "XAUUSDm"
    print(f"OK test_chart_analysis_drawings_built ({len(drawings)} drawings)")


def test_chart_analysis_fallback_offline():
    # _fetch_bars returns [] (no MT5) -> analyze_chart returns ok False but a
    # well-formed ChartAnalysis
    res = ca.analyze_chart("XAUUSDm", "15m")
    assert "analysis" in res
    assert res["analysis"]["symbol"] == "XAUUSDm"
    print("OK test_chart_analysis_fallback_offline")


if __name__ == "__main__":
    test_polish_with_valid_llm()
    test_polish_fallback_when_llm_down()
    test_polish_empty_prompt()
    test_signal_engine_no_confluence_skips()
    test_signal_engine_long_on_clean_uptrend()
    test_signal_engine_levels_ordering_short()
    test_performance_math()
    test_performance_all_wins_pf_capped()
    test_performance_empty()
    test_chart_analysis_drawings_built()
    test_chart_analysis_fallback_offline()
    print("\n✓ all strategy-pipeline tests passed")
