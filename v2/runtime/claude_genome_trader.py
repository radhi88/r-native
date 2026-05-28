"""runtime/claude_genome_trader.py — The LIVE genome trades for real.

Born 2026-05-28 — finally connects the evolved genome system to MT5.

WHAT IT DOES:
  Every 5s, reads:
    1. brain_live.json — current market snapshot
    2. live_genome.json — the currently promoted "best" genome
  Evaluates the snapshot against the LIVE genome's parameters.
  If genome says BUY/SELL → places trade on MT5 (magic 99782).

WHY THIS IS THE MISSING LINK:
  • genome_evolver.py has been evolving genomes for hours (gen 50!)
  • genome_promoter.py auto-promotes the best to LIVE status
  • r_native_brain_link.py generates paper signals from genomes
  • palace_council.py votes on signals
  BUT — none of them actually TRADE the LIVE genome's signals.
  This trader is the bridge.

GENOME EVOLUTION CYCLE NOW WORKS END-TO-END:
  brain_v1 captures market →
  genomes evaluate vs their params →
  council votes (5/5) →
  best genome promoted to LIVE →
  THIS TRADER reads LIVE → trades on MT5 →
  performance_coordinator tracks PnL →
  evolver kills losers, breeds winners →
  promoter swaps LIVE to better genome →
  loop forever (system gets smarter)

Magic 99782 (separate from 99780 simple, 99781 smart).
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make `runtime.shared.*` importable when launched as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.shared.orchestrator_gate import is_engine_active, get_active_summary  # noqa: E402
from runtime.shared.circuit_breaker import CircuitBreaker  # noqa: E402

_breaker = None  # lazy-init after MAGIC defined

SYMBOL = "XAUUSDm"
MAGIC = 99782
BRAIN_LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
LIVE_GENOME = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\live_genome.json")
TRADE_LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_genome_trades.jsonl")
POLL = 5.0

# Risk (adapts to account size)
MAX_OPEN = 2
COOLDOWN_SEC = 90
DAILY_LOSS_PCT = 15      # 15% of balance
MIN_EQUITY_PCT = 70      # stop at 70% of starting balance
SL_PTS = 4.0             # initial; trailing_stop_manager takes over after +3pt
TP_PTS = 20.0            # FAR out — trailing handles real exit. TP = safety net only.
USE_ATR_TP = True        # if True: TP = max(TP_PTS, atr_h1 × 3)

_last_trade_ts = 0
_session_start_equity = 0


def _append(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def get_realized_today(magic: int) -> float:
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    return sum(float(d.profit) for d in deals
                if int(d.magic) == magic and int(d.entry) in (1, 2))


def evaluate_with_genome(snap: dict, genome: dict) -> tuple[str | None, float, str]:
    """Apply the evolved genome's parameters to the snapshot."""
    if not snap or not genome: return (None, 0, "no data")

    # Genome parameters
    rsi_max = genome.get("rsi_max", 60)
    min_imb = genome.get("min_imb_count", 2)
    use_fp = genome.get("use_footprint", True)
    min_pressure = genome.get("min_pressure_abs", 3)
    min_mtf = genome.get("min_mtf_agreement", 2)

    # Market state
    bias_m1 = snap.get("bias", {}).get("m1", "?")
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")
    bias_h1 = snap.get("bias", {}).get("h1", "?")
    rsi = snap.get("rsi", {}).get("m1", 50)
    pressure = snap.get("pressure_10m1", 0)
    fp = snap.get("footprint", {})

    biases = [bias_m1, bias_m5, bias_m15, bias_h1]
    up_count = biases.count("UP")
    dn_count = biases.count("DOWN")

    direction = None
    if up_count >= min_mtf: direction = "BUY"
    elif dn_count >= min_mtf: direction = "SELL"
    if not direction: return (None, 0, f"MTF: UP={up_count} DN={dn_count} (need ≥{min_mtf})")

    # RSI
    if direction == "BUY" and rsi > rsi_max:
        return (None, 0, f"RSI {rsi} > {rsi_max} for BUY")
    if direction == "SELL" and rsi < (100 - rsi_max):
        return (None, 0, f"RSI {rsi} < {100-rsi_max} for SELL")

    # Pressure
    if abs(pressure) < min_pressure:
        return (None, 0, f"|pressure {pressure:.1f}| < {min_pressure}")
    if direction == "BUY" and pressure < 0:
        return (None, 0, f"pressure {pressure:.1f} negative for BUY")
    if direction == "SELL" and pressure > 0:
        return (None, 0, f"pressure {pressure:.1f} positive for SELL")

    # Footprint imbalance
    if use_fp and fp:
        imb_buy = fp.get("imb_buy_count_3bars", 0)
        imb_sell = fp.get("imb_sell_count_3bars", 0)
        if direction == "BUY" and imb_buy < min_imb:
            return (None, 0, f"FP imb_buy {imb_buy} < {min_imb}")
        if direction == "SELL" and imb_sell < min_imb:
            return (None, 0, f"FP imb_sell {imb_sell} < {min_imb}")

    # Confidence based on alignment
    confidence = min(1.0, (up_count if direction == "BUY" else dn_count) / 4.0)
    if use_fp and fp.get("in_demand_zone" if direction == "BUY" else "in_supply_zone"):
        confidence = min(1.0, confidence + 0.2)

    return (direction, confidence,
            f"{direction} MTF{up_count if direction=='BUY' else dn_count}/4 "
            f"RSI{rsi} P{pressure:+.1f} conf{confidence:.2f}")


def hard_guards(equity: float, balance: float) -> str | None:
    global _session_start_equity
    if _session_start_equity == 0:
        _session_start_equity = equity

    if equity < balance * MIN_EQUITY_PCT / 100:
        return f"equity ${equity:.2f} < {MIN_EQUITY_PCT}% of bal (${balance * MIN_EQUITY_PCT/100:.2f})"

    realized = get_realized_today(MAGIC)
    daily_limit = -(balance * DAILY_LOSS_PCT / 100)
    if realized <= daily_limit:
        return f"realized ${realized:+.2f} ≤ daily limit ${daily_limit:.2f}"

    if time.time() - _last_trade_ts < COOLDOWN_SEC:
        return f"cooldown {int(COOLDOWN_SEC - (time.time() - _last_trade_ts))}s"

    positions = mt5.positions_get(symbol=SYMBOL) or []
    my_pos = [p for p in positions if int(p.magic) == MAGIC]
    if len(my_pos) >= MAX_OPEN:
        return f"max {MAX_OPEN} open"

    return None


def execute(side: str, genome_name: str, reason: str, confidence: float):
    global _last_trade_ts
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return

    # Adaptive lot based on equity
    acc = mt5.account_info()
    lot = 0.01 if acc.balance < 200 else 0.02 if acc.balance < 500 else 0.03

    # ATR-aware TP: prefer atr_h1 × 3, fall back to TP_PTS
    tp_dist = TP_PTS
    if USE_ATR_TP:
        try:
            import json as _json
            snap = _json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
            atr_h1 = float(snap.get("atr", {}).get("h1", 0))
            if atr_h1 > 0:
                tp_dist = max(TP_PTS, atr_h1 * 3.0)
        except Exception:
            pass
    if side == "BUY":
        price = tick.ask; sl = price - SL_PTS; tp = price + tp_dist
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid; sl = price + SL_PTS; tp = price - tp_dist
        order_type = mt5.ORDER_TYPE_SELL

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": lot, "type": order_type,
        "price": price, "sl": sl, "tp": tp,
        "deviation": 50, "magic": MAGIC,
        "comment": f"GEN_{genome_name[:8]}_{side}"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    if ok:
        _last_trade_ts = time.time()
        if _breaker: _breaker.mark_trade()
        print(f"[{datetime.now():%H:%M:%S}] 🧬 {side} #{r.order} @ {r.price:.2f} "
               f"SL {sl:.2f} TP {tp:.2f} lot {lot} | {genome_name} | {reason}")
        _append(TRADE_LOG, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "side": side, "ticket": int(r.order),
            "entry": float(r.price), "sl": sl, "tp": tp,
            "lot": lot, "genome": genome_name,
            "confidence": confidence, "reason": reason,
        })
    else:
        print(f"[{datetime.now():%H:%M:%S}] ❌ {side} failed: {getattr(r, 'retcode', None)}")


def main():
    if not mt5.initialize(): mt5.initialize()
    acc = mt5.account_info()
    print(f"╔══════════════════════════════════════════════╗")
    print(f"║ [claude_genome_trader] ONLINE                ║")
    print(f"║ The evolved genome system trades for real    ║")
    print(f"╠══════════════════════════════════════════════╣")
    print(f"║ Magic: {MAGIC}                                  ║")
    print(f"║ Balance: ${acc.balance:.2f}  Equity: ${acc.equity:.2f}     ║")
    print(f"║ SL {SL_PTS}pt · TP {TP_PTS}pt · R:R 2:1               ║")
    print(f"║ Cooldown {COOLDOWN_SEC}s · Max {MAX_OPEN} open               ║")
    print(f"║ Daily limit {DAILY_LOSS_PCT}% · Floor {MIN_EQUITY_PCT}% of balance   ║")
    print(f"╚══════════════════════════════════════════════╝")

    last_genome_check = ""
    while True:
        try:
            if not BRAIN_LIVE.exists() or not LIVE_GENOME.exists():
                time.sleep(POLL); continue
            snap = json.loads(BRAIN_LIVE.read_text(encoding="utf-8"))
            live = json.loads(LIVE_GENOME.read_text(encoding="utf-8"))
            genome = live.get("params", {})
            genome_name = live.get("name", "UNKNOWN")
            promoted_ts = live.get("promoted_ts", "")

            # Announce when LIVE genome changes
            if genome_name != last_genome_check:
                print(f"\n[{datetime.now():%H:%M:%S}] 👑 LIVE GENOME: {genome_name}")
                print(f"  promoted: {promoted_ts[:19]}")
                print(f"  params: rsi≤{genome.get('rsi_max')} imb≥{genome.get('min_imb_count')} "
                      f"lot {genome.get('lot')} mtf≥{genome.get('min_mtf_agreement')} "
                      f"FP={genome.get('use_footprint')}\n")
                last_genome_check = genome_name

            acc = mt5.account_info()
            blocker = hard_guards(acc.equity, acc.balance)
            if blocker:
                time.sleep(POLL); continue

            # Orchestrator gate — respect regime decision
            orch_block = is_engine_active(MAGIC)
            if orch_block:
                time.sleep(POLL); continue

            # Circuit breaker — prevent cascade (claude_auto-style disaster)
            global _breaker
            if _breaker is None: _breaker = CircuitBreaker(MAGIC, SYMBOL)
            cb_block = _breaker.check()
            if cb_block:
                time.sleep(POLL); continue

            side, confidence, reason = evaluate_with_genome(snap, genome)
            if side and confidence >= 0.5:
                execute(side, genome_name, reason, confidence)

            time.sleep(POLL)
        except KeyboardInterrupt:
            print("[claude_genome_trader] stopped"); break
        except Exception as e:
            print(f"[claude_genome_trader] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
