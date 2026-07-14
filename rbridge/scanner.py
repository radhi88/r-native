"""
scanner.py — ماسح خفيف وحتمي (بدون كلود) لكل الأزواج.
الفلسفة: رياضيات رخيصة تمسح كل شي وترتّبه، وكلود يأكّد القائمة المختصرة فقط.
يحسب لكل فريم: اتجاه EMA + كسر هيكل بسيط، ثم يجمع توافق الفريمات.

⚠️ صدق علميّ (FRIDAY): هذا ترتيب **حتميّ للعرض**، لا حافّة ربح. المشروع أثبت أنّ تأكيد
EMA/الهيكل متعدّد-الفريمات ~50% بعد التكلفة. استعمله لِفرز ما تنظر إليه، لا كإشارة دخول.
قناعة FRIDAY الحقيقية (فيتو Bonferroni/التكلفة) تُضاف بجانبه في الخادم.
"""
import mt5_client as mt5c

# أوزان الفريمات: الأعلى يوزن أكثر
TF_WEIGHTS = {"M5": 1, "M15": 1.5, "M30": 2, "H1": 2.5, "H4": 3.5, "D1": 4}


def _ema(values, period):
    if not values:
        return []
    k = 2 / (period + 1)
    e = values[0]
    out = []
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.0
    n = min(period, len(trs))
    return sum(trs[-n:]) / n


def analyze_tf(candles):
    """يرجّع {bias, score, note} لفريم واحد. score من -100 إلى 100."""
    if len(candles) < 60:
        return {"bias": "NEUTRAL", "score": 0, "note": "بيانات غير كافية"}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1]

    e50 = _ema(closes, 50)[-1]
    e200 = _ema(closes, 200)[-1] if len(closes) >= 200 else _ema(closes, 100)[-1]
    atr = _atr(highs, lows, closes) or 1e-9

    score = 0.0
    notes = []

    # 1) ترتيب المتوسطات
    if price > e50 > e200:
        score += 40; notes.append("ترتيب صاعد")
    elif price < e50 < e200:
        score -= 40; notes.append("ترتيب هابط")

    # 2) بُعد السعر عن EMA50 منسوب لـ ATR (زخم)
    dist = (price - e50) / atr
    score += max(-25, min(25, dist * 12))

    # 3) كسر هيكل بسيط: مقارنة بأعلى/أدنى آخر 20 (باستثناء الأخيرة)
    win_high = max(highs[-21:-1])
    win_low = min(lows[-21:-1])
    if price > win_high:
        score += 25; notes.append("كسر قمة")
    elif price < win_low:
        score -= 25; notes.append("كسر قاع")

    score = max(-100, min(100, score))
    bias = "BUY" if score > 15 else "SELL" if score < -15 else "NEUTRAL"
    return {"bias": bias, "score": round(score, 1), "note": "، ".join(notes) or "تجميع"}


def scan_symbol(symbol, tfs):
    """يمسح رمز واحد على عدة فريمات ويرجّع التوافق الكلي."""
    per_tf = []
    weighted = 0.0
    total_w = 0.0
    for tf in tfs:
        candles = mt5c.rates(symbol, tf, 250)
        a = analyze_tf(candles)
        a["tf"] = tf
        per_tf.append(a)
        w = TF_WEIGHTS.get(tf, 1)
        weighted += a["score"] * w
        total_w += w

    agg = weighted / total_w if total_w else 0
    # قوة التوافق: كم فريم يتفق مع الاتجاه الكلي
    direction = "BUY" if agg > 12 else "SELL" if agg < -12 else "NEUTRAL"
    aligned = sum(1 for a in per_tf if a["bias"] == direction and direction != "NEUTRAL")
    confidence = round(min(100, abs(agg) * 0.7 + (aligned / max(1, len(tfs))) * 30))

    t = mt5c.tick(symbol) or {}
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "agg_score": round(agg, 1),
        "aligned": f"{aligned}/{len(tfs)}",
        "bid": t.get("bid"),
        "ask": t.get("ask"),
        "spread": t.get("spread"),
        "timeframes": per_tf,
    }


def scan_all(symbols, tfs):
    """يمسح كل الأزواج ويرتّبها حسب الثقة (الأقوى أولاً)."""
    rows = []
    for s in symbols:
        try:
            rows.append(scan_symbol(s, tfs))
        except Exception as e:
            rows.append({"symbol": s, "direction": "NEUTRAL", "confidence": 0, "error": str(e)})
    rows.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    return rows
