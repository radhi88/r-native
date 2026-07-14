"""
boundary_hunter.py — صيّاد اللحظات: يتعلّم بشراسة على كل افتتاح وقبيل كل خبر.

أمر المستخدم (2026-07-14): «كل بداية ساعة/يوم/أسبوع/شهر/4س/30د/15د وقبل الخبر
بخمس دقائق — لازم يتعلّم عليها. نستغلّ كل لحظات الأسواق، نهجم هجوماً شرساً.»

العقيدة: الهجوم الشرس على **التعلّم** أولاً — كل لحظة حدودية تُرصد وتُقاس نتيجتها
(انفجار؟ اتجاه؟ كم ATR؟) عبر كل الرموز. التنفيذ يأتي حين يثبت النمط رقميّاً
(نفس بوّابة الأمانة: n≥30 و|t|≥2) — عندها يظهر في maturity_status كمرشّح بناء.
(ذاكرة المشروع: ركوب الانفجار الأعمى NO_EDGE؛ الخبر يستمرّ 58-71% = خيط حقيقيّ.)

اللحظات المرصودة لكل رمز:
  M15/M30/H1/H4/D1/W1/MN1 عند الافتتاح (أول 90 ثانية) + PRE_NEWS (خبر High بعد 3-7د).

يكتب: boundary_sweep.jsonl (الأحداث) + boundary_knowledge.json (نمط→نتيجة بأمانة)
      + boundary_hunter_status.json (نبض). قراءة فقط — لا أوامر إطلاقاً.
"""
from __future__ import annotations
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

ROOT = Path(__file__).resolve().parent
RN = ROOT / "data" / "r_native"
SWEEP_F = RN / "boundary_sweep.jsonl"
KNOW_F = RN / "boundary_knowledge.json"
STATUS_F = RN / "boundary_hunter_status.json"
NEWS_F = ROOT / "friday_v3" / "data" / "news_calendar.json"

SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
           "USDCADm", "USDCHFm", "EURJPYm", "GBPJPYm", "ETHUSDm", "US30m"]
BOUNDARIES = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400,
              "D1": 86400, "W1": 604800, "MN1": 2592000}
HORIZONS_MIN = (15, 30)          # نقيس الانفجار بعد 15 و30 دقيقة
POLL_S = 20
MIN_N, MIN_T = 30, 2.0           # بوّابة الأمانة نفسها


def _ema(x, n):
    x = np.asarray(x, float)
    if not len(x):
        return x
    k = 2.0 / (n + 1.0)
    e = np.empty(len(x)); e[0] = x[0]
    for i in range(1, len(x)):
        e[i] = x[i] * k + e[i - 1] * (1 - k)
    return e


def _atr14_m5(sym):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 20)
    if r is None or len(r) < 15:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(1, len(r))]
    return float(np.mean(trs[-14:]))


def _news_soon():
    """أخبار High خلال 3-7 دقائق (يدعم صيغتي التقويم: ISO أو حقول منفصلة)."""
    try:
        events = json.loads(NEWS_F.read_text(encoding="utf-8"))
        if isinstance(events, dict):
            events = events.get("events", [])
    except Exception:
        return []
    out = []
    now = datetime.now(timezone.utc)
    for ev in events:
        if str(ev.get("impact", "")).lower() not in ("high", "3"):
            continue
        t = None
        for k in ("time_utc", "datetime", "date", "time"):
            v = ev.get(k)
            if not v:
                continue
            try:
                t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                break
            except Exception:
                continue
        if t is None:
            continue
        dt_min = (t - now).total_seconds() / 60.0
        if 3.0 <= dt_min <= 7.0:
            out.append({"title": str(ev.get("title", ev.get("event", "?")))[:60],
                        "currency": ev.get("currency", "?"), "in_min": round(dt_min, 1)})
    return out


def _detect_boundaries(now_epoch):
    """أي حدودٍ فُتحت للتوّ؟ (أول 90 ثانية من الفترة، بتوقيت UTC)."""
    hits = []
    for name, secs in BOUNDARIES.items():
        if name == "MN1":
            d = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
            if d.day == 1 and d.hour == 0 and d.minute < 2:
                hits.append(name)
            continue
        if name == "W1":
            d = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
            if d.weekday() == 0 and d.hour == 0 and d.minute < 2:  # افتتاح الاثنين
                hits.append(name)
            continue
        if now_epoch % secs < 90:
            hits.append(name)
    return hits


def _snapshot(sym, boundary, extra=None):
    ti = mt5.symbol_info_tick(sym)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 25)
    if not ti or r is None or len(r) < 21:
        return None
    c = r["close"]
    atr = _atr14_m5(sym)
    if atr <= 0:
        return None
    e20 = float(_ema(c, 20)[-1])
    mom = "up" if float(c[-1]) > e20 else "down"
    prior = "bull" if float(r[-2]["close"]) > float(r[-2]["open"]) else "bear"
    return {"ts": time.time(), "iso": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": sym, "boundary": boundary, "price": float((ti.bid + ti.ask) / 2),
            "spread": round(float(ti.ask - ti.bid), 5), "atr": round(atr, 5),
            "momentum": mom, "prior_candle": prior, "resolved": False,
            **({"news": extra} if extra else {})}


def _resolve(snaps):
    """يحسم اللقطات التي مضى أفقها: الحركة والانفجار بوحدات ATR."""
    now = time.time()
    changed = 0
    for s in snaps:
        if s.get("resolved") or now - s["ts"] < HORIZONS_MIN[-1] * 60 + 60:
            continue
        frm = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
        to = datetime.fromtimestamp(s["ts"] + HORIZONS_MIN[-1] * 60 + 120, tz=timezone.utc)
        try:
            r = mt5.copy_rates_range(s["symbol"], mt5.TIMEFRAME_M1, frm, to)
        except Exception:
            r = None
        if r is None or len(r) < HORIZONS_MIN[0]:
            s["resolved"] = True; s["ok"] = False; changed += 1
            continue
        p0, atr = s["price"], s["atr"]
        for hm in HORIZONS_MIN:
            seg = r[:hm]
            if not len(seg):
                continue
            move = (float(seg[-1]["close"]) - p0) / atr
            burst = (float(seg["high"].max()) - float(seg["low"].min())) / atr
            s[f"move_{hm}m_atr"] = round(move, 2)
            s[f"burst_{hm}m_atr"] = round(burst, 2)
            # مع الزخم السابق أم ضدّه؟ (هذا ما نتعلّمه: هل الافتتاح يواصل أم يعكس)
            sgn = 1.0 if s["momentum"] == "up" else -1.0
            s[f"with_mom_{hm}m"] = round(sgn * move, 2)
        s["resolved"] = True; s["ok"] = True; changed += 1
    return changed


def _rebuild_knowledge(snaps):
    """نمط→نتيجة: key = boundary|symbol|momentum ؛ بأمانة n/t/trust."""
    agg = {}
    for s in snaps:
        if not (s.get("resolved") and s.get("ok")):
            continue
        key = f"{s['boundary']}|{s['symbol']}|{s['momentum']}"
        a = agg.setdefault(key, {"n": 0, "sum": 0.0, "sumsq": 0.0,
                                 "burst_sum": 0.0, "spread_sum": 0.0})
        v = s.get(f"with_mom_{HORIZONS_MIN[0]}m")
        if v is None:
            continue
        a["n"] += 1; a["sum"] += v; a["sumsq"] += v * v
        a["burst_sum"] += s.get(f"burst_{HORIZONS_MIN[0]}m_atr", 0)
        a["spread_sum"] += s.get("spread", 0)
    know = {}
    for key, a in agg.items():
        n = a["n"]
        if n == 0:
            continue
        mean = a["sum"] / n
        var = max(0.0, a["sumsq"] / n - mean * mean)
        t = mean / math.sqrt(var / n) if var > 0 and n > 1 else 0.0
        trust = ("SIGNIFICANT" if n >= MIN_N and abs(t) >= MIN_T
                 else "COLLECTING" if n < MIN_N else "NOISE")
        know[key] = {"n": n, "mean_with_mom_atr": round(mean, 3),
                     "t_stat": round(t, 2), "avg_burst_atr": round(a["burst_sum"] / n, 2),
                     "avg_spread": round(a["spread_sum"] / n, 5), "trust": trust}
    know["_meta"] = {"updated": datetime.now(timezone.utc).isoformat(),
                     "gate": f"SIGNIFICANT = n>={MIN_N} & |t|>={MIN_T}",
                     "reading": "mean_with_mom_atr>0 = الافتتاح يُواصل مع الزخم؛ <0 = يعكسه",
                     "horizon_min": HORIZONS_MIN[0]}
    return know


def _load_snaps():
    out = []
    try:
        for line in SWEEP_F.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _save_snaps(snaps):
    keep = [s for s in snaps if not s.get("resolved")] + \
           [s for s in snaps if s.get("resolved")][-4000:]
    with open(SWEEP_F, "w", encoding="utf-8") as f:
        for s in keep:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def main():
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print("🗡️ boundary_hunter بدأ — كل الافتتاحات + قبيل الأخبار، 12 رمزاً")
    snaps = _load_snaps()
    seen = set()          # (boundary, symbol, period_start) لمنع التكرار
    cycles = 0
    while True:
        try:
            now = time.time()
            hits = _detect_boundaries(now)
            news = _news_soon()
            new_snaps = 0
            for sym in SYMBOLS:
                for b in hits:
                    period = int(now // BOUNDARIES[b])
                    kk = (b, sym, period)
                    if kk in seen:
                        continue
                    seen.add(kk)
                    s = _snapshot(sym, b)
                    if s:
                        snaps.append(s); new_snaps += 1
                if news:
                    kk = ("PRE_NEWS", sym, int(now // 300))
                    if kk not in seen:
                        seen.add(kk)
                        s = _snapshot(sym, "PRE_NEWS", extra=news[0])
                        if s:
                            snaps.append(s); new_snaps += 1
            resolved = _resolve(snaps)
            if new_snaps or resolved or cycles % 15 == 0:
                _save_snaps(snaps)
                know = _rebuild_knowledge(snaps)
                KNOW_F.write_text(json.dumps(know, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            if len(seen) > 20000:
                seen = set(list(seen)[-5000:])
            cycles += 1
            json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                       "cycles": cycles, "events_total": len(snaps),
                       "unresolved": sum(1 for s in snaps if not s.get("resolved")),
                       "news_watch": news},
                      open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
