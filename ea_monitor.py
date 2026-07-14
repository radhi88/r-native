"""
EA Monitor — GOLD LIVE v7.31 Bridge
=====================================
يراقب الـ LIVE EA شمعة بشمعة ويرسل أوامر Claude عبر claude_live_control.csv
تشغيل: python ea_monitor.py

Dashboard: http://localhost:7799
"""

import os, csv, json, time, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime
try:
    import anthropic
except Exception:
    anthropic = None
try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

# ── مسارات الملفات ──────────────────────────────────────────────────
PORT        = 7799
MT5_COMMON  = os.path.expanduser(
    r"~\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
)
STATUS_FILE      = os.path.join(MT5_COMMON, "ea_realtime_status.json")
HISTORY_FILE     = os.path.join(MT5_COMMON, "ea_bar_history.json")
LIVE_CONTROL_CSV = os.path.join(MT5_COMMON, "claude_live_control.csv")   # ← EA يقرأ هذا
DNA_MEMORY_CSV   = os.path.join(MT5_COMMON, "gold_dna_memory.csv")       # ← EA يكتب هذا
AGENTS_DIR       = os.path.join(os.path.dirname(__file__), "agents")
CONFLUENCE_FILE  = os.path.join(AGENTS_DIR, "confluence_signal.json")
VP_SIGNAL_FILE   = os.path.join(AGENTS_DIR, "volume_profile_signal.json")

SUGGEST_EVERY = 1     # اقترح كل شمعة، والـ fast_autopilot يكتب كل ثانية
MAX_HISTORY   = 500
CHART_HISTORY = 200   # آخر 200 شمعة M1 حقيقية للواجهة
AUTO_APPLY    = True  # تطبيق اقتراحات Claude تلقائياً على EA
DISABLE_COOLDOWN = True

# ── State ────────────────────────────────────────────────────────────
state = {
    "candles":       [],
    "current":       {},
    "suggestions":   [],
    "metrics":       {},
    "dna_memory":    [],   # آخر أجيال DNA من gold_dna_memory.csv
    "bar_count":     0,
    "thinking":      False,
    "connected":     False,
    "last_action":   "—",
    "total_applied": 0,
    "agents":        {},
}

client = anthropic.Anthropic() if anthropic else None
_MT5_READY = False

CLAUDE_SYSTEM = """You are a real-time DNA parameter optimizer for a LIVE GOLD (XAUUSDm) Stop-Reverse grid EA.
This is v7.31 — a real-money account ($100-$500), so BE CONSERVATIVE. Small safe adjustments only.

The EA reads claude_live_control.csv every 1 second. You can tweak params quickly, but keep bounded real-money risk.

LIVE EA parameters you can suggest:
- gap         : ExtraTightGapPoints — grid spacing in points (current ~150, safe: 50-500)
- tp          : BasketTakeProfitMoney — basket take-profit in USD (current ~$2, safe: 0.5-10)
- sl          : BasketStopLossMoney — basket stop-loss in USD (current ~$5, safe: 1-20)
- lock_start  : BasketLockStartMoney — equity lock trigger in USD (current ~$3, safe: 0.5-10)
- lock_giveback: BasketLockGiveBackMoney — how much to give back before locking (current ~$1.5, safe: 0.1-5)
- secure_start: SecureProfitStartMoney — per-trade profit lock trigger (current ~$0.50, safe: 0.1-2)
- secure_lock : SecureProfitLockMoney — per-trade profit to secure (current ~$0.50, safe: 0.1-2)
- lot_factor  : LotFactor — grid level multiplier (safe: 0.5-2.0)
- grid_factor : GridWidenFactor — grid widen factor (safe: 0.5-2.0)
- modify_step : ModifyStepPoints — SL trail step in points (safe: 1-50)

Decision rules for REAL MONEY GOLD:
- If equity drawdown > 20%: CRITICAL — reduce sl, reduce lot_factor, widen gap
- If consecutive losses >= 3: widen gap by 15%, reduce lot_factor slightly
- If basket_pnl < -80% of sl: CRITICAL — act now
- If win_streak >= 5 and equity growing: cautious TP tighten (+10%), hold everything else
- If generation fitness improving: HOLD — don't interfere with evolution
- Cooldown is disabled by operator request; do not block decisions only because cooldown appears in old status files

Safety rules (hard limits you MUST respect):
- sl MUST always be > tp (never let sl <= tp)
- lock_start must be between tp and sl
- lock_giveback must be < lock_start
- lot_factor must stay 0.5-2.0 for small account
- DO NOT suggest reducing sl below $1.00 or tp below $0.50

Respond ONLY with valid JSON (no markdown):
{
  "action": "HOLD" | "TWEAK" | "CRITICAL",
  "message": "<one line Arabic summary>",
  "suggestion": "<specific change in English>",
  "confidence": 1-100,
  "params": {
    "gap": <int or omit>,
    "tp": <float or omit>,
    "sl": <float or omit>,
    "lock_start": <float or omit>,
    "lock_giveback": <float or omit>,
    "secure_start": <float or omit>,
    "secure_lock": <float or omit>,
    "lot_factor": <float or omit>,
    "grid_factor": <float or omit>,
    "modify_step": <int or omit>
  }
}"""


# ── قراءة ملفات MT5 ──────────────────────────────────────────────────
def read_mt5_status():
    if not os.path.exists(STATUS_FILE):
        return None
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_json_file(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {} if default is None else default

def read_agent_signals():
    return {
        "confluence": read_json_file(CONFLUENCE_FILE, {}),
        "volume_profile": read_json_file(VP_SIGNAL_FILE, {}),
    }

def _num(value, default=0.0):
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default

def _int(value, default=0):
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except Exception:
        return default

# ── Per-candle indicator fields required by the UI-SPEC Candle interface ──
SPEC_CANDLE_INDICATORS = ("atr_points", "sig", "trend", "rsi", "adx", "macd_hist", "mfi",
                          "vol_pct", "dch_pos", "demand", "supply", "entry_score", "avoid_score")

def _candle_indicator_defaults(ctx=None, latest=False):
    """Zero-filled indicator dict for historical bars; live values for the latest bar."""
    ctx = ctx or {}
    out = {k: 0 for k in SPEC_CANDLE_INDICATORS}
    if latest:
        for k in SPEC_CANDLE_INDICATORS:
            out[k] = _num(ctx.get(k), 0)
    return out

def normalize_current(current):
    global _MT5_READY
    if not isinstance(current, dict):
        return {}
    c = dict(current)
    c.setdefault("generation", c.get("dna_gen", 1))
    c.setdefault("basket_pnl", c.get("open_pnl", 0))
    c.setdefault("profit_factor", c.get("pf", 0))
    c.setdefault("drawdown_pct", c.get("max_drawdown_pct", 0))
    # ── Guarantee every UI-SPEC CurrentState field (real value or zero) ──
    c.setdefault("dna_gen", c.get("generation", 0))
    c["bar"]          = _int(c.get("bar"), 0)
    c["time"]         = c.get("time") or ""
    c["balance"]      = _num(c.get("balance"), 0)
    c["equity"]       = _num(c.get("equity"), c.get("balance", 0))
    c["peak_balance"] = _num(c.get("peak_balance"), c.get("balance", 0))
    c["open_pnl"]     = _num(c.get("open_pnl", c.get("basket_pnl")), 0)
    c["positions"]    = _int(c.get("positions"), 0)
    c["lot_factor"]   = _num(c.get("lot_factor"), 0)
    c["grid_factor"]  = _num(c.get("grid_factor"), 0)
    c["win_streak"]   = _int(c.get("win_streak"), 0)
    c["loss_streak"]  = _int(c.get("loss_streak"), 0)
    c["dna_gap"]      = _num(c.get("dna_gap"), 0)
    c["dna_tp"]       = _num(c.get("dna_tp"), 0)
    c["dna_sl"]       = _num(c.get("dna_sl"), 0)
    c["dna_gen"]      = _int(c.get("dna_gen"), 0)
    c["cooldown"]     = _int(c.get("cooldown"), 0)
    for k in ("open", "high", "low", "close"):
        c[k] = _num(c.get(k), 0)
    if DISABLE_COOLDOWN:
        c["cooldown"] = 0
        c["cooldown_enabled"] = False
    if mt5 is not None and not c.get("account_login"):
        try:
            if not _MT5_READY:
                _MT5_READY = bool(mt5.initialize())
            info = mt5.account_info() if _MT5_READY else None
            if info:
                c["account_login"] = getattr(info, "login", "")
                c["account_server"] = getattr(info, "server", "")
                c["account_currency"] = getattr(info, "currency", "")
                c["account_name"] = getattr(info, "name", "")
        except Exception:
            pass
    return c

def read_history_file():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def read_mt5_platform_history(symbol, current=None, bars=CHART_HISTORY):
    """يجلب شموع M1 الحقيقية مباشرة من منصة MT5."""
    global _MT5_READY
    if mt5 is None:
        return []
    try:
        if not _MT5_READY:
            _MT5_READY = bool(mt5.initialize())
        if not _MT5_READY:
            return []

        symbol = symbol or "XAUUSDm"
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, int(bars))
        if rates is None or len(rates) == 0:
            return []

        ctx = current or {}
        balance = _num(ctx.get("balance"), 100)
        equity = _num(ctx.get("equity"), balance)
        pnl = _num(ctx.get("open_pnl", ctx.get("basket_pnl")), 0)
        spread = _num(ctx.get("spread_points"), 0)
        positions = _int(ctx.get("positions"), 0)

        out = []
        for i, rate in enumerate(list(rates)[-int(bars):], start=1):
            row_dict = {
                "bar": i,
                "time": int(rate["time"]),
                "open": _num(rate["open"], 0),
                "high": _num(rate["high"], 0),
                "low": _num(rate["low"], 0),
                "close": _num(rate["close"], 0),
                "balance": balance,
                "equity": equity,
                "open_pnl": pnl,
                "positions": positions,
                "spread_points": spread,
            }
            row_dict.update(_candle_indicator_defaults())
            out.append(row_dict)
        if out:
            out[-1].update(_candle_indicator_defaults(ctx, latest=True))
        return out
    except Exception:
        return []

def normalize_history_rows(rows, current=None):
    ctx = current or {}
    out = []
    for i, row in enumerate(rows[-CHART_HISTORY:], start=1):
        if not isinstance(row, dict):
            continue
        row_dict = {
            "bar": _int(row.get("bar"), i),
            "time": row.get("time") or row.get("t") or "",
            "open": _num(row.get("open", row.get("o")), 0),
            "high": _num(row.get("high", row.get("h")), 0),
            "low": _num(row.get("low", row.get("l")), 0),
            "close": _num(row.get("close", row.get("c")), 0),
            "balance": _num(row.get("balance", row.get("b")), _num(ctx.get("balance"), 100)),
            "equity": _num(row.get("equity", row.get("e")), _num(ctx.get("equity"), 100)),
            "open_pnl": _num(row.get("open_pnl", row.get("p")), _num(ctx.get("open_pnl"), 0)),
            "positions": _int(row.get("positions", row.get("pos")), _int(ctx.get("positions"), 0)),
            "spread_points": _num(row.get("spread_points", row.get("spr")), _num(ctx.get("spread_points"), 0)),
        }
        row_dict.update(_candle_indicator_defaults())
        out.append(row_dict)
    out = [r for r in out if r["open"] or r["high"] or r["low"] or r["close"]]
    if out:
        out[-1].update(_candle_indicator_defaults(ctx, latest=True))
    return out

def refresh_chart_history(current):
    symbol = (current or {}).get("symbol") or "XAUUSDm"
    candles = read_mt5_platform_history(symbol, current, CHART_HISTORY)
    if not candles:
        candles = normalize_history_rows(read_history_file(), current)
    if candles:
        state["candles"] = candles[-MAX_HISTORY:]
        return True
    return False

def build_live_manager(current, metrics):
    cooldown = _int(current.get("cooldown"), 0)
    if DISABLE_COOLDOWN:
        cooldown = 0
    trade_allowed = current.get("trade_allowed", True)
    action = "LIVE_READY"
    reason = "مرتبط بالحساب ويتابع السوق."
    if not trade_allowed:
        action = "TRADE_BLOCKED"
        reason = current.get("trade_block_reason", "trade_not_allowed")
    elif cooldown > 0:
        action = "WAIT_COOLDOWN"
        reason = f"تبريد بعد خسارة/ستوب: {cooldown}s."
    elif _int(current.get("adaptive_no_reverse"), 0) > 0:
        action = "ADAPTIVE_NO_REVERSE"
        reason = "أوقف العكس السريع مؤقتاً بعد لمس ستوب."
    elif _num(current.get("spread_points"), 0) > 150:
        action = "SPREAD_CAUTION"
        reason = "السبريد عالي، المسافة الفعلية تتوسع تلقائياً."
    return {
        "action": action,
        "confidence": 90,
        "reason": reason,
        "current": {
            "cooldown_sec": cooldown,
            "loss_streak": current.get("loss_streak"),
            "lot_factor": current.get("lot_factor"),
            "grid_factor": current.get("grid_factor"),
            "profit_factor": metrics.get("profit_factor"),
            "spread_points": current.get("spread_points"),
            "effective_gap": current.get("effective_gap"),
        },
        "control": {
            "live_control_epoch": current.get("live_control_epoch"),
            "adaptive_loss_streak": current.get("adaptive_loss_streak"),
            "adaptive_win_streak": current.get("adaptive_win_streak"),
        }
    }

def public_payload():
    current = normalize_current(state.get("current", {}))
    records = state.get("dna_memory", [])[:10]
    return {
        "connected": state["connected"],
        "account": current.get("account_login"),
        "server": current.get("account_server"),
        "account_name": current.get("account_name"),
        "currency": current.get("account_currency"),
        "balance": current.get("balance"),
        "equity": current.get("equity"),
        "trade_allowed": current.get("trade_allowed"),
        "cooldown": current.get("cooldown", 0),
        "current": current,
        "candles": state["candles"][-CHART_HISTORY:],
        "metrics": state.get("metrics", {}),
        "suggestions": state["suggestions"][:30],
        "dna_memory": {
            "count": len(records),
            "best": records[0] if records else None,
            "records": records,
        },
        "manager": build_live_manager(current, state.get("metrics", {})),
        "agents": state.get("agents", {}),
        "bar_count": len(state["candles"][-CHART_HISTORY:]) or state["bar_count"],
        "total_applied": state["total_applied"],
        "paths": {
            "status": STATUS_FILE,
            "history": HISTORY_FILE,
            "control": LIVE_CONTROL_CSV,
            "dna": DNA_MEMORY_CSV,
        },
    }


def read_dna_memory():
    """يقرأ gold_dna_memory.csv ويرجع أحسن 10 أجيال"""
    if not os.path.exists(DNA_MEMORY_CSV):
        return []
    try:
        rows = []
        with open(DNA_MEMORY_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "gap":       int(row.get("ExtraTightGapPoints", 0)),
                    "tp":        float(row.get("BasketTakeProfitMoney") or row.get("BasketTakeProfit") or 0),
                    "sl":        float(row.get("BasketStopLossMoney") or row.get("BasketStopLoss") or 0),
                    "lot":       float(row.get("LotReductionFactor", 1.0)),
                    "fitness":   float(row.get("fitness", 0)),
                    "gen":       int(row.get("generation", 0)),
                    "pf":        float(row.get("profit_factor", 0)),
                    "dd":        float(row.get("max_drawdown_pct", 0)),
                    "trades":    int(row.get("total_trades", 0)),
                    "net":       float(row.get("net_profit", 0)),
                })
        # مرتبة بالفعل حسب fitness تنازلياً من الـ EA
        return rows[:10]
    except Exception as e:
        print(f"[DNA Memory] Read error: {e}")
        return []


# ── كتابة claude_live_control.csv ────────────────────────────────────
def write_live_control_csv(params: dict, bar: int, action: str, confidence: int, reason: str = "monitor"):
    """
    يكتب الـ CSV بالتنسيق اللي يقرأه الـ LIVE EA:
    صف أول: 18 عنوان
    صف ثاني: 18 قيمة
    confidence لازم > 0 عشان الـ EA يطبق
    القيم 0 = بدون تعديل (الـ EA يتجاهلها)
    """
    header = [
        "epoch","bar","action","confidence",
        "gap","tp","sl",
        "lock_start","lock_giveback","secure_start","secure_lock",
        "modify_step","lot_factor","grid_factor",
        "profit_factor","drawdown_pct","spread_points","reason_code"
    ]
    row = [
        int(time.time()),
        bar,
        action,
        max(1, confidence),             # لازم > 0
        int(params.get("gap", 0)),
        float(params.get("tp", 0)),
        float(params.get("sl", 0)),
        float(params.get("lock_start", 0)),
        float(params.get("lock_giveback", 0)),
        float(params.get("secure_start", 0)),
        float(params.get("secure_lock", 0)),
        int(params.get("modify_step", 0)),
        float(params.get("lot_factor", 0)),
        float(params.get("grid_factor", 0)),
        float(params.get("profit_factor", 0)),
        float(params.get("drawdown_pct", 0)),
        float(params.get("spread_points", 0)),
        str(reason),
    ]
    try:
        with open(LIVE_CONTROL_CSV, "w", newline="", encoding="ansi") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerow(row)
        state["total_applied"] += 1
        print(f"   ✓ CSV written → EA | action={action} conf={confidence} | {params}")
    except Exception as e:
        print(f"   ✗ CSV write failed: {e}")


def apply_claude_command(params: dict, bar: int, action: str = "TWEAK", confidence: int = 75):
    """يكتب الأوامر للـ LIVE EA عبر claude_live_control.csv"""
    if not params:
        return
    # تأكد من الحدود الآمنة
    if "sl" in params and "tp" in params:
        if params["sl"] <= params["tp"]:
            params["sl"] = params["tp"] + 0.5
    if "sl" in params:
        params["sl"] = max(1.0, float(params["sl"]))
    if "tp" in params:
        params["tp"] = max(0.5, float(params["tp"]))
    if "lot_factor" in params:
        params["lot_factor"] = max(0.5, min(2.0, float(params["lot_factor"])))

    write_live_control_csv(params, bar, action, confidence, reason="claude_monitor")


def inject_best_dna():
    """Applies the best DNA generation (records sorted best-first) to the live EA."""
    records = state.get("dna_memory", [])
    if not records:
        return {"ok": False, "error": "no_dna_memory"}
    best = records[0]                     # already sorted best-first
    params = {
        "gap": int(best.get("gap", 0)),
        "tp":  float(best.get("tp", 0)),
        "sl":  float(best.get("sl", 0)),
        "lot_factor": float(best.get("lot", 0) or 0),
    }
    params = {k: v for k, v in params.items() if v}
    apply_claude_command(params, state.get("bar_count", 0),
                         action="INJECT_DNA", confidence=90)
    return {"ok": True, "injected": {"generation": best.get("gen"), "params": params}}


# ── Claude AI ────────────────────────────────────────────────────────
def ask_claude(current, candles, metrics):
    if state["thinking"]:
        return
    if client is None:
        _hold(current.get("bar", 0))
        return
    if current.get("trade_allowed") is False or (not DISABLE_COOLDOWN and _int(current.get("cooldown"), 0) > 0):
        _hold(current.get("bar", 0))
        return
    state["thinking"] = True

    recent   = candles[-20:] if len(candles) >= 20 else candles
    balances = [c.get("balance", 100) for c in recent]
    trend    = "صاعد ↑" if len(balances) > 1 and balances[-1] > balances[0] else "هابط ↓"
    wr       = metrics.get("win_rate", 0)
    dd       = metrics.get("drawdown_pct", 0)

    # أحسن جيل من DNA
    dna_hist = state.get("dna_memory", [])
    best_dna = dna_hist[0] if dna_hist else {}

    prompt = f"""=== BAR {current.get('bar', 0)} — LIVE EA v7.30 ===

ACCOUNT (REAL MONEY):
  Balance: ${current.get('balance', 0):.2f}  Equity: ${current.get('equity', 0):.2f}
  Open P&L: ${current.get('open_pnl', 0):.2f}  Basket P&L: ${current.get('basket_pnl', 0):.2f}
  Positions: {current.get('positions', 0)}  Levels: {current.get('levels', 0)}

STREAKS:
  Win streak: {current.get('win_streak', 0)}  Loss streak: {current.get('loss_streak', 0)}
  Cooldown bars left: {current.get('cooldown', 0)}

CURRENT DNA PARAMS:
  Gap: {current.get('dna_gap', 150)} pts
  Basket TP: ${current.get('dna_tp', 2.0):.2f}  SL: ${current.get('dna_sl', 5.0):.2f}
  Lock start: ${current.get('dna_lock_start', 3.0):.2f}  Giveback: ${current.get('dna_lock_giveback', 1.5):.2f}
  Secure start: ${current.get('secure_profit_start', 0.5):.2f}  Lock: ${current.get('secure_profit_lock', 0.5):.2f}
  Generation: {current.get('generation', 1)}  Fitness: {current.get('best_fitness', 0):.2f}

METRICS:
  Win rate: {wr:.1f}%  Drawdown: {dd:.1f}%
  Total trades: {metrics.get('total_trades', 0)}
  Balance trend (20 bars): {trend}
  Range: ${min(balances):.2f} → ${max(balances):.2f}

BEST DNA IN MEMORY:
  fitness={best_dna.get('fitness', 0):.2f} gen={best_dna.get('gen', 0)}
  gap={best_dna.get('gap', 0)} tp=${best_dna.get('tp', 0):.2f} sl=${best_dna.get('sl', 0):.2f}
  net_profit=${best_dna.get('net', 0):.2f} trades={best_dna.get('trades', 0)}

REAL AGENT SIGNALS:
  Confluence approved={state.get('agents', {}).get('confluence', {}).get('approved')}
  votes={state.get('agents', {}).get('confluence', {}).get('votes')}/{state.get('agents', {}).get('confluence', {}).get('total')}
  direction={state.get('agents', {}).get('confluence', {}).get('direction')}
  VP source={state.get('agents', {}).get('volume_profile', {}).get('source')}
  bars={state.get('agents', {}).get('volume_profile', {}).get('bars')}
  signal={state.get('agents', {}).get('volume_profile', {}).get('trade_signal')}
  poc={state.get('agents', {}).get('volume_profile', {}).get('poc')}
  vah={state.get('agents', {}).get('volume_profile', {}).get('vah')}
  val={state.get('agents', {}).get('volume_profile', {}).get('val')}
  avg_spread_points={state.get('agents', {}).get('volume_profile', {}).get('avg_spread_points')}

What do you observe? Should DNA params change?"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=CLAUDE_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["bar"]       = current.get("bar", 0)
        result["timestamp"] = datetime.now().strftime("%H:%M:%S")
        result["balance"]   = current.get("balance", 0)

        state["suggestions"].insert(0, result)
        state["suggestions"] = state["suggestions"][:50]
        state["last_action"] = result["action"]

        sym = "🔴" if result["action"] == "CRITICAL" else "🟡" if result["action"] == "TWEAK" else "🟢"
        print(f"{sym} [{result['timestamp']}] Bar {result['bar']}: "
              f"{result['action']} ({result['confidence']}%) — {result['message']}")

        if AUTO_APPLY and result["action"] in ("TWEAK", "CRITICAL"):
            params = result.get("params", {})
            if params:
                apply_claude_command(
                    params,
                    result["bar"],
                    action=result["action"],
                    confidence=result["confidence"]
                )

    except json.JSONDecodeError as e:
        print(f"[Claude] JSON error: {e}")
        _hold(current.get("bar", 0))
    except Exception as e:
        print(f"[Claude] Error: {e}")
        _hold(current.get("bar", 0))
    finally:
        state["thinking"] = False


def _hold(bar):
    state["suggestions"].insert(0, {
        "action": "HOLD", "message": "جاري المراقبة...",
        "suggestion": "", "confidence": 0,
        "params": {}, "bar": bar,
        "timestamp": datetime.now().strftime("%H:%M:%S"), "balance": 0,
    })


# ── Monitor Loop ─────────────────────────────────────────────────────
def update_metrics(candles, current):
    if len(candles) < 2:
        return {}
    balances = [c.get("balance", 100) for c in candles]
    wins     = sum(1 for i in range(1, len(candles))
                   if candles[i].get("balance", 0) > candles[i-1].get("balance", 0))
    losses   = sum(1 for i in range(1, len(candles))
                   if candles[i].get("balance", 0) < candles[i-1].get("balance", 0))
    total    = wins + losses
    max_bal  = max(balances)
    min_bal  = min(balances)
    dd       = ((max_bal - min_bal) / max_bal * 100) if max_bal > 0 else 0
    return {
        "total_trades": current.get("total_trades", total),
        "wins": wins, "losses": losses,
        "win_rate": (wins / total * 100) if total > 0 else 0,
        "drawdown_pct": dd,
        "max_balance": max_bal, "min_balance": min_bal,
    }


def monitor_loop():
    last_bar      = -1
    last_dna_read = 0
    last_history_read = 0
    last_agent_read = 0
    print(f"\n{'='*56}")
    print(f"  ◈ GOLD LIVE EA v7.31 MONITOR")
    print(f"  Dashboard  → http://localhost:{PORT}")
    print(f"  MT5 files  → {MT5_COMMON}")
    print(f"  Control    → {LIVE_CONTROL_CSV}")
    print(f"  DNA Memory → {DNA_MEMORY_CSV}")
    print(f"  Auto-apply: {'ON ✓' if AUTO_APPLY else 'OFF'}")
    print(f"{'='*56}\n")

    while True:
        current = normalize_current(read_mt5_status())

        # قراءة DNA كل 60 ثانية
        if time.time() - last_dna_read > 60:
            state["dna_memory"] = read_dna_memory()
            last_dna_read = time.time()

        if current:
            state["connected"] = True
            state["current"]   = current
            if time.time() - last_agent_read > 1:
                state["agents"] = read_agent_signals()
                last_agent_read = time.time()
            bar = current.get("bar", 0)
            if time.time() - last_history_read > 1:
                refresh_chart_history(current)
                last_history_read = time.time()

            if bar != last_bar:
                last_bar = bar
                state["bar_count"] = bar

                if not state["candles"]:
                    state["candles"].append({
                        "bar":        bar,
                        "time":       current.get("time", ""),
                        "balance":    current.get("balance", 100),
                        "equity":     current.get("equity", 100),
                        "basket_pnl": current.get("basket_pnl", 0),
                        "positions":  current.get("positions", 0),
                        "generation": current.get("generation", 1),
                        "dna_gap":    current.get("dna_gap", 150),
                    })

                state["metrics"] = update_metrics(state["candles"], current)
                pnl = current.get("basket_pnl", 0)
                print(f"Bar {bar:5d} | Gen{current.get('generation',1)} | "
                      f"${current.get('balance',0):.2f} | "
                      f"{'📈' if pnl>=0 else '📉'}${pnl:.2f} | "
                      f"Pos:{current.get('positions',0)} | "
                      f"Gap:{current.get('dna_gap',150):.0f}")

                if bar > 0 and bar % SUGGEST_EVERY == 0:
                    threading.Thread(
                        target=ask_claude,
                        args=(current, state["candles"], state["metrics"]),
                        daemon=True,
                    ).start()
        else:
            if state["connected"]:
                print("[Monitor] ⏳ Waiting for MT5 EA...")
            state["connected"] = False

        time.sleep(0.2)


# ── HTML Dashboard ────────────────────────────────────────────────────
def build_dashboard():
    cur     = state.get("current", {})
    metrics = state.get("metrics", {})
    suggs   = state.get("suggestions", [])
    dna_mem = state.get("dna_memory", [])

    bal       = cur.get("balance", 0)
    pnl       = cur.get("basket_pnl", 0)
    pos       = cur.get("positions", 0)
    gen       = cur.get("generation", 1)
    gap       = cur.get("dna_gap", 150)
    tp_v      = cur.get("dna_tp", 2.0)
    sl_v      = cur.get("dna_sl", 5.0)
    lock_s    = cur.get("dna_lock_start", 3.0)
    lock_g    = cur.get("dna_lock_giveback", 1.5)
    sec_s     = cur.get("secure_profit_start", 0.5)
    sec_l     = cur.get("secure_profit_lock", 0.5)
    fit       = cur.get("best_fitness", 0)
    wr        = metrics.get("win_rate", 0)
    dd        = metrics.get("drawdown_pct", 0)
    conn      = state["connected"]
    agents    = state.get("agents", {})
    conf      = agents.get("confluence", {}) if isinstance(agents, dict) else {}
    vp        = agents.get("volume_profile", {}) if isinstance(agents, dict) else {}

    rows = "".join(f"""<tr>
<td>{s.get('timestamp','')}</td><td>Bar {s.get('bar',0)}</td>
<td class="{s.get('action','HOLD')}">{s.get('action','')}</td>
<td>{s.get('confidence',0)}%</td>
<td>{s.get('message','')}</td>
<td style="color:#666">{s.get('suggestion','')[:60]}</td>
</tr>""" for s in suggs[:12])

    if not dna_mem:
        dna_section = '<p style="color:#333;font-size:.8em">لا توجد بيانات — EA لم يحفظ بعد</p>'
    else:
        dna_rows_html = "".join(f"""<tr>
<td style="color:#ffcc00">#{r.get('gen',0)}</td>
<td style="color:#00d4ff">{r.get('fitness',0):.2f}</td>
<td>{r.get('gap',0)}</td>
<td style="color:#00ff88">${r.get('tp',0):.2f}</td>
<td style="color:#ff4444">${r.get('sl',0):.2f}</td>
<td>{r.get('pf',0):.2f}</td>
<td style="color:{'#ff4444' if r.get('dd',0)>20 else '#aaa'}">{r.get('dd',0):.1f}%</td>
<td>{r.get('trades',0)}</td>
<td style="color:{'#00ff88' if r.get('net',0)>0 else '#ff4444'}">${r.get('net',0):.2f}</td>
</tr>""" for r in dna_mem)
        dna_section = f"""<table>
<tr><th>الجيل</th><th>Fitness</th><th>Gap</th><th>TP $</th><th>SL $</th><th>PF</th><th>DD%</th><th>Trades</th><th>Net $</th></tr>
{dna_rows_html}
</table>"""

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><meta http-equiv="refresh" content="1">
<title>LIVE EA v7.31 Monitor</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#080810;color:#ddd;font-family:'Segoe UI',monospace;padding:16px}}
h1{{color:#00d4ff;font-size:1.3em;border-bottom:1px solid #00d4ff33;padding-bottom:8px;margin-bottom:14px}}
h2{{color:#444;font-size:.85em;margin:14px 0 8px;border-bottom:1px solid #1a1a2e;padding-bottom:4px}}
.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:10px}}
.c{{background:#0f0f1a;border:1px solid #1a1a2e;border-radius:8px;padding:10px}}
.l{{font-size:.7em;color:#555;margin-bottom:3px}}
.v{{font-size:1.4em;font-weight:bold}}
.gr{{color:#00ff88}}.rd{{color:#ff4444}}.yl{{color:#ffcc00}}.bl{{color:#00d4ff}}
table{{width:100%;border-collapse:collapse;font-size:.8em;margin-bottom:14px}}
th{{background:#0f0f1a;color:#444;padding:5px 8px;text-align:right;border-bottom:1px solid #1a1a2e}}
td{{padding:4px 8px;border-bottom:1px solid #0a0a14}}
.HOLD{{color:#00ff88}}.TWEAK{{color:#ffcc00}}.CRITICAL{{color:#ff4444}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}}
.on{{background:#00ff88;box-shadow:0 0 6px #00ff88;animation:p 1.5s infinite}}
.off{{background:#ff4444}}
@keyframes p{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75em;font-weight:bold}}
.live{{background:#ff4444;color:#fff}}
</style></head>
<body>
<h1>◈ GOLD LIVE EA v7.31
  <span class="dot {'on' if conn else 'off'}"></span>
  {'<span class="badge live">LIVE 🔴</span>' if conn else '<span style="color:#ff4444">DISCONNECTED</span>'}
</h1>

<div class="g">
  <div class="c"><div class="l">Balance</div><div class="v {'gr' if bal>=100 else 'rd'}">${bal:.2f}</div></div>
  <div class="c"><div class="l">Basket P&L</div><div class="v {'gr' if pnl>=0 else 'rd'}">${pnl:.2f}</div></div>
  <div class="c"><div class="l">Positions</div><div class="v bl">{pos}</div></div>
  <div class="c"><div class="l">Generation</div><div class="v yl">#{gen}</div></div>
  <div class="c"><div class="l">Win Rate</div><div class="v {'gr' if wr>=55 else 'yl' if wr>=40 else 'rd'}">{wr:.1f}%</div></div>
  <div class="c"><div class="l">Drawdown</div><div class="v {'rd' if dd>20 else 'yl' if dd>10 else 'gr'}">{dd:.1f}%</div></div>
  <div class="c"><div class="l">Best Fitness</div><div class="v bl">{fit:.2f}</div></div>
  <div class="c"><div class="l">Applied Cmds</div><div class="v">{state['total_applied']}</div></div>
</div>

<h2>⚡ الوكلاء والبيانات الحقيقية</h2>
<div class="g">
  <div class="c"><div class="l">Confluence</div><div class="v {'gr' if conf.get('approved') else 'rd'}">{'APPROVED' if conf.get('approved') else 'BLOCKED'}</div></div>
  <div class="c"><div class="l">Votes</div><div class="v bl">{conf.get('votes','-')}/{conf.get('total','-')}</div></div>
  <div class="c"><div class="l">Direction</div><div class="v yl">{conf.get('direction','-')}</div></div>
  <div class="c"><div class="l">VP Signal</div><div class="v">{vp.get('trade_signal','-')}</div></div>
  <div class="c"><div class="l">POC / VAH / VAL</div><div class="v" style="font-size:.95em">{vp.get('poc','-')} / {vp.get('vah','-')} / {vp.get('val','-')}</div></div>
  <div class="c"><div class="l">Source / Spread</div><div class="v" style="font-size:.95em">{vp.get('source','-')} / {vp.get('avg_spread_points','-')}</div></div>
</div>

<h2>⚡ DNA الحالي</h2>
<div class="g">
  <div class="c"><div class="l">Gap (pts)</div><div class="v">{gap}</div></div>
  <div class="c"><div class="l">Basket TP ($)</div><div class="v gr">{tp_v:.2f}</div></div>
  <div class="c"><div class="l">Basket SL ($)</div><div class="v rd">{sl_v:.2f}</div></div>
  <div class="c"><div class="l">Lock Start ($)</div><div class="v yl">{lock_s:.2f}</div></div>
  <div class="c"><div class="l">Lock Giveback ($)</div><div class="v">{lock_g:.2f}</div></div>
  <div class="c"><div class="l">Secure Start ($)</div><div class="v">{sec_s:.2f}</div></div>
  <div class="c"><div class="l">Secure Lock ($)</div><div class="v">{sec_l:.2f}</div></div>
</div>

<h2>🧬 DNA Memory — أحسن الأجيال</h2>
{dna_section}

<h2>🤖 آخر اقتراحات Claude</h2>
<table>
<tr><th>الوقت</th><th>الشمعة</th><th>الإجراء</th><th>الثقة</th><th>الملاحظة</th><th>التعديل</th></tr>
{rows}
</table>

<div style="color:#222;font-size:.7em;margin-top:8px">
  Control file: {LIVE_CONTROL_CSV}<br>
  DNA Memory: {DNA_MEMORY_CSV}
</div>
</body></html>"""


# ── HTTP Server ──────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/state", "/data", "/api/mt5/data"):
            body = json.dumps(public_payload(), ensure_ascii=False).encode()
            self._send(200, "application/json", body)
        else:
            self._send(200, "text/html; charset=utf-8", build_dashboard().encode("utf-8"))

    def do_POST(self):
        if self.path == "/api/command":
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length))
            params = data.get("params", {})
            action = data.get("action", "TWEAK")
            conf   = data.get("confidence", 80)
            apply_claude_command(params, state["bar_count"], action=action, confidence=conf)
            self._send(200, "application/json", b'{"ok":true}')
        elif self.path == "/inject_dna":
            result = inject_best_dna()
            self._send(200, "application/json", json.dumps(result).encode())
        elif self.path == "/control":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length) or b"{}")
            action = str(body.get("action", "CONTROL")).upper()
            params = body.get("params", {}) or {}
            # FORCE_COOLDOWN / RESTART / generic — route into the live control CSV
            write_live_control_csv(params, state.get("bar_count", 0), action,
                                   confidence=int(body.get("confidence", 80)),
                                   reason=f"control_{action.lower()}")
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _send(self, code, ctype, body):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[Dashboard] http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[Monitor] Stopped.")
