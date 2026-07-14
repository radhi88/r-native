"""strategy_gate.py - read-only discipline gates from reflection/strategy.json.

Lets live executors honor the reflection engine's discipline tunables WITHOUT
importing the rest of the reflection package. Stdlib only, no MetaTrader5.

FAIL-OPEN by design: any missing/unreadable field returns "no block". A gate
here can only ever ADD a restriction (pause NEW entries) - it can never remove
an existing guard or place/size a trade.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STRATEGY_FILE = Path(__file__).resolve().parent / "strategy.json"


def load_strategy() -> dict:
    try:
        return json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _in_night_window(hour: int, start: int, end: int) -> bool:
    """True if `hour` (0-23 UTC) falls in [start, end). Wraps midnight when
    start > end (e.g. 22 -> 8 covers 22,23,0..7)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def night_block_reason(symbol: str, now_utc: datetime | None = None) -> str:
    """Non-empty reason string if NEW entries on `symbol` are paused by the
    night-trade block right now (UTC); '' if entries are allowed. Fail-open."""
    try:
        nb = load_strategy().get("night_trade_block") or {}
        if not nb.get("enabled"):
            return ""
        if symbol in (nb.get("exempt_symbols") or []):
            return ""  # e.g. BTCUSDm trades 24/7 by design
        now_utc = now_utc or datetime.now(timezone.utc)
        # The window is expressed in BROKER-SERVER time (the frame MT5 deal
        # timestamps use and the edge was measured in). Convert the live UTC clock
        # to server time before comparing. offset defaults to 0 (== treat as UTC).
        offset = int(nb.get("server_utc_offset_hours", 0))
        server_hour = (now_utc.hour + offset) % 24
        start = int(nb.get("start_hour", nb.get("start_utc", 22)))
        end   = int(nb.get("end_hour", nb.get("end_utc", 8)))
        if _in_night_window(server_hour, start, end):
            return f"night block {start:02d}:00-{end:02d}:00 srv (h={server_hour:02d})"
    except Exception:
        pass
    return ""


def entry_block_reason(symbol: str, now_utc: datetime | None = None) -> str:
    """Aggregate of all reflection discipline gates that veto a NEW entry.
    Currently just the night-trade block; add future entry gates here."""
    return night_block_reason(symbol, now_utc)
