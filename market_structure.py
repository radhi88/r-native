# -*- coding: utf-8 -*-
"""market_structure.py — بنية السوق HH/HL/LH/LL + كسر البنية (BOS) + تغيّر الطابع (ChoCH).

يكشف القمم/القيعان المتأرجحة (fractals) ويصنّف:
  • HH (قمة أعلى) + HL (قاع أعلى) = **اتجاه صاعد**.
  • LH (قمة أدنى) + LL (قاع أدنى) = **اتجاه هابط**.
  • انقلاب النمط = كسر بنية (BOS) / تغيّر طابع (ChoCH) = الترند يتغيّر (عند مستوياتك).

يُستهلَك في السكالب لتحديد «الترند الذي نحن واثقون منه»: نبيع مع الهبوط (LH/LL)،
نشتري/نرتدّ مع الصعود (HH/HL)، وننتبه لـ BOS (تغيّر الاتجاه عند المستوى).
صدق: SMC/البنية اختُبرت في المشروع ≈50% (سياق لا عرّافة) — لكنها تعطي البوت ترندك.
"""
from __future__ import annotations
import numpy as np
import MetaTrader5 as mt5

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15}


def _swings(sym, tf=mt5.TIMEFRAME_M5, n=300, k=2):
    """قمم/قيعان متأرجحة (فراكتال ±k). يرجع (قمم, قيعان) كقوائم (فهرس, سعر) بالترتيب الزمني."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 5 * k:
        return [], []
    h, l = r["high"], r["low"]
    highs, lows = [], []
    for i in range(k, len(r) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            highs.append((i, float(h[i])))
        if l[i] == min(l[i - k:i + k + 1]):
            lows.append((i, float(l[i])))
    return highs, lows


def structure(sym, tf="M5"):
    """بنية السوق الحاليّة: الاتجاه + آخر تصنيف (HH/HL/LH/LL) + كسر البنية."""
    highs, lows = _swings(sym, _TF.get(tf, mt5.TIMEFRAME_M5))
    sh = [p for _, p in highs[-2:]]
    sl = [p for _, p in lows[-2:]]
    hh = len(sh) == 2 and sh[-1] > sh[-2]
    lh = len(sh) == 2 and sh[-1] < sh[-2]
    hl = len(sl) == 2 and sl[-1] > sl[-2]
    ll = len(sl) == 2 and sl[-1] < sl[-2]
    if hh and hl:
        trend, label = "up", "HH + HL"
    elif lh and ll:
        trend, label = "down", "LH + LL"
    elif hh and ll:
        trend, label = "expand", "HH + LL (توسّع)"
    elif lh and hl:
        trend, label = "contract", "LH + HL (انكماش)"
    else:
        trend, label = "range", "غير محسوم"
    # كسر البنية: السعر الحاليّ تجاوز آخر قمة (BOS صعودي) أو آخر قاع (BOS هبوطي)
    tk = mt5.symbol_info_tick(sym)
    bos = None
    if tk and sh and sl:
        last_high = highs[-1][1]; last_low = lows[-1][1]
        mid = (tk.bid + tk.ask) / 2.0
        if mid > last_high:
            bos = "BOS↑ (كسر القمة)"
        elif mid < last_low:
            bos = "BOS↓ (كسر القاع)"
    return {"trend": trend, "label": label, "hh": hh, "hl": hl, "lh": lh, "ll": ll,
            "bos": bos, "last_high": round(sh[-1], 2) if sh else None,
            "last_low": round(sl[-1], 2) if sl else None}


if __name__ == "__main__":
    mt5.initialize()
    for s in ("BTCUSDm", "ETHUSDm"):
        for tf in ("M1", "M5", "M15"):
            st = structure(s, tf)
            print(f"{s} {tf}: {st['trend']:8} [{st['label']}] قمة {st['last_high']} قاع {st['last_low']} {st['bos'] or ''}")
