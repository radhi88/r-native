"""structured_logger.py — JSONL pipeline loggers."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from .project_root import PROJECT_ROOT as _ROOT, APPDATA_FRIDAY as _APPDATA_FRIDAY
_PROJECT_LOG_DIR  = _ROOT / "logs"
_APPDATA_LOG_DIR  = _APPDATA_FRIDAY / "logs"
LOG_DIR = _PROJECT_LOG_DIR   # primary: project-level logs (verifiable in repo)
for _d in (_PROJECT_LOG_DIR, _APPDATA_LOG_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

_FILES = {
    "signal":    LOG_DIR / "signal_log.jsonl",
    "decision":  LOG_DIR / "decision_log.jsonl",
    "conflict":  LOG_DIR / "conflict_log.jsonl",
    "risk":      LOG_DIR / "risk_log.jsonl",
    "position":  LOG_DIR / "position_log.jsonl",
    "execution": LOG_DIR / "execution_log.jsonl",
    "error":     LOG_DIR / "error_log.jsonl",
}

def _write(channel: str, record: dict) -> None:
    record.setdefault("ts", datetime.now(timezone.utc).isoformat())
    for log_dir in (_PROJECT_LOG_DIR, _APPDATA_LOG_DIR):
        try:
            path = log_dir / _FILES[channel].name
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

def log_signal(source: str, symbol: str, tf: str, direction: str, confidence: float, reason: str = "") -> None:
    _write("signal", {"source": source, "symbol": symbol, "tf": tf, "direction": direction, "confidence": round(confidence, 3), "reason": reason})

def log_decision(action: str, symbol: str, tf: str, confidence: float, approved: list, blocked: list, reason: str = "") -> None:
    _write("decision", {"action": action, "symbol": symbol, "tf": tf, "confidence": round(confidence, 3), "approved": approved, "blocked": blocked, "reason": reason})

def log_conflict(symbol: str, conflict_type: str, detail: str, blocked: bool) -> None:
    _write("conflict", {"symbol": symbol, "conflict_type": conflict_type, "detail": detail, "blocked": blocked})

def log_risk(symbol: str, approved: bool, lot: float, reason: str, warnings: list) -> None:
    _write("risk", {"symbol": symbol, "approved": approved, "lot": lot, "reason": reason, "warnings": warnings})

def log_position(ticket: int, action: str, symbol: str, reason: str, source: str = "") -> None:
    _write("position", {"ticket": ticket, "action": action, "symbol": symbol, "reason": reason, "source": source})

def log_execution(action: str, symbol: str, lot: float, magic: int, success: bool, retcode: int, simulated: bool, comment: str = "") -> None:
    _write("execution", {"action": action, "symbol": symbol, "lot": lot, "magic": magic, "success": success, "retcode": retcode, "simulated": simulated, "comment": comment})

def log_error(component: str, error: str, context: dict | None = None) -> None:
    _write("error", {"component": component, "error": error, "context": context or {}})
