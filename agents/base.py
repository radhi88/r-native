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
_ring_hydrated = False


def _ensure():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _hydrate_ring_from_disk():
    """Load the last 500 lines from insights.jsonl into the ring buffer.
    Called once on first emit (cheap, idempotent). Survives brain restarts
    so the UI never shows an empty AI Advisors feed after a quick reboot.

    Also seeds the in-memory dedup window from the loaded insights so
    that "same WARN every 3 minutes after a restart" spam is suppressed.
    Without this, the dedup dict resets to {} on every brain restart and
    every old WARN re-fires on the first tick post-startup.
    """
    global _ring_hydrated
    if _ring_hydrated: return
    _ring_hydrated = True
    if not INSIGHTS_PATH.exists(): return
    try:
        # Read all lines, take last 500
        with INSIGHTS_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        import time as _t
        from datetime import datetime as _dt
        now_s = _t.time()
        for line in lines[-500:]:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
                _insights_ring.append(rec)
                # Seed dedup window for this (agent, msg-prefix) — only if it
                # would still be inside the dedup interval right now.
                if not rec.get("action"):
                    try:
                        ts = _dt.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                        age_s = now_s - ts.timestamp()
                        if 0 <= age_s < DEDUP_INTERVAL_S:
                            sig = (rec.get("agent"), (rec.get("message") or "")[:50])
                            # Store original emit time (now_s - age_s) so window
                            # naturally expires at the right wall-clock moment.
                            prev = _dedup_window.get(sig, 0)
                            _dedup_window[sig] = max(prev, now_s - age_s)
                    except Exception: pass
            except Exception:
                continue
    except Exception as e:
        print(f"[insights] hydrate err: {e}", flush=True)


_dedup_window: dict = {}   # (agent, msg_signature) -> last_emit_ts
DEDUP_INTERVAL_S = 600     # don't emit same message twice within 10 min


def emit_insight(agent: str, level: str, message: str,
                 data: Optional[dict] = None, action: Optional[str] = None):
    """Push an insight to the unified stream. Called by agents.

    level: INFO | WARN | ACT  (ACT = the agent actually changed something)

    Auto-deduplication: identical (agent, first-50-chars-of-message) pairs
    fired more than once within 10 minutes are silently dropped. Stops
    the LLM strategist (and any other agent) from spamming the same
    "blocked: pipeline 14%" warning every 7 minutes.
    """
    _ensure()
    with _insights_lock:
        if not _ring_hydrated:
            _hydrate_ring_from_disk()
    # Dedup check — applies to all levels (INFO/WARN/ACT). ACT-level
    # insights with explicit `action` are exempt (we want every actual
    # state change logged even if the message text is similar).
    if not action:
        import time as _t
        sig = (agent, message[:50])
        now_s = _t.time()
        last = _dedup_window.get(sig, 0)
        if (now_s - last) < DEDUP_INTERVAL_S:
            return None   # silently dropped
        _dedup_window[sig] = now_s
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
    """Most recent insights, newest first. Optionally filter by agent / level.
    Hydrates from JSONL on first call so insights survive brain restarts."""
    with _insights_lock:
        if not _ring_hydrated:
            _hydrate_ring_from_disk()
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
