"""runtime/decision_outcome_filler.py — Backfill PnL on closed decisions.

Born 2026-05-28. Companion to decision_log.py.
Rebuilt 2026-07-13 after the learning-link audit found entry_decisions
frozen since Jun 2 (228k rows, 51 with pnl).

WHY IT BROKE (root cause, for posterity):
  1. The service died at boot on a transient WAL 'disk I/O error'
     (fleet-relaunch race; db.py has since grown a retry) and the old
     6-hour MT5 lookback could never reach historical deals anyway.
  2. 99.96% of entry_decisions rows are unified_trader INTENTS with
     ticket=0 — nothing to join on. Only 95 rows ever had tickets, and
     those tickets belong to a previous (retired) demo account, so
     mt5.history_deals_get can never see them again.
  3. Meanwhile the `trades` table in the SAME db is fresh (friday_db
     record-loop) — it was never being joined.

WHAT IT DOES NOW (read/backfill only — NOT an order path):
  Boot:
    a. UPDATE entry_decisions rows that have a ticket, joining trades
       on ticket → fills pnl / exit_price / duration (idempotent:
       only rows WHERE pnl IS NULL).
    b. INSERT decision rows for executed bot trades that have pnl but
       no entry_decisions row (exit_reason='trades_backfill' marker,
       executed=1). Manual trades and external user EAs are excluded —
       genome fitness must learn from OUR engines only.
    c. Mark old unfillable rows (intent spam / dead-account tickets)
       via the existing exit_reason column; pnl stays NULL so
       champion_evolution's `WHERE pnl IS NOT NULL` never sees them.
  Steady state (every 30s):
    - incremental (a)+(b) for new trades rows
    - live MT5 history_deals_get pass for any writer that records
      tickets in real time (optional — survives MT5 being down)

Run:  python -m runtime.decision_outcome_filler
"""
from __future__ import annotations
import time
import sqlite3
from datetime import datetime, timezone, timedelta

try:
    import MetaTrader5 as mt5
except Exception:                                   # MT5 optional — trades-table sync is primary
    mt5 = None

from runtime.shared.db import db
from runtime.shared.decision_log import update_decision_outcome

POLL_S = 30.0
LOOKBACK_HOURS = 6           # MT5 live pass window
STALE_HOURS = 48             # intents older than this are marked unfillable
MARK_EVERY_S = 3600          # re-run the unfillable marker hourly
PROGRESS_EVERY = 1000

# Trades that must NOT feed genome learning:
#   manual = the user's own trading; magics = external user EAs (see magic inventory memo).
SKIP_SOURCES = ("manual",)
EXTERNAL_MAGICS = (0, 2447, 20250418, 20250421, 20250422, 20250618)

_mt5_ok = False


def _retry(fn, attempts: int = 3):
    """Run fn(); retry transient sqlite errors (locked / disk I/O) with backoff."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            last = e
            time.sleep(0.5 * (2 ** i))
    raise last


def _ensure_ticket_index() -> None:
    """Partial unique index on ticket — makes INSERT OR IGNORE race-safe
    if two filler processes ever overlap. (95 existing tickets verified unique.)"""
    _retry(lambda: db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_dec_ticket "
        "ON entry_decisions(ticket) WHERE ticket > 0"))


# ──────────────────────────────────────────────────────────
# (a) Fill existing decision rows from the trades table
# ──────────────────────────────────────────────────────────
def fill_decisions_from_trades() -> int:
    rows = _retry(lambda: db.query("""
        SELECT e.id AS eid, t.pnl, t.exit_price, t.duration_sec,
               t.reason AS t_reason, t.ts AS t_ts
        FROM entry_decisions e
        JOIN trades t ON t.ticket = e.ticket
        WHERE e.ticket > 0 AND e.pnl IS NULL AND t.pnl IS NOT NULL
    """))
    n = 0
    for r in rows:
        _retry(lambda r=r: db.execute(
            """UPDATE entry_decisions
               SET pnl=?, exit_price=?, duration_sec=?, exit_reason=?, closed_ts=?
               WHERE id=? AND pnl IS NULL""",
            (float(r["pnl"]), r["exit_price"], r["duration_sec"],
             r["t_reason"] or "trades_join", r["t_ts"], r["eid"])))
        n += 1
        if n % PROGRESS_EVERY == 0:
            print(f"  [fill] updated {n}/{len(rows)} decision rows from trades", flush=True)
    return n


# ──────────────────────────────────────────────────────────
# (b) Insert executed bot trades that never got a decision row
# ──────────────────────────────────────────────────────────
_last_trade_id = 0


def import_missing_trades(full: bool = False) -> int:
    """Insert entry_decisions rows for executed bot trades with pnl that
    have no decision row. Idempotent: NOT EXISTS + unique index (OR IGNORE)."""
    global _last_trade_id
    since_id = 0 if full else _last_trade_id
    src_ph = ",".join("?" for _ in SKIP_SOURCES)
    mag_ph = ",".join("?" for _ in EXTERNAL_MAGICS)
    rows = _retry(lambda: db.query(f"""
        SELECT t.id, t.ts, t.magic, t.source, t.symbol, t.side, t.lot,
               t.entry, t.exit_price, t.sl, t.tp, t.ticket, t.pnl,
               t.duration_sec, t.reason, t.confidence,
               t.regime_at_fire, t.session_at_fire
        FROM trades t
        WHERE t.id > ? AND t.pnl IS NOT NULL
          AND t.ticket IS NOT NULL AND t.ticket > 0
          AND COALESCE(t.source,'') NOT IN ({src_ph})
          AND t.magic NOT IN ({mag_ph})
          AND NOT EXISTS (SELECT 1 FROM entry_decisions e WHERE e.ticket = t.ticket)
        ORDER BY t.id
    """, (since_id, *SKIP_SOURCES, *EXTERNAL_MAGICS)))
    n = 0
    for t in rows:
        _retry(lambda t=t: db.execute(
            """INSERT OR IGNORE INTO entry_decisions
               (ts, source, magic, symbol, side, entry, sl, tp, lot,
                reason, confidence, regime, session,
                ticket, executed, pnl, exit_price, exit_reason,
                duration_sec, closed_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
            (t["ts"], t["source"] or str(t["magic"]), t["magic"], t["symbol"],
             t["side"], t["entry"], t["sl"], t["tp"], t["lot"],
             t["reason"] or "", t["confidence"],
             t["regime_at_fire"], t["session_at_fire"],
             t["ticket"], float(t["pnl"]), t["exit_price"],
             "trades_backfill", t["duration_sec"], t["ts"])))
        _last_trade_id = max(_last_trade_id, int(t["id"]))
        n += 1
        if n % PROGRESS_EVERY == 0:
            print(f"  [import] inserted {n}/{len(rows)} executed trades into entry_decisions", flush=True)
    if full and rows:
        _last_trade_id = max(_last_trade_id, int(rows[-1]["id"]))
    return n


# ──────────────────────────────────────────────────────────
# (c) Mark unfillable rows (pnl stays NULL — flag via exit_reason)
# ──────────────────────────────────────────────────────────
def mark_unfillable() -> tuple[int, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)).isoformat()
    cur1 = _retry(lambda: db.execute(
        """UPDATE entry_decisions SET exit_reason='UNFILLABLE_INTENT'
           WHERE pnl IS NULL AND COALESCE(ticket,0)=0
             AND exit_reason IS NULL AND ts < ?""", (cutoff,)))
    cur2 = _retry(lambda: db.execute(
        """UPDATE entry_decisions SET exit_reason='UNFILLABLE_STALE_TICKET'
           WHERE pnl IS NULL AND ticket > 0
             AND exit_reason IS NULL AND ts < ?
             AND NOT EXISTS (SELECT 1 FROM trades t
                             WHERE t.ticket = entry_decisions.ticket
                               AND t.pnl IS NOT NULL)""", (cutoff,)))
    return cur1.rowcount, cur2.rowcount


# ──────────────────────────────────────────────────────────
# Live MT5 pass (original behavior, now optional)
# ──────────────────────────────────────────────────────────
def cycle_mt5() -> int:
    """Fill decisions whose tickets closed on the CURRENT account recently."""
    if not _mt5_ok:
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    exits_by_ticket: dict[int, list] = {}
    for d in deals:
        if int(d.entry) not in (1, 2):
            continue
        pos_id = int(d.position_id) if hasattr(d, "position_id") else int(d.order)
        exits_by_ticket.setdefault(pos_id, []).append(d)

    updated = 0
    for pos_id, deals_list in exits_by_ticket.items():
        total_pnl = sum(float(d.profit) for d in deals_list)
        last_exit = max(deals_list, key=lambda d: d.time)
        rows = _retry(lambda: db.query(
            "SELECT id, ts FROM entry_decisions WHERE ticket=? AND pnl IS NULL",
            (pos_id,)))
        if not rows:
            continue
        rec = rows[0]
        try:
            t_open = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
            t_close = datetime.fromtimestamp(last_exit.time, tz=timezone.utc)
            dur = int((t_close - t_open).total_seconds())
        except Exception:
            dur = 0
        update_decision_outcome(
            ticket=pos_id, pnl=total_pnl, exit_price=float(last_exit.price),
            exit_reason=last_exit.comment or "", duration_sec=dur,
        )
        updated += 1
    return updated


def _counts() -> tuple[int, int]:
    r = db.query("SELECT COUNT(*) AS total, "
                 "SUM(CASE WHEN pnl IS NOT NULL THEN 1 ELSE 0 END) AS filled "
                 "FROM entry_decisions")[0]
    return int(r["total"]), int(r["filled"] or 0)


def main():
    global _mt5_ok
    print(f"[outcome_filler] ONLINE — polling every {POLL_S}s", flush=True)
    if mt5 is not None:
        try:
            _mt5_ok = bool(mt5.initialize() or mt5.initialize())
        except Exception:
            _mt5_ok = False
    print(f"[outcome_filler] mt5={'OK' if _mt5_ok else 'UNAVAILABLE (trades-table sync only)'}", flush=True)

    _ensure_ticket_index()

    # ── one-shot historical backfill ──
    t0, f0 = _counts()
    print(f"[outcome_filler] BEFORE: {f0}/{t0} rows have pnl", flush=True)
    nu = fill_decisions_from_trades()
    ni = import_missing_trades(full=True)
    mi, ms = mark_unfillable()
    t1, f1 = _counts()
    print(f"[outcome_filler] backfill: +{nu} filled by ticket-join, "
          f"+{ni} imported from trades, {mi} intents + {ms} stale-ticket rows marked unfillable", flush=True)
    print(f"[outcome_filler] AFTER: {f1}/{t1} rows have pnl", flush=True)

    # ── steady-state incremental loop ──
    last_mark = time.time()
    while True:
        try:
            n = fill_decisions_from_trades() + import_missing_trades() + cycle_mt5()
            if n:
                print(f"[{datetime.now():%H:%M:%S}] backfilled {n} decision outcome(s)", flush=True)
            if time.time() - last_mark > MARK_EVERY_S:
                mi, ms = mark_unfillable()
                if mi or ms:
                    print(f"[{datetime.now():%H:%M:%S}] marked {mi + ms} unfillable row(s)", flush=True)
                last_mark = time.time()
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            if _mt5_ok:
                mt5.shutdown()
            print("[outcome_filler] stopped", flush=True)
            break
        except Exception as e:
            print(f"err: {e}", flush=True)
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
