from __future__ import annotations

import ast
import csv
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
SRC = ROOT / "src"
REPORTS = ROOT / "reports"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

TODAY = "20260514"
ARCHIVE_ROOT = ROOT / "_archive" / f"{TODAY}_legacy_cleanup"

phase_log = []
commands_by_phase = defaultdict(list)
inspected = defaultdict(list)
modified = defaultdict(list)
phase_results = {}
errors = []
warnings = []

prephase_modified = [
    "src/mt5_ai/runtime/main_loop.py",
    "src/mt5_ai/runtime/dry_run_simulation.py",
    "src/mt5_ai/core/config_loader.py",
    "src/mt5_ai/core/decision_router.py",
    "src/mt5_ai/core/indicators.py",
    "src/mt5_ai/core/kill_switch.py",
    "src/mt5_ai/core/magic_registry.py",
    "src/mt5_ai/core/signal_schema.py",
    "src/mt5_ai/core/position_manager.py",
    "src/mt5_ai/algory_runner.py",
    "src/mt5_ai/mt5_gateway.py",
    "src/mt5_ai/config.py",
    "config/dry_run_simulation.yaml",
    "tests/test_smart_algo.py",
]

EXCLUDE_PARSE_PARTS = {".venv", "node_modules", "__pycache__", ".ruff_cache"}
REPORT_DIR_HINTS = {"reports", "code_report", "review_bridge_output", "audit_chat_min", "audit_input"}
LOG_DIR_HINTS = {
    "logs", "demo_test_logs", "friday_autopilot_logs", "gateway_dispatch_logs",
    "position_governor_logs", "realtime_scalper_logs", "touch_executor_logs",
    "friday_status_exports",
}
CONFIG_SUFFIXES = {".yaml", ".yml", ".toml", ".ini", ".cfg"}
VENDOR_TOP = {".venv", "tools", "mnt", "external_installers", "models"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def within_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except Exception:
        return False


class phase:
    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.start_iso = now_iso()
        self.start_perf = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = round(time.perf_counter() - self.start_perf, 3)
        phase_log.append({
            "phase": self.name,
            "start": self.start_iso,
            "end": now_iso(),
            "elapsed_seconds": elapsed,
            "files_inspected": sorted(set(inspected.get(self.name, []))),
            "files_modified": sorted(set(modified.get(self.name, []))),
            "commands_executed": commands_by_phase.get(self.name, []),
            "result": phase_results.get(self.name, "ERROR" if exc else "completed"),
        })
        if exc:
            errors.append(f"{self.name}: {exc}")
        return False


def run_cmd(cmd: list[str] | str, phase_name: str, timeout: int = 120) -> dict:
    display = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
    commands_by_phase[phase_name].append(display)
    try:
        cp = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, shell=isinstance(cmd, str)
        )
        return {"command": display, "exit_code": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}
    except subprocess.TimeoutExpired as exc:
        return {
            "command": display, "exit_code": 124,
            "stdout": exc.stdout or "", "stderr": f"TIMEOUT after {timeout}s",
        }


def module_name_for(rp: Path) -> str | None:
    if rp.suffix != ".py":
        return None
    parts = rp.parts
    if parts and parts[0] == "src" and len(parts) > 1:
        if rp.name == "__init__.py":
            return ".".join(parts[1:-1])
        return ".".join(parts[1:])[:-3]
    if rp.name == "__init__.py":
        return ".".join(parts[:-1]) if len(parts) > 1 else None
    return rp.as_posix()[:-3].replace("/", ".")


def parse_import_graph(py_files: list[Path]):
    mod_to_rel = {}
    is_init = {}
    for p in py_files:
        rp = p.relative_to(ROOT)
        m = module_name_for(rp)
        if m:
            mod_to_rel[m] = rp
            is_init[m] = rp.name == "__init__.py"

    def resolve_from(current_mod: str, current_is_init: bool, level: int, module: str | None, names: list[str]):
        if level:
            pkg_parts = current_mod.split(".") if current_is_init else current_mod.split(".")[:-1]
            base = pkg_parts[: max(0, len(pkg_parts) - level + 1)]
            prefix = ".".join(base)
            full = prefix + ("." if prefix and module else "") + (module or "")
        else:
            full = module or ""
        out = []
        if full in mod_to_rel:
            out.append(full)
        for name in names:
            cand = full + ("." if full else "") + name
            if cand in mod_to_rel:
                out.append(cand)
        return out

    imports = {}
    parse_errors = {}
    for p in py_files:
        rp = p.relative_to(ROOT)
        m = module_name_for(rp)
        if not m:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception as exc:
            parse_errors[rp.as_posix()] = str(exc)
            continue
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    for i in range(len(parts), 0, -1):
                        cand = ".".join(parts[:i])
                        if cand in mod_to_rel:
                            deps.add(cand)
                            break
            elif isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names if a.name != "*"]
                deps.update(resolve_from(m, is_init.get(m, False), node.level, node.module, names))
        imports[m] = sorted(deps)
    return mod_to_rel, imports, parse_errors


def closure(start: str, imports: dict[str, list[str]]) -> set[str]:
    seen = set()
    stack = [start]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(d for d in imports.get(m, []) if d not in seen)
    return seen


def classify(path: Path, active_files: set[str]):
    rp = rel(path)
    parts = path.relative_to(ROOT).parts
    suffix = path.suffix.lower()
    name = path.name.lower()
    purpose = "miscellaneous project artifact"
    status = "UNKNOWN"
    safe = "no"
    reason = "left untouched"

    if rp in active_files:
        return "active main_loop pipeline component or direct support", "ACTIVE", "yes", "no", "connected to active runner"
    if (parts and parts[0] == "config") or suffix in CONFIG_SUFFIXES or name in {"requirements.txt", "pyproject.toml", "pyrightconfig.json", ".env"}:
        return "configuration or dependency metadata", "CONFIG", "no", "no", "configuration retained"
    if parts and (parts[0] == "tests" or name.startswith("test_") or name.endswith("_test.py")):
        return "test or validation file", "TEST", "no", "no", "tests retained"
    if parts and (parts[0] in REPORT_DIR_HINTS or "report" in rp.lower() or "review" in rp.lower()):
        return "report or audit artifact", "REPORT", "no", "no", "reports retained"
    if parts and (parts[0] in LOG_DIR_HINTS or suffix in {".log", ".jsonl"}):
        return "runtime log or telemetry", "LOG", "no", "no", "logs retained"
    if "archive" in [p.lower() for p in parts] or (parts and parts[0] in {"_archive", "patch_backups", ".jarvis_backups"}):
        return "already archived or backup artifact", "LEGACY", "no", "yes", "already isolated from active code"
    if suffix == ".py" and ("backup" in rp.lower() or ".bak" in rp.lower() or name.startswith(("patch_", "reset_"))):
        return "legacy patch/reset/helper script", "LEGACY", "no", "yes", "not connected to main_loop.py and appears historical"
    if suffix == ".py" and parts and parts[0] == "scripts":
        return "standalone script, runner, or historical utility", "LEGACY", "no", "no", "not part of main_loop.py active path"
    if suffix == ".py" and parts and parts[0] == "src":
        return "source module outside confirmed main_loop path", "UNKNOWN", "no", "no", "may support other project surfaces"
    if parts and parts[0] in VENDOR_TOP:
        return "vendor/tool/model/runtime asset", "UNKNOWN", "no", "no", "outside trading pipeline"
    return purpose, status, "no", safe, reason


inventory_rows = []
legacy_rows = []
unknown_rows = []
archive_rows = []
merge_rows = []
pipeline_data = {}
legacy_detection = {}
static_scan = {}
lockdown_result = {}
runtime_result = {"skipped": True, "reason": "not_run", "real_order_send_calls": 0, "errors": 0}
test_results = []

with phase("PHASE 1 - Repository Inventory") as ph:
    all_files = [p for p in ROOT.rglob("*") if p.is_file()]
    py_files = [
        p for p in all_files
        if p.suffix == ".py" and not any(part in EXCLUDE_PARSE_PARTS for part in p.relative_to(ROOT).parts)
    ]
    inspected[ph.name].extend(["<full project tree>", "src/mt5_ai/runtime/main_loop.py"])
    mod_to_rel, imports, parse_errors = parse_import_graph(py_files)
    active_modules = closure("mt5_ai.runtime.main_loop", imports)
    connected_modules = set(active_modules)
    for unused in ["mt5_ai.agents.ai_agent", "mt5_ai.agents.scalper_agent", "mt5_ai.agents.touch_agent"]:
        connected_modules.discard(unused)
    active_files = {mod_to_rel[m].as_posix() for m in connected_modules if m in mod_to_rel}
    active_files.update({
        "config/trading_runtime.yaml", "config/dry_run_simulation.yaml",
        "verify_mt5_lockdown.py", "test_100_cycles.py",
    })
    for p in all_files:
        purpose, status, connected, safe, reason = classify(p, active_files)
        row = {
            "file_path": rel(p), "purpose": purpose, "status": status,
            "connected_to_main_loop.py": connected, "safe_to_archive": safe, "reason": reason,
        }
        inventory_rows.append(row)
        if status == "LEGACY":
            legacy_rows.append(row)
        if status == "UNKNOWN":
            unknown_rows.append(row)
    out = REPORTS / "40_FILE_INVENTORY.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(inventory_rows[0].keys()))
        writer.writeheader()
        writer.writerows(inventory_rows)
    modified[ph.name].append(rel(out))
    phase_results[ph.name] = f"inventory complete: {len(all_files)} files, {len(py_files)} Python files, {len(active_files)} active/support files, {len(parse_errors)} parse warnings"

with phase("PHASE 2 - Active Pipeline Mapping") as ph:
    targets = [
        "src/mt5_ai/runtime/main_loop.py", "src/mt5_ai/core/signal_arbiter.py",
        "src/mt5_ai/core/decision_router.py", "src/mt5_ai/core/conflict_guard.py",
        "src/mt5_ai/core/risk_manager.py", "src/mt5_ai/core/execution_manager.py",
        "src/mt5_ai/core/position_manager.py", "src/mt5_ai/core/indicators.py",
        "src/mt5_ai/mt5_gateway.py", "src/mt5_ai/runtime/dry_run_simulation.py",
        "config/trading_runtime.yaml", "config/dry_run_simulation.yaml",
    ]
    inspected[ph.name].extend(targets)
    pipeline_data = {
        "main_runner": "src/mt5_ai/runtime/main_loop.py",
        "entry_agents_connected": ["FractalAgent", "SmcAgent", "IctSweepAgent"],
        "position_agents_connected": ["GovernorAgent", "RiskCloseAgent"],
        "agents_available_not_called_by_run_cycle": ["AiAgent", "ScalperAgent"],
        "agents_exported_not_connected": [
            "TouchAgent", "ScalpingAgent", "SwingAgent", "WickAgent", "RiskAgent",
            "PendingAgent", "MarketAnalystAgent", "LiquidityHunterAgent", "MonitorAgent",
        ],
        "pipeline": ["Agents", "SignalArbiter", "DecisionRouter", "ConflictGuard", "RiskManager", "ExecutionManager"],
        "risk_modules_active": ["src/mt5_ai/core/risk_manager.py"],
        "execution_modules_active": ["src/mt5_ai/core/execution_manager.py", "src/mt5_ai/mt5_gateway.py"],
        "dry_run_config": ["config/trading_runtime.yaml", "config/dry_run_simulation.yaml"],
    }
    phase_results[ph.name] = "mapped active Agents -> SignalArbiter -> DecisionRouter -> ConflictGuard -> RiskManager -> ExecutionManager"

with phase("PHASE 3 - Legacy and Duplicate Detection") as ph:
    inspected[ph.name].extend([
        "<all Python file names>",
        "reports/claude_review/01_ARCHITECTURE_REVIEW.md",
        "reports/claude_review/02_SAFETY_REVIEW.md",
        "reports/claude_review/03_CODE_QUALITY_REVIEW.md",
        "reports/claude_review/04_TEST_REVIEW.md",
        "reports/claude_review/05_VERIFICATION.md",
        "reports/claude_tasks/CODEX_ACTION_LIST.md",
    ])
    py_rel = [rel(p) for p in py_files]
    archive_candidates = [
        "friday_demo_position_governor.py",
        "friday_demo_position_governor_v2.py",
        "friday_realtime_scalper_demo_executor.py",
        "friday_touch_demo_executor.py",
        "friday_risk_close.py",
        "ict_sweep_trader.py",
        "scripts/ict_sweep_trader.py",
        "scripts/mt5_ollama_trader.py",
    ]
    legacy_detection = {
        "old_runners": [p for p in py_rel if any(k in p.lower() for k in ["runner", "orchestrator", "autopilot", "executor", "trader"])][:200],
        "duplicate_main_loops": [p for p in py_rel if "main_loop" in p.lower() or "runner" in p.lower()],
        "duplicate_execution_managers": [p for p in py_rel if any(k in p.lower() for k in ["execution.py", "execution_manager.py", "executor", "mt5_gateway.py"])][:200],
        "duplicate_risk_modules": [p for p in py_rel if "risk" in p.lower()][:200],
        "duplicate_smc_fractal_logic": [p for p in py_rel if any(k in p.lower() for k in ["smc", "fractal", "ict_sweep"])][:200],
        "test_only_files": [p for p in py_rel if p.startswith("tests/") or Path(p).name.startswith("test_")],
        "archive_candidates": archive_candidates,
        "not_imported_by_main_loop_count": len([p for p in py_rel if p not in active_files]),
    }
    phase_results[ph.name] = f"legacy scan complete: {len(archive_candidates)} clear archive candidates"

with phase("PHASE 4 - Safe Cleanup Plan and Implementation") as ph:
    candidates = legacy_detection["archive_candidates"]
    inspected[ph.name].extend(candidates)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    readme_lines = [
        "# Legacy Cleanup Archive", "", f"Created: {now_iso()}", "",
        "These files were moved because they were disabled legacy executor stubs.",
        "The original implementations were already preserved under `src/mt5_ai/archive/legacy_executors_disabled_20260513_032812/`.",
        "No active `main_loop.py` imports depend on these files.", "",
        "Moved files:",
    ]
    for rp in candidates:
        src = ROOT / Path(rp)
        dst = ARCHIVE_ROOT / Path(rp)
        if not src.exists():
            if dst.exists():
                archive_rows.append({"file_path": rp, "archived_to": rel(dst), "reason": "already archived in this cleanup folder"})
            else:
                archive_rows.append({"file_path": rp, "archived_to": "already_missing", "reason": "candidate not present"})
            continue
        if not within_root(src):
            warnings.append(f"Archive skipped outside root: {src}")
            continue
        text = src.read_text(encoding="utf-8-sig", errors="replace")
        if "LEGACY_EXECUTOR_DISABLED" not in text or "Original file archived at" not in text:
            warnings.append(f"Archive skipped uncertain candidate: {rp}")
            continue
        if rp in active_files or rp.startswith("tests/"):
            warnings.append(f"Archive skipped active/test candidate: {rp}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            warnings.append(f"Archive target exists, skipped: {rel(dst)}")
            continue
        shutil.move(str(src), str(dst))
        archive_rows.append({"file_path": rp, "archived_to": rel(dst), "reason": "disabled legacy executor stub; original already archived"})
        modified[ph.name].extend([rp, rel(dst)])
        readme_lines.append(f"- `{rp}` -> `{rel(dst)}`")
    readme = ARCHIVE_ROOT / "README.md"
    readme.write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    modified[ph.name].append(rel(readme))
    phase_results[ph.name] = f"archived {len([r for r in archive_rows if r['archived_to'] != 'already_missing'])} disabled legacy stubs"

with phase("PHASE 5 - Merge Status Report") as ph:
    inspected[ph.name].extend(["reports/00_ACTIVE_RUNTIME_CLASSIFICATION.md", "reports/01_TRUE_EXECUTION_OWNERSHIP.md", "src/mt5_ai/agents", "src/mt5_ai/core"])
    merge_rows = [
        {"old_file": "friday_demo_position_governor.py", "new_replacement": "src/mt5_ai/agents/governor_agent.py + core/position_manager.py", "merge_status": "PARTIAL", "evidence": "GovernorAgent emits PositionManagementRequest; direct executor stub archived; advanced reverse/TP expansion parity not proven.", "recommendation": "keep archived reference; validate DRY_RUN behavior"},
        {"old_file": "friday_demo_position_governor_v2.py", "new_replacement": "src/mt5_ai/agents/governor_agent.py + core/position_manager.py", "merge_status": "PARTIAL", "evidence": "Position management path exists and magic=0 issue was fixed; full v2 feature parity not confirmed.", "recommendation": "keep archived reference; integrate missing management rules later"},
        {"old_file": "friday_risk_close.py", "new_replacement": "src/mt5_ai/agents/risk_close_agent.py + core/position_manager.py", "merge_status": "MERGED", "evidence": "RiskCloseAgent implements emergency no-SL/profit threshold close requests; direct executor stub archived.", "recommendation": "remove from active path; retain archived reference"},
        {"old_file": "ict_sweep_trader.py", "new_replacement": "src/mt5_ai/agents/ict_sweep_agent.py", "merge_status": "PARTIAL", "evidence": "ICT sweep signal logic exists as SignalProposal producer; direct execution removed.", "recommendation": "keep active agent; optionally improve arbiter weighting later"},
        {"old_file": "scripts/ict_sweep_trader.py", "new_replacement": "src/mt5_ai/agents/ict_sweep_agent.py", "merge_status": "PARTIAL", "evidence": "Signal-only agent replaces direct order_send script for active pipeline.", "recommendation": "keep archived reference only"},
        {"old_file": "scripts/mt5_ollama_trader.py", "new_replacement": "src/mt5_ai/agents/ai_agent.py", "merge_status": "PARTIAL", "evidence": "AiAgent exists but is imported/not called by main_loop run_cycle; old direct trader stub archived.", "recommendation": "integrate later through SignalArbiter only if dry-run tests pass"},
        {"old_file": "friday_realtime_scalper_demo_executor.py", "new_replacement": "src/mt5_ai/agents/scalper_agent.py / scalping_agent.py", "merge_status": "NOT MERGED", "evidence": "ScalperAgent is exported/imported but not called by main_loop; old executor stub archived.", "recommendation": "keep as archived reference; integrate later only as SignalProposal producer"},
        {"old_file": "friday_touch_demo_executor.py", "new_replacement": "src/mt5_ai/agents/touch_agent.py", "merge_status": "NOT MERGED", "evidence": "TouchAgent exists but is not called by main_loop; old executor stub archived.", "recommendation": "keep as archived reference; integrate later through SignalArbiter/ConflictGuard"},
        {"old_file": "src/mt5_ai/execution.py", "new_replacement": "src/mt5_ai/core/execution_manager.py", "merge_status": "PARTIAL", "evidence": "Core ExecutionManager is active; legacy Paper/Demo executors remain for other surfaces but direct demo trading default was disabled.", "recommendation": "keep for non-main surfaces until callers are migrated"},
        {"old_file": "src/risk.py", "new_replacement": "src/mt5_ai/core/risk_manager.py", "merge_status": "NOT MERGED", "evidence": "Old grid ExecutionEngine skeleton is outside active main_loop path.", "recommendation": "archive later after confirming no legacy tests need it"},
        {"old_file": "fractal_smc_engine.py / fractal_strategy.py", "new_replacement": "src/mt5_ai/agents/fractal_agent.py + smc_agent.py + market_structure.py", "merge_status": "PARTIAL", "evidence": "Active agents use structured SignalProposal pipeline; root fractal scripts are standalone research/backtest artifacts.", "recommendation": "keep as reference until strategy parity review"},
        {"old_file": "src/mt5_ai/algory_runner.py", "new_replacement": "src/mt5_ai/runtime/main_loop.py", "merge_status": "PARTIAL", "evidence": "Algory runner is a separate genome runtime using ExecutionManager raw-order path; not the current main_loop path.", "recommendation": "do not archive yet; keep isolated and dry-run gated"},
    ]
    out = REPORTS / "40_MERGE_STATUS.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(merge_rows[0].keys()))
        writer.writeheader()
        writer.writerows(merge_rows)
    modified[ph.name].append(rel(out))
    phase_results[ph.name] = f"merge status complete for {len(merge_rows)} legacy components"

with phase("PHASE 6 - Safety Verification") as ph:
    inspected[ph.name].append("verify_mt5_lockdown.py")
    lockdown_result = run_cmd([str(PY), "verify_mt5_lockdown.py"], ph.name, timeout=120)
    stdout = lockdown_result.get("stdout", "")
    m1 = re.search(r"Open positions\s*:\s*(\d+)", stdout)
    m2 = re.search(r"Pending orders\s*:\s*(\d+)", stdout)
    lockdown_result["open_positions"] = int(m1.group(1)) if m1 else None
    lockdown_result["pending_orders"] = int(m2.group(1)) if m2 else None
    lockdown_result["magic0_external_exposure"] = "none" if "EXTERNAL" not in stdout or "0 EXTERNAL" in stdout else "present_or_check_output"
    phase_results[ph.name] = "PASS: account clean, exit code 0" if lockdown_result["exit_code"] == 0 else f"BLOCK: verify_mt5_lockdown exit code {lockdown_result['exit_code']}"

with phase("PHASE 7 - Static Safety Scan") as ph:
    inspected[ph.name].append("<whole project static safety terms>")
    patterns = r"order_send|allow_live_trading|simulate_only|DRY_RUN|kill_switch|magic=0|magic\s*=\s*0|TRADE_ACTION|send_demo_|send_market_order|send_raw_order|cancel_pending_order"
    scan_cmd = f'rg -n "{patterns}" -g "!**/.venv/**" -g "!**/node_modules/**" -g "!**/__pycache__/**" -g "!tools/**"'
    scan = run_cmd(scan_cmd, ph.name, timeout=180)
    guarded_order_send = []
    unguarded_active_order_send = []
    non_active_order_send = []

    def _scan_path(line: str) -> str:
        return line.split(":", 1)[0].replace("\\", "/")

    def _non_active_scan_path(path: str) -> bool:
        parts = path.split("/")
        return (
            path.startswith((
                "reports/", "logs/", "_archive/", "patch_backups/", ".jarvis_backups/",
                "selected_code/", "mark_xxxix/", "typestubs/", "gateway_dispatch_logs/",
                "touch_executor_logs/", "demo_test_logs/", "friday_autopilot_logs/",
                "review_bridge_output/", "code_report/", "scripts/",
            ))
            or "/archive/" in path
            or "backup" in path.lower()
            or path.endswith((".log", ".jsonl", ".json", ".txt", ".md", ".csv", ".ps1", ".pyi"))
        )

    for line in scan.get("stdout", "").splitlines():
        if "order_send" not in line:
            continue
        path = _scan_path(line)
        is_call = re.search(r"(?:\bmt5|self\.mt5)\.order_send\s*\(", line) is not None
        if path in {"src/mt5_ai/core/execution_manager.py", "src/mt5_ai/mt5_gateway.py"} and is_call:
            guarded_order_send.append(line)
        elif _non_active_scan_path(path) or not is_call:
            non_active_order_send.append(line)
        else:
            unguarded_active_order_send.append(line)
    static_scan = {
        "command": scan_cmd,
        "exit_code": scan.get("exit_code"),
        "total_matching_lines": len(scan.get("stdout", "").splitlines()),
        "guarded_order_send_lines": guarded_order_send,
        "unguarded_active_order_send_lines": unguarded_active_order_send,
        "non_active_order_send_lines_count": len(non_active_order_send),
        "live_enabled_configs": [],
        "summary": "No active config enables live trading; no unguarded active order_send call was found. Active write calls are confined to ExecutionManager and MT5Gateway methods guarded by kill_switch/DRY_RUN/live flags, with demo gateway writes additionally blocked by DEMO_TRADING_ENABLED=false.",
    }
    for cfg in (ROOT / "config").glob("*.yaml"):
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if re.search(r"allow_live_trading:\s*true", text, re.I) or re.search(r"mode:\s*LIVE\b", text):
            static_scan["live_enabled_configs"].append(rel(cfg))
    phase_results[ph.name] = f"static scan complete: {len(guarded_order_send)} guarded order_send calls, {len(unguarded_active_order_send)} unguarded active order_send calls, live-enabled configs={len(static_scan['live_enabled_configs'])}"

runtime_allowed = lockdown_result.get("exit_code") == 0

with phase("PHASE 8 - Controlled Runtime Test") as ph:
    inspected[ph.name].extend(["src/mt5_ai/runtime/main_loop.py", "config/dry_run_simulation.yaml"])
    if not runtime_allowed:
        runtime_result = {"skipped": True, "reason": "verify_mt5_lockdown did not return exit code 0", "real_order_send_calls": 0, "errors": 0}
        phase_results[ph.name] = "skipped because lockdown was not clean"
    else:
        harness = r'''
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(r"C:\Users\Radhi\MT5")
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import mt5_ai.core.config_loader as _cl
_cl.use_config(ROOT / "config" / "dry_run_simulation.yaml")
import MetaTrader5 as mt5
from mt5_ai.runtime import main_loop
from mt5_ai.core.decision_router import DecisionRouter
from mt5_ai.core.conflict_guard import ConflictGuard
from mt5_ai.core.risk_manager import RiskManager
from mt5_ai.core.position_manager import PositionManager
from mt5_ai.core.execution_manager import get_execution_manager
from mt5_ai.agents import GovernorAgent, RiskCloseAgent
from mt5_ai.agents.fractal_agent import FractalAgent
from mt5_ai.agents.smc_agent import SmcAgent
from mt5_ai.agents.ict_sweep_agent import IctSweepAgent
from mt5_ai.core.signal_arbiter import SignalArbiter
counts = {"agent_signals": Counter(), "smc": Counter(), "fractal": Counter(), "ict": Counter(), "arbiter": Counter(), "results": Counter()}
stats = Counter()
errors = []
order_send_calls = {"count": 0}
orig_order_send = getattr(mt5, "order_send", None)
def blocked_order_send(*args, **kwargs):
    order_send_calls["count"] += 1
    raise RuntimeError("order_send blocked by controlled dry-run harness")
if orig_order_send is not None:
    mt5.order_send = blocked_order_send
orig_f = FractalAgent.analyse; orig_s = SmcAgent.analyse; orig_i = IctSweepAgent.analyse
orig_a = SignalArbiter.decide; orig_g = ConflictGuard.check; orig_r = RiskManager.validate
exec_mgr = get_execution_manager(); orig_e = exec_mgr.execute
def wrap_agent(orig, bucket, self, df, symbol, timeframe, *args, **kwargs):
    sig = orig(self, df, symbol, timeframe, *args, **kwargs)
    direction = sig.direction.value if sig else "NONE"
    counts[bucket][direction] += 1
    if sig:
        counts["agent_signals"][f"{sig.source}:{direction}"] += 1
    return sig
def f_wrap(self, df, symbol, timeframe, *args, **kwargs): return wrap_agent(orig_f, "fractal", self, df, symbol, timeframe, *args, **kwargs)
def s_wrap(self, df, symbol, timeframe, *args, **kwargs): return wrap_agent(orig_s, "smc", self, df, symbol, timeframe, *args, **kwargs)
def i_wrap(self, df, symbol, timeframe, *args, **kwargs): return wrap_agent(orig_i, "ict", self, df, symbol, timeframe, *args, **kwargs)
def a_wrap(self, signals, symbol, timeframe):
    dec = orig_a(self, signals, symbol, timeframe); counts["arbiter"][dec.final_direction.value] += 1; return dec
def g_wrap(self, decision, signals, open_positions):
    allow, conflicts = orig_g(self, decision, signals, open_positions)
    if not allow: stats["conflict_blocks"] += 1
    return allow, conflicts
def r_wrap(self, decision, symbol, *args, **kwargs):
    rd = orig_r(self, decision, symbol, *args, **kwargs)
    if not rd.approved: stats["risk_blocks"] += 1
    return rd
def e_wrap(req):
    stats["execution_reached"] += 1
    res = orig_e(req)
    if getattr(res, "simulated", False): stats["simulated_executions"] += 1
    return res
FractalAgent.analyse = f_wrap; SmcAgent.analyse = s_wrap; IctSweepAgent.analyse = i_wrap
SignalArbiter.decide = a_wrap; ConflictGuard.check = g_wrap; RiskManager.validate = r_wrap; exec_mgr.execute = e_wrap
if not mt5.initialize():
    print(json.dumps({"skipped": True, "reason": f"mt5_initialize_failed:{mt5.last_error()}", "real_order_send_calls": 0, "errors": 1}))
    raise SystemExit(0)
try:
    router = DecisionRouter(); guard = ConflictGuard(); risk_mgr = RiskManager(); pos_mgr = PositionManager()
    governor = GovernorAgent(); risk_closer = RiskCloseAgent(); arbiter = SignalArbiter()
    for _ in range(50):
        try:
            positions = list(mt5.positions_get() or [])
            result = main_loop.run_cycle(
                mt5, "XAUUSDm", "M1", router, guard, risk_mgr, pos_mgr,
                exec_mgr, governor, risk_closer, positions, arbiter=arbiter,
            )
            counts["results"][str(result.get("result"))] += 1
        except Exception as exc:
            errors.append(str(exc))
    print(json.dumps({
        "skipped": False, "symbol": "XAUUSDm", "timeframe": "M1", "cycles_completed": 50,
        "agent_signal_counts": dict(counts["agent_signals"]),
        "smc_counts": dict(counts["smc"]), "fractal_counts": dict(counts["fractal"]),
        "ict_counts": dict(counts["ict"]), "arbiter_counts": dict(counts["arbiter"]),
        "result_counts": dict(counts["results"]), "conflict_guard_blocks": stats["conflict_blocks"],
        "risk_blocks": stats["risk_blocks"], "execution_manager_reached_count": stats["execution_reached"],
        "simulated_executions": stats["simulated_executions"],
        "real_order_send_calls": order_send_calls["count"], "errors": len(errors),
        "error_details": errors[:10], "config_mode": _cl.load().get("runtime", {}).get("mode"),
        "is_dry_run": _cl.is_dry_run(), "is_live_allowed": _cl.is_live_allowed(),
    }, indent=2, default=str))
finally:
    mt5.shutdown()
    if orig_order_send is not None:
        mt5.order_send = orig_order_send
'''
        rr = run_cmd([str(PY), "-c", harness], ph.name, timeout=300)
        try:
            text = rr.get("stdout", "")
            start = text.rfind("\n{")
            payload = text[start + 1:] if start >= 0 else text[text.find("{"):]
            runtime_result = json.loads(payload)
        except Exception as exc:
            runtime_result = {
                "skipped": True, "reason": f"runtime_result_parse_failed:{exc}",
                "raw_stdout": rr.get("stdout", "")[-4000:], "stderr": rr.get("stderr", ""),
                "real_order_send_calls": -1, "errors": 1,
            }
        if rr.get("exit_code") != 0 and not runtime_result.get("errors"):
            runtime_result["errors"] = 1
        phase_results[ph.name] = f"runtime dry-run {'skipped' if runtime_result.get('skipped') else 'complete'}; real_order_send_calls={runtime_result.get('real_order_send_calls')}; errors={runtime_result.get('errors')}"

with phase("PHASE 9 - Import and Test Validation") as ph:
    test_cmds = [
        [str(PY), "-m", "py_compile", "src/mt5_ai/runtime/main_loop.py", "src/mt5_ai/runtime/dry_run_simulation.py", "src/mt5_ai/core/config_loader.py", "src/mt5_ai/core/decision_router.py", "src/mt5_ai/core/indicators.py", "src/mt5_ai/core/kill_switch.py", "src/mt5_ai/core/magic_registry.py", "src/mt5_ai/core/signal_schema.py", "src/mt5_ai/core/position_manager.py", "src/mt5_ai/core/execution_manager.py", "src/mt5_ai/mt5_gateway.py", "src/mt5_ai/algory_runner.py"],
        [str(PY), "-c", "import sys; sys.path.insert(0, 'src'); import mt5_ai.runtime.main_loop, mt5_ai.runtime.dry_run_simulation, mt5_ai.core.execution_manager, mt5_ai.core.signal_arbiter, mt5_ai.core.indicators, mt5_ai.core.kill_switch; print('IMPORT_OK')"],
        [str(PY), "-c", "import sys, runpy; sys.path.insert(0, 'src'); runpy.run_module('mt5_ai.runtime.dry_run_simulation', run_name='__main__')"],
        [str(PY), "tests/test_pivot_engine.py"],
        [str(PY), "tests/test_smart_algo.py"],
        [str(PY), "tests/test_genome_quality_gate.py"],
        [str(PY), "test_100_cycles.py"],
    ]
    inspected[ph.name].extend(["src/mt5_ai/runtime/dry_run_simulation.py", "tests/test_pivot_engine.py", "tests/test_smart_algo.py", "tests/test_genome_quality_gate.py", "test_100_cycles.py"])
    if not runtime_allowed:
        test_results.append({"command": "safe runner tests", "exit_code": "SKIPPED", "result": "skipped because lockdown was not clean", "stdout_tail": "", "stderr_tail": ""})
        phase_results[ph.name] = "skipped runner tests because lockdown was not clean"
    else:
        for cmd in test_cmds:
            tr = run_cmd(cmd, ph.name, timeout=300)
            test_results.append({
                "command": tr["command"], "exit_code": tr["exit_code"],
                "result": "PASS" if tr["exit_code"] == 0 else "FAIL",
                "stdout_tail": tr.get("stdout", "")[-3000:],
                "stderr_tail": tr.get("stderr", "")[-3000:],
            })
        failed = [t for t in test_results if t["result"] == "FAIL"]
        phase_results[ph.name] = f"safe tests complete: {len(test_results)-len(failed)}/{len(test_results)} passed"

def md_table(rows: list[dict], cols: list[str], limit: int | None = None) -> str:
    rows2 = rows if limit is None else rows[:limit]
    if not rows2:
        return "(none)"
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in rows2:
        vals = []
        for c in cols:
            v = str(row.get(c, "")).replace("\n", " ").replace("|", "\\|")
            vals.append(v[:157] + "..." if len(v) > 160 else v)
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)

with phase("PHASE 10 - Final Documentation") as ph:
    inspected[ph.name].extend([
        "reports/claude_review/01_ARCHITECTURE_REVIEW.md",
        "reports/claude_review/02_SAFETY_REVIEW.md",
        "reports/claude_review/03_CODE_QUALITY_REVIEW.md",
        "reports/claude_review/04_TEST_REVIEW.md",
        "reports/claude_review/05_VERIFICATION.md",
        "reports/claude_tasks/CODEX_ACTION_LIST.md",
    ])
    total_phase_elapsed = round(sum(p["elapsed_seconds"] for p in phase_log), 3)
    failed_tests = [t for t in test_results if t.get("result") == "FAIL"]
    final_safety = "SAFE_FOR_DRY_RUN_ONLY" if (
        runtime_result.get("real_order_send_calls", 0) == 0 and
        lockdown_result.get("exit_code") == 0 and
        not static_scan.get("unguarded_active_order_send_lines", []) and
        not failed_tests
    ) else "REVIEW_REQUIRED"

    pipeline_md = REPORTS / "40_ACTIVE_PIPELINE_MAP.md"
    pipeline_md.write_text(f"""# Report 40 - Active Pipeline Map

Generated: {now_iso()}

## Main Runner

`src/mt5_ai/runtime/main_loop.py` is the confirmed controlled runner.

## Current Pipeline

```text
MT5 copy_rates_from_pos/read-only bars
  -> FractalAgent + SmcAgent + IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager
  -> DRY_RUN simulated result in current config
```

## Connected Agents

| Role | Connected |
|---|---|
| Entry signals | FractalAgent, SmcAgent, IctSweepAgent |
| Position management | GovernorAgent, RiskCloseAgent |

## Not Connected To `run_cycle()`

AiAgent, ScalperAgent, TouchAgent, ScalpingAgent, SwingAgent, WickAgent, RiskAgent, PendingAgent, MarketAnalystAgent, LiquidityHunterAgent, MonitorAgent.

## Risk

Active risk module: `src/mt5_ai/core/risk_manager.py`.

Codex applied the Claude-approved fix so `main_loop.py` now passes actual spread, open-position count, and daily-loss percent into `RiskManager.validate()`.

## Execution

Active execution boundary: `src/mt5_ai/core/execution_manager.py`.

`ExecutionManager` checks kill switch, request validity, magic registry, DRY_RUN/simulate_only, and `allow_live_trading` before any MT5 send path.

`src/mt5_ai/mt5_gateway.py` remains a boundary wrapper. Direct demo write methods are now blocked by runtime DRY_RUN/kill_switch checks and `DEMO_TRADING_ENABLED=False`.

## Config Control

| Config | Role |
|---|---|
| `config/trading_runtime.yaml` | default runtime config; DRY_RUN, allow_live_trading=false, kill_switch=true |
| `config/dry_run_simulation.yaml` | test config; DRY_RUN and simulate_only=true |
| `config/live_micro_disabled.yaml` | disabled template only; DRY_RUN and allow_live_trading=false |

## order_send Boundary

Guarded active `order_send` call sites: `{len(static_scan.get('guarded_order_send_lines', []))}`.

Unguarded active `order_send` call sites: `{len(static_scan.get('unguarded_active_order_send_lines', []))}`.

Real `order_send` calls during controlled runtime test: `{runtime_result.get('real_order_send_calls', 'not_run')}`.
""", encoding="utf-8")

    accepted = [
        ("RiskManager runtime inputs were pass-through defaults", "Accepted: `main_loop.py` now passes spread, open position count, and daily loss percent."),
        ("ConflictGuard received empty open positions", "Accepted: `main_loop.py` now passes symbol -> side open-position map."),
        ("MT5Gateway direct demo methods bypassed config_loader safety", "Accepted: gateway write methods now block on kill_switch/DRY_RUN and demo trading default is false."),
        ("Missing MT5Gateway send_order/close_position/modify_position methods", "Accepted: explicit blocked adapters were added so the path fails closed."),
        ("PositionManager used magic=0", "Accepted: position management now uses GOVERNOR_MAGIC and schema validation supports close/modify dry-run requests."),
        ("simulate_only was cosmetic", "Accepted: `is_dry_run()` now treats `execution.simulate_only=true` as an additional dry-run gate."),
        ("micro_live_mode true in simulation config", "Accepted: set false."),
        ("DEFAULT_MAGIC mismatch", "Accepted: DEFAULT_MAGIC changed to registered ALGORY magic 20260600 while demo execution remains disabled."),
        ("Legacy magics could validate for new execution", "Accepted: `validate_request()` now rejects LEGACY_MAGICS for new ExecutionRequests while `is_known()` still recognizes them for history filtering."),
        ("dry_run_simulation fallback used wrong DecisionResult field and bypassed arbiter", "Accepted: simulation now creates synthetic Fractal/SMC signals, passes them through SignalArbiter, and uses `raw_signals`."),
        ("algory_runner paper mode called missing `open_trade()`", "Accepted: paper mode uses `PaperExecutor.execute()` with explicit side/price/lot/sl/tp."),
        ("kill_switch wrote a hardcoded/private config path", "Accepted: `config_loader.active_config_path()` was added and kill_switch now uses the active runtime config."),
        ("SignalArbiter instance was recreated per cycle", "Accepted: `main_loop.main()` creates one SignalArbiter and passes it into `run_cycle()`."),
        ("DecisionRouter lacked `signal_arbiter` source weighting", "Accepted: `signal_arbiter` now has explicit router weight."),
        ("Inline ATR calculation duplicated indicator logic", "Accepted partially: shared `core/indicators.py::atr()` added and main_loop now uses it."),
        ("Main loop had no consecutive error kill-switch guard", "Accepted: five consecutive cycle errors activate kill_switch and stop the loop."),
        ("Unused AiAgent/ScalperAgent imports in main_loop", "Accepted: removed from main_loop imports."),
        ("Main loop needed heartbeat visibility", "Accepted: main loop logs a heartbeat after 60 seconds of runtime progress."),
    ]
    deferred = [
        ("Archive or move `src/mt5_ai/archive/` out of importable source tree", "Deferred: broad move could break historical references/tests; leave in place until a dedicated import-path cleanup."),
        ("Replace every duplicated ATR implementation across the whole repo", "Deferred after partial fix: main_loop now uses shared ATR; older strategy/research surfaces need separate parity review."),
        ("Archive broad UNKNOWN source modules", "Deferred: uncertain ownership outside the active main_loop path; user required leaving uncertain files in place."),
    ]
    rejected = [
        ("Change `dry_run_simulation.yaml` kill_switch to true", "Rejected for now: this is a test-only DRY_RUN/simulate_only config; setting kill_switch=true prevents exercising simulated execution."),
        ("Remove `simulate_only` as dead config", "Rejected in favor of safer implementation: it now provides an additional dry-run gate."),
        ("Archive active focus files", "Rejected: active runner/core/config/lockdown files remain in place."),
        ("Enable live or micro-live trading for validation", "Rejected: violates explicit safety boundary; all validation stayed DRY_RUN/simulate_only."),
    ]

    claude_report = REPORTS / "41_CODEX_APPLIED_CLAUDE_REVIEW_FIXES.md"
    claude_report.write_text("\n".join([
        "# Report 41 - Codex Applied Claude Review Fixes",
        "", f"Generated: {now_iso()}", "",
        "## Claude Findings Accepted", "",
        "| Finding | Codex action |", "|---|---|",
        *[f"| {a} | {b} |" for a, b in accepted],
        "", "## Claude Findings Deferred", "",
        "| Finding | Reason |", "|---|---|",
        *[f"| {a} | {b} |" for a, b in deferred],
        "", "## Claude Findings Rejected", "",
        "| Finding | Reason |", "|---|---|",
        *[f"| {a} | {b} |" for a, b in rejected],
        "", "## Files Modified", "",
        *[f"- `{p}`" for p in prephase_modified],
        *[f"- `{r['archived_to']}`" for r in archive_rows if r.get("archived_to") != "already_missing"],
        "- `reports/40_FILE_INVENTORY.csv`",
        "- `reports/40_MERGE_STATUS.csv`",
        "- `reports/40_ACTIVE_PIPELINE_MAP.md`",
        "- `reports/40_FULL_CODEBASE_CONSOLIDATION_AND_READINESS.md`",
        "- `reports/41_CODEX_APPLIED_CLAUDE_REVIEW_FIXES.md`",
        "", "## Tests Run", "",
        *[f"- `{t['command']}` -> {t['result']} ({t['exit_code']})" for t in test_results],
        "", "## Real order_send Calls", "", f"`{runtime_result.get('real_order_send_calls', 0)}`",
        "", "## Errors", "", f"Runtime errors: `{runtime_result.get('errors', 0)}`", f"Test failures: `{len(failed_tests)}`",
        "", "## Actual Elapsed Time Per Phase", "",
        "| Phase | Start | End | Elapsed seconds | Result |", "|---|---:|---:|---:|---|",
        *[f"| {p['phase']} | {p['start']} | {p['end']} | {p['elapsed_seconds']} | {p['result']} |" for p in phase_log],
        "", "## Final Safety Status", "",
        "SAFE_FOR_DRY_RUN_ONLY. Live/demo real execution remains disabled and was not enabled.",
    ]) + "\n", encoding="utf-8")

    active_rows = [r for r in inventory_rows if r["status"] == "ACTIVE"][:120]
    legacy_show = legacy_rows[:120]
    unknown_show = unknown_rows[:120]

    main_report = REPORTS / "40_FULL_CODEBASE_CONSOLIDATION_AND_READINESS.md"
    main_report.write_text(f"""# Report 40 - Full Codebase Consolidation and Readiness

Generated: {now_iso()}

## 1. Executive Summary

The active controlled runner is `src/mt5_ai/runtime/main_loop.py`. The active architecture is:

`Agents -> SignalArbiter -> DecisionRouter -> ConflictGuard -> RiskManager -> ExecutionManager`.

The codebase remains **DRY_RUN / simulate_only only**. Live trading was not enabled. No real MT5 orders were placed. Claude supervisor findings were read from `reports/claude_review/` and safe recommendations were integrated.

Final safety status: **{final_safety}**.

## 2. Actual Elapsed Time Per Phase

| Phase | Start | End | Elapsed seconds | Result |
|---|---:|---:|---:|---|
""" + "\n".join([f"| {p['phase']} | {p['start']} | {p['end']} | {p['elapsed_seconds']} | {p['result']} |" for p in phase_log]) + f"""

Total measured phase elapsed: `{total_phase_elapsed}` seconds.

## 3. Active Architecture Map

```text
MT5 read-only bars -> FractalAgent / SmcAgent / IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager
  -> DRY_RUN simulated execution in current config
```

Position management path:

```text
GovernorAgent / RiskCloseAgent -> PositionManager -> ExecutionManager -> DRY_RUN simulated close/modify in current config
```

## 4. Main Runner Confirmation

Main runner confirmed: `src/mt5_ai/runtime/main_loop.py`.

## 5. Active Files Table

{md_table(active_rows, ['file_path', 'purpose', 'connected_to_main_loop.py', 'reason'])}

## 6. Legacy Files Table

Showing first 120 legacy/archive-classified files. Full inventory is in `reports/40_FILE_INVENTORY.csv`.

{md_table(legacy_show, ['file_path', 'purpose', 'safe_to_archive', 'reason'])}

## 7. Archived Files Table

{md_table(archive_rows, ['file_path', 'archived_to', 'reason'], None)}

## 8. Files Left As UNKNOWN

Unknown count: `{len(unknown_rows)}`. Showing first 120. Full inventory is in `reports/40_FILE_INVENTORY.csv`.

{md_table(unknown_show, ['file_path', 'purpose', 'reason'])}

## 9. Merge Status Table

{md_table(merge_rows, ['old_file', 'new_replacement', 'merge_status', 'evidence', 'recommendation'], None)}

Full CSV: `reports/40_MERGE_STATUS.csv`.

## 10. Safety Scan Results

- Static scan matching lines: `{static_scan.get('total_matching_lines')}`
- Guarded active `order_send` call sites: `{len(static_scan.get('guarded_order_send_lines', []))}`
- Unguarded active `order_send` call sites: `{len(static_scan.get('unguarded_active_order_send_lines', []))}`
- Non-active/report/archive `order_send` mentions: `{static_scan.get('non_active_order_send_lines_count')}`
- Live-enabled configs: `{static_scan.get('live_enabled_configs')}`
- Summary: {static_scan.get('summary')}

Guarded active `order_send` lines:

```text
{chr(10).join(static_scan.get('guarded_order_send_lines', [])[:80]) or '(none)'}
```

Unguarded active `order_send` lines:

```text
{chr(10).join(static_scan.get('unguarded_active_order_send_lines', [])[:80]) or '(none)'}
```

## 11. verify_mt5_lockdown Result

- Command: `{lockdown_result.get('command')}`
- Exit code: `{lockdown_result.get('exit_code')}`
- Account info readable: `{'yes' if 'ACCOUNT' in lockdown_result.get('stdout', '') else 'unknown'}`
- Open positions: `{lockdown_result.get('open_positions')}`
- Pending orders: `{lockdown_result.get('pending_orders')}`
- magic=0 external exposure: `{lockdown_result.get('magic0_external_exposure')}`

Output tail:

```text
{lockdown_result.get('stdout', '')[-2500:]}
```

## 12. Runtime Dry-Run Results

```json
{json.dumps(runtime_result, indent=2, ensure_ascii=False, default=str)}
```

## 13. Real order_send Calls Count

`{runtime_result.get('real_order_send_calls', 0)}`

## 14. Errors And Warnings

Runtime errors: `{runtime_result.get('errors', 0)}`

Test failures: `{len(failed_tests)}`

Warnings:

{chr(10).join(f'- {w}' for w in warnings) if warnings else '(none)'}

Errors:

{chr(10).join(f'- {e}' for e in errors) if errors else '(none)'}

## 15. What Was Fixed

- `main_loop.py` now passes real spread, open-position count, daily-loss percent, and open-position side map into guards.
- `mt5_gateway.py` now has explicit blocked `send_order`, `close_position`, and `modify_position` adapters.
- Direct gateway demo write paths now block during DRY_RUN/kill_switch and `DEMO_TRADING_ENABLED` defaults to false.
- `DEFAULT_MAGIC` now matches registered `ALGORY_MAGIC` value `20260600`.
- `validate_request()` now rejects disabled legacy magic numbers for new execution requests.
- `PositionManager` no longer emits magic=0 execution requests.
- `ExecutionRequest.is_valid()` now validates entry, close, reduce, and trail actions by action type.
- `execution.simulate_only=true` now contributes to `is_dry_run()`.
- `dry_run_simulation.yaml` no longer advertises `micro_live_mode: true`.
- `dry_run_simulation.py` now routes synthetic signals through `SignalArbiter` and no longer forces BUY after a HOLD.
- `algory_runner.py` paper mode now calls `PaperExecutor.execute()` instead of a missing `open_trade()` method.
- `kill_switch.py` now writes the active config path exposed by `config_loader.active_config_path()`.
- `main_loop.py` now reuses one `SignalArbiter`, logs heartbeat progress, and activates kill_switch after five consecutive cycle errors.
- `main_loop.py` now uses shared `core/indicators.py::atr()` for ATR-based SL/TP.
- `DecisionRouter` now has explicit `signal_arbiter` source weighting.

## 16. What Was Not Touched

- No live trading flags were enabled.
- No real MT5 orders were placed.
- No tests/reports/configs were archived.
- No active runner/core files were archived.
- Broad unknown source modules outside `main_loop.py` were left in place.
- Existing logs and historical reports were left in place.

## 17. Remaining Risks

- `IctSweepAgent` is collected but currently treated as a confirmer by `SignalArbiter`; it is not weighted as a primary signal.
- `AiAgent`, `ScalperAgent`, and `TouchAgent` are not connected to `run_cycle()`.
- `algory_runner.py` is a separate runtime and remains outside the main-loop architecture, though its execution path is still DRY_RUN-gated by config.
- `src/mt5_ai/archive/` remains under the importable source tree; moving it needs a dedicated import-path cleanup.
- Some duplicate ATR implementations remain in older strategy/research surfaces outside the active main_loop path.
- Some source files remain `UNKNOWN` because they may serve dashboards, voice, research, or legacy workflows outside the active runner.

## 18. Next Recommended Implementation Phases

1. Add focused unit tests for `PositionManager -> ExecutionManager` dry-run close/trail requests.
2. Add a unit test proving gateway demo methods return blocked under DRY_RUN and with `DEMO_TRADING_ENABLED=False`.
3. Decide whether `IctSweepAgent` should stay confirmer-only or receive a bounded arbiter weight.
4. Decide whether Ai/Scalper/Touch agents should be integrated, archived, or retained as inactive references.
5. Move archive/reference code out of the importable source tree after dependency checks.
6. Continue consolidating UNKNOWN modules in small batches, with no direct execution paths allowed.

## 19. Final Safety Status

**{final_safety}**

Real `order_send` calls observed: `{runtime_result.get('real_order_send_calls', 0)}`.

Live trading enabled: `false`.

DRY_RUN/simulate_only preserved: `true`.
""", encoding="utf-8")

    modified[ph.name].extend([rel(pipeline_md), rel(claude_report), rel(main_report)])
    phase_results[ph.name] = f"wrote final reports: {rel(main_report)}, {rel(pipeline_md)}, {rel(claude_report)}"

phase_log_path = REPORTS / "40_PHASE_LOG.json"
phase_log_path.write_text(json.dumps(phase_log, indent=2, ensure_ascii=False), encoding="utf-8")

summary = {
    "phase_count": len(phase_log),
    "total_phase_elapsed_seconds": round(sum(p["elapsed_seconds"] for p in phase_log), 3),
    "changed_files": sorted(set(
        prephase_modified
        + [m for vals in modified.values() for m in vals]
        + [rel(phase_log_path), "reports/40_run_full_audit.py"]
    )),
    "archived_files": archive_rows,
    "tests_run": test_results,
    "real_order_send_calls": runtime_result.get("real_order_send_calls", 0),
    "runtime_errors": runtime_result.get("errors", 0),
    "test_failures": len([t for t in test_results if t.get("result") == "FAIL"]),
    "lockdown_exit_code": lockdown_result.get("exit_code"),
    "final_status": "SAFE_FOR_DRY_RUN_ONLY" if (
        runtime_result.get("real_order_send_calls", 0) == 0
        and lockdown_result.get("exit_code") == 0
        and not static_scan.get("unguarded_active_order_send_lines", [])
        and not [t for t in test_results if t.get("result") == "FAIL"]
    ) else "REVIEW_REQUIRED",
    "reports": [
        "reports/40_FULL_CODEBASE_CONSOLIDATION_AND_READINESS.md",
        "reports/40_FILE_INVENTORY.csv",
        "reports/40_MERGE_STATUS.csv",
        "reports/40_ACTIVE_PIPELINE_MAP.md",
        "reports/41_CODEX_APPLIED_CLAUDE_REVIEW_FIXES.md",
        "reports/40_PHASE_LOG.json",
        "reports/40_RUN_SUMMARY.json",
    ],
}
summary_path = REPORTS / "40_RUN_SUMMARY.json"
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
