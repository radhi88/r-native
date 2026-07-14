# -*- coding: utf-8 -*-
"""
agent_trend.py — 10 وكلاء ترند نقيّون لحظيّون (بلا LLM).

العقد الموحّد لكل وكيل:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx قاموس جاهز فيه على الأقل:
    ctx['sym']                       اسم العملة
    ctx['m1'|'m5'|'m15'|'h1']        قاموس {'o','h','l','c','v'} مصفوفات numpy (~200 شمعة)
    ctx['price'], ctx['atr_m5'], ctx['spread']
    ctx['smc']                       حقول SMC من market_pulse (bos/choch/ob/fvg/liq/sweeps/poc/trend_m1/trend_m5)

مبدأ الدفاع: أيّ نقص بيانات أو استثناء ⇒ (0, 0.0, "ناقص"). لا نكسر أبداً.
"""
import numpy as np

# ───────────────────────── أدوات نقيّة (numpy فقط) ─────────────────────────


def _arr(ctx, tf, field):
    """يُرجِع مصفوفة numpy 1D للحقل المطلوب أو None عند الغياب."""
    try:
        d = ctx.get(tf)
        if d is None:
            return None
        a = d.get(field)
        if a is None:
            return None
        a = np.asarray(a, dtype=float).ravel()
        if a.size == 0 or not np.all(np.isfinite(a[-1:])):
            return None
        return a
    except Exception:
        return None


def _ema(a, period):
    """EMA بسيط بلا مكتبات؛ يُرجِع مصفوفة بنفس طول a أو None."""
    try:
        if a is None or a.size < period:
            return None
        k = 2.0 / (period + 1.0)
        out = np.empty(a.size, dtype=float)
        out[0] = a[0]
        for i in range(1, a.size):
            out[i] = a[i] * k + out[i - 1] * (1.0 - k)
        return out
    except Exception:
        return None


def _atr(ctx, tf='m5', period=14):
    """ATR تقريبي من o/h/l/c، أو fallback على ctx['atr_m5']."""
    try:
        h = _arr(ctx, tf, 'h')
        l = _arr(ctx, tf, 'l')
        c = _arr(ctx, tf, 'c')
        if h is None or l is None or c is None:
            v = ctx.get('atr_m5')
            return float(v) if v else None
        n = min(h.size, l.size, c.size)
        if n < period + 1:
            v = ctx.get('atr_m5')
            return float(v) if v else None
        h, l, c = h[-n:], l[-n:], c[-n:]
        pc = c[:-1]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
        if tr.size < period:
            return float(np.mean(tr)) if tr.size else None
        return float(np.mean(tr[-period:]))
    except Exception:
        v = ctx.get('atr_m5')
        return float(v) if v else None


def _clip(x, lo=0.0, hi=1.0):
    return float(max(lo, min(hi, x)))


def _smc(ctx):
    s = ctx.get('smc')
    return s if isinstance(s, dict) else {}


# ─────────────────────────── الوكلاء العشرة ────────────────────────────────


def agent_ema_cross_5_13(ctx):
    """تقاطع EMA5/EMA13 على m5: فوق=+1، تحت=-1، الثقة من الفجوة/atr."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 14:
            return (0, 0.0, "ناقص")
        e5, e13 = _ema(c, 5), _ema(c, 13)
        if e5 is None or e13 is None:
            return (0, 0.0, "ناقص")
        gap = e5[-1] - e13[-1]
        atr = _atr(ctx) or (abs(gap) + 1e-9)
        conf = _clip(abs(gap) / (atr + 1e-12))
        if gap > 0:
            return (1, conf, f"EMA5>EMA13 m5 فجوة={gap:.5g}")
        if gap < 0:
            return (-1, conf, f"EMA5<EMA13 m5 فجوة={gap:.5g}")
        return (0, 0.0, "تساوٍ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_ema_cross_9_21(ctx):
    """تقاطع EMA9/EMA21 على m5 — الزاوية الكلاسيكية للترند القصير."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 22:
            return (0, 0.0, "ناقص")
        e9, e21 = _ema(c, 9), _ema(c, 21)
        if e9 is None or e21 is None:
            return (0, 0.0, "ناقص")
        gap = e9[-1] - e21[-1]
        atr = _atr(ctx) or (abs(gap) + 1e-9)
        conf = _clip(abs(gap) / (atr + 1e-12))
        if gap > 0:
            return (1, conf, f"EMA9>EMA21 m5 فجوة={gap:.5g}")
        if gap < 0:
            return (-1, conf, f"EMA9<EMA21 m5 فجوة={gap:.5g}")
        return (0, 0.0, "تساوٍ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_ema_cross_21_55(ctx):
    """تقاطع EMA21/EMA55 على m15 لترند متوسط الأمد."""
    try:
        c = _arr(ctx, 'm15', 'c')
        if c is None or c.size < 56:
            return (0, 0.0, "ناقص")
        e21, e55 = _ema(c, 21), _ema(c, 55)
        if e21 is None or e55 is None:
            return (0, 0.0, "ناقص")
        gap = e21[-1] - e55[-1]
        atr = _atr(ctx, 'm15') or (abs(gap) + 1e-9)
        conf = _clip(abs(gap) / (atr + 1e-12))
        if gap > 0:
            return (1, conf, f"EMA21>EMA55 m15 فجوة={gap:.5g}")
        if gap < 0:
            return (-1, conf, f"EMA21<EMA55 m15 فجوة={gap:.5g}")
        return (0, 0.0, "تساوٍ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_ema_slope_h1(ctx):
    """ميل EMA50 على h1 (فرق آخر شمعتين) — اتجاه الفريم الأعلى."""
    try:
        c = _arr(ctx, 'h1', 'c')
        if c is None or c.size < 52:
            return (0, 0.0, "ناقص")
        e50 = _ema(c, 50)
        if e50 is None:
            return (0, 0.0, "ناقص")
        slope = e50[-1] - e50[-2]
        atr = _atr(ctx, 'h1') or (abs(slope) + 1e-9)
        conf = _clip(abs(slope) / (atr * 0.25 + 1e-12))
        if slope > 0:
            return (1, conf, f"ميل EMA50 h1 صاعد={slope:.5g}")
        if slope < 0:
            return (-1, conf, f"ميل EMA50 h1 هابط={slope:.5g}")
        return (0, 0.0, "مسطّح")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_price_vs_ema200_m15(ctx):
    """موقع السعر فوق/تحت EMA200 على m15 كفلتر ترند رئيسي."""
    try:
        c = _arr(ctx, 'm15', 'c')
        if c is None:
            return (0, 0.0, "ناقص")
        # EMA200 يتطلب عمقاً؛ إن قصُر، نستخدم أطول EMA ممكن (>=50)
        per = 200 if c.size >= 200 else (c.size - 1 if c.size > 50 else 0)
        if per < 50:
            return (0, 0.0, "ناقص")
        e = _ema(c, per)
        if e is None:
            return (0, 0.0, "ناقص")
        px = ctx.get('price') or c[-1]
        dist = px - e[-1]
        atr = _atr(ctx, 'm15') or (abs(dist) + 1e-9)
        conf = _clip(abs(dist) / (atr * 2.0 + 1e-12))
        tag = f"EMA{per}"
        if dist > 0:
            return (1, conf, f"سعر فوق {tag} m15")
        if dist < 0:
            return (-1, conf, f"سعر تحت {tag} m15")
        return (0, 0.0, "على الخطّ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_triple_ema_stack_m5(ctx):
    """ترتيب EMA8>21>55 (أو العكس) على m5 = ترند نظيف مكدّس."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 56:
            return (0, 0.0, "ناقص")
        e8, e21, e55 = _ema(c, 8), _ema(c, 21), _ema(c, 55)
        if e8 is None or e21 is None or e55 is None:
            return (0, 0.0, "ناقص")
        a, b, d = e8[-1], e21[-1], e55[-1]
        atr = _atr(ctx) or 1e-9
        spread = abs(a - d) / (atr + 1e-12)
        conf = _clip(spread * 0.5)
        if a > b > d:
            return (1, conf, "مكدّس صاعد EMA8>21>55 m5")
        if a < b < d:
            return (-1, conf, "مكدّس هابط EMA8<21<55 m5")
        return (0, 0.0, "غير مكدّس")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_adx_di_m15(ctx):
    """اتجاه +DI/-DI مع ADX14>20 على m15؛ يصوّت فقط حين قوّة الترند كافية."""
    try:
        h = _arr(ctx, 'm15', 'h')
        l = _arr(ctx, 'm15', 'l')
        c = _arr(ctx, 'm15', 'c')
        if h is None or l is None or c is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, c.size)
        if n < 30:
            return (0, 0.0, "ناقص")
        h, l, c = h[-n:], l[-n:], c[-n:]
        up = h[1:] - h[:-1]
        dn = l[:-1] - l[1:]
        plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
        minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
        pc = c[:-1]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
        p = 14
        if tr.size < p:
            return (0, 0.0, "ناقص")
        atr = np.mean(tr[-p:]) + 1e-12
        pdi = 100.0 * np.mean(plus_dm[-p:]) / atr
        mdi = 100.0 * np.mean(minus_dm[-p:]) / atr
        denom = pdi + mdi + 1e-12
        dx = 100.0 * abs(pdi - mdi) / denom
        # ADX ~ تنعيم dx عبر النافذة (تقريب بسيط)
        adx = dx
        if adx < 20.0:
            return (0, _clip(adx / 40.0) * 0.3, f"ADX ضعيف={adx:.0f}")
        conf = _clip((adx - 20.0) / 30.0)
        if pdi > mdi:
            return (1, conf, f"+DI>-DI ADX={adx:.0f} m15")
        if mdi > pdi:
            return (-1, conf, f"-DI>+DI ADX={adx:.0f} m15")
        return (0, 0.0, "DI متعادل")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_hh_hl_counter(ctx):
    """عدّ القمم/القيعان الصاعدة مقابل الهابطة في آخر 30 شمعة m5."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        if h is None or l is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, 31)
        if n < 10:
            return (0, 0.0, "ناقص")
        h, l = h[-n:], l[-n:]
        # كسور محلّية (fractal 3-شمعات)
        up_score = 0
        dn_score = 0
        for i in range(1, n - 1):
            if h[i] > h[i - 1] and h[i] > h[i + 1]:  # قمّة محلّية
                # هل هي أعلى من آخر قمّة؟ نقارن بالمتوسط المتحرّك للقمم
                up_score += 1 if h[i] >= np.max(h[max(0, i - 5):i] if i > 0 else h[:1]) else 0
            if l[i] < l[i - 1] and l[i] < l[i + 1]:
                dn_score += 1 if l[i] <= np.min(l[max(0, i - 5):i] if i > 0 else l[:1]) else 0
        # بديل أبسط وأدقّ: ميل خطّ أعلى القمم وأدنى القيعان
        half = n // 2
        hh = np.max(h[half:]) - np.max(h[:half])
        ll = np.min(l[half:]) - np.min(l[:half])
        rng = (np.max(h) - np.min(l)) + 1e-12
        score = (hh + ll) / rng  # موجب=هيكل صاعد
        conf = _clip(abs(score) * 1.5)
        if score > 0.05:
            return (1, conf, "قمم/قيعان صاعدة (HH+HL) m5")
        if score < -0.05:
            return (-1, conf, "قمم/قيعان هابطة (LH+LL) m5")
        return (0, 0.0, "هيكل عرضيّ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_supertrend_m5(ctx):
    """خطّ Supertrend (atr×3) على m5: فوقه=+1 تحته=-1."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        c = _arr(ctx, 'm5', 'c')
        if h is None or l is None or c is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, c.size)
        if n < 20:
            return (0, 0.0, "ناقص")
        h, l, c = h[-n:], l[-n:], c[-n:]
        atr = _atr(ctx) or 1e-9
        hl2 = (h + l) / 2.0
        mult = 3.0
        upper = hl2 + mult * atr
        lower = hl2 - mult * atr
        px = ctx.get('price') or c[-1]
        # اتجاه بسيط: السعر مقابل خطّ السفلي/العلوي الحالي
        if px > lower[-1] and c[-1] > c[-2]:
            conf = _clip((px - lower[-1]) / (mult * atr + 1e-12))
            return (1, conf, "فوق Supertrend m5")
        if px < upper[-1] and c[-1] < c[-2]:
            conf = _clip((upper[-1] - px) / (mult * atr + 1e-12))
            return (-1, conf, "تحت Supertrend m5")
        return (0, 0.0, "داخل النطاق")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_trend_agreement_mtf(ctx):
    """توافق trend_m1/trend_m5 (من النبض) مع ميل h1؛ يصوّت حين تتحاذى الأفرمة."""
    try:
        smc = _smc(ctx)
        t1 = smc.get('trend_m1')
        t5 = smc.get('trend_m5')
        # fallback: احسب من الإغلاقات إن غابت
        if t1 is None:
            c1 = _arr(ctx, 'm1', 'c')
            t1 = int(np.sign(c1[-1] - c1[-5])) if c1 is not None and c1.size >= 5 else 0
        if t5 is None:
            c5 = _arr(ctx, 'm5', 'c')
            t5 = int(np.sign(c5[-1] - c5[-5])) if c5 is not None and c5.size >= 5 else 0
        ch1 = _arr(ctx, 'h1', 'c')
        th1 = int(np.sign(ch1[-1] - ch1[-3])) if ch1 is not None and ch1.size >= 3 else 0
        s = int(t1) + int(t5) + th1
        agree = abs(s)
        if agree == 0:
            return (0, 0.0, "تضارب فريمات")
        conf = _clip(agree / 3.0)
        if s > 0:
            return (1, conf, f"توافق صاعد m1/m5/h1 ({agree}/3)")
        return (-1, conf, f"توافق هابط m1/m5/h1 ({agree}/3)")
    except Exception:
        return (0, 0.0, "ناقص")


# ────────────────────────────── السجلّ ─────────────────────────────────────
AGENTS = [
    ("ema_cross_5_13",      "trend", agent_ema_cross_5_13,      1.0),
    ("ema_cross_9_21",      "trend", agent_ema_cross_9_21,      1.0),
    ("ema_cross_21_55",     "trend", agent_ema_cross_21_55,     1.0),
    ("ema_slope_h1",        "trend", agent_ema_slope_h1,        1.0),
    ("price_vs_ema200_m15", "trend", agent_price_vs_ema200_m15, 1.0),
    ("triple_ema_stack_m5", "trend", agent_triple_ema_stack_m5, 1.0),
    ("adx_di_m15",          "trend", agent_adx_di_m15,          1.0),
    ("hh_hl_counter",       "trend", agent_hh_hl_counter,       1.0),
    ("supertrend_m5",       "trend", agent_supertrend_m5,       1.0),
    ("trend_agreement_mtf", "trend", agent_trend_agreement_mtf, 1.0),
]
