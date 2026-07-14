"""decision_router.py — Aggregates SignalProposals into one DecisionResult."""
from __future__ import annotations
import logging
from .signal_schema import SignalProposal, DecisionResult, Direction
from .structured_logger import log_decision

log = logging.getLogger("decision_router")

_SOURCE_WEIGHTS = {
    "signal_arbiter": 1.5,
    "fractal_agent": 1.2, "smc_agent": 1.1, "ai_agent": 1.0,
    "ict_sweep_agent": 1.0, "scalper_agent": 0.9, "touch_agent": 0.9,
    "orderflow_agent": 0.8, "pivot_agent": 0.7,
}

class DecisionRouter:
    def route(self, signals: list[SignalProposal], symbol: str, timeframe: str) -> DecisionResult:
        if not signals:
            return DecisionResult(action=Direction.HOLD, symbol=symbol, timeframe=timeframe,
                                  confidence=0.0, reason="no_signals")

        # Block any agent with can_execute=True
        for s in signals:
            if s.can_execute:
                log.warning("BLOCKED signal from %s — can_execute=True", s.source)
        signals = [s for s in signals if not s.can_execute]

        buy_score = sum(_SOURCE_WEIGHTS.get(s.source, 1.0) * s.confidence
                        for s in signals if s.direction == Direction.BUY)
        sell_score = sum(_SOURCE_WEIGHTS.get(s.source, 1.0) * s.confidence
                         for s in signals if s.direction == Direction.SELL)
        close_signals = [s for s in signals if s.direction == Direction.CLOSE]
        approved, blocked = [], []

        if close_signals:
            action = Direction.CLOSE
            confidence = max(s.confidence for s in close_signals)
            reason = "close_requested"
        elif buy_score == 0 and sell_score == 0:
            action = Direction.HOLD; confidence = 0.0; reason = "no_directional_signal"
        elif buy_score > sell_score * 1.2:
            action = Direction.BUY
            confidence = min(0.95, buy_score / (buy_score + sell_score + 1e-8))
            reason = f"buy_score={buy_score:.2f}_vs_sell={sell_score:.2f}"
            approved = [s.source for s in signals if s.direction == Direction.BUY]
            blocked  = [s.source for s in signals if s.direction == Direction.SELL]
        elif sell_score > buy_score * 1.2:
            action = Direction.SELL
            confidence = min(0.95, sell_score / (buy_score + sell_score + 1e-8))
            reason = f"sell_score={sell_score:.2f}_vs_buy={buy_score:.2f}"
            approved = [s.source for s in signals if s.direction == Direction.SELL]
            blocked  = [s.source for s in signals if s.direction == Direction.BUY]
        else:
            action = Direction.HOLD; confidence = 0.0; reason = "conflicting_signals"

        log_decision(action.value, symbol, timeframe, confidence, approved, blocked, reason)
        return DecisionResult(action=action, symbol=symbol, timeframe=timeframe,
                              confidence=confidence, approved_sources=approved,
                              blocked_sources=blocked, reason=reason, raw_signals=signals)
