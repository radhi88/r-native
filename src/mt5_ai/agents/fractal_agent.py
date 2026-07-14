"""fractal_agent.py — SignalProducer: fractal structure + market projection."""
from __future__ import annotations
import logging
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("fractal_agent")

class FractalAgent:
    source = "fractal_agent"

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str,
                genome_win_rate: float = 0.5) -> SignalProposal | None:
        try:
            from ..fractal_structure_engine import analyse_structure
            from ..market_projection_engine import generate_projection
            fs   = analyse_structure(df)
            ema  = df["close"].ewm(span=21, adjust=False).mean()
            proj = generate_projection(df, fs, symbol=symbol, tf=timeframe,
                                       ema_series=ema, genome_win_rate=genome_win_rate)

            direction_str = proj.get("direction", "SIDEWAYS")
            confidence    = float(proj.get("confidence", 0.0))

            if direction_str == "UP":
                direction = Direction.BUY
            elif direction_str == "DOWN":
                direction = Direction.SELL
            else:
                direction = Direction.HOLD

            reason = proj.get("reason", "")
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id="FRIDAY_FRACTAL",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=float(proj.get("bull_score", 0) + proj.get("bear_score", 0)),
                reason=reason,
                features={
                    "structure_bias": 1.0 if fs.structure_bias == "bullish" else -1.0 if fs.structure_bias == "bearish" else 0.0,
                    "trend_quality": 1.0 if fs.trend_quality == "impulsive" else 0.5 if fs.trend_quality == "corrective" else 0.0,
                    "bos_recent": float(fs.bos_recent),
                    "choch_recent": float(fs.choch_recent),
                    "sweep_recent": float(fs.sweep_recent),
                    "stop_hunt_prob": fs.stop_hunt_probability,
                },
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=3,
                tags=["fractal", "smc", "projection"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None
