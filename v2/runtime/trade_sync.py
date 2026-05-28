"""runtime/trade_sync.py — Keep trading.db.trades in sync with live MT5.

Born 2026-05-28 to close the learning loop:
  "هل لو دخلت صفقات بشكل يدوي يتعلم بعد؟"  →  نعم، عبر هذا.

Every 60s:
  1. Pull MT5 closed deals (entry=1/2) since a lookback window
  2. Upsert into trading.db.trades by ticket (no duplicates)
  3. Includes MANUAL trades (magic 0) — so genome_birth learns from
     the user's newest hand-trades on every rebirth.

This is the bridge that makes "the child keeps learning from you" TRUE:
  your manual trade closes → trade_sync → trades table → genome_birth
  → next CHILD genome inherits your latest winning patterns.

Run:
    python -m runtime.trade_sync
"""
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

from runtime.shared.db import db
from runtime.shared.tokens import NAMES

POLL_S = 60.0
LOOKBACK_HOURS = 24


def _existing_tickets() -> set[int]:
    rows = db.query("SELECT DISTINCT ticket FROM trades WHERE ticket > 0")
    return {int(r["ticket"]) for r in rows}


def cycle() -> int:
    """Upsert recent closed deals into trades. Returns rows added."""
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    exits = [d for d in deals if int(d.entry) in (1, 2)]
    if not exits:
        return 0

    existing = _existing_tickets()
    added = 0
    with db.transaction():
        for d in exits:
            tk = int(d.ticket)
            if tk in existing:
                continue
            magic = int(d.magic)
            db.insert("trades", {
                "ts":        datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                "magic":     magic,
                "source":    NAMES.get(magic, str(magic)),
                "symbol":    d.symbol or "?",
                "side":      "BUY" if d.type == 0 else "SELL",
                "lot":       float(d.volume),
                "entry":     0,
                "exit_price": float(d.price),
                "sl":        0, "tp": 0,
                "ticket":    tk,
                "pnl":       float(d.profit),
                "duration_sec": None,
                "reason":    f"trade_sync entry={d.entry}",
                "confidence": 0.5,
                "regime_at_fire": None,
                "session_at_fire": None,
                "raw_json":  None,
            })
            added += 1
    return added


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("[trade_sync] mt5 init failed"); return
    print(f"[trade_sync] ONLINE — syncing MT5 history → trading.db every {POLL_S}s")
    print(f"[trade_sync] manual trades (magic 0) now feed genome_birth")
    while True:
        try:
            n = cycle()
            if n:
                print(f"[{datetime.now():%H:%M:%S}] synced {n} new closed trade(s) → db")
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("[trade_sync] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(POLL_S)


if __name__ == "__main__":
    main()
