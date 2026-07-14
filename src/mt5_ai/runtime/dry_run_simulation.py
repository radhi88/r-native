"""dry_run_simulation.py — Full pipeline simulation with synthetic TEST_SIGNAL.

Uses dry_run_simulation.yaml config (kill_switch=false, simulate_only=true).
Does NOT connect to MT5. Does NOT send any real order.
All execution logged as DRY_RUN_SIMULATED_EXECUTION_NOT_SENT.
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import os as _os
_env_root = _os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[3]
SRC  = ROOT / "src"
SIM_CONFIG = ROOT / "config" / "dry_run_simulation.yaml"

for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Override config BEFORE any other pipeline imports read it
import mt5_ai.core.config_loader as _cl
_cl.use_config(SIM_CONFIG)

from mt5_ai.core.signal_schema import (
    SignalProposal, Direction, ExecutionRequest,
)
from mt5_ai.core.magic_registry import ALGORY_MAGIC
from mt5_ai.core.decision_router import DecisionRouter
from mt5_ai.core.conflict_guard import ConflictGuard
from mt5_ai.core.risk_manager import RiskManager
from mt5_ai.core.execution_manager import get_execution_manager
from mt5_ai.core.signal_arbiter import SignalArbiter
from mt5_ai.core.structured_logger import (
    log_signal, log_decision, log_conflict,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
log = logging.getLogger("dry_run_simulation")

SYMBOL    = "XAUUSDm"
TIMEFRAME = "M5"
LOT       = 0.01


def _make_synthetic_signals() -> list[SignalProposal]:
    """Create synthetic agent signals: no MT5 connection, no real data."""
    fractal = SignalProposal(
        source="fractal_agent",
        strategy_id="FRIDAY_DRY_RUN_FRACTAL_TEST",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        direction=Direction.BUY,
        confidence=0.92,
        strength=2.1,
        reason="synthetic_fractal_test_signal:dry_run_simulation",
        features={"test": 1.0, "synthetic": 1.0, "swing_bias": 1.0},
        can_execute=False,
        desired_magic=ALGORY_MAGIC,
        priority=5,
        tags=["test", "synthetic", "dry_run", "fractal"],
    )
    smc = SignalProposal(
        source="smc_agent",
        strategy_id="FRIDAY_DRY_RUN_SMC_TEST",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        direction=Direction.BUY,
        confidence=0.88,
        strength=2.0,
        reason="synthetic_smc_test_signal:dry_run_simulation",
        features={"test": 1.0, "synthetic": 1.0, "entry_confirmed": 1.0},
        can_execute=False,
        desired_magic=ALGORY_MAGIC,
        priority=5,
        tags=["test", "synthetic", "dry_run", "smc"],
    )
    for sig in (fractal, smc):
        log_signal(sig.source, sig.symbol, sig.timeframe, sig.direction.value,
                   sig.confidence, sig.reason)
        log.info("[STEP 1] SYNTHETIC_SIGNAL: %s %s %s dir=%s conf=%.2f",
                 sig.source, sig.symbol, sig.timeframe, sig.direction.value, sig.confidence)
    return [fractal, smc]


def run_simulation() -> dict:
    log.info("=" * 70)
    log.info("DRY_RUN_EXECUTION_SIMULATION START")
    log.info("Config: %s", SIM_CONFIG)
    log.info("kill_switch=%s allow_live_trading=%s mode=%s",
             _cl.is_kill_switch(), _cl.is_live_allowed(), _cl.load().get("runtime", {}).get("mode"))
    log.info("=" * 70)

    # ── Step 1: Synthetic agent signals ────────────────────────────────────
    signals = _make_synthetic_signals()

    # ── Step 2: SignalArbiter ──────────────────────────────────────────────
    arbiter = SignalArbiter()
    arb = arbiter.decide(signals, SYMBOL, TIMEFRAME)
    log.info("[STEP 2] SignalArbiter: action=%s conf=%.2f reason=%s",
             arb.final_direction.value, arb.final_confidence, arb.reason)
    arb_signal = arb.to_signal_proposal()
    if arb_signal is None:
        log.error("SignalArbiter returned HOLD in simulation: %s", arb.reason)
        return {"status": "ARBITER_HOLD", "reason": arb.reason}

    # ── Step 3: DecisionRouter ─────────────────────────────────────────────
    router   = DecisionRouter()
    decision = router.route([arb_signal], SYMBOL, TIMEFRAME)
    log.info("[STEP 3] DecisionRouter: action=%s conf=%.2f reason=%s",
             decision.action.value, decision.confidence, decision.reason)
    log_decision(decision.action.value, SYMBOL, TIMEFRAME, decision.confidence,
                 [arb_signal.source], [], decision.reason)

    if decision.action == Direction.HOLD:
        return {"status": "ROUTER_HOLD", "reason": decision.reason}

    # ── Step 4: ConflictGuard ──────────────────────────────────────────────
    guard       = ConflictGuard()
    allow, cfls = guard.check(decision, [arb_signal], {})
    log.info("[STEP 4] ConflictGuard: allow=%s conflicts=%s", allow, cfls)
    log_conflict(SYMBOL, "simulation_check", str(cfls), not allow)

    if not allow:
        return {"status": "CONFLICT_BLOCKED", "conflicts": cfls}

    # ── Step 5: RiskManager ────────────────────────────────────────────────
    rm = RiskManager()
    rd = rm.validate(decision, SYMBOL, spread_points=5, open_positions=0)
    log.info("[STEP 5] RiskManager: approved=%s lot=%.2f reason=%s",
             rd.approved, rd.adjusted_lot, rd.reason)

    if not rd.approved:
        log.error("RiskManager blocked in simulation: %s", rd.reason)
        return {"status": "RISK_BLOCKED", "reason": rd.reason}

    # ── Step 6: PositionManager (not needed for new entry) ─────────────────
    log.info("[STEP 6] PositionManager: N/A for new entry signal")

    # ── Step 7: ExecutionManager ───────────────────────────────────────────
    req = ExecutionRequest(
        action=decision.action,
        symbol=SYMBOL,
        lot=LOT,
        sl=1900.0,
        tp=1950.0,
        magic=ALGORY_MAGIC,
        comment="SIM_TEST|dry_run_simulation",
        risk_decision=rd,
    )
    exec_mgr = get_execution_manager()
    result   = exec_mgr.execute(req)
    log.info("[STEP 7] ExecutionManager: success=%s simulated=%s message=%s",
             result.success, result.simulated, result.message)

    # ── Step 8: MT5Gateway boundary ────────────────────────────────────────
    log.info("[STEP 8] MT5Gateway: NOT called (DRY_RUN blocks before gateway)")
    log.info("=" * 70)
    log.info("DRY_RUN_EXECUTION_SIMULATION COMPLETE")
    log.info("Real order sent: NO")
    log.info("MT5Gateway called: NO")
    log.info("ExecutionManager message: %s", result.message)
    log.info("=" * 70)

    return {
        "status":           "SIMULATION_COMPLETE",
        "signals":          [f"{s.source}:{s.direction.value}:{s.confidence}" for s in signals],
        "arbiter":          f"{arb.final_direction.value}:{arb.final_confidence:.2f}",
        "decision":         f"{decision.action.value}:{decision.confidence:.2f}",
        "conflict_guard":   "PASS",
        "risk_approved":    rd.approved,
        "lot":              LOT,
        "exec_success":     result.success,
        "exec_simulated":   result.simulated,
        "exec_message":     result.message,
        "real_order_sent":  False,
        "mt5_gateway_called": False,
    }


def verify_logs() -> dict[str, bool]:
    log_dir = ROOT / "logs"
    files = {
        "signal_log.jsonl":    log_dir / "signal_log.jsonl",
        "decision_log.jsonl":  log_dir / "decision_log.jsonl",
        "conflict_log.jsonl":  log_dir / "conflict_log.jsonl",
        "risk_log.jsonl":      log_dir / "risk_log.jsonl",
        "execution_log.jsonl": log_dir / "execution_log.jsonl",
    }
    results = {}
    for name, path in files.items():
        exists = path.exists() and path.stat().st_size > 0
        results[name] = exists
        log.info("LOG CHECK %s: %s (%d bytes)",
                 name, "OK" if exists else "MISSING",
                 path.stat().st_size if path.exists() else 0)
    return results


if __name__ == "__main__":
    result = run_simulation()
    print("\n── SIMULATION RESULT ──────────────────────────────────────")
    for k, v in result.items():
        print(f"  {k:25s}: {v}")
    print()

    logs = verify_logs()
    print("── LOG VERIFICATION ───────────────────────────────────────")
    all_ok = True
    for name, ok in logs.items():
        print(f"  {'OK' if ok else 'MISSING':7s}  logs/{name}")
        if not ok:
            all_ok = False
    print()
    print("SIMULATION STATUS:", "PASS" if result["status"] == "SIMULATION_COMPLETE" and all_ok else "FAIL")

    # Restore default config
    _cl.reset_config()
