"""
r_trade_journal.py — الصندوق الأسود: كل صفقة حارس مشروحة في سجلّها نفسه.

لكل مركزٍ مغلق (magic 20260701 على XAUUSDm) يبني سجلّاً مكتفياً بذاته يجمع:
  • الدخول: تذكرة، اتجاه، سعر، لوت، وقت.
  • الخروج: سعر، صافٍ، R محقّقة، سبب الخروج المُستنتج (هدف/وقف/تعادل/جزئيّ).
  • القراءة الفنيّة على كل فريم وقت الدخول بالضبط (M1/M5/M15/H1):
        الترند (السعر↔EMA50↔EMA200)، RSI14، Stoch، ATR، آخر شمعة.
  • توافق الفريمات: كم فريماً وافق اتجاه الصفقة (بذرة حافّة مقيسة).

فنقدر نشرح كل ربح/خسارة بالأرقام. يملأ التاريخ رجعيّاً + يعمل للأمام.

تشغيل:  python r_trade_journal.py [--days N]   (افتراضي 5 أيام)
        python r_trade_journal.py --magic all      (كل الماجيكات لا الحارس فقط)
        python r_trade_journal.py --magic 99779    (ماجيك محدّد)
        python r_trade_journal.py --summary   (إحصاء بلا إعادة بناء)
"""
from __future__ import annotations
import sys
import json
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

import numpy as np
import MetaTrader5 as mt5

MAGIC = 20260701
SYM = "XAUUSDm"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "r_native" / "r_trade_journal.jsonl"

_TFS = [("M1", mt5.TIMEFRAME_M1, 60), ("M5", mt5.TIMEFRAME_M5, 300),
        ("M15", mt5.TIMEFRAME_M15, 900), ("H1", mt5.TIMEFRAME_H1, 3600)]


# ── مؤشّرات ──────────────────────────────────────────────────────
def _ema(a, p):
    a = np.asarray(a, float)
    if len(a) == 0:
        return a
    k = 2.0 / (p + 1.0)
    e = np.empty(len(a)); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _rsi(c, n=14):
    c = np.asarray(c, float)
    if len(c) < n + 1:
        return 50.0
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.mean(up[-n:]); ad = np.mean(dn[-n:])
    if ad == 0:
        return 100.0
    rs = au / ad
    return float(100.0 - 100.0 / (1.0 + rs))


def _stoch(h, l, c, kp=14, slow=3):
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float)
    n = len(c)
    if n < kp:
        return 50.0
    raw = np.full(n, 50.0)
    for i in range(kp - 1, n):
        hh = h[i - kp + 1:i + 1].max(); ll = l[i - kp + 1:i + 1].min()
        raw[i] = 100.0 * (c[i] - ll) / ((hh - ll) or 1e-9)
    return float(_ema(raw, slow)[-1])


def _atr(r, n=14):
    h = r["high"]; l = r["low"]; c = r["close"]
    if len(r) < 2:
        return 0.0
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(1, len(r))]
    return float(np.mean(trs[-n:])) if len(trs) >= n else float(np.mean(trs) if trs else 0.0)


def _candle(r):
    if r is None or len(r) < 1:
        return "—"
    o, h, l, c = (float(r[-1]["open"]), float(r[-1]["high"]),
                  float(r[-1]["low"]), float(r[-1]["close"]))
    rng = (h - l) or 1e-9
    body = abs(c - o); up = h - max(o, c); dn = min(o, c) - l
    if dn / rng >= 0.6 and body / rng <= 0.35:
        return "مطرقة/رفض-سفليّ"
    if up / rng >= 0.6 and body / rng <= 0.35:
        return "نجمة/رفض-علويّ"
    return "صعوديّة" if c > o else "هبوطيّة" if c < o else "دوجي"


# ── قراءة فريم واحد وقت الدخول بالضبط ─────────────────────────────
def _bars_before(sym, tf_const, tf_secs, at_epoch, count=220):
    """آخر `count` شمعة تنتهي عند/قبل لحظة الدخول (وقت الخادم ≈ UTC)."""
    frm = datetime.fromtimestamp(at_epoch - (count + 3) * tf_secs, tz=timezone.utc)
    to = datetime.fromtimestamp(at_epoch, tz=timezone.utc)
    try:
        r = mt5.copy_rates_range(sym, tf_const, frm, to)
    except Exception:
        r = None
    return r


def _tf_read(sym, tf_const, tf_secs, at_epoch, side):
    r = _bars_before(sym, tf_const, tf_secs, at_epoch)
    if r is None or len(r) < 20:
        return {"ok": False, "note": "لا بيانات كافية"}
    c = r["close"]; price = float(c[-1])
    e50 = float(_ema(c, 50)[-1]) if len(c) >= 50 else float(np.mean(c))
    e200 = float(_ema(c, 200)[-1]) if len(c) >= 200 else e50
    trend = "صاعد" if price > e50 > e200 else ("هابط" if price < e50 < e200 else "مختلط")
    rsi = _rsi(c); st = _stoch(r["high"], r["low"], c); atr = _atr(r)
    # هل وافق هذا الفريم اتجاه الصفقة؟ (buy يريد صاعد، sell يريد هابط)
    agree = (trend == "صاعد") if side == "BUY" else (trend == "هابط")
    return {"ok": True, "trend": trend, "rsi": round(rsi, 1), "stoch": round(st, 1),
            "atr": round(atr, 2), "ema50": round(e50, 2), "ema200": round(e200, 2),
            "price": round(price, 2), "candle": _candle(r),
            "agree_with_trade": bool(agree)}


def _multi_tf(sym, at_epoch, side):
    out = {}
    for name, tf, secs in _TFS:
        try:
            out[name] = _tf_read(sym, tf, secs, at_epoch, side)
        except Exception as e:
            out[name] = {"ok": False, "note": str(e)}
    agreed = [k for k, v in out.items() if v.get("ok") and v.get("agree_with_trade")]
    out["_agreement"] = {"agreed_frames": agreed, "n_agree": len(agreed),
                         "n_frames": sum(1 for v in out.values() if isinstance(v, dict) and v.get("ok"))}
    return out


def _exit_reason(side, entry, exitp, atr, net):
    """يستنتج سبب الخروج من إزاحة السعر بوحدات R (R≈1.3×ATR في الحارس)."""
    R = 1.3 * atr if atr > 0 else 1e-9
    move = (exitp - entry) if side == "BUY" else (entry - exitp)
    r_mult = move / R
    if r_mult >= 0.40:
        reason = "هدف/فوز (بلغ ≥0.4R)"
    elif r_mult <= -0.40:
        reason = "وقف/خسارة (بلغ ≤-0.4R)"
    elif -0.15 <= r_mult <= 0.15:
        reason = "تعادل/كشط (BE — الوقف نُقل للتعادل)"
    else:
        reason = "خروج جزئيّ/مختلط"
    return reason, round(r_mult, 2)


# ── إعادة بناء السجلّ من التاريخ ──────────────────────────────────
def build(days=5, magics=None):
    if not mt5.initialize():
        print("MT5 init فشل"); return []
    frm = datetime.now() - timedelta(days=days)
    to = datetime.now() + timedelta(hours=6)
    deals = mt5.history_deals_get(frm, to) or []
    rows = [d for d in deals if (magics is None and d.magic == MAGIC) or (magics == "all" and d.magic != 0) or (isinstance(magics, (list, set, tuple)) and d.magic in magics)]
    by_pos = {}
    for d in rows:
        by_pos.setdefault(d.position_id, []).append(d)

    records = []
    for pid, ds in by_pos.items():
        ds.sort(key=lambda x: x.time)
        ins = [d for d in ds if d.entry == 0]
        outs = [d for d in ds if d.entry == 1]
        if not ins or not outs:
            continue  # مركز لا يزال مفتوحاً
        e = ins[0]; x = outs[-1]
        side = "BUY" if e.type == 0 else "SELL"
        entry = float(e.price); exitp = float(x.price)
        net = sum(float(d.profit) + float(d.commission) + float(d.swap) for d in ds)
        dur_min = round((x.time - e.time) / 60.0, 1)
        mtf = _multi_tf(e.symbol, e.time, side)
        atr_m5 = mtf.get("M5", {}).get("atr", 0.0) or 0.0
        reason, r_mult = _exit_reason(side, entry, exitp, atr_m5, net)
        rec = {
            "position_id": pid,
            "magic": e.magic, "symbol": e.symbol, "side": side,
            "entry_ts": e.time,
            "entry_iso": datetime.fromtimestamp(e.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "entry_hour_utc": datetime.fromtimestamp(e.time, tz=timezone.utc).hour,
            "entry_price": round(entry, 2), "exit_price": round(exitp, 2),
            "lot": float(e.volume), "net_usd": round(net, 2),
            "win": net > 0, "r_realized": r_mult, "exit_reason": reason,
            "duration_min": dur_min,
            "tf_read": mtf,
            "explain": _explain(side, net, reason, r_mult, mtf, atr_m5),
        }
        records.append(rec)

    # 📎 دمج سياق الدخول الحيّ (سبريد/توافق/تبريد) إن سُجّل وقت التنفيذ
    ctx_f = ROOT / "data" / "r_native" / "gold_sentinel_entries.jsonl"
    ctx = {}
    if ctx_f.exists():
        for line in ctx_f.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(line)
                if c.get("ticket"):
                    ctx[int(c["ticket"])] = c
            except Exception:
                pass
    for r in records:
        c = ctx.get(int(r["position_id"]))
        if c:
            r["entry_context"] = {k: c[k] for k in
                ("spread", "score", "cooldown_eff_min", "conf_mult", "target_r_eff") if k in c}

    records.sort(key=lambda r: r["entry_ts"])
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return records


def _explain(side, net, reason, r_mult, mtf, atr):
    ag = mtf.get("_agreement", {})
    n_ag = ag.get("n_agree", 0); n_fr = ag.get("n_frames", 0)
    frames = "/".join(ag.get("agreed_frames", [])) or "لا شيء"
    verdict = "ربحت" if net > 0 else "خسرت"
    return (f"{side} {verdict} ${net:+.2f} ({r_mult:+.2f}R، {reason}). "
            f"توافق الفريمات وقت الدخول: {n_ag}/{n_fr} ({frames}). "
            f"ATR(M5)={atr:.2f}.")


# ── إحصاء ────────────────────────────────────────────────────────
def summary(records=None):
    if records is None:
        records = []
        if OUT.exists():
            for line in OUT.read_text(encoding="utf-8").splitlines():
                try: records.append(json.loads(line))
                except Exception: pass
    if not records:
        print("لا سجلّات."); return
    n = len(records); wins = [r for r in records if r["win"]]
    net = sum(r["net_usd"] for r in records)
    avg_w = np.mean([r["net_usd"] for r in wins]) if wins else 0.0
    losses = [r for r in records if not r["win"]]
    avg_l = np.mean([r["net_usd"] for r in losses]) if losses else 0.0
    magics_here = sorted({r.get("magic", MAGIC) for r in records})
    print(f"\n=== الصندوق الأسود — {n} صفقة عبر {len(magics_here)} ماجيك ===")
    if len(magics_here) > 1:
        from collections import defaultdict as _dd
        bym = _dd(lambda: [0, 0, 0.0])
        for r in records:
            m = r.get("magic"); bym[m][0] += 1; bym[m][1] += 1 if r["win"] else 0; bym[m][2] += r["net_usd"]
        print("--- لكل ماجيك ---")
        for m in sorted(bym, key=lambda x: -bym[x][2]):
            c2, w2, s2 = bym[m]
            print(f"  magic {m}: n={c2} WR {100*w2/c2:.0f}% صافٍ ${s2:+.2f}")
    print(f"WR {100*len(wins)/n:.1f}%  |  صافٍ ${net:.2f}  |  متوسّط فوز ${avg_w:.2f}  خسارة ${avg_l:.2f}"
          f"  |  RR {abs(avg_w/avg_l):.2f}:1" if avg_l else "")
    # حسب سبب الخروج
    from collections import Counter, defaultdict
    by_reason = defaultdict(lambda: [0, 0.0])
    for r in records:
        by_reason[r["exit_reason"]][0] += 1
        by_reason[r["exit_reason"]][1] += r["net_usd"]
    print("--- حسب سبب الخروج ---")
    for k, (cnt, s) in sorted(by_reason.items(), key=lambda kv: kv[1][1]):
        print(f"  {k:32} n={cnt:3}  صافٍ ${s:+.2f}")
    # حافّة توافق الفريمات: هل الصفقات عالية-التوافق تربح أكثر؟
    print("--- حافّة توافق الفريمات (n_agree → WR/صافٍ) ---")
    by_ag = defaultdict(lambda: [0, 0, 0.0])
    for r in records:
        a = r["tf_read"].get("_agreement", {}).get("n_agree", 0)
        by_ag[a][0] += 1; by_ag[a][1] += 1 if r["win"] else 0; by_ag[a][2] += r["net_usd"]
    for a in sorted(by_ag):
        cnt, w, s = by_ag[a]
        print(f"  {a} فريم موافق: n={cnt:3}  WR {100*w/cnt:5.1f}%  صافٍ ${s:+.2f}")
    # حسب الساعة (حافّة الانضباط النهاريّ)
    print("--- حسب ساعة الدخول UTC (ليل 22-08 = حافّة سالبة مثبتة) ---")
    by_h = defaultdict(lambda: [0, 0, 0.0])
    for r in records:
        h = r["entry_hour_utc"]; by_h[h][0] += 1; by_h[h][1] += 1 if r["win"] else 0; by_h[h][2] += r["net_usd"]
    night = [0, 0.0]; day = [0, 0.0]
    for h in sorted(by_h):
        cnt, w, s = by_h[h]
        tag = "🌙" if (h >= 22 or h < 8) else "☀️"
        if tag == "🌙": night[0] += cnt; night[1] += s
        else: day[0] += cnt; day[1] += s
    print(f"  ☀️ نهار (08-22): n={day[0]}  صافٍ ${day[1]:+.2f}")
    print(f"  🌙 ليل (22-08):  n={night[0]}  صافٍ ${night[1]:+.2f}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        days = 5
        if "--days" in sys.argv:
            try: days = int(sys.argv[sys.argv.index("--days") + 1])
            except Exception: pass
        magics = None
        if "--magic" in sys.argv:
            v = sys.argv[sys.argv.index("--magic") + 1]
            magics = "all" if v == "all" else [int(v)]
        recs = build(days, magics)
        print(f"بُني {len(recs)} سجلّ صفقة -> {OUT}")
        summary(recs)
