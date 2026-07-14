# -*- coding: utf-8 -*-
"""wade_backtest.py — 🔁 إعادة تشغيل تاريخية لإعدادَي Wade FX (طلب المستخدم «تقدر تجرّبه» 2026-07-03).

A) SH+BMS+RTO: كنس ⇒ BOS بعده ⇒ كمين عند حافة OB غير مُخمَد — على SMC حقيقي (smc_engine) يُعاد
   حسابه شمعةً شمعة M5 (سببيّ — لا نظرة مستقبلية: نافذة منتهية بالشمعة المغلقة الحالية فقط).
B) Turtle Soup على PDH/PDL داخل نوافذ لندن/نيويورك — على M1.

قواعد الحكم الصارمة: تعبئة الكمين فقط إن لمسه السعر خلال مهلته؛ الشمعة التي تلمس الوقف والهدف
معاً تُحسب خسارة (متشائم عمداً)؛ كلفة 0.24$ لكل صفقة؛ صفقة واحدة حيّة لكل إعداد (لا تداخل)."""
import os, sys, json, time
import numpy as np

_BASE = r"C:\Users\Radhi\MT5"
sys.path.insert(0, _BASE)
_RN = os.path.join(_BASE, "data", "r_native")
LOG = open(os.path.join(_RN, "wade_backtest.out.log"), "a", buffering=1, encoding="utf-8")
sys.stdout = LOG; sys.stderr = LOG

import MetaTrader5 as mt5
import smc_engine

SYM = "XAUUSDm"
COST = 0.24
SL_MIN, SL_MAX, TP_MIN, TP_CAP = 1.8, 3.5, 1.2, 3.0
OUT = os.path.join(_RN, "wade_backtest_result.json")


def atr14(h, l, c):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    if len(tr) < 14:
        return None
    return float(tr[-14:].mean())


def first_touch(h, l, i0, d, sl, tp, max_bars):
    """يمشي شمعةً شمعة: أيّهما يُلمس أولاً؟ اللمس المزدوج بنفس الشمعة = خسارة (متشائم)."""
    for i in range(i0, min(i0 + max_bars, len(h))):
        hit_sl = (l[i] <= sl) if d == 1 else (h[i] >= sl)
        hit_tp = (h[i] >= tp) if d == 1 else (l[i] <= tp)
        if hit_sl:                                     # يشمل المزدوج ⇒ خسارة
            return -1, i
        if hit_tp:
            return 1, i
    return 0, min(i0 + max_bars, len(h)) - 1           # انتهت المهلة بلا حسم


def run_A(r5):
    """SH+BMS+RTO على M5 بإعادة حساب SMC سببيّاً كل شمعة."""
    o = r5["open"].astype(float); h = r5["high"].astype(float)
    l = r5["low"].astype(float); c = r5["close"].astype(float)
    v = r5["tick_volume"].astype(float)
    n = len(c); WIN = 160
    trades = []; busy_until = 0
    for i in range(WIN, n - 1):
        if i < busy_until:
            continue
        w0 = i - WIN + 1
        try:
            smc = smc_engine.compute_smc(o[w0:i + 1], h[w0:i + 1], l[w0:i + 1], c[w0:i + 1], v[w0:i + 1])
        except Exception:
            continue
        sweeps = smc.get("sweeps") or []; bos = smc.get("bos") or []; obs = smc.get("ob") or []
        if not sweeps or not bos:
            continue
        mid = float(c[i])
        fired = False
        for d, side in ((1, "low"), (-1, "high")):
            sw = next((s for s in reversed(sweeps)
                       if str(s.get("side")) == side and (WIN - 1 - int(s.get("idx", -9))) <= 12), None)
            if not sw:
                continue
            b = bos[-1]
            if int(b.get("dir", 0)) != d or int(b.get("idx", -1)) <= int(sw["idx"]):
                continue
            ob = next((z for z in reversed(obs)
                       if int(z.get("dir", 0)) == d and not z.get("mitigated")
                       and int(z.get("idx", -9)) >= int(sw["idx"]) - 2), None)
            if not ob:
                continue
            edge = float(ob["hi"]) if d == 1 else float(ob["lo"])
            if not (0.3 <= d * (mid - edge) <= 6.0):
                continue
            a = atr14(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1]) or 0.5
            struct = (min(float(ob["lo"]), float(sw["price"])) if d == 1
                      else max(float(ob["hi"]), float(sw["price"])))
            sl = struct - d * max(0.15, 0.03 * a)
            sd = abs(edge - sl)
            if sd > SL_MAX or sd < 0.4:
                continue
            if sd < SL_MIN:
                sl = edge - d * SL_MIN
            tgt = float(b.get("price", 0) or 0)
            if not tgt:
                continue
            tp = min(tgt, edge + TP_CAP) if d == 1 else max(tgt, edge - TP_CAP)
            if d * (tp - edge) < TP_MIN:
                continue
            # التعبئة: هل يلمس السعر الحافة خلال 3 شموع M5 (900ث)؟
            fill_i = None
            for j in range(i + 1, min(i + 4, n)):
                if (l[j] <= edge) if d == 1 else (h[j] >= edge):
                    fill_i = j; break
            if fill_i is None:
                continue
            res, end_i = first_touch(h, l, fill_i, d, sl, tp, 288)   # مهلة 24 ساعة
            pnl = (d * (tp - edge) if res == 1 else (-abs(edge - sl) if res == -1
                   else d * (float(c[end_i]) - edge))) - COST
            trades.append({"t": int(r5["time"][i]), "dir": d, "entry": round(edge, 2),
                           "sl": round(sl, 2), "tp": round(tp, 2), "res": res, "pnl": round(pnl, 2)})
            busy_until = end_i + 1
            fired = True
            break
        if not fired:
            continue
    return trades


def run_B(r1, d1):
    """Turtle Soup على M1 — PDH/PDL يومية + نوافذ الجلسات."""
    h1 = r1["high"].astype(float); l1 = r1["low"].astype(float)
    c1 = r1["close"].astype(float); t1 = r1["time"].astype(np.int64)
    days = {}
    for k in range(1, len(d1)):
        daykey = time.strftime("%Y-%m-%d", time.gmtime(int(d1["time"][k])))
        days[daykey] = {"pdh": float(d1["high"][k - 1]), "pdl": float(d1["low"][k - 1]),
                        "dopen": float(d1["open"][k])}
    trades = []; done = set(); busy_until = 0
    for i in range(20, len(c1) - 1):
        if i < busy_until:
            continue
        ep = int(t1[i]); hr = time.gmtime(ep).tm_hour
        if not ((7 <= hr < 10) or (12 <= hr < 15)):
            continue
        daykey = time.strftime("%Y-%m-%d", time.gmtime(ep))
        lv = days.get(daykey)
        if not lv:
            continue
        a = atr14(h1[i - 19:i + 1], l1[i - 19:i + 1], c1[i - 19:i + 1]) or 0.4
        for d, L, key in ((1, lv["pdl"], "pdl"), (-1, lv["pdh"], "pdh")):
            if (daykey, key) in done:
                continue
            lo6 = l1[i - 5:i + 1].min(); hi6 = h1[i - 5:i + 1].max()
            if d == 1:
                pierced = lo6 < L and c1[i] > L; depth = L - lo6; ext = lo6
            else:
                pierced = hi6 > L and c1[i] < L; depth = hi6 - L; ext = hi6
            if not pierced or not (0.10 * a <= depth <= 1.2 * a):
                continue
            entry = L + d * 0.05
            if d * (c1[i] - entry) > 4.0:
                continue
            sl = ext - d * max(0.15, 0.1 * a)
            sd = abs(entry - sl)
            if sd > SL_MAX:
                continue
            if sd < SL_MIN:
                sl = entry - d * SL_MIN
            do = lv["dopen"]
            tp = do if (do and d * (do - entry) >= TP_MIN) else entry + d * TP_CAP
            if d * (tp - entry) > TP_CAP:
                tp = entry + d * TP_CAP
            fill_i = None
            for j in range(i + 1, min(i + 11, len(c1))):
                if (l1[j] <= entry) if d == 1 else (h1[j] >= entry):
                    fill_i = j; break
            if fill_i is None:
                continue
            res, end_i = first_touch(h1, l1, fill_i, d, sl, tp, 1440)
            pnl = (d * (tp - entry) if res == 1 else (-abs(entry - sl) if res == -1
                   else d * (float(c1[end_i]) - entry))) - COST
            trades.append({"t": ep, "dir": d, "level": key, "entry": round(entry, 2),
                           "res": res, "pnl": round(pnl, 2), "depth_atr": round(depth / a, 2)})
            done.add((daykey, key))
            busy_until = end_i + 1
            break
    return trades


def stats(trades):
    if not trades:
        return {"n": 0}
    p = np.array([t["pnl"] for t in trades])
    w = int((p > 0).sum())
    t_ = float(p.mean() / (p.std(ddof=1) / np.sqrt(len(p)))) if len(p) > 2 and p.std(ddof=1) > 1e-9 else 0.0
    return {"n": len(p), "wins": w, "wr": round(100 * w / len(p), 1), "net": round(float(p.sum()), 2),
            "avg": round(float(p.mean()), 3), "t": round(t_, 2),
            "best": round(float(p.max()), 2), "worst": round(float(p.min()), 2)}


def main():
    t0 = time.time()
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🔁 اختبار Wade التاريخي بدأ {time.strftime('%H:%M:%S')}")
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 1, 13000)
    r1 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 1, 45000)
    d1 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 0, 70)
    print(f"بيانات: M5={len(r5) if r5 is not None else 0} · M1={len(r1) if r1 is not None else 0} · D1={len(d1) if d1 is not None else 0}")
    A = run_A(r5) if r5 is not None else []
    B = run_B(r1, d1) if (r1 is not None and d1 is not None) else []
    sa, sb = stats(A), stats(B)
    days5 = (int(r5["time"][-1]) - int(r5["time"][0])) / 86400 if r5 is not None else 0
    days1 = (int(r1["time"][-1]) - int(r1["time"][0])) / 86400 if r1 is not None else 0
    out = {"iso": time.strftime("%Y-%m-%dT%H:%M:%S"), "cost_usd": COST,
           "pessimistic_double_touch": True,
           "A_shbmsrto": {"days": round(days5, 1), **sa, "last5": A[-5:]},
           "B_turtle_soup": {"days": round(days1, 1), **sb, "last5": B[-5:]},
           "runtime_s": round(time.time() - t0, 1)}
    tmp = OUT + ".tmp"; json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(json.dumps({k: v for k, v in out.items() if k != "runtime_s"}, ensure_ascii=False)[:600])
    print(f"🏁 انتهى في {out['runtime_s']}ث")
    mt5.shutdown()


if __name__ == "__main__":
    main()
