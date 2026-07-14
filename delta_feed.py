"""delta_feed.py — الدلتا (تدفّق الأوامر) كسياق مقيس، لا كعرّاف.

الحقيقة المقاسة أولاً (بروتوكولنا): بروكر Exness لا يرسل أعلام مشترٍ/بائع ولا حجماً حقيقياً،
فالدلتا الحقيقية مستحيلة؛ البديل الصناعي هو دلتا قاعدة-التيك (uptick=شراء، downtick=بيع).
اختبرناها على 1.7 مليون تيك حقيقي (48 ساعة): دقة اتجاهية ~47-52% = غير تنبؤية وحدها.

لذلك دورها هنا (مثل سابقة الفراكتال "سياق فقط"):
  1. تُحسب حيّاً لكل رموز الجلسة وتُعرض في ARENA (يعرف المستخدم كيف يدخل: مع من الضغط الآن).
  2. تُسجَّل على كل صفقة في trade_ledger → لو أثبت السجل لاحقاً أن "دخولات جينٍ ما مع دلتا
     موجبة تتفوّق"، يكسب الدلتا وزنه بالدليل عبر المُهجِّن — لا بالإيمان.
Writes: data/r_native/delta_state.json — {sym: {delta_m1, cvd_20m, bias(-100..100), ticks}}.
Read-only. Windowless.  Run:  pythonw delta_feed.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
OUT = RN / "delta_state.json"
POLL_S = 30
WIN_S = 20 * 60                 # نافذة الدلتا التراكمية CVD
if str(MT5DIR / "r_native_v2") not in sys.path:
    sys.path.insert(0, str(MT5DIR / "r_native_v2"))


def _roster():
    try:
        import multi_trader as mt
        syms = set(mt._genomes())
    except Exception:
        syms = set()
    syms.add("XAUUSDm")
    return sorted(syms)


def _tick_delta(mt5, sym):
    now = int(time.time())
    ticks = mt5.copy_ticks_range(sym, now - WIN_S, now, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) < 50:
        return None
    prev = None
    cvd = 0
    last_min = int(ticks[0]["time"] // 60)
    d_m1 = 0
    m1_series = []
    for t in ticks:
        mid = (float(t["bid"]) + float(t["ask"])) / 2
        mn = int(t["time"] // 60)
        if mn != last_min:
            m1_series.append(d_m1)
            d_m1 = 0
            last_min = mn
        if prev is not None:
            if mid > prev:
                cvd += 1; d_m1 += 1
            elif mid < prev:
                cvd -= 1; d_m1 -= 1
        prev = mid
    m1_series.append(d_m1)
    n = len(ticks)
    bias = max(-100, min(100, round(cvd / max(1, n) * 400)))
    return {"cvd_20m": int(cvd), "delta_m1": int(m1_series[-1]) if m1_series else 0,
            "m1_series": [int(x) for x in m1_series[-15:]], "bias": bias, "ticks": int(n)}


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[DELTA] دلتا قاعدة-التيك حيّة (سياق مقيس ~50% — تكسب وزنها بالدليل فقط)", flush=True)
    while True:
        try:
            out = {"_ts": time.time(), "_iso": datetime.now(timezone.utc).isoformat(),
                   "_doc": "tick-rule delta — measured ~50% standalone; CONTEXT + ledger evidence only"}
            for sym in _roster():
                d = _tick_delta(mt5, sym)
                if d:
                    out[sym] = d
            tmp = OUT.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, OUT)
            tag = " · ".join(f"{s.replace('m','')}: {v['bias']:+d}" for s, v in out.items()
                             if not s.startswith("_"))
            print(f"[DELTA] {tag}", flush=True)
        except Exception as e:
            print(f"[DELTA] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
