"""Shared per-symbol model + scaler loader (Phase 3, D-06).

One helper used by both friday_web_dashboard.py (wired this phase) and the legacy
friday_auto_trader.py (future). Resolves a symbol's own model+scaler from the
subfolder layout models/{SYMBOL}/model.keras + models/{SYMBOL}/scaler.pkl (D-04).

Missing per-symbol model -> fall back to the SHARED hybrid_model.keras / scaler.save
with a VISIBLE warning (D-02/D-03). No AUC quality gate is applied (D-01): every
per-symbol model that exists is loaded for live use; bad signals are suppressed at
runtime by live confidence thresholds, not by refusing to load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import joblib

from .config import (
    MODEL_PATH,
    SCALER_PATH,
    symbol_model_path,
    symbol_scaler_path,
)


@dataclass
class LoadedModel:
    """Result of resolving a symbol's prediction model + scaler."""
    symbol: str
    model: object            # Keras model (or an injected fallback object)
    scaler: object | None    # fitted StandardScaler or None
    source: str              # "per_symbol" | "shared"
    warning: str | None = None  # human-readable fallback warning (None on per_symbol)


def _load_keras(path):
    """Load a Keras model from disk. Imports TF lazily; raises on failure."""
    import tensorflow as tf  # lazy — keeps module import cheap and TF-optional
    return tf.keras.models.load_model(str(path), compile=False)


def load_symbol_model(
    symbol: str,
    fallback_model: Optional[object] = None,
    fallback_scaler: Optional[object] = None,
    verbose: bool = True,
) -> LoadedModel:
    """Resolve the prediction model + scaler for `symbol`.

    Order of resolution:
      1. If models/{symbol}/model.keras exists -> load it + its scaler.pkl (source="per_symbol").
      2. Else fall back to the shared model (source="shared") with a VISIBLE warning:
         - prefer the caller-provided fallback_model/fallback_scaler (already in memory),
         - otherwise load the shared hybrid_model.keras / scaler.save from disk.

    NO AUC quality gate is applied (D-01). The shared artifacts are never deleted (D-03).
    """
    symbol = str(symbol).strip()
    per_model = symbol_model_path(symbol)
    per_scaler = symbol_scaler_path(symbol)

    if per_model.exists():
        try:
            model = _load_keras(per_model)
            scaler = None
            if per_scaler.exists():
                try:
                    scaler = joblib.load(str(per_scaler))
                except Exception as exc:  # scaler load failed — keep model, warn
                    if verbose:
                        print(f"[WARN][model_loader] {symbol}: per-symbol scaler load "
                              f"failed ({exc}); using None scaler")
            if verbose:
                print(f"[model_loader] {symbol}: loaded per-symbol model {per_model}")
            return LoadedModel(symbol=symbol, model=model, scaler=scaler,
                               source="per_symbol", warning=None)
        except Exception as exc:  # per-symbol model present but unreadable — fall back
            warning = (f"per-symbol model load failed ({exc}); falling back to shared model")
            if verbose:
                print(f"[WARN][model_loader] {symbol}: {warning}")
            return _fallback(symbol, fallback_model, fallback_scaler, warning, verbose)

    warning = (f"no per-symbol model at {per_model}; using SHARED model "
               f"({MODEL_PATH.name}) — trading continues on shared model")
    if verbose:
        print(f"[WARN][model_loader] {symbol}: {warning}")
    return _fallback(symbol, fallback_model, fallback_scaler, warning, verbose)


def _fallback(symbol, fallback_model, fallback_scaler, warning, verbose) -> LoadedModel:
    """Build a shared-model LoadedModel, preferring in-memory fallbacks over disk."""
    model = fallback_model
    scaler = fallback_scaler
    if model is None:
        model = _load_keras(MODEL_PATH)
    if scaler is None and SCALER_PATH.exists():
        try:
            scaler = joblib.load(str(SCALER_PATH))
        except Exception as exc:
            if verbose:
                print(f"[WARN][model_loader] {symbol}: shared scaler load failed ({exc})")
            scaler = None
    return LoadedModel(symbol=symbol, model=model, scaler=scaler,
                       source="shared", warning=warning)
