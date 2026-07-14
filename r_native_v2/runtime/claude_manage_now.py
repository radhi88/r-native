"""runtime/claude_manage_now.py — Emergency position manager.

User authorization (2026-05-27 17:51): "سو كود بايثون وتصرف للصفقات الحاليه"

Strategy: The BUY pyramid is underwater -$216 with 28 positions avg 4445.07
while price is 4438.72. BULL_OB + BULL FVG both broken. Marubozu_bear 93%
confirmed the breakdown. BUT — inverted_hammer just printed at the low,
RSI=39 in user's sweet spot, CVD extreme = potential bounce setup.

PLAN:
  1. Close 60% of HIGHEST-priced BUYs (the worst losers, lock the bad pain)
  2. Keep 40% LOWEST-priced BUYs (the recent dip buys, best avg for bounce)
  3. Set basket TP @ 4443 on remainder = breakeven escape window
  4. Set basket SL @ 4432 on remainder = max additional loss ~$80
  5. If bounce reaches 4443 = TPs hit → close all → escape with -$130 total
  6. If breakdown to 4432 = SLs hit → -$295 total → still survive at $322
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "XAUUSDm"
KEEP_RATIO = 0.40         # keep this fraction of BUYs (lowest entries)
TP_ON_KEPT = 4443.00      # breakeven escape target
SL_ON_KEPT = 4432.00      # hard floor
LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_actions.jsonl")


def _log(event: dict):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def close_position(p) -> dict:
    """Close one position at market."""
    tick = mt5.symbol_info_tick(SYMBOL)
    close_type = mt5.ORDER_TYPE_SELL if int(p.type) == 0 else mt5.ORDER_TYPE_BUY
    price = tick.bid if int(p.type) == 0 else tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": float(p.volume), "type": close_type,
        "position": int(p.ticket), "price": price,
        "deviation": 50, "magic": 99777,
        "comment": "CLAUDE_MGMT",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    if not ok:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
        ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "ticket": int(p.ticket), "ok": bool(ok),
        "entry": float(p.price_open), "exit": price,
        "lot": float(p.volume), "profit": float(p.profit),
        "retcode": getattr(r, "retcode", None) if r else None,
    }


def set_sl_tp(p, sl: float, tp: float) -> bool:
    """Modify position SL/TP."""
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   SYMBOL,
        "position": int(p.ticket),
        "sl":       sl,
        "tp":       tp,
    }
    r = mt5.order_send(req)
    return r and r.retcode == mt5.TRADE_RETCODE_DONE


def main():
    if not mt5.initialize():
        if not mt5.initialize():
            print("MT5 init failed"); return

    acc_b = mt5.account_info()
    positions = list(mt5.positions_get(symbol=SYMBOL) or [])
    buys  = [p for p in positions if int(p.type) == 0]
    sells = [p for p in positions if int(p.type) == 1]
    tick = mt5.symbol_info_tick(SYMBOL)

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"INITIAL STATE @ {datetime.now():%H:%M:%S}")
    print(f"  Balance: ${acc_b.balance:.2f}  Equity: ${acc_b.equity:.2f}")
    print(f"  Floating: ${acc_b.profit:+.2f}")
    print(f"  BUYs: {len(buys)}  SELLs: {len(sells)}")
    print(f"  Price: bid {tick.bid:.2f} ask {tick.ask:.2f}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not buys:
        print("No BUYs to manage — exit"); return

    # ── 1. Close any SELLs (we are net LONG plan, no hedges) ──
    for p in sells:
        r = close_position(p)
        print(f"  CLOSED SELL #{r['ticket']} @ {r['exit']:.2f} profit ${r['profit']:+.2f}")
        _log({"ts": datetime.now(timezone.utc).isoformat(), "action": "close_sell", **r})

    # ── 2. Sort BUYs by price_open DESCENDING (highest first = worst losers) ──
    buys_sorted = sorted(buys, key=lambda p: -float(p.price_open))
    n_total = len(buys_sorted)
    n_keep  = max(1, int(round(n_total * KEEP_RATIO)))
    n_close = n_total - n_keep

    to_close = buys_sorted[:n_close]
    to_keep  = buys_sorted[n_close:]

    keep_avg  = sum(p.price_open * p.volume for p in to_keep) / sum(p.volume for p in to_keep)
    close_avg = sum(p.price_open * p.volume for p in to_close) / sum(p.volume for p in to_close)
    print(f"PLAN: close {n_close} (avg ${close_avg:.2f})  ·  keep {n_keep} (avg ${keep_avg:.2f})")

    # ── 3. Close the high-entry BUYs ──
    closed_ok = 0
    closed_pnl = 0.0
    for p in to_close:
        r = close_position(p)
        if r["ok"]:
            closed_ok += 1
            closed_pnl += r["profit"]
            print(f"  ✓ CLOSED #{r['ticket']} {p.price_open:.2f} → {r['exit']:.2f}  P/L ${r['profit']:+.2f}")
        else:
            print(f"  ✗ FAILED #{r['ticket']} retcode={r['retcode']}")
        _log({"ts": datetime.now(timezone.utc).isoformat(), "action": "close_buy", **r})

    # ── 4. Set SL/TP on the kept BUYs ──
    time.sleep(2)
    survivors = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if int(p.type)==0]
    sltp_ok = 0
    for p in survivors:
        if set_sl_tp(p, SL_ON_KEPT, TP_ON_KEPT):
            sltp_ok += 1
        _log({"ts": datetime.now(timezone.utc).isoformat(), "action": "set_sltp",
              "ticket": int(p.ticket), "sl": SL_ON_KEPT, "tp": TP_ON_KEPT})

    # ── 5. Final report ──
    time.sleep(2)
    acc_a = mt5.account_info()
    remaining = mt5.positions_get(symbol=SYMBOL) or []
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"AFTER:")
    print(f"  Balance: ${acc_a.balance:.2f}  ({acc_a.balance - acc_b.balance:+.2f} realized)")
    print(f"  Equity:  ${acc_a.equity:.2f}")
    print(f"  Floating: ${acc_a.profit:+.2f}")
    print(f"  Positions left: {len(remaining)} (target {n_keep})")
    print(f"  SL/TP set on: {sltp_ok}/{len(survivors)}  ·  TP {TP_ON_KEPT} · SL {SL_ON_KEPT}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"EXIT SCENARIOS:")
    if remaining:
        keep_lot = sum(float(p.volume) for p in remaining)
        keep_avg = sum(float(p.price_open)*float(p.volume) for p in remaining)/keep_lot
        for tgt in (4438, 4440, 4443, 4445, 4432):
            pl = (tgt - keep_avg) * keep_lot * 100
            tot = acc_a.balance + pl
            print(f"  @ {tgt}: kept_float ${pl:+.0f}  total_balance ${tot:.0f}")

    _log({"ts": datetime.now(timezone.utc).isoformat(), "action": "summary",
          "balance_before": acc_b.balance, "balance_after": acc_a.balance,
          "realized": acc_a.balance - acc_b.balance,
          "closed_count": closed_ok, "kept_count": len(remaining)})

    mt5.shutdown()


if __name__ == "__main__":
    main()
