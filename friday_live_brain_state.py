from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


ROOT = Path(r"C:\Users\Radhi\MT5")

STATE_FILE = ROOT / "friday_live_brain_state.json"
BRAIN_FILE = ROOT / "friday_brain_memory.json"
PROJECT_MAP_FILE = ROOT / "friday_project_map.json"
STRATEGY_GENES_FILE = ROOT / "friday_strategy_genes.json"
TOUCH_MEMORY_FILE = ROOT / "friday_touch_level_memory.json"
AUTOPILOT_STATE_FILE = ROOT / "friday_autopilot_state.json"
ORDERFLOW_STATE_FILE = ROOT / "friday_orderflow_state.json"
ORDERFLOW_EVENTS_FILE = ROOT / "friday_orderflow_events.json"
FEATURE_COUNCIL_FILE = ROOT / "friday_feature_council_state.json"

REALTIME_LOG_DIR = ROOT / "realtime_scalper_logs"
TOUCH_LOG_DIR = ROOT / "touch_executor_logs"
GOVERNOR_LOG_DIR = ROOT / "position_governor_logs"
AUTOPILOT_LOG_DIR = ROOT / "friday_autopilot_logs"
DISPATCH_LOG_DIR = ROOT / "gateway_dispatch_logs"

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "agents_app"

SERVICES = {
    "gateway": f"{os.getenv('FRIDAY_GATEWAY_URL', 'http://127.0.0.1:8799').rstrip('/')}/openapi.json",
    "chat": f"{os.getenv('FRIDAY_CHAT_URL', 'http://127.0.0.1:8811').rstrip('/')}/",
    "tradingview_dashboard": f"{os.getenv('FRIDAY_TRADINGVIEW_URL', 'http://127.0.0.1:8822').rstrip('/')}/api/state?symbol=XAUUSDm&timeframe=M1&bars=30",
    "agents_browser": f"{os.getenv('FRIDAY_AGENTS_URL', 'http://127.0.0.1:8833').rstrip('/')}/api/overview",
}

DEMO_ONLY_RULES = {
    "demo_only": True,
    "live_blocked": True,
    "no_file_delete": True,
    "patch_review_before_apply": True,
    "apply_requires_backup": True,
    "apply_requires_test": True,
    "trading_sensitive_files_read_only": True,
}

app = FastAPI(title="FRIDAY Live Brain State Bus", version="0.1")
_STATE_CACHE_LOCK = threading.Lock()
_STATE_CACHE: tuple[float, dict[str, Any]] | None = None
_STATE_CACHE_TTL_SECONDS = 4.0


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_json_safe(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(v) for v in value]

    return value


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(make_json_safe(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def latest_file(folder: Path, pattern: str = "*.jsonl") -> Path | None:
    if not folder.exists():
        return None

    files = [p for p in folder.glob(pattern) if p.is_file()]

    if not files:
        return None

    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def read_jsonl_tail(path: Path | None, limit: int = 400) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []

    for line in lines[-limit:]:
        line = line.strip()

        if not line:
            continue

        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    return rows


def read_log_tail(folder: Path, limit_lines: int = 80) -> str:
    path = latest_file(folder, "*.log")

    if not path:
        return ""

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-limit_lines:])
    except Exception:
        return ""


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
    except Exception:
        return []


def http_ok(url: str, timeout: int = 4) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            sample = resp.read(600).decode("utf-8", errors="replace")
            return {"ok": True, "sample": sample[:600]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_strategy_genes() -> dict[str, Any]:
    default = {
        "version": "0.1",
        "project": "FRIDAY Strategy Genes",
        "created_at": now(),
        "updated_at": now(),
        "rules": {
            "demo_only": True,
            "learn_from_scalper": True,
            "learn_from_touch_levels": True,
            "learn_from_governor": True,
            "reward_successful_genes": True,
            "punish_failed_genes": True,
            "council_consensus_required": True,
        },
        "global_stats": {
            "events": 0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "genes_count": 0,
        },
        "genes": {},
        "agent_accountability": {},
        "council_history": [],
    }

    genes = read_json(STRATEGY_GENES_FILE, None)

    if not isinstance(genes, dict):
        genes = default
        write_json(STRATEGY_GENES_FILE, genes)
        return genes

    changed = False

    for key, value in default.items():
        if key not in genes:
            genes[key] = value
            changed = True

    if changed:
        genes["updated_at"] = now()
        write_json(STRATEGY_GENES_FILE, genes)

    return genes


def gene_key_from_reason(action: str, reason: str, symbol: str = "") -> str:
    tokens = []

    for part in str(reason or "").replace("|", "+").split("+"):
        p = part.strip()

        if not p:
            continue

        if any(x.lower() in p.lower() for x in [
            "trend",
            "bos",
            "choch",
            "fvg",
            "sweep",
            "vwap",
            "delta",
            "support",
            "resistance",
            "premium",
            "discount",
            "level",
            "touch",
            "breakout",
            "reversal",
            "governor",
        ]):
            tokens.append(p)

    if not tokens:
        tokens = ["unknown_pattern"]

    prefix = f"{symbol}:" if str(symbol or "").strip() else ""
    return f"{prefix}{action}:{'|'.join(tokens[:12])}"[:260]


def register_gene_event(
    genes: dict[str, Any],
    action: str,
    reason: str,
    source: str,
    result: str = "neutral",
    confidence: float = 0.0,
    pnl_points: float = 0.0,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    symbol = str(meta.get("symbol") or "").strip()
    gene_id = gene_key_from_reason(action, reason, symbol=symbol)
    gene_map = genes.setdefault("genes", {})

    gene = gene_map.setdefault(
        gene_id,
        {
            "gene_id": gene_id,
            "created_at": now(),
            "updated_at": now(),
            "sources": {},
            "seen": 0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "score": 1.0,
            "confidence_boost": 0.0,
            "last_result": None,
            "examples": [],
        },
    )

    gene["seen"] = int(gene.get("seen", 0) or 0) + 1
    gene["updated_at"] = now()
    gene.setdefault("sources", {})[source] = int(gene.setdefault("sources", {}).get(source, 0) or 0) + 1

    result = str(result or "neutral").lower().strip()

    if result == "win":
        gene["wins"] = int(gene.get("wins", 0) or 0) + 1
        gene["score"] = min(10.0, float(gene.get("score", 1.0) or 1.0) + 0.14)
        gene["confidence_boost"] = min(0.35, float(gene.get("confidence_boost", 0.0) or 0.0) + 0.012)
        genes.setdefault("global_stats", {})["wins"] = int(genes.setdefault("global_stats", {}).get("wins", 0) or 0) + 1

    elif result == "loss":
        gene["losses"] = int(gene.get("losses", 0) or 0) + 1
        gene["score"] = max(0.05, float(gene.get("score", 1.0) or 1.0) - 0.18)
        gene["confidence_boost"] = max(-0.35, float(gene.get("confidence_boost", 0.0) or 0.0) - 0.018)
        genes.setdefault("global_stats", {})["losses"] = int(genes.setdefault("global_stats", {}).get("losses", 0) or 0) + 1

    else:
        gene["neutral"] = int(gene.get("neutral", 0) or 0) + 1
        genes.setdefault("global_stats", {})["neutral"] = int(genes.setdefault("global_stats", {}).get("neutral", 0) or 0) + 1

    example = {
        "time": now(),
        "source": source,
        "symbol": symbol,
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "result": result,
        "pnl_points": pnl_points,
        "meta": meta,
    }

    gene["examples"] = (gene.get("examples") or [])[-25:] + [example]
    gene["last_result"] = example

    stats = genes.setdefault("global_stats", {})
    stats["events"] = int(stats.get("events", 0) or 0) + 1
    stats["genes_count"] = len(gene_map)

    genes["updated_at"] = now()

    return gene


def extract_scalper_events() -> dict[str, Any]:
    path = latest_file(REALTIME_LOG_DIR, "realtime_demo_executor_*.jsonl")
    if not path:
        path = latest_file(REALTIME_LOG_DIR, "realtime_scalper_*.jsonl")

    events = read_jsonl_tail(path, limit=500)

    latest_decision = None
    latest_execution = None
    executions = []

    for event in events:
        typ = event.get("type")
        decision = event.get("decision") or {}

        if decision:
            latest_decision = decision

        if typ == "demo_execution":
            latest_execution = event
            executions.append(event)

    return {
        "log_path": str(path) if path else None,
        "latest_decision": latest_decision,
        "latest_execution": latest_execution,
        "executions": executions[-30:],
        "events_count": len(events),
    }


def extract_touch_events() -> dict[str, Any]:
    path = latest_file(TOUCH_LOG_DIR, "touch_demo_executor_*.jsonl")
    events = read_jsonl_tail(path, limit=500)

    latest_plan = None
    latest_execution = None
    executions = []

    for event in events:
        plan = event.get("plan") or {}

        if plan:
            latest_plan = plan

        if event.get("type") == "touch_execution":
            latest_execution = event
            executions.append(event)

    return {
        "log_path": str(path) if path else None,
        "latest_plan": latest_plan,
        "latest_execution": latest_execution,
        "executions": executions[-30:],
        "events_count": len(events),
    }


def extract_governor_events() -> dict[str, Any]:
    path = latest_file(GOVERNOR_LOG_DIR, "governor_*.jsonl")
    events = read_jsonl_tail(path, limit=500)

    latest_decision = None
    closes = []
    reverses = []

    for event in events:
        decision = event.get("decision") or {}

        if decision:
            latest_decision = decision

        if event.get("close_result"):
            closes.append(event)

        if event.get("reverse_result"):
            reverses.append(event)

    return {
        "log_path": str(path) if path else None,
        "latest_decision": latest_decision,
        "closes": closes[-30:],
        "reverses": reverses[-30:],
        "events_count": len(events),
    }


def extract_touch_memory_summary() -> dict[str, Any]:
    memory = read_json(TOUCH_MEMORY_FILE, {})

    symbols = memory.get("symbols", {}) if isinstance(memory, dict) else {}

    summary = {
        "exists": TOUCH_MEMORY_FILE.exists(),
        "updated_at": memory.get("updated_at") if isinstance(memory, dict) else None,
        "symbols": [],
        "top_levels": [],
        "live_results_count": len(memory.get("live_results", []) or []) if isinstance(memory, dict) else 0,
    }

    for symbol, data in symbols.items():
        tf_data = data.get("timeframes", {}) if isinstance(data, dict) else {}
        total_levels = sum(len(v or []) for v in tf_data.values())
        summary["symbols"].append({"symbol": symbol, "levels": total_levels})

        levels = []

        for tf, rows in tf_data.items():
            for row in rows or []:
                score = max(
                    float(row.get("buy_score", 0.0) or 0.0),
                    float(row.get("sell_score", 0.0) or 0.0),
                    float(row.get("breakout_buy_score", 0.0) or 0.0),
                    float(row.get("breakout_sell_score", 0.0) or 0.0),
                )
                levels.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "level": row.get("level"),
                    "touches": row.get("touches"),
                    "score": round(score, 4),
                    "buy_score": row.get("buy_score"),
                    "sell_score": row.get("sell_score"),
                    "breakout_buy_score": row.get("breakout_buy_score"),
                    "breakout_sell_score": row.get("breakout_sell_score"),
                })

        levels.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
        summary["top_levels"].extend(levels[:10])

    summary["top_levels"] = summary["top_levels"][:20]
    return summary


def extract_dispatch_state() -> dict[str, Any]:
    jobs = db_all(
        """
        SELECT id, status, model, report_path, patch_json_path, created_at, updated_at
        FROM dispatch_jobs
        ORDER BY id DESC
        LIMIT 20
        """
    )

    runs = db_all(
        """
        SELECT id, job_id, agent_name, agent_role, status, created_at
        FROM dispatch_agent_runs
        ORDER BY id DESC
        LIMIT 60
        """
    )

    patches = db_all(
        """
        SELECT id, job_id, agent_name, agent_role, target_file, risk, approved, applied, created_at,
               LEFT(reason, 300) AS reason_preview
        FROM dispatch_patch_proposals
        ORDER BY id DESC
        LIMIT 40
        """
    )

    active_runs = [r for r in runs if str(r.get("status", "")).lower() in {"running", "queued"}]

    return {
        "jobs": jobs,
        "agent_runs": runs,
        "active_runs": active_runs,
        "patches": patches,
    }


def compute_agent_accountability(genes: dict[str, Any], dispatch: dict[str, Any]) -> dict[str, Any]:
    accountability = genes.setdefault("agent_accountability", {})

    for run in dispatch.get("agent_runs", [])[-40:]:
        agent = str(run.get("agent_name") or "UNKNOWN")
        role = str(run.get("agent_role") or "UNKNOWN")
        key = f"{agent}/{role}"
        status = str(run.get("status") or "").lower()

        acc = accountability.setdefault(
            key,
            {
                "agent": agent,
                "role": role,
                "score": 1.0,
                "done": 0,
                "failed": 0,
                "running": 0,
                "punishments": 0,
                "rewards": 0,
                "last_action": None,
            },
        )

        seen_key = f"_seen_run_{run.get('id')}"
        if acc.get(seen_key):
            continue

        acc[seen_key] = True

        if status == "done":
            acc["done"] = int(acc.get("done", 0) or 0) + 1
            acc["score"] = min(10.0, float(acc.get("score", 1.0) or 1.0) + 0.03)
            acc["rewards"] = int(acc.get("rewards", 0) or 0) + 1
            acc["last_action"] = f"reward_done_job_{run.get('job_id')}"

        elif status == "failed":
            acc["failed"] = int(acc.get("failed", 0) or 0) + 1
            acc["score"] = max(0.05, float(acc.get("score", 1.0) or 1.0) - 0.08)
            acc["punishments"] = int(acc.get("punishments", 0) or 0) + 1
            acc["last_action"] = f"punish_failed_job_{run.get('job_id')}"

        elif status in {"running", "queued"}:
            acc["running"] = int(acc.get("running", 0) or 0) + 1
            acc["last_action"] = f"monitor_{status}_job_{run.get('job_id')}"

    # Penalize agents proposing bad patches.
    for patch in dispatch.get("patches", [])[-40:]:
        agent = str(patch.get("agent_name") or "UNKNOWN")
        role = str(patch.get("agent_role") or "UNKNOWN")
        key = f"{agent}/{role}"

        acc = accountability.setdefault(
            key,
            {
                "agent": agent,
                "role": role,
                "score": 1.0,
                "done": 0,
                "failed": 0,
                "running": 0,
                "punishments": 0,
                "rewards": 0,
                "last_action": None,
            },
        )

        seen_key = f"_seen_patch_{patch.get('id')}"
        if acc.get(seen_key):
            continue

        acc[seen_key] = True

        risk = str(patch.get("risk") or "").lower()
        approved = int(patch.get("approved") or 0)
        applied = int(patch.get("applied") or 0)

        if risk in {"high", "medium"} and applied == 0:
            acc["score"] = max(0.05, float(acc.get("score", 1.0) or 1.0) - 0.04)
            acc["punishments"] = int(acc.get("punishments", 0) or 0) + 1
            acc["last_action"] = f"punish_risky_patch_{patch.get('id')}"

        elif risk == "low" and approved == 1 and applied == 1:
            acc["score"] = min(10.0, float(acc.get("score", 1.0) or 1.0) + 0.05)
            acc["rewards"] = int(acc.get("rewards", 0) or 0) + 1
            acc["last_action"] = f"reward_applied_patch_{patch.get('id')}"

    return accountability


def council_vote(
    scalper: dict[str, Any],
    touch: dict[str, Any],
    governor: dict[str, Any],
    touch_memory: dict[str, Any],
    services: dict[str, Any],
) -> dict[str, Any]:
    votes = []

    sd = scalper.get("latest_decision") or {}
    scalper_reason = str(sd.get("reason", "") or "")
    spread_blocked = "spread_block" in scalper_reason

    if sd:
        vote = sd.get("action", "HOLD")

        if spread_blocked and vote in {"BUY", "SELL"}:
            vote = "HOLD"

        votes.append({
            "name": "Realtime Scalper",
            "vote": vote,
            "confidence": float(sd.get("confidence", 0.0) or 0.0),
            "reason": scalper_reason,
        })

    tp = touch.get("latest_plan") or {}
    touch_order_kind = str(tp.get("order_kind", "") or "")
    touch_action = str(tp.get("action", "HOLD") or "HOLD")
    touch_near = float(tp.get("near_points", 999999) or 999999)
    touch_conf = float(tp.get("confidence", 0.0) or 0.0)

    if tp:
        # If level is far, this is a pending plan, not a direct market vote.
        if touch_order_kind in {"BUY_LIMIT", "BUY_STOP"} or (touch_action == "BUY" and touch_near > 650):
            vote = "PENDING_BUY"
        elif touch_order_kind in {"SELL_LIMIT", "SELL_STOP"} or (touch_action == "SELL" and touch_near > 650):
            vote = "PENDING_SELL"
        else:
            vote = touch_action

        votes.append({
            "name": "Touch Level Brain",
            "vote": vote,
            "confidence": touch_conf,
            "reason": tp.get("reason", ""),
            "order_kind": touch_order_kind,
            "near_points": touch_near,
            "entry": tp.get("entry"),
            "tp": tp.get("tp"),
            "sl_mode": tp.get("sl_mode"),
        })

    gd = governor.get("latest_decision") or {}
    if gd:
        reverse = gd.get("reverse_action")
        action = gd.get("action")
        vote = reverse if action == "CLOSE_AND_REVERSE" and reverse else "HOLD"

        votes.append({
            "name": "Position Governor",
            "vote": vote,
            "confidence": float((gd.get("council") or {}).get("confidence", 0.0) or 0.0),
            "reason": gd.get("reason", ""),
        })

    service_ok = all(v.get("ok") for v in services.values())
    top_levels = touch_memory.get("top_levels", []) or []

    if not service_ok or len(top_levels) == 0:
        risk_vote = "BLOCK"
        risk_reason = "missing_service_or_touch_memory"
    elif spread_blocked:
        risk_vote = "BLOCK_MARKET"
        risk_reason = "spread_block_market_only_pending_allowed"
    else:
        risk_vote = "ALLOW"
        risk_reason = "services_ok_and_touch_memory_ready"

    votes.append({
        "name": "Risk Manager",
        "vote": risk_vote,
        "confidence": 1.0 if risk_vote in {"ALLOW", "BLOCK_MARKET"} else 0.0,
        "reason": risk_reason,
    })

    buy = sum(float(v.get("confidence", 0.0) or 0.0) for v in votes if v.get("vote") == "BUY")
    sell = sum(float(v.get("confidence", 0.0) or 0.0) for v in votes if v.get("vote") == "SELL")
    pending_buy = sum(float(v.get("confidence", 0.0) or 0.0) for v in votes if v.get("vote") == "PENDING_BUY")
    pending_sell = sum(float(v.get("confidence", 0.0) or 0.0) for v in votes if v.get("vote") == "PENDING_SELL")
    hold = sum(float(v.get("confidence", 0.0) or 0.0) for v in votes if v.get("vote") in {"HOLD", "BLOCK", "BLOCK_MARKET"})

    total = max(buy + sell + pending_buy + pending_sell + hold, 1e-9)

    if risk_vote == "BLOCK":
        final = "BLOCK"
        confidence = 0.0

    elif risk_vote == "BLOCK_MARKET":
        # High spread: no market order, but pending plans are allowed.
        if pending_buy > pending_sell and pending_buy > 0:
            final = "PENDING_BUY"
            confidence = pending_buy / total
        elif pending_sell > pending_buy and pending_sell > 0:
            final = "PENDING_SELL"
            confidence = pending_sell / total
        else:
            final = "HOLD"
            confidence = hold / total

    elif buy > sell and buy > hold and buy >= pending_buy:
        final = "BUY"
        confidence = buy / total

    elif sell > buy and sell > hold and sell >= pending_sell:
        final = "SELL"
        confidence = sell / total

    elif pending_buy > pending_sell and pending_buy > hold:
        final = "PENDING_BUY"
        confidence = pending_buy / total

    elif pending_sell > pending_buy and pending_sell > hold:
        final = "PENDING_SELL"
        confidence = pending_sell / total

    else:
        final = "HOLD"
        confidence = hold / total

    return {
        "time": now(),
        "final_vote": final,
        "confidence": round(float(min(0.99, confidence)), 4),
        "scoreboard": {
            "buy": round(buy, 4),
            "sell": round(sell, 4),
            "pending_buy": round(pending_buy, 4),
            "pending_sell": round(pending_sell, 4),
            "hold_or_block": round(hold, 4),
        },
        "risk": {
            "spread_blocked": spread_blocked,
            "risk_vote": risk_vote,
            "risk_reason": risk_reason,
        },
        "votes": votes,
    }


def learn_from_current_state(
    genes: dict[str, Any],
    scalper: dict[str, Any],
    touch: dict[str, Any],
    governor: dict[str, Any],
    council: dict[str, Any],
) -> dict[str, Any]:
    learned = []

    def event_symbol(*items: Any) -> str:
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("symbol",):
                symbol = str(item.get(key) or "").strip()
                if symbol:
                    return symbol
            for nested_key in ("decision", "plan"):
                nested = item.get(nested_key)
                if isinstance(nested, dict):
                    symbol = str(nested.get("symbol") or "").strip()
                    if symbol:
                        return symbol
        return ""

    sd = scalper.get("latest_decision") or {}
    sd_symbol = event_symbol(sd, scalper.get("latest_execution") or {})
    if sd:
        gene = register_gene_event(
            genes=genes,
            action=str(sd.get("action") or "HOLD"),
            reason=str(sd.get("reason") or ""),
            source="scalper",
            result="neutral",
            confidence=float(sd.get("confidence", 0.0) or 0.0),
            meta={
                "symbol": sd_symbol,
                "buy_score": sd.get("buy_score"),
                "sell_score": sd.get("sell_score"),
                "spread_points": sd.get("spread_points"),
            },
        )
        learned.append({"source": "scalper", "gene_id": gene["gene_id"], "score": gene["score"]})

    tp = touch.get("latest_plan") or {}
    tp_symbol = event_symbol(tp, touch.get("latest_execution") or {})
    if tp:
        gene = register_gene_event(
            genes=genes,
            action=str(tp.get("action") or "HOLD"),
            reason=str(tp.get("reason") or ""),
            source="touch",
            result="neutral",
            confidence=float(tp.get("confidence", 0.0) or 0.0),
            meta={
                "symbol": tp_symbol,
                "level": tp.get("level"),
                "timeframe": tp.get("timeframe"),
                "sl_mode": tp.get("sl_mode"),
                "order_kind": tp.get("order_kind"),
            },
        )
        learned.append({"source": "touch", "gene_id": gene["gene_id"], "score": gene["score"]})

    gd = governor.get("latest_decision") or {}
    gd_symbol = event_symbol(
        gd,
        (governor.get("closes") or [])[-1] if governor.get("closes") else {},
        (governor.get("reverses") or [])[-1] if governor.get("reverses") else {},
    )
    if gd:
        action = gd.get("reverse_action") or gd.get("action") or "HOLD"
        result = "neutral"

        profit = float(gd.get("profit", 0.0) or 0.0)
        if profit > 0.20 and gd.get("action") in {"CLOSE", "CLOSE_AND_REVERSE"}:
            result = "win"
        elif profit < -0.50 and gd.get("action") in {"CLOSE", "CLOSE_AND_REVERSE"}:
            result = "loss"

        gene = register_gene_event(
            genes=genes,
            action=str(action),
            reason=str(gd.get("reason") or ""),
            source="governor",
            result=result,
            confidence=float((gd.get("council") or {}).get("confidence", 0.0) or 0.0),
            pnl_points=0.0,
            meta={
                "symbol": gd_symbol,
                "ticket": gd.get("ticket"),
                "position_type": gd.get("position_type"),
                "profit": gd.get("profit"),
            },
        )
        learned.append({"source": "governor", "gene_id": gene["gene_id"], "score": gene["score"], "result": result})

    # Council gene: rewards agreement patterns.
    vote_reason = "+".join([f"{v['name']}={v['vote']}" for v in council.get("votes", [])])
    gene = register_gene_event(
        genes=genes,
        action=str(council.get("final_vote") or "HOLD"),
        reason=vote_reason,
        source="council",
        result="neutral",
        confidence=float(council.get("confidence", 0.0) or 0.0),
        meta={
            "symbol": sd_symbol or tp_symbol or gd_symbol,
            "scoreboard": council.get("scoreboard"),
        },
    )
    learned.append({"source": "council", "gene_id": gene["gene_id"], "score": gene["score"]})

    genes.setdefault("council_history", []).append(council)
    genes["council_history"] = genes["council_history"][-200:]
    genes["updated_at"] = now()

    return {"learned": learned}


def top_genes(genes: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    rows = list((genes.get("genes") or {}).values())
    rows.sort(
        key=lambda x: (
            float(x.get("score", 0.0) or 0.0),
            int(x.get("wins", 0) or 0),
            int(x.get("seen", 0) or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def compute_orderflow_advisor_vote(symbol: str = "XAUUSDm") -> dict[str, Any]:
    """
    PHASE 9 — Order Flow Advisor.
    Reads orderflow state + feature council state to produce a unified advisor vote.
    Vote: BUY | SELL | HOLD | PENDING_BUY | PENDING_SELL | BLOCK_MARKET
    """
    of_state = read_json(ORDERFLOW_STATE_FILE, {})
    council_state = read_json(FEATURE_COUNCIL_FILE, {})

    decisions = council_state.get("decisions", [])
    council_dec = next((d for d in decisions if d.get("symbol") == symbol), {})
    council_action = str(council_dec.get("action", "HOLD")).upper()
    council_conf = float(council_dec.get("confidence", 0.0) or 0.0)
    spread_mode = str((council_dec.get("vwap_summary") or {}).get("vwap_signal", "") or "")

    of_symbol = (of_state.get("symbols", {}) or {}).get(symbol, {})
    of_m1 = of_symbol.get("M1", {})

    vp = of_m1.get("volume_profile", {})
    delta = of_m1.get("delta_features", {})
    absorption = of_m1.get("absorption_exhaustion", {})
    events = of_m1.get("events", [])

    loc = vp.get("price_location_vs_value_area", "INSIDE_VALUE")
    divergence = delta.get("delta_divergence", "NONE")
    vol_spike = float(delta.get("volume_spike_score", 1.0) or 1.0)
    abs_buy = bool(absorption.get("absorption_buy", False))
    abs_sell = bool(absorption.get("absorption_sell", False))
    exh_buy = bool(absorption.get("exhaustion_buy", False))
    exh_sell = bool(absorption.get("exhaustion_sell", False))
    vwap_signal = str((council_dec.get("vwap_summary") or {}).get("vwap_signal", "") or "")

    # Derive OF directional signal
    of_buy_signals = 0
    of_sell_signals = 0
    reasons = []

    if vwap_signal in {"VWAP_RECLAIM"}:
        of_buy_signals += 2
        reasons.append("VWAP_RECLAIM")
    elif vwap_signal in {"VWAP_REJECTION"}:
        of_sell_signals += 2
        reasons.append("VWAP_REJECTION")
    elif vwap_signal == "ABOVE_VWAP":
        of_buy_signals += 1
        reasons.append("ABOVE_VWAP")
    elif vwap_signal == "BELOW_VWAP":
        of_sell_signals += 1
        reasons.append("BELOW_VWAP")

    if loc == "ABOVE_VALUE":
        of_buy_signals += 1
        reasons.append("ABOVE_VALUE_AREA")
    elif loc == "BELOW_VALUE":
        of_sell_signals += 1
        reasons.append("BELOW_VALUE_AREA")

    if divergence == "BULLISH_DIVERGENCE":
        of_buy_signals += 2
        reasons.append("BULLISH_DELTA_DIV")
    elif divergence == "BEARISH_DIVERGENCE":
        of_sell_signals += 2
        reasons.append("BEARISH_DELTA_DIV")

    if abs_buy:
        of_buy_signals += 2
        reasons.append("ABSORPTION_BUY")
    if abs_sell:
        of_sell_signals += 2
        reasons.append("ABSORPTION_SELL")

    if exh_buy:
        of_sell_signals += 1
        reasons.append("EXHAUSTION_BUY_CAUTION")
    if exh_sell:
        of_buy_signals += 1
        reasons.append("EXHAUSTION_SELL_CAUTION")

    # Determine OF vote
    if of_buy_signals >= 3:
        of_vote = "BUY"
    elif of_sell_signals >= 3:
        of_vote = "SELL"
    elif of_buy_signals > of_sell_signals:
        of_vote = "PENDING_BUY"
    elif of_sell_signals > of_buy_signals:
        of_vote = "PENDING_SELL"
    else:
        of_vote = "HOLD"

    # Spread guard: if spread extreme, force pending only
    if "EXTREME_BLOCK" in str(council_dec.get("execution_mode", "") or ""):
        of_vote = "BLOCK_MARKET"
        reasons.append("SPREAD_EXTREME")

    # Check if all recent OF events (conf>=0.7) point to one direction
    of_events_raw: list[dict[str, Any]] = []
    try:
        raw = read_json(ORDERFLOW_EVENTS_FILE, [])
        if isinstance(raw, list):
            of_events_raw = raw[-20:]
    except Exception:
        pass

    high_conf_events = [e for e in of_events_raw if float(e.get("confidence", 0.0) or 0.0) >= 0.7]
    hc_sell = sum(1 for e in high_conf_events if e.get("side") == "SELL")
    hc_buy = sum(1 for e in high_conf_events if e.get("side") == "BUY")
    all_hc_sell = len(high_conf_events) >= 3 and hc_sell >= len(high_conf_events) * 0.75
    all_hc_buy = len(high_conf_events) >= 3 and hc_buy >= len(high_conf_events) * 0.75

    if all_hc_sell and of_vote not in {"BUY"}:
        of_vote = "SELL"
        reasons.append(f"HIGH_CONF_SELL_EVENTS({hc_sell}/{len(high_conf_events)})")
    elif all_hc_buy and of_vote not in {"SELL"}:
        of_vote = "BUY"
        reasons.append(f"HIGH_CONF_BUY_EVENTS({hc_buy}/{len(high_conf_events)})")

    # Merge with Feature Council
    if of_vote == "BLOCK_MARKET":
        final_vote = "BLOCK_MARKET"
        merged_confidence = 0.0
        merge_note = "SPREAD_BLOCKED"
    elif council_action in {"BUY", "SELL"} and of_vote == council_action:
        final_vote = council_action
        merged_confidence = min(0.99, council_conf + 0.08)
        merge_note = "OF_CONFIRMS_COUNCIL"
    elif council_action in {"BUY", "SELL"} and of_vote in {"BUY", "SELL"} and of_vote != council_action:
        # Contradiction: lower confidence, hold direction only if council is strong
        if council_conf >= 0.65:
            final_vote = council_action
            merged_confidence = max(0.0, council_conf - 0.10)
            merge_note = "OF_CONTRADICTS_LOW_IMPACT"
        else:
            final_vote = "HOLD"
            merged_confidence = max(0.0, council_conf - 0.15)
            merge_note = "OF_CONTRADICTS_COUNCIL_HOLD"
    else:
        final_vote = council_action
        merged_confidence = council_conf
        merge_note = "OF_NEUTRAL"

    return {
        "symbol": symbol,
        "orderflow_vote": of_vote,
        "council_action": council_action,
        "final_vote": final_vote,
        "merged_confidence": round(merged_confidence, 4),
        "merge_note": merge_note,
        "of_buy_signals": of_buy_signals,
        "of_sell_signals": of_sell_signals,
        "reasons": reasons,
        "updated_at": now(),
    }


def primary_orderflow_symbol() -> str:
    of_state = read_json(ORDERFLOW_STATE_FILE, {})
    symbols = of_state.get("symbols", {}) if isinstance(of_state, dict) else {}
    if isinstance(symbols, dict) and symbols:
        return next(iter(symbols.keys()))

    council_state = read_json(FEATURE_COUNCIL_FILE, {})
    for decision in council_state.get("decisions", []) if isinstance(council_state, dict) else []:
        symbol = str(decision.get("symbol") or "").strip()
        if symbol:
            return symbol

    return "XAUUSDm"


def build_state() -> dict[str, Any]:
    genes = ensure_strategy_genes()
    brain = read_json(BRAIN_FILE, {})
    project_map = read_json(PROJECT_MAP_FILE, {})
    autopilot = read_json(AUTOPILOT_STATE_FILE, {})

    services = {name: http_ok(url) for name, url in SERVICES.items()}

    scalper = extract_scalper_events()
    touch = extract_touch_events()
    governor = extract_governor_events()
    touch_memory = extract_touch_memory_summary()
    dispatch = extract_dispatch_state()

    accountability = compute_agent_accountability(genes, dispatch)

    council = council_vote(
        scalper=scalper,
        touch=touch,
        governor=governor,
        touch_memory=touch_memory,
        services=services,
    )

    learning = learn_from_current_state(
        genes=genes,
        scalper=scalper,
        touch=touch,
        governor=governor,
        council=council,
    )

    # PHASE 9 — Order Flow Advisor vote
    try:
        orderflow_advisor = compute_orderflow_advisor_vote(primary_orderflow_symbol())
    except Exception as exc:
        orderflow_advisor = {"error": str(exc), "updated_at": now()}

    write_json(STRATEGY_GENES_FILE, genes)

    state = {
        "version": "0.1",
        "project": "FRIDAY Unified Live Brain",
        "generated_at": now(),
        "rules": DEMO_ONLY_RULES,
        "services": services,
        "brain": {
            "version": brain.get("brain_version"),
            "generated_at": brain.get("generated_at"),
            "jobs": len(brain.get("jobs", []) or []),
            "patches": len(brain.get("patches", []) or []),
            "agent_runs": len(brain.get("agent_runs", []) or []),
            "rules": brain.get("rules", {}),
        },
        "project_map": {
            "generated_at": project_map.get("generated_at"),
            "summary": project_map.get("summary", {}),
        },
        "scalper": scalper,
        "touch_brain": touch,
        "governor": governor,
        "touch_memory": touch_memory,
        "genes": {
            "file": str(STRATEGY_GENES_FILE),
            "global_stats": genes.get("global_stats", {}),
            "top_genes": top_genes(genes, 20),
        },
        "council": council,
        "orderflow_advisor": orderflow_advisor,
        "learning": learning,
        "agents": {
            "active_runs": dispatch.get("active_runs", []),
            "recent_runs": dispatch.get("agent_runs", [])[:40],
            "recent_jobs": dispatch.get("jobs", [])[:20],
            "recent_patches": dispatch.get("patches", [])[:40],
            "accountability": accountability,
        },
        "autopilot": autopilot,
        "logs": {
            "dispatch_tail": read_log_tail(DISPATCH_LOG_DIR, 80),
            "autopilot_tail": read_log_tail(AUTOPILOT_LOG_DIR, 80),
        },
    }

    write_json(STATE_FILE, state)
    return state


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(content=HTML_PAGE)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "friday_live_brain_state",
        "port": 8844,
        "time": now(),
    }


@app.get("/api/state")
def api_state():
    global _STATE_CACHE
    now_ts = time.time()
    cached = _STATE_CACHE
    if cached and now_ts - cached[0] <= _STATE_CACHE_TTL_SECONDS:
        payload = dict(cached[1])
        payload["cached"] = True
        return JSONResponse(make_json_safe(payload))

    if not _STATE_CACHE_LOCK.acquire(blocking=False):
        if cached:
            payload = dict(cached[1])
            payload["cached"] = True
            payload["stale"] = True
            return JSONResponse(make_json_safe(payload))
        return JSONResponse({"ok": False, "error": "state_builder_busy"}, status_code=503)

    try:
        state = build_state()
        state["cached"] = False
        _STATE_CACHE = (time.time(), state)
        return JSONResponse(make_json_safe(state))
    finally:
        _STATE_CACHE_LOCK.release()


@app.get("/api/council")
def api_council():
    state = _STATE_CACHE[1] if _STATE_CACHE else build_state()
    return JSONResponse(make_json_safe(state.get("council", {})))


@app.get("/api/genes")
def api_genes():
    genes = ensure_strategy_genes()
    return JSONResponse(make_json_safe(genes))


HTML_PAGE = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"/>
<title>FRIDAY Unified Live Brain</title>
<style>
  :root{
    --bg:#050b14; --card:#0d1728; --line:#203047; --text:#e5f0ff;
    --muted:#8ea4c5; --green:#22c55e; --red:#ef4444; --yellow:#eab308;
    --blue:#38bdf8; --violet:#8b5cf6; --pink:#ec4899;
  }
  *{box-sizing:border-box}
  body{
    margin:0;
    background:
      radial-gradient(circle at 20% 10%, rgba(56,189,248,.12), transparent 28%),
      radial-gradient(circle at 80% 10%, rgba(139,92,246,.13), transparent 30%),
      radial-gradient(circle at 50% 85%, rgba(34,197,94,.08), transparent 34%),
      var(--bg);
    color:var(--text);
    font-family:Arial, sans-serif;
    overflow:hidden;
  }
  .top{
    height:58px;
    background:rgba(5,11,20,.82);
    border-bottom:1px solid var(--line);
    display:flex;align-items:center;gap:14px;padding:0 16px;
    backdrop-filter: blur(12px);
  }
  .brand{
    font-size:28px;font-weight:900;margin-left:auto;letter-spacing:.5px;
  }
  .muted{color:var(--muted);font-size:12px}
  .layout{
    display:grid;
    grid-template-columns:1.15fr .85fr;
    gap:12px;
    padding:12px;
    height:calc(100vh - 58px);
  }
  .left,.right{display:grid;gap:12px;min-height:0}
  .left{grid-template-rows:1.1fr .9fr}
  .right{grid-template-rows:auto auto 1fr}
  .card{
    position:relative;
    background:linear-gradient(180deg, rgba(13,23,40,.96), rgba(7,17,31,.96));
    border:1px solid var(--line);
    border-radius:18px;
    padding:14px;
    min-height:0;
    overflow:hidden;
    box-shadow:0 14px 30px rgba(0,0,0,.22);
  }
  .card h3{margin:0 0 10px;font-size:19px}
  .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  .stat{
    background:#081321;border:1px solid var(--line);border-radius:14px;padding:10px;
  }
  .stat .label{color:var(--muted);font-size:12px}
  .stat .value{font-size:24px;font-weight:900;margin-top:5px}
  #brainCanvas{
    width:100%;height:100%;display:block;border-radius:14px;background:#030914;border:1px solid var(--line);
  }
  .row{
    display:grid;grid-template-columns:1fr auto auto;gap:10px;
    border-bottom:1px solid rgba(32,48,71,.65);
    padding:8px 4px;font-size:13px;align-items:center;
  }
  .pill{
    border:1px solid var(--line);background:#07111f;border-radius:999px;padding:4px 8px;font-size:11px;font-weight:800;
  }
  .buy{color:var(--green)} .sell{color:var(--red)} .hold{color:var(--yellow)} .block{color:var(--red)}
  pre{
    direction:ltr;text-align:left;white-space:pre-wrap;overflow:auto;height:100%;
    font-family:Consolas,monospace;font-size:12px;line-height:1.5;
    background:#030914;border:1px solid var(--line);border-radius:12px;padding:12px;
  }
  .genes{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;overflow:auto;max-height:100%}
  .gene{background:#07111f;border:1px solid var(--line);border-radius:12px;padding:10px;font-size:12px}
  .gene b{font-size:20px;color:#8fdcff}
  .scroll{overflow:auto;height:100%}
</style>
</head>
<body>
<div class="top">
  <button onclick="refreshState()">تحديث</button>
  <span id="status" class="muted">starting...</span>
  <span class="muted">Unified State Bus • Council • Genes • Accountability</span>
  <div class="brand">FRIDAY UNIFIED LIVE BRAIN</div>
</div>

<div class="layout">
  <div class="left">
    <div class="card">
      <h3>🧠 مجلس العقل الحي</h3>
      <canvas id="brainCanvas"></canvas>
    </div>
    <div class="card">
      <h3>📜 Live Console</h3>
      <pre id="console">loading...</pre>
    </div>
  </div>

  <div class="right">
    <div class="card">
      <h3>⚡ القرار الموحد</h3>
      <div class="grid4">
        <div class="stat"><div class="label">Final Vote</div><div id="finalVote" class="value hold">-</div></div>
        <div class="stat"><div class="label">Confidence</div><div id="confidence" class="value">-</div></div>
        <div class="stat"><div class="label">Genes</div><div id="genesCount" class="value">-</div></div>
        <div class="stat"><div class="label">Services</div><div id="servicesOk" class="value">-</div></div>
      </div>
    </div>

    <div class="card">
      <h3>🧬 أفضل الجينات</h3>
      <div id="genesBox" class="genes"></div>
    </div>

    <div class="card">
      <h3>👥 محاسبة الوكلاء</h3>
      <div id="agentsBox" class="scroll"></div>
    </div>
  </div>
</div>

<script>
let latest = null;

function cls(v){
  const x = String(v || "").toLowerCase();
  if (x === "buy") return "buy";
  if (x === "sell") return "sell";
  if (x === "block") return "block";
  return "hold";
}

function n(x,d=2){
  if(x===null || x===undefined || isNaN(Number(x))) return "-";
  return Number(x).toFixed(d);
}

function esc(x){
  return String(x ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
}

async function refreshState(){
  try{
    const r = await fetch("/api/state");
    latest = await r.json();
    render(latest);
    document.getElementById("status").textContent = "updated " + new Date().toLocaleTimeString();
  }catch(e){
    document.getElementById("status").textContent = "ERROR " + e;
  }
}

function render(s){
  const c = s.council || {};
  const gs = (s.genes || {}).global_stats || {};
  const services = s.services || {};
  const serviceCount = Object.values(services).filter(x=>x.ok).length + "/" + Object.keys(services).length;

  const fv = document.getElementById("finalVote");
  fv.textContent = c.final_vote || "-";
  fv.className = "value " + cls(c.final_vote);

  document.getElementById("confidence").textContent = n(c.confidence,4);
  document.getElementById("genesCount").textContent = gs.genes_count || 0;
  document.getElementById("servicesOk").textContent = serviceCount;

  const genes = ((s.genes || {}).top_genes || []);
  document.getElementById("genesBox").innerHTML = genes.length ? genes.slice(0,10).map(g => `
    <div class="gene">
      <b>${n(g.score,2)}</b>
      boost=${n(g.confidence_boost,3)} seen=${g.seen || 0}<br>
      W/L/N=${g.wins || 0}/${g.losses || 0}/${g.neutral || 0}
      <div class="muted">${esc(String(g.gene_id || "").slice(0,170))}</div>
    </div>
  `).join("") : '<div class="gene">No genes yet</div>';

  const acc = ((s.agents || {}).accountability || {});
  const arr = Object.values(acc).sort((a,b)=>(b.score || 0)-(a.score || 0)).slice(0,20);
  document.getElementById("agentsBox").innerHTML = arr.map(a => `
    <div class="row">
      <div><b>${esc(a.agent)}/${esc(a.role)}</b><br><span class="muted">${esc(a.last_action || "-")}</span></div>
      <div class="pill">score ${n(a.score,2)}</div>
      <div class="pill">R/P ${a.rewards || 0}/${a.punishments || 0}</div>
    </div>
  `).join("");

  const consoleLines = [];
  consoleLines.push("=== COUNCIL ===");
  consoleLines.push(JSON.stringify(c, null, 2));
  consoleLines.push("");
  consoleLines.push("=== SCALPER ===");
  consoleLines.push(JSON.stringify((s.scalper || {}).latest_decision || {}, null, 2));
  consoleLines.push("");
  consoleLines.push("=== TOUCH BRAIN ===");
  consoleLines.push(JSON.stringify((s.touch_brain || {}).latest_plan || {}, null, 2));
  consoleLines.push("");
  consoleLines.push("=== GOVERNOR ===");
  consoleLines.push(JSON.stringify((s.governor || {}).latest_decision || {}, null, 2));
  consoleLines.push("");
  consoleLines.push("=== LEARNING ===");
  consoleLines.push(JSON.stringify(s.learning || {}, null, 2));
  document.getElementById("console").textContent = consoleLines.join("\n");

  drawBrain(s);
}

function drawBrain(s){
  const canvas = document.getElementById("brainCanvas");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = (rect.height - 45) * devicePixelRatio;
  canvas.style.width = rect.width + "px";
  canvas.style.height = (rect.height - 45) + "px";

  const ctx = canvas.getContext("2d");
  ctx.scale(devicePixelRatio, devicePixelRatio);

  const w = rect.width;
  const h = rect.height - 45;
  const t = Date.now()/1000;
  ctx.clearRect(0,0,w,h);

  const center = {x:w/2,y:h/2};

  const votes = ((s.council || {}).votes || []);
  const labels = [
    "Scalper",
    "Touch",
    "Governor",
    "Risk",
    "Genes",
    "Agents",
    "Autopilot",
    "Memory"
  ];

  const radius = Math.min(w,h)*0.34;

  for(let i=0;i<80;i++){
    ctx.fillStyle = "rgba(148,163,184,0.10)";
    ctx.beginPath();
    ctx.arc((i*127.1)%w,(i*73.7)%h,1.2,0,Math.PI*2);
    ctx.fill();
  }

  labels.forEach((label,i)=>{
    const angle = Math.PI*2*i/labels.length + t*0.05;
    const x = center.x + Math.cos(angle)*radius;
    const y = center.y + Math.sin(angle)*radius*0.78;

    const vote = votes.find(v => String(v.name || "").toLowerCase().includes(label.toLowerCase().split(" ")[0]));
    const v = vote ? vote.vote : "HOLD";

    let color = "#eab308";
    if(v==="BUY" || v==="ALLOW") color="#22c55e";
    if(v==="SELL" || v==="BLOCK") color="#ef4444";

    ctx.strokeStyle = "rgba(56,189,248,0.22)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(center.x,center.y);
    ctx.lineTo(x,y);
    ctx.stroke();

    const pulse = 1 + Math.sin(t*4+i)*0.12;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x,y,16*pulse,0,Math.PI*2);
    ctx.fill();

    ctx.fillStyle = "#e5f0ff";
    ctx.font = "bold 12px Arial";
    ctx.textAlign = "center";
    ctx.fillText(label,x,y+34);
    ctx.fillStyle = "#8ea4c5";
    ctx.font = "11px Arial";
    ctx.fillText(v,x,y+48);
  });

  const final = (s.council || {}).final_vote || "HOLD";
  let brainColor = "#eab308";
  if(final==="BUY") brainColor="#22c55e";
  if(final==="SELL" || final==="BLOCK") brainColor="#ef4444";

  ctx.fillStyle = "rgba(56,189,248,0.16)";
  ctx.beginPath();
  ctx.arc(center.x,center.y,82+Math.sin(t*3)*5,0,Math.PI*2);
  ctx.fill();

  ctx.fillStyle = "rgba(139,92,246,0.25)";
  ctx.beginPath();
  ctx.arc(center.x,center.y,58+Math.sin(t*4)*3,0,Math.PI*2);
  ctx.fill();

  ctx.fillStyle = brainColor;
  ctx.beginPath();
  ctx.arc(center.x,center.y,42,0,Math.PI*2);
  ctx.fill();

  ctx.fillStyle = "#fff";
  ctx.font = "bold 20px Arial";
  ctx.textAlign = "center";
  ctx.fillText("FRIDAY",center.x,center.y-5);
  ctx.font = "12px Arial";
  ctx.fillText(final,center.x,center.y+17);
}

refreshState();
setInterval(refreshState, 5000);
</script>
</body>
</html>
"""


def main_loop(interval: int = 2) -> None:
    print("FRIDAY Unified Live Brain State Bus started.")
    print("State:", STATE_FILE)
    print("Genes:", STRATEGY_GENES_FILE)

    while True:
        try:
            state = build_state()
            print(
                f"[{now()}] council={state['council']['final_vote']} "
                f"conf={state['council']['confidence']} "
                f"genes={state['genes']['global_stats'].get('genes_count', 0)}"
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[{now()}] ERROR: {exc}")

        time.sleep(max(1, interval))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=2)
    parser.add_argument("--port", type=int, default=8844)
    args = parser.parse_args()

    if args.serve:
        uvicorn.run(
            "friday_live_brain_state:app",
            host="127.0.0.1",
            port=args.port,
            reload=False,
        )
        return

    if args.loop:
        main_loop(interval=args.interval)
        return

    state = build_state()
    print("Built:", STATE_FILE)
    print("Council:", state["council"])
    print("Genes:", state["genes"]["global_stats"])


if __name__ == "__main__":
    main()
