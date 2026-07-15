"""why_no_trades.py — 🩺 «ليه ما يدخل صفقات؟» — تشخيصٌ ذاتيّ شامل، قراءة فقط.

يفحص كل بوّابات المنع بالترتيب (عامّة ⇒ محرّكية ⇒ عابرة) ويطبع حكماً صريحاً:
  🔴 قاطعٌ عامّ (يوقف الأسطول كلّه) · 🟠 قاطع محرّك · 🟡 تحذير · 🟢 سليم

تشغيل على جهاز التداول:  python why_no_trades.py
لا يتاجر، لا يعدّل شيئاً، لا يمسّ MT5 إلا قراءةً (initialize للفحص فقط).
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
if not MT5DIR.exists():                      # تشغيل من مكان آخر ⇒ جرّب مجلّد الملف
    MT5DIR = Path(__file__).resolve().parent
RN = MT5DIR / "data" / "r_native"

R = []          # (شدّة، عنوان، تفصيل)  شدّة: 0=🔴 1=🟠 2=🟡 3=🟢


def _add(sev, title, detail=""):
    R.append((sev, title, detail))


def _j(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _age_min(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 60.0
    except Exception:
        return None


# ═══ 1) القواطع العامّة ═══════════════════════════════════════════════════

def check_kill():
    for p, label in ((RN / "kill_switch.txt", "data/r_native/kill_switch.txt"),
                     (MT5DIR / "kill_switch.txt", "kill_switch.txt (الجذر)")):
        if p.exists():
            body = ""
            try:
                body = p.read_text(encoding="utf-8", errors="replace")[:120].strip()
            except Exception:
                pass
            _add(0, f"مفتاح القتل موجود: {label}",
                 f"كل المنفّذين متجمّدون. المحتوى: {body or '—'} · "
                 f"عمره {int(_age_min(p) or 0)} دقيقة. من كتبه غالباً: real_lock "
                 f"(حساب غير ديمو) أو master_floor (هامش ≤130% أو حقوق ≤12% من القمة).")
            return
    _add(3, "لا مفتاح قتل", "kill_switch.txt غير موجود في الموقعين.")


def check_watchdog():
    st = _j(RN / "watchdog_status.json")
    if not st:
        _add(0, "لا ملف حالة للوصيّ (watchdog_status.json)",
             "الوصيّ نفسه غالباً غير شغّال ⇒ الأسطول كلّه واقف. "
             "شغّل START_UNIFIED.bat (توحيد #1 استبدل كل المشغّلات القديمة).")
        return
    age = _age_min(RN / "watchdog_status.json")
    if age is not None and age > 5:
        _add(0, f"الوصيّ صامت منذ {int(age)} دقيقة",
             "watchdog_status.json بائت ⇒ الوصيّ مات ولم يُعَد. أعد START_UNIFIED.bat.")
        return
    dead = [k for k, c in (st.get("alive") or {}).items() if not c]
    _add(3, f"الوصيّ حيّ ({st.get('n_alive')}/{st.get('n_total')} محرّكاً)",
         ("ميّتة الآن: " + ", ".join(dead[:8])) if dead else "الكلّ حيّ.")


def check_focus():
    if (MT5DIR / "focus_youtube.flag").exists():
        _add(1, "وضع التركيز مفعّل (focus_youtube.flag)",
             "محرّكات الدخول متعدّدة العملات مُقصاة من الحراسة: multi_trader، "
             "army_warroom، pipflow، gold_scalper، orb_trader، level_sentinel_multi… "
             "⇒ الفوركس/المؤشرات بلا منفّذ تقريباً؛ الباقي ذهبيّ الطابع أو نادر الإشارة. "
             "هذا وحده يفسّر «لا صفقات على أي عملة». للإلغاء: احذف العلم وأعد الوصيّ.")
    else:
        _add(3, "وضع التركيز غير مفعّل", "قائمة المحرّكات الكاملة تحت الحراسة.")


def check_governance():
    g = _j(RN / "engine_governance.json")
    if not g:
        _add(3, "لا حوكمة مايسترو مقيّدة", "engine_governance.json غائب ⇒ مضاعِف 1.0 للجميع.")
        return
    paused = g.get("paused") or []
    mults = {k: v for k, v in (g.get("mults") or {}).items() if float(v) < 0.5}
    if paused:
        _add(1, f"المايسترو مُوقِف {len(paused)} محرّكاً بالكامل (paused)",
             f"المجيكات: {paused} — لا فتح جديد لها إطلاقاً حتى يرفعها المايسترو.")
    if mults:
        _add(2, "مضاعِفات خانقة (<0.5)", str(mults))
    if not paused and not mults:
        _add(3, "حوكمة المايسترو غير خانقة", "")


def check_edge_governor():
    led = _j(RN / "edge_governor_retired.json")
    if led:
        last = led[-3:]
        _add(1, f"حاكم الحافّة قاعَدَ {len(led)} محرّكاً (enabled=false)",
             "آخرها: " + "; ".join(f"{e.get('name')}({e.get('magic')}) net_3d={e.get('net_3d')}"
                                    for e in last))
    else:
        _add(3, "حاكم الحافّة لم يُقاعد أحداً بعد", "")


def check_risk_register():
    d = _j(RN / "risk_register.json")
    if d and d.get("emergency") and time.time() - float(d.get("ts", 0)) < 300:
        _add(0, "علم الطوارئ مرفوع (risk_register.emergency)",
             "المحرّكات التي تحترمه تتوقّف عن الفتح.")
    else:
        _add(3, "لا علم طوارئ", "")


# ═══ 2) MT5: الطرفيّة والحساب والسوق ═══════════════════════════════════════

def check_mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        _add(2, "MetaTrader5 غير متاح هنا",
             "شغّل الأداة على جهاز التداول لفحص الطرفيّة/الحساب/السبريد.")
        return
    if not mt5.initialize():
        _add(0, "mt5.initialize فشل", "الطرفيّة مطفأة أو الاتصال مقطوع ⇒ لا أحد يتداول.")
        return
    try:
        ti = mt5.terminal_info()
        if ti and not ti.trade_allowed:
            _add(0, "زرّ AutoTrading في الطرفيّة مُطفأ! (trade_allowed=false)",
                 "كل order_send يرفض بـ retcode 10027 — سببٌ واحد يوقف الأسطول كلّه. "
                 "فعّل زرّ Algo Trading الأخضر في MT5.")
        else:
            _add(3, "AutoTrading مفعّل في الطرفيّة", "")
        a = mt5.account_info()
        if a:
            srv = a.server or ""
            demo = ("trial" in srv.lower()) or ("demo" in srv.lower())
            if not demo:
                _add(0, f"الخادم '{srv}' ليس Trial/Demo",
                     "كل المحرّكات ترفض التداول (حارس الديمو) + real_lock يكتب kill.")
            else:
                _add(3, f"حساب ديمو مؤكّد ({srv})", "")
            ml = getattr(a, "margin_level", 0) or 0
            _add(3 if (ml == 0 or ml > 200) else 1,
                 f"رصيد {a.balance:.2f}$ · حقوق {a.equity:.2f}$ · هامش {ml:.0f}%",
                 "هامش ≤130% ⇒ master_floor يصفّي ويقفل. رصيد صغير قد يمنع فتح 0.01 "
                 "على المؤشرات (retcode 10019 لا مال).")
        # عيّنة سبريد وجلسة
        now = datetime.now(timezone.utc)
        for sym in ("XAUUSDm", "EURUSDm", "USTECm"):
            mt5.symbol_select(sym, True)
            tk = mt5.symbol_info_tick(sym)
            if not tk or not tk.bid:
                _add(2, f"{sym}: لا تسعير الآن", "سوق مغلق/رمز غير مفعّل.")
                continue
            stale = time.time() - (tk.time or 0)
            spread = tk.ask - tk.bid
            _add(3 if stale < 120 else 2,
                 f"{sym}: سبريد {spread:.2f} · آخر تيك قبل {int(stale)}ث",
                 "تيك بائت >120ث = جلسة مغلقة. سبريد ليليّ واسع = فيتوهات السبريد تمنع.")
        _add(3, f"الساعة الآن {now:%H:%M} UTC ({(now.hour - 4) % 24:02d}:00 نيويورك تقريباً)",
             "الحظر الليليّ (night_block) مفعّل افتراضياً في radhi_mimic وbrain_trader؛ "
             "وNR7/Fabio لا يشتغلان إلا حول جلسات نيويورك (12:30+ UTC صيفاً).")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


# ═══ 3) إعدادات محرّكات الدخول ══════════════════════════════════════════════

ENGINES_CFG = [
    ("الحارس gold_level_sentinel (20260701)", RN / "gold_sentinel_config.json",
     ("enabled", "execute")),
    ("محاكي راضي (20260703)", RN / "radhi_mimic_config.json", ("enabled",)),
    ("R Core brain_trader (20260706)", RN / "brain_trader_config.json", ("enabled",)),
    ("هجوم اللحظات boundary_pilot (20260714)", RN / "boundary_pilot_config.json",
     ("enabled", "execute")),
    ("هجين r_hybrid_pilot (20260713)", RN / "r_hybrid_pilot_config.json",
     ("enabled", "execute")),
    ("حارس العملات level_sentinel_multi (20260709)",
     MT5DIR / "level_sentinel_multi_config.json", ("enabled", "execute")),
    ("Fabio ORB (20260716)", RN / "fabio_orb_config.json", ("enabled", "execute")),
]


def check_engine_configs():
    for name, path, keys in ENGINES_CFG:
        cfg = _j(path)
        if cfg is None:
            _add(2, f"{name}: لا ملف إعداد", f"{path.name} غير موجود (قد لم يُقلع بعد).")
            continue
        offs = [k for k in keys if cfg.get(k, True) is False]
        if offs:
            why = cfg.get("retired_reason") or cfg.get("_note", "")[:60]
            _add(1, f"{name}: {'+'.join(offs)}=false ⇒ لا يفتح صفقات",
                 (f"قاعَدَه {cfg.get('retired_by')}: {why}" if cfg.get("retired_by")
                  else f"مُطفأ في {path.name}. execute=false = وضع إشارة فقط."))
        else:
            _add(3, f"{name}: مفعّل", "")


# ═══ التقرير ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n🩺 why_no_trades — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"   الجذر: {MT5DIR}\n" + "═" * 74)
    check_kill(); check_watchdog(); check_focus(); check_governance()
    check_edge_governor(); check_risk_register(); check_mt5(); check_engine_configs()
    icons = {0: "🔴", 1: "🟠", 2: "🟡", 3: "🟢"}
    R.sort(key=lambda r: r[0])
    for sev, title, detail in R:
        print(f"{icons[sev]} {title}")
        if detail:
            print(f"    ↳ {detail}")
    blockers = [t for s, t, _ in R if s == 0]
    print("═" * 74)
    if blockers:
        print("⛔ الحكم: يوجد قاطعٌ عامّ — عالج بالترتيب:")
        for i, b in enumerate(blockers, 1):
            print(f"   {i}. {b}")
    else:
        eng = [t for s, t, _ in R if s == 1]
        if eng:
            print("🟠 الحكم: لا قاطع عامّ — لكن هذه المحرّكات/الأوضاع تمنع الدخول:")
            for i, b in enumerate(eng, 1):
                print(f"   {i}. {b}")
        else:
            print("🟢 الحكم: لا مانع بنيويّ — الصمت غالباً عابر (ليل/سبريد/ندرة إشارة).")


if __name__ == "__main__":
    main()
