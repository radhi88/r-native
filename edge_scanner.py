# -*- coding: utf-8 -*-
"""edge_scanner.py — 🔬 ماسح الحافّة لكل رمز ولكل فريم (طلب راضي «أفضل المؤشّرات والتحليلات لكل
عملة ولكل فريم»). يقيس **بصدق** (walk-forward، بعد الكلفة) هل لأيّ مؤشّرٍ حافّةٌ تنبّؤيّة على كل
رمز/فريم، ويسجّل الأفضل (إن وُجد) في edge_scan.json — يقرؤه منمّي المعرفة ويكتبه معرفةً.

المؤشّرات المقيسة: RSI (عكس-تطرّف)، Stochastic (عكس-تطرّف)، EMA9/21 (زخم-عبور)، MACD (عبور)،
Bollinger (عكس-حدّ). لكلٍّ إشارةٌ معياريّة (غير مُلائَمة للبيانات ⇒ لا إفراط)، تُقاس عائديّتها على H
شمعة بوحدة R (÷ATR) بعد خصم السبريد، على العيّنة الكاملة وعلى أحدث 30% (استقرار). verdict: حافّة
فقط إن t>2 وexp>0 على الأحدث؛ وإلا ضجيج. ⚖️ الصدق: الأغلب «لا حافّة» (يموت OOS)؛ ما يصمد يُعلَّم.

قراءةٌ فقط، لا يتاجر. windowless، مسجّل بالوصيّ. Run: pythonw edge_scanner.py
"""
from __future__ import annotations
import sys, os, json, time
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "edge_scanner.out.log"
OUT = RN / "edge_scan.json"
STATUS_F = RN / "edge_scanner_status.json"
POLL_S = 1800     # كل 30 دقيقة (حسابٌ ثقيل؛ الحافّة لا تتغيّر بالدقائق)

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

# رموزٌ سائلة ممثّلة لكل الفئات (يُقاس عليها؛ قابلة للتوسّع)
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "BTCUSDm",
           "ETHUSDm", "US500m", "US30m", "USOILm", "XAGUSDm"]
TFS = [("M5", 5), ("M15", 15), ("H1", 60)]
HOLD = {"M5": 6, "M15": 4, "H1": 3}     # شمعات الاحتفاظ لكل فريم
POINT_GUESS = {"XAUUSDm": 0.001, "XAGUSDm": 0.001}


def _ema(a, p):
    k = 2.0 / (p + 1.0); e = np.empty(len(a)); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _rsi(c, p=14):
    d = np.diff(c, prepend=c[0]); g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
    ag = np.full(len(c), np.nan); al = np.full(len(c), np.nan)
    if len(c) > p:
        ag[p] = g[1:p + 1].mean(); al[p] = l[1:p + 1].mean()
        for i in range(p + 1, len(c)):
            ag[i] = (ag[i - 1] * (p - 1) + g[i]) / p; al[i] = (al[i - 1] * (p - 1) + l[i]) / p
    return 100 - 100 / (1 + ag / (al + 1e-9))


def _stoch(h, l, c, k=14, sm=3):
    n = len(c); raw = np.full(n, 50.0)
    for i in range(k - 1, n):
        hh = h[i - k + 1:i + 1].max(); ll = l[i - k + 1:i + 1].min()
        raw[i] = 100 * (c[i] - ll) / ((hh - ll) or 1e-9)
    return _ema(raw, sm)


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    for i in range(n, len(c)):
        out[i] = tr[i - n:i].mean()
    return out


def _signals(o, h, l, c):
    """يرجع dict{اسم المؤشّر: مصفوفة اتّجاه سببيّ لكل شمعة (+1 شراء/-1 بيع/0 لا شيء، عند إغلاق i)}."""
    n = len(c); rsi = _rsi(c); stk = _stoch(h, l, c); e9 = _ema(c, 9); e21 = _ema(c, 21)
    ml = _ema(c, 12) - _ema(c, 26); sig = _ema(ml, 9)
    # ⚠️ سببيّ صارم: متوسّطٌ متأخّرٌ 20 (كان convolve mode="same" مركزيّاً ⇒ تسريبٌ مستقبليّ زيّف حافّة Bollinger)
    sma20 = np.array([c[max(0, i - 19):i + 1].mean() for i in range(n)]); sd = np.array([c[max(0, i - 19):i + 1].std() for i in range(n)])
    out = {"RSI عكس": np.zeros(n), "Stoch عكس": np.zeros(n), "EMA9/21 زخم": np.zeros(n),
           "MACD عبور": np.zeros(n), "Bollinger عكس": np.zeros(n)}
    for i in range(30, n):
        if rsi[i] <= 30: out["RSI عكس"][i] = 1
        elif rsi[i] >= 70: out["RSI عكس"][i] = -1
        if stk[i] <= 20: out["Stoch عكس"][i] = 1
        elif stk[i] >= 80: out["Stoch عكس"][i] = -1
        if e9[i] > e21[i] and e9[i - 1] <= e21[i - 1]: out["EMA9/21 زخم"][i] = 1
        elif e9[i] < e21[i] and e9[i - 1] >= e21[i - 1]: out["EMA9/21 زخم"][i] = -1
        if ml[i] > sig[i] and ml[i - 1] <= sig[i - 1]: out["MACD عبور"][i] = 1
        elif ml[i] < sig[i] and ml[i - 1] >= sig[i - 1]: out["MACD عبور"][i] = -1
        if c[i] < sma20[i] - 2 * sd[i]: out["Bollinger عكس"][i] = 1
        elif c[i] > sma20[i] + 2 * sd[i]: out["Bollinger عكس"][i] = -1
    return out


def _measure(o, h, l, c, atr, sig, hold, spread_price):
    """عائديّة الإشارة على hold شمعة بوحدة R (÷ATR) بعد الكلفة. يرجع (n, exp_full, exp_oos, t_oos)."""
    n = len(c); cut = int(n * 0.70); rs = []
    idx = np.where(sig != 0)[0]
    for i in idx:
        if i + hold >= n or np.isnan(atr[i]) or atr[i] <= 0:
            continue
        d = sig[i]; entry = o[i + 1] if i + 1 < n else c[i]
        ex = c[min(i + hold, n - 1)]
        r = ((ex - entry) * d - spread_price) / atr[i]
        rs.append((i, r))
    if len(rs) < 15:
        return (len(rs), None, None, None)
    full = np.array([r for _, r in rs])
    oos = np.array([r for i, r in rs if i >= cut])
    exp_full = float(full.mean())
    exp_oos = float(oos.mean()) if len(oos) >= 8 else None
    t_oos = float((oos.mean() / (oos.std() + 1e-9)) * np.sqrt(len(oos))) if len(oos) >= 8 else None
    return (len(rs), round(exp_full, 4), (round(exp_oos, 4) if exp_oos is not None else None),
            (round(t_oos, 2) if t_oos is not None else None))


def scan():
    res = {}; best_count = 0
    for sym in SYMBOLS:
        si = mt5.symbol_info(sym)
        if si is None:
            mt5.symbol_select(sym, True); si = mt5.symbol_info(sym)
        if si is None:
            continue
        point = si.point or POINT_GUESS.get(sym, 1e-5)
        spread_price = (si.spread or 0) * point
        res[sym] = {}
        for tfn, _mins in TFS:
            tf = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}[tfn]
            r = mt5.copy_rates_from_pos(sym, tf, 0, 2500)
            if r is None or len(r) < 300:
                continue
            o = np.array([x["open"] for x in r], float); h = np.array([x["high"] for x in r], float)
            l = np.array([x["low"] for x in r], float); c = np.array([x["close"] for x in r], float)
            atr = _atr(h, l, c); sigs = _signals(o, h, l, c); hold = HOLD[tfn]
            tf_res = {}
            for name, sg in sigs.items():
                n_s, ef, eo, to = _measure(o, h, l, c, atr, sg, hold, spread_price)
                if n_s >= 15:
                    edge = (to is not None and to > 2.0 and eo is not None and eo > 0)
                    if edge:
                        best_count += 1
                    tf_res[name] = {"n": n_s, "exp_full_R": ef, "exp_oos_R": eo, "t_oos": to,
                                    "verdict": "حافّة" if edge else "ضجيج"}
            # الأفضل لهذا الرمز/الفريم (أعلى exp_oos موجب دالّ، وإلا «لا حافّة»)
            edges = [(k, v) for k, v in tf_res.items() if v["verdict"] == "حافّة"]
            best = max(edges, key=lambda kv: kv[1]["exp_oos_R"])[0] if edges else "لا حافّة"
            res[sym][tfn] = {"best": best, "indicators": tf_res}
    payload = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
               "symbols": len(res), "edges_found": best_count, "scan": res,
               "honesty": "مقيسٌ walk-forward بعد الكلفة؛ حافّة فقط إن t_oos>2 وexp_oos>0. الأغلب لا-حافّة (يؤكّد أنّ الحافّة انضباط لا تنبّؤ)."}
    tmp = OUT.with_suffix(".tmp"); tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    try:
        json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engine": "ماسح الحافّة",
                   "symbols": len(res), "edges_found": best_count, "next_scan_s": POLL_S},
                  open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    print(f"🔬 مُسح {len(res)} رمزاً × {len(TFS)} فريم — حوافّ صامدة OOS: {best_count} (الأغلب لا-حافّة، صدقٌ مقيس)", flush=True)


def main():
    if engine_lock:
        try:
            engine_lock.claim("edge_scanner")
        except Exception:
            pass
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🔬 ماسح الحافّة بدأ — poll={POLL_S}s (يقيس كل مؤشّر لكل رمز/فريم بصدق)", flush=True)
    while True:
        try:
            scan()
        except Exception as e:
            print(f"scan err: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
