"""
scaling_risk_lab.py
===================
Quantifies — HONESTLY, with numbers — why the user's riskiest habit is dangerous:

    "as long as it's falling I keep buying"  (averaging down / martingale,
     scaling into a losing position with NO stop).

This nearly cost -$722 on a single gold float. The point of this lab is NOT to
endorse the habit. It "usually wins" (mean-reverting drift back to the first
entry), but the rare run that never reverts wipes the account. We show that with
two methods and then show what a SAFE version (capped adds + hard portfolio stop)
looks like.

METHOD 1 (Historical, no-lookahead):
  Walk real bars. At each candidate start bar i (only using data <= i), open a
  long. While price falls a further -X*ATR from the last add, add another unit
  (martingale: each add can be equal or geometrically larger). Exit when price
  returns to the *volume-weighted average entry* (the "I got out flat/green"
  fantasy) OR after M bars (time stop) OR — for the safe variant — when a hard
  portfolio loss / max-adds cap is hit. Compare three strategies on identical
  start bars:
     A) UNBOUNDED martingale add-on-loss, no stop  (the dangerous habit)
     B) SINGLE entry with a fixed hard stop (-X*ATR) and TP (+R*X*ATR)
     C) SAFE scaling: capped #adds + hard portfolio $ stop
  Report OOS (33% held-out by time) expectancy, worst drawdown per sequence,
  and the fraction of sequences that breach a -50% / -80% account-equivalent
  floating loss before they recover.

METHOD 2 (Monte-Carlo risk-of-ruin):
  Model the martingale add-on-loss sizing on a $1900 account at the user's
  observed sizing. Bootstrap real bar returns (block bootstrap to keep
  autocorrelation/fat tails) and run many account paths of repeated martingale
  sequences. Compute risk-of-ruin (P(equity <= ruin floor) over the horizon),
  median terminal equity, and the win-rate-vs-blowup tradeoff. Compare unbounded
  vs capped/hard-stop.

RIGOR
  * NO lookahead: a sequence opened at bar i sees only bars > i as they arrive,
    one at a time; ATR at i uses bars <= i. Pivots/structure not needed here.
  * 67/33 IS/OOS split by time; we report OOS.
  * >=30 OOS sequences required or labelled small-sample.
  * Realistic per-trade cost: spread+commission proxy subtracted per add and per
    exit (round-trip ~2x typical spread in points * point_value).

Data: data/lab_cache/<SYM>_<TF>.npz (t,o,h,l,c,v) + <SYM>_meta.json.
Run:  ./.venv/Scripts/python.exe scaling_risk_lab.py
Out:  data/lab_cache/scaling_risk_lab_results.json
"""

from __future__ import annotations
import json
import math
import os
import sys
import functools
from dataclasses import dataclass, field, asdict

import numpy as np

print = functools.partial(print, flush=True)  # unbuffered for live progress

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

# ----- user-observed reality (from MEMORY: $1900 acct, gold floats ~-$722) -----
ACCOUNT = 1900.0
# Typical spread in *points* per symbol (round-trip cost proxy = 2x this * point_value).
TYPICAL_SPREAD_PTS = {"XAUUSDm": 25.0, "BTCUSDm": 45.0}
# Base lot the user trades (min lot scalper sizing observed in the stack).
BASE_LOT = 0.01

# ----- experiment knobs -----
TFS = ["M5", "M15"]            # intraday TFs where "keep buying the dip" happens
SYMBOLS = ["XAUUSDm", "BTCUSDm"]
ATR_PERIOD = 14
ADD_STEP_ATR = 1.0             # add another unit every -1 ATR further down
MAX_BARS_HOLD = 240            # time stop (e.g. 240*M5 = 20h ; 240*M15 = 60h)
SINGLE_STOP_ATR = 2.0          # fixed hard stop for the disciplined single-entry
SINGLE_TP_R = 1.5              # TP = 1.5 * stop distance
SAFE_MAX_ADDS = 3              # capped scaling: at most 3 adds (4 units total)
SAFE_PORT_STOP_FRAC = 0.06     # hard portfolio stop = 6% of account floating loss
MARTINGALE_MULT = 1.0          # 1.0 = equal adds ; >1 = geometric (true martingale)
START_STRIDE = 20              # sample candidate starts every N bars (independence)
RNG_SEED = 7

rng = np.random.default_rng(RNG_SEED)


def point_value_per_lot(meta: dict) -> float:
    """$ per 1 point of price move, per 1.00 lot."""
    return meta["trade_tick_value"] * (meta["point"] / meta["trade_tick_size"])


def dollars_per_price_unit(meta: dict) -> float:
    """$ PnL per 1.0 of price (e.g. $1 of gold) per 1.00 lot."""
    return point_value_per_lot(meta) / meta["point"]


def roundtrip_cost(meta: dict, sym: str, lots: float) -> float:
    """$ cost per round trip for `lots`: 2x typical spread (pts) * pt_value * lots."""
    pv = point_value_per_lot(meta)
    return 2.0 * TYPICAL_SPREAD_PTS[sym] * pv * lots


def load(sym: str, tf: str):
    d = np.load(os.path.join(CACHE, f"{sym}_{tf}.npz"))
    return d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]


def atr_series(h, l, c, period=ATR_PERIOD):
    """Wilder-ish ATR; atr[i] uses bars <= i only (no lookahead)."""
    n = len(c)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.full(n, np.nan)
    if n > period:
        atr[period] = tr[1 : period + 1].mean()
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ============================================================================
# METHOD 1 — historical simulation (no lookahead, OOS only reported)
# ============================================================================

@dataclass
class SeqResult:
    pnl: float                 # net $ at close (incl. costs)
    worst_float: float         # worst floating $ loss reached during the life
    units: int                 # how many units ended up open
    bars: int                  # how long it ran
    outcome: str               # 'reverted' | 'timeout' | 'port_stop' | 'hard_stop' | 'tp'


def sim_unbounded(o, h, l, c, atr, sym, meta, i):
    """A) The dangerous habit: long, add every -ADD_STEP_ATR, NO stop.
       Exit only when price >= volume-weighted avg entry, or time stop."""
    dpu = dollars_per_price_unit(meta)
    a = atr[i]
    if not np.isfinite(a) or a <= 0:
        return None
    lot = BASE_LOT
    entries = [c[i]]            # entry prices
    lots = [lot]
    next_add_below = c[i] - ADD_STEP_ATR * a
    cost = roundtrip_cost(meta, sym, lot)  # cost of first unit's round trip share
    worst = 0.0
    end = min(i + MAX_BARS_HOLD, len(c) - 1)
    for j in range(i + 1, end + 1):
        px = c[j]
        # add on further drop (martingale). Use intrabar low for trigger realism.
        while l[j] <= next_add_below:
            lot_j = lots[-1] * MARTINGALE_MULT if MARTINGALE_MULT != 1.0 else BASE_LOT
            lot_j = round(lot_j, 2)
            if lot_j < meta["volume_min"]:
                lot_j = meta["volume_min"]
            entries.append(next_add_below)
            lots.append(lot_j)
            cost += roundtrip_cost(meta, sym, lot_j)
            next_add_below = next_add_below - ADD_STEP_ATR * a
        tot_lots = sum(lots)
        avg = sum(e * lo for e, lo in zip(entries, lots)) / tot_lots
        # floating PnL (long): (px - avg) * dpu * tot_lots
        flt = (px - avg) * dpu * tot_lots
        worst = min(worst, flt - cost)
        # exit: price recovers to avg entry (the "got out flat" fantasy)
        if h[j] >= avg:
            pnl = (avg - avg) * 0.0  # exits at avg -> gross ~0, pay costs
            return SeqResult(pnl - cost, worst, len(lots), j - i, "reverted")
    # time stop: close at last close
    px = c[end]
    tot_lots = sum(lots)
    avg = sum(e * lo for e, lo in zip(entries, lots)) / tot_lots
    pnl = (px - avg) * dpu * tot_lots - cost
    worst = min(worst, pnl)
    return SeqResult(pnl, worst, len(lots), end - i, "timeout")


def sim_single(o, h, l, c, atr, sym, meta, i):
    """B) Disciplined single entry: hard stop -SINGLE_STOP_ATR, TP +R."""
    dpu = dollars_per_price_unit(meta)
    a = atr[i]
    if not np.isfinite(a) or a <= 0:
        return None
    lot = BASE_LOT
    entry = c[i]
    stop = entry - SINGLE_STOP_ATR * a
    tp = entry + SINGLE_TP_R * SINGLE_STOP_ATR * a
    cost = roundtrip_cost(meta, sym, lot)
    worst = 0.0
    end = min(i + MAX_BARS_HOLD, len(c) - 1)
    for j in range(i + 1, end + 1):
        flt = (c[j] - entry) * dpu * lot
        worst = min(worst, flt - cost)
        # stop first (conservative: if both touched in same bar, assume stop)
        if l[j] <= stop:
            pnl = (stop - entry) * dpu * lot - cost
            return SeqResult(pnl, min(worst, pnl), 1, j - i, "hard_stop")
        if h[j] >= tp:
            pnl = (tp - entry) * dpu * lot - cost
            return SeqResult(pnl, worst, 1, j - i, "tp")
    px = c[end]
    pnl = (px - entry) * dpu * lot - cost
    return SeqResult(pnl, min(worst, pnl), 1, end - i, "timeout")


def sim_safe(o, h, l, c, atr, sym, meta, i):
    """C) Safe scaling: capped #adds AND hard portfolio $ stop. Exit at avg or stop."""
    dpu = dollars_per_price_unit(meta)
    a = atr[i]
    if not np.isfinite(a) or a <= 0:
        return None
    port_stop = SAFE_PORT_STOP_FRAC * ACCOUNT  # $ floating loss limit
    entries = [c[i]]
    lots = [BASE_LOT]
    next_add_below = c[i] - ADD_STEP_ATR * a
    cost = roundtrip_cost(meta, sym, BASE_LOT)
    worst = 0.0
    end = min(i + MAX_BARS_HOLD, len(c) - 1)
    for j in range(i + 1, end + 1):
        while l[j] <= next_add_below and (len(lots) - 1) < SAFE_MAX_ADDS:
            lot_j = lots[-1] * MARTINGALE_MULT if MARTINGALE_MULT != 1.0 else BASE_LOT
            lot_j = max(round(lot_j, 2), meta["volume_min"])
            entries.append(next_add_below)
            lots.append(lot_j)
            cost += roundtrip_cost(meta, sym, lot_j)
            next_add_below = next_add_below - ADD_STEP_ATR * a
        tot_lots = sum(lots)
        avg = sum(e * lo for e, lo in zip(entries, lots)) / tot_lots
        flt = (c[j] - avg) * dpu * tot_lots
        worst = min(worst, flt - cost)
        # hard portfolio stop (intrabar low)
        flt_low = (l[j] - avg) * dpu * tot_lots
        if flt_low - cost <= -port_stop:
            pnl = -port_stop
            return SeqResult(pnl, min(worst, pnl), len(lots), j - i, "port_stop")
        if h[j] >= avg:
            return SeqResult(0.0 - cost, worst, len(lots), j - i, "reverted")
    px = c[end]
    tot_lots = sum(lots)
    avg = sum(e * lo for e, lo in zip(entries, lots)) / tot_lots
    pnl = (px - avg) * dpu * tot_lots - cost
    return SeqResult(pnl, min(worst, pnl), len(lots), end - i, "timeout")


def summarize(results: list[SeqResult], label: str):
    if not results:
        return {"label": label, "n": 0}
    pnl = np.array([r.pnl for r in results])
    worst = np.array([r.worst_float for r in results])
    wins = (pnl > 0).sum()
    # account-equivalent floating loss breaches
    breach_50 = (worst <= -0.50 * ACCOUNT).sum()
    breach_80 = (worst <= -0.80 * ACCOUNT).sum()
    outcomes = {}
    for r in results:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    return {
        "label": label,
        "n": int(len(results)),
        "win_rate": round(float(wins) / len(results), 4),
        "expectancy_$": round(float(pnl.mean()), 3),
        "median_pnl_$": round(float(np.median(pnl)), 3),
        "total_pnl_$": round(float(pnl.sum()), 2),
        "best_$": round(float(pnl.max()), 2),
        "worst_close_$": round(float(pnl.min()), 2),
        "mean_worst_float_$": round(float(worst.mean()), 2),
        "p95_worst_float_$": round(float(np.percentile(worst, 5)), 2),  # 5th pct = deep loss
        "max_worst_float_$": round(float(worst.min()), 2),
        "pct_breach_50pct_acct": round(float(breach_50) / len(results), 4),
        "pct_breach_80pct_acct": round(float(breach_80) / len(results), 4),
        "mean_units": round(float(np.mean([r.units for r in results])), 2),
        "max_units": int(max(r.units for r in results)),
        "outcomes": outcomes,
    }


def run_historical(sym, tf):
    t, o, h, l, c, v = load(sym, tf)
    meta = json.load(open(os.path.join(CACHE, f"{sym}_meta.json")))
    atr = atr_series(h, l, c)
    n = len(c)
    split = int(n * 0.67)  # time split; report OOS = bars >= split
    starts = list(range(max(split, ATR_PERIOD + 2), n - MAX_BARS_HOLD - 1, START_STRIDE))
    res_unb, res_sgl, res_safe = [], [], []
    for i in starts:
        ru = sim_unbounded(o, h, l, c, atr, sym, meta, i)
        rs = sim_single(o, h, l, c, atr, sym, meta, i)
        rf = sim_safe(o, h, l, c, atr, sym, meta, i)
        if ru:
            res_unb.append(ru)
        if rs:
            res_sgl.append(rs)
        if rf:
            res_safe.append(rf)
    return {
        "symbol": sym, "tf": tf,
        "oos_start_bar": split, "n_bars": n,
        "n_oos_sequences": len(res_unb),
        "small_sample": len(res_unb) < 30,
        "unbounded_martingale_noStop": summarize(res_unb, "A_unbounded_noStop"),
        "single_entry_hardStop": summarize(res_sgl, "B_single_hardStop"),
        "safe_capped_portStop": summarize(res_safe, "C_safe_capped_portStop"),
    }


# ============================================================================
# METHOD 2 — Monte-Carlo risk-of-ruin on a $1900 account
# ============================================================================

def block_bootstrap_returns(c, block=12, n_draw=None, rstate=None):
    """Sample log-returns in blocks to preserve autocorrelation & fat tails."""
    r = np.diff(np.log(c))
    r = r[np.isfinite(r)]
    if rstate is None:
        rstate = rng
    if n_draw is None:
        n_draw = len(r)
    out = np.empty(n_draw)
    pos = 0
    while pos < n_draw:
        s = rstate.integers(0, len(r) - block)
        take = min(block, n_draw - pos)
        out[pos : pos + take] = r[s : s + take]
        pos += take
    return out


def _episode_pnl_vectorized(px0, paths, a, dpu, cost_unit, max_units, port_stop_frac):
    """
    Realized-$ for ONE martingale long-from-dip episode, stepped bar-by-bar but
    VECTORIZED across all paths.  `paths` shape = (P, EP_LEN).  Equal-add
    martingale on a fixed ATR grid (level j at entry0 - j*step).  Time-ordered,
    NO lookahead: each bar (a) fires any pending adds the current price reaches,
    (b) checks the SAFE hard portfolio stop, (c) checks revert-to-avg exit. The
    FIRST of stop/revert to occur ends the episode for that path; otherwise the
    episode times out at the final close.
    Returns realized $ per path (shape P,).
    """
    P = paths.shape[0]
    step = ADD_STEP_ATR * a
    entry0 = px0
    cap_adds = (max_units - 1) if max_units is not None else 10_000_000
    port_stop = (port_stop_frac * ACCOUNT) if port_stop_frac is not None else None

    units = np.ones(P, dtype=np.int64)              # 1 unit open at entry0
    sum_entry = np.full(P, entry0, dtype=float)     # sum of entry prices (equal lots)
    next_below = np.full(P, entry0 - step)          # next add trigger price
    done = np.zeros(P, dtype=bool)
    realized = np.zeros(P, dtype=float)

    for j in range(paths.shape[1]):
        px = paths[:, j]
        live = ~done
        # (a) fire adds while price has fallen to/below the next trigger (capped)
        # may fire multiple levels in one bar -> loop until no path triggers
        for _ in range(64):
            can_add = live & (px <= next_below) & (units <= cap_adds)
            if not can_add.any():
                break
            units = np.where(can_add, units + 1, units)
            sum_entry = np.where(can_add, sum_entry + next_below, sum_entry)
            next_below = np.where(can_add, next_below - step, next_below)
        avg = sum_entry / units
        tot_lots = units * BASE_LOT
        cost = units * cost_unit
        flt = (px - avg) * dpu * tot_lots - cost
        # (b) SAFE hard portfolio stop (intrabar; use current px as proxy floor)
        if port_stop is not None:
            stop_hit = live & (flt <= -port_stop)
            realized = np.where(stop_hit, -port_stop, realized)
            done = done | stop_hit
            live = ~done
        # (c) revert-to-avg exit -> close flat, pay costs only
        rev = live & (px >= avg)
        realized = np.where(rev, -cost, realized)
        done = done | rev
        if done.all():
            break

    # timeout: any path still live closes at final price
    live = ~done
    if live.any():
        px = paths[:, -1]
        avg = sum_entry / units
        tot_lots = units * BASE_LOT
        cost = units * cost_unit
        to_pnl = (px - avg) * dpu * tot_lots - cost
        realized = np.where(live, to_pnl, realized)
    return realized


def mc_account_paths(sym, tf, mode, n_paths=4000, n_sequences=300, max_units=None,
                     port_stop_frac=None):
    """
    Simulate `n_sequences` martingale long-from-dip episodes per account path,
    VECTORIZED across all paths.  mode: 'unbounded' | 'safe...'.
    Account starts at $1900; ruin = equity <= 20% of start (=$380, margin-call-ish).
    Returns risk-of-ruin and terminal equity distribution (OOS-honest: any revert
    bias makes the habit look safer, so reported ruin is a conservative floor).
    """
    t, o, h, l, c, v = load(sym, tf)
    meta = json.load(open(os.path.join(CACHE, f"{sym}_meta.json")))
    dpu = dollars_per_price_unit(meta)
    px0 = float(c[-1])
    lr = np.diff(np.log(c[c > 0]))
    lr = lr[np.isfinite(lr)]
    sigma_lr = float(np.std(lr))
    a = sigma_lr * px0 * math.sqrt(ATR_PERIOD)  # ATR-equivalent in price units
    ruin_floor = 0.20 * ACCOUNT
    cost_unit = roundtrip_cost(meta, sym, BASE_LOT)
    EP_LEN = MAX_BARS_HOLD
    BLOCK = 12

    rs = np.random.default_rng(RNG_SEED + abs(hash((sym, tf, mode))) % 100000)
    equity = np.full(n_paths, ACCOUNT, dtype=float)
    alive = np.ones(n_paths, dtype=bool)
    nblocks = int(np.ceil(EP_LEN / BLOCK))

    for _seq in range(n_sequences):
        alive = equity > ruin_floor
        if not alive.any():
            break
        # block-bootstrap one EP_LEN path per account-path, vectorized
        starts = rs.integers(0, len(lr) - BLOCK, size=(n_paths, nblocks))
        offs = np.arange(BLOCK)
        idx = (starts[:, :, None] + offs[None, None, :]).reshape(n_paths, -1)[:, :EP_LEN]
        rets = lr[idx]                                  # (P, EP_LEN)
        paths = px0 * np.exp(np.cumsum(rets, axis=1))   # (P, EP_LEN)
        realized = _episode_pnl_vectorized(px0, paths, a, dpu, cost_unit,
                                           max_units, port_stop_frac)
        equity = np.where(alive, equity + realized, equity)

    terminals = equity
    ruined = int((terminals <= ruin_floor).sum())

    return {
        "mode": mode, "symbol": sym, "tf": tf,
        "n_paths": n_paths, "n_sequences_per_path": n_sequences,
        "max_units": max_units, "port_stop_frac": port_stop_frac,
        "risk_of_ruin": round(ruined / n_paths, 4),
        "median_terminal_$": round(float(np.median(terminals)), 2),
        "mean_terminal_$": round(float(terminals.mean()), 2),
        "p05_terminal_$": round(float(np.percentile(terminals, 5)), 2),
        "p95_terminal_$": round(float(np.percentile(terminals, 95)), 2),
        "pct_paths_grew": round(float((terminals > ACCOUNT).mean()), 4),
        "atr_equiv_price": round(a, 4),
    }


def main():
    out = {
        "account": ACCOUNT, "base_lot": BASE_LOT,
        "config": {
            "add_step_atr": ADD_STEP_ATR, "max_bars_hold": MAX_BARS_HOLD,
            "single_stop_atr": SINGLE_STOP_ATR, "single_tp_r": SINGLE_TP_R,
            "safe_max_adds": SAFE_MAX_ADDS, "safe_port_stop_frac": SAFE_PORT_STOP_FRAC,
            "martingale_mult": MARTINGALE_MULT, "start_stride": START_STRIDE,
            "typical_spread_pts": TYPICAL_SPREAD_PTS,
        },
        "method1_historical_oos": [],
        "method2_monte_carlo": [],
    }

    print("=" * 78)
    print("METHOD 1 — HISTORICAL (OOS only, no-lookahead): scaling-into-loss vs discipline")
    print("=" * 78)
    for sym in SYMBOLS:
        for tf in TFS:
            r = run_historical(sym, tf)
            out["method1_historical_oos"].append(r)
            a = r["unbounded_martingale_noStop"]
            b = r["single_entry_hardStop"]
            cc = r["safe_capped_portStop"]
            ss = " [SMALL SAMPLE]" if r["small_sample"] else ""
            print(f"\n--- {sym} {tf}  (OOS n={r['n_oos_sequences']} sequences){ss} ---")
            for tag, s in [("A UNBOUNDED no-stop", a), ("B SINGLE +stop", b), ("C SAFE capped+portStop", cc)]:
                print(f"  {tag:24s} WR={s['win_rate']*100:5.1f}%  E=${s['expectancy_$']:+8.2f}  "
                      f"total=${s['total_pnl_$']:+9.1f}  worstFloat=${s['max_worst_float_$']:+9.1f}  "
                      f"breach50={s['pct_breach_50pct_acct']*100:4.1f}%  breach80={s['pct_breach_80pct_acct']*100:4.1f}%  "
                      f"maxUnits={s['max_units']}")

    print("\n" + "=" * 78)
    print("METHOD 2 — MONTE-CARLO RISK-OF-RUIN ($1900 acct, block-bootstrap real returns)")
    print("=" * 78)
    for sym in SYMBOLS:
        tf = "M15"
        for mode, kw in [
            ("unbounded", dict(max_units=None, port_stop_frac=None)),
            ("safe_capped3_stop6", dict(max_units=4, port_stop_frac=SAFE_PORT_STOP_FRAC)),
        ]:
            r = mc_account_paths(sym, tf, mode, n_paths=5000, n_sequences=200, **kw)
            out["method2_monte_carlo"].append(r)
            print(f"\n--- {sym} {tf}  mode={mode} ---")
            print(f"  risk_of_ruin = {r['risk_of_ruin']*100:5.2f}%   "
                  f"median_terminal=${r['median_terminal_$']:.0f}  "
                  f"p05=${r['p05_terminal_$']:.0f}  p95=${r['p95_terminal_$']:.0f}  "
                  f"pct_grew={r['pct_paths_grew']*100:.1f}%")

    outpath = os.path.join(CACHE, "scaling_risk_lab_results.json")
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved -> {outpath}")
    return out


if __name__ == "__main__":
    main()
