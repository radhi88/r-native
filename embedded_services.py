"""embedded_services.py — run brain_server + r_executor inside the Qt app.

Until now R Native required 3 terminals (brain_server, app, r_executor).
This module collapses them into ONE process so the user just runs:

    python -m r_native.app

…and everything starts. The brain Flask server runs in a background
daemon thread, the r_executor loop in another, and the 5 agents +
continuous_evolution arm themselves on brain boot.

Design notes:
  • Idempotent: if an external brain is already on port 5055 (legacy
    setup), we skip embedding and use the external one instead. This
    means the user can still run them split if they want.
  • Daemon threads die when the Qt window closes — no zombie processes.
  • MT5 is shared across all threads via the global mt5 module (each
    init() call after the first is a no-op).
  • Each service has its own status function so the UI can render a
    health bar.
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Optional


# ─── Module state (per process) ────────────────────────────────────
_brain_thread:    Optional[threading.Thread] = None
_executor_thread: Optional[threading.Thread] = None
_brain_external:  bool = False   # True if we detected a brain we didn't start
_executor_mode:   str = "PAPER"  # PAPER | LIVE — set by start_executor()


# ─── Port probe ─────────────────────────────────────────────────────
def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ─── Brain server ───────────────────────────────────────────────────
def _run_brain():
    """Target for the brain_server daemon thread."""
    try:
        # Import here so failures land in this thread, not at app boot
        import brain_server  # registers all @app.route handlers + starts agents
        from r_native.agents.orchestrator import start_all as _start_agents
        from r_native.continuous_evolution import start as _start_evo
        _start_agents()
        _start_evo()
        # Run Flask without reloader (it conflicts with non-main-thread start)
        brain_server.app.run(
            host="127.0.0.1", port=5055,
            debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        print(f"[embedded brain] CRASHED: {e}", flush=True)


def start_brain() -> dict:
    """Start brain_server in a daemon thread if not already running.

    NON-BLOCKING — returns immediately. The thread comes up asynchronously
    over the next few seconds; UI should poll services_status() to detect
    when the port is reachable.
    """
    global _brain_thread, _brain_external
    if _port_open("127.0.0.1", 5055):
        _brain_external = True
        return {"started": False, "external": True, "port": 5055,
                "reason": "external brain detected on :5055"}
    if _brain_thread and _brain_thread.is_alive():
        return {"started": False, "external": False, "port": 5055,
                "reason": "already running in this process"}
    _brain_external = False
    _brain_thread = threading.Thread(target=_run_brain,
                                     name="embedded-brain",
                                     daemon=True)
    _brain_thread.start()
    return {"started": True, "external": False, "port": 5055,
            "alive": _brain_thread.is_alive()}


# ─── R Executor ─────────────────────────────────────────────────────
def _run_executor(mode: str, interval: int):
    """Target for the executor daemon thread."""
    try:
        from friday_v3.algory.r_executor import loop as _exec_loop
        _exec_loop(mode, interval)
    except Exception as e:
        print(f"[embedded executor] CRASHED: {e}", flush=True)


def start_executor(mode: str = "PAPER", interval: int = 30) -> dict:
    """Start the autonomous trader in a daemon thread. NON-BLOCKING."""
    global _executor_thread, _executor_mode
    if _executor_thread and _executor_thread.is_alive():
        return {"started": False, "mode": _executor_mode,
                "reason": "already running"}
    _executor_mode = mode
    _executor_thread = threading.Thread(
        target=_run_executor,
        name=f"embedded-executor-{mode}",
        args=(mode, interval),
        daemon=True)
    _executor_thread.start()
    return {"started": True, "mode": mode,
            "alive": _executor_thread.is_alive()}


# ─── Status reporting ──────────────────────────────────────────────
def services_status() -> dict:
    """Compact status for the UI status bar."""
    brain_alive = (_brain_external or
                   (_brain_thread is not None and _brain_thread.is_alive()))
    return {
        "brain": {
            "alive":    brain_alive,
            "port":     5055,
            "external": _brain_external,
            "embedded_thread_alive": bool(
                _brain_thread and _brain_thread.is_alive()),
        },
        "executor": {
            "alive": bool(_executor_thread and _executor_thread.is_alive()),
            "mode":  _executor_mode,
        },
        "endpoint_reachable": _port_open("127.0.0.1", 5055),
    }


def start_all(executor_mode: str = "PAPER",
              delay_executor_seconds: int = 4) -> dict:
    """Convenience: start brain + executor in one call. NON-BLOCKING.

    Brain starts immediately in its daemon thread. Executor starts after
    `delay_executor_seconds` (also in a daemon thread that sleeps first),
    so it can talk to a brain that's had a chance to bind. The main
    thread is not blocked at any point — the Qt UI can render immediately.
    """
    brain_r = start_brain()

    # Schedule the executor start without blocking — use a tiny launcher thread
    def _delayed_exec_start():
        time.sleep(delay_executor_seconds)
        start_executor(executor_mode)
    threading.Thread(target=_delayed_exec_start,
                     name="exec-deferred-start",
                     daemon=True).start()

    return {"brain": brain_r,
            "executor_delayed_seconds": delay_executor_seconds,
            "status": services_status()}
