"""Tests for sl_tp_resolver — SMC-anchored SL/TP placement."""
from __future__ import annotations

import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("sl_tp_resolver_under_test",
                                              os.path.join(REPO, "sl_tp_resolver.py"))
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)


def _genome(flags: dict | None = None, params: dict | None = None) -> dict:
    p = {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0, "smc_ob_buffer_atr": 0.3}
    if params: p.update(params)
    return {"flags": flags or {}, "params": p}


def _snap(smc_h1: dict | None = None, **kwargs) -> dict:
    snap = {
        "h1":  {"current": 100.0, "atr": 1.0, "swing_high": 101.5, "swing_low": 98.5},
        "m15": {}, "h4": {},
        "bid": 100.0, "ask": 100.05,
    }
    snap["h1"]["smc"] = smc_h1 or {}
    snap.update(kwargs)
    return snap


# ─── Fallback (pure ATR) ────────────────────────────────────────
def test_fallback_atr_buy():
    out = r.resolve_sl_tp(_genome(), "BUY", entry=100.0, snap=_snap(), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "atr"
    assert out["sl"] < 100.0     # SL below entry
    assert out["near_tp"] > 100.0 and out["far_tp"] > out["near_tp"]
    print("OK test_fallback_atr_buy")


def test_fallback_atr_sell():
    out = r.resolve_sl_tp(_genome(), "SELL", entry=100.0, snap=_snap(), h1_atr=1.0)
    assert out["ok"]
    assert out["sl"] > 100.0
    assert out["near_tp"] < 100.0 and out["far_tp"] < out["near_tp"]
    print("OK test_fallback_atr_sell")


def test_bad_side():
    out = r.resolve_sl_tp(_genome(), "FOO", entry=100.0, snap=_snap(), h1_atr=1.0)
    assert out.get("ok") is False or "bad side" in str(out.get("reasoning", []))
    print("OK test_bad_side")


# ─── SMC OB SL anchor ───────────────────────────────────────────
def test_sl_anchor_ob_buy():
    smc = {"fresh_ob_below": {"top": 99.5, "bottom": 99.0, "strength": 0.7}}
    g = _genome(flags={"sl_anchor_smc_ob": True}, params={"smc_ob_buffer_atr": 0.2})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "smc_ob"
    # SL = ob_bottom - 0.2 × 1.0 = 99.0 - 0.2 = 98.8
    assert abs(out["sl"] - 98.8) < 1e-9, f"got sl={out['sl']}"
    assert out["anchor_levels"]["ob_used"]["bottom"] == 99.0
    print("OK test_sl_anchor_ob_buy")


def test_sl_anchor_ob_sell():
    smc = {"fresh_ob_above": {"top": 100.5, "bottom": 100.2, "strength": 0.6}}
    g = _genome(flags={"sl_anchor_smc_ob": True}, params={"smc_ob_buffer_atr": 0.2})
    out = r.resolve_sl_tp(g, "SELL", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "smc_ob"
    # SL = ob_top + 0.2 = 100.5 + 0.2 = 100.7
    assert abs(out["sl"] - 100.7) < 1e-9, f"got sl={out['sl']}"
    print("OK test_sl_anchor_ob_sell")


def test_sl_anchor_ob_missing_falls_back_to_atr():
    g = _genome(flags={"sl_anchor_smc_ob": True})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc_h1={}), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "atr"    # fell back when no OB available
    print("OK test_sl_anchor_ob_missing_falls_back_to_atr")


# ─── SMC swing SL anchor ────────────────────────────────────────
def test_sl_anchor_swing_buy():
    g = _genome(flags={"sl_anchor_smc_swing": True}, params={"smc_ob_buffer_atr": 0.1})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "smc_swing"
    # SL = swing_low - 0.1 × atr = 98.5 - 0.1 = 98.4
    assert abs(out["sl"] - 98.4) < 1e-9, f"got sl={out['sl']}"
    print("OK test_sl_anchor_swing_buy")


# ─── SMC liquidity TP anchor ────────────────────────────────────
def test_tp_target_liq_buy():
    smc = {"liq_above": [101.0, 102.5, 104.0]}
    g = _genome(flags={"tp_target_smc_liq": True})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    assert out["tp_anchor"] == "smc_liq"
    assert out["near_tp"] == 101.0
    assert out["far_tp"] == 102.5
    print("OK test_tp_target_liq_buy")


def test_tp_target_liq_sell():
    smc = {"liq_below": [99.0, 97.5, 96.0]}
    g = _genome(flags={"tp_target_smc_liq": True})
    out = r.resolve_sl_tp(g, "SELL", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    # liq_below sorted desc → 99 nearer, 97.5 further
    assert out["near_tp"] == 99.0
    assert out["far_tp"] == 97.5
    print("OK test_tp_target_liq_sell")


# ─── SMC opposite OB TP anchor ──────────────────────────────────
def test_tp_target_opposite_ob_buy():
    smc = {"fresh_ob_above": {"top": 102.5, "bottom": 102.0}}
    g = _genome(flags={"tp_target_smc_ob": True})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    assert out["tp_anchor"] == "smc_ob"
    # far_tp = (102.5 + 102.0) / 2 = 102.25
    assert abs(out["far_tp"] - 102.25) < 1e-9
    print("OK test_tp_target_opposite_ob_buy")


def test_combined_ob_sl_and_liq_tp():
    smc = {
        "fresh_ob_below": {"top": 99.5, "bottom": 99.0},
        "liq_above":      [101.0, 102.5],
    }
    g = _genome(flags={"sl_anchor_smc_ob": True, "tp_target_smc_liq": True})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc), h1_atr=1.0)
    assert out["ok"]
    assert out["sl_anchor"] == "smc_ob"
    assert out["tp_anchor"] == "smc_liq"
    assert out["sl"] < 100.0 < out["near_tp"] < out["far_tp"]
    print("OK test_combined_ob_sl_and_liq_tp")


def test_max_sl_dist_rejects():
    smc = {"fresh_ob_below": {"top": 90.0, "bottom": 89.0}}  # absurdly deep OB
    g = _genome(flags={"sl_anchor_smc_ob": True})
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(smc), h1_atr=1.0,
                          max_sl_dist=2.0)
    assert out["ok"] is False
    print("OK test_max_sl_dist_rejects")


def test_custom_fallback_invoked():
    called = {"hit": False}
    def fb(genome, side, entry, atr):
        called["hit"] = True
        return {"ok": True, "sl": 99, "near_tp": 102, "far_tp": 105}
    g = _genome()
    out = r.resolve_sl_tp(g, "BUY", entry=100.0, snap=_snap(), h1_atr=1.0,
                          fallback=fb)
    assert called["hit"]
    assert out["sl"] == 99
    print("OK test_custom_fallback_invoked")


if __name__ == "__main__":
    test_fallback_atr_buy()
    test_fallback_atr_sell()
    test_bad_side()
    test_sl_anchor_ob_buy()
    test_sl_anchor_ob_sell()
    test_sl_anchor_ob_missing_falls_back_to_atr()
    test_sl_anchor_swing_buy()
    test_tp_target_liq_buy()
    test_tp_target_liq_sell()
    test_tp_target_opposite_ob_buy()
    test_combined_ob_sl_and_liq_tp()
    test_max_sl_dist_rejects()
    test_custom_fallback_invoked()
    print("\n✓ all sl_tp_resolver tests passed")
