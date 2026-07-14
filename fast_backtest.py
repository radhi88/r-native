#!/usr/bin/env python3
"""
fast_backtest.py - numba-JIT acceleration of the scanner/backtest inner loop.

WHY THIS FILE EXISTS
--------------------
The MEASURED bottleneck in this project is the scanner/backtest (CPU-bound; a full
universe scan took ~23 min for 507 cells). Live trading is NOT a bottleneck
(chart_read = 5.3 ms). So the only place a "fast language" helps is here: the
bar-by-bar inner loop of the backtest (breakout/entry/SL/TP/resolution).

WHAT IT DOES
------------
Re-implements the exact hot loop of data/lab_cache/full_scan_lab.py
(gen_signals + simulate) twice:

  1. PURE  - the original pure-Python loops (reference / ground truth).
  2. NUMBA - the same logic wrapped in @njit (JIT compiled inside Python,
             no external toolchain).

It then, on REAL cached bars (data/lab_cache/<SYM>_<TF>.npz):
  * runs BOTH versions on identical inputs,
  * verifies the results are LITERALLY identical (trade count, every per-trade R,
    profit factor) -- speed without correctness is worthless,
  * times both (numba timed AFTER a warm-up call so JIT-compile time is excluded,
    which is the honest number for a long scan that reuses the compiled function
    across hundreds of cells), and
  * reports the speedup.

HONESTY NOTES
-------------
* The indicators (ema/atr/rolling max-min) are computed once per (sym,tf) and are
  identical in both paths -- they are NOT the hot loop, so they are left in plain
  numpy/python. The accelerated part is the per-setup/per-side signal+simulate loop,
  which is what runs SETUPS*SIDES (=8) times per cell and dominates the scan.
* First-ever numba call pays a one-time compile cost (~1-3 s). Over a 507-cell scan
  that is amortized to nothing; over a single cell it would dominate. Both numbers
  are printed so the reader can judge.
* Floating point: the numba port performs the SAME operations in the SAME order as
  the pure version, so results match bit-for-bit on the tested data. Verified by
  exact array equality, not tolerance.
"""
import json
import os
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(HERE, "data", "lab_cache")

# ---- strategy constants (identical to full_scan_lab.py) --------------------
EMA_FAST = 8
EMA_SLOW = 21
EMA_MR = 20
ATR_N = 14
BREAK_N = 20
PULLBACK_TOL = 0.25
MR_SIGMA = 2.0
VOL_MULT = 2.5
SL_ATR = 1.5
RR = 2.0
MAX_HOLD = 200

# setup codes (so numba sees ints, not strings)
S_CONT, S_MR, S_BRK, S_VOL = 0, 1, 2, 3
SETUP_NAMES = {S_CONT: "CONTINUATION", S_MR: "MEAN_REVERSION",
               S_BRK: "BREAKOUT", S_VOL: "VOL_EXPANSION"}


# ============================================================================
# Shared indicators (NOT the hot loop -- computed once per cell, plain numpy)
# ============================================================================
def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x)
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


def rolling_max(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = np.max(x[i - n:i])
    return out


def rolling_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = np.min(x[i - n:i])
    return out


# ============================================================================
# PURE-PYTHON reference: signal generation + simulation (the hot loop).
# Mirrors full_scan_lab.gen_signals + simulate but fused for one (setup,side).
# Returns (entry_idx_array, net_R_array).
# ============================================================================
def _pure_one(setup, side, o, h, l, c, ema_f, ema_s, ema_m, a, hh, ll, cost_price):
    n = len(c)
    want = +1 if side == "long" else -1
    start = max(EMA_SLOW, ATR_N, BREAK_N) + 1
    ei_out = []
    r_out = []
    busy_until = -1
    for i in range(start, n - 1):
        ai = a[i]
        if not np.isfinite(ai) or ai <= 0:
            continue
        ci = c[i]
        d = 0
        sl_dist = 0.0
        tp_price = np.nan  # NaN means "use RR target"
        if setup == S_CONT:
            if ema_f[i] > ema_s[i] and abs(ci - ema_f[i]) <= PULLBACK_TOL * ai and ci >= ema_f[i]:
                d, sl_dist = +1, SL_ATR * ai
            elif ema_f[i] < ema_s[i] and abs(ci - ema_f[i]) <= PULLBACK_TOL * ai and ci <= ema_f[i]:
                d, sl_dist = -1, SL_ATR * ai
        elif setup == S_MR:
            dev = ci - ema_m[i]
            if dev > MR_SIGMA * ai:
                d, sl_dist, tp_price = -1, SL_ATR * ai, ema_m[i]
            elif dev < -MR_SIGMA * ai:
                d, sl_dist, tp_price = +1, SL_ATR * ai, ema_m[i]
        elif setup == S_BRK:
            if np.isfinite(hh[i]) and ci > hh[i]:
                d = +1
                sl_dist = ci - ll[i] if (np.isfinite(ll[i]) and ll[i] < ci) else SL_ATR * ai
            elif np.isfinite(ll[i]) and ci < ll[i]:
                d = -1
                sl_dist = hh[i] - ci if (np.isfinite(hh[i]) and hh[i] > ci) else SL_ATR * ai
        elif setup == S_VOL:
            if (h[i] - l[i]) > VOL_MULT * ai:
                d = +1 if ci >= o[i] else -1
                sl_dist = SL_ATR * ai

        if d == 0 or d != want:
            continue
        ei = i + 1
        if ei >= n or ei <= busy_until:
            continue
        if sl_dist <= 0 or not np.isfinite(sl_dist):
            continue
        entry = o[ei]
        if d > 0:
            sl = entry - sl_dist
            tp = entry + RR * sl_dist if not np.isfinite(tp_price) else tp_price
            if tp <= entry:
                continue
        else:
            sl = entry + sl_dist
            tp = entry - RR * sl_dist if not np.isfinite(tp_price) else tp_price
            if tp >= entry:
                continue
        R = sl_dist
        cost_R = cost_price / R
        outcome = np.nan
        exit_idx = ei
        end = min(ei + MAX_HOLD, n)
        got = False
        for j in range(ei, end):
            hi, lo = h[j], l[j]
            exit_idx = j
            if d > 0:
                if lo <= sl:
                    outcome = (sl - entry) / R; got = True; break
                if hi >= tp:
                    outcome = (tp - entry) / R; got = True; break
            else:
                if hi >= sl:
                    outcome = (entry - sl) / R; got = True; break
                if lo <= tp:
                    outcome = (entry - tp) / R; got = True; break
        if not got:
            j = end - 1
            exit_idx = j
            outcome = ((c[j] - entry) if d > 0 else (entry - c[j])) / R
        ei_out.append(ei)
        r_out.append(outcome - cost_R)
        busy_until = exit_idx
    return np.asarray(ei_out, dtype=np.int64), np.asarray(r_out, dtype=np.float64)


# ============================================================================
# NUMBA version: byte-for-byte same logic, JIT compiled. Preallocated outputs.
# ============================================================================
from numba import njit  # noqa: E402


@njit(cache=True, fastmath=False)
def _numba_one(setup, want, o, h, l, c, ema_f, ema_s, ema_m, a, hh, ll, cost_price):
    n = c.shape[0]
    start = EMA_SLOW
    if ATR_N > start:
        start = ATR_N
    if BREAK_N > start:
        start = BREAK_N
    start += 1

    ei_out = np.empty(n, dtype=np.int64)
    r_out = np.empty(n, dtype=np.float64)
    k = 0
    busy_until = -1
    for i in range(start, n - 1):
        ai = a[i]
        if not np.isfinite(ai) or ai <= 0.0:
            continue
        ci = c[i]
        d = 0
        sl_dist = 0.0
        tp_price = np.nan
        if setup == 0:  # CONT
            if ema_f[i] > ema_s[i] and abs(ci - ema_f[i]) <= PULLBACK_TOL * ai and ci >= ema_f[i]:
                d = 1; sl_dist = SL_ATR * ai
            elif ema_f[i] < ema_s[i] and abs(ci - ema_f[i]) <= PULLBACK_TOL * ai and ci <= ema_f[i]:
                d = -1; sl_dist = SL_ATR * ai
        elif setup == 1:  # MR
            dev = ci - ema_m[i]
            if dev > MR_SIGMA * ai:
                d = -1; sl_dist = SL_ATR * ai; tp_price = ema_m[i]
            elif dev < -MR_SIGMA * ai:
                d = 1; sl_dist = SL_ATR * ai; tp_price = ema_m[i]
        elif setup == 2:  # BREAKOUT
            if np.isfinite(hh[i]) and ci > hh[i]:
                d = 1
                if np.isfinite(ll[i]) and ll[i] < ci:
                    sl_dist = ci - ll[i]
                else:
                    sl_dist = SL_ATR * ai
            elif np.isfinite(ll[i]) and ci < ll[i]:
                d = -1
                if np.isfinite(hh[i]) and hh[i] > ci:
                    sl_dist = hh[i] - ci
                else:
                    sl_dist = SL_ATR * ai
        else:  # VOL_EXPANSION (setup == 3)
            if (h[i] - l[i]) > VOL_MULT * ai:
                if ci >= o[i]:
                    d = 1
                else:
                    d = -1
                sl_dist = SL_ATR * ai

        if d == 0 or d != want:
            continue
        ei = i + 1
        if ei >= n or ei <= busy_until:
            continue
        if sl_dist <= 0.0 or not np.isfinite(sl_dist):
            continue
        entry = o[ei]
        if d > 0:
            sl = entry - sl_dist
            if np.isfinite(tp_price):
                tp = tp_price
            else:
                tp = entry + RR * sl_dist
            if tp <= entry:
                continue
        else:
            sl = entry + sl_dist
            if np.isfinite(tp_price):
                tp = tp_price
            else:
                tp = entry - RR * sl_dist
            if tp >= entry:
                continue
        R = sl_dist
        cost_R = cost_price / R
        outcome = np.nan
        exit_idx = ei
        end = ei + MAX_HOLD
        if end > n:
            end = n
        got = False
        for j in range(ei, end):
            hi = h[j]
            lo = l[j]
            exit_idx = j
            if d > 0:
                if lo <= sl:
                    outcome = (sl - entry) / R; got = True; break
                if hi >= tp:
                    outcome = (tp - entry) / R; got = True; break
            else:
                if hi >= sl:
                    outcome = (entry - sl) / R; got = True; break
                if lo <= tp:
                    outcome = (entry - tp) / R; got = True; break
        if not got:
            j = end - 1
            exit_idx = j
            if d > 0:
                outcome = (c[j] - entry) / R
            else:
                outcome = (entry - c[j]) / R
        ei_out[k] = ei
        r_out[k] = outcome - cost_R
        k += 1
        busy_until = exit_idx
    return ei_out[:k].copy(), r_out[:k].copy()


def profit_factor(rs):
    rs = np.asarray(rs)
    if rs.size == 0:
        return 0.0
    gains = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


# ============================================================================
# Benchmark harness
# ============================================================================
def load_cell(sym, tf):
    npz = np.load(os.path.join(LAB, "%s_%s.npz" % (sym, tf)))
    o = npz["o"].astype(np.float64)
    h = npz["h"].astype(np.float64)
    l = npz["l"].astype(np.float64)
    c = npz["c"].astype(np.float64)
    return o, h, l, c


def precompute(o, h, l, c):
    return (ema(c, EMA_FAST), ema(c, EMA_SLOW), ema(c, EMA_MR),
            atr(h, l, c, ATR_N), rolling_max(h, BREAK_N), rolling_min(l, BREAK_N))


def run_pure(o, h, l, c, ind, cost_price):
    ef, es, em, a, hh, ll = ind
    res = {}
    for setup in (S_CONT, S_MR, S_BRK, S_VOL):
        for side in ("long", "short"):
            ei, r = _pure_one(setup, side, o, h, l, c, ef, es, em, a, hh, ll, cost_price)
            res[(setup, side)] = (ei, r)
    return res


def run_numba(o, h, l, c, ind, cost_price):
    ef, es, em, a, hh, ll = ind
    res = {}
    for setup in (S_CONT, S_MR, S_BRK, S_VOL):
        for side in ("long", "short"):
            want = 1 if side == "long" else -1
            ei, r = _numba_one(setup, want, o, h, l, c, ef, es, em, a, hh, ll, cost_price)
            res[(setup, side)] = (ei, r)
    return res


def verify_identical(pure_res, numba_res):
    """Literal equality check: same trade count, same entry idx, same per-trade R, same PF."""
    all_ok = True
    details = []
    for key in pure_res:
        ei_p, r_p = pure_res[key]
        ei_n, r_n = numba_res[key]
        same_n = (ei_p.shape[0] == ei_n.shape[0])
        same_ei = same_n and np.array_equal(ei_p, ei_n)
        # exact equality of R; NaN-safe (there should be no NaN in outputs)
        same_r = same_n and np.array_equal(r_p, r_n)
        pf_p, pf_n = profit_factor(r_p), profit_factor(r_n)
        same_pf = (pf_p == pf_n) or (not np.isfinite(pf_p) and not np.isfinite(pf_n))
        ok = same_n and same_ei and same_r and same_pf
        all_ok = all_ok and ok
        details.append({
            "setup": SETUP_NAMES[key[0]], "side": key[1],
            "n_pure": int(ei_p.shape[0]), "n_numba": int(ei_n.shape[0]),
            "pf_pure": (None if not np.isfinite(pf_p) else round(pf_p, 6)),
            "pf_numba": (None if not np.isfinite(pf_n) else round(pf_n, 6)),
            "identical": bool(ok),
        })
    return all_ok, details


def main():
    # Pick a representative heavy cell: gold-class symbol, H1, full 20k bars.
    sym, tf = "XAUEURm", "H1"
    cost_price = 0.30
    if not os.path.exists(os.path.join(LAB, "%s_%s.npz" % (sym, tf))):
        sym, tf, cost_price = "EURUSDm", "H1", 0.00010

    o, h, l, c = load_cell(sym, tf)
    nbars = len(c)
    ind = precompute(o, h, l, c)

    # ---- WARM-UP numba (compile once; excluded from the timed loop) --------
    t0 = time.perf_counter()
    _ = run_numba(o, h, l, c, ind, cost_price)
    compile_plus_first = (time.perf_counter() - t0) * 1000.0

    # ---- correctness: run both, compare literally -------------------------
    pure_res = run_pure(o, h, l, c, ind, cost_price)
    numba_res = run_numba(o, h, l, c, ind, cost_price)
    identical, details = verify_identical(pure_res, numba_res)

    # ---- timing: repeat to average out noise ------------------------------
    REPEAT = 5
    t0 = time.perf_counter()
    for _ in range(REPEAT):
        run_pure(o, h, l, c, ind, cost_price)
    pure_ms = (time.perf_counter() - t0) * 1000.0 / REPEAT

    t0 = time.perf_counter()
    for _ in range(REPEAT):
        run_numba(o, h, l, c, ind, cost_price)
    numba_ms = (time.perf_counter() - t0) * 1000.0 / REPEAT

    speedup = (pure_ms / numba_ms) if numba_ms > 0 else float("inf")

    total_trades = sum(int(v[0].shape[0]) for v in pure_res.values())

    print("=" * 72)
    print("fast_backtest.py  -- numba acceleration of the scanner inner loop")
    print("=" * 72)
    print("cell             : %s %s  (%d bars)" % (sym, tf, nbars))
    print("setups x sides   : 4 x 2 = 8 inner-loop passes per cell")
    print("total OOS+IS trades simulated (one cell): %d" % total_trades)
    print("-" * 72)
    print("RESULTS IDENTICAL: %s" % ("YES (literal: trade-count + per-trade R + PF)" if identical else "NO -- MISMATCH!"))
    for d in details:
        print("  %-15s %-5s  n_pure=%4d n_numba=%4d  pf_pure=%s pf_numba=%s  %s" % (
            d["setup"], d["side"], d["n_pure"], d["n_numba"],
            d["pf_pure"], d["pf_numba"], "OK" if d["identical"] else "<<< MISMATCH"))
    print("-" * 72)
    print("PURE  python (avg of %d): %9.3f ms / cell" % (REPEAT, pure_ms))
    print("NUMBA jit    (avg of %d): %9.3f ms / cell" % (REPEAT, numba_ms))
    print("SPEEDUP                 : %.2fx" % speedup)
    print("numba one-time compile (first call, amortized over a scan): %.0f ms" % compile_plus_first)
    print("-" * 72)
    # Extrapolate to a full universe scan (the measured 507-cell / ~23 min job).
    cells = 507
    pure_scan_s = pure_ms * cells / 1000.0
    numba_scan_s = numba_ms * cells / 1000.0
    print("Extrapolated %d-cell scan (inner-loop only):" % cells)
    print("  pure : %6.1f s   numba: %6.1f s   saved: %6.1f s" % (
        pure_scan_s, numba_scan_s, pure_scan_s - numba_scan_s))
    print("=" * 72)

    out = {
        "cell": "%s_%s" % (sym, tf),
        "bars": int(nbars),
        "results_identical": bool(identical),
        "verify_detail": details,
        "pure_ms_per_cell": round(pure_ms, 4),
        "numba_ms_per_cell": round(numba_ms, 4),
        "speedup_x": round(speedup, 3),
        "numba_first_call_ms": round(compile_plus_first, 1),
        "total_trades_one_cell": total_trades,
        "extrapolated_507cell_scan_pure_s": round(pure_scan_s, 2),
        "extrapolated_507cell_scan_numba_s": round(numba_scan_s, 2),
    }
    outpath = os.path.join(LAB, "fast_backtest_results.json")
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print("Saved -> %s" % outpath)
    return out


if __name__ == "__main__":
    main()
