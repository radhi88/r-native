"""r_native/external_gate.py — Cross-system veto bridge.

Born 2026-05-28 to let R Native respect the Claude orchestrator's
regime decision. Reads active_engines.json (written by Claude's
trader_orchestrator) and blocks R Native trades when the orchestrator
says STANDBY for magic 20260605.

DESIGN:
  - Pure-stdlib (no imports from r_native_v2 — keeps systems decoupled)
  - Fail-OPEN: if file missing/stale/parse-error → allow trade
    (so a crashed orchestrator never deadlocks R Native)
  - Cached for 2s to avoid hammering disk on every check
  - Lives in r_native/ — R Native owns its own consumer

USAGE (from any R Native module):
    from r_native.external_gate import can_trade
    allowed, reason = can_trade(R_MAGIC)
    if not allowed:
        return {"ok": False, "reason": f"external veto: {reason}"}
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_FILE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\active_engines.json")
MAX_STALE_SEC = 60
CACHE_SEC = 2.0

_cache: dict = {}
_cache_ts: float = 0.0


def _load() -> dict | None:
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


def can_trade(magic: int) -> tuple[bool, str]:
    """Return (allowed, reason).

    Fail-open: if orchestrator is offline or stale, allow.
    Block only when orchestrator is fresh AND magic is in standby.
    """
    data = _load()
    if not data:
        return True, "orchestrator offline → allow"

    # Staleness check
    ts = data.get("ts")
    if ts:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            if age > MAX_STALE_SEC:
                return True, f"orchestrator stale {int(age)}s → allow"
        except Exception:
            return True, "orchestrator ts unparseable → allow"

    standby = data.get("standby_magics", [])
    if magic in standby:
        regime = data.get("regime", "?")
        return False, f"orchestrator standby (regime {regime})"

    return True, "ok"


def summary() -> str:
    """Human one-liner for logs."""
    data = _load()
    if not data:
        return "orchestrator offline"
    return f"regime {data.get('regime','?')} · active {len(data.get('active_magics', []))} engines"


__all__ = ["can_trade", "summary"]
