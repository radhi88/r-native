"""ai_agent.py — Neural network signal producer.

Wraps TradingBrain.decide from ai_brain.py. Requires a trained Keras model.
Falls back gracefully if model is unavailable.
"""
from __future__ import annotations
import logging
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("ai_agent")


class AiAgent:
    source = "ai_agent"

    def __init__(self, model=None, profile_name: str = "ict"):
        self._model = model
        self._profile_name = profile_name

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str,
                sequence: list | None = None, probability: float | None = None,
                spread: float = 0.0) -> SignalProposal | None:
        try:
            from ..ai_brain import TradingBrain
            brain = TradingBrain(model=self._model, profile_name=self._profile_name)
            td = brain.decide(df, sequence=sequence, probability=probability,
                              spread=spread, ignore_spread=True)

            if td is None or td.action not in ("BUY", "SELL"):
                return None

            direction  = Direction.BUY if td.action == "BUY" else Direction.SELL
            confidence = float(td.confidence or td.probability or 0.0)
            if confidence < 0.40:
                return None

            reason = td.reason or f"ai:{td.action}|prob={td.probability:.3f}|ctx={td.context_score}"
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id=f"FRIDAY_AI_{self._profile_name.upper()}",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=float(td.context_score or 0),
                reason=reason,
                features={
                    "probability": float(td.probability or 0.0),
                    "smc_buy_score": float(td.smc_buy_score or 0.0),
                    "smc_sell_score": float(td.smc_sell_score or 0.0),
                    "smc_bias": float(td.smc_bias or 0.0),
                    "context_score": float(td.context_score or 0),
                    "risk_allowed": float(td.risk_allowed),
                },
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=5,
                tags=["ai", "neural", "keras"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None
