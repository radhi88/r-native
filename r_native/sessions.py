"""sessions.py — Trading session windows (Algory-style presets).

Times are UTC. Each session = (start_hour, end_hour) inclusive of start, exclusive of end.

Used by:
- trade_gate (filter trades to session window)
- campaign config (set start_hour/end_hour for evolved genomes)
- inspector (annotate which session a strategy targets)
"""
from __future__ import annotations
from datetime import datetime, timezone

# Algory's exact session definitions (UTC)
SESSIONS = {
    "TO":     (0,  4),    # Tokyo Open
    "LO":     (7,  11),   # London Open
    "NYO":    (13, 17),   # New York Open
    "Tokyo":  (0,  9),    # Full Tokyo
    "London": (7,  16),   # Full London
    "NY":     (13, 22),   # Full New York
    "Any":    (0,  24),   # No restriction
}


def in_session(session: str, dt: datetime | None = None) -> bool:
    dt = dt or datetime.now(timezone.utc)
    if session not in SESSIONS: return True
    s, e = SESSIONS[session]
    return s <= dt.hour < e


def detect_session(start_hour: int, end_hour: int) -> str:
    """Find the named session that best matches a (start, end) hour range."""
    for name, (s, e) in SESSIONS.items():
        if s == start_hour and e == end_hour: return name
    # Fuzzy: find session that fully contains the range
    for name, (s, e) in SESSIONS.items():
        if s <= start_hour and e >= end_hour: return name
    return "Custom"


def session_for_hour(h: int) -> list[str]:
    """Return list of sessions active at hour `h` (UTC)."""
    return [name for name, (s, e) in SESSIONS.items()
            if name != "Any" and s <= h < e]


def all_session_names() -> list[str]:
    """Names for UI pills (excluding Any)."""
    return ["TO", "LO", "NYO", "Tokyo", "London", "NY"]
