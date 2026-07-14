"""scalper_agent.py — Algory genome-based scalping signal producer.

Wraps algory_signal_engine.compute_signals. Requires an active Genome object.
"""
from __future__ import annotations
import logging
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("scalper_agent")


class ScalperAgent:
    source = "scalper_agent"

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str,
                genome=None, genome_win_rate: float = 0.5) -> SignalProposal | None:
        if genome is None:
            return None
        try:
            from ..algory_signal_engine import compute_signals
            result_df = compute_signals(df, genome)
            if result_df is None or len(result_df) == 0:
                return None

            last = result_df.iloc[-1]
            entry_dir = int(last.get("entry_dir", 0) or 0)
            filter_ok = bool(last.get("filter_ok", False))

            if not filter_ok or entry_dir == 0:
                return None

            direction  = Direction.BUY if entry_dir == 1 else Direction.SELL
            # Confidence = genome win_rate blended with signal strength
            signal_val = float(last.get("signal", 0) or 0)
            confidence = min(0.88, max(0.35, genome_win_rate * 0.7 + abs(signal_val) * 0.15))
            if confidence < 0.40:
                return None

            sl_px = float(last.get("sl", 0.0) or 0.0)
            tp_px = float(last.get("tp", 0.0) or 0.0)
            reason = f"scalper:{direction.value}|genome={getattr(genome, 'id', '?')}|wr={genome_win_rate:.2f}|sl={sl_px}|tp={tp_px}"
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id=f"FRIDAY_SCALPER_{getattr(genome, 'id', 'G0')}",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=float(abs(signal_val)),
                reason=reason,
                features={
                    "signal": float(signal_val),
                    "bias": float(last.get("bias", 0) or 0),
                    "filter_ok": float(filter_ok),
                    "sl_price": sl_px,
                    "tp_price": tp_px,
                    "genome_win_rate": genome_win_rate,
                },
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=3,
                tags=["scalper", "algory", "genome"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None
