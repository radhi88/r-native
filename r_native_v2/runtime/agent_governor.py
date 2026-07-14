"""runtime/agent_governor.py — The autonomy daemon.

Born 2026-05-29 from the user's mandate:

  "الوكلاء يقومون بما تقومه به انت بالضبط ... تعديل ما يلزم وضبط كل شيء واعادة
   التشغيل، وليس متفرجين ... وقبل اطلاقها يقومون باستشاراتك كل واحد منهم او
   بالاجماع."

i.e. the agents must DO what Claude does — tune, edit, restart — not spectate.
But every change passes a gate first: Claude's consult OR the agents' consensus.

This daemon is the executor side of that gate. agent_governance.py is the
constitution (propose/vote/consult/apply primitives); this process is the
standing officer that:

  1. APPLIES   every proposal that has cleared the gate
                 • CONSENSUS_OK   (non-money, peers agreed)        → apply
                 • APPROVED       (Claude said yes in consult)     → apply
                 (HIGH / money-touching never reach CONSENSUS — they sit in
                  NEEDS_CLAUDE until claude_decide(), so they can't slip through)
  2. RESTARTS  every service queued by an applied change (or by request_restart)
                 — kills the live `python -m runtime.<svc>` and relaunches it,
                 exactly the dedupe-safe spawn the launcher uses.
  3. SURFACES  the Claude consult queue + a full status snapshot to
                 data/governance/governor_status.json so the UI (and Claude)
                 always see what's waiting and what shipped.

It NEVER writes code itself: edit_code proposals are approved-in-principle here,
Claude writes the actual diff, and the affected service is queued for restart.
That keeps the human-grade judgement (Claude) on the one action that can do
arbitrary harm, while everything mechanical runs autonomously.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.shared import agent_governance as gov

# Where the v2 services live (same root as the launcher uses).
R_NATIVE_V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2")
LOG_DIR     = R_NATIVE_V2 / "data" / "logs"

STATUS_FILE  = gov.GOV_DIR / "governor_status.json"
QUEUE_CURSOR = gov.GOV_DIR / ".restart_cursor"      # how many queue lines we've consumed

POLL_SEC = 15.0

# Services the governor is allowed to bounce. Mirrors v2_stack.SERVICES so a
# rogue/garbage restart target can't make us spawn an arbitrary module.
ALLOWED_SERVICES = {
    "brain_v1", "regime_classifier", "trader_orchestrator",
    "genome_promoter", "genome_evolver", "r_native_brain_link",
    "unified_trader", "palace_council", "trailing_stop_manager",
    "decision_outcome_filler", "trade_sync", "champion_evolution",
    "genome_academy", "agent_governor",
}
# Never let the queue ask us to restart ourselves (would orphan the relaunch).
NEVER_RESTART = {"agent_governor"}


# ──────────────────────────────────────────────────────────
# Process control (dedupe-safe, never matches our own probes)
# ──────────────────────────────────────────────────────────
def _proc_iter():
    import psutil
    for p in psutil.process_iter(["name", "cmdline", "pid"]):
        try:
            if not p.info["name"] or "python" not in p.info["name"].lower():
                continue
            yield p, " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _is_running(svc: str) -> bool:
    token = f"runtime.{svc}"
    for _p, cmd in _proc_iter():
        # `-m runtime.<svc>` only — never a `python -c "...runtime.<svc>..."` probe
        if token in cmd and "-c" not in cmd.split():
            return True
    return False


def _kill_service(svc: str) -> int:
    """Terminate every live `python -m runtime.<svc>` (excludes us & -c probes)."""
    import psutil
    token = f"runtime.{svc}"
    me = os.getpid()
    killed = 0
    for p, cmd in _proc_iter():
        try:
            if p.info["pid"] == me:
                continue
            if token in cmd and "-c" not in cmd.split():
                p.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        # give them a beat to die, then hard-kill stragglers
        time.sleep(1.0)
        for p, cmd in _proc_iter():
            try:
                if p.info["pid"] != me and token in cmd and "-c" not in cmd.split():
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return killed


def _spawn_service(svc: str) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    creationflags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
    logf = open(LOG_DIR / f"{svc}.log", "a", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", f"runtime.{svc}"],
        cwd=str(R_NATIVE_V2),
        stdout=logf, stderr=subprocess.STDOUT,
        creationflags=creationflags, close_fds=True,
    )
    return p.pid


def _restart_service(svc: str) -> str:
    if svc not in ALLOWED_SERVICES:
        return f"refused: {svc!r} not an allowed service"
    if svc in NEVER_RESTART:
        return f"refused: will not restart self ({svc})"
    killed = _kill_service(svc)
    pid = _spawn_service(svc)
    return f"restarted {svc}: killed {killed}, new pid {pid}"


# ──────────────────────────────────────────────────────────
# Restart-queue consumption (cursor-tracked, exactly-once)
# ──────────────────────────────────────────────────────────
def _read_cursor() -> int:
    try:
        return int(QUEUE_CURSOR.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


def _write_cursor(n: int) -> None:
    gov.GOV_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_CURSOR.write_text(str(n), encoding="utf-8")


def _drain_restart_queue() -> list[str]:
    """Process any restart requests appended since our last cursor. De-dupes
    repeated requests for the same service within one drain."""
    if not gov.RESTART_QUEUE.exists():
        return []
    lines = gov.RESTART_QUEUE.read_text(encoding="utf-8").splitlines()
    cursor = _read_cursor()
    new = lines[cursor:]
    if not new:
        return []
    wanted: list[str] = []
    for ln in new:
        if not ln.strip():
            continue
        try:
            svc = (json.loads(ln).get("service") or "").strip()
        except Exception:
            continue
        if svc and svc not in wanted:
            wanted.append(svc)
    results = []
    for svc in wanted:
        try:
            results.append(_restart_service(svc))
        except Exception as e:
            results.append(f"restart {svc} failed: {type(e).__name__}: {e}")
    _write_cursor(len(lines))
    return results


# ──────────────────────────────────────────────────────────
# Apply cleared proposals
# ──────────────────────────────────────────────────────────
def _apply_cleared() -> list[str]:
    out = []
    for p in gov.approved_ready():
        ok, res = gov.apply_proposal(p)
        out.append(f"{'✓' if ok else '✗'} {p.id} {p.action} {p.target} → {res}")
    return out


# ──────────────────────────────────────────────────────────
# Status snapshot
# ──────────────────────────────────────────────────────────
def _write_status(last_applied: list[str], last_restarts: list[str]) -> None:
    snap = gov.snapshot()
    snap["service"] = "agent_governor"
    snap["heartbeat"] = datetime.now(timezone.utc).isoformat()
    snap["last_applied"] = last_applied[-10:]
    snap["last_restarts"] = last_restarts[-10:]
    gov.GOV_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    os.replace(tmp, STATUS_FILE)


# ──────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────
def main_loop() -> None:
    print(f"[governor] ONLINE — polling every {POLL_SEC:.0f}s "
          f"(gate: consensus OR Claude consult; money/code → Claude)", flush=True)
    last_applied: list[str] = []
    last_restarts: list[str] = []
    while True:
        try:
            applied = _apply_cleared()
            if applied:
                last_applied += applied
                for line in applied:
                    print(f"[governor] apply {line}", flush=True)

            restarts = _drain_restart_queue()
            if restarts:
                last_restarts += restarts
                for line in restarts:
                    print(f"[governor] {line}", flush=True)

            # Show what's waiting on Claude (the consult queue the user mandated).
            waiting = gov.pending_for_claude()
            if waiting:
                names = ", ".join(f"{p.id}:{p.action}:{p.target}" for p in waiting[:5])
                print(f"[governor] {len(waiting)} awaiting Claude consult → {names}",
                      flush=True)

            _write_status(last_applied, last_restarts)
        except KeyboardInterrupt:
            print("[governor] stopped", flush=True)
            break
        except Exception as e:
            print(f"[governor] err: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main_loop()
