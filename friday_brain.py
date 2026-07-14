"""
friday_brain.py — FRIDAY Cognitive Brain (LLM-powered, networked, continuous)

5 وكلاء بـ Ollama LLM يتحدثون مع بعض عبر message bus، ويضعون أوامر pending
على مستويات سعرية محددة، وينفّذون عبر MT5 Python API.

التشغيل:
    python friday_brain.py             # paper mode (يكتب الخطط، لا ينفّذ)
    python friday_brain.py --live      # ينفّذ فعلياً عبر MT5
    python friday_brain.py --kill      # توقف فوري (لا يفتح أي صفقة)

الإيقاف الطارئ: أنشئ ملف 'kill_switch.txt' في C:\\Users\\Radhi\\MT5
"""

import argparse
import json
import random
import re
import statistics
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
import MetaTrader5 as mt5

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

import os

# ── Centralized config (edit friday_config.py to tune the whole system) ──
try:
    import friday_config as cfg
except ImportError:
    cfg = None

# ── Learning + safety guards (CRITICAL) ──
try:
    import friday_memory as memory
    import friday_regime as regime
    HAS_LEARNING = True
except ImportError:
    HAS_LEARNING = False
    print("[CRITICAL] friday_memory or friday_regime not found — flying blind!")

try:
    import pandas as _pd
    from fractal_smc_engine import run_full_pipeline as _fractal_pipeline
    _FRACTAL_ENGINE_OK = True
except Exception:
    _FRACTAL_ENGINE_OK = False

ROOT        = cfg.ROOT        if cfg else Path(r"C:\Users\Radhi\MT5")
MT5_COMMON  = cfg.MT5_COMMON  if cfg else Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
KILL_SWITCH = cfg.KILL_SWITCH if cfg else ROOT / "kill_switch.txt"
BUS_FILE    = cfg.BUS_FILE    if cfg else ROOT / "friday_bus.json"
LEVELS_FILE = cfg.LEVELS_FILE if cfg else ROOT / "friday_levels.json"
ORDERS_LOG  = cfg.ORDERS_LOG  if cfg else ROOT / "friday_orders.csv"
BRAIN_STATE = cfg.BRAIN_STATE if cfg else ROOT / "friday_brain_v2_state.json"
EA_ORDERS   = cfg.EA_ORDERS   if cfg else MT5_COMMON / "friday_brain_orders.json"

OLLAMA_URL  = cfg.OLLAMA_URL  if cfg else "http://localhost:11434/api/chat"
FAST_MODEL  = cfg.FAST_MODEL  if cfg else "qwen2.5:3b"
DEEP_MODEL  = cfg.DEEP_MODEL  if cfg else "qwen2.5:7b"

# Claude API (optional) — enables higher-quality COORDINATOR if API key set
CLAUDE_MODEL_COORDINATOR = cfg.CLAUDE_COORDINATOR_MODEL if cfg else "claude-sonnet-4-5"
USE_CLAUDE_FOR_COORDINATOR = (
    bool(os.environ.get("ANTHROPIC_API_KEY"))
    and (cfg.USE_CLAUDE_FOR_COORDINATOR_IF_KEY if cfg else True)
)
try:
    import anthropic
    HAS_ANTHROPIC = True
    _anthropic_client = anthropic.Anthropic() if USE_CLAUDE_FOR_COORDINATOR else None
except Exception:
    HAS_ANTHROPIC = False
    _anthropic_client = None

SYMBOL      = cfg.SYMBOL    if cfg else "XAUUSDm"
MAGIC       = cfg.MAGIC     if cfg else 20260600
MAX_LOT     = cfg.MAX_LOT   if cfg else 0.02
MIN_LOT     = cfg.MIN_LOT   if cfg else 0.01
MAX_ORDERS  = cfg.MAX_ORDERS if cfg else 3
COOLDOWN_S  = cfg.COOLDOWN_S if cfg else 30
MIN_SPREAD_TO_MOVE_MULT = cfg.MIN_SPREAD_TO_MOVE_MULT if cfg else 3.0
MIN_RR_RATIO            = cfg.MIN_RR_RATIO            if cfg else 1.5

CYCLE_SECONDS = cfg.CYCLE_SECONDS if cfg else 8

# Multi-stage trailing SL constants (from cfg, with safe fallbacks)
BREAKEVEN_TRIGGER_R  = cfg.BREAKEVEN_TRIGGER_R  if cfg else 0.8
BREAKEVEN_BUFFER_PCT = cfg.BREAKEVEN_BUFFER_PCT if cfg else 10
TRAIL_STAGE1_R       = cfg.TRAIL_STAGE1_R       if cfg else 1.0
TRAIL_STAGE2_R       = cfg.TRAIL_STAGE2_R       if cfg else 1.5
TRAIL_STAGE3_R       = cfg.TRAIL_STAGE3_R       if cfg else 2.5
TRAIL_STAGE4_R       = cfg.TRAIL_STAGE4_R       if cfg else 3.5
TRAIL_DIST_STAGE1    = cfg.TRAIL_DIST_STAGE1    if cfg else 0.85
TRAIL_DIST_STAGE2    = cfg.TRAIL_DIST_STAGE2    if cfg else 0.55
TRAIL_DIST_STAGE3    = cfg.TRAIL_DIST_STAGE3    if cfg else 0.35
TRAIL_DIST_STAGE4    = cfg.TRAIL_DIST_STAGE4    if cfg else 0.20
TRAIL_MIN_MOVE_PT    = cfg.TRAIL_MIN_MOVE_PT    if cfg else 2.0

# FVG strategy constants
FVG_ENABLED      = cfg.FVG_ENABLED      if cfg else True
FVG_MAX_AGE_BARS = cfg.FVG_MAX_AGE_BARS if cfg else 8
FVG_MIN_SIZE_PT  = cfg.FVG_MIN_SIZE_PT  if cfg else 30
FVG_SL_BUFFER_PT = cfg.FVG_SL_BUFFER_PT if cfg else 60
FVG_TP_RR        = cfg.FVG_TP_RR        if cfg else 2.0
FVG_MAX_SPREAD   = cfg.FVG_MAX_SPREAD_PT if cfg else 420
FVG_COOLDOWN_S   = cfg.FVG_COOLDOWN_S   if cfg else 45


# ═══════════════════════════════════════════════════════════════════════════
# MESSAGE BUS — agents publish/subscribe
# ═══════════════════════════════════════════════════════════════════════════

class Bus:
    def __init__(self, capacity=200):
        self._msgs = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def post(self, sender: str, topic: str, content: dict):
        msg = {
            "ts":      datetime.now().strftime("%H:%M:%S"),
            "sender":  sender,
            "topic":   topic,
            "content": content,
        }
        with self._lock:
            self._msgs.append(msg)
        return msg

    def recent(self, n=20, topic=None, exclude_sender=None):
        with self._lock:
            msgs = list(self._msgs)
        if topic:
            msgs = [m for m in msgs if m["topic"] == topic]
        if exclude_sender:
            msgs = [m for m in msgs if m["sender"] != exclude_sender]
        return msgs[-n:]

    def snapshot(self):
        with self._lock:
            return list(self._msgs)


# ═══════════════════════════════════════════════════════════════════════════
# OLLAMA LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════

def llm_chat(model: str, system: str, user: str, timeout=45,
             use_claude: bool = False, retries: int = 2) -> str:
    """Single-turn chat with retry + keep_alive.
    By default uses Ollama (parallel-capable). Falls back to Claude if configured."""

    if use_claude and _anthropic_client is not None:
        try:
            resp = _anthropic_client.messages.create(
                model=CLAUDE_MODEL_COORDINATOR,
                max_tokens=600,
                temperature=0.4,
                system=[{
                    "type":          "text",
                    "text":          system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            print(f"[Claude API error, fallback Ollama] {e}")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream":     False,
        "keep_alive": "60m",            # keep model hot in VRAM
        "options": {
            "temperature":  0.6,
            "num_predict":  400,
            "num_ctx":      4096,        # larger context, fewer truncations
        },
    }

    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()
        except requests.exceptions.Timeout as e:
            last_err = f"timeout (attempt {attempt+1}/{retries+1})"
            # On retry, give it a bit more headroom
            timeout = min(timeout + 15, 90)
        except Exception as e:
            last_err = str(e)[:80]
            time.sleep(0.5)

    return f"[LLM ERROR: {last_err}]"


def extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM output. Handles deep nesting via brace-matching."""
    if not text:
        return {}

    # Try fenced code first
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try: return json.loads(m.group(1))
        except: pass

    # Brace-counting scan for first complete top-level JSON object
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start:i+1]
                    try:
                        return json.loads(chunk)
                    except Exception:
                        break  # try next opening brace
        start = text.find("{", start + 1)

    return {}


# ═══════════════════════════════════════════════════════════════════════════
# MARKET CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

def read_market_context() -> dict:
    """Read EA's status + bar history into a compact context dict."""
    status_path = MT5_COMMON / "ea_realtime_status.json"
    bars_path   = MT5_COMMON / "ea_bar_history.json"

    status = {}
    if status_path.exists():
        try: status = json.loads(status_path.read_text(encoding="utf-8"))
        except: pass

    bars = []
    if bars_path.exists():
        try:
            b = json.loads(bars_path.read_text(encoding="utf-8"))
            bars = b.get("bars", b) if isinstance(b, dict) else b
        except: pass

    last_bars = bars[-20:] if bars else []

    # Compute simple stats from bars
    closes = [float(b.get("c", b.get("close", 0))) for b in last_bars if b]
    highs  = [float(b.get("h", b.get("high", 0)))  for b in last_bars if b]
    lows   = [float(b.get("l", b.get("low", 0)))   for b in last_bars if b]
    trend  = "—"
    if len(closes) >= 5:
        avg_first = sum(closes[:5])/5
        avg_last  = sum(closes[-5:])/5
        diff = avg_last - avg_first
        trend = "صاعد" if diff > 1.0 else ("هابط" if diff < -1.0 else "جانبي")

    # Try to read footprint data
    footprint = {}
    fp_path = ROOT / "friday_footprint.json"
    if fp_path.exists():
        try:
            footprint = json.loads(fp_path.read_text(encoding="utf-8"))
        except: pass

    # Compute fractal direction from bar history
    fractal_dir = "neutral"
    fractal_last_high = 0.0
    fractal_last_low  = 0.0
    fractal_high_age  = 50
    fractal_low_age   = 50
    fractal_signal_active = False
    fractal_confidence    = 0.0
    if _FRACTAL_ENGINE_OK and len(bars) >= 10:
        try:
            df = _pd.DataFrame(bars)
            df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})
            for col in ("open", "high", "low", "close"):
                if col in df.columns:
                    df[col] = _pd.to_numeric(df[col], errors="coerce")
            df = _fractal_pipeline(df)
            r = df.iloc[-1]
            raw_bias = r.get("smc_fractal_bias", "NEUTRAL") if hasattr(r, "get") else "NEUTRAL"
            fractal_dir = {"BUY": "bull", "SELL": "bear", "NEUTRAL": "neutral"}.get(str(raw_bias), "neutral")
            if "last_fractal_high" in df.columns:
                v = r["last_fractal_high"]
                fractal_last_high = float(v) if _pd.notna(v) else 0.0
            if "last_fractal_low" in df.columns:
                v = r["last_fractal_low"]
                fractal_last_low  = float(v) if _pd.notna(v) else 0.0
            if "fractal_high_age" in df.columns:
                fractal_high_age = int(r["fractal_high_age"])
            if "fractal_low_age" in df.columns:
                fractal_low_age  = int(r["fractal_low_age"])
            if "smc_fractal_confidence" in df.columns:
                fractal_confidence = float(r["smc_fractal_confidence"])
            fractal_signal_active = min(fractal_high_age, fractal_low_age) <= 10
        except Exception:
            pass

    return {
        "symbol":   status.get("symbol", SYMBOL),
        "bid":      float(status.get("bid", 0)),
        "ask":      float(status.get("ask", 0)),
        "spread_pt": float(status.get("spread_points", 0)),
        "footprint": footprint,
        "balance":  float(status.get("balance", 0)),
        "equity":   float(status.get("equity", 0)),
        "positions": int(status.get("positions", 0)),
        "smc_bias":  status.get("smc_bias", "—"),
        "smc_swing_high": float(status.get("smc_swing_high", 0)),
        "smc_swing_low":  float(status.get("smc_swing_low", 0)),
        "prev_day_high":  float(status.get("prev_day_high", 0)),
        "prev_day_low":   float(status.get("prev_day_low", 0)),
        "ob_count":  status.get("smc_ob_count", 0),
        "fvg_count": status.get("smc_fvg_count", 0),
        "has_bos":   status.get("smc_has_bos", False),
        "has_choch": status.get("smc_has_choch", False),
        "loss_streak": status.get("loss_streak", 0),
        "win_streak":  status.get("win_streak", 0),
        "trend_5v5":  trend,
        "recent_high": max(highs) if highs else 0,
        "recent_low":  min(lows)  if lows  else 0,
        "last_bars":  last_bars[-10:],
        "fractal_dir":          fractal_dir,
        "fractal_last_high":    fractal_last_high,
        "fractal_last_low":     fractal_last_low,
        "fractal_high_age":     fractal_high_age,
        "fractal_low_age":      fractal_low_age,
        "fractal_signal_active": fractal_signal_active,
        "fractal_confidence":   fractal_confidence,
    }


def market_summary_for_llm(ctx: dict) -> str:
    """Compact market description for LLM prompts."""
    lines = [
        f"الرمز: {ctx['symbol']}  |  Bid={ctx['bid']:.2f}  Ask={ctx['ask']:.2f}  Spread={ctx['spread_pt']:.0f}pt",
        f"الاتجاه (20 شمعة): {ctx['trend_5v5']}",
        f"SMC bias: {ctx['smc_bias']}  |  BOS={ctx['has_bos']}  CHoCH={ctx['has_choch']}  OB={ctx['ob_count']}  FVG={ctx['fvg_count']}",
        f"Swing↑ {ctx['smc_swing_high']:.2f}  Swing↓ {ctx['smc_swing_low']:.2f}",
        f"PDH {ctx['prev_day_high']:.2f}  PDL {ctx['prev_day_low']:.2f}",
        f"أعلى 20 شمعة: {ctx['recent_high']:.2f}  |  أدنى: {ctx['recent_low']:.2f}",
        f"الحساب: balance={ctx['balance']:.2f}  equity={ctx['equity']:.2f}  positions={ctx['positions']}  losses={ctx['loss_streak']}",
    ]

    # Fractal direction context
    f_dir   = ctx.get("fractal_dir", "neutral")
    f_fh    = ctx.get("fractal_last_high", 0.0)
    f_fl    = ctx.get("fractal_last_low", 0.0)
    f_fha   = ctx.get("fractal_high_age", 50)
    f_fla   = ctx.get("fractal_low_age", 50)
    f_act   = ctx.get("fractal_signal_active", False)
    f_conf  = ctx.get("fractal_confidence", 0.0)
    lines.append(
        f"Fractal direction: {f_dir.upper()}  |  "
        f"FracHigh={f_fh:.2f}(age={f_fha}b)  FracLow={f_fl:.2f}(age={f_fla}b)  "
        f"Signal={'ACTIVE' if f_act else 'EXPIRED'}  conf={f_conf:.2f}"
    )

    # Tick-level footprint context (if available)
    fp = ctx.get("footprint", {})
    if fp.get("bars"):
        last_fp = fp["bars"][-1]
        sign = "+" if last_fp.get("delta", 0) >= 0 else ""
        lines.append(
            f"Footprint: ticks={last_fp['tick_count']} Δ{sign}{last_fp['delta']} "
            f"POC={last_fp['poc']} cumΔ={last_fp.get('cum_delta',0)} "
            f"sess_POC={fp.get('session_poc')} VAH={fp.get('vah')} VAL={fp.get('val')}"
        )
        if last_fp.get("imbalances"):
            imb_str = ", ".join([f"{i['side']}@{i['price']:.2f}({i['ratio']}x)" for i in last_fp["imbalances"][:3]])
            lines.append(f"Imbalances: {imb_str}")

    # FVG zones (injected by Brain after detection, passed via ctx extension)
    fvg_zones = ctx.get("fvg_zones", [])
    if fvg_zones:
        fvg_str = "  ".join(
            f"{z['type']}@{z['mid']:.2f}(sz={z['size_pt']:.0f}pt,age={z['age_bars']}b)"
            for z in fvg_zones[:3]
        )
        lines.append(f"FVG active: {fvg_str}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# LLM AGENT BASE
# ═══════════════════════════════════════════════════════════════════════════

class LLMAgent:
    def __init__(self, name: str, role_emoji: str, model: str, system: str, bus: Bus):
        self.name   = name
        self.emoji  = role_emoji
        self.model  = model
        self.system = system
        self.bus    = bus
        self.last_message = ""
        self.cycles = 0
        self.last_good_output = None    # cached for fallback when LLM fails
        self.consecutive_failures = 0

    def think(self, market: dict, peers: list) -> dict:
        """Run one cognitive cycle. Returns parsed structured output."""
        peer_lines = []
        for m in peers[-8:]:
            if m["sender"] == self.name: continue
            c = m["content"]
            txt = c.get("say") or c.get("note") or c.get("decision") or str(c)
            peer_lines.append(f"{m['sender']}: {txt[:140]}")
        peer_block = "\n".join(peer_lines) if peer_lines else "(لا رسائل بعد)"

        user_prompt = f"""=== حالة السوق الآن ===
{market_summary_for_llm(market)}

=== ما يقوله زملاؤك (آخر رسائل) ===
{peer_block}

=== مهمتك ===
حلّل، ثم أعطني JSON واحد فقط بهذا الشكل (لا تخرج عن الـ schema):
{{"say": "جملة قصيرة بالعربية تشرح رأيك للزملاء (≤80 حرف)",
  "stance": "BUY|SELL|WAIT|HALT",
  "confidence": 0-100,
  "levels": [{{"side":"BUY|SELL", "price": 4555.50, "reason": "السبب"}}],
  "drawings": [],
  "veto": false}}

ملاحظات:
• levels: مستويات سعرية محددة تتوقع أن السعر سيلامسها.
• drawings: استخدمه فقط إذا كنت CHARTIST (ارسم على الشارت). البقية اتركوها مصفوفة فارغة.
• veto=true يعني تعارض القرار الجماعي لخطر شديد.
أعطني JSON فقط، بدون شرح خارجي."""

        raw = llm_chat(self.model, self.system, user_prompt)
        out = extract_json(raw)

        # Detect timeout/error
        is_llm_error = (not raw) or raw.startswith("[LLM ERROR")

        if not out:
            if is_llm_error and self.last_good_output:
                # Reuse last valid opinion (with reduced confidence) instead of WAIT 30%
                self.consecutive_failures += 1
                fade = max(0.5, 1.0 - self.consecutive_failures * 0.15)
                cached_conf = int(self.last_good_output.get("confidence", 50) * fade)
                out = {
                    "say":        f"[cached {self.consecutive_failures}× LLM busy] " + self.last_good_output.get("say", "")[:60],
                    "stance":     self.last_good_output.get("stance", "WAIT"),
                    "confidence": cached_conf,
                    "levels":     self.last_good_output.get("levels", []),
                    "drawings":   self.last_good_output.get("drawings", []),
                    "veto":       self.last_good_output.get("veto", False),
                }
            else:
                # First-ever failure: log + sane defaults
                try:
                    debug_dir = ROOT / "brain_debug"
                    debug_dir.mkdir(exist_ok=True)
                    (debug_dir / f"{datetime.now():%H%M%S}_{self.name}.txt").write_text(
                        f"=== {self.name} raw (no JSON parsed) ===\n{raw}",
                        encoding="utf-8")
                except Exception: pass
                out = {"say": (raw[:80] if raw else "(no LLM response)"),
                       "stance": "WAIT", "confidence": 30,
                       "levels": [], "drawings": [], "veto": False}
                self.consecutive_failures += 1
        else:
            # Good output — cache it for future fallback
            self.last_good_output = out
            self.consecutive_failures = 0

        # Publish to bus
        self.bus.post(self.name, "dialogue", {
            "say":        out.get("say", "")[:120],
            "stance":     out.get("stance", "WAIT"),
            "confidence": int(out.get("confidence", 0) or 0),
            "levels":     out.get("levels", []),
            "drawings":   out.get("drawings", []),
            "veto":       bool(out.get("veto", False)),
        })

        self.last_message = out.get("say", "")
        self.cycles += 1
        return out


def ClampLot_static(lot: float) -> float:
    """Lot clamper used by the fast scalp path before trader has full symbol info."""
    return round(max(MIN_LOT, min(MAX_LOT, lot)), 2)


# ═══════════════════════════════════════════════════════════════════════════
# MOMENTUM DETECTOR — finds "whale" candles + speed/strength
# ═══════════════════════════════════════════════════════════════════════════

class MomentumDetector:
    """Multi-trigger momentum detector — whale, push, breakout, exhaustion."""

    def __init__(self):
        self.last = {}

    def _bars_from_mt5(self, count: int = 15):
        """Read fresh bars directly from MT5 (more current than EA JSON)."""
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, count)
            if rates is None or len(rates) < 5:
                return None
            return rates
        except Exception:
            return None

    def analyze(self, market: dict) -> dict:
        rates = self._bars_from_mt5(15)
        if rates is None:
            # fallback to EA JSON (may be slightly stale)
            bars_dict = market.get("last_bars", [])[-15:]
            if len(bars_dict) < 5:
                self.last = self._empty("no bars")
                return self.last
            opens  = [float(b.get("o", 0)) for b in bars_dict]
            closes = [float(b.get("c", 0)) for b in bars_dict]
            highs  = [float(b.get("h", 0)) for b in bars_dict]
            lows   = [float(b.get("l", 0)) for b in bars_dict]
        else:
            opens  = [r["open"]  for r in rates]
            closes = [r["close"] for r in rates]
            highs  = [r["high"]  for r in rates]
            lows   = [r["low"]   for r in rates]

        bodies = [closes[i] - opens[i] for i in range(len(opens))]
        ranges = [max(0.01, highs[i] - lows[i]) for i in range(len(opens))]

        # Direction streak
        dirs = [1 if b > 0 else -1 if b < 0 else 0 for b in bodies]
        last_dir = dirs[-1]
        streak = 1
        for d in reversed(dirs[:-1]):
            if d == last_dir and d != 0: streak += 1
            else: break

        # Stats
        br_ratios     = [abs(bodies[i]) / ranges[i] for i in range(len(opens))]
        avg_br        = statistics.mean(br_ratios)
        last_body     = abs(bodies[-1])
        avg_body      = statistics.mean([abs(b) for b in bodies[:-1]]) or 0.01
        body_exp      = last_body / avg_body
        avg_range     = statistics.mean(ranges)
        last_range    = ranges[-1]
        range_exp     = last_range / avg_range if avg_range > 0 else 1.0

        # === Trigger A: WHALE — one big aggressive bar (loose) ===
        whale = (body_exp >= 1.2 and streak >= 2 and avg_br >= 0.5)

        # === Trigger B: PUSH — last 2-3 bars same direction ===
        last2 = bodies[-2:] if len(bodies) >= 2 else bodies
        last3 = bodies[-3:] if len(bodies) >= 3 else bodies
        push = False
        push_dir = "FLAT"
        # 3-bar push (stronger)
        if len(last3) == 3:
            same3 = all(b > 0 for b in last3) or all(b < 0 for b in last3)
            push_total = sum(abs(b) for b in last3)
            if same3 and push_total > avg_range * 1.0:
                push = True
                push_dir = "UP" if last3[-1] > 0 else "DOWN"
        # 2-bar strong push
        if not push and len(last2) == 2:
            same2 = (last2[0] > 0 and last2[1] > 0) or (last2[0] < 0 and last2[1] < 0)
            total2 = sum(abs(b) for b in last2)
            if same2 and total2 > avg_range * 1.3:
                push = True
                push_dir = "UP" if last2[-1] > 0 else "DOWN"

        # === Trigger C: BREAKOUT — closes above recent high / below recent low ===
        breakout = False
        bo_dir = "FLAT"
        if len(closes) >= 5:
            recent_high = max(highs[-5:-1])  # exclude current bar
            recent_low  = min(lows[-5:-1])
            if closes[-1] > recent_high and bodies[-1] > 0:
                breakout = True; bo_dir = "UP"
            elif closes[-1] < recent_low and bodies[-1] < 0:
                breakout = True; bo_dir = "DOWN"

        # === Trigger D: BAR VELOCITY — single strong bar ===
        bar_strong = (last_body > avg_body * 1.6 and br_ratios[-1] > 0.55)

        # === Trigger E: RANGE EXPLOSION — current bar's range >> avg ===
        range_explosion = (range_exp >= 1.8 and abs(bodies[-1]) > avg_body * 1.2)

        # === Score ===
        score = 0
        if whale:           score += 45
        if push:            score += 40
        if breakout:        score += 35
        if bar_strong:      score += 25
        if range_explosion: score += 20
        if streak >= 4: score += 15
        elif streak >= 3: score += 8
        score = min(100, score)

        # === Direction — consensus of triggers ===
        votes = {"UP": 0, "DOWN": 0}
        if whale:    votes["UP" if last_dir > 0 else "DOWN"] += 1
        if push:     votes[push_dir] += 1
        if breakout: votes[bo_dir]   += 1
        if bar_strong: votes["UP" if last_dir > 0 else "DOWN"] += 1
        if range_explosion: votes["UP" if last_dir > 0 else "DOWN"] += 1
        direction = "UP" if votes["UP"] > votes["DOWN"] else "DOWN" if votes["DOWN"] > votes["UP"] else "FLAT"

        # === Signal: any meaningful trigger fired ===
        signal = whale or push or breakout or bar_strong or range_explosion

        triggers = []
        if whale:           triggers.append("WHALE")
        if push:            triggers.append("PUSH")
        if breakout:        triggers.append("BREAKOUT")
        if bar_strong:      triggers.append("STRONG_BAR")
        if range_explosion: triggers.append("RANGE_EXP")

        # Cast all numeric/bool values to Python native types (mt5 returns numpy)
        out = {
            "score":     int(score),
            "direction": str(direction),
            "whale":     bool(whale),
            "push":      bool(push),
            "breakout":  bool(breakout),
            "bar_strong": bool(bar_strong),
            "range_explosion": bool(range_explosion),
            "signal":    bool(signal),
            "triggers":  [str(t) for t in triggers],
            "streak":    int(streak),
            "body_exp":  round(float(body_exp), 2),
            "range_exp": round(float(range_exp), 2),
            "avg_br":    round(float(avg_br), 2),
            "atr_proxy": round(float(avg_range), 2),
            "reason":    f"triggers={triggers} streak={int(streak)} body×{float(body_exp):.1f}",
        }
        self.last = out
        return out

    def _empty(self, reason):
        return {"score": 0, "direction": "FLAT", "whale": False, "push": False,
                "breakout": False, "bar_strong": False, "signal": False,
                "triggers": [], "streak": 0, "body_exp": 0, "range_exp": 0,
                "avg_br": 0, "atr_proxy": 0, "reason": reason}


# ═══════════════════════════════════════════════════════════════════════════
# FVG DETECTOR — finds 3-candle imbalance zones (ICT Fair Value Gaps)
# ═══════════════════════════════════════════════════════════════════════════

class FVGDetector:
    """
    Detects Fair Value Gaps: 3-candle patterns where candle[i-2] and candle[i]
    don't overlap, leaving an un-visited price zone (the FVG).

    Bullish FVG: bars[i-2].high < bars[i].low  → gap below a strong up-move
                 Price tends to return (fill) before continuing higher.
                 Enter BUY LIMIT at FVG midpoint.

    Bearish FVG: bars[i-2].low  > bars[i].high → gap above a strong down-move
                 Price tends to return (fill) before continuing lower.
                 Enter SELL LIMIT at FVG midpoint.
    """

    def detect(self, bars) -> list:
        """
        Accepts either MT5 numpy recarray (fields: open/high/low/close)
        or list of dicts (fields: o/h/l/c or open/high/low/close).
        Returns list of FVG dicts sorted freshest-first.
        """
        if bars is None or len(bars) < 3:
            return []

        try:
            if hasattr(bars[0], 'dtype') or (hasattr(bars, 'dtype')):
                highs  = [float(b['high'])  for b in bars]
                lows   = [float(b['low'])   for b in bars]
                opens  = [float(b['open'])  for b in bars]
                closes = [float(b['close']) for b in bars]
            else:
                highs  = [float(b.get('h', b.get('high',  0))) for b in bars]
                lows   = [float(b.get('l', b.get('low',   0))) for b in bars]
                opens  = [float(b.get('o', b.get('open',  0))) for b in bars]
                closes = [float(b.get('c', b.get('close', 0))) for b in bars]
        except Exception:
            return []

        n = len(bars)
        fvgs = []

        for i in range(2, n):
            body_size = abs(closes[i] - opens[i])

            # ── Bullish FVG: gap[i-2].high → [i].low (gap below price) ──
            bull_bot = highs[i - 2]
            bull_top = lows[i]
            if bull_top > bull_bot:
                size_pt = (bull_top - bull_bot) * 100
                if size_pt >= FVG_MIN_SIZE_PT:
                    age = n - 1 - i
                    if age <= FVG_MAX_AGE_BARS:
                        mid = (bull_bot + bull_top) / 2
                        fvgs.append({
                            'type':     'BUY',
                            'top':      round(bull_top, 2),
                            'bottom':   round(bull_bot, 2),
                            'mid':      round(mid, 2),
                            'size_pt':  round(size_pt, 1),
                            'age_bars': age,
                        })

            # ── Bearish FVG: gap[i].high → [i-2].low (gap above price) ──
            bear_bot = highs[i]
            bear_top = lows[i - 2]
            if bear_top > bear_bot:
                size_pt = (bear_top - bear_bot) * 100
                if size_pt >= FVG_MIN_SIZE_PT:
                    age = n - 1 - i
                    if age <= FVG_MAX_AGE_BARS:
                        mid = (bear_bot + bear_top) / 2
                        fvgs.append({
                            'type':     'SELL',
                            'top':      round(bear_top, 2),
                            'bottom':   round(bear_bot, 2),
                            'mid':      round(mid, 2),
                            'size_pt':  round(size_pt, 1),
                            'age_bars': age,
                        })

        fvgs.sort(key=lambda x: x['age_bars'])
        return fvgs

    def filter_actionable(self, fvgs: list, bid: float, ask: float) -> list:
        """Keep only FVGs that price hasn't yet entered (still un-filled)."""
        out = []
        for fvg in fvgs:
            if fvg['type'] == 'BUY':
                # BUY FVG is below current price — valid only while bid > fvg.top
                if bid > fvg['top']:
                    out.append(fvg)
            else:
                # SELL FVG is above current price — valid only while ask < fvg.bottom
                if ask < fvg['bottom']:
                    out.append(fvg)
        return out

    def summary_for_llm(self, fvgs: list) -> str:
        if not fvgs:
            return "FVG: none active"
        parts = [f"{f['type']}@{f['mid']:.2f}({f['size_pt']:.0f}pt,age={f['age_bars']}b)" for f in fvgs[:3]]
        return "FVG active: " + "  ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# POSITION MANAGER — moves SL to BE, trails, cancels stale pendings
# ═══════════════════════════════════════════════════════════════════════════

class PositionManager:
    """Dynamic management of open positions and pendings."""

    def __init__(self, trader):
        self.trader = trader
        self.state = {}     # ticket -> dict
        self.events = deque(maxlen=50)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.appendleft({"ts": ts, "msg": msg})
        print(f"[PM {ts}] {msg}")

    def _min_stop_dist(self):
        """Broker minimum stop distance (price units), incl. freeze level, + 1pt pad."""
        try:
            info = mt5.symbol_info(SYMBOL)
            if not info:
                return None
            pt = info.point or 0.01
            lvl = max(info.trade_stops_level, getattr(info, "trade_freeze_level", 0))
            return (lvl + 1) * pt   # +1pt safety pad
        except Exception:
            return None

    def manage(self, market: dict):
        if not self.trader.connected: return

        positions = self.trader.get_positions()
        pendings  = self.trader.get_pendings()
        bid = float(market.get("bid", 0)) or 0
        ask = float(market.get("ask", 0)) or 0

        # 1) Manage open positions
        for p in positions:
            self._ensure_tracked(p)
            self._move_to_breakeven(p, bid, ask)
            self._trail_stop(p, bid, ask, market)
            self._close_on_adverse(p, bid, ask, market)

        # 2) Clean dead/stale or wrong-direction pendings
        self._clean_pendings(pendings, market)

    def _ensure_tracked(self, p):
        if p.ticket not in self.state:
            side = "BUY" if p.type == 0 else "SELL"
            self.state[p.ticket] = {
                "original_sl":   p.sl,
                "original_tp":   p.tp,
                "entry":         p.price_open,
                "side":          side,
                "breakeven_set": False,
                "peak_price":    p.price_open,  # best price seen (updated every cycle)
                "trail_stage":   0,              # 0=pre-BE, 1-4=post-BE stages
                "started_ts":    time.time(),
            }
            self._log(f"track #{p.ticket} {side} @ {p.price_open:.2f} sl={p.sl:.2f}")

    def _move_to_breakeven(self, p, bid, ask):
        st = self.state[p.ticket]
        side = st["side"]
        risk = abs(st["entry"] - st["original_sl"])

        # Always track peak price (best price ever seen) — even before BE
        price_now = bid if side == "BUY" else ask
        if side == "BUY":
            if price_now > st["peak_price"]:
                st["peak_price"] = price_now
        else:
            if price_now < st["peak_price"]:
                st["peak_price"] = price_now

        if st["breakeven_set"]: return
        if st["original_sl"] <= 0 or risk <= 0: return

        profit_dist = (price_now - st["entry"]) if side == "BUY" else (st["entry"] - price_now)

        if profit_dist >= risk * BREAKEVEN_TRIGGER_R:
            buffer = risk * (BREAKEVEN_BUFFER_PCT / 100.0)
            new_sl = st["entry"] + buffer if side == "BUY" else st["entry"] - buffer

            # Respect broker minimum stop distance — the BE stop must sit at least
            # min_stop away from the current market price, else MT5 rejects it as
            # INVALID_STOPS (10016). For tiny-risk scalps entry+buffer is usually
            # inside the freeze zone, so we simply wait until price has moved far
            # enough rather than retrying (and spamming) every cycle.
            min_stop = self._min_stop_dist()
            if min_stop is not None:
                if side == "BUY" and new_sl > price_now - min_stop:
                    return    # not yet safe — try again next cycle, silently
                if side == "SELL" and new_sl < price_now + min_stop:
                    return

            if self.trader.dry_run:
                self._log(f"DRY: BE #{p.ticket} → {new_sl:.2f} (+{profit_dist:.2f}pt, {profit_dist/risk:.2f}R)")
                st["breakeven_set"] = True
                st["trail_stage"] = 1
                return

            req = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "sl":       float(new_sl),
                "tp":       float(p.tp),
                "symbol":   SYMBOL,
            }
            r = mt5.order_send(req)
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                st["breakeven_set"] = True
                st["trail_stage"] = 1
                self._log(f"✓ BE #{p.ticket} SL → {new_sl:.2f} (profit {profit_dist:.2f}pt = {profit_dist/risk:.2f}R)")
            else:
                # Throttle failure logging to once/30s per ticket so a persistent
                # rejection can't flood the event feed.
                now = time.time()
                if now - st.get("_last_be_fail_log", 0) >= 30:
                    st["_last_be_fail_log"] = now
                    self._log(f"✗ BE failed #{p.ticket}: retcode={r.retcode if r else 'None'}")

    def _trail_stop(self, p, bid, ask, market):
        st = self.state[p.ticket]
        if not st["breakeven_set"]: return    # only trail after BE locked
        side = st["side"]
        risk = abs(st["entry"] - st["original_sl"])
        if risk <= 0: return

        # profit_r uses peak_price (already updated in _move_to_breakeven)
        peak = st["peak_price"]
        profit_dist = (peak - st["entry"]) if side == "BUY" else (st["entry"] - peak)
        profit_r = profit_dist / risk

        # Multi-stage trail distance — tightens as profit grows
        if profit_r >= TRAIL_STAGE4_R:
            trail_dist = risk * TRAIL_DIST_STAGE4
            stage = 4
        elif profit_r >= TRAIL_STAGE3_R:
            trail_dist = risk * TRAIL_DIST_STAGE3
            stage = 3
        elif profit_r >= TRAIL_STAGE2_R:
            trail_dist = risk * TRAIL_DIST_STAGE2
            stage = 2
        else:
            trail_dist = risk * TRAIL_DIST_STAGE1
            stage = 1

        if stage > st["trail_stage"]:
            self._log(f"⚡ trail stage→{stage} #{p.ticket} profit={profit_r:.2f}R dist={trail_dist:.1f}pt")
            st["trail_stage"] = stage

        if side == "BUY":
            new_sl = peak - trail_dist
            if new_sl > p.sl + TRAIL_MIN_MOVE_PT:
                self._send_sltp(p, new_sl, stage)
        else:
            new_sl = peak + trail_dist
            if p.sl == 0 or new_sl < p.sl - TRAIL_MIN_MOVE_PT:
                self._send_sltp(p, new_sl, stage)

    def _send_sltp(self, p, new_sl, stage=1):
        if self.trader.dry_run:
            self._log(f"DRY: trail[s{stage}] #{p.ticket} SL→{new_sl:.2f}")
            return
        # Clamp the trailing stop to the broker minimum-stop distance from the
        # current market price, else MT5 rejects with INVALID_STOPS (10016).
        side = self.state.get(p.ticket, {}).get("side", "BUY" if p.type == 0 else "SELL")
        min_stop = self._min_stop_dist()
        if min_stop is not None:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick:
                if side == "BUY":
                    new_sl = min(new_sl, tick.bid - min_stop)
                else:
                    new_sl = max(new_sl, tick.ask + min_stop)
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "sl":       float(new_sl),
            "tp":       float(p.tp),
            "symbol":   SYMBOL,
        }
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            self._log(f"✓ trail[s{stage}] #{p.ticket} SL→{new_sl:.2f}")

    def _close_on_adverse(self, p, bid, ask, market):
        """Close position if SMC structure flipped strongly against it."""
        st  = self.state[p.ticket]
        bias = market.get("smc_bias", "")
        choch = market.get("has_choch", False)

        # If CHoCH against position direction → close at market
        side = st["side"]
        adverse = (side == "BUY" and bias == "SELL" and choch) or \
                  (side == "SELL" and bias == "BUY" and choch)
        if not adverse: return

        if self.trader.dry_run:
            self._log(f"DRY: close #{p.ticket} on CHoCH against {side}")
            return

        if side == "BUY":
            ok = self.trader._close_position(p.ticket, mt5.ORDER_TYPE_SELL, bid)
        else:
            ok = self.trader._close_position(p.ticket, mt5.ORDER_TYPE_BUY, ask)
        if ok:
            self._log(f"✓ closed #{p.ticket} on CHoCH against {side}")

    def _clean_pendings(self, pendings, market):
        bias = market.get("smc_bias", "")
        for o in pendings:
            age = time.time() - o.time_setup
            is_buy  = o.type in (mt5.ORDER_TYPE_BUY_STOP,  mt5.ORDER_TYPE_BUY_LIMIT)
            is_sell = o.type in (mt5.ORDER_TYPE_SELL_STOP, mt5.ORDER_TYPE_SELL_LIMIT)

            reason = None
            if age > 1800:                              # 30 min
                reason = "stale_30min"
            elif is_buy  and bias == "SELL":
                reason = "bias_flipped_SELL"
            elif is_sell and bias == "BUY":
                reason = "bias_flipped_BUY"

            if reason:
                if self.trader.dry_run:
                    self._log(f"DRY: cancel #{o.ticket} ({reason})")
                    continue
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                r = mt5.order_send(req)
                if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                    self._log(f"✓ cancel #{o.ticket} ({reason})")


# ═══════════════════════════════════════════════════════════════════════════
# MT5 TRADER — places real pending orders with safety
# ═══════════════════════════════════════════════════════════════════════════

class MT5Trader:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.last_order_ts = 0
        self.connected = False
        self._connect()

    def _connect(self):
        if not mt5.initialize():
            print(f"[MT5] initialize() failed: {mt5.last_error()}")
            return
        info = mt5.account_info()
        if info:
            self.connected = True
            print(f"[MT5] connected · login={info.login} balance={info.balance} trade_allowed={info.trade_allowed}")

    def is_killed(self):
        return KILL_SWITCH.exists()

    def get_symbol_info(self):
        return mt5.symbol_info(SYMBOL) if self.connected else None

    def get_pendings(self):
        """Return list of our own pending orders."""
        if not self.connected: return []
        orders = mt5.orders_get(symbol=SYMBOL) or []
        return [o for o in orders if o.magic == MAGIC]

    def get_positions(self):
        if not self.connected: return []
        pos = mt5.positions_get(symbol=SYMBOL) or []
        return [p for p in pos if p.magic == MAGIC]

    def cancel_old_pendings(self, keep_seconds=600):
        """Cancel our pendings older than N seconds."""
        if not self.connected: return 0
        cancelled = 0
        for o in self.get_pendings():
            age = time.time() - o.time_setup
            if age > keep_seconds:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                if self.dry_run:
                    print(f"[DRY] cancel order #{o.ticket} (age {age:.0f}s)")
                else:
                    mt5.order_send(req)
                cancelled += 1
        return cancelled

    def place_pending(self, side: str, price: float, sl: float, tp: float, lot: float, reason: str):
        """Place BUY_STOP or SELL_STOP at level. Returns (ok, msg, ticket)."""
        if not self.connected:
            return False, "not connected", 0
        if self.is_killed():
            return False, "kill_switch active", 0
        if time.time() - self.last_order_ts < COOLDOWN_S:
            return False, f"cooldown {int(time.time()-self.last_order_ts)}s/{COOLDOWN_S}s", 0
        if len(self.get_pendings()) + len(self.get_positions()) >= MAX_ORDERS:
            return False, "max orders reached", 0

        # Get current market
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick:
            return False, "no tick", 0

        info = mt5.symbol_info(SYMBOL)
        if not info:
            return False, "no symbol info", 0

        point = info.point
        min_stop_dist = info.trade_stops_level * point  # broker minimum

        # Validate side + price; auto-pick STOP vs LIMIT based on price vs market
        side = side.upper()
        if side == "BUY":
            # BUY above ask = STOP (breakout); BUY below ask = LIMIT (dip buy)
            if price > tick.ask + min_stop_dist:
                order_type = mt5.ORDER_TYPE_BUY_STOP
            elif price < tick.ask - min_stop_dist:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
            else:
                return False, f"BUY price too close to ask ({tick.ask:.2f}, min_dist {min_stop_dist:.2f})", 0
        elif side == "SELL":
            # SELL below bid = STOP (breakdown); SELL above bid = LIMIT (rally sell)
            if price < tick.bid - min_stop_dist:
                order_type = mt5.ORDER_TYPE_SELL_STOP
            elif price > tick.bid + min_stop_dist:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
            else:
                return False, f"SELL price too close to bid ({tick.bid:.2f}, min_dist {min_stop_dist:.2f})", 0
        else:
            return False, f"bad side {side}", 0

        # Clamp lot
        lot = max(MIN_LOT, min(MAX_LOT, lot))
        lot = round(lot / info.volume_step) * info.volume_step
        lot = max(info.volume_min, min(info.volume_max, lot))

        # Validate SL/TP distance
        if side == "BUY":
            if sl >= price or tp <= price: return False, "invalid SL/TP for BUY", 0
        else:
            if sl <= price or tp >= price: return False, "invalid SL/TP for SELL", 0

        # MT5 only accepts ASCII in comment — strip non-ASCII (Arabic etc.)
        ascii_reason = "".join(ch for ch in reason if 32 <= ord(ch) < 127)[:20].strip() or "auto"
        req = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       SYMBOL,
            "volume":       float(lot),
            "type":         order_type,
            "price":        float(price),
            "sl":           float(sl),
            "tp":           float(tp),
            "magic":        MAGIC,
            "comment":      f"FRIDAY {ascii_reason}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if self.dry_run:
            self._log_order("DRY", side, price, sl, tp, lot, reason, "dry-run")
            return True, "DRY-RUN", 0

        result = mt5.order_send(req)
        if result is None:
            return False, f"order_send None: {mt5.last_error()}", 0
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self._log_order("FAIL", side, price, sl, tp, lot, reason, f"retcode={result.retcode}")
            return False, f"retcode={result.retcode} comment={result.comment}", 0

        self.last_order_ts = time.time()
        self._log_order("LIVE", side, price, sl, tp, lot, reason, f"ticket={result.order}")
        return True, "OK", result.order

    def _close_position(self, ticket: int, close_type, price) -> bool:
        """Close an open position at market."""
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return False
        p = pos[0]
        req = {
            "action":   mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol":   SYMBOL,
            "volume":   p.volume,
            "type":     close_type,
            "price":    float(price),
            "deviation": 50,
            "magic":    MAGIC,
            "comment":  "FRIDAY close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)

    def place_scalp_now(self, side: str, atr_proxy: float, market: dict, reason: str):
        """Fast-path scalp order — tight SL/TP based on ATR, market direction."""
        if not self.connected: return False, "not_connected"
        if self.is_killed(): return False, "killed"
        # short cooldown for scalp: 12s
        if time.time() - self.last_order_ts < 12:
            return False, "scalp_cooldown"
        if len(self.get_pendings()) + len(self.get_positions()) >= MAX_ORDERS:
            return False, "max_orders"

        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if not tick or not info: return False, "no_tick"
        min_stop = info.trade_stops_level * info.point

        atr = max(atr_proxy, 2.0)   # avoid zero
        # Tight: SL = 0.8 × ATR, TP = 2.0 × ATR (R:R 1:2.5)
        sl_dist = atr * 0.8
        tp_dist = atr * 2.0

        if side == "BUY":
            entry = tick.ask + max(min_stop, atr * 0.1)
            sl    = entry - sl_dist
            tp    = entry + tp_dist
            order_type = mt5.ORDER_TYPE_BUY_STOP
        elif side == "SELL":
            entry = tick.bid - max(min_stop, atr * 0.1)
            sl    = entry + sl_dist
            tp    = entry - tp_dist
            order_type = mt5.ORDER_TYPE_SELL_STOP
        else:
            return False, f"bad_side_{side}"

        lot = ClampLot_static(MIN_LOT)  # smallest lot for scalps

        ascii_reason = "SCALP " + "".join(ch for ch in reason if 32 <= ord(ch) < 127)[:15]
        req = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       SYMBOL,
            "volume":       float(lot),
            "type":         order_type,
            "price":        float(entry),
            "sl":           float(sl),
            "tp":           float(tp),
            "magic":        MAGIC,
            "comment":      ascii_reason,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if self.dry_run:
            self._log_order("DRY-SCALP", side, entry, sl, tp, lot, reason, "scalp-dry")
            return True, "DRY"

        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            self.last_order_ts = time.time()
            self._log_order("SCALP", side, entry, sl, tp, lot, reason, f"ticket={r.order}")
            return True, f"ticket={r.order}"
        else:
            self._log_order("SCALP_FAIL", side, entry, sl, tp, lot, reason,
                            f"retcode={r.retcode if r else 'None'}")
            return False, f"retcode={r.retcode if r else 'None'}"

    def _log_order(self, kind, side, price, sl, tp, lot, reason, note):
        ts = datetime.now().isoformat()
        line = f"{ts},{kind},{side},{price:.2f},{sl:.2f},{tp:.2f},{lot:.2f},\"{reason}\",\"{note}\"\n"
        if not ORDERS_LOG.exists():
            ORDERS_LOG.write_text("ts,kind,side,price,sl,tp,lot,reason,note\n", encoding="utf-8")
        with open(ORDERS_LOG, "a", encoding="utf-8") as f:
            f.write(line)
        print(f"[{kind}] {side} @ {price:.2f}  SL={sl:.2f} TP={tp:.2f} lot={lot:.2f}  | {reason}  | {note}")


# ═══════════════════════════════════════════════════════════════════════════
# AGENT DEFINITIONS — 5 distinct personas
# ═══════════════════════════════════════════════════════════════════════════

AGENT_DEFS = [
    {
        "name": "HUNTER",
        "emoji": "🎯",
        "model": DEEP_MODEL,
        "system": """أنت HUNTER — صياد المستويات. تدرس الشموع، تحدد المستويات السعرية القوية،
وتقترح أوامر pending عند هذه المستويات.

## مستويات Fractal (أولوية أولى):
بيانات السوق تحتوي على: fractal_dir, fractal_last_high, fractal_last_low, fractal_high_age, fractal_low_age, fractal_signal_active.

- fractal_dir=bull AND fractal_signal_active=true → Stop Buy فوق fractal_last_high + 1pt
  (السيولة فوق الـ fractal high محشودة — الكسر يشغّلها وقوداً للصعود)
- fractal_dir=bear AND fractal_signal_active=true → Stop Sell تحت fractal_last_low - 1pt
- fractal_high_age أو fractal_low_age > 20 → الـ fractal قديم، ابحث عن مستوى غيره
- fractal_signal_active=false → الفرصة على هذا الـ fractal انتهت، لا تدخل عليه
- لو fractal_dir=neutral → لا تعتمد على fractal level، استخدم swing high/low فقط

## المستويات الأخرى (أولوية ثانية):
- swing high/low (قوة مضاعفة إذا تقاطع مع fractal level)
- previous day H/L
- order blocks قريبة من fractal level

لا تخف من السبريد العالي — اقترح TP يتجاوز السبريد بـ 3× على الأقل.
اختر مستويين كحد أقصى. الأولوية للمستوى الذي يتوافق فيه fractal + SMC."""
    },
    {
        "name": "STRUCTURE",
        "emoji": "🏗",
        "model": DEEP_MODEL,
        "system": """أنت STRUCTURE — محلل البنية. تفسّر SMC (Smart Money Concepts): BOS, CHoCH, order blocks, fair value gaps.
تؤكد أو ترفض اقتراحات HUNTER بناءً على بنية السوق.

## قراءة Fractal Direction (أولوية عالية)
بيانات السوق تحتوي على: fractal_dir (bull/bear/neutral), fractal_last_high, fractal_last_low, fractal_high_age, fractal_low_age, fractal_signal_active, fractal_confidence.

قواعد الدمج مع SMC:
- fractal=bull + smc_bias=BUY → STRONG BUY (ثقة عالية) — ادعم HUNTER بقوة
- fractal=bull + smc_bias=SELL → CONFLICT — قل "انتظر CHoCH أو BOS تأكيد"
- fractal=bear + smc_bias=SELL → STRONG SELL (ثقة عالية) — ادعم SELL بقوة
- fractal=bear + smc_bias=BUY → CONFLICT — قل "انتظر BOS لأعلى يؤكد"
- fractal=neutral → ثقة منخفضة ≤ 0.45، أشر لذلك صراحةً

دمج Footprint Delta:
- fractal=bull + cumDelta>0 → شراء مؤسسي مؤكد، ادعم BUY بقوة
- fractal=bull + cumDelta<0 → تحذير توزيع، نبّه HUNTER
- fractal=bear + cumDelta<0 → بيع مؤسسي مؤكد، ادعم SELL بقوة
- fractal=bear + cumDelta>0 → تحذير تراكم، نبّه HUNTER

## البنية الكلاسيكية:
- BOS لأعلى → دعم BUY عند OB/FVG أو swing low القريب
- CHoCH → إشارة انعكاس أقوى من الـ fractal — أعطها الأولوية
أعطِ مستوى واحد دعماً للبنية مع ذكر fractal_confidence.

## Fair Value Gaps (FVG) — أولوية للدخول السريع
بيانات السوق قد تحتوي على FVG active zones (imbalance zones من 3 شموع).
- FVG BUY below price + fractal_dir=bull + smc_bias=BUY → ادعم BUY LIMIT بقوة (أفضل دخول)
- FVG SELL above price + fractal_dir=bear + smc_bias=SELL → ادعم SELL LIMIT بقوة
- FVG يعاكس الـ bias → حذّر الفريق، لا تدعم الدخول
- FVG يتداخل مع OB أو swing level → ثقة أعلى
اذكر FVG في الـ say إذا كان نشطاً ومهماً."""
    },
    {
        "name": "MOMENTUM",
        "emoji": "⚡",
        "model": FAST_MODEL,
        "system": """أنت MOMENTUM — قارئ الزخم. تدرس RSI، ATR، spread، التحرك الأخير.
تخبر الفريق إن كان الزخم يدعم الدخول أم لا.
ATR منخفض + spread عالي = WAIT. ATR عالي + trend واضح = ادعم HUNTER.
لا تقترح مستويات بنفسك — فقط ادعم/ارفض البقية برسالة موجزة."""
    },
    {
        "name": "RISK",
        "emoji": "🛡",
        "model": FAST_MODEL,
        "system": """أنت RISK — حارس المخاطر. تراقب الخسائر المتتالية، نسبة الـ equity،
وتمنع الدخول الخطر. veto=true في الحالات الحرجة:
- loss_streak >= 3
- equity تحت 80% من الـ balance
- positions >= 4
- spread > 500pt
كل صفقة يجب أن يكون SL واضحاً، حجم Lot لا يتجاوز 0.02 لكل دخول."""
    },
    {
        "name": "CHARTIST",
        "emoji": "🎨",
        "model": DEEP_MODEL,
        "system": """أنت CHARTIST — رسّام محترف للشارت. تعمل مثل محلل تقني خبير يرسم على الشارت بالـ Objects.

تنتج drawings مفصّلة تُرسم تلقائياً على الشارت. الأنواع المدعومة:

1. **hline** — خط أفقي (مستوى رئيسي، POC، VWAP):
   {"type":"hline", "price":4548.50, "color":"#a855f7", "label":"key 4548"}

2. **trendline** — خط اتجاه يصل نقطتين عبر الزمن:
   {"type":"trendline", "from":{"bars_ago":15,"price":4520.00}, "to":{"bars_ago":2,"price":4548.00},
    "color":"#fbbf24", "label":"bull trend"}

3. **zone** — منطقة طلب/عرض (مستطيل سعري):
   {"type":"zone", "top":4555.00, "bottom":4548.00, "color":"#10b981", "label":"demand"}
   (color: أخضر للطلب، أحمر للعرض، بنفسجي لـ OB)

4. **fib** — تراجع فيبوناتشي بين high و low:
   {"type":"fib", "high":4560.00, "low":4520.00, "label":"fib 1H"}
   (سيرسم 0% 23.6 38.2 50 61.8 78.6 100% تلقائياً)

5. **marker** — علامة على شمعة (سهم، نجمة، دائرة):
   {"type":"marker", "bars_ago":3, "shape":"arrowUp|arrowDown|circle", "color":"#22d3ee", "label":"BOS"}

6. **channel** — قناة سعرية (خطين متوازيين):
   {"type":"channel", "from":{"bars_ago":20,"price":4515}, "to":{"bars_ago":0,"price":4548},
    "width":12, "color":"#22d3ee", "label":"ascending channel"}

مهمتك كل دورة: ارسم 3-6 objects تُلخّص بنية السوق الحالية مثل محترف.
ركّز على:
- آخر swing high/low (hline)
- اتجاه آخر 15-20 شمعة (trendline)
- منطقة طلب/عرض قريبة (zone)
- fib لو في تصحيح واضح
- BOS/CHoCH إذا حدث (marker)

أعطِ stance + confidence على البنية ككل.
JSON output كاملاً (drawings تكون مصفوفة من 3-6 عناصر)."""
    },
    {
        "name": "COORDINATOR",
        "emoji": "🧠",
        "model": DEEP_MODEL,
        "system": """أنت COORDINATOR — المنسق الأخير. تقرأ كل آراء الفريق، ثم تتخذ القرار النهائي.
إذا 3 من 4 وكلاء يدعمون مستوى، ولا veto من RISK → اعتمده.
output JSON: {{"final_action":"PLACE|WAIT|CANCEL_ALL", "side":"BUY|SELL",
              "entry":4555.50, "sl":4548.00, "tp":4570.00, "lot":0.01,
              "reason":"إجماع الفريق على ..."}}
السلامة أهم من الجرأة. لو في شك، WAIT."""
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# MAIN BRAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

class Brain:
    def __init__(self, live=False):
        self.bus    = Bus()
        self.trader = MT5Trader(dry_run=not live)
        self.agents = [LLMAgent(a["name"], a["emoji"], a["model"], a["system"], self.bus)
                       for a in AGENT_DEFS if a["name"] != "COORDINATOR"]
        coord_def = next(a for a in AGENT_DEFS if a["name"] == "COORDINATOR")
        self.coordinator = LLMAgent(coord_def["name"], coord_def["emoji"],
                                    coord_def["model"], coord_def["system"], self.bus)
        self.cycle = 0
        self.proposed_levels = []
        self.drawings = []   # CHARTIST's drawing objects
        self.last_decision = {}
        self.position_mgr  = PositionManager(self.trader)
        self.momentum      = MomentumDetector()
        self.fvg_detector  = FVGDetector()
        self.last_scalp_ts = 0
        self.scalps        = []   # log of scalp attempts
        self._last_fvg_ts  = 0
        self.fvg_last      = []   # most recent detected FVGs
        self.fvg_entries   = []   # log of FVG limit order attempts

    def _try_scalp(self, mom: dict, market: dict) -> bool:
        """Attempt a scalp entry if momentum signals fire. Returns True if order placed."""
        if not mom.get("signal"): return False
        if mom.get("score", 0) < 35: return False
        if (time.time() - self.last_scalp_ts) < 15: return False

        side = "BUY" if mom["direction"] == "UP" else "SELL" if mom["direction"] == "DOWN" else None
        if side is None: return False

        # Spread guard for scalps
        spread_pt = market.get("spread_pt", 0)
        if spread_pt > 450:
            print(f"  ⚡ scalp blocked: spread {spread_pt}pt > 450pt")
            return False

        # Skip if SMC bias contradicts strongly
        bias = market.get("smc_bias", "")
        if (side == "BUY"  and bias == "SELL") or (side == "SELL" and bias == "BUY"):
            # Allow if the trigger is BREAKOUT (often precedes bias flip)
            if not mom.get("breakout"):
                print(f"  ⚡ scalp blocked: {side} vs bias {bias} (no breakout)")
                return False

        trigger_label = "+".join(mom.get("triggers", []))
        reason = f"{trigger_label} streak={mom['streak']}"

        ok, msg = self.trader.place_scalp_now(side, mom["atr_proxy"], market, reason)
        self.scalps.append({
            "ts":       datetime.now().strftime("%H:%M:%S"),
            "side":     side, "score": mom["score"],
            "triggers": mom.get("triggers", []),
            "result":   msg, "ok": ok,
        })
        self.scalps = self.scalps[-20:]
        if ok:
            self.last_scalp_ts = time.time()
            print(f"  ⚡ SCALP placed: {side} ({trigger_label}) → {msg}")
        else:
            print(f"  ⚡ scalp rejected: {msg}")
        return ok

    def _fvg_detect_and_place(self, market: dict) -> bool:
        """
        Detect fresh un-filled FVGs and place LIMIT orders at their midpoint.
        This is the fast-reaction path: no LLM involved, pure price structure.
        Returns True if a limit order was placed.
        """
        if not FVG_ENABLED:
            return False
        if (time.time() - self._last_fvg_ts) < FVG_COOLDOWN_S:
            return False

        spread_pt = market.get('spread_pt', 0)
        if spread_pt > FVG_MAX_SPREAD:
            return False

        # Prefer live MT5 bars (freshest); fall back to EA JSON
        bars = None
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 25)
            if rates is not None and len(rates) >= 10:
                bars = rates
        except Exception:
            pass
        if bars is None:
            bars = market.get('last_bars', [])

        fvgs = self.fvg_detector.detect(bars)
        self.fvg_last = fvgs  # save for state / LLM context

        if not fvgs:
            return False

        bid = float(market.get('bid', 0))
        ask = float(market.get('ask', 0))
        actionable = self.fvg_detector.filter_actionable(fvgs, bid, ask)
        if not actionable:
            return False

        # Prefer FVG aligned with SMC bias; otherwise take freshest
        smc_bias = market.get('smc_bias', '')
        best = None
        for fvg in actionable:
            if (fvg['type'] == 'BUY' and smc_bias == 'BUY') or \
               (fvg['type'] == 'SELL' and smc_bias == 'SELL'):
                best = fvg
                break
        if best is None:
            best = actionable[0]

        # Build entry / SL / TP
        entry   = best['mid']
        buf_pr  = FVG_SL_BUFFER_PT / 100.0   # points → price for gold (point=0.01)
        side    = best['type']

        if side == 'BUY':
            sl   = best['bottom'] - buf_pr
            risk = entry - sl
            tp   = entry + risk * FVG_TP_RR
        else:
            sl   = best['top'] + buf_pr
            risk = sl - entry
            tp   = entry - risk * FVG_TP_RR

        if risk <= 0:
            return False

        # Enforce minimum SL distance (same as system-wide guard)
        min_sl_dist = getattr(cfg, 'MIN_SL_DISTANCE_PT', 80) / 100.0
        if risk < min_sl_dist:
            print(f"  🎯 FVG skip: SL dist {risk*100:.0f}pt < min {min_sl_dist*100:.0f}pt")
            return False

        reason = f"FVG{side} {best['size_pt']:.0f}pt a={best['age_bars']}b"
        ok, msg, ticket = self.trader.place_pending(side, entry, sl, tp, MIN_LOT, reason)

        entry_rec = {
            'ts':     datetime.now().strftime('%H:%M:%S'),
            'type':   side,
            'entry':  round(entry, 2),
            'sl':     round(sl, 2),
            'tp':     round(tp, 2),
            'fvg_size': best['size_pt'],
            'age_bars': best['age_bars'],
            'result': msg,
            'ok':     ok,
        }
        self.fvg_entries.append(entry_rec)
        self.fvg_entries = self.fvg_entries[-20:]

        if ok:
            self._last_fvg_ts = time.time()
            print(f"  🎯 FVG LIMIT {side} @ {entry:.2f}  SL={sl:.2f} TP={tp:.2f}"
                  f"  [{best['size_pt']:.0f}pt gap, age={best['age_bars']}b] → {msg}")
        else:
            print(f"  🎯 FVG rejected: {msg}")
        return ok

    def fast_scalp_loop(self):
        """Sub-loop running every 3s — momentum scalp + FVG limit checks, no LLM."""
        while True:
            try:
                if not self.trader.is_killed():
                    market = read_market_context()
                    mom = self.momentum.analyze(market)
                    self._try_scalp(mom, market)
                    self._fvg_detect_and_place(market)
            except Exception as e:
                print(f"  [scalp loop error] {e}")
            time.sleep(3)

    def run_cycle(self):
        self.cycle += 1
        market = read_market_context()

        print(f"\n{'═'*70}")
        print(f"  CYCLE #{self.cycle}  [{datetime.now():%H:%M:%S}]  "
              f"Price={market['bid']:.2f}  Spread={market['spread_pt']:.0f}pt  "
              f"Bias={market['smc_bias']}")
        print('═'*70)

        # ── Phase 0a: Manage open positions + clean stale pendings ──
        try:
            self.position_mgr.manage(market)
        except Exception as e:
            print(f"  [PM error] {e}")

        # ── Phase 0b: Momentum / scalp fast-path (4 triggers) + FVG limits ──
        try:
            mom = self.momentum.analyze(market)
            trig_str = "+".join(mom.get("triggers", [])) or "—"
            print(f"  ⚡ momentum: score={mom['score']} dir={mom['direction']} "
                  f"triggers=[{trig_str}] streak={mom['streak']} body×{mom['body_exp']}")

            self._try_scalp(mom, market)
            self._fvg_detect_and_place(market)

            # Inject FVG zones into market context for LLM agents
            if self.fvg_last:
                market['fvg_zones'] = self.fvg_last
                print(f"  🎯 {self.fvg_detector.summary_for_llm(self.fvg_last)}")
        except Exception as e:
            print(f"  [momentum error] {e}")

        # === Phase 1: Each specialist thinks (in parallel via threads) ===
        results = {}
        threads = []
        def runner(ag):
            out = ag.think(market, self.bus.recent(n=15, topic="dialogue"))
            results[ag.name] = out

        for ag in self.agents:
            t = threading.Thread(target=runner, args=(ag,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=40)

        # Print specialist outputs (defensive — LLM may return non-string fields)
        for name, out in results.items():
            ag = next(a for a in self.agents if a.name == name)
            stance = str(out.get("stance", "—"))[:6]
            try:    conf = int(out.get("confidence", 0) or 0)
            except: conf = 0
            say    = str(out.get("say", ""))[:90]
            veto   = " 🚫VETO" if out.get("veto") else ""
            print(f"  {ag.emoji} {name:<10} {stance:<5} {conf:>3d}%{veto}  → {say}")

        # === Phase 2: Coordinator synthesizes ===
        peer_lines = []
        for name, out in results.items():
            peer_lines.append(
                f"{name} ({out.get('stance','?')} {out.get('confidence',0)}%, "
                f"veto={out.get('veto',False)}): {out.get('say','')[:90]}"
                + (" LEVELS=" + str(out.get("levels", []))[:120] if out.get("levels") else "")
            )
        coord_user = f"""=== السوق ===
{market_summary_for_llm(market)}

=== آراء الفريق ===
{chr(10).join(peer_lines)}

=== مهمتك ===
خذ القرار النهائي. JSON فقط:
{{"final_action":"PLACE|WAIT|CANCEL_ALL", "side":"BUY|SELL",
  "entry":<price>, "sl":<price>, "tp":<price>, "lot":0.01,
  "reason":"<السبب القصير>"}}
لو final_action=WAIT أو CANCEL_ALL، أعطِ entry/sl/tp = 0."""

        coord_raw  = llm_chat(self.coordinator.model, self.coordinator.system, coord_user,
                              timeout=60, use_claude=USE_CLAUDE_FOR_COORDINATOR)
        decision   = extract_json(coord_raw) or {"final_action": "WAIT", "reason": "no parse"}
        self.last_decision = decision

        self.bus.post("COORDINATOR", "decision", decision)

        action = decision.get("final_action", "WAIT")
        print(f"\n  🧠 COORDINATOR → {action}  {decision.get('reason','')[:100]}")

        # === Phase 2.5: SAFETY GATES (regime + memory + caps) ===
        if HAS_LEARNING and action == "PLACE":
            # Refresh memory from MT5 first (catch any new closed trades)
            try: memory.sync_from_mt5(hours_back=2)
            except Exception as e: print(f"  [memory sync error] {e}")

            # Run safety check
            safety = memory.safety_check(force_paper=self.trader.dry_run)
            if not safety["allowed"]:
                print(f"  🚫 SAFETY BLOCK: {' | '.join(safety['reasons'])}")
                # Log this as a "block" event
                action = "WAIT"
                decision["final_action"] = "WAIT"
                decision["reason"] = "SAFETY BLOCK: " + " | ".join(safety["reasons"])[:80]

            # Regime check
            if action == "PLACE":
                try:
                    reg = regime.classify_regime()
                    if not reg["allow_trade"]:
                        print(f"  🌪 REGIME BLOCK ({reg['regime']}): {' | '.join(reg['reasons'])}")
                        action = "WAIT"
                        decision["final_action"] = "WAIT"
                        decision["reason"] = f"REGIME={reg['regime']}: " + " | ".join(reg["reasons"])[:80]
                    else:
                        print(f"  ✓ regime OK: {reg['regime']} (score {reg['score']})")
                except Exception as e:
                    print(f"  [regime error] {e}")

            # Setup confidence modifier from memory
            if action == "PLACE":
                try:
                    mom_state = self.momentum.last if hasattr(self.momentum, 'last') else {}
                    sig = memory.setup_signature(decision, market, mom_state)
                    mult, reason_mem = memory.setup_confidence_modifier(sig)
                    print(f"  📚 memory: setup={sig[:40]} mult={mult:.2f} ({reason_mem})")
                    if mult == 0.0:
                        action = "WAIT"
                        decision["final_action"] = "WAIT"
                        decision["reason"] = f"MEMORY REJECT: {reason_mem}"
                        print(f"  ⛔ MEMORY REJECTS this setup")
                    elif mult < 1.0:
                        # Halve lot size for low-confidence setups
                        decision["lot"] = max(MIN_LOT, float(decision.get("lot", MIN_LOT)) * mult)
                        print(f"  ⤓ lot reduced by memory: {decision['lot']:.2f}")
                except Exception as e:
                    print(f"  [memory check error] {e}")

            # Kelly criterion lot sizing
            if action == "PLACE" and HAS_LEARNING:
                kelly_mult = memory.kelly_lot_multiplier()
                old_lot = float(decision.get("lot", MIN_LOT))
                new_lot = max(MIN_LOT, old_lot * kelly_mult)
                if abs(new_lot - old_lot) > 0.001:
                    print(f"  ⚖ kelly: {old_lot:.2f} × {kelly_mult:.2f} = {new_lot:.2f}")
                    decision["lot"] = new_lot

        # === Phase 3: Execute ===
        if any(r.get("veto") for r in results.values()):
            print("  🚫 RISK veto active → skipping execution")
        elif action == "PLACE":
            side  = decision.get("side", "").upper()
            entry = float(decision.get("entry", 0) or 0)
            sl    = float(decision.get("sl", 0)    or 0)
            tp    = float(decision.get("tp", 0)    or 0)
            lot   = float(decision.get("lot", MIN_LOT) or MIN_LOT)
            reason = decision.get("reason", "")[:50]

            # ── AUTO-CORRECT inverted SL/TP from LLM mistakes ──
            corrected = False
            if side == "BUY":
                if sl > entry and tp < entry:
                    # Fully swapped
                    sl, tp = tp, sl
                    corrected = True
                elif sl > entry:
                    # SL on wrong side — mirror it below entry
                    sl = entry - abs(sl - entry)
                    corrected = True
                elif tp > 0 and tp < entry:
                    tp = entry + abs(entry - tp)
                    corrected = True
            elif side == "SELL":
                if sl < entry and tp > entry:
                    sl, tp = tp, sl
                    corrected = True
                elif sl < entry and sl > 0:
                    sl = entry + abs(entry - sl)
                    corrected = True
                elif tp > entry and tp > 0:
                    tp = entry - abs(tp - entry)
                    corrected = True
            if corrected:
                print(f"  🔧 auto-corrected SL/TP for {side}: entry={entry:.2f} sl={sl:.2f} tp={tp:.2f}")
                reason = "[AUTO-FIXED] " + reason

            # Profit check: expected move must beat spread × multiplier
            spread = market["spread_pt"]
            expected_move_pt = abs(tp - entry) * 100  # rough for gold (point=0.01)
            risk_pt   = abs(entry - sl) * 100
            reward_pt = abs(tp - entry) * 100
            rr_ratio  = reward_pt / risk_pt if risk_pt > 0 else 0

            skip_reason = None
            if expected_move_pt < spread * MIN_SPREAD_TO_MOVE_MULT:
                skip_reason = f"tp_move({expected_move_pt:.0f}pt)<3x_spread({spread:.0f}pt)"
            elif rr_ratio < MIN_RR_RATIO:
                skip_reason = f"R:R 1:{rr_ratio:.2f} < min 1:{MIN_RR_RATIO}"
            elif risk_pt < 50:
                skip_reason = f"risk too small ({risk_pt:.0f}pt) — likely LLM error"

            if skip_reason:
                print(f"  ⏸ skip: {skip_reason}")
                try:
                    if not ORDERS_LOG.exists():
                        ORDERS_LOG.write_text("ts,kind,side,price,sl,tp,lot,reason,note\n", encoding="utf-8")
                    with open(ORDERS_LOG, "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now().isoformat()},SKIP,{side},{entry:.2f},{sl:.2f},{tp:.2f},{lot:.2f},\"{reason}\",\"{skip_reason}\"\n")
                except: pass
            else:
                ok, msg, ticket = self.trader.place_pending(side, entry, sl, tp, lot, reason)
                emoji = "✅" if ok else "❌"
                print(f"  {emoji} place {side} {entry:.2f} → {msg} (ticket={ticket})")
                # Log every attempt (success or fail) to CSV
                if not ok:
                    try:
                        if not ORDERS_LOG.exists():
                            ORDERS_LOG.write_text("ts,kind,side,price,sl,tp,lot,reason,note\n", encoding="utf-8")
                        with open(ORDERS_LOG, "a", encoding="utf-8") as f:
                            f.write(f"{datetime.now().isoformat()},REJECT,{side},{entry:.2f},{sl:.2f},{tp:.2f},{lot:.2f},\"{reason}\",\"{msg}\"\n")
                    except: pass

        elif action == "CANCEL_ALL":
            n = self.trader.cancel_old_pendings(keep_seconds=0)
            print(f"  🗑 cancelled {n} pendings")

        # === Phase 4: Aggregate levels for dashboard ===
        all_levels = []
        for name, out in results.items():
            for lv in (out.get("levels") or []):
                if isinstance(lv, dict) and lv.get("price"):
                    all_levels.append({
                        "agent": name,
                        "side":  lv.get("side", "?"),
                        "price": float(lv["price"]),
                        "reason": lv.get("reason", "")[:60],
                        "ts":    datetime.now().strftime("%H:%M:%S"),
                    })
        self.proposed_levels = (self.proposed_levels + all_levels)[-30:]

        # Aggregate drawings (mainly from CHARTIST, but any agent can emit)
        fresh_drawings = []
        for name, out in results.items():
            for d in (out.get("drawings") or []):
                if isinstance(d, dict) and d.get("type"):
                    fresh_drawings.append({
                        "agent": name,
                        "ts":    datetime.now().strftime("%H:%M:%S"),
                        **d,
                    })
        # Replace each cycle (drawings are a fresh snapshot of structure)
        if fresh_drawings:
            self.drawings = fresh_drawings

        # === Phase 5: Persist state for dashboard ===
        self._save_state(market, results, decision)

    def _save_state(self, market, results, decision):
        # Bus messages
        BUS_FILE.write_text(json.dumps(self.bus.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        # Levels
        LEVELS_FILE.write_text(json.dumps(self.proposed_levels, ensure_ascii=False, indent=2), encoding="utf-8")
        # Brain state
        try:
            pendings = [{"ticket": o.ticket, "type": int(o.type), "price": o.price_open,
                         "sl": o.sl, "tp": o.tp, "volume": o.volume_initial,
                         "comment": o.comment, "time": o.time_setup}
                        for o in self.trader.get_pendings()]
            positions = [{"ticket": p.ticket, "type": int(p.type), "price": p.price_open,
                          "sl": p.sl, "tp": p.tp, "volume": p.volume,
                          "profit": p.profit, "comment": p.comment}
                         for p in self.trader.get_positions()]
        except Exception:
            pendings, positions = [], []

        state = {
            "ts":      datetime.now().isoformat(),
            "cycle":   self.cycle,
            "live":    not self.trader.dry_run,
            "killed":  self.trader.is_killed(),
            "market":  market,
            "agents":  [{"name": ag.name, "emoji": ag.emoji, "model": ag.model,
                         "cycles": ag.cycles, "last_message": ag.last_message,
                         "last": results.get(ag.name, {})} for ag in self.agents],
            "coordinator": {"emoji": self.coordinator.emoji,
                            "model": self.coordinator.model,
                            "last_decision": decision},
            "levels":    self.proposed_levels[-15:],
            "drawings":  self.drawings,
            "pendings":  pendings,
            "positions": positions,
            "dialogue":  self.bus.recent(20),
            "momentum":   self.momentum.last,
            "scalps":     self.scalps[-10:],
            "fvg_zones":  self.fvg_last[:5],
            "fvg_entries": self.fvg_entries[-10:],
            "pm_events":  list(self.position_mgr.events)[:15],
        }
        BRAIN_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── Compact EA-facing JSON (for FRIDAY_Brain_Executor.mq5) ──
        ea_payload = {
            "epoch":    int(time.time()),
            "cycle":    self.cycle,
            "killed":   self.trader.is_killed(),
            "symbol":   SYMBOL,
            "magic":    MAGIC,
            "decision": decision or {},
            "drawings": self.drawings,
            "levels":   self.proposed_levels[-10:],
            "spread_pt": market.get("spread_pt", 0),
            "bid":       market.get("bid", 0),
            "ask":       market.get("ask", 0),
        }
        try:
            EA_ORDERS.parent.mkdir(parents=True, exist_ok=True)
            EA_ORDERS.write_text(json.dumps(ea_payload, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[EA-JSON write error] {e}")

    def _preload_models(self):
        """Warm up Ollama models so first cycle isn't slow."""
        models = {a.model for a in self.agents} | {self.coordinator.model}
        for m in models:
            try:
                print(f"  pre-warming {m}...", end=" ", flush=True)
                r = requests.post(
                    OLLAMA_URL.replace("/chat", "/generate"),
                    json={"model": m, "prompt": "hi", "stream": False, "keep_alive": "60m"},
                    timeout=120,
                )
                print("OK" if r.status_code == 200 else f"status={r.status_code}")
            except Exception as e:
                print(f"warn ({e})")

    def loop(self):
        print(f"\n{'='*70}")
        print(f"  FRIDAY BRAIN v2 — LLM-powered, continuous, networked")
        print(f"{'='*70}")
        print(f"  Mode:    {'🔴 LIVE' if not self.trader.dry_run else '🟢 PAPER (dry-run)'}")
        print(f"  Agents:  {[a.name for a in self.agents]} + COORDINATOR")
        print(f"  Models:  fast={FAST_MODEL}  deep={DEEP_MODEL}")
        print(f"  Cycle:   every {CYCLE_SECONDS}s")
        print(f"  Kill:    create '{KILL_SWITCH.name}' to halt")
        print(f"  Scalp loop: running every 3s in background thread")
        print(f"{'='*70}")
        print()

        # Warm models so first cycle has hot models loaded
        self._preload_models()
        print()

        # Start the fast scalp sub-loop (runs in parallel, checks momentum every 3s)
        scalp_thread = threading.Thread(target=self.fast_scalp_loop, daemon=True)
        scalp_thread.start()

        while True:
            try:
                if self.trader.is_killed():
                    print(f"[{datetime.now():%H:%M:%S}] 🛑 KILL SWITCH active — sleeping")
                else:
                    self.run_cycle()
            except Exception as e:
                print(f"[{datetime.now():%H:%M:%S}] cycle error: {e}")
                import traceback; traceback.print_exc()
            time.sleep(CYCLE_SECONDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="execute real orders (default: dry-run)")
    ap.add_argument("--kill", action="store_true", help="create kill switch and exit")
    args = ap.parse_args()

    if args.kill:
        KILL_SWITCH.write_text(f"killed at {datetime.now()}", encoding="utf-8")
        print(f"🛑 kill switch created: {KILL_SWITCH}")
        return

    if KILL_SWITCH.exists():
        print(f"⚠ kill switch exists at {KILL_SWITCH}. Remove it to enable trading.")

    brain = Brain(live=args.live)
    brain.loop()


if __name__ == "__main__":
    main()
