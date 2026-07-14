"""with_trend_pullback_lab.py — Does a WITH-TREND EMA20 pullback-resume entry,
gated by a higher-timeframe EMA50-slope trend, have a NET-of-spread edge on
USDJPYm? (M5 entry gated by M15 trend; M15 entry gated by H1 trend.)

WHY THIS EXISTS
    USDJPYm leaned +0.3R on the shadow scoreboard but was NOT significant
    (t<1.9, within multiple-testing noise at pooled n~1100). The market-analyst
    proposed a falsifiable WITH-TREND hypothesis to test it properly:

      HTF trend (CAUSAL, closed HTF bars only): on the higher TF compute
        EMA50(close) and ATR14. slope_k = EMA50_k - EMA50_{k-50};
        ratio_k = slope_k / ATR14_k. UP if ratio>+0.5; DOWN if ratio<-0.5;
        FLAT (no-trade) if |ratio|<=0.5 (deadband suppresses chop). Map to an
        execution-TF entry bar i via the LAST fully-CLOSED HTF bar
        (htf_open_time + htf_seconds <= t_entry[i]). 100% causal coverage.

      Entry (CAUSAL, bars <= i-1 for decision inputs): execution-TF EMA20 +
        ATR14. LONG (only when HTF==UP): PULLBACK low[i-1]<=EMA20[i-1];
        RESUME close[i]>EMA20[i] AND close[i]>open[i] AND close[i]>close[i-1].
        SHORT mirror (HTF==DOWN). FLAT -> no trade. Enter at open[i+1].

      SL/TP: R = SL_ATR * ATR14(execution TF at entry bar). SL against trade.
        TP variants tested: 1.0R, 1.5R, and an ATR-chandelier trail (2.0xATR).
        Time-stop HORIZON bars. Intrabar SL-first pessimism.

      Cost: realistic round-trip spread subtracted in R per trade
        (USDJPY ~1.5 pip = 0.015 price each way -> charged round-trip in R).

    The project prior: on volatile symbols, WITH-trend beats counter-trend
    (counter-trend is a fat-tail risk the EMA50-slope veto already blocks). This
    is the direct positive MIRROR of that proven veto. Honest caveat from the
    analyst: +0.3R lean was GROSS, net-of-spread is worse, USDJPY range is
    contained (152-161) -> expect NO_EDGE net-of-cost. Test rigorously.

WHAT IT DOES (honest, falsifiable, NO-lookahead)
    For each execution TF (M5 gated by M15; M15 gated by H1):
      - Build the WITH-trend pullback signal set (LONG/SHORT/FLAT).
      - Also build the AGAINST-trend mirror (enter the SAME pullback-resume but
        gated to fire AGAINST the HTF trend) and the ALL set (no trend gate) to
        confirm WHETHER the with-trend gate is what helps.
      - For each (direction-gate x exit) sweep: OOS 67/33 expectancy, bootstrap
        2000x 95% CI, walk-forward 4 blocks (block0 = burn-in/IS discarded,
        pooled OOS over blocks 1..3), and a same-region random-bar baseline
        (same N, same long/short mix, same exit/spread).
    EDGE requires, on the BEST honest cell: OOS net-expectancy CI strictly > 0
    AND walk-forward pooled-OOS CI > 0 AND OOS expR beats the random CI_hi AND
    n>=30. Otherwise NO_EDGE. Do not manufacture an edge.

DATA  data/lab_cache/USDJPYm_{M5,M15,H1}.npz (t,o,h,l,c,v float arrays) +
      USDJPYm_meta.json (trade_tick_value/trade_tick_size for $).
RUN   C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe with_trend_pullback_lab.py
NOTE  read-only research. No MT5 connection, no order_send. Writes
      data/lab_cache/with_trend_pullback_lab_results.json.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
RESULTS = os.path.join(CACHE, "with_trend_pullback_lab_results.json")

SYMBOL = "USDJPYm"
# Execution TF -> (HTF, htf_seconds, exec_seconds)
TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600}
SETUPS = [("M5", "M15"), ("M15", "H1")]   # (exec_tf, htf_tf)

EMA_HTF = 50            # HTF trend EMA
SLOPE_LOOKBACK = 50     # EMA50_k - EMA50_{k-50}
ATR_PERIOD = 14
DEADBAND = 0.5          # |slope/ATR| <= 0.5 -> FLAT (no trade)
EMA_EXEC = 20           # execution-TF pullback EMA

SL_ATR = 1.5            # initial risk R = SL_ATR * ATR(exec) at entry bar
TP_RS = (1.0, 1.5)      # fixed take-profits to test
TRAIL_ATR = 2.0         # chandelier trailing-stop distance (xATR)
HORIZON = 48            # forward bars time-stop (M5: 4h; M15: 12h)

# Realistic round-trip spread in PRICE units (USDJPY ~1.5 pip = 0.015 price).
# Swept low/mid/high; mid is the headline.
SPREAD_SWEEP = [0.010, 0.015, 0.030]
MID_IDX = 1

N_BLOCKS = 4
IS_FRACTION = 0.67
MIN_OOS = 30
BOOT = 2000
SEED = 23


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_bars(tf):
    p = os.path.join(CACHE, f"{SYMBOL}_{tf}.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p)
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def load_meta():
    p = os.path.join(CACHE, f"{SYMBOL}_meta.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8-sig"))
    return {}


def money_per_unit(meta):
    tv, ts = meta.get("trade_tick_value"), meta.get("trade_tick_size") or meta.get("point")
    return float(tv) / float(ts) if (tv and ts and ts > 0) else 1.0


# --------------------------------------------------------------------------- #
# Indicators (causal). EMA over closes (value at bar k uses closes <= k).
# ATR14 simple-MA of TR (value at bar k uses bars <= k). To USE a value as a
# decision input at execution bar i we always reference index i-1 (closed bar).
# --------------------------------------------------------------------------- #
def ema(c, period):
    n = c.size
    out = np.full(n, np.nan)
    if n == 0:
        return out
    k = 2.0 / (period + 1.0)
    # seed with SMA of first `period` to avoid early-bar distortion
    if n >= period:
        seed = np.mean(c[:period])
        out[period - 1] = seed
        prev = seed
        for i in range(period, n):
            prev = c[i] * k + prev * (1 - k)
            out[i] = prev
    return out


def atr(h, l, c, period=ATR_PERIOD):
    n = h.size
    pc = np.empty(n); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        out[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    return out


def htf_trend_series(c15, h15, l15):
    """Per-HTF-bar trend label known at the CLOSE of that HTF bar k.
    label[k] in {+1 UP, -1 DOWN, 0 FLAT}. Uses EMA50(close)/slope50/ATR14 all
    computed on bars <= k (causal within the HTF series)."""
    e = ema(c15, EMA_HTF)
    a = atr(h15, l15, c15, ATR_PERIOD)
    n = c15.size
    lab = np.zeros(n, dtype=np.int8)
    for k in range(n):
        if k < SLOPE_LOOKBACK or not np.isfinite(e[k]) or not np.isfinite(e[k - SLOPE_LOOKBACK]):
            lab[k] = 0; continue
        av = a[k]
        if not np.isfinite(av) or av <= 0:
            lab[k] = 0; continue
        slope = e[k] - e[k - SLOPE_LOOKBACK]
        ratio = slope / av
        lab[k] = 1 if ratio > DEADBAND else (-1 if ratio < -DEADBAND else 0)
    return lab


def map_htf_to_exec(t_exec, t_htf, htf_sec):
    """For each exec bar i, index of the LAST fully-CLOSED HTF bar k* such that
    t_htf[k*] + htf_sec <= t_exec[i]. -1 if none. Causal (HTF must be closed)."""
    close_htf = t_htf + htf_sec
    idx = np.searchsorted(close_htf, t_exec, side="right") - 1
    return idx  # -1 where no closed parent


# --------------------------------------------------------------------------- #
# Signal generation (causal). gate in {"with","against","all"}.
#   with    : take LONG only when HTF==UP, SHORT only when HTF==DOWN, FLAT->skip
#   against : take LONG only when HTF==DOWN, SHORT only when HTF==UP (mirror)
#   all     : take the pullback-resume in its own direction regardless of HTF
# Entry executed at open[i+1] (next bar open; no same-bar lookahead).
# --------------------------------------------------------------------------- #
def find_signals(o, h, l, c, a_exec, ema_exec, htf_lab_at_exec, gate):
    n = c.size
    out = []
    # need i-1 indicators valid and i+1 to exist for the open-next entry
    start = max(EMA_EXEC + 1, ATR_PERIOD + 1, 2)
    for i in range(start, n - 1):
        e_i = ema_exec[i]; e_im1 = ema_exec[i - 1]
        if not (np.isfinite(e_i) and np.isfinite(e_im1)):
            continue
        # LONG pullback-resume setup
        long_setup = (l[i - 1] <= e_im1) and (c[i] > e_i) and (c[i] > o[i]) and (c[i] > c[i - 1])
        # SHORT mirror
        short_setup = (h[i - 1] >= e_im1) and (c[i] < e_i) and (c[i] < o[i]) and (c[i] < c[i - 1])
        if not (long_setup or short_setup):
            continue
        # signal direction from the setup itself (a bar could in principle satisfy
        # neither/one; both is impossible since c>o and c<o are exclusive)
        sig_dir = 1 if long_setup else -1
        trend = int(htf_lab_at_exec[i])  # +1/-1/0 from last closed HTF bar
        # apply the gate
        if gate == "with":
            if trend == 0:
                continue
            if sig_dir != trend:
                continue
            trade_dir = sig_dir
        elif gate == "against":
            # against-trend = the setup fires OPPOSITE to the HTF trend
            # (LONG setup while trend==DOWN, or SHORT setup while trend==UP).
            # We take the trade in the setup's own direction; the point is to
            # measure the same pullback-resume entry when it is counter-trend.
            if trend == 0:
                continue
            if sig_dir == trend:
                continue
            trade_dir = sig_dir
        elif gate == "all":
            trade_dir = sig_dir
        else:
            continue
        ei = i + 1                      # enter at next-bar OPEN
        entry = float(o[ei])
        av = a_exec[i]                  # ATR known at decision bar i (uses <= i)
        if not np.isfinite(av) or av <= 0:
            continue
        sl = entry - SL_ATR * av if trade_dir > 0 else entry + SL_ATR * av
        out.append({"i": int(i), "entry_idx": int(ei), "dir": int(trade_dir),
                    "entry": entry, "sl": float(sl), "atr": float(av),
                    "trend": trend})
    return out


# --------------------------------------------------------------------------- #
# Forward exit sim (no-lookahead within trade; intrabar SL-first = pessimistic).
# Forward sim reads ONLY bars > entry_idx (entry executed at open[entry_idx]).
# --------------------------------------------------------------------------- #
def sim_fixed(h, l, c, entry_idx, d, entry, sl, tp_R, horizon):
    n = c.size
    R = abs(entry - sl)
    if R <= 0:
        return None
    tp = entry + tp_R * R if d > 0 else entry - tp_R * R
    last = min(entry_idx + horizon, n - 1)
    maa = mfa = 0.0
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        fav = (hi - entry) / R if d > 0 else (entry - lo) / R
        adv = (entry - lo) / R if d > 0 else (hi - entry) / R
        mfa = max(mfa, fav); maa = max(maa, adv)
        hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
        hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
        if hit_sl and hit_tp:        # ambiguous bar -> SL first (pessimistic)
            return {"R": -1.0, "mfa": mfa, "maa": maa}
        if hit_sl:
            return {"R": -1.0, "mfa": mfa, "maa": maa}
        if hit_tp:
            return {"R": float(tp_R), "mfa": mfa, "maa": maa}
    px = c[last]
    rr = (px - entry) / R if d > 0 else (entry - px) / R
    return {"R": float(rr), "mfa": mfa, "maa": maa}


def sim_trail(h, l, c, a, entry_idx, d, entry, sl0, horizon):
    """ATR chandelier trailing stop. R unit = initial risk |entry-sl0|. No fixed
    TP. Stop updates off CLOSED bars only; intrabar we check the CURRENT stop
    (set from bars < j) before updating (pessimistic)."""
    n = c.size
    R = abs(entry - sl0)
    if R <= 0:
        return None
    last = min(entry_idx + horizon, n - 1)
    stop = sl0
    extreme = entry
    maa = mfa = 0.0
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        fav = (hi - entry) / R if d > 0 else (entry - lo) / R
        adv = (entry - lo) / R if d > 0 else (hi - entry) / R
        mfa = max(mfa, fav); maa = max(maa, adv)
        hit = (lo <= stop) if d > 0 else (hi >= stop)
        if hit:
            rr = (stop - entry) / R if d > 0 else (entry - stop) / R
            return {"R": float(rr), "mfa": mfa, "maa": maa}
        av = a[j] if np.isfinite(a[j]) and a[j] > 0 else R
        if d > 0:
            extreme = max(extreme, hi)
            stop = max(stop, extreme - TRAIL_ATR * av)
        else:
            extreme = min(extreme, lo)
            stop = min(stop, extreme + TRAIL_ATR * av)
    px = c[last]
    rr = (px - entry) / R if d > 0 else (entry - px) / R
    return {"R": float(rr), "mfa": mfa, "maa": maa}


def run(h, l, c, a, sigs, exit_kind, tp_R, spread):
    netR, grossR = [], []
    for s in sigs:
        ei, d, entry, sl = s["entry_idx"], s["dir"], s["entry"], s["sl"]
        R = abs(entry - sl)
        if R <= 0:
            continue
        if exit_kind == "fixed":
            sim = sim_fixed(h, l, c, ei, d, entry, sl, tp_R, HORIZON)
        else:
            sim = sim_trail(h, l, c, a, ei, d, entry, sl, HORIZON)
        if sim is None:
            continue
        cost = spread / R
        netR.append(sim["R"] - cost); grossR.append(sim["R"])
    return {"netR": np.asarray(netR), "grossR": np.asarray(grossR)}


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def boot_ci(arr, rng):
    if arr.size == 0:
        return None
    m = np.empty(BOOT); n = arr.size
    for b in range(BOOT):
        m[b] = np.mean(arr[rng.integers(0, n, n)])
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summ(arr, rng):
    if arr.size == 0:
        return {"n": 0, "expR": None, "wr": None, "ci95": None,
                "ci_pos": False, "ci_crosses_0": None, "t_stat": None}
    ci = boot_ci(arr, rng)
    m = float(np.mean(arr)); sd = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    t = (m / (sd / np.sqrt(arr.size))) if sd > 0 else None
    return {"n": int(arr.size), "expR": m, "wr": float(np.mean(arr > 0)),
            "ci95": ci, "ci_pos": bool(ci and ci[0] > 0),
            "ci_crosses_0": bool(ci and ci[0] <= 0 <= ci[1]),
            "t_stat": (float(t) if t is not None else None)}


def walk_forward(h, l, c, a, sigs, exit_kind, tp_R, spread, n_exec, rng):
    edges = [int(n_exec * k / N_BLOCKS) for k in range(N_BLOCKS + 1)]
    per, pooled = [], []
    for b in range(N_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        blk = [s for s in sigs if lo <= s["i"] < hi]
        r = run(h, l, c, a, blk, exit_kind, tp_R, spread)
        s = summ(r["netR"], rng); s["block"] = b; s["burn_in"] = (b == 0)
        per.append(s)
        if b >= 1:
            pooled.append(r["netR"])
    pa = np.concatenate(pooled) if pooled else np.array([])
    return {"per_block": per, "pooled_oos": summ(pa, rng)}


def random_baseline(h, l, c, a, lo_i, hi_i, n_ent, dpf, exit_kind, tp_R, spread, rng):
    """Random bars in the SAME OOS region; same N, same long-frac, same exit.

    Optimised: pre-sim every valid bar ONCE for both long & short (full no-look-
    ahead forward sim, same machinery / intrabar SL-first / spread), then the
    bootstrap just resamples those precomputed net-R values. Statistically
    identical to resimulating each draw, far faster."""
    n = c.size
    valid = np.asarray([i for i in range(max(lo_i, ATR_PERIOD + 1), min(hi_i, n - HORIZON - 1))
                        if np.isfinite(a[i]) and a[i] > 0], dtype=np.int64)
    if valid.size < 5 or n_ent < 1:
        return None
    longR = np.empty(valid.size); shortR = np.empty(valid.size)
    for k, ei in enumerate(valid):
        ei = int(ei); entry = float(c[ei]); av = float(a[ei])
        for d, store in ((1, longR), (-1, shortR)):
            sl = entry - SL_ATR * av if d > 0 else entry + SL_ATR * av
            R = abs(entry - sl)
            sim = (sim_fixed(h, l, c, ei, d, entry, float(sl), tp_R, HORIZON)
                   if exit_kind == "fixed" else
                   sim_trail(h, l, c, a, ei, d, entry, float(sl), HORIZON))
            store[k] = (sim["R"] - spread / R) if (sim and R > 0) else 0.0
    avgs = np.empty(BOOT)
    nv = valid.size
    for b in range(BOOT):
        picks = rng.integers(0, nv, n_ent)
        longs = rng.random(n_ent) < dpf
        vals = np.where(longs, longR[picks], shortR[picks])
        avgs[b] = vals.mean()
    return {"mean": float(np.mean(avgs)), "ci_lo": float(np.percentile(avgs, 2.5)),
            "ci_hi": float(np.percentile(avgs, 97.5))}


# --------------------------------------------------------------------------- #
# Per-setup driver
# --------------------------------------------------------------------------- #
EXITS = {"fixed_1R": ("fixed", 1.0), "fixed_1.5R": ("fixed", 1.5), "trail": ("trail", None)}


def analyze_setup(exec_tf, htf_tf, rng):
    eb = load_bars(exec_tf); hb = load_bars(htf_tf)
    if eb is None or hb is None:
        return {"error": f"missing data {exec_tf}/{htf_tf}"}
    t5, o5, h5, l5, c5, v5 = eb
    t15, o15, h15, l15, c15, v15 = hb
    n = c5.size
    meta = load_meta(); mpu = money_per_unit(meta)

    a5 = atr(h5, l5, c5)
    e5 = ema(c5, EMA_EXEC)
    lab15 = htf_trend_series(c15, h15, l15)
    idx = map_htf_to_exec(t5, t15, TF_SECONDS[htf_tf])
    htf_at_exec = np.where(idx >= 0, lab15[np.clip(idx, 0, lab15.size - 1)], 0).astype(np.int8)
    cov = float(np.mean(idx >= 0))

    spread = SPREAD_SWEEP[MID_IDX]
    oos_i = int(n * IS_FRACTION)

    res = {"exec_tf": exec_tf, "htf_tf": htf_tf, "bars": int(n),
           "span_days": float((t5[-1] - t5[0]) / 86400), "mpu": mpu,
           "htf_map_coverage": cov, "sl_atr": SL_ATR, "trail_atr": TRAIL_ATR,
           "deadband": DEADBAND, "ema_htf": EMA_HTF, "ema_exec": EMA_EXEC,
           "horizon": HORIZON, "spread_sweep": SPREAD_SWEEP, "mid_spread": spread,
           "oos_start_idx": oos_i}

    res["trend_dist"] = {"up": int(np.sum(htf_at_exec == 1)),
                         "flat": int(np.sum(htf_at_exec == 0)),
                         "down": int(np.sum(htf_at_exec == -1))}

    gates = {}
    for gate in ("with", "against", "all"):
        sigs = find_signals(o5, h5, l5, c5, a5, e5, htf_at_exec, gate)
        oos = [s for s in sigs if s["i"] >= oos_i]
        g = {"n_signals_total": len(sigs), "n_signals_oos": len(oos),
             "small_sample_oos": bool(len(oos) < MIN_OOS)}
        g["oos_mid"] = {}
        for label, (ek, tp) in EXITS.items():
            r = run(h5, l5, c5, a5, oos, ek, tp, spread)
            g["oos_mid"][label] = summ(r["netR"], rng)
            if label == "fixed_1R":
                g["oos_mid"][label]["gross_expR"] = (
                    float(np.mean(r["grossR"])) if r["grossR"].size else None)
        g["walk_forward"] = {}
        for label, (ek, tp) in EXITS.items():
            g["walk_forward"][label] = walk_forward(h5, l5, c5, a5, sigs, ek, tp, spread, n, rng)
        dpf = float(np.mean([1.0 if s["dir"] > 0 else 0.0 for s in oos])) if oos else 0.5
        g["random_baseline_oos"] = {}
        for label, (ek, tp) in EXITS.items():
            g["random_baseline_oos"][label] = random_baseline(
                h5, l5, c5, a5, oos_i, n, len(oos), dpf, ek, tp, spread, rng)
        g["spread_sensitivity_fixed1R_oos"] = {}
        for sp in SPREAD_SWEEP:
            r = run(h5, l5, c5, a5, oos, "fixed", 1.0, sp)
            g["spread_sensitivity_fixed1R_oos"][f"spread_{sp}"] = summ(r["netR"], rng)
        gates[gate] = g
    res["gates"] = gates
    return res


def cell_is_edge(cell, wf, rb):
    if cell["n"] < MIN_OOS or not cell.get("ci_pos"):
        return False
    if not (wf and wf["pooled_oos"].get("ci_pos")):
        return False
    if rb and cell["expR"] is not None and cell["expR"] <= rb["ci_hi"]:
        return False
    return True


def verdict(res_by_setup):
    any_data = any_edge = False
    detail = {}
    for key, r in res_by_setup.items():
        if "error" in r:
            continue
        any_data = True
        edge_here = False
        for gate in ("with", "against", "all"):
            g = r["gates"][gate]
            for label in EXITS:
                cell = g["oos_mid"][label]
                wf = g["walk_forward"][label]
                rb = g["random_baseline_oos"][label]
                if cell_is_edge(cell, wf, rb):
                    edge_here = True; any_edge = True
                    detail[f"{key}.{gate}.{label}"] = "EDGE"
        if not edge_here:
            detail[key] = "no_edge"
    if any_edge:
        return "EDGE", detail
    return ("NO_EDGE" if any_data else "INCONCLUSIVE"), detail


def fmt(x):
    return "  n/a" if x is None else f"{x:+.3f}"


def best_cell(res_by_setup):
    best = None
    for key, r in res_by_setup.items():
        if "error" in r:
            continue
        for gate in ("with",):
            g = r["gates"][gate]
            for label in EXITS:
                cell = g["oos_mid"][label]
                if cell["n"] < 1:
                    continue
                wf = g["walk_forward"][label]; rb = g["random_baseline_oos"][label]
                is_edge = cell_is_edge(cell, wf, rb)
                score = (1 if is_edge else 0, cell["expR"] if cell["expR"] is not None else -9)
                cand = {"key": key, "gate": gate, "exit": label, "cell": cell,
                        "wf": wf, "rb": rb, "is_edge": is_edge, "score": score,
                        "exec_tf": r["exec_tf"]}
                if best is None or score > best["score"]:
                    best = cand
    return best


def main():
    rng = np.random.default_rng(SEED)
    print("=" * 92)
    print("with_trend_pullback_lab — USDJPYm WITH-trend EMA20 pullback-resume, HTF EMA50-slope gate")
    print(f"setups={SETUPS} | HTF deadband |slope/ATR|<= {DEADBAND} | SL={SL_ATR}ATR TP={TP_RS}R trail={TRAIL_ATR}ATR")
    print(f"horizon={HORIZON} bars | spread sweep={SPREAD_SWEEP} (mid={SPREAD_SWEEP[MID_IDX]}) | OOS67/33 + walk-fwd{N_BLOCKS} boot={BOOT}")
    print("PRIOR: USDJPY +0.3R lean GROSS & not significant (pooled n~1100 t<1.9). Expect NO_EDGE net-of-cost.")
    print("=" * 92)
    res_by_setup = {}
    for exec_tf, htf_tf in SETUPS:
        key = f"{exec_tf}_x_{htf_tf}"
        r = analyze_setup(exec_tf, htf_tf, rng)
        res_by_setup[key] = r
        if "error" in r:
            print(f"\n{key}: ERROR {r['error']}"); continue
        td = r["trend_dist"]; tot = sum(td.values())
        print(f"\n{'#'*92}\n{key}  exec={exec_tf} HTF={htf_tf}  bars={r['bars']} span={r['span_days']:.0f}d "
              f"$/unit/lot={r['mpu']:.3f}  HTFmap={100*r['htf_map_coverage']:.1f}%")
        print(f"  trend@exec: UP={100*td['up']/tot:.0f}% FLAT={100*td['flat']/tot:.0f}% DOWN={100*td['down']/tot:.0f}%")
        for gate in ("with", "against", "all"):
            g = r["gates"][gate]
            print(f"  -- gate={gate.upper():<7} signals tot={g['n_signals_total']} OOS={g['n_signals_oos']}"
                  f"{'  [SMALL OOS]' if g['small_sample_oos'] else ''}")
            for label in EXITS:
                s = g["oos_mid"][label]; ci = s["ci95"]
                cis = f"[{fmt(ci[0])},{fmt(ci[1])}]" if ci else "n/a"
                gross = s.get("gross_expR")
                gx = f" gross={fmt(gross)}" if gross is not None else ""
                wf = g["walk_forward"][label]["pooled_oos"]; wci = wf["ci95"]
                wcs = f"[{fmt(wci[0])},{fmt(wci[1])}]" if wci else "n/a"
                rb = g["random_baseline_oos"][label]
                rbs = f"rndCI=[{fmt(rb['ci_lo'])},{fmt(rb['ci_hi'])}]" if rb else "rnd n/a"
                wrp = 'n/a' if s['wr'] is None else f"{100*s['wr']:.0f}%"
                tval = 'n/a' if s['t_stat'] is None else f"{s['t_stat']:+.2f}"
                print(f"       {label:<10} n={s['n']:<4} expR={fmt(s['expR'])}{gx} wr={wrp} t={tval} "
                      f"OOSci={cis}{' CI>0' if s['ci_pos'] else ''} | wf-pooled n={wf['n']} {fmt(wf['expR'])} {wcs}"
                      f"{' WF+' if wf['ci_pos'] else ''} | {rbs}")

    v, detail = verdict(res_by_setup)
    bc = best_cell(res_by_setup)
    print("\n" + "=" * 92)
    print(f"VERDICT (with-trend pullback has net edge?): {v}")
    print(f"  detail={detail}")
    if bc:
        cell = bc["cell"]; wf = bc["wf"]["pooled_oos"]; rb = bc["rb"]
        print(f"  BEST with-trend cell: {bc['key']} exit={bc['exit']} -> n={cell['n']} expR={fmt(cell['expR'])} "
              f"t={'n/a' if cell['t_stat'] is None else f'{cell['t_stat']:+.2f}'} CI={cell['ci95']} "
              f"WFpooled={fmt(wf['expR'])}(n{wf['n']},{'+' if wf['ci_pos'] else '-'}) "
              f"rndCIhi={None if not rb else round(rb['ci_hi'],4)} EDGE={bc['is_edge']}")
    print("=" * 92)

    out = {"ts": datetime.now(timezone.utc).isoformat(),
           "symbol": SYMBOL, "config": {
               "setups": SETUPS, "ema_htf": EMA_HTF, "slope_lookback": SLOPE_LOOKBACK,
               "atr_period": ATR_PERIOD, "deadband": DEADBAND, "ema_exec": EMA_EXEC,
               "sl_atr": SL_ATR, "tp_Rs": list(TP_RS), "trail_atr": TRAIL_ATR,
               "horizon": HORIZON, "spread_sweep": SPREAD_SWEEP, "mid_idx": MID_IDX,
               "n_blocks": N_BLOCKS, "is_fraction": IS_FRACTION, "min_oos": MIN_OOS,
               "boot": BOOT, "seed": SEED,
               "no_lookahead": "HTF EMA50/slope50/ATR14 on closed HTF bars only; mapped to exec bar via "
                               "last HTF bar with open+htf_sec<=t_exec[i]; exec EMA20/ATR14 use bars<=i-1 "
                               "(referenced at i-1); entry=open[i+1]; fwd sim reads bars>entry; trail off "
                               "closed bars; intrabar SL-first; walk-fwd block0=burn-in",
               "cost": "round-trip spread subtracted in R per trade (spread_price/R), USDJPY ~1.5pip=0.015 mid"},
           "verdict": v, "verdict_detail": detail, "best_with_trend_cell": (
               None if not bc else {"key": bc["key"], "exit": bc["exit"],
                                    "is_edge": bc["is_edge"], "cell": bc["cell"]}),
           "results": res_by_setup}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(RESULTS, "w", encoding="utf-8"), indent=2)
    print(f"\nSaved -> {RESULTS}")
    return out


if __name__ == "__main__":
    main()
