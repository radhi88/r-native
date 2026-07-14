# -*- coding: utf-8 -*-
"""
agent_liquidity.py — 5 وكلاء نقيّون لحظيّون لفئة السيولة (liquidity).

عقد صارم موحّد:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

يقرأ من نبض SMC: liq_pools, sweeps, poc, وأسعار m1/m5.
    liq_pool = {'side':'high'|'low', 'price':float, 'count':int, 'idxs':[..]}
    sweep    = {'idx':int, 'side':'high'|'low', 'price':float}
غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
"""
import numpy as np

VETO = (0, 0.0, "بيانات ناقصة")


# ----------------------------------------------------------------------------
# أدوات داخليّة دفاعيّة
# ----------------------------------------------------------------------------
def _pulse(ctx):
    for key in ("smc", "pulse", "smc_pulse"):
        p = ctx.get(key)
        if isinstance(p, dict):
            return p
    return ctx


def _get(ctx, *names, default=None):
    p = _pulse(ctx)
    for n in names:
        if n in ctx and ctx[n] is not None:
            return ctx[n]
        if isinstance(p, dict) and n in p and p[n] is not None:
            return p[n]
    return default


def _arr(ctx, tf, field):
    try:
        frame = ctx.get(tf)
        if frame is None:
            return None
        a = np.asarray(frame.get(field), dtype=float)
        if a.size == 0 or not np.isfinite(a).any():
            return None
        return a
    except Exception:
        return None


def _price(ctx):
    px = ctx.get("price")
    if px is not None:
        try:
            return float(px)
        except Exception:
            pass
    c = _arr(ctx, "m5", "c")
    if c is None:
        c = _arr(ctx, "m1", "c")
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
    h = _arr(ctx, "m5", "h")
    l = _arr(ctx, "m5", "l")
    if h is not None and l is not None and h.size >= 14:
        v = float(np.nanmean((h - l)[-14:]))
        if v > 0:
            return v
    return None


def _clamp(x):
    return float(max(0.0, min(1.0, x)))


def _pools(ctx):
    p = _get(ctx, "liq_pools", default=[])
    return p if isinstance(p, list) else []


def _sweeps(ctx):
    s = _get(ctx, "sweeps", default=[])
    return s if isinstance(s, list) else []


# ----------------------------------------------------------------------------
# 1) liq_pool_target — أقرب liq_pool في اتجاه السعر كهدف سيولة مُرجَّح
# ----------------------------------------------------------------------------
def agent_liq_pool_target(ctx):
    try:
        pools = _pools(ctx)
        px = _price(ctx)
        atr = _atr(ctx)
        if not pools or px is None or atr is None or atr <= 0:
            return VETO
        # اتجاه السعر الآنيّ
        c = _arr(ctx, "m5", "c")
        drift = 0
        if c is not None and c.size >= 4:
            drift = 1 if c[-1] > c[-4] else (-1 if c[-1] < c[-4] else 0)
        above = [p for p in pools if float(p.get("price", px)) > px]
        below = [p for p in pools if float(p.get("price", px)) < px]
        target = None
        direction = 0
        if drift >= 0 and above:
            target = min(above, key=lambda p: float(p["price"]) - px)
            direction = 1
        elif drift <= 0 and below:
            target = min(below, key=lambda p: px - float(p["price"]))
            direction = -1
        elif above or below:  # لا انحياز ⇒ أقرب بركة مطلقاً
            allp = above + below
            target = min(allp, key=lambda p: abs(float(p["price"]) - px))
            direction = 1 if float(target["price"]) > px else -1
        if target is None:
            return (0, 0.0, "لا بركة سيولة في الاتجاه")
        dist = abs(float(target["price"]) - px) / atr
        if dist > 4.0:
            return (0, 0.1, "بركة السيولة بعيدة جدّاً")
        count = int(target.get("count", 1))
        conf = _clamp(0.35 + 0.12 * count + 0.15 * max(0.0, 1.5 - dist))
        d = "أعلى" if direction > 0 else "أسفل"
        return (direction, conf, f"هدف سيولة {d} عند {float(target['price']):.2f} ({dist:.1f} ATR)")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 2) sweep_then_reverse — اصطياد ثمّ انعكاس عكس جهة الاصطياد
# ----------------------------------------------------------------------------
def agent_sweep_then_reverse(ctx):
    try:
        sweeps = _sweeps(ctx)
        c = _arr(ctx, "m5", "c")
        if not sweeps or c is None or c.size < 3:
            return VETO
        last = sweeps[-1]
        side = last.get("side")
        sweep_px = float(last.get("price", c[-1]))
        px = float(c[-1])
        # اصطياد قمم (high) ⇒ نتوقّع انعكاساً هبوطيّاً، والعكس
        if side == "high":
            confirmed = px < sweep_px  # عاد السعر تحت السيولة المصطادة
            direction = -1
        elif side == "low":
            confirmed = px > sweep_px
            direction = 1
        else:
            return (0, 0.0, "جهة اصطياد غير معروفة")
        if not confirmed:
            return (0, 0.15, f"اصطياد {side} بلا تأكيد انعكاس بعد")
        atr = _atr(ctx)
        back = abs(px - sweep_px) / atr if atr else 0.3
        conf = _clamp(0.45 + 0.25 * min(1.0, back))
        d = "هبوطيّ" if direction < 0 else "صعوديّ"
        return (direction, conf, f"اصطياد {side} ثمّ انعكاس {d}")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 3) equal_highs_lows_draw — قمم/قيعان متساوية (count≥2) تجذب السعر
# ----------------------------------------------------------------------------
def agent_equal_highs_lows_draw(ctx):
    try:
        pools = _pools(ctx)
        px = _price(ctx)
        atr = _atr(ctx)
        if not pools or px is None or atr is None or atr <= 0:
            return VETO
        # أبرك ذات count>=2 هي قمم/قيعان متساوية = سيولة تجذب
        equals = [p for p in pools if int(p.get("count", 1)) >= 2]
        if not equals:
            return (0, 0.0, "لا قمم/قيعان متساوية")
        target = min(equals, key=lambda p: abs(float(p["price"]) - px))
        tp = float(target["price"])
        dist = abs(tp - px) / atr
        if dist < 0.1:
            return (0, 0.1, "السعر عند السيولة المتساوية")
        if dist > 5.0:
            return (0, 0.08, "السيولة المتساوية بعيدة")
        direction = 1 if tp > px else -1
        count = int(target.get("count", 2))
        conf = _clamp(0.35 + 0.1 * (count - 1) + 0.12 * max(0.0, 2.0 - dist))
        side = target.get("side", "?")
        d = "أعلى" if direction > 0 else "أسفل"
        return (direction, conf, f"سيولة {side} متساوية ×{count} تجذب {d} ({dist:.1f} ATR)")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 4) poc_liquidity_magnet — انجذاب السعر نحو POC كمنطقة قبول/سيولة
# ----------------------------------------------------------------------------
def agent_poc_liquidity_magnet(ctx):
    try:
        poc = _get(ctx, "poc")
        px = _price(ctx)
        atr = _atr(ctx)
        if poc is None or px is None or atr is None or atr <= 0:
            return VETO
        poc = float(poc)
        dist = (poc - px) / atr  # موجب ⇒ POC فوق ⇒ جذب صعوديّ
        adist = abs(dist)
        if adist < 0.4:
            return (0, 0.1, "السعر ملتصق بـ POC")
        if adist > 4.0:
            return (0, 0.08, "POC بعيد جدّاً كمغناطيس")
        direction = 1 if dist > 0 else -1
        conf = _clamp(0.3 + 0.14 * min(3.0, adist))
        d = "أعلى" if direction > 0 else "أسفل"
        return (direction, conf, f"POC ({poc:.2f}) مغناطيس سيولة {d} ({adist:.1f} ATR)")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 5) stop_hunt_wick — ذيل طويل يخترق pool ثمّ يغلق داخله ⇒ عكسه
# ----------------------------------------------------------------------------
def agent_stop_hunt_wick(ctx):
    try:
        pools = _pools(ctx)
        o = _arr(ctx, "m5", "o")
        h = _arr(ctx, "m5", "h")
        l = _arr(ctx, "m5", "l")
        c = _arr(ctx, "m5", "c")
        atr = _atr(ctx)
        if (not pools or o is None or h is None or l is None or c is None
                or atr is None or atr <= 0 or c.size < 1):
            return VETO
        oo, hh, ll, cc = float(o[-1]), float(h[-1]), float(l[-1]), float(c[-1])
        body = abs(cc - oo)
        up_wick = hh - max(oo, cc)
        dn_wick = min(oo, cc) - ll
        rng = hh - ll
        if rng <= 0:
            return (0, 0.0, "شمعة بلا مدى")
        highs = [float(p["price"]) for p in pools if p.get("side") == "high"]
        lows = [float(p["price"]) for p in pools if p.get("side") == "low"]
        tol = 0.25 * atr
        # اصطياد قمّة: ذيل علويّ طويل اخترق بركة قمم ثمّ أغلق تحتها
        if highs and up_wick > 1.4 * body and up_wick > 0.15 * atr:
            hit = any(hh >= hp - tol and cc < hp for hp in highs)
            if hit:
                conf = _clamp(0.45 + 0.3 * min(1.0, up_wick / (rng or 1)))
                return (-1, conf, "ذيل علويّ اصطاد قمم سيولة ⇒ عكس هبوطيّ")
        # اصطياد قاع: ذيل سفليّ طويل اخترق بركة قيعان ثمّ أغلق فوقها
        if lows and dn_wick > 1.4 * body and dn_wick > 0.15 * atr:
            hit = any(ll <= lp + tol and cc > lp for lp in lows)
            if hit:
                conf = _clamp(0.45 + 0.3 * min(1.0, dn_wick / (rng or 1)))
                return (1, conf, "ذيل سفليّ اصطاد قيعان سيولة ⇒ عكس صعوديّ")
        return (0, 0.1, "لا ذيل اصطياد مؤكّد عند بركة")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# التسجيل الموحّد
# ----------------------------------------------------------------------------
AGENTS = [
    ("liq_pool_target",        "liquidity", agent_liq_pool_target,        1.0),
    ("sweep_then_reverse",     "liquidity", agent_sweep_then_reverse,     1.0),
    ("equal_highs_lows_draw",  "liquidity", agent_equal_highs_lows_draw,  1.0),
    ("poc_liquidity_magnet",   "liquidity", agent_poc_liquidity_magnet,   1.0),
    ("stop_hunt_wick",         "liquidity", agent_stop_hunt_wick,         1.0),
]
