"""live_indicators.py — compute the 11 dashboard indicators from OHLC bars
and emit BULLISH / BEARISH / NEUTRAL per indicator + an aggregate signal.

Pure numpy — no MT5, no network. The live path fetches bars via MT5 then
calls compute_indicator_panel(); the offline/test path passes bars directly.

Indicator set (matches strategy_types.INDICATOR_KEYS):
    sma_cross, ema_cross, macd, rsi, supertrend, stochastic,
    bollinger, ao (Awesome Oscillator), sar (Parabolic SAR), cci, adx

Each indicator returns ("BULLISH"|"BEARISH"|"NEUTRAL", detail_str).
The aggregate signal is LONG only if ALL ENABLED indicators are BULLISH,
SHORT only if ALL ENABLED are BEARISH (full-confluence rule from the spec).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from r_native.strategy_types import (
    IndicatorStatus, INDICATOR_KEYS, INDICATOR_LABELS, TF_TO_MT5_NAME,
)


# ─── Bar extraction ──────────────────────────────────────────────
def _ohlc(bars) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (open, high, low, close) float arrays from a list[dict] or a
    numpy structured array."""
    if hasattr(bars, "dtype") and getattr(bars.dtype, "names", None):
        return (bars["open"].astype(float), bars["high"].astype(float),
                bars["low"].astype(float), bars["close"].astype(float))
    o = np.array([float(b["open"])  for b in bars])
    h = np.array([float(b["high"])  for b in bars])
    l = np.array([float(b["low"])   for b in bars])
    c = np.array([float(b["close"]) for b in bars])
    return o, h, l, c


# ─── Core math ───────────────────────────────────────────────────
def _sma(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) < n:
        return np.full(len(x), np.nan)
    out = np.full(len(x), np.nan)
    csum = np.cumsum(np.insert(x, 0, 0.0))
    out[n-1:] = (csum[n:] - csum[:-n]) / n
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) == 0:
        return x
    k = 2.0 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i-1] * (1 - k)
    return out


def _rsi(c: np.ndarray, n: int = 14) -> float:
    if len(c) < n + 1:
        return 50.0
    diffs = np.diff(c)
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    avg_g = gains[-n:].mean()
    avg_l = losses[-n:].mean()
    if avg_l == 0:
        return 100.0 if avg_g > 0 else 50.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    # Wilder smoothing
    atr = np.full(len(c), np.nan)
    if len(c) <= n:
        atr[:] = tr.mean()
        return atr
    s = tr[:n].mean()
    atr[n-1] = s
    for i in range(n, len(c)):
        s = (s * (n - 1) + tr[i]) / n
        atr[i] = s
    atr[:n-1] = s
    return atr


# ─── Indicator evaluators: return (status, detail) ───────────────
def _ind_sma_cross(o, h, l, c) -> tuple[str, str]:
    fast, slow = _sma(c, 20), _sma(c, 50)
    if np.isnan(fast[-1]) or np.isnan(slow[-1]):
        return "NEUTRAL", "insufficient bars"
    if fast[-1] > slow[-1]:  return "BULLISH", f"SMA20>{'SMA50'} ({fast[-1]:.2f}>{slow[-1]:.2f})"
    if fast[-1] < slow[-1]:  return "BEARISH", f"SMA20<SMA50 ({fast[-1]:.2f}<{slow[-1]:.2f})"
    return "NEUTRAL", "flat"


def _ind_ema_cross(o, h, l, c) -> tuple[str, str]:
    fast, slow = _ema(c, 20), _ema(c, 50)
    if fast[-1] > slow[-1]:  return "BULLISH", f"EMA20>EMA50"
    if fast[-1] < slow[-1]:  return "BEARISH", f"EMA20<EMA50"
    return "NEUTRAL", "flat"


def _ind_macd(o, h, l, c) -> tuple[str, str]:
    ema12, ema26 = _ema(c, 12), _ema(c, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    hist = macd_line[-1] - signal[-1]
    if hist > 0:  return "BULLISH", f"hist +{hist:.3f}"
    if hist < 0:  return "BEARISH", f"hist {hist:.3f}"
    return "NEUTRAL", "hist 0"


def _ind_rsi(o, h, l, c) -> tuple[str, str]:
    r = _rsi(c, 14)
    if r > 55:  return "BULLISH", f"RSI {r:.1f}"
    if r < 45:  return "BEARISH", f"RSI {r:.1f}"
    return "NEUTRAL", f"RSI {r:.1f}"


def _ind_supertrend(o, h, l, c, period: int = 10, mult: float = 3.0) -> tuple[str, str]:
    atr = _atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    # Iterative supertrend direction
    direction = np.ones(len(c))   # 1 = uptrend, -1 = downtrend
    st = np.copy(lower)
    for i in range(1, len(c)):
        if np.isnan(atr[i]):
            direction[i] = direction[i-1]; st[i] = st[i-1]; continue
        if c[i] > upper[i-1]:
            direction[i] = 1
        elif c[i] < lower[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1:
                lower[i] = max(lower[i], lower[i-1])
            else:
                upper[i] = min(upper[i], upper[i-1])
        st[i] = lower[i] if direction[i] == 1 else upper[i]
    if direction[-1] > 0:  return "BULLISH", "uptrend"
    if direction[-1] < 0:  return "BEARISH", "downtrend"
    return "NEUTRAL", "flat"


def _ind_stochastic(o, h, l, c, k: int = 14, d: int = 3) -> tuple[str, str]:
    if len(c) < k + d:
        return "NEUTRAL", "insufficient bars"
    lows = np.array([l[i-k+1:i+1].min() for i in range(k-1, len(c))])
    highs = np.array([h[i-k+1:i+1].max() for i in range(k-1, len(c))])
    closes = c[k-1:]
    rng = np.where(highs - lows == 0, 1e-9, highs - lows)
    pK = (closes - lows) / rng * 100.0
    pD = _sma(pK, d)
    kv, dv = pK[-1], pD[-1]
    if np.isnan(dv): return "NEUTRAL", "warmup"
    if kv < 20 and kv > dv:  return "BULLISH", f"%K {kv:.0f} oversold cross up"
    if kv > 80 and kv < dv:  return "BEARISH", f"%K {kv:.0f} overbought cross down"
    if kv > dv:              return "BULLISH", f"%K>%D ({kv:.0f}>{dv:.0f})"
    if kv < dv:              return "BEARISH", f"%K<%D ({kv:.0f}<{dv:.0f})"
    return "NEUTRAL", f"%K {kv:.0f}"


def _ind_bollinger(o, h, l, c, n: int = 20, mult: float = 2.0) -> tuple[str, str]:
    if len(c) < n:
        return "NEUTRAL", "insufficient bars"
    mid = _sma(c, n)
    sd = np.array([c[i-n+1:i+1].std() for i in range(n-1, len(c))])
    upper = mid[n-1:] + mult * sd
    lower = mid[n-1:] - mult * sd
    price = c[-1]
    if price > upper[-1]:  return "BULLISH", "above upper band (breakout)"
    if price < lower[-1]:  return "BEARISH", "below lower band (breakdown)"
    if price > mid[-1]:    return "BULLISH", "above mid"
    if price < mid[-1]:    return "BEARISH", "below mid"
    return "NEUTRAL", "at mid"


def _ind_ao(o, h, l, c) -> tuple[str, str]:
    """Awesome Oscillator = SMA5(median) - SMA34(median)."""
    median = (h + l) / 2.0
    if len(median) < 34:
        return "NEUTRAL", "insufficient bars"
    ao = _sma(median, 5) - _sma(median, 34)
    if ao[-1] > 0 and ao[-1] >= ao[-2]:  return "BULLISH", f"AO +{ao[-1]:.3f} rising"
    if ao[-1] < 0 and ao[-1] <= ao[-2]:  return "BEARISH", f"AO {ao[-1]:.3f} falling"
    if ao[-1] > 0:  return "BULLISH", f"AO +{ao[-1]:.3f}"
    if ao[-1] < 0:  return "BEARISH", f"AO {ao[-1]:.3f}"
    return "NEUTRAL", "AO 0"


def _ind_sar(o, h, l, c, step: float = 0.02, max_step: float = 0.2) -> tuple[str, str]:
    """Parabolic SAR — standard Wilder iteration."""
    n = len(c)
    if n < 5:
        return "NEUTRAL", "insufficient bars"
    sar = np.zeros(n)
    bull = True
    af = step
    ep = h[0]
    sar[0] = l[0]
    for i in range(1, n):
        sar[i] = sar[i-1] + af * (ep - sar[i-1])
        if bull:
            if l[i] < sar[i]:
                bull = False; sar[i] = ep; ep = l[i]; af = step
            else:
                if h[i] > ep: ep = h[i]; af = min(af + step, max_step)
        else:
            if h[i] > sar[i]:
                bull = True; sar[i] = ep; ep = h[i]; af = step
            else:
                if l[i] < ep: ep = l[i]; af = min(af + step, max_step)
    if c[-1] > sar[-1]:  return "BULLISH", f"price>SAR ({c[-1]:.2f}>{sar[-1]:.2f})"
    if c[-1] < sar[-1]:  return "BEARISH", f"price<SAR ({c[-1]:.2f}<{sar[-1]:.2f})"
    return "NEUTRAL", "at SAR"


def _ind_cci(o, h, l, c, n: int = 20) -> tuple[str, str]:
    if len(c) < n:
        return "NEUTRAL", "insufficient bars"
    tp = (h + l + c) / 3.0
    sma_tp = _sma(tp, n)[-1]
    md = np.mean(np.abs(tp[-n:] - sma_tp))
    if md == 0:
        return "NEUTRAL", "flat"
    cci = (tp[-1] - sma_tp) / (0.015 * md)
    if cci >= 100:   return "BULLISH", f"CCI {cci:.0f} strong up"
    if cci <= -100:  return "BEARISH", f"CCI {cci:.0f} strong down"
    if cci > 0:      return "BULLISH", f"CCI {cci:.0f}"
    if cci < 0:      return "BEARISH", f"CCI {cci:.0f}"
    return "NEUTRAL", "CCI 0"


def _ind_adx(o, h, l, c, n: int = 14) -> tuple[str, str]:
    """ADX as a TREND-STRENGTH filter + +DI/-DI direction."""
    if len(c) < 2 * n:
        return "NEUTRAL", "insufficient bars"
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h[1:] - l[1:],
                            np.abs(h[1:] - c[:-1]),
                            np.abs(l[1:] - c[:-1])])
    atr = _wilder(tr, n)
    pdi = 100.0 * _wilder(plus_dm, n) / np.where(atr == 0, 1e-9, atr)
    mdi = 100.0 * _wilder(minus_dm, n) / np.where(atr == 0, 1e-9, atr)
    dx = 100.0 * np.abs(pdi - mdi) / np.where(pdi + mdi == 0, 1e-9, pdi + mdi)
    adx = _wilder(dx, n)
    adx_v = adx[-1]
    if adx_v < 20:
        return "NEUTRAL", f"ADX {adx_v:.0f} (ranging)"
    if pdi[-1] > mdi[-1]:  return "BULLISH", f"ADX {adx_v:.0f} +DI>-DI"
    return "BEARISH", f"ADX {adx_v:.0f} -DI>+DI"


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        out[:] = x.mean() if len(x) else 0.0
        return out
    s = x[:n].sum()
    out[n-1] = s / n
    for i in range(n, len(x)):
        s = s - (s / n) + x[i]
        out[i] = s / n
    out[:n-1] = out[n-1]
    return out


_EVALUATORS = {
    "sma_cross":  _ind_sma_cross,
    "ema_cross":  _ind_ema_cross,
    "macd":       _ind_macd,
    "rsi":        _ind_rsi,
    "supertrend": _ind_supertrend,
    "stochastic": _ind_stochastic,
    "bollinger":  _ind_bollinger,
    "ao":         _ind_ao,
    "sar":        _ind_sar,
    "cci":        _ind_cci,
    "adx":        _ind_adx,
}


# ─── Public: indicator panel + aggregate signal ─────────────────
def compute_indicators(bars, enabled: Optional[dict] = None,
                       wr_map: Optional[dict] = None) -> list[IndicatorStatus]:
    """Return list[IndicatorStatus] for all 11 indicators from `bars`.

    enabled: optional {key: bool} to mark which indicators participate.
    wr_map:  optional {key: float} standalone win-rates (0..100).
    """
    o, h, l, c = _ohlc(bars)
    out: list[IndicatorStatus] = []
    for key in INDICATOR_KEYS:
        ev = _EVALUATORS[key]
        try:
            status, _detail = ev(o, h, l, c)
        except Exception:
            status = "NEUTRAL"
        out.append(IndicatorStatus(
            key=key, label=INDICATOR_LABELS[key], status=status,
            standaloneWR=float((wr_map or {}).get(key, 0.0)),
            enabled=bool((enabled or {}).get(key, True)),
        ))
    return out


def aggregate_signal(indicators: list[IndicatorStatus]) -> str:
    """Full-confluence rule: LONG iff every ENABLED indicator is BULLISH,
    SHORT iff every ENABLED is BEARISH, else NONE."""
    enabled = [i for i in indicators if i.enabled]
    if not enabled:
        return "NONE"
    if all(i.status == "BULLISH" for i in enabled):
        return "LONG"
    if all(i.status == "BEARISH" for i in enabled):
        return "SHORT"
    return "NONE"


def confluence_score(indicators: list[IndicatorStatus]) -> dict:
    """How many enabled indicators agree, and in which direction.
    Returns {bullish, bearish, neutral, enabled, dominant, pct}."""
    enabled = [i for i in indicators if i.enabled]
    bull = sum(1 for i in enabled if i.status == "BULLISH")
    bear = sum(1 for i in enabled if i.status == "BEARISH")
    neut = sum(1 for i in enabled if i.status == "NEUTRAL")
    n = len(enabled) or 1
    dominant = "LONG" if bull > bear else ("SHORT" if bear > bull else "NONE")
    pct = round(max(bull, bear) / n * 100.0, 1)
    return {"bullish": bull, "bearish": bear, "neutral": neut,
            "enabled": len(enabled), "dominant": dominant, "pct": pct}


# ─── Live MT5 path ──────────────────────────────────────────────
def compute_indicator_panel(symbol: str, tf: str = "15m", n_bars: int = 120,
                            enabled: Optional[dict] = None,
                            wr_map: Optional[dict] = None) -> dict:
    """Fetch live bars from MT5 then build the dashboard payload.

    Returns {ok, symbol, tf, indicators:[...], signal, confluence}.
    Returns ok=False with a reason on any failure (caller renders a hint).
    """
    try:
        import MetaTrader5 as mt5
    except Exception:
        return {"ok": False, "reason": "MetaTrader5 unavailable"}
    try:
        if not mt5.initialize():
            mt5.initialize()
        tf_name = TF_TO_MT5_NAME.get(tf, "M15")
        tf_const = getattr(mt5, f"TIMEFRAME_{tf_name}", None)
        if tf_const is None:
            return {"ok": False, "reason": f"bad tf {tf}"}
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n_bars)
        if rates is None or len(rates) < 40:
            return {"ok": False, "reason": "insufficient bars"}
        inds = compute_indicators(rates, enabled=enabled, wr_map=wr_map)
        return {
            "ok": True, "symbol": symbol, "tf": tf,
            "indicators": [i.to_dict() for i in inds],
            "signal": aggregate_signal(inds),
            "confluence": confluence_score(inds),
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}
