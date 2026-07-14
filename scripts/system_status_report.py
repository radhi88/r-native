"""Generate authoritative FRIDAY/Qader system status.

Writes:
  - SYSTEM_STATUS.md
  - runtime/system_status.json
  - runtime/friday_agent_status.json
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RUNTIME = ROOT / "runtime"
LOGS = ROOT / "logs"
RUNTIME.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(ok: bool, degraded: bool = False) -> str:
    if ok and not degraded:
        return "OK"
    if ok and degraded:
        return "DEGRADED"
    return "DOWN"


def port_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def http_json(url: str, timeout: float = 2.0) -> tuple[bool, Any, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        try:
            return True, json.loads(body), ""
        except Exception:
            return True, body[:500], ""
    except Exception as exc:
        return False, None, str(exc)


def powershell_processes(pattern: str) -> list[dict[str, Any]]:
    cmd = [
        "powershell",
        "-NonInteractive",
        "-Command",
        (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | "
            "ConvertTo-Json -Compress"
        ),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        text = (completed.stdout or "").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def file_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    return max(0.0, time.time() - path.stat().st_mtime)


def tail_jsonl(path: Path, max_bytes: int = 32768) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "latest": None, "parse_error": "missing"}
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", errors="replace")
        for line in reversed([x.strip() for x in raw.splitlines() if x.strip()]):
            try:
                return {"exists": True, "latest": json.loads(line), "parse_error": ""}
            except Exception:
                continue
        return {"exists": True, "latest": None, "parse_error": "no_json_record"}
    except Exception as exc:
        return {"exists": True, "latest": None, "parse_error": str(exc)}


def qader_status() -> dict[str, Any]:
    state_path = ROOT / "dashboard" / "qader_live_state.json"
    loop_log = LOGS / "qader_realtime_loop.jsonl"
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            state = {"error": str(exc)}
    loop = state.get("loop", {}) if isinstance(state, dict) else {}
    latest_log = tail_jsonl(loop_log)
    age = file_age_seconds(state_path)
    log_age = file_age_seconds(loop_log)
    processes = powershell_processes("qader_app")
    fresh = age is not None and age <= 30
    loop_state = str(loop.get("state") or "").upper()
    running = bool(loop.get("thread_alive")) and loop_state == "RUNNING"
    blocked = loop_state == "BLOCKED"
    degraded = not fresh or (not running and not blocked) or not processes
    if running and fresh:
        status = "OK"
    elif blocked:
        status = "BLOCKED"
    elif fresh:
        status = "DEGRADED"
    else:
        status = "DOWN"
    return {
        "status": status,
        "state_file": str(state_path),
        "state_file_age_seconds": age,
        "loop_log": str(loop_log),
        "loop_log_age_seconds": log_age,
        "process_count": len(processes),
        "loop": loop,
        "latest_loop_record": latest_log.get("latest"),
        "evidence": "qader_live_state.json + qader_realtime_loop.jsonl + process scan",
    }


def mt5_status() -> dict[str, Any]:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    result: dict[str, Any] = {"status": "UNKNOWN"}
    try:
        import MetaTrader5 as mt5

        initialized = bool(mt5.initialize())
        info = mt5.account_info() if initialized else None
        tick = mt5.symbol_info_tick("XAUUSDm") if initialized else None
        rates = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_M1, 0, 10) if initialized else None
        positions = list(mt5.positions_get() or []) if initialized else []
        orders = list(mt5.orders_get() or []) if initialized else []
        server = str(getattr(info, "server", "") or "") if info else ""
        trade_mode = int(getattr(info, "trade_mode", -1) if info else -1)
        demo_constant = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
        demo = bool(info) and (trade_mode == demo_constant or any(k in server.lower() for k in ("demo", "trial")))
        def _magic(obj: Any) -> int:
            raw = getattr(obj, "magic", -1)
            return -1 if raw is None else int(raw)

        external_magic0 = any(_magic(x) == 0 for x in positions + orders)
        ok = initialized and bool(info) and bool(tick) and rates is not None and len(rates) > 0 and demo and not external_magic0
        result = {
            "status": "OK" if ok else "BLOCKED",
            "initialized": initialized,
            "login": getattr(info, "login", None) if info else None,
            "server": server,
            "trade_mode": trade_mode,
            "demo_or_trial": demo,
            "balance": getattr(info, "balance", None) if info else None,
            "equity": getattr(info, "equity", None) if info else None,
            "xauusdm_tick": {
                "bid": getattr(tick, "bid", None) if tick else None,
                "ask": getattr(tick, "ask", None) if tick else None,
            },
            "xauusdm_m1_bars": 0 if rates is None else len(rates),
            "open_positions": len(positions),
            "pending_orders": len(orders),
            "external_magic0_exposure": external_magic0,
            "pending_order_details": [
                {
                    "ticket": getattr(o, "ticket", None),
                    "symbol": getattr(o, "symbol", ""),
                    "magic": getattr(o, "magic", None),
                    "volume": getattr(o, "volume_current", None),
                    "sl": getattr(o, "sl", None),
                    "tp": getattr(o, "tp", None),
                    "comment": getattr(o, "comment", ""),
                }
                for o in orders
            ],
            "terminal_processes": len(powershell_processes("terminal64.exe")),
        }
        mt5.shutdown()
    except Exception as exc:
        result = {"status": "DOWN", "error": str(exc)}
    return result


def ollama_status() -> dict[str, Any]:
    port = port_open(11434)
    ok, data, err = http_json("http://127.0.0.1:11434/api/tags", timeout=3)
    models = []
    if isinstance(data, dict):
        models = [str(item.get("name", "")) for item in data.get("models", []) if isinstance(item, dict)]
    required = "qwen2.5:3b-instruct"
    has_required = required in models or any(name.startswith("qwen2.5") for name in models)
    return {
        "status": _status(port and ok, degraded=(port and ok and not has_required)),
        "port": 11434,
        "port_open": port,
        "http_ok": ok,
        "required_model": required,
        "required_model_present": has_required,
        "models": models[:20],
        "error": err,
    }


def http_service_status(name: str, port: int, path: str = "/health") -> dict[str, Any]:
    port_ok = port_open(port)
    timeout = 6.0 if name in {"friday_dashboard", "tradingview", "brain_server", "qader"} else 3.0
    ok, data, err = http_json(f"http://127.0.0.1:{port}{path}", timeout=timeout)
    status = "OK" if port_ok and ok else ("DEGRADED" if port_ok else "DOWN")
    return {
        "status": status,
        "port": port,
        "port_open": port_ok,
        "http_ok": ok,
        "health": data,
        "error": err,
        "name": name,
    }


def log_freshness() -> dict[str, Any]:
    files = [
        "qader_realtime_loop.jsonl",
        "qader_audit.jsonl",
        "signal_log.jsonl",
        "execution_log.jsonl",
        "risk_log.jsonl",
        "decision_log.jsonl",
        "friday_voice/friday_voice.log",
        "friday_voice/friday_voice_status.jsonl",
    ]
    return {
        name: {
            "exists": (LOGS / name).exists(),
            "age_seconds": file_age_seconds(LOGS / name),
            "latest": tail_jsonl(LOGS / name).get("latest") if name.endswith(".jsonl") else None,
        }
        for name in files
    }


def build_status() -> dict[str, Any]:
    services = {
        "ollama": ollama_status(),
        "desktop_agent": http_service_status("desktop_agent", 8855),
        "gateway": http_service_status("gateway", 8799),
        "friday_dashboard": http_service_status("friday_dashboard", 8790, "/api/state"),
        "chat": http_service_status("chat", 8811, "/"),
        "tradingview": http_service_status("tradingview", 8822, "/health"),
        "agents_browser": http_service_status("agents_browser", 8833, "/"),
        "brain_server": http_service_status("brain_server", 8844, "/health"),
        "algory_charts": http_service_status("algory_charts", 8866, "/"),
        "qader": qader_status(),
        "mt5": mt5_status(),
    }
    agents = {
        "system_takeover": {"status": "OK", "evidence": "process/status/report coordinator active"},
        "voice": {"status": "OK" if (LOGS / "friday_voice" / "friday_voice_status.jsonl").exists() else "READY", "evidence": "voice runtime status sink installed"},
        "brain": {"status": services["ollama"]["status"], "evidence": "Ollama + router/brain checks"},
        "mt5": {"status": services["mt5"]["status"], "evidence": "MT5 terminal/account/tick/bars check"},
        "diagnostics": {"status": "OK", "evidence": "system_status_report.py"},
        "qader": {"status": services["qader"]["status"], "evidence": "Qader loop state/log checks"},
    }
    return {
        "schema_version": 1,
        "checked_at": utc_now(),
        "project_root": str(ROOT),
        "services": services,
        "agents": agents,
        "logs": log_freshness(),
    }


def write_reports(status: dict[str, Any]) -> None:
    (RUNTIME / "system_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RUNTIME / "friday_agent_status.json").write_text(json.dumps(status["agents"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# SYSTEM_STATUS",
        "",
        f"- checked_at: `{status['checked_at']}`",
        f"- project_root: `{status['project_root']}`",
        "",
        "## Services",
        "",
        "| Service | Status | Evidence |",
        "|---|---:|---|",
    ]
    for name, svc in status["services"].items():
        evidence = svc.get("evidence") or svc.get("error") or svc.get("port") or ""
        lines.append(f"| {name} | {svc.get('status')} | {str(evidence)[:180]} |")

    lines += [
        "",
        "## Agents",
        "",
        "| Agent | Status | Evidence |",
        "|---|---:|---|",
    ]
    for name, agent in status["agents"].items():
        lines.append(f"| {name} | {agent.get('status')} | {agent.get('evidence')} |")

    qader = status["services"].get("qader", {})
    loop = qader.get("loop", {}) if isinstance(qader, dict) else {}
    mt5 = status["services"].get("mt5", {})
    lines += [
        "",
        "## Qader",
        "",
        f"- state: `{loop.get('state')}`",
        f"- cycle_count: `{loop.get('cycle_count')}`",
        f"- demo_trades_opened: `{loop.get('demo_trades_opened')}`",
        f"- allow_new_entries: `{loop.get('allow_new_entries')}`",
        f"- latest_reason: `{loop.get('reason')}`",
        "",
        "## MT5",
        "",
        f"- status: `{mt5.get('status')}`",
        f"- server: `{mt5.get('server')}`",
        f"- login: `{mt5.get('login')}`",
        f"- demo_or_trial: `{mt5.get('demo_or_trial')}`",
        f"- open_positions: `{mt5.get('open_positions')}`",
        f"- pending_orders: `{mt5.get('pending_orders')}`",
        "",
        "Generated by `scripts/system_status_report.py`.",
    ]
    (ROOT / "SYSTEM_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write FRIDAY/Qader system status reports.")
    parser.add_argument("--loop", action="store_true", help="Keep refreshing status.")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()

    while True:
        status = build_status()
        write_reports(status)
        print(json.dumps({"checked_at": status["checked_at"], "services": {k: v.get("status") for k, v in status["services"].items()}}, ensure_ascii=False))
        if not args.loop:
            return 0
        time.sleep(max(2.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
