# -*- coding: utf-8 -*-
"""gold_deep_brain.py — عقل ذهب عميق ذاتي-التعلّم (قراءة فقط، windowless تحت الوصيّ).

يبني كل دورة (~20ث) ملفّاً عميقاً لـXAUUSDm (قابل للتوسعة لأي رمز): كل المؤشرات في كل
الفريمات (عبر chart_read) + الزخم + التذبذب + المستويات المفتاحية (دعم/مقاومة، عرض/طلب،
قمة/قاع اليوم والأسبوع، البايفوت، الأرقام المدوّرة) → bias + نداء عالي-الثقة (دخول/انتظار).

التعلّم الذاتي العميق: عند نداء عالي-الثقة يلتقط لقطة خصائص (قوّة المحاذاة، نظام التذبذب،
القرب من مستوى، نضارة/امتداد الزخم) ويحكم نتيجتها الأمامية (حركة السعر خلال أفق) → يراكم
توقّعاً لكل دلو-خصائص. فيتعلّم *أيّ* الإعدادات العميقة تسبق الربح فعلاً — بصدق، بلا ادّعاء
حافّة حتى يُثبت سجلّه (n + توقّع + معنوية). يكتب data/r_native/gold_deep_dossier.json +
gold_deep_learning.json. لا order_send — سياق وتعلّم فقط؛ المنفّذون/أنت تقرؤون الملفّ.
"""
from __future__ import annotations
import json, math, os, time
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

try:
    import chart_read as cr
    _HAVE_CR = hasattr(cr, "read_local")
except Exception:
    _HAVE_CR = False

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
DOSSIER_F = RN / "gold_deep_dossier.json"
LEARN_F = RN / "gold_deep_learning.json"
LOG_F = RN / "gold_deep_brain.log"

SYMS = ["XAUUSDm"]                       # قابل للتوسعة
TFS = [("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15), ("M30", mt5.TIMEFRAME_M30),
       ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4), ("D1", mt5.TIMEFRAME_D1)]
POLL_S = 20.0
JUDGE_TF = mt5.TIMEFRAME_M15             # الأفق يُقاس بشموع M15
JUDGE_HORIZON = 16                       # 16×M15 = 4 ساعات
HICONF = 0.62                            # عتبة "نداء عالي-الثقة" العميق (محاذاة + توافق)


def _jdefault(o):
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"not serializable: {type(o)}")


def _log(m):
    try:
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _ema(a, n):
    k = 2.0 / (n + 1); e = a[0]
    for x in a[1:]:
        e += k * (x - e)
    return e


def _rsi(c, n=14):
    d = np.diff(c)
    up = np.clip(d, 0, None)[-n:].mean(); dn = (-np.clip(d, None, 0))[-n:].mean()
    return 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return tr[-n:].mean(), tr


def _bars(sym, tf, n=200):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 60:
        return None
    return (np.array([x["open"] for x in r]), np.array([x["high"] for x in r]),
            np.array([x["low"] for x in r]), np.array([x["close"] for x in r]))


def _tf_read(sym, tfname, tf):
    o, h, l, c = _bars(sym, tf) or (None, None, None, None)
    if c is None:
        return None
    conf = 0.0; dr = 0
    if _HAVE_CR:
        try:
            d = cr.read_local(mt5, sym, tfname)
            conf = float(d.get("confluence") or d.get("conf") or 0); dr = int(d.get("dir") or 0)
        except Exception:
            pass
    if dr == 0:                                       # احتياط: اتجاه EMA50
        dr = 1 if c[-1] > _ema(c, 50) else -1
    atr, trs = _atr(h, l, c)
    roc = (c[-1] / c[-11] - 1.0) * 100.0 if len(c) > 11 else 0.0
    rsi = _rsi(c)
    hi = h[-50:].max(); lo = l[-50:].min(); pos = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
    # نظام التذبذب: مئوية ATR الحالية ضمن آخر 100
    atr_series = np.array([trs[i - 14:i].mean() for i in range(14, len(trs))]) if len(trs) > 28 else np.array([atr])
    atr_pct = float((atr_series[-100:] < atr).mean()) if len(atr_series) else 0.5
    return {"dir": dr, "conf": round(conf, 3), "roc": round(roc, 3), "rsi": round(rsi, 1),
            "pos": round(pos, 3), "atr": round(float(atr), 3), "atr_pct": round(atr_pct, 2),
            "close": float(c[-1])}


def _levels(sym):
    """مستويات مفتاحية: سوينغ + قمة/قاع اليوم والأسبوع + بايفوت + أرقام مدوّرة."""
    out = {}
    b1 = _bars(sym, mt5.TIMEFRAME_D1, 30)
    if b1:
        o, h, l, c = b1
        out["prev_day_high"] = round(float(h[-2]), 2); out["prev_day_low"] = round(float(l[-2]), 2)
        ph, pl, pc = h[-2], l[-2], c[-2]
        piv = (ph + pl + pc) / 3.0
        out["pivot"] = round(float(piv), 2)
        out["R1"] = round(float(2 * piv - pl), 2); out["S1"] = round(float(2 * piv - ph), 2)
        out["R2"] = round(float(piv + (ph - pl)), 2); out["S2"] = round(float(piv - (ph - pl)), 2)
    bw = _bars(sym, mt5.TIMEFRAME_W1, 12)
    if bw:
        o, h, l, c = bw
        out["prev_week_high"] = round(float(h[-2]), 2); out["prev_week_low"] = round(float(l[-2]), 2)
    bm = _bars(sym, mt5.TIMEFRAME_M30, 200)
    if bm:
        o, h, l, c = bm
        # سوينغ بسيط: أعلى/أدنى محلّي
        sw_hi = [float(h[i]) for i in range(2, len(h) - 2) if h[i] == max(h[i - 2:i + 3])][-4:]
        sw_lo = [float(l[i]) for i in range(2, len(l) - 2) if l[i] == min(l[i - 2:i + 3])][-4:]
        out["swing_highs"] = [round(x, 2) for x in sorted(set(sw_hi))[-4:]]
        out["swing_lows"] = [round(x, 2) for x in sorted(set(sw_lo))[:4]]
        px = float(c[-1])
        out["round_above"] = round(math.ceil(px / 25.0) * 25.0, 2)
        out["round_below"] = round(math.floor(px / 25.0) * 25.0, 2)
    return out


def _nearest(price, levels, atr):
    """أقرب مستوى فوق/تحت + المسافة بـATR."""
    vals = []
    for k, v in levels.items():
        if isinstance(v, (int, float)):
            vals.append((k, v))
        elif isinstance(v, list):
            for x in v:
                vals.append((k, x))
    above = sorted([(k, v) for k, v in vals if v > price], key=lambda x: x[1])
    below = sorted([(k, v) for k, v in vals if v < price], key=lambda x: -x[1])
    na = above[0] if above else None
    nb = below[0] if below else None
    d_above = (na[1] - price) / atr if (na and atr) else None
    d_below = (price - nb[1]) / atr if (nb and atr) else None
    return na, d_above, nb, d_below


def _synth(sym, read, levels):
    tfs = [t for t in read.values() if t]
    if not tfs:
        return None
    dirs = [t["dir"] for t in tfs]
    net = sum(dirs); n_tf = len(dirs)
    wconf = np.mean([t["conf"] for t in tfs]) if tfs else 0
    align = abs(net) / n_tf                            # 0..1 محاذاة الفريمات
    bias = "صعود" if net > 0 else "هبوط" if net < 0 else "محايد"
    px = tfs[0]["close"]
    h1 = read.get("H1") or tfs[0]; atr_h1 = h1["atr"]
    na, da, nb, db = _nearest(px, levels, atr_h1)
    # نضارة/امتداد الزخم: RSI متطرّف + بعيد عن وسط المدى = ممتدّ
    rsi_h1 = h1["rsi"]; pos_h1 = h1["pos"]
    extended = (rsi_h1 > 72 or rsi_h1 < 28) or (pos_h1 > 0.92 or pos_h1 < 0.08)
    # نداء عالي الثقة: محاذاة قوية + توافق عالٍ + زخم غير ممتدّ عكسياً
    score = 0.5 * align + 0.5 * min(1.0, wconf / 0.75)
    hi = score >= HICONF and align >= 0.66
    call = "قف" if not hi else ("بيع قوي" if net < 0 else "شراء قوي")
    if hi and extended:
        call += " (لكن الزخم ممتدّ — انتظر ارتداداً)"
    feat = {"align_b": ("strong" if align >= 0.85 else "med" if align >= 0.6 else "weak"),
            "vol_b": ("hi" if h1["atr_pct"] >= 0.66 else "lo" if h1["atr_pct"] <= 0.33 else "mid"),
            "near_b": ("yes" if (db is not None and db <= 0.6) or (da is not None and da <= 0.6) else "no"),
            "mom_b": ("extended" if extended else "fresh")}
    return {"sym": sym, "ts": time.time(), "price": round(px, 2), "bias": bias,
            "net_tf": net, "n_tf": n_tf, "align": round(align, 2), "confluence": round(float(wconf), 3),
            "score": round(score, 3), "high_conf": hi, "call": call, "extended": extended,
            "nearest_above": na, "dist_above_atr": round(da, 2) if da is not None else None,
            "nearest_below": nb, "dist_below_atr": round(db, 2) if db is not None else None,
            "features": feat, "per_tf": read, "levels": levels}


# ------------- التعلّم الذاتي العميق (سبورة ظلّية على الخصائص) -------------
def _load_learn():
    if LEARN_F.exists():
        try:
            return json.load(open(LEARN_F, encoding="utf-8-sig"))
        except Exception:
            pass
    return {"pending": [], "buckets": {}, "pooled": {"n": 0, "sumR": 0.0, "wins": 0}}


def _save_learn(d):
    try:
        json.dump(d, open(LEARN_F, "w", encoding="utf-8"), ensure_ascii=False, default=_jdefault)
    except Exception:
        pass


def _judge(sym, dossier, learn):
    """يسجّل النداءات عالية-الثقة ويحكم نتيجتها الأمامية → توقّع لكل دلو-خصائص."""
    now = time.time()
    # سجّل نداءً جديداً (مرّة لكل اتجاه/سعر، تفادي التكرار خلال 15د)
    if dossier and dossier["high_conf"] and "قف" not in dossier["call"] and "انتظر" not in dossier["call"]:
        d = 1 if dossier["net_tf"] > 0 else -1
        recent = [p for p in learn["pending"] if p["sym"] == sym and now - p["ts"] < 900 and p["dir"] == d]
        if not recent:
            learn["pending"].append({"sym": sym, "ts": now, "dir": d, "entry": dossier["price"],
                                     "feat": dossier["features"], "atr": dossier["per_tf"].get("H1", {}).get("atr", 1.0)})
    # احكم الناضجة
    b = _bars(sym, JUDGE_TF, JUDGE_HORIZON + 5)
    px = float(b[3][-1]) if b else None
    keep = []
    for p in learn["pending"]:
        if p["sym"] != sym:
            keep.append(p); continue
        if now - p["ts"] < JUDGE_HORIZON * 15 * 60:     # لم تنضج بعد
            keep.append(p); continue
        if px is None:
            keep.append(p); continue
        r = (px - p["entry"]) * p["dir"] / max(p["atr"], 1e-9)   # نتيجة بـATR
        learn["pooled"]["n"] += 1; learn["pooled"]["sumR"] += round(r, 3)
        learn["pooled"]["wins"] += int(r > 0)
        for k, v in p["feat"].items():
            key = f"{k}={v}"
            bk = learn["buckets"].setdefault(key, {"n": 0, "sumR": 0.0, "wins": 0})
            bk["n"] += 1; bk["sumR"] += round(r, 3); bk["wins"] += int(r > 0)
    learn["pending"] = keep
    return learn


def _learn_summary(learn):
    p = learn["pooled"]; n = p["n"]; e = p["sumR"] / n if n else 0
    t = e * math.sqrt(n) if n else 0
    buckets = {}
    for k, b in learn["buckets"].items():
        bn = b["n"]; be = b["sumR"] / bn if bn else 0
        buckets[k] = {"n": bn, "expR": round(be, 3), "t": round(be * math.sqrt(bn), 2) if bn else 0,
                      "win": round(b["wins"] / bn * 100, 0) if bn else 0}
    best = sorted(buckets.items(), key=lambda kv: -kv[1]["expR"])[:5]
    return {"pooled_n": n, "pooled_expR": round(e, 4), "pooled_t": round(t, 2),
            "verdict": ("🟢 مرشّح" if t > 2 and e > 0 else "⏳ يتعلّم/لا حافّة بعد"),
            "best_conditions": dict(best), "all_conditions": buckets}


def main():
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    RN.mkdir(parents=True, exist_ok=True)
    _log(f"gold_deep_brain start (chart_read={_HAVE_CR})")
    while True:
        try:
            learn = _load_learn()
            out = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "symbols": {}}
            for sym in SYMS:
                read = {name: _tf_read(sym, name, tf) for name, tf in TFS}
                levels = _levels(sym)
                doss = _synth(sym, read, levels)
                if doss:
                    learn = _judge(sym, doss, learn)
                    doss["learning"] = _learn_summary(learn)
                    out["symbols"][sym] = doss
            _save_learn(learn)
            json.dump(out, open(DOSSIER_F, "w", encoding="utf-8"), ensure_ascii=False, default=_jdefault)
        except Exception as e:
            _log(f"loop error: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
