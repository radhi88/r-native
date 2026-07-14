"""Realtime REAL_CONTROLLED_MODE loop service for Qader.

Runs the live scan/execute loop in a background thread and writes audit logs to
logs/qader_realtime_loop.jsonl.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.paths import app_root, dna_dir, ensure_runtime_dirs, logs_dir
from qader_app.storage.audit_log import log_action
from qader_app.storage.settings_store import PermissionsStore
from mt5_ai.core.market_quality import current_market_session, spread_quality


class RealTimeLoopService:
    STOPPED = "STOPPED"
    ARMING = "ARMING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    EMERGENCY_STOP = "EMERGENCY_STOP"

    def __init__(self, permissions: PermissionsStore | None = None, guard: PermissionsGuard | None = None):
        self.permissions = permissions or PermissionsStore()
        self.guard = guard or PermissionsGuard(self.permissions)
        self.state = self.STOPPED
        self.state_reason = "init"
        self.cycle_count = 0
        self.last_cycle_time = ""
        self.last_signal = ""
        self.last_decision = ""
        self.last_block_reason = ""
        self.order_send_called = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._allow_new_entries = True
        self._lock = threading.Lock()
        self._heartbeat_at = 0.0
        self._log_path = logs_dir() / "qader_realtime_loop.jsonl"
        self._journal_path = logs_dir() / "live_performance_journal.jsonl"
        self._dna_journal_path = dna_dir() / "live_performance_journal.jsonl"
        self._dashboard_state_path = app_root() / "dashboard" / "qader_live_state.json"
        self._demo_trades_opened = 0
        self._demo_trade_orders: set[int] = set()
        self._managed_position_tickets: set[int] = set()
        self._partial_closed_tickets: set[int] = set()
        self._open_position_snapshots: dict[int, dict] = {}
        self._latest_record: dict[str, Any] = {}
        self._chart_history: list[dict[str, Any]] = []
        self._learning_service = None
        self._learning_decisions: list[dict[str, Any]] = []
        self._latest_learning_state: dict[str, Any] = {}
        self._last_learning_apply_at = 0.0
        self._last_entry_at: dict[str, float] = {}
        self._last_pending_at: dict[str, float] = {}
        self._bar_ts_cache: dict = {}
        self._analysis_cache: dict = {}
        self._cached_agents: tuple | None = None
        ensure_runtime_dirs()

    @property
    def config_path(self) -> Path:
        return app_root() / "config" / "real_controlled_mode.yaml"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "reason": self.state_reason,
                "cycle_count": self.cycle_count,
                "last_cycle_time": self.last_cycle_time,
                "last_signal": self.last_signal,
                "last_decision": self.last_decision,
                "last_block_reason": self.last_block_reason,
                "order_send_called": self.order_send_called,
                "demo_trades_opened": self._demo_trades_opened,
                "demo_trades_managed": len(self._managed_position_tickets),
                "allow_new_entries": self._allow_new_entries,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
            }

    def _set_state(self, state: str, reason: str = "") -> None:
        with self._lock:
            self.state = state
            self.state_reason = reason
            if state in (self.STOPPED, self.BLOCKED, self.EMERGENCY_STOP):
                self._pause_event.set()

    def _increment_cycle(self) -> None:
        with self._lock:
            self.cycle_count += 1
            self.last_cycle_time = datetime.now(timezone.utc).isoformat()

    def _write_loop_log(self, record: dict[str, Any]) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._latest_record = dict(record)
        self._update_chart_history(record)
        self._write_dashboard_state()

    def _update_chart_history(self, record: dict[str, Any]) -> None:
        if "cycle_number" not in record or "bid" not in record or "ask" not in record:
            return
        try:
            bid = float(record.get("bid", 0.0) or 0.0)
            ask = float(record.get("ask", 0.0) or 0.0)
            if bid <= 0 or ask <= 0:
                return
            point = {
                "timestamp": record.get("timestamp", ""),
                "cycle_number": int(record.get("cycle_number", 0) or 0),
                "symbol": record.get("symbol", ""),
                "timeframe": record.get("timeframe", ""),
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2.0, 5),
                "spread": float(record.get("spread", 0.0) or 0.0),
                "confidence": float(record.get("confidence", 0.0) or 0.0),
                "final_action": record.get("final_action", "HOLD"),
                "arbiter_result": record.get("arbiter_result", "HOLD"),
                "risk_status": record.get("risk_status", ""),
                "execution_status": record.get("execution_status", ""),
                "open_positions": record.get("open_positions", 0),
            }
        except Exception:
            return
        if self._chart_history and self._chart_history[-1].get("cycle_number") == point["cycle_number"]:
            self._chart_history[-1] = point
        else:
            self._chart_history.append(point)
        self._chart_history = self._chart_history[-240:]

    def _write_loop_event(self, event: str, reason: str = "", **extra: Any) -> None:
        self._write_loop_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_number": self.cycle_count,
            "loop_state": self.state,
            "event": event,
            "symbol": extra.pop("symbol", "XAUUSDm"),
            "timeframe": extra.pop("timeframe", "M1"),
            "reason": reason,
            **extra,
        })

    def _write_journal(self, event: dict[str, Any]) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        for path in (self._journal_path, self._dna_journal_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _write_dashboard_state(self) -> None:
        try:
            self._dashboard_state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "loop": self.status(),
                "latest_record": self._latest_record,
                "chart_history": self._chart_history,
                "fvg_zones": self._latest_record.get("fvg_zones", []),
                "market_levels": self._latest_record.get("market_levels", {}),
                "fusion_candle": self._latest_record.get("fusion_candle", {}),
                "structure_map": self._latest_record.get("structure_map", {}),
                "indicator_pack": self._latest_record.get("indicator_pack", {}),
                "pending_plan": self._latest_record.get("pending_plan", {}),
                "learning_state": self._latest_learning_state,
                "session_info": self._session_info(),
                "log_path": str(self._log_path),
                "journal_path": str(self._journal_path),
                "dna_journal_path": str(self._dna_journal_path),
                "demo_only": True,
            }
            self._dashboard_state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            pass

    def _restore_demo_session_state(self) -> dict[str, Any]:
        restored_count = 0
        restored_order_keys: set[int] = set()
        sources: set[str] = set()

        def as_int(value: Any) -> int:
            try:
                return int(value or 0)
            except Exception:
                return 0

        def remember_order(record: dict[str, Any]) -> None:
            order_key = as_int(record.get("order") or record.get("deal"))
            if order_key > 0:
                restored_order_keys.add(order_key)

        def observe_record(record: Any, source: str) -> None:
            nonlocal restored_count
            if not isinstance(record, dict):
                return

            loop = record.get("loop")
            if isinstance(loop, dict):
                count = as_int(loop.get("demo_trades_opened"))
                if count > restored_count:
                    restored_count = count
                    sources.add(source)

            latest_record = record.get("latest_record")
            if isinstance(latest_record, dict):
                remember_order(latest_record)

            count = as_int(record.get("demo_trade_count"))
            if count > restored_count:
                restored_count = count
                sources.add(source)

            event = str(record.get("event") or "")
            reason = str(record.get("reason") or "")
            if event == "realtime_loop_target_reached_manage_only" and "target_demo_trades_reached:" in reason:
                count = as_int(reason.rsplit(":", 1)[-1])
                if count > restored_count:
                    restored_count = count
                    sources.add(source)

            if record.get("order_send_called") and record.get("execution_status") == "executed":
                remember_order(record)

        def read_json_file(path: Path, source: str) -> None:
            try:
                text = path.read_text(encoding="utf-8").replace("\x00", "").strip()
                if text:
                    observe_record(json.loads(text), source)
            except Exception:
                pass

        def read_recent_jsonl(path: Path, source: str, max_bytes: int = 8_000_000, limit: int = 2500) -> None:
            try:
                if not path.exists():
                    return
                size = path.stat().st_size
                with path.open("rb") as handle:
                    if size > max_bytes:
                        handle.seek(size - max_bytes)
                    text = handle.read().decode("utf-8", errors="ignore").replace("\x00", "")
                seen = 0
                for line in reversed(text.splitlines()):
                    if seen >= limit:
                        break
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        observe_record(json.loads(line), source)
                        seen += 1
                    except Exception:
                        continue
            except Exception:
                pass

        read_json_file(self._dashboard_state_path, "dashboard_state")
        read_recent_jsonl(self._journal_path, "performance_journal")
        read_recent_jsonl(self._dna_journal_path, "dna_journal")
        read_recent_jsonl(self._log_path, "loop_log")

        if restored_count > 0:
            self._demo_trades_opened = max(self._demo_trades_opened, restored_count)
        self._demo_trade_orders.update(restored_order_keys)
        return {
            "demo_trades_opened": self._demo_trades_opened,
            "orders_restored": len(restored_order_keys),
            "sources": sorted(sources),
        }

    def start(self, final_confirmation: bool = False) -> dict[str, Any]:
        if not final_confirmation:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_path.touch(exist_ok=True)
            self._write_loop_event("realtime_loop_blocked", "final_gui_confirmation_required")
            return {"ok": False, "reason": "final_gui_confirmation_required"}

        perm = self.guard.check("can_place_live_orders", "start_real_controlled_loop", "real_time_loop_service")
        if not perm.allowed:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_path.touch(exist_ok=True)
            self._write_loop_event("realtime_loop_blocked", perm.reason)
            return {"ok": False, "reason": perm.reason}

        if self._thread and self._thread.is_alive():
            return {"ok": False, "reason": "already_running"}

        self._stop_event.clear()
        self._pause_event.clear()
        self._allow_new_entries = os.environ.get("QADER_START_MANAGE_ONLY", "").lower() not in {"1", "true", "yes"}
        self.order_send_called = False
        self._demo_trades_opened = 0
        self._demo_trade_orders.clear()
        self._managed_position_tickets.clear()
        self._partial_closed_tickets.clear()
        self._open_position_snapshots.clear()
        self._learning_decisions.clear()
        self._latest_learning_state = {}
        self._last_learning_apply_at = 0.0
        self._set_state(self.ARMING, "arming_loop")
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.touch(exist_ok=True)
        restored_state = self._restore_demo_session_state()
        if restored_state.get("demo_trades_opened"):
            self._write_loop_event("realtime_loop_restored_demo_session", "restored_demo_counter", restored=restored_state)
        self._write_loop_event("realtime_loop_starting", "arming_loop")

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="RealTimeLoopService")
        self._thread.start()
        log_action("real_time_loop_start", "can_place_live_orders", True, "loop_arming", "real_time_loop_service")
        return {"ok": True, "state": self.state}

    def pause(self) -> dict[str, Any]:
        self._pause_event.set()
        self._set_state(self.PAUSED, "paused_by_user")
        log_action("real_time_loop_pause", None, True, "paused", "real_time_loop_service")
        return {"ok": True, "state": self.state}

    def resume(self) -> dict[str, Any]:
        if self.state == self.EMERGENCY_STOP:
            return {"ok": False, "reason": "emergency_stop_active"}
        self._pause_event.clear()
        self._set_state(self.RUNNING, "resumed_by_user")
        log_action("real_time_loop_resume", None, True, "resumed", "real_time_loop_service")
        return {"ok": True, "state": self.state}

    def stop_new_entries(self) -> dict[str, Any]:
        self._allow_new_entries = False
        log_action("real_time_loop_stop_new_entries", None, True, "new_entries_disabled", "real_time_loop_service")
        return {"ok": True, "allow_new_entries": False}

    def enable_new_entries(self) -> dict[str, Any]:
        self._allow_new_entries = True
        log_action("real_time_loop_enable_new_entries", None, True, "new_entries_enabled", "real_time_loop_service")
        return {"ok": True, "allow_new_entries": True}

    def stop(self, reason: str = "stopped_by_user") -> dict[str, Any]:
        self._stop_event.set()
        self._set_state(self.STOPPED, reason)
        log_action("real_time_loop_stop", None, True, reason, "real_time_loop_service")
        return {"ok": True, "state": self.state}

    def emergency_stop(self) -> dict[str, Any]:
        self._stop_event.set()
        self._pause_event.set()
        self._set_state(self.EMERGENCY_STOP, "emergency_stop")
        try:
            from mt5_ai.core.kill_switch import activate
            activate("qader_emergency_stop")
        except Exception:
            pass
        log_action("real_time_loop_emergency_stop", None, True, "emergency_stop", "real_time_loop_service")
        return {"ok": True, "state": self.state}

    def _run_loop(self) -> None:
        from mt5_ai.core import config_loader
        from mt5_ai.core.conflict_guard import ConflictGuard
        from mt5_ai.core.decision_router import DecisionRouter
        from mt5_ai.core.execution_manager import get_execution_manager
        from mt5_ai.core.indicators import atr as calc_atr
        from mt5_ai.core.position_manager import PositionManager
        from mt5_ai.core.risk_manager import RiskManager
        from mt5_ai.core.signal_arbiter import SignalArbiter
        from mt5_ai.core.signal_schema import Direction, ExecutionRequest
        from mt5_ai.agents import FractalAgent, IctSweepAgent, SmcAgent, GovernorAgent, RiskCloseAgent

        old_config = config_loader.active_config_path()
        config_loader.use_config(self.config_path)
        try:
            import MetaTrader5 as mt5

            if not mt5.initialize():
                self._set_state(self.BLOCKED, f"mt5_initialize_failed:{mt5.last_error()}")
                self._write_loop_event("realtime_loop_blocked", self.state_reason, error=str(mt5.last_error()))
                return

            exec_mgr = get_execution_manager()
            exec_mgr.reset_real_controlled_run()
            router = DecisionRouter()
            guard = ConflictGuard()
            risk_mgr = RiskManager()
            position_mgr = PositionManager()
            governor = GovernorAgent()
            risk_closer = RiskCloseAgent()
            arbiter = SignalArbiter()
            self._cached_agents = (FractalAgent(), SmcAgent(), IctSweepAgent())
            self._bar_ts_cache.clear()
            self._analysis_cache.clear()

            cfg = config_loader.load()
            if not bool(cfg.get("realtime_loop_enabled", True)):
                self._set_state(self.BLOCKED, "realtime_loop_disabled_in_config")
                self._write_loop_event("realtime_loop_blocked", self.state_reason)
                return
            account_status = self._account_status(mt5)
            log_action(
                "real_time_loop_account_status",
                None,
                bool(account_status.get("demo_or_trial")),
                "demo_trial_account" if account_status.get("demo_or_trial") else "blocked_not_demo_or_trial",
                "real_time_loop_service",
                result=account_status,
            )
            if not account_status.get("demo_or_trial"):
                self._switch_to_demo_only_blocked(account_status)
                self._set_state(self.BLOCKED, "connected_account_not_demo_or_trial")
                self._write_loop_event("realtime_loop_blocked", self.state_reason, account=account_status)
                return

            interval = float(cfg.get("loop_interval_seconds", 1) or 1)
            heartbeat_interval = float(cfg.get("heartbeat_interval_seconds", 5) or 5)
            max_failures = int(cfg.get("max_data_failures_before_block", 60) or 60)
            max_data_unavailable_seconds = float(cfg.get("max_data_unavailable_seconds", 300) or 300)
            continue_after_hold = bool(cfg.get("continue_after_hold", True))
            continue_after_blocked_cycle = bool(cfg.get("continue_after_blocked_cycle", True))
            continue_after_order_send = bool(cfg.get("continue_after_order_send", True))
            manage_open_positions = bool(cfg.get("manage_open_positions", True))
            selected_symbols = list(cfg.get("symbols", {}).get("active", ["XAUUSDm"]))
            selected_timeframes = list(cfg.get("symbols", {}).get("timeframes", ["M1"]))
            max_open_positions = int(cfg.get("risk", {}).get("max_open_positions", 1) or 1)
            _tdt = cfg.get("target_demo_trades")
            if _tdt is None:
                _tdt = cfg.get("execution", {}).get("target_demo_trades")
            target_demo_trades = int(_tdt) if _tdt is not None else 3
            stop_after_target = bool(cfg.get("stop_after_target_demo_trades", False))

            last_account_readable = time.monotonic()
            consecutive_data_failures = 0
            self._set_state(self.RUNNING, "loop_started")
            self._write_loop_event("realtime_loop_started", "loop_started", account=account_status)
            self._heartbeat_at = time.monotonic()

            while not self._stop_event.is_set():
                if self._pause_event.is_set() and self.state != self.PAUSED:
                    self._set_state(self.PAUSED, "paused")

                if self._pause_event.is_set():
                    time.sleep(0.25)
                    continue

                if not self._is_mt5_account_readable(mt5):
                    if time.monotonic() - last_account_readable > max_data_unavailable_seconds:
                        self._set_state(self.BLOCKED, f"mt5_account_data_unavailable_longer_than_{int(max_data_unavailable_seconds)}s")
                        self._write_loop_event("realtime_loop_blocked", self.state_reason)
                        break
                    time.sleep(1.0)
                    continue

                last_account_readable = time.monotonic()

                if manage_open_positions:
                    self._manage_positions(mt5, governor, risk_closer, position_mgr, exec_mgr, cfg)

                positions = list(mt5.positions_get() or [])
                if not positions and len(selected_symbols) == 0:
                    self._set_state(self.BLOCKED, "no_symbols_selected")
                    self._write_loop_event("realtime_loop_blocked", self.state_reason)
                    break

                self._increment_cycle()
                cycle_ok = False
                any_order_sent = False
                cycle_block_reason = ""
                exec_mgr.reset_real_controlled_run()
                # target_demo_trades==0 means unlimited; restored counters must
                # still block entries before the first post-restart scan.
                if target_demo_trades > 0 and self._demo_trades_opened >= target_demo_trades:
                    self._allow_new_entries = False
                elif not self._allow_new_entries:
                    self._allow_new_entries = True

                # Reload gene weights every 100 cycles so that Bayesian
                # feedback written by dna_live_feedback.py propagates to live
                # decisions without restarting the loop service.
                if self.cycle_count % 100 == 0:
                    try:
                        arbiter.reload_weights()
                    except Exception:
                        pass  # never let a weight reload crash the loop

                for symbol in selected_symbols:
                    for timeframe in selected_timeframes:
                        try:
                            scan_result = self._scan_symbol_cycle(
                                mt5=mt5,
                                symbol=symbol,
                                timeframe=timeframe,
                                router=router,
                                guard=guard,
                                risk_mgr=risk_mgr,
                                position_mgr=position_mgr,
                                exec_mgr=exec_mgr,
                                arbiter=arbiter,
                                max_open_positions=max_open_positions,
                                cfg=cfg,
                            )
                        except Exception as exc:
                            scan_result = self._cycle_error_record(symbol, timeframe, mt5, exec_mgr, cfg, exc)
                            log_action(
                                "real_time_loop_cycle_exception",
                                None,
                                False,
                                str(exc),
                                "real_time_loop_service",
                                result={"traceback": traceback.format_exc()},
                            )
                        self._record_learning_cycle(scan_result, cfg)
                        self._write_loop_log(scan_result)
                        self.last_signal = scan_result.get("arbiter_result", "")
                        self.last_decision = scan_result.get("final_action", "")
                        self.last_block_reason = scan_result.get("reason", "")
                        if scan_result.get("order_send_called"):
                            any_order_sent = True
                        if scan_result.get("result") == "blocked_cycle":
                            consecutive_data_failures += 1
                        else:
                            consecutive_data_failures = 0
                        if scan_result.get("order_send_called"):
                            self.order_send_called = True

                        if scan_result.get("final_action") == "HOLD" and not continue_after_hold:
                            self._set_state(self.STOPPED, "hold_cycle_stopped")
                            self._stop_event.set()
                            break
                        if scan_result.get("result") == "blocked_cycle" and not continue_after_blocked_cycle:
                            self._set_state(self.STOPPED, "blocked_cycle_stop")
                            self._stop_event.set()
                            break
                        if scan_result.get("order_send_called") and not continue_after_order_send:
                            self._set_state(self.STOPPED, "order_send_stop")
                            self._stop_event.set()
                            break
                    if self._stop_event.is_set():
                        break

                if consecutive_data_failures >= max_failures:
                    self._set_state(self.BLOCKED, "max_data_failures_reached")
                    self._write_loop_event("realtime_loop_blocked", self.state_reason)
                    break

                if target_demo_trades > 0 and self._demo_trades_opened >= target_demo_trades and not stop_after_target and self._allow_new_entries:
                    self._allow_new_entries = False
                    log_action(
                        "real_time_loop_target_reached_stop_new_entries",
                        None,
                        True,
                        f"target_demo_trades_reached:{self._demo_trades_opened}",
                        "real_time_loop_service",
                        result={"target_demo_trades": target_demo_trades, "demo_trades_opened": self._demo_trades_opened},
                    )
                    self._write_loop_event(
                        "realtime_loop_target_reached_manage_only",
                        f"target_demo_trades_reached:{self._demo_trades_opened}",
                    )

                if target_demo_trades > 0 and self._demo_trades_opened >= target_demo_trades and stop_after_target:
                    self._set_state(self.STOPPED, f"target_demo_trades_reached:{self._demo_trades_opened}")
                    break

                if self._stop_event.is_set():
                    break

                if time.monotonic() - self._heartbeat_at >= heartbeat_interval:
                    self._log_heartbeat()
                    self._heartbeat_at = time.monotonic()

                self._set_state(self.RUNNING, "loop_running")
                time.sleep(interval)
        except Exception as exc:
            self._set_state(self.BLOCKED, f"exception:{exc}")
            tb = traceback.format_exc()
            self._write_loop_event("realtime_loop_crashed", str(exc), error=str(exc), traceback=tb)
            log_action("real_time_loop_exception", None, False, str(exc), "real_time_loop_service", result={"traceback": tb})
        finally:
            try:
                import MetaTrader5 as mt5
                mt5.shutdown()
            except Exception:
                pass
            config_loader.use_config(old_config)
            if self.state not in (self.BLOCKED, self.EMERGENCY_STOP):
                self._set_state(self.STOPPED, "loop_complete")
            self._write_loop_event(
                "realtime_loop_blocked" if self.state == self.BLOCKED else "realtime_loop_stopped",
                self.state_reason,
            )

    def _account_status(self, mt5) -> dict[str, Any]:
        try:
            info = mt5.account_info()
            if info is None:
                return {"readable": False, "demo_or_trial": False, "last_error": mt5.last_error()}
            server = str(getattr(info, "server", "") or "")
            trade_mode_raw = getattr(info, "trade_mode", -1)
            trade_mode = int(-1 if trade_mode_raw is None else trade_mode_raw)
            demo_constant = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
            server_demo = any(keyword in server.lower() for keyword in ("demo", "trial"))
            return {
                "readable": True,
                "login": getattr(info, "login", None),
                "server": server,
                "name": getattr(info, "name", ""),
                "company": getattr(info, "company", ""),
                "currency": getattr(info, "currency", ""),
                "balance": getattr(info, "balance", None),
                "equity": getattr(info, "equity", None),
                "margin": getattr(info, "margin", None),
                "trade_mode": trade_mode,
                "trade_mode_demo_constant": demo_constant,
                "server_demo_keyword": server_demo,
                "demo_or_trial": trade_mode == demo_constant or server_demo,
            }
        except Exception as exc:
            return {"readable": False, "demo_or_trial": False, "error": str(exc)}

    def _switch_to_demo_only_blocked(self, account: dict[str, Any]) -> None:
        try:
            from qader_app.storage.settings_store import SettingsStore

            SettingsStore().save({
                "mode": "demo_only",
                "safety_status": "DEMO_ONLY_BLOCKED_REAL_ACCOUNT",
                "last_account_status": account,
            })
        except Exception:
            pass

    def _is_mt5_account_readable(self, mt5) -> bool:
        try:
            info = mt5.account_info()
            return info is not None
        except Exception:
            return False

    def _cycle_error_record(self, symbol: str, timeframe: str, mt5, exec_mgr, cfg: dict[str, Any], exc: Exception) -> dict[str, Any]:
        bid, ask, spread = self._symbol_tick_data(mt5, symbol)
        orders_sent = int(getattr(exec_mgr, "_real_orders_sent_this_run", 0) or 0)
        execution_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        max_orders = int(execution_cfg.get("max_market_orders_per_run", cfg.get("max_market_orders_per_run", 3) if isinstance(cfg, dict) else 3) or 3)
        open_positions = 0
        open_positions_total = 0
        pending_orders = 0
        pending_orders_total = 0
        try:
            from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC

            positions = list(mt5.positions_get() or [])
            orders = list(mt5.orders_get() or [])
            open_positions_total = len(positions)
            open_positions = len([
                pos for pos in positions
                if int(getattr(pos, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
            ])
            pending_orders_total = len(orders)
            pending_orders = len([
                order for order in orders
                if int(getattr(order, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
            ])
        except Exception:
            pass
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_number": self.cycle_count,
            "loop_state": self.state,
            "symbol": symbol,
            "timeframe": timeframe,
            "bars_received": 0,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "fractal_result": "ERROR",
            "smc_result": "ERROR",
            "ict_result": "ERROR",
            "arbiter_result": "HOLD",
            "confidence": 0.0,
            "risk_status": "cycle_exception",
            "final_action": "HOLD",
            "execution_status": "cycle_exception",
            "execution_decision": "cycle_exception",
            "open_positions": open_positions,
            "open_positions_total": open_positions_total,
            "pending_orders": pending_orders,
            "pending_orders_total": pending_orders_total,
            "order_send_called": False,
            "order": 0,
            "deal": 0,
            "demo_calibration": False,
            "orders_sent_this_run": orders_sent,
            "max_market_orders_per_run": max_orders,
            "order_attempt_status": "not_attempted",
            "blocked_reason": f"cycle_exception:{exc}",
            "reason": f"cycle_exception:{exc}",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "result": "blocked_cycle",
        }

    def _record_learning_cycle(self, record: dict[str, Any], cfg: dict[str, Any] | None = None) -> None:
        decision = {
            "event": "cycle_decision_outcome",
            "cycle_number": record.get("cycle_number"),
            "symbol": record.get("symbol"),
            "timeframe": record.get("timeframe"),
            "final_action": record.get("final_action"),
            "confidence": record.get("confidence"),
            "risk_status": record.get("risk_status"),
            "execution_status": record.get("execution_status"),
            "order_send_called": record.get("order_send_called"),
            "demo_calibration": record.get("demo_calibration"),
            "reason": record.get("reason"),
            "error": record.get("error", ""),
        }
        self._learning_decisions.append(decision)
        self._learning_decisions = self._learning_decisions[-50:]
        self._write_journal(decision)
        learning_cfg = self._learning_config(cfg)
        if not learning_cfg["collect_every_cycle"]:
            return
        self._collect_learning_proposal(
            decisions=self._learning_decisions[-int(learning_cfg["sample_window"]):],
            source_event="cycle_decision_outcome",
            cycle_number=record.get("cycle_number"),
            context={
                "symbol": record.get("symbol"),
                "timeframe": record.get("timeframe"),
                "final_action": record.get("final_action"),
                "execution_status": record.get("execution_status"),
            },
            cfg=cfg,
            allow_apply=learning_cfg["auto_apply_proposals"],
        )

    def _record_trade_learning(self, trade_record: dict[str, Any], record: dict[str, Any], cfg: dict[str, Any]) -> None:
        decision = {
            "event": "trade_decision_outcome",
            "cycle_number": record.get("cycle_number"),
            "symbol": record.get("symbol"),
            "timeframe": record.get("timeframe"),
            "final_action": record.get("final_action"),
            "confidence": record.get("confidence"),
            "risk_status": record.get("risk_status"),
            "execution_status": record.get("execution_status"),
            "order_send_called": True,
            "demo_calibration": record.get("demo_calibration"),
            "reason": record.get("reason"),
            "order": record.get("order"),
            "deal": record.get("deal"),
        }
        self._learning_decisions.append(decision)
        self._learning_decisions = self._learning_decisions[-50:]
        self._write_journal(decision)
        learning_cfg = self._learning_config(cfg)
        self._collect_learning_proposal(
            decisions=self._learning_decisions[-int(learning_cfg["sample_window"]):],
            source_event="demo_trade_entry",
            cycle_number=record.get("cycle_number"),
            context=trade_record,
            cfg=cfg,
            allow_apply=learning_cfg["apply_on_trade_opened"],
        )

    def _learning_config(self, cfg: dict[str, Any] | None) -> dict[str, Any]:
        raw = cfg.get("learning", {}) if isinstance(cfg, dict) else {}
        sample_window = int(raw.get("sample_window", raw.get("min_samples_for_auto_apply", 30)) or 30)
        min_samples = int(raw.get("min_samples_for_auto_apply", sample_window) or sample_window)
        return {
            "collect_every_cycle": bool(raw.get("collect_every_cycle", True)),
            "apply_on_trade_opened": bool(raw.get("apply_on_trade_opened", False)),
            "auto_apply_proposals": bool(raw.get("auto_apply_proposals", False)),
            "min_samples_for_auto_apply": max(1, min_samples),
            "sample_window": max(1, sample_window),
            "apply_cooldown_seconds": float(raw.get("apply_cooldown_seconds", 60) or 60),
        }

    def _ensure_learning_service(self):
        if self._learning_service is None:
            from qader_app.services.learning_service import LearningService

            self._learning_service = LearningService()
        return self._learning_service

    def _collect_learning_proposal(
        self,
        *,
        decisions: list[dict[str, Any]],
        source_event: str,
        cycle_number: Any,
        context: dict[str, Any],
        cfg: dict[str, Any] | None,
        allow_apply: bool,
    ) -> None:
        try:
            learning_cfg = self._learning_config(cfg)
            learning_service = self._ensure_learning_service()
            learning = learning_service.collect_and_propose(decisions, context=context)
            proposal = learning.get("proposal")
            proposal_payload = getattr(proposal, "changes", proposal)
            summary = learning.get("summary") or {}
            sample_count = int(summary.get("count", 0) or 0)
            application: dict[str, Any] = {
                "applied": False,
                "reason": "auto_apply_disabled",
                "proposal": getattr(proposal, "proposal_id", ""),
            }

            if allow_apply and learning_cfg["auto_apply_proposals"]:
                cooldown_remaining = learning_cfg["apply_cooldown_seconds"] - (time.monotonic() - self._last_learning_apply_at)
                if sample_count < learning_cfg["min_samples_for_auto_apply"]:
                    application["reason"] = (
                        f"samples_below_minimum:{sample_count}<"
                        f"{learning_cfg['min_samples_for_auto_apply']}"
                    )
                elif cooldown_remaining > 0:
                    application["reason"] = f"apply_cooldown:{int(cooldown_remaining)}s"
                else:
                    application = learning_service.apply_proposal(proposal, approved=True)
                    if application.get("applied"):
                        self._last_learning_apply_at = time.monotonic()
            elif allow_apply:
                application["reason"] = "proposal_application_not_enabled_in_config"

            strategy_dna_modification = "applied" if application.get("applied") else "guarded"
            event = {
                "event": "dna_learning_proposal",
                "source_event": source_event,
                "cycle_number": cycle_number,
                "summary": summary,
                "proposal": proposal_payload,
                "source_modification": strategy_dna_modification,
                "strategy_dna_modification": strategy_dna_modification,
                "approved": bool(allow_apply and learning_cfg["auto_apply_proposals"]),
                "application": application,
                "learning_config": {
                    "min_samples_for_auto_apply": learning_cfg["min_samples_for_auto_apply"],
                    "sample_window": learning_cfg["sample_window"],
                    "apply_cooldown_seconds": learning_cfg["apply_cooldown_seconds"],
                },
                "context": context,
            }
            self._latest_learning_state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_event": source_event,
                "cycle_number": cycle_number,
                "summary": summary,
                "proposal": proposal_payload,
                "application": application,
                "approved": bool(allow_apply and learning_cfg["auto_apply_proposals"]),
                "learning_config": event["learning_config"],
                "strategy_dna_modification": strategy_dna_modification,
            }
            self._write_journal(event)
            if application.get("applied"):
                self._write_journal({
                    "event": "dna_learning_applied",
                    "cycle_number": cycle_number,
                    "proposal": proposal_payload,
                    "application": application,
                    "context": context,
                })
        except Exception as exc:
            self._latest_learning_state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_event": source_event,
                "cycle_number": cycle_number,
                "error": str(exc),
            }
            self._write_journal({
                "event": "dna_learning_error",
                "cycle_number": cycle_number,
                "source_event": source_event,
                "error": str(exc),
                "source_modification": "disabled",
            })

    def _cleanup_stale_pending_orders(self, mt5, exec_mgr, cfg: dict[str, Any]) -> None:
        """Cancel Qader pending orders older than pending_stale_minutes (default 20)."""
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC

        pending_cfg = cfg.get("level_pending_orders", {}) if isinstance(cfg, dict) else {}
        stale_minutes = float(pending_cfg.get("stale_cancel_minutes", 20) or 20)
        if stale_minutes <= 0:
            return
        stale_seconds = stale_minutes * 60
        now = time.time()
        try:
            orders = list(mt5.orders_get() or [])
        except Exception:
            return
        for order in orders:
            if int(getattr(order, "magic", -1) or -1) != QADER_REAL_CONTROLLED_MAGIC:
                continue
            setup_time = float(getattr(order, "time_setup", 0) or 0)
            if setup_time <= 0 or (now - setup_time) < stale_seconds:
                continue
            ticket = int(getattr(order, "ticket", 0) or 0)
            symbol = str(getattr(order, "symbol", ""))
            age_min = round((now - setup_time) / 60, 1)
            try:
                request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
                result = mt5.order_send(request)
                retcode = int(getattr(result, "retcode", 0) or 0)
                success = retcode == mt5.TRADE_RETCODE_DONE
                self._write_journal({
                    "event": "stale_pending_order_cancelled",
                    "ticket": ticket,
                    "symbol": symbol,
                    "age_minutes": age_min,
                    "retcode": retcode,
                    "success": success,
                })
            except Exception as exc:
                self._write_journal({
                    "event": "stale_pending_cancel_error",
                    "ticket": ticket,
                    "symbol": symbol,
                    "error": str(exc),
                })

    def _manage_positions(self, mt5, governor, risk_closer, position_mgr, exec_mgr, cfg: dict[str, Any]) -> None:
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC
        from mt5_ai.core.signal_schema import PositionAction, PositionManagementRequest

        self._cleanup_stale_pending_orders(mt5, exec_mgr, cfg)

        positions = list(mt5.positions_get() or [])
        qader_positions = [
            pos for pos in positions
            if int(getattr(pos, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
        ]
        current_tickets = {int(getattr(p, "ticket", 0) or 0) for p in qader_positions}

        # Detect closed positions — ticket was tracked but no longer open
        closed_tickets = self._managed_position_tickets - current_tickets
        for ticket in closed_tickets:
            self._managed_position_tickets.discard(ticket)
            entry = self._open_position_snapshots.pop(ticket, {})
            # Find close deal in MT5 history
            try:
                from_ts = int(entry.get("open_time", 0)) or int(time.time() - 7200)
                deals = list(mt5.history_deals_get(from_ts, int(time.time()) + 60) or [])
                close_deal = next(
                    (d for d in reversed(deals)
                     if int(getattr(d, "position_id", -1)) == ticket
                     and getattr(d, "entry", -1) == 1),  # DEAL_ENTRY_OUT = 1
                    None,
                )
                profit = float(getattr(close_deal, "profit", 0.0) or 0.0) if close_deal else 0.0
                close_reason = str(getattr(close_deal, "comment", "unknown") or "unknown")
            except Exception:
                profit = 0.0
                close_reason = "unknown"
            won = profit > 0
            self._write_journal({
                "event": "demo_trade_exit",
                "ticket": ticket,
                "symbol": entry.get("symbol", ""),
                "side": entry.get("side", ""),
                "entry_price": entry.get("entry_price", 0.0),
                "profit": round(profit, 4),
                "won": won,
                "close_reason": close_reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        for pos in qader_positions:
            ticket = int(getattr(pos, "ticket", 0) or 0)
            self._managed_position_tickets.add(ticket)
            # Snapshot entry data for exit tracking
            if ticket not in self._open_position_snapshots:
                self._open_position_snapshots[ticket] = {
                    "symbol": str(getattr(pos, "symbol", "")),
                    "side": "BUY" if int(getattr(pos, "type", 1)) == 0 else "SELL",
                    "entry_price": float(getattr(pos, "price_open", 0.0) or 0.0),
                    "open_time": int(getattr(pos, "time", 0) or 0),
                    "volume": float(getattr(pos, "volume", 0.01) or 0.01),
                }
            requests = self._build_position_management_requests(mt5, pos, cfg)
            evaluation = {
                "event": "position_management_evaluated",
                "ticket": getattr(pos, "ticket", None),
                "symbol": getattr(pos, "symbol", ""),
                "volume": getattr(pos, "volume", None),
                "profit": getattr(pos, "profit", None),
                "sl": getattr(pos, "sl", None),
                "tp": getattr(pos, "tp", None),
                "requests": [req.action.value for req in requests],
                "management_features": {
                    "breakeven": bool(cfg.get("position_management", {}).get("breakeven_enabled", True)),
                    "trailing": bool(cfg.get("position_management", {}).get("trailing_enabled", True)),
                    "sl_lock": bool(cfg.get("position_management", {}).get("sl_lock_enabled", True)),
                    "partial_tp": bool(cfg.get("position_management", {}).get("partial_tp_enabled", False)),
                    "max_runtime": cfg.get("position_management", {}).get("max_runtime_seconds", 1800),
                    "max_loss": cfg.get("position_management", {}).get("max_loss_usd", -2.0),
                },
            }
            self._write_journal(evaluation)
            for req in requests:
                exec_req = position_mgr.handle(req)
                if exec_req:
                    result = exec_mgr.execute(exec_req)
                    self._write_journal({
                        "event": "position_management_order_result",
                        "ticket": req.position_ticket,
                        "symbol": req.symbol,
                        "action": req.action.value,
                        "reason": req.reason,
                        "success": result.success,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                        "message": result.message,
                    })

        for req in risk_closer.evaluate_positions(qader_positions):
            exec_req = position_mgr.handle(req)
            if exec_req:
                result = exec_mgr.execute(exec_req)
                self._write_journal({
                    "event": "risk_close_order_result",
                    "ticket": req.position_ticket,
                    "symbol": req.symbol,
                    "action": req.action.value,
                    "reason": req.reason,
                    "success": result.success,
                    "retcode": result.retcode,
                    "order": result.order,
                    "deal": result.deal,
                    "message": result.message,
                })
        for req in governor.evaluate_positions(
            qader_positions,
            get_signal_fn=lambda sym: None,
            genes={},
            cfg=cfg.get("risk", {}),
        ):
            exec_req = position_mgr.handle(req)
            if exec_req:
                exec_mgr.execute(exec_req)

    def _build_position_management_requests(self, mt5, pos, cfg: dict[str, Any]) -> list:
        from mt5_ai.core.signal_schema import PositionAction, PositionManagementRequest

        pm_cfg = cfg.get("position_management", {}) if isinstance(cfg, dict) else {}
        if not bool(pm_cfg.get("enabled", True)):
            return []

        ticket = int(getattr(pos, "ticket", 0) or 0)
        symbol = str(getattr(pos, "symbol", ""))
        pos_type = self._position_side(mt5, pos)
        current_sl = float(getattr(pos, "sl", 0.0) or 0.0)
        current_tp = float(getattr(pos, "tp", 0.0) or 0.0)
        open_price = float(getattr(pos, "price_open", 0.0) or 0.0)
        current_price = float(getattr(pos, "price_current", 0.0) or 0.0)
        profit = float(getattr(pos, "profit", 0.0) or 0.0)
        volume = float(getattr(pos, "volume", 0.0) or 0.0)
        point = self._symbol_point(mt5, symbol)
        requests: list[PositionManagementRequest] = []

        max_loss = float(pm_cfg.get("max_loss_usd", -2.0) or -2.0)
        if profit <= max_loss:
            return [PositionManagementRequest(
                action=PositionAction.FULL_CLOSE,
                symbol=symbol,
                position_ticket=ticket,
                reason=f"max_loss_stop:profit={profit:.2f}",
                source="qader_position_management",
            )]

        max_runtime_seconds = float(pm_cfg.get("max_runtime_seconds", 1800) or 1800)
        opened_at = float(getattr(pos, "time", 0) or 0)
        if opened_at > 0 and time.time() - opened_at >= max_runtime_seconds:
            return [PositionManagementRequest(
                action=PositionAction.FULL_CLOSE,
                symbol=symbol,
                position_ticket=ticket,
                reason=f"max_runtime_per_position:{int(time.time() - opened_at)}s",
                source="qader_position_management",
            )]

        best_sl = current_sl
        reasons: list[str] = []

        def proposed_sl_from_lock(points: float) -> float:
            offset = max(points * point, point)
            return open_price + offset if pos_type == "BUY" else open_price - offset

        def proposed_sl_from_trail(points: float) -> float:
            offset = max(points * point, point)
            return current_price - offset if pos_type == "BUY" else current_price + offset

        if bool(pm_cfg.get("breakeven_enabled", True)) and profit >= float(pm_cfg.get("breakeven_profit_usd", 0.20) or 0.20):
            candidate = proposed_sl_from_lock(float(pm_cfg.get("breakeven_lock_points", 30) or 30))
            if self._sl_improves(pos_type, current_sl, candidate):
                best_sl = candidate
                reasons.append("breakeven")

        if bool(pm_cfg.get("sl_lock_enabled", True)) and profit >= float(pm_cfg.get("sl_lock_profit_usd", 0.15) or 0.15):
            candidate = proposed_sl_from_lock(float(pm_cfg.get("breakeven_lock_points", 30) or 30))
            if self._sl_improves(pos_type, best_sl, candidate):
                best_sl = candidate
                reasons.append("sl_lock")

        if bool(pm_cfg.get("trailing_enabled", True)) and profit >= float(pm_cfg.get("trailing_start_profit_usd", 0.35) or 0.35):
            candidate = proposed_sl_from_trail(float(pm_cfg.get("trailing_distance_points", 120) or 120))
            if self._sl_improves(pos_type, best_sl, candidate):
                best_sl = candidate
                reasons.append("trailing_stop")

        if reasons and best_sl > 0:
            requests.append(PositionManagementRequest(
                action=PositionAction.BREAKEVEN if "breakeven" in reasons else PositionAction.TRAIL,
                symbol=symbol,
                position_ticket=ticket,
                proposed_sl=round(best_sl, 5),
                proposed_tp=current_tp,
                reason="+".join(reasons),
                source="qader_position_management",
            ))

        if (
            bool(pm_cfg.get("partial_tp_enabled", False))
            and profit >= float(pm_cfg.get("partial_tp_profit_usd", 0.80) or 0.80)
            and ticket not in self._partial_closed_tickets
            and volume > 0.01
        ):
            fraction = min(0.9, max(0.1, float(pm_cfg.get("partial_tp_fraction", 0.5) or 0.5)))
            proposed_lot = max(0.01, round(volume * fraction, 2))
            self._partial_closed_tickets.add(ticket)
            requests.append(PositionManagementRequest(
                action=PositionAction.PARTIAL_CLOSE,
                symbol=symbol,
                position_ticket=ticket,
                proposed_lot=proposed_lot,
                reason=f"partial_tp_toggle:profit={profit:.2f}",
                source="qader_position_management",
            ))

        return requests

    def _sl_improves(self, side: str, current_sl: float, proposed_sl: float) -> bool:
        if proposed_sl <= 0:
            return False
        if current_sl <= 0:
            return True
        if side == "BUY":
            return proposed_sl > current_sl
        return proposed_sl < current_sl

    def _symbol_point(self, mt5, symbol: str) -> float:
        try:
            info = mt5.symbol_info(symbol)
            point = float(getattr(info, "point", 0.0) or 0.0)
            return point if point > 0 else 0.00001
        except Exception:
            return 0.00001

    def _symbol_tick_data(self, mt5, symbol: str) -> tuple[float, float, float]:
        bid = ask = float("nan")
        spread = float("inf")
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                bid = float(getattr(tick, "bid", float("nan")) or float("nan"))
                ask = float(getattr(tick, "ask", float("nan")) or float("nan"))
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is not None and getattr(symbol_info, "spread", None) is not None:
                spread = float(getattr(symbol_info, "spread", float("inf")) or float("inf"))
        except Exception:
            pass
        return bid, ask, spread

    def _daily_loss_pct(self, mt5) -> float:
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

    def _fetch_bars(self, mt5, symbol: str, timeframe: str, n: int = 80):
        try:
            TF = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            tf_code = TF.get(timeframe)
            if tf_code is None:
                return None
            for _ in range(3):
                if not mt5.symbol_select(symbol, True):
                    time.sleep(0.25)
                    continue
                rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, n)
                if rates is None or len(rates) < 30:
                    time.sleep(0.25)
                    continue
                import pandas as pd
                df = pd.DataFrame(rates)
                if df.empty:
                    time.sleep(0.25)
                    continue
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.set_index("time").rename(columns={"tick_volume": "volume"})
                return df[["open", "high", "low", "close", "volume"]]
        except Exception:
            pass
        return None

    def _scan_symbol_cycle(
        self,
        mt5,
        symbol: str,
        timeframe: str,
        router,
        guard,
        risk_mgr,
        position_mgr,
        exec_mgr,
        arbiter,
        max_open_positions: int,
        cfg: dict[str, Any],
    ) -> dict[str, Any]:
        bars = self._fetch_bars(mt5, symbol, timeframe)
        bid, ask, spread = self._symbol_tick_data(mt5, symbol)
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC
        all_positions = list(mt5.positions_get() or [])
        all_orders = list(mt5.orders_get() or [])
        qader_positions = [
            pos for pos in all_positions
            if int(getattr(pos, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
        ]
        qader_orders = [
            order for order in all_orders
            if int(getattr(order, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
        ]
        execution_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        max_run_orders = int(execution_cfg.get("max_market_orders_per_run", cfg.get("max_market_orders_per_run", 3)) or 3)
        orders_sent_this_run = int(getattr(exec_mgr, "_real_orders_sent_this_run", 0) or 0)
        quality = spread_quality(symbol, spread)
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_number": self.cycle_count,
            "loop_state": self.state,
            "symbol": symbol,
            "timeframe": timeframe,
            "session": current_market_session(),
            "bars_received": len(bars) if bars is not None else 0,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "spread_quality": quality["spread_quality"],
            "spread_limit": quality["spread_limit"],
            "spread_ratio": quality["spread_ratio"],
            "fractal_result": "NONE",
            "smc_result": "NONE",
            "ict_result": "NONE",
            "arbiter_result": "HOLD",
            "confidence": 0.0,
            "risk_status": "not_evaluated",
            "final_action": "HOLD",
            "execution_status": "none",
            "execution_decision": "none",
            "open_positions": len(qader_positions),
            "open_positions_total": len(all_positions),
            "pending_orders": len(qader_orders),
            "pending_orders_total": len(all_orders),
            "qader_pending_tickets": [
                int(getattr(order, "ticket", 0) or 0)
                for order in qader_orders[:20]
            ],
            "order_send_called": False,
            "order": 0,
            "deal": 0,
            "demo_calibration": False,
            "orders_sent_this_run": orders_sent_this_run,
            "max_market_orders_per_run": max_run_orders,
            "order_attempt_status": "not_attempted",
            "blocked_reason": "",
            "reason": "",
            "error": "",
            "buy_agent_score": 0.0,
            "sell_agent_score": 0.0,
            "arbiter_primary_code": "",
            "fvg_zones": [],
            "market_levels": {},
            "fusion_candle": {},
            "structure_map": {},
            "indicator_pack": {},
            "pending_plan": {},
            "pending_order_status": "not_evaluated",
        }

        if bars is None:
            record["reason"] = "insufficient_data"
            record["result"] = "blocked_cycle"
            record["execution_status"] = "blocked_cycle"
            record["execution_decision"] = "blocked_cycle"
            record["blocked_reason"] = record["reason"]
            self.last_block_reason = record["reason"]
            return record

        current_mid = (bid + ask) / 2.0 if bid == bid and ask == ask and bid > 0 and ask > 0 else float(bars["close"].iloc[-1])

        from mt5_ai.core.signal_schema import Direction, ExecutionRequest
        from mt5_ai.core.indicators import atr as calc_atr

        _cache_key = (symbol, timeframe)
        _last_bar_ts = bars.index[-1]
        _is_new_bar = _last_bar_ts != self._bar_ts_cache.get(_cache_key)
        _cached = self._analysis_cache.get(_cache_key, {})

        if _is_new_bar or not _cached:
            record["fvg_zones"] = self._detect_fvg_zones(bars)
            record["market_levels"] = self._market_levels(mt5, symbol, timeframe, bars, current_mid)
            record["fusion_candle"] = self._fusion_candle(mt5, symbol)
            record["structure_map"] = self._market_structure_map(bars)
            record["indicator_pack"] = self._indicator_pack(bars, spread)

            raw_signals = []
            agent_outputs = {"fractal_agent": "NONE", "smc_agent": "NONE", "ict_sweep_agent": "NONE"}
            if self._cached_agents:
                _agents = self._cached_agents
            else:
                from mt5_ai.agents import FractalAgent as _FA, IctSweepAgent as _IA, SmcAgent as _SA
                _agents = (_FA(), _SA(), _IA())
            for agent in _agents:
                try:
                    sig = agent.analyse(bars, symbol, timeframe)
                    if sig:
                        raw_signals.append(sig)
                        agent_outputs[sig.source] = sig.direction.value
                except Exception as exc:
                    agent_outputs[getattr(agent, "source", agent.__class__.__name__)] = f"ERROR:{exc}"

            arb = arbiter.decide(raw_signals, symbol, timeframe)

            self._bar_ts_cache[_cache_key] = _last_bar_ts
            self._analysis_cache[_cache_key] = {
                "raw_signals": raw_signals,
                "agent_outputs": agent_outputs,
                "arb": arb,
                "fvg_zones": record["fvg_zones"],
                "market_levels": record["market_levels"],
                "fusion_candle": record["fusion_candle"],
                "structure_map": record["structure_map"],
                "indicator_pack": record["indicator_pack"],
            }
        else:
            raw_signals = _cached["raw_signals"]
            agent_outputs = _cached["agent_outputs"]
            arb = _cached["arb"]
            record["fvg_zones"] = _cached["fvg_zones"]
            record["market_levels"] = _cached["market_levels"]
            record["fusion_candle"] = _cached["fusion_candle"]
            record["structure_map"] = _cached["structure_map"]
            record["indicator_pack"] = _cached["indicator_pack"]

        record["fractal_result"] = agent_outputs.get("fractal_agent", "NONE")
        record["smc_result"] = agent_outputs.get("smc_agent", "NONE")
        record["ict_result"] = agent_outputs.get("ict_sweep_agent", "NONE")
        record["intra_bar_cycle"] = not _is_new_bar

        calibration = self._apply_demo_calibration(arb, cfg)
        record["arbiter_result"] = arb.final_direction.value
        record["confidence"] = round(float(arb.final_confidence), 4)
        record["reason"] = arb.reason or "arbiter_hold"
        record["buy_agent_score"] = round(float(getattr(arb, "buy_agent_score", 0.0) or 0.0), 4)
        record["sell_agent_score"] = round(float(getattr(arb, "sell_agent_score", 0.0) or 0.0), 4)
        record["arbiter_primary_code"] = str(getattr(arb, "primary_code", "") or "")
        if calibration.get("applied"):
            record["demo_calibration"] = True
            record["demo_calibration_label"] = calibration.get("label", "DEMO_CALIBRATION_NOT_LIVE")
            log_action(
                "demo_opportunity_calibration",
                None,
                True,
                record["reason"],
                "real_time_loop_service",
                result={"symbol": symbol, "timeframe": timeframe, **calibration},
            )

        if arb.final_direction == Direction.HOLD:
            record["risk_status"] = "not_reached"
            record["final_action"] = "HOLD"
            record["execution_status"] = "hold_no_order"
            record["execution_decision"] = "hold_no_order"
            record["blocked_reason"] = record["reason"]
            pending_attempt = self._maybe_place_pending_level_order(
                mt5=mt5,
                symbol=symbol,
                timeframe=timeframe,
                bars=bars,
                raw_signals=raw_signals,
                arb=arb,
                market_levels=record["market_levels"],
                spread=spread,
                open_positions=len(qader_positions),
                risk_mgr=risk_mgr,
                exec_mgr=exec_mgr,
                cfg=cfg,
            )
            if pending_attempt.get("evaluated"):
                record["pending_order_status"] = str(pending_attempt.get("status", "evaluated"))
                record["pending_plan"] = pending_attempt.get("plan", {})
                if pending_attempt.get("order_send_called"):
                    record["order_send_called"] = True
                    record["execution_status"] = "pending_order_placed" if pending_attempt.get("success") else "pending_order_failed"
                    record["execution_decision"] = record["execution_status"]
                    record["order_attempt_status"] = "pending_success" if pending_attempt.get("success") else "pending_failed"
                    record["order"] = int(pending_attempt.get("order", 0) or 0)
                    record["deal"] = int(pending_attempt.get("deal", 0) or 0)
                    record["retcode"] = int(pending_attempt.get("retcode", 0) or 0)
                    record["result"] = record["execution_status"]
                    record["orders_sent_this_run"] = int(getattr(exec_mgr, "_real_orders_sent_this_run", 0) or 0)
                    record["reason"] = str(pending_attempt.get("reason", record["reason"]))
                    record["blocked_reason"] = "" if pending_attempt.get("success") else record["reason"]
            return record

        arb_signal = arb.to_signal_proposal()
        decision = router.route([arb_signal], symbol, timeframe)
        record["reason"] = decision.reason or record["reason"]

        positions = list(mt5.positions_get() or [])
        orders = list(mt5.orders_get() or [])
        qader_positions = [
            pos for pos in positions
            if int(getattr(pos, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
        ]
        qader_orders = [
            order for order in orders
            if int(getattr(order, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC
        ]
        record["open_positions"] = len(qader_positions)
        record["open_positions_total"] = len(positions)
        record["pending_orders"] = len(qader_orders)
        record["pending_orders_total"] = len(orders)
        record["qader_pending_tickets"] = [
            int(getattr(order, "ticket", 0) or 0)
            for order in qader_orders[:20]
        ]

        opposite_exit = self._maybe_exit_on_opposite_signal(
            mt5=mt5,
            positions=qader_positions,
            decision=decision,
            position_mgr=position_mgr,
            exec_mgr=exec_mgr,
            cfg=cfg,
        )
        _did_flip = False
        if opposite_exit.get("evaluated"):
            record["position_management_status"] = opposite_exit
            if opposite_exit.get("order_send_called"):
                record["order_send_called"] = True
                if opposite_exit.get("success"):
                    # Flip: refresh positions from MT5 and continue immediately to open opposite
                    from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC as _MAGIC
                    qader_positions = [p for p in (mt5.positions_get() or []) if int(getattr(p, "magic", -1) or -1) == _MAGIC]
                    record["open_positions"] = len(qader_positions)
                    # Reset cooldown so the new direction enters without delay
                    self._last_entry_at[f"{symbol}:{decision.action.value}"] = 0.0
                    _did_flip = True
                else:
                    record["execution_status"] = "opposite_signal_exit_failed"
                    record["execution_decision"] = "opposite_signal_exit_failed"
                    record["order_attempt_status"] = "management_failed"
                    record["reason"] = opposite_exit.get("reason", record["reason"])
                    record["blocked_reason"] = record["reason"]
                    return record

        record["signal_flip"] = _did_flip

        # During a flip, mask the symbol from the positions map so the conflict guard
        # doesn't block entry due to remaining same-symbol positions in the old direction.
        open_positions_map = {str(pos.symbol): self._position_side(mt5, pos) for pos in qader_positions}
        if _did_flip:
            open_positions_map.pop(symbol, None)
        allow, conflicts = guard.check(decision, [arb_signal], open_positions_map)
        if not allow:
            record["risk_status"] = "conflict_blocked:" + ",".join(conflicts)
            record["final_action"] = "HOLD"
            record["execution_status"] = "conflict_blocked"
            record["execution_decision"] = "conflict_blocked"
            record["reason"] = record["risk_status"]
            record["blocked_reason"] = record["reason"]
            return record

        risk_decision = risk_mgr.validate(
            decision,
            symbol,
            spread_points=spread,
            open_positions=len(qader_positions),
            daily_loss_pct=self._daily_loss_pct(mt5),
        )
        record["risk_status"] = "approved" if risk_decision.approved else f"risk_blocked:{risk_decision.reason}"
        if not risk_decision.approved:
            record["final_action"] = "HOLD"
            record["execution_status"] = "risk_blocked"
            record["execution_decision"] = "risk_blocked"
            record["reason"] = record["risk_status"]
            record["blocked_reason"] = record["reason"]
            return record

        cooldown_seconds = float(execution_cfg.get("same_direction_entry_cooldown_seconds", 45) or 0)
        entry_key = f"{symbol}:{decision.action.value}"
        last_entry_at = float(self._last_entry_at.get(entry_key, 0.0) or 0.0)
        if cooldown_seconds > 0 and time.time() - last_entry_at < cooldown_seconds:
            remaining = int(max(0.0, cooldown_seconds - (time.time() - last_entry_at)))
            record["final_action"] = "HOLD"
            record["execution_status"] = "entry_cooldown"
            record["execution_decision"] = "entry_cooldown"
            record["reason"] = f"same_direction_entry_cooldown:{decision.action.value}:{remaining}s"
            record["blocked_reason"] = record["reason"]
            return record

        atr = calc_atr(bars, period=14)
        last_close = float(bars["close"].iloc[-1])
        point = self._symbol_point(mt5, symbol)
        min_stop_points = 0.0
        try:
            symbol_info = mt5.symbol_info(symbol)
            min_stop_points = float(getattr(symbol_info, "trade_stops_level", 0.0) or 0.0)
        except Exception:
            min_stop_points = 0.0
        sl_dist = max(atr * 1.5, point * max(min_stop_points * 2.0, 300.0), 0.0001)
        entry_price = ask if arb.final_direction == Direction.BUY and ask == ask else bid if bid == bid else last_close
        if arb.final_direction == Direction.BUY:
            sl = round(entry_price - sl_dist, 5)
            tp_default = round(entry_price + sl_dist * 2.0, 5)
            tp = self._fvg_tp(bars, entry_price, sl_dist, "BUY") or tp_default
        else:
            sl = round(entry_price + sl_dist, 5)
            tp_default = round(entry_price - sl_dist * 2.0, 5)
            tp = self._fvg_tp(bars, entry_price, sl_dist, "SELL") or tp_default

        exec_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        magic_number = int(exec_cfg.get("magic_number") or 0)
        comment_prefix = str(exec_cfg.get("comment") or "ARB")
        req = ExecutionRequest(
            action=decision.action,
            symbol=symbol,
            lot=risk_decision.adjusted_lot,
            sl=sl,
            tp=tp,
            magic=magic_number,
            comment=f"{comment_prefix}|ARB|{arb.primary_code[:10]}",
            risk_decision=risk_decision,
            confidence=float(arb.final_confidence),
            signal_arbiter_passed=True,
            conflict_guard_passed=True,
        )

        if not self._allow_new_entries:
            record["execution_status"] = "new_entries_disabled"
            record["execution_decision"] = "new_entries_disabled"
            record["final_action"] = "HOLD"
            record["reason"] = "new_entries_disabled"
            record["blocked_reason"] = record["reason"]
            return record

        pending_cfg = cfg.get("level_pending_orders", {}) if isinstance(cfg, dict) else {}
        if bool(pending_cfg.get("prefer_over_market", False)):
            pending_attempt = self._maybe_place_pending_level_order(
                mt5=mt5,
                symbol=symbol,
                timeframe=timeframe,
                bars=bars,
                raw_signals=raw_signals,
                arb=arb,
                market_levels=record["market_levels"],
                spread=spread,
                open_positions=len(qader_positions),
                risk_mgr=risk_mgr,
                exec_mgr=exec_mgr,
                cfg=cfg,
                forced_side=decision.action.value,
                forced_confidence=float(arb.final_confidence),
            )
            if pending_attempt.get("evaluated"):
                record["pending_order_status"] = str(pending_attempt.get("status", "evaluated"))
                record["pending_plan"] = pending_attempt.get("plan", {})
                if pending_attempt.get("order_send_called"):
                    record["order_send_called"] = True
                    record["execution_status"] = "pending_order_placed" if pending_attempt.get("success") else "pending_order_failed"
                    record["execution_decision"] = record["execution_status"]
                    record["final_action"] = decision.action.value if pending_attempt.get("success") else "HOLD"
                    record["order_attempt_status"] = "pending_success" if pending_attempt.get("success") else "pending_failed"
                    record["order"] = int(pending_attempt.get("order", 0) or 0)
                    record["deal"] = int(pending_attempt.get("deal", 0) or 0)
                    record["retcode"] = int(pending_attempt.get("retcode", 0) or 0)
                    record["result"] = record["execution_status"]
                    record["orders_sent_this_run"] = int(getattr(exec_mgr, "_real_orders_sent_this_run", 0) or 0)
                    record["reason"] = str(pending_attempt.get("reason", record["reason"]))
                    record["blocked_reason"] = "" if pending_attempt.get("success") else record["reason"]
                    return record
                if not bool(pending_cfg.get("fallback_to_market_when_no_level", False)):
                    record["final_action"] = "HOLD"
                    record["execution_status"] = f"pending_{record['pending_order_status']}"
                    record["execution_decision"] = record["execution_status"]
                    record["order_attempt_status"] = "pending_not_sent"
                    record["reason"] = str(pending_attempt.get("reason", record["reason"]))
                    record["blocked_reason"] = record["reason"]
                    return record

        result = exec_mgr.execute(req)
        record["order_send_called"] = True
        record["execution_status"] = "executed" if result.success else "execution_failed"
        record["execution_decision"] = record["execution_status"]
        record["final_action"] = decision.action.value
        record["reason"] = result.message or record["reason"]
        record["retcode"] = result.retcode
        record["order"] = result.order
        record["deal"] = result.deal
        record["result"] = "order_sent" if result.success else "execution_failed"
        record["orders_sent_this_run"] = int(getattr(exec_mgr, "_real_orders_sent_this_run", 0) or 0)
        record["order_attempt_status"] = "success" if result.success else "failed"
        record["blocked_reason"] = "" if result.success else record["reason"]
        record["execution_raw"] = result.raw if not result.success else {}
        if result.success and not result.simulated:
            new_demo_trade_opened = False
            self._last_entry_at[entry_key] = time.time()
            order_key = int(result.order or result.deal or 0)
            if order_key and order_key not in self._demo_trade_orders:
                self._demo_trade_orders.add(order_key)
                self._demo_trades_opened += 1
                new_demo_trade_opened = True
            if not new_demo_trade_opened:
                return record
            try:
                from mt5_ai.event_bus import get_event_bus
                get_event_bus().publish("trade_opened", {
                    "symbol": symbol, "timeframe": timeframe,
                    "action": decision.action.value, "lot": risk_decision.adjusted_lot,
                    "sl": sl, "tp": tp, "order": result.order, "deal": result.deal,
                    "confidence": record["confidence"], "cycle": self.cycle_count,
                })
            except Exception:
                pass
            trade_record = {
                "event": "demo_trade_entry",
                "symbol": symbol,
                "timeframe": timeframe,
                "action": decision.action.value,
                "lot": risk_decision.adjusted_lot,
                "sl": sl,
                "tp": tp,
                "spread": spread,
                "atr": atr,
                "signal_agreement": {
                    "fractal": record["fractal_result"],
                    "smc": record["smc_result"],
                    "ict": record["ict_result"],
                    "arbiter": record["arbiter_result"],
                    "confidence": record["confidence"],
                    "demo_calibration": record["demo_calibration"],
                },
                "reason": record["reason"],
                "order": result.order,
                "deal": result.deal,
                "retcode": result.retcode,
                "demo_trade_count": self._demo_trades_opened,
                "dna_adjustment_proposal": self._dna_adjustment_hint(),
            }
            self._write_journal(trade_record)
            self._record_trade_learning(trade_record, record, cfg)
        return record

    def _apply_demo_calibration(self, arb, cfg: dict[str, Any]) -> dict[str, Any]:
        from mt5_ai.core.signal_schema import Direction

        calibration_cfg = cfg.get("demo_calibration", {}) if isinstance(cfg, dict) else {}
        if not bool(calibration_cfg.get("enabled", False)):
            return {"applied": False}
        if arb.final_direction != Direction.HOLD:
            return {"applied": False}
        if bool(getattr(arb, "agent_conflict", False)):
            return {"applied": False, "reason": "hard_conflict_present"}
        if arb.primary_code not in {"confidence_below_threshold", "structure_without_entry_confirmation"}:
            return {"applied": False, "reason": f"primary_code_not_calibrated:{arb.primary_code}"}
        if arb.primary_code == "structure_without_entry_confirmation" and not bool(calibration_cfg.get("allow_structure_without_entry_confirmation", False)):
            return {"applied": False, "reason": "structure_without_entry_confirmation_disabled"}

        min_conf = float(calibration_cfg.get("min_confidence", 0.35) or 0.35)
        confidence = float(getattr(arb, "final_confidence", 0.0) or 0.0)
        if confidence < min_conf:
            return {"applied": False, "reason": f"confidence_{confidence:.3f}<{min_conf:.3f}"}

        buy_score = float(getattr(arb, "buy_agent_score", 0.0) or 0.0)
        sell_score = float(getattr(arb, "sell_agent_score", 0.0) or 0.0)
        if max(buy_score, sell_score) <= 0:
            return {"applied": False, "reason": "no_directional_primary_score"}
        if arb.primary_code == "structure_without_entry_confirmation":
            structure_min_conf = float(calibration_cfg.get("structure_min_confidence", 0.52) or 0.52)
            min_gap = float(calibration_cfg.get("min_directional_score_gap", 0.08) or 0.08)
            if confidence < structure_min_conf:
                return {"applied": False, "reason": f"structure_confidence_{confidence:.3f}<{structure_min_conf:.3f}"}
            if abs(buy_score - sell_score) < min_gap:
                return {"applied": False, "reason": f"directional_gap_{abs(buy_score - sell_score):.3f}<{min_gap:.3f}"}

        lead = Direction.BUY if buy_score >= sell_score else Direction.SELL
        old_reason = arb.reason
        arb.final_direction = lead
        arb.reason = (
            f"DEMO_CALIBRATION_NOT_LIVE|lowered_threshold_only|"
            f"original={old_reason}|threshold={min_conf:.2f}"
        )
        arb.primary_code = "demo_calibration"
        return {
            "applied": True,
            "label": str(calibration_cfg.get("label", "DEMO_CALIBRATION_NOT_LIVE")),
            "direction": lead.value,
            "confidence": confidence,
            "old_reason": old_reason,
            "threshold": min_conf,
        }

    def _maybe_exit_on_opposite_signal(self, mt5, positions: list, decision, position_mgr, exec_mgr, cfg: dict[str, Any]) -> dict[str, Any]:
        from mt5_ai.core.signal_schema import PositionAction, PositionManagementRequest

        pm_cfg = cfg.get("position_management", {}) if isinstance(cfg, dict) else {}
        if not bool(pm_cfg.get("opposite_signal_exit_enabled", True)):
            return {"evaluated": False, "reason": "opposite_signal_exit_disabled"}

        opposite_exit_conf = float(pm_cfg.get("opposite_exit_min_confidence", 0.50))

        for pos in positions:
            side = self._position_side(mt5, pos)
            if str(getattr(pos, "symbol", "")) != str(decision.symbol):
                continue
            if decision.action.value == side:
                continue

            pos_profit = float(getattr(pos, "profit", 0.0) or 0.0)
            sig_confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
            if sig_confidence < opposite_exit_conf:
                return {
                    "evaluated": True, "order_send_called": False,
                    "reason": f"flip_held:side={side},profit={pos_profit:.2f},conf={sig_confidence:.3f}<{opposite_exit_conf}",
                }

            req = PositionManagementRequest(
                action=PositionAction.FULL_CLOSE,
                symbol=str(pos.symbol),
                position_ticket=int(pos.ticket),
                reason=f"opposite_signal_exit:{side}_vs_{decision.action.value}",
                source="qader_opposite_signal_exit",
            )
            exec_req = position_mgr.handle(req)
            if exec_req is None:
                return {"evaluated": True, "order_send_called": False, "reason": "position_manager_returned_none"}
            result = exec_mgr.execute(exec_req)
            self._write_journal({
                "event": "opposite_signal_exit",
                "ticket": int(pos.ticket),
                "symbol": str(pos.symbol),
                "position_side": side,
                "new_signal": decision.action.value,
                "success": result.success,
                "retcode": result.retcode,
                "order": result.order,
                "deal": result.deal,
                "message": result.message,
            })
            return {
                "evaluated": True,
                "order_send_called": True,
                "success": result.success,
                "retcode": result.retcode,
                "order": result.order,
                "deal": result.deal,
                "reason": result.message or req.reason,
            }
        return {"evaluated": True, "order_send_called": False, "reason": "no_opposite_position"}

    def _dna_adjustment_hint(self) -> dict[str, Any]:
        if self._demo_trades_opened < 3:
            return {
                "status": "collecting_samples",
                "sample_count": self._demo_trades_opened,
                "source_modification": "disabled",
            }
        return {
            "status": "proposal_ready_after_min_samples",
            "sample_count": self._demo_trades_opened,
            "proposal": "review confidence, spread, ATR, and signal-agreement distributions before changing Strategy DNA",
            "source_modification": "disabled",
        }

    def _session_info(self) -> dict[str, Any]:
        raw = current_market_session()
        current = {
            "london_ny_overlap": "overlap",
            "asia_london_overlap": "overlap",
            "new_york": "ny",
            "off_session": "off",
        }.get(raw, raw)
        if current not in {"asia", "london", "overlap", "ny", "off"}:
            current = "off"
        return {
            "current": current,
            "raw": raw,
            "utc_hour": datetime.now(timezone.utc).hour,
            "by_session": {
                "asia": {"genes": [], "avg_wr": 0.0},
                "london": {"genes": [], "avg_wr": 0.0},
                "overlap": {"genes": [], "avg_wr": 0.0},
                "ny": {"genes": [], "avg_wr": 0.0},
            },
        }

    def _detect_fvg_zones(self, bars, lookback: int = 80, max_zones: int = 12) -> list[dict[str, Any]]:
        try:
            if bars is None or len(bars) < 3:
                return []
            highs = [float(v) for v in bars["high"].values]
            lows = [float(v) for v in bars["low"].values]
            closes = [float(v) for v in bars["close"].values]
            times = list(getattr(bars, "index", []))
            current = closes[-1]
            zones: list[dict[str, Any]] = []
            start = max(2, len(highs) - int(lookback))
            for i in range(start, len(highs)):
                ts = 0
                if i < len(times) and hasattr(times[i], "timestamp"):
                    ts = int(times[i].timestamp())

                # Bullish FVG: demand imbalance between candle i-2 high and candle i low.
                if lows[i] > highs[i - 2]:
                    low = highs[i - 2]
                    high = lows[i]
                    subsequent_lows = lows[i + 1:] if i + 1 < len(lows) else []
                    filled = bool(subsequent_lows and min(subsequent_lows) <= low)
                    if not filled:
                        zones.append({
                            "type": "bull_fvg",
                            "low": round(low, 5),
                            "high": round(high, 5),
                            "mid": round((low + high) / 2.0, 5),
                            "time": ts,
                            "label": "Bull FVG",
                            "filled": False,
                            "distance": round(abs(((low + high) / 2.0) - current), 5),
                        })

                # Bearish FVG: supply imbalance between candle i high and candle i-2 low.
                if highs[i] < lows[i - 2]:
                    low = highs[i]
                    high = lows[i - 2]
                    subsequent_highs = highs[i + 1:] if i + 1 < len(highs) else []
                    filled = bool(subsequent_highs and max(subsequent_highs) >= high)
                    if not filled:
                        zones.append({
                            "type": "bear_fvg",
                            "low": round(low, 5),
                            "high": round(high, 5),
                            "mid": round((low + high) / 2.0, 5),
                            "time": ts,
                            "label": "Bear FVG",
                            "filled": False,
                            "distance": round(abs(((low + high) / 2.0) - current), 5),
                        })
            zones.sort(key=lambda z: float(z.get("distance", 0.0)))
            return zones[:max_zones]
        except Exception:
            return []

    def _market_levels(self, mt5, symbol: str, timeframe: str, bars, current: float) -> dict[str, Any]:
        try:
            point = self._symbol_point(mt5, symbol)
            current_price = float(current)
            levels: list[dict[str, Any]] = []

            volume = bars["volume"].astype(float)
            typical = (bars["high"].astype(float) + bars["low"].astype(float) + bars["close"].astype(float)) / 3.0
            vol_sum = float(volume.sum())
            vwap = float((typical * volume).sum() / vol_sum) if vol_sum > 0 else float(bars["close"].iloc[-1])

            def add_level(name: str, price: float, source: str) -> None:
                if not price or price != price or price <= 0:
                    return
                role = "support" if price < current_price else "resistance" if price > current_price else "touch"
                levels.append({
                    "name": name,
                    "price": round(float(price), 5),
                    "source": source,
                    "role": role,
                    "distance": round(abs(float(price) - current_price), 5),
                    "distance_points": round(abs(float(price) - current_price) / point, 1) if point > 0 else 0.0,
                })

            add_level("VWAP", vwap, "recent_session")

            pivot_levels: dict[str, float] = {}
            try:
                daily = self._fetch_bars(mt5, symbol, "D1", 4)
                if daily is not None and len(daily) >= 2:
                    from mt5_ai.pivot_engine import calculate_daily_pivots
                    pivot_levels = calculate_daily_pivots(daily.iloc[-2])
                    for key in ("PP", "R1", "R2", "S1", "S2", "M1", "M2", "M3", "M4"):
                        if key in pivot_levels:
                            add_level(key, float(pivot_levels[key]), "daily_pivot")
            except Exception:
                pivot_levels = {}

            levels.sort(key=lambda item: float(item.get("distance_points", 0.0)))
            supports = [x for x in levels if x.get("role") == "support"]
            resistances = [x for x in levels if x.get("role") == "resistance"]
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "current": round(current_price, 5),
                "point": point,
                "vwap": round(vwap, 5),
                "pivot_levels": {k: round(float(v), 5) for k, v in pivot_levels.items()},
                "levels": levels[:16],
                "nearest_support": supports[0] if supports else {},
                "nearest_resistance": resistances[0] if resistances else {},
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _classify_fusion_candle(self, open_: float, high: float, low: float, close: float, consensus: float) -> dict[str, Any]:
        rng = max(float(high) - float(low), 1e-9)
        body = abs(float(close) - float(open_))
        upper = float(high) - max(float(open_), float(close))
        lower = min(float(open_), float(close)) - float(low)
        body_pct = body / rng
        upper_pct = upper / rng
        lower_pct = lower / rng
        direction = "BUY" if close > open_ else "SELL" if close < open_ else "HOLD"

        if body_pct < 0.12:
            pattern = "Fusion Doji"
            bias = "HOLD"
        elif direction == "BUY" and body_pct >= 0.58 and consensus >= 0.65:
            pattern = "Bull Fusion Impulse"
            bias = "BUY"
        elif direction == "SELL" and body_pct >= 0.58 and consensus >= 0.65:
            pattern = "Bear Fusion Impulse"
            bias = "SELL"
        elif lower_pct >= 0.48 and direction == "BUY":
            pattern = "Bull Fusion Rejection"
            bias = "BUY"
        elif upper_pct >= 0.48 and direction == "SELL":
            pattern = "Bear Fusion Rejection"
            bias = "SELL"
        elif consensus < 0.55:
            pattern = "Mixed Frame Compression"
            bias = "HOLD"
        else:
            pattern = "Fusion Continuation"
            bias = direction

        return {
            "pattern": pattern,
            "bias": bias,
            "body_pct": round(body_pct, 3),
            "upper_wick_pct": round(upper_pct, 3),
            "lower_wick_pct": round(lower_pct, 3),
        }

    def _fusion_candle(self, mt5, symbol: str) -> dict[str, Any]:
        frames = (("M1", 1.0), ("M5", 2.0), ("M15", 3.0), ("H1", 5.0))
        candles: list[dict[str, Any]] = []
        try:
            for tf, weight in frames:
                df = self._fetch_bars(mt5, symbol, tf, 80 if tf == "M1" else 20)
                if df is None or df.empty:
                    continue
                row = df.iloc[-1]
                o = float(row["open"])
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])
                v = float(row.get("volume", 0.0) or 0.0)
                candles.append({
                    "timeframe": tf,
                    "weight": weight,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "direction": "BUY" if c > o else "SELL" if c < o else "HOLD",
                })
            if not candles:
                return {}

            weight_sum = sum(float(c["weight"]) for c in candles) or 1.0
            open_ = sum(float(c["open"]) * float(c["weight"]) for c in candles) / weight_sum
            close = sum(float(c["close"]) * float(c["weight"]) for c in candles) / weight_sum
            high = max(float(c["high"]) for c in candles)
            low = min(float(c["low"]) for c in candles)
            buy_count = sum(1 for c in candles if c["direction"] == "BUY")
            sell_count = sum(1 for c in candles if c["direction"] == "SELL")
            consensus = max(buy_count, sell_count) / max(1, len(candles))
            shape = self._classify_fusion_candle(open_, high, low, close, consensus)
            return {
                "symbol": symbol,
                "timeframes": [c["timeframe"] for c in candles],
                "open": round(open_, 5),
                "high": round(high, 5),
                "low": round(low, 5),
                "close": round(close, 5),
                "direction": "BUY" if close > open_ else "SELL" if close < open_ else "HOLD",
                "consensus": round(consensus, 3),
                "pattern": shape["pattern"],
                "bias": shape["bias"],
                "body_pct": shape["body_pct"],
                "upper_wick_pct": shape["upper_wick_pct"],
                "lower_wick_pct": shape["lower_wick_pct"],
                "components": candles,
            }
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        k = 2.0 / (period + 1.0)
        out = [float(values[0])]
        for value in values[1:]:
            out.append(float(value) * k + out[-1] * (1.0 - k))
        return out

    def _indicator_pack(self, bars, spread: float) -> dict[str, Any]:
        try:
            if bars is None or len(bars) < 35:
                return {}
            opens = [float(v) for v in bars["open"].values]
            highs = [float(v) for v in bars["high"].values]
            lows = [float(v) for v in bars["low"].values]
            closes = [float(v) for v in bars["close"].values]
            volumes = [float(v) for v in bars["volume"].values]
            n = len(closes)

            tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)]
            atr14 = sum(tr[-14:]) / max(1, min(14, len(tr)))

            deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
            gains = [max(0.0, d) for d in deltas[-14:]]
            losses = [abs(min(0.0, d)) for d in deltas[-14:]]
            avg_gain = sum(gains) / max(1, len(gains))
            avg_loss = sum(losses) / max(1, len(losses))
            rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

            plus_dm, minus_dm = [], []
            for i in range(1, n):
                up = highs[i] - highs[i - 1]
                down = lows[i - 1] - lows[i]
                plus_dm.append(up if up > down and up > 0 else 0.0)
                minus_dm.append(down if down > up and down > 0 else 0.0)
            tr14 = sum(tr[-14:]) or 1e-9
            plus_di = 100.0 * sum(plus_dm[-14:]) / tr14
            minus_di = 100.0 * sum(minus_dm[-14:]) / tr14
            dx = 100.0 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9)
            adx = dx

            ema12 = self._ema(closes, 12)
            ema26 = self._ema(closes, 26)
            macd_series = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
            signal_series = self._ema(macd_series, 9)
            macd_line = macd_series[-1]
            macd_signal = signal_series[-1] if signal_series else 0.0
            macd_hist = macd_line - macd_signal

            typ = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
            pos_flow = neg_flow = 0.0
            for i in range(max(1, n - 14), n):
                flow = typ[i] * volumes[i]
                if typ[i] > typ[i - 1]:
                    pos_flow += flow
                elif typ[i] < typ[i - 1]:
                    neg_flow += flow
            mfi = 100.0 if neg_flow == 0 else 100.0 - (100.0 / (1.0 + pos_flow / neg_flow))

            ema20 = self._ema(closes, 20)[-1]
            ema50 = self._ema(closes, 50)[-1] if len(closes) >= 50 else self._ema(closes, 34)[-1]
            ema_slope = ema20 - self._ema(closes[:-5], 20)[-1] if len(closes) > 25 else closes[-1] - closes[-5]
            ema_trend = "BUY" if closes[-1] > ema20 > ema50 and ema_slope > 0 else "SELL" if closes[-1] < ema20 < ema50 and ema_slope < 0 else "MIXED"

            momentum = closes[-1] - closes[-8]
            higher_closes = sum(1 for i in range(n - 5, n) if closes[i] > closes[i - 1])
            lower_closes = sum(1 for i in range(n - 5, n) if closes[i] < closes[i - 1])
            sig_trend = "BUY" if momentum > atr14 * 0.55 and higher_closes >= 3 else "SELL" if momentum < -atr14 * 0.55 and lower_closes >= 3 else "RANGE"

            dc_period = min(20, n - 2)
            dc_upper = max(highs[-dc_period - 1:-1])
            dc_lower = min(lows[-dc_period - 1:-1])
            breakout = "UP" if closes[-1] > dc_upper else "DOWN" if closes[-1] < dc_lower else "INSIDE"

            supply_high = max(highs[-50:])
            demand_low = min(lows[-50:])
            zone_pad = atr14 * 0.35
            avg_vol20 = sum(volumes[-20:]) / max(1, min(20, len(volumes)))
            voi = ((volumes[-1] / max(avg_vol20, 1e-9)) - 1.0) * 100.0
            tick_behavior = "surge" if voi > 35 else "drying" if voi < -35 else "normal"
            spread_status = "wide" if float(spread or 0.0) >= 300 else "normal"

            votes = {"BUY": 0, "SELL": 0}
            if rsi > 55: votes["BUY"] += 1
            if rsi < 45: votes["SELL"] += 1
            if plus_di > minus_di and adx >= 18: votes["BUY"] += 1
            if minus_di > plus_di and adx >= 18: votes["SELL"] += 1
            if macd_hist > 0: votes["BUY"] += 1
            if macd_hist < 0: votes["SELL"] += 1
            if mfi > 55: votes["BUY"] += 1
            if mfi < 45: votes["SELL"] += 1
            if ema_trend == "BUY": votes["BUY"] += 2
            if ema_trend == "SELL": votes["SELL"] += 2
            if sig_trend == "BUY" or breakout == "UP": votes["BUY"] += 1
            if sig_trend == "SELL" or breakout == "DOWN": votes["SELL"] += 1
            direction = "BUY" if votes["BUY"] > votes["SELL"] + 1 else "SELL" if votes["SELL"] > votes["BUY"] + 1 else "HOLD"
            confidence = min(0.9, 0.45 + abs(votes["BUY"] - votes["SELL"]) / 10.0)

            return {
                "classic": {
                    "rsi": round(rsi, 2),
                    "atr": round(atr14, 5),
                    "adx": round(adx, 2),
                    "plus_di": round(plus_di, 2),
                    "minus_di": round(minus_di, 2),
                    "macd": {"line": round(macd_line, 5), "signal": round(macd_signal, 5), "hist": round(macd_hist, 5)},
                    "mfi": round(mfi, 2),
                },
                "trend": {
                    "ema20": round(ema20, 5),
                    "ema50": round(ema50, 5),
                    "ema_slope": round(ema_slope, 5),
                    "ema_trend": ema_trend,
                    "sig_trend": sig_trend,
                    "classifier": direction,
                    "confidence": round(confidence, 3),
                    "votes": votes,
                },
                "structure": {
                    "donchian": {"upper": round(dc_upper, 5), "lower": round(dc_lower, 5), "breakout": breakout},
                    "demand_zone": {"low": round(demand_low, 5), "high": round(demand_low + zone_pad, 5)},
                    "supply_zone": {"low": round(supply_high - zone_pad, 5), "high": round(supply_high, 5)},
                },
                "volume": {
                    "voi_percent": round(voi, 2),
                    "tick_volume": round(volumes[-1], 2),
                    "avg_tick_volume_20": round(avg_vol20, 2),
                    "behavior": tick_behavior,
                },
                "microstructure": {
                    "spread_points": round(float(spread or 0.0), 1),
                    "spread_status": spread_status,
                    "last_candle_body_pct": round(abs(closes[-1] - opens[-1]) / max(highs[-1] - lows[-1], 1e-9), 3),
                },
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _market_structure_map(self, bars) -> dict[str, Any]:
        try:
            if bars is None or len(bars) < 30:
                return {}
            opens = [float(v) for v in bars["open"].values]
            highs = [float(v) for v in bars["high"].values]
            lows = [float(v) for v in bars["low"].values]
            closes = [float(v) for v in bars["close"].values]
            volumes = [float(v) for v in bars["volume"].values]
            times = list(getattr(bars, "index", []))
            n = len(closes)
            current = closes[-1]

            tr_values = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)]
            atr = sum(tr_values[-14:]) / max(1, min(14, len(tr_values)))
            tolerance = max(atr * 0.35, 0.0001)

            swings_high: list[dict[str, Any]] = []
            swings_low: list[dict[str, Any]] = []
            for i in range(2, n - 2):
                ts = int(times[i].timestamp()) if i < len(times) and hasattr(times[i], "timestamp") else i
                if highs[i] >= max(highs[i - 2:i + 3]):
                    swings_high.append({"index": i, "time": ts, "price": round(highs[i], 5)})
                if lows[i] <= min(lows[i - 2:i + 3]):
                    swings_low.append({"index": i, "time": ts, "price": round(lows[i], 5)})

            last_high = swings_high[-1] if swings_high else {}
            last_low = swings_low[-1] if swings_low else {}
            bos = "NONE"
            if last_high and current > float(last_high["price"]):
                bos = "BULLISH_BOS"
            elif last_low and current < float(last_low["price"]):
                bos = "BEARISH_BOS"

            order_block: dict[str, Any] = {}
            search_start = max(0, n - 28)
            if bos == "BULLISH_BOS":
                for i in range(n - 2, search_start, -1):
                    if closes[i] < opens[i]:
                        order_block = {"type": "bullish_ob", "low": round(lows[i], 5), "high": round(highs[i], 5), "origin_index": i}
                        break
            elif bos == "BEARISH_BOS":
                for i in range(n - 2, search_start, -1):
                    if closes[i] > opens[i]:
                        order_block = {"type": "bearish_ob", "low": round(lows[i], 5), "high": round(highs[i], 5), "origin_index": i}
                        break

            liquidity: list[dict[str, Any]] = []
            for source, side in ((swings_high[-10:], "buy_side_liquidity"), (swings_low[-10:], "sell_side_liquidity")):
                used: set[int] = set()
                for idx, lvl in enumerate(source):
                    if idx in used:
                        continue
                    cluster = [lvl]
                    used.add(idx)
                    for j, other in enumerate(source[idx + 1:], idx + 1):
                        if j not in used and abs(float(other["price"]) - float(lvl["price"])) <= tolerance:
                            cluster.append(other)
                            used.add(j)
                    if len(cluster) >= 2:
                        price = sum(float(x["price"]) for x in cluster) / len(cluster)
                        liquidity.append({
                            "type": side,
                            "price": round(price, 5),
                            "touches": len(cluster),
                            "distance": round(abs(price - current), 5),
                            "above_price": price > current,
                        })
            liquidity.sort(key=lambda x: float(x["distance"]))

            ifvgs: list[dict[str, Any]] = []
            start = max(2, n - 90)
            for i in range(start, n):
                ts = int(times[i].timestamp()) if i < len(times) and hasattr(times[i], "timestamp") else i
                if lows[i] > highs[i - 2]:
                    low, high = highs[i - 2], lows[i]
                    if current < low:
                        ifvgs.append({"type": "bearish_ifvg", "low": round(low, 5), "high": round(high, 5), "time": ts, "distance": round(abs(((low + high) / 2) - current), 5)})
                if highs[i] < lows[i - 2]:
                    low, high = highs[i], lows[i - 2]
                    if current > high:
                        ifvgs.append({"type": "bullish_ifvg", "low": round(low, 5), "high": round(high, 5), "time": ts, "distance": round(abs(((low + high) / 2) - current), 5)})
            ifvgs.sort(key=lambda x: float(x["distance"]))

            drift_window = min(24, n - 1)
            drift = closes[-1] - closes[-drift_window]
            drift_atr = drift / max(atr, 1e-9)
            drift_angle = math.degrees(math.atan(drift_atr / max(1, drift_window)))
            recent_ranges = [highs[i] - lows[i] for i in range(max(0, n - 6), n)]
            avg_recent_range = sum(recent_ranges) / max(1, len(recent_ranges))
            last5 = closes[-5:]
            rising = sum(1 for i in range(1, len(last5)) if last5[i] > last5[i - 1])
            falling = sum(1 for i in range(1, len(last5)) if last5[i] < last5[i - 1])
            micro = "compression" if avg_recent_range < atr * 0.65 else "micro_rise" if rising >= 4 else "micro_drop" if falling >= 4 else "mixed_micro"
            volume_surge = bool(volumes[-1] > (sum(volumes[-20:]) / max(1, min(20, len(volumes)))) * 1.35)

            score = 0.0
            reasons: list[str] = []
            if bos == "BULLISH_BOS":
                score += 2.0; reasons.append("bullish_bos")
            elif bos == "BEARISH_BOS":
                score -= 2.0; reasons.append("bearish_bos")
            for z in ifvgs[:2]:
                if z["type"] == "bullish_ifvg":
                    score += 1.1; reasons.append("bullish_ifvg")
                if z["type"] == "bearish_ifvg":
                    score -= 1.1; reasons.append("bearish_ifvg")
            if drift_atr > 0.6:
                score += 0.8; reasons.append("positive_drift")
            elif drift_atr < -0.6:
                score -= 0.8; reasons.append("negative_drift")
            if micro == "micro_rise":
                score += 0.5; reasons.append("micro_rise")
            elif micro == "micro_drop":
                score -= 0.5; reasons.append("micro_drop")
            if volume_surge:
                score *= 1.08
                reasons.append("volume_surge")

            bias = "BUY" if score >= 1.6 else "SELL" if score <= -1.6 else "HOLD"
            confidence = min(0.86, 0.45 + abs(score) / 7.0)
            return {
                "current": round(current, 5),
                "atr": round(atr, 5),
                "bos": bos,
                "order_block": order_block,
                "ifvg": ifvgs[:8],
                "liquidity": liquidity[:8],
                "swings": {"highs": swings_high[-8:], "lows": swings_low[-8:]},
                "drift": {"delta": round(drift, 5), "atr_multiple": round(drift_atr, 3), "angle": round(drift_angle, 2)},
                "micro_pattern": micro,
                "volume_surge": volume_surge,
                "prediction": {"bias": bias, "confidence": round(confidence, 3), "score": round(score, 3), "reasons": reasons[:8]},
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _pending_side_from_signals(self, raw_signals: list, arb, cfg: dict[str, Any], forced_side: str | None, forced_confidence: float | None) -> tuple[str | None, float, str]:
        from mt5_ai.core.signal_schema import Direction

        if forced_side in {"BUY", "SELL"}:
            return forced_side, float(forced_confidence or getattr(arb, "final_confidence", 0.0) or 0.0), "confirmed_market_bias"

        pending_cfg = cfg.get("level_pending_orders", {}) if isinstance(cfg, dict) else {}
        min_conf = float(pending_cfg.get("min_confidence", 0.47) or 0.47)
        min_smc = float(pending_cfg.get("min_smc_confidence", 0.58) or 0.58)

        smc = next((s for s in raw_signals if getattr(s, "source", "") == "smc_agent" and s.direction in (Direction.BUY, Direction.SELL)), None)
        if smc is not None and float(getattr(smc, "confidence", 0.0) or 0.0) >= min_smc:
            return smc.direction.value, float(smc.confidence), "smc_level_bias"

        if getattr(arb, "final_direction", Direction.HOLD) in (Direction.BUY, Direction.SELL):
            conf = float(getattr(arb, "final_confidence", 0.0) or 0.0)
            if conf >= min_conf:
                return arb.final_direction.value, conf, "arbiter_level_bias"

        buy_score = float(getattr(arb, "buy_agent_score", 0.0) or 0.0)
        sell_score = float(getattr(arb, "sell_agent_score", 0.0) or 0.0)
        conf = float(getattr(arb, "final_confidence", 0.0) or 0.0)
        min_gap = float(pending_cfg.get("min_score_gap", 0.12) or 0.12)
        if conf >= min_conf and abs(buy_score - sell_score) >= min_gap:
            return ("BUY" if buy_score > sell_score else "SELL"), conf, "score_gap_level_bias"

        return None, conf, f"no_pending_bias:conf={conf:.3f},buy={buy_score:.3f},sell={sell_score:.3f}"

    def _pending_order_duplicate(self, mt5, symbol: str, side: str, price: float, magic: int, tolerance: float) -> bool:
        try:
            orders = list(mt5.orders_get(symbol=symbol) or [])
            buy_types = {getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2), getattr(mt5, "ORDER_TYPE_BUY_STOP", 4)}
            sell_types = {getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3), getattr(mt5, "ORDER_TYPE_SELL_STOP", 5)}
            wanted = buy_types if side == "BUY" else sell_types
            for order in orders:
                if int(getattr(order, "magic", -1) or -1) != int(magic):
                    continue
                if int(getattr(order, "type", -1) or -1) not in wanted:
                    continue
                if abs(float(getattr(order, "price_open", 0.0) or 0.0) - float(price)) <= tolerance:
                    return True
        except Exception:
            return False
        return False

    def _pick_pending_level(self, mt5, symbol: str, side: str, bars, market_levels: dict[str, Any], current: float, sl_dist: float, cfg: dict[str, Any]) -> dict[str, Any]:
        pending_cfg = cfg.get("level_pending_orders", {}) if isinstance(cfg, dict) else {}
        point = self._symbol_point(mt5, symbol)
        min_points = float(pending_cfg.get("min_distance_points", 80) or 80)
        max_points = float(pending_cfg.get("max_distance_points", 3500) or 3500)

        candidates: list[dict[str, Any]] = []
        for level in market_levels.get("levels", []) if isinstance(market_levels, dict) else []:
            price = float(level.get("price", 0.0) or 0.0)
            if side == "BUY" and price < current:
                candidates.append({**level, "order_type": "BUY_LIMIT"})
            if side == "SELL" and price > current:
                candidates.append({**level, "order_type": "SELL_LIMIT"})

        for zone in self._detect_fvg_zones(bars, lookback=120, max_zones=20):
            z_mid = float(zone.get("mid", 0.0) or 0.0)
            if side == "BUY" and zone.get("type") == "bull_fvg" and z_mid < current:
                candidates.append({"name": zone.get("label", "Bull FVG"), "price": z_mid, "source": "fvg", "role": "support", "order_type": "BUY_LIMIT"})
            if side == "SELL" and zone.get("type") == "bear_fvg" and z_mid > current:
                candidates.append({"name": zone.get("label", "Bear FVG"), "price": z_mid, "source": "fvg", "role": "resistance", "order_type": "SELL_LIMIT"})

        valid: list[dict[str, Any]] = []
        for item in candidates:
            price = float(item.get("price", 0.0) or 0.0)
            dist_points = abs(float(current) - price) / point if point > 0 else 0.0
            if min_points <= dist_points <= max_points:
                valid.append({**item, "price": round(price, 5), "distance_points": round(dist_points, 1)})
        valid.sort(key=lambda item: float(item.get("distance_points", 0.0)))
        if not valid:
            return {"ok": False, "reason": f"no_level_in_pending_range:{side}:min={min_points},max={max_points}"}

        level = valid[0]
        entry = float(level["price"])
        if side == "BUY":
            sl = round(entry - sl_dist, 5)
            resistance = market_levels.get("nearest_resistance", {}) if isinstance(market_levels, dict) else {}
            tp_level = float(resistance.get("price", 0.0) or 0.0)
            tp = self._fvg_tp(bars, entry, sl_dist, "BUY") or (round(tp_level, 5) if tp_level > entry + sl_dist * 1.5 else round(entry + sl_dist * 2.0, 5))
        else:
            sl = round(entry + sl_dist, 5)
            support = market_levels.get("nearest_support", {}) if isinstance(market_levels, dict) else {}
            tp_level = float(support.get("price", 0.0) or 0.0)
            tp = self._fvg_tp(bars, entry, sl_dist, "SELL") or (round(tp_level, 5) if 0 < tp_level < entry - sl_dist * 1.5 else round(entry - sl_dist * 2.0, 5))

        return {
            "ok": True,
            "side": side,
            "order_type": level["order_type"],
            "price": entry,
            "sl": sl,
            "tp": tp,
            "level_name": str(level.get("name", "level")),
            "level_source": str(level.get("source", "")),
            "distance_points": level.get("distance_points", 0.0),
            "reason": f"{level['order_type']}@{level.get('name')}:{level.get('distance_points')}pts",
        }

    def _maybe_place_pending_level_order(
        self,
        mt5,
        symbol: str,
        timeframe: str,
        bars,
        raw_signals: list,
        arb,
        market_levels: dict[str, Any],
        spread: float,
        open_positions: int,
        risk_mgr,
        exec_mgr,
        cfg: dict[str, Any],
        forced_side: str | None = None,
        forced_confidence: float | None = None,
    ) -> dict[str, Any]:
        pending_cfg = cfg.get("level_pending_orders", {}) if isinstance(cfg, dict) else {}
        if not bool(pending_cfg.get("enabled", False)):
            return {"evaluated": False, "reason": "level_pending_orders_disabled"}
        if not self._allow_new_entries:
            return {"evaluated": True, "status": "blocked", "order_send_called": False, "reason": "new_entries_disabled"}

        side, confidence, bias_reason = self._pending_side_from_signals(raw_signals, arb, cfg, forced_side, forced_confidence)
        if side not in {"BUY", "SELL"}:
            return {"evaluated": True, "status": "no_bias", "order_send_called": False, "reason": bias_reason}

        from mt5_ai.core.indicators import atr as calc_atr
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC
        from mt5_ai.core.signal_schema import DecisionResult, Direction, ExecutionRequest

        current = float(market_levels.get("current", bars["close"].iloc[-1]) if isinstance(market_levels, dict) else bars["close"].iloc[-1])
        point = self._symbol_point(mt5, symbol)
        try:
            symbol_info = mt5.symbol_info(symbol)
            min_stop_points = float(getattr(symbol_info, "trade_stops_level", 0.0) or 0.0)
        except Exception:
            min_stop_points = 0.0
        sl_dist = max(calc_atr(bars, period=14) * 1.5, point * max(min_stop_points * 2.0, 300.0), 0.0001)
        plan = self._pick_pending_level(mt5, symbol, side, bars, market_levels, current, sl_dist, cfg)
        if not plan.get("ok"):
            return {"evaluated": True, "status": "no_level", "order_send_called": False, "plan": plan, "reason": plan.get("reason", "no_pending_level")}

        exec_cfg = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        magic_number = int(exec_cfg.get("magic_number") or QADER_REAL_CONTROLLED_MAGIC)
        cooldown = float(pending_cfg.get("cooldown_seconds", 120) or 120)
        cooldown_key = f"{symbol}:{side}:{plan['level_name']}:{round(float(plan['price']), 2)}"
        last_at = float(self._last_pending_at.get(cooldown_key, 0.0) or 0.0)
        if cooldown > 0 and time.time() - last_at < cooldown:
            remaining = int(max(0.0, cooldown - (time.time() - last_at)))
            return {"evaluated": True, "status": "cooldown", "order_send_called": False, "plan": plan, "reason": f"pending_level_cooldown:{remaining}s"}

        tolerance = point * float(pending_cfg.get("duplicate_tolerance_points", 120) or 120)
        if self._pending_order_duplicate(mt5, symbol, side, float(plan["price"]), magic_number, tolerance):
            return {"evaluated": True, "status": "duplicate", "order_send_called": False, "plan": plan, "reason": "similar_pending_order_exists"}

        decision = DecisionResult(
            action=Direction(side),
            symbol=symbol,
            timeframe=timeframe,
            confidence=float(confidence),
            approved_sources=["level_pending", bias_reason],
            reason=f"{bias_reason}|{plan['reason']}",
            raw_signals=[],
        )
        risk_decision = risk_mgr.validate(
            decision,
            symbol,
            spread_points=spread,
            open_positions=open_positions,
            daily_loss_pct=self._daily_loss_pct(mt5),
        )
        if not risk_decision.approved:
            return {"evaluated": True, "status": "risk_blocked", "order_send_called": False, "plan": plan, "reason": "pending_risk_blocked:" + risk_decision.reason}

        comment_prefix = str(exec_cfg.get("comment") or "QADER_DEMO")
        req = ExecutionRequest(
            action=Direction(side),
            symbol=symbol,
            lot=risk_decision.adjusted_lot,
            price=float(plan["price"]),
            sl=float(plan["sl"]),
            tp=float(plan["tp"]),
            deviation=int(exec_cfg.get("deviation", 20) or 20),
            magic=magic_number,
            comment=f"{comment_prefix}|PEND|ARB|LEVEL",
            risk_decision=risk_decision,
            confidence=float(confidence),
            signal_arbiter_passed=True,
            conflict_guard_passed=True,
        )
        result = exec_mgr.execute_pending_limit(req)
        if result.success and not result.simulated:
            self._last_pending_at[cooldown_key] = time.time()
            self._write_journal({
                "event": "demo_pending_order",
                "symbol": symbol,
                "timeframe": timeframe,
                "action": side,
                "order_type": plan["order_type"],
                "lot": risk_decision.adjusted_lot,
                "entry": plan["price"],
                "sl": plan["sl"],
                "tp": plan["tp"],
                "level": plan["level_name"],
                "level_source": plan["level_source"],
                "confidence": round(float(confidence), 4),
                "reason": decision.reason,
                "order": result.order,
                "deal": result.deal,
                "retcode": result.retcode,
            })
        return {
            "evaluated": True,
            "status": "placed" if result.success else "failed",
            "order_send_called": True,
            "success": result.success,
            "retcode": result.retcode,
            "order": result.order,
            "deal": result.deal,
            "plan": plan,
            "reason": result.message or decision.reason,
        }

    def _fvg_tp(self, bars, entry: float, sl_dist: float, direction: str) -> float | None:
        """Use the nearest open imbalance in the take-profit direction as TP."""
        try:
            zones = self._detect_fvg_zones(bars, lookback=120, max_zones=30)
            min_reward = sl_dist * 1.5
            max_reward = sl_dist * 5.0
            if direction == "BUY":
                targets = [
                    z for z in zones
                    if float(z["mid"]) > entry
                    and min_reward <= float(z["mid"]) - entry <= max_reward
                ]
                targets.sort(key=lambda z: (0 if z["type"] == "bear_fvg" else 1, float(z["mid"])))
                return round(float(targets[0]["mid"]), 5) if targets else None

            targets = [
                z for z in zones
                if float(z["mid"]) < entry
                and min_reward <= entry - float(z["mid"]) <= max_reward
            ]
            targets.sort(key=lambda z: (0 if z["type"] == "bull_fvg" else 1, -float(z["mid"])))
            return round(float(targets[0]["mid"]), 5) if targets else None
        except Exception:
            return None

    def _position_side(self, mt5, pos) -> str:
        buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0)
        return "BUY" if int(getattr(pos, "type", buy_type)) == int(buy_type) else "SELL"

    def _log_heartbeat(self) -> None:
        self._write_loop_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_number": self.cycle_count,
            "loop_state": self.state,
            "event": "heartbeat",
            "reason": self.state_reason,
        })
