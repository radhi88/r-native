"""candle_lab.py — Does any candlestick pattern carry OOS edge? (causal, cost-net)

The user trades off the CANDLES themselves + a bit of RSI. This lab quantifies,
with strict no-lookahead discipline, whether the patterns he reads actually
carry forward edge — standalone, and the high-value variant: ONLY when the
pattern sits at an FVG edge or order-block zone (SMC confluence).

PATTERNS DETECTED (all close-confirmed at bar i, using only bars <= i):
  * ENGULFING (bullish / bearish)            — body engulfs prior body
  * PIN BAR / hammer / shooting-star         — one wick >= 2x body, other small
  * INSIDE-BAR BREAKOUT                       — inside bar then close beyond it
  * 3-BAR REVERSAL                            — down-down-up (bull) / up-up-down (bear)

EDGE MEASURED TWO WAYS, OOS ONLY:
  1. forward N-bar directional hit-rate: did price close in the pattern's
     predicted direction N bars later? (raw, no cost — a sanity gauge)
  2. TRADABLE: enter at the pattern's CLOSE, SL one tick beyond the pattern's
     extreme (low for longs, high for shorts), TP = 2R. Walk bars forward;
     first-touch wins; if a single bar's range spans BOTH SL and TP we assume
     SL first (pessimistic). Realized R is netted of a realistic round-trip
     cost (spread+commission proxy) computed from the symbol meta.

CONFLUENCE VARIANT: re-run the tradable test but keep ONLY pattern occurrences
whose price overlaps an SMC zone (order block OR FVG) that was CONFIRMED at or
before the pattern bar (zone.idx <= i — strictly causal). Compare at-zone edge
vs standalone edge.

RIGOR:
  * NO LOOKAHEAD. Patterns use bars <= i. Zones carry a causal confirmation
    index; we only consult zones with idx <= pattern-bar. Trade outcome walks
    strictly future bars.
  * 67/33 IS/OOS split BY TIME. We report OOS only. (IS is computed too, only
    to confirm the split ran; never reported as the headline.)
  * >= 30 OOS events required, else flagged small-sample.

DATA: read ONLY from data/lab_cache/<SYM>_<TF>.npz (t,o,h,l,c,v) — never imports
MetaTrader5 (avoids terminal contention). Cost from <SYM>_meta.json.

RUN:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\candle_lab.py
Results JSON -> data/lab_cache/candle_lab_results.json
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
sys.path.insert(0, os.path.join(HERE, "r_native_v2", "runtime", "shared"))

# Reuse the existing causal SMC detectors (their idx = causal confirmation bar).
from order_blocks import detect_order_blocks, detect_fvg  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm"]
TFS = ["M5", "M15", "H1"]
IS_FRAC = 0.67          # 67/33 split by time
RR = 2.0                # TP = 2R
FWD_N = 5               # forward bars for the raw hit-rate gauge
MAX_HOLD = 60           # max bars to hold a tradable trade before timeout
MIN_OOS = 30            # below this -> small-sample flag

# typical spread per symbol, in POINTS (price = points * point). Round-trip
# cost proxy = 2 * typical_spread_points * point_value_per_price_unit. We model
# cost directly in price terms: cost_price = 2 * typ_spread_points * point.
# (commission baked into the doubled spread proxy per the task brief.)
TYP_SPREAD_POINTS = {
    "XAUUSDm": 25.0,    # gold ~20-30 points
    "EURUSDm": 1.5,     # FX ~1-2 pips -> 15-20 points at 5-digit; spread in *points*
    "GBPUSDm": 2.0,
}
# NOTE: a "pip" for 5-digit FX = 10 points. The brief says FX ~1-2 pips.
# We express the spread directly in PIPS-as-price below for FX to be honest.
TYP_SPREAD_PIPS_FX = {"EURUSDm": 1.5, "GBPUSDm": 2.0}  # pips round-trip-ish


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_bars(sym: str, tf: str):
    d = np.load(os.path.join(CACHE, f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64),
            d["o"].astype(np.float64), d["h"].astype(np.float64),
            d["l"].astype(np.float64), d["c"].astype(np.float64),
            d["v"].astype(np.float64))


def load_meta(sym: str) -> dict:
    with open(os.path.join(CACHE, f"{sym}_meta.json"), "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def roundtrip_cost_price(sym: str, meta: dict) -> float:
    """Realistic round-trip cost expressed in PRICE units (spread + commission
    proxy = ~2x typical spread). Gold/indices use point*points; FX uses pips."""
    point = float(meta["point"])
    if sym in TYP_SPREAD_PIPS_FX:
        # 1 pip (5-digit FX) = 10 * point. Round trip ~ 2 * spread pips.
        pip = 10.0 * point
        return 2.0 * TYP_SPREAD_PIPS_FX[sym] * pip
    # gold / others: spread already in points
    return 2.0 * TYP_SPREAD_POINTS.get(sym, 20.0) * point


# ---------------------------------------------------------------------------
# RSI (Wilder, causal). rsi[i] uses closes <= i only.
# ---------------------------------------------------------------------------
def rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = close.size
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_g = gain[:period].mean()
    avg_l = loss[:period].mean()
    for i in range(period, n):
        g = gain[i - 1]
        l = loss[i - 1]
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        rs = avg_g / avg_l if avg_l > 0 else np.inf
        rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


# ---------------------------------------------------------------------------
# Pattern detectors — each returns list of (i, direction) where direction is
# +1 (bullish/long) or -1 (bearish/short). Pattern at bar i uses ONLY bars <= i.
# The pattern is CONFIRMED at the close of bar i; a trade can act from bar i's
# close onward (we simulate fills/outcomes on bars > i, plus an entry at i.close).
# ---------------------------------------------------------------------------
def _body(o, c):
    return abs(c - o)


def detect_engulfing(o, h, l, c) -> List[Tuple[int, int]]:
    out = []
    n = c.size
    for i in range(1, n):
        b_prev = _body(o[i - 1], c[i - 1])
        b_cur = _body(o[i], c[i])
        if b_cur <= 0 or b_prev <= 0:
            continue
        # bullish engulfing: prev down, cur up, cur body engulfs prev body
        prev_down = c[i - 1] < o[i - 1]
        cur_up = c[i] > o[i]
        if prev_down and cur_up and c[i] >= o[i - 1] and o[i] <= c[i - 1] and b_cur > b_prev:
            out.append((i, +1))
            continue
        prev_up = c[i - 1] > o[i - 1]
        cur_down = c[i] < o[i]
        if prev_up and cur_down and c[i] <= o[i - 1] and o[i] >= c[i - 1] and b_cur > b_prev:
            out.append((i, -1))
    return out


def detect_pinbar(o, h, l, c, wick_mult: float = 2.0) -> List[Tuple[int, int]]:
    """Hammer (bullish, long lower wick) / shooting-star (bearish, long upper
    wick). One wick >= wick_mult * body; the opposite wick must be small (<=
    body). Body must be non-trivial relative to range to avoid doji noise."""
    out = []
    n = c.size
    for i in range(n):
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        body = _body(o[i], c[i])
        if body <= 0:
            continue
        upper = h[i] - max(o[i], c[i])
        lower = min(o[i], c[i]) - l[i]
        # body should be a real but minority part of the range
        if body > 0.5 * rng:
            continue
        # hammer: long lower wick, small upper wick
        if lower >= wick_mult * body and upper <= body:
            out.append((i, +1))
            continue
        # shooting star: long upper wick, small lower wick
        if upper >= wick_mult * body and lower <= body:
            out.append((i, -1))
    return out


def detect_inside_break(o, h, l, c) -> List[Tuple[int, int]]:
    """Inside bar (bar k fully inside bar k-1) followed by a breakout CLOSE
    beyond the mother bar. Confirmation at the breakout bar i (i = k+1..).
    Causal: only uses bars <= i."""
    out = []
    n = c.size
    for i in range(2, n):
        k = i - 1  # candidate inside bar
        # k must be inside its mother bar k-1
        if not (h[k] <= h[k - 1] and l[k] >= l[k - 1]):
            continue
        mother_hi = h[k - 1]
        mother_lo = l[k - 1]
        # breakout bar i closes beyond the mother bar's range
        if c[i] > mother_hi:
            out.append((i, +1))
        elif c[i] < mother_lo:
            out.append((i, -1))
    return out


def detect_3bar_reversal(o, h, l, c) -> List[Tuple[int, int]]:
    """Classic 3-bar reversal confirmed at bar i.
      bullish: bars i-2,i-1 are down; bar i is up and closes above i-1 high.
      bearish: bars i-2,i-1 are up; bar i is down and closes below i-1 low.
    Causal."""
    out = []
    n = c.size
    for i in range(2, n):
        d2 = c[i - 2] < o[i - 2]
        d1 = c[i - 1] < o[i - 1]
        u2 = c[i - 2] > o[i - 2]
        u1 = c[i - 1] > o[i - 1]
        if d2 and d1 and c[i] > o[i] and c[i] > h[i - 1]:
            out.append((i, +1))
        elif u2 and u1 and c[i] < o[i] and c[i] < l[i - 1]:
            out.append((i, -1))
    return out


PATTERN_FUNCS = {
    "engulfing": detect_engulfing,
    "pinbar": detect_pinbar,
    "inside_break": detect_inside_break,
    "three_bar_rev": detect_3bar_reversal,
}


# ---------------------------------------------------------------------------
# Zone confluence (causal). Build zones once on the full array; each zone has a
# causal confirmation idx. A pattern at bar i is "at zone" if some zone with
# idx <= i overlaps the pattern's relevant price (the pattern extreme & close).
# ---------------------------------------------------------------------------
# A trader's "at an OB/FVG zone" means a FRESH, still-active zone — not any of
# the thousands of stale zones accumulated over 20-40k bars (price overlaps one
# of those almost always, which would make the filter a no-op and the lift
# meaningless). We therefore require, strictly causally:
#   (a) the zone was confirmed within ZONE_LOOKBACK bars before the pattern, and
#   (b) the zone was still UNMITIGATED as of the pattern bar i (no bar strictly
#       between confirm_idx and i has already traded back into it).
ZONE_LOOKBACK = {"M5": 200, "M15": 150, "H1": 100}  # bars of zone freshness


def build_zones(t, o, h, l, c):
    rates = {"time": t, "open": o, "high": h, "low": l, "close": c}
    obs = detect_order_blocks(rates, swing=5)
    fvg = detect_fvg(rates)
    zones = []
    for z in obs + fvg:
        zones.append((int(z["idx"]), float(z["lo"]), float(z["hi"])))
    # sort by confirm idx for fast causal filtering
    zones.sort(key=lambda x: x[0])
    return zones


def _zone_touched_before(zlo, zhi, conf_idx, i, h, l) -> bool:
    """Causal: has any bar in (conf_idx, i) already traded into [zlo,zhi]?
    If so the zone is mitigated/consumed before the pattern -> not 'fresh'."""
    for j in range(conf_idx + 1, i):
        if l[j] <= zhi and h[j] >= zlo:
            return True
    return False


def at_zone(i: int, plo: float, phi: float, zones, zidx_arr, lookback, h, l) -> bool:
    """True if the pattern at bar i sits in a FRESH, still-active OB/FVG zone:
    confirmed within `lookback` bars before i, overlapping the pattern's price
    span [plo,phi], and not yet mitigated before i. Strictly causal."""
    import bisect
    cut = bisect.bisect_right(zidx_arr, i)          # zones confirmed by bar i
    lo_bound = bisect.bisect_left(zidx_arr, i - lookback)  # within lookback
    for k in range(lo_bound, cut):
        conf_idx, zlo, zhi = zones[k]
        if conf_idx >= i:
            continue
        if plo <= zhi and phi >= zlo:               # pattern overlaps zone
            if not _zone_touched_before(zlo, zhi, conf_idx, i, h, l):
                return True
    return False


# ---------------------------------------------------------------------------
# Trade simulation — enter at pattern close, SL beyond pattern extreme, TP=2R.
# First-touch on future bars; bar spanning both -> SL (pessimistic). Net cost.
# Returns realized R (cost-netted) or None if it never resolved (timeout->mark
# to close at horizon, still cost-netted).
# ---------------------------------------------------------------------------
def simulate_trade(i, direction, o, h, l, c, cost_price, point) -> float | None:
    n = c.size
    entry = c[i]
    pad = point  # SL one tick beyond the extreme
    if direction > 0:
        sl = l[i] - pad
        risk = entry - sl
        if risk <= 0:
            return None
        tp = entry + RR * risk
    else:
        sl = h[i] + pad
        risk = sl - entry
        if risk <= 0:
            return None
        tp = entry - RR * risk

    end = min(n, i + 1 + MAX_HOLD)
    for j in range(i + 1, end):
        hit_sl = (l[j] <= sl) if direction > 0 else (h[j] >= sl)
        hit_tp = (h[j] >= tp) if direction > 0 else (l[j] <= tp)
        if hit_sl and hit_tp:
            r = -1.0  # pessimistic tie-break
            return r - cost_price / risk
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    # timeout: mark to last close
    last = c[end - 1]
    pnl_price = (last - entry) if direction > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


def fwd_hit(i, direction, c) -> int | None:
    """Raw directional gauge: did close N bars later move in predicted dir?
    Returns 1 (hit), 0 (miss), or None if no horizon."""
    n = c.size
    j = i + FWD_N
    if j >= n:
        return None
    moved = c[j] - c[i]
    return int((moved > 0) == (direction > 0)) if moved != 0 else 0


# ---------------------------------------------------------------------------
# Aggregation for one (symbol, tf, pattern, variant)
# ---------------------------------------------------------------------------
def _bootstrap(rs_a: np.ndarray, B: int = 5000, seed: int = 1):
    """Stationary bootstrap of the mean R vs zero. Returns (ci_lo, ci_hi,
    p_le_0) — p_le_0 is the share of resampled means that are <= 0 (a one-sided
    'no edge' p-value). Edge requires p_le_0 small (< ~0.05)."""
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


def summarize(rs: List[float], hits: List[int], boot: bool = False) -> dict:
    rs = [r for r in rs if r is not None]
    hits = [hh for hh in hits if hh is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0}
    rs_a = np.array(rs)
    wins = int((rs_a > 0).sum())
    out = {
        "n": n,
        "win_rate": round(100.0 * wins / n, 2),
        "avg_R": round(float(rs_a.mean()), 4),
        "total_R": round(float(rs_a.sum()), 3),
        "expectancy_R": round(float(rs_a.mean()), 4),
        "fwd_hit_rate": round(100.0 * float(np.mean(hits)), 2) if hits else None,
        "fwd_n": len(hits),
    }
    # Only bootstrap OOS cells that look like an edge (avg_R>0) AND have >=MIN_OOS
    # events — that's where significance actually matters for the verdict.
    if boot and n >= MIN_OOS and out["avg_R"] > 0:
        lo, hi, p = _bootstrap(rs_a)
        out["ci95_lo"], out["ci95_hi"], out["p_avgR_le_0"] = lo, hi, p
        out["significant"] = bool(p is not None and p < 0.05)
    return out


def run_one(sym, tf):
    t, o, h, l, c, v = load_bars(sym, tf)
    meta = load_meta(sym)
    point = float(meta["point"])
    cost_price = roundtrip_cost_price(sym, meta)
    n = c.size
    split = int(n * IS_FRAC)

    zones = build_zones(t, o, h, l, c)
    zidx_arr = [z[0] for z in zones]
    lookback = ZONE_LOOKBACK.get(tf, 150)

    out = {}
    for pname, func in PATTERN_FUNCS.items():
        if pname == "pinbar":
            occ = func(o, h, l, c, wick_mult=2.0)
        else:
            occ = func(o, h, l, c)

        # buckets
        buckets = {
            ("standalone", "IS"): {"r": [], "f": []},
            ("standalone", "OOS"): {"r": [], "f": []},
            ("at_zone", "IS"): {"r": [], "f": []},
            ("at_zone", "OOS"): {"r": [], "f": []},
        }
        for (i, direction) in occ:
            # leave room for a forward window / hold; skip the very tail so the
            # trade can resolve. (still strictly causal — just drops unresolved.)
            if i >= n - 2:
                continue
            r = simulate_trade(i, direction, o, h, l, c, cost_price, point)
            f = fwd_hit(i, direction, c)
            phase = "IS" if i < split else "OOS"
            buckets[("standalone", phase)]["r"].append(r)
            buckets[("standalone", phase)]["f"].append(f)
            # confluence: pattern price span = [low,high] of pattern bar; only
            # FRESH unmitigated zones within lookback count (causal).
            if at_zone(i, l[i], h[i], zones, zidx_arr, lookback, h, l):
                buckets[("at_zone", phase)]["r"].append(r)
                buckets[("at_zone", phase)]["f"].append(f)

        res = {}
        for (variant, phase), d in buckets.items():
            res.setdefault(variant, {})[phase] = summarize(
                d["r"], d["f"], boot=(phase == "OOS"))
        out[pname] = res

    return out, {"n_bars": n, "split_idx": split, "cost_price": cost_price,
                 "n_zones": len(zones)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_results = {}
    summary_rows = []  # for the printed table + verdict
    for sym in SYMBOLS:
        for tf in TFS:
            try:
                res, meta = run_one(sym, tf)
            except Exception as exc:
                print(f"[ERR] {sym} {tf}: {exc}")
                continue
            all_results[f"{sym}_{tf}"] = {"meta": meta, "patterns": res}
            for pname, variants in res.items():
                for variant, phases in variants.items():
                    oos = phases.get("OOS", {})
                    summary_rows.append({
                        "symbol": sym, "tf": tf, "pattern": pname,
                        "variant": variant,
                        "n": oos.get("n", 0),
                        "win_rate": oos.get("win_rate"),
                        "avg_R": oos.get("avg_R"),
                        "fwd_hit": oos.get("fwd_hit_rate"),
                        "ci95_lo": oos.get("ci95_lo"),
                        "ci95_hi": oos.get("ci95_hi"),
                        "p_avgR_le_0": oos.get("p_avgR_le_0"),
                        "significant": oos.get("significant"),
                    })

    # ---- print report ----
    print("=" * 100)
    print("CANDLE LAB — OOS (33% out-of-sample, by time). Tradable: enter@close, "
          "SL@extreme, TP=2R, cost-net.")
    print("Baselines: random entry expectancy at 2R with ~33% breakeven WR -> "
          "avg_R ~ 0 (edge => avg_R > 0 AND n>=30).")
    print("=" * 100)
    hdr = f"{'SYMBOL':9} {'TF':4} {'PATTERN':14} {'VARIANT':11} {'N':>5} {'WIN%':>6} {'avgR':>8} {'fwd%':>6}  FLAG"
    print(hdr)
    print("-" * 100)
    for row in sorted(summary_rows, key=lambda r: (r["symbol"], r["tf"], r["pattern"], r["variant"])):
        n = row["n"] or 0
        flag = "" if n >= MIN_OOS else "small-sample"
        edge = ""
        if n >= MIN_OOS and row["avg_R"] is not None and row["avg_R"] > 0.05:
            edge = "<<EDGE?"
        wr = f"{row['win_rate']:.1f}" if row["win_rate"] is not None else "-"
        ar = f"{row['avg_R']:+.3f}" if row["avg_R"] is not None else "-"
        fw = f"{row['fwd_hit']:.1f}" if row["fwd_hit"] is not None else "-"
        print(f"{row['symbol']:9} {row['tf']:4} {row['pattern']:14} {row['variant']:11} "
              f"{n:>5} {wr:>6} {ar:>8} {fw:>6}  {flag}{edge}")

    # ---- verdict scan ----
    print("\n" + "=" * 100)
    print("POSITIVE-EXPECTANCY OOS CELLS (n>=30, cost-net, avg_R>+0.05) + bootstrap:")
    pos = [r for r in summary_rows
           if (r["n"] or 0) >= MIN_OOS and r["avg_R"] is not None and r["avg_R"] > 0.05]
    sig_edges = []
    if not pos:
        print("  NONE positive.")
    else:
        for e in sorted(pos, key=lambda r: -r["avg_R"]):
            print(f"  {e['symbol']} {e['tf']} {e['pattern']}/{e['variant']}: "
                  f"avg_R={e['avg_R']:+.3f} WR={e['win_rate']}% n={e['n']} "
                  f"CI95=[{e.get('ci95_lo')},{e.get('ci95_hi')}] "
                  f"p(<=0)={e.get('p_avgR_le_0')} "
                  f"{'SIGNIFICANT' if e.get('significant') else 'NOT-SIG (CI straddles 0)'}")
            if e.get("significant"):
                sig_edges.append(e)
    print("\n  >>> STATISTICALLY SIGNIFICANT edges (p(avg_R<=0) < 0.05): "
          f"{len(sig_edges)}")
    if not sig_edges:
        print("  >>> NONE. Every positive cell's 95% CI straddles zero -> NO_EDGE.")

    # confluence comparison: at_zone vs standalone where both have n>=30
    print("\nCONFLUENCE LIFT (at_zone avg_R - standalone avg_R, both n>=30 OOS):")
    lift_rows = []
    for sym in SYMBOLS:
        for tf in TFS:
            key = f"{sym}_{tf}"
            if key not in all_results:
                continue
            pats = all_results[key]["patterns"]
            for pname, variants in pats.items():
                sa = variants.get("standalone", {}).get("OOS", {})
                az = variants.get("at_zone", {}).get("OOS", {})
                if (sa.get("n", 0) >= MIN_OOS and az.get("n", 0) >= MIN_OOS
                        and sa.get("avg_R") is not None and az.get("avg_R") is not None):
                    lift = az["avg_R"] - sa["avg_R"]
                    lift_rows.append((sym, tf, pname, sa["avg_R"], az["avg_R"], lift, az["n"]))
    if not lift_rows:
        print("  (no pattern had >=30 OOS at-zone events to compare — confluence is "
              "RARE; treat as small-sample.)")
    else:
        for (sym, tf, pname, sar, azr, lift, nz) in sorted(lift_rows, key=lambda x: -x[5]):
            print(f"  {sym} {tf} {pname}: standalone={sar:+.3f} -> at_zone={azr:+.3f} "
                  f"(lift {lift:+.3f}, n_zone={nz})")

    # ---- save raw ----
    outpath = os.path.join(CACHE, "candle_lab_results.json")
    payload = {
        "config": {"IS_FRAC": IS_FRAC, "RR": RR, "FWD_N": FWD_N,
                   "MAX_HOLD": MAX_HOLD, "MIN_OOS": MIN_OOS,
                   "cost_model": "2x typ spread (spread+commission proxy), price units",
                   "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
                   "no_lookahead": True},
        "results": all_results,
        "summary_oos": summary_rows,
    }
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nRaw results saved -> {outpath}")
    return all_results, summary_rows


if __name__ == "__main__":
    main()
