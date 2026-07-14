"""Watchdog — keeps the desk loop alive with a singleton guard.

Holds a singleton TCP lock on a fixed port so only one watchdog runs, then
launches and supervises ``run.py``, restarting it if it exits. Honours a
``kill_switch.txt`` next to this script: while present, the loop is not
(re)started. Mirrors the project's existing watchdog discipline.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

_PORT = 8626  # unique singleton port for this desk's watchdog
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KILL = os.path.join(_ROOT, "kill_switch.txt")


def _singleton() -> socket.socket | None:
    """Bind the singleton port; return the socket or None if already held."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", _PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def _child(name: str, extra: list[str], symbols: list[str]) -> subprocess.Popen:
    """Start a supervised ``run.py`` child with extra args."""
    cmd = [sys.executable, os.path.join(_ROOT, "run.py"),
           "--symbols", *symbols, "--tf", "M5", *extra]
    print(f"[watchdog] (re)starting {name}")
    return subprocess.Popen(cmd, cwd=_ROOT)


def main() -> int:
    """Run the supervision loop over the execution loop + HR grader."""
    lock = _singleton()
    if lock is None:
        print(f"[watchdog] another instance holds :{_PORT} — exiting")
        return 1
    symbols = sys.argv[1:] or ["XAUUSDm", "BTCUSDm", "EURUSDm"]
    # name -> (extra args, handle)
    specs: dict[str, list[str]] = {"desk-loop": ["--all", "--interval", "180"],
                                   "hr-grader": ["--all", "--hr"],
                                   "evolution": ["--all", "--evo"],
                                   "dashboard": ["--dashboard"]}
    procs: dict[str, subprocess.Popen | None] = {k: None for k in specs}
    print(f"[watchdog] supervising {list(specs)} on {symbols} (singleton :{_PORT})")
    try:
        while True:
            if os.path.exists(_KILL):
                for n, p in procs.items():
                    if p and p.poll() is None:
                        p.terminate()
                        procs[n] = None
                print("[watchdog] kill_switch present — all children stopped")
                time.sleep(10)
                continue
            for name, extra in specs.items():
                p = procs[name]
                if p is None or p.poll() is not None:
                    procs[name] = _child(name, extra, symbols)
            time.sleep(15)
    except KeyboardInterrupt:
        for p in procs.values():
            if p:
                p.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
