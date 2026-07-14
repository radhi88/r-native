"""broker_calc.py — استغلال أرقام MT5 الدقيقة: حارس الهامش + فلتر السوب (كلفة الاحتفاظ).

من تفكيك الـAPI:
  • order_calc_margin → هامش الصفقة الدقيق قبل إرسالها (حارس: لا تفتح ما يخنق الحساب).
  • order_calc_profit → ربح/خسارة دقيق لأي حركة سعر (تحجيم/أهداف بالدولار لا التقدير).
  • swap_long/short → كلفة الاحتفاظ ليلاً (الذهب long ≈ -516/لوت سنوياً — يأكل ربح السوينق!).
دوال نقية تأخذ mt5 — تُستهلك من multi_trader وغيره. صفر تكلفة.
"""
from __future__ import annotations


def margin_ok(mt5, sym, lot, price, side="buy", max_frac=0.30):
    """True لو الصفقة لا تتجاوز هامشها max_frac من الهامش الحرّ (حارس دقيق قبل order_send)."""
    try:
        ot = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        need = mt5.order_calc_margin(ot, sym, float(lot), float(price))
        acc = mt5.account_info()
        free = getattr(acc, "margin_free", 0.0) if acc else 0.0
        if need is None or free <= 0:
            return True                       # فشل الحساب → لا تمنع (fail-safe)
        return need <= free * max_frac
    except Exception:
        return True


def swap_penalty(mt5, sym, direction, tf="M15"):
    """فلتر السوب: لو اتجاه الصفقة له سوب سالب كبير وكنّا على فريم سوينق (نحتفظ ليلاً)، أعِد
    عقوبة ثقة (0..0.15) لتثبيط الكاري المكلف. السكالب (M1/M5) لا يُحتفظ ليلاً → بلا عقوبة."""
    try:
        if tf in ("M1", "M5"):
            return 0.0
        i = mt5.symbol_info(sym)
        if not i:
            return 0.0
        sw = i.swap_long if direction > 0 else i.swap_short
        cs = getattr(i, "trade_contract_size", 1) or 1
        # سوب نقاط؛ طبّعه بقيمة العقد لمقارنة عبر الرموز. كبير سالب ⇒ عقوبة أعلى
        norm = sw / max(1.0, cs)
        if norm >= -0.5:
            return 0.0
        return min(0.15, abs(norm) * 0.02)     # -5/عقد ≈ 0.10 عقوبة
    except Exception:
        return 0.0


def dollar_target(mt5, sym, lot, entry, target_price, side="buy"):
    """ربح/خسارة بالدولار الدقيق لحركة سعرية (order_calc_profit) — لأهداف/تحجيم بالدولار."""
    try:
        ot = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        return mt5.order_calc_profit(ot, sym, float(lot), float(entry), float(target_price))
    except Exception:
        return None
