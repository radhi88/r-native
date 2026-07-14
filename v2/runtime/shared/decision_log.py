"""shared/decision_log.py — Unified entry-decision log.

Born 2026-05-28 because: "قرارتهم كل واحد لحاله لكن في مكان واحد".

Every engine keeps its OWN decision logic (independent).
But every entry decision flows through this single recorder, so we can
ask "which engine called the great SELL at 4451?" or
"which engine consistently buys the dips?"

USAGE — drop-in for any trader, right before order_send:

    from runtime.shared.decision_log import record_decision
    rec_id = record_decision(
        source="claude_genome",
        magic=99782,
        symbol="XAUUSDm",
        side="SELL",
        entry=4405.37,
        sl=4408.06,
        tp=4399.06,
        lot=0.02,
        reason="MTF=3/3 DOWN, RSI 38, pressure -2.32, regime TREND_DOWN",
        snap=brain_snap,      # OPTIONAL — the brain_live.json content
    )

    # After order_send returns ticket:
    update_decision_ticket(rec_id, ticket=r.order)

STORAGE
    data/decisions.jsonl        — append-only for tail/grep
    trading.db → entry_decisions — indexed SQL for analysis

Query examples (see runtime/decision_log_query.py):
    python -m runtime.decision_log_query --side BUY --outcome WIN
    python -m runtime.decision_log_query --source claude_genome --last 24h
    python -m runtime.decision_log_query --regime TREND_DOWN --rank
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from runtime.shared.tokens import PATHS

DECISIONS_JSONL = PATHS["brain_decisions"].parent / "decisions.jsonl"


# ──────────────────────────────────────────────────────────
# SQL schema — auto-created on first import
# ──────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entry_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    source          TEXT NOT NULL,
    magic           INTEGER,
    symbol          TEXT,
    side            TEXT,
    entry           REAL,
    sl              REAL,
    tp              REAL,
    lot             REAL,
    reason          TEXT,
    confidence      REAL,

    -- market context snapshot at decision time
    regime          TEXT,
    session         TEXT,
    rsi_m1          REAL,
    rsi_m5          REAL,
    atr_m1          REAL,
    atr_h1          REAL,
    pressure_10m1   INTEGER,
    bias_m1         TEXT,
    bias_m5         TEXT,
    bias_m15        TEXT,
    bias_h1         TEXT,
    mtf_align       TEXT,

    -- linked execution
    ticket          INTEGER DEFAULT 0,
    executed        INTEGER DEFAULT 0,    -- 1 if accepted by MT5
    error           TEXT,

    -- post-close (filled by post-trade hook)
    pnl             REAL,
    exit_price      REAL,
    exit_reason     TEXT,
    duration_sec    INTEGER,
    closed_ts       TEXT
);
CREATE INDEX IF NOT EXISTS idx_dec_source_ts ON entry_decisions(source, ts);
CREATE INDEX IF NOT EXISTS idx_dec_side ON entry_decisions(side);
CREATE INDEX IF NOT EXISTS idx_dec_regime ON entry_decisions(regime);
CREATE INDEX IF NOT EXISTS idx_dec_ticket ON entry_decisions(ticket);
CREATE INDEX IF NOT EXISTS idx_dec_pnl ON entry_decisions(pnl);
"""

# Lazy-init the DB schema on first import (db.py may not exist yet in test env)
try:
    from runtime.shared.db import db as _db
    _db._conn().executescript(SCHEMA_SQL)
except Exception as _e:
    _db = None  # falls back to JSONL-only mode


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_context(snap: Optional[dict]) -> dict:
    """Pull useful fields from a brain_live snapshot."""
    if not snap: return {}
    out = {
        "regime":        snap.get("regime"),
        "session":       snap.get("session"),
        "mtf_align":     snap.get("mtf_align"),
        "pressure_10m1": snap.get("pressure_10m1"),
    }
    bias = snap.get("bias") or {}
    rsi  = snap.get("rsi")  or {}
    atr  = snap.get("atr")  or {}
    out["bias_m1"]  = bias.get("m1")
    out["bias_m5"]  = bias.get("m5")
    out["bias_m15"] = bias.get("m15")
    out["bias_h1"]  = bias.get("h1")
    out["rsi_m1"]   = rsi.get("m1")
    out["rsi_m5"]   = rsi.get("m5")
    out["atr_m1"]   = atr.get("m1")
    out["atr_h1"]   = atr.get("h1")
    return {k: v for k, v in out.items() if v is not None}


# ──────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────
def record_decision(
    *,
    source: str,
    magic: int,
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    lot: float,
    reason: str = "",
    confidence: float = 0.5,
    snap: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> int:
    """Record an entry decision. Returns DB row id (or 0 if SQL unavailable).

    Call BEFORE order_send. After order_send returns, call
    update_decision_ticket() to link the ticket.
    """
    ctx = _extract_context(snap)
    rec = {
        "ts": _now(),
        "source": source,
        "magic": int(magic),
        "symbol": symbol,
        "side": side,
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "lot": float(lot),
        "reason": reason,
        "confidence": float(confidence),
        **ctx,
    }
    if extra:
        rec["extra"] = extra

    # 1. JSONL — always (cheap, append-only)
    DECISIONS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")

    # 2. SQL — if db available
    if _db is None:
        return 0
    try:
        rec_for_sql = {k: v for k, v in rec.items()
                       if k in ("ts", "source", "magic", "symbol", "side",
                                "entry", "sl", "tp", "lot", "reason", "confidence",
                                "regime", "session", "rsi_m1", "rsi_m5",
                                "atr_m1", "atr_h1", "pressure_10m1",
                                "bias_m1", "bias_m5", "bias_m15", "bias_h1",
                                "mtf_align")}
        return _db.insert("entry_decisions", rec_for_sql)
    except Exception:
        return 0


def update_decision_ticket(rec_id: int, ticket: int, error: str = "") -> None:
    """After order_send, update the row with ticket + execution status."""
    if _db is None or rec_id <= 0: return
    try:
        _db.execute(
            "UPDATE entry_decisions SET ticket=?, executed=?, error=? WHERE id=?",
            (int(ticket), 1 if ticket > 0 else 0, error, int(rec_id)),
        )
    except Exception:
        pass


def update_decision_outcome(ticket: int, pnl: float, exit_price: float,
                             exit_reason: str = "", duration_sec: int = 0) -> None:
    """Backfill outcome when a trade closes."""
    if _db is None: return
    try:
        _db.execute(
            """UPDATE entry_decisions
               SET pnl=?, exit_price=?, exit_reason=?, duration_sec=?, closed_ts=?
               WHERE ticket=? AND pnl IS NULL""",
            (float(pnl), float(exit_price), exit_reason,
             int(duration_sec), _now(), int(ticket)),
        )
    except Exception:
        pass


__all__ = [
    "record_decision",
    "update_decision_ticket",
    "update_decision_outcome",
    "DECISIONS_JSONL",
]
