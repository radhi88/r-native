# -*- coding: utf-8 -*-
"""candle_anatomy.py — تشريح تشكيلات الشموع على 1000 شمعة دقيقة + ماذا تسبق.

يقيس لكل شمعة: الجسم، الذيل العلوي/السفلي، المدى، الاتجاه، ويصنّفها (مطرقة/شهاب/ماروبوزو/
دوجي/مغزل/عادية). ثم يحلّل على 1000 شمعة: كل تشكيل، كم مرّة ظهر وما **متوسط حركة الشمعة
التالية** بعده (هل بُلِّغ صعوداً/هبوطاً) — فنعرف أيّ تشكيل تنبّئي فعلاً (لا تخمين).

جوهر أسلوب المستخدم: شمعة هبوطية كبيرة بذيل سفلي طويل = **رفض القاع = ارتداد صعودي قويّ**.
"""
from __future__ import annotations
import numpy as np
import MetaTrader5 as mt5


def _bars(sym, n=1000):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n + 2)
    if r is None or len(r) < 50:
        return None
    return r


def classify(o, h, l, c):
    """تشريح شمعة واحدة → (نمط, خصائص)."""
    rng = h - l
    if rng <= 0:
        return "flat", {}
    body = abs(c - o)
    uw = h - max(o, c)          # ذيل علوي
    lw = min(o, c) - l          # ذيل سفلي
    bp = body / rng             # نسبة الجسم
    uwp = uw / rng; lwp = lw / rng
    d = 1 if c > o else -1 if c < o else 0
    feat = {"body_pct": round(bp, 2), "uw_pct": round(uwp, 2), "lw_pct": round(lwp, 2), "dir": d}
    if bp < 0.1:
        pat = "doji"                                   # تردّد
    elif bp >= 0.85:
        pat = "marubozu_up" if d > 0 else "marubozu_dn"  # زخم قويّ صرف
    elif lwp >= 0.5 and uwp <= 0.2:
        pat = "hammer"                                 # 🔨 ذيل سفلي طويل = رفض القاع (صعودي)
    elif uwp >= 0.5 and lwp <= 0.2:
        pat = "shooting_star"                          # ⭐ ذيل علوي طويل = رفض القمة (هبوطي)
    elif bp < 0.3:
        pat = "spinning_top"                           # مغزل = تردّد
    else:
        pat = "body_up" if d > 0 else "body_dn"
    return pat, feat


def analyze(sym, n=1000):
    """على n شمعة: كل تشكيل → عدده + متوسط حركة الشمعة التالية (R بوحدات المدى) + % صعود التالي."""
    r = _bars(sym, n)
    if r is None:
        return None
    o, h, l, c = r["open"], r["high"], r["low"], r["close"]
    rng = np.maximum(h - l, 1e-9)
    stats = {}
    for i in range(len(r) - 2):
        pat, _ = classify(o[i], h[i], l[i], c[i])
        nxt = (c[i + 1] - c[i]) / rng[i]               # حركة الشمعة التالية بوحدات مدى الشمعة الحالية
        s = stats.setdefault(pat, [])
        s.append(nxt)
    out = {}
    for pat, vals in stats.items():
        a = np.array(vals); nn = len(a)
        m = float(a.mean()); sd = float(a.std())
        t = m / (sd / np.sqrt(nn)) if sd > 0 else 0.0
        out[pat] = {"n": nn, "next_avg": round(m, 4), "t": round(t, 2),
                    "up_pct": round(100 * float((a > 0).mean()))}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["t"]))


def last_signal(sym):
    """تشريح آخر شمعة مكتملة + تلميح ارتداد/استمرار (لتعزيز شراء الارتداد)."""
    r = _bars(sym, 5)
    if r is None or len(r) < 3:
        return {"pat": "?", "bounce_strength": 0.0}
    o, h, l, c = r["open"][-2], r["high"][-2], r["low"][-2], r["close"][-2]   # آخر شمعة مكتملة
    pat, feat = classify(o, h, l, c)
    # قوّة الارتداد الصعودي: مطرقة (ذيل سفلي طويل) أو هبوطية كبيرة بذيل سفلي = رفض القاع
    bounce = 0.0
    if pat == "hammer":
        bounce = 1.0
    elif feat.get("dir") == -1 and feat.get("lw_pct", 0) >= 0.33:
        bounce = 0.6                                   # هبوطية لكن رُفض قاعها جزئياً
    elif pat == "marubozu_dn":
        bounce = 0.2                                   # هبوط صرف بلا رفض = ارتداد أضعف
    return {"pat": pat, "feat": feat, "bounce_strength": round(bounce, 2)}


if __name__ == "__main__":
    mt5.initialize()
    for s in ("BTCUSDm", "ETHUSDm"):
        a = analyze(s, 1000)
        if not a:
            print(s, "لا بيانات"); continue
        print(f"\n=== {s} — تشريح 1000 شمعة دقيقة: التشكيل → حركة الشمعة التالية ===")
        for pat, st in a.items():
            print(f"  {pat:14} n={st['n']:5} حركة-تالية={st['next_avg']:+.4f} t={st['t']:+.2f} صعود-تالي={st['up_pct']}%")
        print("  آخر شمعة:", last_signal(s))
