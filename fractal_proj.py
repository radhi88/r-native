"""fractal_proj.py — إسقاط فراكتالي/أنالوج صادق: يجد أشبه الحركات السابقة ويعرض ما حصل بعدها كمروحة.

⚠️ صدق علمي (مثبت سابقاً OOS): الأنالوج لا يتنبّأ بالاتجاه (~50-53% = عملة، path-corr~0).
لذا هذا «سياق فقط»: يعرض الحركات المشابهة وما تلاها — الإشارة الحقيقية هي التشتّت/المدى (عدم اليقين)،
لا اتجاه مؤكّد. لا تتداول عليه كإشارة اتجاه. (بلا lookahead: نقارن نافذة حالية بنوافذ ماضية منتهية.)

Run: .venv\\Scripts\\python.exe fractal_proj.py [SYMBOL] [TF] [L_query] [H_proj] [K]
"""
from __future__ import annotations
import sys
from pathlib import Path
_MT5 = Path(__file__).resolve().parent
sys.path.insert(0, str(_MT5))
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import MetaTrader5 as mt5

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
BG = "#0b1020"; GRID = "#1a2540"; UP = "#26a69a"; DN = "#ef5350"


def render(symbol="XAUUSDm", tf="M15", L=24, H=16, K=6, hist=2000):
    if not mt5.initialize() and not mt5.initialize():
        print("init failed"); return None
    r = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, hist)
    mt5.shutdown()
    if r is None or len(r) < L + H + 200:
        print("no data"); return None
    c = np.array([x["close"] for x in r], float); o = np.array([x["open"] for x in r], float)
    hi = np.array([x["high"] for x in r], float); lo = np.array([x["low"] for x in r], float)
    n = len(c)
    cur_price = c[-1]
    # نافذة الاستعلام = آخر L إغلاق، مُطبَّعة (% من بداية النافذة) لمقارنة الشكل
    q = c[-L:]; qn = (q - q[0]) / (q[0] + 1e-9)
    # ابحث في الماضي: كل نافذة [i-L, i] لها مستقبل [i, i+H]؛ i لا يتداخل مع الاستعلام
    cands = []
    for i in range(L, n - H - L):       # i = نهاية نافذة مرشّحة (ولها H مستقبل)
        w = c[i - L:i]; wn = (w - w[0]) / (w[0] + 1e-9)
        # تشابه الشكل = ارتباط بيرسون على المسار المُطبَّع
        if wn.std() < 1e-9:
            continue
        corr = float(np.corrcoef(qn, wn)[0, 1])
        cands.append((corr, i))
    cands.sort(key=lambda x: -x[0])
    top = cands[:K]
    # المسارات الأمامية لكل مرشّح، مُعاد توجيهها لتبدأ من السعر الحالي
    paths = []
    for corr, i in top:
        fut = c[i:i + H + 1]
        if len(fut) < H + 1:
            continue
        rel = fut / fut[0]              # تطوّر نسبي
        proj = cur_price * rel          # مُسقَط من السعر الحالي
        paths.append((corr, proj))
    if not paths:
        print("no analogs"); return None
    arr = np.array([p for _, p in paths])
    median = np.median(arr, axis=0); lo_env = arr.min(axis=0); hi_env = arr.max(axis=0)
    ups = sum(1 for _, p in paths if p[-1] > cur_price); downs = len(paths) - ups
    med_ret = (median[-1] - cur_price) / cur_price * 100

    # رسم: آخر ~80 شمعة + المروحة المُسقطة
    show = 80; x0 = n - show
    fig, ax = plt.subplots(figsize=(15, 8), dpi=115)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_color(GRID)
    ax.tick_params(colors="#9fb0d0", labelsize=8); ax.grid(True, color=GRID, lw=0.4, alpha=0.35)
    w = 0.4
    for j in range(x0, n):
        col = UP if c[j] >= o[j] else DN; xx = j - x0
        ax.plot([xx, xx], [lo[j], hi[j]], color=col, lw=0.7, zorder=3)
        ax.add_patch(Rectangle((xx - w, min(o[j], c[j])), 2 * w, abs(c[j] - o[j]) or (hi[j] - lo[j]) * 0.02, facecolor=col, edgecolor=col, lw=0.5, zorder=4))
    nx = show - 1  # موضع الآن
    fx = np.arange(nx, nx + H + 1)
    ax.axvline(nx, color="#90a4ae", lw=1.0, ls=":", alpha=0.7)
    ax.fill_between(fx, lo_env, hi_env, color="#5c6bc0", alpha=0.15, zorder=1, label="مدى الأنالوج (تشتّت=عدم يقين)")
    for corr, p in paths:
        ax.plot(fx, p, color="#7e8aa8", lw=0.8, alpha=0.6, zorder=2)
    ax.plot(fx, median, color="#ffd54f", lw=2.0, zorder=5, label="المسار الوسيط (سياق لا تنبّؤ)")
    ax.scatter([nx], [cur_price], color="#fff", s=30, zorder=6)
    disp = (hi_env[-1] - lo_env[-1]) / cur_price * 100
    ax.set_title(f"Fractal/Analog — {symbol} {tf}  ·  أشبه {len(paths)} حركات سابقة  ·  بعد {H} شمعة: "
                 f"{ups}↑/{downs}↓ · وسيط {med_ret:+.2f}% · تشتّت {disp:.2f}%   "
                 f"⚠️ سياق فقط — غير تنبّؤي بالاتجاه (~50% OOS)", color="#fff", fontsize=9.5)
    ax.legend(loc="upper left", fontsize=8, facecolor="#0d1530", edgecolor=GRID, labelcolor="#cdd6e4")
    ax.margins(y=0.06)
    out = _MT5 / f"fractal_proj_{symbol}_{tf}.png"
    fig.tight_layout(); fig.savefig(out, facecolor=BG); plt.close(fig)
    print(f"analogs={len(paths)} {ups}up/{downs}down median={med_ret:+.2f}% disp={disp:.2f}% -> {out}")
    return str(out), ups, downs, med_ret, disp


if __name__ == "__main__":
    a = sys.argv
    render(a[1] if len(a) > 1 else "XAUUSDm", a[2] if len(a) > 2 else "M15",
           int(a[3]) if len(a) > 3 else 24, int(a[4]) if len(a) > 4 else 16, int(a[5]) if len(a) > 5 else 6)
