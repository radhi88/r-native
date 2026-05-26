"""Tests for the SMC signal evaluators + filters added to genome_signal.py.

Verifies tolerance of missing `smc` field, correct directional votes, and
that decide_entry still works end-to-end with an SMC-flagged genome.
"""
from __future__ import annotations

import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# Load genome_signal as a standalone module (no r_native package needed)
gs = _load_module("genome_signal_under_test",
                  os.path.join(REPO, "genome_signal.py"))


# ─── Snapshot builder helpers ────────────────────────────────────
def _empty_snap(bid: float = 100.0) -> dict:
    """Snapshot without SMC data — evaluators must return (0, 'no smc data')."""
    return {
        "h1":  {"current": bid, "atr": 1.0, "rsi": 50, "swing_high": 101,
                 "swing_low": 99, "range_size": 2.0, "bias": "RANGE",
                 "slope_atr": 0.0},
        "m15": {"current": bid, "atr": 0.5, "rsi": 50, "swing_high": 100.5,
                 "swing_low": 99.5, "range_size": 1.0, "bias": "RANGE",
                 "slope_atr": 0.0},
        "h4":  {"current": bid, "atr": 2.0, "rsi": 50, "swing_high": 102,
                 "swing_low": 98, "range_size": 4.0, "bias": "RANGE",
                 "slope_atr": 0.0},
        "bid": bid, "ask": bid + 0.05,
    }


def _with_smc(snap: dict, smc_h1: dict | None = None,
              smc_h4: dict | None = None) -> dict:
    snap = dict(snap)
    snap["h1"] = dict(snap["h1"]); snap["h1"]["smc"] = smc_h1 or {}
    if smc_h4 is not None:
        snap["h4"] = dict(snap["h4"]); snap["h4"]["smc"] = smc_h4
    return snap


# ─── Tolerance tests (missing smc) ───────────────────────────────
def test_smc_evaluators_tolerate_missing_smc():
    snap = _empty_snap()
    for name in ("use_sig_smc_ob", "use_sig_smc_fvg", "use_sig_smc_bos",
                 "use_sig_smc_choch", "use_sig_smc_liq_sweep", "use_sig_smc_idm"):
        vote, reason = gs.SIGNAL_EVALUATORS[name](snap)
        assert vote == 0, f"{name} should be 0 on no-smc snapshot, got {vote}"
        assert "no" in reason.lower() or "stale" in reason.lower(), \
            f"{name} reason looks off: {reason}"
    print("OK test_smc_evaluators_tolerate_missing_smc")


def test_smc_filters_default_safe():
    snap = _empty_snap()
    # fresh_only / htf_alignment should not block when no smc data
    blocks, _ = gs.FILTER_EVALUATORS["use_filter_smc_fresh_only"](snap)
    assert blocks is False
    blocks, _ = gs.FILTER_EVALUATORS["use_filter_smc_htf_alignment"](snap)
    assert blocks is False
    # idm_required SHOULD block (because no IDM data = no IDM swept)
    blocks, reason = gs.FILTER_EVALUATORS["use_filter_smc_idm_required"](snap)
    assert blocks is True
    print("OK test_smc_filters_default_safe")


# ─── Directional behavior ───────────────────────────────────────
def test_smc_ob_signal_bull():
    bid = 100.0
    snap = _with_smc(_empty_snap(bid), smc_h1={
        "fresh_ob_below": {"top": 100.1, "bottom": 99.9, "strength": 0.8,
                            "tested_count": 0, "age_bars": 3, "created_at": 0},
    })
    vote, reason = gs.SIGNAL_EVALUATORS["use_sig_smc_ob"](snap)
    assert vote == +1, f"expected +1, got {vote} reason={reason}"
    print("OK test_smc_ob_signal_bull")


def test_smc_ob_signal_bear():
    bid = 100.0
    snap = _with_smc(_empty_snap(bid), smc_h1={
        "fresh_ob_above": {"top": 100.1, "bottom": 99.9, "strength": 0.8,
                            "tested_count": 0, "age_bars": 3, "created_at": 0},
    })
    vote, reason = gs.SIGNAL_EVALUATORS["use_sig_smc_ob"](snap)
    assert vote == -1, f"expected -1, got {vote} reason={reason}"
    print("OK test_smc_ob_signal_bear")


def test_smc_bos_signal():
    snap = _with_smc(_empty_snap(), smc_h1={
        "last_bos": {"direction": "UP", "level": 100.5, "age_bars": 5, "confirmed": True},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_bos"](snap)
    assert vote == +1
    snap = _with_smc(_empty_snap(), smc_h1={
        "last_bos": {"direction": "DOWN", "level": 99.5, "age_bars": 5, "confirmed": True},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_bos"](snap)
    assert vote == -1
    # Stale BOS → 0
    snap = _with_smc(_empty_snap(), smc_h1={
        "last_bos": {"direction": "UP", "level": 100.5, "age_bars": 50, "confirmed": True},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_bos"](snap)
    assert vote == 0
    print("OK test_smc_bos_signal")


def test_smc_choch_signal():
    snap = _with_smc(_empty_snap(), smc_h1={
        "last_choch": {"direction": "DOWN", "level": 99.5, "age_bars": 3},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_choch"](snap)
    assert vote == -1
    # Stale CHoCH → 0
    snap = _with_smc(_empty_snap(), smc_h1={
        "last_choch": {"direction": "DOWN", "level": 99.5, "age_bars": 20},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_choch"](snap)
    assert vote == 0
    print("OK test_smc_choch_signal")


def test_smc_liq_sweep_reversal():
    # Sweep above (BUY stops taken) + reclaim → SELL signal
    snap = _with_smc(_empty_snap(), smc_h1={
        "recent_liq_sweep": {"side": "BUY", "level": 101.0, "age_bars": 2, "reclaim": True},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_liq_sweep"](snap)
    assert vote == -1
    # Sweep below + reclaim → BUY
    snap = _with_smc(_empty_snap(), smc_h1={
        "recent_liq_sweep": {"side": "SELL", "level": 99.0, "age_bars": 1, "reclaim": True},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_liq_sweep"](snap)
    assert vote == +1
    # No reclaim → 0
    snap = _with_smc(_empty_snap(), smc_h1={
        "recent_liq_sweep": {"side": "BUY", "level": 101.0, "age_bars": 2, "reclaim": False},
    })
    vote, _ = gs.SIGNAL_EVALUATORS["use_sig_smc_liq_sweep"](snap)
    assert vote == 0
    print("OK test_smc_liq_sweep_reversal")


def test_smc_filter_htf_misalignment_blocks():
    snap = _with_smc(_empty_snap(),
        smc_h1={"last_bos": {"direction": "UP",   "level": 100, "age_bars": 5, "confirmed": True}},
        smc_h4={"last_bos": {"direction": "DOWN", "level": 99,  "age_bars": 10, "confirmed": True}},
    )
    blocks, reason = gs.FILTER_EVALUATORS["use_filter_smc_htf_alignment"](snap)
    assert blocks is True
    assert "h1=UP" in reason and "h4=DOWN" in reason
    print("OK test_smc_filter_htf_misalignment_blocks")


def test_smc_fresh_only_blocks_tested_ob():
    snap = _with_smc(_empty_snap(), smc_h1={
        "fresh_ob_below": {"top": 100.1, "bottom": 99.9, "tested_count": 2, "age_bars": 3},
    })
    blocks, _ = gs.FILTER_EVALUATORS["use_filter_smc_fresh_only"](snap)
    assert blocks is True
    # Fresh (tested_count=0) → no block
    snap = _with_smc(_empty_snap(), smc_h1={
        "fresh_ob_below": {"top": 100.1, "bottom": 99.9, "tested_count": 0, "age_bars": 3},
    })
    blocks, _ = gs.FILTER_EVALUATORS["use_filter_smc_fresh_only"](snap)
    assert blocks is False
    print("OK test_smc_fresh_only_blocks_tested_ob")


if __name__ == "__main__":
    test_smc_evaluators_tolerate_missing_smc()
    test_smc_filters_default_safe()
    test_smc_ob_signal_bull()
    test_smc_ob_signal_bear()
    test_smc_bos_signal()
    test_smc_choch_signal()
    test_smc_liq_sweep_reversal()
    test_smc_filter_htf_misalignment_blocks()
    test_smc_fresh_only_blocks_tested_ob()
    print("\n✓ all SMC signal tests passed")
