"""runtime/decision_outcome_filler.py — Backfill PnL on closed decisions.

Born 2026-05-28. Companion to decision_log.py.

Every 30s:
  1. Pull recent MT5 deals (exits, entry=1 or 2)
  2. For each, find the matching open decision (by ticket)
  3. Update the decision row with pnl, exit_price, duration

This is what makes the unified log USEFUL — without it, every decision
sits in the DB without an outcome. With it, you can query "winning SELLs"
and actually get answers.

Run in its own terminal:
    python -m runtime.decision_outcome_filler
"""
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

from runtime.shared.db import db
from runtime.shared.decision_log import update_decision_outcome

POLL_S = 30.0
LOOKBACK_HOURS = 6


def cycle() -> int:
    """One backfill pass. Returns number of rows updated."""
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    # Group exits by ticket — last exit per position has the pnl
    exits_by_ticket: dict[int, list] = {}
    for d in deals:
        if int(d.entry) not in (1, 2): continue
        # The "position" id is what links to original entry's ticket
        pos_id = int(d.position_id) if hasattr(d, "position_id") else int(d.order)
        exits_by_ticket.setdefault(pos_id, []).append(d)

    updated = 0
    for pos_id, deals_list in exits_by_ticket.items():
        # Sum pnl across partial closes (usually just one)
        total_pnl = sum(float(d.profit) for d in deals_list)
        last_exit = max(deals_list, key=lambda d: d.time)
        exit_price = float(last_exit.price)
        exit_reason = last_exit.comment or ""
        # Find decision by ticket — only update if not already filled
        rows = db.query(
            "SELECT id, ts, ticket FROM entry_decisions WHERE ticket=? AND pnl IS NULL",
            (pos_id,),
        )
        if not rows: continue
        rec = rows[0]
        try:
            t_open = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
            t_close = datetime.fromtimestamp(last_exit.time, tz=timezone.utc)
            dur = int((t_close - t_open).total_seconds())
        except Exception:
            dur = 0
        update_decision_outcome(
            ticket=pos_id, pnl=total_pnl, exit_price=exit_price,
            exit_reason=exit_reason, duration_sec=dur,
        )
        updated += 1
    return updated


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("[outcome_filler] mt5 init failed"); return
    print(f"[outcome_filler] ONLINE — polling every {POLL_S}s")
    while True:
        try:
            n = cycle()
            if n: print(f"[{datetime.now():%H:%M:%S}] backfilled {n} decision outcome(s)")
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("[outcome_filler] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(POLL_S)


if __name__ == "__main__":
    main()
