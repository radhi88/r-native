"""shared/agent_operator.py — Claude-grade powers for every agent.

Born 2026-05-29 from the user's mandate that the agents stop being spectators:

  "الوكلاء يقومون بما تقومه به انت بالضبط ... وليس متفرجين، اعطهم جميع
   الصلاحيات كما لديك ... وقبل اطلاقها يقومون باستشاراتك."

Each agent wraps itself in an `AgentOperator(name)` and gets the SAME verbs
Claude uses — tune a parameter, flip a flag, edit code, crown a new live
brain, restart a service — except every verb files a PROPOSAL through
agent_governance instead of acting unilaterally. The proposal only goes live
after the gate clears (peer consensus for safe changes; Claude's consult for
anything that touches money or code).

It also gives agents the OTHER half of being an operator: judgement on peers'
work. `review_peers()` lets an agent vote on pending proposals using a policy,
so the consensus mechanism has real, opinionated voters instead of rubber stamps.

This module never touches MT5 or live files directly — it only ever calls into
agent_governance. That keeps the safety boundary in exactly one place.
"""
from __future__ import annotations
from typing import Optional

from runtime.shared import agent_governance as gov


class AgentOperator:
    """A thin, safe handle an agent uses to act like Claude — behind the gate."""

    def __init__(self, agent: str):
        self.agent = agent

    # ── propose actions (Claude's verbs) ─────────────────────────────────────
    def tune(self, param: str, value, rationale: str, *, sym: Optional[str] = None,
             service: str = "unified_trader", risk: str = gov.RISK_LOW) -> str:
        """Propose a genome parameter change. sym=None → shared champion genome.
        Money-touching params (lot/risk_pct/sl/tp/max_open) auto-escalate to
        Claude consult inside governance — the agent can't downgrade that."""
        target = f"genome:{sym}:{param}" if sym else f"genome:{param}"
        return gov.propose(self.agent, "tune_param", target,
                           {"value": value, "service": service}, rationale, risk)

    def flag(self, key: str, value, rationale: str, *,
             service: str = "unified_trader", risk: str = gov.RISK_LOW) -> str:
        """Propose a runtime override flag (services read agent_overrides.json)."""
        return gov.propose(self.agent, "set_override", f"override:{key}",
                           {"value": value, "service": service}, rationale, risk)

    def edit_code(self, file: str, summary: str, rationale: str, *,
                  service: str, diff: str = "") -> str:
        """Propose a code change. ALWAYS HIGH → Claude writes the actual diff
        after approving; governor then restarts `service`. The agent supplies
        the intent + a summary (and optionally a suggested diff for Claude)."""
        return gov.propose(self.agent, "edit_code", f"code:{file}",
                           {"service": service, "diff_summary": summary, "diff": diff},
                           rationale, gov.RISK_HIGH)

    def crown(self, genome: dict, fitness: float, rationale: str, *,
              dethroned: str = "", name: str = "") -> str:
        """Propose deploying `genome` as the new LIVE brain. ALWAYS HIGH →
        Claude consult, because crowning is the user's "قبل اطلاقها" moment."""
        return gov.propose(self.agent, "crown_genome", "genome:crown",
                           {"genome": genome, "name": name or genome.get("name"),
                            "fitness": fitness, "dethroned": dethroned,
                            "note": rationale},
                           rationale, gov.RISK_HIGH)

    def restart(self, service: str, rationale: str) -> str:
        return gov.propose(self.agent, "restart_service", f"service:{service}",
                           {"service": service}, rationale, gov.RISK_LOW)

    # ── peer review (the judgement half of being an operator) ────────────────
    def review_peers(self, policy=None) -> list[tuple[str, str]]:
        """Vote on every open peer proposal. Returns [(pid, new_status), ...].

        Default policy: APPROVE safe peer changes (LOW, non-money, sane action),
        ABSTAIN on money/code (those need Claude, not a peer rubber-stamp — so we
        simply don't vote and let them sit in the consult queue). A custom
        `policy(proposal) -> Optional[bool]` may override (None = abstain)."""
        policy = policy or self._default_policy
        out: list[tuple[str, str]] = []
        for raw in gov._load_all().values():
            p = gov.Proposal(**raw)
            if p.agent == self.agent:                 # never self-vote
                continue
            if p.status not in (gov.ST_PENDING,):     # only fresh ones
                continue
            verdict = policy(p)
            if verdict is None:
                continue
            status = gov.vote(p.id, self.agent, bool(verdict),
                              note=f"peer-review by {self.agent}")
            out.append((p.id, status))
        return out

    @staticmethod
    def _default_policy(p: "gov.Proposal") -> Optional[bool]:
        # Money/code/crown → abstain (Claude's call, not consensus).
        if p.risk == gov.RISK_HIGH:
            return None
        # Safe, bounded tweaks → approve.
        if p.action in ("tune_param", "set_override", "set_flag", "restart_service"):
            return True
        return None

    # ── visibility ───────────────────────────────────────────────────────────
    def my_pending(self) -> list[gov.Proposal]:
        return [gov.Proposal(**r) for r in gov._load_all().values()
                if gov.Proposal(**r).agent == self.agent
                and gov.Proposal(**r).status not in (gov.ST_APPLIED, gov.ST_REJECTED)]


__all__ = ["AgentOperator"]
