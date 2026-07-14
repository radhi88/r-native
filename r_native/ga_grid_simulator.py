"""ga_grid_simulator.py — numpy backtest evaluator for the GRID / stop-reverse
strategy (the Agentic_Profiled_Grid_GOLD EA), so the existing GA campaign loop
can evolve GRID DNA the same way ga_simulator.py evolves signal genomes.

Drop-in contract — mirrors r_native.ga_simulator.simulate_genome:
    simulate_grid_genome(genome, bars, sym_info) -> stats dict
    {trades, win_rate, profit_factor, total_return_pct, sharpe, linearity,
     max_dd, net, score}

Models the EA's core "stop-reverse pair" mechanic (see the MQL5 EA's
PlaceReversePending / ManageStopReversePair / ApplyDNA):
  • when flat, arm a buy-stop and sell-stop at +/- grid_dist (ATR-scaled)
  • on a fill, take that direction; arm the opposite stop at grid_dist
  • on the opposite fill, realize the leg's P&L, reverse, scale the lot by
    lot_factor (bounded by MinLotFactor..1 via LotReductionFactor)
  • ATR stop-loss / take-profit; session-hour + Friday-close filters

IMPORTANT — VALIDATION GATE: this is an approximation of the MQL5 grid logic,
not bit-exact. Genomes it favours MUST be paper-proven (or MT5-tester-confirmed)
before any live deploy — same PROVEN-needs-approval gate the signal genomes use.
"""
from __future__ import annotations
import numpy as np


# Gene space for grid DNA — names mirror the EA's AgentDNA fields.
GRID_GENE_SPACE = {
    "grid_dist_atr":       (0.5, 4.0),    # grid spacing in ATR multiples
    "sl_atr_mult":         (1.0, 6.0),
    "tp_atr_mult":         (1.0, 10.0),
    "lot_factor":          (1.0, 2.5),    # scale-up on reverse
    "min_lot_factor":      (0.1, 0.5),    # floor after reductions
    "lot_reduction":       (0.3, 0.9),    # multiply lot toward floor each reverse
    "atr_period":          (8, 30),
    "start_hour":          (0, 12),
    "end_hour":            (12, 23),
    "friday_close":        (12, 22),
    "max_reverses":        (2, 12),       # basket cap before forced flatten
}


def _atr(h, l, c, n):
    tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    if len(tr) < n:
        return np.array([])
    return np.convolve(tr, np.ones(n) / n, mode="valid")


def _stats(trades, equity, start_equity):
    """Shape-compatible with ga_simulator.simulate_genome's return."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "total_return_pct": 0.0, "sharpe": 0.0, "linearity": 0.0,
                "max_dd": 0.0, "net": 0.0, "score": 0.0}
    arr = np.array(trades, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = 100.0 * len(wins) / len(arr)
    gp, gl = wins.sum(), -losses.sum()
    pf = float((gp / gl) if gl > 1e-9 else (gp if gp > 0 else 0.0))
    eq = np.array(equity, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / np.maximum(peak, 1e-9)).max() * 100.0)
    net = float(eq[-1] - start_equity)
    total_ret = 100.0 * net / start_equity
    rets = np.diff(eq)
    sharpe = float(rets.mean() / (rets.std() + 1e-9) * np.sqrt(252)) if len(rets) > 1 else 0.0
    # linearity: R^2 of equity curve vs a straight line (smoothness of growth)
    x = np.arange(len(eq))
    if len(eq) > 2 and eq.std() > 1e-9:
        lin = float(np.corrcoef(x, eq)[0, 1] ** 2)
    else:
        lin = 0.0
    # composite score (same spirit as the signal sim: reward PF + return, punish DD)
    score = float(round(pf * 10 + total_ret - dd * 0.5 + wr * 0.1, 2))
    return {"trades": len(arr), "win_rate": round(wr, 1), "profit_factor": round(pf, 2),
            "total_return_pct": round(total_ret, 2), "sharpe": round(sharpe, 2),
            "linearity": round(lin, 3), "max_dd": round(dd, 2),
            "net": round(net, 2), "score": score}


def simulate_grid_genome(genome: dict, bars, sym_info=None) -> dict:
    if bars is None or len(bars) < 120:
        return {"trades": 0, "score": 0.0}
    p = genome.get("params", {})
    g = lambda k: float(p.get(k, sum(GRID_GENE_SPACE[k]) / 2))

    h = np.asarray(bars["high"], float); l = np.asarray(bars["low"], float)
    c = np.asarray(bars["close"], float)
    import datetime as _dt
    try:
        secs = np.asarray(bars["time"]).astype("int64")
        hours = np.array([_dt.datetime.utcfromtimestamp(int(t)).hour for t in secs])
        wdays = np.array([_dt.datetime.utcfromtimestamp(int(t)).weekday() for t in secs])
    except Exception:
        hours = np.zeros(len(c), int); wdays = np.zeros(len(c), int)

    n = int(round(g("atr_period")))
    atr = _atr(h, l, c, max(8, min(30, n)))
    if len(atr) == 0:
        return {"trades": 0, "score": 0.0}
    off = len(c) - len(atr)

    grid_atr = g("grid_dist_atr"); sl_m = g("sl_atr_mult"); tp_m = g("tp_atr_mult")
    lotf = g("lot_factor"); minf = g("min_lot_factor"); red = g("lot_reduction")
    sh, eh, fc = int(g("start_hour")), int(g("end_hour")), int(g("friday_close"))
    maxrev = int(g("max_reverses"))

    point = float(sym_info.get("point", 0.01)) if isinstance(sym_info, dict) else 0.01
    tick_val = float(sym_info.get("trade_tick_value", 1.0)) if isinstance(sym_info, dict) else 1.0
    tick_sz = float(sym_info.get("trade_tick_size", point)) if isinstance(sym_info, dict) else point

    start_equity = 10000.0
    bal = start_equity
    equity = [bal]
    trades = []
    side = 0; entry = 0.0; lot = 1.0; reverses = 0
    pend_buy = pend_sell = 0.0   # armed stop prices (0 = none)

    def pnl(exit_price):
        d = (exit_price - entry) if side > 0 else (entry - exit_price)
        return d / tick_sz * tick_val * lot

    def scaled(L, rev):
        # alternate scale-up (reverse) and reduction-toward-floor, like the EA's DNA
        return min(lotf, L * lotf) if rev % 2 else max(minf, L * red)

    for i in range(off, len(c)):
        a = atr[i - off]
        hr, wd = int(hours[i]), int(wdays[i])
        in_session = (sh <= hr <= eh)
        friday_flat = (wd == 4 and hr >= fc)

        if side != 0:
            closed = None
            # SL / TP on this bar's range (one fill per bar)
            if side > 0:
                if l[i] <= entry - sl_m * a:   closed = entry - sl_m * a
                elif h[i] >= entry + tp_m * a: closed = entry + tp_m * a
            else:
                if h[i] >= entry + sl_m * a:   closed = entry + sl_m * a
                elif l[i] <= entry - tp_m * a: closed = entry - tp_m * a
            if closed is not None:
                t = pnl(closed); trades.append(t); bal += t; side = 0; reverses = 0
                pend_buy = pend_sell = 0.0
            elif friday_flat:
                t = pnl(c[i]); trades.append(t); bal += t; side = 0; reverses = 0
                pend_buy = pend_sell = 0.0
            # reverse-stop fill: opposite stop hit -> realize leg, flip, scale lot
            elif side > 0 and pend_sell and l[i] <= pend_sell and reverses < maxrev:
                t = pnl(pend_sell); trades.append(t); bal += t
                entry = pend_sell; side = -1; reverses += 1; lot = scaled(lot, reverses)
                pend_buy = entry + grid_atr * a; pend_sell = 0.0
            elif side < 0 and pend_buy and h[i] >= pend_buy and reverses < maxrev:
                t = pnl(pend_buy); trades.append(t); bal += t
                entry = pend_buy; side = 1; reverses += 1; lot = scaled(lot, reverses)
                pend_sell = entry - grid_atr * a; pend_buy = 0.0

        # flat: arm a straddle ONCE, let it sit until a stop fills on a later bar
        if side == 0:
            if not in_session or friday_flat:
                pend_buy = pend_sell = 0.0
            else:
                if pend_buy == 0.0 and pend_sell == 0.0:
                    pend_buy = c[i] + grid_atr * a
                    pend_sell = c[i] - grid_atr * a
                if h[i] >= pend_buy:
                    side = 1; entry = pend_buy; lot = 1.0; reverses = 0
                    pend_sell = entry - grid_atr * a; pend_buy = 0.0
                elif l[i] <= pend_sell:
                    side = -1; entry = pend_sell; lot = 1.0; reverses = 0
                    pend_buy = entry + grid_atr * a; pend_sell = 0.0

        equity.append(bal)

    if side != 0:
        t = pnl(c[-1]); trades.append(t); bal += t; equity.append(bal)
    return _stats(trades, equity, start_equity)


# ---- self-test: runs on a synthetic trend+noise series so we can verify it
# executes and returns sane stats without needing live MT5 data ----------------
if __name__ == "__main__":
    rng = np.random.default_rng(7)
    nbar = 3000
    price = 2000 + np.cumsum(rng.normal(0.02, 1.5, nbar))   # gold-ish drift
    bars = np.zeros(nbar, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"),
                                 ("low", "f8"), ("close", "f8")])
    bars["close"] = price
    bars["open"] = np.concatenate([[price[0]], price[:-1]])
    bars["high"] = np.maximum(bars["open"], bars["close"]) + np.abs(rng.normal(0, 0.6, nbar))
    bars["low"] = np.minimum(bars["open"], bars["close"]) - np.abs(rng.normal(0, 0.6, nbar))
    bars["time"] = 1_700_000_000 + np.arange(nbar) * 300
    genome = {"params": {"grid_dist_atr": 1.5, "sl_atr_mult": 2.0, "tp_atr_mult": 4.0,
                          "lot_factor": 1.5, "min_lot_factor": 0.25, "lot_reduction": 0.5,
                          "atr_period": 14, "start_hour": 0, "end_hour": 23,
                          "friday_close": 18, "max_reverses": 6}}
    sym = {"point": 0.01, "trade_tick_value": 1.0, "trade_tick_size": 0.01}
    out = simulate_grid_genome(genome, bars, sym)
    print("grid sim self-test:", out)
