"""deep_model_lab.py — HONESTY GATE for "deep learning" on our labeled manual-trade dataset.

Question (single, falsifiable): Is there a REAL predictive edge in the causal entry-time
features that beats the trivial baseline OUT-OF-SAMPLE, across a time-ordered walk-forward?
Or is it NO_EDGE (most of our historical signals were)?

Strict rules honored here:
  * READ-ONLY data. No MT5 orders. No edits to existing .py. New file only.
  * Causal features ONLY (everything in the snapshot is <= entry time by construction in
    manual_feature_recorder.snapshot). We additionally DROP outcome/leakage columns
    (net, win, hold_min, lot) and absolute price/EMA levels (non-stationary symbol id leak).
  * Time-ordered walk-forward (5 expanding blocks: train on past, test on future).
    NO random split. Single split != proof.
  * Baselines: always-predict-majority accuracy (= base win rate) and AUC=0.5.
  * Metric: OOS AUC (threshold-free, robust to the 70/30 imbalance) + OOS net expectancy.
  * Multiple-testing aware: we report a permutation/label-shuffle null for AUC so a fold
    that "beats baseline" by luck is exposed.
  * Verdict EDGE only if OOS AUC clears 0.55 in the MAJORITY of folds AND mean OOS AUC is
    well above the shuffled-label null. Otherwise NO_EDGE / INCONCLUSIVE.

Run:  C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\deep_model_lab.py
"""
from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np

DATASET = Path(r"C:\Users\Radhi\MT5\data\r_native\manual_trade_features.jsonl")
OUT = Path(r"C:\Users\Radhi\MT5\data\deep_model_lab_results.json")
RNG = np.random.default_rng(7)
N_FOLDS = 5
AUC_EDGE_BAR = 0.55  # OOS AUC must clear this in majority of folds to call EDGE

SESSIONS = ["ASIAN", "LONDON", "NYOVL", "NYPM"]


def load_records():
    recs, seen = [], {}
    for ln in DATASET.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("win") is None or r.get("net") is None or "features" not in r:
            continue
        seen[r.get("ticket")] = r  # dedupe by ticket, keep latest
    recs = list(seen.values())
    recs.sort(key=lambda r: r["time"])  # time order = walk-forward order
    return recs


def featurize(recs):
    """Build numeric matrix from CAUSAL entry-time features only.
    Excluded: net, win, hold_min, lot (outcome/sizing), price/ema8/ema21 absolute (leak)."""
    names, X, y, net, sym, t = [], [], [], [], [], []

    def candle_feats(cn):
        # 5 candles x (body_atr, uw_atr, dw_atr, bull) = 20 features; pad if short
        out = []
        for i in range(5):
            if i < len(cn):
                c = cn[i]
                out += [c.get("body_atr", 0.0), c.get("uw_atr", 0.0), c.get("dw_atr", 0.0), float(c.get("bull", 0))]
            else:
                out += [0.0, 0.0, 0.0, 0.0]
        return out

    cand_names = []
    for i in range(5):
        cand_names += [f"c{i}_body", f"c{i}_uw", f"c{i}_dw", f"c{i}_bull"]

    base_names = ["dir", "spread", "atr", "atr_pctile", "trend", "htf_trend",
                  "dist_ema_atr", "rsi", "stoch", "hour", "dow"]
    sess_names = [f"sess_{s}" for s in SESSIONS]
    names = base_names + sess_names + cand_names

    for r in recs:
        f = r["features"]
        row = [
            float(r.get("dir", 0)),
            float(f.get("spread") or 0),
            float(f.get("atr") or 0),
            float(f.get("atr_pctile") or 50.0),
            float(f.get("trend") or 0),
            float(f.get("htf_trend") or 0),
            float(f.get("dist_ema_atr") or 0),
            float(f.get("rsi") or 50.0),
            float(f.get("stoch") or 50.0),
            float(f.get("hour") or 0),
            float(f.get("dow") or 0),
        ]
        sess = f.get("session")
        row += [1.0 if sess == s else 0.0 for s in SESSIONS]
        row += candle_feats(f.get("candles", []))
        X.append(row)
        y.append(int(r["win"]))
        net.append(float(r["net"]))
        sym.append(r.get("symbol", "?"))
        t.append(r["time"])
    return names, np.array(X, float), np.array(y, int), np.array(net, float), np.array(sym), np.array(t)


def make_model():
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05,
            l2_regularization=1.0, min_samples_leaf=40,
            early_stopping=True, validation_fraction=0.15, random_state=7), "HistGradientBoostingClassifier"
    except Exception:
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(max_depth=3, n_estimators=150, learning_rate=0.05,
                                          subsample=0.8, random_state=7), "GradientBoostingClassifier"


def auc(y_true, score):
    # rank-based AUC; returns 0.5 if degenerate
    y_true = np.asarray(y_true)
    n1 = int(y_true.sum())
    n0 = len(y_true) - n1
    if n0 == 0 or n1 == 0:
        return 0.5
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score), float)
    ranks[order] = np.arange(1, len(score) + 1)
    # average ties
    s_sorted = score[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    sum_pos = ranks[y_true == 1].sum()
    return float((sum_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def walk_forward(X, y, net, t, model_factory, shuffle_y=False):
    n = len(y)
    bounds = [int(round(n * k / (N_FOLDS + 1))) for k in range(N_FOLDS + 2)]
    folds = []
    yy = y.copy()
    if shuffle_y:
        yy = RNG.permutation(yy)
    for k in range(1, N_FOLDS + 1):
        tr_end = bounds[k]
        te_end = bounds[k + 1]
        tr = slice(0, tr_end)
        te = slice(tr_end, te_end)
        if te_end - tr_end < 20 or yy[tr].sum() in (0, tr_end):
            continue
        mdl, _ = model_factory()
        mdl.fit(X[tr], yy[tr])
        if len(np.unique(yy[tr])) < 2:
            continue
        proba = mdl.predict_proba(X[te])[:, 1]
        a = auc(y[te], proba)  # eval on TRUE labels
        base = float(y[te].mean())  # baseline = test base win rate (majority predictor acc)
        # expectancy of taking only top-half-confidence trades vs all
        thr = np.median(proba)
        take = proba >= thr
        exp_take = float(net[te][take].mean()) if take.sum() else float("nan")
        exp_all = float(net[te].mean())
        folds.append({
            "fold": k, "n_train": tr_end, "n_test": int(te_end - tr_end),
            "auc": round(a, 4), "test_base_winrate": round(base, 4),
            "exp_all_net": round(exp_all, 3), "exp_topconf_net": round(exp_take, 3),
            "lift_net": round(exp_take - exp_all, 3) if not math.isnan(exp_take) else None,
        })
    return folds


def main():
    recs = load_records()
    n = len(recs)
    names, X, y, net, sym, t = featurize(recs)
    base_win = float(y.mean())

    model_factory = make_model
    _, model_name = make_model()

    real = walk_forward(X, y, net, t, model_factory, shuffle_y=False)
    # shuffled-label null (multiple-testing / luck control): repeat a few times, average AUC
    null_aucs = []
    for _ in range(5):
        fl = walk_forward(X, y, net, t, model_factory, shuffle_y=True)
        null_aucs += [f["auc"] for f in fl]
    null_mean = float(np.mean(null_aucs)) if null_aucs else 0.5
    null_std = float(np.std(null_aucs)) if null_aucs else 0.0

    aucs = [f["auc"] for f in real]
    mean_auc = float(np.mean(aucs)) if aucs else 0.5
    folds_above_bar = sum(1 for a in aucs if a >= AUC_EDGE_BAR)
    z_vs_null = (mean_auc - null_mean) / (null_std + 1e-9)

    # feature importance via permutation on a final past->recent holdout (last fold)
    importances = []
    try:
        from sklearn.inspection import permutation_importance
        cut = int(round(n * 0.8))
        mdl, _ = make_model()
        mdl.fit(X[:cut], y[:cut])
        if len(np.unique(y[:cut])) >= 2 and n - cut > 20:
            pi = permutation_importance(mdl, X[cut:], y[cut:], scoring="roc_auc",
                                        n_repeats=10, random_state=7)
            order = np.argsort(pi.importances_mean)[::-1]
            importances = [(names[i], round(float(pi.importances_mean[i]), 4)) for i in order[:10]]
    except Exception as e:
        importances = [("(perm_importance_failed)", 0.0)]

    # verdict
    enough = n >= 300
    clearly_above_null = z_vs_null >= 2.0 and (mean_auc - null_mean) >= 0.02
    majority_above_bar = folds_above_bar >= math.ceil(len(aucs) / 2.0) and len(aucs) >= 3
    if not enough:
        verdict = "INCONCLUSIVE"
    elif majority_above_bar and clearly_above_null and mean_auc >= AUC_EDGE_BAR:
        verdict = "EDGE"
    elif mean_auc < 0.53 or not clearly_above_null:
        verdict = "NO_EDGE"
    else:
        verdict = "INCONCLUSIVE"

    # overfit risk: gap between in-sample-ish and oos, plus null proximity
    if mean_auc - null_mean < 0.015:
        overfit = "low"  # model isn't even learning past noise into test -> not overfit, just no signal
    elif mean_auc >= AUC_EDGE_BAR and z_vs_null >= 3:
        overfit = "low"
    elif mean_auc >= 0.53:
        overfit = "medium"
    else:
        overfit = "medium"

    result = {
        "n_samples": n,
        "model": model_name,
        "target": "win (net>0) classification; net used for expectancy",
        "validation": f"{len(aucs)}-fold time-ordered walk-forward (expanding train, future test), no random split",
        "base_winrate": round(base_win, 4),
        "metric_name": "OOS AUC (mean across walk-forward folds)",
        "mean_oos_auc": round(mean_auc, 4),
        "folds": real,
        "folds_above_0.55": folds_above_bar,
        "shuffled_label_null_auc_mean": round(null_mean, 4),
        "shuffled_label_null_auc_std": round(null_std, 4),
        "z_auc_vs_null": round(z_vs_null, 2),
        "top_features_perm_importance_auc": importances,
        "verdict": verdict,
        "overfit_risk": overfit,
        "net_sum_dataset": round(float(net.sum()), 2),
        "symbols": {s: int((sym == s).sum()) for s in sorted(set(sym.tolist()))},
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
