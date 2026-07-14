"""runtime/unified_trader.py — ONE process that does it all.

Born 2026-05-28 because: "هل نقدر نشغل نظام واحد الحين؟" + "كلهم".

REPLACES IN ONE LOOP:
  • claude_genome_trader     (genome-driven entry)
  • claude_simple_trader     (aggressive entry)
  • claude_smart_trader      (filtered entry)
  • trailing_stop_manager    (universal SL trail — for OWN positions only)

INHERITS FROM:
  • brain_v1.py              → reads brain_live.json
  • regime_classifier.py     → reads market_regime.json
  • trader_orchestrator.py   → reads active_engines.json (gate)
  • genome_promoter.py       → reads live_genome.json
  • shared/orchestrator_gate → uses it before firing
  • shared/circuit_breaker   → uses it before firing
  • shared/decision_log      → logs every decision
  • shared/contracts         → TradeSignal validation

WHAT IT DOESN'T DO (still external):
  • brain_v1 capture         (other systems consume brain_live.json)
  • regime classification    (R Native uses regime too)
  • orchestrator decision    (it's the source of truth)
  • genome evolution         (background GA)

PHILOSOPHY:
  One main loop. No threads. No async. Easy to reason about, easy to debug.
  Every 3 seconds:
    1. Read brain_live + market_regime + live_genome
    2. Check gates (orchestrator + circuit breaker)
    3. Evaluate genome's rules → BUY / SELL / WAIT
    4. If signal: record decision, order_send, mark breaker, log ticket
    5. Manage existing positions: move SL forward per ladder
"""
from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.shared.tokens import PATHS, MAGICS, ACCOUNT_RISK, TRADE_LOGS  # noqa: E402
from runtime.shared.orchestrator_gate import is_engine_active   # noqa: E402
from runtime.shared.circuit_breaker import CircuitBreaker       # noqa: E402
from runtime.shared.risk_sentinel import RiskSentinel           # noqa: E402
from runtime.shared.decision_log import (                        # noqa: E402
    record_decision, update_decision_ticket,
)
from runtime.shared.contracts import TradeSignal                 # noqa: E402
from runtime.shared.trade_executor import execute_signal         # noqa: E402
from runtime.shared.fvg_pending import plan_fvg_pendings          # noqa: E402

# ──────────────────────────────────────────────────────────
# Identity
# ──────────────────────────────────────────────────────────
MAGIC  = MAGICS["claude_genome"]   # 99782 — same as old claude_genome (continuity)
SYMBOL = "XAUUSDm"                  # PRIMARY — gold, the proven one
# Sub-second reactivity. Full 4-symbol structure read is ~25ms, a tick + a
# positions_get are ~0.03ms — so a 1s sleep meant the son was idle 97% of the
# time ("يغفي"). Now: a FAST tick protects open money every POLL_S, while the
# heavier entry scan (structure + ML) runs every ENTRY_EVERY (no over-firing).
POLL_S      = 0.15    # fast loop: trailing SL / loss-cut reacts within ~150ms
ENTRY_EVERY = 0.50    # entry scan cadence — structure/ML don't change faster

# ── Multi-symbol: our son now trades the rest of the currencies too ──────────
# User (2026-05-29): "هل نقدر نطلع زي ولدنا على باقي العملات؟" — نعم.
# Gold stays primary & most-trusted (allowed 2 concurrent). FX pairs are newer,
# so each is capped at 1 concurrent and there's a global cap on our own magic so
# margin can never blow up the way the magic-0 EA did.
# BTCUSDm added 2026-05-30: crypto is the ONLY market open on the weekend, so the
# son keeps trading while FX/metals are closed. It carries its OWN genome
# (live_genome__BTCUSDm.json: session_filter=[] → 24/7, smaller lot) so gold's
# session/value calibration never leaks onto a $73k instrument.
# ALL MARKET PAIRS (user 2026-05-30: "وعلى جميع أزواج السوق") — the full
# 12-symbol universe the brain already snapshots. Gold stays PRIMARY; BTC is
# the 24/7 weekend worker with its OWN ATR-anchored genome; every other pair
# uses its live_genome__<SYM>.json if present else the shared champion
# (auto via _load_genome_for). Risk stays fenced: per-symbol caps below +
# GLOBAL_MAX_OPEN + genome-pause/DD gates apply to market AND pending entries.
SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm",
           "USDCADm", "AUDUSDm", "NZDUSDm", "USDCHFm", "EURJPYm",
           "GBPJPYm", "XAGUSDm"]
# Per-symbol concurrent-position cap (anti-pyramid — THE guard magic-0 lacked).
# Gold proven → 2 concurrent. All FX/silver/crypto newer → 1 each.
MAX_OPEN_BY_SYM = {"XAUUSDm": 2, "EURUSDm": 1, "GBPUSDm": 1, "USDJPYm": 1,
                   "USDCADm": 1, "AUDUSDm": 1, "NZDUSDm": 1, "USDCHFm": 1,
                   "EURJPYm": 1, "XAGUSDm": 1, "BTCUSDm": 1, "GBPJPYm": 1}
MAX_OPEN_DEFAULT = 1
# ── CONFIDENT SCALP-STACK (user 2026-05-30: "زيد عدد الصفقات في نفس العملة اللي
# فيها فرصة واضحة وبثقة عالية") ─────────────────────────────────────────────
# Beyond the BASE cap above, the son MAY add more positions on the SAME symbol
# — but ONLY into STRENGTH: (a) confidence ≥ STACK_CONF, (b) the symbol's book
# is NET GREEN, (c) SAME direction as the existing winners. Never average down.
# This is the SAFE form of the pattern that crashed the account at +80% (that
# was a naked, no-SL, add-into-a-LOSER down-stack). Every add still carries a
# stop-loss, and CircuitBreaker + GLOBAL_MAX_OPEN + DD-guard still bound it.
STACK_MAX_BY_SYM = {"XAUUSDm": 5, "BTCUSDm": 3}
STACK_MAX_DEFAULT = 3
STACK_CONF = 0.72          # high-confidence bar each extra same-symbol add must clear
# Hard ceiling across ALL our son's open positions, every symbol combined.
# Raised 5→8 for scalp-stacking headroom; still bounds total margin/risk.
GLOBAL_MAX_OPEN = 8
# Back-compat alias (some code/UI may still reference MAX_OPEN for gold).
MAX_OPEN = MAX_OPEN_BY_SYM["XAUUSDm"]

# ── FVG-anchored PENDING orders ("اوامر معلقة على الفجوات") ──────────────────
# Our son now rests LIMIT/STOP orders ahead of price on unfilled FVGs — bouncing
# off them (reversal) or breaking through (continuation). These are planned by
# shared/fvg_pending.py and managed (deduped / expired / invalidated) here.
ENABLE_FVG_PENDING   = True
PENDING_EVERY        = 2.0     # plan/refresh pending orders every ~2s (gaps move slowly)
PENDING_MAX_AGE_S    = 1800    # auto-expire a resting order after 30min unfilled
PENDING_MAX_BY_SYM   = {"XAUUSDm": 3}   # default below
PENDING_MAX_DEFAULT  = 2
GLOBAL_MAX_PENDING   = 8       # ceiling across ALL symbols (resting orders only)
# Dedupe: don't stack a new pending within this many gold-points of an existing
# same-side resting order (scaled per symbol by _PT).
PENDING_DEDUPE_PT    = 1.5
# ── Re-arm guard ─────────────────────────────────────────────────────────────
# FIX (user report on magic 99782): after a resting FVG pending FILLED and took
# profit, the stateless planner re-armed the IDENTICAL level on the next 2s-scan;
# and a pending the user manually DELETED was re-added immediately. Root cause:
# dedupe only checked CURRENTLY-RESTING orders, so a vanished level (filled OR
# cancelled) looked "free to arm again". The trader now REMEMBERS each level it
# armed: when its order vanishes the level goes on a cooldown before it may be
# armed again (longer if cancelled, so a manual delete is respected), and a level
# that keeps filling is parked for hours so it stops churning + reversing on us.
FVG_RELEVEL_COOLDOWN_S = 900     # after a level FILLS, wait 15min before re-arming the same level
FVG_CANCEL_COOLDOWN_S  = 1800    # vanished WITHOUT a fill (manual delete / our invalidation) → respect 30min
FVG_MAX_FILLS          = 2       # after this many fills, park the level for 6h (stop the churn)
_fvg_levels: dict = {}           # level-key -> {"ticket","fills","until","note","user_denied"}
_self_cancelled_tickets: set = set()   # tickets WE removed (expiry/SL-breach) — so a vanished
                                       # order can be told apart from a USER's manual delete
_last_pending_scan   = 0.0

# Pullback entries: in a CONFIRMED trend, allow buying the dip / selling the
# rally even when short-term pressure is mildly contra — that's a pullback, not
# a reversal. Block only when the counter-flow is deeper than this (a real
# reversal). The ML gate makes the final call. Lets him trade far more often.
PULLBACK_MAX_CONTRA = 15.0

# Files we read (single source of truth)
BRAIN_LIVE  = PATHS["brain_live"]
REGIME_FILE = PATHS["market_regime"]
LIVE_GENOME = PATHS["live_genome"]


def _genome_path_for(sym: str):
    """Per-symbol genome file, e.g. live_genome__EURUSDm.json.
    'كل عمله ولها قيمها الخاصة وجيناتها الخاصة' — each symbol may carry its own
    genes/values; if no per-symbol file exists it falls back to the shared one."""
    return LIVE_GENOME.parent / f"live_genome__{sym}.json"


def _load_genome_for(sym: str, shared: dict) -> tuple[dict, str]:
    """Return (params, name) for this symbol: its own genome if present, else
    the shared champion. Gold keeps using the shared champion unless given one."""
    per = _read_json(_genome_path_for(sym))
    if per and per.get("params"):
        return per.get("params", {}), per.get("name", f"{sym}-genome")
    return shared.get("params", {}), shared.get("name", "UNKNOWN")

# Trailing ladder — SECURE PROFIT, NEVER sit at entry-or-worse (user's rule:
# "أمّن أكبر ربح، ولا يتوقف عند الدخول وأقل منه"). Every rung locks POSITIVE
# profit; wider trail higher up so a winner can RIDE for the biggest move.
TRAIL_LADDER = [
    (15.0, 2.0),   # +15pt → trail 2pt  (lock ≥13pt) — ride the big move
    (10.0, 3.0),   # +10pt → trail 3pt  (lock ≥7pt)
    ( 6.0, 3.0),   # +6pt  → trail 3pt  (lock ≥3pt)
    ( 3.0, 1.5),   # +3pt  → trail 1.5pt (lock ≥1.5pt)
    ( 1.5, 0.8),   # +1.5pt→ trail 0.8pt (lock ≥0.7pt — SL ABOVE entry fast, never BE)
]

# Confidence threshold (genome's signal strength must clear this to fire).
# Escalated 0.50->0.62->0.72 (2026-06-02): the live genome kept losing (18% WR,
# -$41/3h) even after the first raise + regime/HTF gates. The real edge is FEWER,
# higher-quality trades — demand strong conviction. If it STILL loses next cycle,
# the escalation is: revert genome to backup OR pause new genome risk until a
# walk-forward-validated genome exists (in-sample fitness has never held live).
MIN_CONFIDENCE = 0.72
# ── ML clone gate — SELF-TUNING ──────────────────────────────────────────
# User mandate (2026-05-28): "خفّض العتبة، وخلّه هو يرفعها إذا بدأ يخسر."
# Lower BASE so our son actually trades; then he RAISES the bar on himself
# when he starts losing (consecutive losers / red day) or when the market is
# choppy. He relaxes back toward BASE after wins / when a clean trend returns.
ML_BASE_PWIN = 0.42        # floor — trades freely above this in clean trends
ML_MAX_PWIN  = 0.66        # ceiling — gets this strict only when bleeding/chop
_thr_cache = {"t": 0.0, "v": ML_BASE_PWIN, "why": f"base {ML_BASE_PWIN}"}

# ══════════════════════════════════════════════════════════════════════════
# AGGRESSIVE SCALPING MODE  (طلب المستخدم 2026-06-04: "سكالبينج سريع لحظي عدواني،
# والوكلاء يدعمونه لحظة بلحظة"). One master switch:
#   • scans entries ~5x/sec and reacts on open positions every 100ms
#   • fires on much thinner conviction (conf 0.72→0.25, ML 0.42→0.30)
#   • holds more concurrent scalps (global 5→10)
#   • locks tiny scalp profits FAST (tight trail ladder)
#   • flips the agent QUALITY gates (trend/regime/structure/ML/brain) from hard
#     VETOES into "support": they still log their view + nudge conviction, but
#     they DON'T block — so the agents back the scalper moment-by-moment.
#
# ⚠️ HONEST WARNING (your own data): gold scalping is currently NET-LOSING
# (-$34, Sharpe -1.22); the measured edge is DISCIPLINE, not speed. This mode
# trades far more and can lose FASTER. Catastrophe-brakes that STILL apply:
# demo-only executor guard, kill_switch.txt, a stop-loss on every order, the
# position caps, the per-symbol CircuitBreaker and the account RiskSentinel.
# Fully reversible — set AGGRO = False to restore the disciplined engine.
# ══════════════════════════════════════════════════════════════════════════
AGGRO                  = False  # USER DECISION 2026-05-30 ("1 + 3"): OFF restores
                                # the DISCIPLINED engine (conf 0.72, max 5, agent
                                # gates = hard vetoes → fewer/higher-quality trades)
                                # AND the WIDE profit-riding ladder (let winners
                                # run to a big target instead of banking $0.50).
                                # This is exactly proven-style sizing + discipline
                                # (dir 1) + bigger targets (dir 3). Reversible: True.
AGGRO_KEEP_NIGHT_BLOCK = True   # keep the ONE proven edge (no 22:00-08:00); set False for true "no limits"
AGGRO_AGENTS_SUPPORT   = True   # agent quality-gates inform + nudge conviction instead of vetoing

if AGGRO:
    POLL_S          = 0.10                       # fast loop: trailing/exit reacts ~100ms
    ENTRY_EVERY     = 0.20                        # entry scan ~5x/sec
    MIN_CONFIDENCE  = 0.25                        # fire on thin conviction
    ML_BASE_PWIN    = 0.30                        # ML floor relaxed
    ML_MAX_PWIN     = 0.55                        # ML ceiling relaxed
    GLOBAL_MAX_OPEN = 10                          # more concurrent scalps (was 5)
    MAX_OPEN_BY_SYM = {s: (3 if s == "XAUUSDm" else 2) for s in SYMBOLS}
    MAX_OPEN        = MAX_OPEN_BY_SYM["XAUUSDm"]
    TRAIL_LADDER = [                              # scalp exits — lock tiny profit FAST (gold-points)
        (4.0, 1.0),   # +4pt   → trail 1pt
        (2.5, 0.8),   # +2.5pt → trail 0.8pt
        (1.5, 0.5),   # +1.5pt → trail 0.5pt
        (0.8, 0.3),   # +0.8pt → trail 0.3pt (lock almost immediately)
    ]
    _thr_cache = {"t": 0.0, "v": ML_BASE_PWIN, "why": f"base {ML_BASE_PWIN}"}

# Module state
_breakers: dict = {}                 # per-symbol CircuitBreaker
_sentinels: dict = {}                # per-symbol RiskSentinel (account-level guards)

# ── ANTI-WEDGE (2026-07-14 root-cause fix) ──────────────────────────────────
# WHY: CircuitBreaker.check() fires up to 3 mt5.history_deals_get calls and
# RiskSentinel.check() 2 more — per SYMBOL, per ENTRY SCAN. At 12 symbols ×
# 2 Hz that was ~120 history IPC queries/sec: the exact flood that wedges the
# terminal IPC (see project_mt5_ipc_flood lesson 2026-06-28). After a machine
# hang / terminal restart each of those calls can block for minutes — or, on a
# half-open IPC pipe, FOREVER (the MetaTrader5 API has no per-call timeout),
# turning this single-threaded loop into an hours-stale zombie.
# FIX 1: cache the two gate verdicts per symbol for GATE_CHECK_EVERY seconds.
#        Verdicts change on minute-scale (freezes/cooldowns/daily-loss), so a
#        10s cache is behaviorally identical on a healthy terminal while
#        cutting the history-IPC load ~20×. The cache is INVALIDATED on every
#        successful fire so cooldown / rate-limit engage immediately.
# FIX 2: a stall watchdog (see _stall_watchdog) self-exits the process if the
#        loop makes NO progress for STALL_EXIT_S — a fresh respawned process
#        re-establishes MT5 IPC in ~0.2s instead of zombie-ing for hours.
GATE_CHECK_EVERY = 10.0
_gate_cache: dict = {}               # sym -> {"t": mono, "cb": verdict, "rs": verdict}

STALL_EXIT_S = 300.0                 # no loop progress this long → exit for respawn
_hb = {"t": time.monotonic()}        # loop heartbeat (touched on every progress step)


def _touch_hb() -> None:
    _hb["t"] = time.monotonic()


def _stall_watchdog() -> None:
    """Daemon thread: the ONLY cure for an mt5 IPC call that never returns
    (no timeout exists in the API). If the main loop shows no progress for
    STALL_EXIT_S, exit hard — the external watchdog/launcher respawns us and a
    fresh process reconnects instantly. Never fires on slow-but-progressing
    cycles because the heartbeat is touched after every symbol."""
    import os
    while True:
        time.sleep(30)
        idle = time.monotonic() - _hb["t"]
        if idle > STALL_EXIT_S:
            try:
                print(f"[{datetime.now():%H:%M:%S}] 💀 STALL: no loop progress for "
                      f"{idle:.0f}s (wedged mt5 IPC call?) — exiting for fresh respawn",
                      flush=True)
            except Exception:
                pass
            os._exit(3)


def _cached_gate_checks(sym: str, brk, sentinel) -> tuple:
    """(cb_verdict, rs_verdict) refreshed at most every GATE_CHECK_EVERY s."""
    now = time.monotonic()
    ent = _gate_cache.get(sym)
    if ent is not None and now - ent["t"] < GATE_CHECK_EVERY:
        return ent["cb"], ent["rs"]
    cb = brk.check()
    rs = sentinel.check()
    _gate_cache[sym] = {"t": now, "cb": cb, "rs": rs}
    return cb, rs

_last_genome_name: str | None = None
_last_sym_genome: dict = {}          # per-symbol genome name (for change-logging)
_last_status_print: float = 0.0
_son_multi: dict = {}                # latest per-symbol verdict (for UI summary)


def _adaptive_pwin_threshold(regime: str) -> tuple[float, str]:
    """Self-tuning ML gate. Returns (threshold, human-readable why).

    threshold = BASE
              + regime penalty   (chop/dead/range → pickier)
              + loss penalty      (each trailing consecutive loser → +0.03)
              + red-day penalty   (today's realized P/L < -$3 → +0.05)
    clamped to [BASE, MAX]. Cached 20s so we don't hammer history_deals_get."""
    global _thr_cache
    now = time.time()
    if now - _thr_cache["t"] < 20:
        return _thr_cache["v"], _thr_cache["why"]
    thr = ML_BASE_PWIN
    why = [f"base {ML_BASE_PWIN:.2f}"]
    r = (regime or "?").upper()
    if r in ("CHOP", "DEAD"):
        thr += 0.10; why.append("+.10 chop")
    elif r == "RANGE":
        thr += 0.06; why.append("+.06 range")
    elif r == "TRANSITION":
        thr += 0.04; why.append("+.04 transit")
    try:
        import datetime as _dt
        now_dt = _dt.datetime.now()
        deals = mt5.history_deals_get(now_dt - _dt.timedelta(hours=12), now_dt) or []
        ours = sorted([d for d in deals if d.magic == MAGIC and d.entry == 1],
                      key=lambda d: d.time, reverse=True)
        consec = 0
        for d in ours:
            if d.profit < 0: consec += 1
            else: break
        if consec:
            bump = min(consec, 6) * 0.03
            thr += bump; why.append(f"+{bump:.2f} {consec}L")
        day_pnl = sum(d.profit for d in ours
                      if _dt.datetime.fromtimestamp(d.time).date() == now_dt.date())
        if day_pnl < -3.0:
            thr += 0.05; why.append("+.05 day<-$3")
    except Exception:
        pass
    thr = round(max(ML_BASE_PWIN, min(ML_MAX_PWIN, thr)), 3)
    _thr_cache = {"t": now, "v": thr, "why": " ".join(why)}
    return thr, _thr_cache["why"]


def _open_count(sym: str = SYMBOL) -> int:
    """How many positions we already hold on sym+MAGIC (anti-pyramid)."""
    try:
        pos = mt5.positions_get(symbol=sym) or []
        return sum(1 for p in pos if p.magic == MAGIC)
    except Exception:
        return 0


def _symbol_book(sym: str) -> tuple[int, float, str | None]:
    """(count, net_profit, dominant_side) for OUR open positions on sym.

    Used by the confident scalp-stack gate: only add into a GREEN book on the
    SAME side. dominant_side is 'BUY'/'SELL' by majority (None if flat)."""
    try:
        ps = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    except Exception:
        return (0, 0.0, None)
    if not ps:
        return (0, 0.0, None)
    net = sum(p.profit for p in ps)
    buys = sum(1 for p in ps if p.type == 0)
    side = "BUY" if buys * 2 >= len(ps) else "SELL"
    return (len(ps), net, side)


def _global_open_count() -> int:
    """Total open positions on OUR magic across ALL symbols (margin ceiling)."""
    try:
        pos = mt5.positions_get() or []
        return sum(1 for p in pos if p.magic == MAGIC)
    except Exception:
        return 0


_PENDING_TYPES = None   # lazily resolved set of MT5 pending order-type ints


def _pending_type_set():
    global _PENDING_TYPES
    if _PENDING_TYPES is None:
        _PENDING_TYPES = {
            mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
            mt5.ORDER_TYPE_BUY_STOP,  mt5.ORDER_TYPE_SELL_STOP,
        }
    return _PENDING_TYPES


def _pending_orders(sym: str | None = None) -> list:
    """Resting pending orders on OUR magic (optionally for one symbol)."""
    try:
        orders = (mt5.orders_get(symbol=sym) if sym else mt5.orders_get()) or []
        pt_types = _pending_type_set()
        return [o for o in orders if o.magic == MAGIC and o.type in pt_types]
    except Exception:
        return []


def _pending_count(sym: str) -> int:
    return len(_pending_orders(sym))


def _global_pending_count() -> int:
    return len(_pending_orders())


def _pt(sym: str) -> float:
    """Price-units per '1 pt' for sym, so gold-tuned thresholds scale to FX."""
    return _PT.get(sym, 1.0)


def _atr_px(sym: str, n: int = 14) -> float:
    """ATR(n) on M15 in PRICE UNITS. Pro-panel Step-1: the live SL was a flat
    `sl_pts` (~4 gold-pts ≈ 0.7·ATR — a noise stop one bar sweeps). We floor the
    stop to a real volatility multiple so it isn't grazed by ordinary noise."""
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, n + 2)
        if r is None or len(r) < n + 1:
            return 0.0
        import numpy as np
        h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float); pc = np.roll(c, 1); pc[0] = c[0]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        return float(np.mean(tr[-n:]))
    except Exception:
        return 0.0


def _brain_path_for(sym: str) -> Path:
    """Per-symbol brain snapshot the trader reads (gold also has its own file)."""
    return BRAIN_LIVE.parent / f"brain_live__{sym}.json"


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
def _read_json(p: Path) -> dict | None:
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


# Account-wide drawdown lockout written by the drawdown_recovery agent. The
# r_executor (magic 20260605) already honors this ("Cycle 25 SAFETY"); the v2
# unified_trader (magic 99782) must honor the SAME flag so a DD lockout applies
# to BOTH executors and one engine can't keep opening trades / resting FVG
# pendings while the other is locked out. Fail-OPEN: a missing or unreadable
# file never blocks trading (it only ever ADDS a guard, never removes one).
_DD_RECOVERY_FILE = Path(r"C:\Users\Radhi\MT5\data\r_native\dd_recovery_state.json")

def _dd_blocks_new_entries() -> str:
    """Return a non-empty reason string if new entries are DD-blocked, else ''."""
    try:
        st = _read_json(_DD_RECOVERY_FILE)
        if st and st.get("blocks_new_entries"):
            return (f"DD-BLOCK {st.get('drawdown_pct', 0):.1f}% "
                    f"(sev {st.get('severity_level', '?')}, "
                    f"{st.get('action', '?')})")
    except Exception:
        pass   # fail-open — never let this guard itself crash the loop
    return ""


_GENOME_PAUSE_FILE = PATHS["brain_decisions"].parent / "genome_paused.json"


def _genome_paused() -> str:
    """Return a reason string if the genome's NEW entries are paused, else ''.
    Set by the develop-loop escalation when the live genome keeps losing and no
    walk-forward-validated genome exists yet. Pauses NEW risk only — open
    positions are still managed/trailed, and evolution keeps searching."""
    try:
        st = _read_json(_GENOME_PAUSE_FILE)
        if st and st.get("paused"):
            return st.get("reason", "genome paused (no validated edge)")
    except Exception:
        pass
    return ""


# ── Reflection-engine discipline gate (reflection/strategy.json) ─────────────
# The reflection loop (C:\Users\Radhi\MT5\reflection\) maintains discipline
# tunables and edits ONE per cycle. The strongest is the night-trade block —
# excluding 22:00-08:00 UTC flipped the user's real manual record from -$18 to
# +$904 (PF 3.36). We honor it here as a NEW-ENTRY veto: open positions keep
# trailing, only fresh risk pauses in the window. Fail-OPEN exactly like the
# DD/genome guards — if the reflection module/file is missing or unreadable it
# NEVER blocks; it can only ever ADD a restriction, never remove one or trade.
_REFLECTION_DIR = Path(r"C:\Users\Radhi\MT5\reflection")

def _reflection_entry_block(sym: str) -> str:
    """Non-empty reason if reflection/strategy.json vetoes a NEW entry on `sym`
    right now (night-trade block etc.), else ''. Fail-open on any error."""
    try:
        if str(_REFLECTION_DIR) not in sys.path:
            sys.path.insert(0, str(_REFLECTION_DIR))
        from strategy_gate import entry_block_reason
        return entry_block_reason(sym)
    except Exception:
        return ""  # fail-open — the reflection subsystem can never freeze trading


# Deep trail rungs kept fixed; the tightest (scalp) rung is the LEARNED one.
_SCALP_LADDER_DEEP = [(4.0, 1.0), (2.5, 0.8), (1.5, 0.5)]
_last_scalp_load = 0.0

def _refresh_scalp_tunables(force: bool = False) -> None:
    """Re-read the LEARNED scalp values from reflection/strategy.json so the
    reflection engine's hill-climbed, profit-improving values take effect LIVE
    (no restart). Cached ~5s. Fail-open — never breaks the loop."""
    global MIN_CONFIDENCE, ML_BASE_PWIN, GLOBAL_MAX_OPEN, TRAIL_LADDER, _last_scalp_load
    now = time.time()
    if not force and now - _last_scalp_load < 5.0:
        return
    _last_scalp_load = now
    try:
        if str(_REFLECTION_DIR) not in sys.path:
            sys.path.insert(0, str(_REFLECTION_DIR))
        from strategy_gate import load_strategy
        st = load_strategy()
        if not st:
            return
        mc = st.get("scalp_min_confidence")
        if isinstance(mc, (int, float)): MIN_CONFIDENCE = float(mc)
        ml = st.get("scalp_ml_base_pwin")
        if isinstance(ml, (int, float)): ML_BASE_PWIN = float(ml)
        gm = st.get("scalp_global_max_open")
        if isinstance(gm, (int, float)): GLOBAL_MAX_OPEN = int(gm)
        trig = st.get("scalp_trail_trigger_pt")
        dist = st.get("scalp_trail_distance_pt")
        if isinstance(trig, (int, float)) and isinstance(dist, (int, float)):
            rebuilt = [r for r in _SCALP_LADDER_DEEP if r[0] > float(trig)]
            rebuilt.append((float(trig), float(dist)))
            TRAIL_LADDER = sorted(rebuilt, key=lambda r: r[0], reverse=True)
    except Exception:
        pass  # fail-open


def _write_son_status(stage: str, detail: str, genome: str, snap: dict,
                      side: str = "", p_win: float = 0.0,
                      ml_min: float = ML_BASE_PWIN, sym: str = SYMBOL) -> None:
    """Persist the live verdict so the UI / OUR SON tab can show what it's thinking.

    Gold (PRIMARY) writes son_status.json exactly as before (UI back-compat).
    Every symbol also writes son_status__<SYM>.json, and a combined
    son_status_multi.json summarises all symbols for the multi-symbol UI grid."""
    try:
        acc = mt5.account_info()
        st = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": sym,
            "stage": stage, "detail": detail, "genome": genome,
            "side": side, "p_win": round(p_win, 3),
            "ml_min": round(ml_min, 3),
            "balance": acc.balance if acc else None,
            "equity": acc.equity if acc else None,
            "regime": snap.get("regime"),
            "session": snap.get("session"),
            "rsi_m1": (snap.get("rsi") or {}).get("m1"),
            "pressure": snap.get("pressure_10m1"),
        }
        payload = json.dumps(st, ensure_ascii=False, default=str)
        base = PATHS["brain_decisions"].parent
        # per-symbol file (always)
        (base / f"son_status__{sym}.json").write_text(payload, encoding="utf-8")
        # gold = the canonical son_status.json the existing UI tab reads
        if sym == SYMBOL:
            (base / "son_status.json").write_text(payload, encoding="utf-8")
            try:
                from runtime.shared.tokens import COMMON_FILES
                (COMMON_FILES / "son_status.json").write_text(payload, encoding="utf-8")
            except Exception:
                pass
        # combined multi-symbol summary
        _son_multi[sym] = st
        try:
            (base / "son_status_multi.json").write_text(
                json.dumps({"ts": st["ts"], "symbols": _son_multi},
                           ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            pass
    except Exception:
        pass


def _status(msg: str, force: bool = False) -> None:
    """Print one-line status, throttled to every 30s unless force=True."""
    global _last_status_print
    now = time.time()
    if not force and now - _last_status_print < 30: return
    print(f"[{datetime.now():%H:%M:%S}] {msg}")
    _last_status_print = now


# ──────────────────────────────────────────────────────────
# Genome evaluation (CHILD-style — looser, distilled from wins)
# ──────────────────────────────────────────────────────────
def evaluate_genome(snap: dict, genome_params: dict, pt: float = 1.0) -> tuple[str | None, float, str]:
    """Return (side, confidence, reason) or (None, 0, why_no_signal).

    `pt` scales the gold-tuned pressure thresholds into the symbol's own price
    units (gold pt=1.0; EURUSD pt=0.0001) so the same genome works on any pair."""
    if not snap or not genome_params:
        return (None, 0, "no snap/genome")

    rsi_max          = genome_params.get("rsi_max", 60)
    # gold-points → symbol price units
    min_pressure_abs = genome_params.get("min_pressure_abs", 3) * pt
    min_mtf          = genome_params.get("min_mtf_agreement", 2)
    regime_filter    = genome_params.get("regime_filter") or []
    session_filter   = genome_params.get("session_filter") or []
    side_bias        = genome_params.get("side_bias")

    # Session filter (if specified)
    sess = snap.get("session", "?")
    if session_filter and sess not in session_filter:
        return (None, 0, f"session {sess} not in {session_filter}")

    # Regime filter (if specified)
    reg = snap.get("regime", "?")
    if regime_filter and reg not in regime_filter:
        return (None, 0, f"regime {reg} not in {regime_filter}")

    # Bias counting
    bias = snap.get("bias", {})
    up_count = sum(1 for v in bias.values() if v == "UP")
    dn_count = sum(1 for v in bias.values() if v == "DOWN")

    if up_count >= min_mtf:
        direction = "BUY"
    elif dn_count >= min_mtf:
        direction = "SELL"
    else:
        return (None, 0, f"MTF mixed ({up_count}↑/{dn_count}↓ need ≥{min_mtf})")

    if side_bias == "BUY_ONLY"  and direction != "BUY":  return (None, 0, "side_bias BUY_ONLY")
    if side_bias == "SELL_ONLY" and direction != "SELL": return (None, 0, "side_bias SELL_ONLY")

    # RSI filter (for the chosen side)
    rsi = (snap.get("rsi") or {}).get("m1", 50)
    if direction == "BUY" and rsi >= rsi_max:
        return (None, 0, f"BUY blocked: RSI {rsi:.1f} ≥ {rsi_max}")
    rsi_min = 100 - rsi_max
    if direction == "SELL" and rsi <= rsi_min:
        return (None, 0, f"SELL blocked: RSI {rsi:.1f} ≤ {rsi_min}")

    # Pressure: two ways in —
    #   • MOMENTUM (with-trend): pressure confirms the side → needs real flow.
    #   • PULLBACK (counter-trend dip): pressure mildly contra in a confirmed
    #     trend → buy the dip / sell the rally. ML gate decides if it's worth it.
    pressure   = float(snap.get("pressure_10m1", 0))
    pullback_max = PULLBACK_MAX_CONTRA * pt   # gold-points → symbol price units
    trend_n    = max(up_count, dn_count)
    strong_trend = trend_n >= 3
    confirms = (direction == "BUY" and pressure > 0) or (direction == "SELL" and pressure < 0)

    if confirms:
        if abs(pressure) < min_pressure_abs:
            return (None, 0, f"pressure |{pressure:.4g}| < {min_pressure_abs:.4g}")
        entry_mode = "momentum"
    else:
        # counter-pressure = pullback
        if not strong_trend:
            return (None, 0, f"contra {direction}, weak trend {trend_n}/4")
        if abs(pressure) > pullback_max:
            return (None, 0, f"pullback too deep |{pressure:.4g}|>{pullback_max:.4g}")
        entry_mode = "pullback"

    # Confidence
    mtf_score = trend_n / 4   # 0..1
    if entry_mode == "momentum":
        pres_score = min(abs(pressure) / 10, 1.0)
        confidence = round(mtf_score * 0.6 + pres_score * 0.4, 2)
    else:                      # pullback — lean on trend strength
        confidence = round(mtf_score * 0.7, 2)

    reason = (f"{direction} {entry_mode} MTF{trend_n}/4 "
              f"RSI{rsi:.0f} P{pressure:+.4g} regime{reg} sess{sess}")
    return (direction, confidence, reason)


# ──────────────────────────────────────────────────────────
# Pre-breakout readiness — "يجهّز نفسه للانطلاقة"
# ──────────────────────────────────────────────────────────
def detect_armed(snap: dict, genome_params: dict, pt: float = 1.0) -> tuple[bool, str]:
    """Detect a coil the trader should *prepare* for — NOT a trade.

    Two patterns the user asked to catch ("أي حركات قوية أو تجمعات ضعيفة
    يجهّز نفسه للانطلاقة"):

      • LOADING — direction already chosen by MTF, pressure CONFIRMS that side
        and is climbing toward the fire threshold (≥55% of it). A strong move
        is loading; the moment pressure crosses min_pressure_abs the normal
        momentum path fires. We surface it early so the system/UI is primed.

      • SQUEEZE — tight accumulation: very low pressure in a RANGE/TRANSITION/
        CHOP regime with MTF just starting to lean. Energy is building inside a
        coil; we flag it as "waiting for the break" so a breakout isn't missed.

    Pure visibility/telemetry. Returns (armed, detail). The real FIRE path and
    every risk gate downstream are completely unchanged — this never sends an
    order, it only re-labels a NO_SIGNAL tick as ARMED so the readiness shows.
    """
    try:
        min_pressure_abs = genome_params.get("min_pressure_abs", 3) * pt
        min_mtf = genome_params.get("min_mtf_agreement", 2)
        if min_pressure_abs <= 0:
            return (False, "")
        bias = snap.get("bias", {}) or {}
        up = sum(1 for v in bias.values() if v == "UP")
        dn = sum(1 for v in bias.values() if v == "DOWN")
        pressure = float(snap.get("pressure_10m1", 0) or 0)
        ap = abs(pressure)
        reg = snap.get("regime", "?")

        # LOADING — side decided + pressure confirming + nearing threshold
        if up >= min_mtf or dn >= min_mtf:
            direction = "BUY" if up >= min_mtf else "SELL"
            confirms = (direction == "BUY" and pressure > 0) or \
                       (direction == "SELL" and pressure < 0)
            if confirms and 0.55 * min_pressure_abs <= ap < min_pressure_abs:
                pct = ap / min_pressure_abs * 100.0
                return (True, f"🔫 LOADING {direction} — ضغط {ap:.3g}/"
                              f"{min_pressure_abs:.3g} ({pct:.0f}%) يجهّز للانطلاق")

        # SQUEEZE — tight accumulation building energy inside a coil
        if reg in ("TRANSITION", "RANGE", "CHOP") and ap < 0.45 * min_pressure_abs \
                and (up >= 1 or dn >= 1):
            lean = "↑" if up > dn else ("↓" if dn > up else "—")
            return (True, f"🧨 SQUEEZE — تجمّع/انضغاط (ميل {lean} {max(up, dn)}/4، "
                          f"ضغط {ap:.3g}) ينتظر الكسر")

        return (False, "")
    except Exception:
        return (False, "")


# ──────────────────────────────────────────────────────────
# Trailing SL (in-process, only on OUR positions)
# ──────────────────────────────────────────────────────────
# Per-symbol "1 pt" in price units, so the XAU-tuned ladder scales to any symbol.
_PT = {"XAUUSDm": 1.0, "XAGUSDm": 0.10, "BTCUSDm": 100.0, "EURUSDm": 0.0001,
       "GBPUSDm": 0.0001, "USDJPYm": 0.01, "GBPJPYm": 0.01,
       "USDCADm": 0.0001, "AUDUSDm": 0.0001, "NZDUSDm": 0.0001,
       "USDCHFm": 0.0001, "EURJPYm": 0.01}


def _ideal_sl(pos, tick) -> tuple[float, str] | None:
    pt = _PT.get(pos.symbol, 1.0)
    digits = 5 if pt <= 0.0001 else (3 if pt <= 0.01 else 2)
    # profit in symbol-native "pts"
    p_pts = ((tick.bid - pos.price_open) if pos.type == 0
             else (pos.price_open - tick.ask)) / pt
    for trigger, dist in TRAIL_LADDER:
        if p_pts >= trigger:
            if dist == 0:
                return (round(pos.price_open, digits), f"BE@{trigger:.0f}")
            if pos.type == 0:   # BUY
                return (round(tick.bid - dist * pt, digits), f"trail{dist:.0f}@{trigger:.0f}")
            return (round(tick.ask + dist * pt, digits), f"trail{dist:.0f}@{trigger:.0f}")
    return None


def _better_sl(pos, new_sl: float) -> bool:
    eps = _PT.get(pos.symbol, 1.0) * 0.5      # half a pt — symbol-aware
    if pos.sl == 0: return True
    if pos.type == 0: return new_sl > pos.sl + eps
    return new_sl < pos.sl - eps


PROTECT_RISK_PCT = 0.12     # NAKED positions: cap the loss-from-now at this % of equity (account safety)


def _protective_sl(pos, tick):
    """For a NAKED position (no SL) — e.g. a manual trade opened without a stop — place a protective
    stop that bounds the loss-FROM-NOW to PROTECT_RISK_PCT of equity, in the safe direction
    (BUY: below bid, SELL: above ask). Protects the account from an unstopped runner."""
    try:
        info = mt5.symbol_info(pos.symbol); acct = mt5.account_info()
        if not info or not acct or not info.trade_tick_size: return None
        tv = info.trade_tick_value / info.trade_tick_size
        if tv <= 0 or pos.volume <= 0 or acct.equity <= 0: return None
        dist = (PROTECT_RISK_PCT * acct.equity) / (tv * pos.volume)
        return round((tick.bid - dist) if pos.type == 0 else (tick.ask + dist), info.digits)
    except Exception:
        return None


def manage_open_positions() -> None:
    """Trail SL on EVERY open position — our son watches them all, any symbol,
    any magic (own trades + legacy + manual). 'خله يناظر الصفقات ويتصرف براحته'."""
    positions = mt5.positions_get() or []          # ALL positions, every symbol/magic
    for p in positions:
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick: continue
        ideal = _ideal_sl(p, tick)
        if ideal is not None:                       # winner → trail to lock profit
            new_sl, rung = ideal
            if not _better_sl(p, new_sl): continue
        elif p.sl == 0:                             # NAKED position → set a capped protective stop
            new_sl = _protective_sl(p, tick)
            if new_sl is None: continue
            rung = "protect"
        else:
            continue
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": int(p.ticket),
            "symbol":   p.symbol,
            "sl":       float(new_sl),
            "tp":       float(p.tp),
            "magic":    int(p.magic),
        }
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            side = "BUY " if p.type == 0 else "SELL"
            print(f"[{datetime.now():%H:%M:%S}] 🪜 #{p.ticket} {side} {rung}  "
                   f"SL {p.sl:.2f} → {new_sl:.2f}  (P/L ${p.profit:+.2f})")


# ──────────────────────────────────────────────────────────
# Risk-based position sizing
# ──────────────────────────────────────────────────────────
def _risk_lot(sym: str, sl_px: float, risk_pct: float, fallback: float) -> float:
    """Lot sized so hitting the SL risks exactly risk_pct% of EQUITY.

    A flat lot means a 0.02 gold trade risks dollars while a 0.02 EURUSD trade
    risks pennies — incoherent across an account. This converts the SL distance
    (in price) into money-per-lot via the broker's tick value, then solves for
    the lot that loses `risk_pct%` of equity at the stop. Clamped to the
    symbol's volume_min/max/step. Falls back to `fallback` on any uncertainty.
    """
    try:
        info = mt5.symbol_info(sym)
        acc  = mt5.account_info()
        if not info or not acc or sl_px <= 0:
            return fallback
        tick_val = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        tick_sz  = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        if tick_val <= 0 or tick_sz <= 0:
            return fallback
        loss_per_lot = (sl_px / tick_sz) * tick_val      # $ lost per 1.0 lot at SL
        if loss_per_lot <= 0:
            return fallback
        risk_amt = float(acc.equity) * risk_pct / 100.0
        lot = risk_amt / loss_per_lot
        vmin = float(getattr(info, "volume_min", 0.01) or 0.01)
        vmax = float(getattr(info, "volume_max", 100.0) or 100.0)
        vstep = float(getattr(info, "volume_step", 0.01) or 0.01)
        lot = max(vmin, min(vmax, lot))
        lot = round(round(lot / vstep) * vstep, 2)        # snap to broker step
        return max(vmin, lot)
    except Exception:
        return fallback


# ──────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────
def fire_entry(side: str, confidence: float, reason: str,
                snap: dict, genome_params: dict, genome_name: str,
                sym: str = SYMBOL) -> bool:
    tick = mt5.symbol_info_tick(sym)
    if not tick: return False

    pt = _pt(sym)
    info = mt5.symbol_info(sym)
    digits = info.digits if info else (5 if pt <= 0.0001 else (3 if pt <= 0.01 else 2))
    # genome SL/TP are in gold-points → scale to this symbol's price units
    sl_pts = float(genome_params.get("sl_pts", 4.0))
    tp_pts = float(genome_params.get("tp_pts", 12.0))
    # Legacy SMC genomes rely on the trailing ladder, so we inflate their TP.
    # But imported Algory champions (honor_tp=true) carry a precise, OOS-validated
    # tight TP that IS their edge — honor it exactly, don't inflate. (2026-05-31)
    if not genome_params.get("honor_tp"):
        tp_pts = max(tp_pts, 20.0)      # inflate TP — trail handles the real exit
    sl_px = sl_pts * pt
    tp_px = tp_pts * pt
    # ATR FLOOR (pro-panel Step-1): never let the stop be tighter than 1.2·ATR,
    # and keep the TP at least 2·ATR so R:R geometry holds across vol regimes.
    # Honor-TP (Algory champions) keep their exact validated TP — only floor SL.
    atr = _atr_px(sym)
    if atr > 0:
        sl_px = max(sl_px, 1.2 * atr)
        if not genome_params.get("honor_tp"):
            tp_px = max(tp_px, 2.0 * atr)
    lot = float(genome_params.get("lot", 0.02))
    # Risk-based sizing (opt-in): genome sets risk_pct>0 → size the lot so an SL
    # hit costs exactly that % of equity. Keeps risk-per-trade consistent across
    # gold vs FX vs silver. risk_pct=0 (default) keeps the flat genome lot.
    risk_pct = float(genome_params.get("risk_pct", 0.0))
    if risk_pct > 0:
        lot = _risk_lot(sym, sl_px, risk_pct, fallback=lot)

    if side == "BUY":
        price = tick.ask; sl = round(price - sl_px, digits); tp = round(price + tp_px, digits)
        otype = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid; sl = round(price + sl_px, digits); tp = round(price - tp_px, digits)
        otype = mt5.ORDER_TYPE_SELL

    # 1. Record decision in unified log
    dec_id = record_decision(
        source="unified_trader", magic=MAGIC, symbol=sym, side=side,
        entry=price, sl=sl, tp=tp, lot=lot,
        reason=f"{genome_name}: {reason}", confidence=confidence, snap=snap,
    )

    # 2. Send order
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
        "volume": lot, "type": otype,
        "price": price, "sl": sl, "tp": tp,
        "deviation": 50, "magic": MAGIC,
        "comment": f"UNI_{genome_name[:10]}_{side}"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE

    # 3. Link ticket back to decision
    update_decision_ticket(dec_id, int(r.order) if ok else 0,
                            error="" if ok else f"retcode {getattr(r, 'retcode', '?')}")

    # 4. Mark circuit breaker (per-symbol)
    if ok:
        _b = _breakers.get(sym)
        if _b: _b.mark_trade()
        print(f"[{datetime.now():%H:%M:%S}] 🎯 {sym} {side} #{r.order} @ {r.price:.{digits}f} "
               f"SL {sl:.{digits}f} TP {tp:.{digits}f} lot {lot} conf {confidence:.2f} | {reason}")
        # BUY alert — persistent flag + desktop toast (the child's first/every BUY)
        if side == "BUY":
            _emit_buy_alert(int(r.order), float(r.price), lot, confidence, reason, genome_name)
    else:
        print(f"[{datetime.now():%H:%M:%S}] ❌ {side} failed: {getattr(r, 'retcode', None)}")
    return bool(ok)


def _emit_buy_alert(ticket: int, price: float, lot: float,
                    confidence: float, reason: str, genome_name: str) -> None:
    """Persist a BUY alert + try a desktop notification."""
    alert = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticket": ticket, "price": price, "lot": lot,
        "confidence": confidence, "genome": genome_name, "reason": reason,
    }
    try:
        p = PATHS["brain_decisions"].parent / "buy_alerts.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    # Desktop toast (best-effort — never blocks trading)
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(
            "🟢 ولدك اشترى!", f"BUY #{ticket} @ {price:.2f} ({genome_name})",
            duration=10, threaded=True)
    except Exception:
        pass
    print(f"[{datetime.now():%H:%M:%S}] 🔔 BUY ALERT written → buy_alerts.jsonl")


# ──────────────────────────────────────────────────────────
# FVG-anchored PENDING orders — plan / place / manage
# ──────────────────────────────────────────────────────────
def _fvg_level_key(sym: str, side: str, entry: float, pt: float) -> str:
    """Quantise an entry into PENDING_DEDUPE_PT buckets so the same FVG maps to ONE
    stable key across scans (small price wiggle within a bucket = the same level)."""
    q = max(pt * PENDING_DEDUPE_PT, 1e-9)
    return f"{sym}|{side}|{int(round(entry / q))}"


def _fvg_level_blocked(key: str) -> str | None:
    """Reason this level must NOT be (re)armed right now, else None."""
    st = _fvg_levels.get(key)
    if not st:
        return None
    if st.get("ticket"):
        return "already resting"
    if st.get("user_denied"):
        return "user-cancelled (respected)"   # the human deleted it by hand — don't re-add it
    until = float(st.get("until", 0.0))
    if until > time.time():
        return f"{st.get('note', 'cooldown')} {int(until - time.time())}s"
    return None


def _reconcile_fvg_levels() -> None:
    """Watch the resting orders WE armed. When one vanishes, decide whether it
    FILLED (→ short cooldown + count it) or was CANCELLED — by us OR by the user's
    hand (→ longer cooldown so the deletion is respected and not re-added). Levels
    that keep filling get parked for 6h. Read-only on history; touches only our own
    tracked levels — never other magics, never positions."""
    now = time.time()
    try:
        resting = {int(o.ticket) for o in _pending_orders()}
    except Exception:
        return
    deals = None
    for key, st in list(_fvg_levels.items()):
        tk = st.get("ticket")
        if tk and tk not in resting:
            if deals is None:                       # query once per scan, only if needed
                try:
                    deals = {int(getattr(d, "order", 0)) for d in
                             (mt5.history_deals_get(int(now - 1800), int(now)) or [])
                             if d.entry == 0}
                except Exception:
                    deals = set()
            st["ticket"] = None
            if int(tk) in deals:                    # FILLED
                st["fills"] = int(st.get("fills", 0)) + 1
                if st["fills"] >= FVG_MAX_FILLS:
                    st["until"] = now + 6 * 3600; st["note"] = "churn-park 6h"
                else:
                    st["until"] = now + FVG_RELEVEL_COOLDOWN_S; st["note"] = "filled→cooldown"
            else:                                   # vanished WITHOUT a fill
                if int(tk) in _self_cancelled_tickets:    # WE removed it (expiry / SL-breach) → cooldown, may re-arm later
                    _self_cancelled_tickets.discard(int(tk))
                    st["until"] = now + FVG_CANCEL_COOLDOWN_S; st["note"] = "self-cancelled→cooldown"
                else:                                 # the USER deleted it by hand → respect it durably
                    st["user_denied"] = True; st["until"] = now + FVG_CANCEL_COOLDOWN_S
                    st["note"] = "user-cancelled→respected"
        # forget a level only after its cooldown AND only if the user didn't deny it by hand
        if not st.get("ticket") and not st.get("user_denied") and float(st.get("until", 0.0)) < now:
            _fvg_levels.pop(key, None)


def manage_pending_orders() -> None:
    """Cancel resting pending orders that are stale or invalidated.

    A pending order dies when:
      • it has rested longer than PENDING_MAX_AGE_S without filling, or
      • price has already blown through its STOP-LOSS before the entry could
        fill (the gap/level is gone — the setup is dead).
    Trailing/exits for FILLED positions are handled by manage_open_positions."""
    now_epoch = time.time()
    for o in _pending_orders():
        try:
            cancel_reason = None
            age = now_epoch - getattr(o, "time_setup", now_epoch)
            if age > PENDING_MAX_AGE_S:
                cancel_reason = f"expired {age/60:.0f}min"
            else:
                tick = mt5.symbol_info_tick(o.symbol)
                if tick and o.sl:
                    is_buy = o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
                    # SL breached before fill → setup invalidated
                    if is_buy and tick.bid <= o.sl:
                        cancel_reason = "SL breached pre-fill"
                    elif (not is_buy) and tick.ask >= o.sl:
                        cancel_reason = "SL breached pre-fill"
            if cancel_reason:
                r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE,
                                    "order": int(o.ticket)})
                if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                    _self_cancelled_tickets.add(int(o.ticket))   # mark as OUR cancel (not a user delete)
                    print(f"[{datetime.now():%H:%M:%S}] 🗑️ pending #{o.ticket} {o.symbol} "
                           f"cancelled — {cancel_reason}")
        except Exception as _e:
            print(f"[pending-manage] {getattr(o,'ticket','?')}: {_e}")


def place_fvg_pendings(sym: str, genome_params: dict, genome_name: str,
                       snap: dict, pt: float, g_held: int) -> None:
    """Rest LIMIT/STOP orders on the unfilled FVGs this symbol exposes.

    Reversal (يرد من عندها) and continuation (يكمل نزول/صعود) plans come from
    fvg_pending.plan_fvg_pendings; we dedupe against existing resting orders,
    respect the per-symbol + global pending caps, and send via execute_signal."""
    # SPLIT-BRAIN FIX (2026-05-30, analyst audit): the pause + drawdown gates
    # lived only in process_symbol (market entries), so resting FVG orders kept
    # arming and FILLING while the genome was officially PAUSED — 35 leaked
    # trades in 30d. A pending order is NEW risk; it honors the same gates.
    if _genome_paused() or _dd_blocks_new_entries():
        return
    plans = plan_fvg_pendings(snap, genome_params, pt, sym)
    if not plans:
        return

    # Capacity: resting + open should never threaten the margin ceiling.
    cap_sym  = PENDING_MAX_BY_SYM.get(sym, PENDING_MAX_DEFAULT)
    existing = _pending_orders(sym)
    room_sym = cap_sym - len(existing)
    if room_sym <= 0:
        return
    room_glob = GLOBAL_MAX_PENDING - _global_pending_count()
    if room_glob <= 0:
        return
    # Don't let pending + open + this plan exceed the open-position ceiling worth
    # of margin: leave at least the open ceiling free of resting orders.
    room = min(room_sym, room_glob)

    dedupe_px = PENDING_DEDUPE_PT * pt
    lot = float(genome_params.get("lot", 0.02))
    log_path = TRADE_LOGS.get("claude_genome")

    placed = 0
    for plan in plans:
        if placed >= room:
            break
        # Re-arm guard — skip a level we just filled / the user just cancelled.
        lkey = _fvg_level_key(sym, plan.side, plan.entry, pt)
        why = _fvg_level_blocked(lkey)
        if why:
            continue
        # Dedupe — skip if a same-side resting order already sits near this price.
        dup = any(
            ((o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)) == (plan.side == "BUY"))
            and abs(o.price_open - plan.entry) <= dedupe_px
            for o in existing
        )
        if dup:
            continue
        try:
            sig = TradeSignal(
                symbol=sym, side=plan.side, lot=lot,
                sl=plan.sl, tp=plan.tp, source="unified_trader",
                magic=MAGIC, reason=f"{genome_name}: {plan.reason}",
                confidence=0.55, order_type=plan.order_type,
                entry=plan.entry, expire_s=PENDING_MAX_AGE_S,
                metadata={"kind": plan.kind, "gap": [plan.gap_lo, plan.gap_hi]},
            )
            rec = execute_signal(sig, log_path=log_path,
                                 regime=snap.get("regime"), session=snap.get("session"),
                                 comment=f"FVG_{plan.kind[:4]}_{plan.side}")
            if rec.accepted:
                placed += 1
                _fvg_levels[lkey] = {"ticket": int(getattr(rec, "ticket", 0) or 0),
                                     "fills": int(_fvg_levels.get(lkey, {}).get("fills", 0)),
                                     "until": 0.0, "note": "armed"}
                existing.append(type("O", (), {
                    "type": (mt5.ORDER_TYPE_BUY_LIMIT if plan.side == "BUY"
                             else mt5.ORDER_TYPE_SELL_LIMIT),
                    "price_open": plan.entry})())
                print(f"[{datetime.now():%H:%M:%S}] 📌 {sym} {plan.side} {plan.order_type} "
                       f"@ {plan.entry} SL {plan.sl} TP {plan.tp} #{rec.ticket} | {plan.kind} | {plan.reason}")
            else:
                print(f"[{datetime.now():%H:%M:%S}] ⚠️ pending rejected {sym} {plan.side} "
                       f"{plan.order_type} @ {plan.entry}: {rec.error}")
        except Exception as _e:
            print(f"[fvg-pending] {sym} {plan.side}: {_e}")


# ──────────────────────────────────────────────────────────
# Per-symbol decision (gates → evaluate → ML gate → fire)
# ──────────────────────────────────────────────────────────
def process_symbol(sym: str, genome_params: dict, genome_name: str,
                   g_held: int) -> None:
    """Run the full decision pipeline for ONE symbol. Gold (XAUUSDm) behaves
    exactly as before (pt=1.0, regime from regime_classifier); FX pairs scale by
    their _PT and use their own ADX-derived regime from the brain snapshot."""
    snap = _read_json(_brain_path_for(sym))
    if not snap:
        return
    pt = _pt(sym)

    # Regime: gold uses the dedicated classifier; others carry their own.
    regime_name = snap.get("regime") or "?"
    if sym == SYMBOL:
        rj = _read_json(REGIME_FILE) or {}
        regime_name = rj.get("regime") or regime_name

    # Circuit breaker — per symbol (lazy-created)
    brk = _breakers.get(sym)
    if brk is None:
        brk = _breakers[sym] = CircuitBreaker(magic=MAGIC, symbol=sym)
    # RISK SENTINEL — account-level guards the son was missing: daily-loss cap,
    # equity floor, spread blow-out, cooldown, consec-SL auto-pause. One bad
    # streak can no longer drain the account the way the duplicate-process gold
    # disaster did.
    sentinel = _sentinels.get(sym)
    if sentinel is None:
        sentinel = _sentinels[sym] = RiskSentinel(magic=MAGIC, symbol=sym)
    # Both verdicts via the 10s anti-IPC-flood cache (see ANTI-WEDGE above).
    cb_block, rs_block = _cached_gate_checks(sym, brk, sentinel)
    if cb_block:
        _write_son_status("FROZEN", f"circuit breaker: {cb_block}",
                          genome_name, snap, sym=sym)
        return
    if rs_block:
        _write_son_status("RISK_BLOCK", f"risk: {rs_block}",
                          genome_name, snap, sym=sym)
        return

    # GENOME PAUSE — escalation when the live genome keeps losing and no
    # walk-forward-validated genome exists yet. Stops NEW risk; open positions
    # are still trailed; evolution keeps searching for a real edge.
    g_pause = _genome_paused()
    if g_pause:
        _write_son_status("PAUSED", f"genome paused: {g_pause}",
                          genome_name, snap, sym=sym)
        return

    # ACCOUNT-WIDE DRAWDOWN LOCKOUT — the same flag r_executor honors. When the
    # drawdown_recovery agent sets blocks_new_entries (severity 3+), NO new
    # entries may open on ANY symbol. Managing existing positions still runs
    # elsewhere; this only vetoes opening fresh risk. Fail-open on missing file.
    dd_block = _dd_blocks_new_entries()
    if dd_block:
        _write_son_status("RISK_BLOCK", f"risk: {dd_block}",
                          genome_name, snap, sym=sym)
        return

    # REFLECTION DISCIPLINE GATE — honor reflection/strategy.json (night-trade
    # block etc.). NEW-entry veto only; open positions keep trailing. Fail-open.
    refl_block = _reflection_entry_block(sym) if (not AGGRO or AGGRO_KEEP_NIGHT_BLOCK) else ""
    if refl_block:
        _write_son_status("RISK_BLOCK", f"discipline: {refl_block}",
                          genome_name, snap, sym=sym)
        return

    # Global margin ceiling — protects the account across ALL symbols.
    if g_held >= GLOBAL_MAX_OPEN:
        _write_son_status("MANAGING",
                          f"سقف عام {g_held}/{GLOBAL_MAX_OPEN} — يراقب فقط",
                          genome_name, snap, sym=sym)
        return

    # Per-symbol cap. BASE cap = disciplined first positions. Beyond it we MAY
    # stack up to STACK_MAX — but only into high-confidence GREEN strength (the
    # book/side/conf checks happen AFTER the signal is evaluated, below). The
    # absolute stack ceiling always applies; the hard anti-pyramid guard stays.
    cap       = MAX_OPEN_BY_SYM.get(sym, MAX_OPEN_DEFAULT)
    stack_cap = STACK_MAX_BY_SYM.get(sym, STACK_MAX_DEFAULT)
    held      = _open_count(sym)
    if held >= stack_cap:                       # absolute ceiling — never exceed
        _write_son_status("MANAGING",
                          f"{sym}: {held}/{stack_cap} سقف التكديس — يراقب فقط",
                          genome_name, snap, sym=sym)
        return
    stacking = held >= cap                       # beyond base → this add is a STACK

    # Evaluate genome (pressure/pullback thresholds scaled to this symbol)
    side, confidence, reason = evaluate_genome(snap, genome_params, pt)
    if side is None:
        # Not firing — but is it coiling toward a launch? Surface ARMED so the
        # system/UI is primed for the breakout (LOADING) or watching a SQUEEZE.
        armed, armed_detail = detect_armed(snap, genome_params, pt)
        if armed:
            _write_son_status("ARMED", armed_detail, genome_name, snap, sym=sym)
        else:
            _write_son_status("NO_SIGNAL", reason, genome_name, snap, sym=sym)
        return
    if confidence < MIN_CONFIDENCE:
        _write_son_status("LOW_CONF", f"conf {confidence} | {reason}",
                          genome_name, snap, sym=sym)
        return

    # ── CONFIDENT SCALP-STACK GATE — extra same-symbol adds only into STRENGTH.
    # First position (held < base cap) passes freely on MIN_CONFIDENCE. Each
    # ADD beyond the base cap must clear a HIGHER conviction bar (STACK_CONF),
    # the book must be NET GREEN, and the add must be SAME-SIDE as the winners
    # — pyramid into a working move, never average down / never hedge.
    if stacking:
        if confidence < STACK_CONF:
            _write_son_status("MANAGING",
                f"{sym}: {held}/{cap} — تكديس يحتاج ثقة ≥{STACK_CONF} (الآن {confidence:.2f})",
                genome_name, snap, side=side, sym=sym)
            return
        _bk_n, _bk_net, _bk_side = _symbol_book(sym)
        if _bk_net <= 0:
            _write_son_status("MANAGING",
                f"{sym}: الكتاب بخسارة ({_bk_net:+.2f}) — لا تكديس إلا على رابح",
                genome_name, snap, side=side, sym=sym)
            return
        if _bk_side and side != _bk_side:
            _write_son_status("MANAGING",
                f"{sym}: تكديس بنفس اتجاه الرابح فقط ({_bk_side}) — لا عكس",
                genome_name, snap, side=side, sym=sym)
            return

    # ── TREND-ALIGNMENT GATE — THE root-cause fix for the gold losses.
    # Never take a trade that fights a CONFIRMED higher-timeframe trend (the son
    # was buying gold straight into a TREND_DOWN). Buying the dip WITH the trend
    # still passes — only counter-HTF entries are vetoed. Genome-tunable so a
    # mean-reversion genome can relax it if it ever proves itself.
    if bool(genome_params.get("trend_align", True)):
        try:
            from runtime.shared.trend_filter import counter_trend_veto
            ta_min = float(genome_params.get("trend_align_min", 0.45))
            veto, ta_reason = counter_trend_veto(snap, side, ta_min)
            if veto:
                _write_son_status("TREND_VETO", ta_reason,
                                  genome_name, snap, side=side, sym=sym)
                if not AGGRO_AGENTS_SUPPORT:
                    return
                confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
            reason = f"{reason} | ترند {ta_reason}"
        except Exception as _te:
            print(f"[trend] gate skipped ({sym}): {_te}")  # never blocks on error

    # ── REGIME GATE (pro-panel Step-1, extended to the genome) — the single
    # highest-EV fix. The 6-specialist desk found the genome firing directional
    # trades in ADX≈7 / efficiency≈0.05 chop (20% live WR). Don't trade noise:
    # when the live signal flags no-trend, veto NEW entries — UNLESS the genome
    # is explicitly a mean-reversion strategy (allow_chop) or a strong reversal
    # is firing. Also veto fighting the D1/H4 trend. Fail-open on any error.
    if bool(genome_params.get("regime_gate", True)) and not bool(genome_params.get("allow_chop", False)):
        try:
            from runtime.shared.brain_signal import brain_regime
            rg = brain_regime(sym)
            if rg.get("ok"):
                if rg["no_trend"]:
                    _write_son_status("REGIME_CHOP",
                                      f"{side}: لا اتجاه (ADX {rg['adx']} / ER {rg['er']}) — لا دخول بالضجيج",
                                      genome_name, snap, side=side, sym=sym)
                    if not AGGRO_AGENTS_SUPPORT:
                        return
                    confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
                hd = rg.get("htf_dir")
                if hd in ("BUY", "SELL") and hd != side:
                    _write_son_status("HTF_VETO",
                                      f"{side}: ترند D1/H4 {hd} يعاكس — لا تقاتل الإطار الأكبر",
                                      genome_name, snap, side=side, sym=sym)
                    if not AGGRO_AGENTS_SUPPORT:
                        return
                    confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
        except Exception as _re:
            print(f"[regime] gate skipped ({sym}): {_re}")  # never blocks on error

    # ── STRUCTURE GATE — the real trader's brain (FVG/IFVG/VWAP/VP/wicks/flow).
    # Born from the user's complaint that entries were "بالشكل الغبي والمكان الغبي".
    # • VETO  → never buy into supply / sell into demand / chase >2σ from VWAP.
    # • OPP   → if structure clearly favors the opposite side, don't fight it.
    # • WEAK  → no real demand/supply support → skip (enter AT zones, not in air).
    # struct_min is per-genome tunable so each symbol can demand its own evidence.
    try:
        from runtime.shared.structure_entry import structure_decision
        sd = structure_decision(snap, pt)
        s_long, s_short = sd.get("score_long", 0.0), sd.get("score_short", 0.0)
        side_score  = s_long if side == "BUY" else s_short
        opp_score   = s_short if side == "BUY" else s_long
        side_vetoes = sd.get("long_vetoes" if side == "BUY" else "short_vetoes") or []
        struct_min  = float(genome_params.get("struct_min", 0.10))

        if side_vetoes:
            _write_son_status("STRUCT_VETO", f"{side} مرفوض هيكلياً: {side_vetoes[0]}",
                              genome_name, snap, side=side, sym=sym)
            if not AGGRO_AGENTS_SUPPORT:
                return
            confidence = max(0.0, confidence - 0.20)   # agent support: nudge, don't block
        if opp_score - side_score >= 0.30:
            _write_son_status("STRUCT_OPP",
                              f"{side}: الهيكل يفضّل العكس ({opp_score:.2f} ضد {side_score:.2f})",
                              genome_name, snap, side=side, sym=sym)
            if not AGGRO_AGENTS_SUPPORT:
                return
            confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
        if side_score < struct_min:
            _write_son_status("STRUCT_WEAK",
                              f"{side}: لا هيكل داعم ({side_score:.2f} < {struct_min:.2f})",
                              genome_name, snap, side=side, sym=sym)
            if not AGGRO_AGENTS_SUPPORT:
                return
        # structure agrees → it can only RAISE conviction, never lower it
        confidence = round(min(1.0, max(confidence, side_score)), 2)
        s_reasons = sd.get("reasons") or []
        if s_reasons:
            reason = f"{reason} | هيكل {side_score:.2f}: {'، '.join(s_reasons[:2])}"
    except Exception as _se:
        print(f"[structure] gate skipped ({sym}): {_se}")  # never blocks on error

    # SELF-TUNING ML CLONE GATE — fire only where he historically WINS.
    thr, thr_why = _adaptive_pwin_threshold(regime_name)
    p_win = 0.5
    try:
        from runtime.ml_clone import predict as _ml_predict
        p_win = _ml_predict(snap, side)
        if p_win < thr:
            _write_son_status("ML_BLOCK",
                              f"{side}: P(win) {p_win:.2f} < {thr:.2f} [{thr_why}]",
                              genome_name, snap, side=side, p_win=p_win,
                              ml_min=thr, sym=sym)
            if not AGGRO_AGENTS_SUPPORT:
                return
            confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
        reason = f"{reason} | P(win) {p_win:.2f}≥{thr:.2f}"
    except Exception:
        pass  # ML never blocks trading on error

    # BRAIN-SIGNAL CONFLUENCE GATE — integrate the live blended signal (10
    # components + FADE, from chart_signal_writer) into R Native's engine.
    # Veto only when the brain STRONGLY opposes this side; agreement raises conviction.
    try:
        from runtime.shared.brain_signal import brain_confluence
        bdir, bconf, bwhy = brain_confluence(sym)
        if bdir and bdir != side and bconf >= 55.0:
            _write_son_status("BRAIN_OPP",
                              f"{side}: إشارة الدماغ تعارض ({bdir} {bconf:.0f}% {bwhy})",
                              genome_name, snap, side=side, sym=sym)
            if not AGGRO_AGENTS_SUPPORT:
                return
            confidence = max(0.0, confidence - 0.15)   # agent support: nudge, don't block
        if bdir == side:
            confidence = round(min(1.0, confidence + 0.05), 2)
            reason = f"{reason} | دماغ {bdir} {bconf:.0f}%"
    except Exception:
        pass  # brain gate never blocks on error / when neutral

    # FIRE
    _write_son_status("FIRING",
                      f"{side} conf {confidence} P(win) {p_win:.2f}≥{thr:.2f}",
                      genome_name, snap, side=side, p_win=p_win, ml_min=thr, sym=sym)
    ok = fire_entry(side, confidence, reason, snap, genome_params, genome_name, sym=sym)
    # Start the risk-sentinel cooldown so we don't re-fire the same setup instantly.
    if ok and sentinel:
        sentinel.mark_trade()
    if ok:
        # Drop the cached gate verdict so cooldown / rate-limit apply on the
        # very next scan (the 10s cache must never let a burst re-fire).
        _gate_cache.pop(sym, None)


# ──────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────
def main():
    global _last_genome_name, _last_sym_genome
    if not mt5.initialize() and not mt5.initialize():
        print("[unified_trader] mt5 init failed"); return
    acc = mt5.account_info()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║ [unified_trader] ONLINE — multi-symbol trading engine    ║")
    print("║ Replaces: simple + smart + genome + council + trailing   ║")
    print(f"║ Magic: {MAGIC}  ·  Balance: ${acc.balance:.2f}                 ║")
    print(f"║ Symbols: {' '.join(SYMBOLS)}")
    print(f"║ Caps: {MAX_OPEN_BY_SYM}  global {GLOBAL_MAX_OPEN}")
    print(f"║ Trail ladder: BE@3pt → +1@5pt → +5@8pt → +10@12pt        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Per-symbol circuit breakers + risk sentinels (account-level guards)
    for _s in SYMBOLS:
        _breakers[_s]  = CircuitBreaker(magic=MAGIC, symbol=_s)
        _sentinels[_s] = RiskSentinel(magic=MAGIC, symbol=_s)

    # Load any LEARNED scalp values the reflection engine has saved.
    _refresh_scalp_tunables(force=True)

    # 🛡️ Guard our son — restore the champion genome if it ever went missing
    try:
        from runtime.champion_seeder import seed as _seed_champion
        _cr = _seed_champion()
        if _cr.get("ok"):
            print(f"[champion] {_cr['champion']} — {', '.join(_cr['actions'])}")
    except Exception as _e:
        print(f"[champion] seeder skipped: {_e}")

    # Stall watchdog — self-exit (for a fresh respawn) if a wedged mt5 IPC
    # call blocks the loop for STALL_EXIT_S. See ANTI-WEDGE note up top.
    import threading
    threading.Thread(target=_stall_watchdog, daemon=True,
                     name="stall-watchdog").start()

    _last_entry_scan = 0.0
    _last_pending_scan = 0.0
    while True:
        try:
            _touch_hb()
            # ── FAST PATH (every POLL_S ≈150ms) — protect open money instantly.
            # Trailing SL / breakeven / loss-cut on EVERY position, any symbol/magic.
            # This is the part that must never "يغفي" on a fast move.
            manage_open_positions()
            # Reactively kill resting pendings whose level is already invalidated
            # (price blew through the SL before the entry could fill).
            if ENABLE_FVG_PENDING:
                manage_pending_orders()

            # ── ENTRY SCAN (every ENTRY_EVERY ≈500ms) — heavier structure + ML.
            # Structure zones / regime / ML don't change in 150ms, and scanning
            # entries this often (vs trailing) avoids any risk of double-firing.
            now = time.monotonic()
            if now - _last_entry_scan >= ENTRY_EVERY:
                _last_entry_scan = now
                _refresh_scalp_tunables()   # pick up freshly-learned scalp values
                # Genome — single source of truth, shared across all symbols
                live = _read_json(LIVE_GENOME) or {}
                if live:
                    genome_params = live.get("params", {})
                    genome_name = live.get("name", "UNKNOWN")
                    if genome_name != _last_genome_name:
                        print(f"\n[{datetime.now():%H:%M:%S}] 👑 LIVE GENOME = {genome_name}")
                        print(f"  rsi≤{genome_params.get('rsi_max')} P≥{genome_params.get('min_pressure_abs')} "
                               f"mtf≥{genome_params.get('min_mtf_agreement')} lot {genome_params.get('lot')}")
                        _last_genome_name = genome_name

                    # Should we also refresh resting FVG pending orders this pass?
                    do_pending = (ENABLE_FVG_PENDING
                                  and now - _last_pending_scan >= PENDING_EVERY)
                    if do_pending:
                        _last_pending_scan = now
                        _reconcile_fvg_levels()   # update level memory before re-arming

                    # Each symbol gets its OWN genome (own values/genes) if present,
                    # else falls back to the shared champion. 'كل عمله ولها قيمها الخاصة'.
                    g_held = _global_open_count()
                    for sym in SYMBOLS:
                        try:
                            _touch_hb()   # progress marker — slow scans never trip the stall exit
                            sym_params, sym_name = _load_genome_for(sym, live)
                            if _last_sym_genome.get(sym) != sym_name:
                                tag = "خاص" if sym_name != genome_name else "مشترك"
                                print(f"[{datetime.now():%H:%M:%S}] 🧬 {sym} genome = {sym_name} ({tag})")
                                _last_sym_genome[sym] = sym_name
                            process_symbol(sym, sym_params, sym_name, g_held)
                            g_held = _global_open_count()   # refresh after a possible fill
                            # FVG-anchored pending orders — rest LIMIT/STOP on gaps
                            # the son expects price to revisit (reversal / breakout).
                            # FVG pendings are NEW entries too — suppress them
                            # under the same account-wide DD lockout that gates
                            # process_symbol above. Fail-open on missing file.
                            if do_pending and not _dd_blocks_new_entries():
                                snap = _read_json(_brain_path_for(sym))
                                if snap:
                                    brk = _breakers.get(sym)
                                    snt = _sentinels.get(sym)
                                    # cached verdict (anti IPC-flood) — same 10s window
                                    cbv = (_cached_gate_checks(sym, brk, snt)[0]
                                           if (brk and snt) else (brk.check() if brk else None))
                                    if not cbv:                     # not frozen
                                        place_fvg_pendings(sym, sym_params, sym_name,
                                                           snap, _pt(sym), g_held)
                        except Exception as _e:
                            print(f"[{sym}] err: {_e}")

            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("\n[unified_trader] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
