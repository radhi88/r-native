"""style_miner.py — يستخرج "أسلوب المستخدم الرابح" من صفقاته الحقيقية (magic-0)، قراءة فقط.
لا يقلّد النقرات — يجد تحت أي ظروف يكون توقّعه الرياضي موجباً (بصمة الحافّة) مقابل السالب (النزيف).

Run: .venv\\Scripts\\python.exe style_miner.py [DAYS]
"""
from __future__ import annotations
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

DOW = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def _sess(h):
    if 22 <= h or h < 7: return "ASIAN(22-07)"
    if 7 <= h < 12: return "LONDON(07-12)"
    if 12 <= h < 16: return "NYOVL(12-16)"
    return "NYPM(16-22)"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    mt5.initialize() or mt5.initialize()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    mt5.shutdown()
    net = lambda x: x.profit + x.commission + x.swap
    # pair IN/OUT by position
    pos = {}
    for x in deals:
        if x.magic != 0:
            continue
        p = pos.setdefault(x.position_id, {"in": None, "out": None, "net": 0.0})
        if x.entry == 0: p["in"] = x
        elif x.entry == 1: p["out"] = x
        p["net"] += net(x)
    trades = []
    for p in pos.values():
        if not p["in"]:
            continue
        din = p["in"]; dt = datetime.fromtimestamp(din.time, timezone.utc)
        hold = ((p["out"].time - din.time) / 60.0) if p["out"] else 0.0
        trades.append({"t": din.time, "dt": dt, "sym": din.symbol, "vol": din.volume,
                       "net": p["net"], "hour": dt.hour, "dow": dt.weekday(), "hold": hold})
    trades.sort(key=lambda r: r["t"])
    # mark "after a loss" (revenge/tilt)
    for i, r in enumerate(trades):
        r["after_loss"] = (i > 0 and trades[i - 1]["net"] < 0)
    n = len(trades)
    if n < 30:
        print(f"عيّنة صغيرة ({n})"); return
    tot = sum(r["net"] for r in trades)
    print(f"=== style_miner · magic-0 · {days}يوم · {n} صفقة · صافي {tot:+.0f} ===\n")

    def seg(keyfn, title, minn=20):
        agg = defaultdict(lambda: [0, 0.0, 0])
        for r in trades:
            k = keyfn(r)
            if k is None: continue
            a = agg[k]; a[0] += 1; a[1] += r["net"]; a[2] += (r["net"] > 0)
        print(f"--- {title} (التوقّع = صافي/صفقة) ---")
        rows = []
        for k, (cnt, s, w) in agg.items():
            if cnt < minn: continue
            rows.append((k, cnt, s / cnt, s, w / cnt * 100))
        for k, cnt, exp, s, wr in sorted(rows, key=lambda x: -x[2]):
            tag = "✅ حافّة" if exp > 0 else "🔴 نزيف"
            print(f"  {str(k):16} n={cnt:>4} توقّع={exp:>7.2f}$ صافي={s:>8.0f} فوز={wr:>3.0f}%  {tag}")
        print()

    seg(lambda r: _sess(r["hour"]), "حسب الجلسة")
    seg(lambda r: ("≤0.05" if r["vol"] <= 0.05 else "0.05-0.2" if r["vol"] <= 0.2 else "0.2-1" if r["vol"] <= 1 else ">1"), "حسب حجم اللوت")
    seg(lambda r: DOW[r["dow"]] if r["dow"] < 7 else None, "حسب يوم الأسبوع")
    seg(lambda r: ("<5د" if r["hold"] < 5 else "5-30د" if r["hold"] < 30 else "30-120د" if r["hold"] < 120 else ">120د") if r["hold"] > 0 else None, "حسب مدة الاحتفاظ")
    seg(lambda r: ("بعد خسارة (انتقام؟)" if r["after_loss"] else "بعد ربح/بداية"), "حسب الحالة النفسية", minn=30)
    seg(lambda r: r["sym"], "حسب الرمز", minn=25)

    # البصمة الرابحة المُركّبة: جلسة نهارية + لوت صغير
    edge = [r for r in trades if not (22 <= r["hour"] or r["hour"] < 7) and r["vol"] <= 0.2]
    bleed = [r for r in trades if (22 <= r["hour"] or r["hour"] < 7) or r["vol"] > 0.2]
    def stat(g):
        return (len(g), sum(x["net"] for x in g), (sum(x["net"] for x in g)/len(g) if g else 0))
    en, es, ee = stat(edge); bn, bs, be = stat(bleed)
    print("=== البصمة المُركّبة ===")
    print(f"  ✅ حافّتك (نهار + لوت ≤0.2): n={en} صافي={es:+.0f} توقّع={ee:+.2f}$/صفقة")
    print(f"  🔴 نزيفك (ليل أو لوت >0.2):  n={bn} صافي={bs:+.0f} توقّع={be:+.2f}$/صفقة")
    print(f"\n  لو تداولتَ حافّتك فقط: تقريباً {es:+.0f}$ بدل {tot:+.0f}$ الفعلي.")


if __name__ == "__main__":
    main()
