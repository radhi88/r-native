"""conflict_guard.py — Detects and blocks execution conflicts."""
from __future__ import annotations
import logging
from .signal_schema import SignalProposal, DecisionResult, Direction
from .structured_logger import log_conflict

log = logging.getLogger("conflict_guard")

class ConflictGuard:
    def check(self, decision: DecisionResult,
              signals: list[SignalProposal],
              open_positions: dict[str, str]) -> tuple[bool, list[str]]:
        """Returns (allow, list_of_conflicts)."""
        conflicts = []

        # 1. can_execute guard — block any agent that set can_execute=True
        for s in signals:
            if s.can_execute:
                conflicts.append(f"agent_{s.source}_has_can_execute_True")

        # 2. BUY + SELL conflict in same signals
        directions = {s.direction for s in signals if s.direction in (Direction.BUY, Direction.SELL)}
        if Direction.BUY in directions and Direction.SELL in directions:
            conflicts.append("buy_sell_conflict_in_signals")

        # 3. Opposite open position conflict
        sym = decision.symbol
        existing = open_positions.get(sym)
        if existing and decision.action.value != existing and decision.action in (Direction.BUY, Direction.SELL):
            conflicts.append(f"opposite_position_{existing}_vs_{decision.action.value}")

        # 4. Low confidence
        from .config_loader import get
        min_conf = get("confidence.min_decision_confidence") or 0.45
        if decision.confidence < min_conf:
            conflicts.append(f"confidence_too_low_{decision.confidence:.2f}")

        # 5. Single weak signal — don't trade on one signal alone below 0.5
        active = [s for s in signals if s.direction == decision.action and s.confidence > 0]
        demo_calibration = bool(get("demo_calibration.enabled")) and any(
            "DEMO_CALIBRATION_NOT_LIVE" in str(s.reason) for s in active
        )
        if len(active) == 1 and active[0].confidence < 0.50 and not demo_calibration:
            conflicts.append(f"single_weak_signal_{active[0].source}_{active[0].confidence:.2f}")

        allow = len(conflicts) == 0
        for c in conflicts:
            log_conflict(sym, c, decision.reason, blocked=True)
        return allow, conflicts
