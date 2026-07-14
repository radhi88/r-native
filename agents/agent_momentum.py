# -*- coding: utf-8 -*-
"""
وكلاء فئة الزخم (momentum) — 10 وكلاء نقيّون لحظيّون.

العقد الموحّد لكل وكيل:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx قاموس جاهز فيه (كل الحقول اختياريّة — الوكيل دفاعيّ):
    sym            : اسم العملة (str)
    m1/m5/m15/h1   : dict فيه 'o'/'h'/'l'/'c'/'v' مصفوفات numpy (آخر ~200 شمعة)
    price, atr_m5, spread
    حقول النبض المباشرة: momentum (stoch_k/stoch_d/rsi9/trend_m1/trend_m5)،
    pattern_m1، pattern_m5، structure، smc (bos/choch/ob/fvg/liq_pools/sweeps/poc).

غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة"). لا استثناء أبداً.
لا مكتبات خارجيّة غير numpy. يجب أن يعمل 100 وكيل × 17 عملة في <100ms.
"""
import numpy as np

CATEGORY = "momentum"

# ───────────────────────── أدوات numpy نقيّة ─────────────────────────

def _frame(ctx, tf):
    """يُرجِع dict الفريم أو None."""
    if not isinstance(ctx, dict):
        return None
    f = ctx.get(tf)
    if not isinstance(f, dict):
        return None
    return f


def _arr(frame, key, minlen=1):
    """مصفوفة numpy float من الفريم، أو None إن قصُرت/غابت."""
    if not isinstance(frame, dict):
        return None
    a = frame.get(key)
    if a is None:
        return None
    try:
        v = np.asarray(a, dtype=np.float64).ravel()
    except Exception:
        return None
    if v.size < minlen or not np.all(np.isfinite(v)):
        # نُبقي القيم المتناهية فقط إن كان الطول كافياً
        v = v[np.isfinite(v)]
        if v.size < minlen:
            return None
    return v


def _closes(ctx, tf, minlen=1):
    return _arr(_frame(ctx, tf), "c", minlen)


def _clip01(x):
    try:
        return float(max(0.0, min(1.0, x)))
    except Exception:
        return 0.0


def _rsi(closes, period):
    """RSI ويلدر النقيّ. يُرجِع None إن قصُرت البيانات."""
    if closes is None or closes.size < period + 1:
        return None
    d = np.diff(closes)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    # متوسّط ويلدر الأوّليّ ثمّ التنعيم
    ag = gain[:period].mean()
    al = loss[:period].mean()
    for i in range(period, d.size):
        ag = (ag * (period - 1) + gain[i]) / period
        al = (al * (period - 1) + loss[i]) / period
    if al <= 1e-12:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return float(100.0 - 100.0 / (1.0 + rs))


def _ema(x, period):
    if x is None or x.size == 0:
        return None
    k = 2.0 / (period + 1.0)
    e = x[0]
    for v in x[1:]:
        e = v * k + e * (1.0 - k)
    return float(e)


def _ema_series(x, period):
    if x is None or x.size == 0:
        return None
    k = 2.0 / (period + 1.0)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, x.size):
        out[i] = x[i] * k + out[i - 1] * (1.0 - k)
    return out


def _macd(closes, fast=12, slow=26, signal=9):
    """يُرجِع (macd_line_series, signal_series, hist_series) أو None."""
    if closes is None or closes.size < slow + signal:
        return None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    if ef is None or es is None:
        return None
    macd_line = ef - es
    sig = _ema_series(macd_line, signal)
    if sig is None:
        return None
    hist = macd_line - sig
    return macd_line, sig, hist


def _stoch(h, l, c, k_period=14, d_period=3):
    """ستوكاستك %K/%D. يُرجِع (k, d) أو None."""
    n = k_period + d_period
    if c is None or h is None or l is None or c.size < n or h.size < n or l.size < n:
        return None
    m = min(c.size, h.size, l.size)
    h, l, c = h[-m:], l[-m:], c[-m:]
    ks = []
    for i in range(k_period - 1, m):
        hh = h[i - k_period + 1:i + 1].max()
        ll = l[i - k_period + 1:i + 1].min()
        rng = hh - ll
        ks.append(50.0 if rng <= 1e-12 else (c[i] - ll) / rng * 100.0)
    if len(ks) < d_period:
        return None
    ks = np.asarray(ks)
    k = float(ks[-1])
    d = float(ks[-d_period:].mean())
    return k, d


def _pulse_mom(ctx):
    m = ctx.get("momentum") if isinstance(ctx, dict) else None
    return m if isinstance(m, dict) else {}


# ───────────────────────── الوكلاء ─────────────────────────

def agent_rsi14_ob_os(ctx):
    """RSI14 m5: >70 بيع / <30 شراء (انعكاس)، الثقة = بُعد عن 50."""
    try:
        c = _closes(ctx, "m5", 15)
        r = _rsi(c, 14)
        if r is None:
            m = _pulse_mom(ctx)
            r = m.get("rsi9")  # بديل احتياطيّ من النبض
            if r is None:
                return (0, 0.0, "بيانات ناقصة")
            r = float(r)
        if r >= 70.0:
            return (-1, _clip01((r - 70.0) / 30.0 + 0.35), f"RSI14={r:.0f} تشبّع شرائيّ ⇒ انعكاس بيع")
        if r <= 30.0:
            return (1, _clip01((30.0 - r) / 30.0 + 0.35), f"RSI14={r:.0f} تشبّع بيعيّ ⇒ انعكاس شراء")
        return (0, _clip01(abs(r - 50.0) / 50.0 * 0.4), f"RSI14={r:.0f} حياد")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_rsi9_midcross(ctx):
    """اختراق RSI9 لمستوى 50 صعوداً/هبوطاً كإشارة زخم."""
    try:
        c = _closes(ctx, "m5", 12)
        if c is not None and c.size >= 12:
            r_now = _rsi(c, 9)
            r_prev = _rsi(c[:-1], 9)
        else:
            r_now = _pulse_mom(ctx).get("rsi9")
            r_prev = None
        if r_now is None:
            return (0, 0.0, "بيانات ناقصة")
        r_now = float(r_now)
        if r_prev is not None:
            if r_prev < 50.0 <= r_now:
                return (1, _clip01((r_now - 50.0) / 20.0 + 0.3), f"RSI9 اخترق 50 صعوداً ({r_now:.0f})")
            if r_prev > 50.0 >= r_now:
                return (-1, _clip01((50.0 - r_now) / 20.0 + 0.3), f"RSI9 اخترق 50 هبوطاً ({r_now:.0f})")
            return (0, 0.1, f"RSI9={r_now:.0f} لا اختراق")
        # بلا سابقة: نُصوّت بالجهة الحاليّة بثقة ضعيفة
        v = 1 if r_now > 50 else (-1 if r_now < 50 else 0)
        return (v, _clip01(abs(r_now - 50.0) / 50.0 * 0.3), f"RSI9={r_now:.0f} (نبض)")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_stoch_cross_m5(ctx):
    """تقاطع stoch_k/stoch_d من النبض: k>d=+1، مع تصفية التشبع."""
    try:
        m = _pulse_mom(ctx)
        k = m.get("stoch_k")
        d = m.get("stoch_d")
        if k is None or d is None:
            st = _stoch(_arr(_frame(ctx, "m5"), "h", 17),
                        _arr(_frame(ctx, "m5"), "l", 17),
                        _closes(ctx, "m5", 17))
            if st is None:
                return (0, 0.0, "بيانات ناقصة")
            k, d = st
        k = float(k); d = float(d)
        gap = k - d
        if abs(gap) < 1e-6:
            return (0, 0.05, "ستوكاستك متعادل")
        # تصفية: تقاطع من منطقة تشبّع أقوى
        if gap > 0:
            boost = 0.25 if k < 30 else 0.0  # خروج من التشبع البيعيّ
            return (1, _clip01(min(gap / 30.0, 1.0) * 0.6 + 0.2 + boost), f"K>{d:.0f} (K={k:.0f})")
        boost = 0.25 if k > 70 else 0.0
        return (-1, _clip01(min(-gap / 30.0, 1.0) * 0.6 + 0.2 + boost), f"K<{d:.0f} (K={k:.0f})")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_roc_10_m5(ctx):
    """معدّل التغيّر 10 شموع m5 معاير بـ ATR؛ إشارته وفق دفع الزخم."""
    try:
        c = _closes(ctx, "m5", 11)
        if c is None:
            return (0, 0.0, "بيانات ناقصة")
        roc = c[-1] - c[-11]
        atr = ctx.get("atr_m5") or 0.0
        try:
            atr = float(atr)
        except Exception:
            atr = 0.0
        denom = atr if atr > 1e-9 else (abs(c[-11]) * 1e-4 + 1e-9)
        z = roc / denom
        if abs(z) < 0.4:
            return (0, _clip01(abs(z) * 0.3), f"ROC10≈0 (z={z:.2f})")
        v = 1 if z > 0 else -1
        return (v, _clip01(min(abs(z) / 3.0, 1.0) * 0.7 + 0.15), f"ROC10 z={z:.2f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_macd_hist_m15(ctx):
    """هيستوغرام MACD(12,26,9) على m15: موجب متزايد=+1."""
    try:
        c = _closes(ctx, "m15", 40)
        if c is None:
            c = _closes(ctx, "m5", 40)  # بديل احتياطيّ لو غاب m15
            if c is None:
                return (0, 0.0, "بيانات ناقصة")
        m = _macd(c)
        if m is None:
            return (0, 0.0, "بيانات ناقصة")
        _, _, hist = m
        if hist.size < 2:
            return (0, 0.0, "بيانات ناقصة")
        h_now, h_prev = float(hist[-1]), float(hist[-2])
        rising = h_now > h_prev
        atr = float(ctx.get("atr_m5") or 0.0)
        scale = atr if atr > 1e-9 else (abs(c[-1]) * 1e-4 + 1e-9)
        mag = _clip01(abs(h_now) / (scale * 2.0))
        if h_now > 0 and rising:
            return (1, _clip01(mag * 0.6 + 0.3), "هيستوغرام MACD موجب ومتزايد")
        if h_now < 0 and not rising:
            return (-1, _clip01(mag * 0.6 + 0.3), "هيستوغرام MACD سالب ومتناقص")
        # اتّجاه دون تسارع ⇒ إشارة أضعف
        v = 1 if h_now > 0 else (-1 if h_now < 0 else 0)
        return (v, _clip01(mag * 0.3), "هيستوغرام MACD بلا تسارع")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_macd_signal_cross_m5(ctx):
    """تقاطع خط MACD مع الإشارة على m5 كزخم أسرع."""
    try:
        c = _closes(ctx, "m5", 40)
        if c is None:
            return (0, 0.0, "بيانات ناقصة")
        m = _macd(c)
        if m is None:
            return (0, 0.0, "بيانات ناقصة")
        line, sig, _ = m
        if line.size < 2:
            return (0, 0.0, "بيانات ناقصة")
        d_now = line[-1] - sig[-1]
        d_prev = line[-2] - sig[-2]
        atr = float(ctx.get("atr_m5") or 0.0)
        scale = atr if atr > 1e-9 else (abs(c[-1]) * 1e-4 + 1e-9)
        if d_prev <= 0 < d_now:
            return (1, _clip01(abs(d_now) / scale * 0.5 + 0.35), "تقاطع MACD صاعد")
        if d_prev >= 0 > d_now:
            return (-1, _clip01(abs(d_now) / scale * 0.5 + 0.35), "تقاطع MACD هابط")
        v = 1 if d_now > 0 else (-1 if d_now < 0 else 0)
        return (v, _clip01(abs(d_now) / scale * 0.25), "MACD بلا تقاطع")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_cci_20_m5(ctx):
    """CCI20 m5: خروج من +100/-100 كزخم اندفاعيّ مؤكَّد."""
    try:
        f = _frame(ctx, "m5")
        h = _arr(f, "h", 21); l = _arr(f, "l", 21); c = _arr(f, "c", 21)
        if h is None or l is None or c is None:
            return (0, 0.0, "بيانات ناقصة")
        m = min(h.size, l.size, c.size)
        h, l, c = h[-m:], l[-m:], c[-m:]
        tp = (h + l + c) / 3.0
        tp20 = tp[-20:]
        sma = tp20.mean()
        md = np.mean(np.abs(tp20 - sma))
        if md <= 1e-12:
            return (0, 0.05, "CCI غير معرّف")
        cci = (tp[-1] - sma) / (0.015 * md)
        cci_prev_tp = tp[-21:-1] if tp.size >= 21 else None
        if cci > 100.0:
            return (1, _clip01((cci - 100.0) / 200.0 + 0.35), f"CCI={cci:.0f} اندفاع صاعد")
        if cci < -100.0:
            return (-1, _clip01((-cci - 100.0) / 200.0 + 0.35), f"CCI={cci:.0f} اندفاع هابط")
        return (0, _clip01(abs(cci) / 100.0 * 0.3), f"CCI={cci:.0f} داخل النطاق")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_williams_r_m5(ctx):
    """Williams %R m5 لكشف تشبّع الزخم القصير والانعكاس."""
    try:
        f = _frame(ctx, "m5")
        h = _arr(f, "h", 14); l = _arr(f, "l", 14); c = _closes(ctx, "m5", 14)
        if h is None or l is None or c is None:
            return (0, 0.0, "بيانات ناقصة")
        m = min(h.size, l.size, c.size)
        hh = h[-14:].max(); ll = l[-14:].min()
        rng = hh - ll
        if rng <= 1e-12:
            return (0, 0.05, "%R غير معرّف")
        wr = -100.0 * (hh - c[-1]) / rng   # [-100..0]
        if wr <= -80.0:  # تشبّع بيعيّ ⇒ انعكاس شراء
            return (1, _clip01((-80.0 - wr) / 20.0 + 0.3), f"%R={wr:.0f} تشبّع بيعيّ")
        if wr >= -20.0:  # تشبّع شرائيّ ⇒ انعكاس بيع
            return (-1, _clip01((wr + 20.0) / 20.0 + 0.3), f"%R={wr:.0f} تشبّع شرائيّ")
        return (0, _clip01(abs(wr + 50.0) / 50.0 * 0.25), f"%R={wr:.0f} حياد")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_momentum_burst_z(ctx):
    """زخم السعر معايراً بـ atr_m5 (تحرّك>1.5×ATR) في اتجاه واحد."""
    try:
        c = _closes(ctx, "m5", 4)
        if c is None:
            return (0, 0.0, "بيانات ناقصة")
        move = c[-1] - c[-4]  # تحرّك 3 شموع
        atr = float(ctx.get("atr_m5") or 0.0)
        if atr <= 1e-9:
            f = _frame(ctx, "m5")
            h = _arr(f, "h", 4); l = _arr(f, "l", 4)
            if h is not None and l is not None:
                atr = float(np.mean(h[-3:] - l[-3:]))
        if atr <= 1e-9:
            return (0, 0.0, "بيانات ناقصة")
        z = move / atr
        if abs(z) < 1.5:
            return (0, _clip01(abs(z) / 1.5 * 0.25), f"لا انفجار (z={z:.2f})")
        v = 1 if z > 0 else -1
        return (v, _clip01((abs(z) - 1.5) / 2.5 * 0.6 + 0.3), f"انفجار زخم z={z:.2f}×ATR")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_rsi_divergence_m5(ctx):
    """تباعد RSI14 مقابل السعر (قاع أدنى/RSI أعلى) كإنذار انعكاس مبكّر."""
    try:
        c = _closes(ctx, "m5", 30)
        if c is None:
            return (0, 0.0, "بيانات ناقصة")
        n = c.size
        half = min(10, n // 2)
        if half < 4:
            return (0, 0.0, "بيانات ناقصة")
        recent = c[-half:]
        prior = c[-2 * half:-half]
        # RSI متدرّج على نافذتين
        r_recent = _rsi(c[-(half + 14):], 14)
        r_prior = _rsi(c[-(2 * half + 14):-half] if n >= 2 * half + 14 else c[:-half], 14)
        if r_recent is None or r_prior is None:
            return (0, 0.0, "بيانات ناقصة")
        p_low_r, p_low_p = recent.min(), prior.min()
        p_high_r, p_high_p = recent.max(), prior.max()
        # تباعد صعوديّ: قاع أدنى في السعر لكن RSI أعلى
        if p_low_r < p_low_p and r_recent > r_prior + 3.0:
            return (1, _clip01((r_recent - r_prior) / 20.0 * 0.5 + 0.3), "تباعد صعوديّ RSI/سعر")
        # تباعد هبوطيّ: قمّة أعلى في السعر لكن RSI أدنى
        if p_high_r > p_high_p and r_recent < r_prior - 3.0:
            return (-1, _clip01((r_prior - r_recent) / 20.0 * 0.5 + 0.3), "تباعد هبوطيّ RSI/سعر")
        return (0, 0.1, "لا تباعد")
    except Exception:
        return (0, 0.0, "ناقص")


# ───────────────────────── السجلّ ─────────────────────────
AGENTS = [
    ("rsi14_ob_os",          CATEGORY, agent_rsi14_ob_os,          1.0),
    ("rsi9_midcross",        CATEGORY, agent_rsi9_midcross,        1.0),
    ("stoch_cross_m5",       CATEGORY, agent_stoch_cross_m5,       1.0),
    ("roc_10_m5",            CATEGORY, agent_roc_10_m5,            1.0),
    ("macd_hist_m15",        CATEGORY, agent_macd_hist_m15,        1.0),
    ("macd_signal_cross_m5", CATEGORY, agent_macd_signal_cross_m5, 1.0),
    ("cci_20_m5",            CATEGORY, agent_cci_20_m5,            1.0),
    ("williams_r_m5",        CATEGORY, agent_williams_r_m5,        1.0),
    ("momentum_burst_z",     CATEGORY, agent_momentum_burst_z,     1.0),
    ("rsi_divergence_m5",    CATEGORY, agent_rsi_divergence_m5,    1.0),
]
