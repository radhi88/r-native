"""bleeder_scan.py — هل multi_trader (أو أي بوت) يخسر باستمرار على رمز أو جلسة معيّنة؟
نفس نمط btc_live (قُصَّ الخاسر الثابت) + فلتر الليل — لكن بإثبات walk-forward لا نافذة واحدة.

لكل رمز ولكل جلسة (UTC): الصافي المحقّق، نسبة الفوز، والأهم — هل هو خاسر في *معظم* الكتل
الزمنية (≥CONSISTENCY من K) أم في كتلة سيئة واحدة؟ مرشّح القصّ = خاسر ثابت + عيّنة كافية.

Run: .venv\\Scripts\\python.exe bleeder_scan.py [MAGIC] [DAYS] [K]
"""
from __future__ import annotations
import sys, json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

MT5DIR = Path(__file__).resolve().parent
# جلسات UTC (بحسب ذاكرة المشروع: الليل 22-08 سيّئ للتداول اليدوي؛ نقيس البوت بحرّية)
def session_of(hour):
    if 22 <= hour or hour < 7: return "ASIAN(22-07)"
    if 7 <= hour < 12:        return "LONDON(07-12)"
    if 12 <= hour < 16:       return "NYOVERLAP(12-16)"
    return "NYPM(16-22)"

MIN_N = 25          # أقل عيّنة للحكم على رمز/جلسة
CONSISTENCY = 4     # خاسر في ≥4 من K كتل = ثابت


def main():
    magic = int(sys.argv[1]) if len(sys.argv) > 1 else 20260608
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    K = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    mt5.initialize() or mt5.initialize()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    mt5.shutdown()
    pos = defaultdict(lambda: {"in": None, "net": 0.0})
    for x in deals:
        if x.magic != magic:
            continue
        p = pos[x.position_id]
        if x.entry == 0:
            p["in"] = x
        p["net"] += x.profit + x.commission + x.swap
    trades = [{"sym": p["in"].symbol, "t": p["in"].time, "net": p["net"]}
              for p in pos.values() if p["in"]]
    trades.sort(key=lambda r: r["t"])
    n = len(trades)
    if n < K * 5:
        print(f"too few trades ({n})"); return
    t0, t1 = trades[0]["t"], trades[-1]["t"]
    edges = np.linspace(t0, t1 + 1, K + 1)
    def block_of(t): return min(K - 1, int(np.searchsorted(edges, t, side="right") - 1))

    print(f"=== bleeder_scan magic {magic} · {n} trades · {days}d · {K} blocks ===")
    print(f"total net: {sum(r['net'] for r in trades):+.2f}\n")

    def analyze(keyfn, title):
        agg = defaultdict(lambda: {"net": 0.0, "n": 0, "w": 0, "blk": defaultdict(float)})
        for r in trades:
            k = keyfn(r); a = agg[k]
            a["net"] += r["net"]; a["n"] += 1; a["w"] += (r["net"] > 0)
            a["blk"][block_of(r["t"])] += r["net"]
        print(f"--- by {title} ---")
        cands = []
        for k, a in sorted(agg.items(), key=lambda kv: kv[1]["net"]):
            if a["n"] < MIN_N:
                tag = "(small)"
            else:
                neg_blocks = sum(1 for bi in range(K) if a["blk"].get(bi, 0.0) < 0)
                consistent = neg_blocks >= CONSISTENCY and a["net"] < 0
                tag = f"neg in {neg_blocks}/{K} blocks" + ("  🔴 CONSISTENT BLEEDER" if consistent else "")
                if consistent:
                    cands.append((k, a, neg_blocks))
            wr = a["w"] / a["n"] * 100
            print(f"  {str(k):17} n={a['n']:>4} net={a['net']:>9.2f} wr={wr:4.0f}%  {tag}")
        return cands

    sym_c = analyze(lambda r: r["sym"], "SYMBOL")
    print()
    ses_c = analyze(lambda r: session_of(datetime.fromtimestamp(r["t"], timezone.utc).hour), "SESSION")

    print("\n=== PRUNE CANDIDATES (consistent across blocks, n>=%d) ===" % MIN_N)
    if not sym_c and not ses_c:
        print("  none — no symbol/session is a consistent walk-forward bleeder. No prune justified.")
    for k, a, nb in sym_c:
        print(f"  SYMBOL {k}: net {a['net']:+.2f}, neg in {nb}/{K} blocks — candidate to gate/cut")
    for k, a, nb in ses_c:
        print(f"  SESSION {k}: net {a['net']:+.2f}, neg in {nb}/{K} blocks — candidate to gate")
    out = MT5DIR / "data" / "lab_cache" / f"bleeder_scan_{magic}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ts": now.isoformat(), "magic": magic, "days": days, "K": K, "n": n,
                               "sym_candidates": [{"k": k, "net": a["net"], "neg_blocks": nb} for k, a, nb in sym_c],
                               "ses_candidates": [{"k": k, "net": a["net"], "neg_blocks": nb} for k, a, nb in ses_c]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
