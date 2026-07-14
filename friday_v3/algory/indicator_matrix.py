"""indicator_matrix.py — the FPU-MAX indicator suite ported to Python.

R's brain used to lean on ATR + RSI only. This module computes the full
21-indicator panel (the same set as the TradingView "Free Plan Unlocked - MAX"
Pine script the user provided) across multiple timeframes, then rolls it up
into an honest bull/bear *confluence score* so the gate can reason on breadth
of agreement instead of a single oscillator.

Pure functions over OHLCV arrays — NO MT5 / network here (brain_server feeds it
bars from its shared, already-alive mt5 handle). numpy + pandas only; no TA-lib.

Directional signals (19)  → vote bull(+1)/bear(-1)  → confluence_score 0..100
Strength signals   (ADX, ATR%) → context gates, not votes.

Indicators (matching the Pine f_scan order):
  1 ema9>21   2 ema21>50   3 ema50>200   4 RSI(14)   5 Stoch(14)
  6 MACD x    7 MACD hist  8 CCI(20)     9 MFI(14)   10 ADX(14)*
 11 DI+>DI-  12 BB %B     13 W%R(14)    14 ROC(9)   15 ATR%*
 16 OBV up   17 SuperT    18 Mom(10)    19 >SMA20   20 >SMA50   21 >10 ago
(* = strength, not a directional vote)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── timeframes the matrix scans (label → nominal minutes, for reference) ──
DEFAULT_TFS = ["M5", "M15", "H1", "H4", "D1", "W1"]

# indicators that measure strength/volatility, not direction — excluded from vote
_STRENGTH_KEYS = {"adx", "atr_pct"}


# ═══════════════════════════ primitive helpers ═══════════════════════════
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rma(s: pd.Series, n: int) -> pd.Series:
    # Wilder's smoothing
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = _rma(d.clip(lower=0), n)
    dn = _rma((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _stoch_k(close, high, low, n: int = 14) -> pd.Series:
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    rng = (hh - ll).replace(0, np.nan)
    return (((close - ll) / rng) * 100.0).fillna(50.0)


def _macd(close: pd.Series, f=12, sl=26, sig=9):
    line = _ema(close, f) - _ema(close, sl)
    signal = _ema(line, sig)
    return line, signal, line - signal


def _cci(close, high, low, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    sma = tp.rolling(n).mean()
    md = (tp - sma).abs().rolling(n).mean()
    return ((tp - sma) / (0.015 * md.replace(0, np.nan))).fillna(0.0)


def _mfi(close, high, low, vol, n: int = 14) -> pd.Series:
    tp = (high + low + close) / 3.0
    mf = tp * vol
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    mr = pos / neg.replace(0, np.nan)
    return (100 - 100 / (1 + mr)).fillna(50.0)


def _atr(close, high, low, n: int = 14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return _rma(tr, n)


def _dmi(close, high, low, n: int = 14):
    up = high.diff()
    dn = -low.diff()
    plus = up.where((up > dn) & (up > 0), 0.0)
    minus = dn.where((dn > up) & (dn > 0), 0.0)
    atr = _atr(close, high, low, n)
    di_p = 100 * _rma(plus, n) / atr.replace(0, np.nan)
    di_m = 100 * _rma(minus, n) / atr.replace(0, np.nan)
    dx = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    adx = _rma(dx.fillna(0.0), n)
    return di_p.fillna(0.0), di_m.fillna(0.0), adx.fillna(0.0)


def _bb_pctb(close: pd.Series, n=20, mult=2.0) -> pd.Series:
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    up = mid + mult * sd
    lo = mid - mult * sd
    rng = (up - lo).replace(0, np.nan)
    return (((close - lo) / rng) * 100.0).fillna(50.0)


def _wpr(close, high, low, n: int = 14) -> pd.Series:
    hh = high.rolling(n).max()
    ll = low.rolling(n).min()
    rng = (hh - ll).replace(0, np.nan)
    return (((hh - close) / rng) * -100.0).fillna(-50.0)


def _roc(close: pd.Series, n: int = 9) -> pd.Series:
    return (close / close.shift(n) - 1.0).fillna(0.0) * 100.0


def _obv(close: pd.Series, vol: pd.Series) -> pd.Series:
    sign = np.sign(close.diff().fillna(0.0))
    return (sign * vol).cumsum()


def _supertrend_bull(close, high, low, period=10, mult=3.0) -> bool:
    atr = _atr(close, high, low, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    n = len(close)
    if n < period + 2:
        return bool(close.iloc[-1] > hl2.iloc[-1])
    fu = np.array(upper.values, dtype=float)
    fl = np.array(lower.values, dtype=float)
    lo_raw = np.array(lower.values, dtype=float)
    up_raw = np.array(upper.values, dtype=float)
    c = np.array(close.values, dtype=float)
    dir_up = True
    for i in range(1, n):
        fl[i] = max(lo_raw[i], fl[i - 1]) if c[i - 1] > fl[i - 1] else lo_raw[i]
        fu[i] = min(up_raw[i], fu[i - 1]) if c[i - 1] < fu[i - 1] else up_raw[i]
        if c[i] > fu[i - 1]:
            dir_up = True
        elif c[i] < fl[i - 1]:
            dir_up = False
    return bool(dir_up)


# ═══════════════════════════ main panel ═══════════════════════════
def compute_panel(o, h, l, c, v) -> dict:
    """Return the 21-indicator panel for one timeframe from raw OHLCV lists.

    Each entry: {"value": <num|bool>, "bull": <bool|None>, "kind": "bool"|"val"}.
    bull is None for the two strength indicators (adx, atr_pct).
    Returns {} if there are too few bars to compute reliably (<210 for ema200).
    """
    c = pd.Series(np.asarray(c, dtype=float))
    h = pd.Series(np.asarray(h, dtype=float))
    l = pd.Series(np.asarray(l, dtype=float))
    o = pd.Series(np.asarray(o, dtype=float))
    v = pd.Series(np.asarray(v, dtype=float))
    n = len(c)
    if n < 30:
        return {}

    last = -1
    have200 = n >= 210
    have50 = n >= 60

    ema9, ema21, ema50 = _ema(c, 9), _ema(c, 21), _ema(c, 50)
    ema200 = _ema(c, 200) if have200 else None
    rsi = _rsi(c, 14)
    stoch = _stoch_k(c, h, l, 14)
    ml, ms, mh = _macd(c)
    cci = _cci(c, h, l, 20)
    mfi = _mfi(c, h, l, v, 14)
    di_p, di_m, adx = _dmi(c, h, l, 14)
    bbb = _bb_pctb(c, 20, 2.0)
    wpr = _wpr(c, h, l, 14)
    roc = _roc(c, 9)
    atr = _atr(c, h, l, 14)
    atr_pct = float(atr.iloc[last] / c.iloc[last] * 100.0) if c.iloc[last] else 0.0
    obv = _obv(c, v)
    st_bull = _supertrend_bull(c, h, l, 10, 3.0)
    mom = float(c.iloc[last] - c.iloc[last - 10]) if n > 10 else 0.0
    sma20 = _sma(c, 20)
    sma50 = _sma(c, 50) if have50 else None

    def B(val):   # boolean signal
        return {"value": bool(val), "bull": bool(val), "kind": "bool"}

    def Vv(val, bull):  # numeric directional
        return {"value": round(float(val), 3), "bull": bool(bull), "kind": "val"}

    def S(val):   # strength (no direction)
        return {"value": round(float(val), 3), "bull": None, "kind": "val"}

    panel = {
        "ema9_gt_21":   B(ema9.iloc[last] > ema21.iloc[last]),
        "ema21_gt_50":  B(ema21.iloc[last] > ema50.iloc[last]),
        "ema50_gt_200": B(ema200.iloc[last] > 0 and ema50.iloc[last] > ema200.iloc[last]) if ema200 is not None else B(False),
        "rsi":          Vv(rsi.iloc[last], rsi.iloc[last] > 50),
        "stoch":        Vv(stoch.iloc[last], stoch.iloc[last] > 50),
        "macd_x":       B(ml.iloc[last] > ms.iloc[last]),
        "macd_hist":    Vv(mh.iloc[last], mh.iloc[last] > 0),
        "cci":          Vv(cci.iloc[last], cci.iloc[last] > 0),
        "mfi":          Vv(mfi.iloc[last], mfi.iloc[last] > 50),
        "adx":          S(adx.iloc[last]),
        "di_plus_gt_minus": B(di_p.iloc[last] > di_m.iloc[last]),
        "bb_pctb":      Vv(bbb.iloc[last], bbb.iloc[last] > 50),
        "wpr":          Vv(wpr.iloc[last], wpr.iloc[last] > -50),
        "roc":          Vv(roc.iloc[last], roc.iloc[last] > 0),
        "atr_pct":      S(atr_pct),
        "obv_up":       B(obv.iloc[last] > obv.iloc[last - 1]) if n > 1 else B(False),
        "supertrend":   B(st_bull),
        "mom":          Vv(mom, mom > 0),
        "close_gt_sma20": B(c.iloc[last] > sma20.iloc[last]),
        "close_gt_sma50": B(sma50 is not None and c.iloc[last] > sma50.iloc[last]) if sma50 is not None else B(False),
        "close_gt_10ago": B(n > 10 and c.iloc[last] > c.iloc[last - 10]),
    }
    return panel


def score_panel(panel: dict) -> dict:
    """Roll a panel into bull/bear votes + a 0..100 confluence score.

    confluence = bull_votes / directional_total * 100 (50 = perfectly split).
    direction = BULL / BEAR / NEUTRAL by the vote balance.
    """
    if not panel:
        return {"bull": 0, "bear": 0, "total": 0, "score": 50.0, "direction": "NEUTRAL"}
    bull = bear = 0
    for k, d in panel.items():
        if k in _STRENGTH_KEYS or d.get("bull") is None:
            continue
        if d["bull"]:
            bull += 1
        else:
            bear += 1
    total = bull + bear
    score = round(bull / total * 100.0, 1) if total else 50.0
    if score >= 62:
        direction = "BULL"
    elif score <= 38:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"
    adx = panel.get("adx", {}).get("value", 0.0)
    return {
        "bull": bull, "bear": bear, "total": total,
        "score": score, "direction": direction,
        "adx": adx, "trending": bool(adx and adx >= 20),
    }


def build_matrix(bars_by_tf: dict) -> dict:
    """bars_by_tf: {tf_label: {"o":[],"h":[],"l":[],"c":[],"v":[]}} →
    {"per_tf": {tf: {"panel":..., "score":...}},
     "aggregate": {"score", "direction", "bull_tfs", "bear_tfs", "trend_align"}}.

    aggregate.score = mean of per-TF scores weighted by how much data each TF has
    (equal weight here); trend_align = fraction of TFs agreeing on direction.
    """
    per_tf = {}
    scores = []
    dirs = []
    for tf, b in (bars_by_tf or {}).items():
        panel = compute_panel(b.get("o"), b.get("h"), b.get("l"), b.get("c"), b.get("v"))
        sc = score_panel(panel)
        per_tf[tf] = {"panel": panel, "score": sc}
        if panel:
            scores.append(sc["score"])
            dirs.append(sc["direction"])
    if scores:
        agg_score = round(sum(scores) / len(scores), 1)
    else:
        agg_score = 50.0
    bull_tfs = dirs.count("BULL")
    bear_tfs = dirs.count("BEAR")
    if agg_score >= 62:
        agg_dir = "BULL"
    elif agg_score <= 38:
        agg_dir = "BEAR"
    else:
        agg_dir = "NEUTRAL"
    dominant = max(bull_tfs, bear_tfs)
    align = round(dominant / len(dirs), 2) if dirs else 0.0
    return {
        "per_tf": per_tf,
        "aggregate": {
            "score": agg_score,
            "direction": agg_dir,
            "bull_tfs": bull_tfs,
            "bear_tfs": bear_tfs,
            "tf_count": len(dirs),
            "trend_align": align,
        },
    }


# ── self-test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import math
    N = 260
    # synthetic clean uptrend → should read strongly BULL
    up_c = [100 + i * 0.5 + math.sin(i / 5) for i in range(N)]
    up_h = [x + 0.3 for x in up_c]
    up_l = [x - 0.3 for x in up_c]
    up_o = [up_c[i - 1] if i else up_c[0] for i in range(N)]
    up_v = [1000 + (i % 7) * 10 for i in range(N)]
    p = compute_panel(up_o, up_h, up_l, up_c, up_v)
    s = score_panel(p)
    assert p, "panel empty on 260 bars"
    assert len(p) == 21, f"expected 21 indicators, got {len(p)}"
    assert s["direction"] == "BULL", f"uptrend not BULL: {s}"
    assert s["score"] > 70, f"uptrend score low: {s}"

    # synthetic downtrend → BEAR
    dn_c = [200 - i * 0.5 + math.sin(i / 5) for i in range(N)]
    dn_h = [x + 0.3 for x in dn_c]
    dn_l = [x - 0.3 for x in dn_c]
    dn_o = [dn_c[i - 1] if i else dn_c[0] for i in range(N)]
    dn_v = [1000 + (i % 7) * 10 for i in range(N)]
    ps = score_panel(compute_panel(dn_o, dn_h, dn_l, dn_c, dn_v))
    assert ps["direction"] == "BEAR", f"downtrend not BEAR: {ps}"
    assert ps["score"] < 30, f"downtrend score high: {ps}"

    # too-few-bars guard
    assert compute_panel([1, 2], [1, 2], [1, 2], [1, 2], [1, 1]) == {}, "short-bars guard failed"

    # aggregate over TFs
    bars = {"H1": {"o": up_o, "h": up_h, "l": up_l, "c": up_c, "v": up_v},
            "H4": {"o": dn_o, "h": dn_h, "l": dn_l, "c": dn_c, "v": dn_v}}
    m = build_matrix(bars)
    assert m["aggregate"]["tf_count"] == 2, m["aggregate"]
    assert m["aggregate"]["bull_tfs"] == 1 and m["aggregate"]["bear_tfs"] == 1, m["aggregate"]
    print("indicator_matrix self-test PASSED")
    print("  uptrend  :", s)
    print("  downtrend:", ps)
    print("  aggregate:", m["aggregate"])
