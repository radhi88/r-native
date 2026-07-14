"""twoday_watchdog.py — stateless self-healing watchdog for unattended operation.

Run every few minutes by a Scheduled Task. Each run:
  1) Ensures the gold HTF overlay runner is alive (restarts it DETACHED if not).
     The runner's own singleton pidfile lock prevents duplicates.
  2) Takes a monitoring snapshot (account / positions / overlay -> twoday_report.md).
Exits immediately; Task Scheduler handles recurrence — nothing to babysit.

Pure Python (no PowerShell execution-policy dependency).
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
PY = Path(r"C:\Users\Radhi\MT5\.venv\Scripts\python.exe")
RUNNER = ROOT / "runtime" / "gold_htf_overlay_runner.py"
PIDFILE = ROOT / "data" / "gold_htf_overlay.pid"
WLOG = ROOT / "data" / "twoday_watchdog.log"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with WLOG.open("a", encoding="utf-8") as f:
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass
    print(f"{ts}  {msg}", flush=True)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore
        if not psutil.pid_exists(pid):
            return False
        p = psutil.Process(pid)
        return "python" in (p.name() or "").lower()
    except Exception:
        pass
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _overlay_alive() -> bool:
    try:
        if not PIDFILE.exists():
            return False
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
        return _pid_alive(pid)
    except Exception:
        return False


def _start_overlay() -> None:
    """Launch the overlay runner detached (survives this process exiting)."""
    env = dict(os.environ)
    env["ENABLE_GOLD_HTF_OVERLAY"] = "1"
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so it outlives the watchdog
    flags = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(
            [str(PY), str(RUNNER)],
            cwd=str(ROOT), env=env,
            creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, close_fds=True,
        )
        _log("overlay runner was DOWN -> started detached (armed)")
        time.sleep(3)
    except Exception as e:
        _log(f"FAILED to start overlay: {e}")


def main() -> int:
    if _overlay_alive():
        pid = PIDFILE.read_text(encoding="utf-8").strip() if PIDFILE.exists() else "?"
        _log(f"overlay alive (pid {pid})")
    else:
        _start_overlay()
    # snapshot
    try:
        from runtime import twoday_snapshot
        twoday_snapshot.main()
        _log("snapshot taken")
    except Exception as e:
        _log(f"snapshot failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
