# -*- coding: utf-8 -*-
"""profit_harvester.py — الدماغ الإداريّ الذاتيّ: يجني أرباح الصفقات التي يتركها البوت مفتوحة،
تلقائياً 24/7، تماماً كما يفعل المستخدم بيده — كي لا يجالسها.

السياق (تدقيق متعدّد-الوكلاء): أغلب المحرّكات تدير رابحيها بنفسها (gold_scalper/multi_trader/
news_gene). لكنّ **غرفة الحرب (20260618) و orb (20260616) يضعان وقفاً+هدفاً عند الدخول ثمّ يتركان** —
فالربح العائم يبقى مفتوحاً حتى ينعكس أو يلامس الهدف الثابت. هذه بالضبط الفجوة التي يسدّها المستخدم يدوياً.

ماذا يفعل (إدارة لا تنبّؤ):
  • يراقب مراكز magic المستهدفة فقط، ويتعقّب **قمّة الربح الصافي** لكلّ تذكرة.
  • يقفل الرابح **فقط حين يتراجع عن قمّته** (giveback) — فالرابح القويّ يجري، والضعيف يُبنَك قبل أن يعود.
  • **لا يُغلق على خسارة أبداً** (صافي≤0 ⇒ يُترَك — قاعدة المستخدم). **لا وقف فرديّ أعمى.**

حُرّاس صارمة (ديمو-فقط):
  • يتصرّف على مجيكاتنا فقط {20260618, 20260616}. يتجاهل الخبراء الخارجيّين واليدويّ (0) صراحةً.
  • **يتخطّى المحرّكات التي تدير نفسها** (gold_scalper/multi_trader/news_gene/tournament) = لا سباق إغلاق مزدوج.
  • إغلاق-فقط (لا يفتح صفقات أبداً). يحترم kill_switch. اتّصال MT5 واحد. لا يلمس master_floor.

Run: pythonw profit_harvester.py   (windowless تحت الوصيّ)
"""
from __future__ import annotations
from engine_lock import claim
import json, time
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
KILL = ROOT / "kill_switch.txt"
KILL_D = ROOT / "data" / "r_native" / "kill_switch.txt"   # درس 2026-07-02: نحترم القفلَين معاً
STATUS = RN / "profit_harvester_status.json"
LOG = RN / "profit_harvester.log"

# 🌍 2026-07-02 بأمر المستخدم «فعّل تأمين الأرباح لكل العملات»: قائمة سوداء بدل بيضاء —
# نحصد كلّ مجيك لنا على كلّ رمز، ونستثني فقط من يدير رابحه بنفسه (سباق إغلاق مزدوج) والمحميّين.
# ⚔️ خطة الحسم 2026-07-02: أُطفئت محرّكات الدخول الخاسرة (youtube/multi/warroom/genes/news_gene)
# ⇒ الحاصد يتبنّى مراكزها اليتيمة. يتخطّى فقط الأحياء المُدارين ذاتياً:
SELF_MANAGED  = {20260628,                                  # manual_manager (يدير يدويّ المستخدم)
                 20260703,                                  # radhi_mimic (بنك-الموجة ذاتيّ) — المحرّك الوحيد
                 111111,                                    # 🛡️ 2026-07-15: مُثبِت NR7 — SL=1×ATR/TP=3R على الأمر.
                                                            # الحاصد كان يقدر يبنكه عند giveback فيكسر عدم-التماثل = جوهر الحافة.
                 20260716,                                  # 🛡️ Fabio ORB — هدف 1R محدّد على الأمر، يدير خروجه بنفسه
                 3627}                                      # SAR دائم-الاتجاه — إغلاقه يكسر منطقه
EXTERNAL      = {2447, 20250418, 20250421, 20250422, 20250618}  # خبراء المستخدم — لا تُلمَس
MANUAL        = 0                              # يدويّ — يملكه manual_manager، لا نلمسه
_SKIP         = SELF_MANAGED | EXTERNAL | {MANUAL}

POLL_S      = 0.3       # 2026-07-08: 0.5→0.3ث — بنك الرابح أسرع (السرعة تنفع الخروج)
# ⚖️ 2026-07-07 جراحة عدم-التماثل (تشخيص المستخدم «الخسائر أكبر من الأرباح وعدد الرابحات أكثر»):
# ARM_USD=0.30 الثابت كان يبتر كل رابح عند +$0.10-0.20 بينما الستوبات −$1.5-2.6 (عائد عكسيّ 17:1
# = توقّع الحارس هبط لـ−$0.03/صفقة رغم فوز 77%). الحلّ: التسليح يقيس بمخاطرة المركز نفسه (R):
# لا تتبّع قبل ربح ≥ ARM_R×R — فالرابح يتنفّس حتى يبلغ ربحاً ذا معنى نسبةً لوقفه، ثم يُحمى.
# (مطابقةً لعقيدة «دع الرابح يجري» ولقفل يدويّ المستخدم المتحرّك الذي يصنع +$0.95/صفقة.)
MIN_NET     = 0.12      # لا نجني تحت هذا (نترك الأخضر الصغير جداً يكبر؛ ولا نُغلق على خسارة قطعاً)
ARM_R       = 0.8       # نُسلّح حين الربح ≥ 0.8×مخاطرة المركز (R من وقفه الفعليّ عبر order_calc_profit)
ARM_USD     = 1.00      # أرضيّة التسليح للمراكز بلا وقف/مخاطرة معلومة (كان 0.30 — سبب البتر)
GIVEBACK    = 0.50      # نجني إن تراجع الربح إلى 50% من قمّته (نلتقط ~نصف القمّة، نترك القويّ يجري)
BIG_R       = 2.0       # رابح كبير = ≥2R (أو BIG_USD للمجهول): نشدّ الحماية كي لا يضيع مكسب كبير
BIG_USD     = 3.0
BIG_GIVEBACK = 0.70

_peak = {}             # {ticket: قمّة الربح الصافي}
_risk = {}             # {ticket: مخاطرة المركز بالدولار من وقفه الأصليّ (تُحسب مرّة وتُثبَّت)}


def _risk_usd(p):
    """مخاطرة المركز بالدولار من وقفه (حساب الوسيط الرسميّ). تُثبَّت من أوّل قراءة كي لا يُصفّرها
    نقل الوقف للتعادل. بلا وقف/فشل الحساب ⇒ None (تسري أرضيّة ARM_USD)."""
    if p.ticket in _risk:
        return _risk[p.ticket]
    sl = float(getattr(p, "sl", 0.0) or 0.0)
    if sl <= 0:
        return None
    try:
        otype = mt5.ORDER_TYPE_BUY if p.type == 0 else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(otype, p.symbol, float(p.volume), float(p.price_open), sl)
        if loss is None or loss >= 0:            # وقفٌ عند/فوق الدخول (تعادل) = مخاطرة صفريّة الآن
            return None                          # لا نثبّت — لعلّ الوقف الأصليّ فات علينا؛ الأرضيّة تكفي
        r = abs(float(loss))
        if r >= 0.05:
            _risk[p.ticket] = r
            return r
    except Exception:
        pass
    return None


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _is_demo(ai):
    srv = (ai.server or "") if ai else ""
    return ("Trial" in srv) or ("Demo" in srv) or (ai and ai.login == 262998147)


def _net(p):
    # ⚠️ المركز المفتوح (TradePosition) لا يملك .commission (حقل الصفقة/deal فقط — عمولة الدخول مُحقَّقة
    # في الرصيد سلفاً). كان p.commission يرمي استثناءً كل دورة ⇒ تعطّل الحاصد 13 ساعة. الصافي العائم = ربح + سواب.
    return float(p.profit + getattr(p, "swap", 0.0))


def _close(p, reason):
    """إغلاق مركز رابح بسعر السوق (مع إعادة محاولة التعبئة). يبقي المجيك للمركز كي تبقى نسبة الربح للفرقة."""
    tk = mt5.symbol_info_tick(p.symbol)
    if not tk:
        return False
    px = tk.bid if p.type == 0 else tk.ask
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
           "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": p.ticket, "price": px, "deviation": 50, "magic": p.magic,
           "comment": f"harvest-{reason}"[:31]}
    for fill in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        req["type_filling"] = fill
        r = mt5.order_send(req)
        if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            return True
    return False


def _harvest():
    """يمرّ على مراكز المجيكات المستهدفة، ويجني الرابح المتراجع عن قمّته. يرجع (عدد المُجنى, الربح المُبنَك)."""
    pos = mt5.positions_get() or []
    live = set()
    banked = 0; banked_usd = 0.0
    for p in pos:
        if p.magic in _SKIP:                    # حارس صارم: يتخطّى الخارجيّ/اليدويّ/المُدار-ذاتياً — والباقي كلّه يُؤمَّن
            continue
        live.add(p.ticket)
        net = _net(p)
        if net <= MIN_NET:                      # 🚫 لا نُغلق على خسارة، ولا نجني الأخضر الضئيل — نتركه يكبر
            _peak.pop(p.ticket, None)
            continue
        pk = _peak.get(p.ticket, 0.0)
        if net > pk:
            _peak[p.ticket] = pk = net          # تتبّع القمّة (الرابح القويّ يرفعها ⇒ يجري)
        r_usd = _risk_usd(p)
        arm = max(ARM_USD, ARM_R * r_usd) if r_usd else ARM_USD
        if pk < arm:                            # لم يبلغ ربحاً ذا معنى نسبةً لمخاطرته ⇒ دعه يتنفّس
            continue
        big = (BIG_R * r_usd) if r_usd else BIG_USD
        gb = BIG_GIVEBACK if pk >= big else GIVEBACK
        if net <= pk * gb:                      # 🔒 تراجَع عن قمّته ⇒ اجنِ (التقط ~نصف القمّة قبل أن يعود)
            if _close(p, f"lock {net:.2f}/{pk:.2f}"):
                banked += 1; banked_usd += net
                _peak.pop(p.ticket, None)
                _log(f"جنى {p.symbol} magic {p.magic}: ${net:.2f} (من قمّة ${pk:.2f})")
    for t in list(_peak):                       # نظّف القمم للتذاكر المُغلقة
        if t not in live:
            _peak.pop(t, None)
    for t in list(_risk):                       # ونظّف مخاطر التذاكر المُغلقة
        if t not in live:
            _risk.pop(t, None)
    return banked, banked_usd


def _save(st):
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def main():
    claim("profit_harvester")                      # 🔒 قفل نسخة-مفردة (لا تداول مزدوج)
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    ai = mt5.account_info()
    if not _is_demo(ai):                          # 🛡️ ديمو-فقط
        _log(f"ليس حساب ديمو (login={getattr(ai,'login',None)} server={getattr(ai,'server',None)}) — أرفض العمل"); return
    _log(f"profit_harvester start — 🌍 يجني كل مجيكات الأسطول على كل العملات (يتخطّى {sorted(_SKIP)})")
    total = 0; total_usd = 0.0; last_save = 0.0
    while True:
        try:
            if KILL.exists() or KILL_D.exists():
                _save({"ts": time.time(), "state": "kill_switch", "banked": total, "banked_usd": round(total_usd, 2)})
                time.sleep(POLL_S); continue
            n, usd = _harvest()
            total += n; total_usd += usd
            now = time.time()
            if now - last_save >= 2.0:            # حفظ مُهدّأ
                tracked = len(_peak)
                _save({"ts": now, "state": "نشط 🌍 (يؤمّن أرباح كل الأسطول/كل العملات)", "skip": sorted(_SKIP),
                       "tracked_winners": tracked, "banked_total": total, "banked_usd": round(total_usd, 2)})
                last_save = now
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
