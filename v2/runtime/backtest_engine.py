"""runtime/backtest_engine.py — Simulate a genome on historical bars.

Born 2026-05-28 for the genome academy. Lightweight but honest:
pulls real MT5 bars for ANY symbol, computes the same features the
live genome uses (MTF bias, RSI, pressure proxy), simulates entries
with the genome's SL/TP, and reports trades/WR/PnL/drawdown.

This is what lets us ask: "does the child generalize beyond gold?"
"""
from __future__ import annotations
from dataclasses import dataclass, field

import MetaTrader5 as mt5


@dataclass
class BTResult:
    symbol: str
    trades: int = 0
    wins: int = 0
    pnl_pts: float = 0.0       # net in price-points
    max_dd_pts: float = 0.0    # worst peak-to-trough in pts
    max_consec_loss: int = 0
    gross_win_pts: float = 0.0
    gross_loss_pts: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_win_pts / abs(self.gross_loss_pts) if self.gross_loss_pts else (
            self.gross_win_pts if self.gross_win_pts else 0.0)

    @property
    def expectancy_pts(self) -> float:
        return self.pnl_pts / self.trades if self.trades else 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "trades": self.trades, "wins": self.wins,
            "win_rate": round(self.win_rate * 100, 1),
            "pnl_pts": round(self.pnl_pts, 2),
            "expectancy_pts": round(self.expectancy_pts, 3),
            "profit_factor": round(self.profit_factor, 2),
            "max_dd_pts": round(self.max_dd_pts, 2),
            "max_consec_loss": self.max_consec_loss,
        }


def _ema(values, period):
    if not values: return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    rsis = [50.0] * period
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
        rs = avg_g / avg_l if avg_l else 999
        rsis.append(100 - 100/(1+rs))
    while len(rsis) < len(closes): rsis.append(rsis[-1])
    return rsis


def backtest(genome: dict, symbol: str, n_bars: int = 2500,
             lookahead: int = 12) -> BTResult:
    """Simulate the genome on `symbol` over the last n_bars M5 candles.

    Entry logic mirrors unified_trader.evaluate_genome (approximated from bars):
      • MTF bias: EMA9 vs EMA21 vs EMA50 slope on M5 (proxy for multi-TF)
      • RSI gate
      • Pressure proxy: signed momentum over last 10 bars
    Exit: whichever of SL/TP is hit first within `lookahead` bars.
    """
    res = BTResult(symbol=symbol)
    if not mt5.initialize() and not mt5.initialize():
        return res
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n_bars)
    if rates is None or len(rates) < 100:
        return res

    closes = [float(r["close"]) for r in rates]
    opens  = [float(r["open"]) for r in rates]
    highs  = [float(r["high"]) for r in rates]
    lows   = [float(r["low"]) for r in rates]

    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    rsi   = _rsi(closes, 14)

    rsi_max = genome.get("rsi_max") or 60
    rsi_min = 100 - rsi_max
    min_p   = genome.get("min_pressure_abs") or 3
    # SL/TP are ATR-relative so they scale to ANY symbol (gold, FX, crypto).
    g_sl = float(genome.get("sl_pts") or 4.0)
    g_tp = float(genome.get("tp_pts") or 10.0)
    rr = g_tp / max(g_sl, 0.1)              # reward:risk ratio
    sl_atr_mult = 1.2                        # stop = 1.2 × ATR (universal)
    side_bias = genome.get("side_bias")
    # NEW genes:
    entry_mode = genome.get("entry_mode", "trend")     # "trend" | "pullback"
    min_trend = float(genome.get("min_trend_strength") or 0.0)  # ADX-proxy gate (filters chop)

    # ATR proxy = avg true range over recent bars (symbol-native units)
    _ranges = [highs[j] - lows[j] for j in range(max(1, len(highs)-200), len(highs))]
    atr = (sum(_ranges) / len(_ranges)) if _ranges else 1e-9
    sl_dist = sl_atr_mult * atr
    tp_dist = sl_dist * rr

    equity = 0.0
    peak = 0.0
    consec = 0
    max_consec = 0
    i = 55
    while i < len(closes) - lookahead:
        # MTF proxy: stacked EMAs = trend
        up = ema9[i] > ema21[i] > ema50[i]
        dn = ema9[i] < ema21[i] < ema50[i]

        # Trend-strength gate (ADX proxy): EMA9-EMA50 separation / ATR.
        # Mirrors the live orchestrator's regime gate — skip chop.
        trend_strength = abs(ema9[i] - ema50[i]) / atr if atr else 0
        if trend_strength < min_trend:
            i += 1; continue

        # Pressure proxy: signed sum of last 10 bar bodies, scaled
        body_sum = sum((closes[j] - opens[j]) for j in range(i-9, i+1))
        avg_range = (sum(highs[j]-lows[j] for j in range(i-9, i+1)) / 10) or 1e-9
        pressure = body_sum / avg_range * 3   # ~comparable to live pressure_10m1

        direction = None
        if up:   direction = "BUY"
        elif dn: direction = "SELL"
        if direction is None:
            i += 1; continue
        if side_bias == "BUY_ONLY" and direction != "BUY": i += 1; continue
        if side_bias == "SELL_ONLY" and direction != "SELL": i += 1; continue

        r = rsi[i]
        if entry_mode == "pullback":
            # Buy the DIP in an uptrend / sell the BOUNCE in a downtrend.
            # Enter only when price pulled back toward EMA21 and RSI is
            # stretched against the trend (mean-reversion within trend).
            near_ema = abs(closes[i] - ema21[i]) <= 0.5 * atr
            if direction == "BUY":
                # uptrend but RSI dipped low (pullback) → expect bounce up
                if not (r <= rsi_min + 15 and near_ema): i += 1; continue
            else:
                if not (r >= rsi_max - 15 and near_ema): i += 1; continue
            # pullback mode ignores the momentum-pressure direction filter
        else:
            # TREND mode (momentum continuation)
            if direction == "BUY" and r >= rsi_max: i += 1; continue
            if direction == "SELL" and r <= rsi_min: i += 1; continue
            if abs(pressure) < min_p: i += 1; continue
            if direction == "BUY" and pressure < 0: i += 1; continue
            if direction == "SELL" and pressure > 0: i += 1; continue

        # Simulate the trade — outcome normalized to "R units" (× ATR).
        entry = closes[i]
        use_trailing = genome.get("use_trailing", False)
        if direction == "BUY":
            sl = entry - sl_dist; tp = entry + tp_dist
        else:
            sl = entry + sl_dist; tp = entry - tp_dist

        outcome = None
        if use_trailing:
            # Trailing exit: move SL forward as price advances (live behaviour).
            # Breakeven at +1R, then trail 0.6R behind the favorable extreme.
            be_trig = sl_dist            # +1 ATR → breakeven
            trail_gap = 0.6 * sl_dist
            best = entry
            for k in range(i+1, min(i+1+lookahead*3, len(closes))):
                if direction == "BUY":
                    best = max(best, highs[k])
                    if best - entry >= be_trig:
                        sl = max(sl, entry, best - trail_gap)   # never lower
                    if lows[k] <= sl:
                        outcome = (sl - entry) / sl_dist; break
                else:
                    best = min(best, lows[k])
                    if entry - best >= be_trig:
                        sl = min(sl, entry, best + trail_gap)
                    if highs[k] >= sl:
                        outcome = (entry - sl) / sl_dist; break
            if outcome is None:
                last = closes[min(i+lookahead*3, len(closes)-1)]
                raw = (last - entry) if direction == "BUY" else (entry - last)
                outcome = raw / sl_dist if sl_dist else 0.0
        else:
            for k in range(i+1, min(i+1+lookahead, len(closes))):
                if direction == "BUY":
                    if lows[k] <= sl: outcome = -1.0; break
                    if highs[k] >= tp: outcome = +rr; break
                else:
                    if highs[k] >= sl: outcome = -1.0; break
                    if lows[k] <= tp: outcome = +rr; break
            if outcome is None:
                last = closes[min(i+lookahead, len(closes)-1)]
                raw = (last - entry) if direction == "BUY" else (entry - last)
                outcome = raw / sl_dist if sl_dist else 0.0

        res.trades += 1
        res.pnl_pts += outcome
        if outcome > 0:
            res.wins += 1; res.gross_win_pts += outcome; consec = 0
        else:
            res.gross_loss_pts += outcome
            consec += 1; max_consec = max(max_consec, consec)
        equity += outcome
        peak = max(peak, equity)
        res.max_dd_pts = max(res.max_dd_pts, peak - equity)

        i += 3  # small step — allow more (slightly overlapping) samples for stats
    res.max_consec_loss = max_consec
    return res


__all__ = ["backtest", "BTResult"]
