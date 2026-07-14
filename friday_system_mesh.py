from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(os.getenv("FRIDAY_ROOT", r"C:\Users\Radhi\MT5")).resolve()
JARVIS_DIR = ROOT / ".jarvis_agents"
MESH_FILE = JARVIS_DIR / "friday_system_mesh.json"
LOCAL_STATE_FILE = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "FRIDAY" / "system_mesh.json"
HEALTH_STATUS_FILE = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "FRIDAY" / "health_status.json"
GENOME_STATUS_FILE = JARVIS_DIR / "friday_genome_development_status.json"
GENOME_EXPORT_SCRIPT = ROOT / "friday_genome_status_export.py"
AUTOPILOT_STATE_FILE = ROOT / "friday_autopilot_state.json"

SERVICE_URLS = {
    "dashboard": os.getenv("FRIDAY_DASHBOARD_URL", "http://127.0.0.1:8790").rstrip("/"),
    "gateway": os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799").rstrip("/"),
    "chat": os.getenv("FRIDAY_CHAT_URL", "http://127.0.0.1:8811").rstrip("/"),
    "tradingview": os.getenv("FRIDAY_TRADINGVIEW_URL", "http://127.0.0.1:8822").rstrip("/"),
    "agents": os.getenv("FRIDAY_AGENTS_URL", "http://127.0.0.1:8833").rstrip("/"),
    "brain": os.getenv("FRIDAY_BRAIN_URL", "http://127.0.0.1:8844").rstrip("/"),
}

SERVICE_PROBES = {
    "dashboard": "/api/state",
    "gateway": "/health",
    "chat": "/state",
    "tradingview": "/health",
    "agents": "/api/overview",
    "brain": "/health",
}

PROCESS_PATTERNS = {
    "indicator_engine": "friday_indicator_feature_engine.py",
    "orderflow_engine": "friday_orderflow_feature_engine.py",
    "feature_learner": "friday_feature_outcome_learner.py",
    "trade_learner": "friday_trade_outcome_learner.py",
    "gateway": "friday_local_gateway:app",
    "chat": "friday_chat_app.py",
    "tradingview": "friday_scalper_live_dashboard.py",
    "agents": "friday_agents_browser.py",
    "brain_server": "friday_live_brain_state.py --serve",
    "brain_loop": "friday_live_brain_state.py --loop",
    "autopilot": "friday_autopilot_supervisor.py",
    "algory_runner": "mt5_ai.algory_runner",
    "dashboard": "friday_web_dashboard.py",
    "scalper_executor": "friday_realtime_scalper_demo_executor.py",
    "touch_executor": "friday_touch_demo_executor.py",
    "position_governor": "friday_demo_position_governor_v2.py",
    "health_monitor": "friday_health_monitor.py",
    "system_mesh": "friday_system_mesh.py",
    "legacy_safe_supervisor": "friday_safe_supervisor.py",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(url: str, timeout: float = 4.0) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    meta: dict[str, Any] = {"url": url, "ok": False, "status": None, "elapsed_ms": 0.0, "error": ""}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            meta["status"] = getattr(resp, "status", None)
            meta["ok"] = int(meta["status"] or 200) < 500
            meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            try:
                return json.loads(body), meta
            except json.JSONDecodeError:
                return {"text": body[:500]}, meta
    except Exception as exc:
        meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        meta["error"] = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            meta["status"] = exc.code
        return {}, meta


def run_genome_export() -> None:
    if not GENOME_EXPORT_SCRIPT.exists():
        return
    try:
        subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(GENOME_EXPORT_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        pass


def process_counts() -> dict[str, dict[str, Any]]:
    ps = r"""
Get-CimInstance Win32_Process |
Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine } |
ForEach-Object { "$($_.ProcessId),$($_.ParentProcessId),$($_.CommandLine)" }
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return {}

    rows: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split(",", 2)
        if len(parts) != 3 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
            continue
        rows.append((int(parts[0]), int(parts[1]), parts[2]))

    output: dict[str, dict[str, Any]] = {}
    for name, pattern in PROCESS_PATTERNS.items():
        matches = [(pid, ppid, cmd) for pid, ppid, cmd in rows if pattern in cmd]
        if name == "system_mesh":
            matches = _drop_current_mesh_probe(matches)
        match_pids = {pid for pid, _ppid, _cmd in matches}
        roots = [pid for pid, ppid, _cmd in matches if ppid not in match_pids]
        output[name] = {
            "pattern": pattern,
            "processes": len(matches),
            "instances": len(roots),
            "roots": roots,
            "pids": [pid for pid, _ppid, _cmd in matches],
        }
    return output


def _drop_current_mesh_probe(matches: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Do not count a one-shot mesh refresh as a duplicate of the loop service."""
    current_pid = os.getpid()
    match_pids = {pid for pid, _ppid, _cmd in matches}
    if current_pid not in match_pids:
        return matches

    def root_for(pid: int) -> int:
        parent_by_pid = {row_pid: row_ppid for row_pid, row_ppid, _cmd in matches}
        root = pid
        seen: set[int] = set()
        while parent_by_pid.get(root) in match_pids and root not in seen:
            seen.add(root)
            root = parent_by_pid[root]
        return root

    roots = {root_for(pid) for pid in match_pids}
    if len(roots) <= 1:
        return matches

    current_root = root_for(current_pid)
    return [row for row in matches if root_for(row[0]) != current_root]


def service_snapshot() -> dict[str, Any]:
    services = {}
    for name, base in SERVICE_URLS.items():
        path = SERVICE_PROBES.get(name, "/")
        data, meta = http_json(f"{base}{path}", timeout=14.0 if name in {"brain", "tradingview"} else 5.0)
        services[name] = {
            **meta,
            "probe": path,
            "keys": sorted(data.keys())[:12] if isinstance(data, dict) else [],
        }
    return services


def dashboard_summary(state: dict[str, Any]) -> dict[str, Any]:
    account = state.get("account") or {}
    symbols = state.get("symbols") or []
    external = state.get("external_runtime") or {}
    stats = state.get("stats") or {}
    return {
        "ok": bool(state),
        "account_type": state.get("account_type"),
        "analysis_only": state.get("analysis_only"),
        "active_symbol": state.get("active_symbol") or state.get("symbol"),
        "symbols": len(symbols),
        "open_positions": state.get("open_positions_count", len(state.get("open_positions") or [])),
        "recent_trades": len(state.get("recent_trades") or []),
        "external_events": external.get("events_count", stats.get("external_events", 0)),
        "external_executed": external.get("executed_count", stats.get("external_executed", 0)),
        "balance": account.get("balance"),
        "equity": account.get("equity"),
    }


def genome_summary(status: dict[str, Any]) -> dict[str, Any]:
    strategy = status.get("strategy_genes") or {}
    live = status.get("live") or {}
    populations = status.get("genetic_populations") or {}
    pop_symbols = populations.get("symbols") or []
    stats = strategy.get("global_stats") or {}
    return {
        "ok": bool(status),
        "generated_at": status.get("generated_at"),
        "live_symbols": live.get("symbols_with_live_state", 0),
        "strategy_events": stats.get("events", 0),
        "strategy_genes": stats.get("genes_count", 0),
        "population_symbols": len(pop_symbols),
        "top_population_symbols": [
            {
                "symbol": row.get("symbol"),
                "population": row.get("population", 0),
                "trades": row.get("trades", 0),
                "protected": row.get("protected", 0),
                "best_fitness": row.get("best_fitness", 0),
            }
            for row in pop_symbols[:10]
        ],
    }


def build_findings(mesh: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    services = mesh.get("services") or {}
    processes = mesh.get("processes") or {}
    dashboard = mesh.get("dashboard") or {}
    health = mesh.get("health_monitor") or {}
    genome = mesh.get("genomes") or {}

    down = [name for name, row in services.items() if not row.get("ok")]
    if down:
        findings.append({
            "severity": "high",
            "area": "services",
            "message": "Some service endpoints are unreachable.",
            "items": down,
            "action": "Use friday_stack_control restart or let health monitor heal them.",
        })

    health_services = health.get("services") or {}
    health_bad = [name for name, status in health_services.items() if status != "OK"]
    if health_bad:
        findings.append({
            "severity": "high",
            "area": "health_monitor",
            "message": "Health monitor reports non-OK services.",
            "items": health_bad,
            "action": "Inspect health_monitor.log before changing strategies.",
        })

    if int(dashboard.get("symbols") or 0) < 50:
        findings.append({
            "severity": "high",
            "area": "symbols",
            "message": "Symbol universe looks too small; all-symbol mode may be broken.",
            "items": [dashboard.get("symbols", 0)],
            "action": "Keep --symbols all and verify MT5 symbol discovery.",
        })

    legacy = processes.get("legacy_safe_supervisor") or {}
    if legacy.get("processes"):
        findings.append({
            "severity": "medium",
            "area": "legacy_paths",
            "message": "Legacy safe supervisor is running outside the unified stack.",
            "items": legacy.get("pids", []),
            "action": "Stop it; unified execution must go through start_friday_trading_full.ps1.",
        })

    duplicate_roots = [
        name for name, row in processes.items()
        if name not in {"legacy_safe_supervisor"} and int(row.get("instances") or 0) > 1
    ]
    if duplicate_roots:
        findings.append({
            "severity": "medium",
            "area": "processes",
            "message": "Some managed services have multiple independent roots.",
            "items": duplicate_roots,
            "action": "Health monitor should dedupe these without killing child workers.",
        })

    if not genome.get("ok"):
        findings.append({
            "severity": "medium",
            "area": "genomes",
            "message": "Genome status file is missing or unreadable.",
            "items": [str(GENOME_STATUS_FILE)],
            "action": "Run friday_genome_status_export.py and check dashboard /api/evolution.",
        })
    elif int(genome.get("population_symbols") or 0) < 5:
        findings.append({
            "severity": "low",
            "area": "genomes",
            "message": "Few symbols have dedicated population files yet.",
            "items": [genome.get("population_symbols", 0)],
            "action": "Let the all-symbol runners collect more samples before applying strategy edits.",
        })

    return findings


def build_next_actions(mesh: dict[str, Any]) -> list[str]:
    findings = mesh.get("findings") or []
    high = [row for row in findings if row.get("severity") == "high"]
    if high:
        return [
            "Keep trading logic unchanged until high-severity service or symbol-universe findings are clear.",
            "Run the unified stop/start cycle and verify health_status.json reports every service as OK.",
            "Do not approve agent patches that touch order execution while the mesh is unhealthy.",
        ]

    return [
        "Keep all launch paths on start_friday_trading_full.ps1 and block legacy paper-mode supervisors.",
        "Let per-symbol genomes collect more live demo observations before changing risk parameters.",
        "Use agent patches only through the gateway allowlist; execution files stay manual-review only.",
        "Compare each symbol's population fitness, drawdown, and trade count before promoting a genome.",
    ]


def build_mesh(refresh_genomes: bool = False) -> dict[str, Any]:
    if refresh_genomes:
        run_genome_export()

    dashboard_state, dashboard_meta = http_json(f"{SERVICE_URLS['dashboard']}/api/state", timeout=8.0)
    evolution_state, evolution_meta = http_json(f"{SERVICE_URLS['dashboard']}/api/evolution", timeout=8.0)
    health = load_json(HEALTH_STATUS_FILE, {})
    genome_status = load_json(GENOME_STATUS_FILE, {})
    autopilot = load_json(AUTOPILOT_STATE_FILE, {})

    mesh = {
        "generated_at": now(),
        "root": str(ROOT),
        "contract": {
            "single_entrypoint": str(ROOT / "start_friday_trading_full.ps1"),
            "stop_entrypoint": str(ROOT / "stop_friday_all.ps1"),
            "symbol_mode": "all",
            "account_boundary": "DEMO",
            "execution_review": "order execution changes require manual review",
            "legacy_blocked": sorted(PROCESS_PATTERNS[name] for name in ["legacy_safe_supervisor"]),
        },
        "services": service_snapshot(),
        "dashboard": dashboard_summary(dashboard_state if isinstance(dashboard_state, dict) else {}),
        "dashboard_probe": dashboard_meta,
        "evolution": {
            "ok": isinstance(evolution_state, dict) and bool(evolution_state),
            "probe": evolution_meta,
            "generation": (evolution_state or {}).get("generation") if isinstance(evolution_state, dict) else None,
            "population": (evolution_state or {}).get("population") if isinstance(evolution_state, dict) else None,
            "protected": (evolution_state or {}).get("protected") if isinstance(evolution_state, dict) else None,
            "symbols_tracked": (evolution_state or {}).get("symbols_tracked") if isinstance(evolution_state, dict) else None,
            "leaderboard": ((evolution_state or {}).get("leaderboard") or [])[:10]
            if isinstance(evolution_state, dict) else [],
        },
        "health_monitor": health,
        "genomes": genome_summary(genome_status if isinstance(genome_status, dict) else {}),
        "autopilot": {
            "ok": bool(autopilot),
            "cycles": autopilot.get("cycles"),
            "mode": autopilot.get("mode"),
            "last_actions": (autopilot.get("actions") or [])[-8:],
            "safe_edit_allowlist": autopilot.get("safe_edit_allowlist", []),
        },
        "processes": process_counts(),
    }
    mesh["findings"] = build_findings(mesh)
    mesh["next_actions"] = build_next_actions(mesh)
    mesh["maturity"] = {
        "services_online": sum(1 for row in mesh["services"].values() if row.get("ok")),
        "services_total": len(mesh["services"]),
        "symbols": mesh["dashboard"].get("symbols", 0),
        "genome_population_symbols": mesh["genomes"].get("population_symbols", 0),
        "status": "coordinated" if not mesh["findings"] else "needs_attention",
    }
    return mesh


def run_once(refresh_genomes: bool = False) -> dict[str, Any]:
    mesh = build_mesh(refresh_genomes=refresh_genomes)
    write_json(MESH_FILE, mesh)
    write_json(LOCAL_STATE_FILE, mesh)
    return mesh


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FRIDAY unified system mesh state.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--refresh-genomes", action="store_true")
    args = parser.parse_args()

    if not args.loop:
        mesh = run_once(refresh_genomes=args.refresh_genomes)
        print(json.dumps({
            "generated_at": mesh["generated_at"],
            "maturity": mesh["maturity"],
            "findings": len(mesh["findings"]),
            "file": str(MESH_FILE),
        }, ensure_ascii=False))
        return 0

    cycle = 0
    while True:
        cycle += 1
        mesh = run_once(refresh_genomes=args.refresh_genomes or cycle % 5 == 1)
        print(
            f"[{mesh['generated_at']}] mesh={mesh['maturity']['status']} "
            f"services={mesh['maturity']['services_online']}/{mesh['maturity']['services_total']} "
            f"symbols={mesh['maturity']['symbols']} findings={len(mesh['findings'])}",
            flush=True,
        )
        time.sleep(max(15, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
