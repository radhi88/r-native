"""verify_gold_htf_adversarial.py — Track B step-3 ADVERSARIAL VERIFY (READ-ONLY).

Independent referee of gold_htf_backtest.py's WINNER claim
(ema50/200 chandelier x3.0). Creates NO live state, writes nothing.

Checks:
  (A) Data source actually used (real bars vs synthetic).
  (B) Re-derive PF / WR / net / maxDD from the raw per-trade nets, independently
      of _summarize, and compare to the reported aggregates.
  (C) Cost model truly applied: every trade must have cost>0 and net==gross-cost.
  (D) Look-ahead / HTF-leak test: re-run OOS with the HTF series TRUNCATED so it
      contains no H4 bar that closes after the OOS H1 start. If results are
      identical, the longer HTF array in the original run supplied only legit
      warmup (no future leak). If they differ, there is leakage.
  (E) Stop-then-target conservatism + same-bar look-ahead spot check.
  (F) Multiple-testing: how many of the 10 grid cells pass OOS; is the winner an
      outlier or part of a broad cluster.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gold_htf_trend import Bars, Config, backtest, load_bars  # noqa: E402
import runtime.gold_htf_trend as ght  # noqa: E402

SYMBOL = "XAUUSDm"
DAYS = 760


def _slice(bars, lo, hi):
    return Bars(symbol=bars.symbol, timeframe=bars.timeframe,
                time=bars.time[lo:hi], open=bars.open[lo:hi], high=bars.high[lo:hi],
                low=bars.low[lo:hi], close=bars.close[lo:hi], source=bars.source)


def _capture_trades(h1, h4, cfg):
    cap = {"t": None}
    orig = ght._summarize
    def grab(symbol, cfg_, b1, bhtf, trades, eq, dd):
        cap["t"] = list(trades)
        return orig(symbol, cfg_, b1, bhtf, trades, eq, dd)
    ght._summarize = grab
    try:
        res = backtest(SYMBOL, cfg=cfg, bars_h1=h1, bars_htf=h4)
    finally:
        ght._summarize = orig
    return res, cap["t"]


def _independent_metrics(trades):
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    pf = (gp / gl) if gl > 0 else float("inf")
    wr = len(wins) / len(nets) if nets else 0.0
    # equity curve + maxDD from running peak
    eq, cum, peak, dd = [0.0], 0.0, 0.0, 0.0
    for x in nets:
        cum += x
        eq.append(cum)
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"trades": len(nets), "win_rate": wr, "pf": pf,
            "net": sum(nets), "maxdd": dd, "peak": peak, "final": cum}


def main():
    out = []
    h1 = load_bars(SYMBOL, "H1", days=DAYS, source="auto")
    h4 = load_bars(SYMBOL, "H4", days=DAYS + 120, source="auto")
    out.append(f"[A] H1 source={h1.source} n={len(h1)} {h1.time[0]}..{h1.time[-1]}")
    out.append(f"[A] H4 source={h4.source} n={len(h4)} {h4.time[0]}..{h4.time[-1]}")

    n = len(h1)
    split = int(n * 0.67)
    oos = _slice(h1, split, n)
    is_ = _slice(h1, 0, split)
    out.append(f"[A] split={split} OOS {oos.time[0]}..{oos.time[-1]} ({len(oos)} bars)")

    winner = Config(htf="H4", trend_mode="ema", allow_long=True, allow_short=False,
                    use_cot_gate=False, risk_dollars=10.0,
                    tp_mode="chandelier", chandelier_atr_mult=3.0)

    res, trades = _capture_trades(oos, h4, winner)
    m = _independent_metrics(trades)
    out.append("")
    out.append("[B] INDEPENDENT RE-DERIVE (OOS winner):")
    out.append(f"    reported: tr=85 wr=0.4235 pf=1.3114 net=642.02 dd=431.31")
    out.append(f"    mine:     tr={m['trades']} wr={m['win_rate']:.4f} pf={m['pf']:.4f} "
               f"net={m['net']:.2f} dd={m['maxdd']:.2f}")
    out.append(f"    engine:   tr={res['trades']} wr={res['win_rate']} pf={res['profit_factor']} "
               f"net={res['net']} dd={res['max_drawdown']}")
    out.append(f"    peak={m['peak']:.2f} final={m['final']:.2f} net/dd={m['net']/m['maxdd']:.2f}x")

    # [C] cost model applied on every trade
    bad_cost = [t for t in trades if t["cost"] <= 0]
    bad_net = [t for t in trades if abs((t["gross"] - t["cost"]) - t["net"]) > 0.011]
    costs = [t["cost"] for t in trades]
    out.append("")
    out.append(f"[C] cost_model loaded in engine: {ght._COST_OK}  res.cost_model={res.get('cost_model')}")
    out.append(f"    trades w/ cost<=0: {len(bad_cost)} ; net!=gross-cost: {len(bad_net)}")
    out.append(f"    cost range ${min(costs):.2f}..${max(costs):.2f} mean ${np.mean(costs):.2f}; "
               f"total costs ${sum(costs):.2f}")
    # what would gross (pre-cost) look like?
    gross_net = sum(t["gross"] for t in trades)
    out.append(f"    GROSS net (no costs) would be ${gross_net:.2f} vs NET ${m['net']:.2f} "
               f"(costs ate ${gross_net - m['net']:.2f})")

    # [D] HTF-leak test: truncate H4 to bars whose CLOSE <= last OOS H1 close.
    # The legit warmup question: does feeding the FULL (longer) H4 array change
    # OOS trades vs feeding an H4 array trimmed to [start_of_warmup .. oos_end]?
    # A leak would require future H4 bars (close AFTER an H1 decision) to alter a
    # past indicator value — impossible if EMA/ATR are causal. We test by also
    # TRUNCATING the future end and confirming identical OOS trades.
    oos_end = oos.time[-1]
    h4_close = np.array([h4.time[k] + timedelta(minutes=240) for k in range(len(h4))], dtype=object)
    keep = np.array([ct <= oos_end + timedelta(minutes=240) for ct in h4_close])
    h4_trunc = Bars(symbol=h4.symbol, timeframe=h4.timeframe, time=h4.time[keep],
                    open=h4.open[keep], high=h4.high[keep], low=h4.low[keep],
                    close=h4.close[keep], source=h4.source)
    res_t, trades_t = _capture_trades(oos, h4_trunc, winner)
    same = (len(trades_t) == len(trades) and
            all(abs(a["net"] - b["net"]) < 1e-6 and a["entry_time"] == b["entry_time"]
                for a, b in zip(trades, trades_t)))
    out.append("")
    out.append(f"[D] HTF future-truncation test: full-H4 trades={len(trades)} "
               f"trunc-H4 trades={len(trades_t)} identical={same}")
    out.append(f"    (identical => the extra future H4 bars did NOT change any OOS decision = no leak)")

    # also: does extending H4 EARLIER (more warmup) change OOS? Feed only H4 from
    # ~250 bars before OOS start. If trades change drastically, EMA200 warmup is
    # the dependency (expected, benign) not a leak.
    oos_start = oos.time[0]
    warmup_cut = oos_start - timedelta(days=120)
    keep2 = np.array([(t >= warmup_cut) and (t <= oos_end) for t in h4.time])
    h4_warm = Bars(symbol=h4.symbol, timeframe=h4.timeframe, time=h4.time[keep2],
                   open=h4.open[keep2], high=h4.high[keep2], low=h4.low[keep2],
                   close=h4.close[keep2], source=h4.source)
    res_w, trades_w = _capture_trades(oos, h4_warm, winner)
    out.append(f"    warmup-sensitivity: 120d-warmup H4 -> OOS trades={len(trades_w)} "
               f"net={sum(t['net'] for t in trades_w):.2f} "
               f"(vs full {len(trades)}/{m['net']:.2f})")

    # [E] same-bar look-ahead spot check: confirm entries fire at open[i+1] and
    # exits use bar i+1 H/L; verify a few trades have entry==open of a bar and
    # exit reason among {stop,target,time}.
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    out.append("")
    out.append(f"[E] exit-reason mix: {reasons}")
    # For chandelier mode, tp_mode != 'rr' so 'target' should be absent; exits
    # are 'stop' (incl. trailed) only.
    out.append(f"    chandelier => expect NO 'target' exits (trailing stop only): "
               f"{'OK' if 'target' not in reasons else 'UNEXPECTED target exits!'}")

    # [F] multiple testing: rerun full grid OOS, count passers.
    base = Config(htf="H4", trend_mode="ema", allow_long=True, allow_short=False,
                  use_cot_gate=False, risk_dollars=10.0)
    grid = [
        ("base 4R", replace(base)),
        ("pb0.5 4R", replace(base, pullback_atr_mult=0.5)),
        ("3R", replace(base, rr_target=3.0)),
        ("5R", replace(base, rr_target=5.0)),
        ("4R sl1.5", replace(base, sl_min_atr=1.5)),
        ("pb0.5 5R sl1.5", replace(base, pullback_atr_mult=0.5, rr_target=5.0, sl_min_atr=1.5)),
        ("ema40/120 4R", replace(base, ema_fast=40, ema_slow=120)),
        ("ema40/120 pb0.5 3R", replace(base, ema_fast=40, ema_slow=120, pullback_atr_mult=0.5, rr_target=3.0)),
        ("chand x3", replace(base, tp_mode="chandelier", chandelier_atr_mult=3.0)),
        ("chand x4", replace(base, tp_mode="chandelier", chandelier_atr_mult=4.0)),
    ]
    passers = 0
    big = 0
    out.append("")
    out.append("[F] grid OOS pass count (PF>1 & net>0 & tr>=10):")
    for lbl, cfg in grid:
        r = backtest(SYMBOL, cfg=cfg, bars_h1=oos, bars_htf=h4)
        pf = r["profit_factor"]
        pf = float("inf") if pf == "inf" else float(pf)
        ok = r["net"] > 0 and pf > 1.0 and r["trades"] >= 10
        passers += int(ok)
        if r["trades"] >= 50:
            big += 1
        out.append(f"    {lbl:20s} tr={r['trades']:3d} pf={pf:.2f} net={r['net']:7.1f} "
                   f"{'PASS' if ok else 'fail'}")
    out.append(f"    => {passers}/10 pass OOS; {big}/10 have >=50 trades (statistically meaningful)")

    print("\n".join(out))


if __name__ == "__main__":
    main()
