"""
friday_ea_evolver.py — Autonomous EA evolution daemon.

Every CYCLE_MINUTES the daemon:
  1. Inspects current system state (brain, fractals, footprint, orders log, EA status)
  2. Picks the most impactful improvement to FRIDAY_Brain_Executor.mq5
  3. Backs up the current EA to ea_backups/<ts>.mq5
  4. Dispatches a CODER task to make the change
  5. Waits for the task to finish
  6. Auto-compiles via metaeditor64.exe
  7. If compile fails → rollback from backup
  8. Logs everything to ea_evolution.csv

The user does NOT need to attach the EA manually each cycle — MT5 auto-reloads
the .ex5 next time the chart is interacted with, OR the user can keep it on chart
permanently (the .ex5 hot-swaps when MetaEditor compiles).

Run:    python friday_ea_evolver.py
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT          = Path(r"C:\Users\Radhi\MT5")
EA_PATH       = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5\Experts\FRIDAY_Brain_Executor.mq5")
BACKUP_DIR    = ROOT / "ea_backups"
EVOLVE_LOG    = ROOT / "ea_evolution.csv"
EVOLVE_STATE  = ROOT / "ea_evolver_state.json"
QUEUE_FILE    = ROOT / "friday_tasks.json"
TEAM_OUTPUT   = ROOT / "friday_agent_team_output"

CYCLE_MINUTES   = 20         # one evolution attempt every N minutes
TASK_WAIT_S     = 600        # max wait for CODER to finish
ROLLBACK_ON_FAIL = True

# Improvement themes — rotate through these. Each gets a CODER task.
THEMES = [
    {
        "id": "add_ema_alignment",
        "intent": "Add EMA(50)/EMA(200) trend alignment check before allowing orders",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add an internal trend filter:
- Add input `InpUseEMATrendFilter` (default true).
- In OnInit, add two iMA handles: ema50 (period 50) and ema200 (period 200) on current TF.
- Before PlaceBrainOrder allows a BUY: require Close[0] > EMA50 > EMA200 OR InpUseEMATrendFilter=false.
- Before allowing a SELL: require Close[0] < EMA50 < EMA200.
- If filter blocks, set g_last_reason = "EMA trend filter blocked" and return false from PlaceBrainOrder.
- Free handles in OnDeinit.
- Keep all existing safety checks intact. Don't modify the magic number or risk caps.""",
    },
    {
        "id": "add_atr_dynamic_sl",
        "intent": "Use ATR(14) for dynamic minimum SL distance",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add ATR-based SL validation:
- Add input `InpUseATRMinSL` (default true) and `InpATRMinSLMult` (default 1.5).
- Add iATR handle (period 14) in OnInit, release in OnDeinit.
- In PlaceBrainOrder: compute atr_pt = ATR * 100 (for gold). Require |entry - sl| >= atr_pt * InpATRMinSLMult.
- If too tight, set g_last_reason and reject.
- Keep all other logic intact.""",
    },
    {
        "id": "add_spread_history_filter",
        "intent": "Reject orders when current spread > 2x rolling-5min average",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add adaptive spread filter:
- Maintain a circular buffer of last 60 spread samples (one per OnTimer tick).
- Compute rolling average. If current spread > 2.0x rolling avg → reject with reason "spread spike vs 5min avg".
- Add input `InpUseSpreadSpikeFilter` (default true) and `InpSpreadSpikeMult` (default 2.0).""",
    },
    {
        "id": "add_session_filter",
        "intent": "Add trading-session filter — avoid Asian session low-volume periods",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add session filter:
- Add input `InpAvoidAsianSession` (default false — don't auto-enable).
- Asian session = 00:00-06:00 UTC. Detect via TimeGMT().
- When active and InpAvoidAsianSession=true, reject orders with reason "asian session filter".""",
    },
    {
        "id": "add_news_blackout_window",
        "intent": "Add manual news-blackout time window",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add news blackout:
- Add inputs `InpNewsBlackoutFile` (default "news_blackout.csv" in Common\\Files).
- File format: each line "HH:MM,minutes_after" (e.g., "12:30,30" = blackout 12:30 + 30 min).
- On each OnTimer, read file (cache for 60s). If now is within any blackout, reject orders.""",
    },
    {
        "id": "add_dashboard_extra_lines",
        "intent": "Add extra info to chart Comment dashboard",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Enhance the dashboard Comment:
- Add a line showing rolling win/loss count (last 24h, using HistoryDealGetTicket).
- Add a line showing current EMA50/EMA200 values (if those handles exist).
- Don't add new indicators if not present — gracefully omit.""",
    },
    {
        "id": "log_rejected_orders_csv",
        "intent": "Persist rejected order attempts to CSV for audit",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add rejection logging:
- When PlaceBrainOrder returns false, append a row to "ea_rejections.csv" in Common\\Files:
  timestamp, side, entry, sl, tp, lot, reason.
- Open in append mode (FILE_READ|FILE_WRITE|FILE_TXT|FILE_CSV|FILE_COMMON), seek to end, write, close.""",
    },
    {
        "id": "add_breakeven_after_partial",
        "intent": "Move SL to breakeven after partial TP hit",
        "prompt": """Open FRIDAY_Brain_Executor.mq5. Add partial-TP/BE logic:
- If a position is at 50% of (TP-Entry) distance from entry, move SL to entry + 5 points buffer (or entry - 5 for SELL).
- Implement in a new helper `ManageBreakeven()` called from OnTimer.
- Only act on positions with our magic.""",
    },
]


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[EA-EVOLVER {ts}] {msg}", flush=True)


def _csv_append(row: list[str]):
    new = not EVOLVE_LOG.exists()
    with open(EVOLVE_LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "theme_id", "task_id", "status", "compile_ok",
                        "compile_summary", "duration_s", "ea_size_before", "ea_size_after"])
        w.writerow(row)


def _save_state(theme: dict, task_id: str, status: str):
    state = {
        "ts":       datetime.now().isoformat(),
        "theme":    theme,
        "task_id":  task_id,
        "status":   status,
        "ea_path":  str(EA_PATH),
    }
    EVOLVE_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _backup_ea() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"FRIDAY_Brain_Executor_{datetime.now():%Y%m%d_%H%M%S}.mq5"
    shutil.copy2(EA_PATH, backup)
    return backup


def _rollback(backup: Path):
    shutil.copy2(backup, EA_PATH)
    _log(f"🔄 ROLLED BACK from {backup.name}")


def _enqueue(role: str, prompt: str, priority: int = 6) -> str:
    """Submit task to the agent team queue."""
    task_id = uuid.uuid4().hex[:8]
    if not QUEUE_FILE.exists():
        QUEUE_FILE.write_text('{"tasks": []}', encoding="utf-8")
    q = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    q["tasks"].append({
        "id":           task_id,
        "role":         role.upper(),
        "task":         prompt,
        "priority":     priority,
        "status":       "pending",
        "submitted_at": datetime.now().isoformat(),
        "started_at":   None,
        "finished_at":  None,
        "result":       None,
        "requested_by": "ea_evolver",
    })
    QUEUE_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    return task_id


def _wait_for_task(task_id: str, timeout_s: int) -> dict | None:
    """Poll the queue until the task is completed or failed."""
    start = time.time()
    while time.time() - start < timeout_s:
        time.sleep(8)
        try:
            q = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            for t in q["tasks"]:
                if t["id"] == task_id and t["status"] in ("completed", "failed"):
                    return t
        except Exception:
            pass
    return None


def _compile_ea() -> tuple[bool, str]:
    """Run metaeditor64.exe compile."""
    try:
        from friday_mql5_compile import compile_mq5
        return compile_mq5(str(EA_PATH))
    except Exception as e:
        return False, f"compile invoke failed: {e}"


# ─────────────────────────────────────────────────────────────────────────
# Theme selector
# ─────────────────────────────────────────────────────────────────────────

def pick_theme() -> dict:
    """Pick the next theme to apply. Avoid repeating recent themes."""
    recent_ids: set[str] = set()
    if EVOLVE_LOG.exists():
        try:
            with open(EVOLVE_LOG, encoding="utf-8") as f:
                rows = list(csv.reader(f))[1:]   # skip header
            # Last 5 themes attempted (regardless of success)
            recent_ids = {r[1] for r in rows[-5:]} if rows else set()
        except Exception:
            pass

    # Pick first theme not in recent
    for t in THEMES:
        if t["id"] not in recent_ids:
            return t
    # If all recently tried, pick oldest by cycling
    return THEMES[0]


# ─────────────────────────────────────────────────────────────────────────
# Main cycle
# ─────────────────────────────────────────────────────────────────────────

def run_cycle():
    _log("─" * 60)
    if not EA_PATH.exists():
        _log(f"✗ EA not found: {EA_PATH}")
        return

    theme = pick_theme()
    _log(f"🎯 theme: {theme['id']} — {theme['intent']}")

    # 1. Backup
    backup = _backup_ea()
    ea_size_before = EA_PATH.stat().st_size
    _log(f"💾 backed up to {backup.name} ({ea_size_before} bytes)")

    # 2. Submit CODER task
    full_prompt = (
        theme["prompt"]
        + "\n\nIMPORTANT: After editing, run `python C:\\Users\\Radhi\\MT5\\friday_mql5_compile.py "
          f"\"{EA_PATH}\"` to verify compilation. If it fails, restore from "
          f"`{backup}` and report the failure. Always preserve magic 20260600 and all safety checks."
    )
    task_id = _enqueue("CODER", full_prompt, priority=6)
    _log(f"📤 dispatched CODER task {task_id}")
    _save_state(theme, task_id, "running")

    started = time.time()
    result = _wait_for_task(task_id, TASK_WAIT_S)
    duration = round(time.time() - started, 1)

    if not result:
        _log(f"⏱ task {task_id} timed out after {TASK_WAIT_S}s")
        if ROLLBACK_ON_FAIL: _rollback(backup)
        _csv_append([datetime.now().isoformat(), theme["id"], task_id, "timeout",
                     False, "task timeout", duration, ea_size_before, EA_PATH.stat().st_size])
        _save_state(theme, task_id, "timeout")
        return

    if result["status"] == "failed":
        _log(f"✗ task failed: {(result.get('result') or '')[:120]}")
        if ROLLBACK_ON_FAIL: _rollback(backup)
        _csv_append([datetime.now().isoformat(), theme["id"], task_id, "agent_failed",
                     False, "agent reported failure", duration, ea_size_before, EA_PATH.stat().st_size])
        _save_state(theme, task_id, "agent_failed")
        return

    # 3. Compile
    _log("🔨 compiling EA...")
    ok, log_text = _compile_ea()
    # Extract last result line
    summary = ""
    for line in (log_text or "").splitlines():
        if "Result:" in line or "error" in line.lower():
            summary = line.strip()[:200]
    if not summary:
        summary = log_text[-200:] if log_text else ""

    ea_size_after = EA_PATH.stat().st_size

    if not ok:
        _log(f"✗ COMPILE FAILED — rolling back. {summary[:120]}")
        if ROLLBACK_ON_FAIL: _rollback(backup)
        _csv_append([datetime.now().isoformat(), theme["id"], task_id, "compile_failed",
                     False, summary, duration, ea_size_before, ea_size_after])
        _save_state(theme, task_id, "compile_failed")
        return

    _log(f"✅ compile OK. {summary[:120]}")
    _csv_append([datetime.now().isoformat(), theme["id"], task_id, "applied",
                 True, summary, duration, ea_size_before, ea_size_after])
    _save_state(theme, task_id, "applied")


def main():
    print("=" * 70)
    print("  FRIDAY EA Evolver — autonomous EA improvement")
    print("=" * 70)
    print(f"  EA path:      {EA_PATH}")
    print(f"  Backups:      {BACKUP_DIR}")
    print(f"  Log:          {EVOLVE_LOG}")
    print(f"  Cycle:        every {CYCLE_MINUTES} min")
    print(f"  Themes:       {len(THEMES)} configured")
    print(f"  Rollback:     {'enabled' if ROLLBACK_ON_FAIL else 'disabled'}")
    print("=" * 70)
    print()

    while True:
        try:
            run_cycle()
        except Exception as e:
            _log(f"cycle error: {e}")
            import traceback; traceback.print_exc()
        _log(f"💤 sleeping {CYCLE_MINUTES}min before next cycle")
        time.sleep(CYCLE_MINUTES * 60)


if __name__ == "__main__":
    main()
