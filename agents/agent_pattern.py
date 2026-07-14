# -*- coding: utf-8 -*-
"""
وكلاء فئة الأنماط (pattern) — 8 وكلاء نقيّون لحظيّون.

العقد الموحّد:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx: sym، m1/m5/m15/h1 (o/h/l/c/v مصفوفات numpy)، price، atr_m5، spread،
     وحقول النبض: pattern_m1، pattern_m5 (name/dir/strength)، structure، smc.

غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة"). لا استثناء. numpy فقط.
"""
import numpy as np

CATEGORY = "pattern"


# ───────────────────────── أدوات ─────────────────────────

def _frame(ctx, tf):
    if not isinstance(ctx, dict):
        return None
    f = ctx.get(tf)
    return f if isinstance(f, dict) else None


def _ohlc(ctx, tf, minlen=1):
    """يُرجِع (o, h, l, c) numpy محاذاة الطول، أو None."""
    f = _frame(ctx, tf)
    if not isinstance(f, dict):
        return None
    try:
        o = np.asarray(f.get("o"), dtype=np.float64).ravel()
        h = np.asarray(f.get("h"), dtype=np.float64).ravel()
        l = np.asarray(f.get("l"), dtype=np.float64).ravel()
        c = np.asarray(f.get("c"), dtype=np.float64).ravel()
    except Exception:
        return None
    m = min(o.size, h.size, l.size, c.size)
    if m < minlen:
        return None
    o, h, l, c = o[-m:], h[-m:], l[-m:], c[-m:]
    if not (np.all(np.isfinite(o)) and np.all(np.isfinite(h))
            and np.all(np.isfinite(l)) and np.all(np.isfinite(c))):
        return None
    return o, h, l, c


def _clip01(x):
    try:
        return float(max(0.0, min(1.0, x)))
    except Exception:
        return 0.0


def _pulse_pat(ctx, key):
    p = ctx.get(key) if isinstance(ctx, dict) else None
    return p if isinstance(p, dict) else {}


def _trend_hint(ctx):
    """اتّجاه تقريبيّ من النبض (+1/-1/0) لتحديد جهة الرفض/الانعكاس."""
    m = ctx.get("momentum") if isinstance(ctx, dict) else None
    if isinstance(m, dict):
        t5 = m.get("trend_m5")
        if t5 in (1, -1):
            return int(t5)
    st = ctx.get("structure") if isinstance(ctx, dict) else None
    if isinstance(st, dict) and st.get("bos") in (1, -1):
        return int(st["bos"])
    return 0


# ───────────────────────── الوكلاء ─────────────────────────

def agent_pulse_pattern_m5(ctx):
    """يقرأ pattern_m5 (name/dir/strength) من النبض كتصويت جاهز."""
    try:
        p = _pulse_pat(ctx, "pattern_m5")
        d = p.get("dir")
        if d not in (1, -1):
            return (0, 0.0, "لا نمط M5")
        s = float(p.get("strength") or 1)
        name = p.get("name") or "نمط M5"
        return (int(d), _clip01(0.3 + s / 4.0 * 0.55), f"{name} (قوّة {s:.0f})")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_pulse_pattern_m1(ctx):
    """يقرأ pattern_m1 للإشارة الأسرع على m1."""
    try:
        p = _pulse_pat(ctx, "pattern_m1")
        d = p.get("dir")
        if d not in (1, -1):
            return (0, 0.0, "لا نمط M1")
        s = float(p.get("strength") or 1)
        name = p.get("name") or "نمط M1"
        # M1 أسرع لكن أضعف موثوقيّة ⇒ سقف ثقة أقلّ
        return (int(d), _clip01(0.2 + s / 4.0 * 0.45), f"{name} M1 (قوّة {s:.0f})")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_engulfing_m5(ctx):
    """شمعة ابتلاعيّة صاعدة/هابطة على m5 محسوبة من o/h/l/c."""
    try:
        d = _ohlc(ctx, "m5", 2)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        o1, c1 = o[-2], c[-2]      # الشمعة السابقة
        o0, c0 = o[-1], c[-1]      # الأخيرة
        body_prev = abs(c1 - o1)
        body_now = abs(c0 - o0)
        if body_now <= 1e-12:
            return (0, 0.05, "جسم صفريّ")
        # ابتلاع صاعد: سابقة هابطة، أخيرة صاعدة تبتلع جسمها
        bull = c1 < o1 and c0 > o0 and c0 >= o1 and o0 <= c1
        bear = c1 > o1 and c0 < o0 and c0 <= o1 and o0 >= c1
        ratio = body_now / (body_prev + 1e-12)
        if bull:
            return (1, _clip01(0.35 + min(ratio - 1.0, 1.5) / 1.5 * 0.5), "ابتلاع صاعد M5")
        if bear:
            return (-1, _clip01(0.35 + min(ratio - 1.0, 1.5) / 1.5 * 0.5), "ابتلاع هابط M5")
        return (0, 0.05, "لا ابتلاع")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_pin_bar_reject(ctx):
    """شمعة دبّوسيّة (ذيل طويل) ترفض مستوى؛ اتجاهها عكس الذيل."""
    try:
        d = _ohlc(ctx, "m5", 1)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        o0, h0, l0, c0 = o[-1], h[-1], l[-1], c[-1]
        rng = h0 - l0
        if rng <= 1e-12:
            return (0, 0.05, "مدى صفريّ")
        body = abs(c0 - o0)
        upper = h0 - max(o0, c0)
        lower = min(o0, c0) - l0
        body_frac = body / rng
        # دبّوس رفض علويّ: ذيل علويّ طويل ⇒ رفض هبوطيّ
        if upper >= 0.6 * rng and body_frac <= 0.35 and upper > lower * 1.5:
            return (-1, _clip01(0.3 + upper / rng * 0.55), "دبّوس رفض علويّ ⇒ بيع")
        # دبّوس رفض سفليّ: ذيل سفليّ طويل ⇒ رفض صعوديّ
        if lower >= 0.6 * rng and body_frac <= 0.35 and lower > upper * 1.5:
            return (1, _clip01(0.3 + lower / rng * 0.55), "دبّوس رفض سفليّ ⇒ شراء")
        return (0, 0.05, "لا دبّوس")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_inside_bar_break(ctx):
    """كسر شمعة داخليّة (ضغط) باتجاه الاختراق على m5."""
    try:
        d = _ohlc(ctx, "m5", 3)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        # الشمعة قبل الأخيرة داخليّة نسبةً للأمّ قبلها؟
        mother_h, mother_l = h[-3], l[-3]
        inside_h, inside_l = h[-2], l[-2]
        is_inside = inside_h <= mother_h and inside_l >= mother_l
        if not is_inside:
            return (0, 0.05, "لا شمعة داخليّة")
        c0 = c[-1]
        if c0 > mother_h:
            return (1, _clip01(0.35 + (c0 - mother_h) / (mother_h - mother_l + 1e-12) * 0.5), "كسر داخليّة صعوداً")
        if c0 < mother_l:
            return (-1, _clip01(0.35 + (mother_l - c0) / (mother_h - mother_l + 1e-12) * 0.5), "كسر داخليّة هبوطاً")
        return (0, 0.15, "داخليّة دون كسر")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_outside_bar_m5(ctx):
    """شمعة خارجيّة (ابتلاع مدى) كإشارة سيطرة اتجاهيّة."""
    try:
        d = _ohlc(ctx, "m5", 2)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        outside = h[-1] > h[-2] and l[-1] < l[-2]
        if not outside:
            return (0, 0.05, "لا شمعة خارجيّة")
        o0, c0 = o[-1], c[-1]
        rng_now = h[-1] - l[-1]
        rng_prev = h[-2] - l[-2]
        expand = _clip01((rng_now / (rng_prev + 1e-12) - 1.0) / 1.5)
        if c0 > o0:
            return (1, _clip01(0.35 + expand * 0.45), "شمعة خارجيّة صاعدة")
        if c0 < o0:
            return (-1, _clip01(0.35 + expand * 0.45), "شمعة خارجيّة هابطة")
        return (0, 0.1, "خارجيّة دوجي")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_doji_indecision(ctx):
    """دوجي عند طرف حركة ⇒ يصوّت 0 ويشير لتردّد/انعكاس محتمل."""
    try:
        d = _ohlc(ctx, "m5", 6)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        o0, h0, l0, c0 = o[-1], h[-1], l[-1], c[-1]
        rng = h0 - l0
        if rng <= 1e-12:
            return (0, 0.05, "مدى صفريّ")
        body_frac = abs(c0 - o0) / rng
        if body_frac > 0.12:
            return (0, 0.05, "ليست دوجي")
        # عند طرف حركة صاعدة/هابطة سابقة ⇒ تردّد/انعكاس محتمل (لكن التصويت 0 حسب العقد)
        prior = c[-6:-1]
        rose = prior[-1] > prior[0]
        note = "دوجي بعد صعود ⇒ تردّد" if rose else "دوجي بعد هبوط ⇒ تردّد"
        # ثقة رمزيّة تعكس أنّها إشارة تردّد لا اتّجاه
        return (0, _clip01(0.2 + (0.12 - body_frac) / 0.12 * 0.2), note)
    except Exception:
        return (0, 0.0, "ناقص")


def agent_three_bar_thrust(ctx):
    """ثلاث شموع بنفس الاتجاه واتّساع متزايد = دفعة مؤكَّدة."""
    try:
        d = _ohlc(ctx, "m5", 3)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        bodies = c[-3:] - o[-3:]
        dirs = np.sign(bodies)
        if dirs[0] == dirs[1] == dirs[2] and dirs[0] != 0:
            mags = np.abs(bodies)
            expanding = mags[2] >= mags[1] >= mags[0] * 0.8
            base = 0.45 if expanding else 0.3
            conf = _clip01(base + min(mags.sum() / (abs(c[-1]) * 3e-3 + 1e-9), 1.0) * 0.3)
            v = int(dirs[0])
            return (v, conf, f"دفعة ثلاثيّة {'صاعدة' if v > 0 else 'هابطة'}")
        return (0, 0.05, "لا دفعة ثلاثيّة")
    except Exception:
        return (0, 0.0, "ناقص")


# ───────────────────────── السجلّ ─────────────────────────
AGENTS = [
    ("pulse_pattern_m5",  CATEGORY, agent_pulse_pattern_m5,  1.0),
    ("pulse_pattern_m1",  CATEGORY, agent_pulse_pattern_m1,  1.0),
    ("engulfing_m5",      CATEGORY, agent_engulfing_m5,      1.0),
    ("pin_bar_reject",    CATEGORY, agent_pin_bar_reject,    1.0),
    ("inside_bar_break",  CATEGORY, agent_inside_bar_break,  1.0),
    ("outside_bar_m5",    CATEGORY, agent_outside_bar_m5,    1.0),
    ("doji_indecision",   CATEGORY, agent_doji_indecision,   1.0),
    ("three_bar_thrust",  CATEGORY, agent_three_bar_thrust,  1.0),
]
