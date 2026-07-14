"""tools/render_trade_chart.py — Render gold (or any symbol) trade chart
with P/L labels at each entry, plus live SMC zones from smc_engine.

Usage:
    # Live: pulls bars + history straight from MT5
    python tools/render_trade_chart.py --symbol XAUUSDm --tf H1 \
        --since 2026-05-20 --out trades_xau.png

    # Offline: feed it your own bars + trades JSON (no MT5 required)
    python tools/render_trade_chart.py --bars-json bars.json \
        --trades-json trades.json --symbol XAUUSDm --out demo.png

Output: a PNG showing:
    • candlestick chart (dark theme)
    • bullish OB / bearish OB / FVG zones from smc_engine
    • entry arrows (green ▲ for BUY, red ▼ for SELL)
    • exit arrows with P/L label (+$X.XX in green, -$X.XX in red)
    • SL / TP horizontal lines per trade
    • cumulative P/L watermark
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# Headless matplotlib so it works in CI / SSH / Docker
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ─── Data loaders ────────────────────────────────────────────────
def load_bars_from_mt5(symbol: str, tf: str, since: datetime, bars_back: int):
    """Return list[{time, open, high, low, close, volume}] from MT5."""
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        raise SystemExit(f"MetaTrader5 not available: {e}")
    if not mt5.initialize():
        mt5.initialize()
    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
              "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
              "D1": mt5.TIMEFRAME_D1}
    rates = mt5.copy_rates_from(symbol, tf_map[tf], since, bars_back)
    if rates is None:
        return []
    return [{"time": int(r["time"]), "open": float(r["open"]),
             "high": float(r["high"]), "low": float(r["low"]),
             "close": float(r["close"]), "volume": int(r["tick_volume"])}
            for r in rates]


def load_trades_from_mt5(symbol: str, since: datetime, magic: int | None = None):
    """Return list[{open_ts, close_ts, side, entry, exit, sl, tp, profit, ticket}]
    pulled from MT5 deal history."""
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        raise SystemExit(f"MetaTrader5 not available: {e}")
    if not mt5.initialize():
        mt5.initialize()
    deals = mt5.history_deals_get(since, datetime.now()) or []
    # Group deals by position_id: entry deal + exit deal per position
    by_pos: dict[int, dict] = {}
    for d in deals:
        if d.symbol != symbol: continue
        if magic and d.magic != magic: continue
        pid = int(d.position_id)
        rec = by_pos.setdefault(pid, {"ticket": pid, "deals": []})
        rec["deals"].append(d)
    out = []
    for pid, rec in by_pos.items():
        ins  = [d for d in rec["deals"] if d.entry == 0]   # IN
        outs = [d for d in rec["deals"] if d.entry == 1]   # OUT
        if not ins or not outs: continue
        entry_d = ins[0]; exit_d = outs[-1]
        side = "BUY" if entry_d.type == 0 else "SELL"
        out.append({
            "ticket":   pid,
            "open_ts":  int(entry_d.time),
            "close_ts": int(exit_d.time),
            "side":     side,
            "entry":    float(entry_d.price),
            "exit":     float(exit_d.price),
            "profit":   float(sum(d.profit for d in rec["deals"])
                              + sum(d.commission for d in rec["deals"])
                              + sum(d.swap for d in rec["deals"])),
            "sl":       0,  # MT5 deals don't carry the live SL/TP at close
            "tp":       0,
        })
    out.sort(key=lambda t: t["open_ts"])
    return out


def load_json(path: Path) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ─── Chart renderer ──────────────────────────────────────────────
DARK_BG = "#0E1117"
GRID    = "#1f2530"
WICK    = "#9aa4b1"
GREEN   = "#26A69A"
RED     = "#EF5350"
OB_BULL = "#26A69A"
OB_BEAR = "#EF5350"
FVG_BL  = "#42A5F5"
FVG_BR  = "#FF7043"
WHITE   = "#E6E6E6"
GOLD    = "#FFD54F"


def render_chart(bars: list, trades: list, *, symbol: str, out_path: Path,
                 title: str | None = None, draw_smc: bool = True,
                 figsize=(16, 9)) -> Path:
    if not bars:
        raise SystemExit("no bars to render")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    times  = np.array([b["time"] for b in bars])
    opens  = np.array([b["open"]  for b in bars])
    highs  = np.array([b["high"]  for b in bars])
    lows   = np.array([b["low"]   for b in bars])
    closes = np.array([b["close"] for b in bars])

    # Use bar INDEX as x-axis (cleaner than datetime when bars are uneven)
    x = np.arange(len(bars))

    fig, ax = plt.subplots(figsize=figsize, facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    for spine in ax.spines.values(): spine.set_color(GRID)
    ax.tick_params(colors=WICK)
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.6)

    # Candles
    up   = closes >= opens
    body_w = 0.62
    wick_w = 0.10
    for i in range(len(bars)):
        c = GREEN if up[i] else RED
        ax.add_patch(mpatches.Rectangle(
            (x[i] - body_w / 2, min(opens[i], closes[i])),
            body_w, max(1e-9, abs(closes[i] - opens[i])),
            facecolor=c, edgecolor=c, linewidth=0))
        ax.add_patch(mpatches.Rectangle(
            (x[i] - wick_w / 2, lows[i]),
            wick_w, highs[i] - lows[i],
            facecolor=c, edgecolor=c, linewidth=0))

    # SMC zones overlay (best-effort — silent if engine unavailable)
    if draw_smc:
        try:
            import smc_engine as se
            snap = se.compute_offline(bars)
            ob = snap.get("fresh_ob_below")
            if ob:
                ax.add_patch(mpatches.Rectangle(
                    (0, ob["bottom"]), len(bars) - 1, ob["top"] - ob["bottom"],
                    facecolor=OB_BULL, alpha=0.18, edgecolor=OB_BULL,
                    linewidth=1, label="Bullish OB"))
                ax.text(len(bars) * 0.01,
                        (ob["bottom"] + ob["top"]) / 2,
                        "OB ▲", color=OB_BULL, fontsize=9, va="center")
            ob = snap.get("fresh_ob_above")
            if ob:
                ax.add_patch(mpatches.Rectangle(
                    (0, ob["bottom"]), len(bars) - 1, ob["top"] - ob["bottom"],
                    facecolor=OB_BEAR, alpha=0.18, edgecolor=OB_BEAR,
                    linewidth=1, label="Bearish OB"))
                ax.text(len(bars) * 0.01,
                        (ob["bottom"] + ob["top"]) / 2,
                        "OB ▼", color=OB_BEAR, fontsize=9, va="center")
            for fvg in (snap.get("fresh_fvg_bull") or [])[:3]:
                ax.add_patch(mpatches.Rectangle(
                    (0, fvg["bottom"]), len(bars) - 1,
                    fvg["top"] - fvg["bottom"],
                    facecolor=FVG_BL, alpha=0.12, edgecolor=FVG_BL,
                    linewidth=0))
            for fvg in (snap.get("fresh_fvg_bear") or [])[:3]:
                ax.add_patch(mpatches.Rectangle(
                    (0, fvg["bottom"]), len(bars) - 1,
                    fvg["top"] - fvg["bottom"],
                    facecolor=FVG_BR, alpha=0.12, edgecolor=FVG_BR,
                    linewidth=0))
            # Liquidity pools as dashed horizontal lines
            for px in (snap.get("liq_above") or [])[:3]:
                ax.axhline(px, color="#FFA726", linestyle="--",
                           linewidth=0.8, alpha=0.6)
            for px in (snap.get("liq_below") or [])[:3]:
                ax.axhline(px, color="#FFA726", linestyle="--",
                           linewidth=0.8, alpha=0.6)
        except Exception as e:
            print(f"[render] SMC overlay skipped: {e}", file=sys.stderr)

    # Trade markers
    cum_pl = 0.0
    wins = losses = 0
    for t in trades:
        try:
            ix_in  = int(np.searchsorted(times, t["open_ts"]))
            ix_out = int(np.searchsorted(times, t["close_ts"]))
            ix_in  = min(max(0, ix_in),  len(bars) - 1)
            ix_out = min(max(0, ix_out), len(bars) - 1)
        except Exception:
            continue
        side  = (t.get("side") or "").upper()
        entry = float(t.get("entry") or 0)
        exitp = float(t.get("exit")  or 0)
        pnl   = float(t.get("profit") or 0)
        cum_pl += pnl
        if pnl > 0: wins += 1
        elif pnl < 0: losses += 1
        in_color  = GREEN if side == "BUY" else RED
        out_color = GREEN if pnl > 0 else RED

        # Entry arrow
        if side == "BUY":
            ax.annotate("▲", (ix_in, entry), color=in_color, fontsize=14,
                        ha="center", va="top", xytext=(0, -6),
                        textcoords="offset points")
        else:
            ax.annotate("▼", (ix_in, entry), color=in_color, fontsize=14,
                        ha="center", va="bottom", xytext=(0, 6),
                        textcoords="offset points")

        # Connect entry to exit
        ax.plot([ix_in, ix_out], [entry, exitp],
                color=out_color, linewidth=1.4, alpha=0.85, zorder=3)

        # Exit dot + P/L label
        ax.plot(ix_out, exitp, marker="o", color=out_color, markersize=6,
                zorder=4)
        sign = "+" if pnl >= 0 else ""
        label = f"{sign}${pnl:.2f}"
        # Anchor the label above/below depending on side + pnl
        va, dy = ("bottom", 12) if (pnl > 0) ^ (side == "SELL") else ("top", -12)
        ax.annotate(
            label, (ix_out, exitp), color=out_color, fontsize=10,
            fontweight="bold",
            ha="center", va=va,
            xytext=(0, dy), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.25",
                       facecolor=DARK_BG, edgecolor=out_color,
                       linewidth=1, alpha=0.85))

    # Title + summary
    tot = wins + losses
    wr  = (wins / tot * 100) if tot else 0
    sign = "+" if cum_pl >= 0 else ""
    head = title or (f"{symbol} — R-Native trades   "
                     f"({tot} closed · {wins}W/{losses}L · WR {wr:.0f}% · "
                     f"net {sign}${cum_pl:.2f})")
    ax.set_title(head, color=GOLD, fontsize=13, pad=12, fontweight="bold")
    ax.set_xlabel("bar index", color=WICK)
    ax.set_ylabel("price",     color=WICK)

    # Legend (deduped)
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        seen = set(); h2 = []; l2 = []
        for h, l in zip(handles, labels):
            if l in seen: continue
            seen.add(l); h2.append(h); l2.append(l)
        ax.legend(h2, l2, facecolor=DARK_BG, edgecolor=GRID, labelcolor=WHITE,
                  loc="upper left", fontsize=9)

    # Watermark
    ax.text(0.99, 0.02, "R-Native · SMC engine", transform=ax.transAxes,
            ha="right", va="bottom", color="#3a4252", fontsize=8,
            style="italic")

    plt.tight_layout()
    fig.savefig(out_path, dpi=120, facecolor=DARK_BG)
    plt.close(fig)
    return out_path


# ─── CLI ─────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Render a trade chart with P/L labels.")
    p.add_argument("--symbol",   default="XAUUSDm", help="Symbol (e.g. XAUUSDm)")
    p.add_argument("--tf",       default="H1",      help="Timeframe: M1/M5/M15/H1/H4")
    p.add_argument("--since",    default=None,      help="Start date YYYY-MM-DD")
    p.add_argument("--bars-back", type=int, default=200, help="How many bars to fetch")
    p.add_argument("--magic",    type=int, default=None, help="Filter by magic number")
    p.add_argument("--bars-json",   default=None, help="Offline path to bars JSON list")
    p.add_argument("--trades-json", default=None, help="Offline path to trades JSON list")
    p.add_argument("--no-smc",   action="store_true", help="Skip SMC zone overlay")
    p.add_argument("--out",      default="trade_chart.png", help="Output PNG path")
    args = p.parse_args()

    if args.bars_json and args.trades_json:
        bars   = load_json(Path(args.bars_json))
        trades = load_json(Path(args.trades_json))
    else:
        if args.since:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        else:
            since = datetime.now(timezone.utc) - timedelta(days=14)
        bars   = load_bars_from_mt5(args.symbol, args.tf, since, args.bars_back)
        trades = load_trades_from_mt5(args.symbol, since, args.magic)

    out = render_chart(bars, trades, symbol=args.symbol,
                       out_path=Path(args.out), draw_smc=not args.no_smc)
    print(f"wrote {out}  ({len(bars)} bars, {len(trades)} trades)")


if __name__ == "__main__":
    main()
