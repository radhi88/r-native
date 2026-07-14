"""launcher.py — single-entry supervisor for the FRIDAY R Factory stack.

Brings up everything in staged order, probes health, and keeps services alive.
Replaces the old dist/RNative_launcher.bat which only started the UI.

Stages:
  0. Setup       — ensure data dirs exist; kill any stale R-Factory processes
  1. Brain       — start brain_server, wait until /api/r/executor responds
  2. Executor    — start r_executor in LIVE mode (or PAPER via --paper)
  3. Daemons     — start lineage, asymmetry, monster scanners
  4. Bootstrap   — (optional) full GA scan for symbols missing genomes
  5. UI          — start R Native desktop window
  6. Supervise   — heartbeat loop, auto-restart anything that died

Usage (double-click RNative.bat, or from PowerShell):
  python -m r_native.launcher                          # default LIVE, no bootstrap
  python -m r_native.launcher --paper                  # PAPER mode
  python -m r_native.launcher --bootstrap              # run GA scan first
  python -m r_native.launcher --skip-ui                # headless (no window)
  python -m r_native.launcher --stop                   # clean shutdown of everything
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
TMP  = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Temp"
PID_FILE = ROOT / "data" / "launcher_pids.json"
DATA_DIRS = [
    ROOT / "data" / "r_native" / "symbol_configs",
    ROOT / "data" / "r_native" / "hall_of_fame" / "by_symbol",
    ROOT / "data" / "r_native" / "symbol_learning",
    ROOT / "data" / "r_native" / "decision_log",
]
BRAIN_URL = "http://localhost:5055/api/r/executor"

# Each service: (name, [argv], log file basename)
SERVICES = [
    ("brain",     [sys.executable, "-u", "brain_server.py"],
                  "brain_server.log"),
    ("executor",  [sys.executable, "-u", "-m", "friday_v3.algory.r_executor",
                   "--live", "--no-brain-json", "--interval", "8"],
                  "r_solo.log"),
    ("lineage",   [sys.executable, "-u", "-m", "r_native.genome_lineage",
                   "--daemon", "--interval-min", "15",
                   "--children-per-parent", "4", "--n-bars", "3000"],
                  "daemon_lineage.log"),
    ("asymmetry", [sys.executable, "-u", "-m", "r_native.genome_asymmetry",
                   "daemon", "--interval-min", "5"],
                  "daemon_asymmetry.log"),
    ("monster",   [sys.executable, "-u", "-m", "r_native.monster_genome",
                   "daemon", "--interval-min", "5"],
                  "daemon_monster.log"),
    ("contender", [sys.executable, "-u", "-m", "r_native.genome_contender",
                   "daemon", "--interval-min", "5"],
                  "daemon_contender.log"),
    ("autoga",    [sys.executable, "-u", "-m", "r_native.auto_ga_daemon",
                   "--daemon", "--interval-min", "15"],
                  "daemon_autoga.log"),
    ("ui",        [sys.executable, "-u", "-m", "r_native.app"],
                  "r_native_ui.log"),
]


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────

def _print(stage: str, msg: str, ok: bool | None = None) -> None:
    """One-line status with a stage prefix."""
    sym = " " if ok is None else ("✓" if ok else "✗")
    ts  = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sym} {stage:10s}  {msg}", flush=True)


def _load_pids() -> dict:
    if not PID_FILE.exists(): return {}
    try: return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception: return {}


def _save_pids(pids: dict) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def _kill_pid(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 9)
        return True
    except Exception:
        return False


def _svc_marker(argv: list[str]) -> str | None:
    """Distinctive token identifying the service's program, for cmdline
    cross-checks. For `-m pkg.mod` it's the module path; otherwise the
    script filename (e.g. brain_server.py)."""
    try:
        if "-m" in argv:
            i = argv.index("-m")
            return argv[i + 1] if i + 1 < len(argv) else None
        for tok in reversed(argv):
            if tok.endswith(".py"):
                return os.path.basename(tok)
    except Exception:
        pass
    return None


def _is_alive(pid: int, expect: str | None = None) -> bool:
    """Exact liveness check. Verifies the PID exists *and* (when `expect`
    is given) that the running process's command line still contains the
    expected program marker — so a recycled PID running an unrelated
    program is NOT counted as the service.

    Avoids substring-matching tasklist output (e.g. PID 1596 matching
    15968) by comparing the PID field exactly via psutil."""
    if not pid: return False
    try:
        import psutil  # available in venv; imported lazily
        if not psutil.pid_exists(pid):
            return False
        if expect is None:
            return True
        try:
            cmdline = " ".join(psutil.Process(pid).cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        norm = cmdline.replace("\\", ".").replace("/", ".")
        marker = expect.replace("\\", ".").replace("/", ".")
        return marker in norm
    except ImportError:
        # Fallback: exact PID-field match on tasklist CSV (no header,
        # so no substring bleed across columns).
        try:
            if sys.platform == "win32":
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5)
                for line in (r.stdout or "").splitlines():
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) == pid:
                        return True
                return False
            else:
                os.kill(pid, 0); return True
        except Exception:
            return False
    except Exception:
        return False


def _http_ping(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _find_stale_processes() -> list[tuple[int, str]]:
    """Walk all python.exe processes and find ones running our modules."""
    if sys.platform != "win32": return []
    try:
        r = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='pythonw.exe'",
             "get", "ProcessId,CommandLine", "/FORMAT:LIST"],
            capture_output=True, text=True, timeout=8)
        out = []
        cur_pid, cur_cmd = None, None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("CommandLine="):
                cur_cmd = line[12:]
            elif line.startswith("ProcessId="):
                try: cur_pid = int(line[10:])
                except: cur_pid = None
                if cur_pid and cur_cmd and any(
                    k in cur_cmd for k in (
                        "brain_server", "r_executor", "r_native.app",
                        "r_native\\app", "genome_lineage", "genome_asymmetry",
                        "monster_genome",
                    )):
                    out.append((cur_pid, cur_cmd))
                cur_pid, cur_cmd = None, None
        return out
    except Exception:
        return []


# ───────────────────────────────────────────────────────────────────────
# Stage 0: setup
# ───────────────────────────────────────────────────────────────────────

def stage_setup() -> None:
    _print("setup", "ensuring data directories…")
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    _print("setup", f"all {len(DATA_DIRS)} dirs present", ok=True)

    stale = _find_stale_processes()
    if stale:
        _print("setup", f"killing {len(stale)} stale R-Factory process(es)")
        for pid, _ in stale:
            _kill_pid(pid)
        time.sleep(2)
        _print("setup", "stale processes cleared", ok=True)
    else:
        _print("setup", "no stale processes", ok=True)


# ───────────────────────────────────────────────────────────────────────
# Stage 1-5: launch services
# ───────────────────────────────────────────────────────────────────────

def _spawn(name: str, argv: list[str], log_basename: str,
           hidden: bool = True) -> int | None:
    log_path = TMP / log_basename
    err_path = TMP / log_basename.replace(".log", "_err.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Always bypass session/weekend for autonomous-mode trading
    env["R_BYPASS_SESSION"] = "1"
    env["R_BYPASS_WEEKEND"] = "1"
    env["R_BYPASS_FRIDAY"]  = "1"
    creationflags = 0
    if sys.platform == "win32" and hidden:
        creationflags = 0x00000008 | 0x00000200    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        with open(log_path, "ab") as out_f, open(err_path, "ab") as err_f:
            p = subprocess.Popen(argv, cwd=str(ROOT),
                                  stdout=out_f, stderr=err_f,
                                  env=env, creationflags=creationflags,
                                  close_fds=True)
        return p.pid
    except Exception as e:
        _print(name, f"spawn failed: {e}", ok=False)
        return None


def stage_brain() -> int | None:
    pid = _spawn("brain", SERVICES[0][1], SERVICES[0][2])
    if not pid:
        _print("brain", "could not spawn", ok=False); return None
    _print("brain", f"spawned pid={pid}, probing /api/r/executor…")
    for _ in range(30):  # up to 30s
        if _http_ping(BRAIN_URL):
            _print("brain", "responsive", ok=True); return pid
        time.sleep(1)
    _print("brain", "no response after 30s (still spawned, may need more time)",
           ok=False)
    return pid


def stage_executor() -> int | None:
    # DISABLED 2026-06-26: algory r_executor (magic 20260605) bleeds — 30d audit
    # n27 net -$86.35 win 14% (worst engine by win-asymmetry). Do NOT relaunch LIVE.
    # Re-enable by restoring the two _spawn lines below.
    _print("executor", "DISABLED (magic 20260605 bleeder) — not started", ok=False)
    return None
    # pid = _spawn("executor", SERVICES[1][1], SERVICES[1][2])
    # if pid: _print("executor", f"LIVE pid={pid}", ok=True)
    # return pid


DAEMON_NAMES = ("lineage", "asymmetry", "monster", "contender", "autoga")


def stage_daemons() -> dict[str, int]:
    out = {}
    for name in DAEMON_NAMES:
        svc = next((s for s in SERVICES if s[0] == name), None)
        if not svc:
            _print(name, "service not registered", ok=False); continue
        _, argv, log = svc
        pid = _spawn(name, argv, log)
        if pid:
            out[name] = pid
            _print(name, f"daemon pid={pid}", ok=True)
        else:
            _print(name, "spawn failed", ok=False)
    return out


def stage_ui() -> int | None:
    svc = next((s for s in SERVICES if s[0] == "ui"), None)
    if not svc: return None
    pid = _spawn("ui", svc[1], svc[2], hidden=False)
    if pid: _print("ui", f"window spawned pid={pid}", ok=True)
    return pid


# ───────────────────────────────────────────────────────────────────────
# Stage 4 (optional): bootstrap GA scan
# ───────────────────────────────────────────────────────────────────────

def stage_bootstrap(max_symbols: int = 15) -> None:
    """Run a single full_scan to fill in symbol_configs for the top N symbols.
    This trains archetype-based stats per (symbol × timeframe × archetype) and
    writes them into symbol_configs so the gate has real fallback data.

    Note: this is the ALGORY-style scan (not the GA campaign). It doesn't
    produce genomes, only ranks the 4 hardcoded archetypes per TF. The full
    GA campaign (genome evolution) is launched from the R Native UI's
    🧪 CAMPAIGN tab — too long-running for an auto-launcher.
    """
    _print("bootstrap", f"scanning top {max_symbols} symbols × 4 TFs × 4 archetypes…")
    try:
        from r_native.scanner import full_scan, update_symbol_configs_from_scan
        from friday_v3.algory.r_multi_symbol import rank_symbols
        import MetaTrader5 as mt5
        if not mt5.initialize():
            _print("bootstrap", "MT5 init failed", ok=False); return
        ranking = rank_symbols(max_symbols=max_symbols)
        symbols = [c["symbol"] for c in (ranking.get("candidates") or [])][:max_symbols]
        if not symbols:
            _print("bootstrap", "no symbols to scan", ok=False); return
        _print("bootstrap", f"symbols: {', '.join(symbols)}")
        summary = full_scan(symbols=symbols, n_bars=3000,
                            progress_cb=lambda s: _print("bootstrap", s))
        if summary.get("ok") is not False:
            update_symbol_configs_from_scan(summary)
            _print("bootstrap", f"updated symbol_configs ({len(symbols)} files)",
                   ok=True)
    except Exception as e:
        _print("bootstrap", f"failed: {e}", ok=False)


# ───────────────────────────────────────────────────────────────────────
# Supervise loop
# ───────────────────────────────────────────────────────────────────────

# Crash-loop backoff / circuit-breaker tuning ──────────────────────────
# A service that dies repeatedly is respawned with an exponentially growing
# delay. If it crashes more than CRASH_MAX times inside CRASH_WINDOW_S it is
# tripped (paused) until the window rolls over, so we stop hammering MT5 /
# reloading genomes every few seconds and surface a loud alert instead.
CRASH_WINDOW_S   = 600       # 10-minute sliding window
CRASH_MAX        = 5         # trips the breaker after this many crashes/window
BACKOFF_BASE_S   = 5         # first restart waits this long
BACKOFF_CAP_S    = 300       # never wait more than 5 min between restarts


def _tail_err(log_basename: str, n: int = 12) -> str:
    """Return the last n non-blank lines of a service's stderr log, if any."""
    err_path = TMP / log_basename.replace(".log", "_err.log")
    try:
        if not err_path.exists():
            return ""
        lines = err_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = [ln for ln in lines if ln.strip()][-n:]
        return "\n".join(tail)
    except Exception:
        return ""


def supervise(pids: dict[str, int], poll_s: int = 15) -> None:
    """Heartbeat loop: check every service, respawn if it died.

    Respawns are governed by exponential backoff + a per-service crash-rate
    circuit breaker so a hard-crashing worker (e.g. the Qt 0xFFFFFFFF UI
    crash) can no longer churn in a tight loop. Exits on Ctrl+C with a clean
    shutdown via stop_all()."""
    _print("supervise", f"heartbeat every {poll_s}s — Ctrl+C to stop")
    # Per-service crash bookkeeping.
    crash_times: dict[str, list[float]] = {}   # name -> [death timestamps]
    next_retry_at: dict[str, float] = {}        # name -> earliest respawn time
    tripped: dict[str, bool] = {}               # name -> breaker engaged?
    while True:
        try:
            time.sleep(poll_s)
            now = time.time()
            for name, pid in list(pids.items()):
                _svc = next((s for s in SERVICES if s[0] == name), None)
                _marker = _svc_marker(_svc[1]) if _svc else None
                if pid and _is_alive(pid, _marker):
                    # Healthy: clear any tripped breaker so it can recover
                    # cleanly once it has been stable again.
                    if tripped.get(name):
                        _print(name, "recovered — clearing crash breaker", ok=True)
                        tripped[name] = False
                        crash_times[name] = []
                        next_retry_at.pop(name, None)
                    continue

                # Record this death in the sliding window.
                hist = [t for t in crash_times.get(name, [])
                        if now - t < CRASH_WINDOW_S]
                hist.append(now)
                crash_times[name] = hist
                n_crashes = len(hist)

                err_tail = _tail_err(next(s[2] for s in SERVICES if s[0] == name))

                # Circuit breaker: too many crashes in the window → pause.
                if n_crashes > CRASH_MAX:
                    if not tripped.get(name):
                        tripped[name] = True
                        _print(name,
                               f"CRASH-LOOP TRIPPED — {n_crashes} crashes in "
                               f"<{CRASH_WINDOW_S//60}min. Pausing respawns "
                               f"until rate drops. INVESTIGATE.", ok=False)
                        if err_tail:
                            _print(name, f"last stderr:\n{err_tail}", ok=False)
                    continue

                # Exponential backoff between restarts.
                delay = min(BACKOFF_CAP_S,
                            BACKOFF_BASE_S * (2 ** (n_crashes - 1)))
                ready_at = next_retry_at.get(name, 0)
                if now < ready_at:
                    continue  # still cooling down from the previous restart
                if name not in next_retry_at and delay > 0:
                    # First time we notice this death: schedule the backoff,
                    # log it (with stderr), then respawn on the next pass.
                    next_retry_at[name] = now + delay
                    _print(name,
                           f"DIED (pid={pid}) — crash #{n_crashes}, "
                           f"backing off {delay}s before respawn", ok=False)
                    if err_tail:
                        _print(name, f"last stderr:\n{err_tail}", ok=False)
                    continue

                # Backoff elapsed → respawn.
                svc = next(s for s in SERVICES if s[0] == name)
                new_pid = _spawn(name, svc[1], svc[2],
                                  hidden=(name != "ui"))
                next_retry_at.pop(name, None)
                if new_pid:
                    pids[name] = new_pid
                    _save_pids(pids)
                    _print(name, f"respawned pid={new_pid} "
                                 f"(crash #{n_crashes}/{CRASH_MAX})", ok=True)
            # Periodic brain ping
            if not _http_ping(BRAIN_URL):
                _print("brain", "/api unresponsive — leaving to next cycle",
                       ok=False)
        except KeyboardInterrupt:
            _print("supervise", "shutdown signal received")
            stop_all()
            return


def stop_all() -> None:
    """Kill every spawned service."""
    pids = _load_pids()
    if not pids:
        # Fall back to scanning
        stale = _find_stale_processes()
        for pid, _ in stale:
            _kill_pid(pid)
        _print("stop", f"killed {len(stale)} processes (scanned)", ok=True)
        return
    n = 0
    for name, pid in pids.items():
        _svc = next((s for s in SERVICES if s[0] == name), None)
        _marker = _svc_marker(_svc[1]) if _svc else None
        if pid and _is_alive(pid, _marker):
            _kill_pid(pid); n += 1
            _print("stop", f"killed {name} pid={pid}", ok=True)
    PID_FILE.unlink(missing_ok=True)
    _print("stop", f"shutdown complete ({n} processes)", ok=True)


# ───────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="r_native.launcher")
    ap.add_argument("--paper", action="store_true",
                    help="run executor in PAPER mode (no real orders)")
    ap.add_argument("--bootstrap", action="store_true",
                    help="run a full archetype scan for top symbols before starting daemons")
    ap.add_argument("--bootstrap-symbols", type=int, default=15,
                    help="how many top symbols to bootstrap-scan (default 15)")
    ap.add_argument("--skip-ui", action="store_true",
                    help="don't open the desktop window (headless)")
    ap.add_argument("--no-supervise", action="store_true",
                    help="exit after starting (don't restart-on-crash)")
    ap.add_argument("--stop", action="store_true",
                    help="cleanly kill every R-Factory process and exit")
    args = ap.parse_args()

    if args.stop:
        stop_all()
        return

    # Swap executor mode if --paper
    if args.paper:
        SERVICES[1] = ("executor",
                       [sys.executable, "-u", "-m", "friday_v3.algory.r_executor",
                        "--no-brain-json", "--interval", "8"],
                       "r_solo.log")

    print("=" * 60)
    print("  FRIDAY  R Factory  —  Master Launcher")
    print("=" * 60)

    stage_setup()
    pids = {}

    pid = stage_brain()
    if pid: pids["brain"] = pid

    # Seed all top-30 symbols BEFORE executor starts so first trades have genomes
    _print("seed", "bootstrapping deployed_genome for top 30 symbols…")
    try:
        from r_native.genome_seeder import bootstrap_all_top_symbols
        r = bootstrap_all_top_symbols(30)
        _print("seed", f"checked={r.get('checked')} seeded={r.get('seeded')} "
                        f"already={r.get('already')}", ok=True)
    except Exception as e:
        _print("seed", f"failed: {e}", ok=False)

    pid = stage_executor()
    if pid: pids["executor"] = pid

    pids.update(stage_daemons())

    if args.bootstrap:
        stage_bootstrap(max_symbols=args.bootstrap_symbols)

    if not args.skip_ui:
        pid = stage_ui()
        if pid: pids["ui"] = pid

    _save_pids(pids)

    print("=" * 60)
    print(f"  ALL UP — {len(pids)} services running")
    print(f"    brain   : http://localhost:5055/r/")
    print(f"    pids    : {PID_FILE}")
    print(f"    logs    : {TMP}")
    print("=" * 60)

    if args.no_supervise:
        _print("done", "exiting without supervise — services keep running")
        return
    supervise(pids)


if __name__ == "__main__":
    main()
