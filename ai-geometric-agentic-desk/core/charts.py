"""Professional geometric chart artist.

Renders a candlestick chart annotated with the desk's geometry: Williams
fractals, Square-of-9 levels, the Gann fan, SMC order-block / FVG zones, and
the proposed entry/SL/TP. Uses a non-interactive Matplotlib backend so it runs
headless inside the agent loop. Returns PNG bytes for the journal BLOB.
"""
from __future__ import annotations

import io
from typing import Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from core.fractals import Fractal  # noqa: E402
from core.smc import SMCSnapshot  # noqa: E402


def _candles(ax, o, h, l, c) -> None:
    """Draw OHLC candles onto ``ax``."""
    for i in range(len(c)):
        up = c[i] >= o[i]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([i, i], [l[i], h[i]], color=col, linewidth=0.6, zorder=1)
        ax.add_patch(plt.Rectangle((i - 0.3, min(o[i], c[i])), 0.6,
                                   abs(c[i] - o[i]) + 1e-9, color=col, zorder=2))


def render(
    symbol: str,
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    fractals: Sequence[Fractal],
    sq9_levels: dict[str, float],
    fan: dict[str, float],
    smc: SMCSnapshot,
    entry: float | None = None,
    sl: float | None = None,
    tps: Sequence[float] = (),
) -> bytes:
    """Render an annotated chart and return PNG bytes.

    Args:
        symbol: Symbol label for the title.
        o, h, l, c: OHLC arrays (oldest first).
        fractals: Confirmed fractals to mark.
        sq9_levels: Square-of-9 levels to draw as horizontal lines.
        fan: Gann fan line prices at the latest bar.
        smc: SMC snapshot for zone shading.
        entry, sl: Optional entry / stop lines.
        tps: Optional take-profit lines.

    Returns:
        PNG image bytes.
    """
    fig, ax = plt.subplots(figsize=(12, 6), dpi=90)
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")
    n = len(c)
    _candles(ax, o, h, l, c)

    for f in fractals[-12:]:
        ax.scatter(f.index, f.price, marker="v" if f.kind == "bear" else "^",
                   color="#ffd54f", s=40, zorder=4)

    for label, lvl in sq9_levels.items():
        if lvl > 0 and l.min() * 0.97 < lvl < h.max() * 1.03:
            ax.axhline(lvl, color="#5c6bc0", linewidth=0.5, alpha=0.5)
            ax.text(0, lvl, f"Sq9{label}", color="#9fa8da", fontsize=6)

    for zone, col, name in ((smc.ob_zone, "#ab47bc", "OB"),
                            (smc.fvg_zone, "#42a5f5", "FVG")):
        if zone:
            ax.add_patch(plt.Rectangle((n - 20, zone[0]), 20, zone[1] - zone[0],
                                       color=col, alpha=0.18, zorder=0))
            ax.text(n - 20, zone[1], name, color=col, fontsize=7)

    if entry:
        ax.axhline(entry, color="#ffffff", linewidth=0.8, linestyle="--")
    if sl:
        ax.axhline(sl, color="#ef5350", linewidth=0.8, linestyle=":")
    for tp in tps:
        ax.axhline(tp, color="#26a69a", linewidth=0.6, linestyle=":")

    ax.set_title(f"{symbol} — Geometric Confluence", color="#eceff1")
    ax.tick_params(colors="#78909c", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#37474f")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
