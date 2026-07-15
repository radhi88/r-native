"""army_warroom.py — غرفة حرب حيّة: لكل عملة "فرقة" تقرأ كل فريم، **تُحاسَب بسبورة نتائج**،
و(اختيارياً) **تنفّذ صفقات حيّة** على الإشارات القوية — كل شيء أمامك في الطرفية (لا خلفية/متصفّح).

ثلاث طبقات:
  1) قراءة: ترند M5/M15/H1 + زخم + تذبذب + بنية + إجماع + ثقة + هدف مُسقَط لكل فرقة.
  2) سبورة (تعلّم/إثبات): تسجّل كل إشارة وتُقيّمها لاحقاً → سجلّ حيّ (إصابة% + توقّع R) لكل عملة.
  3) تنفيذ حيّ (DEMO) للإشارات القوية فقط، بحدود صارمة، magic 20260618.

⚠️ صدق: التنفيذ على إشارات غير مُثبتة → غالب الخسارة أولاً (ديمو، محدود). السبورة تكشف الرابح
فنُبقيه ونوقف الخاسر. هذا "يتعلّمون بالعمل" بحدود. القرار الحقيقي يبقى للفرق التي تُثبت إصابة.

Run (طرفية مرئية):  army_warroom.bat   أو   .venv\\Scripts\\python.exe army_warroom.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5
import portfolio_guard as pg
import deep_conviction as dc
import session_gate as sgate
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console, Group
from rich.text import Text
from rich.align import Align

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
SCORE_F = RN / "army_scoreboard.json"
KILL_F = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")   # إيقاف طارئ: وجوده يوقف الفتح فوراً
console = Console()

FOCUS = ["XAUUSDm", "BTCUSDm", "ETHUSDm", "SOLUSDm", "BNBUSDm",
         # 🪙 البيتكوين وأزواجه — مُقدَّمة دائماً للتعلّم بالظلّ (السبورة تحكم على حركة السعر بلا تكلفة؛
         # التنفيذ الحيّ يبقى مقيّداً بالبوابة الصافية n≥15/net>0.05/t>2 التي تطرح السبريد، فالأزواج
         # واسعة السبريد تتعلّم لكن لا تُنفَّذ أبداً حتى تُثبت حافّة صافية):
         "BTCUSDTm", "BTCJPYm", "BTCXAUm", "BTCXAGm", "BTCAUDm",
         "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "NZDUSDm",
         # 🌐 توسيع كل أزواج الفوركس (طلب المستخدم): مُقدَّمة للتعلّم؛ غير-المُثبت = أصغر لوت فقط حتى يُثبت حافّة صافية:
         "EURGBPm", "EURJPYm", "GBPJPYm", "AUDJPYm", "CADJPYm", "CHFJPYm", "USDCHFm",
         "EURAUDm", "NZDJPYm", "AUDNZDm", "AUDCADm", "EURCADm", "GBPAUDm", "EURCHFm",
         "US30m", "USTECm", "US500m", "XAGUSDm", "USOILm", "JP225m", "GER40m", "DE30m"]
MAX_SYMBOLS = 35          # 🌐 توسيع لكل الأزواج (طلب المستخدم): يمسح 245 ويتداول حتى 35/دورة. المخاطرة محدودة: غير-المُثبت=أصغر لوت حتى n≥15/net_t>2 + سقف المراكز MAX_POS=18
MAX_SPREAD_PCT = 0.18     # استبعد واسعة السبريد (TRY/ZAR/SEK تنزف سبريداً)

# 🩸 استبعاد رموز النزيف (بيانات 30 يوماً، 1001 صفقة، صافي −$371): (أ) المعادن XAU*/XAG* (سبريد مدموج
# عالٍ: الذهب وحده −$99 رغم 82% فوز = يربح صغيراً ويخسر كبيراً)، (ب) المرفوعة x10/x100 (مخاطرة مضخّمة)،
# (ج) رموز نازفة صريحة مُثبتة. يُطبَّق على مخرجات _select_symbols فيغطّي FOCUS والقائمة معاً.
import re as _re
BLEED_SYMS = {"JP225m", "USDJPYm", "BTCUSDTm", "GBPCHFm", "EURNZDm", "GBPNZDm", "XAUGBPm", "XAUEURm"}


def _excluded(sym):
    """True لو الرمز يُستبعَد: معدن (XAU/XAG) أو مرفوع (_x10/_x100) أو في قائمة النزيف الصريحة."""
    s = str(sym).upper()
    if s.startswith("XAU") or s.startswith("XAG"):
        return True
    if _re.search(r"_X\d+", s):
        return True
    return sym in BLEED_SYMS


def _is_open(s, mt5_):
    """السوق مفتوح فعلاً: تنفيذ كامل + تيك حديث (<180ث). يستبعد المغلق بعطلة/جلسة
    (فوركس/مؤشرات/معادن في الويكند تيكها راكد) فيُتداوَل ما هو مفتوح حقاً (الكريبتو في العطلة)."""
    try:
        info = mt5_.symbol_info(s)
        if not info or info.trade_mode != mt5_.SYMBOL_TRADE_MODE_FULL:
            return False
        tk = mt5_.symbol_info_tick(s)
        return bool(tk and (time.time() - tk.time) < 180)
    except Exception:
        return False


def _select_symbols(mt5_):
    """يبني الفرق من كل عملاتك (245) مفلترةً بالسيولة (سبريد%) ثم **بالسوق المفتوح**.
    الأولوية للكبار، ثم الأسيَل؛ ويُقصَر على المفتوح فعلاً (أي سوق فاتح يدخله — طلب المستخدم)."""
    try:
        univ = json.loads((RN / "market_watch_symbols.json").read_text(encoding="utf-8"))
    except Exception:
        univ = list(FOCUS)
    rows = []
    for s in univ:
        info = mt5_.symbol_info(s)
        if info is None:
            try: mt5_.symbol_select(s, True)
            except Exception: pass
            info = mt5_.symbol_info(s)
        if info is None or not info.point: continue
        px = info.bid or info.ask or 0
        if px <= 0: continue
        rows.append((s, (info.spread * info.point) / px * 100))
    rows.sort(key=lambda x: x[1])                              # الأسيَل أولاً
    have = {s for s, _ in rows}
    liquid = [s for s, sp in rows if sp <= MAX_SPREAD_PCT]
    pri = [s for s in FOCUS if s in have and not _excluded(s)]  # الكبار أولاً، بلا معادن/مرفوعة/نازفة
    cand = pri + [s for s in liquid if s not in pri and not _excluded(s)]
    # 🟢 تداول المفتوح فعلاً: في العطلة = كريبتو (BTC/ETH...)؛ في الأسبوع = الكل. احتياط لو تعذّر الكشف.
    open_cand = [s for s in cand if _is_open(s, mt5_)]
    base = open_cand if open_cand else cand
    return base[:MAX_SYMBOLS], len(rows), len(rows) - len(liquid)
TFS = [("M1", mt5.TIMEFRAME_M1), ("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)]
REFRESH_S = 12          # النواة الكاملة أثقل قليلاً → دورة أبطأ (قرار M15 لا يحتاج ثواني)

# 🧠 تطوّر ذاتي #2: السبورة توقف تنفيذ أي فرقة يُثبت سجلّها الأمامي أنها خاسرة (عيّنة كافية)
SCORE_MIN_N = 8         # لا تحكم على فرقة قبل هذا العدد
SCORE_MIN_EXPR = -0.05  # توقّع/صفقة أسوأ من هذا (بعد العيّنة) → أوقف تنفيذها

_CR = None
def _chart_read():
    global _CR
    if _CR is None:
        try: import chart_read as _m; _CR = _m
        except Exception: _CR = False
    return _CR or None

# ضد التجمّد: القرار الثقيل (chart_read) مُخبّأ بـTTL ويُعاد حساب عدد محدود فقط كل دورة (round-robin)،
# بينما العرض الخفيف (سعر/أسهم الفريمات) يتحدّث لكل العملات كل دورة → اللوحة تتحرّك مع السوق دائماً.
DECISION_TTL = 120          # ثانية: عمر قرار chart_read قبل إعادة حسابه
HEAVY_PER_CYCLE = 6         # كم فرقة تُعيد حساب النواة الثقيلة كل دورة
_DEC_CACHE = {}

# ===== تنفيذ حيّ (DEMO) — عدواني لكن ناجٍ =====
EXECUTE = True
EXEC_MAGIC = 20260618
MIN_CONF = 0.58          # توازن (طلب المستخدم: تنفيذ الآن): يتداول السوق الحيّ على رموز منخفضة التكلفة (لا معادن). 0.58 يدخل
                         # الإعدادات الأقوى المتوافقة مع الترند فقط، نزيف أبطأ. master_floor يحرس.
EXPLORE_MIN_CONF = 0.62  # استكشاف معتدل على رموز منخفضة التكلفة (ديمو، أصغر لوت)
MIN_CONS = 2             # 2 من 3 فريمات محاذية (كان 3 = نادر جداً)
MAX_PER_SYMBOL = 2       # تشديد: تكديس أقل بكثير بنفس العملة (نزيف أقل)
MAX_POS = 18             # تشديد: تعرّض أقل بكثير. master_floor يبقى حاجز الكارثة (−50% من القمة)
MAX_PER_CCY = 4          # 🌐 سقف التعرّض لكل عملة: أقصى مراكز تشترك في عملةٍ واحدة (يحدّ الرهان المترابط: long EUR/USD+GBP/USD+short USD/CAD = رهان USD واحد)
LOT_HARD = 0.30          # لوت أكبر (عدواني) — الكارثة يحكمها master_floor فقط
MAX_TRADE_RISK = 2.0     # 🛡️ أُرجِع لـ2% (المستخدم: «الخسائر أكبر كمبلغ» عند 4%). حجم اللوت قرصٌ واحد يحرّك الربح
                         # والخسارة معاً؛ فضّلنا مبالغ خسارة أصغر على هجوميّة أكبر. حتى المُثبت يبقى محافظاً (2% سقفاً).
                         # السقف الكلّيّ PORTFOLIO_RISK_PCT=25% + master_floor. (لتقليل أكثر: اخفض لـ1.0 أو دع الكلّ أصغر-لوت.)
# 🟡 سماح معادن على حساب صغير (طلب المستخدم صراحةً): الذهب/المعادن أصغر لوت يخاطر >2% على $100،
# فبدل التخطّي نسمح بسقف أعلى محدود METAL_RISK_CAP ونشدّ الوقف ليُلائم أصغر لوت (وقف أضيق = توقّفات
# ضوضاء أكثر، مقابل إمكان دخول الذهب). مقيّد: مركز واحد فقط (لا تكديس) + مع-الاتجاه فقط (الفيتو موجود).
# ليس نظاماً انتحارياً: مركز ذهب واحد بـ%6 مع-الترند على ديمو. يعود تلقائياً لـ2% متى لاءم أصغر لوت.
METAL_RISK_CAP = 2.0     # 🛡️ أُعيد لـ2% (المعادن مُستبعَدة هنا أصلاً عبر _excluded؛ سقف احتياطيّ آمن)
METAL_MAX_POS = 1        # تشديد: مركز معدن واحد فقط (لا تكديس)
METAL_SL_ATR_FLOOR = 0.6 # لا نشدّ وقف المعادن أضيق من هذا×ATR (تجنّب توقّف ضوضاء مفرط)
# 🎚️ تحجيم اللوت حسب الثقة لكل عملة (طلب المستخدم): فرقة مُثبتة-صافياً تبدأ بهذه النسبة وتتدرّج للسقف.
CONF_BASE_RISK = 2.0     # نقطة بداية المخاطرة% لفرقة مُثبتة (ترتفع مع قوة الثقة الصافية حتى _cap)
CONF_FULL_N = 40         # لا يُسمح بالوصول للسقف الكامل إلا بعيّنة ≥ هذا (مقاومة السلسلة الرابحة)
SL_ATR = 1.5
MIN_MARGIN = 120.0       # واقع الهامش فقط (تجنّب نداء الهامش قبل أن يعمل master_floor) — ليس سقف خسارة
MAX_DD_PCT = 60.0        # معطّل عملياً: master_floor يصفّي عند −50% أولاً (أُبقي فوقه احتياطاً)
PORTFOLIO_RISK_PCT = 25.0  # 🛡️ أُعيد التحجيم (على $143: 25% = ~$36 مخاطرة مُلتزمة < حاجز الأرضية $58 ⇒ البوّابة تعمل قبل الأرضية)
                           # (رُفع 15→20 لإفساح مجال التكديس على الرابح المؤكّد دام المارجن — لكنه يبقى السقف)
                           # (يحدّ تراكم المخاطر المترابطة في الوضع العدواني — رأينا 19% على صفقات AUD متعدّدة)
DAILY_HALT_PCT = 8.0       # 🛡️ أُعيد حدّ يوميّ 8% (يوقف الفتح بعد خسارة يوم 8% ⇒ يحدّ نزيف الاستكشاف العريض). master_floor يبقى حاجز الكارثة
JUDGE_HORIZON_S = 45 * 60   # تُقيَّم الإشارة بعد 45د (أو عند الهدف/الوقف) — كان ساعتين = فرز بطيء جداً
                            # (n=2 بعد ساعات)؛ 45د تسرّع التعلّم ~2.7× فيُحظر الخاسر أسرع ويرتقي الرابح
COOLDOWN_S = 600         # ⚡ 2026-07-15 (أمر «صفقاته قليلة جداً»): 30د→10د بين الإضافات — على 35 رمزاً
                         # كان الخانق الأكبر. الحماية باقية: MAX_POS=18 + سقف 2% + lot_guard + الأرضية.


def _ema(c, n):
    k = 2.0 / (n + 1); e = c[0]
    for x in c[1:]: e = x * k + e * (1 - k)
    return e


def _rsi(c, n=14):
    if len(c) < n + 1: return 50.0
    d = np.diff(c[-(n + 1):]); up = d[d > 0].sum(); dn = -d[d < 0].sum()
    return 100.0 if dn == 0 else 100 - 100 / (1 + (up / n) / (dn / n))


def _atr(h, l, c, n=14):
    pc = c[:-1]; tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    return float(np.mean(tr[-n:])) if len(tr) >= n else 0.0


def tf_read(symbol, tf):
    r = mt5.copy_rates_from_pos(symbol, tf, 0, 120)
    if r is None or len(r) < 30: return None
    o = np.array([x["open"] for x in r], float); h = np.array([x["high"] for x in r], float)
    l = np.array([x["low"] for x in r], float); c = np.array([x["close"] for x in r], float)
    ema8 = _ema(c[-60:], 8); ema21 = _ema(c[-60:], 21); atr = _atr(h, l, c)
    trs = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    volp = float((trs[-1] >= trs[-100:]).mean() * 100) if len(trs) >= 30 else 50.0
    return {"px": c[-1], "atr": atr, "trend": 1 if ema8 > ema21 else -1, "rsi": _rsi(c), "volp": volp}


def squad(symbol, allow_heavy=True):
    # قراءات خفيفة لكل فريم (تتحدّث كل دورة — السعر/الأسهم تتحرّك مع السوق دائماً)
    reads = {name: tf_read(symbol, tf) for name, tf in TFS}
    reads = {k: v for k, v in reads.items() if v}
    if not reads: return None
    base = reads.get("M15") or list(reads.values())[0]
    atr, px = base["atr"], base["px"]
    cons = sum(rd["trend"] for rd in reads.values())   # محاذاة الفريمات (تتحدّث كل دورة)
    # ===== القرار الثقيل من النواة (30+ مصوّت/SMC/أخبار/أوزان متعلّمة) — مُخبّأ بـTTL + round-robin =====
    dec = _DEC_CACHE.get(symbol)
    fresh = dec and (time.time() - dec[0] < DECISION_TTL)
    if not fresh and allow_heavy:
        cr = _chart_read()
        if cr:
            try:
                d_ = cr.read_local(mt5, symbol, "M15")
            except Exception:
                d_ = None
            if d_ and d_.get("dir") is not None:
                dd = int(d_["dir"]); v = d_.get("votes", {}); w = d_.get("weights", {})
                top = sorted([(k, abs(v[k] * w.get(k, 0))) for k in v if v[k] == dd and v[k] != 0],
                             key=lambda x: -x[1])[:2]
                dec = (time.time(), {"dir": dd, "conf": float(d_.get("confluence", 0.0)),
                                     "regime": d_.get("regime", "?"), "drivers": "+".join(k for k, _ in top) or "—"})
                _DEC_CACHE[symbol] = dec
    if dec:
        D = dec[1]; d = D["dir"]; conf = D["conf"]; regime = D["regime"]; drivers = D["drivers"]
        sig = "BUY" if d > 0 else ("SELL" if d < 0 else "WAIT")
    else:
        d = 0; conf = 0.0; regime = "?"; drivers = "…"; sig = "WAIT"   # لم يُحسب بعد — السعر/الأسهم تظهر فوراً
    return {"reads": reads, "sig": sig, "tgt": px + d * 2 * atr if d else px, "conf": round(conf, 2),
            "px": px, "atr": atr, "rsi": base["rsi"], "volp": base["volp"], "cons": cons, "dir": d,
            "regime": regime, "drivers": drivers}


# ===== سبورة النتائج (إثبات/تعلّم) =====
def _load_score():
    try: return json.loads(SCORE_F.read_text(encoding="utf-8"))
    except Exception: return {"pending": [], "stats": {}}


def _save_score(s):
    try:
        tmp = SCORE_F.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False,
                                  default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
        os.replace(tmp, SCORE_F)
    except Exception as e:
        print(f"[WARROOM] _save_score failed: {type(e).__name__}: {e}", flush=True)


def record_and_judge(sym, s, score, now):
    """سجّل إشارة جديدة (عند تغيّر الاتجاه) وقيّم المعلّقة المنتهية. يُحدّث stats[sym]."""
    if s["sig"] in ("BUY", "SELL"):
        # سجّل فقط عند عدم وجود معلّق نشط لنفس العملة (إشارة جديدة)
        if not any(p["sym"] == sym for p in score["pending"]):
            d = 1 if s["sig"] == "BUY" else -1
            risk = SL_ATR * s["atr"]
            score["pending"].append({"sym": sym, "dir": d, "entry": s["px"], "risk": risk,
                                     "tgt": s["tgt"], "sl": s["px"] - d * risk, "t": now})
    # قيّم معلّقات هذه العملة
    still = []
    for p in score["pending"]:
        if p["sym"] != sym:
            still.append(p); continue
        d = p["dir"]; px = s["px"]; r = None
        if (px - p["entry"]) * d >= (p["tgt"] - p["entry"]) * d: r = (p["tgt"] - p["entry"]) * d / p["risk"]
        elif (px - p["entry"]) * d <= -(p["risk"]): r = -1.0
        elif now - p["t"] >= JUDGE_HORIZON_S: r = (px - p["entry"]) * d / p["risk"] if p["risk"] else 0
        if r is None:
            still.append(p)
        else:
            st = score["stats"].setdefault(sym, {"n": 0, "wins": 0, "sumR": 0.0})
            st["n"] += 1; st["wins"] += (r > 0); st["sumR"] += round(r, 3)
    score["pending"] = still


def _is_volatile(sym):
    """رموز يصنع فيها الدخول عكس الاتجاه خسائر ذيل كارثية (مُثبت OOS): معادن/نفط/مؤشرات/كريبتو."""
    s = sym.upper()
    if s.startswith("XAU") or s.startswith("XAG") or "OIL" in s or "BTC" in s or "ETH" in s:
        return True
    return any(ix in s for ix in ("US30", "US500", "USTEC", "JP225", "DE30", "GER40", "UK100", "US2000", "HK50", "NAS"))


# ===== تنفيذ حيّ (DEMO) =====
def maybe_execute(sym, s, info, acct, total_pos, last_exec, halt, score=None):
    if not EXECUTE or halt or s["sig"] == "WAIT": return None
    # 📼 بوّابة الجلسة (30 يوماً: london الرابحة الوحيدة؛ asia −$184 و ny −$196 تنزفان): دخول جديد فقط في
    # لندن (08-13 UTC) + تداخل نيويورك المبكّر/الذروة (13-17 UTC). آسيا/نيويورك-المتأخّرة/الانتقال = لا دخول.
    # entry-only: إدارة/إغلاق/تثبيت الوقف للمراكز القائمة تبقى حيّة في باقي الدورة (مثل kill_switch).
    try:
        if not sgate.session_allows_entry():   # بوّابة مدفوعة بالبيانات: الجلسة المُثبتة حيّة، غيرها ظلّ (احتياط: لندن+نيويورك)
            return None
    except Exception:
        pass   # فشل آمن: لا نُجمّد التنفيذ عند خطأ البوّابة
    if s["conf"] < MIN_CONF or abs(s["cons"]) < MIN_CONS: return None
    # 🧭 حارس الذيل (مُثبت OOS): رمز متقلّب + الإشارة عكس M15&H1 المتفقين = سكين ساقط → امنع. سببي (شموع مغلقة).
    if _is_volatile(sym):
        rd = s.get("reads", {}) or {}
        m15t = (rd.get("M15") or {}).get("trend", 0); h1t = (rd.get("H1") or {}).get("trend", 0)
        sd = 1 if s["sig"] == "BUY" else -1
        if m15t == h1t and m15t != 0 and sd != m15t:
            return None
    # 🧠 تدرّج الفرق (inline، بلا وحدة خارجية = بلا اصطدام أسماء): يوقف النزيف على الإشارات غير المُثبتة.
    #   BANNED (خاسر مُثبت: n≥4 وتوقّع<−0.05) → لا تنفيذ حيّ (يبقى يُقيَّم بالورق فيمكن أن يتعافى ويرتقي).
    #   PROVEN (n≥6 وتوقّع>+0.05) → لوت كامل.  EXPLORE (غير ذلك) → أصغر لوت فقط (يُفرض أدناه) = نزيف ضئيل.
    st = score["stats"].get(sym) if score else None
    _exp = (st["sumR"] / st["n"]) if (st and st.get("n")) else 0.0
    # PROVEN = معنوية إحصائية حقيقية (لا مجرّد n≥6): n≥15 و توقّع×√n > 2 (≈2 سيغما، sd≈1 لوحدات R).
    # هكذا اللوت الكامل لا يذهب إلا لحافّة مُثبتة بالأرقام لا بالحظّ (طلب المستخدم: إشارات قوية بالبيانات).
    _proven = bool(st and st["n"] >= 15 and _exp * (st["n"] ** 0.5) > 2.0)
    if st and st["n"] >= 4 and _exp < -0.05:
        return None
    if not _proven and s["conf"] < EXPLORE_MIN_CONF:
        return None   # استكشاف انتقائي: الفرق غير المُثبتة لا تستكشف إلا الإشارات الأقوى → رسوم تعلّم أقل
                      # (المُثبتة تتداول من MIN_CONF؛ هذا يقلّل خسائر غرفة الحرب على الإشارات الضعيفة)
    if total_pos >= MAX_POS: return None
    if time.time() - last_exec.get(sym, 0) < COOLDOWN_S: return None
    # 🛡️ حارس خطر-المحفظة: مجموع الخطر الملتزَم (كل الأوقاف المفتوحة) لا يتجاوز السقف → يحدّ تراكم
    # المخاطر المترابطة (الرموز الغالية تتجاوز 2%/صفقة بأصغر لوت؛ هذا يحكم الإجمالي بدل الفرد)
    open_risk = 0.0
    for p in (mt5.positions_get() or []):
        if p.magic != EXEC_MAGIC or not p.sl:
            continue
        pi = mt5.symbol_info(p.symbol)
        if pi and pi.trade_tick_size:
            open_risk += abs(p.price_open - p.sl) / pi.trade_tick_size * pi.trade_tick_value * p.volume
    if open_risk >= acct.equity * PORTFOLIO_RISK_PCT / 100.0:
        return None
    d = 1 if s["sig"] == "BUY" else -1
    # سقف ومراكز خاصة بالمعادن (مرفوع لكن محدود) مقابل بقية الرموز (2% الافتراضي)
    _metal = _is_volatile(sym)
    _cap = METAL_RISK_CAP if _metal else MAX_TRADE_RISK
    _maxpos = METAL_MAX_POS if _metal else MAX_PER_SYMBOL
    # تكديس مع الترند فقط: حتى _maxpos، وبشرط أن تكون مراكز العملة الحالية رابحة (لا تعميق على خاسر)
    mine = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == EXEC_MAGIC]
    if len(mine) >= _maxpos: return None
    if mine:
        if sum(p.profit for p in mine) <= 0: return None          # خاسرة → لا تُضِف (لا متوسّط هابط)
        if any((1 if p.type == 0 else -1) != d for p in mine): return None  # نفس الاتجاه فقط
    tk = mt5.symbol_info_tick(sym)
    if not tk: return None
    entry = tk.ask if d > 0 else tk.bid
    sl_dist = SL_ATR * s["atr"]
    if sl_dist <= 0: return None
    tv = info.trade_tick_value; ts = info.trade_tick_size
    # 🟡 معادن: بدل التخطّي، شدّ الوقف ليُلائم أصغر لوت ضمن السقف المرفوع (_cap)، دون النزول تحت الأرضية.
    if _metal and tv > 0 and ts > 0 and info.volume_min > 0:
        max_sl = (acct.equity * _cap / 100.0) / (info.volume_min / ts * tv)   # أقصى مسافة وقف ضمن السقف
        if sl_dist > max_sl:
            sl_dist = max(METAL_SL_ATR_FLOOR * s["atr"], max_sl)
    sl = round(entry - d * sl_dist, info.digits); tp = round(entry + d * 2 * sl_dist, info.digits)
    # 🛑 منع صارم بحجم-الحساب: لو حتى أصغر لوت يتجاوز السقف (_cap) → تخطّ الرمز (يُعاد تلقائياً متى كبر الحساب).
    if tv > 0 and ts > 0 and info.volume_min * (sl_dist / ts) * tv > acct.equity * _cap / 100.0:
        return None
    # 🎚️ تحجيم اللوت حسب الثقة الصافية لكل عملة (طلب المستخدم: نزيد اللوت عند ثقة قوية لكل عملة).
    # صافي = توقّع السبورة (إجمالي) − تكلفة السبريد الحالية بوحدات R → لا نكبّر على ضوضاء/سلسلة-رابحة إجمالية.
    # كلما قويت الثقة الصافية المعنوية كبر اللوت تدريجياً حتى السقف؛ عيّنة كبيرة شرط للسقف (مقاومة السلسلة).
    spread_R = ((tk.ask - tk.bid) / sl_dist) if sl_dist > 0 else 0.0
    _n = st["n"] if (st and st.get("n")) else 0
    _net = _exp - spread_R
    _net_t = _net * (_n ** 0.5) if _n else 0.0
    risk_pct = 0.0
    if _n >= 15 and _net > 0.05 and _net_t > 2.0:        # مُثبت صافياً (لا إجمالي فقط)
        conf = max(0.0, min(1.0, (_net_t - 2.0) / 2.0))  # 2σ→0 .. 4σ→أقصى
        cap_eff = _cap if _n >= CONF_FULL_N else min(_cap, CONF_BASE_RISK + (_cap - CONF_BASE_RISK) * 0.4)
        risk_pct = CONF_BASE_RISK + conf * (cap_eff - CONF_BASE_RISK)
    lot = info.volume_min
    if risk_pct > 0 and tv > 0 and ts > 0:
        capm = acct.equity * risk_pct / 100.0
        lot = min(LOT_HARD, capm / ((sl_dist / ts) * tv))
        step = info.volume_step or 0.01
        lot = max(info.volume_min, int(lot / step) * step)
    # 🧲 قناعة العقل العميق: التعلّم المُثبت (Bonferroni) يكبّر اللوت على الضوء الأخضر، ويمنع الدخول
    # على شرطٍ دالٍّ سالب (فيتو تعلّمي). محايد الآن (لا حافّة مُثبتة بعد) ⇒ ×1.0 = بلا أثر حتى تُثبت.
    _cvm, _cvt, _cvok = dc.conviction(sym, "BUY" if d > 0 else "SELL")
    if not _cvok:
        print(f"[WARROOM] skip {sym}: فيتو تعلّمي عميق ({_cvt} ×{_cvm})", flush=True)
        return None
    if _cvm != 1.0:
        _stp = info.volume_step or 0.01
        lot = max(info.volume_min, min(LOT_HARD, round(lot * _cvm / _stp) * _stp))
    try:                                            # 🎛️ حوكمة المايسترو: يخنق هذه الفرقة النزّافة (fail-safe 1.0)
        import json as _j
        _gm = float(_j.load(open(r"C:\Users\Radhi\MT5\data\r_native\engine_governance.json", encoding="utf-8"))
                    .get("mults", {}).get(str(EXEC_MAGIC), 1.0))
        _gm = max(0.1, min(1.5, _gm))
        if _gm != 1.0:
            _stp = info.volume_step or 0.01
            lot = max(info.volume_min, round(lot * _gm / _stp) * _stp)
    except Exception:
        pass
    # 🚫 حارس التحوّط-البيني: لا تفتح عكس محرّكٍ آخر منّا على نفس الرمز (سبريد مزدوج بلا حافّة).
    _hedge, _hr = pg.would_hedge(mt5, sym, mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL, EXEC_MAGIC)
    if _hedge:
        print(f"[WARROOM] skip {sym}: {_hr}", flush=True)
        return None
    # 🌐 سقف التعرّض لكل عملة: امنع تكدّس مراكز تشترك في عملةٍ واحدة (رهان مترابط متخفٍّ كتنويع)
    _cur = set(_re.findall(r"[A-Z]{3}", sym.upper()[:6]))
    _same = sum(1 for p in (mt5.positions_get() or []) if p.magic == EXEC_MAGIC
                and set(_re.findall(r"[A-Z]{3}", p.symbol.upper()[:6])) & _cur)
    if _same >= MAX_PER_CCY:
        print(f"[WARROOM] skip {sym}: سقف تعرّض العملة ({_same}≥{MAX_PER_CCY} مراكز تشترك بعملة)", flush=True)
        return None
    # 🧪 FORWARD-TEST MODE على الديمو (طلب المستخدم: جرّب كل شيء حيّاً، الواقع يحكم). ننفّذ حتى الإشارات
    # غير-المُثبتة بأصغر لوت؛ المُثبت صافياً فقط يكبّر الحجم (risk_pct>0 أعلاه). master_floor يحرس من الكارثة.
    try:
        import lot_guard                                   # 🛑 السقف الصلب المُثبت OOS (الحجم = الرافعة الوحيدة)
        lot, _ = lot_guard.cap(mt5, sym, lot, acct.equity)
    except Exception:
        pass
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL, "price": entry,
                          "sl": sl, "tp": tp, "deviation": 50, "magic": EXEC_MAGIC,
                          "comment": f"army-{s['conf']:.0%}", "type_filling": mt5.ORDER_FILLING_IOC})
    if getattr(res, "retcode", None) == mt5.TRADE_RETCODE_DONE:
        last_exec[sym] = time.time()
        # ✅ تحقّق أن الصفقة حملت الوقف فعلاً: الوسيط قد يملأ الصفقة ويرفض الـSL (داخل stops_level أو بعد
        # انزلاق IOC) فيرجع DONE → مركز عارٍ يبطل سقف 12% ويركض لنداء الهامش. نضع الوقف، وإن تعذّر نُغلق.
        try:
            mine_now = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == EXEC_MAGIC]
            newest = max(mine_now, key=lambda p: p.time) if mine_now else None
            if newest is not None and (not newest.sl or newest.sl == 0.0):
                fix = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                                      "position": newest.ticket, "sl": sl, "tp": tp})
                if getattr(fix, "retcode", None) != mt5.TRADE_RETCODE_DONE:
                    tkx = mt5.symbol_info_tick(sym)   # تعذّر الوقف → أغلق العاري فوراً
                    if tkx:
                        cl = mt5.ORDER_TYPE_SELL if newest.type == 0 else mt5.ORDER_TYPE_BUY
                        px = tkx.bid if newest.type == 0 else tkx.ask
                        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": newest.volume,
                                        "type": cl, "position": newest.ticket, "price": px, "deviation": 100,
                                        "magic": EXEC_MAGIC, "comment": "noSL-close", "type_filling": mt5.ORDER_FILLING_IOC})
                        print(f"[WARROOM] {sym} filled WITHOUT SL → closed naked position (risk voided)", flush=True)
        except Exception as _e:
            print(f"[WARROOM] SL-verify error {sym}: {_e}", flush=True)
        return f"{s['sig']} {lot}"
    return None


def _arrow(t): return "[green]▲[/green]" if t > 0 else ("[red]▼[/red]" if t < 0 else "[dim]─[/dim]")


def build_table(data, score, posmap, tick, halt=False, halt_reason=""):
    t = Table(expand=True, header_style="bold cyan", border_style="grey37")
    for col, j in [("الفرقة", "left"), ("السعر", "right"), ("M1", "center"), ("M5", "center"), ("M15", "center"),
                   ("H1", "center"), ("الإشارة", "center"), ("ثقة", "right"), ("المحرّك (مكوّنات)", "center"),
                   ("سجلّ الفرقة", "center"), ("تنفيذ حيّ", "right")]:
        t.add_column(col, justify=j, no_wrap=True)
    for sym, s in data.items():
        if s is None:
            t.add_row(sym, "[dim]…[/dim]", "", "", "", "", "[dim]جمع[/dim]", "", "", "", ""); continue
        try:                                  # خلية واحدة سيئة لا تقتل الجدول كلّه (درس الحارس)
            rd = s.get("reads", {}) or {}
            cells = [_arrow(rd[k]["trend"]) if (isinstance(rd.get(k), dict) and "trend" in rd[k]) else "·"
                     for k in ("M1", "M5", "M15", "H1")]
            sigc = {"BUY": "[bold green]BUY[/bold green]", "SELL": "[bold red]SELL[/bold red]",
                    "WAIT": "[dim]WAIT[/dim]"}.get(s.get("sig"), "[dim]WAIT[/dim]")
            regime = s.get("regime") or "?"   # قد يعود None لا "?" → كان يسبّب None[:4]
            drv = f"[cyan]{s.get('drivers','—')}[/cyan]" + (f" [dim]{regime[:4]}[/dim]" if regime != "?" else "")
            st = score["stats"].get(sym)
            if st and st["n"] >= 3:
                exp = st["sumR"] / st["n"]; col = "green" if exp > 0 else "red"
                track = f"[{col}]{st['wins']/st['n']*100:.0f}% {exp:+.2f}R n{st['n']}[/{col}]"
            else:
                track = f"[dim]يجمع {st['n'] if st else 0}[/dim]"
            pos = posmap.get(sym)
            posc = (f"[green]+{pos:.0f}[/green]" if pos and pos > 0 else (f"[red]{pos:.0f}[/red]" if pos else "[dim]—[/dim]"))
            px = s.get("px") or 0
            dig = 2 if px > 50 else 5
            t.add_row(sym, f"{px:.{dig}f}", *cells, sigc, f"{s.get('conf', 0):.0%}", drv, track, posc)
        except Exception as e:
            t.add_row(sym, "[dim]⚠[/dim]", "", "", "", "", f"[dim]{type(e).__name__}[/dim]", "", "", "", "")
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[tick % 10]
    npend = len(score["pending"]); npos = len([1 for v in posmap.values() if v is not None])
    hb = f"[bold red]🛑 إيقاف الفتح ({halt_reason})[/bold red]" if halt else "[green]✓ نشط[/green]"
    foot = Text.from_markup(f"[dim]{spin} تنفيذ DEMO عدواني-ناجٍ: ثقة≥{MIN_CONF:.0%} · {MIN_CONS}/3 فريم · "
                            f"تكديس≤{MAX_PER_SYMBOL}/عملة (على الرابح) · ≤{MAX_POS} مركز · لوت≤{LOT_HARD} · سقف2% · "
                            f"قاطع: هامش<{MIN_MARGIN:.0f}% أو سحب>{MAX_DD_PCT:.0f}%[/dim]  {hb}  "
                            f"[dim]معلّق:{npend} مفتوح:{npos} · {datetime.now():%H:%M:%S}[/dim]")
    return Panel(Group(t, Align.center(foot)),
                 title="[bold yellow]🪖 غرفة حرب FRIDAY — تقرأ · تُحاسَب · تنفّذ (DEMO)[/bold yellow]", border_style="yellow")


def main():
    # ثلاثة أوضاع: افتراضي = نافذة تنفّذ+تعرض (مستقل) · --exec = منفّذ بلا واجهة 24/7 (تحت الحارس) ·
    # --view = نافذة عرض فقط (لا تنفّذ — تتفرّج على ما يفعله المنفّذ؛ إغلاقها لا يوقف التداول).
    view_only = "--view" in sys.argv
    headless = "--exec" in sys.argv
    execute = not view_only
    # 🔒 قفل وحيد للمنفّذ: عدّة حُرّاس (watchdog/autopilot/keepalive) قد تُطلق --exec معاً →
    # نسخ منفّذة مكرّرة تتسابق على نفس الإشارات (تتجاوز سقف العملة والتهدئة) = إفراط تداول خطر على حساب صغير.
    # ربط منفذ محلي ثابت يضمن نسخة --exec واحدة فقط (يتحرّر تلقائياً عند موت العملية).
    if headless:
        import socket
        _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _lock.bind(("127.0.0.1", 8617)); _lock.listen(1)
            main._singleton_lock = _lock   # إبقاء المرجع حيّاً طوال عمر العملية
        except OSError:
            print("[WARROOM-EXEC] منفّذ --exec آخر يعمل بالفعل — خروج (قفل وحيد)", flush=True); return
    if not (mt5.initialize() or mt5.initialize()):
        (print if headless else console.print)("فشل اتصال MT5"); return
    syms, total, excluded = _select_symbols(mt5)
    if headless:
        print(f"[WARROOM-EXEC] {len(syms)} فرقة — تنفيذ بلا واجهة 24/7 (تحت الحارس)", flush=True)
    else:
        head = "بثّ حيّ + تنفيذ" if execute else "عرض فقط (المنفّذ يعمل بالخلفية تحت الحارس)"
        console.print(Panel(Align.center(Text(f"🪖 تجييش {len(syms)} فرقة (من {total} عملة · استُبعد {excluded} واسع السبريد)\n"
                                              + " · ".join(syms), style="bold yellow")), border_style="yellow"))
        for s in syms:
            console.print(f"  [green]✚[/green] فرقة [bold]{s}[/bold]", highlight=False); time.sleep(0.03)
        console.print(f"[bold green]الميدان جاهز. {head}...[/bold green]\n"); time.sleep(0.5)
    data = {s: None for s in syms}; score = _load_score(); posmap = {}; last_exec = {}; tick = 0; hb_i = 0

    def one_cycle(live):
        nonlocal tick, hb_i, posmap, score
        if not execute:                       # عرض فقط: أعِد تحميل السبورة الحيّة التي يكتبها المنفّذ
            score = _load_score()
        acct = mt5.account_info()
        allpos = mt5.positions_get() or []
        total_pos = sum(1 for p in allpos if p.magic == EXEC_MAGIC)
        posmap = {p.symbol: p.profit for p in allpos if p.magic == EXEC_MAGIC}
        # 🛑 قاطع أمان الحساب: هامش منخفض أو سحب عائم كبير → أوقف الفتح
        ml = (acct.equity / acct.margin * 100) if acct and acct.margin > 0 else 9999
        dd = ((acct.balance - acct.equity) / acct.balance * 100) if acct and acct.balance > 0 else 0
        _killed = KILL_F.exists()   # 🛑 مفتاح الإيقاف الطارئ (يحترمه التنفيذ الحيّ الآن)
        halt = _killed or ml < MIN_MARGIN or dd > MAX_DD_PCT
        halt_reason = ("إيقاف طارئ (kill_switch)" if _killed else
                       (f"هامش {ml:.0f}%<{MIN_MARGIN:.0f}" if ml < MIN_MARGIN else
                        (f"سحب {dd:.0f}%>{MAX_DD_PCT:.0f}" if dd > MAX_DD_PCT else "")))
        # 🛑 سقف خسارة يومي للبوت: صافي صفقات magic اليوم المحقّق < −DAILY_HALT_PCT% من الحقوق → أوقف الفتح
        if execute and acct and acct.equity > 0:
            try:
                _ds = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                _tdy = mt5.history_deals_get(int(_ds), int(time.time())) or []
                # 🩺 2026-07-15: عملية رصيد اليوم (type 2/3) = خطُّ أساس جديد — التصفير ليس خسارة تداول
                _rst = max((int(x.time) for x in _tdy if getattr(x, "type", -1) in (2, 3)), default=int(_ds))
                _daynet = sum(x.profit + x.commission + x.swap
                              for x in _tdy
                              if x.magic == EXEC_MAGIC and x.entry == 1 and int(x.time) >= _rst)
                if _daynet < -DAILY_HALT_PCT / 100.0 * acct.equity:
                    halt = True
                    halt_reason = halt_reason or f"خسارة يومية ${_daynet:.0f} (>{DAILY_HALT_PCT:.0f}%)"
            except Exception:
                pass
        now = time.time()
        heavy = {syms[(hb_i + j) % len(syms)] for j in range(min(HEAVY_PER_CYCLE, len(syms)))}
        hb_i = (hb_i + HEAVY_PER_CYCLE) % len(syms)
        for i, s in enumerate(syms):
            try:
                data[s] = squad(s, allow_heavy=(s in heavy))
                if data[s] and execute:
                    record_and_judge(s, data[s], score, now)
                    ex = maybe_execute(s, data[s], mt5.symbol_info(s), acct, total_pos, last_exec, halt, score)
                    if ex: total_pos += 1
            except Exception:
                data[s] = None
            tick += 1
            if execute and i % 16 == 15:            # حفظ دوري للسبورة وسط الدورة (الدورة قد تطول على 48 رمزاً
                _save_score(score)                   # → كان الحفظ نهاية-الدورة فقط لا يُنفَّذ = تجمّد التعلّم 9س)
            if live is not None and i % 16 == 0:    # رسم تقدّمي كل 16 فرقة (لا كل فرقة → لا تجمّد)
                live.update(build_table(data, score, posmap, tick, halt, halt_reason))
        if live is not None:
            live.update(build_table(data, score, posmap, tick, halt, halt_reason))
        if execute:
            _save_score(score)

    try:
        if headless:                              # 24/7 بلا TUI
            while True:
                try:
                    one_cycle(None)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"[WARROOM-EXEC] دورة تخطّت: {type(e).__name__}: {e}", flush=True)
                time.sleep(REFRESH_S)
        else:
            with Live(build_table(data, score, posmap, tick), console=console, refresh_per_second=2, screen=False) as live:
                while True:
                    try:
                        one_cycle(live)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        console.print(f"[dim red]دورة تخطّت خطأً: {type(e).__name__}[/dim red]")
                    time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        pass
    finally:
        if execute:
            _save_score(score)
        mt5.shutdown()
        if not headless:
            tail = "" if execute else " (المنفّذ مستمر بالخلفية تحت الحارس)"
            console.print(f"\n[yellow]أُغلقت النافذة{tail}.[/yellow]")


if __name__ == "__main__":
    main()
