# -*- coding: utf-8 -*-
"""pipflow_core.py — محلّل-متداول مستقلّ لكل رمز عبر فريمات (مثل تطبيق PipFlow). magic 20260629.

(ديمو فقط، windowless تحت الوصيّ، اتصال MT5 واحد، قفل نسخة-مفردة.)

لكل رمز كل دورة:
  (1) تحليل متعدّد الفريمات (M5/M15/H1) بإعادة استخدام rbridge/analysis.setup() — خطّة فيبو الذهبية
      (اتجاه/دخول/منطقة ذهبية/أهداف) + chart_read مؤشرات + SMC بنية/أوردر-بلوك. لكل رمز تحليله الخاصّ.
  (2) على التقاء قويّ متوافق عبر الفريمات ⇒ أمر سوق (لوت صغير محكوم).
  (3) أوامر محدّدة (limit) عند المناطق (الذهبية/OB/FVG) كي يأتي إليها السعر — بلا وقف (دع الرابح يجري).
  (4) ركوب الزخم: زخمٌ قويّ متوافق مع الترند (|mom|/ATR≥0.8) ⇒ دخول سوق حتى عند التقاء متواضع.
  (5) تعلّم خفيف لكل رمز (يتتبّع صافي الرمز الأخير ⇒ يكيّف الثقة/التحجيم — مضادّ-مارتنغيل).
  الإدارة: دع الرابح يجري / لا نُغلق على خسارة صافية أبداً (مذهب المستخدم) + قفل متحرّك + إغلاق على انعكاس.

أمان صلب (7 قواعد، غير قابلة للتفاوض):
  1) مضادّ-مارتنغيل: لا نزيد اللوت بعد خسارة أبداً؛ نكبّر فقط على أرباح مُثبتة، ونصغّر بعد الخسائر. لا تعويض.
  2) ديمو فقط: نرفض إن لم يكن الخادم Trial/Demo أو login 262998147.
  3) محكوم: نقرأ gov_mult/is_paused(20260629)؛ نخنق اللوت، وإن أُقيل ⇒ إدارة فقط بلا فتح. مُسجّل بالمايسترو.
  4) لا عاصفة عمليّات: محرّك واحد، mt5.initialize واحد، قفل engine_lock.claim('pipflow_core').
  5) حارس الكلفة: بوّابة سبريد (نتخطّى إن السبريد > ~0.4×ATR).
  6) سقف مخاطرة ≤2%/صفقة، نحترم kill_switch (وقف الفتح)، لا نلمس master_floor، مضادّ-تحوّط portfolio_guard.
  7) لا نلمس أبداً مجيكات خارجية {2447,20250418,20250421,20250422,20250618} ولا اليدويّ 0.

تشغيل: pythonw pipflow_core.py
"""
from __future__ import annotations
from engine_lock import claim
import sys, json, time
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "rbridge") not in sys.path:
    sys.path.insert(0, str(ROOT / "rbridge"))

import analysis as an                       # rbridge/analysis: setup() خطّة فيبو الذهبية + smc() مناطق رقميّة
try:
    import chart_read as cr                  # مؤشرات (read_local: dir/confluence) — تصويت مستقلّ
except Exception:
    cr = None
try:
    from engine_gov import gov_mult, is_paused   # 🎚️ حوكمة المايسترو المشتركة (لا نعيد تنفيذ قراءة json)
except Exception:
    def gov_mult(m, lo=0.1, hi=1.5): return 1.0
    def is_paused(m): return False
try:
    from portfolio_guard import would_hedge        # مضادّ-تحوّط عابر للمحرّكات
except Exception:
    def would_hedge(mt, s, ot, mm): return (False, "")
try:
    import candle_anatomy as ca             # شمعة انعكاسيّة للإدارة
except Exception:
    ca = None
try:
    from friday_db import FridayDB          # 📝 تأريخ كل قرار (رخيص، لا يرفع استثناءً)
    _DB = FridayDB()
except Exception:
    _DB = None

MAGIC = 20260629
RN = ROOT / "data" / "r_native"
KILL = ROOT / "kill_switch.txt"
STATUS = RN / "pipflow_status.json"
LOG = RN / "pipflow.log"

# 🥇 الذهب + عملات FX الكبرى + الكريبتو (ثمانية إلى اثنا عشر رمزاً منطقياً)
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "BTCUSDm", "ETHUSDm"]
PROTECTED = {0, 2447, 20250418, 20250421, 20250422, 20250618}   # 🚫 لا تُلمَس أبداً (قاعدة 7)

POLL_S = 6.0                # دورة كاملة لكل الرموز (محلّل لا سكالب محموم)
RISK_PCT = 1.5             # أساس مخاطرة لكل صفقة — ليس AGGR_RISK_PCT 2.5 الخاصّ بالذهب
RISK_CAP_PCT = 2.0         # 🚧 سقف صلب فعليّ (قاعدة 6): حتى لو ضرب gov×size المضاعِفات، المخاطرة ≤ 2% من الحقوق
SL_ATR = 1.20             # مسافة افتراضيّة لتقدير الحجم فقط (لا يُوضَع وقف فعليّ — مذهب بلا وقف)
SPREAD_MAX_ATR = 0.40      # 🛡️ بوّابة الكلفة (قاعدة 5): نتخطّى إن السبريد > 0.4×ATR (الكلفة عنق الزجاجة)
MARGIN_MIN_PCT = 250.0     # لا فتح إن هبط مستوى الهامش تحته (حماية من كاسكيد stop-out)
MAX_LOT_MULT = 8          # سقف اللوت ≤ 8× الأدنى
MAX_POS_PER_SYM = 3        # رشّ محدود لكل رمز
MAX_POS_TOTAL = 12
MAX_PENDINGS_PER_SYM = 3   # أوامر محدّدة عند المناطق لكل رمز
PAUSE_DD_PCT = 8.0         # تراجع عائم أعمق ⇒ نوقف الفتح (نُمسك، لا نُغلق على خسارة)
MOM_RIDE = 0.8            # 🔥 ركوب الزخم: |mom|/ATR ≥ هذا متوافق مع الترند ⇒ دخول سوق
LOCK_ARM_USD = 4.0        # تسلَّح القفل المتحرّك حين بلغ الربح هذا$
LOCK_GIVEBACK = 0.45      # اقفل إن تراجع الربح إلى 45% من قمته
SPREAD_REV_ATR = 0.50     # سبريد عالٍ عكسنا وقت الانعكاس = تأكيد ⇒ اقفل
# مضادّ-مارتنغيل (قاعدة 1): التحجيم يعتمد على صافي الرمز الأخير فقط — لا عدد مراكز ولا تعويض.
WIN_BUMP_CAP = 1.30       # أقصى تكبير على أرباح مُثبتة
LOSS_CUT_FLOOR = 0.50     # أقصى تصغير بعد خسائر
LEARN_K = 12              # نافذة آخر K صفقة مغلقة لكل رمز

_peak_pl = {}             # {sym: قمة الربح العائم} للقفل المتحرّك
_cool = {}                # {sym: آخر وقت فتح}
COOLDOWN_S = 8


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _is_demo():
    """قاعدة 2: ديمو فقط — Trial/Demo بالخادم أو login 262998147 (Exness Trial يبلغ trade_mode=0 خطأً)."""
    try:
        ai = mt5.account_info()
        srv = (ai.server or "") if ai else ""
        return ("Trial" in srv) or ("Demo" in srv) or (ai is not None and ai.login == 262998147)
    except Exception:
        return False


def _atr(sym, tf, n=14):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def _open(sym):
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    return bool(info and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL and tk and (time.time() - tk.time) < 180)


def _record(action, sym, tf=None, d=0, conf=None, regime=None, entry=None, risk=None, **extra):
    if _DB is None:
        return
    try:
        _DB.record_signal(symbol=sym, tf=tf or "M5", dir=(int(d) if d else None), confluence=conf,
                          regime=regime, entry=entry, risk=risk, source="pipflow_core",
                          extra={"action": action, **extra})
    except Exception:
        pass


def _recent_net(sym):
    """تعلّم خفيف لكل رمز: صافي آخر LEAN_K صفقة مغلقة لنا على الرمز (صافي-التكلفة). آمن=0."""
    try:
        deals = mt5.history_deals_get(time.time() - 14 * 86400, time.time()) or []
        mine = [d for d in deals if d.magic == MAGIC and d.symbol == sym and d.entry == 1]
        mine = mine[-LEARN_K:]
        return sum(d.profit + d.commission + d.swap for d in mine), len(mine)
    except Exception:
        return 0.0, 0


def _size_mult(sym):
    """🛡️ مضادّ-مارتنغيل (قاعدة 1): نكبّر فقط على أرباح مُثبتة، نصغّر بعد خسائر. لا تعويض، لا عدّ مراكز.
    أسوأ حالة لملفّ تاريخ مفقود = 1.0 (الحجم الأساسيّ فقط). لا شيء في هذا المسار يرفع اللوت بعد خسارة."""
    net, n = _recent_net(sym)
    if n < 3:                                   # عيّنة ناقصة ⇒ الحجم الأساسيّ فقط
        return 1.0
    if net > 0:                                 # أرباح مُثبتة ⇒ تكبير متحفّظ مسقوف
        return min(WIN_BUMP_CAP, 1.0 + min(0.30, net / 50.0))
    if net < 0:                                 # خسائر ⇒ تصغير (عكس الكتاب اليدويّ −$28k)
        return max(LOSS_CUT_FLOOR, 1.0 + max(-0.50, net / 50.0))
    return 1.0


def _mtf_align(sym):
    """تحليل متعدّد الفريمات لكل رمز: setup(M5/M15/H1) (خطّة فيبو الذهبية) + chart_read dir.
    يرجع (d, score, setups, conf) حيث d=±1 إن اتّفقت الفريمات، 0 إن اختلفت."""
    try:
        s5 = an.setup(sym, "M5"); s15 = an.setup(sym, "M15"); s1 = an.setup(sym, "H1")
    except Exception:
        return 0, 0.0, [], 0.0
    setups = [s5, s15, s1]
    dirs = []
    for s in setups:
        if isinstance(s, dict) and s.get("valid"):
            dirs.append(1 if s.get("direction") == "BUY" else -1)
    if not dirs:
        return 0, 0.0, setups, 0.0
    # تأكيد مستقلّ من chart_read (≈40 مؤشّراً موزوناً) لكل فريم — نتجنّب اعتماد H1 على بنية M5 (gotcha)
    conf = 0.0
    if cr is not None:
        for tf in ("M5", "M15", "H1"):
            try:
                rd = cr.read_local(mt5, sym, tf)
                if rd:
                    dirs.append(int(rd.get("dir") or 0))
                    conf = max(conf, float(rd.get("confluence") or 0.0))
            except Exception:
                pass
    votes = [v for v in dirs if v != 0]
    if not votes:
        return 0, 0.0, setups, conf
    s = sum(votes)
    d = 1 if s > 0 else -1 if s < 0 else 0
    agree = sum(1 for v in votes if v == d) / len(votes)        # نسبة الاتّفاق على الاتجاه السائد
    # درجة = اتّفاق الفريمات × متوسّط درجة الإعداد (0..6) — التقاء قويّ = اتّفاق تامّ + إعداد عالٍ
    setup_score = np.mean([s.get("score", 0) for s in setups if isinstance(s, dict) and s.get("valid")] or [0]) / 6.0
    score = agree * (0.5 + 0.5 * setup_score)
    return d, float(score), setups, conf


def _momentum_ride(sym, d, atr1):
    """🔥 ركوب الزخم (قاعدة 4): |mom|/ATR ≥ MOM_RIDE متوافق مع الترند والاتجاه d."""
    r6 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 6)
    if r6 is None or len(r6) < 5 or atr1 <= 0:
        return False
    mv = float(r6["close"][-1] - r6["close"][-5])
    return abs(mv) / atr1 >= MOM_RIDE and (1 if mv > 0 else -1) == d


def _lot(sym, eq, atr1, info):
    """تحجيم محكوم: أساس eq×RISK_PCT (≤2%، قاعدة 6) × gov_mult (قاعدة 3) × مضادّ-مارتنغيل (قاعدة 1)."""
    sl_dist = SL_ATR * atr1                                # مسافة افتراضيّة للتحجيم فقط (لا وقف فعليّ)
    ts = info.trade_tick_size or info.point; tv = info.trade_tick_value
    step = info.volume_step or 0.01
    rpu = (sl_dist / ts) * tv if (ts and tv) else 0
    if rpu <= 0:
        return 0.0
    lot = (eq * RISK_PCT / 100.0) / rpu                    # ⬆️ السقف على 2% (RISK_PCT=1.5)
    lot *= gov_mult(MAGIC)                                 # 🎚️ حوكمة المايسترو (قاعدة 3)
    lot *= _size_mult(sym)                                 # 🛡️ مضادّ-مارتنغيل (قاعدة 1) — لا يزيد بعد خسارة
    lot = min(lot, (eq * RISK_CAP_PCT / 100.0) / rpu)      # 🚧 سقف صلب 2% فعليّ (قاعدة 6) — يُبطِل تجاوز المضاعِفات (gov 1.5×size 1.3=2.9%→2%)
    lot = max(info.volume_min, round(lot / step) * step)
    lot = min(lot, info.volume_min * MAX_LOT_MULT, info.volume_max or lot)
    try:
        import lot_guard                                   # 🛑 السقف الصلب المُثبت OOS (الحجم = الرافعة الوحيدة)
        lot, _ = lot_guard.cap(mt5, sym, lot, eq)
    except Exception:
        pass
    return float(lot)


def _market(sym, d, lot):
    tk = mt5.symbol_info_tick(sym)
    if not tk:
        return None
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL,
                          "price": tk.ask if d > 0 else tk.bid, "sl": 0.0, "tp": 0.0,   # 🚫 بلا وقف
                          "deviation": 30, "magic": MAGIC, "comment": "pipflow-mkt",
                          "type_filling": mt5.ORDER_FILLING_IOC})
    return getattr(res, "retcode", None)


def _pending(sym, otype, price, lot, info, tp=None):
    """أمر محدّد عند منطقة — بلا وقف (مذهب المستخدم: دع الرابح يجري). يدور على أنماط التعبئة."""
    t = {"BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT}.get(otype)
    if t is None:
        return None
    req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot), "type": t,
           "price": round(float(price), info.digits), "deviation": 50, "magic": MAGIC,
           "comment": "pipflow-pend", "type_time": mt5.ORDER_TIME_GTC}   # 🚫 لا مفتاح sl
    if tp:
        req["tp"] = round(float(tp), info.digits)
    for fill in (mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK):
        req["type_filling"] = fill
        r = mt5.order_send(req)
        if r is None:
            return None
        if r.retcode == mt5.TRADE_RETCODE_DONE:
            return r.retcode
        if r.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
            continue
        return r.retcode
    return None


def _place_zone_limits(sym, d, setups, lot, info, tk):
    """قاعدة 3 من المهمّة: أوامر محدّدة عند المناطق (الذهبية/OB/FVG) كي يأتي السعر إليها — بلا وقف.
    BUY ⇒ BUY_LIMIT أسفل السعر؛ SELL ⇒ SELL_LIMIT أعلى السعر."""
    have = len([o for o in (mt5.orders_get(symbol=sym) or []) if o.magic == MAGIC])
    if have >= MAX_PENDINGS_PER_SYM:
        return 0
    cur = (tk.bid + tk.ask) / 2.0
    zones = []
    for s in setups:                                       # المنطقة الذهبية لكل إعداد صالح
        if isinstance(s, dict) and s.get("valid"):
            gz = s.get("golden_zone") or []
            if len(gz) == 2:
                zones.append((gz[0] + gz[1]) / 2.0)
            if s.get("entry"):
                zones.append(float(s["entry"]))
    try:
        sm = an.smc(sym, "M5")                             # مناطق OB / FVG الرقميّة
        for key in ("ob_zone", "fvg_zone"):
            z = sm.get(key)
            if z and len(z) >= 2:
                zones.append((float(z[0]) + float(z[1])) / 2.0)
    except Exception:
        pass
    placed = 0
    seen = set()
    for px in zones:
        if have + placed >= MAX_PENDINGS_PER_SYM:
            break
        key = round(px, info.digits)
        if key in seen or px <= 0:
            continue
        seen.add(key)
        if d > 0 and px < cur * 0.9995:                    # BUY_LIMIT أسفل السعر فقط
            if _pending(sym, "BUY_LIMIT", px, lot, info) == mt5.TRADE_RETCODE_DONE:
                placed += 1
        elif d < 0 and px > cur * 1.0005:                  # SELL_LIMIT أعلى السعر فقط
            if _pending(sym, "SELL_LIMIT", px, lot, info) == mt5.TRADE_RETCODE_DONE:
                placed += 1
    if placed:
        _log(f"أوامر محدّدة {sym} {'BUY_LIMIT' if d>0 else 'SELL_LIMIT'} ×{placed} عند المناطق (بلا وقف)")
    return placed


def _close_all(sym, reason):
    closed = 0
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != MAGIC:                               # 🚫 قاعدة 7: لا نلمس إلا مجيكنا
            continue
        tk = mt5.symbol_info_tick(sym)
        if not tk:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": p.volume,
                            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                            "position": p.ticket, "price": tk.bid if p.type == 0 else tk.ask,
                            "deviation": 50, "magic": MAGIC, "comment": f"close-{reason}",
                            "type_filling": mt5.ORDER_FILLING_IOC})
        closed += int(getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE)
    if closed:
        _log(f"إغلاق {sym}: {closed} ({reason})")
        _record("close:" + reason, sym, retcode=closed)
    return closed


def _manage(sym):
    """دع الرابح يجري / لا نُغلق على خسارة صافية أبداً (قاعدة 6/مذهب) + قفل متحرّك + إغلاق على انعكاس واضح."""
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    if not mine:
        _peak_pl.pop(sym, None)
        return
    netpl = sum(p.profit for p in mine)
    if netpl <= 0:                                         # 🚫 لا نُغلق على خسارة — نُمسك حتى يعود أخضر
        return
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 4)
    if r is None or len(r) < 3 or atr1 <= 0:
        return
    netdir = 1 if sum((1 if p.type == 0 else -1) for p in mine) >= 0 else -1
    pk = _peak_pl.get(sym, 0.0)
    if netpl > pk:
        _peak_pl[sym] = pk = netpl
    if pk >= LOCK_ARM_USD and netpl <= pk * LOCK_GIVEBACK:   # 💰 قفل متحرّك (يعمل في الربح فقط ⇒ لا يكسر المذهب)
        _close_all(sym, f"قفل-متحرّك ({netpl:.1f}$ من قمّة {pk:.1f}$)"); _peak_pl.pop(sym, None); return
    move = float(r["close"][-1] - r["close"][-3]); speed = abs(move) / atr1
    mdir = 1 if move > 0 else -1
    tk = mt5.symbol_info_tick(sym)
    adverse_spread = bool(tk) and (tk.ask - tk.bid) >= SPREAD_REV_ATR * atr1
    mom_rev = speed >= 0.55 and mdir != netdir
    pat = (ca.last_signal(sym).get("pat", "") if ca else "")
    candle_rev = ((netdir == 1 and pat in ("shooting_star", "marubozu_dn", "bearish_engulfing"))
                  or (netdir == -1 and pat in ("hammer", "marubozu_up", "bullish_engulfing")))
    st = an.ms.structure(sym, "M5") if getattr(an, "ms", None) else {}
    struct_rev = bool(st.get("bos")) and ((netdir == 1 and st.get("trend") == "down")
                                          or (netdir == -1 and st.get("trend") == "up"))
    if (mom_rev or candle_rev or struct_rev) and adverse_spread:   # انعكاس واضح + سبريد ⇒ تأمين أكبر ربح
        _close_all(sym, "انعكاس واضح + سبريد"); _peak_pl.pop(sym, None)


def _try_symbol(sym, eq, paused):
    if not _open(sym):
        return "مغلق"
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    if not info or not tk or atr1 <= 0:
        return "لا بيانات"
    if (tk.ask - tk.bid) > SPREAD_MAX_ATR * atr1:          # 🛡️ قاعدة 5: بوّابة الكلفة
        return "سبريد واسع"
    d, score, setups, conf = _mtf_align(sym)
    if d == 0:
        return "فريمات غير متّفقة"
    ride = _momentum_ride(sym, d, atr1)                    # 🔥 قاعدة 4
    strong = score >= 0.70                                 # التقاء قويّ متوافق ⇒ سوق
    if not strong and not ride:
        return f"التقاء {score:.0%} — أوامر محدّدة فقط"     # نضع أوامر عند المناطق وننتظر (أدناه)
    # مضادّ-تحوّط (قاعدة 6): لا نفتح بعكس محرّك آخر من محرّكاتنا على نفس الرمز
    blocked, why = would_hedge(mt5, sym, 0 if d > 0 else 1, MAGIC)
    if blocked:
        return "مضادّ-تحوّط: " + why
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    if len(mine) >= MAX_POS_PER_SYM:
        return "سقف مراكز الرمز"
    if not strong and time.time() - _cool.get(sym, 0) < COOLDOWN_S:
        return "تهدئة"
    acct = mt5.account_info()                              # حارس هامش حيّ
    if acct and acct.margin > 0 and (acct.margin_level or 1e9) < MARGIN_MIN_PCT:
        return f"هامش {acct.margin_level:.0f}% < {MARGIN_MIN_PCT}%"
    lot = _lot(sym, eq, atr1, info)
    if lot <= 0:
        return "لا تحجيم"
    rc = _market(sym, d, lot)
    if rc == mt5.TRADE_RETCODE_DONE:
        _cool[sym] = time.time()
        kind = "🔥 ركوب-زخم" if ride and not strong else "التقاء-قويّ"
        _log(f"{kind} {sym} {'BUY' if d>0 else 'SELL'} {lot} @{tk.ask if d>0 else tk.bid:.5f} (درجة {score:.0%} conf {conf:.0%})")
        _record(f"open:{kind}", sym, d=d, conf=score, entry=(tk.ask if d > 0 else tk.bid), risk=lot,
                ride=ride, strong=strong, chart_conf=conf, retcode=rc)
        # أوامر محدّدة إضافيّة عند المناطق (قاعدة 3) بنفس الاتجاه
        try:
            _place_zone_limits(sym, d, setups, lot, info, tk)
        except Exception:
            pass
        return f"{kind} {'شراء' if d>0 else 'بيع'} (درجة {score:.0%})"
    return f"فشل rc={rc}"


def _zones_only(sym, eq):
    """عند التقاء غير قويّ: نضع أوامر محدّدة عند المناطق كي يأتي السعر إليها (بلا فتح سوق)."""
    if not _open(sym):
        return
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atr1 = _atr(sym, mt5.TIMEFRAME_M1)
    if not info or not tk or atr1 <= 0:
        return
    if (tk.ask - tk.bid) > SPREAD_MAX_ATR * atr1:
        return
    d, score, setups, _ = _mtf_align(sym)
    if d == 0 or score < 0.40:                             # نحتاج اتّجاهاً متّفقاً ولو متواضعاً
        return
    blocked, _ = would_hedge(mt5, sym, 0 if d > 0 else 1, MAGIC)
    if blocked:
        return
    lot = _lot(sym, eq, atr1, info)
    if lot > 0:
        try:
            _place_zone_limits(sym, d, setups, lot, info, tk)
        except Exception:
            pass


def _save(st):
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def main():
    claim("pipflow_core")                                  # 🔒 قاعدة 4: قفل نسخة-مفردة (لا تداول مزدوج)
    if not (mt5.initialize() or mt5.initialize()):         # اتصال MT5 واحد (درس عاصفة العمليّات 2026-06-28)
        _log("mt5 init failed"); return
    if not _is_demo():                                     # 🚫 قاعدة 2: ديمو فقط — نرفض الحساب الحقيقيّ
        _log("ليس ديمو — رفض التشغيل (قاعدة الأمان 2)"); _save({"state": "رُفض: ليس ديمو"}); return
    _log(f"pipflow start — {SYMBOLS} magic {MAGIC} (محلّل-متداول لكل رمز عبر فريمات، مضادّ-مارتنغيل، ديمو)")
    while True:
        try:
            st = {"ts": time.time(), "magic": MAGIC, "symbols": {}}
            acct = mt5.account_info()
            if not acct:
                time.sleep(POLL_S); continue
            eq = acct.equity
            allmine = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
            st["open_positions"] = len(allmine)
            for sym in SYMBOLS:                            # 🔄 الإدارة أولاً دائماً (تستمرّ حتى تحت kill_switch/الإيقاف)
                try:
                    _manage(sym)
                except Exception as e:
                    _log(f"manage {sym}: {type(e).__name__}")
            paused = is_paused(MAGIC)                       # 🎚️ قاعدة 3: أُقيل المحرّك ⇒ إدارة فقط
            killed = KILL.exists()                          # 🛑 قاعدة 6: kill_switch يوقف الفتح فقط (الإدارة تستمرّ)
            if paused or killed:
                st["state"] = ("🔥 مُقال (المايسترو) — إدارة فقط" if paused else "🛑 kill_switch — إدارة فقط")
                _save(st); time.sleep(POLL_S); continue
            floatpl = sum(p.profit for p in allmine)
            dd = (-floatpl / eq * 100.0) if (eq and floatpl < 0) else 0.0
            if dd >= PAUSE_DD_PCT:                          # تراجع عائم عميق ⇒ لا فتح (نُمسك، لا نُغلق على خسارة)
                st["state"] = f"تراجع عائم {dd:.1f}% — إدارة فقط"; _save(st); time.sleep(POLL_S); continue
            if len(allmine) >= MAX_POS_TOTAL:
                st["state"] = "سقف المراكز الكلّي — إدارة فقط"; _save(st); time.sleep(POLL_S); continue
            ml = acct.margin_level or 0.0
            if acct.margin > 0 and ml < MARGIN_MIN_PCT:
                st["state"] = f"هامش الحساب {ml:.0f}% — إدارة فقط"; _save(st); time.sleep(POLL_S); continue
            opened = False
            for sym in SYMBOLS:
                state = _try_symbol(sym, eq, paused)
                st["symbols"][sym] = state
                if state.startswith(("التقاء", "🔥", "🔥 ركوب")) and ("شراء" in state or "بيع" in state):
                    opened = True
                    break
                if "أوامر محدّدة فقط" in state:             # التقاء متواضع ⇒ نضع أوامر عند المناطق
                    _zones_only(sym, eq)
            st["state"] = "نشط (يحلّل + سوق على التقاء قويّ + أوامر محدّدة عند المناطق)" if not opened else "فتح صفقة"
            _save(st)
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
