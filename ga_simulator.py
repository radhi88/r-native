"""ga_simulator.py - Pure-numpy backtest evaluator for a genome.

Given:
  genome_dict (flags + params)
  bars (numpy structured array from mt5.copy_rates_*)
  sym_info (symbol_info from MT5)

Returns:
  stats dict: trades, wins, win_rate, profit_factor, max_dd, sharpe,
              linearity, total_return_pct, equity_curve_summary
"""
from __future__ import annotations
import math
import statistics
from datetime import datetime, timezone

import numpy as np


def _sma(a, n):
    if len(a) < n: return np.array([])
    return np.convolve(a, np.ones(n)/n, mode='valid')

def _atr(h, l, c, n=14):
    tr = np.maximum.reduce([h[1:] - l[1:],
                             np.abs(h[1:] - c[:-1]),
                             np.abs(l[1:] - c[:-1])])
    return _sma(tr, n)

def _rsi(c, n=14):
    diffs = np.diff(c)
    gains = np.where(diffs > 0, diffs, 0)
    losses = np.where(diffs < 0, -diffs, 0)
    if len(diffs) < n: return np.array([50]*len(c))
    out = []
    avg_g = np.mean(gains[:n]); avg_l = np.mean(losses[:n])
    for i in range(n, len(diffs)):
        avg_g = (avg_g * (n-1) + gains[i]) / n
        avg_l = (avg_l * (n-1) + losses[i]) / n
        out.append(100 - 100/(1 + (avg_g/avg_l)) if avg_l > 0 else 100)
    return np.array([50]*(n+1) + out)


def _linearity(equity_curve: list) -> float:
    """How close is equity curve to a straight line? R² of linear fit, 0..1."""
    if len(equity_curve) < 5: return 0
    x = np.arange(len(equity_curve))
    y = np.array(equity_curve)
    if y.std() == 0: return 0
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = ((y - pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    if ss_tot == 0: return 0
    return max(0.0, min(1.0, 1 - ss_res / ss_tot))


def simulate_genome(genome: dict, bars, sym_info) -> dict:
    """Evaluate one genome on the bars. Returns stats dict."""
    flags = genome.get("flags", {})
    params = genome.get("params", {})
    if bars is None or len(bars) < 100: return {"trades": 0}

    o = bars["open"].astype(float)
    h = bars["high"].astype(float)
    l = bars["low"].astype(float)
    c = bars["close"].astype(float)
    times = bars["time"]

    # Pre-compute indicators based on what's enabled
    atr_p = max(8, min(30, int(params.get("atr_period", 14))))
    atr = _atr(h, l, c, atr_p)
    rsi = _rsi(c, max(8, min(28, int(params.get("rsi_period", 14)))))
    rsi_lo = params.get("rsi_lower", 30)
    rsi_hi = params.get("rsi_upper", 70)
    sf_n = max(5, min(25, int(params.get("ema_fast", 8))))
    ss_n = max(15, min(80, int(params.get("ema_slow", 21))))
    sma_fast = _sma(c, sf_n)
    sma_slow = _sma(c, ss_n)
    bo_n = max(10, min(50, int(params.get("breakout_lookback", 20))))

    # Session
    start_h = int(params.get("start_hour", 0))
    end_h   = int(params.get("end_hour", 23))
    if end_h <= start_h: end_h = min(23, start_h + 4)
    friday_close = int(params.get("friday_close", 18))
    no_friday = flags.get("use_no_open_friday", False)
    fri_close_profit = flags.get("use_friday_close_profit", False)

    # Risk params
    sl_mult = float(params.get("sl_atr_mult", 2.0))
    tp_mult = float(params.get("tp_atr_mult", 5.0))
    # Min RR sanity
    if tp_mult <= 0.5: tp_mult = 1.0
    if sl_mult <= 0.2: sl_mult = 0.5

    consec_max = int(params.get("consec_max", 3))
    use_be     = flags.get("use_breakeven", False)
    use_eod    = flags.get("use_eod_close", False)
    use_partial= flags.get("use_partial_tp", False)
    use_sl_lock= flags.get("use_sl_lock", False)
    use_sl_red = flags.get("use_sl_reduce", False)
    use_trail  = flags.get("use_bias_trailing", False)

    point   = sym_info.point if sym_info else 0.001
    contract= sym_info.trade_contract_size if sym_info else 100
    LOT     = 0.01
    # Estimated spread cost (use current symbol spread)
    spread_pt = 0
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(sym_info.name)
        if tick:
            spread_pt = (tick.ask - tick.bid) / point
    except Exception: pass
    spread_price = spread_pt * point

    # ─── Iterate bars ───
    trades = []
    equity_curve = [0.0]
    cum_pl = 0.0
    pos = None
    consec_losses = 0
    cooldown = 0

    start_idx = max(50, len(c) - 4000)   # only test last 4000 bars
    for i in range(start_idx, len(c) - 1):
        # Index offsets for indicator arrays
        atr_i = i - (len(c) - len(atr)) if i - (len(c) - len(atr)) >= 0 else 0
        if atr_i >= len(atr): continue
        rsi_i = i if i < len(rsi) else len(rsi) - 1
        smf_i = i - (len(c) - len(sma_fast)) if i - (len(c) - len(sma_fast)) >= 0 else 0
        sms_i = i - (len(c) - len(sma_slow)) if i - (len(c) - len(sma_slow)) >= 0 else 0

        cur_atr = atr[atr_i] if atr_i < len(atr) else 0
        if cur_atr <= 0: continue
        cur_rsi = rsi[rsi_i]
        sf = sma_fast[smf_i] if smf_i < len(sma_fast) else c[i]
        ss = sma_slow[sms_i] if sms_i < len(sma_slow) else c[i]

        # Session filter
        bar_dt = datetime.fromtimestamp(int(times[i]), tz=timezone.utc)
        hour = bar_dt.hour
        weekday = bar_dt.weekday()    # 0=Mon
        in_session = start_h <= hour < end_h
        is_friday = weekday == 4

        # Manage open position
        if pos:
            bar_h = h[i]; bar_l = l[i]
            # Friday close
            if fri_close_profit and is_friday and hour >= friday_close:
                exit_p = c[i]
                pl = ((exit_p - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - exit_p)) * LOT * contract
                trades.append((pl, "FRIDAY"))
                pos = None; cooldown = 2
                cum_pl += pl
                equity_curve.append(cum_pl)
                if pl < 0: consec_losses += 1
                else: consec_losses = 0
                continue
            # SL/TP intra-bar (conservative: assume SL hit first if both could)
            if pos["side"] == "BUY":
                if bar_l <= pos["sl"]:
                    pl = (pos["sl"] - pos["entry"]) * LOT * contract
                    trades.append((pl, "SL"))
                    pos = None; cooldown = 2; consec_losses += 1
                    cum_pl += pl; equity_curve.append(cum_pl)
                    continue
                if bar_h >= pos["tp"]:
                    pl = (pos["tp"] - pos["entry"]) * LOT * contract
                    trades.append((pl, "TP"))
                    pos = None; cooldown = 2; consec_losses = 0
                    cum_pl += pl; equity_curve.append(cum_pl)
                    continue
                # Break-even nudge
                if use_be and (c[i] - pos["entry"]) > cur_atr * 1.5:
                    pos["sl"] = max(pos["sl"], pos["entry"] + cur_atr * 0.1)
            else:    # SELL
                if bar_h >= pos["sl"]:
                    pl = (pos["entry"] - pos["sl"]) * LOT * contract
                    trades.append((pl, "SL"))
                    pos = None; cooldown = 2; consec_losses += 1
                    cum_pl += pl; equity_curve.append(cum_pl)
                    continue
                if bar_l <= pos["tp"]:
                    pl = (pos["entry"] - pos["tp"]) * LOT * contract
                    trades.append((pl, "TP"))
                    pos = None; cooldown = 2; consec_losses = 0
                    cum_pl += pl; equity_curve.append(cum_pl)
                    continue
                if use_be and (pos["entry"] - c[i]) > cur_atr * 1.5:
                    pos["sl"] = min(pos["sl"], pos["entry"] - cur_atr * 0.1)
            continue

        # Don't open if cooldown / consec losses / wrong session
        if cooldown > 0: cooldown -= 1; continue
        if not in_session: continue
        if no_friday and is_friday: continue
        if consec_losses >= consec_max: continue

        # ─── Entry signal logic (combines all enabled signal genes) ───
        signal = None
        score = 0
        # Breakout
        if flags.get("use_sig_breakout"):
            recent_h = h[max(0, i - bo_n):i].max()
            recent_l = l[max(0, i - bo_n):i].min()
            if c[i] > recent_h: signal = "BUY"; score += 25
            elif c[i] < recent_l: signal = "SELL"; score += 25
        # Momentum break (smaller breakout)
        if flags.get("use_sig_mom_break") and not signal:
            recent_h_s = h[max(0, i-5):i].max()
            recent_l_s = l[max(0, i-5):i].min()
            if c[i] > recent_h_s: signal = "BUY"; score += 15
            elif c[i] < recent_l_s: signal = "SELL"; score += 15
        # RSI extreme
        if flags.get("use_sig_rsi"):
            if cur_rsi < rsi_lo: signal = signal or "BUY"; score += 15
            elif cur_rsi > rsi_hi: signal = signal or "SELL"; score += 15
        # MACD-like (sma_fast cross sma_slow)
        if flags.get("use_sig_macd") and smf_i > 0 and sms_i > 0:
            sf_prev = sma_fast[smf_i-1] if smf_i-1 < len(sma_fast) else sf
            ss_prev = sma_slow[sms_i-1] if sms_i-1 < len(sma_slow) else ss
            if sf_prev < ss_prev and sf > ss: signal = signal or "BUY"; score += 10
            elif sf_prev > ss_prev and sf < ss: signal = signal or "SELL"; score += 10
        # Engulfing
        if flags.get("use_sig_engulfing") and i > 0:
            prev_o, prev_c = o[i-1], c[i-1]
            if c[i] > o[i] and o[i] < prev_c and c[i] > prev_o:
                signal = signal or "BUY"; score += 12
            elif c[i] < o[i] and o[i] > prev_c and c[i] < prev_o:
                signal = signal or "SELL"; score += 12
        # Pin bar
        if flags.get("use_sig_pin_bar"):
            body = abs(c[i] - o[i])
            uw = h[i] - max(o[i], c[i])
            lw = min(o[i], c[i]) - l[i]
            if lw > body * 2 and c[i] > o[i]: signal = signal or "BUY"; score += 10
            elif uw > body * 2 and c[i] < o[i]: signal = signal or "SELL"; score += 10

        # ─── Bias filter (must agree with signal direction) ───
        if signal:
            if flags.get("use_bias_sma"):
                bias = "BUY" if sf > ss else "SELL"
                if signal != bias: signal = None
            if signal and flags.get("use_bias_rsi"):
                bias = "BUY" if cur_rsi > 50 else "SELL"
                if signal != bias: signal = None
            if signal and flags.get("use_bias_ema"):
                if signal == "BUY" and c[i] < sf: signal = None
                elif signal == "SELL" and c[i] > sf: signal = None

        # ─── Filter genes (block signals in bad conditions) ───
        if signal:
            if flags.get("use_filt_consec") and consec_losses >= 2:
                signal = None
            if signal and flags.get("use_filt_rsi"):
                # RSI must not be at opposite extreme
                if signal == "BUY" and cur_rsi > 75: signal = None
                elif signal == "SELL" and cur_rsi < 25: signal = None
            if signal and flags.get("use_filt_sma"):
                # Price must be on the right side of SMA
                if signal == "BUY" and c[i] < ss: signal = None
                elif signal == "SELL" and c[i] > ss: signal = None
            if signal and flags.get("use_filt_volatility"):
                # ATR must be in middle range (not too quiet, not too explosive)
                recent_atr = atr[max(0, atr_i-20):atr_i].mean() if atr_i > 20 else cur_atr
                if recent_atr > 0 and (cur_atr < recent_atr * 0.5 or cur_atr > recent_atr * 2.5):
                    signal = None

        # Minimum score threshold (use param but cap at 25 for any-signal entry)
        min_score = min(25, int(params.get("min_score", 40)))
        if signal and score < min_score:
            signal = None
        # If no enabled signal genes at all, fall back to simple breakout (so we always get trades)
        if signal is None and not any(flags.get(s) for s in
            ["use_sig_breakout","use_sig_mom_break","use_sig_rsi","use_sig_macd",
             "use_sig_engulfing","use_sig_pin_bar"]):
            recent_h = h[max(0, i - 20):i].max()
            recent_l = l[max(0, i - 20):i].min()
            if c[i] > recent_h: signal = "BUY"
            elif c[i] < recent_l: signal = "SELL"

        if not signal: continue

        # Open the position
        entry = c[i] + spread_price / 2 if signal == "BUY" else c[i] - spread_price / 2
        sl_dist = cur_atr * sl_mult
        tp_dist = cur_atr * tp_mult
        sl = entry - sl_dist if signal == "BUY" else entry + sl_dist
        tp = entry + tp_dist if signal == "BUY" else entry - tp_dist
        pos = {"side": signal, "entry": entry, "sl": sl, "tp": tp, "open_i": i}

    # Compute stats
    if not trades:
        return {"trades": 0, "score": 0}
    profits = [p for p, _ in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    gw = sum(wins); gl = abs(sum(losses))
    wr = len(wins) / len(trades) * 100
    pf = gw / gl if gl > 0 else (999 if wins else 0)
    # Sharpe per trade
    if len(profits) > 1:
        mean = statistics.mean(profits)
        sd = statistics.stdev(profits)
        sharpe = (mean / sd) * math.sqrt(len(profits)) if sd > 0 else 0
    else:
        sharpe = 0
    # Drawdown
    bal, peak, dd = 0, 0, 0
    for p in profits:
        bal += p; peak = max(peak, bal); dd = max(dd, peak - bal)
    total_ret = sum(profits)
    # Linearity (R² of equity curve)
    lin = _linearity(equity_curve)
    return {
        "trades":         len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(wr, 1),
        "profit_factor":  round(pf, 2),
        "total_return_pct": round(total_ret, 2),
        "max_drawdown_pct": round(dd, 2),
        "sharpe":         round(sharpe, 2),
        "linearity":      round(lin, 3),
        "avg_win":        round(gw / max(1, len(wins)), 4),
        "avg_loss":       round(-gl / max(1, len(losses)), 4),
        "exit_breakdown": {
            "TP":     sum(1 for _, r in trades if r == "TP"),
            "SL":     sum(1 for _, r in trades if r == "SL"),
            "FRIDAY": sum(1 for _, r in trades if r == "FRIDAY"),
        },
    }
