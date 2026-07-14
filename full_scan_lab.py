"""
full_scan_lab.py
================
Strict no-lookahead setup-battery scanner over index symbols.

Data source : data/lab_cache/<SYM>_<TF>.npz  (np.load -> t,o,h,l,c,v)
Cost source : data/lab_cache/<SYM>_meta.json  (trade_tick_value / trade_tick_size / point)

Rules
-----
* Signal at bar i uses ONLY data with index <= i (no lookahead).
* Act on NEXT bar: a signal confirmed at close of bar i opens a trade at open of bar i+1.
* Outcome resolved on subsequent bars using their H/L; if both SL and TP are
  inside the same bar's range we resolve CONSERVATIVELY (assume SL hit first).
* Cost is a realistic round-trip, expressed in PRICE units, subtracted from the
  raw price P&L of every trade before converting to R.
* Split 67/33 IS/OOS by time. Only OOS stats are reported.
* Bootstrap 2000x the avg-R distribution; CI excludes 0 => 95% pct interval
  (2.5..97.5) does not straddle zero.
* EDGE flag : n>=40 AND oos_pf>=1.2 AND ci_excludes_0.

Setups (each tested long & short)
---------------------------------
CONTINUATION   : EMA8>EMA21 (uptrend) AND pullback touches EMA8 -> long; mirror short.
                 SL 1.5*ATR, TP 2R.
MEAN_REVERSION : |close-EMA20| > 2*ATR -> fade (close below -> long, above -> short).
                 TP = EMA20 (at signal), SL 1.5*ATR.
BREAKOUT       : close beyond prior 20-bar high/low -> trade in breakout direction.
                 SL = other side of the 20-bar range, TP 2R.
VOL_EXPANSION  : bar range > 2.5*ATR -> trade in that bar's direction (continuation).
                 SL 1.5*ATR, TP 2R.
"""

import json
import os
import sys

import numpy as np

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

SYMBOLS = ["USOILm", "EURAUDm", "GBPAUDm", "AUDJPYm", "CADJPYm"]
TFS = ["M5", "M15", "H1"]

# Realistic round-trip cost in PRICE units, by symbol.
# Brief guidance: oil ~3-5pt, FX ~1-2pip.
#   USOIL  : point=0.001 -> 4 pt   = 4   * 0.001  = 0.004    (oil 3-5pt, mid 4)
#   EURAUD : point=1e-5  -> 1.5pip = 1.5 * 10*1e-5 = 0.00015 (FX 1-2pip)
#   GBPAUD : point=1e-5  -> 2.0pip = 2.0 * 10*1e-5 = 0.00020 (wider cross)
#   AUDJPY : point=0.001 -> 1.5pip = 1.5 * 10*0.001 = 0.015  (JPY: 1pip=100pt)
#   CADJPY : point=0.001 -> 1.5pip = 1.5 * 10*0.001 = 0.015
# NOTE: COST_PTS is the round-trip cost expressed in PRICE units (subtracted
# directly from price P&L). 'point' from meta is used only for the pt readout.
COST_PTS = {
    "USOILm": 0.004,
    "EURAUDm": 0.00015,
    "GBPAUDm": 0.00020,
    "AUDJPYm": 0.015,
    "CADJPYm": 0.015,
}

EMA_FAST, EMA_SLOW, EMA_MR = 8, 21, 20
ATR_LEN = 14
BREAK_LOOKBACK = 20
SL_ATR = 1.5
TP_R = 2.0
MR_DIST_ATR = 2.0
VOL_EXP_ATR = 2.5
MAX_HOLD = 200          # bars to wait for SL/TP before abandoning (no lookahead window cap)
IS_FRAC = 0.67
N_BOOT = 2000
MIN_N = 40
PF_THRESH = 1.2
SEED = 12345


def ema(x, length):
    a = 2.0 / (length + 1.0)
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(h, l, c, length):
    n = len(c)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.empty(n, dtype=np.float64)
    out[0] = tr[0]
    a = 1.0 / length
    for i in range(1, n):
        out[i] = a * tr[i] + (1 - a) * out[i - 1]   # Wilder-style smoothing
    return out


def rolling_max(x, w):
    """rolling_max[i] = max(x[i-w .. i-1])  (PRIOR window, excludes i). NaN until valid."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w, n):
        out[i] = np.max(x[i - w:i])
    return out


def rolling_min(x, w):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w, n):
        out[i] = np.min(x[i - w:i])
    return out


def resolve_trade(h, l, c, entry_idx, direction, entry, sl, tp):
    """
    Resolve a trade opened at OPEN of entry_idx (entry price already given).
    Returns (exit_price, exit_idx) or (None, None) if never resolved within MAX_HOLD.
    Conservative: if both SL and TP fall inside the same bar, assume SL first.
    """
    n = len(c)
    end = min(n, entry_idx + MAX_HOLD)
    for j in range(entry_idx, end):
        hi, lo = h[j], l[j]
        if direction == 1:  # long
            hit_sl = lo <= sl
            hit_tp = hi >= tp
            if hit_sl and hit_tp:
                return sl, j          # conservative
            if hit_sl:
                return sl, j
            if hit_tp:
                return tp, j
        else:  # short
            hit_sl = hi >= sl
            hit_tp = lo <= tp
            if hit_sl and hit_tp:
                return sl, j
            if hit_sl:
                return sl, j
            if hit_tp:
                return tp, j
    # not resolved -> close at last available close (mark-to-market)
    return c[end - 1], end - 1


def gen_signals(o, h, l, c, ema_f, ema_s, ema_mr, atr_v, hh, ll):
    """
    Returns list of (signal_bar_i, setup, direction, sl_price_basis, tp_price_basis_kind, extra)
    All computed using only data<=i. Trade is entered at open of i+1.
    We emit (i, setup, dir, sl_dist_or_level, tp_kind, tp_val).
    tp_kind: 'R' (2R from entry) or 'LEVEL' (absolute price, for mean reversion).
    sl spec: ('DIST', atr*1.5) or ('LEVEL', price)
    """
    sigs = []
    n = len(c)
    start = max(EMA_SLOW, ATR_LEN, BREAK_LOOKBACK) + 1
    for i in range(start, n - 1):  # need i+1 to exist
        a = atr_v[i]
        if not np.isfinite(a) or a <= 0:
            continue
        ci = c[i]

        # CONTINUATION: trend + pullback to EMA8 (low dips to/below EMA8 in uptrend)
        if ema_f[i] > ema_s[i] and l[i] <= ema_f[i] and ci > ema_f[i]:
            sigs.append((i, "CONTINUATION", 1, ("DIST", SL_ATR * a), "R", None))
        if ema_f[i] < ema_s[i] and h[i] >= ema_f[i] and ci < ema_f[i]:
            sigs.append((i, "CONTINUATION", -1, ("DIST", SL_ATR * a), "R", None))

        # MEAN_REVERSION: |close-EMA20| > 2*ATR, fade back to EMA20
        dev = ci - ema_mr[i]
        if dev < -MR_DIST_ATR * a:
            sigs.append((i, "MEAN_REVERSION", 1, ("DIST", SL_ATR * a), "LEVEL", ema_mr[i]))
        if dev > MR_DIST_ATR * a:
            sigs.append((i, "MEAN_REVERSION", -1, ("DIST", SL_ATR * a), "LEVEL", ema_mr[i]))

        # BREAKOUT: close beyond prior 20-bar high/low; SL = other side of range
        if np.isfinite(hh[i]) and ci > hh[i]:
            sigs.append((i, "BREAKOUT", 1, ("LEVEL", ll[i]), "R", None))
        if np.isfinite(ll[i]) and ci < ll[i]:
            sigs.append((i, "BREAKOUT", -1, ("LEVEL", hh[i]), "R", None))

        # VOL_EXPANSION: bar range > 2.5*ATR, trade in bar direction
        rng = h[i] - l[i]
        if rng > VOL_EXP_ATR * a:
            if ci >= o[i]:
                sigs.append((i, "VOL_EXPANSION", 1, ("DIST", SL_ATR * a), "R", None))
            else:
                sigs.append((i, "VOL_EXPANSION", -1, ("DIST", SL_ATR * a), "R", None))
    return sigs


def run_trade(o, h, l, c, sig, cost_pts):
    i, setup, direction, sl_spec, tp_kind, tp_val = sig
    entry_idx = i + 1
    entry = o[entry_idx]

    # Stop loss price
    if sl_spec[0] == "DIST":
        dist = sl_spec[1]
        sl = entry - dist if direction == 1 else entry + dist
    else:  # LEVEL
        sl = sl_spec[1]
        dist = abs(entry - sl)
    if dist <= 0:
        return None

    # Take profit price
    if tp_kind == "R":
        tp = entry + TP_R * dist if direction == 1 else entry - TP_R * dist
    else:  # LEVEL (mean reversion target = EMA20)
        tp = tp_val
        # target must be on the profitable side; else skip
        if direction == 1 and tp <= entry:
            return None
        if direction == -1 and tp >= entry:
            return None

    exit_price, exit_idx = resolve_trade(h, l, c, entry_idx, direction, entry, sl, tp)
    if exit_price is None:
        return None

    raw = (exit_price - entry) if direction == 1 else (entry - exit_price)
    net = raw - cost_pts                      # round-trip cost in price units
    r = net / dist                            # R-multiple (risk = SL distance)
    return r, entry_idx, exit_idx


def bootstrap_ci(rs, n_boot, seed):
    rs = np.asarray(rs, dtype=np.float64)
    if len(rs) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n = len(rs)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        means[b] = rs[idx].mean()
    lo = np.percentile(means, 2.5)
    hi = np.percentile(means, 97.5)
    return float(lo), float(hi)


def profit_factor(rs):
    rs = np.asarray(rs, dtype=np.float64)
    gains = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def load_meta(sym):
    with open(os.path.join(LAB, f"{sym}_meta.json")) as f:
        m = json.load(f)
    return m


def scan_cell(sym, tf, cost_pts):
    path = os.path.join(LAB, f"{sym}_{tf}.npz")
    d = np.load(path)
    o, h, l, c = (d["o"].astype(np.float64), d["h"].astype(np.float64),
                  d["l"].astype(np.float64), d["c"].astype(np.float64))
    n = len(c)

    ema_f = ema(c, EMA_FAST)
    ema_s = ema(c, EMA_SLOW)
    ema_mr = ema(c, EMA_MR)
    atr_v = atr(h, l, c, ATR_LEN)
    hh = rolling_max(h, BREAK_LOOKBACK)
    ll = rolling_min(l, BREAK_LOOKBACK)

    sigs = gen_signals(o, h, l, c, ema_f, ema_s, ema_mr, atr_v, hh, ll)

    split_idx = int(n * IS_FRAC)   # bars before this are IS; trades entered at/after are OOS

    # bucket: (setup, dir) -> list of OOS R
    buckets = {}
    for sig in sigs:
        res = run_trade(o, h, l, c, sig, cost_pts)
        if res is None:
            continue
        r, entry_idx, exit_idx = res
        if entry_idx < split_idx:
            continue  # IS, skip for OOS reporting
        key = (sig[1], sig[2])
        buckets.setdefault(key, []).append(r)

    out = []
    for (setup, direction), rs in sorted(buckets.items()):
        rs = np.asarray(rs, dtype=np.float64)
        nn = len(rs)
        pf = profit_factor(rs)
        expr = float(rs.mean()) if nn else 0.0
        lo, hi = bootstrap_ci(rs, N_BOOT, SEED)
        ci_excl = bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))
        is_edge = bool(nn >= MIN_N and pf >= PF_THRESH and ci_excl)
        out.append({
            "symbol": sym,
            "tf": tf,
            "setup": f"{setup}_{'LONG' if direction == 1 else 'SHORT'}",
            "n": int(nn),
            "oos_pf": round(pf, 4) if np.isfinite(pf) else None,
            "oos_expR": round(expr, 5),
            "ci_lo": round(lo, 5) if np.isfinite(lo) else None,
            "ci_hi": round(hi, 5) if np.isfinite(hi) else None,
            "ci_excludes_0": ci_excl,
            "is_edge": is_edge,
        })
    return out


def main():
    np.seterr(all="ignore")
    all_rows = []
    cells = 0
    print(f"{'SYM':7s} {'TF':4s} {'SETUP':22s} {'n':>5s} {'OOS_PF':>8s} "
          f"{'expR':>8s} {'CI_lo':>8s} {'CI_hi':>8s} {'EDGE':>5s}")
    print("-" * 80)
    meta_ctx = {}
    for sym in SYMBOLS:
        cost = COST_PTS[sym]
        m = load_meta(sym)
        point = float(m.get("point", m.get("tick_size", 1.0)))
        tv = float(m.get("trade_tick_value", 1.0))
        ts = float(m.get("trade_tick_size", point))
        # round-trip cost in points and (per min-lot 0.01) USD, for context only
        cost_in_pts = cost / point
        cost_usd_001 = (cost / ts) * tv * 0.01
        meta_ctx[sym] = {"point": point, "trade_tick_value": tv,
                         "trade_tick_size": ts, "cost_price": cost,
                         "cost_points": round(cost_in_pts, 2),
                         "cost_usd_per_0.01lot": round(cost_usd_001, 4)}
        print(f"# COST {sym:8s} = {cost:.6f} price  "
              f"({cost_in_pts:.1f} pt, ~${cost_usd_001:.4f}/0.01lot, "
              f"tick_value={tv})")
        for tf in TFS:
            cells += 1
            rows = scan_cell(sym, tf, cost)
            for r in rows:
                all_rows.append(r)
                pf = r["oos_pf"]
                pf_s = f"{pf:8.3f}" if pf is not None else "     inf"
                edge = "EDGE" if r["is_edge"] else ""
                print(f"{r['symbol']:7s} {r['tf']:4s} {r['setup']:22s} "
                      f"{r['n']:5d} {pf_s} {r['oos_expR']:8.4f} "
                      f"{(r['ci_lo'] if r['ci_lo'] is not None else float('nan')):8.4f} "
                      f"{(r['ci_hi'] if r['ci_hi'] is not None else float('nan')):8.4f} "
                      f"{edge:>5s}")

    edges = [r for r in all_rows if r["is_edge"]]
    print("-" * 80)
    print(f"Cells scanned (symbol x TF): {cells}")
    print(f"Setup-direction results rows: {len(all_rows)}")
    print(f"EDGES found: {len(edges)}")
    for e in edges:
        print(f"  EDGE: {e['symbol']} {e['tf']} {e['setup']} "
              f"n={e['n']} PF={e['oos_pf']} expR={e['oos_expR']} "
              f"CI=[{e['ci_lo']},{e['ci_hi']}]")

    result = {
        "meta_cost_context": meta_ctx,
        "config": {
            "symbols": SYMBOLS, "tfs": TFS, "cost_pts": COST_PTS,
            "is_frac": IS_FRAC, "n_boot": N_BOOT,
            "edge_rule": {"min_n": MIN_N, "min_pf": PF_THRESH, "ci_excludes_0": True},
            "ema_fast": EMA_FAST, "ema_slow": EMA_SLOW, "atr_len": ATR_LEN,
            "sl_atr": SL_ATR, "tp_r": TP_R, "break_lookback": BREAK_LOOKBACK,
            "max_hold_bars": MAX_HOLD, "no_lookahead": True,
            "conservative_intrabar": "SL_assumed_first",
        },
        "cells_tested": cells,
        "rows": all_rows,
        "edges": edges,
    }
    out_path = os.path.join(LAB, "full_scan_results.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved -> {out_path}")
    return result


if __name__ == "__main__":
    main()
