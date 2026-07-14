"""shared/db.py — Single SQLite database for the entire trading system.

Born 2026-05-28 — replaces 20+ scattered JSONL files with one queryable .db.
Uses SQLite (same engine MT5 ships natively — MetaEditor can open this file
directly for inspection).

DB FILE: data/trading.db

TABLES:
  • trades              — every closed trade (one row per exit)
  • signals             — every signal a trader/genome emitted
  • brain_snapshots     — periodic market state snapshots
  • regime_history      — regime transitions (TREND_UP ↔ CHOP etc.)
  • orchestrator_log    — every orchestrator decision
  • council_votes       — palace council votes
  • genome_fitness      — per-cycle genome scores
  • account_equity      — periodic equity snapshots
  • events              — generic event log (errors, alerts, restarts)

USAGE:
    from runtime.shared.db import db
    db.insert_trade({...})
    rows = db.query("SELECT magic, SUM(pnl) FROM trades GROUP BY magic")

DESIGN PRINCIPLES:
  • Single connection per process (SQLite handles serialization)
  • WAL mode for concurrent readers (dashboard + bots reading same db)
  • All inserts use parameterized queries (SQL injection safe)
  • Schema versioned via PRAGMA user_version
  • Bootstrap creates tables on first import
"""
from __future__ import annotations
import sqlite3
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from runtime.shared.tokens import PATHS

DB_PATH = PATHS["brain_decisions"].parent / "trading.db"
SCHEMA_VERSION = 1

# ──────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    magic           INTEGER NOT NULL,
    source          TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    lot             REAL NOT NULL,
    entry           REAL,
    exit_price      REAL,
    sl              REAL,
    tp              REAL,
    ticket          INTEGER,
    pnl             REAL,
    duration_sec    INTEGER,
    reason          TEXT,
    confidence      REAL,
    regime_at_fire  TEXT,
    session_at_fire TEXT,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_magic ON trades(magic);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    source          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    price           REAL,
    confidence      REAL,
    genome          TEXT,
    payload_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_source_ts ON signals(source, ts);

CREATE TABLE IF NOT EXISTS brain_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    bid             REAL,
    ask             REAL,
    bias_m1         TEXT,
    bias_m5         TEXT,
    bias_m15        TEXT,
    bias_h1         TEXT,
    rsi_m1          REAL,
    rsi_m5          REAL,
    atr_m1          REAL,
    atr_h1          REAL,
    mtf_align       TEXT,
    pressure_10m1   INTEGER,
    session         TEXT,
    regime          TEXT,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON brain_snapshots(ts);

CREATE TABLE IF NOT EXISTS regime_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    regime          TEXT NOT NULL,
    reason          TEXT,
    adx_m5          REAL,
    atr_m5          REAL,
    vol_ratio       REAL
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_history(ts);

CREATE TABLE IF NOT EXISTS orchestrator_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    regime          TEXT,
    active_magics   TEXT,
    reasoning       TEXT
);

CREATE TABLE IF NOT EXISTS council_votes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    genome          TEXT,
    side            TEXT,
    approves        INTEGER,
    vetos           INTEGER,
    verdict         TEXT,
    payload_json    TEXT
);

CREATE TABLE IF NOT EXISTS genome_fitness (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    name            TEXT NOT NULL,
    generation      INTEGER,
    cycles          INTEGER,
    buy_signals     INTEGER,
    sell_signals    INTEGER,
    wait_signals    INTEGER,
    avg_confidence  REAL,
    realized_pnl    REAL
);
CREATE INDEX IF NOT EXISTS idx_fitness_name ON genome_fitness(name);

CREATE TABLE IF NOT EXISTS account_equity (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    balance         REAL NOT NULL,
    equity          REAL NOT NULL,
    floating        REAL NOT NULL,
    margin_free     REAL,
    open_positions  INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    category        TEXT,
    severity        TEXT,
    source          TEXT,
    message         TEXT,
    payload_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);
"""


# ──────────────────────────────────────────────────────────
# Connection (one per thread)
# ──────────────────────────────────────────────────────────
class DB:
    _local = threading.local()

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    def _bootstrap(self) -> None:
        c = self._conn()
        c.executescript(SCHEMA_SQL)
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ──────────────────────────────────────────────────────
    # Query helpers
    # ──────────────────────────────────────────────────────
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn().execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self._conn().execute(sql, params).fetchall())

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        col_list = ",".join(cols)
        cur = self._conn().execute(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            tuple(row[c] for c in cols),
        )
        return cur.lastrowid or 0

    @contextmanager
    def transaction(self):
        c = self._conn()
        try:
            c.execute("BEGIN")
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK"); raise

    # ──────────────────────────────────────────────────────
    # High-level convenience inserts (typed wrappers)
    # ──────────────────────────────────────────────────────
    def insert_trade(self, *, magic: int, symbol: str, side: str, lot: float,
                     ticket: int, entry: float, sl: float, tp: float,
                     pnl: Optional[float] = None, source: str = "",
                     reason: str = "", confidence: float = 0.5,
                     regime_at_fire: Optional[str] = None,
                     session_at_fire: Optional[str] = None,
                     raw: Optional[dict] = None) -> int:
        return self.insert("trades", {
            "ts": _now_iso(),
            "magic": magic, "source": source, "symbol": symbol,
            "side": side, "lot": lot, "entry": entry, "exit_price": None,
            "sl": sl, "tp": tp, "ticket": ticket, "pnl": pnl,
            "duration_sec": None, "reason": reason, "confidence": confidence,
            "regime_at_fire": regime_at_fire, "session_at_fire": session_at_fire,
            "raw_json": json.dumps(raw, default=str) if raw else None,
        })

    def insert_signal(self, *, source: str, symbol: str, action: str,
                      price: float, confidence: float = 0.5,
                      genome: Optional[str] = None,
                      payload: Optional[dict] = None) -> int:
        return self.insert("signals", {
            "ts": _now_iso(), "source": source, "symbol": symbol,
            "action": action, "price": price, "confidence": confidence,
            "genome": genome,
            "payload_json": json.dumps(payload, default=str) if payload else None,
        })

    def insert_account_equity(self, *, balance: float, equity: float,
                              floating: float, margin_free: float = 0,
                              open_positions: int = 0) -> int:
        return self.insert("account_equity", {
            "ts": _now_iso(), "balance": balance, "equity": equity,
            "floating": floating, "margin_free": margin_free,
            "open_positions": open_positions,
        })

    def insert_event(self, *, category: str, severity: str, source: str,
                     message: str, payload: Optional[dict] = None) -> int:
        return self.insert("events", {
            "ts": _now_iso(), "category": category, "severity": severity,
            "source": source, "message": message,
            "payload_json": json.dumps(payload, default=str) if payload else None,
        })

    # ──────────────────────────────────────────────────────
    # Quick analytics
    # ──────────────────────────────────────────────────────
    def leaderboard_24h(self) -> list[dict]:
        """Return per-magic stats over last 24h."""
        return [dict(r) for r in self.query("""
            SELECT magic, COUNT(*) AS trades,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(pnl) AS pnl,
                   AVG(pnl) AS expectancy
            FROM trades
            WHERE ts > datetime('now', '-1 day') AND pnl IS NOT NULL
            GROUP BY magic
            ORDER BY pnl DESC
        """)]

    def best_genomes(self, top_n: int = 5) -> list[dict]:
        return [dict(r) for r in self.query(f"""
            SELECT name, AVG(avg_confidence) AS conf,
                   SUM(buy_signals + sell_signals) AS signals,
                   COUNT(*) AS cycles
            FROM genome_fitness
            WHERE ts > datetime('now', '-7 day')
            GROUP BY name
            ORDER BY conf DESC
            LIMIT {top_n}
        """)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────
# Module singleton
# ──────────────────────────────────────────────────────────
db = DB()

__all__ = ["db", "DB", "DB_PATH"]
