"""pendulum_test.py — اختبار «معادلة البندول» من فيديو الفراكتال بصدق علمي OOS بلا lookahead.

ادعاء الفيديو (توقيت لا اتجاه): طول الساق (عدد الشموع بين قمة وقاع) × 1.618 = عدد الشموع
للانعكاس القادم. نختبره كفرضية توقيت بحتة:

  لكل ساق مكتمل من محور A (شمعة a) إلى محور B (شمعة b):  L = b - a
  الادعاء: المحور التالي C يقع عند  b + round(L × φ)  حيث φ=1.618
  إصابة = |c_فعلي - c_متوقّع| ≤ tol  (tol = 2 أو 3 شموع)

المحاور تُكتشف بنافذة fractal (محور مؤكَّد بعد w شمعة فقط = بلا lookahead).
نقارن φ=1.618 ضد: (أ) أفضل مضاعِف داخل العيّنة IS (سقف متفائل)، (ب) مضاعِف 1.0 (تماثل ساذج)،
(ج) خط أساس عشوائي. القرار = هل φ يتفوّق على العشوائي إحصائياً (binomial)؟ نتوقّع الفشل لكنه قابل للدحض.

Run: .venv\\Scripts\\python.exe pendulum_test.py [SYMBOL] [TF] [WINDOW] [TOL]
"""
from __future__ import annotations
import sys
from pathlib import Path
_MT5 = Path(__file__).resolve().parent
sys.path.insert(0, str(_MT5))
import numpy as np
import MetaTrader5 as mt5

PHI = 1.618
_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1}


def _pivots(hi, lo, w):
    """محاور fractal بلا lookahead: قمة عند i لو high[i] = أعلى قيمة في [i-w, i+w]؛
    تُؤكَّد عملياً عند i+w. نُرجع قائمة (idx, kind) بالتناوب H/L مع دمج التتالي نفس النوع."""
    n = len(hi)
    piv = []
    for i in range(w, n - w):
        win_h = hi[i - w:i + w + 1]; win_l = lo[i - w:i + w + 1]
        is_h = hi[i] == win_h.max() and hi[i] > hi[i - 1]  # قمة محلية
        is_l = lo[i] == win_l.min() and lo[i] < lo[i - 1]   # قاع محلي
        if is_h and not is_l:
            piv.append((i, "H", hi[i]))
        elif is_l and not is_h:
            piv.append((i, "L", lo[i]))
    # فرض التناوب H,L,H,L: عند تتالي نفس النوع، أبقِ الأكثر تطرّفاً
    clean = []
    for p in piv:
        if clean and clean[-1][1] == p[1]:
            if (p[1] == "H" and p[2] > clean[-1][2]) or (p[1] == "L" and p[2] < clean[-1][2]):
                clean[-1] = p
        else:
            clean.append(p)
    return clean


def run(symbol="XAUUSDm", tf="M15", w=5, tol=3, hist=20000):
    ok = mt5.initialize() or mt5.initialize()
    if not ok:
        print("init failed", mt5.last_error()); return None
    r = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, hist)
    mt5.shutdown()
    if r is None or len(r) < 1000:
        print("no data"); return None
    hi = np.array([x["high"] for x in r], float)
    lo = np.array([x["low"] for x in r], float)
    piv = _pivots(hi, lo, w)
    if len(piv) < 30:
        print(f"too few pivots ({len(piv)})"); return None

    # ساق = من محور i إلى i+1؛ المحور التالي i+2 هو الانعكاس المتوقَّع
    legs = []  # (L = طول الساق, gap = شموع من B إلى C, ratio = gap/L)
    for k in range(len(piv) - 2):
        a = piv[k][0]; b = piv[k + 1][0]; c = piv[k + 2][0]
        L = b - a; gap = c - b
        if L >= 2 and gap >= 1:
            legs.append((L, gap, gap / L))
    if len(legs) < 25:
        print(f"too few legs ({len(legs)})"); return None
    legs = np.array(legs)
    Ls = legs[:, 0]; gaps = legs[:, 1]; ratios = legs[:, 2]
    n = len(legs)

    # تقسيم IS/OOS (67/33) زمنياً
    cut = int(n * 0.67)
    is_r = ratios[:cut]; oos_L = Ls[cut:]; oos_gap = gaps[cut:]
    best_mult_is = float(np.median(is_r))  # أفضل تخمين داخل العيّنة (سقف متفائل)

    def hit_rate(mult, Larr, garr):
        pred = np.round(Larr * mult)
        return float(np.mean(np.abs(garr - pred) <= tol)), pred

    hr_phi, _ = hit_rate(PHI, oos_L, oos_gap)
    hr_is, _ = hit_rate(best_mult_is, oos_L, oos_gap)
    hr_one, _ = hit_rate(1.0, oos_L, oos_gap)

    # خط أساس عشوائي: تنبؤ بفجوة عشوائية من توزيع الفجوات الفعلي (IS) — متوسط عبر 200 سحبة
    rng = np.random.default_rng(42)
    is_gaps = gaps[:cut]
    rand_hits = []
    for _ in range(200):
        rand_pred = rng.choice(is_gaps, size=len(oos_gap))
        rand_hits.append(np.mean(np.abs(oos_gap - rand_pred) <= tol))
    hr_rand = float(np.mean(rand_hits)); hr_rand_sd = float(np.std(rand_hits))

    # binomial: هل φ يتفوّق على العشوائي؟ z-score تقريبي
    no = len(oos_gap)
    k_phi = int(round(hr_phi * no))
    p0 = max(hr_rand, 1e-6)
    se = (p0 * (1 - p0) / no) ** 0.5
    z = (hr_phi - p0) / se if se > 0 else 0.0

    # توزيع النِسَب الفعلية: هل يتجمّع حول 1.618؟
    med_ratio = float(np.median(ratios)); mean_ratio = float(np.mean(ratios))
    frac_near_phi = float(np.mean(np.abs(ratios - PHI) <= 0.25))  # ضمن ±0.25 من φ

    print(f"\n=== PENDULUM TEST — {symbol} {tf}  (w={w}, tol=±{tol})  ===")
    print(f"محاور={len(piv)}  سيقان={n}  (IS={cut} / OOS={no})")
    print(f"نِسَب gap/L الفعلية:  وسيط={med_ratio:.2f}  متوسط={mean_ratio:.2f}  "
          f"(الادعاء φ={PHI})  ضمن±0.25 من φ: {frac_near_phi*100:.0f}%")
    print(f"\nمعدّل الإصابة OOS (الانعكاس ضمن ±{tol} شمعة من المتوقَّع):")
    print(f"  φ=1.618 (الادعاء):       {hr_phi*100:5.1f}%")
    print(f"  أفضل مضاعِف IS={best_mult_is:.2f} (سقف): {hr_is*100:5.1f}%")
    print(f"  مضاعِف 1.0 (تماثل):       {hr_one*100:5.1f}%")
    print(f"  عشوائي (خط أساس):        {hr_rand*100:5.1f}% ± {hr_rand_sd*100:.1f}%")
    print(f"\nهل φ يتفوّق على العشوائي؟  z = {z:+.2f}  "
          f"({'✅ دالّ (z>1.96)' if z > 1.96 else '✗ غير دالّ — لا حافّة توقيت'})")
    verdict = "EDGE" if z > 1.96 and hr_phi > hr_rand else "NO-EDGE"
    print(f"\nالحكم: {verdict}")
    return {"symbol": symbol, "tf": tf, "n_legs": n, "med_ratio": med_ratio,
            "frac_near_phi": frac_near_phi, "hr_phi": hr_phi, "hr_rand": hr_rand,
            "hr_best_is": hr_is, "z": z, "verdict": verdict}


if __name__ == "__main__":
    a = sys.argv
    sym = a[1] if len(a) > 1 else "XAUUSDm"
    tfs = (a[2].split(",") if len(a) > 2 else ["M1", "M5", "M15", "H1"])
    w = int(a[3]) if len(a) > 3 else 5
    tol = int(a[4]) if len(a) > 4 else 3
    for tf in tfs:
        try:
            run(sym, tf, w, tol)
        except Exception as e:
            print(f"err {tf}: {e}")
