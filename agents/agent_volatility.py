# -*- coding: utf-8 -*-
"""
agent_volatility.py — 8 وكلاء تقلّب نقيّون لحظيّون (بلا LLM).

العقد الموحّد لكل وكيل:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx فيه m1/m5/m15/h1 (o/h/l/c/v مصفوفات numpy)، price، atr_m5، spread، وحقول smc.
دفاعيّ دائماً: نقص/استثناء ⇒ (0, 0.0, "ناقص").
"""
import numpy as np

# ───────────────────────── أدوات نقيّة (numpy فقط) ─────────────────────────


def _arr(ctx, tf, field):
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


def _tr_series(ctx, tf='m5'):
    """سلسلة المدى الحقيقي True-Range للفريم."""
    try:
        h = _arr(ctx, tf, 'h')
        l = _arr(ctx, tf, 'l')
        c = _arr(ctx, tf, 'c')
        if h is None or l is None or c is None:
            return None
        n = min(h.size, l.size, c.size)
        if n < 3:
            return None
        h, l, c = h[-n:], l[-n:], c[-n:]
        pc = c[:-1]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
        return tr
    except Exception:
        return None


def _atr(ctx, tf='m5', period=14):
    try:
        tr = _tr_series(ctx, tf)
        if tr is None or tr.size == 0:
            v = ctx.get('atr_m5')
            return float(v) if v else None
        if tr.size < period:
            return float(np.mean(tr))
        return float(np.mean(tr[-period:]))
    except Exception:
        v = ctx.get('atr_m5')
        return float(v) if v else None


def _clip(x, lo=0.0, hi=1.0):
    return float(max(lo, min(hi, x)))


def _last_dir(ctx, tf='m5'):
    """اتجاه آخر شمعة إغلاق مقابل فتح."""
    try:
        o = _arr(ctx, tf, 'o')
        c = _arr(ctx, tf, 'c')
        if o is None or c is None:
            return 0
        return int(np.sign(c[-1] - o[-1]))
    except Exception:
        return 0


def _spread_atr_pct(ctx):
    """spread كنسبة من atr_m5 (٪). fallback من الحقول."""
    try:
        sp = ctx.get('spread')
        atr = ctx.get('atr_m5') or _atr(ctx)
        if sp is None or not atr:
            v = ctx.get('spread_atr_pct')
            return float(v) if v is not None else None
        return 100.0 * float(sp) / (float(atr) + 1e-12)
    except Exception:
        return None


# ─────────────────────────────── الوكلاء ───────────────────────────────────


def agent_atr_expansion(ctx):
    """ATR14 m5 يتوسّع مقابل متوسطه ⇒ تحرّك قادم؛ يصوّت باتجاه آخر شمعة."""
    try:
        tr = _tr_series(ctx, 'm5')
        if tr is None or tr.size < 30:
            return (0, 0.0, "ناقص")
        recent = np.mean(tr[-5:])
        base = np.mean(tr[-30:-5]) + 1e-12
        ratio = recent / base
        if ratio <= 1.15:
            return (0, 0.0, f"لا توسّع ({ratio:.2f}x)")
        conf = _clip((ratio - 1.15) / 1.0)
        d = _last_dir(ctx, 'm5')
        if d > 0:
            return (1, conf, f"توسّع ATR صاعد {ratio:.2f}x")
        if d < 0:
            return (-1, conf, f"توسّع ATR هابط {ratio:.2f}x")
        return (0, conf * 0.3, f"توسّع ATR محايد {ratio:.2f}x")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_atr_contraction_coil(ctx):
    """انكماش ATR (ضغط) كتمهيد اختراق؛ محايد اتجاهيّاً حتى الكسر."""
    try:
        tr = _tr_series(ctx, 'm5')
        if tr is None or tr.size < 30:
            return (0, 0.0, "ناقص")
        recent = np.mean(tr[-5:])
        base = np.mean(tr[-30:-5]) + 1e-12
        ratio = recent / base
        if ratio >= 0.85:
            return (0, 0.0, f"لا ضغط ({ratio:.2f}x)")
        # ضغط قائم ⇒ إشارة "استعداد" لا اتجاه ⇒ vote=0 بثقة توثّق الضغط
        conf = _clip((0.85 - ratio) / 0.5)
        return (0, conf * 0.4, f"ضغط تقلّب (coil) {ratio:.2f}x — بانتظار الكسر")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_bb_squeeze_m5(ctx):
    """ضيق نطاقات بولنجر(20,2) m5 = ضغط تقلّب قبل انفجار (محايد اتجاهاً)."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 40:
            return (0, 0.0, "ناقص")
        c = c[-120:] if c.size > 120 else c
        win = 20
        # عرض النطاق الحالي مقابل تاريخه
        widths = []
        for i in range(win, c.size + 1):
            seg = c[i - win:i]
            widths.append(4.0 * np.std(seg))  # 2σ علوي + 2σ سفلي
        widths = np.asarray(widths)
        if widths.size < 5:
            return (0, 0.0, "ناقص")
        cur = widths[-1]
        med = np.median(widths) + 1e-12
        ratio = cur / med
        if ratio >= 0.75:
            return (0, 0.0, f"نطاق طبيعيّ ({ratio:.2f})")
        conf = _clip((0.75 - ratio) / 0.6)
        return (0, conf * 0.4, f"انضغاط بولنجر m5 ({ratio:.2f}) — تمهيد انفجار")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_bb_breakout_dir(ctx):
    """إغلاق خارج نطاق بولنجر العلويّ/السفليّ باتجاه الاختراق."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 21:
            return (0, 0.0, "ناقص")
        win = 20
        seg = c[-win:]
        mid = np.mean(seg)
        sd = np.std(seg) + 1e-12
        px = ctx.get('price') or c[-1]
        z = (px - mid) / sd
        if z >= 2.0:
            return (1, _clip((z - 2.0) / 1.5 + 0.4), f"اختراق بولنجر علويّ z={z:.2f}")
        if z <= -2.0:
            return (-1, _clip((abs(z) - 2.0) / 1.5 + 0.4), f"اختراق بولنجر سفليّ z={z:.2f}")
        return (0, 0.0, f"داخل النطاق z={z:.2f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_spread_atr_guard(ctx):
    """spread_atr_pct مرتفع (كلفة>الحافّة) ⇒ يصوّت 0 ويكبح الثقة (حارس كلفة)."""
    try:
        pct = _spread_atr_pct(ctx)
        if pct is None:
            return (0, 0.0, "ناقص")
        # هذا الوكيل فيتو-كلفة: دائماً vote=0، وثقته ترتفع كتحذير حين تسوء الكلفة.
        if pct >= 30.0:
            return (0, _clip((pct - 30.0) / 40.0 + 0.5), f"كلفة عالية جداً spread={pct:.0f}%ATR — كبح")
        if pct >= 15.0:
            return (0, _clip((pct - 15.0) / 30.0), f"كلفة مرتفعة spread={pct:.0f}%ATR")
        return (0, 0.0, f"كلفة مقبولة spread={pct:.0f}%ATR")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_keltner_break_m5(ctx):
    """اختراق قناة كيلتنر (EMA20 ± atr×1.5) على m5."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 21:
            return (0, 0.0, "ناقص")
        # EMA20
        k = 2.0 / 21.0
        ema = c[0]
        for i in range(1, c.size):
            ema = c[i] * k + ema * (1.0 - k)
        atr = _atr(ctx, 'm5') or 1e-9
        upper = ema + 1.5 * atr
        lower = ema - 1.5 * atr
        px = ctx.get('price') or c[-1]
        if px > upper:
            return (1, _clip((px - upper) / (atr + 1e-12) + 0.3), "اختراق كيلتنر علويّ m5")
        if px < lower:
            return (-1, _clip((lower - px) / (atr + 1e-12) + 0.3), "اختراق كيلتنر سفليّ m5")
        return (0, 0.0, "داخل قناة كيلتنر")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_range_position(ctx):
    """موقع السعر ضمن مدى (high-low) آخر 20 شمعة m5: قرب القمة=هبوط محتمل، قرب القاع=صعود."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        if h is None or l is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, 20)
        if n < 10:
            return (0, 0.0, "ناقص")
        hi = np.max(h[-n:])
        lo = np.min(l[-n:])
        rng = hi - lo + 1e-12
        px = ctx.get('price')
        if px is None:
            c = _arr(ctx, 'm5', 'c')
            px = c[-1] if c is not None else (hi + lo) / 2.0
        pos = (px - lo) / rng  # 0=قاع .. 1=قمّة
        # موقع متطرّف = احتمال ارتداد ضمن المدى (إشارة سياقيّة خفيفة)
        if pos >= 0.85:
            return (-1, _clip((pos - 0.85) / 0.15) * 0.6, f"قرب قمّة المدى ({pos:.2f})")
        if pos <= 0.15:
            return (1, _clip((0.15 - pos) / 0.15) * 0.6, f"قرب قاع المدى ({pos:.2f})")
        return (0, 0.0, f"وسط المدى ({pos:.2f})")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_vol_regime_filter(ctx):
    """تصنيف نظام التقلّب (هادئ/متفجّر) من atr؛ يخفض ثقة الجميع في الهدوء (فيتو-نظام)."""
    try:
        tr = _tr_series(ctx, 'm5')
        if tr is None or tr.size < 50:
            return (0, 0.0, "ناقص")
        cur = np.mean(tr[-5:])
        long_base = np.mean(tr[-50:]) + 1e-12
        ratio = cur / long_base
        # وكيل نظام: vote=0 دائماً؛ الثقة تُعلِن حالة النظام للمجلس.
        if ratio <= 0.6:
            return (0, _clip((0.6 - ratio) / 0.6 + 0.3), f"نظام هادئ ({ratio:.2f}x) — خفّض الثقة")
        if ratio >= 1.6:
            return (0, _clip((ratio - 1.6) / 1.0), f"نظام متفجّر ({ratio:.2f}x) — احذر")
        return (0, 0.0, f"نظام طبيعيّ ({ratio:.2f}x)")
    except Exception:
        return (0, 0.0, "ناقص")


# ────────────────────────────── السجلّ ─────────────────────────────────────
AGENTS = [
    ("atr_expansion",        "volatility", agent_atr_expansion,        1.0),
    ("atr_contraction_coil", "volatility", agent_atr_contraction_coil, 1.0),
    ("bb_squeeze_m5",        "volatility", agent_bb_squeeze_m5,        1.0),
    ("bb_breakout_dir",      "volatility", agent_bb_breakout_dir,      1.0),
    ("spread_atr_guard",     "volatility", agent_spread_atr_guard,     1.0),
    ("keltner_break_m5",     "volatility", agent_keltner_break_m5,     1.0),
    ("range_position",       "volatility", agent_range_position,       1.0),
    ("vol_regime_filter",    "volatility", agent_vol_regime_filter,    1.0),
]
