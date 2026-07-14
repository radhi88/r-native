"""smc_chart.py — اختبار بصري احترافي: بنى SMC الحقيقية + Volume Profile/POC على شارت حقيقي.

يستخدم نفس الكاشف الصارم الذي يستهلكه النظام (order_blocks.py، بلا lookahead) + يضيف
Volume Profile (حجم-بالسعر) وPOC ومنطقة القيمة — كما تُرسم الشارتات الاحترافية (المرجع: لوحات
SMC على TradingView). كل منطقة مرسومة هي ما يكتشفه الكود فعلاً.

Run:  .venv\\Scripts\\python.exe smc_chart.py [SYMBOL] [TF] [BARS]
"""
from __future__ import annotations
import sys
from pathlib import Path

_MT5 = Path(__file__).resolve().parent
for p in (str(_MT5), str(_MT5 / "r_native_v2" / "runtime" / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from matplotlib.lines import Line2D
import MetaTrader5 as mt5
import order_blocks as ob

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}

BG = "#0b1020"; GRID = "#1a2540"; UP = "#26a69a"; DN = "#ef5350"
C_DEMAND = "#26a69a"; C_SUPPLY = "#ef5350"; C_FVGB = "#42a5f5"; C_FVGS = "#ffa726"
C_LIQ = "#d4a017"; C_POC = "#ffd54f"; C_VA = "#5c6bc0"


def _volume_profile(h, l, vol, lo, hi, bins=70):
    """حجم-بالسعر: نوزّع حجم كل شمعة على السلال التي يغطّيها مداها. يرجع (مراكز، أحجام، POC، VA)."""
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    prof = np.zeros(bins)
    for i in range(len(vol)):
        b0 = np.searchsorted(edges, l[i]) - 1
        b1 = np.searchsorted(edges, h[i]) - 1
        b0 = max(0, min(bins - 1, b0)); b1 = max(0, min(bins - 1, b1))
        span = b1 - b0 + 1
        if span > 0:
            prof[b0:b1 + 1] += vol[i] / span
    poc_i = int(np.argmax(prof))
    # value area = أصغر مجموعة سلال حول POC تضمّ 70% من الحجم
    order = np.argsort(prof)[::-1]
    cum = 0.0; tot = prof.sum() or 1.0; sel = set()
    for bi in order:
        sel.add(int(bi)); cum += prof[bi]
        if cum >= 0.70 * tot:
            break
    va = [centers[i] for i in sel]
    return centers, prof, centers[poc_i], (min(va), max(va))


def render(symbol="XAUUSDm", tf="M15", bars=160):
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return None
    rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) < 30:
        print("no data"); return None
    o = rates["open"]; h = rates["high"]; l = rates["low"]; c = rates["close"]; v = rates["tick_volume"].astype(float)
    n = len(c)

    obs = ob.detect_order_blocks(rates, swing=5)
    fvgs = ob.detect_fvg(rates)
    pools = ob.liquidity_pools(rates, swing=5)
    centers, prof, poc, (va_lo, va_hi) = _volume_profile(h, l, v, float(l.min()), float(h.max()))

    fig, ax = plt.subplots(figsize=(16, 8.6), dpi=115)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors="#9fb0d0", labelsize=8)
    ax.grid(True, color=GRID, lw=0.5, alpha=0.45)

    PW = int(n * 0.20)            # عرض منطقة الـvolume-profile (سلال) على اليمين
    x_right = n + PW + 4

    # value-area shading (خلف كل شيء)
    ax.axhspan(va_lo, va_hi, color=C_VA, alpha=0.07, zorder=0)

    # شموع
    w = 0.38
    for i in range(n):
        col = UP if c[i] >= o[i] else DN
        ax.plot([i, i], [l[i], h[i]], color=col, lw=0.7, zorder=3)
        ax.add_patch(Rectangle((i - w, min(o[i], c[i])), 2 * w, abs(c[i] - o[i]) or (h[i] - l[i]) * 0.02,
                               facecolor=col, edgecolor=col, lw=0.5, zorder=4))

    def box(z, color, label, alpha):
        x = z.get("ob_bar", z.get("idx", 0)); mit = z.get("mitigated")
        a = alpha * (0.3 if mit else 1.0)
        ax.add_patch(Rectangle((x, z["lo"]), (n - 1) - x, z["hi"] - z["lo"],
                               facecolor=color, edgecolor=color, lw=1.0, alpha=a, zorder=2))
        ax.text(n - 1, (z["hi"] + z["lo"]) / 2, label + (" (mit)" if mit else "") + " ",
                color=color, fontsize=7, va="center", ha="right", zorder=6, alpha=0.5 if mit else 0.95)

    for z in [z for z in obs if z["type"] == "demand"][-3:]:
        box(z, C_DEMAND, "Demand OB", 0.16)
    for z in [z for z in obs if z["type"] == "supply"][-3:]:
        box(z, C_SUPPLY, "Supply OB", 0.16)
    for z in [z for z in fvgs if z["type"] == "bullish"][-3:]:
        box(z, C_FVGB, "FVG↑", 0.13)
    for z in [z for z in fvgs if z["type"] == "bearish"][-3:]:
        box(z, C_FVGS, "FVG↓", 0.13)
    for p in pools[-6:]:
        kind = "EQH" if p["type"] == "equal_highs" else "EQL"
        ax.plot([0, n - 1], [p["price"], p["price"]], color=C_LIQ, lw=1.0, ls="--", alpha=0.65, zorder=2)
        ax.text(0, p["price"], f"$$$ {kind} x{p['touches']} ", color=C_LIQ, fontsize=7, va="bottom", ha="left", zorder=6)

    # ---- Volume Profile على اليمين (حجم-بالسعر) ----
    bh = (centers[1] - centers[0]) * 0.9 if len(centers) > 1 else 1.0
    pmax = prof.max() or 1.0
    for i, cy in enumerate(centers):
        bw = (prof[i] / pmax) * PW
        in_va = va_lo <= cy <= va_hi
        col = C_VA if in_va else "#33405e"
        ax.add_patch(Rectangle((n + 2, cy - bh / 2), bw, bh, facecolor=col, edgecolor="none", alpha=0.55, zorder=1))
    # POC line (مغناطيس المؤسسات)
    ax.plot([0, x_right], [poc, poc], color=C_POC, lw=1.4, ls="-", alpha=0.9, zorder=5)
    ax.text(x_right, poc, f" POC {poc:.2f}", color=C_POC, fontsize=8, va="center", ha="left", zorder=6, fontweight="bold")

    nd = sum(1 for z in obs if z["type"] == "demand"); ns = len(obs) - nd
    fresh = sum(1 for z in obs + fvgs if not z.get("mitigated"))
    ax.set_title(f"SMC PRO  ·  {symbol} {tf}  ·  {n} bars   |   OB {nd}D/{ns}S  ·  FVG {len(fvgs)}  ·  "
                 f"liquidity {len(pools)}  ·  fresh {fresh}  ·  POC {poc:.2f}   [strictly causal · no look-ahead]",
                 color="#fff", fontsize=10.5)
    legend = [Patch(facecolor=C_DEMAND, alpha=.5, label="Demand OB (buy zone)"),
              Patch(facecolor=C_SUPPLY, alpha=.5, label="Supply OB (sell zone)"),
              Patch(facecolor=C_FVGB, alpha=.5, label="FVG bull"), Patch(facecolor=C_FVGS, alpha=.5, label="FVG bear"),
              Line2D([], [], color=C_LIQ, ls="--", label="$$$ liquidity (equal H/L)"),
              Line2D([], [], color=C_POC, lw=1.4, label="POC (volume magnet)"),
              Patch(facecolor=C_VA, alpha=.3, label="Value area (70% vol)")]
    ax.legend(handles=legend, loc="upper left", fontsize=7.5, facecolor="#0d1530", edgecolor=GRID, labelcolor="#cdd6e4")
    ax.set_xlim(-1, x_right + n * 0.04); ax.margins(y=0.05)
    out = _MT5 / f"smc_chart_{symbol}_{tf}.png"
    fig.tight_layout(); fig.savefig(out, facecolor=BG); plt.close(fig)
    print(f"OB={len(obs)} FVG={len(fvgs)} pools={len(pools)} POC={poc:.2f} -> {out}")
    return str(out)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M15"
    bars = int(sys.argv[3]) if len(sys.argv) > 3 else 160
    render(sym, tf, bars)
