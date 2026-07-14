"""truth_tracker.py — the honest scoreboard: are we ACTUALLY making money?

The user asked "ما اشوف تقدم بالربح؟". Features don't equal profit. This loop records the REAL
per-source live P&L (today + 7d) + account equity over time, so "re-evaluate later" is data-driven,
not vibes. The dashboard reads pnl_scoreboard.json and shows it FIRST — no sugar-coating.

Read-only on MT5. Windowless. Run:  python truth_tracker.py --loop
"""
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(r"C:\Users\Radhi\MT5\data\r_native\pnl_scoreboard.json")
HIST = Path(r"C:\Users\Radhi\MT5\data\r_native\pnl_history.json")
INTERVAL = 600
MAGIC_MULTI = 20260608
NAMES = {0: "يدوي (أنت)", 20260611: "صياد القفزات", 20260612: "بطولة التوائم", 20260613: "🧬 الهجائن", 20260614: "جين الأخبار 🪜", 20260616: "ORB 🎯", 20260608: "multi_trader", 99782: "unified ذهب", 99791: "gold_live",
         99790: "stacker", 20260600: "EA", 20260605: "r_exec", 99784: "إشارة", 99792: "99792"}


def _by_source(mt5, hours):
    a = int(time.time() - hours * 3600)
    deals = [d for d in (mt5.history_deals_get(a, int(time.time())) or []) if d.entry == 1]
    by = {}
    for d in deals:
        t = by.setdefault(d.magic, [0, 0.0, 0])
        t[0] += 1; t[1] += d.profit + d.commission + d.swap; t[2] += 1 if d.profit > 0 else 0
    rows = [{"name": NAMES.get(m, str(m)), "magic": m, "n": n, "net": round(net, 2),
             "win": round(w / n * 100) if n else 0} for m, (n, net, w) in by.items()]
    rows.sort(key=lambda r: r["net"])
    return rows, round(sum(r["net"] for r in rows), 2)


def snapshot(mt5) -> dict:
    acct = mt5.account_info()
    d1, t1 = _by_source(mt5, 24)
    d7, t7 = _by_source(mt5, 168)
    # per-symbol live net for OUR bot
    a = int(time.time() - 168 * 3600)
    bysym = {}
    for d in (mt5.history_deals_get(a, int(time.time())) or []):
        if d.entry == 1 and d.magic == MAGIC_MULTI:
            t = bysym.setdefault(d.symbol, [0, 0.0]); t[0] += 1; t[1] += d.profit + d.commission + d.swap
    syms = sorted([{"sym": s, "n": n, "net": round(net, 2)} for s, (n, net) in bysym.items()],
                  key=lambda x: x["net"])
    eq = round(acct.equity, 2) if acct else 0.0
    verdict = "نازل 🔴" if t1 < -1 else "صاعد 🟢" if t1 > 1 else "متعادل ⚪"
    out = {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
           "balance": round(acct.balance, 2) if acct else 0, "equity": eq,
           "floating": round((acct.equity - acct.balance), 2) if acct else 0,
           "today_net": t1, "today_src": d1[:8], "d7_net": t7, "d7_src": d7[:10],
           "bot_worst": syms[:5], "bot_best": syms[::-1][:5], "verdict": verdict}
    # append an equity point (throttled to once per ~30min via history dedupe)
    try:
        h = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {"curve": []}
    except Exception:
        h = {"curve": []}
    cur = h.get("curve", [])
    if not cur or time.time() - cur[-1][0] > 1800:
        cur.append([round(time.time()), eq]); h["curve"] = cur[-200:]
        try: HIST.write_text(json.dumps(h), encoding="utf-8")
        except Exception: pass
    out["equity_curve"] = [p[1] for p in h.get("curve", [])][-60:]
    return out


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        while True:
            try:
                o = snapshot(mt5)
                OUT.parent.mkdir(parents=True, exist_ok=True)
                tmp = OUT.with_suffix(".json.tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
                import os; os.replace(tmp, OUT)
                print(f"[TRUTH] equity ${o['equity']} · اليوم ${o['today_net']} · 7أيام ${o['d7_net']} · {o['verdict']}", flush=True)
            except Exception as e:
                print(f"[TRUTH] err {e}", flush=True)
            if not a.loop:
                break
            time.sleep(INTERVAL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
