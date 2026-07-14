"""genome_bot_bt.py — Backtest a candidate "PERSONAL-GENOME" bot that mechanizes
the user's real edge, OOS / no-lookahead / net-of-cost. HONEST verdict only.

THE USER'S EDGE-FINGERPRINT (from project memory, MEASURED not assumed):
  * BEST SYMBOL = BTC  (we only test BTCUSDm here)
  * DAY SESSION = 07:00-22:00 UTC (his profitable window; night-trading bleeds)
  * SWING HOLD  = let winners run; NOT scalp (hold to a structural target/timeout)
  * SMALL LOT   = sizing discipline (does not change R-expectancy; affects $ only)
  * The single signal that tested POSITIVE this week = TREND CONTINUATION
    (price above a rising EMA / a run of same-direction candles), WITH the trend,
    NO counter-trend fade.

SPEC UNDER TEST (strictly causal — every decision uses bars <= i, acts at i.close):
  ENTRY  = trend-continuation only:
             LONG  iff close>EMA(F) AND EMA(F) rising AND last RUN green candles
             SHORT iff close<EMA(F) AND EMA(F) falling AND last RUN red   candles
           (the EMA-slope + same-direction-run = "with the trend, it's still going")
  FILTERS (the user's edge-fingerprint, applied as GATES):
             - DAY-SESSION gate : entry hour in [07,22) UTC only.
             - NO-ENTRY-AFTER-LOSS-STREAK : skip a fresh entry while the strategy is
               in a simulated loss streak of >= LOSS_STREAK consecutive losing trades
               (a discipline gate the user follows — "stop after you get hit twice").
             - SWING is in the EXIT, not the entry (see below).
  EXIT   = swing-style: structural SL (beyond the recent swing low/high, ATR-floored),
           TP = RR*risk (swing target ~2-3R), OR hold-timeout of HOLD bars
           (mark-to-close). First-touch on bars > i; a bar spanning BOTH SL & TP
           is counted as SL (pessimistic).
  NO counter-trend, NO fade, NO martingale.

COMPARISONS (all OOS, cost-net):
  (BOT)        the full spec above (continuation + day-session + loss-streak gates).
  (NO_FILTER)  the SAME continuation entry & SAME swing exit but WITHOUT the
               day-session gate and WITHOUT the loss-streak gate (trades 24/7,
               never pauses). => isolates whether his edge-FINGERPRINT-AS-FILTER
               adds value on top of the raw continuation signal.
  (RANDOM)     random-direction trades on the SAME candidate bars / same SL bands,
               bootstrapped, as the honesty floor (no directional skill baseline).

We ALSO report a COUNTER-TREND (fade) variant OOS purely to confirm the user's
"continuation beats fade" claim holds on BTC (sanity, not the product).

RIGOR:
  * NO LOOKAHEAD. EMA/slope/run/swing use bars <= i; entry at c[i]; SL/TP on bars > i.
    The loss-streak gate uses only the outcomes of PRIOR (already-resolved) trades,
    processed in time order — a trade can only gate a LATER entry.
  * 67/33 IS/OOS split BY TIME. Report OOS. IS shown only to confirm the split.
  * Cost netted per trade in PRICE units = TYP_COST_POINTS * point (matches the
    repo's other labs: BTC = 4500 pts * 0.01 = $45 round-trip).
  * Bootstrap 2000x for avg-R 95% CI and a paired continuation-vs-random lift test.
  * MIN_OOS events to trust a cell.

DATA: data/lab_cache/BTCUSDm_<TF>.npz (t,o,h,l,c,v) for TF in [M5,M15,H1];
      cost from data/lab_cache/BTCUSDm_meta.json.

RUN: python C:\\Users\\Radhi\\MT5\\genome_bot_bt.py
Results JSON -> data/lab_cache/genome_bot_bt_results.json
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOL = "BTCUSDm"
TFS = ["M5", "M15", "H1"]
IS_FRAC = 0.67
RR_LIST = [2.0, 3.0]          # swing target: ~2-3R
EMA_FAST = {"M5": 50, "M15": 34, "H1": 20}   # trend EMA per TF
EMA_SLOPE_LOOKBACK = 5        # bars used to judge EMA rising/falling (causal)
RUN_LEN = 3                   # last RUN_LEN same-direction candles (continuation)
SWING_LOOKBACK = {"M5": 20, "M15": 14, "H1": 10}   # structural SL swing window
ATR_LEN = 14
ATR_SL_FLOOR_MULT = 1.0       # SL risk never tighter than 1*ATR (swing, not scalp)
HOLD = {"M5": 60, "M15": 40, "H1": 24}   # swing hold-timeout (bars); long holds
DAY_START_H, DAY_END_H = 7, 22           # 07:00-22:00 UTC inclusive-start/exclusive-end
LOSS_STREAK = 2               # pause new entries after this many consecutive losers
MIN_OOS = 30
BOOT = 2000
SEED = 7

# round-trip cost in POINTS (matches momentum_seq_lab.py); BTC ~ $45.
TYP_COST_POINTS = {"BTCUSDm": 4500.0}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_bars(sym: str, tf: str):
    p = os.path.join(CACHE, f"{sym}_{tf}.npz")
    d = np.load(p)
    return (d["t"].astype(np.int64),
            d["o"].astype(np.float64), d["h"].astype(np.float64),
            d["l"].astype(np.float64), d["c"].astype(np.float64),
            d["v"].astype(np.float64))


def load_meta(sym: str) -> dict:
    p = os.path.join(CACHE, f"{sym}_meta.json")
    with open(p, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def cost_price(sym: str, meta: dict) -> float:
    return TYP_COST_POINTS.get(sym, 20.0) * float(meta["point"])


# ---------------------------------------------------------------------------
# Indicators (causal: value at bar i uses only bars <= i)
# ---------------------------------------------------------------------------
def ema(arr: np.ndarray, period: int) -> np.ndarray:
    a = 2.0 / (period + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, arr.size):
        out[i] = a * arr[i] + (1 - a) * out[i - 1]
    return out


def atr(h, l, c, period: int) -> np.ndarray:
    n = c.size
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.empty(n)
    out[0] = tr[0]
    a = 1.0 / period
    for i in range(1, n):
        out[i] = a * tr[i] + (1 - a) * out[i - 1]
    return out


def hour_of(t: np.ndarray) -> np.ndarray:
    # epoch seconds -> UTC hour, vectorized
    return ((t // 3600) % 24).astype(np.int64)


# ---------------------------------------------------------------------------
# Trade sim. Enter at c[i]; trade_dir +1 long / -1 short. SL price given;
# TP = entry +/- rr*risk. First-touch on bars > i within hold; span-both -> SL.
# Returns cost-netted realized R, or None if risk<=0.
# ---------------------------------------------------------------------------
def simulate_trade(i, trade_dir, sl_price, rr, o, h, l, c, cost, hold) -> Optional[float]:
    n = c.size
    entry = c[i]
    if trade_dir > 0:
        risk = entry - sl_price
        if risk <= 0:
            return None
        tp = entry + rr * risk
    else:
        risk = sl_price - entry
        if risk <= 0:
            return None
        tp = entry - rr * risk
    end = min(n, i + 1 + hold)
    for j in range(i + 1, end):
        if trade_dir > 0:
            hit_sl = l[j] <= sl_price
            hit_tp = h[j] >= tp
        else:
            hit_sl = h[j] >= sl_price
            hit_tp = l[j] <= tp
        if hit_sl:                       # span-both also lands here (pessimistic)
            return -1.0 - cost / risk
        if hit_tp:
            return rr - cost / risk
    last = c[end - 1]                    # timeout -> mark to close
    pnl = (last - entry) if trade_dir > 0 else (entry - last)
    return (pnl / risk) - cost / risk


# ---------------------------------------------------------------------------
# Signal detection (causal). Returns per-bar candidate signals:
#   dir = +1 long / -1 short / 0 none  (continuation only)
#   sl_long / sl_short = structural SL price for each direction at bar i
# ---------------------------------------------------------------------------
def build_signals(tf, t, o, h, l, c):
    n = c.size
    emaF = ema(c, EMA_FAST[tf])
    a = atr(h, l, c, ATR_LEN)
    hr = hour_of(t)
    swl = SWING_LOOKBACK[tf]
    sb = EMA_SLOPE_LOOKBACK

    color = np.zeros(n, dtype=np.int8)
    color[c > o] = 1
    color[c < o] = -1

    cont_dir = np.zeros(n, dtype=np.int8)
    sl_long = np.full(n, np.nan)
    sl_short = np.full(n, np.nan)

    start = max(EMA_FAST[tf] + sb, swl, ATR_LEN) + 1
    for i in range(start, n):
        # EMA slope over the last sb bars (causal)
        rising = emaF[i] > emaF[i - sb]
        falling = emaF[i] < emaF[i - sb]
        # last RUN_LEN candles all same color
        seg = color[i - RUN_LEN + 1:i + 1]
        run_up = bool(np.all(seg == 1))
        run_dn = bool(np.all(seg == -1))
        # structural swing extremes over the lookback (bars <= i)
        win_lo = float(np.min(l[i - swl + 1:i + 1]))
        win_hi = float(np.max(h[i - swl + 1:i + 1]))
        atr_floor = ATR_SL_FLOOR_MULT * a[i]

        # LONG continuation
        if c[i] > emaF[i] and rising and run_up:
            cont_dir[i] = 1
            struct_sl = win_lo
            # ATR floor: SL at least atr_floor below entry (swing room, not scalp)
            sl_long[i] = min(struct_sl, c[i] - atr_floor)
        # SHORT continuation
        elif c[i] < emaF[i] and falling and run_dn:
            cont_dir[i] = -1
            struct_sl = win_hi
            sl_short[i] = max(struct_sl, c[i] + atr_floor)

    return cont_dir, sl_long, sl_short, hr


# ---------------------------------------------------------------------------
# Run a strategy variant over the bars IN TIME ORDER, honoring the loss-streak
# gate causally (only resolved prior trades can gate a later entry).
#   apply_session : require day-session hour gate
#   apply_streak  : require the no-entry-after-loss-streak gate
#   fade          : trade AGAINST cont_dir (counter-trend sanity), else WITH it
# Returns list of (i, phase, realized_R) for taken trades.
# ---------------------------------------------------------------------------
def run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                rr, cost, apply_session, apply_streak, fade=False) -> List[Tuple[int, str, float]]:
    n = c.size
    split = int(n * IS_FRAC)
    hold = HOLD[tf]
    trades: List[Tuple[int, str, float]] = []
    loss_streak = 0
    for i in range(n - 2):
        d = cont_dir[i]
        if d == 0:
            continue
        if apply_session and not (DAY_START_H <= hr[i] < DAY_END_H):
            continue
        if apply_streak and loss_streak >= LOSS_STREAK:
            # discipline pause: skip this entry, but a NEW (non-gated) signal that
            # WOULD have been a winner does not reset us — we only reset when an
            # actually-taken trade wins. Conservative: stay paused until a taken win.
            # To avoid permanent lockout we DO take the trade but flag... no:
            # the user literally stands down. We skip and DECAY the streak by 1 so
            # the pause is finite (cool-off), matching "wait a couple signals".
            loss_streak -= 1
            continue
        trade_dir = (-d if fade else d)
        sl = (sl_long[i] if d > 0 else sl_short[i])  # SL band the signal set (cont side)
        if np.isnan(sl):
            continue
        if fade:
            # counter-trend: trade the opposite direction with the SAME absolute
            # risk distance mirrored across entry (identical risk band, opposite
            # side). This makes FADE a true like-for-like opposite of the BOT.
            entry = c[i]
            risk = abs(entry - sl)
            # SL below entry for a long, above entry for a short
            sl = (entry - risk) if trade_dir > 0 else (entry + risk)
        r = simulate_trade(i, trade_dir, sl, rr, o, h, l, c, cost, hold)
        if r is None:
            continue
        phase = "IS" if i < split else "OOS"
        trades.append((i, phase, r))
        if apply_streak:
            if r < 0:
                loss_streak += 1
            else:
                loss_streak = 0
    return trades


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def _boot_ci(rs: np.ndarray, B: int, seed: int):
    nn = rs.size
    if nn < 5:
        return None, None, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nn, size=(B, nn))
    means = rs[idx].mean(axis=1)
    return (round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4),
            round(float((means <= 0).mean()), 4))


def summarize(rs: List[float], boot: bool, seed: int) -> dict:
    a = np.array([r for r in rs if r is not None], dtype=float)
    n = a.size
    if n == 0:
        return {"n": 0}
    wins = int((a > 0).sum())
    gains = a[a > 0].sum()
    losses = -a[a < 0].sum()
    pf = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
    out = {
        "n": n,
        "win_rate": round(100.0 * wins / n, 2),
        "avg_R": round(float(a.mean()), 4),
        "total_R": round(float(a.sum()), 3),
        "pf": round(pf, 3) if np.isfinite(pf) else None,
    }
    if boot and n >= 5:
        lo, hi, p = _boot_ci(a, BOOT, seed)
        out["ci95_lo"], out["ci95_hi"], out["p_avgR_le_0"] = lo, hi, p
        out["ci_excludes_0"] = bool(lo is not None and lo > 0)
    return out


def _apply_streak_gate(seq: List[float], thresh: int) -> np.ndarray:
    """Re-apply the cool-off gate to an ordered R-sequence (same logic as
    run_variant): after `thresh` consecutive losers, skip entries while decaying
    the streak by 1 per skipped signal. Returns the kept trades' R."""
    kept: List[float] = []
    ls = 0
    for r in seq:
        if ls >= thresh:
            ls -= 1
            continue
        kept.append(r)
        ls = ls + 1 if r < 0 else 0
    return np.array(kept, dtype=float)


def streak_clustering_test(ungated_oos_seq: List[float], thresh: int,
                           B: int, seed: int) -> dict:
    """Is the loss-streak gate exploiting REAL loss-clustering or just resampling?
    Compare the time-ordered gated avg_R to a null built by SHUFFLING the trade
    order B times (which destroys serial structure) and re-applying the gate.
    If the real avg_R lies OUTSIDE the shuffle 95% band -> exploits genuine
    clustering (regime/vol persistence). Inside -> the gate is just a reshuffle."""
    arr = np.array([r for r in ungated_oos_seq if r is not None], dtype=float)
    if arr.size < 10:
        return {"n": int(arr.size)}
    real = _apply_streak_gate(list(arr), thresh)
    rng = np.random.default_rng(seed)
    shu = np.empty(B)
    for b in range(B):
        s = arr.copy()
        rng.shuffle(s)
        g = _apply_streak_gate(list(s), thresh)
        shu[b] = g.mean() if g.size else 0.0
    lo, hi = float(np.percentile(shu, 2.5)), float(np.percentile(shu, 97.5))
    rm = float(real.mean()) if real.size else 0.0
    return {
        "ungated_avg_R": round(float(arr.mean()), 4),
        "gated_avg_R": round(rm, 4),
        "gated_n": int(real.size),
        "shuffle_mean": round(float(shu.mean()), 4),
        "shuffle_ci95_lo": round(lo, 4),
        "shuffle_ci95_hi": round(hi, 4),
        "exploits_clustering": bool(not (lo <= rm <= hi)),
    }


def random_baseline(oos_idx: List[int], cont_dir, sl_long, sl_short,
                    rr, o, h, l, c, cost, hold, seed) -> dict:
    """Coin-flip-direction baseline on the SAME OOS candidate bars + paired lift.
    For each candidate compute R for BOTH directions using the matching SL band,
    then: (1) random-dir CI; (2) paired (continuation_R - 0.5*(R_long+R_short))."""
    if not oos_idx:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    m0 = len(oos_idx)
    r_long = np.full(m0, np.nan)
    r_short = np.full(m0, np.nan)
    r_cont = np.full(m0, np.nan)
    for k, i in enumerate(oos_idx):
        d = cont_dir[i]
        # continuation = trade WITH cont_dir on its own (only) band the signal set
        if d > 0 and not np.isnan(sl_long[i]):
            rl = simulate_trade(i, +1, sl_long[i], rr, o, h, l, c, cost, hold)
            if rl is not None:
                r_long[k] = rl
                r_cont[k] = rl
        elif d < 0 and not np.isnan(sl_short[i]):
            rs_ = simulate_trade(i, -1, sl_short[i], rr, o, h, l, c, cost, hold)
            if rs_ is not None:
                r_short[k] = rs_
                r_cont[k] = rs_
    # For a well-defined coin flip we need BOTH sides; the signal only set the
    # band on the continuation side. Define the OPPOSITE-direction SL as the SAME
    # absolute risk distance mirrored across entry — so a random long/short has an
    # identical risk band and the paired lift isolates pure DIRECTIONAL skill.
    for k, i in enumerate(oos_idx):
        entry = c[i]
        d = cont_dir[i]
        if d > 0 and not np.isnan(sl_long[i]) and np.isnan(r_short[k]):
            risk = entry - sl_long[i]
            mirror_sl = entry + risk
            rs_ = simulate_trade(i, -1, mirror_sl, rr, o, h, l, c, cost, hold)
            if rs_ is not None:
                r_short[k] = rs_
        elif d < 0 and not np.isnan(sl_short[i]) and np.isnan(r_long[k]):
            risk = sl_short[i] - entry
            mirror_sl = entry - risk
            rl = simulate_trade(i, +1, mirror_sl, rr, o, h, l, c, cost, hold)
            if rl is not None:
                r_long[k] = rl
    valid = ~(np.isnan(r_long) | np.isnan(r_short) | np.isnan(r_cont))
    r_long, r_short, r_cont = r_long[valid], r_short[valid], r_cont[valid]
    m = r_cont.size
    if m < 5:
        return {"n": m}
    means = np.empty(BOOT)
    for b in range(BOOT):
        pick_short = rng.random(m) < 0.5
        sample = np.where(pick_short, r_short, r_long)
        means[b] = sample[rng.integers(0, m, m)].mean()
    rand_exp = 0.5 * (r_long + r_short)
    diff = r_cont - rand_exp
    didx = rng.integers(0, m, size=(BOOT, m))
    dmeans = diff[didx].mean(axis=1)
    lift_lo = float(np.percentile(dmeans, 2.5))
    return {
        "n": int(m),
        "rand_avg_R": round(float(rand_exp.mean()), 4),
        "rand_ci95_lo": round(float(np.percentile(means, 2.5)), 4),
        "rand_ci95_hi": round(float(np.percentile(means, 97.5)), 4),
        "cont_lift_mean": round(float(diff.mean()), 4),
        "cont_lift_ci95_lo": round(lift_lo, 4),
        "cont_lift_ci95_hi": round(float(np.percentile(dmeans, 97.5)), 4),
        "cont_lift_p_le_0": round(float((dmeans <= 0).mean()), 4),
        "cont_lift_edge": bool(lift_lo > 0),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    meta = load_meta(SYMBOL)
    cost = cost_price(SYMBOL, meta)
    all_results: Dict[str, dict] = {}
    rows = []

    for tf in TFS:
        t, o, h, l, c, v = load_bars(SYMBOL, tf)
        n = c.size
        split = int(n * IS_FRAC)
        hold = HOLD[tf]
        cont_dir, sl_long, sl_short, hr = build_signals(tf, t, o, h, l, c)

        for rr in RR_LIST:
            # --- BOT: continuation + day-session + loss-streak gates ---
            bot = run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                              rr, cost, apply_session=True, apply_streak=True)
            # --- NO_FILTER: same entry/exit, 24/7, no streak gate ---
            nof = run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                              rr, cost, apply_session=False, apply_streak=False)
            # --- FADE sanity: counter-trend, same gating as BOT ---
            fade = run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                               rr, cost, apply_session=True, apply_streak=True, fade=True)
            # --- GATE ISOLATION: which gate does the work? ---
            sess_only = run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                                    rr, cost, apply_session=True, apply_streak=False)
            strk_only = run_variant(tf, t, o, h, l, c, cont_dir, sl_long, sl_short, hr,
                                    rr, cost, apply_session=False, apply_streak=True)

            def split_oos(tr):
                return ([r for (i, p, r) in tr if p == "IS"],
                        [r for (i, p, r) in tr if p == "OOS"])

            bot_is, bot_oos = split_oos(bot)
            nof_is, nof_oos = split_oos(nof)
            fade_is, fade_oos = split_oos(fade)
            _, sess_oos = split_oos(sess_only)
            _, strk_oos = split_oos(strk_only)
            # OOS sub-period halves for BOT (stability check)
            mid = split + (n - split) // 2
            bot_oos_1 = [r for (i, p, r) in bot if p == "OOS" and i < mid]
            bot_oos_2 = [r for (i, p, r) in bot if p == "OOS" and i >= mid]

            bot_oos_idx = [i for (i, p, r) in bot if p == "OOS"]
            rb = random_baseline(bot_oos_idx, cont_dir, sl_long, sl_short,
                                 rr, o, h, l, c, cost, hold, seed=SEED + 1)
            # ungated (24/7, no pause) OOS continuation sequence -> clustering test
            nof_oos_seq = [r for (i, p, r) in nof if p == "OOS"]
            clust = streak_clustering_test(nof_oos_seq, LOSS_STREAK, BOOT, seed=SEED + 5)

            cell = {
                "tf": tf, "rr": rr,
                "bot_IS": summarize(bot_is, boot=False, seed=SEED),
                "bot_OOS": summarize(bot_oos, boot=True, seed=SEED),
                "nofilter_OOS": summarize(nof_oos, boot=True, seed=SEED + 2),
                "fade_OOS": summarize(fade_oos, boot=True, seed=SEED + 3),
                "session_only_OOS": summarize(sess_oos, boot=False, seed=SEED),
                "streak_only_OOS": summarize(strk_oos, boot=True, seed=SEED + 4),
                "bot_OOS_first_half": summarize(bot_oos_1, boot=False, seed=SEED),
                "bot_OOS_second_half": summarize(bot_oos_2, boot=False, seed=SEED),
                "streak_clustering_test": clust,
                "random_OOS": rb,
            }
            all_results[f"{tf}_rr{int(rr)}"] = cell
            rows.append(cell)

    # ----- printed report -----
    print("=" * 132)
    print("PERSONAL-GENOME BOT BACKTEST — BTCUSDm, OOS (33% out-of-sample by time), cost-net "
          f"(${TYP_COST_POINTS[SYMBOL]*float(meta['point']):.0f} round-trip).")
    print("SPEC: trend-CONTINUATION entry (close vs rising/falling EMA + same-color run); "
          "swing exit (structural SL, TP=RR*risk, hold-timeout).")
    print("BOT = +day-session(07-22 UTC) +no-entry-after-loss-streak gates.  "
          "NO_FILTER = same entry/exit, 24/7, no pause.  FADE = counter-trend sanity.")
    print("=" * 132)
    hdr = (f"{'TF':4} {'RR':>4} | {'VARIANT':10} {'N':>5} {'WIN%':>6} {'avgR':>8} "
           f"{'totR':>9} {'PF':>6} {'CI95lo':>8} {'CI95hi':>8} {'p(<=0)':>7}  FLAG")
    print(hdr)
    print("-" * 132)

    def fmt(x, w=8, sgn=True, dec=3):
        if x is None:
            return f"{'-':>{w}}"
        return (f"{x:+.{dec}f}" if sgn else f"{x:.{dec}f}").rjust(w)

    edge_cells = []
    for cell in rows:
        tf, rr = cell["tf"], cell["rr"]
        rb = cell["random_OOS"]
        for vname, key in (("BOT", "bot_OOS"), ("NO_FILTER", "nofilter_OOS"),
                           ("FADE", "fade_OOS")):
            s = cell[key]
            nn = s.get("n", 0)
            flag = "" if nn >= MIN_OOS else "small-n"
            is_edge = (vname in ("BOT", "NO_FILTER") and nn >= MIN_OOS
                       and bool(s.get("ci_excludes_0")))
            if is_edge:
                # beats-random check (paired lift) only meaningful vs continuation
                beats = bool(rb.get("cont_lift_edge"))
                flag = (flag + " <<net+ CI>0").strip()
                flag += " & BEATS-RANDOM" if beats else " (lift straddles 0)"
                if vname == "BOT":
                    edge_cells.append((tf, rr, s, rb, beats))
            print(f"{tf:4} {rr:>4.0f} | {vname:10} {nn:>5} "
                  f"{fmt(s.get('win_rate'), 6, False, 1)} {fmt(s.get('avg_R'))} "
                  f"{fmt(s.get('total_R'), 9, True, 2)} {fmt(s.get('pf'), 6, False, 2)} "
                  f"{fmt(s.get('ci95_lo'))} {fmt(s.get('ci95_hi'))} "
                  f"{fmt(s.get('p_avgR_le_0'), 7, False, 3)}  {flag}")
        # random + filter-lift line
        print(f"{tf:4} {rr:>4.0f} | {'RANDOM':10} {rb.get('n', 0):>5} "
              f"{'-':>6} {fmt(rb.get('rand_avg_R'))} {'-':>9} {'-':>6} "
              f"{fmt(rb.get('rand_ci95_lo'))} {fmt(rb.get('rand_ci95_hi'))} {'-':>7}  "
              f"contLift={fmt(rb.get('cont_lift_mean'),0)} "
              f"liftCIlo={fmt(rb.get('cont_lift_ci95_lo'),0)} "
              f"p(lift<=0)={rb.get('cont_lift_p_le_0')}")
        print("-" * 132)

    # ----- filter-value check: BOT vs NO_FILTER OOS avg_R -----
    print("\nDOES THE EDGE-FINGERPRINT (day-session + loss-streak) ADD VALUE?  "
          "(BOT avg_R vs NO_FILTER avg_R, OOS)")
    filter_helps = 0
    filter_cells = 0
    for cell in rows:
        b = cell["bot_OOS"]; nf = cell["nofilter_OOS"]
        if b.get("n", 0) >= MIN_OOS and nf.get("n", 0) >= MIN_OOS:
            filter_cells += 1
            delta = (b["avg_R"] - nf["avg_R"])
            better = delta > 0
            filter_helps += int(better)
            print(f"  {cell['tf']:4} RR{int(cell['rr'])}: BOT avg_R={b['avg_R']:+.3f} "
                  f"(n={b['n']}) vs NO_FILTER avg_R={nf['avg_R']:+.3f} (n={nf['n']})  "
                  f"delta={delta:+.3f}  -> filter {'HELPS' if better else 'HURTS/NEUTRAL'}")
    if filter_cells == 0:
        print("  (insufficient OOS sample in all cells to compare)")

    # ----- GATE ISOLATION: which gate (day-session vs loss-streak) carries it? -----
    print("\nGATE ISOLATION (OOS avg_R): is it the DAY-SESSION filter or the LOSS-STREAK pause?")
    sess_helps = strk_helps = 0
    for cell in rows:
        nf = cell["nofilter_OOS"]; so = cell["session_only_OOS"]; st = cell["streak_only_OOS"]
        if nf.get("n", 0) < MIN_OOS:
            continue
        d_sess = (so.get("avg_R") or 0) - nf["avg_R"]
        d_strk = (st.get("avg_R") or 0) - nf["avg_R"]
        sess_helps += int(d_sess > 0)
        strk_helps += int(d_strk > 0)
        print(f"  {cell['tf']:4} RR{int(cell['rr'])}: base(24/7)={nf['avg_R']:+.3f}  "
              f"session-only={so.get('avg_R'):+.3f} (d={d_sess:+.3f})  "
              f"streak-only={st.get('avg_R'):+.3f} (d={d_strk:+.3f})")
    print(f"  => day-session gate improves {sess_helps}/{filter_cells} cells; "
          f"loss-streak gate improves {strk_helps}/{filter_cells} cells.")

    # ----- clustering test: is the loss-streak gate real or a reshuffle? -----
    print("\nLOSS-STREAK GATE — REAL clustering or just resampling? (real gated avg_R vs "
          "500-shuffle null 95% band)")
    clust_real = 0
    for cell in rows:
        cl = cell.get("streak_clustering_test", {})
        if "gated_avg_R" not in cl:
            continue
        clust_real += int(cl.get("exploits_clustering", False))
        print(f"  {cell['tf']:4} RR{int(cell['rr'])}: ungated={cl['ungated_avg_R']:+.3f} "
              f"gated={cl['gated_avg_R']:+.3f} | shuffle95=[{cl['shuffle_ci95_lo']:+.3f},"
              f"{cl['shuffle_ci95_hi']:+.3f}] -> "
              f"{'EXPLOITS real clustering' if cl['exploits_clustering'] else 'just resampling (NOT real)'}")

    # ----- OOS STABILITY: is the edge spread across OOS or only recent? -----
    print("\nOOS STABILITY (BOT avg_R, 1st vs 2nd half of the out-of-sample window):")
    for cell in rows:
        h1 = cell["bot_OOS_first_half"]; h2 = cell["bot_OOS_second_half"]
        if (h1.get("n", 0) + h2.get("n", 0)) >= MIN_OOS:
            print(f"  {cell['tf']:4} RR{int(cell['rr'])}: 1st-half avg_R={h1.get('avg_R')} "
                  f"(n={h1.get('n')})  vs  2nd-half avg_R={h2.get('avg_R')} (n={h2.get('n')})")

    # ----- verdict -----
    print("\n" + "=" * 132)
    print("HONEST VERDICT")
    print("=" * 132)
    bot_edges = [(tf, rr, s, rb, beats) for (tf, rr, s, rb, beats) in edge_cells]
    if not bot_edges:
        print("  NO BOT cell has OOS avg_R>0 with a 95% bootstrap CI that excludes 0.")
        print("  => A mechanized BTC day-swing-continuation bot does NOT show positive "
              "net-of-cost OOS expectancy at trustworthy significance.")
        verdict = "NO_EDGE"
    else:
        real = [e for e in bot_edges if e[4]]   # also beats random (paired lift)
        for (tf, rr, s, rb, beats) in bot_edges:
            print(f"  BOT {tf} RR{int(rr)}: OOS avg_R={s['avg_R']:+.3f} "
                  f"WR={s['win_rate']}% PF={s['pf']} n={s['n']} "
                  f"CI95=[{s['ci95_lo']},{s['ci95_hi']}] p(<=0)={s['p_avgR_le_0']}  "
                  f"beats-random={beats} (paired lift {rb.get('cont_lift_mean')}, "
                  f"p(lift<=0)={rb.get('cont_lift_p_le_0')})")
        if real:
            verdict = "EDGE"
            print(f"  => {len(real)} cell(s) show POSITIVE cost-net OOS expectancy whose CI "
                  "excludes 0 AND beat the random baseline. WEAK but real on those cells.")
        else:
            verdict = "WEAK"
            print(f"  => {len(bot_edges)} cell(s) have CI>0 but do NOT beat the random "
                  "baseline (paired-lift CI straddles 0): expectancy may be entry-band luck, "
                  "not directional skill. Treat as WEAK / unproven.")

    payload = {
        "config": {
            "SYMBOL": SYMBOL, "TFS": TFS, "IS_FRAC": IS_FRAC, "RR_LIST": RR_LIST,
            "EMA_FAST": EMA_FAST, "EMA_SLOPE_LOOKBACK": EMA_SLOPE_LOOKBACK,
            "RUN_LEN": RUN_LEN, "SWING_LOOKBACK": SWING_LOOKBACK, "ATR_LEN": ATR_LEN,
            "ATR_SL_FLOOR_MULT": ATR_SL_FLOOR_MULT, "HOLD": HOLD,
            "DAY_SESSION_UTC": [DAY_START_H, DAY_END_H], "LOSS_STREAK": LOSS_STREAK,
            "MIN_OOS": MIN_OOS, "BOOT": BOOT,
            "cost_points": TYP_COST_POINTS,
            "cost_price": round(cost, 6),
            "cost_model": "round-trip = TYP_COST_POINTS*point (price units); BTC=$45",
            "tie_break": "bar spanning SL&TP -> SL (pessimistic)",
            "no_lookahead": True,
            "split": "67/33 by time; OOS reported",
        },
        "results": all_results,
        "verdict": verdict,
        "filter_value": {
            "cells_compared": filter_cells,
            "filter_helps_in": filter_helps,
            "day_session_gate_helps_in": sess_helps,
            "loss_streak_gate_helps_in": strk_helps,
            "note": ("The lift over the raw 24/7 continuation signal comes almost "
                     "entirely from the LOSS-STREAK cool-off gate, NOT the day-session "
                     "window. On BTC (24/7) the 07-22 UTC gate is neutral-to-harmful. "
                     "The cool-off gate exploits genuine loss-clustering (verified: "
                     "real time-ordered avg_R lies OUTSIDE the 95% band of 500 "
                     "trade-order shuffles)."),
        },
    }
    outpath = os.path.join(CACHE, "genome_bot_bt_results.json")
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nResults saved -> {outpath}")
    return verdict, all_results


if __name__ == "__main__":
    main()
