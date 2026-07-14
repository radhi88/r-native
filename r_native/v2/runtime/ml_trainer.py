"""runtime/ml_trainer.py — Phase 5.C: train sklearn → ONNX.

Born 2026-05-28. Trains a balanced classifier that learns:
    "given THIS snapshot, will the next SELL/BUY entry win?"

Training set composition (avoids the 98% imbalance trap):
    POSITIVES = user winning trades (the gold signal, WR ~80%)
    NEGATIVES = bot losing trades (what NOT to do — claude_auto, algory)

Output:
    data/ml/model.pkl       — sklearn pickle (rapid retraining)
    data/ml/model.onnx      — for FRIDAY_Brain_Executor.mq5 inference
    data/ml/feature_map.json — column name + categorical mappings

Usage:
    python -m runtime.ml_trainer
"""
from __future__ import annotations
import csv
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score, accuracy_score
)
from sklearn.preprocessing import OrdinalEncoder
from skl2onnx import to_onnx
from skl2onnx.common.data_types import FloatTensorType

from runtime.shared.tokens import PATHS

ML_DIR = PATHS["brain_decisions"].parent / "ml"
USER_CSV = ML_DIR / "user_trades.csv"
ALL_CSV  = ML_DIR / "all_trades.csv"
MODEL_PKL  = ML_DIR / "model.pkl"
MODEL_ONNX = ML_DIR / "model.onnx"
FEATURE_MAP = ML_DIR / "feature_map.json"

NUMERIC  = ["rsi_m1", "rsi_m5", "atr_m1", "atr_h1", "pressure_10m1", "side_BUY"]
CATEGORICAL = ["bias_m1", "bias_m5", "bias_m15", "bias_h1",
               "mtf_align", "session", "regime"]


def _read_csv(p: Path) -> list[dict]:
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8")))


def _build_balanced_dataset() -> tuple[np.ndarray, np.ndarray, dict, OrdinalEncoder]:
    """POSITIVES = user wins. NEGATIVES = bot losses."""
    all_rows = _read_csv(ALL_CSV)
    user_rows = _read_csv(USER_CSV)
    print(f"  raw all_trades:  {len(all_rows)}")
    print(f"  raw user_trades: {len(user_rows)}")

    user_wins = [r for r in user_rows if r["__win"] == "1"]
    # Bot trades = magic != 0 (and != "manual"-attributed magics if any)
    bot_losses = [r for r in all_rows
                  if r["__win"] == "0" and r["__magic"] != "0"]

    print(f"  user wins:  {len(user_wins)}")
    print(f"  bot losses: {len(bot_losses)}")

    if not user_wins or not bot_losses:
        raise RuntimeError("Not enough data — need both user wins AND bot losses")

    # Balance: oversample minority OR undersample majority
    n_pos = len(user_wins); n_neg = len(bot_losses)
    n = min(n_pos, n_neg, 200)  # cap at 200 each for now
    import random
    random.seed(42)
    pos = random.sample(user_wins, min(n, n_pos))
    neg = random.sample(bot_losses, min(n, n_neg))
    rows = pos + neg
    random.shuffle(rows)
    print(f"  balanced: {len(pos)} positives + {len(neg)} negatives")

    # Build feature matrix
    cat_data = [[r.get(c, "?") or "?" for c in CATEGORICAL] for r in rows]
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    cat_encoded = encoder.fit_transform(cat_data)

    num_data = np.array([
        [float(r.get(n, 0) or 0) for n in NUMERIC]
        for r in rows
    ], dtype=np.float32)

    X = np.hstack([cat_encoded, num_data]).astype(np.float32)
    y = np.array([1 if r in pos else 0 for r in rows], dtype=np.int64)

    # Save the mapping for inference-time use
    cat_categories = {c: list(map(str, encoder.categories_[i]))
                      for i, c in enumerate(CATEGORICAL)}
    feature_map = {
        "categorical": CATEGORICAL,
        "numeric":     NUMERIC,
        "encoder_categories": cat_categories,
        "feature_order": CATEGORICAL + NUMERIC,
        "n_features":   X.shape[1],
        "trained_on":   {"positives": len(pos), "negatives": len(neg)},
    }
    return X, y, feature_map, encoder


def train() -> dict:
    print("═══ ML TRAINER — sklearn → ONNX ═══\n")
    print("[1] Building balanced dataset...")
    X, y, fmap, encoder = _build_balanced_dataset()
    print(f"  X shape: {X.shape}  ·  y balance: {y.sum()}/{len(y)}")

    print("\n[2] Train/test split (80/20 stratified)...")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.20, stratify=y, random_state=42)
    print(f"  train: {len(Xtr)}  ·  test: {len(Xte)}")

    print("\n[3] Training GradientBoostingClassifier...")
    model = GradientBoostingClassifier(
        n_estimators=80, max_depth=3, learning_rate=0.08, random_state=42,
    )
    model.fit(Xtr, ytr)

    pred_tr = model.predict(Xtr)
    pred_te = model.predict(Xte)
    proba_te = model.predict_proba(Xte)[:, 1]

    print(f"\n  train acc: {accuracy_score(ytr, pred_tr):.3f}")
    print(f"  test acc:  {accuracy_score(yte, pred_te):.3f}")
    try:
        print(f"  test AUC:  {roc_auc_score(yte, proba_te):.3f}")
    except Exception: pass
    print(f"  confusion matrix (test):\n{confusion_matrix(yte, pred_te)}")
    print(f"\n  classification report (test):")
    print(classification_report(yte, pred_te, target_names=["LOSS", "WIN"]))

    # Feature importances
    print("\n[4] Top features by importance:")
    importances = list(zip(fmap["feature_order"], model.feature_importances_))
    for name, imp in sorted(importances, key=lambda x: -x[1])[:10]:
        bar = "█" * int(imp * 50)
        print(f"  {name:18s} {imp:.4f} {bar}")

    print(f"\n[5] Saving sklearn pickle → {MODEL_PKL}")
    ML_DIR.mkdir(parents=True, exist_ok=True)
    with MODEL_PKL.open("wb") as f:
        pickle.dump({"model": model, "encoder": encoder, "feature_map": fmap}, f)

    print(f"\n[6] Exporting ONNX → {MODEL_ONNX}")
    onnx_model = to_onnx(
        model, X[:1].astype(np.float32),
        target_opset=17,
        options={id(model): {"zipmap": False}},
    )
    MODEL_ONNX.write_bytes(onnx_model.SerializeToString())
    print(f"  ONNX size: {MODEL_ONNX.stat().st_size / 1024:.1f} KB")

    print(f"\n[7] Saving feature map → {FEATURE_MAP}")
    FEATURE_MAP.write_text(json.dumps(fmap, indent=2, default=str), encoding="utf-8")

    print(f"\n[8] ONNX inference smoke test:")
    import onnxruntime as ort
    sess = ort.InferenceSession(str(MODEL_ONNX))
    sample = X[:3].astype(np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: sample})
    print(f"  Input shape:  {sample.shape}")
    print(f"  Output preds: {out[0]}")
    print(f"  Output probs: {out[1]}")

    return {
        "test_acc": float(accuracy_score(yte, pred_te)),
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "feature_count": int(X.shape[1]),
        "model_pkl": str(MODEL_PKL),
        "model_onnx": str(MODEL_ONNX),
        "feature_map": str(FEATURE_MAP),
    }


if __name__ == "__main__":
    result = train()
    print(f"\n═══ DONE ═══")
    for k, v in result.items():
        print(f"  {k}: {v}")
