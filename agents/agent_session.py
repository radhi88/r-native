# -*- coding: utf-8 -*-
"""
وكلاء الفئة: session — 7 وكلاء نقيّون لحظيّون.

كل وكيل دالة نقيّة: agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

هذه الفئة تعتمد الوقت (UTC). تُقرأ الساعة من ctx بالأولويّة:
  ctx['hour_utc'] (float 0..24) أو ctx['ts'] (epoch seconds) أو ctx['iso'] ("HH:MM..")
وإلا يُستعمل توقيت النظام UTC كملاذ أخير (لحظيّ دائماً).

درس الانضباط (ذاكرة المشروع): الليل (22-08 UTC) يخسر ⇒ نكبح الثقة ليلاً.

قاعدة صارمة: غياب البيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
"""
import numpy as np
import time as _time
from datetime import datetime, timezone

_EMPTY = (0, 0.0, "بيانات ناقصة")


# ------------------------------- أدوات داخليّة -------------------------------

def _hour_utc(ctx):
    """ساعة UTC كسريّة (0.0..24.0). يقرأ من ctx أولاً ثم من النظام."""
    # 1) hour_utc صريحة
    h = ctx.get("hour_utc")
    if h is not None:
        try:
            h = float(h) % 24.0
            if np.isfinite(h):
                return h
        except (TypeError, ValueError):
            pass
    # 2) ts epoch
    ts = ctx.get("ts")
    if ts is not None:
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return dt.hour + dt.minute / 60.0
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    # 3) iso "HH:MM:SS"
    iso = ctx.get("iso")
    if isinstance(iso, str) and ":" in iso:
        try:
            parts = iso.strip().split(":")
            hh = float(parts[0]) % 24.0
            mm = float(parts[1]) if len(parts) > 1 else 0.0
            return hh + mm / 60.0
        except (TypeError, ValueError, IndexError):
            pass
    # 4) ملاذ: توقيت النظام UTC
    try:
        dt = datetime.fromtimestamp(_time.time(), tz=timezone.utc)
        return dt.hour + dt.minute / 60.0
    except Exception:
        return None


def _weekday_utc(ctx):
    """يوم الأسبوع UTC (0=إثنين .. 4=جمعة .. 6=أحد) أو None."""
    ts = ctx.get("ts")
    try:
        if ts is not None:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).weekday()
        return datetime.fromtimestamp(_time.time(), tz=timezone.utc).weekday()
    except Exception:
        return None


def _closes(ctx, tf):
    fr = ctx.get(tf)
    if not isinstance(fr, dict):
        return None
    c = fr.get("c")
    if c is None:
        return None
    try:
        a = np.asarray(c, dtype=float)
    except (TypeError, ValueError):
        return None
    a = a[np.isfinite(a)]
    return a if a.size else None


def _hilo(ctx, tf):
    """(high, low) مصفوفتان للفريم tf أو (None, None)."""
    fr = ctx.get(tf)
    if not isinstance(fr, dict):
        return None, None
    try:
        h = np.asarray(fr.get("h"), dtype=float)
        l = np.asarray(fr.get("l"), dtype=float)
    except (TypeError, ValueError):
        return None, None
    if h.size == 0 or l.size == 0:
        return None, None
    return h, l


def _in_window(h, a, b):
    """هل الساعة h ضمن [a,b)؟ يدعم الالتفاف حول منتصف الليل (a>b)."""
    if h is None:
        return False
    if a <= b:
        return a <= h < b
    return h >= a or h < b


def _price(ctx):
    p = ctx.get("price")
    if p is not None:
        try:
            p = float(p)
            if np.isfinite(p) and p > 0:
                return p
        except (TypeError, ValueError):
            pass
    c = _closes(ctx, "m5")
    return float(c[-1]) if c is not None and c.size else None


# ================================ الوكلاء ================================

def agent_session_gate_utc(ctx):
    """بوّابة الجلسة: يكبح الثقة ليلاً (22-08 UTC) وفق درس الانضباط.
    ليس وكيل اتجاه؛ يصوّت 0 دائماً لكن ثقته تمثّل «سماح الجلسة»
    (عالية نهاراً، ~0 ليلاً) لتُستعمل كوزن/بوّابة في المحرّك.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        night = _in_window(h, 22.0, 8.0)  # ليل الانضباط
        if night:
            return (0, 0.05, "جلسة ليليّة (كبح) %.1fh" % h)
        # نهار: نافذة نشطة ⇒ سماح مرتفع
        active = _in_window(h, 7.0, 21.0)
        conf = 0.85 if active else 0.5
        return (0, float(conf), "جلسة نهاريّة (سماح) %.1fh" % h)
    except Exception:
        return _EMPTY


def agent_london_open_bias(ctx):
    """نافذة افتتاح لندن (07-09 UTC): يعزّز اتجاه أول اختراق نطاق.
    يقارن السعر بنطاق ما قبل الافتتاح (آخر ~12 شمعة m5) ويصوّت مع الاختراق.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        if not _in_window(h, 7.0, 9.0):
            return (0, 0.0, "خارج افتتاح لندن")
        hi, lo = _hilo(ctx, "m5")
        price = _price(ctx)
        if hi is None or lo is None or price is None or hi.size < 6:
            return (0, 0.0, "بيانات نطاق ناقصة")
        w = min(12, hi.size)
        rng_hi = float(np.max(hi[-w:]))
        rng_lo = float(np.min(lo[-w:]))
        if not (rng_hi > rng_lo):
            return (0, 0.0, "نطاق مسطّح")
        if price >= rng_hi:
            return (1, 0.7, "اختراق افتتاح لندن صعوداً")
        if price <= rng_lo:
            return (-1, 0.7, "اختراق افتتاح لندن هبوطاً")
        # داخل النطاق: تحيّز خفيف نحو الحافّة الأقرب
        mid = (rng_hi + rng_lo) / 2.0
        pos = (price - mid) / ((rng_hi - rng_lo) / 2.0)
        if abs(pos) < 0.5:
            return (0, 0.2, "نطاق لندن غير محسوم")
        return (int(np.sign(pos)), 0.4, "ميل لحافّة لندن")
    except Exception:
        return _EMPTY


def agent_ny_open_bias(ctx):
    """نافذة افتتاح نيويورك (12-14 UTC): تحيّز زخم الجلسة النشطة.
    يصوّت مع زخم آخر ~6 شموع m5 خلال النافذة.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        if not _in_window(h, 12.0, 14.0):
            return (0, 0.0, "خارج افتتاح نيويورك")
        c = _closes(ctx, "m5")
        if c is None or c.size < 6:
            return (0, 0.0, "بيانات زخم ناقصة")
        seg = c[-6:]
        change = float(seg[-1] - seg[0])
        base = float(np.mean(np.abs(np.diff(seg)))) or 1e-9
        strength = abs(change) / (base * 5.0)
        if abs(change) < base * 0.5:
            return (0, 0.25, "زخم نيويورك ضعيف")
        conf = float(np.clip(0.45 + 0.4 * strength, 0.45, 0.85))
        d = int(np.sign(change))
        side = "صعوداً" if d > 0 else "هبوطاً"
        return (d, conf, "زخم افتتاح نيويورك %s" % side)
    except Exception:
        return _EMPTY


def agent_asian_range_fade(ctx):
    """نطاق الجلسة الآسيويّة الضيّق ⇒ تلاشي الحوافّ (mean-revert).
    خلال 00-07 UTC وإن كان النطاق ضيّقاً، نصوّت عكس اتّجاه لمس الحافّة.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        if not _in_window(h, 0.0, 7.0):
            return (0, 0.0, "خارج الجلسة الآسيويّة")
        hi, lo = _hilo(ctx, "m5")
        c = _closes(ctx, "m5")
        price = _price(ctx)
        if hi is None or lo is None or c is None or price is None or hi.size < 8:
            return (0, 0.0, "بيانات نطاق ناقصة")
        w = min(24, hi.size)
        rng_hi = float(np.max(hi[-w:]))
        rng_lo = float(np.min(lo[-w:]))
        span = rng_hi - rng_lo
        if span <= 0:
            return (0, 0.0, "نطاق صفريّ")
        # مقياس ضيق النطاق مقابل تقلّب الشموع
        body = float(np.mean(np.abs(np.diff(c[-w:])))) or 1e-9
        tightness = span / (body * w)  # أصغر = أضيق
        if tightness > 2.5:
            return (0, 0.15, "نطاق آسيويّ واسع — لا تلاشٍ")
        mid = (rng_hi + rng_lo) / 2.0
        pos = (price - mid) / (span / 2.0)  # -1..1
        if pos >= 0.7:
            return (-1, float(np.clip(0.4 + 0.3 * (pos), 0.4, 0.75)), "تلاشي حافّة آسيويّة عليا")
        if pos <= -0.7:
            return (1, float(np.clip(0.4 + 0.3 * (-pos), 0.4, 0.75)), "تلاشي حافّة آسيويّة سفلى")
        return (0, 0.2, "منتصف النطاق الآسيويّ")
    except Exception:
        return _EMPTY


def agent_overlap_boost(ctx):
    """تداخل لندن/نيويورك (12-16 UTC) يرفع ثقة إشارات الترند.
    يصوّت مع اتجاه ترند m5 (إن وُجد بالنبض/الإغلاقات) بثقة معزَّزة داخل التداخل.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        if not _in_window(h, 12.0, 16.0):
            return (0, 0.0, "خارج التداخل")
        # اتجاه الترند: نفضّل trend_m5 من النبض، وإلا ميل الإغلاقات
        d = 0
        mo = ctx.get("momentum")
        if isinstance(mo, dict) and mo.get("trend_m5") is not None:
            try:
                d = int(np.sign(int(mo.get("trend_m5"))))
            except (TypeError, ValueError):
                d = 0
        if d == 0:
            c = _closes(ctx, "m5")
            if c is not None and c.size >= 10:
                d = int(np.sign(float(c[-1] - c[-10])))
        if d == 0:
            return (0, 0.2, "لا ترند واضح بالتداخل")
        side = "صاعد" if d > 0 else "هابط"
        return (d, 0.7, "تعزيز ترند %s بتداخل لندن/نيويورك" % side)
    except Exception:
        return _EMPTY


def agent_friday_close_caution(ctx):
    """قرب إغلاق الجمعة ⇒ يخفض الثقة/يصوّت 0 (خطر الفجوة).
    الجمعة بعد 19 UTC: بوّابة حذر (تصويت 0، ثقة كبح منخفضة).
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        wd = _weekday_utc(ctx)
        # 4 = الجمعة
        if wd == 4 and h >= 19.0:
            return (0, 0.03, "قرب إغلاق الجمعة — حذر الفجوة")
        if wd == 4 and h >= 16.0:
            return (0, 0.2, "جمعة متأخّرة — حذر نسبيّ")
        # غير ذلك: لا اعتراض (سماح كامل)
        return (0, 0.8, "لا خطر إغلاق")
    except Exception:
        return _EMPTY


def agent_killzone_smc(ctx):
    """كِل-زون ICT (لندن 07-10 / نيويورك 12-15 UTC) يعطي وزناً أعلى لإشارات smc فقط داخلها.
    داخل الكِل-زون يصوّت مع تحيّز smc (bos/choch/trend) بثقة معزَّزة؛ خارجها 0.
    """
    try:
        h = _hour_utc(ctx)
        if h is None:
            return _EMPTY
        in_kz = _in_window(h, 7.0, 10.0) or _in_window(h, 12.0, 15.0)
        if not in_kz:
            return (0, 0.0, "خارج الكِل-زون")
        smc = ctx.get("smc") if isinstance(ctx.get("smc"), dict) else ctx
        d = 0
        # أولويّة: آخر CHoCH ثم آخر BOS ثم trend
        choch = smc.get("choch")
        if choch:
            d = int(np.sign(choch[-1].get("dir", 0)))
        if d == 0:
            bos = smc.get("bos")
            if bos:
                d = int(np.sign(bos[-1].get("dir", 0)))
        if d == 0 and smc.get("trend") is not None:
            try:
                d = int(np.sign(int(smc.get("trend"))))
            except (TypeError, ValueError):
                d = 0
        if d == 0:
            return (0, 0.25, "كِل-زون بلا إشارة smc")
        side = "صاعد" if d > 0 else "هابط"
        return (d, 0.75, "كِل-زون ICT ⇒ smc %s" % side)
    except Exception:
        return _EMPTY


# ------------------------------ سجلّ الفئة ------------------------------
CATEGORY = "session"
AGENTS = [
    ("session_gate_utc",      CATEGORY, agent_session_gate_utc,      1.0),
    ("london_open_bias",      CATEGORY, agent_london_open_bias,      1.0),
    ("ny_open_bias",          CATEGORY, agent_ny_open_bias,          1.0),
    ("asian_range_fade",      CATEGORY, agent_asian_range_fade,      1.0),
    ("overlap_boost",         CATEGORY, agent_overlap_boost,         1.0),
    ("friday_close_caution",  CATEGORY, agent_friday_close_caution,  1.0),
    ("killzone_smc",          CATEGORY, agent_killzone_smc,          1.0),
]
