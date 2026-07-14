"""agents/live_journal.py
Every closed trade gets a human-readable story.

Watches journal.jsonl for new CLOSE events. For each one:
  1. Finds the matching PROPOSAL + OPEN events (same position id).
  2. Writes a narrative: why proposed, how council voted, outcome, lesson.
  3. Appends to data/stories.jsonl (separate from raw log).

Stateless cursor in data/journal_cursor.json — idempotent, restart-safe.

Usage:
    python -m r_native_v2.agents.live_journal          # run once
    python -m r_native_v2.agents.live_journal --loop   # poll every 30 s
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

DATA     = Path(os.path.join('C:', os.sep, 'Users', 'Radhi', 'MT5', 'r_native_v2', 'data'))
JOURNAL  = DATA / 'journal.jsonl'
STORIES  = DATA / 'stories.jsonl'
CURSOR_F = DATA / 'journal_cursor.json'
DATA.mkdir(parents=True, exist_ok=True)


# ─── cursor helpers ────────────────────────────────────────────────────────

def _load_cursor() -> int:
    if not CURSOR_F.exists(): return 0
    try:
        return int(json.loads(CURSOR_F.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        return 0

def _save_cursor(offset: int) -> None:
    CURSOR_F.write_text(json.dumps({"offset": offset}), encoding="utf-8")


# ─── I/O ───────────────────────────────────────────────────────────────────

def _append_story(entry: dict) -> None:
    with STORIES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

def _read_journal_events() -> list:
    if not JOURNAL.exists(): return []
    out = []
    with JOURNAL.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line.strip()))
            except Exception:
                pass
    return out


# ─── index ─────────────────────────────────────────────────────────────────

def _build_index(events: list) -> dict:
    """Build {trade_id -> {proposal, open, close}} from all journal events."""
    idx = {}
    for e in events:
        tid = e.get("id")
        if not tid: continue
        if tid not in idx: idx[tid] = {}
        kind = e.get("kind", "")
        if kind == "PROPOSAL": idx[tid]["proposal"] = e
        elif kind == "OPEN":   idx[tid]["open"]     = e
        elif kind == "CLOSE":  idx[tid]["close"]    = e
    return idx


# ─── narrative helpers ──────────────────────────────────────────────────────

def _tag(reason: str, pnl) -> str:
    if reason == "TP": return "WIN"
    if reason == "SL": return "LOSS"
    return "EXIT"

def _council_narrative(summary: str) -> str:
    if not summary: return "council summary unavailable"
    approved = "APPROVED" in summary
    votes = []
    for token in summary.split():
        if "=" in token:
            name, rest = token.split("=", 1)
            tick = "OK" if ("✓" in rest or "True" in rest) else "VETO"
            votes.append(f"{name}:{tick}")
    verdict = "APPROVED" if approved else "BLOCKED"
    return verdict + "  |  " + "   ".join(votes)

def _write_story(trade: dict) -> None:
    close    = trade.get("close", {})
    proposal = trade.get("proposal", {})
    open_e   = trade.get("open", {})

    tid     = close.get("id", "?")
    genome  = close.get("genome",  proposal.get("genome", "?"))
    symbol  = close.get("symbol",  "?")
    side    = close.get("side",    "?")
    entry   = close.get("entry",   open_e.get("entry", 0))
    close_p = close.get("close_price", 0)
    pnl     = close.get("pnl",    0)
    reason  = close.get("close_reason", "?")
    held    = close.get("held_min", "?")
    ts_c    = close.get("ts", "")

    thesis     = proposal.get("thesis",     open_e.get("thesis", "no thesis recorded"))
    council    = proposal.get("council",    "")
    confluence = proposal.get("confluence", [])
    dissent    = proposal.get("dissent",    [])

    pnl_str    = f"${pnl:+.2f}" if isinstance(pnl, (int, float)) else str(pnl)
    tag        = _tag(reason, pnl)
    conf_lines = "\n".join(f"  - {c}" for c in confluence) or "  (not recorded)"
    diss_lines = "\n".join(f"  VETO {n}: {r}" for n, r in dissent) or "  (none - unanimous)"

    if reason == "TP" and isinstance(pnl, (int, float)) and pnl > 0:
        lesson = "TP hit. Thesis matched outcome. FVG retest + pressure combo validated."
    elif reason == "SL" and isinstance(pnl, (int, float)) and pnl < 0:
        lesson = ("SL hit. Review: did FVG hold? Was marubozu-bear filter strong enough? "
                  "Check if regime shifted after council approval.")
    else:
        lesson = "Manual review recommended."

    narrative = (
        f"TRADE {tid}\n"
        f"  Genome : {genome}\n"
        f"  Thesis : {thesis}\n"
        f"  Entry  : {entry}   Close: {close_p}   PnL: {pnl_str}\n"
        f"  Reason : {reason}  Held: {held}min  Closed: {ts_c}\n\n"
        f"COUNCIL:\n  {_council_narrative(council)}\n\n"
        f"DISSENT:\n{diss_lines}\n\n"
        f"CONFLUENCE AT ENTRY:\n{conf_lines}\n\n"
        f"LESSON:\n  {lesson}"
    )
    story = {
        "kind":      "STORY",
        "ts":        datetime.now(timezone.utc).isoformat(),
        "id":        tid,
        "genome":    genome,
        "symbol":    symbol,
        "headline":  f"[{tag}] {genome} {side} {symbol} -> {pnl_str} ({reason})",
        "narrative": narrative,
        "pnl":       pnl,
        "reason":    reason,
    }
    _append_story(story)
    print(f"[live_journal] [{tag}] {tid}  {pnl_str} ({reason})")


# ─── public API ────────────────────────────────────────────────────────────

class LiveJournal:
    """Stateful journal agent. Call .run_once() to process new closes."""

    def run_once(self) -> int:
        """Process new CLOSE events since last cursor. Returns # stories written."""
        events     = _read_journal_events()
        cursor     = _load_cursor()
        new_events = events[cursor:]
        idx        = _build_index(events)          # full index for context

        written = 0; new_cursor = cursor
        for i, e in enumerate(new_events, start=cursor):
            if e.get("kind") == "CLOSE":
                tid = e.get("id")
                if tid and tid in idx and "close" in idx[tid]:
                    _write_story(idx[tid])
                    written += 1
            new_cursor = i + 1
        _save_cursor(new_cursor)
        return written

    def run_loop(self, poll_sec: int = 30) -> None:
        print(f"[live_journal] running  poll={poll_sec}s")
        while True:
            try:
                n = self.run_once()
                if n: print(f"[live_journal] wrote {n} new stories")
            except KeyboardInterrupt:
                print("[live_journal] stopped"); break
            except Exception as e:
                print(f"[live_journal] err: {e}")
            time.sleep(poll_sec)


if __name__ == "__main__":
    agent = LiveJournal()
    if "--loop" in sys.argv:
        agent.run_loop()
    else:
        n = agent.run_once()
        print(f"[live_journal] done  {n} stories written")
