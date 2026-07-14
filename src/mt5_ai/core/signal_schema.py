"""
signal_schema.py
----------------
Typed data contracts for the FRIDAY execution pipeline.

Flow:
  SignalProposal (agents) → DecisionResult (router) → RiskDecision (risk)
  → PositionManagementRequest (position) → ExecutionRequest → ExecutionResult (execution)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Enums ────────────────────────────────────────────────────────────────────

class Direction(str, Enum):
    BUY             = "BUY"
    SELL            = "SELL"
    HOLD            = "HOLD"
    NO_CONFIRMATION = "NO_CONFIRMATION"   # agent has bias but no active entry trigger
    CLOSE           = "CLOSE"
    REDUCE          = "REDUCE"
    TRAIL_ONLY      = "TRAIL_ONLY"


class PositionAction(str, Enum):
    TRAIL         = "TRAIL"
    BREAKEVEN     = "BREAKEVEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    FULL_CLOSE    = "FULL_CLOSE"
    REDUCE        = "REDUCE"
    HOLD          = "HOLD"


class RuntimeMode(str, Enum):
    DRY_RUN      = "DRY_RUN"
    DEMO         = "DEMO"
    LIVE         = "LIVE"
    REAL_CONTROLLED_MODE = "REAL_CONTROLLED_MODE"
    LIVE_DISABLED = "LIVE_DISABLED"


# ── Signal Proposal (produced by agents — NEVER executes) ─────────────────────

@dataclass
class SignalProposal:
    source:        str              # e.g. "fractal_agent", "smc_agent"
    strategy_id:   str
    symbol:        str
    timeframe:     str
    direction:     Direction
    confidence:    float            # 0.0 – 1.0
    strength:      float = 0.0     # normalized signal strength
    risk:          float = 0.0     # risk score 0–1 (higher = riskier)
    reason:        str  = ""
    features:      dict[str, float] = field(default_factory=dict)
    timestamp:     str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    can_execute:   bool = False     # ALWAYS False for agents — enforced by ConflictGuard
    desired_magic: int  = 0
    priority:      int  = 5        # 1=highest, 10=lowest
    tags:          list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.can_execute:
            raise ValueError(f"SignalProposal from {self.source} must have can_execute=False")
        self.confidence = max(0.0, min(1.0, self.confidence))


# ── Decision Result (produced by DecisionRouter) ──────────────────────────────

@dataclass
class DecisionResult:
    action:           Direction
    symbol:           str
    timeframe:        str
    confidence:       float
    approved_sources: list[str] = field(default_factory=list)
    blocked_sources:  list[str] = field(default_factory=list)
    conflicts:        list[str] = field(default_factory=list)
    reason:           str       = ""
    risk_notes:       list[str] = field(default_factory=list)
    timestamp:        str       = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_signals:      list[SignalProposal] = field(default_factory=list)


# ── Risk Decision (produced by RiskManager) ───────────────────────────────────

@dataclass
class RiskDecision:
    approved:      bool
    reason:        str
    max_lot:       float = 0.0
    adjusted_lot:  float = 0.0
    blocks:        list[str] = field(default_factory=list)
    warnings:      list[str] = field(default_factory=list)
    spread_ok:     bool = True
    margin_ok:     bool = True
    daily_loss_ok: bool = True
    position_limit_ok: bool = True


# ── Position Management Request (PositionManager → ExecutionManager) ──────────

@dataclass
class PositionManagementRequest:
    action:          PositionAction
    symbol:          str
    position_ticket: int
    reason:          str
    proposed_sl:     float = 0.0
    proposed_tp:     float = 0.0
    proposed_lot:    float = 0.0   # for partial close
    confidence:      float = 0.0
    source:          str   = ""


# ── Execution Request (only approved requests reach ExecutionManager) ─────────

@dataclass
class ExecutionRequest:
    action:             Direction
    symbol:             str
    lot:                float
    order_type:         int    = 0
    price:              float  = 0.0
    sl:                 float  = 0.0
    tp:                 float  = 0.0
    deviation:          int    = 20
    magic:              int    = 0
    comment:            str    = ""
    source_decision_id: str    = ""
    risk_decision:      RiskDecision | None = None
    position_ticket:    int    = 0   # for close/modify requests
    confidence:         float  = 0.0
    signal_arbiter_passed: bool = False
    conflict_guard_passed: bool = False

    def is_valid(self) -> tuple[bool, str]:
        if self.magic == 0:
            return False, "magic number required"
        if self.action in (Direction.BUY, Direction.SELL):
            if self.lot <= 0:
                return False, "lot must be positive"
            if self.sl <= 0:
                return False, "SL required for new entries"
        elif self.action == Direction.REDUCE:
            if self.lot <= 0:
                return False, "lot must be positive for reduce"
            if self.position_ticket <= 0:
                return False, "position ticket required"
        elif self.action in (Direction.CLOSE, Direction.TRAIL_ONLY):
            if self.lot < 0:
                return False, "lot must not be negative"
            if self.position_ticket <= 0:
                return False, "position ticket required"
        return True, "ok"


# ── Execution Result (returned by ExecutionManager) ───────────────────────────

@dataclass
class ExecutionResult:
    success:  bool
    retcode:  int   = 0
    order:    int   = 0
    deal:     int   = 0
    message:  str   = ""
    raw:      Any   = None
    simulated: bool = False  # True in DRY_RUN mode
