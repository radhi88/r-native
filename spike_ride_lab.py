#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
spike_ride_lab.py
=================
Tests THE USER'S ACTUAL STYLE: enter aggressively WITH a price SPIKE (jump) in
the spike's direction (continuation) and RIDE it for profit.

QUESTION (honest, falsifiable):
  Does entering WITH a spike and RIDING it have a real, net-of-cost,
  out-of-sample edge -- per symbol / timeframe / spike-threshold k?

DESIGN (strict, no-lookahead):
  * ATR(14) computed causally (Wilder). At bar i we use ATR that is known
    AT the close of bar i (built only from bars <= i).
  * SPIKE = a W-bar window ending at bar i whose move is large vs ATR:
        - directional move      = c[i] - o[i-W+1]
        - window amplitude       = max(h[i-W+1..i]) - min(l[i-W+1..i])
      Spike confirmed if  amplitude >= k * ATR(at i-1)   (k in {1.5,2.0,3.0})
      AND the net directional move has the same sign as the dominant push
      (|directional move| >= 0.5 * amplitude) so we only ride decisive jumps,
      not chop. W tested in {1,2,3} bars.
    Direction = sign(c[i] - o[i-W+1]).
  * ENTER at close of the confirmed spike bar (c[i]).  (Variant: next open.)
  * RISK (R) = distance from entry to structural SL.
      SL beyond the spike's ORIGIN = the window's pre-spike extreme:
        long  -> SL = min(l[i-W+1..i]) - pad
        short -> SL = max(h[i-W+1..i]) + pad
      pad = 0.10 * ATR (small structural buffer).
  * RIDE EXITS tested:
        TP3R     : fixed take-profit at +3R, SL at -1R
        trailwide: chandelier trail = 3*ATR from running extreme (give room)
        holdH    : hold up to H bars then exit at market (H=40 M5,24 M15,12 H1)
      All exits also honor the structural SL.
  * Forward sim bar-by-bar from i+1. CONSERVATIVE intrabar ordering: if a bar's
    range touches BOTH stop and target, assume the STOP filled first (worst case).
  * COST: realistic round-trip cost in PRICE units subtracted from every trade
    (spread + slippage), per symbol. Converted to R by dividing by risk distance.
  * SPLIT 67/33 IS/OOS by time. Report OOS ONLY. Need >=40 OOS events else
    flagged small_sample.
  * BASELINE: random-entry, SAME exit machinery, SAME bars, bootstrap 2000x.
    Edge is real only if OOS avg-R bootstrap 95% CI is clear of the random
    baseline CI (and ideally clear of 0).

Outputs: data/lab_cache/spike_ride_results.json  + printed summary.

NEVER fabricates. If data is thin or edge is absent, it says so.
"""
import os, sys, json, math, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "US30m", "GBPUSDm"]
TFS = ["M5", "M15", "H1"]
KS = [1.5, 2.0, 3.0]
WINDOWS = [1, 2, 3]            # spike window in bars
HOLD = {"M5": 40, "M15": 24, "H1": 12}
ATR_N = 14
PAD_ATR = 0.10                 # structural SL buffer as fraction of ATR
TRAIL_ATR = 3.0                # chandelier trail width
MIN_OOS = 40
BOOT = 2000
RNG = np.random.default_rng(20260616)

# ---- realistic round-trip COST in PRICE units (spread + slippage) -----------
# Conservative retail micro-account estimates (Exness-style 'm' symbols).
# These are intentionally generous (pessimistic) so the test is honest.
COST_PRICE = {
    "XAUUSDm": 0.35,    # gold ~ 30-40 cents round trip
    "BTCUSDm": 12.0,    # bitcoin spread+slip, dollars
    "EURUSDm": 0.00012, # ~1.2 pip
    "US30m":   2.5,     # index points
    "GBPUSDm": 0.00018, # ~1.8 pip
}


def load_bars(sym, tf):
    p = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(p):
        d = np.load(p)
        return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
                d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))
    # fallback to MT5
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return None
        tfmap = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
        r = mt5.copy_rates_from_pos(sym, tfmap[tf], 0, 40000)
        mt5.shutdown()
        if r is None or len(r) == 0:
            return None
        return (r["time"].astype(np.int64), r["open"].astype(float), r["high"].astype(float),
                r["low"].astype(float), r["close"].astype(float), r["tick_volume"].astype(float))
    except Exception:
        return None


def wilder_atr(h, l, c, n=ATR_N):
    """Causal Wilder ATR. atr[i] uses only data through bar i. atr[i] is NaN
    until enough bars. We will index atr at i-1 when deciding at bar i, so a
    spike decision at i never uses bar i's own ATR contribution beyond TR[i]
    which is itself fully known at close of i (we use atr[i-1] to be strict)."""
    nbar = len(c)
    tr = np.empty(nbar)
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - pc), np.abs(l[1:] - pc)])
    atr = np.full(nbar, np.nan)
    if nbar <= n:
        return atr
    atr[n] = tr[1:n + 1].mean()
    for i in range(n + 1, nbar):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def detect_spikes(o, h, l, c, atr, k, w):
    """Return list of (i, direction, sl, entry) for spikes confirmed at bar i.
    Strict no-lookahead: uses atr[i-1] (known before bar i forms in our model
    we treat atr at i-1 as the established volatility) and bars in [i-w+1, i].
    Entry = c[i]. SL = window pre-spike extreme +/- pad."""
    out = []
    n = len(c)
    start = max(ATR_N + 2, w)
    for i in range(start, n):
        a = atr[i - 1]
        if not np.isfinite(a) or a <= 0:
            continue
        j0 = i - w + 1
        win_hi = h[j0:i + 1].max()
        win_lo = l[j0:i + 1].min()
        amp = win_hi - win_lo
        if amp < k * a:
            continue
        dirmove = c[i] - o[j0]
        if abs(dirmove) < 0.5 * amp:   # require decisive directional push
            continue
        direction = 1 if dirmove > 0 else -1
        entry = c[i]
        pad = PAD_ATR * a
        if direction == 1:
            sl = win_lo - pad
            if sl >= entry:
                continue
        else:
            sl = win_hi + pad
            if sl <= entry:
                continue
        out.append((i, direction, sl, entry, a))
    return out


def simulate(o, h, l, c, i_entry, direction, sl, entry, atr_at, exit_rule, tf, cost_price):
    """Forward sim from i_entry+1. Returns R (net of cost) or None if no exit
    within data. Conservative: SL-before-TP within the same bar."""
    n = len(c)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    Hmax = HOLD[tf]
    if exit_rule == "TP3R":
        tp = entry + direction * 3.0 * risk
    run_ext = entry  # running favorable extreme for trail
    for step in range(1, Hmax + 1):
        i = i_entry + step
        if i >= n:
            # ran out of data: exit at last close
            px = c[n - 1]
            gross = direction * (px - entry)
            return (gross - cost_price) / risk
        bh, bl = h[i], l[i]
        # --- stop check (structural SL always active) ---
        hit_sl = (bl <= sl) if direction == 1 else (bh >= sl)
        if exit_rule == "TP3R":
            hit_tp = (bh >= tp) if direction == 1 else (bl <= tp)
            if hit_sl and hit_tp:
                # conservative: stop first
                gross = direction * (sl - entry)
                return (gross - cost_price) / risk
            if hit_sl:
                gross = direction * (sl - entry)
                return (gross - cost_price) / risk
            if hit_tp:
                gross = direction * (tp - entry)
                return (gross - cost_price) / risk
        elif exit_rule == "trailwide":
            # update favorable extreme using this bar, then compute trail stop.
            # Conservative: check the structural/trailing stop using THIS bar's
            # extreme but only trail off PRIOR extreme to avoid lookahead on the
            # very bar that makes the new high.
            trail_stop = (run_ext - TRAIL_ATR * atr_at) if direction == 1 \
                         else (run_ext + TRAIL_ATR * atr_at)
            eff_stop = max(sl, trail_stop) if direction == 1 else min(sl, trail_stop)
            hit = (bl <= eff_stop) if direction == 1 else (bh >= eff_stop)
            if hit:
                gross = direction * (eff_stop - entry)
                return (gross - cost_price) / risk
            # update extreme AFTER stop check (prior-bar extreme governs)
            run_ext = max(run_ext, bh) if direction == 1 else min(run_ext, bl)
        elif exit_rule == "holdH":
            if hit_sl:
                gross = direction * (sl - entry)
                return (gross - cost_price) / risk
            # else keep holding to H
        # holdH falls through until step == Hmax
    # time exit at H
    i = min(i_entry + Hmax, n - 1)
    px = c[i]
    gross = direction * (px - entry)
    return (gross - cost_price) / risk


def random_baseline(o, h, l, c, atr, n_events, direction_pool, sl_dist_pool,
                    exit_rule, tf, cost_price, valid_lo, valid_hi):
    """Random entries in [valid_lo, valid_hi): random index, random direction,
    structural-style SL placed at a random distance drawn from the SPIKE
    population's risk distances (so risk scale matches). Same exit machinery."""
    n = len(c)
    Rs = []
    tries = 0
    target = n_events
    while len(Rs) < target and tries < target * 20:
        tries += 1
        i = int(RNG.integers(valid_lo, valid_hi))
        a = atr[i - 1] if i - 1 < n else np.nan
        if not np.isfinite(a) or a <= 0:
            continue
        d = int(direction_pool[RNG.integers(len(direction_pool))])
        risk = float(sl_dist_pool[RNG.integers(len(sl_dist_pool))])
        if risk <= 0:
            continue
        entry = c[i]
        sl = entry - d * risk
        r = simulate(o, h, l, c, i, d, sl, entry, a, exit_rule, tf, cost_price)
        if r is not None:
            Rs.append(r)
    return np.array(Rs)


def boot_ci(arr, fn=np.mean, n=BOOT, lo=2.5, hi=97.5):
    if len(arr) == 0:
        return (float("nan"), float("nan"), float("nan"))
    arr = np.asarray(arr, float)
    idx = RNG.integers(0, len(arr), size=(n, len(arr)))
    stats = fn(arr[idx], axis=1)
    return float(fn(arr)), float(np.percentile(stats, lo)), float(np.percentile(stats, hi))


def pf(Rs):
    Rs = np.asarray(Rs, float)
    g = Rs[Rs > 0].sum()
    b = -Rs[Rs < 0].sum()
    if b == 0:
        return float("inf") if g > 0 else 0.0
    return g / b


def main():
    results = {"meta": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "atr_n": ATR_N, "ks": KS, "windows": WINDOWS,
                        "hold": HOLD, "cost_price": COST_PRICE,
                        "split": "67/33 IS/OOS by time", "boot": BOOT,
                        "intrabar": "stop-before-target (conservative)",
                        "question": "Does entering WITH a spike and RIDING it have a real net-of-cost OOS edge?"},
               "runs": []}
    exit_rules = ["TP3R", "trailwide", "holdH"]
    entry_variants = ["close"]  # primary: enter at spike close

    best_edges = []
    for sym in SYMBOLS:
        cost_price = COST_PRICE[sym]
        for tf in TFS:
            bars = load_bars(sym, tf)
            if bars is None:
                results["runs"].append({"sym": sym, "tf": tf, "error": "no_data"})
                continue
            t, o, h, l, c, v = bars
            atr = wilder_atr(h, l, c)
            n = len(c)
            split_t = t[int(n * 0.67)]   # time split
            for w in WINDOWS:
                spikes_all = detect_spikes(o, h, l, c, atr, k=None if False else KS[0], w=w) if False else None
                for k in KS:
                    spikes = detect_spikes(o, h, l, c, atr, k, w)
                    if not spikes:
                        continue
                    # split by time of entry bar
                    oos = [s for s in spikes if t[s[0]] >= split_t]
                    iss = [s for s in spikes if t[s[0]] < split_t]
                    n_oos = len(oos)
                    if n_oos == 0:
                        continue
                    # risk-distance pool & direction pool for baseline (from OOS spikes)
                    risk_pool = np.array([abs(s[3] - s[2]) for s in oos])
                    dir_pool = np.array([s[1] for s in oos])
                    valid_lo = int(np.searchsorted(t, split_t))
                    valid_hi = n - max(HOLD.values()) - 1
                    if valid_hi <= valid_lo + 5:
                        continue
                    for er in exit_rules:
                        # spike OOS R's
                        Rs = []
                        for (i, d, sl, entry, a) in oos:
                            r = simulate(o, h, l, c, i, d, sl, entry, a, er, tf, cost_price)
                            if r is not None:
                                Rs.append(r)
                        Rs = np.array(Rs)
                        if len(Rs) == 0:
                            continue
                        mean_r, ci_lo, ci_hi = boot_ci(Rs)
                        # random baseline matched count
                        base = random_baseline(o, h, l, c, atr, len(Rs), dir_pool,
                                               risk_pool, er, tf, cost_price,
                                               valid_lo, valid_hi)
                        b_mean, b_lo, b_hi = boot_ci(base) if len(base) else (float("nan"),)*3
                        wr = float((Rs > 0).mean())
                        net = float(Rs.sum())
                        edge_vs_zero = ci_lo > 0
                        edge_vs_rand = (not math.isnan(b_hi)) and (ci_lo > b_hi)
                        rec = {
                            "sym": sym, "tf": tf, "k": k, "window": w, "exit": er,
                            "n_oos": int(len(Rs)),
                            "small_sample": len(Rs) < MIN_OOS,
                            "avg_R": round(mean_r, 4),
                            "avg_R_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
                            "win_rate": round(wr, 4),
                            "pf": round(pf(Rs), 3),
                            "net_R": round(net, 2),
                            "rand_avg_R": round(b_mean, 4) if not math.isnan(b_mean) else None,
                            "rand_avg_R_ci95": [round(b_lo, 4), round(b_hi, 4)] if not math.isnan(b_lo) else None,
                            "edge_vs_zero": bool(edge_vs_zero),
                            "edge_vs_random": bool(edge_vs_rand),
                        }
                        results["runs"].append(rec)
                        if edge_vs_zero and edge_vs_rand and not rec["small_sample"]:
                            best_edges.append(rec)

    best_edges.sort(key=lambda r: r["avg_R"], reverse=True)
    results["edges_passing_all_gates"] = best_edges

    outp = os.path.join(CACHE, "spike_ride_results.json")
    with open(outp, "w") as f:
        json.dump(results, f, indent=1)

    # ----- printed summary -----
    print("=" * 78)
    print("SPIKE-RIDE LAB  (enter WITH a spike, RIDE it)  -- OOS only, net of cost")
    print("=" * 78)
    runs = [r for r in results["runs"] if "avg_R" in r]
    print(f"total configs tested: {len(runs)}   |   configs passing ALL gates "
          f"(CI>0 AND CI>random AND n>={MIN_OOS}): {len(best_edges)}")
    print("-" * 78)
    hdr = f"{'SYM':8}{'TF':4}{'k':4}{'W':3}{'exit':10}{'nOOS':6}{'avgR':9}{'CI95':18}{'WR':7}{'PF':7}{'vs0':4}{'vRnd':5}"
    print(hdr)
    # show the strongest config per (sym,tf) for readability
    by_cell = {}
    for r in runs:
        key = (r["sym"], r["tf"])
        if key not in by_cell or r["avg_R"] > by_cell[key]["avg_R"]:
            by_cell[key] = r
    for sym in SYMBOLS:
        for tf in TFS:
            r = by_cell.get((sym, tf))
            if not r:
                continue
            ci = f"[{r['avg_R_ci95'][0]:+.3f},{r['avg_R_ci95'][1]:+.3f}]"
            flag0 = "Y" if r["edge_vs_zero"] else "-"
            flagr = "Y" if r["edge_vs_random"] else "-"
            ss = "*" if r["small_sample"] else " "
            print(f"{r['sym']:8}{r['tf']:4}{r['k']:<4}{r['window']:<3}{r['exit']:10}"
                  f"{r['n_oos']:<6}{r['avg_R']:+8.3f}{ss}{ci:18}{r['win_rate']*100:5.1f}% "
                  f"{r['pf']:<6.2f}{flag0:<4}{flagr:<5}")
    print("-" * 78)
    print("(* = small sample <40 OOS; vs0=CI clear of 0; vRnd=CI clear of random baseline)")
    print("=" * 78)
    if best_edges:
        print("EDGES PASSING ALL GATES (sorted by avg R):")
        for r in best_edges[:15]:
            print(f"  {r['sym']:8}{r['tf']:4} k={r['k']} W={r['window']} {r['exit']:10}"
                  f" avgR={r['avg_R']:+.3f} CI{r['avg_R_ci95']} WR={r['win_rate']*100:.0f}%"
                  f" PF={r['pf']} n={r['n_oos']} (rand avgR={r['rand_avg_R']})")
    else:
        print("NO configuration passed all gates. Spike-and-ride shows NO robust")
        print("net-of-cost OOS edge over a random-entry baseline in this data.")
    print("=" * 78)
    print(f"results saved -> {outp}")
    return results


if __name__ == "__main__":
    main()
