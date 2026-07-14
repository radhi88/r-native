"""Read-only MT5 connection service for Qader."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.storage.audit_log import log_action


@dataclass(slots=True)
class MT5Status:
    installed: bool
    connected: bool
    account_readable: bool
    message: str


class MT5Service:
    def __init__(self, guard: PermissionsGuard | None = None):
        self.guard = guard or PermissionsGuard()
        self.mt5 = None
        self.connected = False

    def _import_mt5(self):
        if self.mt5 is not None:
            return self.mt5
        try:
            import MetaTrader5 as mt5

            self.mt5 = mt5
            return mt5
        except Exception:
            return None

    def connect(self, terminal_path: str = "") -> MT5Status:
        perm = self.guard.check("can_read_mt5", "connect_mt5", "mt5_service")
        if not perm.allowed:
            return MT5Status(False, False, False, perm.reason)
        mt5 = self._import_mt5()
        if mt5 is None:
            return MT5Status(False, False, False, "MetaTrader5 Python package is not available.")
        try:
            ok = mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize()
            self.connected = bool(ok)
            info = mt5.account_info() if ok else None
            message = "connected" if ok else f"initialize_failed:{mt5.last_error()}"
            log_action("connect_mt5", "can_read_mt5", bool(ok), message, "mt5_service")
            return MT5Status(True, bool(ok), info is not None, message)
        except Exception as exc:
            log_action("connect_mt5_failed", "can_read_mt5", False, str(exc), "mt5_service")
            return MT5Status(True, False, False, str(exc))

    def shutdown(self) -> None:
        mt5 = self._import_mt5()
        if mt5 is not None and self.connected:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.connected = False

    def status(self) -> MT5Status:
        mt5 = self._import_mt5()
        if mt5 is None:
            return MT5Status(False, False, False, "MetaTrader5 Python package is not available.")
        try:
            info = mt5.account_info() if self.connected else None
            return MT5Status(True, self.connected, info is not None, "connected" if self.connected else "not_connected")
        except Exception as exc:
            return MT5Status(True, False, False, str(exc))

    def timeframe_value(self, timeframe: str) -> Any:
        mt5 = self._import_mt5()
        if mt5 is None:
            return None
        return {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }.get(timeframe)

    def fetch_bars(self, symbol: str, timeframe: str, n: int = 300):
        mt5 = self._import_mt5()
        if mt5 is None:
            return None
        if not self.connected:
            status = self.connect()
            if not status.connected:
                return None
        tf = self.timeframe_value(timeframe)
        if tf is None:
            return None
        try:
            import pandas as pd

            rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
            if rates is None:
                return None
            df = pd.DataFrame(rates)
            if df.empty:
                return None
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df = df.set_index("time").rename(columns={"tick_volume": "volume"})
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as exc:
            log_action("fetch_bars_failed", "can_read_mt5", False, str(exc), "mt5_service", metadata={"symbol": symbol, "timeframe": timeframe})
            return None

    def spread_points(self, symbol: str) -> float:
        mt5 = self._import_mt5()
        if mt5 is None or not self.connected:
            return float("inf")
        try:
            info = mt5.symbol_info(symbol)
            return float(getattr(info, "spread", float("inf")) if info else float("inf"))
        except Exception:
            return float("inf")

