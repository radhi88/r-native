"""
friday_plugin.py — FRIDAY × JARVIS integration
-------------------------------------------------
Extends Mark-XXXIX (JARVIS) with FRIDAY trading system capabilities:
  - FRIDAY-specific tools for state, evolution, services, control, and self-test
  - SSE listener thread: announces trades/awards/predictions via JARVIS voice
  - One dashboard/SSE hub at http://127.0.0.1:8790
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from main import JarvisLive

log = logging.getLogger("friday_plugin")

FRIDAY_BASE        = os.getenv("FRIDAY_DASHBOARD_URL", os.getenv("FRIDAY_BASE", "http://127.0.0.1:8790")).rstrip("/")
FRIDAY_GATEWAY_URL = os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799").rstrip("/")
FRIDAY_BRAIN_URL   = os.getenv("FRIDAY_BRAIN_URL", "http://127.0.0.1:8844").rstrip("/")
FRIDAY_AGENTS_URL  = os.getenv("FRIDAY_AGENTS_URL", "http://127.0.0.1:8833").rstrip("/")
FRIDAY_CHAT_URL    = os.getenv("FRIDAY_CHAT_URL", "http://127.0.0.1:8811").rstrip("/")
FRIDAY_TV_URL      = os.getenv("FRIDAY_TRADINGVIEW_URL", "http://127.0.0.1:8822").rstrip("/")
FRIDAY_ROOT        = Path(os.getenv("FRIDAY_ROOT", str(Path(__file__).resolve().parents[1]))).resolve()

SERVICE_URLS = {
    "dashboard": FRIDAY_BASE,
    "gateway": FRIDAY_GATEWAY_URL,
    "chat": FRIDAY_CHAT_URL,
    "tradingview": FRIDAY_TV_URL,
    "agents": FRIDAY_AGENTS_URL,
    "brain": FRIDAY_BRAIN_URL,
}

SERVICE_PROBES = {
    "dashboard": "/api/state",
    "gateway": "/health",
    "chat": "/health",
    "tradingview": "/health",
    "agents": "/health",
    "brain": "/health",
}

GENOME_STATUS_FILE   = FRIDAY_ROOT / ".jarvis_agents" / "friday_genome_development_status.json"
GENOME_STATUS_EXPORT = FRIDAY_ROOT / "friday_genome_status_export.py"
SYSTEM_MESH_FILE     = FRIDAY_ROOT / ".jarvis_agents" / "friday_system_mesh.json"
SYSTEM_MESH_EXPORT   = FRIDAY_ROOT / "friday_system_mesh.py"
AWARENESS_FILE       = FRIDAY_ROOT / ".jarvis_agents" / "friday_awareness.json"
_MIN_ANNOUNCE_GAP    = 12.0
_AWARENESS_INTERVAL  = float(os.getenv("JARVIS_FRIDAY_AWARENESS_INTERVAL", "45") or 45)
_last_announce: float = 0.0
_awareness_started = False


# ── Tool Declarations for Gemini ─────────────────────────────────────────────

FRIDAY_DNA_BRIDGE_URL = os.getenv("FRIDAY_DNA_BRIDGE_URL", "http://127.0.0.1:7800").rstrip("/")

FRIDAY_TOOL_DECLARATIONS = [
    {
        "name": "friday_dna_evolve",
        "description": (
            "Gets the live status of the v7.2 DNA EVOLVE EA running in MT5 Strategy Tester. "
            "Reports current generation, fitness score, Gap/TP/SL parameters, P&L, and the "
            "last Claude suggestion. Can also apply a parameter change by sending a command "
            "to the EA via the command file. "
            "Call when the user asks about the DNA EA, the tester run, generation, fitness, "
            "or wants to adjust Gap/TP/SL/LotFactor while the tester is running."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "status | apply_params",
                },
                "params": {
                    "type": "OBJECT",
                    "description": "Parameter changes to apply (BasketGap, BasketTP, BasketSL, LotBase, LotFactor). Only used when action=apply_params.",
                    "properties": {
                        "BasketGap":    {"type": "NUMBER"},
                        "BasketTP":     {"type": "NUMBER"},
                        "BasketSL":     {"type": "NUMBER"},
                        "LotBase":      {"type": "NUMBER"},
                        "LotFactor":    {"type": "NUMBER"},
                    },
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "friday_services",
        "description": (
            "Gets unified FRIDAY service URLs, port health, dashboard state, and genome summary. "
            "Call this when the user asks whether FRIDAY/JARVIS is connected, what ports are active, "
            "or if everything is linked through one brain."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "detail": {
                    "type": "BOOLEAN",
                    "description": "Include extra raw counts and errors when true.",
                }
            },
        },
    },
    {
        "name": "friday_stack_control",
        "description": (
            "Controls the local FRIDAY stack scripts. Use status for inspection, start/restart to run "
            "the unified stack, and stop to stop FRIDAY services. Does not place live trades."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "status | start | restart | stop",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "friday_self_test",
        "description": (
            "Runs a fast local integration self-test for JARVIS <-> FRIDAY: service probes, "
            "state endpoint, evolution endpoint, and genome status file."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "friday_state",
        "description": (
            "Gets the live FRIDAY trading system state: "
            "account balance, equity, open positions, and P&L. "
            "Call when user asks about balance, money, positions, or trading status."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "friday_evolution",
        "description": (
            "Gets FRIDAY's genetic evolution leaderboard: "
            "active genome name, medals, win rate, profit factor, generation number. "
            "Call when user asks about genomes, strategy evolution, or trading performance."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "friday_genome_status",
        "description": (
            "Gets the external Jarvis-readable genome development status file: "
            "per-symbol scan state, current strategy genes, historical gene performance, "
            "genetic population files, and patch permission boundaries. "
            "Call when user asks where genomes reached per pair, or asks about Jarvis patch permissions."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "friday_system_mesh",
        "description": (
            "Gets the unified FRIDAY system mesh: compatibility contract, service health, "
            "process roots, symbol universe, genome maturity, autopilot state, findings, "
            "and safe next actions. Call when the user asks to link systems, coordinate agents, "
            "or make FRIDAY evolve over time."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "refresh": {
                    "type": "BOOLEAN",
                    "description": "Refresh the mesh file before reading it.",
                }
            },
        },
    },
    {
        "name": "friday_oracle",
        "description": (
            "Gets FRIDAY's Market Oracle: directional predictions (UP/DOWN) per currency pair "
            "and historical prediction accuracy. Inter-market correlations (Gold↑ → Oil, etc.). "
            "Call when user asks about market direction, forecasts, or correlations."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "friday_consult",
        "description": (
            "Asks FRIDAY's autonomous AI brain (Claude) a market or strategy question. "
            "Use for deep analysis: 'Why is Gold going up?', 'Should I trade EURUSD now?', "
            "'Explain the current genome behavior'. Returns the AI brain's analysis."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {
                    "type": "STRING",
                    "description": "The question to ask FRIDAY's AI brain",
                }
            },
            "required": ["question"],
        },
    },
    {
        "name": "friday_open_dashboard",
        "description": (
            "Opens the FRIDAY trading dashboard in the browser. "
            "Panels: dashboard (main AI view), brain (live brain state), "
            "agents (agent discussions), chat (chat app), tradingview (charts)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "panel": {
                    "type": "STRING",
                    "description": "dashboard | brain | agents | chat | tradingview (default: dashboard)",
                }
            },
        },
    },
]


# ── Tool Implementations ──────────────────────────────────────────────────────

def _load_genome_status(refresh: bool = True) -> tuple[dict, str | None]:
    if refresh and GENOME_STATUS_EXPORT.exists():
        try:
            subprocess.run(
                [sys.executable, str(GENOME_STATUS_EXPORT)],
                cwd=str(FRIDAY_ROOT),
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except Exception as exc:
            return {}, f"status export failed: {exc}"

    try:
        if GENOME_STATUS_FILE.exists():
            return json.loads(GENOME_STATUS_FILE.read_text(encoding="utf-8")), None
        return {}, f"status file not found: {GENOME_STATUS_FILE}"
    except Exception as exc:
        return {}, f"status file read failed: {exc}"


def _load_system_mesh(refresh: bool = False) -> tuple[dict, str | None]:
    if refresh and SYSTEM_MESH_EXPORT.exists():
        try:
            subprocess.run(
                [sys.executable, str(SYSTEM_MESH_EXPORT), "--refresh-genomes"],
                cwd=str(FRIDAY_ROOT),
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except Exception as exc:
            return {}, f"mesh refresh failed: {exc}"

    try:
        if SYSTEM_MESH_FILE.exists():
            return json.loads(SYSTEM_MESH_FILE.read_text(encoding="utf-8")), None
        return {}, f"mesh file not found: {SYSTEM_MESH_FILE}"
    except Exception as exc:
        return {}, f"mesh file read failed: {exc}"


def _join_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _get_json(url: str, timeout: float = 2.5) -> tuple[dict | list | None, str | None, int | None, float]:
    started = time.perf_counter()
    try:
        response = requests.get(url, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if response.status_code >= 500:
            return None, f"HTTP {response.status_code}", response.status_code, elapsed_ms
        try:
            return response.json(), None, response.status_code, elapsed_ms
        except Exception:
            return {"text": response.text[:300]}, None, response.status_code, elapsed_ms
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return None, str(exc), None, elapsed_ms


def _probe_service(name: str, url: str) -> dict:
    probe_path = SERVICE_PROBES.get(name, "/")
    timeout = 14.0 if name in {"brain", "tradingview"} else 3.5
    data, err, status_code, elapsed_ms = _get_json(_join_url(url, probe_path), timeout=timeout)
    return {
        "name": name,
        "url": url,
        "probe": probe_path,
        "ok": err is None and (status_code is None or status_code < 500),
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "error": err or "",
        "keys": sorted(list(data.keys()))[:12] if isinstance(data, dict) else [],
    }


def friday_awareness_snapshot() -> dict:
    """Collect one small status document that JARVIS can cache and reason from."""
    services = {name: _probe_service(name, url) for name, url in SERVICE_URLS.items()}

    state, state_err, _state_code, _state_ms = _get_json(f"{FRIDAY_BASE}/api/state", timeout=8.0)
    evolution, evo_err, _evo_code, _evo_ms = _get_json(f"{FRIDAY_BASE}/api/evolution", timeout=8.0)
    genome_status, genome_err = _load_genome_status(refresh=True)
    mesh_status, mesh_err = _load_system_mesh(refresh=False)

    state = state if isinstance(state, dict) else {}
    evolution = evolution if isinstance(evolution, dict) else {}
    genome_status = genome_status if isinstance(genome_status, dict) else {}
    mesh_status = mesh_status if isinstance(mesh_status, dict) else {}

    snapshot = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(FRIDAY_ROOT),
        "service_urls": SERVICE_URLS,
        "services": services,
        "dashboard": {
            "ok": not state_err,
            "error": state_err or "",
            "account": state.get("account", {}),
            "active_symbol": state.get("active_symbol", state.get("symbol", "")),
            "symbols": len(state.get("symbols", []) or []),
            "open_positions": len(state.get("open_positions", []) or []),
            "recent_trades": len(state.get("recent_trades", []) or []),
            "stats": state.get("stats", {}),
        },
        "evolution": {
            "ok": not evo_err,
            "error": evo_err or "",
            "generation": evolution.get("generation", 0),
            "population": evolution.get("population", 0),
            "protected": evolution.get("protected", 0),
            "symbols_tracked": evolution.get("symbols_tracked", 0),
            "leaderboard": (evolution.get("leaderboard") or [])[:8],
            "per_symbol": evolution.get("per_symbol", {}),
        },
        "genome_status_file": {
            "ok": bool(genome_status),
            "error": genome_err or "",
            "path": str(GENOME_STATUS_FILE),
            "generated_at": genome_status.get("generated_at", ""),
        },
        "system_mesh": {
            "ok": bool(mesh_status),
            "error": mesh_err or "",
            "path": str(SYSTEM_MESH_FILE),
            "generated_at": mesh_status.get("generated_at", ""),
            "maturity": mesh_status.get("maturity", {}),
            "findings": mesh_status.get("findings", [])[:8],
            "next_actions": mesh_status.get("next_actions", [])[:8],
        },
    }

    try:
        AWARENESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        AWARENESS_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return snapshot


def _format_awareness(snapshot: dict, detail: bool = False) -> str:
    services = snapshot.get("services", {}) or {}
    dashboard = snapshot.get("dashboard", {}) or {}
    evolution = snapshot.get("evolution", {}) or {}
    mesh = snapshot.get("system_mesh", {}) or {}
    ok_count = sum(1 for s in services.values() if s.get("ok"))

    lines = [
        f"FRIDAY unified hub: {SERVICE_URLS['dashboard']}",
        f"Root: {snapshot.get('root', FRIDAY_ROOT)}",
        f"Services: {ok_count}/{len(services)} online",
    ]
    for name, row in services.items():
        mark = "OK" if row.get("ok") else "DOWN"
        extra = f" {row.get('elapsed_ms')}ms" if row.get("ok") else f" {row.get('error')}"
        lines.append(f"  {mark} {name}: {row.get('url')}{extra}")

    acct = dashboard.get("account", {}) or {}
    stats = dashboard.get("stats", {}) or {}
    lines.extend(
        [
            (
                f"Dashboard: symbols={dashboard.get('symbols', 0)} "
                f"active={dashboard.get('active_symbol') or '-'} "
                f"positions={dashboard.get('open_positions', 0)} "
                f"recent={dashboard.get('recent_trades', 0)}"
            ),
            (
                f"Account: balance={acct.get('balance', 'N/A')} "
                f"equity={acct.get('equity', 'N/A')} "
                f"executor_trades={stats.get('external_executed', 0)}"
            ),
            (
                f"Evolution: gen={evolution.get('generation', 0)} "
                f"pop={evolution.get('population', 0)} "
                f"protected={evolution.get('protected', 0)} "
                f"symbols_tracked={evolution.get('symbols_tracked', 0)}"
            ),
        ]
    )
    maturity = mesh.get("maturity") or {}
    if mesh.get("ok"):
        lines.append(
            f"System mesh: {maturity.get('status', 'unknown')} | "
            f"services={maturity.get('services_online', 0)}/{maturity.get('services_total', 0)} | "
            f"genome_symbols={maturity.get('genome_population_symbols', 0)} | "
            f"findings={len(mesh.get('findings') or [])}"
        )
    if detail:
        for g in (evolution.get("leaderboard") or [])[:5]:
            name = g.get("name") or str(g.get("id", ""))[:8]
            lines.append(
                f"  Genome {g.get('symbol', '-')}: {name} "
                f"fitness={float(g.get('fitness') or 0):.4f} "
                f"WR={float(g.get('win_rate') or 0):.0%}"
            )
        lines.append(f"Awareness cache: {AWARENESS_FILE}")
    return "\n".join(lines)


def _format_system_mesh(mesh: dict) -> str:
    maturity = mesh.get("maturity") or {}
    dashboard = mesh.get("dashboard") or {}
    genomes = mesh.get("genomes") or {}
    contract = mesh.get("contract") or {}
    findings = mesh.get("findings") or []
    next_actions = mesh.get("next_actions") or []

    lines = [
        f"FRIDAY system mesh: {maturity.get('status', 'unknown')}",
        f"Generated: {mesh.get('generated_at', 'unknown')}",
        f"Entrypoint: {contract.get('single_entrypoint', '-')}",
        (
            f"Services: {maturity.get('services_online', 0)}/{maturity.get('services_total', 0)} | "
            f"Symbols: {dashboard.get('symbols', 0)} | "
            f"Active: {dashboard.get('active_symbol') or '-'}"
        ),
        (
            f"Account boundary: {dashboard.get('account_type') or contract.get('account_boundary', '-')} | "
            f"analysis_only={dashboard.get('analysis_only')}"
        ),
        (
            f"Genomes: population_symbols={genomes.get('population_symbols', 0)} | "
            f"strategy_genes={genomes.get('strategy_genes', 0)} | "
            f"events={genomes.get('strategy_events', 0)}"
        ),
    ]

    if findings:
        lines.append("Findings:")
        for row in findings[:8]:
            items = row.get("items") or []
            item_text = ", ".join(str(item) for item in items[:5])
            lines.append(
                f"  {row.get('severity', 'info').upper()} {row.get('area', '-')}: "
                f"{row.get('message', '')} {item_text}".strip()
            )
    else:
        lines.append("Findings: none")

    if next_actions:
        lines.append("Next actions:")
        lines.extend(f"  - {action}" for action in next_actions[:6])

    return "\n".join(lines)


def _format_genome_status(status: dict, limit: int = 12) -> str:
    live = status.get("live", {}) or {}
    strategy = status.get("strategy_genes", {}) or {}
    historical = status.get("historical_performance", {}) or {}
    populations = status.get("genetic_populations", {}) or {}
    permissions = status.get("permissions", {}) or {}

    stats = strategy.get("global_stats", {}) or {}
    lines = [
        f"Genome status generated: {status.get('generated_at', 'unknown')}",
        (
            f"Live scan: {live.get('symbols_with_live_state', 0)} symbols | "
            f"actions={live.get('action_counts', {})}"
        ),
        (
            f"Current strategy genes: events={stats.get('events', 0)} "
            f"genes={stats.get('genes_count', 0)} "
            f"W/L/N={stats.get('wins', 0)}/{stats.get('losses', 0)}/{stats.get('neutral', 0)}"
        ),
    ]

    evo_api = live.get("evolution_api", {}) or {}
    lines.append(
        "Genetic API: "
        f"generation={evo_api.get('generation', 0)} "
        f"population={evo_api.get('population', 0)} "
        f"protected={evo_api.get('protected', 0)}"
    )

    lines.append("Priority symbols:")
    for row in (live.get("priority_symbols") or [])[:limit]:
        lines.append(
            f"  {row.get('symbol')}: {row.get('action') or '-'} "
            f"prob={float(row.get('prob') or 0):.3f} "
            f"price={row.get('price')}"
        )

    hist = historical.get("symbols") or []
    if hist:
        lines.append("Historical gene performance:")
        for row in hist[:5]:
            lines.append(
                f"  {row.get('symbol')}: trades={row.get('trades', 0)} "
                f"WR={float(row.get('win_rate') or 0):.0%} "
                f"profit={float(row.get('profit') or 0):+.2f}"
            )

    pop = populations.get("symbols") or []
    if pop:
        lines.append("Population files:")
        for row in pop[:6]:
            lines.append(
                f"  {row.get('symbol')}: pop={row.get('population', 0)} "
                f"trades={row.get('trades', 0)} protected={row.get('protected', 0)} "
                f"bestfit={float(row.get('best_fitness') or 0):.4f}"
            )

    notes = status.get("notes") or []
    if notes:
        lines.append("Notes:")
        lines.extend(f"  - {note}" for note in notes[:5])

    pipeline = permissions.get("patch_pipeline", {}) or {}
    lines.append(
        "Patch permission boundary: "
        f"auto_apply={pipeline.get('auto_apply_enabled')} | "
        f"allowlist={len(pipeline.get('safe_edit_allowlist') or [])} files | "
        "execution/order files remain blocked."
    )

    return "\n".join(lines)

def _friday_dna_evolve(args: dict) -> str:
    action = str(args.get("action", "status") or "status").strip().lower()

    if action == "apply_params":
        params = args.get("params") or {}
        if not params:
            return "No params provided. Send params like {BasketGap: 600, BasketTP: 50}."
        try:
            resp = requests.post(
                f"{FRIDAY_DNA_BRIDGE_URL}/api/dna/command",
                json={"params": params},
                timeout=4,
            )
            result = resp.json()
            if result.get("ok"):
                changes = ", ".join(f"{k}={v}" for k, v in params.items())
                return f"✓ DNA command sent to EA: {changes}"
            return f"Bridge rejected command: {result}"
        except Exception as exc:
            return f"DNA bridge unreachable: {exc}"

    # default: status
    try:
        state_resp = requests.get(f"{FRIDAY_DNA_BRIDGE_URL}/api/dna/state", timeout=3)
        sugg_resp  = requests.get(f"{FRIDAY_DNA_BRIDGE_URL}/api/dna/suggestions?limit=3", timeout=3)
        state = state_resp.json()
        sugg_data = sugg_resp.json() if sugg_resp.ok else {}
    except Exception as exc:
        # fallback: read status file directly
        try:
            status_path = (
                Path.home()
                / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
                / "ea_realtime_status.json"
            )
            state_raw = json.loads(status_path.read_text(encoding="utf-8-sig"))
            cur = state_raw
            lines = [
                f"DNA EVOLVE v7.2 (file fallback — bridge at {FRIDAY_DNA_BRIDGE_URL} unreachable: {exc})",
                f"Gen: {cur.get('generation', cur.get('dna_gen', '—'))} | "
                f"Balance: ${cur.get('balance', 0):.2f} | Equity: ${cur.get('equity', 0):.2f}",
                f"Gap: {cur.get('dna_gap', '—')} | TP: {cur.get('dna_tp', '—')} | SL: {cur.get('dna_sl', '—')}",
                f"Fitness: {cur.get('best_fitness', '—')} | Positions: {cur.get('positions', 0)}",
            ]
            return "\n".join(lines)
        except Exception as exc2:
            return f"DNA status unavailable: bridge={exc}, file={exc2}"

    cur = state.get("current", {})
    connected = state.get("connected", False)
    total_applied = state.get("total_applied", 0)
    bar = cur.get("bar", 0)

    lines = [
        f"DNA EVOLVE v7.2 — {'✓ MT5 CONNECTED' if connected else '⏳ Waiting for MT5'}",
        f"Generation: #{cur.get('generation', cur.get('dna_gen', '—'))} | "
        f"Bar: {bar} | Applied cmds: {total_applied}",
        f"Balance: ${cur.get('balance', 0):.2f} | Equity: ${cur.get('equity', 0):.2f} | "
        f"Open P&L: ${cur.get('open_pnl', 0):.2f}",
        f"DNA Gap: {cur.get('dna_gap', '—')} pts | "
        f"TP: ${cur.get('dna_tp', '—')} | SL: ${cur.get('dna_sl', '—')}",
        f"Lot factor: {cur.get('lot_factor', '—')} | Best fitness: {cur.get('best_fitness', '—')}",
        f"Win streak: {cur.get('win_streak', 0)} | Loss streak: {cur.get('loss_streak', 0)} | "
        f"Cooldown: {cur.get('cooldown', 0)}s",
    ]

    suggestions = sugg_data.get("suggestions", [])
    if suggestions:
        last = suggestions[0]
        action_sym = "🔴" if last.get("action") == "CRITICAL" else "🟡" if last.get("action") == "TWEAK" else "🟢"
        lines.append(
            f"Last Claude: {action_sym} {last.get('action', 'HOLD')} ({last.get('confidence', 0)}%) — "
            f"{last.get('message', '')} | {last.get('suggestion', '')}"
        )
        params_changed = last.get("params_to_change", {})
        if params_changed:
            lines.append("  Params: " + ", ".join(f"{k}={v}" for k, v in params_changed.items() if v))
    else:
        lines.append("No Claude suggestions yet.")

    lines.append(f"Bridge: {FRIDAY_DNA_BRIDGE_URL} | Widget: {FRIDAY_DNA_BRIDGE_URL.replace('7800', '5173')}/arena")
    return "\n".join(lines)


def _friday_state(_args: dict) -> str:
    try:
        r = requests.get(f"{FRIDAY_BASE}/api/state", timeout=5)
        s = r.json()
        acct  = s.get("account", {})
        stats = s.get("stats", {})
        pos   = s.get("open_positions", [])
        recent = s.get("recent_trades", []) or []
        external = stats.get("external_executed", 0)
        symbols = s.get("symbols", []) or []

        lines = [
            f"Balance: {acct.get('balance', 'N/A')} | Equity: {acct.get('equity', 'N/A')}",
            f"Trades: {stats.get('trades', 0)} dashboard | {external} executor | Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}",
            f"Open positions: {len(pos)}",
            f"Symbols: {len(symbols)} | Active: {s.get('active_symbol', s.get('symbol', '?'))}",
        ]
        for p in pos[:6]:
            pnl = p.get("profit", 0)
            lines.append(
                f"  {p.get('side','?')} {p.get('symbol','?')} "
                f"#{p.get('ticket','?')} PnL={pnl:+.2f}"
            )
        if recent:
            lines.append("Recent FRIDAY executor events:")
            for trade in recent[:5]:
                status = "SENT" if trade.get("executed") or trade.get("sent") else "BLOCKED"
                lines.append(
                    f"  {status} {trade.get('action','?')} {trade.get('symbol','?')} "
                    f"{trade.get('source','')}"
                )
        return "\n".join(lines)
    except Exception as e:
        return f"FRIDAY not reachable: {e}"


def _friday_services(args: dict) -> str:
    detail = bool(args.get("detail"))
    snapshot = friday_awareness_snapshot()
    return _format_awareness(snapshot, detail=detail)


def _friday_stack_control(args: dict) -> str:
    action = str(args.get("action", "status") or "status").strip().lower()
    if action in {"status", "health", "check"}:
        return _friday_services({"detail": True})

    # Stack start/stop requires a physical button click — never via voice or text
    if action in {"start", "restart", "stop"}:
        return (
            f"⚠️ Stack {action.upper()} requires manual confirmation. "
            "Use the FRIDAY control panel or run the script directly in a terminal. "
            "Voice-triggered stack control is disabled for safety."
        )

    return "Unknown FRIDAY stack action. Use: status, start, restart, stop."


def _friday_self_test(_args: dict) -> str:
    snapshot = friday_awareness_snapshot()
    lines = ["FRIDAY/JARVIS self-test:"]
    lines.extend(_format_awareness(snapshot, detail=True).splitlines())

    checks = {
        "state_tool": _friday_state({})[:500],
        "evolution_tool": _friday_evolution({})[:500],
        "genome_status_tool": _friday_genome_status({})[:500],
    }
    lines.append("Tool checks:")
    for name, result in checks.items():
        ok = not any(
            marker in result.lower()
            for marker in ["unavailable", "not reachable", "failed", "error", "timed out"]
        )
        lines.append(f"  {'OK' if ok else 'WARN'} {name}: {result.splitlines()[0] if result else '-'}")
    return "\n".join(lines)


def _friday_evolution(_args: dict) -> str:
    try:
        r = requests.get(f"{FRIDAY_BASE}/api/evolution", timeout=5)
        ev = r.json()
        lines = [
            f"Generation: {ev.get('generation', 0)} | "
            f"Population: {ev.get('population', 0)} | "
            f"Protected: {ev.get('protected', 0)}",
            f"Active genome: {ev.get('active_name', '—')} | "
            f"Fitness: {ev.get('active_fitness', 0):.4f} | "
            f"WR: {ev.get('active_wr', 0):.0%}",
        ]
        for g in ev.get("leaderboard", [])[:5]:
            medals = " ".join(g.get("medals", []))
            name   = g.get("name") or g.get("id", "")[:8]
            lines.append(
                f"  {medals} {name} | WR={g.get('win_rate', 0):.0%} "
                f"PF={g.get('profit_factor', 0):.2f} "
                f"PnL=${g.get('total_pnl', 0):.2f}"
            )
        status, err = _load_genome_status(refresh=True)
        if status:
            lines.append("")
            lines.append("External status file:")
            lines.extend(_format_genome_status(status, limit=8).splitlines()[:18])
        elif err:
            lines.append(f"External status unavailable: {err}")
        return "\n".join(lines)
    except Exception as e:
        status, err = _load_genome_status(refresh=True)
        if status:
            return _format_genome_status(status)
        return f"Evolution data unavailable: {e}; external status unavailable: {err}"


def _friday_genome_status(_args: dict) -> str:
    status, err = _load_genome_status(refresh=True)
    if not status:
        return f"Genome status unavailable: {err}"
    return _format_genome_status(status)


def _friday_system_mesh(args: dict) -> str:
    status, err = _load_system_mesh(refresh=bool(args.get("refresh")))
    if not status:
        return f"System mesh unavailable: {err}"
    return _format_system_mesh(status)


def _friday_oracle(_args: dict) -> str:
    try:
        r = requests.get(f"{FRIDAY_BASE}/api/state", timeout=5)
        s      = r.json()
        oracle = s.get("oracle", {})
        acc    = oracle.get("accuracy", {})
        preds  = oracle.get("active_predictions", [])

        lines = ["Market Oracle — active predictions:"]
        for p in preds[:7]:
            sym  = p.get("symbol", "?")
            dir_ = p.get("direction", "?")
            conf = p.get("confidence", 0)
            lines.append(f"  {sym}: {dir_} ({conf:.0%} confidence)")

        if acc:
            lines.append("Prediction accuracy:")
            for sym, a in list(acc.items())[:7]:
                lines.append(
                    f"  {sym}: {a.get('accuracy', 0):.0%} "
                    f"({a.get('correct', 0)}/{a.get('total', 0)} correct)"
                )

        return "\n".join(lines) if len(lines) > 1 else "No active Oracle predictions yet."
    except Exception as e:
        return f"Oracle data unavailable: {e}"


def _friday_consult(args: dict) -> str:
    question = args.get("question", "")
    try:
        r = requests.post(
            f"{FRIDAY_BASE}/api/consult",
            json={"question": question},
            timeout=30,
        )
        return r.json().get("answer", "No response from AI brain.")
    except Exception as e:
        return f"FRIDAY brain unavailable: {e}"


def _friday_open_dashboard(args: dict) -> str:
    panel = args.get("panel", "dashboard")
    urls  = {
        "dashboard":   FRIDAY_BASE,
        "brain":       FRIDAY_BRAIN_URL,
        "agents":      FRIDAY_AGENTS_URL,
        "chat":        FRIDAY_CHAT_URL,
        "tradingview": FRIDAY_TV_URL,
    }
    url = urls.get(panel, urls["dashboard"])
    subprocess.Popen(["cmd", "/c", "start", url], shell=False)
    return f"Opening FRIDAY {panel} at {url}"


_HANDLERS = {
    "friday_dna_evolve":      _friday_dna_evolve,
    "friday_services":        _friday_services,
    "friday_stack_control":   _friday_stack_control,
    "friday_self_test":       _friday_self_test,
    "friday_state":          _friday_state,
    "friday_evolution":      _friday_evolution,
    "friday_genome_status":  _friday_genome_status,
    "friday_system_mesh":    _friday_system_mesh,
    "friday_oracle":         _friday_oracle,
    "friday_consult":        _friday_consult,
    "friday_open_dashboard": _friday_open_dashboard,
}


def friday_execute(name: str, args: dict) -> str:
    """Dispatch a FRIDAY tool call and return the result string."""
    handler = _HANDLERS.get(name)
    if handler:
        return handler(args)
    return f"Unknown FRIDAY tool: {name}"


# ── SSE Listener ─────────────────────────────────────────────────────────────

def _sse_thread(jarvis: JarvisLive) -> None:
    """Background thread — listens to FRIDAY events, speaks important ones."""
    global _last_announce

    def _announce(text: str) -> None:
        global _last_announce
        now = time.time()
        if now - _last_announce < _MIN_ANNOUNCE_GAP:
            return
        _last_announce = now
        try:
            jarvis.ui.write_log(f"FRIDAY: {text[:100]}")
        except Exception:
            pass
        try:
            jarvis.speak(text)
        except Exception:
            pass

    url = f"{FRIDAY_BASE}/events"
    while True:
        try:
            resp = requests.get(
                url,
                stream=True,
                timeout=60,
                headers={"Accept": "text/event-stream"},
            )
            try:
                jarvis.ui.write_log("SYS: FRIDAY trading feed connected.")
            except Exception:
                pass

            event_type = ""
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    event_type = ""
                    continue
                if raw.startswith("event:"):
                    event_type = raw[6:].strip()
                elif raw.startswith("data:") and event_type:
                    try:
                        data = json.loads(raw[5:].strip())
                    except Exception:
                        continue

                    # ── Trade executed ───────────────────────────────────
                    if (
                        event_type == "trade"
                        and data.get("executed")
                        and data.get("action") in ("BUY", "SELL")
                    ):
                        direction = "شراء" if data["action"] == "BUY" else "بيع"
                        symbol    = data.get("symbol", "")
                        opp       = float(data.get("opp_mult", 1.0))
                        quality   = (
                            "سنايبر" if opp >= 1.8
                            else ("قوية" if opp >= 1.2 else "عادية")
                        )
                        lot = data.get("lot", 0)
                        _announce(
                            f"صفقة {direction} على {symbol}، "
                            f"إشارة {quality}، لوت {lot:.2f}"
                        )

                    # ── Genome award ─────────────────────────────────────
                    elif event_type == "genome_award":
                        name   = data.get("name", "")
                        medal  = data.get("medal_emoji", "🏅")
                        title  = data.get("medal_name", "")
                        _announce(f"جينوم {name} حصل على وسام {medal} {title}")

                    # ── Correct oracle prediction ─────────────────────────
                    elif event_type == "oracle_result" and data.get("correct"):
                        symbol    = data.get("symbol", "")
                        direction = data.get("direction", "")
                        dir_ar    = "صعود" if direction == "UP" else "هبوط"
                        move      = abs(float(data.get("move_pct", 0)))
                        _announce(
                            f"تنبؤ صحيح على {symbol}، "
                            f"{dir_ar} بنسبة {move:.2f} بالمئة"
                        )

                    # ── Important agent messages ──────────────────────────
                    elif event_type == "agent_discussion":
                        msg = data.get("message", "")
                        if any(k in msg for k in ["👑", "💎", "🥇", "Legend", "أسطورة"]):
                            _announce(f"وكيل يُعلن: {msg[:80]}")

        except Exception as exc:
            log.debug("FRIDAY SSE disconnected: %s — retry in 5s", exc)
            time.sleep(5)


def start_sse_listener(jarvis: JarvisLive) -> None:
    """Start the FRIDAY SSE listener as a background daemon thread."""
    t = threading.Thread(
        target=_sse_thread,
        args=(jarvis,),
        daemon=True,
        name="friday-sse",
    )
    t.start()
    log.info("FRIDAY SSE listener started.")


def _awareness_thread(jarvis: JarvisLive) -> None:
    last_ok: dict[str, bool] = {}
    first = True
    while True:
        try:
            snapshot = friday_awareness_snapshot()
            services = snapshot.get("services", {}) or {}
            ok_count = sum(1 for row in services.values() if row.get("ok"))
            total = len(services)
            dashboard = snapshot.get("dashboard", {}) or {}
            evolution = snapshot.get("evolution", {}) or {}
            summary = (
                f"FRIDAY awareness: services={ok_count}/{total}, "
                f"symbols={dashboard.get('symbols', 0)}, "
                f"positions={dashboard.get('open_positions', 0)}, "
                f"tracked_genomes={evolution.get('symbols_tracked', 0)}"
            )
            try:
                jarvis.ui.write_log(f"SYS: {summary}")
            except Exception:
                pass

            current_ok = {name: bool(row.get("ok")) for name, row in services.items()}
            changed_down = [name for name, ok in current_ok.items() if not ok and last_ok.get(name, True)]
            changed_up = [name for name, ok in current_ok.items() if ok and last_ok.get(name) is False]
            last_ok = current_ok

            if first:
                first = False
                try:
                    jarvis.ui.write_log(f"SYS: FRIDAY awareness cache: {AWARENESS_FILE}")
                except Exception:
                    pass
            elif changed_down:
                try:
                    jarvis.speak("تنبيه: بعض خدمات FRIDAY غير متصلة: " + "، ".join(changed_down[:4]))
                except Exception:
                    pass
            elif changed_up:
                try:
                    jarvis.ui.write_log("SYS: FRIDAY services recovered: " + ", ".join(changed_up[:4]))
                except Exception:
                    pass
        except Exception as exc:
            try:
                jarvis.ui.write_log(f"ERR: FRIDAY awareness monitor failed: {str(exc)[:160]}")
            except Exception:
                pass
        time.sleep(max(15.0, _AWARENESS_INTERVAL))


def start_awareness_monitor(jarvis: JarvisLive) -> None:
    """Start the FRIDAY status monitor as one background daemon thread."""
    global _awareness_started
    if _awareness_started:
        return
    _awareness_started = True
    t = threading.Thread(
        target=_awareness_thread,
        args=(jarvis,),
        daemon=True,
        name="friday-awareness",
    )
    t.start()
    log.info("FRIDAY awareness monitor started.")
