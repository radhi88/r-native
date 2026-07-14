# -*- coding: utf-8 -*-
"""adaptive_sense.py — 👁️🫀 عيون وإحساس + عضويّة القناعة↔الثقة (2026-07-08 · لا ماجيك · لا يتاجر أبداً).

طلب المستخدم حرفيّاً: «حط لهم عيون واحساس دون تثبيتها بالقواعد» + «القناعة مربطة بالثقة وترتفع او
تنخفض بعد دخوله بالصفقة وضربه للاهداف». هذا المحرّك يُلبّي الطلبين بلا كذبٍ ولا حافّةٍ مُفترضة:

⚖️ الصدق هو المُنتَج. أعمق ما قِسناه: هذه النماذج لا تتنبّأ بالسوق (وجهُ قطعةٍ نقديّة خارج العيّنة).
لذلك لا ادّعاء حافّة، ولا ثقة مُفبركة. الثقة تُحسَب حصراً من نتائج صفقاتٍ مُغلقةٍ حقيقيّة — ترتفع حين
يضرب الأهداف، وتهبط حين يضرب الوقف — لا شيء آخر. التكيّف حقيقيّ (الإحساس يتنفّس مع الظروف، والثقة
تتعلّم من الواقع) لكنّه ناعمٌ ومحدود: يُعدّل داخل الحدود الآمنة فقط، لا يُلغي فيتو، لا يتجاوز سقفاً
صلباً، لا يُصفّر حجماً ولا يُفجّره.

مُخرَجان (كلّ ~2-3ث):
  1) 👁️ الإحساس بالسوق (متّصل، ليس قواعد) — لكلّ رمزٍ في القائمة يُحسَب إحساسٌ مُطبَّع في [0,1]
     (لا عتبات ثنائيّة): spread_sense (السبريد ÷ وسيطه الأخير = «السبريد يختار اللحظة»)، vol_sense
     (ATR M1 ÷ ATR M15 مئويّاً)، momentum_sense (ميل EMA مُطبَّعاً بـATR)، energy_sense (نبض التكّات
     ÷ وسيطه). أحاسيسٌ تشعر بها المحرّكات، لا قواعد تُقيّدها ⇒ market_sense.json.
  2) 🫀 الثقة من النتائج (حلقة القناعة↔الثقة) — لكلّ محرّكٍ من ماجيكاتنا تُحسَب ثقةٌ حيّة في [0,1]
     كـEWMA (نصف-عمر ~15 صفقة) لنتائج R الأخيرة: تصعد بضرب الهدف وتهبط بضرب الوقف — تماماً كما طلب.
     ثمّ تُخطَّط الثقة إلى مُعدِّل قناعة/حجم محدود في [0.5, 1.3] (لا صفر، لا انفجار) ⇒ confidence.json.

🔒 مُقدَّس لا يُضعَّف أبداً (هذا المحرّك لا يلمس أيّاً منها — يقرأ فقط ويكتب مُعدِّلاتٍ ناعمة):
  master_floor · مسارا kill_switch · حارس Trial/Demo · السقوف الصلبة للمخاطرة · حارس 2.5% لأدنى لوت ·
  خنق العقل الجمعيّ. المُعدِّلات المكتوبة هنا ناعمةٌ ومحدودةٌ [0.5,1.3]: تُعايِر داخل الآمن، لا تنزعه.

قراءة فقط تماماً: لا order_send، لا مسار أوامر، لا ماجيك. windowless. قفل engine_lock "adaptive_sense".
"""
import os, sys, json, time, math
from collections import deque, defaultdict
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "adaptive_sense.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("adaptive_sense")
except SystemExit:
    raise
except Exception:
    pass

CFG_F = os.path.join(_RN, "adaptive_sense_config.json")
SENSE_F = os.path.join(_RN, "market_sense.json")
CONF_F = os.path.join(_RN, "confidence.json")
STATUS_F = os.path.join(_RN, "adaptive_sense_status.json")
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

# ماجيكات فرقنا (المستخدم سمّاها) — للثقة من النتائج فقط. هذا المحرّك لا ماجيك له ولا يتاجر.
ENGINES = {
    20260701: "الحارس", 20260706: "R Core", 20260707: "قنّاص",
    20260709: "حارس العملات", 20260703: "محاكي راضي", 20260631: "يوتيوب",
}

# 🔒 حدودٌ صلبة على المُعدِّل — مُدمجة عمداً (ليست في الإعدادات كي لا تُوسَّع): المُعدِّل ناعمٌ ومحدود
# دائماً في [0.5, 1.3]. لا يُصفّر حجماً (≥0.5) ولا يُفجّره (≤1.3). هذه ليست حافّة — إعادة معايرةٍ صادقة.
MOD_MIN, MOD_MAX = 0.5, 1.3
# نصف-عمر الثقة (بالصفقات): وزنٌ يتضاءل هندسيّاً — أحدثُ ~15 صفقة تحكم الثقة.
CONF_HALFLIFE = 15.0
# مقياس R: نقصّ العائد لكلّ صفقة إلى ±R_CLIP كي لا تُفجّر صفقةٌ شاذّة الثقة (صدقٌ لا حساسيّة مفرطة).
R_CLIP = 3.0

# نوافذ متدحرجة للإحساس (لكلّ رمز) — عيّنات لا عتبات: نقيس السبريد/الطاقة نسبةً لعادتهما الأخيرة.
_SPREAD_HIST = defaultdict(lambda: deque(maxlen=200))   # آخر ~200 عيّنة سبريد لكلّ رمز
_TICKRATE_HIST = defaultdict(lambda: deque(maxlen=200))  # آخر ~200 عيّنة معدّل تكّات لكلّ رمز
_LAST_TICK = {}   # sym -> (last_tick_time_epoch, last_sample_wall) لاشتقاق معدّل التكّات

G = {"status_ts": 0.0, "conf_cache": {}, "conf_cache_ts": 0.0}


def _cfg():
    d = {
        "enabled": True,
        "symbols": ["XAUUSDm", "BTCUSDm", "ETHUSDm", "US30m", "US500m", "USTECm",
                    "USOILm", "EURUSDm", "GBPUSDm", "USDJPYm", "XAGUSDm"],
        "loop_s": 2.5,                 # نبض 2-3ث كما طُلب
        "conf_history_days": 7,        # نافذة سحب الصفقات المُغلقة للثقة
        "conf_refresh_s": 20.0,        # لا نُثقل التاريخ كلّ دورة — نُحدّث الثقة كل ~20ث
        "conf_halflife": CONF_HALFLIFE,
        "ema_period": 20,              # لميل الزخم على M1
        "min_spread_samples": 20,      # قبل نضج تاريخ السبريد نُرجِع 0.5 (محايد، لا نكذب دقّة)
        "_note": "👁️🫀 عيون وإحساس + ثقة من النتائج. قراءة فقط، لا ماجيك، لا تداول. المُعدِّل ناعم "
                 "ومحدود [0.5,1.3] — يُعايِر داخل الآمن ولا يلمس أيّ فيتو/سقف/أرضيّة/قفل مُقدَّس.",
    }
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"
            json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _atomic_write(path, obj):
    """كتابة ذرّيّة (tmp ثمّ replace) — لا يقرأ قارئٌ ملفّاً نصفَ مكتوب."""
    try:
        t = path + ".tmp"
        json.dump(obj, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, path)
        return True
    except Exception:
        return False


def _pctile(hist, x):
    """موقع x المئويّ ضمن التاريخ (0..1). عيّنةٌ حيّة نسبةً لعادتها — لا عتبة ثابتة."""
    if not hist:
        return 0.5
    n = len(hist)
    below = sum(1 for v in hist if v < x)
    equal = sum(1 for v in hist if v == x)
    return (below + 0.5 * equal) / n


def _atr(sym, tf, n=14):
    """ATR بسيط (متوسّط المدى الحقيقيّ) — fail-soft إلى None (غيابه لا يُعطّل الحلقة)."""
    try:
        r = mt5.copy_rates_from_pos(sym, tf, 1, n + 1)
        if r is None or len(r) < n + 1:
            return None
        trs = []
        for i in range(1, len(r)):
            hi = float(r[i]["high"]); lo = float(r[i]["low"]); pc = float(r[i - 1]["close"])
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        m = sum(trs[-n:]) / n
        return m if m > 0 else None
    except Exception:
        return None


def _ema_slope_signed(sym, period, atr_m1):
    """ميل EMA على M1 لآخر شمعتين، مُطبَّعاً بـATR(M1) ⇒ إشارة زخمٍ موقّعة في [-1,1]:
    0 = محايد، >0 صعوديّ، <0 هبوطيّ. مقياسٌ لا تنبّؤ (الزخم قد يستمرّ أو ينعكس). fail-soft ⇒ 0.0."""
    try:
        if not atr_m1 or atr_m1 <= 0:
            return 0.0
        need = period + 3
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, need + 1)
        if r is None or len(r) < need:
            return 0.0
        closes = [float(x["close"]) for x in r]
        k = 2.0 / (period + 1.0)
        ema = closes[0]
        emas = [ema]
        for c in closes[1:]:
            ema = c * k + ema * (1 - k)
            emas.append(ema)
        if len(emas) < 2:
            return 0.0
        slope = emas[-1] - emas[-2]              # تغيّر EMA لكلّ شمعة
        norm = slope / atr_m1                    # مُطبَّع بتقلّب الرمز نفسه (بلا وحدات)
        return max(-1.0, min(1.0, math.tanh(3.0 * norm)))   # tanh يضغط بسلاسة إلى [-1,1]
    except Exception:
        return 0.0


def _tick_rate(sym, tick):
    """معدّل التكّات المُقدَّر: كم تكّة/ثانية تقريباً بين قياسين متتاليين (باستخدام وقت التكّة).
    fail-soft إلى None. لا يستدعي شيئاً ثقيلاً — يعتمد على الطابع الزمنيّ للتكّة الأخيرة."""
    try:
        t_now = float(getattr(tick, "time_msc", 0) or 0) / 1000.0
        if t_now <= 0:
            t_now = float(getattr(tick, "time", 0) or 0)
        wall = time.time()
        prev = _LAST_TICK.get(sym)
        _LAST_TICK[sym] = (t_now, wall)
        if not prev:
            return None
        pt, pw = prev
        dt_wall = wall - pw
        if dt_wall <= 0:
            return None
        # عدد التكّات غير معلوم مباشرةً؛ نستعمل «هل تحرّك وقت التكّة؟» كنبضٍ خشِن: تكّة جديدة⇒1 وإلا 0،
        # على مدى النافذة يُعطي التاريخُ المتدحرج توزيعاً نقيس عليه (نشاطٌ نسبيّ لا عدّ مطلق).
        moved = 1.0 if t_now > pt else 0.0
        return moved / dt_wall if dt_wall > 0 else moved
    except Exception:
        return None


def _sense_symbol(sym, cfg):
    """👁️ إحساسٌ متّصل لرمزٍ واحد في [0,1] — عيّنات نسبيّة لا عتبات. fail-soft: يتخطّى الرمز عند العجز."""
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    if not info.visible:
        try:
            mt5.symbol_select(sym, True)
        except Exception:
            pass
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        return None
    bid = float(getattr(tick, "bid", 0) or 0)
    ask = float(getattr(tick, "ask", 0) or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    spread = ask - bid

    # ── spread_sense: السبريد الآنيّ نسبةً لعادته الأخيرة (مئويّ) = «السبريد يختار اللحظة» ──
    sh = _SPREAD_HIST[sym]
    if len(sh) >= int(cfg.get("min_spread_samples", 20)):
        spread_pctile = _pctile(sh, spread)
    else:
        spread_pctile = 0.5              # قبل النضج: محايد (لا ندّعي دقّةً لا نملكها)
    sh.append(spread)
    spread_sense = max(0.0, min(1.0, spread_pctile))   # 0 ضيّق .. 1 واسع

    # ── vol_sense: ATR(M1) ÷ ATR(M15) مضغوطاً إلى [0,1] (تقلّبٌ لحظيّ نسبةً للأكبر) ──
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    atr15 = _atr(sym, mt5.TIMEFRAME_M15)
    if atr1 and atr15 and atr15 > 0:
        ratio = atr1 / atr15
        vol_sense = max(0.0, min(1.0, math.tanh(1.2 * ratio)))   # نسبةٌ موجبة ⇒ [0,1] بسلاسة
    else:
        vol_sense = 0.5

    # ── momentum_sense: ميل EMA(M1) مُطبَّعاً بـATR(M1). نحمل الشكلين: موقّع [-1,1] (يستهلكه
    #    brain_trader: agree = mom×dir) و[0,1] (0.5 محايد) للإحساس المُطبَّع الموحّد. ──
    momentum_signed = _ema_slope_signed(sym, int(cfg.get("ema_period", 20)), atr1)
    momentum_sense = max(0.0, min(1.0, 0.5 + 0.5 * momentum_signed))

    # ── energy_sense: نبض التكّات نسبةً لعادته الأخيرة (مئويّ) ──
    tr = _tick_rate(sym, tick)
    th = _TICKRATE_HIST[sym]
    if tr is not None:
        if len(th) >= int(cfg.get("min_spread_samples", 20)):
            energy_sense = _pctile(th, tr)
        else:
            energy_sense = 0.5
        th.append(tr)
    else:
        energy_sense = 0.5
    energy_sense = max(0.0, min(1.0, energy_sense))

    return {
        "spread": round(spread_sense, 4),
        "vol": round(vol_sense, 4),
        "momentum": round(momentum_sense, 4),          # [0,1] مُطبَّع (0.5 محايد)
        "momentum_signed": round(momentum_signed, 4),  # [-1,1] موقّع (للمستهلكين الاتّجاهيّين)
        "energy": round(energy_sense, 4),
        "spread_pctile": round(spread_pctile, 4),
    }


def _build_sense(cfg):
    """👁️ يبني إحساس كلّ الرموز → market_sense.json. صلبٌ لكلّ رمزٍ على حِدة (رمزٌ يعجز لا يُسقط البقيّة)."""
    syms = {}
    for sym in cfg.get("symbols", []):
        try:
            s = _sense_symbol(sym, cfg)
            if s is not None:
                syms[sym] = s
        except Exception as e:
            print(f"sense err {sym}: {type(e).__name__}: {e}")
    now = round(time.time(), 1)
    out = {"updated": now,
           "ts": now,                          # 🔑 مفتاح الحداثة الذي يقرؤه المستهلكون (brain_trader)
           "iso": datetime.now().isoformat(timespec="seconds"),
           "note": "أحاسيسٌ متّصلة [0,1] تشعر بها المحرّكات — ليست قواعد. spread=السبريد يختار اللحظة.",
           "syms": syms}
    # 🔗 توافقٌ مع المستهلك القائم (brain_trader ذهب-فقط يقرأ حقولاً مسطّحة عُليا): نعكس حواسّ الرمز
    #    الأوّل (الذهب افتراضيّاً) في المستوى الأعلى — spread_sense∈[0,1] (1=ضيّق مريح عنده)،
    #    momentum_sense موقّع [-1,1]، vol_sense∈[0,1]. هذه إضافةٌ لا تكسر الشكل المُتداخل المطلوب.
    prim = None
    for s in cfg.get("symbols", []):
        if s in syms:
            prim = syms[s]; out["primary_symbol"] = s; break
    if prim is not None:
        out["spread_sense"] = round(1.0 - prim["spread"], 4)   # brain_trader: 1=ضيّق مريح (نعكس المئويّ)
        out["momentum_sense"] = prim.get("momentum_signed", 0.0)
        out["vol_sense"] = prim["vol"]
        out["energy_sense"] = prim["energy"]
    _atomic_write(SENSE_F, out)
    return len(syms)


# ─────────────────────────── الثقة من نتائج R الحقيقيّة ───────────────────────────
def _closed_R(cfg):
    """🫀 يسحب الصفقات المُغلقة لماجيكاتنا (history_deals، last N days، entry==1) ويحسب لكلٍّ عائد R
    تقريبيّ. entry==1 = الإغلاق حيث تتحقّق النتيجة. نصل الإغلاق بدخوله (position_id) لاستعادة مسافة
    الوقف المقصودة ⇒ R حقيقيّ = ربح ÷ مخاطرة. إن تعذّرت الاستعادة نُطبّع بمقياسٍ صلبٍ لكلّ رمز (مدى
    ATR) — تطبيعٌ متحفّظ لا وعدٌ بدقّة. يرجّع dict magic -> list[(ts, R, sym)] مرتّبة زمنيّاً."""
    days = int(cfg.get("conf_history_days", 7))
    frm = datetime.now() - timedelta(days=days)
    to = datetime.now() + timedelta(hours=12)
    try:
        deals = mt5.history_deals_get(frm, to) or []
    except Exception as e:
        print(f"history err: {type(e).__name__}: {e}")
        return {}
    # فهرسة الدخولات (entry==0) بـposition_id لاستعادة سعر الدخول والحجم (لتقدير مخاطرة R).
    entries = {}
    for d in deals:
        try:
            if int(getattr(d, "entry", -1)) == 0:
                pid = int(getattr(d, "position_id", 0) or 0)
                if pid:
                    entries[pid] = d
        except Exception:
            continue
    per_magic = defaultdict(list)
    for d in deals:
        try:
            if int(getattr(d, "magic", 0)) not in ENGINES:
                continue
            if int(getattr(d, "entry", -1)) != 1:      # نريد الإغلاق فقط (النتيجة المُحقّقة)
                continue
            sym = str(getattr(d, "symbol", "") or "")
            if not sym:
                continue
            ts = float(getattr(d, "time", 0) or 0)
            if ts <= 0:
                continue
            pnl = (float(getattr(d, "profit", 0.0)) + float(getattr(d, "commission", 0.0))
                   + float(getattr(d, "swap", 0.0)))
            if pnl == 0.0:
                continue
            R = _pnl_to_R(d, sym, pnl, entries)
            if R is None:
                continue
            per_magic[int(d.magic)].append((ts, R, sym))
        except Exception:
            continue
    for m in per_magic:
        per_magic[m].sort(key=lambda x: x[0])
    return per_magic


def _pnl_to_R(close_deal, sym, pnl, entries):
    """يحوّل ربح/خسارة الصفقة إلى R (مضاعفات المخاطرة). المحاولة الأولى: استعادة مخاطرة الدخول من الوقف
    المخزّن على المركز (sl على صفقة الدخول ليس متاحاً في history_deals مباشرةً) — لذا نستعمل مقياساً
    متحفّظاً: مخاطرة ≈ order_calc_profit على مسافة ATR(M15) واحدة بحجم الدخول. R = pnl ÷ |risk|.
    fail-soft: إن تعذّر ⇒ نُطبّع بإشارةٍ ثنائيّةٍ مقصوصة (±0.7R) كي لا نكذب دقّةً غير متاحة."""
    try:
        pid = int(getattr(close_deal, "position_id", 0) or 0)
        vol = float(getattr(close_deal, "volume", 0) or 0)
        ent = entries.get(pid)
        if ent is not None and vol <= 0:
            vol = float(getattr(ent, "volume", 0) or 0)
        entry_px = float(getattr(ent, "price", 0) or 0) if ent is not None else 0.0
        etype = int(getattr(ent, "type", -1)) if ent is not None else -1  # 0 buy, 1 sell
        atr15 = _atr(sym, mt5.TIMEFRAME_M15)
        if vol > 0 and entry_px > 0 and atr15 and etype in (0, 1):
            # سعر وقفٍ افتراضيّ على بُعد ATR(M15) واحد في الاتّجاه المعاكس للدخول.
            if etype == 0:      # buy => الوقف أسفل
                sl_px = entry_px - atr15
                otype = mt5.ORDER_TYPE_BUY
            else:               # sell => الوقف أعلى
                sl_px = entry_px + atr15
                otype = mt5.ORDER_TYPE_SELL
            risk = mt5.order_calc_profit(otype, sym, vol, entry_px, sl_px)
            if risk is not None and abs(float(risk)) > 1e-9:
                R = pnl / abs(float(risk))
                return max(-R_CLIP, min(R_CLIP, R))
    except Exception:
        pass
    # مسارٌ احتياطيّ صادق: لا مخاطرة قابلة للاستعادة ⇒ إشارةٌ اتّجاهيّة مقصوصة (فوز/خسارة) لا حجم مُدّعى.
    return 0.7 if pnl > 0 else -0.7


def _confidence_for(magic_rows, halflife):
    """🫀 القلب: ثقةٌ في [0,1] كـEWMA لعوائد R الأخيرة (نصف-عمر halflife صفقة). تصعد بالأهداف، تهبط
    بالوقف — تماماً كطلب المستخدم. الترميز: نُطبّع كلّ R بدالّة لوجستيّة إلى [0,1] (خسارةٌ→<0.5،
    ربحٌ→>0.5)، ثمّ متوسّطٌ موزونٌ هندسيّاً (أحدثُ أثقل). لا تنبّؤ — انعكاسٌ صادق للنتائج المُحقّقة."""
    if not magic_rows:
        return 0.5, 0, 0.0, 0
    # وزنٌ هندسيّ: أحدث صفقة وزنها 1، وكلّ خطوةٍ أقدم تُضرب بـdecay حتى يبلغ 0.5 عند halflife.
    decay = 0.5 ** (1.0 / max(1.0, float(halflife)))
    rows = magic_rows[-max(4, int(halflife * 4)):]   # نكتفي بآخر ~4×نصف-العمر (الأقدم وزنه ضئيل)
    num = 0.0; den = 0.0; w = 1.0
    for ts, R, sym in reversed(rows):                # من الأحدث إلى الأقدم
        # لوجستيّة: R=0→0.5، R=+1→~0.73، R=−1→~0.27، مقصوصةٌ سلفاً في [−R_CLIP,R_CLIP].
        p = 1.0 / (1.0 + math.exp(-R))
        num += w * p
        den += w
        w *= decay
    conf = (num / den) if den > 0 else 0.5
    last_R = rows[-1][1]
    streak = _streak(rows)
    return max(0.0, min(1.0, conf)), len(rows), last_R, streak


def _streak(rows):
    """سلسلة النتائج الحاليّة: +k فوزٌ متتالٍ، −k خسارةٌ متتالية (من الأحدث)."""
    if not rows:
        return 0
    sign = 1 if rows[-1][1] > 0 else -1
    k = 0
    for _, R, _s in reversed(rows):
        if (R > 0 and sign > 0) or (R <= 0 and sign < 0):
            k += 1
        else:
            break
    return sign * k


def _conf_to_mod(conf):
    """🔒 يُخطّط الثقة [0,1] إلى مُعدِّل قناعة/حجم محدود [MOD_MIN, MOD_MAX] خطّيّاً حول المحايد.
    conf=0.5 ⇒ 1.0 (محايد)، conf=1 ⇒ MOD_MAX، conf=0 ⇒ MOD_MIN. ناعمٌ ومحدود دائماً — لا يُصفّر
    ولا يُفجّر، ولا يُلغي أيّ فيتو (المحرّكات تضربه داخل حدودها الآمنة، لا تستبدله بها)."""
    conf = max(0.0, min(1.0, conf))
    if conf >= 0.5:
        mod = 1.0 + (conf - 0.5) / 0.5 * (MOD_MAX - 1.0)
    else:
        mod = MOD_MIN + (conf / 0.5) * (1.0 - MOD_MIN)
    return max(MOD_MIN, min(MOD_MAX, mod))


def _build_confidence(cfg):
    """🫀 يبني ثقة كلّ محرّكٍ من نتائجه المُغلقة → confidence.json. يُخبّئ سحب التاريخ conf_refresh_s
    ثانية (لا نُثقل history كلّ دورة). صلبٌ: عجزٌ ⇒ نُبقي الكاش السابق أو محايداً."""
    now = time.time()
    halflife = float(cfg.get("conf_halflife", CONF_HALFLIFE))
    if (now - G["conf_cache_ts"]) >= float(cfg.get("conf_refresh_s", 20.0)) or not G["conf_cache"]:
        try:
            per_magic = _closed_R(cfg)
        except Exception as e:
            print(f"confidence pull err: {type(e).__name__}: {e}")
            per_magic = {}
        engines_out = {}
        for magic, name in ENGINES.items():
            rows = per_magic.get(magic, [])
            conf, n_recent, last_R, streak = _confidence_for(rows, halflife)
            # ثقةٌ فرعيّة لكلّ (محرّك، رمز) — نفس المنطق على مجموعات الرمز الجزئيّة.
            per_sym = defaultdict(list)
            for ts, R, sym in rows:
                per_sym[sym].append((ts, R, sym))
            psym_out = {}
            for sym, srows in per_sym.items():
                sc, sn, slr, sstk = _confidence_for(srows, halflife)
                psym_out[sym] = {
                    "confidence": round(sc, 4),
                    "modifier": round(_conf_to_mod(sc), 4),
                    "n_recent": sn,
                    "last_R": round(slr, 3),
                    "streak": sstk,
                }
            engines_out[str(magic)] = {
                "name": name,
                "confidence": round(conf, 4),
                "modifier": round(_conf_to_mod(conf), 4),
                "n_recent": n_recent,
                "last_R": round(last_R, 3),
                "streak": streak,
                "per_symbol": psym_out,
            }
        cache = {
            "updated": round(now, 1),
            "ts": round(now, 1),               # 🔑 مفتاح حداثةٍ للمستهلكين
            "iso": datetime.now().isoformat(timespec="seconds"),
            "halflife_trades": halflife,
            "mod_bounds": [MOD_MIN, MOD_MAX],
            "note": "ثقةٌ من نتائج R مُغلقة حقيقيّة فقط (EWMA نصف-عمر ~15 صفقة): تصعد بالأهداف تهبط "
                    "بالوقف. المُعدِّل محدود [0.5,1.3] — ناعمٌ لا يُلغي فيتو ولا يتجاوز سقفاً. لا تنبّؤ.",
            "engines": engines_out,
        }
        # 🔗 توافقٌ مع المستهلك القائم (brain_trader يقرأ c[str(MAGIC)].modifier عُليا، ثم c["magics"][k]):
        #    نعكس مدخلات المحرّكات في المستوى الأعلى وتحت "magics" — إضافةٌ لا تكسر بلوك "engines" المطلوب.
        cache["magics"] = engines_out
        for mk, mv in engines_out.items():
            cache[mk] = mv
        G["conf_cache"] = cache
        G["conf_cache_ts"] = now
    else:
        # لم يحن التحديث — نُحدّث الطابع الزمنيّ فقط كي يبقى الملفّ «حيّاً» للوصيّ دون إعادة حساب.
        G["conf_cache"]["updated"] = round(now, 1)
        G["conf_cache"]["ts"] = round(now, 1)
        G["conf_cache"]["iso"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write(CONF_F, G["conf_cache"])
    return len(G["conf_cache"].get("engines", {}))


def _save_status(cfg, n_sense, n_conf):
    now = time.time()
    if now - G["status_ts"] < 5:
        return
    G["status_ts"] = now
    st = {"ts": round(now, 1), "iso": datetime.now().isoformat(timespec="seconds"),
          "engine": "عيون وإحساس", "role": "read_only_no_trade",
          "n_symbols_sensed": n_sense, "n_engines_scored": n_conf,
          "enabled": bool(cfg.get("enabled", True)),
          "note": "قراءة فقط — لا ماجيك، لا مسار أوامر. مُخرَجان: market_sense.json + confidence.json"}
    _atomic_write(STATUS_F, st)


def _idle_status():
    """💤 نبض idle حين مُعطَّل/مقفول — كي لا يراه الوصيّ «معلّقاً» فيدخل حلقة قتل/إحياء."""
    try:
        st = {"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
              "engine": "عيون وإحساس", "role": "read_only_no_trade",
              "enabled": False, "reason": "معطَّل/مقفول — خامل (enabled=false أو kill_switch)"}
        _atomic_write(STATUS_F, st)
        # نُبقي market_sense حيّاً أيضاً (نبض) كي لا يُشفى قسرياً على heartbeat market_sense.json.
        _atomic_write(SENSE_F, {"updated": round(time.time(), 1),
                                "iso": datetime.now().isoformat(timespec="seconds"),
                                "idle": True, "syms": {}})
    except Exception:
        pass


def main():
    ok = False
    for i in range(6):
        try:
            if mt5.initialize():
                ok = True; break
        except Exception:
            pass
        print(f"⏳ init {i + 1}/6"); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5"); return
    print(f"👁️🫀 عيون وإحساس بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — قراءة فقط · لا ماجيك · "
          f"لا تداول · مُخرَجان: الإحساس + الثقة من النتائج")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True) or os.path.exists(KILL1) or os.path.exists(KILL2):
                _idle_status()
                time.sleep(10); continue
            # حارس Trial/Demo — مُقدَّس. هذا المحرّك لا يتاجر أصلاً، لكن نحترم الحارس صراحةً كطبقةٍ إضافيّة:
            # نُبقي الإحساس يعمل (قراءة سوق بحتة، آمنة) لكن نمتنع عن نسب ثقةٍ من حسابٍ حقيقيّ (صدق: الثقة
            # تجربةُ ديمو مقيسة). على حسابٍ حقيقيّ نكتب الثقة محايدةً صراحةً بدل إيهام تعلّمٍ حيّ.
            acct = mt5.account_info()
            srv = str(getattr(acct, "server", "") or "") if acct else ""
            is_demo = bool(acct) and ("Trial" in srv or "Demo" in srv)

            n_sense = _build_sense(cfg)          # 👁️ الإحساس — قراءة سوق آمنة دائماً

            if is_demo:
                n_conf = _build_confidence(cfg)  # 🫀 الثقة من نتائج الديمو المُقاسة
            else:
                # حسابٌ حقيقيّ: لا ندّعي تعلّماً — نكتب ثقةً محايدةً (مُعدِّل 1.0) صراحةً.
                neutral = {str(m): {"name": nm, "confidence": 0.5, "modifier": 1.0,
                                    "n_recent": 0, "last_R": 0.0, "streak": 0, "per_symbol": {}}
                           for m, nm in ENGINES.items()}
                _now = round(time.time(), 1)
                nc = {
                    "updated": _now, "ts": _now,
                    "iso": datetime.now().isoformat(timespec="seconds"),
                    "halflife_trades": float(cfg.get("conf_halflife", CONF_HALFLIFE)),
                    "mod_bounds": [MOD_MIN, MOD_MAX],
                    "note": f"خادم '{srv}' ليس ديمو — الثقة تجربةُ قياسٍ ديمو؛ نكتبها محايدةً (1.0) "
                            f"بلا ادّعاء تعلّمٍ حيّ.",
                    "engines": neutral, "magics": neutral}
                for mk, mv in neutral.items():
                    nc[mk] = mv                     # مرآة عُليا للمستهلك القائم (modifier=1.0 محايد)
                _atomic_write(CONF_F, nc)
                n_conf = len(neutral)

            _save_status(cfg, n_sense, n_conf)
            time.sleep(float(cfg.get("loop_s", 2.5)))
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
