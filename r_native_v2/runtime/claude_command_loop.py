"""runtime/claude_command_loop.py — I am the captain now.

User authorization (2026-05-27 17:54): "انا ما راح المس الشارت انت القائد الحين"
"I won't touch the chart. You're the leader now."

This loop manages the existing 11 BUYs at avg 4442.24 autonomously until they
exit (TP/SL hit or emergency close). Logs every decision.

LIVE STATE WHEN TAKING COMMAND:
  Balance: $482.66 (realized -$197 already this swing)
  Equity:  $402 (floating -$80)
  Position: 11 BUYs · avg 4442.24 · lot 0.15
  Current TP: 4443.20 · SL: 4432.00

MY RULES AS CAPTAIN:
  Trail SL up as price moves favorably (protect profits):
    Price ≥ 4440.00 → SL = max(SL, 4434.00)
    Price ≥ 4442.00 → SL = max(SL, 4438.50)  ← breakeven approach
    Price ≥ 4443.00 → SL = max(SL, 4441.00)  ← lock +$0
  Emergency close (full exit) if ANY of:
    • marubozu_bear body≥70% close<4436 vol>150%
    • Price <4434 (early SL trigger, save the dust)
    • Equity drops below $370 (≈ -$110 from entry)
  Otherwise: let the TP=4443.20 fire naturally.
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "XAUUSDm"
POLL = 3.0
LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_actions.jsonl")
LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")

TRAIL_LEVELS = [
    (4440.00, 4434.00),   # if price ≥ 4440, SL→4434
    (4442.00, 4438.50),   # if price ≥ 4442, SL→4438.50
    (4443.00, 4441.00),   # if price ≥ 4443, SL→4441 (lock breakeven+)
]
EMERGENCY_SL_PRICE = 4434.0
EMERGENCY_EQUITY_FLOOR = 370.0
HARD_TP = 4443.20


def _log(event):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _modify(p, sl, tp):
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   SYMBOL,
        "position": int(p.ticket),
        "sl":       sl, "tp": tp,
    }
    r = mt5.order_send(req)
    return r and r.retcode == mt5.TRADE_RETCODE_DONE


def _close(p, reason=""):
    tick = mt5.symbol_info_tick(SYMBOL)
    close_type = mt5.ORDER_TYPE_SELL if int(p.type)==0 else mt5.ORDER_TYPE_BUY
    price = tick.bid if int(p.type)==0 else tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": float(p.volume), "type": close_type,
        "position": int(p.ticket), "price": price,
        "deviation": 50, "magic": 99777,
        "comment": f"CLAUDE_{reason}"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    if not ok:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
        ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    return ok, getattr(r, "retcode", None) if r else None


def emergency_close_all(buys, reason):
    closed = 0
    for p in buys:
        ok, _ = _close(p, reason)
        if ok: closed += 1
        _log({"ts": datetime.now(timezone.utc).isoformat(),
              "action": "emergency_close", "reason": reason,
              "ticket": int(p.ticket), "ok": ok})
    return closed


def _load_snap():
    if not LIVE.exists(): return {}
    try: return json.loads(LIVE.read_text(encoding="utf-8"))
    except: return {}


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("MT5 init failed"); return

    print(f"[claude_captain] ONLINE · {datetime.now():%H:%M:%S}")
    print(f"[claude_captain] managing 11 BUYs, TP={HARD_TP}, SL trail enabled")
    print(f"[claude_captain] emergency stops: price<{EMERGENCY_SL_PRICE} or equity<${EMERGENCY_EQUITY_FLOOR}")
    _log({"ts": datetime.now(timezone.utc).isoformat(),
          "action": "captain_online",
          "tp": HARD_TP, "emergency_floor": EMERGENCY_EQUITY_FLOOR})

    while True:
        try:
            buys = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if int(p.type)==0]
            buys = [p for p in buys if int(p.magic) != 20260605]   # ignore Algory trades
            if not buys:
                print(f"[claude_captain] no BUYs left — mission complete @ {datetime.now():%H:%M:%S}")
                acc = mt5.account_info()
                if acc:
                    print(f"[claude_captain] final balance ${acc.balance:.2f} equity ${acc.equity:.2f}")
                    _log({"ts": datetime.now(timezone.utc).isoformat(),
                          "action": "mission_complete",
                          "balance": acc.balance, "equity": acc.equity})
                break

            tick = mt5.symbol_info_tick(SYMBOL)
            acc = mt5.account_info()
            mid = (tick.bid + tick.ask) / 2

            # Emergency 1 — equity floor breach
            if acc.equity < EMERGENCY_EQUITY_FLOOR:
                msg = f"equity_breach_${acc.equity:.0f}"
                print(f"[claude_captain] 🆘 EMERGENCY: equity ${acc.equity:.2f} < ${EMERGENCY_EQUITY_FLOOR}")
                n = emergency_close_all(buys, msg)
                print(f"[claude_captain] closed {n}/{len(buys)} positions emergency")
                continue

            # Emergency 2 — price below hard floor
            if tick.bid < EMERGENCY_SL_PRICE:
                msg = f"price_floor_{tick.bid:.2f}"
                print(f"[claude_captain] 🆘 EMERGENCY: price {tick.bid:.2f} < ${EMERGENCY_SL_PRICE}")
                n = emergency_close_all(buys, msg)
                continue

            # Emergency 3 — pulse signal (marubozu bear with vol spike)
            snap = _load_snap()
            if snap:
                bars = snap.get("m1_last5", [])
                if bars:
                    last = bars[-1]
                    if (last.get("kind") == "marubozu_bear"
                        and last.get("body_pct", 0) >= 70
                        and last["c"] < 4436
                        and last.get("v", 0) > 750):   # ~150% of ~500 average
                        msg = f"mara_bear_v{last['v']}"
                        print(f"[claude_captain] 🆘 EMERGENCY: marubozu_bear vol spike close ${last['c']}")
                        n = emergency_close_all(buys, msg)
                        continue

            # Trail SL up as price moves favorably
            for trigger, new_sl in TRAIL_LEVELS:
                if mid >= trigger:
                    # Update SL on each position that needs it
                    for p in buys:
                        if float(p.sl) < new_sl - 0.001:
                            ok = _modify(p, new_sl, HARD_TP)
                            if ok:
                                _log({"ts": datetime.now(timezone.utc).isoformat(),
                                      "action": "trail_sl",
                                      "ticket": int(p.ticket),
                                      "old_sl": float(p.sl), "new_sl": new_sl,
                                      "trigger_price": trigger, "mid": mid})
                                print(f"[{datetime.now():%H:%M:%S}] ⬆ trailed SL #{p.ticket} {p.sl:.2f}→{new_sl:.2f}")

            time.sleep(POLL)

        except KeyboardInterrupt:
            print("[claude_captain] STOP requested"); break
        except Exception as e:
            print(f"[claude_captain] err: {e}")
            time.sleep(POLL)

    mt5.shutdown()


if __name__ == "__main__":
    main()
