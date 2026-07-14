"""extra_indicators.py — Precise computations for CCI/Stoch/Fib/Candle patterns.

The base genome_signal evaluators work from a coarse h1/m15/h4 dict (current,
atr, rsi, swing_high, swing_low, slope_atr). That's good enough for
breakout/RSI/BB-style logic but too coarse for:

  CCI            — needs typical-price mean deviation
  Stochastic     — needs %K and %D over a lookback
  Fib retracement— needs the actual swing high/low + price ratio
  3 Soldiers     — needs the last 3 candle open/close
  Wick Rejection — needs the last bar's wick-to-body ratio

This module fetches a small bar history per symbol (cached 60s) and exposes
six new evaluators that genome_signal.py registers into SIGNAL_EVALUATORS /
FILTER_EVALUATORS. They follow the same `(vote, reason)` / `(blocks, reason)`
contract used elsewhere.

The MT5 import is lazy so the module is still importable on machines without
MetaTrader 5 (returns 0/no-block with a "no mt5" reason).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional, Tuple

_BARS_CACHE: dict = {}  # (symbol, tf_const, n) → (ts, bars_list)
_CACHE_TTL = 60         # 1 min — these are all M5/H1 indicators


def _symbol(snap: dict) -> Optional[str]:
    s = (snap.get("symbol") or "").strip()
    return s or None


def _bid(snap: dict) -> float:
    return float(snap.get("bid") or (snap.get("h1") or {}).get("current") or 0)


def _get_bars(symbol: str, tf, n: int) -> Optional[list]:
    """Cached MT5 bar fetch."""
    key = (symbol, int(tf), n)
    cached = _BARS_CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): return None
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, max(n, 3))
        if bars is None or len(bars) < min(n, 3): return None
        bars_list = [dict(b._asdict()) if hasattr(b, "_asdict")
                     else {k: b[k] for k in b.dtype.names}
                     for b in bars]
        _BARS_CACHE[key] = (time.time(), bars_list)
        return bars_list
    except Exception:
        return None


# ────────── SIGNALS ──────────

def sig_cci(snap: dict) -> Tuple[int, str]:
    """CCI(20) on H1. Classic thresholds:
        ≤ -100 → +1 (oversold, expect bounce up)
        ≥ +100 → -1 (overbought, expect fade down)
    """
    sym = _symbol(snap)
    if not sym: return 0, "no symbol"
    try:
        import MetaTrader5 as mt5
        bars = _get_bars(sym, mt5.TIMEFRAME_H1, 25)
        if not bars: return 0, "no bars"
        tp = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars[-20:]]
        sma = sum(tp) / len(tp)
        mad = sum(abs(p - sma) for p in tp) / len(tp)
        if mad == 0: return 0, "flat tp"
        cci = (tp[-1] - sma) / (0.015 * mad)
        cci = round(cci, 1)
        if cci <= -100: return +1, f"cci={cci} oversold"
        if cci >= +100: return -1, f"cci={cci} overbought"
        return 0, f"cci={cci} neutral"
    except Exception as e:
        return 0, f"cci err {type(e).__name__}"


def sig_stoch(snap: dict) -> Tuple[int, str]:
    """Stochastic %K(14)/%D(3) on H1.
        %K < 20 and %K crossing above %D → +1
        %K > 80 and %K crossing below %D → -1
    """
    sym = _symbol(snap)
    if not sym: return 0, "no symbol"
    try:
        import MetaTrader5 as mt5
        bars = _get_bars(sym, mt5.TIMEFRAME_H1, 20)
        if not bars or len(bars) < 17: return 0, "no bars"

        ks = []
        for i in range(len(bars) - 14, len(bars)):
            window = bars[i - 13:i + 1] if i >= 13 else bars[: i + 1]
            hh = max(b["high"] for b in window)
            ll = min(b["low"]  for b in window)
            close = bars[i]["close"]
            ks.append(0.0 if hh == ll else (close - ll) / (hh - ll) * 100)

        k_now = ks[-1]
        k_prev = ks[-2] if len(ks) > 1 else k_now
        # %D is 3-period SMA of %K
        d_now  = sum(ks[-3:]) / min(3, len(ks))
        d_prev = sum(ks[-4:-1]) / 3 if len(ks) >= 4 else d_now

        k_now, d_now = round(k_now, 1), round(d_now, 1)
        cross_up   = k_prev <= d_prev and k_now > d_now
        cross_down = k_prev >= d_prev and k_now < d_now
        if k_now < 20 and cross_up:
            return +1, f"stoch %K={k_now} cross↑ %D={d_now} oversold"
        if k_now > 80 and cross_down:
            return -1, f"stoch %K={k_now} cross↓ %D={d_now} overbought"
        return 0, f"stoch %K={k_now} %D={d_now} no cross"
    except Exception as e:
        return 0, f"stoch err {type(e).__name__}"


def sig_fib(snap: dict) -> Tuple[int, str]:
    """Fibonacci retracement on the H4 swing.
        Price at 0.382-0.5 of an UP swing → +1 (buy retrace)
        Price at 0.5-0.618 of a DOWN swing → -1 (sell retrace)
        50/61.8 zones are highest-probability bounce levels.
    """
    h4 = snap.get("h4") or {}
    sh = h4.get("swing_high"); sl = h4.get("swing_low")
    bid = _bid(snap); bias = h4.get("bias", "RANGE")
    if not (sh and sl and bid) or sh == sl: return 0, "no h4 swing"
    rng = sh - sl
    if bias == "UP":
        # Retracement from swing_high back into the range
        retrace = (sh - bid) / rng     # 0 at high, 1 at low
        if 0.382 <= retrace <= 0.50:
            return +1, f"fib 0.5 retrace in UP ({retrace:.2f})"
        if 0.50 < retrace <= 0.618:
            return +1, f"fib 0.618 retrace in UP ({retrace:.2f})"
        return 0, f"retrace={retrace:.2f} not at fib"
    if bias == "DOWN":
        retrace = (bid - sl) / rng     # 0 at low, 1 at high
        if 0.382 <= retrace <= 0.50:
            return -1, f"fib 0.5 retrace in DOWN ({retrace:.2f})"
        if 0.50 < retrace <= 0.618:
            return -1, f"fib 0.618 retrace in DOWN ({retrace:.2f})"
        return 0, f"retrace={retrace:.2f} not at fib"
    return 0, "h4 range"


def sig_three_soldiers(snap: dict) -> Tuple[int, str]:
    """3 White Soldiers (3 consecutive bullish bars with rising closes, each
    opening within prior body) → +1. Mirror (3 Black Crows) → -1.
    Computed on M15."""
    sym = _symbol(snap)
    if not sym: return 0, "no symbol"
    try:
        import MetaTrader5 as mt5
        bars = _get_bars(sym, mt5.TIMEFRAME_M15, 6)
        if not bars or len(bars) < 3: return 0, "no bars"
        a, b, c = bars[-3], bars[-2], bars[-1]
        bull = lambda x: x["close"] > x["open"]
        bear = lambda x: x["close"] < x["open"]
        # Body sizes (min 30% of range to count as "real" body)
        body = lambda x: abs(x["close"] - x["open"])
        rng  = lambda x: max(x["high"] - x["low"], 1e-9)
        real = lambda x: body(x) / rng(x) >= 0.30

        if (bull(a) and bull(b) and bull(c)
                and real(a) and real(b) and real(c)
                and c["close"] > b["close"] > a["close"]
                and a["close"] < b["open"] < a["high"]
                and b["close"] < c["open"] < b["high"]):
            return +1, "3 white soldiers M15"
        if (bear(a) and bear(b) and bear(c)
                and real(a) and real(b) and real(c)
                and c["close"] < b["close"] < a["close"]
                and a["high"] > b["open"] > a["close"]
                and b["high"] > c["open"] > b["close"]):
            return -1, "3 black crows M15"
        return 0, "no 3-soldier pattern"
    except Exception as e:
        return 0, f"3sold err {type(e).__name__}"


def sig_wick_rejection(snap: dict) -> Tuple[int, str]:
    """Last M15 bar with wick ≥ 2× body in one direction → reversal signal.
    Upper wick rejection at swing_high → -1 (rejection from high)
    Lower wick rejection at swing_low  → +1 (rejection from low)
    """
    sym = _symbol(snap)
    if not sym: return 0, "no symbol"
    try:
        import MetaTrader5 as mt5
        bars = _get_bars(sym, mt5.TIMEFRAME_M15, 3)
        if not bars: return 0, "no bars"
        last = bars[-1]
        o, c, h, l = last["open"], last["close"], last["high"], last["low"]
        body = abs(c - o)
        if body == 0: return 0, "doji last bar"
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        h1 = snap.get("h1") or {}
        sh = h1.get("swing_high"); sl = h1.get("swing_low")

        if upper_wick >= 2 * body and sh and h >= sh - (sh * 0.001):
            return -1, (f"upper wick {upper_wick/body:.1f}x body "
                        f"at swing_high {sh}")
        if lower_wick >= 2 * body and sl and l <= sl + (sl * 0.001):
            return +1, (f"lower wick {lower_wick/body:.1f}x body "
                        f"at swing_low {sl}")
        return 0, "no wick rejection at level"
    except Exception as e:
        return 0, f"wick err {type(e).__name__}"


# ────────── FILTERS ──────────

def filt_no_fri_open(snap: dict) -> Tuple[bool, str]:
    """Block opening new trades on Friday after 18:00 UTC — too close to
    weekend gap risk. Friday morning trades are still allowed."""
    now = datetime.now(timezone.utc)
    if now.weekday() == 4 and now.hour >= 18:
        return True, f"friday {now:%H:%M} UTC — block (gap risk)"
    if now.weekday() == 5 or now.weekday() == 6:
        return True, f"{['mon','tue','wed','thu','fri','sat','sun'][now.weekday()]} — weekend"
    return False, f"{now:%a %H:%M} UTC OK"
