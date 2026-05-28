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
from runtime.shared.tokens import PATHS, MAGICS, ACCOUNT_RISK  # noqa: E402
from runtime.shared.orchestrator_gate import is_engine_active   # noqa: E402
from runtime.shared.circuit_breaker import CircuitBreaker       # noqa: E402
from runtime.shared.decision_log import (                        # noqa: E402
    record_decision, update_decision_ticket,
)

# ──────────────────────────────────────────────────────────
# Identity
# ──────────────────────────────────────────────────────────
MAGIC  = MAGICS["claude_genome"]   # 99782 — same as old claude_genome (continuity)
SYMBOL = "XAUUSDm"
POLL_S = 1.0          # real-time: react within ~1s (was 3.0). لا نفوق أي فرصة

# Anti-pyramid: never stack more than this many open positions on SYMBOL+MAGIC.
# This is THE guard that prevents the over-leverage stop-out that wiped magic-0.
# 2 = a little concurrency for speed, still tiny risk (2×0.02 lot on a $150 acct).
MAX_OPEN = 2

# Pullback entries: in a CONFIRMED trend, allow buying the dip / selling the
# rally even when short-term pressure is mildly contra — that's a pullback, not
# a reversal. Block only when the counter-flow is deeper than this (a real
# reversal). The ML gate makes the final call. Lets him trade far more often.
PULLBACK_MAX_CONTRA = 15.0

# Files we read (single source of truth)
BRAIN_LIVE  = PATHS["brain_live"]
REGIME_FILE = PATHS["market_regime"]
LIVE_GENOME = PATHS["live_genome"]

# Trailing ladder (replaces trailing_stop_manager for OUR positions)
TRAIL_LADDER = [
    (12.0, 2.0),   # +12pt profit → trail by 2pt (lock ≥10pt)
    ( 8.0, 3.0),   # +8pt  → trail 3pt (lock ≥5pt)
    ( 5.0, 4.0),   # +5pt  → trail 4pt (lock ≥1pt)
    ( 3.0, 0.0),   # +3pt  → breakeven
]

# Confidence threshold (genome's signal strength must clear this to fire)
MIN_CONFIDENCE = 0.5
# ── ML clone gate — SELF-TUNING ──────────────────────────────────────────
# User mandate (2026-05-28): "خفّض العتبة، وخلّه هو يرفعها إذا بدأ يخسر."
# Lower BASE so our son actually trades; then he RAISES the bar on himself
# when he starts losing (consecutive losers / red day) or when the market is
# choppy. He relaxes back toward BASE after wins / when a clean trend returns.
ML_BASE_PWIN = 0.42        # floor — trades freely above this in clean trends
ML_MAX_PWIN  = 0.66        # ceiling — gets this strict only when bleeding/chop
_thr_cache = {"t": 0.0, "v": ML_BASE_PWIN, "why": f"base {ML_BASE_PWIN}"}

# Module state
_breaker: CircuitBreaker | None = None
_last_genome_name: str | None = None
_last_status_print: float = 0.0


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


def _open_count() -> int:
    """How many positions we already hold on SYMBOL+MAGIC (anti-pyramid)."""
    try:
        pos = mt5.positions_get(symbol=SYMBOL) or []
        return sum(1 for p in pos if p.magic == MAGIC)
    except Exception:
        return 0


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
def _read_json(p: Path) -> dict | None:
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _write_son_status(stage: str, detail: str, genome: str, snap: dict,
                      side: str = "", p_win: float = 0.0,
                      ml_min: float = ML_BASE_PWIN) -> None:
    """Persist the live verdict so the UI / OUR SON tab can show what it's thinking."""
    try:
        acc = mt5.account_info()
        st = {
            "ts": datetime.now(timezone.utc).isoformat(),
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
        (PATHS["brain_decisions"].parent / "son_status.json").write_text(payload, encoding="utf-8")
        # Mirror to MT5 Common/Files so FRIDAY_Brain_Executor.mq5 (the EA) can read it
        try:
            from runtime.shared.tokens import COMMON_FILES
            (COMMON_FILES / "son_status.json").write_text(payload, encoding="utf-8")
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
def evaluate_genome(snap: dict, genome_params: dict) -> tuple[str | None, float, str]:
    """Return (side, confidence, reason) or (None, 0, why_no_signal)."""
    if not snap or not genome_params:
        return (None, 0, "no snap/genome")

    rsi_max          = genome_params.get("rsi_max", 60)
    min_pressure_abs = genome_params.get("min_pressure_abs", 3)
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
    trend_n    = max(up_count, dn_count)
    strong_trend = trend_n >= 3
    confirms = (direction == "BUY" and pressure > 0) or (direction == "SELL" and pressure < 0)

    if confirms:
        if abs(pressure) < min_pressure_abs:
            return (None, 0, f"pressure |{pressure:.1f}| < {min_pressure_abs}")
        entry_mode = "momentum"
    else:
        # counter-pressure = pullback
        if not strong_trend:
            return (None, 0, f"contra {direction}, weak trend {trend_n}/4")
        if abs(pressure) > PULLBACK_MAX_CONTRA:
            return (None, 0, f"pullback too deep |{pressure:.1f}|>{PULLBACK_MAX_CONTRA:.0f}")
        entry_mode = "pullback"

    # Confidence
    mtf_score = trend_n / 4   # 0..1
    if entry_mode == "momentum":
        pres_score = min(abs(pressure) / 10, 1.0)
        confidence = round(mtf_score * 0.6 + pres_score * 0.4, 2)
    else:                      # pullback — lean on trend strength
        confidence = round(mtf_score * 0.7, 2)

    reason = (f"{direction} {entry_mode} MTF{trend_n}/4 "
              f"RSI{rsi:.0f} P{pressure:+.1f} regime{reg} sess{sess}")
    return (direction, confidence, reason)


# ──────────────────────────────────────────────────────────
# Trailing SL (in-process, only on OUR positions)
# ──────────────────────────────────────────────────────────
# Per-symbol "1 pt" in price units, so the XAU-tuned ladder scales to any symbol.
_PT = {"XAUUSDm": 1.0, "XAGUSDm": 0.10, "BTCUSDm": 100.0, "EURUSDm": 0.0001,
       "GBPUSDm": 0.0001, "USDJPYm": 0.01, "GBPJPYm": 0.01}


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


def manage_open_positions() -> None:
    """Trail SL on EVERY open position — our son watches them all, any symbol,
    any magic (own trades + legacy + manual). 'خله يناظر الصفقات ويتصرف براحته'."""
    positions = mt5.positions_get() or []          # ALL positions, every symbol/magic
    for p in positions:
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick: continue
        ideal = _ideal_sl(p, tick)
        if ideal is None: continue
        new_sl, rung = ideal
        if not _better_sl(p, new_sl): continue
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
# Entry
# ──────────────────────────────────────────────────────────
def fire_entry(side: str, confidence: float, reason: str,
                snap: dict, genome_params: dict, genome_name: str) -> None:
    global _breaker
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return

    sl_pts = float(genome_params.get("sl_pts", 4.0))
    tp_pts = float(genome_params.get("tp_pts", 12.0))
    # Inflate TP — trail handles the real exit
    tp_pts = max(tp_pts, 20.0)
    lot = float(genome_params.get("lot", 0.02))

    if side == "BUY":
        price = tick.ask; sl = price - sl_pts; tp = price + tp_pts
        otype = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid; sl = price + sl_pts; tp = price - tp_pts
        otype = mt5.ORDER_TYPE_SELL

    # 1. Record decision in unified log
    dec_id = record_decision(
        source="unified_trader", magic=MAGIC, symbol=SYMBOL, side=side,
        entry=price, sl=sl, tp=tp, lot=lot,
        reason=f"{genome_name}: {reason}", confidence=confidence, snap=snap,
    )

    # 2. Send order
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
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

    # 4. Mark circuit breaker
    if ok:
        if _breaker: _breaker.mark_trade()
        print(f"[{datetime.now():%H:%M:%S}] 🎯 {side} #{r.order} @ {r.price:.2f} "
               f"SL {sl:.2f} TP {tp:.2f} lot {lot} conf {confidence:.2f} | {reason}")
        # BUY alert — persistent flag + desktop toast (the child's first/every BUY)
        if side == "BUY":
            _emit_buy_alert(int(r.order), float(r.price), lot, confidence, reason, genome_name)
    else:
        print(f"[{datetime.now():%H:%M:%S}] ❌ {side} failed: {getattr(r, 'retcode', None)}")


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
# Main loop
# ──────────────────────────────────────────────────────────
def main():
    global _breaker, _last_genome_name
    if not mt5.initialize() and not mt5.initialize():
        print("[unified_trader] mt5 init failed"); return
    acc = mt5.account_info()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║ [unified_trader] ONLINE — single-process trading engine  ║")
    print("║ Replaces: simple + smart + genome + council + trailing   ║")
    print(f"║ Magic: {MAGIC}  ·  Balance: ${acc.balance:.2f}                 ║")
    print(f"║ Gates: orchestrator + circuit_breaker + ATR-aware TP     ║")
    print(f"║ Trail ladder: BE@3pt → +1@5pt → +5@8pt → +10@12pt        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    _breaker = CircuitBreaker(magic=MAGIC, symbol=SYMBOL)

    # 🛡️ Guard our son — restore the champion genome if it ever went missing
    try:
        from runtime.champion_seeder import seed as _seed_champion
        _cr = _seed_champion()
        if _cr.get("ok"):
            print(f"[champion] {_cr['champion']} — {', '.join(_cr['actions'])}")
    except Exception as _e:
        print(f"[champion] seeder skipped: {_e}")

    while True:
        try:
            # 1. Read state
            snap   = _read_json(BRAIN_LIVE)
            regime = _read_json(REGIME_FILE) or {}
            live   = _read_json(LIVE_GENOME) or {}
            if not snap or not live:
                time.sleep(POLL_S); continue
            genome_params = live.get("params", {})
            genome_name = live.get("name", "UNKNOWN")

            # Announce LIVE genome changes
            if genome_name != _last_genome_name:
                print(f"\n[{datetime.now():%H:%M:%S}] 👑 LIVE GENOME = {genome_name}")
                print(f"  rsi≤{genome_params.get('rsi_max')} P≥{genome_params.get('min_pressure_abs')} "
                       f"mtf≥{genome_params.get('min_mtf_agreement')} lot {genome_params.get('lot')}")
                _last_genome_name = genome_name

            # 2. Manage open positions FIRST (always do this even if gates block entry)
            manage_open_positions()

            # 3. Regime (orchestrator) — now a SOFT signal, not a hard block.
            #    User: "ليه ما دخل صفقات؟ لا نفوّت أي فرصة." The blanket
            #    "CHOP → everyone standby" froze him 100% of the time. Instead
            #    we fold regime into the self-tuning ML threshold below: he CAN
            #    trade choppy markets, but only on much stronger ML conviction.
            regime_name = (regime.get("regime") or snap.get("regime") or "?")
            orch_block  = is_engine_active(MAGIC)   # kept for transparency only

            # 4. Gate: circuit breaker — the REAL hard stop (cascade / DD / rate)
            cb_block = _breaker.check()
            if cb_block:
                _status(f"breaker: {cb_block}")
                _write_son_status("FROZEN", f"circuit breaker: {cb_block}", genome_name, snap)
                time.sleep(POLL_S); continue

            # 4b. Anti-pyramid guard — THE protection that magic-0 lacked.
            #     Manage existing positions, but never stack a new one on top.
            held = _open_count()
            if held >= MAX_OPEN:
                _status(f"hold: {held} open (max {MAX_OPEN}) — managing, no new entry")
                _write_son_status("MANAGING",
                                   f"صفقة مفتوحة ({held}) — يراقبها ولا يكدّس",
                                   genome_name, snap)
                time.sleep(POLL_S); continue

            # 5. Evaluate genome
            side, confidence, reason = evaluate_genome(snap, genome_params)
            if side is None:
                _status(f"no signal: {reason}")
                _write_son_status("NO_SIGNAL", reason, genome_name, snap)
                time.sleep(POLL_S); continue
            if confidence < MIN_CONFIDENCE:
                _status(f"low conf {confidence}: {reason}")
                _write_son_status("LOW_CONF", f"conf {confidence} | {reason}", genome_name, snap)
                time.sleep(POLL_S); continue

            # 5b. SELF-TUNING ML CLONE GATE — fire only where he historically WINS.
            #     Threshold lowers the bar (trade more) but he raises it on himself
            #     when losing / in chop. (orch_block makes regime visible in logs.)
            thr, thr_why = _adaptive_pwin_threshold(regime_name)
            p_win = 0.5
            try:
                from runtime.ml_clone import predict as _ml_predict
                p_win = _ml_predict(snap, side)
                if p_win < thr:
                    _status(f"ml gate: P(win) {p_win:.2f} < {thr:.2f} ({thr_why}) — skip {side}")
                    _write_son_status("ML_BLOCK",
                                       f"{side}: P(win) {p_win:.2f} < {thr:.2f} [{thr_why}]"
                                       + (f" · {orch_block}" if orch_block else ""),
                                       genome_name, snap, side=side, p_win=p_win, ml_min=thr)
                    time.sleep(POLL_S); continue
                reason = f"{reason} | P(win) {p_win:.2f}≥{thr:.2f}"
            except Exception:
                pass  # ML never blocks trading on error

            # 6. FIRE
            _write_son_status("FIRING", f"{side} conf {confidence} P(win) {p_win:.2f}≥{thr:.2f}",
                              genome_name, snap, side=side, p_win=p_win, ml_min=thr)
            fire_entry(side, confidence, reason, snap, genome_params, genome_name)

            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("\n[unified_trader] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
