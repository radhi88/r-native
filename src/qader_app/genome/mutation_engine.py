"""Safe strategy DNA mutation proposals."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.genome.gene_store import GeneStore
from qader_app.storage.audit_log import log_action


@dataclass(slots=True)
class MutationProposal:
    proposal_id: str
    reason: str
    changes: dict[str, Any]
    requires_approval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class MutationEngine:
    def __init__(self, store: GeneStore | None = None, guard: PermissionsGuard | None = None):
        self.store = store or GeneStore()
        self.guard = guard or PermissionsGuard()

    def propose_threshold_adjustment(self, metric: dict[str, Any]) -> MutationProposal:
        score = float(metric.get("score", 0.0))
        current = self.store.load_active()
        threshold = float(current.get("confidence_thresholds", {}).get("arbiter_pass", 0.70))
        if score < -0.10:
            new_threshold = min(0.90, threshold + 0.02)
            reason = "Recent dry-run outcomes underperformed; propose stricter arbiter threshold."
        else:
            new_threshold = max(0.65, threshold - 0.01)
            reason = "Recent dry-run outcomes are stable; propose slight threshold relaxation."
        return MutationProposal(
            proposal_id=f"proposal_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            reason=reason,
            changes={"confidence_thresholds": {"arbiter_pass": round(new_threshold, 3)}},
            metadata={"input_metric": metric, "old_threshold": threshold},
        )

    def apply(self, proposal: MutationProposal, approved: bool = False) -> dict[str, Any]:
        if not approved:
            log_action("genome_mutation_rejected", "can_modify_strategy_dna", False, "approval_required", "mutation_engine", result=proposal.proposal_id)
            return {"applied": False, "reason": "approval_required", "proposal": proposal.proposal_id}
        perm = self.guard.check("can_modify_strategy_dna", "apply_genome_mutation", "mutation_engine")
        if not perm.allowed:
            return {"applied": False, "reason": perm.reason, "proposal": proposal.proposal_id}
        current = self.store.load_active()
        updated = self._deep_merge(deepcopy(current), proposal.changes)
        updated["version"] = int(updated.get("version", 1)) + 1
        self.store.save_active(updated, proposal.reason)
        log_action("genome_mutation_applied", "can_modify_strategy_dna", True, proposal.reason, "mutation_engine", result=proposal.changes)
        return {"applied": True, "genome": updated, "proposal": proposal.proposal_id}

    def rollback_to_default(self, reason: str = "performance_floor_breached") -> dict[str, Any]:
        perm = self.guard.check("can_modify_strategy_dna", "rollback_genome", "mutation_engine")
        if not perm.allowed:
            return {"rolled_back": False, "reason": perm.reason}
        default = self.store.load_default()
        default["version"] = int(self.store.load_active().get("version", 1)) + 1
        self.store.save_active(default, reason)
        log_action("genome_rollback", "can_modify_strategy_dna", True, reason, "mutation_engine")
        return {"rolled_back": True, "genome": default}

    def auto_rollback_if_bad(self, score: float) -> dict[str, Any]:
        active = self.store.load_active()
        floor = float(active.get("performance", {}).get("rollback_score_floor", -0.25))
        if score < floor:
            return self.rollback_to_default(f"score {score:.3f} below floor {floor:.3f}")
        return {"rolled_back": False, "reason": "score_above_floor"}

    @staticmethod
    def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = MutationEngine._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

