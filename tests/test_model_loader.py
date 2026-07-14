"""
test_model_loader.py
--------------------
Unit tests for the Phase 3 shared per-symbol model loader
(src/mt5_ai/model_loader.py) and the per-symbol path helpers in config.py.

No real TensorFlow model or training is needed: the per-symbol "model" is monkey
-patched and in-memory sentinels exercise the shared-fallback path.

Run: python -m pytest tests/test_model_loader.py
  OR: python tests/test_model_loader.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai import config
from mt5_ai import model_loader
from mt5_ai.model_loader import LoadedModel, load_symbol_model


# ── config path helpers (subfolder layout, D-04) ────────────────────────────
def test_symbol_model_path_subfolder_layout():
    p = config.symbol_model_path("XAUUSDm")
    assert p.name == "model.keras"
    assert p.parent.name == "XAUUSDm"
    assert p.parent.parent == config.MODELS_DIR


def test_symbol_scaler_path_subfolder_layout():
    p = config.symbol_scaler_path("EURUSDm")
    assert p.name == "scaler.pkl"
    assert p.parent.name == "EURUSDm"
    assert p.parent.parent == config.MODELS_DIR


def test_symbol_path_strips_whitespace():
    assert config.symbol_model_path("  BTCUSDm  ").parent.name == "BTCUSDm"


# ── shared fallback path (D-02/D-03): missing per-symbol model ───────────────
def test_fallback_uses_in_memory_shared_model_and_warns():
    r = load_symbol_model(
        "___NO_SUCH_SYMBOL___",
        fallback_model="SHARED_SENTINEL",
        fallback_scaler="SCALER_SENTINEL",
        verbose=False,
    )
    assert isinstance(r, LoadedModel)
    assert r.source == "shared"
    assert r.model == "SHARED_SENTINEL"
    assert r.scaler == "SCALER_SENTINEL"
    assert r.warning and "SHARED" in r.warning


def test_fallback_does_not_touch_tensorflow_when_fallback_supplied(monkeypatch):
    # If TF were loaded on the fallback path, this would raise.
    def _boom(_path):
        raise AssertionError("_load_keras must NOT be called when fallback_model is provided")

    monkeypatch.setattr(model_loader, "_load_keras", _boom)
    r = load_symbol_model(
        "___NO_SUCH_SYMBOL___",
        fallback_model="SHARED_SENTINEL",
        verbose=False,
    )
    assert r.source == "shared"
    assert r.model == "SHARED_SENTINEL"


# ── per-symbol load path (D-01: load regardless of quality) ─────────────────
def test_per_symbol_model_loaded_when_present(monkeypatch, tmp_path):
    sym = "ZZTESTm"
    per_dir = tmp_path / sym
    per_dir.mkdir(parents=True)
    model_file = per_dir / "model.keras"
    model_file.write_text("fake-keras")  # presence only; loader is monkeypatched
    scaler_file = per_dir / "scaler.pkl"

    # Point the config helpers at the temp layout.
    monkeypatch.setattr(model_loader, "symbol_model_path", lambda s: model_file)
    monkeypatch.setattr(model_loader, "symbol_scaler_path", lambda s: scaler_file)

    sentinel_model = object()
    monkeypatch.setattr(model_loader, "_load_keras", lambda path: sentinel_model)

    # No scaler.pkl on disk -> scaler is None but model still loads (no gate, D-01).
    r = load_symbol_model(sym, fallback_model="SHARED_SENTINEL", verbose=False)
    assert r.source == "per_symbol"
    assert r.model is sentinel_model
    assert r.scaler is None
    assert r.warning is None


def test_per_symbol_load_failure_falls_back_to_shared(monkeypatch, tmp_path):
    sym = "ZZBADm"
    per_dir = tmp_path / sym
    per_dir.mkdir(parents=True)
    model_file = per_dir / "model.keras"
    model_file.write_text("corrupt")

    monkeypatch.setattr(model_loader, "symbol_model_path", lambda s: model_file)
    monkeypatch.setattr(model_loader, "symbol_scaler_path", lambda s: per_dir / "scaler.pkl")

    def _boom(_path):
        raise ValueError("corrupt model")

    monkeypatch.setattr(model_loader, "_load_keras", _boom)

    r = load_symbol_model(sym, fallback_model="SHARED_SENTINEL", verbose=False)
    assert r.source == "shared"
    assert r.model == "SHARED_SENTINEL"
    assert r.warning and "failed" in r.warning


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
