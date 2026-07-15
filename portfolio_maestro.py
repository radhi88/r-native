# -*- coding: utf-8 -*-
"""portfolio_maestro.py — المايسترو: عقل حوكمة/تخصيص المحفظة لمحرّكاتنا.

«Agentic AI: حوكمة العمليّة» — يوزّع رأس المال (مضاعِف لوت لكل محرّك) حسب **الأداء الصافي
الحقيقيّ بعد التكلفة**، لا حسب الرغبة: **يخنق النزّافين المُثبتين، يبقي المحايد، يكافئ الرابح
بتحفّظ**، + طبقة **خفض-مخاطرة محفظيّة** تتدخّل مبكّراً عند السحب (قبل كارثة الأرضية 50%).

صدق وحدود:
  • يحكم **محرّكاتنا فقط** {our magics}. لا يلمس اليدويّ (0) ولا الخبراء الخارجيّين — تلك للمستخدم.
  • قراءة-فقط للسوق: يكتب engine_governance.json؛ المحرّكات تقرأ مضاعِفها وتقيس لوتها.
  • غير متماثل (انحياز للبقاء): الخنق قويّ (حتى 0.25×)، التحفيز ضعيف (حتى 1.3×).
  • لا يلمس master_floor (الكارثة) — يكمّله بتدخّلٍ أبكر.

Run: pythonw portfolio_maestro.py   (windowless تحت الوصيّ)
"""
from __future__ import annotations
from engine_lock import claim
import json, time
from pathlib import Path
from collections import defaultdict
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
OUT = RN / "engine_governance.json"
LOG = RN / "portfolio_maestro.log"
KILL = ROOT / "kill_switch.txt"

# ══════════════════════════════════════════════════════════════════════════
# 🧠 FLEET MIND — «العقل الجديد»: المحرّكات تُدير بعضها عبر الترابط بدل التجمّد فرديّاً.
#   المبدأ (طلب المستخدم صراحةً): «لا تجميد» — كل شيء مُطلَقٌ إلّا شبكة الكارثة
#   (master_floor 130% + كِلا مسارَي kill_switch + حارس Trial/Demo). النزّاف لا يُقال:
#   يُخنَق صغيراً كي يبقى يتعلّم؛ فقط master_floor يوقف بالكامل.
#   الجماعة تحكم الفرد: كل محرّك يأخذ lot_mult من مكانته المُقاسة مقابل الأسطول،
#   مضروباً بعامل ميزانيّة الأسطول (حالة المخاطرة الجماعيّة). قراءة-فقط، لا يتداول أبداً.
SCORE   = RN / "desk_scoreboard.json"           # 📊 مصدر الأداء الحيّ لكل ماجيك (net_today/net_3d/payoff/…)
FLEET_OUT = RN / "fleet_mind.json"              # 📸 لقطة بشريّة للواجهة (سبب كل مضاعِف)
# محرّكاتنا المنفّذة (الجيل الحيّ) — هؤلاء يُحكَمون بعقل الأسطول:
FLEET_MAGICS = {20260701: "الحارس", 20260706: "R Core 🥷", 20260707: "قنّاص المجلس 🏛️",
                20260709: "حارس العملات 🌍", 20260703: "محاكي راضي", 20260631: "يوتيوب 📺"}
# 🚫 لا نحكمهم أبداً: يدويّ + خبراء المستخدم الخارجيّون + محرّكات ذاتيّة-الإدارة:
FLEET_SKIP = {0, 2447, 20250418, 20250421, 20250422, 20250618, 3627}
MIN_MULT = 0.8        # 🔼 رُفِع 0.4→0.8 (طلب المستخدم «ارفعه»): حتى النزّاف يدخل بحجمٍ شبه كامل — لا خنق يوقفه
MAX_MULT = 1.8        # أقصى تحفيز لأفضل رابح مُقاس (المنفّذ يخنق فقط min(1.0)؛ الحارس/multi لا يطبّقان الحوكمة أصلاً)
DEEP_DD_PCT = 8.0     # سحبٌ يوميّ للأسطول ≥ هذا% من الحقوق = عميق ⇒ خنق جماعيّ (0.3، لا صفر)
MILD_DD_PCT = 3.0     # سحبٌ خفيف ⇒ ميزانيّة 0.6

OURS = {20260608: "multi_trader", 20260618: "army_warroom", 20260628: "gold_scalper",
        20260612: "tournament", 20260614: "news_gene", 20260616: "orb",
        20260629: "pipflow_core", 20260605: "brain_server", 20260617: "legacy_20260617",
        20260630: "momentum_harvester"}
#  ↑ 20260605/20260617 أُضيفا (تدقيق صفقات-البوتات): كانا نزّافين غير محكومين خارج المايسترو
#  ↑ 20260630 = حاصد الزخم البطيء (TSM) — الحافّة البنيويّة الموثّقة على كل الأزواج (بديل الحمل المسدود)
WINDOW_D = 7
MIN_N    = 30          # عيّنة كافية للحكم على محرّك
THR_EXP  = -0.05       # توقّع/صفقة أسوأ من هذا (صافي) = نزّاف مُثبت ⇒ خنق
BOOST_EXP = 0.05       # أفضل من هذا = رابح ⇒ تحفيز متحفّظ
MULT_FLOOR = 0.25      # أدنى مضاعِف لنزّافٍ عاديّ
MULT_CAP   = 1.30      # أقصى تحفيز (انحياز للبقاء: التحفيز ضعيف)
CATA_EXP   = -0.5      # 🔥 توقّع/صفقة أسوأ من هذا = نزّاف كارثيّ ⇒ شبه إيقاف (المايسترو "يُقيل" النازف)
CATA_FLOOR = 0.12      # مضاعِف الكارثيّ (يبقى ضئيلاً للبيانات لا صفراً)
KEEP_ACTIVE = {20260628}   # 🔄 طلب المستخدم «عيده واضبطه»: الذهب يبقى يفتح (يُخنَق ~0.4× لا يُقال) — مضبوطٌ الآن
                           # بـlot_guard + لا-تكديس-على-أحمر + استرداد + انقلاب-حاسم + وقف-ذروة (الحماية مطبّقة).
KEEP_FLOOR  = 0.30         # خُفِّض 0.4→0.3: حصّة أصغر (يتداول بحذر أكبر بعد ضبطه)
ACUTE_MIN    = 90      # 🚑 نافذة حادّة (دقائق): نمسك النزيف السريع الذي تفوّته نافذة 7 أيّام (جذر «نوصل ربح ثم يخفس»)
ACUTE_DD_PCT = 2.0     # محرّكٌ يخسر مُحقَّقاً ≥ هذا% من الحقوق في النافذة الحادّة = نزيفٌ حادّ ⇒ خنق فوريّ + إيقاف مؤقّت (دائرة قطع)
POLL_S   = 60.0        # حوكمة كل دقيقة (2026-07-08: العقل الجماعيّ يحتاج استجابةً أسرع لخنق النازف — كان 300ث)


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _base_mult(n, exp):
    """مضاعِف الأداء + الرتبة لكل محرّك (غير متماثل). يرجع (mult, tier)."""
    if n < MIN_N:
        return 1.0, "small_sample"                   # عيّنة صغيرة ⇒ محايد
    if exp < CATA_EXP:                               # 🔥 كارثيّ ⇒ شبه إيقاف ("إقالة" النازف)
        return CATA_FLOOR, "catastrophic"
    if exp < THR_EXP:                                # نزّاف: كلّما ساء، خُنِق أكثر
        return max(MULT_FLOOR, min(0.9, 1.0 + 1.5 * exp)), "bleeder"
    if exp > BOOST_EXP:                              # رابح: تحفيز متحفّظ
        return min(MULT_CAP, 1.0 + exp), "proven"
    return 1.0, "neutral"


def _derisk(dd_pct):
    """طبقة خفض-المخاطرة المحفظيّة: تخفض كل المضاعِفات مع تعمّق السحب (تدخّل أبكر من الأرضية)."""
    if dd_pct >= 20: return 0.45
    if dd_pct >= 10: return 0.65
    if dd_pct >= 5:  return 0.85
    return 1.0


def _peak():
    try:
        return float(json.load(open(RN / "master_floor_state.json", encoding="utf-8")).get("peak", 0.0))
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
# 🧠 FLEET MIND
def _budget_factor(fleet_daily, eq):
    """🚫 أزال المستخدم «حدّ اليوم» صراحةً (2026-07-08 «شيل هذا حد اليوم — قاعدتك تقول قف وخله يدخل
    صفقات»): لا خنقٌ جماعيّ بالسحب اليوميّ بعد الآن — تبقى **جدارةُ كلّ محرّك** (standing_mult:
    الرابح يُدفَع، النزّاف يُخنَق بأدائه هو) + **master_floor** الحاجزَ الوحيد. نُبقي تسمية الحالة
    للعرض فقط. (كان: عميق 0.3 / خفيف 0.6 ⇒ الآن 1.0 دائماً كي يواصل الدخول.)"""
    if eq <= 0:
        return 1.0, "unknown"
    dd_pct = (-fleet_daily / eq * 100.0) if fleet_daily < 0 else 0.0   # للعرض فقط الآن
    if dd_pct >= DEEP_DD_PCT:
        return 1.0, "deep_drawdown"      # لا خنق — يواصل الدخول (master_floor وحده يوقف)
    if dd_pct >= MILD_DD_PCT:
        return 1.0, "mild_drawdown"      # لا خنق — يواصل الدخول
    return 1.0, "healthy"


def _engine_mult(row):
    """مكانة المحرّك المُقاسة مقابل الأسطول ⇒ مضاعِف قبل الميزانيّة، ضمن [MIN_MULT..MAX_MULT].
    الرابح (net_3d موجب / payoff≥1) يُدفَع نحو MAX؛ النزّاف (net_3d سالب، خاصّة payoff<0.3)
    يُخنَق نحو MIN — لكن لا يُجمّد أبداً (يبقى يفتح صغيراً كي يتعلّم)."""
    net3d = float(row.get("net_3d") or 0.0)
    payoff = row.get("payoff")
    payoff = float(payoff) if payoff is not None else None
    if net3d > 0 or (payoff is not None and payoff >= 1.0):        # 🏆 رابح مُقاس ⇒ تحفيز
        m = 1.0 + min(0.8, 0.15 + max(0.0, net3d) * 0.02)         # يتدرّج مع الربح حتى MAX
        if payoff is not None and payoff >= 1.0:
            m = max(m, 1.2)
        return round(min(MAX_MULT, m), 3)
    # نزّاف: كلّما ساء الأداء و/أو انهار الـpayoff، خُنِق أكثر (بلا تجميد)
    thr = 1.0 + max(-0.6, net3d * 0.03)                            # سالب أعمق ⇒ أقلّ
    if payoff is not None and payoff < 0.3:                        # 🩸 payoff منهار ⇒ خنقٌ إضافيّ
        thr -= 0.2
    return round(max(MIN_MULT, min(1.0, thr)), 3)


def _fleet_mind(gov):
    """العقل الجديد: يقرأ الأداء الحيّ لكل ماجيك (desk_scoreboard) + الحقوق، يحسب حالة المخاطرة
    الجماعيّة وعامل الميزانيّة، ثمّ يخصّص lot_mult لكل محرّكٍ منفّذ (الجماعة تحكم الفرد).
    يدمج mults في نفس ملفّ الحوكمة (توافقٌ خلفيّ: engine_gov يقرأها) + يكتب لقطة fleet_mind.
    قراءة-فقط عدا ملفّاته؛ لا يُجمّد (لا يضيف أحداً إلى paused)؛ لا يتداول أبداً."""
    try:
        board = json.load(open(SCORE, encoding="utf-8"))
    except Exception as e:
        _log(f"fleet_mind: تعذّر قراءة اللوحة ({type(e).__name__}) — يبقى المضاعِف كما هو")
        return gov
    rows = {int(r.get("magic")): r for r in board.get("magics", []) if r.get("magic") is not None}
    eq = float(gov.get("equity") or (board.get("account", {}) or {}).get("equity") or 0.0)

    fleet_daily = sum(float(rows.get(m, {}).get("net_today") or 0.0) for m in FLEET_MAGICS)
    budget, fleet_state = _budget_factor(fleet_daily, eq)

    fleet_mults = {}; detail = {}
    for m, name in FLEET_MAGICS.items():
        if m in FLEET_SKIP:                                    # حماية مزدوجة: لا نحكم المُستثنى أبداً
            continue
        row = rows.get(m, {})
        stand = _engine_mult(row)                             # مكانةٌ مقابل الأسطول
        fm = round(max(MIN_MULT, min(MAX_MULT, stand * budget)), 3)   # × ميزانيّة الأسطول (لا تجميد)
        fleet_mults[str(m)] = fm
        n3 = float(row.get("net_3d") or 0.0); po = row.get("payoff")
        if stand >= 1.2:
            why = "رابح ⇒ تحفيز"
        elif stand <= 0.55:
            why = "نزّاف ⇒ خنق (بلا تجميد)"
        else:
            why = "محايد"
        detail[str(m)] = {"engine": name, "net_today": round(float(row.get("net_today") or 0.0), 2),
                          "net_3d": round(n3, 2), "payoff": po, "wr_today": row.get("wr_today"),
                          "n_open": row.get("n_open"), "standing_mult": stand, "lot_mult": fm, "why": why}

    ts = time.time()
    # دمجٌ متوافق-خلفيّاً: نُبقي كل مفاتيح gov القديمة، ونُحدّث/نضيف mults لمحرّكات الأسطول.
    merged = dict(gov.get("mults", {})); merged.update(fleet_mults)
    gov["mults"] = merged
    gov["magics"] = fleet_mults                               # خريطة صريحة يقرأها المنفّذ {"20260706":1.3,…}
    gov["fleet_state"] = fleet_state
    gov["budget_factor"] = budget
    gov["fleet_daily"] = round(fleet_daily, 2)
    gov["updated"] = ts
    # لا نلمس gov["paused"] إطلاقاً: العقل الجديد لا يُجمّد أحداً (فقط master_floor يوقف بالكامل).

    snap = {"updated": ts, "iso": time.strftime("%H:%M:%S"), "equity": round(eq, 2),
            "fleet_daily": round(fleet_daily, 2), "fleet_state": fleet_state, "budget_factor": budget,
            "min_mult": MIN_MULT, "max_mult": MAX_MULT, "engines": detail,
            "note": "العقل الجديد: الجماعة تحكم الفرد. lot_mult=(مكانة مقابل الأسطول)×(ميزانيّة الأسطول). لا تجميد — فقط master_floor/kill يوقف."}
    try:
        ftmp = FLEET_OUT.with_suffix(".json.tmp")
        json.dump(snap, open(ftmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ftmp.replace(FLEET_OUT)
    except Exception as e:
        _log(f"fleet_mind: تعذّر كتابة اللقطة ({type(e).__name__})")
    # 🩺 2026-07-15: فُكّ f-string المتداخل (كان يكسر الترجمة على Python ≤3.11 ⇒ المايسترو لا يقلع)
    _fmults = ", ".join(f"{n}={fleet_mults.get(str(m), '?')}" for m, n in FLEET_MAGICS.items())
    _log(f"🧠 fleet_mind: {fleet_state} budget {budget} fleet_daily {fleet_daily:.2f} | {_fmults}")
    return gov


def _cycle():
    deals = mt5.history_deals_get(time.time() - WINDOW_D * 86400, time.time()) or []
    net = defaultdict(float); n = defaultdict(int); acute = defaultdict(float)
    acute_cut = time.time() - ACUTE_MIN * 60        # 🚑 نافذة النزيف الحادّ (تُحسب من نفس صفقات الـ7 أيّام)
    for d in deals:
        if d.entry == 1 and d.magic in OURS:
            pnl = d.profit + d.commission + d.swap
            net[d.magic] += pnl
            n[d.magic] += 1
            if d.time >= acute_cut:
                acute[d.magic] += pnl
    acct = mt5.account_info()
    eq = acct.equity if acct else 0.0
    peak = max(_peak(), eq)
    dd_pct = ((peak - eq) / peak * 100.0) if peak > 0 else 0.0
    derisk = _derisk(dd_pct)
    mults = {}; raw = {}
    for m in OURS:
        exp = (net[m] / n[m]) if n[m] else 0.0
        bm, tier = _base_mult(n[m], exp)
        if tier == "catastrophic" and m in KEEP_ACTIVE:             # 🥇 المستخدم يريده يتداول — يُخنَق لا يُقال
            bm, tier = KEEP_FLOOR, "kept_active"
        if eq > 0 and acute[m] <= -(ACUTE_DD_PCT / 100.0) * eq:      # 🚑 نزيفٌ حادّ (تفوّته نافذة 7 أيّام) ⇒ قطع فوريّ
            if m in KEEP_ACTIVE:
                bm, tier = min(bm, CATA_FLOOR), "acute_kept"         # يبقى يفتح بأرضية (طلب المستخدم) لكن مخنوقٌ جداً
            else:
                bm, tier = CATA_FLOOR, "acute_bleeder"              # إيقاف مؤقّت (يُدير فقط) حتى يبرد ACUTE_MIN دقيقة
        fm = round(max(CATA_FLOOR, min(MULT_CAP, bm * derisk)), 3)   # أداء × خفض-مخاطرة
        mults[str(m)] = fm
        raw[str(m)] = {"engine": OURS[m], "n": n[m], "net": round(net[m], 2), "acute": round(acute[m], 2),
                       "exp": round(exp, 4), "base_mult": round(bm, 3), "tier": tier}
    paused = [int(k) for k, v in raw.items() if v.get("tier") in ("catastrophic", "acute_bleeder")]   # 🔥/🚑 لا يفتح جديداً (إدارة فقط)
    out = {"ts": time.time(), "window_d": WINDOW_D, "equity": round(eq, 2), "peak": round(peak, 2),
           "dd_pct": round(dd_pct, 1), "derisk": derisk, "mults": mults, "paused": paused, "raw": raw,
           "note": "حوكمة محرّكاتنا فقط (لا يدويّ/خارجيّ). المحرّك يضرب لوته بـ mults[magic]."}
    # 🧠 العقل الجماعيّ: يدمج مضاعفات المتحدّين (FLEET_MAGICS من السبورة الحيّة) في out + يكتب fleet_mind.json
    # قبل الكتابة الوحيدة أدناه — كي يصل مضاعِف كل متحدٍّ للمنفّذ عبر out["magics"].
    try:
        _fleet_mind(out)
    except Exception as e:
        _log(f"fleet_mind err: {type(e).__name__}: {e}")
    tmp = OUT.with_suffix(".json.tmp")
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tmp.replace(OUT)
    worst = min(raw.items(), key=lambda kv: kv[1]["net"])
    _log(f"حوكمة: dd {dd_pct:.1f}% derisk {derisk} | أسوأ {worst[1]['engine']} net {worst[1]['net']} mult {mults[worst[0]]} "
         f"| {', '.join(f'{OURS[m]}={mults[str(m)]}' for m in OURS)}")
    return out


def main():
    claim("portfolio_maestro")                      # 🔒 قفل نسخة-مفردة (لا تداول مزدوج)
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    _log(f"portfolio_maestro start — يحكم {list(OURS.values())}")
    while True:
        try:
            _cycle()
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
