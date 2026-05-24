"""trade_screenshots.py — J.11 — Auto-capture chart snapshots on trade events.

When R Executor opens/closes a trade, snap a small PNG of the chart with
entry/exit markers. Build a visual audit trail you can scroll later.

Two approaches:
  1. RENDERED: Use matplotlib (offline, no MT5 chart needed) — recommended
  2. SCREEN: Use Win32 ScreenToBitmap of the MT5 chart window — needs MT5 open

This module uses approach #1 (matplotlib) since it works headless and gives
consistent output. Approach #2 left as comment hook.

Storage: data/r_native/screenshots/<symbol>/<ticket>_<event>.png
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCREENSHOT_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\screenshots")


def capture_trade_chart(symbol: str, ticket: int, event: str,
                        entry_price: float, exit_price: float | None = None,
                        side: str = "BUY",
                        bars_before: int = 40, bars_after: int = 20) -> Path | None:
    """Render a small candlestick PNG with entry/exit markers.

    Args:
        symbol:      e.g. BTCUSDm
        ticket:      MT5 position ticket
        event:       "OPEN" or "CLOSE"
        entry_price: trade entry price
        exit_price:  trade exit price (None if event=OPEN)
        side:        BUY or SELL
        bars_before: candles before entry
        bars_after:  candles after entry/exit

    Returns: Path to saved PNG, or None on failure.
    """
    try:
        import MetaTrader5 as mt5
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError as e:
        print(f"[screenshots] missing dep: {e}")
        return None

    if not mt5.initialize(): return None
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0,
                                    bars_before + bars_after)
    if bars is None or len(bars) == 0: return None

    fig, ax = plt.subplots(figsize=(8, 4), dpi=80, facecolor="#0a0a0f")
    ax.set_facecolor("#13131a")

    # Plot candlesticks
    for i, b in enumerate(bars):
        color = "#22c55e" if b["close"] >= b["open"] else "#ef4444"
        # Wick
        ax.plot([i, i], [b["low"], b["high"]], color=color, linewidth=0.8)
        # Body
        body_low  = min(b["open"], b["close"])
        body_high = max(b["open"], b["close"])
        ax.add_patch(Rectangle((i - 0.3, body_low), 0.6, body_high - body_low,
                                facecolor=color, edgecolor=color))

    # Entry marker
    ax.axhline(entry_price, color="#f5a524", linestyle="--", linewidth=1, alpha=0.7,
               label=f"Entry {entry_price:.3f}")
    # Exit marker
    if exit_price is not None:
        pl_color = "#22c55e" if (
            (side == "BUY" and exit_price > entry_price) or
            (side == "SELL" and exit_price < entry_price)) else "#ef4444"
        ax.axhline(exit_price, color=pl_color, linestyle="-", linewidth=1, alpha=0.8,
                   label=f"Exit {exit_price:.3f}")

    # Style
    ax.set_title(f"{symbol} · {side} · #{ticket} · {event}",
                 color="#ededf0", fontsize=10)
    ax.tick_params(colors="#9494a0", labelsize=8)
    for spine in ax.spines.values(): spine.set_color("#2a2a38")
    ax.grid(True, color="#1a1a23", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=7, framealpha=0.6,
              facecolor="#13131a", edgecolor="#2a2a38", labelcolor="#ededf0")

    # Save
    out_dir = SCREENSHOT_DIR / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ticket}_{event}_{ts}.png"
    plt.tight_layout()
    plt.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return out_path


def list_recent_screenshots(symbol: str = None, limit: int = 20) -> list[dict]:
    """Return metadata for recent screenshots, newest first."""
    if not SCREENSHOT_DIR.exists(): return []
    files = []
    pattern = SCREENSHOT_DIR / (symbol if symbol else "*") / "*.png"
    import glob
    for fp in glob.glob(str(pattern)):
        p = Path(fp)
        # Parse name: <ticket>_<event>_<ts>.png
        try:
            ticket, event, *rest = p.stem.split("_")
            ts_str = "_".join(rest)
        except Exception:
            ticket = event = ts_str = ""
        files.append({
            "path":   str(p),
            "symbol": p.parent.name,
            "ticket": ticket,
            "event":  event,
            "ts":     ts_str,
            "size":   p.stat().st_size,
        })
    files.sort(key=lambda x: x["ts"], reverse=True)
    return files[:limit]


def cleanup_old(max_age_days: int = 30) -> int:
    """Delete screenshots older than N days. Returns count deleted."""
    if not SCREENSHOT_DIR.exists(): return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    count = 0
    for f in SCREENSHOT_DIR.rglob("*.png"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                count += 1
        except Exception: pass
    return count
