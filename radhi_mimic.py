# -*- coding: utf-8 -*-
"""radhi_mimic.py — 🪞 محاكي أسلوب راضي اليدويّ الحرفيّ (ماجيك 20260703 · XAUUSDm · ديمو فقط).

المصدر: الحساب الحقيقي 256245478 يوم 2026-07-02 — 85 إغلاقاً يدويّاً مُراقَباً حيّاً (WR ملحوظ ~90%).

النمط أ — قنص (الافتراضيّ): سكالب مع الترند (ميل EMA50 على M5 + السعر في جهته)، دخول على ارتداد:
  شمعة M1 تلمس EMA50-M1 ضمن 0.15×ATR ثم التالية تُغلق باتجاه الترند. لوت 0.01 ثابت،
  هدف 2.0$ (مشدود [1.2، 3.0])، وقف خلف قاع/قمة الارتداد [1.8$، 3.5$]. احتفاظ وسيط المستخدم ~180ث.
النمط ب — ركوب الموجة: يُسلَّح داخل نافذة خبر USD مهم [الحدث، +15د] أو باندفاعة ≥8$ في شمعتي M1.
  الاتجاه = اتجاه الاندفاعة. دخول على أوّل ارتداد 30-50% من الرجل أو لمسة EMA9-M1، الوقف خلف
  أقصى الارتداد (خطر ≤6$). تكديس حتى 3×0.01 (ارتداد جديد + فجوة ≥20ث لكل طبقة).
  «بنك الموجة» (توقيع المستخدم — أفضل قبضة واحدة له 20.25$): إغلاق الكومة كلّها عند إغلاق M1
  خلف EMA9 عكس الاتجاه أو ابتلاع معاكس >60% من جسم الشمعة السابقة، ثم يُسمح بموجة جديدة على
  الارتداد التالي (حدّ 3 موجات لكل نافذة). تسطيح إجباريّ بعد 15د من آخر دخول.
⛔ الفيتو الذهبيّ — ثابت مُدمج غير قابل للضبط (درس المستخدم بلسانه «شريت بالقمة»): لا دخول إذا كان
  مدى شمعة M1 (الجارية أو آخر مغلقة) > 5$ أو السعر أبعد من 5$ عن EMA50-M1 باتجاه الصفقة.
الجدران الصلبة: SL≠0 في كلّ أمر عند الإرسال · ≤3 مراكز لهذا الماجيك (تُفحص قبل الإرسال) · خسارة
  اليوم (محقّقة بالماجيك + عائمة) ≤3% من الحقوق وإلا تجميد حتى منتصف الليل (مُثبَّت في الحالة) ·
  مفتاحا القتل (r_native + الجذر) كلّ دورة · ديمو فقط (Trial/Demo في اسم الخادم) · سبريد ≤0.6$ ·
  تهيئة MT5 واحدة بـ6 محاولات (لا init داخل الحلقة) · حلقة بسرعتين: 1ث موجة / 5ث قنص."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "radhi_mimic.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time
from datetime import datetime, timedelta
import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("radhi_mimic")
except SystemExit:
    raise
except Exception:
    pass

MAGIC = 20260703
SYM = "XAUUSDm"
CFG_F = os.path.join(_RN, "radhi_mimic_config.json")
STATUS_F = os.path.join(_RN, "radhi_mimic_status.json")
FEED_F = os.path.join(_RN, "radhi_mimic_feed.jsonl")
EV_F = os.path.join(_RN, "news_events.json")
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

# 📊 المعايير الممحوصة كما مُنجمت من مراقبة المستخدم الحيّة — تُدمج كافتراضات
MINED = {"source": "real account 256245478, 2026-07-02, 85 manual closes, observed live",
         "scalp": {"median_tp_usd": 2, "tp_clamp": [1.2, 3], "typical_loss_usd": 1, "max_sl_usd": 3.5,
                   "median_hold_s": 180, "wr_observed": 90},
         "wave": {"impulse_min_usd": 8, "retrace_pct": [30, 50], "stack_max": 3,
                  "bank_best_single": 20.25, "leg_hold_s": 78, "force_flat_min": 15},
         "reentry_gap_s_min": 20,
         "golden_veto": "no entry when M1 candle range > $5 or price > $5 beyond M1 EMA50 — "
                        "user self-diagnosed leak «شريت بالقمة», hard-coded"}

# ⛔ الفيتو الذهبيّ — ثوابت مُدمجة عمداً (ليست في ملفّ الإعدادات كي لا تُعطَّل أبداً)
GOLDEN_BAR_USD = 5.0     # مدى شمعة M1 (جارية أو آخر مغلقة) > 5$ ⇒ لا دخول
GOLDEN_EXT_USD = 5.0     # السعر أبعد من 5$ عن EMA50-M1 باتجاه الصفقة ⇒ لا دخول «شريت بالقمة»

G = {"last_sig_bar": 0, "last_entry_ts": 0.0, "last_imp_bar": 0,
     "status_ts": 0.0, "veto_ts": 0.0, "pnl": 0.0, "pnl_ts": 0.0}


def _cfg():
    d = {"enabled": True, "lot": 0.01, "tp_r": 2.0, "tp_r_max_usd": 8.0, "tp_usd": 2.0, "tp_clamp": [1.2, 3.0],
         "sl_min_usd": 1.8, "sl_max_usd": 3.5, "pullback_atr_frac": 0.15,
         "wave_impulse_usd": 8.0, "wave_retrace_pct": [30, 50], "wave_stack_max": 3,
         "wave_risk_max_usd": 6.0, "wave_force_flat_min": 15, "wave_max_per_window": 3,
         "event_window_min": 15, "reentry_gap_s": 6, "spread_max_usd": 0.6, "bank_usd": 5.0,
         "daily_loss_pct": 3.0, "min_confluence": 3, "night_block": True,
         "pre_news_block_min": 10, "_mined": MINED,
         "_note": "🪞 محاكي أسلوب راضي: قنص EMA50 مع الترند + ركوب موجة الأخبار/الاندفاعات مع «بنك "
                  "الموجة». اللوت 0.01 ثابت. الفيتو الذهبيّ («شريت بالقمة») مُدمَج في الكود ولا يُضبط "
                  "من هنا عمداً. ديمو فقط — ماجيك 20260703."}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _st_load():
    """يسترجع التجميد/العدّادات من ملف الحالة (الصمود عبر إعادة التشغيل — جدار صلب)."""
    try:
        d = json.load(open(STATUS_F, encoding="utf-8"))
        return {"day": str(d.get("day", "")), "veto_count": int(d.get("veto_count", 0)),
                "frozen_until": float(d.get("frozen_until", 0) or 0)}
    except Exception:
        return {"day": "", "veto_count": 0, "frozen_until": 0.0}


def _status(st, mode, pnl, force=False):
    now = time.time()
    if not force and now - G["status_ts"] < 5:
        return
    G["status_ts"] = now
    d = {"ts": round(now, 1), "iso": datetime.now().isoformat(timespec="seconds"), "mode": mode,
         "positions": len(_positions()), "pnl_today": round(pnl, 2),
         "veto_count": int(st.get("veto_count", 0)), "day": st.get("day", ""),
         "frozen_until": st.get("frozen_until", 0), "magic": MAGIC, "symbol": SYM}
    try:
        t = STATUS_F + ".tmp"
        json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(t, STATUS_F)
    except Exception:
        pass


def _feed(kind, **kw):
    try:
        kw.update({"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
                   "kind": kind})
        with open(FEED_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _positions():
    return [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == MAGIC]


def _ema(vals, n):
    if vals is None or len(vals) < n:
        return None
    k = 2.0 / (n + 1); e = sum(vals[:n]) / float(n)
    for v in vals[n:]:
        e += k * (v - e)
    return e


def _atr(r, n=14):
    if r is None or len(r) < n + 1:
        return None
    trs = [max(float(r[i]["high"] - r[i]["low"]), abs(float(r[i]["high"] - r[i - 1]["close"])),
               abs(float(r[i]["low"] - r[i - 1]["close"]))) for i in range(1, len(r))]
    return sum(trs[-n:]) / float(n)


def _closed(tf, n):
    """شموع مغلقة فقط — من الفهرس 1 (الشمعة 0 هي الجارية ولا نتاجر عليها)."""
    return mt5.copy_rates_from_pos(SYM, tf, 1, n)


def _pnl_today():
    """خسارة/ربح اليوم = محقّق بالماجيك (history_deals_get منذ منتصف الليل) + عائم المراكز."""
    now = time.time()
    if now - G["pnl_ts"] < 10:
        return G["pnl"] + sum(float(p.profit) for p in _positions()) - G.get("pnl_float", 0.0)
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day0_ep = day0.timestamp()                        # حدّ اليوم بالحقبة المحلية الحقيقية
    realized = 0.0
    try:
        # ⏰ درس 2026-07-03: history_deals_get بنطاق datetime ينزاح بفارق توقيت الخادم (3س) فيُدخل
        # صفقات أمس في «اليوم» ويجمّد ظلماً ⇒ نسحب نافذة أوسع ونصفّي بالحقبة (d.time UTC دقيق).
        _deals = mt5.history_deals_get(day0 - timedelta(hours=12),
                                       datetime.now() + timedelta(hours=12)) or []
        # 🩺 2026-07-15: عملية رصيد اليوم (تصفير/إيداع، type 2/3) = خطُّ أساسٍ جديد —
        # تصفيةُ التصفير لا تُحسب خسارة يومٍ تجمّدنا حتى منتصف الليل.
        _base = max((float(d.time) for d in _deals
                     if getattr(d, "type", -1) in (2, 3) and float(getattr(d, "time", 0)) >= day0_ep),
                    default=day0_ep)
        for d in _deals:
            if d.magic == MAGIC and float(getattr(d, "time", 0)) >= _base:
                realized += float(d.profit) + float(d.commission) + float(d.swap)
    except Exception:
        pass
    flt = sum(float(p.profit) for p in _positions())
    G["pnl"] = realized + flt; G["pnl_float"] = flt; G["pnl_ts"] = now
    return G["pnl"]


def _next_midnight():
    return (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                        microsecond=0).timestamp()


def _news_window(cfg):
    """نافذة خبر USD مهم نشطة الآن: [الحدث، الحدث + 15د]."""
    try:
        d = json.load(open(EV_F, encoding="utf-8"))
        evs = d.get("events", d) if isinstance(d, dict) else d
    except Exception:
        return None
    now = time.time()
    for e in evs or []:
        ep = float(e.get("epoch") or 0)
        if str(e.get("currency")) not in ("USD", "ALL"):
            continue
        if str(e.get("impact")) not in ("High", "Medium"):
            continue
        if ep <= now <= ep + cfg.get("event_window_min", 15) * 60:
            return {"ep": ep, "title": str(e.get("title", "?"))}
    return None


def _impulse(cfg):
    """اندفاعة: شمعتان مغلقتان بحركة ≥8$ بنفس الاتجاه، أو — ⚡ ترقية السرعة 2026-07-03 —
    الشمعة الجارية وحدها تتحرّك ≥8$ (رصدٌ لحظيّ داخل الشمعة: لا ننتظر إغلاقها لنرى الانفجار)."""
    thr = float(cfg.get("wave_impulse_usd", 8.0))
    fo = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, 1)     # الجارية
    if fo is not None and len(fo):
        netf = float(fo[0]["close"]) - float(fo[0]["open"])
        if abs(netf) >= thr:                                       # انفجارٌ يحدث الآن
            return {"dir": 1 if netf > 0 else -1, "hi": float(fo[0]["high"]),
                    "lo": float(fo[0]["low"]), "t": int(fo[0]["time"]) + 1}   # +1 يميّزه عن المغلقة
    r = _closed(mt5.TIMEFRAME_M1, 3)
    if r is None or len(r) < 2:
        return None
    b1, b2 = r[-2], r[-1]
    net = float(b2["close"]) - float(b1["open"])
    d1 = float(b1["close"]) - float(b1["open"]); d2 = float(b2["close"]) - float(b2["open"])
    if abs(net) >= thr and d1 * net > 0 and d2 * net > 0:
        hi = max(float(b1["high"]), float(b2["high"])); lo = min(float(b1["low"]), float(b2["low"]))
        return {"dir": 1 if net > 0 else -1, "hi": hi, "lo": lo, "t": int(b2["time"])}
    return None


def _golden_veto(direction, px):
    """⛔ الفيتو الذهبيّ — درس «شريت بالقمة»: يمنع الشراء بقمّة ممطوطة والبيع بقاعٍ ممطوط."""
    try:
        fo = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, 1)   # الشمعة الجارية
        cl = _closed(mt5.TIMEFRAME_M1, 80)
        if fo is None or len(fo) < 1 or cl is None or len(cl) < 55:
            return "بيانات M1 ناقصة — نمتنع احتياطاً"
        rng_f = float(fo[0]["high"] - fo[0]["low"]); rng_c = float(cl[-1]["high"] - cl[-1]["low"])
        if rng_f > GOLDEN_BAR_USD:
            return f"مدى الشمعة الجارية {rng_f:.2f}$ > {GOLDEN_BAR_USD}$"
        if rng_c > GOLDEN_BAR_USD:
            return f"مدى آخر شمعة مغلقة {rng_c:.2f}$ > {GOLDEN_BAR_USD}$"
        e50 = _ema([float(x["close"]) for x in cl], 50)
        if e50 is not None and direction * (px - e50) > GOLDEN_EXT_USD:
            return f"السعر {abs(px - e50):.2f}$ أبعد من {GOLDEN_EXT_USD}$ عن EMA50-M1 — «شريت بالقمة»"
    except Exception as ex:
        return f"استثناء أثناء فحص الفيتو ({type(ex).__name__}) — نمتنع احتياطاً (fail-closed)"
    return None


# ══════════ 🧭 بوابة التوافق (2026-07-02 بأمر المستخدم) ══════════
# «لا يشتري بالقمم إلا بمؤشرات قوية يستند عليها، ولا يبيع عكس الترند أو يشتري عكسه»
# تجمع كل أدوات المشروع الحيّة: نبض السوق (SMC/BOS/POC/Stoch) + مكتب الحسابات + ترند M5/H1 الداخلي.
PULSE_F = os.path.join(_RN, "market_pulse.json")
DESK_F = os.path.join(_RN, "quant_desk.json")
TOP_MIN_SCORE = 5        # ⛔ ثابت مُدمج غير قابل للضبط: دخول منطقة القمّة يتطلّب ≥5/7 + BOS مؤيّد


def _read_fresh(path, max_age_s):
    """يقرأ JSON فقط إن كان طازجاً — القِدَم = لا رأي (محافظ)."""
    try:
        if time.time() - os.path.getmtime(path) > max_age_s:
            return None
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _tf_bias(tf, bars=140):
    """اتجاه إطار زمنيّ: ميل EMA50 + جهة السعر ⇒ 1/-1/0 (محسوب داخلياً — لا اعتماد خارجيّ)."""
    r = _closed(tf, bars)
    if r is None or len(r) < 60:
        return 0
    c = [float(x["close"]) for x in r]
    e, ep = _ema(c, 50), _ema(c[:-3], 50)
    if e is None or ep is None:
        return 0
    if e > ep and c[-1] > e:
        return 1
    if e < ep and c[-1] < e:
        return -1
    return 0


def _candle_read(direction):
    """🕯️ تشريح الشموع اللحظيّ (أمر المستخدم 2026-07-02): «قبلها وتكويناتها وتجمّعاتها ونزولها وصعودها
    ومقاساتها وذيولها وألوانها — ونعرف وش راح يصير بعدها». يرجع (انحياز -2..+2، قراءة نصيّة)."""
    r = _closed(mt5.TIMEFRAME_M1, 20)
    if r is None or len(r) < 14:
        return 0, "بيانات ناقصة"
    atr = _atr(r) or 0.5
    bodies = [float(x["close"] - x["open"]) for x in r]
    rngs = [max(float(x["high"] - x["low"]), 1e-9) for x in r]
    upw = [float(x["high"]) - max(float(x["close"]), float(x["open"])) for x in r]
    dnw = [min(float(x["close"]), float(x["open"])) - float(x["low"]) for x in r]
    bias = 0; notes = []
    if all(b > 0 for b in bodies[-3:]):                              # تسلسل اللون (تجمّع صاعد)
        bias += 1; notes.append("3 خضر متتالية")
    elif all(b < 0 for b in bodies[-3:]):
        bias -= 1; notes.append("3 حمر متتالية")
    if any(dnw[i] >= 0.6 * rngs[i] and rngs[i] >= 0.6 * atr for i in (-1, -2)):
        bias += 1; notes.append("ذيل رفض سفليّ")                     # الذيول = رفض المستوى
    if any(upw[i] >= 0.6 * rngs[i] and rngs[i] >= 0.6 * atr for i in (-1, -2)):
        bias -= 1; notes.append("ذيل رفض علويّ")
    if abs(bodies[-1]) > abs(bodies[-2]) and bodies[-1] * bodies[-2] < 0:
        bias += 1 if bodies[-1] > 0 else -1; notes.append("ابتلاع")  # جسم يبتلع سابقه المعاكس
    if rngs[-2] > 2 * atr and (abs(bodies[-1]) < 0.25 * rngs[-1] or bodies[-1] * bodies[-2] < 0):
        bias += -1 if bodies[-2] > 0 else 1                          # عملاقة ثم دوجي/معاكسة = إنهاك ضدّها
        notes.append("إنهاك بعد شمعة عملاقة")
    if all(abs(b) < 0.35 * atr for b in bodies[-5:]):
        notes.append("تجمّع انضغاطيّ — انفجار قريب")                 # مقاسات صغيرة متراكبة
    return max(-2, min(2, bias)), "، ".join(notes) or "حيادية"


def _confluence(direction, px, m5b, h1b):
    """درجة التوافق 0-7 مع أسبابها — من كلّ عيون المشروع. الغائب/القديم = صفر نقاط (محافظ)."""
    parts = {}
    parts["m5"] = m5b == direction
    parts["h1"] = h1b == direction
    smc_t = bos_ok = poc_ok = stoch_ok = desk_ok = False
    pu = _read_fresh(PULSE_F, 120)
    sym = ((pu or {}).get("symbols") or {}).get(SYM) or {}
    smc = sym.get("smc") or {}
    try:
        smc_t = int(smc.get("trend", 0)) == direction
        bl = smc.get("bos") or []
        bos_ok = bool(bl) and int(bl[-1].get("dir", 0)) == direction     # آخر كسر بنية مؤيّد
        poc = float(smc.get("poc") or 0)
        poc_ok = poc > 0 and direction * (px - poc) > 0                  # السعر في جهة القيمة الصحيحة
        k = float((sym.get("momentum") or {}).get("stoch_k", 50))
        stoch_ok = (k < 85) if direction == 1 else (k > 15)              # لا شراء بإنهاك ولا بيع بتشبّع
    except Exception:
        pass
    dk = _read_fresh(DESK_F, 300)
    try:
        comp = float(((dk or {}).get("symbols") or {}).get(SYM, {}).get("composite", 0))
        desk_ok = direction * comp >= 10.0                               # المكتب يؤيّد بوضوح
    except Exception:
        pass
    cb, cread = _candle_read(direction)                              # 🕯️ العين الثامنة: تشريح الشموع
    brain_ok = False                                                 # 🧠 العين التاسعة: المخ الواحد (متبادل)
    try:
        ub = _read_fresh(os.path.join(_RN, "unified_brain.json"), 15)
        u = ((ub or {}).get("symbols") or {}).get(SYM) or {}
        brain_ok = int(u.get("dir", 0)) == direction and float(u.get("conviction", 0)) >= 0.30
    except Exception:
        pass
    parts.update({"smc": smc_t, "bos": bos_ok, "poc": poc_ok, "stoch": stoch_ok, "desk": desk_ok,
                  "candles": cb * direction >= 1, "brain": brain_ok})
    return sum(1 for v in parts.values() if v), parts, smc, cb, cread


def _gap_hazard(direction, px, smc):
    """💨 فجوات غير مملوءة خلف السعر = فراغ سيولة/مغناطيس عكسيّ (درس المستخدم 2026-07-02:
    «يحذر أكثر إذا في فجوات — الذهب ترك تحته فجوات كبيرة واحنا نشتري!»). يرجع مجموع الفراغ بالدولار."""
    tot = 0.0
    try:
        for g in smc.get("fvg") or []:
            if g.get("inverted") or float(g.get("filled", 0) or 0) >= 0.7:
                continue
            lo, hi = float(g["lo"]), float(g["hi"])
            unfil = 1.0 - float(g.get("filled", 0) or 0)
            if direction == 1 and int(g.get("dir", 0)) == 1 and lo < px:
                tot += max(0.0, min(hi, px) - lo) * unfil        # فراغ صاعد تحتنا ونحن نشتري
            elif direction == -1 and int(g.get("dir", 0)) == -1 and hi > px:
                tot += max(0.0, hi - max(lo, px)) * unfil        # فراغ هابط فوقنا ونحن نبيع
    except Exception:
        pass
    return tot


_VOL = {"ts": 0.0, "pct": None}


def _vol_regime():
    """🌡️ نظام التقلب الكوانتي (درس فيديو 2026-07-03): ATR14-H1 الآن مقابل 30 يوماً — مخبّأ 5 دقائق.
    يُرجع percentile (0-100) أو None. الفلتر: عالٍ ⇒ موجات فقط · منخفض/متوسط ⇒ الكل مسموح."""
    now = time.time()
    if now - _VOL["ts"] < 300:
        return _VOL["pct"]
    pct = None
    try:
        rh = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 1, 760)
        if rh is not None and len(rh) > 80:
            h = rh["high"]; l = rh["low"]; c = rh["close"]
            trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
                   for i in range(1, len(rh))]
            atrs = [sum(trs[i - 14:i]) / 14.0 for i in range(14, len(trs))]
            pct = 100.0 * sum(1 for a in atrs if a < atrs[-1]) / len(atrs)
    except Exception:
        pass
    _VOL.update({"ts": now, "pct": pct})
    return pct


def _night_blocked(cfg):
    """درس الحافّة المُثبَت (2026-05-31): ليل 22-08 UTC ينزف — لا دخولات جديدة."""
    if not cfg.get("night_block", True):
        return False
    h = datetime.utcnow().hour
    return h >= 22 or h < 8


def _pre_news_blocked(cfg):
    """لا قنص قبل خبر USD أحمر بـ10 دقائق — الموجة تتسلّح بعده لا قبله."""
    try:
        d = json.load(open(EV_F, encoding="utf-8"))
        evs = d.get("events", d) if isinstance(d, dict) else d
        now = time.time(); lead = float(cfg.get("pre_news_block_min", 10)) * 60
        for e in evs or []:
            ep = float(e.get("epoch") or 0)
            if (str(e.get("currency")) in ("USD", "ALL") and str(e.get("impact")) == "High"
                    and 0 < ep - now <= lead):
                return str(e.get("title", "?"))
    except Exception:
        pass
    return None


def _veto(st, kind, reason, tag):
    now = time.time()
    if now - G["veto_ts"] < 20:          # كتم تكرار الفيتو نفسه كلّ ثانية داخل منطقة الموجة
        return
    G["veto_ts"] = now
    st["veto_count"] = int(st.get("veto_count", 0)) + 1
    _feed("veto", veto=kind, reason=reason, tag=tag)
    print(f"⛔ فيتو {kind} [{tag}]: {reason}")


def _enter(direction, sl_px, tp_px, tag, cfg, st):
    """نقطة الإرسال الوحيدة — كلّ الجدران هنا: فجوة 20ث، ≤3 مراكز، سبريد، الفيتو الذهبي، SL≠0."""
    now = time.time()
    gap_s = float(cfg.get("reentry_gap_s", 20))
    if tag.startswith("wave") and G.get("conv_hot"):  # 🔥 يقين الموجة السابق ⇒ فجوة أسرع (حطب على النار)
        gap_s = max(10.0, gap_s / 2)
    if now - G["last_entry_ts"] < gap_s:
        return False
    if len(_positions()) >= 3:                       # 🧱 يُفحص قبل الإرسال — غير قابل للتفاوض
        return False
    tick = mt5.symbol_info_tick(SYM); si = mt5.symbol_info(SYM)
    if not (tick and si):
        return False
    spread = float(tick.ask - tick.bid)
    if spread > float(cfg.get("spread_max_usd", 0.6)):   # 🧱 فيتو السبريد
        _veto(st, "spread", f"سبريد {spread:.2f}$ > {cfg.get('spread_max_usd', 0.6)}$", tag)
        return False
    px = float(tick.ask if direction == 1 else tick.bid)
    # ── 🧭 بوابة التوافق (بأمر المستخدم 2026-07-02) ──
    night = _night_blocked(cfg)
    if night and tag == "scalp":                      # 🌙 درس الليل المُثبَت: القنص الليلي ممنوع دائماً
        _veto(st, "night", "ليل 22-08 UTC — القنص ممنوع (حافّة الانضباط المثبتة)", tag)
        return False
    if tag == "scalp":
        ev = _pre_news_blocked(cfg)
        if ev:                                        # 📰 لا قنص قبل الخبر الأحمر
            _veto(st, "pre_news", f"خبر أحمر بعد <{cfg.get('pre_news_block_min', 10)}د: {ev}", tag)
            return False
        vp = _vol_regime()                            # 🌡️ فلتر نظام التقلب (موصول من اللوحة للتنفيذ)
        if vp is not None and vp >= 70.0:
            _veto(st, "vol_regime", f"نظام تقلب عالٍ 🌋 (pct {vp:.0f}) — القنص ممنوع، موجات فقط", tag)
            return False
    m5b, h1b = _tf_bias(mt5.TIMEFRAME_M5), _tf_bias(mt5.TIMEFRAME_H1)
    if m5b == -direction:                             # 🧱 مطلق: لا صفقة عكس ترند M5 أبداً
        _veto(st, "trend", f"عكس ترند M5 ({m5b:+d} ضدّ {direction:+d})", tag)
        return False
    score, parts, smc, cb, cread = _confluence(direction, px, m5b, h1b)
    if h1b == -direction and not parts.get("smc"):    # 🧱 H1 معاكس وبنية SMC لا تؤيّد ⇒ عكس الترند الكبير
        _veto(st, "trend", f"عكس ترند H1 ({h1b:+d}) بلا تأييد بنية SMC", tag)
        return False
    if cb * direction <= -2:                          # 🕯️ الشموع تصرخ بالعكس (ذيول+تسلسل+إنهاك مجتمعة)
        _veto(st, "candles", f"تشريح الشموع ضدّ الاتجاه ({cb:+d}): {cread}", tag)
        return False
    wave = tag.startswith("wave")
    if night and wave and score < 6:                  # 🌙 موجة ليلية = فقط بقرار «جداً مدروس» (أمر 2026-07-03)
        _veto(st, "night", f"موجة ليلية تحتاج توافق ≥6/8 (لديك {score}) — الحكمة قبل الحركة", tag)
        return False
    conviction = wave and score >= 6                  # 🔥 «حطب اليقين» (بأمر المستخدم): يقين ≥6/8 مع الاندفاعة
    hz = _gap_hazard(direction, px, smc)
    if hz >= 12.0:                                    # 💨 فجوة عملاقة خلفنا ⇒ أقصى يقظة لا شلل («لا تمنعه قراراتي»)
        if score < 6:
            _veto(st, "gap", f"فراغ فجوات ${hz:.1f} ≥ $12 — يلزم توافق ≥6/7 (لديك {score})", tag)
            return False
        conviction = False                            # فوق الفراغ العملاق: يُطفأ حطب المضاعفة — حجم عاديّ
        _feed("gap_caution", tag=tag, hazard=round(hz, 1), score=f"{score}/7",
              note="سُمح بأقصى توافق وحجم عاديّ فوق فجوة عملاقة")
        print(f"💨 يقظة الفجوة [{tag}]: فراغ ${hz:.1f} — دخول بتوافق {score}/7 وحجم عاديّ بلا مضاعفة")
    elif hz >= 4.0 and score < TOP_MIN_SCORE:         # 💨 فجوات معتبرة ⇒ نرفع عتبة التوافق إلى 5/7
        _veto(st, "gap", f"فجوات خلف السعر ${hz:.1f} — الحذر يرفع العتبة لـ{TOP_MIN_SCORE}/7 (لديك {score})", tag)
        return False
    gv = _golden_veto(direction, px)
    if gv:                                            # ⛔ منطقة القمّة: تُفتح فقط بتوافق قويّ + BOS — واليقين لا يكسر الفيتو أبداً
        if score >= TOP_MIN_SCORE and parts.get("bos"):   # 🧱 «شريت بالقمة»: لا مرور إلا بمؤشرات قوية يستند عليها (قاعدة راضي)
            _feed("top_override", tag=tag, score=f"{score}/7", conviction=conviction,
                  parts={k: v for k, v in parts.items() if v}, golden=gv)
            print(f"🔓 قمّة بمؤشرات قوية [{tag}]: توافق {score}/7 + BOS مؤيّد — سُمح رغم ({gv})")
        else:
            _veto(st, "golden", f"{gv} · توافق {score}/7 لا يكفي لقمّة (يلزم ≥{TOP_MIN_SCORE}+BOS)", tag)
            return False
    elif score < max(2, int(cfg.get("min_confluence", 3))):   # 🧭 دخول عاديّ: توافق ≥3/7
        _veto(st, "confluence", f"توافق ضعيف {score}/7: {[k for k, v in parts.items() if v]}", tag)
        return False
    if not sl_px or sl_px <= 0 or direction * (px - sl_px) <= 0:
        return False                                  # 🧱 لا أمر بلا SL سليم الجهة — أبداً
    G["conv_hot"] = bool(conviction)                  # 🔥 ذاكرة اليقين لفجوة الدخول التالية فقط (تلقيم أسرع، لا حجم أكبر)
    lot = float(cfg.get("lot", 0.01))                 # 🧱 حجم ثابت 0.01 — لا مضاعفة على اليقين (الفيتو الذهبيّ هو الحاكم)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": lot,
           "type": mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL, "price": px,
           "sl": round(float(sl_px), si.digits),
           "tp": round(float(tp_px), si.digits) if tp_px else 0.0,
           "deviation": 50, "magic": MAGIC, "comment": "rmimic", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        G["last_entry_ts"] = now
        _feed("entry", tag=tag, dir=("buy" if direction == 1 else "sell"), px=px,
              sl=req["sl"], tp=req["tp"], lot=req["volume"], conviction=bool(conviction),
              gap_hazard=round(hz, 1), confluence=f"{score}/8", candle_read=cread,
              parts=[k for k, v in parts.items() if v])
        print(f"✅ دخول {tag} {'شراء' if direction == 1 else 'بيع'} @ {px:.2f} "
              f"وقف {req['sl']:.2f} هدف {req['tp'] or '—'} لوت {req['volume']}")
        return True
    print(f"⚠️ فشل إرسال {tag}: retcode={getattr(r, 'retcode', None)} {getattr(r, 'comment', '')}")
    return False


def _pendings():
    return [o for o in (mt5.orders_get(symbol=SYM) or []) if o.magic == MAGIC]


_SCALP_TAGS = ("scalp", "shbmsrto", "tsoup")          # 📖 كمائن صنف-القنص: تخضع لكل فحوص القنص


def _enter_limit(direction, px_lim, sl_px, tp_px, tag, cfg, st, expire_s=300, min_score=0):
    """⚔️ خطة الحسم (إصلاح «يدخل متأخر بمكان غلط»): أمر محدَّد عند المستوى — ندخل حيث تدخل يد
    المستخدم، حين يأتي السعر إلينا، لا مطاردةً بعده. نفس بوّابات _enter كلّها تُقيَّم على سعر الأمر."""
    now = time.time()
    if len(_positions()) + len(_pendings()) >= 3:     # 🧱 المراكز + المعلّقات ≤ 3
        return False
    tick = mt5.symbol_info_tick(SYM); si = mt5.symbol_info(SYM)
    if not (tick and si):
        return False
    if float(tick.ask - tick.bid) > float(cfg.get("spread_max_usd", 0.6)):
        return False
    night = _night_blocked(cfg)
    if night and tag in _SCALP_TAGS:                  # 🌙 كمائن صنف-القنص ممنوعة ليلاً؛ كمين الموجة بالتوافق أدناه
        _veto(st, "night", "ليل 22-08 UTC — لا كمائن قنص", tag)
        return False
    if tag in _SCALP_TAGS and _pre_news_blocked(cfg):
        return False
    if tag in _SCALP_TAGS:
        vp = _vol_regime()                            # 🌡️ فلتر النظام على الكمائن أيضاً
        if vp is not None and vp >= 70.0:
            _veto(st, "vol_regime", f"نظام عالٍ 🌋 (pct {vp:.0f}) — لا كمائن قنص، موجات فقط", tag)
            return False
    m5b, h1b = _tf_bias(mt5.TIMEFRAME_M5), _tf_bias(mt5.TIMEFRAME_H1)
    if m5b == -direction:
        return False
    score, parts, smc, cb, cread = _confluence(direction, float(px_lim), m5b, h1b)
    if night and score < 6:                           # 🌙 كمين ليليّ = قرار «جداً مدروس» فقط (≥6/8)
        _veto(st, "night", f"كمين ليليّ يحتاج توافق ≥6/8 (لديك {score})", tag)
        return False
    if h1b == -direction and not parts.get("smc"):
        return False
    if cb * direction <= -2:
        _veto(st, "candles", f"الشموع ضدّ الاتجاه: {cread}", tag)
        return False
    hz = _gap_hazard(direction, float(px_lim), smc)
    if hz >= 12.0 and score < 6:
        _veto(st, "gap", f"فراغ ${hz:.1f} — يلزم ≥6/8 (لديك {score})", tag)
        return False
    if hz < 12.0 and hz >= 4.0 and score < TOP_MIN_SCORE:
        _veto(st, "gap", f"فجوات ${hz:.1f} — عتبة {TOP_MIN_SCORE}/8 (لديك {score})", tag)
        return False
    # ملاحظة: الفيتو الذهبيّ لا يمنع أمراً محدَّداً عند المستوى — نحن ننتظر الرجوع لا نشتري القمّة،
    # لكن التوافق الأدنى يبقى شرطاً
    if score < max(2, int(cfg.get("min_confluence", 3)), int(min_score)):
        _veto(st, "confluence", f"توافق {score}/8 دون العتبة ({max(2, int(cfg.get('min_confluence', 3)), int(min_score))})", tag)
        return False
    if not sl_px or direction * (float(px_lim) - float(sl_px)) <= 0:
        return False                                  # 🧱 SL سليم الجهة إجباريّ حتى للمعلّق
    typ = mt5.ORDER_TYPE_BUY_LIMIT if direction == 1 else mt5.ORDER_TYPE_SELL_LIMIT
    req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": SYM, "volume": float(cfg.get("lot", 0.01)),
           "type": typ, "price": round(float(px_lim), si.digits),
           "sl": round(float(sl_px), si.digits),
           "tp": round(float(tp_px), si.digits) if tp_px else 0.0,
           "magic": MAGIC, "comment": ("rmimic_" + tag)[:31],
           "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": int(now + expire_s)}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        G["last_entry_ts"] = now
        _feed("limit_placed", tag=tag, dir=("buy" if direction == 1 else "sell"),
              px=req["price"], sl=req["sl"], tp=req["tp"], confluence=f"{score}/8",
              candle_read=cread, expire_s=expire_s)
        print(f"📌 أمر مستوى {tag} {'شراء' if direction == 1 else 'بيع'}@{req['price']:.2f} "
              f"وقف {req['sl']:.2f} هدف {req['tp'] or '—'} (توافق {score}/8، ينتهي {expire_s}ث)")
        return True
    return False


def _pending_manage(cfg):
    """يلغي معلّقات المستوى إن انقلب الترند أو هرب السعر بعيداً (لا مطاردة حتى بالمعلّق)."""
    pend = _pendings()
    if not pend:
        return
    m5b = _tf_bias(mt5.TIMEFRAME_M5)
    tick = mt5.symbol_info_tick(SYM)
    for o in pend:
        d = 1 if o.type == mt5.ORDER_TYPE_BUY_LIMIT else -1
        far = tick and abs((tick.bid + tick.ask) / 2 - float(o.price_open)) > 6.0
        if (m5b == -d) or far:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                _feed("limit_cancel", reason=("انقلاب ترند" if m5b == -d else "السعر هرب بعيداً"),
                      ticket=int(o.ticket))
                print(f"✂️ أُلغي معلّق {o.ticket} ({'انقلاب ترند' if m5b == -d else 'سعر بعيد'})")


def _close_all(tag):
    """إغلاق كومة الماجيك كلّها بالسوق (بنك الموجة / تسطيح إجباري)."""
    for p in _positions():
        tick = mt5.symbol_info_tick(SYM)
        if not tick:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": float(p.volume),
                            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                            "position": p.ticket,
                            "price": float(tick.bid if p.type == 0 else tick.ask),
                            "sl": float(p.sl),      # موجود أصلاً على المركز — نوثّق الالتزام بالجدار
                            "deviation": 50, "magic": MAGIC, "comment": "rmimic",
                            "type_filling": mt5.ORDER_FILLING_IOC})
        ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
        _feed("exit", tag=tag, ticket=int(p.ticket), pnl=round(float(p.profit), 2), ok=ok)
        print(f"{'🏦' if tag == 'bank' else '⏱️'} إغلاق {p.ticket} ({tag}) ${p.profit:+.2f} ⇒ {ok}")


# ══════════════════ النمط أ — قنص (سكالب الارتداد مع الترند) ══════════════════
def _scalp(cfg, st):
    r5 = _closed(mt5.TIMEFRAME_M5, 140)
    if r5 is None or len(r5) < 60:
        return
    c5 = [float(x["close"]) for x in r5]
    e5, e5p = _ema(c5, 50), _ema(c5[:-3], 50)
    if e5 is None or e5p is None:
        return
    trend = 1 if (e5 > e5p and c5[-1] > e5) else (-1 if (e5 < e5p and c5[-1] < e5) else 0)
    if trend == 0:                                    # لا ترند واضح على M5 ⇒ لا قنص
        return
    r1 = _closed(mt5.TIMEFRAME_M1, 90)
    if r1 is None or len(r1) < 60:
        return
    if int(r1[-1]["time"]) == G["last_sig_bar"]:      # تقييم واحد لكلّ شمعة مغلقة
        return
    G["last_sig_bar"] = int(r1[-1]["time"])
    e50 = _ema([float(x["close"]) for x in r1], 50); atr = _atr(r1)
    if e50 is None or not atr:
        return
    if _pendings():                                   # كمين واحد قائم يكفي
        return
    tick = mt5.symbol_info_tick(SYM)
    if not tick:
        return
    # ⚔️ إصلاح «يدخل متأخر بمكان غلط»: لا ننتظر اللمسة والتأكيد (متأخّر شمعتين) — نضع الكمين
    # عند EMA50 نفسه وننتظر السعر يرجع إلينا، مثل يد المستخدم عند المستوى.
    mid = (float(tick.ask) + float(tick.bid)) / 2.0
    dist_above = trend * (mid - e50)
    if not (0.3 <= dist_above <= 4.0):                # لصيقٌ جداً أو ممطوطٌ جداً ⇒ لا كمين
        return
    lim = e50 + trend * 0.05
    sl_d = max(float(cfg.get("sl_min_usd", 1.8)),
               min(float(cfg.get("sl_max_usd", 3.5)), 0.6 * atr + 0.2))
    # 🎯 إصلاح 2026-07-03 (نقد المستخدم «الـTP قليل»): الهدف = مضاعف الوقف (نسبة R حقيقية) لا رقم ثابت.
    # كان $2 بوقف $2.6 = 0.77R (أصغر من الوقف — خطأ رياضيّ)؛ الآن 2R مسقوفٌ بـ$8 كي يتنفّس مع ATR الذهب.
    tp_d = min(float(cfg.get("tp_r", 2.0)) * sl_d, float(cfg.get("tp_r_max_usd", 8.0)))
    _enter_limit(trend, lim, lim - trend * sl_d, lim + trend * tp_d, "scalp", cfg, st, expire_s=300)


# ══════════ 📖 إعدادا Wade FX (فصفصة 2026-07-03 — المرجع docs/wade_fx_reference.md) ══════════
_WADE = {"bar": 0, "pdh": None, "pdl": None, "dopen": None, "day": "", "pdl_done": False, "pdh_done": False}


def _wade_day_levels():
    """PDH/PDL من شمعة أمس + افتتاح اليوم — تُحسب مرة كل يوم."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _WADE["day"] != today:
        try:
            d1p = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 1, 1)
            d1c = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 0, 1)
            if d1p is not None and len(d1p) and d1c is not None and len(d1c):
                _WADE.update({"pdh": float(d1p[0]["high"]), "pdl": float(d1p[0]["low"]),
                              "dopen": float(d1c[0]["open"]), "day": today,
                              "pdl_done": False, "pdh_done": False})
        except Exception:
            pass
    return _WADE


def _in_session_window():
    """نوافذ الكتاب: افتتاح لندن 07-10 UTC وافتتاح نيويورك 12-15 UTC."""
    h = datetime.utcnow().hour
    return (7 <= h < 10) or (12 <= h < 15)


def _bars_ago_m5(sym_d, idx):
    """عمر عنصر SMC بشموع M5 عبر candles_m5_first_idx (محاذاة فهارس النبض)."""
    try:
        first = int(sym_d.get("candles_m5_first_idx") or 0)
        n = len(sym_d.get("candles_m5") or [])
        return (first + n - 1) - int(idx)
    except Exception:
        return 10 ** 9


def _wade_setups(cfg, st):
    """📖 A: SH+BMS+RTO (كنس ثم كسر بنية ثم كمين عودة للأوردر بلوك) · B: Turtle Soup على PDH/PDL.
    كلاهما كمائن limit عبر كل بوابات _enter_limit — لا تخفيف، وكل إشارة تُسجَّل للمحاسبة."""
    r1 = _closed(mt5.TIMEFRAME_M1, 20)
    if r1 is None or len(r1) < 15:
        return
    bt = int(r1[-1]["time"])
    if bt == _WADE["bar"]:                            # تقييم واحد لكل شمعة M1 مغلقة
        return
    _WADE["bar"] = bt
    atr = _atr(r1) or 0.5
    tick = mt5.symbol_info_tick(SYM)
    if not tick:
        return
    mid = (float(tick.ask) + float(tick.bid)) / 2.0
    pu = _read_fresh(PULSE_F, 120)
    sym_d = ((pu or {}).get("symbols") or {}).get(SYM) or {}
    smc = sym_d.get("smc") or {}
    pend_tags = {str(o.comment or "") for o in _pendings()}
    lv = _wade_day_levels()
    in_win = _in_session_window()

    # ── A: SH+BMS+RTO — «الإعداد الرئيسي» في الكتاب (p087-092) ──
    if "rmimic_shbmsrto" not in pend_tags:
        try:
            sweeps = smc.get("sweeps") or []
            bos = smc.get("bos") or []
            obs = smc.get("ob") or []
            for d, side in ((1, "low"), (-1, "high")):
                sw = next((s for s in reversed(sweeps)
                           if str(s.get("side")) == side and _bars_ago_m5(sym_d, s.get("idx", -9)) <= 12), None)
                if not sw or not bos:
                    continue
                b = bos[-1]
                if int(b.get("dir", 0)) != d or int(b.get("idx", -1)) <= int(sw.get("idx", 10 ** 9)):
                    continue                          # الكسر يجب أن يأتي بعد الكنس — ترتيب الكتاب الإلزامي
                ob = next((o for o in reversed(obs)
                           if int(o.get("dir", 0)) == d and not o.get("mitigated")
                           and int(o.get("idx", -9)) >= int(sw["idx"]) - 2), None)
                if not ob:
                    continue
                edge = float(ob["hi"]) if d == 1 else float(ob["lo"])
                if not (0.3 <= d * (mid - edge) <= 6.0):
                    continue                          # المنطقة خلفنا وعلى بُعد معقول — ننتظرها لا نطاردها
                px_lim = edge
                struct_sl = (min(float(ob["lo"]), float(sw.get("price", ob["lo"]))) if d == 1
                             else max(float(ob["hi"]), float(sw.get("price", ob["hi"]))))
                sl_px = struct_sl - d * max(0.15, 0.1 * atr)
                sl_d = abs(px_lim - sl_px)
                if sl_d > float(cfg.get("sl_max_usd", 3.5)) or sl_d < 0.4:
                    continue                          # وقف هيكليّ (تحت قاع الكنس) أو لا صفقة — لا تضييق
                if sl_d < float(cfg.get("sl_min_usd", 1.8)):
                    sl_px = px_lim - d * float(cfg.get("sl_min_usd", 1.8))
                tgt = float(b.get("price", 0) or 0)
                if not tgt:
                    continue
                cap = float(cfg.get("tp_r_max_usd", 8.0))   # 🎯 هدف Wade هيكليّ (قمة الكسر) — سقفٌ أوسع
                tp_px = min(tgt, px_lim + cap) if d == 1 else max(tgt, px_lim - cap)
                if d * (tp_px - px_lim) < 1.2:
                    continue                          # هدف لا يغطي الكلفة ⇒ تخطَّ
                if _enter_limit(d, px_lim, sl_px, tp_px, "shbmsrto", cfg, st,
                                expire_s=900, min_score=(0 if in_win else 5)):
                    _feed("wade_signal", setup="SH+BMS+RTO", dir=("buy" if d == 1 else "sell"),
                          sweep=round(float(sw.get("price", 0)), 2), bos=round(tgt, 2),
                          ob=[round(float(ob["lo"]), 2), round(float(ob["hi"]), 2)], in_window=in_win)
                    print(f"📖 إشارة SH+BMS+RTO {'شراء' if d == 1 else 'بيع'}: كنس {sw.get('price')}"
                          f" ⇒ كسر {tgt} ⇒ كمين OB @{px_lim:.2f}")
                break
        except Exception as e:
            print(f"wade A err: {type(e).__name__}: {e}")

    # ── B: Turtle Soup على PDH/PDL داخل نوافذ الافتتاح (p082-086) ──
    # ⚠️ مُطفأ افتراضياً 2026-07-03: الاختبار التاريخي 0/11 خسائر t=−13.6 (نظام ترند — الكنس يستمر
    # لا يرتد). الكتاب يفترض سوقاً عرضياً؛ يُعاد فحصه إن تحوّل النظام (tsoup_enabled في الإعدادات).
    if cfg.get("tsoup_enabled", False) and in_win and "rmimic_tsoup" not in pend_tags:
        try:
            for d, lvl_key, done_key in ((1, "pdl", "pdl_done"), (-1, "pdh", "pdh_done")):
                if lv.get(done_key) or not lv.get(lvl_key):
                    continue
                L = float(lv[lvl_key])
                lows = [float(x["low"]) for x in r1[-6:]]
                highs = [float(x["high"]) for x in r1[-6:]]
                lastc = float(r1[-1]["close"])
                if d == 1:
                    pierced = min(lows) < L and lastc > L
                    depth = L - min(lows); ext = min(lows)
                else:
                    pierced = max(highs) > L and lastc < L
                    depth = max(highs) - L; ext = max(highs)
                if not pierced or not (0.10 * atr <= depth <= 1.2 * atr):
                    continue                          # غرزٌ أعمق من 1.2×ATR = كسر حقيقيّ محتمل — تخطَّ
                tr = int(smc.get("trend", 0) or 0)
                if tr == -d:
                    continue                          # لا نقاتل اتجاه SMC الصريح
                bos = smc.get("bos") or []
                if bos and int(bos[-1].get("dir", 0)) == -d and _bars_ago_m5(sym_d, bos[-1].get("idx", -9)) <= 3:
                    continue                          # كسرٌ معاكس طازج ⇒ الكنس قد يكون بداية انهيار
                px_lim = L + d * 0.05
                if d * (mid - px_lim) > 4.0:
                    continue                          # السعر هرب — فات الكمين، لا مطاردة
                sl_px = ext - d * max(0.15, 0.1 * atr)
                sl_d = abs(px_lim - sl_px)
                if sl_d > float(cfg.get("sl_max_usd", 3.5)):
                    continue
                if sl_d < float(cfg.get("sl_min_usd", 1.8)):
                    sl_px = px_lim - d * float(cfg.get("sl_min_usd", 1.8))
                do = float(lv.get("dopen") or 0)
                tp_px = do if (do and d * (do - px_lim) >= 1.2) else px_lim + d * 3.0
                if d * (tp_px - px_lim) > 3.0:
                    tp_px = px_lim + d * 3.0
                if _enter_limit(d, px_lim, sl_px, tp_px, "tsoup", cfg, st, expire_s=600):
                    _WADE[done_key] = True            # مستوى واحد = محاولة واحدة يومياً (محروق بعدها)
                    _feed("wade_signal", setup="TurtleSoup", dir=("buy" if d == 1 else "sell"),
                          level=round(L, 2), depth=round(depth, 2), depth_atr=round(depth / atr, 2))
                    print(f"📖 إشارة Turtle Soup {'شراء' if d == 1 else 'بيع'}: كنس {lvl_key.upper()}"
                          f" {L:.2f} بعمق {depth:.2f}$ ⇒ كمين @{px_lim:.2f}")
        except Exception as e:
            print(f"wade B err: {type(e).__name__}: {e}")


# ══════════════════ النمط ب — ركوب الموجة (خبر/اندفاعة + بنك) ══════════════════
def _wave_reset():
    return {"armed": False, "src": "", "dir": 0, "hi": 0.0, "lo": 0.0, "leg": 0.0, "until": 0.0,
            "waves": 0, "last_entry": 0.0, "entry_px": 0.0, "fav": 0.0, "ext": 0.0, "bar": 0}


def _wave_try_arm(cfg, W, nw, st):
    imp = _impulse(cfg)
    if imp is None or imp["t"] == G["last_imp_bar"]:  # لا نُعيد التسليح على الاندفاعة نفسها
        return
    G["last_imp_bar"] = imp["t"]
    tick = mt5.symbol_info_tick(SYM)
    ref = (float(tick.bid if imp["dir"] == 1 else tick.ask) if tick
           else (imp["hi"] if imp["dir"] == 1 else imp["lo"]))
    W.update(_wave_reset())
    W.update({"armed": True, "src": ("news:" + nw["title"]) if nw else "impulse",
              "dir": imp["dir"], "hi": imp["hi"], "lo": imp["lo"], "leg": imp["hi"] - imp["lo"],
              "until": time.time() + float(cfg.get("event_window_min", 15)) * 60, "ext": ref})
    _feed("wave_armed", src=W["src"], dir=("buy" if imp["dir"] == 1 else "sell"),
          leg=round(W["leg"], 2), hi=round(W["hi"], 2), lo=round(W["lo"], 2))
    print(f"🌊 موجة مسلّحة ({W['src']}) {'صعود' if imp['dir'] == 1 else 'هبوط'} — رجل {W['leg']:.2f}$")
    d = imp["dir"]                                    # ⚔️ كمين الموجة: محدَّد عند ارتداد 38% فوراً — لا مطاردة
    lim = (W["hi"] - 0.38 * W["leg"]) if d == 1 else (W["lo"] + 0.38 * W["leg"])
    sl_d = min(float(cfg.get("wave_risk_max_usd", 6.0)), max(1.2, 0.50 * W["leg"]))
    _enter_limit(d, lim, lim - d * sl_d, 0.0, "wave1L1", cfg, st,
                 expire_s=int(float(cfg.get("event_window_min", 15)) * 60))


def _wave_manage(cfg, W, st, frozen):
    now = time.time()
    tick = mt5.symbol_info_tick(SYM)
    if not tick:
        return
    d = W["dir"]; poss = _positions()
    ref = float(tick.bid if d == 1 else tick.ask)
    W["ext"] = min(W["ext"], ref) if d == 1 else max(W["ext"], ref)   # أقصى الارتداد (للوقف)
    if W["entry_px"]:
        W["fav"] = max(W["fav"], d * (ref - W["entry_px"]))           # للحكم على «ارتداد جديد»
    r = _closed(mt5.TIMEFRAME_M1, 40)
    if r is None or len(r) < 12:
        return
    e9 = _ema([float(x["close"]) for x in r], 9)
    bt = int(r[-1]["time"])
    if bt != W["bar"] and e9 is not None:             # حكم البنك مرّة واحدة لكلّ شمعة مغلقة جديدة
        W["bar"] = bt
        b, p = r[-1], r[-2]
        body_b = float(b["close"] - b["open"]); body_p = float(p["close"] - p["open"])
        bank = None
        if d * (float(b["close"]) - e9) < 0:
            bank = f"إغلاق M1 خلف EMA9 عكس الموجة ({float(b['close']):.2f} ضدّ {e9:.2f})"
        elif body_b * d < 0 and abs(body_b) > 0.6 * max(abs(body_p), 0.01):
            bank = f"ابتلاع معاكس {abs(body_b):.2f}$ > 60% من جسم السابقة {abs(body_p):.2f}$"
        if bank and poss:                             # 🏦 توقيع المستخدم: اقبض الكومة كلّها
            tot = sum(float(x.profit) for x in poss)
            _close_all("bank")
            G["last_entry_ts"] = 0.0                  # 🔫 إعادة تلقيم فور بنك الموجة
            W["waves"] += 1; W["fav"] = 0.0
            _feed("bank", reason=bank, pnl=round(tot, 2), waves=W["waves"])
            print(f"🏦 بنك الموجة #{W['waves']}: {bank} — مقبوض ${tot:+.2f}")
            if W["waves"] >= int(cfg.get("wave_max_per_window", 3)):
                print("🏁 اكتمل حدّ الموجات للنافذة — نزع التسليح")
                W.update(_wave_reset())
            return
    if poss and W["last_entry"] and now - W["last_entry"] > float(cfg.get("wave_force_flat_min", 15)) * 60:
        _close_all("force_flat")                      # ⏱️ تسطيح إجباري بعد 15د من آخر دخول
        _feed("force_flat", after_min=cfg.get("wave_force_flat_min", 15))
        W.update(_wave_reset())
        return
    if not poss and now > W["until"]:                 # انتهت النافذة بلا مراكز ⇒ عودة للقنص
        W.update(_wave_reset())
        return
    if frozen or e9 is None:
        return
    if len(poss) >= min(3, int(cfg.get("wave_stack_max", 3))):
        return
    if W["entry_px"] and W["fav"] < 0.30 * W["leg"]:  # الطبقة الجديدة تشترط ارتداداً جديداً
        return
    rp = cfg.get("wave_retrace_pct", [30, 50])
    f_lo, f_hi = float(rp[0]) / 100.0, float(rp[1]) / 100.0
    entry_px = float(tick.ask if d == 1 else tick.bid)
    if d == 1:
        zone_lo, zone_hi = W["hi"] - f_hi * W["leg"], W["hi"] - f_lo * W["leg"]
    else:
        zone_lo, zone_hi = W["lo"] + f_lo * W["leg"], W["lo"] + f_hi * W["leg"]
    in_zone = zone_lo <= entry_px <= zone_hi
    touch_e9 = d * (entry_px - e9) <= 0.10            # لمسة EMA9 من جهة الموجة
    if not (in_zone or touch_e9):
        return
    sl = W["ext"] - d * 0.30                          # خلف أقصى الارتداد + هامش
    if abs(entry_px - sl) > float(cfg.get("wave_risk_max_usd", 6.0)):
        sl = entry_px - d * float(cfg.get("wave_risk_max_usd", 6.0))
    if abs(entry_px - sl) < 1.0:
        sl = entry_px - d * 1.0                       # حدّ أدنى يقي من قنص السبريد
    if _enter(d, sl, 0.0, f"wave{W['waves'] + 1}L{len(poss) + 1}", cfg, st):
        W["last_entry"] = now; W["entry_px"] = entry_px; W["fav"] = 0.0


def main():
    ok = False
    for i in range(6):                                # تهيئة واحدة × 6 محاولات — لا init بالحلقة
        if mt5.initialize():
            ok = True; break
        print(f"⏳ mt5.initialize فشل ({i + 1}/6) — انتظار 10ث"); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5 بعد 6 محاولات — خروج"); return
    try:
        mt5.symbol_select(SYM, True)
    except Exception:
        pass
    st = _st_load()
    W = _wave_reset()
    print(f"🪞 محاكي راضي بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — قنص+موجة، ماجيك {MAGIC}، "
          f"لوت 0.01، ديمو فقط. الفيتو الذهبيّ «شريت بالقمة» مُدمج.")
    while True:
        try:
            cfg = _cfg()
            if os.path.exists(KILL1) or os.path.exists(KILL2):    # 🧱 مفتاحا القتل كلّ دورة
                _status(st, "killed", G.get("pnl", 0.0), force=True)   # 💓 نبضة أثناء القتل — لا يُترك الملفّ بائتاً فيقتله الوصيّ تكراراً
                time.sleep(10); continue
            if not cfg.get("enabled", True):
                _status(st, "disabled", G.get("pnl", 0.0), force=True)  # 💓 نبضة أثناء التعطيل (نمط brain_trader الخامل النظيف)
                time.sleep(10); continue
            acct = mt5.account_info()
            srv = str(getattr(acct, "server", "") or "")
            if not acct or not ("Trial" in srv or "Demo" in srv):  # 🧱 ديمو فقط — أبداً على حقيقي
                print(f"⛔ الخادم '{srv}' ليس Trial/Demo — رفض التداول"); time.sleep(30); continue
            today = datetime.now().strftime("%Y-%m-%d")
            if st.get("day") != today:                             # يوم جديد ⇒ تصفير العدّادات
                st.update({"day": today, "veto_count": 0, "frozen_until": 0.0})
                _status(st, "scalp", 0.0, force=True)
            pnl = _pnl_today()
            frozen = time.time() < float(st.get("frozen_until", 0) or 0)
            if not frozen and pnl <= -float(cfg.get("daily_loss_pct", 3.0)) / 100.0 * float(acct.equity):
                st["frozen_until"] = _next_midnight(); frozen = True   # 🧊 3% يوميّاً ⇒ تجميد
                _feed("freeze", pnl=round(pnl, 2), equity=round(float(acct.equity), 2))
                _status(st, "frozen", pnl, force=True)
                print(f"🧊 تجميد حتى منتصف الليل: خسارة اليوم ${pnl:+.2f} بلغت "
                      f"{cfg.get('daily_loss_pct', 3.0)}% من الحقوق {acct.equity:.0f}")
            poss_now = _positions()                    # 💰🔫 قفل الـ5$ (أمر المستخدم): الكومة تلمس +5$ ⇒ حصاد فوريّ
            flt_now = sum(float(p.profit) for p in poss_now)
            if poss_now and flt_now >= float(cfg.get("bank_usd", 5.0)):
                _close_all("bank5")
                _feed("bank5", pnl=round(flt_now, 2), positions=len(poss_now))
                G["last_entry_ts"] = 0.0               # إعادة تلقيم الرشّاش — الدخول التالي فوريّ
                print(f"💰 قفل الـ5$: حُصدت {len(poss_now)} صفقة بمجموع ${flt_now:+.2f} — الرشّاش مُلقَّم")
            _pending_manage(cfg)                       # ✂️ إدارة كمائن المستوى (إلغاء عند انقلاب/هروب)
            nw = _news_window(cfg)
            if not frozen and not W["armed"]:          # 🧊 لا تسليح موجة جديدة أثناء التجميد — يُدار القائم فقط
                _wave_try_arm(cfg, W, nw, st)
            if W["armed"]:
                _wave_manage(cfg, W, st, frozen)      # الإدارة (بنك/تسطيح) تعمل حتى أثناء التجميد
            elif not frozen:
                _scalp(cfg, st)
                _wade_setups(cfg, st)                 # 📖 إعدادا Wade FX (كمائن SH+BMS+RTO وTurtle Soup)
            _status(st, "frozen" if frozen else ("wave" if W["armed"] else "scalp"), pnl)
            time.sleep(0.5 if (W["armed"] or nw) else 1)           # ⚡ 2026-07-03: نصف ثانية بالموجة / ثانية دائماً
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            try:
                _status(st, "err", G.get("pnl", 0.0), force=True)   # 💓 نبضة حتى عند الخطأ — يمنع الوصيّ من قتل النبض البائت
            except Exception:
                pass
            time.sleep(5)


if __name__ == "__main__":
    main()
