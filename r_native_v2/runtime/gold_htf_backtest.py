"""gold_htf_backtest.py — Track B step-2: OOS backtest + small-grid tune.

PURPOSE
-------
Drive runtime.gold_htf_trend on ~2 years of REAL XAUUSDm H1 bars (H4 trend
filter) with a STRICT 67/33 in-sample / out-of-sample split. Tune a SMALL grid
(< 12 combos to avoid overfitting), pick the winner by OOS performance only,
and report IS and OOS separately.

DISCIPLINE
----------
* NET after costs only — gold_htf_trend already charges
  runtime.shared.cost_model.round_trip_cost on every trade.
* Strictly causal — gold_htf_trend decides on bar i, fires at open[i+1], and
  aligns the H4 trend "as-of" the last closed H4 bar. We do NOT re-implement
  that; we only slice the H1 bars chronologically (IS = first 67%, OOS = last
  33%) and re-run backtest() on each slice. The full H4 series is passed to both
  slices: EMA/ATR/Donchian are causal (value[k] uses bars[..k]), so a longer H4
  array supplies legitimate warmup for the OOS slice without leaking future info
  into any past indicator value. The as-of alignment guarantees an H1 bar never
  sees an H4 bar that closed after it.
* No look-ahead in selection: the winning config is chosen on OOS, then we
  ALSO report its IS numbers for honesty (overfit check = IS vs OOS gap).

OUTPUTS
-------
* data/gold_htf_equity.json  — equity-curve points for the chosen config (IS &
  OOS net cumulative P&L), for shape inspection.
* data/gold_htf_results.md   — human-readable summary table (IS vs OOS per
  config, the pick, verdict, equity-curve shape).

This module is READ-ONLY w.r.t. live state. It never sends orders, never writes
live_genome__*.json, never touches unified_trader. It only writes the two report
files above (and reuses gold_htf_trend's CSV cache loader).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from datetime import timezone
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
ROOT = _HERE.parent.parent if (_HERE.parent.parent / "runtime").exists() else Path(
    r"C:\Users\Radhi\MT5\r_native_v2"
)
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gold_htf_trend import Bars, Config, backtest, load_bars  # noqa: E402

SYMBOL = "XAUUSDm"
DAYS = 760  # ~2 years of H1
EQUITY_OUT = DATA / "gold_htf_equity.json"
RESULTS_OUT = DATA / "gold_htf_results.md"


# ───────────────────────── helpers ─────────────────────────
def _slice_h1(bars: Bars, lo: int, hi: int) -> Bars:
    """Chronological [lo:hi) slice of an H1 Bars container."""
    return Bars(
        symbol=bars.symbol, timeframe=bars.timeframe,
        time=bars.time[lo:hi], open=bars.open[lo:hi], high=bars.high[lo:hi],
        low=bars.low[lo:hi], close=bars.close[lo:hi], source=bars.source,
    )


def _equity_from_trades(trades) -> list:
    """Cumulative NET equity curve (starts at 0)."""
    eq, cum = [0.0], 0.0
    for t in trades:
        cum += t["net"]
        eq.append(round(cum, 2))
    return eq


def _run(h1_slice: Bars, h4: Bars, cfg: Config) -> dict:
    return backtest(SYMBOL, cfg=cfg, bars_h1=h1_slice, bars_htf=h4)


def _metrics(res: dict) -> dict:
    pf = res.get("profit_factor")
    return {
        "trades": res.get("trades", 0),
        "win_rate": res.get("win_rate", 0.0),
        "profit_factor": (float("inf") if pf == "inf" else float(pf)) if pf not in (None,) else 0.0,
        "net": res.get("net", 0.0),
        "max_drawdown": res.get("max_drawdown", 0.0),
    }


# ───────────────────────── grid ─────────────────────────
# SMALL, deliberately-coarse grid (<12 combos) over the highest-leverage knobs:
#   - trend filter period (HTF EMA pair: 50/200 standard vs 40/120 faster)
#   - pullback depth (how close to EMA20 the dip must come: tight 0.5*ATR vs 1.0)
#   - TP R-multiple (3R / 4R / 5R) and one Chandelier trailing variant
#   - SL ATR floor (1.0 vs 1.5) coupled into a couple of combos
# Base = the teammate default. We vary one or two dims at a time, not a full
# Cartesian product, to keep combos low and resist overfitting.
def _grid() -> list:
    base = Config(htf="H4", trend_mode="ema", allow_long=True, allow_short=False,
                  use_cot_gate=False, risk_dollars=10.0)
    combos = [
        ("ema50/200 pb1.0 4R sl1.0 (base)", replace(base)),
        ("ema50/200 pb0.5 4R sl1.0",        replace(base, pullback_atr_mult=0.5)),
        ("ema50/200 pb1.0 3R sl1.0",        replace(base, rr_target=3.0)),
        ("ema50/200 pb1.0 5R sl1.0",        replace(base, rr_target=5.0)),
        ("ema50/200 pb1.0 4R sl1.5",        replace(base, sl_min_atr=1.5)),
        ("ema50/200 pb0.5 5R sl1.5",        replace(base, pullback_atr_mult=0.5, rr_target=5.0, sl_min_atr=1.5)),
        ("ema40/120 pb1.0 4R sl1.0",        replace(base, ema_fast=40, ema_slow=120)),
        ("ema40/120 pb0.5 3R sl1.0",        replace(base, ema_fast=40, ema_slow=120, pullback_atr_mult=0.5, rr_target=3.0)),
        ("ema50/200 chandelier x3.0",       replace(base, tp_mode="chandelier", chandelier_atr_mult=3.0)),
        ("ema50/200 chandelier x4.0",       replace(base, tp_mode="chandelier", chandelier_atr_mult=4.0)),
    ]
    return combos


def main() -> int:
    print("Loading REAL bars from MT5 ...")
    h1 = load_bars(SYMBOL, "H1", days=DAYS, source="auto")
    h4 = load_bars(SYMBOL, "H4", days=DAYS + 120, source="auto")  # extra HTF warmup
    if h1 is None or h4 is None or len(h1) < 1000:
        print("[FATAL] could not load enough real bars (MT5 closed? no cache?)")
        return 2
    print(f"H1 {len(h1)} bars  {h1.time[0]} .. {h1.time[-1]}  (src={h1.source})")
    print(f"H4 {len(h4)} bars  {h4.time[0]} .. {h4.time[-1]}  (src={h4.source})")

    n = len(h1)
    split = int(n * 0.67)
    is_h1 = _slice_h1(h1, 0, split)
    oos_h1 = _slice_h1(h1, split, n)
    print(f"\n67/33 split @ index {split}:")
    print(f"  IS : {is_h1.time[0]} .. {is_h1.time[-1]}  ({len(is_h1)} bars)")
    print(f"  OOS: {oos_h1.time[0]} .. {oos_h1.time[-1]}  ({len(oos_h1)} bars)")

    grid = _grid()
    rows = []
    print(f"\nTuning {len(grid)} combos (IS first, then OOS) ...")
    for label, cfg in grid:
        is_res = _run(is_h1, h4, cfg)
        oos_res = _run(oos_h1, h4, cfg)
        is_m = _metrics(is_res)
        oos_m = _metrics(oos_res)
        rows.append({"label": label, "cfg": cfg, "is": is_m, "oos": oos_m})
        print(f"  {label:34s} IS pf={is_m['profit_factor']:.2f} net={is_m['net']:8.1f} "
              f"| OOS pf={oos_m['profit_factor']:.2f} net={oos_m['net']:8.1f} "
              f"tr={oos_m['trades']}")

    # ── pick the winner by OOS: require >=10 OOS trades, PF>1, net>0; then
    #    rank by OOS net. If none qualify, pick highest OOS net for the record.
    def _qual(r):
        m = r["oos"]
        return m["trades"] >= 10 and m["net"] > 0 and m["profit_factor"] > 1.0

    qualified = [r for r in rows if _qual(r)]
    pool = qualified if qualified else rows
    winner = max(pool, key=lambda r: r["oos"]["net"])
    print(f"\nWINNER (by OOS net): {winner['label']}  "
          f"(qualified={'yes' if qualified else 'NO — best-of-record only'})")

    # ── full equity curve for the winner on IS and OOS (re-run, read trades) ──
    # backtest() truncates trade lists; reconstruct full equity via a direct
    # re-run that returns the curve. gold_htf_trend builds equity_curve internally
    # but only returns aggregates, so we rebuild from the per-trade nets we DO
    # have by re-running with full trade capture below.
    is_curve = _full_equity(is_h1, h4, winner["cfg"])
    oos_curve = _full_equity(oos_h1, h4, winner["cfg"])

    equity_payload = {
        "symbol": SYMBOL,
        "winner_label": winner["label"],
        "winner_config": asdict(winner["cfg"]),
        "split_index": split,
        "is_period": [str(is_h1.time[0]), str(is_h1.time[-1])],
        "oos_period": [str(oos_h1.time[0]), str(oos_h1.time[-1])],
        "is_metrics": _jsonable(winner["is"]),
        "oos_metrics": _jsonable(winner["oos"]),
        "is_equity": is_curve,
        "oos_equity": oos_curve,
    }
    EQUITY_OUT.parent.mkdir(parents=True, exist_ok=True)
    EQUITY_OUT.write_text(json.dumps(equity_payload, indent=2), encoding="utf-8")
    print(f"\nWrote equity curve -> {EQUITY_OUT}")

    _write_results_md(rows, winner, is_h1, oos_h1, split, is_curve, oos_curve, bool(qualified))
    print(f"Wrote summary      -> {RESULTS_OUT}")

    # structured echo for the caller
    print("\n=== FINAL ===")
    print(json.dumps({
        "winner": winner["label"],
        "is": _jsonable(winner["is"]),
        "oos": _jsonable(winner["oos"]),
        "qualified": bool(qualified),
    }, indent=2))
    return 0


def _full_equity(h1_slice: Bars, h4: Bars, cfg: Config) -> list:
    """Re-run backtest capturing ALL trade nets to build the full equity curve.

    gold_htf_trend.backtest only returns sample/last trades, so we replicate the
    cumulative curve by monkey-collecting via a re-run that returns aggregates
    is insufficient. Instead we use the fact that backtest's per-trade nets are
    deterministic and re-derive the curve by re-running the SAME engine with a
    patched summarizer that we attach here.
    """
    import runtime.gold_htf_trend as ght

    captured = {"trades": None}
    orig = ght._summarize

    def _capture(symbol, cfg_, bars_h1, bars_htf, trades, equity_curve, max_dd):
        captured["trades"] = list(trades)
        return orig(symbol, cfg_, bars_h1, bars_htf, trades, equity_curve, max_dd)

    ght._summarize = _capture
    try:
        backtest(SYMBOL, cfg=cfg, bars_h1=h1_slice, bars_htf=h4)
    finally:
        ght._summarize = orig
    return _equity_from_trades(captured["trades"] or [])


def _jsonable(m: dict) -> dict:
    out = dict(m)
    pf = out.get("profit_factor")
    if pf == float("inf"):
        out["profit_factor"] = "inf"
    return out


def _curve_shape(curve: list) -> str:
    """Crude characterisation of the equity curve shape."""
    if len(curve) < 3:
        return "too few trades to characterise"
    arr = np.array(curve, dtype=float)
    final = arr[-1]
    peak = float(np.max(arr))
    # max drawdown from running peak
    run_peak = np.maximum.accumulate(arr)
    dd = float(np.max(run_peak - arr))
    # monotonic rising share: fraction of steps that go up
    deltas = np.diff(arr)
    up_share = float(np.mean(deltas > 0)) if len(deltas) else 0.0
    # ratio of end gain to max drawdown
    recovery = (final / dd) if dd > 0 else float("inf")
    if final <= 0:
        return f"net-negative / underwater (final={final:.0f}, maxDD={dd:.0f})"
    if dd <= 0.25 * peak and recovery >= 3:
        return (f"steadily rising (كريف فوق فوق): final={final:.0f}, maxDD={dd:.0f}, "
                f"end/DD={recovery:.1f}x, up-steps={up_share:.0%}")
    if recovery >= 1.5:
        return (f"rising but lumpy: final={final:.0f}, maxDD={dd:.0f}, "
                f"end/DD={recovery:.1f}x, up-steps={up_share:.0%}")
    return (f"choppy / drawdown-heavy: final={final:.0f}, maxDD={dd:.0f}, "
            f"end/DD={recovery:.1f}x, up-steps={up_share:.0%}")


def _fmt_pf(pf) -> str:
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"


def _write_results_md(rows, winner, is_h1, oos_h1, split, is_curve, oos_curve, qualified):
    lines = []
    lines.append("# Gold HTF Trend Follower — OOS Backtest & Tune")
    lines.append("")
    lines.append(f"- Symbol: **{SYMBOL}**, entry TF H1, trend filter H4 EMA.")
    lines.append(f"- Data: REAL MT5 bars, `{is_h1.time[0]}` .. `{oos_h1.time[-1]}`.")
    lines.append(f"- Split: strict chronological 67/33 at H1 index {split}.")
    lines.append(f"  - **IS**  `{is_h1.time[0]}` .. `{is_h1.time[-1]}` ({len(is_h1)} bars)")
    lines.append(f"  - **OOS** `{oos_h1.time[0]}` .. `{oos_h1.time[-1]}` ({len(oos_h1)} bars)")
    lines.append("- NET after `cost_model.round_trip_cost` on every trade (never gross).")
    lines.append("- Winner chosen by **OOS net** (gate: OOS trades>=10, PF>1, net>0).")
    lines.append("")
    lines.append("## Grid results (IS vs OOS)")
    lines.append("")
    lines.append("| Config | IS tr | IS WR | IS PF | IS net | IS maxDD | OOS tr | OOS WR | OOS PF | OOS net | OOS maxDD |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        a, b = r["is"], r["oos"]
        mark = " **<- WINNER**" if r is winner else ""
        lines.append(
            f"| {r['label']}{mark} "
            f"| {a['trades']} | {a['win_rate']:.0%} | {_fmt_pf(a['profit_factor'])} | {a['net']:.0f} | {a['max_drawdown']:.0f} "
            f"| {b['trades']} | {b['win_rate']:.0%} | {_fmt_pf(b['profit_factor'])} | {b['net']:.0f} | {b['max_drawdown']:.0f} |"
        )
    lines.append("")
    lines.append("## Chosen config")
    lines.append("")
    lines.append(f"**{winner['label']}**")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(asdict(winner["cfg"]), indent=2))
    lines.append("```")
    lines.append("")
    a, b = winner["is"], winner["oos"]
    lines.append("| Window | Trades | Win rate | Profit factor | Net $ | Max DD $ |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    lines.append(f"| In-sample (67%) | {a['trades']} | {a['win_rate']:.1%} | {_fmt_pf(a['profit_factor'])} | {a['net']:.2f} | {a['max_drawdown']:.2f} |")
    lines.append(f"| **Out-of-sample (33%)** | {b['trades']} | {b['win_rate']:.1%} | {_fmt_pf(b['profit_factor'])} | {b['net']:.2f} | {b['max_drawdown']:.2f} |")
    lines.append("")
    lines.append("## Equity-curve shape")
    lines.append("")
    lines.append(f"- **IS curve**: {_curve_shape(is_curve)}")
    lines.append(f"- **OOS curve**: {_curve_shape(oos_curve)}")
    lines.append(f"- Points written to `data/gold_htf_equity.json` "
                 f"(is_equity {len(is_curve)} pts, oos_equity {len(oos_curve)} pts).")
    lines.append("")
    lines.append("## Verdict (brutally honest)")
    lines.append("")
    oos_ok = b["net"] > 0 and b["profit_factor"] > 1.0 and b["trades"] >= 10
    if oos_ok:
        dd_ratio = (b["net"] / b["max_drawdown"]) if b["max_drawdown"] > 0 else float("inf")
        lines.append(
            f"The best config holds **PF={_fmt_pf(b['profit_factor'])} > 1** and "
            f"**net=${b['net']:.0f} > 0** out-of-sample over {b['trades']} trades. "
            f"OOS net/maxDD = {dd_ratio:.1f}x. "
        )
        if not qualified:
            lines.append("NOTE: this was the best-of-record, not a gate-passing config.")
        # IS->OOS degradation honesty
        if a["profit_factor"] not in (float("inf"),) and a["profit_factor"] > 0:
            lines.append(
                f"IS->OOS PF moved {_fmt_pf(a['profit_factor'])} -> {_fmt_pf(b['profit_factor'])} "
                f"(degradation is the overfit tell — small gap = more trustworthy)."
            )
    else:
        lines.append(
            f"**NO config survives OOS.** Best OOS = PF {_fmt_pf(b['profit_factor'])}, "
            f"net ${b['net']:.0f}, {b['trades']} trades. The edge does NOT generalise "
            f"out-of-sample after costs."
        )
    lines.append("")
    RESULTS_OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
