# -*- coding: utf-8 -*-
"""brain_trader.py — 🥷 R CORE «النسخة المنضبطة من يد راضي» (ماجيك 20260706 · ذهب فقط · ديمو فقط).

التحوّل 2026-07-06: تقاعد رشّاش الـ17 عملة (ماجيك 20260704، −$61/3أيام — سجلّه محفوظ له) ووُلد R CORE:
قنّاص ذهبٍ واحد يدمج DNA الرابحين المقيسين — زناد الحارس (20260701) + بنية الديسك + قواعد راضي الثماني
(radhi_mimic 20260703). الدخول = زنادٌ ∧ لا فيتو:
  أ) زناد الحارس: تنبيه مستوياتٍ طازج (≤120ث، توافق ≥2) من gold_sentinel_feed.jsonl يعطي الاتجاه.
  ب) زناد البنية: قناعة المخ الواحد ≥0.55 + اتفاق ≥3 والسعر على ارتدادٍ (ضمن 1.0×ATR من EMA50-M1).
  ج) زناد الزخم: ممتدّ لكنّ الاندفاعة حيّة (قناعة ≥0.60 + 3 شموع + توسّعٌ بلا إنهاك) ⇒ ركوبٌ بتريلينغ.
  هـ) زناد الاصطفاف الخماسيّ (suite_linreg_st): LinReg+RSI+VWAP+SuperTrend+بنية متوافقة وانقلاب ST
     طازج (≤8 شموع) — استيرادٌ دفاعيّ (غياب الوحدة ⇒ الزناد معطَّل بصمت) ويمرّ على كامل الفيتوهات.
الفيتوهات (أيّها صدق ⇒ امتناعٌ مسجَّل بسببه ليتعلّم النظام لماذا امتنع):
  ⛔ الفيتو الذهبيّ «شريت بالقمة» (مُدمج غير قابل للضبط، بمرآتيه: لا شراء قمّة ممطوطة ولا بيع قاع هلع):
  مدى شمعة M1 >5$ أو السعر >5$ أبعد من EMA50-M1 باتجاه الصفقة · عكس ترند H1 (ميل EMA50) · ليل 22-08
  UTC · قبل خبرٍ أحمر بـ10د · سبريد >0.4×ATR · تبريد الانتقام (خسارتان/12د ⇒ 15د) · تجميد اليوم (−6%)
  · ≥3 مراكز · مركزٌ معاكس على الرمز نفسه (لا تحوّط ذاتيّ) · فجوة إعادة دخول 20ث · المجلس فيتو-فقط
  (قِيس تنسيقاً لا حافّة: يمنع فقط إن أجمع ≥75% ضدّنا — لا يشترط موافقته).
الخروج (توقيع الرابحين): هدف 2R هيكليّ · تعادلٌ مبكّر عند ربح ≥0.5R (الوقف⇐الدخول مرّة واحدة) ·
  تريلينغ الزخم 0.8×ATR بهدف 4R · تسوية إجباريّة بعد 90د.
الحجم: سُلّم الثقة (أرضية 0.5%) بسقفٍ صلب 2% — order_calc_profit الرسميّ + وقف 0.8×ATR (أرضية تضييق 0.5).
جدران ثابتة: SL≠0 لكلّ أمر · Trial/Demo فقط · مفتاحا القتل · كتابة ذرّيّة · نبض خامل عند التعطيل."""
import os, sys, json, time, math
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "brain_trader.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("brain_trader")
except SystemExit:
    raise
except Exception:
    pass

MAGIC = 20260706                                      # 🥷 R CORE — سجلّ قياسٍ نظيف (20260704 يخصّ الرشّاش المتقاعد)
UNI_F = os.path.join(_RN, "unified_brain.json")
CFG_F = os.path.join(_RN, "brain_trader_config.json")
STATUS_F = os.path.join(_RN, "brain_trader_status.json")
FEED_F = os.path.join(_RN, "brain_trader_feed.jsonl")
SENT_F = os.path.join(_RN, "gold_sentinel_feed.jsonl")
EV_F = os.path.join(_RN, "news_events.json")
GOV_F = os.path.join(_RN, "engine_governance.json")   # 🤝 حوكمة الأسطول (portfolio_maestro يكتب mults[magic])
SENSE_F = os.path.join(_RN, "market_sense.json")       # 👁️ حسّ السوق (adaptive_sense يكتبه: spread/momentum/vol)
CONF_F = os.path.join(_RN, "confidence.json")          # 🎯 ثقةٌ مكتسبة من الصفقات المغلقة الحقيقيّة فقط
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

# ⛔ الفيتو الذهبيّ — ثوابت مُدمجة عمداً (ليست في الإعدادات كي لا تُعطَّل أبداً) — درس «شريت بالقمة»
GOLDEN_BAR_USD = 5.0     # مدى شمعة M1 (جارية أو آخر مغلقة) > 5$ ⇒ لا دخول
GOLDEN_EXT_USD = 5.0     # السعر أبعد من 5$ عن EMA50-M1 باتجاه الصفقة ⇒ لا دخول (شراءً كان أم بيعاً)
# 🛡️ خريطة تنبيهات الحارس ⇒ اتجاه (مفاتيح gold_sentinel_feed.jsonl الفعليّة كما تُكتب)
_SENT_DIR = {"ارتداد-شراء": 1, "كسر-صعوديّ": 1, "رفض-بيع": -1, "كسر-هبوطيّ": -1}

try:
    import revenge_logic                               # 🗡️ ثأر القنّاص المنضبط (وحدة نقيّة ذات اختبار ذاتيّ)
except Exception:
    revenge_logic = None                               # فشل الاستيراد ⇒ الثأر معطَّل والمحرّك يعمل كالمعتاد

try:
    import suite_linreg_st                             # 🎼 حزمة Pine الخماسيّة (LinReg+RSI+VWAP+ST+بنية)
except Exception:
    suite_linreg_st = None                             # فشل الاستيراد ⇒ زناد الاصطفاف (هـ) معطَّل بصمت

G = {"last_entry": {}, "status_ts": 0.0, "frozen_until": 0.0, "day": "", "risk_pct": 0.5,
     "ladder_ts": 0.0, "sent_used": 0.0, "veto_ts": {},
     "revenge": (revenge_logic.new_state() if revenge_logic else None),   # 🗡️ حالة الثأر (تُصفَّر يوميّاً)
     "open_meta": {}, "rev_seen": set(), "rev_scan_ts": 0.0,              # {ticket: {sym,dir,entry,sl,comment}}
     "suite_cache": {}}                                                   # 🎼 {sym: (ts, نتيجة evaluate)} ~5ث


def _rev_day():
    """يوم الثأر (نفس يوم المحرّك) — يسقط على تاريخ اليوم إن لم يُضبط بعد."""
    return G.get("day") or datetime.now().strftime("%Y-%m-%d")

try:
    import perf_ladder                                 # 🎚️ سُلّم الثقة المكتسبة (تحجيم المخاطرة بالأداء المقيس)
except Exception:
    perf_ladder = None


def _cfg():
    d = {"enabled": True, "mode": "r_core", "symbols": ["XAUUSDm"], "conviction_thr": 0.55, "agree_min": 3,
         "max_positions": 3, "sl_atr": 0.8, "min_sl_atr": 0.5, "tp_r": 2.0, "be_at_r": 0.5,
         "momentum_mode": True, "momentum_conv_thr": 0.6, "momentum_tp_r": 4.0, "trail_atr": 0.8,
         "risk_max_pct": 2.0, "hard_ceiling_pct": 2.0, "base_risk_floor_pct": 0.5,
         "daily_loss_pct": 6.0, "spread_atr_max": 0.4, "extend_atr_max": 1.0,
         "hold_max_min": 90, "reentry_gap_s": 20, "night_block": True, "pre_news_block_min": 10,
         "council_veto_pct": 75.0, "sentinel_max_age_s": 120, "sentinel_min_score": 2,
         "collective_mode": True,   # 🤝 لا تجمّد على خسارة اليوم — واصل بحجمٍ مخنوقٍ عبر حوكمة الأسطول
         # 👁️🎯 التكيّف الناعم (adaptive_sense): يُعدّل داخل الحدود الآمنة فقط — لا يرفع فيتو ولا يتجاوز سقفاً.
         # adaptive_mode=false ⇒ السلوك القديم بالحرف. الصدق: هذه ليست تنبؤاً — إنّها ضبطُ النفس للظروف
         # وثقةٌ مقيسةٌ من الصفقات المغلقة الحقيقيّة فقط (لا حافّة مزعومة، لا ثقةٌ مزيّفة).
         "adaptive_mode": True, "conf_lo": 0.5, "conf_hi": 1.3, "sense_max_age_s": 120,
         "spread_sense_k": 0.5, "spread_atr_abs_cap": 0.6, "entry_sense_nudge": 0.05,
         "entry_thr_floor": 0.45,
         "suite_trigger": True, "suite_fresh_bars": 8,
         "loop_s": 0.3, "cool_losses": 2, "cool_win_min": 12, "cool_min": 15,
         "revenge": {"enabled": True, "window_min": 30, "max_per_day": 3,
                     "hunt_min_score": 3, "hunt_size_mult": 0.5},
         "_note": "🥷 R CORE — النسخة المنضبطة من يد راضي: زناد الحارس (مستويات) + بنية الديسك + "
                  "فيتوهات القواعد الثماني، ذهب فقط، مخاطرة تُكتسب بالسُلّم (0.5%→2%). ماجيك 20260706. ديمو فقط. "
                  "🗡️ + ثأر القنّاص (revenge_logic): إعادة دخول صيد-الستوب بنفس الحجم والاتجاه، مطاردة A+ "
                  "بنصف الحجم أثناء التبريد، قفل تصعيد عند الفشل — لا مضاعفة ولا انعكاس أبداً."}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _gov_mult():
    """🤝 مضاعف لوت هذا الماجيك من حوكمة الأسطول (portfolio_maestro يكتب mults[str(magic)]) —
    fail-soft إلى 1.0 (غياب الملف/المفتاح لا يمسّ الحلقة). يقبل عدّة أشكالٍ للسكيما احتياطاً."""
    try:
        g = json.load(open(GOV_F, encoding="utf-8"))
        k = str(MAGIC)
        for src in (g.get("mults"), g.get("magics"), g):
            if isinstance(src, dict) and k in src:
                v = src[k]
                v = v.get("mult", v.get("mults")) if isinstance(v, dict) else v
                v = float(v)
                if v >= 0:
                    return min(1.0, v)      # الحوكمة تخنق فقط — لا تكبّر لوت المحرّك أبداً
    except Exception:
        pass
    return 1.0


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        return lo
    return lo if v < lo else (hi if v > hi else v)


def _sense_read(cfg):
    """👁️ حسّ السوق (market_sense.json من adaptive_sense) — قراءة دفاعيّة fail-soft إلى المحايد:
    غياب الملفّ/قِدمه/أيّ خللٍ ⇒ كلّ الحواسّ 0.5 (محايدة = بلا تعديل). لا يمسّ الحلقة أبداً.
    spread_sense∈[0,1] (1=ضيّق مريح، 0=واسع)، momentum_sense∈[-1,1] (اتجاه+قوّة)، vol_sense∈[0,1] (صحّة التذبذب)."""
    neutral = {"spread": 0.5, "momentum": 0.0, "vol": 0.5, "fresh": False}
    if not cfg.get("adaptive_mode", True):
        return neutral
    try:
        s = json.load(open(SENSE_F, encoding="utf-8"))
        if not isinstance(s, dict):
            return neutral
        if time.time() - float(s.get("ts", 0) or 0) > float(cfg.get("sense_max_age_s", 120)):
            return neutral                                # قديمٌ ⇒ محايد (لا نتصرّف على حسٍّ بائت)
        return {"spread": _clamp(s.get("spread_sense", 0.5), 0.0, 1.0),
                "momentum": _clamp(s.get("momentum_sense", 0.0), -1.0, 1.0),
                "vol": _clamp(s.get("vol_sense", 0.5), 0.0, 1.0), "fresh": True}
    except Exception:
        return neutral


def _conf_modifier(cfg):
    """🎯 مُعامل الثقة لماجيكنا (confidence.json[magic].modifier، مُقاسٌ من الصفقات المغلقة الحقيقيّة
    فقط بواسطة adaptive_sense) — fail-soft إلى 1.0. يُقصّ صلباً إلى [conf_lo, conf_hi] (افتراضيّاً
    [0.5,1.3]) كطبقة أمانٍ ثانية حتى لو كتب المصدر قيمةً شاذّة. غياب الملف/المفتاح ⇒ 1.0 (بلا تعديل)."""
    if not cfg.get("adaptive_mode", True):
        return 1.0
    lo = float(cfg.get("conf_lo", 0.5)); hi = float(cfg.get("conf_hi", 1.3))
    try:
        c = json.load(open(CONF_F, encoding="utf-8"))
        k = str(MAGIC)
        src = c.get(k)
        if src is None and isinstance(c.get("magics"), dict):
            src = c["magics"].get(k)
        if isinstance(src, dict):
            m = src.get("modifier", src.get("mult", 1.0))
        elif src is not None:
            m = src
        else:
            return 1.0
        return _clamp(m, lo, hi)
    except Exception:
        return 1.0


def _feed(kind, **kw):
    try:
        kw.update({"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
                   "kind": kind, "engine": "R CORE"})
        with open(FEED_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _veto(sym, kind, reason, **kw):
    """⛔ يسجّل الفيتو بسببه (ليتعلّم النظام لماذا امتنع) — بكتمٍ 20ث لكلّ (رمز، نوع) كي لا يفيض السجلّ."""
    now = time.time()
    vt = G.setdefault("veto_ts", {})
    if now - vt.get((sym, kind), 0) < 20:
        return
    vt[(sym, kind)] = now
    _feed("veto", sym=sym, veto=kind, reason=reason, **kw)
    print(f"⛔ R CORE فيتو {kind} [{sym}]: {reason}")


def _ema(vals, n):
    if vals is None or len(vals) < n:
        return None
    k = 2.0 / (n + 1); e = sum(vals[:n]) / float(n)
    for v in vals[n:]:
        e += k * (v - e)
    return e


def _ema_m1(sym, n=50):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n + 30)
    if r is None or len(r) < n:
        return None
    return _ema([float(x["close"]) for x in r], n)


def _atr(sym, tf=None, n=14):
    tf = tf or mt5.TIMEFRAME_M5
    r = mt5.copy_rates_from_pos(sym, tf, 1, n + 1)
    if r is None or len(r) < n + 1:
        return None
    trs = [max(float(r[i]["high"] - r[i]["low"]), abs(float(r[i]["high"] - r[i - 1]["close"])),
               abs(float(r[i]["low"] - r[i - 1]["close"]))) for i in range(1, len(r))]
    return sum(trs[-n:]) / n


def _tf_bias(sym, tf, bars=140):
    """اتجاه إطارٍ زمنيّ (منطق المحاكي الحرفيّ): ميل EMA50 + جهة السعر ⇒ 1/-1/0 — لا اعتماد خارجيّ."""
    r = mt5.copy_rates_from_pos(sym, tf, 1, bars)
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


def _positions():
    return [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]


def _pnl_today():
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ep = day0.timestamp(); r = 0.0
    try:
        for d in (mt5.history_deals_get(day0 - timedelta(hours=12), datetime.now() + timedelta(hours=12)) or []):
            if d.magic == MAGIC and d.entry == 1 and float(getattr(d, "time", 0)) >= ep:
                r += float(d.profit) + float(d.commission) + float(d.swap)
    except Exception:
        pass
    return r + sum(float(p.profit) for p in _positions())


def _council(cfg):
    """🏛️ مجلس الـ90 وكيلاً لكل رمز (agent_council.json، طازج ≤30ث)."""
    try:
        c = json.load(open(os.path.join(_RN, "agent_council.json"), encoding="utf-8"))
        if time.time() - float(c.get("ts", 0)) > 30:
            return {}
        return c.get("symbols") or {}
    except Exception:
        return {}


def _council_veto(sym, d, cfg):
    """🏛️ المجلس فيتو-فقط (قِيس: تنسيقٌ لا حافّة — لا يحجب زناد الرابح، يمنع فقط المعارضة الساحقة):
    يرجع سبباً إذا أجمع ≥council_veto_pct% في الاتجاه المعاكس، وإلا None."""
    try:
        cv = _council(cfg).get(sym) or {}
        pct = float(cv.get("agreement_pct", 0) or 0)
        if cv and int(cv.get("dir", 0)) == -d and pct >= float(cfg.get("council_veto_pct", 75.0)):
            return f"المجلس مُجمِعٌ ضدّنا {pct:.0f}% ≥ {cfg.get('council_veto_pct', 75.0)}%"
    except Exception:
        pass
    return None


def _sentinel_signal(cfg):
    """🛡️ زناد الحارس (الرابح المقيس 20260701): آخر تنبيهٍ طازج من gold_sentinel_feed.jsonl —
    قراءة ذيل الملف (~8KB) بلا تحميلٍ كامل، fail-soft: أيّ خللٍ ⇒ لا زناد (لا يُعطّل الحلقة)."""
    try:
        with open(SENT_F, "rb") as f:
            f.seek(0, 2); size = f.tell()
            f.seek(max(0, size - 8192))
            lines = f.read().decode("utf-8", "replace").splitlines()
        now = time.time(); best = None
        for ln in lines[-40:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                a = json.loads(ln)
            except Exception:
                continue
            d = _SENT_DIR.get(str(a.get("kind", "")))
            if not d:
                continue
            if now - float(a.get("ts", 0) or 0) > float(cfg.get("sentinel_max_age_s", 120)):
                continue
            if int(a.get("score", 0) or 0) < int(cfg.get("sentinel_min_score", 2)):
                continue
            if best is None or float(a.get("ts", 0)) >= float(best.get("ts", 0)):
                best = a
        if best:
            return {"dir": _SENT_DIR[str(best["kind"])], "kind": str(best.get("kind")),
                    "level": str(best.get("level", "")), "score": int(best.get("score", 0)),
                    "price": float(best.get("price", 0) or 0), "ts": float(best.get("ts", 0))}
    except Exception:
        pass
    return None


def _golden_veto(sym, direction, px):
    """⛔ الفيتو الذهبيّ — درس المستخدم بلسانه «شريت بالقمة» (مُدمج، fail-closed، بمرآتيه):
    لا شراء إذا مدى شمعة M1 >5$ أو السعر >5$ فوق EMA50-M1، ولا بيع إذا الشمعة هلعٌ >5$ أو
    السعر >5$ تحت EMA50-M1 (لا نبيع قاع شمعة الهلع)."""
    try:
        fo = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 1)   # الشمعة الجارية
        cl = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 80)  # المغلقات
        if fo is None or len(fo) < 1 or cl is None or len(cl) < 55:
            return "بيانات M1 ناقصة — نمتنع احتياطاً"
        rng_f = float(fo[0]["high"] - fo[0]["low"]); rng_c = float(cl[-1]["high"] - cl[-1]["low"])
        if rng_f > GOLDEN_BAR_USD:
            return f"مدى الشمعة الجارية {rng_f:.2f}$ > {GOLDEN_BAR_USD}$"
        if rng_c > GOLDEN_BAR_USD:
            return f"مدى آخر شمعة مغلقة {rng_c:.2f}$ > {GOLDEN_BAR_USD}$"
        e50 = _ema([float(x["close"]) for x in cl], 50)
        if e50 is not None and direction * (px - e50) > GOLDEN_EXT_USD:
            side = "فوق" if direction == 1 else "تحت"
            return f"السعر {abs(px - e50):.2f}$ {side} EMA50-M1 (>{GOLDEN_EXT_USD}$) — «شريت بالقمة»"
    except Exception as ex:
        return f"استثناء أثناء فحص الفيتو ({type(ex).__name__}) — نمتنع احتياطاً (fail-closed)"
    return None


def _night_blocked(cfg):
    """🌙 درس الحافّة المُثبَت (2026-05-31): ليل 22-08 UTC ينزف — لا دخولات جديدة."""
    if not cfg.get("night_block", True):
        return False
    h = datetime.utcnow().hour
    return h >= 22 or h < 8


def _pre_news_blocked(cfg):
    """📰 لا دخول قبل خبر USD أحمر بـ10 دقائق (آلية المحاكي حرفيّاً) — يرجع عنوان الخبر أو None."""
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


def _brain_read(cfg):
    """🧠 قراءة المخ الواحد (طازج ≤30ث) — رموز الإعدادات فقط (ذهبٌ افتراضاً، لا رشّ سوق)."""
    try:
        u = json.load(open(UNI_F, encoding="utf-8"))
        if time.time() - float(u.get("ts", 0)) > 30:
            return {}
        syms = set(cfg.get("symbols") or ["XAUUSDm"])
        return {s: o for s, o in (u.get("symbols") or {}).items() if s in syms}
    except Exception:
        return {}


def _momentum_ride(sym, d, o, cfg, atr):
    """🏇 هل الاندفاعة حيّة (نركبها) أم منهَكة (نتجنّبها)؟ «العنف بفن»:
    نعم إذا: قناعة المخ ≥ عتبة الزخم + آخر 3 شموع M1 بنفس اللون والاتجاه + المدى يتوسّع + بلا إنهاك
    (شمعة عملاقة >2.5×ATR ثم دوجي/انعكاس = إنهاك ⇒ لا)."""
    if float(o.get("conviction", 0) or 0) < float(cfg.get("momentum_conv_thr", 0.6)):
        return False
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 6)
    if r is None or len(r) < 5:
        return False
    bodies = [float(x["close"] - x["open"]) for x in r]
    rngs = [max(float(x["high"] - x["low"]), 1e-9) for x in r]
    seq = all(b * d > 0 for b in bodies[-3:])              # ثلاث شموع بنفس اتجاه الصفقة (زخم)
    expanding = rngs[-1] >= rngs[-2] * 0.8 and rngs[-1] > 0.5 * atr   # المدى لا ينكمش (حياة)
    exhausted = (rngs[-2] > 2.5 * atr and (abs(bodies[-1]) < 0.3 * rngs[-1] or bodies[-1] * bodies[-2] < 0))
    ok = seq and expanding and not exhausted
    if ok:
        _feed("momentum", sym=sym, conv=o.get("conviction"), note="اندفاعة حيّة — ركوبٌ بتريلينغ")
        print(f"🏇 R CORE زخم حيّ {sym}: 3 شموع {'صعود' if d == 1 else 'هبوط'} + توسّع + بلا إنهاك ⇒ نركبه")
    return ok


def _trail_momentum(cfg):
    """🏇 تريلينغ صفقات الزخم (comment=rcore_mom): يرفع الوقف خلف السعر بـtrail_atr×ATR كلّما تقدّم،
    ويبنك فوراً إن انعكست شمعة M1 مغلقة ضدّ الاتجاه بعد ربحٍ محقَّق ≥1×المخاطرة (يركض ثم يقبض بفنّ)."""
    for p in _positions():
        if "mom" not in str(getattr(p, "comment", "")):
            continue
        try:
            sym = p.symbol; d = 1 if p.type == 0 else -1
            atr = _atr(sym); tick = mt5.symbol_info_tick(sym); info = mt5.symbol_info(sym)
            if not (atr and tick and info) or atr <= 0:
                continue
            cur = float(tick.bid if d == 1 else tick.ask)
            trail = float(cfg.get("trail_atr", 0.8)) * atr
            new_sl = cur - d * trail
            # ارفع الوقف فقط في اتجاه الربح (لا نُرخيه أبداً)
            if (d == 1 and new_sl > float(p.sl) + info.point) or (d == -1 and new_sl < float(p.sl) - info.point):
                r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": sym, "position": p.ticket,
                                    "sl": round(new_sl, info.digits), "tp": float(p.tp), "magic": MAGIC})
                if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                    _feed("trail", sym=sym, new_sl=round(new_sl, info.digits), price=round(cur, info.digits))
            # بنك عند انعكاس شمعة M1 بعد ربحٍ محقَّق (لا نعيد المكسب للسوق)
            rr = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 2)
            if rr is not None and len(rr) >= 1 and p.profit > 0:
                b = rr[-1]; body = float(b["close"] - b["open"])
                moved = d * (cur - float(p.price_open))
                if body * d < 0 and abs(body) > 0.5 * atr and moved > atr:   # شمعة معاكسة قويّة بعد جريٍ
                    _close(p, "bank_reversal")
                    print(f"🏦 R CORE بنك زخم {sym}: انعكاس بعد جريٍ +{moved:.4f} (${p.profit:+.2f})")
        except Exception as e:
            print(f"trail err {getattr(p, 'symbol', '?')}: {type(e).__name__}: {e}")


def _break_even(cfg):
    """🔐 توقيع الرابحين (منقول من الحارس): بعد ربحٍ ≥ be_at_r×R (المخاطرة الحاليّة = |الدخول−الوقف|)
    ⇒ الوقف إلى سعر الدخول — مرّة واحدة فقط (بعد النقل يصبح الوقف عند الدخول فلا يُعاد)، ولا يُرخى أبداً."""
    frac = float(cfg.get("be_at_r", 0.5))
    for p in _positions():
        try:
            if not p.sl:
                continue
            stop_dist = abs(float(p.price_open) - float(p.sl))
            if stop_dist < 1e-9:
                continue
            be_done = (float(p.sl) >= float(p.price_open)) if p.type == 0 else (float(p.sl) <= float(p.price_open))
            if be_done:
                continue                              # الوقف عند الدخول أو أفضل (تريلينغ) — لا تكرار
            tick = mt5.symbol_info_tick(p.symbol); info = mt5.symbol_info(p.symbol)
            if not (tick and info):
                continue
            cur = float(tick.bid if p.type == 0 else tick.ask)
            fav = (cur - float(p.price_open)) if p.type == 0 else (float(p.price_open) - cur)
            if fav >= frac * stop_dist:
                r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                                    "sl": round(float(p.price_open), info.digits), "tp": float(p.tp),
                                    "magic": MAGIC})
                if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                    _feed("breakeven", sym=p.symbol, ticket=int(p.ticket),
                          sl=round(float(p.price_open), info.digits), fav=round(fav, 2),
                          r_dist=round(stop_dist, 2))
                    print(f"🔐 R CORE تعادل {p.ticket}: ربح {fav:.2f} ≥ {frac}×R({stop_dist:.2f}) — الوقف⇐الدخول")
        except Exception as e:
            print(f"be err {getattr(p, 'symbol', '?')}: {type(e).__name__}: {e}")


def _close(p, tag):
    tk = mt5.symbol_info_tick(p.symbol)
    if not tk:
        return
    mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                    "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": p.ticket, "price": tk.bid if p.type == 0 else tk.ask,
                    "deviation": 50, "magic": MAGIC, "comment": ("rcore_" + tag)[:31],
                    "type_filling": mt5.ORDER_FILLING_IOC})
    _feed("exit", sym=p.symbol, tag=tag, pnl=round(float(p.profit), 2))


def _sym_cooldown(sym, cfg):
    """🧊 حارس الانتقام (درس المستخدم: الانتقام قاتله #1): إن خسر الرمز ≥2 مرّة في آخر cool_win
    دقيقة ⇒ تبريده cool_min دقيقة (توقّف مطاردة الرمز الخاسر الدوّار). يُخبّأ 20ث لكل رمز."""
    now = time.time()
    cc = G.setdefault("cooldown_cache", {})
    ce = cc.get(sym)
    if ce and now - ce[0] < 20:
        return ce[1]
    try:
        frm = datetime.now() - timedelta(minutes=float(cfg.get("cool_win_min", 12)))
        losses = [d for d in (mt5.history_deals_get(frm, datetime.now()) or [])
                  if d.magic == MAGIC and d.symbol == sym and d.entry == 1 and d.profit < 0]
        until = 0.0
        if len(losses) >= int(cfg.get("cool_losses", 2)):
            last_loss = max(d.time for d in losses)
            until = last_loss + float(cfg.get("cool_min", 15)) * 60
    except Exception:
        until = 0.0
    cc[sym] = (now, until)
    return until


def _revenge_track(cfg):
    """🗡️ رصد الإغلاقات الخاسرة الجديدة لماجيكنا (نفس آلية كشف الخسائر في تبريد الانتقام:
    history_deals_get) وتسجيلها كمرشّحات ثأر في revenge_logic. إن كانت الخاسرة طلقةَ ثأرٍ
    (تعليقها rcore_rev) ⇒ قفل التصعيد للرمز حتى نهاية اليوم. fail-soft: أيّ خللٍ لا يمسّ الحلقة."""
    if revenge_logic is None or not isinstance(G.get("revenge"), dict):
        return
    rcfg = cfg.get("revenge") or {}
    if not rcfg.get("enabled", True):
        return
    now = time.time()
    if now - G.get("rev_scan_ts", 0) < 5:              # مسح كل 5ث يكفي (النافذة بالدقائق)
        return
    G["rev_scan_ts"] = now
    day = _rev_day()
    seen = G.get("rev_seen") or set()
    cur = set()
    try:
        frm = datetime.now() - timedelta(minutes=float(rcfg.get("window_min", 30)) + 5)
        for dl in (mt5.history_deals_get(frm, datetime.now() + timedelta(hours=12)) or []):
            if dl.magic != MAGIC or dl.entry != 1 or float(dl.profit) >= 0:
                continue                               # إغلاقات خاسرة لماجيكنا فقط
            tk = int(getattr(dl, "ticket", 0) or 0)
            if not tk:
                continue
            cur.add(tk)
            if tk in seen:
                continue                               # عولجت سابقاً
            sym = str(dl.symbol)
            pid = int(getattr(dl, "position_id", 0) or 0)
            meta = (G.get("open_meta") or {}).pop(pid, None)
            ddir = 1 if int(dl.type) == 1 else -1      # صفقة الإغلاق بيعٌ ⇒ المركز كان شراءً
            entry_px, sl_px, cmt = 0.0, 0.0, ""
            if meta:
                ddir = 1 if int(meta.get("dir", ddir)) > 0 else -1
                entry_px = float(meta.get("entry", 0) or 0)
                sl_px = float(meta.get("sl", 0) or 0)
                cmt = str(meta.get("comment", ""))
            if not entry_px and pid:                   # لا ذاكرة (إعادة تشغيل؟) ⇒ صفقات المركز نفسها
                try:
                    for d0 in (mt5.history_deals_get(position=pid) or []):
                        if int(d0.entry) == 0:
                            entry_px = float(d0.price)
                            cmt = cmt or str(getattr(d0, "comment", "") or "")
                            break
                except Exception:
                    pass
            if not entry_px:
                continue                               # بلا سعر دخولٍ حقيقيّ لا نسجّل (لا ثأر على تخمين)
            if not sl_px:
                sl_px = float(dl.price)                # الإغلاق الخاسر ≈ مكان الستوب
            revenge_logic.record_stop_out(G["revenge"], sym, ddir, entry_px, sl_px, float(dl.time), day)
            if "rcore_rev" in cmt:                     # طلقة ثأرٍ خسرت ⇒ قفل تصعيدٍ صارم
                revenge_logic.revenge_failed(G["revenge"], sym, day)
                _feed("revenge_lock", sym=sym,
                      note="🔒 قفل تصعيد: طلقة الثأر خسرت — لا ثأر ولا مطاردة للرمز حتى نهاية اليوم")
                print(f"🔒 R CORE قفل تصعيد {sym}: طلقة الثأر خسرت")
        G["rev_seen"] = cur                            # ما خرج من النافذة يسقط تلقائيّاً (ذاكرة محدودة)
    except Exception as e:
        print(f"revenge track err: {type(e).__name__}: {e}")


def _suite_eval(sym, cfg):
    """🎼 تقييم الحزمة الخماسيّة (suite_linreg_st) — جلب M1 مرّة كلّ ~5ث لكلّ رمز (مُخبَّأ في G)،
    fail-soft: غياب الوحدة/أيّ خللٍ ⇒ None (زناد هـ معطَّل بصمت، الحلقة لا تتأثّر)."""
    if suite_linreg_st is None or not cfg.get("suite_trigger", True):
        return None
    now = time.time()
    sc = G.setdefault("suite_cache", {})
    ent = sc.get(sym)
    if ent and now - ent[0] < 5:
        return ent[1]
    res = None
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 120)
        if r is not None and len(r) >= 60:
            out = suite_linreg_st.evaluate(r)
            if isinstance(out, dict):
                res = out
    except Exception:
        res = None
    sc[sym] = (now, res)                               # حتى الفشل يُخبَّأ 5ث (لا قصف للوحدة/الوسيط)
    return res


def _entry_thr(cfg, d, sense):
    """🎯 عتبة القناعة بعد لمسة الحسّ (المعدِّل 3، ناعمٌ ومحدود ±entry_sense_nudge — إحساسٌ لا قاعدة):
    إن اتّفق الزخم بقوّة مع اتجاه الصفقة والتذبذب صحّيّ ⇒ خفّض العتبة قليلاً؛ إن تعارضا ⇒ ارفعها.
    محصورةٌ دائماً في [conviction_thr - nudge, conviction_thr + nudge] ولا تنزل أبداً تحت أرضيةٍ صلبة
    (لا تُلغي بوّابة القناعة). adaptive_mode=false ⇒ العتبة الأصليّة بالحرف."""
    base = float(cfg.get("conviction_thr", 0.55))
    if not cfg.get("adaptive_mode", True) or not sense.get("fresh"):
        return base
    nudge = float(cfg.get("entry_sense_nudge", 0.05))
    mom = float(sense.get("momentum", 0.0)); vol = float(sense.get("vol", 0.5))
    agree = mom * float(d)                                 # >0 الزخم مع الصفقة، <0 ضدّها
    vol_ok = 0.35 <= vol <= 0.95                           # تذبذبٌ صحّيّ (لا ميّتٌ ولا هائج)
    if agree > 0.3 and vol_ok:
        thr = base - nudge * min(1.0, agree)              # اتفاقٌ قويّ + تذبذب صحّيّ ⇒ لمسة تساهل
    elif agree < -0.3 or not vol_ok:
        thr = base + nudge * min(1.0, abs(agree) if agree < 0 else 1.0)   # تعارضٌ/تذبذب رديء ⇒ لمسة تشدّد
    else:
        thr = base
    lo = max(float(cfg.get("entry_thr_floor", 0.45)), base - nudge)
    return _clamp(thr, lo, base + nudge)


def _trigger(sym, cfg, brain, sent, tick, atr, e50, sense=None):
    """🎯 الزنادات الخمسة — يرجع (dir, tag, o) أو None:
    أ) الحارس: تنبيه مستوياتٍ طازج (يخصّ XAUUSDm — الحارس يراقبه حصراً)، كلّ تنبيهٍ يُستهلك مرّة.
    ب) البنية: قناعة+اتفاق المخ والسعرُ على ارتدادٍ (غير ممتدّ عن EMA50-M1).
    ج) الزخم: ممتدّ لكنّ الاندفاعة حيّة — شرطٌ أشدّ (momentum_conv_thr + تسلسل 3 شموع).
    د) الثأر: ستوب ضُرب بذيلٍ ثم عاد السعر عبر الدخول الأصليّ بالاتجاه نفسه (revenge_logic) —
       نفس الحجم، نفس الاتجاه، ويمرّ على كامل سلسلة الفيتوهات كأيّ زناد.
    هـ) الاصطفاف الخماسيّ (Pine suite): LinReg+RSI+VWAP+SuperTrend+بنية متوافقة وانقلاب ST طازج
       (≤ suite_fresh_bars شمعة) — أدنى أولويّةً، ويمرّ على كامل سلسلة الفيتوهات كأيّ زناد."""
    if sent and sym == "XAUUSDm" and float(sent.get("ts", 0)) > float(G.get("sent_used", 0)):
        return int(sent["dir"]), "sentinel", {"conviction": None, "agree": None, "sent": sent}
    if revenge_logic is not None and isinstance(G.get("revenge"), dict):
        try:                                           # 🗡️ د) ثأر صيد-الستوب (النافذة ضيّقة ⇒ فحصٌ كلّ حلقة)
            mid = (float(tick.ask) + float(tick.bid)) / 2.0
            rv = revenge_logic.check_stop_hunt_reentry(G["revenge"], sym, mid, time.time(),
                                                       cfg.get("revenge"), _rev_day())
        except Exception:
            rv = None
        if rv:
            return (1 if int(rv.get("dir", 0)) > 0 else -1), "revenge", \
                   {"conviction": None, "agree": None, "rev": rv}
    o = (brain or {}).get(sym) or {}
    d = int(o.get("dir", 0) or 0)
    if d != 0:
        px = float(tick.ask if d == 1 else tick.bid)
        conv = float(o.get("conviction", 0) or 0); agree = int(o.get("agree", 0) or 0)
        extended = abs(px - e50) > float(cfg.get("extend_atr_max", 1.0)) * atr
        conv_thr = _entry_thr(cfg, d, sense or {})     # 🎯 عتبةٌ ملموسةٌ بالحسّ (±0.05، محدودة)
        if (not extended and conv >= conv_thr
                and agree >= int(cfg.get("agree_min", 3))):
            return d, "structure", o                   # ب) بنية على ارتداد — لا مطاردة
        if extended and cfg.get("momentum_mode", True) and _momentum_ride(sym, d, o, cfg, atr):
            return d, "momentum", o                    # ج) اندفاعة حيّة — ركوبٌ بتريلينغ
    sw = _suite_eval(sym, cfg)                         # 🎼 هـ) الاصطفاف الخماسيّ (أدنى أولويّة)
    if sw:
        setup = str(sw.get("setup", "") or "").lower()
        sd = 1 if "bull" in setup else (-1 if "bear" in setup else 0)
        try:
            age = int(sw.get("st_flip_age", 10 ** 9))
        except Exception:
            age = 10 ** 9
        if sd != 0 and age <= int(cfg.get("suite_fresh_bars", 8)):
            return sd, "suite", {"conviction": None, "agree": None,
                                 "suite": {"setup": sw.get("setup"), "score": sw.get("score"),
                                           "st_flip_age": age,
                                           "reason": "اصطفاف خماسيّ: LinReg+RSI+VWAP+ST+بنية"}}
    return None


def _try_enter(sym, cfg, equity, brain, sent):
    """🎯 R CORE: الدخول = زنادٌ ∧ لا فيتو — كلّ امتناعٍ يُسجَّل بسببه (فتتعلّم المحاسبة لماذا امتنعنا)."""
    if "XAU" not in sym.upper():                      # 🧱 جدارٌ صلب كالديمو: R CORE ذهبٌ فقط — حتى لو عُدّلت الإعدادات
        _veto(sym, "symbol", "R CORE ذهبٌ فقط — رمزٌ غير ذهبيّ مرفوض (جدار مُدمج)"); return
    now = time.time()
    if now - G["last_entry"].get(sym, 0) < float(cfg.get("reentry_gap_s", 20)):
        return
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    atr = _atr(sym); e50 = _ema_m1(sym)
    if not (info and tick and atr and e50) or atr <= 0:
        return
    sense = _sense_read(cfg)                          # 👁️ حسّ السوق (محايدٌ إن غاب/بائت) — لا يمسّ الفيتوهات
    trg = _trigger(sym, cfg, brain, sent, tick, atr, e50, sense)
    if not trg:
        return
    d, tag, o = trg
    rev_mult, rev_note = 1.0, ""                       # 🗡️ مضاعف حجم الثأر (≤1.0 دائماً — لا مضاعفة أبداً)
    is_rev = (tag == "revenge")
    if is_rev:
        rv = o.get("rev") or {}
        rev_mult = min(1.0, float(rv.get("size_mult", 1.0)))
        rev_note = str(rv.get("reason", ""))
    # ══ الفيتوهات — أيّ واحدٍ يصدق ⇒ لا دخول (الأمان يغلب الزناد دائماً) ══
    poss = _positions()
    if len(poss) >= int(cfg.get("max_positions", 3)):
        _veto(sym, "max_positions", f"≥{cfg.get('max_positions', 3)} مراكز مفتوحة", trigger=tag); return
    if any(p.symbol == sym and (1 if p.type == 0 else -1) == -d for p in poss):
        _veto(sym, "hedge", "مركزٌ معاكس مفتوح على الرمز نفسه — لا تحوّط ذاتيّ", trigger=tag); return
    # 🚫 لا تكديس على أحمر (درس انهيار +80% في 2026-06-29، وتكراره هنا 11:00:02/22/42 اليوم: 3 دخولات
    # بنفس الاتجاه خلال 40ث ⇒ ذبذبة واحدة = خسارة ثلاثيّة ⇒ تجميد اليوم). الإضافة بنمط بنك-الموجة
    # اليدويّ: فوق صفقةٍ رابحة ≥ stack_min_r×R فقط.
    same_dir = [p for p in poss if p.symbol == sym and (1 if p.type == 0 else -1) == d]
    if same_dir:
        min_r = float(cfg.get("stack_min_r", 0.3))
        def _prof_r(p):
            risk = abs(float(p.price_open) - float(p.sl)) if p.sl else 0.0
            return (float(p.profit) / (risk * float(p.volume) * 100.0)) if risk > 0 else 0.0
        if not all(_prof_r(p) >= min_r for p in same_dir):
            _veto(sym, "stack_red", f"تكديسٌ فوق صفقةٍ غير رابحة (<{min_r}R) — الإضافة للرابح فقط (بنك-الموجة)",
                  trigger=tag); return
    cd = _sym_cooldown(sym, cfg)
    if now < cd:
        # 🎯 وضع المطاردة (revenge_logic.hunt_gate): التبريد لا يُكسَر إلا بإشارة A+
        # (توافق حارسٍ ≥ hunt_min_score) وبنصف الحجم وطلقة واحدة للرمز — وإلا الفيتو كما كان.
        ok_hunt, mult, note = False, 0.0, ""
        if revenge_logic is not None and isinstance(G.get("revenge"), dict):
            try:
                t_score = int((o.get("sent") or {}).get("score", 0) or 0) if tag == "sentinel" else 0
                ok_hunt, mult, note = revenge_logic.hunt_gate(G["revenge"], sym, True, t_score,
                                                              cfg.get("revenge"), _rev_day())
            except Exception:
                ok_hunt, note = False, ""
        if not ok_hunt:
            _veto(sym, "revenge",
                  note or f"تبريد الانتقام: خسارتان مؤخّراً — راحة {int((cd - now) / 60)}د", trigger=tag)
            return
        rev_mult = min(rev_mult, 1.0, float(mult)); is_rev = True; rev_note = note
        print(f"🎯 R CORE مطاردة {sym}: {note} (حجم ×{rev_mult:.2f})")
    if _night_blocked(cfg):
        _veto(sym, "night", "ليل 22-08 UTC — حافّة الانضباط المثبتة", trigger=tag); return
    ev = _pre_news_blocked(cfg)
    if ev:
        _veto(sym, "pre_news", f"خبر أحمر بعد <{cfg.get('pre_news_block_min', 10)}د: {ev}", trigger=tag); return
    if not mt5.symbol_select(sym, True):
        return
    px = float(tick.ask if d == 1 else tick.bid)
    spread = float(tick.ask - tick.bid)
    # 🌗 المعدِّل 2 — ضبط السبريد الذاتيّ (ناعمٌ ومحدود بسقفٍ مطلق): بدل عتبةٍ واحدة ثابتة، نلمس التسامح
    # بحسّ السبريد (spread_sense∈[0,1]، 1=مريحٌ ضيّق). سبريدٌ مريح ⇒ لمسة تساهل، واسعٌ ⇒ تشدّد — لكن
    # لا يقبل سبريداً سخيفاً أبداً (سقفٌ مطلق spread_atr_abs_cap). adaptive_mode=false ⇒ العتبة الأصليّة.
    base_thr = float(cfg.get("spread_atr_max", 0.4))
    spread_thr = base_thr
    if cfg.get("adaptive_mode", True) and sense.get("fresh"):
        k = float(cfg.get("spread_sense_k", 0.5))
        scale = _clamp(1.0 + k * (float(sense.get("spread", 0.5)) - 0.5), 1.0 - k / 2.0, 1.0 + k / 2.0)
        spread_thr = min(base_thr * scale, float(cfg.get("spread_atr_abs_cap", 0.6)))  # 🧱 سقفٌ مطلق
    if spread > spread_thr * atr:
        _veto(sym, "spread", f"سبريد {spread:.2f} > {spread_thr:.3f}×ATR — يلتهم الحركة",
              trigger=tag); return
    gv = _golden_veto(sym, d, px)
    if gv:
        _veto(sym, "golden", gv, trigger=tag); return
    h1b = _tf_bias(sym, mt5.TIMEFRAME_H1)
    if h1b == -d:
        _veto(sym, "trend", f"عكس ترند H1 ({h1b:+d} ضدّ {d:+d}) — لا نتاجر عكس الترند الكبير", trigger=tag)
        return
    cv = _council_veto(sym, d, cfg)
    if cv:
        _veto(sym, "council", cv, trigger=tag); return
    # ══ الوقف/الهدف/الحجم — order_calc_profit الرسميّ بسقفٍ صلب 2% ══
    sl_d = float(cfg.get("sl_atr", 0.8)) * atr        # الوقف الهيكليّ المرغوب (ATR)
    sl_px = px - d * sl_d
    tp_r = float(cfg.get("momentum_tp_r", 4.0)) if tag == "momentum" else float(cfg.get("tp_r", 2.0))
    tp_px = px + d * tp_r * sl_d
    step = float(info.volume_step or 0.01); vmin = float(info.volume_min or 0.01)
    vmax = float(info.volume_max or 100.0)
    # 🎚️ ميزانيّة المخاطرة من سُلّم الثقة — أرضية 0.5% وسقف 2% (تُكتسب بالإثبات لا تُمنح)
    risk_pct = float(G.get("risk_pct", cfg.get("base_risk_floor_pct", 0.5)))
    risk_pct = max(float(cfg.get("base_risk_floor_pct", 0.5)), min(risk_pct, float(cfg.get("risk_max_pct", 2.0))))
    gov_mult = _gov_mult() if cfg.get("collective_mode", True) else 1.0   # 🤝 خنق حوكمة الأسطول (بدل التجميد)
    conf_mult = _conf_modifier(cfg)   # 🎯 المعدِّل 1 — القناعة↔الثقة (مقيسة من الصفقات المغلقة الحقيقيّة، [0.5,1.3])
    # الثقة تُطبَّق على الميزانيّة قبل قصّ السقف الصلب أدناه ⇒ السقف يغلب دائماً (فوزٌ ⇒ حجمٌ أكبر قليلاً،
    # خسارةٌ ⇒ أصغر — لكن لا تتجاوز السقف الصلب ولا تنزل تحت حارس أدنى-لوت/2% أبداً).
    cap_usd = risk_pct / 100.0 * equity * min(1.0, rev_mult) * gov_mult * conf_mult  # 🗡️ الثأر ≤1.0
    otype = mt5.ORDER_TYPE_BUY if d == 1 else mt5.ORDER_TYPE_SELL
    loss_1lot = mt5.order_calc_profit(otype, sym, 1.0, px, sl_px)
    if loss_1lot is None or loss_1lot >= 0:
        _veto(sym, "calc", "تعذّر حساب مخاطرة الوسيط (order_calc_profit)", trigger=tag); return
    risk_per_lot = abs(float(loss_1lot))              # خسارة 1.0 لوت بالدولار إن ضُرب الوقف
    ceiling_usd = float(cfg.get("hard_ceiling_pct", 2.0)) / 100.0 * equity
    cap_usd = min(cap_usd, ceiling_usd)               # 🧱 السقف الصلب يغلب الثقة دائماً (قصٌّ بعد التعديل)
    if risk_per_lot * vmin > ceiling_usd:             # أدنى لوت يتجاوز السقف ⇒ ضيّق الوقف حتى أرضية 0.5×ATR
        shrink = ceiling_usd / (risk_per_lot * vmin)
        floor_frac = float(cfg.get("min_sl_atr", 0.5)) / max(float(cfg.get("sl_atr", 0.8)), 1e-9)
        if shrink < floor_frac:                       # حتى أضيق وقفٍ آمن يتجاوز السقف ⇒ لا صفقة
            _veto(sym, "size", f"أدنى لوت {vmin} يخاطر ${risk_per_lot * vmin:.2f} > سقف ${ceiling_usd:.2f} "
                  f"حتى بأضيق وقف", trigger=tag); return
        sl_d *= shrink; sl_px = px - d * sl_d; tp_px = px + d * tp_r * sl_d
        recalc = mt5.order_calc_profit(otype, sym, 1.0, px, sl_px)
        if recalc is not None and recalc < 0:
            risk_per_lot = abs(float(recalc))         # وإلا نبقي تقدير الوقف الأعرض (أشدّ تحفّظاً — لوت أصغر)
        _feed("tighten", sym=sym, note=f"وقف كُيِّف ×{shrink:.2f} ليُلائم سقف {cfg.get('hard_ceiling_pct', 2.0)}%")
    lot = max(vmin, math.floor((cap_usd / risk_per_lot) / step) * step)
    lot = min(lot, vmax)
    risk = risk_per_lot * lot
    if risk > ceiling_usd:                             # حارس صلب نهائيّ: لا صفقة تتجاوز السقف
        _veto(sym, "risk", f"مخاطرة ${risk:.2f} > سقف ${ceiling_usd:.2f}", trigger=tag); return
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot,
           "type": mt5.ORDER_TYPE_BUY if d == 1 else mt5.ORDER_TYPE_SELL, "price": px,
           "sl": round(sl_px, info.digits), "tp": round(tp_px, info.digits),
           "deviation": 50, "magic": MAGIC,
           "comment": ("rcore_rev" if is_rev else ("rcore_mom" if tag == "momentum" else "rcore")),
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        G["last_entry"][sym] = now
        if tag == "sentinel":                          # كلّ تنبيه حارسٍ يُستهلك مرّة واحدة (لا تكديس عليه)
            G["sent_used"] = float((o.get("sent") or {}).get("ts", now))
        try:                                           # 🗡️ ذاكرة المراكز المفتوحة (لتسجيل الستوب-آوت بدقّة)
            tk = int(getattr(r, "order", 0) or 0)
            if tk:
                G.setdefault("open_meta", {})[tk] = {"sym": sym, "dir": d, "entry": px,
                                                     "sl": float(req["sl"]), "comment": str(req["comment"])}
                for k in list(G["open_meta"])[:-50]:   # حدّ 50 مدخلاً — الأقدم يُطرَح
                    G["open_meta"].pop(k, None)
        except Exception:
            pass
        _feed("entry", sym=sym, trigger=tag, dir=("buy" if d == 1 else "sell"),
              px=px, sl=req["sl"], tp=req["tp"], lot=lot, conviction=o.get("conviction"),
              agree=o.get("agree"), sent=o.get("sent"), suite=o.get("suite"),
              atr=round(atr, 5), risk_usd=round(risk, 2),
              risk_pct=round(100 * risk / equity, 2) if equity > 0 else 0, budget_pct=round(risk_pct, 2),
              revenge=bool(is_rev), rev_reason=(rev_note or None),
              conf_mult=round(conf_mult, 3), sense=(sense if sense.get("fresh") else None))
        print(f"✅ R CORE دخول {sym} {'شراء' if d == 1 else 'بيع'} [{tag}] @ {px} لوت {lot} "
              f"وقف {req['sl']} هدف {req['tp']} (مخاطرة {risk_pct:.1f}%=${risk:.2f})")
    else:
        print(f"⚠️ R CORE فشل {sym}: {getattr(r, 'retcode', None)} {getattr(r, 'comment', '')}")


def _save_status(cfg, pnl, frozen, n_sig):
    now = time.time()
    if now - G["status_ts"] < 5:
        return
    G["status_ts"] = now
    poss = _positions()
    st = {"ts": round(now, 1), "iso": datetime.now().isoformat(timespec="seconds"),
          "engine": "R CORE", "mode": "r_core",
          "magic": MAGIC, "positions": len(poss), "symbols_open": [p.symbol for p in poss],
          "pnl_today": round(pnl, 2), "frozen": frozen, "signals_now": n_sig,
          "floating": round(sum(float(p.profit) for p in poss), 2),
          "risk_pct": round(float(G.get("risk_pct", 0.5)), 2),        # 🎚️ ميزانيّة المخاطرة الحاليّة
          "confidence": round(float(G.get("confidence", 0.0)), 2),
          "satisfaction": G.get("satisfaction", 0)}
    rv = G.get("revenge")
    if revenge_logic is not None and isinstance(rv, dict):            # 🗡️ ملخّص الثأر
        st["revenge"] = {"avenged_today": int(rv.get("avenged_today", 0) or 0),
                         "locked": sorted(s for s, v in (rv.get("locked") or {}).items() if v)}
    try:                                                              # 🎼 ملخّص الحزمة الخماسيّة (من الخبيئة — بلا كلفة)
        psym = (cfg.get("symbols") or ["XAUUSDm"])[0]
        ent = (G.get("suite_cache") or {}).get(psym)
        sw = ent[1] if ent else None
        if isinstance(sw, dict):
            st["suite"] = {"setup": sw.get("setup"), "score": sw.get("score")}
    except Exception:
        pass
    try:
        t = STATUS_F + ".tmp"; json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, STATUS_F)
    except Exception:
        pass


def main():
    ok = False
    for i in range(6):
        if mt5.initialize():
            ok = True; break
        print(f"⏳ init {i + 1}/6"); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5"); return
    print(f"🥷 R CORE بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — ماجيك {MAGIC} · ذهبٌ فقط · ديمو فقط")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True) or os.path.exists(KILL1) or os.path.exists(KILL2):
                # 💤 مُعطَّل/مقفول: نبض قلب idle كي لا يراه الوصيّ «معلّقاً» فيدخل حلقة قتل/إحياء.
                try:
                    st = {"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
                          "engine": "R CORE", "mode": "r_core",
                          "magic": MAGIC, "positions": 0, "pnl_today": 0.0, "frozen": False,
                          "signals_now": 0, "disabled": True,
                          "reason": "معطَّل/مقفول — R CORE خامل (enabled=false أو kill_switch)"}
                    t = STATUS_F + ".tmp"; json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False)
                    os.replace(t, STATUS_F)
                except Exception:
                    pass
                time.sleep(10); continue
            acct = mt5.account_info(); srv = str(getattr(acct, "server", "") or "")
            if not acct or not ("Trial" in srv or "Demo" in srv):
                print(f"⛔ خادم '{srv}' ليس ديمو — رفض"); time.sleep(30); continue
            today = datetime.now().strftime("%Y-%m-%d")
            if G["day"] != today:
                G["day"] = today; G["frozen_until"] = 0.0
            pnl = _pnl_today()
            _revenge_track(cfg)                        # 🗡️ رصد الستوب-آوتات الجديدة كمرشّحات ثأر
            # 🎚️ سُلّم الثقة: أعِد التقييم كل 30ث ⇒ ميزانيّة المخاطرة بحسب الأداء المقيس (أرضية 0.5% سقف 2%)
            if perf_ladder and time.time() - G.get("ladder_ts", 0) > 30:
                try:
                    lad = perf_ladder.evaluate(MAGIC, cfg.get("ladder") or {})
                    prev = G.get("risk_pct")
                    G["risk_pct"] = max(float(cfg.get("base_risk_floor_pct", 0.5)),
                                        min(float(lad.get("risk_pct", 0.5)), float(cfg.get("risk_max_pct", 2.0))))
                    G["confidence"] = float(lad.get("confidence", 0.0))
                    G["satisfaction"] = lad.get("satisfaction", 0)
                    G["ladder_ts"] = time.time()
                    if prev is not None and abs(G["risk_pct"] - prev) >= 0.25:  # سجّل تغيّر الدرجة
                        _feed("ladder", risk_pct=G["risk_pct"], confidence=G["confidence"],
                              satisfaction=G["satisfaction"], reason=lad.get("reason"))
                        print(f"🎚️ سُلّم الثقة: مخاطرة {prev:.1f}%→{G['risk_pct']:.1f}% · "
                              f"رضا {G['satisfaction']}% · {lad.get('reason')}")
                except Exception as e:
                    print(f"ladder err: {type(e).__name__}: {e}")
            # 🤝 وضع الجماعة (collective_mode): لا تجميد يوميّ — نواصل تقييم الدخول بحجمٍ مخنوقٍ عبر
            # حوكمة الأسطول (_gov_mult). التجميد التقليديّ يبقى فقط إن أُطفئ الوضع صراحةً.
            if cfg.get("collective_mode", True):
                G["frozen_until"] = 0.0                 # نظّف أيّ تجميدٍ عالق كي لا يتسرّب
                frozen = False
            else:
                frozen = time.time() < G["frozen_until"]
                if not frozen and pnl <= -float(cfg.get("daily_loss_pct", 6.0)) / 100.0 * float(acct.equity):
                    G["frozen_until"] = (datetime.now() + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0).timestamp()
                    frozen = True; _feed("freeze", pnl=round(pnl, 2))
                    print(f"🧊 R CORE تجميد: خسارة اليوم ${pnl:+.2f}")
            # 🏇 إدارة المراكز: تريلينغ الزخم + 🔐 التعادل المبكّر (توقيع الرابحين) + تسوية المُسنّة
            _trail_momentum(cfg)
            _break_even(cfg)
            for p in _positions():
                age_min = (time.time() - int(getattr(p, "time", time.time()))) / 60.0
                if age_min > float(cfg.get("hold_max_min", 90)):
                    _close(p, "force_flat")
            brain = _brain_read(cfg)
            sent = _sentinel_signal(cfg)
            n_sig = (1 if sent else 0) + sum(
                1 for _s, o in brain.items()
                if int(o.get("dir", 0) or 0) != 0
                and float(o.get("conviction", 0) or 0) >= float(cfg.get("conviction_thr", 0.55))
                and int(o.get("agree", 0) or 0) >= int(cfg.get("agree_min", 3)))
            if not frozen and len(_positions()) < int(cfg.get("max_positions", 3)):
                for sym in (cfg.get("symbols") or ["XAUUSDm"]):
                    if len(_positions()) >= int(cfg.get("max_positions", 3)):
                        break
                    _try_enter(sym, cfg, float(acct.equity), brain, sent)
            _save_status(cfg, pnl, frozen, n_sig)
            time.sleep(float(cfg.get("loop_s", 0.3)))  # ⚡ نبضٌ سريع (0.3ث) — السرعة لإدارة المخاطر لا للمطاردة
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
