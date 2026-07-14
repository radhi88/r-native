"""gold_htf_adversarial.py — stress-test the validated gold HTF trend edge.

Reuses the 6 hostile transforms from r_native/adversarial_backtest.py (J.25)
but runs them through OUR validated strategy (gold_htf_trend.backtest) instead
of the r_native genome simulator. A robust edge survives all 6; a fragile /
regime-lucky edge dies on at least one (especially the MIRROR test).

Run:  python runtime/gold_htf_adversarial.py
"""
from __future__ import annotations
import copy
import numpy as np
from dataclasses import replace

from runtime.gold_htf_trend import load_bars, backtest, Config, Bars


def _rebuild(b: Bars, o, h, l, c) -> Bars:
    return Bars(symbol=b.symbol, timeframe=b.timeframe, time=b.time,
                open=o, high=h, low=l, close=c, source=b.source)


# ── hostile transforms on a Bars object (numpy) ─────────────────────────────
def widen_spread(b: Bars, mult: float) -> Bars:
    center = (b.high + b.low) / 2.0
    half = (b.high - b.low) / 2.0 * mult
    return _rebuild(b, b.open, center + half, center - half, b.close)


def inject_slippage(b: Bars, pts: float, rng) -> Bars:
    noise = rng.uniform(-pts, pts, size=len(b.close)) * 0.01  # gold point=0.01$
    o = b.open + noise
    c = b.close + noise * 0.5
    h = np.maximum.reduce([b.high, o, c])
    l = np.minimum.reduce([b.low, o, c])
    return _rebuild(b, o, h, l, c)


def inject_gap(b: Bars, gap_pct: float, freq: float, rng) -> Bars:
    o, h, l, c = b.open.copy(), b.high.copy(), b.low.copy(), b.close.copy()
    for i in range(1, len(c)):
        if rng.random() < freq:
            g = c[i - 1] * gap_pct * (1 if rng.random() < 0.5 else -1)
            o[i] += g; h[i] += g; l[i] += g; c[i] += g
    return _rebuild(b, o, h, l, c)


def inject_news_spike(b: Bars, n: int, rng) -> Bars:
    o, h, l, c = b.open.copy(), b.high.copy(), b.low.copy(), b.close.copy()
    rng_atr = np.mean(b.high - b.low)
    idxs = rng.choice(np.arange(20, len(c) - 1), size=min(n, len(c) - 21), replace=False)
    for i in idxs:
        d = rng_atr * 3 * (1 if rng.random() < 0.5 else -1)
        c[i] += d
        h[i] = max(h[i], c[i]); l[i] = min(l[i], c[i])
    return _rebuild(b, o, h, l, c)


def mirror(b: Bars) -> Bars:
    """Flip the price path vertically around the first close: uptrend->downtrend.
    Keeps time order & causality intact — the true 'mirror market' test."""
    base = 2.0 * b.close[0]
    o = base - b.open; c = base - b.close
    h = base - b.low; l = base - b.high   # high/low swap under reflection
    return _rebuild(b, o, h, l, c)


def shuffle_returns(b: Bars, rng) -> Bars:
    """Shuffle bar-to-bar returns (destroys trend, keeps volatility)."""
    rets = np.diff(b.close, prepend=b.close[0])
    perm = rng.permutation(len(rets))
    new_c = b.close[0] + np.cumsum(rets[perm])
    span = (b.high - b.low)
    h = new_c + span / 2.0; l = new_c - span / 2.0
    return _rebuild(b, new_c, h, l, new_c)


def _run(cfg, h1, h4, label):
    r = backtest("XAUUSDm", cfg=cfg, bars_h1=h1, bars_htf=h4)
    pf = r.get("profit_factor")
    return {"scenario": label, "trades": r.get("trades", 0),
            "win_rate": r.get("win_rate"), "profit_factor": pf,
            "net": r.get("net"), "max_dd": r.get("max_dd")}


def main():
    cfg = Config(tp_mode="chandelier", chandelier_atr_mult=3.0,
                 ema_fast=50, ema_slow=200)
    h1 = load_bars("XAUUSDm", "H1", days=480)
    h4 = load_bars("XAUUSDm", "H4", days=570)
    if h1 is None or h4 is None:
        print("no bars"); return
    rng = np.random.default_rng(42)

    scen = []
    scen.append(_run(cfg, h1, h4, "clean (baseline)"))
    scen.append(_run(cfg, widen_spread(h1, 2.0), widen_spread(h4, 2.0), "spread_2x"))
    scen.append(_run(cfg, widen_spread(h1, 3.0), widen_spread(h4, 3.0), "spread_3x"))
    scen.append(_run(cfg, inject_slippage(h1, 50, rng), h4, "slippage_high(50pt)"))
    scen.append(_run(cfg, inject_gap(h1, 0.015, 0.05, rng), inject_gap(h4, 0.015, 0.05, rng), "gappy_market"))
    scen.append(_run(cfg, inject_news_spike(h1, 8, rng), h4, "news_spikes"))
    scen.append(_run(cfg, mirror(h1), mirror(h4), "MIRROR (uptrend->downtrend)"))
    scen.append(_run(cfg, shuffle_returns(h1, rng), shuffle_returns(h4, rng), "shuffled (no trend)"))

    print("\n" + "=" * 78)
    print("  GOLD HTF TREND EDGE — ADVERSARIAL STRESS TEST (r_native J.25 transforms)")
    print("=" * 78)
    print(f"  {'scenario':30} {'trades':>7} {'WR%':>6} {'PF':>7} {'net$':>9} {'maxDD$':>8}")
    print("  " + "-" * 74)
    base_pf = None
    for s in scen:
        pf = s["profit_factor"]
        pfv = pf if isinstance(pf, (int, float)) else 999
        if base_pf is None:
            base_pf = pfv
        wr = s["win_rate"]
        wrs = f"{wr*100:.1f}" if isinstance(wr, (int, float)) and wr <= 1 else (f"{wr:.1f}" if isinstance(wr,(int,float)) else "-")
        flag = ""
        if isinstance(pf, (int, float)):
            if pf < 1.0:
                flag = "  <- DIES (PF<1)"
            elif pf < base_pf * 0.7:
                flag = "  <- degrades"
        print(f"  {s['scenario']:30} {s['trades']:>7} {wrs:>6} {pfv:>7.2f} "
              f"{(s['net'] if isinstance(s['net'],(int,float)) else 0):>9.0f} "
              f"{(s['max_dd'] if isinstance(s['max_dd'],(int,float)) else 0):>8.0f}{flag}")
    print("=" * 78)
    survived = sum(1 for s in scen[1:] if isinstance(s["profit_factor"], (int, float)) and s["profit_factor"] >= 1.0)
    print(f"  Survived (PF>=1) in {survived}/{len(scen)-1} hostile scenarios.")
    print("  KEY: MIRROR test = does the edge work when the trend is inverted?")
    print("       If MIRROR collapses -> the edge is pure trend-riding (regime-dependent).")


if __name__ == "__main__":
    main()
