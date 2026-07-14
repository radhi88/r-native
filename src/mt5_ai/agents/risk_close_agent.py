"""risk_close_agent.py — Emergency risk management contributor.

Scans open positions for unprotected losses (no SL and profit < threshold).
Returns PositionManagementRequest objects — never calls mt5.order_send.
"""
from __future__ import annotations
import logging
from ..core.signal_schema import PositionManagementRequest, PositionAction
from ..core.structured_logger import log_error

log = logging.getLogger("risk_close_agent")

DEFAULT_MAX_LOSS_USD = -50.0


class RiskCloseAgent:
    source = "risk_close_agent"

    def __init__(self, max_loss_usd: float = DEFAULT_MAX_LOSS_USD):
        self.max_loss_usd = max_loss_usd

    def evaluate_positions(self, positions: list) -> list[PositionManagementRequest]:
        requests: list[PositionManagementRequest] = []
        for pos in positions:
            try:
                sl     = float(getattr(pos, "sl", 0.0) or 0.0)
                profit = float(getattr(pos, "profit", 0.0) or 0.0)
                if sl == 0.0 and profit < self.max_loss_usd:
                    ticket = int(pos.ticket)
                    symbol = str(pos.symbol)
                    log.warning("risk_close: #%d %s profit=%.2f no SL — requesting close", ticket, symbol, profit)
                    requests.append(PositionManagementRequest(
                        position_ticket=ticket,
                        symbol=symbol,
                        action=PositionAction.FULL_CLOSE,
                        reason=f"emergency_risk_close:profit={profit:.2f}|sl=0",
                        source=self.source,
                    ))
            except Exception as exc:
                log_error(self.source, str(exc), {"ticket": getattr(pos, "ticket", 0)})
        return requests
