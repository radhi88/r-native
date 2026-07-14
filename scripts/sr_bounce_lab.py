"""
sr_bounce_lab.py  -- OFFLINE strict walk-forward test of ONE rule family:

FAMILY: Support/resistance (PDH/PDL) bounce with rejection-candle confirmation.

RULE (long at PDL support; mirror short at PDH resistance):
  * PDH/PDL = high/low of the PRIOR completed calendar day (UTC), computed from
    bars whose day-index < current bar's day-index  (STRICT, no lookahead).
  * At bar i, price must approach the level from the correct side and print a
    rejection candle:
      LONG (support = PDL):  l[i] dips within tol_atr*ATR of PDL from ABOVE
        (close still above PDL), candle is a bullish rejection:
          close-position in range >= body_frac AND lower wick >= wick_frac of range.
      SHORT (resistance = PDH): mirror.
  * Entry at OPEN of i+1 (act on next bar).
  * SL = rejection low - buf*ATR (long) / rejection high + buf*ATR (short).
  * TP = entry +/- TP_R * risk_distance.
  * Cost (round-trip, price units) subtracted from raw P&L before R.
  * Intrabar conservative: SL assumed hit before TP in the same bar.

WALK-FORWARD:
  * 67/33 time split. Param grid chosen ONLY on IS (by IS mean-R, IS n>=MIN_IS).
  * Chosen params evaluated ONCE on OOS. Only OOS reported.
  * Judge: OOS expectancy(mean R net cost) + t-stat + max drawdown (in R).
    survives = expR>0 AND n_oos>=30 AND t>=3 AND cost included AND dd not catastrophic.
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from full_scan_lab import atr, resolve_trade, profit_factor, bootstrap_ci, MAX_HOLD  # reuse strict mechanics

LAB = os.path.join(ROOT, "data", "lab_cache")

# round-trip cost in PRICE units, per symbol
COST_PTS = {
    "XAUUSDm": 0.30, "XAGUSDm": 0.04, "US30m": 3.0, "BTCUSDm": 20.0,
    "EURUSDm": 0.00015, "GBPUSDm": 0.00020, "USDJPYm": 0.015, "EURJPYm": 0.015,
}
ATR_LEN = 14
IS_FRAC = 0.67
MIN_IS = 25          # min IS trades for a param combo to be eligible
N_BOOT = 2000
SEED = 12345

# param grid (chosen on IS only)
GRID_TOL   = [0.25, 0.5, 1.0]     # proximity band in ATR
GRID_BODY  = [0.5, 0.66]          # close-position-in-range threshold
GRID_WICK  = [0.25, 0.4]          # rejection wick as frac of range
GRID_TPR   = [1.0, 1.5, 2.0]      # reward multiple
BUF_ATR    = 0.15                 # SL buffer beyond wick


def prior_day_levels(t, h, l):
    """PDH/PDL arrays: for each bar, the high/low of the most recent STRICTLY
    earlier calendar day. NaN until a full prior day exists."""
    day = (t.astype(np.int64) // 86400)
    n = len(t)
    pdh = np.full(n, np.nan)
    pdl = np.full(n, np.nan)
    # aggregate per day
    cur = day[0]
    cur_hi, cur_lo = h[0], l[0]
    last_day = None
    last_hi = last_lo = np.nan
    for i in range(n):
        if day[i] != cur:
            # day rolled over -> the day we just finished becomes "last completed"
            last_day, last_hi, last_lo = cur, cur_hi, cur_lo
            cur = day[i]
            cur_hi, cur_lo = h[i], l[i]
        else:
            if h[i] > cur_hi: cur_hi = h[i]
            if l[i] < cur_lo: cur_lo = l[i]
        if last_day is not None:
            pdh[i] = last_hi
            pdl[i] = last_lo
    return pdh, pdl


def gen_and_run(o, h, l, c, atr_v, pdh, pdl, cost, tol, body, wick, tp_r, split_idx):
    n = len(c)
    is_R, oos_R = [], []
    for i in range(ATR_LEN + 2, n - 1):
        a = atr_v[i]
        if not np.isfinite(a) or a <= 0:
            continue
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        band = tol * a
        # --- LONG at PDL support ---
        PL = pdl[i]
        if np.isfinite(PL):
            close_pos = (c[i] - l[i]) / rng                       # 1=close at high
            lower_wick = (min(o[i], c[i]) - l[i]) / rng
            approached = (l[i] <= PL + band) and (c[i] > PL) and (l[i] >= PL - 3 * band)
            if approached and close_pos >= body and lower_wick >= wick:
                entry = o[i + 1]
                sl = l[i] - BUF_ATR * a
                dist = entry - sl
                if dist > 0:
                    tp = entry + tp_r * dist
                    ep, ei = resolve_trade(h, l, c, i + 1, 1, entry, sl, tp)
                    if ep is not None:
                        r = ((ep - entry) - cost) / dist
                        (oos_R if (i + 1) >= split_idx else is_R).append(r)
        # --- SHORT at PDH resistance ---
        PH = pdh[i]
        if np.isfinite(PH):
            close_pos = (h[i] - c[i]) / rng                       # 1=close at low
            upper_wick = (h[i] - max(o[i], c[i])) / rng
            approached = (h[i] >= PH - band) and (c[i] < PH) and (h[i] <= PH + 3 * band)
            if approached and close_pos >= body and upper_wick >= wick:
                entry = o[i + 1]
                sl = h[i] + BUF_ATR * a
                dist = sl - entry
                if dist > 0:
                    tp = entry - tp_r * dist
                    ep, ei = resolve_trade(h, l, c, i + 1, -1, entry, sl, tp)
                    if ep is not None:
                        r = ((entry - ep) - cost) / dist
                        (oos_R if (i + 1) >= split_idx else is_R).append(r)
    return is_R, oos_R


def max_dd_R(rs):
    eq = np.cumsum(rs)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(rs) else 0.0


def tstat(rs):
    rs = np.asarray(rs, float)
    if len(rs) < 2:
        return 0.0
    return float(rs.mean() / (rs.std(ddof=1) + 1e-9) * np.sqrt(len(rs)))


def run_cell(sym, tf):
    d = np.load(os.path.join(LAB, f"{sym}_{tf}.npz"))
    t = d["t"]; o, h, l, c = (d["o"].astype(float), d["h"].astype(float),
                              d["l"].astype(float), d["c"].astype(float))
    n = len(c)
    atr_v = atr(h, l, c, ATR_LEN)
    pdh, pdl = prior_day_levels(t, h, l)
    cost = COST_PTS[sym]
    split_idx = int(n * IS_FRAC)

    # ---- IS param selection ----
    best = None
    for tol in GRID_TOL:
        for body in GRID_BODY:
            for wick in GRID_WICK:
                for tp_r in GRID_TPR:
                    is_R, _ = gen_and_run(o, h, l, c, atr_v, pdh, pdl, cost,
                                          tol, body, wick, tp_r, split_idx)
                    if len(is_R) < MIN_IS:
                        continue
                    m = float(np.mean(is_R))
                    if best is None or m > best[0]:
                        best = (m, tol, body, wick, tp_r, len(is_R))
    if best is None:
        return {"symbol": sym, "tf": tf, "eligible": False,
                "reason": f"no IS combo reached MIN_IS={MIN_IS}"}

    _, tol, body, wick, tp_r, is_n = best
    # ---- OOS evaluation of the single chosen combo ----
    _, oos_R = gen_and_run(o, h, l, c, atr_v, pdh, pdl, cost, tol, body, wick, tp_r, split_idx)
    rs = np.asarray(oos_R, float)
    nn = len(rs)
    if nn == 0:
        return {"symbol": sym, "tf": tf, "eligible": True, "n_oos": 0,
                "params": {"tol": tol, "body": body, "wick": wick, "tp_r": tp_r}}
    expR = float(rs.mean())
    t_ = tstat(rs)
    pf = profit_factor(rs)
    lo, hi = bootstrap_ci(rs, N_BOOT, SEED)
    ci_excl = bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))
    wr = float((rs > 0).mean())
    dd = max_dd_R(rs)
    survives = bool(expR > 0 and nn >= 30 and t_ >= 3 and ci_excl and dd > -8.0)
    return {"symbol": sym, "tf": tf, "eligible": True,
            "params": {"tol": tol, "body": body, "wick": wick, "tp_r": tp_r},
            "is_n": is_n, "n_oos": nn, "oos_expR": round(expR, 5),
            "t": round(t_, 3), "pf": round(pf, 3), "win_rate": round(wr, 4),
            "ci": [round(lo, 5), round(hi, 5)], "ci_excludes_0": ci_excl,
            "max_dd_R": round(dd, 3), "cost_price": cost, "survives": survives}


def main():
    np.seterr(all="ignore")
    cells = []
    for sym in ["XAUUSDm", "XAGUSDm", "US30m", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "EURJPYm"]:
        for tf in ["M5", "M15"]:
            p = os.path.join(LAB, f"{sym}_{tf}.npz")
            if not os.path.exists(p):
                continue
            try:
                cells.append(run_cell(sym, tf))
            except Exception as e:
                cells.append({"symbol": sym, "tf": tf, "error": str(e)})
    print(f"{'SYM':9s}{'TF':4s}{'n_oos':>6s}{'expR':>9s}{'t':>7s}{'PF':>7s}{'WR':>7s}{'ddR':>8s}  survives  params")
    print("-" * 100)
    for r in cells:
        if r.get("error"):
            print(f"{r['symbol']:9s}{r['tf']:4s}  ERROR {r['error']}"); continue
        if not r.get("eligible", True) or r.get("n_oos", 0) == 0:
            print(f"{r['symbol']:9s}{r['tf']:4s}  (skipped: {r.get('reason','no OOS trades')})"); continue
        p = r["params"]
        print(f"{r['symbol']:9s}{r['tf']:4s}{r['n_oos']:6d}{r['oos_expR']:9.4f}{r['t']:7.2f}"
              f"{r['pf']:7.2f}{r['win_rate']:7.3f}{r['max_dd_R']:8.2f}  {str(r['survives']):8s}  "
              f"tol={p['tol']} body={p['body']} wick={p['wick']} tpR={p['tp_r']}")
    out = os.path.join(LAB, "sr_bounce_lab_results.json")
    with open(out, "w") as f:
        json.dump(cells, f, indent=2)
    print("\nSaved ->", out)
    survivors = [c for c in cells if c.get("survives")]
    print("SURVIVORS:", len(survivors))
    return cells


if __name__ == "__main__":
    main()
