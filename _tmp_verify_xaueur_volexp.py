#!/usr/bin/env python3
"""Adversarial verification of CLAIMED edge:
   XAUEURm M5 VOL_EXPANSION_long  OOS PF=1.6869 expR=0.37266 n=64.
Reuses full_scan_lab.py logic verbatim (strict no-lookahead, next-bar entry,
SL-before-TP intrabar, cost in price units / stop-dist -> R).
Adds: (1) reproduce, (2) walk-forward 5 blocks, (3) multiple-testing bars.
"""
import os, numpy as np
import scipy.stats as st

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

# ---- params copied verbatim from full_scan_lab.py ----
EMA_FAST, EMA_SLOW, EMA_MR, ATR_N, BREAK_N = 8, 21, 20, 14, 20
PULLBACK_TOL, MR_SIGMA, VOL_MULT, SL_ATR, RR, MAX_HOLD = 0.25, 2.0, 2.5, 1.5, 2.0, 200
COST_PRICE_XAUEUR = 0.30
BOOT_N = 2000
RNG = np.random.default_rng(20260618)   # same seed as lab


def ema(x, n):
    a = 2.0 / (n + 1.0); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)): out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out

def atr(h, l, c, n):
    tr = np.empty(len(c)); tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.empty(len(c)); out[:n] = np.nan; out[n-1] = np.mean(tr[:n]); a = 1.0/n
    for i in range(n, len(c)): out[i] = a*tr[i] + (1-a)*out[i-1]
    return out

def gen_vol_exp_long(o, h, l, c, a):
    """VOL_EXPANSION long signals only (matches lab gen_signals + side filter)."""
    sigs = []; n = len(c)
    for i in range(max(EMA_SLOW, ATR_N, BREAK_N) + 1, n - 1):
        ai = a[i]
        if not np.isfinite(ai) or ai <= 0: continue
        if (h[i] - l[i]) > VOL_MULT * ai:
            direction = +1 if c[i] >= o[i] else -1
            if direction == +1:
                sigs.append((i, +1, SL_ATR * ai))
    return sigs

def simulate(sigs, o, h, l, c, cost_price):
    n = len(c); out = []; busy_until = -1
    for (i, d, sl_dist) in sigs:           # d always +1 here
        ei = i + 1
        if ei >= n or ei <= busy_until: continue
        if sl_dist <= 0 or not np.isfinite(sl_dist): continue
        entry = o[ei]; sl = entry - sl_dist; tp = entry + RR * sl_dist
        if tp <= entry: continue
        R = sl_dist; cost_R = cost_price / R; outcome = None; exit_idx = ei
        end = min(ei + MAX_HOLD, n)
        for j in range(ei, end):
            exit_idx = j
            if l[j] <= sl: outcome = (sl - entry) / R; break
            if h[j] >= tp: outcome = (tp - entry) / R; break
        if outcome is None:
            j = end - 1; exit_idx = j; outcome = (c[j] - entry) / R
        out.append((ei, outcome - cost_R))
        busy_until = exit_idx
    return out

def profit_factor(rs):
    rs = np.asarray(rs); g = rs[rs > 0].sum(); ls = -rs[rs < 0].sum()
    if ls <= 0: return float("inf") if g > 0 else 0.0
    return float(g / ls)

def bootstrap_ci(rs, n_boot, rng, lo_p=2.5, hi_p=97.5):
    rs = np.asarray(rs)
    if len(rs) < 2: return (float("nan"), float("nan"))
    means = np.empty(n_boot); nrec = len(rs)
    for b in range(n_boot):
        means[b] = rs[rng.integers(0, nrec, nrec)].mean()
    lo, hi = np.percentile(means, [lo_p, hi_p])
    return float(lo), float(hi)


def main():
    d = np.load(os.path.join(HERE, "XAUEURm_M5.npz"))
    o = d["o"].astype(float); h = d["h"].astype(float)
    l = d["l"].astype(float); c = d["c"].astype(float)
    n = len(c); split = int(n * 0.67)
    a = atr(h, l, c, ATR_N)
    sigs = gen_vol_exp_long(o, h, l, c, a)
    trades = simulate(sigs, o, h, l, c, COST_PRICE_XAUEUR)

    # ---------- (1) REPRODUCE ----------
    oos = [(ei, r) for (ei, r) in trades if ei >= split]
    rs = np.asarray([r for (ei, r) in oos])
    npos = len(rs)
    expR = float(rs.mean()); pf = profit_factor(rs)
    lo95, hi95 = bootstrap_ci(rs, BOOT_N, np.random.default_rng(20260618))
    print("=== (1) REPRODUCE (OOS, net of cost) ===")
    print(f"  n={npos}  PF={pf:.4f}  expR={expR:.5f}  CI95=[{lo95:+.5f},{hi95:+.5f}]")
    print(f"  CLAIM   n=64  PF=1.6869  expR=0.37266")
    reproduced = (npos == 64 and abs(pf - 1.6869) < 0.01 and abs(expR - 0.37266) < 0.001)
    print(f"  reproduced={reproduced}")

    # ---------- (2) WALK-FORWARD: 5 sequential blocks over ALL trades ----------
    print("\n=== (2) WALK-FORWARD 5 sequential blocks (entire history) ===")
    all_rs = np.asarray([r for (ei, r) in trades])
    all_ei = np.asarray([ei for (ei, r) in trades])
    nb = 5
    edges = np.linspace(0, n, nb + 1).astype(int)   # split by BAR index (time)
    blk_pf = []; blk_exp = []; blk_n = []
    for b in range(nb):
        lo_b, hi_b = edges[b], edges[b+1]
        m = (all_ei >= lo_b) & (all_ei < hi_b)
        r = all_rs[m]; blk_n.append(len(r))
        if len(r) == 0:
            blk_pf.append(float("nan")); blk_exp.append(float("nan")); continue
        blk_pf.append(profit_factor(r)); blk_exp.append(float(r.mean()))
    profitable_blocks = 0
    for b in range(nb):
        good = (np.isfinite(blk_pf[b]) and blk_pf[b] >= 1.2 and blk_exp[b] > 0)
        profitable_blocks += int(good)
        pfs = f"{blk_pf[b]:.2f}" if np.isfinite(blk_pf[b]) else "nan"
        es  = f"{blk_exp[b]:+.4f}" if np.isfinite(blk_exp[b]) else "nan"
        print(f"  block {b+1}: n={blk_n[b]:3d}  PF={pfs:>6}  expR={es}  {'OK' if good else ''}")
    print(f"  profitable_blocks(PF>=1.2 & expR>0) = {profitable_blocks}/5")
    wf_robust = (profitable_blocks >= 4)
    print(f"  walk_forward_robust(>=4/5) = {wf_robust}")

    # also report OOS-region block breakdown (the 64 trades themselves)
    print("\n  -- within-OOS detail (the claimed 64 trades, split into 4 quartiles) --")
    if npos >= 8:
        q = np.array_split(rs, 4)
        for k, seg in enumerate(q):
            print(f"     q{k+1}: n={len(seg):2d} PF={profit_factor(seg):5.2f} expR={seg.mean():+.4f}")

    # ---------- (3) MULTIPLE TESTING ----------
    print("\n=== (3) MULTIPLE-TESTING / stricter bar ===")
    M = 507  # claimed scanned-cell universe
    # one-sample t-test on per-trade R (H0: mean<=0)
    t_stat, p_two = st.ttest_1samp(rs, 0.0)
    p_one = p_two / 2 if t_stat > 0 else 1 - p_two / 2
    print(f"  one-sided t-test on per-trade R: t={t_stat:.3f}  p_one={p_one:.5f}")
    bonf_alpha = 0.05 / M
    print(f"  Bonferroni alpha = 0.05/{M} = {bonf_alpha:.2e}")
    passes_bonf_t = (p_one < bonf_alpha)
    print(f"  passes Bonferroni via t-test = {passes_bonf_t}")

    # bootstrap CI at Bonferroni-corrected level (two-sided): alpha=0.05/M
    pct_lo = 100.0 * (bonf_alpha / 2.0)
    pct_hi = 100.0 - pct_lo
    blo, bhi = bootstrap_ci(rs, 20000, np.random.default_rng(777), lo_p=pct_lo, hi_p=pct_hi)
    print(f"  Bonferroni bootstrap CI [{pct_lo:.5f}%,{pct_hi:.5f}%] = [{blo:+.4f},{bhi:+.4f}]")
    passes_bonf_boot = (blo > 0)
    print(f"  passes Bonferroni via bootstrap CI (lo>0) = {passes_bonf_boot}")

    # 99% bootstrap CI (milder bar requested in prompt)
    c99lo, c99hi = bootstrap_ci(rs, 20000, np.random.default_rng(888), lo_p=0.5, hi_p=99.5)
    print(f"  99% bootstrap CI = [{c99lo:+.4f},{c99hi:+.4f}]  excl0={c99lo>0}")

    survives_mt = bool(passes_bonf_boot or passes_bonf_t)
    print(f"  survives_multiple_testing = {survives_mt}")

    print("\n=== VERDICT ===")
    confirmed = bool(reproduced and wf_robust and survives_mt)
    print(f"  reproduced={reproduced}  wf_robust={wf_robust}  survives_mt={survives_mt}")
    print(f"  CONFIRMED = {confirmed}")


if __name__ == "__main__":
    main()
