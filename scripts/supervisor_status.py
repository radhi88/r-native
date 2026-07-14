import json
import sqlite3

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import JOURNAL_DIR


DB_PATH = JOURNAL_DIR / "jarvis_memory.sqlite3"


def fetch_all(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def main():
    conn = sqlite3.connect(DB_PATH)
    payload = {
        "heartbeat": fetch_all(
            conn,
            "SELECT * FROM autonomous_heartbeat ORDER BY updated_at DESC LIMIT 5",
        ),
        "strategy_state": fetch_all(
            conn,
            "SELECT * FROM autonomous_strategy_state ORDER BY confidence DESC",
        ),
        "symbol_profile_state": fetch_all(
            conn,
            """
            SELECT symbol, profile, confidence, observations, wins, losses, net_points, updated_at
            FROM autonomous_symbol_profile_state
            ORDER BY confidence DESC, net_points DESC
            LIMIT 25
            """,
        ),
        "research_summary": fetch_all(
            conn,
            """
            SELECT symbol, profile, COUNT(*) AS observations,
                   SUM(CASE WHEN points > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(points) AS net_points
            FROM autonomous_research_outcomes
            GROUP BY symbol, profile
            ORDER BY net_points DESC
            LIMIT 25
            """,
        ),
        "open_positions": fetch_all(
            conn,
            "SELECT * FROM autonomous_positions WHERE status = 'open' ORDER BY opened_at DESC",
        ),
        "agent_adjustments": fetch_all(
            conn,
            """
            SELECT profile, symbol, side, points, close_reason, thresholds_json, updated_at
            FROM autonomous_agent_adjustments
            ORDER BY id DESC
            LIMIT 10
            """,
        ),
        "closed_summary": fetch_all(
            conn,
            """
            SELECT profile, COUNT(*) AS trades,
                   SUM(CASE WHEN points > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(points) AS net_points
            FROM autonomous_positions
            WHERE status = 'closed'
            GROUP BY profile
            ORDER BY net_points DESC
            """,
        ),
        "recent_decisions": fetch_all(
            conn,
            """
            SELECT symbol, profile, action, probability, confidence, context_score, reason, trusted, created_at
            FROM autonomous_decisions
            ORDER BY id DESC
            LIMIT 20
            """,
        ),
    }
    conn.close()
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
