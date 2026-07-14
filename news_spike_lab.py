"""news_spike_lab.py — Does FADING (or RIDING) a butter-hour spike pay, NET of
the WIDE news spread? (XAUUSDm + US30m, M5)

WHY THIS EXISTS
    User's idea: during the "butter hour" (ساعة الزبدة = NY open / news window,
    ~12:30-15:30 UTC) the market explodes. He wants: sharp spike UP -> place a
    BIG SELL stop below it (FADE); sharp spike DOWN -> BIG BUY stop above (FADE).
    And the opposite (RIDE, enter WITH the spike) as the comparison.

    We ALREADY tested generic spike fading on gold M5 k=2 and it was a
    significant LOSER: avg -0.18R, net -$68 (data/lab_cache/spike_fade_lab_results.json),
    and RIDING showed no edge (spike_ride_results.json). The NEW question here
    is narrower and fairer to the user's actual claim:
        (a) Does restricting to the BUTTER HOUR change the verdict vs all-hours?
        (b) Does the realistic WIDE news spread (NOT the tight spread) kill it?
           — because the user's whole premise lives in the high-spread moment.

WHAT IT DOES (honest, falsifiable, no-lookahead) — reuses the prior detection
    logic verbatim (spike = |bar move| >= k*ATR(14), confirmed at bar CLOSE):
    1. SPIKE = |close[i] - open[i]| >= K * ATR[i-1].  Causal: ATR uses bars
       <= i-1, the bar i is fully formed at its close. We classify each spike as
       BUTTER (12:30 <= UTC time-of-day < 15:30) vs OTHER hours.
       (Unlike the continuation-filtered exit lab, we take BOTH up and down
       spikes regardless of trend, because the user's rule is purely directional
       off the spike sign — fade up-spikes, fade down-spikes.)
    2. FADE: a spike UP -> SELL; a spike DOWN -> BUY. Entry at the spike-bar
       CLOSE (the "stop" would fill ~there once price pulls back a tick; we model
       fill at close, then charge the full WIDE round-trip spread as cost, which
       is conservative for a stop entry). SL = beyond the spike extreme
       (long fade-of-down-spike: SL = low - buf; short fade-of-up-spike:
       SL = high + buf), buf = SL_ATR_BUF * ATR. R = |entry - SL|. TP at 1R and
       1.5R. Time horizon HORIZON bars. Intrabar pessimism: if a bar spans both
       SL and TP, SL is assumed hit first.
       RIDE: identical machinery but direction = spike sign (buy up-spikes).
    3. REALISTIC NEWS SPREAD: cost is the WIDE spread at the spike moment, NOT
       the calm spread. We sweep several values per symbol (gold $0.50/$1.00/$1.50,
       US30 $3/$5/$8) and show the sensitivity. Cost is charged round-trip in R
       (spread_price / R) on every trade. Reported expectancy is NET.
    4. WALK-FORWARD OOS: 4 sequential time blocks. Block 1 is burn-in / IS only;
       blocks 2..4 are OOS (we only ever judge on data after an earlier block).
       We also report the simple 67/33 latest-OOS for continuity with the prior
       labs. Bootstrap 2000x for a 95% CI on OOS expectancy. EDGE requires the
       OOS expectancy CI to sit strictly > 0 at the realistic mid spread.
    5. BIG-LOT RUIN: for the FADE, when the spike KEEPS GOING (doesn't fade), a
       big lot bleeds fast. We measure: P(spike continues vs reverts) within the
       horizon, the worst single-trade R (and $ on a deliberately big lot), and
       the continuation tail — the user's downside if he sizes up.
    6. RANDOM BASELINE: same count / same direction mix / same exit on random
       bars in the SAME OOS region, bootstrapped. If the strategy's OOS expR
       doesn't clear the random 95% CI, the "edge" is random-bar noise.

DATA
    data/lab_cache/{XAUUSDm,US30m}_M5.npz  (t,o,h,l,c,v) — 40k M5 bars each.
    data/lab_cache/<SYM>_meta.json (trade_tick_value/point) for $ conversion.

RUN
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\news_spike_lab.py

NOTE: read-only research. No MT5 connection, no order_send. Writes JSON to
    data/lab_cache/news_spike_lab_results.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "data", "lab_cache")
RESULTS_PATH = os.path.join(CACHE_DIR, "news_spike_lab_results.json")

SYMBOLS = ["XAUUSDm", "US30m"]
TF = "M5"

ATR_PERIOD = 14
SPIKE_K = 2.0              # spike = |close-open| >= 2*ATR (matches prior labs)
SL_ATR_BUF = 0.25         # SL placed this many ATR beyond the spike extreme
TP_RS = (1.0, 1.5)        # take-profits per the user's spec (1R, 1.5R)
HORIZON = 12              # forward bars = 1h on M5 (time stop)

# Butter hour = NY open / news window, UTC time-of-day in [START, END)
BUTTER_START_H, BUTTER_START_M = 12, 30   # 12:30 UTC
BUTTER_END_H, BUTTER_END_M = 15, 30       # 15:30 UTC

# Realistic WIDE news spreads (round-trip, PRICE units). Sweep low/mid/high.
# These are the moment-of-news spreads, deliberately wide (not the calm spread).
NEWS_SPREAD_SWEEP = {
    "XAUUSDm": [0.50, 1.00, 1.50],   # gold dollars
    "US30m":   [3.0, 5.0, 8.0],      # Dow index points
}
MID_IDX = 1  # index into the sweep used as the "realistic" headline number

N_BLOCKS = 4              # walk-forward blocks (block 0 = burn-in/IS)
IS_FRACTION = 0.67        # for the continuity 67/33 OOS report
MIN_OOS = 30              # below -> small_sample flag
BOOT = 2000
SEED = 11

BIG_LOT = 1.0            # the "big lot" the user imagines sizing up to (1.00)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_bars(symbol: str):
    path = os.path.join(CACHE_DIR, f"{symbol}_{TF}.npz")
    if not os.path.exists(path):
        return None
    d = np.load(path)
    return (d["t"].astype(np.int64), d["o"].astype(np.float64),
            d["h"].astype(np.float64), d["l"].astype(np.float64),
            d["c"].astype(np.float64), d["v"].astype(np.float64))


def load_meta(symbol: str) -> dict:
    path = os.path.join(CACHE_DIR, f"{symbol}_meta.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def money_per_price_per_lot(meta: dict) -> float:
    """$ per 1.0 price-unit move per 1.00 lot = tick_value / tick_size."""
    tv = meta.get("trade_tick_value")
    ts = meta.get("trade_tick_size") or meta.get("point")
    if tv and ts and ts > 0:
        return float(tv) / float(ts)
    return 1.0


# ---------------------------------------------------------------------------
# Indicators (causal)
# ---------------------------------------------------------------------------
def atr(h, l, c, period=ATR_PERIOD):
    n = h.size
    prev_c = np.empty(n)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out = np.full(n, np.nan)
    if n >= period:
        csum = np.cumsum(tr)
        out[period - 1:] = (csum[period - 1:] - np.concatenate(([0.0], csum[:-period]))) / period
    return out


def in_butter(ts: int) -> bool:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    mins = dt.hour * 60 + dt.minute
    lo = BUTTER_START_H * 60 + BUTTER_START_M
    hi = BUTTER_END_H * 60 + BUTTER_END_M
    return lo <= mins < hi


# ---------------------------------------------------------------------------
# Spike detection (CAUSAL): |close-open| >= K*ATR[i-1]; entry = close[i]
# ---------------------------------------------------------------------------
def find_spikes(t, o, h, l, c, a, k=SPIKE_K):
    """Return list of dict spikes. direction = sign of the spike bar body.

    No continuation/trend filter — the user's rule is purely directional off
    the spike itself. Causal: everything is known at the close of bar i.
    """
    n = c.size
    out = []
    for i in range(ATR_PERIOD + 1, n - 1):  # leave >=1 fwd bar
        av = a[i - 1]
        if not np.isfinite(av) or av <= 0:
            continue
        body = c[i] - o[i]
        if abs(body) < k * av:
            continue
        spike_dir = 1 if body > 0 else -1   # +1 = up-spike, -1 = down-spike
        out.append({
            "i": i,
            "spike_dir": spike_dir,
            "close": float(c[i]),
            "high": float(h[i]),
            "low": float(l[i]),
            "atr": float(av),
            "butter": bool(in_butter(t[i])),
            "move": float(abs(body)),
        })
    return out


# ---------------------------------------------------------------------------
# Forward exit sim (no-lookahead within trade; intrabar SL-first = pessimistic)
# Returns dict: gross_R (before cost), continued (bool: did spike keep going),
#               mfa_R (max favorable), maa_R (max adverse) within horizon.
# ---------------------------------------------------------------------------
def sim_trade(h, l, c, entry_idx, trade_dir, entry, sl, tp_R, horizon):
    n = c.size
    R = abs(entry - sl)
    if R <= 0:
        return None
    if trade_dir > 0:
        tp = entry + tp_R * R
    else:
        tp = entry - tp_R * R
    last = entry_idx + horizon
    if last >= n:
        return None
    maa = 0.0  # max adverse excursion (R, positive number)
    mfa = 0.0  # max favorable excursion (R)
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        # excursions
        if trade_dir > 0:
            fav = (hi - entry) / R
            adv = (entry - lo) / R
        else:
            fav = (entry - lo) / R
            adv = (hi - entry) / R
        if fav > mfa:
            mfa = fav
        if adv > maa:
            maa = adv
        hit_sl = (lo <= sl) if trade_dir > 0 else (hi >= sl)
        hit_tp = (hi >= tp) if trade_dir > 0 else (lo <= tp)
        if hit_sl and hit_tp:
            return {"gross_R": -1.0, "exit": "sl_pessim", "mfa_R": mfa, "maa_R": maa}
        if hit_sl:
            return {"gross_R": -1.0, "exit": "sl", "mfa_R": mfa, "maa_R": maa}
        if hit_tp:
            return {"gross_R": float(tp_R), "exit": "tp", "mfa_R": mfa, "maa_R": maa}
    exit_px = c[last]
    rr = (exit_px - entry) / R if trade_dir > 0 else (entry - exit_px) / R
    return {"gross_R": float(rr), "exit": "time", "mfa_R": mfa, "maa_R": maa}


def build_trade(sp, style):
    """Return (trade_dir, entry, sl) for FADE or RIDE on a spike, else None.

    FADE: trade against the spike. up-spike -> SELL (SL above the high);
          down-spike -> BUY (SL below the low).
    RIDE: trade with the spike. up-spike -> BUY (SL below the low);
          down-spike -> SELL (SL above the high).
    SL placed SL_ATR_BUF*ATR beyond the spike extreme on the protective side.
    """
    buf = SL_ATR_BUF * sp["atr"]
    entry = sp["close"]
    if style == "fade":
        trade_dir = -sp["spike_dir"]
    else:  # ride
        trade_dir = sp["spike_dir"]
    if trade_dir > 0:   # long -> SL below the bar low
        sl = sp["low"] - buf
        if entry - sl <= 0:
            return None
    else:               # short -> SL above the bar high
        sl = sp["high"] + buf
        if sl - entry <= 0:
            return None
    return trade_dir, entry, float(sl)


# ---------------------------------------------------------------------------
# Run a set of spikes through a style at a given spread, one TP. Returns arrays.
# ---------------------------------------------------------------------------
def run_set(h, l, c, spikes, style, tp_R, spread_price):
    net_R, gross_R, continued, maa, mfa, dirs = [], [], [], [], [], []
    for sp in spikes:
        bt = build_trade(sp, style)
        if bt is None:
            continue
        trade_dir, entry, sl = bt
        R = abs(entry - sl)
        sim = sim_trade(h, l, c, sp["i"], trade_dir, entry, sl, tp_R, HORIZON)
        if sim is None:
            continue
        cost_R = spread_price / R
        net_R.append(sim["gross_R"] - cost_R)
        gross_R.append(sim["gross_R"])
        # "continued" = spike kept going in its original direction past entry
        # i.e. for a FADE (trade against spike) the spike continuing = adverse.
        # We measure continuation in the SPIKE's own direction:
        #   spike up & price went further up than down within horizon.
        continued.append(sim["maa_R"] if style == "fade" else None)
        maa.append(sim["maa_R"])
        mfa.append(sim["mfa_R"])
        dirs.append(trade_dir)
    return {
        "net_R": np.asarray(net_R, dtype=np.float64),
        "gross_R": np.asarray(gross_R, dtype=np.float64),
        "maa_R": np.asarray(maa, dtype=np.float64),
        "mfa_R": np.asarray(mfa, dtype=np.float64),
        "dirs": np.asarray(dirs, dtype=np.int64),
    }


def boot_ci(arr, boot=BOOT, rng=None):
    if arr.size == 0:
        return None
    rng = rng or np.random.default_rng(SEED)
    means = np.empty(boot)
    n = arr.size
    for b in range(boot):
        means[b] = np.mean(arr[rng.integers(0, n, n)])
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def summ(arr, rng=None):
    if arr.size == 0:
        return {"n": 0, "expR": None, "wr": None, "ci95": None}
    ci = boot_ci(arr, rng=rng)
    return {
        "n": int(arr.size),
        "expR": float(np.mean(arr)),
        "wr": float(np.mean(arr > 0)),
        "ci95": ci,
        "ci_crosses_0": bool(ci is not None and ci[0] <= 0 <= ci[1]),
        "ci_pos": bool(ci is not None and ci[0] > 0),
    }


# ---------------------------------------------------------------------------
# Random baseline: random OOS bars, same N, same dir mix, same exit/spread.
# ---------------------------------------------------------------------------
def random_baseline(h, l, c, a, oos_lo, oos_hi, n_entries, dir_pos_frac,
                    tp_R, spread_price, rng, boot=BOOT):
    n = c.size
    valid = [i for i in range(max(oos_lo, ATR_PERIOD + 1), min(oos_hi, n - HORIZON - 1))
             if np.isfinite(a[i - 1]) and a[i - 1] > 0]
    valid = np.asarray(valid, dtype=np.int64)
    if valid.size < 5 or n_entries < 1:
        return None
    avgs = np.empty(boot)
    for b in range(boot):
        picks = rng.choice(valid, size=n_entries, replace=True)
        dd = np.where(rng.random(n_entries) < dir_pos_frac, 1, -1)
        rs = []
        for idx, d in zip(picks, dd):
            entry = c[idx]
            buf = SL_ATR_BUF * a[idx - 1]
            sl = (l[idx] - buf) if d > 0 else (h[idx] + buf)
            R = abs(entry - sl)
            if R <= 0:
                continue
            sim = sim_trade(h, l, c, int(idx), int(d), float(entry), float(sl),
                            tp_R, HORIZON)
            if sim is not None:
                rs.append(sim["gross_R"] - spread_price / R)
        avgs[b] = np.mean(rs) if rs else 0.0
    return {"mean": float(np.mean(avgs)),
            "ci_lo": float(np.percentile(avgs, 2.5)),
            "ci_hi": float(np.percentile(avgs, 97.5))}


# ---------------------------------------------------------------------------
# Big-lot ruin analysis on the FADE (worst case when the spike continues)
# ---------------------------------------------------------------------------
def big_lot_ruin(h, l, c, spikes, spread_price, money_per_unit, meta):
    """For FADE trades: what happens to a BIG lot when the spike DOESN'T fade.

    Reports: continuation probability (spike kept going adverse >= 1R before any
    TP), worst single-trade net-R, worst single-trade $ on BIG_LOT, and the
    distribution of adverse excursion (MAA).
    """
    # NOTE: worst-R and worst-$ are DIFFERENT trades (a small-R trade can lose
    # fewer R but more $ if its stop distance is wide). We track each with its
    # OWN paired figure so the report never multiplies mismatched numbers.
    worst_R = 0.0           # the worst net-R trade
    worst_R_money = 0.0     # ... and that same trade's $ on BIG_LOT
    worst_money = 0.0       # the worst $ trade on BIG_LOT
    worst_money_R = 0.0     # ... and that same trade's net-R
    maa_list = []
    cont = 0
    rev = 0
    nt = 0
    big_loss_money = []  # $ loss on big lot for losing trades
    for sp in spikes:
        bt = build_trade(sp, "fade")
        if bt is None:
            continue
        trade_dir, entry, sl = bt
        R = abs(entry - sl)
        # use the 1R TP for the ruin framing (user's primary target)
        sim = sim_trade(h, l, c, sp["i"], trade_dir, entry, sl, TP_RS[0], HORIZON)
        if sim is None:
            continue
        nt += 1
        net_R = sim["gross_R"] - spread_price / R
        maa_list.append(sim["maa_R"])
        # continuation = the spike went further in its own direction (adverse to
        # the fade) by at least 1R before reverting (i.e. SL-ish risk realized)
        if sim["maa_R"] >= 1.0:
            cont += 1
        else:
            rev += 1
        # $ outcome on BIG_LOT: net_R * R(price) * money_per_unit * lot
        money = net_R * R * money_per_unit * BIG_LOT
        if net_R < worst_R:
            worst_R = net_R
            worst_R_money = money       # pair: $ OF the worst-R trade
        if money < worst_money:
            worst_money = money
            worst_money_R = net_R       # pair: R OF the worst-$ trade
        if money < 0:
            big_loss_money.append(money)
    maa_arr = np.asarray(maa_list, dtype=np.float64)
    return {
        "n_fade_trades": int(nt),
        "p_continue_ge_1R": float(cont / nt) if nt else None,
        "p_revert": float(rev / nt) if nt else None,
        "worst_single_R": float(worst_R),
        "worst_single_R_money_biglot": float(worst_R_money),
        "worst_single_money_biglot": float(worst_money),
        "worst_single_money_R": float(worst_money_R),
        "biglot_lot": BIG_LOT,
        "maa_R_p50": float(np.percentile(maa_arr, 50)) if maa_arr.size else None,
        "maa_R_p90": float(np.percentile(maa_arr, 90)) if maa_arr.size else None,
        "maa_R_p99": float(np.percentile(maa_arr, 99)) if maa_arr.size else None,
        "mean_loss_money_biglot": (float(np.mean(big_loss_money))
                                   if big_loss_money else None),
    }


# ---------------------------------------------------------------------------
# Walk-forward across N_BLOCKS sequential blocks (judge blocks 2..N as OOS)
# ---------------------------------------------------------------------------
def walk_forward(h, l, c, spikes, style, tp_R, spread_price, n, rng):
    """Split spikes by their bar index into N_BLOCKS equal time blocks.
    Block 0 = burn-in (IS, discarded). Blocks 1..N-1 are reported OOS, plus a
    pooled OOS over blocks 1..N-1. Returns per-block expR and pooled summary.
    """
    edges = [int(n * k / N_BLOCKS) for k in range(N_BLOCKS + 1)]
    per_block = []
    pooled = []
    for b in range(N_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        blk = [s for s in spikes if lo <= s["i"] < hi]
        r = run_set(h, l, c, blk, style, tp_R, spread_price)
        s = summ(r["net_R"], rng=rng)
        s["block"] = b
        s["is_burn_in"] = (b == 0)
        per_block.append(s)
        if b >= 1:
            pooled.append(r["net_R"])
    pooled_arr = np.concatenate(pooled) if pooled else np.array([])
    return {"per_block": per_block, "pooled_oos": summ(pooled_arr, rng=rng)}


# ---------------------------------------------------------------------------
# Per-symbol driver
# ---------------------------------------------------------------------------
def analyze(symbol, rng):
    bars = load_bars(symbol)
    if bars is None:
        return {"error": "no data"}
    t, o, h, l, c, v = bars
    n = c.size
    meta = load_meta(symbol)
    mpu = money_per_price_per_lot(meta)
    a = atr(h, l, c)

    spikes = find_spikes(t, o, h, l, c, a)
    butter = [s for s in spikes if s["butter"]]
    other = [s for s in spikes if not s["butter"]]

    spreads = NEWS_SPREAD_SWEEP.get(symbol, [0.0])
    mid_spread = spreads[MID_IDX]

    # 67/33 latest-OOS (continuity with prior labs)
    oos_start_idx = int(n * IS_FRACTION)
    def oos_subset(lst):
        return [s for s in lst if s["i"] >= oos_start_idx]

    result = {
        "symbol": symbol, "tf": TF, "bars": int(n),
        "money_per_price_unit_per_lot": mpu,
        "spike_k": SPIKE_K, "sl_atr_buf": SL_ATR_BUF, "horizon_bars": HORIZON,
        "tp_Rs": list(TP_RS),
        "news_spread_sweep": spreads, "mid_spread": mid_spread,
        "n_spikes_total": len(spikes),
        "n_spikes_butter": len(butter),
        "n_spikes_other": len(other),
        "butter_window_utc": f"{BUTTER_START_H:02d}:{BUTTER_START_M:02d}-{BUTTER_END_H:02d}:{BUTTER_END_M:02d}",
    }

    # ---- spread sensitivity table: OOS (67/33) expR for each style/TP/spread ----
    groups = {"butter": oos_subset(butter), "other": oos_subset(other),
              "all": oos_subset(spikes)}
    sens = {}
    for gname, glist in groups.items():
        sens[gname] = {}
        for style in ("fade", "ride"):
            sens[gname][style] = {}
            for tp_R in TP_RS:
                tpk = f"TP{tp_R}R"
                sens[gname][style][tpk] = {}
                for sp_price in spreads:
                    r = run_set(h, l, c, glist, style, tp_R, sp_price)
                    sens[gname][style][tpk][f"spread_{sp_price}"] = summ(
                        r["net_R"], rng=rng)
    result["oos_67_33_spread_sensitivity"] = sens
    result["small_sample_butter_oos"] = bool(len(oos_subset(butter)) < MIN_OOS)

    # ---- headline: butter vs all-hours FADE & RIDE at MID spread, TP1R ----
    def headline(glist, style):
        r = run_set(h, l, c, glist, style, TP_RS[0], mid_spread)
        s = summ(r["net_R"], rng=rng)
        return s
    result["headline_mid_spread_TP1R"] = {
        "fade_butter_oos": headline(oos_subset(butter), "fade"),
        "fade_all_oos": headline(oos_subset(spikes), "fade"),
        "ride_butter_oos": headline(oos_subset(butter), "ride"),
        "ride_all_oos": headline(oos_subset(spikes), "ride"),
    }

    # ---- walk-forward (4 blocks) on butter-fade, all-fade, butter-ride ----
    result["walk_forward_mid_spread_TP1R"] = {
        "fade_butter": walk_forward(h, l, c, butter, "fade", TP_RS[0], mid_spread, n, rng),
        "fade_all": walk_forward(h, l, c, spikes, "fade", TP_RS[0], mid_spread, n, rng),
        "ride_butter": walk_forward(h, l, c, butter, "ride", TP_RS[0], mid_spread, n, rng),
        "ride_all": walk_forward(h, l, c, spikes, "ride", TP_RS[0], mid_spread, n, rng),
    }

    # ---- random baseline (OOS region) for butter-fade & all-fade at mid spread, TP1R ----
    dpf_butter = (np.mean([1.0 if (-s["spike_dir"]) > 0 else 0.0
                           for s in oos_subset(butter)]) if oos_subset(butter) else 0.5)
    dpf_all = (np.mean([1.0 if (-s["spike_dir"]) > 0 else 0.0
                        for s in oos_subset(spikes)]) if oos_subset(spikes) else 0.5)
    nb = len(oos_subset(butter))
    na = len(oos_subset(spikes))
    result["random_baseline_mid_spread_TP1R"] = {
        "fade_butter": random_baseline(h, l, c, a, oos_start_idx, n, nb,
                                       float(dpf_butter), TP_RS[0], mid_spread, rng),
        "fade_all": random_baseline(h, l, c, a, oos_start_idx, n, na,
                                    float(dpf_all), TP_RS[0], mid_spread, rng),
    }

    # ---- big-lot ruin (FADE, mid spread, TP1R) on butter spikes (OOS) ----
    result["big_lot_ruin_fade_butter_oos_mid_spread"] = big_lot_ruin(
        h, l, c, oos_subset(butter), mid_spread, mpu, meta)
    result["big_lot_ruin_fade_all_oos_mid_spread"] = big_lot_ruin(
        h, l, c, oos_subset(spikes), mid_spread, mpu, meta)

    return result


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
def verdict_for(style_key, res_by_sym):
    """EDGE only if, for ANY symbol, the butter-OOS expectancy CI is strictly
    > 0 at the MID (realistic) news spread AND beats the random baseline; else
    NO_EDGE. INCONCLUSIVE if every relevant cell is small_sample / missing."""
    any_data = False
    any_edge = False
    for sym, res in res_by_sym.items():
        if "error" in res:
            continue
        hl = res["headline_mid_spread_TP1R"].get(f"{style_key}_butter_oos")
        if hl is None or hl.get("n", 0) == 0:
            continue
        any_data = True
        if hl.get("n", 0) < MIN_OOS:
            continue
        ci_pos = bool(hl.get("ci_pos"))
        # random baseline check (fade has baseline; ride: use sign of expR + CI)
        beats_rand = True
        if style_key == "fade":
            base = res["random_baseline_mid_spread_TP1R"].get("fade_butter")
            if base is not None and hl.get("expR") is not None:
                beats_rand = hl["expR"] > base["ci_hi"]
        if ci_pos and beats_rand:
            any_edge = True
    if any_edge:
        return "EDGE"
    if any_data:
        return "NO_EDGE"
    return "INCONCLUSIVE"


def fmt(x):
    return "  n/a" if x is None else f"{x:+.3f}"


def fmt_pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


# ---------------------------------------------------------------------------
def main():
    rng = np.random.default_rng(SEED)
    print("=" * 84)
    print("news_spike_lab — FADE vs RIDE a butter-hour spike, NET of WIDE news spread")
    print(f"spike=|close-open|>={SPIKE_K}*ATR(14) causal | butter={BUTTER_START_H:02d}:{BUTTER_START_M:02d}"
          f"-{BUTTER_END_H:02d}:{BUTTER_END_M:02d} UTC | TP={TP_RS}R horizon={HORIZON}bars"
          f" | OOS 67/33 + walk-fwd {N_BLOCKS} blocks | boot={BOOT}")
    print("PRIOR RESULT (data/lab_cache): generic gold M5 k2 FADE = -0.18R, net -$68 (significant LOSER).")
    print("=" * 84)

    res_by_sym = {}
    for sym in SYMBOLS:
        r = analyze(sym, rng)
        res_by_sym[sym] = r
        if "error" in r:
            print(f"\n{sym}: ERROR -> {r['error']}")
            continue
        print(f"\n{'#'*84}\n{sym} {TF}  bars={r['bars']}  spikes total={r['n_spikes_total']} "
              f"(butter={r['n_spikes_butter']}, other={r['n_spikes_other']})  "
              f"$/unit/lot={r['money_per_price_unit_per_lot']:.3f}")
        mid = r["mid_spread"]
        hl = r["headline_mid_spread_TP1R"]
        print(f"  -- HEADLINE @ mid news spread={mid} (price), TP1R, OOS 67/33 --")
        for k in ("fade_butter_oos", "fade_all_oos", "ride_butter_oos", "ride_all_oos"):
            s = hl[k]
            ci = s["ci95"]
            cistr = f"[{fmt(ci[0])},{fmt(ci[1])}]" if ci else "n/a"
            print(f"    {k:<18} n={s['n']:<4} expR={fmt(s['expR'])} wr={fmt_pct(s['wr'])} "
                  f"CI95={cistr} {'CI>0' if s.get('ci_pos') else ''}")
        # random baseline
        rb = r["random_baseline_mid_spread_TP1R"]
        for k in ("fade_butter", "fade_all"):
            b = rb[k]
            if b:
                print(f"    random {k:<11} avg-R CI95=[{fmt(b['ci_lo'])},{fmt(b['ci_hi'])}] (mean {fmt(b['mean'])})")
        # spread sensitivity (butter fade TP1R)
        print(f"  -- SPREAD SENSITIVITY (butter FADE, TP1R, OOS) --")
        sens = r["oos_67_33_spread_sensitivity"]["butter"]["fade"]["TP1.0R"]
        for spk, s in sens.items():
            print(f"    {spk:<16} n={s['n']:<4} expR={fmt(s['expR'])} wr={fmt_pct(s['wr'])}")
        # walk-forward butter fade
        wf = r["walk_forward_mid_spread_TP1R"]["fade_butter"]
        blkstr = " ".join(
            f"b{b['block']}{'(IS)' if b['is_burn_in'] else ''}={fmt(b['expR'])}(n{b['n']})"
            for b in wf["per_block"])
        po = wf["pooled_oos"]
        poci = po["ci95"]
        print(f"  -- WALK-FWD butter FADE @mid TP1R: {blkstr}")
        print(f"     pooled OOS expR={fmt(po['expR'])} n={po['n']} "
              f"CI95={f'[{fmt(poci[0])},{fmt(poci[1])}]' if poci else 'n/a'}")
        # big-lot ruin
        rn = r["big_lot_ruin_fade_butter_oos_mid_spread"]
        print(f"  -- BIG-LOT RUIN (FADE butter, lot={rn['biglot_lot']}, mid spread) --")
        print(f"     P(spike continues>=1R)={fmt_pct(rn['p_continue_ge_1R'])}  "
              f"P(revert)={fmt_pct(rn['p_revert'])}")
        print(f"     worst-R trade={fmt(rn['worst_single_R'])}R (=${rn['worst_single_R_money_biglot']:.2f}); "
              f"worst-$ trade=${rn['worst_single_money_biglot']:.2f} (={fmt(rn['worst_single_money_R'])}R) "
              f"[DIFFERENT trades]")
        print(f"     MAA(adverse) p50={fmt(rn['maa_R_p50'])}R p90={fmt(rn['maa_R_p90'])}R "
              f"p99={fmt(rn['maa_R_p99'])}R")

    fade_v = verdict_for("fade", res_by_sym)
    ride_v = verdict_for("ride", res_by_sym)

    print("\n" + "=" * 84)
    print(f"VERDICT  FADE (butter, mid news spread, OOS): {fade_v}")
    print(f"VERDICT  RIDE (butter, mid news spread, OOS): {ride_v}")
    print("=" * 84)

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "config": {
            "symbols": SYMBOLS, "tf": TF, "atr_period": ATR_PERIOD,
            "spike_k": SPIKE_K, "sl_atr_buf": SL_ATR_BUF, "tp_Rs": list(TP_RS),
            "horizon_bars": HORIZON,
            "butter_window_utc": f"{BUTTER_START_H:02d}:{BUTTER_START_M:02d}-{BUTTER_END_H:02d}:{BUTTER_END_M:02d}",
            "news_spread_sweep": NEWS_SPREAD_SWEEP, "mid_idx": MID_IDX,
            "n_blocks": N_BLOCKS, "is_fraction": IS_FRACTION, "min_oos": MIN_OOS,
            "boot": BOOT, "big_lot": BIG_LOT, "seed": SEED,
            "no_lookahead": "spike confirmed at bar close (bars<=i-1 for ATR); entry=close[i]; "
                            "fwd sim uses each bar's own H/L; intrabar SL-first; "
                            "walk-forward 4 blocks (block0=burn-in IS) + 67/33 latest-OOS; OOS only judged",
            "cost_model": "WIDE round-trip news spread subtracted in R per trade (spread_price/R)",
            "prior_result": "generic gold M5 k2 FADE = -0.18R net -$68 (significant loser)",
        },
        "verdicts": {"fade_butter_mid_spread": fade_v, "ride_butter_mid_spread": ride_v},
        "results": res_by_sym,
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved -> {RESULTS_PATH}")
    return out


if __name__ == "__main__":
    main()
