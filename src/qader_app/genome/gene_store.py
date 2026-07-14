"""Strategy DNA file storage."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.paths import dna_dir, ensure_runtime_dirs


DEFAULT_GENOME = {
    "genome_id": "qader_default_v1",
    "version": 1,
    "description": "Safe default Qader strategy DNA. Config only; no source-code mutation.",
    "agent_weights": {
        "fractal_agent": 0.45,
        "smc_agent": 0.45,
        "session": 0.10,
        "ict_sweep_agent": 0.0,
    },
    "confidence_thresholds": {
        "arbiter_pass": 0.70,
        "decision_min": 0.45,
    },
    "risk": {
        "max_lot": 0.01,
        "max_spread_points": 30,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 2.0,
        "max_open_positions": 1,
    },
    "symbols": {
        "XAUUSDm": {"enabled": True, "timeframes": ["M1"], "max_spread_points": 80}
    },
    "sessions": {
        "prefer_london_ny_overlap": True,
        "avoid_low_liquidity": True,
    },
    "performance": {
        "minimum_sample_size": 30,
        "rollback_score_floor": -0.25,
    },
    "created_at": "",
    "updated_at": "",
}


def default_genome_path() -> Path:
    ensure_runtime_dirs()
    return dna_dir() / "default_genome.json"


def active_genome_path() -> Path:
    ensure_runtime_dirs()
    return dna_dir() / "active_genome.json"


def history_path() -> Path:
    ensure_runtime_dirs()
    return dna_dir() / "genome_history.jsonl"


def performance_journal_path() -> Path:
    ensure_runtime_dirs()
    return dna_dir() / "performance_journal.jsonl"


class GeneStore:
    def ensure_defaults(self) -> None:
        ensure_runtime_dirs()
        now = datetime.now(timezone.utc).isoformat()
        genome = {**DEFAULT_GENOME, "created_at": now, "updated_at": now}
        if not default_genome_path().exists():
            default_genome_path().write_text(json.dumps(genome, indent=2, ensure_ascii=False), encoding="utf-8")
        if not active_genome_path().exists():
            active_genome_path().write_text(json.dumps(genome, indent=2, ensure_ascii=False), encoding="utf-8")
        history_path().touch(exist_ok=True)
        performance_journal_path().touch(exist_ok=True)

    def load_default(self) -> dict[str, Any]:
        self.ensure_defaults()
        return json.loads(default_genome_path().read_text(encoding="utf-8"))

    def load_active(self) -> dict[str, Any]:
        self.ensure_defaults()
        return json.loads(active_genome_path().read_text(encoding="utf-8"))

    def save_active(self, genome: dict[str, Any], reason: str = "") -> dict[str, Any]:
        self.ensure_defaults()
        genome = dict(genome)
        genome["updated_at"] = datetime.now(timezone.utc).isoformat()
        active_genome_path().write_text(json.dumps(genome, indent=2, ensure_ascii=False), encoding="utf-8")
        self.append_history("save_active", genome, reason)
        return genome

    def append_history(self, event: str, genome: dict[str, Any], reason: str = "") -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "reason": reason,
            "genome_id": genome.get("genome_id"),
            "version": genome.get("version"),
            "genome": genome,
        }
        with history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def append_performance(self, record: dict[str, Any]) -> None:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
        with performance_journal_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

