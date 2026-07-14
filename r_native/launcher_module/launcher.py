"""launcher.py — Always-on supervisor for the R Native Worker process.

Mirrors Algory.exe's parent+worker pattern:
  - This process stays small (~30MB), shows only a tray icon + tiny status window
  - Spawns RNativeWorker (= r_native/app.py) as a subprocess with no console
  - Polls http://127.0.0.1:7711/heartbeat every 2s
  - On 3 consecutive misses → kill + respawn (worker likely wedged or OOM)
  - Tray menu: Show Worker · Restart Worker · Quit Both

Usage
-----
    python -m r_native_launcher.launcher          # source mode
    RNativeLauncher.exe                            # frozen mode (PyInstaller)

When frozen, sys.executable points at RNativeLauncher.exe; the worker is
spawned by invoking sibling RNativeWorker.exe in the same _internal/ bundle.
"""
from __future__ import annotations

import os
import sys
import time
import json
import signal
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from PySide6.QtCore    import Qt, QTimer, QPoint
from PySide6.QtGui     import QIcon, QAction, QFont
from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QDialog,
                               QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
                               QFrame, QStyle, QMessageBox)


# ─── Configuration ─────────────────────────────────────────────────────
PROJECT_ROOT     = Path(__file__).parent.parent
WORKER_PORT      = 7711
HEARTBEAT_URL    = f"http://127.0.0.1:{WORKER_PORT}/heartbeat"
SHUTDOWN_URL     = f"http://127.0.0.1:{WORKER_PORT}/shutdown"
POLL_INTERVAL_MS = 2000               # 2s heartbeat poll
POLL_TIMEOUT_S   = 1.5                # individual request timeout
MAX_MISSES       = 3                  # 3 misses (~6s dead) → respawn
SPAWN_GRACE_S    = 30                 # max wait for new worker first heartbeat
RESTART_BACKOFF  = [1, 2, 5, 10, 30, 60]  # seconds between respawn attempts
# Crash-rate circuit breaker: if the worker dies > CRASH_MAX times inside
# CRASH_WINDOW_S, stop hammering respawns and surface a loud alert instead.
# This prevents perpetual churn when the worker hard-crashes seconds after
# launch (e.g. the Qt 0xFFFFFFFF crash) — which otherwise reset the backoff
# index every spawn and respawned in a tight loop.
CRASH_WINDOW_S   = 600                 # 10-minute sliding window
CRASH_MAX        = 6                   # crashes/window before the breaker trips
STABLE_RESET_S   = 120                 # worker must live this long to reset backoff
LOG_FILE         = PROJECT_ROOT / "data" / "r_native" / "launcher.log"


def _now_iso() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str) -> None:
    line = f"[{_now_iso()}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _resolve_worker_command() -> list[str]:
    """Return the argv to spawn the worker.

    Frozen mode  → sibling RNativeWorker.exe in same _internal/
    Source mode  → python -m r_native.app
    """
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: RNativeLauncher.exe lives next to RNativeWorker.exe
        worker_exe = Path(sys.executable).parent / "RNativeWorker.exe"
        if worker_exe.exists():
            return [str(worker_exe)]
        # Fallback: same exe with --worker flag (single-exe mode)
        return [sys.executable, "--worker"]
    # Source mode
    return [sys.executable, "-m", "r_native.app"]


# ─── Worker supervisor ─────────────────────────────────────────────────
class WorkerSupervisor:
    """Spawns + monitors the worker subprocess."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.misses          = 0
        self.last_ok_ts      = 0.0
        self.last_state      = {}
        self.restart_count   = 0
        self.spawn_attempt_i = 0
        self.crash_times: list[float] = []   # recent death timestamps
        self.tripped         = False         # crash-rate breaker engaged?
        self.spawn_ts        = 0.0           # when the current worker was spawned

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self) -> bool:
        if self.is_alive():
            return True
        cmd = _resolve_worker_command()
        _log(f"spawning worker: {' '.join(cmd)}")
        creationflags = 0
        if sys.platform == "win32":
            # Worker child gets no console window
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd            = str(PROJECT_ROOT),
                creationflags  = creationflags,
                stdout         = subprocess.DEVNULL,
                stderr         = subprocess.DEVNULL,
            )
            self.misses           = 0
            self.last_ok_ts       = time.time()
            self.spawn_ts         = time.time()
            # NOTE: do NOT reset spawn_attempt_i here. A worker that crashes
            # seconds after a "successful" spawn would otherwise reset the
            # backoff every time and respawn in a tight loop. The index is
            # only reset once the worker has stayed alive STABLE_RESET_S
            # (see tick()).
            _log(f"  ↳ worker PID {self.proc.pid}")
            return True
        except Exception as e:
            _log(f"  ↳ spawn FAILED: {e}")
            self.proc = None
            return False

    def kill(self, graceful: bool = True) -> None:
        if not self.is_alive():
            return
        pid = self.proc.pid
        if graceful:
            try:
                req = urllib.request.Request(SHUTDOWN_URL, method="POST")
                urllib.request.urlopen(req, timeout=2).read()
                _log(f"sent graceful /shutdown to PID {pid}")
                # Wait up to 8s for clean exit
                for _ in range(40):
                    if self.proc.poll() is not None:
                        _log(f"  ↳ PID {pid} exited cleanly")
                        return
                    time.sleep(0.2)
                _log(f"  ↳ PID {pid} ignored shutdown, force-killing")
            except Exception as e:
                _log(f"  ↳ graceful shutdown failed ({e}); force-killing")
        try:
            self.proc.kill()
            self.proc.wait(timeout=3)
        except Exception as e:
            _log(f"  ↳ kill error: {e}")
        self.proc = None

    def poll_heartbeat(self) -> dict | None:
        """One heartbeat request. Returns dict on success, None on miss."""
        try:
            with urllib.request.urlopen(HEARTBEAT_URL, timeout=POLL_TIMEOUT_S) as r:
                data = json.loads(r.read().decode())
                self.last_ok_ts = time.time()
                self.misses     = 0
                self.last_state = data
                return data
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            self.misses += 1
            return None

    def tick(self) -> dict:
        """Run one supervision cycle. Returns status dict for the UI."""
        # Did the process die without us asking?
        if self.proc is not None and self.proc.poll() is not None:
            exit_code = self.proc.returncode
            now = time.time()
            self.crash_times = [t for t in self.crash_times
                                if now - t < CRASH_WINDOW_S]
            self.crash_times.append(now)
            _log(f"worker exited unexpectedly (code {exit_code}) "
                 f"[crash {len(self.crash_times)}/{CRASH_MAX} in "
                 f"<{CRASH_WINDOW_S//60}min]")
            self.proc = None

        if not self.is_alive():
            # Circuit breaker: too many crashes in the window → stop the
            # churn and alert loudly instead of hammering respawns.
            now = time.time()
            recent = [t for t in self.crash_times if now - t < CRASH_WINDOW_S]
            if len(recent) > CRASH_MAX:
                if not self.tripped:
                    self.tripped = True
                    _log("CRASH-LOOP BREAKER TRIPPED — worker died "
                         f"{len(recent)}× in <{CRASH_WINDOW_S//60}min. "
                         "Pausing respawns; investigate the worker crash "
                         "(likely the Qt 0xFFFFFFFF fault). Will resume once "
                         "the crash rate falls below threshold.")
                return self._status_dict()
            if self.tripped:
                _log("crash rate back below threshold — resuming respawns")
                self.tripped = False

            backoff_s = RESTART_BACKOFF[min(self.spawn_attempt_i,
                                            len(RESTART_BACKOFF) - 1)]
            self.spawn_attempt_i += 1
            if self.spawn_attempt_i > 1:
                _log(f"backoff {backoff_s}s before respawn (attempt {self.spawn_attempt_i})")
            time.sleep(backoff_s if self.spawn_attempt_i > 1 else 0)
            if self.spawn():
                self.restart_count += 1
            return self._status_dict()

        # Worker has been alive long enough → it's stable, reset the backoff
        # escalation so a future isolated crash starts fresh from attempt 0.
        if self.spawn_attempt_i and self.spawn_ts \
                and (time.time() - self.spawn_ts) >= STABLE_RESET_S:
            _log(f"worker stable for {STABLE_RESET_S}s — resetting backoff")
            self.spawn_attempt_i = 0

        data = self.poll_heartbeat()
        if data is None and self.misses >= MAX_MISSES:
            _log(f"heartbeat missed {self.misses}× — killing wedged worker PID {self.proc.pid}")
            self.kill(graceful=False)
            # next tick will respawn

        # Honor a graceful restart request from the worker itself (H.6)
        if data and data.get("wants_restart"):
            _log("worker requested restart (wants_restart=true)")
            self.kill(graceful=True)
            # next tick will respawn

        return self._status_dict()

    def _status_dict(self) -> dict:
        return {
            "alive":         self.is_alive(),
            "pid":           self.proc.pid if self.is_alive() else None,
            "misses":        self.misses,
            "last_ok_age_s": round(time.time() - self.last_ok_ts, 1) if self.last_ok_ts else None,
            "ram_mb":        self.last_state.get("ram_mb"),
            "uptime_sec":    self.last_state.get("uptime_sec"),
            "vault_size":    self.last_state.get("vault_size"),
            "restart_count": self.restart_count,
        }


# ─── Status window (small, ~280×140) ───────────────────────────────────
class StatusWindow(QDialog):
    def __init__(self, supervisor: WorkerSupervisor):
        super().__init__()
        self.sup = supervisor
        self.setWindowTitle("R Native — Worker")
        self.setFixedSize(300, 160)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        ico_path = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.ico"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        title = QLabel("R NATIVE · Worker Supervisor")
        title.setStyleSheet("color:#fbbf24; font-weight:700; letter-spacing:2px;")
        v.addWidget(title)

        self.lbl_state  = QLabel("—"); self.lbl_state.setStyleSheet("font-size:11px;")
        self.lbl_pid    = QLabel("—"); self.lbl_pid.setStyleSheet("color:#94a3b8; font-size:10px; font-family:Consolas;")
        self.lbl_ram    = QLabel("—"); self.lbl_ram.setStyleSheet("color:#94a3b8; font-size:10px; font-family:Consolas;")
        self.lbl_uptime = QLabel("—"); self.lbl_uptime.setStyleSheet("color:#94a3b8; font-size:10px; font-family:Consolas;")
        self.lbl_misses = QLabel("—"); self.lbl_misses.setStyleSheet("color:#94a3b8; font-size:10px; font-family:Consolas;")
        for w in (self.lbl_state, self.lbl_pid, self.lbl_ram, self.lbl_uptime, self.lbl_misses):
            v.addWidget(w)

        btn_row = QHBoxLayout()
        self.btn_restart = QPushButton("Restart Worker")
        self.btn_restart.clicked.connect(self._on_restart)
        btn_row.addWidget(self.btn_restart)
        v.addLayout(btn_row)

        # Dark theme
        self.setStyleSheet("""
            QDialog  { background: #0d0824; color: #f1f5f9; }
            QPushButton {
                background: #1c1142; color: #fbbf24; border: 1px solid #4c1d95;
                padding: 4px 10px; border-radius: 4px; font-size: 10px;
            }
            QPushButton:hover { background: #2d1b69; }
        """)

    def update_view(self, st: dict) -> None:
        if st["alive"]:
            self.lbl_state.setText("● ALIVE")
            self.lbl_state.setStyleSheet("color:#10b981; font-size:12px; font-weight:700;")
        else:
            self.lbl_state.setText("○ DOWN — respawning…")
            self.lbl_state.setStyleSheet("color:#ef4444; font-size:12px; font-weight:700;")
        self.lbl_pid.setText(f"PID:      {st['pid'] or '—'}")
        self.lbl_ram.setText(f"RAM:      {st['ram_mb'] or '—'} MB")
        u = st['uptime_sec']
        self.lbl_uptime.setText(f"Uptime:   {int(u)}s" if u else "Uptime:   —")
        miss_color = "#ef4444" if st["misses"] >= 2 else "#94a3b8"
        self.lbl_misses.setText(f"Misses:   {st['misses']}   ·   restarts: {st['restart_count']}")
        self.lbl_misses.setStyleSheet(f"color:{miss_color}; font-size:10px; font-family:Consolas;")

    def _on_restart(self):
        self.btn_restart.setEnabled(False)
        self.btn_restart.setText("Restarting…")
        self.sup.kill(graceful=True)
        QTimer.singleShot(1200, self._restart_complete)

    def _restart_complete(self):
        self.btn_restart.setEnabled(True)
        self.btn_restart.setText("Restart Worker")


# ─── Main app ──────────────────────────────────────────────────────────
def main():
    # Windows: distinct AppUserModelID so the tray icon is OUR icon
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.radhi.rnative.launcher")
        except Exception: pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    ico_path = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.ico"
    if ico_path.exists():
        app.setWindowIcon(QIcon(str(ico_path)))

    # Single-instance check via the worker port —
    # if another launcher is already supervising, exit immediately.
    try:
        urllib.request.urlopen(HEARTBEAT_URL, timeout=0.8).read()
        QMessageBox.information(None, "R Native",
            "Another R Native worker is already running.\n"
            "Use its tray icon to control it.")
        sys.exit(0)
    except Exception:
        pass  # no existing worker — good, proceed

    sup     = WorkerSupervisor()
    status  = StatusWindow(sup)

    # Tray icon
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "R Native", "System tray unavailable on this OS.")
        sys.exit(1)
    tray_icon = QIcon(str(ico_path)) if ico_path.exists() \
                else app.style().standardIcon(QStyle.SP_ComputerIcon)
    tray = QSystemTrayIcon(tray_icon)
    tray.setToolTip("R Native — Worker Supervisor")

    menu = QMenu()
    a_show = QAction("Show Status"); a_show.triggered.connect(lambda: (status.show(), status.raise_()))
    a_restart = QAction("Restart Worker"); a_restart.triggered.connect(lambda: sup.kill(graceful=True))
    a_force   = QAction("Force Kill Worker"); a_force.triggered.connect(lambda: sup.kill(graceful=False))
    a_quit    = QAction("Quit Both")
    def _quit():
        sup.kill(graceful=True)
        app.quit()
    a_quit.triggered.connect(_quit)
    menu.addAction(a_show)
    menu.addSeparator()
    menu.addAction(a_restart)
    menu.addAction(a_force)
    menu.addSeparator()
    menu.addAction(a_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: status.show() if reason == QSystemTrayIcon.Trigger else None)
    tray.show()

    # Initial spawn
    _log("=" * 50)
    _log("RNativeLauncher started")
    sup.spawn()

    # Supervision timer — 2s tick
    def _tick():
        st = sup.tick()
        if status.isVisible():
            status.update_view(st)
    timer = QTimer()
    timer.timeout.connect(_tick)
    timer.start(POLL_INTERVAL_MS)

    # Show status briefly on first launch so user sees "it works"
    status.show()
    QTimer.singleShot(4000, status.hide)

    sys.exit(app.exec())


if __name__ == "__main__":
    # PyInstaller multiprocessing safety
    import multiprocessing
    multiprocessing.freeze_support()
    main()
