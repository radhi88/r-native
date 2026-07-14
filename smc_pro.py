"""smc_pro.py — ماركب SMC احترافي حقيقي (لا تفريغ خام): بنية السوق + BOS/CHoCH + sweeps + premium/discount.

يبني العمود الفقري لـSMC الذي كان ناقصاً:
  • بنية السوق: قمم/قيعان مؤكّدة موسومة HH/HL/LH/LL (سببي).
  • BOS (كسر استمراري) و CHoCH (أول كسر عكس الاتجاه) — بخطوط ووسوم عند نقطة الكسر.
  • صيد السيولة (sweep): اختراق قمة/قاع سابق ثم إغلاق-للداخل (خطف ستوبات) — بعلامة ✗.
  • Premium/Discount: نطاق التداول الحالي + خط التوازن 50% (شراء من الخصم/بيع من البريميوم).
  • OB/FVG منتقاة: أحدث المناطق الطازجة فقط القريبة من السعر (لا 30 منطقة).
كله causal (الـpivot يُؤكَّد بعد w شموع). وسوم إنجليزية (اصطلاح SMC) لتجنّب قلب العربية.

Run: .venv\\Scripts\\python.exe smc_pro.py [SYMBOL] [TF] [BARS]
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
from matplotlib.patches import Rectangle, Patch
from matplotlib.lines import Line2D
import MetaTrader5 as mt5
import order_blocks as ob

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
       "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
BG = "#0b1020"; GRID = "#1a2540"; UP = "#26a69a"; DN = "#ef5350"
C_BOS = "#26a69a"; C_CHOCH = "#ff9800"; C_SWEEP = "#e040fb"; C_LIQ = "#d4a017"
C_PREM = "#ef5350"; C_DISC = "#26a69a"; C_OB = "#42a5f5"; C_FVG = "#7e57c2"


def _swings(h, l, w=5):
    """قمم/قيعان مؤكّدة (fractal متماثل) — تُعرف فقط بعد w شموع يمينية (سببي). يرجع قائمة زمنية."""
    n = len(h); out = []
    for i in range(w, n - w):
        if h[i] == max(h[i - w:i + w + 1]) and np.count_nonzero(h[i - w:i + w + 1] == h[i]) == 1:
            out.append({"idx": i, "confirm": i + w, "price": float(h[i]), "kind": "H"})
        if l[i] == min(l[i - w:i + w + 1]) and np.count_nonzero(l[i - w:i + w + 1] == l[i]) == 1:
            out.append({"idx": i, "confirm": i + w, "price": float(l[i]), "kind": "L"})
    out.sort(key=lambda s: s["idx"])
    return out


def _label_structure(sw):
    """وسم HH/HL/LH/LL بمقارنة كل قمة/قاع بسابقه من نفس النوع."""
    lastH = lastL = None
    for s in sw:
        if s["kind"] == "H":
            s["label"] = "HH" if (lastH is not None and s["price"] > lastH) else ("LH" if lastH is not None else "H")
            lastH = s["price"]
        else:
            s["label"] = "HL" if (lastL is not None and s["price"] > lastL) else ("LL" if lastL is not None else "L")
            lastL = s["price"]
    return sw


def _bos_choch(c, sw):
    """كسر البنية: BOS=كسر مع الاتجاه، CHoCH=أول كسر عكسه. سببي: نستخدم سعر إغلاق البار ومستوى
    قمة/قاع مؤكّد سابقاً فقط. يرجع أحداث {bar, level, type}."""
    events = []; n = len(c)
    sh = [s for s in sw if s["kind"] == "H"]; sl = [s for s in sw if s["kind"] == "L"]
    ih = il = 0; last_sh = last_sl = None; trend = 0
    for b in range(n):
        while ih < len(sh) and sh[ih]["confirm"] <= b:
            last_sh = sh[ih]["price"]; ih += 1
        while il < len(sl) and sl[il]["confirm"] <= b:
            last_sl = sl[il]["price"]; il += 1
        if last_sh is not None and c[b] > last_sh:
            events.append({"bar": b, "level": last_sh, "type": "CHoCH↑" if trend < 0 else "BOS↑"})
            trend = 1; last_sh = None
        elif last_sl is not None and c[b] < last_sl:
            events.append({"bar": b, "level": last_sl, "type": "CHoCH↓" if trend > 0 else "BOS↓"})
            trend = -1; last_sl = None
    return events


def _sweeps(h, l, c, sw):
    """صيد سيولة: بار يخترق قمة/قاع pivot سابق ثم يغلق للداخل (خطف ستوبات ثم رفض)."""
    out = []; n = len(c)
    sh = [s for s in sw if s["kind"] == "H"]; sl = [s for s in sw if s["kind"] == "L"]
    ih = il = 0; lvH = lvL = None
    for b in range(n):
        while ih < len(sh) and sh[ih]["confirm"] <= b:
            lvH = sh[ih]["price"]; ih += 1
        while il < len(sl) and sl[il]["confirm"] <= b:
            lvL = sl[il]["price"]; il += 1
        if lvH is not None and h[b] > lvH and c[b] < lvH:
            out.append({"bar": b, "price": float(h[b]), "type": "SSL"})   # خطف سيولة الشراء أعلى ثم رفض = بيعي
            lvH = None
        if lvL is not None and l[b] < lvL and c[b] > lvL:
            out.append({"bar": b, "price": float(l[b]), "type": "BSL"})
            lvL = None
    return out


def render(symbol="XAUUSDm", tf="M15", bars=140, w=5):
    if not mt5.initialize() and not mt5.initialize():
        print("init failed"); return None
    rates = mt5.copy_rates_from_pos(symbol, _TF.get(tf, mt5.TIMEFRAME_M15), 0, bars)
    info = mt5.symbol_info(symbol); mt5.shutdown()
    if rates is None or len(rates) < 40:
        print("no data"); return None
    o = rates["open"]; hh = rates["high"]; ll = rates["low"]; c = rates["close"]; n = len(c)
    dig = info.digits if info else 2
    sw = _label_structure(_swings(hh, ll, w))
    events = _bos_choch(c, sw)
    sweeps = _sweeps(hh, ll, c, sw)
    obs = ob.detect_order_blocks(rates, swing=w)
    fvgs = ob.detect_fvg(rates)
    pools = ob.liquidity_pools(rates, swing=w)

    fig, ax = plt.subplots(figsize=(16, 8.6), dpi=120)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_color(GRID)
    ax.tick_params(colors="#9fb0d0", labelsize=8); ax.grid(True, color=GRID, lw=0.4, alpha=0.35)

    # Premium / Discount: من آخر قمة وقاع مؤكّدين (النطاق الحالي)
    recentH = next((s["price"] for s in reversed(sw) if s["kind"] == "H"), float(hh.max()))
    recentL = next((s["price"] for s in reversed(sw) if s["kind"] == "L"), float(ll.min()))
    eq = (recentH + recentL) / 2
    ax.axhspan(eq, recentH, color=C_PREM, alpha=0.05, zorder=0)
    ax.axhspan(recentL, eq, color=C_DISC, alpha=0.05, zorder=0)
    ax.axhline(eq, color="#90a4ae", lw=0.8, ls=":", alpha=0.6, zorder=1)
    ax.text(2, eq, " EQ 50% (equilibrium)", color="#90a4ae", fontsize=7, va="bottom", zorder=6)
    ax.text(2, recentH, " PREMIUM (sell area)", color=C_PREM, fontsize=7, va="top", zorder=6, alpha=0.8)
    ax.text(2, recentL, " DISCOUNT (buy area)", color=C_DISC, fontsize=7, va="bottom", zorder=6, alpha=0.8)

    # Fibonacci على النطاق الحالي + منطقة OTE الذهبية (0.618–0.786 = أفضل دخول SMC/ICT)
    rng = (recentH - recentL) or 1e-9
    for f in (0.236, 0.382, 0.5, 0.618, 0.705, 0.786):
        y = recentH - rng * f
        ax.axhline(y, color="#5c6b8a", lw=0.5, ls=":", alpha=0.45, zorder=1)
        ax.text(n - 2, y, f"fib {f:.3f} ", color="#8b9bbf", fontsize=6, ha="right", va="center", alpha=0.8, zorder=6)
    ote_hi = recentH - rng * 0.618; ote_lo = recentH - rng * 0.786
    ax.axhspan(ote_lo, ote_hi, color="#ffd54f", alpha=0.12, zorder=0)
    ax.text(n * 0.5, (ote_lo + ote_hi) / 2, "OTE golden zone 0.62–0.79", color="#ffd54f", fontsize=7, ha="center", va="center", zorder=6, alpha=0.9)

    w_ = 0.38
    for i in range(n):
        col = UP if c[i] >= o[i] else DN
        ax.plot([i, i], [ll[i], hh[i]], color=col, lw=0.7, zorder=3)
        ax.add_patch(Rectangle((i - w_, min(o[i], c[i])), 2 * w_, abs(c[i] - o[i]) or (hh[i] - ll[i]) * 0.02, facecolor=col, edgecolor=col, lw=0.5, zorder=4))

    # وسوم بنية السوق (آخر ~10 فقط لتجنّب الزحام)
    for s in sw[-10:]:
        y = s["price"]; col = "#cdd6e4"
        ax.text(s["idx"], y, s["label"], color=col, fontsize=7.5, ha="center",
                va="bottom" if s["kind"] == "H" else "top", zorder=6, fontweight="bold")
        ax.scatter([s["idx"]], [y], s=12, color="#90a4ae", zorder=5)

    # BOS / CHoCH (آخر ~6)
    for e in events[-6:]:
        col = C_CHOCH if "CHoCH" in e["type"] else C_BOS
        ax.plot([max(0, e["bar"] - 18), e["bar"]], [e["level"], e["level"]], color=col, lw=1.3, ls="--", alpha=0.9, zorder=5)
        ax.text(e["bar"], e["level"], " " + e["type"], color=col, fontsize=7.5, va="center", fontweight="bold", zorder=7)

    # صيد السيولة
    for s in sweeps[-8:]:
        ax.scatter([s["bar"]], [s["price"]], marker="x", s=70, color=C_SWEEP, linewidths=1.6, zorder=7)
        ax.text(s["bar"], s["price"], " sweep", color=C_SWEEP, fontsize=6.5, va="bottom" if s["type"] == "SSL" else "top", zorder=7)

    # سيولة (pools)
    for p in pools[-4:]:
        ax.axhline(p["price"], color=C_LIQ, lw=0.8, ls="--", alpha=0.5, zorder=2)
        ax.text(n - 1, p["price"], f"{'EQH' if p['type']=='equal_highs' else 'EQL'} liq ", color=C_LIQ, fontsize=6.5, ha="right", va="bottom", zorder=6)

    # OB/FVG منتقاة: أحدث طازجة فقط
    fresh_ob = [z for z in obs if not z.get("mitigated")][-2:]
    fresh_fvg = [z for z in fvgs if not z.get("mitigated")][-2:]
    for z in fresh_ob:
        x = z.get("ob_bar", z["idx"])
        ax.add_patch(Rectangle((x, z["lo"]), (n - 1) - x, z["hi"] - z["lo"], facecolor=C_OB, edgecolor=C_OB, alpha=0.18, zorder=2))
        ax.text(n - 1, z["hi"], f"OB {z['type'][:1].upper()} ", color=C_OB, fontsize=7, ha="right", va="bottom", zorder=6)
    for z in fresh_fvg:
        ax.add_patch(Rectangle((z["idx"], z["lo"]), (n - 1) - z["idx"], z["hi"] - z["lo"], facecolor=C_FVG, edgecolor=C_FVG, alpha=0.16, zorder=2))
        ax.text(n - 1, z["lo"], "FVG ", color=C_FVG, fontsize=7, ha="right", va="top", zorder=6)

    last_ev = events[-1]["type"] if events else "—"
    bias = "DISCOUNT→buy" if c[-1] < eq else "PREMIUM→sell"
    ax.set_title(f"SMC structure  ·  {symbol} {tf}  ·  {n} bars   |   last break: {last_ev}  ·  price in {bias}  ·  "
                 f"sweeps {len(sweeps)}  ·  fresh OB {len(fresh_ob)} / FVG {len(fresh_fvg)}   [causal · no look-ahead]",
                 color="#fff", fontsize=10)
    leg = [Line2D([], [], color=C_BOS, ls="--", label="BOS (continuation)"),
           Line2D([], [], color=C_CHOCH, ls="--", label="CHoCH (trend change)"),
           Line2D([], [], color=C_SWEEP, marker="x", ls="", label="liquidity sweep"),
           Patch(facecolor=C_OB, alpha=.4, label="fresh Order Block"), Patch(facecolor=C_FVG, alpha=.4, label="fresh FVG"),
           Patch(facecolor=C_PREM, alpha=.3, label="Premium (sell)"), Patch(facecolor=C_DISC, alpha=.3, label="Discount (buy)")]
    ax.legend(handles=leg, loc="upper left", fontsize=7.5, facecolor="#0d1530", edgecolor=GRID, labelcolor="#cdd6e4", ncol=2)
    ax.set_xlim(-1, n + 6); ax.margins(y=0.05)
    out = _MT5 / f"smc_pro_{symbol}_{tf}.png"
    fig.tight_layout(); fig.savefig(out, facecolor=BG); plt.close(fig)
    print(f"swings={len(sw)} BOS/CHoCH={len(events)} sweeps={len(sweeps)} freshOB={len(fresh_ob)} -> {out}")
    return str(out)


if __name__ == "__main__":
    a = sys.argv
    render(a[1] if len(a) > 1 else "XAUUSDm", a[2] if len(a) > 2 else "M15", int(a[3]) if len(a) > 3 else 140)
