"""agents/trade_journal.py — JSONL journal of every closed R-magic trade.

What we have currently:
  • HoF live_pnl aggregated per genome
  • session_pl_tracker (Asia/London/NY rollup)
  • night_summary.json (12h snapshot)
  • deployment_status.json (slot landscape)

What we DON'T have: per-trade record with full context the user can audit.
"genome X lost \$1.22 — what was the entry signal? How long did it hold?
Did it ever go profitable before losing? Was regime DEAD when entered?"

This agent runs every 2 min and:
  • Scans MT5 history for R-magic CLOSES since last sync
  • For each new close: looks up the OPEN deal, parses R-<gid>-<side>
  • Captures: genome_id, symbol, side, entry, exit, profit, swap,
    commission, exit_reason (from broker comment), hold_minutes
  • Appends a JSON line to data/r_native/trade_journal.jsonl

Each line is one trade. User can:
  • grep journal for specific genome ID to see all its trades
  • compute custom stats (avg loss, hold time per outcome, …)
  • feed it to spreadsheet/LLM for analysis

State persisted via last_synced_ts — agent only processes NEW closes
each tick. Survives brain restarts cleanly.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


JOURNAL_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\trade_journal.jsonl")
STATE_PATH   = Path(r"C:\Users\Radhi\MT5\data\r_native\trade_journal_state.json")
R_MAGIC      = 20260605


class TradeJournal(Agent):
    name = "trade_journal"
    description = "Per-trade JSONL log with full attribution + exit context"
    interval_seconds = 120        # every 2 min
    default_enabled = True

    LOOKBACK_HOURS_ON_FIRST_RUN = 24

    def _load_state(self) -> dict:
        if not STATE_PATH.exists(): return {}
        try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception: return {}

    def _save_state(self, state: dict):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    def _parse_exit_reason(self, comment: str) -> str:
        """Broker overwrites comment on SL/TP with '[sl X]' / '[tp Y]'.
        Agent-driven closes use specific tags like 'aging_zombie_cut',
        'night_bleeder_cut'. Else 'manual_close' or 'unknown'."""
        if not comment: return "unknown"
        c = comment.lower()
        if "[sl" in c:        return "SL"
        if "[tp" in c:        return "TP"
        if "aging" in c:      return "aging_cut"
        if "night" in c or "bleeder" in c: return "night_cut"
        if "manual" in c:     return "manual"
        return c[:30]

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init err: {e}")
            return

        state = self._load_state()
        last_synced_ts = state.get("last_synced_ts")
        if last_synced_ts:
            since = datetime.fromtimestamp(last_synced_ts)
        else:
            # First run — go back 24h to capture recent history
            since = datetime.now() - timedelta(hours=self.LOOKBACK_HOURS_ON_FIRST_RUN)

        try:
            deals = mt5.history_deals_get(since, datetime.now()) or []
        except Exception as e:
            emit_insight(self.name, "WARN", f"history_deals_get err: {e}")
            return

        r_deals = [d for d in deals if int(getattr(d, "magic", 0)) == R_MAGIC]

        # Build ticket → (opener_gid, opener_side, opener_price, opener_ts)
        opens_by_ticket: dict[int, dict] = {}
        for d in r_deals:
            if int(d.entry) != 0: continue  # opens only
            ticket = int(getattr(d, "position_id", None) or d.order)
            m = re.match(r"R-([A-F0-9]{6})-(\w+)?", d.comment or "")
            opener_gid = m.group(1) if m else None
            opens_by_ticket[ticket] = {
                "gid":     opener_gid,
                "side":    "BUY" if int(d.type) == 0 else "SELL",
                "entry":   float(d.price),
                "ts_open": int(d.time),
                "lot":     float(d.volume),
                "comment_open": d.comment,
            }

        # Iterate CLOSES, write journal line for each, track max ts
        max_ts = last_synced_ts or 0
        written = 0
        for d in sorted([x for x in r_deals if int(x.entry) == 1],
                         key=lambda x: int(x.time)):
            ts_close = int(d.time)
            if last_synced_ts and ts_close <= last_synced_ts: continue
            max_ts = max(max_ts, ts_close)

            ticket = int(getattr(d, "position_id", None) or d.order)
            opener = opens_by_ticket.get(ticket) or {}
            profit = float(d.profit)
            swap   = float(d.swap)
            comm   = float(d.commission)
            net    = profit + swap + comm
            hold_min = None
            if opener.get("ts_open"):
                hold_min = round((ts_close - opener["ts_open"]) / 60, 1)

            rec = {
                "ts_close": datetime.fromtimestamp(ts_close, tz=timezone.utc).isoformat(),
                "ts_open":  (datetime.fromtimestamp(opener["ts_open"], tz=timezone.utc)
                              .isoformat() if opener.get("ts_open") else None),
                "ticket":   ticket,
                "symbol":   d.symbol,
                "genome":   opener.get("gid"),
                "side":     opener.get("side"),
                "lot":      opener.get("lot"),
                "entry":    opener.get("entry"),
                "exit":     float(d.price),
                "profit":   round(profit, 2),
                "swap":     round(swap, 2),
                "comm":     round(comm, 2),
                "net_pl":   round(net, 2),
                "hold_min": hold_min,
                "exit_reason":  self._parse_exit_reason(d.comment),
                "win":      net > 0,
            }

            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

        if written:
            # Quick stats over this batch
            new_lines = []
            try:
                # Read just this batch's lines (last `written` lines)
                with JOURNAL_PATH.open("r", encoding="utf-8") as f:
                    all_lines = f.readlines()
                for line in all_lines[-written:]:
                    line = line.strip()
                    if not line: continue
                    new_lines.append(json.loads(line))
            except Exception: pass

            wins   = sum(1 for r in new_lines if r.get("win"))
            net    = sum(r.get("net_pl", 0) for r in new_lines)
            emit_insight(self.name, "INFO",
                f"📓 logged {written} new trades · {wins} wins / "
                f"{written-wins} losses · net ${net:+.2f}",
                data={"written": written, "wins": wins, "net": round(net, 2)})

        # Save sync state
        if max_ts > (last_synced_ts or 0):
            state["last_synced_ts"]  = max_ts
            state["last_synced_iso"] = datetime.fromtimestamp(
                max_ts, tz=timezone.utc).isoformat()
            self._save_state(state)
