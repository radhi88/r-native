"""Safe runner service for fixed-cycle dry-run execution."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.paths import config_dir
from qader_app.storage.audit_log import log_action


class RunnerService:
    def __init__(self, guard: PermissionsGuard | None = None):
        self.guard = guard or PermissionsGuard()
        self.running = False
        self.last_result: dict[str, Any] = {}

    def emergency_stop(self) -> dict[str, Any]:
        self.running = False
        try:
            from mt5_ai.core.kill_switch import activate

            activate("qader_emergency_stop")
        except Exception as exc:
            log_action("emergency_stop_kill_switch_failed", None, False, str(exc), "runner_service")
        log_action("emergency_stop", None, True, "scanner_runner_voice_stopped", "runner_service")
        return {"stopped": True, "message": "Emergency stop applied."}

    def run_fixed_dry_run(self, symbol: str, timeframe: str = "M1", cycles: int = 1, confirmed_long: bool = False) -> dict[str, Any]:
        perm = self.guard.check("can_run_dry_run", "run_fixed_dry_run", "runner_service")
        if not perm.allowed:
            return {"ok": False, "reason": perm.reason, "real_order_send_calls": 0}
        cycles = max(1, min(int(cycles), 100))
        if cycles > 50 and not confirmed_long:
            return {"ok": False, "reason": "long_session_requires_confirmation", "real_order_send_calls": 0}

        import MetaTrader5 as mt5
        import mt5_ai.core.config_loader as config_loader
        from mt5_ai.agents import GovernorAgent, RiskCloseAgent
        from mt5_ai.core.conflict_guard import ConflictGuard
        from mt5_ai.core.decision_router import DecisionRouter
        from mt5_ai.core.execution_manager import get_execution_manager
        from mt5_ai.core.position_manager import PositionManager
        from mt5_ai.core.risk_manager import RiskManager
        from mt5_ai.core.signal_arbiter import SignalArbiter
        from mt5_ai.runtime import main_loop

        config_loader.use_config(config_dir() / "dry_run_simulation.yaml")
        real_order_send_calls = {"count": 0}
        original_order_send = getattr(mt5, "order_send", None)

        def blocked_order_send(*args, **kwargs):
            real_order_send_calls["count"] += 1
            raise RuntimeError("Qader dry-run guard blocked mt5.order_send")

        if original_order_send is not None:
            mt5.order_send = blocked_order_send

        counts = Counter()
        errors = []
        self.running = True
        try:
            if not mt5.initialize():
                return {"ok": False, "reason": f"mt5_initialize_failed:{mt5.last_error()}", "real_order_send_calls": 0}
            router = DecisionRouter()
            guard = ConflictGuard()
            risk = RiskManager()
            pos = PositionManager()
            exec_mgr = get_execution_manager()
            governor = GovernorAgent()
            risk_closer = RiskCloseAgent()
            arbiter = SignalArbiter()
            for _ in range(cycles):
                if not self.running:
                    break
                try:
                    positions = list(mt5.positions_get() or [])
                    result = main_loop.run_cycle(
                        mt5, symbol, timeframe, router, guard, risk, pos,
                        exec_mgr, governor, risk_closer, positions, arbiter=arbiter,
                    )
                    counts[str(result.get("result"))] += 1
                except Exception as exc:
                    errors.append(str(exc))
            self.last_result = {
                "ok": not errors,
                "symbol": symbol,
                "timeframe": timeframe,
                "cycles_completed": sum(counts.values()),
                "result_counts": dict(counts),
                "errors": errors,
                "real_order_send_calls": real_order_send_calls["count"],
                "is_dry_run": config_loader.is_dry_run(),
                "is_live_allowed": config_loader.is_live_allowed(),
            }
            log_action("run_fixed_dry_run", "can_run_dry_run", True, "completed", "runner_service", result=self.last_result)
            return self.last_result
        finally:
            self.running = False
            try:
                mt5.shutdown()
            except Exception:
                pass
            if original_order_send is not None:
                mt5.order_send = original_order_send

    def last_result_json(self) -> str:
        return json.dumps(self.last_result, indent=2, ensure_ascii=False, default=str)

