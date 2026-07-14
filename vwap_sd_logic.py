# -*- coding: utf-8 -*-
"""
vwap_sd_logic — منطق نطاقات VWAP بالانحراف المعياري (وحدة نقية، بلا MetaTrader5).

الفضل: الإطار الثلاثي لـ Zak Elga — «النطاق ليس الإشارة، بل نقطة اهتمام»:
  1) السياق: هل اليوم متوازن (Balanced) أم متجه؟ التلاشي ممنوع في يوم متجه.
  2) الموقع: سيولة تُكنَس خلف نطاق ±2SD ثم ترتد (Sweep + Snap-back).
  3) العدوان: تدفق أوامر عدواني بعد الارتداد (انقلاب دلتا التكات + قفزة معدل التكات
     كوكيل عن جدار Iceberg).

ملاحظة صدق: تلاشي العودة-للمتوسط يموت في أيام الترند — مرشِّح السياق هو
الاستراتيجية نفسها، وليس النطاق. بدون فلتر التوازن هذه مجرد وصفة لخسارة منتظمة.

وحدة نقية: مصفوفات/قوائم فقط (duck-typed مثل مصفوفات mt5 الهيكلية)، لا كتابة ملفات.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------- helpers

_VOL_KEYS = ("tick_volume", "real_volume", "volume", "vol")


def _field(rec, names, default=None):
    """قراءة حقل من dict / numpy structured record / كائن — duck-typed."""
    if isinstance(names, str):
        names = (names,)
    for n in names:
        try:
            return float(rec[n])
        except Exception:
            pass
        try:
            return float(getattr(rec, n))
        except Exception:
            pass
    if default is not None:
        return float(default)
    raise KeyError("missing field(s): %r" % (names,))


def _bar_hlc3_vol(bar):
    h = _field(bar, "high")
    l = _field(bar, "low")
    c = _field(bar, "close")
    v = _field(bar, _VOL_KEYS, default=1.0)
    if v <= 0:
        v = 1.0
    return (h + l + c) / 3.0, c, v


def _tick_price(t):
    last = _field(t, "last", default=0.0)
    if last > 0:
        return last
    bid = _field(t, "bid", default=0.0)
    ask = _field(t, "ask", default=0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return bid


# ---------------------------------------------------- 1) VWAP + SD bands

def session_vwap_bands(bars):
    """VWAP الجلسة ونطاقات ±1/2/3 انحراف معياري (تراكمي منذ بداية الجلسة)."""
    if bars is None or len(bars) == 0:
        raise ValueError("session_vwap_bands: no bars")
    s_pv = s_v = s_pv2 = 0.0
    for b in bars:
        p, _c, v = _bar_hlc3_vol(b)
        s_pv += p * v
        s_v += v
        s_pv2 += p * p * v
    vwap = s_pv / s_v if s_v > 0 else 0.0
    var = max(s_pv2 / s_v - vwap * vwap, 0.0) if s_v > 0 else 0.0
    sd = math.sqrt(var)
    return {
        "vwap": vwap, "sd": sd,
        "b1u": vwap + sd, "b1l": vwap - sd,
        "b2u": vwap + 2 * sd, "b2l": vwap - 2 * sd,
        "b3u": vwap + 3 * sd, "b3l": vwap - 3 * sd,
    }


# ---------------------------------------------------- 2) day context

def day_context(bars_today, atr10_daily):
    """هل اليوم متوازن؟ 4 فحوص، متوازن = 3/4 على الأقل. يوم غير متوازن ⇒ التلاشي ممنوع."""
    reasons = []
    n = len(bars_today) if bars_today is not None else 0
    if n < 8:
        return {"balanced": False, "score": 0,
                "reasons": ["✗ بيانات غير كافية (%d شمعة < 8)" % n]}
    closes, day_hi, day_lo = [], -1e18, 1e18
    for b in bars_today:
        _p, c, _v = _bar_hlc3_vol(b)
        closes.append(c)
        day_hi = max(day_hi, _field(b, "high"))
        day_lo = min(day_lo, _field(b, "low"))
    full = session_vwap_bands(bars_today)
    vwap, sd = full["vwap"], full["sd"]
    score = 0

    # (a) نسبة نطاق اليوم إلى ATR اليومي
    if atr10_daily and atr10_daily > 0:
        rr = (day_hi - day_lo) / atr10_daily
        ok = rr < 1.1
        reasons.append("%s نطاق اليوم/ATR10 = %.2f (مطلوب < 1.10)" % ("✓" if ok else "✗", rr))
    else:
        ok = False
        reasons.append("✗ ATR10 اليومي غير صالح — فحص النطاق فشل احترازيًا")
    score += 1 if ok else 0

    # (b) انحدار VWAP مسطّح: مقارنة مع vwap عند 25% من الجلسة
    i25 = max(1, n // 4)
    vwap25 = session_vwap_bands(bars_today[:i25])["vwap"]
    drift = abs(vwap - vwap25)
    ok = drift <= 0.35 * sd + 1e-12
    reasons.append("%s انجراف VWAP عن ربع الجلسة = %.4f (السقف 0.35×SD = %.4f)"
                   % ("✓" if ok else "✗", drift, 0.35 * sd))
    score += 1 if ok else 0

    # (c) الوقت داخل القيمة: نسبة الإغلاقات ضمن ±1SD
    inside = sum(1 for c in closes if abs(c - vwap) <= sd + 1e-12)
    frac = inside / float(n)
    ok = frac >= 0.55
    reasons.append("%s نسبة الإغلاقات داخل ±1SD = %.2f (مطلوب ≥ 0.55)" % ("✓" if ok else "✗", frac))
    score += 1 if ok else 0

    # (d) لا إصرار أحادي الاتجاه: أطول سلسلة إغلاقات M5 بنفس الاتجاه
    streak = best = 0
    prev_dir = 0
    for i in range(1, n):
        d = 1 if closes[i] > closes[i - 1] else (-1 if closes[i] < closes[i - 1] else 0)
        streak = streak + 1 if (d != 0 and d == prev_dir) else (1 if d != 0 else 0)
        prev_dir = d
        best = max(best, streak)
    ok = best < 8
    reasons.append("%s أطول سلسلة أحادية = %d شمعة (مطلوب < 8)" % ("✓" if ok else "✗", best))
    score += 1 if ok else 0

    balanced = score >= 3
    if not balanced:
        reasons.append("✗ اليوم غير متوازن ⇒ التلاشي (fade) ممنوع — هذا هو الدرس الجوهري")
    return {"balanced": balanced, "score": score, "reasons": reasons}


# ------------------------------------------- 3) sweep + aggression flip

_DEF_CFG = {"window_s": 90.0, "pierce_frac": 0.15, "sd": None,
            "delta_ratio": 0.62, "rate_mult": 1.5}


def detect_sweep_reversal(ticks, band_price, side, cfg=None):
    """كنس سيولة خلف النطاق + ارتداد + عدوان (وكيل Iceberg). دالة نقية على تكات معطاة."""
    c = dict(_DEF_CFG)
    if cfg:
        c.update(cfg)
    out = {"sweep": False, "aggression": False, "confirmed": False,
           "delta": 0.0, "reasons": []}
    if ticks is None or len(ticks) < 5:
        out["reasons"].append("✗ تكات غير كافية")
        return out
    ts = [_field(t, "time_msc") / 1000.0 for t in ticks]
    px = [_tick_price(t) for t in ticks]
    vol = [max(_field(t, _VOL_KEYS, default=1.0), 1.0) for t in ticks]
    t_end = ts[-1]
    keep = [i for i in range(len(ts)) if ts[i] >= t_end - float(c["window_s"])]
    ts = [ts[i] for i in keep]; px = [px[i] for i in keep]; vol = [vol[i] for i in keep]
    n = len(px)
    sd = c["sd"]
    if not sd or sd <= 0:  # تقدير احتياطي من تشتت التكات نفسها
        m = sum(px) / n
        sd = math.sqrt(max(sum((p - m) ** 2 for p in px) / n, 1e-12))
    pierce = float(c["pierce_frac"]) * sd
    up = (side == "upper")
    beyond = [(p >= band_price + pierce) if up else (p <= band_price - pierce) for p in px]
    if not any(beyond):
        out["reasons"].append("✗ لا اختراق خلف النطاق ≥ %.4f" % pierce)
        return out
    i_first = beyond.index(True)
    i_ext = max(range(n), key=lambda i: px[i] if up else -px[i])
    j = None  # أول عودة عبر النطاق بعد قمة/قاع الكنس
    for k in range(i_ext + 1, n):
        if (px[k] <= band_price) if up else (px[k] >= band_price):
            j = k
            break
    if j is None:
        out["reasons"].append("✗ اختراق بلا عودة عبر النطاق (لا snap-back) ⇒ ليس كنسًا")
        return out
    out["sweep"] = True
    out["reasons"].append("✓ كنس: اختراق %.4f ثم عودة عبر النطاق" % (abs(px[i_ext] - band_price)))

    # عدوان بعد الارتداد: دلتا حجم التكات + قفزة معدل التكات
    upv = dnv = 0.0
    for k in range(j, n):
        dp = px[k] - px[k - 1]
        if dp > 0:
            upv += vol[k]
        elif dp < 0:
            dnv += vol[k]
    tot = upv + dnv
    frac = ((dnv if up else upv) / tot) if tot > 0 else 0.0
    out["delta"] = frac
    d_ok = frac >= float(c["delta_ratio"])
    out["reasons"].append("%s دلتا اتجاه التلاشي = %.2f (مطلوب ≥ %.2f)"
                          % ("✓" if d_ok else "✗", frac, float(c["delta_ratio"])))
    pre_n = i_first
    pre_dur = ts[i_first - 1] - ts[0] if pre_n >= 2 else 0.0
    post_n = n - j
    post_dur = ts[-1] - ts[j]
    if pre_n >= 2 and pre_dur > 0 and post_n >= 2 and post_dur > 0:
        pre_rate = (pre_n - 1) / pre_dur
        post_rate = (post_n - 1) / post_dur
        r_ok = post_rate >= float(c["rate_mult"]) * pre_rate
        out["reasons"].append("%s معدل التكات بعد/قبل = %.2f/%.2f (مطلوب ×%.1f)"
                              % ("✓" if r_ok else "✗", post_rate, pre_rate, float(c["rate_mult"])))
    else:
        r_ok = False
        out["reasons"].append("✗ عيّنات غير كافية لقياس معدل التكات")
    out["aggression"] = bool(d_ok and r_ok)
    out["confirmed"] = bool(out["sweep"] and out["aggression"])
    return out


# ---------------------------------------------------- 4) fade geometry

def fade_geometry(band2, band3, vwap, side):
    """هندسة الصفقة: دخول عند/داخل ±2SD، وقف خلف ±3SD + هامش، هدف = VWAP.
    على المستدعي رفض الصفقة إذا rr < 1.0."""
    sd = abs(float(band3) - float(band2))  # المسافة بين النطاقين = 1×SD
    entry_mid = float(band2)
    lo, hi = entry_mid - 0.25 * sd, entry_mid + 0.25 * sd
    if side == "upper":
        sl = float(band3) + 0.1 * sd
    else:
        sl = float(band3) - 0.1 * sd
    tp = float(vwap)
    risk = abs(entry_mid - sl)
    reward = abs(tp - entry_mid)
    rr = reward / risk if risk > 1e-12 else 0.0
    return {"entry_zone": (lo, hi), "sl": sl, "tp": tp, "rr": rr}


# ---------------------------------------------------------- self-tests

if __name__ == "__main__":
    def bar(h, l, c, v=100.0):
        return {"high": h, "low": l, "close": c, "tick_volume": v}

    def tick(t_ms, p, v=1.0):
        return {"time_msc": t_ms, "bid": p, "ask": p + 0.1, "last": 0.0,
                "volume": v, "flags": 0}

    # 1) يوم مسطّح متوازن
    pat = [3000.0, 3000.5, 3001.0, 3000.5, 3000.0, 2999.5, 2999.0, 2999.5]
    flat = [bar(c + 0.2, c - 0.2, c) for c in pat * 9]
    ctx = day_context(flat, atr10_daily=10.0)
    assert ctx["balanced"] and ctx["score"] >= 3, ctx

    # 2) يوم ترند صاعد قوي ⇒ غير متوازن ⇒ التلاشي ممنوع
    ramp = [bar(3000 + 2 * i + 0.5, 3000 + 2 * i - 0.5, 3000 + 2 * i) for i in range(72)]
    ctx2 = day_context(ramp, atr10_daily=10.0)
    assert not ctx2["balanced"], ctx2

    # 3) كنس علوي + ارتداد + عدوان هبوطي ⇒ confirmed
    band, sd = 3010.0, 2.0
    t0 = 1_000_000
    tk = [tick(t0 + i * 1000, 3008.0 + (0.2 if i % 2 else -0.2)) for i in range(40)]
    tk += [tick(t0 + 40_000, 3009.5), tick(t0 + 40_400, 3010.1),
           tick(t0 + 40_800, 3010.6), tick(t0 + 41_200, 3010.9)]  # اختراق ≥ 0.3
    p = 3010.2
    for k in range(30):  # هبوط كثيف: معدل 5 تكات/ث وحجم بيعي مهيمن
        if k % 5 == 4:
            p += 0.03
            tk.append(tick(t0 + 42_000 + k * 200, p, v=1.0))
        else:
            p -= 0.12
            tk.append(tick(t0 + 42_000 + k * 200, p, v=3.0))
    res = detect_sweep_reversal(tk, band, "upper", {"sd": sd})
    assert res["sweep"] and res["aggression"] and res["confirmed"], res

    # 4) اختراق بلا عودة ⇒ sweep=False
    tk2 = [tick(t0 + i * 1000, 3008.0) for i in range(40)]
    tk2 += [tick(t0 + 40_000 + k * 500, 3010.6 + 0.05 * k) for k in range(20)]
    res2 = detect_sweep_reversal(tk2, band, "upper", {"sd": sd})
    assert not res2["sweep"] and not res2["confirmed"], res2

    # 5) سعر ثابت: vwap == السعر و sd≈0 بلا قسمة على صفر
    const = [bar(3000.0, 3000.0, 3000.0) for _ in range(20)]
    vb = session_vwap_bands(const)
    assert abs(vb["vwap"] - 3000.0) < 1e-9 and vb["sd"] < 1e-9, vb
    assert abs(vb["b3u"] - vb["vwap"]) < 1e-9

    # 6) هندسة التلاشي
    g = fade_geometry(band2=3004.0, band3=3006.0, vwap=3000.0, side="upper")
    assert g["sl"] > 3006.0 and g["tp"] == 3000.0 and g["rr"] > 1.0, g
    g0 = fade_geometry(3000.0, 3000.0, 3000.0, "upper")  # منحلّ: بلا قسمة على صفر
    assert g0["rr"] == 0.0, g0

    print("OK — vwap_sd_logic self-tests passed")
