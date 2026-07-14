"""Minimal Qader learning loop."""
from __future__ import annotations

from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.genome.evaluation_engine import EvaluationEngine
from qader_app.genome.mutation_engine import MutationEngine
from qader_app.storage.audit_log import log_action


class LearningService:
    def __init__(
        self,
        evaluator: EvaluationEngine | None = None,
        mutations: MutationEngine | None = None,
        guard: PermissionsGuard | None = None,
    ):
        self.evaluator = evaluator or EvaluationEngine()
        self.mutations = mutations or MutationEngine()
        self.guard = guard or PermissionsGuard()

    def collect_and_propose(self, decisions: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
        scored = [self.evaluator.score_decision(d) for d in decisions]
        summary = self.evaluator.summarize(scored)
        proposal = self.mutations.propose_threshold_adjustment(summary)
        log_action(
            "learning_collect_and_propose",
            None,
            True,
            "proposal_created",
            "learning_service",
            result={"summary": summary, "proposal": proposal.changes, "context": context or {}},
        )
        return {"summary": summary, "proposal": proposal, "context": context or {}}

    def collect_propose_and_apply(
        self,
        decisions: list[dict[str, Any]],
        *,
        approved: bool = False,
        apply: bool = False,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.collect_and_propose(decisions, context=context)
        proposal = result["proposal"]
        if apply:
            application = self.apply_proposal(proposal, approved=approved)
        else:
            application = {"applied": False, "reason": "apply_disabled", "proposal": proposal.proposal_id}
        result["application"] = application
        log_action(
            "learning_apply_proposal",
            "can_modify_strategy_dna",
            bool(application.get("applied")),
            str(application.get("reason", "applied" if application.get("applied") else "not_applied")),
            "learning_service",
            result={
                "summary": result.get("summary"),
                "proposal": proposal.changes,
                "application": application,
                "context": context or {},
            },
        )
        return result

    def apply_proposal(self, proposal, approved: bool = False) -> dict[str, Any]:
        return self.mutations.apply(proposal, approved=approved)
