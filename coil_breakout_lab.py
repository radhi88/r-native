"""coil_breakout_lab.py — Is the user's "تجمّعات الشموع الصغيرة" (small-candle
clusters / coil) a real scalping edge, or a coin flip after cost?

THE IDEA (user's words): a run of small candles bunched together — a low-volatility
COIL — that then "breaks out". The trader's intuition is that energy builds inside
the coil and releases in a tradable direction.

We test it the only honest way: strict no-lookahead, OOS-only, cost-netted, vs a
random baseline. TWO separate questions, reported separately:

  H1 — DIRECTION (is the breakout side predictable BEFORE it happens?)
       Before any close pierces the coil, can prior trend / coil position tell us
       which way it will break? We classify each coil by a CAUSAL prior-trend sign
       (EMA20 slope over the bars leading INTO the coil, known at coil-close) and
       ask: what fraction of coils break in the trend direction? Is it > 50% by
       more than noise? (binomial). We also ask the cleaner question: GIVEN the
       breakout direction, is the NEXT-N-bar close move in that direction more
       often than a coin flip — i.e. does breakout CONTINUE rather than fade?

  H2 — CONTINUATION / TRADABILITY (does entering the breakout pay after cost?)
       When a candle CLOSES beyond the coil's high (long) or low (short), enter at
       that bar's close. SL = OTHER side of the coil (the brief's spec). TP = 2R.
       Walk strictly-future bars; first touch wins; a bar spanning BOTH SL & TP is
       counted SL (pessimistic). Realized R is netted of a realistic round-trip
       cost from the symbol meta. Report OOS avg_R, win-rate, and a bootstrap 95%
       CI on avg_R vs the same-bar RANDOM-direction baseline. Edge requires the
       CI to NOT straddle zero (and to beat the random baseline).

GRID (per the brief):
   SYMBOLS x TFS = [XAUUSDm,EURUSDm,GBPUSDm,US30m,BTCUSDm] x [M5,M15,H1]
   K (coil length)            = 4, 6, 8 consecutive candles
   m (coil tightness vs ATR)  = 0.6, 0.8   (total coil range < m * ATR)

STRICT NO-LOOKAHEAD
   * The coil at bar i uses ONLY bars <= i (the K candles ending at i, and an ATR
     reference computed over bars BEFORE the coil so the "small" judgement is not
     contaminated by the coil itself).
   * Prior-trend sign is computed from bars <= i (EMA over the run leading into
     the coil). It is known at coil close.
   * The breakout must happen on a bar j > i and is acted on at j's close.
   * Forward outcomes use only bars > j.
   * A coil is given a limited WAIT window for a breakout to appear (so we don't
     pick up a "breakout" 5000 bars later). If no close pierces the coil within
     the wait window, the coil is discarded (recorded as a no-trade, not a loss).

SPLIT 67/33 IS/OOS BY TIME. Report OOS only. >=40 OOS events required else flagged
small-sample (per the brief).

FORWARD HORIZON N (for the raw directional gauge): 30 (M5), 20 (M15), 12 (H1).

DATA: data/lab_cache/<SYM>_<TF>.npz (t,o,h,l,c,v). Falls back to MetaTrader5
copy_rates_from_pos only if a cache file is missing. Cost from <SYM>_meta.json.

RUN:
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\coil_breakout_lab.py
Results JSON -> data/lab_cache/coil_breakout_lab_results.json
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

K_GRID = [4, 6, 8]            # coil length (consecutive candles)
M_GRID = [0.6, 0.8]          # total coil range < m * ATR

IS_FRAC = 0.67               # 67/33 split by time
RR = 2.0                     # TP = 2R
MIN_OOS = 40                 # below this -> small-sample flag (brief: >=40)

ATR_PERIOD = 14              # ATR reference window (causal, ends BEFORE the coil)
EMA_TREND = 20               # prior-trend EMA for the DIRECTION test

# forward horizon for the raw directional gauge, by TF
FWD_N = {"M5": 30, "M15": 20, "H1": 12}
# max bars to wait for a breakout close to appear after the coil (in bars)
WAIT_WINDOW = {"M5": 30, "M15": 20, "H1": 12}
# max bars to hold a tradable breakout trade before timeout-mark-to-close
MAX_HOLD = {"M5": 60, "M15": 40, "H1": 24}

BOOT_B = 2000                # bootstrap resamples (brief: 2000x)
SEED = 7

# Realistic round-trip cost. FX expressed in PIPS (5-digit: 1 pip = 10 points);
# gold/index/crypto expressed directly in POINTS. Round-trip ~ 2x typical spread
# (spread + commission proxy), per the brief's guidance:
#   gold ~20-30 points, FX ~1-2 pips, US30 ~2-4 pts, BTC ~30-60 pts.
TYP_SPREAD_POINTS = {        # one-way typical spread, in POINTS (price = points*point)
    "XAUUSDm": 25.0,         # gold ~20-30 pts -> mid 25
    "US30m": 3.0,            # US30 ~2-4 pts -> mid 3
    "BTCUSDm": 45.0,         # BTC ~30-60 pts -> mid 45
}
TYP_SPREAD_PIPS_FX = {"EURUSDm": 1.5, "GBPUSDm": 2.0}   # FX one-way, in PIPS


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_bars(sym: str, tf: str):
    path = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(path):
        d = np.load(path)
        return (d["t"].astype(np.int64),
                d["o"].astype(np.float64), d["h"].astype(np.float64),
                d["l"].astype(np.float64), d["c"].astype(np.float64),
                d["v"].astype(np.float64))
    return _load_bars_mt5(sym, tf)


_MT5_READY = False


def _load_bars_mt5(sym: str, tf: str):
    """Fallback: pull from MetaTrader5 if the cache file is missing. Initializes
    the terminal once."""
    global _MT5_READY
    import MetaTrader5 as mt5  # local import: only if needed
    if not _MT5_READY:
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        _MT5_READY = True
    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    count = {"M5": 40000, "M15": 30000, "H1": 20000}[tf]
    rates = mt5.copy_rates_from_pos(sym, tf_map[tf], 0, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 copy_rates_from_pos returned nothing for {sym} {tf}")
    return (rates["time"].astype(np.int64),
            rates["open"].astype(np.float64), rates["high"].astype(np.float64),
            rates["low"].astype(np.float64), rates["close"].astype(np.float64),
            rates["tick_volume"].astype(np.float64))


def load_meta(sym: str) -> dict:
    with open(os.path.join(CACHE, f"{sym}_meta.json"), "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def roundtrip_cost_price(sym: str, meta: dict) -> float:
    """Round-trip cost in PRICE units = 2 * one-way-typical-spread."""
    point = float(meta["point"])
    if sym in TYP_SPREAD_PIPS_FX:
        pip = 10.0 * point                       # 5-digit FX: 1 pip = 10 points
        return 2.0 * TYP_SPREAD_PIPS_FX[sym] * pip
    return 2.0 * TYP_SPREAD_POINTS.get(sym, 20.0) * point


# ---------------------------------------------------------------------------
# Indicators (causal)
# ---------------------------------------------------------------------------
def atr_wilder(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder ATR. atr[i] uses bars <= i only (prev close c[i-1])."""
    n = c.size
    atr = np.full(n, np.nan)
    if n <= period + 1:
        return atr
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    first = tr[1:period + 1].mean()
    atr[period] = first
    a = first
    for i in range(period + 1, n):
        a = (a * (period - 1) + tr[i]) / period
        atr[i] = a
    return atr


def ema(x: np.ndarray, period: int) -> np.ndarray:
    """Causal EMA. ema[i] uses x[<=i]."""
    n = x.size
    out = np.full(n, np.nan)
    if n == 0:
        return out
    k = 2.0 / (period + 1.0)
    out[0] = x[0]
    for i in range(1, n):
        out[i] = x[i] * k + out[i - 1] * (1.0 - k)
    return out


# ---------------------------------------------------------------------------
# Coil detection (causal). A coil ENDS at bar i: the K candles [i-K+1 .. i] have
# total span (max high - min low) < m * ATR_ref, where ATR_ref is the Wilder ATR
# evaluated at bar (i-K) — i.e. using only bars BEFORE the coil, so the coil's
# own (small) bars do not deflate the volatility reference and make the test
# trivially pass.
#
# Returns list of dicts (all fields known at coil close, bar i):
#   i        : coil-end bar (confirmation bar; act only on bars > i)
#   coil_hi  : max high over the K coil bars
#   coil_lo  : min low  over the K coil bars
#   atr_ref  : ATR reference used
#   trend    : +1 / -1 / 0  prior-trend sign (EMA20 slope into the coil)
# ---------------------------------------------------------------------------
def detect_coils(o, h, l, c, K: int, m: float, atr: np.ndarray,
                 ema_trend: np.ndarray) -> List[dict]:
    n = c.size
    out = []
    start_min = max(K, ATR_PERIOD + 2)   # need an ATR ref before the coil
    for i in range(start_min, n):
        s = i - K + 1                    # first bar of the coil
        atr_ref = atr[s - 1]             # ATR known BEFORE the coil starts (causal)
        if not np.isfinite(atr_ref) or atr_ref <= 0:
            continue
        coil_hi = float(h[s:i + 1].max())
        coil_lo = float(l[s:i + 1].min())
        span = coil_hi - coil_lo
        if span <= 0:
            continue
        if span >= m * atr_ref:
            continue                     # not tight enough -> not a coil
        # prior-trend sign: EMA20 slope over the bars leading into the coil.
        # Compare EMA at the bar just before the coil to EMA K bars earlier.
        e_now = ema_trend[s - 1]
        e_then = ema_trend[max(0, s - 1 - K)]
        if not (np.isfinite(e_now) and np.isfinite(e_then)):
            trend = 0
        else:
            d = e_now - e_then
            # require a non-trivial slope relative to atr to call a trend
            if abs(d) < 0.05 * atr_ref:
                trend = 0
            else:
                trend = 1 if d > 0 else -1
        out.append({"i": i, "coil_hi": coil_hi, "coil_lo": coil_lo,
                    "atr_ref": atr_ref, "trend": trend})
    return out


def find_breakout(coil: dict, o, h, l, c, wait: int) -> Optional[dict]:
    """Strictly future: find the FIRST bar j>i whose CLOSE pierces the coil
    high (long, dir=+1) or coil low (short, dir=-1), within `wait` bars. Returns
    {j, direction} or None if the coil never breaks out in the window.
    Causal: examines only bars j>i in order, returns the first."""
    n = c.size
    i = coil["i"]
    hi = coil["coil_hi"]
    lo = coil["coil_lo"]
    end = min(n, i + 1 + wait)
    for j in range(i + 1, end):
        if c[j] > hi:
            return {"j": j, "direction": +1}
        if c[j] < lo:
            return {"j": j, "direction": -1}
    return None


# ---------------------------------------------------------------------------
# Trade simulation — enter at breakout bar close, SL = OTHER side of coil,
# TP = 2R. First-touch on future bars; bar spanning both -> SL (pessimistic).
# Returns realized R (cost-netted) or None if risk invalid.
# ---------------------------------------------------------------------------
def simulate_breakout(j: int, direction: int, coil: dict, o, h, l, c,
                      cost_price: float, max_hold: int) -> Optional[float]:
    n = c.size
    entry = c[j]
    if direction > 0:
        sl = coil["coil_lo"]             # other side of coil
        risk = entry - sl
        if risk <= 0:
            return None
        tp = entry + RR * risk
    else:
        sl = coil["coil_hi"]
        risk = sl - entry
        if risk <= 0:
            return None
        tp = entry - RR * risk

    end = min(n, j + 1 + max_hold)
    for k in range(j + 1, end):
        hit_sl = (l[k] <= sl) if direction > 0 else (h[k] >= sl)
        hit_tp = (h[k] >= tp) if direction > 0 else (l[k] <= tp)
        if hit_sl and hit_tp:
            return -1.0 - cost_price / risk          # pessimistic tie -> SL
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    # timeout: mark to last close
    last = c[end - 1]
    pnl_price = (last - entry) if direction > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


def fwd_continue(j: int, direction: int, c, fwd_n: int) -> Optional[int]:
    """Raw continuation gauge: did the close fwd_n bars AFTER the breakout bar
    move further in the breakout direction? 1 hit / 0 miss / None if no horizon."""
    n = c.size
    k = j + fwd_n
    if k >= n:
        return None
    moved = c[k] - c[j]
    if moved == 0:
        return 0
    return int((moved > 0) == (direction > 0))


# ---------------------------------------------------------------------------
# Random baseline — same breakout BARS, but a coin-flip direction. SL/TP set the
# same |risk| as a real coil trade would use at that bar (use the actual coil
# width so the geometry matches), but the side is random. Cost-netted. This is
# the honest "what would a random scalper at these same moments earn?" control.
# ---------------------------------------------------------------------------
def simulate_random(j: int, coil: dict, o, h, l, c, cost_price: float,
                    max_hold: int, rng: np.random.Generator) -> Optional[float]:
    direction = 1 if rng.random() < 0.5 else -1
    entry = c[j]
    width = coil["coil_hi"] - coil["coil_lo"]
    if width <= 0:
        return None
    # mimic the real trade's risk geometry: risk = distance from entry to the
    # far side of the coil in the chosen direction.
    if direction > 0:
        sl = entry - width if (entry - width) < coil["coil_lo"] else coil["coil_lo"]
        # use the coil's far side as the real trade does
        sl = coil["coil_lo"]
        risk = entry - sl
        if risk <= 0:
            risk = width
            sl = entry - width
        tp = entry + RR * risk
    else:
        sl = coil["coil_hi"]
        risk = sl - entry
        if risk <= 0:
            risk = width
            sl = entry + width
        tp = entry - RR * risk
    n = c.size
    end = min(n, j + 1 + max_hold)
    for k in range(j + 1, end):
        hit_sl = (l[k] <= sl) if direction > 0 else (h[k] >= sl)
        hit_tp = (h[k] >= tp) if direction > 0 else (l[k] <= tp)
        if hit_sl and hit_tp:
            return -1.0 - cost_price / risk
        if hit_sl:
            return -1.0 - cost_price / risk
        if hit_tp:
            return RR - cost_price / risk
    last = c[end - 1]
    pnl_price = (last - entry) if direction > 0 else (entry - last)
    return (pnl_price / risk) - cost_price / risk


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def _bootstrap_ci(rs_a: np.ndarray, B: int = BOOT_B, seed: int = SEED):
    """Bootstrap the mean R. Returns (ci_lo, ci_hi, p_le_0) where p_le_0 is the
    share of resampled means <= 0 (one-sided 'no edge' p-value)."""
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


def _binom_p_two_sided(k: int, n: int, p0: float = 0.5) -> Optional[float]:
    """Two-sided binomial p-value for k successes in n trials vs p0. Normal
    approx with continuity correction (n is large here)."""
    if n == 0:
        return None
    mu = n * p0
    sd = math.sqrt(n * p0 * (1 - p0))
    if sd == 0:
        return None
    z = (abs(k - mu) - 0.5) / sd
    # two-sided
    p = math.erfc(z / math.sqrt(2.0))
    return round(p, 4)


def summarize_trades(rs: List[Optional[float]]) -> dict:
    rs = [r for r in rs if r is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0}
    a = np.array(rs)
    wins = int((a > 0).sum())
    out = {
        "n": n,
        "win_rate": round(100.0 * wins / n, 2),
        "avg_R": round(float(a.mean()), 4),
        "total_R": round(float(a.sum()), 3),
    }
    return out


# ---------------------------------------------------------------------------
# Run one (symbol, tf, K, m)
# ---------------------------------------------------------------------------
def run_cell(sym, tf, K, m, bars, cost_price):
    t, o, h, l, c, v = bars
    n = c.size
    split = int(n * IS_FRAC)
    atr = atr_wilder(h, l, c, ATR_PERIOD)
    et = ema(c, EMA_TREND)
    fwd_n = FWD_N[tf]
    wait = WAIT_WINDOW[tf]
    max_hold = MAX_HOLD[tf]

    coils = detect_coils(o, h, l, c, K, m, atr, et)

    rng = np.random.default_rng(SEED + K * 100 + int(m * 10))

    # direction-test accumulators (OOS only)
    dir_trend_aligned = 0        # breakout matched prior trend
    dir_trend_total = 0          # coils with a defined prior trend that broke out
    # continuation-gauge accumulators (OOS)
    cont_hits: List[int] = []
    # tradable + random accumulators (OOS)
    rs_trade: List[Optional[float]] = []
    rs_rand: List[Optional[float]] = []
    # IS tradable (robustness gate: a real edge must exist in-sample too, not
    # only appear in the last 33% — that would be a regime artifact).
    rs_trade_is: List[Optional[float]] = []
    n_coils_oos = 0
    n_broke_oos = 0

    for coil in coils:
        i = coil["i"]
        phase = "IS" if i < split else "OOS"
        bk = find_breakout(coil, o, h, l, c, wait)
        if bk is None:
            if phase == "OOS":
                n_coils_oos += 1
            continue
        j = bk["j"]
        direction = bk["direction"]

        if phase == "IS":
            rt_is = simulate_breakout(j, direction, coil, o, h, l, c, cost_price, max_hold)
            if rt_is is not None:
                rs_trade_is.append(rt_is)
            continue

        # ---- OOS only below ----
        n_coils_oos += 1
        n_broke_oos += 1

        # H1 DIRECTION: did the breakout side match the prior trend?
        if coil["trend"] != 0:
            dir_trend_total += 1
            if (coil["trend"] > 0) == (direction > 0):
                dir_trend_aligned += 1

        # H1 continuation gauge
        fc = fwd_continue(j, direction, c, fwd_n)
        if fc is not None:
            cont_hits.append(fc)

        # H2 tradable + random baseline (same bar)
        rt = simulate_breakout(j, direction, coil, o, h, l, c, cost_price, max_hold)
        rr = simulate_random(j, coil, o, h, l, c, cost_price, max_hold, rng)
        if rt is not None:
            rs_trade.append(rt)
        if rr is not None:
            rs_rand.append(rr)

    # ---- H2 stats ----
    trade = summarize_trades(rs_trade)
    rand = summarize_trades(rs_rand)
    is_clean = [r for r in rs_trade_is if r is not None]
    is_avg_R = round(float(np.mean(is_clean)), 4) if is_clean else None
    trade["is_n"] = len(is_clean)
    trade["is_avg_R"] = is_avg_R
    if trade.get("n", 0) >= 5:
        lo, hi, p = _bootstrap_ci(np.array([r for r in rs_trade if r is not None]))
        trade["ci95_lo"], trade["ci95_hi"], trade["p_avgR_le_0"] = lo, hi, p
        # edge requires CI not straddling 0 AND beating random avg_R
        trade["ci_excludes_0"] = bool(lo is not None and lo > 0)
        trade["beats_random"] = bool(rand.get("avg_R") is not None
                                     and trade["avg_R"] > rand["avg_R"])
        # robustness: was the edge also positive IN-SAMPLE? (sign-consistent)
        trade["is_consistent"] = bool(is_avg_R is not None and is_avg_R > 0)

    # ---- H1 stats ----
    breakout_rate = round(100.0 * n_broke_oos / n_coils_oos, 2) if n_coils_oos else None
    trend_align_rate = (round(100.0 * dir_trend_aligned / dir_trend_total, 2)
                        if dir_trend_total else None)
    trend_align_p = _binom_p_two_sided(dir_trend_aligned, dir_trend_total) \
        if dir_trend_total else None
    cont_rate = round(100.0 * float(np.mean(cont_hits)), 2) if cont_hits else None
    cont_p = _binom_p_two_sided(int(sum(cont_hits)), len(cont_hits)) if cont_hits else None

    return {
        "n_coils_oos": n_coils_oos,
        "n_broke_oos": n_broke_oos,
        "breakout_rate_pct": breakout_rate,
        # H1 DIRECTION
        "direction": {
            "trend_align_rate_pct": trend_align_rate,   # % breakouts matching prior trend
            "trend_align_n": dir_trend_total,
            "trend_align_p": trend_align_p,             # vs 50%
            "continuation_rate_pct": cont_rate,         # % fwd-N close continues breakout
            "continuation_n": len(cont_hits),
            "continuation_p": cont_p,                   # vs 50%
        },
        # H2 CONTINUATION / TRADABILITY
        "tradable": trade,
        "random_baseline": rand,
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------
def classify_verdict(rows: List[dict]) -> Tuple[str, List[dict]]:
    """rows = flattened OOS tradable cells.

    EDGE  : n>=MIN_OOS, OOS avg_R>0, bootstrap CI excludes 0, beats random, AND
            the SAME config is also positive IN-SAMPLE (is_consistent) — i.e. the
            edge is not just a property of the most-recent 33% regime.
    WEAK  : OOS positive & CI excludes 0 & beats random, but FAILS in-sample
            (sign flips) -> regime artifact, not a stable edge.
    NO_EDGE: nothing OOS-positive clears even the CI/random bar.
    """
    strong = []
    weak = []
    for r in rows:
        n = r.get("n", 0) or 0
        avgR = r.get("avg_R")
        if avgR is None:
            continue
        passes_oos = (n >= MIN_OOS and avgR > 0
                      and r.get("ci_excludes_0") and r.get("beats_random"))
        if not passes_oos:
            continue
        if r.get("is_consistent"):
            strong.append(r)
        else:
            weak.append(r)   # OOS-significant but in-sample-negative = regime artifact
    if strong:
        return "EDGE", strong
    if weak:
        return "WEAK", weak
    return "NO_EDGE", []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_results = {}
    flat_tradable = []          # for verdict + table
    dir_rows = []               # for H1 table

    for sym in SYMBOLS:
        meta = load_meta(sym)
        cost_price = roundtrip_cost_price(sym, meta)
        for tf in TFS:
            try:
                bars = load_bars(sym, tf)
            except Exception as exc:
                print(f"[ERR] load {sym} {tf}: {exc}")
                continue
            for K in K_GRID:
                for m in M_GRID:
                    try:
                        cell = run_cell(sym, tf, K, m, bars, cost_price)
                    except Exception as exc:
                        print(f"[ERR] {sym} {tf} K{K} m{m}: {exc}")
                        continue
                    key = f"{sym}_{tf}_K{K}_m{m}"
                    all_results[key] = {
                        "symbol": sym, "tf": tf, "K": K, "m": m,
                        "cost_price": cost_price, **cell,
                    }
                    tr = cell["tradable"]
                    flat_tradable.append({
                        "symbol": sym, "tf": tf, "K": K, "m": m,
                        "n": tr.get("n", 0),
                        "win_rate": tr.get("win_rate"),
                        "avg_R": tr.get("avg_R"),
                        "ci95_lo": tr.get("ci95_lo"),
                        "ci95_hi": tr.get("ci95_hi"),
                        "p_avgR_le_0": tr.get("p_avgR_le_0"),
                        "ci_excludes_0": tr.get("ci_excludes_0"),
                        "beats_random": tr.get("beats_random"),
                        "is_avg_R": tr.get("is_avg_R"),
                        "is_consistent": tr.get("is_consistent"),
                        "rand_avg_R": cell["random_baseline"].get("avg_R"),
                    })
                    d = cell["direction"]
                    dir_rows.append({
                        "symbol": sym, "tf": tf, "K": K, "m": m,
                        "n_coils": cell["n_coils_oos"],
                        "breakout_rate": cell["breakout_rate_pct"],
                        "trend_align": d["trend_align_rate_pct"],
                        "trend_align_n": d["trend_align_n"],
                        "trend_align_p": d["trend_align_p"],
                        "cont_rate": d["continuation_rate_pct"],
                        "cont_n": d["continuation_n"],
                        "cont_p": d["continuation_p"],
                    })

    # ===================== PRINT: H1 DIRECTION =====================
    print("=" * 118)
    print("COIL-BREAKOUT LAB — small-candle clusters (coil) breakout. OOS (33% out-of-sample, by time).")
    print("Coil = K consecutive candles whose total range < m*ATR(ref before coil). Strict no-lookahead, cost-netted.")
    print("=" * 118)
    print("\n### H1 — DIRECTION: is the breakout side predictable BEFORE it happens?")
    print("   trend_align% = breakouts matching prior-trend sign (vs 50% coin flip; p two-sided).")
    print("   cont% = forward-N close continued the breakout direction (vs 50%; p two-sided).")
    print("-" * 118)
    hdr = (f"{'SYMBOL':9}{'TF':4}{'K':>3}{'m':>5}{'coils':>7}{'brk%':>6}"
           f"{'align%':>8}{'aN':>5}{'alignP':>8}{'cont%':>7}{'cN':>5}{'contP':>8}  FLAG")
    print(hdr)
    print("-" * 118)
    for r in sorted(dir_rows, key=lambda x: (x["symbol"], x["tf"], x["K"], x["m"])):
        flag = "" if (r["cont_n"] or 0) >= MIN_OOS else "small-sample"
        def fmt(x, suf=""):
            return f"{x:.1f}{suf}" if x is not None else "-"
        print(f"{r['symbol']:9}{r['tf']:4}{r['K']:>3}{r['m']:>5.1f}{r['n_coils']:>7}"
              f"{fmt(r['breakout_rate']):>6}{fmt(r['trend_align']):>8}{r['trend_align_n']:>5}"
              f"{(f'{r['trend_align_p']:.3f}' if r['trend_align_p'] is not None else '-'):>8}"
              f"{fmt(r['cont_rate']):>7}{r['cont_n']:>5}"
              f"{(f'{r['cont_p']:.3f}' if r['cont_p'] is not None else '-'):>8}  {flag}")

    # DIRECTION verdict
    print("\n  >>> DIRECTION signal scan (n>=%d, p<0.05, rate clearly off 50%%):" % MIN_OOS)
    dir_signals = []
    for r in dir_rows:
        for kind, rate, nn, pp in (("trend_align", r["trend_align"], r["trend_align_n"], r["trend_align_p"]),
                                   ("continuation", r["cont_rate"], r["cont_n"], r["cont_p"])):
            if (nn or 0) >= MIN_OOS and rate is not None and pp is not None and pp < 0.05 \
                    and abs(rate - 50.0) >= 3.0:
                dir_signals.append((r["symbol"], r["tf"], r["K"], r["m"], kind, rate, nn, pp))
    if not dir_signals:
        print("     NONE. No coil's breakout direction (trend-align or continuation) beats a coin flip "
              "at n>=%d, p<0.05. -> DIRECTION NOT PREDICTABLE." % MIN_OOS)
    else:
        for (s, tf, K, m, kind, rate, nn, pp) in sorted(dir_signals, key=lambda x: x[7]):
            print(f"     {s} {tf} K{K} m{m} {kind}: {rate:.1f}% (n={nn}, p={pp})")

    # ===================== PRINT: H2 TRADABILITY =====================
    print("\n" + "=" * 118)
    print("### H2 — CONTINUATION / TRADABILITY: enter breakout@close, SL=other side of coil, TP=2R, cost-net.")
    print("   Random baseline = SAME bars, coin-flip direction, same risk geometry, cost-net.")
    print("   EDGE needs: n>=%d, OOS avg_R>0, bootstrap 95%% CI excludes 0, beats random," % MIN_OOS)
    print("   AND in-sample (isR) also positive (sign-consistent — not just a recent-regime fluke).")
    print("   isR = same config's avg_R on the FIRST 67%% (in-sample). If isR<0 but OOS>0 => regime artifact.")
    print("-" * 118)
    hdr2 = (f"{'SYMBOL':9}{'TF':4}{'K':>3}{'m':>5}{'N':>6}{'WIN%':>7}{'avgR':>9}"
            f"{'isR':>9}{'randR':>9}{'CI95lo':>9}{'CI95hi':>9}{'p<=0':>7}  FLAG")
    print(hdr2)
    print("-" * 118)
    for r in sorted(flat_tradable, key=lambda x: (x["symbol"], x["tf"], x["K"], x["m"])):
        n = r["n"] or 0
        flag = "" if n >= MIN_OOS else "small-sample"
        if n >= MIN_OOS and r["avg_R"] is not None and r["avg_R"] > 0 \
                and r.get("ci_excludes_0") and r.get("beats_random"):
            flag += (" <<EDGE" if r.get("is_consistent") else " <<OOS-only(REGIME ARTIFACT)")
        def f3(x):
            return f"{x:+.3f}" if x is not None else "-"
        def f1(x):
            return f"{x:.1f}" if x is not None else "-"
        print(f"{r['symbol']:9}{r['tf']:4}{r['K']:>3}{r['m']:>5.1f}{n:>6}"
              f"{f1(r['win_rate']):>7}{f3(r['avg_R']):>9}{f3(r['is_avg_R']):>9}{f3(r['rand_avg_R']):>9}"
              f"{f3(r['ci95_lo']):>9}{f3(r['ci95_hi']):>9}"
              f"{(f'{r['p_avgR_le_0']:.3f}' if r['p_avgR_le_0'] is not None else '-'):>7}  {flag}")

    verdict, winners = classify_verdict(flat_tradable)
    print("\n  >>> TRADABILITY positive-expectancy OOS cells (n>=%d, avg_R>0):" % MIN_OOS)
    pos = [r for r in flat_tradable if (r["n"] or 0) >= MIN_OOS and r["avg_R"] is not None and r["avg_R"] > 0]
    if not pos:
        print("     NONE. No coil-breakout config is net-positive OOS after cost. -> coin flip (or worse).")
    else:
        for r in sorted(pos, key=lambda x: -(x["avg_R"] or 0)):
            if r.get("ci_excludes_0") and r.get("beats_random"):
                tag = "EDGE (IS-consistent)" if r.get("is_consistent") \
                      else "OOS-ONLY -> REGIME ARTIFACT (in-sample negative)"
            else:
                tag = "CI straddles 0" if not r.get("ci_excludes_0") else "loses-to-random"
            print(f"     {r['symbol']} {r['tf']} K{r['K']} m{r['m']}: avg_R={r['avg_R']:+.3f} "
                  f"(isR {f'{r['is_avg_R']:+.3f}' if r['is_avg_R'] is not None else '-'}, "
                  f"rand {r['rand_avg_R']:+.3f}) WR={r['win_rate']}% n={r['n']} "
                  f"CI95=[{r['ci95_lo']},{r['ci95_hi']}] -> {tag}")

    # count negative-significant cells for the multiple-testing context
    neg_sig = sum(1 for r in flat_tradable if (r["n"] or 0) >= MIN_OOS
                  and r.get("ci95_hi") is not None and r["ci95_hi"] < 0)
    big_n = sum(1 for r in flat_tradable if (r["n"] or 0) >= MIN_OOS)
    print(f"\n  >>> Multiple-testing context: of {big_n} cells with n>={MIN_OOS}, "
          f"{neg_sig} are SIGNIFICANTLY NEGATIVE (CI fully <0); "
          f"{len(winners)} clear the full EDGE bar.")

    # ===================== FINAL VERDICT =====================
    print("\n" + "=" * 118)
    print(f"FINAL VERDICT: {verdict}")
    if verdict == "EDGE":
        print("  Coil-breakout shows a statistically robust, cost-survived, beats-random, IS-consistent edge in:")
        for r in winners:
            print(f"    - {r['symbol']} {r['tf']} K{r['K']} m{r['m']}: OOS avg_R={r['avg_R']:+.3f}, "
                  f"IS avg_R={r['is_avg_R']:+.3f}, CI95=[{r['ci95_lo']},{r['ci95_hi']}]")
    elif verdict == "WEAK":
        print("  Some cells are net-positive OOS, CI-excludes-0 AND beat random — BUT they FAIL in-sample")
        print("  (sign flips negative on the first 67%). That is the signature of a recent-REGIME ARTIFACT,")
        print("  not a stable structural edge. Combined with many significantly-NEGATIVE cells elsewhere,")
        print("  coil-breakout is NOT a reliable standalone scalping edge — it is a coin flip after cost,")
        print("  with the lone positive cluster explained by one favorable out-of-sample window.")
    else:
        print("  No coil-breakout configuration is net-positive OOS after realistic cost, and the breakout")
        print("  direction is not predictable beyond a coin flip. Coil-breakout is NOT a standalone edge.")
    print("=" * 118)

    # ---- save ----
    outpath = os.path.join(CACHE, "coil_breakout_lab_results.json")
    payload = {
        "config": {
            "SYMBOLS": SYMBOLS, "TFS": TFS, "K_GRID": K_GRID, "M_GRID": M_GRID,
            "IS_FRAC": IS_FRAC, "RR": RR, "MIN_OOS": MIN_OOS,
            "ATR_PERIOD": ATR_PERIOD, "EMA_TREND": EMA_TREND,
            "FWD_N": FWD_N, "WAIT_WINDOW": WAIT_WINDOW, "MAX_HOLD": MAX_HOLD,
            "BOOT_B": BOOT_B,
            "cost_model": "2x typical one-way spread (spread+commission proxy), price units",
            "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
            "no_lookahead": True,
            "coil_def": "K consecutive candles, total range < m*ATR(ref evaluated at bar before coil)",
            "sl_def": "other side of coil; tp=2R",
            "edge_gate": "n>=MIN_OOS AND OOS avg_R>0 AND bootstrap CI excludes 0 AND beats random "
                         "AND in-sample avg_R>0 (sign-consistent). OOS-positive-but-IS-negative = "
                         "regime artifact -> WEAK, not EDGE.",
        },
        "verdict": verdict,
        "results": all_results,
        "tradable_oos": flat_tradable,
        "direction_oos": dir_rows,
    }
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nRaw results saved -> {outpath}")
    return verdict, flat_tradable, dir_rows


if __name__ == "__main__":
    main()
