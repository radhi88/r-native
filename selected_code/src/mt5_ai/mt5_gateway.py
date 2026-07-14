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
}

VALID_SIDES = {"BUY", "SELL"}
SUCCESS_RETCODES = {10008, 10009}  # TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE


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
    - Live trading is permanently blocked by send_market_order().
    - Only demo execution is allowed through send_demo_market_order().
    - Demo execution is additionally blocked unless the connected account server
      contains one of DEMO_SERVER_KEYWORDS.
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
        return results[: max(0, int(limit))]

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

    def send_demo_market_order(self, plan: OrderPlan) -> dict[str, Any]:
        """Send a market order only if connected account is detected as demo."""
        self._validate_plan(plan)

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

        result = self.mt5.order_send(request)
        if result is None and self._last_error_is_ipc():
            self.reconnect()
            result = self.mt5.order_send(request)

        result_data = result._asdict() if result is not None else None
        retcode = int(result_data.get("retcode") or 0) if result_data else 0
        sent = retcode in SUCCESS_RETCODES

        return {
            "sent": sent,
            "mode": "demo_mt5",
            "account": account_or_error,
            "request": request,
            "result": result_data,
            "retcode": retcode,
            "last_error": self.mt5.last_error(),
        }

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
