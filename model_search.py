# -*- coding: utf-8 -*-
"""model_search.py — بحث موديلات ML موسّع على الصفقات الحقيقية (صافي التكلفة)، بصدق علمي صارم.

السؤال: هل أيّ (موديل × مجموعة خصائص × هدف) يختار صفقاتٍ صافيها موجب **خارج العيّنة**،
صامداً عبر walk-forward (لا أثر-نافذة)؟ المعيار = صافي الصفقات المختارة OOS، لا الدقّة.

شبكة موسّعة: ~12 موديل × مجموعات خصائص × هدفان (انحدار على الصافي / تصنيف على الفوز).
تقييم موحّد: 5 طيّات زمنية متوسّعة؛ صامد = ≥4/5 طيّات موجبة و المتوسط موجب و > الأساس.

تشغيل:  python model_search.py
"""
from __future__ import annotations
import sqlite3, math, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")

DB = Path(r"C:\Users\Radhi\MT5") / "data" / "friday.db"
TOP_FRAC = 0.25
N_FOLDS = 5


def _load():
    c = sqlite3.connect(str(DB))
    q = ("select f.ts, f.symbol, f.side, f.rsi, f.atr, f.atr_pctile, f.spread, f.stoch, "
         "f.dist_ema_atr, f.trend, f.htf_trend, f.hour, f.dow, "
         "(t.pnl+t.commission+t.swap) net "
         "from features f join trades t on f.ticket=t.ticket where t.exit is not null order by f.ts")
    rows = c.execute(q).fetchall(); c.close()
    return rows


def _featurize(rows):
    cnt = {}
    for r in rows:
        cnt[r[1]] = cnt.get(r[1], 0) + 1
    sym_top = [s for s, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:8]]
    ind, full, y = [], [], []
    for r in rows:
        (t, sym, side, rsi, atr, atrp, spread, stoch, dist, trend, htf, hour, dow, net) = r
        if net is None:
            continue
        def num(v): return float(v) if v is not None else 0.0
        sd = 1.0 if (str(side) in ("0", "BUY") or side == 0) else 0.0
        ind_f = [num(rsi), num(atr), num(atrp), num(spread), num(stoch), num(dist), num(trend), num(htf)]
        ctx = [num(hour), num(dow), sd] + [1.0 if sym == s else 0.0 for s in sym_top]
        ind.append(ind_f); full.append(ind_f + ctx); y.append(float(net))
    return {"indicators": np.array(ind), "all": np.array(full)}, np.array(y)


def _sel_net(score, y_te, frac=TOP_FRAC):
    k = max(int(len(score) * frac), 15)
    s = y_te[np.argsort(-score)[:k]]
    m = s.mean(); sd = s.std()
    t = m / (sd / math.sqrt(len(s))) if sd > 0 else 0.0
    return m, t


def _robust(X, y, model_fn, classify=False):
    """5 طيّات متوسّعة. يرجع (متوسط_صافي, طيّات_موجبة, عدد, الأساس_المتوسط)."""
    from sklearn.preprocessing import StandardScaler
    n = len(y); start = int(n * 0.4); step = (n - start) // N_FOLDS
    nets, bases = [], []
    for i in range(N_FOLDS):
        tr_end = start + i * step; te_end = min(tr_end + step, n)
        if te_end - tr_end < 50 or tr_end < 200:
            continue
        Xtr, ytr, Xte, yte = X[:tr_end], y[:tr_end], X[tr_end:te_end], y[tr_end:te_end]
        try:
            sc = StandardScaler().fit(Xtr); Xtr_s, Xte_s = sc.transform(Xtr), sc.transform(Xte)
            mdl = model_fn()
            if classify:
                mdl.fit(Xtr_s, (ytr > 0).astype(int))
                score = mdl.predict_proba(Xte_s)[:, 1] if hasattr(mdl, "predict_proba") else mdl.predict(Xte_s)
            else:
                mdl.fit(Xtr_s, ytr); score = mdl.predict(Xte_s)
            m, _t = _sel_net(score, yte)
            nets.append(m); bases.append(yte.mean())
        except Exception:
            continue
    if not nets:
        return None
    return (round(float(np.mean(nets)), 2), sum(1 for m in nets if m > 0), len(nets),
            round(float(np.mean(bases)), 2), [round(x, 1) for x in nets])


def _models():
    from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
    from sklearn.ensemble import (RandomForestRegressor, ExtraTreesRegressor, GradientBoostingRegressor,
                                  HistGradientBoostingRegressor, AdaBoostRegressor, RandomForestClassifier)
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.neural_network import MLPRegressor
    M = [
        ("Ridge", lambda: Ridge(alpha=1.0), False),
        ("ElasticNet", lambda: ElasticNet(alpha=0.1), False),
        ("RandomForest", lambda: RandomForestRegressor(n_estimators=150, max_depth=6, min_samples_leaf=30, n_jobs=-1, random_state=42), False),
        ("ExtraTrees", lambda: ExtraTreesRegressor(n_estimators=150, max_depth=6, min_samples_leaf=30, n_jobs=-1, random_state=42), False),
        ("GradientBoost", lambda: GradientBoostingRegressor(n_estimators=150, max_depth=3, min_samples_leaf=30, random_state=42), False),
        ("HistGB", lambda: HistGradientBoostingRegressor(max_depth=3, max_iter=200, min_samples_leaf=30, random_state=42), False),
        ("AdaBoost", lambda: AdaBoostRegressor(n_estimators=100, random_state=42), False),
        ("kNN", lambda: KNeighborsRegressor(n_neighbors=50), False),
        ("MLP_NN", lambda: MLPRegressor(hidden_layer_sizes=(32, 16), max_iter=400, early_stopping=True, random_state=42), False),
        ("LogReg(win)", lambda: LogisticRegression(max_iter=500, C=0.5), True),
        ("RF_clf(win)", lambda: RandomForestClassifier(n_estimators=150, max_depth=6, min_samples_leaf=30, n_jobs=-1, random_state=42), True),
    ]
    try:
        import lightgbm as lgb
        M.append(("LightGBM", lambda: lgb.LGBMRegressor(n_estimators=300, max_depth=4, num_leaves=15,
                  min_child_samples=40, learning_rate=0.03, random_state=42, verbose=-1), False))
    except Exception:
        pass
    return M


def main():
    rows = _load()
    feats, y = _featurize(rows)
    base = round(float(y[int(len(y) * 0.4):].mean()), 2)
    print(f"العيّنة: {len(y)} صفقة حقيقية (صافي التكلفة) · الأساس (تداول الكلّ، نطاق الاختبار): {base}/صفقة\n")
    print(f"{'الموديل':<15}{'خصائص':<12}{'متوسط-صافي-OOS':>16}{'طيّات+':>9}{'الحُكم':>14}")
    print("-" * 70)
    results = []
    for name, fn, clf in _models():
        for fs in ("all", "indicators"):
            r = _robust(feats[fs], y, fn, classify=clf)
            if not r:
                continue
            avg, pos, nf, b, folds = r
            robust = (pos >= max(4, nf) and avg > 0 and avg > b)
            verdict = "🟢 صامد!" if robust else ("➕ موجب-هشّ" if avg > 0 else "➖ سالب")
            print(f"{name:<15}{fs:<12}{avg:>16.2f}{pos:>6}/{nf}{verdict:>14}")
            results.append((name, fs, avg, pos, nf, robust, folds))
    print("-" * 70)
    winners = [r for r in results if r[5]]
    if winners:
        print(f"\n🟢 موديلات صامدة عبر walk-forward: {[(w[0], w[1], w[2]) for w in winners]}")
        print("   تستحقّ التوصيل (ظلّ → إثبات أمامي على الديمو قبل أي تكبير).")
    else:
        best = max(results, key=lambda r: r[2]) if results else None
        print(f"\n⚠️ لا موديل يصمد عبر كل الطيّات (أفضل: {best[0]}/{best[1]} متوسط {best[2]}, طيّات {best[6]}).")
        print("   النتيجة الصادقة: المؤشرات/الموديلات لا تتنبّأ بالربح صافي التكلفة بثبات — العائق التكلفة.")
        print("   الباقي صحيح: فيتو الكوارث الحقيقي (overbought −$31) + الانضباط + تقليل التكلفة.")
    return results


if __name__ == "__main__":
    main()
