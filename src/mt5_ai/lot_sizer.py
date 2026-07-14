"""
lot_sizer.py — Dynamic lot sizing based on strategy confidence.

Tiers (paper/demo only):
  Tier 0 (default)   → 0.01  lot   — < 50 trades or stats not significant
  Tier 1 (growing)   → 0.02  lot   — 50+ trades, WR CI > 0.52, PF > 1.4
  Tier 2 (proven)    → 0.03  lot   — 100+ trades, WR CI > 0.55, PF > 1.6
  Tier 3 (elite)     → 0.05  lot   — 200+ trades, WR CI > 0.58, PF > 2.0

Safety caps:
  - Never exceed MAX_LOT (config)
  - Never exceed 2% of tracked paper balance per trade
  - If current_losing_streak ≥ 5 → drop back to Tier 0 until streak resets
"""

import math
import logging
from dataclasses import dataclass

from .config import DEFAULT_LOT, MAX_LOT

log = logging.getLogger("friday.lot_sizer")

_TIERS = [
    # (min_trades, wilson_lb, min_pf, lot)
    (200, 0.58, 2.00, 0.05),
    (100, 0.55, 1.60, 0.03),
    (50,  0.52, 1.40, 0.02),
    (0,   0.0,  0.0,  DEFAULT_LOT),   # fallback
]

_STREAK_RESET = 5   # drop to Tier 0 after this many consecutive losses


@dataclass
class SizingResult:
    lot: float
    tier: int
    reason: str


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return centre - margin


def compute_lot(
    journal_rows: list[dict],
    paper_balance: float | None = None,
) -> SizingResult:
    """
    journal_rows: list of row dicts from LearningEngine._load_rows(agent=name)
    paper_balance: simulated equity (optional — used for 2% cap)
    """
    n = len(journal_rows)
    if n == 0:
        return SizingResult(lot=DEFAULT_LOT, tier=0, reason="no trades yet")

    wins = sum(1 for r in journal_rows if r.get("won") in ("True", True, 1))
    pts  = [float(r["points"]) for r in journal_rows]

    gross_win  = sum(p for p in pts if p > 0) or 0.0
    gross_loss = abs(sum(p for p in pts if p < 0)) or 1e-9
    pf         = gross_win / gross_loss

    wilson_lb = _wilson_lower(wins, n)

    # Losing-streak guard
    streak = 0
    for r in reversed(journal_rows):
        won = r.get("won") in ("True", True, 1)
        if not won:
            streak += 1
        else:
            break

    if streak >= _STREAK_RESET:
        return SizingResult(
            lot=DEFAULT_LOT, tier=0,
            reason=f"losing streak {streak} — reset to base lot"
        )

    # Find tier
    chosen_lot = DEFAULT_LOT
    tier = 0
    for i, (min_t, min_wlb, min_pf, lot) in enumerate(_TIERS):
        if n >= min_t and wilson_lb >= min_wlb and pf >= min_pf:
            chosen_lot = lot
            tier = len(_TIERS) - 1 - i
            break

    # 2% of paper balance cap
    if paper_balance and paper_balance > 0:
        max_by_balance = round(paper_balance * 0.02 / 100, 2)  # 2% risk, ~100 pts SL assumed
        chosen_lot = min(chosen_lot, max(max_by_balance, DEFAULT_LOT))

    chosen_lot = min(chosen_lot, MAX_LOT)

    reason = (
        f"tier={tier} trades={n} wilson_lb={wilson_lb:.3f} "
        f"pf={pf:.2f} streak={streak}"
    )
    log.debug("lot_sizer: %s → %.2f", reason, chosen_lot)
    return SizingResult(lot=chosen_lot, tier=tier, reason=reason)
