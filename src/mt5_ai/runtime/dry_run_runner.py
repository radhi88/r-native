"""dry_run_runner.py — Full pipeline without placing any trades."""
from __future__ import annotations
import sys, time, logging
from pathlib import Path

import os as _os
_env_root = _os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[3]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path: sys.path.insert(0, p)

from mt5_ai.core.signal_schema import Direction
from mt5_ai.core.decision_router import DecisionRouter
from mt5_ai.core.conflict_guard import ConflictGuard
from mt5_ai.core.risk_manager import RiskManager
from mt5_ai.core.execution_manager import get_execution_manager
from mt5_ai.agents.fractal_agent import FractalAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s %(message)s")
log = logging.getLogger("dry_run_runner")


def _fetch_bars(symbol: str, timeframe: str, n: int = 250):
    try:
        import MetaTrader5 as mt5, pandas as pd
        TF = {"M1":mt5.TIMEFRAME_M1,"M5":mt5.TIMEFRAME_M5,"M15":mt5.TIMEFRAME_M15,
              "H1":mt5.TIMEFRAME_H1,"H4":mt5.TIMEFRAME_H4}
        mt5.initialize()
        rates = mt5.copy_rates_from_pos(symbol, TF[timeframe], 0, n)
        if rates is None: return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time").rename(columns={"tick_volume":"volume"})[["open","high","low","close","volume"]]
        return df
    except Exception as e:
        log.error("fetch_bars %s %s: %s", symbol, timeframe, e); return None


def run_one_cycle(symbol: str = "EURUSDm", timeframe: str = "M5") -> dict:
    log.info("── DRY RUN CYCLE %s %s ──", symbol, timeframe)

    df = _fetch_bars(symbol, timeframe)
    if df is None or len(df) < 50:
        return {"result": "no_data"}

    # 1. Agents produce signals
    agent   = FractalAgent()
    signal  = agent.analyse(df, symbol, timeframe)
    signals = [signal] if signal and signal.direction != Direction.HOLD else []
    log.info("Signals: %d | %s", len(signals), [f"{s.source}:{s.direction.value}:{s.confidence:.2f}" for s in signals])

    # 2. DecisionRouter
    router   = DecisionRouter()
    decision = router.route(signals, symbol, timeframe)
    log.info("Decision: %s confidence=%.2f reason=%s", decision.action.value, decision.confidence, decision.reason)

    if decision.action == Direction.HOLD:
        return {"result": "HOLD", "reason": decision.reason}

    # 3. ConflictGuard
    guard        = ConflictGuard()
    allow, cfls  = guard.check(decision, signals, {})
    if not allow:
        log.warning("ConflictGuard blocked: %s", cfls)
        return {"result": "BLOCKED", "conflicts": cfls}

    # 4. RiskManager
    rm     = RiskManager()
    rd     = rm.validate(decision, symbol)
    if not rd.approved:
        log.warning("RiskManager blocked: %s", rd.reason)
        return {"result": "RISK_BLOCKED", "reason": rd.reason}

    # 5. ExecutionManager (DRY_RUN — no real order)
    from mt5_ai.core.signal_schema import ExecutionRequest
    from mt5_ai.core.magic_registry import ALGORY_MAGIC
    req = ExecutionRequest(
        action=decision.action, symbol=symbol, lot=rd.adjusted_lot,
        sl=0.0, tp=0.0, magic=ALGORY_MAGIC,
        comment=f"DRY|{decision.reason[:20]}",
        risk_decision=rd,
    )
    result = get_execution_manager().execute(req)
    log.info("ExecutionResult: success=%s simulated=%s msg=%s", result.success, result.simulated, result.message)
    return {"result": decision.action.value, "confidence": decision.confidence, "simulated": result.simulated}


if __name__ == "__main__":
    r = run_one_cycle()
    print("\nDRY RUN RESULT:", r)
