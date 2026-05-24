"""agents/base.py — base Agent class + insight stream.

Every agent inherits from Agent and implements .tick().
Agents are not cosmetic — they read live state, make decisions, and
write to the world (HoF pins, kill switch, deploys, etc.).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

AGENTS_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\agents")
INSIGHTS_PATH = AGENTS_DIR / "insights.jsonl"
STATE_PATH    = AGENTS_DIR / "state.json"

# Module-level insight ring buffer (last 500) shared across agents
_insights_lock = threading.Lock()
_insights_ring: deque = deque(maxlen=500)


def _ensure():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def emit_insight(agent: str, level: str, message: str,
                 data: Optional[dict] = None, action: Optional[str] = None):
    """Push an insight to the unified stream. Called by agents.

    level: INFO | WARN | ACT  (ACT = the agent actually changed something)
    """
    _ensure()
    rec = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "agent":   agent,
        "level":   level,
        "message": message,
        "action":  action,
        "data":    data or {},
    }
    with _insights_lock:
        _insights_ring.append(rec)
        try:
            with INSIGHTS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception: pass
    return rec


def get_recent_insights(n: int = 100, agent: str = None, level: str = None) -> list[dict]:
    """Most recent insights, newest first. Optionally filter by agent / level."""
    with _insights_lock:
        items = list(_insights_ring)
    items.reverse()
    if agent:
        items = [r for r in items if r.get("agent") == agent]
    if level:
        items = [r for r in items if r.get("level") == level]
    return items[:n]


def _load_state() -> dict:
    if not STATE_PATH.exists(): return {}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {}


def _save_state(state: dict):
    _ensure()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


class Agent:
    """Base class. Subclass and override .tick()."""
    name: str          = "agent"
    interval_seconds:  int = 60
    description:       str = "an agent"
    default_enabled:   bool = True

    def __init__(self):
        self._stop   = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_tick_at: Optional[str] = None
        self._last_tick_duration_ms: int = 0
        self._tick_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._next_tick_at: Optional[float] = None
        # Read persisted enabled flag (defaults to default_enabled)
        st = _load_state().get(self.name, {})
        self.enabled = bool(st.get("enabled", self.default_enabled))

    # ── lifecycle ──
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"agent-{self.name}")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def toggle(self, enabled: bool = None) -> bool:
        if enabled is None: enabled = not self.enabled
        self.enabled = bool(enabled)
        state = _load_state()
        state.setdefault(self.name, {})["enabled"] = self.enabled
        _save_state(state)
        emit_insight(self.name, "INFO",
                     f"{'enabled' if enabled else 'disabled'} via toggle")
        return self.enabled

    def status(self) -> dict:
        return {
            "name":              self.name,
            "description":       self.description,
            "enabled":           self.enabled,
            "thread_alive":      bool(self._thread and self._thread.is_alive()),
            "interval_seconds":  self.interval_seconds,
            "last_tick_at":      self._last_tick_at,
            "last_tick_ms":      self._last_tick_duration_ms,
            "tick_count":        self._tick_count,
            "error_count":       self._error_count,
            "last_error":        self._last_error,
            "next_tick_in_s":    (max(0, int(self._next_tick_at - time.time()))
                                  if self._next_tick_at else None),
        }

    # ── override these ──
    def tick(self):
        """Called every interval_seconds. Override in subclasses.
        Use emit_insight() to push observations + actions to the stream."""
        raise NotImplementedError

    # ── internals ──
    def _loop(self):
        emit_insight(self.name, "INFO",
                     f"started · interval={self.interval_seconds}s")
        while not self._stop.is_set():
            if not self.enabled:
                self._stop.wait(30)
                continue
            t0 = time.time()
            try:
                self.tick()
                self._tick_count += 1
                self._last_tick_at = datetime.now(timezone.utc).isoformat()
                self._last_tick_duration_ms = int((time.time() - t0) * 1000)
            except Exception as e:
                self._error_count += 1
                self._last_error = f"{type(e).__name__}: {e}"
                emit_insight(self.name, "WARN",
                             f"tick error: {self._last_error}",
                             data={"traceback": traceback.format_exc()[-500:]})
            self._next_tick_at = time.time() + self.interval_seconds
            # Sleep in 5-sec chunks so .stop() responds promptly
            elapsed = 0
            while elapsed < self.interval_seconds and not self._stop.is_set():
                time.sleep(min(5, self.interval_seconds - elapsed))
                elapsed += 5
        emit_insight(self.name, "INFO", "stopped")
