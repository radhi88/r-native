# -*- coding: utf-8 -*-
"""lot_guard.py — السقف الصلب للوت (الرافعة الوحيدة المُثبتة خارج العيّنة).

صيّاد الحافّة (walk-forward + صافي-التكلفة + Bonferroni + ناقد عدائيّ) أثبت: **لا حافّة تنبّؤيّة**، لكن
الرافعة الحقيقيّة الوحيدة هي **الحجم**. بالأرقام على friday.db: اللوت الكبير (≥0.2) هو قاتل الحساب —
اليدويّ ذهب كبير −$45,619 مقابل صغير +$30,535؛ والبوت كبير exp −$1.50 مقابل صغير −$0.41/صفقة.

هذا الحارس **قراءة-فقط ونقيّ**: يقصّ اللوت المطلوب كي لا تتجاوز **مخاطرة/هامش** المركز نسبةً من الحقوق
(نسبيّ-للحقوق ⇒ يتقلّص تلقائياً على الحساب الصغير). لا يزيد اللوت أبداً، fail-open (يرجع المطلوب إن تعذّر
الحساب). يُستدعى قبل order_send في كل منفّذ: `lot, capped = lot_guard.cap(mt5, sym, lot, equity)`.
"""
from __future__ import annotations

MAX_RISK_PCT   = 2.0      # مخاطرة المركز على حركة 1% ≤ هذا% من الحقوق (حدّ 2% المُثبت في المشروع)
MAX_MARGIN_PCT = 15.0     # هامش المركز الواحد ≤ هذا% من الحقوق (يمنع رشّ الهامش الكارثيّ)
MOVE_FRAC      = 0.01     # «حركة نمطيّة» لتقدير مخاطرة الذيل = 1% من السعر


def cap(mt5, symbol, desired_lot, equity, max_risk_pct=MAX_RISK_PCT, max_margin_pct=MAX_MARGIN_PCT):
    """يرجع (capped_lot, was_capped). يقصّ desired_lot نسبيّاً للحقوق (مخاطرة + هامش). لا يزيد أبداً."""
    try:
        if desired_lot is None or desired_lot <= 0 or not equity or equity <= 0:
            return desired_lot, False
        info = mt5.symbol_info(symbol)
        if not info:
            return desired_lot, False
        vmin = info.volume_min or 0.01
        vstep = info.volume_step or 0.01
        caps = [float(desired_lot)]

        # (1) سقف المخاطرة: خسارة المركز على حركة MOVE_FRAC عكسيّة ≤ max_risk_pct% من الحقوق
        price = float(getattr(info, "ask", 0.0) or getattr(info, "bid", 0.0) or 0.0)
        tick_sz = float(info.trade_tick_size or info.point or 0.0)
        tick_val = float(info.trade_tick_value or 0.0)
        if price > 0 and tick_sz > 0 and tick_val > 0:
            risk_per_lot = (price * MOVE_FRAC / tick_sz) * tick_val
            if risk_per_lot > 0:
                caps.append((equity * max_risk_pct / 100.0) / risk_per_lot)

        # (2) سقف الهامش: هامش 1 لوت ≤ max_margin_pct% من الحقوق
        try:
            m1 = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, 1.0, price or 1.0)
        except Exception:
            m1 = None
        if m1 and m1 > 0:
            caps.append((equity * max_margin_pct / 100.0) / m1)

        capped = min(caps)
        capped = round(capped / vstep) * vstep              # محاذاة للخطوة
        capped = max(vmin, min(capped, float(desired_lot)))  # لا تحت الأدنى، ولا فوق المطلوب
        # تقريب الفاصلة لعدد منازل الخطوة (تفادي 0.30000000004)
        capped = round(capped, 8)
        return float(capped), (capped < float(desired_lot) - 1e-9)
    except Exception:
        return desired_lot, False


if __name__ == "__main__":
    import MetaTrader5 as mt5
    mt5.initialize()
    a = mt5.account_info()
    eq = a.equity if a else 100.0
    print(f"equity ${eq:.2f} — اختبار السقف على لوت مطلوب كبير:")
    for sym in ("XAUUSDm", "BTCUSDm", "EURUSDm"):
        for want in (0.5, 0.2, 0.05, 0.01):
            capped, was = cap(mt5, sym, want, eq)
            flag = "🛑 قُصّ" if was else "✅"
            print(f"  {sym:9} طلب {want:>4} → {capped:>5} {flag}")
    mt5.shutdown()
