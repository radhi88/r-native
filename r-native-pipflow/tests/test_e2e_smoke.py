"""End-to-end smoke test — exercise every SMC module together.

Walks synthetic OHLCV bars through the full pipeline:

    bars  -> smc_engine.compute_and_annotate
          -> chart_drawings.drawings_from_smc_snapshot
          -> sl_tp_resolver.resolve_sl_tp (with a fake genome)
          -> combo_fitness.record_smc_trade
          -> hall_of_fame lane classification
          -> agent_governance gating

Does NOT touch MT5. Designed to catch integration regressions between the
modules (signature drift, key-name mismatches, import cycles).
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import importlib.util
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# Load every module under test
se  = _load("smc_engine_e2e",       os.path.join(REPO, "smc_engine.py"))
nn  = _load("smc_neural_e2e",       os.path.join(REPO, "smc_neural.py"))
cd  = _load("chart_drawings_e2e",   os.path.join(REPO, "chart_drawings.py"))
slr = _load("sl_tp_resolver_e2e",   os.path.join(REPO, "sl_tp_resolver.py"))
cf  = _load("combo_fitness_e2e",    os.path.join(REPO, "combo_fitness.py"))
hof = _load("hall_of_fame_e2e",     os.path.join(REPO, "hall_of_fame.py"))
gov = _load("agent_governance_e2e", os.path.join(REPO, "agent_governance.py"))

# Redirect persistence to /tmp so we don't write to Windows paths
_tmp = Path(tempfile.mkdtemp())
cf.FITNESS_PATH = _tmp / "fitness.json"
gov.GOV_STATE   = _tmp / "gov.json"
gov.GOV_LOG     = _tmp / "gov.jsonl"


def _bar(t, o, h, l, c, v=100):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _make_bars(n: int = 150) -> list:
    """Build bars with a recognisable bullish setup ending near an OB."""
    bars = []
    price = 100.0
    # Phase A: downtrend (sets up swing low + low pool)
    for i in range(0, 40):
        o = price
        c = price - 0.2 if i % 3 != 0 else price + 0.05
        bars.append(_bar(i, o, max(o, c) + 0.15, min(o, c) - 0.25, c))
        price = c
    # Phase B: impulse up (creates bullish BOS through pre-existing high)
    for i in range(40, 60):
        o = price; c = price + 0.5
        bars.append(_bar(i, o, c + 0.2, o - 0.1, c))
        price = c
    # Phase C: retracement that taps a bullish OB zone (last bear candle pre-impulse)
    for i in range(60, 90):
        o = price; c = price - 0.15 if i % 2 == 0 else price + 0.05
        bars.append(_bar(i, o, max(o, c) + 0.15, min(o, c) - 0.2, c))
        price = c
    # Phase D: continuation
    for i in range(90, n):
        o = price; c = price + 0.25
        bars.append(_bar(i, o, c + 0.15, o - 0.05, c))
        price = c
    return bars


# ─── End-to-end pipeline ─────────────────────────────────────────
def test_e2e_smc_engine_to_drawings():
    bars = _make_bars()
    snap = se.compute_and_annotate(bars, cache_key=("X", "H1"), htf_bias="UP")
    assert "atr14" in snap
    assert isinstance(snap.get("fresh_fvg_bull", []), list)
    # nn_strength must have been attached to every fresh OB/FVG
    if snap.get("fresh_ob_below"):
        assert "nn_strength" in snap["fresh_ob_below"]
        assert 0.0 <= snap["fresh_ob_below"]["nn_strength"] <= 1.0
    for fvg in snap.get("fresh_fvg_bull", []):
        assert "nn_strength" in fvg

    # Convert to drawings
    drawings = cd.drawings_from_smc_snapshot("XAGUSDm", "h1", snap)
    assert isinstance(drawings, list)
    types = {d["type"] for d in drawings}
    assert types.issubset({"rectangle", "trendline", "arrow", "hline", "label",
                            "fib_levels"})
    # All drawings have deterministic IDs + symbol filter
    for d in drawings:
        assert d["symbol"] == "XAGUSDm"
        assert d["id"].startswith(("r_", "t_", "a_", "h_", "lbl_", "fib_"))
    print(f"OK e2e: snapshot -> {len(drawings)} drawings "
          f"(types: {sorted(types)})")


def test_e2e_resolver_with_genome():
    bars = _make_bars()
    snap = se.compute_and_annotate(bars, cache_key=("Y", "H1"))
    # Wrap snap into the genome_signal-style snapshot shape
    gs_snap = {"h1": {"current": snap["current"], "atr": snap["atr14"],
                       "swing_high": snap.get("liq_above", [101])[0] if snap.get("liq_above") else 102,
                       "swing_low":  snap.get("liq_below", [99])[0]  if snap.get("liq_below")  else 98,
                       "smc": snap},
                "bid": snap["current"], "ask": snap["current"] + 0.05}
    # Genome with OB SL anchor + liquidity TP target
    genome = {
        "flags":  {"sl_anchor_smc_ob": True, "tp_target_smc_liq": True,
                    "use_sig_smc_ob": True},
        "params": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0,
                    "smc_ob_buffer_atr": 0.4},
    }
    out = slr.resolve_sl_tp(genome, side="BUY", entry=snap["current"],
                            snap=gs_snap, h1_atr=snap["atr14"])
    assert out.get("ok") in (True, False)   # never crash
    if out["ok"]:
        # SL on the correct side of entry
        assert out["sl"] < snap["current"]
        # Some anchor was attempted (may have fallen back to ATR)
        assert out["sl_anchor"] in ("smc_ob", "smc_swing", "atr")
        print(f"OK e2e: resolver ok sl_anchor={out['sl_anchor']} "
              f"tp_anchor={out['tp_anchor']}")
    else:
        print(f"OK e2e: resolver legitimately rejected ({out.get('reasoning')})")


def test_e2e_fitness_records_partition():
    """Simulate 20 trades with two different SMC contexts; verify the
    breeder can read back the win-rate split."""
    db = cf._empty_db()
    # 10 OB+IDM trades: 8 win, 2 loss
    for i in range(10):
        cf.record_smc_trade("ZZ", "M5",
            active_genes=["use_sig_smc_ob", "use_sig_smc_idm"],
            smc_context={"entry_in_ob": "fresh", "idm_swept": True,
                          "exit_via": "liquidity_pool"},
            stats={"won": i < 8, "return_pct": 3.0 if i < 8 else -1.0},
            db=db)
    # 10 OB-only (no idm sweep): 3 win, 7 loss
    for i in range(10):
        cf.record_smc_trade("ZZ", "M5",
            active_genes=["use_sig_smc_ob"],
            smc_context={"entry_in_ob": "fresh", "idm_swept": False,
                          "exit_via": "sl"},
            stats={"won": i < 3, "return_pct": 3.0 if i < 3 else -1.0},
            db=db)
    cf.save(db)
    report = cf.smc_context_report("ZZ", "M5")
    assert report["idm_swept_before"]["wins"] == 8
    assert report["no_idm_sweep"]["fails"]   == 7
    # The breeder can now see: OB-with-IDM wins ~80%, OB-only ~30%
    print(f"OK e2e: context report — "
          f"idm_swept WR={report['idm_swept_before']['win_rate']}% "
          f"vs no_idm WR={report['no_idm_sweep']['win_rate']}%")


def test_e2e_lane_classification():
    smc_active   = ["use_sig_smc_ob", "use_sig_macd"]
    classic_only = ["use_sig_macd", "use_sig_rsi"]
    assert hof._classify_lane(smc_active)   == "smc"
    assert hof._classify_lane(classic_only) == "classic"
    print("OK e2e: lane classification — smc/classic")


def test_e2e_governance_gates_overactive_agent():
    g = gov.Governance(policy=gov.GovernancePolicy(
        max_trades_per_hour_per_agent=2,
        consecutive_losses_pause_threshold=99,
    ))
    g.record_trade("vol_hunter", "XAGUSDm", "open")
    g.record_trade("vol_hunter", "XAGUSDm", "open")
    ok, reason = g.can_trade("vol_hunter", "XAGUSDm")
    assert ok is False
    assert "hourly cap" in reason
    # Same agent, different symbol — also blocked because hourly is per-agent
    ok2, _ = g.can_trade("vol_hunter", "XAUUSDm")
    assert ok2 is False
    # Different agent — still allowed
    ok3, _ = g.can_trade("gap_hunter", "XAGUSDm")
    assert ok3 is True
    print("OK e2e: governance hourly cap gates the right agent")


def test_e2e_pipeline_no_smc_data_safe():
    """Genomes with SMC flags but no SMC data in snapshot must NOT crash."""
    # Snapshot lacking the "smc" key entirely
    snap = {"h1": {"current": 100, "atr": 1, "swing_high": 101, "swing_low": 99,
                    "range_size": 2, "bias": "RANGE", "slope_atr": 0.0},
             "m15": {}, "h4": {}, "bid": 100, "ask": 100.05}
    genome = {"flags": {"sl_anchor_smc_ob": True, "tp_target_smc_liq": True,
                         "use_sig_smc_ob": True},
              "params": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0}}
    out = slr.resolve_sl_tp(genome, side="BUY", entry=100.0,
                            snap=snap, h1_atr=1.0)
    assert out["ok"], f"must fall back gracefully, got {out}"
    # Must have fallen back to ATR
    assert out["sl_anchor"] == "atr"
    assert out["tp_anchor"] == "atr"
    print("OK e2e: missing SMC data falls back to ATR safely")


if __name__ == "__main__":
    test_e2e_smc_engine_to_drawings()
    test_e2e_resolver_with_genome()
    test_e2e_fitness_records_partition()
    test_e2e_lane_classification()
    test_e2e_governance_gates_overactive_agent()
    test_e2e_pipeline_no_smc_data_safe()
    print("\n✓ all end-to-end smoke tests passed")
