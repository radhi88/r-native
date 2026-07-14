"""strategy_store.py — JSON persistence for Prompt-Trading strategies +
an in-memory ring buffer for the live decision-log feed.

Follows the project's existing storage convention (per-entity JSON under the
MT5 data dir, same as symbol_configs). Pure I/O — no MT5, no LLM.

Strategies are stored one-file-per-strategy under:
    <DATA>/r_native/strategies/<id>.json

The live LogEntry feed (Feature 4) is kept in a bounded in-process ring so
the monitor UI can poll it cheaply; it is ALSO appended to a JSONL on disk
so it survives a brain restart.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from r_native.strategy_types import Strategy, log_entry


# Mirror the path convention used by symbol_configs / hall_of_fame.
_DATA_ROOT = Path(r"C:\Users\Radhi\MT5\data\r_native")
STRATEGIES_DIR = _DATA_ROOT / "strategies"
LOG_PATH       = _DATA_ROOT / "strategy_decisions.jsonl"

# Allow tests / non-Windows hosts to redirect the root.
def set_data_root(path) -> None:
    global _DATA_ROOT, STRATEGIES_DIR, LOG_PATH
    _DATA_ROOT = Path(path)
    STRATEGIES_DIR = _DATA_ROOT / "strategies"
    LOG_PATH = _DATA_ROOT / "strategy_decisions.jsonl"


# ─── Strategy CRUD ───────────────────────────────────────────────
def save_strategy(strat: Strategy) -> dict:
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    p = STRATEGIES_DIR / f"{strat.id}.json"
    d = strat.to_dict()
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def load_strategy(strategy_id: str) -> Optional[Strategy]:
    p = STRATEGIES_DIR / f"{strategy_id}.json"
    if not p.exists():
        return None
    try:
        return Strategy.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_strategies() -> list[dict]:
    if not STRATEGIES_DIR.exists():
        return []
    out = []
    for p in sorted(STRATEGIES_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    # Newest first
    out.sort(key=lambda d: d.get("createdAt", ""), reverse=True)
    return out


def delete_strategy(strategy_id: str) -> bool:
    p = STRATEGIES_DIR / f"{strategy_id}.json"
    if p.exists():
        try:
            p.unlink()
            return True
        except Exception:
            return False
    return False


def set_status(strategy_id: str, status: str) -> Optional[dict]:
    strat = load_strategy(strategy_id)
    if not strat:
        return None
    if status not in ("ACTIVE", "PAUSED", "STOPPED"):
        return None
    strat.status = status
    return save_strategy(strat)


# ─── Live decision-log feed (Feature 4) ──────────────────────────
_log_lock = threading.Lock()
_log_ring: deque = deque(maxlen=500)
_log_hydrated = False


def _hydrate_log() -> None:
    global _log_hydrated
    if _log_hydrated:
        return
    _log_hydrated = True
    if not LOG_PATH.exists():
        return
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines()[-500:]:
            line = line.strip()
            if not line:
                continue
            try:
                _log_ring.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass


def emit_log(level: str, tag: str, text: str) -> dict:
    """Append a LogEntry to the live ring + JSONL. level ∈ info|ok|warn|err."""
    entry = log_entry(level, tag, text)
    with _log_lock:
        _hydrate_log()
        _log_ring.append(entry)
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return entry


def recent_logs(n: int = 100, tag: Optional[str] = None) -> list[dict]:
    with _log_lock:
        _hydrate_log()
        items = list(_log_ring)
    if tag:
        items = [e for e in items if e.get("tag") == tag]
    return items[-n:]
