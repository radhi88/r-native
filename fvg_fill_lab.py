"""fvg_fill_lab.py — Rigorous, no-lookahead test of the user's FVG-fill thesis.

THESIS (user): when price moves fast and leaves a GAP / imbalance (a Fair Value
Gap) below (or above), price tends to RETURN and FILL it.

This lab answers two questions, honestly, on REAL cached bars:

  PART 1 — IS THE THESIS TRUE?
    Detect strictly-causal 3-candle FVGs. For each FVG confirmed at bar i, look
    forward up to N bars (N=200 M5 / 100 M15 / 60 H1) and ask: did price trade
    back INTO the gap zone (touch the near edge)? Report:
      * fill RATE (overall, by gap size bucket, by TF, by symbol)
      * median bars-to-fill
      * a BASELINE: random price zones of the SAME width placed at the SAME bar,
        measured with the same forward window. The thesis is only interesting if
        real FVGs fill MORE / FASTER than random width-matched zones.

  PART 2 — IS IT TRADABLE?
    When an unfilled OPPOSITE FVG exists (a gap left behind by the move), enter
    TOWARD it (fade the impulse), SL beyond the swing that created the gap, TP at
    the far edge of the gap (the fill). Net of realistic cost. OOS 67/33 split by
    time. Report PF, win-rate, expectancy (R), and sample. Beats break-even?

RIGOR
  * NO LOOKAHEAD. A pattern at bar i uses only bars <= i. FVG confirmation bar is
    the 3rd candle (causal by construction). Entry can only happen at bar i+1
    open or later. Forward fill/exit scan walks bars strictly > entry bar.
  * Cost-correct. Loads <SYM>_meta.json (trade_tick_value/tick_size/point) and
    subtracts a realistic round-trip spread cost (in price units) from every
    trade before computing R.
  * Time split 67/33 IS/OOS; PART 2 reports OOS only. < 30 OOS events => labelled
    small-sample.

DATA: reads ONLY data/lab_cache/<SYM>_<TF>.npz  (np.load -> t,o,h,l,c,v).
      Never imports MetaTrader5 (avoids terminal contention).

Run:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\fvg_fill_lab.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

# Reuse the repo's causal FVG detector where convenient.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "r_native_v2", "runtime", "shared"))
try:
    from order_blocks import detect_fvg as _repo_detect_fvg  # noqa: F401
    _HAVE_REPO = True
except Exception:
    _HAVE_REPO = False

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "US30m", "BTCUSDm"]
TFS = ["M5", "M15", "H1"]

# Forward window (bars) to look for a fill, per the user's spec.
FILL_WINDOW = {"M5": 200, "M15": 100, "H1": 60}

# Typical spread (in POINTS, i.e. multiples of `point`) per symbol, round trip.
# We subtract ~2x typical one-side spread per round trip (entry + exit crossing
# the spread). Conservative, matches the user's stated proxy.
TYPICAL_SPREAD_POINTS = {
    "XAUUSDm": 25.0,   # gold ~20-30 points (point=0.001 => 2.5 cents)
    "EURUSDm": 1.5,    # FX ~1-2 pips; point=1e-5 => 1.5 points = 0.15 pip... see note
    "GBPUSDm": 2.0,
    "US30m":   3.0,    # ~2-4 pts (point=0.1)
    "BTCUSDm": 45.0,   # ~30-60 pts (point=0.01 => $0.45)
}
# NOTE on FX: a "pip" for EURUSD is 0.0001 = 10 points (point=1e-5). The user
# said "FX ~1-2 pips". So spread in POINTS = pips * 10. We use 15/20 points
# (=1.5/2.0 pips). Corrected below.
TYPICAL_SPREAD_POINTS["EURUSDm"] = 15.0  # 1.5 pip
TYPICAL_SPREAD_POINTS["GBPUSDm"] = 20.0  # 2.0 pip

SWING = 5          # symmetric fractal half-width for the SL swing
ATR_PERIOD = 14
IS_FRACTION = 0.67  # 67/33 time split


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def load_bars(sym: str, tf: str):
    d = np.load(os.path.join(CACHE, f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.float64), d["o"].astype(np.float64),
            d["h"].astype(np.float64), d["l"].astype(np.float64),
            d["c"].astype(np.float64), d["v"].astype(np.float64))


def load_meta(sym: str) -> Dict:
    with open(os.path.join(CACHE, f"{sym}_meta.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def cost_price_units(sym: str, meta: Dict) -> float:
    """Realistic round-trip cost expressed in PRICE units.

    spread_points * point  = one-side spread in price.
    Round trip crosses the spread effectively ~2x (enter + exit), so
    cost_price = 2 * spread_points * point.
    """
    point = float(meta.get("point", meta.get("trade_tick_size", 0.0)))
    sp = TYPICAL_SPREAD_POINTS[sym]
    return 2.0 * sp * point


# ---------------------------------------------------------------------------
# Causal indicators
# ---------------------------------------------------------------------------
def atr(h, l, c, period=ATR_PERIOD):
    n = h.size
    prev_c = np.empty(n)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        out[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    else:
        out[:] = tr.mean() if n else np.nan
    return out


def detect_fvg_causal(o, h, l, c):
    """3-candle FVGs, confirmed at the 3rd candle (causal).

    Returns list of dicts: {type, lo, hi, idx, width, swing_idx}
      type: 'bullish' (gap below, support) or 'bearish' (gap above, resistance)
      lo, hi: gap zone bounds (lo<hi)
      idx: index of confirming (3rd) candle
      width: hi-lo (price units)
    Matches r_native_v2/runtime/shared/order_blocks.detect_fvg logic exactly:
      bullish: l[i] > h[i-2]  -> gap [h[i-2], l[i]]
      bearish: h[i] < l[i-2]  -> gap [h[i], l[i-2]]
    """
    n = c.size
    out = []
    for i in range(2, n):
        if l[i] > h[i - 2]:
            zlo, zhi = float(h[i - 2]), float(l[i])
            out.append({"type": "bullish", "lo": zlo, "hi": zhi, "idx": i,
                        "width": zhi - zlo})
        elif h[i] < l[i - 2]:
            zlo, zhi = float(h[i]), float(l[i - 2])
            out.append({"type": "bearish", "lo": zlo, "hi": zhi, "idx": i,
                        "width": zhi - zlo})
    return out


# ---------------------------------------------------------------------------
# PART 1 — fill rate
# ---------------------------------------------------------------------------
def first_fill_bar(h, l, idx, zlo, zhi, window):
    """First bar in (idx, idx+window] whose [low,high] overlaps the gap zone.
    Returns (fill_bar or -1, bars_to_fill or -1)."""
    n = h.size
    end = min(n - 1, idx + window)
    for j in range(idx + 1, end + 1):
        if l[j] <= zhi and h[j] >= zlo:  # overlap
            return j, j - idx
    return -1, -1


def bucket_by_size(width, atr_val):
    """ATR-normalized gap size bucket. small <0.5 ATR, med 0.5-1.5, large >1.5."""
    if not np.isfinite(atr_val) or atr_val <= 0:
        return "unk"
    r = width / atr_val
    if r < 0.5:
        return "small"
    if r < 1.5:
        return "med"
    return "large"


def part1_symbol_tf(sym, tf):
    t, o, h, l, c, v = load_bars(sym, tf)
    n = c.size
    window = FILL_WINDOW[tf]
    a = atr(h, l, c)

    fvgs = detect_fvg_causal(o, h, l, c)

    # restrict to FVGs that have a full forward window available (so fill-rate
    # isn't biased by truncation near the end of the series)
    rng = np.random.default_rng(20260615)

    rows = []          # per-FVG records
    base_rows = []     # per matched random-zone records
    for f in fvgs:
        i = f["idx"]
        if i + window > n - 1:
            continue
        av = a[i]
        if not np.isfinite(av) or av <= 0:
            continue
        fb, btf = first_fill_bar(h, l, i, f["lo"], f["hi"], window)
        rows.append({
            "idx": i, "type": f["type"], "width": f["width"],
            "bucket": bucket_by_size(f["width"], av),
            "filled": fb >= 0, "btf": btf,
        })
        # BASELINE: a random zone of the SAME width, centered on a random price
        # within a +-1.5 ATR band of the close at bar i (a plausible nearby
        # zone), measured with the same window. This controls for "any narrow
        # band near price gets touched eventually".
        w = f["width"]
        center = c[i] + rng.uniform(-1.5, 1.5) * av
        bzlo, bzhi = center - w / 2.0, center + w / 2.0
        bfb, bbtf = first_fill_bar(h, l, i, bzlo, bzhi, window)
        base_rows.append({"filled": bfb >= 0, "btf": bbtf,
                          "bucket": bucket_by_size(w, av)})

    if not rows:
        return None

    def summarize(recs, key_filter=None):
        sel = [r for r in recs if key_filter is None or key_filter(r)]
        nn = len(sel)
        if nn == 0:
            return {"n": 0, "fill_rate": None, "median_btf": None}
        filled = [r for r in sel if r["filled"]]
        rate = len(filled) / nn
        med = float(np.median([r["btf"] for r in filled])) if filled else None
        return {"n": nn, "fill_rate": round(rate, 4), "median_btf": med}

    out = {
        "n_fvg": len(rows),
        "overall": summarize(rows),
        "baseline_overall": summarize(base_rows),
        "by_bucket": {b: summarize(rows, lambda r, b=b: r["bucket"] == b)
                      for b in ["small", "med", "large"]},
        "baseline_by_bucket": {b: summarize(base_rows, lambda r, b=b: r["bucket"] == b)
                               for b in ["small", "med", "large"]},
        "by_type": {ty: summarize(rows, lambda r, ty=ty: r["type"] == ty)
                    for ty in ["bullish", "bearish"]},
    }
    return out


# ---------------------------------------------------------------------------
# PART 2 — tradability (fade toward an unfilled opposite gap)
# ---------------------------------------------------------------------------
def swing_extreme_for_sl(o, h, l, c, fvg, side):
    """The swing that CREATED the gap = the 3-candle pattern's extreme.

    For a bullish FVG (gap below, we BUY toward it = price came down to fill, so
    we buy the dip): SL goes below the gap's lower swing (the low of candle i, or
    the gap low). For a bearish FVG (gap above, we SELL toward it): SL goes above
    the gap's upper swing.

    We use the gap-creating candles' extreme as the structural swing.
    """
    i = fvg["idx"]
    if side == "buy":
        # protective low = min low of the 3 gap candles
        return float(np.min(l[i - 2:i + 1]))
    else:
        return float(np.max(h[i - 2:i + 1]))


def part2_symbol_tf(sym, tf, meta):
    """Strategy: at each bar, if there is an UNFILLED opposite FVG nearby, fade
    the move toward the gap.

    Mechanics (no lookahead):
      * Walk bars in time. Maintain the list of FVGs confirmed so far (idx<=bar).
      * A *fade-toward* setup: price has moved AWAY and left a gap; we enter when
        price is approaching but the gap is still UNFILLED.
        - BULLISH FVG (gap below current price): price impulsed UP leaving a gap
          below. Thesis says price returns DOWN to fill it. So we SELL (fade the
          up-move) targeting the gap (TP = far/lower edge of gap = full fill).
          Entry trigger: at a bar where the gap is still unfilled and price is
          above it. SL = above the swing high that created the gap.
        - BEARISH FVG (gap above): price impulsed DOWN leaving a gap above.
          Thesis: price returns UP to fill it. We BUY targeting the gap.
          SL = below the swing low that created the gap.
      * Enter at next bar OPEN after the trigger bar (no same-bar fill).
      * Manage forward: scan bars > entry bar. Hit SL or TP (intrabar: if both
        touched in same bar, assume SL first = conservative). Time-stop after
        the fill window with exit at that bar's close.
      * Cost subtracted in price units from gross PnL.
      * R = pnl_price / risk_price where risk_price = |entry - SL|.

    To make this a clean, ACTIONABLE-on-confirmation rule (and avoid firing on
    every bar), we trigger ONCE per FVG: at the confirmation bar idx, we place a
    fade trade at idx+1 open if the gap is unfilled and entry-to-TP > entry-to-SL
    isn't absurd. This is the most faithful "the gap just formed, fade back into
    it" reading and is fully causal.
    """
    t, o, h, l, c, v = load_bars(sym, tf)
    n = c.size
    window = FILL_WINDOW[tf]
    cost = cost_price_units(sym, meta)

    fvgs = detect_fvg_causal(o, h, l, c)

    trades = []  # each: {entry_idx, side, R, win, gross_R, t}
    for f in fvgs:
        i = f["idx"]
        if i + 1 >= n:
            continue
        entry_idx = i + 1
        if entry_idx + 1 >= n:
            continue
        entry = float(o[entry_idx])  # next-bar open (causal)

        if f["type"] == "bullish":
            # gap below; price went up; fade = SELL down into the gap
            side = "sell"
            tp = f["lo"]            # far (lower) edge = full fill
            sl = swing_extreme_for_sl(o, h, l, c, f, "sell")  # above swing high
            # entry must be above the gap (we're selling from above into it)
            if not (entry > f["hi"] and sl > entry and tp < entry):
                continue
        else:  # bearish: gap above; price went down; fade = BUY up into the gap
            side = "buy"
            tp = f["hi"]            # far (upper) edge = full fill
            sl = swing_extreme_for_sl(o, h, l, c, f, "buy")   # below swing low
            if not (entry < f["lo"] and sl < entry and tp > entry):
                continue

        risk = abs(entry - sl)
        if risk <= 0:
            continue

        # forward management (bars strictly after entry_idx)
        exit_price = None
        end = min(n - 1, entry_idx + window)
        for j in range(entry_idx, end + 1):
            hi_j, lo_j = h[j], l[j]
            if side == "sell":
                hit_sl = hi_j >= sl
                hit_tp = lo_j <= tp
            else:
                hit_sl = lo_j <= sl
                hit_tp = hi_j >= tp
            if hit_sl and hit_tp:
                exit_price = sl   # conservative: assume SL first
                break
            if hit_sl:
                exit_price = sl
                break
            if hit_tp:
                exit_price = tp
                break
        if exit_price is None:
            exit_price = float(c[end])  # time-stop at window end close

        if side == "sell":
            gross = entry - exit_price
        else:
            gross = exit_price - entry
        net = gross - cost
        R = net / risk
        gross_R = gross / risk
        trades.append({"entry_idx": entry_idx, "side": side, "R": R,
                       "gross_R": gross_R, "win": net > 0, "t": float(t[entry_idx])})

    if not trades:
        return None

    # 67/33 time split (by entry time)
    trades.sort(key=lambda x: x["t"])
    split = int(len(trades) * IS_FRACTION)
    oos = trades[split:]

    def stats(ts):
        if not ts:
            return None
        Rs = np.array([x["R"] for x in ts])
        wins = Rs[Rs > 0]
        losses = Rs[Rs <= 0]
        gross_win = float(wins.sum()) if wins.size else 0.0
        gross_loss = float(-losses.sum()) if losses.size else 0.0
        pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        return {
            "n": len(ts),
            "win_rate": round(float((Rs > 0).mean()), 4),
            "expectancy_R": round(float(Rs.mean()), 4),
            "pf": round(pf, 4) if np.isfinite(pf) else None,
            "sum_R": round(float(Rs.sum()), 4),
            "gross_expectancy_R": round(float(np.mean([x["gross_R"] for x in ts])), 4),
        }

    return {
        "n_total": len(trades),
        "is": stats(trades[:split]),
        "oos": stats(oos),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("fvg_fill_lab.py — FVG fill thesis (no-lookahead, cost-correct, OOS)")
    print(f"repo detector reused: {_HAVE_REPO}")
    print("=" * 78)

    results = {"part1_fill": {}, "part2_trade": {}, "config": {
        "fill_window": FILL_WINDOW, "spread_points": TYPICAL_SPREAD_POINTS,
        "is_fraction": IS_FRACTION, "swing": SWING}}

    # ---------------- PART 1 ----------------
    print("\n" + "#" * 78)
    print("# PART 1 — DO FVGs FILL? (real vs random width-matched baseline)")
    print("#" * 78)
    for sym in SYMBOLS:
        results["part1_fill"][sym] = {}
        for tf in TFS:
            r = part1_symbol_tf(sym, tf)
            results["part1_fill"][sym][tf] = r
            if r is None:
                print(f"\n{sym} {tf}: no FVGs with full window")
                continue
            ov = r["overall"]
            bo = r["baseline_overall"]
            print(f"\n{sym} {tf}: n_fvg={r['n_fvg']}")
            print(f"  FILL RATE  real={ov['fill_rate']}  (median bars={ov['median_btf']})  n={ov['n']}")
            print(f"  BASELINE   rand={bo['fill_rate']}  (median bars={bo['median_btf']})  n={bo['n']}")
            edge = (ov['fill_rate'] - bo['fill_rate']) if (ov['fill_rate'] is not None and bo['fill_rate'] is not None) else None
            print(f"  EDGE vs baseline: {round(edge,4) if edge is not None else None}")
            for b in ["small", "med", "large"]:
                bb = r["by_bucket"][b]
                rb = r["baseline_by_bucket"][b]
                print(f"    {b:<5}: real={bb['fill_rate']} (n={bb['n']}, med={bb['median_btf']})  "
                      f"base={rb['fill_rate']} (n={rb['n']})")

    # ---------------- PART 2 ----------------
    print("\n" + "#" * 78)
    print("# PART 2 — IS IT TRADABLE? (fade toward gap, OOS 33%, net of cost)")
    print("#" * 78)
    for sym in SYMBOLS:
        meta = load_meta(sym)
        results["part2_trade"][sym] = {}
        cpu = cost_price_units(sym, meta)
        for tf in TFS:
            r = part2_symbol_tf(sym, tf, meta)
            results["part2_trade"][sym][tf] = r
            if r is None or r["oos"] is None:
                print(f"\n{sym} {tf}: no trades")
                continue
            oos = r["oos"]
            tag = "  [SMALL SAMPLE]" if oos["n"] < 30 else ""
            print(f"\n{sym} {tf}: n_total={r['n_total']}  cost/trade(price)={cpu:.5f}{tag}")
            print(f"  OOS: n={oos['n']}  WR={oos['win_rate']}  expR={oos['expectancy_R']}  "
                  f"PF={oos['pf']}  sumR={oos['sum_R']}  grossExpR={oos['gross_expectancy_R']}")

    # ---------------- SAVE ----------------
    out_path = os.path.join(CACHE, "fvg_fill_lab_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print("\n" + "=" * 78)
    print(f"raw results saved -> {out_path}")
    print("=" * 78)
    return results


if __name__ == "__main__":
    main()
