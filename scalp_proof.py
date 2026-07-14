"""scalp_proof.py — the HONEST proving gate for the gold scalper (magic 99791).

Before ANY real money goes in, the scalper must PROVE positive expectancy NET of
spread + commission on the demo, over a meaningful sample. This reads the real closed
deals from MT5 history (not estimates), computes net P&L, win-rate, profit factor and
per-trade expectancy, and prints a clear PASS/FAIL against a real-money gate.

It also acts as a capital GUARD: if the scalper's realized net for the day drops below a
hard floor, it writes a halt flag (gold_live reads it and flattens + stops).

Run:  python scalp_proof.py --loop        (guard + proof, every 20s)
      python scalp_proof.py --once         (one tally)
"""
from __future__ import annotations
import argparse, json, time, datetime
from pathlib import Path

MAGIC = 99791
HALT = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_halt.flag")
OUT  = Path(r"C:\Users\Radhi\MT5\scalp_proof.json")

# real-money gate (must clear ALL on the demo first)
GATE_TRADES = 50      # minimum closed scalps
GATE_PF     = 1.20    # profit factor net of costs
GATE_NET    = 0.0     # net must be positive
# capital guard
DAY_FLOOR_PCT = 3.0   # if today's realized net <= -3% equity -> HALT the scalper


def tally(mt5, since_ts):
    deals = mt5.history_deals_get(since_ts, int(time.time())) or []
    out = [d for d in deals if d.magic == MAGIC and d.entry == 1]   # entry==1 => closing deals (realized)
    n = len(out)
    net = sum(d.profit + d.commission + d.swap for d in out)
    wins = [d for d in out if (d.profit + d.commission + d.swap) > 0]
    losses = [d for d in out if (d.profit + d.commission + d.swap) < 0]
    gross_w = sum(d.profit + d.commission + d.swap for d in wins)
    gross_l = -sum(d.profit + d.commission + d.swap for d in losses)
    pf = (gross_w / gross_l) if gross_l > 0 else (gross_w if gross_w > 0 else 0.0)
    wr = (len(wins) / n * 100.0) if n else 0.0
    exp = (net / n) if n else 0.0
    return {"trades": n, "net": round(net, 2), "wr": round(wr, 1), "pf": round(pf, 2),
            "expectancy": round(exp, 4), "gross_win": round(gross_w, 2), "gross_loss": round(gross_l, 2)}


def gate(t):
    ok = (t["trades"] >= GATE_TRADES and t["pf"] >= GATE_PF and t["net"] > GATE_NET)
    return ok


def cycle(mt5):
    acct = mt5.account_info()
    day0 = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day = tally(mt5, int(day0.timestamp()))
    allt = tally(mt5, int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)).timestamp()))
    passed = gate(allt)
    rec = {"ts": int(time.time()), "today": day, "last14d": allt,
           "real_money_gate": {"pass": passed, "need": f">={GATE_TRADES} trades, PF>={GATE_PF}, net>0",
                               "status": "READY for real money" if passed else "NOT READY — keep proving on demo"}}
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    # NOTE: the shared capital HALT is now owned by coordinator.py (across ALL magics).
    # scalp_proof only reports the real-money proving gate; it no longer halts on its own.
    # proof line (surfaced by monitor)
    print(f"[PROOF] all:{allt['trades']}tr net {allt['net']} WR {allt['wr']}% PF {allt['pf']} exp {allt['expectancy']} | "
          f"today net {day['net']} | gate:{'PASS' if passed else 'FAIL'}", flush=True)
    return rec


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=20)
    a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        while True:
            try: cycle(mt5)
            except Exception as e: print(f"[PROOF] ERROR {e}", flush=True)
            if not a.loop or a.once: break
            time.sleep(a.interval)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
