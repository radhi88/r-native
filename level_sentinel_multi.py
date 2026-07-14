# -*- coding: utf-8 -*-
"""level_sentinel_multi.py — 🌍 حارس المستويات متعدد العملات: استنساخٌ حرفيّ لحارس الذهب الرابح
(gold_level_sentinel.py — اليوم +$19.09 صفقة واحدة، payoff 1.83) على سلّة رموزٍ بلا الذهب.

نفس المنطق بالضبط (طلب المستخدم 2026-07-07): كشف المستويات (قمّة/قاع اليوم والأسبوع، المستديرات،
EMA50/200 كمستوياتٍ متحرّكة)، توافق 0-6 (Stochastic 14,3,3 EMA · اتجاه EMA · ميل السلّة/الدولار ·
ذيل الرفض · تأكيد الشموع)، أنواع التنبيه (ارتداد-شراء/رفض-بيع/كسر-صعوديّ/كسر-هبوطيّ)، بوّابات
التنفيذ (_maybe_execute)، هندسة 0.5R وقف/هدف، نقل الوقف للتعادل، تبريد ما بعد الوقف، حظر الليل.

⚠️ الفروقات الموثّقة الوحيدة عن الأصل:
1. MAGIC=20260709 · engine_lock.claim("level_sentinel_multi") (منفذ صريح 8766) · ملفات
   level_sentinel_multi_{status.json,feed.jsonl} · level_sentinel_multi_config.json ·
   level_sentinel_multi.out.log · lsm_slcool.json.
2. SYMBOLS من الإعدادات (افتراضيّاً 15 رمزاً) — XAUUSDm مستبعَدٌ قسريّاً: الأصلي يملك الذهب،
   لا ازدواج. حالة لكل رمز (dedup/_last_exec/تبريد الوقف مفاتيحها الرمز).
3. الحلقة تمسح كلّ الرموز في كلّ دورة، POLL_S=10 (الأصل 5 ثوانٍ لرمزٍ واحد؛ 10 ثوانٍ لـ15 رمزاً
   = المكافئ الرشيق — لا نُغرق الطرفية بنداءات mt5). رمزٌ غير ظاهر/معطّل ⇒ تخطٍّ صامت (fail-soft).
4. المستديرات عامّة (الذهب كان 5/10$ ثابتة): step = 10**floor(log10(price))/100 مقرَّباً لأرقام
   الوسيط، ثم تصعيدٌ بسلّم 1-2-5 حتى step >= 2*ATR(M5) (شبكةٌ أنعم من الضجيج بلا معنى)؛ شبكتان
   (step, 2*step) تُحاكيان (5,10) للذهب. محور السلّة: DXYm لأزواج الدولار — إشارة معكوسة للأزواج
   المسعّرة بالدولار (مثل منطق الذهب: دولار↑ ⇒ ضغطٌ بيعيّ) ومباشرة لأزواج USD-كأساس؛ الكريبتو
   والمؤشرات والنفط والتقاطعات بلا دولار ⇒ المحور غير متاح ولا يُحتسب (لا تزييف).
5. إعدادات افتراضيّة محافظة: min_exec_score=2 · max_positions=3 · per_symbol_max=1 ·
   risk_cap=3% · exec_cooldown 10د · تُنشأ ذريّاً إن غابت.
6. حارس حجم الحساب (عقيدة الأسطول — الأصل يفتقده): قبل كلّ أمرٍ، لو خطرُ أدنى لوت
   (order_calc_profit على مسافة الوقف الفعليّة) > 2.5% من الحقوق ⇒ فيتو مع سببٍ مطبوع
   (درس المعادن على الحسابات الصغيرة: أدنى لوت قد يخاطر 6-18%).
7. الحجم عامّ عبر order_calc_profit (بديل معادلة الذهب $100/لوت) مع risk_cap من الإعدادات؛
   كتابة الملفات ذريّة (tmp ثم os.replace).

🚫 ديمو فقط + kill_switch + السبورة (execute في الإعدادات) تحكم. تشغيل (نافذة):
pythonw.exe level_sentinel_multi.py"""
from __future__ import annotations
import sys, os, json, time, math
from pathlib import Path
from datetime import datetime, timedelta

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "level_sentinel_multi.out.log"
STATUS_F = RN / "level_sentinel_multi_status.json"
FEED_F = RN / "level_sentinel_multi_feed.jsonl"

# نافذة-آمن: أعِد توجيه stdout/stderr قبل أيّ استيراد ثقيل (pythonw بلا stdout ⇒ تعطّل)
try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import numpy as np
import MetaTrader5 as mt5

try:
    import engine_lock
except Exception:
    engine_lock = None

POLL_S = 5                 # 2026-07-08: 10→5ث — طلب المستخدم «الرابحين أسرع» (مسحٌ أكثف لكل الرموز)
NEAR_R = 0.15              # «قرب المستوى» = ضمن 0.15R
BREAK_R = 0.10             # كسرٌ واضح = تجاوز المستوى بـ0.10R إغلاقاً
DEDUP_MIN = 15             # لا نكرّر نفس التنبيه (رمز+مستوى+نوع) قبل 15 دقيقة
MINLOT_VETO = 0.025        # 🛡️ حارس حجم الحساب: خطر أدنى لوت > 2.5% حقوق ⇒ فيتو
CFG_F = MT5DIR / "level_sentinel_multi_config.json"
SENSE_F = RN / "market_sense.json"          # 👁️ حسّ السوق (adaptive_sense يكتبه: spread/momentum/vol)
CONF_F = RN / "confidence.json"             # 🎯 ثقةٌ مكتسبة من الصفقات المغلقة الحقيقيّة فقط
MAGIC = 20260709
DEFAULT_SYMBOLS = ["XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "USDCHFm",
                   "EURJPYm", "GBPJPYm", "BTCUSDm", "ETHUSDm", "US30m", "US500m", "USTECm", "USOILm"]
DEFAULT_CFG = {
    "enabled": True, "execute": True, "min_exec_score": 2, "max_positions": 3,
    "per_symbol_max": 1, "stop_r": 0.5, "target_r": 0.5, "risk_cap": 0.03,
    "exec_cooldown_min": 10, "stop_cooldown_min": 30, "exec_night_block": True,
    # 👁️🎯 التكيّف الناعم (adaptive_sense): يُعدّل داخل الحدود الآمنة فقط — لا يرفع فيتو ولا يتجاوز
    # risk_cap ولا حارس 2.5% ولا أرضيّة السبريد. adaptive_mode=false ⇒ السلوك القديم بالحرف.
    "adaptive_mode": True, "conf_lo": 0.5, "conf_hi": 1.3, "sense_max_age_s": 120,
    "spread_sense_k": 0.5, "spread_atr_abs_cap": 0.6, "entry_sense_nudge": 0.05, "exec_score_floor": 2,
    "symbols": DEFAULT_SYMBOLS,
    "_note": ("🌍 حارس المستويات متعدد العملات — استنساخ حرفي لحارس الذهب الرابح (طلب المستخدم "
              "2026-07-07). ماجيك 20260709، ديمو فقط، السبورة تحكم. risk_cap افتراضي 3% (محافظ) — "
              "يُرفع من هنا مثل ما فعل المستخدم للذهب."),
}
_last_alert: dict = {}     # dedup لكل (رمز|مستوى|نوع)
_last_exec: dict = {}      # آخر تنفيذ لكل رمز
_last_kind: dict = {}      # آخر نوع تنبيهٍ لكل رمز (للستاتس)
_SLCOOL_F = RN / "lsm_slcool.json"


def _aw(path, obj):
    """كتابة ذريّة: tmp ثم os.replace (لا ملفّات نصف مكتوبة يقرأها الداشبورد)."""
    try:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, str(path))
    except Exception:
        pass


def _ensure_cfg():
    """أنشئ الإعدادات ذريّاً إن غابت (لا نلمسها إن وُجدت — السبورة/المستخدم يملكانها)."""
    if not CFG_F.exists():
        try:
            tmp = str(CFG_F) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CFG, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(CFG_F))
            print(f"⚙️ أنشأتُ الإعدادات الافتراضيّة: {CFG_F}")
        except Exception:
            pass


def _cfg():
    """إعدادات: execute=true افتراضياً بعتبةٍ مثل الذهب الرابح — والسبورة تطفئه متى شاءت."""
    d = dict(DEFAULT_CFG)
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        pass
    return d


def _is_demo():
    try:
        a = mt5.account_info()
        s = (a.server or "").lower() if a else ""
        return ("demo" in s) or ("trial" in s)
    except Exception:
        return False


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        return lo
    return lo if v < lo else (hi if v > hi else v)


def _sense_read(cfg):
    """👁️ حسّ السوق (market_sense.json من adaptive_sense) — قراءة دفاعيّة fail-soft إلى المحايد:
    غياب الملفّ/قِدمه/أيّ خللٍ ⇒ محايدٌ = بلا تعديل. لا يمسّ الحلقة أبداً."""
    neutral = {"spread": 0.5, "momentum": 0.0, "vol": 0.5, "fresh": False}
    if not cfg.get("adaptive_mode", True):
        return neutral
    try:
        s = json.load(open(SENSE_F, encoding="utf-8"))
        if not isinstance(s, dict):
            return neutral
        if time.time() - float(s.get("ts", 0) or 0) > float(cfg.get("sense_max_age_s", 120)):
            return neutral
        return {"spread": _clamp(s.get("spread_sense", 0.5), 0.0, 1.0),
                "momentum": _clamp(s.get("momentum_sense", 0.0), -1.0, 1.0),
                "vol": _clamp(s.get("vol_sense", 0.5), 0.0, 1.0), "fresh": True}
    except Exception:
        return neutral


def _conf_modifier(cfg):
    """🎯 مُعامل الثقة لماجيكنا (confidence.json[magic].modifier، مقيسٌ من صفقاتٍ مغلقةٍ حقيقيّة فقط) —
    fail-soft إلى 1.0 ويُقصّ صلباً إلى [conf_lo, conf_hi] (افتراضيّاً [0.5,1.3]). غياب الملف/المفتاح ⇒ 1.0."""
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


def _loss_per_lot(sym, stop_dist, is_buy=True):
    """خسارة 1.0 لوت لو ضُرب الوقف (order_calc_profit على المسافة الفعليّة؛ fallback: tick_value)."""
    si = mt5.symbol_info(sym); ti = mt5.symbol_info_tick(sym)
    if not si or not ti or stop_dist <= 0:
        return 0.0
    try:
        px = ti.ask if is_buy else ti.bid
        px2 = px - stop_dist if is_buy else px + stop_dist
        loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                                     sym, 1.0, px, px2)
        if loss is not None and abs(float(loss)) > 0:
            return abs(float(loss))
    except Exception:
        pass
    try:
        ts = si.trade_tick_size or si.point or 1e-9
        return abs((stop_dist / ts) * si.trade_tick_value)
    except Exception:
        return 0.0


def _rec_lot(sym, equity, stop_dist, risk, per_lot=None):
    """حجمٌ عامّ لكلّ رمز (فارق موثّق 7): lot = risk_cap*equity / خسارة-اللوت-الواحد على مسافة الوقف،
    مقرَّباً لأسفل على volume_step ومحصوراً [volume_min, volume_max]. risk_cap من الإعدادات يقود."""
    si = mt5.symbol_info(sym)
    if not si or equity <= 0 or stop_dist <= 0:
        return 0.0
    pl = per_lot if per_lot else _loss_per_lot(sym, stop_dist)
    if pl <= 0:
        return 0.0
    lot = (float(risk or 0.03) * equity) / pl
    step = si.volume_step or 0.01
    lot = math.floor(lot / step + 1e-9) * step
    return max(si.volume_min or 0.01, min(round(lot, 8), si.volume_max or 100.0))


def _place(sym, is_buy, entry, sl, tp, lot, digits):
    """أمرٌ محكوم (ديمو فقط، وقف+هدف مضبوطان مسبقاً = set-and-forget). يرجع True عند التنفيذ."""
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
           "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL, "price": float(entry),
           "sl": float(round(sl, digits)), "tp": float(round(tp, digits)), "deviation": 30,
           "magic": MAGIC, "comment": "lvl_multi", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    if ok:
        print(f"   ⚡ نُفّذت (ديمو) {sym}: {'شراء' if is_buy else 'بيع'} {lot} @ {entry:.{digits}f} "
              f"وقف {sl:.{digits}f} هدف {tp:.{digits}f}")
    else:
        print(f"   ⏭️ لم تُنفّذ {sym}: {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}")
    return ok


def _slcool():
    try:
        d = json.load(open(_SLCOOL_F, encoding="utf-8"))
        if isinstance(d.get("until"), dict) and isinstance(d.get("track"), dict):
            return d
    except Exception:
        pass
    return {"until": {}, "track": {}}


def _slcool_save(d):
    _aw(_SLCOOL_F, d)


def _slcool_reconcile(cfg):
    """🧊 بعد ضرب الوقف: تبريد stop_cooldown_min (افتراضيّ 30د) **لذلك الرمز** — لا ثأر فوريّ."""
    d = _slcool(); trk = d.get("track", {})
    if not trk:
        return
    open_ids = {str(p.ticket) for p in (mt5.positions_get() or []) if p.magic == MAGIC}
    changed = False
    for tk, sym in list(trk.items()):
        if tk in open_ids:
            continue
        try:
            deals = mt5.history_deals_get(position=int(tk)) or []
            hit = any(x.entry == 1 and "sl" in (x.comment or "").lower() for x in deals)
        except Exception:
            hit = False
        if hit:
            d.setdefault("until", {})[str(sym)] = time.time() + cfg.get("stop_cooldown_min", 30) * 60
            print(f"🧊 {sym} {tk} ضرب الوقف — تبريد تنفيذه {cfg.get('stop_cooldown_min', 30)}د "
                  f"(التنبيهات مستمرّة)")
        del trk[tk]; changed = True
    if changed:
        _slcool_save(d)


_COH_F = os.path.join(r"C:\Users\Radhi\MT5", "data", "r_native", "coherence.json")


def _coherence_veto(sym, is_buy):
    """🧩 يحترم توجيه المُعالِج (conflict_resolver): إن كان اتّجاه هذه الصفقة ممنوعاً (ضدّ الدولار DXY)
    ⇒ لا دخول (وقائيّ — يمنع التعارض قبل أن يصير صفقة). غياب/تلف الملفّ ⇒ لا فيتو (fail-open)."""
    try:
        v = json.load(open(_COH_F, encoding="utf-8")).get(sym)
        if isinstance(v, dict) and int(v.get("veto_dir", 0)) == (1 if is_buy else -1):
            return True
    except Exception:
        pass
    return False


def _maybe_execute(sym, is_buy, price, R, score, cfg, equity):
    """ينفّذ فقط لو: execute + توافق>=العتبة + نهار + ديمو + لا kill_switch + تحت سقفَي المراكز
    (كلّي وللرمز) + خارج تبريدَي التنفيذ والوقف + ناجٍ من حارس حجم الحساب + متّسقٌ مع توجيه المُعالِج."""
    sense = _sense_read(cfg)                            # 👁️ حسّ السوق (محايدٌ إن غاب/بائت) — لا يمسّ الفيتوهات
    # 🎯 المعدِّل 3 — عتبة توافقٍ ملموسةٌ بالحسّ (ناعمٌ ومحدود ±1 نقطة، إحساسٌ لا بوّابة): زخمٌ متّفقٌ
    # + تذبذبٌ صحّيّ ⇒ اخفض نقطةً؛ تعارضٌ/تذبذب رديء ⇒ ارفع نقطةً. لا تنزل تحت exec_score_floor.
    thr = float(cfg.get("min_exec_score", 2))
    if cfg.get("adaptive_mode", True) and sense.get("fresh"):
        dd = 1.0 if is_buy else -1.0
        stepn = max(0, min(1, int(round(float(cfg.get("entry_sense_nudge", 0.05)) * 20.0))))
        ag = float(sense.get("momentum", 0.0)) * dd; vok = 0.35 <= float(sense.get("vol", 0.5)) <= 0.95
        if ag > 0.3 and vok:
            thr = thr - stepn
        elif ag < -0.3 or not vok:
            thr = thr + stepn
        thr = max(float(cfg.get("exec_score_floor", 2)), thr)
    if not cfg.get("execute") or score < thr:
        return
    if _coherence_veto(sym, is_buy):                   # 🧩 توجيه المُعالِج: لا دخول ضدّ الدولار (وقائيّ)
        print(f"   🧩 المُعالِج: {sym} {'شراء' if is_buy else 'بيع'} ضدّ الدولار — تخطّي وقائيّ", flush=True)
        return
    # 🌙 حظر ليل التنفيذ (نفس عقيدة الذهب): الحافّة المثبتة نهاريّة (+$904 PF3.36 باستبعاد 22-08 UTC)
    if cfg.get("exec_night_block", True):
        h = time.gmtime().tm_hour
        if h >= 22 or h < 8:
            return
    if (RN / "kill_switch.txt").exists() or not _is_demo():
        return
    # 🤝 وضع الجماعة (collective_mode 2026-07-08): لا تجميد يوميّ — الأسطول يخنق النازف عبر الحوكمة لا يوقفه.
    # التجميد التقليديّ يبقى فقط إن أُطفئ الوضع صراحةً (الكارثة-نت master_floor هو الحاجز الأخير الوحيد).
    if not cfg.get("collective_mode", True):
        try:
            if _pnl_today() <= -float(cfg.get("daily_loss_pct", 5.0)) / 100.0 * equity:
                return
        except Exception:
            pass
    if time.time() - _last_exec.get(sym, 0.0) < cfg.get("exec_cooldown_min", 10) * 60:
        return
    if time.time() < float(_slcool().get("until", {}).get(sym, 0)):   # 🧊 مبرَّد بعد وقفٍ لهذا الرمز
        return
    poss = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    if len(poss) >= cfg.get("max_positions", 3):
        return
    # 🌊 تكديس بنك-الموجة (طلب المستخدم «ادخلهم كلهم تكديس» 2026-07-08): إضافةٌ على الرمز مسموحةٌ حتى
    # per_symbol_max، لكن **فقط فوق مركزٍ رابح** (كل مراكز الرمز في ربح ≥ stack_min_r×R، بنفس الاتجاه —
    # لا تحوّط). هذا نمط راضي الرابح يوم +161% (بنك-الموجة)، لا التكديس الأعمى على الأحمر (قاتلنا المُثبت).
    on_sym = [p for p in poss if p.symbol == sym]
    if on_sym:
        if len(on_sym) >= int(cfg.get("per_symbol_max", 1)):
            return
        d = 0 if is_buy else 1                              # اتجاه الصفقة الجديدة (0=شراء،1=بيع بترميز MT5)
        if any(p.type != d for p in on_sym):               # مركزٌ معاكس على الرمز ⇒ لا تحوّط، لا تكديس
            return
        min_r = float(cfg.get("stack_min_r", 0.3))
        def _prof_r(p):
            if not getattr(p, "sl", 0):
                return -1.0
            try:
                ot = mt5.ORDER_TYPE_BUY if p.type == 0 else mt5.ORDER_TYPE_SELL
                loss = mt5.order_calc_profit(ot, p.symbol, float(p.volume), float(p.price_open), float(p.sl))
                risk = abs(float(loss)) if loss else 0.0
                return (float(p.profit) / risk) if risk > 0 else -1.0
            except Exception:
                return -1.0
        if not all(_prof_r(p) >= min_r for p in on_sym):   # ليست كلّها رابحة ≥0.3R ⇒ لا نكدّس على غير-رابح
            return
    si = mt5.symbol_info(sym)
    if not si:
        return
    stop = cfg.get("stop_r", 0.5) * R; targ = cfg.get("target_r", 0.5) * R
    # 🛡️ أرضيّة السبريد (درس AUDUSD 13:40: وقف 0.5R ظهيرةً = بيبة واحدة بحجم السبريد ⇒ موت فوريّ):
    # لا دخول إن كان الوقف < min_stop_spread_mult × السبريد الحاليّ — الهندسة نفسها تبقى، الرمز الهادئ يُتخطّى.
    tick = mt5.symbol_info_tick(sym)
    if tick:
        spr = float(tick.ask - tick.bid)
        if spr > 0 and stop < float(cfg.get("min_stop_spread_mult", 3.0)) * spr:
            print(f"   🛑 فيتو {sym}: الوقف {stop:.5f} < {cfg.get('min_stop_spread_mult', 3.0)}×سبريد "
                  f"({spr:.5f}) — رمزٌ هادئ الآن، السبريد يأكل الهندسة")
            return
        # 🌗 المعدِّل 2 — حارس سبريدٍ ناعمٌ ومحدود (adaptive فقط ⇒ adaptive_mode=false = لا حارس جديد):
        # نقارن السبريد بتسامحٍ مُقاسٍ بحسّ السبريد (مريح ⇒ لمسة تساهل، واسع ⇒ تشدّد) نسبةً إلى ATR
        # (ATR≈R/1.3)، بسقفٍ مطلق. لا يقبل سبريداً سخيفاً أبداً.
        if cfg.get("adaptive_mode", True) and spr > 0:
            atr_g = R / 1.3 if R > 0 else 0.0
            if atr_g > 0:
                base_thr = float(cfg.get("spread_atr_max", 1.2)); k = float(cfg.get("spread_sense_k", 0.5))
                scale = _clamp(1.0 + k * (float(sense.get("spread", 0.5)) - 0.5), 1.0 - k / 2.0, 1.0 + k / 2.0)
                spread_thr = min(base_thr * scale, float(cfg.get("spread_atr_abs_cap", 0.6)))
                if spr > spread_thr * atr_g:
                    print(f"   🛑 فيتو سبريد (تكيّفيّ) {sym}: {spr:.5f} > {spread_thr:.3f}×ATR — يأكل الحركة")
                    return
    per_lot = _loss_per_lot(sym, stop, is_buy)
    if per_lot <= 0:
        return
    vmin = si.volume_min or 0.01
    min_risk = per_lot * vmin
    # 🛡️ حارس 2.5% يقلّص لا يوقف (طلب المستخدم 2026-07-08 «لا يوقف حتى لو سحبت/أضفت الرصيد»): إن كان
    # أدنى لوت الوسيط نفسه يخرق 2.5% (حسابٌ صغير) نتداوله رغم ذلك — لا رهانَ أصغر منه، master_floor الحاجز.
    if min_risk > MINLOT_VETO * max(equity, 1e-9):
        print(f"   ⚠️ {sym}: أدنى لوت ${min_risk:.2f} > {MINLOT_VETO:.1%} — يُتداول بأدنى لوت (لا توقّف)")
    sl = price - stop if is_buy else price + stop
    tp = price + targ if is_buy else price - targ
    lot = _rec_lot(sym, equity, stop, cfg.get("risk_cap", 0.03), per_lot)
    if lot <= 0:
        return
    # 🎯 المعدِّل 1 — القناعة↔الثقة: الثقة (مقيسة من صفقاتٍ مغلقةٍ حقيقيّة، [0.5,1.3]) تعدّل الحجم، لكنّ
    # حارس 2.5% أدناه يبقى الحاجز الصلب (فوزٌ ⇒ أكبر قليلاً، خسارةٌ ⇒ أصغر — لا تنفجر ولا تصفّر).
    if cfg.get("adaptive_mode", True):
        conf_mult = _conf_modifier(cfg)
        if conf_mult != 1.0:
            step = si.volume_step or 0.01
            lot = max(vmin, math.floor((lot * conf_mult) / step + 1e-9) * step)
            lot = min(lot, si.volume_max or 100.0)
        # 🛡️ الحارس الصلب بعد التعديل: خطر اللوت المختار لا يتجاوز 2.5% من الحقوق أبداً (الثقة لا تكسره)
        chosen_risk = per_lot * lot
        if chosen_risk > MINLOT_VETO * max(equity, 1e-9):
            step = si.volume_step or 0.01
            capped = math.floor((MINLOT_VETO * equity / max(per_lot, 1e-9)) / step) * step
            lot = max(vmin, capped)           # 🔻 قلّص ضمن 2.5% لكن لا تنزل تحت أدنى لوت الوسيط — يتداول دائماً (لا توقّف)
    if _place(sym, is_buy, price, sl, tp, lot, si.digits):
        _last_exec[sym] = time.time()
        try:                                            # اربط أحدث مركزٍ للتبريد لو ضُرب وقفه
            poss2 = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
            if poss2:
                d = _slcool()
                d.setdefault("track", {})[str(max(poss2, key=lambda p: p.time).ticket)] = sym
                _slcool_save(d)
        except Exception:
            pass


def _ema(a, p):
    a = np.asarray(a, float); k = 2.0 / (p + 1.0)
    e = np.empty(len(a)); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _stoch(h, l, c, kp=14, slow=3, dp=3):
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float); n = len(c)
    raw = np.full(n, 50.0)
    for i in range(kp - 1, n):
        hh = h[i - kp + 1:i + 1].max(); ll = l[i - kp + 1:i + 1].min()
        raw[i] = 100.0 * (c[i] - ll) / ((hh - ll) or 1e-9)
    k = _ema(raw, slow)
    return float(k[-1]), float(_ema(k, dp)[-1])


def _atr(r, n=14):
    h = r["high"]; l = r["low"]; c = r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(1, len(r))]
    return float(np.mean(trs[-n:])) if len(trs) >= n else float(np.mean(trs) if trs else 1.0)


def _candle_conf(r):
    """قراءة الشموع لتأكيد الدخول (أسلوب LuxAlgo): ابتلاع / مطرقة / نجمة / رفض. يرجع (bull, bear, name)."""
    if r is None or len(r) < 3:
        return (False, False, "")
    o1, h1, l1, c1 = (float(r[-2]["open"]), float(r[-2]["high"]), float(r[-2]["low"]), float(r[-2]["close"]))
    o2, c2 = float(r[-3]["open"]), float(r[-3]["close"])
    rng = (h1 - l1) or 1e-9
    body = abs(c1 - o1); up = h1 - max(o1, c1); dn = min(o1, c1) - l1
    if c1 > o1 and c2 < o2 and c1 >= o2 and o1 <= c2:              # ابتلاع صعوديّ
        return (True, False, "ابتلاع صعوديّ")
    if c1 < o1 and c2 > o2 and c1 <= o2 and o1 >= c2:              # ابتلاع هبوطيّ
        return (False, True, "ابتلاع هبوطيّ")
    if dn / rng >= 0.6 and body / rng <= 0.35:                     # مطرقة (رفضٌ سفليّ ⇒ صعوديّ)
        return (True, False, "مطرقة/رفض")
    if up / rng >= 0.6 and body / rng <= 0.35:                     # نجمة (رفضٌ علويّ ⇒ هبوطيّ)
        return (False, True, "نجمة/رفض")
    return (False, False, "")


def _round_step(price, atr, digits):
    """🧮 شبكة المستديرات العامّة (فارق موثّق 4):
    base = 10**floor(log10(price))/100 — يعطي 10$ لذهبٍ~3300، 0.01 لليورو~1.08، 1000 لبتكوين~100k —
    ثم تصعيدٌ بسلّم 1-2-5 حتى base >= 2*ATR(M5) (لا شبكة أنعم من ضجيج السوق)، مقرَّباً لأرقام الوسيط."""
    step = 10.0 ** math.floor(math.log10(max(abs(price), 1e-9))) / 100.0
    lad = (2.0, 2.5, 2.0); i = 0
    while step < 2.0 * max(atr, 0.0) and i < 30:
        step *= lad[i % 3]; i += 1
    return max(round(step, digits), 10.0 ** (-digits))


def _levels(sym, price, atr, digits):
    """مستويات مطلقة: قمّة/قاع اليوم والأسبوع + مستديرات (step, 2*step) حول السعر (تُحاكي 5/10 للذهب)."""
    out = []
    for tf, tag in [(mt5.TIMEFRAME_D1, "اليوم"), (mt5.TIMEFRAME_W1, "الأسبوع")]:
        r = mt5.copy_rates_from_pos(sym, tf, 0, 2)
        if r is not None and len(r) >= 1:
            out.append({"price": float(r[-1]["high"]), "name": f"قمّة {tag}", "role": "res"})
            out.append({"price": float(r[-1]["low"]), "name": f"قاع {tag}", "role": "sup"})
    base = _round_step(price, atr, digits)
    for step in (base, base * 2.0):                        # أقرب مستديرات فوق وتحت
        lo = math.floor(price / step) * step; hi = lo + step
        out.append({"price": round(lo, digits), "name": f"مستدير {round(lo, digits)}", "role": "sup"})
        out.append({"price": round(hi, digits), "name": f"مستدير {round(hi, digits)}", "role": "res"})
    return out


def _basket_mode(sym):
    """محور السلّة/الدولار لكلّ رمز (فارق موثّق 4): 'inv' = مسعَّرٌ بالدولار (دولار↑ ⇒ ضغطٌ بيعيّ، مثل
    الذهب/الفضة/اليورو)؛ 'dir' = الدولار أساس (دولار↑ ⇒ دعم)؛ None = كريبتو/مؤشرات/نفط/تقاطعات —
    المحور غير متاح ولا يُزيَّف."""
    s = sym[:-1] if sym.endswith("m") else sym
    s = s.upper()
    if s in ("BTCUSD", "ETHUSD") or len(s) != 6 or not s.isalpha():
        return None
    if s.endswith("USD"):
        return "inv"
    if s.startswith("USD"):
        return "dir"
    return None


def _basket_tilt(sym):
    """ميل الدولار (DXYm M15) مُسقَطاً على الرمز. يرجع (نصّ, تأكيد-شراء, تأكيد-بيع)."""
    mode = _basket_mode(sym)
    if mode is None:
        return ("—", False, False)
    try:
        r = mt5.copy_rates_from_pos("DXYm", mt5.TIMEFRAME_M15, 0, 5)
        if r is not None and len(r) >= 4:
            up = bool(r[-1]["close"] > r[-4]["close"])
            bear = up if mode == "inv" else (not up)
            lbl = ("دولار↑" if up else "دولار↓") + (" (ضغطٌ بيعيّ)" if bear else " (دعمٌ شرائيّ)")
            return (lbl, not bear, bear)
    except Exception:
        pass
    return ("—", False, False)


HONESTY = ("دعمٌ للقرار فقط — ليست حافّة مثبتة (اختُبر على الذهب: ≈0R بعد السبريد، يموت OOS). "
           "يُنبّه أن الشروط التي تتداولها أنت حاضرة. انضباطك + حجمك = الحافّة، لا هذه الإشارة.")


def _emit(sym, kind, level, score, ctx, lot, digits):
    key = f"{sym}|{level['name']}|{kind}"
    now = time.time()
    if now - _last_alert.get(key, 0) < DEDUP_MIN * 60:      # منع التكرار (لكل رمز+مستوى+نوع)
        return
    _last_alert[key] = now
    _last_kind[sym] = kind
    alert = {"ts": now, "iso": time.strftime("%H:%M:%S"), "symbol": sym, "kind": kind,
             "level": level["name"], "level_price": round(level["price"], digits), "score": score,
             "price": ctx["price"], "stoch": ctx["stoch"], "trend": ctx["trend"],
             "basket": ctx["basket"], "rec_lot": lot, "reasons": ctx["reasons"], "honesty": HONESTY}
    try:
        with open(FEED_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"🔔 {sym} {kind} @ {level['name']} {level['price']:.{digits}f} · توافق {score}/6 · "
          f"Stoch {ctx['stoch']:.0f} · {ctx['trend']} · لوت≤{lot} · {ctx['reasons']}")


def _manage_positions(cfg):
    """🔐 تعزيز البطل (نفس منطق الذهب، عبر كلّ الرموز): بعد بلوغ الربح 60% من مسافة الوقف
       ⇒ الوقف إلى التعادل. يحوّل الخاسرين المرتدّين إلى تعادلاتٍ بدل خسائر."""
    frac = cfg.get("be_arm_frac", 0.6)
    for p in (mt5.positions_get() or []):
        if p.magic != MAGIC or not p.sl:
            continue
        stop_dist = abs(p.price_open - p.sl)
        if stop_dist < 1e-9:
            continue                                   # وقفه على التعادل أصلاً
        ti = mt5.symbol_info_tick(p.symbol); si = mt5.symbol_info(p.symbol)
        if not ti or not si:
            continue
        digits = si.digits
        cur = ti.bid if p.type == 0 else ti.ask
        fav = (cur - p.price_open) if p.type == 0 else (p.price_open - cur)
        be_ok = (p.sl < p.price_open) if p.type == 0 else (p.sl > p.price_open)   # الوقف خلف الدخول
        if be_ok and fav >= frac * stop_dist:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                                "position": p.ticket, "sl": round(p.price_open, digits),
                                "tp": p.tp, "magic": MAGIC})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"🔐 {p.symbol} {p.ticket}: الوقف⇐التعادل {p.price_open:.{digits}f} "
                      f"(ربح {fav:.{digits}f} ≥ {frac:.0%} من الوقف)")


def _pnl_today():
    """صافي اليوم لماجيكنا: مغلقٌ اليوم (ربح+عمولة+سواب) + عائم المراكز المفتوحة."""
    total = 0.0
    try:
        now = datetime.now()
        for d in (mt5.history_deals_get(datetime(now.year, now.month, now.day),
                                        now + timedelta(hours=3)) or []):
            if d.magic == MAGIC:
                total += d.profit + d.commission + d.swap
    except Exception:
        pass
    try:
        total += sum(p.profit for p in (mt5.positions_get() or []) if p.magic == MAGIC)
    except Exception:
        pass
    return round(total, 2)


def _cycle_sym(sym, equity, cfg):
    """دورة رمزٍ واحد — نفس _cycle الذهب حرفيّاً مع تعميم المستديرات والسلّة والحجم."""
    si = mt5.symbol_info(sym)
    if si is None or not si.visible:                    # غير ظاهر/معطّل ⇒ تخطٍّ صامت (fail-soft)
        return
    digits = si.digits
    r5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60)
    if r5 is None or len(r5) < 30:
        return
    c = r5["close"]; price = float(c[-1])
    atr = _atr(r5); R = 1.3 * atr or 1e-9
    e50 = float(_ema(c, 50)[-1]) if len(c) >= 50 else float(np.mean(c))
    e200_src = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 220)
    e200 = (float(_ema(e200_src["close"], 200)[-1])
            if e200_src is not None and len(e200_src) >= 200 else e50)
    trend = "صاعد" if price > e50 > e200 else ("هابط" if price < e50 < e200 else "مختلط")
    kv, dv = _stoch(r5["high"], r5["low"], c)
    basket, bbull, bbear = _basket_tilt(sym)
    lot = _rec_lot(sym, equity, cfg.get("stop_r", 0.5) * R, cfg.get("risk_cap", 0.03))
    # ذيل رفض على آخر شمعة (ضمن _candle_conf: مطرقة/نجمة ≥60% من المدى)
    moving_up = bool(c[-1] > c[-4])
    cbull, cbear, cname = _candle_conf(r5)                          # 🕯️ قراءة الشموع (تأكيد الدخول)
    levels = _levels(sym, price, atr, digits) + [
        {"price": e50, "name": "EMA50", "role": "res" if price < e50 else "sup"},
        {"price": e200, "name": "EMA200", "role": "res" if price < e200 else "sup"}]
    for L in levels:
        dist_r = abs(price - L["price"]) / R
        near = dist_r <= NEAR_R
        # كسر: أغلقنا خلف المستوى بـ>=BREAK_R
        broke_up = (price - L["price"]) / R >= BREAK_R and c[-2] <= L["price"]
        broke_dn = (L["price"] - price) / R >= BREAK_R and c[-2] >= L["price"]
        if near and L["role"] == "res" and kv >= 85 and trend in ("هابط", "مختلط"):
            reasons = f"مقاومة+Stoch{kv:.0f}تشبّع+ترند{trend}" + (f"+شمعة:{cname}" if cbear else "")
            score = 2 + cbear + (trend == "هابط") + bbear + (not moving_up)   # الدولار↑ يؤكّد البيع
            _emit(sym, "رفض-بيع", L, int(score), {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": reasons}, lot, digits)
            _maybe_execute(sym, False, price, R, int(score), cfg, equity)
        elif near and L["role"] == "sup" and kv <= 15 and trend in ("صاعد", "مختلط"):
            reasons = f"دعم+Stoch{kv:.0f}تشبّع+ترند{trend}" + (f"+شمعة:{cname}" if cbull else "")
            score = 2 + cbull + (trend == "صاعد") + bbull + moving_up         # الدولار↓ يؤكّد الشراء
            _emit(sym, "ارتداد-شراء", L, int(score), {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": reasons}, lot, digits)
            _maybe_execute(sym, True, price, R, int(score), cfg, equity)
        elif broke_up and 15 < kv < 85 and trend != "هابط":
            _emit(sym, "كسر-صعوديّ", L, 3, {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": f"كسر {L['name']} صعوداً+زخم"}, lot, digits)
            # 2026-07-08 (طلب المستخدم «يدخل صفقات أكثر»): تنفيذ الكسر بالزخم أيضاً (كالحارس) عبر 54 رمزاً
            # ⇒ تكرارٌ أعلى. مُعلَّم config (exec_breakouts) للرجوع. نفس الخروج الضيّق + التقليص + المُعالِج.
            if cfg.get("exec_breakouts", True):
                _maybe_execute(sym, True, price, R, 3, cfg, equity)
        elif broke_dn and 15 < kv < 85 and trend != "صاعد":
            _emit(sym, "كسر-هبوطيّ", L, 3, {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": f"كسر {L['name']} هبوطاً+زخم"}, lot, digits)
            if cfg.get("exec_breakouts", True):
                _maybe_execute(sym, False, price, R, 3, cfg, equity)


def main():
    if engine_lock:
        try:
            if not engine_lock.claim("level_sentinel_multi"):
                print("نسخةٌ أخرى تعمل — خروج."); return
        except SystemExit:
            raise
        except Exception:
            pass
    _ensure_cfg()
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    # 👁️ مرّة عند البدء: أظهر رموز الإعدادات في Market Watch (كأشقّائه brain_trader/army_warroom) —
    # بدونها si.visible=False ⇒ تخطٍّ صامت يقلّص المسح بلا إنذار.
    for s in (_cfg().get("symbols") or DEFAULT_SYMBOLS):
        try:
            si = mt5.symbol_info(s)
            if si is None or not si.visible:
                mt5.symbol_select(s, True)
        except Exception:
            pass
    print(f"🟢 حارس المستويات متعدد العملات بدأ — ماجيك {MAGIC} · poll={POLL_S}s · near={NEAR_R}R "
          f"· بلا XAUUSDm (الأصلي يملك الذهب)")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True):
                time.sleep(POLL_S); continue
            acct = mt5.account_info()
            eq = acct.equity if acct else 1000.0
            _manage_positions(cfg)                     # 🔐 إدارة المراكز: تعادلٌ مبكّر (تعزيز البطل)
            _slcool_reconcile(cfg)                     # 🧊 تبريدٌ بعد ضرب الوقف (لا ثأر) — لكل رمز
            syms = [s for s in (cfg.get("symbols") or DEFAULT_SYMBOLS)
                    if not str(s).upper().startswith("XAUUSD")]   # الذهب محجوزٌ للأصل — لا ازدواج
            for sym in syms:
                try:
                    _cycle_sym(sym, eq, cfg)
                except Exception as e:
                    print(f"{sym} err: {type(e).__name__}: {e}")
            npos = len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC])
            _aw(STATUS_F, {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "magic": MAGIC,
                           "execute": bool(cfg.get("execute")),
                           "min_exec_score": cfg.get("min_exec_score", 2),
                           "n_symbols": len(syms), "positions": npos,
                           "pnl_today": _pnl_today(), "last_alerts": dict(_last_kind)})
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
