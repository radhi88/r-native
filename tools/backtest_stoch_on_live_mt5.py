"""Pull real M3 gold bars from YOUR MT5 and run the Stochastic-Reversion
backtest on them. Saves a PNG identical in layout to the synthetic-data
demo, but using actual market data.

Run on your Windows machine:

    python tools/backtest_stoch_on_live_mt5.py
    # default: XAUUSDm, last 7 days of M3, output stoch_rev_real.png

    python tools/backtest_stoch_on_live_mt5.py --symbol XAUUSD --bars 4000 \
        --use-sl 1 --out gold_real.png

Requires MetaTrader5 Python package + MT5 terminal running and logged in.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Headless matplotlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp

# Try both package forms so it works regardless of repo layout on disk
try:
    from r_native.strategies.stoch_reversion import backtest, stochastic_kd
except Exception:
    try:
        from strategies.stoch_reversion import backtest, stochastic_kd
    except Exception:
        # Hard fallback: explicit file load
        import importlib.util, types
        if "r_native" not in sys.modules:
            p = types.ModuleType("r_native"); p.__path__ = [str(REPO)]
            sys.modules["r_native"] = p
        for sub in ("strategy_types",):
            s = importlib.util.spec_from_file_location(
                f"r_native.{sub}", str(REPO / f"{sub}.py"))
            m = importlib.util.module_from_spec(s)
            sys.modules[f"r_native.{sub}"] = m; s.loader.exec_module(m)
        spec = importlib.util.spec_from_file_location(
            "strategies.stoch_reversion", str(REPO / "strategies" / "stoch_reversion.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["strategies.stoch_reversion"] = mod; spec.loader.exec_module(mod)
        backtest = mod.backtest; stochastic_kd = mod.stochastic_kd


# ─── MT5 bar fetch ──────────────────────────────────────────────
def fetch_mt5_bars(symbol: str, n_bars: int = 4000):
    """Pull the last N M3 bars from MT5. M3 isn't a built-in TF — we fetch M1
    and resample to M3 (every 3 minutes)."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise SystemExit(
            "MetaTrader5 package not installed. Run:\n"
            "    pip install MetaTrader5"
        )
    if not mt5.initialize():
        raise SystemExit(f"MT5 init failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        # Try common variants
        for variant in (symbol, symbol + "m", symbol + ".raw", symbol[:-1]):
            if mt5.symbol_info(variant) is not None:
                symbol = variant
                print(f"  using symbol '{symbol}'")
                break
        else:
            raise SystemExit(f"symbol {symbol} not found in MT5")
    if not info or not info.visible:
        mt5.symbol_select(symbol, True)

    # Fetch n_bars * 3 of M1 then aggregate to M3 (M3 isn't a native TF in MT5)
    n_m1 = n_bars * 3 + 30
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n_m1)
    if rates is None or len(rates) < 100:
        raise SystemExit(f"insufficient M1 data ({0 if rates is None else len(rates)})")

    # Resample M1 -> M3
    m3 = []
    block = []
    for r in rates:
        block.append(r)
        # Align to wall-clock multiples of 3 minutes
        # Boundary = when (epoch / 60) % 3 == 2 (the 3rd minute closes)
        if (int(r["time"]) // 60) % 3 == 2 and block:
            m3.append({
                "time":  int(block[0]["time"]),
                "open":  float(block[0]["open"]),
                "high":  float(max(b["high"] for b in block)),
                "low":   float(min(b["low"]  for b in block)),
                "close": float(block[-1]["close"]),
                "volume": int(sum(int(b["tick_volume"]) for b in block)),
            })
            block = []
    if not m3:
        # Fallback: just chunk by 3 if no clean boundaries
        chunks = [rates[i:i+3] for i in range(0, len(rates) - 2, 3)]
        for ch in chunks:
            m3.append({
                "time":  int(ch[0]["time"]),
                "open":  float(ch[0]["open"]),
                "high":  float(max(b["high"] for b in ch)),
                "low":   float(min(b["low"]  for b in ch)),
                "close": float(ch[-1]["close"]),
                "volume": int(sum(int(b["tick_volume"]) for b in ch)),
            })
    return symbol, m3[-n_bars:]


# ─── Render (same layout as the synthetic-data PNG) ─────────────
DARK="#0e1117"; GREEN="#26A69A"; RED="#EF5350"; GOLD="#FFD54F"
WHITE="#E6E6E6"; MUTED="#94a3b8"; CYAN="#22d3ee"; VIOLET="#8b5cf6"


def render(bars: list, result: dict, symbol: str, out_path: Path,
           title_suffix: str = "") -> Path:
    s = result["summary"]
    x = np.arange(len(bars))
    opens  = np.array([b["open"]  for b in bars])
    highs  = np.array([b["high"]  for b in bars])
    lows   = np.array([b["low"]   for b in bars])
    closes = np.array([b["close"] for b in bars])

    fig, (ax_price, ax_stoch, ax_eq) = plt.subplots(
        3, 1, figsize=(20, 12), facecolor=DARK,
        gridspec_kw={"height_ratios": [4, 2, 1.2], "hspace": 0.10})
    for ax in (ax_price, ax_stoch, ax_eq):
        ax.set_facecolor(DARK)
        for sp in ax.spines.values(): sp.set_color("#1f2530")
        ax.tick_params(colors=MUTED, labelsize=9)
        ax.grid(True, color="#1f2530", lw=0.5, alpha=0.55)

    # Candles
    up = closes >= opens
    bw = max(0.35, min(0.7, 600 / len(bars)))
    for i in range(len(bars)):
        cc = GREEN if up[i] else RED
        ax_price.add_patch(mp.Rectangle((x[i] - bw / 2, min(opens[i], closes[i])),
                                         bw, max(1e-6, abs(closes[i] - opens[i])),
                                         facecolor=cc, edgecolor=cc, lw=0))
        ax_price.add_patch(mp.Rectangle((x[i] - bw * 0.07, lows[i]),
                                         bw * 0.14, highs[i] - lows[i],
                                         facecolor=cc, edgecolor=cc, lw=0))

    # Trades
    for t in result["trades"]:
        win = t["profit"] > 0; col = GREEN if win else RED
        if t["side"] == "SELL":
            ax_price.annotate("▼", (t["idx_open"], t["entry"]), color=RED, fontsize=11,
                              ha="center", va="bottom",
                              xytext=(0, 6), textcoords="offset points")
        else:
            ax_price.annotate("▲", (t["idx_open"], t["entry"]), color=GREEN, fontsize=11,
                              ha="center", va="top",
                              xytext=(0, -6), textcoords="offset points")
        ax_price.plot([t["idx_open"], t["idx_close"]],
                       [t["entry"], t["exit"]],
                       color=col, lw=1.0, alpha=0.80, zorder=3)
        ax_price.plot(t["idx_close"], t["exit"], marker="o",
                       color=col, ms=4, zorder=4)
        sign = "+" if t["profit"] >= 0 else ""
        ax_price.annotate(f"{sign}${t['profit']:.1f}",
                          (t["idx_close"], t["exit"]), color=col, fontsize=7,
                          fontweight="bold", ha="center",
                          va="bottom" if win else "top",
                          xytext=(0, 8 if win else -8),
                          textcoords="offset points")

    days = (bars[-1]["time"] - bars[0]["time"]) / 86400
    ax_price.set_title(
        f"{symbol} · M3 · Stochastic-Reversion {title_suffix}    "
        f"{s['trades']} trades · {s['win_rate']}% WR · PF {s['profit_factor']} · "
        f"net {('+' if s['net_pnl']>=0 else '')}${s['net_pnl']:.2f}  "
        f"({len(bars)} bars ≈ {days:.1f} days)",
        color=GOLD, fontsize=12, pad=10, fontweight="bold")
    ax_price.set_ylabel("price (USD)", color=MUTED)

    # Stochastic panel
    d = np.array(result["stoch_d"]); k = np.array(result["stoch_k"])
    ax_stoch.fill_between(x, 0, np.nan_to_num(k, nan=0),
                          color=CYAN, alpha=0.18, step="mid", label="%K")
    ax_stoch.plot(x, d, color=GOLD, lw=1.4, label="%D")
    for lvl, col, ls, txt in [(90, RED, "--", "Sell 90"), (85, RED, ":", "Sell 85"),
                               (50, WHITE, "-", "TP 50"),
                               (15, GREEN, ":", "Buy 15"), (10, GREEN, "--", "Buy 10")]:
        ax_stoch.axhline(lvl, color=col, lw=0.8, ls=ls, alpha=0.6)
        ax_stoch.text(len(x) * 1.005, lvl, txt, color=col, fontsize=8, va="center")
    ax_stoch.set_ylim(-3, 103)
    ax_stoch.set_ylabel("Stochastic", color=MUTED)
    ax_stoch.legend(facecolor=DARK, edgecolor="#1f2530", labelcolor=WHITE,
                    loc="lower left", fontsize=8)
    for t in result["trades"]:
        col = GREEN if t["profit"] > 0 else RED
        di = d[t["idx_open"]] if not np.isnan(d[t["idx_open"]]) else 50
        ax_stoch.plot(t["idx_open"], di, marker="o", color=col, ms=3, alpha=0.85)

    # Equity
    eq_x = [e["i"] for e in result["equity_curve"]]
    eq_y = [e["eq"] for e in result["equity_curve"]]
    ax_eq.plot(eq_x, eq_y, color=VIOLET, lw=1.4)
    ax_eq.fill_between(eq_x, 0, eq_y, where=np.array(eq_y) > 0,
                       color=GREEN, alpha=0.15, step="mid")
    ax_eq.fill_between(eq_x, 0, eq_y, where=np.array(eq_y) < 0,
                       color=RED,   alpha=0.15, step="mid")
    ax_eq.axhline(0, color=MUTED, lw=0.6, ls=":")
    ax_eq.set_ylabel("equity (USD)", color=MUTED)
    ax_eq.set_xlabel("bar index (M3)", color=MUTED)

    plt.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=DARK, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ─── CLI ────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Stochastic-Reversion backtest on REAL MT5 gold M3 data")
    ap.add_argument("--symbol",  default="XAUUSDm", help="Gold symbol on your broker")
    ap.add_argument("--bars",    type=int, default=4000, help="How many M3 bars to backtest")
    ap.add_argument("--use-sl",  type=int, default=1,    help="1 = ATR SL, 0 = no SL (screenshot mode)")
    ap.add_argument("--sl-mult", type=float, default=2.5, help="ATR x N for SL distance")
    ap.add_argument("--out",     default="stoch_rev_real.png", help="Output PNG path")
    args = ap.parse_args()

    print(f"Fetching {args.bars} M3 bars of {args.symbol} from MT5...")
    sym, bars = fetch_mt5_bars(args.symbol, args.bars)
    days = (bars[-1]["time"] - bars[0]["time"]) / 86400
    print(f"  got {len(bars)} M3 bars ≈ {days:.1f} days   "
          f"first={datetime.fromtimestamp(bars[0]['time'])}   "
          f"last={datetime.fromtimestamp(bars[-1]['time'])}")
    lo = min(b["low"]  for b in bars)
    hi = max(b["high"] for b in bars)
    print(f"  price range: {lo:.2f}  ->  {hi:.2f}")

    # The lot economics: 0.01 lot of gold => ~$1 per $1 price-unit (contract 100)
    sl_mode = args.use_sl == 1
    print(f"\nRunning backtest (UseSL={sl_mode}, slMult={args.sl_mult})...")
    result = backtest(bars,
                       atr_sl_mult=(args.sl_mult if sl_mode else 1e9),
                       lot_value_per_unit=1.0)
    s = result["summary"]
    print("\n=== BACKTEST SUMMARY ===")
    for k, v in s.items():
        print(f"  {k:18s} {v}")

    # Optionally: top winners + worst losers
    trades = result["trades"]
    if trades:
        best = max(trades, key=lambda t: t["profit"])
        worst = min(trades, key=lambda t: t["profit"])
        print(f"\n  BEST  trade: {best['side']} @{best['entry']:.2f} -> {best['exit']:.2f}  "
              f"({best['exit_reason']})  +${best['profit']:.2f}")
        print(f"  WORST trade: {worst['side']} @{worst['entry']:.2f} -> {worst['exit']:.2f}  "
              f"({worst['exit_reason']})  ${worst['profit']:.2f}")

    out = render(bars, result, sym, Path(args.out),
                 title_suffix=("(no SL — screenshot mode)" if not sl_mode else ""))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
