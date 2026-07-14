"""Profile persistence for first-run onboarding."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.paths import data_dir, ensure_runtime_dirs


def profile_path() -> Path:
    ensure_runtime_dirs()
    return data_dir() / "profile.json"


DEFAULT_PROFILE = {
    "preferred_name": "",
    "language": "bilingual",
    "tone": "professional",
    "created_at": "",
    "updated_at": "",
}


class ProfileStore:
    def exists(self) -> bool:
        return profile_path().exists()

    def load(self) -> dict[str, Any]:
        path = profile_path()
        if not path.exists():
            return dict(DEFAULT_PROFILE)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {**DEFAULT_PROFILE, **data}
        except Exception:
            return dict(DEFAULT_PROFILE)

    def save(self, profile: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.load()
        data = {**existing, **profile, "updated_at": now}
        if not data.get("created_at"):
            data["created_at"] = now
        path = profile_path()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

