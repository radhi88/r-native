# -*- coding: utf-8 -*-
"""
smc_engine.py — محرك SMC نقي (حساب فقط، بدون MT5)
=====================================================
وحدة مستقلة تعمل على مصفوفات OHLCV عادية (numpy أو lists).
كل الحسابات سببية (causal): لا نظرة مستقبلية — المناطق تُبنى من شموع مغلقة فقط،
والقمم/القيعان لا "تتأكد" إلا بعد k شموع لاحقة.

تذكير صادق (مقاس في هذا المشروع): SMC كتنبؤ = لا أفضلية
(CHoCH ~50% بأثر رجعي، IFVG ~52%، TP عند مناطق SMC أسوأ من R ثابت).
هذه الوحدة = سياق بصري للقراءة اليدوية فقط — ممنوع ربطها بأي مسار أوامر.
"""

import numpy as np


# ---------------------------------------------------------------- أدوات داخلية

def _arr(x):
    """تحويل أي list/np إلى numpy float64."""
    return np.asarray(x, dtype=np.float64)


def _atr(h, l, c, period=14):
    """ATR بطريقة Wilder — مصفوفة سببية بطول السلسلة (atr[i] يستخدم الماضي فقط)."""
    h, l, c = _arr(h), _arr(l), _arr(c)
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.empty(n)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ------------------------------------------------------------------- 1) القمم والقيعان

def swings(h, l, k=2):
    """قمم/قيعان فراكتالية: قمة عند i إذا كانت h[i] أعلى من k شموع قبلها وبعدها.
    ملاحظة سببية: القمة عند i لا تُعرف إلا عند إغلاق الشمعة i+k.
    ترجع dict: {'highs': [(idx, price)], 'lows': [(idx, price)], 'k': k}"""
    h, l = _arr(h), _arr(l)
    n = len(h)
    highs, lows = [], []
    for i in range(k, n - k):
        left_h, right_h = h[i - k:i], h[i + 1:i + k + 1]
        if h[i] > left_h.max() and h[i] >= right_h.max():
            highs.append((i, float(h[i])))
        left_l, right_l = l[i - k:i], l[i + 1:i + k + 1]
        if l[i] < left_l.min() and l[i] <= right_l.min():
            lows.append((i, float(l[i])))
    return {"highs": highs, "lows": lows, "k": k}


# ------------------------------------------------------------------- 2) البنية BOS/CHoCH

def structure(closes, sw):
    """أحداث البنية: BOS = إغلاق خلف آخر قمة/قاع بنفس اتجاه الترند،
    CHoCH = أول إغلاق خلف الطرف المعاكس ضد الترند السائد.
    سببي: القمة/القاع لا يدخلان الحساب إلا بعد تأكيدهما (idx+k).
    ترجع آخر ~6 أحداث: [{'type','dir','idx','price'}]"""
    c = _arr(closes)
    sh, sl, k = sw["highs"], sw["lows"], sw["k"]
    events = []
    trend = 0                      # +1 صاعد / -1 هابط / 0 غير محدد
    jh = jl = 0
    last_sh = last_sl = None       # آخر قمة/قاع مؤكدين
    broken_h = broken_l = True     # لا كسر قبل وجود مرجع
    for i in range(len(c)):
        # تأكيد القمم/القيعان التي اكتملت k شموع بعدها
        while jh < len(sh) and sh[jh][0] + k <= i:
            last_sh = sh[jh]; jh += 1; broken_h = False
        while jl < len(sl) and sl[jl][0] + k <= i:
            last_sl = sl[jl]; jl += 1; broken_l = False
        if last_sh is not None and not broken_h and c[i] > last_sh[1]:
            typ = "CHoCH" if trend == -1 else "BOS"
            events.append({"type": typ, "dir": 1, "idx": i, "price": float(c[i])})
            trend = 1; broken_h = True
        if last_sl is not None and not broken_l and c[i] < last_sl[1]:
            typ = "CHoCH" if trend == 1 else "BOS"
            events.append({"type": typ, "dir": -1, "idx": i, "price": float(c[i])})
            trend = -1; broken_l = True
    return events[-6:]


# ------------------------------------------------------------------- 3) مناطق الأوامر OB

def order_blocks(o, h, l, c, max_zones=4):
    """OB هابط = آخر شمعة صاعدة قبل اندفاع هابط قوي (>= 1.5×ATR14 خلال 3 شموع)،
    والعكس للصاعد. المنطقة = مدى الشمعة كاملاً (جسم+ذيل) [lo,hi].
    mitigated = السعر عاد لاحقاً واخترق المنطقة بالكامل."""
    o, h, l, c = _arr(o), _arr(h), _arr(l), _arr(c)
    n = len(c)
    atr = _atr(h, l, c)
    zones = []
    for i in range(1, n - 3):
        if atr[i] <= 0:
            continue
        impulse = 1.5 * atr[i]
        # OB هابط: شمعة صاعدة تليها شمعة هابطة واندفاع نزولي
        if c[i] > o[i] and c[i + 1] < o[i + 1]:
            drop = c[i] - c[i + 1:i + 4].min()
            if drop >= impulse:
                mitig = bool((h[i + 4:] >= h[i]).any()) if i + 4 < n else False
                zones.append({"idx": i, "dir": -1, "lo": float(l[i]),
                              "hi": float(h[i]), "mitigated": mitig})
                continue
        # OB صاعد: شمعة هابطة تليها شمعة صاعدة واندفاع صعودي
        if c[i] < o[i] and c[i + 1] > o[i + 1]:
            rise = c[i + 1:i + 4].max() - c[i]
            if rise >= impulse:
                mitig = bool((l[i + 4:] <= l[i]).any()) if i + 4 < n else False
                zones.append({"idx": i, "dir": 1, "lo": float(l[i]),
                              "hi": float(h[i]), "mitigated": mitig})
    return zones[-max_zones:]


# ------------------------------------------------------------------- 4) فجوات FVG / IFVG

def fvg(o, h, l, c, max_zones=4):
    """فجوة صاعدة عند الشمعة الوسطى i: low[i+1] > high[i-1] (والعكس للهابطة).
    filled = نسبة الامتلاء بتداول لاحق داخل الفجوة (0..1).
    IFVG: فجوة اختُرقت بالكامل ثم تعمل معكوسة → inverted=True مع قلب dir."""
    o, h, l, c = _arr(o), _arr(h), _arr(l), _arr(c)
    n = len(c)
    zones = []
    for i in range(1, n - 1):
        # فجوة صاعدة
        if l[i + 1] > h[i - 1]:
            bot, top = float(h[i - 1]), float(l[i + 1])
            filled = 0.0
            if i + 2 < n and top > bot:
                filled = float(np.clip((top - l[i + 2:].min()) / (top - bot), 0.0, 1.0))
            inv = filled >= 1.0
            zones.append({"idx": i, "dir": -1 if inv else 1, "lo": bot, "hi": top,
                          "filled": round(filled, 3), "inverted": inv})
        # فجوة هابطة
        elif h[i + 1] < l[i - 1]:
            top, bot = float(l[i - 1]), float(h[i + 1])
            filled = 0.0
            if i + 2 < n and top > bot:
                filled = float(np.clip((h[i + 2:].max() - bot) / (top - bot), 0.0, 1.0))
            inv = filled >= 1.0
            zones.append({"idx": i, "dir": 1 if inv else -1, "lo": bot, "hi": top,
                          "filled": round(filled, 3), "inverted": inv})
    return zones[-max_zones:]


# ------------------------------------------------------------------- 5) برك السيولة والاصطياد

def liquidity(h, l, sw, c=None):
    """برك سيولة = قمم/قيعان متساوية (2+ ضمن 0.15×ATR) — أماكن تجمع الستوبات ($$$).
    SWEEP = ذيل يخترق البركة ثم يغلق راجعاً خلفها.
    c اختياري (لو غاب نستخدم منتصف الشمعة كتقريب للإغلاق).
    ترجع (pools, sweeps)."""
    h, l = _arr(h), _arr(l)
    closes = _arr(c) if c is not None else (h + l) / 2.0
    rng = h - l
    atr_proxy = float(rng[-14:].mean()) if len(rng) >= 14 else float(rng.mean())
    tol = 0.15 * atr_proxy if atr_proxy > 0 else 1e-9
    n = len(h)

    def _cluster(points, side):
        pools = []
        for idx, p in points:
            for pool in pools:
                if abs(p - pool["price"]) <= tol:
                    pool["idxs"].append(idx)
                    pool["_ps"].append(p)
                    pool["price"] = float(np.mean(pool["_ps"]))
                    break
            else:
                pools.append({"side": side, "price": float(p), "idxs": [idx], "_ps": [p]})
        out = []
        for pool in pools:
            if len(pool["idxs"]) >= 2:
                pool.pop("_ps")
                pool["count"] = len(pool["idxs"])
                out.append(pool)
        return out

    pools = _cluster(sw["highs"], "high") + _cluster(sw["lows"], "low")
    sweeps = []
    for pool in pools:
        start = max(pool["idxs"]) + 1
        for j in range(start, n):
            if pool["side"] == "high" and h[j] > pool["price"] and closes[j] < pool["price"]:
                sweeps.append({"idx": j, "side": "high", "price": float(pool["price"])})
                break  # أول اصطياد لكل بركة يكفي
            if pool["side"] == "low" and l[j] < pool["price"] and closes[j] > pool["price"]:
                sweeps.append({"idx": j, "side": "low", "price": float(pool["price"])})
                break
    return pools, sweeps[-4:]


# ------------------------------------------------------------------- 6) بروفايل الحجم POC

def poc(h, l, c, tick_volume, bins=24):
    """نقطة التحكم الحجمية: توزيع tick_volume لكل شمعة على مداها H-L عبر صناديق سعرية.
    ترجع (poc_price, hvn_top3) — مركز صندوق الحجم الأعظم + أعلى 3 مستويات HVN."""
    h, l, v = _arr(h), _arr(l), _arr(tick_volume)
    lo, hi = float(l.min()), float(h.max())
    if hi <= lo:
        return float(round(lo, 3)), [float(round(lo, 3))]
    edges = np.linspace(lo, hi, bins + 1)
    vol_bins = np.zeros(bins)
    for i in range(len(h)):
        bh, bl, bv = h[i], l[i], v[i]
        span = bh - bl
        if span <= 0:  # شمعة نقطية: كل الحجم في صندوقها
            b = min(int((bl - lo) / (hi - lo) * bins), bins - 1)
            vol_bins[b] += bv
            continue
        for b in range(bins):
            ov = min(bh, edges[b + 1]) - max(bl, edges[b])
            if ov > 0:
                vol_bins[b] += bv * ov / span
    centers = (edges[:-1] + edges[1:]) / 2.0
    order = np.argsort(vol_bins)[::-1]
    poc_price = float(round(centers[order[0]], 3))
    hvn = [float(round(centers[b], 3)) for b in order[:3] if vol_bins[b] > 0]
    return poc_price, hvn


# ------------------------------------------------------------------- 7) الحزمة الكاملة

def compute_smc(o, h, l, c, vol):
    """حزمة SMC كاملة جاهزة لـ JSON — سياق بصري فقط (لا إشارة أوتوماتيكية)."""
    o, h, l, c = _arr(o), _arr(h), _arr(l), _arr(c)
    sw = swings(h, l, k=2)
    events = structure(c, sw)
    obs = order_blocks(o, h, l, c)
    gaps = fvg(o, h, l, c)
    pools, sweeps = liquidity(h, l, sw, c)
    poc_price, hvn = poc(h, l, c, vol)

    def _r(x):
        return float(round(float(x), 3))

    bos = [{**e, "price": _r(e["price"])} for e in events if e["type"] == "BOS"]
    choch = [{**e, "price": _r(e["price"])} for e in events if e["type"] == "CHoCH"]
    ob_out = [{**z, "lo": _r(z["lo"]), "hi": _r(z["hi"])} for z in obs]
    fvg_out = [{**z, "lo": _r(z["lo"]), "hi": _r(z["hi"])} for z in gaps]
    pools_out = [{"side": p["side"], "price": _r(p["price"]),
                  "count": p["count"], "idxs": p["idxs"]} for p in pools]
    sweeps_out = [{**s, "price": _r(s["price"])} for s in sweeps]
    trend = events[-1]["dir"] if events else 0
    last_close = float(c[-1])

    # ---- قراءة عربية بسطر واحد
    parts = []
    if events:
        e = events[-1]
        parts.append(f"{e['type']} {'صاعد' if e['dir'] > 0 else 'هابط'}")
    open_gaps = [z for z in gaps if not z["inverted"] and z["filled"] < 1.0]
    if open_gaps:
        g = open_gaps[-1]
        place = "تحت" if g["hi"] < last_close else ("فوق" if g["lo"] > last_close else "عند السعر")
        parts.append(f"FVG غير مملوء {place}")
    if sweeps_out:
        s = sweeps_out[-1]
        parts.append(f"اصطياد سيولة {'قمم' if s['side'] == 'high' else 'قيعان'} عند {s['price']}")
    elif pools_out:
        p = pools_out[-1]
        parts.append(f"بركة سيولة عند {p['price']}")
    parts.append(f"POC عند {poc_price}")
    summary = " + ".join(parts) if parts else "لا إشارات هيكلية واضحة"

    return {
        "bos": bos, "choch": choch, "ob": ob_out, "fvg": fvg_out,
        "liq_pools": pools_out, "sweeps": sweeps_out,
        "poc": poc_price, "hvn": hvn, "trend": int(trend),
        "summary": summary,
    }


# ------------------------------------------------------------------- اختبار ذاتي مصغر

if __name__ == "__main__":
    import json

    # 1) القمم والقيعان
    th = [1, 2, 3, 2, 1, 2, 5, 2, 1]
    tl = [5, 4, 3, 4, 5, 4, 1, 4, 5]
    sw1 = swings(th, tl, k=2)
    assert (2, 3.0) in sw1["highs"] and (6, 5.0) in sw1["highs"], "swing highs"
    assert (2, 3.0) in sw1["lows"] and (6, 1.0) in sw1["lows"], "swing lows"

    # 2) البنية: صعود مع كسور (BOS) ثم انهيار خلف القاع (CHoCH)
    cs = np.array([10, 11, 12, 11, 10.5, 11.5, 12.5, 13, 12, 11.5, 12.8, 14, 11, 9.5, 9])
    hh, ll = cs + 0.3, cs - 0.3
    ev = structure(cs, swings(hh, ll, k=2))
    assert any(e["type"] == "BOS" and e["dir"] == 1 for e in ev), "BOS up"
    assert any(e["type"] == "CHoCH" and e["dir"] == -1 for e in ev), "CHoCH down"

    # 3) OB هابط: شمعة صاعدة ثم اندفاع نزولي 6 نقاط (ATR~1) ثم عودة (mitigated)
    n0 = 25
    oo = [100.0] * n0 + [100.0, 101.0, 99.0, 97.0, 95.2, 95.0, 96.0]
    cc = [100.0] * n0 + [101.0, 99.0, 97.0, 95.0, 95.5, 96.0, 102.0]
    hh2 = [100.5] * n0 + [101.2, 100.9, 99.1, 97.1, 95.8, 96.2, 102.5]
    ll2 = [99.5] * n0 + [99.9, 98.9, 96.9, 94.9, 94.8, 94.9, 95.9]
    obs = order_blocks(oo, hh2, ll2, cc)
    bear = [z for z in obs if z["dir"] == -1]
    assert bear and bear[-1]["idx"] == n0 and bear[-1]["mitigated"], "bearish OB"

    # 4) FVG صاعد ثم امتلاء كامل → IFVG معكوس
    fo = [9.5, 9.8, 11.4, 11.9, 12.4]
    fh = [10.0, 11.5, 12.0, 12.5, 12.5]
    fl = [9.0, 9.7, 11.0, 11.8, 9.9]
    fc = [9.8, 11.4, 11.9, 12.4, 10.0]
    g1 = fvg(fo, fh, fl, fc)
    assert g1 and g1[0]["inverted"] and g1[0]["dir"] == -1, "IFVG"
    g2 = fvg(fo[:4], fh[:4], fl[:4], fc[:4])  # بدون الشمعة الهابطة → غير مملوء
    assert g2 and not g2[0]["inverted"] and g2[0]["filled"] < 1.0, "open FVG"

    # 5) قمم متساوية + اصطياد (ذيل فوق البركة وإغلاق تحتها)
    lh = [10, 10, 12, 10, 10, 10, 12.05, 10, 10, 12.5, 10]
    lll = [x - 1 for x in lh]
    lcc = [x - 0.5 for x in lh]; lcc[9] = 11.5
    pools, sweeps = liquidity(lh, lll, swings(lh, lll, k=2), lcc)
    hp = [p for p in pools if p["side"] == "high" and p["count"] >= 2]
    assert hp and abs(hp[0]["price"] - 12.025) < 0.1, "equal-highs pool"
    assert sweeps and sweeps[0]["side"] == "high" and sweeps[0]["idx"] == 9, "sweep"

    # 6) POC: الحجم متركز حول 50
    ph = [50.5] * 20 + [60.5, 61.0]
    pl = [49.5] * 20 + [59.5, 60.0]
    pcl = [50.0] * 20 + [60.0, 60.5]
    pv = [100] * 20 + [1, 1]
    p_price, hvn = poc(ph, pl, pcl, pv)
    assert abs(p_price - 50.0) < 1.0 and len(hvn) >= 1, "POC"

    # 7) الحزمة الكاملة على سلسلة البنية
    bundle = compute_smc(cs, hh, ll, cs, np.ones(len(cs)) * 10)
    for key in ("bos", "choch", "ob", "fvg", "liq_pools", "sweeps",
                "poc", "hvn", "trend", "summary"):
        assert key in bundle, f"missing {key}"
    assert bundle["trend"] == -1 and isinstance(bundle["summary"], str)
    json.dumps(bundle, ensure_ascii=False)  # جاهز لـ JSON

    print("SMC engine self-test: OK")
    print(json.dumps(bundle, ensure_ascii=False, indent=1))
