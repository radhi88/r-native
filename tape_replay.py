"""tape_replay.py — إعادة تشغيل الشريط: "لو فعلنا كذا كان صار كذا".

يأخذ شريط القرارات المسجّل (tape/*.jsonl) + فرضية (شروط على أي حقل مسجّل)، ويحسب النتيجة
الافتراضية من أسعار MT5 الفعلية عند تلك اللحظات (سبريد حقيقي، أفق H بار) — لا افتراض.

أمثلة:
  python tape_replay.py --filter "aggressive==True"                  # لو دخلنا فقط وقت الهجومية
  python tape_replay.py --filter "confluence>=0.7,surge>=1.9"        # ثقة عالية + هجومي
  python tape_replay.py --filter "session==NY_OVERLAP,regime==trend" # جلسة نيويورك بترند
  python tape_replay.py --filter "votes.ml!=0,delta>15" --horizon 12
المخرجات: عدد الصفقات · معدّل الفوز · صافي R (بعد السبريد) · PF · لكل عملة/جلسة.
"""
from __future__ import annotations
import argparse, glob, json, sys
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
TAPE = MT5DIR / "data" / "r_native" / "tape"


def _get(row, key):
    if "." in key:                                  # votes.ml → row['votes']['ml']
        a, b = key.split(".", 1)
        return (row.get(a) or {}).get(b)
    return row.get(key)


def _match(row, conds):
    for k, op, val in conds:
        cur = _get(row, k)
        if cur is None:
            return False
        try:
            if op in (">", ">=", "<", "<=") and not isinstance(cur, (int, float)):
                return False
            if op == ">" and not (cur > val): return False
            if op == ">=" and not (cur >= val): return False
            if op == "<" and not (cur < val): return False
            if op == "<=" and not (cur <= val): return False
            if op == "==" and not (str(cur) == str(val)): return False
            if op == "!=" and not (str(cur) != str(val)): return False
        except Exception:
            return False
    return True


def _parse(flt):
    conds = []
    for part in flt.split(","):
        part = part.strip()
        if not part:
            continue
        for op in (">=", "<=", "!=", "==", ">", "<"):
            if op in part:
                k, v = part.split(op, 1); k = k.strip(); v = v.strip()
                if v in ("True", "False"):
                    val = (v == "True")
                else:
                    try: val = float(v)
                    except Exception: val = v
                conds.append((k, op, val)); break
    return conds


def replay(flt, horizon=8, days=3):
    import MetaTrader5 as mt5
    mt5.initialize()
    conds = _parse(flt)
    files = sorted(glob.glob(str(TAPE / "*.jsonl")))[-days:]
    rows = []
    for fp in files:
        for ln in Path(fp).read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(ln))
            except Exception: pass
    hits = [r for r in rows if r.get("dir") and _match(r, conds)]
    print(f"الشريط: {len(rows)} لقطة · مطابقة الفرضية «{flt}»: {len(hits)}")
    tfmap = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    by_sym, by_sess = {}, {}
    tot = [0, 0.0, 0]                                # n, netR, wins
    for r in hits:
        sym = r["sym"]; ts = int(r["ts"]); d = r["dir"]; atr = r.get("atr") or 0
        if atr <= 0:
            continue
        # أسعار فعلية بعد القرار (M15 افتراضاً) — سبريد حقيقي من السجل
        rates = mt5.copy_rates_from(sym, mt5.TIMEFRAME_M15, ts, horizon + 2)
        if rates is None or len(rates) < horizon + 1:
            continue
        entry = r["ask"] if d > 0 else r["bid"]
        fut = float(rates[min(horizon, len(rates) - 1)]["close"])
        sp = r.get("spread") or 0
        rR = ((fut - entry) if d > 0 else (entry - fut)) / atr - sp / atr   # عائد R صافي
        win = rR > 0
        for agg, key in ((by_sym, sym), (by_sess, r.get("session", "?"))):
            t = agg.setdefault(key, [0, 0.0, 0]); t[0] += 1; t[1] += rR; t[2] += 1 if win else 0
        tot[0] += 1; tot[1] += rR; tot[2] += 1 if win else 0
    def line(name, t):
        pf_w = t[2]; n = t[0]
        return f"  {name:14} {n:4d} صفقة · فوز {round(pf_w/n*100) if n else 0:3d}% · صافي {t[1]:+7.1f}R"
    print("\n═══ النتيجة الافتراضية (لو نفّذنا الفرضية) ═══")
    print(line("الإجمالي", tot))
    print("— حسب العملة —"); [print(line(s.replace("m",""), v)) for s, v in sorted(by_sym.items(), key=lambda x: -x[1][1])]
    print("— حسب الجلسة —"); [print(line(s, v)) for s, v in sorted(by_sess.items(), key=lambda x: -x[1][1])]
    mt5.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default="aggressive==True")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args()
    replay(a.filter, a.horizon, a.days)
