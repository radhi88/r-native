"""straddle3627_edge_search.py — بحث عن ميزة حقيقية: نفس استراتيجية البوت عبر
(رمز × فريم) متعدّد. ذهب M1 خسر لأن السبريد يلتهم الحركة الصغيرة؛ هنا نختبر فريمات
أعلى وأصول متّرندة حيث السبريد نسبة ضئيلة. يحفظ في straddle3627.db (جدول edge_search)
ويرتّب حسب PF (>1 = ميزة حقيقية). يعيد استخدام simulate من المختبر.

Run:  python straddle3627_edge_search.py
"""
import json, time, sqlite3
from pathlib import Path
import bisect
import MetaTrader5 as mt5
from straddle3627_lab import ema, simulate

DB = Path(r"C:\Users\Radhi\MT5\data\r_native\straddle3627.db")

SYMBOLS = ["XAUUSDm", "US30m", "USTECm", "BTCUSDm", "USOILm", "JP225m", "ETHUSDm"]
# (base_tf, trend_tf, اسم)
TFS = [("M5", "M15"), ("M15", "H1"), ("H1", "H4")]
TFMAP = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
         "H4": mt5.TIMEFRAME_H4}
TFSECS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
NBARS = 6000

# جينات متّرندة قوية (دع الرابح يجري بعيداً)
GENES = {
    "G_run": dict(step_atr=0.8, candle_need=2, candle_body_dom=0.40, trail_tight_mult=1.0,
                  trail_wide_mult=3.5, conv_hold=0.6, max_legs=3, ladder_first=0.25,
                  ladder_spacing=0.55, smc_counter_legs=1, use_smc=False, let_winners_run=True),
    "G_strict": dict(step_atr=1.0, candle_need=3, candle_body_dom=0.45, trail_tight_mult=1.0,
                     trail_wide_mult=3.5, conv_hold=0.6, max_legs=1, ladder_first=0.25,
                     ladder_spacing=0.55, smc_counter_legs=1, use_smc=False, let_winners_run=True),
    "G_widerun": dict(step_atr=1.2, candle_need=2, candle_body_dom=0.40, trail_tight_mult=1.0,
                      trail_wide_mult=5.0, conv_hold=0.5, max_legs=3, ladder_first=0.25,
                      ladder_spacing=0.55, smc_counter_legs=1, use_smc=False, let_winners_run=True),
}


def build_F(sym, base, trend, spread_price):
    bt = TFMAP[base]; tt = TFMAP[trend]
    rb = mt5.copy_rates_from_pos(sym, bt, 0, NBARS)
    rt = mt5.copy_rates_from_pos(sym, tt, 0, NBARS)
    if rb is None or rt is None or len(rb) < 200 or len(rt) < 60:
        return None, spread_price
    n = len(rb)
    o = [b["open"] for b in rb]; h = [b["high"] for b in rb]
    lo = [b["low"] for b in rb]; c = [b["close"] for b in rb]; tm = [b["time"] for b in rb]
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, n)]
    atr = [0.0] * n; s = 0.0
    for i in range(n):
        s += tr[i] - (tr[i - 14] if i >= 14 else 0)
        atr[i] = s / 14 if i >= 13 else (sum(tr[:i + 1]) / (i + 1))
    cd = [1 if c[i] > o[i] else -1 if c[i] < o[i] else 0 for i in range(n)]
    bd = [abs(c[i] - o[i]) / ((h[i] - lo[i]) or 1e-9) for i in range(n)]
    # ترند من الفريم الأعلى
    ct = [b["close"] for b in rt]; ttime = [b["time"] for b in rt]
    ef = ema(ct, 8); es = ema(ct, 21)
    trt = [rt[0]["high"] - rt[0]["low"]] + [max(rt[i]["high"] - rt[i]["low"],
           abs(rt[i]["high"] - rt[i - 1]["close"]), abs(rt[i]["low"] - rt[i - 1]["close"])) for i in range(1, len(rt))]
    at = []; st = 0.0
    for i in range(len(rt)):
        st += trt[i] - (trt[i - 14] if i >= 14 else 0)
        at.append(st / 14 if i >= 13 else 1.0)
    tend = [x + TFSECS[trend] for x in ttime]
    tdir = [0] * n; tstr = [0.0] * n
    for i in range(n):
        j = bisect.bisect_right(tend, tm[i]) - 1
        if j >= 0:
            gap = ef[j] - es[j]; a = at[j] or 1.0
            tdir[i] = 1 if gap > 0 else -1 if gap < 0 else 0
            tstr[i] = abs(gap) / a
    F = dict(n=n, o=o, h=h, lo=lo, c=c, atr=atr, cd=cd, bd=bd, tdir=tdir, tstr=tstr, smc=[0] * n)
    return F, spread_price


def main():
    mt5.initialize()
    con = sqlite3.connect(str(DB), timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS edge_search(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, base_tf TEXT, trend_tf TEXT,
        gene TEXT, trades INTEGER, net_price REAL, net_usd REAL, wr REAL, pf REAL, maxdd_price REAL)""")
    con.execute("DELETE FROM edge_search")
    import straddle3627_lab as lab
    results = []
    for sym in SYMBOLS:
        info = mt5.symbol_info(sym)
        if not info:
            continue
        if not info.visible:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
        t = mt5.symbol_info_tick(sym)
        spread_price = (t.ask - t.bid) if t else info.spread * info.point
        # $ لكل 1.0 حركة سعر على vol_min
        usd_per_price = (info.trade_tick_value / info.trade_tick_size) * info.volume_min if info.trade_tick_size else info.volume_min
        for base, trend in TFS:
            lab.SPREAD = spread_price          # المختبر يستخدم متغيّر عام للسبريد
            F, sp = build_F(sym, base, trend, spread_price)
            if F is None:
                continue
            for gname, g in GENES.items():
                m = simulate(F, g)
                net_usd = round(m["net"] * usd_per_price, 2)   # m['net'] بوحدات السعر×lot؟ راجع أدناه
                con.execute("INSERT INTO edge_search(ts,symbol,base_tf,trend_tf,gene,trades,net_price,net_usd,wr,pf,maxdd_price) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (time.time(), sym, base, trend, gname, m["trades"], m["net"], net_usd, m["wr"], m["pf"], m["maxdd"]))
                results.append((m["pf"], m["net"], net_usd, m["wr"], m["trades"], sym, base, trend, gname))
    con.commit()
    mt5.shutdown()
    # الترتيب حسب PF (الميزة الحقيقية) ثم net
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    print(f"\n═══ بحث الميزة: {len(results)} اختبار (رمز×فريم×جين) ═══")
    print(f"{'رمز':<9}{'فريم':>6}{'ترند':>6}{'جين':>10}{'صفقات':>7}{'PF':>6}{'ربح٪':>6}{'صافي$':>10}")
    print("── أفضل 15 (PF أعلى = ميزة حقيقية لو PF>1) ──")
    for pf, net, usd, wr, nt, sym, base, trend, gn in results[:15]:
        mark = " 🟢ميزة" if pf > 1.05 else (" ~حدّي" if pf >= 0.98 else "")
        print(f"{sym:<9}{base:>6}{trend:>6}{gn:>10}{nt:>7}{pf:>6}{wr:>6.0f}{usd:>10.2f}{mark}")
    winners = [r for r in results if r[0] > 1.05 and r[4] >= 15]
    print(f"\n🏆 جينات/أصول ذات ميزة (PF>1.05 و≥15 صفقة): {len(winners)}")
    for pf, net, usd, wr, nt, sym, base, trend, gn in winners[:10]:
        print(f"   {sym} {base}(ترند {trend}) {gn}: PF {pf} · ربح {wr:.0f}% · {nt} صفقة · ${usd:+.2f}")
    if not winners:
        print("   لا ميزة واضحة بعد — جرّب فريمات أعلى/جلسات/جينات أخرى.")


if __name__ == "__main__":
    raise SystemExit(main())
