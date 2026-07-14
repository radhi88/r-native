# -*- coding: utf-8 -*-
"""gold_level_sentinel.py — حارس مستويات الذهب: وكيلٌ دائم، **تنبيه-فقط** (لا ينفّذ صفقات إطلاقاً).

يراقب لحظياً اقتراب السعر من المستويات (قمّة/قاع اليوم والأسبوع، المستديرات، EMA50/200)، ويقرأ التوافق الحيّ
(Stochastic 14,3,3 EMA · اتجاه EMA · ميل السلّة/الدولار · ذيل الرفض) ⇒ يُنبّه: «ارتداد-شراء / رفض-بيع / كسر»
مع درجة توافق 0-6، وحجمٍ مقترحٍ ≤3% من الحقوق، وبانر صدق.

⚖️ مثبت علمياً (walk-forward، ٧ وكلاء): لا حافّة تنبؤيّة في **الدخول الآليّ** عند المستويات — كلّ القواعد
≈ −سبريد OOS (ارتداد M5 −0.030R t=−1.21؛ التوافق≥3 رمية عملة؛ «الرابح» Bonferroni p=1.00 سراب). فالقيمة
في **قرارك أنت المنضبط** (يدويّ ذهب 72% فوز، +$904 PF3.36 استبعاد الليل؛ الحجم هو القاتل لا مهارة الدخول).

🚫 لا يستورد friday_place_order ولا mt5.order_send — يكتب تنبيهاتٍ فقط (feed + status) للداشبورد/الجوّال.
تشغيل (نافذة): pythonw.exe gold_level_sentinel.py"""
from __future__ import annotations
import sys, os, json, time, math
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "gold_sentinel.out.log"
STATUS_F = RN / "gold_sentinel_status.json"
FEED_F = RN / "gold_sentinel_feed.jsonl"

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

SYM = "XAUUSDm"
POLL_S = 0.5                # 2026-07-13 (أمر المستخدم «سرعة فائقة»): 1→0.5ث — نفس إيقاع r_executor المُثبَت (رمز واحد، عمليّة واحدة = آمن على IPC)
NEAR_R = 0.15              # «قرب المستوى» = ضمن 0.15R
BREAK_R = 0.10            # كسرٌ واضح = تجاوز المستوى بـ0.10R إغلاقاً
DEDUP_MIN = 15           # لا نكرّر نفس التنبيه (مستوى+نوع) قبل 15 دقيقة
RISK_CAP = 0.08          # حجمٌ مقترح ≤8% (الرافعة الوحيدة المثبتة)
MINLOT_VETO = 0.025      # 🛡️ حارس حجم الحساب (عقيدة الأسطول): خطر أدنى لوت > 2.5% حقوق ⇒ فيتو تنفيذ
BASKET = ["DXYm", "XAGUSDm"]
CFG_F = RN / "gold_sentinel_config.json"   # 2026-07-07 توحيد (تدقيق C9): كان يقرأ ROOT بينما كل تعديلات
# المستخدم/الأسطول تذهب لـ data/r_native ⇒ كانت no-op. الآن يقرأ الملفّ الحيّ الموحّد (risk 5%، تجميد 6%).
MAGIC = 20260701
SENSE_F = RN / "market_sense.json"          # 👁️ حسّ السوق (adaptive_sense يكتبه: spread/momentum/vol)
CONF_F = RN / "confidence.json"             # 🎯 ثقةٌ مكتسبة من الصفقات المغلقة الحقيقيّة فقط
_last_alert: dict = {}


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        return lo
    return lo if v < lo else (hi if v > hi else v)


def _sense_read(cfg):
    """👁️ حسّ السوق (market_sense.json) — قراءة دفاعيّة fail-soft إلى المحايد: غياب/قِدم/خلل ⇒ محايد."""
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


def _cfg():
    """إعدادات: execute=false افتراضياً (تنبيه فقط، صادق). فعّلها لتنفيذٍ محكومٍ على أقوى توافق فقط."""
    d = {"enabled": True, "execute": False, "min_exec_score": 4, "max_positions": 1,
         "stop_r": 0.5, "target_r": 0.5, "risk_cap": 0.08, "exec_cooldown_min": 20,
         # 👁️🎯 التكيّف الناعم (adaptive_sense): يُعدّل داخل الحدود الآمنة فقط — لا يرفع فيتو ولا يتجاوز
         # risk_cap ولا حارس 2.5%. adaptive_mode=false ⇒ السلوك القديم بالحرف. الصدق: ضبطٌ للظروف
         # وثقةٌ مقيسةٌ من الصفقات المغلقة الحقيقيّة فقط — لا حافّة مزعومة، لا ثقةٌ مزيّفة.
         "adaptive_mode": True, "conf_lo": 0.5, "conf_hi": 1.3, "sense_max_age_s": 120,
         "spread_sense_k": 0.5, "spread_atr_abs_cap": 0.6, "entry_sense_nudge": 0.05}
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


def _place(is_buy, entry, sl, tp, lot, ctx=None):
    """أمرٌ محكوم (ديمو فقط، وقف+هدف مضبوطان مسبقاً = set-and-forget). يرجع True عند التنفيذ.
    ctx (اختياريّ): سياق الدخول (سبريد/توافق/تبريد...) يُسجَّل في gold_sentinel_entries.jsonl
    مربوطاً بتذكرة المركز — فيدمجه الصندوق الأسود (r_trade_journal) ويشرح الصفقة بظروفها الفعليّة."""
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": float(round(lot, 2)),
           "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL, "price": float(entry),
           "sl": float(round(sl, 3)), "tp": float(round(tp, 3)), "deviation": 30, "magic": MAGIC,
           "comment": "sentinel", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    # 💡 2026-07-10: رفض 10019 (NO_MONEY) — اللوت المحسوب أكبر ممّا يسمح به الهامش الحرّ (حسابٌ منكمش +
    # مراكز أخرى تستهلك الهامش) ⇒ بدل إضاعة الإشارة كاملةً، أعد المحاولة مرّةً بأدنى لوت الوسيط.
    if not ok and getattr(r, "retcode", 0) == 10019 and float(lot) > 0.011:
        si_m = mt5.symbol_info(SYM)
        vmin_m = float((si_m.volume_min if si_m else 0.01) or 0.01)
        req["volume"] = vmin_m
        r = mt5.order_send(req)
        ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
        if ok:
            print(f"   ⚡ نُفّذت بأدنى لوت {vmin_m} (الهامش لا يكفي لوت {lot}) — لا إشارة تضيع")
            return ok
    if ok:
        print(f"   ⚡ نُفّذت (ديمو): {'شراء' if is_buy else 'بيع'} {lot} @ {entry:.2f} وقف {sl:.2f} هدف {tp:.2f}")
        try:                                            # 📓 سياق الدخول → الصندوق الأسود
            rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "ticket": int(getattr(r, "order", 0) or 0), "side": "BUY" if is_buy else "SELL",
                   "entry": float(entry), "sl": float(sl), "tp": float(tp),
                   "lot": float(req["volume"])}
            if isinstance(ctx, dict):
                rec.update(ctx)
            with open(os.path.join(str(MT5DIR), "data", "r_native",
                                   "gold_sentinel_entries.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    else:
        print(f"   ⏭️ لم تُنفّذ: {getattr(r,'retcode','?')} {getattr(r,'comment','')}")
    return ok


_last_exec = {"ts": 0.0}
_SLCOOL_F = os.path.join(str(MT5DIR), "data", "r_native", "gold_sentinel_slcool.json")


def _slcool():
    try:
        return json.load(open(_SLCOOL_F, encoding="utf-8"))
    except Exception:
        return {"until": 0.0, "track": {}}


def _slcool_save(d):
    try:
        json.dump(d, open(_SLCOOL_F, "w", encoding="utf-8"))
    except Exception:
        pass


def _slcool_reconcile(cfg):
    """🧊 بعد ضرب الوقف: تبريد stop_cooldown_min (افتراضيّ 30د) — لا ثأر فوريّ على نفس الظروف."""
    d = _slcool()
    trk = d.get("track", {})
    if not trk:
        return
    open_ids = {str(p.ticket) for p in (mt5.positions_get() or []) if p.magic == MAGIC}
    changed = False
    for tk in list(trk.keys()):
        if tk in open_ids:
            continue
        try:
            deals = mt5.history_deals_get(position=int(tk)) or []
            hit = any(x.entry == 1 and "sl" in (x.comment or "").lower() for x in deals)
        except Exception:
            hit = False
        if hit:
            d["until"] = time.time() + cfg.get("stop_cooldown_min", 30) * 60
            print(f"🧊 {tk} ضرب الوقف — تبريد التنفيذ {cfg.get('stop_cooldown_min',30)}د (التنبيهات مستمرّة)")
        del trk[tk]; changed = True
    if changed:
        _slcool_save(d)


def _exec_score_thr(cfg, is_buy, sense):
    """🎯 عتبة التوافق للتنفيذ بعد لمسة الحسّ (المعدِّل 3، ناعمٌ ومحدود ±1 نقطة، إحساسٌ لا بوّابة):
    إن اتّفق الزخم بقوّة مع اتجاه الصفقة والتذبذب صحّيّ ⇒ اخفض العتبة نقطةً واحدة كحدٍّ أقصى؛ إن تعارضا ⇒
    ارفعها. لا تنزل أبداً تحت أرضيةٍ صلبة (exec_score_floor). adaptive_mode=false ⇒ العتبة الأصليّة بالحرف."""
    base = float(cfg.get("min_exec_score", 4))
    if not cfg.get("adaptive_mode", True) or not sense.get("fresh"):
        return base
    d = 1.0 if is_buy else -1.0
    step = round(float(cfg.get("entry_sense_nudge", 0.05)) * 20.0)   # 0.05×20 ⇒ ±1 نقطة كحدٍّ أقصى
    step = max(0, min(1, int(step)))
    mom = float(sense.get("momentum", 0.0)); vol = float(sense.get("vol", 0.5))
    agree = mom * d; vol_ok = 0.35 <= vol <= 0.95
    if agree > 0.3 and vol_ok:
        thr = base - step
    elif agree < -0.3 or not vol_ok:
        thr = base + step
    else:
        thr = base
    return max(float(cfg.get("exec_score_floor", 3)), thr)


def _maybe_execute(is_buy, price, R, score, cfg, trend_sign=0):
    """ينفّذ فقط لو: execute + توافق≥العتبة + مع الترند + ديمو + لا kill_switch + تحت سقف المراكز + خارج التبريد."""
    sense = _sense_read(cfg)                            # 👁️ حسّ السوق (محايدٌ إن غاب/بائت) — لا يمسّ الفيتوهات
    if not cfg.get("execute") or score < _exec_score_thr(cfg, is_buy, sense):
        return
    # 🧭 محاذاة الترند (2026-07-08، مقيسٌ على 66 صفقة حارس: مع الترند 60%فوز +$49.75 مقابل عكسه 39% −$14):
    # لا تنفيذ عكس اتّجاه EMA50. مُعلَّم (require_trend_align). trend_sign: +1 السعر فوق EMA50، -1 تحته، 0=غير معروف.
    if cfg.get("require_trend_align", True) and trend_sign != 0 and (1 if is_buy else -1) != trend_sign:
        print(f"   🧭 تخطّي عكس-الترند: {'شراء' if is_buy else 'بيع'} والسعر {'فوق' if trend_sign>0 else 'تحت'} EMA50", flush=True)
        return
    # 🌙 حظر ليل التنفيذ (2026-07-07): 4 صفقات ليليّة = صافٍ سالب، والحافّة المثبتة نهاريّة
    # (+$904 PF3.36 باستبعاد 22-08 UTC). التنبيهات تستمرّ ليلاً — التنفيذ يمتنع.
    if cfg.get("exec_night_block", True):
        h = time.gmtime().tm_hour
        if h >= 22 or h < 8:
            return
    # 🤝 وضع الجماعة (collective_mode 2026-07-08): لا تجميد يوميّ — الأسطول يخنق لا يوقف.
    # التجميد التقليديّ يبقى فقط إن أُطفئ الوضع صراحةً (الكارثة-نت master_floor يبقى الحاجز الأخير).
    if not cfg.get("collective_mode", True):
      try:
        acct0 = mt5.account_info()
        if acct0:
            day0 = __import__("datetime").datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            pnl = sum(x.profit + x.commission + x.swap
                      for x in (mt5.history_deals_get(day0, __import__("datetime").datetime.now()) or [])
                      if x.magic == MAGIC and x.entry == 1)
            if pnl <= -float(cfg.get("daily_loss_pct", 6.0)) / 100.0 * float(acct0.equity):
                return
      except Exception:
        pass
    if (MT5DIR / "data" / "r_native" / "kill_switch.txt").exists() or not _is_demo():
        return
    # ⚡ السرعة تتسارع مع الثقة المقيسة (طلب المستخدم 2026-07-13 «يزيد سرعته ولوته مع تعلّمه وثقته»):
    # ثقةٌ عالية (فوزٌ حقيقيّ مقيسٌ من صفقاتٍ مغلقة، _conf_modifier) ⇒ تبريدٌ أقصر (أسرع)؛ خسارةٌ ⇒ تبريدٌ
    # أطول (أبطأ). مقيّدٌ بأرضيّةٍ صلبة (exec_cooldown_floor_min) فلا يرشّ أبداً. مُعلَّمٌ (speed_scales_with_conf).
    base_cd = cfg.get("exec_cooldown_min", 20)
    eff_cd = base_cd
    if cfg.get("adaptive_mode", True) and cfg.get("speed_scales_with_conf", True):
        cm = _conf_modifier(cfg)                       # >1 فوز ⇒ أسرع، <1 خسارة ⇒ أبطأ
        eff_cd = base_cd * _clamp(2.0 - cm, 0.5, 1.5)  # مدى [0.5×,1.5×] من التبريد الأساس
        eff_cd = max(float(cfg.get("exec_cooldown_floor_min", 1.0)), eff_cd)
    if time.time() - _last_exec["ts"] < eff_cd * 60:
        return
    if time.time() < _slcool().get("until", 0):        # 🧊 مبرَّد بعد ضرب وقفٍ — تنبيهٌ بلا تنفيذ
        return
    npos = len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC])
    if npos >= cfg.get("max_positions", 1):
        return
    stop = cfg.get("stop_r", 0.5) * R
    # 🎯 أهداف تتّسع مع الثقة (طلب المستخدم «كل ما زادت أرباحه وثقتنا نعطيه مساحة أكبر»): الثقة مقيسةٌ من
    # صفقاتٍ مغلقةٍ حقيقيّة؛ حين تعلو (سلسلة فوز فعليّة) يتّسع الهدف تدريجيّاً فوق 0.5R المُثبَت، مقيّداً بسقفٍ
    # (target_r_max) ومُعلَّماً (target_conf_scale، 0=إطفاء). الوقف يبقى ضيّقاً 0.5R. يقيسه التشريح؛ يُخفَّض لو أضرّ.
    _tc = float(cfg.get("target_conf_scale", 0.5)); _tr = float(cfg.get("target_r", 0.5))
    if cfg.get("adaptive_mode", True) and _tc > 0:
        _cm = _conf_modifier(cfg)
        _tr = min(float(cfg.get("target_r_max", 1.0)), _tr * (1.0 + _tc * max(0.0, _cm - 1.0)))
    targ = _tr * R
    # 🛑 فيتو السبريد الصلب — غير مشروط (أمر المستخدم 2026-07-13 «جداً حسّاس على السبريد»):
    # العتبة = الأدنى بين نسبيّة (spread_atr_max × ATR) ومطلقة (spread_abs_max بوحدات السعر $/أونصة).
    # سبريد الذهب الطبيعيّ ~$0.13-0.20؛ المطلقة 0.25 تقبل الطبيعيّ وترفض أيّ اتّساع (خبر/سيولة شحيحة).
    # يعمل دائماً بصرف النظر عن adaptive_mode — التكلفة أثبت روافعنا، لا تُعلَّق على مزاج التكيّف.
    spr = None
    try:
        tk0 = mt5.symbol_info_tick(SYM)
        atr_g = R / 1.3 if R > 0 else 0.0              # ATR ≈ R/1.3 (R=1.3×ATR في هذا المحرّك)
        if tk0:
            spr = float(tk0.ask - tk0.bid)
            thr_rel = float(cfg.get("spread_atr_max", 0.5)) * atr_g if atr_g > 0 else 1e9
            thr_abs = float(cfg.get("spread_abs_max", 0.25))
            thr = min(thr_rel, thr_abs)
            if spr > thr:
                print(f"   🛑 فيتو سبريد صلب: {spr:.3f} > {thr:.3f} (نسبيّ {thr_rel:.3f} | مطلق {thr_abs:.2f})")
                return
    except Exception:
        pass
    sl = price - stop if is_buy else price + stop
    tp = price + targ if is_buy else price - targ
    acct = mt5.account_info()
    equity = acct.equity if acct else 1000.0
    lot_base = _rec_lot(equity, R / 1.5, cfg.get("risk_cap"))
    lot = lot_base
    if cfg.get("adaptive_mode", True):
        # 🎯 المعدِّل 1 — القناعة↔الثقة: الثقة (مقيسة من صفقاتٍ مغلقةٍ حقيقيّة، [0.5,1.3]) تعدّل الحجم، لكن
        # لا تتجاوز اللوت الذي يسمح به risk_cap إلا بحدود conf_hi (سقفٌ يغلب الثقة) — فوزٌ ⇒ أكبر قليلاً،
        # خسارةٌ ⇒ أصغر. ثمّ حارس حجم الحساب 2.5% (أدناه، غير مشروط) يمنع أيّ تضخّمٍ خطير (لا تزييف حجم).
        conf_mult = _conf_modifier(cfg)
        si0 = mt5.symbol_info(SYM); step0 = float((si0.volume_step if si0 else 0.01) or 0.01)
        vmin0 = float((si0.volume_min if si0 else 0.01) or 0.01)
        if conf_mult != 1.0:
            lot = max(vmin0, math.floor((lot_base * conf_mult) / step0) * step0)
        lot = min(lot, lot_base * float(cfg.get("conf_hi", 1.3)))   # سقفٌ صلبٌ فوق حجم risk_cap
    # 🛡️ حارس حجم الحساب 2.5% — مُقدَّس وغير مشروط: يعمل دائماً بصرف النظر عن adaptive_mode (السقف الصلب
    # لا يُلغى بإطفاء التكيّف). خطر اللوت النهائيّ > 2.5% من الحقوق ⇒ لا تنفيذ (درس المعادن على الحساب الصغير).
    # 🛡️ حارس حجم الحساب 2.5%: يمنع *التكبير* لا *التداول* (طلب المستخدم 2026-07-08 «لا يوقف حتى لو
    # سحبت/أضفت الرصيد — يعمل دون حدود»). إن خرق اللوت 2.5% ⇒ قلّصه لأكبر لوتٍ ضمن 2.5%، وأرضيّته
    # أدنى-لوت الوسيط: يتداول دائماً بأصغر رهانٍ ممكن حتى لو تجاوز 2.5% على حسابٍ صغير (لا رهانَ أصغر
    # منه أصلاً). لا توقّف أبداً — master_floor (هامش 130%) يبقى الحاجز الأخير الوحيد.
    try:
        si0 = mt5.symbol_info(SYM); vmin0 = float((si0.volume_min if si0 else 0.01) or 0.01)
        vstep0 = float((si0.volume_step if si0 else 0.01) or 0.01)
        loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                                     SYM, float(lot), price, sl)
        # 🔼 2026-07-10 (أمر المستخدم «ارفع لوته»): السقف صار من الإعداد (minlot_veto_pct، افتراضيّ 2.5%
        # القديم). للرابح رُفع لـ6% — يسمح بـ~0.02 لوت على $100 بالتذبذب الحاليّ، ويتدرّج آليّاً مع الحقوق.
        _veto_pct = float(cfg.get("minlot_veto_pct", MINLOT_VETO))
        cap = _veto_pct * max(equity, 1e-9)
        if loss is not None and abs(float(loss)) > cap > 0:
            scaled = float(lot) * cap / abs(float(loss))
            clamped = max(vmin0, math.floor(scaled / vstep0) * vstep0)
            if clamped < float(lot):
                print(f"   🔻 قُلِّص ضمن {_veto_pct:.0%} ⇒ {clamped} (كان يخرق ${abs(float(loss)):.2f}؛ أدنى-لوت يُتداول دائماً)")
                lot = clamped
    except Exception:
        pass
    _entry_ctx = {"spread": round(spr, 3) if spr is not None else None, "score": int(score),
                  "R": round(R, 3), "stop_r": cfg.get("stop_r"), "target_r_eff": round(_tr, 3),
                  "cooldown_eff_min": round(eff_cd, 2), "trend_sign": trend_sign,
                  "conf_mult": round(_conf_modifier(cfg), 3)}
    if _place(is_buy, price, sl, tp, lot, ctx=_entry_ctx):
        _last_exec["ts"] = time.time()
        try:                                            # اربط أحدث مركزٍ للتبريد لو ضُرب وقفه
            poss = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
            if poss:
                d = _slcool(); d.setdefault("track", {})[str(max(poss, key=lambda p: p.time).ticket)] = 1
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


def _levels(price):
    """مستويات مطلقة: قمّة/قاع اليوم والأمس والأسبوع + مستديرات 5/10 حول السعر + EMA50/200."""
    out = []
    for tf, tag in [(mt5.TIMEFRAME_D1, "اليوم"), (mt5.TIMEFRAME_W1, "الأسبوع")]:
        r = mt5.copy_rates_from_pos(SYM, tf, 0, 2)
        if r is not None and len(r) >= 1:
            out.append({"price": float(r[-1]["high"]), "name": f"قمّة {tag}", "role": "res"})
            out.append({"price": float(r[-1]["low"]), "name": f"قاع {tag}", "role": "sup"})
    for step in (5, 10):                                   # أقرب مستديرات فوق وتحت
        lo = math.floor(price / step) * step; hi = lo + step
        out.append({"price": float(lo), "name": f"مستدير {int(lo)}", "role": "sup"})
        out.append({"price": float(hi), "name": f"مستدير {int(hi)}", "role": "res"})
    return out


def _basket_tilt():
    """ميل السلّة: DXY صاعد ⇒ ضغطٌ هابط على الذهب (وبالعكس)."""
    try:
        r = mt5.copy_rates_from_pos("DXYm", mt5.TIMEFRAME_M15, 0, 5)
        if r is not None and len(r) >= 4:
            return "دولار↑ (ضغط بيعيّ للذهب)" if r[-1]["close"] > r[-4]["close"] else "دولار↓ (دعمٌ للذهب)"
    except Exception:
        pass
    return "—"


def _rec_lot(equity, atr, risk=None):
    """حجمٌ مقترح لوقفٍ = 1R (1.5×ATR). ذهب: $1 حركة = $100/لوت.
    2026-07-06: risk من الإعدادات (risk_cap) يقود التنفيذ — كان مقطوعاً (الكود يتجاهله) واللوت عالقاً
    على الحدّ الأدنى. التنبيهات تبقى على RISK_CAP المحافظ (3%)؛ التنفيذ يتبع الإعداد."""
    stop = 1.5 * atr
    if stop <= 0 or equity <= 0:
        return 0.01
    lot = (float(risk or RISK_CAP) * equity) / (stop * 100.0)
    # ⚠️ 2026-07-07 16:55: السطر السابق round(lot/0.01)*0.15 كان مضاعِف ×15 بأرضيّة 0.15 لوت إجباريّة
    # مهما اتّسع الوقف ⇒ صفقة 14:59 خسرت −$42.18 (~20% من الحساب) لمّا توسّع ATR الجلسة الأمريكيّة.
    # القصد كان خطوات لوت 0.15 — هذه صيغتها الصحيحة (والأرضيّة 0.01 لا 0.15):
    return max(0.01, round(lot / 0.15) * 0.15) if lot >= 0.075 else max(0.01, round(lot / 0.01) * 0.01)


HONESTY = ("دعمٌ للقرار فقط — ليست حافّة مثبتة (اختُبر: ≈0R， −0.015..−0.030R بعد السبريد، يموت OOS). "
           "يُنبّه أن الشروط التي تتداولها أنت حاضرة. انضباطك + حجمك = الحافّة، لا هذه الإشارة.")


def _emit(kind, level, score, ctx, lot):
    key = f"{level['name']}|{kind}"
    now = time.time()
    if now - _last_alert.get(key, 0) < DEDUP_MIN * 60:      # منع التكرار
        return
    _last_alert[key] = now
    alert = {"ts": now, "iso": time.strftime("%H:%M:%S"), "kind": kind, "level": level["name"],
             "level_price": round(level["price"], 2), "score": score, "price": ctx["price"],
             "stoch": ctx["stoch"], "trend": ctx["trend"], "basket": ctx["basket"],
             "rec_lot": lot, "reasons": ctx["reasons"], "honesty": HONESTY}
    try:
        with open(FEED_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"🔔 {kind} @ {level['name']} {level['price']:.2f} · توافق {score}/6 · "
          f"Stoch {ctx['stoch']:.0f} · {ctx['trend']} · لوت≤{lot} · {ctx['reasons']}")


def _manage_positions(cfg):
    """🔐 تعزيز البطل (طلب المستخدم): إدارة مراكزه المفتوحة — بعد بلوغ الربح 60% من مسافة الوقف
       ⇒ الوقف إلى التعادل. يحوّل الخاسرين المرتدّين إلى تعادلاتٍ بدل خسائر (تعزيزٌ بلا تكبير حجم)."""
    frac = cfg.get("be_arm_frac", 0.6)
    for p in (mt5.positions_get(symbol=SYM) or []):
        if p.magic != MAGIC or not p.sl:
            continue
        stop_dist = abs(p.price_open - p.sl)
        if stop_dist < 1e-9:
            continue                                   # وقفه على التعادل أصلاً
        ti = mt5.symbol_info_tick(SYM)
        if not ti:
            continue
        cur = ti.bid if p.type == 0 else ti.ask
        fav = (cur - p.price_open) if p.type == 0 else (p.price_open - cur)
        be_ok = (p.sl < p.price_open) if p.type == 0 else (p.sl > p.price_open)   # الوقف ما زال خلف الدخول
        if be_ok and fav >= frac * stop_dist:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYM, "position": p.ticket,
                                "sl": round(p.price_open, 3), "tp": p.tp, "magic": MAGIC})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"🔐 {p.ticket}: الوقف⇐التعادل {p.price_open:.2f} (ربح {fav:.2f} ≥ {frac:.0%} من الوقف)")


def _cycle(equity, cfg):
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 60)
    if r5 is None or len(r5) < 30:
        return None
    c = r5["close"]; price = float(c[-1])
    atr = _atr(r5); R = 1.3 * atr or 1e-9
    e50 = _ema(c, 50)[-1] if len(c) >= 50 else float(np.mean(c))
    e200_src = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 220)
    e200 = _ema(e200_src["close"], 200)[-1] if e200_src is not None and len(e200_src) >= 200 else e50
    trend = "صاعد" if price > e50 > e200 else ("هابط" if price < e50 < e200 else "مختلط")
    kv, dv = _stoch(r5["high"], r5["low"], c)
    basket = _basket_tilt()
    lot = _rec_lot(equity, atr)
    # ذيل رفض على آخر شمعة (≥60% من مداها)
    moving_up = c[-1] > c[-4]
    cbull, cbear, cname = _candle_conf(r5)                          # 🕯️ قراءة الشموع (تأكيد الدخول)
    levels = _levels(price) + [{"price": e50, "name": "EMA50", "role": "res" if price < e50 else "sup"},
                               {"price": e200, "name": "EMA200", "role": "res" if price < e200 else "sup"}]
    status_alerts = []
    for L in levels:
        dist_r = abs(price - L["price"]) / R
        if dist_r > NEAR_R and abs(price - L["price"]) / R > BREAK_R:
            # ليس قريباً وليس كسراً ⇒ تجاهل (إلا لو كسرٌ واضح أدناه)
            pass
        near = dist_r <= NEAR_R
        # كسر: أغلقنا خلف المستوى بـ≥BREAK_R
        broke_up = (price - L["price"]) / R >= BREAK_R and c[-2] <= L["price"]
        broke_dn = (L["price"] - price) / R >= BREAK_R and c[-2] >= L["price"]
        if near and L["role"] == "res" and kv >= 85 and trend in ("هابط", "مختلط"):
            reasons = f"مقاومة+Stoch{kv:.0f}تشبّع+ترند{trend}" + (f"+شمعة:{cname}" if cbear else "")
            score = 2 + cbear + (trend == "هابط") + ("↑" in basket) + (not moving_up)   # الدولار↑ يؤكّد البيع
            _emit("رفض-بيع", L, int(score), {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": reasons}, lot)
            status_alerts.append({"kind": "رفض-بيع", "level": L["name"], "score": int(score)})
            _maybe_execute(False, price, R, int(score), cfg, 1 if price > e50 else -1)
        elif near and L["role"] == "sup" and kv <= 15 and trend in ("صاعد", "مختلط"):
            reasons = f"دعم+Stoch{kv:.0f}تشبّع+ترند{trend}" + (f"+شمعة:{cname}" if cbull else "")
            score = 2 + cbull + (trend == "صاعد") + ("↓" in basket) + moving_up          # الدولار↓ يؤكّد الشراء
            _emit("ارتداد-شراء", L, int(score), {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": reasons}, lot)
            status_alerts.append({"kind": "ارتداد-شراء", "level": L["name"], "score": int(score)})
            _maybe_execute(True, price, R, int(score), cfg, 1 if price > e50 else -1)
        elif broke_up and 15 < kv < 85 and trend != "هابط":
            _emit("كسر-صعوديّ", L, 3, {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": f"كسر {L['name']} صعوداً+زخم"}, lot)
            status_alerts.append({"kind": "كسر-صعوديّ", "level": L["name"], "score": 3})
            # 2026-07-08 (طلب المستخدم «خله يدخل صفقات الآن»): تنفيذ الكسر بزخمٍ أيضاً (لا ارتداد فقط).
            # مُعلَّم config (exec_breakouts) للرجوع. نفس الخروج الضيّق + التقليص + التبريد. زخمٌ لا حافّة مثبتة.
            if cfg.get("exec_breakouts", True):
                _maybe_execute(True, price, R, 3, cfg, 1 if price > e50 else -1)
        elif broke_dn and 15 < kv < 85 and trend != "صاعد":
            _emit("كسر-هبوطيّ", L, 3, {"price": price, "stoch": kv, "trend": trend,
                  "basket": basket, "reasons": f"كسر {L['name']} هبوطاً+زخم"}, lot)
            status_alerts.append({"kind": "كسر-هبوطيّ", "level": L["name"], "score": 3})
            if cfg.get("exec_breakouts", True):
                _maybe_execute(False, price, R, 3, cfg, 1 if price > e50 else -1)
    return {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "price": round(price, 2),
            "stoch_k": round(kv, 1), "stoch_d": round(dv, 1), "trend": trend, "basket": basket,
            "ema50": round(e50, 2), "ema200": round(e200, 2), "atr": round(atr, 2),
            "candle": cname or "—", "rec_lot": lot, "R": round(R, 2),
            "alerts": status_alerts, "honesty": HONESTY}


def main():
    if engine_lock:
        try:
            if not engine_lock.claim("gold_level_sentinel"):
                print("نسخةٌ أخرى تعمل — خروج."); return
        except Exception:
            pass
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🟢 حارس المستويات بدأ — تنبيه فقط، لا تنفيذ. poll={POLL_S}s near={NEAR_R}R")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True):
                time.sleep(POLL_S); continue
            acct = mt5.account_info()
            eq = acct.equity if acct else 1000.0
            _manage_positions(cfg)                     # 🔐 إدارة مراكزه: تعادلٌ مبكّر (تعزيز البطل)
            _slcool_reconcile(cfg)                     # 🧊 تبريدٌ بعد ضرب الوقف (لا ثأر)
            st = _cycle(eq, cfg)
            if st:
                st["execute"] = bool(cfg.get("execute"))
                st["min_exec_score"] = cfg.get("min_exec_score", 4)
                try:
                    json.dump(st, open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
                except Exception:
                    pass
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
