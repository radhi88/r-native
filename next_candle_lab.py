"""next_candle_lab.py — "وش راح يصير بعدها": does candle SHAPE predict the NEXT candle?

The question, stated plainly: if I look at the last 2 or 3 candles and classify
their SHAPE (big bull, big bear, doji, upper-wick, lower-wick, inside-bar...),
does the resulting SEQUENCE tell me anything about whether the NEXT candle closes
up or down — with a hit-rate meaningfully above a coin flip, that survives cost
for a 1-bar scalp? Or is it all ~50% noise?

This is a SHAPE-SEQUENCE study, distinct from candle_lab.py (which tested named
reversal patterns + SMC confluence). Here we brute-force EVERY 2-candle and
3-candle shape combination and let the data speak.

----------------------------------------------------------------------------
CANDLE SHAPE CLASSES (each candle encoded from its own o/h/l/c, plus the prior
bar's range for the "inside" test — strictly causal, uses only bars <= i):

    inside      : bar fully inside the prior bar's high-low (h<=h_prev, l>=l_prev)
                  -> tested FIRST; an inside bar is an inside bar regardless of body
    doji        : body <= 10% of range (indecision)
    big_bull    : up bar, body >= 60% of range (strong demand)
    big_bear    : down bar, body >= 60% of range (strong supply)
    upper_wick  : upper wick >= 2x body AND upper wick is the dominant wick
                  (rejection from above — "shooting-star-ish")
    lower_wick  : lower wick >= 2x body AND lower wick is the dominant wick
                  (rejection from below — "hammer-ish")
    small_bull  : up bar, none of the above (ordinary small green)
    small_bear  : down bar, none of the above (ordinary small red)

Classification order is deterministic: inside -> doji -> big -> wick -> small.

----------------------------------------------------------------------------
WHAT WE MEASURE — two independent edges, OOS only:

  (1) DIRECTIONAL HIT-RATE of the NEXT candle. For each sequence class, P(next
      candle close > next candle open). Tested against a 50% coin flip with an
      exact binomial two-sided p-value. The class's "predicted side" is chosen
      ON THE IS DATA (predict UP if IS P(up)>50%, else DOWN); on OOS we then ask
      whether that pre-committed side hits > 50%. (No peeking: the side is locked
      from IS, evaluated on OOS.)

  (2) TRADABLE 1-bar-ish scalp, net of realistic cost. After the sequence's last
      candle CLOSES, enter in the IS-chosen direction at that close. SL one tick
      beyond the sequence's extreme (the min low / max high of the candles in the
      sequence). TP = 2R. Walk forward up to N bars (N=30 M5, 20 M15, 12 H1);
      first touch wins; a bar spanning BOTH SL and TP counts as SL (pessimistic).
      Realized R is netted of a round-trip cost proxy (2x typical spread, from
      <SYM>_meta.json). Compared against a same-bar RANDOM-direction baseline via
      a 2000x bootstrap; if the 95% CI of avg-R crosses 0 -> NOT a real edge.

----------------------------------------------------------------------------
STRICT NO-LOOKAHEAD:
  * A sequence ending at bar i uses ONLY bars <= i (shape of i and its
    predecessors; the "inside" test uses i-1 which is < i).
  * The trade acts AFTER bar i closes (entry = c[i]); SL/TP resolve on bars > i.
  * The predicted SIDE for each class is fit on IS only and frozen for OOS.
  * 67/33 IS/OOS split BY TIME. We report OOS only.
  * >= 40 OOS events required per class, else flagged small-sample.

DATA: data/lab_cache/<SYM>_<TF>.npz (t,o,h,l,c,v). Falls back to MetaTrader5
copy_rates_from_pos if a cache file is missing (initialize once). Cost from
<SYM>_meta.json (tick_value / point).

SYMBOLS x TFS: [XAUUSDm,EURUSDm,GBPUSDm,US30m,BTCUSDm] x [M5,M15,H1].

RUN:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\next_candle_lab.py
Results JSON -> data/lab_cache/next_candle_lab_results.json
"""
from __future__ import annotations

import json
import math
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
IS_FRAC = 0.67           # 67/33 split by time
RR = 2.0                 # TP = 2R
MIN_OOS = 40             # below this -> small-sample flag
# forward bars to let a 1-bar-scalp trade resolve, per the brief
FWD_N = {"M5": 30, "M15": 20, "H1": 12}

# typical round-trip cost in *points* (price = points * point). The brief's
# guidance: gold ~20-30 pts, FX ~1-2 pips, US30 ~2-4 pts, BTC ~30-60 pts.
# We model cost directly in price = points * point.
TYP_SPREAD_POINTS = {
    "XAUUSDm": 250.0,   # gold point=0.001 -> 250 pts = $0.25 ~ a 25-"point"(=0.01) spread, conservative mid
    "EURUSDm": 15.0,    # 5-digit FX: 1.5 pip = 15 points
    "GBPUSDm": 20.0,    # 2.0 pip = 20 points
    "US30m": 30.0,      # point=0.1 -> 30 pts = 3.0 index points (mid of 2-4)
    "BTCUSDm": 4500.0,  # point=0.01 -> 4500 pts = $45 (mid of $30-60)
}

# binomial significance threshold for the directional gauge
ALPHA = 0.05


# ---------------------------------------------------------------------------
# Data loading (cache first, MT5 fallback)
# ---------------------------------------------------------------------------
_TF_MAP = {"M5": ("TIMEFRAME_M5", 5), "M15": ("TIMEFRAME_M15", 15),
           "H1": ("TIMEFRAME_H1", 60)}
_mt5_inited = False


def _mt5_fallback(sym: str, tf: str, n: int = 40000):
    global _mt5_inited
    import MetaTrader5 as mt5  # type: ignore
    if not _mt5_inited:
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        _mt5_inited = True
    tfconst = getattr(mt5, _TF_MAP[tf][0])
    rates = mt5.copy_rates_from_pos(sym, tfconst, 0, n)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_from_pos returned nothing for {sym} {tf}")
    return (rates["time"].astype(np.int64),
            rates["open"].astype(np.float64), rates["high"].astype(np.float64),
            rates["low"].astype(np.float64), rates["close"].astype(np.float64),
            rates["tick_volume"].astype(np.float64))


def load_bars(sym: str, tf: str):
    path = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(path):
        d = np.load(path)
        return (d["t"].astype(np.int64),
                d["o"].astype(np.float64), d["h"].astype(np.float64),
                d["l"].astype(np.float64), d["c"].astype(np.float64),
                d["v"].astype(np.float64))
    print(f"  [cache miss] {sym} {tf} -> MetaTrader5 fallback")
    return _mt5_fallback(sym, tf)


def load_meta(sym: str) -> dict:
    path = os.path.join(CACHE, f"{sym}_meta.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    # minimal fallback meta
    return {"symbol": sym, "point": 0.01, "trade_tick_value": 1.0}


def roundtrip_cost_price(sym: str, meta: dict) -> float:
    """Round-trip cost in PRICE units = typical-spread-points * point. The
    TYP_SPREAD_POINTS already encode a realistic round-trip-ish proxy per brief."""
    point = float(meta["point"])
    return TYP_SPREAD_POINTS.get(sym, 30.0) * point


# ---------------------------------------------------------------------------
# Candle shape encoding (causal). class of bar i may use bar i and bar i-1 only.
# ---------------------------------------------------------------------------
DOJI_BODY = 0.10        # body <= 10% range -> doji
BIG_BODY = 0.60         # body >= 60% range -> big directional
WICK_MULT = 2.0         # dominant wick >= 2x body -> wick-rejection bar

CLASSES = ("inside", "doji", "big_bull", "big_bear",
           "upper_wick", "lower_wick", "small_bull", "small_bear")


def encode_shapes(o, h, l, c) -> np.ndarray:
    """Return an int8 array of class indices, one per bar. Bar 0 cannot be
    'inside' (no predecessor) — handled by treating i-1 as itself for i==0,
    which simply means bar 0 is never 'inside'."""
    n = c.size
    cls = np.empty(n, dtype=np.int8)
    idx = {name: k for k, name in enumerate(CLASSES)}
    for i in range(n):
        rng = h[i] - l[i]
        body = abs(c[i] - o[i])
        upper = h[i] - max(o[i], c[i])
        lower = min(o[i], c[i]) - l[i]
        up = c[i] > o[i]
        # 1) inside bar (needs predecessor)
        if i > 0 and h[i] <= h[i - 1] and l[i] >= l[i - 1]:
            cls[i] = idx["inside"]
            continue
        if rng <= 0:
            cls[i] = idx["doji"]
            continue
        body_frac = body / rng
        # 2) doji
        if body_frac <= DOJI_BODY:
            cls[i] = idx["doji"]
            continue
        # 3) big directional
        if body_frac >= BIG_BODY:
            cls[i] = idx["big_bull"] if up else idx["big_bear"]
            continue
        # 4) wick-rejection (only if a wick truly dominates the body)
        if body > 0:
            if upper >= WICK_MULT * body and upper > lower:
                cls[i] = idx["upper_wick"]
                continue
            if lower >= WICK_MULT * body and lower > upper:
                cls[i] = idx["lower_wick"]
                continue
        # 5) ordinary small body
        cls[i] = idx["small_bull"] if up else idx["small_bear"]
    return cls


# ---------------------------------------------------------------------------
# Trade simulation — enter at sequence's last close, SL beyond the sequence's
# extreme, TP=2R. First-touch on future bars; bar spanning both -> SL. Net cost.
# Returns realized R (cost-netted) or None if unresolvable.
# ---------------------------------------------------------------------------
def simulate_trade(i, direction, seq_lo, seq_hi, o, h, l, c,
                   cost_price, point, max_hold) -> Optional[float]:
    n = c.size
    entry = c[i]
    pad = point  # SL one tick beyond the sequence extreme
    if direction > 0:
        sl = seq_lo - pad
        risk = entry - sl
        if risk <= 0:
            return None
        tp = entry + RR * risk
    else:
        sl = seq_hi + pad
        risk = sl - entry
        if risk <= 0:
            return None
        tp = entry - RR * risk

    end = min(n, i + 1 + max_hold)
    for j in range(i + 1, end):
        hit_sl = (l[j] <= sl) if direction > 0 else (h[j] >= sl)
        hit_tp = (h[j] >= tp) if direction > 0 else (l[j] <= tp)
        if hit_sl and hit_tp:
            return -1.0 - cost_price / risk          # pessimistic tie -> SL
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    # timeout: mark to last close, cost-netted
    last = c[end - 1]
    pnl_price = (last - entry) if direction > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def binom_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial p-value for observing k successes in n trials
    under H0: prob = p. Uses the 'method of small p-values' (sum of all outcomes
    with pmf <= pmf(k)). Pure python — fine for n up to a few thousand."""
    if n == 0:
        return 1.0
    from math import comb
    pmf = [comb(n, x) * (p ** x) * ((1 - p) ** (n - x)) for x in range(n + 1)]
    pk = pmf[k]
    tot = sum(px for px in pmf if px <= pk + 1e-15)
    return min(1.0, tot)


def benjamini_hochberg(pvals: List[float], alpha: float = 0.05) -> int:
    """Number of hypotheses that survive Benjamini-Hochberg FDR control at
    `alpha`, given the FULL list of p-values for every test performed. This is
    the antidote to data-dredging: with thousands of shape classes, ~alpha*m
    will show p<alpha by chance alone. Returns how many are real after FDR."""
    m = len(pvals)
    if m == 0:
        return 0
    ps = np.sort(np.asarray(pvals, dtype=float))
    thresh = alpha * (np.arange(1, m + 1)) / m
    passed = ps <= thresh
    return int(np.where(passed)[0].max() + 1) if passed.any() else 0


def _bootstrap_avgR(rs_a: np.ndarray, B: int = 2000, seed: int = 7):
    """Bootstrap the mean R. Returns (ci_lo, ci_hi, p_le_0)."""
    n = rs_a.size
    if n < 5:
        return None, None, None
    rng = np.random.default_rng(seed)
    means = np.empty(B)
    for b in range(B):
        means[b] = rs_a[rng.integers(0, n, n)].mean()
    return (round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4),
            round(float((means <= 0).mean()), 4))


def random_baseline_avgR(occ_idx, seq_lo_arr, seq_hi_arr, o, h, l, c,
                         cost_price, point, max_hold,
                         B: int = 2000, seed: int = 11):
    """Same bars, RANDOM direction each draw. Build the bootstrap distribution
    of avg-R for a coin-flip trader entering at the same closes with the same
    SL/TP geometry. Returns (mean, ci_lo, ci_hi, p_le_0)."""
    rng = np.random.default_rng(seed)
    m = len(occ_idx)
    if m == 0:
        return None
    # precompute both-direction R for each event once (long & short)
    long_R = np.empty(m)
    short_R = np.empty(m)
    for k in range(m):
        i = occ_idx[k]
        rL = simulate_trade(i, +1, seq_lo_arr[k], seq_hi_arr[k], o, h, l, c,
                            cost_price, point, max_hold)
        rS = simulate_trade(i, -1, seq_lo_arr[k], seq_hi_arr[k], o, h, l, c,
                            cost_price, point, max_hold)
        long_R[k] = rL if rL is not None else np.nan
        short_R[k] = rS if rS is not None else np.nan
    means = np.empty(B)
    for b in range(B):
        sides = rng.integers(0, 2, m)  # 0 short, 1 long
        picked = np.where(sides == 1, long_R, short_R)
        picked = picked[~np.isnan(picked)]
        means[b] = picked.mean() if picked.size else np.nan
    means = means[~np.isnan(means)]
    if means.size == 0:
        return None
    return (round(float(means.mean()), 4),
            round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4),
            round(float((means <= 0).mean()), 4))


# ---------------------------------------------------------------------------
# Core: enumerate sequences, split IS/OOS, fit side on IS, evaluate on OOS.
# ---------------------------------------------------------------------------
def run_one(sym: str, tf: str) -> Tuple[dict, dict]:
    t, o, h, l, c, v = load_bars(sym, tf)
    meta = load_meta(sym)
    point = float(meta["point"])
    cost_price = roundtrip_cost_price(sym, meta)
    n = c.size
    split = int(n * IS_FRAC)
    max_hold = FWD_N[tf]

    cls = encode_shapes(o, h, l, c)
    next_up = (c > o)  # whether bar j closes up; we look at bar i+1

    # Collect events for 2-seq and 3-seq.
    # A sequence ENDS at bar i; next candle is i+1. We need i+1 < n (next exists)
    # and room for the trade to resolve (drop the unresolved tail).
    # Strict causal: sequence label uses cls[i-(L-1)..i], all <= i.
    results = {"seq2": {}, "seq3": {}}
    diag = {"n_bars": n, "split_idx": split, "cost_price": round(cost_price, 6),
            "max_hold": max_hold, "n_classes": len(CLASSES)}

    for L, key in ((2, "seq2"), (3, "seq3")):
        # accumulate per-class lists
        # store: IS up-count/total, OOS lists of (next_up, R, lo, hi, idx)
        buckets: Dict[str, dict] = {}
        start = L - 1
        for i in range(start, n - 1):  # need i+1
            label = tuple(int(cls[i - (L - 1) + s]) for s in range(L))
            name = "|".join(CLASSES[x] for x in label)
            b = buckets.setdefault(name, {
                "is_up": 0, "is_tot": 0,
                "oos_up": 0, "oos_tot": 0,
                "oos_idx": [], "oos_lo": [], "oos_hi": [],
            })
            nu = bool(next_up[i + 1])
            seq_lo = float(np.min(l[i - (L - 1):i + 1]))
            seq_hi = float(np.max(h[i - (L - 1):i + 1]))
            if i < split:
                b["is_tot"] += 1
                b["is_up"] += int(nu)
            else:
                b["oos_tot"] += 1
                b["oos_up"] += int(nu)
                b["oos_idx"].append(i)
                b["oos_lo"].append(seq_lo)
                b["oos_hi"].append(seq_hi)

        # evaluate each class
        for name, b in buckets.items():
            if b["is_tot"] < 20 or b["oos_tot"] < 1:
                continue  # need enough IS to even pick a side
            is_p_up = b["is_up"] / b["is_tot"]
            side = +1 if is_p_up >= 0.5 else -1  # IS-chosen, frozen for OOS

            oos_tot = b["oos_tot"]
            # directional hit-rate on OOS in the IS-chosen side
            # "hit" = next candle moved in `side` direction
            if side > 0:
                oos_hits = b["oos_up"]
            else:
                oos_hits = oos_tot - b["oos_up"]
            hit_rate = oos_hits / oos_tot if oos_tot else None
            p_binom = binom_two_sided_p(oos_hits, oos_tot, 0.5) if oos_tot else None

            # tradable OOS expectancy in the IS-chosen side
            rs = []
            for k in range(len(b["oos_idx"])):
                i = b["oos_idx"][k]
                if i >= n - 1:
                    continue
                r = simulate_trade(i, side, b["oos_lo"][k], b["oos_hi"][k],
                                   o, h, l, c, cost_price, point, max_hold)
                if r is not None:
                    rs.append(r)
            rs_a = np.array(rs) if rs else np.array([])
            entry = {
                "side": "UP" if side > 0 else "DOWN",
                "is_n": b["is_tot"],
                "is_p_up": round(is_p_up, 4),
                "oos_n": oos_tot,
                "oos_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
                "oos_p_binom": round(p_binom, 5) if p_binom is not None else None,
                "trade_n": int(rs_a.size),
                "avg_R": round(float(rs_a.mean()), 4) if rs_a.size else None,
                "win_rate": round(float((rs_a > 0).mean()) * 100, 2) if rs_a.size else None,
                "small_sample": oos_tot < MIN_OOS,
            }
            # bootstrap CI of avg_R + random baseline ONLY for promising cells
            # (>= MIN_OOS and a positive avg_R) — that is where significance
            # actually decides the verdict.
            if (rs_a.size >= MIN_OOS and entry["avg_R"] is not None
                    and entry["avg_R"] > 0):
                lo, hi, ple0 = _bootstrap_avgR(rs_a)
                entry["ci95_lo"], entry["ci95_hi"], entry["p_avgR_le_0"] = lo, hi, ple0
                entry["avgR_significant"] = bool(ple0 is not None and ple0 < ALPHA)
                base = random_baseline_avgR(
                    b["oos_idx"], b["oos_lo"], b["oos_hi"], o, h, l, c,
                    cost_price, point, max_hold)
                if base is not None:
                    entry["rand_avg_R"], entry["rand_ci95_lo"], \
                        entry["rand_ci95_hi"], entry["rand_p_le_0"] = base
                    entry["beats_random"] = bool(
                        entry["avg_R"] > entry["rand_ci95_hi"])
            results[key][name] = entry

    return results, diag


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_results = {}
    # collected rows for ranking/verdict
    dir_rows = []     # directional-edge candidates (hit>50%)
    trade_rows = []   # tradable-edge candidates (avg_R>0)
    # FULL p-value populations — the honest denominators for FDR control.
    all_dir_p = []        # every adequately-sampled class's binomial p
    all_trade_avgR = []   # every adequately-sampled class's tradable avg_R

    for sym in SYMBOLS:
        for tf in TFS:
            try:
                res, diag = run_one(sym, tf)
            except Exception as exc:
                print(f"[ERR] {sym} {tf}: {exc}")
                continue
            all_results[f"{sym}_{tf}"] = {"diag": diag, "seq2": res["seq2"],
                                          "seq3": res["seq3"]}
            for seqkey in ("seq2", "seq3"):
                for name, e in res[seqkey].items():
                    base = {"symbol": sym, "tf": tf, "seq_len": seqkey,
                            "pattern": name, **e}
                    # FULL populations (both directions of deviation) for FDR
                    if e["oos_n"] >= MIN_OOS and e["oos_p_binom"] is not None:
                        all_dir_p.append(e["oos_p_binom"])
                    if e["trade_n"] >= MIN_OOS and e["avg_R"] is not None:
                        all_trade_avgR.append(e["avg_R"])
                    # directional candidate: enough OOS + significant binom + >50%
                    if (e["oos_n"] >= MIN_OOS and e["oos_p_binom"] is not None
                            and e["oos_hit_rate"] is not None
                            and e["oos_hit_rate"] > 0.5):
                        dir_rows.append(base)
                    # tradable candidate: positive cost-net avg_R, enough events
                    if (e["trade_n"] >= MIN_OOS and e["avg_R"] is not None
                            and e["avg_R"] > 0):
                        trade_rows.append(base)

    # ---- print: data summary ----
    print("=" * 108)
    print('NEXT-CANDLE LAB — "وش راح يصير بعدها": does candle SHAPE predict the NEXT candle?')
    print("Encoded classes:", ", ".join(CLASSES))
    print("Edge #1: OOS next-candle directional hit-rate vs 50% (exact binomial). "
          "Side frozen from IS.")
    print("Edge #2: OOS cost-net 1-bar scalp avg_R (enter@close, SL@seq-extreme, "
          "TP=2R) vs random baseline.")
    print(f"Split {int(IS_FRAC*100)}/{100-int(IS_FRAC*100)} by time; report OOS only; "
          f">= {MIN_OOS} OOS events required (else small-sample).")
    print("=" * 108)

    # ---- DIRECTIONAL ranking ----
    print("\n[ EDGE #1 — DIRECTIONAL ] top OOS classes with hit-rate > 50% AND "
          f"binomial p < {ALPHA} (n>={MIN_OOS}):")
    sig_dir = [r for r in dir_rows if r["oos_p_binom"] < ALPHA]
    if not sig_dir:
        print("  NONE. No shape-sequence beats a coin flip on next-candle "
              "direction at p<0.05 with adequate sample.")
    else:
        sig_dir.sort(key=lambda r: (-r["oos_hit_rate"], r["oos_p_binom"]))
        hdr = (f"  {'SYM':8} {'TF':4} {'LEN':5} {'PATTERN':34} {'SIDE':4} "
               f"{'OOSn':>5} {'HIT%':>6} {'p':>8}")
        print(hdr)
        print("  " + "-" * 104)
        for r in sig_dir[:30]:
            print(f"  {r['symbol']:8} {r['tf']:4} {r['seq_len']:5} {r['pattern'][:34]:34} "
                  f"{r['side']:4} {r['oos_n']:>5} {r['oos_hit_rate']*100:>6.2f} "
                  f"{r['oos_p_binom']:>8.5f}")
    # also show the best raw hit-rates even if not significant, for honesty
    print("\n  (context) best raw OOS hit-rates regardless of significance (n>=%d):" % MIN_OOS)
    dir_rows.sort(key=lambda r: -r["oos_hit_rate"])
    for r in dir_rows[:10]:
        tag = "SIG" if r["oos_p_binom"] < ALPHA else "ns"
        print(f"    {r['symbol']:8} {r['tf']:4} {r['seq_len']:5} {r['pattern'][:30]:30} "
              f"{r['side']:4} n={r['oos_n']:>5} hit={r['oos_hit_rate']*100:5.2f}% "
              f"p={r['oos_p_binom']:.4f} [{tag}]")

    # ---- TRADABLE ranking ----
    print("\n[ EDGE #2 — TRADABLE, cost-net ] OOS classes with avg_R>0 (n>=%d), "
          "with bootstrap + random baseline:" % MIN_OOS)
    real_trade = [r for r in trade_rows
                  if r.get("avgR_significant") and r.get("beats_random")]
    if not trade_rows:
        print("  NONE positive after cost.")
    else:
        trade_rows.sort(key=lambda r: -(r["avg_R"] or -9))
        hdr = (f"  {'SYM':8} {'TF':4} {'LEN':5} {'PATTERN':30} {'SIDE':4} "
               f"{'n':>5} {'avgR':>7} {'WIN%':>6} {'CI95':>18} {'pR<=0':>7} "
               f"{'randHi':>7} {'BEATS?':>7}")
        print(hdr)
        print("  " + "-" * 118)
        for r in trade_rows[:30]:
            ci = (f"[{r.get('ci95_lo')},{r.get('ci95_hi')}]"
                  if r.get("ci95_lo") is not None else "-")
            randhi = r.get("rand_ci95_hi")
            randhi_s = f"{randhi:+.3f}" if randhi is not None else "-"
            beats = "YES" if r.get("beats_random") else ("no" if "beats_random" in r else "-")
            sig = "*" if r.get("avgR_significant") else ""
            print(f"  {r['symbol']:8} {r['tf']:4} {r['seq_len']:5} {r['pattern'][:30]:30} "
                  f"{r['side']:4} {r['trade_n']:>5} {r['avg_R']:>+7.3f}{sig} "
                  f"{(r['win_rate'] or 0):>6.1f} {ci:>18} "
                  f"{str(r.get('p_avgR_le_0','-')):>7} {randhi_s:>7} {beats:>7}")

    # ---- MULTIPLE-TESTING CORRECTION (the deciding honesty check) ----
    # We tested THOUSANDS of shape classes. At alpha=0.05 we EXPECT ~alpha*m
    # false positives by pure chance. A raw "p<0.05" or a positive bootstrap is
    # meaningless without correcting for how many hypotheses were screened.
    m_dir = len(all_dir_p)
    exp_fp = ALPHA * m_dir
    obs_sig = sum(1 for p in all_dir_p if p < ALPHA)
    bh_dir = benjamini_hochberg(all_dir_p, ALPHA)
    bonf_dir = sum(1 for p in all_dir_p if p < ALPHA / max(m_dir, 1))

    # For the tradable side, the honest p-population = bootstrap p for the cells
    # we bootstrapped (positive avg_R), PADDED with p=1.0 for every other tested
    # cell we did NOT bootstrap (they had avg_R<=0 — definitionally "no edge").
    boot_ps = [r["p_avgR_le_0"] for r in trade_rows
               if r.get("p_avgR_le_0") is not None]
    m_trade = len(all_trade_avgR)
    pad = [1.0] * max(0, m_trade - len(boot_ps))
    bh_trade = benjamini_hochberg(boot_ps + pad, ALPHA)

    # ---- VERDICT ----
    print("\n" + "=" * 108)
    print("VERDICT")
    print("-" * 108)
    print("  MULTIPLE-TESTING CORRECTION (we screened thousands of classes):")
    print(f"    DIRECTIONAL: {m_dir} classes tested; expected false positives at "
          f"p<{ALPHA} = {exp_fp:.0f}; observed p<{ALPHA} = {obs_sig}.")
    print(f"      -> survive Benjamini-Hochberg FDR {ALPHA:.0%}: {bh_dir};  "
          f"survive Bonferroni: {bonf_dir}")
    print(f"    TRADABLE: {m_trade} classes tested; "
          f"survive BH-FDR on bootstrap p (padded): {bh_trade}")
    print()
    print(f"  Raw directional cells (hit% > 50, binomial p<{ALPHA}, n>={MIN_OOS}): "
          f"{len(sig_dir)}  [UNCORRECTED]")
    print(f"  Raw tradable cells (cost-net avg_R>0, bootstrap-sig AND beats "
          f"random CI): {len(real_trade)}  [UNCORRECTED]")
    if bh_dir == 0 and bh_trade == 0:
        print("  >>> After multiple-testing correction: ZERO directional and ZERO "
              "tradable edges survive.")
        print("  >>> Observed 'significant' count is at/below chance expectation "
              "=> all apparent edges are data-dredging noise. VERDICT: NO_EDGE.")
    elif real_trade:
        print("  >>> Candidate tradable edges (still verify FDR survival above):")
        for r in sorted(real_trade, key=lambda r: -(r["avg_R"] or -9)):
            print(f"      {r['symbol']} {r['tf']} {r['seq_len']} {r['pattern']} "
                  f"side={r['side']} avg_R={r['avg_R']:+.3f} n={r['trade_n']} "
                  f"(rand CI hi {r.get('rand_ci95_hi'):+.3f})")
    else:
        print("  >>> NO tradable edge survives cost + bootstrap + random baseline.")

    # honest aggregate: how far is the median OOS hit-rate from 50%?
    if dir_rows:
        all_hits = np.array([r["oos_hit_rate"] for r in dir_rows
                             if r["oos_n"] >= MIN_OOS] +
                            # include sub-50 cells too for an unbiased center
                            [])
        # build full distribution (both >50 and <=50) from every class
        full = []
        for key, blob in all_results.items():
            for seqkey in ("seq2", "seq3"):
                for nm, e in blob[seqkey].items():
                    if e["oos_n"] >= MIN_OOS and e["oos_hit_rate"] is not None:
                        full.append(e["oos_hit_rate"])
        if full:
            full = np.array(full)
            print(f"\n  OOS next-candle hit-rate across ALL {full.size} adequately-"
                  f"sampled classes: median={np.median(full)*100:.2f}%, "
                  f"mean={full.mean()*100:.2f}%, "
                  f"5-95pct=[{np.percentile(full,5)*100:.1f}%, "
                  f"{np.percentile(full,95)*100:.1f}%]")
            print("  (centered on 50% => shapes carry ~no directional information.)")

    # ---- save ----
    outpath = os.path.join(CACHE, "next_candle_lab_results.json")
    payload = {
        "config": {
            "question": "Does recent candle SHAPE predict the NEXT candle direction?",
            "classes": list(CLASSES),
            "encoding": {"doji_body_frac": DOJI_BODY, "big_body_frac": BIG_BODY,
                         "wick_mult": WICK_MULT},
            "IS_FRAC": IS_FRAC, "RR": RR, "MIN_OOS": MIN_OOS,
            "fwd_bars_by_tf": FWD_N,
            "typ_spread_points": TYP_SPREAD_POINTS,
            "side_selection": "IS-chosen, frozen for OOS",
            "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
            "no_lookahead": True,
        },
        "results": all_results,
        "multiple_testing": {
            "directional_classes_tested": m_dir,
            "expected_false_positives_at_alpha": round(exp_fp, 1),
            "observed_p_lt_alpha": obs_sig,
            "survive_benjamini_hochberg_fdr": bh_dir,
            "survive_bonferroni": bonf_dir,
            "tradable_classes_tested": m_trade,
            "tradable_survive_bh_fdr": bh_trade,
            "note": ("With ~%d classes screened, ~%d p<0.05 hits are expected by "
                     "chance. Edges that do not survive FDR are data-dredging "
                     "artifacts, not real predictive structure."
                     % (m_dir, round(exp_fp))),
        },
        "verdict": ("NO_EDGE" if (bh_dir == 0 and bh_trade == 0)
                    else "EDGE_CANDIDATES_PENDING_FDR"),
        "ranking": {
            "directional_significant_UNCORRECTED": sorted(
                sig_dir, key=lambda r: (-r["oos_hit_rate"], r["oos_p_binom"]))[:50],
            "tradable_positive_UNCORRECTED": sorted(
                trade_rows, key=lambda r: -(r["avg_R"] or -9))[:50],
            "tradable_real_edges_UNCORRECTED": real_trade,
        },
    }
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nRaw results saved -> {outpath}")
    return all_results, sig_dir, real_trade


if __name__ == "__main__":
    main()
