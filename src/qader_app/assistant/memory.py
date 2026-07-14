"""Safe local assistant memory."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.paths import data_dir, ensure_runtime_dirs


SENSITIVE_KEYS = {"password", "passwd", "secret", "api_key", "token", "broker_password"}


def memory_path() -> Path:
    ensure_runtime_dirs()
    return data_dir() / "memory.json"


class QaderMemory:
    def load(self) -> dict[str, Any]:
        path = memory_path()
        if not path.exists():
            return {"preferences": {}, "instructions": [], "last_decision": None}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"preferences": {}, "instructions": [], "last_decision": None}

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._strip_sensitive(data)
        cleaned["updated_at"] = datetime.now(timezone.utc).isoformat()
        memory_path().write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
        return cleaned

    def remember_preference(self, key: str, value: Any) -> dict[str, Any]:
        data = self.load()
        data.setdefault("preferences", {})[key] = value
        return self.save(data)

    def set_last_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        data["last_decision"] = decision
        return self.save(data)

    def _strip_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, val in value.items():
                if str(key).lower() in SENSITIVE_KEYS:
                    continue
                out[key] = self._strip_sensitive(val)
            return out
        if isinstance(value, list):
            return [self._strip_sensitive(v) for v in value]
        return value

