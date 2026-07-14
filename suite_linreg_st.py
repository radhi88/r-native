# -*- coding: utf-8 -*-
"""
suite_linreg_st — نقل أمين لحزمة راضي على Pine v6: «LinReg + Supertrend»
=========================================================================
هذه الوحدة مؤشر صافٍ (numpy فقط — لا استيراد MetaTrader5، لا كتابة ملفات)
تنقل منطق حزمة TradingView التي جمعها راضي بنفسه:

  1) الانحدار الخطي ta.linreg(close, 11, 0) + إشارة SMA(7) فوقه
  2) RSI(14) بطريقة وايلدر مقابل متوسطه SMA(14)
  3) VWAP جلسي (يُصفَّر عند حدود يوم الشمعة)
  4) Supertrend(7, 0.7) الكلاسيكي مع عمر الانعكاس وتبريد 8 شموع
  5) هيكل القمم/القيعان عبر Pivots(20,20): ‏HH+HL أو LH+LL

ملاحظة الصدق: كل مؤشر من هذه المؤشرات قِيس منفردًا في هذا المشروع فخرج
~عملة متوازنة (coin-flip، لا أفضلية). فرضية القيمة الوحيدة هنا هي التقاطع
الخماسي الصارم — أن تتفق الطبقات الخمس معًا لحظة انعكاس Supertrend طازج.
لوحة النتائج (scoreboard) هي الحَكم النهائي، لا هذا الملف.
"""
from __future__ import annotations

import numpy as np

DEFAULTS = {
    "linreg_len": 11,
    "signal_len": 7,
    "sma_signal": True,
    "rsi_len": 14,
    "rsi_sma_len": 14,
    "st_atr_len": 7,
    "st_mult": 0.7,
    "st_cooldown": 8,
    "zigzag_len": 20,
    "fresh_bars": 8,
}

_SECONDS_PER_DAY = 86400


def _field(row, *keys):
    """duck-type: dict أو np.void أو كائن بخصائص."""
    for k in keys:
        try:
            return row[k]
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        if hasattr(row, k):
            return getattr(row, k)
    raise KeyError(keys[0])


def _extract(rates):
    """يقبل numpy structured array (mt5.copy_rates_from_pos) أو قائمة dicts."""
    if rates is None:
        raise ValueError("rates is None")
    if hasattr(rates, "dtype") and getattr(rates.dtype, "names", None):
        names = rates.dtype.names
        vkey = next((k for k in ("tick_volume", "volume", "real_volume") if k in names), None)
        if vkey is None:
            raise KeyError("volume")
        c = lambda k: np.asarray(rates[k], dtype=float)  # noqa: E731
        return c("open"), c("high"), c("low"), c("close"), c(vkey), c("time")
    rows = list(rates)
    o = np.array([float(_field(r, "open")) for r in rows])
    h = np.array([float(_field(r, "high")) for r in rows])
    l = np.array([float(_field(r, "low")) for r in rows])
    cl = np.array([float(_field(r, "close")) for r in rows])
    v = np.array([float(_field(r, "volume", "tick_volume", "real_volume")) for r in rows])
    t = []
    for r in rows:
        x = _field(r, "time", "datetime")
        t.append(float(x.timestamp()) if hasattr(x, "timestamp") else float(x))
    return o, h, l, cl, v, np.array(t)


def _linreg_series(close, length, count):
    """قيمة خط المربعات الصغرى عند آخر شمعة لكل نافذة — يعادل ta.linreg(close, L, 0)."""
    n = close.size
    count = min(count, n - length + 1)
    x = np.arange(length, dtype=float)
    sx, sxx = x.sum(), (x * x).sum()
    denom = length * sxx - sx * sx
    out = np.empty(count)
    for j in range(count):
        end = n - count + 1 + j
        y = close[end - length:end]
        sy, sxy = y.sum(), (x * y).sum()
        slope = (length * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / length
        out[j] = intercept + slope * (length - 1)
    return out


def _rsi_series(close, length):
    """RSI وايلدر القياسي؛ العنصر i يقابل الشمعة i+1."""
    d = np.diff(close)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    m = d.size
    rsi = np.full(m, np.nan)
    if m < length:
        return rsi
    ag, al = gain[:length].mean(), loss[:length].mean()
    for i in range(length - 1, m):
        if i >= length:
            ag = (ag * (length - 1) + gain[i]) / length
            al = (al * (length - 1) + loss[i]) / length
        rsi[i] = 100.0 if al <= 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


def _atr_rma(h, l, c, length):
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.full(c.size, np.nan)
    a = tr[:length].mean()
    for i in range(length - 1, c.size):
        if i >= length:
            a = (a * (length - 1) + tr[i]) / length
        atr[i] = a
    return atr


def _supertrend(h, l, c, atr_len, mult):
    """الخوارزمية الكلاسيكية؛ dirs: 1=صاعد (يوازي dir<0 في Pine)، -1=هابط."""
    n = c.size
    atr = _atr_rma(h, l, c, atr_len)
    hl2 = (h + l) / 2.0
    ub, lb = hl2 + mult * atr, hl2 - mult * atr
    fu, fl = ub.copy(), lb.copy()
    st = np.full(n, np.nan)
    dirs = np.zeros(n, dtype=int)
    start = atr_len - 1
    dirs[start], st[start] = 1, fl[start]
    for i in range(start + 1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if dirs[i - 1] == 1:
            dirs[i] = 1 if c[i] >= fl[i] else -1
        else:
            dirs[i] = -1 if c[i] <= fu[i] else 1
        st[i] = fl[i] if dirs[i] == 1 else fu[i]
    return st, dirs, start


def _pivots(src, span, is_high):
    """pivothigh/low(src, span, span) بمقارنة صارمة على النافذتين."""
    out = []
    for i in range(span, src.size - span):
        left, right, v = src[i - span:i], src[i + 1:i + span + 1], src[i]
        if is_high:
            if v > left.max() and v > right.max():
                out.append((i, float(v)))
        elif v < left.min() and v < right.min():
            out.append((i, float(v)))
    return out


def _session_vwap(h, l, c, v, t):
    day = (t.astype("int64") // _SECONDS_PER_DAY)
    m = day == day[-1]
    tp, vol = (h[m] + l[m] + c[m]) / 3.0, v[m]
    denom = vol.sum()
    return float(tp.mean()) if denom <= 0 else float((tp * vol).sum() / denom)


def evaluate(rates, cfg=None):
    conf = dict(DEFAULTS)
    if cfg:
        conf.update(cfg)
    try:
        _o, h, l, c, v, t = _extract(rates)
    except Exception as exc:  # حدود النظام: مدخلات غير صالحة
        return {"setup": None, "error": f"bad rates: {exc}"}
    n = c.size
    zz = int(conf["zigzag_len"])
    if n < max(60, zz * 2 + 2):
        return {"setup": None, "error": "insufficient bars"}

    # 1+2) linreg + إشارة SMA
    lr = _linreg_series(c, int(conf["linreg_len"]), 40)
    sig_len = int(conf["signal_len"])
    sig = np.convolve(lr, np.ones(sig_len) / sig_len, mode="valid") if conf.get("sma_signal", True) else lr
    signal_rising = bool(sig[-1] > sig[-2])
    signal_falling = bool(sig[-1] < sig[-2])

    # 3) RSI مقابل متوسطه (يعادل مزلاج آخر تقاطع)
    rsi = _rsi_series(c, int(conf["rsi_len"]))
    rsi_ok = rsi[~np.isnan(rsi)]
    rsi_sma = rsi_ok[-int(conf["rsi_sma_len"]):].mean()
    rsi_bull = bool(rsi_ok[-1] > rsi_sma)
    rsi_bear = bool(rsi_ok[-1] < rsi_sma)

    # 4) VWAP جلسي
    vwap = _session_vwap(h, l, c, v, t)
    above_vwap, below_vwap = bool(c[-1] > vwap), bool(c[-1] < vwap)

    # 5) Supertrend + عمر الانعكاس + تبريد الإشارات المتشابهة الاتجاه
    st_line, dirs, st_start = _supertrend(h, l, c, int(conf["st_atr_len"]), float(conf["st_mult"]))
    flips = [i for i in range(st_start + 1, n) if dirs[i] != dirs[i - 1]]
    st_dir = int(dirs[-1])
    flip_age = int(n - 1 - flips[-1]) if flips else None
    cooled = len(flips) >= 3 and (flips[-1] - flips[-3]) < int(conf["st_cooldown"])
    fresh = flip_age is not None and flip_age <= int(conf["fresh_bars"]) and not cooled
    st_fresh_bull = st_dir == 1 and fresh
    st_fresh_bear = st_dir == -1 and fresh

    # 6) هيكل HH/HL مقابل LH/LL عبر Pivots المؤكدة
    ph, pl = _pivots(h, zz, True), _pivots(l, zz, False)
    structure, struct_bull, struct_bear = None, False, False
    if len(ph) >= 2 and len(pl) >= 2:
        hh, hl = ph[-1][1] > ph[-2][1], pl[-1][1] > pl[-2][1]
        if hh and hl:
            structure, struct_bull = "HH+HL", True
        elif not hh and not hl:
            structure, struct_bear = "LH+LL", True
        else:
            structure = "mixed"

    # 7) التقاطع الخماسي + العدّاد
    bull_n = sum([signal_rising, rsi_bull, above_vwap, st_dir == 1, struct_bull])
    bear_n = sum([signal_falling, rsi_bear, below_vwap, st_dir == -1, struct_bear])
    setup = None
    if rsi_bull and signal_rising and above_vwap and st_fresh_bull and struct_bull:
        setup = "bullish"
    elif rsi_bear and signal_falling and below_vwap and st_fresh_bear and struct_bear:
        setup = "bearish"

    return {
        "setup": setup,
        "components": {
            "linreg_rising": signal_rising,
            "rsi_bull": rsi_bull,
            "above_vwap": above_vwap,
            "st_dir": st_dir,
            "st_flip_age": flip_age,
            "structure": structure,
        },
        "score": int(max(bull_n, bear_n)),
        "vwap": float(vwap),
        "supertrend": float(st_line[-1]),
        "signal": float(sig[-1]),
    }


def _synth(n=400, up=True):
    """اتجاه نظيف: انجراف + جيب (دورة 80 شمعة) بفواصل ساعة."""
    i = np.arange(n, dtype=float)
    base = 100.0 + 0.04 * i + 1.5 * np.sin(2.0 * np.pi * i / 80.0)
    if not up:
        base = 300.0 - base
    close = base
    open_ = np.concatenate(([base[0]], base[:-1]))
    high = np.maximum(open_, close) + 0.3
    low = np.minimum(open_, close) - 0.3
    vol = 1050.0 + 200.0 * np.sin(2.0 * np.pi * i / 37.0)
    times = 1_750_000_000.0 + i * 3600.0
    return [
        {"open": open_[k], "high": high[k], "low": low[k], "close": close[k],
         "volume": vol[k], "time": times[k]}
        for k in range(n)
    ]


def _bull_count(comp):
    return sum([comp["linreg_rising"], comp["rsi_bull"], comp["above_vwap"],
                comp["st_dir"] == 1, comp["structure"] == "HH+HL"])


def _bear_count(comp):
    return sum([not comp["linreg_rising"], not comp["rsi_bull"], not comp["above_vwap"],
                comp["st_dir"] == -1, comp["structure"] == "LH+LL"])


if __name__ == "__main__":
    up_bars = _synth(up=True)
    res_up = evaluate(up_bars)
    assert "error" not in res_up, res_up
    assert _bull_count(res_up["components"]) >= 4, res_up
    assert res_up["score"] >= 4, res_up

    res_dn = evaluate(_synth(up=False))
    assert "error" not in res_dn, res_dn
    assert _bear_count(res_dn["components"]) >= 4, res_dn
    assert res_dn["score"] >= 4, res_dn

    # مسار structured array (شكل mt5.copy_rates_from_pos)
    dt = np.dtype([("time", "f8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                   ("close", "f8"), ("tick_volume", "f8")])
    arr = np.array([(b["time"], b["open"], b["high"], b["low"], b["close"], b["volume"])
                    for b in up_bars], dtype=dt)
    res_arr = evaluate(arr)
    assert res_arr["components"] == res_up["components"], (res_arr, res_up)

    res_short = evaluate(up_bars[:40])
    assert res_short["setup"] is None and res_short.get("error") == "insufficient bars", res_short
    print("OK", {"up_score": res_up["score"], "down_score": res_dn["score"],
                 "up_st_dir": res_up["components"]["st_dir"],
                 "down_st_dir": res_dn["components"]["st_dir"]})
