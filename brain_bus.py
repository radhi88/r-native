# -*- coding: utf-8 -*-
"""brain_bus.py — 🚌 ناقل العقل: يجعل تبادل المعلومات بين المحرّكات صريحاً وحيّاً (قراءة فقط، لا تداول إطلاقاً)
================================================================================
شكوى المستخدم: «ما فيه تبادل معلومات بينهم». الحقيقة أنّ التبادل يحدث فعلاً — لكنه ضمنيّ ومبعثر عبر
ملفّات JSON/JSONL. هذا المحرّك يجعله **صريحاً**: كل ~2ث يقرأ ذيول التغذيات وملفّات الحالة/التنسيق
ويصهرها في **تيّار رسائل مُهيكلة** {ts, iso, frm, to, kind, sym, payload, note} تُصوّر مسار المعلومة
الذي يجري أصلاً — **لا يخترع رسالةً**، كل رسالة مشتقّة من حدثٍ حقيقيّ.

الصدق هو المنتج. أعمق قياس في هذا المشروع: السوق **غير قابل للتنبّؤ** بهذه النماذج (مجلس/شبكة عصبيّة/
مؤشّرات = وجه عملة خارج العيّنة). لذلك هذا الناقل **لا يزيّف حافّةً ولا يزيّف تقدّم تعلّم**. المُقيّم-الفوقيّ
(meta-learner) يقيس معايرة الحكم المصهور خارج-العيّنة فعلاً — ولو كانت مسطّحةً أو سالبة يقولها كما هي.
القيمة المُسلَّمة: الشفافية + تبادل معلومات صادق + قياس ذاتيّ نزيه — **لا وعدٌ بربح**.

READ-ONLY تماماً: لا اتّصال MT5، لا order_send، لا فتح/إغلاق/تعديل. يقرأ ملفّات r_native فقط. ديمو-فقط.

المخرجات (ذرّياً كل دورة):
  data/r_native/brain_bus.jsonl  — إلحاق التيّار (يُقلَّم لآخر 5000 سطر عند تجاوز ~5MB)
  data/r_native/brain_bus.json   — آخر 60 رسالة + عدّاد-لكل-حافّة (آخر 5د) + إجمالي اليوم + معايرة صادقة
"""
import os, sys, io

# ── أوّل شيء: تحويل stdout/stderr لملفّ سجلّ (pythonw بلا كونسول) — نمط desk_scoreboard ──
_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
_LOG_PATH = os.path.join(_RN, "brain_bus.out.log")
os.makedirs(_RN, exist_ok=True)
try:
    _log_f = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
except Exception:
    try:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
    except Exception:
        pass

import json, time
from collections import deque, defaultdict, OrderedDict
from datetime import datetime, timezone

# ── قفل النسخة الوحيدة (يخرج هادئاً إن كانت نسخة أخرى تعمل) ──
try:
    import engine_lock
    engine_lock.claim("brain_bus")
except SystemExit:
    raise
except Exception as e:
    print(f"[lock] engine_lock غير متاح ({e}) — نتابع بدون قفل")

# ── الثوابت والمسارات ──
LOOP_S = 2.0
OUT_JSONL = os.path.join(_RN, "brain_bus.jsonl")
OUT_JSON = os.path.join(_RN, "brain_bus.json")

JSONL_MAX_BYTES = 5 * 1024 * 1024   # ~5MB سقف قبل التقليم
JSONL_KEEP_LINES = 5000             # يُقلَّم لآخر هذا العدد عند التجاوز
RECENT_MSGS = 60                    # آخر كم رسالة في brain_bus.json (تقرؤها الواجهة)
EDGE_WINDOW_S = 300.0              # نافذة عدّاد-لكل-حافّة (5د)
TAIL_LINES = 60                    # كم سطراً نقرأ من ذيل كل تغذية في الدورة
SEEN_CAP = 4000                    # سقف بصمات الأحداث المرئيّة لكل مصدر (منع تضخّم الذاكرة)

# مصادر التغذية (JSONL نتبع ذيلها) — (مسار، مفتاح-دالّة-الاشتقاق)
FEED_SENTINEL = os.path.join(_RN, "gold_sentinel_feed.jsonl")
FEED_BRAIN = os.path.join(_RN, "brain_trader_feed.jsonl")
FEED_SNIPER = os.path.join(_RN, "council_sniper_feed.jsonl")
FEED_MIMIC = os.path.join(_RN, "radhi_mimic_feed.jsonl")
FEED_LEVELMULTI = os.path.join(_RN, "level_sentinel_multi_feed.jsonl")

# ملفّات الحالة/التنسيق (نقرؤها كاملةً كل دورة، نشتقّ رسائلَ من تغيّرها الحقيقيّ)
F_COUNCIL = os.path.join(_RN, "agent_council.json")
F_SCORE = os.path.join(_RN, "desk_scoreboard.json")
F_FLEET = os.path.join(_RN, "fleet_mind.json")
F_UNIFIED = os.path.join(_RN, "unified_brain.json")

# أسماء المحرّكات العربيّة (للحقلين frm/to)
E_SENTINEL = "الحارس"
E_RCORE = "R Core"
E_COUNCIL = "المجلس(96)"
E_SNIPER = "قنّاص المجلس"
E_MIMIC = "محاكي راضي"
E_LEVELMULTI = "حارس العملات"
E_BOARD = "السبورة"
E_FLEET = "العقل الجماعيّ"
E_UNIFIED = "المخّ الواحد"

# ملاحظة الصدق الموحّدة (تُلحق بكل رسالة تنبّؤ/إجماع/صهر — لا نزيّف حافّة)
NOTE_HONEST = ("تبادلٌ حقيقيّ يُعرض شفّافاً — قياس المشروع: لا حافّة تنبّؤيّة (~50% خارج العيّنة). "
               "قيمته الشفافية لا الربح.")


def atomic_write(path, obj):
    """كتابة ذرّية: ملفّ مؤقّت ثمّ os.replace (utf-8، ensure_ascii=False)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _load_json(path):
    """قراءة JSON fail-soft (utf-8-sig لأجل BOM) — يعيد None عند أيّ فشل."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, (dict, list)) else None
    except Exception:
        return None


def _tail_lines(path, n):
    """آخر n سطراً من ملفّ نصّيّ، قراءة كتليّة من الذيل (رخيصة على ملفّات كبيرة). fail-soft."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 8192
            data = b""
            pos = size
            while pos > 0 and data.count(b"\n") <= n:
                step = min(block, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
            text = data.decode("utf-8", errors="replace")
    except Exception:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-n:]


def _parse_jsonl_tail(path, n):
    """آخر n كائن JSON صالح من ذيل ملفّ JSONL. يتخطّى السطور المعطوبة (كتابة جزئيّة). fail-soft."""
    out = []
    for ln in _tail_lines(path, n):
        try:
            o = json.loads(ln)
            if isinstance(o, dict):
                out.append(o)
        except Exception:
            pass
    return out


class SeenSet:
    """مجموعة بصمات-أحداث مرئيّة لكل مصدر (منع إصدار نفس الحدث مرّتين). محدودة الحجم (FIFO)."""
    def __init__(self, cap=SEEN_CAP):
        self._d = OrderedDict()
        self._cap = cap

    def add_if_new(self, key):
        """يعيد True إن كان جديداً (ويسجّله)، False إن سبق أن رُئي."""
        if key in self._d:
            return False
        self._d[key] = 1
        if len(self._d) > self._cap:
            self._d.popitem(last=False)
        return True


def _fnum(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _dir_to_side(d):
    """يحوّل الاتجاه العدديّ/النصّيّ إلى buy/sell/flat بصدق."""
    if isinstance(d, str):
        s = d.strip().lower()
        if s in ("buy", "long"):
            return "buy"
        if s in ("sell", "short"):
            return "sell"
    dv = _fnum(d)
    if dv is None:
        return "flat"
    if dv > 0:
        return "buy"
    if dv < 0:
        return "sell"
    return "flat"


# ══════════════════════════════════════════════════════════════════════════════
#  المُقيّم-الفوقيّ الصادق: معايرة حكم المخّ الواحد خارج-العيّنة
#  عند رصد حكم قناعة (dir != 0) لرمزٍ نسجّل توقّعاً معلّقاً: (اتّجاه، سعرٌ مرجعيّ). بعد HORIZON نقيس
#  هل تحرّك السعر في الاتّجاه المُتوقَّع. النتيجة تُقاس فعلاً — لا نزيّفها ولو كانت ≈50% أو أسوأ.
#  السعر المرجعيّ يُؤخذ من تغذية سوقٍ حقيقيّة (نبض/حارس) — إن غاب لا نسجّل توقّعاً (لا نخترع).
# ══════════════════════════════════════════════════════════════════════════════
CALIB_HORIZON_S = 180.0     # أفق تقييم التوقّع (3د)
CALIB_MOVE_MIN = 1e-9      # حركة أدنى تُعدّ إشارة (تحت هذا = تعادل، لا يُحسب صواباً)
CALIB_MAX_OPEN = 500        # سقف التوقّعات المعلّقة
CALIB_MAX_RESOLVED = 3000  # سقف تاريخ التوقّعات المُقيَّمة (نافذة متدحرجة)


class MetaCalibrator:
    """يقيس معايرة حكم المخّ الواحد خارج-العيّنة بصدق (dir مقابل حركة السعر الفعليّة بعد HORIZON)."""
    def __init__(self):
        self.open = deque()      # (resolve_at, sym, side, ref_price)
        self.n = 0               # مجموع التوقّعات المُقيَّمة
        self.hits = 0            # التي تحرّك فيها السعر بالاتّجاه المُتوقَّع
        self.pushed = set()      # (sym, verdict_ts) كي لا نسجّل نفس الحكم مرّتين

    def maybe_predict(self, sym, side, ref_price, verdict_ts, now):
        """يسجّل توقّعاً معلّقاً إن كان جديداً وله سعرٌ مرجعيّ حقيقيّ."""
        if side not in ("buy", "sell") or ref_price is None:
            return
        key = (sym, round(verdict_ts, 1))
        if key in self.pushed:
            return
        self.pushed.add(key)
        if len(self.pushed) > CALIB_MAX_OPEN * 4:
            self.pushed = set(list(self.pushed)[-CALIB_MAX_OPEN * 2:])
        self.open.append((now + CALIB_HORIZON_S, sym, side, float(ref_price)))
        while len(self.open) > CALIB_MAX_OPEN:
            self.open.popleft()

    def resolve(self, now, price_of):
        """يُقيّم التوقّعات التي حان أفقها مقابل السعر الحيّ الحقيقيّ (price_of: sym->price أو None)."""
        while self.open and self.open[0][0] <= now:
            _, sym, side, ref = self.open.popleft()
            px = price_of(sym)
            if px is None:
                continue                       # لا سعرٌ حاليّ ⇒ لا نُقيّم (لا نخترع نتيجة)
            move = px - ref
            if abs(move) < CALIB_MOVE_MIN:
                self.n += 1                    # تعادل يُحسب كعيّنة (لا إصابة)
                continue
            up = move > 0
            correct = (up and side == "buy") or ((not up) and side == "sell")
            self.n += 1
            if correct:
                self.hits += 1
        # نافذة متدحرجة على العدّاد كي تبقى المعايرة «حديثة» لا تراكميّة أبديّة
        if self.n > CALIB_MAX_RESOLVED:
            ratio = self.hits / self.n
            self.n = CALIB_MAX_RESOLVED
            self.hits = int(round(ratio * CALIB_MAX_RESOLVED))

    def report(self):
        """تقرير معايرة صادق — يقول صراحةً إن كانت العيّنة صغيرة أو الدقّة ≈ وجه-عملة."""
        if self.n < 30:
            return {
                "n": self.n, "hits": self.hits, "accuracy": None,
                "horizon_s": int(CALIB_HORIZON_S),
                "verdict": "عيّنة غير كافية بعد (لا ندّعي شيئاً)",
                "honest": "المعايرة تُبنى من صفقات-توقّعٍ حقيقيّة فقط؛ ننتظر n≥30 قبل أيّ حكم.",
            }
        acc = self.hits / self.n
        if acc <= 0.52:
            verdict = "≈ وجه عملة (لا حافّة) — كما يقول قياس المشروع خارج العيّنة"
        elif acc <= 0.55:
            verdict = "فوق العشوائيّ هامشياً — غالباً ضجيج، لا يكفي بعد السبريد"
        else:
            verdict = f"دقّة {acc*100:.1f}% على n={self.n} — يُراقَب بحذر، ليست وعداً بربح"
        return {
            "n": self.n, "hits": self.hits, "accuracy": round(acc, 4),
            "horizon_s": int(CALIB_HORIZON_S), "verdict": verdict,
            "honest": "دقّة اتّجاه حكم المخّ الواحد على أفقٍ قصير، مقيسة فعلاً — تُعرض ولو مسطّحة/سالبة.",
        }


# ══════════════════════════════════════════════════════════════════════════════
#  الحالة عبر الدورات
# ══════════════════════════════════════════════════════════════════════════════
class BusState:
    def __init__(self):
        self.recent = deque(maxlen=RECENT_MSGS)     # آخر الرسائل (للواجهة)
        self.edge_hits = deque()                    # (ts, edge_key) لعدّاد-لكل-حافّة (5د)
        self.day_count = 0                          # إجمالي رسائل اليوم
        self.day_key = None                         # yyyy-mm-dd (UTC) لتصفير العدّاد يومياً
        # بصمات مرئيّة لكل مصدر
        self.seen = defaultdict(SeenSet)
        # آخر لقطة لملفّات الحالة (لإصدار رسالة فقط عند تغيّر حقيقيّ)
        self.last_council = {}     # sym -> (pct, dir)
        self.last_fleet = {}       # magic -> (mult, state)
        self.last_score = {}       # magic -> net_today
        self.last_unified = {}     # sym -> (dir, conv)
        # أحدث سعرٍ حقيقيّ لكل رمز (من تغذيات السوق) — للمعايرة الصادقة
        self.price = {}            # sym -> price
        self.calib = MetaCalibrator()

    def price_of(self, sym):
        return self.price.get(sym)


def _mk(now, frm, to, kind, sym, payload, note=""):
    """يبني رسالة موحّدة {ts, iso, frm, to, kind, sym, payload, note}."""
    return {
        "ts": round(now, 2),
        "iso": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "frm": frm, "to": to, "kind": kind,
        "sym": sym or "", "payload": payload, "note": note,
    }


def _edge_key(m):
    """مفتاح-الحافّة لعدّاد التدفّق: frm→to/kind."""
    return f"{m['frm']}→{m['to']}/{m['kind']}"


# ══════════════════════════════════════════════════════════════════════════════
#  مشتقّات الرسائل من كل مصدر (كلٌّ يعيد قائمة رسائل جديدة فقط)
# ══════════════════════════════════════════════════════════════════════════════
def derive_sentinel(st, now):
    """gold_sentinel_feed: تنبيه (kind/level/side/score) ⇒ {الحارس→R Core, trigger}. مُشغّل R Core (أ)."""
    out = []
    for o in _parse_jsonl_tail(FEED_SENTINEL, TAIL_LINES):
        ts = _fnum(o.get("ts"))
        if ts is None:
            continue
        key = f"{ts}|{o.get('kind')}|{o.get('level')}"
        if not st.seen["sentinel"].add_if_new(key):
            continue
        kind = str(o.get("kind", ""))
        # الاتّجاه من نوع الحدث (كسر-صعوديّ/ارتداد شراء = buy، عكسه = sell) — نبقى محايدين إن غمض
        side = "buy" if ("صعود" in kind or "شراء" in kind or "BOUNCE" in kind.upper()) else \
               ("sell" if ("هبوط" in kind or "بيع" in kind or "REJECT" in kind.upper()) else "flat")
        px = _fnum(o.get("price"))
        if px is not None:
            st.price["XAUUSDm"] = px
        out.append(_mk(now, E_SENTINEL, E_RCORE, "trigger", "XAUUSDm",
                       {"side": side, "score": o.get("score"), "level": o.get("level")},
                       "مُشغّل R Core (أ): شرطُ مستوىً حاضر — دعمُ قرارٍ لا حافّة."))
    return out


def derive_council(st, now):
    """agent_council.json: إجماع لكل رمز (pct/dir) ⇒ {المجلس→قنّاص المجلس, consensus} + {→R Core فيتو-مدخل}."""
    out = []
    d = _load_json(F_COUNCIL)
    if not isinstance(d, dict):
        return out
    syms = d.get("symbols") or {}
    if not isinstance(syms, dict):
        return out
    for sym, s in syms.items():
        if not isinstance(s, dict):
            continue
        pct = _fnum(s.get("agreement_pct"))
        dv = s.get("dir")
        if pct is None:
            continue
        prev = st.last_council.get(sym)
        cur = (round(pct, 1), dv)
        if prev == cur:
            continue                            # لا تغيّر ⇒ لا رسالة (منع تكرار)
        st.last_council[sym] = cur
        side = _dir_to_side(dv)
        payload = {"pct": round(pct, 1), "dir": dv, "side": side,
                   "verdict": s.get("verdict"), "n_voted": s.get("n_voted")}
        out.append(_mk(now, E_COUNCIL, E_SNIPER, "consensus", sym, payload, NOTE_HONEST))
        out.append(_mk(now, E_COUNCIL, E_RCORE, "consensus", sym,
                       {"pct": round(pct, 1), "side": side, "role": "veto-input"},
                       "مدخلُ فيتو لـ R Core — إجماعٌ يُستشار لا يُطاع عمياً."))
    return out


def _derive_executor_feed(st, path, source_key, engine_name, now):
    """تغذية منفّذ (دخول/فيتو/إغلاق) ⇒ {المنفّذ→السبورة, kind, payload:{reason/pnl/...}}."""
    out = []
    for o in _parse_jsonl_tail(path, TAIL_LINES):
        ts = _fnum(o.get("ts"))
        if ts is None:
            continue
        kind = str(o.get("kind", "")) or "event"
        key = f"{ts}|{kind}|{o.get('sym') or o.get('tag') or ''}|{o.get('ticket') or ''}"
        if not st.seen[source_key].add_if_new(key):
            continue
        sym = str(o.get("sym", "") or "")
        px = _fnum(o.get("px"))
        if px is not None and sym:
            st.price[sym] = px
        # payload صادق: نلتقط ما وُجد فعلاً (سبب/ربح/اتّجاه/توافق) دون اختراع
        payload = {}
        for k_src, k_dst in (("dir", "side"), ("reason", "reason"), ("veto", "veto"),
                             ("pnl", "pnl"), ("lot", "lot"), ("risk_usd", "risk_usd"),
                             ("agreement_pct", "pct"), ("agree", "agree"),
                             ("confluence", "confluence"), ("tag", "tag")):
            if k_src in o and o[k_src] is not None:
                payload[k_dst] = o[k_src]
        out.append(_mk(now, engine_name, E_BOARD, kind, sym, payload,
                       "حدثٌ تنفيذيّ حقيقيّ يُبلَّغ للسبورة (قراءة فقط)."))
    return out


def derive_executors(st, now):
    out = []
    out += _derive_executor_feed(st, FEED_BRAIN, "brain", E_RCORE, now)
    out += _derive_executor_feed(st, FEED_SNIPER, "sniper", E_SNIPER, now)
    out += _derive_executor_feed(st, FEED_MIMIC, "mimic", E_MIMIC, now)
    out += _derive_executor_feed(st, FEED_LEVELMULTI, "levelmulti", E_LEVELMULTI, now)
    return out


def derive_scoreboard(st, now):
    """desk_scoreboard.json: صافي كل ماجيك ⇒ {السبورة→العقل الجماعيّ, perf} عند تغيّر الصافي فقط."""
    out = []
    d = _load_json(F_SCORE)
    if not isinstance(d, dict):
        return out
    for row in (d.get("magics") or []):
        if not isinstance(row, dict):
            continue
        magic = row.get("magic")
        net = _fnum(row.get("net_today"))
        if magic is None or net is None:
            continue
        prev = st.last_score.get(magic)
        if prev is not None and abs(prev - net) < 1e-9:
            continue                            # صافٍ ثابت ⇒ لا رسالة
        st.last_score[magic] = net
        out.append(_mk(now, E_BOARD, E_FLEET, "perf", "",
                       {"magic": magic, "name": row.get("name"), "net": round(net, 2),
                        "net_3d": row.get("net_3d"), "wr_today": row.get("wr_today")},
                       "أداءٌ حقيقيّ يُغذّي قرار الحوكمة (خنق/تحفيز)."))
    return out


def derive_fleet(st, now):
    """fleet_mind.json: مضاعف لكل ماجيك ⇒ {العقل الجماعيّ→المحرّك, govern} عند تغيّر القرار. قرارُ الخنق."""
    out = []
    d = _load_json(F_FLEET)
    if not isinstance(d, dict):
        return out
    fleet_state = d.get("fleet_state")
    engines = d.get("engines") or {}
    if not isinstance(engines, dict):
        return out
    for magic, e in engines.items():
        if not isinstance(e, dict):
            continue
        mult = _fnum(e.get("lot_mult"))
        if mult is None:
            mult = _fnum(e.get("standing_mult"))
        if mult is None:
            continue
        cur = (round(mult, 3), fleet_state)
        if st.last_fleet.get(magic) == cur:
            continue                            # نفس المضاعف ونفس الحالة ⇒ لا رسالة
        st.last_fleet[magic] = cur
        out.append(_mk(now, E_FLEET, str(e.get("engine") or magic), "govern", "",
                       {"magic": magic, "mult": round(mult, 3), "state": fleet_state,
                        "why": e.get("why")},
                       "قرارُ خنق/تحفيز حقيقيّ يقرؤه المحرّك ويقيس لوته."))
    return out


def derive_unified(st, now):
    """unified_brain.json: حكم لكل رمز ⇒ {المخّ الواحد→R Core, fuse}. + يغذّي المعايرة الصادقة."""
    out = []
    d = _load_json(F_UNIFIED)
    if not isinstance(d, dict):
        return out
    ts = _fnum(d.get("ts"), now)
    syms = d.get("symbols") or {}
    if not isinstance(syms, dict):
        return out
    for sym, s in syms.items():
        if not isinstance(s, dict):
            continue
        dv = s.get("dir")
        conv = _fnum(s.get("conviction"))
        if conv is None:
            conv = _fnum(s.get("fused"))
        if conv is None:
            continue
        prev = st.last_unified.get(sym)
        cur = (dv, round(conv, 3))
        # نُسجّل توقّعاً للمعايرة عند حكمٍ ذي قناعة (dir != 0) ولو لم تتغيّر الرسالة — بصدق
        side = _dir_to_side(dv)
        if side in ("buy", "sell"):
            st.calib.maybe_predict(sym, side, st.price.get(sym), ts, now)
        if prev == cur:
            continue                            # لا تغيّر ⇒ لا رسالة (المعايرة سُجّلت أعلاه)
        st.last_unified[sym] = cur
        out.append(_mk(now, E_UNIFIED, E_RCORE, "fuse", sym,
                       {"dir": dv, "side": side, "conv": round(conv, 3),
                        "agree": s.get("agree"), "verdict": s.get("verdict")},
                       NOTE_HONEST))
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  كتابة المخرجات
# ══════════════════════════════════════════════════════════════════════════════
def _append_jsonl(messages):
    """يُلحق الرسائل بـ brain_bus.jsonl، ويُقلّم لآخر JSONL_KEEP_LINES عند تجاوز السقف. fail-soft."""
    if not messages:
        return
    try:
        with open(OUT_JSONL, "a", encoding="utf-8") as f:
            for m in messages:
                f.write(json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e:
        print(f"[jsonl] فشل الإلحاق: {e}")
        return
    # تقليم عند تجاوز الحجم
    try:
        if os.path.getsize(OUT_JSONL) > JSONL_MAX_BYTES:
            lines = _tail_lines(OUT_JSONL, JSONL_KEEP_LINES)
            tmp = OUT_JSONL + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
            os.replace(tmp, OUT_JSONL)
            print(f"[jsonl] قُلّم لآخر {len(lines)} سطر")
    except Exception as e:
        print(f"[jsonl] فشل التقليم: {e}")


def _roll_day(st, now):
    """يصفّر عدّاد اليوم عند تغيّر التاريخ (UTC)."""
    dk = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if st.day_key != dk:
        st.day_key = dk
        st.day_count = 0


def build_status(st, now):
    """يبني brain_bus.json: آخر الرسائل + عدّاد-لكل-حافّة (5د) + إجمالي اليوم + معايرة صادقة."""
    # نافذة عدّاد-لكل-حافّة (5د): نُسقط القديم
    cutoff = now - EDGE_WINDOW_S
    while st.edge_hits and st.edge_hits[0][0] < cutoff:
        st.edge_hits.popleft()
    edge_counts = defaultdict(int)
    for _, ek in st.edge_hits:
        edge_counts[ek] += 1
    edges = sorted(({"edge": k, "count": v} for k, v in edge_counts.items()),
                   key=lambda r: r["count"], reverse=True)
    return {
        "updated": round(now, 1),
        "iso": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "recent": list(st.recent),
        "edges_5min": edges,
        "msgs_5min": len(st.edge_hits),
        "total_today": st.day_count,
        "calibration": st.calib.report(),
        "honesty": ("ناقل العقل: تبادلٌ حقيقيّ بين المحرّكات يُعرض صريحاً (قراءة فقط، لا تداول). "
                    "المعايرة تُقاس فعلاً؛ إن كانت مسطّحة فهذا هو الصدق — لا حافّة مزيّفة، لا تعلّمٌ مزيّف."),
    }


def cycle(st):
    """دورة واحدة: اجمع الرسائل الجديدة من كل مصدر، ألحقها، حدّث المعايرة، اكتب المخرجات. fail-soft كليّاً."""
    now = time.time()
    _roll_day(st, now)

    msgs = []
    for fn in (derive_sentinel, derive_council, derive_executors,
               derive_scoreboard, derive_fleet, derive_unified):
        try:
            msgs += fn(st, now)
        except Exception as e:
            print(f"[derive] {getattr(fn, '__name__', fn)} فشل: {e}")

    # حلّ توقّعات المعايرة التي حان أفقها مقابل الأسعار الحيّة الحقيقيّة
    try:
        st.calib.resolve(now, st.price_of)
    except Exception as e:
        print(f"[calib] فشل الحلّ: {e}")

    # ترتيب زمنيّ ثمّ تسجيل
    msgs.sort(key=lambda m: m["ts"])
    for m in msgs:
        st.recent.append(m)
        st.edge_hits.append((m["ts"], _edge_key(m)))
        st.day_count += 1

    _append_jsonl(msgs)
    try:
        atomic_write(OUT_JSON, build_status(st, now))
    except Exception as e:
        print(f"[status] فشل كتابة brain_bus.json: {e}")
    return len(msgs)


def main():
    print(f"\n[brain_bus] بدء التشغيل {datetime.now().isoformat()} — ناقل قراءة فقط، لا MT5، لا تداول")
    st = BusState()
    while True:
        t0 = time.time()
        try:
            n = cycle(st)
            if n:
                print(f"[cycle] {n} رسالة جديدة (إجمالي اليوم {st.day_count})")
        except Exception as e:
            import traceback
            print(f"[cycle] خطأ: {e}\n{traceback.format_exc()}")
            time.sleep(2)
            continue
        elapsed = time.time() - t0
        time.sleep(max(0.2, LOOP_S - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"[fatal] {e}\n{traceback.format_exc()}")
