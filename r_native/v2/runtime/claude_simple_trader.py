"""runtime/claude_simple_trader.py — Simple aggressive autonomous trader.

Built 2026-05-27 because the complex brain (archetypes + 7 rules) is TOO
restrictive — keeps saying WAIT. User funded $100, wants trades.

Strategy: pure confluence check on brain_live.json snapshot every 5s.
  BUY if: MTF align UP + pressure > 0 + RSI 30-65 + last bar bull
  SELL if: MTF align DOWN + pressure < 0 + RSI 35-70 + last bar bear

Hard caps:
  • Max 3 open positions (this trader only)
  • Max 0.05 lot total
  • $5 risk per trade (5pt SL × 0.01 lot)
  • Daily loss limit: -$15 → stop
  • Min equity: $80 → stop
  • 60s cooldown between trades
  • Magic: 99780 (CLAUDE_SIMPLE)
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.shared.orchestrator_gate import is_engine_active  # noqa: E402
from runtime.shared.circuit_breaker import CircuitBreaker  # noqa: E402
from runtime.shared.decision_log import record_decision, update_decision_ticket  # noqa: E402

_breaker = None

SYMBOL = "XAUUSDm"
MAGIC = 99780
BRAIN_LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
TRADE_LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_simple_trades.jsonl")
POLL = 5.0

# Risk contract
MAX_OPEN = 3
MAX_LOT_TOTAL = 0.05
LOT_PER_TRADE = 0.01
SL_PTS = 5.0
TP_PTS = 20.0   # FAR — trailing_stop_manager handles real exits
COOLDOWN_SEC = 60
DAILY_LOSS_LIMIT = -15.0
MIN_EQUITY = 80.0

_last_trade_ts = 0
_baseline_equity = 0


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def evaluate_signal(snap: dict) -> tuple[str | None, str]:
    """Returns (BUY/SELL/None, reason)."""
    if not snap: return (None, "no snap")

    bias_m1 = snap.get("bias", {}).get("m1", "?")
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")
    rsi = snap.get("rsi", {}).get("m1", 50)
    pressure = snap.get("pressure_10m1", 0)
    mtf = snap.get("mtf_align", "MIXED")
    bars = snap.get("m1_last5", [])
    last_bar = bars[-1] if bars else {}
    last_kind = last_bar.get("kind", "")
    last_body = last_bar.get("body_pct", 0)
    session = snap.get("session", "?")
    spread = snap.get("spread", 0)

    if spread > 0.5:
        return (None, f"spread ${spread:.2f} too wide")

    # BUY conditions
    up_count = [bias_m1, bias_m5, bias_m15].count("UP")
    dn_count = [bias_m1, bias_m5, bias_m15].count("DOWN")

    if up_count >= 2 and pressure > -1 and 25 <= rsi <= 70:
        # Bonus: last bar bull
        if last_kind in ("strong_bull", "marubozu_bull", "normal_bull", "hammer"):
            return ("BUY", f"{up_count}/3 UP, RSI {rsi}, P{pressure:+.1f}, {last_kind}")
        # Even without bullish bar, if MTF strongly UP
        if up_count == 3 and pressure > 1:
            return ("BUY", f"3/3 UP MTF, RSI {rsi}, P{pressure:+.1f}, strong align")

    if dn_count >= 2 and pressure < 1 and 30 <= rsi <= 75:
        if last_kind in ("strong_bear", "marubozu_bear", "normal_bear", "shooting_star"):
            return ("SELL", f"{dn_count}/3 DOWN, RSI {rsi}, P{pressure:+.1f}, {last_kind}")
        if dn_count == 3 and pressure < -1:
            return ("SELL", f"3/3 DOWN MTF, RSI {rsi}, P{pressure:+.1f}, strong align")

    return (None, f"no confluence (up={up_count} dn={dn_count} rsi={rsi} P{pressure:+.1f})")


def hard_guards(mt5, equity: float) -> str | None:
    global _baseline_equity
    if _baseline_equity == 0:
        _baseline_equity = equity
    if equity < MIN_EQUITY:
        return f"equity ${equity:.2f} < ${MIN_EQUITY}"
    # Check REALIZED daily losses (not floating)
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    realized = sum(float(d.profit) for d in deals
                    if int(d.magic) == MAGIC and int(d.entry) in (1, 2))
    if realized <= DAILY_LOSS_LIMIT:
        return f"realized daily ${realized:+.2f} ≤ ${DAILY_LOSS_LIMIT}"
    if time.time() - _last_trade_ts < COOLDOWN_SEC:
        return f"cooldown {int(COOLDOWN_SEC - (time.time() - _last_trade_ts))}s left"
    positions = mt5.positions_get(symbol=SYMBOL) or []
    my_pos = [p for p in positions if int(p.magic) == MAGIC]
    if len(my_pos) >= MAX_OPEN:
        return f"max {MAX_OPEN} open"
    total_lot = sum(float(p.volume) for p in my_pos)
    if total_lot >= MAX_LOT_TOTAL:
        return f"max lot {MAX_LOT_TOTAL}"
    return None


def execute(mt5, side: str, reason: str):
    global _last_trade_ts
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return
    if side == "BUY":
        price = tick.ask
        sl = price - SL_PTS
        tp = price + TP_PTS
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + SL_PTS
        tp = price - TP_PTS
        order_type = mt5.ORDER_TYPE_SELL

    # Record decision in unified log
    _snap = None
    try:
        import json as _json
        _snap = _json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
    except Exception: pass
    _dec_id = record_decision(
        source="claude_simple", magic=MAGIC, symbol=SYMBOL, side=side,
        entry=price, sl=sl, tp=tp, lot=LOT_PER_TRADE,
        reason=reason, snap=_snap,
    )

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": LOT_PER_TRADE, "type": order_type,
        "price": price, "sl": sl, "tp": tp,
        "deviation": 50, "magic": MAGIC,
        "comment": f"CLAUDE_SMP_{side}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    update_decision_ticket(_dec_id, int(r.order) if ok else 0,
                            error="" if ok else f"retcode {getattr(r,'retcode','?')}")
    if ok:
        _last_trade_ts = time.time()
        print(f"[{datetime.now():%H:%M:%S}] ✅ {side} #{r.order} @ {r.price:.2f} "
               f"SL {sl:.2f} TP {tp:.2f} | {reason}")
        _append(TRADE_LOG, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "side": side, "ticket": int(r.order),
            "entry": float(r.price), "sl": sl, "tp": tp,
            "reason": reason,
        })
    else:
        rc = getattr(r, "retcode", None) if r else None
        print(f"[{datetime.now():%H:%M:%S}] ❌ {side} failed: {rc}")


def main():
    if not mt5.initialize(): mt5.initialize()
    acc = mt5.account_info()
    print(f"[claude_simple_trader] ONLINE — magic {MAGIC}")
    print(f"  Balance: ${acc.balance:.2f}  Equity: ${acc.equity:.2f}")
    print(f"  Caps: max {MAX_OPEN} open, ${SL_PTS} SL/${TP_PTS} TP per trade")
    print(f"  Cooldown: {COOLDOWN_SEC}s · Daily limit: ${DAILY_LOSS_LIMIT}")

    while True:
        try:
            if not BRAIN_LIVE.exists():
                time.sleep(POLL); continue
            snap = json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
            acc = mt5.account_info()
            blocker = hard_guards(mt5, acc.equity)
            if blocker:
                time.sleep(POLL); continue
            # Orchestrator gate — respect regime decision
            if is_engine_active(MAGIC):
                time.sleep(POLL); continue
            # Circuit breaker
            global _breaker
            if _breaker is None: _breaker = CircuitBreaker(MAGIC, SYMBOL)
            if _breaker.check():
                time.sleep(POLL); continue
            side, reason = evaluate_signal(snap)
            if side:
                execute(mt5, side, reason)
                if _breaker: _breaker.mark_trade()
            time.sleep(POLL)
        except KeyboardInterrupt:
            print("[claude_simple_trader] stopped"); break
        except Exception as e:
            print(f"[claude_simple_trader] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
