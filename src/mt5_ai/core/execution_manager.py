"""
execution_manager.py
--------------------
The ONLY component allowed to send orders to MT5.

Rules:
1. Receives only approved ExecutionRequest objects
2. Checks kill_switch + allow_live_trading before every send
3. Validates magic number via registry
4. In DRY_RUN mode: logs simulation, never calls MT5
5. Returns ExecutionResult always — never raises
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from .signal_schema import ExecutionRequest, ExecutionResult, Direction
from .config_loader import (
    get,
    is_kill_switch,
    is_live_allowed,
    is_dry_run,
    is_real_controlled_allowed,
    is_real_controlled_mode,
    load as cfg_load,
)
from .magic_registry import QADER_REAL_CONTROLLED_MAGIC, validate_request
from .market_quality import current_market_session, spread_quality
from .structured_logger import log_execution, log_error

log = logging.getLogger("execution_manager")


class ExecutionManager:
    def __init__(self) -> None:
        self._gateway = None  # lazy import to avoid MT5 init at import time
        self._real_orders_sent_this_run = 0

    def _get_gateway(self):
        if self._gateway is None:
            from mt5_ai.mt5_gateway import MT5Gateway
            self._gateway = MT5Gateway()
        return self._gateway

    def reset_real_controlled_run(self) -> None:
        self._real_orders_sent_this_run = 0

    @staticmethod
    def _audit(action: str, allowed: bool, reason: str, result=None, metadata: dict | None = None) -> None:
        try:
            from qader_app.storage.audit_log import log_action

            log_action(
                action,
                "can_place_live_orders",
                allowed,
                reason,
                "execution_manager",
                result=result,
                metadata=metadata,
            )
        except Exception:
            log.info("[QADER_AUDIT_FALLBACK] action=%s allowed=%s reason=%s", action, allowed, reason)

    @staticmethod
    def _gate(gates: list[dict], name: str, passed: bool, reason: str) -> None:
        gates.append({"gate": name, "passed": bool(passed), "reason": str(reason)})

    @staticmethod
    def _is_qader_demo_config(cfg: dict) -> bool:
        runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
        execution = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        return bool(cfg.get("demo_only") or runtime.get("demo_only") or execution.get("demo_only"))

    @staticmethod
    def _account_status(mt5_module=None) -> dict[str, Any]:
        try:
            mt5 = mt5_module
            if mt5 is None:
                import MetaTrader5 as mt5
            info = mt5.account_info()
            if info is None:
                initialized = mt5.initialize()
                info = mt5.account_info() if initialized else None
            if info is None:
                return {"readable": False, "demo_or_trial": False, "last_error": getattr(mt5, "last_error", lambda: None)()}

            server = str(getattr(info, "server", "") or "")
            trade_mode_raw = getattr(info, "trade_mode", -1)
            trade_mode = int(-1 if trade_mode_raw is None else trade_mode_raw)
            demo_constant = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
            server_demo = any(keyword in server.lower() for keyword in ("demo", "trial"))
            demo_or_trial = trade_mode == demo_constant or server_demo
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
                "demo_or_trial": demo_or_trial,
            }
        except Exception as exc:
            return {"readable": False, "demo_or_trial": False, "error": str(exc)}

    def _switch_to_demo_only_blocked(self, account: dict[str, Any]) -> None:
        try:
            from qader_app.storage.settings_store import PermissionsStore, SettingsStore

            SettingsStore().save({
                "mode": "demo_only",
                "safety_status": "DEMO_ONLY_BLOCKED_REAL_ACCOUNT",
                "last_account_status": account,
            })
            PermissionsStore().lock_real_controlled_mode("blocked_real_account_demo_only")
        except Exception:
            pass
        self._audit(
            "demo_only_real_account_block",
            False,
            "connected_account_is_not_demo_or_trial",
            result={"account": account},
        )

    def _base_real_controlled_gates(self, cfg: dict, mt5_module=None) -> tuple[list[dict], dict[str, Any]]:
        runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
        execution = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        gates: list[dict] = []
        self._gate(gates, "runtime_mode", runtime.get("mode") == "REAL_CONTROLLED_MODE", f"mode={runtime.get('mode')}")
        self._gate(gates, "allow_live_trading", runtime.get("allow_live_trading") is True, f"allow_live_trading={runtime.get('allow_live_trading')}")
        self._gate(gates, "demo_only_config", self._is_qader_demo_config(cfg), f"demo_only={self._is_qader_demo_config(cfg)}")
        self._gate(gates, "simulate_only_false", execution.get("simulate_only") is False, f"simulate_only={execution.get('simulate_only')}")
        self._gate(gates, "dry_run_false", execution.get("dry_run") is False and runtime.get("mode") != "DRY_RUN", f"dry_run={execution.get('dry_run')}")
        self._gate(gates, "kill_switch_false", not is_kill_switch(), f"kill_switch={is_kill_switch()}")
        self._gate(gates, "real_controlled_allowed_by_config", is_real_controlled_allowed(), "config_loader gate")
        self._gate(gates, "pending_orders_config_present", "pending_orders_enabled" in execution, f"pending_orders_enabled={execution.get('pending_orders_enabled')}")
        self._gate(gates, "no_averaging", execution.get("averaging_enabled") is False, f"averaging_enabled={execution.get('averaging_enabled')}")
        self._gate(gates, "no_martingale", execution.get("martingale_enabled") is False, f"martingale_enabled={execution.get('martingale_enabled')}")
        self._gate(gates, "no_grid", execution.get("grid_enabled") is False, f"grid_enabled={execution.get('grid_enabled')}")
        self._gate(gates, "no_pyramiding", execution.get("pyramiding_enabled") is False, f"pyramiding_enabled={execution.get('pyramiding_enabled')}")
        self._gate(gates, "no_reentry_loop", execution.get("reentry_loop_enabled") is False, f"reentry_loop_enabled={execution.get('reentry_loop_enabled')}")

        account = self._account_status(mt5_module)
        self._gate(gates, "account_info_readable", bool(account.get("readable")), f"login={account.get('login')}")
        self._gate(gates, "demo_or_trial_account", bool(account.get("demo_or_trial")), f"server={account.get('server')},trade_mode={account.get('trade_mode')}")
        return gates, account

    @staticmethod
    def _fresh_lockdown_timestamp(value: str, max_age_minutes: int) -> tuple[bool, str]:
        if not value:
            return False, "missing_lockdown_timestamp"
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
            limit = max(1, int(max_age_minutes)) * 60
            return age <= limit, f"age_seconds={age:.0f},limit_seconds={limit}"
        except Exception as exc:
            return False, f"invalid_lockdown_timestamp:{exc}"

    def validate_real_controlled_request(self, req: ExecutionRequest | None, mt5_module=None) -> dict:
        cfg = cfg_load()
        runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
        execution = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        risk = cfg.get("risk", {}) if isinstance(cfg, dict) else {}
        confidence_cfg = cfg.get("confidence", {}) if isinstance(cfg, dict) else {}
        gates, account = self._base_real_controlled_gates(cfg, mt5_module)
        max_run_orders = int(execution.get("max_market_orders_per_run", 1) or 1)
        self._gate(
            gates,
            "max_market_orders_per_run",
            self._real_orders_sent_this_run < max_run_orders,
            f"sent_this_run={self._real_orders_sent_this_run},max={max_run_orders}",
        )

        try:
            from qader_app.storage.settings_store import PermissionsStore

            permissions = PermissionsStore().load()
        except Exception as exc:
            permissions = {}
            self._gate(gates, "qader_permissions_readable", False, str(exc))
        else:
            self._gate(gates, "qader_permissions_readable", True, "permissions loaded")
        unlocked = bool(permissions.get("_real_controlled_mode_unlocked"))
        phrase_confirmed = bool(permissions.get("_real_unlock_phrase_confirmed"))
        permission_live = bool(permissions.get("can_place_live_orders"))
        lockdown_value = permissions.get("_real_lockdown_exit_code", 1)
        lockdown_exit = int(1 if lockdown_value is None else lockdown_value)
        fresh_lockdown, fresh_reason = self._fresh_lockdown_timestamp(
            str(permissions.get("_real_lockdown_verified_at", "")),
            int(runtime.get("max_runtime_minutes") or 10),
        )
        self._gate(gates, "permission_can_place_live_orders", permission_live, f"can_place_live_orders={permission_live}")
        self._gate(gates, "real_mode_unlocked", unlocked, f"unlocked={unlocked}")
        self._gate(gates, "unlock_phrase_confirmed", phrase_confirmed, f"phrase_confirmed={phrase_confirmed}")
        self._gate(gates, "lockdown_exit_code_zero", lockdown_exit == 0, f"exit_code={lockdown_exit}")
        self._gate(gates, "lockdown_recent", fresh_lockdown, fresh_reason)

        if req is None:
            self._gate(gates, "execution_request_present", False, "no ExecutionRequest supplied")
        else:
            ok, msg = req.is_valid()
            min_conf = float(confidence_cfg.get("min_decision_confidence", get("confidence.min_decision_confidence") or 0.55))
            fixed_lot = float(risk.get("fixed_lot", 0.01) or 0.01)
            max_lot = float(risk.get("max_lot", 0.01) or 0.01)
            req_conf = float(getattr(req, "confidence", 0.0) or 0.0)
            rd_ok = bool(req.risk_decision and req.risk_decision.approved)
            self._gate(gates, "execution_request_valid", ok, msg)
            self._gate(gates, "action_buy_or_sell", req.action in (Direction.BUY, Direction.SELL), f"action={req.action.value}")
            arbiter_gate = req.action in (Direction.BUY, Direction.SELL) and bool(req.signal_arbiter_passed) and "ARB" in req.comment
            self._gate(gates, "signal_arbiter_final_buy_sell", arbiter_gate, f"arbiter_passed={req.signal_arbiter_passed},comment={req.comment}")
            self._gate(gates, "conflict_guard_passed", bool(req.conflict_guard_passed), f"conflict_guard_passed={req.conflict_guard_passed}")
            self._gate(gates, "final_confidence_threshold", req_conf >= min_conf, f"confidence={req_conf:.3f},threshold={min_conf:.3f}")
            self._gate(gates, "risk_manager_approved", rd_ok, "RiskDecision approved" if rd_ok else "RiskDecision missing or blocked")
            self._gate(gates, "sl_required", float(req.sl or 0.0) > 0, f"sl={req.sl}")
            self._gate(gates, "tp_or_trailing_required", float(req.tp or 0.0) > 0, f"tp={req.tp}")
            self._gate(gates, "lot_fixed", abs(float(req.lot) - fixed_lot) < 1e-9, f"lot={req.lot},fixed_lot={fixed_lot}")
            self._gate(gates, "lot_within_max", 0 < float(req.lot) <= max_lot, f"lot={req.lot},max_lot={max_lot}")
            cfg_magic = int(execution.get("magic_number") or QADER_REAL_CONTROLLED_MAGIC)
            self._gate(gates, "magic_number_qader_real", int(req.magic) == cfg_magic == QADER_REAL_CONTROLLED_MAGIC, f"req_magic={req.magic},cfg_magic={cfg_magic}")
            self._gate(gates, "comment_qader_real", str(execution.get("comment") or "") in req.comment, f"comment={req.comment}")

        try:
            mt5 = mt5_module
            if mt5 is None:
                import MetaTrader5 as mt5
            positions = list(mt5.positions_get() or [])
            orders = list(mt5.orders_get() or [])
            qader_positions = [p for p in positions if int(getattr(p, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC]
            non_qader_positions = [p for p in positions if int(getattr(p, "magic", -1) or -1) != QADER_REAL_CONTROLLED_MAGIC]
            qader_orders = [o for o in orders if int(getattr(o, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC]
            non_qader_orders = [o for o in orders if int(getattr(o, "magic", -1) or -1) != QADER_REAL_CONTROLLED_MAGIC]
            def _magic(value: Any) -> int:
                try:
                    return int(getattr(value, "magic", -1))
                except Exception:
                    return -1

            allow_external_pending = bool(risk.get("allow_external_pending_orders", False))
            magic0_positions = [_p for _p in positions if _magic(_p) == 0]
            magic0_orders = [_o for _o in orders if _magic(_o) == 0]
            account = {
                **account,
                "open_positions": len(positions),
                "qader_open_positions": len(qader_positions),
                "non_qader_open_positions": len(non_qader_positions),
                "pending_orders": len(orders),
                "qader_pending_orders": len(qader_orders),
                "non_qader_pending_orders": len(non_qader_orders),
                "external_magic0_position_exposure": bool(magic0_positions),
                "external_magic0_pending_exposure": bool(magic0_orders),
                "external_magic0_exposure": bool(magic0_positions) or (bool(magic0_orders) and not allow_external_pending),
                "allow_external_pending_orders": allow_external_pending,
            }
        except Exception as exc:
            self._gate(gates, "account_positions_readable", False, str(exc))
            positions = []
            orders = []
            qader_positions = []
            non_qader_positions = []
        else:
            max_open = int(risk.get("max_open_positions", 1) or 1)
            max_pending = int(risk.get("max_pending_orders", 0) or 0)
            self._gate(gates, "account_positions_readable", True, f"positions={len(positions)},orders={len(orders)}")
            self._gate(
                gates,
                "open_positions_clean",
                len(qader_positions) < max_open and len(non_qader_positions) == 0,
                f"qader_open_positions={len(qader_positions)},non_qader={len(non_qader_positions)},max={max_open}",
            )
            self._gate(
                gates,
                "pending_orders_within_limit",
                len(qader_orders) <= max_pending and (allow_external_pending or len(non_qader_orders) == 0),
                f"qader_pending_orders={len(qader_orders)},non_qader={len(non_qader_orders)},max={max_pending},allow_external_pending={allow_external_pending}",
            )
            self._gate(gates, "magic0_external_exposure_none", not account["external_magic0_exposure"], f"external_magic0={account['external_magic0_exposure']}")

            if req is not None:
                try:
                    mt5 = mt5_module
                    if mt5 is None:
                        import MetaTrader5 as mt5
                    symbol_info = mt5.symbol_info(req.symbol)
                    spread = float(getattr(symbol_info, "spread", float("inf")) if symbol_info else float("inf"))
                except Exception as exc:
                    spread = float("inf")
                    spread_reason = f"spread_read_failed:{exc}"
                else:
                    spread_reason = f"spread={spread}"
                max_spread_config = risk.get("max_spread_points", {})
                if isinstance(max_spread_config, dict):
                    max_spread = float(max_spread_config.get(req.symbol, max_spread_config.get("default", 350)) or 350)
                else:
                    max_spread = float(max_spread_config or 350)
                quality = spread_quality(req.symbol, spread, max_spread)
                account = {
                    **account,
                    "session": current_market_session(),
                    "spread": spread,
                    "spread_quality": quality["spread_quality"],
                    "spread_limit": quality["spread_limit"],
                    "spread_ratio": quality["spread_ratio"],
                }
                self._gate(gates, "spread_within_limit", spread <= max_spread, f"{spread_reason},max={max_spread}")

        allowed = all(g["passed"] for g in gates)
        return {
            "allowed": allowed,
            "mode": "REAL_CONTROLLED_MODE",
            "gates": gates,
            "account": account,
            "orders_sent_this_run": self._real_orders_sent_this_run,
        }

    def validate_real_controlled_management_request(self, req: ExecutionRequest | None, mt5_module=None) -> dict:
        cfg = cfg_load()
        gates, account = self._base_real_controlled_gates(cfg, mt5_module)
        execution = cfg.get("execution", {}) if isinstance(cfg, dict) else {}

        if req is None:
            self._gate(gates, "execution_request_present", False, "no ExecutionRequest supplied")
        else:
            ok, msg = req.is_valid()
            self._gate(gates, "execution_request_valid", ok, msg)
            self._gate(gates, "management_action", req.action in (Direction.CLOSE, Direction.REDUCE, Direction.TRAIL_ONLY), f"action={req.action.value}")
            self._gate(gates, "position_ticket_required", int(req.position_ticket or 0) > 0, f"ticket={req.position_ticket}")
            self._gate(gates, "magic_number_qader_real", int(req.magic) == QADER_REAL_CONTROLLED_MAGIC, f"req_magic={req.magic}")
            self._gate(gates, "comment_qader_real", str(execution.get("comment") or "") in req.comment, f"comment={req.comment}")
            if req.action == Direction.TRAIL_ONLY:
                self._gate(gates, "sl_or_tp_modify_present", float(req.sl or 0.0) > 0 or float(req.tp or 0.0) > 0, f"sl={req.sl},tp={req.tp}")

        try:
            mt5 = mt5_module
            if mt5 is None:
                import MetaTrader5 as mt5
            positions = list(mt5.positions_get() or [])
            target = next((p for p in positions if int(getattr(p, "ticket", 0) or 0) == int(req.position_ticket if req else 0)), None)
            self._gate(gates, "position_found", target is not None, f"ticket={getattr(req, 'position_ticket', 0)}")
            if target is not None:
                self._gate(
                    gates,
                    "position_magic_qader",
                    int(getattr(target, "magic", -1) or -1) == QADER_REAL_CONTROLLED_MAGIC,
                    f"position_magic={getattr(target, 'magic', None)}",
                )
                account = {**account, "target_position": {
                    "ticket": getattr(target, "ticket", None),
                    "symbol": getattr(target, "symbol", ""),
                    "volume": getattr(target, "volume", None),
                    "profit": getattr(target, "profit", None),
                    "sl": getattr(target, "sl", None),
                    "tp": getattr(target, "tp", None),
                }}
        except Exception as exc:
            self._gate(gates, "position_readable", False, str(exc))

        allowed = all(g["passed"] for g in gates)
        return {
            "allowed": allowed,
            "mode": "REAL_CONTROLLED_MODE",
            "gates": gates,
            "account": account,
            "orders_sent_this_run": self._real_orders_sent_this_run,
        }

    def _execute_real_controlled_market(self, req: ExecutionRequest) -> ExecutionResult:
        report = self.validate_real_controlled_request(req)
        self._audit("real_controlled_pre_order_gate_check", report["allowed"], "gate_report", result=report)
        if not report["allowed"]:
            if not bool(report.get("account", {}).get("demo_or_trial")):
                self._switch_to_demo_only_blocked(report.get("account", {}))
            failed = [g for g in report["gates"] if not g["passed"]]
            message = "real_controlled_gate_blocked:" + ",".join(g["gate"] for g in failed[:5])
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, message)
            return ExecutionResult(success=False, message=message, raw=report)

        try:
            import MetaTrader5 as mt5

            symbol_info = mt5.symbol_info(req.symbol)
            tick = mt5.symbol_info_tick(req.symbol)
            if symbol_info is None or tick is None:
                return ExecutionResult(success=False, message="symbol_info_or_tick_unavailable", raw=report)
            order_type = mt5.ORDER_TYPE_BUY if req.action == Direction.BUY else mt5.ORDER_TYPE_SELL
            price = float(tick.ask if req.action == Direction.BUY else tick.bid)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": req.symbol,
                "volume": float(req.lot),
                "type": order_type,
                "price": price,
                "sl": float(req.sl),
                "tp": float(req.tp),
                "deviation": int(req.deviation),
                "magic": int(req.magic),
                "comment": str(req.comment),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            self._audit("real_controlled_before_order_send", True, "about_to_send_one_market_order", result={"request": request, "gate_report": report})
            result = mt5.order_send(request)
            if result is None:
                self._audit("real_controlled_after_order_send", False, "order_send_none", result={"last_error": mt5.last_error()})
                return ExecutionResult(success=False, message="order_send_none", raw={"gate_report": report, "last_error": mt5.last_error()})
            raw = result._asdict() if hasattr(result, "_asdict") else result
            retcode = int(getattr(result, "retcode", 0) or 0)
            done_codes = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", mt5.TRADE_RETCODE_DONE)}
            success = retcode in done_codes
            if success:
                self._real_orders_sent_this_run += 1
            order = int(getattr(result, "order", 0) or 0)
            deal = int(getattr(result, "deal", 0) or 0)
            self._audit("real_controlled_after_order_send", success, f"retcode={retcode}", result={"raw": raw, "order": order, "deal": deal})
            log_execution(req.action.value, req.symbol, req.lot, req.magic, success, retcode, False, req.comment)
            return ExecutionResult(success=success, retcode=retcode, order=order, deal=deal, raw={"request": request, "result": raw, "gate_report": report})
        except Exception as exc:
            self._audit("real_controlled_order_send_exception", False, str(exc), result=report)
            log_error("execution_manager", str(exc), {"symbol": req.symbol, "action": req.action.value})
            return ExecutionResult(success=False, message=str(exc), raw=report)

    def validate_real_controlled_pending_request(self, req: ExecutionRequest | None, mt5_module=None) -> dict:
        report = self.validate_real_controlled_request(req, mt5_module)
        cfg = cfg_load()
        execution = cfg.get("execution", {}) if isinstance(cfg, dict) else {}
        risk = cfg.get("risk", {}) if isinstance(cfg, dict) else {}
        gates = list(report.get("gates", []))
        account = dict(report.get("account", {}))

        self._gate(
            gates,
            "pending_orders_enabled",
            execution.get("pending_orders_enabled") is True,
            f"pending_orders_enabled={execution.get('pending_orders_enabled')}",
        )
        self._gate(
            gates,
            "max_pending_orders_positive",
            int(risk.get("max_pending_orders", 0) or 0) > 0,
            f"max_pending_orders={risk.get('max_pending_orders')}",
        )
        max_pending = int(risk.get("max_pending_orders", 0) or 0)
        qader_pending = int(account.get("qader_pending_orders", account.get("pending_orders", 0)) or 0)
        self._gate(
            gates,
            "pending_capacity_available",
            qader_pending < max_pending,
            f"qader_pending_orders={qader_pending},max={max_pending}",
        )

        try:
            import MetaTrader5 as mt5

            if mt5_module is not None:
                mt5 = mt5_module
            if req is None:
                raise ValueError("no request")

            tick = mt5.symbol_info_tick(req.symbol)
            symbol_info = mt5.symbol_info(req.symbol)
            if tick is None or symbol_info is None:
                self._gate(gates, "pending_tick_readable", False, "tick_or_symbol_info_unavailable")
            else:
                self._gate(gates, "pending_tick_readable", True, "tick readable")
                point = float(getattr(symbol_info, "point", 0.0) or 0.00001)
                stops_level = float(getattr(symbol_info, "trade_stops_level", 0.0) or 0.0)
                min_distance = point * max(stops_level, 1.0)
                price = float(req.price or 0.0)
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                if req.action == Direction.BUY:
                    valid_side = price > 0 and price < ask and abs(ask - price) >= min_distance
                    side_reason = f"buy_limit_price={price},ask={ask},min_distance={min_distance}"
                elif req.action == Direction.SELL:
                    valid_side = price > 0 and price > bid and abs(price - bid) >= min_distance
                    side_reason = f"sell_limit_price={price},bid={bid},min_distance={min_distance}"
                else:
                    valid_side = False
                    side_reason = f"unsupported_action={getattr(req.action, 'value', req.action)}"
                self._gate(gates, "pending_limit_price_valid", valid_side, side_reason)
        except Exception as exc:
            self._gate(gates, "pending_limit_price_valid", False, str(exc))

        allowed = all(g["passed"] for g in gates)
        return {
            **report,
            "allowed": allowed,
            "gates": gates,
            "account": account,
        }

    def execute_pending_limit(self, req: ExecutionRequest) -> ExecutionResult:
        """Place one Qader-controlled BUY_LIMIT/SELL_LIMIT order on a demo/trial account."""
        if is_kill_switch():
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, "KILL_SWITCH")
            return ExecutionResult(success=False, message="kill_switch_active")

        ok, msg = req.is_valid()
        if not ok:
            log_error("execution_manager", f"Invalid pending request: {msg}", {"symbol": req.symbol})
            return ExecutionResult(success=False, message=f"invalid_request:{msg}")

        try:
            validate_request(req.magic, req.comment)
        except ValueError as exc:
            log_error("execution_manager", str(exc))
            return ExecutionResult(success=False, message=str(exc))

        if is_dry_run():
            log_execution(req.action.value, req.symbol, req.lot, req.magic, True, 0, True,
                          "DRY_RUN_SIMULATED_PENDING_NOT_SENT")
            return ExecutionResult(success=True, simulated=True, message="DRY_RUN_SIMULATED_PENDING_NOT_SENT")

        if not is_real_controlled_mode():
            return ExecutionResult(success=False, message="pending_limit_supported_only_in_real_controlled_mode")

        report = self.validate_real_controlled_pending_request(req)
        self._audit("real_controlled_pending_pre_order_gate_check", report["allowed"], "gate_report", result=report)
        if not report["allowed"]:
            if not bool(report.get("account", {}).get("demo_or_trial")):
                self._switch_to_demo_only_blocked(report.get("account", {}))
            failed = [g for g in report["gates"] if not g["passed"]]
            message = "real_controlled_pending_gate_blocked:" + ",".join(g["gate"] for g in failed[:5])
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, message)
            return ExecutionResult(success=False, message=message, raw=report)

        try:
            import MetaTrader5 as mt5

            order_type = mt5.ORDER_TYPE_BUY_LIMIT if req.action == Direction.BUY else mt5.ORDER_TYPE_SELL_LIMIT
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": req.symbol,
                "volume": float(req.lot),
                "type": order_type,
                "price": float(req.price),
                "sl": float(req.sl),
                "tp": float(req.tp),
                "deviation": int(req.deviation),
                "magic": int(req.magic),
                "comment": str(req.comment),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            self._audit("real_controlled_pending_before_order_send", True, "about_to_send_one_pending_limit", result={"request": request, "gate_report": report})
            result = mt5.order_send(request)
            if result is None:
                self._audit("real_controlled_pending_after_order_send", False, "order_send_none", result={"last_error": mt5.last_error()})
                return ExecutionResult(success=False, message="order_send_none", raw={"gate_report": report, "last_error": mt5.last_error()})
            raw = result._asdict() if hasattr(result, "_asdict") else result
            retcode = int(getattr(result, "retcode", 0) or 0)
            done_codes = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", mt5.TRADE_RETCODE_DONE)}
            success = retcode in done_codes
            if success:
                self._real_orders_sent_this_run += 1
            order = int(getattr(result, "order", 0) or 0)
            deal = int(getattr(result, "deal", 0) or 0)
            self._audit("real_controlled_pending_after_order_send", success, f"retcode={retcode}", result={"raw": raw, "order": order, "deal": deal})
            log_execution(req.action.value, req.symbol, req.lot, req.magic, success, retcode, False, req.comment)
            return ExecutionResult(success=success, retcode=retcode, order=order, deal=deal, raw={"request": request, "result": raw, "gate_report": report})
        except Exception as exc:
            self._audit("real_controlled_pending_order_send_exception", False, str(exc), result=report)
            log_error("execution_manager", str(exc), {"symbol": req.symbol, "action": req.action.value})
            return ExecutionResult(success=False, message=str(exc), raw=report)

    def _find_position(self, mt5, ticket: int):
        positions = list(mt5.positions_get() or [])
        return next((p for p in positions if int(getattr(p, "ticket", 0) or 0) == int(ticket)), None)

    def _execute_real_controlled_close_or_reduce(self, req: ExecutionRequest) -> ExecutionResult:
        report = self.validate_real_controlled_management_request(req)
        self._audit("real_controlled_management_pre_order_gate_check", report["allowed"], "gate_report", result=report)
        if not report["allowed"]:
            if not bool(report.get("account", {}).get("demo_or_trial")):
                self._switch_to_demo_only_blocked(report.get("account", {}))
            failed = [g for g in report["gates"] if not g["passed"]]
            message = "real_controlled_management_gate_blocked:" + ",".join(g["gate"] for g in failed[:5])
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, message)
            return ExecutionResult(success=False, message=message, raw=report)

        try:
            import MetaTrader5 as mt5

            pos = self._find_position(mt5, req.position_ticket)
            tick = mt5.symbol_info_tick(req.symbol)
            if pos is None or tick is None:
                return ExecutionResult(success=False, message="position_or_tick_unavailable", raw=report)
            pos_type = int(getattr(pos, "type", 0) or 0)
            close_type = mt5.ORDER_TYPE_SELL if pos_type == int(getattr(mt5, "POSITION_TYPE_BUY", 0)) else mt5.ORDER_TYPE_BUY
            price = float(tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask)
            current_volume = float(getattr(pos, "volume", 0.0) or 0.0)
            volume = current_volume if req.action == Direction.CLOSE or req.lot <= 0 else min(float(req.lot), current_volume)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": req.symbol,
                "volume": float(volume),
                "type": close_type,
                "position": int(req.position_ticket),
                "price": price,
                "deviation": int(req.deviation),
                "magic": int(req.magic),
                "comment": str(req.comment),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            self._audit("real_controlled_management_before_order_send", True, "about_to_send_close_or_reduce", result={"request": request, "gate_report": report})
            result = mt5.order_send(request)
            if result is None:
                self._audit("real_controlled_management_after_order_send", False, "order_send_none", result={"last_error": mt5.last_error()})
                return ExecutionResult(success=False, message="order_send_none", raw={"gate_report": report, "last_error": mt5.last_error()})
            raw = result._asdict() if hasattr(result, "_asdict") else result
            retcode = int(getattr(result, "retcode", 0) or 0)
            done_codes = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", mt5.TRADE_RETCODE_DONE)}
            success = retcode in done_codes
            order = int(getattr(result, "order", 0) or 0)
            deal = int(getattr(result, "deal", 0) or 0)
            self._audit("real_controlled_management_after_order_send", success, f"retcode={retcode}", result={"raw": raw, "order": order, "deal": deal})
            log_execution(req.action.value, req.symbol, volume, req.magic, success, retcode, False, req.comment)
            return ExecutionResult(success=success, retcode=retcode, order=order, deal=deal, raw={"request": request, "result": raw, "gate_report": report})
        except Exception as exc:
            self._audit("real_controlled_management_order_send_exception", False, str(exc), result=report)
            log_error("execution_manager", str(exc), {"symbol": req.symbol, "action": req.action.value})
            return ExecutionResult(success=False, message=str(exc), raw=report)

    def _execute_real_controlled_modify(self, req: ExecutionRequest) -> ExecutionResult:
        report = self.validate_real_controlled_management_request(req)
        self._audit("real_controlled_modify_pre_order_gate_check", report["allowed"], "gate_report", result=report)
        if not report["allowed"]:
            if not bool(report.get("account", {}).get("demo_or_trial")):
                self._switch_to_demo_only_blocked(report.get("account", {}))
            failed = [g for g in report["gates"] if not g["passed"]]
            message = "real_controlled_modify_gate_blocked:" + ",".join(g["gate"] for g in failed[:5])
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, message)
            return ExecutionResult(success=False, message=message, raw=report)

        try:
            import MetaTrader5 as mt5

            pos = self._find_position(mt5, req.position_ticket)
            if pos is None:
                return ExecutionResult(success=False, message="position_unavailable", raw=report)
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": int(req.position_ticket),
                "symbol": req.symbol,
                "sl": float(req.sl or getattr(pos, "sl", 0.0) or 0.0),
                "tp": float(req.tp or getattr(pos, "tp", 0.0) or 0.0),
                "magic": int(req.magic),
                "comment": str(req.comment),
            }
            self._audit("real_controlled_modify_before_order_send", True, "about_to_send_sltp_modify", result={"request": request, "gate_report": report})
            result = mt5.order_send(request)
            if result is None:
                self._audit("real_controlled_modify_after_order_send", False, "order_send_none", result={"last_error": mt5.last_error()})
                return ExecutionResult(success=False, message="order_send_none", raw={"gate_report": report, "last_error": mt5.last_error()})
            raw = result._asdict() if hasattr(result, "_asdict") else result
            retcode = int(getattr(result, "retcode", 0) or 0)
            done_codes = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", mt5.TRADE_RETCODE_DONE)}
            success = retcode in done_codes
            order = int(getattr(result, "order", 0) or 0)
            deal = int(getattr(result, "deal", 0) or 0)
            self._audit("real_controlled_modify_after_order_send", success, f"retcode={retcode}", result={"raw": raw, "order": order, "deal": deal})
            log_execution(req.action.value, req.symbol, req.lot, req.magic, success, retcode, False, req.comment)
            return ExecutionResult(success=success, retcode=retcode, order=order, deal=deal, raw={"request": request, "result": raw, "gate_report": report})
        except Exception as exc:
            self._audit("real_controlled_modify_order_send_exception", False, str(exc), result=report)
            log_error("execution_manager", str(exc), {"symbol": req.symbol, "action": req.action.value})
            return ExecutionResult(success=False, message=str(exc), raw=report)

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        # 1. Kill switch
        if is_kill_switch():
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, "KILL_SWITCH")
            return ExecutionResult(success=False, message="kill_switch_active")

        # 2. Validate request
        ok, msg = req.is_valid()
        if not ok:
            log_error("execution_manager", f"Invalid request: {msg}", {"symbol": req.symbol})
            return ExecutionResult(success=False, message=f"invalid_request:{msg}")

        # 3. Validate magic
        try:
            validate_request(req.magic, req.comment)
        except ValueError as e:
            log_error("execution_manager", str(e))
            return ExecutionResult(success=False, message=str(e))

        # 4. DRY_RUN — simulate only, never send to MT5
        if is_dry_run():
            log_execution(req.action.value, req.symbol, req.lot, req.magic, True, 0, True,
                          "DRY_RUN_SIMULATED_EXECUTION_NOT_SENT")
            log.info("[DRY_RUN_SIMULATED_EXECUTION_NOT_SENT] %s %s %.2f lot | SL=%.5f TP=%.5f | magic=%d",
                     req.action.value, req.symbol, req.lot, req.sl, req.tp, req.magic)
            return ExecutionResult(success=True, simulated=True, message="DRY_RUN_SIMULATED_EXECUTION_NOT_SENT")

        # 5. Qader REAL_CONTROLLED_MODE — only this branch may place one real market order.
        if is_real_controlled_mode():
            if req.action in (Direction.BUY, Direction.SELL):
                return self._execute_real_controlled_market(req)
            if req.action in (Direction.CLOSE, Direction.REDUCE):
                return self._execute_real_controlled_close_or_reduce(req)
            if req.action == Direction.TRAIL_ONLY:
                return self._execute_real_controlled_modify(req)
            return ExecutionResult(success=False, message=f"real_controlled_action_not_supported:{req.action.value}")

        # 5. Live check
        if not is_live_allowed():
            log_execution(req.action.value, req.symbol, req.lot, req.magic, False, 0, False, "live_not_allowed")
            return ExecutionResult(success=False, message="live_trading_not_allowed_in_config")

        # 6. Send via MT5Gateway
        try:
            gw = self._get_gateway()
            if req.action in (Direction.BUY, Direction.SELL):
                raw = gw.send_order(
                    symbol=req.symbol, action=req.action.value,
                    lot=req.lot, price=req.price,
                    sl=req.sl, tp=req.tp,
                    magic=req.magic, comment=req.comment,
                    deviation=req.deviation,
                )
            elif req.action == Direction.CLOSE:
                raw = gw.close_position(ticket=req.position_ticket, lot=req.lot,
                                        magic=req.magic, comment=req.comment)
            else:
                raw = gw.modify_position(ticket=req.position_ticket,
                                         sl=req.sl, tp=req.tp, magic=req.magic)

            success = raw.get("success", False) if isinstance(raw, dict) else False
            retcode = raw.get("retcode", 0) if isinstance(raw, dict) else 0
            order   = raw.get("order",   0) if isinstance(raw, dict) else 0
            log_execution(req.action.value, req.symbol, req.lot, req.magic,
                          success, retcode, False, req.comment)
            return ExecutionResult(success=success, retcode=retcode, order=order, raw=raw)
        except Exception as exc:
            log_error("execution_manager", str(exc), {"symbol": req.symbol, "action": req.action.value})
            return ExecutionResult(success=False, message=str(exc))


    def cancel_pending_order(self, ticket: int, magic: int, comment: str = "") -> ExecutionResult:
        """Cancel a pending MT5 order by ticket. Respects kill_switch and DRY_RUN."""
        if is_kill_switch():
            log_execution("CANCEL_PENDING", "", 0.0, magic, False, 0, False, "KILL_SWITCH")
            return ExecutionResult(success=False, message="kill_switch_active")

        if is_dry_run():
            log.info("[DRY_RUN] CANCEL_PENDING ticket=%d magic=%d", ticket, magic)
            log_execution("CANCEL_PENDING", "", 0.0, magic, True, 0, True, comment)
            return ExecutionResult(success=True, simulated=True, message="dry_run_simulated")

        return ExecutionResult(success=False, message="pending_order_cancel_disabled_in_qader_real_controlled_v1")

    def send_raw_order(self, req: dict, magic: int | None = None) -> ExecutionResult:
        """Send a pre-built MT5 order dict. Respects kill_switch and DRY_RUN.

        Use this only from algory_runner which already constructs the full request dict.
        All other callers should use execute() with an ExecutionRequest.
        """
        if is_kill_switch():
            return ExecutionResult(success=False, message="kill_switch_active")

        _magic = int(req.get("magic", magic or 0))
        try:
            validate_request(_magic, str(req.get("comment", "")))
        except ValueError as e:
            return ExecutionResult(success=False, message=str(e))

        if is_dry_run():
            log.info("[DRY_RUN] RAW_ORDER %s %s vol=%.2f magic=%d",
                     req.get("symbol", "?"), req.get("type", "?"),
                     float(req.get("volume", 0)), _magic)
            log_execution("RAW_ORDER", req.get("symbol", ""), float(req.get("volume", 0)),
                          _magic, True, 0, True, str(req.get("comment", "")))
            return ExecutionResult(success=True, simulated=True, message="dry_run_simulated")

        return ExecutionResult(success=False, message="raw_order_live_disabled_use_execution_request_pipeline")


# Singleton
_em: ExecutionManager | None = None

def get_execution_manager() -> ExecutionManager:
    global _em
    if _em is None:
        _em = ExecutionManager()
    return _em
