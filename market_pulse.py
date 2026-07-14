# -*- coding: utf-8 -*-
"""
market_pulse.py — نبض السوق (قراءة فائقة الحساسية لكلّ العملات)
================================================================
محرّك دائم للقراءة فقط (لا أوامر تداول إطلاقاً):
يقرأ M1 (120 شمعة) و M5 (100 شمعة) لكلّ رمز كلّ ~4 ثوانٍ ويحسب:
  1) أنماط الشموع على آخر شمعة مُغلقة (M1 و M5 منفصلين)
  2) البنية: قمم/قيعان فراكتالية 3-شموع على M5 + كسر بنية BOS
  3) الزخم: Stoch(9,3,3) و RSI(9) على M1 + EMA9/EMA21 على M1 و M5
  4) الحجم: z-score لآخر شمعة مقابل 30 السابقة (سبايك > 2)
  5) التقلّب/التكلفة: ATR14 على M5 + السبريد ونسبته من ATR
  6) درجة ضغط 0-100 (50 محايد، >50 صعوديّ) — حسّاسة (وزن M1 أثقل)
  7) سطر قراءة عربيّ موجز لكلّ رمز
يكتب data/r_native/market_pulse.json ذرّياً كلّ دورة،
ويُلحق الإشارات القويّة الجديدة في data/r_native/market_pulse_feed.jsonl.
"""

import os, sys, io

# ── أوّل شيء: تحويل stdout/stderr لملفّ سجلّ (pythonw بلا كونسول) ──
_BASE = os.path.dirname(os.path.abspath(__file__))
_LOG_PATH = os.path.join(_BASE, "data", "r_native", "market_pulse.out.log")
os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
try:
    _log_f = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
except Exception:
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

import json, time, math
from datetime import datetime

import numpy as np
import MetaTrader5 as mt5

import smc_engine   # سياق SMC بصري فقط — لا يدخل في أوزان درجة الضغط

# ── قفل النسخة الوحيدة (اختياريّ — نتابع لو فشل الاستيراد) ──
try:
    import engine_lock
    engine_lock.claim("market_pulse")
except SystemExit:
    raise
except Exception as e:
    print(f"[lock] engine_lock غير متاح ({e}) — نتابع بدون قفل")

# ── الثوابت والمسارات ──
SYMBOLS = ["XAUUSDm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "USDCHFm",
           "USDCADm", "AUDUSDm", "NZDUSDm", "EURJPYm", "GBPJPYm",
           "BTCUSDm", "ETHUSDm", "USOILm", "US30m", "US500m", "DXYm"]

OUT_JSON  = os.path.join(_BASE, "data", "r_native", "market_pulse.json")
FEED_PATH = os.path.join(_BASE, "data", "r_native", "market_pulse_feed.jsonl")
CFG_PATH  = os.path.join(_BASE, "data", "r_native", "market_pulse_config.json")

DEDUP_S     = 600      # لا نكرّر نفس الرمز+الاتجاه في التغذية خلال 10 دقائق
BULL_TH     = 72.0     # عتبة الإشارة الصعوديّة القويّة
BEAR_TH     = 28.0     # عتبة الإشارة الهبوطيّة القويّة
VOL_SPIKE_Z = 2.0      # عتبة سبايك الحجم

# ── الإعدادات ──
def load_config():
    """قراءة الإعدادات مع قيم افتراضيّة (setdefault)."""
    cfg = {}
    try:
        with open(CFG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    cfg.setdefault("enabled", True)
    cfg.setdefault("poll_s", 4)
    return cfg


# ═══════════════════ أدوات المؤشّرات ═══════════════════

def ema(vals, period):
    """متوسّط أسّي بسيط على مصفوفة numpy — يعيد آخر قيمة والسلسلة."""
    k = 2.0 / (period + 1.0)
    out = np.empty(len(vals))
    out[0] = vals[0]
    for i in range(1, len(vals)):
        out[i] = vals[i] * k + out[i - 1] * (1.0 - k)
    return out

def rsi_wilder(closes, period=9):
    """RSI بطريقة Wilder (تنعيم أسّي بمعامل 1/period)."""
    d = np.diff(closes)
    if len(d) < period + 1:
        return 50.0
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag = gains[:period].mean()
    al = losses[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al <= 1e-12:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)

def stoch_933(high, low, close):
    """Stoch(9,3,3): %K خام على 9 ثمّ تنعيم 3 ثمّ %D تنعيم 3. يعيد (K, D)."""
    n = len(close)
    if n < 15:
        return 50.0, 50.0
    raw = np.empty(n - 8)
    for i in range(8, n):
        hh = high[i - 8:i + 1].max()
        ll = low[i - 8:i + 1].min()
        rng = hh - ll
        raw[i - 8] = 50.0 if rng <= 1e-12 else (close[i] - ll) / rng * 100.0
    if len(raw) < 5:
        return 50.0, 50.0
    k = np.convolve(raw, np.ones(3) / 3.0, mode="valid")   # تنعيم %K
    if len(k) < 3:
        return float(k[-1]), float(k[-1])
    d = np.convolve(k, np.ones(3) / 3.0, mode="valid")     # تنعيم %D
    return float(k[-1]), float(d[-1])

def atr14(high, low, close):
    """ATR(14) بتنعيم Wilder على بيانات M5."""
    n = len(close)
    if n < 16:
        return 0.0
    trs = np.empty(n - 1)
    for i in range(1, n):
        trs[i - 1] = max(high[i] - low[i],
                         abs(high[i] - close[i - 1]),
                         abs(low[i] - close[i - 1]))
    a = trs[:14].mean()
    for i in range(14, len(trs)):
        a = (a * 13 + trs[i]) / 14.0
    return float(a)


# ═══════════════════ أنماط الشموع ═══════════════════

def detect_pattern(o, h, l, c):
    """
    يكشف أنماط آخر شمعة مُغلقة (المصفوفات تنتهي بآخر شمعة مُغلقة).
    يعيد (الاسم العربي، الاتجاه ±1/0، القوّة 0-4). يختار الأقوى عند التعدّد.
    """
    n = len(c)
    if n < 4:
        return "", 0, 0
    i = n - 1                      # آخر شمعة مُغلقة
    body = c[i] - o[i]
    rng = h[i] - l[i]
    if rng <= 1e-12:
        return "", 0, 0
    ab = abs(body)
    up_w = h[i] - max(o[i], c[i])   # الفتيل العلويّ
    lo_w = min(o[i], c[i]) - l[i]   # الفتيل السفليّ
    pb = abs(c[i - 1] - o[i - 1])   # جسم الشمعة السابقة

    found = []   # (قوّة، اسم، اتجاه)

    # ثلاثة جنود بيض / ثلاثة غربان سود (3 شموع)
    if n >= 3:
        bodies = [c[i - 2] - o[i - 2], c[i - 1] - o[i - 1], body]
        rngs = [h[i - 2] - l[i - 2], h[i - 1] - l[i - 1], rng]
        solid = all(r > 1e-12 and abs(b) >= 0.5 * r for b, r in zip(bodies, rngs))
        if solid and all(b > 0 for b in bodies) and c[i] > c[i - 1] > c[i - 2]:
            found.append((4, "ثلاثة جنود بيض", 1))
        if solid and all(b < 0 for b in bodies) and c[i] < c[i - 1] < c[i - 2]:
            found.append((4, "ثلاثة غربان سود", -1))

    # ابتلاع (جسم يبتلع جسم السابقة بالكامل وباتجاه معاكس)
    if pb > 1e-12 and ab > pb:
        if body > 0 and o[i - 1] > c[i - 1] and c[i] >= max(o[i - 1], c[i - 1]) and o[i] <= min(o[i - 1], c[i - 1]):
            found.append((3, "ابتلاع صعوديّ", 1))
        if body < 0 and c[i - 1] > o[i - 1] and c[i] <= min(o[i - 1], c[i - 1]) and o[i] >= max(o[i - 1], c[i - 1]):
            found.append((3, "ابتلاع هبوطيّ", -1))

    # ماروبوزو (جسم ≥ 90% من المدى)
    if ab >= 0.9 * rng:
        found.append((3, "ماروبوزو صاعد" if body > 0 else "ماروبوزو هابط", 1 if body > 0 else -1))

    # مطرقة / نجم ساقط (جسم صغير + فتيل مهيمن)
    if ab <= 0.35 * rng:
        if lo_w >= 2.0 * ab and up_w <= 0.25 * rng:
            found.append((2, "مطرقة", 1))
        if up_w >= 2.0 * ab and lo_w <= 0.25 * rng:
            found.append((2, "نجم ساقط", -1))

    # بن بار (فتيل ≥ 66% من المدى)
    if lo_w >= 0.66 * rng:
        found.append((2, "بن بار صعوديّ", 1))
    elif up_w >= 0.66 * rng:
        found.append((2, "بن بار هبوطيّ", -1))

    # شمعة خارجيّة (مدى يحتوي مدى السابقة)
    if h[i] > h[i - 1] and l[i] < l[i - 1]:
        d = 1 if body > 0 else (-1 if body < 0 else 0)
        if d != 0:
            found.append((2, "شمعة خارجيّة صاعدة" if d > 0 else "شمعة خارجيّة هابطة", d))

    # شمعة داخليّة (انضغاط — محايدة)
    if h[i] <= h[i - 1] and l[i] >= l[i - 1]:
        found.append((1, "شمعة داخليّة", 0))

    # دوجي (جسم ≤ 10% من المدى)
    if ab <= 0.10 * rng:
        found.append((1, "دوجي", 0))

    if not found:
        return "", 0, 0
    found.sort(key=lambda x: x[0], reverse=True)
    s, name, d = found[0]
    return name, d, s


# ═══════════════════ البنية (فراكتال + BOS) ═══════════════════

def structure_m5(h, l, c):
    """
    قمم/قيعان فراكتالية 3-شموع على M5 (الوسطى أعلى/أدنى من الجارتين)،
    ثمّ كشف BOS: إغلاق آخر شمعة مُغلقة خلف آخر قمّة/قاع.
    يعيد dict: آخر مستويات + bos ±1/0.
    """
    n = len(c)
    swing_hi, swing_lo = [], []   # (index, level)
    for i in range(1, n - 1):
        if h[i] > h[i - 1] and h[i] > h[i + 1]:
            swing_hi.append((i, float(h[i])))
        if l[i] < l[i - 1] and l[i] < l[i + 1]:
            swing_lo.append((i, float(l[i])))
    last_hi = swing_hi[-1][1] if swing_hi else None
    last_lo = swing_lo[-1][1] if swing_lo else None
    bos = 0
    # نتجاهل القمّة/القاع إن كانت هي الشمعة قبل الأخيرة نفسها (كسر ذاتيّ زائف)
    hi_lvl = None
    for idx, lvl in reversed(swing_hi):
        if idx < n - 2:
            hi_lvl = lvl
            break
    lo_lvl = None
    for idx, lvl in reversed(swing_lo):
        if idx < n - 2:
            lo_lvl = lvl
            break
    close_last = float(c[-1])
    if hi_lvl is not None and close_last > hi_lvl:
        bos = 1
    elif lo_lvl is not None and close_last < lo_lvl:
        bos = -1
    return {"swing_high": last_hi, "swing_low": last_lo, "bos": bos}


# ═══════════════════ تحليل رمز واحد ═══════════════════

def analyze_symbol(sym):
    """يجلب M1/M5 ويحسب كلّ الحقول. يعيد dict أو None عند فشل البيانات."""
    r1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 120)
    r5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 100)
    if r1 is None or r5 is None or len(r1) < 40 or len(r5) < 30:
        return None

    # مصفوفات float — الشمعة الأخيرة [−1] حيّة، لذا "آخر مُغلقة" = [:-1]
    o1 = r1["open"].astype(float);  h1 = r1["high"].astype(float)
    l1 = r1["low"].astype(float);   c1 = r1["close"].astype(float)
    v1 = r1["tick_volume"].astype(float)
    o5 = r5["open"].astype(float);  h5 = r5["high"].astype(float)
    l5 = r5["low"].astype(float);   c5 = r5["close"].astype(float)
    v5 = r5["tick_volume"].astype(float)
    t5 = r5["time"].astype(int)

    # ── 1) أنماط الشموع على آخر شمعة مُغلقة ──
    p1_name, p1_dir, p1_str = detect_pattern(o1[:-1], h1[:-1], l1[:-1], c1[:-1])
    p5_name, p5_dir, p5_str = detect_pattern(o5[:-1], h5[:-1], l5[:-1], c5[:-1])

    # ── 2) البنية على M5 (شموع مُغلقة) ──
    st = structure_m5(h5[:-1], l5[:-1], c5[:-1])
    bos = st["bos"]

    # ── 2ب) SMC على M5 (شموع مُغلقة) — سياق بصري فقط، لا يمسّ الدرجة ──
    smc = None
    smc_fresh = False
    try:
        smc = smc_engine.compute_smc(o5[:-1], h5[:-1], l5[:-1], c5[:-1], v5[:-1])
        n_closed = len(c5) - 1
        recent = [e["idx"] for e in (smc["bos"] + smc["choch"] + smc["sweeps"])]
        smc_fresh = any(idx >= n_closed - 3 for idx in recent)
    except Exception as e:
        print(f"[{sym}] خطأ SMC: {e}")

    # ── 3) الزخم ──
    stoch_k, stoch_d = stoch_933(h1, l1, c1)
    rsi9 = rsi_wilder(c1, 9)
    e9_1 = ema(c1, 9)[-1];   e21_1 = ema(c1, 21)[-1]
    e9_5 = ema(c5, 9)[-1];   e21_5 = ema(c5, 21)[-1]
    trend_m1 = 1 if e9_1 > e21_1 else (-1 if e9_1 < e21_1 else 0)
    trend_m5 = 1 if e9_5 > e21_5 else (-1 if e9_5 < e21_5 else 0)

    # ── 4) الحجم: z-score آخر شمعة مُغلقة مقابل 30 قبلها ──
    vol_z = 0.0
    if len(v1) >= 33:
        base = v1[-32:-2]           # الثلاثون السابقة لآخر مُغلقة
        mu = base.mean()
        sd = base.std()
        if sd > 1e-9:
            vol_z = float((v1[-2] - mu) / sd)
    vol_spike = vol_z > VOL_SPIKE_Z

    # ── 5) التقلّب والتكلفة ──
    atr = atr14(h5, l5, c5)
    tick = mt5.symbol_info_tick(sym)
    bid = float(tick.bid) if tick else float(c1[-1])
    ask = float(tick.ask) if tick else float(c1[-1])
    spread = max(0.0, ask - bid)
    spread_atr_pct = (spread / atr * 100.0) if atr > 1e-12 else 0.0

    # ── 6) درجة الضغط 0-100 (حسّاسة — وزن M1 أثقل) ──
    # الاتجاه (30%): M1 بوزن 0.65 و M5 بوزن 0.35
    trend_comp = 0.65 * trend_m1 + 0.35 * trend_m5
    # الزخم (25%): ستوكاستك + RSI + تقاطع K/D — كلّها من M1
    mom_comp = 0.4 * ((stoch_k - 50.0) / 50.0) \
             + 0.4 * ((rsi9 - 50.0) / 50.0) \
             + 0.2 * (1.0 if stoch_k > stoch_d else -1.0)
    mom_comp = max(-1.0, min(1.0, mom_comp))
    # الأنماط (20%): M1 بوزن 0.65 و M5 بوزن 0.35، مُدرَّجة بالقوّة
    pat_comp = 0.65 * p1_dir * (p1_str / 4.0) + 0.35 * p5_dir * (p5_str / 4.0)
    # البنية (15%): BOS مباشر
    struct_comp = float(bos)
    # الحجم (10%): سبايك يعزّز اتجاه الشمعة الأخيرة
    last_body_dir = 1 if c1[-2] > o1[-2] else (-1 if c1[-2] < o1[-2] else 0)
    vol_comp = last_body_dir * min(1.0, max(0.0, vol_z / 3.0)) if vol_spike else 0.0

    raw = 0.30 * trend_comp + 0.25 * mom_comp + 0.20 * pat_comp \
        + 0.15 * struct_comp + 0.10 * vol_comp
    score = round(max(0.0, min(100.0, 50.0 + 50.0 * raw)), 1)

    # ── 7) سطر القراءة العربيّ ──
    bits = []
    if p1_name:
        bits.append(f"{p1_name} M1")
    if p5_name and p5_name != p1_name:
        bits.append(f"{p5_name} M5")
    if bos == 1:
        bits.append("كسر بنية صاعد")
    elif bos == -1:
        bits.append("كسر بنية هابط")
    if mom_comp > 0.35:
        bits.append("زخم صاعد قويّ")
    elif mom_comp < -0.35:
        bits.append("زخم هابط قويّ")
    if vol_spike:
        bits.append(f"سبايك حجم z={vol_z:.1f}")
    if trend_m1 == trend_m5 == 1:
        bits.append("اتّجاه صاعد M1+M5")
    elif trend_m1 == trend_m5 == -1:
        bits.append("اتّجاه هابط M1+M5")
    if spread_atr_pct > 25:
        bits.append("سبريد مرتفع")
    if not bits:
        bits.append("حياد — لا إشارة واضحة")
    read = " + ".join(bits[:4])
    # حدث SMC طازج (آخر 3 شموع M5) → نُلحق ملخّصه بالقراءة (سياق بصري فقط)
    if smc and smc_fresh and smc.get("summary"):
        read += " · " + smc["summary"]

    digits = 5
    info = mt5.symbol_info(sym)
    if info:
        digits = int(info.digits)

    return {
        "price": round(bid, digits),
        "score": score,
        "read": read,
        "pattern_m1": {"name": p1_name, "dir": p1_dir, "strength": p1_str},
        "pattern_m5": {"name": p5_name, "dir": p5_dir, "strength": p5_str},
        "structure": {"bos": bos,
                      "swing_high": round(st["swing_high"], digits) if st["swing_high"] else None,
                      "swing_low": round(st["swing_low"], digits) if st["swing_low"] else None},
        "momentum": {"stoch_k": round(stoch_k, 1), "stoch_d": round(stoch_d, 1),
                     "rsi9": round(rsi9, 1),
                     "trend_m1": trend_m1, "trend_m5": trend_m5},
        "volume": {"z": round(vol_z, 2), "spike": bool(vol_spike)},
        "volatility": {"atr14_m5": round(atr, digits),
                       "spread": round(spread, digits),
                       "spread_atr_pct": round(spread_atr_pct, 1)},
        "spark": [round(float(x), digits) for x in c1[-40:]],
        "smc": smc,
        "candles_m5": [[int(t5[j]), round(float(o5[j]), digits),
                        round(float(h5[j]), digits), round(float(l5[j]), digits),
                        round(float(c5[j]), digits)]
                       for j in range(max(0, len(c5) - 60), len(c5))],
        # فهرس أوّل شمعة مُصدَّرة ضمن سلسلة SMC الكاملة — لمحاذاة المناطق في الواجهة
        "candles_m5_first_idx": max(0, len(c5) - 60),
    }


# ═══════════════════ الكتابة الذرّية والتغذية ═══════════════════

def atomic_write(path, obj):
    """كتابة ذرّية: ملفّ مؤقّت ثمّ os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)

def maybe_feed(sym, d, last_feed):
    """
    إشارة قويّة = نمط + BOS + زخم كلّها بنفس الاتجاه + درجة متطرّفة.
    منع التكرار: نفس الرمز+الاتجاه خلال 10 دقائق يُتجاهَل.
    """
    score = d["score"]
    if not (score >= BULL_TH or score <= BEAR_TH):
        return
    direction = 1 if score >= BULL_TH else -1
    pat_dir = d["pattern_m1"]["dir"] or d["pattern_m5"]["dir"]
    bos = d["structure"]["bos"]
    mom = d["momentum"]
    mom_dir = 1 if (mom["stoch_k"] > mom["stoch_d"] and mom["rsi9"] > 50) else \
              (-1 if (mom["stoch_k"] < mom["stoch_d"] and mom["rsi9"] < 50) else 0)
    if not (pat_dir == bos == mom_dir == direction):
        return
    key = f"{sym}:{direction}"
    now = time.time()
    if now - last_feed.get(key, 0) < DEDUP_S:
        return
    last_feed[key] = now
    rec = {"ts": round(now, 1),
           "iso": datetime.now().strftime("%H:%M:%S"),
           "symbol": sym, "dir": direction, "score": score,
           "pattern": d["pattern_m1"]["name"] or d["pattern_m5"]["name"],
           "read": d["read"], "price": d["price"]}
    try:
        with open(FEED_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[feed] {sym} dir={direction} score={score} — {d['read']}")
    except Exception as e:
        print(f"[feed] فشل الإلحاق: {e}")


# ═══════════════════ الحلقة الرئيسيّة ═══════════════════

def mt5_connect():
    """اتّصال واحد لكلّ عمليّة — 6 محاولات بينها 10 ثوانٍ."""
    for attempt in range(6):
        if mt5.initialize():
            print(f"[mt5] متّصل (محاولة {attempt + 1})")
            return True
        print(f"[mt5] فشل initialize (محاولة {attempt + 1}/6): {mt5.last_error()}")
        time.sleep(10)
    return False

def main():
    print(f"\n[market_pulse] بدء التشغيل {datetime.now().isoformat()}")
    if not mt5_connect():
        print("[market_pulse] تعذّر الاتّصال بـ MT5 — خروج")
        return

    for s in SYMBOLS:
        try:
            mt5.symbol_select(s, True)
        except Exception:
            pass

    last_feed = {}      # منع تكرار الإشارات: {"SYM:dir": ts}
    cfg_check = 0.0
    cfg = load_config()
    empty_streak = 0    # 🔧 عدّاد دورات صفر-رمز متتالية (اتصال MT5 وَهَن بعد السبات ⇒ نعيد التهيئة)

    while True:
        t0 = time.time()
        # إعادة قراءة الإعدادات كلّ ~30 ثانية
        if t0 - cfg_check > 30:
            cfg = load_config()
            cfg_check = t0
        if not cfg.get("enabled", True):
            time.sleep(5)
            continue

        out = {"ts": round(t0, 1),
               "iso": datetime.now().strftime("%H:%M:%S"),
               "symbols": {}}
        for sym in SYMBOLS:
            try:
                d = analyze_symbol(sym)
                if d is None:
                    continue
                out["symbols"][sym] = d
                maybe_feed(sym, d, last_feed)
            except Exception as e:
                print(f"[{sym}] خطأ تحليل: {e}")

        # 🔧 شفاء ذاتيّ: دورتان متتاليتان بلا أيّ رمز = اتصال MT5 ميّت (IPC وَهَن) ⇒ أعد التهيئة
        if not out["symbols"]:
            empty_streak += 1
            if empty_streak >= 2:
                print(f"[heal] {empty_streak} دورات صفر-رمز — إعادة تهيئة MT5")
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                time.sleep(2)
                for _ in range(3):
                    if mt5.initialize():
                        for s in SYMBOLS:
                            try:
                                mt5.symbol_select(s, True)
                            except Exception:
                                pass
                        print("[heal] أُعيدت التهيئة ✅"); break
                    time.sleep(5)
                empty_streak = 0
                time.sleep(3); continue           # لا تكتب ملفّاً فارغاً — أعطِ الاتصال دورةً ليتعافى
        else:
            empty_streak = 0

        try:
            atomic_write(OUT_JSON, out)
        except Exception as e:
            print(f"[write] فشل الكتابة الذرّية: {e}")

        # نوم حتى إكمال الدورة (poll_s ناقص زمن الحساب)
        elapsed = time.time() - t0
        time.sleep(max(0.5, float(cfg.get("poll_s", 4)) - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"[fatal] {e}\n{traceback.format_exc()}")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
