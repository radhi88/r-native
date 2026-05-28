"""r_native/v2_stack.py — Launch & supervise the unified v2 trading stack.

Born 2026-05-28: "الحل 3 — جعل R Native نفسه يطلق كل شي".

When R Native (app.py) boots, it calls start_all() here, which spawns
the 8 unified-stack processes as detached subprocesses. The user just
opens R Native — the whole trading brain comes up automatically.

DESIGN:
  • dedup-safe — never spawns a service that's already running
    (checks running python.exe command lines via psutil)
  • silent — each service logs to data/logs/<service>.log (CREATE_NO_WINDOW)
  • crash-tolerant — a service that fails to spawn doesn't block the others
  • clean shutdown — stop_all() terminates only what we own

The 8 services (run from r_native_v2/ so `python -m runtime.X` resolves):
  brain_v1, regime_classifier, trader_orchestrator, genome_promoter,
  genome_evolver, unified_trader, trailing_stop_manager,
  decision_outcome_filler
"""
from __future__ import annotations
import subprocess
import sys
import os
from pathlib import Path

# The v2 runtime lives in the sibling r_native_v2 (data paths are absolute there).
R_NATIVE_V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2")
LOG_DIR = R_NATIVE_V2 / "data" / "logs"

# Order matters: producers before consumers.
SERVICES = [
    "brain_v1",                 # market snapshot
    "regime_classifier",        # TREND/CHOP
    "trader_orchestrator",      # regime gate
    "genome_promoter",          # promote best gene
    "genome_evolver",           # breed genes
    "unified_trader",           # THE sole executor
    "trailing_stop_manager",    # SL trail
    "decision_outcome_filler",  # PnL backfill
    "trade_sync",               # MT5 history → db (manual trades feed learning)
]

_spawned: dict[str, int] = {}   # service -> pid we started


def _running_modules() -> set[str]:
    """Return the set of runtime.<module> names currently running."""
    running: set[str] = set()
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if not p.info["name"] or "python" not in p.info["name"].lower():
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                for svc in SERVICES:
                    if f"runtime.{svc}" in cmd:
                        running.add(svc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return running


def start_all() -> dict:
    """Spawn any of the 8 services that aren't already running.

    Returns {"started": [...], "already_running": [...], "failed": [...]}.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    already = _running_modules()

    started, skipped, failed = [], [], []
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW — silent background, no console popups
        creationflags = 0x08000000

    for svc in SERVICES:
        if svc in already:
            skipped.append(svc)
            continue
        try:
            logf = open(LOG_DIR / f"{svc}.log", "a", encoding="utf-8")
            p = subprocess.Popen(
                [sys.executable, "-m", f"runtime.{svc}"],
                cwd=str(R_NATIVE_V2),
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=True,
            )
            _spawned[svc] = p.pid
            started.append(svc)
        except Exception as e:
            failed.append((svc, str(e)))

    return {"started": started, "already_running": skipped, "failed": failed}


def stop_all() -> int:
    """Terminate every running v2 service (ours + any leaked copies). Returns count."""
    killed = 0
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if not p.info["name"] or "python" not in p.info["name"].lower():
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                if any(f"runtime.{svc}" in cmd for svc in SERVICES):
                    p.terminate()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    _spawned.clear()
    return killed


def status() -> dict:
    """Which of the 8 are alive right now."""
    running = _running_modules()
    return {svc: (svc in running) for svc in SERVICES}


def summary_line() -> str:
    s = status()
    up = sum(1 for v in s.values() if v)
    return f"v2 stack: {up}/{len(SERVICES)} services up"


__all__ = ["start_all", "stop_all", "status", "summary_line", "SERVICES"]
