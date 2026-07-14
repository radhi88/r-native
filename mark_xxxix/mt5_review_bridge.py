from __future__ import annotations

import os
import json
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


_env_root = os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[1]
OUT = ROOT / "review_bridge_output"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"

# ضع Webhook n8n هنا لاحقًا بعد ما ننشئه
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "").strip()


SAFE_TITLE = "MT5_REVIEW_PACK"


def run_cmd(cmd: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (
            f"$ {cmd}\n\n"
            f"--- STDOUT ---\n{result.stdout}\n\n"
            f"--- STDERR ---\n{result.stderr}\n\n"
            f"--- RETURN CODE ---\n{result.returncode}\n"
        )
    except Exception as exc:
        return f"$ {cmd}\n\nERROR: {exc}\n"


def tail_file(path: Path, max_lines: int = 200) -> str:
    if not path.exists():
        return f"[MISSING] {path}\n"

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception as exc:
        return f"[READ_ERROR] {path}: {exc}\n"


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


def build_review_pack() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pack_dir = OUT / f"review_pack_{timestamp}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # 1) Commands
    commands = {
        "git_status.txt": "git status --short",
        "git_diff_stat.txt": "git diff --stat",
        "git_diff.patch": "git diff",
        "compileall_src_tests.txt": r".\.venv\Scripts\python.exe -m compileall src tests",
        "python_processes.txt": r'powershell -NoProfile -Command "Get-Process python,python3,code,node -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path,StartTime | Format-List"',
        "listening_ports.txt": r'powershell -NoProfile -Command "Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize"',
        "execution_scan.txt": r'powershell -NoProfile -Command "Get-ChildItem -Recurse -Include *.py | Where-Object { $_.FullName -notmatch ''\\(\.venv|venv|__pycache__|logs|archive|models|prepared|node_modules|patch_backups)\\'' } | Select-String -Pattern ''mt5\.order_send|order_send|TRADE_ACTION_DEAL|TRADE_ACTION_SLTP|TRADE_ACTION_REMOVE|CTrade|PositionModify''"',
    }

    cmd_dir = pack_dir / "command_outputs"
    cmd_dir.mkdir(exist_ok=True)

    for filename, cmd in commands.items():
        (cmd_dir / filename).write_text(run_cmd(cmd), encoding="utf-8", errors="replace")

    # 2) Copy reports
    reports_dir = pack_dir / "reports"
    reports_dir.mkdir(exist_ok=True)

    wanted_reports = [
        "19_DRY_RUN_RUNNER_SAFE_TEST.md",
        "20_DEGENERATE_RETRAIN_INCIDENT.md",
        "21_NUMERIC_SAFETY_PATCH.md",
        "22_PRE_DEMO_NUMERIC_GATE.md",
        "23_SESSION_HANDOFF_STATE.md",
        "24_GENOME_QUALITY_GATE.md",
        "25_BREEDING_POOL_SYSTEM.md",
        "26_APPROVED_GENOME_SELECTION_RULES.md",
        "27_GENOME_SAFETY_TEST_RESULTS.md",
        "28_REVIEW_PACK_SUMMARY.md",
    ]

    for name in wanted_reports:
        copy_if_exists(REPORTS / name, reports_dir / name)

    # 3) Copy key source files
    source_dir = pack_dir / "source_snapshot"
    key_files = [
        r"src\mt5_ai\core\genome_quality_gate.py",
        r"src\mt5_ai\core\breeding_pool.py",
        r"src\mt5_ai\core\numeric_safety.py",
        r"src\mt5_ai\gene_fitness_db.py",
        r"algory_retrain.py",
        r"tests\test_genome_quality_gate.py",
        r"config\trading_runtime.yaml",
        r"config\dry_run_simulation.yaml",
        r"config\live_micro_disabled.yaml",
    ]

    for rel in key_files:
        copy_if_exists(ROOT / rel, source_dir / rel)

    # 4) Tail logs
    log_dir = pack_dir / "log_tails"
    log_dir.mkdir(exist_ok=True)

    for log_name in [
        "signal_log.jsonl",
        "decision_log.jsonl",
        "conflict_log.jsonl",
        "risk_log.jsonl",
        "execution_log.jsonl",
        "fitness_safety_log.jsonl",
        "genome_quality_log.jsonl",
        "breeding_pool_log.jsonl",
        "error_log.jsonl",
    ]:
        (log_dir / f"{log_name}.tail.txt").write_text(
            tail_file(LOGS / log_name),
            encoding="utf-8",
            errors="replace",
        )

    # 5) Summary
    summary = {
        "title": SAFE_TITLE,
        "timestamp": timestamp,
        "root": str(ROOT),
        "mode": "REVIEW_ONLY",
        "hard_rules": [
            "No demo started",
            "No live trading enabled",
            "No algory_runner execution",
            "No MT5 orders sent by this bridge",
            "Review pack only",
        ],
        "next_required_gate": "GENOME_GATE_STATUS must be PASS before demo",
    }

    (pack_dir / "REVIEW_PACK_MANIFEST.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    (pack_dir / "README_REVIEW_PACK.md").write_text(
        f"""# MT5 Review Pack

Generated: {timestamp}

Mode: REVIEW_ONLY

This pack contains:
- reports
- git diff
- compile output
- execution scan
- running process snapshot
- log tails
- key source files

Hard rules:
- No demo was started by this script.
- No live trading was enabled.
- No MT5 order was sent.
- This is only for review.

Next gate:
GENOME_GATE_STATUS must be PASS before demo.
""",
        encoding="utf-8",
    )

    # 6) Zip
    zip_path = OUT / f"review_pack_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for file in pack_dir.rglob("*"):
            if file.is_file():
                z.write(file, file.relative_to(pack_dir))

    return zip_path


def send_to_n8n(zip_path: Path) -> None:
    if not N8N_WEBHOOK_URL:
        print("[INFO] N8N_WEBHOOK_URL is not set. Review pack created locally only.")
        return

    if requests is None:
        print("[ERROR] requests is not installed. Run: pip install requests")
        return

    with zip_path.open("rb") as f:
        files = {"file": (zip_path.name, f, "application/zip")}
        data = {
            "project": "MT5",
            "mode": "REVIEW_ONLY",
            "status": "REVIEW_PACK_READY",
            "note": "No demo/live execution. Review pack only.",
        }
        resp = requests.post(N8N_WEBHOOK_URL, data=data, files=files, timeout=120)

    print(f"[N8N] status={resp.status_code}")
    print(resp.text[:1000])


def main() -> int:
    print("[MT5 Review Bridge] Building review pack...")
    zip_path = build_review_pack()
    print(f"[DONE] Review pack created:")
    print(zip_path)

    send_to_n8n(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())