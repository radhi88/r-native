#!/usr/bin/env python3
"""Adversarial verification of AUDJPYm M15 MEAN_REVERSION_LONG claimed edge.
Reuses full_scan_lab_fxcrosses.py logic EXACTLY (causal, no-lookahead, same cost model).

Claim: OOS PF=1.2405, expR=0.15087, n=615.
Checks: (1) reproduce; (2) walk-forward 5 sequential OOS sub-blocks;
        (3) multiple-testing (Bonferroni over ~507 cells, ~99.99% per-test CI).
"""
import json
import os
import numpy as np

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

EMA_MR = 20
ATR_N = 14
BREAK_N = 20
EMA_SLOW = 21
MR_SIGMA = 2.0
SL_ATR = 1.5
RR = 2.0
MAX_HOLD = 200
BOOT_N = 2000
RNG = np.random.default_rng(20260618)


def roundtrip_cost_price(point):
    pip = point * 10.0
    return 1.5 * pip


def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(h, l, c, n):
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.empty(len(c))
    out[:n] = np.nan
    out[n - 1] = np.mean(tr[:n])
    a = 1.0 / n
    for i in range(n, len(c)):
        out[i] = a * tr[i] + (1 - a) * out[i - 1]
    return out


def gen_signals_mr_long(o, h, l, c, ema_m, a):
    """MEAN_REVERSION long: dev = close-EMA20 < -2*ATR -> long, TP=EMA20, SL=1.5*ATR."""
    sigs = []
    n = len(c)
    start = max(EMA_SLOW, ATR_N, BREAK_N) + 1
    for i in range(start, n - 1):
        ai = a[i]
        if not np.isfinite(ai) or ai <= 0:
            continue
        ci = c[i]
        dev = ci - ema_m[i]
        if dev < -MR_SIGMA * ai:
            sigs.append((i, SL_ATR * ai, ema_m[i]))
    return sigs


def simulate_long(sigs, o, h, l, c, cost_price):
    n = len(c)
    rows = []  # (signal_idx i, net_R)
    d = 1
    for (i, sl_dist, tp_price) in sigs:
        ei = i + 1
        if ei >= n:
            continue
        entry = o[ei]
        if sl_dist <= 0 or not np.isfinite(sl_dist):
            continue
        sl = entry - sl_dist
        tp = (entry + RR * sl_dist) if tp_price is None else tp_price
        if tp <= entry:
            continue
        R = sl_dist
        cost_R = cost_price / R
        outcome = None
        end = min(ei + MAX_HOLD, n)
        for j in range(ei, end):
            hi, lo = h[j], l[j]
            if lo <= sl:
                outcome = -1.0
                break
            if hi >= tp:
                outcome = (tp - entry) / R
                break
        if outcome is None:
            j = end - 1
            outcome = (c[j] - entry) / R
        rows.append((i, outcome - cost_R))
    return rows


def profit_factor(rs):
    rs = np.asarray(rs)
    gains = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def bootstrap_ci(rs, pct, n_boot=BOOT_N):
    rs = np.asarray(rs)
    if len(rs) < 2:
        return (float("nan"), float("nan"))
    nrec = len(rs)
    idx = RNG.integers(0, nrec, size=(n_boot, nrec))
    means = rs[idx].mean(axis=1)
    lo, hi = np.percentile(means, [pct, 100.0 - pct])
    return float(lo), float(hi)


def main():
    sym = "AUDJPYm"
    tf = "M15"
    meta = json.load(open(os.path.join(HERE, sym + "_meta.json")))
    point = meta.get("point", meta.get("trade_tick_size", 1e-5))
    cost_price = roundtrip_cost_price(point)

    npz = np.load(os.path.join(HERE, sym + "_" + tf + ".npz"))
    o = npz["o"].astype(float); h = npz["h"].astype(float)
    l = npz["l"].astype(float); c = npz["c"].astype(float)
    n = len(c)
    split = int(n * 0.67)

    ema_m = ema(c, EMA_MR)
    a = atr(h, l, c, ATR_N)

    sigs = gen_signals_mr_long(o, h, l, c, ema_m, a)
    rows = simulate_long(sigs, o, h, l, c, cost_price)

    # OOS = signal bar in OOS window (matches fxcrosses: s[0] >= split)
    oos = [(i, r) for (i, r) in rows if i >= split]
    oos_rs = np.array([r for (i, r) in oos])
    npos = len(oos_rs)
    expR = float(np.mean(oos_rs))
    pf = profit_factor(oos_rs)
    lo95, hi95 = bootstrap_ci(oos_rs, 2.5)

    print("=" * 70)
    print("REPRODUCE: AUDJPYm M15 MEAN_REVERSION_LONG")
    print("  cost_price=%.5f (point=%s, 1.5pip)" % (cost_price, point))
    print("  total bars=%d  split(67%%)=%d  total signals=%d  OOS trades=%d"
          % (n, split, len(rows), npos))
    print("  OOS PF=%.4f  expR=%.5f" % (pf, expR))
    print("  Claimed: PF=1.2405 expR=0.15087 n=615")
    print("  95%% bootstrap CI of avgR = [%+.5f, %+.5f]" % (lo95, hi95))
    print("=" * 70)

    # ---- (2) WALK-FORWARD: 5 sequential blocks across the WHOLE series ----
    # Partition all trades by signal-bar time into 5 equal-count sequential blocks.
    all_rows = sorted(rows, key=lambda x: x[0])
    all_rs = np.array([r for (i, r) in all_rows])
    nb = 5
    print("\nWALK-FORWARD (5 sequential blocks across full series, by trade order):")
    wf_pos = 0
    block_stats = []
    idxs = np.array_split(np.arange(len(all_rs)), nb)
    for bi, ix in enumerate(idxs):
        seg = all_rs[ix]
        bpf = profit_factor(seg)
        bexp = float(np.mean(seg))
        block_stats.append((len(seg), bpf, bexp))
        ok = bexp > 0 and bpf > 1.0
        wf_pos += 1 if ok else 0
        print("  block %d: n=%4d  PF=%6.3f  expR=%+.5f  %s"
              % (bi + 1, len(seg), bpf, bexp, "POS" if ok else "neg"))
    print("  -> blocks positive (expR>0 & PF>1): %d/5" % wf_pos)

    # Also walk-forward WITHIN the OOS window only (5 sub-blocks) — stricter, OOS-only.
    oos_rows = sorted(oos, key=lambda x: x[0])
    oos_only = np.array([r for (i, r) in oos_rows])
    print("\nWALK-FORWARD (5 sequential sub-blocks WITHIN OOS window only):")
    wf_pos_oos = 0
    idxs2 = np.array_split(np.arange(len(oos_only)), nb)
    for bi, ix in enumerate(idxs2):
        seg = oos_only[ix]
        bpf = profit_factor(seg)
        bexp = float(np.mean(seg))
        ok = bexp > 0 and bpf > 1.0
        wf_pos_oos += 1 if ok else 0
        print("  oos-block %d: n=%4d  PF=%6.3f  expR=%+.5f  %s"
              % (bi + 1, len(seg), bpf, bexp, "POS" if ok else "neg"))
    print("  -> OOS sub-blocks positive: %d/5" % wf_pos_oos)

    # ---- (3) MULTIPLE TESTING: Bonferroni over ~507 cells ----
    N_CELLS = 507
    # Per-test alpha for family-wise 5%: alpha = 0.05/507
    alpha = 0.05 / N_CELLS
    pct = 100.0 * (alpha / 2.0)  # two-sided percentile for the CI tail
    loB, hiB = bootstrap_ci(oos_rs, pct)
    bonf_excl = (loB > 0) or (hiB < 0)
    # Parametric one-sample t against 0 (avgR>0), one-sided p, compare to alpha
    from math import sqrt
    sd = float(np.std(oos_rs, ddof=1))
    se = sd / sqrt(npos)
    t = expR / se if se > 0 else 0.0
    # normal approx for large n
    from statistics import NormalDist
    p_one = 1.0 - NormalDist().cdf(t)  # P(T> t) for H1: mean>0
    print("\nMULTIPLE TESTING (family of ~%d cells, Bonferroni FWER 5%%):" % N_CELLS)
    print("  per-test alpha=%.3e -> need CI at %.4f%% tail" % (alpha, 100 - 2 * pct))
    print("  Bonferroni bootstrap CI = [%+.5f, %+.5f]  excludes0=%s"
          % (loB, hiB, bonf_excl))
    print("  one-sample t-stat (avgR vs 0) = %.3f  one-sided p=%.3e" % (t, p_one))
    print("  survives Bonferroni (p < %.3e)? %s" % (alpha, p_one < alpha))

    # 99% CI as an intermediate bar
    lo99, hi99 = bootstrap_ci(oos_rs, 0.5)
    print("  99%% CI = [%+.5f, %+.5f]  excludes0=%s"
          % (lo99, hi99, (lo99 > 0) or (hi99 < 0)))

    print("\nSUMMARY")
    print("  reproduce: PF=%.4f vs 1.2405 ; expR=%.5f vs 0.15087 ; n=%d vs 615"
          % (pf, expR, npos))
    print("  walk_forward full=%d/5  oos-only=%d/5" % (wf_pos, wf_pos_oos))
    print("  multiple_testing survives=%s" % (p_one < alpha and bonf_excl))


if __name__ == "__main__":
    main()
