"""Tests for smc_neural — heuristic scorer, annotate, train round-trip."""
from __future__ import annotations

import os
import sys
import tempfile
import importlib.util
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)   # so build_training_dataset can `import smc_engine`

_modname = "smc_neural_under_test"
spec = importlib.util.spec_from_file_location(_modname, os.path.join(REPO, "smc_neural.py"))
nn = importlib.util.module_from_spec(spec)
sys.modules[_modname] = nn
spec.loader.exec_module(nn)


def test_heuristic_in_range():
    scorer = nn.SMCPatternScorer(model_path=Path("/nonexistent.npz"))
    assert scorer.backend == "heuristic"
    ob = {"top": 100.5, "bottom": 100.0, "age_bars": 2, "strength": 0.8,
          "body_ratio": 0.7}
    s = scorer.score_ob(ob, atr=1.0, price=100.2, confluence=0.5, htf_aligned=True)
    assert 0.0 <= s <= 1.0
    print(f"OK test_heuristic_in_range (score={s:.3f})")


def test_strong_fresh_scores_higher_than_weak_stale():
    scorer = nn.SMCPatternScorer(model_path=Path("/nonexistent.npz"))
    strong = {"top": 100.3, "bottom": 100.0, "age_bars": 1, "strength": 0.95,
              "body_ratio": 0.8}
    weak   = {"top": 103.0, "bottom": 100.0, "age_bars": 60, "strength": 0.1,
              "body_ratio": 0.2}
    s_strong = scorer.score_ob(strong, atr=1.0, price=100.15, confluence=1.0,
                               htf_aligned=True, volume_z=2.0)
    s_weak   = scorer.score_ob(weak, atr=1.0, price=110.0, confluence=0.0,
                               htf_aligned=False, volume_z=-1.0)
    assert s_strong > s_weak, f"strong={s_strong} weak={s_weak}"
    print(f"OK test_strong_fresh_scores_higher_than_weak_stale "
          f"(strong={s_strong:.3f} weak={s_weak:.3f})")


def test_annotate_snapshot_adds_nn_strength():
    snap = {
        "atr14": 1.0, "current": 100.0,
        "fresh_ob_below": {"top": 99.5, "bottom": 99.0, "age_bars": 3, "strength": 0.7},
        "fresh_ob_above": None,
        "fresh_fvg_bull": [{"top": 99.8, "bottom": 99.6, "age_bars": 2, "filled_pct": 0.0}],
        "fresh_fvg_bear": [],
        "last_bos": {"direction": "UP", "level": 100.2, "age_bars": 5},
    }
    out = nn.annotate_snapshot(snap, htf_bias="UP")
    assert "nn_strength" in out["fresh_ob_below"]
    assert 0.0 <= out["fresh_ob_below"]["nn_strength"] <= 1.0
    assert "nn_strength" in out["fresh_fvg_bull"][0]
    print("OK test_annotate_snapshot_adds_nn_strength")


def test_annotate_tolerates_empty():
    assert nn.annotate_snapshot({}) == {}
    assert nn.annotate_snapshot(None) is None
    print("OK test_annotate_tolerates_empty")


def test_train_roundtrip_and_load():
    # Synthetic separable data: feature 0 (strength) drives the label
    rng = np.random.default_rng(0)
    n = 200
    X = rng.random((n, nn.N_FEATURES))
    y = (X[:, 0] > 0.5).astype(int)   # strength > 0.5 → reacts
    tmp = Path(tempfile.mkdtemp()) / "model.npz"
    res = nn.train_model(X, y, out_path=tmp, epochs=400, lr=0.3)
    assert res["ok"], res
    assert res["accuracy"] > 0.8, f"acc too low: {res['accuracy']}"
    # Load it back via scorer
    scorer = nn.SMCPatternScorer(model_path=tmp)
    assert scorer.backend == "learned"
    high = scorer.score_ob({"top": 1, "bottom": 0.9, "age_bars": 0, "strength": 0.95,
                            "body_ratio": 0.5}, atr=1.0, price=0.95)
    assert 0.0 <= high <= 1.0
    print(f"OK test_train_roundtrip_and_load (acc={res['accuracy']})")


def test_train_refuses_tiny_dataset():
    X = np.zeros((5, nn.N_FEATURES)); y = np.zeros(5)
    res = nn.train_model(X, y)
    assert res["ok"] is False
    print("OK test_train_refuses_tiny_dataset")


def test_build_training_dataset_runs():
    # Build synthetic bars with a clear OB + reaction, ensure no crash
    def _bar(t, o, h, l, c): return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 100}
    bars = []
    price = 100.0
    for i in range(60):
        o = price
        c = price + (0.3 if i % 2 == 0 else -0.1)
        bars.append(_bar(i, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        price = c
    X, y = nn.build_training_dataset(bars, horizon=10)
    assert X.shape[1] == nn.N_FEATURES if len(X) else True
    print(f"OK test_build_training_dataset_runs ({len(X)} samples)")


if __name__ == "__main__":
    test_heuristic_in_range()
    test_strong_fresh_scores_higher_than_weak_stale()
    test_annotate_snapshot_adds_nn_strength()
    test_annotate_tolerates_empty()
    test_train_roundtrip_and_load()
    test_train_refuses_tiny_dataset()
    test_build_training_dataset_runs()
    print("\n✓ all smc_neural tests passed")
