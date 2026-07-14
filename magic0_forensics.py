"""magic0_forensics.py — تشريح صادق (قراءة فقط) لنزيف magic-0 (إكسبيرت/يدوي الذهب) كي يقرّر المستخدم.
لا يلمس أي صفقة — history_deals_get فقط. يجيب: متى يخسر؟ بأي حجم؟ EA أم يدوي؟ ما الكارثة؟

Run: .venv\\Scripts\\python.exe magic0_forensics.py [DAYS]
"""
from __future__ import annotations
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

REASON = {0: "CLIENT(يدوي)", 1: "MOBILE(يدوي)", 2: "WEB(يدوي)", 3: "EXPERT(EA)",
          4: "SL", 5: "TP", 6: "STOPOUT", 7: "ROLLOVER", 8: "VMARGIN", 9: "SPLIT"}


def _sess(h):
    if 22 <= h or h < 7: return "ASIAN(22-07)"
    if 7 <= h < 12: return "LONDON(07-12)"
    if 12 <= h < 16: return "NYOVL(12-16)"
    return "NYPM(16-22)"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    mt5.initialize() or mt5.initialize()
    now = datetime.now(timezone.utc)
    deals = [x for x in (mt5.history_deals_get(now - timedelta(days=days), now) or [])
             if x.magic == 0 and x.entry == 1]   # OUT = realized
    if not deals:
        print("no magic-0 closed deals"); mt5.shutdown(); return
    net = lambda x: x.profit + x.commission + x.swap
    tot = sum(net(x) for x in deals)
    print(f"=== magic-0 forensics · {days}d · {len(deals)} closed deals · NET {tot:+.0f} ===\n")

    # 1) EA vs manual (by OPEN reason — need the IN deal's reason). Use position open reason via the OUT deal's reason is exit reason;
    #    better: group by the OUT deal reason to see SL/TP/manual-close, AND pull IN reasons.
    ins = {x.position_id: x for x in (mt5.history_deals_get(now - timedelta(days=days), now) or [])
           if x.magic == 0 and x.entry == 0}
    by_openreason = defaultdict(lambda: [0, 0.0, 0])
    for x in deals:
        r = ins[x.position_id].reason if x.position_id in ins else x.reason
        b = by_openreason[r]; b[0] += 1; b[1] += net(x); b[2] += (net(x) > 0)
    print("بحسب سبب الفتح (EA مقابل يدوي):")
    for r, (n, pl, w) in sorted(by_openreason.items(), key=lambda kv: kv[1][1]):
        print(f"  {REASON.get(r, r):14} n={n:>4} net={pl:>9.0f} wr={w/n*100:3.0f}%")

    # 2) by exit reason (how positions close)
    by_exit = defaultdict(lambda: [0, 0.0])
    for x in deals:
        b = by_exit[x.reason]; b[0] += 1; b[1] += net(x)
    print("\nبحسب سبب الإغلاق:")
    for r, (n, pl) in sorted(by_exit.items(), key=lambda kv: kv[1][1]):
        print(f"  {REASON.get(r, r):14} n={n:>4} net={pl:>9.0f}")

    # 3) by session + hour
    by_sess = defaultdict(lambda: [0, 0.0, 0])
    by_hour = defaultdict(float)
    for x in deals:
        h = datetime.fromtimestamp(x.time, timezone.utc).hour
        s = by_sess[_sess(h)]; s[0] += 1; s[1] += net(x); s[2] += (net(x) > 0)
        by_hour[h] += net(x)
    print("\nبحسب الجلسة:")
    for k, (n, pl, w) in sorted(by_sess.items(), key=lambda kv: kv[1][1]):
        print(f"  {k:14} n={n:>4} net={pl:>9.0f} wr={w/n*100:3.0f}%")
    worst_h = sorted(by_hour.items(), key=lambda kv: kv[1])[:5]
    print("  أسوأ 5 ساعات UTC:", [(h, round(v)) for h, v in worst_h])

    # 4) by lot size bucket (martingale check)
    by_lot = defaultdict(lambda: [0, 0.0])
    for x in deals:
        v = x.volume
        b = "min<=0.05" if v <= 0.05 else ("0.05-0.2" if v <= 0.2 else ("0.2-1" if v <= 1 else ">1"))
        t = by_lot[b]; t[0] += 1; t[1] += net(x)
    print("\nبحسب حجم اللوت:")
    for k in ["min<=0.05", "0.05-0.2", "0.2-1", ">1"]:
        if k in by_lot:
            n, pl = by_lot[k]; print(f"  {k:10} n={n:>4} net={pl:>9.0f}")

    # 5) worst single day forensic
    by_day = defaultdict(lambda: [0, 0.0])
    for x in deals:
        d = datetime.fromtimestamp(x.time, timezone.utc).strftime("%m-%d")
        t = by_day[d]; t[0] += 1; t[1] += net(x)
    worst_day = min(by_day.items(), key=lambda kv: kv[1][1])
    print(f"\nأسوأ يوم: {worst_day[0]} net={worst_day[1][1]:+.0f} ({worst_day[1][0]} صفقة)")
    wd = worst_day[0]
    dd = [x for x in deals if datetime.fromtimestamp(x.time, timezone.utc).strftime("%m-%d") == wd]
    biggest = sorted(dd, key=net)[:5]
    print("  أكبر 5 خسائر ذلك اليوم:")
    for x in biggest:
        t = datetime.fromtimestamp(x.time, timezone.utc)
        print(f"    {t:%H:%M} {x.symbol} vol={x.volume} net={net(x):+.0f}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
