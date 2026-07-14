"""
friday_agent_team.py — Daemon that runs FRIDAY's specialist Claude clones.

5 specialist agents — each a clone of Claude with FRIDAY's full context + a specialty:
  🧠 STRATEGIST  — trading strategy expert
  💻 CODER       — code improvements & bug fixes
  🔬 RESEARCHER  — web research for strategies & best practices
  🛠 DEBUGGER    — bug hunting & root-cause fixes
  🎨 DESIGNER    — dashboard UX/UI improvements

Polls friday_tasks.json for pending work, dispatches each task to its
specialist via `claude -p` (Claude Code CLI in headless mode).

Run:    python friday_agent_team.py
Submit: python friday_delegate.py <role> "<task description>"
"""
from __future__ import annotations
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT          = Path(r"C:\Users\Radhi\MT5")
PERSONAS_DIR  = ROOT / "friday_agents_personas"
QUEUE_FILE    = ROOT / "friday_tasks.json"
LOG_FILE      = ROOT / "friday_agent_team_log.csv"
OUTPUT_DIR    = ROOT / "friday_agent_team_output"
STATE_FILE    = ROOT / "friday_agent_team_state.json"

CLAUDE_TIMEOUT_S = 600     # 10 min hard cap per task
POLL_INTERVAL_S  = 5
MAX_PARALLEL     = 2       # workers running simultaneously

ROLES = ["STRATEGIST", "CODER", "RESEARCHER", "DEBUGGER", "DESIGNER"]
ROLE_EMOJI = {
    "STRATEGIST": "🧠", "CODER": "💻", "RESEARCHER": "🔬",
    "DEBUGGER":   "🛠", "DESIGNER": "🎨",
}

# ─────────────────────────────────────────────────────────────────────────
# Queue helpers
# ─────────────────────────────────────────────────────────────────────────

_queue_lock = threading.Lock()

def _read_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {"tasks": []}
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tasks": []}

def _write_queue(data: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def enqueue(role: str, task: str, priority: int = 5, requested_by: str = "user") -> str:
    """Add a task. Returns task_id."""
    task_id = uuid.uuid4().hex[:8]
    with _queue_lock:
        q = _read_queue()
        q["tasks"].append({
            "id":           task_id,
            "role":         role.upper(),
            "task":         task,
            "priority":     priority,
            "status":       "pending",
            "submitted_at": datetime.now().isoformat(),
            "started_at":   None,
            "finished_at":  None,
            "result":       None,
            "requested_by": requested_by,
        })
        _write_queue(q)
    return task_id

def next_task() -> dict | None:
    """Atomically claim the highest-priority pending task."""
    with _queue_lock:
        q = _read_queue()
        pending = [t for t in q["tasks"] if t["status"] == "pending"]
        if not pending:
            return None
        pending.sort(key=lambda t: (-t["priority"], t["submitted_at"]))
        claimed = pending[0]
        claimed["status"]     = "in_progress"
        claimed["started_at"] = datetime.now().isoformat()
        _write_queue(q)
        return claimed

def mark_done(task_id: str, result: str, ok: bool) -> None:
    with _queue_lock:
        q = _read_queue()
        for t in q["tasks"]:
            if t["id"] == task_id:
                t["status"]      = "completed" if ok else "failed"
                t["finished_at"] = datetime.now().isoformat()
                t["result"]      = (result or "")[:2000]
                break
        _write_queue(q)


# ─────────────────────────────────────────────────────────────────────────
# Persona loading
# ─────────────────────────────────────────────────────────────────────────

def load_persona(role: str) -> str:
    """Master context + specialist persona = full system prompt."""
    master = (PERSONAS_DIR / "_master_context.md").read_text(encoding="utf-8")
    role_file = PERSONAS_DIR / f"{role}.md"
    if not role_file.exists():
        return master + "\n\n(no specialist persona found — operate from master context)"
    return master + "\n\n---\n\n" + role_file.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# Worker — runs one task through Claude Code CLI
# ─────────────────────────────────────────────────────────────────────────

def _log_csv(line: str) -> None:
    header = "ts,role,task_id,task_brief,status,duration_s,result_snippet\n"
    if not LOG_FILE.exists():
        LOG_FILE.write_text(header, encoding="utf-8")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_task(task: dict) -> None:
    role    = task["role"]
    task_id = task["id"]
    desc    = task["task"]
    persona = load_persona(role)
    emoji   = ROLE_EMOJI.get(role, "🤖")

    out_dir = OUTPUT_DIR / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    full_prompt = f"""{persona}

---

# Your task right now

**Task ID**: {task_id}
**Role**: {role}
**Requested**: {desc}

Work on this task end-to-end. Read whatever files you need, make changes,
verify, and write your final summary to:
`{out_dir / 'SUMMARY.md'}`

When done, also append ONE line to `{LOG_FILE}` in CSV format:
`<ts>,{role},{task_id},"<brief>",completed,<duration_s>,<one-line-result>`

Do not ask for clarification — make a reasonable interpretation and execute.
"""

    print(f"\n{'═'*72}")
    print(f"  {emoji} {role} starting task {task_id}")
    print(f"  → {desc[:80]}")
    print(f"{'═'*72}")

    started = time.time()
    cmd = ["claude", "-p", full_prompt,
           "--output-format", "json",
           "--print",
           "--dangerously-skip-permissions"]

    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CLAUDE_TIMEOUT_S,
        )
        duration = round(time.time() - started, 1)

        if proc.returncode != 0:
            err = (proc.stderr or "")[:400]
            (out_dir / "ERROR.txt").write_text(err, encoding="utf-8")
            print(f"  ✗ {role} {task_id} FAILED (code {proc.returncode}) in {duration}s")
            mark_done(task_id, f"FAILED: {err}", ok=False)
            _log_csv(f"{datetime.now().isoformat()},{role},{task_id},\"{desc[:40]}\",failed,{duration},\"{err[:80]}\"")
            return

        try:
            data = json.loads(proc.stdout.strip())
            result_text = data.get("result", proc.stdout.strip())
        except json.JSONDecodeError:
            result_text = proc.stdout.strip()

        (out_dir / "OUTPUT.txt").write_text(result_text, encoding="utf-8")
        snippet = result_text.split("\n")[0][:120] if result_text else ""
        print(f"  ✓ {role} {task_id} DONE in {duration}s")
        print(f"    {snippet}")
        mark_done(task_id, result_text, ok=True)
        _log_csv(f"{datetime.now().isoformat()},{role},{task_id},\"{desc[:40]}\",completed,{duration},\"{snippet}\"")

    except subprocess.TimeoutExpired:
        duration = round(time.time() - started, 1)
        print(f"  ⏱ {role} {task_id} TIMEOUT after {duration}s")
        mark_done(task_id, f"TIMEOUT after {duration}s", ok=False)
        _log_csv(f"{datetime.now().isoformat()},{role},{task_id},\"{desc[:40]}\",timeout,{duration},timeout")
    except FileNotFoundError:
        print(f"  ✗ Claude CLI not found — install Claude Code first")
        mark_done(task_id, "Claude CLI not installed", ok=False)
    except Exception as e:
        print(f"  ✗ {role} {task_id} ERROR: {e}")
        mark_done(task_id, f"ERROR: {e}", ok=False)


# ─────────────────────────────────────────────────────────────────────────
# Main daemon loop
# ─────────────────────────────────────────────────────────────────────────

def write_state(active_workers: list[str]) -> None:
    q = _read_queue()
    counts = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
    for t in q["tasks"]:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    state = {
        "ts":             datetime.now().isoformat(),
        "active_workers": active_workers,
        "queue_counts":   counts,
        "recent_tasks":   [{"id": t["id"], "role": t["role"], "status": t["status"],
                            "task": t["task"][:80], "result": (t.get("result") or "")[:120]}
                           for t in q["tasks"][-15:]],
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    print("=" * 72)
    print("  FRIDAY Agent Team — Claude specialist clones")
    print("=" * 72)
    print(f"  Roles:           {', '.join(ROLES)}")
    print(f"  Personas:        {PERSONAS_DIR}")
    print(f"  Queue:           {QUEUE_FILE.name}")
    print(f"  Output dir:      {OUTPUT_DIR.name}")
    print(f"  Max parallel:    {MAX_PARALLEL}")
    print(f"  Poll interval:   {POLL_INTERVAL_S}s")
    print(f"  Per-task limit:  {CLAUDE_TIMEOUT_S}s")
    print("=" * 72)
    print()

    # Sanity: ensure personas exist
    missing = [r for r in ROLES if not (PERSONAS_DIR / f"{r}.md").exists()]
    if missing:
        print(f"⚠ Missing personas: {missing}")

    # Ensure folders
    OUTPUT_DIR.mkdir(exist_ok=True)
    if not QUEUE_FILE.exists():
        _write_queue({"tasks": []})

    active: dict[str, threading.Thread] = {}

    while True:
        # Reap finished threads
        for tid, th in list(active.items()):
            if not th.is_alive():
                del active[tid]

        # Spawn new workers up to MAX_PARALLEL
        while len(active) < MAX_PARALLEL:
            task = next_task()
            if not task:
                break
            tid = task["id"]
            th = threading.Thread(target=run_task, args=(task,), daemon=True)
            th.start()
            active[tid] = th

        write_state([f"{t['id']}" for t in [next((x for x in _read_queue()['tasks'] if x['id'] == tid), {}) for tid in active]])
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
