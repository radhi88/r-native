"""council/reviewer.py — cross-check against recent live history.

  • Has THIS genome been losing on this symbol the last 5 trades?
    → veto (let it cool off / be re-trained)
  • Was the LAST trade closed within 60s of entry by aging cut?
    → market is choppy, raise thresholds
  • Is the proposed direction the same as the last 3 losing trades?
    → veto possible overfit / wrong-side bias
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timedelta
from .types import Proposal, Verdict


JOURNAL = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\journal.jsonl")


def _recent_for_genome(genome: str, symbol: str, n: int = 5) -> list:
    if not JOURNAL.exists(): return []
    out = []
    try:
        with JOURNAL.open(encoding="utf-8") as f:
            for line in f:
                try: e = json.loads(line)
                except: continue
                if e.get("genome") == genome and e.get("symbol") == symbol:
                    out.append(e)
    except Exception: pass
    return out[-n:]


def reviewer_review(proposal: Proposal, snapshot, account) -> Verdict:
    p = proposal
    recent = _recent_for_genome(p.genome, p.symbol, 5)
    if not recent:
        return Verdict(True, "no history yet — fresh start", 70)

    losses = [r for r in recent if (r.get("pnl") or 0) < 0]
    if len(losses) >= 4:
        return Verdict(False,
            f"{p.genome} has {len(losses)}/5 recent losses on {p.symbol}", 85)

    # Consecutive-loss same-direction
    last3 = recent[-3:]
    if (len(last3) == 3
            and all((r.get("pnl") or 0) < 0 for r in last3)
            and all(r.get("side") == p.side for r in last3)):
        return Verdict(False,
            f"3 consecutive losing {p.side}s on {p.symbol} — wrong-side pattern", 90)

    # Chop detection
    last1 = recent[-1] if recent else None
    if last1 and last1.get("close_reason", "").startswith("aging"):
        return Verdict(True, "last trade aged-out — market choppy, lower confidence", 50)

    wins = len(recent) - len(losses)
    return Verdict(True, f"{wins}W/{len(losses)}L last 5 — OK", 75)
