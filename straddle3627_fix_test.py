"""straddle3627_fix_test.py — اختبار الإصلاحات على الذهب قبل إعادة الإطلاق.

يجيب: هل فلتر الجلسة و/أو فريم أعلى يجعل ذهب straddle3627 متيناً رابحاً؟
يختبر XAUUSDm على M1/M5/M15 × جينات × جلسات، مع تقسيم خارج-العيّنة (OOS).
لا نعيد الإطلاق إلا لو ظهر إعداد PF>1 في نصفي البيانات.

Run:  python straddle3627_fix_test.py
"""
import datetime, bisect
import MetaTrader5 as mt5
from straddle3627_lab import ema, simulate
import straddle3627_lab as lab

SYM = "XAUUSDm"
TFMAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
         "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
TFSEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
NB = 12000

# فريم أساس → فريم ترند
PAIRS = [("M1", "M5"), ("M5", "M15"), ("M15", "H1")]

SESSIONS = {
    "كل الساعات": None,
    "NY-overlap(12-21)": list(range(12, 21)),
    "نهار(8-22)": list(range(8, 22)),
    "نشط(13-20)": list(range(13, 20)),
}

GENES = {
    "run": dict(step_atr=0.8, candle_need=2, candle_body_dom=0.40, trail_tight_mult=1.0,
                trail_wide_mult=3.5, conv_hold=0.6, max_legs=3, ladder_first=0.25,
                ladder_spacing=0.55, smc_counter_legs=1, use_smc=False, let_winners_run=True),
    "strict": dict(step_atr=1.0, candle_need=3, candle_body_dom=0.45, trail_tight_mult=1.0,
                   trail_wide_mult=3.5, conv_hold=0.6, max_legs=1, ladder_first=0.25,
                   ladder_spacing=0.55, smc_counter_legs=1, use_smc=False, let_winners_run=True),
}


def build_F(base, trend):
    rb = mt5.copy_rates_from_pos(SYM, TFMAP[base], 0, NB)
    rt = mt5.copy_rates_from_pos(SYM, TFMAP[trend], 0, NB)
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
    hour = [datetime.datetime.utcfromtimestamp(x).hour for x in tm]
    ct = [b["close"] for b in rt]; ttime = [b["time"] for b in rt]
    ef = ema(ct, 8); es = ema(ct, 21)
    trt = [rt[0]["high"] - rt[0]["low"]] + [max(rt[i]["high"] - rt[i]["low"],
           abs(rt[i]["high"] - rt[i - 1]["close"]), abs(rt[i]["low"] - rt[i - 1]["close"])) for i in range(1, len(rt))]
    at = []; st = 0.0
    for i in range(len(rt)):
        st += trt[i] - (trt[i - 14] if i >= 14 else 0)
        at.append(st / 14 if i >= 13 else 1.0)
    tend = [x + TFSEC[trend] for x in ttime]
    tdir = [0] * n; tstr = [0.0] * n
    for i in range(n):
        j = bisect.bisect_right(tend, tm[i]) - 1
        if j >= 0:
            gap = ef[j] - es[j]; a = at[j] or 1.0
            tdir[i] = 1 if gap > 0 else -1 if gap < 0 else 0
            tstr[i] = abs(gap) / a
    return dict(n=n, o=o, h=h, lo=lo, c=c, atr=atr, cd=cd, bd=bd, tdir=tdir, tstr=tstr,
               smc=[0] * n, hour=hour)


def slice_F(F, a, b):
    return {k: (v[a:b] if isinstance(v, list) else v) for k, v in F.items()} | {"n": b - a}


def main():
    mt5.initialize()
    info = mt5.symbol_info(SYM); t = mt5.symbol_info_tick(SYM)
    lab.SPREAD = (t.ask - t.bid)
    usd = (info.trade_tick_value / info.trade_tick_size) * info.volume_min if info.trade_tick_size else info.volume_min
    print(f"اختبار إصلاحات الذهب · سبريد ${lab.SPREAD:.3f} · {NB} شمعة لكل فريم\n")
    print(f"{'فريم':>5}{'جين':>8}{'جلسة':>18}{'صفقات':>7}{'PF':>6}{'صافي$':>9}{'PF-نص1':>8}{'PF-نص2':>8}{'حكم':>9}")
    robust = []
    for base, trend in PAIRS:
        F = build_F(base, trend)
        for gn, gbase in GENES.items():
            for sname, hrs in SESSIONS.items():
                g = dict(gbase); g["allowed_hours"] = hrs
                full = simulate(F, g)
                n = F["n"]; mid = n // 2
                h1 = simulate(slice_F(F, 0, mid), g); h2 = simulate(slice_F(F, mid, n), g)
                ok = full["pf"] > 1.05 and h1["pf"] > 1.0 and h2["pf"] > 1.0 and full["trades"] >= 20
                verdict = "✅ متين" if ok else ("⚠ نصف" if h2["pf"] > 1.0 else "❌")
                if full["trades"] >= 15:
                    print(f"{base:>5}{gn:>8}{sname:>18}{full['trades']:>7}{full['pf']:>6}"
                          f"{full['net']*usd:>9.1f}{h1['pf']:>8}{h2['pf']:>8}{verdict:>10}")
                if ok:
                    robust.append((full["pf"], base, gn, sname, full["trades"], full["net"] * usd))
    print()
    if robust:
        robust.sort(reverse=True)
        print("🏆 إعدادات ذهب متينة (PF>1.05 في النصفين):")
        for pf, base, gn, sname, nt, net in robust:
            print(f"   ذهب {base} · جين {gn} · {sname}: PF {pf} · {nt} صفقة · ${net:+.1f}  → صالح لإعادة الإطلاق")
    else:
        print("❌ لا إعداد ذهب متين رغم الإصلاحات (فلتر الجلسة/الفريم لم يخلق ميزة).")
        print("   التوصية: أبقِ الذهب موقوفاً. الميزة الحقيقية في BTCUSD H1.")
    mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
