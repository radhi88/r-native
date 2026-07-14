"""Dry-run result evaluation for Qader learning."""
from __future__ import annotations

from statistics import mean
from typing import Any

from qader_app.genome.gene_store import GeneStore
from qader_app.storage.audit_log import log_action


class EvaluationEngine:
    def __init__(self, store: GeneStore | None = None):
        self.store = store or GeneStore()

    def score_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        action = str(decision.get("final_action") or decision.get("result") or "HOLD")
        confidence = float(decision.get("confidence") or decision.get("final_confidence") or 0.0)
        risk_status = str(decision.get("risk_status") or "")
        blocked = "blocked" in risk_status.lower() or action in {"HOLD", "NO_CONFIRMATION"}
        score = confidence if not blocked else 0.0
        if decision.get("error"):
            score -= 1.0
        record = {"action": action, "confidence": confidence, "risk_status": risk_status, "score": score}
        self.store.append_performance(record)
        log_action("score_decision", None, True, "decision_scored", "evaluation_engine", result=record)
        return record

    def summarize(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            return {"count": 0, "score": 0.0, "recommendation": "collect_more_data"}
        scores = [float(r.get("score", 0.0)) for r in records]
        avg = mean(scores)
        recommendation = "tighten_thresholds" if avg < 0.25 else "maintain_or_relax"
        return {"count": len(records), "score": round(avg, 4), "recommendation": recommendation}

