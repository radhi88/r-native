"""
friday_health_monitor.py
------------------------
مراقب شامل لجميع عمليات FRIDAY.

يقوم بـ:
  1. مراقبة جميع العمليات كل 30 ثانية
  2. إعادة تشغيل أي عملية توقفت تلقائياً
  3. ربط algory_runner مع MT5 (live demo mode)
  4. تسجيل الحالة في ملف log
  5. عرض لوحة حالة موحدة

تشغيل:
  python friday_health_monitor.py
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
ROOT    = Path(r"C:\Users\Radhi\MT5")
SRC     = ROOT / "src"
PY      = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = Path(r"C:\Users\Radhi\AppData\Local\FRIDAY")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "health_monitor.log"
_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("health_monitor")

CHECK_INTERVAL  = 30   # ثوان بين كل فحص
RESTART_COOLDOWN = 60  # ثوان قبل إعادة التشغيل مرة أخرى
LOCK_PORT = int(os.getenv("FRIDAY_HEALTH_MONITOR_LOCK_PORT", "18777") or "18777")
_LOCK_SOCKET: socket.socket | None = None
UNMANAGED_PROCESS_KEYWORDS: dict[str, list[str]] = {
    # Old paper-mode supervisor uses a separate decision path and conflicts with
    # the unified live-demo stack managed by this monitor.
    "legacy_safe_supervisor": ["friday_safe_supervisor.py"],
}
# ─────────────────────────────────────────────────────────────────────────────


def _acquire_single_instance_lock() -> bool:
    """Prevent multiple health monitors from fighting over the same services."""
    global _LOCK_SOCKET
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
        sock.listen(1)
        _LOCK_SOCKET = sock
        return True
    except OSError:
        try:
            sock.close()
        except Exception:
            pass
        return False


@dataclass
class Service:
    name:         str
    script:       str           # مسار نسبي من ROOT (أو مطلق)
    args:         list[str]     = field(default_factory=list)
    title:        str           = ""
    cwd:          str           = ""   # فارغ = ROOT
    critical:     bool          = True
    single:       bool          = True  # منع تعدد النسخ
    # runtime state
    pid:          int           = 0
    last_restart: float         = 0.0
    restart_count:int           = 0
    misses:       int           = 0


# ─── تعريف جميع خدمات FRIDAY ─────────────────────────────────────────────────

SERVICES: list[Service] = [
    # ── محركات الذكاء ──────────────────────────────────────────────────────────
    Service(
        name="indicator_engine",
        script="friday_indicator_feature_engine.py",
        args=["--symbols", "all", "--loop", "--interval", "1"],
        title="FRIDAY Feature Council Engine",
    ),
    Service(
        name="orderflow_engine",
        script="friday_orderflow_feature_engine.py",
        args=["--symbols", "all", "--loop", "--interval", "5"],
        title="FRIDAY Order Flow Engine",
    ),

    # ── التعلم ───────────────────────────────────────────────────────────────
    Service(
        name="feature_learner",
        script="friday_feature_outcome_learner.py",
        args=["--loop", "--interval", "20", "--hours-back", "24"],
        title="FRIDAY Feature Outcome Learner",
    ),
    Service(
        name="trade_learner",
        script="friday_trade_outcome_learner.py",
        args=["--loop", "--interval", "15", "--hours-back", "24"],
        title="FRIDAY Trade Outcome Learner",
    ),

    # ── الخدمات / APIs ───────────────────────────────────────────────────────
    Service(
        name="gateway",
        script="-m uvicorn friday_local_gateway:app",
        args=["--host", "127.0.0.1", "--port", "8799"],
        title="FRIDAY Gateway 8799",
    ),
    Service(
        name="chat",
        script="friday_chat_app.py",
        title="FRIDAY Chat 8811",
    ),
    Service(
        name="dashboard_tv",
        script="friday_scalper_live_dashboard.py",
        title="FRIDAY TradingView Dashboard 8822",
    ),
    Service(
        name="agents_browser",
        script="friday_agents_browser.py",
        title="FRIDAY Agents Browser 8833",
    ),
    Service(
        name="brain_server",
        script="friday_live_brain_state.py",
        args=["--serve", "--port", "8844"],
        title="FRIDAY Unified Brain Browser 8844",
    ),
    Service(
        name="brain_loop",
        script="friday_live_brain_state.py",
        args=["--loop", "--interval", "2"],
        title="FRIDAY Unified Brain Loop",
    ),
    Service(
        name="autopilot",
        script="friday_autopilot_supervisor.py",
        args=["20"],
        title="FRIDAY Autopilot Supervisor",
    ),
    Service(
        name="system_mesh",
        script="friday_system_mesh.py",
        args=["--loop", "--interval", "60"],
        title="FRIDAY System Mesh",
    ),

    # ── Algory Engine (PAPER by default; Qader owns DEMO execution) ───────────
    Service(
        name="algory_runner",
        script="-m mt5_ai.algory_runner",
        args=["--symbols", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
              "USDCADm", "NZDUSDm", "USDCHFm", "XAUUSDm",
              "--timeframes", "M1", "M5", "M15", "H1", "H4",
              "--interval", "5"],
        title="FRIDAY Algory Runner",
        cwd=str(SRC),
    ),

    # ── لوحة الذكاء الاصطناعي ─────────────────────────────────────────────────
    Service(
        name="ai_dashboard",
        script="scripts/friday_web_dashboard.py",
        args=["--profile", "scalping", "--symbols", "all",
              "--max-open-positions", "3",
              "--entry-cooldown-seconds", "30",
              "--analysis-only", "--port", "8790"],
        title="FRIDAY AI Dashboard 8790",
    ),

    # ── المنفذون (معطّلون — يُشغَّلون يدوياً فقط عند الحاجة) ───────────────────
    # scalper_executor / touch_executor / position_governor
    # أُزيلوا من المراقبة التلقائية لأنهم يفتحون مئات الصفقات دون سقف واضح.
    # استخدم algory_runner وحده كمنفذ — هو يملك SL/TP و R:R guard.
]

# ─────────────────────────────────────────────────────────────────────────────


def _find_pids(service: Service) -> list[int]:
    return list(_find_process_map(service).keys())


def _find_process_map(service: Service) -> dict[int, int]:
    """ابحث عن python.exe فقط (تجاهل PowerShell wrappers) باستخدام WMI."""
    return _find_python_process_map_by_keywords(_service_keywords(service))


def _find_python_process_map_by_keywords(keywords: list[str]) -> dict[int, int]:
    """Return matching python.exe processes as {pid: parent_pid}."""
    try:
        import subprocess as sp
        checks = " -and ".join(
            f'$_.CommandLine -like "*{_ps_quote(k)}*"' for k in keywords
        )
        r = sp.run(
            ["powershell", "-NonInteractive", "-Command",
             f'Get-WmiObject Win32_Process | Where-Object {{ '
             f'$_.Name -eq "python.exe" -and $_.CommandLine -and {checks} '
             f'}} | ForEach-Object {{ "$($_.ProcessId),$($_.ParentProcessId)" }}'],
            capture_output=True, text=True, timeout=15
        )
        processes: dict[int, int] = {}
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",", 1)]
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                processes[int(parts[0])] = int(parts[1])
        return processes
    except Exception:
        return {}


def _service_keywords(service: Service) -> list[str]:
    """Return command-line fragments that uniquely identify a managed service."""
    if service.script.startswith("-m "):
        return service.script[3:].split()

    script_name = Path(service.script).name
    if service.name == "brain_server":
        return [script_name, "--serve", "--port", "8844"]
    if service.name == "brain_loop":
        return [script_name, "--loop"]
    if service.name == "system_mesh":
        return [script_name, "--loop"]
    return [script_name]


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _process_groups(processes: dict[int, int]) -> dict[int, list[int]]:
    """Group matching Python processes by root parent to avoid killing child workers."""
    pid_set = set(processes)
    groups: dict[int, list[int]] = {}

    for pid in sorted(pid_set):
        root = pid
        seen: set[int] = set()
        while processes.get(root) in pid_set and root not in seen:
            seen.add(root)
            root = processes[root]
        groups.setdefault(root, []).append(pid)

    return groups


def _service_port(service: Service) -> int | None:
    explicit_ports = {
        "chat": 8811,
        "dashboard_tv": 8822,
        "agents_browser": 8833,
    }
    if service.name in explicit_ports:
        return explicit_ports[service.name]
    if "--port" in service.args:
        idx = service.args.index("--port")
        try:
            return int(service.args[idx + 1])
        except (IndexError, ValueError):
            return None
    return None


def _listening_pid(port: int | None) -> int | None:
    if not port:
        return None
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NonInteractive",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
                "| Select-Object -First 1 -ExpandProperty OwningProcess",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = r.stdout.strip()
        return int(value) if value.isdigit() else None
    except Exception:
        return None


def _choose_group_to_keep(service: Service, groups: dict[int, list[int]]) -> int:
    port_owner = _listening_pid(_service_port(service))
    if port_owner:
        for root, pids in groups.items():
            if port_owner in pids:
                return root

    # Prefer the original orchestrator-started copy over a copy spawned later by
    # this health monitor. On Windows the venv launcher and child can share the
    # same command line, so grouping already handles parent/child pairs.
    monitor_pids = set(_find_python_process_map_by_keywords(["friday_health_monitor.py"]))
    for root in sorted(groups):
        parent_pid = _find_python_process_map_by_keywords(_service_keywords(service)).get(root)
        if parent_pid not in monitor_pids:
            return root
    return min(groups)


def _kill_pids(pids: list[int]) -> None:
    for pid in sorted(set(pids), reverse=True):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=5)
        except Exception:
            pass


def _find_python_pids_by_keywords(keywords: list[str]) -> list[int]:
    return list(_find_python_process_map_by_keywords(keywords))


def _enforce_single_health_monitor() -> None:
    """Keep one health monitor alive; stale copies can duplicate the whole stack."""
    current_pid = os.getpid()
    processes = _find_python_process_map_by_keywords(["friday_health_monitor.py"])
    groups = _process_groups(processes)
    current_root = None
    for root, pids in groups.items():
        if current_pid in pids:
            current_root = root
            break
    if current_root is None:
        return

    stale_pids: list[int] = []
    for root, pids in groups.items():
        if root != current_root:
            stale_pids.extend(pids)
    if not stale_pids:
        return
    _kill_pids(stale_pids)
    log.warning("STOPPED  %-22s  removed %d stale monitor processes", "health_monitor", len(stale_pids))


def _stop_unmanaged_processes() -> None:
    for label, keywords in UNMANAGED_PROCESS_KEYWORDS.items():
        pids = _find_python_pids_by_keywords(keywords)
        if not pids:
            continue
        _kill_pids(pids)
        log.warning("STOPPED  %-22s  removed %d unmanaged processes", label, len(pids))


def _is_running(service: Service) -> bool:
    return len(_find_pids(service)) > 0


def _kill_all(service: Service) -> None:
    _kill_pids(_find_pids(service))


def _spawn(service: Service) -> None:
    """Restart a service directly instead of leaving PowerShell wrapper windows."""
    cwd = service.cwd or str(ROOT)

    if service.script.startswith("-m "):
        cmd_parts = [str(PY), "-m", *service.script[3:].split()] + service.args
    else:
        script_path = ROOT / service.script
        cmd_parts = [str(PY), str(script_path)] + service.args

    env = os.environ.copy()
    env.update({
        "FRIDAY_PROJECT_ROOT": str(ROOT),
        "QADER_ROOT": str(ROOT),
        "FRIDAY_MT5_READONLY": "1",
        "FRIDAY_DASHBOARD_DISABLE_TF": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })

    log_root = ROOT / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = log_root / f"health_monitor_{service.name}.out.log"
    stderr_path = log_root / f"health_monitor_{service.name}.err.log"
    stdout = open(stdout_path, "a", encoding="utf-8", errors="replace")
    stderr = open(stderr_path, "a", encoding="utf-8", errors="replace")
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            cmd_parts,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
    finally:
        stdout.close()
        stderr.close()
    service.last_restart = time.monotonic()
    service.restart_count += 1
    log.info("STARTED  %-22s  (restart #%d)", service.name, service.restart_count)


def _check_and_heal(service: Service) -> str:
    """فحص واحدة وإصلاحها. يعيد الحالة كنص."""
    processes = _find_process_map(service)
    pids = list(processes)
    port_owner = _listening_pid(_service_port(service))

    if not pids:
        if port_owner:
            service.pid = port_owner
            log.warning("%-24s  port %s already owned by PID %s; skip duplicate restart",
                        service.name, _service_port(service), port_owner)
            return "OK"
        service.misses += 1
        if service.misses < 2:
            return "DOWN (confirming)"
        # ميتة — أعد التشغيل إذا انتهت فترة الانتظار
        elapsed = time.monotonic() - service.last_restart
        if elapsed >= RESTART_COOLDOWN:
            _spawn(service)
            return "RESTARTED"
        return f"DOWN (cooldown {RESTART_COOLDOWN - elapsed:.0f}s)"
    service.misses = 0

    # مزدوجة؟ لا نحسب child worker كنسخة مستقلة.
    groups = _process_groups(processes)
    if service.single and len(groups) > 1:
        keep_root = _choose_group_to_keep(service, groups)
        removed = 0
        for root, group_pids in groups.items():
            if root == keep_root:
                continue
            removed += len(group_pids)
            _kill_pids(group_pids)
        log.warning("DEDUPED  %-22s  removed %d extra processes", service.name, removed)
        time.sleep(0.5)
        processes = _find_process_map(service)
        pids = list(processes)

    service.pid = port_owner or min(pids)
    return "OK"


# ─────────────────────────────────────────────────────────────────────────────
#  MT5 حالة الصفقات
# ─────────────────────────────────────────────────────────────────────────────

def _mt5_status() -> dict:
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        info     = mt5.account_info()
        pos      = mt5.positions_get() or []
        orders   = mt5.orders_get()   or []
        balance  = info.balance  if info else 0.0
        equity   = info.equity   if info else 0.0
        margin   = info.margin   if info else 0.0
        profit   = sum(p.profit for p in pos)
        algory_pos = [p for p in pos if p.comment and "FRIDAY|" in p.comment]
        return {
            "balance":      round(balance, 2),
            "equity":       round(equity,  2),
            "free_margin":  round(info.margin_free if info else 0.0, 2),
            "open_pos":     len(pos),
            "algory_pos":   len(algory_pos),
            "pending":      len(orders),
            "float_pnl":    round(profit, 2),
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Algory genome status
# ─────────────────────────────────────────────────────────────────────────────

def _algory_status() -> list[dict]:
    try:
        reg_path = Path(r"C:\Users\Radhi\AppData\Local\FRIDAY\active_genomes.json")
        if not reg_path.exists():
            return []
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        rows = []
        for key, g in data.items():
            sym, tf = key.split("|", 1)
            rows.append({
                "key":      key,
                "id":       g.get("id", "?")[:8],
                "campaign": g.get("campaign", "?"),
                "trades":   g.get("trades", 0),
                "win_rate": g.get("win_rate", 0.0),
                "return":   g.get("total_return_pct", 0.0),
                "dd":       g.get("max_dd_pct", 0.0),
            })
        return sorted(rows, key=lambda r: r["key"])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  لوحة الحالة
# ─────────────────────────────────────────────────────────────────────────────

def _print_dashboard(statuses: dict[str, str], mt5: dict, ts: str) -> None:
    print("\n" + "═" * 70)
    print(f"  FRIDAY HEALTH DASHBOARD  —  {ts}")
    print("═" * 70)

    # عمليات
    ok = sum(1 for s in statuses.values() if s == "OK")
    down = sum(1 for s in statuses.values() if "DOWN" in s or "RESTARTED" in s)
    print(f"\n  Processes: {ok} OK  |  {down} issues")
    print(f"  {'SERVICE':<24} {'STATUS'}")
    print(f"  {'─'*23} {'─'*20}")
    for name, status in statuses.items():
        icon = "✓" if status == "OK" else ("↺" if "RESTARTED" in status else "✗")
        print(f"  {icon} {name:<22} {status}")

    # MT5
    print()
    if "error" in mt5:
        print(f"  MT5: ERROR — {mt5['error']}")
    else:
        print(f"  MT5  |  Balance={mt5['balance']}  Equity={mt5['equity']}"
              f"  Float={mt5['float_pnl']:+.2f}")
        print(f"       |  Open={mt5['open_pos']} (Algory={mt5['algory_pos']})"
              f"  Pending={mt5['pending']}"
              f"  FreeMargin={mt5['free_margin']}")

    print("═" * 70)


# ─────────────────────────────────────────────────────────────────────────────
#  الحلقة الرئيسية
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _enforce_single_health_monitor()
    if not _acquire_single_instance_lock():
        log.warning("Another FRIDAY Health Monitor is already running; exiting this copy.")
        return

    log.info("FRIDAY Health Monitor started — checking every %ds", CHECK_INTERVAL)
    log.info("Services to monitor: %d", len(SERVICES))

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        statuses: dict[str, str] = {}

        _stop_unmanaged_processes()

        for svc in SERVICES:
            try:
                statuses[svc.name] = _check_and_heal(svc)
            except Exception as e:
                statuses[svc.name] = f"ERROR:{e}"
                log.error("check failed for %s: %s", svc.name, e)

        mt5_info = _mt5_status()

        # طباعة لوحة الحالة كل 5 دورات (2.5 دقيقة)
        if cycle % 5 == 1:
            _print_dashboard(statuses, mt5_info, ts)

        # سجل موجز
        issues = [(n, s) for n, s in statuses.items() if s != "OK"]
        if issues:
            for name, status in issues:
                log.warning("%-24s  %s", name, status)
        else:
            log.info("Cycle %d | all %d services OK | MT5 equity=%.2f float=%+.2f",
                     cycle, len(SERVICES),
                     mt5_info.get("equity", 0),
                     mt5_info.get("float_pnl", 0))

        # حفظ حالة JSON للـ dashboard
        status_file = LOG_DIR / "health_status.json"
        status_file.write_text(json.dumps({
            "ts":       ts,
            "cycle":    cycle,
            "services": statuses,
            "mt5":      mt5_info,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
