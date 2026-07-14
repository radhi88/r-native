"""scoreboard_learn.py — "تدرّج الفِرق" لغرفة الحرب army_warroom.py، مُستخرَجاً في دوال نقيّة
قابلة للاستيراد والاختبار. الهدف الصريح: **تقليل النزيف على الإشارات غير المُثبتة** عبر تدرّج
صلاحية التنفيذ — لا اختراع أفضلية، لا وعد ربح.

لماذا ملف منفصل؟ المنفّذ الحيّ (magic 20260618) يعمل الآن ولا يُعدَّل بنفسي. هذا الملف إضافي بحت:
لا order_send، لا حالة عالمية، لا أعراض جانبية عدا قراءة friday_db (قراءة فقط هنا — الإدراج يبقى
للمنفّذ). army_warroom يستورده ويستبدل بوّابة maybe_execute (السطور 201-208) بنداء tier/live_policy
(انظر "مواصفة التعديل الحرفية" في رسالة التسليم).

تدرّج الفِرق (tier) — ثلاث حالات لكل فرقة (symbol):
  PROVEN  : n>=N_PROVEN و expectancy>+T_POS  → لوت كامل، تكديس مسموح.
  BANNED  : n>=N_MIN   و expectancy<-T_NEG   → **لا تنفيذ حيّ إطلاقاً** (يبقى التسجيل/التقييم
            بالورق في record_and_judge كي تتعافى وتُرقَّى لاحقاً — لا قتل دائم).
  EXPLORE : غير ذلك (عيّنة صغيرة، أو حافّة قرب الصفر) → **أصغر لوت + مركز واحد فقط** لهذه الفرقة
            (ميزانية استكشاف ضئيلة: ندفع ثمناً صغيراً جداً لنقيس الحافّة قبل أن نثق).

كيف يوقف النزيف:
  * BANNED بلا مال        → الخاسر المُثبت يتوقّف تماماً عن صرف المال (لكن يبقى يُقيَّم بالورق).
  * EXPLORE ضئيل          → غير المُثبت يدخل بأصغر لوت ومركز واحد فقط = خسارته القصوى دقيقة.
  * PROVEN فقط يأخذ المال الكامل والتكديس → رأس المال يذهب حيث ثبتت الحافّة قياساً، لا ظنّاً.

إصلاح العيب (1) — التأرجح: الاستئناف من BANNED محكوم بـ hysteresis + dwell:
  لا تُرفَع فرقة من BANNED حتى (أ) يتعافى توقّعها التراكمي فوق -RESUME_EXPR_FLOOR، و(ب) تكون نافذتها
  الحديثة موجبة فوق RESUME_RECENT_THRESH، و(ج) مرّ عليها MIN_TRADES_SINCE_BAN صفقة منذ آخر حظر.
  حتى حينها لا تقفز PROVEN مباشرة — تمرّ بـ EXPLORE أولاً. لا تذبذب bang-bang.

إصلاح العيب (2) — مطابقة بالأقدم-زمناً: judge_pending يطابق الصفقة المغلقة في friday_db بـ
  ticket/position_id الذي خُزّن وقت الدخول الحيّ (لا بأقدم صفقة لنفس الرمز)، ويحسب R من
  (exit-entry)*side ÷ risk الخاص بنفس الإشارة (لا خلط دخول-DB بمخاطرة-إشارة، لا خلط صفقات).
  لو لا ticket (إشارة ظلّية لم تُنفَّذ حيّاً) → يسقط لهدف/وقف/سقف-زمن الإشارة الظلّية كما السابق.

مَقبِض FridayDB يُمرَّر مشتركاً (db=...) فلا يُفتح اتصال لكل نداء. db=False يتجاوز DB صراحةً (للاختبار).

تشغيل تحقّق:  python -c "import scoreboard_learn"
              python scoreboard_learn.py        # فحوص دخان نقيّة (بلا MT5/DB)
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Optional, Sequence

# ============================================================================ ثوابت التدرّج
# عتبات الترقية/الحظر (محافِظة عمداً — أصغر عيّنة للحظر من الترقية: نوقف النزيف أسرع ممّا نثق).
N_PROVEN: int = 6          # حدّ أدنى من الصفقات لاعتماد فرقة PROVEN
T_POS: float = 0.05        # expectancy يجب أن يتجاوز هذا (+R/صفقة) لتصبح PROVEN
N_MIN: int = 4             # حدّ أدنى من الصفقات للحكم بالحظر (أصغر = نوقف الخاسر بسرعة)
T_NEG: float = 0.05        # expectancy تحت -هذا → BANNED

# ميزانية الاستكشاف (EXPLORE): أصغر لوت + مركز واحد فقط لهذه الفرقة.
EXPLORE_LOT_FRAC: float = 0.25   # كسر من اللوت المحسوب (سقف 2% يبقى يحكم أيضاً) — ضئيل عمداً
EXPLORE_MAX_POS: int = 1         # مركز واحد فقط لفرقة استكشافية (لا تكديس)

# استئناف من BANNED — hysteresis + dwell (إصلاح العيب 1: لا تأرجح).
RESUME_EXPR_FLOOR: float = -0.02   # التوقّع التراكمي يجب أن يتعافى فوق هذا (أقرب للصفر من -T_NEG)
RESUME_RECENT_THRESH: float = 0.05 # متوسّط النافذة الحديثة يجب أن يتجاوز هذا (موجب)
RESUME_RECENT_MIN: int = 4         # حجم النافذة الحديثة المطلوبة للحكم على التعافي
MIN_TRADES_SINCE_BAN: int = 4      # صفقات يجب أن تمرّ (بالورق) منذ آخر حظر قبل التفكير في الرفع
RECENT_WINDOW: int = 12            # طول الذاكرة الدوّارة recentR المحفوظة في صف السبورة

# تقييم-عند-الإغلاق (نفضّل R الحقيقي من إغلاق MT5 على أفق 2h الثابت).
EXEC_MAGIC: int = 20260618
JUDGE_HORIZON_S: int = 2 * 3600    # سقف زمني احتياطي لو لم تُغلق الصفقة أبداً (مرآة army_warroom)

SQUAD_NAME: str = "army_warroom"   # اسم الفصيل في جدول friday_db.scoreboard

# قيم التدرّج الثابتة (للوضوح ومنع الأخطاء المطبعية).
PROVEN: str = "PROVEN"
EXPLORE: str = "EXPLORE"
BANNED: str = "BANNED"


# ============================================================================ توقّع
def expectancy(stats_row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """توقّع R لكل صفقة = sumR / n (أو None إن لا عيّنة). يقبل صف السبورة كما هو {n,wins,sumR,...}."""
    if not stats_row:
        return None
    n = int(stats_row.get("n", 0) or 0)
    if n <= 0:
        return None
    return float(stats_row.get("sumR", 0.0) or 0.0) / n


def _recent_list(stats_row: Optional[Mapping[str, Any]],
                 recent: Optional[Sequence[float]]) -> list[float]:
    """نافذة النتائج الحديثة: تُمرَّر صراحةً، أو تُقرأ من الحقل الإضافي recentR في صف السبورة."""
    if recent is not None:
        return [float(x) for x in recent]
    if stats_row:
        rr = stats_row.get("recentR")
        if isinstance(rr, (list, tuple)):
            return [float(x) for x in rr]
    return []


# ============================================================================ التدرّج (tier)
def tier(stats_row: Optional[Mapping[str, Any]],
         recent: Optional[Sequence[float]] = None,
         *, n_proven: int = N_PROVEN, t_pos: float = T_POS,
         n_min: int = N_MIN, t_neg: float = T_NEG,
         resume_expr_floor: float = RESUME_EXPR_FLOOR,
         resume_recent_thresh: float = RESUME_RECENT_THRESH,
         resume_recent_min: int = RESUME_RECENT_MIN,
         min_trades_since_ban: int = MIN_TRADES_SINCE_BAN) -> str:
    """يُرتّب فرقة (symbol) إلى PROVEN / EXPLORE / BANNED من صف سبورتها.

    منطق التدرّج (بالترتيب):
      1) لا عيّنة كافية للحكم بأي طرف → EXPLORE (نقيس بحذر بميزانية ضئيلة).
      2) عيّنة كافية وحافّة موجبة قويّة (n>=n_proven, exp>+t_pos) → PROVEN.
      3) عيّنة كافية وحافّة سالبة قويّة (n>=n_min, exp<-t_neg)   → BANNED
         — إلا أن تكون قد استوفت شروط التعافي (hysteresis+dwell) فترتقي إلى EXPLORE
           (لا تقفز PROVEN مباشرة؛ تُعاد تحت المجهر بميزانية صغيرة أولاً).
      4) غير ذلك (حافّة قرب الصفر) → EXPLORE.

    إصلاح العيب (1): الرفع من BANNED محكوم بثلاثة شروط مجتمعة عبر _recovered():
      التوقّع التراكمي > resume_expr_floor (أقرب للصفر) + متوسّط النافذة الحديثة موجب +
      مضى عدد أدنى من الصفقات منذ آخر حظر (banned_at_n مخزّن في الصف). فلا تأرجح bang-bang.
    """
    exp = expectancy(stats_row)
    if exp is None:
        return EXPLORE
    n = int((stats_row or {}).get("n", 0) or 0)

    # حافّة موجبة قويّة بعيّنة كافية → مُثبتة.
    if n >= n_proven and exp > t_pos:
        return PROVEN

    # حافّة سالبة قويّة بعيّنة كافية → محظورة، ما لم تتعافَ (hysteresis+dwell).
    if n >= n_min and exp < -t_neg:
        if _recovered(stats_row, recent, exp=exp,
                      resume_expr_floor=resume_expr_floor,
                      resume_recent_thresh=resume_recent_thresh,
                      resume_recent_min=resume_recent_min,
                      min_trades_since_ban=min_trades_since_ban):
            return EXPLORE      # تعافت → تُعاد تحت المجهر (لا PROVEN مباشرة)
        return BANNED

    # حافّة قرب الصفر أو عيّنة بينيّة → استكشاف بميزانية ضئيلة.
    return EXPLORE


def _recovered(stats_row: Optional[Mapping[str, Any]],
               recent: Optional[Sequence[float]], *, exp: float,
               resume_expr_floor: float, resume_recent_thresh: float,
               resume_recent_min: int, min_trades_since_ban: int) -> bool:
    """شروط التعافي (إصلاح العيب 1 — hysteresis + dwell). كلّها مطلوبة معاً:
      (أ) التوقّع التراكمي exp > resume_expr_floor (تعافٍ نحو الصفر، عتبة أعلى من عتبة الحظر).
      (ب) متوسّط النافذة الحديثة (آخر resume_recent_min نتائج) > resume_recent_thresh (زخم موجب).
      (ج) مضى >= min_trades_since_ban صفقة منذ آخر حظر — يُقاس بـ (n - banned_at_n).
          لو لا banned_at_n مخزّن (لم يُحظَر سابقاً أو سبورة قديمة) → نطلب نافذة حديثة فقط (أ+ب).
    """
    if exp <= resume_expr_floor:
        return False
    rr = _recent_list(stats_row, recent)
    if len(rr) < resume_recent_min:
        return False
    window = rr[-resume_recent_min:]
    if (sum(window) / len(window)) <= resume_recent_thresh:
        return False
    # dwell: صفقات منذ الحظر
    if stats_row is not None:
        banned_at = stats_row.get("banned_at_n")
        if banned_at is not None:
            n = int(stats_row.get("n", 0) or 0)
            if (n - int(banned_at)) < min_trades_since_ban:
                return False
    return True


# ============================================================================ سياسة التنفيذ الحيّ
def live_policy(t: str, base_lot: float, *, max_per_symbol: int,
                explore_lot_frac: float = EXPLORE_LOT_FRAC,
                explore_max_pos: int = EXPLORE_MAX_POS) -> dict:
    """يحوّل التدرّج إلى قرار تنفيذ حيّ ملموس. يُرجع:
        {execute: bool, lot: float, max_pos: int, stack: bool, tier: str}

      PROVEN : execute=True,  lot=base_lot,                max_pos=max_per_symbol, stack=True.
      EXPLORE: execute=True,  lot=base_lot*explore_lot_frac, max_pos=explore_max_pos(=1), stack=False.
      BANNED : execute=False, lot=0,                       max_pos=0, stack=False  ← لا مال حيّ.

    لا يضمن السقف الأدنى للوت هنا (volume_min) — هذا شأن army_warroom (لديه info.volume_min/step).
    نُرجع فقط النيّة؛ army_warroom يأرضِها على volume_min/step بعد ضربها بالكسر. base_lot هو اللوت
    الذي حسبه army_warroom *قبل* الأرضية أو *بعدها*؛ التوافق محفوظ لأن EXPLORE يضرب كسراً ثم يُؤرَّض.
    """
    if t == BANNED:
        return {"execute": False, "lot": 0.0, "max_pos": 0, "stack": False, "tier": BANNED}
    if t == EXPLORE:
        return {"execute": True, "lot": float(base_lot) * float(explore_lot_frac),
                "max_pos": int(explore_max_pos), "stack": False, "tier": EXPLORE}
    # PROVEN (افتراض آمن لأي قيمة أخرى: عامِلها كاستكشاف لا كمُثبتة — never trust by default،
    # لكن tier() لا يُرجع غير الثلاثة، فهذا الفرع هو PROVEN فعلياً).
    if t == PROVEN:
        return {"execute": True, "lot": float(base_lot),
                "max_pos": int(max_per_symbol), "stack": True, "tier": PROVEN}
    # قيمة غير متوقّعة → الأكثر تحفّظاً: استكشاف ضئيل (لا نمنح لوتاً كاملاً لمجهول).
    return {"execute": True, "lot": float(base_lot) * float(explore_lot_frac),
            "max_pos": int(explore_max_pos), "stack": False, "tier": EXPLORE}


def policy_for(stats_row: Optional[Mapping[str, Any]], base_lot: float,
               recent: Optional[Sequence[float]] = None, *,
               max_per_symbol: int = 3, **tier_kw) -> dict:
    """بوّابة واحدة جاهزة لـmaybe_execute: من صف السبورة → قرار تنفيذ كامل.
    تجمع tier() ثم live_policy(). تستبدل سطرَي الفحص القديمين (201-208) بنداء واحد.

    مثال الاستخدام داخل maybe_execute (انظر مواصفة التعديل):
        pol = policy_for(score["stats"].get(sym), base_lot=lot,
                         recent=None, max_per_symbol=MAX_PER_SYMBOL)
        if not pol["execute"]: return None        # BANNED
        lot = max(info.volume_min, ...pol["lot"]...)   # EXPLORE يصغّر اللوت
        # وتُستعمل pol["max_pos"]/pol["stack"] بدل MAX_PER_SYMBOL في فحص التكديس.
    """
    t = tier(stats_row, recent, **tier_kw)
    return live_policy(t, base_lot, max_per_symbol=max_per_symbol)


# ============================================================================ تتبّع الحظر/النافذة
def push_recent(stats_row: dict, r: float, *, window: int = RECENT_WINDOW) -> dict:
    """يدفع نتيجة R إلى الذاكرة الدوّارة recentR داخل صف السبورة (يبقيها بطول window).
    لا يلمس n/wins/sumR (تلك يُحدّثها record_and_judge). يُرجع نفس الصف للتسلسل.
    يُستدعى من record_and_judge مباشرة بعد تحديث sumR لكل R جديد (انظر مواصفة التعديل البند 4)."""
    rr = list(stats_row.get("recentR", []) or [])
    rr.append(round(float(r), 3))
    if len(rr) > window:
        rr = rr[-window:]
    stats_row["recentR"] = rr
    return stats_row


def mark_ban_epoch(stats_row: dict, *, n_proven: int = N_PROVEN, t_pos: float = T_POS,
                   n_min: int = N_MIN, t_neg: float = T_NEG) -> dict:
    """يسجّل لحظة دخول الفرقة الحظر (banned_at_n = n الحالي) لقياس dwell لاحقاً.
    يُستدعى بعد push_recent في record_and_judge: إن أصبحت الفرقة الآن BANNED ولم تكن مُعلَّمة،
    نختم n الحالي؛ وإن خرجت من نطاق الحظر (لم تعد سالبة قويّة) نمسح العلامة كي يُعاد العدّ نظيفاً
    عند أي حظر مستقبلي. هذا ما يجعل dwell يقيس "صفقات منذ آخر حظر" لا منذ بداية الزمن."""
    exp = expectancy(stats_row)
    n = int(stats_row.get("n", 0) or 0)
    is_banned_zone = exp is not None and n >= n_min and exp < -t_neg
    if is_banned_zone:
        if stats_row.get("banned_at_n") is None:
            stats_row["banned_at_n"] = n
    else:
        # خرجت من منطقة الحظر (تعافى التوقّع التراكمي) → امسح العلامة لعدّ نظيف لاحقاً.
        if "banned_at_n" in stats_row:
            stats_row.pop("banned_at_n", None)
    return stats_row


# ============================================================================ تقييم مربوط بالتذكرة
def closed_R_from_db(pending: Mapping[str, Any], *, magic: int = EXEC_MAGIC,
                     db=None) -> Optional[float]:
    """تقييم-عند-الإغلاق **مربوط بالتذكرة** (إصلاح العيب 2).

    يطابق الصفقة المغلقة في friday_db.trades بـ ticket أو position_id المخزّن في الإشارة وقت
    الدخول الحيّ — لا بأقدم صفقة لنفس الرمز. ويحسب R من مخرج تلك الصفقة بعينها ÷ risk الخاص بنفس
    الإشارة (لا خلط دخول-DB بمخاطرة-إشارة):

        R = (exit - entry_signal) * side ÷ risk_signal

    حيث entry_signal/risk_signal/side من الإشارة نفسها (pending)، و exit من الصفقة المُطابَقة
    بالتذكرة في DB. هكذا لا تختلط صفقتان لنفس الرمز، ولا يُخلط دخول الـDB بمخاطرة الإشارة.

    يُرجع None إن: لا ticket/position_id في الإشارة (إشارة ظلّية → يحكمها هدف/وقف الظلّ)، أو لم
    تُغلق الصفقة بعد، أو فشلت أي خطوة (لا نكسر الحلقة الحيّة أبداً — نسقط بهدوء).
    قراءة فقط. db=False يتجاوز DB صراحةً. لا يفتح اتصالاً إن مُرِّر db (لا اتصال لكل نداء).
    """
    if db is False or not pending:
        return None
    ticket = pending.get("ticket")
    position_id = pending.get("position_id")
    if ticket is None and position_id is None:
        return None                      # إشارة ظلّية لم تُنفَّذ حيّاً → لا مطابقة DB
    risk = float(pending.get("risk", 0) or 0)
    side = int(pending.get("dir", 0) or 0)
    entry_sig = float(pending.get("entry", 0) or 0)
    if risk <= 0 or side == 0:
        return None
    own = db
    try:
        if own is None:
            from friday_db import FridayDB
            own = FridayDB()
        # مطابقة بالتذكرة أولاً (الأصدق)، ثم بالـposition_id؛ كلاهما مع magic لتقييد الفصيل.
        row = None
        if ticket is not None:
            row = own.con.execute(
                """SELECT exit, side, closed FROM trades
                   WHERE ticket=? AND magic=? LIMIT 1""",
                (int(ticket), magic),
            ).fetchone()
        if row is None and position_id is not None:
            row = own.con.execute(
                """SELECT exit, side, closed FROM trades
                   WHERE position_id=? AND magic=? LIMIT 1""",
                (int(position_id), magic),
            ).fetchone()
        if row is None:
            return None
        if not row["closed"]:
            return None                  # ما زالت مفتوحة في DB
        ex = row["exit"]
        if ex is None:
            return None
        tside = int(row["side"]) if row["side"] is not None else side
        if tside != side:
            return None                  # تعارض اتجاه (لقطة مغلوطة) → لا تحسب
        return round((float(ex) - entry_sig) * side / risk, 3)
    except Exception:
        return None
    finally:
        if db is None and own is not None:
            try:
                own.close()
            except Exception:
                pass


def judge_pending(pending: Mapping[str, Any], cur_px: float, now: Optional[float] = None,
                  *, magic: int = EXEC_MAGIC, db=None,
                  judge_horizon_s: int = JUDGE_HORIZON_S) -> Optional[float]:
    """يقرّر R لإشارة معلّقة، مفضّلاً الإغلاق الحقيقي المربوط بالتذكرة ثم الهدف/الوقف ثم سقف الزمن.

    ترتيب الأفضليّة (الأسرع/الأصدق أولاً):
      1) إغلاق حقيقي مُطابَق بالتذكرة في friday_db (إن كانت الإشارة منفَّذة حيّاً) → R الحقيقي.
      2) السعر بلغ الهدف   → R = (tgt-entry)*dir / risk.
      3) السعر بلغ الوقف   → R = -1.0.
      4) تجاوز سقف الزمن    → R = (px-entry)*dir / risk الحالي (mark-to-market).
      5) غير ذلك           → None (تبقى معلّقة).

    مرآة لمنطق record_and_judge الحالي + بند (1) المربوط بالتذكرة. لا أعراض جانبية.
    إشارة بلا ticket/position_id (ظلّية) تتجاوز (1) مباشرة إلى منطق الهدف/الوقف/الزمن.
    """
    if now is None:
        now = time.time()
    # 1) إغلاق حقيقي مربوط بالتذكرة (الأسرع/الأصدق) — None لو ظلّية أو لم تُغلق.
    r = closed_R_from_db(pending, magic=magic, db=db)
    if r is not None:
        return r
    d = int(pending.get("dir", 0) or 0)
    entry = float(pending.get("entry", 0) or 0)
    risk = float(pending.get("risk", 0) or 0)
    tgt = float(pending.get("tgt", entry) or entry)
    t0 = float(pending.get("t", now) or now)
    if d == 0 or risk <= 0:
        return None
    # 2) الهدف
    if (cur_px - entry) * d >= (tgt - entry) * d:
        return round((tgt - entry) * d / risk, 3)
    # 3) الوقف
    if (cur_px - entry) * d <= -risk:
        return -1.0
    # 4) سقف الزمن
    if now - t0 >= judge_horizon_s:
        return round((cur_px - entry) * d / risk, 3)
    # 5) ما زالت مفتوحة
    return None


# ============================================================================ مزامنة DB (اختياري)
def sync_scoreboard_to_db(score: Mapping[str, Any], *, squad: str = SQUAD_NAME,
                          db=None) -> int:
    """يكتب صفوف stats[symbol]={n,wins,sumR} إلى جدول friday_db.scoreboard (upsert).
    يُرجع عدد الصفوف المكتوبة. آمن للتشغيل المتكرر (مفتاح طبيعي squad,symbol). يُمرَّر db مشتركاً
    لتفادي فتح اتصال لكل نداء. db=False يتجاوز الكتابة (للاختبار)."""
    if db is False or not score:
        return 0
    stats = score.get("stats", {}) or {}
    if not stats:
        return 0
    own = db
    n = 0
    try:
        if own is None:
            from friday_db import FridayDB
            own = FridayDB()
        for sym, st in stats.items():
            if not isinstance(st, Mapping):
                continue
            own.upsert_scoreboard(
                squad=squad, symbol=sym,
                n=int(st.get("n", 0) or 0),
                wins=int(st.get("wins", 0) or 0),
                sum_r=float(st.get("sumR", 0.0) or 0.0),
            )
            n += 1
        return n
    except Exception:
        return n
    finally:
        if db is None and own is not None:
            try:
                own.close()
            except Exception:
                pass


# ============================================================================ تحقّق سريع (دخان)
if __name__ == "__main__":
    # فحوص دخان نقيّة بلا MT5/DB — تثبت أن منطق التدرّج/التعافي/المطابقة سليم.

    # --- tier: عيّنة غير كافية → EXPLORE
    assert tier({"n": 2, "wins": 1, "sumR": 0.4}) == EXPLORE
    assert tier(None) == EXPLORE
    assert tier({}) == EXPLORE

    # --- tier: مُثبتة (n>=6, exp>+0.05)
    assert tier({"n": 8, "wins": 6, "sumR": 2.4}) == PROVEN          # exp=0.30
    assert tier({"n": 6, "wins": 4, "sumR": 0.30}) == EXPLORE        # exp=0.05 ليس > 0.05 → EXPLORE
    assert tier({"n": 6, "wins": 4, "sumR": 0.36}) == PROVEN         # exp=0.06 > 0.05

    # --- tier: محظورة (n>=4, exp<-0.05) بلا تعافٍ
    assert tier({"n": 8, "wins": 1, "sumR": -2.4}) == BANNED         # exp=-0.30
    assert tier({"n": 4, "wins": 0, "sumR": -0.40}) == BANNED        # exp=-0.10
    assert tier({"n": 3, "wins": 0, "sumR": -3.0}) == EXPLORE        # n<4 → لا حظر بعد

    # --- tier: قرب الصفر → EXPLORE
    assert tier({"n": 10, "wins": 5, "sumR": 0.2}) == EXPLORE        # exp=0.02 بين العتبتين

    # --- استئناف من BANNED: hysteresis + dwell
    # سالبة قويّة لكن النافذة الحديثة تعافت + التوقّع فوق الأرضية + dwell كافٍ → EXPLORE
    recovered = {"n": 14, "wins": 6, "sumR": -0.2, "recentR": [1, 1, 1, 1, 1],
                 "banned_at_n": 6}      # exp=-0.0143 > -0.02 ; n-banned_at=8 >= 4
    assert tier(recovered) == EXPLORE
    # نفس النافذة المتعافية لكن لم يمضِ ما يكفي من الصفقات منذ الحظر (dwell) → يبقى BANNED
    too_soon = {"n": 8, "wins": 2, "sumR": -0.6, "recentR": [1, 1, 1, 1, 1],
                "banned_at_n": 6}      # exp=-0.075 < -0.05 (منطقة حظر) ؛ n-banned_at=2 < 4
    assert tier(too_soon) == BANNED
    # التوقّع التراكمي ما زال تحت الأرضية رغم نافذة موجبة → يبقى BANNED (hysteresis)
    deep_neg = {"n": 12, "wins": 2, "sumR": -3.0, "recentR": [1, 1, 1, 1, 1], "banned_at_n": 4}
    assert tier(deep_neg) == BANNED                  # exp=-0.25 <= -0.02
    # نافذة حديثة سالبة → يبقى BANNED رغم اقتراب التوقّع التراكمي (تعافٍ غير مؤكَّد)
    weak_recent = {"n": 20, "wins": 9, "sumR": -1.2, "recentR": [-1, -1, 1, -1], "banned_at_n": 4}
    assert tier(weak_recent) == BANNED               # exp=-0.06 < -0.05 ؛ نافذة سالبة → لا رفع

    # --- live_policy: BANNED لا مال
    pol_b = live_policy(BANNED, 0.05, max_per_symbol=3)
    assert pol_b["execute"] is False and pol_b["lot"] == 0.0 and pol_b["max_pos"] == 0
    # EXPLORE: لوت أصغر + مركز واحد، لا تكديس
    pol_e = live_policy(EXPLORE, 0.08, max_per_symbol=3)
    assert pol_e["execute"] is True and pol_e["lot"] == 0.08 * EXPLORE_LOT_FRAC
    assert pol_e["max_pos"] == 1 and pol_e["stack"] is False
    # PROVEN: لوت كامل + تكديس
    pol_p = live_policy(PROVEN, 0.08, max_per_symbol=3)
    assert pol_p["execute"] is True and pol_p["lot"] == 0.08
    assert pol_p["max_pos"] == 3 and pol_p["stack"] is True

    # --- policy_for: end-to-end من صف سبورة
    assert policy_for({"n": 8, "wins": 1, "sumR": -2.4}, 0.08, max_per_symbol=3)["execute"] is False
    assert policy_for({"n": 8, "wins": 6, "sumR": 2.4}, 0.08, max_per_symbol=3)["tier"] == PROVEN
    assert policy_for({"n": 2, "wins": 1, "sumR": 0.4}, 0.08, max_per_symbol=3)["tier"] == EXPLORE

    # --- push_recent: يحافظ على النافذة
    row = {"n": 0, "wins": 0, "sumR": 0.0}
    for i in range(20):
        push_recent(row, 1.0 if i % 2 else -1.0)
    assert len(row["recentR"]) == RECENT_WINDOW

    # --- mark_ban_epoch: يختم n عند دخول الحظر، يمسح عند الخروج
    br = {"n": 5, "wins": 0, "sumR": -1.0}   # exp=-0.2 منطقة حظر
    mark_ban_epoch(br); assert br["banned_at_n"] == 5
    mark_ban_epoch(br); assert br["banned_at_n"] == 5          # لا يُعاد ختمه
    br["n"] = 12; br["sumR"] = 0.6                              # تعافى (exp=+0.05 خارج الحظر)
    mark_ban_epoch(br); assert "banned_at_n" not in br          # مُسح للعدّ النظيف

    # --- judge_pending: هدف/وقف/زمن بلا DB (db=False يتجاوز DB)
    pend = {"sym": "X", "dir": 1, "entry": 100.0, "risk": 2.0, "tgt": 104.0, "t": time.time()}
    assert judge_pending(pend, 104.0, db=False) == 2.0   # هدف
    assert judge_pending(pend, 97.0, db=False) == -1.0   # وقف
    assert judge_pending(pend, 101.0, db=False) is None  # ما زالت مفتوحة
    # سقف الزمن (mark-to-market)
    old = dict(pend, t=time.time() - JUDGE_HORIZON_S - 1)
    assert judge_pending(old, 101.0, db=False) == 0.5    # (101-100)*1/2

    # --- closed_R_from_db: إشارة ظلّية (لا ticket) → None ؛ db=False → None
    assert closed_R_from_db({"sym": "X", "dir": 1, "entry": 100.0, "risk": 2.0}, db=False) is None
    assert closed_R_from_db({"ticket": 123, "dir": 1, "entry": 100.0, "risk": 2.0}, db=False) is None

    print("scoreboard_learn: كل فحوص الدخان نجحت ✓ (tier/live_policy/recovery/ticket-judge)")
