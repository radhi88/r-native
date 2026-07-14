# -*- coding: utf-8 -*-
"""trade_autopsy.py — 🔎 تشريح كل صفقة مُغلقة لمحرّكاتنا (طلب راضي: «كل ما ضرب وقف نراجع ليه خسرنا —
دخولٌ خاطئ أم لامس تأمين ربح؟ نفرّق. وإذا ضرب هدفاً نحلّل ونسجّل ونكرّر»).

لكل صفقةٍ تُغلَق (magic لنا)، يُعيد بناء **أقصى ربحٍ عابر (MFE)** و**أقصى خسارةٍ عابرة (MAE)** من شمعات
M1 بين الدخول والخروج (÷ATR الدخول)، فيصنّف السبب الحقيقيّ:
  • هدف/ربح  → win: يسجّل سياق الفوز (نكرّره).
  • أعاد ربحاً → كان MFE≥0.5R ثمّ خسر ⇒ **مشكلة خروج/تأمين** لا دخول.
  • تأمين ضعيف → MFE بين 0.2 و0.5R.
  • دخولٌ خاطئ → MFE<0.2R (لم ينجح قطّ) ⇒ **مشكلة دخول**.
يُجمّع لكل محرّك: كم % خسائرنا «دخول خاطئ» مقابل «أعاد ربحاً» — يجيب سؤالك الجوهريّ (الخلل بالدخول أم الخروج؟).

قراءةٌ فقط، لا يتاجر. يكتب trade_autopsy.jsonl + autopsy_summary.json (يقرؤه المخّ/المعرفة). windowless.
Run: pythonw trade_autopsy.py
"""
from __future__ import annotations
import sys, os, json, time
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "trade_autopsy.out.log"
JL = RN / "trade_autopsy.jsonl"
SUM = RN / "autopsy_summary.json"
SEEN_F = RN / "trade_autopsy_seen.json"
POLL_S = 30

try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8"); sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import numpy as np
import MetaTrader5 as mt5
try:
    import engine_lock
except Exception:
    engine_lock = None

OURS = {20260701: "الحارس", 20260706: "R Core", 20260707: "قنّاص المجلس",
        20260709: "حارس العملات", 20260703: "محاكي راضي", 20260600: "الديسك", 20260631: "يوتيوب"}


def _atr_at(sym, at_unix, n=14):
    """ATR(M5) عند وقت الدخول (سببيّ: شمعات ≤ الدخول)."""
    r = mt5.copy_rates_from(sym, mt5.TIMEFRAME_M5, int(at_unix), n + 5)
    if r is None or len(r) < n + 1:
        return None
    r = [x for x in r if x["time"] <= at_unix]
    if len(r) < n + 1:
        return None
    h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
    c = np.array([x["close"] for x in r], float)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def _mfe_mae(sym, is_buy, entry, t0, t1, atr):
    """أقصى ربح/خسارة عابرة بين الدخول والخروج (÷ATR) من شمعات M1."""
    r = mt5.copy_rates_from(sym, mt5.TIMEFRAME_M1, int(t0), int((t1 - t0) / 60) + 3)
    if r is None or len(r) < 1 or atr <= 0:
        return (None, None)
    seg = [x for x in r if t0 <= x["time"] <= t1 + 60]
    if not seg:
        return (None, None)
    hi = max(float(x["high"]) for x in seg); lo = min(float(x["low"]) for x in seg)
    if is_buy:
        mfe = (hi - entry) / atr; mae = (entry - lo) / atr
    else:
        mfe = (entry - lo) / atr; mae = (hi - entry) / atr
    return (round(mfe, 2), round(mae, 2))


def _classify(net, mfe):
    """يصنّف السبب — يفرّق بين خطأ الدخول وإعادة الربح (جوهر سؤال المستخدم)."""
    if net > 0:
        return ("هدف/ربح", "win")
    if mfe is None:
        return ("خسارة (تعذّر التشريح)", "loss_unknown")
    if mfe >= 0.5:
        return ("أعاد ربحاً — خلل خروج/تأمين", "gave_back")
    if mfe >= 0.2:
        return ("تأمين ضعيف — خرج قبل الهدف", "weak_protection")
    return ("دخولٌ خاطئ — لم ينجح قطّ", "wrong_entry")


def _load_seen():
    try:
        return set(json.load(open(SEEN_F, encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(s):
    try:
        json.dump(sorted(s)[-4000:], open(SEEN_F, "w", encoding="utf-8"))
    except Exception:
        pass


def cycle(seen):
    now = time.time()
    deals = mt5.history_deals_get(int(now - 3 * 86400), int(now)) or []
    # اجمع دخولاً/خروجاً لكل position_id لمحرّكاتنا
    pos = {}
    for d in deals:
        if d.magic not in OURS:
            continue
        p = pos.setdefault(d.position_id, {"in": None, "out": None, "net": 0.0})
        if d.entry == 0:
            p["in"] = d
        elif d.entry == 1:
            p["out"] = d; p["net"] += d.profit + d.commission + d.swap
    new = 0
    for pid, p in pos.items():
        if p["in"] is None or p["out"] is None or str(pid) in seen:
            continue
        din, dout = p["in"], p["out"]
        atr = _atr_at(din.symbol, din.time)
        is_buy = (din.type == 0)
        mfe, mae = _mfe_mae(din.symbol, is_buy, din.price, din.time, dout.time, atr or 1e9) if atr else (None, None)
        label, cls = _classify(p["net"], mfe)
        rec = {"ts": now, "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "ticket": pid,
               "magic": din.magic, "engine": OURS.get(din.magic, str(din.magic)),
               "symbol": din.symbol, "dir": ("شراء" if is_buy else "بيع"),
               "net": round(p["net"], 2), "mfe_r": mfe, "mae_r": mae,
               "hold_min": round((dout.time - din.time) / 60.0, 1), "class": cls, "label": label}
        try:
            with open(JL, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
        seen.add(str(pid)); new += 1
        print(f"🔎 {rec['engine']} {din.symbol} {rec['dir']} net={rec['net']:+.2f} MFE={mfe}R ⇒ {label}", flush=True)
    if new:
        _save_seen(seen)
    _summarize()
    return new


def _summarize():
    """يجمّع التشريح: لكل محرّك، توزيع الأسباب — يجيب «الخلل بالدخول أم الخروج؟»."""
    agg = {}
    try:
        for ln in JL.read_text(encoding="utf-8").splitlines()[-2000:]:
            r = json.loads(ln)
            e = agg.setdefault(r["engine"], {"n": 0, "win": 0, "gave_back": 0, "wrong_entry": 0,
                                             "weak_protection": 0, "net": 0.0})
            e["n"] += 1; e["net"] += r.get("net", 0)
            c = r.get("class", "")
            if c in e:
                e[c] += 1
            elif c == "win":
                e["win"] += 1
    except Exception:
        pass
    for e in agg.values():
        losses = e["gave_back"] + e["wrong_entry"] + e["weak_protection"]
        e["net"] = round(e["net"], 1)
        e["loss_from_entry_pct"] = round(e["wrong_entry"] / losses * 100) if losses else 0
        e["loss_from_exit_pct"] = round((e["gave_back"] + e["weak_protection"]) / losses * 100) if losses else 0
    verdict = "لا صفقات كافية بعد"
    tot_we = sum(e["wrong_entry"] for e in agg.values())
    tot_gb = sum(e["gave_back"] + e["weak_protection"] for e in agg.values())
    if tot_we + tot_gb >= 8:
        verdict = ("الخلل الأكبر: **الخروج/التأمين** (نعيد ربحاً) ⇒ شدّ إدارة الخروج."
                   if tot_gb > tot_we else
                   "الخلل الأكبر: **الدخول** (لا ينجح قطّ) ⇒ راجع شروط الدخول/التوافق.")
    out = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engines": agg,
           "wrong_entry_total": tot_we, "gave_back_total": tot_gb, "verdict": verdict,
           "honesty": "MFE مُعادٌ بناؤه من شمعات M1؛ «أعاد ربحاً» = كان MFE≥0.5R ثمّ خسر = خلل خروج لا دخول."}
    tmp = SUM.with_suffix(".tmp"); tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, SUM)


def main():
    if engine_lock:
        try:
            engine_lock.claim("trade_autopsy")
        except Exception:
            pass
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🔎 مشرّح الصفقات بدأ — poll={POLL_S}s (يفرّق: دخولٌ خاطئ أم إعادة ربح؟)", flush=True)
    seen = _load_seen()
    while True:
        try:
            cycle(seen)
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
