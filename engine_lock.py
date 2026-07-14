# -*- coding: utf-8 -*-
"""engine_lock.py — قفل نسخة-مفردة لكل محرّك (منفذ localhost ثابت لكل اسم). يمنع نسختين تتداولان معاً
(الخطر الذي رأيناه: بدءٌ يدويّ يسابق الوصيّ ⇒ نسختان). يُستدعى أوّل main(): إن فشل القفل (نسخة أخرى
تعمل) ⇒ خروج هادئ. يتحرّر تلقائياً عند موت العملية. متوافق مع نمط stub+real (الحقيقيّة تمسك LISTEN)."""
import socket, sys

# منافذ صريحة (لا تتعارض مع القائمة: warroom 8617 / multi 8708 / gene 8712 / news 8714 / spike 8716)
_PORTS = {
    "gold_scalper": 8720, "orb_trader": 8722, "gold_straddle": 8724,
    "portfolio_maestro": 8726, "profit_harvester": 8728, "real_account_gate": 8730,
    "bot_feature_recorder": 8732, "manual_manager": 8734, "manual_mimic": 8736,
    "pipflow_core": 8738, "master_floor": 8740, "peak_watch": 8742,
    "momentum_harvester": 8744, "chart_server": 8746, "manual_lot_alert": 8748,
    "youtube_analyst": 8750, "news_alarm": 8752,
    # 2026-07-02: تصادم crc32 مكتشف — news_straddle والوصيّ كلاهما ⇒ 8940 (انتحار وصيّ صامت). منفذان صريحان:
    "watchdog_guard": 8754, "news_straddle": 8756,
    "agent_council": 8758,                                # 🏛️ مجلس الـ90 وكيلاً (2026-07-06)
    "r_trader_gateway": 8760,                             # 🚪 بوّابة R Trader :8020 (2026-07-06)
    "desk_scoreboard": 8762,                              # 🏁 سبّورة الديسك لكل ماجيك (قراءة فقط 2026-07-06)
    "council_sniper": 8764,                               # 🏛️🎯 قنّاص المجلس (2026-07-07)
    "level_sentinel_multi": 8768,                         # 🌍 حارس المستويات متعدد العملات (نُقل 8766→8768: تصادم مع منفذ tick_ws HTTP، تدقيق C11 2026-07-07)
    "hand_guard": 8772,                                   # 🖐️ حرس اليد 2026-07-07 (8770 = خلفية FRIDAY — متخطّى)
    "brain_bus": 8774,                                    # 🚌 ناقل العقل: مجمِّع رسائل تبادل-المعلومات بين المحرّكات (قراءة فقط 2026-07-08)
    "meta_learner": 8776,                                 # 🧭📏 المتعلّم-الفوقيّ الصادق: قياسٌ ذاتيّ OOS لكل صفقة مُغلقة (لا يتاجر 2026-07-08)
    "adaptive_sense": 8778,                               # 👁️🫀 عيون وإحساس + ثقة من النتائج (قراءة فقط، لا ماجيك، لا تداول 2026-07-08)
    "manual_feature_recorder": 8780,                      # 📸 مُسجّل بصمة لحظة كل صفقة يدوية (magic-0) → friday.db (2026-07-08)
    "hand_miner": 8782,                                   # 🖐️⛏️ معدِّن اليد: يفكّ لماذا تربح يدك OOS (قراءة فقط، لا تداول 2026-07-08)
    "tradingview_bridge": 8792,                            # 🌉 جسر TradingView→MT5 (webhook منفذ 8025، القفل 8792 2026-07-10)
    "conflict_resolver": 8784,                            # 🧩 المُعالِج الذاتيّ لتعارض القرارات (وقائيّ + قصّ الخاسر المتعارض 2026-07-08)
    "knowledge_grower": 8786,                             # 🌱 منمّي المعرفة: يقطّر التجربة الحيّة إلى معرفةٍ مقيسة تتكاثر بالمخّ (قراءة فقط 2026-07-08)
    "edge_scanner": 8788,                                 # 🔬 ماسح الحافّة: يقيس كل مؤشّر لكل رمز/فريم OOS بصدق — سجّل ما ينفع (قراءة فقط 2026-07-08)
    "trade_autopsy": 8790,                                # 🔎 مشرّح الصفقات: لماذا خسرنا (دخول خاطئ أم إعادة ربح؟) عبر MFE (قراءة فقط 2026-07-08)
}
_HELD = []


def claim(name):
    """يحجز قفل المحرّك. إن كانت نسخة أخرى تمسكه ⇒ sys.exit(0) (خروج هادئ)."""
    port = _PORTS.get(name)
    if port is None:
        import zlib
        port = 8800 + (zlib.crc32(name.encode()) % 180)   # ثابتٌ عبر العمليّات (hash عشوائيّ لكل عمليّة!)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 🔒 ويندوز: بلا SO_EXCLUSIVEADDRUSE قد تنجح عمليّتان بنفس المنفذ ⇒ تكرار تداول. هذا يضمن الحصريّة.
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except OSError:
            pass
    try:
        s.bind(("127.0.0.1", port)); s.listen(1)
        _HELD.append(s)                       # إبقاء المرجع حيّاً طوال عمر العملية
        return True
    except OSError:
        print(f"[{name}] نسخة منفّذة أخرى تعمل (قفل {port}) — خروج", flush=True)
        sys.exit(0)
