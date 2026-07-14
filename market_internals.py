"""market_internals.py — مؤشرات خاصة من أرقام MT5 المهملة (symbol_info): قوة نسبية مقطعية + DRP.

اكتشفنا بتفكيك الـAPI أرقاماً لم نستغلّها:
  • bidhigh/bidlow → DRP (موقع السعر في مدى اليوم 0-100): قرب القمة=زخم صاعد · قرب القاع=ضعف.
  • price_change (% يومي) لكل الرموز (289) → قوة نسبية مقطعية: من يقود ومن يتخلّف (زخم مقطعي مؤسسي).
  • spread/مدى، swap (كلفة الاحتفاظ) — سياق إضافي.
يكتب market_internals.json {sym:{chg,drp,rs}} + قادة/متخلّفون. chart_read يقرأه كصوتين متعلّمين
(drp, rstr). صفر تكلفة، لحظي. Windowless.  Run:  pythonw market_internals.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5") / "data" / "r_native"
OUT = RN / "market_internals.json"
POLL_S = 60


def cycle(mt5):
    syms = mt5.symbols_get()
    rows = {}
    chgs = []
    for s in syms:
        n = s.name
        if not n.endswith("m"):
            continue
        i = mt5.symbol_info(n)
        if not i or not getattr(i, "bid", 0):
            continue
        rng = i.bidhigh - i.bidlow
        drp = round((i.bid - i.bidlow) / rng * 100) if rng > 0 else None
        chg = round(getattr(i, "price_change", 0.0), 2)
        sp_rng = round((i.ask - i.bid) / rng * 100, 2) if rng > 0 else None   # سبريد كنسبة من مدى اليوم
        # انحياز افتتاح الجلسة: فوق افتتاح اليوم = نهار صاعد (مرجع مؤسسي مجاني من MT5)
        sopen = getattr(i, "session_open", 0.0) or 0.0
        sob = (1 if i.bid > sopen else -1) if (sopen and rng > 0) else 0
        rows[n] = {"chg": chg, "drp": drp, "spread_rng": sp_rng, "sob": sob,
                   "swap_long": getattr(i, "swap_long", 0.0), "swap_short": getattr(i, "swap_short", 0.0)}
        if chg:
            chgs.append((n, chg))
    # القوة النسبية المقطعية: المئين لكل رمز حسب التغيّر اليومي
    chgs.sort(key=lambda x: x[1])
    m = len(chgs)
    for rank, (n, _) in enumerate(chgs):
        rows[n]["rs"] = round(rank / max(1, m - 1) * 100)        # 0=أضعف · 100=أقوى
    leaders = [(n.replace("m", ""), c) for n, c in sorted(chgs, key=lambda x: -x[1])[:8]]
    laggards = [(n.replace("m", ""), c) for n, c in sorted(chgs, key=lambda x: x[1])[:8]]
    out = {"_ts": time.time(), "_iso": datetime.now(timezone.utc).isoformat(),
           "n": m, "leaders": leaders, "laggards": laggards, **rows}
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT)
    return m, leaders[:3], laggards[:3]


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[INTERNALS] داخليات السوق حيّة — قوة نسبية مقطعية + DRP من أرقام MT5", flush=True)
    while True:
        try:
            m, lead, lag = cycle(mt5)
            print(f"[INTERNALS] {m} رمز · قادة {lead} · متخلّفون {lag}", flush=True)
        except Exception as e:
            print(f"[INTERNALS] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
