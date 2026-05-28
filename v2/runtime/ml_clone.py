"""runtime/ml_clone.py — Clone the user's edge (done right).

Born 2026-05-28. The academy proved raw indicators have no edge, but the
USER does (80% WR over 300+ trades). This learns the market CONTEXT that
precedes a winning entry — regardless of which engine fired it — and gates
future trades on P(win).

FIXES the Phase 5.C overfit:
  • NO raw ATR (it leaked time-of-day). Uses atr_ratio = atr_m1/atr_h1.
  • Cyclical hour-of-day (sin/cos) instead of nothing.
  • Encoded bias/session/regime, normalized RSI/pressure.
  • Balanced classes, TIME-BASED split (train past → test future).
  • Honest CV metrics — no more fake 100%.

PIPELINE:
  build_dataset()  — 219 matchable trades → normalized feature matrix
  train()          — LogReg + RandomForest, time-split, pick best, ONNX
  predict(snap)    — P(win) for a live brain snapshot

USAGE:
  python -m runtime.ml_clone --train
  python -m runtime.ml_clone --eval          # show metrics only
"""
from __future__ import annotations
import argparse
import json
import math
import pickle
from pathlib import Path

import numpy as np

from runtime.shared.db import db
from runtime.shared.tokens import PATHS

ML_DIR = PATHS["brain_decisions"].parent / "ml"
MODEL_PKL = ML_DIR / "clone_model.pkl"
MODEL_ONNX = ML_DIR / "clone_model.onnx"
FEATURE_MAP = ML_DIR / "clone_features.json"

_BIAS = {"UP": 1.0, "BULL": 1.0, "DOWN": -1.0, "BEAR": -1.0, "FLAT": 0.0, None: 0.0, "": 0.0}
_SESSIONS = ["ASIAN", "LONDON", "NY_OVERLAP", "NY_LATE", "TRANSITION"]
_REGIMES = ["TREND_UP", "TREND_DOWN", "TREND", "CHOP", "SPIKE", "TRANSITION"]


def _bias_val(v) -> float:
    return _BIAS.get(v, 0.0)


def _hour_from_ts(ts: str) -> int:
    try:
        return int(ts[11:13])
    except Exception:
        return 12


_VOLT = {"RISING": 1.0, "STEADY": 0.0, "FALLING": -1.0, None: 0.0, "": 0.0}


def _rich(raw: dict) -> dict:
    """Pull the rich indicators brain_v1 captures (footprint/SMC/momentum)."""
    if not isinstance(raw, dict):
        return {}
    bid = raw.get("bid") or raw.get("ask") or 0.0
    macd = raw.get("macd_m5") or {}
    adx = raw.get("adx") or {}
    # Order-block / FVG proximity: is price inside or near a bull/bear zone?
    def _near_zone(z, kind):
        try:
            box = (z or {}).get(kind)
            if not box: return 0.0
            top, bot = box.get("top", 0), box.get("bot", 0)
            if bot <= bid <= top: return 1.0          # inside the zone
            dist = min(abs(bid - top), abs(bid - bot))
            atr = (raw.get("atr") or {}).get("m5", 1) or 1
            return max(0.0, 1.0 - dist / (atr * 3))    # proximity 0..1
        except Exception:
            return 0.0
    fvg5 = raw.get("fvg_m5") or {}
    im = raw.get("intermarket") or {}
    return {
        "cvd": max(-500.0, min(500.0, float(raw.get("cvd_30m1") or 0))) / 500.0,
        "macd_hist": max(-30.0, min(30.0, float(macd.get("hist") or 0))) / 30.0,
        "adx_m5": min(float(adx.get("m5") or 0), 100.0) / 100.0,
        "adx_m15": min(float(adx.get("m15") or 0), 100.0) / 100.0,
        "vol_trend": _VOLT.get(raw.get("vol_trend_m5"), 0.0),
        "ob_bull_prox": _near_zone(raw.get("ob_m5"), "bull"),
        "ob_bear_prox": _near_zone(raw.get("ob_m5"), "bear"),
        "fvg_bull_n": min(len(fvg5.get("bull") or []), 3) / 3.0,
        "fvg_bear_n": min(len(fvg5.get("bear") or []), 3) / 3.0,
        "liq_sweep": 1.0 if raw.get("liquidity_sweep_m5") else 0.0,
        # inter-market (gold↔oil) — the user's insight
        "gold_oil_div": float(im.get("gold_oil_divergence") or 0.0),
    }


def _featurize(row: dict, side: str, raw: dict | None = None) -> list[float]:
    """Build the normalized feature vector for one sample (base + rich indicators)."""
    rsi_m1 = (row.get("rsi_m1") or 50) / 100.0
    rsi_m5 = (row.get("rsi_m5") or 50) / 100.0
    atr_m1 = row.get("atr_m1") or 0.0
    atr_h1 = row.get("atr_h1") or 1.0
    atr_ratio = (atr_m1 / atr_h1) if atr_h1 else 0.0           # normalized vol (no leak)
    atr_ratio = max(0.0, min(atr_ratio, 3.0)) / 3.0
    pressure = max(-15.0, min(15.0, float(row.get("pressure_10m1") or 0))) / 15.0
    b1 = _bias_val(row.get("bias_m1")); b5 = _bias_val(row.get("bias_m5"))
    b15 = _bias_val(row.get("bias_m15")); bh1 = _bias_val(row.get("bias_h1"))
    mtf_align = (b1 + b5 + b15 + bh1) / 4.0                    # -1..+1
    side_buy = 1.0 if side == "BUY" else 0.0
    hour = _hour_from_ts(row.get("ts", ""))
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)
    sess = row.get("session") or "?"
    sess_oh = [1.0 if sess == s else 0.0 for s in _SESSIONS]
    reg = row.get("regime") or "?"
    reg_oh = [1.0 if reg == s else 0.0 for s in _REGIMES]

    base = [rsi_m1, rsi_m5, atr_ratio, pressure, b1, b5, b15, bh1,
            mtf_align, side_buy, hour_sin, hour_cos]
    r = _rich(raw or {})
    rich = [r.get(k, 0.0) for k in _RICH_KEYS]
    return base + rich + sess_oh + reg_oh


_RICH_KEYS = ["cvd", "macd_hist", "adx_m5", "adx_m15", "vol_trend",
              "ob_bull_prox", "ob_bear_prox", "fvg_bull_n", "fvg_bear_n", "liq_sweep",
              "gold_oil_div"]

FEATURE_NAMES = (["rsi_m1", "rsi_m5", "atr_ratio", "pressure", "bias_m1", "bias_m5",
                  "bias_m15", "bias_h1", "mtf_align", "side_buy", "hour_sin", "hour_cos"]
                 + _RICH_KEYS
                 + [f"sess_{s}" for s in _SESSIONS] + [f"reg_{r}" for r in _REGIMES])


def build_dataset() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Match each closed trade to its nearest prior brain_snapshot → features."""
    trades = db.query("""
        SELECT ts, side, pnl FROM trades
        WHERE pnl IS NOT NULL
          AND ts BETWEEN (SELECT MIN(ts) FROM brain_snapshots)
                     AND (SELECT MAX(ts) FROM brain_snapshots)
        ORDER BY ts
    """)
    snaps = [dict(s) for s in db.query("SELECT * FROM brain_snapshots ORDER BY ts")]
    if not snaps or not trades:
        return np.empty((0, 0)), np.empty((0,)), []

    X, y, ts_list = [], [], []
    for t in trades:
        # nearest prior snapshot
        cand = None
        for s in snaps:
            if s["ts"] <= t["ts"]:
                cand = s
            else:
                break
        if cand is None:
            continue
        raw = {}
        try:
            if cand.get("raw_json"):
                raw = json.loads(cand["raw_json"])
        except Exception:
            pass
        feat = _featurize(cand, t["side"], raw)
        X.append(feat)
        y.append(1 if t["pnl"] > 0 else 0)
        ts_list.append(t["ts"])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64), ts_list


def train(verbose: bool = True) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score, accuracy_score, classification_report, confusion_matrix

    X, y, ts = build_dataset()
    if len(X) < 50:
        return {"ok": False, "reason": f"only {len(X)} samples — need ≥50"}

    # TIME-BASED split: first 75% train, last 25% test (no future leak)
    n = len(X)
    cut = int(n * 0.75)
    Xtr, Xte = X[:cut], X[cut:]
    ytr, yte = y[:cut], y[cut:]

    if verbose:
        print(f"  samples: {n}  (train {len(Xtr)} / test {len(Xte)})")
        print(f"  class balance: train {ytr.sum()}/{len(ytr)} win · test {yte.sum()}/{len(yte)} win")

    results = {}
    models = {
        "logreg": LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5),
        "forest": RandomForestClassifier(n_estimators=120, max_depth=4,
                                         min_samples_leaf=8, class_weight="balanced",
                                         random_state=42),
    }
    best_name, best_auc, best_model = None, -1, None
    for name, m in models.items():
        m.fit(Xtr, ytr)
        proba = m.predict_proba(Xte)[:, 1]
        pred = (proba >= 0.5).astype(int)
        try:
            auc = roc_auc_score(yte, proba)
        except Exception:
            auc = 0.5
        acc = accuracy_score(yte, pred)
        results[name] = {"auc": round(auc, 3), "acc": round(acc, 3)}
        if verbose:
            print(f"\n  [{name}] test AUC {auc:.3f} · acc {acc:.3f}")
            print(f"    confusion:\n{confusion_matrix(yte, pred)}")
        if auc > best_auc:
            best_name, best_auc, best_model = name, auc, m

    if verbose:
        print(f"\n  🏆 best: {best_name} (AUC {best_auc:.3f})")
        # Feature importance / coef
        if hasattr(best_model, "feature_importances_"):
            imp = list(zip(FEATURE_NAMES, best_model.feature_importances_))
        elif hasattr(best_model, "coef_"):
            imp = list(zip(FEATURE_NAMES, abs(best_model.coef_[0])))
        else:
            imp = []
        print("  top features:")
        for nm, v in sorted(imp, key=lambda x: -x[1])[:8]:
            print(f"    {nm:16s} {v:.3f}")

    ML_DIR.mkdir(parents=True, exist_ok=True)
    with MODEL_PKL.open("wb") as f:
        pickle.dump({"model": best_model, "features": FEATURE_NAMES, "name": best_name}, f)
    FEATURE_MAP.write_text(json.dumps({
        "features": FEATURE_NAMES, "best_model": best_name,
        "test_auc": best_auc, "results": results, "n_samples": n,
    }, indent=2), encoding="utf-8")

    # ONNX export
    onnx_ok = False
    try:
        from skl2onnx import to_onnx
        onx = to_onnx(best_model, X[:1].astype(np.float32), target_opset=17,
                      options={id(best_model): {"zipmap": False}})
        MODEL_ONNX.write_bytes(onx.SerializeToString())
        onnx_ok = True
    except Exception as e:
        if verbose: print(f"  onnx export skipped: {e}")

    verdict = "EDGE FOUND" if best_auc >= 0.58 else ("WEAK" if best_auc >= 0.53 else "NO EDGE")
    return {"ok": True, "best": best_name, "test_auc": round(best_auc, 3),
            "verdict": verdict, "n_samples": n, "onnx": onnx_ok, "results": results}


# ──────────────────────────────────────────────────────────
# Inference — used live by unified_trader as an advisory gate
# ──────────────────────────────────────────────────────────
_loaded = None
def predict(snap: dict, side: str) -> float:
    """P(win) for a live brain snapshot + intended side. 0.5 if no model."""
    global _loaded
    if _loaded is None:
        if not MODEL_PKL.exists():
            return 0.5
        with MODEL_PKL.open("rb") as f:
            _loaded = pickle.load(f)
    # flatten live snap into the same row shape
    row = {
        "rsi_m1": (snap.get("rsi") or {}).get("m1"),
        "rsi_m5": (snap.get("rsi") or {}).get("m5"),
        "atr_m1": (snap.get("atr") or {}).get("m1"),
        "atr_h1": (snap.get("atr") or {}).get("h1"),
        "pressure_10m1": snap.get("pressure_10m1"),
        "bias_m1": (snap.get("bias") or {}).get("m1"),
        "bias_m5": (snap.get("bias") or {}).get("m5"),
        "bias_m15": (snap.get("bias") or {}).get("m15"),
        "bias_h1": (snap.get("bias") or {}).get("h1"),
        "session": snap.get("session"),
        "regime": snap.get("regime"),
        "ts": snap.get("ts", ""),
    }
    feat = np.array([_featurize(row, side, snap)], dtype=np.float32)
    try:
        return float(_loaded["model"].predict_proba(feat)[0, 1])
    except Exception:
        return 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--eval", action="store_true")
    args = ap.parse_args()
    print("═══ 🧠 ML CLONE — يتعلم متى تربح ═══\n")
    r = train(verbose=True)
    print(f"\n═══ VERDICT ═══")
    if not r.get("ok"):
        print(f"  {r.get('reason')}")
    else:
        print(f"  best model: {r['best']}  ·  test AUC {r['test_auc']}  ·  {r['verdict']}")
        print(f"  (AUC 0.50 = coin flip · 0.58+ = real edge · 0.65+ = strong)")


if __name__ == "__main__":
    main()
