"""council/types.py — shared dataclasses."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Proposal:
    """A trader's proposed entry. Council inspects + votes."""
    genome:        str              # "CLAUDE-XAU-G1"
    symbol:        str
    side:          str              # "BUY" / "SELL"
    order_kind:    str              # "MARKET" / "BUY_LIMIT" / "BUY_STOP" / "SELL_LIMIT" / "SELL_STOP"
    entry:         float
    sl:            float
    tp:            float
    lot:           float
    thesis:        str              # human-readable WHY (the trader's argument)
    confluence:    list = field(default_factory=list)   # signals supporting the trade


@dataclass
class Verdict:
    approve:    bool
    reason:     str
    confidence: int                  # 0-100


@dataclass
class CouncilResult:
    approved:        bool
    verdicts:        list            # [Verdict, ...]
    avg_confidence:  int
    proposal:        Proposal

    def dissent(self) -> list:
        """List of expert names that vetoed."""
        names = ("ARCHITECT", "QUANT", "RISK", "EXECUTOR", "REVIEWER")
        return [(n, v.reason) for n, v in zip(names, self.verdicts) if not v.approve]

    def summary(self) -> str:
        names = ("ARCHITECT", "QUANT", "RISK", "EXECUTOR", "REVIEWER")
        votes = [f"{n}={'✓' if v.approve else '✗'}({v.confidence})"
                 for n, v in zip(names, self.verdicts)]
        return f"[{'APPROVED' if self.approved else 'BLOCKED'}] " + " ".join(votes)
