# -*- coding: utf-8 -*-
"""deep_brain.py — العقل العميق: نظام التعلّم الذاتي الأقوى لـ*كل* العملات السائلة.

(قراءة فقط، windowless تحت الوصيّ — لا order_send. سياق + تعلّم؛ المنفّذون/المستخدم يقرؤون الملفّ.)

يتشرّب كل رمز بالتناوب: كل المؤشرات في كل الفريمات (عبر chart_read) + الزخم + التذبذب +
المستويات + الجلسة + اتجاه HTF + نظام RSI → bias + نداء عالي-الثقة *انتقائي*. ويتعلّم ذاتياً
عميقاً عبر سبورة ظلّية على:
  • خصائص مفردة (محاذاة/تذبذب/قرب-مستوى/زخم/جلسة/مع-أو-ضد الاتجاه/RSI)
  • تركيبات الخصائص الكاملة (combo) — هنا تختبئ الحافّة الحقيقية (تفاعل الشروط)
  • لكل رمز ولكل اتجاه (شراء/بيع منفصلان)
بصدق علميّ صارم: t حقيقي بالانحراف المعياري (لا افتراض σ=1R)، ونطاق ثقة 95%، و"مرشّح مُثبت"
يتطلّب تصحيح Bonferroni (يمنع ظهور حافّة وهمية من كثرة الخلايا المُختبَرة). يحفظ منحنى تعلّم.
يكتب data/r_native/deep_dossier.json + deep_learning.json.
"""
from __future__ import annotations
import json, math, time
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

try:
    import chart_read as cr
    _HAVE_CR = hasattr(cr, "read_local")
except Exception:
    _HAVE_CR = False

try:
    import gold_micro as gm                    # مؤشرات الذهب اللحظية (tick/M1)
    _HAVE_GM = True
except Exception:
    _HAVE_GM = False

try:
    import novel_indicators as ni             # 🆕 مؤشرات مُبتكَرة (بنية السوق/قابلية التنبّؤ)
    _HAVE_NI = True
except Exception:
    _HAVE_NI = False

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
DOSSIER_F = RN / "deep_dossier.json"
LEARN_F = RN / "deep_learning.json"
REAL_RULES_F = RN / "real_rules.json"     # قواعد من صفقات حقيقية منفّذة (صافي التكلفة)
LOG_F = RN / "deep_brain.log"
_RR_CACHE = {"t": 0.0, "v": {"vetoes": [], "favors": []}}


def _load_real_rules():
    now = time.time()
    if now - _RR_CACHE["t"] < 60 and _RR_CACHE["v"]:
        return _RR_CACHE["v"]
    try:
        v = json.load(open(REAL_RULES_F, encoding="utf-8-sig"))
    except Exception:
        v = {"vetoes": [], "favors": []}
    _RR_CACHE.update(t=now, v=v)
    return v

TFS = [("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15), ("M30", mt5.TIMEFRAME_M30),
       ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4), ("D1", mt5.TIMEFRAME_D1)]
POLL_S = 5.0                             # دورة أسرع (كان 15) — استجابة أعلى
PER_CYCLE = 8
JUDGE_TF = mt5.TIMEFRAME_M15
JUDGE_HORIZON = 16                       # 16×M15 = 4 ساعات (الأفق البطيء)
# 🕐 آفاق متعددة (بالدقائق): يُحكَم على كل إشارة عند كل أفق → التعلّم يظهر خلال دقائق لا ساعات
HORIZONS = [("fast", 15), ("mid", 60), ("slow", 240)]
HORIZON_LABELS = {"fast": "15 دقيقة", "mid": "ساعة", "slow": "4 ساعات"}
GOLD = "XAUUSDm"                          # أولوية: يُقرأ كل دورة + مسار سريع
# الرموز التي تحصل على المؤشرات اللحظية (tick/M1): الذهب + الكريبتو (BTC/ETH 24/7 — مفتوح بالعطلة)
MICRO_SYMS = {GOLD, "BTCUSDm", "ETHUSDm"}
PRIORITY_SYMS = [GOLD, "BTCUSDm", "ETHUSDm"]   # تُقرأ كل دورة (مفتوحة غالباً + بؤرة التعلّم)
HICONF = 0.68                            # عتبة ثقة انتقائية (رُفعت 0.62→0.68)
HI_ALIGN = 0.75                          # يتطلّب محاذاة قوية عبر الفريمات
HI_MAX = 8                               # أقصى نداءات عالية-الثقة معروضة (الأقوى فقط — لا صراخ)
PROVEN_MIN_N = 25                        # أدنى عيّنة للمرشّح المُثبت
PROVEN_ALPHA = 0.05                      # مستوى دلالة (بعد Bonferroni)

# عالم سائل قابل للتداول فقط — لا أزواج EM غريبة عالية السبريد (ضجيج + تكلفة قاتلة)
BASE_SYMS = ["XAUUSDm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "NZDUSDm",
             "USDCHFm", "EURJPYm", "GBPJPYm", "EURGBPm", "AUDJPYm", "EURAUDm", "GBPAUDm", "CADJPYm",
             "CHFJPYm", "NZDJPYm", "EURCHFm", "GBPCHFm", "AUDNZDm", "AUDCADm", "EURCADm", "GBPCADm",
             "BTCUSDm", "ETHUSDm", "SOLUSDm", "BNBUSDm", "XRPUSDm",
             "US30m", "US500m", "USTECm", "GER40m", "UK100m", "JP225m", "USOILm", "UKOILm"]
# عملات تسعير غير سائلة/عالية السبريد — تُستبعَد من التوسعة التلقائية
ILLIQUID_QUOTES = ("TRY", "ZAR", "PLN", "NOK", "SEK", "MXN", "THB", "CNH", "HUF",
                   "CZK", "DKK", "SGD", "HKD", "RUB", "ILS", "CLP", "COP")


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


def _liquid(s):
    return not any(s[3:6] == q or s.endswith(q + "m") for q in ILLIQUID_QUOTES)


def _load_syms():
    syms = list(BASE_SYMS)
    try:
        univ = json.loads((RN / "market_watch_symbols.json").read_text(encoding="utf-8"))
        for s in univ:
            if s in syms or not _liquid(s):
                continue
            if any(s.startswith(p) for p in ("EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF",
                                             "XAU", "XAG", "BTC", "ETH")):
                syms.append(s)
    except Exception:
        pass
    out = []
    for s in syms:
        info = mt5.symbol_info(s)
        if info is None:
            try:
                mt5.symbol_select(s, True); info = mt5.symbol_info(s)
            except Exception:
                pass
        if info is not None:
            out.append(s)
    return out[:48]


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
    b = _bars(sym, tf)
    if b is None:
        return None
    o, h, l, c = b
    conf = 0.0; dr = 0
    if _HAVE_CR:
        try:
            d = cr.read_local(mt5, sym, tfname)
            conf = float(d.get("confluence") or d.get("conf") or 0); dr = int(d.get("dir") or 0)
        except Exception:
            pass
    if dr == 0:
        dr = 1 if c[-1] > _ema(c, 50) else -1
    atr, trs = _atr(h, l, c)
    roc = float((c[-1] / c[-11] - 1.0) * 100.0) if len(c) > 11 else 0.0
    rsi = float(_rsi(c))
    hi = h[-50:].max(); lo = l[-50:].min(); pos = float((c[-1] - lo) / (hi - lo)) if hi > lo else 0.5
    atr_series = np.array([trs[i - 14:i].mean() for i in range(14, len(trs))]) if len(trs) > 28 else np.array([atr])
    atr_pct = float((atr_series[-100:] < atr).mean()) if len(atr_series) else 0.5
    return {"dir": int(dr), "conf": round(conf, 3), "roc": round(roc, 3), "rsi": round(rsi, 1),
            "pos": round(pos, 3), "atr": round(float(atr), 5), "atr_pct": round(atr_pct, 2),
            "close": float(c[-1])}


def _levels(sym):
    out = {}
    b1 = _bars(sym, mt5.TIMEFRAME_D1, 30)
    if b1:
        o, h, l, c = b1
        out["prev_day_high"] = round(float(h[-2]), 5); out["prev_day_low"] = round(float(l[-2]), 5)
        ph, pl, pc = h[-2], l[-2], c[-2]; piv = (ph + pl + pc) / 3.0
        out["pivot"] = round(float(piv), 5)
        out["R1"] = round(float(2 * piv - pl), 5); out["S1"] = round(float(2 * piv - ph), 5)
        out["R2"] = round(float(piv + (ph - pl)), 5); out["S2"] = round(float(piv - (ph - pl)), 5)
    bw = _bars(sym, mt5.TIMEFRAME_W1, 12)
    if bw:
        o, h, l, c = bw
        out["prev_week_high"] = round(float(h[-2]), 5); out["prev_week_low"] = round(float(l[-2]), 5)
    bm = _bars(sym, mt5.TIMEFRAME_M30, 200)
    if bm:
        o, h, l, c = bm
        sw_hi = [float(h[i]) for i in range(2, len(h) - 2) if h[i] == max(h[i - 2:i + 3])][-4:]
        sw_lo = [float(l[i]) for i in range(2, len(l) - 2) if l[i] == min(l[i - 2:i + 3])][-4:]
        out["swing_highs"] = [round(x, 5) for x in sorted(set(sw_hi))[-4:]]
        out["swing_lows"] = [round(x, 5) for x in sorted(set(sw_lo))[:4]]
    return out


def _nearest(price, levels, atr):
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
    da = (na[1] - price) / atr if (na and atr) else None
    db = (price - nb[1]) / atr if (nb and atr) else None
    return na, da, nb, db


def _session():
    hr = time.gmtime().tm_hour
    if 0 <= hr < 7:
        return "asia"
    if 7 <= hr < 12:
        return "london"
    if 12 <= hr < 21:
        return "ny"
    return "off"


def _synth(sym, read, levels):
    tfs = [t for t in read.values() if t]
    if not tfs:
        return None
    dirs = [t["dir"] for t in tfs]
    net = int(sum(dirs)); n_tf = len(dirs)
    wconf = float(np.mean([t["conf"] for t in tfs])) if tfs else 0.0
    align = abs(net) / n_tf
    bias = "صعود" if net > 0 else "هبوط" if net < 0 else "محايد"
    px = tfs[0]["close"]
    h1 = read.get("H1") or tfs[0]; atr_h1 = h1["atr"]
    h4 = read.get("H4") or h1
    na, da, nb, db = _nearest(px, levels, atr_h1)
    rsi_h1 = h1["rsi"]; pos_h1 = h1["pos"]
    extended = bool((rsi_h1 > 72 or rsi_h1 < 28) or (pos_h1 > 0.92 or pos_h1 < 0.08))
    d = 1 if net > 0 else -1 if net < 0 else 0
    with_htf = bool(d != 0 and (h4["dir"] == d or h4["dir"] == 0))
    score = float(0.5 * align + 0.5 * min(1.0, wconf / 0.75))
    # ثقة عالية انتقائية: قوة المحاذاة + موافقة الاتجاه الأعلى + غير ممتدّ
    hi = bool(score >= HICONF and align >= HI_ALIGN and with_htf and not extended)
    call = "قف" if not hi else ("بيع قوي" if net < 0 else "شراء قوي")
    rsi_b = "ob" if rsi_h1 > 70 else "os" if rsi_h1 < 30 else "neutral"
    feat = {"align_b": ("strong" if align >= 0.85 else "med" if align >= 0.6 else "weak"),
            "vol_b": ("hi" if h1["atr_pct"] >= 0.66 else "lo" if h1["atr_pct"] <= 0.33 else "mid"),
            "near_b": ("yes" if (db is not None and db <= 0.6) or (da is not None and da <= 0.6) else "no"),
            "mom_b": ("extended" if extended else "fresh"),
            "sess_b": _session(),
            "trend_b": ("with" if with_htf else "against"),
            "rsi_b": rsi_b}
    gsignal = None
    if _HAVE_GM and sym in MICRO_SYMS:           # 🥇 مؤشرات لحظية (tick/M1) للذهب + الكريبتو — تُتعلَّم وتُحكَم مجاناً
        try:
            gmf = gm.gold_micro_features(sym)
            feat.update(gmf)
            gsignal = gm.gold_micro_signal(gmf)
        except Exception:
            pass
    if _HAVE_NI:                                 # 🆕 مؤشرات مُبتكَرة (بنية/قابلية تنبّؤ) لكل الرموز — تُتعلَّم وتُحكَم
        try:
            feat.update(ni.novel_features(sym))
        except Exception:
            pass
    return {"sym": sym, "ts": time.time(), "price": round(px, 5), "bias": bias, "gsignal": gsignal,
            "net_tf": net, "n_tf": n_tf, "align": round(align, 2), "confluence": round(wconf, 3),
            "score": round(score, 3), "high_conf": hi, "call": call, "extended": extended,
            "with_htf": with_htf, "session": feat["sess_b"], "rsi_h1": round(rsi_h1, 1),
            "nearest_above": na, "dist_above_atr": round(da, 2) if da is not None else None,
            "nearest_below": nb, "dist_below_atr": round(db, 2) if db is not None else None,
            "features": feat, "per_tf": read, "levels": levels}


def _new_tree():
    return {"pooled": {"n": 0, "sumR": 0.0, "sumR2": 0.0, "wins": 0}, "buckets": {}, "combos": {},
            "by_symbol": {}, "by_symdir": {}, "by_session": {}, "session_cond": {}, "history": []}


def _load_learn():
    if LEARN_F.exists():
        try:
            d = json.load(open(LEARN_F, encoding="utf-8-sig"))
            d.setdefault("pending", []); d.setdefault("judged_total", 0); d.setdefault("trees", {})
            for hn, _ in HORIZONS:
                d["trees"].setdefault(hn, _new_tree())
            return d
        except Exception:
            pass
    return {"pending": [], "trees": {hn: _new_tree() for hn, _ in HORIZONS}, "judged_total": 0}


def _save_learn(d):
    try:
        json.dump(d, open(LEARN_F, "w", encoding="utf-8"), ensure_ascii=False, default=_jdefault)
    except Exception:
        pass


def _accum(store, key, r):
    b = store.setdefault(key, {"n": 0, "sumR": 0.0, "sumR2": 0.0, "wins": 0})
    b["n"] += 1; b["sumR"] += r; b["sumR2"] += r * r; b["wins"] += int(r > 0)


def _accum_tree(tree, sym, d, feat, r):
    pl = tree["pooled"]; pl["n"] += 1; pl["sumR"] += r; pl["sumR2"] += r * r; pl["wins"] += int(r > 0)
    _accum(tree["by_symbol"], sym, r)
    _accum(tree["by_symdir"], f"{sym}:{'BUY' if d > 0 else 'SELL'}", r)
    for k, v in feat.items():
        _accum(tree["buckets"], f"{k}={v}", r)
    _accum(tree["combos"], "|".join(f"{k}={feat[k]}" for k in sorted(feat)), r)
    _sess = feat.get("sess_b", "?")
    _accum(tree["by_session"], _sess, r)
    for k, v in feat.items():
        if k != "sess_b":
            _accum(tree["session_cond"], f"{_sess}|{k}={v}", r)


def _judge(sym, doss, learn):
    """يُسجّل الإشارة عالية-الثقة، ويحكم على المعلّقات عند *كل* أفق (15د/ساعة/4س) بسعر التيك اللحظي.
    فالأفق السريع يملأ التعلّم خلال دقائق؛ والبطيء يبقى الحُكم الأعمق."""
    now = time.time()
    if doss and doss["high_conf"] and "قف" not in doss["call"]:
        d = 1 if doss["net_tf"] > 0 else -1
        recent = [p for p in learn["pending"] if p["sym"] == sym and now - p["ts"] < 600 and p["dir"] == d]
        if not recent:
            learn["pending"].append({"sym": sym, "ts": now, "dir": d, "entry": doss["price"],
                                     "feat": doss["features"],
                                     "atr": doss["per_tf"].get("H1", {}).get("atr", 1.0), "done": []})
    t = mt5.symbol_info_tick(sym)
    px = float((t.bid + t.ask) / 2.0) if t else None
    keep = []
    for p in learn["pending"]:
        if p["sym"] != sym or px is None:
            keep.append(p); continue
        p.setdefault("done", [])
        el_min = (now - p["ts"]) / 60.0
        for hn, hmin in HORIZONS:
            if hn in p["done"] or el_min < hmin:
                continue
            r = round((px - p["entry"]) * p["dir"] / max(p["atr"], 1e-9), 3)
            _accum_tree(learn["trees"][hn], sym, p["dir"], p["feat"], r)
            p["done"].append(hn)
            if hn == HORIZONS[-1][0]:
                learn["judged_total"] += 1
        if len(p["done"]) < len(HORIZONS):
            keep.append(p)
    learn["pending"] = keep
    return learn


def _bstat(b):
    n = b.get("n", 0)
    if not n:
        return {"n": 0, "expR": 0, "t": 0, "win": 0, "ci_lo": 0, "ci_hi": 0}
    mean = b["sumR"] / n
    var = max(b.get("sumR2", 0.0) / n - mean * mean, 0.0)
    std = math.sqrt(var)
    se = (std / math.sqrt(n)) if (n > 1 and std > 0) else (1.0 / math.sqrt(n))
    t = mean / se if se > 0 else 0.0
    ci = 1.96 * se
    return {"n": n, "expR": round(mean, 3), "std": round(std, 3), "t": round(t, 2),
            "ci_lo": round(mean - ci, 3), "ci_hi": round(mean + ci, 3),
            "win": round(b["wins"] / n * 100, 0)}


def _p_two(t):
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0))))


def _summarize_tree(tree):
    pooled = _bstat(tree["pooled"]); n = pooled["n"]
    conds = {k: _bstat(b) for k, b in tree["buckets"].items()}
    combos = {k: _bstat(b) for k, b in tree["combos"].items() if b["n"] >= 8}
    syms = {k: _bstat(b) for k, b in tree["by_symbol"].items()}
    symdir = {k: _bstat(b) for k, b in tree["by_symdir"].items()}
    cand = {**{f"cond:{a}": b for a, b in conds.items()},
            **{f"combo:{a}": b for a, b in combos.items()},
            **{f"sym:{a}": b for a, b in syms.items()},
            **{f"symdir:{a}": b for a, b in symdir.items()}}
    n_tests = max(len(cand), 1)
    proven = {k: v for k, v in cand.items()
              if v["n"] >= PROVEN_MIN_N and v["expR"] > 0 and _p_two(v["t"]) * n_tests < PROVEN_ALPHA}
    sessions = {}
    for sess in ("london", "ny", "asia", "off"):
        b = tree["by_session"].get(sess)
        if not b:
            continue
        st = _bstat(b)
        sc = {k.split("|", 1)[1]: _bstat(v) for k, v in tree["session_cond"].items()
              if k.startswith(sess + "|") and v["n"] >= 5}
        st["top_conditions"] = dict(sorted(sc.items(), key=lambda kv: -kv[1]["t"])[:4])
        st["verdict"] = ("🟢 مُثبت" if (st["n"] >= PROVEN_MIN_N and st["expR"] > 0
                                        and _p_two(st["t"]) * n_tests < PROVEN_ALPHA)
                         else "➕ موجب (غير مؤكَّد)" if st["expR"] > 0 else "➖ سالب")
        sessions[sess] = st
    return {"pooled_n": n, "pooled_expR": pooled["expR"], "pooled_t": pooled["t"], "sessions": sessions,
            "pooled_win": pooled["win"], "pooled_ci_lo": pooled["ci_lo"], "pooled_ci_hi": pooled["ci_hi"],
            "n_tests": n_tests, "n_conditions": len(conds), "n_combos": len(combos),
            "verdict": ("🟢 مرشّح مُثبت" if proven else "⏳ يتعلّم — لا حافّة معنوية بعد"),
            "proven": dict(sorted(proven.items(), key=lambda kv: -kv[1]["t"])),
            "best_conditions": dict(sorted(conds.items(), key=lambda kv: -kv[1]["t"])[:8]),
            "best_combos": dict(sorted(combos.items(), key=lambda kv: -kv[1]["t"])[:6]),
            "by_symbol": dict(sorted(syms.items(), key=lambda kv: -kv[1]["t"])[:10]),
            "history": tree.get("history", [])[-120:]}


def _learn_summary(learn):
    horizons = {hn: _summarize_tree(learn["trees"][hn]) for hn, _ in HORIZONS}
    fast = horizons[HORIZONS[0][0]]                      # المستوى الأعلى = الأفق السريع (يملأ خلال دقائق)
    return {**fast, "horizons": horizons, "horizon_labels": HORIZON_LABELS,
            "judged_total": learn.get("judged_total", 0), "pending": len(learn.get("pending", []))}


def _conviction(sym, d, feat, learn):
    """جسر القناعة: يحوّل التعلّم المُثبت إلى قوّة دخول. مدفوع بالشروط الدالّة فقط
    (Bonferroni=قوي، معنوي |t|>2=ناعم) المطابِقة للخصائص الحاليّة واتجاه الإشارة عبر كل الآفاق.
    1.0=محايد · >1 ثقة أعلى (ادخل أقوى/أكبر) · <1 تحفّظ/فيتو-تعلّمي. fail-open (خطأ ⇒ 1.0)."""
    if d == 0:
        return {"mult": 1.0, "tier": "محايد", "pos": 0.0, "neg": 0.0, "hits": []}
    side = "BUY" if d > 0 else "SELL"
    pos = 0.0; neg = 0.0; hits = []
    try:
        for hn, _ in HORIZONS:
            tr = learn["trees"][hn]
            n_tests = max(len(tr["buckets"]) + len(tr["by_symdir"]) + len(tr["combos"]), 1)
            checks = [(f"{k}={v}", tr["buckets"].get(f"{k}={v}")) for k, v in feat.items()]
            checks.append((f"{sym}:{side}", tr["by_symdir"].get(f"{sym}:{side}")))
            sess = feat.get("sess_b")
            if sess:
                for k, v in feat.items():
                    if k != "sess_b":
                        checks.append((f"{sess}|{k}={v}", tr["session_cond"].get(f"{sess}|{k}={v}")))
            for key, b in checks:
                if not b or b["n"] < PROVEN_MIN_N:
                    continue
                st = _bstat(b)
                if abs(st["t"]) <= 2.0:
                    continue
                bonf = _p_two(st["t"]) * n_tests < PROVEN_ALPHA
                w = 1.0 if bonf else 0.4
                if st["expR"] > 0:
                    pos += w; hits.append({"h": hn, "k": key, "s": "+", "expR": st["expR"], "t": st["t"], "n": st["n"], "bonf": bonf})
                else:
                    neg += w; hits.append({"h": hn, "k": key, "s": "-", "expR": st["expR"], "t": st["t"], "n": st["n"], "bonf": bonf})
        # 💰 قواعد من صفقات حقيقية منفّذة (صافي السبريد) — وزن أعلى لأنها الاختبار الحقيقي
        rr = _load_real_rules()
        rkeys = {f"{k}={v}" for k, v in feat.items()}          # كل الخصائص الـ14 (أساسية + غنيّة)
        rkeys |= {f"{feat.get('sess_b')}|rsi={feat.get('rsi_b')}", f"sym={sym}", f"symdir={sym}:{side}"}
        for r in rr.get("vetoes", []):
            if r.get("key") in rkeys:
                w = 2.2 if r.get("bonf") else 0.8
                neg += w; hits.append({"h": "حقيقي", "k": r["key"], "s": "-", "expR": r.get("net"),
                                       "t": r.get("t"), "n": r.get("n"), "bonf": r.get("bonf", False), "real": True})
        for r in rr.get("favors", []):
            k = r.get("key", "")
            # 🚫 تجنّب أثر-الريجيم في الأضواء الخضراء: تفضيلات الرمز-الواحد (sym=/symdir=) خادعة — مثل
            # BTC +$22 = كله SELL في هبوطٍ واحد، يفشل train/test (حذّر منه تحقيق الحافّة). نقبل للضوء
            # الأخضر فقط الشروط الواسعة (جلسة/RSI) الأمتن. (الفيتوهات تبقى كلها — الحجب آمن حتى لو ناقصاً.)
            if k in rkeys and not (k.startswith("sym=") or k.startswith("symdir=")):
                w = 2.2 if r.get("bonf") else 0.8
                pos += w; hits.append({"h": "حقيقي", "k": k, "s": "+", "expR": r.get("net"),
                                       "t": r.get("t"), "n": r.get("n"), "bonf": r.get("bonf", False), "real": True})
        mult = max(0.4, min(2.0, 1.0 + 0.16 * pos - 0.28 * neg))
        real_veto = any(h.get("real") and h.get("bonf") and h["s"] == "-" for h in hits)
        real_green = any(h.get("real") and h.get("bonf") and h["s"] == "+" for h in hits)
        tier = ("🔴 فيتو حقيقي (صافي مُثبت)" if real_veto
                else "🟢 ضوء أخضر حقيقي" if (real_green and mult >= 1.2)
                else "🟢 ضوء أخضر مُثبت" if (mult >= 1.3 and any(h.get("bonf") and h["s"] == "+" for h in hits))
                else "➕ مائل موجب" if mult > 1.05
                else "🔴 فيتو تعلّمي" if mult < 0.75 else "محايد")
        hits = sorted(hits, key=lambda h: (-int(bool(h.get("real"))), -abs(h.get("t") or 0)))[:5]
    except Exception:
        return {"mult": 1.0, "tier": "محايد", "pos": 0.0, "neg": 0.0, "hits": [], "real_veto": False}
    return {"mult": round(mult, 2), "tier": tier, "pos": round(pos, 1), "neg": round(neg, 1),
            "real_veto": real_veto, "hits": hits}


def main():
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    RN.mkdir(parents=True, exist_ok=True)
    syms = _load_syms()
    _log(f"deep_brain start: {len(syms)} رمز سائل · chart_read={_HAVE_CR}")
    state = {}
    idx = 0
    last_hist_n = {}
    while True:
        try:
            if not syms:
                syms = _load_syms()
            batch = syms[idx:idx + PER_CYCLE] or syms[:PER_CYCLE]
            idx = (idx + PER_CYCLE) % max(1, len(syms))
            for _ps in PRIORITY_SYMS:                     # 🥇 أولوية: الذهب + الكريبتو يُقرآن كل دورة
                if _ps in syms and _ps not in batch:
                    batch = [_ps] + batch
            learn = _load_learn()
            for sym in batch:
                try:
                    read = {name: _tf_read(sym, name, tf) for name, tf in TFS}
                    doss = _synth(sym, read, _levels(sym))
                    if doss:
                        learn = _judge(sym, doss, learn)
                        state[sym] = doss
                except Exception as e:
                    _log(f"{sym} err: {type(e).__name__}: {e}")
            # منحنى تعلّم لكل أفق: لقطة عند تغيّر عيّنته المُحكَّمة
            for hn, _ in HORIZONS:
                tr = learn["trees"][hn]; pn = tr["pooled"]["n"]
                if pn != last_hist_n.get(hn):
                    ps = _bstat(tr["pooled"])
                    tr["history"].append([round(time.time(), 0), pn, ps["expR"], ps["t"]])
                    tr["history"] = tr["history"][-300:]
                    last_hist_n[hn] = pn
            _save_learn(learn)
            summ = _learn_summary(learn)
            # 🧲 جسر القناعة: التعلّم المُثبت → قوّة دخول لكل رمز + أضواء خضراء (ادخل بقوّة) / فيتو
            green, red = [], []
            for s, dd in state.items():
                _d = 1 if dd["net_tf"] > 0 else -1 if dd["net_tf"] < 0 else 0
                cv = _conviction(s, _d, dd.get("features", {}), learn)
                dd["conviction"] = cv
                if cv["mult"] >= 1.3:
                    green.append({"sym": s, "bias": dd["bias"], "mult": cv["mult"], "call": dd["call"], "tier": cv["tier"]})
                elif cv["mult"] <= 0.7:
                    red.append({"sym": s, "bias": dd["bias"], "mult": cv["mult"], "tier": cv["tier"]})
            green.sort(key=lambda x: -x["mult"]); red.sort(key=lambda x: x["mult"])
            # نداءات عالية-الثقة: الأقوى فقط (top-N حسب score) — لا صراخ على عشرات الرموز
            hicands = sorted([d for d in state.values() if d.get("high_conf")],
                             key=lambda d: -d["score"])[:HI_MAX]
            hi = {d["sym"]: {"bias": d["bias"], "call": d["call"], "align": d["align"],
                             "score": d["score"], "session": d["session"], "with_htf": d["with_htf"]}
                  for d in hicands}
            g = state.get(GOLD) or {}
            _gf = g.get("features", {})
            gold_live = {"signal": g.get("gsignal"), "bias": g.get("bias"), "score": g.get("score"),
                         "call": g.get("call"), "price": g.get("price"), "rsi_h1": g.get("rsi_h1"),
                         "micro": {k: _gf.get(k) for k in ("spread_b", "tickimb_b", "rvol_b",
                                   "vwapdev_b", "round_b", "struct_b", "orpos_b")}}
            out = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_symbols": len(state),
                   "high_conf_now": hi, "learning": summ, "gold_live": gold_live,
                   "green_lights": green, "red_flags": red, "symbols": state}
            json.dump(out, open(DOSSIER_F, "w", encoding="utf-8"), ensure_ascii=False, default=_jdefault)
        except Exception as e:
            _log(f"loop error: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
