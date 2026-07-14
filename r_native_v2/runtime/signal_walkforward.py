"""signal_walkforward.py — PURGED / EMBARGOED WALK-FORWARD validation of the
signal weights (pro-panel Step-3). The single 67/33 train/test split in
signal_optimizer.py can still overfit one cut; this does proper rolling
out-of-sample cross-validation and only promotes weights that beat the
equal-weight/default baseline OOS *consistently across folds*.

Method:
  • sort the recorded (components, outcome) rows by time
  • build K sequential folds; for fold i, train on everything before it with an
    EMBARGO gap (>= the outcome horizon, ~10 samples) purged out so a prediction
    whose 10-min outcome overlaps the test window cannot leak into training
  • score EVERY candidate weight set on EVERY fold's test slice; rank by MEAN
    out-of-sample accuracy across folds (with a minimum fold-coverage)
  • PROMOTE only if mean OOS >= 0.55, beats baseline by >= 0.03, and is positive
    (>baseline) in the majority of folds

Reuses signal_optimizer's data loader, candidate grid and scorer.
Run:  python -m runtime.signal_walkforward --once   (or --loop)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

from runtime import signal_optimizer as so   # reuse loader/grid/scorer

DATA = _V2 / "data"
WF_WEIGHTS = DATA / "signal_weights.json"      # same file chart_signal_writer reads
WF_REPORT = DATA / "signal_walkforward.md"

K_FOLDS = 5
EMBARGO = 10                 # samples purged between train and test (>= horizon/log_every)
MIN_TOTAL = 80              # need at least this many decided samples to even try
MIN_FOLD_DECISIONS = 5      # a candidate must make >= this many test decisions in a fold to count
MIN_FOLDS_COVERED = 3       # ...in at least this many folds
PASS_OOS = 0.55             # promote only above this mean OOS accuracy
PASS_MARGIN = 0.03          # ...and at least this much above baseline
POLL = 300


def _folds(n, k):
    """Return list of (train_end, test_start, test_end) with an embargo gap."""
    out = []
    step = n // (k + 1)
    if step < (MIN_FOLD_DECISIONS + EMBARGO):
        return out
    for i in range(1, k + 1):
        tr_end = i * step
        te_start = tr_end + EMBARGO
        te_end = min(n, (i + 1) * step)
        if te_start < te_end:
            out.append((tr_end, te_start, te_end))
    return out


def walk_forward():
    rows = so._load_decided()
    n = len(rows)
    if n < MIN_TOTAL:
        return {"ok": False, "reason": f"only {n}/{MIN_TOTAL} decided samples — keep collecting"}
    rows.sort(key=lambda d: d["ts"])
    folds = _folds(n, K_FOLDS)
    if not folds:
        return {"ok": False, "reason": f"{n} samples too few for {K_FOLDS} folds + embargo {EMBARGO}"}

    cands = list(so._candidates())
    # score every candidate (+ its best sens per fold-train) across folds' TEST slices.
    # To keep it honest+bounded: for each fold, pick the candidate's best sens on the
    # TRAIN slice, then evaluate that on the TEST slice (no test-set peeking for sens).
    best = None
    base_oos = []   # baseline OOS acc per fold
    for (tr_end, te_start, te_end) in folds:
        train = rows[:tr_end]; test = rows[te_start:te_end]
        bd, bw, bacc = so._score_weights(test, so.DEFAULT, so.DEFAULT["sensitivity"])
        if bd >= MIN_FOLD_DECISIONS:
            base_oos.append(bacc)

    # evaluate each candidate across folds
    scored = []
    for w in cands:
        accs = []; ns = 0
        for (tr_end, te_start, te_end) in folds:
            train = rows[:tr_end]; test = rows[te_start:te_end]
            # pick this candidate's best sensitivity on TRAIN only
            bs = None
            for sens in so.SENS_GRID:
                td, tw, tr = so._score_weights(train, w, sens)
                if td < 8:
                    continue
                if bs is None or tr > bs[1]:
                    bs = (sens, tr)
            if bs is None:
                continue
            od, ow, oacc = so._score_weights(test, w, bs[0])
            if od >= MIN_FOLD_DECISIONS:
                accs.append(oacc); ns += 1
        if ns >= MIN_FOLDS_COVERED:
            mean_oos = sum(accs) / len(accs)
            scored.append({"w": w, "mean_oos": mean_oos, "folds": ns, "accs": accs})

    if not scored:
        return {"ok": False, "reason": "no candidate made enough decisions across folds"}
    scored.sort(key=lambda x: x["mean_oos"], reverse=True)
    top = scored[0]
    baseline = (sum(base_oos) / len(base_oos)) if base_oos else 0.0
    folds_beating = sum(1 for a in top["accs"] if a > baseline)
    promote = (top["mean_oos"] >= PASS_OOS
               and top["mean_oos"] >= baseline + PASS_MARGIN
               and folds_beating >= (len(top["accs"]) + 1) // 2)

    # pick the sensitivity for the promoted weights = its most common best-sens on the full set
    full_best_sens = so.DEFAULT["sensitivity"]
    bs = None
    for sens in so.SENS_GRID:
        td, tw, tr = so._score_weights(rows, top["w"], sens)
        if td >= 8 and (bs is None or tr > bs[1]):
            bs = (sens, tr)
    if bs:
        full_best_sens = bs[0]

    result = {"ok": True, "n": n, "folds": len(folds), "baseline_oos": round(baseline, 3),
              "best_mean_oos": round(top["mean_oos"], 3), "folds_covered": top["folds"],
              "folds_beating_base": folds_beating, "per_fold": [round(a, 3) for a in top["accs"]],
              "promote": promote, "weights": top["w"], "sensitivity": full_best_sens}

    if promote:
        out = dict(top["w"]); out["sensitivity"] = full_best_sens
        out["_meta"] = {"method": "walk_forward", "mean_oos": result["best_mean_oos"],
                        "baseline_oos": result["baseline_oos"], "folds": len(folds),
                        "ts": int(time.time())}
        WF_WEIGHTS.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# تحقّق Walk-Forward للأوزان (purged/embargoed CV)\n",
         f"عيّنات محكومة: {n} · folds: {len(folds)} · embargo: {EMBARGO}\n",
         f"خط الأساس (الأوزان الافتراضية) OOS: {baseline*100:.0f}%\n",
         f"أفضل تركيبة — **متوسط OOS عبر الـfolds: {top['mean_oos']*100:.0f}%** "
         f"(تغطية {top['folds']} folds · تتفوّق على الأساس في {folds_beating})\n",
         f"OOS لكل fold: {[round(a*100) for a in top['accs']]}\n",
         f"الأوزان: {top['w']} · حساسية {full_best_sens}\n",
         f"**{'✅ اعتُمدت (تفوّقت OOS عبر الـfolds)' if promote else '⛔ لم تُعتمد — لا تتفوّق باستمرار خارج العيّنة (نتجنّب الـoverfitting)'}**\n",
         "> الانضباط: ما ننشر أوزاناً إلا لو صمدت walk-forward عبر عدّة نوافذ، لا مجرد تقسيمة واحدة."]
    WF_REPORT.write_text("\n".join(L), encoding="utf-8")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args(argv)
    while True:
        try:
            r = walk_forward()
            print(f"[walkforward] {r}", flush=True)
        except Exception as e:
            print(f"[walkforward] error: {e}", flush=True)
        if not (args.loop and not args.once):
            break
        time.sleep(POLL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
