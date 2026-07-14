"""Entrypoint for the AI Geometric Agentic Desk.

Usage:
    python run.py --selftest                 # offline: full pipeline, no MT5, no orders
    python run.py --once --symbols XAUUSDm    # one live cycle (demo-guarded)
    python run.py --symbols XAUUSDm BTCUSDm    # the infinite loop

The desk roots itself on sys.path so the hyphenated package directory imports
cleanly. Execution is demo-only and exam-gated; ``--selftest`` never touches a
broker and is safe to run anywhere.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import config


def _tf(name: str) -> int:
    """Resolve a timeframe name to an MT5 constant (falling back to ints)."""
    try:
        import MetaTrader5 as mt5
        return {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}.get(name, mt5.TIMEFRAME_M5)
    except Exception:
        return {"M1": 1, "M5": 5, "M15": 15, "H1": 16385}.get(name, 5)


def _synthetic(n: int = 600, seed: int = 7) -> dict[str, np.ndarray]:
    """Generate a deterministic synthetic OHLC series for the self-test."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.0, n).cumsum()
    base = 2000.0 + steps + 8.0 * np.sin(np.arange(n) / 30.0)
    o = base + rng.normal(0, 0.3, n)
    c = base + rng.normal(0, 0.3, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.6, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.6, n))
    return {"open": o, "high": h, "low": l, "close": c}


def selftest() -> int:
    """Run the entire pipeline offline on synthetic data; print a report."""
    from agents.desk_agents import (AnalysisAgent, ChartAgent, HRExamAgent,
                                    RiskAgent, Bundle)
    d = _synthetic()
    meta = {"tick_size": 0.01, "tick_value": 1.0, "vol_min": 0.01,
            "vol_step": 0.01, "spread_price": 0.30, "margin_lot": 5.0,
            "point": 0.01, "digits": 2, "volume": 100}
    b = Bundle("XAUUSDm-SIM", "gold", d["open"], d["high"], d["low"], d["close"], meta)

    hr, an, rk, ch = HRExamAgent(), AnalysisAgent(), RiskAgent(), ChartAgent()
    print("=== AI Geometric Agentic Desk — SELF TEST (offline) ===")
    exam, params = hr.examine(b)
    print(f"EXAM  : score={exam.score:.1f}/100  PF={exam.profit_factor:.2f}  "
          f"{exam.notes}")
    print(f"PARAMS: {params}")
    print(f"GATE  : passes={HRExamAgent.passes(exam)} "
          f"(needs score>={config.EXAM_PASS_SCORE} & PF>={config.PF_TARGET})")

    rk.r_multiple = params["r_multiple"]
    b = an.analyse(b, params["sq9_deg"])
    print(f"SIGNAL: dir={b.decision.direction} conf={b.decision.count} "
          f"{b.decision.confluences} trade={b.decision.trade}")
    b = rk.size(b, config.ASSUMED_START_EQUITY, 10.0, exam)
    print(f"SIZING: {b.sizing.reason} (accepted={b.sizing.accepted})")

    out = os.path.join(os.path.dirname(__file__), "data", "selftest_chart.png")
    with open(out, "wb") as fh:
        fh.write(ch.draw(b))
    print(f"CHART : rendered → {out}")
    print("VERDICT: pipeline runs end-to-end. Deploy gate correctly "
          f"{'OPEN' if HRExamAgent.passes(exam) else 'CLOSED (no edge net of cost)'}.")
    return 0


def main() -> int:
    """Parse arguments and dispatch to self-test or the live loop."""
    p = argparse.ArgumentParser(description="AI Geometric Agentic Desk")
    p.add_argument("--selftest", action="store_true", help="offline pipeline test")
    p.add_argument("--hr", action="store_true", help="run the autonomous HR grading loop")
    p.add_argument("--evo", action="store_true", help="run the evolution agent")
    p.add_argument("--dashboard", action="store_true", help="serve the live web dashboard")
    p.add_argument("--once", action="store_true", help="single live cycle")
    p.add_argument("--symbols", nargs="*", default=["XAUUSDm"], help="symbols")
    p.add_argument("--all", action="store_true", help="trade every tradable MT5 symbol")
    p.add_argument("--tf", default="M5", help="timeframe (M1/M5/M15/H1/H4/D1)")
    p.add_argument("--interval", type=float, default=60.0, help="loop seconds")
    p.add_argument("--bars", type=int, default=400, help="history depth")
    args = p.parse_args()

    if args.selftest:
        return selftest()
    if args.dashboard:
        from dashboard.live_server import serve
        serve()
        return 0

    symbols = args.symbols
    if args.all:
        from agents import broker
        broker.connect()
        symbols = broker.list_symbols(max_rel_spread=config.MAX_REL_SPREAD)
        print(f"[run] universe: {len(symbols)} tradable MT5 symbols "
              f"(spread-pruned, rel<{config.MAX_REL_SPREAD:.1%})")
    args.symbols = symbols

    if args.hr:
        from agents.hr_manager import run as hr_run
        hr_run(args.symbols, _tf(args.tf), args.bars, interval=300.0, once=args.once)
        return 0
    if args.evo:
        from agents.evolution import run as evo_run
        evo_run(args.symbols, _tf(args.tf), args.bars, interval=120.0, once=args.once)
        return 0
    from orchestrator import loop
    loop(args.symbols, _tf(args.tf), args.bars, args.interval, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
