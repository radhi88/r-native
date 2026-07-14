"""exit_lab.py — باكتست جودة الخروج بصدق علمي no-lookahead على صفقات البوتات الحقيقية.

السؤال: البوتات (multi_trader 20260608، twins 20260612) تربح كثيراً صغيراً وتخسر قليلاً كبيراً
(W/L≈0.12-0.34). هل بديل خروج (trail/partial/time-stop/R ثابت) يرفع expectancy؟

المنهج (بلا lookahead): لكل صفقة مغلقة حقيقية نأخذ الدخول (سعر/اتجاه/وقت) فقط، ثم نعيد تشغيل
الشموع الأمامية ونحسب MFE/MAE ونحاكي قواعد خروج بديلة بوحدة R = ATR وقت الدخول (مقياس ثابت
لأن وقف كل جين يختلف). نقارن expectancy (متوسط R) لكل قاعدة مقابل الخروج الفعلي. تقسيم 67/33 OOS.

Run: .venv\\Scripts\\python.exe exit_lab.py [DAYS]
"""
from __future__ import annotations
import sys, json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

MT5DIR = Path(__file__).resolve().parent
MAGICS = {20260608: "multi_trader", 20260612: "twins"}
HORIZON = 120          # شموع M5 أمامية كحد أقصى للمحاكاة (~10h)
ATR_N = 14


def _atr_series(h, l, c):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.convolve(tr, np.ones(ATR_N) / ATR_N, mode="full")[:len(tr)]
    return atr


def simulate_exits(entry, direction, atr_r, fwd_h, fwd_l, fwd_c, sl=1.5):
    """fwd_* = شموع بعد الدخول (سببية). يرجع R لكل قاعدة. SL قابل للتعيين (افتراضي 1.5R)."""
    if atr_r <= 0:
        return None
    sgn = 1.0 if direction == "buy" else -1.0
    out = {}
    # دالة: امشِ أماماً، أوّل مَن يضرب TP أو SL
    def run(tp_r=None, trail_r=None, time_n=None):
        best = -1e9  # MFE in R
        peak = 0.0
        for i in range(len(fwd_c)):
            hi_r = sgn * (fwd_h[i] - entry) / atr_r if sgn > 0 else sgn * (fwd_l[i] - entry) / atr_r
            lo_r = sgn * (fwd_l[i] - entry) / atr_r if sgn > 0 else sgn * (fwd_h[i] - entry) / atr_r
            # SL يُفحص أولاً (متحفظ)
            if lo_r <= -sl:
                return -sl
            if trail_r is not None:
                peak = max(peak, hi_r)
                if peak - (sgn * (fwd_c[i] - entry) / atr_r) >= trail_r and peak >= trail_r:
                    return sgn * (fwd_c[i] - entry) / atr_r
            if tp_r is not None and hi_r >= tp_r:
                return tp_r
            if time_n is not None and i + 1 >= time_n:
                return sgn * (fwd_c[i] - entry) / atr_r
        return sgn * (fwd_c[-1] - entry) / atr_r  # نهاية الأفق
    out["TP1R"] = run(tp_r=1.0)
    out["TP2R"] = run(tp_r=2.0)
    out["TP3R"] = run(tp_r=3.0)
    out["trail1R"] = run(trail_r=1.0)
    out["trail1.5R"] = run(trail_r=1.5)
    out["time20"] = run(time_n=20)
    out["time40"] = run(time_n=40)
    # MFE/MAE للتشخيص
    mfe = max((sgn * (fwd_h[i] - entry) / atr_r if sgn > 0 else sgn * (fwd_l[i] - entry) / atr_r) for i in range(len(fwd_c)))
    mae = min((sgn * (fwd_l[i] - entry) / atr_r if sgn > 0 else sgn * (fwd_h[i] - entry) / atr_r) for i in range(len(fwd_c)))
    out["_mfe"] = mfe; out["_mae"] = mae
    return out


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 21
    mt5.initialize() or mt5.initialize()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    # اجمع IN/OUT حسب position_id
    pos = defaultdict(lambda: {"in": None, "out": None, "magic": None, "symbol": None})
    for x in deals:
        if x.magic not in MAGICS:
            continue
        p = pos[x.position_id]
        p["magic"] = x.magic; p["symbol"] = x.symbol
        if x.entry == 0:
            p["in"] = x
        elif x.entry == 1:
            p["out"] = x
    trades = [(pid, p) for pid, p in pos.items() if p["in"] and p["out"]]
    trades.sort(key=lambda kv: kv[1]["in"].time)
    print(f"paired trades: {len(trades)} over {days}d")

    # حمّل شموع M5 لكل رمز مرّة واحدة
    syms = set(p["symbol"] for _, p in trades)
    bars = {}
    for s in syms:
        r = mt5.copy_rates_range(s, mt5.TIMEFRAME_M5, now - timedelta(days=days + 2), now)
        if r is not None and len(r) > ATR_N + 5:
            t = np.array([x["time"] for x in r], np.int64)
            o = np.array([x["open"] for x in r], float); h = np.array([x["high"] for x in r], float)
            l = np.array([x["low"] for x in r], float); c = np.array([x["close"] for x in r], float)
            bars[s] = (t, o, h, l, c, _atr_series(h, l, c))
    mt5.shutdown()

    rows_by_magic = defaultdict(list)
    for pid, p in trades:
        s = p["symbol"]
        if s not in bars:
            continue
        t, o, h, l, c, atr = bars[s]
        din = p["in"]; dout = p["out"]
        direction = "buy" if din.type == 0 else "sell"   # DEAL_TYPE_BUY=0
        entry = din.price; etime = din.time
        # موضع الدخول في الشموع: آخر شمعة وقت <= etime (سببي)
        idx = int(np.searchsorted(t, etime, side="right") - 1)
        if idx < ATR_N or idx + 2 >= len(c):
            continue
        atr_r = atr[idx]
        fwd_end = min(idx + 1 + HORIZON, len(c))
        fwd_h = h[idx + 1:fwd_end]; fwd_l = l[idx + 1:fwd_end]; fwd_c = c[idx + 1:fwd_end]
        if len(fwd_c) < 3:
            continue
        sim = simulate_exits(entry, direction, atr_r, fwd_h, fwd_l, fwd_c)
        if sim is None:
            continue
        # الخروج الفعلي بوحدة R
        sgn = 1.0 if direction == "buy" else -1.0
        actual_r = sgn * (dout.price - entry) / atr_r if atr_r > 0 else 0.0
        sim["_actual"] = actual_r
        sim["_time"] = etime
        rows_by_magic[p["magic"]].append(sim)

    rules = ["_actual", "TP1R", "TP2R", "TP3R", "trail1R", "trail1.5R", "time20", "time40"]
    report = {}
    for magic, rows in rows_by_magic.items():
        if len(rows) < 20:
            print(f"\n{MAGICS[magic]} ({magic}): only {len(rows)} usable — skip")
            continue
        rows.sort(key=lambda r: r["_time"])
        cut = int(len(rows) * 0.67)
        oos = rows[cut:]
        print(f"\n=== {MAGICS[magic]} ({magic}) — {len(rows)} trades (OOS={len(oos)}) ===")
        mfe = np.mean([r["_mfe"] for r in oos]); mae = np.mean([r["_mae"] for r in oos])
        print(f"  متوسط MFE={mfe:+.2f}R  MAE={mae:+.2f}R  (كم تتحرك لصالحنا قبل أن نخرج)")
        res = {}
        for rule in rules:
            vals = [r[rule] for r in oos]
            exp = float(np.mean(vals)); std = float(np.std(vals))
            wr = float(np.mean([1.0 if v > 0 else 0.0 for v in vals])) if vals else 0.0
            res[rule] = {"expR": round(exp, 4), "wr": round(wr, 3), "n": len(vals)}
            tag = " ← الفعلي" if rule == "_actual" else ""
            print(f"  {rule:10} expR={exp:+.3f}  WR={wr*100:4.0f}%  (std {std:.2f}){tag}")
        # الأفضل
        best = max((k for k in rules if k != "_actual"), key=lambda k: res[k]["expR"])
        delta = res[best]["expR"] - res["_actual"]["expR"]
        print(f"  >>> أفضل بديل: {best} (expR {res[best]['expR']:+.3f}) مقابل الفعلي {res['_actual']['expR']:+.3f} = فرق {delta:+.3f}R")
        report[MAGICS[magic]] = {"n": len(rows), "oos": len(oos), "mfe": round(mfe, 3),
                                 "mae": round(mae, 3), "rules": res, "best": best, "delta_R": round(delta, 4)}
    out = MT5DIR / "data" / "lab_cache" / "exit_lab_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ts": now.isoformat(), "days": days, "report": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
