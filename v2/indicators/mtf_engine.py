"""indicators/mtf_engine.py — single source of truth for MTF data.

Returns a SnapShot object with M1/M5/M15/H1/H4 bars + the indicators
the council needs. Cached 30s per (symbol, tf) tuple. Lazy MT5 import
so unit tests can mock.

CRITICAL difference from v1's snapshot path: this engine ALWAYS returns
ALL indicators for ALL TFs in one call. v1 fetched per-genome which led
to redundant MT5 calls (one per agent × per tick). v2 fetches once,
shares snapshot via dataclass.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Optional


_BARS_CACHE: dict = {}    # {(symbol, tf, n) → (ts, bars_list)}
_CACHE_TTL = 30           # 30s — M1 freshness matters


@dataclass
class TFFrame:
    tf:           str
    n_bars:       int
    last_close:   float
    rsi:          float
    atr:          float
    ema9:         float
    ema21:        float
    ema50:        float
    ema100:       Optional[float]
    swing_high:   float
    swing_low:    float
    range_size:   float
    slope_atr:    float    # last-bar TR / mean TR
    bias:         str      # "UP" / "DOWN" / "RANGE"
    last_bar:     dict     # {open, high, low, close, time}
    # Pattern signals (computed once, shared)
    bull_engulf:  bool     # last bar engulfs prior bear bar
    bear_engulf:  bool
    pin_top:      bool     # upper wick ≥ 2× body
    pin_bot:      bool


@dataclass
class Snapshot:
    symbol:    str
    bid:       float
    ask:       float
    spread:    float
    ts_utc:    str
    tfs:       dict          # {"M1": TFFrame, "M5": TFFrame, ...}
    notes:     list = field(default_factory=list)


def _get_bars(symbol: str, tf, n: int):
    key = (symbol, int(tf), n)
    cached = _BARS_CACHE.get(key)
    if cached and _time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, max(n, 30))
        if rates is None or len(rates) < 30:
            return None
        bars = [dict(b._asdict()) if hasattr(b, "_asdict")
                else {k: b[k] for k in b.dtype.names}
                for b in rates]
        _BARS_CACHE[key] = (_time.time(), bars)
        return bars
    except Exception:
        return None


def _rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    # Wilder smoothing
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0: return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 1)


def _atr(bars: list, period: int = 14) -> float:
    if len(bars) < period + 1: return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # Wilder ATR
    atr = sum(trs[:period]) / period
    for t in trs[period:]:
        atr = (atr * (period - 1) + t) / period
    return round(atr, 5)


def _ema(closes: list, period: int) -> float:
    if not closes: return 0.0
    k = 2 / (period + 1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 5)


def _bias_from_emas(ema9: float, ema21: float, ema50: float, slope: float) -> str:
    if ema9 > ema21 > ema50 and slope > 0.5: return "UP"
    if ema9 < ema21 < ema50 and slope < -0.5: return "DOWN"
    return "RANGE"


def _engulf(bars: list) -> tuple[bool, bool]:
    if len(bars) < 2: return False, False
    a, b = bars[-2], bars[-1]
    bull = (a["close"] < a["open"] and b["close"] > b["open"]
            and b["close"] > a["open"] and b["open"] < a["close"])
    bear = (a["close"] > a["open"] and b["close"] < b["open"]
            and b["close"] < a["open"] and b["open"] > a["close"])
    return bull, bear


def _pin(bar: dict) -> tuple[bool, bool]:
    body = abs(bar["close"] - bar["open"])
    if body == 0: return False, False
    upper = bar["high"] - max(bar["open"], bar["close"])
    lower = min(bar["open"], bar["close"]) - bar["low"]
    return (upper >= 2 * body, lower >= 2 * body)


def build_frame(symbol: str, tf, tf_label: str, n_bars: int = 100) -> Optional[TFFrame]:
    bars = _get_bars(symbol, tf, n_bars)
    if not bars: return None
    closes = [b["close"] for b in bars]
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]

    # Slope: last bar TR vs mean TR
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    cur_tr = trs[-1] if trs else 0
    mean_tr = sum(trs[-14:]) / max(1, len(trs[-14:])) if trs else 1
    slope_atr = round(cur_tr / mean_tr, 2) if mean_tr > 0 else 0

    ema9 = _ema(closes, 9); ema21 = _ema(closes, 21); ema50 = _ema(closes, 50)
    ema100 = _ema(closes, 100) if len(closes) >= 100 else None
    rsi = _rsi(closes, 14)
    atr = _atr(bars, 14)
    sh = max(highs[-30:]); sl = min(lows[-30:])
    bias = _bias_from_emas(ema9, ema21, ema50, slope_atr)
    bull, bear = _engulf(bars)
    pin_t, pin_b = _pin(bars[-1])

    return TFFrame(
        tf=tf_label, n_bars=len(bars),
        last_close=closes[-1], rsi=rsi, atr=atr,
        ema9=ema9, ema21=ema21, ema50=ema50, ema100=ema100,
        swing_high=sh, swing_low=sl, range_size=sh - sl,
        slope_atr=slope_atr, bias=bias,
        last_bar=bars[-1],
        bull_engulf=bull, bear_engulf=bear,
        pin_top=pin_t, pin_bot=pin_b,
    )


def build_snapshot(symbol: str) -> Optional[Snapshot]:
    """Build the full MTF snapshot the council consumes."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        tick = mt5.symbol_info_tick(symbol)
        if not tick: return None
        ts = mt5.symbol_info(symbol)
    except Exception:
        return None
    from datetime import datetime as _dt, timezone as _tz
    tfs = {}
    for label, tf, n in [("M1", mt5.TIMEFRAME_M1, 120),
                          ("M5", mt5.TIMEFRAME_M5, 100),
                          ("M15", mt5.TIMEFRAME_M15, 100),
                          ("H1", mt5.TIMEFRAME_H1, 100),
                          ("H4", mt5.TIMEFRAME_H4, 100)]:
        f = build_frame(symbol, tf, label, n)
        if f: tfs[label] = f
    return Snapshot(
        symbol=symbol, bid=tick.bid, ask=tick.ask,
        spread=(tick.ask - tick.bid),
        ts_utc=_dt.now(_tz.utc).isoformat(),
        tfs=tfs,
    )


if __name__ == "__main__":
    snap = build_snapshot("XAUUSDm")
    if snap:
        print(f"{snap.symbol} bid={snap.bid:.2f} ask={snap.ask:.2f} spread=${snap.spread:.2f}")
        for tf in ["M1","M5","M15","H1","H4"]:
            f = snap.tfs.get(tf)
            if f: print(f"  {tf}: bias={f.bias} RSI={f.rsi} ATR=${f.atr:.2f} "
                        f"slope={f.slope_atr} engulf=({f.bull_engulf},{f.bear_engulf})")
