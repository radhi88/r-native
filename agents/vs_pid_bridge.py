#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Filesystem bridge between the MT5 PlutoBrain vault and a VS Code terminal PID.

The VS Code integrated terminal process is not a socket server, so this bridge
does not inject keystrokes. It exposes a stable vault-based heartbeat, inbox,
and outbox that local agents can read and write safely.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
BRAIN = BASE / "brain_vault"
CONFIG = BASE / "unified_config.json"
HEARTBEAT = BRAIN / "vs_pid_bridge.json"
MESSAGES = BRAIN / "vs_pid_messages.jsonl"
VENDOR_PLUTOBRAIN = ROOT / "vendor" / "plutobrain"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_pid(default: int) -> int:
    config = _read_json(CONFIG, {})
    try:
        return int(config.get("agents", {}).get("claude", {}).get("pid") or default)
    except Exception:
        return default


def _process_info(pid: int) -> dict[str, Any] | None:
    command = (
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\"; "
        "if ($p) { "
        "$p | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate "
        "| ConvertTo-Json -Compress "
        "}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception:
        return {"ProcessId": pid, "Name": "unknown", "CommandLine": text[:500]}


def _inline(value: Any) -> str:
    text = str(value or "")
    return text.replace("`", "'").replace("\r", " ").replace("\n", " ").strip()


def _write_bridge_note(pid: int, role: str, alive: bool, process: dict[str, Any] | None, message: str) -> None:
    inbox = BRAIN / "inbox" / f"vs-pid-{pid}.md"
    outbox = BRAIN / "inbox" / f"vs-pid-{pid}-outbox.md"
    process = process or {}
    status = "online" if alive else "offline"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(
        "\n".join(
            [
                f"# VS PID {pid} Bridge",
                "",
                f"Last heartbeat: {_now()}",
                f"Status: {status}",
                f"Role: {role}",
                f"Project: `{ROOT}`",
                f"PlutoBrain vault: `{BRAIN}`",
                f"Vendor PlutoBrain: `{VENDOR_PLUTOBRAIN}`",
                "",
                "## Process",
                f"- Name: `{_inline(process.get('Name'))}`",
                f"- Executable: `{_inline(process.get('ExecutablePath'))}`",
                f"- Parent PID: `{_inline(process.get('ParentProcessId'))}`",
                f"- Command line: `{_inline(process.get('CommandLine'))}`",
                "",
                "## Protocol",
                f"- Machine heartbeat: `agents/brain_vault/vs_pid_bridge.json`",
                f"- Message log: `agents/brain_vault/vs_pid_messages.jsonl`",
                f"- Reply/outbox: `agents/brain_vault/inbox/vs-pid-{pid}-outbox.md`",
                "",
                "## Latest Message",
                "",
                message.strip() or "Bridge heartbeat only.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if not outbox.exists():
        outbox.write_text(
            "\n".join(
                [
                    f"# VS PID {pid} Outbox",
                    "",
                    "Write replies, status notes, or tasks for the MT5/Codex side here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def _append_message(payload: dict[str, Any]) -> None:
    message = str(payload.get("message") or "").strip()
    if not message:
        return
    MESSAGES.parent.mkdir(parents=True, exist_ok=True)
    with MESSAGES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_once(pid: int, role: str, message: str, append_message: bool) -> dict[str, Any]:
    process = _process_info(pid)
    payload = {
        "timestamp": _now(),
        "pid": pid,
        "role": role,
        "alive": process is not None,
        "project_root": str(ROOT),
        "brain_vault": str(BRAIN),
        "vendor_plutobrain": str(VENDOR_PLUTOBRAIN),
        "message": message,
        "process": process or {},
    }
    _write_json(HEARTBEAT, payload)
    _write_bridge_note(pid, role, process is not None, process, message)
    if append_message:
        _append_message(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge a VS Code terminal PID into PlutoBrain.")
    parser.add_argument("--pid", type=int, default=None, help="VS Code integrated terminal PID.")
    parser.add_argument("--role", default="claude-vscode-terminal", help="Logical role for this PID.")
    parser.add_argument("--message", default="PlutoBrain is installed and linked to the MT5 project.")
    parser.add_argument("--loop", action="store_true", help="Keep refreshing the heartbeat.")
    parser.add_argument("--interval", type=float, default=10.0, help="Heartbeat interval in seconds.")
    parser.add_argument("--quiet", action="store_true", help="Suppress heartbeat stdout.")
    args = parser.parse_args()

    pid = args.pid if args.pid is not None else _config_pid(2804)
    first = True
    while True:
        payload = run_once(pid, args.role, args.message, append_message=first)
        if not args.quiet:
            print(
                f"[{payload['timestamp']}] VS PID {pid} "
                f"{'online' if payload['alive'] else 'offline'} -> {HEARTBEAT}"
            )
        if not args.loop:
            return 0 if payload["alive"] else 2
        first = False
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
