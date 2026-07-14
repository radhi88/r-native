"""warroom_guards.py — حارسا مخاطر إضافيّان لغرفة الحرب (army_warroom.py، magic 20260618).

لماذا ملف منفصل؟ المنفّذ الحيّ يعمل الآن ولا يُعدّل بثقلٍ. هذا الملف **إضافي بحت**:
لا order_send، لا حالة عالمية، لا أعراض جانبية. يقرأ فقط التاريخ المغلق والمراكز المفتوحة.
army_warroom يستورده ويُدرج نداءين في maybe_execute (انظر مواصفة التعديل في رسالة التسليم).

الهدف الصريح: **تقليل النزيف المتراكم على إشارات غير مُثبتة** — لا اختراع أفضلية، لا وعد ربح.
كلا الحارسين سببيّان بحت (يقرآن الماضي/الحاضر فقط، صفر lookahead).

حارسان:
  1) daily_halt(mt5, magic, equity, pct)              — سقف خسارة يوميّ للبوت.
     True ⇐ صافي صفقات هذا الـmagic المحقّقة منذ بداية اليوم (UTC) < −pct% من الحقوق.
     مرآةٌ لنمط DAILY_KILL في multi_trader: history_deals_get(today_start, now) → جمع
     profit+commission+swap على صفقات الخروج (d.entry==1) لهذا الـmagic فقط. عند True:
     المنفّذ يوقف فتح الجديد بقيّة اليوم (المراكز المفتوحة تبقى — لا نلمسها). تاريخ مغلق فقط.

  2) correlation_block(open_positions, sym, side, ...) — سقف ترابط الباسكت.
     True ⇐ يوجد بالفعل >= max_corr مراكز مفتوحة (لنفس الـmagic) تشارك **عملةً واحدة على الأقل**
     (أساس/تسعير) مع الرمز المرشَّح **وفي اتجاهٍ متوافق مع نفس الرهان**. يمنع تكدّس الباسكت
     المترابط الذي رأيناه (AUDUSD+AUDJPY+AUDCHF longs = رهان AUD واحد بخطر 19-21%).

استخراج عملات الرمز: نفضّل حقول MT5 الصريحة (currency_base/currency_profit) عبر دالة
symbol_currencies إن مُرّر mt5؛ وإلا نسقط إلى تحليل اسمٍ بسيط (AUDJPYm → {AUD, JPY}).

"الاتجاه المتوافق مع نفس الرهان": للرمز المرشَّح، شراؤه = رهان صعودٍ على عملة الأساس + هبوطٍ
على عملة التسعير. مركزٌ مفتوح يُحتسب "نفس الرهان" إذا اشترك في عملةٍ ونفس إشارة الرهان عليها
(longs على AUD يتراكمان؛ AUDUSD long + USDJPY short كلاهما رهانٌ ضدّ USD → يتراكمان أيضاً).
هذا أدقّ من مجرّد "تشارك عملة" لأنه لا يحجب التحوّط الفعليّ (AUDUSD long + AUDJPY short).

تشغيل تحقّق:  python -c "import warroom_guards"
              python warroom_guards.py     # فحوص دخان نقيّة بلا MT5
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

# ----------------------------------------------------------------------------- ثوابت
# تطابق نمط multi_trader.DAILY_KILL_PCT في الروح؛ army_warroom يمرّر القيمة صراحةً.
DEFAULT_DAILY_HALT_PCT: float = 8.0   # صافي يوميّ أسوأ من −8% من الحقوق → أوقف الفتح بقيّة اليوم
DEFAULT_MAX_CORR: int = 2             # >= 2 مراكز مترابطة بنفس الرهان → امنع المرشَّح
EXEC_MAGIC: int = 20260618            # نفس magic المنفّذ الحيّ (للتوثيق فقط؛ يُمرَّر صراحةً)

# عملات التسعير التي قد تظهر داخل اسم الرمز (لتحليل الاسم الاحتياطيّ فقط).
_KNOWN_CCY = (
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD",
    "XAU", "XAG", "BTC", "ETH", "SOL", "BNB", "CNH", "SGD",
    "HKD", "SEK", "NOK", "ZAR", "TRY", "MXN", "PLN",
)


# ----------------------------------------------------------------------------- أدوات الرمز
def _clean_symbol(sym: str) -> str:
    """يزيل اللاحقة الوسيطة الشائعة (m) والزوائد غير الأبجدية للتحليل الاحتياطيّ.
    مثال: 'AUDJPYm' → 'AUDJPY' ، 'AUDJPY.r' → 'AUDJPY'.
    """
    if not sym:
        return ""
    s = "".join(ch for ch in str(sym) if ch.isalnum()).upper()
    if s.endswith("M") and len(s) > 1:   # لاحقة الحساب الوسيط 'm'
        s = s[:-1]
    return s


def parse_symbol_currencies(sym: str) -> set[str]:
    """تحليل اسمٍ بسيط لاستخراج العملات المشاركة (احتياطيّ بلا MT5).

    منطق: نطابق عملاتٍ معروفة كبادئة 3-أحرف ثم البقيّة. للأزواج 6-أحرف (FX) نأخذ
    أوّل 3 + ثاني 3. لرموز السلع/المؤشّرات (XAUUSD, BTCUSD) ينجح نفس المنطق (XAU+USD).
    إن لم نتعرّف → نُرجع مجموعة فارغة (الحارس يتساهل: لا حجب على المجهول).
    """
    s = _clean_symbol(sym)
    out: set[str] = set()
    # حالة الزوج النظاميّ: 6 أحرف = عملتان من 3
    if len(s) == 6:
        a, b = s[:3], s[3:]
        if a in _KNOWN_CCY:
            out.add(a)
        if b in _KNOWN_CCY:
            out.add(b)
        if out:
            return out
    # عامّ: التقط أيّ عملة معروفة كبادئة، ثم البقيّة
    rest = s
    while rest:
        hit = None
        for c in _KNOWN_CCY:
            if rest.startswith(c):
                hit = c
                break
        if hit:
            out.add(hit)
            rest = rest[len(hit):]
        else:
            rest = rest[1:]   # تخطَّ حرفاً غير معروف وتابع
    return out


def symbol_currencies(sym: str, mt5: Any = None, info: Any = None) -> set[str]:
    """العملات المشاركة في رمز. يفضّل حقول MT5 الصريحة، ويسقط إلى تحليل الاسم.

    - info: كائن symbol_info جاهز (إن مُرّر، لا نستعلم MT5 ثانيةً).
    - mt5 : وحدة MetaTrader5 (اختياريّ) لجلب info عند غيابه.
    لا يرمي أبداً: أيّ فشل → تحليل الاسم → مجموعة (قد تكون فارغة).
    """
    if info is None and mt5 is not None:
        try:
            info = mt5.symbol_info(sym)
        except Exception:
            info = None
    if info is not None:
        try:
            base = getattr(info, "currency_base", None)
            prof = getattr(info, "currency_profit", None)
            ccys = {c.upper() for c in (base, prof) if c}
            if ccys:
                return ccys
        except Exception:
            pass
    return parse_symbol_currencies(sym)


# ----------------------------------------------------------------------------- 1) سقف خسارة يوميّ
def today_start_ts(now: Optional[float] = None) -> float:
    """طابع بداية اليوم الحاليّ (UTC، 00:00) كـunix — حدّ "اليوم" للسقف (نفس multi_trader)."""
    if now is None:
        now = time.time()
    dt = datetime.fromtimestamp(now, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp()


def realized_today(mt5: Any, magic: int, *, now: Optional[float] = None) -> float:
    """صافي الربح/الخسارة المحقّق اليوم (UTC) لصفقات هذا الـmagic فقط — سببيّ بحت (مغلق).

    مرآةٌ لنمط multi_trader: history_deals_get(today_start, now) → اجمع
    profit+commission+swap على صفقات **الخروج** (d.entry == 1) لهذا الـmagic.
    (الخروج يحمل الـP&L المحقّق؛ الدخول entry==0 ربحُه صفر.) فشل/لا اتصال → 0.0
    (نتساهل: لا نوقف بسبب خطأ قراءة).
    """
    try:
        start = int(today_start_ts(now))
        end = int(now if now is not None else time.time())
        deals = mt5.history_deals_get(start, end) or []
    except Exception:
        return 0.0
    total = 0.0
    for d in deals:
        try:
            if getattr(d, "magic", None) != magic:
                continue
            if getattr(d, "entry", None) != 1:   # صفقات الخروج فقط تحمل الـP&L المحقّق
                continue
            total += float(getattr(d, "profit", 0.0) or 0.0)
            total += float(getattr(d, "commission", 0.0) or 0.0)
            total += float(getattr(d, "swap", 0.0) or 0.0)
        except Exception:
            continue
    return round(total, 2)


def daily_halt(mt5: Any, magic: int, equity: float,
               pct: float = DEFAULT_DAILY_HALT_PCT, *, now: Optional[float] = None) -> bool:
    """True ⇐ صافي اليوم المحقّق لهذا الـmagic < −pct% من الحقوق → أوقف فتح الجديد بقيّة اليوم.

    سببيّ بحت: تاريخ مغلق فقط، لا lookahead. عند True المنفّذ يمتنع عن أيّ فتحٍ جديد
    (كـDAILY_KILL في multi_trader)؛ المراكز المفتوحة لا تُمَسّ. equity<=0 أو pct<=0 → False.
    """
    if equity is None or equity <= 0 or pct is None or pct <= 0:
        return False
    realized = realized_today(mt5, magic, now=now)
    threshold = -(pct / 100.0) * float(equity)
    return realized <= threshold


# ----------------------------------------------------------------------------- 2) سقف ترابط الباسكت
def _pos_side(p: Any) -> int:
    """اتجاه مركز: شراء(+1)/بيع(−1). يقبل dict أو كائن MT5 position.

    التمييز صريح بالحقل المستخدَم:
      * حقل 'side' (اصطلاح ±1) → يُمرَّر كما هو (>0 شراء، <0 بيع).
      * حقل 'type' (اصطلاح MT5: 0=شراء، غيره=بيع) → يُحوَّل.
    كائن MT5 الحقيقيّ يحمل 'type' دائماً (0/1) فيُعالَج بفرع type.
    """
    # فرع 'side' (±1) — فقط حين يكون dict يحمل المفتاح 'side' صراحةً
    if isinstance(p, dict) and "side" in p:
        try:
            sv = int(p["side"])
        except Exception:
            return 0
        return 1 if sv > 0 else (-1 if sv < 0 else 0)
    # فرع 'type' (MT5: 0=شراء)
    if isinstance(p, dict):
        t = p.get("type")
    else:
        t = getattr(p, "type", None)
    if t is None:
        return 0
    try:
        ti = int(t)
    except Exception:
        return 0
    return 1 if ti == 0 else -1


def _pos_symbol(p: Any) -> str:
    if isinstance(p, dict):
        return str(p.get("symbol", p.get("sym", "")))
    return str(getattr(p, "symbol", ""))


def _currency_bets(sym: str, side: int, mt5: Any = None, info: Any = None) -> dict[str, int]:
    """يحوّل (رمز، اتجاه) إلى خريطة رهانٍ لكل عملة: +1 صعود / −1 هبوط.

    شراء الزوج = رهان صعودٍ على الأساس + هبوطٍ على التسعير، والعكس للبيع.
    للرمز ثنائيّ-العملة الواضح (الأساس≠التسعير) نُرتّب: العملة الأولى (الأساس) ترث side،
    والثانية (التسعير) ترث −side. عند تعذّر تمييز الأساس من التسعير (تحليل اسمٍ يُرجع مجموعة
    غير مرتّبة) نُحاول حقول MT5؛ وإلا نسند side لكلّ العملات (محافِظ: يحجب أكثر، لا يقلّ).
    """
    base = prof = None
    if info is None and mt5 is not None:
        try:
            info = mt5.symbol_info(sym)
        except Exception:
            info = None
    if info is not None:
        base = (getattr(info, "currency_base", None) or "").upper() or None
        prof = (getattr(info, "currency_profit", None) or "").upper() or None
    if not (base and prof):
        # تحليل اسمٍ: حاول استخراج الأساس(أوّل 3) والتسعير(ثاني 3) للأزواج النظاميّة
        s = _clean_symbol(sym)
        if len(s) == 6 and s[:3] in _KNOWN_CCY and s[3:] in _KNOWN_CCY:
            base, prof = s[:3], s[3:]
    out: dict[str, int] = {}
    if base and prof and base != prof:
        out[base] = side          # طويل الأساس = رهان صعودٍ عليه
        out[prof] = -side         # ... وهبوطٍ على التسعير
        return out
    # تعذّر التمييز → اسند side لكلّ العملات المعروفة (محافِظ)
    for c in symbol_currencies(sym, mt5=mt5, info=info):
        out[c] = side
    return out


def correlation_block(open_positions: Iterable[Any], sym: str, side: int,
                      *, max_corr: int = DEFAULT_MAX_CORR, magic: Optional[int] = None,
                      mt5: Any = None) -> bool:
    """True ⇐ يوجد بالفعل >= max_corr مراكز مفتوحة تشارك المرشَّح **نفس الرهان على عملة**.

    سببيّ بحت: يقرأ المراكز المفتوحة فقط (لا lookahead). يمنع تكدّس الباسكت المترابط
    (AUDUSD+AUDJPY+AUDCHF longs = رهان AUD واحد). لا يحجب التحوّط الحقيقيّ (رهان معاكس
    على نفس العملة لا يُحتسب).

    المعاملات:
      open_positions : قابل-للتكرار من مراكز MT5 (positions_get) أو dicts {symbol, type|side}.
      sym, side      : المرشَّح؛ side = +1 شراء / −1 بيع.
      max_corr       : عتبة العدد (افتراضيّاً 2 → ثالثٌ مترابط يُحجب).
      magic          : إن مُرّر، نحتسب فقط مراكز هذا الـmagic (تجاهل صفقات المستخدم/بوتات أخرى).
      mt5            : وحدة MetaTrader5 (اختياريّ) لاستخراج عملات المراكز عبر حقولها الصريحة.

    المنطق: نبني رهانات المرشَّح (عملة→±1). لكلّ مركز مفتوح نبني رهاناته؛ إن تطابق رهانٌ
    على عملةٍ واحدة على الأقل (نفس العملة ونفس الإشارة) فهو "مترابط بنفس الباسكت". إن بلغ
    عدد هذه المراكز max_corr → True (حجب).
    """
    try:
        s = int(side)
    except Exception:
        return False
    if s == 0 or max_corr is None or max_corr <= 0:
        return False
    cand = _currency_bets(sym, 1 if s > 0 else -1, mt5=mt5)
    if not cand:
        return False
    corr = 0
    for p in (open_positions or []):
        if magic is not None:
            pm = p.get("magic") if isinstance(p, dict) else getattr(p, "magic", None)
            if pm != magic:
                continue
        psym = _pos_symbol(p)
        if not psym:
            continue
        pside = _pos_side(p)
        if pside == 0:
            continue
        bets = _currency_bets(psym, pside, mt5=mt5)
        # تطابق رهانٍ على عملةٍ واحدة على الأقل (نفس العملة + نفس الإشارة) = نفس الباسكت
        if any(cand.get(c) == v for c, v in bets.items()):
            corr += 1
            if corr >= max_corr:
                return True
    return False


# ----------------------------------------------------------------------------- تحقّق سريع
if __name__ == "__main__":
    # 1) استخراج العملات (تحليل اسمٍ بلا MT5)
    assert parse_symbol_currencies("AUDJPYm") == {"AUD", "JPY"}
    assert parse_symbol_currencies("EURUSDm") == {"EUR", "USD"}
    assert parse_symbol_currencies("XAUUSDm") == {"XAU", "USD"}
    assert parse_symbol_currencies("BTCUSDm") == {"BTC", "USD"}
    assert symbol_currencies("AUDUSDm") == {"AUD", "USD"}

    # 2) رهانات العملة: شراء AUDUSD = +AUD، −USD
    cb = _currency_bets("AUDUSDm", 1)
    assert cb == {"AUD": 1, "USD": -1}, cb
    cb2 = _currency_bets("AUDJPYm", 1)
    assert cb2 == {"AUD": 1, "JPY": -1}, cb2

    # 3) سقف الترابط: تكدّس AUD longs يُحجب عند الثالث (max_corr=2)
    open_aud = [
        {"symbol": "AUDUSDm", "type": 0},   # AUD long
        {"symbol": "AUDJPYm", "type": 0},   # AUD long
    ]
    # مرشَّح AUDCHF long → عملة AUD تتطابق مع مركزين → حجب
    assert correlation_block(open_aud, "AUDCHFm", 1, max_corr=2) is True
    # مركز واحد فقط → لا حجب (دون العتبة)
    assert correlation_block([{"symbol": "AUDUSDm", "type": 0}], "AUDCHFm", 1, max_corr=2) is False
    # تحوّط حقيقيّ: AUDUSD long + AUDJPY SHORT، مرشَّح AUDCHF long
    #   AUDUSD long → +AUD ، AUDJPY short → −AUD ؛ المرشَّح +AUD يطابق الأوّل فقط (مركز واحد) → لا حجب
    hedged = [{"symbol": "AUDUSDm", "type": 0}, {"symbol": "AUDJPYm", "type": 1}]
    assert correlation_block(hedged, "AUDCHFm", 1, max_corr=2) is False
    # رهانٌ ضدّ USD يتراكم عبر أزواج مختلفة: EURUSD long(+EUR,−USD) + GBPUSD long(+GBP,−USD)،
    #   مرشَّح AUDUSD long(−USD) → عملة USD(−1) تتطابق مع كليهما → حجب
    anti_usd = [{"symbol": "EURUSDm", "type": 0}, {"symbol": "GBPUSDm", "type": 0}]
    assert correlation_block(anti_usd, "AUDUSDm", 1, max_corr=2) is True
    # اتجاه معاكس لا يتطابق: مرشَّح AUDUSD long ضدّ مركزين short على نفس الزوج → رهان USD معاكس
    shorts = [{"symbol": "EURUSDm", "type": 1}, {"symbol": "GBPUSDm", "type": 1}]
    assert correlation_block(shorts, "AUDUSDm", 1, max_corr=2) is False
    # تصفية بالـmagic: مراكز بوتٍ آخر تُتجاهَل
    foreign = [{"symbol": "AUDUSDm", "type": 0, "magic": 999},
               {"symbol": "AUDJPYm", "type": 0, "magic": 999}]
    assert correlation_block(foreign, "AUDCHFm", 1, max_corr=2, magic=20260618) is False

    # 4) سقف الخسارة اليوميّ: محاكاة mt5 وهميّ
    class _Deal:
        def __init__(self, magic, entry, profit=0.0, commission=0.0, swap=0.0):
            self.magic, self.entry = magic, entry
            self.profit, self.commission, self.swap = profit, commission, swap

    class _MT5:
        def __init__(self, deals): self._d = deals
        def history_deals_get(self, a, b): return self._d

    # خسارة −100 على الحقوق 1000 = −10% < −8% → halt True
    losers = _MT5([_Deal(20260618, 1, profit=-100.0)])
    assert daily_halt(losers, 20260618, 1000.0, pct=8.0) is True
    # خسارة −50 = −5% > −8% → False (لا halt)
    small = _MT5([_Deal(20260618, 1, profit=-50.0)])
    assert daily_halt(small, 20260618, 1000.0, pct=8.0) is False
    # صفقة بوتٍ آخر لا تُحتسب
    other = _MT5([_Deal(999, 1, profit=-500.0)])
    assert daily_halt(other, 20260618, 1000.0, pct=8.0) is False
    # صفقة دخولٍ (entry==0) لا تُحتسب حتى لو حملت ربحاً
    entry_deal = _MT5([_Deal(20260618, 0, profit=-500.0)])
    assert daily_halt(entry_deal, 20260618, 1000.0, pct=8.0) is False
    # equity<=0 → False (لا حجب بسبب بيانات سيّئة)
    assert daily_halt(losers, 20260618, 0.0, pct=8.0) is False

    print("warroom_guards: كل فحوص الدخان نجحت ✓")
