"""
friday_delegate.py — Submit a task to the FRIDAY Agent Team.

Usage:
    python friday_delegate.py <role> "<task description>" [--priority N]
    python friday_delegate.py list                    # show all tasks
    python friday_delegate.py status <task_id>        # show one task
    python friday_delegate.py clear-completed         # purge done tasks

Roles: strategist | coder | researcher | debugger | designer

Examples:
    python friday_delegate.py coder "Add type hints to friday_brain.py functions missing them"
    python friday_delegate.py researcher "Find 3 M1 scalp strategies for gold that handle 300pt spread"
    python friday_delegate.py strategist "Review last 50 orders in friday_orders.csv and suggest a new gate"
    python friday_delegate.py debugger "MOMENTUM agent keeps WAIT — investigate why"
    python friday_delegate.py designer "Add a live equity sparkline to the dashboard header"
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT       = Path(r"C:\Users\Radhi\MT5")
QUEUE_FILE = ROOT / "friday_tasks.json"

VALID_ROLES = ["STRATEGIST", "CODER", "RESEARCHER", "DEBUGGER", "DESIGNER"]


def read_q() -> dict:
    if not QUEUE_FILE.exists():
        return {"tasks": []}
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def write_q(d: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_submit(role: str, task: str, priority: int) -> None:
    import uuid
    from datetime import datetime
    role = role.upper()
    if role not in VALID_ROLES:
        print(f"✗ Invalid role '{role}'. Pick one of: {VALID_ROLES}")
        sys.exit(1)

    q = read_q()
    task_id = uuid.uuid4().hex[:8]
    q["tasks"].append({
        "id":           task_id,
        "role":         role,
        "task":         task,
        "priority":     priority,
        "status":       "pending",
        "submitted_at": datetime.now().isoformat(),
        "started_at":   None,
        "finished_at":  None,
        "result":       None,
        "requested_by": "cli",
    })
    write_q(q)
    print(f"✓ Submitted task {task_id} to {role} (priority {priority})")
    print(f"  Watch: python friday_delegate.py status {task_id}")


def cmd_list() -> None:
    q = read_q()
    if not q["tasks"]:
        print("(no tasks)")
        return
    print(f"{'ID':<10} {'ROLE':<12} {'STATUS':<12} {'TASK':<60}")
    print("-" * 100)
    for t in q["tasks"][-30:]:
        task_short = t["task"][:60].replace("\n", " ")
        print(f"{t['id']:<10} {t['role']:<12} {t['status']:<12} {task_short}")


def cmd_status(task_id: str) -> None:
    q = read_q()
    for t in q["tasks"]:
        if t["id"] == task_id:
            print(json.dumps(t, ensure_ascii=False, indent=2))
            return
    print(f"(no task with id {task_id})")


def cmd_clear() -> None:
    q = read_q()
    before = len(q["tasks"])
    q["tasks"] = [t for t in q["tasks"] if t["status"] not in ("completed", "failed")]
    after = len(q["tasks"])
    write_q(q)
    print(f"✓ Removed {before - after} completed/failed tasks. {after} remain.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); return

    cmd = args[0].lower()
    if cmd == "list":
        cmd_list(); return
    if cmd == "status":
        if len(args) < 2: print("usage: friday_delegate.py status <task_id>"); return
        cmd_status(args[1]); return
    if cmd in ("clear-completed", "clear"):
        cmd_clear(); return

    # Default: submit a task
    role = args[0]
    task_words = args[1:]
    priority = 5
    if "--priority" in task_words:
        i = task_words.index("--priority")
        priority = int(task_words[i+1])
        task_words = task_words[:i] + task_words[i+2:]
    elif "-p" in task_words:
        i = task_words.index("-p")
        priority = int(task_words[i+1])
        task_words = task_words[:i] + task_words[i+2:]
    if not task_words:
        print(__doc__); return
    task = " ".join(task_words)
    cmd_submit(role, task, priority)


if __name__ == "__main__":
    main()
