"""
oos_backtest.py — BRICK B2
==========================
INDEPENDENT out-of-sample backtester for OUR (r_native_v2) genomes.

WHY THIS EXISTS
---------------
The numbers stamped on our deployed genomes (e.g. "OOS: +529%/PF4.48/lin0.98")
come from the *Algory* factory's own backtester. This module is a SECOND,
INDEPENDENT opinion. It does NOT call Algory, does NOT reuse Algory code, and
does NOT trust Algory's stats. It pulls raw MT5 history and re-evaluates a
genome from scratch using only core indicators.

  *** THIS IS AN APPROXIMATION — READ THIS ***
  The LIVE brain (runtime.brain_v1 / runtime.unified_trader) decides on a rich
  snapshot: order-flow footprint pressure, market structure, multi-timeframe
  bias from real MTF frames, S/R clusters, round numbers, candle patterns, an
  ML confidence gate, and a trend-alignment veto sourced from live MTF frames.
  This backtester reconstructs ONLY core indicators per bar:
      RSI14, EMA20, EMA50, ADX14, session-from-UTC-hour, and a *simple* MTF bias
      (EMA20-vs-EMA50 on this TF AND on one higher TF).
  It applies ONLY the subset of genome gates that map cleanly onto those core
  features (session_filter, side_bias, rsi_max + SELL mirror rule, sl_pts/tp_pts
  with honor_tp, trend_align as a SOFT filter). Pressure/structure/ML gates are
  NOT reproduced. Therefore:
      • Results will differ from both the live brain and the Algory backtest.
      • Treat the verdict as a robustness sanity check ("does the edge survive a
        naive core-indicator re-run?"), NOT as a profitability promise.
      • A genome that passes here is *less likely* to be a curve-fit artifact;
        a genome that fails here deserves scrutiny before trusting live capital.

Public API
----------
    backtest_genome(symbol, timeframe_str, genome, days=120) -> dict

Dependencies: numpy, MetaTrader5, runtime.shared.cost_model (with a safe
fallback if that sibling brick is not yet present).

This module is READ-ONLY with respect to live state: it never writes live
files, never sends orders, never mutates the genome.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

try:
    import MetaTrader5 as mt5
except Exception as _e:  # pragma: no cover
    mt5 = None
    _MT5_IMPORT_ERROR = _e
else:
    _MT5_IMPORT_ERROR = None


# ───────────────────────────── cost model ──────────────────────────────────
# Prefer the shared cost model (sibling brick B1). It is expected to expose a
# round-trip cost in *gold-points / price-units* per round turn. We probe a few
# plausible interfaces so B2 keeps working whether B1 lands before or after it.
# If nothing is available we fall back to a conservative XAUUSDm-ish default.

_FALLBACK_RT_COST_PTS = 0.30   # ~spread+commission+slippage, in gold-points
_COST_SOURCE = "fallback_default"


def _round_trip_cost_pts(symbol: str) -> float:
    """Round-trip trading cost expressed in gold-points (price units), per trade.

    Tries runtime.shared.cost_model first. Documented as an APPROXIMATION: real
    cost varies with spread regime, session and fill quality."""
    global _COST_SOURCE
    try:
        from runtime.shared import cost_model as _cm  # type: ignore
    except Exception:
        _COST_SOURCE = "fallback_default"
        return _FALLBACK_RT_COST_PTS

    # Try the most specific / likely interfaces in order.
    for attr in ("round_trip_cost_pts", "round_trip_pts", "round_trip_cost",
                 "roundtrip_cost", "cost_pts"):
        fn = getattr(_cm, attr, None)
        if callable(fn):
            try:
                val = float(fn(symbol))
                _COST_SOURCE = f"runtime.shared.cost_model.{attr}"
                return val
            except Exception:
                try:
                    val = float(fn())
                    _COST_SOURCE = f"runtime.shared.cost_model.{attr}()"
                    return val
                except Exception:
                    pass

    # A class-based model: cost_model.CostModel(symbol).round_trip_pts()
    cls = getattr(_cm, "CostModel", None)
    if cls is not None:
        try:
            inst = cls(symbol)
            for attr in ("round_trip_pts", "round_trip_cost_pts", "round_trip_cost"):
                m = getattr(inst, attr, None)
                if callable(m):
                    val = float(m())
                    _COST_SOURCE = f"runtime.shared.cost_model.CostModel.{attr}"
                    return val
                if m is not None:
                    val = float(m)
                    _COST_SOURCE = f"runtime.shared.cost_model.CostModel.{attr}"
                    return val
        except Exception:
            pass

    # A module-level constant.
    for attr in ("ROUND_TRIP_COST_PTS", "DEFAULT_ROUND_TRIP_PTS"):
        v = getattr(_cm, attr, None)
        if v is not None:
            try:
                _COST_SOURCE = f"runtime.shared.cost_model.{attr}"
                return float(v)
            except Exception:
                pass

    _COST_SOURCE = "fallback_default"
    return _FALLBACK_RT_COST_PTS


# ─────────────────────────── MT5 timeframes ────────────────────────────────

def _tf_const(timeframe_str: str):
    s = str(timeframe_str).upper().strip()
    table = {
        "M1": "TIMEFRAME_M1", "M2": "TIMEFRAME_M2", "M3": "TIMEFRAME_M3",
        "M4": "TIMEFRAME_M4", "M5": "TIMEFRAME_M5", "M6": "TIMEFRAME_M6",
        "M10": "TIMEFRAME_M10", "M12": "TIMEFRAME_M12", "M15": "TIMEFRAME_M15",
        "M20": "TIMEFRAME_M20", "M30": "TIMEFRAME_M30",
        "H1": "TIMEFRAME_H1", "H2": "TIMEFRAME_H2", "H3": "TIMEFRAME_H3",
        "H4": "TIMEFRAME_H4", "H6": "TIMEFRAME_H6", "H8": "TIMEFRAME_H8",
        "H12": "TIMEFRAME_H12", "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
        "MN1": "TIMEFRAME_MN1",
    }
    name = table.get(s)
    if name is None or mt5 is None:
        return None
    return getattr(mt5, name, None)


def _higher_tf_str(timeframe_str: str) -> str:
    """One step up for the simple MTF-bias confirmation."""
    s = str(timeframe_str).upper().strip()
    ladder = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    if s in ladder:
        i = ladder.index(s)
        return ladder[min(i + 2, len(ladder) - 1)]  # ~2 steps for separation
    return "H1"


# ─────────────────────────── core indicators ───────────────────────────────
# Vectorized numpy. Wilder-smoothed RSI and ADX to match common MT5 conventions.

def _ema(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n = values.size
    out = np.empty(n, dtype=float)
    if n == 0:
        return out
    k = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, n):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def _rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    n = close.size
    rsi = np.full(n, 50.0, dtype=float)
    if n < period + 1:
        return rsi
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    for i in range(period, n):
        g = gain[i - 1]
        l = loss[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _adx_wilder(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                period: int = 14) -> np.ndarray:
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = close.size
    adx = np.zeros(n, dtype=float)
    if n < 2 * period + 1:
        return adx

    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1]),
    ])

    # Wilder smoothing of TR, +DM, -DM (length n-1, aligned to bar i>=1).
    atr = np.zeros(tr.size)
    sp = np.zeros(tr.size)
    sm = np.zeros(tr.size)
    atr[period - 1] = tr[:period].sum()
    sp[period - 1] = plus_dm[:period].sum()
    sm[period - 1] = minus_dm[:period].sum()
    for i in range(period, tr.size):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / period + plus_dm[i]
        sm[i] = sm[i - 1] - sm[i - 1] / period + minus_dm[i]

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * np.where(atr > 0, sp / atr, 0.0)
        minus_di = 100.0 * np.where(atr > 0, sm / atr, 0.0)
        denom = plus_di + minus_di
        dx = 100.0 * np.where(denom > 0, np.abs(plus_di - minus_di) / denom, 0.0)

    # ADX = Wilder average of DX, mapped back to full-length array (offset +1).
    adx_dm = np.zeros(tr.size)
    first = 2 * period - 1
    if first < tr.size:
        adx_dm[first] = dx[period - 1: first + 1].mean()
        for i in range(first + 1, tr.size):
            adx_dm[i] = (adx_dm[i - 1] * (period - 1) + dx[i]) / period
    adx[1:] = adx_dm
    return adx


def _session_from_hour(hour_utc: int) -> str:
    """Task-spec session mapping (UTC hour). 13-17 NY_OVERLAP, 8-13 LONDON,
    17-21 NY_LATE, else ASIAN."""
    h = int(hour_utc)
    if 13 <= h < 17:
        return "NY_OVERLAP"
    if 8 <= h < 13:
        return "LONDON"
    if 17 <= h < 21:
        return "NY_LATE"
    return "ASIAN"


# ───────────────────────────── data pull ───────────────────────────────────

def _ensure_mt5():
    if mt5 is None:
        raise RuntimeError(f"MetaTrader5 import failed: {_MT5_IMPORT_ERROR}")
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")


def _copy_rates(symbol: str, tf_const, days: int) -> np.ndarray:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, tf_const, start, end)
    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"copy_rates_range returned no data for {symbol} "
            f"({mt5.last_error() if mt5 else 'n/a'})")
    return rates


def _higher_tf_bias_for_times(symbol: str, higher_tf_const, times_sec: np.ndarray,
                              days: int) -> np.ndarray:
    """Per-bar higher-TF bias (+1 UP / -1 DOWN / 0 RANGE) by EMA20 vs EMA50 on
    the higher TF, forward-filled onto each lower-TF bar's open time."""
    n = times_sec.size
    out = np.zeros(n, dtype=int)
    if higher_tf_const is None:
        return out
    try:
        hr = _copy_rates(symbol, higher_tf_const, days + 5)
    except Exception:
        return out
    if hr is None or len(hr) < 60:
        return out
    h_close = hr["close"].astype(float)
    h_time = hr["time"].astype(np.int64)
    h_e20 = _ema(h_close, 20)
    h_e50 = _ema(h_close, 50)
    h_bias = np.where(h_e20 > h_e50, 1, np.where(h_e20 < h_e50, -1, 0))
    # For each lower-TF bar, take the most recent *closed* higher-TF bar.
    idx = np.searchsorted(h_time, times_sec.astype(np.int64), side="right") - 1
    idx = np.clip(idx, 0, h_time.size - 1)
    out = h_bias[idx]
    return out


# ─────────────────────────── stats helpers ─────────────────────────────────

def _r2_equity_vs_time(equity: np.ndarray) -> float:
    """R^2 of the equity curve against a straight line in time (linearity).
    1.0 = perfectly linear growth. Empty/flat → 0.0."""
    equity = np.asarray(equity, dtype=float)
    n = equity.size
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    if np.allclose(equity, equity[0]):
        return 0.0
    try:
        slope, intercept = np.polyfit(x, equity, 1)
    except Exception:
        return 0.0
    pred = slope * x + intercept
    ss_res = float(np.sum((equity - pred) ** 2))
    ss_tot = float(np.sum((equity - equity.mean()) ** 2))
    if ss_tot <= 0:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _max_dd_pct(equity_with_start: np.ndarray) -> float:
    """Max drawdown as a percentage of running peak. equity is cumulative
    account value starting at a positive base."""
    eq = np.asarray(equity_with_start, dtype=float)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (peak - eq) / peak, 0.0)
    return float(np.max(dd) * 100.0)


# ───────────────────────────── core engine ─────────────────────────────────

def backtest_genome(symbol: str, timeframe_str: str, genome: dict,
                    days: int = 120) -> dict:
    """Independent OOS backtest of one genome on core indicators only.

    APPROXIMATION — see module docstring. Applies ONLY the genome gates that
    map onto core features (session_filter, side_bias, rsi_max + SELL mirror,
    sl_pts/tp_pts with honor_tp, trend_align as a soft filter). Simulates one
    position at a time, exits on SL or TP, and subtracts a round-trip cost from
    runtime.shared.cost_model. Splits the period 67% IS / 33% OOS by time.

    Returns a stats dict (see keys at the bottom of this function)."""

    # Genome params live under "params" for our deployed-genome files, but a
    # bare params dict is also accepted.
    params = genome.get("params") if isinstance(genome, dict) and "params" in genome else genome
    params = params or {}

    session_filter = params.get("session_filter") or []
    side_bias      = params.get("side_bias")            # None / "BUY_ONLY" / "SELL_ONLY"
    rsi_max        = float(params.get("rsi_max", 60))
    rsi_min        = 100.0 - rsi_max                    # unified_trader SELL mirror
    sl_pts         = float(params.get("sl_pts", 4.0))
    tp_pts         = float(params.get("tp_pts", 12.0))
    honor_tp       = bool(params.get("honor_tp", False))
    trend_align    = bool(params.get("trend_align", True))

    # honor_tp semantics from unified_trader: if NOT honoring tp, the live trail
    # handles the exit so the genome's tight tp is inflated. We mirror that so a
    # non-honor_tp genome is simulated with the same effective TP the live path
    # would use (a trail proxy → wide fixed TP). honor_tp genomes use tp as-is.
    if not honor_tp:
        tp_pts = max(tp_pts, 20.0)

    _ensure_mt5()
    tf_const = _tf_const(timeframe_str)
    if tf_const is None:
        raise ValueError(f"Unknown/unsupported timeframe: {timeframe_str!r}")

    rates = _copy_rates(symbol, tf_const, days)
    open_  = rates["open"].astype(float)
    high   = rates["high"].astype(float)
    low    = rates["low"].astype(float)
    close  = rates["close"].astype(float)
    times  = rates["time"].astype(np.int64)             # epoch seconds (UTC)
    n = close.size

    # point size: gold pt = 1.0 in price units; FX pairs ~ symbol-dependent.
    info = mt5.symbol_info(symbol)
    point = float(info.point) if info is not None and info.point else 0.01
    digits = int(info.digits) if info is not None else 2
    # sl_pts/tp_pts are in GOLD-POINTS (=1.0 price unit for XAU). For non-gold
    # symbols we convert gold-points→price the same way unified_trader does:
    # multiply by `pt` where pt is 1.0 for gold and the symbol point for FX.
    pt = 1.0 if "XAU" in symbol.upper() else point
    sl_px = sl_pts * pt
    tp_px = tp_pts * pt
    rt_cost_px = _round_trip_cost_pts(symbol) * pt

    # ── core features (computed on full series, used causally per bar) ──
    rsi = _rsi_wilder(close, 14)
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    adx = _adx_wilder(high, low, close, 14)

    hours = np.array([datetime.fromtimestamp(int(t), tz=timezone.utc).hour
                      for t in times], dtype=int)
    sessions = [_session_from_hour(h) for h in hours]

    # simple MTF bias: this-TF EMA20-vs-EMA50  +  one higher TF EMA20-vs-EMA50
    this_bias = np.where(ema20 > ema50, 1, np.where(ema20 < ema50, -1, 0))
    higher_tf_const = _tf_const(_higher_tf_str(timeframe_str))
    higher_bias = _higher_tf_bias_for_times(symbol, higher_tf_const, times, days)

    # ── 67% IS / 33% OOS split by TIME ──
    split_idx = int(n * 0.67)
    split_time = times[split_idx] if 0 < split_idx < n else (times[-1] if n else 0)

    # ── walk the bars, one position at a time ──
    warmup = 60  # let EMA50 / RSI14 / ADX14 settle
    pnls_all: list[float] = []          # per-trade price-PnL (in price units), net of cost
    trade_phase: list[str] = []         # "IS" / "OOS" per closed trade
    equity_px = 0.0
    equity_curve_all: list[float] = []  # cumulative net price-PnL after each closed trade
    equity_time_all: list[int] = []
    straddle_count = 0                   # bars that hit SL & TP in the same bar (ambiguous)

    i = warmup
    while i < n - 1:
        sess = sessions[i]
        # SESSION gate
        if session_filter and sess not in session_filter:
            i += 1
            continue

        # MTF bias / direction: count this-TF + higher-TF agreement.
        up = int(this_bias[i] > 0) + int(higher_bias[i] > 0)
        dn = int(this_bias[i] < 0) + int(higher_bias[i] < 0)
        if up >= 2:
            direction = "BUY"
        elif dn >= 2:
            direction = "SELL"
        else:
            i += 1
            continue

        # SIDE_BIAS gate
        if side_bias == "BUY_ONLY" and direction != "BUY":
            i += 1; continue
        if side_bias == "SELL_ONLY" and direction != "SELL":
            i += 1; continue

        # RSI gate (unified_trader rules; SELL uses rsi<=100-rsi_max)
        r = rsi[i]
        if direction == "BUY" and r >= rsi_max:
            i += 1; continue
        if direction == "SELL" and r <= rsi_min:
            i += 1; continue

        # TREND_ALIGN soft filter: skip entries that fight the higher-TF bias.
        # (Soft: only vetoes when higher TF has a *defined, opposing* bias.)
        if trend_align:
            if direction == "BUY" and higher_bias[i] < 0:
                i += 1; continue
            if direction == "SELL" and higher_bias[i] > 0:
                i += 1; continue

        # ── ENTER at next bar open, simulate forward to SL/TP ──
        entry_idx = i + 1
        if entry_idx >= n:
            break
        entry_px = open_[entry_idx]
        if direction == "BUY":
            sl_level = entry_px - sl_px
            tp_level = entry_px + tp_px
        else:
            sl_level = entry_px + sl_px
            tp_level = entry_px - tp_px

        exit_idx = None
        exit_pnl_px = None
        j = entry_idx
        while j < n:
            hi = high[j]; lo = low[j]
            op = open_[j]
            if direction == "BUY":
                hit_sl = lo <= sl_level
                hit_tp = hi >= tp_level
            else:
                hit_sl = hi >= sl_level
                hit_tp = lo <= tp_level
            if hit_sl and hit_tp:
                # Bar straddles BOTH levels — intrabar order is unknown at bar
                # granularity. We resolve by distance from the bar OPEN to each
                # level (whichever level price had to travel less to reach is
                # the more likely first touch). This is an APPROXIMATION and is
                # tracked via straddle_count for transparency: a high straddle
                # rate means SL/TP are tighter than typical bar range and the
                # verdict is correspondingly less reliable.
                straddle_count += 1
                d_sl = abs(op - sl_level)
                d_tp = abs(op - tp_level)
                if d_sl <= d_tp:
                    exit_pnl_px = -sl_px
                else:
                    exit_pnl_px = +tp_px
                exit_idx = j
                break
            if hit_sl:
                exit_pnl_px = -sl_px
                exit_idx = j
                break
            if hit_tp:
                exit_pnl_px = +tp_px
                exit_idx = j
                break
            j += 1

        if exit_idx is None:
            # Trade never closed within the window: close at last bar's close.
            last_px = close[n - 1]
            exit_pnl_px = (last_px - entry_px) if direction == "BUY" else (entry_px - last_px)
            exit_idx = n - 1

        # subtract round-trip cost
        net_px = exit_pnl_px - rt_cost_px
        pnls_all.append(net_px)
        equity_px += net_px
        equity_curve_all.append(equity_px)
        equity_time_all.append(int(times[entry_idx]))
        # phase by ENTRY time
        trade_phase.append("IS" if times[entry_idx] < split_time else "OOS")

        # one position at a time: resume scanning AFTER the exit bar
        i = max(exit_idx + 1, entry_idx + 1)

    # ───────────────────────── aggregate stats ─────────────────────────────
    pnls_is  = [p for p, ph in zip(pnls_all, trade_phase) if ph == "IS"]
    pnls_oos = [p for p, ph in zip(pnls_all, trade_phase) if ph == "OOS"]
    eq_is  = [e for e, ph in zip(equity_curve_all, trade_phase) if ph == "IS"]
    eq_oos = [e for e, ph in zip(equity_curve_all, trade_phase) if ph == "OOS"]

    trades = len(pnls_all)
    trades_is = len(pnls_is)
    trades_oos = len(pnls_oos)

    wins = sum(1 for p in pnls_all if p > 0)
    win_rate = (wins / trades * 100.0) if trades else 0.0

    pf_all = _profit_factor(pnls_all)
    pf_oos = _profit_factor(pnls_oos)

    # return_pct: net price-PnL relative to a notional risk base. We anchor to
    # the SL size (1R per losing trade) so % is comparable across symbols:
    # account base = max SL distance reached (proxy for deployed risk per R).
    base_px = sl_px if sl_px > 0 else (close[0] if n else 1.0)
    # cumulative equity expressed as multiples of 1R (one SL):
    equity_R = np.array([e / base_px for e in equity_curve_all], dtype=float) if equity_curve_all else np.array([])
    # account-style equity curve (start at 100 "R-units") for DD%:
    start_units = 100.0
    acct_curve = np.concatenate([[start_units], start_units + equity_R]) if equity_R.size else np.array([start_units])
    return_pct = float((equity_px / base_px)) * 1.0  # in R-multiples
    # express as percent-of-base for readability (each R = 1.0):
    return_pct = float(equity_px / base_px) * 100.0 / 1.0 if base_px else 0.0

    max_dd_pct = _max_dd_pct(acct_curve)

    linearity     = _r2_equity_vs_time(np.array(equity_curve_all))
    linearity_is  = _r2_equity_vs_time(np.array(eq_is))
    linearity_oos = _r2_equity_vs_time(np.array(eq_oos))

    accept = bool(trades_oos >= 60 and pf_oos > 1.1)

    return {
        # headline
        "return_pct": round(return_pct, 2),
        "profit_factor": round(pf_all, 4) if math.isfinite(pf_all) else pf_all,
        "trades": trades,
        "win_rate": round(win_rate, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        # linearity
        "linearity": round(linearity, 4),
        "linearity_is": round(linearity_is, 4),
        "linearity_oos": round(linearity_oos, 4),
        # split detail
        "trades_is": trades_is,
        "trades_oos": trades_oos,
        "profit_factor_is": round(_profit_factor(pnls_is), 4) if math.isfinite(_profit_factor(pnls_is)) else _profit_factor(pnls_is),
        "profit_factor_oos": round(pf_oos, 4) if math.isfinite(pf_oos) else pf_oos,
        # verdict
        "accept": accept,
        # provenance / honesty
        "symbol": symbol,
        "timeframe": str(timeframe_str).upper(),
        "days": days,
        "bars": n,
        "cost_source": _COST_SOURCE,
        "round_trip_cost_pts": round(rt_cost_px / pt, 5),
        "straddle_count": straddle_count,
        "straddle_rate": round(straddle_count / trades, 4) if trades else 0.0,
        "is_oos_split_time_utc": datetime.fromtimestamp(int(split_time), tz=timezone.utc).isoformat() if split_time else None,
        "approximation": ("Core indicators only (RSI14/EMA20/EMA50/ADX14/session/"
                          "simple-MTF). NOT footprint/structure/full-MTF/ML like the live brain."),
    }


# ─────────────────────────────── CLI ───────────────────────────────────────

_LIVE_GOLD_GENOME = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\live_genome__XAUUSDm.json")


def _infer_timeframe_from_name(genome: dict, default: str = "M5") -> str:
    name = ""
    if isinstance(genome, dict):
        name = str(genome.get("name") or (genome.get("params") or {}).get("name") or "")
    for tf in ("MN1", "W1", "D1", "H12", "H8", "H6", "H4", "H3", "H2", "H1",
               "M30", "M20", "M15", "M12", "M10", "M6", "M5", "M4", "M3", "M2", "M1"):
        if tf in name.upper().replace("-", " ").split() or name.upper().endswith(tf):
            return tf
    return default


def _main(argv: list[str]) -> int:
    days = 120
    genome_path = _LIVE_GOLD_GENOME
    # optional args: [genome_json_path] [days]
    if len(argv) >= 1 and argv[0]:
        genome_path = Path(argv[0])
    if len(argv) >= 2 and argv[1]:
        try:
            days = int(argv[1])
        except ValueError:
            pass

    if not genome_path.exists():
        print(f"[oos_backtest] genome file not found: {genome_path}")
        return 2

    genome = json.loads(genome_path.read_text(encoding="utf-8"))
    symbol = genome.get("symbol") or (genome.get("params") or {}).get("symbol") or "XAUUSDm"
    timeframe = _infer_timeframe_from_name(genome, default="M5")

    print("=" * 72)
    print("INDEPENDENT OOS BACKTEST (BRICK B2) — APPROXIMATION, core indicators only")
    print("  NOT footprint/structure/full-MTF/ML. Sanity check, not a profit promise.")
    print("=" * 72)
    print(f"Genome file : {genome_path}")
    print(f"Genome name : {genome.get('name')}")
    print(f"Symbol      : {symbol}")
    print(f"Timeframe   : {timeframe}")
    print(f"History     : last {days} days")
    print("-" * 72)

    try:
        stats = backtest_genome(symbol, timeframe, genome, days=days)
    except Exception as e:
        print(f"[oos_backtest] FAILED: {e}")
        return 1
    finally:
        try:
            if mt5 is not None:
                mt5.shutdown()
        except Exception:
            pass

    def _fmt(v):
        return f"{v}"

    print(f"Cost source        : {stats['cost_source']}  "
          f"(round-trip {stats['round_trip_cost_pts']} pts)")
    print(f"Bars pulled        : {stats['bars']}")
    if stats.get("straddle_rate", 0) > 0.25:
        print(f"!! WARNING: {stats['straddle_rate']*100:.0f}% of trades had SL & TP "
              f"inside the SAME bar — SL/TP are tighter than typical bar range.")
        print(f"   Bar-granularity simulation is UNRELIABLE for this genome; "
              f"intrabar order is guessed. Treat the verdict as low-confidence.")
    print(f"IS/OOS split (UTC) : {stats['is_oos_split_time_utc']}")
    print("-" * 72)
    print(f"Trades (total)     : {stats['trades']}   "
          f"IS={stats['trades_is']}  OOS={stats['trades_oos']}")
    print(f"Win rate           : {stats['win_rate']}%")
    print(f"Return (R-mult %)  : {stats['return_pct']}%")
    print(f"Profit factor      : ALL={_fmt(stats['profit_factor'])}  "
          f"IS={_fmt(stats['profit_factor_is'])}  OOS={_fmt(stats['profit_factor_oos'])}")
    print(f"Max drawdown       : {stats['max_dd_pct']}%")
    print(f"Linearity (R^2)    : ALL={stats['linearity']}  "
          f"IS={stats['linearity_is']}  OOS={stats['linearity_oos']}")
    print("-" * 72)
    verdict = "ACCEPT" if stats["accept"] else "REJECT"
    print(f"INDEPENDENT VERDICT: {verdict}   "
          f"(rule: trades_oos>=60 AND OOS profit_factor>1.1)")
    print(f"  → OOS trades = {stats['trades_oos']} (need >=60), "
          f"OOS PF = {_fmt(stats['profit_factor_oos'])} (need >1.1)")
    print("=" * 72)
    print("\nRAW STATS DICT:")
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
