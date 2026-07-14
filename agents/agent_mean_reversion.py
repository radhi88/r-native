# -*- coding: utf-8 -*-
"""
agent_mean_reversion.py — 6 وكلاء ارتداد للوسط نقيّون لحظيّون (بلا LLM).

العقد الموحّد لكل وكيل:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

منطق الفئة: التطرّف يُعكَس *في السوق العرضيّ*. لذلك كل وكيل يكبح نفسه حين
يكون الترند قويّاً (تلاشي مع ترند = انتحار)، ويصوّت فقط عند التطرّف + غياب ترند حادّ.
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


def _clip(x, lo=0.0, hi=1.0):
    return float(max(lo, min(hi, x)))


def _rsi(c, period=14):
    """RSI Wilder-تقريبي على مصفوفة إغلاق."""
    try:
        if c is None or c.size < period + 1:
            return None
        d = np.diff(c)
        up = np.where(d > 0, d, 0.0)
        dn = np.where(d < 0, -d, 0.0)
        au = np.mean(up[-period:])
        ad = np.mean(dn[-period:]) + 1e-12
        rs = au / ad
        return 100.0 - 100.0 / (1.0 + rs)
    except Exception:
        return None


def _stoch(ctx, tf='m5', kperiod=14):
    """%K ستوكاستيك على الفريم."""
    try:
        h = _arr(ctx, tf, 'h')
        l = _arr(ctx, tf, 'l')
        c = _arr(ctx, tf, 'c')
        if h is None or l is None or c is None:
            return None
        n = min(h.size, l.size, c.size)
        if n < kperiod:
            return None
        h, l, c = h[-kperiod:], l[-kperiod:], c[-n:]
        hi = np.max(h)
        lo = np.min(l)
        rng = hi - lo + 1e-12
        return 100.0 * (c[-1] - lo) / rng
    except Exception:
        return None


def _trend_strength_m5(ctx):
    """قوّة الترند 0..1 عبر ميل EMA9 مقابل atr — لكبح التلاشي حين الترند حادّ."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 12:
            return 0.0
        k = 2.0 / 10.0
        ema = np.empty(c.size)
        ema[0] = c[0]
        for i in range(1, c.size):
            ema[i] = c[i] * k + ema[i - 1] * (1.0 - k)
        slope = ema[-1] - ema[-6]
        # ATR m5
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        atr = ctx.get('atr_m5')
        if not atr and h is not None and l is not None:
            n = min(h.size, l.size, c.size)
            atr = float(np.mean((h[-14:] - l[-14:]))) if n >= 14 else None
        atr = atr or (abs(slope) + 1e-9)
        return _clip(abs(slope) / (atr + 1e-12))
    except Exception:
        return 0.0


def _is_ranging(ctx):
    """هل السوق عرضيّ؟ (ترند ضعيف) — شرط تفعيل الارتداد."""
    return _trend_strength_m5(ctx) < 0.6


# ─────────────────────────────── الوكلاء ───────────────────────────────────


def agent_bb_meanrev_m5(ctx):
    """لمس نطاق بولنجر الخارجيّ في سوق عرضيّ ⇒ ارتداد للوسط."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 21:
            return (0, 0.0, "ناقص")
        seg = c[-20:]
        mid = np.mean(seg)
        sd = np.std(seg) + 1e-12
        px = ctx.get('price') or c[-1]
        z = (px - mid) / sd
        rng = _is_ranging(ctx)
        if not rng:
            return (0, 0.0, "ترند قويّ — لا تلاشي")
        if z >= 2.0:  # لمس علوي ⇒ نبيع للوسط
            return (-1, _clip((z - 2.0) / 1.5 + 0.4), f"لمس بولنجر علويّ عرضيّ z={z:.2f} ⇒ ارتداد")
        if z <= -2.0:  # لمس سفلي ⇒ نشتري للوسط
            return (1, _clip((abs(z) - 2.0) / 1.5 + 0.4), f"لمس بولنجر سفليّ عرضيّ z={z:.2f} ⇒ ارتداد")
        return (0, 0.0, f"داخل النطاق z={z:.2f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_rsi_extreme_fade(ctx):
    """RSI14 عند >80/<20 في مدى ⇒ تلاشي التطرّف عكسيّاً."""
    try:
        c = _arr(ctx, 'm5', 'c')
        r = _rsi(c, 14)
        if r is None:
            return (0, 0.0, "ناقص")
        if not _is_ranging(ctx):
            return (0, 0.0, f"ترند قويّ RSI={r:.0f} — لا تلاشي")
        if r >= 80.0:
            return (-1, _clip((r - 80.0) / 20.0 + 0.4), f"RSI تشبّع شراء {r:.0f} ⇒ بيع")
        if r <= 20.0:
            return (1, _clip((20.0 - r) / 20.0 + 0.4), f"RSI تشبّع بيع {r:.0f} ⇒ شراء")
        return (0, 0.0, f"RSI معتدل {r:.0f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_zscore_price_m5(ctx):
    """z-score لسعر الإغلاق مقابل متوسط 20 شمعة؛ التطرّف يُعكَس."""
    try:
        c = _arr(ctx, 'm5', 'c')
        if c is None or c.size < 21:
            return (0, 0.0, "ناقص")
        seg = c[-20:]
        mu = np.mean(seg)
        sd = np.std(seg) + 1e-12
        px = ctx.get('price') or c[-1]
        z = (px - mu) / sd
        if not _is_ranging(ctx):
            return (0, 0.0, f"ترند قويّ z={z:.2f} — لا تلاشي")
        if z >= 1.8:
            return (-1, _clip((z - 1.8) / 1.7 + 0.35), f"z مرتفع {z:.2f} ⇒ عودة للوسط (بيع)")
        if z <= -1.8:
            return (1, _clip((abs(z) - 1.8) / 1.7 + 0.35), f"z منخفض {z:.2f} ⇒ عودة للوسط (شراء)")
        return (0, 0.0, f"z معتدل {z:.2f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_vwap_revert_m5(ctx):
    """انحراف السعر عن VWAP يوميّ تقريبيّ ⇒ عودة للـ VWAP."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        c = _arr(ctx, 'm5', 'c')
        v = _arr(ctx, 'm5', 'v')
        if h is None or l is None or c is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, c.size)
        if n < 20:
            return (0, 0.0, "ناقص")
        h, l, c = h[-n:], l[-n:], c[-n:]
        tp = (h + l + c) / 3.0
        if v is not None and v.size >= n and np.sum(v[-n:]) > 0:
            w = v[-n:]
        else:
            w = np.ones(n)  # لا حجم ⇒ متوسط سعريّ بسيط
        vwap = np.sum(tp * w) / (np.sum(w) + 1e-12)
        px = ctx.get('price') or c[-1]
        atr = ctx.get('atr_m5') or (np.mean(h - l) + 1e-9)
        dev = (px - vwap) / (atr + 1e-12)
        if not _is_ranging(ctx):
            return (0, 0.0, f"ترند قويّ dev={dev:.2f} — لا تلاشي")
        if dev >= 1.5:
            return (-1, _clip((dev - 1.5) / 2.0 + 0.35), f"فوق VWAP بـ{dev:.2f}ATR ⇒ عودة")
        if dev <= -1.5:
            return (1, _clip((abs(dev) - 1.5) / 2.0 + 0.35), f"تحت VWAP بـ{dev:.2f}ATR ⇒ عودة")
        return (0, 0.0, f"قرب VWAP dev={dev:.2f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_stoch_extreme_hook(ctx):
    """خطّاف ستوكاستيك من منطقة تشبّع (خروج من >80/<20) كانعكاس."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        c = _arr(ctx, 'm5', 'c')
        if h is None or l is None or c is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, c.size)
        if n < 16:
            return (0, 0.0, "ناقص")
        # %K الحالي والسابق
        def kval(end):
            seg_h = h[end - 14:end]
            seg_l = l[end - 14:end]
            hi, lo = np.max(seg_h), np.min(seg_l)
            return 100.0 * (c[end - 1] - lo) / (hi - lo + 1e-12)
        k_now = kval(n)
        k_prev = kval(n - 1)
        if not _is_ranging(ctx):
            return (0, 0.0, f"ترند قويّ K={k_now:.0f} — لا خطّاف")
        # خطّاف هبوطيّ: كان >80 وانعطف نزولاً ⇒ بيع
        if k_prev >= 80.0 and k_now < k_prev:
            return (-1, _clip((k_prev - 80.0) / 20.0 + 0.4), f"خطّاف ستوك هبوطيّ من {k_prev:.0f}")
        # خطّاف صعوديّ: كان <20 وانعطف صعوداً ⇒ شراء
        if k_prev <= 20.0 and k_now > k_prev:
            return (1, _clip((20.0 - k_prev) / 20.0 + 0.4), f"خطّاف ستوك صعوديّ من {k_prev:.0f}")
        return (0, 0.0, f"ستوك بلا خطّاف K={k_now:.0f}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_range_edge_fade(ctx):
    """قرب حافّة مدى 20-شمعة داخل نطاق ضيّق ⇒ تلاشي نحو المنتصف."""
    try:
        h = _arr(ctx, 'm5', 'h')
        l = _arr(ctx, 'm5', 'l')
        c = _arr(ctx, 'm5', 'c')
        if h is None or l is None or c is None:
            return (0, 0.0, "ناقص")
        n = min(h.size, l.size, c.size)
        if n < 20:
            return (0, 0.0, "ناقص")
        hi = np.max(h[-20:])
        lo = np.min(l[-20:])
        rng = hi - lo + 1e-12
        atr = ctx.get('atr_m5') or (np.mean(h[-20:] - l[-20:]) + 1e-9)
        # شرط "نطاق ضيّق": المدى الكلّي ليس أكبر بكثير من atr (سوق محصور)
        tightness = rng / (atr + 1e-12)
        if tightness > 8.0:
            return (0, 0.0, f"مدى واسع ({tightness:.1f}ATR) — لا تلاشي حافّة")
        px = ctx.get('price') or c[-1]
        pos = (px - lo) / rng
        if not _is_ranging(ctx):
            return (0, 0.0, "ترند قويّ — لا تلاشي حافّة")
        if pos >= 0.88:
            return (-1, _clip((pos - 0.88) / 0.12 + 0.35), f"حافّة علويّة نطاق ضيّق ({pos:.2f})")
        if pos <= 0.12:
            return (1, _clip((0.12 - pos) / 0.12 + 0.35), f"حافّة سفليّة نطاق ضيّق ({pos:.2f})")
        return (0, 0.0, f"وسط النطاق ({pos:.2f})")
    except Exception:
        return (0, 0.0, "ناقص")


# ────────────────────────────── السجلّ ─────────────────────────────────────
AGENTS = [
    ("bb_meanrev_m5",      "mean_reversion", agent_bb_meanrev_m5,      1.0),
    ("rsi_extreme_fade",   "mean_reversion", agent_rsi_extreme_fade,   1.0),
    ("zscore_price_m5",    "mean_reversion", agent_zscore_price_m5,    1.0),
    ("vwap_revert_m5",     "mean_reversion", agent_vwap_revert_m5,     1.0),
    ("stoch_extreme_hook", "mean_reversion", agent_stoch_extreme_hook, 1.0),
    ("range_edge_fade",    "mean_reversion", agent_range_edge_fade,    1.0),
]
