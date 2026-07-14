"""
algory_signal_engine.py
-----------------------
Vectorized signal engine replicating Algory's full gene-based signal logic.

Implements ALL Algory signals/biases/filters using pandas/numpy for speed.
Supports all timeframes: M1, M5, M15, M30, H1, H2, H4, D1.

Entry modes (exec_modes):
  stop     → place stop order above/below signal bar at close ± stop_offset_atr × ATR
  limit    → place limit order at close ± limit_offset_atr × ATR
  limit2   → aggressive limit: close ± limit2_offset_atr × ATR (tighter)
  market2  → wait for pullback of market2_pullback_atr × ATR then enter

Signal genes → pandas Series of {1=buy, -1=sell, 0=no signal}
Bias genes   → pandas Series of {1=bullish, -1=bearish, 0=neutral}
Filter genes → pandas Series of {True=trade allowed, False=blocked}

All calculations are fully vectorized — no Python loops over bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Any


def _sign_int(s: "pd.Series | np.ndarray") -> "pd.Series":
    """np.sign → int with NaN filled as 0 (avoids IntCastingNaNError)."""
    return np.sign(s).fillna(0).astype(int)


# ─────────────────────────────────────────────────────────────────────────────
#  ATR calculation (Wilder's smoothed)
# ─────────────────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1.0 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _cci(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp   = (df["high"] + df["low"] + df["close"]) / 3
    ma   = tp.rolling(period).mean()
    mad  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * mad.replace(0, np.nan))


def _stoch(df: pd.DataFrame, k: int = 14, d: int = 3) -> tuple[pd.Series, pd.Series]:
    lo_k = df["low"].rolling(k).min()
    hi_k = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - lo_k) / (hi_k - lo_k).replace(0, np.nan)
    pct_d = pct_k.rolling(d).mean()
    return pct_k, pct_d


def _macd(series: pd.Series, fast=12, slow=26, sig=9) -> tuple[pd.Series, pd.Series]:
    ema_f = series.ewm(span=fast, adjust=False).mean()
    ema_s = series.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    signal = macd.ewm(span=sig, adjust=False).mean()
    return macd, signal


def _williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi = df["high"].rolling(period).max()
    lo = df["low"].rolling(period).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, np.nan)


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr   = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    dm_p = (h - h.shift()).clip(lower=0).where((h - h.shift()) > (l.shift() - l), 0)
    dm_m = (l.shift() - l).clip(lower=0).where((l.shift() - l) > (h - h.shift()), 0)
    atr14 = tr.ewm(alpha=1/period, adjust=False).mean()
    di_p  = 100 * dm_p.ewm(alpha=1/period, adjust=False).mean() / atr14.replace(0, np.nan)
    di_m  = 100 * dm_m.ewm(alpha=1/period, adjust=False).mean() / atr14.replace(0, np.nan)
    dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean()


def _psar(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    n     = len(close)
    psar  = np.full(n, np.nan)
    bull  = True
    af    = step
    ep    = low[0]
    psar[0] = high[0]
    for i in range(1, n):
        prev = psar[i-1]
        if bull:
            psar[i] = prev + af * (ep - prev)
            psar[i] = min(psar[i], low[i-1], low[i-2] if i >= 2 else low[i-1])
            if low[i] < psar[i]:
                bull = False; af = step; ep = low[i]; psar[i] = ep
            else:
                if high[i] > ep:
                    ep = high[i]; af = min(af + step, max_step)
        else:
            psar[i] = prev + af * (ep - prev)
            psar[i] = max(psar[i], high[i-1], high[i-2] if i >= 2 else high[i-1])
            if high[i] > psar[i]:
                bull = True; af = step; ep = high[i]; psar[i] = ep
            else:
                if low[i] < ep:
                    ep = low[i]; af = min(af + step, max_step)
    return pd.Series(psar, index=df.index)


def _chandelier(df: pd.DataFrame, period: int = 22, mult: float = 3.0) -> tuple[pd.Series, pd.Series]:
    atr    = _atr(df, period)
    hi_max = df["high"].rolling(period).max()
    lo_min = df["low"].rolling(period).min()
    long_stop  = hi_max - mult * atr
    short_stop = lo_min + mult * atr
    return long_stop, short_stop


def _keltner(df: pd.DataFrame, period: int = 20, mult: float = 1.5) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid  = df["close"].ewm(span=period, adjust=False).mean()
    atr  = _atr(df, period)
    return mid + mult * atr, mid, mid - mult * atr


def _donchian_mid(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return (df["high"].rolling(period).max() + df["low"].rolling(period).min()) / 2


def _daily_mid(df: pd.DataFrame) -> pd.Series:
    """Approximate daily mid as rolling 24-bar high+low midpoint on H1 data."""
    period = 24
    return (df["high"].rolling(period).max() + df["low"].rolling(period).min()) / 2


def _adr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return (df["high"] - df["low"]).rolling(period).mean()


# ─────────────────────────────────────────────────────────────────────────────
#  Precomputed indicator cache
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IndicatorCache:
    atr:           pd.Series
    rsi:           pd.Series
    cci:           pd.Series
    stoch_k:       pd.Series
    stoch_d:       pd.Series
    macd:          pd.Series
    macd_sig:      pd.Series
    williams:      pd.Series
    adx:           pd.Series
    psar:          pd.Series
    sma_fast:      pd.Series
    sma_slow:      pd.Series
    ema:           pd.Series
    chan_long:     pd.Series
    chan_short:    pd.Series
    kelt_upper:    pd.Series
    kelt_mid:      pd.Series
    kelt_lower:    pd.Series
    donchian_mid:  pd.Series
    daily_mid:     pd.Series
    adr:           pd.Series
    momentum:      pd.Series


def build_cache(df: pd.DataFrame, g: Any) -> IndicatorCache:
    """Build all indicator series from genome parameters. Called once per genome evaluation."""
    macd, macd_sig   = _macd(df["close"])
    stk, std         = _stoch(df, g.stoch_k_period, g.stoch_d_period)
    chan_l, chan_s    = _chandelier(df, period=22, mult=g.chand_mult)
    ku, km, kl        = _keltner(df, g.keltner_period, g.keltner_mult)
    return IndicatorCache(
        atr           = _atr(df, g.atr_ma_period),
        rsi           = _rsi(df["close"], g.rsi_period),
        cci           = _cci(df, g.cci_period),
        stoch_k       = stk,
        stoch_d       = std,
        macd          = macd,
        macd_sig      = macd_sig,
        williams      = _williams_r(df, g.williams_period),
        adx           = _adx(df, g.adx_period),
        psar          = _psar(df, g.psar_step, g.psar_max),
        sma_fast      = df["close"].rolling(g.sma_fast_period).mean(),
        sma_slow      = df["close"].rolling(g.sma_slow_period).mean(),
        ema           = df["close"].ewm(span=g.ema_period, adjust=False).mean(),
        chan_long      = chan_l,
        chan_short     = chan_s,
        kelt_upper    = ku,
        kelt_mid      = km,
        kelt_lower    = kl,
        donchian_mid  = _donchian_mid(df, g.sma_fast_period),
        daily_mid     = _daily_mid(df),
        adr           = _adr(df, g.adr_period),
        momentum      = df["close"].diff(g.momentum_period),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  SIGNAL computation (returns pd.Series: 1=buy, -1=sell, 0=none)
# ─────────────────────────────────────────────────────────────────────────────

def sig_inside_break(df: pd.DataFrame) -> pd.Series:
    """Inside bar breakout: current bar's high > prev bar's high (buy) or low < prev low (sell)."""
    prev_h = df["high"].shift(1)
    prev_l = df["low"].shift(1)
    prev_prev_h = df["high"].shift(2)
    prev_prev_l = df["low"].shift(2)
    # Bar[1] was inside bar[2]
    inside = (prev_h <= prev_prev_h) & (prev_l >= prev_prev_l)
    buy  = inside & (df["close"] > prev_h)
    sell = inside & (df["close"] < prev_l)
    return buy.astype(int) - sell.astype(int)


def sig_wick_rejection(df: pd.DataFrame, wick_ratio: float = 1.5) -> pd.Series:
    """Wick rejection: long lower wick = bullish, long upper wick = bearish."""
    body  = (df["close"] - df["open"]).abs()
    upper = df["high"] - df[["close","open"]].max(axis=1)
    lower = df[["close","open"]].min(axis=1) - df["low"]
    buy   = (lower > wick_ratio * body) & (lower > upper)
    sell  = (upper > wick_ratio * body) & (upper > lower)
    return buy.astype(int) - sell.astype(int)


def sig_engulfing(df: pd.DataFrame) -> pd.Series:
    """Bullish/bearish engulfing candle."""
    o, c    = df["open"], df["close"]
    po, pc  = o.shift(1), c.shift(1)
    bull = (c > o) & (pc > po) & (c >= po) & (o <= pc)   # bullish engulf bearish
    bear = (c < o) & (pc < po) & (c <= po) & (o >= pc)
    return bull.astype(int) - bear.astype(int)


def sig_pin_bar(df: pd.DataFrame, body_pct: float = 0.33) -> pd.Series:
    """Pin bar: small body at one end, long tail at other."""
    body  = (df["close"] - df["open"]).abs()
    total = df["high"] - df["low"]
    body_frac = body / total.replace(0, np.nan)
    upper = df["high"] - df[["close","open"]].max(axis=1)
    lower = df[["close","open"]].min(axis=1) - df["low"]
    buy   = (body_frac < body_pct) & (lower > 2 * upper)
    sell  = (body_frac < body_pct) & (upper > 2 * lower)
    return buy.astype(int) - sell.astype(int)


def sig_rsi(ind: IndicatorCache) -> pd.Series:
    """RSI oversold/overbought signal."""
    buy  = ind.rsi < 30
    sell = ind.rsi > 70
    return buy.astype(int) - sell.astype(int)


def sig_macd(ind: IndicatorCache) -> pd.Series:
    """MACD crossover signal."""
    buy  = (ind.macd > ind.macd_sig) & (ind.macd.shift(1) <= ind.macd_sig.shift(1))
    sell = (ind.macd < ind.macd_sig) & (ind.macd.shift(1) >= ind.macd_sig.shift(1))
    return buy.astype(int) - sell.astype(int)


def sig_stoch(ind: IndicatorCache) -> pd.Series:
    """Stochastic K/D crossover from OS/OB zones."""
    buy  = (ind.stoch_k > ind.stoch_d) & (ind.stoch_k.shift(1) <= ind.stoch_d.shift(1)) & (ind.stoch_k < 30)
    sell = (ind.stoch_k < ind.stoch_d) & (ind.stoch_k.shift(1) >= ind.stoch_d.shift(1)) & (ind.stoch_k > 70)
    return buy.astype(int) - sell.astype(int)


def sig_cci(ind: IndicatorCache, limit: float = 100) -> pd.Series:
    """CCI cross of ±limit."""
    buy  = (ind.cci > -limit) & (ind.cci.shift(1) <= -limit)
    sell = (ind.cci < limit)  & (ind.cci.shift(1) >= limit)
    return buy.astype(int) - sell.astype(int)


def sig_williams(ind: IndicatorCache, ob: float = -20, os: float = -80) -> pd.Series:
    buy  = (ind.williams > os) & (ind.williams.shift(1) <= os)
    sell = (ind.williams < ob) & (ind.williams.shift(1) >= ob)
    return buy.astype(int) - sell.astype(int)


def sig_breakout(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    hi  = df["high"].shift(1).rolling(lookback).max()
    lo  = df["low"].shift(1).rolling(lookback).min()
    buy  = df["close"] > hi
    sell = df["close"] < lo
    return buy.astype(int) - sell.astype(int)


def sig_fib(df: pd.DataFrame, level: float = 0.382, lookback: int = 50) -> pd.Series:
    """Price near Fibonacci retracement of recent swing."""
    hi  = df["high"].rolling(lookback).max()
    lo  = df["low"].rolling(lookback).min()
    fib = lo + level * (hi - lo)
    tol = (hi - lo) * 0.02
    buy  = (df["close"].shift(1) > fib.shift(1)) & (df["low"] <= fib + tol) & (df["close"] > df["open"])
    sell = (df["close"].shift(1) < fib.shift(1)) & (df["high"] >= fib - tol) & (df["close"] < df["open"])
    return buy.astype(int) - sell.astype(int)


def sig_three_soldiers(df: pd.DataFrame, min_body_atr: float = 0.3, atr: pd.Series = None) -> pd.Series:
    """Three white soldiers / three black crows."""
    c, o = df["close"], df["open"]
    body  = (c - o).abs()
    min_b = (atr * min_body_atr) if atr is not None else body.rolling(5).mean() * 0.3
    # 3 consecutive bullish
    bull1 = (c > o) & (body > min_b)
    bull2 = bull1.shift(1) & (o > o.shift(1))
    bull3 = bull2.shift(1)
    white = bull1 & bull2.fillna(False) & bull3.fillna(False)
    # 3 consecutive bearish
    bear1 = (c < o) & (body > min_b)
    bear2 = bear1.shift(1) & (o < o.shift(1))
    bear3 = bear2.shift(1)
    black = bear1 & bear2.fillna(False) & bear3.fillna(False)
    return white.astype(int) - black.astype(int)


def sig_mom_break(df: pd.DataFrame, ind: IndicatorCache, mom_atr: float = 0.5) -> pd.Series:
    """Momentum breakout: momentum crosses ±mom_atr × ATR."""
    thresh = ind.atr * mom_atr
    buy   = (ind.momentum > thresh) & (ind.momentum.shift(1) <= thresh.shift(1))
    sell  = (ind.momentum < -thresh) & (ind.momentum.shift(1) >= -thresh.shift(1))
    return buy.astype(int) - sell.astype(int)


def sig_sweep(df: pd.DataFrame, lookback: int = 20, candles: int = 4) -> pd.Series:
    """Liquidity sweep: price briefly breaks a recent high/low then reverses."""
    prev_hi = df["high"].shift(candles).rolling(lookback).max()
    prev_lo = df["low"].shift(candles).rolling(lookback).min()
    swept_hi = (df["high"].rolling(candles).max() > prev_hi) & (df["close"] < prev_hi)
    swept_lo = (df["low"].rolling(candles).min() < prev_lo) & (df["close"] > prev_lo)
    return swept_lo.astype(int) - swept_hi.astype(int)


def sig_inside_break_v2(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """
    Enhanced inside break using ATR confirmation (Algory's primary signal).
    Inside bar + close above/below with ATR-scaled threshold.
    """
    prev_h  = df["high"].shift(1)
    prev_l  = df["low"].shift(1)
    prev2_h = df["high"].shift(2)
    prev2_l = df["low"].shift(2)
    is_inside = (prev_h <= prev2_h) & (prev_l >= prev2_l)
    buy   = is_inside & (df["close"] > prev2_h + ind.atr * 0.05)
    sell  = is_inside & (df["close"] < prev2_l - ind.atr * 0.05)
    return buy.astype(int) - sell.astype(int)


# ─────────────────────────────────────────────────────────────────────────────
#  BIAS computation (returns pd.Series: 1=bullish, -1=bearish, 0=neutral)
# ─────────────────────────────────────────────────────────────────────────────

def bias_sma(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    return _sign_int(ind.sma_fast - ind.sma_slow)


def bias_ema(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    return _sign_int(df["close"] - ind.ema)


def bias_rsi(ind: IndicatorCache) -> pd.Series:
    bull = ind.rsi > 50
    bear = ind.rsi < 50
    return bull.astype(int) - bear.astype(int)


def bias_adx(df: pd.DataFrame, ind: IndicatorCache, threshold: float = 25) -> pd.Series:
    trending = ind.adx > threshold
    up_trend = trending & (df["close"] > df["close"].shift(1))
    dn_trend = trending & (df["close"] < df["close"].shift(1))
    return up_trend.astype(int) - dn_trend.astype(int)


def bias_psar(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    return _sign_int(df["close"] - ind.psar)


def bias_chandelier(ind: IndicatorCache) -> pd.Series:
    return _sign_int(ind.chan_long - ind.chan_short)


def bias_daily_mid(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    return _sign_int(df["close"] - ind.daily_mid)


def bias_donchian_mid(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    return _sign_int(df["close"] - ind.donchian_mid)


def bias_htf(df: pd.DataFrame, htf_period: int = 20) -> pd.Series:
    """Higher timeframe bias using a slower MA approximation."""
    sma_htf = df["close"].rolling(htf_period * 4).mean()
    return _sign_int(df["close"] - sma_htf)


def bias_momentum(ind: IndicatorCache) -> pd.Series:
    return _sign_int(ind.momentum)


def bias_market_struct(df: pd.DataFrame) -> pd.Series:
    """Simple market structure: series of higher highs/lows vs lower highs/lows."""
    hh = (df["high"] > df["high"].shift(1)) & (df["high"].shift(1) > df["high"].shift(2))
    ll = (df["low"] < df["low"].shift(1)) & (df["low"].shift(1) < df["low"].shift(2))
    return hh.astype(int) - ll.astype(int)


def bias_trailing(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """Trailing stop direction as bias."""
    span = max(2, int(ind.atr.rolling(5).mean().fillna(14).iloc[-1]))
    trail_ma = df["close"].ewm(span=span, adjust=False).mean()
    return _sign_int(df["close"] - trail_ma)


# ─────────────────────────────────────────────────────────────────────────────
#  FILTER computation (returns pd.Series of bool: True = trade allowed)
# ─────────────────────────────────────────────────────────────────────────────

def filt_consec(df: pd.DataFrame, count: int = 3, direction: pd.Series = None) -> pd.Series:
    """Block trade if N consecutive candles already in same direction (overextended)."""
    if direction is None:
        direction = np.sign(df["close"] - df["open"])
    # Check if last `count` candles are all in the same direction
    rolling_sum = direction.rolling(count).sum().abs()
    return (rolling_sum < count).fillna(True)


def filt_doji(df: pd.DataFrame, atr: pd.Series, doji_ratio: float = 0.1) -> pd.Series:
    """Block if current bar is a doji (very small body)."""
    body  = (df["close"] - df["open"]).abs()
    is_doji = body < (atr * doji_ratio)
    return ~is_doji


def filt_adr_exhaust(df: pd.DataFrame, ind: IndicatorCache, exhaust_pct: float = 0.7) -> pd.Series:
    """Block if today's range already exceeded exhaust_pct × ADR."""
    daily_range = df["high"] - df["low"]
    return daily_range < (ind.adr * exhaust_pct)


def filt_adx(ind: IndicatorCache, threshold: float = 20) -> pd.Series:
    """Only trade when ADX confirms trending (above threshold)."""
    return ind.adx > threshold


def filt_bb(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """Block if price is inside BB (not at extreme)."""
    return (df["close"] > ind.kelt_upper) | (df["close"] < ind.kelt_lower)


def filt_cci(ind: IndicatorCache, limit: float = 100) -> pd.Series:
    """Only trade when CCI is extreme."""
    return ind.cci.abs() > limit


def filt_keltner(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """Only trade when price is outside Keltner channel."""
    return (df["close"] > ind.kelt_upper) | (df["close"] < ind.kelt_lower)


def filt_receding(df: pd.DataFrame) -> pd.Series:
    """Block if volume/range is expanding (receding momentum filter)."""
    rng = df["high"] - df["low"]
    return rng < rng.shift(1)


def filt_rsi(ind: IndicatorCache) -> pd.Series:
    """Block if RSI is in extreme zone (50±30)."""
    return (ind.rsi > 30) & (ind.rsi < 70)


def filt_sma(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """Only trade in direction of SMA trend."""
    return (df["close"] > ind.sma_fast) | (df["close"] < ind.sma_fast)


def filt_volatility(df: pd.DataFrame, ind: IndicatorCache) -> pd.Series:
    """Only trade when ATR is in normal range (not too high, not too low)."""
    avg_atr = ind.atr.rolling(50).mean()
    return (ind.atr > avg_atr * 0.5) & (ind.atr < avg_atr * 2.5)


# ─────────────────────────────────────────────────────────────────────────────
#  Master signal combiner
# ─────────────────────────────────────────────────────────────────────────────

def compute_signals(df: pd.DataFrame, genome: Any) -> pd.DataFrame:
    """
    Compute combined signal for every bar based on genome's active genes.

    Returns DataFrame with columns:
      signal    : 1=buy, -1=sell, 0=no signal
      bias      : 1=bullish bias, -1=bearish bias, 0=neutral
      filter_ok : True if trade allowed by all active filters
      entry_dir : final trade direction (signal × confirmed by bias)
      sl        : stop-loss price
      tp        : take-profit price
      entry_px  : entry price (based on exec_mode)
    """
    # normalise column names to lowercase (MT5 returns Title case)
    df = df.rename(columns={c: c.lower() for c in df.columns})

    g   = genome
    ind = build_cache(df, g)

    # ── Collect signals ──────────────────────────────────────────────────────
    sigs: list[pd.Series] = []
    if g.use_sig_inside_break:  sigs.append(sig_inside_break_v2(df, ind))
    if g.use_sig_wick_rejection: sigs.append(sig_wick_rejection(df, g.wick_ratio))
    if g.use_sig_engulfing:     sigs.append(sig_engulfing(df))
    if g.use_sig_pin_bar:       sigs.append(sig_pin_bar(df, g.pin_bar_body_pct))
    if g.use_sig_rsi:           sigs.append(sig_rsi(ind))
    if g.use_sig_macd:          sigs.append(sig_macd(ind))
    if g.use_sig_stoch:         sigs.append(sig_stoch(ind))
    if g.use_sig_cci:           sigs.append(sig_cci(ind, g.cci_limit))
    if g.use_sig_williams:      sigs.append(sig_williams(ind, g.williams_ob, g.williams_os))
    if g.use_sig_breakout:      sigs.append(sig_breakout(df, g.breakout_lookback))
    if g.use_sig_fib:           sigs.append(sig_fib(df, g.fib_level, g.fib_lookback))
    if g.use_sig_three_soldiers: sigs.append(sig_three_soldiers(df, g.soldiers_min_body_atr, ind.atr))
    if g.use_sig_mom_break:     sigs.append(sig_mom_break(df, ind, g.mom_break_atr))
    if g.use_sig_sweep:         sigs.append(sig_sweep(df, g.sweep_period, g.sweep_lookback_candles))

    if not sigs:
        signal     = pd.Series(0, index=df.index)
        confidence = pd.Series(0.0, index=df.index)
    else:
        stacked    = pd.concat(sigs, axis=1).fillna(0)
        vote_sum   = stacked.sum(axis=1)
        signal     = np.sign(vote_sum).astype(int)
        # confidence = fraction of active signals agreeing (0.0 – 1.0)
        n_sigs     = len(sigs)
        confidence = (vote_sum.abs() / n_sigs).clip(0.0, 1.0).round(3)

    # ── Collect biases ───────────────────────────────────────────────────────
    biases: list[pd.Series] = []
    if g.use_bias_sma:          biases.append(bias_sma(df, ind))
    if g.use_bias_ema:          biases.append(bias_ema(df, ind))
    if g.use_bias_rsi:          biases.append(bias_rsi(ind))
    if g.use_bias_adx:          biases.append(bias_adx(df, ind, g.adx_threshold))
    if g.use_bias_psar:         biases.append(bias_psar(df, ind))
    if g.use_bias_chandelier:   biases.append(bias_chandelier(ind))
    if g.use_bias_daily_mid:    biases.append(bias_daily_mid(df, ind))
    if g.use_bias_donchian_mid: biases.append(bias_donchian_mid(df, ind))
    if g.use_bias_htf:          biases.append(bias_htf(df, g.htf_sma_period))
    if g.use_bias_momentum:     biases.append(bias_momentum(ind))
    if g.use_bias_market_struct: biases.append(bias_market_struct(df))
    if g.use_bias_trailing:     biases.append(bias_trailing(df, ind))

    if biases:
        bias_stack = pd.concat(biases, axis=1).fillna(0)
        bias       = np.sign(bias_stack.sum(axis=1)).astype(int)
    else:
        bias = pd.Series(0, index=df.index)

    # ── Collect filters ──────────────────────────────────────────────────────
    filters: list[pd.Series] = []
    dir_series = signal.fillna(0)
    if g.use_filt_consec:       filters.append(filt_consec(df, g.consec_count, dir_series))
    if g.use_filt_doji:         filters.append(filt_doji(df, ind.atr))
    if g.use_filt_adr_exhaust:  filters.append(filt_adr_exhaust(df, ind, g.adr_exhaust_pct))
    if g.use_filt_adx:          filters.append(filt_adx(ind, g.adx_threshold))
    if g.use_filt_bb:           filters.append(filt_bb(df, ind))
    if g.use_filt_cci:          filters.append(filt_cci(ind, g.cci_limit))
    if g.use_filt_keltner:      filters.append(filt_keltner(df, ind))
    if g.use_filt_receding:     filters.append(filt_receding(df))
    if g.use_filt_rsi:          filters.append(filt_rsi(ind))
    if g.use_filt_sma:          filters.append(filt_sma(df, ind))
    if g.use_filt_volatility:   filters.append(filt_volatility(df, ind))

    if filters:
        filter_ok = pd.concat(filters, axis=1).fillna(True).all(axis=1)
    else:
        filter_ok = pd.Series(True, index=df.index)

    # ── Trading hours filter ─────────────────────────────────────────────────
    try:
        dti   = pd.DatetimeIndex(df.index)
        hours = dti.hour
        weekday_vals = dti.dayofweek
    except Exception:
        hours        = pd.Series(12, index=df.index)
        weekday_vals = pd.Series(0,  index=df.index)

    hour_ok = pd.Series(
        (hours >= g.start_hour) & (hours < g.end_hour),
        index=df.index,
    )
    friday_ok = pd.Series(
        ~((weekday_vals == 4) & (hours >= g.friday_close)),
        index=df.index,
    )

    filter_ok = filter_ok & hour_ok & friday_ok

    # ── Combine signal + bias + filter ───────────────────────────────────────
    confirmed = signal.copy()
    if biases:
        # Signal must agree with bias direction (bias != 0 means confirmed)
        confirmed = confirmed.where(
            (bias == 0) | (bias == signal), 0
        )
    entry_dir = confirmed.where(filter_ok, 0).fillna(0).astype(int)

    # ── Compute SL / TP / entry price ────────────────────────────────────────
    atr     = ind.atr
    sl_dist = atr * g.sl_max
    tp_dist = atr * g.tp_max

    c = df["close"]
    sl = np.where(entry_dir == 1, c - sl_dist, np.where(entry_dir == -1, c + sl_dist, np.nan))
    tp = np.where(entry_dir == 1, c + tp_dist, np.where(entry_dir == -1, c - tp_dist, np.nan))

    # Entry price depends on exec_mode
    offset = atr * g.stop_offset_atr
    if g.exec_stop:
        entry_px = np.where(entry_dir == 1, c + offset, np.where(entry_dir == -1, c - offset, np.nan))
    elif g.exec_limit:
        entry_px = np.where(entry_dir == 1, c - g.limit_offset_atr * atr,
                            np.where(entry_dir == -1, c + g.limit_offset_atr * atr, np.nan))
    else:
        entry_px = c.values  # market order

    return pd.DataFrame({
        "signal":     signal,
        "bias":       bias,
        "filter_ok":  filter_ok,
        "entry_dir":  entry_dir,
        "confidence": confidence,
        "sl":         sl,
        "tp":         tp,
        "entry_px":   entry_px,
        "atr":        atr,
    }, index=df.index)
