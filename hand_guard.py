# -*- coding: utf-8 -*-
"""hand_guard.py — 🖐️ حرس اليد (مراقبة فقط · لا أوامر إطلاقاً · إنذارات للهاتف).

يراقب تداول المستخدم اليدويّ (ماجيك 0) ولا يفتح/يغلق/يعدّل أيّ مركزٍ أبداً —
إدارة ماجيك-0 ملكُ manual_manager وحده؛ هذا المحرّك يشاهد ويَعُدّ ويُنذر فقط.

الأدوار (حلقة 5ث):
  1. متتبّع الانطلاقة: الحقوق مقابل بداية المستخدم ($100.14) + قمّة-منذ-الانطلاقة + الأيام.
  2. إحصاء اليوم اليدويّ: ربح/خسارة صفقات ماجيك-0 المغلقة منذ منتصف الليل + عدّاد آخر ساعة.
  3. الحرّاس الثلاثة (إنذارات عربيّة إلى قناة الهاتف news_alarm_feed.jsonl بنوع hand_guard):
     أ. حدّ اليوم: خسارة اليد ≥10% من حقوق بداية اليوم ⇒ «توقف — القاعدة قاعدتك».
     ب. عدّاد الرشّ: ≥8 فتحات يدويّة في ساعة ⇒ تحذير الانتقام (قاتله رقم 1 المُثبَت).
     ج. فيتو شريت-بالقمة: دخول ذهبٍ يدويّ جديد شراءً فوق EMA50-M1 بـ$5 أو بعد شمعةٍ >$5 ⇒
        «⛔ شريت بالقمة!» (ومرآته بيعاً تحت EMA50 ⇒ «بعت بالقاع!») — قاعدة المستخدم الذهبيّة.
⚖️ عقدٌ صارم: لا order_send ولا SL/TP ولا إغلاق — قراءةٌ وإنذارٌ فقط."""
import os, sys, json, time
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "hand_guard.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("hand_guard")                   # 🔒 منفذ 8772 في السجلّ (8770 لِفرايدي — ممنوع)
except SystemExit:
    raise
except Exception:
    pass

BASELINE_F = os.path.join(_RN, "launch_baseline.json")
STATE_F = os.path.join(_RN, "hand_guard_state.json")
STATUS_F = os.path.join(_RN, "hand_guard_status.json")
FEED_F = os.path.join(_RN, "hand_guard_feed.jsonl")
ALARM_F = os.path.join(_RN, "news_alarm_feed.jsonl")  # 📱 قناة إنذار الهاتف الموجودة
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

# ⚙️ ثوابت مُدمجة عمداً (قواعد المستخدم نفسه — ليست إعدادات كي لا تُميَّع):
DAY_LIMIT_PCT = 10.0                                  # 🛑 حدّ خسارة اليوم اليدويّ (قاعدته)
SPRAY_N = 8                                           # ⚠️ فتحات/ساعة = وضع الرشّ (الانتقام)
GOLD_RANGE_USD = 5.0                                  # 🕯️ شمعة M1 أعرض من $5 = مطاردة
EMA_DIST_USD = 5.0                                    # 📏 بُعد $5 عن EMA50-M1 = قمّة/قاع
COOL_S = 1800                                         # 🧊 تبريد إعادة الإنذار (حارسا أ، ب) 30د
TOP_COOL_S = 60                                       # 🧊 تبريد حارس ج (لكلّ تذكرة مرّة أصلاً)
LOOP_S = 5.0

G = {"alert_ts": {}, "primed": False}


# ═══════════════════ حالة دائمة (ذرّيّة) + إنذارات ═══════════════════
def _load_state():
    try:
        return json.load(open(STATE_F, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    try:
        t = STATE_F + ".tmp"
        json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(t, STATE_F)
    except Exception:
        pass


def _alarm(guard, title, cool_s, **kw):
    """📣 إنذارٌ مزدوج: قناة الهاتف (news_alarm_feed) + سجلّ الحرس (hand_guard_feed).
    كلّ حارسٍ يطلق مرّةً واحدة لكلّ فترة تبريد — لا فيضان إنذارات."""
    now = time.time()
    if now - G["alert_ts"].get(guard, 0) < cool_s:
        return False
    G["alert_ts"][guard] = now
    ev = {"ts": round(now, 1), "iso": datetime.now().isoformat(timespec="seconds"),
          "kind": "hand_guard", "guard": guard, "title": title,
          "impact": "High", "currency": "ALL"}
    for path in (ALARM_F, FEED_F):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ev, **kw), ensure_ascii=False) + "\n")
        except Exception:
            pass
    print(f"📣 {title}")
    return True


# ═══════════════════ مؤشّرات (منسوخة من brain_trader — قراءة فقط) ═══════════════════
def _ema(vals, n):
    if vals is None or len(vals) < n:
        return None
    k = 2.0 / (n + 1); e = sum(vals[:n]) / float(n)
    for v in vals[n:]:
        e += k * (v - e)
    return e


def _ema_m1(sym, n=50):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n + 30)
    if r is None or len(r) < n:
        return None
    return _ema([float(x["close"]) for x in r], n)


def _m1_last_range(sym):
    """🕯️ مدى آخر شمعة M1 مُغلقة (فتيل-لِفتيل) — الشمعة العريضة = مطاردة حركة."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 1)
    if r is None or len(r) < 1:
        return None
    return float(r[0]["high"] - r[0]["low"])


# ═══════════════════ 1) متتبّع الانطلاقة ═══════════════════
def _baseline():
    d = {"start_equity": 100.14, "ts": 0.0, "iso": ""}
    try:
        d.update(json.load(open(BASELINE_F, encoding="utf-8")))
    except Exception:
        pass
    return d


# ═══════════════════ 2) إحصاء اليوم اليدويّ (ماجيك 0 فقط) ═══════════════════
def _manual_day():
    """صفقات المستخدم اليدويّة المُغلقة منذ منتصف الليل المحلّيّ (entry==1، ماجيك 0،
    صفقات شراء/بيع فقط — لا إيداعات) + عدّاد الفتحات (entry==0) في آخر ساعة."""
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ep = day0.timestamp(); now = time.time()
    pnl = 0.0; n = wins = losses = opens_1h = 0
    try:
        deals = mt5.history_deals_get(day0 - timedelta(hours=12),
                                      datetime.now() + timedelta(hours=12)) or []
        for d in deals:
            if int(getattr(d, "magic", -1)) != 0 or int(getattr(d, "type", 9)) not in (0, 1):
                continue                              # يدويّ صرف: ماجيك 0 + شراء/بيع فقط
            t = float(getattr(d, "time", 0))
            if int(d.entry) == 1 and t >= ep:         # إغلاق ⇒ نتيجة اليوم
                pl = float(d.profit) + float(d.commission) + float(d.swap)
                pnl += pl; n += 1
                if pl > 0:
                    wins += 1
                elif pl < 0:
                    losses += 1
            elif int(d.entry) == 0 and t >= now - 3600:
                opens_1h += 1                         # فتح ⇒ عدّاد الرشّ
    except Exception:
        pass
    wr = round(100.0 * wins / (wins + losses), 1) if (wins + losses) else None
    return {"pnl_today": round(pnl, 2), "n_today": n, "n_last_hour": opens_1h,
            "wins": wins, "losses": losses, "wr_today": wr}


# ═══════════════════ 3) الحرّاس الثلاثة (إنذارٌ فقط — لا لمس مراكز) ═══════════════════
def _guard_day_limit(st, man, equity):
    """🛑 أ. حدّ اليوم: خسارة اليد المُغلقة ≥10% من حقوق بداية اليوم ⇒ إنذارٌ صارخ
    (يتكرّر كلّ 30د ما دام الخرق قائماً). حقوق بداية اليوم تُلتقط مرّةً عند أوّل نبضةٍ لليوم."""
    today = datetime.now().strftime("%Y-%m-%d")
    if st.get("day") != today:                        # 🌅 يومٌ جديد ⇒ التقاط الحقوق + رفع الأعلام
        st["day"] = today
        st["day_start_equity"] = round(float(equity), 2)
        st["day_limit_hit"] = False
        G["alert_ts"].pop("day_limit", None)
    base = float(st.get("day_start_equity") or equity or 0)
    breached = base > 0 and float(man["pnl_today"]) <= -DAY_LIMIT_PCT / 100.0 * base
    if breached:
        st["day_limit_hit"] = True
        _alarm("day_limit",
               "🖐️🛑 يدك بلغت حد اليوم (-10%): توقف — القاعدة قاعدتك", COOL_S,
               pnl_today=man["pnl_today"], day_start_equity=base,
               limit_usd=round(-DAY_LIMIT_PCT / 100.0 * base, 2))
    return bool(st.get("day_limit_hit"))


def _guard_spray(man):
    """⚠️ ب. عدّاد الرشّ: ≥8 فتحات يدويّة في ساعة — نمط الانتقام (تسريبه رقم 1 المُثبَت)."""
    n = int(man["n_last_hour"])
    if n >= SPRAY_N:
        _alarm("spray",
               f"🖐️⚠️ وضع الرش: {n} صفقة يدوية في ساعة — تسريبك رقم 1 هو الانتقام",
               COOL_S, n_last_hour=n)
    return n >= SPRAY_N


def _guard_top_buy(st):
    """⛔ ج. فيتو شريت-بالقمة (قاعدة المستخدم الذهبيّة يوم +161%): دخول ذهبٍ يدويّ جديد
    شراءً بعد شمعة M1 أعرض من $5 أو فوق EMA50-M1 بأكثر من $5 ⇒ إنذارٌ فوريّ.
    ومرآته: بيعٌ تحت EMA50 بأكثر من $5 ⇒ «بعت بالقاع». كلّ تذكرةٍ تُنذر مرّةً واحدة."""
    poss = [p for p in (mt5.positions_get() or [])
            if int(getattr(p, "magic", -1)) == 0 and str(p.symbol).upper().startswith("XAUUSD")]
    seen = st.get("seen_tickets")
    prime = seen is None and not G["primed"]          # 🌱 أوّل تشغيلٍ نظيف: بصمة بلا إنذار رجعيّ
    seen = set(int(x) for x in (seen or []))
    G["primed"] = True
    new = [p for p in poss if int(p.ticket) not in seen]
    ind = {}                                          # خبيئة EMA/المدى لكلّ رمزٍ في هذه النبضة
    for p in new:
        seen.add(int(p.ticket))
        if prime:
            continue                                  # مراكز موجودة قبل ولادتنا — لا حكم عليها
        sym = str(p.symbol)
        if sym not in ind:
            ind[sym] = (_ema_m1(sym), _m1_last_range(sym))
        e50, rng = ind[sym]
        entry = float(getattr(p, "price_open", 0) or 0)
        wide = rng is not None and rng > GOLD_RANGE_USD
        if int(p.type) == 0:                          # شراء
            far = e50 is not None and entry > e50 + EMA_DIST_USD
            title = "⛔🖐️ شريت بالقمة! (قاعدتك الذهبية)"
        else:                                         # بيع — المرآة
            far = e50 is not None and entry < e50 - EMA_DIST_USD
            title = "⛔🖐️ بعت بالقاع! (قاعدتك الذهبية)"
        if wide or far:
            fired = _alarm(f"top_{p.ticket}", title, TOP_COOL_S,
                           sym=sym, ticket=int(p.ticket), entry=entry,
                           ema50_m1=round(e50, 2) if e50 else None,
                           m1_range=round(rng, 2) if rng is not None else None,
                           side=("buy" if int(p.type) == 0 else "sell"),
                           why=("شمعة M1 عريضة" if wide else "بعيدٌ عن EMA50"))
            if fired:
                st["last_top_buy_iso"] = datetime.now().isoformat(timespec="seconds")
    st["seen_tickets"] = sorted(seen)[-300:]          # لا تتضخّم الذاكرة عبر الأسابيع
    return st.get("last_top_buy_iso")


# ═══════════════════ 4) ملفّ الحالة (كتابة ذرّيّة كلّ نبضة ≤5ث) ═══════════════════
def _flows_and_trading_pnl(since_ts):
    """صافي التدفّقات (إيداع/سحب) والربح التداوليّ الحقيقيّ منذ الانطلاقة — صافي التدفّقات = صدق.
    الوهم الذي خدعنا 2026-07-07: قياس (الحقوق−البداية) يحسب الإيداعات أرباحاً. الحقيقة = مجموع صفقات فعليّة."""
    if not since_ts:
        return 0.0, 0.0
    try:
        deals = mt5.history_deals_get(datetime.fromtimestamp(float(since_ts)),
                                      datetime.now() + timedelta(hours=1)) or []
    except Exception:
        return 0.0, 0.0
    flows = trade = 0.0
    for d in deals:
        if int(getattr(d, "type", -1)) == mt5.DEAL_TYPE_BALANCE:   # إيداع/سحب/عمولة رصيد
            flows += float(d.profit)
        elif int(getattr(d, "entry", -1)) == 1:                    # صفقة إغلاق محقّقة
            trade += float(d.profit) + float(d.commission) + float(d.swap)
    return round(flows, 2), round(trade, 2)


def _save_status(bl, st, man, equity, spray, frozen_note):
    start = float(bl.get("start_equity") or 0)
    peak = float(st.get("peak") or 0)
    b_ts = float(bl.get("ts") or 0)
    net_flows, trade_pnl = _flows_and_trading_pnl(b_ts)          # 🔑 الأرقام الصادقة (بلا وهم الإيداعات)
    true_eq = round(start + trade_pnl, 2)                         # منحنى الحقوق التداوليّ (بلا تدفّقات)
    status = {"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
              "engine": "حرس اليد", "read_only": True,
              "launch": {"start": start, "equity": round(float(equity or 0), 2),
                         "net_flows": net_flows,                  # إيداعاتك − سحوباتك منذ الانطلاقة
                         "trading_pnl": trade_pnl,                # ✅ الربح الحقيقيّ من الصفقات فقط
                         "trading_pct": round(trade_pnl / start * 100.0, 2) if start > 0 else None,
                         "true_equity": true_eq,                  # ماذا كانت ستكون الحقوق بلا تدفّقات
                         "pct": round(trade_pnl / start * 100.0, 2) if start > 0 else None,  # = التداوليّ الصادق
                         "peak": round(peak, 2),
                         "dd_from_peak_pct": round((peak - true_eq) / peak * 100.0, 2)
                                             if peak > 0 else None,
                         "days": round((time.time() - b_ts) / 86400.0, 2) if b_ts else None,
                         "since_iso": bl.get("iso") or None},
              "manual": man,
              "guards": {"day_limit_hit": bool(st.get("day_limit_hit")),
                         "spray_mode": bool(spray),
                         "last_top_buy_iso": st.get("last_top_buy_iso")},
              "frozen_note": frozen_note}
    try:
        t = STATUS_F + ".tmp"
        json.dump(status, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, STATUS_F)
    except Exception:
        pass


def _idle_status(note):
    """💤 نبض قلبٍ خامل (مفتاح قتل/غير ديمو) كي لا يظنّنا الوصيّ «معلّقين» فيقتل/يحيي."""
    try:
        st = {"ts": round(time.time(), 1), "iso": datetime.now().isoformat(timespec="seconds"),
              "engine": "حرس اليد", "read_only": True, "frozen_note": note}
        t = STATUS_F + ".tmp"
        json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, STATUS_F)
    except Exception:
        pass


def main():
    ok = False
    for i in range(6):                                # ⏳ تهيئة موقوتة 6×10ث (درس IPC: انتظر لا تطرق)
        if mt5.initialize():
            ok = True; break
        print(f"⏳ init {i + 1}/6"); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5"); return
    print(f"🖐️ حرس اليد بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — مراقبة فقط، لا أوامر أبداً")
    state = _load_state()
    while True:
        try:
            if os.path.exists(KILL1) or os.path.exists(KILL2):
                _idle_status("مفتاح القتل مفعّل — حرس اليد خامل (قراءة فقط أصلاً)")
                time.sleep(10); continue
            acct = mt5.account_info()
            srv = str(getattr(acct, "server", "") or "")
            if not acct or not ("Trial" in srv or "Demo" in srv):
                _idle_status(f"الخادم '{srv}' ليس Trial/Demo — حرس اليد صامت حتى العودة للديمو")
                time.sleep(30); continue
            equity = float(acct.equity)
            # 1) الانطلاقة: قمّة منحنى الحقوق التداوليّ (بلا وهم الإيداعات) — تُحسب داخل _save_status
            bl = _baseline()
            _nf, _tp = _flows_and_trading_pnl(float(bl.get("ts") or 0))
            _true_eq = float(bl.get("start_equity") or 0) + _tp
            if _true_eq > float(state.get("peak") or 0):
                state["peak"] = round(_true_eq, 2)
            # 2) إحصاء اليد اليوم
            man = _manual_day()
            # 3) الحرّاس الثلاثة — إنذارٌ فقط، صفر أوامر
            _guard_day_limit(state, man, equity)
            spray = _guard_spray(man)
            _guard_top_buy(state)
            _save_state(state)
            # 4) الحالة كلّ نبضة (≤5ث)
            _save_status(bl, state, man, equity, spray, None)
            time.sleep(LOOP_S)
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
