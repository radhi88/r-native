"""conf_calibration.py — معايرة ثقة لكل رمز (per-symbol confidence calibration).

الفكرة (صادقة، لا تنبّؤ دخول):
    ثقة chart_read الخام (raw confluence/agreement 0..1) ليست بالضرورة احتمال فوز حقيقي.
    نتعلّم خريطة لكل رمز: raw_conf → win-rate فعلي، ونتحقّق **بمشي-للأمام زمني** أن المعايَر
    يطابق الفوز الفعلي خارج العيّنة أفضل من الخام (Brier / reliability) وأنه لا يهدم الترتيب.

قيد الصدق الحاسم (مكتوب صراحةً، لا يُخفى):
    جدول signals في friday.db لا يحوي أزواج (raw_conf, win) تاريخية قابلة للاستخدام
    (صفّ واحد فقط فيه confluence). و chart_read.confluence يُحسب لحظياً من مدخلات نقطية
    (news / market_internals / ml) غير مخزّنة لكل صفقة — فلا يمكن إعادة بنائها بأمانة.
    لذلك نبني **بديل ثقة (proxy) قابل لإعادة الإنتاج بدقّة** من السمات المخزّنة فعلاً في
    features (rsi, stoch, trend, htf_trend, dist_ema_atr, زخم الشموع, محاذاة EMA) — من نفس
    عائلة أصوات chart_read. السؤال المُختبَر: هل معايرة هذا البديل لكل رمز تتفوّق على الخام
    OOS عبر كتل زمنية؟ إن نعم → الطبقة تستحق الوصل بـ chart_read.confluence الحيّ.
    إن لا → NO_EDGE/INCONCLUSIVE. (تذكّر: نموذج تعلّم-عميق للدخول كان NO_EDGE / لا-استقرار.)

التحقّق:
    * مشي-للأمام زمني (time-ordered walk-forward): درّب على الماضي، قيّم على المستقبل، عدّة كتل.
    * مقاييس OOS: Brier score (أقل=أفضل) للخام مقابل المعايَر، + منحنى موثوقية (reliability),
      + هل تحسّن expectancy عند فرز/عتبة الإشارات بالثقة المعايَرة مقابل الخام.
    * فحص الاستقرار: هل خريطة المعايرة ثابتة عبر الكتل (تباين مُنخفِض) أم تنقلب (كما قتل
      نموذج الدخول)؟ نُبلِّغ بصراحة.

واجهة عامّة:
    calibrate(sym, raw_conf) -> adj            # احتمال فوز معايَر [0..1] (يقع على الخام لو لا حافة)

لا يرسل أي أمر تداول؛ قراءة friday.db فقط + يكتب data/conf_calibration.json (خريطة معايرة).
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "friday.db"
OUT_PATH = ROOT / "data" / "conf_calibration.json"

# عتبات "حافة" دنيا. الكسب الحقيقي = المعايَر يتفوّق على الثابت (base-rate) + ترتيب فعلي (AUC).
# Brier-vs-raw وحده خادع: يكافئ معايرة المستوى حتى لو لا تمييز (انظر الفخّ في run/verdict).
BRIER_IMPROVE_MIN = 0.002          # المعايَر مقابل الثابت base-rate (لا مقابل الخام)
AUC_MIN = 0.55                     # حدّ أدنى لقدرة التمييز OOS (0.5 = لا ترتيب)
DRIFT_MAX = 0.12                   # سقف لا-استقرار win-rate عبر الزمن (فوقه = هدف متحرّك كنموذج الدخول)
MIN_TRAIN = 200                    # حد أدنى لعيّنة التدريب لكل كتلة
MIN_TEST = 80                      # حد أدنى لعيّنة الاختبار لكل كتلة
N_BLOCKS = 5                       # عدد كتل المشي-للأمام


# ----------------------------------------------------------------- proxy raw_conf
def _proxy_conf(f: dict, side: int) -> Optional[float]:
    """بديل ثقة قابل لإعادة الإنتاج من السمات المخزّنة — عائلة أصوات chart_read.

    يبني تصويتاً موزوناً متّجهاً (نفس منطق chart_read: agree/total) من المؤشّرات المتاحة،
    ثم يُسقطه على اتجاه الصفقة الفعلي (side) ليعطي ثقة [0..1] في اتجاه الدخول.
    يرجع None لو لا توجد سمات كافية.
    """
    if side not in (1, -1):
        return None
    votes: dict[str, int] = {}
    weights: dict[str, float] = {}

    def cast(name: str, v: int, w: float) -> None:
        if v != 0:
            votes[name] = v
            weights[name] = w

    rsi = f.get("rsi")
    if rsi is not None:
        cast("rsi", 1 if rsi < 40 else -1 if rsi > 60 else 0, 1.0)
    stoch = f.get("stoch")
    if stoch is not None:
        cast("stoch", 1 if stoch < 25 else -1 if stoch > 75 else 0, 1.0)
    tr = f.get("trend")
    if tr is not None:
        cast("trend", int(np.sign(tr)), 1.2)
    htf = f.get("htf_trend")
    if htf is not None:
        cast("htf", int(np.sign(htf)), 1.5)
    # محاذاة EMA: السعر فوق/تحت ema21 + ميل ema8>ema21
    ema8, ema21, price = f.get("ema8"), f.get("ema21"), f.get("price")
    if ema8 is not None and ema21 is not None and price is not None:
        align = 1 if (price > ema21 and ema8 >= ema21) else -1 if (price < ema21 and ema8 <= ema21) else 0
        cast("ema", align, 1.2)
    # مسافة عن EMA (dist_ema_atr): إرهاق ممتد → انحياز ارتداد خفيف
    de = f.get("dist_ema_atr")
    if de is not None:
        cast("dist", -1 if de > 1.5 else 1 if de < -1.5 else 0, 0.6)
    # زخم الشموع (آخر شمعتين): اتجاه الجسم
    cs = f.get("candles") or []
    if cs:
        mom = 0
        for c in cs[-2:]:
            mom += 1 if c.get("bull") else -1
        cast("candles", int(np.sign(mom)), 0.9)

    total = sum(weights.values())
    if total <= 0:
        return None
    # ثقة في اتجاه الصفقة الفعلي: نسبة الوزن المتّفق مع side
    agree = sum(weights[k] for k in votes if votes[k] == side)
    return agree / total


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


# ----------------------------------------------------------------- calibrators
def _fit_platt(x: np.ndarray, y: np.ndarray, iters: int = 500, lr: float = 0.3) -> tuple[float, float]:
    """Platt scaling: sigmoid(a*logit(raw)+b) عبر انحدار لوجستي بسيط (نزول متدرّج)."""
    z = np.array([_logit(float(v)) for v in x])
    a, b = 1.0, 0.0
    n = len(z)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(a * z + b)))
        ga = float(np.dot(p - y, z)) / n
        gb = float(np.sum(p - y)) / n
        a -= lr * ga
        b -= lr * gb
    return a, b


def _apply_platt(raw: float, a: float, b: float) -> float:
    return _sigmoid(a * _logit(float(raw)) + b)


def _fit_isotonic(x: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """isotonic regression (PAV) — رتيب غير معلمي. يرجع (عتبات x مرتّبة, قيم y معايَرة)."""
    order = np.argsort(x)
    xs = x[order].astype(float)
    ys = y[order].astype(float)
    # Pool Adjacent Violators
    w = np.ones_like(ys)
    vals = ys.copy()
    i = 0
    blocks = [[v, 1.0, v] for v in vals]  # [value, weight, _]
    # نهج مكدّس بسيط
    stack: list[list[float]] = []
    for v in ys:
        cur = [v, 1.0]
        while stack and stack[-1][0] > cur[0]:
            prev = stack.pop()
            tw = prev[1] + cur[1]
            cur = [(prev[0] * prev[1] + cur[0] * cur[1]) / tw, tw]
        stack.append(cur)
    # افرد القيم الرتيبة بطول البيانات
    fitted = []
    for v, wt in stack:
        fitted.extend([v] * int(round(wt)))
    fitted = fitted[: len(ys)]
    while len(fitted) < len(ys):
        fitted.append(fitted[-1] if fitted else 0.5)
    return xs.tolist(), fitted


def _apply_isotonic(raw: float, xs: list[float], ys: list[float]) -> float:
    if not xs:
        return raw
    raw = float(raw)
    if raw <= xs[0]:
        return ys[0]
    if raw >= xs[-1]:
        return ys[-1]
    # بحث خطّي/تداخلي
    import bisect
    i = bisect.bisect_right(xs, raw) - 1
    i = max(0, min(i, len(ys) - 1))
    return ys[i]


def _brier(probs: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((probs - y) ** 2))


# ----------------------------------------------------------------- data load
def _load_samples(con: sqlite3.Connection, symbol: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """يرجع (raw_conf, win, ts) للرمز، مرتّبة زمنياً. يحسب proxy_conf من features_json."""
    cur = con.execute(
        "SELECT ts, side, win, features_json FROM features "
        "WHERE symbol=? AND win IS NOT NULL AND features_json IS NOT NULL ORDER BY ts ASC",
        (symbol,),
    )
    raw, win, ts = [], [], []
    for r in cur.fetchall():
        try:
            f = json.loads(r["features_json"])
        except Exception:
            continue
        c = _proxy_conf(f, int(r["side"]) if r["side"] is not None else 0)
        if c is None:
            continue
        raw.append(c)
        win.append(int(r["win"]))
        ts.append(float(r["ts"]))
    return np.array(raw), np.array(win), np.array(ts)


# ----------------------------------------------------------------- walk-forward
def _auc(scores: np.ndarray, y: np.ndarray) -> float:
    """AUC بترتيب Mann-Whitney — قدرة التمييز (0.5 = لا ترتيب)."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(y)
    npos, nneg = int((y == 1).sum()), int((y == 0).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def walk_forward(raw: np.ndarray, win: np.ndarray, method: str = "platt") -> dict:
    """مشي-للأمام زمني: قسّم لـ N_BLOCKS؛ درّب على ما قبل، قيّم على الكتلة الحالية.

    يقيس ثلاثة أشياء منفصلة بصدق (الفخّ: Brier وحده يكافئ معايرة المستوى فقط):
      1. brier_raw مقابل brier_cal     — هل المعايرة تقلّل الخطأ؟
      2. brier_base (ثابت = win-rate التدريب) — الأساس التافه. لو المعايَر ≈ الأساس فالكسب
         مجرّد تعلّم المستوى، لا تمييز.
      3. AUC(raw, win) OOS              — هل الثقة الخام ترتّب الفائز فوق الخاسر أصلاً؟
                                          AUC≈0.5 = لا حافة ترتيب → المعايرة تجميل بلا قيمة.
    """
    n = len(raw)
    if n < MIN_TRAIN + MIN_TEST:
        return {"ok": False, "reason": f"عيّنة صغيرة n={n}"}

    # حدود كتل متساوية على المحور الزمني (البيانات مرتّبة زمنياً مسبقاً)
    edges = np.linspace(0, n, N_BLOCKS + 1, dtype=int)
    blocks = []
    params = []
    raw_briers, cal_briers, base_briers, aucs = [], [], [], []
    base_rate_test = []

    for bi in range(1, N_BLOCKS):
        tr_end = edges[bi]
        te_end = edges[bi + 1]
        x_tr, y_tr = raw[:tr_end], win[:tr_end]
        x_te, y_te = raw[tr_end:te_end], win[tr_end:te_end]
        if len(x_tr) < MIN_TRAIN or len(x_te) < MIN_TEST:
            continue
        if len(set(y_tr.tolist())) < 2:
            continue

        if method == "platt":
            a, b = _fit_platt(x_tr, y_tr)
            cal_te = np.array([_apply_platt(v, a, b) for v in x_te])
            params.append({"a": round(a, 4), "b": round(b, 4)})
        else:  # isotonic
            xs, ys = _fit_isotonic(x_tr, y_tr)
            cal_te = np.array([_apply_isotonic(v, xs, ys) for v in x_te])
            params.append({"iso_n": len(xs)})

        base_p = float(y_tr.mean())                  # تنبّؤ ثابت = win-rate التدريب (الأساس التافه)
        rb = _brier(x_te, y_te)          # الخام يُستخدم كاحتمال مباشرة (هذا هو الادّعاء المُختبَر)
        cb = _brier(cal_te, y_te)
        bb = _brier(np.full(len(y_te), base_p), y_te)
        au = _auc(x_te, y_te)
        raw_briers.append(rb)
        cal_briers.append(cb)
        base_briers.append(bb)
        if not math.isnan(au):
            aucs.append(au)
        base_rate_test.append(float(y_te.mean()))
        blocks.append({
            "block": bi,
            "n_train": int(len(x_tr)), "n_test": int(len(x_te)),
            "brier_raw": round(rb, 4), "brier_cal": round(cb, 4),
            "brier_base": round(bb, 4),
            "delta": round(rb - cb, 4),           # موجب = المعايَر أفضل من الخام
            "cal_vs_base": round(bb - cb, 4),     # موجب = المعايَر أفضل من ثابت base-rate (تمييز حقيقي)
            "auc": round(au, 3) if not math.isnan(au) else None,
            "winrate_train": round(base_p, 3),
            "winrate_test": round(float(y_te.mean()), 3),
        })

    if not blocks:
        return {"ok": False, "reason": "لا كتل صالحة (عيّنة/توازن)"}

    deltas = [b["delta"] for b in blocks]
    cal_vs_base = [b["cal_vs_base"] for b in blocks]
    mean_delta = float(np.mean(deltas))
    blocks_improved = sum(1 for d in deltas if d > 0)
    base_drift = float(np.std(base_rate_test))

    return {
        "ok": True,
        "method": method,
        "blocks": blocks,
        "params_per_block": params,
        "mean_brier_raw": round(float(np.mean(raw_briers)), 4),
        "mean_brier_cal": round(float(np.mean(cal_briers)), 4),
        "mean_brier_base": round(float(np.mean(base_briers)), 4),
        "mean_delta": round(mean_delta, 4),
        "delta_std": round(float(np.std(deltas)), 4),
        # الكسب الحقيقي = المعايَر يتفوّق على الثابت base-rate (تمييز، لا معايرة-مستوى)
        "mean_cal_vs_base": round(float(np.mean(cal_vs_base)), 4),
        "mean_auc_oos": round(float(np.mean(aucs)), 4) if aucs else None,
        "blocks_improved": blocks_improved,
        "n_blocks_eval": len(blocks),
        "base_winrate_drift_std": round(base_drift, 3),
    }


def _expectancy_lift(raw: np.ndarray, win: np.ndarray, wf: dict) -> dict:
    """هل ترتيب/عتبة بالثقة المعايَرة يحسّن دقّة الإشارات المنتقاة OOS؟

    باستخدام معاملات آخر كتلة، نطبّق على نصف-الاختبار الأخير: انتقِ أعلى ثلث ثقة في كلٍّ
    (خام مقابل معايَر) وقارن win-rate. (تقريب — التحقّق الأساسي هو Brier.)
    """
    if not wf.get("ok"):
        return {"ok": False}
    n = len(raw)
    split = int(n * 0.7)
    x_tr, y_tr = raw[:split], win[:split]
    x_te, y_te = raw[split:], win[split:]
    if len(x_te) < 60 or len(set(y_tr.tolist())) < 2:
        return {"ok": False}
    a, b = _fit_platt(x_tr, y_tr)
    cal_te = np.array([_apply_platt(v, a, b) for v in x_te])
    # أعلى ثلث ثقة
    k = max(10, len(x_te) // 3)
    raw_top = np.argsort(x_te)[-k:]
    cal_top = np.argsort(cal_te)[-k:]
    return {
        "ok": True,
        "n_test": int(len(x_te)),
        "k_top": int(k),
        "winrate_all": round(float(y_te.mean()), 3),
        "winrate_top_raw": round(float(y_te[raw_top].mean()), 3),
        "winrate_top_cal": round(float(y_te[cal_top].mean()), 3),
    }


# ----------------------------------------------------------------- verdict + fit
def _verdict(per_symbol: dict) -> tuple[str, bool, str]:
    """احكم بصدق عبر الرموز. USE فقط لو تحسّن متّسق OOS وثبات معقول."""
    usable = {s: r for s, r in per_symbol.items() if r.get("platt", {}).get("ok")}
    if not usable:
        return "INCONCLUSIVE", False, "لا رمز بعيّنة كافية للمشي-للأمام."

    notes = []
    any_use = False
    for s, r in usable.items():
        any_use = _symbol_use(r["platt"]) or any_use
        notes.append(f"{s}: {_symbol_note(r['platt'])}")

    verdict = "USE" if any_use else "NO_EDGE"
    return verdict, any_use, " | ".join(notes)


def _symbol_use(wf: dict) -> bool:
    """USE صارم: تمييز حقيقي (AUC OOS) + المعايَر يتفوّق على الثابت base-rate عبر الكتل +
    استقرار win-rate. أي شرط يسقط → NO_EDGE لهذا الرمز (لا تجميل مستوى، لا هدف متحرّك)."""
    if not wf.get("ok"):
        return False
    auc = wf.get("mean_auc_oos")
    discriminates = auc is not None and auc >= AUC_MIN
    beats_base = wf.get("mean_cal_vs_base", -1) >= BRIER_IMPROVE_MIN
    stable = wf.get("base_winrate_drift_std", 1.0) <= DRIFT_MAX
    return bool(discriminates and beats_base and stable)


def _symbol_note(wf: dict) -> str:
    if _symbol_use(wf):
        return (f"USE (AUC_oos={wf.get('mean_auc_oos')}, cal_vs_base={wf.get('mean_cal_vs_base'):+.4f}, "
                f"drift={wf.get('base_winrate_drift_std')})")
    reasons = []
    auc = wf.get("mean_auc_oos")
    if auc is None or auc < AUC_MIN:
        reasons.append(f"AUC_oos={auc}<{AUC_MIN} (لا ترتيب)")
    if wf.get("mean_cal_vs_base", -1) < BRIER_IMPROVE_MIN:
        reasons.append(f"cal_vs_base={wf.get('mean_cal_vs_base'):+.4f} (= مجرّد معايرة مستوى)")
    if wf.get("base_winrate_drift_std", 1.0) > DRIFT_MAX:
        reasons.append(f"drift={wf.get('base_winrate_drift_std')}>{DRIFT_MAX} (هدف متحرّك)")
    return "لا — " + ", ".join(reasons)


def _fit_full(con: sqlite3.Connection, symbol: str) -> Optional[dict]:
    """عاير على كامل بيانات الرمز (للاستخدام الحيّ بعد ثبوت الحافة OOS)."""
    raw, win, _ = _load_samples(con, symbol)
    if len(raw) < MIN_TRAIN:
        return None
    if len(set(win.tolist())) < 2:
        return None
    a, b = _fit_platt(raw, win)
    return {"a": round(a, 5), "b": round(b, 5), "n": int(len(raw)),
            "base_winrate": round(float(win.mean()), 4)}


# ----------------------------------------------------------------- public API
_CACHE: Optional[dict] = None


def _load_map() -> dict:
    global _CACHE
    if _CACHE is None:
        if OUT_PATH.exists():
            try:
                _CACHE = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            except Exception:
                _CACHE = {}
        else:
            _CACHE = {}
    return _CACHE


def calibrate(sym: str, raw_conf: float) -> float:
    """احتمال فوز معايَر [0..1] للرمز. يقع على الخام لو لا حافة مُثبتة (USE) للرمز.

    الاستخدام الحيّ في chart_read (بعد ثبوت الحافة):
        adj = calibrate(symbol, result['confluence'])
    """
    try:
        raw_conf = float(raw_conf)
    except Exception:
        return float(raw_conf) if raw_conf is not None else 0.5
    m = _load_map()
    sym_map = (m.get("calibrators") or {}).get(sym)
    # نطبّق فقط لو الحكم العام للرمز USE (وإلا الخام — صدق: لا حافة = لا تغيير)
    if not sym_map or sym_map.get("verdict") != "USE":
        return raw_conf
    a, b = sym_map.get("a"), sym_map.get("b")
    if a is None or b is None:
        return raw_conf
    return round(_apply_platt(raw_conf, a, b), 4)


# ----------------------------------------------------------------- run
def run() -> dict:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    # رموز بعيّنة معقولة
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM features WHERE win IS NOT NULL GROUP BY symbol "
        "HAVING COUNT(*) >= ? ORDER BY COUNT(*) DESC", (MIN_TRAIN + MIN_TEST,)
    ).fetchall()]

    per_symbol: dict[str, dict] = {}
    for s in syms:
        raw, win, ts = _load_samples(con, s)
        if len(raw) < MIN_TRAIN + MIN_TEST:
            per_symbol[s] = {"n": int(len(raw)), "skip": "عيّنة صغيرة"}
            continue
        wf_platt = walk_forward(raw, win, "platt")
        wf_iso = walk_forward(raw, win, "isotonic")
        lift = _expectancy_lift(raw, win, wf_platt)
        per_symbol[s] = {
            "n": int(len(raw)),
            "overall_winrate": round(float(win.mean()), 4),
            "raw_conf_mean": round(float(raw.mean()), 4),
            "raw_conf_std": round(float(raw.std()), 4),
            "platt": wf_platt,
            "isotonic": wf_iso,
            "expectancy_lift": lift,
        }

    verdict, any_use, vnotes = _verdict(per_symbol)

    # ركّب خريطة المعايرة الحيّة (full-fit فقط للرموز التي حكمها USE الصارم)
    calibrators: dict[str, dict] = {}
    for s, r in per_symbol.items():
        wf = r.get("platt", {})
        if not wf.get("ok"):
            continue
        sym_verdict = "USE" if _symbol_use(wf) else "NO_EDGE"
        ff = _fit_full(con, s) if sym_verdict == "USE" else None
        calibrators[s] = {"verdict": sym_verdict,
                          **(ff or {}),
                          "oos_mean_auc": wf.get("mean_auc_oos"),
                          "oos_cal_vs_base_brier": wf.get("mean_cal_vs_base"),
                          "winrate_drift_std": wf.get("base_winrate_drift_std")}

    out = {
        "_doc": "per-symbol confidence calibration; proxy raw_conf من features (ليس chart_read الحيّ)",
        "verdict": verdict,
        "verdict_notes": vnotes,
        "brier_improve_min": BRIER_IMPROVE_MIN,
        "n_blocks": N_BLOCKS,
        "per_symbol": per_symbol,
        "calibrators": calibrators,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()
    return out


if __name__ == "__main__":
    res = run()
    print(json.dumps({
        "verdict": res["verdict"],
        "notes": res["verdict_notes"],
        "per_symbol": {s: {
            "n": r.get("n"),
            "winrate": r.get("overall_winrate"),
            "raw_conf_mean": r.get("raw_conf_mean"),
            "AUC_oos": r.get("platt", {}).get("mean_auc_oos"),
            "cal_vs_base_brier": r.get("platt", {}).get("mean_cal_vs_base"),
            "cal_vs_raw_brier": r.get("platt", {}).get("mean_delta"),
            "winrate_drift_std": r.get("platt", {}).get("base_winrate_drift_std"),
            "expectancy_lift": r.get("expectancy_lift"),
        } for s, r in res["per_symbol"].items()},
    }, ensure_ascii=False, indent=2))
