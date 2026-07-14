# -*- coding: utf-8 -*-
"""desk_scoreboard.py — 🏁 سبّورة الديسك الحيّة لكل ماجيك (قراءة سوق فقط، لا تداول إطلاقاً)
================================================================================
محرّك دائم بلا نافذة يكتب سبّورةً طازجة لكل ماجيك كل ~30ث: صافي اليوم/3أيام، عدد الصفقات،
نسبة الفوز، العائم، وحالة كل فرقة (رابح/متقاعد/مراقَبة). READ-ONLY تماماً:
لا يستدعي order_send ولا يفتح/يغلق/يعدّل أيّ مركز. ديمو-فقط.

المصدر: history_deals_get (صفقات الإغلاق فقط: entry==DEAL_ENTRY_OUT، pl=profit+commission+swap)
        + positions_get (العائم + عدد المفتوح لكل ماجيك) + account_info (رصيد/حقوق/عائم).
يكتب data/r_native/desk_scoreboard.json ذرّياً كل دورة (tmp + os.replace، utf-8، ensure_ascii=False).
"""
import os, sys, io

# ── أوّل شيء: تحويل stdout/stderr لملفّ سجلّ (pythonw بلا كونسول) ──
_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
_LOG_PATH = os.path.join(_RN, "desk_scoreboard.out.log")
os.makedirs(_RN, exist_ok=True)
# نحوّل فقط إذا كان التيّار معدوماً (pythonw) أو غير صالح — نحاكي حارس r_trader/gateway.py
try:
    if sys.stdout is None or sys.stderr is None:
        _log_f = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _log_f
        if sys.stderr is None:
            sys.stderr = _log_f
    else:
        # حتى مع كونسول: وجّه للسجلّ كي لا نفقد الأثر عند التشغيل بلا نافذة عبر الوصيّ
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
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

# ── قفل النسخة الوحيدة (يخرج هادئاً إن كانت نسخة أخرى تعمل) ──
try:
    import engine_lock
    engine_lock.claim("desk_scoreboard")
except SystemExit:
    raise
except Exception as e:
    print(f"[lock] engine_lock غير متاح ({e}) — نتابع بدون قفل")

# ── الثوابت والمسارات ──
LOOP_S = 30
OUT_JSON = os.path.join(_RN, "desk_scoreboard.json")
# 📈 منحنى الحقوق الحيّ (2026-07-07): كُتّابه القدامى (friday_dashboard/evolution_monitor) لا يعملون
# فتجمّد منذ 30-06 ومنحنى الرئيسية يعمل على الاحتياط. السبّورة تغذّيه — عيّنة كل ≥60ث، سقف 24س.
PNL_HIST = os.path.join(_RN, "pnl_history.json")
_CURVE_MIN_GAP_S = 60
_CURVE_CAP = 2880


def feed_equity_curve(equity, now):
    """يلحق [ts, equity] بمنحنى pnl_history.json (fail-soft، ذرّي، يحفظ بقيّة المفاتيح)."""
    try:
        try:
            with open(PNL_HIST, "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
        curve = d.get("curve")
        if not isinstance(curve, list):
            curve = []
        if curve and (now - float(curve[-1][0])) < _CURVE_MIN_GAP_S:
            return
        curve.append([round(now, 1), round(float(equity), 2)])
        d["curve"] = curve[-_CURVE_CAP:]
        d["updated"] = round(now, 1)
        atomic_write(PNL_HIST, d)
    except Exception as e:
        print(f"[curve] فشل تغذية المنحنى: {e}")

# خريطة أسماء الماجيك العربيّة (حسب العقد المشترك)
NAME_MAP = {
    0: "يدوي",
    20260701: "الحارس",
    20260600: "الديسك",
    20260703: "محاكي راضي",
    20260704: "رشّاش (متقاعد)",
    20260706: "R Core 🥷",
    20260631: "يوتيوب 📺",
    20260707: "قنّاص المجلس 🏛️",
    20260709: "حارس العملات 🌍",
}

# ماجيك ⇒ ملفّ إعداداته (لقراءة enabled ديناميكياً — نُعلّم المُطفأ متقاعداً)
# 2026-07-06: brain_trader_config.json صار ملفّ R Core (20260706) — الرشّاش 20260704 متقاعدٌ بالاسم أصلاً.
CFG_BY_MAGIC = {
    20260706: os.path.join(_RN, "brain_trader_config.json"),
}

MAX_TRADES = 30          # أقصى عدد صفقات اليوم في القائمة (الأحدث أولاً)
RETIRE_NET_3D = -20.0    # صافي 3أيام أدنى من هذا (مع n_today>=10) ⇒ متقاعد
RETIRE_N_TODAY = 10
WIN_N_TODAY = 5          # صافي موجب مع هذا العدد (أو ضمن الرابحين) ⇒ رابح


def _name(magic):
    """اسم الماجيك العربيّ أو نصّه إن لم يكن معروفاً."""
    return NAME_MAP.get(int(magic), str(int(magic)))


def _is_disabled(magic):
    """هل هذا الماجيك مُطفأ في إعداداته (enabled==false)؟ fail-soft إن غاب الملفّ."""
    path = CFG_BY_MAGIC.get(int(magic))
    if not path:
        return False
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        return isinstance(cfg, dict) and cfg.get("enabled", True) is False
    except Exception:
        return False


def _deal_pl(d):
    """صافي صفقة إغلاق = ربح + عمولة + سواب."""
    return float(d.profit) + float(d.commission) + float(d.swap)


def _closing_deals(since_dt):
    """صفقات الإغلاق فقط (entry == DEAL_ENTRY_OUT) منذ since_dt حتى الآن+ساعة."""
    to_dt = datetime.now() + timedelta(hours=1)
    try:
        deals = mt5.history_deals_get(since_dt, to_dt) or []
    except Exception as e:
        print(f"[deals] فشل history_deals_get: {e}")
        return []
    return [d for d in deals if getattr(d, "entry", None) == mt5.DEAL_ENTRY_OUT]


def atomic_write(path, obj):
    """كتابة ذرّية: ملفّ مؤقّت ثمّ os.replace (utf-8، ensure_ascii=False)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def build_scoreboard():
    """يبني كائن السبّورة الكامل حسب العقد المشترك. يعيد dict أو None عند فشل الحساب."""
    now = time.time()

    # ── الحساب ──
    acct = mt5.account_info()
    if acct is None:
        print("[acct] account_info أعاد None")
        return None
    balance = float(acct.balance)
    equity = float(acct.equity)
    floating_acct = round(equity - balance, 2)

    # ── حدود الوقت (00:00 UTC اليوم، وقبل 3 أيام) ──
    now_utc = datetime.now(timezone.utc)
    day0_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    since3d = now_utc - timedelta(days=3)

    # ── صفقات إغلاق اليوم (منذ 00:00 UTC) ──
    per = {}   # magic -> {"net_today","n_today","n_win","sum_win","sum_loss","n_loss"}
    today_deals = _closing_deals(day0_utc)
    for d in today_deals:
        m = int(d.magic)
        pl = _deal_pl(d)
        e = per.setdefault(m, {"net_today": 0.0, "n_today": 0, "n_win": 0,
                               "sum_win": 0.0, "sum_loss": 0.0, "n_loss": 0})
        e["net_today"] += pl
        e["n_today"] += 1
        if pl > 0:
            e["n_win"] += 1
            e["sum_win"] += pl
        elif pl < 0:
            e["n_loss"] += 1
            e["sum_loss"] += pl

    # ── صافي 3أيام لكل ماجيك ──
    net3d = {}   # magic -> net_3d
    for d in _closing_deals(since3d):
        m = int(d.magic)
        net3d[m] = net3d.get(m, 0.0) + _deal_pl(d)

    # ── العائم + عدد المفتوح لكل ماجيك ──
    floats = {}  # magic -> {"floating","n_open"}
    try:
        for p in (mt5.positions_get() or []):
            m = int(p.magic)
            fe = floats.setdefault(m, {"floating": 0.0, "n_open": 0})
            fe["floating"] += float(p.profit)
            fe["n_open"] += 1
    except Exception as e:
        print(f"[pos] فشل positions_get: {e}")

    # ── مجموعة كل الماجيكات الظاهرة ──
    all_magics = set(per) | set(net3d) | set(floats)

    # ── بناء صفوف الماجيك + حالة كلٍّ ──
    magics_rows = []
    winners = []
    retired = []
    for m in all_magics:
        pe = per.get(m, {"net_today": 0.0, "n_today": 0, "n_win": 0,
                         "sum_win": 0.0, "sum_loss": 0.0, "n_loss": 0})
        n_today = int(pe["n_today"])
        net_today = round(float(pe["net_today"]), 2)
        n_win = int(pe["n_win"])
        wr_today = int(round(100.0 * n_win / n_today)) if n_today > 0 else 0
        n_loss = int(pe["n_loss"])
        # ── مقياس المستخدم الأوّل (اللاتماثل): متوسّط الربح/الخسارة ونسبة العائد ──
        avg_win = round(float(pe["sum_win"]) / n_win, 2) if n_win > 0 else 0.0
        avg_loss = round(float(pe["sum_loss"]) / n_loss, 2) if n_loss > 0 else 0.0
        # payoff = |avg_win/avg_loss| عند وجود الطرفين؛ None بلا خسائر (لا مقام) — لا نزيّف لانهاية
        payoff = round(abs(avg_win / avg_loss), 2) if (n_loss > 0 and avg_loss != 0.0) else None
        n3d = round(float(net3d.get(m, 0.0)), 2)
        fe = floats.get(m, {"floating": 0.0, "n_open": 0})
        floating = round(float(fe["floating"]), 2)
        n_open = int(fe["n_open"])

        # ── الحالة (حسب العقد): متقاعد إن أُطفئت إعداداته أو (net_3d<-20 و n_today>=10)؛
        #    رابح إن net_3d>0 و (n_today>=5 أو ضمن الرابحين حتى الآن)؛ وإلّا مراقَبة ──
        # ⚖️ استثناء دلاليّ: magic 0 = يد المستخدم — ليست محرّكاً يُقاعَد؛ الأرقام تُعرض صادقةً بحالة «مراقَبة».
        if int(m) == 0:
            status = "watch"
        elif _is_disabled(m) or (n3d < RETIRE_NET_3D and n_today >= RETIRE_N_TODAY):
            status = "retired"
            retired.append(int(m))
        elif n3d > 0 and (n_today >= WIN_N_TODAY or int(m) in winners):
            status = "winner"
            winners.append(int(m))
        else:
            status = "watch"

        magics_rows.append({
            "magic": int(m),
            "name": _name(m),
            "net_today": net_today,
            "net_3d": n3d,
            "n_today": n_today,
            "wr_today": wr_today,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff": payoff,
            "floating": floating,
            "n_open": n_open,
            "status": status,
        })

    # ترتيب تنازليّ حسب صافي 3أيام
    magics_rows.sort(key=lambda r: r["net_3d"], reverse=True)

    # ── قائمة صفقات اليوم (الأحدث أولاً، بحدّ أقصى 30) ──
    today_sorted = sorted(today_deals, key=lambda d: float(getattr(d, "time", 0)), reverse=True)
    today_trades = []
    for d in today_sorted[:MAX_TRADES]:
        try:
            ts = float(getattr(d, "time", 0))
            iso = datetime.fromtimestamp(ts).strftime("%H:%M") if ts > 0 else ""
            # نوع الصفقة: DEAL_TYPE_BUY=0، DEAL_TYPE_SELL=1
            dtype = int(getattr(d, "type", -1))
            direction = "buy" if dtype == mt5.DEAL_TYPE_BUY else ("sell" if dtype == mt5.DEAL_TYPE_SELL else "")
            today_trades.append({
                "iso": iso,
                "magic": int(d.magic),
                "name": _name(d.magic),
                "sym": str(getattr(d, "symbol", "") or ""),
                "dir": direction,
                "net": round(_deal_pl(d), 2),
            })
        except Exception as e:
            print(f"[trade] تخطّي صفقة: {e}")

    return {
        "updated": round(now, 1),
        "iso": datetime.now().strftime("%H:%M:%S"),
        "account": {"balance": round(balance, 2), "equity": round(equity, 2), "floating": floating_acct},
        "magics": magics_rows,
        "winners": winners,
        "retired": retired,
        "today_trades": today_trades,
    }


def mt5_connect():
    """اتّصال واحد لكلّ عمليّة — 6 محاولات بينها 10 ثوانٍ (نمط brain_trader)."""
    for attempt in range(6):
        if mt5.initialize():
            print(f"[mt5] متّصل (محاولة {attempt + 1})")
            return True
        print(f"[mt5] فشل initialize (محاولة {attempt + 1}/6): {mt5.last_error()}")
        time.sleep(10)
    return False


def main():
    print(f"\n[desk_scoreboard] بدء التشغيل {datetime.now().isoformat()}")
    if not mt5_connect():
        print("[desk_scoreboard] تعذّر الاتّصال بـ MT5 — خروج")
        return

    # ── حارس ديمو: نتابع فقط إن كان الخادم Trial/Demo (لا نلمس شيئاً أصلاً، لكن نلتزم القاعدة) ──
    acct = mt5.account_info()
    srv = str(getattr(acct, "server", "") or "")
    if not acct or not ("Trial" in srv or "Demo" in srv):
        print(f"[desk_scoreboard] ⛔ الخادم '{srv}' ليس ديمو — خروج (READ-ONLY، لكن نلتزم ديمو-فقط)")
        return
    print(f"[desk_scoreboard] ديمو مؤكّد ({srv}) — سبّورة قراءة فقط كل {LOOP_S}ث")

    while True:
        t0 = time.time()
        try:
            board = build_scoreboard()
            if board is not None:
                atomic_write(OUT_JSON, board)
                feed_equity_curve(board["account"]["equity"], time.time())
            else:
                print("[cycle] لا سبّورة هذه الدورة (حساب غير متاح) — إعادة محاولة")
        except Exception as e:
            import traceback
            print(f"[cycle] خطأ: {e}\n{traceback.format_exc()}")
            time.sleep(15)
            continue
        # نوم حتى إكمال الدورة (LOOP_S ناقص زمن الحساب)
        elapsed = time.time() - t0
        time.sleep(max(1.0, LOOP_S - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"[fatal] {e}\n{traceback.format_exc()}")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
