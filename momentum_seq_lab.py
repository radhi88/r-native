"""momentum_seq_lab.py — Do micro-momentum candle RUNS carry OOS edge? (causal, cost-net)

The user scalps fast off candle "runs" — N consecutive same-color candles. This
lab asks, with strict no-lookahead discipline, whether a run of N same-color
candles predicts ANYTHING tradable, and tests TWO opposing hypotheses on the
SAME detected runs:

  HYP-A  CONTINUATION : the run keeps going — trade WITH the run's direction.
  HYP-B  EXHAUSTION   : the run is spent — FADE it (trade against the run).

PATTERN (all close-confirmed at bar i, using ONLY bars <= i):
  * RUN_N           : N consecutive same-color candles (close>open up / close<open down),
                      tested for N in {3,4,5}. Direction = run color.
  * RUN_N_ACCEL     : same run, but ADDITIONALLY each candle's body strictly
                      larger than the prior candle's body (momentum acceleration).
  The pattern bar i is the LAST candle of the run. We act only AFTER it closes;
  outcomes are measured on bars strictly > i.

EDGE MEASURED TWO WAYS, OOS ONLY:
  1. forward N-bar directional hit-rate: did price close FWD_N bars later move in
     the hypothesis's predicted direction? (raw gauge, no cost). For CONTINUATION
     the predicted dir = run dir; for EXHAUSTION = opposite. FWD_N depends on TF
     (30 M5, 20 M15, 12 H1) per the brief.
  2. TRADABLE: enter at the pattern's CLOSE.
        CONTINUATION: SL beyond the run's far extreme (the run's low for a long /
            run's high for a short — the swing the run carved); TP = 2R.
        EXHAUSTION (fade): SL beyond the run's near extreme that just printed
            (the run's high for a fade-short / run's low for a fade-long — i.e.
            beyond where the run terminated); TP = 2R.
     First-touch on future bars; a bar whose range spans BOTH SL and TP -> SL
     (pessimistic). Realized R is netted of a realistic round-trip cost from meta.

RANDOM BASELINE (the honesty gate): for each (sym,tf) we draw, on the SAME bar
indices the real patterns could occur on, RANDOM-direction same-spec trades
(random long/short, SL = ATR-ish band so risk is comparable), bootstrapped 2000x,
and report the 95% CI of the random avg-R. A pattern only "beats random" if its
OOS avg-R lies ABOVE the random CI's upper bound AND its own bootstrap CI doesn't
straddle 0. We also bootstrap the pattern's own avg-R (2000x) so we can state
whether its 95% CI crosses 0.

RIGOR:
  * NO LOOKAHEAD. Runs use bars <= i. Entry at i.close; SL/TP resolved on bars > i.
  * 67/33 IS/OOS split BY TIME. Report OOS only (IS computed only to confirm split).
  * >= 40 OOS events required, else label small-sample (per brief).
  * Cost netted per trade in price units from <SYM>_meta.json (2x typ spread proxy).

DATA: read ONLY from data/lab_cache/<SYM>_<TF>.npz (t,o,h,l,c,v). If a cache file
is missing, fall back to MetaTrader5 copy_rates_from_pos (initialize once).

RUN:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\momentum_seq_lab.py
Results JSON -> data/lab_cache/momentum_seq_lab_results.json
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "US30m", "BTCUSDm"]
TFS = ["M5", "M15", "H1"]
RUN_NS = [3, 4, 5]
IS_FRAC = 0.67          # 67/33 split by time
RR = 2.0                # TP = 2R
MIN_OOS = 40            # below this -> small-sample flag (per brief)
BOOT = 2000             # bootstrap resamples (per brief)
SEED = 7

# forward-bar horizon for the raw directional hit-rate, per TF (per brief)
FWD_N = {"M5": 30, "M15": 20, "H1": 12}
# max bars to hold a tradable trade before timeout (mark-to-close). Tie horizon
# to FWD_N so the trade has a comparable window to resolve.
MAX_HOLD = {"M5": 30, "M15": 20, "H1": 12}

# typical round-trip cost in POINTS per symbol (spread + commission proxy).
# price cost = points * point. Brief: gold ~20-30 pts, FX ~1-2 pips, US30 ~2-4
# pts, BTC ~30-60 pts. For 5-digit FX, 1 pip = 10 points, so 1.5 pips = 15 pts.
TYP_COST_POINTS = {
    "XAUUSDm": 25.0,    # gold ~20-30 points
    "EURUSDm": 15.0,    # ~1.5 pips * 10 pts/pip
    "GBPUSDm": 20.0,    # ~2.0 pips * 10 pts/pip
    "US30m": 30.0,      # ~3 pts (point=0.1 -> 30 points)
    "BTCUSDm": 4500.0,  # ~45 USD (point=0.01 -> 4500 points)
}
# fallback bar counts if we must pull from MT5
MT5_BARS = {"M5": 40000, "M15": 30000, "H1": 20000}


# ---------------------------------------------------------------------------
# Data (cache first, MT5 fallback)
# ---------------------------------------------------------------------------
def _mt5_fallback(sym: str, tf: str):
    import MetaTrader5 as mt5  # noqa
    if not getattr(_mt5_fallback, "_init", False):
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        _mt5_fallback._init = True
    tfmap = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    rates = mt5.copy_rates_from_pos(sym, tfmap[tf], 0, MT5_BARS[tf])
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 returned no rates for {sym} {tf}")
    return (rates["time"].astype(np.int64),
            rates["open"].astype(np.float64), rates["high"].astype(np.float64),
            rates["low"].astype(np.float64), rates["close"].astype(np.float64),
            rates["tick_volume"].astype(np.float64))


def load_bars(sym: str, tf: str):
    p = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(p):
        d = np.load(p)
        return (d["t"].astype(np.int64),
                d["o"].astype(np.float64), d["h"].astype(np.float64),
                d["l"].astype(np.float64), d["c"].astype(np.float64),
                d["v"].astype(np.float64))
    print(f"[cache-miss] {sym} {tf} -> MT5 fallback")
    return _mt5_fallback(sym, tf)


def load_meta(sym: str) -> dict:
    p = os.path.join(CACHE, f"{sym}_meta.json")
    with open(p, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def roundtrip_cost_price(sym: str, meta: dict) -> float:
    point = float(meta["point"])
    return TYP_COST_POINTS.get(sym, 20.0) * point


# ---------------------------------------------------------------------------
# Run detector. A "run" at bar i = the last bar of N consecutive same-color
# candles ending at i. Returns list of dicts (strictly causal; uses bars <= i):
#   { i, dir, run_hi, run_lo } where dir=+1 (green run) / -1 (red run),
#   run_hi/run_lo = extreme high/low across the N run bars.
# accel=True additionally requires each run body strictly > prior body.
#
# NON-OVERLAP: we register a run only at the FIRST bar that completes exactly N
# (i.e. the (N)-th consecutive bar) and NOT again while the streak keeps growing,
# so a 6-green streak yields ONE N=3 event (at the 3rd bar), not 4. This keeps
# events near-independent and avoids inflating n by counting nested windows.
# (We still allow a longer streak to later produce a fresh N-run after a color
# flip — runs are segmented by color changes.)
# ---------------------------------------------------------------------------
def detect_runs(o, h, l, c, N: int, accel: bool) -> List[dict]:
    n = c.size
    out = []
    # streak length of current color ending at each bar
    color = np.zeros(n, dtype=np.int8)   # +1 green, -1 red, 0 doji
    for i in range(n):
        if c[i] > o[i]:
            color[i] = 1
        elif c[i] < o[i]:
            color[i] = -1
        else:
            color[i] = 0
    body = np.abs(c - o)

    streak = 0
    cur = 0
    for i in range(n):
        col = color[i]
        if col == 0:
            streak = 0
            cur = 0
            continue
        if col == cur:
            streak += 1
        else:
            cur = col
            streak = 1
        # fire exactly when the streak first reaches N (the N-th bar)
        if streak == N:
            run_idx = range(i - N + 1, i + 1)
            if accel:
                ok = True
                for k in range(i - N + 2, i + 1):
                    if not (body[k] > body[k - 1]):
                        ok = False
                        break
                if not ok:
                    continue
            run_hi = float(np.max(h[i - N + 1:i + 1]))
            run_lo = float(np.min(l[i - N + 1:i + 1]))
            out.append({"i": i, "dir": int(col), "run_hi": run_hi, "run_lo": run_lo})
    return out


# ---------------------------------------------------------------------------
# Trade simulation. Enter at pattern close c[i]. trade_dir = +1 long / -1 short.
# SL_price given; TP = entry +/- RR*risk. First-touch on bars > i; span both->SL.
# Returns realized R (cost-netted) or None if risk<=0.
# ---------------------------------------------------------------------------
def simulate_trade(i, trade_dir, sl_price, o, h, l, c, cost_price, max_hold) -> Optional[float]:
    n = c.size
    entry = c[i]
    if trade_dir > 0:
        risk = entry - sl_price
        if risk <= 0:
            return None
        tp = entry + RR * risk
    else:
        risk = sl_price - entry
        if risk <= 0:
            return None
        tp = entry - RR * risk

    end = min(n, i + 1 + max_hold)
    for j in range(i + 1, end):
        if trade_dir > 0:
            hit_sl = l[j] <= sl_price
            hit_tp = h[j] >= tp
        else:
            hit_sl = h[j] >= sl_price
            hit_tp = l[j] <= tp
        if hit_sl and hit_tp:
            return -1.0 - cost_price / risk          # pessimistic tie -> SL
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    # timeout: mark to last available close
    last = c[end - 1]
    pnl_price = (last - entry) if trade_dir > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


def fwd_hit(i, pred_dir, c, fwd_n) -> Optional[int]:
    n = c.size
    j = i + fwd_n
    if j >= n:
        return None
    moved = c[j] - c[i]
    if moved == 0:
        return 0
    return int((moved > 0) == (pred_dir > 0))


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------
def _boot_ci(rs_a: np.ndarray, B: int, seed: int):
    """Bootstrap mean; return (ci_lo, ci_hi, p_le_0). p_le_0 = share of resample
    means <= 0 (one-sided 'no positive edge' p-value)."""
    nn = rs_a.size
    if nn < 5:
        return None, None, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nn, size=(B, nn))
    means = rs_a[idx].mean(axis=1)
    return (round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4),
            round(float((means <= 0).mean()), 4))


def random_baseline(dirs_pool: List[Tuple[int, int, float, float]],
                    o, h, l, c, cost_price, max_hold, seed) -> dict:
    """Random-direction baseline on the SAME candidate bar indices, PLUS the
    rigorous paired-lift test for the continuation hypothesis.

    For each candidate we know the run's risk band (run_hi/run_lo) and the run
    direction. We compute the realized R for BOTH possible trade directions
    (long uses run_lo as SL, short uses run_hi as SL — the same bands the real
    strategies use). Two outputs:

      (1) RANDOM CI: bootstrap the avg-R when the trade direction is a coin flip
          (the 'no directional skill' baseline). Reported as rand_ci95_*.
      (2) PAIRED LIFT: per event, continuation_R (trade the run's own dir) minus
          the per-event random expectation E=0.5*(R_long+R_short). Bootstrap the
          MEAN of that paired difference. Because the SL band is identical, this
          isolates pure DIRECTIONAL skill and removes common per-event noise — a
          far tighter test than comparing two independent CIs. Edge => the paired
          difference CI excludes 0 (lift_ci_lo > 0)."""
    if not dirs_pool:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    m0 = len(dirs_pool)
    r_long = np.full(m0, np.nan)
    r_short = np.full(m0, np.nan)
    r_cont = np.full(m0, np.nan)   # continuation = trade the run's own direction
    for k, (i, rdir, run_hi, run_lo) in enumerate(dirs_pool):
        rl = simulate_trade(i, +1, run_lo, o, h, l, c, cost_price, max_hold)
        rs = simulate_trade(i, -1, run_hi, o, h, l, c, cost_price, max_hold)
        if rl is not None:
            r_long[k] = rl
        if rs is not None:
            r_short[k] = rs
        r_cont[k] = rl if rdir > 0 else rs
    valid = ~(np.isnan(r_long) | np.isnan(r_short) | np.isnan(r_cont))
    r_long = r_long[valid]
    r_short = r_short[valid]
    r_cont = r_cont[valid]
    m = r_long.size
    if m < 5:
        return {"n": m}
    # (1) random-direction CI
    means = np.empty(BOOT)
    for b in range(BOOT):
        pick_short = rng.random(m) < 0.5
        sample = np.where(pick_short, r_short, r_long)
        res = sample[rng.integers(0, m, m)]
        means[b] = res.mean()
    # (2) paired continuation-minus-random-expectation lift
    rand_exp = 0.5 * (r_long + r_short)
    diff = r_cont - rand_exp
    didx = rng.integers(0, m, size=(BOOT, m))
    dmeans = diff[didx].mean(axis=1)
    lift_lo = float(np.percentile(dmeans, 2.5))
    lift_hi = float(np.percentile(dmeans, 97.5))
    lift_p = float((dmeans <= 0).mean())
    return {
        "n": int(m),
        "rand_avg_R": round(float((rand_exp).mean()), 4),
        "rand_ci95_lo": round(float(np.percentile(means, 2.5)), 4),
        "rand_ci95_hi": round(float(np.percentile(means, 97.5)), 4),
        "cont_lift_mean": round(float(diff.mean()), 4),
        "cont_lift_ci95_lo": round(lift_lo, 4),
        "cont_lift_ci95_hi": round(lift_hi, 4),
        "cont_lift_p_le_0": round(lift_p, 4),
        "cont_lift_edge": bool(lift_lo > 0),
    }


def summarize(rs: List[Optional[float]], hits: List[Optional[int]], boot: bool,
              seed: int) -> dict:
    rs2 = [r for r in rs if r is not None]
    hits2 = [hh for hh in hits if hh is not None]
    n = len(rs2)
    if n == 0:
        return {"n": 0}
    rs_a = np.array(rs2)
    wins = int((rs_a > 0).sum())
    out = {
        "n": n,
        "win_rate": round(100.0 * wins / n, 2),
        "avg_R": round(float(rs_a.mean()), 4),
        "total_R": round(float(rs_a.sum()), 3),
        "fwd_hit_rate": round(100.0 * float(np.mean(hits2)), 2) if hits2 else None,
        "fwd_n": len(hits2),
    }
    if boot and n >= 5:
        lo, hi, p = _boot_ci(rs_a, BOOT, seed)
        out["ci95_lo"], out["ci95_hi"], out["p_avgR_le_0"] = lo, hi, p
        # own-CI significance: avg_R>0 AND CI does not straddle 0
        out["ci_excludes_0"] = bool(lo is not None and lo > 0)
    return out


# ---------------------------------------------------------------------------
# Run one (symbol, tf): both hypotheses, all run-specs.
# ---------------------------------------------------------------------------
def run_one(sym, tf):
    t, o, h, l, c, v = load_bars(sym, tf)
    meta = load_meta(sym)
    point = float(meta["point"])
    cost_price = roundtrip_cost_price(sym, meta)
    n = c.size
    split = int(n * IS_FRAC)
    fwd_n = FWD_N[tf]
    max_hold = MAX_HOLD[tf]

    specs = {}
    for N in RUN_NS:
        for accel in (False, True):
            name = f"run{N}" + ("_accel" if accel else "")
            specs[name] = detect_runs(o, h, l, c, N, accel)

    out = {}
    for name, occ in specs.items():
        # buckets: (hypothesis, phase) -> {r, f}
        buckets = {
            ("continuation", "IS"): {"r": [], "f": []},
            ("continuation", "OOS"): {"r": [], "f": []},
            ("exhaustion", "IS"): {"r": [], "f": []},
            ("exhaustion", "OOS"): {"r": [], "f": []},
        }
        # candidate pool for the random baseline, OOS only (i, rdir, run_hi, run_lo)
        rand_pool_oos: List[Tuple[int, int, float, float]] = []

        for rec in occ:
            i = rec["i"]
            rdir = rec["dir"]
            run_hi = rec["run_hi"]
            run_lo = rec["run_lo"]
            if i >= n - 2:
                continue
            phase = "IS" if i < split else "OOS"

            # CONTINUATION: trade WITH run dir. SL beyond the run's far extreme
            # (the origin of the run move): long -> run_lo; short -> run_hi.
            cont_dir = rdir
            cont_sl = (run_lo - point) if cont_dir > 0 else (run_hi + point)
            r_cont = simulate_trade(i, cont_dir, cont_sl, o, h, l, c, cost_price, max_hold)
            f_cont = fwd_hit(i, cont_dir, c, fwd_n)
            buckets[("continuation", phase)]["r"].append(r_cont)
            buckets[("continuation", phase)]["f"].append(f_cont)

            # EXHAUSTION: FADE the run. trade dir = -rdir. SL beyond the run's
            # terminal extreme (where the run pushed to): fade-short -> run_hi;
            # fade-long -> run_lo.
            ex_dir = -rdir
            ex_sl = (run_lo - point) if ex_dir > 0 else (run_hi + point)
            r_ex = simulate_trade(i, ex_dir, ex_sl, o, h, l, c, cost_price, max_hold)
            f_ex = fwd_hit(i, ex_dir, c, fwd_n)
            buckets[("exhaustion", phase)]["r"].append(r_ex)
            buckets[("exhaustion", phase)]["f"].append(f_ex)

            if phase == "OOS":
                rand_pool_oos.append((i, rdir, run_hi, run_lo))

        res = {}
        for (hyp, phase), d in buckets.items():
            res.setdefault(hyp, {})[phase] = summarize(
                d["r"], d["f"], boot=(phase == "OOS"), seed=SEED)

        # random baseline (OOS) shared by both hypotheses on this spec
        rb = random_baseline(rand_pool_oos,
                             o, h, l, c, cost_price, max_hold, seed=SEED + 1)
        res["_random_oos"] = rb
        out[name] = res

    return out, {"n_bars": n, "split_idx": split, "cost_price": round(cost_price, 6),
                 "fwd_n": fwd_n, "max_hold": max_hold}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_results = {}
    rows = []  # flattened OOS rows for the printed table + verdict
    for sym in SYMBOLS:
        for tf in TFS:
            try:
                res, meta = run_one(sym, tf)
            except Exception as exc:
                print(f"[ERR] {sym} {tf}: {exc}")
                continue
            all_results[f"{sym}_{tf}"] = {"meta": meta, "specs": res}
            for spec, hyps in res.items():
                rb = hyps.get("_random_oos", {})
                for hyp in ("continuation", "exhaustion"):
                    oos = hyps.get(hyp, {}).get("OOS", {})
                    rows.append({
                        "symbol": sym, "tf": tf, "spec": spec, "hyp": hyp,
                        "n": oos.get("n", 0),
                        "win_rate": oos.get("win_rate"),
                        "avg_R": oos.get("avg_R"),
                        "fwd_hit": oos.get("fwd_hit_rate"),
                        "ci95_lo": oos.get("ci95_lo"),
                        "ci95_hi": oos.get("ci95_hi"),
                        "p_avgR_le_0": oos.get("p_avgR_le_0"),
                        "ci_excludes_0": oos.get("ci_excludes_0"),
                        "rand_avg_R": rb.get("rand_avg_R"),
                        "rand_ci_hi": rb.get("rand_ci95_hi"),
                        # paired continuation-vs-random lift (only meaningful for
                        # the continuation hypothesis; the same band is reused).
                        "cont_lift_mean": rb.get("cont_lift_mean") if hyp == "continuation" else None,
                        "cont_lift_ci_lo": rb.get("cont_lift_ci95_lo") if hyp == "continuation" else None,
                        "cont_lift_p_le_0": rb.get("cont_lift_p_le_0") if hyp == "continuation" else None,
                        "cont_lift_edge": rb.get("cont_lift_edge") if hyp == "continuation" else None,
                    })

    # ---- printed table ----
    print("=" * 122)
    print("MOMENTUM-SEQUENCE LAB — OOS (33% out-of-sample, by time). Tradable: "
          "enter@close, SL beyond run extreme, TP=2R, cost-net.")
    print("CONTINUATION = trade WITH the run. EXHAUSTION = FADE the run. "
          "Edge => OOS avg_R>0, own CI excludes 0, AND avg_R > random CI upper bound.")
    print("=" * 122)
    hdr = (f"{'SYMBOL':9} {'TF':4} {'SPEC':11} {'HYP':12} {'N':>5} {'WIN%':>6} "
           f"{'avgR':>8} {'CI95lo':>8} {'CI95hi':>8} {'fwd%':>6} {'randHi':>8}  FLAG")
    print(hdr)
    print("-" * 122)
    for row in sorted(rows, key=lambda r: (r["symbol"], r["tf"], r["spec"], r["hyp"])):
        nn = row["n"] or 0
        flag = "" if nn >= MIN_OOS else "small-sample"
        ar = row["avg_R"]
        # TRADABLE EDGE gate: continuation only, POSITIVE cost-net expectancy
        # whose own CI excludes 0 (makes money) AND paired-lift CI excludes 0
        # (the direction is real skill, not the entry timing). Both required.
        edge = (nn >= MIN_OOS and row["hyp"] == "continuation"
                and bool(row.get("ci_excludes_0")) and bool(row.get("cont_lift_edge")))
        # Directional-skill-only: lift is real but expectancy still <=0 after cost.
        skill_only = (nn >= MIN_OOS and row["hyp"] == "continuation"
                      and bool(row.get("cont_lift_edge")) and not edge)
        if edge:
            flag = (flag + " ").strip() + " <<EDGE (net+ & beats random)"
        elif skill_only:
            flag = (flag + " ").strip() + " (dir-skill but net<=0)"
        def f(x, w=8, sgn=True):
            if x is None:
                return f"{'-':>{w}}"
            return f"{x:+.3f}".rjust(w) if sgn else f"{x:.1f}".rjust(w)
        wr = f"{row['win_rate']:.1f}".rjust(6) if row["win_rate"] is not None else f"{'-':>6}"
        fw = f"{row['fwd_hit']:.1f}".rjust(6) if row["fwd_hit"] is not None else f"{'-':>6}"
        print(f"{row['symbol']:9} {row['tf']:4} {row['spec']:11} {row['hyp']:12} "
              f"{nn:>5} {wr} {f(ar)} {f(row['ci95_lo'])} {f(row['ci95_hi'])} "
              f"{fw} {f(row['rand_ci_hi'])}  {flag}")

    # ---- verdict scan ----
    print("\n" + "=" * 122)
    print("CANDIDATE EDGES (n>=40, OOS avg_R>0, own bootstrap CI excludes 0):")
    cand = [r for r in rows if (r["n"] or 0) >= MIN_OOS and r["avg_R"] is not None
            and r.get("ci_excludes_0")]
    beats_random = []
    if not cand:
        print("  NONE — no spec/hypothesis has a positive avg_R whose 95% CI excludes 0.")
    else:
        for e in sorted(cand, key=lambda r: -r["avg_R"]):
            # TWO 'beats random' lenses:
            #  (loose) avg_R above the random-direction CI upper bound; and
            #  (strict) the PAIRED lift (continuation_R - per-event random E[R])
            #           CI excludes 0 — the rigorous directional-skill test.
            loose = (e.get("rand_ci_hi") is not None and e["avg_R"] > e["rand_ci_hi"])
            strict = bool(e.get("cont_lift_edge"))
            if e["hyp"] == "continuation":
                tag = ("BEATS RANDOM (paired-lift CI excludes 0)" if strict
                       else "does NOT beat random (paired lift straddles 0)")
                lift_s = (f" lift={e['cont_lift_mean']:+.3f} p(lift<=0)={e['cont_lift_p_le_0']}"
                          if e.get("cont_lift_mean") is not None else "")
            else:
                tag = ("above random CI but FADE — not a paired test" if loose
                       else "does NOT beat random baseline")
                lift_s = ""
            print(f"  {e['symbol']} {e['tf']} {e['spec']}/{e['hyp']}: "
                  f"avg_R={e['avg_R']:+.3f} WR={e['win_rate']}% n={e['n']} "
                  f"CI95=[{e['ci95_lo']},{e['ci95_hi']}] "
                  f"randCI_hi={e.get('rand_ci_hi')} fwd%={e['fwd_hit']}{lift_s}  -> {tag}")
            if e["hyp"] == "continuation" and strict:
                beats_random.append(e)
    print(f"\n  >>> Continuation specs that BEAT random by the STRICT paired-lift "
          f"test (lift CI excludes 0): {len(beats_random)}")
    if not beats_random:
        print("  >>> NONE -> NO_EDGE for micro-momentum runs.")
    else:
        for e in beats_random:
            print(f"      {e['symbol']} {e['tf']} {e['spec']}/{e['hyp']} "
                  f"(avg_R {e['avg_R']:+.3f}, paired lift {e['cont_lift_mean']:+.3f} "
                  f"over random, p(lift<=0)={e['cont_lift_p_le_0']})")

    # continuation-vs-exhaustion direction tally (which way do runs lean OOS?)
    print("\nDIRECTION LEAN (OOS fwd-hit > 50% means runs tend that way; n>=40 only):")
    lean = {"continuation": [], "exhaustion": []}
    for r in rows:
        if (r["n"] or 0) >= MIN_OOS and r["fwd_hit"] is not None:
            lean[r["hyp"]].append(r["fwd_hit"])
    for hyp in ("continuation", "exhaustion"):
        vals = lean[hyp]
        if vals:
            print(f"  {hyp:12}: mean fwd-hit {np.mean(vals):.1f}% across {len(vals)} cells "
                  f"(>50 favors {hyp})")

    # ---- save ----
    outpath = os.path.join(CACHE, "momentum_seq_lab_results.json")
    payload = {
        "config": {
            "SYMBOLS": SYMBOLS, "TFS": TFS, "RUN_NS": RUN_NS,
            "IS_FRAC": IS_FRAC, "RR": RR, "MIN_OOS": MIN_OOS,
            "FWD_N": FWD_N, "MAX_HOLD": MAX_HOLD, "BOOT": BOOT,
            "cost_points": TYP_COST_POINTS,
            "cost_model": "round-trip = TYP_COST_POINTS * point (spread+commission proxy), price units",
            "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
            "non_overlap_runs": "one event at the N-th consecutive bar; segmented by color flip",
            "no_lookahead": True,
        },
        "results": all_results,
        "summary_oos": rows,
        "verdict": {
            "candidates_ci_excludes_0": len(cand),
            "beats_random": len(beats_random),
            "beats_random_cells": [
                f"{e['symbol']}_{e['tf']}_{e['spec']}_{e['hyp']}" for e in beats_random],
        },
    }
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nResults saved -> {outpath}")
    return all_results, rows, beats_random


if __name__ == "__main__":
    main()
