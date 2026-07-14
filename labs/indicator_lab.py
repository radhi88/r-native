# -*- coding: utf-8 -*-
"""indicator_lab.py — 🔬 مختبر الأرقام الشامل (طلب المستخدم 2026-07-03 الساعة 01:00):
«يجرّب كل الأرقام اختبارات معقّدة ويشوف أيّ تطابق أرقام راح يكون مربحاً».

المنهج الصارم (الدرس المدفوع الثمن — كل اختبار سابق بلا هذا مات):
  • شموع مغلقة فقط (لا نظرة مستقبلية) — السمات من الشمعة i، والعائد من فتح i+1 حتى إغلاق i+N.
  • الكلفة محسومة: سبريد ذهاب-إياب 0.24$ يُخصم من كل صفقة افتراضية.
  • walk-forward: 6 طيّات زمنية متتالية — القاعدة تنجو فقط إن ربحت في ≥5/6 طيّات.
  • تصحيح التوافيق المتعددة: عتبة t المجمّعة ≥ 3.0 (لا 2.0) + ≥150 إشارة + فحص Bonferroni تقريبي.
النتيجة تُكتب إلى data/r_native/indicator_lab_result.json + سطر للموجز الليلي.
"""
import os, sys, json, time, itertools
import numpy as np

_BASE = r"C:\Users\Radhi\MT5"
_RN = os.path.join(_BASE, "data", "r_native")
_LOG = open(os.path.join(_RN, "indicator_lab.out.log"), "a", buffering=1, encoding="utf-8")
sys.stdout = _LOG; sys.stderr = _LOG

import MetaTrader5 as mt5

SYM = "XAUUSDm"
SPREAD_COST = 0.24          # $ ذهاب-إياب لكل 0.01 لوت (مقاس من طرفيتنا)
HORIZONS = (5, 15, 30)      # دقائق أمامية للحكم
MIN_SIGNALS = 150
MIN_FOLD_WINS = 5           # من 6
T_POOLED = 3.0
OUT = os.path.join(_RN, "indicator_lab_result.json")


def ema(a, n):
    k = 2.0 / (n + 1)
    e = np.empty_like(a); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = e[i - 1] + k * (a[i] - e[i - 1])
    return e


def atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    if len(tr) >= n:
        cs = np.convolve(tr, np.ones(n) / n, mode="valid")
        out[n:] = cs
    return out


def stoch_k(h, l, c, n=14, smooth=3):
    out = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        hh = h[i - n + 1:i + 1].max(); ll = l[i - n + 1:i + 1].min()
        out[i] = 100.0 * (c[i] - ll) / max(hh - ll, 1e-9)
    k = np.copy(out)
    for i in range(n + smooth - 2, len(c)):
        k[i] = np.nanmean(out[i - smooth + 1:i + 1])
    return k


def build_features():
    """M1 آخر 30+ يوماً: سمات سببية (شموع مغلقة) + عوائد أمامية بعد الكلفة."""
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 1, 45000)
    if r is None or len(r) < 8000:
        raise RuntimeError(f"بيانات M1 غير كافية: {0 if r is None else len(r)}")
    o = r["open"].astype(float); h = r["high"].astype(float)
    l = r["low"].astype(float); c = r["close"].astype(float)
    t = r["time"].astype(np.int64)
    n = len(c)
    e50 = ema(c, 50); e200 = ema(c, 200)
    a14 = atr(h, l, c, 14)
    k14 = stoch_k(h, l, c)
    body = c - o
    rng = np.maximum(h - l, 1e-9)
    upw = h - np.maximum(c, o)
    dnw = np.minimum(c, o) - l
    hour = ((t // 3600) % 24).astype(int)             # UTC
    F = {}
    F["dist_e50"] = (c - e50)                          # موجب=فوق المتوسط
    F["dist_e200"] = (c - e200)
    F["e50_slope"] = e50 - np.roll(e50, 3)
    F["stoch"] = k14
    F["body_atr"] = body / np.where(np.isnan(a14), np.inf, a14)
    F["rng_atr"] = rng / np.where(np.isnan(a14), np.inf, a14)
    F["upw_frac"] = upw / rng
    F["dnw_frac"] = dnw / rng
    b1 = np.roll(body, 1); b2 = np.roll(body, 2)
    F["seq3"] = np.sign(body) + np.sign(b1) + np.sign(b2)          # +3=ثلاث خضر
    F["engulf"] = np.where((np.abs(body) > np.abs(b1)) & (body * b1 < 0), np.sign(body), 0)
    F["mom15"] = c - np.roll(c, 15)
    F["day_sess"] = ((hour >= 8) & (hour < 21)).astype(float)      # جلسة النهار (حافّة الانضباط)
    # عوائد أمامية بعد الكلفة (شراء؛ البيع = السالب)
    R = {}
    for hz in HORIZONS:
        fwd = np.full(n, np.nan)
        fwd[:-hz - 1] = c[hz:-1] - o[1:n - hz]                     # من فتح التالية إلى إغلاق +hz
        R[hz] = fwd
    valid = ~np.isnan(a14)
    for k_ in F:
        F[k_] = np.where(valid, F[k_], np.nan)
    return F, R, n


# 🔭 مكتبة العتبات لكل سمة: (اسم، دالة شرط، اتجاه القاعدة المقترح +1/-1/0=كلاهما)
def threshold_menu():
    return {
        "dist_e50":  [("فوق_e50>", (0.5, 1.5, 3.0), +1), ("تحت_e50<", (-0.5, -1.5, -3.0), -1)],
        "dist_e200": [("فوق_e200>", (1.0, 4.0), +1), ("تحت_e200<", (-1.0, -4.0), -1)],
        "e50_slope": [("ميل_صاعد>", (0.15, 0.5), +1), ("ميل_هابط<", (-0.15, -0.5), -1)],
        "stoch":     [("تشبع_بيع<", (15, 25), +1), ("تشبع_شراء>", (75, 85), -1)],
        "body_atr":  [("جسم_قوي>", (0.8, 1.5), 0), ("جسم_قوي_هابط<", (-0.8, -1.5), 0)],
        "rng_atr":   [("مدى_هادئ<", (0.6,), 0), ("مدى_متفجر>", (2.0,), 0)],
        "upw_frac":  [("ذيل_علوي>", (0.55,), -1)],
        "dnw_frac":  [("ذيل_سفلي>", (0.55,), +1)],
        "seq3":      [("3خضر=", (3,), 0), ("3حمر=", (-3,), 0)],
        "engulf":    [("ابتلاع_صاعد=", (1,), +1), ("ابتلاع_هابط=", (-1,), -1)],
        "mom15":     [("زخم15_صاعد>", (2.0, 5.0), +1), ("زخم15_هابط<", (-2.0, -5.0), -1)],
        "day_sess":  [("نهار=", (1,), 0)],
    }


def conditions(F):
    """يبني كل الشروط الأولية (سمة، عتبة) كأقنعة منطقية."""
    conds = []
    for feat, specs in threshold_menu().items():
        x = F[feat]
        for name, ths, sug in specs:
            for th in ths:
                if name.endswith(">"):
                    m = x > th
                elif name.endswith("<"):
                    m = x < th
                else:
                    m = x == th
                conds.append((f"{feat}:{name}{th}", m & ~np.isnan(x), sug))
    return conds


def evaluate(mask, direction, R, folds):
    """تقييم قاعدة عبر الطيّات: (صافي مجمّع بعد الكلفة، t، عدد، انتصارات الطيات، أفضل أفق)."""
    best = None
    for hz in HORIZONS:
        r = R[hz]
        sel = mask & ~np.isnan(r)
        idx_all = np.where(sel)[0]
        if len(idx_all) < MIN_SIGNALS:
            continue
        # 🧪 إصلاح التداخل: صفقة واحدة كل hz شمعة — الإشارات المتلاصقة تعدّ الحركة نفسها مراراً وتنفخ t زوراً
        idx = []
        last = -10 ** 9
        for i in idx_all:
            if i - last >= hz:
                idx.append(i); last = i
        idx = np.asarray(idx)
        if len(idx) < max(60, MIN_SIGNALS // 3):
            continue
        pnl = direction * r[idx] - SPREAD_COST
        # الطيّات الزمنية
        fw = 0
        parts = np.array_split(idx, folds)
        ok = True
        for part in parts:
            if len(part) < 8:
                ok = False; break
            if (direction * r[part] - SPREAD_COST).mean() > 0:
                fw += 1
        if not ok:
            continue
        m = pnl.mean(); s = pnl.std(ddof=1)
        tstat = m / (s / np.sqrt(len(pnl))) if s > 1e-12 else 0.0
        cand = {"hz": hz, "n": int(len(pnl)), "mean": round(float(m), 4),
                "t": round(float(tstat), 2), "fold_wins": fw,
                "net": round(float(pnl.sum()), 2)}
        if best is None or cand["t"] > best["t"]:
            best = cand
    return best


def main():
    t0 = time.time()
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🔬 مختبر الأرقام بدأ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    F, R, n = build_features()
    conds = conditions(F)
    print(f"شموع M1: {n} · شروط أولية: {len(conds)}")
    rules = []
    # المستوى 1: شروط مفردة | المستوى 2: كل الأزواج | المستوى 3: ثلاثيات مقيّدة بجلسة النهار
    singles = [(c1[0], c1[1], d) for c1 in conds for d in ((+1, -1) if c1[2] == 0 else (c1[2],))]
    for name, m, d in singles:
        rules.append((name, m, d))
    for (n1, m1, s1), (n2, m2, s2) in itertools.combinations(conds, 2):
        dirs = set()
        for s in (s1, s2):
            if s != 0:
                dirs.add(s)
        use_dirs = dirs if len(dirs) == 1 else {+1, -1}
        mm = m1 & m2
        for d in use_dirs:
            rules.append((f"{n1} & {n2}", mm, d))
    day = F["day_sess"] == 1
    for (n1, m1, s1), (n2, m2, s2) in itertools.combinations(conds, 2):
        if s1 == 0 and s2 == 0:
            continue
        d = s1 if s1 != 0 else s2
        rules.append((f"نهار & {n1} & {n2}", m1 & m2 & day, d))
    total = len(rules)
    print(f"إجمالي القواعد المُختبرة: {total} (بونفيروني التقريبي: t≥{T_POOLED} يعادل p~{0.0013 * total:.2f} متوقَّعاً بالصدفة)")
    survivors = []
    checked = 0
    for name, m, d in rules:
        checked += 1
        if checked % 2000 == 0:
            print(f"  ... {checked}/{total} ({time.time()-t0:.0f}ث) · ناجون حتى الآن: {len(survivors)}")
        if int(m.sum()) < MIN_SIGNALS:
            continue
        best = evaluate(m, d, R, 6)
        if best and best["t"] >= T_POOLED and best["fold_wins"] >= MIN_FOLD_WINS:
            survivors.append({"rule": name, "dir": ("شراء" if d == 1 else "بيع"), **best})
    survivors.sort(key=lambda x: -x["t"])
    # الصدفة المتوقَّعة: بهذه العتبة نتوقع ~0.1% × عدد القواعد ناجين زائفين
    expected_false = round(0.0013 * total, 1)
    verdict = ("🏆 ناجون حقيقيون محتملون — يستحقون اختبار paper فوريّ"
               if len(survivors) > expected_false * 3 else
               ("⚠️ الناجون ≈ ضجيج التوافيق المتوقَّع — لا حافّة أرقام"
                if survivors else "❌ صفر ناجين — الأرقام وحدها لا تربح بعد الكلفة (المتوقَّع علمياً)"))
    out = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "bars_m1": n, "rules_tested": total, "min_signals": MIN_SIGNALS,
           "t_threshold": T_POOLED, "folds": "6 (فوز ≥5)", "cost_usd": SPREAD_COST,
           "expected_false_survivors": expected_false,
           "survivors": survivors[:40], "n_survivors": len(survivors),
           "verdict": verdict, "runtime_s": round(time.time() - t0, 1)}
    tmp = OUT + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    # سطر للجوّال عبر قناة الإنذارات
    try:
        with open(os.path.join(_RN, "news_alarm_feed.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                "kind": "LAB", "impact": "Info", "currency": "ALL",
                                "title": f"🔬 مختبر الأرقام انتهى: {total} قاعدة، ناجون {len(survivors)} "
                                         f"(صدفة متوقَّعة ~{expected_false}) — {verdict}"},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"🏁 {verdict} · ناجون {len(survivors)}/{total} · {out['runtime_s']}ث")
    mt5.shutdown()


if __name__ == "__main__":
    main()
