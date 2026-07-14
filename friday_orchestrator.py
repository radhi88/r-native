"""
friday_orchestrator.py
----------------------
Orchestrateur FRIDAY — يشغّل الكل بالترتيب الصحيح.

الطبقات (كل طبقة تنتظر الطبقة اللي قبلها قبل ما تبدأ):

  1. Data Foundation   — indicator_engine, orderflow_engine
  2. Intelligence      — feature_learner, trade_learner, brain_loop
  3. API Layer         — gateway, brain_server, system_mesh
  4. Dashboards        — chat, dashboard_tv, agents_browser, ai_dashboard
  5. Trading Engine    — autopilot, algory_runner in PAPER mode, Qader DEMO loop
  6. Health Monitor    — يراقب الكل
  7. JARVIS (Mark-XXXIX) — آخر شيء يشتغل | يستقبل أوامر المستخدم فقط

تشغيل:
  python friday_orchestrator.py
  python friday_orchestrator.py --skip-jarvis
  python friday_orchestrator.py --tier 3          # تبدأ من طبقة معينة
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# ─── Paths ───────────────────────────────────────────────────────────────────
ROOT    = Path(r"C:\Users\Radhi\MT5")
SRC     = ROOT / "src"
PY      = ROOT / ".venv" / "Scripts" / "python.exe"
DATA    = Path(r"C:\Users\Radhi\AppData\Local\FRIDAY")
JARVIS  = ROOT / "mark_xxxix"
LOGS    = ROOT / "logs"
RUNTIME = ROOT / "runtime"

DATA.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)

# ─── ANSI colours ────────────────────────────────────────────────────────────
R  = "\033[91m"   # red
G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
M  = "\033[95m"   # magenta
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
DG = "\033[90m"   # dark grey
RST= "\033[0m"
BOLD="\033[1m"

def clr(text: str, color: str) -> str:
    return f"{color}{text}{RST}"


_LOCK_FD: int | None = None
_LOCK_PATH = RUNTIME / "friday_orchestrator.lock"


def _pid_is_orchestrator(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["powershell", "-NonInteractive", "-Command",
                 f'if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ "1" }}'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "1" in (r.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _release_orchestrator_lock() -> None:
    global _LOCK_FD
    try:
        if _LOCK_FD is not None:
            os.close(_LOCK_FD)
            _LOCK_FD = None
        _LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _acquire_orchestrator_lock() -> None:
    """Prevent two orchestrators from spawning duplicate FRIDAY workers."""
    global _LOCK_FD
    while True:
        try:
            _LOCK_FD = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(_LOCK_FD, str(os.getpid()).encode("ascii"))
            atexit.register(_release_orchestrator_lock)
            return
        except FileExistsError:
            try:
                pid = int(_LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                pid = 0
            if _pid_is_orchestrator(pid):
                print(clr(f"Another FRIDAY orchestrator is already running (PID {pid}).", R))
                raise SystemExit(2)
            _LOCK_PATH.unlink(missing_ok=True)


# ─── Service definition ───────────────────────────────────────────────────────

@dataclass
class Svc:
    name:     str
    title:    str
    script:   str                       # relative to ROOT, or "-m module"
    args:     list[str]  = field(default_factory=list)
    cwd:      str        = ""           # "" = ROOT
    port:     int | None = None         # TCP port to check for ready
    ready_file: str      = ""           # optional: file must exist & be <60s old
    env: dict[str, str]  = field(default_factory=dict)
    wait_min: int        = 4            # minimum seconds after spawn before ready
    # runtime
    pid:      int        = 0

    def effective_cwd(self) -> str:
        return self.cwd or str(ROOT)

    def cmd_parts(self) -> list[str]:
        if self.script.startswith("-m "):
            return [str(PY), "-m", *self.script[3:].split()] + self.args
        return [str(PY), str(ROOT / self.script)] + self.args

    def is_port_open(self) -> bool:
        if not self.port:
            return False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                return True
        except OSError:
            return False

    def is_process_running(self) -> bool:
        kw = self._keyword()
        try:
            r = subprocess.run(
                ["powershell", "-NonInteractive", "-Command",
                 f'Get-WmiObject Win32_Process | Where-Object {{ '
                 f'$_.Name -eq "python.exe" -and $_.CommandLine -like "*{kw}*" '
                 f'}} | Measure-Object | Select-Object -ExpandProperty Count'],
                capture_output=True, text=True, timeout=10,
            )
            return int(r.stdout.strip() or "0") > 0
        except Exception:
            return False

    def _keyword(self) -> str:
        if self.script.startswith("-m "):
            return self.script[3:].split()[0]
        return Path(self.script).name.replace("'", "''")

    def is_ready(self) -> bool:
        if self.port:
            return self.is_port_open()
        if self.ready_file:
            p = Path(self.ready_file)
            return p.exists() and (time.time() - p.stat().st_mtime) < 120
        return self.is_process_running()


# ─── Tier definition ──────────────────────────────────────────────────────────

@dataclass
class Tier:
    number:  int
    name:    str
    color:   str
    services: list[Svc]
    wait_after: int = 3   # extra settle seconds after all services ready


# ─── Service catalogue ────────────────────────────────────────────────────────

TIERS: list[Tier] = [

    Tier(1, "Data Foundation", C, [
        Svc("indicator_engine", "Feature Council Engine",
            "friday_indicator_feature_engine.py",
            args=["--symbols", "all", "--loop", "--interval", "1"],
            wait_min=8),
        Svc("orderflow_engine", "Order Flow Engine",
            "friday_orderflow_feature_engine.py",
            args=["--symbols", "all", "--loop", "--interval", "5"],
            wait_min=5),
    ]),

    Tier(2, "Intelligence Layer", M, [
        Svc("feature_learner", "Feature Outcome Learner",
            "friday_feature_outcome_learner.py",
            args=["--loop", "--interval", "20", "--hours-back", "24"],
            wait_min=4),
        Svc("trade_learner", "Trade Outcome Learner",
            "friday_trade_outcome_learner.py",
            args=["--loop", "--interval", "15", "--hours-back", "24"],
            wait_min=4),
        Svc("brain_loop", "Brain State Loop",
            "friday_live_brain_state.py",
            args=["--loop", "--interval", "2"],
            wait_min=4),
    ]),

    Tier(3, "API Layer", Y, [
        Svc("gateway", "Gateway :8799",
            "-m uvicorn friday_local_gateway:app",
            args=["--host", "127.0.0.1", "--port", "8799"],
            port=8799, wait_min=4),
        Svc("desktop_agent", "Desktop Agent :8855",
            "scripts/friday_jarvis_desktop_agent.py",
            port=8855, wait_min=4),
        Svc("brain_server", "Brain Server :8844",
            "friday_live_brain_state.py",
            args=["--serve", "--port", "8844"],
            port=8844, wait_min=4),
        Svc("system_mesh", "System Mesh",
            "friday_system_mesh.py",
            args=["--loop", "--interval", "60"],
            wait_min=3),
    ]),

    Tier(4, "Dashboards", B, [
        Svc("chat", "Chat :8811",
            "friday_chat_app.py",
            port=8811, wait_min=4),
        Svc("dashboard_tv", "TradingView :8822",
            "friday_scalper_live_dashboard.py",
            port=8822, wait_min=4),
        Svc("agents_browser", "Agents Browser :8833",
            "friday_agents_browser.py",
            port=8833, wait_min=4),
        Svc("ai_dashboard", "AI Dashboard :8790",
            "scripts/friday_web_dashboard.py",
            args=["--profile", "scalping", "--symbols", "all",
                  "--max-open-positions", "3", "--entry-cooldown-seconds", "30",
                  "--analysis-only", "--port", "8790"],
            env={"FRIDAY_DASHBOARD_DISABLE_TF": "1"},
            port=8790, wait_min=5),
        Svc("qader_dashboard", "Qader Live Dashboard :8765",
            "scripts/dashboard_server.py",
            port=8765, wait_min=4),
        Svc("qader_market_chat", "Qader Market Chat :8788",
            "scripts/jarvis_ui.py",
            args=["--source", "mt5", "--profile", "scalping",
                  "--symbol", "XAUUSDm", "--timeframe", "M1",
                  "--port", "8788", "--no-speak"],
            port=8788, wait_min=8),
        Svc("algory_charts", "Algory Chart Dashboard :8866",
            "algory_chart_dashboard.py",
            env={"ALGORY_CHART_PORT": "8866"},
            port=8866, wait_min=5),
        Svc("fractal_monitor", "Fractal Projection Monitor",
            "live_fractal_projection_monitor.py",
            ready_file=str(DATA / "fractal_live_state.json"),
            wait_min=10),
    ]),

    Tier(5, "Trading Engine", G, [
        Svc("autopilot", "Autopilot Supervisor",
            "friday_autopilot_supervisor.py",
            args=["20"],
            wait_min=4),
        Svc("algory_runner", "Algory Runner (PAPER)",
            "-m mt5_ai.algory_runner",
            args=["--symbols", "EURUSDm", "GBPUSDm", "USDJPYm",
                  "AUDUSDm", "USDCADm", "NZDUSDm", "USDCHFm", "XAUUSDm",
                  "--timeframes", "M1", "M5", "M15", "H1", "H4",
                  "--interval", "5"],
            cwd=str(SRC),
            wait_min=6),
        Svc("qader_loop", "Qader DEMO Execution Loop",
            "scripts/run_qader_headless.py",
            ready_file=str(ROOT / "dashboard" / "qader_live_state.json"),
            wait_min=8),
    ]),

    Tier(6, "Health Monitor", DG, [
        Svc("health_monitor", "Health Monitor",
            "friday_health_monitor.py",
            wait_min=3),
        Svc("diagnostics", "System Diagnostics",
            "scripts/system_status_report.py",
            args=["--loop", "--interval", "15"],
            ready_file=str(ROOT / "runtime" / "system_status.json"),
            wait_min=3),
        Svc("dna_feedback", "Bayesian DNA Feedback :live",
            "scripts/dna_live_feedback.py",
            args=["--interval", "60"],
            wait_min=3),
    ]),
]

# Mark-XXXIX is handled separately (last, user-commands only)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _kill_all() -> None:
    """Kill any already-running FRIDAY python processes before fresh start."""
    patterns = [
        "friday_indicator_feature_engine", "friday_orderflow_feature_engine",
        "friday_feature_outcome_learner", "friday_trade_outcome_learner",
        "friday_live_brain_state", "friday_local_gateway",
        "friday_jarvis_desktop_agent",
        "friday_system_mesh", "friday_chat_app",
        "friday_scalper_live_dashboard", "friday_agents_browser",
        "friday_web_dashboard", "friday_autopilot_supervisor",
        "dashboard_server", "jarvis_ui", "run_qader_headless",
        "mt5_ai.algory_runner", "algory_chart_dashboard",
        "live_fractal_projection_monitor",
        "friday_health_monitor", "dna_live_feedback",
        # executors (disabled but kill if running)
        "friday_realtime_scalper_demo_executor",
        "friday_touch_demo_executor",
        "friday_demo_position_governor_v2",
    ]
    regex = "|".join(p.replace(".", r"\.") for p in patterns)
    subprocess.run(
        ["powershell", "-NonInteractive", "-Command",
         f'Get-WmiObject Win32_Process | Where-Object {{ '
         f'$_.Name -eq "python.exe" -and $_.CommandLine -match "{regex}" '
         f'}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}'],
        capture_output=True, timeout=20,
    )
    time.sleep(2)


def _spawn_window(svc: Svc) -> None:
    """Start a managed service as a detached Python process with logs."""
    env = os.environ.copy()
    env.update({
        "FRIDAY_PROJECT_ROOT": str(ROOT),
        "QADER_ROOT": str(ROOT),
        "FRIDAY_MT5_READONLY": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        **svc.env,
    })
    stdout_path = LOGS / f"orchestrator_{svc.name}.out.log"
    stderr_path = LOGS / f"orchestrator_{svc.name}.err.log"
    stdout = open(stdout_path, "a", encoding="utf-8", errors="replace")
    stderr = open(stderr_path, "a", encoding="utf-8", errors="replace")
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(
            svc.cmd_parts(),
            cwd=svc.effective_cwd(),
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
        )
        svc.pid = proc.pid
    finally:
        stdout.close()
        stderr.close()


def _wait_ready(svc: Svc, timeout: int = 90) -> bool:
    """
    Wait until the service is healthy.
    Returns True = healthy, False = timed out.
    """
    deadline = time.monotonic() + timeout
    # minimum wait first
    time.sleep(svc.wait_min)
    while time.monotonic() < deadline:
        if svc.is_ready():
            return True
        time.sleep(2)
    return False


def _mt5_brief() -> dict:
    """Collect current MT5 state for the JARVIS session brief."""
    try:
        sys.path.insert(0, str(SRC))
        import MetaTrader5 as mt5
        mt5.initialize()
        info = mt5.account_info()
        pos  = mt5.positions_get() or []
        return {
            "balance":  round(info.balance,  2) if info else 0,
            "equity":   round(info.equity,   2) if info else 0,
            "open_pos": len(pos),
            "float":    round(sum(p.profit for p in pos), 2),
        }
    except Exception:
        return {}


def _write_jarvis_brief() -> Path:
    """
    Write a session brief for Mark-XXXIX.
    JARVIS reads this at startup to know the current system state.
    It does NOT receive commands from other services.
    """
    mt5 = _mt5_brief()

    # Load active genome count
    reg = DATA / "active_genomes.json"
    genome_count = 0
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        genome_count = len(data)
    except Exception:
        pass

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    brief = f"""# FRIDAY Session Brief — {ts}
## Your Role
You are the voice interface for FRIDAY, a demo/paper-first algorithmic trading system.
You ONLY receive commands from the user (Radhi). No other service sends you commands.
You DO NOT execute trades, DO NOT trigger service restarts, DO NOT modify code.
You observe, explain, answer, and execute only what the user explicitly asks.

## System State at Startup
- MT5 Balance  : {mt5.get('balance', 'N/A')} USD
- MT5 Equity   : {mt5.get('equity', 'N/A')} USD
- Open Positions: {mt5.get('open_pos', 'N/A')}
- Float P&L    : {mt5.get('float', 'N/A')} USD
- Active Genomes: {genome_count} loaded in Algory registry

## Active Services (all started before you)
1. indicator_engine   — computes 50+ technical features every second
2. orderflow_engine   — reads tick/volume order flow every 5s
3. feature_learner    — trains ML model on feature→outcome pairs
4. trade_learner      — records and learns from completed trades
5. brain_loop         — aggregates all signals into a unified brain state
6. gateway            — REST API at :8799 for internal service communication
7. brain_server       — serves brain state at :8844
8. system_mesh        — monitors cross-service health every 60s
9. chat               — chat interface at :8811
10. dashboard_tv      — TradingView live dashboard at :8822
11. agents_browser    — agent status browser at :8833
12. ai_dashboard      — main AI dashboard at :8790
13. qader_dashboard   — live Qader dashboard at :8765
14. qader_market_chat — chat connected to Qader+MT5 market data at :8788
15. autopilot         — decision supervisor
16. algory_runner     — Algory genetic strategy engine (PAPER mode by default)
17. qader_loop        — Qader DEMO execution loop
18. health_monitor    — watchdog, auto-restarts crashed services

## Algory Trading Engine
- Symbols: EURUSDm GBPUSDm USDJPYm AUDUSDm USDCADm NZDUSDm USDCHFm XAUUSDm
- Timeframes: M15, H1, H4
- Mode: PAPER for Algory; Qader DEMO-only execution loop is started by this orchestrator after demo account verification
- Executors: scalper/touch/governor are DISABLED — only Algory trades
- Trades tagged: FRIDAY|{{genome_id}}

## What the User May Ask You
- "كم عندنا صفقات مفتوحة؟" — check open positions
- "كيف حال FRIDAY؟" — system health summary
- "أوقف الـ algory" — you may stop specific services if user asks
- "أي زوج يعطي أفضل إشارة؟" — read brain state and answer
- "افتح صفقة شراء على EURUSD" — route to Qader DEMO-only confirmation flow; never bypass ExecutionManager

## Important
You started LAST so you have full context of everything running.
Wait for the user to speak first. Do not initiate.
"""

    brief_path = ROOT / "jarvis_session_brief.md"
    brief_path.write_text(brief, encoding="utf-8")
    return brief_path


def _write_system_status_once() -> None:
    try:
        subprocess.run(
            [str(PY), str(ROOT / "scripts" / "system_status_report.py")],
            cwd=str(ROOT),
            capture_output=True,
            timeout=45,
        )
    except Exception as exc:
        print(f"  {Y}SYSTEM_STATUS probe skipped: {exc}{RST}")


def _launch_jarvis(brief_path: Path) -> None:
    """Launch Mark-XXXIX with full context, user-commands-only mode."""
    root = str(ROOT)
    dashboard = "http://127.0.0.1:8790"
    gateway   = "http://127.0.0.1:8799"
    chat      = "http://127.0.0.1:8811"
    qader     = "http://127.0.0.1:8765"
    qaderchat = "http://127.0.0.1:8788"
    tv        = "http://127.0.0.1:8822"
    agents    = "http://127.0.0.1:8833"
    brain     = "http://127.0.0.1:8844"

    env = os.environ.copy()
    env.update({
        "JARVIS_PROJECT_ROOT": root,
        "FRIDAY_ROOT": root,
        "FRIDAY_DASHBOARD_URL": dashboard,
        "FRIDAY_BASE": dashboard,
        "FRIDAY_SSE_URL": f"{dashboard}/events",
        "FRIDAY_GATEWAY_URL": gateway,
        "FRIDAY_CHAT_URL": chat,
        "QADER_DASHBOARD_URL": qader,
        "QADER_STATE_URL": f"{qader}/api/state",
        "QADER_STREAM_URL": f"{qader}/api/stream",
        "QADER_CHAT_URL": qaderchat,
        "FRIDAY_TRADINGVIEW_URL": tv,
        "FRIDAY_AGENTS_URL": agents,
        "FRIDAY_BRAIN_URL": brain,
        "JARVIS_VOICE_BACKEND": "gemini_live",
        "JARVIS_LIVE_MIC": "1",
        "JARVIS_LOCAL_MIC_FALLBACK": "0",
        "JARVIS_MIC_MODE": "local",
        "JARVIS_STT_BACKEND": "whisper",
        "JARVIS_WHISPER_MODEL": "small",
        "JARVIS_WHISPER_LANGUAGE": "ar",
        "JARVIS_WHISPER_VAD_RMS": "0.020",
        "JARVIS_WHISPER_MIN_SPEECH_SECONDS": "0.80",
        "JARVIS_WHISPER_MIN_WORDS": "2",
        "JARVIS_OLLAMA_FAST_MODEL": "llama3.2:3b",
        "JARVIS_OLLAMA_SMART_MODEL": "qwen2.5:3b",
        "JARVIS_OLLAMA_CODE_MODEL": "qwen2.5-coder:3b",
        "JARVIS_OLLAMA_TOOL_MODEL": "qwen2.5:3b",
        "JARVIS_OLLAMA_REASONING_MODEL": "qwen2.5:3b",
        "JARVIS_OLLAMA_REVIEW_MODEL": "qwen2.5:3b",
        "JARVIS_OLLAMA_VISION_MODEL": "llava:latest",
        "JARVIS_VISION_BACKEND": "llava",
        "JARVIS_PROJECT_AGENT_AUTO_WATCH": "1",
        "JARVIS_COMMAND_INBOX_ENABLED": "1",
        "JARVIS_SESSION_BRIEF": str(brief_path).replace("\\", "/"),
        "JARVIS_USER_COMMANDS_ONLY": "1",
        "JARVIS_NO_AUTOCOMMAND": "1",
    })
    stdout = open(LOGS / "orchestrator_jarvis.out.log", "a", encoding="utf-8", errors="replace")
    stderr = open(LOGS / "orchestrator_jarvis.err.log", "a", encoding="utf-8", errors="replace")
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [str(PY), "main.py"],
            cwd=str(JARVIS),
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
        )
    finally:
        stdout.close()
        stderr.close()


# ─── Terminal UI ──────────────────────────────────────────────────────────────

def _banner() -> None:
    os.system("cls" if os.name == "nt" else "clear")
    print(f"\n{BOLD}{C}{'═'*62}{RST}")
    print(f"{BOLD}{W}   FRIDAY ORCHESTRATOR — Startup Sequencer{RST}")
    print(f"{DG}   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RST}")
    print(f"{BOLD}{C}{'═'*62}{RST}\n")


def _tier_header(tier: Tier) -> None:
    line = f"  TIER {tier.number}  ·  {tier.name}"
    print(f"\n{BOLD}{tier.color}{line}{RST}")
    print(f"{tier.color}  {'─'*50}{RST}")


def _svc_line(svc: Svc, status: str, color: str, elapsed: float = 0.0) -> None:
    t = f"  {color}{'●'}{RST}  {W}{svc.name:<22}{RST}  {color}{status:<14}{RST}"
    if elapsed > 0:
        t += f"  {DG}{elapsed:.1f}s{RST}"
    print(t)


def _tier_done(tier: Tier, elapsed: float) -> None:
    print(f"\n  {G}✓ {tier.name} ready{RST}  {DG}({elapsed:.1f}s){RST}")


def _final_summary(total_elapsed: float) -> None:
    print(f"\n{BOLD}{C}{'═'*62}{RST}")
    print(f"{BOLD}{G}  FRIDAY stack fully operational — {total_elapsed:.0f}s{RST}")
    print(f"{BOLD}{C}{'═'*62}{RST}\n")
    print(f"  {C}Dashboards:{RST}")
    print(f"    AI Dashboard   →  http://127.0.0.1:8790")
    print(f"    Brain State    →  http://127.0.0.1:8844")
    print(f"    TradingView    →  http://127.0.0.1:8822")
    print(f"    Agents Browser →  http://127.0.0.1:8833")
    print(f"    Chat           →  http://127.0.0.1:8811")
    print(f"    Qader Live     →  http://127.0.0.1:8765/qader_live_dashboard.html")
    print(f"    Qader Chat API →  http://127.0.0.1:8788")
    print(f"    Algory Charts  →  http://127.0.0.1:8866  (SMC · Fractals · OB · FVG)")
    print(f"\n  {G}Trading:{RST}  algory_runner PAPER + Qader DEMO loop — XAUUSDm fast mode")
    print(f"  {Y}JARVIS:{RST}   Mark-XXXIX started — awaiting user commands\n")


# ─── Main orchestration loop ─────────────────────────────────────────────────

def run(start_from_tier: int = 1, skip_jarvis: bool = False) -> None:
    _banner()
    os.environ.setdefault("FRIDAY_PROJECT_ROOT", str(ROOT))
    os.environ.setdefault("QADER_ROOT", str(ROOT))
    os.environ.setdefault("FRIDAY_MT5_READONLY", "1")

    print(f"  {Y}Stopping any existing FRIDAY processes...{RST}")
    _kill_all()
    print(f"  {G}Clean slate.{RST}\n")
    _write_system_status_once()

    total_t0 = time.monotonic()

    # Load .env
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    for tier in TIERS:
        if tier.number < start_from_tier:
            print(f"  {DG}Skipping Tier {tier.number}: {tier.name}{RST}")
            continue

        _tier_header(tier)
        tier_t0 = time.monotonic()

        # Launch all services in this tier
        for svc in tier.services:
            _svc_line(svc, "starting…", Y)
            _spawn_window(svc)
            time.sleep(0.5)

        # Wait for all to become healthy
        results: dict[str, bool] = {}
        ready_times: dict[str, float] = {}

        for svc in tier.services:
            t0 = time.monotonic()
            ok = _wait_ready(svc, timeout=90)
            elapsed = time.monotonic() - t0
            results[svc.name] = ok
            ready_times[svc.name] = elapsed
            status = "ready" if ok else "TIMEOUT"
            color  = G if ok else R
            _svc_line(svc, status, color, elapsed)

        # Extra settle time
        if tier.wait_after > 0:
            print(f"\n  {DG}Settling {tier.wait_after}s…{RST}")
            time.sleep(tier.wait_after)

        tier_elapsed = time.monotonic() - tier_t0
        _tier_done(tier, tier_elapsed)

    # ── Open dashboards ───────────────────────────────────────────────────────
    print(f"\n  {C}Opening dashboards in browser…{RST}")
    for url in ["http://127.0.0.1:8790", "http://127.0.0.1:8844",
                "http://127.0.0.1:8822", "http://127.0.0.1:8833",
                "http://127.0.0.1:8811", "http://127.0.0.1:8866"]:
        subprocess.Popen(["cmd", "/c", "start", url],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(0.3)

    # ── JARVIS last ───────────────────────────────────────────────────────────
    if not skip_jarvis:
        print(f"\n{BOLD}{M}  TIER 7  ·  JARVIS (Mark-XXXIX){RST}")
        print(f"{M}  {'─'*50}{RST}")
        print(f"  {Y}Writing session brief…{RST}")

        brief_path = _write_jarvis_brief()
        print(f"  {G}Brief written → {brief_path.name}{RST}")
        print(f"  {Y}Launching Mark-XXXIX — user commands only{RST}")
        time.sleep(1)
        _launch_jarvis(brief_path)
        print(f"  {G}Mark-XXXIX started — awaiting user.{RST}")

    total_elapsed = time.monotonic() - total_t0
    _write_system_status_once()
    _final_summary(total_elapsed)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FRIDAY Orchestrator")
    parser.add_argument("--skip-jarvis", action="store_true",
                        help="Don't launch Mark-XXXIX at the end")
    parser.add_argument("--tier", type=int, default=1,
                        help="Start from this tier number (1-7)")
    args = parser.parse_args()

    try:
        _acquire_orchestrator_lock()
        run(start_from_tier=args.tier, skip_jarvis=args.skip_jarvis)
    except KeyboardInterrupt:
        print(f"\n\n  {Y}Orchestrator interrupted by user.{RST}\n")
