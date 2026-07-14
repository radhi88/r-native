"""smc_plan_chart.py — «كيف يرسم النظام الصفقة»: خطة دخول/وقف/هدف حيّة على إعداد SMC الرابح.

يأخذ أحدث Order Block طازج (غير مُخفّف) في اتجاه الحافة المثبتة، ويرسم بالضبط ما سينفّذه النظام:
منطقة الدخول (OB) · سعر الدخول (حافة الزون المحافظة) · الوقف الهيكلي (خلف الزون) · الهدف 3R (الطريقة
المثبتة OOS) · مع POC والسيولة للسياق و نسبة المخاطرة/العائد. نفس منطق cot_ob_backtest الرابح.

Run: .venv\\Scripts\\python.exe smc_plan_chart.py [SYMBOL] [TF] [side]   (افتراضي XAUUSDm M5 long)
"""
from __future__ import annotations
import sys
from pathlib import Path
_MT5 = Path(__file__).resolve().parent
for p in (str(_MT5), str(_MT5 / "r_native_v2" / "runtime" / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import MetaTrader5 as mt5
import order_blocks as ob

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
BG = "#0b1020"; GRID = "#1a2540"; UP = "#26a69a"; DN = "#ef5350"
C_ZONE = "#26a69a"; C_SL = "#ef5350"; C_TP = "#ffd54f"; C_ENT = "#42a5f5"; C_LIQ = "#d4a017"


def _atr(h, l, c, n=14):
    p = np.empty(len(c)); p[0] = c[0]; p[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - p), np.abs(l - p)))
    cs = np.cumsum(tr); a = np.full(len(c), np.nan)
    if len(c) >= n:
        a[n - 1:] = (cs[n - 1:] - np.concatenate(([0.0], cs[:-n]))) / n
    return a


def render(symbol="XAUUSDm", tf="M5", side="long", bars=120, rr=3.0):
    if not mt5.initialize() and not mt5.initialize():
        print("init failed"); return None
    rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M5), 0, bars)
    info = mt5.symbol_info(symbol); mt5.shutdown()
    if rates is None or len(rates) < 40:
        print("no data"); return None
    o = rates["open"]; h = rates["high"]; l = rates["low"]; c = rates["close"]; n = len(c)
    dig = info.digits if info else 2
    atr = _atr(h, l, c)
    want = "demand" if side == "long" else "supply"
    zones = [z for z in ob.detect_order_blocks(rates, swing=5) if z["type"] == want]
    pools = ob.liquidity_pools(rates, swing=5)
    # أحدث زون طازج (غير مُخفّف) — هو المنطقة القابلة للتداول؛ وإلا أحدث زون
    fresh = [z for z in zones if not z.get("mitigated")]
    z = (fresh or zones)[-1] if (fresh or zones) else None

    fig, ax = plt.subplots(figsize=(15, 8.4), dpi=115)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_color(GRID)
    ax.tick_params(colors="#9fb0d0", labelsize=8); ax.grid(True, color=GRID, lw=0.5, alpha=0.4)
    w = 0.38
    for i in range(n):
        col = UP if c[i] >= o[i] else DN
        ax.plot([i, i], [l[i], h[i]], color=col, lw=0.7, zorder=3)
        ax.add_patch(Rectangle((i - w, min(o[i], c[i])), 2 * w, abs(c[i] - o[i]) or (h[i] - l[i]) * 0.02, facecolor=col, edgecolor=col, lw=0.5, zorder=4))
    for p in pools[-5:]:
        ax.axhline(p["price"], color=C_LIQ, lw=0.9, ls="--", alpha=0.55, zorder=2)
        ax.text(0, p["price"], f" $$$ {'EQH' if p['type']=='equal_highs' else 'EQL'}", color=C_LIQ, fontsize=7, va="bottom", zorder=6)

    title = f"{symbol} {tf} — خطة الصفقة (لا توجد منطقة نشطة)"
    if z is not None:
        x0 = z.get("ob_bar", z["idx"]); a = atr[z["idx"]] if np.isfinite(atr[z["idx"]]) else (z["hi"] - z["lo"])
        buf = 0.25 * a
        if side == "long":
            entry = z["hi"]; sl = z["lo"] - buf; tp = entry + rr * abs(entry - sl)
        else:
            entry = z["lo"]; sl = z["hi"] + buf; tp = entry - rr * abs(entry - sl)
        risk = abs(entry - sl); reward = abs(tp - entry)
        # منطقة الدخول (OB)
        ax.add_patch(Rectangle((x0, z["lo"]), (n - 1 + 6) - x0, z["hi"] - z["lo"], facecolor=C_ZONE, edgecolor=C_ZONE, alpha=0.18, zorder=2))
        ax.text(x0, z["hi"], f" منطقة الشراء (Demand OB)" if side == "long" else " منطقة البيع (Supply OB)", color=C_ZONE, fontsize=8, va="bottom", zorder=6)
        # خطوط دخول/وقف/هدف
        for price, col, lab in ((entry, C_ENT, f"دخول {entry:.{dig}f}"), (sl, C_SL, f"وقف SL {sl:.{dig}f}  (−1R)"),
                                (tp, C_TP, f"هدف TP {tp:.{dig}f}  (+{rr:.0f}R)")):
            ax.axhline(price, color=col, lw=1.4, ls="-", alpha=0.9, zorder=5)
            ax.text(n + 6, price, f" {lab}", color=col, fontsize=8.5, va="center", ha="left", fontweight="bold", zorder=7)
        # تظليل المخاطرة (أحمر) والعائد (أخضر)
        ax.add_patch(Rectangle((n - 1, min(entry, sl)), 6, risk, facecolor=C_SL, alpha=0.12, zorder=1))
        ax.add_patch(Rectangle((n - 1, min(entry, tp)), 6, reward, facecolor=C_TP, alpha=0.12, zorder=1))
        state = "نشطة (طازجة)" if not z.get("mitigated") else "مُخفّفة (انتظار إعادة اختبار)"
        title = (f"{symbol} {tf} — خطة {'شراء' if side=='long' else 'بيع'} عند {want.upper()} OB  ·  "
                 f"دخول {entry:.{dig}f} · وقف {sl:.{dig}f} · هدف 3R {tp:.{dig}f}  ·  RR 1:{reward/risk:.0f}  ·  {state}   "
                 f"[الحافة المثبتة OOS PF 2.27]")
    ax.set_title(title, color="#fff", fontsize=10)
    ax.set_xlim(-1, n + 16); ax.margins(y=0.06)
    out = _MT5 / f"smc_plan_{symbol}_{tf}_{side}.png"
    fig.tight_layout(); fig.savefig(out, facecolor=BG); plt.close(fig)
    print(f"plan -> {out}")
    return str(out)


if __name__ == "__main__":
    a = sys.argv
    render(a[1] if len(a) > 1 else "XAUUSDm", a[2] if len(a) > 2 else "M5", a[3] if len(a) > 3 else "long")
