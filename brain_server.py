"""
brain_server.py — FRIDAY Brain Web Server
http://localhost:5055

يعرض لوحة التحكم الكاملة في المتصفح:
  - الوكلاء المحليون (السرب) — يتحدث كل ثانيتين
  - جلسات الوكلاء الذكيين (Claude AI)
  - بيانات السوق الحية
  - vault hot cache

تشغيل:
    python brain_server.py
    ثم افتح: http://localhost:5055
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import urllib.request
import urllib.error

import requests
from flask import Flask, Response, jsonify, redirect, request, send_from_directory

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
    if not mt5.initialize():
        print(f"[warn] MT5 init failed: {mt5.last_error()}")
        HAS_MT5 = False
    else:
        print(f"[mt5] initialized in brain_server")
except ImportError:
    HAS_MT5 = False
    print("[warn] MetaTrader5 not available")

# DOM subscription state (one-time setup)
_dom_subscribed = set()
_dom_lock = threading.Lock()


def _ensure_dom_subscribed(symbol: str) -> bool:
    """Subscribe to DOM updates once per symbol. Returns True if broker supports it."""
    if not HAS_MT5: return False
    with _dom_lock:
        if symbol in _dom_subscribed:
            return True
        # Make sure symbol is in market watch
        mt5.symbol_select(symbol, True)
        ok = mt5.market_book_add(symbol)
        if ok:
            _dom_subscribed.add(symbol)
            print(f"[dom] subscribed to {symbol}")
            return True
        return False

# ── Paths ──────────────────────────────────────────────────────────────────────
MT5_ROOT     = Path(r"C:\Users\Radhi\MT5")
VAULT        = Path(r"C:\Users\Radhi\MT5\plutobrain")
MT5_DATA     = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
DASHBOARD    = MT5_ROOT / "dashboard"
BRIDGE_STATE = MT5_ROOT / "friday_bridge_state.json"
CONTROL_CSV  = MT5_DATA / "claude_live_control.csv"
BRAIN_V2       = MT5_ROOT / "friday_brain_v2_state.json"
LEVELS_FILE    = MT5_ROOT / "friday_levels.json"
BUS_FILE       = MT5_ROOT / "friday_bus.json"
FOOTPRINT_FILE  = MT5_ROOT / "friday_footprint.json"
BINANCE_DOM     = MT5_ROOT / "friday_binance_dom.json"
TEAM_STATE      = MT5_ROOT / "friday_agent_team_state.json"
FRACTALS_FILE   = MT5_ROOT / "friday_fractals.json"
EA_EVOLVER_STATE = MT5_ROOT / "ea_evolver_state.json"
EA_EVOLUTION_LOG = MT5_ROOT / "ea_evolution.csv"
V3_STATE         = MT5_ROOT / "friday_v3" / "data" / "v3_state.json"
V3_TRADES        = MT5_ROOT / "friday_v3" / "data" / "v3_trades.csv"
V3_GENE_POOL     = MT5_ROOT / "friday_v3" / "data" / "gene_pool.json"
V3_BACKTEST      = MT5_ROOT / "friday_v3" / "data" / "backtest_report.json"
V3_MINER         = MT5_ROOT / "friday_v3" / "data" / "miner_rules.json"

app = Flask(__name__, static_folder=str(DASHBOARD))


# ── Readers ────────────────────────────────────────────────────────────────────

def _json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _text(p: Path, limit: int = 800) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit]
    except Exception:
        return ""


# ── Convert swarm → agents_state format ───────────────────────────────────────

ROLE_COLORS = {
    "محلل الفجوة":         "#f59e0b",
    "قارئ السوق":          "#22d3ee",
    "حارس المخاطر":        "#ef4444",
    "مطور الجينات":        "#a78bfa",
    "مبتكر الاستراتيجيات": "#34d399",
    "محلل الكود":          "#fb923c",
    "المنسق الرئيسي":      "#ffffff",
}


def swarm_to_state(swarm: dict) -> dict:
    """Convert friday_agents.json → agents_state.json format."""
    agents = []
    feed   = []
    score  = swarm.get("total_score", 0)

    for a in swarm.get("agents", []):
        role  = a.get("role", "?")
        conf  = a.get("confidence", 0)
        dec   = a.get("decision", "—")
        thought = a.get("thought", "")

        agents.append({
            "id":           a.get("name", role),
            "name":         f"{a.get('emoji','')} {role}",
            "group":        "specialist",
            "role":         dec,
            "status":       "active" if a.get("status") == "نشط" else "idle",
            "activity":     min(conf / 100, 1.0),
            "tasks_done":   a.get("decisions_count", 0),
            "current_task": thought[:90] if thought else dec,
            "platform":     "FRIDAY-Swarm",
            "color":        ROLE_COLORS.get(role, "#64748b"),
            "confidence":   conf,
            "decision":     dec,
            "params":       a.get("params", {}),
            "last_update":  a.get("last_update", ""),
        })

        if dec and dec != "—":
            feed.insert(0, {
                "ts":    a.get("last_update", ""),
                "agent": f"{a.get('emoji','')} {role}",
                "text":  f"{dec} ({conf}%) — {thought[:60]}",
                "level": "alert" if conf >= 85 else "info",
                "color": ROLE_COLORS.get(role, "#64748b"),
            })

    # Add coordinator
    coord = swarm.get("coordinator", {})
    if coord:
        role = "المنسق الرئيسي"
        agents.append({
            "id":           "coordinator",
            "name":         f"🤖 {role}",
            "group":        "primary",
            "role":         coord.get("decision", "—"),
            "status":       "active",
            "activity":     min(coord.get("confidence", 0) / 100, 1.0),
            "tasks_done":   coord.get("decisions_count", 0),
            "current_task": coord.get("thought", "")[:90],
            "platform":     "FRIDAY-Swarm",
            "color":        "#ffffff",
            "confidence":   coord.get("confidence", 0),
            "decision":     coord.get("decision", "—"),
        })

    return {
        "last_updated": swarm.get("timestamp", datetime.now().isoformat()),
        "session_id":   "friday-live",
        "total_score":  score,
        "agents":       agents,
        "feed":         feed[:30],
        "alerts":       swarm.get("alerts", []),
    }


# ── Background updater: writes agents_state.json every 3s ─────────────────────

def _updater():
    state_file = DASHBOARD / "agents_state.json"
    while True:
        try:
            for p in [MT5_DATA / "friday_agents.json", MT5_ROOT / "friday_agents.json"]:
                if p.exists():
                    swarm = _json(p)
                    if swarm:
                        state = swarm_to_state(swarm)
                        state_file.write_text(
                            json.dumps(state, ensure_ascii=False, indent=2),
                            encoding="utf-8"
                        )
                    break
        except Exception:
            pass
        time.sleep(3)


threading.Thread(target=_updater, daemon=True).start()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Professional unified dashboard — TradingView chart + LLM brain + agents."""
    return send_from_directory(str(DASHBOARD), "friday_pro.html")


@app.route("/v1")
def index_v1():
    """Previous compact dashboard."""
    return send_from_directory(str(DASHBOARD), "friday_unified.html")


@app.route("/old")
def index_old():
    """Legacy command center."""
    return send_from_directory(str(DASHBOARD), "agents_command_center.html")


@app.route("/dashboard/<path:filename>")
def dashboard_static(filename):
    return send_from_directory(str(DASHBOARD), filename)


# ── SMC Dashboard bridge (port 5050) ──────────────────────────────────────────

SMC_BASE = "http://127.0.0.1:5050"  # use IP to skip IPv6 probe on Windows (saves ~2s per call)


def _proxy_get(url: str, timeout: float = 3.0) -> tuple[dict | list, int]:
    """Fetch JSON from another local server; returns (data, status)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), 200
    except urllib.error.URLError:
        return {"error": "smc_dashboard not running on :5050"}, 503
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/smc/status")
def api_smc_status():
    data, code = _proxy_get(f"{SMC_BASE}/api/status")
    return jsonify(data), code


@app.route("/api/smc/decisions")
def api_smc_decisions():
    data, code = _proxy_get(f"{SMC_BASE}/api/decisions")
    return jsonify(data), code


@app.route("/api/smc/agents")
def api_smc_agents():
    data, code = _proxy_get(f"{SMC_BASE}/api/agents")
    return jsonify(data), code


@app.route("/api/smc/brain")
def api_smc_brain():
    data, code = _proxy_get(f"{SMC_BASE}/api/brain")
    return jsonify(data), code


@app.route("/smc")
def smc_redirect():
    """Quick link from the new dashboard to the legacy SMC one."""
    return redirect(SMC_BASE, code=302)


@app.route("/api/brain")
def api_brain():
    """LLM-powered brain (friday_brain.py) full state."""
    return jsonify(_json(BRAIN_V2, {"status": "brain v2 not running"}))


@app.route("/api/footprint")
def api_footprint():
    """Tick-by-tick footprint: per-bar price levels, buy/sell, delta, POC, imbalances."""
    return jsonify(_json(FOOTPRINT_FILE, {"status": "footprint engine not running"}))


@app.route("/api/fractals")
def api_fractals():
    """Bill Williams fractals + market direction (built by CODER agent)."""
    return jsonify(_json(FRACTALS_FILE, {"status": "friday_fractals.py not running"}))


@app.route("/api/v3")
def api_v3():
    """FRIDAY v3 Genetic Dip Buyer — pool state + recent trades + miner rules."""
    state = _json(V3_STATE, {})
    pool  = _json(V3_GENE_POOL, {})
    backtest = _json(V3_BACKTEST, {})
    miner = _json(V3_MINER, {})
    # Recent trades CSV (last 20)
    trades = []
    if V3_TRADES.exists():
        try:
            lines = V3_TRADES.read_text(encoding="utf-8").strip().split("\n")
            if len(lines) > 1:
                headers = lines[0].split(",")
                for line in lines[-20:]:
                    parts = line.split(",")
                    if len(parts) == len(headers):
                        trades.append(dict(zip(headers, parts)))
        except Exception: pass
    return jsonify({
        "state":    state,
        "pool":     pool,
        "trades":   trades,
        "backtest": backtest,
        "miner":    miner,
    })


@app.route("/api/memory")
def api_memory():
    """Brain learning memory — win rates, kelly multiplier, daily P/L, halts."""
    try:
        import sys as _sys
        if str(MT5_ROOT) not in _sys.path: _sys.path.insert(0, str(MT5_ROOT))
        import friday_memory as fm
        return jsonify(fm.stats())
    except Exception as e:
        return jsonify({"error": str(e)})


_regime_cache = {"ts": 0, "data": {}}
_regime_lock  = threading.Lock()

@app.route("/api/regime")
def api_regime():
    """Current market regime (cached 5s to avoid MT5 contention)."""
    with _regime_lock:
        now = time.time()
        if (now - _regime_cache["ts"]) < 5 and _regime_cache["data"]:
            return jsonify(_regime_cache["data"])
        try:
            import sys as _sys
            if str(MT5_ROOT) not in _sys.path: _sys.path.insert(0, str(MT5_ROOT))
            import friday_regime as fr
            data = fr.classify_regime()
            _regime_cache["ts"] = now
            _regime_cache["data"] = data
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)})


# ── Team chat (specialist Claude clones — STRATEGIST, CODER, etc.) ──

VALID_TEAM_ROLES = ["STRATEGIST", "CODER", "RESEARCHER", "DEBUGGER", "DESIGNER"]
TASKS_QUEUE      = MT5_ROOT / "friday_tasks.json"
TEAM_OUTPUT_DIR  = MT5_ROOT / "friday_agent_team_output"


@app.route("/api/team/submit", methods=["POST"])
def api_team_submit():
    """Submit a task to one of the 5 specialist Claude clones.
       body: { role, task, priority=5 }"""
    import uuid
    data = request.get_json(force=True) or {}
    role  = (data.get("role") or "").upper().strip()
    task  = (data.get("task") or "").strip()
    pri   = int(data.get("priority", 5))
    if role not in VALID_TEAM_ROLES:
        return jsonify({"ok": False, "error": f"role must be one of {VALID_TEAM_ROLES}"}), 400
    if not task:
        return jsonify({"ok": False, "error": "empty task"}), 400

    task_id = uuid.uuid4().hex[:8]
    if not TASKS_QUEUE.exists():
        TASKS_QUEUE.write_text('{"tasks": []}', encoding="utf-8")
    q = json.loads(TASKS_QUEUE.read_text(encoding="utf-8"))
    q["tasks"].append({
        "id":           task_id, "role": role, "task": task, "priority": pri,
        "status":       "pending",
        "submitted_at": datetime.now().isoformat(),
        "started_at":   None, "finished_at": None, "result": None,
        "requested_by": "dashboard",
    })
    TASKS_QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "task_id": task_id, "role": role})


@app.route("/api/team/result/<task_id>")
def api_team_result(task_id):
    """Get task status + result + SUMMARY.md content if produced."""
    if not TASKS_QUEUE.exists():
        return jsonify({"error": "no queue"})
    q = json.loads(TASKS_QUEUE.read_text(encoding="utf-8"))
    for t in q["tasks"]:
        if t["id"] == task_id:
            out = dict(t)
            summary_path = TEAM_OUTPUT_DIR / task_id / "SUMMARY.md"
            if summary_path.exists():
                try:
                    out["summary"] = summary_path.read_text(encoding="utf-8")[:6000]
                except Exception: pass
            return jsonify(out)
    return jsonify({"error": f"task {task_id} not found"})


@app.route("/api/team/recent")
def api_team_recent():
    """Last 20 dashboard-submitted tasks (newest first)."""
    if not TASKS_QUEUE.exists():
        return jsonify([])
    q = json.loads(TASKS_QUEUE.read_text(encoding="utf-8"))
    tasks = [t for t in q.get("tasks", []) if t.get("requested_by") == "dashboard"]
    return jsonify(tasks[-20:][::-1])


@app.route("/api/ea/evolver")
def api_ea_evolver():
    """EA Evolver daemon state + recent evolution history."""
    state = _json(EA_EVOLVER_STATE, {})
    history = []
    if EA_EVOLUTION_LOG.exists():
        try:
            import csv as _csv
            with open(EA_EVOLUTION_LOG, encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                history = list(reader)[-15:]
        except Exception: pass
    if state.get("ts"):
        try:
            age = (datetime.now() - datetime.fromisoformat(state["ts"])).total_seconds()
            state["age_s"] = age
        except Exception: pass
    return jsonify({"state": state, "history": history})


@app.route("/api/team")
def api_team():
    """Agent team daemon state — queue counts, recent tasks, daemon health."""
    state = _json(TEAM_STATE, {})
    if state.get("ts"):
        try:
            age = (datetime.now() - datetime.fromisoformat(state["ts"])).total_seconds()
            state["age_s"]   = age
            state["running"] = age < 30
        except Exception:
            state["running"] = False
    else:
        state["running"] = False
    return jsonify(state)


@app.route("/api/dom")
def api_dom():
    """Real Level-2 DOM from Binance (BTCUSDT) — Bookmap-style order book."""
    return jsonify(_json(BINANCE_DOM, {"status": "binance dom not running"}))


@app.route("/api/gold_dom")
def api_gold_dom():
    """Try to pull DOM for XAUUSDm directly from MT5 (if broker provides it)."""
    if not HAS_MT5:
        return jsonify({"available": False, "reason": "MT5 not initialized"})

    symbol = "XAUUSDm"
    subscribed = _ensure_dom_subscribed(symbol)
    if not subscribed:
        return jsonify({
            "available": False,
            "reason": f"broker (Exness) does not publish Level-2 DOM for {symbol}",
            "alternative": "Using tick-derived Footprint at /api/footprint",
        })

    book = mt5.market_book_get(symbol)
    if not book:
        return jsonify({"available": True, "levels": 0, "reason": "DOM subscribed but empty"})

    bids = []
    asks = []
    for b in book:
        entry = {"price": float(b.price), "volume": float(b.volume),
                 "volume_real": float(b.volume_real)}
        if b.type in (mt5.BOOK_TYPE_BUY, mt5.BOOK_TYPE_BUY_MARKET):
            bids.append(entry)
        elif b.type in (mt5.BOOK_TYPE_SELL, mt5.BOOK_TYPE_SELL_MARKET):
            asks.append(entry)

    tick = mt5.symbol_info_tick(symbol)
    return jsonify({
        "available": True,
        "symbol":    symbol,
        "ts":        datetime.now().isoformat(),
        "best_bid":  float(tick.bid) if tick else None,
        "best_ask":  float(tick.ask) if tick else None,
        "bid_levels": sorted(bids, key=lambda x: -x["price"])[:20],
        "ask_levels": sorted(asks, key=lambda x:  x["price"])[:20],
        "bid_total":  sum(b["volume"] for b in bids),
        "ask_total":  sum(a["volume"] for a in asks),
    })


# ── Chat with agents ──────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/chat"

AGENT_PERSONAS = {
    "HUNTER": {
        "emoji": "🎯", "model": "qwen2.5:7b",
        "system": "أنت HUNTER — صياد المستويات في فريق FRIDAY. تحلل الشموع وتحدد مستويات سعرية قوية. تجيب بالعربية بشكل مهني ومباشر. أنت تتحدث الآن مع المستخدم Radhi."
    },
    "STRUCTURE": {
        "emoji": "🏗", "model": "qwen2.5:7b",
        "system": "أنت STRUCTURE — محلل البنية SMC. تشرح BOS, CHoCH, order blocks, FVG. تجيب بالعربية بأسلوب واضح. تتحدث الآن مع المستخدم Radhi."
    },
    "MOMENTUM": {
        "emoji": "⚡", "model": "qwen2.5:3b",
        "system": "أنت MOMENTUM — قارئ الزخم. تقيّم RSI و ATR والسبريد والاتجاه. مختصر ومباشر. تتحدث الآن مع Radhi."
    },
    "RISK": {
        "emoji": "🛡", "model": "qwen2.5:3b",
        "system": "أنت RISK — حارس المخاطر. تقيّم حجم الـ lot، الـ SL، والـ exposure. كن صريحاً ومحافظاً. تتحدث مع Radhi."
    },
    "CHARTIST": {
        "emoji": "🎨", "model": "qwen2.5:7b",
        "system": "أنت CHARTIST — رسّام محترف للشارت. ترسم trend lines، demand/supply zones، Fibonacci، channels، ومستويات رئيسية. تشرح ما رسمته على الشارت ولماذا. تتحدث مع Radhi."
    },
    "COORDINATOR": {
        "emoji": "🧠", "model": "qwen2.5:7b",
        "system": "أنت COORDINATOR — المنسق الذكي لفريق FRIDAY. تشاهد كل آراء الفريق وتعطي صورة موحدة. أجب بالعربية بهدوء وثقة. تتحدث مع Radhi."
    },
}


def _market_context_text():
    """Compact market summary for chat prompts."""
    for p in [MT5_DATA / "ea_realtime_status.json"]:
        if p.exists():
            m = _json(p, {})
            return (
                f"السعر: bid={m.get('bid','?')} ask={m.get('ask','?')} "
                f"spread={m.get('spread_points','?')}pt | "
                f"SMC bias={m.get('smc_bias','?')} BOS={m.get('smc_has_bos',False)} "
                f"OB={m.get('smc_ob_count',0)} FVG={m.get('smc_fvg_count',0)} | "
                f"Swing↑{m.get('smc_swing_high','?')} Swing↓{m.get('smc_swing_low','?')} | "
                f"PDH {m.get('prev_day_high','?')} PDL {m.get('prev_day_low','?')} | "
                f"Balance={m.get('balance','?')} Equity={m.get('equity','?')} "
                f"positions={m.get('positions',0)} losses={m.get('loss_streak',0)}"
            )
    return "(لا بيانات سوق)"


def _recent_dialogue_text(n=6):
    bs = _json(BRAIN_V2, {})
    msgs = bs.get("dialogue", [])[-n:]
    lines = []
    for m in msgs:
        c = m.get("content", {}) or {}
        say = c.get("say") or c.get("reason") or ""
        if say:
            lines.append(f"  {m.get('sender','?')}: {say[:100]}")
    return "\n".join(lines) or "(لا حوار حديث)"


def _ask_agent(agent_name: str, user_msg: str, history: list) -> dict:
    persona = AGENT_PERSONAS.get(agent_name, AGENT_PERSONAS["COORDINATOR"])
    market  = _market_context_text()
    peers   = _recent_dialogue_text()

    # Build messages with history
    messages = [
        {"role": "system", "content": persona["system"] + (
            f"\n\n=== السوق الآن ===\n{market}\n\n=== ما يقوله زملاؤك مؤخراً ===\n{peers}\n\n"
            "أجب باختصار، بالعربية، كنص طبيعي (لا JSON). إذا كان السؤال تقنياً، أعطِ أرقاماً محددة."
        )}
    ]
    for h in history[-6:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": persona["model"],
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 350},
        }, timeout=60)
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        text = f"[خطأ في LLM: {e}]"

    return {
        "agent":    agent_name,
        "emoji":    persona["emoji"],
        "model":    persona["model"],
        "response": text,
        "ts":       datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/chat/agents")
def api_chat_agents():
    """List available chat agents."""
    return jsonify([
        {"name": n, "emoji": p["emoji"], "model": p["model"]}
        for n, p in AGENT_PERSONAS.items()
    ])


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chat with one or all agents.
       Body: { "agent": "HUNTER|STRUCTURE|MOMENTUM|RISK|COORDINATOR|ALL",
               "message": "...", "history": [{role, content}, ...] }"""
    data = request.get_json(force=True) or {}
    agent = (data.get("agent") or "COORDINATOR").upper()
    msg   = (data.get("message") or "").strip()
    hist  = data.get("history") or []

    if not msg:
        return jsonify({"error": "empty message"}), 400

    if agent == "ALL":
        # Ask all agents in parallel-ish (sequential here is fine for ~5 small models)
        results = []
        for name in AGENT_PERSONAS:
            results.append(_ask_agent(name, msg, hist))
        return jsonify({"mode": "all", "replies": results})

    if agent not in AGENT_PERSONAS:
        return jsonify({"error": f"unknown agent {agent}"}), 400

    reply = _ask_agent(agent, msg, hist)
    return jsonify({"mode": "single", "replies": [reply]})


# ─────────────────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME ANALYSIS — read same dip-detector logic on M1/M5/M15/H1/H4
# Used by /api/team/decide to give agents a multi-TF view in one call.
# ─────────────────────────────────────────────────────────────────────────
def _ensure_mt5_alive() -> bool:
    """If MT5 IPC dropped, reinitialize. Returns True if ready."""
    if not HAS_MT5: return False
    try:
        if mt5.account_info() is None:
            try: mt5.shutdown()
            except Exception: pass
            return mt5.initialize()
        return True
    except Exception:
        try: mt5.shutdown()
        except Exception: pass
        return mt5.initialize()


def _quick_tf_snapshot(symbol: str, tf, n_bars: int = 60) -> dict:
    """Return key levels + simple bias for one timeframe."""
    if not HAS_MT5:
        return {"ok": False, "reason": "mt5"}
    try:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None or len(rates) < 20:
            # Try one reconnect — IPC can drop
            if _ensure_mt5_alive():
                rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
            if rates is None or len(rates) < 20:
                return {"ok": False, "reason": "no bars"}
        c = rates["close"]; h = rates["high"]; l = rates["low"]
        # ATR(14)
        tr = [max(float(h[i])-float(l[i]),
                  abs(float(h[i])-float(c[i-1])),
                  abs(float(l[i])-float(c[i-1]))) for i in range(1, len(rates))]
        atr = sum(tr[-14:]) / 14
        # RSI(14)
        diffs = [float(c[i])-float(c[i-1]) for i in range(1, len(c))]
        gains = [max(0, d) for d in diffs[-14:]]
        losses= [max(0,-d) for d in diffs[-14:]]
        avg_g = sum(gains)/14; avg_l = sum(losses)/14
        rsi   = 100 - 100/(1 + (avg_g/avg_l)) if avg_l > 0 else 100
        # Simple trend bias: last 20 closes — higher highs+higher lows = UP
        last20 = c[-20:]
        slope = (float(last20[-1]) - float(last20[0])) / max(1e-9, atr)
        if slope > 0.5: bias = "UP"
        elif slope < -0.5: bias = "DOWN"
        else: bias = "RANGE"
        # Swing high/low across n_bars
        out = {
            "ok":        True,
            "current":   round(float(c[-1]), 3),
            "atr":       round(atr, 3),
            "rsi":       round(rsi, 1),
            "swing_high": round(float(h.max()), 3),
            "swing_low":  round(float(l.min()), 3),
            "range_size": round(float(h.max() - l.min()), 3),
            "bias":      bias,
            "slope_atr": round(slope, 2),
        }
        # ── SMC sub-dict (Phase 4): attach OB/FVG/BOS/CHoCH/sweep/IDM/pools
        # so genome_signal SMC evaluators have data to read. Failures here
        # MUST NOT break the TF snapshot — return empty smc on any error.
        try:
            from r_native import smc_engine as _se
            out["smc"] = _se.compute_offline(rates)
        except Exception:
            out["smc"] = {}
        return out
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@app.route("/api/multi_tf")
def api_multi_tf():
    """Snapshot of the same instrument across M1/M5/M15/H1/H4."""
    symbol = request.args.get("symbol", "XAUUSDm")
    if not HAS_MT5:
        return jsonify({"ok": False, "reason": "MT5 unavailable"})
    tfs = [("M1", mt5.TIMEFRAME_M1, 60),
           ("M5", mt5.TIMEFRAME_M5, 60),
           ("M15", mt5.TIMEFRAME_M15, 60),
           ("H1", mt5.TIMEFRAME_H1, 60),
           ("H4", mt5.TIMEFRAME_H4, 60)]
    result = {}
    for label, tf, n in tfs:
        result[label] = _quick_tf_snapshot(symbol, tf, n)
    # Alignment scoring
    biases = [r.get("bias") for r in result.values() if r.get("ok")]
    up = biases.count("UP"); dn = biases.count("DOWN"); rg = biases.count("RANGE")
    if up >= 4: trend = "STRONG_UP"
    elif up >= 3: trend = "UP_LEANING"
    elif dn >= 4: trend = "STRONG_DOWN"
    elif dn >= 3: trend = "DOWN_LEANING"
    else: trend = "MIXED"
    return jsonify({
        "ok":       True,
        "ts":       datetime.now().isoformat(),
        "symbol":   symbol,
        "tfs":      result,
        "trend":    trend,
        "vote":     {"UP": up, "DOWN": dn, "RANGE": rg},
    })


# ─────────────────────────────────────────────────────────────────────────
# /api/snapshot — single endpoint that bundles EVERY number the dashboard
# shows, so the team can analyse the whole picture with one HTTP round-trip.
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/snapshot")
def api_snapshot():
    """Composite of everything the team should consider, one call."""
    try:
        # use existing helpers / endpoints internally via a Flask test request
        # we call each builder function inline to keep latency low
        with app.test_client() as tc:
            def J(path):
                try:
                    r = tc.get(path)
                    if r.status_code != 200: return {"_err": r.status_code}
                    return r.get_json()
                except Exception as e:
                    return {"_err": str(e)}

            snap = {
                "ts":       datetime.now().isoformat(),
                "account":  J("/api/account?hours=168"),
                "regime":   J("/api/regime"),
                "multi_tf": J("/api/multi_tf"),
                "chart":    {"levels": J("/api/chart").get("levels", {})},
                "v3":       J("/api/v3"),
                "fractals": J("/api/fractals"),
                "memory":   J("/api/memory"),
            }
        # Footprint is heavy — only attach a short summary
        fp = _json(FOOTPRINT_FILE, {})
        if fp:
            snap["footprint_summary"] = {
                "session_poc":  fp.get("session_poc"),
                "session_vah":  fp.get("session_vah"),
                "session_val":  fp.get("session_val"),
                "cum_delta":    fp.get("cum_delta_series", [])[-1] if fp.get("cum_delta_series") else None,
                "bars":         len(fp.get("bars", [])),
            }
        return jsonify(snap)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────
# /api/team/decide — feed full snapshot to each agent; each returns a
# STRUCTURED JSON verdict. Then COORDINATOR aggregates.
# ADVISORY ONLY — does not execute any order_send.
# ─────────────────────────────────────────────────────────────────────────
DECISION_AGENTS = ["HUNTER", "STRUCTURE", "MOMENTUM", "RISK", "CHARTIST"]

def _build_decision_prompt(snap: dict) -> str:
    """Compress the snapshot into a numeric brief the LLM can reason over."""
    mk  = (snap.get("account") or {}).get("account") or {}
    pos = (snap.get("account") or {}).get("positions") or []
    rg  = snap.get("regime") or {}
    mtf = (snap.get("multi_tf") or {}).get("tfs", {})
    chl = (snap.get("chart")    or {}).get("levels", {})
    v3  = (snap.get("v3")       or {}).get("state", {})
    fp  = snap.get("footprint_summary") or {}

    parts = []
    parts.append(f"=== ACCOUNT ===")
    parts.append(f"balance ${mk.get('balance')} | equity ${mk.get('equity')} | open_pnl ${(snap.get('account') or {}).get('open_pnl')} | positions {len(pos)}")
    if pos:
        for p in pos[:6]:
            parts.append(f"  pos #{p['ticket']} {p['symbol']} {p['type']} {p['volume']} entry={p['price_open']} now={p['price_current']} sl={p['sl']} tp={p['tp']} pnl=${p['profit']}")

    parts.append(f"\n=== REGIME ===")
    parts.append(f"regime={rg.get('regime')} score={rg.get('score')} allow_trade={rg.get('allow_trade')} spread={rg.get('spread_pt')}pt atr={rg.get('atr_pt')}pt")
    if rg.get('reasons'): parts.append(f"  reasons: {'; '.join(rg['reasons'])}")

    parts.append(f"\n=== MULTI-TF (XAUUSDm) ===")
    for tf, d in mtf.items():
        if d.get("ok"):
            parts.append(f"  {tf}: price={d['current']} bias={d['bias']} RSI={d['rsi']} ATR={d['atr']} swing[{d['swing_low']}-{d['swing_high']}]")
    parts.append(f"  → composite trend: {(snap.get('multi_tf') or {}).get('trend')}")

    parts.append(f"\n=== SMC / KEY LEVELS ===")
    if chl:
        parts.append(f"bid={chl.get('bid')} ask={chl.get('ask')} spread={chl.get('spread_points')}pt")
        parts.append(f"SMC bias={chl.get('smc_bias')} swing_hi={chl.get('smc_swing_high')} swing_lo={chl.get('smc_swing_low')} BOS={chl.get('smc_has_bos')} CHoCH={chl.get('smc_has_choch')}")
        parts.append(f"PDH={chl.get('prev_day_high')} PDL={chl.get('prev_day_low')}")

    parts.append(f"\n=== FOOTPRINT ===")
    if fp:
        parts.append(f"POC={fp.get('session_poc')} VAH={fp.get('session_vah')} VAL={fp.get('session_val')} cum_delta={fp.get('cum_delta')}")

    parts.append(f"\n=== V3 GENETIC POOL ===")
    parts.append(f"generation={v3.get('generation')} best_fitness={v3.get('best_fitness')} daily_pl=${v3.get('daily_pl')} killed={v3.get('killed')} mode={v3.get('mode')}")

    return "\n".join(parts)


def _ask_for_structured_verdict(agent_name: str, brief: str) -> dict:
    persona = AGENT_PERSONAS.get(agent_name, AGENT_PERSONAS["COORDINATOR"])
    instr = (persona["system"]
        + "\n\nأنت الآن في وضع 'صنع قرار'. اقرأ كل الأرقام بدقة. "
          "أعد ردك حصرياً ككائن JSON صالح (لا نص آخر) بالحقول التالية:\n"
          "{\n"
          '  "action": "BUY"|"SELL"|"HOLD"|"CLOSE_OPEN"|"WAIT",\n'
          '  "timeframe": "M1"|"M5"|"M15"|"H1"|"H4",\n'
          '  "entry":    number_or_null,\n'
          '  "sl":       number_or_null,\n'
          '  "near_tp":  number_or_null,\n'
          '  "far_tp":   number_or_null,\n'
          '  "confidence": 0-100,\n'
          '  "reason_ar":   "سبب موجز بالعربية",\n'
          '  "tf_alignment":"M1/M5/M15/H1/H4 كم منها يدعم القرار"\n'
          "}\n"
          "لا تكتب أي شيء قبل أو بعد الـ JSON.")
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": persona["model"],
            "messages": [
                {"role": "system", "content": instr},
                {"role": "user",   "content": "بيانات السوق:\n" + brief +
                                              "\n\nالآن أعطِ القرار المنظم بصيغة JSON فقط."},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.3, "num_predict": 500},
        }, timeout=90)
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "").strip()
        try:
            data = json.loads(text)
        except Exception:
            # try to extract first {...} block
            import re as _re
            m = _re.search(r"\{[\s\S]*\}", text)
            data = json.loads(m.group(0)) if m else {"action": "WAIT", "reason_ar": text[:200]}
    except Exception as e:
        data = {"action": "WAIT", "reason_ar": f"خطأ LLM: {e}", "confidence": 0}
    data["agent"] = agent_name
    data["emoji"] = persona["emoji"]
    return data


@app.route("/api/team/decide", methods=["GET", "POST"])
def api_team_decide():
    """Read every dashboard number, ask the team, return aggregated verdicts.
    ADVISORY ONLY — no order_send anywhere.
    """
    try:
        # 1. Build snapshot
        with app.test_client() as tc:
            snap_resp = tc.get("/api/snapshot")
            if snap_resp.status_code != 200:
                return jsonify({"ok": False, "error": "snapshot failed"}), 500
            snap = snap_resp.get_json()

        brief = _build_decision_prompt(snap)

        # 2. Ask each decision agent in parallel via threadpool
        from concurrent.futures import ThreadPoolExecutor, as_completed
        verdicts = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(_ask_for_structured_verdict, a, brief): a for a in DECISION_AGENTS}
            for f in as_completed(futs, timeout=120):
                try:    verdicts.append(f.result())
                except Exception as e:
                    verdicts.append({"agent": futs[f], "action": "WAIT",
                                     "reason_ar": f"err: {e}", "confidence": 0})

        # 3. Aggregate: count BUY/SELL/HOLD votes weighted by confidence
        weighted = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0, "CLOSE_OPEN": 0.0, "WAIT": 0.0}
        for v in verdicts:
            a = (v.get("action") or "WAIT").upper()
            c = float(v.get("confidence") or 0)
            if a not in weighted: a = "WAIT"
            weighted[a] += c
        # Final consensus
        final_action = max(weighted, key=weighted.get) if any(weighted.values()) else "WAIT"
        avg_conf = round(sum(weighted.values()) / max(1, len([v for v in verdicts if v.get("action")])), 1)

        # Aggregate near_tp / far_tp / sl (median of those provided)
        def _median(xs):
            xs = sorted([float(x) for x in xs if isinstance(x,(int,float))])
            return xs[len(xs)//2] if xs else None
        near_tps = [v.get("near_tp") for v in verdicts if v.get("near_tp")]
        far_tps  = [v.get("far_tp")  for v in verdicts if v.get("far_tp")]
        sls      = [v.get("sl")      for v in verdicts if v.get("sl")]

        consensus = {
            "action":     final_action,
            "confidence": avg_conf,
            "near_tp":    _median(near_tps),
            "far_tp":     _median(far_tps),
            "sl":         _median(sls),
            "weighted_votes": {k: round(v,1) for k,v in weighted.items()},
        }

        return jsonify({
            "ok":         True,
            "ts":         datetime.now().isoformat(),
            "advisory":   "ADVISORY ONLY — no orders sent. EA is in control.",
            "snapshot_brief": brief,
            "verdicts":   verdicts,
            "consensus":  consensus,
        })
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:500]}), 500


@app.route("/api/control")
def api_control():
    """The Live Control vector being sent to the EA, plus raw CSV echo."""
    state = _json(BRIDGE_STATE, {}) if BRIDGE_STATE.exists() else {}
    csv_text = ""
    csv_age = None
    if CONTROL_CSV.exists():
        try:
            csv_text = CONTROL_CSV.read_text(encoding="cp1252", errors="replace")
            csv_age  = int(time.time() - CONTROL_CSV.stat().st_mtime)
        except Exception:
            pass
    return jsonify({
        "bridge_state":      state,
        "control_csv_raw":   csv_text,
        "control_csv_age_s": csv_age,
        "control_csv_path":  str(CONTROL_CSV),
    })


@app.route("/api/unified")
def api_unified():
    """One endpoint that merges Brain (swarm + market + vault) + SMC + EA control."""
    swarm = {}
    for p in [MT5_DATA / "friday_agents.json", MT5_ROOT / "friday_agents.json"]:
        if p.exists():
            swarm = _json(p, {})
            break

    market = {}
    for p in [MT5_DATA / "ea_realtime_status.json",
              MT5_DATA / "ea_bar_history.json",
              MT5_DATA / "friday_realtime_bar.json"]:
        if p.exists():
            d = _json(p, {})
            market = d.get("current", d)
            break

    # SMC sub-fetches — tight timeouts so /api/unified stays responsive (<1s)
    smc_status,    _ = _proxy_get(f"{SMC_BASE}/api/status",    timeout=0.8)
    smc_decisions, _ = _proxy_get(f"{SMC_BASE}/api/decisions", timeout=0.8)
    smc_brain,     _ = _proxy_get(f"{SMC_BASE}/api/brain",     timeout=0.8)

    bridge_state = _json(BRIDGE_STATE, {}) if BRIDGE_STATE.exists() else {}
    control_age  = None
    if CONTROL_CSV.exists():
        try:
            control_age = int(time.time() - CONTROL_CSV.stat().st_mtime)
        except Exception:
            pass

    # Bar history for the chart panel
    bars = _json(MT5_DATA / "ea_bar_history.json", [])
    if isinstance(bars, dict):
        bars = bars.get("bars", []) or bars.get("history", []) or []
    if len(bars) > 120:
        bars = bars[-120:]

    # Brain v2 (LLM-powered, multi-agent network)
    brain_llm = _json(BRAIN_V2, {}) if BRAIN_V2.exists() else {}

    # Footprint (tick-level)
    footprint = _json(FOOTPRINT_FILE, {}) if FOOTPRINT_FILE.exists() else {}

    # Binance DOM (real Level-2 order book for BTCUSDT)
    binance_dom = _json(BINANCE_DOM, {}) if BINANCE_DOM.exists() else {}

    return jsonify({
        "ts":          datetime.now().isoformat(),
        "swarm":       swarm,
        "brain_llm":   brain_llm,
        "footprint":   footprint,
        "binance_dom": binance_dom,
        "market":      market,
        "chart":  {
            "bars": bars,
            "levels": {
                "bid":            market.get("bid"),
                "ask":            market.get("ask"),
                "prev_day_high":  market.get("prev_day_high"),
                "prev_day_low":   market.get("prev_day_low"),
                "smc_swing_high": market.get("smc_swing_high"),
                "smc_swing_low":  market.get("smc_swing_low"),
                "smc_bos_level":  market.get("smc_bos_level"),
                "smc_bias":       market.get("smc_bias"),
                "dna_gap":        market.get("dna_gap"),
            },
        },
        "smc": {
            "status":    smc_status,
            "decisions": smc_decisions[-20:] if isinstance(smc_decisions, list) else smc_decisions,
            "brain":     smc_brain,
        },
        "control": {
            "bridge":     bridge_state,
            "csv_age_s":  control_age,
            "applied":    (control_age is not None and control_age < 30
                           and bridge_state.get("control", {}).get("confidence", 0) >= 50),
        },
        "vault": {
            "hot":      _text(VAULT / "hot.md", 800),
            "log_tail": _text(VAULT / "log.md", 400),
        },
    })


@app.route("/<path:filename>")
def root_static(filename):
    """Serve any dashboard file at root so relative fetches in HTML work."""
    target = DASHBOARD / filename
    if target.exists() and target.is_file():
        return send_from_directory(str(DASHBOARD), filename)
    return ("not found", 404)


@app.route("/api/swarm")
def api_swarm():
    """Raw swarm JSON from friday_agents.py."""
    for p in [MT5_DATA / "friday_agents.json", MT5_ROOT / "friday_agents.json"]:
        if p.exists():
            return jsonify(_json(p, {}))
    return jsonify({"error": "swarm not running — start friday_agents.py"})


@app.route("/api/market")
def api_market():
    """Live MT5 market data."""
    for p in [MT5_DATA / "ea_realtime_status.json",
               MT5_DATA / "ea_bar_history.json",
               MT5_DATA / "friday_realtime_bar.json"]:
        if p.exists():
            data = _json(p, {})
            return jsonify(data.get("current", data))
    return jsonify({"status": "EA not running", "symbol": "XAUUSDm"})


@app.route("/api/chart")
def api_chart():
    """OHLC bar history + key levels — pulls LIVE from MT5 Python API (bypasses stale EA JSON)."""
    out_bars = []
    live_status = {}

    # ── LIVE path: read directly from MT5 ──
    if HAS_MT5:
        try:
            rates = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_M1, 0, 120)
            if rates is not None and len(rates) > 0:
                for r in rates:
                    out_bars.append({
                        "t":   datetime.fromtimestamp(int(r["time"])).strftime("%Y.%m.%d %H:%M"),
                        "o":   float(r["open"]),
                        "h":   float(r["high"]),
                        "l":   float(r["low"]),
                        "c":   float(r["close"]),
                        "spr": int(r["spread"]),
                        "vol": int(r["tick_volume"]),
                    })

            tick = mt5.symbol_info_tick("XAUUSDm")
            si   = mt5.symbol_info("XAUUSDm")
            if tick and si:
                live_status = {
                    "bid":           float(tick.bid),
                    "ask":           float(tick.ask),
                    "spread_points": int(si.spread),
                    "symbol":        "XAUUSDm",
                }
        except Exception as e:
            print(f"[/api/chart MT5 error] {e}")

    # ── Fallback to stale EA JSON if MT5 read failed ──
    if not out_bars:
        bars   = _json(MT5_DATA / "ea_bar_history.json", [])
        status = _json(MT5_DATA / "ea_realtime_status.json", {})
        if isinstance(bars, dict):
            bars = bars.get("bars", []) or bars.get("history", []) or []
        if len(bars) > 120: bars = bars[-120:]
        for b in bars:
            if not isinstance(b, dict): continue
            out_bars.append({
                "t":   b.get("time") or b.get("t") or "",
                "o":   b.get("o") or b.get("open"),
                "h":   b.get("h") or b.get("high"),
                "l":   b.get("l") or b.get("low"),
                "c":   b.get("c") or b.get("close"),
                "spr": b.get("spr") or b.get("spread_points"),
            })
        live_status = status

    # Read SMC + key levels from the (possibly stale) EA snapshot, override bid/ask with live
    ea_snap = _json(MT5_DATA / "ea_realtime_status.json", {})
    levels = {
        "bid":             live_status.get("bid")           or ea_snap.get("bid"),
        "ask":             live_status.get("ask")           or ea_snap.get("ask"),
        "spread_points":   live_status.get("spread_points") or ea_snap.get("spread_points"),
        "prev_day_high":   ea_snap.get("prev_day_high"),
        "prev_day_low":    ea_snap.get("prev_day_low"),
        "smc_swing_high":  ea_snap.get("smc_swing_high"),
        "smc_swing_low":   ea_snap.get("smc_swing_low"),
        "smc_bos_level":   ea_snap.get("smc_bos_level"),
        "smc_bias":        ea_snap.get("smc_bias"),
        "smc_has_bos":     ea_snap.get("smc_has_bos"),
        "smc_has_choch":   ea_snap.get("smc_has_choch"),
        "smc_ob_count":    ea_snap.get("smc_ob_count"),
        "smc_fvg_count":   ea_snap.get("smc_fvg_count"),
        "dna_gap":         ea_snap.get("dna_gap"),
        "dna_tp":          ea_snap.get("dna_tp"),
        "dna_sl":          ea_snap.get("dna_sl"),
    }

    return jsonify({
        "symbol":     "XAUUSDm",
        "timeframe":  "M1",
        "bars":       out_bars,
        "levels":     levels,
        "live_from":  "mt5" if HAS_MT5 and out_bars else "ea_json",
        "ts":         datetime.now().isoformat(),
    })


# ═══════════════════════════════════════════════════════════════════════
# R FACTORY — Algory clone with R branding + persistent learning memory
# ═══════════════════════════════════════════════════════════════════════
R_ROOT = Path(r"C:\Users\Radhi\MT5\friday_v3\algory")

@app.route("/r/")
@app.route("/r")
def r_factory_home():
    """R Factory main UI."""
    page = R_ROOT / "r_factory_ui.html"
    if not page.exists():
        return "<h1>R Factory UI missing</h1>", 404
    return page.read_text(encoding="utf-8")


@app.route("/r/logo.svg")
def r_factory_logo():
    """Serve R logo SVG."""
    svg = R_ROOT / "r_logo.svg"
    if not svg.exists():
        return "", 404
    return Response(svg.read_text(encoding="utf-8"), mimetype="image/svg+xml")


# ─── H.20: Pixel Lab dashboard + state feed ─────────────────────────
PIXEL_DASH_ROOT = Path(r"C:\Users\Radhi\MT5\r_native\dashboard")

@app.route("/r/pixel_lab")
@app.route("/r/pixel_lab/")
def r_pixel_lab_page():
    """Serve the Arabic pixel-lab HTML dashboard (generated by external agent)."""
    page = PIXEL_DASH_ROOT / "pixel_lab.html"
    if not page.exists():
        return "<h1>pixel_lab.html missing</h1>", 404
    return page.read_text(encoding="utf-8")


@app.route("/r/pixel_lab/sprites.json")
def r_pixel_lab_sprites():
    """Serve the sprite atlas JSON consumed by the HTML page."""
    sp = PIXEL_DASH_ROOT / "pixel_sprites.json"
    if not sp.exists():
        return jsonify({"error": "sprites missing"}), 404
    return Response(sp.read_text(encoding="utf-8"),
                    mimetype="application/json")


@app.route("/api/r/agents/list")
@app.route("/api/r/agents")     # alias used by dashboard.html
def api_r_agents_list():
    """List all registered agents + their status."""
    try:
        from r_native.agents.orchestrator import list_agents
        return jsonify({"ok": True, "agents": list_agents()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/agents/<name>/run", methods=["POST"])
def api_r_agents_path_run(name):
    """Path-style alias for dashboard: POST /api/r/agents/<name>/run"""
    try:
        from r_native.agents.orchestrator import run_now
        result = run_now(name)
        if result is None:
            return jsonify({"ok": False, "error": f"agent {name} not found"}), 404
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/agents/toggle", methods=["POST"])
def api_r_agents_toggle():
    """Toggle a specific agent on/off.
    Body: {"name": "risk_sentinel", "enabled": true|false}
    """
    try:
        from flask import request as _req
        from r_native.agents.orchestrator import toggle
        payload = _req.get_json(silent=True) or {}
        name = payload.get("name")
        if not name: return jsonify({"ok": False, "error": "missing name"})
        result = toggle(name, payload.get("enabled"))
        if result is None:
            return jsonify({"ok": False, "error": f"agent {name} not found"})
        return jsonify({"ok": True, "agent": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/agents/run_now", methods=["POST"])
def api_r_agents_run_now():
    """Manually trigger one tick of an agent.
    Body: {"name": "genome_curator"}
    """
    try:
        from flask import request as _req
        from r_native.agents.orchestrator import run_now
        payload = _req.get_json(silent=True) or {}
        name = payload.get("name")
        if not name: return jsonify({"ok": False, "error": "missing name"})
        result = run_now(name)
        if result is None:
            return jsonify({"ok": False, "error": f"agent {name} not found"})
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/agents/strategist_autonomous", methods=["GET", "POST"])
def api_r_strategist_autonomous():
    """Get or set the LLM Strategist's autonomous mode flag.
    POST body: {"enabled": true|false}
    GET returns current state.
    """
    try:
        from flask import request as _req
        from r_native.agents.orchestrator import _agents
        strat = _agents.get("llm_strategist")
        if not strat:
            return jsonify({"ok": False, "error": "strategist not loaded"})
        if _req.method == "POST":
            payload = _req.get_json(silent=True) or {}
            new_val = strat.set_autonomous(bool(payload.get("enabled", False)))
            return jsonify({"ok": True, "autonomous": new_val})
        return jsonify({"ok": True, "autonomous": strat._autonomous})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/breed", methods=["POST"])
def api_r_breed():
    """Manually breed two HoF genomes into a child + admit to HoF.
    Body: {"symbol": "BTCUSDm", "parent_a": "ID1", "parent_b": "ID2"}
    """
    try:
        from flask import request as _req
        from r_native.breeder import breed_and_admit
        payload = _req.get_json(silent=True) or {}
        sym = payload.get("symbol", "BTCUSDm")
        pa  = payload.get("parent_a")
        pb  = payload.get("parent_b")
        if not (pa and pb):
            return jsonify({"ok": False, "error": "need parent_a and parent_b"})
        result = breed_and_admit(sym, pa, pb,
                                 tf=payload.get("tf", "M5"),
                                 bars=int(payload.get("bars", 2000)))
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/agents/insights")
def api_r_agents_insights():
    """Recent insights from the unified stream.
    Query params: ?n=50&agent=risk_sentinel&level=ACT
    """
    try:
        from flask import request as _req
        from r_native.agents.orchestrator import insights
        n     = int(_req.args.get("n", 100))
        agent = _req.args.get("agent")
        level = _req.args.get("level")
        items = insights(n=n, agent=agent, level=level)
        return jsonify({"ok": True, "count": len(items), "insights": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/hof/summary")
def api_r_hof_summary():
    """Hall of Fame stats — total genomes, by-symbol ranks, pinned count."""
    try:
        from r_native.hall_of_fame import summary
        return jsonify({"ok": True, **summary()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/hof/symbol/<symbol>")
def api_r_hof_symbol(symbol):
    """Ranked list of all genomes ever produced for this symbol."""
    try:
        from r_native.hall_of_fame import load_symbol
        from flask import request as _req
        n = int(_req.args.get("limit", 50))
        items = load_symbol(symbol)[:n]
        return jsonify({"ok": True, "symbol": symbol, "count": len(items),
                        "genomes": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/hof/pin", methods=["POST"])
def api_r_hof_pin():
    """Pin/unpin a genome (pinned = immortal, can't be killed).
    Body: {"id": "DF9F6C", "pinned": true|false}
    """
    try:
        from flask import request as _req
        from r_native.hall_of_fame import pin, unpin
        payload = _req.get_json(silent=True) or {}
        gid = payload.get("id")
        if not gid: return jsonify({"ok": False, "error": "missing id"})
        if payload.get("pinned", True):
            pin(gid)
            return jsonify({"ok": True, "pinned": True, "id": gid})
        unpin(gid)
        return jsonify({"ok": True, "pinned": False, "id": gid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/hof/deploy", methods=["POST"])
def api_r_hof_deploy():
    """Manually deploy a Hall-of-Fame genome to live.
    Body: {"id": "DF9F6C", "symbol": "BTCUSDm"}
    """
    try:
        from flask import request as _req
        from r_native.hall_of_fame import load_index
        from r_native.actions import deploy_genome_to_live
        payload = _req.get_json(silent=True) or {}
        gid = payload.get("id")
        sym = payload.get("symbol")
        if not (gid and sym):
            return jsonify({"ok": False, "error": "missing id or symbol"})
        entry = load_index().get(gid)
        if not entry:
            return jsonify({"ok": False, "error": f"genome {gid} not in HoF"})
        # Build genome dict from entry
        genome_dict = {
            "id":             gid,
            "score":          entry.get("score"),
            "stats":          entry.get("stats", {}),
            "all_params":     entry.get("all_params", {}),
            "active_genes":   entry.get("active_genes", []),
            "archetype":      entry.get("archetype"),
        }
        # Flatten params so deployed_genome lookups (start_hour etc.) work
        for k, v in (entry.get("all_params") or {}).items():
            genome_dict.setdefault(k, v)
        result = deploy_genome_to_live(sym, gid, entry.get("tf", "M5"),
                                       genome_dict=genome_dict)
        return jsonify({"ok": result.get("ok"), **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/auto_evo/status")
def api_r_auto_evo_status():
    """Return continuous-evolution loop status."""
    try:
        from r_native.continuous_evolution import status
        return jsonify({"ok": True, **status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/auto_evo/toggle", methods=["POST"])
def api_r_auto_evo_toggle():
    """Toggle the continuous-evolution loop on/off.
    Body: {"enabled": true|false}  (omit to flip current state)
    """
    try:
        from flask import request as _req
        from r_native.continuous_evolution import toggle
        payload = _req.get_json(silent=True) or {}
        result = toggle(payload.get("enabled"))
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/auto_evo/run_now", methods=["POST"])
def api_r_auto_evo_run_now():
    """Fire one evolution cycle immediately (non-blocking)."""
    try:
        import threading
        from r_native.continuous_evolution import run_one_cycle
        threading.Thread(target=lambda: run_one_cycle(reason="manual"),
                         daemon=True, name="manual-evo-cycle").start()
        return jsonify({"ok": True, "kicked_off": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/auto_evo/config", methods=["GET", "POST"])
def api_r_auto_evo_config():
    """Read or update continuous-evolution settings.
    POST body: any subset of {interval_hours, symbols, pg, gens,
                              auto_deploy_threshold, min_trades_for_deploy,
                              max_deploys_per_day}
    """
    try:
        from flask import request as _req
        from r_native.continuous_evolution import load, save
        cfg = load()
        if _req.method == "POST":
            patch = _req.get_json(silent=True) or {}
            allowed = {"interval_hours", "symbols", "tf", "pg", "gens",
                       "auto_deploy_threshold", "min_trades_for_deploy",
                       "max_deploys_per_day", "notify_telegram", "notify_ui"}
            for k, v in patch.items():
                if k in allowed:
                    cfg[k] = v
            save(cfg)
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/force_trade", methods=["POST"])
def api_r_force_trade():
    """Bypass ALL gates and fire a test trade.
    Body: {symbol, side: BUY|SELL, lot: 0.01, sl_pts: 50, tp_pts: 100, comment}
    Returns: order send result.
    Magic: 20260605 (same as R Executor — appears in R dashboard).
    """
    if not HAS_MT5:
        return jsonify({"ok": False, "error": "MT5 not initialized"})
    try:
        from flask import request as _req
        payload = _req.get_json(silent=True) or {}
        symbol  = payload.get("symbol", "BTCUSDm")
        side    = (payload.get("side") or "BUY").upper()
        lot     = float(payload.get("lot",     0.01))
        sl_pts_in  = payload.get("sl_pts")
        tp_pts_in  = payload.get("tp_pts")
        comment = payload.get("comment", "R_FORCE_TEST")[:31]

        _ensure_mt5_alive()
        sym  = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not (sym and tick):
            return jsonify({"ok": False, "error": f"no symbol/tick for {symbol}"})

        # Auto-pick safe SL/TP: must clear the symbol's spread + stops_level
        # Default: 5× current spread (safety margin) — enforces sane stops
        min_dist = max(int(sym.spread or 100) * 5,
                       int(sym.trade_stops_level or 100) * 3,
                       500)   # absolute floor
        sl_pts = int(sl_pts_in) if sl_pts_in else min_dist
        tp_pts = int(tp_pts_in) if tp_pts_in else min_dist
        if sl_pts < min_dist:
            sl_pts = min_dist
        if tp_pts < min_dist:
            tp_pts = min_dist

        mt5.symbol_select(symbol, True)
        digits = sym.digits
        point  = sym.point or 0.00001
        # Clamp lot
        step = sym.volume_step or 0.01
        lot  = round(round(lot / step) * step, 2)
        lot  = max(sym.volume_min, min(sym.volume_max or 100, lot))

        if side == "BUY":
            price = tick.ask
            sl = round(price - sl_pts * point, digits)
            tp = round(price + tp_pts * point, digits)
            order_type = mt5.ORDER_TYPE_BUY
        else:
            price = tick.bid
            sl = round(price + sl_pts * point, digits)
            tp = round(price - tp_pts * point, digits)
            order_type = mt5.ORDER_TYPE_SELL

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lot),
            "type":         order_type,
            "price":        round(float(price), digits),
            "sl":           sl,
            "tp":           tp,
            "deviation":    50,
            "magic":        20260605,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res is None:
            return jsonify({"ok": False, "error": f"order_send None: {mt5.last_error()}"})

        return jsonify({
            "ok":         res.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode":    res.retcode,
            "comment":    res.comment,
            "order":      res.order,
            "deal":       res.deal,
            "volume":     res.volume,
            "price":      res.price,
            "symbol":     symbol,
            "side":       side,
            "sl":         sl,
            "tp":         tp,
            "request":    {"lot": lot, "sl_pts": sl_pts, "tp_pts": tp_pts},
        })
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e),
                        "tb": traceback.format_exc()[:400]})


@app.route("/r/pixel_lab/state")
def r_pixel_lab_state():
    """Live mascot state derived from R Executor + MT5 — for HTML polling."""
    try:
        # 1) Pull R Executor's open P/L + today's stats from state file
        import json as _json
        state_file = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
        exec_state = {}
        if state_file.exists():
            try: exec_state = _json.loads(state_file.read_text(encoding="utf-8"))
            except Exception: pass

        # 2) Pull MT5 account
        balance = 100.0; equity = 100.0; open_pl = 0.0; open_count = 0
        if HAS_MT5:
            try:
                info = mt5.account_info()
                if info:
                    balance = float(info.balance)
                    equity  = float(info.equity)
                positions = [p for p in (mt5.positions_get() or [])
                             if int(p.magic) == 20260605]
                open_count = len(positions)
                open_pl = sum(float(p.profit) for p in positions)
            except Exception: pass

        # 3) Derive mascot state
        from r_native.pixel_sprites import state_from_pnl, preset_for_state
        today_pl = float(exec_state.get("today_pl", 0) or 0)
        state    = state_from_pnl(today_pl, balance,
                                   hodl=bool(open_count))
        preset   = preset_for_state(state)

        # 4) Get currently-deployed genome on BTCUSDm for "current strategy"
        deployed = None
        try:
            cp = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs\BTCUSDm.json")
            if cp.exists():
                cfg = _json.loads(cp.read_text(encoding="utf-8"))
                dg = cfg.get("deployed_genome") or {}
                if dg.get("id"):
                    deployed = {"id": dg["id"],
                                "pf": dg.get("profit_factor"),
                                "wr": dg.get("win_rate"),
                                "symbol": "BTCUSDm"}
        except Exception: pass

        return jsonify({
            "ok":           True,
            "ts":           datetime.now().isoformat(),
            "state":        state,
            "preset_id":    preset.get("id"),
            "preset_name":  preset.get("name"),
            "today_pl":     today_pl,
            "open_pl":      round(open_pl, 2),
            "balance":      round(balance, 2),
            "equity":       round(equity, 2),
            "open_count":   open_count,
            "armed":        bool(exec_state.get("armed")),
            "mode":         exec_state.get("mode", "—"),
            "last_action":  (exec_state.get("last_action") or "")[:80],
            "deployed":     deployed,
        })
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e),
                        "tb": traceback.format_exc()[:300]})


@app.route("/api/r/memory")
def api_r_memory():
    """R's accumulated learning memory — LIGHT version for the UI.
    Pass ?full=1 for the full payload (heavy)."""
    try:
        from friday_v3.algory.learning_memory import get_memory_summary, absorb_snapshot
        # Trigger fresh absorption from latest report
        report_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\algory_report.json")
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                absorb_snapshot(report)
            except Exception: pass
        data = get_memory_summary()
        if request.args.get("full") != "1":
            # Strip the heaviest fields for normal UI polls
            light = {
                "iq":           data.get("iq", {}),
                "journal":      (data.get("journal") or [])[:15],
                "strategy_count": len(data.get("strategy_index") or {}),
                "gene_count":   len(data.get("gene_history") or {}),
                "archetype_count": len(data.get("archetype_trends") or {}),
            }
            return jsonify(light)
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/executor")
def api_r_executor():
    """R executor state — mode, armed, today_pl, freeze status.

    Counters (total_trades / wins / today_pl) are RECOMPUTED from broker
    history so they're always accurate even after restarts.
    """
    state_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
    if not state_path.exists():
        return jsonify({"running": False, "reason": "executor not started"})
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        age = (datetime.now().timestamp() -
               datetime.fromisoformat(state["ts"].replace("Z","+00:00")).timestamp())
        state["alive"] = age < 60
        state["age_s"] = round(age, 1)

        # Tally R-magic LIVE positions across ALL symbols
        r_positions = []
        r_open_pl_total = 0.0
        if HAS_MT5:
            try:
                _ensure_mt5_alive()
                for p in (mt5.positions_get() or []):    # ALL symbols
                    if int(p.magic) == 20260605:
                        r_positions.append({
                            "ticket": p.ticket,
                            "symbol": p.symbol,
                            "type": "BUY" if p.type == 0 else "SELL",
                            "volume": p.volume, "price_open": p.price_open,
                            "price_current": p.price_current,
                            "sl": p.sl, "tp": p.tp, "profit": round(p.profit, 2),
                            "swap": round(p.swap, 2),
                            "time_open": int(p.time),
                            "age_min": round((datetime.now().timestamp() - p.time) / 60, 1),
                        })
                        r_open_pl_total += float(p.profit)
            except Exception: pass
        state["r_open_positions"] = r_positions
        state["r_open_pl_total"]  = round(r_open_pl_total, 2)

        # RECOMPUTE counters from broker history (magic 20260605, last 24h)
        if HAS_MT5:
            try:
                from datetime import timedelta as _td
                today_start = (datetime.now() - _td(hours=24))
                deals = mt5.history_deals_get(today_start, datetime.now()) or []
                r_closed = [d for d in deals if int(d.magic) == 20260605 and int(d.entry) == 1]
                today_pl = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in r_closed)
                wins = sum(1 for d in r_closed if float(d.profit) > 0)
                state["today_pl"]     = round(today_pl, 2)
                state["today_wins"]   = wins
                state["today_trades"] = len(r_closed)
                # Last 14 days totals
                all_deals = mt5.history_deals_get(datetime.now() - _td(days=14), datetime.now()) or []
                r_all = [d for d in all_deals if int(d.magic) == 20260605 and int(d.entry) == 1]
                state["total_trades"] = len(r_all)
                state["total_wins"]   = sum(1 for d in r_all if float(d.profit) > 0)
                state["total_pl"]     = round(sum(float(d.profit) + float(d.swap) + float(d.commission) for d in r_all), 2)
                # Consecutive losses from most-recent backwards
                consec = 0
                for d in sorted(r_all, key=lambda x: -x.time):
                    if float(d.profit) < 0: consec += 1
                    else: break
                state["consec_losses"] = consec
            except Exception as e:
                state["counter_err"] = str(e)
        # Also expose paper position (with live unrealized P/L)
        pp = state.get("paper_open")
        if pp and HAS_MT5:
            try:
                t = mt5.symbol_info_tick("XAUUSDm")
                if t:
                    bid, ask = t.bid, t.ask
                    if pp["side"] == "BUY":
                        unreal = (bid - pp["entry"]) * pp["lot"] * 100
                        cur = bid
                    else:
                        unreal = (pp["entry"] - ask) * pp["lot"] * 100
                        cur = ask
                    state["paper_position_live"] = {
                        **pp, "current": cur, "unrealized_pl": round(unreal, 2),
                    }
            except Exception: pass
        return jsonify(state)
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})


@app.route("/api/r/trades")
def api_r_trades():
    """Recent R trades from CSV."""
    csv_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_trades.csv")
    if not csv_path.exists():
        return jsonify({"trades": [], "count": 0})
    try:
        import csv as _csv
        rows = []
        with open(csv_path, encoding="utf-8") as f:
            for r in _csv.DictReader(f):
                rows.append(r)
        return jsonify({"trades": rows[-40:][::-1], "count": len(rows)})
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)})


@app.route("/api/r/symbols")
def api_r_symbols():
    """Ranked list of tradeable symbols + blacklist/whitelist."""
    try:
        from friday_v3.algory.r_multi_symbol import rank_symbols, get_book_summary
        ranking = rank_symbols(max_symbols=30)
        ranking["book"] = get_book_summary()
        return jsonify(ranking)
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/r/training")
def api_r_training():
    """Training session — when market closed, R simulates today and learns."""
    try:
        from friday_v3.algory.r_training import run_training_session, is_market_open
        force = request.args.get("force") == "1"
        # If market is open and not forced, return cached/skip
        symbol = request.args.get("symbol", "XAUUSDm")
        if not force and is_market_open(symbol):
            return jsonify({"ok": True, "status": "market_open",
                            "message": "Training runs automatically when markets close. Use ?force=1 to run anyway."})
        return jsonify(run_training_session(symbol))
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/r/levels")
def api_r_levels():
    """Chart-read levels: PDH/PDL, VWAP+bands, swings, FVGs, round numbers."""
    try:
        from friday_v3.algory.r_levels import compute_all_levels
        sym = request.args.get("symbol", "XAUUSDm")
        return jsonify(compute_all_levels(sym))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


_spark_cache: dict = {}
_SPARK_TTL_S = 60


@app.route("/api/r/sparkline")
def api_r_sparkline():
    """Lightweight closes series for per-symbol sparklines in scanner UI.
    Defaults: 30 H1 bars. Cached per (symbol,tf,n) for 60s to spare MT5."""
    sym = request.args.get("symbol", "").strip()
    tf_name = request.args.get("tf", "H1").upper()
    try:
        n = max(8, min(120, int(request.args.get("n", "30"))))
    except ValueError:
        n = 30
    if not sym:
        return jsonify({"ok": False, "error": "missing symbol"})
    if not HAS_MT5:
        return jsonify({"ok": False, "error": "no mt5"})
    tf_map = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(tf_name, mt5.TIMEFRAME_H1)
    key = (sym, tf_name, n)
    now = time.time()
    cached = _spark_cache.get(key)
    if cached and (now - cached["ts"]) < _SPARK_TTL_S:
        return jsonify(cached["data"])
    try:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if rates is None or len(rates) < 4:
            if _ensure_mt5_alive():
                rates = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if rates is None or len(rates) < 4:
            return jsonify({"ok": False, "error": "no bars"})
        closes = [round(float(r["close"]), 5) for r in rates]
        last = closes[-1]
        first = closes[0]
        pct = ((last - first) / first * 100.0) if first else 0.0
        data = {
            "ok": True,
            "symbol": sym,
            "tf": tf_name,
            "closes": closes,
            "lo": min(closes),
            "hi": max(closes),
            "first": first,
            "last": last,
            "pct": round(pct, 3),
        }
        _spark_cache[key] = {"ts": now, "data": data}
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/learning")
def api_r_learning():
    """R's adaptive learning state: per-archetype stats, recent trades,
    user overrides, current template adjustments."""
    try:
        from friday_v3.algory.r_learning import get_learning_summary
        return jsonify(get_learning_summary())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────
# /api/r/equity_curve — snapshot balance/equity to JSONL and return last 24h.
# Called by /r/ UI every 10s; writes one row per call (deduped to ≥30s apart).
# File: data/r_equity_history.jsonl  (one JSON per line: ts, bal, eq, profit)
# ─────────────────────────────────────────────────────────────────────────
_EQUITY_LOG = Path("data") / "r_equity_history.jsonl"
_equity_last_write_ts = 0.0

@app.route("/api/r/equity_curve")
def api_r_equity_curve():
    global _equity_last_write_ts
    try:
        hours = max(1, min(72, int(request.args.get("hours", "24"))))
    except ValueError:
        hours = 24

    # ── snapshot current account (best-effort) and append if ≥30s elapsed
    now_ts = time.time()
    if HAS_MT5 and (now_ts - _equity_last_write_ts) >= 30.0:
        try:
            info = mt5.account_info()
            if info:
                _EQUITY_LOG.parent.mkdir(parents=True, exist_ok=True)
                row = {
                    "ts":     datetime.now().isoformat(timespec="seconds"),
                    "bal":    round(float(info.balance), 2),
                    "eq":     round(float(info.equity), 2),
                    "profit": round(float(info.profit), 2),
                }
                with _EQUITY_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
                _equity_last_write_ts = now_ts
        except Exception:
            pass  # snapshot is best-effort; still return whatever history exists

    # ── read history, filter to last N hours
    points = []
    if _EQUITY_LOG.exists():
        cutoff = datetime.now().timestamp() - hours * 3600
        try:
            with _EQUITY_LOG.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line: continue
                    try:
                        r = json.loads(line)
                        # ts → epoch (cheap re-parse; ISO is sortable but we need filter)
                        try:
                            t_epoch = datetime.fromisoformat(r["ts"]).timestamp()
                        except Exception:
                            continue
                        if t_epoch < cutoff: continue
                        points.append({
                            "ts":  r["ts"],
                            "t":   int(t_epoch),
                            "bal": r.get("bal", 0),
                            "eq":  r.get("eq", 0),
                        })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"ok": False, "error": f"read failed: {e}"})

    # ── compute min/max/delta for chart auto-scale
    eqs = [p["eq"] for p in points] or [0]
    first_eq = points[0]["eq"] if points else 0
    last_eq  = points[-1]["eq"] if points else 0
    return jsonify({
        "ok":         True,
        "hours":      hours,
        "count":      len(points),
        "points":     points,
        "eq_min":     min(eqs),
        "eq_max":     max(eqs),
        "eq_first":   first_eq,
        "eq_last":    last_eq,
        "eq_delta":   round(last_eq - first_eq, 2),
    })


@app.route("/api/r/full")
def api_r_full():
    """Single rich snapshot for the R Factory UI — combines account, executor,
    positions, recent trades, algory, multi_tf, news, regime — one HTTP call."""
    out = {"ts": datetime.now().isoformat()}
    try:
        with app.test_client() as tc:
            out["executor"] = (tc.get("/api/r/executor").get_json() or {})
            out["account"]  = (tc.get("/api/account?hours=24").get_json() or {})
            out["algory"]   = (tc.get("/api/algory").get_json() or {})

        # Per-magic-20260605 closed-trade history (last 14 days)
        recent_r_trades = []
        if HAS_MT5:
            try:
                _ensure_mt5_alive()
                from datetime import timedelta as _td
                deals = mt5.history_deals_get(datetime.now() - _td(days=14), datetime.now()) or []
                r_deals = [d for d in deals if int(d.magic) == 20260605]
                # Pair entries with exits by position_id
                positions = {}
                for d in r_deals:
                    pid = int(d.position_id)
                    positions.setdefault(pid, []).append(d)
                for pid, ds in positions.items():
                    if len(ds) < 2: continue
                    ds = sorted(ds, key=lambda x: x.time)
                    in_d, out_d = ds[0], ds[-1]
                    recent_r_trades.append({
                        "position_id":  pid,
                        "side":         "BUY" if in_d.type == 0 else "SELL",
                        "open_price":   float(in_d.price),
                        "close_price":  float(out_d.price),
                        "open_time":    int(in_d.time),
                        "close_time":   int(out_d.time),
                        "open_ts":      datetime.fromtimestamp(in_d.time).isoformat(),
                        "close_ts":     datetime.fromtimestamp(out_d.time).isoformat(),
                        "profit":       round(float(out_d.profit) + float(out_d.swap) + float(out_d.commission), 2),
                        "duration_min": round((out_d.time - in_d.time) / 60, 1),
                        "comment":      str(out_d.comment or in_d.comment or ""),
                    })
                recent_r_trades.sort(key=lambda x: -x["close_time"])
            except Exception as e:
                out["trades_err"] = str(e)
        out["recent_trades"] = recent_r_trades[:30]

        return jsonify(out)
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/r/trade_gate")
def api_r_trade_gate():
    """R's exact decision on whether to enter a trade RIGHT NOW.

    ADVISORY ONLY — never sends orders. Returns full check breakdown.
    """
    try:
        from friday_v3.algory.trade_gate import evaluate_gate
        # Symbol from URL (default XAUUSDm) — CRITICAL for multi-symbol trading
        target_symbol = request.args.get("symbol", "XAUUSDm")
        snap = {"symbol": target_symbol}
        # Account
        with app.test_client() as tc:
            acc_r = tc.get("/api/account?hours=24")
            snap["account"] = acc_r.get_json() if acc_r.status_code == 200 else {}
        # Regime (always uses default symbol — keep simple)
        regime_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\regime.json")
        if regime_path.exists():
            try: snap["regime"] = json.loads(regime_path.read_text(encoding="utf-8"))
            except Exception: snap["regime"] = {}
        else:
            with app.test_client() as tc:
                rr = tc.get("/api/regime")
                snap["regime"] = rr.get_json() if rr.status_code == 200 else {}
        # Multi-TF for the TARGET symbol (not hardcoded XAU!)
        mtf_data = {}
        if HAS_MT5:
            tfs = [("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15),
                   ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4)]
            for label, tf in tfs:
                mtf_data[label] = _quick_tf_snapshot(target_symbol, tf, 60)
        snap["multi_tf"] = {"tfs": mtf_data}
        # Chart levels for the TARGET symbol
        chart_levels = {}
        if HAS_MT5:
            try:
                t = mt5.symbol_info_tick(target_symbol); s = mt5.symbol_info(target_symbol)
                if t and s:
                    chart_levels = {"bid": t.bid, "ask": t.ask,
                                    "spread_points": round((t.ask - t.bid) / s.point, 0)}
            except Exception: pass
        snap["chart"] = {"levels": chart_levels}
        # News
        news_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\news_calendar.json")
        news_events = []
        if news_path.exists():
            try: news_events = json.loads(news_path.read_text(encoding="utf-8")).get("events", [])
            except Exception: pass

        bypass = {
            "session": request.args.get("bypass_session", "0") == "1",
            "weekend": request.args.get("bypass_weekend", "0") == "1",
            "friday":  request.args.get("bypass_friday",  "0") == "1",
        }
        verdict = evaluate_gate(snap, news_events, bypass=bypass)
        return jsonify(verdict.to_dict())
    except Exception as e:
        import traceback
        return jsonify({"verdict": "ERROR", "reason_ar": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/r/multi_tf_strategies")
def api_r_multi_tf():
    """For each TF (M5/M15/H1/H4), produce strategy guidance based on Algory wisdom.

    Avoids nested test_client by calling multi-tf snapshot helper directly.
    """
    try:
        from friday_v3.algory.strategy_mirror import evaluate_setup
        symbol = request.args.get("symbol", "XAUUSDm")

        # Build multi_tf locally without test_client
        mtf_data = {}
        if HAS_MT5:
            tfs = [("M5", mt5.TIMEFRAME_M5),
                   ("M15", mt5.TIMEFRAME_M15),
                   ("H1", mt5.TIMEFRAME_H1),
                   ("H4", mt5.TIMEFRAME_H4)]
            for label, tf in tfs:
                mtf_data[label] = _quick_tf_snapshot(symbol, tf, 60)

        # Pull regime once
        regime = _json(Path(r"C:\Users\Radhi\MT5\friday_v3\data\regime.json"), {})

        # Chart levels — read MT5 tick directly
        chart_levels = {}
        if HAS_MT5:
            try:
                t = mt5.symbol_info_tick(symbol)
                s = mt5.symbol_info(symbol)
                if t and s:
                    chart_levels = {
                        "bid":   t.bid, "ask": t.ask,
                        "spread_points": round((t.ask - t.bid) / s.point, 0),
                    }
            except Exception: pass

        result = {}
        for tf in ("M5", "M15", "H1", "H4"):
            tf_info = mtf_data.get(tf, {})
            # Build a per-TF snapshot that puts THIS TF's data in the H1 slot
            # so evaluate_setup uses this frame's bias/ATR for the archetype
            # match check.
            per_tf_snap = {
                "multi_tf": {"tfs": {**mtf_data, "H1": tf_info if tf_info.get("ok") else mtf_data.get("H1", {})}},
                "regime":   regime,
                "chart":    {"levels": chart_levels},
            }
            evals = {}
            for arch in ("BREAKOUT_HUNTER", "MEAN_REVERTER", "MULTI_SIGNAL", "PATTERN_SPOTTER"):
                ev = evaluate_setup(per_tf_snap, arch)
                evals[arch] = {
                    "verdict": ev["verdict"],
                    "score":   ev["score"],
                    "bias":    ev.get("bias_h1"),
                    "checks_failed": [k for k, v in (ev.get("checks") or {}).items() if not v],
                }
            best = max(evals.items(), key=lambda x: x[1]["score"]) if evals else (None, None)
            result[tf] = {
                "tf_data":   tf_info,
                "archetype_eval": evals,
                "best_archetype": best[0],
                "best_score":     best[1]["score"] if best[1] else 0,
            }
        return jsonify({"ok": True, "ts": datetime.now().isoformat(),
                        "frames": result})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/algory/strategy")
def api_algory_strategy():
    """FRIDAY's adopted strategy recommendations based on Algory's OOS history."""
    try:
        from friday_v3.algory.strategy_mirror import get_active_recommendation, evaluate_setup
        symbol = request.args.get("symbol", "XAUUSDm")
        tf     = request.args.get("tf", "H1")
        rec = get_active_recommendation(symbol, tf)

        # Also evaluate current market setup vs each archetype
        with app.test_client() as tc:
            snap_resp = tc.get("/api/snapshot")
            snap = snap_resp.get_json() if snap_resp.status_code == 200 else {}
        rec["setup_evaluation"] = {
            arch: evaluate_setup(snap, arch)
            for arch in ("BREAKOUT_HUNTER", "MEAN_REVERTER", "MULTI_SIGNAL", "PATTERN_SPOTTER")
        }
        return jsonify(rec)
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "tb": traceback.format_exc()[:300]})


@app.route("/api/algory")
def api_algory():
    """Read-only Algory factory snapshot — vault, gene fitness, recommendations."""
    report_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\algory_report.json")
    if not report_path.exists():
        # Build on demand if watcher hasn't run yet
        try:
            from friday_v3.algory.algory_watcher import build_report, mirror_vault_index
            r = build_report()
            mirror_vault_index()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            return jsonify(r)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    # Check freshness — if older than 60s, rebuild
    try:
        age = (datetime.now().timestamp() - report_path.stat().st_mtime)
        if age > 60:
            from friday_v3.algory.algory_watcher import build_report, mirror_vault_index
            r = build_report()
            mirror_vault_index()
            report_path.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            return jsonify(r)
        return jsonify(_json(report_path, {}))
    except Exception as e:
        return jsonify(_json(report_path, {"error": str(e)}))


@app.route("/api/vault")
def api_vault():
    """PlutoBrain session cache."""
    return jsonify({
        "hot":      _text(VAULT / "hot.md", 1200),
        "log_tail": _text(VAULT / "log.md", 600),
        "updated":  datetime.now().isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────
# /api/account — READ-ONLY live account snapshot + recent deals.
# Used by dashboard to show what the EA actually did (no execution side-effects).
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/account")
def api_account():
    if not HAS_MT5:
        return jsonify({"ok": False, "reason": "MT5 not initialized"})
    try:
        from datetime import timedelta as _td
        info = mt5.account_info()
        if not info:
            # Try a single reconnect — MT5 IPC can drop
            try:
                mt5.shutdown()
            except Exception: pass
            if not mt5.initialize():
                return jsonify({"ok": False, "reason": f"reinit failed: {mt5.last_error()}"})
            info = mt5.account_info()
            if not info:
                return jsonify({"ok": False, "reason": f"account_info failed after reinit: {mt5.last_error()}"})

        # Currently open positions (across all symbols)
        positions = []
        for p in (mt5.positions_get() or []):
            positions.append({
                "ticket":  p.ticket,
                "symbol":  p.symbol,
                "type":    "BUY" if p.type == 0 else "SELL",
                "volume":  float(p.volume),
                "price_open":    float(p.price_open),
                "price_current": float(p.price_current),
                "sl":      float(p.sl),
                "tp":      float(p.tp),
                "profit":  float(p.profit),
                "swap":    float(p.swap),
                "magic":   int(p.magic),
                "comment": str(p.comment or ""),
                "time":    int(p.time),
            })

        # Recent deals — configurable window (default 7 days = 168h)
        from flask import request as _req
        hours = int(_req.args.get("hours", 168))
        from_dt = datetime.now() - _td(hours=hours)
        to_dt   = datetime.now()
        deals = mt5.history_deals_get(from_dt, to_dt) or []
        recent = []
        # We only care about "OUT" deals (closing legs) for P/L attribution
        for d in sorted(deals, key=lambda x: x.time, reverse=True)[:40]:
            recent.append({
                "ticket":  int(d.ticket),
                "order":   int(d.order),
                "symbol":  str(d.symbol),
                "type":    "BUY" if d.type == 0 else "SELL" if d.type == 1 else "OTHER",
                "entry":   int(d.entry),     # 0=in, 1=out, 2=inout
                "volume":  float(d.volume),
                "price":   float(d.price),
                "profit":  float(d.profit),
                "commission": float(d.commission),
                "swap":    float(d.swap),
                "magic":   int(d.magic),
                "comment": str(d.comment or ""),
                "time":    int(d.time),
                "ts_iso":  datetime.fromtimestamp(int(d.time)).isoformat(),
            })

        # Group closed-trade P/L per magic for quick attribution
        by_magic = {}
        for d in recent:
            if d["entry"] != 1: continue   # closing legs only
            m = d["magic"]
            agg = by_magic.setdefault(m, {"magic": m, "trades": 0, "wins": 0,
                                          "net_profit": 0.0, "symbols": set()})
            agg["trades"]    += 1
            agg["net_profit"]+= d["profit"] + d["swap"] + d["commission"]
            if d["profit"] > 0: agg["wins"] += 1
            agg["symbols"].add(d["symbol"])
        # serialize sets
        attribution = []
        for m, v in by_magic.items():
            v["symbols"] = sorted(list(v["symbols"]))
            v["win_rate"] = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0
            v["net_profit"] = round(v["net_profit"], 2)
            attribution.append(v)
        attribution.sort(key=lambda x: -x["net_profit"])

        return jsonify({
            "ok": True,
            "ts": datetime.now().isoformat(),
            "account": {
                "login":    info.login,
                "server":   info.server,
                "currency": info.currency,
                "balance":  round(info.balance, 2),
                "equity":   round(info.equity, 2),
                "profit":   round(info.profit, 2),
                "margin":   round(info.margin, 2),
                "margin_free": round(info.margin_free, 2),
                "leverage": info.leverage,
                "trade_allowed": bool(info.trade_allowed),
            },
            "positions":   positions,
            "positions_count": len(positions),
            "open_pnl":    round(sum(p["profit"] for p in positions), 2),
            "recent_deals": recent,
            "deals_window_hours": hours,
            "attribution_by_magic": attribution,
        })
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)})


@app.route("/api/sessions")
def api_sessions():
    """Last 10 Claude AI agent sessions from vault inbox."""
    inbox = VAULT / "inbox"
    sessions = []
    if inbox.exists():
        files = sorted(inbox.glob("*-agent-session.md"), reverse=True)[:10]
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
                sessions.append({
                    "file":    f.name,
                    "ts":      f.stem[:15],
                    "preview": content[:300],
                })
            except Exception:
                pass
    return jsonify(sessions)


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events: push swarm updates every 2s."""
    def generate():
        while True:
            for p in [MT5_DATA / "friday_agents.json", MT5_ROOT / "friday_agents.json"]:
                if p.exists():
                    data = _json(p, {})
                    state = swarm_to_state(data)
                    yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                    break
            else:
                yield f"data: {json.dumps({'error': 'swarm not running'})}\n\n"
            time.sleep(2)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/stream/footprint")
def api_stream_footprint():
    """Server-Sent Events: push real-time footprint data every 1s.
    Clients receive the latest friday_footprint.json as it's written by the engine.
    """
    def generate():
        last_ts = None
        while True:
            try:
                if FOOTPRINT_FILE.exists():
                    mtime = FOOTPRINT_FILE.stat().st_mtime
                    if mtime != last_ts:
                        last_ts = mtime
                        data = _json(FOOTPRINT_FILE, {})
                        # Send only the last 5 bars + summary to keep payload small
                        if "bars" in data and data["bars"]:
                            payload = {
                                "ts":            data.get("ts"),
                                "symbol":        data.get("symbol"),
                                "tick_size":     data.get("tick_size"),
                                "contract_size": data.get("contract_size"),
                                "vol_is_real":   data.get("vol_is_real"),
                                "cum_vol_usd":   data.get("cum_vol_usd"),
                                "session_poc":   data.get("session_poc"),
                                "vah":           data.get("vah"),
                                "val":           data.get("val"),
                                "total_ticks":   data.get("total_ticks"),
                                "last_bar":      data["bars"][-1],
                                "bars":          data["bars"][-20:],
                                "volume_profile": data.get("volume_profile", [])[:30],
                            }
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'status': 'no_bars'})}\n\n"
                    else:
                        # heartbeat every 5s if no new data
                        yield f": heartbeat\n\n"
                else:
                    yield f"data: {json.dumps({'status': 'footprint_engine_not_running'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Per-Genome Live Performance Chart ─────────────────────────────────────────
HOF_INDEX_FILE   = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
DECISION_LOG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\decision_log")


def _load_hof_index() -> dict:
    try:
        if HOF_INDEX_FILE.exists():
            return json.loads(HOF_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[genome-page] hof load failed: {e}")
    return {}


def _load_decisions(gid: str, since_iso: str | None = None) -> list[dict]:
    """Read jsonl, pair OPEN/CLOSE by ticket, return trade rows."""
    fp = DECISION_LOG_DIR / f"{gid}.jsonl"
    if not fp.exists():
        return []
    opens: dict = {}
    closes: dict = {}
    try:
        for ln in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = ln.strip()
            if not ln: continue
            try:
                row = json.loads(ln)
            except Exception:
                continue
            kind = row.get("kind")
            tk = row.get("ticket")
            if tk is None: continue
            if kind == "OPEN":
                opens[tk] = row
            elif kind == "CLOSE":
                closes[tk] = row
    except Exception as e:
        print(f"[genome-page] decisions parse failed {gid}: {e}")
        return []
    out = []
    for tk, op in opens.items():
        cl = closes.get(tk, {})
        out.append({
            "ticket": tk,
            "ts_open": op.get("ts"),
            "ts_close": cl.get("ts"),
            "symbol": op.get("symbol"),
            "side": op.get("side"),
            "entry": op.get("entry"),
            "sl": op.get("sl"),
            "tp": op.get("tp"),
            "lot": op.get("lot"),
            "exit_price": cl.get("exit_price"),
            "profit": cl.get("profit"),
            "exit_reason": cl.get("exit_reason"),
            "confidence": op.get("confidence"),
            "archetype": op.get("archetype"),
            "signals_fired": op.get("signals_fired", []),
            "biases_aligned": op.get("biases_aligned", []),
            "filters_blocking": op.get("filters_blocking", []),
            "indicators": op.get("indicators", {}),
        })
    if since_iso:
        out = [d for d in out if (d.get("ts_open") or "") >= since_iso]
    out.sort(key=lambda d: d.get("ts_open") or "")
    return out


@app.route("/api/r/genome/<gid>/info")
def api_r_genome_info(gid):
    idx = _load_hof_index()
    entry = idx.get(gid)
    if not entry:
        return jsonify({"ok": False, "error": "unknown genome"}), 404
    return jsonify({"ok": True, "genome": entry})


@app.route("/api/r/genome/<gid>/decisions")
def api_r_genome_decisions(gid):
    since = request.args.get("since")
    rows = _load_decisions(gid, since)
    return jsonify({"ok": True, "genome_id": gid, "count": len(rows), "decisions": rows})


@app.route("/api/r/genome/<gid>/bars")
def api_r_genome_bars(gid):
    sym = (request.args.get("symbol") or "").strip()
    tf_name = (request.args.get("tf") or "H1").upper()
    try:
        n = max(50, min(2000, int(request.args.get("n", "500"))))
    except ValueError:
        n = 500
    if not sym:
        return jsonify({"ok": False, "error": "missing symbol"})
    if not HAS_MT5:
        return jsonify({"ok": False, "error": "no mt5"})
    tf_map = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(tf_name, mt5.TIMEFRAME_H1)
    try:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if rates is None or len(rates) < 4:
            if _ensure_mt5_alive():
                rates = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if rates is None or len(rates) < 4:
            return jsonify({"ok": False, "error": "no bars"})
        bars = [{
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low":  float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["tick_volume"]),
        } for r in rates]
        return jsonify({"ok": True, "symbol": sym, "tf": tf_name, "bars": bars})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


_GENOME_PAGE_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Genome __GID__ — Live Performance</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root{--bg0:#0a0a0f;--bg1:#13131a;--bg2:#1a1a23;--gold:#f5a524;--green:#22c55e;--red:#ef4444;--text:#ededf0;--muted:#9494a0;}
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:var(--bg0);color:var(--text);font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:13px;height:100%}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  a{color:var(--gold);text-decoration:none}
  a:hover{text-decoration:underline}
  .topbar{display:flex;align-items:center;gap:16px;padding:10px 16px;background:var(--bg1);border-bottom:1px solid #222}
  .topbar h1{font-size:15px;margin:0;font-weight:600}
  .topbar h1 b{color:var(--gold)}
  .kpis{display:flex;gap:14px;padding:10px 16px;background:var(--bg1);border-bottom:1px solid #222;flex-wrap:wrap}
  .kpi{background:var(--bg2);border:1px solid #25252e;padding:8px 12px;border-radius:6px;min-width:90px}
  .kpi .lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  .kpi .val{font-size:16px;font-weight:600;margin-top:2px}
  .kpi .val.pos{color:var(--green)} .kpi .val.neg{color:var(--red)} .kpi .val.gold{color:var(--gold)}
  .controls{display:flex;gap:10px;padding:8px 16px;background:var(--bg1);border-bottom:1px solid #222;align-items:center}
  .controls label{color:var(--muted);font-size:11px;text-transform:uppercase}
  .controls select,.controls button{background:var(--bg2);color:var(--text);border:1px solid #2a2a35;border-radius:4px;padding:5px 10px;font-size:12px;cursor:pointer}
  .controls select:hover,.controls button:hover{border-color:var(--gold)}
  .layout{display:flex;height:calc(100vh - 130px);min-height:500px}
  #chart{flex:1;background:var(--bg0);position:relative}
  #chart .empty{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:var(--muted);font-size:14px;pointer-events:none}
  .panel{width:380px;background:var(--bg1);border-left:1px solid #222;overflow-y:auto;padding:14px}
  .panel.collapsed{width:32px;padding:14px 4px;overflow:hidden}
  .panel-toggle{background:var(--bg2);border:1px solid #2a2a35;color:var(--text);padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px;width:100%;margin-bottom:10px}
  .panel h3{margin:0 0 8px 0;font-size:12px;color:var(--gold);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #25252e;padding-bottom:4px}
  .panel .empty-state{color:var(--muted);font-style:italic;padding:20px 0;text-align:center}
  .trade-header{background:var(--bg2);padding:10px;border-radius:6px;margin-bottom:12px}
  .trade-header .row{display:flex;justify-content:space-between;padding:2px 0;font-size:12px}
  .trade-header .row .k{color:var(--muted)}
  .trade-header .row .v.pos{color:var(--green)} .trade-header .row .v.neg{color:var(--red)}
  .side-badge{display:inline-block;padding:2px 8px;border-radius:3px;font-weight:600;font-size:11px}
  .side-badge.buy{background:#0d4d2a;color:var(--green)}
  .side-badge.sell{background:#4d0d18;color:var(--red)}
  .confbar{height:6px;background:var(--bg2);border-radius:3px;overflow:hidden;margin:6px 0 12px 0}
  .confbar .fill{height:100%;background:linear-gradient(90deg,var(--red),var(--gold),var(--green))}
  .section{margin-bottom:12px}
  .section ul{list-style:none;padding:0;margin:4px 0}
  .section li{padding:4px 8px;background:var(--bg2);border-radius:3px;margin-bottom:3px;font-size:11px;border-left:2px solid var(--bg2)}
  .section li.signal{border-left-color:var(--green)}
  .section li.bias{border-left-color:var(--gold)}
  .section li.filter{border-left-color:var(--red)}
  .section li b{color:var(--gold)}
  .ind-table{width:100%;border-collapse:collapse;font-size:11px}
  .ind-table th,.ind-table td{padding:4px 6px;text-align:right;border-bottom:1px solid #222}
  .ind-table th{color:var(--muted);font-weight:normal;text-align:left;text-transform:uppercase;font-size:10px}
  .ind-table td:first-child{text-align:left;color:var(--muted)}
  .ind-table tr.h1 td.hi{background:#2a2010;color:var(--gold)}
</style>
</head><body>
<div class="topbar">
  <a href="/r/">&larr; back</a>
  <h1>Genome <b>__GID__</b> — Live Performance</h1>
  <span id="nick" style="color:var(--muted);font-size:11px"></span>
</div>
<div class="kpis" id="kpis"></div>
<div class="controls">
  <label>Symbol</label><select id="symSel"></select>
  <label>TF</label>
  <select id="tfSel">
    <option>M5</option><option>M15</option><option selected>H1</option><option>H4</option>
  </select>
  <button id="reload">Reload</button>
  <span id="status" style="color:var(--muted);font-size:11px;margin-left:auto"></span>
</div>
<div class="layout">
  <div id="chart"><div class="empty" id="chartEmpty">Loading chart&hellip;</div></div>
  <div class="panel" id="panel">
    <button class="panel-toggle" id="panelToggle">collapse &raquo;</button>
    <div id="panelBody"><div class="empty-state">Click any marker on the chart to inspect that trade&rsquo;s reasoning.</div></div>
  </div>
</div>
<script>
const GID = "__GID__";
const $ = (id)=>document.getElementById(id);
let chart, series, decisions=[], decByTime={}, currentSymbol=null;

function fmt(v, d=2){ if(v===null||v===undefined||isNaN(v)) return "—"; return Number(v).toFixed(d); }
function tsToUnix(s){ if(!s) return null; const t=Math.floor(new Date(s).getTime()/1000); return isNaN(t)?null:t; }

async function loadInfo(){
  const r = await fetch(`/api/r/genome/${GID}/info`);
  if(!r.ok){ $("kpis").innerHTML = `<div class="kpi"><div class="lbl">error</div><div class="val neg">genome not found</div></div>`; return null; }
  const j = await r.json();
  return j.genome;
}

function renderKpis(info, decs){
  const live_pnl = info?.live_pnl ?? 0;
  const live_trades = info?.live_trades ?? 0;
  const closedDecs = decs.filter(d=>d.profit!=null);
  const live_wins = closedDecs.filter(d=>d.profit>0).length;
  const wr = closedDecs.length ? (live_wins/closedDecs.length*100) : 0;
  const counts = {};
  decs.forEach(d=>{ if(d.symbol) counts[d.symbol] = (counts[d.symbol]||0)+1; });
  const best_symbol = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0]?.[0] || info?.symbol || "—";
  const pf = info?.stats?.profit_factor ?? "—";
  const pnlCls = live_pnl>0?"pos":live_pnl<0?"neg":"";
  $("kpis").innerHTML = `
    <div class="kpi"><div class="lbl">Live PnL</div><div class="val mono ${pnlCls}">${fmt(live_pnl,2)}</div></div>
    <div class="kpi"><div class="lbl">Live Trades</div><div class="val mono">${live_trades}</div></div>
    <div class="kpi"><div class="lbl">Live Wins</div><div class="val mono">${live_wins} (${fmt(wr,1)}%)</div></div>
    <div class="kpi"><div class="lbl">Best Symbol</div><div class="val gold">${best_symbol}</div></div>
    <div class="kpi"><div class="lbl">PF (backtest)</div><div class="val mono">${pf}</div></div>
    <div class="kpi"><div class="lbl">Archetype</div><div class="val gold" style="font-size:13px">${info?.archetype||"—"}</div></div>
  `;
  $("nick").textContent = info?.nickname || "";
}

function populateSymbols(decs, fallback){
  const counts = {};
  decs.forEach(d=>{ if(d.symbol) counts[d.symbol]=(counts[d.symbol]||0)+1; });
  let syms = Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(x=>x[0]);
  if(syms.length===0 && fallback) syms = [fallback];
  const sel = $("symSel");
  sel.innerHTML = syms.map(s=>`<option value="${s}">${s} (${counts[s]||0})</option>`).join("") || `<option value="">—</option>`;
  return syms[0];
}

function initChart(){
  const el = $("chart");
  chart = LightweightCharts.createChart(el, {
    layout: { background:{ color:"#0a0a0f" }, textColor:"#ededf0" },
    grid: { vertLines:{ color:"#1a1a23" }, horzLines:{ color:"#1a1a23" } },
    timeScale: { timeVisible:true, secondsVisible:false, borderColor:"#25252e" },
    rightPriceScale: { borderColor:"#25252e" },
    crosshair: { mode: 1 },
    width: el.clientWidth, height: el.clientHeight,
  });
  series = chart.addCandlestickSeries({
    upColor:"#22c55e", downColor:"#ef4444", borderUpColor:"#22c55e",
    borderDownColor:"#ef4444", wickUpColor:"#22c55e", wickDownColor:"#ef4444",
  });
  window.addEventListener("resize", ()=>chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));

  // Click handler: find nearest decision to clicked time
  chart.subscribeClick((param)=>{
    if(!param.time) return;
    const t = typeof param.time === "object" ? param.time.timestamp : param.time;
    let best=null, bestDelta=Infinity;
    Object.entries(decByTime).forEach(([k,d])=>{
      const dd = Math.abs(Number(k)-t);
      if(dd<bestDelta){ bestDelta=dd; best=d; }
    });
    if(best && bestDelta < 24*3600) renderTrade(best);
  });
}

async function loadBars(symbol, tf){
  $("status").textContent = "loading bars…";
  const r = await fetch(`/api/r/genome/${GID}/bars?symbol=${encodeURIComponent(symbol)}&tf=${tf}&n=500`);
  const j = await r.json();
  if(!j.ok){ $("status").textContent = "bars error: "+(j.error||"?"); return; }
  const data = j.bars.map(b=>({ time:b.time, open:b.open, high:b.high, low:b.low, close:b.close }));
  series.setData(data);
  $("status").textContent = `${data.length} ${tf} bars`;
  applyMarkers(symbol);
}

function applyMarkers(symbol){
  decByTime = {};
  const markers = [];
  decisions.filter(d=>d.symbol===symbol && d.ts_open).forEach(d=>{
    const t = tsToUnix(d.ts_open);
    if(!t) return;
    decByTime[t] = d;
    const isBuy = (d.side||"").toUpperCase()==="BUY";
    const conf = d.confidence!=null ? Math.round(d.confidence*100>1?d.confidence:d.confidence*100) : null;
    markers.push({
      time: t,
      position: isBuy ? "belowBar" : "aboveBar",
      color: isBuy ? "#22c55e" : "#ef4444",
      shape: isBuy ? "arrowUp" : "arrowDown",
      text: (isBuy?"B":"S") + (conf!=null?conf+"%":""),
    });
  });
  markers.sort((a,b)=>a.time-b.time);
  series.setMarkers(markers);
}

function renderTrade(d){
  const isBuy = (d.side||"").toUpperCase()==="BUY";
  const profit = d.profit;
  const pCls = profit==null?"":(profit>0?"pos":"neg");
  const conf = d.confidence!=null ? (d.confidence>1?d.confidence:d.confidence*100) : 0;
  const sigList = (d.signals_fired||[]).map(s=>`<li class="signal"><b>${s.flag||"?"}</b> &nbsp;${s.reason||""} ${s.vote?`<span style="color:var(--muted)">(${s.vote})</span>`:""}</li>`).join("") || `<li style="color:var(--muted)">none</li>`;
  const biasList = (d.biases_aligned||[]).map(s=>{
    if(typeof s==="string") return `<li class="bias"><b>${s}</b></li>`;
    return `<li class="bias"><b>${s.flag||"?"}</b> &nbsp;${s.reason||""}</li>`;
  }).join("") || `<li style="color:var(--muted)">none</li>`;
  const filterList = (d.filters_blocking||[]).map(s=>{
    if(typeof s==="string") return `<li class="filter"><b>${s}</b></li>`;
    return `<li class="filter"><b>${s.flag||"?"}</b> &nbsp;${s.reason||""}</li>`;
  }).join("") || `<li style="color:var(--muted)">none</li>`;

  const ind = d.indicators||{};
  const tfRows = ["h1","h4","m15"].map(tf=>{
    const row = ind[tf]||{};
    const isH1 = tf==="h1";
    return `<tr class="${tf}">
      <td>${tf.toUpperCase()}</td>
      <td class="mono">${fmt(row.current,5)}</td>
      <td class="mono">${fmt(row.atr,5)}</td>
      <td class="mono ${isH1?'hi':''}">${fmt(row.rsi,1)}</td>
      <td class="mono">${row.bias||"—"}</td>
      <td class="mono ${isH1?'hi':''}">${fmt(row.slope,4)}</td>
      <td class="mono">${fmt(row.swing_high,5)}</td>
      <td class="mono">${fmt(row.swing_low,5)}</td>
    </tr>`;
  }).join("");

  $("panelBody").innerHTML = `
    <div class="trade-header">
      <div class="row"><span class="k">Ticket</span><span class="v mono">#${d.ticket||"?"}</span></div>
      <div class="row"><span class="k">Side</span><span class="v"><span class="side-badge ${isBuy?'buy':'sell'}">${(d.side||'?').toUpperCase()}</span> ${d.symbol||''}</span></div>
      <div class="row"><span class="k">Entry</span><span class="v mono">${fmt(d.entry,5)}</span></div>
      <div class="row"><span class="k">SL / TP</span><span class="v mono">${fmt(d.sl,5)} / ${fmt(d.tp,5)}</span></div>
      <div class="row"><span class="k">Exit</span><span class="v mono">${fmt(d.exit_price,5)}</span></div>
      <div class="row"><span class="k">Profit</span><span class="v mono ${pCls}">${fmt(profit,2)}</span></div>
      <div class="row"><span class="k">Exit reason</span><span class="v">${d.exit_reason||"—"}</span></div>
      <div class="row"><span class="k">Opened</span><span class="v mono" style="font-size:11px">${d.ts_open||"—"}</span></div>
    </div>
    <div class="section">
      <h3>Confidence — ${fmt(conf,0)}%</h3>
      <div class="confbar"><div class="fill" style="width:${Math.max(0,Math.min(100,conf))}%"></div></div>
    </div>
    <div class="section"><h3>Signals fired</h3><ul>${sigList}</ul></div>
    <div class="section"><h3>Biases aligned</h3><ul>${biasList}</ul></div>
    <div class="section"><h3>Filters blocking</h3><ul>${filterList}</ul></div>
    <div class="section">
      <h3>Indicators @ entry</h3>
      <table class="ind-table">
        <thead><tr><th>TF</th><th>price</th><th>ATR</th><th>RSI</th><th>bias</th><th>slope</th><th>swH</th><th>swL</th></tr></thead>
        <tbody>${tfRows}</tbody>
      </table>
    </div>
  `;
}

$("panelToggle").addEventListener("click", ()=>{
  const p = $("panel");
  p.classList.toggle("collapsed");
  $("panelToggle").textContent = p.classList.contains("collapsed") ? "«" : "collapse »";
  setTimeout(()=>chart && chart.applyOptions({ width: $("chart").clientWidth }), 50);
});

$("reload").addEventListener("click", ()=>refresh());
$("symSel").addEventListener("change", ()=>{ currentSymbol = $("symSel").value; loadBars(currentSymbol, $("tfSel").value); });
$("tfSel").addEventListener("change", ()=>loadBars($("symSel").value, $("tfSel").value));

async function refresh(){
  const info = await loadInfo();
  const dr = await fetch(`/api/r/genome/${GID}/decisions`).then(r=>r.json()).catch(()=>({decisions:[]}));
  decisions = dr.decisions || [];
  renderKpis(info, decisions);
  const def = populateSymbols(decisions, info?.symbol);
  if(decisions.length===0){
    $("panelBody").innerHTML = `<div class="empty-state">No live decisions yet — make some trades!</div>`;
  }
  if(def){ currentSymbol = def; $("symSel").value = def; await loadBars(def, $("tfSel").value); }
}

initChart();
refresh();
</script>
</body></html>
"""


@app.route("/r/genome/<gid>")
def r_genome_page(gid):
    # basic sanitization — gid should be alnum-ish
    safe = "".join(c for c in gid if c.isalnum() or c in ("-", "_"))[:64]
    html = _GENOME_PAGE_HTML.replace("__GID__", safe)
    return Response(html, mimetype="text/html")


@app.route("/dashboard")
def dashboard_page():
    """Serve the new Mission Control HTML dashboard."""
    from pathlib import Path as _P
    html_path = _P(r"C:\Users\Radhi\MT5\dashboard.html")
    if not html_path.exists():
        return Response("<h1>dashboard.html not found</h1>", status=404,
                        mimetype="text/html")
    return Response(html_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route("/api/r/contenders")
def api_r_contenders():
    """Return the current contender pipeline — genomes validated in shadow,
    awaiting user accept/reject (or auto-promotion)."""
    try:
        from r_native.genome_contender import list_contenders
        return jsonify(list_contenders())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/contenders/<child_id>/accept", methods=["POST"])
def api_r_contender_accept(child_id):
    try:
        from r_native.genome_contender import accept
        return jsonify(accept(child_id))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/contenders/<child_id>/reject", methods=["POST"])
def api_r_contender_reject(child_id):
    try:
        from r_native.genome_contender import reject
        return jsonify(reject(child_id))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/exposure")
def api_r_exposure():
    """Per-symbol exposure snapshot: opens today, net P/L, DD-pause status."""
    try:
        from r_native.exposure_guard import snapshot
        return jsonify({"ok": True, **snapshot()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/monsters")
def api_r_monsters():
    """List qualified monster genomes (sorted by monster_score)."""
    from pathlib import Path as _P
    import json as _j
    mp = _P(r"C:\Users\Radhi\MT5\data\r_native\monster_genomes.json")
    if not mp.exists():
        return jsonify({"ok": True, "monsters": [], "near": [],
                        "note": "run `python -m r_native.monster_genome scan` first"})
    try:
        d = _j.loads(mp.read_text(encoding="utf-8"))
        return jsonify({"ok": True, **d})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/r/genomes/active")
def api_r_genomes_active():
    """List every deployed genome (and ensemble members) across all symbols,
    with current live PnL / live_trades / archetype / kill_protected flag.
    Used by the R Native UI's ACTIVE GENOMES tab and any external watcher.
    """
    from pathlib import Path as _P
    import json as _j
    CFG_DIR = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
    HOF_IDX = _P(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
    DLOG    = _P(r"C:\Users\Radhi\MT5\data\r_native\decision_log")

    try:
        hof = _j.loads(HOF_IDX.read_text(encoding="utf-8")) if HOF_IDX.exists() else {}
    except Exception:
        hof = {}

    out = []
    if CFG_DIR.exists():
        for p in sorted(CFG_DIR.glob("*.json")):
            sym = p.stem
            try:
                cfg = _j.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

            def _stats_for(gid):
                """Pull HoF live stats + count OPEN entries in decision_log."""
                if not gid: return {}
                h = hof.get(gid, {}) or {}
                stats = {
                    "live_pnl":     float(h.get("live_pnl") or 0),
                    "live_trades":  int(h.get("live_trades") or 0),
                    "kill_protected": bool(h.get("kill_protected")),
                    "directional":  h.get("directional_specialist"),
                    "pinned":       bool(h.get("pinned")),
                }
                dl = DLOG / f"{gid}.jsonl"
                if dl.exists():
                    opens = closes = 0
                    last_ts = None
                    try:
                        for line in dl.read_text(encoding="utf-8").splitlines():
                            if not line.strip(): continue
                            try: ev = _j.loads(line)
                            except Exception: continue
                            if ev.get("kind") == "OPEN":  opens += 1
                            if ev.get("kind") == "CLOSE": closes += 1
                            ts = ev.get("ts")
                            if ts and (not last_ts or ts > last_ts): last_ts = ts
                    except Exception: pass
                    stats["decision_log_opens"]  = opens
                    stats["decision_log_closes"] = closes
                    stats["decision_log_last_ts"] = last_ts
                return stats

            row = {
                "symbol":       sym,
                "tradeable":    bool(cfg.get("tradeable")),
                "best_pf":      cfg.get("best_pf"),
                "lot":          cfg.get("lot"),
                "max_concurrent": cfg.get("max_concurrent"),
            }

            dg = cfg.get("deployed_genome")
            if dg and dg.get("id"):
                gid = dg["id"]
                row["deployed_genome"] = {
                    "id":             gid,
                    "profit_factor":  dg.get("profit_factor"),
                    "sl_atr_mult":    dg.get("sl_atr_mult"),
                    "tp_atr_mult":    dg.get("tp_atr_mult"),
                    "start_hour":     dg.get("start_hour"),
                    "end_hour":       dg.get("end_hour"),
                    "active_gene_count": len(dg.get("active_genes") or []),
                    "source":         dg.get("source"),
                    "stats":          _stats_for(gid),
                }

            ens = cfg.get("deployed_genomes")
            if isinstance(ens, list) and ens:
                row["ensemble"] = [
                    {"id": m.get("id"), "weight": m.get("weight"),
                     "stats": _stats_for(m.get("id"))}
                    for m in ens if m.get("id")
                ]
            out.append(row)

    # Also surface any LIVE R-magic position whose symbol isn't in symbol_configs
    # (Algory archetype fallback path) so the user sees ALL active trades.
    seen_syms = {r["symbol"] for r in out}
    try:
        import MetaTrader5 as _mt5
        if not _mt5.initialize(): _mt5.initialize()
        for p in (_mt5.positions_get(magic=20260605) or []):
            if p.symbol in seen_syms: continue
            arch_label = "ALGORY"
            cmt = (p.comment or "")
            if cmt.startswith("R_") and "_" in cmt:
                arch_label = cmt.split("_", 1)[1] or "ALGORY"
            elif cmt.startswith("R-"):
                # R-<gid>-<side>  → orphan genome (not in any config)
                parts = cmt.split("-")
                if len(parts) >= 2: arch_label = f"orphan {parts[1]}"
            out.append({
                "symbol":      p.symbol,
                "tradeable":   True,
                "archetype_fallback": True,
                "live_position": {
                    "ticket":  int(p.ticket),
                    "side":    "BUY" if p.type == 0 else "SELL",
                    "entry":   float(p.price_open),
                    "sl":      float(p.sl),
                    "tp":      float(p.tp),
                    "lot":     float(p.volume),
                    "profit":  float(p.profit),
                    "archetype": arch_label,
                    "comment": cmt,
                },
            })
    except Exception:
        pass
    return jsonify({"ok": True, "count": len(out), "symbols": out})


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  FRIDAY Brain Server")
    print("  ────────────────────────────────────")
    print("  Dashboard:  http://localhost:5055")
    print("  Swarm API:  http://localhost:5055/api/swarm")
    print("  Market API: http://localhost:5055/api/market")
    print("  Vault API:  http://localhost:5055/api/vault")
    print("  Sessions:   http://localhost:5055/api/sessions")
    print("  SSE Stream: http://localhost:5055/api/stream")
    print("  ────────────────────────────────────")
    print("  تأكد من تشغيل friday_agents.py أولاً لبيانات السرب")
    print()

    # Auto-start the continuous-evolution background loop (it only fires if enabled in JSON)
    try:
        from r_native.continuous_evolution import start as _start_evo
        _start_evo()
        print("  🧬 continuous_evolution loop armed (fires when enabled=true)")
    except Exception as _e:
        print(f"  ⚠ continuous_evolution failed to start: {_e}")

    # Auto-start all agents (risk_sentinel, genome_curator, market_reader, performance_auditor)
    try:
        from r_native.agents.orchestrator import start_all as _start_agents
        _start_agents()
        print("  🤖 agent orchestrator started (risk, curator, market, audit)")
    except Exception as _e:
        print(f"  ⚠ agents failed to start: {_e}")

    app.run(host="0.0.0.0", port=5055, debug=False, threaded=True)
