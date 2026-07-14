# -*- coding: utf-8 -*-
"""
وكلاء الفئة: fib_pivot — 5 وكلاء نقيّون لحظيّون.

كل وكيل دالة نقيّة: agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

يحسب المستويات من الشموع المتاحة في ctx (m5 افتراضاً، ويستعمل h1 إن توفّر لليوميّ)،
ويصوّت على الارتداد/الكسر عند المستوى بحسب قرب السعر (عبر ATR).

قاعدة صارمة: غياب البيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
"""
import numpy as np

_EMPTY = (0, 0.0, "بيانات ناقصة")


# ------------------------------- أدوات داخليّة -------------------------------

def _frame(ctx, tf):
    fr = ctx.get(tf)
    if not isinstance(fr, dict):
        return None
    try:
        o = np.asarray(fr.get("o"), dtype=float)
        h = np.asarray(fr.get("h"), dtype=float)
        l = np.asarray(fr.get("l"), dtype=float)
        c = np.asarray(fr.get("c"), dtype=float)
    except (TypeError, ValueError):
        return None
    n = min(o.size, h.size, l.size, c.size)
    if n == 0:
        return None
    return o[-n:], h[-n:], l[-n:], c[-n:]


def _price(ctx):
    p = ctx.get("price")
    if p is not None:
        try:
            p = float(p)
            if np.isfinite(p) and p > 0:
                return p
        except (TypeError, ValueError):
            pass
    fr = _frame(ctx, "m5")
    if fr is not None:
        return float(fr[3][-1])
    return None


def _atr(ctx):
    a = ctx.get("atr_m5")
    if a is not None:
        try:
            a = float(a)
            if np.isfinite(a) and a > 0:
                return a
        except (TypeError, ValueError):
            pass
    fr = _frame(ctx, "m5")
    if fr is not None:
        _, h, l, c = fr
        n = min(15, h.size)
        if n >= 2:
            tr = h[-n:] - l[-n:]
            m = float(np.mean(tr[np.isfinite(tr)]))
            if np.isfinite(m) and m > 0:
                return m
    return None


def _daily_hlc(ctx):
    """(H, L, C) لآخر «يوم» تقريبيّ. يفضّل h1 (آخر 24) وإلا m5 (آخر ~ يوم = 288)،
    وإلا كامل m5 المتاح.
    """
    fr = _frame(ctx, "h1")
    if fr is not None and fr[1].size >= 6:
        _, h, l, c = fr
        w = min(24, h.size)
        return float(np.max(h[-w:])), float(np.min(l[-w:])), float(c[-1])
    fr = _frame(ctx, "m15")
    if fr is not None and fr[1].size >= 8:
        _, h, l, c = fr
        w = min(96, h.size)
        return float(np.max(h[-w:])), float(np.min(l[-w:])), float(c[-1])
    fr = _frame(ctx, "m5")
    if fr is not None and fr[1].size >= 8:
        _, h, l, c = fr
        w = min(288, h.size)
        return float(np.max(h[-w:])), float(np.min(l[-w:])), float(c[-1])
    return None


def _last_swing(ctx):
    """آخر موجة (نقطة تأرجح low->high أو high->low) من m5. يرجّح استعمال
    structure.swing_high/low من النبض إن توفّرا، وإلا من قمم/قيعان m5.
    يرجع (a, b, up) حيث a بداية الموجة، b نهايتها، up=اتجاه الموجة.
    """
    st = ctx.get("structure")
    if isinstance(st, dict):
        sh = st.get("swing_high"); sl = st.get("swing_low")
        if sh is not None and sl is not None:
            try:
                sh = float(sh); sl = float(sl)
                if np.isfinite(sh) and np.isfinite(sl) and sh > sl:
                    price = _price(ctx)
                    # اتجاه الموجة: إن كان السعر قرب القمّة نعتبرها موجة صاعدة sl->sh
                    up = True
                    if price is not None:
                        up = abs(price - sh) <= abs(price - sl)
                    return (sl, sh, up) if up else (sh, sl, up)
            except (TypeError, ValueError):
                pass
    fr = _frame(ctx, "m5")
    if fr is None:
        return None
    _, h, l, c = fr
    w = min(40, h.size)
    if w < 5:
        return None
    seg_h = h[-w:]; seg_l = l[-w:]
    hi_i = int(np.argmax(seg_h)); lo_i = int(np.argmin(seg_l))
    hi = float(seg_h[hi_i]); lo = float(seg_l[lo_i])
    if hi <= lo:
        return None
    up = hi_i > lo_i  # القمّة بعد القاع ⇒ موجة صاعدة
    return (lo, hi, up) if up else (hi, lo, up)


def _prox(dist, atr, floor=0.15, cap=0.9):
    if atr is None or atr <= 0:
        return 0.4
    r = abs(dist) / atr
    return float(np.clip(1.0 - r / 2.5, floor, cap))


def _near(price, level, atr, mult=0.6):
    """هل السعر قرب المستوى ضمن mult*ATR؟"""
    if atr is None or atr <= 0:
        return False
    return abs(price - level) <= mult * atr


# ================================ الوكلاء ================================

def agent_pivot_classic_r_s(ctx):
    """بيفوت كلاسيكيّ (PP/R1/S1) من candles؛ ارتداد/كسر عند المستوى.
    قرب R1 من الأسفل ⇒ مقاومة (بيع)؛ كسر R1 ⇒ استمرار (شراء).
    قرب S1 من الأعلى ⇒ دعم (شراء)؛ كسر S1 ⇒ استمرار (بيع). قرب PP ⇒ حياد.
    """
    try:
        hlc = _daily_hlc(ctx)
        price = _price(ctx)
        atr = _atr(ctx)
        if hlc is None or price is None:
            return _EMPTY
        H, L, C = hlc
        if not (H > L):
            return (0, 0.0, "نطاق يوميّ غير صالح")
        PP = (H + L + C) / 3.0
        R1 = 2 * PP - L
        S1 = 2 * PP - H
        R2 = PP + (H - L)
        S2 = PP - (H - L)
        # اختبر أقرب مستوى مقاومة/دعم
        for lvl, is_res, name in ((R1, True, "R1"), (S1, False, "S1"),
                                  (R2, True, "R2"), (S2, False, "S2")):
            if _near(price, lvl, atr, mult=0.5):
                conf = _prox(price - lvl, atr, floor=0.35, cap=0.85)
                if is_res:
                    if price > lvl:  # كسر المقاومة صعوداً
                        return (1, conf, "كسر بيفوت %s صعوداً" % name)
                    return (-1, conf, "ارتداد من مقاومة بيفوت %s" % name)
                else:
                    if price < lvl:  # كسر الدعم هبوطاً
                        return (-1, conf, "كسر بيفوت %s هبوطاً" % name)
                    return (1, conf, "ارتداد من دعم بيفوت %s" % name)
        # قرب PP: تحيّز خفيف باتجاه الجهة
        if _near(price, PP, atr, mult=0.4):
            return (0, 0.2, "قرب نقطة البيفوت PP")
        # بين المستويات: تحيّز نحو الأقرب
        if price > PP:
            return (1, 0.3, "فوق البيفوت")
        return (-1, 0.3, "تحت البيفوت")
    except Exception:
        return _EMPTY


def agent_fib_retrace_618(ctx):
    """تصحيح فيبو 0.618 لآخر موجة swing كمنطقة دخول مع الترند.
    في موجة صاعدة: لمس 0.618 من الأعلى ⇒ شراء (ارتداد مع الترند). والعكس هبوطاً.
    """
    try:
        sw = _last_swing(ctx)
        price = _price(ctx)
        atr = _atr(ctx)
        if sw is None or price is None:
            return _EMPTY
        a, b, up = sw
        span = abs(b - a)
        if span <= 0:
            return (0, 0.0, "موجة صفريّة")
        # مستويات التصحيح الرئيسة
        if up:  # موجة صاعدة a(low)->b(high)؛ التصحيح للأسفل
            f382 = b - 0.382 * span
            f618 = b - 0.618 * span
            f500 = b - 0.5 * span
        else:   # موجة هابطة a(high)->b(low)؛ التصحيح للأعلى
            f382 = b + 0.382 * span
            f618 = b + 0.618 * span
            f500 = b + 0.5 * span
        for lvl, name in ((f618, "0.618"), (f500, "0.5"), (f382, "0.382")):
            if _near(price, lvl, atr, mult=0.5):
                conf = _prox(price - lvl, atr, floor=0.4, cap=0.85)
                if up:
                    return (1, conf, "ارتداد فيبو %s (موجة صاعدة)" % name)
                return (-1, conf, "ارتداد فيبو %s (موجة هابطة)" % name)
        return (0, 0.15, "خارج مناطق فيبو")
    except Exception:
        return _EMPTY


def agent_fib_extension_target(ctx):
    """امتداد فيبو 1.272/1.618 كتحيّز استمرار نحو الهدف.
    يصوّت مع اتجاه الموجة طالما السعر لم يبلغ هدف الامتداد بعد.
    """
    try:
        sw = _last_swing(ctx)
        price = _price(ctx)
        atr = _atr(ctx)
        if sw is None or price is None:
            return _EMPTY
        a, b, up = sw
        span = abs(b - a)
        if span <= 0:
            return (0, 0.0, "موجة صفريّة")
        if up:
            ext1 = b + 0.272 * span   # 1.272
            ext2 = b + 0.618 * span   # 1.618
            # إن كان السعر بين b والامتداد ⇒ استمرار صاعد
            if b <= price < ext2:
                # كلّما اقترب من b (بداية الدفعة) زادت الثقة بالاستمرار
                prog = (price - b) / max(ext2 - b, 1e-9)
                conf = float(np.clip(0.65 - 0.3 * prog, 0.35, 0.7))
                tgt = ext1 if price < ext1 else ext2
                return (1, conf, "امتداد صاعد نحو %.5g" % tgt)
            if price >= ext2:
                return (0, 0.2, "بلغ هدف الامتداد الصاعد")
            return (0, 0.15, "دون بداية الامتداد الصاعد")
        else:
            ext1 = b - 0.272 * span
            ext2 = b - 0.618 * span
            if ext2 < price <= b:
                prog = (b - price) / max(b - ext2, 1e-9)
                conf = float(np.clip(0.65 - 0.3 * prog, 0.35, 0.7))
                tgt = ext1 if price > ext1 else ext2
                return (-1, conf, "امتداد هابط نحو %.5g" % tgt)
            if price <= ext2:
                return (0, 0.2, "بلغ هدف الامتداد الهابط")
            return (0, 0.15, "فوق بداية الامتداد الهابط")
    except Exception:
        return _EMPTY


def agent_camarilla_h3_l3(ctx):
    """مستويات كاماريلا H3/L3 كحدود ارتداد داخل النطاق اليوميّ.
    السعر عند/فوق H3 ⇒ بيع (ارتداد)؛ عند/تحت L3 ⇒ شراء (ارتداد).
    كسر H4/L4 (تقريبيّاً H3±) نتركه لوكلاء الاختراق.
    """
    try:
        hlc = _daily_hlc(ctx)
        price = _price(ctx)
        atr = _atr(ctx)
        if hlc is None or price is None:
            return _EMPTY
        H, L, C = hlc
        rng = H - L
        if rng <= 0:
            return (0, 0.0, "نطاق يوميّ غير صالح")
        H3 = C + rng * 1.1 / 4.0
        L3 = C - rng * 1.1 / 4.0
        H4 = C + rng * 1.1 / 2.0
        L4 = C - rng * 1.1 / 2.0
        # كسر H4/L4 ⇒ استمرار (اختراق) بثقة معتدلة
        if price >= H4:
            return (1, 0.5, "كسر كاماريلا H4 (اختراق صاعد)")
        if price <= L4:
            return (-1, 0.5, "كسر كاماريلا L4 (اختراق هابط)")
        # ارتداد من H3/L3
        if _near(price, H3, atr, mult=0.5) or price >= H3:
            conf = _prox(price - H3, atr, floor=0.4, cap=0.85)
            return (-1, conf, "ارتداد من كاماريلا H3")
        if _near(price, L3, atr, mult=0.5) or price <= L3:
            conf = _prox(price - L3, atr, floor=0.4, cap=0.85)
            return (1, conf, "ارتداد من كاماريلا L3")
        return (0, 0.15, "داخل نطاق كاماريلا")
    except Exception:
        return _EMPTY


def agent_round_number_magnet(ctx):
    """أرقام مستديرة (00/50) قرب السعر كمغناطيس/عائق سيولة.
    يحدّد أقرب مستوى مستدير مناسب لمقياس الرمز، ويصوّت جذباً نحوه إن كان قريباً،
    وارتداداً/عائقاً عند لمسه تماماً.
    """
    try:
        price = _price(ctx)
        atr = _atr(ctx)
        if price is None or atr is None or atr <= 0:
            return _EMPTY
        # اختر خطوة الرقم المستدير حسب حجم السعر (تقريب لوغاريتميّ)
        # هدف: أن تكون الخطوة قابلة للّمس ضمن بضعة ATR
        exp = np.floor(np.log10(max(atr, 1e-9)))
        step = float(10 ** (exp + 1))       # مثلاً atr~4 ⇒ step=100؛ atr~0.001 ⇒ step=0.01
        half = step / 2.0
        # أقرب مضاعف كامل ونصفيّ
        nearest_full = round(price / step) * step
        nearest_half = round(price / half) * half
        # اختر الأقرب من الاثنين
        cand = min((nearest_full, nearest_half), key=lambda x: abs(price - x))
        dist = price - cand
        # ضمن 1.5 ATR يُعتبر ضمن نطاق تأثير المغناطيس
        if abs(dist) > 1.5 * atr:
            return (0, 0.1, "بعيد عن رقم مستدير")
        # لمس تماماً (ضمن 0.25 ATR) ⇒ عائق/ارتداد عكس اتجاه الاقتراب
        if abs(dist) <= 0.25 * atr:
            # ارتداد: إن جاء من الأسفل (price>=cand بقليل) نتوقّع رفض هابط والعكس
            vote = -1 if price >= cand else 1
            return (vote, 0.5, "لمس رقم مستدير %.5g (عائق)" % cand)
        # ضمن النطاق لكن ليس ملاصقاً ⇒ جذب نحو الرقم
        vote = 1 if price < cand else -1
        conf = _prox(dist, atr, floor=0.3, cap=0.7)
        return (vote, conf, "جذب لرقم مستدير %.5g" % cand)
    except Exception:
        return _EMPTY


# ------------------------------ سجلّ الفئة ------------------------------
CATEGORY = "fib_pivot"
AGENTS = [
    ("pivot_classic_r_s",    CATEGORY, agent_pivot_classic_r_s,   1.0),
    ("fib_retrace_618",      CATEGORY, agent_fib_retrace_618,      1.0),
    ("fib_extension_target", CATEGORY, agent_fib_extension_target, 1.0),
    ("camarilla_h3_l3",      CATEGORY, agent_camarilla_h3_l3,      1.0),
    ("round_number_magnet",  CATEGORY, agent_round_number_magnet,  1.0),
]
