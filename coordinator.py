"""coordinator.py — ONE shared agreement every gold bot must obey.

The lesson of magic 99790 (-$2156, twice): independent bots that don't talk to each other
over-leverage and blow the account. This is the single contract they all sign:

  • ONE agreed DIRECTION (from the live chart read) — no bot may trade against it.
  • a SHARED EXPOSURE CAP across ALL magics (total lots + total positions on gold).
  • a SHARED RISK FLOOR — realized P&L since the coordinator epoch, summed across ALL
    magics; if it breaches the floor, the coordinator HALTS everyone (writes scalp_halt.flag).

Bots call coordinator.gate(side, add_lots) before entering and obey the verdict.
The coordinator loop keeps coord_state.json fresh.

Run:  python coordinator.py --loop        (--reset to start a fresh epoch + clear halt)
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path

GOLD = "XAUUSDm"
STATE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\coord_state.json")
EPOCH = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\coord_epoch.json")
HALT_FLAG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_halt.flag")
MAX_TOTAL_LOTS = 0.30     # across ALL magics on gold (tiny account) — the REAL exposure bound
MAX_TOTAL_POS = 10        # allow conviction pyramiding; total LOTS above is the hard cap
SHARED_FLOOR_PCT = 15.0   # realized since epoch (ALL magics) <= -15% equity -> HALT everyone
POLL = 4


def _epoch():
    try:
        return int(json.loads(EPOCH.read_text(encoding="utf-8"))["ts"])
    except Exception:
        ts = int(time.time())
        EPOCH.parent.mkdir(parents=True, exist_ok=True)
        EPOCH.write_text(json.dumps({"ts": ts}), encoding="utf-8")
        return ts


def gate(side, add_lots=0.0):
    """Any bot calls this before entering. side = +1 (buy) / -1 (sell). Returns (ok, reason)."""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return True, "no-coord"
    # 🕒 طزاجة: لو حالة المنسّق بايتة (>90ث) فالكاتب غالباً مات — fail-safe: امنع الدخول الجديد
    # بدل احترام halt/agreed_dir مجمّدين (وإلا قد يتجاوز بوت الأرضية المشتركة %15). الحارس يعيده ~60ث.
    if time.time() - float(st.get("updated", 0)) > 90:
        return False, "coord state stale (>90s) — fail-safe block"
    if st.get("halt"):
        return False, "coordinator HALT (" + str(st.get("reason", "")) + ")"
    ad = st.get("agreed_dir")
    if ad and side != ad:
        return False, f"against agreed dir {ad}"
    if st.get("total_positions", 0) >= MAX_TOTAL_POS:
        return False, f"shared pos cap {MAX_TOTAL_POS}"
    if st.get("total_lots", 0.0) + add_lots > MAX_TOTAL_LOTS + 1e-9:
        return False, f"shared lot cap {MAX_TOTAL_LOTS}"
    return True, "ok"


def cycle(mt5):
    import chart_read as cr
    ep = _epoch()
    acct = mt5.account_info()
    pos = list(mt5.positions_get(symbol=GOLD) or [])
    total_lots = round(sum(p.volume for p in pos), 2)
    total_pos = len(pos)
    cread = cr.read_local(mt5, GOLD, "M1") or {}
    agreed = cread.get("dir")
    deals = mt5.history_deals_get(int(ep), int(time.time())) or []
    realized = round(sum(d.profit + d.commission + d.swap for d in deals if d.entry == 1), 2)
    halt = False; reason = ""
    if acct and realized <= -SHARED_FLOOR_PCT / 100.0 * acct.equity:
        halt = True; reason = f"shared floor: realized {realized} <= -{SHARED_FLOOR_PCT}% eq"
        HALT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        if not HALT_FLAG.exists():
            HALT_FLAG.write_text(json.dumps({"reason": reason, "ts": int(time.time())}), encoding="utf-8")
    st = {"agreed_dir": agreed, "regime": cread.get("regime"), "confluence": cread.get("confluence"),
          "total_lots": total_lots, "total_positions": total_pos,
          "equity": acct.equity if acct else None, "realized_since_epoch": realized,
          "epoch": ep, "halt": halt, "reason": reason, "updated": int(time.time())}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args(argv)
    if a.reset:
        for f in (EPOCH, HALT_FLAG):
            try: f.unlink()
            except Exception: pass
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    ep = _epoch()
    print(f"[COORD] shared agreement live — caps lots<={MAX_TOTAL_LOTS} pos<={MAX_TOTAL_POS}, "
          f"shared floor {SHARED_FLOOR_PCT}%, epoch {ep}. All bots obey gate().", flush=True)
    try:
        while True:
            try:
                st = cycle(mt5)
                print(f"[COORD] dir {st['agreed_dir']} regime {st['regime']} conf {st['confluence']} | "
                      f"lots {st['total_lots']} pos {st['total_positions']} | realized {st['realized_since_epoch']} | "
                      f"{'HALT ' + st['reason'] if st['halt'] else 'OK'}", flush=True)
            except Exception as e:
                print(f"[COORD] ERROR {e}", flush=True)
            if not a.loop or a.once: break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
