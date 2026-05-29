"""Tests for combo_fitness SMC context recorder (learning loop)."""
from __future__ import annotations

import os
import sys
import json
import tempfile
import importlib.util
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_modname = "combo_fitness_under_test"
spec = importlib.util.spec_from_file_location(_modname, os.path.join(REPO, "combo_fitness.py"))
cf = importlib.util.module_from_spec(spec)
sys.modules[_modname] = cf
spec.loader.exec_module(cf)

# Redirect persistence to /tmp
cf.FITNESS_PATH = Path(tempfile.mkdtemp()) / "fitness.json"


def _win(): return {"won": True,  "return_pct": 5.0}
def _loss(): return {"won": False, "return_pct": -2.0}


def test_smc_ctx_keys_derivation():
    ctx = {
        "trade_aligned_with_bos": True,
        "entry_in_ob": "fresh",
        "idm_swept": True,
        "htf_aligned": True,
        "exit_via": "liquidity_pool",
    }
    keys = cf._smc_ctx_keys(ctx)
    assert "bos_aligned" in keys
    assert "in_fresh_ob" in keys
    assert "idm_swept_before" in keys
    assert "htf_aligned" in keys
    assert "tp_hit_liquidity" in keys
    print("OK test_smc_ctx_keys_derivation")


def test_record_smc_trade_partitions_by_context():
    db = cf._empty_db()
    # 8 OB trades WITH idm sweep → mostly wins
    for i in range(8):
        cf.record_smc_trade("XAGUSDm", "H1",
            active_genes=["use_sig_smc_ob"],
            smc_context={"entry_in_ob": "fresh", "idm_swept": True},
            stats=_win() if i < 6 else _loss(), db=db)
    # 8 OB trades WITHOUT idm sweep → mostly losses
    for i in range(8):
        cf.record_smc_trade("XAGUSDm", "H1",
            active_genes=["use_sig_smc_ob"],
            smc_context={"entry_in_ob": "fresh", "idm_swept": False},
            stats=_win() if i < 2 else _loss(), db=db)

    bucket = db["XAGUSDm"]["H1"]
    swept   = bucket["smc_contexts"]["idm_swept_before"]
    noswept = bucket["smc_contexts"]["no_idm_sweep"]
    assert swept["wins"]   == 6 and swept["fails"]   == 2
    assert noswept["wins"] == 2 and noswept["fails"] == 6
    print("OK test_record_smc_trade_partitions_by_context")


def test_smc_combo_tracked():
    db = cf._empty_db()
    cf.record_smc_trade("X", "H1",
        active_genes=["use_sig_smc_ob", "use_sig_smc_idm", "use_sig_rsi"],
        smc_context={"idm_swept": True}, stats=_win(), db=db)
    # Only smc genes form the combo key
    bucket = db["X"]["H1"]
    keys = list(bucket["smc_combos"].keys())
    assert len(keys) == 1
    assert "smc" in keys[0]
    assert "rsi" not in keys[0]   # non-smc gene excluded from smc combo
    print("OK test_smc_combo_tracked")


def test_smc_context_report():
    db = cf._empty_db()
    for i in range(10):
        cf.record_smc_trade("X", "H1", active_genes=["use_sig_smc_ob"],
            smc_context={"idm_swept": True},
            stats=_win() if i < 7 else _loss(), db=db)
    # Persist + use module-level report (reads from disk)
    cf.save(db)
    report = cf.smc_context_report("X", "H1")
    assert "idm_swept_before" in report
    assert report["idm_swept_before"]["win_rate"] == 70.0
    assert report["idm_swept_before"]["wins"] == 7
    print("OK test_smc_context_report")


def test_smc_lookup_global_fallback():
    db = cf._empty_db()
    cf.record_smc_trade("X", "H1", active_genes=["use_sig_smc_choch"],
        smc_context={"idm_swept": True}, stats=_win(), db=db)
    cf.save(db)
    # Query a symbol we never recorded → falls back to global
    rec = cf.smc_lookup("UNSEEN", "H1", active_genes=["use_sig_smc_choch"])
    assert rec["scope"] == "global"
    assert rec["wins"] == 1
    print("OK test_smc_lookup_global_fallback")


def test_backfill_smc_buckets_on_old_db():
    # Simulate an old bucket with no smc_combos/smc_contexts keys
    db = cf._empty_db()
    old_bucket = cf._bucket(db, "X", "H1")
    assert "smc_combos" not in old_bucket   # not present until ensured
    cf.record_smc_trade("X", "H1", active_genes=["use_sig_smc_ob"],
        smc_context={"idm_swept": True}, stats=_win(), db=db)
    assert "smc_combos" in db["X"]["H1"]
    assert "smc_contexts" in db["X"]["H1"]
    print("OK test_backfill_smc_buckets_on_old_db")


if __name__ == "__main__":
    test_smc_ctx_keys_derivation()
    test_record_smc_trade_partitions_by_context()
    test_smc_combo_tracked()
    test_smc_context_report()
    test_smc_lookup_global_fallback()
    test_backfill_smc_buckets_on_old_db()
    print("\n✓ all combo_fitness SMC tests passed")
