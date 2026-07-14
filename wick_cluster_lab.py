"""wick_cluster_lab.py — Does the user's "ذيول" (wick) idea carry OOS edge?

THE IDEA (precisely):
  The user reads repeated WICK REJECTION. A single long wick is noise; a *cluster*
  of consecutive candles each rejecting the SAME side — e.g. several candles in a
  row that each print a long LOWER wick (buyers repeatedly slapping price back up
  off lower prices) — is supposed to mark a level the market refuses to break, and
  price should then move AWAY from the wicks (up, for lower-wick clusters; down,
  for upper-wick clusters). Strongest when the cluster forms AT a local extreme
  and/or a fresh order-block / FVG zone.

WHAT WE DETECT (all close-confirmed at bar i, using ONLY bars <= i):
  A WICK-REJECTION CLUSTER of length k (we test k>=2 and k>=3) =
    k CONSECUTIVE candles ending at bar i, EACH of which has a long wick on the
    SAME side, where "long wick" = that side's wick >= WICK_MULT * |body|
    (WICK_MULT=2.0, the user's "2x body"). All k must reject the same side:
      * LOWER-wick cluster  -> rejection of lower prices -> predicted dir = +1 (up)
      * UPPER-wick cluster  -> rejection of higher prices -> predicted dir = -1 (down)
  NEAR A LOCAL EXTREME (the "AND occurring near a local extreme" clause):
      * lower-wick cluster: the cluster's lowest low is within W bars of being the
        local minimum (i.e. it equals/near the min low over [i-LOOK, i]).
      * upper-wick cluster: cluster's highest high near the local max high.
    We test BOTH: the raw cluster (any location) AND the cluster-at-extreme.
  AT A FRESH OB/FVG ZONE (causal): cluster price span overlaps a still-unmitigated
    order-block or FVG confirmed within ZONE_LOOKBACK bars before i (reusing the
    existing causal detectors in r_native_v2/.../order_blocks.py).

HYPOTHESIS: after such a cluster, price moves in the REJECTION direction (away
from the wicks). Falsifiable null: it's ~50% / avg_R ~ 0 net of cost.

EDGE MEASURED TWO WAYS, OOS ONLY:
  1. forward N-bar directional hit-rate: did close N bars later move in the
     predicted (rejection) direction? (N=30 M5, 20 M15, 12 H1.) Raw gauge, no cost.
  2. TRADABLE expectancy: enter at the cluster's CLOSE (bar i), SL one tick BEYOND
     the cluster extreme (cluster low for longs, cluster high for shorts), TP=2R.
     Walk future bars; first-touch wins; a bar spanning BOTH SL & TP -> SL
     (pessimistic). Realized R is netted of a realistic round-trip cost from meta.

RIGOR:
  * STRICT NO-LOOKAHEAD. A cluster at bar i uses only bars <= i. We act only AFTER
    bar i closes (entry at c[i], outcome simulated on bars > i). Zones consulted
    only if their causal confirm idx < i and they were unmitigated as of i.
  * 67/33 IS/OOS split BY TIME. Report OOS only (IS computed only to prove split).
  * Require >= 40 OOS events (per brief) else label small-sample.
  * BOOTSTRAP baseline: 2000x resample of the cell's per-trade R; if the 95% CI of
    avg-R crosses 0 the cell is NOT an edge. We ALSO bootstrap a same-bar RANDOM
    baseline: at each cluster bar, flip a fair coin for direction and run the exact
    same SL/TP/cost trade — this is the honest "is the *direction* doing anything"
    control (a 2R/pessimistic-tie system is slightly negative by construction, so
    the real question is whether the wick direction beats a coin on the same bars).

DATA: data/lab_cache/<SYM>_<TF>.npz (arrays t,o,h,l,c,v). Falls back to MT5
copy_rates_from_pos if a cache file is missing (initialize once). Cost from
<SYM>_meta.json (point + typical spread per asset class).

RUN:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\wick_cluster_lab.py
Results JSON -> data/lab_cache/wick_cluster_lab_results.json
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
sys.path.insert(0, os.path.join(HERE, "r_native_v2", "runtime", "shared"))

from order_blocks import detect_order_blocks, detect_fvg  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "US30m", "BTCUSDm"]
TFS = ["M5", "M15", "H1"]
IS_FRAC = 0.67
RR = 2.0
WICK_MULT = 2.0           # "long wick" = wick >= 2x body (user's "ذيول 2x")
CLUSTER_LENS = [2, 3]     # test >=2 and >=3 consecutive same-side wicks
MIN_OOS = 40              # brief: >=40 OOS events else small-sample
MAX_HOLD = {"M5": 60, "M15": 40, "H1": 24}   # bar cap before timeout mark-out
FWD_N = {"M5": 30, "M15": 20, "H1": 12}      # forward directional gauge horizon
EXTREME_LOOK = {"M5": 30, "M15": 20, "H1": 12}  # W: bars to define "local extreme"
ZONE_LOOKBACK = {"M5": 200, "M15": 150, "H1": 100}  # fresh-zone window
BOOT_B = 2000             # bootstrap resamples (brief: 2000x)

# Typical round-trip cost in PRICE units, by asset class (brief ranges):
#   gold ~20-30 pts -> use 25 pts * point(0.001) = 0.025
#   FX ~1-2 pips    -> use 1.5 pips ; 1 pip(5-digit) = 10*point
#   US30 ~2-4 pts   -> use 3 pts * point(0.1) = 0.3
#   BTC ~30-60 pts  -> use 45 pts * point(0.01) = 0.45
COST_POINTS = {            # round-trip cost expressed in POINTS of `point`
    "XAUUSDm": 25.0,
    "US30m": 30.0,         # 30 points * 0.1 = 3.0 price  (3 index pts)
    "BTCUSDm": 4500.0,     # 4500 points * 0.01 = 45.0 price (45 USD)
}
COST_PIPS_FX = {"EURUSDm": 1.5, "GBPUSDm": 2.0}  # pips, round-trip-ish


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_bars(sym: str, tf: str):
    path = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(path):
        d = np.load(path)
        return (d["t"].astype(np.int64), d["o"].astype(np.float64),
                d["h"].astype(np.float64), d["l"].astype(np.float64),
                d["c"].astype(np.float64), d["v"].astype(np.float64))
    return _load_bars_mt5(sym, tf)


_MT5_READY = {"init": False}


def _load_bars_mt5(sym: str, tf: str):
    import MetaTrader5 as mt5
    if not _MT5_READY["init"]:
        if not mt5.initialize():
            mt5.initialize()
        _MT5_READY["init"] = True
    tfmap = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    n = {"M5": 40000, "M15": 30000, "H1": 20000}[tf]
    r = mt5.copy_rates_from_pos(sym, tfmap[tf], 0, n)
    if r is None or len(r) == 0:
        raise RuntimeError(f"MT5 copy_rates failed for {sym} {tf}: {mt5.last_error()}")
    return (r["time"].astype(np.int64), r["open"].astype(np.float64),
            r["high"].astype(np.float64), r["low"].astype(np.float64),
            r["close"].astype(np.float64), r["tick_volume"].astype(np.float64))


def load_meta(sym: str) -> dict:
    with open(os.path.join(CACHE, f"{sym}_meta.json"), "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def roundtrip_cost_price(sym: str, meta: dict) -> float:
    point = float(meta["point"])
    if sym in COST_PIPS_FX:
        pip = 10.0 * point
        return COST_PIPS_FX[sym] * pip
    return COST_POINTS.get(sym, 20.0) * point


# ---------------------------------------------------------------------------
# Wick-rejection cluster detection (causal). Returns list of clusters, each:
#   (i, direction, cluster_lo, cluster_hi, k, at_extreme)
# i = last bar of the cluster (confirmation bar, entry bar). direction = +1 for a
# lower-wick cluster (predict UP), -1 for an upper-wick cluster (predict DOWN).
# ---------------------------------------------------------------------------
def _wick_side(o: float, h: float, l: float, c: float, wick_mult: float) -> int:
    """Classify a single candle's dominant long wick.
    Returns +1 if it has a long LOWER wick (lower >= wick_mult*body and lower is
    the bigger wick), -1 if a long UPPER wick, 0 otherwise. Body uses |c-o|; a
    near-doji (body ~ 0) is treated with a tiny floor so a huge wick still counts.
    """
    body = abs(c - o)
    rng = h - l
    if rng <= 0:
        return 0
    upper = h - max(o, c)
    lower = min(o, c) - l
    # floor body so a doji with a giant single wick still qualifies as rejection,
    # but require the long wick to clearly dominate the candle range.
    body_eff = max(body, 1e-12)
    long_lower = lower >= wick_mult * body_eff and lower >= 0.5 * rng and lower > upper
    long_upper = upper >= wick_mult * body_eff and upper >= 0.5 * rng and upper > lower
    if long_lower:
        return +1
    if long_upper:
        return -1
    return 0


def detect_wick_clusters(o, h, l, c, k_min: int, wick_mult: float,
                         extreme_look: int) -> List[Tuple[int, int, float, float, int, bool]]:
    n = c.size
    side = np.zeros(n, dtype=np.int8)
    for i in range(n):
        side[i] = _wick_side(o[i], h[i], l[i], c[i], wick_mult)

    out = []
    i = 1
    # find maximal runs of identical non-zero side; emit a cluster at the END of
    # each run once it reaches length >= k_min. We emit ONLY the confirmation bar
    # at run length == k_min (first qualifying bar) to avoid heavy overlap; a
    # longer run thus produces one event at its k_min-th bar. (Tested both >=2,>=3
    # by calling with different k_min.)
    run_start = 0
    while i < n:
        if side[i] != 0 and side[i] == side[i - 1]:
            run_len = i - run_start + 1
        else:
            run_start = i
            run_len = 1
        if side[i] != 0 and run_len == k_min:
            direction = int(side[i])
            seg_lo = float(np.min(l[run_start:i + 1]))
            seg_hi = float(np.max(h[run_start:i + 1]))
            at_ext = _near_local_extreme(i, direction, h, l, seg_lo, seg_hi, extreme_look)
            out.append((i, direction, seg_lo, seg_hi, k_min, at_ext))
        i += 1
    return out


def _near_local_extreme(i: int, direction: int, h, l, seg_lo: float, seg_hi: float,
                        look: int) -> bool:
    """Causal: is the cluster sitting at a local extreme of the last `look` bars
    (inclusive, <= i)? lower-wick cluster -> cluster low ~ the window MIN low;
    upper-wick cluster -> cluster high ~ the window MAX high. 'Near' = the extreme
    sits within the cluster's own span (tolerant: cluster makes the extreme)."""
    lo_bound = max(0, i - look)
    if direction > 0:
        wmin = float(np.min(l[lo_bound:i + 1]))
        return seg_lo <= wmin + 1e-12     # cluster low IS (or ties) the window low
    wmax = float(np.max(h[lo_bound:i + 1]))
    return seg_hi >= wmax - 1e-12


# ---------------------------------------------------------------------------
# Fresh-zone confluence (causal) — identical discipline to candle_lab.
# ---------------------------------------------------------------------------
def build_zones(t, o, h, l, c):
    rates = {"time": t, "open": o, "high": h, "low": l, "close": c}
    obs = detect_order_blocks(rates, swing=5)
    fvg = detect_fvg(rates)
    zones = [(int(z["idx"]), float(z["lo"]), float(z["hi"])) for z in obs + fvg]
    zones.sort(key=lambda x: x[0])
    return zones


def _zone_touched_before(zlo, zhi, conf_idx, i, h, l) -> bool:
    for j in range(conf_idx + 1, i):
        if l[j] <= zhi and h[j] >= zlo:
            return True
    return False


def at_zone(i: int, plo: float, phi: float, zones, zidx_arr, lookback, h, l) -> bool:
    import bisect
    cut = bisect.bisect_right(zidx_arr, i)
    lo_bound = bisect.bisect_left(zidx_arr, i - lookback)
    for k in range(lo_bound, cut):
        conf_idx, zlo, zhi = zones[k]
        if conf_idx >= i:
            continue
        if plo <= zhi and phi >= zlo:
            if not _zone_touched_before(zlo, zhi, conf_idx, i, h, l):
                return True
    return False


# ---------------------------------------------------------------------------
# Trade simulation — enter at cluster close, SL beyond cluster extreme, TP=2R.
# ---------------------------------------------------------------------------
def simulate_trade(i: int, direction: int, seg_lo: float, seg_hi: float,
                   o, h, l, c, cost_price: float, point: float,
                   max_hold: int) -> Optional[float]:
    n = c.size
    entry = c[i]
    pad = point
    if direction > 0:
        sl = seg_lo - pad
        risk = entry - sl
        if risk <= 0:
            return None
        tp = entry + RR * risk
    else:
        sl = seg_hi + pad
        risk = sl - entry
        if risk <= 0:
            return None
        tp = entry - RR * risk

    end = min(n, i + 1 + max_hold)
    for j in range(i + 1, end):
        hit_sl = (l[j] <= sl) if direction > 0 else (h[j] >= sl)
        hit_tp = (h[j] >= tp) if direction > 0 else (l[j] <= tp)
        if hit_sl and hit_tp:
            return -1.0 - cost_price / risk   # pessimistic tie -> SL
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    last = c[end - 1]
    pnl_price = (last - entry) if direction > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


def fwd_hit(i: int, direction: int, c, fwd_n: int) -> Optional[int]:
    n = c.size
    j = i + fwd_n
    if j >= n:
        return None
    moved = c[j] - c[i]
    if moved == 0:
        return 0
    return int((moved > 0) == (direction > 0))


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------
def _bootstrap_mean(rs_a: np.ndarray, B: int = BOOT_B, seed: int = 1):
    """95% CI of the mean R + one-sided p(mean<=0) via iid bootstrap."""
    n = rs_a.size
    if n < 5:
        return None, None, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    means = rs_a[idx].mean(axis=1)
    return (round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4),
            round(float((means <= 0).mean()), 4))


def _random_baseline(cluster_bars: List[Tuple], o, h, l, c, cost_price, point,
                     max_hold, B: int = BOOT_B, seed: int = 7):
    """Same-bar RANDOM-direction control. For each cluster bar, on each of B
    bootstrap passes, flip a fair coin for the trade direction (SL beyond the
    chosen-side extreme, TP=2R) and run the identical cost-net sim. Returns the
    distribution of avg-R across passes -> (mean, ci_lo, ci_hi). This is the
    honest 'does the wick DIRECTION beat a coin on these exact setups' baseline,
    holding the SL/TP geometry and bar selection fixed."""
    if not cluster_bars:
        return None
    rng = np.random.default_rng(seed)
    # Precompute both-direction outcomes once per bar (cheap vs B re-sims).
    long_R, short_R = [], []
    for (i, _d, seg_lo, seg_hi, _k, _ext) in cluster_bars:
        rl = simulate_trade(i, +1, seg_lo, seg_hi, o, h, l, c, cost_price, point, max_hold)
        rs = simulate_trade(i, -1, seg_lo, seg_hi, o, h, l, c, cost_price, point, max_hold)
        long_R.append(rl)
        short_R.append(rs)
    long_R = np.array([x if x is not None else np.nan for x in long_R])
    short_R = np.array([x if x is not None else np.nan for x in short_R])
    valid = ~(np.isnan(long_R) | np.isnan(short_R))
    long_R, short_R = long_R[valid], short_R[valid]
    m = long_R.size
    if m < 5:
        return None
    means = np.empty(B)
    for b in range(B):
        coin = rng.integers(0, 2, size=m).astype(bool)
        picked = np.where(coin, long_R, short_R)
        means[b] = picked.mean()
    return {
        "n": int(m),
        "rand_avg_R": round(float(means.mean()), 4),
        "rand_ci95_lo": round(float(np.percentile(means, 2.5)), 4),
        "rand_ci95_hi": round(float(np.percentile(means, 97.5)), 4),
    }


def summarize(rs: List, hits: List, boot: bool = False) -> dict:
    rs = [r for r in rs if r is not None]
    hits = [hh for hh in hits if hh is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0}
    rs_a = np.array(rs, dtype=np.float64)
    wins = int((rs_a > 0).sum())
    out = {
        "n": n,
        "win_rate": round(100.0 * wins / n, 2),
        "avg_R": round(float(rs_a.mean()), 4),
        "total_R": round(float(rs_a.sum()), 3),
        "fwd_hit_rate": round(100.0 * float(np.mean(hits)), 2) if hits else None,
        "fwd_n": len(hits),
    }
    if boot and n >= MIN_OOS:
        lo, hi, p = _bootstrap_mean(rs_a)
        out["ci95_lo"], out["ci95_hi"], out["p_avgR_le_0"] = lo, hi, p
        # edge requires positive avg_R AND a CI that does not cross 0
        out["significant"] = bool(lo is not None and lo > 0)
    return out


# ---------------------------------------------------------------------------
# One (symbol, tf, k)
# ---------------------------------------------------------------------------
def run_one(sym, tf, k_min):
    t, o, h, l, c, v = load_bars(sym, tf)
    meta = load_meta(sym)
    point = float(meta["point"])
    cost_price = roundtrip_cost_price(sym, meta)
    n = c.size
    split = int(n * IS_FRAC)
    max_hold = MAX_HOLD[tf]
    fwd_n = FWD_N[tf]
    ext_look = EXTREME_LOOK[tf]

    zones = build_zones(t, o, h, l, c)
    zidx_arr = [z[0] for z in zones]
    lookback = ZONE_LOOKBACK.get(tf, 150)

    clusters = detect_wick_clusters(o, h, l, c, k_min, WICK_MULT, ext_look)

    # variants: any-location, at-local-extreme, at-fresh-zone
    buckets = {
        ("any", "IS"): {"r": [], "f": []}, ("any", "OOS"): {"r": [], "f": [], "bars": []},
        ("at_extreme", "IS"): {"r": [], "f": []}, ("at_extreme", "OOS"): {"r": [], "f": [], "bars": []},
        ("at_zone", "IS"): {"r": [], "f": []}, ("at_zone", "OOS"): {"r": [], "f": [], "bars": []},
    }
    n_lower = n_upper = 0
    for (i, direction, seg_lo, seg_hi, k, at_ext) in clusters:
        if i >= n - 2:
            continue
        if direction > 0:
            n_lower += 1
        else:
            n_upper += 1
        r = simulate_trade(i, direction, seg_lo, seg_hi, o, h, l, c, cost_price, point, max_hold)
        f = fwd_hit(i, direction, c, fwd_n)
        phase = "IS" if i < split else "OOS"
        buckets[("any", phase)]["r"].append(r)
        buckets[("any", phase)]["f"].append(f)
        if phase == "OOS":
            buckets[("any", "OOS")]["bars"].append((i, direction, seg_lo, seg_hi, k, at_ext))
        if at_ext:
            buckets[("at_extreme", phase)]["r"].append(r)
            buckets[("at_extreme", phase)]["f"].append(f)
            if phase == "OOS":
                buckets[("at_extreme", "OOS")]["bars"].append((i, direction, seg_lo, seg_hi, k, at_ext))
        if at_zone(i, seg_lo, seg_hi, zones, zidx_arr, lookback, h, l):
            buckets[("at_zone", phase)]["r"].append(r)
            buckets[("at_zone", phase)]["f"].append(f)
            if phase == "OOS":
                buckets[("at_zone", "OOS")]["bars"].append((i, direction, seg_lo, seg_hi, k, at_ext))

    res = {}
    for variant in ("any", "at_extreme", "at_zone"):
        res[variant] = {}
        for phase in ("IS", "OOS"):
            d = buckets[(variant, phase)]
            res[variant][phase] = summarize(d["r"], d["f"], boot=(phase == "OOS"))
        # same-bar random-direction control on the OOS cluster bars
        oos_bars = buckets[(variant, "OOS")]["bars"]
        if res[variant]["OOS"].get("n", 0) >= MIN_OOS:
            rb = _random_baseline(oos_bars, o, h, l, c, cost_price, point, max_hold)
            if rb:
                res[variant]["OOS"]["random_baseline"] = rb
                wick = res[variant]["OOS"].get("avg_R")
                if wick is not None:
                    res[variant]["OOS"]["beats_random"] = bool(
                        wick > rb["rand_ci95_hi"])
    meta_out = {"n_bars": n, "split_idx": split, "cost_price": round(cost_price, 6),
                "n_zones": len(zones), "n_clusters": len(clusters),
                "n_lower_wick": n_lower, "n_upper_wick": n_upper}
    return res, meta_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_results = {}
    rows = []
    for sym in SYMBOLS:
        for tf in TFS:
            for k in CLUSTER_LENS:
                try:
                    res, meta = run_one(sym, tf, k)
                except Exception as exc:
                    print(f"[ERR] {sym} {tf} k>={k}: {exc}")
                    continue
                all_results[f"{sym}_{tf}_k{k}"] = {"meta": meta, "variants": res}
                for variant, phases in res.items():
                    oos = phases.get("OOS", {})
                    rb = oos.get("random_baseline", {})
                    rows.append({
                        "symbol": sym, "tf": tf, "k": k, "variant": variant,
                        "n": oos.get("n", 0),
                        "win_rate": oos.get("win_rate"),
                        "avg_R": oos.get("avg_R"),
                        "fwd_hit": oos.get("fwd_hit_rate"),
                        "ci95_lo": oos.get("ci95_lo"), "ci95_hi": oos.get("ci95_hi"),
                        "p_avgR_le_0": oos.get("p_avgR_le_0"),
                        "significant": oos.get("significant"),
                        "rand_avg_R": rb.get("rand_avg_R"),
                        "rand_ci_hi": rb.get("rand_ci95_hi"),
                        "beats_random": oos.get("beats_random"),
                    })

    # ---- report ----
    print("=" * 118)
    print("WICK-CLUSTER LAB — user's 'ذيول' idea. OOS only (33% out-of-sample by time).")
    print("Cluster = k consecutive candles, EACH wick(same side) >= 2x body. dir = AWAY from the wicks (rejection).")
    print("Tradable: enter@close, SL beyond cluster extreme, TP=2R, cost-net, pessimistic ties.")
    print("EDGE requires: n>=40 AND avg_R>0 AND bootstrap 95% CI_lo>0 AND wick avg_R > random-direction CI_hi.")
    print("=" * 118)
    hdr = (f"{'SYM':9} {'TF':4} {'k':>2} {'VARIANT':11} {'N':>5} {'WIN%':>6} "
           f"{'avgR':>8} {'CI_lo':>7} {'CI_hi':>7} {'randR':>7} {'fwd%':>6}  FLAGS")
    print(hdr)
    print("-" * 118)
    for r in sorted(rows, key=lambda x: (x["symbol"], x["tf"], x["k"], x["variant"])):
        nn = r["n"] or 0
        flags = []
        if nn < MIN_OOS:
            flags.append("small-sample")
        if nn >= MIN_OOS and r["avg_R"] is not None and r["avg_R"] > 0 and r.get("significant"):
            flags.append("CI>0")
        if r.get("beats_random"):
            flags.append("BEATS-RAND")
        if (nn >= MIN_OOS and r.get("significant") and r.get("beats_random")):
            flags.append("<<EDGE")
        wr = f"{r['win_rate']:.1f}" if r["win_rate"] is not None else "-"
        ar = f"{r['avg_R']:+.3f}" if r["avg_R"] is not None else "-"
        clo = f"{r['ci95_lo']:+.3f}" if r["ci95_lo"] is not None else "-"
        chi = f"{r['ci95_hi']:+.3f}" if r["ci95_hi"] is not None else "-"
        rr = f"{r['rand_avg_R']:+.3f}" if r["rand_avg_R"] is not None else "-"
        fw = f"{r['fwd_hit']:.1f}" if r["fwd_hit"] is not None else "-"
        print(f"{r['symbol']:9} {r['tf']:4} {r['k']:>2} {r['variant']:11} {nn:>5} {wr:>6} "
              f"{ar:>8} {clo:>7} {chi:>7} {rr:>7} {fw:>6}  {' '.join(flags)}")

    # ---- verdict scan ----
    print("\n" + "=" * 118)
    qualifying = [r for r in rows if (r["n"] or 0) >= MIN_OOS]
    pos = [r for r in qualifying if r["avg_R"] is not None and r["avg_R"] > 0]
    real_edges = [r for r in qualifying if r.get("significant") and r.get("beats_random")
                  and r["avg_R"] is not None and r["avg_R"] > 0]
    print(f"Cells with >=40 OOS events: {len(qualifying)}   |   positive avg_R: {len(pos)}")
    print(f"Cells where wick beats RANDOM direction AND CI_lo>0 (REAL EDGE): {len(real_edges)}")
    if real_edges:
        for e in sorted(real_edges, key=lambda r: -r["avg_R"]):
            print(f"  >> {e['symbol']} {e['tf']} k>={e['k']} {e['variant']}: avg_R={e['avg_R']:+.3f} "
                  f"WR={e['win_rate']}% n={e['n']} CI=[{e['ci95_lo']},{e['ci95_hi']}] "
                  f"randR={e['rand_avg_R']} (rand_CI_hi={e['rand_ci_hi']}) fwd={e['fwd_hit']}%")
    else:
        print("  >> NONE. No (symbol,tf,k,variant) cell clears all bars -> the wick-cluster")
        print("     direction does NOT beat a coin on its own setups net of cost. NO_EDGE.")

    # forward-hit honesty line: are ANY clusters even >55% directional, ignoring cost?
    print("\nForward directional hit-rate (raw, no cost) — best OOS cells (n>=40):")
    fwd_sorted = sorted([r for r in qualifying if r["fwd_hit"] is not None],
                        key=lambda r: -(r["fwd_hit"] or 0))[:8]
    for r in fwd_sorted:
        print(f"  {r['symbol']} {r['tf']} k>={r['k']} {r['variant']}: fwd_hit={r['fwd_hit']}% "
              f"(n={r['n']}, baseline ~50%)")

    # ---- save ----
    outpath = os.path.join(CACHE, "wick_cluster_lab_results.json")
    payload = {
        "config": {
            "IS_FRAC": IS_FRAC, "RR": RR, "WICK_MULT": WICK_MULT,
            "CLUSTER_LENS": CLUSTER_LENS, "MIN_OOS": MIN_OOS,
            "MAX_HOLD": MAX_HOLD, "FWD_N": FWD_N, "EXTREME_LOOK": EXTREME_LOOK,
            "ZONE_LOOKBACK": ZONE_LOOKBACK, "BOOT_B": BOOT_B,
            "cost_model": "round-trip spread+commission proxy in price units",
            "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
            "edge_rule": "n>=40 AND avg_R>0 AND boot CI_lo>0 AND avg_R>random_dir CI_hi",
            "no_lookahead": True,
        },
        "results": all_results,
        "summary_oos": rows,
        "verdict": {
            "qualifying_cells": len(qualifying),
            "positive_cells": len(pos),
            "real_edge_cells": len(real_edges),
            "edges": [f"{e['symbol']}_{e['tf']}_k{e['k']}_{e['variant']}" for e in real_edges],
        },
    }
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nRaw results saved -> {outpath}")
    return all_results, rows, real_edges


if __name__ == "__main__":
    main()
