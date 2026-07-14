from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
import time

import pandas as pd

from .config import (
    DEFAULT_DEVIATION,
    DEFAULT_MAGIC,
    DEFAULT_LOT,
    DEMO_SERVER_KEYWORDS,
    DEMO_TRADING_ENABLED,
    MAX_LOT,
    MT5_TERMINAL_PATH,
)


TIMEFRAME_MAP: dict[str, str] = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

VALID_SIDES = {"BUY", "SELL"}
SUCCESS_RETCODES = {10008, 10009}  # TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE
NO_CHANGE_RETCODE = 10025          # TRADE_RETCODE_NO_CHANGES


@dataclass(slots=True)
class OrderPlan:
    symbol: str
    side: Literal["BUY", "SELL"] | str
    lot: float = DEFAULT_LOT
    sl: float | None = None
    tp: float | None = None
    comment: str = "mt5-ai-jarvis"

    def normalized_side(self) -> str:
        return str(self.side).strip().upper()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MT5Gateway:
    """
    Gateway wrapper around the MetaTrader5 Python package.

    Safety policy:
    - Live trading is blocked by send_market_order().
    - Demo and legacy write helpers return blocked in the active runtime.
    - Qader real execution is owned by ExecutionManager only.
    """

    def __init__(self) -> None:
        import MetaTrader5 as mt5

        self.mt5 = mt5
        self.connected = False

    # ---------------------------------------------------------------------
    # Connection lifecycle
    # ---------------------------------------------------------------------
    def initialize(self) -> None:
        """Initialize MT5 terminal connection."""
        try:
            ok = self.mt5.initialize(path=MT5_TERMINAL_PATH)
        except TypeError:
            ok = self.mt5.initialize()

        if not ok:
            raise RuntimeError(f"MT5 init failed: {self.mt5.last_error()}")

        self.connected = True

    def reconnect(self, delay: float = 1.0) -> None:
        """Restart MT5 connection, useful after IPC errors."""
        try:
            self.mt5.shutdown()
        except Exception:
            pass

        self.connected = False
        time.sleep(float(delay))
        self.initialize()

    def shutdown(self) -> None:
        """Shutdown MT5 connection."""
        if self.connected:
            self.mt5.shutdown()
        self.connected = False

    def _last_error_is_ipc(self) -> bool:
        try:
            code, message = self.mt5.last_error()
        except Exception:
            return False

        message_text = str(message).lower()
        return int(code) == -10004 or "ipc" in message_text or "connection" in message_text

    def _retry_if_ipc(self, action, *args, **kwargs):
        """Run an MT5 action and retry once if the last error looks like IPC failure."""
        result = action(*args, **kwargs)
        if result is None and self._last_error_is_ipc():
            self.reconnect()
            result = action(*args, **kwargs)
        return result

    # ---------------------------------------------------------------------
    # Symbol and market data
    # ---------------------------------------------------------------------
    def ensure_symbol(self, symbol: str) -> None:
        symbol = self._clean_symbol(symbol)

        if self.mt5.symbol_select(symbol, True):
            return

        if self._last_error_is_ipc():
            self.reconnect()
            if self.mt5.symbol_select(symbol, True):
                return

        raise RuntimeError(f"Failed to select {symbol}: {self.mt5.last_error()}")

    def fetch_rates(self, symbol: str, timeframe_name: str = "M1", bars: int = 400) -> pd.DataFrame:
        symbol = self._clean_symbol(symbol)
        timeframe_name = str(timeframe_name).strip().upper()
        bars = int(bars)

        if timeframe_name not in TIMEFRAME_MAP:
            allowed = ", ".join(sorted(TIMEFRAME_MAP))
            raise ValueError(f"Unsupported timeframe: {timeframe_name}. Allowed: {allowed}")

        if bars <= 0:
            raise ValueError("bars must be greater than zero")

        self.ensure_symbol(symbol)
        timeframe = getattr(self.mt5, TIMEFRAME_MAP[timeframe_name])

        rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
        if (rates is None or len(rates) == 0) and self._last_error_is_ipc():
            self.reconnect()
            self.ensure_symbol(symbol)
            rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)

        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No rates returned for {symbol}: {self.mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.sort_values("time").reset_index(drop=True)

    def symbols(self, visible_only: bool = True, tradable_only: bool = True, limit: int = 60) -> list[dict[str, Any]]:
        symbols = self.mt5.symbols_get()
        if symbols is None and self._last_error_is_ipc():
            self.reconnect()
            symbols = self.mt5.symbols_get()

        if symbols is None:
            raise RuntimeError(f"MT5 symbols_get failed: {self.mt5.last_error()}")

        results: list[dict[str, Any]] = []
        for symbol_info in symbols:
            data = symbol_info._asdict()
            name = data.get("name")

            if not name:
                continue
            if visible_only and not data.get("visible"):
                continue
            if tradable_only and int(data.get("trade_mode") or 0) <= 0:
                continue

            results.append(
                {
                    "symbol": name,
                    "path": data.get("path"),
                    "description": data.get("description"),
                    "spread": data.get("spread"),
                    "digits": data.get("digits"),
                    "trade_mode": data.get("trade_mode"),
                }
            )

        results.sort(key=lambda item: (str(item.get("path") or ""), item["symbol"]))
        limit = int(limit or 0)
        return results if limit <= 0 else results[:limit]

    def get_open_positions(self, magic: int = DEFAULT_MAGIC) -> list[dict[str, Any]]:
        """جلب الصفقات المفتوحة الحقيقية من MT5 (مُفلترة بـmagic number)."""
        positions = self._retry_if_ipc(self.mt5.positions_get)
        if not positions:
            return []
        result = []
        for p in positions:
            d = p._asdict()
            if magic is not None and int(d.get("magic", 0)) != int(magic):
                continue
            result.append({
                "ticket": int(d["ticket"]),
                "symbol": str(d["symbol"]),
                "side":   "BUY" if int(d["type"]) == 0 else "SELL",
                "entry":  float(d["price_open"]),
                "sl":     float(d["sl"]),
                "tp":     float(d["tp"]),
                "volume": float(d["volume"]),
                "profit": float(d["profit"]),
            })
        return result

    def symbol_snapshot(self, symbol: str) -> dict[str, Any]:
        symbol = self._clean_symbol(symbol)
        self.ensure_symbol(symbol)

        info = self.mt5.symbol_info(symbol)
        tick = self.mt5.symbol_info_tick(symbol)

        if (info is None or tick is None) and self._last_error_is_ipc():
            self.reconnect()
            self.ensure_symbol(symbol)
            info = self.mt5.symbol_info(symbol)
            tick = self.mt5.symbol_info_tick(symbol)

        if info is None or tick is None:
            return {"symbol": symbol, "error": str(self.mt5.last_error())}

        return {
            "symbol": symbol,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "spread": float(info.spread),
            "digits": int(info.digits),
            "point": float(info.point),
            "trade_mode": int(info.trade_mode),
        }

    # ---------------------------------------------------------------------
    # Account safety
    # ---------------------------------------------------------------------
    def account_snapshot(self) -> dict[str, Any]:
        account = self.mt5.account_info()
        if account is None and self._last_error_is_ipc():
            self.reconnect()
            account = self.mt5.account_info()

        if account is None:
            return {
                "connected": False,
                "error": str(self.mt5.last_error()),
            }

        data = account._asdict()
        keys = ["login", "server", "balance", "equity", "margin", "margin_free", "currency"]
        snapshot = {key: data.get(key) for key in keys}
        snapshot["connected"] = True
        snapshot["demo_detected"] = self.is_demo_account(snapshot)
        return snapshot

    def is_demo_account(self, snapshot: dict[str, Any] | None = None) -> bool:
        snapshot = snapshot or self.account_snapshot()
        server = str(snapshot.get("server") or "").lower()
        return any(str(keyword).lower() in server for keyword in DEMO_SERVER_KEYWORDS)

    def ensure_demo_account(self) -> tuple[bool, dict[str, Any]]:
        snapshot = self.account_snapshot()

        if not snapshot.get("connected"):
            return False, {
                "sent": False,
                "mode": "blocked",
                "reason": "mt5_account_not_connected",
                "account": snapshot,
            }

        if not self.is_demo_account(snapshot):
            return False, {
                "sent": False,
                "mode": "blocked",
                "reason": "blocked_not_demo_account",
                "account": snapshot,
            }

        return True, snapshot

    # ---------------------------------------------------------------------
    # Trading
    # ---------------------------------------------------------------------
    @staticmethod
    def _blocked_result(operation: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "success": False,
            "sent": False,
            "mode": "blocked",
            "operation": operation,
            "reason": reason,
            **extra,
        }

    def _runtime_write_block(self, operation: str) -> dict[str, Any] | None:
        try:
            from .core.config_loader import is_dry_run, is_kill_switch
        except Exception as exc:
            return self._blocked_result(
                operation,
                "runtime_safety_check_unavailable",
                error=str(exc),
            )

        if is_kill_switch():
            return self._blocked_result(operation, "kill_switch_active")
        if is_dry_run():
            return self._blocked_result(operation, "dry_run_blocks_gateway_write")
        return None

    def send_market_order(self, plan: OrderPlan, allow_live: bool = True) -> dict[str, Any]:
        """
        Live trading endpoint.

        This is intentionally blocked. It returns sent=False because no order is
        submitted to MT5. Keep this function blocked unless you implement a
        separate audited approval flow.
        """
        return {
            "sent": False,
            "mode": "blocked",
            "reason": "live_trading_permanently_disabled",
            "allow_live_requested": bool(allow_live),
            "plan": plan.to_dict(),
        }

    def send_order(
        self,
        symbol: str,
        action: str,
        lot: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        magic: int = DEFAULT_MAGIC,
        comment: str = "",
        deviation: int = DEFAULT_DEVIATION,
    ) -> dict[str, Any]:
        """Blocked live-order adapter for ExecutionManager.

        This method exists so the live path fails closed with a structured
        response instead of an AttributeError. It must not send orders until an
        audited execution flow is explicitly implemented.
        """
        return self._blocked_result(
            "send_order",
            "live_order_adapter_blocked",
            symbol=symbol,
            action=action,
            lot=float(lot),
            price=float(price),
            sl=float(sl),
            tp=float(tp),
            magic=int(magic),
            comment=comment,
            deviation=int(deviation),
        )

    def close_position(
        self,
        ticket: int,
        lot: float = 0.0,
        magic: int = DEFAULT_MAGIC,
        comment: str = "",
    ) -> dict[str, Any]:
        """Blocked close adapter for ExecutionManager."""
        return self._blocked_result(
            "close_position",
            "close_adapter_blocked",
            ticket=int(ticket),
            lot=float(lot),
            magic=int(magic),
            comment=comment,
        )

    def modify_position(
        self,
        ticket: int,
        sl: float = 0.0,
        tp: float = 0.0,
        magic: int = DEFAULT_MAGIC,
    ) -> dict[str, Any]:
        """Blocked modify adapter for ExecutionManager."""
        return self._blocked_result(
            "modify_position",
            "modify_adapter_blocked",
            ticket=int(ticket),
            sl=float(sl),
            tp=float(tp),
            magic=int(magic),
        )

    def send_demo_pending_order(self, plan: OrderPlan, limit_price: float) -> dict[str, Any]:
        """Blocked legacy helper for pending demo orders."""
        self._validate_plan(plan)

        block = self._runtime_write_block("send_demo_pending_order")
        if block:
            return {**block, "plan": plan.to_dict(), "limit_price": float(limit_price)}

        if not DEMO_TRADING_ENABLED:
            return {
                "sent": False,
                "mode": "blocked",
                "reason": "demo_trading_disabled",
                "plan": plan.to_dict(),
            }

        ok, account_or_error = self.ensure_demo_account()
        if not ok:
            return {**account_or_error, "plan": plan.to_dict()}

        self.ensure_symbol(plan.symbol)
        symbol_info = self.symbol_snapshot(plan.symbol)
        if "error" in symbol_info:
            return {"sent": False, "mode": "blocked", "reason": "symbol_snapshot_failed",
                    "symbol_info": symbol_info, "plan": plan.to_dict()}

        return self._blocked_result(
            "send_demo_pending_order",
            "gateway_direct_write_disabled_use_execution_manager",
            account=account_or_error,
            symbol_info=symbol_info,
            plan=plan.to_dict(),
            limit_price=float(limit_price),
        )

    def send_demo_market_order(self, plan: OrderPlan) -> dict[str, Any]:
        """Blocked legacy helper for demo market orders."""
        self._validate_plan(plan)

        block = self._runtime_write_block("send_demo_market_order")
        if block:
            return {**block, "plan": plan.to_dict()}

        if not DEMO_TRADING_ENABLED:
            return {
                "sent": False,
                "mode": "blocked",
                "reason": "demo_trading_disabled",
                "plan": plan.to_dict(),
            }

        ok, account_or_error = self.ensure_demo_account()
        if not ok:
            return {**account_or_error, "plan": plan.to_dict()}

        self.ensure_symbol(plan.symbol)
        symbol_info = self.symbol_snapshot(plan.symbol)

        if "error" in symbol_info:
            return {
                "sent": False,
                "mode": "blocked",
                "reason": "symbol_snapshot_failed",
                "symbol_info": symbol_info,
                "plan": plan.to_dict(),
            }

        lot = self._normalize_lot(plan.lot)
        side = plan.normalized_side()

        if side == "BUY":
            order_type = self.mt5.ORDER_TYPE_BUY
            price = symbol_info["ask"]
        elif side == "SELL":
            order_type = self.mt5.ORDER_TYPE_SELL
            price = symbol_info["bid"]
        else:
            raise ValueError(f"Unknown order side: {plan.side}")

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": plan.symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "deviation": DEFAULT_DEVIATION,
            "magic": DEFAULT_MAGIC,
            "comment": plan.comment,
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

        if plan.sl is not None:
            request["sl"] = float(plan.sl)
        if plan.tp is not None:
            request["tp"] = float(plan.tp)

        return self._blocked_result(
            "send_demo_market_order",
            "gateway_direct_write_disabled_use_execution_manager",
            account=account_or_error,
            request=request,
            plan=plan.to_dict(),
        )

    def _min_stop_dist(self, symbol: str) -> float:
        """Minimum SL/TP distance from current price in price units (stops_level × point + buffer)."""
        try:
            info = self.mt5.symbol_info(symbol)
            if info is None:
                return 0.0
            return max(int(getattr(info, "trade_stops_level", 0)) + 3, 5) * float(info.point)
        except Exception:
            return 0.0

    def modify_demo_position_sl_tp(
        self,
        ticket: int,
        symbol: str,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        """Blocked legacy helper for demo SL/TP modification."""
        block = self._runtime_write_block("modify_demo_position_sl_tp")
        if block:
            return {**block, "ticket": int(ticket), "symbol": symbol}

        if not DEMO_TRADING_ENABLED:
            return {
                "sent": False,
                "mode": "blocked",
                "reason": "demo_trading_disabled",
                "ticket": int(ticket),
            }

        ok, account_or_error = self.ensure_demo_account()
        if not ok:
            return {**account_or_error, "ticket": int(ticket)}

        symbol = self._clean_symbol(symbol)
        self.ensure_symbol(symbol)

        # ── validate SL/TP against broker minimum stop distance ─────────────
        try:
            tick_info  = self.mt5.symbol_info_tick(symbol)
            sym_info   = self.mt5.symbol_info(symbol)
            pos_list   = self.mt5.positions_get(ticket=int(ticket))

            if tick_info and sym_info and pos_list:
                digits    = int(sym_info.digits)
                min_dist  = self._min_stop_dist(symbol)
                bid       = float(tick_info.bid)
                ask       = float(tick_info.ask)
                pos_type  = int(pos_list[0].type)   # 0=BUY, 1=SELL
                mt5_tp    = float(pos_list[0].tp)   # actual TP in MT5

                if sl is not None:
                    sl = float(sl)
                    if pos_type == 0:   # BUY — SL must be below bid
                        sl = min(sl, round(bid - min_dist, digits))
                    else:               # SELL — SL must be above ask
                        sl = max(sl, round(ask + min_dist, digits))

                # Use MT5's actual TP (avoids stale cache invalidating the request)
                if tp is not None:
                    tp_chk = float(tp)
                    if pos_type == 0 and tp_chk < ask + min_dist:
                        tp = mt5_tp if mt5_tp > 0 else tp_chk
                    elif pos_type == 1 and tp_chk > bid - min_dist:
                        tp = mt5_tp if mt5_tp > 0 else tp_chk
        except Exception:
            pass   # non-fatal — proceed with original values
        # ────────────────────────────────────────────────────────────────────

        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": symbol,
            "magic": DEFAULT_MAGIC,
        }
        if sl is not None and float(sl) > 0:
            request["sl"] = float(sl)
        if tp is not None and float(tp) > 0:
            request["tp"] = float(tp)

        return self._blocked_result(
            "modify_demo_position_sl_tp",
            "gateway_direct_write_disabled_use_execution_manager",
            account=account_or_error,
            request=request,
            ticket=int(ticket),
        )

    # ---------------------------------------------------------------------
    # Validation helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        symbol = str(symbol or "").strip()
        if not symbol:
            raise ValueError("symbol is required")
        return symbol

    @staticmethod
    def _normalize_lot(lot: float) -> float:
        lot = float(lot)
        if lot <= 0:
            raise ValueError("lot must be greater than zero")
        return min(max(lot, 0.01), float(MAX_LOT))

    def _validate_plan(self, plan: OrderPlan) -> None:
        if not isinstance(plan, OrderPlan):
            raise TypeError("plan must be an OrderPlan instance")

        self._clean_symbol(plan.symbol)

        side = plan.normalized_side()
        if side not in VALID_SIDES:
            raise ValueError(f"side must be one of {sorted(VALID_SIDES)}, got: {plan.side}")

        self._normalize_lot(plan.lot)

        if plan.sl is not None:
            float(plan.sl)
        if plan.tp is not None:
            float(plan.tp)
