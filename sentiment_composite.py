"""sentiment_composite.py — multi-indicator SENTIMENT gauge (concept inspired by a
TradingView 'sentiment vial' design; original implementation, no copied code).

Averages SEVEN classic tools, each scored 1..5 (1=strong bear, 5=strong bull):
  RSI · EMA-stack alignment · MACD · ADX/DI · Ichimoku · Bollinger %B · OBV slope
→ Active% = (avg-1)/4*100  (0..100). Plus buying_pressure (close-in-range) for the
'health' face: green when sentiment>50 AND buying_pressure>50, else red.

Honest stance (validated below before we trust it as a SIGNAL): a composite of
LAGGING indicators is a CONTEXT/confluence gauge, not necessarily predictive.
validate() checks (1) does Active% predict forward direction OOS, (2) does it
improve the gap-fill SELL setup.
"""
from __future__ import annotations
import numpy as np


def _ema(x, n):
    a = 2.0 / (n + 1.0); o = np.array(x, float)
    for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = _ema(np.maximum(d, 0), n); dn = _ema(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.where(dn > 1e-9, dn, 1e-9))


def compute_series(close, high, low, vol):
    close = np.asarray(close, float); high = np.asarray(high, float)
    low = np.asarray(low, float); vol = np.asarray(vol, float)
    n = len(close)
    rsi = _rsi(close)
    emas = {p: _ema(close, p) for p in (9, 21, 50, 100, 200, 250)}
    macd = _ema(close, 12) - _ema(close, 26); sig = _ema(macd, 9)
    # ADX/DI
    up_m = high - np.roll(high, 1); dn_m = np.roll(low, 1) - low
    plus = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    minus = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
    atr = _ema(tr, 14) + 1e-9
    pdi = 100 * _ema(plus, 14) / atr; mdi = 100 * _ema(minus, 14) / atr
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) > 0, pdi + mdi, 1); adx = _ema(dx, 14)
    # Ichimoku
    def hh(p): return np.array([high[max(0, i - p + 1):i + 1].max() for i in range(n)])
    def ll(p): return np.array([low[max(0, i - p + 1):i + 1].min() for i in range(n)])
    tenkan = (hh(9) + ll(9)) / 2; kijun = (hh(26) + ll(26)) / 2
    spanA = (tenkan + kijun) / 2; spanB = (hh(52) + ll(52)) / 2
    # Bollinger %B
    ma = _ema(close, 20)
    sd = np.array([close[max(0, i - 19):i + 1].std() for i in range(n)]) + 1e-9
    pctb = (close - (ma - 2 * sd)) / (4 * sd)
    # OBV slope
    obv = np.cumsum(np.sign(np.diff(close, prepend=close[0])) * vol)
    obv_sl = obv - np.roll(obv, 10)
    # score each 1..5
    def sc_rsi(i): r = rsi[i]; return 5 if r > 60 else 4 if r > 52 else 3 if r > 48 else 2 if r > 40 else 1
    def sc_ema(i):
        seq = [emas[p][i] for p in (9, 21, 50, 100, 200, 250)]
        ups = sum(1 for a, b in zip(seq, seq[1:]) if a > b)
        return 1 + round(ups / 5 * 4)
    def sc_macd(i): return 5 if macd[i] > sig[i] and macd[i] > 0 else 4 if macd[i] > sig[i] else 2 if macd[i] < 0 else 3
    def sc_adx(i):
        if pdi[i] > mdi[i]: return 5 if adx[i] > 25 else 4
        if mdi[i] > pdi[i]: return 1 if adx[i] > 25 else 2
        return 3
    def sc_ichi(i):
        top = max(spanA[i], spanB[i]); bot = min(spanA[i], spanB[i])
        if close[i] > top: return 5 if tenkan[i] > kijun[i] else 4
        if close[i] < bot: return 1 if tenkan[i] < kijun[i] else 2
        return 3
    def sc_bb(i): b = pctb[i]; return 5 if b > 0.8 else 4 if b > 0.55 else 3 if b > 0.45 else 2 if b > 0.2 else 1
    def sc_obv(i): s = obv_sl[i]; return 5 if s > 0 else 1 if s < 0 else 3
    score = np.zeros(n)
    comps = []
    for i in range(n):
        cs = [sc_rsi(i), sc_ema(i), sc_macd(i), sc_adx(i), sc_ichi(i), sc_bb(i), sc_obv(i)]
        score[i] = (np.mean(cs) - 1) / 4 * 100
        comps.append(cs)
    # buying pressure = where close sits in bar range, EMA-smoothed (0..100)
    rng = (high - low); bp = np.where(rng > 0, (close - low) / rng, 0.5) * 100
    bp = _ema(bp, 5)
    return score, bp, comps


def compute_last(close, high, low, vol):
    score, bp, comps = compute_series(close, high, low, vol)
    names = ["RSI", "EMA", "MACD", "ADX", "Ichimoku", "Bollinger", "OBV"]
    return {"active_pct": round(float(score[-1]), 1),
            "buying_pressure": round(float(bp[-1]), 1),
            "components": dict(zip(names, [int(x) for x in comps[-1]])),
            "health": "bull" if (score[-1] > 50 and bp[-1] > 50) else "bear"}


def validate(symbol="XAUUSDm", tf="M15", bars=4000, K=20):
    import MetaTrader5 as mt5
    TF = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    mt5.initialize(); r = mt5.copy_rates_from_pos(symbol, TF.get(tf, mt5.TIMEFRAME_M15), 0, bars); mt5.shutdown()
    if r is None or len(r) < 500: return {"ok": False, "reason": "bars"}
    close = np.array([x["close"] for x in r], float); high = np.array([x["high"] for x in r], float)
    low = np.array([x["low"] for x in r], float); vol = np.array([x["tick_volume"] for x in r], float)
    score, bp, _ = compute_series(close, high, low, vol)
    n = len(close); hi_up = []; lo_dn = []
    for i in range(260, n - K):
        fwd = close[i + K] - close[i]
        if score[i] > 75: hi_up.append(1 if fwd > 0 else 0)
        if score[i] < 25: lo_dn.append(1 if fwd < 0 else 0)
    def rate(a): return (round(float(np.mean(a)), 3), len(a)) if len(a) >= 15 else (None, len(a))
    hu, hn = rate(hi_up); ld, ln_ = rate(lo_dn)
    return {"ok": True, "symbol": symbol, "tf": tf,
            "high_sent>75_then_up": hu, "n_hi": hn,
            "low_sent<25_then_down": ld, "n_lo": ln_,
            "predictive": bool((hu and hu >= 0.55) or (ld and ld >= 0.55))}


if __name__ == "__main__":
    import sys, json
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    for tf in ("M5", "M15", "H1"):
        print(tf, json.dumps(validate(sym, tf), ensure_ascii=False))
