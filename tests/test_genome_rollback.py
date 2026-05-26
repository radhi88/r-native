"""Tests for genome_rollback evaluate_post_deploy + execute_rollback.

These tests stub out hall_of_fame and symbol-config disk access so we
don't need a real C:\\ path on Linux.
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import importlib.util
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_modname = "genome_rollback_under_test"
spec = importlib.util.spec_from_file_location(
    _modname, os.path.join(REPO, "genome_rollback.py"))
rb = importlib.util.module_from_spec(spec)
sys.modules[_modname] = rb
spec.loader.exec_module(rb)


def _setup_tmp_cfg(cfg: dict):
    tmpdir = Path(tempfile.mkdtemp())
    rb.SYMBOL_CFG    = tmpdir
    rb.ROLLBACK_LOG  = tmpdir / "rollback.jsonl"
    (tmpdir / "X.json").write_text(json.dumps(cfg), encoding="utf-8")


def _stub_hof_index(idx: dict):
    """Monkey-patch the hof import lookup inside rb to return our fake."""
    class _Stub:
        @staticmethod
        def load_index(): return idx
        INDEX_PATH = Path(tempfile.mktemp(suffix=".json"))
        @staticmethod
        def _write_json(p, d): p.write_text(json.dumps(d), encoding="utf-8")
    # Inject as module attribute the function imports go through
    sys.modules["r_native.hall_of_fame"] = _Stub
    # Also satisfy: from r_native import ... (top-level)
    if "r_native" not in sys.modules:
        sys.modules["r_native"] = type(sys)("r_native")
    sys.modules["r_native"].hall_of_fame = _Stub
    return _Stub


def test_no_previous_deploy_returns_ok_false():
    _setup_tmp_cfg({
        "deployed_genome": {"id": "NEW"},
    })
    out = rb.evaluate_post_deploy("X")
    assert out["ok"] is False
    assert "previous" in out["reason"].lower()
    print("OK test_no_previous_deploy_returns_ok_false")


def test_insufficient_trades_returns_no_regression():
    _setup_tmp_cfg({
        "deployed_genome":   {"id": "NEW"},
        "previous_deployed": {"id": "OLD"},
    })
    _stub_hof_index({
        "NEW": {"live_trades": 2, "live_winrate": 30},
        "OLD": {"live_trades": 50, "live_winrate": 60},
    })
    out = rb.evaluate_post_deploy("X", window_trades=10)
    assert out["ok"] is True
    assert out["regressed"] is False
    assert "need" in out["reason"]
    print("OK test_insufficient_trades_returns_no_regression")


def test_regression_detected_when_gap_exceeded():
    _setup_tmp_cfg({
        "deployed_genome":   {"id": "NEW"},
        "previous_deployed": {"id": "OLD"},
    })
    _stub_hof_index({
        "NEW": {"live_trades": 12, "live_winrate": 30},
        "OLD": {"live_trades": 80, "live_winrate": 55},
    })
    out = rb.evaluate_post_deploy("X", window_trades=10, regression_pct=15)
    assert out["ok"] is True
    assert out["regressed"] is True
    assert out["gap_pct"] == 25
    print("OK test_regression_detected_when_gap_exceeded")


def test_no_regression_when_within_tolerance():
    _setup_tmp_cfg({
        "deployed_genome":   {"id": "NEW"},
        "previous_deployed": {"id": "OLD"},
    })
    _stub_hof_index({
        "NEW": {"live_trades": 12, "live_winrate": 52},
        "OLD": {"live_trades": 80, "live_winrate": 58},
    })
    out = rb.evaluate_post_deploy("X", window_trades=10, regression_pct=15)
    assert out["ok"] is True
    assert out["regressed"] is False
    print("OK test_no_regression_when_within_tolerance")


def test_execute_rollback_swaps_deployed():
    _setup_tmp_cfg({
        "deployed_genome":   {"id": "NEW", "score": 80},
        "previous_deployed": {"id": "OLD", "score": 90},
    })
    _stub_hof_index({"NEW": {}, "OLD": {}})
    out = rb.execute_rollback("X", reason="test")
    assert out["ok"] is True
    assert out["restored"] == "OLD"
    assert out["failed"]   == "NEW"
    # Verify file state
    cfg = json.loads((rb.SYMBOL_CFG / "X.json").read_text(encoding="utf-8"))
    assert cfg["deployed_genome"]["id"]   == "OLD"
    assert cfg["previous_deployed"]       is None
    assert cfg["rolled_back_from"]["id"]  == "NEW"
    print("OK test_execute_rollback_swaps_deployed")


def test_execute_rollback_refuses_without_previous():
    _setup_tmp_cfg({"deployed_genome": {"id": "NEW"}})
    out = rb.execute_rollback("X", reason="test")
    assert out["ok"] is False
    print("OK test_execute_rollback_refuses_without_previous")


if __name__ == "__main__":
    test_no_previous_deploy_returns_ok_false()
    test_insufficient_trades_returns_no_regression()
    test_regression_detected_when_gap_exceeded()
    test_no_regression_when_within_tolerance()
    test_execute_rollback_swaps_deployed()
    test_execute_rollback_refuses_without_previous()
    print("\n✓ all genome_rollback tests passed")
