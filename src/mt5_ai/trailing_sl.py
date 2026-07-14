"""
trailing_sl.py — Automatic trailing stop-loss engine (dynamic multi-stage).

Rules (paper/demo only — never touches live positions):
  1. Breakeven  : profit ≥ 0.5×ATR  → SL = entry
  2. Normal     : profit ≥ 1.5×ATR  → trail 1.00×ATR behind peak
  3. Tight      : profit ≥ 3.0×ATR  → trail 0.50×ATR behind peak
  4. Ultra      : profit ≥ 5.0×ATR  → trail 0.25×ATR behind peak
  5. Lock       : profit ≥ 8.0×ATR  → trail 0.12×ATR behind peak

القاعدة: كلما زاد الربح ضاقت مسافة الـTrailing → تسريع تأمين الربح.
Hard lock: SL can only move in the direction of profit (never widen).
"""

import logging

log = logging.getLogger("friday.trailing_sl")

_BREAKEVEN_MULT = 0.5

# Dynamic trailing steps — sorted descending (first match wins)
# (min_profit_in_atr, trail_distance_in_atr, label)
_TRAIL_STEPS = [
    (8.0, 0.12, "lock"),    # ربح > 8×ATR  → trailing 0.12×ATR
    (5.0, 0.25, "ultra"),   # ربح > 5×ATR  → trailing 0.25×ATR
    (3.0, 0.50, "tight"),   # ربح > 3×ATR  → trailing 0.50×ATR
    (1.5, 1.00, "normal"),  # ربح > 1.5×ATR → trailing 1.00×ATR
]


def _find_trail(profit_atr: float) -> tuple[float, str]:
    """Returns (trail_distance_atr_mult, label) for the current profit ratio."""
    for min_profit, dist, label in _TRAIL_STEPS:
        if profit_atr >= min_profit:
            return dist, label
    return 0.0, "none"


class TrailingSLEngine:
    """
    Stateless per-bar engine.  Call update() with current price and ATR.
    Returns a list of (agent_name, new_sl) pairs for positions that need SL update.
    """

    def update(self, positions: dict, current_price: float, atr_points: float) -> list[tuple]:
        """
        positions   : coordinator._positions  {agent_name: {side, entry, sl, tp, ...}}
        current_price: latest market price in price units (same as SL/TP)
        atr_points  : ATR in price units (not pct)

        Returns [(agent_name, new_sl), ...] — caller is responsible for applying.
        """
        if atr_points <= 0:
            return []

        updates = []
        for name, pos in positions.items():
            entry = float(pos["entry"])
            sl    = pos.get("sl")
            side  = pos["side"]

            if sl is None:
                continue

            sl = float(sl)

            if side == "BUY":
                profit = current_price - entry
                peak   = pos.get("_peak", current_price)
                peak   = max(peak, current_price)
                pos["_peak"] = peak

                profit_atr = profit / atr_points
                trail_dist_mult, label = _find_trail(profit_atr)

                if trail_dist_mult > 0:
                    new_sl = max(peak - trail_dist_mult * atr_points, entry)
                    new_sl = max(new_sl, sl)   # never widen
                    if new_sl > sl + 0.001:
                        updates.append((name, round(new_sl, 5)))
                        log.info(
                            "TRAIL[%s] %s BUY  %.5f→%.5f  peak=%.5f  profit=%.1f×ATR",
                            label, name, sl, new_sl, peak, profit_atr,
                        )

                elif profit_atr >= _BREAKEVEN_MULT and sl < entry - 0.001:
                    updates.append((name, round(entry, 5)))
                    log.info("BREAKEVEN %s BUY  SL→%.5f", name, entry)

            elif side == "SELL":
                profit = entry - current_price
                peak   = pos.get("_peak", current_price)
                peak   = min(peak, current_price)
                pos["_peak"] = peak

                profit_atr = profit / atr_points
                trail_dist_mult, label = _find_trail(profit_atr)

                if trail_dist_mult > 0:
                    new_sl = min(peak + trail_dist_mult * atr_points, entry)
                    new_sl = min(new_sl, sl)   # never widen
                    if new_sl < sl - 0.001:
                        updates.append((name, round(new_sl, 5)))
                        log.info(
                            "TRAIL[%s] %s SELL %.5f→%.5f  peak=%.5f  profit=%.1f×ATR",
                            label, name, sl, new_sl, peak, profit_atr,
                        )

                elif profit_atr >= _BREAKEVEN_MULT and sl > entry + 0.001:
                    updates.append((name, round(entry, 5)))
                    log.info("BREAKEVEN %s SELL SL→%.5f", name, entry)

        return updates
