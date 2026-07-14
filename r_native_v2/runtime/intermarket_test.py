"""intermarket_test.py — THE COMPLEX TEST for the intermarket (inverse-correlation)
signal. Validates, on real MT5 history, whether the USD-strength-inverse + silver
context actually PREDICTS gold's forward direction — BEFORE we trust its weight.

Method (honest, walk-forward):
  • pull N days of M5 closes for XAU + EUR/JPY/GBP/CHF + XAG, align by bar time
  • at each bar: usd_strength = mean(-EURret, -GBPret, +JPYret, +CHFret) over 12 bars
    → gold_ctx = -usd_strength*0.6 + silver_ret*0.4   (the live _intermarket_align)
  • forward target = gold return over the NEXT K bars
  • measure DIRECTIONAL hit-rate (sign match) + correlation, split into time FOLDS
    for out-of-sample consistency (not one lucky window)
  • verdict: predictive only if mean OOS hit-rate >= 53% AND positive in majority of folds

Run:  python -m runtime.intermarket_test --days 60 --fwd 6 --folds 5
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))


def run(days=60, fwd=6, folds=5):
    import MetaTrader5 as mt5
    import numpy as np
    if not mt5.initialize() and not mt5.initialize():
        return {"ok": False, "reason": "mt5 init failed"}
    syms = ["XAUUSDm", "EURUSDm", "USDJPYm", "GBPUSDm", "USDCHFm", "XAGUSDm"]
    bars = int(days * 24 * 12)            # M5 bars in `days`
    close = {}
    for s in syms:
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, bars)
        if r is None or len(r) < 500:
            mt5.shutdown(); return {"ok": False, "reason": f"insufficient data for {s}"}
        close[s] = {int(x["time"]): float(x["close"]) for x in r}
    mt5.shutdown()

    # common time grid (gold's times that exist in all)
    times = sorted(t for t in close["XAUUSDm"] if all(t in close[s] for s in syms))
    n = len(times)
    if n < 400:
        return {"ok": False, "reason": f"only {n} aligned bars"}

    W = 12
    def ret(s, i):
        t0, t1 = times[i - W], times[i]
        c0, c1 = close[s][t0], close[s][t1]
        return (c1 - c0) / c0 if c0 else 0.0

    rows = []   # (gold_ctx, forward_gold_return)
    for i in range(W, n - fwd):
        eur, jpy, gbp, chf, sil = (ret("EURUSDm", i), ret("USDJPYm", i),
                                   ret("GBPUSDm", i), ret("USDCHFm", i), ret("XAGUSDm", i))
        usd = (-eur - gbp + jpy + chf) / 4.0
        usd_n = max(-1.0, min(1.0, usd / 0.003))
        gold_ctx = 0.6 * (-usd_n) + 0.4 * max(-1.0, min(1.0, sil / 0.004))
        # forward gold return over next `fwd` bars
        tg, tf_ = times[i], times[i + fwd]
        fwd_ret = (close["XAUUSDm"][tf_] - close["XAUUSDm"][tg]) / close["XAUUSDm"][tg]
        if abs(gold_ctx) < 0.05:
            continue                       # only count meaningful context
        rows.append((gold_ctx, fwd_ret))

    if len(rows) < 100:
        return {"ok": False, "reason": f"only {len(rows)} usable signals"}

    # walk-forward folds — OOS directional hit-rate per fold
    import numpy as np
    arr = np.array(rows)
    fold_sz = len(arr) // folds
    fold_hits = []
    for f in range(folds):
        seg = arr[f * fold_sz:(f + 1) * fold_sz]
        if len(seg) < 20:
            continue
        hit = np.mean(np.sign(seg[:, 0]) == np.sign(seg[:, 1]))
        fold_hits.append(round(float(hit), 3))
    overall_hit = float(np.mean(np.sign(arr[:, 0]) == np.sign(arr[:, 1])))
    corr = float(np.corrcoef(arr[:, 0], arr[:, 1])[0, 1])
    mean_fold = float(np.mean(fold_hits)) if fold_hits else 0.0
    folds_above = sum(1 for h in fold_hits if h >= 0.50)
    predictive = (mean_fold >= 0.53 and folds_above >= (len(fold_hits) + 1) // 2 and corr > 0)

    return {"ok": True, "n_signals": len(rows), "days": days, "fwd_bars": fwd,
            "overall_hit": round(overall_hit, 3), "corr": round(corr, 4),
            "mean_fold_hit": round(mean_fold, 3), "fold_hits": fold_hits,
            "folds_above_50": f"{folds_above}/{len(fold_hits)}", "predictive": predictive}


def main(argv=None):
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--fwd", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args(argv)
    r = run(args.days, args.fwd, args.folds)
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
