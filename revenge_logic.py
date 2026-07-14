# -*- coding: utf-8 -*-
"""revenge_logic.py — 🗡️ ثأر القنّاص المنضبط (وحدة نقيّة بلا MT5 — يستوردها R Core)
=====================================================================================
«اجعله يتنقم أيضاً» (طلب المستخدم 2026-07-06) — لكن ثأر القنّاص لا ثأر المقامر:
البيانات المقيسة تقول: الانتقام الأعمى (إعادة دخول فوريّة/مضاعفة بعد خسارة) هو القاتل
رقم 1 ليد المستخدم (style_miner: −$48k). لذلك الثأر هنا مشروط بالدليل، لا يُضاعِف
الحجم أبداً، لا يعكس الاتجاه أبداً، ويُقفَل أشدّ إذا فشل.

ثلاث آليّات:
1) ثأر صيد-الستوب: ستوب ضُرب بذيلٍ ثم عاد السعر عبر سعر الدخول الأصليّ بالاتجاه نفسه
   خلال النافذة ⇒ الأطروحة كانت صحيحة والسوق «صادنا» ⇒ إعادة دخول بنفس الحجم (لا أكبر).
2) وضع المطاردة: التبريد (خسارتان متتاليتان) لا يعني الهروب التامّ — يُكسَر فقط
   بإشارة A+ (توافق مستويات ≥ hunt_min_score) وبنصف الحجم وطلقة واحدة للرمز.
3) قفل التصعيد: فشل طلقة الثأر ⇒ قفل الثأر لهذا الرمز حتى نهاية اليوم (لا سلسلة انتقام).

كل الدوالّ نقيّة الحالة (تتلقّى dict وتُحدّثه) — قابلة للاختبار بلا سوق. python revenge_logic.py = اختبار ذاتيّ.
"""


def new_state():
    """حالة الثأر داخل ذاكرة المحرّك (تُصفَّر مع كل يوم جديد)."""
    return {"stopouts": {}, "avenged_today": 0, "day": "", "hunt_used": {}, "locked": {}}


def _roll_day(st, day):
    if st.get("day") != day:
        st["day"] = day
        st["avenged_today"] = 0
        st["hunt_used"] = {}
        st["locked"] = {}


def record_stop_out(st, sym, direction, entry_px, sl_px, ts, day):
    """سجّل خروجاً خاسراً (ستوب/إغلاق سالب) كمرشّح ثأر. يحتفظ بآخر 5 لكل رمز."""
    _roll_day(st, day)
    lst = st["stopouts"].setdefault(sym, [])
    lst.append({"dir": 1 if int(direction) > 0 else -1, "entry": float(entry_px),
                "sl": float(sl_px), "ts": float(ts), "avenged": False})
    del lst[:-5]


def check_stop_hunt_reentry(st, sym, px, now, cfg, day):
    """🗡️ ثأر صيد-الستوب: أحدث ستوب غير مُثأر ضمن النافذة، والسعر عاد عبر سعر الدخول
    الأصليّ بالاتجاه نفسه ⇒ dict إعادة دخول بنفس الأطروحة، وإلا None.
    الضمانات: نفس الاتجاه دائماً، size_mult=1.0 دائماً (لا مضاعفة)، سقف يوميّ، قفل تصعيد."""
    _roll_day(st, day)
    if not cfg or not cfg.get("enabled", True):
        return None
    if st["avenged_today"] >= int(cfg.get("max_per_day", 3)):
        return None
    if st["locked"].get(sym):
        return None
    win_s = float(cfg.get("window_min", 30)) * 60.0
    for so in reversed(st["stopouts"].get(sym, [])):
        if so["avenged"] or (now - so["ts"]) > win_s:
            continue
        d = so["dir"]
        # عاد السعر عبر سعر الدخول الأصليّ بالاتجاه نفسه = الذيل صادنا والاتجاه كان صحيحاً
        crossed = (px >= so["entry"]) if d > 0 else (px <= so["entry"])
        if crossed:
            so["avenged"] = True
            st["avenged_today"] += 1
            return {"dir": d, "size_mult": 1.0, "kind": "stop_hunt",
                    "orig_entry": so["entry"],
                    "reason": f"🗡️ ثأر صيد-الستوب: السعر عاد عبر الدخول {so['entry']:.2f} بالاتجاه الأصليّ"}
    return None


def hunt_gate(st, sym, cooled, trigger_score, cfg, day):
    """🎯 وضع المطاردة: أثناء التبريد، اسمح بطلقة ثأر واحدة فقط إن كانت الإشارة A+.
    يعيد (allowed: bool, size_mult: float, note: str). خارج التبريد: مرور طبيعيّ كامل."""
    _roll_day(st, day)
    if not cooled:
        return True, 1.0, ""
    if not cfg or not cfg.get("enabled", True):
        return False, 0.0, "تبريد (الثأر مُطفأ)"
    if st["locked"].get(sym):
        return False, 0.0, "🔒 قفل تصعيد: فشل ثأرٌ سابق — تبريد صارم حتى نهاية اليوم"
    if st["hunt_used"].get(sym):
        return False, 0.0, "طلقة المطاردة استُهلكت لهذا الرمز"
    if int(trigger_score) >= int(cfg.get("hunt_min_score", 3)):
        st["hunt_used"][sym] = True
        return True, float(cfg.get("hunt_size_mult", 0.5)), "🎯 طلقة مطاردة A+ (نصف الحجم، طلقة واحدة)"
    return False, 0.0, f"تبريد — لا يُكسَر إلا بإشارة A+ (توافق≥{cfg.get('hunt_min_score', 3)})"


def revenge_failed(st, sym, day=None):
    """طلقة الثأر خسرت ⇒ قفل التصعيد للرمز حتى نهاية اليوم (يمنع سلسلة الانتقام)."""
    if day is not None:
        _roll_day(st, day)
    st["locked"][sym] = True


if __name__ == "__main__":
    # ── اختبار ذاتيّ نقيّ (بلا سوق) ──
    CFG = {"enabled": True, "window_min": 30, "max_per_day": 3,
           "hunt_min_score": 3, "hunt_size_mult": 0.5}
    st = new_state()
    D = "2026-07-06"

    # 1) ثأر صيد-الستوب: شراء 4150 ستوب 4146 — السعر يعود 4150.5 خلال النافذة ⇒ ثأر شراء
    record_stop_out(st, "XAUUSDm", 1, 4150.0, 4146.0, 1000.0, D)
    assert check_stop_hunt_reentry(st, "XAUUSDm", 4148.0, 1300.0, CFG, D) is None, "لم يعبر الدخول بعد"
    r = check_stop_hunt_reentry(st, "XAUUSDm", 4150.5, 1400.0, CFG, D)
    assert r and r["dir"] == 1 and r["size_mult"] == 1.0, "ثأر شراء بنفس الحجم"
    assert check_stop_hunt_reentry(st, "XAUUSDm", 4151.0, 1500.0, CFG, D) is None, "ثأر واحد لكل ستوب"

    # 2) خارج النافذة ⇒ لا ثأر
    record_stop_out(st, "XAUUSDm", -1, 4140.0, 4144.0, 2000.0, D)
    assert check_stop_hunt_reentry(st, "XAUUSDm", 4139.0, 2000.0 + 31 * 60, CFG, D) is None, "انتهت النافذة"

    # 3) بيع: ستوب 4144 دخول 4140 — السعر يهبط 4139.5 ⇒ ثأر بيع (نفس الاتجاه، لا انعكاس)
    record_stop_out(st, "XAUUSDm", -1, 4140.0, 4144.0, 3000.0, D)
    r = check_stop_hunt_reentry(st, "XAUUSDm", 4139.5, 3100.0, CFG, D)
    assert r and r["dir"] == -1, "ثأر بيع بالاتجاه الأصليّ"

    # 4) السقف اليوميّ: الثأر الثالث يمرّ والرابع يُرفض
    record_stop_out(st, "XAUUSDm", 1, 4160.0, 4156.0, 4000.0, D)
    assert check_stop_hunt_reentry(st, "XAUUSDm", 4160.5, 4100.0, CFG, D), "الثأر الثالث (السقف 3)"
    record_stop_out(st, "XAUUSDm", 1, 4170.0, 4166.0, 5000.0, D)
    assert check_stop_hunt_reentry(st, "XAUUSDm", 4170.5, 5100.0, CFG, D) is None, "سقف اليوم استُهلك"

    # 5) وضع المطاردة: التبريد يُكسَر فقط بإشارة A+ وبنصف الحجم وطلقة واحدة
    st2 = new_state()
    ok, mult, note = hunt_gate(st2, "XAUUSDm", True, 2, CFG, D)
    assert not ok, "إشارة عاديّة لا تكسر التبريد"
    ok, mult, note = hunt_gate(st2, "XAUUSDm", True, 3, CFG, D)
    assert ok and mult == 0.5, "A+ تكسر التبريد بنصف الحجم"
    ok, _, _ = hunt_gate(st2, "XAUUSDm", True, 4, CFG, D)
    assert not ok, "طلقة واحدة فقط"
    ok, mult, _ = hunt_gate(st2, "XAUUSDm", False, 0, CFG, D)
    assert ok and mult == 1.0, "خارج التبريد: مرور طبيعيّ"

    # 6) قفل التصعيد: فشل الثأر ⇒ لا ثأر ولا مطاردة لبقيّة اليوم
    st3 = new_state()
    record_stop_out(st3, "XAUUSDm", 1, 4150.0, 4146.0, 1000.0, D)
    revenge_failed(st3, "XAUUSDm", D)
    assert check_stop_hunt_reentry(st3, "XAUUSDm", 4150.5, 1100.0, CFG, D) is None, "مقفول بعد فشل"
    ok, _, _ = hunt_gate(st3, "XAUUSDm", True, 5, CFG, D)
    assert not ok, "المطاردة مقفولة بعد فشل"

    # 7) يوم جديد ⇒ كل الأقفال تُصفَّر
    ok, mult, _ = hunt_gate(st3, "XAUUSDm", True, 3, CFG, "2026-07-07")
    assert ok and mult == 0.5, "يوم جديد يصفّر الأقفال"

    print("✅ revenge_logic self-test OK — ثأر القنّاص: دليل، لا مضاعفة، لا انعكاس، قفل تصعيد")
