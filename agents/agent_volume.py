# -*- coding: utf-8 -*-
"""
agent_volume.py — 8 وكلاء نقيّون لحظيّون لفئة الحجم (volume).

عقد صارم موحّد:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx قاموس جاهز فيه:
    sym, price, atr_m5, spread,
    m1/m5/m15/h1: dict فيه o/h/l/c/v مصفوفات numpy (آخر ~200 شمعة),
    وحقول نبض SMC: bos/choch/ob/fvg/liq_pools/sweeps/poc (+ hvn, volume{z,spike}).

كل وكيل يحسب زاويته فقط ويرجع تصويته.
غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
"""
import numpy as np

VETO = (0, 0.0, "بيانات ناقصة")


# ----------------------------------------------------------------------------
# أدوات داخليّة دفاعيّة (لا تُصدَّر) — كلّها تعيد None عند غياب البيانات
# ----------------------------------------------------------------------------
def _arr(ctx, tf, field):
    """يرجع مصفوفة numpy لحقل (o/h/l/c/v) على فريم tf، أو None."""
    try:
        frame = ctx.get(tf)
        if frame is None:
            return None
        a = frame.get(field)
        if a is None:
            return None
        a = np.asarray(a, dtype=float)
        if a.size == 0 or not np.isfinite(a).any():
            return None
        return a
    except Exception:
        return None


def _pulse(ctx):
    """يرجع قاموس نبض SMC مهما اختلف موضعه في ctx."""
    for key in ("smc", "pulse", "smc_pulse"):
        p = ctx.get(key)
        if isinstance(p, dict):
            return p
    return ctx  # الحقول قد تكون في الجذر مباشرة


def _get(ctx, *names, default=None):
    """يبحث عن أوّل حقل موجود في ctx ثمّ في نبض SMC."""
    p = _pulse(ctx)
    for n in names:
        if n in ctx and ctx[n] is not None:
            return ctx[n]
        if isinstance(p, dict) and n in p and p[n] is not None:
            return p[n]
    return default


def _price(ctx):
    px = ctx.get("price")
    if px is not None:
        try:
            return float(px)
        except Exception:
            pass
    c = _arr(ctx, "m5", "c") or _arr(ctx, "m1", "c")
    if c is not None:
        return float(c[-1])
    return None


def _atr(ctx):
    a = ctx.get("atr_m5")
    if a is not None:
        try:
            v = float(a)
            if v > 0:
                return v
        except Exception:
            pass
    # اشتقاق تقريبيّ من مدى m5
    h = _arr(ctx, "m5", "h")
    l = _arr(ctx, "m5", "l")
    if h is not None and l is not None and h.size >= 14:
        rng = (h - l)[-14:]
        v = float(np.nanmean(rng))
        if v > 0:
            return v
    return None


def _clamp(x):
    return float(max(0.0, min(1.0, x)))


# ----------------------------------------------------------------------------
# 1) vol_spike_dir — volume.spike=true: يصوّت باتجاه شمعة الارتفاع الحجميّ
# ----------------------------------------------------------------------------
def agent_vol_spike_dir(ctx):
    try:
        vol = _get(ctx, "volume", default={})
        spike = bool(vol.get("spike")) if isinstance(vol, dict) else False
        c = _arr(ctx, "m5", "c")
        o = _arr(ctx, "m5", "o")
        if c is None or o is None or c.size < 1 or o.size < 1:
            return VETO
        body = float(c[-1] - o[-1])
        if not spike:
            return (0, 0.0, "لا ارتفاع حجميّ (spike=false)")
        if body == 0:
            return (0, 0.1, "ارتفاع حجميّ بشمعة محايدة")
        direction = 1 if body > 0 else -1
        atr = _atr(ctx)
        strength = abs(body) / atr if atr else abs(body)
        conf = _clamp(0.5 + 0.4 * min(1.0, strength))
        d = "صعوديّة" if direction > 0 else "هبوطيّة"
        return (direction, conf, f"spike حجميّ + شمعة {d} (جسم {strength:.2f} ATR)")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 2) vol_z_thrust — volume.z>1.5 مع اتجاه السعر = دفعة مدعومة بالحجم
# ----------------------------------------------------------------------------
def agent_vol_z_thrust(ctx):
    try:
        vol = _get(ctx, "volume", default={})
        z = float(vol.get("z", 0.0)) if isinstance(vol, dict) else 0.0
        c = _arr(ctx, "m5", "c")
        if c is None or c.size < 4:
            return VETO
        slope = float(c[-1] - c[-4])  # اتجاه آخر ٣ شموع
        if z <= 1.5 or slope == 0:
            return (0, 0.0, f"لا دفعة حجميّة (z={z:.2f})")
        direction = 1 if slope > 0 else -1
        conf = _clamp(0.45 + 0.18 * (z - 1.5))
        d = "صعود" if direction > 0 else "هبوط"
        return (direction, conf, f"دفعة حجم z={z:.2f} تدعم {d}")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 3) poc_lean — موقع السعر نسبة لـ smc.poc: فوقه شراء، تحته بيع
# ----------------------------------------------------------------------------
def agent_poc_lean(ctx):
    try:
        poc = _get(ctx, "poc")
        px = _price(ctx)
        atr = _atr(ctx)
        if poc is None or px is None:
            return VETO
        poc = float(poc)
        dist = px - poc
        if atr and abs(dist) < 0.15 * atr:
            return (0, 0.1, "السعر عند POC (توازن)")
        direction = 1 if dist > 0 else -1
        mag = abs(dist) / atr if atr else abs(dist)
        conf = _clamp(0.4 + 0.25 * min(2.0, mag))
        d = "فوق" if direction > 0 else "تحت"
        return (direction, conf, f"السعر {d} POC ({poc:.2f}) بـ{mag:.2f} ATR")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 4) hvn_reject — ارتداد السعر من عقدة حجم عالية hvn كمنطقة عرض/طلب
# ----------------------------------------------------------------------------
def agent_hvn_reject(ctx):
    try:
        hvn = _get(ctx, "hvn")
        px = _price(ctx)
        atr = _atr(ctx)
        c = _arr(ctx, "m5", "c")
        if not hvn or px is None or atr is None or c is None or c.size < 2:
            return VETO
        hvn = [float(x) for x in hvn]
        # أقرب عقدة
        node = min(hvn, key=lambda h: abs(h - px))
        near = abs(px - node) <= 0.4 * atr
        if not near:
            return (0, 0.0, "بعيد عن أيّ HVN")
        prev = float(c[-2])
        # ارتداد: كنّا نقترب من العقدة ثمّ ابتعدنا عنها
        approaching_from_below = prev < node and px < node  # لمس من الأسفل ⇒ رفض ⇒ بيع
        approaching_from_above = prev > node and px > node  # لمس من الأعلى ⇒ دعم ⇒ شراء
        if approaching_from_above and px > prev:
            return (1, 0.5, f"طلب عند HVN {node:.2f} (ارتداد صعوديّ)")
        if approaching_from_below and px < prev:
            return (-1, 0.5, f"عرض عند HVN {node:.2f} (ارتداد هبوطيّ)")
        return (0, 0.15, f"عند HVN {node:.2f} بلا رفض واضح")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 5) hvn_pull_to_poc — انجذاب السعر البعيد نحو POC (رجوع للتوازن) عكس الامتداد
# ----------------------------------------------------------------------------
def agent_hvn_pull_to_poc(ctx):
    try:
        poc = _get(ctx, "poc")
        px = _price(ctx)
        atr = _atr(ctx)
        if poc is None or px is None or atr is None or atr <= 0:
            return VETO
        poc = float(poc)
        dist = (poc - px) / atr  # موجب ⇒ POC فوق ⇒ يُتوقّع سحب صعوديّ
        ext = abs(dist)
        if ext < 1.2:
            return (0, 0.0, "قرب التوازن، لا امتداد يُسحب")
        direction = 1 if dist > 0 else -1  # عكس الامتداد نحو POC
        conf = _clamp(0.35 + 0.12 * (ext - 1.2))
        d = "أعلى" if direction > 0 else "أسفل"
        return (direction, conf, f"امتداد {ext:.1f} ATR {d} POC ⇒ سحب للتوازن")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 6) vol_dryup_reversal — انخفاض حادّ في volume.z (<-1) عند طرف حركة كنضوب
# ----------------------------------------------------------------------------
def agent_vol_dryup_reversal(ctx):
    try:
        vol = _get(ctx, "volume", default={})
        z = float(vol.get("z", 0.0)) if isinstance(vol, dict) else 0.0
        c = _arr(ctx, "m5", "c")
        if c is None or c.size < 6:
            return VETO
        if z >= -1.0:
            return (0, 0.0, f"لا نضوب حجم (z={z:.2f})")
        leg = float(c[-1] - c[-6])  # اتجاه الطرف الأخير
        if leg == 0:
            return (0, 0.1, "نضوب حجم بلا حركة")
        # نضوب في طرف حركة ⇒ نتوقّع انعكاساً عكس الطرف
        direction = -1 if leg > 0 else 1
        conf = _clamp(0.35 + 0.15 * (abs(z) - 1.0))
        d = "صعود" if leg > 0 else "هبوط"
        return (direction, conf, f"نضوب حجم z={z:.2f} بعد طرف {d} ⇒ انعكاس")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 7) obv_slope_m5 — ميل On-Balance-Volume على m5 كتأكيد تدفّق تراكميّ
# ----------------------------------------------------------------------------
def agent_obv_slope_m5(ctx):
    try:
        c = _arr(ctx, "m5", "c")
        v = _arr(ctx, "m5", "v")
        if c is None or v is None or c.size < 12 or v.size < 12:
            return VETO
        n = min(c.size, v.size)
        c = c[-n:]
        v = v[-n:]
        sign = np.sign(np.diff(c))
        obv = np.concatenate(([0.0], np.cumsum(sign * v[1:])))
        window = obv[-10:]
        if window.size < 4:
            return VETO
        # ميل بالانحدار الخطّيّ
        x = np.arange(window.size, dtype=float)
        slope = float(np.polyfit(x, window, 1)[0])
        scale = float(np.mean(v[-10:])) or 1.0
        norm = slope / scale
        if abs(norm) < 0.05:
            return (0, 0.1, "OBV مسطّح")
        direction = 1 if norm > 0 else -1
        conf = _clamp(0.4 + 0.4 * min(1.0, abs(norm)))
        d = "تراكم" if direction > 0 else "توزيع"
        return (direction, conf, f"ميل OBV يشير إلى {d}")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 8) vol_climax_fade — ذروة حجم (z مرتفع جدّاً) بعد امتداد = تلاشٍ عكسيّ
# ----------------------------------------------------------------------------
def agent_vol_climax_fade(ctx):
    try:
        vol = _get(ctx, "volume", default={})
        z = float(vol.get("z", 0.0)) if isinstance(vol, dict) else 0.0
        c = _arr(ctx, "m5", "c")
        if c is None or c.size < 10:
            return VETO
        if z < 2.2:
            return (0, 0.0, f"لا ذروة حجم (z={z:.2f})")
        leg = float(c[-1] - c[-10])  # امتداد سابق
        atr = _atr(ctx)
        extended = (abs(leg) / atr) if atr else abs(leg)
        if extended < 1.0:
            return (0, 0.15, "ذروة حجم بلا امتداد كافٍ")
        direction = -1 if leg > 0 else 1  # تلاشٍ عكس الامتداد
        conf = _clamp(0.4 + 0.12 * (z - 2.2) + 0.1 * min(2.0, extended))
        d = "صعوديّ" if leg > 0 else "هبوطيّ"
        return (direction, conf, f"ذروة حجم z={z:.2f} بعد امتداد {d} ⇒ تلاشٍ")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# التسجيل الموحّد
# ----------------------------------------------------------------------------
AGENTS = [
    ("vol_spike_dir",        "volume", agent_vol_spike_dir,        1.0),
    ("vol_z_thrust",         "volume", agent_vol_z_thrust,         1.0),
    ("poc_lean",             "volume", agent_poc_lean,             1.0),
    ("hvn_reject",           "volume", agent_hvn_reject,           1.0),
    ("hvn_pull_to_poc",      "volume", agent_hvn_pull_to_poc,      1.0),
    ("vol_dryup_reversal",   "volume", agent_vol_dryup_reversal,   1.0),
    ("obv_slope_m5",         "volume", agent_obv_slope_m5,         1.0),
    ("vol_climax_fade",      "volume", agent_vol_climax_fade,      1.0),
]
