# -*- coding: utf-8 -*-
"""delta_flow.py — دلتا تدفّق الأوامر الدقيقة اللحظية (للدخول **مع الزخم**).

تُحسب طازجةً عند كل نداء (لا ملفّ، لا تأخير) على التيكات الحقيقية لآخر ثوانٍ:
  • قاعدة-التيك: ارتفاع السعر = شراء عدوانيّ (+حجم)، هبوط = بيع عدوانيّ (−حجم)، مع تمرير-أمامي
    لإشارة الصفر (دقّة أعلى من إهمالها).
  • delta = صافي (شراء − بيع) موزوناً بحجم التيك في النافذة.
  • bias = −100..+100 (كم الضغط أحاديّ الجانب)، cvd = الدلتا التراكمية، rising = هل CVD يصعد
    في النصف الأخير (زخم التدفّق يتسارع).

صدق علميّ (مقاس على 1.7M تيك سابقاً): الدلتا وحدها ~47-52% اتجاهياً = ليست عرّافاً. دورها هنا
**مُؤكِّد توقيت**: لا ندخل ضدّ الشريط (نشتري والمشترون يقودون، نبيع والبائعون يقودون) — أسلوبك:
«ندخل مع الزخم». fail-open: عند غياب التيكات لا نمنع (لا نُعطّل السكالب).
"""
from __future__ import annotations
import time
import numpy as np
import MetaTrader5 as mt5

_CACHE = {}                         # {sym: (t, result)} — تهدئة 0.4s كي لا نُثقل التيكات


def flow(sym, win_s=90, min_ticks=20):
    """تدفّق الأوامر الطازج للرمز عبر آخر win_s ثانية. None إن لا تيكات كافية."""
    now = time.time()
    c = _CACHE.get(sym)
    if c and now - c[0] < 0.4:                       # تهدئة دقيقة (نفس التيكات خلال <0.4s)
        return c[1]
    ticks = mt5.copy_ticks_range(sym, now - win_s, now, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) < min_ticks:
        _CACHE[sym] = (now, None)
        return None
    last = ticks["last"].astype(float)
    mid = (ticks["bid"].astype(float) + ticks["ask"].astype(float)) / 2.0
    px = np.where(last > 0, last, mid)               # CFD غالباً last=0 ⇒ نستعمل المنتصف
    vol = ticks["volume"].astype(float)
    vol = np.where(vol > 0, vol, 1.0)                # تيك بلا حجم = وزن 1 (وجود الصفقة)
    dp = np.diff(px)
    sign = np.sign(dp)
    # تمرير-أمامي لإشارة الصفر (قاعدة-التيك القياسية: التيك المسطّح يرث آخر اتجاه)
    nz = sign != 0
    if nz.any():
        idx = np.where(nz, np.arange(len(sign)), 0)
        np.maximum.accumulate(idx, out=idx)
        sign = sign[idx]
    w = vol[1:]
    signed = sign * w
    delta = float(signed.sum())
    total = float(w.sum())
    cvd = np.cumsum(signed)
    half = len(cvd) // 2
    rising = bool(cvd[-1] > cvd[half]) if half > 0 else False
    falling = bool(cvd[-1] < cvd[half]) if half > 0 else False
    res = {"delta": round(delta, 1), "bias": round(100.0 * delta / total, 1) if total else 0.0,
           "cvd": round(float(cvd[-1]), 1), "rising": rising, "falling": falling,
           "pressure": round(abs(delta) / total, 3) if total else 0.0, "ticks": int(len(ticks))}
    _CACHE[sym] = (now, res)
    return res


def confirms(sym, d, win_s=90, min_bias=8.0):
    """هل تدفّق الأوامر يؤكّد الاتجاه d؟ (ندخل مع الزخم). fail-open إن لا بيانات."""
    f = flow(sym, win_s)
    if not f:
        return True
    if d > 0:
        return f["bias"] >= min_bias                 # مشترون عدوانيّون يقودون
    if d < 0:
        return f["bias"] <= -min_bias                # بائعون عدوانيّون يقودون
    return True


def exhausting(sym, side, win_s=90):
    """هل الضغط المعاكس **ينضب** (لشراء الارتداد)؟ side=+1 يعني نبحث عن نضوب البائعين.

    دقّة الارتداد: لا نشتري القاع وهو ينهار، بل حين يبدأ تدفّق البيع بالانعكاس (CVD يصعد)."""
    f = flow(sym, win_s)
    if not f:
        return True
    if side > 0:
        return f["rising"] or f["bias"] >= -25.0     # بائعون ينضبون / CVD ينعكس صعوداً
    return f["falling"] or f["bias"] <= 25.0


if __name__ == "__main__":
    mt5.initialize()
    for s in ("BTCUSDm", "ETHUSDm", "XAUUSDm"):
        f = flow(s)
        if f:
            print(f"{s}: bias={f['bias']:+6.1f} delta={f['delta']:+10.1f} cvd={f['cvd']:+10.1f} "
                  f"{'صاعد' if f['rising'] else 'هابط' if f['falling'] else 'مسطّح'} "
                  f"ضغط={f['pressure']:.2f} تيكات={f['ticks']}")
        else:
            print(f"{s}: لا تيكات كافية")
