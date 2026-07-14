"""tape_recorder.py — الشريط المسجّل: يحفظ كل ثانية لقطة قرار كاملة لكل رمز جلسة، فنعيد الاختبار
بعيداً ("ماذا لو فعلنا كذا") كأنه شريط فيديو مسجّل للسوق + عقل النظام.

كل لقطة تسجّل: السعر/السبريد/ATR · الجلسة · كل أصوات المؤشرات الـ42 وأوزانها · الاتجاه الموحّد
والتوافق · ماكرو/دلتا/نظام-Hurst · المناطق القريبة · بطولة/أخبار · **وعتاد الهجومية**: كم طبقة
اتفقت (_agree) ومضاعف اللوت (surge) ومتى يصير هجومياً على الشموع · ومركزنا الحالي.
→ data/r_native/tape/YYYY-MM-DD.jsonl (شريط يومي). tape_replay.py يعيد عليه أي فرضية.

صادق: نسجّل القرار + السعر + الطابع الزمني فقط؛ نتيجة "ماذا لو" تُحسب لاحقاً من أسعار MT5 الفعلية
عند تلك اللحظات (سبريد حقيقي) — لا افتراض. Windowless.  Run:  pythonw tape_recorder.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
V2 = MT5DIR / "r_native_v2" / "data"
TAPE = RN / "tape"
POLL_S = 60
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _atr(r, n=14):
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n if tr else 0.0


def snapshot(mt5, sym, cr, mt):
    """لقطة قرار كاملة لرمز — نفس مدخلات المتداول الحيّة."""
    tick = mt5.symbol_info_tick(sym)
    if not tick or not tick.bid:
        return None
    cfg = mt._genomes().get(sym, {})
    cdir, conf = mt._macro(cr, mt5, sym)
    cg = float(cfg.get("conf_gate", 0.6))
    r = mt5.copy_rates_from_pos(sym, mt._tf(mt5, cfg.get("tf", "M15")), 0, 30)
    atr = _atr(r) if r is not None and len(r) > 15 else 0.0
    spread = (tick.ask - tick.bid)
    # عتاد الهجومية: كم طبقة تتفق (نفس منطق CONVICTION SURGE في multi_trader)
    tt = mt._tournament_tilt().get(sym, 0)
    mb = mt._macro_bias(sym)
    dlt = mt._delta_bias(sym)
    agree = 1
    if conf >= cg + 0.10:
        agree += 1
    if tt and tt == cdir:
        agree += 1
    if dlt is not None and ((dlt > 15 and cdir > 0) or (dlt < -15 and cdir < 0)):
        agree += 1
    if mb and (mb > 0) == (cdir > 0) and cdir != 0:
        agree += 1
    surge = {1: 1.0, 2: 1.4, 3: 1.9, 4: 2.3, 5: 2.5}.get(min(5, agree), 1.0)
    # الأصوات الكاملة (42 مؤشّراً)
    d = cr.read_local(mt5, sym, cfg.get("tf", "M15")) or {}
    votes = d.get("votes", {})
    # المناطق القريبة
    zm = (_load(RN / "zone_memory.json", {}) or {}).get(sym, {}).get("zones", [])
    mid = (tick.bid + tick.ask) / 2
    znear = next(({"px": z["px"], "net": z["net"], "t": z["touches"]}
                  for z in zm if z.get("touches", 0) >= 3 and abs(z["px"] - mid) <= 0.5 * atr), None)
    # مركزنا الحالي على الرمز
    pos = [p for p in (mt5.positions_get(symbol=sym) or [])
           if p.magic in (20260608, 20260613)]
    return {
        "ts": time.time(), "sym": sym, "session": mt._session_now(),
        "bid": tick.bid, "ask": tick.ask, "spread": round(spread, 6),
        "spread_atr": round(spread / atr, 3) if atr > 0 else None, "atr": round(atr, 6),
        "dir": cdir, "conf": round(conf, 3), "gate": cg,
        "macro_bias": mb, "delta": dlt, "tourn": tt,
        "regime": d.get("regime"), "confluence": d.get("confluence"), "net": d.get("net"),
        "agree": agree, "surge": surge, "aggressive": surge >= 1.9,
        "votes": {k: int(v) for k, v in votes.items()},
        "zone_near": znear, "open_pos": len(pos),
        "would_enter": bool(cdir != 0 and conf >= cg),   # هل كان سيدخل بالقواعد الحالية
    }


def main():
    import MetaTrader5 as mt5
    import chart_read as cr
    import multi_trader as mt
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    TAPE.mkdir(parents=True, exist_ok=True)
    print("[TAPE] الشريط المسجّل حيّ — يحفظ كل قرار وسياقه لإعادة الاختبار", flush=True)
    while True:
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            fpath = TAPE / f"{day}.jsonl"
            roster = list(mt._genomes())
            n = 0
            with open(fpath, "a", encoding="utf-8") as f:
                for sym in roster:
                    try:
                        snap = snapshot(mt5, sym, cr, mt)
                        if snap:
                            f.write(json.dumps(snap, ensure_ascii=False) + "\n"); n += 1
                    except Exception:
                        pass
            agg = 0
            try:
                # عدّ اللقطات الهجومية الأخيرة (للوحة)
                pass
            except Exception:
                pass
            print(f"[TAPE] سجّلت {n} لقطة · جلسة {mt._session_now()}", flush=True)
        except Exception as e:
            print(f"[TAPE] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
