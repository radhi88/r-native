"""straddle3627_lab.py — مختبر الجينات للبوت (magic 3627).

كل «جين» = مجموعة قيم/مؤشرات خاصة (step_atr، candle_need، body_dom، تتبّع القناعة،
SMC، التعبئة...). نحاكي منطق الاستراتيجية (زخم شموع + سلّم/تعبئة + سلّة + قناعة + SMC)
على ذهب M1 تاريخي، نقيس أداء كل جين (صافي/نسبة ربح/PF/أقصى تراجع)، ونحفظ الكل في
straddle3627.db (جدول genes) مرتّبة — فنعرف الرابح من الخاسر مبنياً على بيانات.

⚠️ تقريبي: تعبئة على OHLC (لا تيك)، سبريد ثابت، SMC على M15 مبسّط. للترتيب النسبي
بين الجينات لا للأرقام المطلقة. Run:  python straddle3627_lab.py
"""
import json, time, itertools, sqlite3
from pathlib import Path
import MetaTrader5 as mt5

DB = Path(r"C:\Users\Radhi\MT5\data\r_native\straddle3627.db")
SYM = "XAUUSDm"
N_M1 = 20000
SPREAD = 0.26          # سبريد ثابت ($) — تكلفة لكل رِجل
LOTDOLLAR = 1.0        # $ لكل $1 حركة على 0.01 لوت ذهب


def ema(vals, n):
    k = 2.0 / (n + 1); e = vals[0]; out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k); out.append(e)
    return out


def load():
    mt5.initialize()
    m1 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, N_M1)
    m5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, N_M1 // 4)
    m15 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, N_M1 // 12)
    mt5.shutdown()
    return m1, m5, m15


def precompute(m1, m5, m15):
    import bisect
    n = len(m1)
    o = [b["open"] for b in m1]; h = [b["high"] for b in m1]
    lo = [b["low"] for b in m1]; c = [b["close"] for b in m1]; tt = [b["time"] for b in m1]
    # ATR M1 (14)
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, n)]
    atr = [0.0] * n; s = sum(tr[:14])
    for i in range(n):
        if i >= 14:
            s += tr[i] - tr[i - 14]
        atr[i] = s / 14 if i >= 13 else (sum(tr[:i + 1]) / (i + 1))
    # candle body dir + dominance per bar
    cd = [1 if c[i] > o[i] else -1 if c[i] < o[i] else 0 for i in range(n)]
    bd = [abs(c[i] - o[i]) / ((h[i] - lo[i]) or 1e-9) for i in range(n)]
    # M5 trend (EMA8/21 + ATR14) per M5 bar → map to M1 by time
    c5 = [b["close"] for b in m5]; t5 = [b["time"] for b in m5]
    ef5 = ema(c5, 8); es5 = ema(c5, 21)
    tr5 = [m5[0]["high"] - m5[0]["low"]] + [max(m5[i]["high"] - m5[i]["low"],
           abs(m5[i]["high"] - m5[i - 1]["close"]), abs(m5[i]["low"] - m5[i - 1]["close"])) for i in range(1, len(m5))]
    atr5 = []; s5 = 0.0
    for i in range(len(m5)):
        s5 += tr5[i] - (tr5[i - 14] if i >= 14 else 0)
        atr5.append(s5 / 14 if i >= 13 else 1.0)
    t5end = [x + 300 for x in t5]   # وقت إغلاق شمعة M5
    tdir = [0] * n; tstr = [0.0] * n
    for i in range(n):
        j = bisect.bisect_right(t5end, tt[i]) - 1
        if j >= 0:
            gap = ef5[j] - es5[j]; a = atr5[j] or 1.0
            tdir[i] = 1 if gap > 0 else -1 if gap < 0 else 0
            tstr[i] = abs(gap) / a
    # SMC M15 (هيكل قمم/قيعان + خصم/علاوة) per M15 bar → map to M1
    t15 = [b["time"] for b in m15]; t15end = [x + 900 for x in t15]
    h15 = [b["high"] for b in m15]; l15 = [b["low"] for b in m15]; c15 = [b["close"] for b in m15]
    smcb = [0] * len(m15)
    K = 2; W = 120
    for i in range(len(m15)):
        a0 = max(0, i - W)
        sh = [(x, h15[x]) for x in range(a0 + K, i - K + 1)
              if all(h15[x] >= h15[x - j] and h15[x] >= h15[x + j] for j in range(1, K + 1))]
        sl = [(x, l15[x]) for x in range(a0 + K, i - K + 1)
              if all(l15[x] <= l15[x - j] and l15[x] <= l15[x + j] for j in range(1, K + 1))]
        b = 0
        if len(sh) >= 2 and len(sl) >= 2:
            if sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]:
                b = 1
            elif sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]:
                b = -1
        if b != 0:                              # تأكيد بالخصم/العلاوة
            seg = m15[a0:i + 1]
            hi = max(x["high"] for x in seg); low = min(x["low"] for x in seg); mid = (hi + low) / 2
            disc = c15[i] < mid
            if (b == 1 and not disc) or (b == -1 and disc):
                pass   # نُبقي الهيكل حتى لو المنطقة معاكِسة (انحياز ناعم)
        smcb[i] = b
    smc = [0] * n
    for i in range(n):
        j = bisect.bisect_right(t15end, tt[i]) - 1
        if j >= 0:
            smc[i] = smcb[j]
    return dict(n=n, o=o, h=h, lo=lo, c=c, atr=atr, cd=cd, bd=bd, tdir=tdir, tstr=tstr, smc=smc)


def simulate(F, g):
    """يحاكي جيناً g على البيانات F. يرجّع dict مقاييس."""
    n = F["n"]; o = F["o"]; h = F["h"]; lo = F["lo"]; c = F["c"]
    atr = F["atr"]; cd = F["cd"]; bd = F["bd"]; tdir = F["tdir"]; tstr = F["tstr"]; smc = F["smc"]
    need = g["candle_need"]; bdom = g["candle_body_dom"]
    pos = 0; entry = 0.0; legs = 0; ext = 0.0; maxlegs = 1; ent_i = 0
    trades = []; equity = 0.0; peak = 0.0; maxdd = 0.0
    nextlevel = 0.0

    def signal(i):
        if i < need:
            return 0
        w = range(i - need + 1, i + 1)
        up = sum(1 for k in w if cd[k] > 0); dn = sum(1 for k in w if cd[k] < 0)
        avgb = sum(bd[k] for k in w) / need
        if avgb < bdom:
            return 0
        if up >= need and up > dn:
            return 1
        if dn >= need and dn > up:
            return -1
        return 0

    for i in range(need, n - 1):
        step = max(g["step_atr"] * atr[i], 0.6)
        sig = signal(i)
        if pos == 0:
            # فلتر الجلسة (اختياري): لا دخول خارج الساعات المسموحة (UTC)
            if g.get("allowed_hours") is not None and F.get("hour") is not None:
                if F["hour"][i] not in g["allowed_hours"]:
                    continue
            if sig != 0:
                pos = sig; legs = 1; ent_i = i + 1
                entry = o[i + 1] + (SPREAD / 2) * pos        # دخول الشمعة التالية + نصف سبريد
                ext = entry
                maxlegs = g["max_legs"]
                if g["use_smc"] and smc[i] != 0 and smc[i] != pos:
                    maxlegs = g["smc_counter_legs"]
                nextlevel = entry + pos * g["ladder_spacing"] * step
            continue
        # داخل صفقة — عالج شمعة i+1
        bar_h = h[i + 1]; bar_l = lo[i + 1]
        ext = max(ext, bar_h) if pos > 0 else min(ext, bar_l)
        # تعبئة (pyramiding) عند امتداد لصالحنا
        if legs < maxlegs:
            if (pos > 0 and bar_h >= nextlevel) or (pos < 0 and bar_l <= nextlevel):
                entry = (entry * legs + (nextlevel + (SPREAD / 2) * pos)) / (legs + 1)
                legs += 1; nextlevel = entry + pos * (g["ladder_first"] + legs * g["ladder_spacing"]) * step
        # القناعة
        conv = 0.0
        conv += 0.35 * min(1.0, tstr[i]) if tdir[i] == pos else 0.0
        conv += 0.25 if tdir[i] == pos and tdir[i] != 0 else 0.0
        conv += 0.20 if smc[i] == pos else 0.0
        conv += 0.10 * min(1.0, bd[i] / 0.7)
        conv += 0.10 if legs >= 2 else 0.0
        tmult = g["trail_tight_mult"] + (g["trail_wide_mult"] - g["trail_tight_mult"]) * conv
        prot = (ext - tmult * step) if pos > 0 else (ext + tmult * step)
        # قفل التعادل
        if pos > 0 and (bar_h - entry) >= step:
            prot = max(prot, entry + 0.25 * step)
        if pos < 0 and (entry - bar_l) >= step:
            prot = min(prot, entry - 0.25 * step)
        exitp = None
        if pos > 0 and bar_l <= prot:
            exitp = prot
        elif pos < 0 and bar_h >= prot:
            exitp = prot
        # انعكاس سوقي (إن لم تكن القناعة عالية)
        if exitp is None and sig == -pos and not (g["let_winners_run"] and conv >= g["conv_hold"]):
            exitp = c[i + 1]
        if exitp is not None:
            net = (exitp - entry) * pos * legs * LOTDOLLAR - SPREAD * legs
            trades.append(net); equity += net
            peak = max(peak, equity); maxdd = max(maxdd, peak - equity)
            pos = 0; legs = 0
    # مقاييس
    nt = len(trades); net = round(sum(trades), 2)
    w = [x for x in trades if x > 0]; l = [x for x in trades if x <= 0]
    wr = round(100 * len(w) / nt, 1) if nt else 0
    aw = round(sum(w) / len(w), 3) if w else 0; al = round(sum(l) / len(l), 3) if l else 0
    pf = round(sum(w) / -sum(l), 2) if l and sum(l) != 0 else (999 if w else 0)
    return dict(trades=nt, net=net, wr=wr, avg_win=aw, avg_loss=al, pf=pf, maxdd=round(maxdd, 2))


def gene_grid():
    grid = dict(
        step_atr=[0.5, 0.8, 1.2],
        candle_need=[2, 3],
        candle_body_dom=[0.40, 0.50],
        trail_wide_mult=[2.0, 3.5],
        conv_hold=[0.5, 0.7],
        max_legs=[1, 3],
        use_smc=[False, True],
    )
    fixed = dict(trail_tight_mult=1.0, ladder_first=0.25, ladder_spacing=0.55,
                 smc_counter_legs=1, let_winners_run=True)
    keys = list(grid.keys())
    out = []
    for combo in itertools.product(*grid.values()):
        g = dict(fixed); g.update(dict(zip(keys, combo)))
        out.append(g)
    return out


def main():
    print("تحميل البيانات…", flush=True)
    m1, m5, m15 = load()
    print(f"M1 {len(m1)} · M5 {len(m5)} · M15 {len(m15)} — حساب المؤشرات…", flush=True)
    F = precompute(m1, m5, m15)
    genes = gene_grid()
    print(f"اختبار {len(genes)} جين على {F['n']} شمعة…", flush=True)
    con = sqlite3.connect(str(DB), timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS genes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, params TEXT,
        trades INTEGER, net REAL, wr REAL, avg_win REAL, avg_loss REAL, pf REAL, maxdd REAL)""")
    con.execute("DELETE FROM genes")
    results = []
    t0 = time.time()
    for gi, g in enumerate(genes):
        m = simulate(F, g)
        con.execute("INSERT INTO genes(ts,params,trades,net,wr,avg_win,avg_loss,pf,maxdd) VALUES(?,?,?,?,?,?,?,?,?)",
                    (time.time(), json.dumps(g, ensure_ascii=False), m["trades"], m["net"],
                     m["wr"], m["avg_win"], m["avg_loss"], m["pf"], m["maxdd"]))
        results.append((m, g))
    con.commit()
    results.sort(key=lambda x: x[0]["net"], reverse=True)
    print(f"\nتمّ في {time.time()-t0:.1f}ث · حُفظت {len(genes)} جين في genes\n")

    def show(m, g):
        flags = f"step{g['step_atr']} need{g['candle_need']} body{g['candle_body_dom']} " \
                f"wide{g['trail_wide_mult']} hold{g['conv_hold']} legs{g['max_legs']} smc{int(g['use_smc'])}"
        print(f"  net {m['net']:+8.2f} | صفقات {m['trades']:4} | ربح {m['wr']:5.1f}% | "
              f"PF {m['pf']:5} | DD {m['maxdd']:6.2f} | {flags}")

    print("═══ أفضل 8 جينات (رابحة) ═══")
    for m, g in results[:8]:
        show(m, g)
    print("\n═══ أسوأ 5 جينات (خاسرة) ═══")
    for m, g in results[-5:]:
        show(m, g)
    best = results[0][1]
    print("\n🏆 أفضل جين (طبّقه حياً عبر straddle3627_state.json → cfg):")
    print("  ", json.dumps({k: best[k] for k in ("step_atr", "candle_need", "candle_body_dom",
          "trail_wide_mult", "conv_hold", "max_legs", "use_smc")}, ensure_ascii=False))
    con.close()


if __name__ == "__main__":
    raise SystemExit(main())
