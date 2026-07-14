"""vol_forecast.py — تنبؤ تقلّب الشمعة القادمة (GARCH) لتحجيم اللوت بدقّة (vol-targeting).

من EDGE_RESEARCH_PLAN: الأنظمة المؤسسية تحجّم بالـvolatility المتوقّعة لا الثابتة. نحسب GARCH(1,1)
next-bar sigma لكل رمز جلسة (عبر quant_gates.garch_sigma) ونقارنه بالتقلّب المُحقّق → نسبة + نظام
(هدوء/عادي/عاصفة). محرّك مستقل (لا يعطّل multi_trader — الفِت ثقيل) يكتب vol_forecast.json،
والمتداول يقرأه رخيصاً: لوت ∝ 1/التقلّب المتوقّع (مخاطرة ثابتة عبر الأنظمة). Windowless.
Run:  pythonw vol_forecast.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
OUT = RN / "vol_forecast.json"
POLL_S = 300
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _roster():
    try:
        import multi_trader as mt
        syms = set(mt._genomes())
    except Exception:
        syms = set()
    syms.update(["XAUUSDm", "BTCUSDm", "USDJPYm"])
    return sorted(syms)


def cycle(mt5):
    import quant_gates as qg
    out = {}
    for sym in _roster():
        try:
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 300)
            if r is None or len(r) < 120:
                continue
            closes = [float(x["close"]) for x in r]
            rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
            sig = qg.garch_sigma(rets)
            if not sig:
                continue
            # التقلّب المُحقّق (آخر 30 شمعة) للمقارنة
            recent = rets[-30:]
            mu = sum(recent) / len(recent)
            realized = (sum((x - mu) ** 2 for x in recent) / len(recent)) ** 0.5
            ratio = round(sig / realized, 3) if realized > 0 else 1.0
            regime = "storm" if ratio > 1.25 else "calm" if ratio < 0.8 else "normal"
            # عامل التحجيم: مخاطرة ثابتة → لوت أصغر وقت العاصفة المتوقّعة، أكبر وقت الهدوء
            factor = round(max(0.5, min(1.5, 1.0 / ratio)), 3) if ratio > 0 else 1.0
            out[sym] = {"garch": round(sig, 6), "realized": round(realized, 6),
                        "ratio": ratio, "regime": regime, "lot_factor": factor}
        except Exception:
            pass
    payload = {"_ts": time.time(), "_iso": datetime.now(timezone.utc).isoformat(),
               "_doc": "GARCH next-bar sigma vs realized → lot_factor (vol-targeting)", **out}
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    return out


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[VOLF] تنبؤ تقلّب GARCH حيّ — تحجيم اللوت بالتقلّب المتوقّع", flush=True)
    while True:
        try:
            o = cycle(mt5)
            tag = " · ".join(f"{s.replace('m','')}:{v['regime']}×{v['lot_factor']}"
                             for s, v in list(o.items())[:5])
            print(f"[VOLF] {tag or 'يجمع'}", flush=True)
        except Exception as e:
            print(f"[VOLF] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
