"""embedded_services.py — manage brain + executor as subprocesses.

WHY subprocesses (not threads): Python's GIL means threads in one
process serialize on bytecode execution. With Qt UI + Flask brain + 5
agent threads + r_executor loop all in ONE process, Qt's event loop
could starve for 5+ seconds → Windows shows "(Not Responding)".

Subprocess approach: each component is its own Python process. Zero
GIL contention. Qt event loop stays smooth. Resource cost: ~50MB extra
RAM per process (negligible).

User experience is identical to threaded embedding: ONE command
(`python -m r_native.app`), ONE window, the brain + executor processes
spawn behind the scenes and are killed when the UI window closes.
"""
from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(r"C:\Users\Radhi\MT5")

# Track child processes so we can kill them on UI exit
_brain_proc:    Optional[subprocess.Popen] = None
_executor_proc: Optional[subprocess.Popen] = None
_brain_external: bool = False
_executor_mode:  str  = "PAPER"


# ─── Port probe ─────────────────────────────────────────────────────
def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ─── Brain server ───────────────────────────────────────────────────
def start_brain() -> dict:
    """Spawn brain_server.py as subprocess if not already running."""
    global _brain_proc, _brain_external
    if _port_open("127.0.0.1", 5055):
        _brain_external = True
        return {"started": False, "external": True, "port": 5055,
                "reason": "external brain on :5055"}
    if _brain_proc and _brain_proc.poll() is None:
        return {"started": False, "external": False,
                "reason": "subprocess already running",
                "pid": _brain_proc.pid}
    _brain_external = False
    log_dir = PROJECT_ROOT / "data" / "r_native"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "embedded_brain.log"
    err_path = log_dir / "embedded_brain.err"
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    _brain_proc = subprocess.Popen(
        [sys.executable, "brain_server.py"],
        cwd=str(PROJECT_ROOT),
        stdout=open(log_path, "a", encoding="utf-8", buffering=1),
        stderr=open(err_path, "a", encoding="utf-8", buffering=1),
        creationflags=creationflags,
    )
    return {"started": True, "external": False, "port": 5055,
            "pid": _brain_proc.pid, "log": str(log_path)}


# ─── R Executor ─────────────────────────────────────────────────────
def start_executor(mode: str = "PAPER") -> dict:
    """Spawn r_executor as subprocess."""
    global _executor_proc, _executor_mode
    if _executor_proc and _executor_proc.poll() is None:
        return {"started": False, "mode": _executor_mode,
                "reason": "subprocess already running",
                "pid": _executor_proc.pid}
    _executor_mode = mode
    log_dir = PROJECT_ROOT / "data" / "r_native"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "embedded_executor.log"
    err_path = log_dir / "embedded_executor.err"
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    # r_executor uses argparse — PAPER is default, --live for real orders
    cmd = [sys.executable, "-m", "friday_v3.algory.r_executor"]
    if mode.upper() == "LIVE":
        cmd.append("--live")
    _executor_proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=open(log_path, "a", encoding="utf-8", buffering=1),
        stderr=open(err_path, "a", encoding="utf-8", buffering=1),
        creationflags=creationflags,
    )
    return {"started": True, "mode": mode,
            "pid": _executor_proc.pid, "log": str(log_path)}


# ─── Status + lifecycle ────────────────────────────────────────────
def services_status() -> dict:
    return {
        "brain": {
            "alive":    _brain_external or _is_alive(_brain_proc),
            "port":     5055,
            "external": _brain_external,
            "pid":      _brain_proc.pid if _brain_proc else None,
        },
        "executor": {
            "alive": _is_alive(_executor_proc),
            "mode":  _executor_mode,
            "pid":   _executor_proc.pid if _executor_proc else None,
        },
        "endpoint_reachable": _port_open("127.0.0.1", 5055),
    }


def _is_alive(proc: Optional[subprocess.Popen]) -> bool:
    return proc is not None and proc.poll() is None


def stop_all():
    """Kill spawned children — called on UI exit."""
    for name, p in (("brain", _brain_proc), ("executor", _executor_proc)):
        if not p or p.poll() is not None: continue
        try:
            p.terminate()
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        except Exception as e:
            print(f"[stop_all] {name}: {e}", flush=True)


atexit.register(stop_all)


def start_all(executor_mode: str = "PAPER",
              delay_executor_seconds: int = 3) -> dict:
    """Spawn brain + executor as subprocesses. NON-BLOCKING.

    Main thread spends < 100ms here — both subprocesses start
    asynchronously and the UI can render immediately.
    """
    brain_r = start_brain()

    # Defer executor a bit so brain has time to bind
    import threading
    def _delayed_exec():
        time.sleep(delay_executor_seconds)
        start_executor(executor_mode)
    threading.Thread(target=_delayed_exec, name="exec-deferred",
                     daemon=True).start()

    return {"brain": brain_r,
            "executor_delayed_seconds": delay_executor_seconds,
            "status": services_status()}
