"""launcher.py — RNativeLauncher: always-on supervisor for the R Native Worker.

Phase H.2 of r_desktop/ROADMAP.md (Algory-style parent+worker pattern):
  - Stays tiny; spawns the worker (r_native.app) via subprocess.Popen
  - Polls http://127.0.0.1:7711/heartbeat every poll_sec (default 10s)
  - Worker is DEAD if: process exited, OR heartbeat unreachable/stale 3
    consecutive polls, OR heartbeat reports wants_restart=true
  - On death: log, kill its OWN child tree only, respawn with exponential
    backoff, capped at max_restarts_per_hour (then halt + alert in log)
  - Tray icon via pystray+Pillow when installed; otherwise console mode
  - Status window: plain tkinter (pid / uptime / ram / restarts / hb age)
  - Rotating log: r_native_launcher/launcher.log (~500 KB)

Phase H.6: control RPC — line-JSON over TCP on 127.0.0.1:7712 (control_port).
  Commands: status | restart-worker | kill-worker | swap-check | quit.
  Tray menu actions route through it; external shells use --send.
Phase H.7: hot-swap — before every (re)spawn, if config worker_exe has a
  sibling `<name>.exe.new` (>1MB, size stable 1s), swap atomically:
  current → .bak, .new → current. Skipped in module-mode (worker_exe empty).

Usage:
    python -m r_native_launcher.launcher              # tray if available
    python -m r_native_launcher.launcher --console    # no tray
    python -m r_native_launcher.launcher --dry-run    # dummy sleep worker,
                                                      # health = process alive
    python -m r_native_launcher.launcher --send status       # RPC client
    python -m r_native_launcher.launcher --test-swap PATH    # swap check only
Config: r_native_launcher/launcher_config.json (created with defaults).
Nothing starts on import — only main() acts.
"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller (H.3): الإعداد واللوج بجوار الـEXE مباشرة (dist\RNative\) —
    # لا داخل _internal — وإلا يسقط للافتراضيّ ويشغّل نفسه بـ-m (خطأ code 2).
    PKG_DIR      = Path(sys.executable).resolve().parent
    PROJECT_ROOT = PKG_DIR.parent.parent if PKG_DIR.name.lower() == "rnative" else PKG_DIR
else:
    PKG_DIR      = Path(__file__).resolve().parent
    PROJECT_ROOT = PKG_DIR.parent
CONFIG_PATH  = PKG_DIR / "launcher_config.json"
LOG_PATH     = PKG_DIR / "launcher.log"

MAX_HB_MISSES = 3          # consecutive heartbeat misses => dead
BACKOFF_CAP_S = 60.0       # exponential backoff ceiling
DRY_RUN_CMD   = [sys.executable, "-c", "import time;time.sleep(999999)"]


def _default_worker_cmd() -> list[str]:
    """Prefer pythonw.exe next to the current interpreter (GUI worker, no console).
    Frozen (PyInstaller): default to RNativeWorker.exe beside this launcher —
    sys.executable is the launcher itself and `-m` would self-spawn (exit 2)."""
    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).with_name("RNativeWorker.exe")
        if worker.exists():
            return [str(worker)]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), "-m", "r_native.app"]


def default_config() -> dict:
    return {
        "worker_cmd":            _default_worker_cmd(),
        "heartbeat_url":         "http://127.0.0.1:7711/heartbeat",
        "poll_sec":              10,
        "restart_backoff_sec":   2,
        "max_restarts_per_hour": 6,
        "control_port":          7712,   # H.6 control RPC (127.0.0.1 only)
        "worker_exe":            "",     # H.7 hot-swap target; "" = module-mode
    }


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[launcher] bad config ({e}) — using defaults", file=sys.stderr)
    else:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def build_logger(console: bool) -> logging.Logger:
    log = logging.getLogger("rnative_launcher")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=500_000, backupCount=1, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


# ─── Supervisor ────────────────────────────────────────────────────────
class WorkerSupervisor:
    """Owns exactly one worker subprocess; never touches other processes."""

    def __init__(self, cfg: dict, log: logging.Logger, dry_run: bool = False):
        self.log        = log
        self.dry_run    = dry_run
        self.worker_cmd = DRY_RUN_CMD if dry_run else list(cfg["worker_cmd"])
        self.hb_url     = str(cfg["heartbeat_url"])
        self.poll_sec   = max(1.0, float(cfg["poll_sec"]))
        self.backoff0   = max(0.5, float(cfg["restart_backoff_sec"]))
        self.max_rph    = max(1, int(cfg["max_restarts_per_hour"]))
        self.worker_exe = str(cfg.get("worker_exe") or "")

        self.proc: subprocess.Popen | None = None
        self.hb_misses      = 0
        self.last_hb: dict  = {}
        self.last_hb_ts     = 0.0
        self.restart_times: deque[float] = deque()
        self.restart_count  = 0
        self.spawn_attempt  = 0
        self.last_spawn_ts  = 0.0
        self.halted         = False   # restart cap hit — needs manual Restart
        self.suspended      = False   # user chose Kill Worker
        self._stop          = threading.Event()
        self._lock          = threading.RLock()

    # -- lifecycle ------------------------------------------------------
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self) -> bool:
        with self._lock:
            if self.is_alive():
                return True
            res = check_hot_swap(self.worker_exe, self.log)   # H.7: before EVERY spawn
            if res["swap"] not in ("none", "skipped"):
                self.log.info("hot-swap check: %s", res)
            self.log.info("spawning worker: %s", " ".join(self.worker_cmd))
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                self.proc = subprocess.Popen(
                    self.worker_cmd, cwd=str(PROJECT_ROOT), creationflags=flags,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                self.log.error("spawn FAILED: %s", e)
                self.proc = None
                return False
            self.hb_misses     = 0
            self.last_spawn_ts = time.time()
            self.log.info("worker up: PID %s", self.proc.pid)
            return True

    def _kill_tree(self) -> None:
        """Kill our own child (and its descendants) — never other pythons."""
        if self.proc is None:
            return
        pid = self.proc.pid
        if self.proc.poll() is None:
            try:
                import psutil
                root = psutil.Process(pid)
                kids = root.children(recursive=True)
                for p in kids + [root]:
                    try: p.kill()
                    except Exception: pass
                psutil.wait_procs(kids + [root], timeout=5)
                self.log.info("killed worker tree PID %s (+%d children)", pid, len(kids))
            except Exception:
                try:
                    self.proc.kill(); self.proc.wait(timeout=5)
                    self.log.info("killed worker PID %s", pid)
                except Exception as e:
                    self.log.error("kill error on PID %s: %s", pid, e)
        self.proc = None

    def kill_worker(self, graceful: bool = True) -> None:
        with self._lock:
            if not self.is_alive():
                self.proc = None
                return
            if graceful and not self.dry_run:
                try:
                    url = self.hb_url.replace("/heartbeat", "/shutdown")
                    req = urllib.request.Request(url, method="POST")
                    urllib.request.urlopen(req, timeout=2).read()
                    self.log.info("sent graceful POST /shutdown to PID %s", self.proc.pid)
                    for _ in range(40):                       # up to 8s
                        if self.proc.poll() is not None:
                            self.log.info("worker exited cleanly")
                            self.proc = None
                            return
                        time.sleep(0.2)
                    self.log.warning("worker ignored /shutdown — force-killing")
                except Exception as e:
                    self.log.warning("graceful shutdown failed (%s) — force-killing", e)
            self._kill_tree()

    # -- health ---------------------------------------------------------
    def poll_heartbeat(self) -> dict | None:
        try:
            timeout = min(self.poll_sec * 0.5, 5.0)
            with urllib.request.urlopen(self.hb_url, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            self.hb_misses  = 0
            self.last_hb    = data
            self.last_hb_ts = time.time()
            return data
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            self.hb_misses += 1
            return None

    def tick(self) -> None:
        """One supervision cycle: check health, restart on death."""
        with self._lock:
            if self._stop.is_set() or self.halted or self.suspended:
                return
            # healthy long enough => reset backoff ladder
            if self.is_alive() and time.time() - self.last_spawn_ts > 60:
                self.spawn_attempt = 0

            if self.proc is not None and self.proc.poll() is not None:
                self._on_death(f"process exited (code {self.proc.returncode})")
                return
            if self.proc is None:
                self._on_death("no worker process")
                return
            if self.dry_run:                     # health = process alive
                return
            data = self.poll_heartbeat()
            if data is None:
                self.log.warning("heartbeat miss %d/%d", self.hb_misses, MAX_HB_MISSES)
                if self.hb_misses >= MAX_HB_MISSES:
                    self._on_death(f"heartbeat unreachable {self.hb_misses}x — worker wedged")
            elif data.get("wants_restart"):
                self._on_death("worker requested restart (wants_restart=true)", graceful=True)

    def _on_death(self, reason: str, graceful: bool = False) -> None:
        self.log.warning("worker DEAD: %s", reason)
        self.kill_worker(graceful=graceful)
        now = time.time()
        while self.restart_times and now - self.restart_times[0] > 3600:
            self.restart_times.popleft()
        if len(self.restart_times) >= self.max_rph:
            self.halted = True
            self.log.critical("RESTART CAP HIT: %d restarts in the last hour "
                              "(max %d) — supervision HALTED. Use Restart Worker "
                              "to resume.", len(self.restart_times), self.max_rph)
            return
        backoff = min(self.backoff0 * (2 ** self.spawn_attempt), BACKOFF_CAP_S)
        self.spawn_attempt += 1
        self.log.info("respawn in %.1fs (attempt %d)", backoff, self.spawn_attempt)
        if self._stop.wait(backoff):
            return
        if self.spawn():
            self.restart_times.append(time.time())
            self.restart_count += 1
            self.log.info("RESTART OK — worker respawned (restart #%d)", self.restart_count)

    # -- user actions (tray menu / status window) ------------------------
    def action_restart(self) -> None:
        self.log.info("user action: Restart Worker")
        self.halted = self.suspended = False
        self.restart_times.clear()
        self.spawn_attempt = 0
        if self.is_alive() and not self.dry_run:
            try:
                url = self.hb_url.replace("/heartbeat", "/restart")
                urllib.request.urlopen(
                    urllib.request.Request(url, method="POST"), timeout=2).read()
            except Exception:
                pass
        self.kill_worker(graceful=True)
        self.spawn()

    def action_kill(self) -> None:
        self.log.info("user action: Kill Worker (supervision suspended)")
        self.suspended = True
        self.kill_worker(graceful=True)

    def shutdown(self) -> None:
        with self._lock:
            if getattr(self, "_shutdown_done", False):
                return
            self._shutdown_done = True
        self._stop.set()
        self.log.info("launcher shutting down — stopping worker")
        self.kill_worker(graceful=True)
        self.log.info("launcher exit clean")

    # -- reporting --------------------------------------------------------
    def status(self) -> dict:
        return {
            "alive":         self.is_alive(),
            "pid":           self.proc.pid if self.is_alive() else None,
            "uptime_sec":    self.last_hb.get("uptime_sec"),
            "ram_mb":        self.last_hb.get("ram_mb"),
            "restart_count": self.restart_count,
            "hb_age_s":      round(time.time() - self.last_hb_ts, 1) if self.last_hb_ts else None,
            "hb_misses":     self.hb_misses,
            "halted":        self.halted,
            "suspended":     self.suspended,
        }

    def loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                self.log.error("tick error: %s", e)
            self._stop.wait(self.poll_sec)


# ─── H.7: hot-swap (atomic .exe.new replacement) ─────────────────────────
def check_hot_swap(worker_exe: str, log: logging.Logger) -> dict:
    """If `<worker_exe>.new` exists and is valid, atomically swap it in.

    Validate: exists, >1MB, size stable across 2 checks 1s apart.
    Swap: current → `<name>.exe.bak` (replacing older .bak), .new → current.
    Module-mode (worker_exe empty) skips entirely.
    """
    if not worker_exe:
        return {"swap": "skipped", "reason": "module-mode (no worker_exe)"}
    cur = Path(worker_exe)
    new = cur.with_name(cur.name + ".new")
    if not new.exists():
        return {"swap": "none", "reason": f"no {new.name}"}
    try:
        s1 = new.stat().st_size
        if s1 < 1_000_000:
            log.warning("hot-swap REJECTED: %s too small (%d B < 1 MB)", new.name, s1)
            return {"swap": "rejected", "reason": f"{new.name} too small ({s1} B < 1 MB)"}
        time.sleep(1.0)                               # still growing?
        s2 = new.stat().st_size
        if s2 != s1:
            log.warning("hot-swap DEFERRED: %s still growing (%d → %d B)", new.name, s1, s2)
            return {"swap": "deferred", "reason": f"{new.name} still growing ({s1} → {s2} B)"}
        bak = cur.with_name(cur.name + ".bak")
        old_size = cur.stat().st_size if cur.exists() else 0
        if cur.exists():
            if bak.exists():
                bak.unlink()                          # keep only the latest .bak
            cur.rename(bak)
        new.rename(cur)
        log.info("HOT-SWAP OK: %s (%d B) → %s (old %d B kept as %s)",
                 new.name, s2, cur.name, old_size, bak.name)
        return {"swap": "done", "exe": str(cur), "new_size": s2,
                "old_size": old_size, "bak": str(bak)}
    except Exception as e:
        log.error("hot-swap FAILED: %s", e)
        return {"swap": "error", "reason": str(e)}


# ─── H.6: control RPC (line-JSON over TCP, 127.0.0.1 only) ───────────────
RPC_CMDS = ("status", "restart-worker", "kill-worker", "swap-check", "quit")

def send_command(cmd: str, port: int, timeout: float = 20.0) -> dict:
    """RPC client: one line-JSON request → one line-JSON response."""
    with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as s:
        s.sendall((json.dumps({"cmd": cmd}) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8", "replace").strip() or "{}")


class ControlServer:
    """Accepts line-JSON commands; every request handled in its own thread
    so the tray/UI loop is never blocked."""

    def __init__(self, sup: WorkerSupervisor, port: int, log: logging.Logger):
        self.sup, self.port, self.log = sup, int(port), log
        self.on_quit = None                     # set by the active front-end
        self._srv: socket.socket | None = None

    def start(self) -> bool:
        try:
            self._srv = socket.create_server(("127.0.0.1", self.port))
        except OSError as e:
            self.log.error("control RPC bind FAILED on 127.0.0.1:%d (%s) — "
                           "tray falls back to direct calls", self.port, e)
            return False
        threading.Thread(target=self._accept_loop, name="control-rpc", daemon=True).start()
        self.log.info("control RPC listening on 127.0.0.1:%d", self.port)
        return True

    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return                          # socket closed on shutdown
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5)
            buf = b""
            while b"\n" not in buf and len(buf) < 4096:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                buf += chunk
            try:
                cmd = str(json.loads(buf.decode("utf-8", "replace").strip() or "{}").get("cmd", ""))
            except ValueError:
                cmd = ""
            conn.sendall((json.dumps(self._dispatch(cmd)) + "\n").encode("utf-8"))
        except Exception as e:
            self.log.error("control RPC handler error: %s", e)
        finally:
            try: conn.close()
            except Exception: pass

    def stop(self) -> None:
        if self._srv is not None:
            try: self._srv.close()
            except Exception: pass
            self._srv = None

    def _dispatch(self, cmd: str) -> dict:
        self.log.info("control RPC command: %s", cmd or "(empty)")
        if cmd == "status":
            return {"ok": True, "cmd": cmd, **self.sup.status()}
        if cmd == "restart-worker":
            self.sup.action_restart()
            return {"ok": True, "cmd": cmd, **self.sup.status()}
        if cmd == "kill-worker":
            self.sup.action_kill()
            return {"ok": True, "cmd": cmd, **self.sup.status()}
        if cmd == "swap-check":
            return {"ok": True, "cmd": cmd, **check_hot_swap(self.sup.worker_exe, self.log)}
        if cmd == "quit":
            threading.Timer(0.2, self.on_quit or self.sup.shutdown).start()
            return {"ok": True, "cmd": cmd, "quitting": True}
        return {"ok": False, "error": f"unknown cmd {cmd!r}", "known": list(RPC_CMDS)}


# ─── Status window (tkinter, hide-on-close) ─────────────────────────────
_STATUS = {"thread": None, "show": threading.Event()}

def show_status_window(sup: WorkerSupervisor) -> None:
    _STATUS["show"].set()
    t = _STATUS["thread"]
    if t is not None and t.is_alive():
        return                                     # window thread re-shows itself
    def _run():
        import tkinter as tk
        root = tk.Tk()
        root.title("R Native Launcher")
        root.geometry("320x190")
        root.attributes("-topmost", True)
        root.configure(bg="#0d0824")
        rows = ["state", "pid", "uptime", "ram", "restarts", "hb_age"]
        labels: dict[str, tk.Label] = {}
        tk.Label(root, text="R NATIVE · WORKER SUPERVISOR", bg="#0d0824",
                 fg="#fbbf24", font=("Consolas", 10, "bold")).pack(pady=(10, 6))
        for k in rows:
            labels[k] = tk.Label(root, text="—", anchor="w", bg="#0d0824",
                                 fg="#94a3b8", font=("Consolas", 9), width=40)
            labels[k].pack(padx=14)
        def on_close():
            _STATUS["show"].clear()
            root.withdraw()                        # hide, don't exit
        root.protocol("WM_DELETE_WINDOW", on_close)
        def refresh():
            if _STATUS["show"].is_set() and root.state() == "withdrawn":
                root.deiconify()
            st = sup.status()
            state = ("HALTED (restart cap)" if st["halted"] else
                     "SUSPENDED (killed)" if st["suspended"] else
                     "ALIVE" if st["alive"] else "DOWN — respawning")
            labels["state"].config(text=f"state:    {state}",
                                   fg="#10b981" if st["alive"] else "#ef4444")
            labels["pid"].config(text=f"pid:      {st['pid'] or '—'}")
            u = st["uptime_sec"]
            labels["uptime"].config(text=f"uptime:   {int(u)}s" if u else "uptime:   —")
            labels["ram"].config(text=f"ram:      {st['ram_mb'] or '—'} MB")
            labels["restarts"].config(text=f"restarts: {st['restart_count']}")
            a = st["hb_age_s"]
            labels["hb_age"].config(
                text=f"hb age:   {a}s (misses {st['hb_misses']})" if a is not None else "hb age:   —")
            root.after(2000, refresh)              # refresh every 2s
        refresh()
        root.mainloop()
    _STATUS["thread"] = threading.Thread(target=_run, name="status-window", daemon=True)
    _STATUS["thread"].start()


# ─── Front-ends ─────────────────────────────────────────────────────────
def run_console(sup: WorkerSupervisor, run_seconds: float | None = None) -> None:
    sup.log.info("console mode (poll every %.1fs)", sup.poll_sec)
    sup.spawn()
    t0 = time.time()
    try:
        while not sup._stop.is_set():
            sup.tick()
            if run_seconds and time.time() - t0 >= run_seconds:
                sup.log.info("--run-seconds %.0f reached", run_seconds)
                break
            sup._stop.wait(sup.poll_sec)
    except KeyboardInterrupt:
        sup.log.info("Ctrl+C received")
    sup.shutdown()


def run_tray(sup: WorkerSupervisor, ctl: ControlServer | None = None) -> None:
    import pystray                                  # availability pre-checked
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), (13, 8, 36))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 56, 56], outline=(251, 191, 36), width=4)
    d.text((24, 18), "R", fill=(251, 191, 36))
    def _bg(fn):                                    # every action non-blocking
        return lambda icon=None, item=None: threading.Thread(target=fn, daemon=True).start()
    def _rpc(cmd, fallback):                        # H.6: tray routes via TCP RPC
        def _r():
            try:
                sup.log.info("tray → RPC %s: %s", cmd, send_command(cmd, ctl.port))
            except Exception as e:
                sup.log.warning("tray RPC %s failed (%s) — direct call", cmd, e)
                fallback()
        return _bg(_r) if ctl and ctl._srv else _bg(fallback)
    def _quit(icon, item=None):
        sup.shutdown()
        icon.stop()
    icon = pystray.Icon("rnative_launcher", img, "R Native — Worker Supervisor",
        menu=pystray.Menu(
            pystray.MenuItem("Status",         _bg(lambda: show_status_window(sup))),
            pystray.MenuItem("Restart Worker", _rpc("restart-worker", sup.action_restart)),
            pystray.MenuItem("Kill Worker",    _rpc("kill-worker",    sup.action_kill)),
            pystray.MenuItem("Quit Launcher",  _quit)))
    if ctl:
        ctl.on_quit = lambda: (sup.shutdown(), icon.stop())
    sup.spawn()
    threading.Thread(target=sup.loop, name="supervisor-loop", daemon=True).start()
    sup.log.info("tray mode active")
    icon.run()                                      # blocks until Quit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="r_native_launcher.launcher",
                                 description="Supervisor for the R Native worker")
    ap.add_argument("--console", action="store_true", help="no tray icon")
    ap.add_argument("--dry-run", action="store_true",
                    help="spawn a dummy sleep worker; health = process alive")
    ap.add_argument("--poll-sec", type=float, default=None, help="override poll interval")
    ap.add_argument("--run-seconds", type=float, default=None,
                    help="(debug) auto-exit after N seconds, console mode only")
    ap.add_argument("--send", metavar="CMD", choices=RPC_CMDS, default=None,
                    help="RPC client: send CMD to a running launcher, print the "
                         "JSON response, exit (H.6)")
    ap.add_argument("--test-swap", nargs="?", const="", default=None, metavar="PATH",
                    help="run ONLY the hot-swap check against PATH (or the config "
                         "worker_exe when omitted), print result, exit (H.7)")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.poll_sec:
        cfg["poll_sec"] = args.poll_sec

    if args.send:                                   # H.6: RPC client mode
        port = int(cfg["control_port"])
        try:
            resp = send_command(args.send, port)
        except Exception as e:
            print(json.dumps({"ok": False, "error":
                              f"no launcher on 127.0.0.1:{port} ({e})"}))
            return 1
        print(json.dumps(resp, indent=2))
        return 0 if resp.get("ok") else 1

    log = build_logger(console=True)

    if args.test_swap is not None:                  # H.7: swap check only
        target = args.test_swap or str(cfg.get("worker_exe") or "")
        res = check_hot_swap(target, log)
        print(json.dumps(res, indent=2))
        return 0 if res["swap"] in ("done", "none", "skipped") else 1

    log.info("=" * 60)
    log.info("RNativeLauncher starting (dry_run=%s console=%s)", args.dry_run, args.console)

    # Safety: never double-spawn against a live R Native worker.
    if not args.dry_run:
        try:
            urllib.request.urlopen(cfg["heartbeat_url"], timeout=1).read()
            log.critical("a worker already answers %s — refusing to spawn a second "
                         "one. Close it (or its launcher) first.", cfg["heartbeat_url"])
            return 2
        except Exception:
            pass

    sup = WorkerSupervisor(cfg, log, dry_run=args.dry_run)
    ctl = ControlServer(sup, cfg["control_port"], log)   # H.6: RPC server
    ctl.start()

    tray_ok = False
    if not args.console:
        try:
            import pystray  # noqa: F401
            import PIL      # noqa: F401
            tray_ok = True
        except ImportError:
            log.warning("pystray/Pillow not installed — falling back to console mode")

    if tray_ok:
        run_tray(sup, ctl)
    else:
        run_console(sup, run_seconds=args.run_seconds)
    ctl.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
