# -*- coding: utf-8 -*-
"""
وكلاء فئة الاختراق (breakout) — 6 وكلاء نقيّون لحظيّون.

العقد الموحّد:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx: sym، m1/m5/m15/h1 (o/h/l/c/v numpy)، price، atr_m5، spread،
     structure (swing_high/swing_low/bos)،
     smc (bos/choch/ob/fvg/liq_pools/sweeps/poc).

غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة"). لا استثناء. numpy فقط.
"""
import numpy as np
from datetime import datetime, timezone

CATEGORY = "breakout"


# ───────────────────────── أدوات ─────────────────────────

def _frame(ctx, tf):
    if not isinstance(ctx, dict):
        return None
    f = ctx.get(tf)
    return f if isinstance(f, dict) else None


def _ohlc(ctx, tf, minlen=1):
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
    if not (np.all(np.isfinite(h)) and np.all(np.isfinite(l)) and np.all(np.isfinite(c))):
        return None
    return o, h, l, c


def _ts(ctx, tf):
    """طوابع زمنيّة للفريم إن توفّرت (لحساب الجلسة/نطاق الافتتاح)."""
    f = _frame(ctx, tf)
    if not isinstance(f, dict):
        return None
    t = f.get("t") or f.get("time") or f.get("ts")
    if t is None:
        return None
    try:
        arr = np.asarray(t, dtype=np.float64).ravel()
        return arr if arr.size else None
    except Exception:
        return None


def _clip01(x):
    try:
        return float(max(0.0, min(1.0, x)))
    except Exception:
        return 0.0


def _atr(ctx):
    a = ctx.get("atr_m5") if isinstance(ctx, dict) else None
    try:
        a = float(a)
        if a > 1e-9:
            return a
    except Exception:
        pass
    d = _ohlc(ctx, "m5", 5)
    if d is None:
        return 0.0
    _, h, l, _ = d
    return float(np.mean(h[-14:] - l[-14:])) if h.size >= 5 else 0.0


def _smc(ctx):
    s = ctx.get("smc") if isinstance(ctx, dict) else None
    return s if isinstance(s, dict) else {}


def _price(ctx):
    p = ctx.get("price") if isinstance(ctx, dict) else None
    if p is not None:
        try:
            return float(p)
        except Exception:
            pass
    d = _ohlc(ctx, "m5", 1)
    return float(d[3][-1]) if d else None


# ───────────────────────── الوكلاء ─────────────────────────

def agent_donchian_20_break(ctx):
    """اختراق أعلى/أدنى 20 شمعة m5 (قناة دونشيان) باتجاه الكسر."""
    try:
        d = _ohlc(ctx, "m5", 21)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        # قناة على الشموع الـ20 السابقة (باستثناء الأخيرة)
        hi = h[-21:-1].max()
        lo = l[-21:-1].min()
        c0 = c[-1]
        atr = _atr(ctx)
        scale = atr if atr > 1e-9 else (hi - lo) / 20.0 + 1e-9
        if c0 > hi:
            return (1, _clip01(0.4 + (c0 - hi) / scale * 0.4), f"اختراق قمّة دونشيان20")
        if c0 < lo:
            return (-1, _clip01(0.4 + (lo - c0) / scale * 0.4), f"اختراق قاع دونشيان20")
        # قرب الحافّة ⇒ إشارة ضعيفة محايدة
        return (0, 0.05, "داخل قناة دونشيان")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_prevday_hl_break(ctx):
    """كسر قمّة/قاع اليوم السابق المحسوبة من candles_m5 المجمّعة."""
    try:
        d = _ohlc(ctx, "m5", 30)
        ts = _ts(ctx, "m5")
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        c0 = c[-1]
        if ts is not None and ts.size == c.size:
            # نحدّد يوم آخر شمعة ونجمع مدى اليوم السابق
            days = np.array([datetime.fromtimestamp(float(x), tz=timezone.utc).toordinal()
                             for x in ts])
            today = days[-1]
            prev_mask = days == (today - 1)
            if prev_mask.sum() >= 3:
                pdh = h[prev_mask].max()
                pdl = l[prev_mask].min()
            else:
                # بديل: أقدم نصف مقابل الأحدث
                half = c.size // 2
                pdh = h[:half].max(); pdl = l[:half].min()
        else:
            half = c.size // 2
            pdh = h[:half].max(); pdl = l[:half].min()
        atr = _atr(ctx)
        scale = atr if atr > 1e-9 else (pdh - pdl) / 20.0 + 1e-9
        if c0 > pdh:
            return (1, _clip01(0.4 + (c0 - pdh) / scale * 0.4), "كسر قمّة اليوم السابق")
        if c0 < pdl:
            return (-1, _clip01(0.4 + (pdl - c0) / scale * 0.4), "كسر قاع اليوم السابق")
        return (0, 0.05, "داخل مدى اليوم السابق")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_range_compression_break(ctx):
    """اختراق بعد انضغاط مدى (NR7) على m5 باتجاه الشمعة."""
    try:
        d = _ohlc(ctx, "m5", 8)
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        ranges = h - l
        # هل الشمعة قبل الأخيرة أضيق 7 مدى (NR7)؟
        window = ranges[-8:-1]
        if window.size < 7:
            return (0, 0.0, "بيانات ناقصة")
        nr7 = window[-1] <= window.min() + 1e-12
        if not nr7:
            return (0, 0.05, "لا انضغاط NR7")
        # الشمعة الأخيرة تكسر مدى NR7؟
        comp_h, comp_l = h[-2], l[-2]
        c0 = c[-1]
        atr = _atr(ctx)
        scale = atr if atr > 1e-9 else (comp_h - comp_l) + 1e-9
        if c0 > comp_h:
            return (1, _clip01(0.4 + (c0 - comp_h) / scale * 0.45), "اختراق انضغاط NR7 صعوداً")
        if c0 < comp_l:
            return (-1, _clip01(0.4 + (comp_l - c0) / scale * 0.45), "اختراق انضغاط NR7 هبوطاً")
        return (0, 0.15, "انضغاط دون كسر")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_liq_sweep_reversal(ctx):
    """بعد smc.sweep لسيولة ⇒ يصوّت عكس جهة الاصطياد (انعكاس)."""
    try:
        smc = _smc(ctx)
        sweeps = smc.get("sweeps")
        if not isinstance(sweeps, list) or not sweeps:
            return (0, 0.0, "لا اصطياد سيولة")
        last = sweeps[-1]
        if not isinstance(last, dict):
            return (0, 0.0, "بيانات ناقصة")
        side = last.get("side")
        # اصطياد قمم (high) ⇒ انعكاس هبوطيّ؛ اصطياد قيعان (low) ⇒ انعكاس صعوديّ
        if side == "high":
            v = -1
        elif side == "low":
            v = 1
        else:
            return (0, 0.0, "جهة غير معروفة")
        # حداثة الاصطياد: كلّما كان idx أقرب لنهاية السلسلة زادت الثقة
        conf = 0.45
        idx = last.get("idx")
        c5 = _ohlc(ctx, "m5", 1)
        # تأكيد أنّ السعر عاد للجهة المعاكسة
        price = _price(ctx)
        swp_price = last.get("price")
        try:
            if price is not None and swp_price is not None:
                if (v == -1 and price < float(swp_price)) or (v == 1 and price > float(swp_price)):
                    conf += 0.2
        except Exception:
            pass
        return (v, _clip01(conf), f"اصطياد سيولة {side} ⇒ انعكاس {'بيع' if v < 0 else 'شراء'}")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_swing_break_confirm(ctx):
    """كسر swing_high/low من النبض مع إغلاق مؤكَّد خلفه."""
    try:
        st = ctx.get("structure") if isinstance(ctx, dict) else None
        if not isinstance(st, dict):
            return (0, 0.0, "بيانات ناقصة")
        sh = st.get("swing_high")
        sl = st.get("swing_low")
        price = _price(ctx)
        if price is None:
            return (0, 0.0, "بيانات ناقصة")
        atr = _atr(ctx)
        scale = atr if atr > 1e-9 else price * 1e-4 + 1e-9
        # إغلاق مؤكَّد خلف السوينغ (تجاوز ≥ 5% من ATR لتفادي الملامسة)
        try:
            if sh is not None and price > float(sh) + 0.05 * scale:
                return (1, _clip01(0.4 + (price - float(sh)) / scale * 0.4), "كسر قمّة سوينغ مؤكَّد")
            if sl is not None and price < float(sl) - 0.05 * scale:
                return (-1, _clip01(0.4 + (float(sl) - price) / scale * 0.4), "كسر قاع سوينغ مؤكَّد")
        except Exception:
            return (0, 0.0, "بيانات ناقصة")
        # دعم من bos النبض إن كان طازجاً
        bos = st.get("bos")
        if bos in (1, -1):
            return (int(bos), 0.2, f"BOS نبض {'صاعد' if bos > 0 else 'هابط'} دون كسر سوينغ")
        return (0, 0.05, "لا كسر سوينغ")
    except Exception:
        return (0, 0.0, "ناقص")


def agent_opening_range_break(ctx):
    """كسر نطاق أول 30 دقيقة من الجلسة النشطة باتجاه الاختراق."""
    try:
        d = _ohlc(ctx, "m5", 8)
        ts = _ts(ctx, "m5")
        if d is None:
            return (0, 0.0, "بيانات ناقصة")
        o, h, l, c = d
        c0 = c[-1]
        # جلسات UTC: لندن 07:00، نيويورك 12:00 — نأخذ أوّل 6 شموع m5 (30 دقيقة) بعد الفتح
        or_h = or_l = None
        if ts is not None and ts.size == c.size:
            hours = np.array([datetime.fromtimestamp(float(x), tz=timezone.utc).hour for x in ts])
            mins = np.array([datetime.fromtimestamp(float(x), tz=timezone.utc).minute for x in ts])
            for open_h in (12, 7):  # نيويورك ثمّ لندن
                mask = (hours == open_h) & (mins < 30)
                if mask.sum() >= 3:
                    or_h = h[mask].max(); or_l = l[mask].min()
                    break
        if or_h is None:
            # بديل: أوّل 6 شموع من النافذة المتاحة
            k = min(6, c.size - 1)
            if k < 3:
                return (0, 0.0, "بيانات ناقصة")
            or_h = h[:k].max(); or_l = l[:k].min()
        atr = _atr(ctx)
        scale = atr if atr > 1e-9 else (or_h - or_l) / 6.0 + 1e-9
        if c0 > or_h:
            return (1, _clip01(0.4 + (c0 - or_h) / scale * 0.4), "كسر نطاق الافتتاح صعوداً")
        if c0 < or_l:
            return (-1, _clip01(0.4 + (or_l - c0) / scale * 0.4), "كسر نطاق الافتتاح هبوطاً")
        return (0, 0.05, "داخل نطاق الافتتاح")
    except Exception:
        return (0, 0.0, "ناقص")


# ───────────────────────── السجلّ ─────────────────────────
AGENTS = [
    ("donchian_20_break",        CATEGORY, agent_donchian_20_break,        1.0),
    ("prevday_hl_break",         CATEGORY, agent_prevday_hl_break,         1.0),
    ("range_compression_break",  CATEGORY, agent_range_compression_break,  1.0),
    ("liq_sweep_reversal",       CATEGORY, agent_liq_sweep_reversal,       1.0),
    ("swing_break_confirm",      CATEGORY, agent_swing_break_confirm,      1.0),
    ("opening_range_break",      CATEGORY, agent_opening_range_break,      1.0),
]
