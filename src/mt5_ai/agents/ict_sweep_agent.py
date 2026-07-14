"""ict_sweep_agent.py — ICT Liquidity Sweep + Reversal signal producer."""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("ict_sweep_agent")

SWING_BARS    = 7
SL_BUFFER_PTS = 3.0
TP_RATIO      = 2.0


def _find_swing_highs(highs: np.ndarray, lb: int) -> np.ndarray:
    n = len(highs)
    out = np.full(n, np.nan)
    for i in range(lb, n - lb):
        if highs[i] >= max(highs[i - lb:i]) and highs[i] >= max(highs[i + 1:i + lb + 1]):
            out[i] = highs[i]
    return out


def _find_swing_lows(lows: np.ndarray, lb: int) -> np.ndarray:
    n = len(lows)
    out = np.full(n, np.nan)
    for i in range(lb, n - lb):
        if lows[i] <= min(lows[i - lb:i]) and lows[i] <= min(lows[i + 1:i + lb + 1]):
            out[i] = lows[i]
    return out


def _check_signal(df: pd.DataFrame) -> tuple[str, float, float, float] | None:
    """Return (side, entry, sl, tp) or None. Uses last completed bar (index -2)."""
    if len(df) < SWING_BARS * 2 + 10:
        return None

    highs  = df["high"].values[:-1]
    lows   = df["low"].values[:-1]
    closes = df["close"].values

    sh = _find_swing_highs(highs, SWING_BARS)
    sl = _find_swing_lows(lows, SWING_BARS)
    idx = len(highs) - 1

    bar_h = highs[idx]
    bar_l = lows[idx]
    bar_c = closes[idx - 1]

    prior_sh = sh[:idx]
    prior_sl = sl[:idx]

    valid_sh = [h for h in prior_sh if not np.isnan(h)]
    if valid_sh:
        last_sh = valid_sh[-1]
        if bar_h > last_sh and bar_c < last_sh:
            entry = bar_c
            stop  = bar_h + SL_BUFFER_PTS
            risk  = stop - entry
            if risk > 0:
                candidates = [x for x in prior_sl if not np.isnan(x) and x < entry]
                sl_below = max(candidates) if candidates else None
                min_tp = entry - risk * TP_RATIO
                tp = sl_below if (sl_below and sl_below <= min_tp) else min_tp
                return "SELL", round(entry, 3), round(stop, 3), round(tp, 3)

    valid_sl = [x for x in prior_sl if not np.isnan(x)]
    if valid_sl:
        last_sl = valid_sl[-1]
        if bar_l < last_sl and bar_c > last_sl:
            entry = bar_c
            stop  = bar_l - SL_BUFFER_PTS
            risk  = entry - stop
            if risk > 0:
                candidates = [h for h in prior_sh if not np.isnan(h) and h > entry]
                sh_above = min(candidates) if candidates else None
                min_tp = entry + risk * TP_RATIO
                tp = sh_above if (sh_above and sh_above >= min_tp) else min_tp
                return "BUY", round(entry, 3), round(stop, 3), round(tp, 3)

    return None


class IctSweepAgent:
    source = "ict_sweep_agent"

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str = "M1") -> SignalProposal | None:
        try:
            result = _check_signal(df)
            if result is None:
                return None

            side, entry, sl_price, tp_price = result
            direction = Direction.BUY if side == "BUY" else Direction.SELL
            risk = abs(entry - sl_price)
            rr   = abs(tp_price - entry) / risk if risk > 0 else 0.0
            confidence = min(0.85, 0.55 + (rr - TP_RATIO) * 0.05)

            reason = f"ict_sweep:{side}|entry={entry}|sl={sl_price}|tp={tp_price}|rr={rr:.1f}"
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id="FRIDAY_ICT_SWEEP",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=rr,
                reason=reason,
                features={
                    "sweep_sl": sl_price,
                    "sweep_tp": tp_price,
                    "sweep_entry": entry,
                    "rr_ratio": rr,
                },
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=4,
                tags=["ict", "sweep", "liquidity"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None
