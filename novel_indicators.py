# -*- coding: utf-8 -*-
"""novel_indicators.py — مؤشرات مُبتكَرة (ليست TA كلاسيكية) تقيس **بنية السوق وقابلية التنبّؤ**.

الفكرة: أثبتنا أن مؤشرات الاتجاه الـ30 قلبة عملة. هذه لا تتنبّأ بالاتجاه — بل تقيس **متى**
يكون السوق مُنتظَماً/متّجهاً (يُوثَق بالإشارة) مقابل عشوائياً (تُتجاهَل). تُحقَن كخصائص bucket
في العقل العميق فتُتعلَّم وتُحكَم (Bonferroni) عبر كل الرموز — رشّ مُقاس بلا تنفيذ حقيقي.

الخمسة المُبتكَرة:
  • hurst_b   — أُسّ هرست (متّجه/عشوائي/عائد-للمتوسط) عبر نسبة التباين
  • entropy_b — إنتروبيا إشارات العوائد (انتظام مقابل عشوائية)
  • volvol_b  — تذبذب-التذبذب (انتقال نظام: توسّع/استقرار/انضغاط)
  • acorr_b   — ارتباط ذاتي تأخّر-1 (زخم/لا شيء/عائد)
  • squeeze_b — انضغاط المدى (ضغط/طبيعي/توسّع)

نقي، رخيص، fail-open بالكامل.
"""
from __future__ import annotations
import math
import numpy as np
import MetaTrader5 as mt5


def _closes(sym, n=240):
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, n)
        if r is None or len(r) < 80:
            return None
        return np.asarray(r["close"], dtype=float)
    except Exception:
        return None


def _hurst(c):
    """أُسّ هرست عبر نسبة-التباين: >0.55 متّجه · ~0.5 عشوائي · <0.45 عائد-للمتوسط."""
    try:
        lr = np.diff(np.log(c[c > 0]))
        if len(lr) < 60:
            return None
        var1 = np.var(lr)
        if var1 <= 0:
            return None
        # تباين العوائد المُجمّعة على آفاق q ∝ q^(2H)
        qs = [2, 4, 8, 16]
        logq, logv = [], []
        for q in qs:
            m = len(lr) // q
            if m < 4:
                continue
            agg = lr[:m * q].reshape(m, q).sum(axis=1)
            logq.append(math.log(q)); logv.append(math.log(max(np.var(agg), 1e-12)))
        if len(logq) < 3:
            return None
        slope = np.polyfit(logq, logv, 1)[0]      # = 2H
        return float(slope / 2.0)
    except Exception:
        return None


def _entropy(c):
    """إنتروبيا شانون لإشارات العوائد على أنماط 2-بت (انتظام مقابل عشوائية، مُطبَّعة 0..1)."""
    try:
        s = np.sign(np.diff(c))
        s = s[s != 0]
        if len(s) < 40:
            return None
        b = (s > 0).astype(int)
        pats = [b[i] * 2 + b[i + 1] for i in range(len(b) - 1)]
        cnt = np.bincount(pats, minlength=4).astype(float)
        p = cnt / cnt.sum()
        h = -sum(x * math.log2(x) for x in p if x > 0)
        return float(h / 2.0)                       # 0=منتظم تماماً .. 1=عشوائي تماماً
    except Exception:
        return None


def _volvol(c):
    """تذبذب-التذبذب: انحراف تغيّرات المدى المتحرّك مُطبّعاً (انتقال النظام)."""
    try:
        lr = np.abs(np.diff(np.log(c[c > 0])))
        if len(lr) < 60:
            return None
        win = 10
        vol = np.array([lr[i - win:i].mean() for i in range(win, len(lr))])
        if len(vol) < 20 or vol.mean() <= 0:
            return None
        return float(np.std(np.diff(vol)) / vol.mean())
    except Exception:
        return None


def _acorr(c):
    """ارتباط ذاتي تأخّر-1 للعوائد: + زخم · ~0 لا شيء · − عائد-للمتوسط."""
    try:
        r = np.diff(np.log(c[c > 0]))
        if len(r) < 60:
            return None
        r = r[-120:]
        a, b = r[:-1], r[1:]
        if a.std() <= 0 or b.std() <= 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])
    except Exception:
        return None


def _squeeze(c):
    """انضغاط المدى: مدى آخر 20 مقابل آخر 100 (نسبة <0.5 ضغط · >1 توسّع)."""
    try:
        if len(c) < 100:
            return None
        rng_s = c[-20:].max() - c[-20:].min()
        rng_l = c[-100:].max() - c[-100:].min()
        if rng_l <= 0:
            return None
        return float((rng_s / rng_l) * 5.0)         # ×5 لأن 20/100؛ ~1 طبيعي
    except Exception:
        return None


def novel_features(sym):
    """5 خصائص bucket مُبتكَرة جاهزة للدمج في doss['features']. fail-open."""
    c = _closes(sym)
    if c is None:
        return {}
    out = {}
    h = _hurst(c)
    if h is not None:
        out["hurst_b"] = "trend" if h >= 0.55 else "revert" if h <= 0.45 else "random"
    e = _entropy(c)
    if e is not None:
        out["entropy_b"] = "ordered" if e <= 0.9 else "random" if e >= 0.99 else "mid"
    vv = _volvol(c)
    if vv is not None:
        out["volvol_b"] = "expand" if vv >= 0.6 else "calm" if vv <= 0.3 else "mid"
    ac = _acorr(c)
    if ac is not None:
        out["acorr_b"] = "momentum" if ac >= 0.1 else "meanrev" if ac <= -0.1 else "none"
    sq = _squeeze(c)
    if sq is not None:
        out["squeeze_b"] = "squeeze" if sq <= 0.6 else "expand" if sq >= 1.4 else "normal"
    return out


def novel_signal(feats):
    """وصف بنية السوق (متى نوثق الإشارة) — للعرض."""
    p = []
    if feats.get("hurst_b") == "trend":
        p.append("سوق متّجه (وثّق الاتجاه)")
    elif feats.get("hurst_b") == "revert":
        p.append("عائد للمتوسط (الاختراق يفشل)")
    if feats.get("entropy_b") == "ordered":
        p.append("نمط منتظم")
    elif feats.get("entropy_b") == "random":
        p.append("عشوائي (تجاهل الإشارة)")
    if feats.get("squeeze_b") == "squeeze":
        p.append("انضغاط (انفجار وشيك)")
    if feats.get("volvol_b") == "expand":
        p.append("نظام يتوسّع")
    return " · ".join(p) or "بنية محايدة"


if __name__ == "__main__":
    mt5.initialize()
    for s in ("XAUUSDm", "BTCUSDm", "EURUSDm"):
        f = novel_features(s)
        print(s, "->", f, "|", novel_signal(f))
