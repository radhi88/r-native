"""smc_neural.py — quality scorer for SMC patterns (0..1).

Scores how likely a detected Order Block / FVG is to HOLD (price reacts
from it) rather than break through. Two scoring backends:

  1. Heuristic (always available, pure numpy) — combines pattern strength,
     freshness, relative size, body/wick shape, and confluence. Good
     enough to gate weak patterns out of the box.

  2. Learned (optional) — if a trained model file exists AND its runtime
     (torch or a pickled sklearn estimator) is importable, predictions
     come from the model. Falls back to heuristic on any failure.

The output `nn_strength` is attached to each fresh OB / FVG in the SMC
snapshot and used by genome_signal SMC evaluators as a vote-weight
multiplier (a high-quality OB counts more than a marginal one).

Training:
  build_training_dataset(bars) replays history through smc_engine, labels
  each OB/FVG by whether price respected it within `horizon` bars, and
  returns (X, y). train_model(X, y, out_path) fits a small classifier.
  Both are runtime-agnostic — sklearn if present, else a numpy logistic
  regression baked in here.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Optional

import numpy as np


MODEL_DIR  = Path(r"C:\Users\Radhi\MT5\data\r_native\models")
MODEL_FILE = MODEL_DIR / "smc_scorer.npz"     # numpy logistic weights (portable)


# ─── Feature extraction (pure numpy) ─────────────────────────────
FEATURE_NAMES = [
    "strength",          # detector-reported strength (0..1)
    "freshness",         # 1 / (1 + age_bars/20) — newer is higher
    "rel_size_atr",      # zone height / ATR
    "dist_to_price_atr", # |zone_mid - price| / ATR  (closer is better)
    "body_ratio",        # for OB: body / range of the OB candle
    "volume_z",          # volume z-score of the impulse vs window
    "confluence",        # count of overlapping concepts (bos/fvg/sweep) 0..1
    "htf_aligned",       # 1 if aligned with HTF bias else 0
]
N_FEATURES = len(FEATURE_NAMES)


def _safe(x, default=0.0):
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v): return default
        return v
    except Exception:
        return default


def extract_features_ob(ob: dict, *, atr: float, price: float,
                        confluence: float = 0.0, htf_aligned: bool = False,
                        volume_z: float = 0.0) -> np.ndarray:
    top    = _safe(ob.get("top"))
    bottom = _safe(ob.get("bottom"))
    height = max(top - bottom, 1e-9)
    mid    = (top + bottom) / 2
    age    = _safe(ob.get("age_bars"), 0)
    feats = np.array([
        _safe(ob.get("strength")),
        1.0 / (1.0 + age / 20.0),
        height / max(atr, 1e-9),
        abs(mid - price) / max(atr, 1e-9),
        _safe(ob.get("body_ratio"), 0.5),
        volume_z,
        confluence,
        1.0 if htf_aligned else 0.0,
    ], dtype=float)
    return feats


def extract_features_fvg(fvg: dict, *, atr: float, price: float,
                         confluence: float = 0.0, htf_aligned: bool = False) -> np.ndarray:
    top    = _safe(fvg.get("top"))
    bottom = _safe(fvg.get("bottom"))
    height = max(top - bottom, 1e-9)
    mid    = (top + bottom) / 2
    age    = _safe(fvg.get("age_bars"), 0)
    filled = _safe(fvg.get("filled_pct"), 0.0)
    feats = np.array([
        1.0 - filled,                       # unfilled FVGs are "stronger"
        1.0 / (1.0 + age / 20.0),
        height / max(atr, 1e-9),
        abs(mid - price) / max(atr, 1e-9),
        0.5,                                # FVGs have no candle body concept
        0.0,
        confluence,
        1.0 if htf_aligned else 0.0,
    ], dtype=float)
    return feats


# ─── Heuristic scorer (always available) ─────────────────────────
def _heuristic_score(feats: np.ndarray) -> float:
    """Hand-tuned weighting; returns 0..1. Designed so a fresh, strong,
    nearby, HTF-aligned pattern with confluence scores high."""
    (strength, freshness, rel_size, dist, body, vol_z, conf, htf) = feats
    # Penalize zones that are too wide (rel_size huge) or too far (dist huge)
    size_pen = 1.0 / (1.0 + max(0.0, rel_size - 2.0))     # >2 ATR tall starts losing
    dist_pen = 1.0 / (1.0 + max(0.0, dist - 1.0))         # >1 ATR away starts losing
    vol_bonus = 1.0 / (1.0 + math.exp(-vol_z))            # sigmoid of vol z
    raw = (
        0.28 * strength +
        0.18 * freshness +
        0.12 * size_pen +
        0.14 * dist_pen +
        0.08 * body +
        0.08 * vol_bonus +
        0.07 * conf +
        0.05 * htf
    )
    return float(max(0.0, min(1.0, raw)))


# ─── Learned scorer (optional, numpy logistic regression) ───────
class _LogisticModel:
    """Portable logistic regression stored as npz (weights + bias + mean/std).
    No external ML dependency required at inference time."""
    def __init__(self, w: np.ndarray, b: float, mean: np.ndarray, std: np.ndarray):
        self.w = w; self.b = b; self.mean = mean; self.std = std

    def predict_proba(self, feats: np.ndarray) -> float:
        x = (feats - self.mean) / np.where(self.std == 0, 1.0, self.std)
        z = float(np.dot(self.w, x) + self.b)
        return 1.0 / (1.0 + math.exp(-max(-30, min(30, -z))))

    @classmethod
    def load(cls, path: Path) -> Optional["_LogisticModel"]:
        try:
            d = np.load(path)
            return cls(d["w"], float(d["b"]), d["mean"], d["std"])
        except Exception:
            return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, w=self.w, b=np.array(self.b),
                 mean=self.mean, std=self.std)


class SMCPatternScorer:
    """Public scorer. Loads a model if present, else uses heuristic."""

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path) if model_path else MODEL_FILE
        self._model = _LogisticModel.load(self.model_path) \
            if self.model_path.exists() else None

    @property
    def backend(self) -> str:
        return "learned" if self._model is not None else "heuristic"

    def _score(self, feats: np.ndarray) -> float:
        if self._model is not None:
            try:
                return float(self._model.predict_proba(feats))
            except Exception:
                pass
        return _heuristic_score(feats)

    def score_ob(self, ob: dict, *, atr: float, price: float,
                 confluence: float = 0.0, htf_aligned: bool = False,
                 volume_z: float = 0.0) -> float:
        if not ob: return 0.0
        feats = extract_features_ob(ob, atr=atr, price=price,
                                    confluence=confluence,
                                    htf_aligned=htf_aligned, volume_z=volume_z)
        return self._score(feats)

    def score_fvg(self, fvg: dict, *, atr: float, price: float,
                  confluence: float = 0.0, htf_aligned: bool = False) -> float:
        if not fvg: return 0.0
        feats = extract_features_fvg(fvg, atr=atr, price=price,
                                     confluence=confluence, htf_aligned=htf_aligned)
        return self._score(feats)


# Module-level singleton (lazy)
_scorer: Optional[SMCPatternScorer] = None


def get_scorer() -> SMCPatternScorer:
    global _scorer
    if _scorer is None:
        _scorer = SMCPatternScorer()
    return _scorer


def annotate_snapshot(snap: dict, *, htf_bias: Optional[str] = None) -> dict:
    """Attach `nn_strength` to each fresh OB / FVG in an smc snapshot
    (the dict shape from smc_engine.compute_offline). Returns the same
    dict mutated in place. Safe on empty/partial snapshots."""
    if not snap: return snap
    scorer = get_scorer()
    atr   = _safe(snap.get("atr14"), 1.0) or 1.0
    price = _safe(snap.get("current"), 0.0)

    # Confluence: how many structural concepts are active right now
    confluence = 0.0
    for k in ("last_bos", "last_choch", "recent_liq_sweep", "idm_status"):
        if snap.get(k): confluence += 0.25
    confluence = min(1.0, confluence)

    def _aligned(side_dir: str) -> bool:
        if not htf_bias: return False
        return (htf_bias == "UP" and side_dir == "bull") or \
               (htf_bias == "DOWN" and side_dir == "bear")

    for key, side_dir in (("fresh_ob_above", "bear"), ("fresh_ob_below", "bull")):
        ob = snap.get(key)
        if ob:
            ob["nn_strength"] = round(scorer.score_ob(
                ob, atr=atr, price=price, confluence=confluence,
                htf_aligned=_aligned(side_dir)), 3)

    for key, side_dir in (("fresh_fvg_bull", "bull"), ("fresh_fvg_bear", "bear")):
        for fvg in snap.get(key, []) or []:
            fvg["nn_strength"] = round(scorer.score_fvg(
                fvg, atr=atr, price=price, confluence=confluence,
                htf_aligned=_aligned(side_dir)), 3)
    return snap


# ─── Training (offline, optional) ───────────────────────────────
def build_training_dataset(bars, *, horizon: int = 20,
                           react_atr: float = 0.5, cfg: dict = None):
    """Replay `bars` through smc_engine, label each OB/FVG by whether price
    reacted from it within `horizon` bars (moved >= react_atr × ATR in the
    expected direction before breaking the zone). Returns (X, y) numpy.

    Pure offline — used by train_model. Requires smc_engine importable.
    """
    try:
        from r_native import smc_engine as se
    except Exception:
        import smc_engine as se
    bv = se.Bars(bars) if not isinstance(bars, se.Bars) else bars
    cfg = {**se.DEFAULT_CFG, **(cfg or {})}
    atr_series = se._atr(bv, cfg.get("atr_period", 14))
    events = se.compute_events(bv, cfg)
    X, y = [], []
    n = len(bv)
    for ev in events:
        if ev.kind not in ("OB", "FVG"): continue
        i = ev.idx_end
        if i + horizon >= n: continue
        atr = atr_series[i] if atr_series[i] > 0 else 1.0
        price = bv[i].close
        zone_mid = (ev.level_high + ev.level_low) / 2
        # Did price react? For bull zone, price should bounce UP after touching.
        reacted = False
        touched = False
        for k in range(i + 1, min(i + 1 + horizon, n)):
            bar = bv[k]
            if ev.side == "bull":
                if bar.low <= ev.level_high:        # touched the zone
                    touched = True
                    if bar.high - ev.level_high >= react_atr * atr:
                        reacted = True; break
                    if bar.close < ev.level_low:    # broke through
                        break
            else:
                if bar.high >= ev.level_low:
                    touched = True
                    if ev.level_low - bar.low >= react_atr * atr:
                        reacted = True; break
                    if bar.close > ev.level_high:
                        break
        if not touched:
            continue   # untested zones aren't training signal
        ob_like = {"top": ev.level_high, "bottom": ev.level_low,
                   "age_bars": 0, "strength": ev.strength,
                   "body_ratio": 0.5, "filled_pct": 0.0}
        if ev.kind == "OB":
            feats = extract_features_ob(ob_like, atr=atr, price=price)
        else:
            feats = extract_features_fvg(ob_like, atr=atr, price=price)
        X.append(feats); y.append(1 if reacted else 0)
    if not X:
        return np.zeros((0, N_FEATURES)), np.zeros((0,))
    return np.array(X), np.array(y)


def train_model(X: np.ndarray, y: np.ndarray, *, epochs: int = 300,
                lr: float = 0.1, out_path: Optional[Path] = None) -> dict:
    """Fit a numpy logistic regression on (X, y). Saves to out_path
    (default MODEL_FILE). Returns {ok, n, accuracy, backend}."""
    if len(X) < 20:
        return {"ok": False, "reason": f"too few samples ({len(X)})"}
    mean = X.mean(axis=0)
    std  = X.std(axis=0)
    Xs   = (X - mean) / np.where(std == 0, 1.0, std)
    w = np.zeros(X.shape[1]); b = 0.0
    m = len(Xs)
    for _ in range(epochs):
        z = Xs @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad_w = Xs.T @ (p - y) / m
        grad_b = float(np.mean(p - y))
        w -= lr * grad_w
        b -= lr * grad_b
    # Accuracy
    p = 1.0 / (1.0 + np.exp(-np.clip(Xs @ w + b, -30, 30)))
    acc = float(np.mean((p >= 0.5).astype(int) == y))
    model = _LogisticModel(w, b, mean, std)
    out = Path(out_path) if out_path else MODEL_FILE
    model.save(out)
    return {"ok": True, "n": int(m), "accuracy": round(acc, 3),
            "backend": "learned", "path": str(out)}
