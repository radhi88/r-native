"""Live read-only console dashboard for the desk.

Prints the account snapshot, open desk positions (magic-filtered), and the
latest exam score per symbol. Pure read-only — it never sends orders. Refreshes
on an interval; Ctrl-C to exit.
"""
from __future__ import annotations

import glob
import os
import sqlite3
import time
from datetime import datetime, timezone

import config
from agents import broker

_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "markets")


def _positions() -> list[str]:
    """Return formatted lines for open desk positions."""
    try:
        import MetaTrader5 as mt5
        pos = [p for p in (mt5.positions_get() or []) if p.magic == config.EXEC_MAGIC]
    except Exception:
        return ["  (MT5 unavailable)"]
    if not pos:
        return ["  (no open desk positions)"]
    out = []
    for p in pos:
        side = "BUY" if p.type == 0 else "SELL"
        out.append(f"  {p.symbol:9} {side:4} {p.volume} @ {p.price_open} "
                   f"SL={p.sl} TP={p.tp} pnl={p.profit:+.2f}")
    return out


def _exams() -> list[str]:
    """Return latest exam line per symbol across market DBs."""
    out = []
    for dbf in sorted(glob.glob(os.path.join(_DB_DIR, "*.db"))):
        conn = sqlite3.connect(dbf)
        try:
            cur = conn.execute(
                "SELECT symbol, score, profit_factor, notes FROM exam_log "
                "WHERE rowid IN (SELECT MAX(rowid) FROM exam_log GROUP BY symbol)")
            for s, sc, pf, nt in cur.fetchall():
                gate = "PASS" if (sc >= config.EXAM_PASS_SCORE
                                  and pf >= config.PF_TARGET) else "----"
                out.append(f"  {s:9} score={sc:5.1f} pf={pf:.2f} [{gate}] {nt or ''}")
        except sqlite3.OperationalError:
            pass
        conn.close()
    return out or ["  (no exams yet)"]


def render_once() -> None:
    """Render one dashboard frame to stdout."""
    broker.connect()
    acct = broker.account()
    print("=" * 72)
    print(f" AI GEOMETRIC AGENTIC DESK — {datetime.now(timezone.utc):%H:%M:%S UTC}")
    print("=" * 72)
    if acct:
        print(f" Account {acct.login} @ {acct.server} "
              f"[{'DEMO' if acct.is_demo else 'REAL'}]  "
              f"equity={acct.equity:.2f}  free={acct.free_margin:.2f}")
    print(f" LIVE_TRADING={config.LIVE_TRADING}  DEMO_ONLY={config.DEMO_ONLY}  "
          f"REQUIRE_EXAM_PASS={config.REQUIRE_EXAM_PASS}")
    print("\n Open desk positions (magic %d):" % config.EXEC_MAGIC)
    print("\n".join(_positions()))
    print("\n Latest exam scores:")
    print("\n".join(_exams()))
    print("=" * 72)


def loop(interval: float = 15.0) -> None:
    """Continuously refresh the dashboard."""
    while True:
        render_once()
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        render_once()
    else:
        loop()
