# -*- coding: utf-8 -*-
"""
quant_desk.py — مكتب الحسابات الكمّي (قراءة فقط — لا أوامر تداول إطلاقاً)
==========================================================================
حلقة دائمة (~5 ثوانٍ) تحسب كلّ شيء حيّاً بأوزان صريحة قابلة للضبط:
  1) المؤشّر المركّب للذهب (-100..+100) من 6 عوامل موزونة، كلّ عامل ومساهمته مُصدَّران
  2) ترتيب أقوى 5 رموز من نبض السوق
  3) عدّادات النظام: risk on/off، ضغط الدولار، حالة تقلّب الذهب، الجلسة
  4) محاسبة أرباح/خسائر اليوم لكلّ مجموعة magic + تقدير السبريد المدفوع
  5) تغذية jsonl عند انقلاب المركّب (±20) أو انقلاب النظام (dedup 15 دقيقة)
⚠️ الصدق (قانون المشروع): هذه الأوزان تجميعٌ شفّاف لقراءة الإنسان فقط —
   قياسات المشروع كلّها: لا حافة تنبّؤيّة (~50% خارج العيّنة). لا يُوصَل بمسارات الأوامر أبداً.
"""

import os, sys, io

# ── أوّل شيء: تحويل stdout/stderr لملفّ سجلّ (pythonw بلا كونسول) قبل الاستيرادات الثقيلة ──
_BASE = os.path.dirname(os.path.abspath(__file__))
_LOG_PATH = os.path.join(_BASE, "data", "r_native", "quant_desk.out.log")
os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
try:
    _log_f = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
except Exception:
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

import json, time
from datetime import datetime, timezone, timedelta

import numpy as np
import MetaTrader5 as mt5

# ── قفل النسخة الوحيدة ──
try:
    import engine_lock
    engine_lock.claim("quant_desk")
except SystemExit:
    raise
except Exception as _e:
    print(f"[lock] engine_lock غير متاح ({_e}) — نتابع بدون قفل")

# ── المسارات والثوابت ──
CFG_PATH   = os.path.join(_BASE, "data", "r_native", "quant_desk_config.json")
OUT_JSON   = os.path.join(_BASE, "data", "r_native", "quant_desk.json")
FEED_PATH  = os.path.join(_BASE, "data", "r_native", "quant_desk_feed.jsonl")
PULSE_PATH = os.path.join(_BASE, "data", "r_native", "market_pulse.json")

GOLD = "XAUUSDm"
# مجموعات الـ magic (المستخدم اليدويّ = 0 — لا نلمسه أبداً، محاسبة فقط)
MAGIC_GROUPS = {
    "radhi_mimic": [20260703],   # ⚔️ المحرّك الوحيد بعد خطة الحسم — استراتيجية المستخدم
    "قوسا_الأخبار": [20260702],
    "يوتيوب":  [20260631],       # مُطفأ 2026-07-02 (خطة الحسم) — يبقى للمحاسبة التاريخية
    "حارس":    [20260701],
    "multi":   [20260608],       # مُطفأ
    "warroom": [20260618],       # مُطفأ
    "يدويّ":   [0],
}
# سلّة تأكيد الذهب: (رمز النبض، +1 نفس الاتّجاه / -1 عكسه)
BASKET = [("XAGUSDm", +1), ("AUDUSDm", +1), ("EURUSDm", +1), ("DXYm", -1), ("USDCHFm", -1)]

HONESTY = ("تجميع موزون شفّاف لقراءة الإنسان فقط — قياس المشروع: لا حافة تنبّؤيّة (~50% خارج العيّنة). "
           "ممنوع وصله بمسارات الأوامر.")

DEDUP_S = 15 * 60   # dedup التغذية 15 دقيقة

# ═══════════════════ الإعدادات ═══════════════════

def load_config():
    """قراءة الإعدادات مع قيم افتراضيّة (setdefault) — الأوزان قابلة للضبط من المستخدم."""
    cfg = {}
    try:
        with open(CFG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    cfg.setdefault("enabled", True)
    cfg.setdefault("poll_s", 5)
    w = cfg.setdefault("weights", {})
    w.setdefault("trend_mtf", 0.25)
    w.setdefault("momentum", 0.20)
    w.setdefault("structure_smc", 0.20)
    w.setdefault("poc_position", 0.15)
    w.setdefault("basket_confirm", 0.10)
    w.setdefault("pattern", 0.10)
    return cfg

def save_config_if_new(cfg):
    """كتابة الإعدادات إن لم يوجد الملف (ليجدها المستخدم ويضبطها)."""
    if not os.path.exists(CFG_PATH):
        try:
            atomic_write(CFG_PATH, cfg)
        except Exception as e:
            print(f"[cfg] تعذّرت كتابة الإعدادات: {e}")

def atomic_write(path, obj):
    """كتابة ذرّية: tmp ثمّ os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)

# ═══════════════════ أدوات المؤشّرات (numpy، مكتفية ذاتيّاً) ═══════════════════

def ema_last(vals, period):
    """آخر قيمة لمتوسّط أسّي."""
    k = 2.0 / (period + 1.0)
    e = float(vals[0])
    for v in vals[1:]:
        e = float(v) * k + e * (1.0 - k)
    return e

def rsi_wilder(closes, period=14):
    """RSI بطريقة Wilder."""
    d = np.diff(np.asarray(closes, dtype=float))
    if len(d) < period + 1:
        return 50.0
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag, al = gains[:period].mean(), losses[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al <= 1e-12:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)

def stoch_1433(high, low, close):
    """Stoch(14,3,3) — يعيد %K المنعّم."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    if n < 20:
        return 50.0
    raw = np.empty(n - 13)
    for i in range(13, n):
        hh, ll = h[i - 13:i + 1].max(), l[i - 13:i + 1].min()
        rng = hh - ll
        raw[i - 13] = 50.0 if rng <= 1e-12 else (c[i] - ll) / rng * 100.0
    k = np.convolve(raw, np.ones(3) / 3.0, mode="valid")
    return float(k[-1]) if len(k) else 50.0

def atr14(high, low, close, period=14):
    """ATR كمتوسّط بسيط لمدى True Range."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    if len(c) < period + 2:
        return 0.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-period:].mean())

def volume_poc(high, low, close, tick_vol, bins=24):
    """POC عبر بروفايل حجم 24 سلّة: حجم كلّ شمعة على سعرها النموذجي."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    v = np.asarray(tick_vol, dtype=float)
    lo, hi = float(l.min()), float(h.max())
    if hi - lo <= 1e-9:
        return float(c[-1])
    typ = (h + l + c) / 3.0
    idx = np.clip(((typ - lo) / (hi - lo) * bins).astype(int), 0, bins - 1)
    prof = np.zeros(bins)
    for i, b in enumerate(idx):
        prof[b] += v[i]
    b = int(prof.argmax())
    return lo + (b + 0.5) * (hi - lo) / bins

def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, float(x)))

# ═══════════════════ سحب الأسعار ═══════════════════

def rates(symbol, tf, count=60):
    """شموع من MT5 — None عند الفشل."""
    try:
        r = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if r is None or len(r) < 10:
            return None
        return r
    except Exception:
        return None

def read_pulse():
    """قراءة market_pulse.json (قد يكتبه محرّك آخر لحظة القراءة — نتسامح)."""
    try:
        with open(PULSE_PATH, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def m5_dir(pulse_sym, lookback=3):
    """اتّجاه آخر ~15 دقيقة من candles_m5 في النبض: sign(الإغلاق الأخير - قبل lookback)."""
    cs = (pulse_sym or {}).get("candles_m5") or []
    if len(cs) < lookback + 1:
        return 0
    try:
        delta = float(cs[-1][4]) - float(cs[-1 - lookback][4])   # [t,o,h,l,c]
    except Exception:
        return 0
    return 1 if delta > 0 else (-1 if delta < 0 else 0)

# ═══════════════════ 1) المركّب الذهبي ═══════════════════

def factor_trend_mtf():
    """أصوات EMA9/21 عبر D1/H4/H1/M15 بأوزان 0.35/0.30/0.20/0.15."""
    votes, total = 0.0, 0.0
    for tf, w in [(mt5.TIMEFRAME_D1, 0.35), (mt5.TIMEFRAME_H4, 0.30),
                  (mt5.TIMEFRAME_H1, 0.20), (mt5.TIMEFRAME_M15, 0.15)]:
        r = rates(GOLD, tf, 60)
        if r is None:
            continue
        c = r["close"]
        vote = 1.0 if ema_last(c, 9) > ema_last(c, 21) else -1.0
        votes += w * vote
        total += w
    return clamp(votes / total) if total > 0 else 0.0

def factor_momentum():
    """زخم: Stoch(14,3,3) + RSI(14) على H1 و M15، حول 50."""
    parts = []
    for tf in (mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M15):
        r = rates(GOLD, tf, 60)
        if r is None:
            continue
        k = stoch_1433(r["high"], r["low"], r["close"])
        rs = rsi_wilder(r["close"], 14)
        parts.append(((k - 50.0) / 50.0 + (rs - 50.0) / 50.0) / 2.0)
    return clamp(float(np.mean(parts))) if parts else 0.0

def factor_structure_smc(pulse_gold):
    """بنية SMC من النبض: الترند + اتّجاه آخر BOS/CHoCH طازج."""
    smc = (pulse_gold or {}).get("smc") or {}
    trend = float(smc.get("trend") or 0)
    events = list(smc.get("bos") or []) + list(smc.get("choch") or [])
    last_dir = 0.0
    if events:
        try:
            last_dir = float(max(events, key=lambda e: e.get("idx", 0)).get("dir") or 0)
        except Exception:
            last_dir = 0.0
    return clamp(0.6 * clamp(trend) + 0.4 * clamp(last_dir))

def factor_poc_position():
    """موقع السعر من POC على H1: sign(price-POC) مُدرَّج بـ |المسافة|/ATR (سقف 1)."""
    r = rates(GOLD, mt5.TIMEFRAME_H1, 60)
    if r is None:
        return 0.0, None
    poc = volume_poc(r["high"], r["low"], r["close"], r["tick_volume"], bins=24)
    a = atr14(r["high"], r["low"], r["close"])
    price = float(r["close"][-1])
    if a <= 1e-9:
        return 0.0, poc
    return clamp((price - poc) / a), poc

def factor_basket_confirm(pulse_syms, gold_dir):
    """تأكيد السلّة: فضّة/AUD/EUR بنفس اتّجاه الذهب، DXY/CHF عكسه — متوسّط التوافق."""
    if gold_dir == 0:
        return 0.0
    scores = []
    for sym, rel in BASKET:
        d = m5_dir(pulse_syms.get(sym))
        scores.append(0.0 if d == 0 else float(gold_dir * d * rel))
    return clamp(float(np.mean(scores))) if scores else 0.0

def factor_pattern(pulse_gold):
    """أنماط شموع الذهب M1/M5 من النبض، موزونة بالقوّة (strength 0-3)."""
    val = 0.0
    for key, w in (("pattern_m1", 0.5), ("pattern_m5", 0.5)):
        p = (pulse_gold or {}).get(key) or {}
        val += w * clamp(float(p.get("dir") or 0)) * min(1.0, float(p.get("strength") or 0) / 3.0)
    return clamp(val)

def arabic_verdict(composite, factors):
    """سطر حكم عربيّ يذكر أقوى المساهمين وأضعفهم."""
    mag = abs(composite)
    side = "شرائيّ" if composite > 0 else "بيعيّ"
    if mag < 10:
        head = f"محايد {composite:+.0f}/100"
    elif mag < 30:
        head = f"انحياز {side} خفيف {composite:+.0f}/100"
    elif mag < 55:
        head = f"انحياز {side} {composite:+.0f}/100"
    else:
        head = f"انحياز {side} قويّ {composite:+.0f}/100"
    names = {"trend_mtf": "الترند", "momentum": "الزخم", "structure_smc": "البنية",
             "poc_position": "موقع POC", "basket_confirm": "السلّة", "pattern": "الشموع"}
    ranked = sorted(factors.items(), key=lambda kv: abs(kv[1]["contrib"]), reverse=True)
    strong = [names[k] for k, v in ranked[:2] if abs(v["contrib"]) >= 3.0]
    flat = [names[k] for k, v in factors.items() if abs(v["value"]) < 0.15]
    tail = ""
    if strong:
        tail += " — " + " و".join(strong) + (" معاً" if len(strong) > 1 else " يقود")
    if flat:
        tail += ("، " if tail else " — ") + " و".join(flat[:2]) + " محايدة"
    return head + tail

def compute_gold_composite(cfg, pulse_syms):
    """يجمع العوامل الستّة بالأوزان الصريحة ويعيد dict كامل."""
    w = cfg["weights"]
    pulse_gold = pulse_syms.get(GOLD) or {}
    poc_val, poc_price = factor_poc_position()
    vals = {
        "trend_mtf":      factor_trend_mtf(),
        "momentum":       factor_momentum(),
        "structure_smc":  factor_structure_smc(pulse_gold),
        "poc_position":   poc_val,
        "basket_confirm": factor_basket_confirm(pulse_syms, m5_dir(pulse_gold)),
        "pattern":        factor_pattern(pulse_gold),
    }
    factors = {}
    composite = 0.0
    for name, v in vals.items():
        wi = float(w.get(name, 0.0))
        contrib = 100.0 * wi * v
        composite += contrib
        factors[name] = {"value": round(v, 3), "weight": wi, "contrib": round(contrib, 1)}
    composite = round(max(-100.0, min(100.0, composite)), 1)
    return {"factors": factors, "composite": composite,
            "verdict": arabic_verdict(composite, factors),
            "poc_h1": round(poc_price, 3) if poc_price else None}

# ═══════════════════ 2) ترتيب الرموز ═══════════════════

def rank_symbols(pulse_syms, top=5):
    """أقوى الرموز حسب |score-50| مع قراءاتها."""
    rows = []
    for sym, d in pulse_syms.items():
        try:
            sc = float(d.get("score", 50))
        except Exception:
            continue
        rows.append({"symbol": sym, "score": round(sc, 1), "bias": round(sc - 50.0, 1),
                     "read": d.get("read", "")})
    rows.sort(key=lambda r: abs(r["bias"]), reverse=True)
    return rows[:top]


def all_symbols_composite(pulse_syms):
    """🌍 مركّبٌ موزون لكلّ رمزٍ (لا الذهب فقط) من حقول النبض — بلا أيّ سحبٍ إضافيّ من MT5.
       الأوزان: نبض 40% (M1-ثقيل) · ترند SMC 25% · شموع 20% · بنية BOS 15% ⇒ -100..+100."""
    out = {}
    for sym, d in (pulse_syms or {}).items():
        try:
            sc = (float(d.get("score", 50)) - 50.0) / 50.0
            smc = d.get("smc") or {}
            tr = float(smc.get("trend") or 0)
            p1 = float(((d.get("pattern_m1") or {}).get("dir")) or 0)
            p5 = float(((d.get("pattern_m5") or {}).get("dir")) or 0)
            st = d.get("structure") or {}
            bos = float(st.get("bos") or 0) if isinstance(st, dict) else 0.0
            comp = 100.0 * (0.40 * sc + 0.25 * tr + 0.20 * (0.65 * p1 + 0.35 * p5) + 0.15 * bos)
            out[sym] = {"composite": round(max(-100.0, min(100.0, comp)), 1),
                        "read": str(d.get("read") or "")[:90]}
        except Exception:
            continue
    return out

# ═══════════ 📚 نسبة تقدّم معرفتنا لكل عملة (أمر المستخدم 2026-07-02) ═══════════

_KNOW_CACHE = {"ts": 0.0, "by_sym": {}}
_EXTERNAL_MAGICS = {0, 2447, 20250418, 20250421, 20250422, 20250618}


def _deal_stats_by_symbol():
    """إحصاء إغلاقات محرّكاتنا لكل رمز (90 يوماً): العدد + t-stat — مخبّأ 10 دقائق (استعلام ثقيل)."""
    now = time.time()
    if now - _KNOW_CACHE["ts"] < 600:
        return _KNOW_CACHE["by_sym"]
    agg = {}
    try:
        for d in (mt5.history_deals_get(datetime.now() - timedelta(days=90), datetime.now()) or []):
            if getattr(d, "magic", 0) in _EXTERNAL_MAGICS:
                continue
            if getattr(d, "entry", None) not in (1, 2, 3):          # إغلاقات فقط
                continue
            s = getattr(d, "symbol", "") or ""
            if s:
                agg.setdefault(s, []).append(float(d.profit))
    except Exception:
        pass
    out = {}
    for s, ps in agg.items():
        n = len(ps)
        m = sum(ps) / n
        var = sum((x - m) ** 2 for x in ps) / max(1, n - 1)
        t = (m / ((var ** 0.5) / (n ** 0.5))) if var > 1e-12 and n > 2 else 0.0
        out[s] = {"n": n, "t": t}
    _KNOW_CACHE.update({"ts": now, "by_sym": out})
    return out


def market_knowledge(pulse_syms):
    """📚 معرفة السوق % لكل عملة = عيون حيّة 25 + خبرة صفقات 25 (n=100 يشبعها) + وضوح بنية 20
    + حافّة مُثبتة 30 (t≥2σ يشبعها). الصدق أولاً: الحافّة هي الجزء الأثقل وهي شبه صفر غالباً — عمداً،
    كي لا تُوهم «معرفةٌ» بلا قدرة ربح مقاسة."""
    stats = _deal_stats_by_symbol()
    out = {}
    for sym, d in (pulse_syms or {}).items():
        try:
            smc = d.get("smc") or {}
            eyes = (15 if d.get("candles_m5") else 0) + (10 if smc else 0)
            st_ = stats.get(sym, {"n": 0, "t": 0.0})
            exp = 25.0 * min(1.0, (st_["n"] / 100.0) ** 0.5)
            clarity = ((8 if smc.get("trend") else 0) + (6 if smc.get("bos") else 0)
                       + (6 if smc.get("poc") else 0))
            t = float(st_["t"])
            edge = 30.0 * min(1.0, max(0.0, t) / 2.0)   # ✅ الصدق: الحافّة الموجبة فقط تُحتسب تقدّماً
            verdict = ("🏆 حافّة ربح مُثبتة" if t >= 2 else
                       ("⚠️ معرفة عكسية مُثبتة: البوتات تخسر هنا بمعنوية — قيمتها: لا تُتداول آلياً"
                        if t <= -2 else "لا حافّة مُثبتة بعد"))
            out[sym] = {"pct": round(min(100.0, eyes + exp + clarity + edge), 1),
                        "n_trades": st_["n"], "t_stat": round(t, 2), "verdict": verdict,
                        "parts": {"عيون": eyes, "خبرة": round(exp, 1),
                                  "بنية": clarity, "حافة": round(edge, 1)}}
        except Exception:
            continue
    return out

# ═══════════════════ 3) عدّادات النظام ═══════════════════

def compute_regime(pulse_syms):
    """risk on/off + ضغط الدولار + حالة تقلّب الذهب + الجلسة."""
    us30 = m5_dir(pulse_syms.get("US30m"))
    btc = m5_dir(pulse_syms.get("BTCUSDm"))
    dxy = m5_dir(pulse_syms.get("DXYm"))
    risk = clamp((us30 + btc - dxy) / 3.0)

    # ضغط الدولار: ميل DXY على M15 (آخر 8 شموع) مُدرَّج بالمدى
    dollar = 0.0
    r = rates("DXYm", mt5.TIMEFRAME_M15, 30)
    if r is not None:
        c = r["close"]
        a = atr14(r["high"], r["low"], r["close"])
        if a > 1e-9 and len(c) >= 9:
            dollar = clamp((float(c[-1]) - float(c[-9])) / (a * 3.0))

    # حالة تقلّب الذهب: ATR14-H1 الآن مقابل percentile آخر 30 يوماً (~720 شمعة H1)
    vol_state, vol_pct = "غير معروف", None
    rh = rates(GOLD, mt5.TIMEFRAME_H1, 760)
    if rh is not None and len(rh) > 60:
        h, l, c = rh["high"], rh["low"], rh["close"]
        tr = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        atr_series = np.convolve(tr, np.ones(14) / 14.0, mode="valid")
        now_atr = float(atr_series[-1])
        vol_pct = round(float((atr_series < now_atr).mean()) * 100.0, 1)
        vol_state = "هادئ" if vol_pct < 30 else ("طبيعيّ" if vol_pct <= 70 else "عاصف")

    hour = datetime.now(timezone.utc).hour
    session = "آسيا" if (hour < 7 or hour >= 21) else ("لندن" if hour < 13 else "نيويورك")
    return {"risk_onoff": round(risk, 2), "dollar_pressure": round(dollar, 2),
            "gold_vol_state": vol_state, "gold_vol_pctile": vol_pct, "session": session}

# ═══════════════════ 4) محاسبة الأرباح/الخسائر ═══════════════════

def compute_pnl():
    """اليوم من 00:00 محلّياً: صافي محقّق/عدد/نسبة ربح/عائم لكلّ مجموعة + تقدير السبريد."""
    now = datetime.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    magic2grp = {m: g for g, ms in MAGIC_GROUPS.items() for m in ms}
    groups = {g: {"realized": 0.0, "trades": 0, "wins": 0, "floating": 0.0}
              for g in MAGIC_GROUPS}
    spread_paid = 0.0
    spread_cache = {}

    deals = mt5.history_deals_get(day0, now) or []
    for d in deals:
        g = magic2grp.get(getattr(d, "magic", -1))
        if g is None:
            continue                      # EAs خارجيّة وغيرها — تجاهل
        entry = getattr(d, "entry", -1)
        net = (getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0)
               + getattr(d, "swap", 0.0) + getattr(d, "fee", 0.0))
        if entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT):
            groups[g]["realized"] += net
            groups[g]["trades"] += 1
            if getattr(d, "profit", 0.0) > 0:
                groups[g]["wins"] += 1
        if entry == mt5.DEAL_ENTRY_IN:
            sym = getattr(d, "symbol", "")
            if sym not in spread_cache:
                info = mt5.symbol_info(sym)
                spread_cache[sym] = (float(info.ask - info.bid)
                                     if info and info.ask and info.bid else 0.0)
            # تقدير: الحجم × السبريد الحاليّ × 100 (تقريبيّ — سبريد الآن لا لحظة الدخول)
            spread_paid += getattr(d, "volume", 0.0) * spread_cache[sym] * 100.0

    for p in (mt5.positions_get() or []):
        g = magic2grp.get(getattr(p, "magic", -1))
        if g is not None:
            groups[g]["floating"] += getattr(p, "profit", 0.0)

    out = {}
    for g, s in groups.items():
        out[g] = {"realized": round(s["realized"], 2), "trades": s["trades"],
                  "win_rate": round(100.0 * s["wins"] / s["trades"], 1) if s["trades"] else None,
                  "floating": round(s["floating"], 2)}
    acc = mt5.account_info()
    account = ({"balance": round(acc.balance, 2), "equity": round(acc.equity, 2),
                "margin_free": round(acc.margin_free, 2)} if acc else {})
    return {"groups": out,
            "spread_paid_today": {"value": round(spread_paid, 2), "note": "تقديريّ (سبريد اللحظة × حجم دخولات اليوم × 100)"},
            "account": account}

# ═══════════════════ 5) التغذية ═══════════════════

_last_feed = {}          # مفتاح الحدث → آخر وقت إرسال

def feed_append(kind, msg, extra=None):
    """إلحاق حدث للتغذية مع dedup 15 دقيقة على نوع الحدث."""
    now = time.time()
    if now - _last_feed.get(kind, 0.0) < DEDUP_S:
        return
    _last_feed[kind] = now
    row = {"ts": int(now), "iso": datetime.now().isoformat(timespec="seconds"),
           "kind": kind, "msg": msg, "honesty": HONESTY}
    if extra:
        row.update(extra)
    try:
        with open(FEED_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[feed] فشل الإلحاق: {e}")

def comp_zone(c):
    """منطقة المركّب: -1 دون -20 / 0 بين / +1 فوق +20."""
    return 1 if c >= 20 else (-1 if c <= -20 else 0)

def check_flips(state, gold, regime):
    """انقلابات المركّب (±20) وانقلابات النظام → تغذية."""
    z = comp_zone(gold["composite"])
    if state.get("zone") is not None and z != state["zone"]:
        name = {1: "تحوّل شرائيّ (المركّب عبر +20)", -1: "تحوّل بيعيّ (المركّب عبر -20)",
                0: "عودة للحياد (المركّب داخل ±20)"}[z]
        feed_append(f"composite_{z}", f"{name} — {gold['verdict']}",
                    {"composite": gold["composite"]})
    state["zone"] = z

    r = regime["risk_onoff"]
    rz = 1 if r >= 0.34 else (-1 if r <= -0.34 else 0)
    if state.get("risk") is not None and rz != state["risk"]:
        name = {1: "risk-ON (مؤشّرات+BTC صعوداً والدولار هبوطاً)",
                -1: "risk-OFF", 0: "شهيّة مخاطرة محايدة"}[rz]
        feed_append(f"risk_{rz}", f"انقلاب النظام: {name}", {"risk_onoff": r})
    state["risk"] = rz

    for key, label in (("gold_vol_state", "تقلّب الذهب"), ("session", "الجلسة")):
        v = regime[key]
        if state.get(key) is not None and v != state[key]:
            feed_append(f"{key}_{v}", f"انقلاب {label}: {state[key]} → {v}")
        state[key] = v

# ═══════════════════ الحلقة الرئيسة ═══════════════════

def mt5_connect():
    """اتّصال MT5 واحد للعملية — 6 محاولات كلّ 10 ثوانٍ."""
    for attempt in range(6):
        if mt5.initialize():
            print(f"[mt5] متّصل — {mt5.account_info().login if mt5.account_info() else '?'}")
            return True
        print(f"[mt5] فشل initialize (محاولة {attempt + 1}/6): {mt5.last_error()}")
        time.sleep(10)
    return False

def cycle_once(cfg=None, state=None):
    """دورة واحدة كاملة: حساب المركّب + الترتيب + النظام + المحاسبة → كتابة ذرّيّة
    لـ quant_desk.json (+ فحص الانقلابات إن مُرِّرت حالة). تُستخدم من الحلقة ومن الاختبار."""
    cfg = cfg or load_config()
    pulse = read_pulse()
    pulse_syms = pulse.get("symbols") or {}
    pulse_age = round(time.time() - float(pulse.get("ts") or 0), 1) if pulse.get("ts") else None
    gold = compute_gold_composite(cfg, pulse_syms)
    out = {
        "ts": int(time.time()),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "honesty": HONESTY,
        "pulse_age_s": pulse_age,
        "gold": gold,
        "symbols": all_symbols_composite(pulse_syms),   # 🌍 كل العملات لا الذهب فقط
        "knowledge": market_knowledge(pulse_syms),      # 📚 نسبة معرفتنا لكل عملة (بأمر المستخدم)
        "rank": rank_symbols(pulse_syms),
        "regime": compute_regime(pulse_syms),
        "pnl": compute_pnl(),
        "weights": cfg["weights"],
    }
    atomic_write(OUT_JSON, out)
    if state is not None:
        check_flips(state, gold, out["regime"])
    return out

def main():
    print(f"[quant_desk] بدء — {datetime.now().isoformat(timespec='seconds')}")
    cfg = load_config()
    save_config_if_new(cfg)
    if not mt5_connect():
        print("[quant_desk] لا اتّصال MT5 — خروج")
        return
    state = {"zone": None, "risk": None, "gold_vol_state": None, "session": None}
    errors = 0
    while True:
        try:
            cfg = load_config()
            if not cfg.get("enabled", True):
                time.sleep(max(5, int(cfg.get("poll_s", 5))))
                continue
            cycle_once(cfg, state)
            errors = 0
            # 📱 موجز التقدّم اليوميّ 21:00 (خطة الحسم): رقم صادق واحد للجوّال كل ليلة
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                _dg = os.path.join(_BASE, "data", "r_native", "quant_digest_day.txt")
                if state.get("digest_day") is None:
                    try:
                        state["digest_day"] = open(_dg, encoding="utf-8").read().strip()
                    except Exception:
                        state["digest_day"] = ""
                if datetime.now().hour == 21 and state.get("digest_day") != today:
                    state["digest_day"] = today
                    try:
                        open(_dg, "w", encoding="utf-8").write(today)   # صامد عبر إعادة التشغيل
                    except Exception:
                        pass
                    q = json.load(open(OUT_JSON, encoding="utf-8"))
                    gsum = q.get("pnl", {}).get("groups", {}) or {}
                    bots = sum(float(v.get("realized", 0)) for k, v in gsum.items()
                               if "يدوي" not in str(k) and "manual" not in str(k).lower())
                    kn = q.get("knowledge", {}) or {}
                    avg_k = round(sum(v["pct"] for v in kn.values()) / max(1, len(kn)), 1)
                    mim = gsum.get("radhi_mimic") or {}
                    msg = (f"📊 موجز الليلة: بوتات اليوم ${bots:+.2f} · محاكيك: {mim.get('trades', '?')}"
                           f" صفقة ${float(mim.get('realized', 0)):+.2f} · معرفة السوق {avg_k}%")
                    with open(os.path.join(_BASE, "data", "r_native", "news_alarm_feed.jsonl"),
                              "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": time.time(), "iso": datetime.now().isoformat(timespec='seconds'),
                                            "kind": "DIGEST", "title": msg, "impact": "Info",
                                            "currency": "ALL"}, ensure_ascii=False) + "\n")
            except Exception:
                pass
        except Exception as e:
            errors += 1
            print(f"[loop] خطأ ({errors}): {type(e).__name__}: {e}")
            if errors >= 30:
                print("[loop] أخطاء متراكمة — إعادة اتّصال MT5")
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                if not mt5_connect():
                    print("[quant_desk] فقدنا MT5 نهائيّاً — خروج")
                    return
                errors = 0
        time.sleep(max(2, int(cfg.get("poll_s", 5))))

if __name__ == "__main__":
    main()
