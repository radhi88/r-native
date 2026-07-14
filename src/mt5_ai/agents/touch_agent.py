"""touch_agent.py — Pivot level touch/bounce signal producer.

Wraps PivotEngine + build_pivot_signal_output from pivot_engine.py.
Emits signals when price touches a key pivot level with a valid bounce setup.
"""
from __future__ import annotations
import logging
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("touch_agent")


class TouchAgent:
    source = "touch_agent"

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from ..pivot_engine import PivotEngine
            self._engine = PivotEngine()
        return self._engine

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalProposal | None:
        try:
            from ..pivot_engine import build_pivot_signal_output
            engine = self._get_engine()
            engine.update(df)
            pivot_levels = engine.levels()

            if not pivot_levels:
                return None

            last_close = float(df["close"].iloc[-1])
            try:
                import MetaTrader5 as mt5
                info = mt5.symbol_info(symbol)
                point_size = float(info.point) if info else 0.00001
            except Exception:
                point_size = 0.00001

            # Use raw signal="NEUTRAL" — build_pivot_signal_output will upgrade it if near a level
            output = build_pivot_signal_output(
                signal="NEUTRAL",
                confidence=0.50,
                price=last_close,
                pivot_levels=pivot_levels,
                point_size=point_size,
            )

            updated_signal = output.get("signal", "NEUTRAL")
            confidence     = float(output.get("confidence", 0.0))

            if updated_signal not in ("BUY", "SELL") or confidence < 0.45:
                return None

            direction = Direction.BUY if updated_signal == "BUY" else Direction.SELL
            pivot_reason = output.get("pivot_reason", "")
            reason = f"touch:{updated_signal}|zone={output.get('zone','?')}|nearest={output.get('nearest_name','?')}@{output.get('nearest_price',0.0):.5f}|{pivot_reason}"
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id="FRIDAY_PIVOT_TOUCH",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=confidence,
                reason=reason,
                features={
                    "zone": 1.0 if output.get("zone") else 0.0,
                    "nearest_price": float(output.get("nearest_price", 0.0) or 0.0),
                    "pivot_confidence": confidence,
                },
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=2,
                tags=["pivot", "touch", "level"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None
