"""main_loop.py — Production pipeline loop.

Single execution path:
  Agents → SignalArbiter → DecisionRouter → ConflictGuard → RiskManager → ExecutionManager

Position management:
  GovernorAgent + RiskCloseAgent → PositionManager → ExecutionManager

Run: python -m mt5_ai.runtime.main_loop --symbol EURUSDm --timeframe M5
"""
from __future__ import annotations
import argparse
import logging
import sys
import time
from pathlib import Path

import os as _os
_env_root = _os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[3]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import mt5_ai.core.config_loader as _cl
from mt5_ai.core.config_loader import load as cfg_load, is_kill_switch
from mt5_ai.core.signal_schema import Direction, ExecutionRequest
from mt5_ai.core.magic_registry import ALGORY_MAGIC
from mt5_ai.core.decision_router import DecisionRouter
from mt5_ai.core.conflict_guard import ConflictGuard
from mt5_ai.core.risk_manager import RiskManager
from mt5_ai.core.position_manager import PositionManager
from mt5_ai.core.execution_manager import get_execution_manager
from mt5_ai.core.signal_arbiter import SignalArbiter
from mt5_ai.core.indicators import atr as calc_atr
from mt5_ai.agents import (
    FractalAgent, SmcAgent,
    IctSweepAgent, GovernorAgent, RiskCloseAgent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
log = logging.getLogger("main_loop")


def _fetch_bars(mt5, symbol: str, timeframe: str, n: int = 300):
    import pandas as pd
    TF = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    }
    rates = mt5.copy_rates_from_pos(symbol, TF[timeframe], 0, n)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def _position_side(mt5, pos) -> str:
    buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0)
    return "BUY" if int(getattr(pos, "type", buy_type)) == int(buy_type) else "SELL"


def _open_position_directions(mt5, positions: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for pos in positions:
        try:
            out[str(pos.symbol)] = _position_side(mt5, pos)
        except Exception:
            continue
    return out


def _spread_points(mt5, symbol: str) -> float:
    try:
        info = mt5.symbol_info(symbol)
        if info is not None and getattr(info, "spread", None) is not None:
            return float(info.spread)
    except Exception:
        pass
    return float("inf")


def _daily_loss_pct(mt5) -> float:
    try:
        info = mt5.account_info()
        if info is None:
            return 0.0
        balance = float(getattr(info, "balance", 0.0) or 0.0)
        equity = float(getattr(info, "equity", balance) or balance)
        if balance <= 0:
            return 0.0
        return max(0.0, (balance - equity) / balance * 100.0)
    except Exception:
        return 0.0


def run_cycle(mt5, symbol: str, timeframe: str,
              router: DecisionRouter, guard: ConflictGuard,
              risk_mgr: RiskManager, pos_mgr: PositionManager,
              exec_mgr, governor: GovernorAgent, risk_closer: RiskCloseAgent,
              active_positions: list,
              arbiter: SignalArbiter | None = None) -> dict:

    if is_kill_switch():
        log.warning("Kill switch active — skipping cycle")
        return {"result": "KILL_SWITCH"}

    # ── Position management (risk_closer first, then governor) ─────────────
    for req in risk_closer.evaluate_positions(active_positions):
        exec_req = pos_mgr.handle(req)
        if exec_req:
            exec_mgr.execute(exec_req)

    for req in governor.evaluate_positions(
        active_positions,
        get_signal_fn=lambda sym: None,  # governor uses own signal in full impl
        genes={},
        cfg=cfg_load().get("risk", {}),
    ):
        exec_req = pos_mgr.handle(req)
        if exec_req:
            exec_mgr.execute(exec_req)

    # ── Entry signal pipeline ───────────────────────────────────────────────
    df = _fetch_bars(mt5, symbol, timeframe)
    if df is None or len(df) < 50:
        return {"result": "no_data"}

    # Collect raw signals from all entry agents
    raw_signals = []
    for agent in (FractalAgent(), SmcAgent(), IctSweepAgent()):
        sig = agent.analyse(df, symbol, timeframe)
        if sig:
            raw_signals.append(sig)

    # ── SignalArbiter: resolve conflict before ConflictGuard ────────────────
    active_arbiter = arbiter or SignalArbiter()
    arb = active_arbiter.decide(raw_signals, symbol, timeframe)

    if arb.final_direction == Direction.HOLD:
        log.info("Arbiter HOLD: %s", arb.reason)
        return {
            "result":           "ARBITER_HOLD",
            "reason":           arb.reason,
            "agent_conflict":   arb.agent_conflict,
            "final_confidence": arb.final_confidence,
        }

    # Single arbiter signal passed to router — no mixed directions remain
    arb_signal = arb.to_signal_proposal()
    decision   = router.route([arb_signal], symbol, timeframe)
    log.info("Decision: %s conf=%.2f reason=%s",
             decision.action.value, decision.confidence, decision.reason)

    if decision.action == Direction.HOLD:
        return {"result": "HOLD", "reason": decision.reason}

    # ConflictGuard — still active, checks remaining rules (can_execute, low-conf, etc.)
    open_position_directions = _open_position_directions(mt5, active_positions)
    allow, cfls = guard.check(decision, [arb_signal], open_position_directions)
    if not allow:
        return {"result": "CONFLICT_BLOCKED", "conflicts": cfls}

    rd = risk_mgr.validate(
        decision,
        symbol,
        spread_points=_spread_points(mt5, symbol),
        open_positions=len(active_positions),
        daily_loss_pct=_daily_loss_pct(mt5),
    )
    if not rd.approved:
        return {"result": "RISK_BLOCKED", "reason": rd.reason}

    # ATR-based SL/TP — required by ExecutionRequest.is_valid()
    atr = calc_atr(df, period=14)
    last_close = float(df["close"].iloc[-1])
    sl_dist = max(atr * 1.5, 0.0001)
    if decision.action == Direction.BUY:
        sl = round(last_close - sl_dist, 5)
        tp = round(last_close + sl_dist * 2.0, 5)
    else:
        sl = round(last_close + sl_dist, 5)
        tp = round(last_close - sl_dist * 2.0, 5)

    cfg = cfg_load()
    exec_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
    magic_number = int(exec_cfg.get("magic_number") or ALGORY_MAGIC)
    comment_prefix = str(exec_cfg.get("comment") or "ARB")
    req = ExecutionRequest(
        action=decision.action, symbol=symbol, lot=rd.adjusted_lot,
        sl=sl, tp=tp, magic=magic_number,
        comment=f"{comment_prefix}|ARB|{arb.reason[:25]}",
        risk_decision=rd,
        confidence=float(arb.final_confidence),
        signal_arbiter_passed=True,
        conflict_guard_passed=True,
    )
    result = exec_mgr.execute(req)
    log.info("Executed: success=%s simulated=%s msg=%s",
             result.success, result.simulated, result.message)
    return {
        "result":     decision.action.value,
        "confidence": arb.final_confidence,
        "simulated":  result.simulated,
        "success":    result.success,
        "execution_message": result.message,
        "retcode":    result.retcode,
        "order":      result.order,
        "sl":         sl, "tp": tp,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",    default="EURUSDm")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--interval",  type=float, default=30.0)
    parser.add_argument("--cycles",    type=int,   default=0, help="0 = run forever")
    parser.add_argument("--config",    default=None, help="override config YAML path")
    args = parser.parse_args()

    if args.config:
        _cl.use_config(Path(args.config).expanduser().resolve())

    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            log.error("MT5 init failed: %s", mt5.last_error())
            return 1
    except ImportError:
        log.warning("MetaTrader5 not available — cannot run main_loop without MT5")
        return 1

    router      = DecisionRouter()
    guard       = ConflictGuard()
    risk_mgr    = RiskManager()
    pos_mgr     = PositionManager()
    exec_mgr    = get_execution_manager()
    governor    = GovernorAgent()
    risk_closer = RiskCloseAgent()
    arbiter     = SignalArbiter()

    log.info("Main loop started | %s %s | interval=%.0fs", args.symbol, args.timeframe, args.interval)

    cycle = 0
    consecutive_errors = 0
    started_at = time.monotonic()
    last_heartbeat = started_at
    while True:
        try:
            positions = list(mt5.positions_get() or [])
            result = run_cycle(
                mt5=mt5, symbol=args.symbol, timeframe=args.timeframe,
                router=router, guard=guard, risk_mgr=risk_mgr, pos_mgr=pos_mgr,
                exec_mgr=exec_mgr, governor=governor, risk_closer=risk_closer,
                active_positions=positions, arbiter=arbiter,
            )
            log.info("Cycle %d result: %s", cycle, result)
            consecutive_errors = 0
            cycle += 1
            now = time.monotonic()
            if now - last_heartbeat >= 60:
                log.info("Heartbeat: cycle=%d uptime=%.0fs", cycle, now - started_at)
                last_heartbeat = now
            if args.cycles and cycle >= args.cycles:
                break
        except KeyboardInterrupt:
            log.info("Interrupted")
            break
        except Exception as exc:
            log.exception("Cycle error: %s", exc)
            consecutive_errors += 1
            if consecutive_errors >= 5:
                log.critical("5 consecutive cycle errors — activating kill switch")
                from mt5_ai.core.kill_switch import activate
                activate("consecutive_failures")
                break

        time.sleep(args.interval)

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
