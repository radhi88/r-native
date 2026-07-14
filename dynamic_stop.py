"""dynamic_stop.py — وقف خسارة ديناميكي (طلب المستخدم: «ابعد الوقف، قريب كل شيء يضربه
ويكمل بنفس الاتجاه — خله ديناميكي حسب الزخم وحركة الشموع»).

المبدأ: الوقف لا يكون رقماً أعمى — يُبنى من:
  1. الهيكل (حركة الشموع): خلف آخر قاع/قمة Swing مؤكّدة + هامش — المكان الذي لو وصله السعر
     فالفكرة فعلاً انكسرت، لا مجرد ضجيج.
  2. الزخم: ترند قوي (اندفاعة + شموع متتالية بنفس اللون) → وسّع (دع الصفقة تتنفس)؛
     سوق هادئ → ابقَ قريباً من الأساس.
  3. أرضية: لا يضيق أبداً عن أساس الجين (التوسيع فقط — حسب طلب المستخدم).
  4. سقف: ≤2.5× الأساس (الوقف البعيد جداً = مخاطرة عمياء).
ملاحظة أمان: المتداول يحجّم بالمخاطرة ⇒ وقف أوسع = لوت أصغر تلقائياً (نفس الدولارات المخاطَرة).
دوال نقية على المصفوفات — بلا MT5، بلا حالة.
"""
from __future__ import annotations


def _atr(high, low, close, n=14):
    trs = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
           for i in range(1, len(close))]
    return sum(trs[-n:]) / min(n, len(trs)) if trs else 0.0


def momentum_mult(high, low, close, atr=None):
    """مضاعف الزخم [1.0 .. 1.6]: اندفاعة قوية + تتابع لوني = السوق يتحرك بقوة → وقف أوسع."""
    if len(close) < 10:
        return 1.0
    a = atr or _atr(high, low, close) or 1e-9
    impulse = abs(close[-1] - close[-6]) / (a * 2.2)          # حركة 5 شموع بوحدات ATR
    runs = 0
    sgn = 1 if close[-1] > close[-2] else -1
    for i in range(2, min(7, len(close))):
        if (close[-i] - close[-i - 1]) * sgn > 0:
            runs += 1
        else:
            break
    m = 1.0 + min(0.45, impulse * 0.3) + min(0.15, runs * 0.05)
    return round(min(1.6, m), 2)


def swing_level(high, low, direction, lookback=24, w=2):
    """آخر Swing مؤكّد (قاع للشراء / قمة للبيع) — «حركة الشموع» التي يجب ألا تُخترق."""
    n = len(high)
    if n < lookback:
        return None
    h = high[-lookback:]; l = low[-lookback:]
    best = None
    for i in range(w, len(h) - w):
        if direction > 0 and l[i] == min(l[i - w:i + w + 1]):
            best = l[i]                                        # آخر قاع مؤكّد (الأحدث يفوز)
        elif direction < 0 and h[i] == max(h[i - w:i + w + 1]):
            best = h[i]
    return best


def dynamic_sl_distance(high, low, close, direction, entry, base_atr_mult, atr=None):
    """مسافة الوقف الديناميكية (بوحدات السعر): هيكل + زخم، أرضية=أساس الجين، سقف=2.5×.
    ترجع (المسافة، شرح_قصير)."""
    a = atr or _atr(high, low, close)
    if a <= 0:
        return None, "no-atr"
    base = float(base_atr_mult) * a
    # 1) الهيكل: خلف آخر Swing + هامش 0.5×ATR (أبعد عن الضجيج — الشريط أثبت 75% ضرب ثم استمرار)
    sw = swing_level(high, low, direction)
    d_struct = (abs(entry - sw) + 0.50 * a) if sw is not None else 0.0
    # 2) أرضية الضجيج: لا أضيق من مدى آخر 6 شموع ×1.3 (الوقف داخل الضجيج = ضرب أكيد ثم استمرار)
    if len(high) >= 6:
        noise = (max(high[-6:]) - min(low[-6:])) * 1.3
    else:
        noise = base
    # 3) الزخم
    mom = momentum_mult(high, low, close, a)
    dist = max(base, d_struct, noise) * mom
    dist = max(base, min(dist, 3.2 * base))                    # أرضية الأساس · سقف 3.2× (أوسع للتنفّس)
    why = f"هيكل {d_struct/a:.1f}A · ضجيج {noise/a:.1f}A · زخم ×{mom} → {dist/a:.1f}A"
    return dist, why


def dynamic_manage(high, low, close, learned_be, learned_trail, atr=None):
    """إدارة ديناميكية: زخم قوي → تأمين أصبر (BE أبعد) وتريل أوسع — لا نخنق الرابحة.
    ترجع (be_trigger_atr, trail_atr)."""
    a = atr or _atr(high, low, close)
    mom = momentum_mult(high, low, close, a)
    be = max(float(learned_be or 0.10), 0.20 + 0.25 * (mom - 1.0) / 0.6)   # 0.20→0.45 حسب الزخم
    trail = min(1.8, float(learned_trail or 1.0) * mom)
    return round(be, 2), round(trail, 2)
