"""signal_optimizer.py — AUTO-OPTIMIZE the % weights like the complex test.

The user asked: "does the % auto-tune (raise/lower) like our complex test? does it
try all the possibilities?" This is that — a random/genetic search over the score
WEIGHTS (tf, ind, flow, zone, wick, rev) + sensitivity, scored against the RECORDED
outcomes (signal_predictions.jsonl). It uses a TRAIN/TEST split (the overfitting
lesson from Algory) and only promotes weights that ALSO win out-of-sample.

Writes data/signal_weights.json (read live by chart_signal_writer).
Run:  python -m runtime.signal_optimizer --loop
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

DATA = _V2 / "data"
PRED = DATA / "signal_predictions.jsonl"
WEIGHTS = DATA / "signal_weights.json"
REPORT = DATA / "signal_optimizer.md"

KEYS = ["tf", "ind", "flow", "zone", "wick", "rev", "vel", "vwap", "imb", "accel", "stoch", "intermarket"]
DEFAULT = {"tf": 0.10, "ind": 0.06, "flow": 0.20, "zone": 0.06, "wick": 0.10, "rev": 0.14,
           "vel": 0.20, "vwap": 0.12, "imb": 0.12, "accel": 0.08, "stoch": 0.16, "intermarket": 0.0, "sensitivity": 22.0}
FIXED = {"vwap": 0.12, "imb": 0.12, "accel": 0.08, "stoch": 0.16, "intermarket": 0.0}   # intermarket=0: failed the complex test (no predictive edge)
MIN_SAMPLES = 40            # need this many decided predictions before trusting an optimization
POLL = 120                 # re-optimize every 2 min
# deterministic candidate weight grid (no RNG — reproducible, "tries the possibilities")
GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
SENS_GRID = [15.0, 20.0, 25.0, 30.0]


def _load_decided():
    rows = []
    if not PRED.exists():
        return rows
    for ln in PRED.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("outcome") in ("hit", "miss") and d.get("components"):
            rows.append(d)
    return rows


def _score_weights(rows, w, sens):
    """Re-score each prediction with weights w; action = sign(score) if |score|>=sens.
    A row 'wins' if the re-scored DIRECTION matches the actual outcome."""
    decided = 0; wins = 0
    for d in rows:
        c = d["components"]
        s = 100.0 * sum(w[k] * float(c.get(k, 0.0)) for k in KEYS)
        if abs(s) < sens:
            continue                       # would be WAIT — not a decision
        pred_up = s > 0
        # outcome 'hit' means the recorded lean was right; we need the recorded lean dir
        lean_up = (d.get("lean") == "BUY")
        actual_up = lean_up if d["outcome"] == "hit" else (not lean_up)
        decided += 1
        wins += 1 if pred_up == actual_up else 0
    return (decided, wins, (wins / decided if decided else 0.0))


def _candidates():
    """Yield normalized weight dicts from the grid (sum>0). Bounded combinatorics."""
    seen = set()
    # vary the 3 most important freely, keep others at a few values -> manageable count
    for tf in GRID:
        for flow in GRID:
            for rev in GRID:
                for vel in GRID:
                    for wick in (0.0, 0.1, 0.2):
                        zone = 0.1
                        ind = max(0.0, 1.0 - (tf + flow + rev + vel + wick + zone))
                        tot = tf + ind + flow + zone + wick + rev + vel
                        if tot <= 0:
                            continue
                        w = {"tf": tf, "ind": ind, "flow": flow, "zone": zone,
                             "wick": wick, "rev": rev, "vel": vel}
                        w = {k: round(v / tot, 3) for k, v in w.items()}
                        w.update(FIXED)                      # vwap/imb/accel at default
                        key = tuple(w[k] for k in KEYS)
                        if key in seen:
                            continue
                        seen.add(key)
                        yield w


def optimize():
    rows = _load_decided()
    n = len(rows)
    if n < MIN_SAMPLES:
        return {"ok": False, "reason": f"only {n}/{MIN_SAMPLES} decided samples — keep collecting"}
    rows.sort(key=lambda d: d["ts"])
    cut = int(n * 0.67)
    train, test = rows[:cut], rows[cut:]
    best = None
    for w in _candidates():
        for sens in SENS_GRID:
            td, tw, tr = _score_weights(train, w, sens)
            if td < 10:
                continue                    # too few decisions on this combo
            if best is None or tr > best["train_acc"]:
                best = {"w": w, "sens": sens, "train_acc": tr, "train_n": td}
    if not best:
        return {"ok": False, "reason": "no combo produced enough decisions"}
    # validate OOS
    od, ow, oacc = _score_weights(test, best["w"], best["sens"])
    # baseline (current default) OOS for comparison
    bd, bw, bacc = _score_weights(test, DEFAULT, DEFAULT["sensitivity"])
    promote = (od >= 8 and oacc >= 0.55 and oacc >= bacc)   # must beat baseline AND clear 55% OOS
    result = {"ok": True, "train_acc": round(best["train_acc"], 3), "train_n": best["train_n"],
              "oos_acc": round(oacc, 3), "oos_n": od, "baseline_oos": round(bacc, 3),
              "promote": promote, "weights": best["w"], "sensitivity": best["sens"]}
    if promote:
        out = dict(best["w"]); out["sensitivity"] = best["sens"]
        out["_meta"] = {"train_acc": result["train_acc"], "oos_acc": result["oos_acc"], "ts": int(time.time())}
        WEIGHTS.write_text(json.dumps(out, indent=2), encoding="utf-8")
    # report
    L = ["# مُحسِّن الأوزان — يجرّب كل الاحتمالات (train/test)\n",
         f"عيّنات محكومة: {n} (تدريب {len(train)} / اختبار {len(test)})\n",
         f"أفضل تركيبة — دقّة تدريب {result['train_acc']*100:.0f}% · **دقّة خارج العيّنة {oacc*100:.0f}%** (الأساس {bacc*100:.0f}%)\n",
         f"الأوزان: {best['w']} · حساسية {best['sens']}\n",
         f"**{'✅ اعتُمدت (تغلّبت على الأساس + ≥55% OOS)' if promote else '⛔ لم تُعتمد (لم تتفوّق OOS — نتجنّب الـ overfitting)'}**\n",
         "> نفس درس Algory: ما نعتمد أوزان إلا لو نجحت خارج عيّنة التدريب."]
    REPORT.write_text("\n".join(L), encoding="utf-8")
    return result


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args(argv)
    while True:
        try:
            r = optimize()
            print(f"[optimizer] {r}", flush=True)
        except Exception as e:
            print(f"[optimizer] error: {e}", flush=True)
        if not (args.loop and not args.once):
            break
        time.sleep(POLL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
