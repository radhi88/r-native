"""Tests for the SMC lane classification (Phase 5).

These tests only exercise the pure-function `_classify_lane` and the
`get_elites_by_lane` filtering logic — they don't write to the on-disk
Hall of Fame so they're safe to run anywhere.
"""
from __future__ import annotations

import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_modname = "hall_of_fame_under_test"
spec = importlib.util.spec_from_file_location(_modname, os.path.join(REPO, "hall_of_fame.py"))
hof = importlib.util.module_from_spec(spec)
sys.modules[_modname] = hof
spec.loader.exec_module(hof)


# ─── _classify_lane unit tests ───────────────────────────────────
def test_classify_empty_is_classic():
    assert hof._classify_lane([]) == "classic"
    assert hof._classify_lane(None) == "classic"
    print("OK test_classify_empty_is_classic")


def test_classify_traditional_is_classic():
    assert hof._classify_lane(["use_sig_breakout", "use_sig_rsi", "use_bias_ema"]) == "classic"
    print("OK test_classify_traditional_is_classic")


def test_classify_any_smc_is_smc():
    assert hof._classify_lane(["use_sig_breakout", "use_sig_smc_ob"]) == "smc"
    assert hof._classify_lane(["use_sig_smc_fvg"]) == "smc"
    assert hof._classify_lane(["sl_anchor_smc_ob"]) == "smc"
    assert hof._classify_lane(["use_filter_smc_idm_required"]) == "smc"
    print("OK test_classify_any_smc_is_smc")


# ─── get_elites_by_lane filtering ────────────────────────────────
def _fake_entries():
    return [
        {"id": "A", "score": 90, "active_genes": ["use_sig_breakout"], "lane": "classic"},
        {"id": "B", "score": 85, "active_genes": ["use_sig_smc_ob", "use_sig_rsi"], "lane": "smc"},
        {"id": "C", "score": 80, "active_genes": ["use_sig_macd"], "lane": "classic"},
        {"id": "D", "score": 75, "active_genes": ["use_sig_smc_choch"], "lane": "smc"},
        {"id": "E", "score": 60, "active_genes": ["use_sig_smc_fvg"]},   # no lane field — backfill
        {"id": "F", "score": 50, "active_genes": ["use_sig_engulfing"], "killed": True},
    ]


def test_get_elites_by_lane(monkey=None):
    # Monkey-patch load_symbol and load_pinned to return fakes
    orig_load_sym    = hof.load_symbol
    orig_load_pinned = hof.load_pinned
    hof.load_symbol  = lambda symbol: _fake_entries()
    hof.load_pinned  = lambda: []
    try:
        smc     = hof.get_elites_by_lane("X", "smc", n=5)
        classic = hof.get_elites_by_lane("X", "classic", n=5)
        smc_ids     = [e["id"] for e in smc]
        classic_ids = [e["id"] for e in classic]
        # E has no lane field but uses use_sig_smc_fvg → must be classified smc by backfill
        assert smc_ids == ["B", "D", "E"], f"smc lane got {smc_ids}"
        # Classics, F is killed → excluded
        assert classic_ids == ["A", "C"], f"classic lane got {classic_ids}"
        print("OK test_get_elites_by_lane")
    finally:
        hof.load_symbol  = orig_load_sym
        hof.load_pinned  = orig_load_pinned


def test_lane_summary():
    orig_load_sym    = hof.load_symbol
    orig_load_pinned = hof.load_pinned
    hof.load_symbol  = lambda symbol: _fake_entries()
    hof.load_pinned  = lambda: []
    try:
        s = hof.lane_summary("X")
        assert s["smc"]["count"] == 3
        assert s["smc"]["best_id"] == "B"
        assert s["smc"]["best_score"] == 85
        assert s["classic"]["count"] == 2
        assert s["classic"]["best_id"] == "A"
        assert s["classic"]["best_score"] == 90
        print("OK test_lane_summary")
    finally:
        hof.load_symbol  = orig_load_sym
        hof.load_pinned  = orig_load_pinned


if __name__ == "__main__":
    test_classify_empty_is_classic()
    test_classify_traditional_is_classic()
    test_classify_any_smc_is_smc()
    test_get_elites_by_lane()
    test_lane_summary()
    print("\n✓ all hof lane tests passed")
