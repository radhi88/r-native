"""runtime/claude_smart_trader.py — v2 with regime filters.

Born 2026-05-28 after simple_trader lost 30% in chop ASIAN session.
This version adds the missing filters:

  1. ADX_M5 ≥ 20 (trending only — no chop)
  2. Session: NY_OVERLAP or LONDON only (no ASIAN whipsaw)
  3. No-chase: don't enter same-side within 3pt of prev entry
  4. Tight SL 3pt (was 5pt) — smaller losses
  5. Wider TP 10pt (was 8pt) — better R:R 3.3:1
  6. Pause 30min after 2 consecutive SLs
  7. Daily loss limit on REALIZED only (not equity)
  8. Skip if last bar spike (vol > 200% = exhaustion)

Magic 99781 (new — separate from broken v1).
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.shared.orchestrator_gate import is_engine_active  # noqa: E402
from runtime.shared.circuit_breaker import CircuitBreaker  # noqa: E402
from runtime.shared.decision_log import record_decision, update_decision_ticket  # noqa: E402

_breaker = None

SYMBOL = "XAUUSDm"
MAGIC = 99781
BRAIN_LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
TRADE_LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_smart_trades.jsonl")
POLL = 5.0

# Risk contract — STRICTER
MAX_OPEN = 2                # was 3, less exposure
MAX_LOT_TOTAL = 0.03        # was 0.05
LOT_PER_TRADE = 0.01
SL_PTS = 3.0                # tight initial; trailing manager protects from there
TP_PTS = 25.0               # FAR safety net — trailing handles real exits
COOLDOWN_SEC = 120          # was 60 — slower
DAILY_LOSS_LIMIT = -15.0    # realized only
MIN_EQUITY = 50.0

# Regime filters (NEW)
MIN_ADX = 20                # trending only
ALLOWED_SESSIONS = ["NY_OVERLAP", "LONDON", "NY_LATE"]  # NO ASIAN
NO_CHASE_PTS = 3.0          # don't enter within 3pt of last entry
CONSEC_SL_PAUSE_COUNT = 2
CONSEC_SL_PAUSE_MIN = 30

_last_trade_ts = 0
_last_entry_price = 0
_last_entry_side = None
_consec_sl_pause_until = 0


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def get_realized_today() -> tuple[float, int]:
    """Returns (realized_pnl, num_closes) for this magic in last 12h."""
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    mine = [d for d in deals if int(d.magic) == MAGIC and int(d.entry) in (1, 2)]
    realized = sum(float(d.profit) for d in mine)
    return realized, len(mine)


def get_consec_sl_count() -> int:
    """Count consecutive SLs in last 1 hour."""
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    mine = sorted([d for d in deals if int(d.magic) == MAGIC and int(d.entry) in (1, 2)],
                   key=lambda d: d.time, reverse=True)
    consec = 0
    for d in mine:
        if float(d.profit) < 0: consec += 1
        else: break
    return consec


def evaluate_signal(snap: dict) -> tuple[str | None, str]:
    if not snap: return (None, "no snap")

    bias_m1 = snap.get("bias", {}).get("m1", "?")
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")
    rsi = snap.get("rsi", {}).get("m1", 50)
    pressure = snap.get("pressure_10m1", 0)
    bars = snap.get("m1_last5", [])
    last_bar = bars[-1] if bars else {}
    last_kind = last_bar.get("kind", "")
    last_body = last_bar.get("body_pct", 0)
    last_vol = last_bar.get("v", 0)
    session = snap.get("session", "?")
    spread = snap.get("spread", 0)
    adx_m5 = snap.get("adx", {}).get("m5", 0)

    # SESSION FILTER
    if session not in ALLOWED_SESSIONS:
        return (None, f"session {session} blocked (need NY/LONDON)")

    # SPREAD
    if spread > 0.5:
        return (None, f"spread ${spread:.2f} too wide")

    # ADX FILTER (regime check)
    if adx_m5 < MIN_ADX:
        return (None, f"ADX_M5 {adx_m5:.1f} < {MIN_ADX} (chop)")

    # Vol spike avoidance (exhaustion)
    avg_vol = sum(b.get("v", 0) for b in bars[-5:]) / max(len(bars), 1) if bars else 100
    if avg_vol > 0 and last_vol > avg_vol * 2.0:
        return (None, f"vol spike {last_vol}/{avg_vol:.0f} = exhaustion risk")

    up_count = [bias_m1, bias_m5, bias_m15].count("UP")
    dn_count = [bias_m1, bias_m5, bias_m15].count("DOWN")

    # BUY: need 3/3 UP + bullish bar + pressure positive
    if up_count == 3 and pressure > 0.5 and 30 <= rsi <= 65:
        if last_kind in ("strong_bull", "marubozu_bull", "hammer"):
            return ("BUY", f"3/3 UP, ADX {adx_m5:.0f}, RSI {rsi}, P{pressure:+.1f}, {last_kind}")

    # SELL: need 3/3 DOWN + bearish bar + pressure negative
    if dn_count == 3 and pressure < -0.5 and 35 <= rsi <= 70:
        if last_kind in ("strong_bear", "marubozu_bear", "shooting_star"):
            return ("SELL", f"3/3 DOWN, ADX {adx_m5:.0f}, RSI {rsi}, P{pressure:+.1f}, {last_kind}")

    return (None, f"no signal (UP={up_count} DN={dn_count} RSI={rsi} ADX={adx_m5:.0f})")


def hard_guards(equity: float, side: str | None) -> str | None:
    global _last_entry_price, _last_entry_side, _consec_sl_pause_until

    if equity < MIN_EQUITY:
        return f"equity ${equity:.2f} < ${MIN_EQUITY}"

    # Realized daily loss check (NOT floating)
    realized, num = get_realized_today()
    if realized <= DAILY_LOSS_LIMIT:
        return f"realized today ${realized:+.2f} ≤ ${DAILY_LOSS_LIMIT}"

    # Cooldown between trades
    if time.time() - _last_trade_ts < COOLDOWN_SEC:
        return f"cooldown {int(COOLDOWN_SEC - (time.time() - _last_trade_ts))}s"

    # Consecutive SL pause
    if time.time() < _consec_sl_pause_until:
        return f"paused {int(_consec_sl_pause_until - time.time())}s (consec SLs)"
    consec = get_consec_sl_count()
    if consec >= CONSEC_SL_PAUSE_COUNT:
        _consec_sl_pause_until = time.time() + CONSEC_SL_PAUSE_MIN * 60
        return f"{consec} consec SLs → pause {CONSEC_SL_PAUSE_MIN}min"

    # Max open + lot
    positions = mt5.positions_get(symbol=SYMBOL) or []
    my_pos = [p for p in positions if int(p.magic) == MAGIC]
    if len(my_pos) >= MAX_OPEN:
        return f"max {MAX_OPEN} open"
    if sum(float(p.volume) for p in my_pos) >= MAX_LOT_TOTAL:
        return f"max lot {MAX_LOT_TOTAL}"

    # No-chase rule
    if side and _last_entry_price > 0:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick:
            cur = tick.ask if side == "BUY" else tick.bid
            if side == _last_entry_side and abs(cur - _last_entry_price) < NO_CHASE_PTS:
                return f"no-chase: too close to last {_last_entry_side} @ {_last_entry_price:.2f}"

    return None


def execute(side: str, reason: str):
    global _last_trade_ts, _last_entry_price, _last_entry_side
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return
    if side == "BUY":
        price = tick.ask; sl = price - SL_PTS; tp = price + TP_PTS
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid; sl = price + SL_PTS; tp = price - TP_PTS
        order_type = mt5.ORDER_TYPE_SELL

    # Record decision in unified log
    _snap = None
    try:
        import json as _json
        _snap = _json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
    except Exception: pass
    _dec_id = record_decision(
        source="claude_smart", magic=MAGIC, symbol=SYMBOL, side=side,
        entry=price, sl=sl, tp=tp, lot=LOT_PER_TRADE,
        reason=reason, snap=_snap,
    )

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": LOT_PER_TRADE, "type": order_type,
        "price": price, "sl": sl, "tp": tp,
        "deviation": 50, "magic": MAGIC,
        "comment": f"CLAUDE_SMART_{side}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    _ok_send = r and r.retcode == mt5.TRADE_RETCODE_DONE
    update_decision_ticket(_dec_id, int(r.order) if _ok_send else 0,
                            error="" if _ok_send else f"retcode {getattr(r,'retcode','?')}")
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    if ok:
        _last_trade_ts = time.time()
        _last_entry_price = float(r.price)
        _last_entry_side = side
        print(f"[{datetime.now():%H:%M:%S}] ✅ {side} #{r.order} @ {r.price:.2f} "
               f"SL {sl:.2f} TP {tp:.2f} R:R 3.3:1 | {reason}")
        _append(TRADE_LOG, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "side": side, "ticket": int(r.order),
            "entry": float(r.price), "sl": sl, "tp": tp,
            "reason": reason,
        })
    else:
        print(f"[{datetime.now():%H:%M:%S}] ❌ {side} failed: {getattr(r, 'retcode', None)}")


def main():
    if not mt5.initialize(): mt5.initialize()
    acc = mt5.account_info()
    print(f"[claude_smart_trader v2] ONLINE — magic {MAGIC}")
    print(f"  Balance: ${acc.balance:.2f}  Equity: ${acc.equity:.2f}")
    print(f"  Filters: ADX≥{MIN_ADX} · sessions {ALLOWED_SESSIONS}")
    print(f"  Caps: max {MAX_OPEN} open · SL {SL_PTS}pt · TP {TP_PTS}pt (R:R 3.3:1)")
    print(f"  Cooldown {COOLDOWN_SEC}s · {CONSEC_SL_PAUSE_COUNT} consec SLs → pause {CONSEC_SL_PAUSE_MIN}min")
    print(f"  Daily limit: ${DAILY_LOSS_LIMIT} realized · floor ${MIN_EQUITY}")

    while True:
        try:
            if not BRAIN_LIVE.exists():
                time.sleep(POLL); continue
            snap = json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
            acc = mt5.account_info()
            side, reason = evaluate_signal(snap)
            blocker = hard_guards(acc.equity, side)
            if blocker:
                # silent skip
                time.sleep(POLL); continue
            # Orchestrator gate — respect regime decision
            if is_engine_active(MAGIC):
                time.sleep(POLL); continue
            # Circuit breaker
            global _breaker
            if _breaker is None: _breaker = CircuitBreaker(MAGIC, SYMBOL)
            if _breaker.check():
                time.sleep(POLL); continue
            if side:
                execute(side, reason)
                if _breaker: _breaker.mark_trade()
            time.sleep(POLL)
        except KeyboardInterrupt:
            print("[claude_smart_trader] stopped"); break
        except Exception as e:
            print(f"[claude_smart_trader] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
