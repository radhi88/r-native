"""smc_bt_chart.py — ارسم نتائج الباكتست: مناطق OB + نقاط الدخول الفعلية (فوز/خسارة) على الشارت.

يستدعي نفس محرّك الباكتست (cot_ob_backtest.simulate) ويرسم كل صفقة: دخول ▲/▼ (أخضر فوز/أحمر خسارة)،
منطقة OB، وخط OOS. هذا «صورة الشارت وفيه مناطق الدخول على باكتست» المطلوبة.

Run: .venv\\Scripts\\python.exe smc_bt_chart.py XAUUSDm M5 long 3R
"""
from __future__ import annotations
import sys
from pathlib import Path
_MT5 = Path(__file__).resolve().parent
for p in (str(_MT5), str(_MT5/"r_native_v2"/"runtime"), str(_MT5/"r_native_v2"/"runtime"/"shared")):
    if p not in sys.path: sys.path.insert(0, p)
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from smc_lab import load_bars
from cot_ob_backtest import simulate, split_metrics
import order_blocks as ob

BG="#0b1020"; GRID="#16213c"; UP="#2ea043"; DN="#ff5b52"; WIN="#19c37d"; LOSS="#ff5b52"; OBC="#3a7d44"


def render(symbol="XAUUSDm", tf="M5", side="long", tp="3R"):
    rates = load_bars(symbol, tf)
    if rates is None or len(rates) < 400:
        print("no data"); return None
    o=rates["open"]; h=rates["high"]; l=rates["low"]; c=rates["close"]; n=len(c)
    trades = simulate(rates, symbol, side, tp, gate_fn=None)
    oos = split_metrics(trades)["OOS"]
    split_idx = int(n*0.67)
    zones=[z for z in ob.detect_order_blocks(rates, swing=5) if z["type"]==("demand" if side=="long" else "supply")]

    # نعرض آخر ~260 شمعة لوضوح السكالب
    x0 = max(0, n-260)
    fig, ax = plt.subplots(figsize=(16, 8.4), dpi=110)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_color(GRID)
    ax.tick_params(colors="#9fb0d0", labelsize=8); ax.grid(True, color=GRID, lw=0.5, alpha=0.4)
    w=0.4
    for i in range(x0, n):
        col = UP if c[i]>=o[i] else DN
        ax.plot([i,i],[l[i],h[i]], color=col, lw=0.6, zorder=2)
        ax.add_patch(Rectangle((i-w, min(o[i],c[i])), 2*w, abs(c[i]-o[i]) or (h[i]-l[i])*0.02, facecolor=col, edgecolor=col, lw=0.4, zorder=3))
    # OB zones (الأحدث فقط، غير المُخفّفة أوضح)
    for z in zones[-14:]:
        xz=max(z.get("ob_bar",z["idx"]), x0)
        ax.add_patch(Rectangle((xz, z["lo"]), (n-1)-xz, z["hi"]-z["lo"], facecolor=OBC, edgecolor=OBC, alpha=0.13, zorder=1))
    # backtest entries
    for t in trades:
        eb=t["entry_bar"]
        if eb < x0: continue
        win = t["net"]>0
        mark = "^" if side=="long" else "v"
        ax.scatter([eb],[t["entry"]], marker=mark, s=90, color=(WIN if win else LOSS), edgecolors="#fff", linewidths=0.6, zorder=6)
        # خط دخول→خروج خفيف
        ax.plot([eb, t["exit_bar"]], [t["entry"], t["entry"]], color=(WIN if win else LOSS), lw=0.5, alpha=0.5, zorder=4)
    # OOS divider
    if split_idx > x0:
        ax.axvline(split_idx, color="#d4a017", lw=1.2, ls=":", zorder=5)
        ax.text(split_idx, h[x0:].max(), " OOS →", color="#d4a017", fontsize=9, va="top")
    al=split_metrics(trades)["ALL"]
    ax.set_title(f"BACKTEST  {symbol} {tf} {side} @ OB, TP={tp}  |  ALL: {al['trades']}tr PF {al['profit_factor']}  "
                 f"||  OOS: {oos['trades']}tr  WR {oos['oos_wr'] if 'oos_wr' in oos else oos['win_rate']}%  PF {oos['profit_factor']}  net ${oos['net']:.0f}"
                 f"   [no look-ahead · net of spread]", color="#fff", fontsize=10.5)
    ax.set_xlim(x0-1, n+4); ax.margins(y=0.04)
    out=_MT5/f"smc_bt_{symbol}_{tf}_{side}_{tp}.png"
    fig.tight_layout(); fig.savefig(out, facecolor=BG); plt.close(fig)
    print(f"trades={len(trades)} OOS_PF={oos['profit_factor']} -> {out}")
    return str(out)


if __name__ == "__main__":
    a=sys.argv
    render(a[1] if len(a)>1 else "XAUUSDm", a[2] if len(a)>2 else "M5",
           a[3] if len(a)>3 else "long", a[4] if len(a)>4 else "3R")
