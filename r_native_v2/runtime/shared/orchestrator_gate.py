"""shared/orchestrator_gate.py — Single source of truth for "should I trade?"

Born 2026-05-28 via /design-system Phase 3 — wires every trader to
respect the orchestrator's regime-aware decision before firing entries.

USAGE in any trader:
    from runtime.shared.orchestrator_gate import is_engine_active

    blocker = is_engine_active(MAGIC)
    if blocker:
        # log once, sleep, retry
        time.sleep(POLL); continue
    # ...proceed with entry...

DESIGN:
  • Read active_engines.json (orchestrator output)
  • If file missing or stale > MAX_STALE_SEC → fail OPEN (allow trade)
    so a crashed orchestrator doesn't freeze the whole system
  • If magic is in active_magics → return None (go ahead)
  • If magic is in standby_magics → return human-readable reason

CACHE:
  Reads are cached for CACHE_SEC to avoid hammering disk every 5s
  in every trader process.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from typing import Optional

from runtime.shared.tokens import PATHS

ACTIVE_FILE = PATHS["active_engines"]
MAX_STALE_SEC = 60      # if orchestrator hasn't written in >60s, fail OPEN
CACHE_SEC = 2.0          # how long to trust cached read

_cache: dict = {}
_cache_ts: float = 0.0


def _load() -> dict | None:
    """Cached JSON read."""
    global _cache, _cache_ts
    now = time.time()
    if now - _cache_ts < CACHE_SEC and _cache:
        return _cache
    if not ACTIVE_FILE.exists():
        return None
    try:
        _cache = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        _cache_ts = now
        return _cache
    except Exception:
        return None


def is_engine_active(magic: int) -> Optional[str]:
    """Return None if engine is allowed to trade, else a reason string.

    Fail-open semantics:
      • orchestrator file missing → ALLOW (return None) — bootstrap mode
      • orchestrator file stale   → ALLOW — orchestrator may have crashed
      • magic in active_magics    → ALLOW
      • magic in standby_magics   → BLOCK with reason
      • magic in neither (unknown engine) → ALLOW (don't block unregistered)
    """
    data = _load()
    if not data:
        return None  # fail open

    # staleness check
    ts = data.get("ts")
    if ts:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            if age > MAX_STALE_SEC:
                return None  # fail open
        except Exception:
            return None  # fail open on parse error

    active = data.get("active_magics", [])
    standby = data.get("standby_magics", [])

    if magic in active:
        return None
    if magic in standby:
        regime = data.get("regime", "?")
        return f"STANDBY (regime {regime}) — orchestrator says no edge"
    # not registered → allow
    return None


def get_active_summary() -> str:
    """Human-friendly one-line summary — useful for dashboards/logs."""
    data = _load()
    if not data:
        return "orchestrator OFFLINE"
    regime = data.get("regime", "?")
    active = data.get("active_magics", [])
    return f"regime {regime} · active {len(active)} engine(s)"


__all__ = ["is_engine_active", "get_active_summary"]
