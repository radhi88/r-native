"""REAL_CONTROLLED_MODE orchestration for Qader.

This service never enables live trading by itself. It runs the lockdown check,
stores the typed GUI unlock state, validates gates, and starts a bounded run only
after the GUI passes an explicit final confirmation.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.paths import app_root, config_dir
from qader_app.storage.audit_log import log_action
from qader_app.storage.settings_store import PermissionsStore, REAL_UNLOCK_PHRASE, SettingsStore


class RealModeService:
    def __init__(self, permissions: PermissionsStore | None = None, guard: PermissionsGuard | None = None):
        self.permissions = permissions or PermissionsStore()
        self.guard = guard or PermissionsGuard(self.permissions)
        self.settings = SettingsStore()

    @property
    def config_path(self) -> Path:
        return config_dir() / "real_controlled_mode.yaml"

    @staticmethod
    def unlock_phrase() -> str:
        return REAL_UNLOCK_PHRASE

    def _python_command(self) -> str:
        venv_python = app_root() / ".venv" / "Scripts" / "python.exe"
        return str(venv_python if venv_python.exists() else Path(sys.executable))

    @staticmethod
    def _parse_lockdown_output(stdout: str, exit_code: int) -> dict[str, Any]:
        open_match = re.search(r"Open positions\s*:\s*(\d+)", stdout, re.IGNORECASE)
        pending_match = re.search(r"Pending orders\s*:\s*(\d+)", stdout, re.IGNORECASE)
        open_positions = int(open_match.group(1)) if open_match else 1
        pending_orders = int(pending_match.group(1)) if pending_match else 1
        external = "EXTERNAL" in stdout and (open_positions > 0 or pending_orders > 0)
        return {
            "exit_code": int(exit_code),
            "account_info_readable": "[ERROR] mt5.account_info()" not in stdout and "ACCOUNT" in stdout,
            "open_positions": open_positions,
            "pending_orders": pending_orders,
            "external_magic0_exposure": external,
            "clean": exit_code == 0 and open_positions == 0 and pending_orders == 0 and not external,
        }

    def run_lockdown_check(self) -> dict[str, Any]:
        script = app_root() / "verify_mt5_lockdown.py"
        command = [self._python_command(), str(script)]
        if not script.exists():
            result = {
                "ok": False,
                "exit_code": 2,
                "command": " ".join(command),
                "stdout": "",
                "stderr": "verify_mt5_lockdown.py missing",
                "account_info_readable": False,
                "open_positions": 1,
                "pending_orders": 1,
                "external_magic0_exposure": True,
                "clean": False,
            }
            log_action("real_mode_lockdown_check", None, False, "script_missing", "real_mode_service", result=result)
            return result

        try:
            completed = subprocess.run(
                command,
                cwd=app_root(),
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            parsed = self._parse_lockdown_output(completed.stdout, completed.returncode)
            result = {
                "ok": parsed["clean"],
                "command": " ".join(command),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                **parsed,
            }
        except Exception as exc:
            result = {
                "ok": False,
                "exit_code": 2,
                "command": " ".join(command),
                "stdout": "",
                "stderr": str(exc),
                "account_info_readable": False,
                "open_positions": 1,
                "pending_orders": 1,
                "external_magic0_exposure": True,
                "clean": False,
            }
        log_action(
            "real_mode_lockdown_check",
            None,
            bool(result.get("ok")),
            "clean" if result.get("ok") else "not_clean_or_unavailable",
            "real_mode_service",
            result={k: v for k, v in result.items() if k not in {"stdout", "stderr"}},
        )
        return result

    def unlock(self, phrase: str) -> dict[str, Any]:
        lockdown = self.run_lockdown_check()
        data = self.permissions.unlock_real_controlled_mode(phrase, lockdown)
        ok = bool(data.get("can_place_live_orders")) and bool(data.get("_real_controlled_mode_unlocked"))
        self.settings.save(
            {
                "mode": "real_controlled_mode" if ok else "observe_only",
                "safety_status": "REAL_CONTROLLED_MODE_UNLOCKED" if ok else "REAL_CONTROLLED_MODE_LOCKED",
            }
        )
        log_action(
            "real_mode_unlock",
            "can_place_live_orders",
            ok,
            "typed_phrase_and_clean_lockdown" if ok else str(data.get("_unlock_error", "unlock_failed")),
            "real_mode_service",
            result={k: v for k, v in data.items() if k not in {"_locked"}},
        )
        return {"ok": ok, "permissions": data, "lockdown": lockdown}

    def lock(self, reason: str = "manual_lock") -> dict[str, Any]:
        data = self.permissions.lock_real_controlled_mode(reason)
        self.settings.save({"mode": "observe_only", "safety_status": "REAL_CONTROLLED_MODE_LOCKED"})
        log_action("real_mode_lock", "can_place_live_orders", False, reason, "real_mode_service")
        return data

    def account_details(self) -> dict[str, Any]:
        try:
            import MetaTrader5 as mt5

            if mt5.account_info() is None:
                mt5.initialize()
            info = mt5.account_info()
            positions = list(mt5.positions_get() or [])
            orders = list(mt5.orders_get() or [])
            if info is None:
                return {"ok": False, "message": f"account_info_unavailable:{mt5.last_error()}"}
            return {
                "ok": True,
                "login": getattr(info, "login", None),
                "server": getattr(info, "server", ""),
                "balance": getattr(info, "balance", 0.0),
                "equity": getattr(info, "equity", 0.0),
                "margin": getattr(info, "margin", 0.0),
                "open_positions": len(positions),
                "pending_orders": len(orders),
                "external_magic0_exposure": any(int(getattr(x, "magic", -1) or -1) == 0 for x in positions + orders),
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def _validation_request(self):
        from mt5_ai.core import config_loader
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC
        from mt5_ai.core.signal_schema import Direction, ExecutionRequest, RiskDecision

        cfg = config_loader.load()
        symbol = str(cfg.get("symbol") or cfg.get("symbols", {}).get("active", ["XAUUSDm"])[0])
        lot = float(cfg.get("risk", {}).get("fixed_lot", 0.01) or 0.01)
        confidence = float(cfg.get("confidence", {}).get("min_decision_confidence", 0.55) or 0.55)
        price = 3000.0
        try:
            import MetaTrader5 as mt5

            if mt5.account_info() is None:
                mt5.initialize()
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                price = float(tick.ask)
        except Exception:
            pass
        return ExecutionRequest(
            action=Direction.BUY,
            symbol=symbol,
            lot=lot,
            price=price,
            sl=max(0.01, price - 1.0),
            tp=price + 2.0,
            magic=QADER_REAL_CONTROLLED_MAGIC,
            comment="QADER_DEMO|ARB|validation",
            risk_decision=RiskDecision(approved=True, reason="validation_only", max_lot=lot, adjusted_lot=lot),
            confidence=confidence,
            signal_arbiter_passed=True,
            conflict_guard_passed=True,
        )

    def validation_mode_without_order(self) -> dict[str, Any]:
        from mt5_ai.core import config_loader
        from mt5_ai.core.execution_manager import get_execution_manager

        old_config = config_loader.active_config_path()
        config_loader.use_config(self.config_path)
        try:
            manager = get_execution_manager()
            report = manager.validate_real_controlled_request(self._validation_request())
        finally:
            config_loader.use_config(old_config)
        log_action(
            "real_mode_validation_only",
            "can_place_live_orders",
            bool(report.get("allowed")),
            "no_order_send_called",
            "real_mode_service",
            result=report,
        )
        return report

    def start_real_controlled_run(self, final_confirmation: bool = False) -> dict[str, Any]:
        if not final_confirmation:
            log_action("real_mode_start_denied", "can_place_live_orders", False, "final_gui_confirmation_required", "real_mode_service")
            return {"ok": False, "reason": "final_gui_confirmation_required"}

        perm = self.guard.check("can_place_live_orders", "start_real_controlled_run", "real_mode_service")
        if not perm.allowed:
            return {"ok": False, "reason": perm.reason}

        lockdown = self.run_lockdown_check()
        if not lockdown.get("ok"):
            self.lock("lockdown_failed_before_run")
            return {"ok": False, "reason": "lockdown_failed_before_run", "lockdown": lockdown}

        from mt5_ai.core import config_loader
        from mt5_ai.core.conflict_guard import ConflictGuard
        from mt5_ai.core.decision_router import DecisionRouter
        from mt5_ai.core.execution_manager import get_execution_manager
        from mt5_ai.core.position_manager import PositionManager
        from mt5_ai.core.risk_manager import RiskManager
        from mt5_ai.core.signal_arbiter import SignalArbiter
        from mt5_ai.agents import GovernorAgent, RiskCloseAgent
        from mt5_ai.runtime import main_loop

        old_config = config_loader.active_config_path()
        config_loader.use_config(self.config_path)
        cfg = config_loader.load()
        symbol = str(cfg.get("symbol") or "XAUUSDm")
        timeframe = str(cfg.get("timeframe") or "M1")
        max_cycles = int(cfg.get("max_cycles") or cfg.get("runtime", {}).get("max_cycles") or 20)
        max_runtime_minutes = float(cfg.get("max_runtime_minutes") or cfg.get("runtime", {}).get("max_runtime_minutes") or 10)
        execution_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        max_market_orders = int(execution_cfg.get("max_market_orders_per_run", cfg.get("max_market_orders_per_run", 3)) or 3)
        if max_cycles <= 0:
            max_cycles = max(1, int(max_runtime_minutes * 60))
        results: list[dict[str, Any]] = []
        started = time.monotonic()
        successful_orders = 0
        try:
            import MetaTrader5 as mt5

            if not mt5.initialize():
                return {"ok": False, "reason": f"mt5_initialize_failed:{mt5.last_error()}", "lockdown": lockdown}

            exec_mgr = get_execution_manager()
            exec_mgr.reset_real_controlled_run()
            router = DecisionRouter()
            guard = ConflictGuard()
            risk_mgr = RiskManager()
            pos_mgr = PositionManager()
            governor = GovernorAgent()
            risk_closer = RiskCloseAgent()
            arbiter = SignalArbiter()

            for cycle in range(max_cycles):
                if (time.monotonic() - started) / 60.0 > max_runtime_minutes:
                    break
                positions = list(mt5.positions_get() or [])
                result = main_loop.run_cycle(
                    mt5=mt5,
                    symbol=symbol,
                    timeframe=timeframe,
                    router=router,
                    guard=guard,
                    risk_mgr=risk_mgr,
                    pos_mgr=pos_mgr,
                    exec_mgr=exec_mgr,
                    governor=governor,
                    risk_closer=risk_closer,
                    active_positions=positions,
                    arbiter=arbiter,
                )
                result["cycle"] = cycle + 1
                result["orders_sent_this_run"] = successful_orders
                result["max_market_orders_per_run"] = max_market_orders
                results.append(result)
                if result.get("order") or (result.get("success") and not result.get("simulated")):
                    successful_orders += 1
                    result["orders_sent_this_run"] = successful_orders
                    if successful_orders >= max_market_orders:
                        break
                time.sleep(0.2)
            return {
                "ok": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "cycles": len(results),
                "orders_sent_this_run": successful_orders,
                "max_market_orders_per_run": max_market_orders,
                "results": results,
            }
        finally:
            try:
                import MetaTrader5 as mt5

                mt5.shutdown()
            except Exception:
                pass
            config_loader.use_config(old_config)
