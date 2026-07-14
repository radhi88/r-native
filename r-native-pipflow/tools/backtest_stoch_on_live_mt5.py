"""tools/backtest_stoch_on_live_mt5.py — Stochastic Reversion backtest on live MT5 data.

Usage:
    # With SL (default)
    python tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --out gold_real.png

    # Without SL
    python tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --use-sl 0 --out gold_no_sl.png

Output:
    PNG chart with: candlestick OHLC, Stoch indicator, trade arrows, equity curve
    Terminal summary: trades WR PF net$
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

from strategies.stoch_reversion import backtest, StochReversionConfig


# ─── Chart helpers ───────────────────────────────────────────────

def _candlestick_ax(ax, bars, start=0, end=None):
    if end is None:
        end = len(bars)
    xs = list(range(end - start))
    for i, bi in enumerate(range(start, end)):
        b = bars[bi]
        color = "#26a69a" if b["close"] >= b["open"] else "#ef5350"
        ax.plot([i, i], [b["low"], b["high"]], color=color, linewidth=0.6, zorder=1)
        body_lo = min(b["open"], b["close"])
        body_hi = max(b["open"], b["close"])
        ax.bar(i, body_hi - body_lo, bottom=body_lo, color=color,
               width=0.6, zorder=2)


def _plot_backtest(bars, result, cfg, out_path: str, title: str = "") -> None:
    trades = result["trades"]
    k_arr  = result["indicators"]["stoch_k"]
    d_arr  = result["indicators"]["stoch_d"]
    s      = result["summary"]

    n = len(bars)
    xs = list(range(n))

    fig = plt.figure(figsize=(18, 10), facecolor="#1a1a2e")
    gs  = GridSpec(3, 1, height_ratios=[3, 1.5, 1], hspace=0.08)

    ax_price  = fig.add_subplot(gs[0])
    ax_stoch  = fig.add_subplot(gs[1], sharex=ax_price)
    ax_equity = fig.add_subplot(gs[2], sharex=ax_price)

    for ax in (ax_price, ax_stoch, ax_equity):
        ax.set_facecolor("#16213e")
        ax.tick_params(colors="white", labelsize=7)
        ax.yaxis.label.set_color("white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333")

    # Price chart
    _candlestick_ax(ax_price, bars)

    # Trade arrows
    buy_xs, buy_ys, sell_xs, sell_ys = [], [], [], []
    for t in trades:
        if t["side"] == "BUY":
            buy_xs.append(t["entry_idx"]); buy_ys.append(t["entry_price"])
        else:
            sell_xs.append(t["entry_idx"]); sell_ys.append(t["entry_price"])

    if buy_xs:
        ax_price.scatter(buy_xs, buy_ys, marker="^", color="#26a69a",
                         s=70, zorder=5, label="BUY")
    if sell_xs:
        ax_price.scatter(sell_xs, sell_ys, marker="v", color="#ef5350",
                         s=70, zorder=5, label="SELL")

    ax_price.legend(loc="upper left", framealpha=0.3, fontsize=8)

    head = (title or "Stoch Reversion — Gold M3")
    sl_note = f"SL: {cfg.atr_sl_mult}×ATR" if cfg.use_sl else "No SL"
    ax_price.set_title(
        f"{head}\n"
        f"Trades={s['trades']}  WR={s['win_rate']}%  PF={s['profit_factor']}  "
        f"Net=${s['net_pnl']}  ({sl_note})",
        color="white", fontsize=10, pad=6,
    )

    # Stoch panel
    valid = [i for i in range(n) if not np.isnan(d_arr[i])]
    if valid:
        kv = [k_arr[i] for i in valid]
        dv = [d_arr[i] for i in valid]
        ax_stoch.plot(valid, kv, color="#b0bec5", linewidth=0.8, label="%K")
        ax_stoch.plot(valid, dv, color="#ffeb3b", linewidth=1.2, label="%D")
        ax_stoch.axhline(cfg.ob_heavy, color="#ef5350", linestyle="--", linewidth=0.7, alpha=0.7)
        ax_stoch.axhline(cfg.ob_light, color="#ef5350", linestyle=":",  linewidth=0.5, alpha=0.5)
        ax_stoch.axhline(cfg.midline,  color="#90caf9", linestyle="-",  linewidth=0.5, alpha=0.5)
        ax_stoch.axhline(cfg.os_light, color="#26a69a", linestyle=":",  linewidth=0.5, alpha=0.5)
        ax_stoch.axhline(cfg.os_heavy, color="#26a69a", linestyle="--", linewidth=0.7, alpha=0.7)
        ax_stoch.fill_between(valid, dv, cfg.ob_heavy,
                              where=[d >= cfg.ob_heavy for d in dv],
                              color="#ef5350", alpha=0.15)
        ax_stoch.fill_between(valid, dv, cfg.os_heavy,
                              where=[d <= cfg.os_heavy for d in dv],
                              color="#26a69a", alpha=0.15)
        ax_stoch.set_ylim(0, 100)
        ax_stoch.set_ylabel("Stoch", color="white", fontsize=8)
        ax_stoch.legend(loc="upper left", framealpha=0.3, fontsize=7)

    # Equity curve
    equity = [0.0]
    for t in sorted(trades, key=lambda x: x["entry_idx"]):
        equity.append(equity[-1] + t.get("pnl", 0))
    eq_xs = [0] + [t["entry_idx"] for t in sorted(trades, key=lambda x: x["entry_idx"])]
    color_eq = "#26a69a" if equity[-1] >= 0 else "#ef5350"
    ax_equity.plot(eq_xs, equity, color=color_eq, linewidth=1.2)
    ax_equity.axhline(0, color="#666", linewidth=0.5)
    ax_equity.fill_between(eq_xs, equity, 0,
                           where=[e >= 0 for e in equity],
                           color="#26a69a", alpha=0.2)
    ax_equity.fill_between(eq_xs, equity, 0,
                           where=[e < 0 for e in equity],
                           color="#ef5350", alpha=0.2)
    ax_equity.set_ylabel("Equity $", color="white", fontsize=8)

    plt.setp(ax_price.get_xticklabels(), visible=False)
    plt.setp(ax_stoch.get_xticklabels(), visible=False)

    # X-axis: show time labels on bottom panel
    step = max(1, n // 10)
    xticks = list(range(0, n, step))
    xlabels = [
        __import__("datetime").datetime.utcfromtimestamp(bars[i]["time"]).strftime("%m/%d")
        if isinstance(bars[i]["time"], (int, float)) else str(bars[i]["time"])
        for i in xticks
    ]
    ax_equity.set_xticks(xticks)
    ax_equity.set_xticklabels(xlabels, rotation=30, ha="right", fontsize=6)

    plt.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    print(f"  → saved {out_path}")


# ─── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest Stoch Reversion on live MT5 bars")
    parser.add_argument("--json",   required=True, help="Path to bars JSON (from export_mt5_bars.py)")
    parser.add_argument("--out",    default="stoch_backtest.png")
    parser.add_argument("--use-sl", type=int, default=1,  help="1=use SL, 0=no SL")
    parser.add_argument("--ob-heavy", type=float, default=90.0)
    parser.add_argument("--ob-light", type=float, default=85.0)
    parser.add_argument("--os-heavy", type=float, default=10.0)
    parser.add_argument("--os-light", type=float, default=15.0)
    parser.add_argument("--atr-sl-mult", type=float, default=2.5)
    args = parser.parse_args()

    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    bars = payload.get("bars_data") or payload.get("bars")
    if not isinstance(bars[0], dict):
        print("ERROR: bars must be list of dicts", file=sys.stderr)
        sys.exit(1)

    cfg = StochReversionConfig(
        ob_heavy=args.ob_heavy,
        ob_light=args.ob_light,
        os_heavy=args.os_heavy,
        os_light=args.os_light,
        use_sl=bool(args.use_sl),
        atr_sl_mult=args.atr_sl_mult,
    )

    result = backtest(bars, cfg)
    s = result["summary"]
    sl_note = f"SL={cfg.atr_sl_mult}×ATR" if cfg.use_sl else "NoSL"
    print(f"[{sl_note}]  trades={s['trades']}  WR={s['win_rate']}%  "
          f"PF={s['profit_factor']}  net=${s['net_pnl']}")

    sym = payload.get("symbol", "GOLD")
    tf  = payload.get("timeframe", "M3")
    title = f"Stoch Reversion — {sym} {tf}"
    _plot_backtest(bars, result, cfg, args.out, title=title)


if __name__ == "__main__":
    main()
