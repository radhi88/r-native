# -*- coding: utf-8 -*-
"""real_lock.py — 🔒 قفل الحساب الحقيقيّ: البوتات ديمو-فقط حتى تخضرّ البوّابة (قانون المستخدم المتّفق).

كل 10 ثوانٍ: لو الطرفيّة متّصلة بحسابٍ غير تجريبيّ (اسم الخادم بلا Trial/Demo — كشف Exness
الموثوق، لأن trade_mode يكذب) ⇒ يكتب kill_switch فوراً فيتجمّد كل المنفّذين، ويصرخ للجوّال
عبر تغذية الإنذارات. اليدويّ (magic 0) حرٌّ دائماً — القفل يوقف البوتات فقط عبر kill_switch
الذي تحترمه جميعها. لا يُفتح إلا يدوياً بعد اخضرار real_account_gate (n≥100/فرقة + >2σ + أنظمة)."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "real_lock.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time
import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("real_lock")
except SystemExit:
    raise
except Exception:
    pass

KILL = os.path.join(_RN, "kill_switch.txt")
KILL_ROOT = os.path.join(_BASE, "kill_switch.txt")     # بعض المحرّكات القديمة تقرأ قفل الجذر — نكتب الاثنين
MODE_F = os.path.join(_RN, "real_mode.json")           # {"mode":"lock"|"cage"} — التبديل بيد المستخدم وحده

# 🧿 القفص المقيّد (cage): المستخدم — بيده — يسمح للبوتات بالحقيقيّ داخل أسوار:
CAGE = {"max_total_lot": 0.05,     # مجموع لوت البوتات المفتوح
        "max_single_lot": 0.03,    # أكبر لوت لصفقة بوت واحدة
        "max_positions": 3,        # أقصى مراكز بوت متزامنة
        "daily_loss_usd": 5.0}     # خسارة بوتات اليوم (محقَّق+عائم) تبلغ هذا ⇒ قفلٌ فوريّ لبقيّة اليوم
_PROTECTED = {0, 2447, 20250418, 20250421, 20250422, 20250618}


def _mode():
    try:
        return str(json.load(open(MODE_F, encoding="utf-8")).get("mode", "lock")).lower()
    except Exception:
        try:
            t = MODE_F + ".tmp"
            json.dump({"mode": "lock",
                       "_note": "lock = البوتات ممنوعة من الحقيقيّ (الافتراضيّ). cage = يُسمح لها داخل القفص: "
                                f"لوت إجماليّ ≤{CAGE['max_total_lot']} · صفقة ≤{CAGE['max_single_lot']} · "
                                f"مراكز ≤{CAGE['max_positions']} · خسارة يوميّة ≤${CAGE['daily_loss_usd']} ⇒ قفل تلقائيّ. "
                                "التبديل إلى cage قرار المستخدم بيده فقط."},
                      open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, MODE_F)
        except Exception:
            pass
        return "lock"


def _clear_our_kills():
    for kf in (KILL, KILL_ROOT):
        try:
            if os.path.exists(kf) and "real_lock" in open(kf, encoding="utf-8", errors="ignore").read():
                os.unlink(kf)
        except Exception:
            pass


def _bots_today_net():
    """محقَّق بوتات اليوم + عائمها الآن (لسور الخسارة اليوميّة)."""
    import datetime as _dtm
    frm = _dtm.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    real = 0.0
    for d in (mt5.history_deals_get(frm, _dtm.datetime.now() + _dtm.timedelta(hours=2)) or []):
        if d.entry == 1 and d.magic not in _PROTECTED:
            real += float(d.profit or 0) + float(d.swap or 0) + float(d.commission or 0)
    flo = sum(p.profit for p in (mt5.positions_get() or []) if p.magic not in _PROTECTED)
    return real + flo


def _cage_breach():
    """يرجع سبب خرق أسوار القفص أو None."""
    poss = [p for p in (mt5.positions_get() or []) if p.magic not in _PROTECTED]
    if len(poss) > CAGE["max_positions"]:
        return f"مراكز بوت {len(poss)} > {CAGE['max_positions']}"
    tot = sum(p.volume for p in poss)
    if tot > CAGE["max_total_lot"] + 1e-9:
        return f"لوت إجماليّ {tot:.2f} > {CAGE['max_total_lot']}"
    if any(p.volume > CAGE["max_single_lot"] + 1e-9 for p in poss):
        return f"لوت صفقة > {CAGE['max_single_lot']}"
    net = _bots_today_net()
    if net <= -CAGE["daily_loss_usd"]:
        return f"خسارة بوتات اليوم ${net:.2f} بلغت السور −${CAGE['daily_loss_usd']}"
    return None
ALARM = os.path.join(_RN, "news_alarm_feed.jsonl")     # قناة الجوّال الموجودة
ST = os.path.join(_RN, "real_lock_status.json")


def _is_demo():
    a = mt5.account_info()
    if a is None:
        return None                                     # غير متّصل — لا حكم
    s = (a.server or "").lower()
    return ("trial" in s) or ("demo" in s)


def main():
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🔒 قفل الحقيقيّ بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — البوتات ديمو-فقط (بوّابة حمراء t=-5.99)")
    warned = False
    while True:
        try:
            demo = _is_demo()
            mode = _mode()
            st = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                  "demo": demo, "mode": mode, "locked": False}
            if demo is False and mode == "cage":         # 🧿 القفص: مسموحٌ داخل الأسوار (قرار المستخدم بيده)
                breach = _cage_breach()
                if breach:
                    st["locked"] = True
                    msg = f"real_lock(cage): خرق سور القفص — {breach}. البوتات مقفولة لبقيّة اليوم. اليدويّ حرّ."
                    for kf in (KILL, KILL_ROOT):
                        try:
                            if not os.path.exists(kf) or "real_lock" not in open(kf, encoding="utf-8", errors="ignore").read():
                                with open(kf, "w", encoding="utf-8") as f:
                                    f.write(msg)
                        except Exception:
                            pass
                    if not warned:
                        print(f"🧿⛔ {msg}")
                        try:
                            with open(ALARM, "a", encoding="utf-8") as f:
                                f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                                    "kind": "CAGE-BREACH", "title": "🧿⛔ " + breach,
                                                    "impact": "High", "currency": "ALL"}, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                        warned = True
                else:
                    st["cage"] = True
                    _clear_our_kills()                   # الأسوار سليمة ⇒ ارفع قفلنا (فقط قفلنا)
                    warned = False
            elif demo is False:                          # 🚨 حساب حقيقيّ + وضع lock (الافتراضيّ)
                st["locked"] = True
                msg = ("real_lock: حسابٌ حقيقيّ مكتشف — البوتات مجمّدة (بوّابة المال الحقيقيّ حمراء: "
                       "n<100/فرقة، t=-5.99، 0/5 أنظمة). اليدويّ حرّ. للسماح المقيّد: real_mode.json ⇒ cage (بيدك).")
                for kf in (KILL, KILL_ROOT):               # 🔒 القفلان معاً — درس تسريب 14:16 (محرّكات تقرأ الجذر)
                    try:
                        if not os.path.exists(kf) or "real_lock" not in open(kf, encoding="utf-8", errors="ignore").read():
                            with open(kf, "w", encoding="utf-8") as f:
                                f.write(msg)
                    except Exception:
                        pass
                if not warned:
                    print("🚨 حساب حقيقيّ ⇒ القفلان كُتبا — كل البوتات تجمّدت. اليدويّ حرّ.")
                if not warned:
                    try:
                        with open(ALARM, "a", encoding="utf-8") as f:
                            f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                                "kind": "REAL-LOCK",
                                                "title": "🚨 حساب حقيقيّ مكتشف — جمّدتُ كل البوتات (بوّابة حمراء). يدويّك حرّ.",
                                                "impact": "High", "currency": "ALL"}, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                    warned = True
            else:                                        # ✅ ديمو ⇒ ارفع قفلَينا فوراً (وإلا بقيت البوتات مجمّدة بعد الرجوع للديمو)
                if demo is True:
                    _clear_our_kills()
                warned = False
            try:
                t = ST + ".tmp"; json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(t, ST)
            except Exception:
                pass
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
