"""chart_read.py — ONE consolidated "what is the chart saying right now" read.

This is the bridge that BINDS live trade entries to the chart reading the user sees.
It returns a single directional verdict + a confluence score (0..1) built from the same
signals the dashboard draws: the genome signal engine action, the Markov daily regime,
RSI / MACD / Stochastic, the sentiment composite, and SMC structure.

Source priority:
  1. HTTP  /api/decision/{symbol}/{tf}  on the live dashboard (:8866) — this is the
     EXACT reading shown on the chart (single source of truth). Preferred.
  2. LOCAL fallback computed directly from MT5 bars (if the dashboard is down) so the
     trader still reads the market instead of trading blind. Marked source="local".

Used by gold_live.py: it only enters when the chart read AGREES with its own setup and
the confluence clears a gate.
"""
from __future__ import annotations
import json
import time
import urllib.request

DASH = "http://127.0.0.1:8866"
STATES = ["Bear", "Sideways", "Bull"]


# ── 1) HTTP read — the real chart ────────────────────────────────────────────
def read_http(symbol: str, tf: str = "M15", timeout: float = 6.0) -> dict | None:
    try:
        url = f"{DASH}/api/decision/{symbol}/{tf}"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        if isinstance(d, dict) and "dir" in d and "error" not in d:
            d["source"] = "chart"
            return d
    except Exception:
        return None
    return None


# ── 2) LOCAL fallback — compute the same condensed read from MT5 ──────────────
def _ema(x, n):
    a = 2.0 / (n + 1.0); o = list(x)
    for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o


def _rsi(c, n=14):
    if len(c) <= n: return 50.0
    gains = []; losses = []
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]; gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n; al = sum(losses[:n]) / n          # seed = SMA of first n (Wilder)
    for i in range(n, len(gains)):                            # Wilder smoothing (المعيار، يطابق MT5/TA-Lib)
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    return 100 - 100 / (1 + ag / al) if al > 1e-9 else 100.0


def _markov_regime(mt5, symbol):
    try:
        from markov_regime import label_regimes, transition_matrix
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 2500)
        if r is None or len(r) < 120: return None
        lab, valid = label_regimes([x["close"] for x in r], 20, 0.02)
        return STATES[int(lab[valid][-1])] if valid.any() else "Sideways"
    except Exception:
        return None


# ── Extra indicators (pure-python, fast) — each returns +1 bull / -1 bear / 0 neutral ──
def _sma(x, n): return sum(x[-n:]) / n if len(x) >= n else sum(x) / len(x)


def _adx_di(high, low, close, n=14):
    """Wilder ADX (المعيار) + directional bias. Returns (adx, +1/-1/0)."""
    if len(close) < 2 * n + 2: return 0.0, 0
    plus = []; minus = []; trs = []
    for i in range(1, len(close)):
        up = high[i] - high[i - 1]; dn = low[i - 1] - low[i]
        plus.append(up if (up > dn and up > 0) else 0.0)
        minus.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    if len(trs) < n + 1: return 0.0, 0
    atr = sum(trs[:n]); pdm = sum(plus[:n]); mdm = sum(minus[:n]); dxs = []
    pdi = mdi = 0.0
    for i in range(n, len(trs)):                              # Wilder RMA لـDM/TR ثم DX
        atr = atr - atr / n + trs[i]; pdm = pdm - pdm / n + plus[i]; mdm = mdm - mdm / n + minus[i]
        pdi = 100 * pdm / atr if atr > 0 else 0.0
        mdi = 100 * mdm / atr if atr > 0 else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi + 1e-9))
    if not dxs: return 0.0, 0
    adx = sum(dxs[:n]) / n if len(dxs) >= n else sum(dxs) / len(dxs)
    for i in range(n, len(dxs)):                              # ADX = تنعيم Wilder لـDX
        adx = (adx * (n - 1) + dxs[i]) / n
    v = 1 if pdi > mdi else -1 if mdi > pdi else 0
    return adx, (v if adx >= 20 else 0)        # only trust direction when trend has strength


def _bollinger(close, n=20, k=2.0):
    if len(close) < n: return 0
    mid = _sma(close, n)
    var = sum((c - mid) ** 2 for c in close[-n:]) / n
    sd = var ** 0.5; price = close[-1]
    up = mid + k * sd; dn = mid - k * sd
    if price > up: return 1            # breakout up
    if price < dn: return -1           # breakdown
    return 1 if price > mid else -1    # bias by half


def _cci(high, low, close, n=20):
    if len(close) < n: return 0
    tp = [(high[i] + low[i] + close[i]) / 3 for i in range(len(close))]
    sma = _sma(tp, n); md = sum(abs(t - sma) for t in tp[-n:]) / n
    if md <= 0: return 0
    c = (tp[-1] - sma) / (0.015 * md)
    return 1 if c > 80 else -1 if c < -80 else 0


def _williams_r(high, low, close, n=14):
    if len(close) < n: return 0
    hi = max(high[-n:]); lo = min(low[-n:])
    wr = -100 * (hi - close[-1]) / (hi - lo + 1e-9)
    return 1 if wr > -50 else -1            # >-50 bullish half, <-50 bearish half


def _ichimoku(high, low, close):
    if len(close) < 52: return 0
    ten = (max(high[-9:]) + min(low[-9:])) / 2
    kij = (max(high[-26:]) + min(low[-26:])) / 2
    a = (ten + kij) / 2
    b = (max(high[-52:]) + min(low[-52:])) / 2
    price = close[-1]; cloud_top = max(a, b); cloud_bot = min(a, b)
    if price > cloud_top and ten > kij: return 1
    if price < cloud_bot and ten < kij: return -1
    return 1 if ten > kij else -1


def _obv_slope(close, vol, n=20):
    if len(close) < n + 1: return 0
    obv = 0.0; series = [0.0]
    for i in range(1, len(close)):
        obv += vol[i] if close[i] > close[i - 1] else -vol[i] if close[i] < close[i - 1] else 0
        series.append(obv)
    return 1 if series[-1] > series[-n] else -1 if series[-1] < series[-n] else 0


def _vwap_vote(high, low, close, vol, n=60):
    if len(close) < n: return 0
    num = den = 0.0
    for i in range(len(close) - n, len(close)):
        tp = (high[i] + low[i] + close[i]) / 3; num += tp * vol[i]; den += vol[i]
    if den <= 0: return 0
    vwap = num / den
    return 1 if close[-1] > vwap else -1


def _roc(close, n=10):
    if len(close) < n + 1: return 0
    r = close[-1] / close[-1 - n] - 1.0
    return 1 if r > 0.0005 else -1 if r < -0.0005 else 0


def _supertrend(high, low, close, n=10, mult=3.0):
    if len(close) < n + 2: return 0
    atr = 0.0
    for i in range(len(close) - n, len(close)):
        atr += max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr /= n
    hl2 = (high[-1] + low[-1]) / 2
    upper = hl2 + mult * atr; lower = hl2 - mult * atr
    if close[-1] > upper: return 1
    if close[-1] < lower: return -1
    return 1 if close[-1] > hl2 else -1


def _donchian(high, low, close, n=20):
    if len(close) < n + 1: return 0
    hh = max(high[-n - 1:-1]); ll = min(low[-n - 1:-1])
    if close[-1] > hh: return 1
    if close[-1] < ll: return -1
    return 0


def _keltner(high, low, close, n=20, m=1.5):
    if len(close) < n + 2: return 0
    mid = _ema(close, n)[-1]
    atr = sum(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
              for i in range(len(close) - n, len(close))) / n
    if close[-1] > mid + m * atr: return 1
    if close[-1] < mid - m * atr: return -1
    return 1 if close[-1] > mid else -1


def _mfi(high, low, close, vol, n=14):
    if len(close) < n + 1: return 0
    pos = neg = 0.0
    for i in range(len(close) - n, len(close)):
        tp = (high[i] + low[i] + close[i]) / 3; tp0 = (high[i - 1] + low[i - 1] + close[i - 1]) / 3
        mf = tp * vol[i]
        if tp > tp0: pos += mf
        elif tp < tp0: neg += mf
    if neg <= 0: return 1 if pos > 0 else 0
    mfi = 100 - 100 / (1 + pos / neg)
    return 1 if mfi > 55 else -1 if mfi < 45 else 0


def _aroon(high, low, n=25):
    if len(high) < n + 1: return 0
    hi = high[-n - 1:]; lo = low[-n - 1:]
    up = (n - (len(hi) - 1 - hi.index(max(hi)))) / n * 100
    dn = (n - (len(lo) - 1 - lo.index(min(lo)))) / n * 100
    return 1 if up > dn else -1 if dn > up else 0


def _cmo(close, n=14):
    if len(close) < n + 1: return 0
    up = dn = 0.0
    for i in range(len(close) - n, len(close)):
        d = close[i] - close[i - 1]
        if d > 0: up += d
        else: dn += -d
    if up + dn <= 0: return 0
    cmo = 100 * (up - dn) / (up + dn)
    return 1 if cmo > 25 else -1 if cmo < -25 else 0


def _momentum(close, n=10):
    if len(close) < n + 1: return 0
    return 1 if close[-1] > close[-1 - n] else -1 if close[-1] < close[-1 - n] else 0


def _sr_zone(high, low, close, n=50):
    """Support/Resistance & supply/demand zones: bounce-bias near support, reject-bias near
    resistance (position within the recent range)."""
    if len(close) < n: return 0
    hi = max(high[-n:]); lo = min(low[-n:]); rng = hi - lo
    if rng <= 0: return 0
    pos = (close[-1] - lo) / rng
    if pos <= 0.20: return 1          # at demand/support → bounce
    if pos >= 0.80: return -1         # at supply/resistance → reject
    return 0


def _liq_sweep(high, low, close, n=20):
    """Liquidity sweep (SMC): price grabs the stops beyond a recent extreme then reverses."""
    if len(close) < n + 1: return 0
    ph = max(high[-n - 1:-1]); pl = min(low[-n - 1:-1])
    if high[-1] > ph and close[-1] < ph: return -1   # swept highs, rejected → bearish
    if low[-1] < pl and close[-1] > pl: return 1      # swept lows, reclaimed → bullish
    return 0


def _learned_factors(symbol: str) -> dict:
    """Per-indicator weight multiplier learned from MEASURED OOS accuracy (self-improvement).
    factor = clamp(1 + lift*10, 0.2, 2.0): accurate indicators (lift>0) weigh more, coin-flip
    ones shrink toward a 0.2 floor. Returns {} (=> all 1.0) if no accuracy file for this symbol."""
    try:
        import json as _j
        from pathlib import Path as _P
        p = _P(r"C:\Users\Radhi\MT5\r_native_v2\data") / f"indicator_accuracy_{symbol}.json"
        acc = _j.loads(p.read_text(encoding="utf-8")).get("accuracy", {})
        out = {}
        for name, d in acc.items():
            if d.get("votes", 0) >= 40:
                out[name] = max(0.2, min(2.0, 1.0 + float(d.get("lift", 0.0)) * 10.0))
        return out
    except Exception:
        return {}


_MACRO = {"mtime": -1.0, "data": {}}


def _macro_vote(symbol: str) -> int:
    """مؤشّر Index/DXY (طلب المستخدم): يقرأ التحيّز الكلّيّ المُشتقّ من الدولار/المؤشّرات في macro_state.json
    (bias[symbol] محسوب من DXY/VIX/10Y/SPX...). صعود الدولار ⇒ ضغط على XXXUSD والذهب، ودعم لـ USDXXX —
    وهذا مُضمَّن أصلاً في bias. تصويت: +1/−1/0. fail-safe + حداثة (يتجاهل البيانات القديمة)."""
    import json as _json, os as _os, time as _t
    p = r"C:\Users\Radhi\MT5\data\r_native\macro_state.json"
    try:
        m = _os.stat(p).st_mtime
        if m != _MACRO["mtime"]:
            _MACRO["data"] = _json.load(open(p, encoding="utf-8")) or {}
            _MACRO["mtime"] = m
        d = _MACRO["data"]
        if _t.time() - float(d.get("ts", 0.0)) > 3600:          # بيانات أقدم من ساعة ⇒ لا تصويت
            return 0
        b = d.get("bias", {}).get(symbol)
        if b is None:                                            # لا تحيّز جاهز ⇒ اشتقّ من اتجاه DXY + علاقة الدولار
            dxy = (d.get("instruments", {}).get("DXY", {}) or {}).get("trend", 0)
            s = symbol.upper().rstrip("M")
            if s[3:6] == "USD":   b = -dxy                       # XXXUSD (ذهب/يورو/بتكوين...): عكس الدولار
            elif s[0:3] == "USD": b = dxy                        # USDXXX: مع الدولار
            else:                 b = 0
        return 1 if b > 0.25 else -1 if b < -0.25 else 0
    except Exception:
        return 0


def read_local(mt5, symbol: str, tf: str = "M15", bars: int = 300) -> dict | None:
    TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
          "H1": mt5.TIMEFRAME_H1}.get(tf, mt5.TIMEFRAME_M15)
    r = mt5.copy_rates_from_pos(symbol, TF, 0, bars)
    if r is None or len(r) < 60:
        return None
    close = [float(x["close"]) for x in r]
    high  = [float(x["high"]) for x in r]
    low   = [float(x["low"]) for x in r]
    open_ = [float(x["open"]) for x in r]
    price = close[-1]
    ema50 = _ema(close, 50)[-1]
    ema_fast = _ema(close, 12); ema_slow = _ema(close, 26)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    macd_sig  = _ema(macd_line, 9)
    macd_hist = macd_line[-1] - macd_sig[-1]
    rsi = _rsi(close)
    kp = 14
    lo = min(low[-kp:]); hi = max(high[-kp:])
    sk = 100 * (price - lo) / (hi - lo + 1e-10)
    # %D ~ mean of last 3 %K (approx)
    sks = []
    for j in range(len(close) - 3, len(close)):
        loj = min(low[max(0, j - kp + 1):j + 1]); hij = max(high[max(0, j - kp + 1):j + 1])
        sks.append(100 * (close[j] - loj) / (hij - loj + 1e-10))
    sd = sum(sks) / len(sks)
    reg = _markov_regime(mt5, symbol)

    votes, weights = {}, {}
    _lf = _learned_factors(symbol)              # measured-accuracy weight multipliers (self-improving)
    def cast(name, v, w): votes[name] = int(v); weights[name] = float(w) * _lf.get(name, 1.0)
    cast("trend", 1 if price > ema50 else -1 if price < ema50 else 0, 2.0)
    cast("markov", 1 if reg == "Bull" else -1 if reg == "Bear" else 0, 2.0)
    cast("rsi", 1 if rsi > 55 else -1 if rsi < 45 else 0, 1.0)
    cast("macd", 1 if macd_hist > 0 else -1 if macd_hist < 0 else 0, 1.0)
    cast("stoch", 1 if (sk > sd and sk < 80) else -1 if (sk < sd and sk > 20) else 0, 1.0)
    cast("dxy_macro", _macro_vote(symbol), 1.2)   # 📊 Index/DXY: تحيّز الدولار/المؤشّرات (يُسجَّل في الجينات، وزنه يتعلّم)
    # sentiment composite (optional)
    try:
        from sentiment_composite import compute_series as _cs
        if len(close) >= 270:
            sc, bp, _ = _cs(close, high, low, [float(x.get("tick_volume", 1)) for x in r])
            cast("sentiment", 1 if (sc[-1] > 50 and bp[-1] > 50) else -1 if (sc[-1] < 50 and bp[-1] < 50) else 0, 1.0)
    except Exception:
        pass

    # ── MORE indicators (each defensive; enough confirming momentum can flip a weak macro) ──
    try:
        vol = [float(x["tick_volume"]) for x in r]
    except Exception:
        try: vol = [float(x["volume"]) for x in r]
        except Exception: vol = [1.0] * len(close)
    for _name, _fn, _w in (
        ("adx",        lambda: _adx_di(high, low, close)[1],       1.5),
        ("ema_cross",  lambda: 1 if _ema(close, 9)[-1] > _ema(close, 21)[-1] else -1, 1.5),
        ("supertrend", lambda: _supertrend(high, low, close),      1.5),
        ("ichimoku",   lambda: _ichimoku(high, low, close),        1.5),
        ("vwap",       lambda: _vwap_vote(high, low, close, vol),  1.5),
        ("bollinger",  lambda: _bollinger(close),                  1.0),
        ("cci",        lambda: _cci(high, low, close),             1.0),
        ("williams",   lambda: _williams_r(high, low, close),      1.0),
        ("obv",        lambda: _obv_slope(close, vol),             1.0),
        ("roc",        lambda: _roc(close),                        1.0),
        # ── auto-discovery library: new candidates; the learned-accuracy weighting decides
        #    which ones matter per symbol (accurate→up, useless→0.2 floor), re-judged hourly ──
        ("donchian",   lambda: _donchian(high, low, close),        1.0),
        ("keltner",    lambda: _keltner(high, low, close),         1.0),
        ("mfi",        lambda: _mfi(high, low, close, vol),        1.0),
        ("aroon",      lambda: _aroon(high, low),                  1.0),
        ("cmo",        lambda: _cmo(close),                        1.0),
        ("momentum",   lambda: _momentum(close),                   1.0),
        ("sr_zone",    lambda: _sr_zone(high, low, close),         1.2),   # دعم/مقاومة/عرض/طلب
        ("liq_sweep",  lambda: _liq_sweep(high, low, close),       1.2),   # سيولة (sweep)
    ):
        try:
            cast(_name, _fn(), _w)
        except Exception:
            pass

    # ── advanced indicators (Fisher/Vortex/TSI/Gann/Hurst-fractal/candle-geo/Chaikin/Elder) ──
    # same set the gene is trained on; each judged by MEASURED per-symbol accuracy (learned weight).
    try:
        import advanced_indicators as _ai
        for _nm, _k, _w in _ai.REGISTRY:
            try: cast(_nm, _ai.vote(_nm, high, low, close, vol), _w)
            except Exception: pass
    except Exception: pass

    # ── TA-Lib indicators we DIDN'T have (KAMA/MAMA/Hilbert cycle/candlestick patterns) ──
    # كل واحد يدخل بوزن متعلّم مثل البقية؛ الدقّة المقيسة تقرّر مصيره (مفيد→يرتفع، عديم→0.2).
    try:
        import talib, numpy as _np
        _c = _np.asarray(close, float); _h = _np.asarray(high, float)
        _l = _np.asarray(low, float); _o = _np.asarray(open_, float)
        def _ok(v):
            return v is not None and not _np.isnan(v)
        _kama = talib.KAMA(_c, timeperiod=20)
        if _ok(_kama[-1]):
            cast("kama", 1 if price > _kama[-1] else -1, 1.0)        # متوسط كوفمان التكيّفي
        _mama, _fama = talib.MAMA(_c)
        if _ok(_mama[-1]) and _ok(_fama[-1]):
            cast("mama", 1 if _mama[-1] > _fama[-1] else -1, 1.0)    # MESA التكيّفي
        _htt = talib.HT_TRENDLINE(_c)
        if _ok(_htt[-1]):
            cast("ht_trend", 1 if price > _htt[-1] else -1, 1.0)     # خط ترند هيلبرت
        _tm = talib.HT_TRENDMODE(_c)                                 # 1=ترند 0=دورة
        _slope = _c[-1] - _c[-4] if len(_c) >= 4 else 0
        if _ok(_tm[-1]) and _tm[-1] == 1:
            cast("ht_cycle", 1 if _slope > 0 else -1 if _slope < 0 else 0, 0.8)
        # أنماط الشموع: مجموع إشارات أنماط موثوقة على آخر شمعة
        _pat = 0
        for _fn in (talib.CDLENGULFING, talib.CDLHAMMER, talib.CDLSHOOTINGSTAR,
                    talib.CDLMORNINGSTAR, talib.CDLEVENINGSTAR, talib.CDL3WHITESOLDIERS,
                    talib.CDL3BLACKCROWS, talib.CDLPIERCING, talib.CDLDARKCLOUDCOVER):
            try:
                _s = _fn(_o, _h, _l, _c)[-1]
                _pat += (1 if _s > 0 else -1 if _s < 0 else 0)
            except Exception:
                pass
        cast("candles", 1 if _pat > 0 else -1 if _pat < 0 else 0, 1.0)
    except Exception:
        pass

    # ── داخليات السوق (market_internals): DRP موقع السعر في مدى اليوم + قوة نسبية مقطعية ──
    try:
        _mif = r"C:\Users\Radhi\MT5\data\r_native\market_internals.json"
        with open(_mif, encoding="utf-8") as _f:
            _mi = json.loads(_f.read())
        if time.time() - float(_mi.get("_ts", 0)) < 300:
            _row = _mi.get(symbol) or {}
            _drp = _row.get("drp")
            if _drp is not None:
                # زخم بمنطقة وسطى · لكن عند الإرهاق (>90 قمة / <10 قاع) لا تشترِ/تبع القمة/القاع
                _dv = 1 if 70 <= _drp < 90 else -1 if 10 < _drp <= 30 else 0
                cast("drp", _dv, 1.0)
                # 🔄 انعكاس الإرهاق: قمة اليوم (DRP≥88) + نمط/شمعة هبوط → بيع · والعكس عند القاع
                _cdl = votes.get("candles", 0); _sw = votes.get("swing_profile", 0)
                if _drp >= 88 and (_cdl < 0 or _sw < 0):
                    cast("exhaust", -1, 1.4)           # بيع إرهاق عند القمة (يعالج: ليش ما يبيع)
                elif _drp <= 12 and (_cdl > 0 or _sw > 0):
                    cast("exhaust", 1, 1.4)            # شراء إرهاق عند القاع
            _rs = _row.get("rs")
            if _rs is not None:                        # قوة نسبية مقطعية: قائد صاعد · متخلّف هابط
                cast("rstr", 1 if _rs >= 70 else -1 if _rs <= 30 else 0, 1.0)
            if _row.get("sob"):                        # انحياز افتتاح الجلسة (فوق/تحت افتتاح اليوم)
                cast("sopen", int(_row["sob"]), 1.0)
    except Exception:
        pass

    # ── ML indicator vote (ml_indicator.py) — صوت واحد، يوزنه _lf بدقّته المقيسة (يُدفن لو فشل) ──
    try:
        _mlf = r"C:\Users\Radhi\MT5\r_native_v2\data\ml_pred_" + symbol + "_" + tf + ".json"
        with open(_mlf, encoding="utf-8") as _f:
            _ml = json.loads(_f.read())
        if time.time() - float(_ml.get("ts", 0)) < 3600 and _ml.get("vote") is not None:
            cast("ml", int(_ml["vote"]), 1.5)
    except Exception:
        pass

    # ── NEWS vote (multi-source + Claude-curated) injected at HIGH weight ──────
    # weight = BASE × tier × conviction (Claude-curated tier=5×, calendar 3×, RSS 1.5×),
    # so a high-conviction curated read can outweigh the technical votes and flip `net`.
    # A news VETO is enforced upstream (multi_trader reads news_blocked_symbols.json); here
    # news only adds DIRECTIONAL conviction to the consolidated decision.
    try:
        import news_engine as _ne
        _nd, _nw, _nveto, _nrsn = _ne.news_vote(symbol)
        if _nd != 0 and _nw > 0:
            votes["news"] = int(_nd); weights["news"] = float(_nw)   # bypass _lf — already tier-weighted
    except Exception:
        pass

    net = sum(votes[k] * weights[k] for k in votes)
    direction = 1 if net > 0 else -1 if net < 0 else 0
    agree = sum(weights[k] for k in votes if direction != 0 and votes[k] == direction)
    total = sum(weights.values())
    confluence = round(agree / total, 3) if total > 0 else 0.0
    return {"symbol": symbol, "tf": tf, "price": round(price, 5),
            "dir": direction, "confluence": confluence, "net": round(net, 2),
            "regime": reg, "votes": votes, "weights": weights, "source": "local"}


def read(mt5, symbol: str, tf: str = "M15") -> dict | None:
    """Preferred entry: try the real chart (HTTP) first, fall back to local MT5 compute."""
    d = read_http(symbol, tf)
    if d is not None:
        return d
    return read_local(mt5, symbol, tf)


if __name__ == "__main__":
    import argparse, MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSDm")
    ap.add_argument("--tf", default="M15")
    a = ap.parse_args()
    mt5.initialize()
    print(json.dumps(read(mt5, a.symbol, a.tf), ensure_ascii=False, indent=2))
    mt5.shutdown()
