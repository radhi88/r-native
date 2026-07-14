"""
scratch_mtf_align_lab.py  —  Multi-timeframe STRICT alignment (M15 + H1 + H4 all agree) directional.

RULE (one precise testable rule):
  Trend on a TF = EMA_fast > EMA_slow (bull=+1) / < (bear=-1).
  Base = M15 (entry TF). Higher = H1 and H4 (H4 resampled from H1).
  At the CLOSE of M15 bar i, using ONLY fully-closed higher-TF bars, if
  M15 trend == H1 trend == H4 trend == d, and alignment is FRESH
  (prior M15 bar was not aligned to d), open a trade at OPEN of bar i+1 in dir d.
  SL = SL_ATR * ATR14(M15). TP = TP_R * risk. Conservative intrabar (SL first).

Strict no-lookahead:
  - M15 signal at i uses data<=i; entry at open of i+1.
  - Higher-TF trend at decision moment m_close=t_m15[i]+900 uses the LAST higher
    bar that has FULLY CLOSED by m_close (searchsorted on bar-close times).
  - Intrabar SL-before-TP conservative.
Cost: round-trip in PRICE units, subtracted from raw P&L before R.
Walk-forward: 67/33 time split. Params chosen on IS, measured ONLY on OOS.
"""
import json, os, numpy as np

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

# round-trip cost in PRICE units (realistic spread)
COST = {
    "XAUUSDm": 0.30, "US30m": 3.0, "US500m": 0.6, "USTECm": 2.5,
    "BTCUSDm": 20.0, "GBPJPYm": 0.020, "USDJPYm": 0.015, "DE30m": 2.0,
    "EURUSDm": 0.00015, "USOILm": 0.004,
}
SYMBOLS = ["XAUUSDm", "US30m", "US500m", "USTECm", "BTCUSDm", "GBPJPYm", "USDJPYm", "DE30m"]

ATR_LEN = 14
SL_ATR = 1.5
MAX_HOLD = 400
IS_FRAC = 0.67
N_BOOT = 2000
SEED = 12345

# IS param grid (chosen on IS, OOS-reported)
EMA_PAIRS = [(20, 50), (10, 30)]
TP_RS = [1.5, 2.0, 2.5]


def ema(x, n):
    a = 2.0/(n+1.0); out = np.empty_like(x, dtype=np.float64); out[0] = x[0]
    for i in range(1, len(x)): out[i] = a*x[i] + (1-a)*out[i-1]
    return out

def atr(h, l, c, n):
    m = len(c); tr = np.empty(m); tr[0] = h[0]-l[0]
    for i in range(1, m): tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.empty(m); out[0] = tr[0]; a = 1.0/n
    for i in range(1, m): out[i] = a*tr[i] + (1-a)*out[i-1]
    return out

def load(sym, tf):
    d = np.load(os.path.join(LAB, f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64), d["o"].astype(np.float64), d["h"].astype(np.float64),
            d["l"].astype(np.float64), d["c"].astype(np.float64))

def resample_h4(t, o, h, l, c):
    """Aggregate H1 into calendar-aligned H4 buckets (0,4,8,12,16,20 UTC)."""
    bucket = t // (4*3600)
    ub, idx = np.unique(bucket, return_index=True)
    # build per-bucket OHLC and bucket-start time
    T, C = [], []
    for k in range(len(ub)):
        s = idx[k]; e = idx[k+1] if k+1 < len(ub) else len(t)
        T.append(ub[k]*4*3600)
        C.append(c[e-1])
    return np.array(T, dtype=np.int64), np.array(C, dtype=np.float64)

def trend_arr(closes, ef, es):
    return np.where(ema(closes, ef) > ema(closes, es), 1, -1)

def higher_trend_on_m15(t_m15, t_hi, trend_hi, bar_secs):
    """For each M15 close moment, last fully-closed higher bar's trend."""
    hi_close = t_hi + bar_secs
    m_close = t_m15 + 900
    pos = np.searchsorted(hi_close, m_close, side="right") - 1
    out = np.zeros(len(t_m15), dtype=np.int64)
    valid = pos >= 0
    out[valid] = trend_hi[pos[valid]]
    out[~valid] = 0
    return out

def resolve(h, l, c, ei, d, sl, tp):
    n = len(c); end = min(n, ei+MAX_HOLD)
    for j in range(ei, end):
        hi, lo = h[j], l[j]
        if d == 1:
            if lo <= sl: return sl, j
            if hi >= tp: return tp, j
        else:
            if hi >= sl: return sl, j
            if lo <= tp: return tp, j
    return c[end-1], end-1

def gen_trades(sym, ef, es, tp_r):
    t15, o, h, l, c = load(sym, "M15")
    th1, _, _, _, ch1 = load(sym, "H1")
    th4, ch4 = resample_h4(*load(sym, "H1"))
    atr15 = atr(h, l, c, ATR_LEN)
    tr15 = trend_arr(c, ef, es)
    tr_h1 = higher_trend_on_m15(t15, th1, trend_arr(ch1, ef, es), 3600)
    tr_h4 = higher_trend_on_m15(t15, th4, trend_arr(ch4, ef, es), 4*3600)

    align = np.zeros(len(c), dtype=np.int64)
    both = (tr15 == tr_h1) & (tr15 == tr_h4) & (tr_h1 != 0) & (tr_h4 != 0)
    align[both] = tr15[both]

    cost = COST[sym]
    start = max(es, ATR_LEN) + 5
    trades = []  # (entry_time, R, dir)
    for i in range(start, len(c)-1):
        d = align[i]
        if d == 0: continue
        if align[i-1] == d: continue  # not fresh
        a = atr15[i]
        if not np.isfinite(a) or a <= 0: continue
        ei = i+1; entry = o[ei]; risk = SL_ATR*a
        sl = entry - risk if d == 1 else entry + risk
        tp = entry + tp_r*risk if d == 1 else entry - tp_r*risk
        xp, xi = resolve(h, l, c, ei, d, sl, tp)
        raw = (xp-entry) if d == 1 else (entry-xp)
        R = (raw - cost)/risk
        trades.append((t15[ei], R, d))
    return trades, t15

def boot_ci(rs, seed=SEED):
    rs = np.asarray(rs)
    if len(rs) < 2: return float("nan"), float("nan")
    rng = np.random.default_rng(seed); n = len(rs)
    m = np.array([rs[rng.integers(0, n, n)].mean() for _ in range(N_BOOT)])
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))

def max_dd_R(rs):
    eq = np.cumsum(rs); peak = np.maximum.accumulate(eq)
    return float((eq-peak).min()) if len(rs) else 0.0

def stats(rs):
    rs = np.asarray(rs, dtype=np.float64); n = len(rs)
    if n == 0: return dict(n=0, expR=0, t=0, pf=0, wr=0, dd=0)
    mean = rs.mean(); sd = rs.std()
    t = mean/(sd+1e-9)*np.sqrt(n)
    g = rs[rs > 0].sum(); losv = -rs[rs < 0].sum()
    pf = (g/losv) if losv > 0 else float("inf")
    return dict(n=int(n), expR=float(mean), t=float(t), pf=float(pf),
                wr=float((rs > 0).mean()), dd=max_dd_R(rs))

def run():
    np.seterr(all="ignore")
    per_sym = {}
    pooled_is, pooled_oos = {}, {}  # keyed by (ef,es,tp_r)
    for sym in SYMBOLS:
        # split time from M15 timestamps
        _, t15 = None, None
        # find split time once (use M15 t array)
        d = np.load(os.path.join(LAB, f"{sym}_M15.npz"))
        t = d["t"].astype(np.int64); split_t = t[int(len(t)*IS_FRAC)]
        best = None
        for (ef, es) in EMA_PAIRS:
            for tp_r in TP_RS:
                trades, _ = gen_trades(sym, ef, es, tp_r)
                is_r = [r for (tt, r, dd) in trades if tt < split_t]
                oos_r = [r for (tt, r, dd) in trades if tt >= split_t]
                # accumulate pooled
                pooled_is.setdefault((ef, es, tp_r), []).extend(is_r)
                pooled_oos.setdefault((ef, es, tp_r), []).extend(oos_r)
                iss = stats(is_r)
                cand = {"ef": ef, "es": es, "tp_r": tp_r, "is": iss,
                        "oos": stats(oos_r), "n_is": len(is_r), "n_oos": len(oos_r)}
                if best is None or iss["expR"] > best["is"]["expR"]:
                    best = cand
        per_sym[sym] = best

    # pooled: pick param by pooled IS expectancy, report pooled OOS
    pbest = None
    for key, isr in pooled_is.items():
        iss = stats(isr)
        cand = {"key": key, "is": iss, "oos": stats(pooled_oos[key])}
        if pbest is None or iss["expR"] > pbest["is"]["expR"]:
            pbest = cand

    out = {"per_symbol": {}, "pooled": None}
    print(f"{'SYM':8s} EMA  TP  | IS_n IS_expR  IS_t | OOS_n OOS_expR OOS_t  PF   WR   DD")
    print("-"*92)
    for sym, b in per_sym.items():
        o_ = b["oos"]
        print(f"{sym:8s} {b['ef']:>2d}/{b['es']:<2d} {b['tp_r']:.1f}| "
              f"{b['n_is']:4d} {b['is']['expR']:+.4f} {b['is']['t']:+.2f} | "
              f"{b['n_oos']:4d} {o_['expR']:+.4f} {o_['t']:+.2f} {o_['pf']:5.2f} "
              f"{o_['wr']:.2f} {o_['dd']:+.1f}")
        out["per_symbol"][sym] = {k: b[k] for k in ("ef", "es", "tp_r", "n_is", "n_oos", "is", "oos")}
    print("-"*92)
    ci = boot_ci(pooled_oos[pbest["key"]])
    po = pbest["oos"]
    print(f"POOLED param(IS-best)={pbest['key']}  OOS: n={po['n']} expR={po['expR']:+.4f} "
          f"t={po['t']:+.2f} pf={po['pf']:.2f} wr={po['wr']:.2f} dd={po['dd']:+.1f} "
          f"CI95=[{ci[0]:+.4f},{ci[1]:+.4f}]")
    out["pooled"] = dict(key=list(pbest["key"]), oos=po, ci95=ci)
    with open(os.path.join(LAB, "mtf_align_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    return out

if __name__ == "__main__":
    run()
