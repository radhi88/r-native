from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / ".jarvis_agents" / "friday_genome_development_status.json"

STATE_URL = "http://127.0.0.1:8790/api/state"
EVOLUTION_URL = "http://127.0.0.1:8790/api/evolution"

PRIORITY_SYMBOLS = [
    "XAUUSDm",
    "XAGUSDm",
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "USDCHFm",
    "USDCADm",
    "AUDUSDm",
    "NZDUSDm",
    "EURJPYm",
    "GBPJPYm",
    "BTCUSDm",
    "ETHUSDm",
    "USOILm",
    "UKOILm",
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def http_json(url: str, timeout: float = 3.0) -> tuple[dict[str, Any], str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace")), None
    except Exception as exc:
        return {}, str(exc)


def infer_symbol_from_gene(gene_id: str, examples: list[dict[str, Any]]) -> str:
    for item in reversed(examples or []):
        symbol = str(item.get("symbol") or (item.get("meta") or {}).get("symbol") or "").strip()
        if symbol:
            return symbol

    first = str(gene_id or "").split(":", 1)[0]
    if re.fullmatch(r"[A-Z0-9_]+m", first or ""):
        return first
    return "GLOBAL/UNKNOWN"


def summarize_strategy_genes() -> dict[str, Any]:
    path = ROOT / "friday_strategy_genes.json"
    data = load_json(path, {})
    genes = data.get("genes", {}) if isinstance(data, dict) else {}

    by_symbol: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "genes": 0,
            "seen": 0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "score_sum": 0.0,
            "sources": Counter(),
            "top_genes": [],
        }
    )

    for gene_id, gene in genes.items():
        examples = gene.get("examples") or []
        symbol = infer_symbol_from_gene(str(gene_id), examples)
        row = by_symbol[symbol]
        row["genes"] += 1
        row["seen"] += int(gene.get("seen") or 0)
        row["wins"] += int(gene.get("wins") or 0)
        row["losses"] += int(gene.get("losses") or 0)
        row["neutral"] += int(gene.get("neutral") or 0)
        row["score_sum"] += float(gene.get("score") or 0.0)
        row["sources"].update(gene.get("sources") or {})
        row["top_genes"].append(
            {
                "gene_id": str(gene_id)[:220],
                "seen": int(gene.get("seen") or 0),
                "score": round(float(gene.get("score") or 0.0), 4),
                "wins": int(gene.get("wins") or 0),
                "losses": int(gene.get("losses") or 0),
                "neutral": int(gene.get("neutral") or 0),
            }
        )

    symbols = []
    for symbol, row in by_symbol.items():
        genes_count = max(1, int(row["genes"]))
        top = sorted(
            row["top_genes"],
            key=lambda item: (item["score"], item["seen"]),
            reverse=True,
        )[:5]
        symbols.append(
            {
                "symbol": symbol,
                "genes": row["genes"],
                "seen": row["seen"],
                "wins": row["wins"],
                "losses": row["losses"],
                "neutral": row["neutral"],
                "avg_score": round(float(row["score_sum"]) / genes_count, 4),
                "sources": dict(row["sources"]),
                "top_genes": top,
            }
        )

    symbols.sort(key=lambda item: (item["symbol"] == "GLOBAL/UNKNOWN", -item["seen"], item["symbol"]))

    return {
        "file": str(path),
        "exists": path.exists(),
        "created_at": data.get("created_at") if isinstance(data, dict) else None,
        "updated_at": data.get("updated_at") if isinstance(data, dict) else None,
        "global_stats": data.get("global_stats", {}) if isinstance(data, dict) else {},
        "symbols": symbols,
    }


def summarize_historical_report() -> dict[str, Any]:
    path = ROOT / "friday_gene_performance_report.json"
    report = load_json(path, {})
    rows = []
    seen: set[str] = set()

    for row in (report.get("top_profitable") or []) + (report.get("worst_genes") or []):
        gene_id = str(row.get("gene_id") or "")
        if not gene_id or gene_id in seen:
            continue
        seen.add(gene_id)
        symbol = gene_id.split(":", 1)[0] if ":" in gene_id else "UNKNOWN"
        rows.append(
            {
                "symbol": symbol,
                "gene_id": gene_id,
                "count": int(row.get("count") or 0),
                "wins": int(row.get("wins") or 0),
                "losses": int(row.get("losses") or 0),
                "neutral": int(row.get("neutral") or 0),
                "win_rate": float(row.get("win_rate") or 0.0),
                "total_profit": float(row.get("total_profit") or 0.0),
                "avg_profit": float(row.get("avg_profit") or 0.0),
            }
        )

    by_symbol: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"genes": 0, "trades": 0, "wins": 0, "losses": 0, "neutral": 0, "profit": 0.0}
    )
    for row in rows:
        item = by_symbol[row["symbol"]]
        item["genes"] += 1
        item["trades"] += row["count"]
        item["wins"] += row["wins"]
        item["losses"] += row["losses"]
        item["neutral"] += row["neutral"]
        item["profit"] += row["total_profit"]

    symbols = []
    for symbol, item in by_symbol.items():
        trades = int(item["trades"])
        symbols.append(
            {
                "symbol": symbol,
                "genes": item["genes"],
                "trades": trades,
                "wins": item["wins"],
                "losses": item["losses"],
                "neutral": item["neutral"],
                "win_rate": round(item["wins"] / trades, 4) if trades else 0.0,
                "profit": round(float(item["profit"]), 2),
            }
        )

    symbols.sort(key=lambda item: item["profit"], reverse=True)
    return {
        "file": str(path),
        "exists": path.exists(),
        "total_genes": report.get("total_genes"),
        "total_trade_outcomes": report.get("total_trade_outcomes"),
        "source_note": "Aggregated from top_profitable and worst_genes rows in the report.",
        "symbols": symbols,
        "best_genes": sorted(rows, key=lambda item: item["total_profit"], reverse=True)[:10],
        "worst_genes": sorted(rows, key=lambda item: item["total_profit"])[:10],
    }


def genome_fitness(genome: dict[str, Any]) -> float:
    trades = int(genome.get("trades") or 0)
    if trades < 8:
        return 0.0
    wins = int(genome.get("wins") or 0)
    win_pnl = float(genome.get("win_pnl") or 0.0)
    loss_pnl = float(genome.get("loss_pnl") or 0.0)
    total_pnl = float(genome.get("total_pnl") or 0.0)
    win_rate = wins / trades if trades else 0.0
    profit_factor = win_pnl / loss_pnl if loss_pnl > 0 else (1.0 if win_pnl > 0 else 0.0)
    return round(0.35 * win_rate + 0.45 * max(0.0, min(1.0, profit_factor / 2.0)) + 0.20 * (1 if total_pnl > 0 else 0), 4)


def summarize_population_file(path: Path) -> dict[str, Any] | None:
    data = load_json(path, None)
    if not isinstance(data, dict):
        return None

    population = data.get("population") or []
    by_symbol: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "population": 0,
            "trades": 0,
            "wins": 0,
            "pnl": 0.0,
            "protected": 0,
            "active": 0,
            "best_fitness": 0.0,
        }
    )

    for genome in population:
        symbol = str(genome.get("symbol") or data.get("symbol") or "UNKNOWN")
        row = by_symbol[symbol]
        row["population"] += 1
        row["trades"] += int(genome.get("trades") or 0)
        row["wins"] += int(genome.get("wins") or 0)
        row["pnl"] += float(genome.get("total_pnl") or 0.0)
        row["protected"] += 1 if genome.get("is_protected") else 0
        row["active"] += 1 if genome.get("is_active") else 0
        row["best_fitness"] = max(row["best_fitness"], genome_fitness(genome))

    return {
        "file": str(path),
        "generation": int(data.get("generation") or 0),
        "active_id": data.get("active_id") or "",
        "trades_to_evolve": int(data.get("trades_to_evolve") or 0),
        "symbols": dict(by_symbol),
    }


def summarize_genetic_populations() -> dict[str, Any]:
    files = []
    legacy = ROOT / "data" / "strategy_population.json"
    if legacy.exists():
        files.append(legacy)
    scoped_dir = ROOT / "data" / "strategy_populations"
    if scoped_dir.exists():
        files.extend(sorted(scoped_dir.glob("*.json")))

    summaries = [item for path in files if (item := summarize_population_file(path))]
    combined: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "population": 0,
            "trades": 0,
            "wins": 0,
            "pnl": 0.0,
            "protected": 0,
            "active": 0,
            "best_fitness": 0.0,
        }
    )

    for summary in summaries:
        for symbol, row in (summary.get("symbols") or {}).items():
            item = combined[symbol]
            item["population"] += int(row.get("population") or 0)
            item["trades"] += int(row.get("trades") or 0)
            item["wins"] += int(row.get("wins") or 0)
            item["pnl"] += float(row.get("pnl") or 0.0)
            item["protected"] += int(row.get("protected") or 0)
            item["active"] += int(row.get("active") or 0)
            item["best_fitness"] = max(float(item["best_fitness"]), float(row.get("best_fitness") or 0.0))

    symbols = []
    for symbol, row in combined.items():
        trades = int(row["trades"])
        symbols.append(
            {
                "symbol": symbol,
                "population": int(row["population"]),
                "trades": trades,
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / trades, 4) if trades else 0.0,
                "pnl": round(float(row["pnl"]), 2),
                "protected": int(row["protected"]),
                "active": int(row["active"]),
                "best_fitness": round(float(row["best_fitness"]), 4),
            }
        )
    symbols.sort(key=lambda item: (item["symbol"] == "TEST", item["symbol"]))

    return {
        "files": [str(path) for path in files],
        "file_summaries": summaries,
        "symbols": symbols,
    }


def summarize_live_state() -> dict[str, Any]:
    state, state_error = http_json(STATE_URL)
    evolution, evolution_error = http_json(EVOLUTION_URL)
    symbol_states = state.get("symbol_states", {}) if isinstance(state, dict) else {}
    action_counts = Counter(str((row or {}).get("action") or "UNKNOWN") for row in symbol_states.values())

    priority = []
    for symbol in PRIORITY_SYMBOLS:
        row = symbol_states.get(symbol) or {}
        priority.append(
            {
                "symbol": symbol,
                "action": row.get("action"),
                "price": row.get("price"),
                "prob": round(float(row.get("prob") or 0.0), 4),
                "positions": row.get("positions"),
                "genome_id": row.get("genome_id") or "",
                "genome_fitness": row.get("genome_fitness"),
            }
        )

    active = []
    for symbol, row in symbol_states.items():
        action = str((row or {}).get("action") or "")
        if action and action != "NO_TRADE":
            active.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "price": row.get("price"),
                    "prob": round(float(row.get("prob") or 0.0), 4),
                    "positions": row.get("positions"),
                }
            )
    active.sort(key=lambda item: (item["action"], item["symbol"]))

    account = state.get("account", {}) if isinstance(state, dict) else {}
    return {
        "state_url": STATE_URL,
        "state_error": state_error,
        "evolution_url": EVOLUTION_URL,
        "evolution_error": evolution_error,
        "account": {
            "login": account.get("login"),
            "server": account.get("server"),
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "currency": account.get("currency"),
            "connected": account.get("connected"),
            "demo_detected": account.get("demo_detected"),
        },
        "is_demo": state.get("is_demo") if isinstance(state, dict) else None,
        "account_type": state.get("account_type") if isinstance(state, dict) else None,
        "active_symbol": state.get("active_symbol") if isinstance(state, dict) else None,
        "symbols_configured": len(state.get("symbols") or []) if isinstance(state, dict) else 0,
        "symbols_with_live_state": len(symbol_states),
        "action_counts": dict(action_counts),
        "priority_symbols": priority,
        "active_signals_sample": active[:40],
        "open_positions_count": len(state.get("open_positions") or []) if isinstance(state, dict) else 0,
        "recent_trades_count": len(state.get("recent_trades") or []) if isinstance(state, dict) else 0,
        "evolution_api": evolution,
    }


def summarize_permissions() -> dict[str, Any]:
    autopilot = load_json(ROOT / "friday_autopilot_state.json", {})
    return {
        "external_status_file": str(OUT_FILE),
        "jarvis_can_read": True,
        "jarvis_should_write_only": [
            ".jarvis_agents/friday_genome_development_status.json",
            ".jarvis_agents/patch_requests/*.json",
        ],
        "patch_pipeline": {
            "proposal_gateway": "http://127.0.0.1:8799/dispatch/run",
            "review_gateway": "http://127.0.0.1:8799/patches",
            "apply_requires": [
                "approved patch",
                "unified diff",
                "safe allowlisted target",
                "backup before apply",
            ],
            "auto_apply_enabled": bool(autopilot.get("auto_apply_enabled", False)),
            "safe_edit_allowlist": autopilot.get("safe_edit_allowlist") or [],
            "blocked_keywords": autopilot.get("blocked_auto_apply_keywords") or [],
        },
        "recommended_boundary": "Do not grant Jarvis direct write/apply permissions for execution, order_send, or live-trading files.",
    }


def build_status() -> dict[str, Any]:
    strategy = summarize_strategy_genes()
    live = summarize_live_state()
    populations = summarize_genetic_populations()
    historical = summarize_historical_report()

    notes = []
    evo_api = live.get("evolution_api") or {}
    if not evo_api.get("population"):
        notes.append("Live /api/evolution currently reports no active population.")
    if any(item.get("symbol") == "GLOBAL/UNKNOWN" for item in strategy.get("symbols", [])):
        notes.append("Some current strategy genes are not symbol-scoped yet; new events after the symbol patch should be scoped.")
    if not any(item.get("trades") for item in populations.get("symbols", [])):
        notes.append("Genetic population files exist, but recorded genome trades are still zero.")

    return {
        "version": "0.1",
        "generated_at": now(),
        "project": "FRIDAY genome development status for Jarvis",
        "live": live,
        "strategy_genes": strategy,
        "genetic_populations": populations,
        "historical_performance": historical,
        "permissions": summarize_permissions(),
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FRIDAY genome development status for Jarvis.")
    parser.add_argument("--out", default=str(OUT_FILE), help="Output JSON path.")
    parser.add_argument("--print", action="store_true", help="Print compact JSON summary after writing.")
    args = parser.parse_args()

    status = build_status()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.print:
        compact = {
            "generated_at": status["generated_at"],
            "live_actions": status["live"].get("action_counts"),
            "strategy_global_stats": status["strategy_genes"].get("global_stats"),
            "population_symbols": status["genetic_populations"].get("symbols"),
            "notes": status["notes"],
            "out": str(out),
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
    else:
        print(str(out))


if __name__ == "__main__":
    main()
