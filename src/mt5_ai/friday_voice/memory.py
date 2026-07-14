from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import FridayVoiceConfig, log_event


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class FridayMemory:
    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self.path = Path(config.memory_path)
        self._lock = threading.RLock()
        self.data = self._load()

    def _default(self) -> dict[str, Any]:
        return {
            "version": "0.1",
            "created_at": _now(),
            "updated_at": _now(),
            "preferences": {
                "symbol": self.config.default_symbol,
                "timeframe": self.config.default_timeframe,
                "voice": self.config.tts_voice,
                "style": "short_spoken",
            },
            "conversations": [],
            "facts": [],
            "recent_analyses": [],
        }

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            log_event("MEMORY", f"load failed: {exc}")
        return self._default()

    def save(self) -> None:
        if not self.config.memory_enabled:
            return
        with self._lock:
            self.data["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def remember_turn(self, user: str, assistant: str, category: str = "CHAT") -> None:
        if not self.config.memory_enabled:
            return
        with self._lock:
            self.data.setdefault("conversations", []).append(
                {
                    "time": _now(),
                    "category": category,
                    "user": user,
                    "assistant": assistant,
                }
            )
            self.data["conversations"] = self.data["conversations"][-80:]
            self.save()

    def remember_analysis(self, payload: dict[str, Any]) -> None:
        if not self.config.memory_enabled:
            return
        with self._lock:
            self.data.setdefault("recent_analyses", []).append({"time": _now(), **payload})
            self.data["recent_analyses"] = self.data["recent_analyses"][-40:]
            self.save()

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock:
            self.data.setdefault("preferences", {})[key] = value
            self.save()

    def preferences(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.data.get("preferences") or {})

    def recent_turns(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            return list((self.data.get("conversations") or [])[-limit:])

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        q = str(query or "").strip().lower()
        if not q:
            return []

        hits: list[dict[str, Any]] = []
        with self._lock:
            rows = list(self.data.get("conversations") or []) + list(self.data.get("facts") or [])

        for row in reversed(rows):
            text = json.dumps(row, ensure_ascii=False).lower()
            if q in text:
                hits.append(row)
                if len(hits) >= limit:
                    break
        return hits
