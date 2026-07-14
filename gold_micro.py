# -*- coding: utf-8 -*-
"""gold_micro.py — مؤشرات الذهب اللحظية (tick/M1) للعقل العميق.

قراءة-فقط، رخيصة، fail-open بالكامل (كل دالة ترجع bucket محايد عند أي خطأ — لا ترفع
استثناءً يقتل دورة deep_brain). تُحقَن خصائصها في doss["features"] للذهب فقط، فتُتعلَّم
وتُحكَم عبر آلة الظلّ (آفاق 15د/ساعة/4س) + t حقيقي + Bonferroni — بلا أي تعديل على آلة الحُكم.

صدق علمي: التنبّؤ بالاتجاه من المؤشرات = قلبة عملة بعد السبريد (مُثبت). هذه خصائص قياس
نبحث عبرها إن كان أيّ تركيب (مثل spread_b=tight × tickimb_b=buy × جلسة) يُنتج حافّة ذهبية
مُثبتة لم تظهر بعد. السبريد عنق الزجاجة على الذهب ⇒ spread_b بوّابة محورية لا زينة.

صُمّمت عبر وركفلو 5-وكلاء (order-flow / microstructure / volatility / session-levels).
"""
from __future__ import annotations
import time
import numpy as np
import MetaTrader5 as mt5

_TICK_CACHE = {"t": 0.0, "ticks": None}      # جلب تيك مشترك بين كل المؤشرات في الدورة
_SPR_EWMA = {"v": None}                       # EWMA سبريد (squeeze/expand)
_RV_HIST = []                                 # تاريخ التذبذب المحقّق للتطبيع النسبي


def _get_ticks(sym="XAUUSDm", win_s=60, max_n=3000, refresh_s=1.0):
    """جلب تيك مخبّأ مشترك — يمنع جلباً مكرراً عبر عدّة مؤشرات في نفس الدورة."""
    now = time.time()
    if _TICK_CACHE["ticks"] is not None and now - _TICK_CACHE["t"] < refresh_s:
        return _TICK_CACHE["ticks"]
    try:
        ts = mt5.copy_ticks_from(sym, now - win_s, max_n, mt5.COPY_TICKS_ALL)
    except Exception:
        ts = None
    _TICK_CACHE.update(t=now, ticks=ts)
    return ts


def spread_regime(sym="XAUUSDm", alpha=0.02):
    """نظام السبريد اللحظي: wide=الكلفة تأكل الحافّة (بوّابة منع) · tight=نافذة رخيصة."""
    try:
        info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
        if not info or not tk:
            return "mid"
        pt = info.point or 0.01
        spr = (tk.ask - tk.bid) / pt
        e = _SPR_EWMA["v"]
        _SPR_EWMA["v"] = spr if e is None else alpha * spr + (1 - alpha) * e
        ratio = spr / max(_SPR_EWMA["v"], 1e-9)
        return "wide" if ratio >= 1.5 else "tight" if ratio <= 0.7 else "mid"
    except Exception:
        return "mid"


def tick_imbalance(sym="XAUUSDm"):
    """عدم توازن العدوانية من علم التيك (TICK_FLAG_ASK/BID موثوقة على Exness)."""
    ts = _get_ticks(sym, win_s=10, max_n=2000)
    try:
        if ts is None or len(ts) < 8:
            return "flat"
        fl = ts["flags"]
        ask_up = int(np.count_nonzero(fl & mt5.TICK_FLAG_ASK))
        bid_up = int(np.count_nonzero(fl & mt5.TICK_FLAG_BID))
        tot = ask_up + bid_up
        if tot == 0:
            return "flat"
        tib = (ask_up - bid_up) / tot
        return "buy" if tib >= 0.33 else "sell" if tib <= -0.33 else "flat"
    except Exception:
        return "flat"


def realized_vol(sym="XAUUSDm"):
    """التذبذب المحقّق اللحظي من التيكات، مُطبَّع نسبياً على تاريخه القريب."""
    ts = _get_ticks(sym, win_s=60, max_n=3000)
    try:
        if ts is None or len(ts) < 20:
            return "mid"
        mid = (ts["bid"].astype(float) + ts["ask"].astype(float)) / 2.0
        mid = mid[mid > 0]
        if len(mid) < 20:
            return "mid"
        ret = np.diff(np.log(mid))
        rv = float(np.sqrt(np.sum(ret * ret)))
        _RV_HIST.append(rv)
        if len(_RV_HIST) > 60:
            _RV_HIST.pop(0)
        if len(_RV_HIST) < 10:
            return "mid"
        p33, p66 = np.percentile(_RV_HIST, [33, 66])
        return "hi" if rv >= p66 else "lo" if rv <= p33 else "mid"
    except Exception:
        return "mid"


def vwap_dev(sym="XAUUSDm", n=240):
    """انحراف السعر عن VWAP (M1) بوحدات الانحراف المعياري — مرساة قيمة عادلة."""
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
        tk = mt5.symbol_info_tick(sym)
        if r is None or len(r) < 30 or not tk:
            return "near"
        tp = (r["high"] + r["low"] + r["close"]) / 3.0
        w = r["tick_volume"].astype(float)
        sw = max(w.sum(), 1e-9)
        vwap = float((tp * w).sum() / sw)
        sd = float(np.sqrt(((tp - vwap) ** 2 * w).sum() / sw))
        mid = (tk.bid + tk.ask) / 2.0
        z = (mid - vwap) / max(sd, 1e-9)
        return "far_above" if z >= 1.5 else "far_below" if z <= -1.5 else "near"
    except Exception:
        return "near"


def round_prox(sym="XAUUSDm"):
    """قرب رقم مستدير ($5/$10) بوحدات السبريد — الذهب يحبّ الأرقام المستديرة."""
    try:
        info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
        if not info or not tk:
            return "away"
        mid = (tk.bid + tk.ask) / 2.0
        spr = max(tk.ask - tk.bid, info.point or 0.01)
        cand = [round(mid / 5.0) * 5.0, round(mid / 10.0) * 10.0]
        d = min(abs(mid - x) for x in cand)
        dist_spr = d / spr
        return "at_round" if dist_spr <= 1.0 else "approach" if dist_spr <= 3.0 else "away"
    except Exception:
        return "away"


def micro_struct(sym="XAUUSDm"):
    """كسر بنية مجهري (BOS) أو سحب سيولة (sweep) لحظي عبر فراكتالات M1."""
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 120)
        tk = mt5.symbol_info_tick(sym)
        if r is None or len(r) < 30 or not tk:
            return "inside"
        h, l = r["high"], r["low"]
        sw_hi = [h[i] for i in range(2, len(h) - 2) if h[i] == max(h[i - 2:i + 3])]
        sw_lo = [l[i] for i in range(2, len(l) - 2) if l[i] == min(l[i - 2:i + 3])]
        last_hi = sw_hi[-1] if sw_hi else float(h.max())
        last_lo = sw_lo[-1] if sw_lo else float(l.min())
        atr1 = float(np.mean(h[-14:] - l[-14:])) or 1e-9
        mid = (tk.bid + tk.ask) / 2.0
        if mid > last_hi:
            return "bos_up" if (mid - last_hi) >= 0.2 * atr1 else "sweep_up"
        if mid < last_lo:
            return "bos_dn" if (last_lo - mid) >= 0.2 * atr1 else "sweep_dn"
        return "inside"
    except Exception:
        return "inside"


def session_range_pos(sym="XAUUSDm"):
    """موقع السعر داخل مدى الجلسة الحيّ (hi/mid/lo)."""
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 480)
        tk = mt5.symbol_info_tick(sym)
        if r is None or len(r) < 30 or not tk:
            return "mid"
        gm = time.gmtime(); hr = gm.tm_hour
        start = 0 if hr < 7 else 7 if hr < 12 else 12 if hr < 21 else 21
        n = min(max((hr - start) * 60 + gm.tm_min, 1), len(r))
        sh = float(r["high"][-n:].max()); sl = float(r["low"][-n:].min())
        mid = (tk.bid + tk.ask) / 2.0
        if sh <= sl:
            return "mid"
        pos = (mid - sl) / (sh - sl)
        return "hi" if pos >= 0.8 else "lo" if pos <= 0.2 else "mid"
    except Exception:
        return "mid"


def gold_micro_features(sym="XAUUSDm"):
    """7 خصائص bucket جاهزة للدمج في doss['features']. fail-open بالكامل."""
    _get_ticks(sym, win_s=60, max_n=3000)        # جلب مشترك واحد لكل المؤشرات
    return {
        "spread_b": spread_regime(sym),
        "tickimb_b": tick_imbalance(sym),
        "rvol_b": realized_vol(sym),
        "vwapdev_b": vwap_dev(sym),
        "round_b": round_prox(sym),
        "struct_b": micro_struct(sym),
        "orpos_b": session_range_pos(sym),
    }


def gold_micro_signal(feats):
    """وصف حالة لحظي معروض (ليس توصية) من الخصائص."""
    p = []
    sb = feats.get("spread_b")
    if sb == "wide":
        p.append("⚠️ سبريد متوسّع: الكلفة تأكل الحافّة")
    elif sb == "tight":
        p.append("سبريد ضيّق: نافذة رخيصة")
    ti = feats.get("tickimb_b")
    if ti == "buy":
        p.append("ضغط شراء عدواني")
    elif ti == "sell":
        p.append("ضغط بيع عدواني")
    if feats.get("round_b") == "at_round":
        p.append("ملامس رقم مستدير")
    st = feats.get("struct_b", "")
    if st.startswith("bos"):
        p.append("كسر بنية مجهري")
    elif st.startswith("sweep"):
        p.append("سحب سيولة (فشل اختراق)")
    if feats.get("rvol_b") == "hi":
        p.append("تذبذب لحظي مرتفع")
    return " · ".join(p) or "هادئ"


if __name__ == "__main__":
    mt5.initialize()
    f = gold_micro_features("XAUUSDm")
    print("gold features:", f)
    print("signal:", gold_micro_signal(f))
