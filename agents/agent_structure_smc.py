# -*- coding: utf-8 -*-
"""
وكلاء الفئة: structure_smc — 10 وكلاء نقيّون لحظيّون.

كل وكيل دالة نقيّة: agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

ctx قاموس جاهز فيه (كلّها اختياريّة — الوكيل دفاعيّ ضد أي نقص):
  sym         : اسم الرمز (str)
  price       : السعر الحاليّ (float)
  atr_m5      : ATR على m5 (float)
  spread      : السبريد بوحدة السعر (float)
  m1/m5/m15/h1: قواميس {o,h,l,c,v} مصفوفات numpy لآخر ~200 شمعة
  smc / حقول نبض SMC: bos, choch, ob, fvg, liq_pools, sweeps, poc  (من market_pulse.json)
  structure   : {bos, swing_high, swing_low}

قاعدة صارمة: غياب البيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
كلّ وكيل يحسب زاويته فقط ويرجع تصويته. يجب أن يعمل 100 وكيل × 17 عملة في <100ms.
"""
import numpy as np

_EMPTY = (0, 0.0, "بيانات ناقصة")


# ------------------------------- أدوات داخليّة -------------------------------

def _price(ctx):
    """السعر الحاليّ من ctx أو من آخر إغلاق m5."""
    p = ctx.get("price")
    if p is not None:
        try:
            p = float(p)
            if np.isfinite(p) and p > 0:
                return p
        except (TypeError, ValueError):
            pass
    c = _closes(ctx, "m5")
    if c is not None and c.size:
        return float(c[-1])
    return None


def _closes(ctx, tf):
    """مصفوفة إغلاقات الفريم tf أو None."""
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
    if a.size == 0 or not np.all(np.isfinite(a)):
        # نظّف اللانهائيّات إن وُجدت جزئيّاً
        a = a[np.isfinite(a)]
        if a.size == 0:
            return None
    return a


def _atr(ctx):
    """ATR m5 من ctx (نطاق مرجعيّ للقرب)، أو تقدير من الإغلاقات، أو None."""
    a = ctx.get("atr_m5")
    if a is not None:
        try:
            a = float(a)
            if np.isfinite(a) and a > 0:
                return a
        except (TypeError, ValueError):
            pass
    c = _closes(ctx, "m5")
    if c is not None and c.size >= 15:
        d = np.abs(np.diff(c[-15:]))
        if d.size:
            m = float(np.mean(d))
            if np.isfinite(m) and m > 0:
                return m
    return None


def _smc(ctx):
    """قاموس نبض smc سواء كان مضمَّناً تحت مفتاح 'smc' أو مسطّحاً في ctx."""
    s = ctx.get("smc")
    if isinstance(s, dict):
        return s
    # قد تكون الحقول مسطّحة مباشرةً في ctx
    if any(k in ctx for k in ("bos", "choch", "ob", "fvg", "liq_pools", "sweeps", "poc")):
        return ctx
    return {}


def _proximity_conf(dist, atr, floor=0.15, cap=0.9):
    """يحوّل مسافة السعر عن مستوى (بوحدة السعر) إلى ثقة 0..1 عبر ATR.
    قريب جداً ⇒ ثقة عالية؛ بعيد ⇒ ثقة منخفضة. غياب ATR ⇒ ثقة متوسّطة ثابتة.
    """
    if atr is None or atr <= 0:
        return 0.4
    r = abs(dist) / atr  # المسافة بوحدات ATR
    conf = float(np.clip(1.0 - r / 3.0, floor, cap))  # 0 ATR→cap، 3 ATR→floor
    return conf


# ================================ الوكلاء ================================

def agent_bos_align(ctx):
    """آخر BOS من نبض smc: اتجاهه هو التصويت، الثقة = قربه بالمؤشّر (idx الأحدث + قرب السعر)."""
    try:
        smc = _smc(ctx)
        bos = smc.get("bos")
        if not bos:
            return _EMPTY
        last = bos[-1]  # الأحدث
        d = int(last.get("dir", 0))
        if d == 0:
            return (0, 0.0, "BOS بلا اتجاه")
        price = _price(ctx)
        atr = _atr(ctx)
        lvl = last.get("price")
        conf = 0.55
        if price is not None and lvl is not None and atr:
            conf = _proximity_conf(price - float(lvl), atr, floor=0.3, cap=0.85)
        else:
            conf = 0.55
        side = "صاعد" if d > 0 else "هابط"
        return (int(np.sign(d)), float(conf), "آخر BOS %s عند %.5g" % (side, float(lvl) if lvl is not None else 0.0))
    except Exception:
        return _EMPTY


def agent_choch_flip(ctx):
    """آخر CHoCH يقلب التحيّز؛ يصوّت باتجاه القلب الجديد."""
    try:
        smc = _smc(ctx)
        choch = smc.get("choch")
        if not choch:
            return _EMPTY
        last = choch[-1]
        d = int(last.get("dir", 0))
        if d == 0:
            return (0, 0.0, "CHoCH بلا اتجاه")
        price = _price(ctx)
        atr = _atr(ctx)
        lvl = last.get("price")
        # CHoCH إشارة تحوّل قويّة نسبياً؛ نعطيها ثقة أساس أعلى قليلاً
        conf = 0.6
        if price is not None and lvl is not None and atr:
            conf = _proximity_conf(price - float(lvl), atr, floor=0.35, cap=0.9)
        side = "صاعد" if d > 0 else "هابط"
        return (int(np.sign(d)), float(conf), "CHoCH قلب %s عند %.5g" % (side, float(lvl) if lvl is not None else 0.0))
    except Exception:
        return _EMPTY


def agent_ob_unmitigated_pull(ctx):
    """أقرب order-block غير مُخفَّف (mitigated=false): السعر يُجذَب لجهته."""
    try:
        smc = _smc(ctx)
        obs = smc.get("ob")
        price = _price(ctx)
        atr = _atr(ctx)
        if not obs or price is None:
            return _EMPTY
        best = None
        best_dist = None
        for ob in obs:
            if ob.get("mitigated"):
                continue
            lo = ob.get("lo")
            hi = ob.get("hi")
            if lo is None or hi is None:
                continue
            mid = (float(lo) + float(hi)) / 2.0
            dist = abs(price - mid)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = (ob, mid)
        if best is None:
            return (0, 0.0, "لا كتلة غير مخفَّفة")
        ob, mid = best
        # الجذب نحو الكتلة: إن كان السعر فوقها ⇒ جذب هابط، تحتها ⇒ جذب صاعد
        if abs(price - mid) < 1e-9:
            vote = int(np.sign(ob.get("dir", 0)))
        else:
            vote = -1 if price > mid else 1
        if vote == 0:
            return (0, 0.0, "كتلة عند السعر")
        conf = _proximity_conf(best_dist, atr, floor=0.2, cap=0.85)
        return (vote, float(conf), "جذب لكتلة غير مخفَّفة عند %.5g" % mid)
    except Exception:
        return _EMPTY


def agent_ob_reject(ctx):
    """ارتداد السعر من حافة OB بنفس اتجاه الـ dir للكتلة."""
    try:
        smc = _smc(ctx)
        obs = smc.get("ob")
        price = _price(ctx)
        atr = _atr(ctx)
        if not obs or price is None or not atr:
            return _EMPTY
        near_band = 0.5 * atr  # قرب حافّة الكتلة
        best = None
        best_dist = None
        for ob in obs:
            lo = ob.get("lo")
            hi = ob.get("hi")
            d = int(ob.get("dir", 0))
            if lo is None or hi is None or d == 0:
                continue
            lo = float(lo); hi = float(hi)
            # المسافة إلى أقرب حافّة
            edge = lo if abs(price - lo) < abs(price - hi) else hi
            dist = abs(price - edge)
            if dist <= near_band and (best_dist is None or dist < best_dist):
                best_dist = dist
                best = (ob, d, edge)
        if best is None:
            return (0, 0.0, "لا ارتداد كتلة")
        ob, d, edge = best
        conf = _proximity_conf(best_dist, atr, floor=0.3, cap=0.9)
        side = "صاعد" if d > 0 else "هابط"
        return (int(np.sign(d)), float(conf), "ارتداد كتلة %s من %.5g" % (side, edge))
    except Exception:
        return _EMPTY


def agent_fvg_unfilled_pull(ctx):
    """فجوة FVG بـ filled منخفض قرب السعر؛ يصوّت لملء الفجوة باتجاهها."""
    try:
        smc = _smc(ctx)
        fvgs = smc.get("fvg")
        price = _price(ctx)
        atr = _atr(ctx)
        if not fvgs or price is None:
            return _EMPTY
        best = None
        best_dist = None
        for f in fvgs:
            if f.get("inverted"):
                continue
            filled = f.get("filled", 0.0)
            try:
                filled = float(filled)
            except (TypeError, ValueError):
                filled = 0.0
            if filled >= 0.7:  # شبه مملوءة — لا جذب يُذكر
                continue
            lo = f.get("lo"); hi = f.get("hi")
            if lo is None or hi is None:
                continue
            mid = (float(lo) + float(hi)) / 2.0
            dist = abs(price - mid)
            # الأولويّة للأقرب والأقلّ ملئاً
            key = dist * (0.5 + filled)
            if best_dist is None or key < best_dist:
                best_dist = key
                best = (f, mid, filled)
        if best is None:
            return (0, 0.0, "لا فجوة مفتوحة")
        f, mid, filled = best
        d = int(f.get("dir", 0))
        # الجذب نحو منتصف الفجوة
        if abs(price - mid) < 1e-9:
            vote = int(np.sign(d))
        else:
            vote = 1 if price < mid else -1
        if vote == 0:
            return (0, 0.0, "فجوة عند السعر")
        conf = _proximity_conf(abs(price - mid), atr, floor=0.2, cap=0.8) * (1.0 - 0.5 * filled)
        conf = float(np.clip(conf, 0.0, 0.8))
        return (vote, conf, "جذب لفجوة مفتوحة (ملء %.0f%%) عند %.5g" % (filled * 100, mid))
    except Exception:
        return _EMPTY


def agent_fvg_inverted_signal(ctx):
    """FVG مقلوبة (inverted=true) كإشارة تحوّل هيكليّ عكسيّ.
    الفجوة المقلوبة تفقد دورها كدعم/مقاومة وتنعكس ⇒ نصوّت عكس اتجاهها الأصليّ.
    """
    try:
        smc = _smc(ctx)
        fvgs = smc.get("fvg")
        price = _price(ctx)
        atr = _atr(ctx)
        if not fvgs or price is None:
            return _EMPTY
        best = None
        best_dist = None
        for f in fvgs:
            if not f.get("inverted"):
                continue
            lo = f.get("lo"); hi = f.get("hi")
            d = int(f.get("dir", 0))
            if lo is None or hi is None or d == 0:
                continue
            mid = (float(lo) + float(hi)) / 2.0
            dist = abs(price - mid)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = (d, mid)
        if best is None:
            return (0, 0.0, "لا فجوة مقلوبة")
        d, mid = best
        vote = -int(np.sign(d))  # الانعكاس
        conf = _proximity_conf(best_dist, atr, floor=0.25, cap=0.75)
        side = "صاعد" if vote > 0 else "هابط"
        return (vote, float(conf), "فجوة مقلوبة ⇒ تحوّل %s عند %.5g" % (side, mid))
    except Exception:
        return _EMPTY


def agent_structure_bos_pulse(ctx):
    """حقل structure.bos المباشر من النبض مع swing_high/low كإطار."""
    try:
        st = ctx.get("structure")
        if not isinstance(st, dict):
            return _EMPTY
        bos = st.get("bos", 0)
        try:
            bos = int(bos)
        except (TypeError, ValueError):
            return _EMPTY
        if bos == 0:
            return (0, 0.0, "بنية محايدة")
        price = _price(ctx)
        atr = _atr(ctx)
        sh = st.get("swing_high"); sl = st.get("swing_low")
        conf = 0.5
        # قوّة أعلى كلّما اقترب السعر من حافّة الكسر (swing المقابل للاتجاه)
        if price is not None and atr and sh is not None and sl is not None:
            try:
                sh = float(sh); sl = float(sl)
                rng = max(sh - sl, 1e-9)
                if bos > 0:
                    pos = (price - sl) / rng   # قرب القمّة ⇒ أقوى للصعود
                else:
                    pos = (sh - price) / rng   # قرب القاع ⇒ أقوى للهبوط
                conf = float(np.clip(0.35 + 0.5 * pos, 0.2, 0.85))
            except (TypeError, ValueError):
                conf = 0.5
        side = "صاعد" if bos > 0 else "هابط"
        return (int(np.sign(bos)), float(conf), "بنية BOS %s (نبض)" % side)
    except Exception:
        return _EMPTY


def agent_swing_break(ctx):
    """كسر swing_high (شراء) أو swing_low (بيع) من حقل structure."""
    try:
        st = ctx.get("structure")
        if not isinstance(st, dict):
            return _EMPTY
        price = _price(ctx)
        atr = _atr(ctx)
        sh = st.get("swing_high"); sl = st.get("swing_low")
        if price is None or sh is None or sl is None:
            return _EMPTY
        sh = float(sh); sl = float(sl)
        if not (np.isfinite(sh) and np.isfinite(sl)) or sh <= sl:
            return (0, 0.0, "نطاق سوينغ غير صالح")
        if price > sh:
            dist = price - sh
            conf = float(np.clip(0.4 + (_proximity_conf(dist, atr) if atr else 0.2), 0.4, 0.9))
            return (1, conf, "كسر قمّة سوينغ %.5g" % sh)
        if price < sl:
            dist = sl - price
            conf = float(np.clip(0.4 + (_proximity_conf(dist, atr) if atr else 0.2), 0.4, 0.9))
            return (-1, conf, "كسر قاع سوينغ %.5g" % sl)
        # داخل النطاق — لا كسر
        return (0, 0.0, "داخل نطاق السوينغ")
    except Exception:
        return _EMPTY


def agent_smc_trend_bias(ctx):
    """حقل smc.trend الكليّ كتحيّز هيكليّ عام للرمز."""
    try:
        smc = _smc(ctx)
        tr = smc.get("trend")
        if tr is None:
            return _EMPTY
        try:
            tr = int(tr)
        except (TypeError, ValueError):
            return _EMPTY
        if tr == 0:
            return (0, 0.0, "اتجاه smc محايد")
        side = "صاعد" if tr > 0 else "هابط"
        return (int(np.sign(tr)), 0.5, "تحيّز smc %s" % side)
    except Exception:
        return _EMPTY


def agent_smc_summary_consensus(ctx):
    """اتّساق مجمل عناصر smc (bos+choch+ob+fvg) في اتجاه واحد.
    يجمع أصوات العناصر المتاحة ويصوّت بالأغلبيّة؛ الثقة = نسبة الاتّساق.
    """
    try:
        smc = _smc(ctx)
        if not smc:
            return _EMPTY
        votes = []
        bos = smc.get("bos")
        if bos:
            votes.append(int(np.sign(bos[-1].get("dir", 0))))
        choch = smc.get("choch")
        if choch:
            votes.append(int(np.sign(choch[-1].get("dir", 0))))
        # الكتلة غير المخفَّفة الأقرب (اتجاهها)
        obs = smc.get("ob")
        if obs:
            unm = [o for o in obs if not o.get("mitigated")]
            pool = unm if unm else obs
            if pool:
                votes.append(int(np.sign(pool[-1].get("dir", 0))))
        # الفجوة الأحدث غير المقلوبة
        fvgs = smc.get("fvg")
        if fvgs:
            fresh = [f for f in fvgs if not f.get("inverted")]
            if fresh:
                votes.append(int(np.sign(fresh[-1].get("dir", 0))))
        tr = smc.get("trend")
        if tr is not None:
            try:
                votes.append(int(np.sign(int(tr))))
            except (TypeError, ValueError):
                pass
        votes = [v for v in votes if v != 0]
        if not votes:
            return (0, 0.0, "عناصر smc محايدة")
        s = sum(votes)
        if s == 0:
            return (0, 0.0, "تعادل عناصر smc")
        direction = int(np.sign(s))
        agree = sum(1 for v in votes if v == direction)
        conf = float(np.clip(agree / len(votes), 0.0, 0.95))
        side = "صاعد" if direction > 0 else "هابط"
        return (direction, conf, "اتّساق smc %s (%d/%d)" % (side, agree, len(votes)))
    except Exception:
        return _EMPTY


# ------------------------------ سجلّ الفئة ------------------------------
CATEGORY = "structure_smc"
AGENTS = [
    ("bos_align",              CATEGORY, agent_bos_align,             1.0),
    ("choch_flip",             CATEGORY, agent_choch_flip,            1.0),
    ("ob_unmitigated_pull",    CATEGORY, agent_ob_unmitigated_pull,   1.0),
    ("ob_reject",              CATEGORY, agent_ob_reject,             1.0),
    ("fvg_unfilled_pull",      CATEGORY, agent_fvg_unfilled_pull,     1.0),
    ("fvg_inverted_signal",    CATEGORY, agent_fvg_inverted_signal,   1.0),
    ("structure_bos_pulse",    CATEGORY, agent_structure_bos_pulse,   1.0),
    ("swing_break",            CATEGORY, agent_swing_break,           1.0),
    ("smc_trend_bias",         CATEGORY, agent_smc_trend_bias,        1.0),
    ("smc_summary_consensus",  CATEGORY, agent_smc_summary_consensus, 1.0),
]
