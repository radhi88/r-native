"""
cs_engulf_wf_lab.py
===================
Strict walk-forward test of ONE candlestick rule (trend-aligned ENGULFING
continuation) across a symbol x TF panel. Offline only (npz), no MT5.

Rule (long; short is mirror):
  Trend filter : EMA_fast > EMA_slow  (uptrend)
  Pattern      : bar i bullish engulfing of bar i-1
                 c[i]>o[i], c[i-1]<o[i-1], o[i]<=c[i-1], c[i]>=o[i-1]
  Pullback opt : min(l[i-1],l[i]) <= EMA_fast[i]   (dip into fast EMA)
  Entry        : open of bar i+1
  SL           : structure = min(l[i],l[i-1]) [long] ; or 1.5*ATR
  TP           : TP_R * risk
Cost           : round-trip in PRICE units, subtracted from raw P&L before R.

Method: 67/33 time split per cell. Choose (TP_R, SL_basis, pullback) on POOLED
IN-SAMPLE by mean-R (with n_IS>=MIN_IS). Lock it. Report POOLED OOS only.
Judge: expectancy(meanR net cost) + t-stat + max drawdown in R.  win_rate context only.
"""
import json, os, itertools
import numpy as np

LAB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lab_cache")

# Panel: liquid symbols with well-established round-trip cost (PRICE units)
COST = {
    "XAUUSDm": 0.30,
    "EURUSDm": 0.00015,   # 1.5 pip
    "GBPUSDm": 0.00020,   # 2.0 pip
    "USDJPYm": 0.015,     # 1.5 pip (JPY)
    "GBPJPYm": 0.020,     # ~2.0 pip (JPY cross, wider)
    "USOILm":  0.004,
    "AUDJPYm": 0.015,
    "CADJPYm": 0.015,
}
SYMBOLS = list(COST.keys())
TFS = ["M5", "M15", "H1"]

EMA_FAST, EMA_SLOW = 8, 21
ATR_LEN = 14
MAX_HOLD = 200
IS_FRAC = 0.67
MIN_IS = 30
SEED = 12345

# Grid chosen on IS
GRID_TP   = [1.0, 1.5, 2.0, 3.0]
GRID_SL   = ["STRUCT", "ATR"]        # structure low/high  or 1.5*ATR
GRID_PULL = [True, False]


def ema(x, length):
    a = 2.0 / (length + 1.0)
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(h, l, c, length):
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.empty(n)
    out[0] = tr[0]
    a = 1.0/length
    for i in range(1, n):
        out[i] = a*tr[i] + (1-a)*out[i-1]
    return out


def resolve_trade(h, l, c, entry_idx, direction, sl, tp):
    n = len(c)
    end = min(n, entry_idx + MAX_HOLD)
    for j in range(entry_idx, end):
        hi, lo = h[j], l[j]
        if direction == 1:
            if lo <= sl:   # conservative: SL first when both
                return sl, j
            if hi >= tp:
                return tp, j
        else:
            if hi >= sl:
                return sl, j
            if lo <= tp:
                return tp, j
    return c[end-1], end-1


def gen_signals(o, h, l, c, ef, es):
    """Return list of (i, direction). Engulfing + trend filter (both variants of
    pullback are decided later; we emit the raw pattern + pullback flag)."""
    sigs = []
    n = len(c)
    start = EMA_SLOW + 2
    for i in range(start, n-1):
        # bullish engulfing, uptrend
        if (ef[i] > es[i] and c[i] > o[i] and c[i-1] < o[i-1]
                and o[i] <= c[i-1] and c[i] >= o[i-1]):
            pull = (min(l[i], l[i-1]) <= ef[i])
            sigs.append((i, 1, pull))
        # bearish engulfing, downtrend
        if (ef[i] < es[i] and c[i] < o[i] and c[i-1] > o[i-1]
                and o[i] >= c[i-1] and c[i] <= o[i-1]):
            pull = (max(h[i], h[i-1]) >= ef[i])
            sigs.append((i, -1, pull))
    return sigs


def run_trade(o, h, l, c, atr_v, i, direction, sl_basis, tp_r, cost):
    entry_idx = i + 1
    entry = o[entry_idx]
    if sl_basis == "STRUCT":
        if direction == 1:
            sl = min(l[i], l[i-1])
        else:
            sl = max(h[i], h[i-1])
    else:  # ATR
        sl = entry - 1.5*atr_v[i] if direction == 1 else entry + 1.5*atr_v[i]
    dist = abs(entry - sl)
    if dist <= 0:
        return None
    tp = entry + tp_r*dist if direction == 1 else entry - tp_r*dist
    ex, exidx = resolve_trade(h, l, c, entry_idx, direction, sl, tp)
    raw = (ex - entry) if direction == 1 else (entry - ex)
    r = (raw - cost) / dist
    t_entry = entry_idx
    return r, t_entry


def load_cell(sym, tf):
    p = os.path.join(LAB, f"{sym}_{tf}.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p)
    o, h, l, c, t = (d["o"].astype(float), d["h"].astype(float),
                     d["l"].astype(float), d["c"].astype(float), d["t"])
    ef = ema(c, EMA_FAST); es = ema(c, EMA_SLOW); av = atr(h, l, c, ATR_LEN)
    sigs = gen_signals(o, h, l, c, ef, es)
    split = int(len(c)*IS_FRAC)
    return dict(o=o, h=h, l=l, c=c, t=t, av=av, sigs=sigs, split=split, cost=COST[sym])


def collect(cells, tp_r, sl_basis, pullback, oos):
    """Return list of (global_time, R) for IS or OOS across all cells."""
    out = []
    for cell in cells:
        o, h, l, c, av = cell["o"], cell["h"], cell["l"], cell["c"], cell["av"]
        t = cell["t"]; split = cell["split"]; cost = cell["cost"]
        for (i, direction, pull) in cell["sigs"]:
            if pullback and not pull:
                continue
            res = run_trade(o, h, l, c, av, i, direction, sl_basis, tp_r, cost)
            if res is None:
                continue
            r, entry_idx = res
            is_oos = entry_idx >= split
            if is_oos != oos:
                continue
            out.append((int(t[entry_idx]), r))
    return out


def stats(rs):
    rs = np.asarray([r for _, r in rs], dtype=float)
    n = len(rs)
    if n == 0:
        return dict(n=0, mean=0, t=0, pf=0, wr=0, maxdd=0)
    mean = rs.mean()
    sd = rs.std(ddof=1) if n > 1 else 0
    tval = mean/(sd+1e-9)*np.sqrt(n)
    gains = rs[rs > 0].sum(); losses = -rs[rs < 0].sum()
    pf = gains/losses if losses > 0 else float("inf")
    wr = float((rs > 0).mean())
    return dict(n=n, mean=float(mean), t=float(tval), pf=float(pf), wr=wr)


def max_dd_R(rs_sorted):
    """rs_sorted: list of (time, R) sorted by time -> peak-to-trough DD in R."""
    rs = [r for _, r in sorted(rs_sorted, key=lambda x: x[0])]
    eq = 0.0; peak = 0.0; mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return float(mdd)


def main():
    np.seterr(all="ignore")
    cells = [c for c in (load_cell(s, tf) for s in SYMBOLS for tf in TFS) if c]
    tot_sigs = sum(len(c["sigs"]) for c in cells)
    print(f"cells={len(cells)}  raw engulfing signals={tot_sigs}")

    # --- choose params on POOLED IN-SAMPLE by mean-R (need MIN_IS trades) ---
    best = None
    print("\nIN-SAMPLE grid (pooled):")
    print(f"{'TP_R':>5} {'SL':>7} {'pull':>5} {'n_IS':>6} {'meanR':>9} {'t':>7} {'PF':>7}")
    for tp_r, sl_b, pull in itertools.product(GRID_TP, GRID_SL, GRID_PULL):
        isr = collect(cells, tp_r, sl_b, pull, oos=False)
        st = stats(isr)
        flag = ""
        if st["n"] >= MIN_IS:
            if best is None or st["mean"] > best[1]["mean"]:
                best = ((tp_r, sl_b, pull), st)
                flag = " <-"
        print(f"{tp_r:5.1f} {sl_b:>7} {str(pull):>5} {st['n']:6d} "
              f"{st['mean']:9.4f} {st['t']:7.2f} {st['pf']:7.2f}{flag}")

    (tp_r, sl_b, pull), is_st = best
    print(f"\nCHOSEN on IS: TP_R={tp_r} SL={sl_b} pullback={pull} "
          f"(IS meanR={is_st['mean']:.4f} n={is_st['n']})")

    # --- lock, evaluate POOLED OOS ---
    oosr = collect(cells, tp_r, sl_b, pull, oos=True)
    st = stats(oosr)
    mdd = max_dd_R(oosr)
    print("\n=== LOCKED OOS RESULT (pooled) ===")
    print(f"n_oos    = {st['n']}")
    print(f"exp R    = {st['mean']:.4f}  (net of cost)")
    print(f"t-stat   = {st['t']:.3f}")
    print(f"PF       = {st['pf']:.3f}")
    print(f"win_rate = {st['wr']:.3f}  (context only)")
    print(f"max_dd_R = {mdd:.2f}")

    # per-cell OOS breakdown for honesty
    print("\nOOS per symbol/TF (chosen params):")
    print(f"{'SYM':8} {'TF':4} {'n':>5} {'meanR':>9} {'t':>7}")
    labels = [(s, tf) for s in SYMBOLS for tf in TFS
              if os.path.exists(os.path.join(LAB, f"{s}_{tf}.npz"))]
    for cell, (s, tf) in zip(cells, labels):
        sub = collect([cell], tp_r, sl_b, pull, oos=True)
        cst = stats(sub)
        print(f"{s:8} {tf:4} {cst['n']:5d} {cst['mean']:9.4f} {cst['t']:7.2f}")

    result = dict(chosen=dict(tp_r=tp_r, sl_basis=sl_b, pullback=pull),
                  is_stats=is_st, oos_stats=st, max_dd_R=mdd,
                  cost=COST, symbols=SYMBOLS, tfs=TFS)
    outp = os.path.join(LAB, "cs_engulf_wf_results.json")
    with open(outp, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nsaved -> {outp}")
    return result


if __name__ == "__main__":
    main()
