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

# هوية كاتب مفتاح القتل من محتواه — وهل يُمسح تلقائياً أم لاصق يحتاج يدك
_KILL_WRITERS = [
    ("drawdown_recovery", "🚨 لاصق! لا يوجد أيّ كود يمسحه — احذفه يدوياً بعد فهم السحب (DD≥18% من القمة). "
                           "وتحقّق من peak_equity.json: قمّة قديمة = انطلاق دائم."),
    ("real_lock(cage)", "يُعاد كتابته كل 10ث ما دام خرق القفص قائماً (خسارة اليوم ≥$5 أو لوت زائد) — عالج السبب لا الملف."),
    ("real_lock", "يُعاد كتابته كل 10ث! حذفه بلا فائدة — السبب: اسم الخادم بلا Trial/Demo. "
                   "لو حسابك ديمو فعلاً فالخادم أعيدت تسميته ⇒ حدّث كشف الديمو."),
    ("master_floor", "يُمسح تلقائياً عند التعافي (حقوق > الأرضية×1.25) — لكن انظر فخّ القمة البائتة أدناه."),
    ("Telegram", "قتل يدويّ عن بُعد — أزِله من تيليغرام أو احذف الملف."),
    ("voice", "قتل بأمر صوتيّ — احذف الملف للاستئناف."),
]


def check_kill():
    found = False
    for p, label in ((RN / "kill_switch.txt", "data/r_native/kill_switch.txt"),
                     (MT5DIR / "kill_switch.txt", "kill_switch.txt (الجذر)")):
        if p.exists():
            found = True
            body = ""
            try:
                body = p.read_text(encoding="utf-8", errors="replace")[:150].strip()
            except Exception:
                pass
            hint = next((h for k, h in _KILL_WRITERS if k in body),
                        "كاتب غير معروف — اقرأ أول كلمة في المحتوى.")
            _add(0, f"مفتاح القتل موجود: {label}",
                 f"المحتوى: «{body or '—'}» · عمره {int(_age_min(p) or 0)}د. {hint} "
                 "(ملاحظة: بعض المحرّكات تقرأ الجذر فقط وبعضها r_native فقط — الملفّان معاً = صمتٌ تامّ.)")
    if not found:
        _add(3, "لا مفتاح قتل", "kill_switch.txt غير موجود في الموقعين.")


def check_peak_traps():
    """🪤 فخّا القمة البائتة: master_floor (12% من القمة) وdrawdown_recovery (سحب 18%) —
    ملفّا القمة لا يتصفّران مع تغيير/تصفير الحساب ⇒ انطلاق دائم لا يشفى."""
    mfs = _j(RN / "master_floor_state.json") or {}
    peak_mf = float(mfs.get("peak", 0) or 0)
    pe = _j(RN / "peak_equity.json") or {}
    peak_dd = float(pe.get("peak", pe.get("peak_equity", 0)) or 0)
    eq = None
    try:
        import MetaTrader5 as m
        if m.initialize():
            a = m.account_info()
            eq = float(a.equity) if a else None
            m.shutdown()
    except Exception:
        pass
    if peak_mf:
        floor = 0.12 * peak_mf
        if eq is not None and eq <= floor * 1.25:
            _add(0, f"🪤 فخّ القمة البائتة (master_floor): قمّة مسجّلة {peak_mf:.0f}$ ⇒ "
                    f"أرضيّة {floor:.0f}$ والحقوق {eq:.0f}$",
                 "كسرٌ دائم: يصفّي ويكتب kill كل 4ث ولا يُشفى أبداً (التعافي يتطلّب حقوق > "
                 "الأرضية×1.25). العلاج: احذف master_floor_state.json (أو حدّث peak) بعد التأكد "
                 "أن القمة تعود لحسابٍ/رصيدٍ قديم.")
        else:
            _add(3, f"قمّة master_floor مسجّلة {peak_mf:.0f}$ — لا كسر حاليّاً", "")
    if peak_dd and eq is not None:
        dd = (1 - eq / peak_dd) * 100 if peak_dd > 0 else 0
        if dd >= 18:
            _add(0, f"🚨 سحب {dd:.0f}% من قمّة peak_equity.json ({peak_dd:.0f}$→{eq:.0f}$) "
                    "≥ عتبة drawdown_recovery (18%)",
                 "هذا الوكيل يكتب kill_switch «لاصقاً» لا يمسحه أيّ كود. لو القمّة من حسابٍ "
                 "قديم: احذف/حدّث peak_equity.json ثم احذف مفتاح القتل.")
        else:
            _add(3, f"السحب من القمّة {dd:.0f}% — تحت عتبة الـ18%", "")


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
    led = _j(RN / "edge_governor_ledger.json") or _j(RN / "edge_governor_retired.json")
    if led:
        rests = [e for e in led if e.get("action", "rest") == "rest"][-3:]
        _add(2 if rests else 3, f"مُعالِج الحافّة: {len(led)} حدث علاج/إفاقة",
             "آخر استراحات: " + "; ".join(
                 f"{e.get('name')}({e.get('magic')}) حتى {e.get('revive_at', '?')[:16]}"
                 for e in rests) if rests else "")
    else:
        _add(3, "مُعالِج الحافّة لم يعالج أحداً بعد", "")


# ═══ 1ب) بوّابات المنفّذين الرئيسيّين (تدقيق 2026-07-15) ═══════════════════

V2DATA = MT5DIR / "r_native_v2" / "data"


def check_unified_trader():
    """المنفّذ المتعدّد 99782 — أكبر مغطٍّ للعملات؛ يموت صامتاً بلا live_genome."""
    lg = _j(V2DATA / "live_genome.json")
    if not lg or not lg.get("params"):
        _add(1, "الموحّد 99782: live_genome.json مفقود/فارغ ⇒ مسح الدخول كلّه مُعطّل صامتاً",
             f"{V2DATA / 'live_genome.json'} — العملية تبدو حيّة (تدير المراكز) لكنها لا تدخل أبداً.")
    else:
        _add(3, "الموحّد 99782: جينوم حيّ موجود", "")
    age = _age_min(V2DATA / "son_status.json")
    if age is not None and age > 15:
        _add(1, f"الموحّد 99782: نبضه بائت منذ {int(age)} دقيقة (son_status.json)",
             "معلّق — الوصيّ يقتله ويعيده فوق 15د، لكن تحقّق يدوياً.")
    gp = _j(V2DATA / "genome_paused.json")
    if gp and gp.get("paused"):
        _add(1, "الموحّد 99782: موقوف عبر genome_paused.json",
             f"السبب: {gp.get('reason', '—')} — كل رموزه الـ12 بلا دخول.")


def check_dd_recovery():
    d = _j(RN / "dd_recovery_state.json")
    if d and d.get("blocks_new_entries"):
        _add(0, "وضع التعافي من السحب يمنع كل الدخول الجديد (dd_recovery_state)",
             f"drawdown={d.get('drawdown_pct')}% · severity={d.get('severity_level')} — "
             "يخرس الموحّد 99782 + المنفّذ 20260605 معاً على كل الرموز.")
    else:
        _add(3, "لا حظر تعافٍ من السحب", "")


def check_reflection_night():
    s = _j(MT5DIR / "reflection" / "strategy.json")
    try:
        nb = (s or {}).get("night_trade_block") or {}
        if nb.get("enabled"):
            off = int((s or {}).get("server_utc_offset_hours", 3))
            sh, eh = int(nb.get("start_hour", 22)), int(nb.get("end_hour", 8))
            srv_h = (datetime.now(timezone.utc).hour + off) % 24
            inside = (srv_h >= sh or srv_h < eh) if sh > eh else (sh <= srv_h < eh)
            if inside:
                _add(0, f"⏰ الحظر الليليّ المجدول فعّال الآن (reflection/strategy.json)",
                     f"ساعة الخادم {srv_h}:00 داخل [{sh}:00→{eh}:00] ⇒ الموحّد 99782 + "
                     f"المنفّذ 20260605 مكتومان على كل الرموز إلا BTCUSDm حتى {eh}:00 "
                     f"بتوقيت الخادم ({(eh - off) % 24}:00 UTC). هذا يفسّر صمت الليل كاملاً.")
            else:
                _add(3, f"الحظر الليليّ المجدول غير فعّال الآن (ساعة الخادم {srv_h}:00)",
                     f"نافذته [{sh}:00→{eh}:00] بتوقيت الخادم — 10 ساعات كتمٍ يوميّاً للمنفّذين الرئيسيّين.")
    except Exception as e:
        _add(2, "تعذّر قراءة حظر الليل reflection/strategy.json", str(e))


def check_circuit_breaker():
    cb = _j(V2DATA / "circuit_breaker_state.json")
    if not cb:
        _add(3, "لا تجميدات قاطع دائرة", "")
        return
    now = time.time()
    frozen = []
    for key, st in (cb.items() if isinstance(cb, dict) else []):
        try:
            until = float((st or {}).get("freeze_until_ts", 0))
            if until > now:
                frozen.append(f"{key} ({int((until - now) / 60)}د متبقّية: "
                              f"{(st or {}).get('freeze_reason', '—')})")
        except Exception:
            pass
    if frozen:
        _add(1, f"قاطع الدائرة مجمّد {len(frozen)} (ماجيك:رمز) — يصمد بعد إعادة التشغيل",
             " · ".join(frozen[:5]))
    else:
        _add(3, "لا تجميدات قاطع دائرة فعّالة", "")


def check_r_executor():
    st = _j(MT5DIR / "friday_v3" / "data" / "r_executor_state.json")
    if st:
        if st.get("mode") and st["mode"] != "LIVE":
            _add(1, f"المنفّذ 20260605 بوضع {st['mode']} — يسجّل ولا يرسل أوامر",
                 "الوصيّ يمرّر --live؛ لو الحالة PAPER فالعملية الحيّة أقلعت بلا العلم.")
        if st.get("armed") is False:
            _add(1, "المنفّذ 20260605: armed=false — الدخول معطّل", "")
        if st.get("frozen_until"):
            _add(1, f"المنفّذ 20260605 مجمّد حتى {st['frozen_until']}",
                 f"السبب: {st.get('frozen_reason', '—')}")
        la = str(st.get("last_action", ""))
        if "gate_error" in la or "FROZEN" in la:
            _add(2, f"المنفّذ 20260605: آخر فعل = {la[:60]}", "")
    # بوّابة العقل 5055 — fail-closed: سقوطها = صمت المنفّذ 20260605 كليّاً
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:5055/api/r/trade_gate",
                                    timeout=5) as r:
            g = json.loads(r.read().decode("utf-8", "replace"))
        _add(3, f"بوّابة العقل 5055 حيّة — الحكم: {g.get('verdict', '?')}",
             str(g.get("reasons", g.get("reason", "")))[:100])
    except Exception:
        _add(1, "بوّابة العقل :5055 لا تستجيب — المنفّذ 20260605 fail-closed ⇒ صامت",
             "شغّل brain_server.py (الوصيّ يحرسه) وتأكّد ألّا نزاع منفذ.")


def check_conviction_feeds():
    age = _age_min(RN / "unified_brain.json")
    if age is None or age > 0.6:
        _add(1, "تغذية المخّ الواحد بائتة (unified_brain.json أقدم من 30ث)",
             "brain_trader يرى قناعاتٍ ميّتة ⇒ صفر رموز ⇒ صفر دخول رغم أنه مفعّل.")
    else:
        _add(3, "تغذية المخّ الواحد طازجة", "")
    if not (V2DATA / "brain_live__XAUUSDm.json").exists():
        _add(2, "لقطات brain_live__<SYM>.json مفقودة",
             "الموحّد 99782 صامت على أي رمز بلا لقطته (جسر chart_signal_writer).")


def check_multi_trader_session():
    h = datetime.now(timezone.utc).hour
    in_london = 7 <= h < 16
    in_ny_overlap = 12 <= h < 16
    if in_london or in_ny_overlap:
        _add(3, "نافذة جلسات multi_trader مفتوحة الآن (LONDON/NY_OVERLAP)", "")
    else:
        _add(2, f"multi_trader خارج نافذته الآن (الساعة {h}:00 UTC)",
             "يدخل فقط في LONDON/NY_OVERLAP (~07:00–16:00 UTC) — صمته الليليّ طبيعيّ.")


def check_zombie_locks():
    st = _j(RN / "watchdog_status.json") or {}
    hot = {k: v for k, v in (st.get("restarts") or {}).items() if int(v) >= 20}
    if hot:
        _add(1, f"محرّكات تُعاد بلا توقّف ({len(hot)}) — اشتباه قفل زومبي (engine_lock)",
             "عمليّة معلّقة تمسك منفذ القفل فكلّ إعادة تموت فوراً بصمت. "
             f"الأعلى: {sorted(hot.items(), key=lambda x: -x[1])[:5]} — اقتل الـPID العالق يدوياً.")
    else:
        _add(3, "لا اشتباه أقفال زومبي", "")


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
                 "على المؤشرات (retcode 10019 لا مال) — وmulti_trader يتخطّى صامتاً أيّ رمزٍ "
                 "أدنى لوته يخاطر >2% من الحقوق.")
            if a.balance > 0 and a.equity < 0.70 * a.balance:
                _add(1, f"حقوق ({a.equity:.0f}$) < 70% من الرصيد ({a.balance:.0f}$) — "
                        "RiskSentinel يكتم الموحّد 99782 على كل الرموز",
                     "عائم سالب كبير — أغلق/قلّص الخاسر العائم أو انتظر التعافي.")
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
    check_kill(); check_peak_traps(); check_watchdog(); check_focus(); check_governance()
    check_edge_governor(); check_risk_register()
    check_reflection_night(); check_dd_recovery(); check_unified_trader()
    check_circuit_breaker(); check_r_executor(); check_conviction_feeds()
    check_multi_trader_session(); check_zombie_locks()
    check_mt5(); check_engine_configs()
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
