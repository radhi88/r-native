# -*- coding: utf-8 -*-
"""gold_scalper.py — نسخة أسلوب المستخدم: سكالب لوت-صغير + إغلاق ربح سريع + رشّ، على المفتوح.

(ديمو، windowless تحت الوصيّ، magic 20260628 — اختبار أمامي صادق لأسلوبك الذي حقّق $25→$78.)

يرشّ على **المفتوح فعلاً**: البيتكوين/الإيثيريوم 24/7 (الآن)، والذهب حين يفتح (الإثنين).
أسلوبك بالضبط (مُحدَّث): لوت أدنى + رشّ على زخم M1 + **لا وقف ولا هدف ثابت** + **إغلاق جماعي**
يديره الزخم: يُغلق كل مراكز الرمز على *انعكاس* (زخم ضدّك) أو *سرعة في صالحك + ربح* (اقفل الربح).
الحُرّاس المُثبتة (للدخول) كي لا ينقلب لفخّ «يربح صغيراً يخسر كبيراً»:
  • لوت أدنى ضمن 2% (لا تحجيم زائد — قاتلك −$94/صفقة).
  • فيتو التشبّع الشرائي (rsi>70 = −$31/صفقة حقيقي).
  • سبريد ضيّق فقط (الكلفة عنق الزجاجة).
  • أسلوبك «لا وقف ولا إغلاق على خسارة»: الخاسر يُمسَك حتى يعود أخضر؛ لا إغلاق إلا لقفل ربح.
  • الكارثة الوحيدة = الأرضية (master_floor 50%) + kill_switch. نوقف الرشّ في تراجع عائم ≥4% (لا نضيف، لا نُغلق).
  ⚠️ هذا أعلى نمط مخاطرة: يربح حتى تأتي دفعة لا تعود — الأرضية وحدها تمسكها.

الأرقام تحكم: هل يصمد أسلوبك صافيةً (حافّة) أم يبدأ + ثم ينهار (الفخّ)؟  تشغيل: pythonw gold_scalper.py
"""
from __future__ import annotations
from engine_lock import claim
import json, math, time
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

try:
    import novel_indicators as ni
except Exception:
    ni = None

try:
    import candle_anatomy as ca       # تشريح تشكيلات الشموع (الرفض/الذيول)
except Exception:
    ca = None

try:
    import market_structure as ms     # بنية السوق HH/HL/LH/LL + BOS
except Exception:
    ms = None
try:
    import delta_flow as df           # دلتا تدفّق الأوامر الدقيقة (ندخل مع الزخم لا ضدّه)
except Exception:
    df = None
try:
    import deep_conviction as dc      # فيتو الخسارة المُثبتة (Bonferroni على صفقات حقيقية) — تشديد فقط
except Exception:
    dc = None
try:
    import level_map as lm            # 🗺️ خريطة المستويات الهدف (قمّة/قاع الأمس + بايفوت + فيبو + جان Sq9/زوايا + نجمة داوود + فراكتل)
except Exception:
    lm = None
try:
    import trend_flip as tf           # 🔄 كاشف الانعكاس الحاسم (أغلق الخاسر واقلب مع الترند الجديد) — مشدّد متعدّد العوامل
except Exception:
    tf = None
try:
    import lot_guard                  # 🛑 ضبط الذهب: السقف الصلب المُثبت OOS (الحجم = الرافعة الوحيدة)
except Exception:
    lot_guard = None
try:
    from friday_db import FridayDB    # 📝 تأريخ كل صفقة ذهب (سياق الدخول + سبب الخروج) في friday.db للتعلّم
    _DB = FridayDB()
except Exception:
    _DB = None

SYMBOLS = ["XAUUSDm", "BTCUSDm", "ETHUSDm"]   # 🥇 الذهب أولاً (أولويّة المستخدم): يُفحَص قبل الكريبتو كل دورة
GOLD = "XAUUSDm"                               # رمز التركيز: إدارة أسرع 4× + تأريخ لحظيّ كامل
MAGIC = 20260628
ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
KILL = ROOT / "kill_switch.txt"
STATUS = RN / "gold_scalper_status.json"
LOG = RN / "gold_scalper.log"

POLL_S = 2.0                # دورة كاملة (إدارة الكلّ + مسح دخول)
GOLD_MANAGE_S = 0.5         # 🥇 إدارة الذهب وحده كل 0.5ث داخل دورة الـ2ث (تفاعل أسرع 4× للانعكاس/القفل) — استطلاع مؤدّب لا حلقة محمومة
SPREAD_REV_ATR = 0.50      # «سبريد عالٍ عكس دخولنا»: سبريد ≥ هذا×ATR وقت الانعكاس = تأكيد حركة حقيقيّة ⇒ اقفل أكبر ربح
MAX_POS_PER_SYM = 2          # رشّ لكل رمز (خُفِّض من 4: «دع الرابح يجري» ألغى إغلاق الرشّ السريع ⇒ الرشّ يكدّس خسارة بلا وقف)
MAX_POS_TOTAL = 5            # خُفِّض من 8: يحدّ عمق الكومة العارية
STACK_RED_PCT = 1.0          # 🚫 لا تفتح المزيد على رمزٍ كومتنا عليه أحمر أعمق من 1% من الحقوق (مضادّ-مارتنغيل + علاج جذر «+80% ثم يهجّ»)
# 🪂 استرداد بزخم مؤكَّد (أسلوب المستخدم): كومة حمراء + زخم M1 ارتدّ فعلاً لصالحنا من طرفٍ مناسب ⇒ إضافة
# محكومة في اتجاه الكومة + معلّق أعمق (بلا وقف). ليس مارتنغيل: نضيف حين الزخم ارتدّ، لا لمجرّد أن السعر أرخص.
RECOVERY_MAX_PER_SYM = 5     # أقصى إضافات استرداد لكل رمز (مؤكَّدة بالزخم، لا رشّ أعمى)
RECOVERY_MAX_TOTAL   = 10    # سقف كلّيّ للاسترداد
RECOVERY_MOM = 0.30          # زخم M1 (آخر 5د) ≥ هذا×ATR في اتجاه كومتنا = ارتداد مؤكَّد (لا سكّين)
RECOVERY_LIMIT_ATR = 0.8     # المعلّق على بُعد 0.8 ATR أعمق (بلا وقف — «بالإضافة إلى المعلّقة»)
SL_ATR = 1.20               # لتقدير حجم اللوت فقط (لا يُوضَع كوقف فعليّ — أسلوبك بلا وقف)
AGGR_RISK_PCT = 2.5         # 🔥 «ادعس»: حجم كل صفقة يستهدف ~2.5% مخاطرة (لا أدنى-لوت فقط)
MAX_LOT_MULT = 15          # سقف أمان: اللوت ≤ 15× الأدنى (عدوانية لا انتحار)
PAUSE_DD_PCT = 8.0          # 🚫 يُمسك لتراجع أعمق (8%) قبل وقف الرشّ — أجرأ. الكارثة الوحيدة = الأرضية (−50%)
MARGIN_MIN_PCT = 250.0      # 🛡️ لا نرشّ إن هبط مستوى هامش الحساب الكلّيّ تحت هذا (يحمي من كاسكيد stop-out)
COOLDOWN_S = 6             # رشّ أكثف (كان 12)
SPREAD_MAX_ATR = 0.40
REV_SPEED = 0.55            # سرعة الانعكاس (×ATR) لإغلاق جماعي ضدّي
FAV_SPEED = 0.65            # سرعة في الصالح (×ATR) + ربح ⇒ اقفل الربح
PYRAMID_MAX = 8             # 🔥 سقف التهرّم عند ترند مؤكَّد (زيد النار حطب على الرابح)
CONFIRM_SPEED = 0.50        # سرعة الزخم اللازمة لتأكيد الترند (للتهرّم)
MOM_RIDE = 0.8              # 🔥 ركوب الزخم: زخم ≥ هذا×ATR متوافق مع الترند = اختراق ⇒ ندخل معه (يتجاوز الالتقاء الضعيف + قرب الطرف)
BOUNCE_DROP_ATR = 1.5      # 🪂 شمعة هبوطية ≥ هذا×ATR = كسر كبير ⇒ نشتري الارتداد بقوّة (يملأ الفجوة)
BOUNCE_RSI_MAX = 55        # نشتري الارتداد فقط إن لم يكن متشبّعاً شرائياً (بعد هبوط = منخفض غالباً)
# 💰 القفل المتحرّك (من تعلّم الندم regret_learner): قِسنا أنّ السعر يتحرّك +MFE لصالحنا ثم نُعيده خسارة
# (التقاط −8% من القمة، MAE −54). نُمسك حتى يربح (أسلوبك) لكن متى دخل ربحاً ذا معنى، نُلاحق القمة كي لا
# يتحوّل الربح خسارةً. هذا لا يكسر «لا نُغلق على خسارة» — يعمل فقط حين netpl موجب.
LOCK_ARM_USD = 4.0         # تسلَّح الملاحقة حين بلغ الربح العائم هذا$ (ربح ذو معنى يستحقّ الحماية)
LOCK_GIVEBACK = 0.45       # اقفل إن تراجع الربح إلى 45% من قمته (نلتقط ~55% من MFE بدل −8%)


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _record_gold(action, sym, d=0, score=None, tier=None, struct=None, rsi=None,
                 spread=None, atr1=None, lot=None, entry=None, retcode=None):
    """📝 يُسجّل صفقة/حدث ذهب في friday.db (signals) — للذهب فقط، آمن (لا يرفع استثناءً، لا يخنق BTC/ETH)."""
    if _DB is None or sym != GOLD:
        return
    try:
        _DB.record_signal(symbol=sym, tf="M1", dir=(int(d) if d else None), confluence=score,
                          regime=(struct or {}).get("label") if isinstance(struct, dict) else None,
                          entry=entry, risk=lot, source="gold_scalper",
                          extra={"action": action, "tier": tier, "rsi": rsi, "spread": spread,
                                 "atr1": atr1, "spread_atr": (spread / atr1) if (spread and atr1) else None,
                                 "retcode": retcode})
    except Exception:
        pass


def _atr(sym, tf, n=14):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def _rsi(sym, tf, n=14):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n + 2)
    if r is None or len(r) < n + 1:
        return 50.0
    d = np.diff(r["close"])
    up = np.clip(d, 0, None)[-n:].mean(); dn = (-np.clip(d, None, 0))[-n:].mean()
    return 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)


def _mom_dir(sym):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 6)
    if r is None or len(r) < 5:
        return 0
    mom = r["close"][-1] - r["close"][-5]
    return 1 if mom > 1e-9 else -1 if mom < -1e-9 else 0


def _big_drop(sym, atr1):
    """شمعة M1 هبوطية كبيرة للتوّ (كسر ≥ BOUNCE_DROP_ATR×ATR) ⇒ يرجع مستوى فيبو 50% (منتصف الشمعة)
    هدفاً للارتداد، وإلا None. الارتداد يملأ ~50% ثم ينعكس (ربح) أو يكسره ويكمل صعوداً (نركب)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 3)
    if r is None or len(r) < 2 or atr1 <= 0:
        return None
    last = r[-2]                                       # الشمعة المكتملة الأخيرة
    drop = float(last["open"] - last["close"])
    if drop >= BOUNCE_DROP_ATR * atr1 and drop > 0:
        return float((last["open"] + last["close"]) / 2.0)   # 50% فيبو
    return None


def _open(sym):
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    return bool(info and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL and tk and (time.time() - tk.time) < 180)


def _day_loss_pct(eq):
    try:
        deals = mt5.history_deals_get(time.time() - 86400, time.time()) or []
        net = sum(d.profit + d.commission + d.swap for d in deals if d.magic == MAGIC and d.entry == 1)
        return (-net / eq * 100.0) if (eq and net < 0) else 0.0
    except Exception:
        return 0.0


_DOSS_CACHE = {"t": 0.0, "syms": {}}
_bounce_tgt = {}                  # {sym: مستوى فيبو 50%} لصفقات الارتداد
_peak_pl = {}                     # {sym: قمة الربح العائم} للقفل المتحرّك (التقاط القمة — تعلّم الندم)
_reverse_to = {}                  # {sym: (اتجاه جديد, وقت)} ستوب-آند-ريفيرس بعد إغلاق رابح على انعكاس

# ── ضبط ذاتيّ مغلق (تشديد-فقط) ────────────────────────────────────────────────
# self_tuner.py يكتب scalper_params.json من نتائج الندم المقاسة؛ نقرؤه حيّاً كل دورة (بلا إعادة تشغيل).
# الأمان الرياضيّ: نُقصّ **تشديداً-فقط ضدّ الافتراضي المشحون** ⇒ ملفّ تالف/خبيث/ضوضائيّ لا يُرخّي أيّ
# حماية أبداً (أسوأ حالة = تحفّظ زائد: التقاط أقلّ/تداول أقلّ، لا تعميق لذيل الخسارة). ضوابط المخاطرة
# (FAV_SPEED/PAUSE_DD/AGGR_RISK/MAX_LOT/PYRAMID/«لا وقف») ثوابت صلبة — ليست من الملفّ.
_PARAMS_FILE = RN / "scalper_params.json"
_PARAM_DEFAULTS = {"lock_giveback": LOCK_GIVEBACK, "lock_arm_usd": LOCK_ARM_USD,
                   "rev_speed": REV_SPEED, "spread_max_atr": SPREAD_MAX_ATR, "cooldown_s": float(COOLDOWN_S)}
_PARAM_BANDS = {"lock_giveback": (0.45, 0.80), "lock_arm_usd": (2.0, 4.0),
                "rev_speed": (0.30, 0.55), "spread_max_atr": (0.20, 0.40), "cooldown_s": (6.0, 30.0)}
_TIGHTEN = {"lock_giveback": max, "lock_arm_usd": min,  # اتجاه التشديد ضدّ الافتراضي:
            "rev_speed": min, "spread_max_atr": min, "cooldown_s": max}  # giveback↑ arm↓ rev↓ spread↓ cooldown↑
_P = dict(_PARAM_DEFAULTS)
_pcache = {"mt": -1.0}


def _load_params():
    """يقرأ scalper_params.json (مُهدّأ بالـmtime) ⇒ يتحقّق (رقم منتهٍ داخل النطاق) ⇒ يُقصّ تشديداً-فقط. fail-safe للافتراضي."""
    global _P
    try:
        mt = _PARAMS_FILE.stat().st_mtime
        if mt == _pcache["mt"]:
            return _P
        _pcache["mt"] = mt
        raw = json.load(open(_PARAMS_FILE, encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not a dict")
    except Exception:
        _P = dict(_PARAM_DEFAULTS); return _P     # مفقود/تالف/نصف-مكتوب ⇒ الافتراضي الآمن
    out = dict(_PARAM_DEFAULTS)
    for k, dflt in _PARAM_DEFAULTS.items():
        v = raw.get(k)
        lo, hi = _PARAM_BANDS[k]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi:
            out[k] = _TIGHTEN[k](float(v), dflt)  # تشديد-فقط: لا يُرخّي تحت الافتراضي المشحون أبداً
    _P = out
    return _P


def _deep_confirm(sym, d):
    """إشارة العقل العميق (مجمّع كل المؤشرات/الإشارات) توافق الاتجاه d بقوّة؟ (تأكيد التهرّم)."""
    try:
        now = time.time()
        if now - _DOSS_CACHE["t"] > 5:
            doss = json.load(open(RN / "deep_dossier.json", encoding="utf-8-sig"))
            _DOSS_CACHE.update(t=now, syms=doss.get("symbols", {}))
        sd = _DOSS_CACHE["syms"].get(sym, {})
        bdir = 1 if sd.get("bias") == "صعود" else -1 if sd.get("bias") == "هبوط" else 0
        return bdir == d and "قوي" in (sd.get("call") or "")
    except Exception:
        return False


def _close_all(sym, reason):
    closed = 0
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != MAGIC:
            continue
        tk = mt5.symbol_info_tick(sym)
        if not tk:
            continue
        px = tk.bid if p.type == 0 else tk.ask
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": p.volume,
                            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                            "position": p.ticket, "price": px, "deviation": 50, "magic": MAGIC,
                            "comment": f"close-{reason}", "type_filling": mt5.ORDER_FILLING_IOC})
        closed += int(getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE)
    if closed:
        _log(f"إغلاق جماعي {sym}: {closed} مركز ({reason})")
        _record_gold(f"close:{reason}", sym, retcode=closed)   # 📝 سبب الخروج (نتعلّم جودة الإغلاق)
    return closed


def _heading_to_level(sym, sdir, move, atr):
    """🗺️ دع الربح يجري للمستوى التالي (شرط المستخدم: «مو نغلق الربع بسرعة — نشوف المستويات اللي راح يتوجه
    لها»): إن كان مستوى هدفٌ هندسيّ (قمّة/قاع الأمس، بايفوت، فيبو، جان، نجمة داوود، فراكتل) أمامنا في
    اتجاهنا والسعر ما زال يتحرّك نحوه ⇒ لا تقفل بعد، اتركه يصل. القفل/الانعكاس يعملان حين يتوقّف الزخم."""
    if lm is None or atr <= 0:
        return False
    try:
        proj = lm.project(sym, sdir)
    except Exception:
        return False
    if not proj or not proj.get("next"):
        return False
    tk = mt5.symbol_info_tick(sym)
    if not tk:
        return False
    price = (tk.ask + tk.bid) / 2.0
    nxt = proj["next"][1]
    ahead = (nxt - price) if sdir > 0 else (price - nxt)        # مسافة للمستوى (موجبة = أمامنا)
    momentum_ours = (move > 0) if sdir > 0 else (move < 0)
    return 0 < ahead <= 2.5 * atr and momentum_ours and abs(move) >= 0.15 * atr


def _flip_open(sym, d, eq):
    """🔄 افتح مركزاً محكوماً واحداً **مع** الترند الجديد (بلا وقف) بعد إغلاق الخواسر — تنفيذ القلب الحاسم."""
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    if not info or not tk or atr1 <= 0:
        return False
    sl_dist = SL_ATR * atr1; ts = info.trade_tick_size or info.point; tv = info.trade_tick_value
    step = info.volume_step or 0.01
    rpu = (sl_dist / ts) * tv if (ts and tv) else 0
    if rpu <= 0:
        return False
    lot = (eq * AGGR_RISK_PCT / 100.0) / rpu * _gov_mult()
    lot = max(info.volume_min, round(lot / step) * step)
    lot = min(lot, info.volume_min * MAX_LOT_MULT, info.volume_max or lot)
    if lot_guard:
        lot, _ = lot_guard.cap(mt5, sym, lot, eq)          # 🛑 سقف صلب 2% (ضبط الذهب — الحجم لا يدمّر)
    entry = tk.ask if d > 0 else tk.bid
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL,
                          "price": entry, "sl": 0.0, "tp": 0.0, "deviation": 30, "magic": MAGIC,
                          "comment": "flip", "type_filling": mt5.ORDER_FILLING_IOC})
    ok = getattr(res, "retcode", None) == mt5.TRADE_RETCODE_DONE
    if ok:
        _log(f"🔄 قلب {sym} {'شراء' if d>0 else 'بيع'} {lot} @{entry:.2f} (مع الترند الجديد بعد إغلاق الخواسر الحاسم)")
        _record_gold("flip_open", sym, d=d, lot=lot, entry=entry, atr1=atr1)
    return ok


def _manage(sym):
    """أسلوبك (لا وقف): أغلق كل مراكز الرمز جماعياً على انعكاس، أو على سرعة في الصالح + ربح."""
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    if not mine:
        _bounce_tgt.pop(sym, None); _peak_pl.pop(sym, None)    # رمز مُسطَّح: انسَ قمّته
        return
    netdir = 1 if sum((1 if p.type == 0 else -1) for p in mine) >= 0 else -1
    netpl = sum(p.profit for p in mine)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 4)
    if r is None or len(r) < 3 or atr1 <= 0:
        return
    if netpl <= 0:                                     # خاسر: أسلوبك = نُمسك حتى يعود أخضر — **إلا** انعكاس حاسم
        # 🔄 انعكاس حاسم (طلب المستخدم، «مصيريّ»): الترند انقلب ضدّنا بوضوح بلا عودة (BOS+لا-عودة+≥4 عوامل+جلسة)
        # ⇒ هذا هو مخرج الخاسر المفقود: أغلق الخواسر واقلب مع الترند الجديد. مشدّد ضدّ التذبذب (ذاتيّ-الإنفاذ).
        if tf is not None and not _is_paused() and not KILL.exists():
            vol = sum(p.volume for p in mine) or 1.0
            avg = sum(p.price_open * p.volume for p in mine) / vol
            _acc = mt5.account_info()
            eq = _acc.equity if _acc else 0.0
            dec = tf.decisive_reversal(mt5, sym, netdir, avg, netpl, eq, atr1, 0.0)
            if dec.get("flip"):
                nd = dec["new_dir"]
                _close_all(sym, f"انعكاس حاسم → قلب: {dec.get('reason','')[:50]}")
                if _flip_open(sym, nd, eq):
                    tf.record_flip(sym, nd)            # ثبّت التهدئة الذاتيّة (لا قلب-ثمّ-قلب)
                _bounce_tgt.pop(sym, None); _peak_pl.pop(sym, None)
        return
    # 💰 القفل المتحرّك (تعلّم الندم): لاحِق قمّة الربح كي لا يتحوّل أخضرُنا أحمر. يعمل فقط في الربح ⇒ لا يكسر قاعدتك.
    pk = _peak_pl.get(sym, 0.0)
    if netpl > pk:
        _peak_pl[sym] = pk = netpl
    move = float(r["close"][-1] - r["close"][-3])     # زخم آخر شمعتين
    speed = abs(move) / atr1
    mdir = 1 if move > 0 else -1
    # 💰 القفل المتحرّك — لكن «دع الربح يجري للمستوى التالي» إن كان أمامنا والزخم يدفع نحوه (شرط المستخدم)
    if pk >= _P["lock_arm_usd"] and netpl <= pk * _P["lock_giveback"]:   # تراجَع الربح عن قمّته
        if not _heading_to_level(sym, netdir, move, atr1):              # لا مستوى أكبر أمامنا ⇒ اقفل والتقِط القمّة
            _close_all(sym, f"قفل-متحرّك (التقاط {netpl:.1f}$ من قمّة {pk:.1f}$)")
            _bounce_tgt.pop(sym, None); _peak_pl.pop(sym, None); return
        # وإلا: متّجه لمستوى هدفٍ أكبر بزخم ⇒ اتركه يجري (لا تقفل هذه الدورة)
    # 🪂 هدف فيبو 50% للارتداد: نتركه يجري ما دام الزخم في صالحنا (دع الرابح يجري)؛ لا نقفل عنده بل عند الانعكاس
    tgt = _bounce_tgt.get(sym)
    if tgt and netdir == 1:
        tk = mt5.symbol_info_tick(sym)
        if tk and tk.bid >= tgt and speed >= FAV_SPEED and mdir == 1:
            _bounce_tgt.pop(sym, None)                  # بلغ الهدف وما زال يصعد بقوّة ⇒ نركب (التهرّم يضيف)
    # ═══ قاعدة الأرباح الكبيرة (المستخدم): دع الرابح يجري لأقصى ربح؛ لا تُغلق إلا على انعكاس واضح ═══
    # الخروج = (انعكاس زخم ∨ شمعة انعكاسيّة ∨ كسر بنية BOS ضدّنا) ∧ سبريد عالٍ عكس دخولنا ⇒ يؤمّن أكبر ربح.
    tk2 = mt5.symbol_info_tick(sym)
    spread2 = (tk2.ask - tk2.bid) if tk2 else 0.0
    adverse_spread = spread2 >= SPREAD_REV_ATR * atr1                 # «سبريد عالٍ» = تأكيد حركة حقيقيّة
    mom_rev = speed >= _P["rev_speed"] and mdir != netdir             # انعكاس زخم
    pat = (ca.last_signal(sym).get("pat", "") if ca else "")          # شمعة انعكاسيّة ضدّنا
    candle_rev = ((netdir == 1 and pat in ("shooting_star", "marubozu_dn", "bearish_engulfing"))
                  or (netdir == -1 and pat in ("hammer", "marubozu_up", "bullish_engulfing")))
    st5 = ms.structure(sym, "M5") if ms else {}                       # كسر بنية ضدّنا (BOS/CHoCH)
    struct_rev = bool(st5.get("bos")) and ((netdir == 1 and st5.get("trend") == "down")
                                           or (netdir == -1 and st5.get("trend") == "up"))
    clear_reversal = mom_rev or candle_rev or struct_rev
    violent_rev = speed >= 1.5 * _P["rev_speed"] and mdir != netdir   # انعكاس عنيف = خروج فوريّ (سلامة)
    if (clear_reversal and adverse_spread) or violent_rev:
        _close_all(sym, "انعكاس واضح + سبريد (تأمين أكبر ربح)")
        _bounce_tgt.pop(sym, None); _peak_pl.pop(sym, None)
        if mdir != netdir:
            _reverse_to[sym] = (mdir, time.time())     # 🔄 «نعكس الأوامر»: نركب الاتجاه الجديد إن وافقت الرغبة
        return
    if speed >= 1.7 * FAV_SPEED and mdir == netdir:    # ⚡ ذروة اندفاع متطرّفة (climax) فقط ⇒ اقفل؛ غيرها يجري للربح الأكبر
        _close_all(sym, "ذروة اندفاع (قفل ربح)"); _bounce_tgt.pop(sym, None); _peak_pl.pop(sym, None)


def _confluence(sym, d, struct, csig, atr1):
    """قوّة «الرغبة»: كم من القوى تتّفق مع الاتجاه d؟ (زخم M1 + ترند M5 + شمعة + تدفّق دلتا + عقل عميق).
    الاتجاهان مسموحان — لكن كلّما زاد الالتقاء زادت الرغبة. يرجع (score, tier, with_trend, against_trend)."""
    votes = 0
    r6 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 6)   # 1) زخم M1 قويّ في اتجاهنا
    if r6 is not None and len(r6) >= 5 and atr1 > 0:
        mv = float(r6["close"][-1] - r6["close"][-5])
        if abs(mv) / atr1 >= 0.3 and (1 if mv > 0 else -1) == d:
            votes += 1
    tr = struct.get("trend")                                   # 2) ترند/بنية M5 يوافق
    with_trend = (d > 0 and tr == "up") or (d < 0 and tr == "down")
    against_trend = (d > 0 and tr == "down") or (d < 0 and tr == "up")
    votes += 1 if with_trend else 0
    pat = csig.get("pat", "")                                  # 3) الشمعة توافق
    if d > 0 and (pat in ("hammer", "marubozu_up") or csig.get("bounce_strength", 0) >= 0.6):
        votes += 1
    elif d < 0 and pat in ("shooting_star", "marubozu_dn"):
        votes += 1
    if df is not None:                                         # 4) تدفّق الأوامر (دلتا) يوافق فعلاً (تصويت حقيقيّ)
        fl = df.flow(sym)
        if fl and ((d > 0 and fl["bias"] >= 8) or (d < 0 and fl["bias"] <= -8)):
            votes += 1
    if _deep_confirm(sym, d):                                  # 5) العقل العميق يوافق
        votes += 1
    score = votes / 5.0
    tier = "قوية" if score >= 0.7 else "عادية" if score >= 0.4 else "ضعيفة"
    return score, tier, with_trend, against_trend


def _gov_mult():
    """🎚️ مضاعِف حوكمة المايسترو لهذا المحرّك (يخنق النزّاف). fail-safe = 1.0 (ملفّ مفقود/تالف ⇒ بلا أثر)."""
    try:
        g = json.load(open(RN / "engine_governance.json", encoding="utf-8"))
        return max(0.1, min(1.5, float(g.get("mults", {}).get(str(MAGIC), 1.0))))
    except Exception:
        return 1.0


def _is_paused():
    """🔥 هل أقال المايسترو سكالب الذهب (نزّاف كارثيّ مُثبت)؟ ⇒ لا يفتح جديداً (الإدارة تستمرّ). آمن=False."""
    try:
        g = json.load(open(RN / "engine_governance.json", encoding="utf-8"))
        return MAGIC in [int(x) for x in g.get("paused", [])]
    except Exception:
        return False


_BULL_KW = ("hammer", "bull", "_up", "morning", "pierc", "dragonfly", "tweezer_b")   # تشكيلات صعوديّة
_BEAR_KW = ("shoot", "bear", "_dn", "_down", "evening", "dark", "gravestone", "tweezer_t")  # هبوطيّة


def _candle_confirms(sym, sdir):
    """تشريح شمعيّ عميق (شرط المستخدم): تشكيلة انعكاسيّة في اتجاهنا أو رفضٌ بذيلٍ واضح — ونرفض الإضافة
    إن كانت الشمعة الحاليّة استمراراً صريحاً عكسنا (لا نشتري تحت شمعة هبوطيّة، ولا نبيع تحت صعوديّة)."""
    if ca is None:
        return True
    sig = ca.last_signal(sym) or {}
    pat = str(sig.get("pat", "")).lower()
    bs = float(sig.get("bounce_strength", 0) or 0)
    bull = any(k in pat for k in _BULL_KW); bear = any(k in pat for k in _BEAR_KW)
    if sdir > 0:
        return (bull or bs >= 0.4) and not bear
    return (bear or bs >= 0.4) and not bull


def _level_rejected_before(sym, price, sdir, atr):
    """ذاكرة المستوى (شرط المستخدم: «الشموع السابقة على نفس السعر وش كانت عليه»): نمسح ~180 شمعة M5،
    ونعدّ اللمسات السابقة لهذا المستوى (±0.5ATR): هل رُفض في صالحنا (دعمٌ لشراء/مقاومةٌ لبيع) أكثر مما
    اخترق؟ لا نضيف استرداداً عند مستوًى تاريخه الاختراق لا الرفض."""
    if atr <= 0:
        return False
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 180)
    if r is None or len(r) < 30:
        return False
    o = r["open"]; c = r["close"]; h = r["high"]; l = r["low"]
    band = 0.5 * atr; rej = 0; brk = 0
    for i in range(2, len(r) - 1):
        rng = float(h[i] - l[i]) or 1e-9
        if sdir > 0:
            if abs(float(l[i]) - price) <= band:                       # لمسة قاعٍ قرب المستوى
                if float(c[i]) > float(o[i]) or (float(c[i]) - float(l[i])) > 0.5 * rng:
                    rej += 1                                            # أغلقت أعلى/ذيل سفليّ ⇒ رفضٌ صعوديّ (دعم)
                elif float(c[i]) < price - band:
                    brk += 1                                            # أغلقت تحت المستوى ⇒ اختراق هابط
        else:
            if abs(float(h[i]) - price) <= band:
                if float(c[i]) < float(o[i]) or (float(h[i]) - float(c[i])) > 0.5 * rng:
                    rej += 1
                elif float(c[i]) > price + band:
                    brk += 1
    return rej >= 2 and rej > brk


def _recovery_add(sym, eq):
    """🪂 استرداد بزخم مؤكَّد (أسلوب المستخدم): كومتنا حمراء (اشترينا قمماً/بِعنا قيعاناً) والزخم ارتدّ فعلاً
    لصالحنا من طرفٍ مناسب ⇒ نضيف مركزاً محكوماً في اتجاه الكومة (يحسّن المتوسّط ويركب الارتداد) + معلّقاً أعمق
    (بلا وقف). ليس مارتنغيل: الشرط هو **زخم ارتدّ لصالحنا**، لا مجرّد سعرٍ أرخص. محكوم + مسقوف + هامش + سبريد.
    يعمل حتى في التراجع العميق (يُستدعى قبل تهدئة الرشّ). يرجع وصفاً عند الإضافة، أو None."""
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    if not mine or len(mine) >= RECOVERY_MAX_PER_SYM:
        return None
    sdir = 1 if mine[0].type == 0 else -1
    netpl = sum(p.profit for p in mine)
    if netpl >= -max(2.0, eq * STACK_RED_PCT / 100.0):       # ليست حمراء بعمق ⇒ لا حاجة لاسترداد
        return None
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    if not info or not tk or atr1 <= 0:
        return None
    if (tk.ask - tk.bid) > SPREAD_MAX_ATR * atr1:            # سبريد واسع عكسنا = لا
        return None
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 30)
    if r is None or len(r) < 12:
        return None
    c = r["close"]; h = r["high"]; l = r["low"]
    price = float(c[-1]); mv5 = float(c[-1] - c[-6])
    hi = float(h.max()); lo = float(l.min())
    if hi <= lo:
        return None
    pos = (price - lo) / (hi - lo)                            # موقع السعر في مدى آخر 30د (0=قاع 1=قمّة)
    avg = sum(p.price_open * p.volume for p in mine) / sum(p.volume for p in mine)
    if sdir > 0:   # كومة شراء: قرب القاع + زخم 5د صاعد مؤكَّد + السعر تحت متوسّطنا (نحسّنه)
        ok = pos < 0.40 and mv5 > RECOVERY_MOM * atr1 and price < avg
    else:          # كومة بيع: قرب القمّة + زخم 5د هابط مؤكَّد + السعر فوق متوسّطنا
        ok = pos > 0.60 and mv5 < -RECOVERY_MOM * atr1 and price > avg
    if not ok:
        return None
    # ── اشتراطات عميقة (شرط المستخدم): لا نقبل على الزخم وحده ──
    if not _candle_confirms(sym, sdir):                      # 🕯️ تشريح شمعيّ: تشكيلة/رفض انعكاسيّ في اتجاهنا
        return None
    if not _level_rejected_before(sym, price, sdir, atr1):   # 🧠 ذاكرة المستوى: رُفض هذا السعر سابقاً في صالحنا
        return None
    flow_ok = (df is None) or df.confirms(sym, sdir)         # 📊 مؤشّر واضح: تدفّق الأوامر يؤكّد اتجاهنا
    rsi = _rsi(sym, mt5.TIMEFRAME_M5)
    rsi_ok = (sdir > 0 and rsi < 68) or (sdir < 0 and rsi > 32)   # ليس متطرّفاً ضدّنا (مجال للحركة)
    if not (flow_ok and rsi_ok):
        return None
    if dc is not None:                                       # 🛑 فيتو الخسارة المُثبتة: لا نسترد باتجاهٍ مُثبت خسارته
        _m, _t, _cok = dc.conviction(sym, "BUY" if sdir > 0 else "SELL")
        if not _cok:
            return None
    acct = mt5.account_info()                                # 🛡️ هامش الحساب كلّه (لا نغذّي ضغط الهامش)
    if acct and acct.margin > 0 and (acct.margin_level or 1e9) < MARGIN_MIN_PCT:
        return None
    sl_dist = SL_ATR * atr1; ts = info.trade_tick_size or info.point; tv = info.trade_tick_value
    step = info.volume_step or 0.01
    rpu = (sl_dist / ts) * tv if (ts and tv) else 0
    if rpu <= 0:
        return None
    lot = (eq * AGGR_RISK_PCT / 100.0) / rpu * _gov_mult()    # 🎚️ محكوم بالمايسترو
    lot = max(info.volume_min, round(lot / step) * step)
    lot = min(lot, info.volume_min * MAX_LOT_MULT, info.volume_max or lot)
    if lot_guard:
        lot, _ = lot_guard.cap(mt5, sym, lot, eq)          # 🛑 سقف صلب 2% (ضبط الذهب — الحجم لا يدمّر)
    entry = tk.ask if sdir > 0 else tk.bid
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if sdir > 0 else mt5.ORDER_TYPE_SELL,
                          "price": entry, "sl": 0.0, "tp": 0.0, "deviation": 30, "magic": MAGIC,
                          "comment": "recov", "type_filling": mt5.ORDER_FILLING_IOC})
    if getattr(res, "retcode", None) != mt5.TRADE_RETCODE_DONE:
        return None
    plimit = round(entry - RECOVERY_LIMIT_ATR * atr1 if sdir > 0 else entry + RECOVERY_LIMIT_ATR * atr1, info.digits)
    mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),   # المعلّق الأعمق (بلا وقف)
                    "type": mt5.ORDER_TYPE_BUY_LIMIT if sdir > 0 else mt5.ORDER_TYPE_SELL_LIMIT,
                    "price": plimit, "sl": 0.0, "tp": 0.0, "magic": MAGIC, "comment": "recov_lim",
                    "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
    _log(f"🪂 استرداد {sym} {'شراء' if sdir>0 else 'بيع'} {lot} @{entry:.2f} (زخم {mv5/atr1:+.2f}ATR موقع {pos:.0%} متوسّط {avg:.2f} عائم ${netpl:.0f}) + معلّق @{plimit}")
    _record_gold("recovery_add", sym, d=sdir, lot=lot, entry=entry, atr1=atr1, spread=tk.ask - tk.bid)
    return ("شراء" if sdir > 0 else "بيع", lot, entry)


def _try_symbol(sym, eq, cooldowns):
    """يرشّ، ويُهرّم (زيد النار حطب) على الرابح حين الاتجاه مؤكَّد (زخم قويّ + العقل العميق يوافق)."""
    if not _open(sym):
        return "مغلق", False
    if _is_paused():                          # 🔥 أقاله المايسترو (نزّاف كارثيّ) ⇒ لا فتح، الإدارة في الحلقة مستمرّة
        return "🔥 مُقال (المايسترو) — إدارة فقط، لا فتح", False
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    if atr1 <= 0 or not tk or not info:
        return "لا بيانات", False
    spread = tk.ask - tk.bid
    d = _mom_dir(sym)
    rev = _reverse_to.pop(sym, None)                        # 🔄 «نعكس الأوامر»: بعد إغلاق رابح على انعكاس
    reversing = bool(rev and time.time() - rev[1] < 4 and rev[0] != 0)   # نافذة عكس ضيّقة (4ث) — أقلّ مطاردة كاذبة
    if reversing:
        d = rev[0]                                          # نركب الاتجاه الجديد (لا يزال يمرّ ببوّابة الرغبة + التحجيم)
    rsi = _rsi(sym, mt5.TIMEFRAME_M5)
    hurst = (ni.novel_features(sym).get("hurst_b") if ni else "?")
    fib50 = _big_drop(sym, atr1)                            # مستوى فيبو 50% (هدف الارتداد) أو None
    csig = ca.last_signal(sym) if ca else {"bounce_strength": 1.0, "pat": "?"}
    # 🪂 شراء الارتداد: كسر هبوطي كبير + رفض القاع (مطرقة/ذيل سفلي طويل) + ليس متشبّعاً شرائياً
    bounce = (fib50 is not None and rsi < BOUNCE_RSI_MAX
              and csig.get("bounce_strength", 0) >= 0.3)
    if bounce:
        d = 1
    if d == 0:
        return "لا زخم", False
    if spread > _P["spread_max_atr"] * atr1:
        return "سبريد واسع", False
    if d > 0 and rsi > 70 and not bounce:               # لا نشتري في التشبّع الشرائي (إلا ارتداد)
        return "تشبّع شرائي (فيتو)", False
    if d < 0 and rsi < 30 and not bounce:               # 🪂 لا نبيع في التشبّع البيعي — نتوقّع ارتداداً (أسلوبك)
        return "تشبّع بيعي (ننتظر ارتداداً لا نبيع)", False
    struct = ms.structure(sym, "M5") if ms else {"trend": "?", "label": "?"}
    # 🪂 ارتداد: البائعون يجب أن يبدأوا بالنضوب (تدفّق ينعكس صعوداً) — لا نُمسك سكّيناً هابطة
    if bounce and df is not None and not df.exhausting(sym, 1):
        return "ارتداد لكن البائعون ما زالوا يقودون — ننتظر النضوب", False
    # ⚖️ بوّابة الرغبة (أسلوبك: الاتجاهان مسموحان «عادي»، لكن الأكثر مع الالتقاء — زخم+ترند+شمعة+تدفّق+عقل):
    score, tier, with_trend, against = _confluence(sym, d, struct, csig, atr1)
    # 🔥 ركوب الزخم (طلب المستخدم): زخمٌ قويّ **متوافق مع الترند** = اختراق حقيقيّ ⇒ ندخل معه حتى لو الالتقاء
    # متواضع أو قرب الطرف (نركب النار). نطلب توافق الزخم+الترند+الاتجاه كي لا نركب ارتداداً عكسياً (سكّيناً هابطة).
    r6r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 6)
    _mv = float(r6r["close"][-1] - r6r["close"][-5]) if (r6r is not None and len(r6r) >= 5) else 0.0
    ride = (atr1 > 0 and abs(_mv) / atr1 >= MOM_RIDE and with_trend and (1 if _mv > 0 else -1) == d)
    if not bounce and not ride:
        if against and tier != "قوية":                 # ضدّ الترند يتطلّب رغبة قويّة (التقاء ≥70%)
            return f"ضدّ الترند ({struct.get('label')}) برغبة {tier} {score:.0%} — ننتظر التقاءً أقوى", False
        if tier == "ضعيفة":                            # رغبة ضعيفة = ضوضاء ⇒ نُفلتر (يقلّل الإفراط + ضغط الهامش)
            return f"رغبة ضعيفة (التقاء {score:.0%}) — ننتظر زخم/ترند/شمعة/تدفّق", False
    # 🚫 لا نشتري قرب القمة ولا نبيع قرب القاع — إلا برغبة قويّة أو **ركوب زخم** (اختراق). البديل: أمر محدّد عند الذهبية.
    if not bounce and not ride and tier != "قوية" and atr1 > 0:
        lh = struct.get("last_high"); ll = struct.get("last_low")
        if d > 0 and lh and 0 <= (lh - tk.bid) < 0.5 * atr1:
            return f"قرب القمة ({lh}) — لا شراء عند الطرف (إلا رغبة قويّة أو أمر محدّد أدنى)", False
        if d < 0 and ll and 0 <= (tk.bid - ll) < 0.5 * atr1:
            return f"قرب القاع ({ll}) — لا بيع عند الطرف (إلا رغبة قويّة أو أمر محدّد أعلى)", False
    # 🔄 عكس آمن: لا نعكس بزخم عارٍ ضدّ بنية لم تُكسَر بعد (BOS) — نطلب تأكيد انقلاب البنية
    if reversing and against and not struct.get("bos"):
        return f"عكس ضدّ بنية {struct.get('label')} بلا كسر BOS — ننتظر تأكيد الانعكاس", False
    # 🛑 فيتو الخسارة المُثبتة (Bonferroni على صفقات منفّذة حقيقية) — حلقة تجنّب-خسارة مُفعّلة، تشديد فقط
    if dc is not None:
        _m, _t, _ok = dc.conviction(sym, "BUY" if d > 0 else "SELL")
        if not _ok:
            return f"فيتو مُثبت (خسارة Bonferroni {sym} {'BUY' if d>0 else 'SELL'})", False
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    netdir = (1 if sum((1 if p.type == 0 else -1) for p in mine) >= 0 else -1) if mine else 0
    netpl = sum(p.profit for p in mine)
    # 🚫 لا تكديس على خاسر (مضادّ-مارتنغيل + علاج جذر انهيار «+80% ثم يهجّ»): إن كانت كومتنا على الرمز
    # أحمر أعمق من STACK_RED_PCT% من الحقوق، لا نفتح المزيد — ندع الموجود يجري لانعكاسه ولا نضيف للخسارة.
    # (التكديس بلا وقف هو ما حوّل صفقة ذهب واحدة إلى −$100). الرابح يتهرّم أدناه كالعادة (netpl>0).
    if mine and netpl < -max(2.0, eq * STACK_RED_PCT / 100.0):
        return f"كومة حمراء ${netpl:.0f} على {sym} — إدارة فقط، لا تكديس (مضادّ-مارتنغيل)", False
    # 🔥 تهرّم: زِد على الرابح إن الاتجاه مؤكَّد (زخم قويّ في اتجاهنا + ليس عشوائياً + العقل العميق يوافق)
    pyramid = False
    if mine and netpl > 0 and netdir == d:
        r6 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 6)
        if r6 is not None and len(r6) >= 5:
            mv = float(r6["close"][-1] - r6["close"][-5])
            if (abs(mv) / atr1 >= CONFIRM_SPEED and (1 if mv > 0 else -1) == d
                    and hurst != "random" and _deep_confirm(sym, d)
                    and (df is None or df.confirms(sym, d))):   # 📊 التدفّق ما زال يقود اتجاهنا
                pyramid = True
    cap = PYRAMID_MAX if pyramid else MAX_POS_PER_SYM
    if len(mine) >= cap:
        return ("سقف تهرّم" if pyramid else "سقف مراكز"), False
    strong = (tier == "قوية")                          # 🔥 رغبة قويّة = التقاء ≥70% ⇒ فرصة فوريّة تتجاوز التهدئة
    if not pyramid and not bounce and not strong and not reversing and (time.time() - cooldowns.get(sym, 0) < _P["cooldown_s"]):
        return "تهدئة", False                          # التهرّم/الارتداد/الرغبة-القويّة/العكس تتجاوز التهدئة (الفرصة فوراً)
    # 🔥 «ادعس»: حجم حسب المخاطرة (يستهدف AGGR_RISK_PCT%) بدل أدنى-لوت، مع سقف أمان 15×
    sl_dist = SL_ATR * atr1
    ts = info.trade_tick_size or info.point; tv = info.trade_tick_value
    step = info.volume_step or 0.01
    rpu = (sl_dist / ts) * tv if (ts and tv) else 0     # مخاطرة لكل 1.0 لوت
    if rpu <= 0:
        return "لا تحجيم", False
    lot = (eq * AGGR_RISK_PCT / 100.0) / rpu
    lot = lot * _gov_mult()                             # 🎚️ حوكمة المايسترو: يخنق المحرّك النزّاف صافي-التكلفة
    lot = max(info.volume_min, round(lot / step) * step)
    lot = min(lot, info.volume_min * MAX_LOT_MULT, info.volume_max or lot)
    if lot_guard:
        lot, _ = lot_guard.cap(mt5, sym, lot, eq)          # 🛑 سقف صلب 2% (ضبط الذهب — الحجم لا يدمّر)
    acct2 = mt5.account_info()                          # 🛡️ فحص هامش حيّ لحظة الإرسال (يغلق فجوة الـ2ث قبل الكاسكيد)
    if acct2 and acct2.margin > 0 and (acct2.margin_level or 1e9) < MARGIN_MIN_PCT:
        return f"هامش حيّ {acct2.margin_level:.0f}% < {MARGIN_MIN_PCT}% — لا فتح", False
    entry = tk.ask if d > 0 else tk.bid
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL,
                          "price": entry, "sl": 0.0, "tp": 0.0,   # 🚫 لا وقف ولا هدف — إدارة جماعية بالزخم
                          "deviation": 30, "magic": MAGIC, "comment": "pyr" if pyramid else "scalp",
                          "type_filling": mt5.ORDER_FILLING_IOC})
    rc = getattr(res, "retcode", None)
    if rc == mt5.TRADE_RETCODE_DONE:
        cooldowns[sym] = time.time()
        if bounce:
            _bounce_tgt[sym] = fib50                        # هدف فيبو 50% للارتداد
        kind = "🔄 عكس" if reversing else "🔥 تهرّم" if pyramid else "🪂 ارتداد" if bounce else ("🔥 رغبة-قويّة" if strong else "رشّ")
        _log(f"{kind} {sym} {'BUY' if d>0 else 'SELL'} {lot} @{entry:.2f} (رغبة {tier} {score:.0%} | بنية {struct.get('label','?')} شمعة {csig.get('pat','?')} rsi {rsi:.0f})")
        _record_gold(f"open:{kind}", sym, d=d, score=score, tier=tier, struct=struct,   # 📝 سياق الدخول الكامل
                     rsi=rsi, spread=spread, atr1=atr1, lot=lot, entry=entry, retcode=rc)
        return f"{kind} {'شراء' if d>0 else 'بيع'} @{entry:.2f} (رغبة {score:.0%})", True
    return f"فشل rc={rc}", False


def _save(st):
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def main():
    claim("gold_scalper")                      # 🔒 قفل نسخة-مفردة (لا تداول مزدوج)
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    _load_params()
    _log(f"scalper start — {SYMBOLS} magic {MAGIC} (أسلوبك: لوت صغير + TP سريع + رشّ) | معاملات حيّة: {_P}")
    cooldowns = {}
    while True:
        try:
            st = {"ts": time.time(), "magic": MAGIC, "symbols": {}}
            if KILL.exists():
                st["state"] = "kill_switch"; _save(st); time.sleep(POLL_S); continue
            acct = mt5.account_info()
            if not acct:
                time.sleep(POLL_S); continue
            _srv = str(getattr(acct, "server", "") or "")   # 🛡️ حاجز ديمو (تدقيق C3 2026-07-08): ديمو-فقط
            if not ("Trial" in _srv or "Demo" in _srv):
                st["state"] = "not_demo"; _save(st); time.sleep(30); continue
            eq = acct.equity
            _load_params()                            # 🔄 ضبط ذاتيّ حيّ (تشديد-فقط، fail-safe)
            st["params"] = _P
            allmine = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
            st["open_positions"] = len(allmine)
            for sym in SYMBOLS:                        # 🔄 إدارة جماعية أولاً (دائماً، حتى عند السقف)
                _manage(sym)
            # 🪂 تمرير الاسترداد (أسلوب المستخدم): يعمل **حتى في التراجع العميق** (قبل تهدئة الرشّ أدناه) —
            # إضافة بزخم مؤكَّد فقط في اتجاه كومتنا الحمراء + معلّق. محكوم + مسقوف + هامش + سبريد داخل الدالة.
            if not KILL.exists() and not _is_paused() and len(allmine) < RECOVERY_MAX_TOTAL:
                for sym in SYMBOLS:
                    try:
                        rv = _recovery_add(sym, eq)
                        if rv:
                            st["symbols"][sym] = f"🪂 استرداد {rv[0]} {rv[1]}"
                    except Exception as e:
                        _log(f"recov err {sym}: {type(e).__name__}: {e}")
            # 🚫 لا نُغلق على خسارة (أسلوبك). البديل: لا نضيف رشّاً في تراجع عائم عميق (نُمسك حتى الأخضر).
            floatpl = sum(p.profit for p in allmine)
            dd_pct = (-floatpl / eq * 100.0) if (eq and floatpl < 0) else 0.0
            if dd_pct >= PAUSE_DD_PCT:
                st["state"] = f"تراجع عائم {dd_pct:.1f}% — أوقفتُ الرشّ (نُمسك، لا نُغلق على خسارة). الكارثة: الأرضية فقط"
                _save(st); time.sleep(POLL_S); continue
            if len(allmine) >= MAX_POS_TOTAL:
                st["state"] = "سقف المراكز الكلّي (إدارة فقط)"; _save(st); time.sleep(POLL_S); continue
            # 🛡️ حارس الهامش الكلّيّ (درس أزمة الهامش 2026-06-27): لا نرشّ إن ضاق هامش الحساب — يشمل
            # مراكزك اليدوية. السكالب كان أعمى يرى مراكزه فقط فغذّى الكاسكيد. الآن يحترم هامش الحساب كلّه.
            ml = acct.margin_level or 0.0
            if acct.margin > 0 and ml < MARGIN_MIN_PCT:
                st["state"] = f"هامش الحساب {ml:.0f}% < {MARGIN_MIN_PCT}% — إدارة فقط، لا نُغذّي ضغط الهامش"
                _save(st); time.sleep(POLL_S); continue
            for sym in SYMBOLS:
                state, opened = _try_symbol(sym, eq, cooldowns)
                st["symbols"][sym] = state
                if opened:
                    break
            st["state"] = "نشط (يرشّ + يدير جماعياً | الذهب أسرع 4×)"
            _save(st)
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        # 🥇 دورة الذهب السريعة: ندير الذهب وحده كل GOLD_MANAGE_S داخل فترة POLL_S (تفاعل أسرع 4× للانعكاس/القفل).
        # قراءات MT5 داخل _manage رخيصة على الاتصال الواحد المفتوح — استطلاع مؤدّب (0.5ث)، لا اتصال جديد ولا حلقة محمومة.
        t_end = time.time() + POLL_S
        while time.time() < t_end:
            if KILL.exists():
                break
            try:
                _manage(GOLD)
            except Exception as e:
                _log(f"gold fast err: {type(e).__name__}: {e}")
            time.sleep(GOLD_MANAGE_S)


if __name__ == "__main__":
    main()
