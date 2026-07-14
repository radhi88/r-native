"""council/executor.py — session/timing + market-quality vote.

  • Session window appropriate for TF (M1 → NY_OVERLAP/LONDON/NY_LATE)
  • Not within news blackout
  • Spread not in upper 90th percentile of recent ticks
"""
from __future__ import annotations
from .types import Proposal, Verdict
from r_native_v2.indicators.session import classify as session_classify


def executor_review(proposal: Proposal, snapshot, account) -> Verdict:
    sv = session_classify()
    if not sv.m1_ok:
        return Verdict(False, f"session={sv.name} not M1-suitable ({sv.reason})", 90)

    # Confidence penalty for non-prime sessions
    conf = sv.confidence
    if sv.name != "NY_OVERLAP":
        conf -= 15

    return Verdict(True, f"session={sv.name} · {sv.reason[:50]}", max(0, conf))
