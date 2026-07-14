"""
friday_mcp_server.py — MCP server for direct Claude control of FRIDAY trading system

Exposes the running FRIDAY brain as tools that Claude can call from any session.

Run standalone:        python friday_mcp_server.py
Register with Claude:  claude mcp add friday -- python "C:\\Users\\Radhi\\MT5\\friday_mcp_server.py"
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT        = Path(r"C:\Users\Radhi\MT5")
MT5_COMMON  = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
BRAIN_STATE = ROOT / "friday_brain_v2_state.json"
KILL_SWITCH = ROOT / "kill_switch.txt"
ORDERS_LOG  = ROOT / "friday_orders.csv"

MAGIC          = 20260600
SYMBOL         = "XAUUSDm"
BRAIN_API      = "http://localhost:5055/api"
OLLAMA_API     = "http://localhost:11434/api"

mcp = FastMCP("friday")

# 🏷️ تلميحات الأدوات: تتيح للمضيف (Claude) التمييز بين القراءة والأفعال المدمِّرة وبوّابتها/تأكيدها.
try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
    _DESTRUCTIVE = ToolAnnotations(destructiveHint=True, openWorldHint=True)
except Exception:                       # نسخة FastMCP لا تدعم التلميحات → لا نكسر الخادم
    _RO = _DESTRUCTIVE = None

def _ann(a):                            # يمرّر التلميح فقط لو مدعوم (آمن عبر النسخ)
    return {"annotations": a} if a is not None else {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _read_state() -> dict:
    if not BRAIN_STATE.exists(): return {}
    try: return json.loads(BRAIN_STATE.read_text(encoding="utf-8"))
    except Exception: return {}


# friday_brain.py (magic 99791) is legacy/display and currently DEAD. When it dies the
# state file freezes but still says live:true — a false "live" that misled monitoring
# (the stale-blindness trap, see memory project_watchdog_silent_death_2026-06-18).
# Report the brain as OFFLINE/STALE when its state file is older than this window.
BRAIN_STALE_AFTER_S = 600


def _brain_age_seconds(state: dict):
    ts = state.get("ts")
    if not ts: return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return None


def _brain_liveness(state: dict) -> dict:
    """Honest brain liveness — never report live:true on a stale/frozen state file.

    `live` is True only when the brain CLAIMS live AND its state is fresh. The raw
    self-reported flag is preserved as `reported_live` for debugging."""
    age = _brain_age_seconds(state)
    reported = bool(state.get("live", False))
    stale = (age is None) or (age > BRAIN_STALE_AFTER_S)
    if stale:
        status = "OFFLINE_STALE" if age is not None else "OFFLINE_NO_STATE"
    else:
        status = "LIVE" if reported else "PAPER"
    return {
        "live": reported and not stale,
        "reported_live": reported,
        "stale": stale,
        "status": status,
        "state_age_seconds": age,
        "stale_threshold_s": BRAIN_STALE_AFTER_S,
    }


def _mt5_init() -> bool:
    if not HAS_MT5: return False
    try: return mt5.initialize()
    except Exception: return False


def _http_get(path: str, timeout: float = 5.0) -> dict:
    try:
        r = requests.get(f"{BRAIN_API}{path}", timeout=timeout)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool(**_ann(_RO))
def friday_status() -> dict:
    """Full snapshot: brain cycle, market, agents, pendings, positions, balance.

    Use this first to see overall system health before any other action."""
    state = _read_state()
    liveness = _brain_liveness(state)

    out: dict[str, Any] = {
        "brain": {
            "cycle":   state.get("cycle", 0),
            "killed":  state.get("killed", False),
            **liveness,   # live (honest), reported_live, stale, status, state_age_seconds, threshold
        },
        "kill_switch_exists": KILL_SWITCH.exists(),
    }

    if _mt5_init():
        info = mt5.account_info()
        tick = mt5.symbol_info_tick(SYMBOL)
        sym  = mt5.symbol_info(SYMBOL)
        pendings = [o for o in (mt5.orders_get(symbol=SYMBOL) or []) if o.magic == MAGIC]
        positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
        types = {2:"BUY_LIMIT",3:"SELL_LIMIT",4:"BUY_STOP",5:"SELL_STOP"}
        out["account"] = {
            "login":          info.login,
            "balance":        info.balance,
            "equity":         info.equity,
            "trade_allowed":  info.trade_allowed,
            "trade_expert":   info.trade_expert,
        }
        out["market"] = {
            "symbol":  SYMBOL,
            "bid":     tick.bid,
            "ask":     tick.ask,
            "spread_points": sym.spread,
        }
        out["pendings"] = [{
            "ticket": o.ticket, "type": types.get(o.type, str(o.type)),
            "price":  o.price_open, "sl": o.sl, "tp": o.tp,
            "volume": o.volume_initial, "comment": o.comment,
            "age_minutes": round((time.time() - o.time_setup) / 60, 1),
        } for o in pendings]
        out["positions"] = [{
            "ticket": p.ticket,
            "side":   "BUY" if p.type == 0 else "SELL",
            "price_open": p.price_open, "sl": p.sl, "tp": p.tp,
            "volume": p.volume, "profit": p.profit,
            "age_minutes": round((time.time() - p.time) / 60, 1),
        } for p in positions]
        mt5.shutdown()

    if state.get("agents"):
        out["agents"] = [{
            "name": a["name"],
            "emoji": a["emoji"],
            "stance":     a.get("last", {}).get("stance"),
            "confidence": a.get("last", {}).get("confidence"),
            "veto":       a.get("last", {}).get("veto"),
            "say":        a.get("last", {}).get("say", "")[:120],
        } for a in state["agents"]]

    if state.get("coordinator", {}).get("last_decision"):
        out["last_decision"] = state["coordinator"]["last_decision"]

    if state.get("momentum"):
        out["momentum"] = state["momentum"]

    out["recent_scalps"] = state.get("scalps", [])[-5:]
    out["pm_events"]     = state.get("pm_events", [])[:8]

    return out


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_kill(reason: str = "manual") -> dict:
    """Emergency stop — creates kill_switch.txt so brain + EA halt trading immediately.

    Use when you want to stop all new orders. Existing positions stay open but unmanaged."""
    KILL_SWITCH.write_text(f"killed by MCP at {datetime.now().isoformat()}\nreason: {reason}",
                           encoding="utf-8")
    return {"ok": True, "killed_at": datetime.now().isoformat(), "reason": reason,
            "note": "Remove kill_switch.txt to resume."}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_resume() -> dict:
    """Remove the kill switch — brain and EA resume normal operation."""
    if KILL_SWITCH.exists():
        KILL_SWITCH.unlink()
        return {"ok": True, "resumed_at": datetime.now().isoformat()}
    return {"ok": False, "msg": "kill switch was not active"}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_set_mode(live: bool) -> dict:
    """Switch the brain between LIVE (real trades) and PAPER (dry-run).

    Args:
        live: True for real trading, False for paper/dry-run.

    Stops current brain process and restarts with the chosen flag."""
    # Stop existing
    subprocess.run([
        "powershell", "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*friday_brain.py*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    ], capture_output=True)
    time.sleep(2)

    args = ["python", str(ROOT / "friday_brain.py")]
    if live: args.append("--live")
    subprocess.Popen(args, cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
    return {"ok": True, "mode": "LIVE" if live else "PAPER",
            "msg": "brain restarted; first cycle in ~10-15s"}


@mcp.tool()
def friday_chat(agent: str, message: str) -> dict:
    """Chat with a FRIDAY agent and get its response with full market context.

    Args:
        agent: One of HUNTER, STRUCTURE, MOMENTUM, RISK, CHARTIST, COORDINATOR, ALL.
        message: Your question in Arabic or English.
    """
    try:
        r = requests.post(f"{BRAIN_API}/chat", json={"agent": agent.upper(), "message": message},
                         timeout=90)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_cancel_order(ticket: int) -> dict:
    """Cancel a specific pending order by ticket. Returns success/failure."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
    r = mt5.order_send(req)
    mt5.shutdown()
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "ticket": ticket, "msg": "cancelled"}
    return {"ok": False, "ticket": ticket,
            "error": f"retcode={r.retcode if r else 'None'} {r.comment if r else ''}"}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_cancel_all_pendings() -> dict:
    """Cancel ALL Brain pending orders (magic 20260600 only). Open positions stay."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    cancelled, failed = [], []
    pendings = [o for o in (mt5.orders_get(symbol=SYMBOL) or []) if o.magic == MAGIC]
    for o in pendings:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            cancelled.append(o.ticket)
        else:
            failed.append({"ticket": o.ticket, "retcode": r.retcode if r else None})
    mt5.shutdown()
    return {"ok": True, "cancelled": cancelled, "failed": failed,
            "total_before": len(pendings)}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_close_position(ticket: int) -> dict:
    """Close an open position at market. Use when an agent or you want to exit early."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        mt5.shutdown()
        return {"ok": False, "error": "position not found"}
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    price = tick.bid if p.type == 0 else tick.ask
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "position":     int(ticket),
        "symbol":       SYMBOL,
        "volume":       p.volume,
        "type":         close_type,
        "price":        float(price),
        "deviation":    50,
        "magic":        MAGIC,
        "comment":      "FRIDAY mcp_close",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    mt5.shutdown()
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "ticket": ticket, "closed_at": price, "msg": "closed"}
    return {"ok": False, "ticket": ticket,
            "error": f"retcode={r.retcode if r else 'None'}"}


@mcp.tool(**_ann(_RO))
def friday_history(hours: int = 24) -> dict:
    """Recent trade deals on XAUUSDm, grouped by magic to spot rogue EAs.

    Args:
        hours: Lookback window (default 24)."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    deals = mt5.history_deals_get(datetime.now() - timedelta(hours=hours), datetime.now()) or []
    xau = [d for d in deals if d.symbol == SYMBOL]
    from collections import defaultdict
    by_magic: dict[int, list] = defaultdict(list)
    for d in xau: by_magic[d.magic].append(d)
    mt5.shutdown()
    return {
        "hours": hours, "total_deals": len(xau),
        "by_magic": {
            str(magic): {
                "count":     len(ds),
                "is_brain":  magic == MAGIC,
                "buys":      sum(1 for d in ds if d.type == 0),
                "sells":     sum(1 for d in ds if d.type == 1),
                "total_pl":  round(sum(d.profit for d in ds), 2),
            } for magic, ds in by_magic.items()
        },
        "latest_5": [{
            "time":   datetime.fromtimestamp(d.time).strftime("%H:%M:%S"),
            "ticket": d.ticket,
            "side":   "BUY" if d.type == 0 else "SELL",
            "entry":  ["IN","OUT","INOUT","OUT_BY"][d.entry] if d.entry < 4 else "?",
            "price":  d.price, "profit": d.profit, "magic": d.magic,
        } for d in xau[-5:]],
    }


@mcp.tool(**_ann(_RO))
def friday_brain_health() -> dict:
    """Diagnose: brain process, ollama, EA data freshness."""
    state = _read_state()
    liveness = _brain_liveness(state)
    state_age = liveness["state_age_seconds"]

    # Process check
    ps = subprocess.run(
        ["powershell", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'friday_brain|brain_server|smc_dashboard' } | "
         "Select-Object ProcessId, @{n='cmd';e={$_.CommandLine}} | ConvertTo-Json"
        ], capture_output=True, text=True, timeout=10)
    procs = []
    try:
        if ps.stdout.strip():
            data = json.loads(ps.stdout)
            procs = data if isinstance(data, list) else [data]
    except Exception: pass

    # Ollama
    ollama_ok = False
    try:
        r = requests.get(f"{OLLAMA_API}/tags", timeout=3); ollama_ok = (r.status_code == 200)
    except Exception: pass

    # Brain server
    bs_ok = False
    try:
        r = requests.get("http://localhost:5055/api/swarm", timeout=3)
        bs_ok = (r.status_code == 200)
    except Exception: pass

    # EA freshness
    ea_status = MT5_COMMON / "ea_realtime_status.json"
    ea_age = None
    if ea_status.exists():
        ea_age = (datetime.now() - datetime.fromtimestamp(ea_status.stat().st_mtime)).total_seconds()

    return {
        "brain_state_age_s": state_age,
        "brain_cycle":       state.get("cycle"),
        "brain_live":        liveness["live"],          # honest: False when stale
        "brain_reported_live": liveness["reported_live"],  # what the frozen file claims
        "brain_stale":       liveness["stale"],
        "brain_status":      liveness["status"],
        "ollama_running":    ollama_ok,
        "brain_server_5055": bs_ok,
        "ea_status_age_s":   ea_age,
        "ea_broadcasting":   ea_age is not None and ea_age < 30,
        "processes":         [{"pid": p.get("ProcessId"), "cmd": (p.get("cmd") or "")[:90]}
                              for p in procs],
        "kill_switch":       KILL_SWITCH.exists(),
    }


@mcp.tool(**_ann(_RO))
def friday_recent_orders(limit: int = 15) -> list[dict]:
    """Last N entries from friday_orders.csv showing brain's order attempts (LIVE/SKIP/REJECT/SCALP)."""
    if not ORDERS_LOG.exists(): return []
    rows = ORDERS_LOG.read_text(encoding="utf-8").strip().split("\n")[-limit:]
    out = []
    for r in rows:
        parts = r.split(",", 8)
        if len(parts) < 8 or parts[0] == "ts": continue
        out.append({
            "ts": parts[0], "kind": parts[1], "side": parts[2],
            "price": parts[3], "sl": parts[4], "tp": parts[5],
            "lot": parts[6], "reason": parts[7][:60], "note": parts[8] if len(parts) > 8 else "",
        })
    return out


@mcp.tool()
def friday_dialogue(n: int = 15) -> list[dict]:
    """Latest agent dialogue messages from the brain's bus.

    Use to see what each agent has been saying."""
    state = _read_state()
    msgs = state.get("dialogue", [])[-n:]
    out = []
    for m in msgs:
        c = m.get("content", {})
        out.append({
            "ts": m["ts"], "sender": m["sender"], "topic": m["topic"],
            "say": c.get("say", ""), "stance": c.get("stance"),
            "confidence": c.get("confidence"), "veto": c.get("veto"),
            "final_action": c.get("final_action"),
            "side": c.get("side"), "entry": c.get("entry"),
            "sl": c.get("sl"), "tp": c.get("tp"),
            "reason": c.get("reason", "")[:100],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────
# AGENT TEAM tools — delegate work to specialist Claude clones
# ─────────────────────────────────────────────────────────────────────────

VALID_ROLES = ["STRATEGIST", "CODER", "RESEARCHER", "DEBUGGER", "DESIGNER"]
TASKS_FILE  = ROOT / "friday_tasks.json"
TEAM_STATE  = ROOT / "friday_agent_team_state.json"
TEAM_LOG    = ROOT / "friday_agent_team_log.csv"


@mcp.tool()
def friday_delegate(role: str, task: str, priority: int = 5) -> dict:
    """Send a task to one of FRIDAY's 5 specialist Claude clones running on the user's machine.

    Args:
        role: STRATEGIST | CODER | RESEARCHER | DEBUGGER | DESIGNER
        task: Clear description of what you want done (Arabic or English).
        priority: 1 (low) to 9 (urgent). Default 5.

    The agent has the full FRIDAY context + tool access and will execute
    end-to-end, writing its result to friday_agent_team_output/<task_id>/SUMMARY.md.
    """
    import uuid
    role_u = role.upper().strip()
    if role_u not in VALID_ROLES:
        return {"ok": False, "error": f"role must be one of {VALID_ROLES}"}
    if not task.strip():
        return {"ok": False, "error": "empty task"}

    task_id = uuid.uuid4().hex[:8]
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text('{"tasks": []}', encoding="utf-8")
    q = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    q["tasks"].append({
        "id":           task_id,
        "role":         role_u,
        "task":         task,
        "priority":     int(priority),
        "status":       "pending",
        "submitted_at": datetime.now().isoformat(),
        "started_at":   None,
        "finished_at":  None,
        "result":       None,
        "requested_by": "mcp",
    })
    TASKS_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "task_id": task_id, "role": role_u,
            "msg": f"Task {task_id} submitted. Watch with friday_task_status('{task_id}')"}


@mcp.tool()
def friday_team_status() -> dict:
    """Show agent team daemon health: active workers, queue counts, recent tasks."""
    if not TEAM_STATE.exists():
        return {"running": False, "reason": "friday_agent_team.py not running"}
    state = _read_json(TEAM_STATE)
    age = None
    try:
        age = (datetime.now() - datetime.fromisoformat(state["ts"])).total_seconds()
    except: pass
    state["age_s"] = age
    state["running"] = age is not None and age < 30
    return state


def _read_json(p: Path) -> dict:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


@mcp.tool()
def friday_task_status(task_id: str) -> dict:
    """Get full details of a single delegated task by ID."""
    if not TASKS_FILE.exists():
        return {"error": "no tasks queue"}
    q = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    for t in q["tasks"]:
        if t["id"] == task_id:
            # Try to read SUMMARY.md if produced
            summary_path = ROOT / "friday_agent_team_output" / task_id / "SUMMARY.md"
            if summary_path.exists():
                t["summary"] = summary_path.read_text(encoding="utf-8")[:3000]
            return t
    return {"error": f"task {task_id} not found"}


@mcp.tool()
def friday_task_list(limit: int = 20, role: str | None = None,
                     status: str | None = None) -> list[dict]:
    """List recent delegated tasks. Optional filter by role or status."""
    if not TASKS_FILE.exists():
        return []
    q = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    tasks = q.get("tasks", [])
    if role:
        tasks = [t for t in tasks if t["role"] == role.upper()]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return tasks[-limit:]


@mcp.tool()
def friday_team_log(limit: int = 20) -> list[dict]:
    """Recent completion log (CSV) from the agent team."""
    if not TEAM_LOG.exists():
        return []
    lines = TEAM_LOG.read_text(encoding="utf-8").strip().split("\n")[1:]  # skip header
    out = []
    for line in lines[-limit:]:
        parts = line.split(",", 6)
        if len(parts) >= 7:
            out.append({
                "ts": parts[0], "role": parts[1], "task_id": parts[2],
                "task_brief": parts[3].strip('"'),
                "status": parts[4], "duration_s": parts[5],
                "result": parts[6].strip('"'),
            })
    return out


# ─────────────────────────────────────────────────────────────────────────
# RAW MT5 PRIMITIVES (طلب المستخدم: place/modify/close/OHLCV/specs/ticks) — محكومة:
# DEMO فقط · فحص طوارئ مدير المخاطر · لوت أدنى · المستخدم هو من يستدعي الأداة.
# ─────────────────────────────────────────────────────────────────────────
MAGIC_MCP = 20260615          # أوامر تُوضع عبر MCP (تمييزها في MT5)
_TF_MAP = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388,
           "D1": 16408, "W1": 32769}


def _is_demo() -> bool:
    """True لحساب غير حقيقي. ملاحظة حرجة: خوادم Exness Trial تُبلّغ trade_mode=0 (REAL) خطأً —
    لذا نعدّه تجريبياً أيضاً لو اسم الخادم يحوي Trial/Demo. يبقى يرفض خادم Real الحقيقي."""
    try:
        a = mt5.account_info()
        if not a:
            return False
        if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            return True
        srv = (a.server or "").lower()
        return ("trial" in srv or "demo" in srv) and "real" not in srv
    except Exception:
        return False


def _risk_blocks() -> str | None:
    """يمنع الدخول الجديد لو مدير المخاطر أعلن طوارئ (توحيد الحوكمة)."""
    try:
        d = json.loads((ROOT / "data" / "r_native" / "risk_register.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) < 300 and d.get("emergency"):
            return "risk_manager EMERGENCY active — new orders blocked"
    except Exception:
        pass
    return None


@mcp.tool(**_ann(_RO))
def friday_symbol_info(symbol: str = SYMBOL) -> dict:
    """Symbol specs: digits, point, min/max/step volume, spread, contract size, bid/ask."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    mt5.symbol_select(symbol, True)
    i = mt5.symbol_info(symbol); t = mt5.symbol_info_tick(symbol)
    mt5.shutdown()
    if not i:
        return {"ok": False, "error": f"unknown symbol {symbol}"}
    return {"ok": True, "symbol": symbol, "digits": i.digits, "point": i.point,
            "volume_min": i.volume_min, "volume_max": i.volume_max, "volume_step": i.volume_step,
            "spread": i.spread, "contract_size": i.trade_contract_size,
            "bid": getattr(t, "bid", None), "ask": getattr(t, "ask", None),
            "trade_allowed": i.trade_mode != 0}


@mcp.tool(**_ann(_RO))
def friday_market_data(symbol: str = SYMBOL, timeframe: str = "M15", count: int = 50) -> dict:
    """OHLCV candles. timeframe ∈ M1/M5/M15/M30/H1/H4/D1/W1. Returns recent `count` bars."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    tf = _TF_MAP.get(timeframe.upper(), 15)
    mt5.symbol_select(symbol, True)
    r = mt5.copy_rates_from_pos(symbol, tf, 0, min(int(count), 500))
    mt5.shutdown()
    if r is None or len(r) == 0:
        return {"ok": False, "error": "no data"}
    bars = [{"t": int(x["time"]), "o": float(x["open"]), "h": float(x["high"]),
             "l": float(x["low"]), "c": float(x["close"]), "v": int(x["tick_volume"]),
             "spread": int(x["spread"])} for x in r]
    return {"ok": True, "symbol": symbol, "timeframe": timeframe.upper(), "bars": bars}


@mcp.tool(**_ann(_RO))
def friday_ticks(symbol: str = SYMBOL, count: int = 50) -> dict:
    """Recent tick snapshot (bid/ask/spread). Request/response form of tick streaming.
    For continuous streaming use the tick_ws.py WebSocket daemon on ws://127.0.0.1:8765."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    mt5.symbol_select(symbol, True)
    ticks = mt5.copy_ticks_from(symbol, int(time.time()) - 300, min(int(count), 500),
                                mt5.COPY_TICKS_ALL)
    mt5.shutdown()
    if ticks is None or len(ticks) == 0:
        return {"ok": False, "error": "no ticks"}
    out = [{"t": int(x["time"]), "bid": float(x["bid"]), "ask": float(x["ask"]),
            "spread": round(float(x["ask"]) - float(x["bid"]), 6)} for x in ticks[-int(count):]]
    return {"ok": True, "symbol": symbol, "ticks": out}


@mcp.tool(**_ann(_RO))
def friday_order_check(symbol: str, side: str, volume: float,
                       sl: float = 0.0, tp: float = 0.0) -> dict:
    """DRY-RUN a market order via mt5.order_check() WITHOUT sending it (read-only, places nothing).
    Returns margin_required, free_margin_after, expected price and retcode/comment so you can verify
    a trade is fundable and valid BEFORE friday_place_order. The video's #1 pre-trade safety primitive."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    side = side.lower()
    if side not in ("buy", "sell"):
        mt5.shutdown(); return {"ok": False, "error": "side must be 'buy' or 'sell'"}
    mt5.symbol_select(symbol, True)
    i = mt5.symbol_info(symbol); t = mt5.symbol_info_tick(symbol)
    if not i or not t:
        mt5.shutdown(); return {"ok": False, "error": f"unknown symbol {symbol}"}
    vol = max(i.volume_min, round(round(float(volume) / i.volume_step) * i.volume_step, 2))
    otype = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = t.ask if side == "buy" else t.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(vol),
           "type": otype, "price": float(price), "sl": float(sl), "tp": float(tp),
           "deviation": 50, "magic": MAGIC_MCP, "type_filling": mt5.ORDER_FILLING_IOC}
    chk = mt5.order_check(req)
    mt5.shutdown()
    if not chk:
        return {"ok": False, "error": "order_check returned None"}
    return {"ok": True, "valid": chk.retcode == 0, "retcode": chk.retcode, "comment": chk.comment,
            "symbol": symbol, "side": side, "volume": vol, "price": price,
            "margin_required": getattr(chk, "margin", None),
            "free_margin_after": getattr(chk, "margin_free", None),
            "equity_after": getattr(chk, "equity", None),
            "balance": getattr(chk, "balance", None),
            "margin_level_after": getattr(chk, "margin_level", None)}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_place_order(symbol: str, side: str, volume: float,
                       sl: float = 0.0, tp: float = 0.0, comment: str = "mcp") -> dict:
    """Place a MARKET order (DEMO only). side='buy'|'sell', volume in lots, optional sl/tp prices.
    GOVERNED: refuses on live accounts and on risk_manager EMERGENCY; clamps to min/step volume.
    User-invoked control — the user pulls the trigger, not autonomous."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    if not _is_demo():
        mt5.shutdown()
        return {"ok": False, "error": "REFUSED: account is not DEMO — live order placement disabled"}
    block = _risk_blocks()
    if block:
        mt5.shutdown()
        return {"ok": False, "error": f"REFUSED: {block}"}
    side = side.lower()
    if side not in ("buy", "sell"):
        mt5.shutdown(); return {"ok": False, "error": "side must be 'buy' or 'sell'"}
    mt5.symbol_select(symbol, True)
    i = mt5.symbol_info(symbol); t = mt5.symbol_info_tick(symbol)
    if not i or not t:
        mt5.shutdown(); return {"ok": False, "error": f"unknown symbol {symbol}"}
    vol = max(i.volume_min, round(round(float(volume) / i.volume_step) * i.volume_step, 2))
    otype = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = t.ask if side == "buy" else t.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(vol),
           "type": otype, "price": float(price), "sl": float(sl), "tp": float(tp),
           "deviation": 50, "magic": MAGIC_MCP, "comment": f"MCP {comment}"[:28],
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    mt5.shutdown()
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "ticket": r.order, "symbol": symbol, "side": side,
                "volume": vol, "price": price, "magic": MAGIC_MCP}
    return {"ok": False, "error": f"retcode={r.retcode if r else 'None'} {getattr(r,'comment','')}"}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_modify_sltp(ticket: int, sl: float = 0.0, tp: float = 0.0) -> dict:
    """Modify an open position's stop-loss / take-profit by ticket. Pass 0 to leave a field unchanged."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    pos = mt5.positions_get(ticket=int(ticket))
    if not pos:
        mt5.shutdown(); return {"ok": False, "error": "position not found"}
    p = pos[0]
    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": int(ticket),
           "sl": float(sl) if sl else p.sl, "tp": float(tp) if tp else p.tp}
    r = mt5.order_send(req)
    mt5.shutdown()
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "ticket": int(ticket), "sl": req["sl"], "tp": req["tp"]}
    return {"ok": False, "error": f"retcode={r.retcode if r else 'None'}"}


@mcp.tool(**_ann(_DESTRUCTIVE))
def friday_close_symbol(symbol: str, which: str = "all", confirm: bool = False,
                        include_manual: bool = False) -> dict:
    """Close positions for a symbol. which='all'|'profit'|'loss'.
    SAFETY (the 'zero my book' hole): with confirm=False this only PREVIEWS — returns the tickets
    and est P&L it WOULD close, sends nothing. Pass confirm=True to actually close.
    Manual trades (magic 0) are PROTECTED and never closed unless include_manual=True (hard user rule).
    DEMO accounts only."""
    if not _mt5_init():
        return {"ok": False, "error": "MT5 not available"}
    if not _is_demo():
        mt5.shutdown()
        return {"ok": False, "error": "REFUSED: account is not DEMO — close disabled"}
    pos = [p for p in (mt5.positions_get(symbol=symbol) or [])]
    if not include_manual:
        pos = [p for p in pos if p.magic != 0]      # احمِ اليدوي (magic 0) دائماً — قاعدة صارمة
    if which == "profit":
        pos = [p for p in pos if p.profit > 0]
    elif which == "loss":
        pos = [p for p in pos if p.profit < 0]
    if not confirm:
        mt5.shutdown()
        return {"ok": False, "preview": True, "error": "REFUSED: pass confirm=True to close",
                "would_close": len(pos), "tickets": [int(p.ticket) for p in pos],
                "est_pnl": round(sum(p.profit + p.swap for p in pos), 2),
                "manual_protected": not include_manual, "filter": which}
    closed, errs = 0, 0
    for p in pos:
        t = mt5.symbol_info_tick(p.symbol); ib = p.type == 0
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket,
                            "symbol": p.symbol, "volume": p.volume,
                            "type": mt5.ORDER_TYPE_SELL if ib else mt5.ORDER_TYPE_BUY,
                            "price": t.bid if ib else t.ask, "deviation": 50,
                            "magic": p.magic, "comment": "MCP close",
                            "type_filling": mt5.ORDER_FILLING_IOC})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
        else:
            errs += 1
    mt5.shutdown()
    return {"ok": True, "symbol": symbol, "closed": closed, "failed": errs, "filter": which}


@mcp.resource("friday://state")
def state_resource() -> str:
    """Full brain state JSON as a resource."""
    return json.dumps(_read_state(), ensure_ascii=False, indent=2)


@mcp.resource("friday://orders-log")
def orders_log_resource() -> str:
    """Full order log."""
    if ORDERS_LOG.exists():
        return ORDERS_LOG.read_text(encoding="utf-8")
    return "(no orders log)"


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
