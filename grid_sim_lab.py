"""grid_sim_lab.py — honest, causal, walk-forward OOS test of the
EA_Hedging_Grid_Dynamic_V7 gold grid logic.

Replicates the EA faithfully (no SL per trade, dynamic grid distance, daily
+$10 target / -$50 stop, limited martingale-recovery on the losing side, daily
reset) and runs it bar-by-bar on real XAUUSDm M5 history with a REALISTIC gold
spread charged on every entry AND every exit fill.

Two configs on the SAME data:
  (A) PLAIN  — exactly the EA logic.
  (B) RANGE-GATED — same logic, but a NEW grid is only armed when the market is
      NOT strongly trending (ADX(14) below a threshold AND |EMA50 slope| small
      on a higher timeframe). A few thresholds are swept.

Scientific rigor:
  * Causal: every decision at bar i uses only data up to and including bar i
    (indicators are computed on full series but only read at/<= i; fills use the
    bar's H/L which is information available once the bar closes — standard
    bar-replay; pending stops are armed on a PRIOR bar's close).
  * No look-ahead: grids are armed on bar i's close and can only fill on bar
    i+1.. ; we never peek at future bars to decide anything.
  * Net of REAL spread: spread is subtracted at fill of entry and fill of exit.
  * Walk-forward: results reported per time block (5 contiguous blocks) so a
    single lucky split cannot masquerade as an edge.
  * "NO EDGE" is an expected, respectable result for a grid on a trending asset.

NO order_send. Read-only. Writes only this file's results to stdout + a json.

EA reference (EA_Hedging_Grid_Dynamic_V7.mq5, gold):
  - buy-stop above + sell-stop below at +/- grid_dist
  - grid_dist for gold ~= 300 'points' * (price/2000); TP per leg ~= same dist
  - up to 5 orders per side
  - grid lot ~= minimum (the 0.05 multiplier < 1 clips to the floor)
  - daily target +$10 -> close all, stop for the day
  - daily loss cap -$50 -> close all
  - NO per-trade SL (InpSLPoints = 0)
  - limited martingale-recovery: when a leg loses <= -$2, add orders at lot x2
    (3 levels up to 0.08) on the LOSING side
  - daily reset
"""
from __future__ import annotations
import json
import os
import datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
SYMBOL = "XAUUSDm"
TF = "M5"

# ----- contract economics (from data/lab_cache/XAUUSDm_meta.json) -----
# point=0.001 (3-decimal quotes), tick_size=0.001, tick_value=0.1
#   => 1.0 lot earns $100 per $1.00 price move (100oz contract)
#   => 0.01 lot earns $1.00 per $1.00 price move
USD_PER_PRICE_PER_LOT = 100.0          # $ per 1.0 USD move, per 1.0 lot
MIN_LOT = 0.01
LOT_STEP = 0.01

# The EA was written with the *conventional* gold point (0.01, 2 decimals): its
# "300 points" => $3.00 base, scaled by price/2000. On this 3-decimal broker the
# literal broker-point (0.001) would make the grid ~$0.69 (0.14x a single M5 bar)
# which is pathological spread-death and not what the author meant. We use the
# conventional gold point so the grid is a sane ~$6.9 at price 4600. This is the
# faithful interpretation of the EA's design intent.
GOLD_POINT = 0.01
GRID_BASE_POINTS = 300.0               # InpGridPoints-equivalent for gold
GRID_REF_PRICE = 2000.0

# Realistic gold spread. Task says ~20-40 'points'; in conventional gold points
# that is $0.20-$0.40. We charge HALF the round-trip spread at each fill (entry
# and exit) so a full open+close pays the full spread. Use $0.30 round-trip.
SPREAD_USD_ROUNDTRIP = 0.30
SPREAD_HALF = SPREAD_USD_ROUNDTRIP / 2.0   # charged per fill

# EA money rules
DAILY_TARGET = 10.0
DAILY_STOP = -50.0
MAX_PER_SIDE = 5                       # max grid orders per side
# limited martingale-recovery
MART_TRIGGER = -2.0                    # add recovery when a leg loses <= -$2
MART_LOT_MULT = 2.0
MART_MAX_LEVELS = 3                    # up to 0.08 from 0.01 base
MART_LOT_CAP = 0.08

START_EQUITY = 10000.0
N_BLOCKS = 5


def load_bars(symbol=SYMBOL, tf=TF):
    """Load from npz cache; fall back to live MT5 copy_rates_from_pos."""
    p = os.path.join(CACHE, f"{symbol}_{tf}.npz")
    if os.path.exists(p):
        d = np.load(p, allow_pickle=True)
        return (d["t"].astype("int64"), d["o"].astype(float), d["h"].astype(float),
                d["l"].astype(float), d["c"].astype(float))
    # fallback
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    r = mt5.copy_rates_from_pos(symbol, tf_map[tf], 0, 40000)
    mt5.shutdown()
    if r is None or len(r) == 0:
        raise RuntimeError("no rates")
    return (r["time"].astype("int64"), r["open"].astype(float), r["high"].astype(float),
            r["low"].astype(float), r["close"].astype(float))


# ---------- indicators (computed once, read causally) ----------
def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def adx(h, l, c, n=14):
    """Wilder ADX. Returns array aligned to bars (first ~2n are warmup ~0)."""
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])

    def wilder(arr, n):
        out = np.zeros(len(arr))
        if len(arr) < n:
            return out
        out[n - 1] = arr[:n].sum()
        for i in range(n, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / n + arr[i]
        return out

    atr = wilder(tr, n)
    pdm = wilder(plus_dm, n)
    mdm = wilder(minus_dm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * np.where(atr > 0, pdm / atr, 0.0)
        mdi = 100.0 * np.where(atr > 0, mdm / atr, 0.0)
        dx = 100.0 * np.where((pdi + mdi) > 0, np.abs(pdi - mdi) / (pdi + mdi), 0.0)
    adx_v = np.zeros(len(dx))
    if len(dx) > 2 * n:
        adx_v[2 * n - 1] = dx[n - 1:2 * n - 1].mean() if (2 * n - 1) <= len(dx) else 0.0
        for i in range(2 * n, len(dx)):
            adx_v[i] = (adx_v[i - 1] * (n - 1) + dx[i]) / n
    out = np.zeros(len(h))
    out[1:] = adx_v          # shift back to bar alignment (dx indexed from 1)
    return out


def grid_dist(price):
    """EA dynamic grid distance in USD: 300pts * (price/2000), conventional pt."""
    return GRID_BASE_POINTS * GOLD_POINT * (price / GRID_REF_PRICE)


def round_lot(x):
    return max(MIN_LOT, round(x / LOT_STEP) * LOT_STEP)


# ---------- the core causal simulation ----------
def simulate(t, o, h, l, c, range_gate=False, adx_thr=25.0, ema_slope_thr=None,
             ema_arr=None, adx_arr=None):
    """Bar-by-bar replay of the EA grid logic.

    Positions: a list of open legs. Each leg = dict(side, entry, lot, tp).
    Pending stops: buy-stop / sell-stop arrays of armed prices (price, lot).
    No per-trade SL. Per-leg TP = grid_dist from entry (EA: TP ~= grid dist).
    Daily target/stop close ALL and (target) halt for the rest of the day.
    Limited martingale: when a closed leg realizes <= MART_TRIGGER, add up to
    MART_MAX_LEVELS recovery stop-orders on the LOSING side at lot x2 (capped).
    """
    n = len(c)
    # day index per bar (UTC date)
    days = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).toordinal() for x in t])

    bal = START_EQUITY
    equity = np.empty(n)
    daily_pnl = 0.0
    cur_day = days[0]
    halted_today = False

    legs = []                 # open legs: dict(side, entry, lot, tp)
    # straddle = the always-on OCO breakout pair (the grid's "armed" state)
    strad_buy = None          # (price, lot)  buy-stop above
    strad_sell = None         # (price, lot)  sell-stop below
    mart_pending = []         # recovery stop orders: (side, price, lot, tp)

    trades = []               # realized pnl per leg (incl spread)
    daily_returns = {}        # day -> realized pnl that day (0 counts as a day)

    def n_open_side(side):
        return sum(1 for L in legs if L["side"] == side) + \
               sum(1 for mp in mart_pending if mp[0] == side)

    def close_leg(L, exit_price):
        d = (exit_price - L["entry"]) if L["side"] > 0 else (L["entry"] - exit_price)
        pnl = d * USD_PER_PRICE_PER_LOT * L["lot"]
        pnl -= SPREAD_HALF * (L["lot"] / MIN_LOT)   # exit spread scales w/ size
        return pnl

    def open_cost(lot):
        return SPREAD_HALF * (lot / MIN_LOT)        # entry spread

    def gate_ok(i):
        if not range_gate or adx_arr is None:
            return True
        if adx_arr[i] > adx_thr:
            return False
        if ema_slope_thr is not None and ema_arr is not None and i >= 5:
            slope = abs(ema_arr[i] - ema_arr[i - 5]) / max(c[i], 1e-9)
            if slope > ema_slope_thr:
                return False
        return True

    for i in range(n):
        # --- daily reset ---
        if days[i] != cur_day:
            cur_day = days[i]
            daily_pnl = 0.0
            halted_today = False
        daily_returns.setdefault(cur_day, 0.0)   # honest: count every trading day

        price_c = c[i]
        hi, lo = h[i], l[i]

        # --- 1. exits of open legs on this bar (TP only; NO per-trade SL) ---
        still = []
        for L in legs:
            hit = None
            if L["side"] > 0 and hi >= L["tp"]:
                hit = L["tp"]
            elif L["side"] < 0 and lo <= L["tp"]:
                hit = L["tp"]
            if hit is not None:
                pnl = close_leg(L, hit)
                bal += pnl
                daily_pnl += pnl
                trades.append(pnl)
                daily_returns[cur_day] += pnl
                # limited martingale-recovery when a leg realizes <= -$2
                if pnl <= MART_TRIGGER and n_open_side(L["side"]) < MAX_PER_SIDE:
                    gd = grid_dist(price_c)
                    lot = L["lot"]
                    for lvl in range(MART_MAX_LEVELS):
                        if n_open_side(L["side"]) + (lvl + 1) > MAX_PER_SIDE:
                            break
                        lot = min(MART_LOT_CAP, round_lot(lot * MART_LOT_MULT))
                        # recovery re-enters on the SAME (losing) side, stepping out
                        if L["side"] > 0:
                            px = price_c + gd * (lvl + 1)
                            mart_pending.append((1, px, lot, px + gd))
                        else:
                            px = price_c - gd * (lvl + 1)
                            mart_pending.append((-1, px, lot, px - gd))
            else:
                still.append(L)
        legs = still

        # --- 2. straddle (OCO) fills: one side fills -> cancel the other ---
        if strad_buy is not None and hi >= strad_buy[0]:
            px, lot = strad_buy
            bal -= open_cost(lot)
            legs.append({"side": 1, "entry": px, "lot": lot, "tp": px + grid_dist(px)})
            strad_buy = None
            strad_sell = None     # OCO cancel
        elif strad_sell is not None and lo <= strad_sell[0]:
            px, lot = strad_sell
            bal -= open_cost(lot)
            legs.append({"side": -1, "entry": px, "lot": lot, "tp": px - grid_dist(px)})
            strad_sell = None
            strad_buy = None      # OCO cancel

        # --- 3. martingale recovery fills ---
        new_mart = []
        for (side, px, lot, tp) in mart_pending:
            if side > 0 and hi >= px:
                bal -= open_cost(lot)
                legs.append({"side": 1, "entry": px, "lot": lot, "tp": tp})
            elif side < 0 and lo <= px:
                bal -= open_cost(lot)
                legs.append({"side": -1, "entry": px, "lot": lot, "tp": tp})
            else:
                new_mart.append((side, px, lot, tp))
        mart_pending = new_mart

        # --- 4. daily target / stop: close ALL on breach ---
        if legs and (daily_pnl >= DAILY_TARGET or daily_pnl <= DAILY_STOP):
            for L in legs:
                pnl = close_leg(L, c[i])
                bal += pnl
                daily_pnl += pnl
                trades.append(pnl)
                daily_returns[cur_day] += pnl
            legs = []
            mart_pending = []
            strad_buy = strad_sell = None
            if daily_pnl >= DAILY_TARGET:
                halted_today = True

        # --- 5. (re)arm a fresh straddle when fully flat & allowed ---
        #   This is what keeps the grid "always working": after every flat
        #   moment (start, or after a basket closes) it re-arms around c[i].
        #   Causal: uses only c[i] (this bar's close), fills only on i+1.. .
        if (not legs and not mart_pending
                and strad_buy is None and strad_sell is None
                and not halted_today and gate_ok(i)):
            gd = grid_dist(price_c)
            strad_buy = (price_c + gd, MIN_LOT)
            strad_sell = (price_c - gd, MIN_LOT)

        equity[i] = bal

    # close any residual legs at last close (no future data used)
    for L in legs:
        pnl = close_leg(L, c[-1])
        bal += pnl
        trades.append(pnl)
        daily_returns[days[-1]] = daily_returns.get(days[-1], 0.0) + pnl
    if n:
        equity[-1] = bal

    return _metrics(trades, equity, daily_returns)


def _metrics(trades, equity, daily_returns):
    net = float(equity[-1] - START_EQUITY) if len(equity) else 0.0
    peak = np.maximum.accumulate(equity) if len(equity) else np.array([START_EQUITY])
    max_dd = float((peak - equity).max()) if len(equity) else 0.0
    drets = np.array(list(daily_returns.values()), dtype=float)
    if len(drets):
        win_days = 100.0 * (drets > 0).sum() / len(drets)
        worst_day = float(drets.min())
        best_day = float(drets.max())
    else:
        win_days = 0.0
        worst_day = 0.0
        best_day = 0.0
    tr = np.array(trades, dtype=float)
    wr = 100.0 * (tr > 0).sum() / len(tr) if len(tr) else 0.0
    gp = tr[tr > 0].sum() if len(tr) else 0.0
    gl = -tr[tr < 0].sum() if len(tr) else 0.0
    pf = float(gp / gl) if gl > 1e-9 else (float(gp) if gp > 0 else 0.0)
    return {
        "net": round(net, 2),
        "trades": int(len(tr)),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "win_days_pct": round(win_days, 1),
        "worst_day": round(worst_day, 2),
        "best_day": round(best_day, 2),
        "max_dd": round(max_dd, 2),
        "n_days": int(len(drets)),
    }


def run():
    t, o, h, l, c = load_bars()
    n = len(c)
    span_days = (int(t[-1]) - int(t[0])) / 86400.0

    # indicators (full series, read causally inside sim)
    adx_arr = adx(h, l, c, 14)
    ema_arr = ema(c, 50)

    results = {"symbol": SYMBOL, "tf": TF, "bars": n,
               "period_days_calendar": round(span_days, 1),
               "spread_usd_roundtrip": SPREAD_USD_ROUNDTRIP,
               "grid_dist_at_4600_usd": round(grid_dist(4600.0), 3)}

    # ---- (A) PLAIN, full sample ----
    plain = simulate(t, o, h, l, c, range_gate=False)
    results["plain_full"] = plain

    # ---- (A) PLAIN, walk-forward blocks ----
    edges = np.linspace(0, n, N_BLOCKS + 1, dtype=int)
    plain_blocks = []
    for b in range(N_BLOCKS):
        s, e = edges[b], edges[b + 1]
        m = simulate(t[s:e], o[s:e], h[s:e], l[s:e], c[s:e], range_gate=False)
        plain_blocks.append(m)
    results["plain_blocks"] = plain_blocks
    results["plain_blocks_positive"] = sum(1 for m in plain_blocks if m["net"] > 0)

    # ---- (B) RANGE-GATED: sweep a few thresholds (full sample) ----
    sweeps = []
    configs = [
        {"adx_thr": 25.0, "ema_slope_thr": None},
        {"adx_thr": 20.0, "ema_slope_thr": None},
        {"adx_thr": 30.0, "ema_slope_thr": None},
        {"adx_thr": 25.0, "ema_slope_thr": 0.0008},
        {"adx_thr": 20.0, "ema_slope_thr": 0.0005},
    ]
    for cfg in configs:
        m = simulate(t, o, h, l, c, range_gate=True,
                     adx_thr=cfg["adx_thr"], ema_slope_thr=cfg["ema_slope_thr"],
                     ema_arr=ema_arr, adx_arr=adx_arr)
        sweeps.append({**cfg, **m})
    results["range_gated_sweeps"] = sweeps

    # ROBUSTNESS: how parameter-fragile is the gate? A real edge does not flip
    # sign when a threshold is nudged. Count net-positive swept configs and the
    # net spread across the sweep.
    sweep_nets = [s["net"] for s in sweeps]
    results["range_gated_sweep_positive"] = sum(1 for x in sweep_nets if x > 0)
    results["range_gated_sweep_count"] = len(sweep_nets)
    results["range_gated_sweep_net_min"] = round(min(sweep_nets), 2)
    results["range_gated_sweep_net_max"] = round(max(sweep_nets), 2)
    sweep_fragile = (min(sweep_nets) < 0 < max(sweep_nets))  # sign flips across sweep
    results["range_gated_sweep_sign_flips"] = bool(sweep_fragile)

    # IN-SAMPLE-PICK walk-forward (biased, kept for transparency): best full-sample
    # config re-measured per block. This OVERSTATES edge; we label it as such.
    best = max(sweeps, key=lambda x: x["net"])
    results["range_gated_best_cfg"] = {"adx_thr": best["adx_thr"],
                                       "ema_slope_thr": best["ema_slope_thr"]}
    gated_blocks = []
    for b in range(N_BLOCKS):
        s, e = edges[b], edges[b + 1]
        m = simulate(t[s:e], o[s:e], h[s:e], l[s:e], c[s:e], range_gate=True,
                     adx_thr=best["adx_thr"], ema_slope_thr=best["ema_slope_thr"],
                     ema_arr=ema_arr[s:e], adx_arr=adx_arr[s:e])
        gated_blocks.append(m)
    results["range_gated_blocks_INSAMPLE_PICK"] = gated_blocks
    results["range_gated_blocks_positive_insample"] = sum(1 for m in gated_blocks if m["net"] > 0)
    results["range_gated_full"] = {k: best[k] for k in
                                   ("net", "trades", "win_rate", "profit_factor",
                                    "win_days_pct", "worst_day", "best_day",
                                    "max_dd", "n_days")}

    # ANCHORED WALK-FORWARD (the honest test, NO selection bias): for each OOS
    # block b>=1, pick the gate threshold that was best on the prior block (b-1),
    # then APPLY it to block b. The threshold is chosen only from past data.
    cand_thrs = [(20.0, None), (25.0, None), (30.0, None)]
    wf_oos = []
    for b in range(1, N_BLOCKS):
        sp, ep = edges[b - 1], edges[b]           # train (prior block)
        so, eo = edges[b], edges[b + 1]           # test  (this block)
        best_thr, best_net = cand_thrs[1], -1e18
        for (at, es) in cand_thrs:
            mt = simulate(t[sp:ep], o[sp:ep], h[sp:ep], l[sp:ep], c[sp:ep],
                          range_gate=True, adx_thr=at, ema_slope_thr=es,
                          ema_arr=ema_arr[sp:ep], adx_arr=adx_arr[sp:ep])
            if mt["net"] > best_net:
                best_net, best_thr = mt["net"], (at, es)
        mo = simulate(t[so:eo], o[so:eo], h[so:eo], l[so:eo], c[so:eo],
                      range_gate=True, adx_thr=best_thr[0], ema_slope_thr=best_thr[1],
                      ema_arr=ema_arr[so:eo], adx_arr=adx_arr[so:eo])
        wf_oos.append({"oos_block": b, "trained_adx_thr": best_thr[0], **mo})
    results["range_gated_walkforward_OOS"] = wf_oos
    wf_net = round(sum(x["net"] for x in wf_oos), 2)
    wf_pos = sum(1 for x in wf_oos if x["net"] > 0)
    results["range_gated_walkforward_net"] = wf_net
    results["range_gated_walkforward_positive"] = wf_pos
    results["range_gated_walkforward_blocks"] = len(wf_oos)

    # ---- verdicts (strict) ----
    def plain_verdict():
        # PLAIN: positive full AND net-positive in >=4/5 blocks -> EDGE
        if plain["net"] <= 0:
            return "NO_EDGE"
        if results["plain_blocks_positive"] >= 4:
            return "EDGE"
        if results["plain_blocks_positive"] >= 3:
            return "INCONCLUSIVE"
        return "NO_EDGE"

    def range_verdict():
        # RANGE-GATED: judged ONLY on the bias-free anchored walk-forward AND
        # parameter robustness. Cherry-picked in-sample numbers do NOT count.
        if sweep_fragile:
            # net flips sign across a tiny threshold nudge -> not a real edge
            return "NO_EDGE"
        if wf_net > 0 and wf_pos >= max(3, len(wf_oos) - 1):
            return "EDGE"
        if wf_net > 0 and wf_pos >= len(wf_oos) / 2.0:
            return "INCONCLUSIVE"
        return "NO_EDGE"

    results["plain_verdict"] = plain_verdict()
    results["range_verdict"] = range_verdict()

    out_path = os.path.join(CACHE, "grid_sim_lab_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    results["_out_path"] = out_path
    return results


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
