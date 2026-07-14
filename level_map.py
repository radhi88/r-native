# -*- coding: utf-8 -*-
"""level_map.py — خريطة المستويات الهدف القادمة (شرط المستخدم).

«مو نغلق الربع بسرعة — نشوف المستويات اللي راح يتوجه لها السعر بعد كسر المقاومة/الدعم: قمّة وقاع
الأمس، فيبوناتشي، زوايا جان ومربّع التسعة، وATR مبنيٌّ على طول الشمعة وقوّتها». قراءة-فقط نقيّة:
يجمع مستويات هدفٍ من عدّة مصادر هندسيّة ويرتّبها فوق/تحت السعر ⇒ «الهدف التالي» في اتجاهنا، كي
ندع الربح يجري إلى المستوى التالي بدل الإغلاق المبكّر. لا يتداول.
"""
from __future__ import annotations
import math
import MetaTrader5 as mt5


def atr_strength(rates, n=14):
    """ATR مُعدّل بقوّة الشمعة (شرط المستخدم): مدى صادق × (1 + نسبة الجسم) — الشموع القويّة الاتجاهيّة
    (جسمٌ كبير نسبةً للمدى) تُوسّع تقدير المدى ⇒ هدفٌ أبعد. الشموع الضعيفة (دوجي) تُبقيه قُرب ATR."""
    if rates is None or len(rates) < n + 1:
        return 0.0
    h = rates["high"]; l = rates["low"]; c = rates["close"]; o = rates["open"]
    trs = []
    for i in range(len(rates) - n, len(rates)):
        tr = max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0
    rng = sum(float(h[i] - l[i]) for i in range(len(rates) - n, len(rates))) / n
    body = sum(abs(float(c[i] - o[i])) for i in range(len(rates) - n, len(rates))) / n
    strength = (body / rng) if rng > 0 else 0.0          # 0=دوجي 1=ماروبوزو
    return atr * (1.0 + strength)                         # قوّة الشمعة تُوسّع المدى


def prev_day(sym):
    """قمّة/قاع/إغلاق الأمس + افتتاح اليوم (مستويات يوميّة يحترمها السوق)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3)
    if r is None or len(r) < 2:
        return {}
    y = r[-2]                                             # شمعة الأمس
    today_open = float(r[-1]["open"])
    return {"pdh": float(y["high"]), "pdl": float(y["low"]), "pdc": float(y["close"]), "today_open": today_open}


def pivots(pdh, pdl, pdc):
    """نقاط البايفوت الكلاسيكيّة من قمّة/قاع/إغلاق الأمس (مقاومات/دعوم يوميّة)."""
    pp = (pdh + pdl + pdc) / 3.0
    r1 = 2 * pp - pdl; s1 = 2 * pp - pdh
    r2 = pp + (pdh - pdl); s2 = pp - (pdh - pdl)
    r3 = pdh + 2 * (pp - pdl); s3 = pdl - 2 * (pdh - pp)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


def fib_levels(swing_hi, swing_lo, direction):
    """فيبوناتشي: تصحيحات + امتدادات. اتجاه صعود ⇒ امتدادات فوق القمّة (1.272/1.618/2.0)؛ هبوط ⇒ تحت القاع."""
    rng = swing_hi - swing_lo
    if rng <= 0:
        return {}
    out = {}
    for f in (0.382, 0.5, 0.618, 0.786):
        out[f"ret{int(f*1000)}"] = (swing_hi - f * rng) if direction > 0 else (swing_lo + f * rng)
    for f in (1.272, 1.618, 2.0, 2.618):                 # الامتدادات = أهداف ما بعد الكسر
        out[f"ext{int(f*1000)}"] = (swing_hi + (f - 1) * rng) if direction > 0 else (swing_lo - (f - 1) * rng)
    return out


def square_of_9(price, degrees=(90, 180, 360, 720)):
    """مربّع جان التسعة: مستويات حول السعر بدوران زوايا على الجذر (sqrt(p)±d/180)^2."""
    if price <= 0:
        return {}
    root = math.sqrt(price); out = {}
    for d in degrees:
        step = d / 180.0
        out[f"sq9+{int(d)}"] = round((root + step) ** 2, 6)
        if root > step:
            out[f"sq9-{int(d)}"] = round((root - step) ** 2, 6)
    return out


def star_of_david(price, base=None):
    """نجمة داوود (السداسيّة على عجلة جان): ستّ نقاط على بُعد 60° على حلزون مربّع التسعة، تشكّل مثلّثين
    متداخلين {60,180,300}∆ و{120,240,360}∇ = هندسة تناظرٍ سداسيّ. نفس صيغة Sq9 على مضاعفات 60°."""
    base = base if base else price
    if base <= 0:
        return {}
    root = math.sqrt(base); out = {}
    for d in (60, 120, 180, 240, 300, 360):
        step = d / 180.0
        out[f"star+{d}"] = round((root + step) ** 2, 6)
        if root > step:
            out[f"star-{d}"] = round((root - step) ** 2, 6)
    return out


def fractals(sym, tf=mt5.TIMEFRAME_M5, n=140, k=2):
    """فراكتلات ويليامز (شرط المستخدم): قمّةٌ مع k قمم أدنى كلّ جهة = فراكتل علويّ (مقاومة)؛ قاعٌ مع k
    قيعان أعلى = فراكتل سفليّ (دعم). نرجع أحدث فراكتلين + أبعد فراكتل في كلّ اتجاه (أهداف تأرجح)."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 2 * k + 1:
        return {}
    h = r["high"]; l = r["low"]; ups = []; downs = []
    for i in range(k, len(r) - k):
        if all(float(h[i]) > float(h[i - j]) and float(h[i]) > float(h[i + j]) for j in range(1, k + 1)):
            ups.append(float(h[i]))
        if all(float(l[i]) < float(l[i - j]) and float(l[i]) < float(l[i + j]) for j in range(1, k + 1)):
            downs.append(float(l[i]))
    out = {}
    if ups:
        out["fractal_up"] = ups[-1]; out["fractal_up_hi"] = max(ups)
    if downs:
        out["fractal_dn"] = downs[-1]; out["fractal_dn_lo"] = min(downs)
    return out


def gann_fan(pivot_price, direction, unit, bars):
    """زوايا جان 1×1/1×2/2×1 من بايفوت: سعرٌ لكل شمعة = unit (ATR مبنيّ على القوّة)."""
    if unit <= 0 or bars <= 0:
        return {}
    s = 1 if direction > 0 else -1
    return {"gann1x1": pivot_price + s * unit * bars,
            "gann1x2": pivot_price + s * (unit * 0.5) * bars,
            "gann2x1": pivot_price + s * (unit * 2.0) * bars}


def vwap(sym, bars=120):
    """VWAP (مؤسّسي): سعر التداول المرجّح بالحجم = Σ(typical×tick_volume)/Σ(tick_volume) على شموع M5.
    typical=(h+l+c)/3. مرجعٌ يراقبه المؤسّسات: فوقه = اتجاه شراء، تحته = بيع. قراءة-فقط/آمن."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, bars)
    if r is None or len(r) < 2:
        return None
    pv = 0.0; vol = 0.0
    for i in range(len(r)):
        tp = (float(r["high"][i]) + float(r["low"][i]) + float(r["close"][i])) / 3.0
        v = float(r["tick_volume"][i])
        pv += tp * v; vol += v
    if vol <= 0:
        return None
    return pv / vol


def poc(sym, bars=240, nbins=40):
    """ملف الحجم (Volume Profile): POC = مركز الخانة السعريّة بأعلى حجم تداول مُجمّع على فترة المراجعة.
    VAH/VAL = منطقة القيمة (الـ70% من الحجم حول POC). مستوياتٌ يحترمها السوق (أعلى قبول/سيولة).
    قراءة-فقط/آمن: يرجع None عند نقص البيانات. يرجع {'POC':..,'VAH':..,'VAL':..}."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, bars)
    if r is None or len(r) < 2:
        return None
    lo = float(min(r["low"])); hi = float(max(r["high"]))
    if hi <= lo or nbins < 1:
        return None
    width = (hi - lo) / nbins
    if width <= 0:
        return None
    binvol = [0.0] * nbins
    for i in range(len(r)):
        tp = (float(r["high"][i]) + float(r["low"][i]) + float(r["close"][i])) / 3.0
        v = float(r["tick_volume"][i])
        b = int((tp - lo) / width)
        if b >= nbins:
            b = nbins - 1
        if b < 0:
            b = 0
        binvol[b] += v
    total = sum(binvol)
    if total <= 0:
        return None
    poc_bin = max(range(nbins), key=lambda b: binvol[b])
    center = lambda b: lo + (b + 0.5) * width
    # منطقة القيمة: توسّع حول POC حتى يُغطّى 70% من الحجم
    target = 0.70 * total
    lo_b = hi_b = poc_bin
    acc = binvol[poc_bin]
    while acc < target and (lo_b > 0 or hi_b < nbins - 1):
        down_v = binvol[lo_b - 1] if lo_b > 0 else -1.0
        up_v = binvol[hi_b + 1] if hi_b < nbins - 1 else -1.0
        if up_v >= down_v:
            hi_b += 1; acc += binvol[hi_b]
        else:
            lo_b -= 1; acc += binvol[lo_b]
    return {"POC": center(poc_bin), "VAH": center(hi_b), "VAL": center(lo_b)}


def project(sym, direction, swing_bars=60):
    """يجمع كل المصادر ويرتّب المستويات فوق/تحت السعر. يرجع:
       {price, atr_strength, up:[..], down:[..], next: الهدف التالي في الاتجاه, all:{label:level}}."""
    tk = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    if not tk or not info:
        return None
    price = (tk.ask + tk.bid) / 2.0
    m5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, max(swing_bars, 60))
    atr_s = atr_strength(m5)
    levels = {}
    pd = prev_day(sym)
    if pd:
        levels.update({"PDH": pd["pdh"], "PDL": pd["pdl"], "PDC": pd["pdc"], "open": pd["today_open"]})
        levels.update(pivots(pd["pdh"], pd["pdl"], pd["pdc"]))
    if m5 is not None and len(m5) >= 10:
        sw = m5[-swing_bars:] if len(m5) >= swing_bars else m5
        shi = float(max(sw["high"])); slo = float(min(sw["low"]))
        levels.update(fib_levels(shi, slo, direction))
        # بايفوت جان من آخر طرف في اتجاهنا
        piv = slo if direction > 0 else shi
        levels.update(gann_fan(piv, direction, atr_s if atr_s > 0 else (shi - slo) / max(len(sw), 1), len(sw)))
    levels.update(square_of_9(price))
    levels.update(star_of_david(price))                  # ✡️ نجمة داوود (السداسيّة)
    levels.update(fractals(sym))                          # 🔺 فراكتلات ويليامز (تأرجح)
    vw = vwap(sym)                                        # 📊 VWAP مرجّح بالحجم (مؤسّسي)
    if vw:
        levels["VWAP"] = vw
    vp = poc(sym)                                         # 📊 POC/VAH/VAL ملف الحجم
    if vp:
        levels.update({"POC": vp["POC"], "VAH": vp["VAH"], "VAL": vp["VAL"]})
    # رتّب فوق/تحت السعر (تجاهل المستويات الملتصقة جداً < 0.05 ATR)
    tol = 0.05 * atr_s if atr_s > 0 else 0
    up = sorted({lbl: v for lbl, v in levels.items() if v and v - price > tol}.items(), key=lambda kv: kv[1])
    down = sorted({lbl: v for lbl, v in levels.items() if v and price - v > tol}.items(), key=lambda kv: kv[1], reverse=True)
    nxt = (up[0] if direction > 0 else down[0]) if (up if direction > 0 else down) else None
    return {"symbol": sym, "price": round(price, info.digits), "atr_strength": round(atr_s, 5),
            "direction": direction,
            "up": [(l, round(v, info.digits)) for l, v in up[:5]],
            "down": [(l, round(v, info.digits)) for l, v in down[:5]],
            "next": (nxt[0], round(nxt[1], info.digits)) if nxt else None,
            "all": {l: round(v, info.digits) for l, v in levels.items() if v}}


def _level_type(lbl):
    """تصنيف المستوى لنوعه الهندسيّ (لقياس تنوّع الالتقاء)."""
    l = lbl.lower()
    if l.startswith(("ret", "ext")):
        return "fib"
    if l.startswith("sq9"):
        return "gann"
    if l.startswith("star"):
        return "star"
    if l.startswith("fractal"):
        return "fractal"
    if l.startswith(("vwap", "poc", "vah", "val")):
        return "volume"
    if l.startswith(("pdh", "pdl", "pdc", "open")):
        return "prevday"
    if l.startswith(("pp", "r", "s")):
        return "pivot"
    return "other"


def confluence_zones(sym, band_atr=0.25, min_levels=3):
    """🎯 مناطق الالتقاء (شرط المستخدم: أهداف عالية-الثقة): حين تتكدّس ≥min_levels مستوياتٍ هندسيّة **متنوّعة**
    في نطاقٍ ضيّق (band_atr×ATR) ⇒ منطقة عالية-الاحتمال (الكلّ يراقبها: بنوك/خوارزميّات). القوّة = العدد +
    التنوّع. تُستعمل كـ: أهدافٍ نثق بوصولها أكثر، ومناطق دخولٍ للأوامر المحدّدة (احتمال تعبئة + ارتداد أعلى).
    ليست يقيناً — ترفع الاحتمال. يرجع مناطق مرتّبة بالقوّة: [{center,n,types,strength,labels,lo,hi}]."""
    tk = mt5.symbol_info_tick(sym); info = mt5.symbol_info(sym)
    if not tk or not info:
        return []
    dig = info.digits
    atr = atr_strength(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60))
    if atr <= 0:
        return []
    band = band_atr * atr
    proj = project(sym, 1)
    if not proj:
        return []
    items = sorted(((lbl, v) for lbl, v in proj["all"].items() if v), key=lambda kv: kv[1])
    zones = []; i = 0
    while i < len(items):
        cluster = [items[i]]; j = i + 1
        while j < len(items) and items[j][1] - cluster[0][1] <= band:
            cluster.append(items[j]); j += 1
        if len(cluster) >= min_levels:
            vals = [v for _, v in cluster]
            types = set(_level_type(lbl) for lbl, _ in cluster)
            zones.append({"center": round(sum(vals) / len(vals), dig), "n": len(cluster),
                          "types": len(types), "strength": len(cluster) + len(types),
                          "labels": [lbl for lbl, _ in cluster],
                          "lo": round(min(vals), dig), "hi": round(max(vals), dig)})
        i = j if j > i + 1 else i + 1
    zones.sort(key=lambda z: -z["strength"])
    return zones


if __name__ == "__main__":      # عرض سريع
    if mt5.initialize():
        for s in ("XAUUSDm", "BTCUSDm"):
            for d in (1, -1):
                r = project(s, d)
                if r:
                    print(f"{s} {'UP' if d>0 else 'DN'} price {r['price']} atrS {r['atr_strength']} next {r['next']} | "
                          f"{'فوق' if d>0 else 'تحت'}: {(r['up'] if d>0 else r['down'])[:3]}")
        mt5.shutdown()
