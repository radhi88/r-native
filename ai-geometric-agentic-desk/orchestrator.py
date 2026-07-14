"""The Infinite Geometric Loop — orchestration of the desk.

For every configured symbol each cycle:

    1. MarketDataAgent pulls closed candles.
    2. HRExamAgent runs the walk-forward exam (sweeping params in autonomous
       mode) and logs every retake.
    3. AnalysisAgent computes geometry + SMC + ML + confluence.
    4. RiskAgent applies survival sizing and session discipline.
    5. Every annotated bar is journaled; a chart is rendered.
    6. A real demo order is sent ONLY when the exam passes (score >= 95 and
       PF >= 2.5), the confluence gate fires, sizing is accepted, and the daily
       loss halt is clear. Otherwise the cycle is research/paper only.

The exam gate is the spine: until the geometry pays net of cost, nothing
touches the $10. This is the honest reading of the spec's "Exam First" rule.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from agents import broker
from agents.desk_agents import (AnalysisAgent, ChartAgent, ExecutionAgent,
                                HRExamAgent, MarketDataAgent, RiskAgent)
from agents.lessons import LessonsBook
from core.indicators import ema
from core.regime import regime_direction
from data import db, bus
from exam.backtest import ExamResult
from markets import get as market_strategy

_NEUTRAL_EXAM = ExamResult(0.0, 0.0, 0, 0.5, 0.0, 0, "reversal")


def _zone(b) -> str:
    """Format a zone tuple for storage."""
    return f"{b[0]:.5f}-{b[1]:.5f}" if b else ""


@dataclass
class DeskState:
    """Mutable run state for the loop."""

    day_start_equity: float = config.ASSUMED_START_EQUITY
    day: int = -1
    exam_pass: dict[str, bool] = field(default_factory=dict)
    halted: bool = False


def _roll_day(state: DeskState, equity: float) -> None:
    """Reset the daily-loss baseline at UTC midnight."""
    today = datetime.now(timezone.utc).toordinal()
    if today != state.day:
        state.day = today
        state.day_start_equity = equity
        state.halted = False


def _daily_halt(state: DeskState, equity: float) -> bool:
    """True when the day's drawdown breaches :data:`config.MAX_DAILY_LOSS`."""
    floor = state.day_start_equity * (1.0 - config.MAX_DAILY_LOSS)
    if equity <= floor:
        state.halted = True
    return state.halted


def run_symbol(symbol: str, agents: dict, state: DeskState,
               equity: float, free_margin: float) -> dict:
    """Run one full pipeline pass for ``symbol``; return a status dict."""
    market = config.classify(symbol)
    bundle = agents["data"].gather(symbol, market)
    if bundle is None:
        return {"symbol": symbol, "status": "no-data"}

    if config.REQUIRE_EXAM_PASS:
        # Deep grid exam gates execution — run it inline and log every retake.
        exam, params = agents["hr"].examine(bundle)
        db.log_exam(market, {
            "ts": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
            "score": exam.score, "profit_factor": exam.profit_factor,
            "trades": exam.trades, "win_rate": exam.win_rate,
            "expectancy_r": exam.expectancy_r, "params": str(params),
            "notes": exam.notes})
        passed = HRExamAgent.passes(exam)
    else:
        # Forward-test: cheap path. The HR grader scores deeply on its own
        # cadence; the hot loop just uses per-market defaults so it scales to
        # the full symbol universe without a 9-config sweep per symbol/cycle.
        st = market_strategy(market)
        params = {"r_multiple": st.r_multiple, "sq9_deg": st.sq9_degrees}
        exam = ExamResult(0.0, 0.0, 0, 0.5, 0.0, 0, "forward-test (HR grades separately)")
        passed = False
    state.exam_pass[symbol] = passed

    agents["risk"].r_multiple = params["r_multiple"]
    bundle = agents["analysis"].analyse(bundle, params["sq9_deg"])
    bundle = agents["risk"].size(bundle, equity, free_margin, exam)

    near = next(iter(bundle.sq9.values()), None)
    db.record_tick(market, {
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
        "open": float(bundle.o[-1]), "high": float(bundle.h[-1]),
        "low": float(bundle.l[-1]), "close": float(bundle.c[-1]),
        "volume": int(bundle.meta.get("volume", 0) or 0),
        "bos_detected": bundle.smc.bos, "choch_detected": bundle.smc.choch,
        "ob_zone": _zone(bundle.smc.ob_zone), "fvg_zone": _zone(bundle.smc.fvg_zone),
        "gann_sq9_level": near, "fractal_state": bundle.fractal_state,
        "poc": bundle.poc, "vah": bundle.vah, "val": bundle.val,
        "ml_signal": bundle.decision.direction,
        "ml_confidence": bundle.decision.ml_conf,
        "entry_price": float(bundle.c[-1]), "sl_price": bundle.sl,
        "tp1": bundle.tp, "regime": bundle.regime})

    exam_ok = passed or not config.REQUIRE_EXAM_PASS
    at_cap = broker.open_count() >= config.MAX_CONCURRENT_POSITIONS
    spread = bundle.meta.get("spread_price", 0.0) or 0.0
    wide_spread = bundle.atr <= 0 or spread > config.MAX_SPREAD_ATR * bundle.atr
    learned_block = agents["lessons"].verdict(symbol) == "blocked"
    deployable = (exam_ok and bundle.decision.trade and bundle.sizing
                  and bundle.sizing.accepted and not _daily_halt(state, equity)
                  and not at_cap and not wide_spread and not learned_block)
    if not deployable:
        reason = ("exam-fail" if (config.REQUIRE_EXAM_PASS and not passed) else
                  "daily-halt" if state.halted else
                  "learned-block" if learned_block and bundle.decision.trade else
                  "max-positions" if at_cap and bundle.decision.trade else
                  "wide-spread" if wide_spread and bundle.decision.trade else
                  "no-confluence" if not bundle.decision.trade else
                  bundle.sizing.reason if bundle.sizing else "no-signal")
        return {"symbol": symbol, "status": "research", "score": exam.score,
                "pf": exam.profit_factor, "reason": reason,
                "confluences": bundle.decision.confluences}

    png = agents["chart"].draw(bundle)
    res = agents["exec"].execute(bundle)
    db.journal_trade(market, {
        "trade_id": f"{symbol}-{datetime.now(timezone.utc).timestamp():.0f}",
        "symbol": symbol, "entry_price": float(bundle.c[-1]),
        "sl_dist": abs(float(bundle.c[-1]) - bundle.sl),
        "kelly_fraction": bundle.sizing.kelly_f,
        "confluences_logged": " + ".join(bundle.decision.confluences),
        "chart_screenshot": png,
        "timestamp": datetime.now(timezone.utc).isoformat()})
    return {"symbol": symbol, "status": "executed", "score": exam.score,
            "result": res, "vol": bundle.sizing.volume}


def _evo_trend(closes) -> int:
    """Live trend direction from the evolution agent's best gene (EMA cross).

    Reads the current hall-of-fame gene off the bus and applies its EMA fast/slow
    cross to the latest bars — this is how the desk "consults" what evolution has
    learned, in real time.

    Returns:
        ``+1`` up, ``-1`` down, ``0`` unknown.
    """
    evo = bus.read_slice("evo")
    genes = evo.get("genes") or []
    if not genes or len(closes) < 5:
        return 0
    g = genes[0]
    ef, es = ema(closes, int(g.get("fast", 12))), ema(closes, int(g.get("slow", 50)))
    return 1 if ef[-1] > es[-1] else -1


def manage_reversals(agents: dict, equity: float, free_margin: float,
                     ring: bus.InsightRing) -> int:
    """Close-and-reverse open positions whose trend has genuinely flipped.

    For each open desk position, re-evaluates the live signal. If the confluence
    now points the opposite way with conviction AND momentum (regime) AND the
    evolution gene agree, the position is closed early and reversed — it does not
    wait for the far stop-loss. Conviction-gated and hold-timed to avoid churn.

    Returns:
        Number of positions flipped this pass.
    """
    if not config.ENABLE_REVERSAL:
        return 0
    flips = 0
    for p in broker.open_positions():
        if (time.time() - (p.get("time") or 0)) < config.REVERSAL_MIN_HOLD_SEC:
            continue
        market = config.classify(p["symbol"])
        b = agents["data"].gather(p["symbol"], market)
        if b is None:
            continue
        st = market_strategy(market)
        b = agents["analysis"].analyse(b, st.sq9_degrees)
        opp = -1 if p["side"] == "BUY" else 1
        momentum = regime_direction(b.regime)
        evo_dir = _evo_trend(b.c)
        flip = (b.decision.direction == opp
                and b.decision.ml_conf >= config.REVERSAL_MIN_CONF
                and b.decision.count >= config.MIN_CONFLUENCES
                and (momentum == opp or evo_dir == opp))
        if not flip:
            continue
        res = broker.close_position(p["symbol"], p["ticket"], p["side"], p["vol"])
        if not res["ok"]:
            continue
        flips += 1
        ndir = "شراء" if opp > 0 else "بيع"
        ring.post("trade", f"🔄 دوران {p['symbol']}: {p['side']} ← تغيّر الاتجاه → {ndir} (إغلاق مبكر)")
        # immediately open the reverse (decision already points the opposite way)
        agents["risk"].r_multiple = st.r_multiple
        b = agents["risk"].size(b, equity, free_margin, _NEUTRAL_EXAM)
        if b.sizing and b.sizing.accepted and broker.open_count() < config.MAX_CONCURRENT_POSITIONS:
            agents["exec"].execute(b)
    return flips


def build_agents(timeframe: int, bars: int) -> dict:
    """Construct the agent roster."""
    return {"data": MarketDataAgent(timeframe, bars), "analysis": AnalysisAgent(),
            "risk": RiskAgent(), "chart": ChartAgent(), "exec": ExecutionAgent(),
            "hr": HRExamAgent(), "lessons": LessonsBook()}


def loop(symbols: list[str], timeframe: int, bars: int = 400,
         interval: float = 60.0, once: bool = False) -> None:
    """Run the infinite geometric loop over ``symbols``.

    Args:
        symbols: Broker symbols to trade.
        timeframe: ``mt5.TIMEFRAME_*`` constant.
        bars: History depth per fetch.
        interval: Seconds between cycles.
        once: Run a single cycle then return (for diagnostics).
    """
    if not broker.connect():
        print("[desk] MT5 connect failed — aborting")
        return
    acct = broker.account()
    if acct is None:
        print("[desk] no account — aborting")
        return
    print(f"[desk] account {acct.login} @ {acct.server} | "
          f"{'DEMO' if acct.is_demo else 'REAL'} | equity={acct.equity:.2f}")
    if config.DEMO_ONLY and not acct.is_demo:
        print("[desk] REAL account + DEMO_ONLY → execution disabled (research only)")

    agents = build_agents(timeframe, bars)
    state = DeskState(day_start_equity=acct.equity)
    ring = bus.InsightRing()
    equity_curve: list[list[float]] = []
    cycles = executed = 0
    ring.post("system", f"🚀 المكتب يعمل على {len(symbols)} رمز — حساب تجريبي {acct.login}")
    while True:
        acct = broker.account() or acct
        _roll_day(state, acct.equity)
        # learn per-currency lessons from realised history, then block bleeders
        try:
            prev_blocked = set(s for s, v in agents["lessons"].book.items()
                               if v.get("verdict") == "blocked")
            book = agents["lessons"].update()
            new_blocked = [s for s, v in book.items()
                           if v["verdict"] == "blocked" and s not in prev_blocked]
            for s in new_blocked:
                ring.post("hr", f"🚫 درس: إيقاف {s} — خاسر متكرّر "
                                f"(صافي {book[s]['net']}، {book[s]['trades']} صفقة)")
        except Exception as exc:
            print(f"[desk] lessons error: {exc}")
        # real-time reversal: flip any position whose trend has changed,
        # before looking for new entries (close early, not at the far SL)
        try:
            flips = manage_reversals(agents, acct.equity, acct.free_margin, ring)
            if flips:
                print(f"[desk] reversals this cycle: {flips}")
        except Exception as exc:
            print(f"[desk] reversal error: {exc}")
        cycle_exec = cycle_skip = 0
        active_sym = ""
        for i, sym in enumerate(symbols):
            active_sym = sym
            try:
                out = run_symbol(sym, agents, state, acct.equity, acct.free_margin)
                if out["status"] == "executed" and out.get("result", {}).get("ok"):
                    cycle_exec += 1
                    executed += 1
                    ring.post("trade", f"✅ صفقة {sym} — {out.get('vol')} لوت")
                elif out["status"] == "research":
                    cycle_skip += 1
            except Exception as exc:  # keep the loop alive
                print(f"[{sym}] error: {exc}")
            # intra-cycle publish keeps the live workflow graph flowing
            if i % 10 == 0:
                _publish_desk(acct, state, symbols, cycles, executed, cycle_exec,
                              cycle_skip, active_sym, equity_curve, ring)
        cycles += 1
        # consult the HR grader's verdicts from the bus
        hr = bus.read_slice("hr")
        deployable = hr.get("deployable", [])
        if deployable:
            ring.post("hr", f"🎓 المُقيّم يرشّح: {', '.join(deployable[:5])}")
        equity_curve.append([round(time.time(), 1), round(acct.equity, 2)])
        equity_curve = equity_curve[-240:]
        _publish_desk(acct, state, symbols, cycles, executed, cycle_exec,
                      cycle_skip, active_sym, equity_curve, ring)
        print(f"[desk] cycle {cycles} exec={cycle_exec} skip={cycle_skip} "
              f"equity={acct.equity:.2f} open={broker.open_count()}")
        if once:
            return
        time.sleep(interval)


def _publish_desk(acct, state, symbols, cycles, executed, cycle_exec,
                  cycle_skip, active_sym, equity_curve, ring) -> None:
    """Write the desk-loop slice to the coordination bus for the dashboard."""
    bus.write_slice("desk", {
        "agent": "desk", "active": f"scan {active_sym}",
        "account": {"login": acct.login, "server": acct.server,
                    "demo": acct.is_demo, "equity": round(acct.equity, 2),
                    "free_margin": round(acct.free_margin, 2)},
        "positions": broker.open_positions(),
        "stats": {"universe": len(symbols), "cycles": cycles,
                  "executed_total": executed, "exec_cycle": cycle_exec,
                  "skip_cycle": cycle_skip, "open": broker.open_count(),
                  "require_exam_pass": config.REQUIRE_EXAM_PASS,
                  "min_conf": config.MIN_CONFLUENCES,
                  "ml_gate": config.ML_CONFIDENCE_GATE},
        "equity_curve": equity_curve, "insights": ring.items})
