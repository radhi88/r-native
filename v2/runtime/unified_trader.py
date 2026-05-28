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
POLL_S = 3.0

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
# ML clone gate — minimum P(win) from the user-cloned model to allow entry
ML_MIN_PWIN = 0.50

# Module state
_breaker: CircuitBreaker | None = None
_last_genome_name: str | None = None
_last_status_print: float = 0.0


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
def _read_json(p: Path) -> dict | None:
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


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

    # Pressure must confirm direction
    pressure = float(snap.get("pressure_10m1", 0))
    if abs(pressure) < min_pressure_abs:
        return (None, 0, f"pressure |{pressure:.1f}| < {min_pressure_abs}")
    if direction == "BUY"  and pressure < 0: return (None, 0, "pressure contra BUY")
    if direction == "SELL" and pressure > 0: return (None, 0, "pressure contra SELL")

    # Confidence — combine MTF + pressure
    mtf_score = max(up_count, dn_count) / 4   # 0..1
    pres_score = min(abs(pressure) / 10, 1.0) # 0..1
    confidence = round((mtf_score * 0.6 + pres_score * 0.4), 2)

    reason = (f"{direction} MTF{max(up_count, dn_count)}/4 "
              f"RSI{rsi:.0f} P{pressure:+.1f} regime{reg} sess{sess}")
    return (direction, confidence, reason)


# ──────────────────────────────────────────────────────────
# Trailing SL (in-process, only on OUR positions)
# ──────────────────────────────────────────────────────────
def _ideal_sl(pos, tick) -> tuple[float, str] | None:
    p_pts = (tick.bid - pos.price_open) if pos.type == 0 else (pos.price_open - tick.ask)
    for trigger, dist in TRAIL_LADDER:
        if p_pts >= trigger:
            if dist == 0:
                return (pos.price_open, f"BE@{trigger:.0f}")
            if pos.type == 0:   # BUY
                return (round(tick.bid - dist, 2), f"trail{dist:.0f}@{trigger:.0f}")
            return (round(tick.ask + dist, 2), f"trail{dist:.0f}@{trigger:.0f}")
    return None


def _better_sl(pos, new_sl: float) -> bool:
    if pos.sl == 0: return True
    if pos.type == 0: return new_sl > pos.sl + 0.01
    return new_sl < pos.sl - 0.01


def manage_open_positions() -> None:
    """Trail SL on our open positions."""
    positions = mt5.positions_get(symbol=SYMBOL) or []
    my_pos = [p for p in positions if int(p.magic) == MAGIC]
    for p in my_pos:
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick: continue
        ideal = _ideal_sl(p, tick)
        if ideal is None: continue
        new_sl, rung = ideal
        if not _better_sl(p, new_sl): continue
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": int(p.ticket),
            "symbol":   SYMBOL,
            "sl":       float(new_sl),
            "tp":       float(p.tp),
            "magic":    MAGIC,
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

            # 3. Gate: orchestrator
            orch_block = is_engine_active(MAGIC)
            if orch_block:
                _status(f"gate: {orch_block}")
                time.sleep(POLL_S); continue

            # 4. Gate: circuit breaker
            cb_block = _breaker.check()
            if cb_block:
                _status(f"breaker: {cb_block}")
                time.sleep(POLL_S); continue

            # 5. Evaluate genome
            side, confidence, reason = evaluate_genome(snap, genome_params)
            if side is None:
                _status(f"no signal: {reason}")
                time.sleep(POLL_S); continue
            if confidence < MIN_CONFIDENCE:
                _status(f"low conf {confidence}: {reason}")
                time.sleep(POLL_S); continue

            # 5b. ML CLONE GATE — only fire in contexts that historically WIN
            #     (learned from the user's 80%-WR trades; AUC 0.72). Advisory:
            #     if no model, p_win=0.5 (pass-through). Blocks weak contexts.
            try:
                from runtime.ml_clone import predict as _ml_predict
                p_win = _ml_predict(snap, side)
                if p_win < ML_MIN_PWIN:
                    _status(f"ml gate: P(win) {p_win:.2f} < {ML_MIN_PWIN} — skip {side}")
                    time.sleep(POLL_S); continue
                reason = f"{reason} | P(win) {p_win:.2f}"
            except Exception:
                pass  # ML never blocks trading on error

            # 6. FIRE
            fire_entry(side, confidence, reason, snap, genome_params, genome_name)

            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("\n[unified_trader] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
