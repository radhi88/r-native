"""council/__init__.py — the 5-expert decision council.

Each expert returns a Verdict(approve: bool, reason: str, confidence: int).
The Trader proposes; the council votes; ALL 5 must approve for trade to fire.
Any single veto blocks the trade. Every decision logged.
"""
from .types import Proposal, Verdict, CouncilResult
from .architect import architect_review
from .quant import quant_review
from .risk import risk_review
from .executor import executor_review
from .reviewer import reviewer_review


def convene(proposal: Proposal, snapshot, account) -> CouncilResult:
    """Run all 5 expert reviews on a trade proposal."""
    verdicts = []
    for expert_fn in (architect_review, quant_review, risk_review,
                       executor_review, reviewer_review):
        try:
            v = expert_fn(proposal, snapshot, account)
        except Exception as e:
            v = Verdict(False, f"{expert_fn.__name__} crashed: {e}", 0)
        verdicts.append(v)
    approved = all(v.approve for v in verdicts)
    avg_conf = sum(v.confidence for v in verdicts) // 5
    return CouncilResult(approved=approved, verdicts=verdicts,
                         avg_confidence=avg_conf,
                         proposal=proposal)
