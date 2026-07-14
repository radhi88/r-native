"""ml_indicator.py — مؤشّر تعلّم آلي صادق (من فيديو CodeTrading، مطبّق بلا تسريب بيانات).

ليس وصفة الفيديو المتسرّبة (shuffle split = 99% وهمي). بدلاً:
  • ميزات سببية (talib RSI/ADX/MACD/ATR/CCI/ROC + عوائد مُطبّعة بالتذبذب + جلسة/ساعة).
  • تصنيف triple-barrier صافٍ بعد السبريد (TP=2·ATR / SL=1·ATR / أفق H بار).
  • أوزان عيّنات بالتفرّد (concurrency) — تعالج تداخل النوافذ.
  • lightgbm صغير مُقنّن (ليس حافظاً) + monotone (سبريد أعلى ⇒ احتمال فوز أقل).
  • تحقّق PURGED + EMBARGOED walk-forward (مُضمّن، بلا skfolio) + null-control بخلط التسميات.
  • بوّابة مالية: DSR>0.5 · PSR>0.95 · AUC≥0.55 · PF≥1.2 صافٍ · ≥75% نوافذ موجبة.
يكتب ml_pred_{sym}_{tf}.json (صوت)، ويدمج accuracy["ml"] فيوزنه chart_read بنفس آلة الدقّة (أرضية
0.2 لو فشل = يدفن نفسه). محرّك windowless: تنبؤ كل 90ث + إعادة تدريب كل 6 ساعات.
Run:  .venv\\Scripts\\pythonw.exe ml_indicator.py --symbols XAUUSDm,BTCUSDm,US30m --tf M15
"""
from __future__ import annotations
import argparse, json, os, sys, time, math
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
V2 = MT5DIR / "r_native_v2" / "data"
MODELS = V2 / "ml_models"
LOCK = V2 / "ml_indicator.lock"
HORIZON = 8
K_TP, K_SL = 2.0, 1.0
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)

FEATS = ["rsi", "adx", "macd_n", "roc", "cci", "natr", "rng_atr",
         "r1", "r3", "r5", "r10", "vol20", "ac1", "hour_sin", "hour_cos",
         "sess_asia", "sess_london", "sess_ny"]


def _tf(mt5, s):
    return {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1}.get(s, mt5.TIMEFRAME_M15)


def _feature_matrix(rates):
    """مصفوفة ميزات سببية لكل بار (numpy + talib). تعيد (X, atr_series, valid_from)."""
    import numpy as np, talib
    o = np.asarray([r["open"] for r in rates], float)
    h = np.asarray([r["high"] for r in rates], float)
    l = np.asarray([r["low"] for r in rates], float)
    c = np.asarray([r["close"] for r in rates], float)
    t = np.asarray([int(r["time"]) for r in rates], int)
    rsi = talib.RSI(c, 14)
    adx = talib.ADX(h, l, c, 14)
    macd, sig, hist = talib.MACD(c, 12, 26, 9)
    atr = talib.ATR(h, l, c, 14)
    natr = talib.NATR(h, l, c, 14)
    roc = talib.ROC(c, 10)
    cci = talib.CCI(h, l, c, 20)
    n = len(c)
    rng_atr = (h - l) / np.where(atr > 0, atr, np.nan)
    def ret(k):
        out = np.full(n, np.nan)
        out[k:] = (c[k:] / c[:-k] - 1.0)
        return out / np.where(natr > 0, natr / 100.0, np.nan)
    r1, r3, r5, r10 = ret(1), ret(3), ret(5), ret(10)
    logret = np.full(n, 0.0); logret[1:] = np.log(c[1:] / c[:-1])
    vol20 = np.full(n, np.nan)
    for i in range(20, n):
        vol20[i] = logret[i - 20:i].std()
    ac1 = np.full(n, np.nan)               # autocorr lag-1 (regime proxy: trend>0 / meanrev<0)
    for i in range(40, n):
        w = logret[i - 30:i]
        if w.std() > 0:
            ac1[i] = np.corrcoef(w[1:], w[:-1])[0, 1]
    hours = np.asarray([datetime.fromtimestamp(x, tz=timezone.utc).hour for x in t])
    hs = np.sin(2 * np.pi * hours / 24); hc = np.cos(2 * np.pi * hours / 24)
    sa = ((hours >= 22) | (hours < 8)).astype(float)
    sl_ = ((hours >= 8) & (hours < 13)).astype(float)
    sn = ((hours >= 13) & (hours < 21)).astype(float)
    X = np.column_stack([rsi, adx, hist / np.where(atr > 0, atr, np.nan), roc, cci, natr,
                         rng_atr, r1, r3, r5, r10, vol20, ac1, hs, hc, sa, sl_, sn])
    return X, atr, 50


def _labels(rates, atr, spread, H=HORIZON):
    """triple-barrier صافٍ بعد السبريد. يعيد (y, t1, idx) — y∈{0,1}, t1=بار الحسم."""
    import numpy as np
    c = np.asarray([r["close"] for r in rates], float)
    h = np.asarray([r["high"] for r in rates], float)
    l = np.asarray([r["low"] for r in rates], float)
    n = len(c)
    y, t1, idx = [], [], []
    for i in range(50, n - H):
        a = atr[i]
        if not (a > 0):
            continue
        sp = spread[i] if i < len(spread) else 0.0
        entry = c[i]
        tp = entry + K_TP * a; sl = entry - K_SL * a
        lab, res = 0, i + H
        for j in range(i + 1, i + H + 1):
            if h[j] >= tp:
                lab, res = 1, j; break
            if l[j] <= sl:
                lab, res = 0, j; break
        else:
            lab = 1 if (c[i + H] - entry - sp) > 0 else 0
        # net-of-spread: a win that barely cleared TP but < spread isn't a win
        if lab == 1 and (K_TP * a - sp) <= 0:
            lab = 0
        y.append(lab); t1.append(res); idx.append(i)
    return np.asarray(y), np.asarray(t1), np.asarray(idx)


def _uniqueness(idx, t1, n):
    """وزن العيّنة = 1/التزامن (de Prado) — يخفّض الأحداث المتداخلة المتكرّرة."""
    import numpy as np
    conc = np.zeros(n + HORIZON + 2)
    for i, e in zip(idx, t1):
        conc[i:e + 1] += 1
    w = np.array([1.0 / max(1.0, conc[i:e + 1].mean()) for i, e in zip(idx, t1)])
    return w / w.mean() if w.mean() > 0 else w


def _purged_folds(idx, t1, folds=4, embargo=HORIZON):
    """purged+embargoed walk-forward: نوافذ زمنية، تُنقّى عيّنات التدريب المتداخلة مع الاختبار."""
    import numpy as np
    m = len(idx)
    bnd = [int(m * k / folds) for k in range(folds + 1)]
    out = []
    for k in range(1, folds):                       # توسّع أمامي: درّب على [0..bnd[k]), اختبر [bnd[k]..bnd[k+1])
        te = np.arange(bnd[k], bnd[k + 1])
        if len(te) < 10:
            continue
        te_start_bar = idx[te[0]]
        tr = np.array([p for p in range(bnd[k]) if t1[p] < te_start_bar - embargo])
        if len(tr) < 50:
            continue
        out.append((tr, te))
    return out


def train_symbol(mt5, sym, tf, n_trials=24):
    import numpy as np, lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    import quant_gates as qg
    import genome_factory as gf
    r = mt5.copy_rates_from_pos(sym, _tf(mt5, sym if False else tf), 0, 5000)
    if r is None or len(r) < 800:
        return None
    info = mt5.symbol_info(sym)
    spread = gf._real_spread_price(r, info.point, (info.spread or 1) * info.point) if info else [0.0] * len(r)
    spread_atr_units = None
    X, atr, vf = _feature_matrix(r)
    y, t1, idx = _labels(r, atr, spread)
    if len(y) < 200 or len(set(y.tolist())) < 2:
        return None
    Xi = X[idx]
    mask = ~np.isnan(Xi).any(axis=1)
    Xi, y2, t1b, idxb = Xi[mask], y[mask], t1[mask], idx[mask]
    if len(y2) < 200:
        return None
    w = _uniqueness(idxb, t1b, len(r))
    folds = _purged_folds(np.arange(len(idxb)), t1b, 4)
    if not folds:
        return None
    mono = [0] * len(FEATS); mono[FEATS.index("natr")] = -1
    params = dict(objective="binary", max_depth=4, num_leaves=23, min_child_samples=150,
                  n_estimators=160, learning_rate=0.03, subsample=0.75, colsample_bytree=0.65,
                  reg_lambda=1.5, is_unbalance=True, verbose=-1, monotone_constraints=mono)
    aucs, R = [], []
    for tr, te in folds:
        m = lgb.LGBMClassifier(**params)
        m.fit(Xi[tr], y2[tr], sample_weight=w[tr])
        prob = m.predict_proba(Xi[te])[:, 1]
        try:
            aucs.append(roc_auc_score(y2[te], prob))
        except Exception:
            pass
        for pi, p in enumerate(prob):                # عوائد R صافية للصفقات المُختارة
            if p >= 0.55:
                R.append((K_TP if y2[te][pi] == 1 else -K_SL) - spread[idxb[te[pi]]] / max(atr[idxb[te[pi]]], 1e-9))
    if not aucs:
        return None
    auc = float(np.mean(aucs)); worst = float(np.min(aucs))
    pos_folds = sum(1 for a in aucs if a > 0.5) / len(aucs)
    # null control: shuffled labels AUC must collapse to ~0.5
    yn = y2.copy(); np.random.shuffle(yn)
    null_aucs = []
    for tr, te in folds:
        m = lgb.LGBMClassifier(**params); m.fit(Xi[tr], yn[tr], sample_weight=w[tr])
        try: null_aucs.append(roc_auc_score(yn[te], m.predict_proba(Xi[te])[:, 1]))
        except Exception: pass
    null_auc = float(np.mean(null_aucs)) if null_aucs else 0.5
    dsr = qg.deflated_sharpe_ratio(R, n_trials) if len(R) >= 20 else 0.0
    psr = qg.probabilistic_sharpe_ratio(R) if len(R) >= 20 else 0.0
    pf = (sum(x for x in R if x > 0) / abs(sum(x for x in R if x < 0))) if any(x < 0 for x in R) else (9.9 if R else 0)
    n_tr = len(R)
    passed = (auc >= 0.55 and pos_folds >= 0.75 and n_tr >= 30 and pf >= 1.2
              and dsr > 0.5 and psr > 0.95 and null_auc < 0.55)
    # فشل → lift سالب قويّ (≤-0.08) ليفرض أرضية 0.2 في chart_read (1+lift*10 ≤ 0.2) = دفن حقيقي
    lift = round(auc - 0.5, 4) if passed else -0.10
    # fit final on ALL data + persist
    MODELS.mkdir(parents=True, exist_ok=True)
    final = lgb.LGBMClassifier(**params); final.fit(Xi, y2, sample_weight=w)
    import joblib, hashlib
    mp = MODELS / f"{sym}_{tf}.joblib"; joblib.dump(final, mp)
    mh = hashlib.md5(open(mp, "rb").read()).hexdigest()[:10]
    meta = {"feats": FEATS, "sym": sym, "tf": tf, "trained": time.time(),
            "auc": round(auc, 4), "worst_auc": round(worst, 4), "null_auc": round(null_auc, 4),
            "pos_folds": round(pos_folds, 2), "n_trades": n_tr, "pf": round(pf, 2),
            "dsr": round(dsr, 3), "psr": round(psr, 3), "passed": passed, "lift": lift, "hash": mh}
    (MODELS / f"{sym}_{tf}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    # merge accuracy["ml"] so chart_read auto-weights it
    af = V2 / f"indicator_accuracy_{sym}.json"
    acc = {}
    try: acc = json.loads(af.read_text(encoding="utf-8"))
    except Exception: acc = {"accuracy": {}}
    acc.setdefault("accuracy", {})["ml"] = {"hit_rate": round(0.5 + lift, 3), "lift": lift, "votes": max(40, n_tr)}
    tmp = af.with_suffix(".json.tmp"); tmp.write_text(json.dumps(acc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, af)
    print(f"[ML] {sym}/{tf}: AUC {auc:.3f} (null {null_auc:.3f}) · فولدز+ {pos_folds:.0%} · PF {pf:.2f} · "
          f"DSR {dsr:.2f} · {'✅ مرّ' if passed else '⛔ فشل→يُدفن'}", flush=True)
    return meta


def predict_symbol(mt5, sym, tf):
    import numpy as np, joblib
    mp = MODELS / f"{sym}_{tf}.joblib"; mf = MODELS / f"{sym}_{tf}.meta.json"
    if not mp.exists() or not mf.exists():
        return
    try:
        meta = json.loads(mf.read_text(encoding="utf-8"))
        if meta.get("feats") != FEATS:
            return
        model = joblib.load(mp)
        r = mt5.copy_rates_from_pos(sym, _tf(mt5, tf), 0, 300)
        if r is None or len(r) < 80:
            return
        r = r[:-1]                                  # أسقط البار المتشكّل → ميزات حيّة = تدريبية
        X, atr, vf = _feature_matrix(r)
        row = X[-1]
        if np.isnan(row).any():
            return
        prob = float(model.predict_proba(row.reshape(1, -1))[:, 1][0])
        if not (0 <= prob <= 1):
            return
        vote = 1 if prob >= 0.55 else -1 if prob <= 0.45 else 0
        out = {"symbol": sym, "tf": tf, "ts": time.time(), "prob_up": round(prob, 4),
               "vote": vote, "hash": meta.get("hash"), "oos_lift": meta.get("lift")}
        of = V2 / f"ml_pred_{sym}_{tf}.json"
        tmp = of.with_suffix(".json.tmp"); tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, of)
    except Exception:
        pass


def main():
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="XAUUSDm,BTCUSDm,US30m")
    ap.add_argument("--tf", default="M15")
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    # single-instance lock
    try:
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 300:
            print("[ML] نسخة أخرى تعمل — خروج"); return 0
    except Exception:
        pass
    print(f"[ML] مؤشّر التعلّم الآلي حيّ · {syms} {a.tf} · تنبؤ 90ث · تدريب 6س", flush=True)
    last_train = 0.0
    while True:
        try:
            LOCK.write_text(str(time.time()))
            if time.time() - last_train > 6 * 3600:
                for s in syms:
                    try: train_symbol(mt5, s, a.tf)
                    except Exception as e: print(f"[ML] train {s} err {e}", flush=True)
                last_train = time.time()
            for s in syms:
                predict_symbol(mt5, s, a.tf)
        except Exception as e:
            print(f"[ML] err {e}", flush=True)
        time.sleep(90)


if __name__ == "__main__":
    raise SystemExit(main())
