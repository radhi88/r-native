from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql


ROOT = Path(r"C:\Users\Radhi\MT5")
APP_ROOT = ROOT / "mnt" / "agents" / "output" / "app"
LOG_DIR = ROOT / "friday_autopilot_logs"
STATE_FILE = ROOT / "friday_autopilot_state.json"

GATEWAY = os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799").rstrip("/")
FRIDAY_CHAT_URL = os.getenv("FRIDAY_CHAT_URL", "http://127.0.0.1:8811").rstrip("/")
FRIDAY_TRADINGVIEW_URL = os.getenv("FRIDAY_TRADINGVIEW_URL", "http://127.0.0.1:8822").rstrip("/")
FRIDAY_AGENTS_URL = os.getenv("FRIDAY_AGENTS_URL", "http://127.0.0.1:8833").rstrip("/")

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "agents_app"

# Proactive improvement tasks — run when system is healthy, rotate through targets
PROACTIVE_IMPROVEMENTS = [
    (
        "Improve trading signal UI: add trend-strength progress bar, cleaner P&L color coding, and live trade count badge to the dashboard.",
        ["friday_scalper_live_dashboard.py"],
    ),
    (
        "Improve agents browser UI: add live trading metrics panel, recent patch activity feed, and agent performance mini-chart.",
        ["friday_agents_browser.py"],
    ),
    (
        "Improve brain memory quality: add trading performance scoring to next_steps, better patch quality metrics, and session win-rate tracking.",
        ["friday_brain.py"],
    ),
    (
        "Improve evolution memory: add pattern hit-rate logging, better learning rate tracking per symbol, and session performance summary.",
        ["friday_evolution_memory.py"],
    ),
    (
        "Improve external genome status export: make Jarvis per-symbol genome visibility clearer while preserving patch safety boundaries.",
        ["friday_genome_status_export.py"],
    ),
    (
        "Improve chat app: add recent trade feed panel, autopilot status badge, and live position P&L ticker.",
        ["friday_chat_app.py"],
    ),
]

HEALTH_ENDPOINTS = {
    "gateway": f"{GATEWAY}/openapi.json",
    "chat": f"{FRIDAY_CHAT_URL}/",
    "scalper_dashboard": f"{FRIDAY_TRADINGVIEW_URL}/api/state?symbol=XAUUSDm&timeframe=M1&bars=50",
    "agents_browser": f"{FRIDAY_AGENTS_URL}/api/overview",
}

PY_COMPILE_FILES = [
    "friday_chat_app.py",
    "friday_local_gateway.py",
    "friday_brain.py",
    "friday_project_map.py",
    "friday_scalper_live_dashboard.py",
    "friday_agents_browser.py",
    "friday_evolution_memory.py",
    "friday_genome_status_export.py",
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now()}] {msg}"
    print(line)
    with (LOG_DIR / "autopilot.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return state
        except Exception:
            pass

    return {
        "mode": "safe_autopilot",
        "started_at": now(),
        "updated_at": now(),
        "cycles": 0,
        "last_health": {},
        "last_actions": [],
        "auto_apply_enabled": True,
    }


def remember_action(state: dict[str, Any], action: dict[str, Any]) -> None:
    actions = state.setdefault("last_actions", [])
    actions.append({"time": now(), **action})
    state["last_actions"] = actions[-80:]


def http_get(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read(4000).decode("utf-8", errors="replace")
            return True, data
    except Exception as exc:
        return False, str(exc)


def http_post_json(url: str, body: dict[str, Any] | None = None, timeout: int = 10) -> tuple[bool, str]:
    payload = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(6000).decode("utf-8", errors="replace")
            return True, data
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8", errors="replace")
        return False, data
    except Exception as exc:
        return False, str(exc)


def db_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def db_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall() or [])
    except Exception as exc:
        log(f"DB ERROR: {exc}")
        return []


def db_exec(sql: str, params: tuple = ()) -> None:
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
    except Exception as exc:
        log(f"DB EXEC ERROR: {exc}")


def run_cmd(cmd: list[str], timeout: int = 45) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out[-8000:]
    except subprocess.TimeoutExpired as exc:
        return False, f"TIMEOUT: {exc}"
    except Exception as exc:
        return False, str(exc)


def compile_safe_files() -> dict[str, Any]:
    results = {}

    for rel in PY_COMPILE_FILES:
        path = ROOT / rel

        if not path.exists():
            results[rel] = {"ok": False, "output": "missing"}
            continue

        ok, out = run_cmd([sys.executable, "-m", "py_compile", str(path)], timeout=30)
        results[rel] = {"ok": ok, "output": out[-1200:]}

    return results


def check_health() -> dict[str, Any]:
    health = {}

    for name, url in HEALTH_ENDPOINTS.items():
        ok, out = http_get(url, timeout=5)
        health[name] = {
            "ok": ok,
            "sample": out[:300],
        }

    return health


def get_pending_patches() -> list[dict[str, Any]]:
    return db_all(
        """
        SELECT id, job_id, agent_name, agent_role, target_file, reason, risk, patch,
               approved, applied, created_at
        FROM dispatch_patch_proposals
        WHERE applied=0
        ORDER BY id DESC
        LIMIT 50
        """
    )


def auto_apply_all_patches(state: dict[str, Any]) -> None:
    if not state.get("auto_apply_enabled", True):
        return

    rows = get_pending_patches()

    for row in rows:
        patch_id = int(row.get("id") or 0)
        log(f"AUTO PATCH: #{patch_id} {row.get('target_file')}")

        ok1, out1 = http_post_json(f"{GATEWAY}/patches/{patch_id}/approve", {})
        remember_action(
            state,
            {
                "type": "approve_patch",
                "patch_id": patch_id,
                "ok": ok1,
                "output": out1[:1000],
            },
        )

        if not ok1 and "already" not in out1.lower():
            log(f"Approve failed for patch #{patch_id}: {out1[:300]}")
            continue

        ok2, out2 = http_post_json(f"{GATEWAY}/patches/{patch_id}/apply", {})
        remember_action(
            state,
            {
                "type": "apply_patch",
                "patch_id": patch_id,
                "ok": ok2,
                "output": out2[:1600],
            },
        )

        if ok2:
            log(f"PATCH APPLIED #{patch_id}")
        else:
            log(f"PATCH APPLY FAILED #{patch_id}: {out2[:400]}")


def any_dispatch_running() -> bool:
    rows = db_all(
        """
        SELECT id FROM dispatch_jobs
        WHERE status IN ('running','queued')
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return bool(rows)


def dispatch_repair_task(title: str, target_files: list[str], model: str = "llama3:latest") -> tuple[bool, str]:
    if any_dispatch_running():
        return False, "dispatch_already_running"

    task = (
        title
        + " اقرأ فقط أولاً. لا تحذف. لا تلمس ملفات التداول أو MT5 الحساسة. "
        + "إذا وجدت تعديلًا حقيقيًا، اقترح unified diff فقط على الملفات المحددة والآمنة. "
        + "لا تقترح نصائح عامة. لا تقترح patch فارغ. "
        + "اختبر py_compile فقط. "
        + "الملفات المستهدفة: "
        + ", ".join(target_files)
    )

    body = {
        "task": task,
        "max_agents": 4,
        "files_per_agent": 3,
        "chars_per_file": 5000,
        "ctx": 4096,
        "agent_roles": ["Backend", "Security", "Tester", "Reviewer"],
        "dispatch_model": model,
        "target_files": target_files,
    }

    return http_post_json(f"{GATEWAY}/dispatch/run", body, timeout=20)


def dispatch_proactive_improvements(state: dict[str, Any], health: dict[str, Any]) -> None:
    cycles = int(state.get("cycles", 0))
    # Run every 30 cycles (~10 min at 20s interval), offset=15 to avoid overlap with brain refresh
    if cycles % 30 != 15:
        return

    # Only dispatch when fully healthy — don't pile on broken systems
    if not all(v.get("ok") for v in health.values()):
        return

    idx = (cycles // 30) % len(PROACTIVE_IMPROVEMENTS)
    title, target_files = PROACTIVE_IMPROVEMENTS[idx]

    ok, out = dispatch_repair_task(title, target_files, model="llama3:latest")
    remember_action(
        state,
        {
            "type": "dispatch_proactive_improvement",
            "objective": title,
            "files": target_files,
            "ok": ok,
            "output": out[:1000],
        },
    )
    log(f"proactive improvement #{idx + 1}/{len(PROACTIVE_IMPROVEMENTS)}: ok={ok} target={target_files[0]}")


def detect_and_dispatch_repairs(state: dict[str, Any], health: dict[str, Any], compile_results: dict[str, Any]) -> None:
    broken_files = [rel for rel, res in compile_results.items() if not res.get("ok")]

    if broken_files:
        ok, out = dispatch_repair_task(
            "AutoRepair py_compile failures.",
            broken_files,
            model="llama3:latest",
        )
        remember_action(
            state,
            {
                "type": "dispatch_compile_repair",
                "files": broken_files,
                "ok": ok,
                "output": out[:1000],
            },
        )
        log(f"compile repair dispatch: ok={ok} files={broken_files}")
        return

    broken_services = [name for name, res in health.items() if not res.get("ok")]

    if broken_services:
        target_files = []

        for svc in broken_services:
            if svc == "chat":
                target_files.append("friday_chat_app.py")
            elif svc == "gateway":
                target_files.append("friday_local_gateway.py")
            elif svc == "scalper_dashboard":
                target_files.append("friday_scalper_live_dashboard.py")
            elif svc == "agents_browser":
                target_files.append("friday_agents_browser.py")

        if target_files:
            ok, out = dispatch_repair_task(
                f"AutoRepair service health failure: {', '.join(broken_services)}.",
                target_files,
                model="llama3:latest",
            )
            remember_action(
                state,
                {
                    "type": "dispatch_health_repair",
                    "services": broken_services,
                    "files": target_files,
                    "ok": ok,
                    "output": out[:1000],
                },
            )
            log(f"health repair dispatch: ok={ok} services={broken_services}")


def refresh_brain_and_maps(state: dict[str, Any]) -> None:
    tasks = [
        ("friday_brain.py", [sys.executable, str(ROOT / "friday_brain.py")]),
        ("friday_project_map.py", [sys.executable, str(ROOT / "friday_project_map.py")]),
        ("friday_genome_status_export.py", [sys.executable, str(ROOT / "friday_genome_status_export.py")]),
    ]

    for name, cmd in tasks:
        path = ROOT / name

        if not path.exists():
            continue

        ok, out = run_cmd(cmd, timeout=60)
        remember_action(
            state,
            {
                "type": "refresh_memory",
                "file": name,
                "ok": ok,
                "output": out[-1000:],
            },
        )


def supervisor_loop(interval: int = 20) -> None:
    state = load_state()
    log("FRIDAY AUTOPILOT SUPERVISOR STARTED")
    save_state(state)

    while True:
        try:
            state = load_state()
            state["cycles"] = int(state.get("cycles", 0) or 0) + 1

            health = check_health()
            compile_results = compile_safe_files()

            state["last_health"] = health
            state["last_compile"] = compile_results

            auto_apply_all_patches(state)
            detect_and_dispatch_repairs(state, health, compile_results)
            dispatch_proactive_improvements(state, health)

            if state["cycles"] % 6 == 0:
                refresh_brain_and_maps(state)

            save_state(state)
            log(f"cycle={state['cycles']} health={ {k:v['ok'] for k,v in health.items()} }")

        except KeyboardInterrupt:
            log("STOPPED BY USER")
            break

        except Exception as exc:
            log("SUPERVISOR ERROR: " + str(exc))
            log(traceback.format_exc())

        time.sleep(interval)


def main() -> None:
    interval = 20

    if len(sys.argv) > 1:
        try:
            interval = max(5, int(sys.argv[1]))
        except Exception:
            pass

    supervisor_loop(interval=interval)


if __name__ == "__main__":
    main()
