import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone

from .config import JOURNAL_DIR


TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def tokenize(text):
    return [token.lower() for token in TOKEN_RE.findall(text or "") if len(token) > 1]


class NeuralMemory:
    """Private local long-term memory.

    This is intentionally local SQLite memory. It does not call cloud APIs.
    Retrieval is lightweight lexical/vector-like scoring so it works before a
    larger local LLM is installed.
    """

    def __init__(self, path=None):
        self.path = path or (JOURNAL_DIR / "jarvis_memory.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self):
        return sqlite3.connect(self.path)

    def _init_db(self):
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    importance REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    result TEXT DEFAULT '',
                    status TEXT DEFAULT 'ok',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT DEFAULT '{}',
                    allowed INTEGER NOT NULL,
                    reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    payload TEXT DEFAULT '{}',
                    sent INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def remember(self, role, content, tags=None, importance=1.0):
        content = (content or "").strip()
        if not content:
            return None

        tags = ",".join(tags or [])
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories (role, content, tags, importance, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (role, content, tags, float(importance), now_iso()),
            )
            return cursor.lastrowid

    def set_fact(self, key, value):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now_iso()),
            )

    def get_fact(self, key, default=None):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def record_command(self, command, result="", status="ok"):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO command_log (command, result, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (command, result, status, now_iso()),
            )

    def record_tool_event(self, capability, action, payload="{}", allowed=False, reason=""):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_events (capability, action, payload, allowed, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (capability, action, payload, int(bool(allowed)), reason, now_iso()),
            )

    def record_trade(self, mode, symbol, side, payload="{}", sent=False):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_log (mode, symbol, side, payload, sent, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mode, symbol, side, payload, int(bool(sent)), now_iso()),
            )

    def recent(self, limit=8):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tags, importance, created_at
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "role": row[0],
                "content": row[1],
                "tags": row[2],
                "importance": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def search(self, query, limit=6):
        q_tokens = Counter(tokenize(query))
        if not q_tokens:
            return self.recent(limit)

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, tags, importance, created_at
                FROM memories
                ORDER BY id DESC
                LIMIT 500
                """
            ).fetchall()

        scored = []
        q_norm = math.sqrt(sum(value * value for value in q_tokens.values())) or 1.0
        for row in rows:
            tokens = Counter(tokenize(row[2] + " " + row[3]))
            if not tokens:
                continue
            dot = sum(q_tokens[token] * tokens.get(token, 0) for token in q_tokens)
            if dot <= 0:
                continue
            t_norm = math.sqrt(sum(value * value for value in tokens.values())) or 1.0
            score = (dot / (q_norm * t_norm)) * float(row[4])
            scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "tags": row[3],
                "importance": row[4],
                "created_at": row[5],
                "score": score,
            }
            for score, row in scored[:limit]
        ]

    def stats(self):
        with self.connect() as conn:
            memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            commands = conn.execute("SELECT COUNT(*) FROM command_log").fetchone()[0]
            tool_events = conn.execute("SELECT COUNT(*) FROM tool_events").fetchone()[0]
            trades = conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0]
        return {
            "path": str(self.path),
            "memories": int(memories),
            "facts": int(facts),
            "commands": int(commands),
            "tool_events": int(tool_events),
            "trades": int(trades),
        }
