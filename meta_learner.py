# -*- coding: utf-8 -*-
"""meta_learner.py — 🧭📏 المتعلّم-الفوقيّ الصادق (ديمو فقط · لا يتاجر أبداً · ماجيك: لا شيء).

════════════════════════════════════════════════════════════════════════════════════════════
الحقيقة أولاً — الحقيقة هي المنتَج (HONESTY IS THE PRODUCT):
  أعمق اكتشافٍ مُقاسٍ في هذا المشروع: السوق ليس متنبَّأً به بهذه النماذج (المجلس/الشبكة العصبيّة/
  المؤشّرات = رمية عملة خارج العيّنة OOS). هذا المحرّك لا يَعِد بحافّةٍ ولا يزوّر تقدّماً في التعلّم.
  قيمته: الشفافيّة + تبادل معلوماتٍ حقيقيّ + قياسٌ ذاتيّ صادق — لا وعدٌ بربح. إن لم توجد حافّة (وهو
  المُرجّح) فالحُكم يقول ذلك صراحةً: 'no_edge'. لا نُلبِس المصادفة ثوب الذكاء.
════════════════════════════════════════════════════════════════════════════════════════════

ماذا يفعل (حلقة ~30ث):
  1. يسحب الصفقات المُغلقة الحقيقيّة (history_deals_get، آخر 14 يوماً، entry==1) لماجيكاتنا فقط.
  2. يشتقّ ميزاتٍ من الوقت+الرمز لكلّ صفقة: {trigger (إن أمكن الوصل من الـfeeds وإلا 'unknown')،
     symbol، session_hour_bucket (0-3)، weekday، was_it_win}.
  3. نموذجٌ متّصلٌ شفّاف: يحافظ على توقّع/نسبة-ربح مشروطة لكلّ قيمة-ميزة (Beta-Bernoulli + متوسّط
     جارٍ للتوقّع) — يُحدَّث تزايديّاً. يكتب meta_beliefs.json: «ما الظروف التي تدفع فعلاً» مُرتّبة بـ|edge|.
  4. القياس الذاتيّ (الجوهر الصادق): يحتجز أحدث 30% من الصفقات كعيّنةٍ خارجيّة OOS. النموذج مُدرَّبٌ
     على أقدم 70% يتنبّأ بـP(ربح) لكلّ صفقة OOS من ميزاتها، ثمّ يُقارَن بالواقع. نحسب Brier + معايرة
     + t-stat لـ«هل مجموعة الاحتمال-العالي تفوق فعلاً مجموعة الاحتمال-المنخفض». يكتب
     meta_learner_progress.json مع verdict ∈ {learning, flat, no_edge} — لا تزوير للتحسّن.
  5. حالة meta_learner_status.json (ts/iso/n_trades/top_condition/verdict).

ما لا يفعله (حدودٌ صارمة):
  • لا يُرسل أيّ أمرٍ تداوليّ إطلاقاً — لا مسار أوامر جديد. القراءة فقط + الكتابة إلى ملفّات القياس.
  • لا يخترع رسائل بَص — كلّ ميزةٍ تُشتقّ من حدثٍ حقيقيّ (صفقة مُغلقة فعليّة + وصلٌ اختياريّ للـfeed).
  • لا يُوصَل الآن كمُسبقٍ ناعم لأيّ محرّك (رغم إمكانه لاحقاً) — نقيس أوّلاً، ثمّ نقرّر.

قفل النسخة-المفردة: engine_lock منفذ "meta_learner" = 8776. مُسجَّل في الوصيّ. ديمو فقط (حارس Trial/Demo).
"""
import os, sys, json, time, math
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")

# 🪟 عديم النافذة: أعِد توجيه stdout/stderr إلى سجلّ (نفس مِزاج بقيّة الدايمونات).
try:
    _lf = open(os.path.join(_RN, "meta_learner.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("meta_learner")
except SystemExit:
    raise
except Exception:
    pass

# ═══ ماجيكاتنا فقط (محرّكاتنا — لا نتعلّم من اليدويّ 0 ولا من خبراء المستخدم الخارجيّين) ═══
OUR_MAGICS = {20260701, 20260706, 20260707, 20260709, 20260703, 20260631}

CFG_F = os.path.join(_RN, "meta_learner_config.json")
BELIEFS_F = os.path.join(_RN, "meta_beliefs.json")
PROGRESS_F = os.path.join(_RN, "meta_learner_progress.json")
STATUS_F = os.path.join(_RN, "meta_learner_status.json")
CONFIDENCE_F = os.path.join(_RN, "confidence.json")   # 🔭 ثقة المحرّكات الذاتيّة (اختياريّ — قد يغيب)
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

# 📡 مصادر الوصل لاشتقاق trigger (اختياريّ — إن تعذّر ⇒ 'unknown'، لا اختراع):
FEEDS = [
    os.path.join(_RN, "brain_trader_feed.jsonl"),
    os.path.join(_RN, "council_sniper_feed.jsonl"),
]
# نافذة الوصل الزمنيّة بين حدث الـfeed (entry) وفتح الصفقة الفعليّة (ثوانٍ).
JOIN_WINDOW_S = 90.0

# ميزاتٌ نتتبّعها (كلّ قيمة-ميزة دلوٌ Beta-Bernoulli مستقلّ).
FEATURES = ("trigger", "symbol", "hour_bucket", "weekday")

G = {"last_progress": None, "status_ts": 0.0, "feed_cache_ts": 0.0, "feed_index": []}


# ─────────────────────────────────────────────────────────────────────────────────────────
def _atomic_write(path, obj):
    """كتابةٌ ذرّيّة (tmp ثمّ replace) — لا يقرأ أحدٌ ملفّاً نصف-مكتوب."""
    try:
        t = path + ".tmp"
        with open(t, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(t, path)
        return True
    except Exception as e:
        print(f"write err {os.path.basename(path)}: {type(e).__name__}: {e}")
        return False


def _cfg():
    d = {"enabled": True, "loop_s": 30.0, "history_days": 14, "oos_frac": 0.30,
         "min_bucket_n": 5, "prior_a": 1.0, "prior_b": 1.0,
         # عتبةٌ صادقة أدنى: حُكمٌ *مبدئيّ* (ثقة 'low') يُسمَح به عند n_oos≥8 كي لا يبقى الشريط
         # فارغاً («وهذا ليه فاضي») بينما البيانات قليلة. الحُكم *الكامل* (ثقة 'med'/'high')
         # يبقى عند n_oos≥20. لا نزوّر: 'no_edge'/'flat' يبقيان صادقَين، و low يُعلَن كـ low.
         "min_oos_provisional": 8, "min_oos_for_verdict": 20,
         "edge_tstat_learn": 2.0, "edge_tstat_flat": 1.0,
         "_note": "🧭📏 المتعلّم-الفوقيّ الصادق: يقيس هل ظروفنا تدفع فعلاً وهل نتحسّن — دون تزوير. "
                  "verdict='no_edge' هو نتيجةٌ مُحترمة (السوق غير متنبَّأ به بهذه النماذج). لا يتاجر. "
                  "min_oos_provisional=8 ⇒ حُكمٌ مبدئيّ صادق مبكّراً (confidence='low')، لا وعدٌ بحافّة."}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        _atomic_write(CFG_F, d)
    return d


# ─────────────────────────────── اشتقاق الميزات ───────────────────────────────
def _hour_bucket(dt):
    """دلو جلسة 0-3: 0=آسيا(0-6) 1=لندن(6-12) 2=نيويورك(12-18) 3=متأخّر(18-24) — بتوقيت UTC."""
    return int(dt.hour // 6)


def _load_feed_index(cfg):
    """يبني فهرسَ أحداث الدخول من الـfeeds لوصل trigger (مُخبّأ 60ث). كلٌّ سجلٌّ = (ts, sym, trigger).
    fail-soft تماماً: غياب/تلف ملفّ ⇒ يُتجاهَل (نبقى على 'unknown' لتلك الصفقات)."""
    now = time.time()
    if G["feed_index"] and now - G["feed_cache_ts"] < 60:
        return G["feed_index"]
    cutoff = now - float(cfg.get("history_days", 14)) * 86400 - 3600
    idx = []
    for fp in FEEDS:
        try:
            if not os.path.exists(fp):
                continue
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("kind") != "entry":
                        continue
                    ts = r.get("ts")
                    sym = r.get("sym") or r.get("symbol")
                    if ts is None or not sym:
                        continue
                    try:
                        ts = float(ts)
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    trig = r.get("trigger") or r.get("tag") or r.get("gene")
                    idx.append((ts, str(sym), (str(trig) if trig else None)))
        except Exception:
            continue
    idx.sort(key=lambda x: x[0])
    G["feed_index"] = idx
    G["feed_cache_ts"] = now
    return idx


def _join_trigger(sym, open_ts, feed_idx):
    """يصل trigger لأقرب حدث دخولٍ في الـfeed لنفس الرمز ضمن JOIN_WINDOW_S — وإلا 'unknown' (لا اختراع)."""
    best = None; best_dt = JOIN_WINDOW_S + 1
    for ts, fsym, trig in feed_idx:
        if fsym != sym or trig is None:
            continue
        dt = abs(ts - open_ts)
        if dt <= JOIN_WINDOW_S and dt < best_dt:
            best_dt = dt; best = trig
    return best or "unknown"


def _closed_trades(cfg):
    """يسحب الصفقات المُغلقة الحقيقيّة (entry==1 = دخول؛ ربح/خسارة الصفقة تُنسَب لدخولها) لماجيكاتنا.
    كلٌّ عنصر = dict ميزات + ts (وقت الفتح) + win (0/1) للترتيب الزمنيّ لاحقاً."""
    days = int(cfg.get("history_days", 14))
    frm = datetime.now() - timedelta(days=days)
    to = datetime.now() + timedelta(hours=12)
    try:
        deals = mt5.history_deals_get(frm, to) or []
    except Exception as e:
        print(f"history err: {type(e).__name__}: {e}")
        return []
    feed_idx = _load_feed_index(cfg)
    out = []
    for d in deals:
        try:
            if int(getattr(d, "magic", 0)) not in OUR_MAGICS:
                continue
            if int(getattr(d, "entry", -1)) != 1:      # 1 = خروج/إغلاق => نتيجة الصفقة مُحقّقة هنا
                continue
            sym = str(getattr(d, "symbol", "") or "")
            if not sym:
                continue
            ts = float(getattr(d, "time", 0) or 0)
            if ts <= 0:
                continue
            pnl = float(getattr(d, "profit", 0.0)) + float(getattr(d, "commission", 0.0)) \
                + float(getattr(d, "swap", 0.0))
            if pnl == 0.0:
                continue                                # لا ربح ولا خسارة (تعديل/بلا نتيجة) — نتجاهل
            dt = datetime.utcfromtimestamp(ts)
            out.append({
                "ts": ts, "win": 1 if pnl > 0 else 0,
                "magic": int(getattr(d, "magic", 0)),   # للربط بثقة المحرّك (confidence.json)
                "trigger": _join_trigger(sym, ts, feed_idx),
                "symbol": sym,
                "hour_bucket": _hour_bucket(dt),
                "weekday": dt.weekday(),
            })
        except Exception:
            continue
    out.sort(key=lambda r: r["ts"])
    return out


# ─────────────────────────────── النموذج المتّصل ───────────────────────────────
class BucketModel:
    """نموذجٌ شفّاف: لكلّ (feature, value) دلو Beta-Bernoulli (a,b) → win_rate = a/(a+b)، مع
    توقّع (متوسّط الربح $) جارٍ. شفّافٌ عمداً (لا صندوق أسود) — «ما الظروف التي تدفع فعلاً»."""

    def __init__(self, prior_a=1.0, prior_b=1.0):
        self.pa = float(prior_a); self.pb = float(prior_b)
        # buckets[feature][value] = {"a","b","n","wins"}
        self.buckets = {f: {} for f in FEATURES}
        self.base_wins = 0; self.base_n = 0     # المعدّل القاعديّ (fallback عند نقص الدلو)

    def fit(self, rows):
        self.buckets = {f: {} for f in FEATURES}
        self.base_wins = 0; self.base_n = 0
        for r in rows:
            self.update(r)

    def update(self, r):
        w = int(r["win"])
        self.base_n += 1; self.base_wins += w
        for f in FEATURES:
            v = r.get(f)
            if v is None:
                continue
            b = self.buckets[f].setdefault(str(v), {"a": self.pa, "b": self.pb, "n": 0, "wins": 0})
            b["n"] += 1; b["wins"] += w
            if w:
                b["a"] += 1
            else:
                b["b"] += 1

    def _base_rate(self):
        return (self.base_wins / self.base_n) if self.base_n else 0.5

    def predict(self, r, min_bucket_n=5):
        """P(win) = متوسّط نسب الدلاء المُحدَّثة كفايةً لميزات هذه الصفقة؛ وإلا المعدّل القاعديّ.
        شفّافٌ لا مُعايَر بالسحر — مجرّد مزجٍ للأدلّة المشروطة المتاحة."""
        rates = []
        for f in FEATURES:
            v = r.get(f)
            if v is None:
                continue
            b = self.buckets[f].get(str(v))
            if b and b["n"] >= min_bucket_n:
                rates.append(b["a"] / (b["a"] + b["b"]))
        return sum(rates) / len(rates) if rates else self._base_rate()

    def beliefs_table(self, min_bucket_n=5):
        """جدول «ما الظروف التي تدفع فعلاً» — مُرتّب بـ|edge| حيث edge = win_rate − المعدّل القاعديّ."""
        base = self._base_rate()
        rows = []
        for f in FEATURES:
            for v, b in self.buckets[f].items():
                n = b["n"]
                if n <= 0:
                    continue
                wr = b["wins"] / n
                post = b["a"] / (b["a"] + b["b"])       # نسبة بايزيّة (مع المُسبق) — أكثر تحفّظاً على n الصغيرة
                edge = wr - base
                # ثقة تقريبيّة: كلّما زاد n قلّ الخطأ المعياريّ للنسبة → ثقة أعلى.
                se = math.sqrt(max(wr * (1 - wr), 1e-9) / n)
                conf = round(max(0.0, 1.0 - min(1.0, se / 0.5)), 3)
                rows.append({
                    "feature": f, "value": v, "n": n,
                    "win_rate": round(wr, 4),
                    "posterior_win_rate": round(post, 4),
                    "expectancy": round(2 * wr - 1, 4),   # توقّع مُطبَّع [-1..1] (لا نزعم دولاراً بلا R موثوق)
                    "edge_vs_base": round(edge, 4),
                    "confidence": conf,
                    "enough_n": n >= min_bucket_n,
                })
        rows.sort(key=lambda x: abs(x["edge_vs_base"]), reverse=True)
        return rows, base


# ─────────────────────────────── القياس الذاتيّ الصادق ───────────────────────────────
def _welch_t(a, b):
    """t-stat لويلش (تباينان غير متساويين) بين مجموعتَي 0/1. يرجع (t, na, nb) أو (None,...)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None, na, nb
    ma = sum(a) / na; mb = sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    denom = math.sqrt(va / na + vb / nb)
    if denom <= 1e-12:
        return 0.0, na, nb
    return (ma - mb) / denom, na, nb


def _self_measure(rows, cfg):
    """الجوهر الصادق: درّب على أقدم 70%، تنبّأ بأحدث 30% OOS، قِس Brier + معايرة + t-stat
    (مجموعة الاحتمال-العالي مقابل المنخفض). لا تزوير — إن لا حافّة فالحُكم 'no_edge'."""
    n = len(rows)
    oos_frac = float(cfg.get("oos_frac", 0.30))
    min_n = int(cfg.get("min_bucket_n", 5))
    prov = int(cfg.get("min_oos_provisional", 8))       # حُكمٌ مبدئيّ صادق (ثقة low)
    full = int(cfg.get("min_oos_for_verdict", 20))      # حُكمٌ كامل (ثقة med/high)
    prog = {
        "ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
        "n_total": n, "n_train": 0, "n_oos": 0,
        "brier": None, "brier_baseline": None, "brier_skill": None,
        "calibration_gap": None, "edge_tstat": None,
        "oos_hi_winrate": None, "oos_lo_winrate": None,
        "verdict": "insufficient_data", "confidence": "none", "improving_vs_last": None,
        "honest_note": "",
    }
    # عتبة الدخول الآن مبنيّةٌ على *العدد الخارجيّ المبدئيّ* (prov) لا على العدد الكلّيّ الكبير:
    # نحتاج فقط أن يكفي التدريب دلوًا صغيراً + عيّنة OOS مبدئيّة. هكذا لا يبقى الشريط فارغاً.
    n_needed = max(10, int(math.ceil(prov / max(oos_frac, 1e-6))))
    if n < n_needed:
        prog["honest_note"] = (f"عيّنة صغيرة (n={n} < {n_needed}) — لا حُكم بعد. أُبلغ الأرقام الخام فقط دون "
                               f"ادّعاء تعلّمٍ أو حافّة. الصدق يقتضي الانتظار حتى تكفي البيانات.")
        return prog

    split = max(1, int(round(n * (1 - oos_frac))))
    train, oos = rows[:split], rows[split:]
    n_oos = len(oos)
    if n_oos < prov:
        prog["n_train"] = len(train); prog["n_oos"] = n_oos
        prog["honest_note"] = (f"عيّنة OOS صغيرة (n_oos={n_oos} < {prov}) — أُبلغ الأرقام لكن الحُكم مؤجّل "
                               f"حتى ≥{prov} صفقة خارجيّة (حدّ مبدئيّ).")
        return prog
    # مستوى الثقة *الصادق* حسب حجم العيّنة الخارجيّة: low إن كانت مبدئيّة فقط (prov≤n_oos<full)،
    # med حتى ضِعف الحدّ الكامل، high فوقه. الثقة تصف *كفاية البيانات* لا وعداً بربح.
    prov_only = n_oos < full
    conf_label = "low" if prov_only else ("high" if n_oos >= 2 * full else "med")

    model = BucketModel(cfg.get("prior_a", 1.0), cfg.get("prior_b", 1.0))
    model.fit(train)

    preds = [max(0.0, min(1.0, model.predict(r, min_n))) for r in oos]
    acts = [int(r["win"]) for r in oos]

    # Brier: متوسّط (p − y)². مرجعٌ: التنبّؤ الثابت بالمعدّل القاعديّ للتدريب (لا معلومة). skill>0 = أفضل من لا-معلومة.
    brier = sum((p - y) ** 2 for p, y in zip(preds, acts)) / len(oos)
    base_rate_train = model._base_rate()
    brier_base = sum((base_rate_train - y) ** 2 for y in acts) / len(oos)
    brier_skill = (1 - brier / brier_base) if brier_base > 1e-9 else 0.0

    # معايرة: |متوسّط p المتوقّع − متوسّط y الفعليّ| (فجوة المعايرة الإجماليّة).
    cal_gap = abs(sum(preds) / len(preds) - sum(acts) / len(acts))

    # t-stat الحافّة: قسّم OOS بوسيط الاحتمال المتوقّع → هل «العالي» يفوز فعلاً أكثر من «المنخفض»؟
    med = sorted(preds)[len(preds) // 2]
    hi = [y for p, y in zip(preds, acts) if p >= med]
    lo = [y for p, y in zip(preds, acts) if p < med]
    tstat, nhi, nlo = _welch_t(hi, lo)

    prog.update({
        "n_train": len(train), "n_oos": len(oos),
        "brier": round(brier, 4), "brier_baseline": round(brier_base, 4),
        "brier_skill": round(brier_skill, 4), "calibration_gap": round(cal_gap, 4),
        "oos_hi_winrate": round(sum(hi) / len(hi), 4) if hi else None,
        "oos_lo_winrate": round(sum(lo) / len(lo), 4) if lo else None,
        "edge_tstat": round(tstat, 3) if tstat is not None else None,
        "oos_hi_n": nhi, "oos_lo_n": nlo,
    })

    # ═══ الحُكم الصادق — لا نُلبِس المصادفة ثوب الذكاء ═══
    t_learn = float(cfg.get("edge_tstat_learn", 2.0))
    t_flat = float(cfg.get("edge_tstat_flat", 1.0))
    prog["confidence"] = conf_label
    prov_caveat = (" ⚠️ حُكمٌ *مبدئيّ* (ثقة منخفضة، n_oos<%d) — مُرشّح للتغيّر مع البيانات." % full) \
        if prov_only else ""
    if tstat is None:
        prog["verdict"] = "insufficient_data"; prog["confidence"] = "none"
        prog["honest_note"] = "تعذّر حساب t-stat (مجموعة أحادية) — لا حُكم."
    elif tstat >= t_learn and brier_skill > 0:
        prog["verdict"] = "learning"
        prog["honest_note"] = (f"إشارة قابلة للقياس: مجموعة الاحتمال-العالي تفوق المنخفض "
                               f"(t={tstat:.2f}≥{t_learn}) وBrier أفضل من لا-معلومة (skill={brier_skill:+.3f}). "
                               f"تحذير الصدق: قد تتلاشى بمزيدٍ من البيانات — تُعاد المعايرة كلّ حلقة.{prov_caveat}")
    elif tstat >= t_flat:
        prog["verdict"] = "flat"
        prog["honest_note"] = (f"إشارة ضعيفة غير حاسمة (t={tstat:.2f}) — لا نزعم حافّة. مسطّح: النموذج "
                               f"لا يميّز الفائز من الخاسر خارج العيّنة تمييزاً موثوقاً.{prov_caveat}")
    else:
        prog["verdict"] = "no_edge"
        prog["honest_note"] = (f"لا حافّة (t={tstat:.2f}، skill={brier_skill:+.3f}). هذا متّسقٌ مع أعمق "
                               f"اكتشافات المشروع: السوق غير متنبَّأ به بهذه الميزات — رمية عملة OOS. "
                               f"نُبلغ الحقيقة لا الأمنية.{prov_caveat}")

    # هل تحسّنّا مقابل آخر قياس؟ (Brier أقلّ = أفضل) — بصدق، بلا تدوير للأرقام لصالح التقدّم.
    last = G.get("last_progress")
    if last and last.get("brier") is not None and prog["brier"] is not None:
        prog["improving_vs_last"] = bool(prog["brier"] < last["brier"] - 1e-6)
    return prog


# ─────────────────────────────── الحلقة ───────────────────────────────
def _top_condition(beliefs, min_n):
    for row in beliefs:                          # مُرتّبة بـ|edge| تنازليّاً
        if row.get("enough_n"):
            return {"feature": row["feature"], "value": row["value"], "n": row["n"],
                    "win_rate": row["win_rate"], "edge_vs_base": row["edge_vs_base"],
                    "confidence": row["confidence"]}
    return None


def _read_confidence():
    """🔭 يقرأ confidence.json (ثقة المحرّكات الذاتيّة) fail-soft. غياب/تلف ⇒ None (لا اختراع).
    نتقبّل شكلين شائعين: {"engines": {"<key>": {"confidence": x}| x}} أو {"<key>": x}. المفتاح
    قد يكون ماجيكاً («20260701») أو اسماً («R Core»/«الحارس»). نُطبّع إلى {key(str): float}."""
    try:
        with open(CONFIDENCE_F, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return None
    src = data.get("engines") if isinstance(data, dict) and isinstance(data.get("engines"), dict) else data
    if not isinstance(src, dict):
        return None
    out = {}
    for k, v in src.items():
        c = None
        if isinstance(v, (int, float)):
            c = float(v)
        elif isinstance(v, dict):
            for ck in ("confidence", "conf", "self_confidence", "belief"):
                if isinstance(v.get(ck), (int, float)):
                    c = float(v[ck]); break
        if c is not None:
            out[str(k)] = max(0.0, min(1.0, c))     # مُقيَّدة [0..1] — لا قيمة شاذّة
    return out or None


def _pearson(xs, ys):
    """معامل ارتباط بيرسون بين متسلسلتَين متساويتَي الطول (≥3). يرجع (r, n) أو (None, n)."""
    n = len(xs)
    if n < 3:
        return None, n
    mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:               # تباينٌ صفريّ ⇒ لا ارتباط مُعرَّف
        return None, n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy), n


def _confidence_belief(rows, cfg):
    """🔭 السؤال الصادق المطلوب: هل *الثقة الذاتيّة الأعلى* تُرافق فعلاً *فوزاً أكثر*؟
    نجمع صفقاتنا المُغلقة حسب الماجيك ⇒ نسبة فوز فعليّة لكلّ محرّك، ونصلها بثقته من
    confidence.json (بالماجيك أو الاسم عبر fleet_mind). ثمّ نحسب ارتباط بيرسون عبر المحرّكات.
    fail-soft تماماً: إن غاب الملفّ أو قلّ التطابق ⇒ نُبلغ 'unobserved'/'insufficient' لا رقماً كاذباً.
    ⚖️ لا نزعم سببيّة ولا حافّة تنبّؤيّة — نقيس *معايرة الثقة* فقط، بصدق."""
    conf = _read_confidence()
    if not conf:
        return {"observed": False, "status": "unobserved",
                "note": "لا ملفّ confidence.json (ثقة ذاتيّة) — لا شيء نصله. لا اختراع."}
    # نسبة الفوز الفعليّة لكلّ ماجيك من صفقاتنا المُغلقة (نحتاج ماجيك في الصفوف)
    by_mag = {}
    for r in rows:
        mg = r.get("magic")
        if mg is None:
            continue
        b = by_mag.setdefault(str(mg), {"wins": 0, "n": 0})
        b["wins"] += int(r["win"]); b["n"] += 1
    # خريطة اسم-محرّك ⇒ ماجيك (من fleet_mind.json) لمطابقة المفاتيح النصّيّة في confidence.json
    name2mag = {}
    try:
        with open(os.path.join(_RN, "fleet_mind.json"), encoding="utf-8-sig") as f:
            fm = json.load(f)
        for mg, info in (fm.get("engines") or {}).items():
            nm = str((info or {}).get("engine") or "").strip()
            if nm:
                name2mag[nm] = str(mg)
    except Exception:
        pass
    pairs = []                                      # (confidence, realized_win_rate, key, n)
    for key, c in conf.items():
        mg = key if key in by_mag else name2mag.get(key)
        if mg is None or mg not in by_mag:
            continue
        b = by_mag[mg]
        if b["n"] < int(cfg.get("min_bucket_n", 5)):
            continue                                # عيّنة المحرّك أصغر من أن تُقارَن
        pairs.append((c, b["wins"] / b["n"], mg, b["n"]))
    if len(pairs) < 3:
        return {"observed": True, "status": "insufficient",
                "n_engines": len(pairs),
                "detail": [{"magic": p[2], "confidence": round(p[0], 3),
                            "win_rate": round(p[1], 4), "n": p[3]} for p in pairs],
                "note": ("ثقةٌ ذاتيّة مقروءة لكنّ المحرّكات المتطابقة قليلة (<3) لحساب ارتباطٍ موثوق. "
                         "نُبلغ الأزواج الخام دون زعم علاقة.")}
    r, ne = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    # حُكمٌ صادق: r موجب معتبر ⇒ الثقة *مُعايَرة* جزئيّاً؛ ~0 ⇒ الثقة لا تتنبّأ بالفوز (المُرجّح).
    if r is None:
        verdict = "flat"; msg = "تباينٌ صفريّ في الثقة أو الفوز — لا ارتباط مُعرَّف."
    elif r >= 0.4:
        verdict = "calibrated"
        msg = (f"ارتباطٌ موجب (r={r:.2f}, k={ne}): الثقة الأعلى ترافقها نسبة فوزٍ أعلى فعلاً — "
               f"معايرةٌ جزئيّة مُشجِّعة، لكنّها *ملاحظة* لا حافّة تنبّؤيّة وقد تتلاشى بمزيدٍ من المحرّكات.")
    elif r <= -0.4:
        verdict = "anti_calibrated"
        msg = (f"ارتباطٌ سالب (r={r:.2f}, k={ne}): الثقة الأعلى ترافقها فوزٌ *أقلّ* — الثقة الذاتيّة "
               f"مُضلّلة هنا. صدقٌ صريح: لا نُصدّق ادّعاء المحرّك بثقته.")
    else:
        verdict = "uncorrelated"
        msg = (f"لا ارتباط يُعتدّ به (r={r:.2f}, k={ne}): الثقة الذاتيّة لا تتنبّأ بالفوز — متّسقٌ مع "
               f"قياس المشروع (السوق غير متنبَّأ به). الثقة تصف الحالة لا النتيجة.")
    return {"observed": True, "status": "measured", "verdict": verdict,
            "pearson_r": round(r, 3) if r is not None else None, "n_engines": ne,
            "detail": [{"magic": p[2], "confidence": round(p[0], 3),
                        "win_rate": round(p[1], 4), "n": p[3]} for p in pairs],
            "note": msg}


def _run_once(cfg):
    rows = _closed_trades(cfg)
    n = len(rows)
    min_n = int(cfg.get("min_bucket_n", 5))

    # النموذج على كامل البيانات (لجدول المعتقدات الشفّاف — ما دفع فعلاً حتى الآن).
    full = BucketModel(cfg.get("prior_a", 1.0), cfg.get("prior_b", 1.0))
    full.fit(rows)
    beliefs, base = full.beliefs_table(min_n)

    conf_belief = _confidence_belief(rows, cfg)   # 🔭 هل الثقة الذاتيّة تُرافق الفوز فعلاً؟ (صادق)

    _atomic_write(BELIEFS_F, {
        "ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
        "n_trades": n, "base_win_rate": round(base, 4),
        "magics": sorted(OUR_MAGICS),
        "note": "🧭 جدول شفّاف: نسبة الربح والتوقّع لكلّ ظرف، مُرتّب بـ|edge| مقابل المعدّل القاعديّ. "
                "قياسٌ لا وعد — enough_n=false يعني الدلو أصغر من أن يُوثَق به.",
        "conditions": beliefs,
        # 🔭 ميزةٌ مُلاحَظة جديدة: معايرة الثقة الذاتيّة (من confidence.json إن وُجد) — صادقة تماماً.
        "confidence_calibration": conf_belief,
    })

    progress = _self_measure(rows, cfg)
    # نمرّر خلاصة معايرة الثقة إلى ملفّ التقدّم أيضاً كي يعرضها الشريط (HUD) صراحةً.
    progress["confidence_calibration"] = {
        "status": conf_belief.get("status"),
        "verdict": conf_belief.get("verdict"),
        "pearson_r": conf_belief.get("pearson_r"),
        "n_engines": conf_belief.get("n_engines"),
    }
    _atomic_write(PROGRESS_F, progress)
    G["last_progress"] = progress

    top = _top_condition(beliefs, min_n)
    _atomic_write(STATUS_F, {
        "ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
        "engine": "المتعلّم-الفوقيّ", "n_trades": n,
        "verdict": progress.get("verdict"),
        "edge_tstat": progress.get("edge_tstat"),
        "brier": progress.get("brier"), "brier_skill": progress.get("brier_skill"),
        "improving_vs_last": progress.get("improving_vs_last"),
        "top_condition": top, "trades_only_ours": True,
        "note": "لا يتاجر — قياسٌ صادق فقط. verdict='no_edge' نتيجةٌ مُحترمة.",
    })
    print(f"🧭 n={n} verdict={progress.get('verdict')} t={progress.get('edge_tstat')} "
          f"brier={progress.get('brier')} skill={progress.get('brier_skill')} "
          f"top={(top or {}).get('value')}")


def _idle_status(reason):
    _atomic_write(STATUS_F, {
        "ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
        "engine": "المتعلّم-الفوقيّ", "n_trades": 0, "verdict": "idle",
        "enabled": False, "reason": reason})


def main():
    ok = False
    for i in range(6):
        if mt5.initialize():
            ok = True; break
        print(f"⏳ init {i + 1}/6"); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5"); return
    print(f"🧭📏 المتعلّم-الفوقيّ بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — ديمو فقط · لا يتاجر · "
          f"قياسٌ صادق")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True) or os.path.exists(KILL1) or os.path.exists(KILL2):
                _idle_status("معطَّل/مقفول — لا قياس (enabled=false أو kill_switch)")
                time.sleep(15); continue
            # حارس الديمو: نقرأ التاريخ فقط، لكنّ التجربة كلّها ديمو — نرفض الحقيقيّ صراحةً.
            acct = mt5.account_info(); srv = str(getattr(acct, "server", "") or "")
            if not acct or not ("Trial" in srv or "Demo" in srv):
                _idle_status(f"الخادم '{srv}' ليس ديمو — قياسٌ ديمو فقط، لا نلمس حساباً حقيقيّاً")
                time.sleep(30); continue
            _run_once(cfg)
            time.sleep(float(cfg.get("loop_s", 30.0)))
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            time.sleep(20)


if __name__ == "__main__":
    main()
