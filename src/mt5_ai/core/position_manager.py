"""position_manager.py — Position management requests → ExecutionManager only."""
from __future__ import annotations
import logging
from .signal_schema import PositionManagementRequest, PositionAction, ExecutionRequest, Direction
from .magic_registry import QADER_REAL_CONTROLLED_MAGIC
from .structured_logger import log_position

log = logging.getLogger("position_manager")

class PositionManager:
    def handle(self, req: PositionManagementRequest) -> ExecutionRequest | None:
        log_position(req.position_ticket, req.action.value, req.symbol, req.reason, req.source)

        if req.action == PositionAction.FULL_CLOSE:
            return ExecutionRequest(
                action=Direction.CLOSE, symbol=req.symbol,
                lot=0.0, position_ticket=req.position_ticket,
                magic=QADER_REAL_CONTROLLED_MAGIC, comment="QADER_DEMO|PM_CLOSE",
                source_decision_id=req.source,
            )
        if req.action == PositionAction.PARTIAL_CLOSE:
            return ExecutionRequest(
                action=Direction.REDUCE, symbol=req.symbol,
                lot=req.proposed_lot, position_ticket=req.position_ticket,
                magic=QADER_REAL_CONTROLLED_MAGIC, comment="QADER_DEMO|PM_PARTIAL",
                source_decision_id=req.source,
            )
        if req.action in (PositionAction.TRAIL, PositionAction.BREAKEVEN):
            return ExecutionRequest(
                action=Direction.TRAIL_ONLY, symbol=req.symbol,
                lot=0.0, position_ticket=req.position_ticket,
                sl=req.proposed_sl, tp=req.proposed_tp,
                magic=QADER_REAL_CONTROLLED_MAGIC, comment=f"QADER_DEMO|PM_{req.action.value[:5]}",
                source_decision_id=req.source,
            )
        return None  # HOLD — no action needed
