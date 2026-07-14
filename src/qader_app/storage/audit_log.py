"""JSONL audit logging for Qader actions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.paths import ensure_runtime_dirs, logs_dir


def audit_log_path() -> Path:
    ensure_runtime_dirs()
    return logs_dir() / "qader_audit.jsonl"


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def log_action(
    action: str,
    permission: str | None = None,
    allowed: bool | None = None,
    reason: str = "",
    module: str = "qader",
    result: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "permission_checked": permission,
        "allowed": allowed,
        "reason": reason,
        "module": module,
        "result": _json_safe(result),
        "metadata": _json_safe(metadata or {}),
    }
    path = audit_log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

