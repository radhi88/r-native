"""watchdog_guard.py — THE NEVER-STOP GUARANTEE: watches every engine of the system, and the
moment one dies it RESPAWNS it windowless. Writes watchdog_status.json so the dashboard shows
which engines are alive/restarted. The user's order: "اهم شيء لا نوقف".

Run:  pythonw watchdog_guard.py   (it also guards itself being the only copy)
"""
from __future__ import annotations
import json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

import psutil

try:
    import engine_lock
    engine_lock.claim("watchdog_guard")   # 🔒 2026-07-02: قفل مفرد للوصيّ نفسه — نهاية حرب التوائم
except SystemExit:                        # (keepalive + إطلاق يدويّ كانا يتسابقان ⇒ وصيّان ⇒ أسطول مزدوج)
    raise
except Exception:
    pass

MT5 = r"C:\Users\Radhi\MT5"
V2 = MT5 + r"\r_native_v2"
PYW = MT5 + r"\.venv\Scripts\pythonw.exe"
if not os.path.exists(PYW):
    PYW = "pythonw"
FLAGS = 0x00000008 | 0x00000200          # DETACHED | NEW_PROCESS_GROUP
STATUS = Path(MT5) / "data" / "r_native" / "watchdog_status.json"
CHECK_S = 30      # ⚡ 2026-07-15 (أمر «أسرع بكثير»): إحياء الساقط خلال نصف دقيقة بدل دقيقة

# needle (cmdline match) -> (args, cwd)
ENGINES = {
    # 👑 الرابح أوّلاً (أمر المستخدم 2026-07-10 «كودنا الرابح اطلقه دائماً اول واحد»): الحارس (ماجيك 20260701،
    # +$35.74/66 صفقة) يُفحَص ويُطلَق قبل كلّ المحرّكات — أوّل من يعود عند أيّ سقوط.
    "gold_level_sentinel.py":     (["gold_level_sentinel.py"], MT5),
    # ⛔ DEPRECATED 2026-07-14 (توحيد التشغيل #1): عقلٌ ثانٍ يربط :5055 ويتنازعه مع brain_server.py
    # الجذر (split-brain — سبب تعارض المنفذ المتكرّر). عقلٌ واحد فقط. للتراجع: أزِل التعليق.
    # "r_native.brain_server":      (["-u", "-m", "r_native.brain_server"], MT5),
    "runtime.unified_trader":     (["-m", "runtime.unified_trader"], V2),
    "brain_server.py":            (["brain_server.py"], MT5),   # 🧠 العقل 5055 (كان يعمل بلا حارس!)
    # 🎯 المنفّذ الموحّد الوحيد (20260605) تحت الوصيّ — LIVE على الديمو (توحيد #1 Step 3). حواجز:
    # لوت 0.01، سقف يوميّ $10، حظر ليليّ، master_floor، kill_switch. للإيقاف: علّق السطر أو أنشئ kill_switch.txt.
    "friday_v3.algory.r_executor": (["-u", "-m", "friday_v3.algory.r_executor", "--live", "--no-brain-json", "--interval", "5"], MT5),  # ⚡ 8→5ث (أمر «أسرع»)
    # 🔬 مُثبِت NR7 الأماميّ (magic 111111): الحافّة الوحيدة التي نجت من المسح العميق —
    # USTECm M15، إثبات ورقيّ ديمو، مركز واحد. يُغذّي /api/r/proof_gate?magic=111111.
    "nr7_prover.py":              (["nr7_prover.py"], MT5),
    # 🚦 حاكم الحافّة (2026-07-15، لا ماجيك — لا يتاجر): الإصلاح المنظوميّ للنزيف. يقرأ صافي كل ماجيك
    # من desk_scoreboard.json ويقلب enabled=false تلقائياً لأيّ محرّك دخولٍ يتجاوز أرضيّة الخسارة —
    # المحرّكات تخمد بنفسها. تقاعدٌ أحاديّ، يحترم gov_override + kill_switch. قراءة/كتابة ملفّات فقط.
    "edge_governor.py":           (["edge_governor.py"], MT5),
    # 🎯 نموذج Fabio ORB (2026-07-15، magic 20260716): اختراق نطاق افتتاح نيويورك على USTECm (نظير NQ)،
    # طويلٌ فقط، هدف 1R، دلتا اختياريّ. ديمو + execute=false افتراضياً (إشارةٌ حتى تفعّله). يُحكَم بالحاكم.
    "fabio_orb.py":               (["fabio_orb.py"], MT5),
    # ✅ multi_trader أُعيد (طلب المستخدم 2026-07-02 «رجّع المشروع على جميع العملات») — تحت lot_guard + حوكمة المايسترو.
    "multi_trader.py":            (["multi_trader.py", "--loop"], MT5),
    # btc_live.py مُطفأ 2026-06-15: تدقيق 30 يوم = بلا حافة (net −$56، WR 34%، PF 0.89) ويعاكس
    # مركز BTC في multi_trader. إزالته رافعة ربحية نظيفة. BTC يبقى مغطّى عبر روستر multi_trader.
    # لإعادة تفعيله: أزل التعليق. (الإطفاء = حذفه من الحارس + قتل العملية.)
    # "btc_live.py":                (["btc_live.py", "--loop"], MT5),
    "coordinator.py":             (["coordinator.py", "--loop"], MT5),
    # 🆕 2026-07-14 منظومة التعلّم والهجوم (أمر المستخدم: لا يتوقّف شيء أبداً — كلّها تحت الحراسة):
    "market_sweeper.py":          (["market_sweeper.py"], MT5),            # 🌍 الماسح الشامل المتعلّم
    "r_hybrid_pilot.py":          (["r_hybrid_pilot.py"], MT5),            # 🧪 هجين B/E (20260713)
    "boundary_hunter.py":         (["boundary_hunter.py"], MT5),           # 🗡️ صيّاد اللحظات (تعلّم)
    "boundary_pilot.py":          (["boundary_pilot.py"], MT5),            # ⚔️ هجوم اللحظات (20260714)
    "learning_pulse.py":          (["learning_pulse.py"], MT5),            # 🎓 نبضة التعلّم + المُرقّي
    "r_native.auto_ga_daemon":    (["-m", "r_native.auto_ga_daemon", "--daemon", "--interval-min", "15"], MT5),  # 🧬 ديمون الحملات الجينية
    # algory_chart_dashboard (:8866) REMOVED: dies on pandas deadlock under 21-engine load and
    # burned 200+ futile respawns. ARENA :8870 supersedes it.
    # market_data_collector.py أُزيل (تدقيق التغذية 2026-06-29): سلكٌ ميّت — لا أحد يقرأ market_data_live/hot.json،
    # وكان مُعلّقاً ~4.5س يكتب {count:0} بينما الحارس يراه "حيّاً". نفس الحقول متاحة أرخص من market_internals.py (مُستهلَك).
    # "market_data_collector.py":   (["market_data_collector.py", "--loop"], V2),
    "paper_prover.py":            (["paper_prover.py", "--loop"], V2),
    "accuracy_updater.py":        (["accuracy_updater.py", "--loop"], V2),
    "_reoptimize_loop.py":        (["_reoptimize_loop.py"], V2),
    "secure_learner.py":          (["secure_learner.py", "--loop"], MT5),
    "intermarket.py":             (["intermarket.py", "--loop"], MT5),
    "news_engine.py":             (["news_engine.py", "--loop"], MT5),
    "llm_analyst.py":             (["llm_analyst.py", "--loop"], MT5),
    "genome_evo_logger.py":       (["genome_evo_logger.py", "--loop"], MT5),
    "truth_tracker.py":           (["truth_tracker.py", "--loop"], MT5),
    "risk_manager.py":            (["risk_manager.py"], MT5),
    # 🛑 الحاجز الوحيد للكارثة بعد إزالة الحد اليومي/سقف 2% (طلب المستخدم): إيقاف+تصفية عند هبوط
    # الحقوق <= 50% من القمة (مع حماية اليدوي/الخبراء الخارجيين). يجب أن يبقى حيّاً دائماً.
    "master_floor.py":            (["master_floor.py"], MT5),
    "straddle_hunter.py":         (["straddle_hunter.py"], MT5),
    "evolution_director.py":      (["evolution_director.py"], MT5),
    "gene_tournament.py":         (["gene_tournament.py"], MT5),
    "zone_memory.py":             (["zone_memory.py"], MT5),
    "gene_ledger.py":             (["gene_ledger.py"], MT5),
    "delta_feed.py":              (["delta_feed.py"], MT5),
    "news_gene.py":               (["news_gene.py"], MT5),
    "brain_animation.py":         (["brain_animation.py"], MT5),
    "runtime.chart_signal_writer": (["-m", "runtime.chart_signal_writer", "--loop"], V2),
    "plutobrain_swarm.orchestrator": (["-m", "plutobrain_swarm.orchestrator"], MT5),
    "graph_brain.py":             (["graph_brain.py"], MT5),
    "tick_ws.py":                 (["tick_ws.py"], MT5),
    "war_room.py":                (["war_room.py"], MT5),
    "macro_feed.py":              (["macro_feed.py"], MT5),
    "orb_trader.py":              (["orb_trader.py"], MT5),
    "vol_forecast.py":            (["vol_forecast.py"], MT5),
    "market_internals.py":        (["market_internals.py"], MT5),
    "forecast_lab.py":            (["forecast_lab.py"], MT5),
    "tape_recorder.py":           (["tape_recorder.py"], MT5),
    "ml_indicator.py":            (["ml_indicator.py", "--symbols", "XAUUSDm,BTCUSDm,US30m", "--tf", "M15"], MT5),
    "manual_guard.py":            (["manual_guard.py"], MT5),
    "edge_guard.py":              (["edge_guard.py"], MT5),
    "manual_feature_recorder.py": (["manual_feature_recorder.py"], MT5),
    # 🖐️⛏️ معدِّن اليد: يعيد تعدين لماذا تربح يد المستخدم (OOS) كل ساعة → hand_edge.json (قراءة فقط، لا يتاجر).
    "hand_miner.py":              (["hand_miner.py", "loop"], MT5),
    # 🧩 المُعالِج الذاتيّ: يقرأ DXY+المجلس+مراكزنا ويحلّ التعارض (وقائيّ + قصّ الخاسر المتعارض) — لا يمسّ يدك/الخارجيّة.
    # 🌉 جسر TradingView→MT5: يستمع webhook تنبيهات الشارت وينفّذ على ميتا (ديمو، سرّ، execute=false افتراضيّاً).
    "tradingview_bridge.py":      (["tradingview_bridge.py"], MT5),
    # 🚇 حارس نفق TradingView: يُبقي cloudflared حيّاً نحو :8025 ويكتب الرابط في tv_tunnel.json (2026-07-10).
    "tv_tunnel_keeper.py":        (["tv_tunnel_keeper.py"], MT5),
    "conflict_resolver.py":       (["conflict_resolver.py"], MT5),
    # 🌱 منمّي المعرفة: يقطّر تجربة الأسطول الحيّة إلى معرفةٍ مقيسة تتكاثر بطبقة المخّ (قراءة فقط، لا يتاجر).
    "knowledge_grower.py":        (["knowledge_grower.py"], MT5),
    # 🔬 ماسح الحافّة: يقيس كل مؤشّر لكل رمز/فريم OOS (walk-forward بعد الكلفة) — يسجّل ما ينفع بصدق (قراءة فقط).
    "edge_scanner.py":            (["edge_scanner.py"], MT5),
    # 🔎 مشرّح الصفقات: يشرّح كل صفقة مُغلقة (دخول خاطئ أم إعادة ربح؟) عبر MFE — قراءة فقط.
    "trade_autopsy.py":           (["trade_autopsy.py"], MT5),
    # 📸 مُسجّل ميزات دخول البوت → friday.db: يفكّ تجمّد جدول features (13يوماً) الذي أعمى المتعلّم الصافي.
    "bot_feature_recorder.py":    (["bot_feature_recorder.py"], MT5),
    # ── توسيع الأسطول (طلب المستخدم: شغّلهم كلهم) — المايسترو/الأرضية يحكمان النزّاف ──
    "scalp_evolver.py":           (["scalp_evolver.py", "--loop"], MT5),        # يضبط gold_live بعد كل صفقة (لا يتداول مباشرة)
    "market_discovery.py":        (["market_discovery.py", "--loop"], V2),      # ماسح قابليّة-التداول (قراءة فقط)
    "runtime.genome_academy":     (["-m", "runtime.genome_academy"], V2),       # مختبر تطوير الجينات (وضع وحدة)
    "runtime.footprint_brain_bridge": (["-m", "runtime.footprint_brain_bridge"], V2),  # جسر بصمة القدم (footprint)
    # 🟡 gold_straddle (3627): انعكاس ذهب مستمرّ — NO_EDGE مُثبت تاريخياً؛ يُشغَّل بطلب المستخدم، يحرسه master_floor.
    "gold_straddle_3627.py":      (["gold_straddle_3627.py"], MT5),
    # 🗄️ مُسجّل صفقات البوت → friday.db (trades): أساس كل التعلّم/السبورة. كان يعمل من worktree مؤقّت غير محروس → نُقل للأساس وحُرِس.
    "friday_db.py --record-loop": (["friday_db.py", "--record-loop", "--window-days", "7", "--interval", "120"], MT5),
    "friday_autopilot.py":        (["friday_autopilot.py"], MT5),
    "spike_rider.py":             (["spike_rider.py"], MT5),
    # العقل العميق ذاتي-التعلّم لكل العملات (قراءة فقط): ملفّ متعدّد-الفريمات + سبورة خصائص ظلّية بالتناوب.
    "deep_brain.py":              (["deep_brain.py"], MT5),
    # تعلّم من صفقات الديمو المنفّذة فعلاً (صافي التكلفة) → قواعد فيتو/تفضيل حقيقية لجسر القناعة.
    "real_trade_learner.py":      (["real_trade_learner.py"], MT5),
    # تعلّم بالندم (counterfactual): لكل صفقة سكالب MFE/MAE/الندم → «لو فعلنا كذا» يُحسّن التوقيت (قفل متحرّك).
    "regret_learner.py":          (["regret_learner.py"], MT5),
    # الحلقة المغلقة: ضابط ذاتيّ تشديد-فقط (بوّابة n≥200 + تحقّق-ذاتيّ) يكتب scalper_params.json. يحترم kill_switch.
    "self_tuner.py":              (["self_tuner.py"], MT5),
    # حارس الكتاب اليدويّ (magic 0، بإذن المستخدم): يُمسك الأحمر، يحرس/يقفل الأخضر. لا يفتح، لا يلمس خبراء خارجيّين.
    "manual_manager.py":          (["manual_manager.py"], MT5),
    # 🖐️ حرس اليد: حدود يد المستخدم — تنبيهات فقط، لا يمس الصفقات
    "hand_guard.py":              (["hand_guard.py"], MT5),
    # مُعمّق التعلّم من دخولك اليدويّ: يلتقط حالة SMC+العقل لحظة كل دخول ويبني بروفايل تقليدك (قراءة فقط).
    "manual_mimic.py":            (["manual_mimic.py"], MT5),
    # 🎖️ عدّاد إثبات الحساب الحقيقي (صادق): يُقيّم كل فرقة على صافي-التكلفة + حداثة + تعرّض عائم → أخضر/أصفر/أحمر.
    "real_account_gate.py":       (["real_account_gate.py", "--loop"], MT5),
    # 🔬 راصد القمّة + مُشرّح الانهيار (قراءة-فقط): يتتبّع أعلى رصيد، وعند الهبوط ≥4% يلتقط مَن نزف
    # (مُحقَّق لكل magic + عائم لكل مصدر) → peak_watch_crashes.jsonl. يجيب «كل ما نوصل 80% يهجّ معه».
    "peak_watch.py":              (["peak_watch.py"], MT5),
    # 🩺 momentum_harvester (TSM) عاد فوركس-فقط 2026-07-15 (أمر «كل العملات — ما نقتل نعالج»):
    # المعادن استُئصلت من GOLD_FOCUS (مصدر النزيف المُثبت)، وفوركس TSM كان موجباً. magic 20260630.
    "momentum_harvester.py":      (["momentum_harvester.py"], MT5),
    # 🧠 حلقة تعلّم الزخم (قراءة-فقط): تقيس أيّ الاتجاهات/الجلسات تدفع → momentum_edge.json؛ المحرّك يقرؤها ويتكيّف.
    "momentum_learn.py":          (["momentum_learn.py"], MT5),
    # 📈 لوحة الشارت الحيّ (:8016، قراءة-فقط): شموع + كل المستويات الهندسيّة (فيبو/جان/نجمة داوود/فراكتل/VWAP/POC) + مناطق الالتقاء، تحديث لحظيّ.
    "chart_server":               (["chart_server/server.py"], MT5),
    # 🚨 التنبيه الصاخب (قراءة-فقط): يرصد لوتك اليدويّ الكبير لحظة فتحه (خاصّةً بعد ربح = نمط الكارثة −$88k) → جوالك.
    "manual_lot_alert.py":        (["manual_lot_alert.py"], MT5),
    # 📺 وكيل محلّل اليوتيوب: يقرأ لوحة إشارات البثّ بصرياً (كشف لون) → Current Position + اتّفاق المؤطّرات (≥7)
    # → تنفيذ محروس (ديمو + lot_guard + أهداف التقاء). magic 20260631، وضع التأكيد افتراضيّاً (لا ينفّذ حتى auto).
    "youtube_analyst_agent.py":   (["youtube_analyst_agent.py"], MT5),
    # سكالب الذهب (أسلوب المستخدم: لوت صغير + TP سريع + رشّ) — اختبار أمامي محروس، magic 20260628.
    "gold_scalper.py":            (["gold_scalper.py"], MT5),
    # 🌊 PipFlow: محلّل-متداول لكل رمز عبر فريمات (M5/M15/H1) — خطّة فيبو ذهبية + SMC + مؤشرات،
    # سوق على التقاء قويّ متوافق، أوامر محدّدة عند المناطق (بلا وقف)، ركوب زخم، مضادّ-مارتنغيل. magic 20260629.
    "pipflow_core.py":            (["pipflow_core.py"], MT5),
    # 🌾 الحاصد الذاتيّ: يجني أرباح المحرّكات التي تترك الربح مفتوحاً (غرفة الحرب 20260618 + orb 20260616)
    # كما يفعل المستخدم بيده. لا يُغلق على خسارة، يتخطّى المُدار-ذاتياً، إغلاق-فقط، ديمو-فقط.
    "profit_harvester.py":        (["profit_harvester.py"], MT5),
    # 🎛️ المايسترو: حوكمة/تخصيص المحفظة — يخنق المحرّك النزّاف صافي-التكلفة (يكتب engine_governance.json
    # تقرؤه المحرّكات وتقيس لوتها) + خفض-مخاطرة محفظيّ عند السحب. يحكم محرّكاتنا فقط (لا يدويّ/خارجيّ).
    "portfolio_maestro.py":       (["portfolio_maestro.py"], MT5),
    # 🦅 مدير السرب: «الوكيل الذي يوظّف الوكلاء» — يُكثّر نحو المُثبت، يُشذّب الكارثيّ، ضمن سقف العمليّات.
    "swarm_director.py":          (["swarm_director.py"], MT5),
    # 🕸️ خريطة المنظومة الحيّة (رسم قوّة-موجّه على :8012، وصول جوّال عبر Tailscale) + وكيل مراقبة الفجوات/الانقطاع.
    "system_graph/server.py":     (["system_graph/server.py"], MT5),
    "system_graph/monitor.py":    (["system_graph/monitor.py"], MT5),
    # خلفية تطبيق سطح المكتب الموحّد (FastAPI) — تخدم الواجهة + REST/WS على :8770.
    "friday_desktop.backend":     (["-m", "uvicorn", "friday_desktop.backend.server:app", "--host", "127.0.0.1", "--port", "8770", "--log-level", "warning"], MT5),
    # جسر R-Confirm للجوال (FastAPI 0.0.0.0:8000، LAN). أُعيد بأمان 2026-06-28 بعد إصلاح سبب العطل:
    # (1) قفل مفرد (منفذ 8099) يمنع التكدّس، (2) اتصال MT5 في خيط خلفيّ غير-حاجب (لا يُعلّق uvicorn ولا
    # يخنق الطرفية). اتصال واحد مستقرّ كأيّ محرّك. ديمو-فقط + يحترم kill_switch + توكن للتنفيذ.
    "run_bridge.py":              (["run_bridge.py"], MT5 + r"\rbridge"),
    # غرفة الحرب: منفّذ بلا واجهة 24/7 (needle بـ --exec كي لا يطابق نافذة العرض --view).
    # النافذة (army_warroom.bat) تفتح بوضع --view = تتفرّج فقط، إغلاقها لا يوقف التداول. magic 20260618.
    # ✅ army_warroom أُعيد (طلب المستخدم 2026-07-02 «جميع العملات») — 35 رمزاً بحُرّاسٍ مُسلَّحة (2%/صفقة، 25% محفظة).
    "army_warroom.py --exec":     (["army_warroom.py", "--exec"], MT5),
    # 🫀 نبض السوق: قارئ شموع/شارتات حسّاس لكل العملات (قراءة فقط) + 🔔 حارس مستويات الذهب
    "market_pulse.py":            (["market_pulse.py"], MT5),
    # 🏁 سبّورة الديسك الحيّة لكل ماجيك (قراءة سوق فقط، لا تداول): صافي اليوم/3أيام + WR + عائم + حالة كل فرقة.
    "desk_scoreboard.py":         (["desk_scoreboard.py"], MT5),
    # (👑 gold_level_sentinel نُقل إلى رأس القائمة — الرابح يُطلَق أوّلاً)
    # 🌍 استنساخ الحارس الرابح على باقي العملات، ماجيك 20260709
    "level_sentinel_multi.py":    (["level_sentinel_multi.py"], MT5),
    # 🧮 مكتب الحسابات الكمّي: تحليلات موزونة لحظيّة (قراءة فقط، singleton)
    "quant_desk.py":              (["quant_desk.py"], MT5),
    # 🤖 محلّل Fable: قراءة سرديّة احترافيّة كل 20د + حارس أخبار (claude CLI، قراءة فقط)
    "llm_chart_analyst.py":       (["llm_chart_analyst.py"], MT5),
    # ⏰ إنذار الأخبار: T-10د + T-60ث (قراءة فقط) — يُغذّي إنذار الجوّال وجسر تقويم news_gene
    "news_alarm.py":              (["news_alarm.py"], MT5),
    # 🧹 بوّاب الأوامر: يُلغي المعلّقات اليتيمة/العتيقة/غير المنطقيّة (درس algory الـ42 أمراً)
    "order_janitor.py":           (["order_janitor.py"], MT5),
    # 🏛️ مجلس العقول المحليّ: كل موديل Ollama بدورٍ يتشاركون (محلّل/ناقد/حكم/عيون/مهندس) — $0 بلا اشتراك
    "ollama_council.py":          (["ollama_council.py"], MT5),
    # ⚖️ منفّذ المجلس: يُطبّق الاقتراحات الموافَق عليها من Claude فقط (قائمة أفعالٍ بيضاء)
    "council_executor.py":        (["council_executor.py"], MT5),
    # 🎯 قوسا الأخبار OCO (مواصفة المستخدم: Buy+Sell Stop حول السعر قبل الخبر، 0.1، إلغاء الآخر)
    "news_straddle.py":           (["news_straddle.py"], MT5),
    # 🔒 قفل الحقيقيّ: حساب غير تجريبيّ ⇒ kill_switch فوريّ (البوتات ديمو-فقط حتى تخضرّ البوّابة)
    "real_lock.py":               (["real_lock.py"], MT5),
    # 🪞 محاكي راضي (2026-07-02): قنص EMA50 مع الترند + ركوب موجة الخبر وبنكها — من يومه الحقيقي +161%.
    # بوابة توافق 7-عيون (M5/H1/SMC/BOS/POC/Stoch/المكتب) + فيتو «شريت بالقمة» مُدمج + حظر ليل/قبل-خبر. ديمو.
    "radhi_mimic.py":             (["radhi_mimic.py"], MT5),
    # 🧬 التطوّر الذاتيّ (2026-07-04): كل 6س يولّد 1400+ خوارزمية، يمحّصها walk-forward، يُرقّي الناجي
    # ورقيّاً فقط ويتقاعد الخاسر. لا يتداول ضجيجاً — الأرقام لا تكذب.
    "self_evolver.py":            (["self_evolver.py"], MT5),
    # 🧠 المخ الواحد (2026-07-04): يصهر كل العيون (نبض/مكتب/عميق/بنية/مجلس) في حكمٍ واحد لكل عملة كل ثانية.
    # قراءة ملفّات فقط (بلا MT5) ⇒ سريع. تنسيقٌ لا تنبّؤ. تقرؤه القمرة والمحرّك.
    "unified_brain.py":           (["unified_brain.py"], MT5),
    # 👁️ حارس المخ (2026-07-04): يراقب المخ الواحد، ويُنبّه الجوّال عند فرصة قناعة عالية (≥50%، اتّفاق ≥3).
    "brain_watch.py":             (["brain_watch.py"], MT5),
    # 🥷 R Core (2026-07-06، ماجيك 20260706): ذهب-فقط — صهر مستويات الحارس + انضباط المكتب + فيتوهات راضي.
    # مخاطرة مكتسبة بالسلّم (ladder-earned). ديمو فقط.
    "brain_trader.py":            (["brain_trader.py"], MT5),
    # 🏛️ مجلس الـ90 وكيلاً (2026-07-06): يكتشف كل agents/agent_*.py، يبني ctx لكل رمز (فريمات mt5 + smc نبض)،
    # يصهر أصوات الـ90 في إجماعٍ موزون لكل عملة ⇒ agent_council.json (عينٌ سادسة في المخ). يتعلّم من إغلاقات
    # منفّذ المخ (20260704) عبر gene_registry. تنسيقٌ لا حافّة (درس التجميع). ديمو، مقيس.
    "agent_council.py":           (["agent_council.py"], MT5),
    # 🏛️🎯 قنّاص المجلس (20260707) — أُعدم نهائياً بأمر المستخدم 2026-05-30
    # ("امسحه عن الوجود لا عاد تخليه يشتغل ابداً") — خاسر بدلالة t=-2.13.
    # الملف مؤرشف في _retired/. لا تُعِده أبداً.
    # 🖥️ بوّابة R Trader الموحّدة (:8020): reverse-proxy يجمع القمرة (:8016) + الخريطة (:8012) + خلفية
    # FRIDAY (:8770) خلف منفذٍ واحد (نفق واحد يكشف كل شيء). واجهة توحيد وقراءة — لا مسار أوامر جديد.
    "r_trader/gateway.py":        (["r_trader/gateway.py"], MT5),
    # 🚌 ناقل العقل (2026-07-08): يجعل تبادل المعلومات بين المحرّكات صريحاً وحيّاً — تيّار رسائل مُهيكلة
    # مشتقّة من أحداثٍ حقيقيّة (تنبيه/إجماع/تنفيذ/أداء/حوكمة/صهر) + معايرة صادقة OOS. قراءة ملفّات فقط، لا MT5، لا تداول.
    "brain_bus.py":               (["brain_bus.py"], MT5),
    # 🧭📏 المتعلّم-الفوقيّ الصادق (2026-07-08، لا ماجيك — لا يتاجر): يتعلّم من كلّ صفقةٍ مُغلقة لماجيكاتنا
    # ويقيس بصدقٍ خارج العيّنة هل يتحسّن (verdict: learning/flat/no_edge). قياسٌ لا وعد. ديمو فقط.
    "meta_learner.py":            (["meta_learner.py"], MT5),
    # 👁️🫀 عيون وإحساس (2026-07-08، لا ماجيك — لا يتاجر): إحساسٌ سوقيّ متّصل [0,1] لكل رمز (السبريد
    # يختار اللحظة/تقلّب/زخم/طاقة) + ثقةٌ من نتائج R المُغلقة الحقيقيّة (تصعد بالأهداف تهبط بالوقف) ⇒
    # مُعدِّل قناعة/حجم ناعمٌ محدود [0.5,1.3]. قراءة فقط، لا مسار أوامر، لا يمسّ فيتو/سقف/أرضيّة/قفل.
    "adaptive_sense.py":          (["adaptive_sense.py"], MT5),
}

# 🎯 وضع التركيز: إن وُجد focus_youtube.flag يحرس مجموعةً رشيقة فقط. 2026-07-02 (طلب المستخدم «جميع العملات»):
# وُسّعت المجموعة لأسطولٍ رشيقٍ متعدّد العملات (المنفّذان + الحُرّاس + النبض) — كل العملات بلا عاصفة الـ50 عمليّة.
_FOCUS_FLAG = os.path.join(MT5, "focus_youtube.flag")
# ⚔️ خطة الحسم 2026-07-02 (أمر المستخدم «الخسائر أكبر من الأرباح — خطة كاملة ونفّذها»):
# تدقيق 90 يوماً: كل محرّكات الدخول سالبة (بوتات ≈ −$2,071 عبر 6000+ صفقة = نزيف سبريد بلا حافّة).
# ⇒ محرّك دخول واحد فقط (radhi_mimic = استراتيجية المستخدم الثمانية) + قوسا الأخبار (تجربة محدودة تُحاسَب
# بعد 5 أحداث). أُطفئ: youtube (اشترى قمّة −$95 اليوم)، multi_trader، غرفة الحرب، جينات التداول، news_gene.
# العيون والحرّاس باقون كلّهم. كل «متعلّم» يُحاسَب أسبوعياً بالأرقام أو يُطفأ.
_FOCUS_KEEP = {"master_floor.py", "peak_watch.py",
               "manual_manager.py", "manual_lot_alert.py", "chart_server",
               "hand_guard.py",                                          # 🖐️ حرس اليد (تنبيهات فقط)
               "manual_feature_recorder.py", "hand_miner.py",            # 🖐️⛏️ التقاط بصمة اليد لحظياً + تعدين لماذا تربح OOS
               "conflict_resolver.py",                                   # 🧩 المُعالِج الذاتيّ لتعارض القرارات
               "tradingview_bridge.py",                                  # 🌉 جسر TradingView
               "tv_tunnel_keeper.py",                                    # 🚇 حارس نفق TradingView
               "knowledge_grower.py",                                    # 🌱 منمّي المعرفة (تتكاثر بالتجربة)
               "edge_scanner.py",                                        # 🔬 ماسح الحافّة لكل رمز/فريم
               "trade_autopsy.py",                                       # 🔎 مشرّح الصفقات (دخول أم خروج)
               "market_pulse.py", "gold_level_sentinel.py",              # 🫀 النبض + الحارس (تنبيهات)
               # 🌍 كتيبة كل العملات — أُعيدت 2026-07-15 (أمر المستخدم «ندخل جميع العملات دون استثناء
               # — ما نقتل نعالج»): النازف يعالجه edge_governor باستراحة مؤقتة، لا يُقصى من الحراسة.
               "level_sentinel_multi.py",                                # 🌍 حارس المستويات متعدد العملات (20260709)
               "multi_trader.py",                                        # 🌍 المشروع على جميع العملات
               "army_warroom.py --exec",                                 # ⚔️ غرفة الحرب — 35 رمزاً (20260618)
               "orb_trader.py",                                          # 🎯 اختراق الافتتاح — مؤشرات/ذهب (20260616)
               "pipflow_core.py",                                        # 🌊 PipFlow متعدد الفريمات (20260629)
               "gold_scalper.py",                                        # 🥇 سكالب الذهب (20260628)
               "momentum_harvester.py",                                  # 🩺 TSM فوركس-فقط بعد العلاج (20260630)
               "desk_scoreboard.py",                                     # 🏁 سبّورة الديسك لكل ماجيك (قراءة فقط)
               "quant_desk.py", "llm_chart_analyst.py",                  # 🧮 المكتب + 🤖 محلّل Fable
               "news_alarm.py", "news_straddle.py",                      # ⏰ الإنذار + 🎯 القوسان (تجربة مُقاسة)
               "market_sweeper.py", "boundary_hunter.py",                # 🌍🗡️ التعلّم الشرس (كل الرموز + كل اللحظات)
               "r_hybrid_pilot.py", "boundary_pilot.py",                 # 🧪⚔️ منفّذا العيّنات (20260713/20260714)
               "learning_pulse.py", "r_native.auto_ga_daemon",           # 🎓🧬 المُرقّي + حملات الجينات
               "runtime.unified_trader",                                 # 🧠 الموحّد 99782 (رابحنا المتعدّد!) — كان خارج التركيز فلا يُحيا (علّة 2026-07-14)
               "brain_server.py",                                        # 🧠 العقل الوحيد 5055 (r_native.brain_server أُزيل — توحيد #1)
               "friday_v3.algory.r_executor",                            # 🎯 المنفّذ الموحّد (20260605) — تحت الحراسة حتى في وضع التركيز
               "nr7_prover.py",                                          # 🔬 مُثبِت NR7 الأماميّ (111111) — الحافّة الناجية
               "edge_governor.py",                                       # 🚦 حاكم الحافّة — يُقاعد النازف تلقائياً (لا يتاجر)
               "fabio_orb.py",                                           # 🎯 نموذج Fabio ORB (20260716) — USTECm، ديمو، execute=false افتراضياً

               "real_lock.py",                                            # 🔒 قفل الحقيقيّ
               "order_janitor.py", "ollama_council.py", "council_executor.py",  # 🧹 البوّاب + 🏛️ المجلس + ⚖️ منفّذه
               "system_graph/server.py",                                 # 🕸️ خريطة المنظومة الحيّة :8012
               "profit_harvester.py", "portfolio_maestro.py", "self_tuner.py",  # 👔 المدراء
               "risk_manager.py", "coordinator.py",                       # إدارة المخاطر/التنسيق
               "radhi_mimic.py", "self_evolver.py", "unified_brain.py",    # 🪞 المحرّك + 🧬 التطوّر + 🧠 المخ الواحد
               "brain_watch.py", "brain_trader.py",                       # 👁️ حارس المخ + 🌍 منفّذه متعدّد العملات
               "agent_council.py",                                        # 🏛️ مجلس الـ90 وكيلاً (عينٌ سادسة)
               "youtube_analyst_agent.py",                                # 📺 وكيل اليوتيوب (أُعيد بطلب المستخدم 2026-07-07، ماجيك 20260631)
               "meta_learner.py",                                         # 🧭📏 المتعلّم-الفوقيّ الصادق (قياسٌ ذاتيّ — لا يتاجر)
               "brain_bus.py",                                            # 🚌 ناقل العقل (تبادل معلومات صريح — قراءة فقط)
               "adaptive_sense.py",                                       # 👁️🫀 عيون وإحساس + ثقة من النتائج (قراءة فقط — لا يتاجر)
               "r_trader/gateway.py"}                                     # 🖥️ بوّابة R Trader الموحّدة :8020
if os.path.exists(_FOCUS_FLAG):
    ENGINES = {k: v for k, v in ENGINES.items() if k in _FOCUS_KEEP}


def _alive() -> dict:
    """needle -> count of live python processes matching it (excluding shell snapshots/this scan)."""
    counts = {k: 0 for k in ENGINES}
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            if "python" not in name:
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "shell-snapshot" in cl or "watchdog_guard" in cl:
                continue
            for k in ENGINES:
                if k in cl:
                    counts[k] += 1
        except Exception:
            pass
    return counts


# 💓 خريطة نبض القلب: محرّك ← (ملفّ نبضه، أقصى قِدَم بالثواني). العمليّة الحيّة لكن ملفّها بائتٌ = حلقة
# معلّقة (ندبة IP/MT5) ⇒ نقتلها لتُعاد نظيفةً. عتبات سخيّة تجنّباً لشفاءٍ كاذب على المحرّكات البطيئة.
_RN_DIR = os.path.join(MT5, "data", "r_native")
HEARTBEAT = {
    # 🧠 2026-07-14: الموحّد (99782 — رابحنا المتعدّد) علق 6.5س بعد تعليق الجهاز بلا حكم —
    # عمليّة حيّة وملفّ بائت. مساره مطلق (join يقبله). عتبة 900ث لإقلاع Keras البطيء.
    "runtime.unified_trader": (os.path.join(MT5, "r_native_v2", "data", "son_status.json"), 900),
    "agent_council.py":    ("agent_council.json", 120),      # يكتب كل ~2ث
    "market_pulse.py":     ("market_pulse.json", 90),        # 4ث
    "desk_scoreboard.py":  ("desk_scoreboard.json", 120),    # 🏁 30ث دورة، عتبة سخيّة
    "unified_brain.py":    ("unified_brain.json", 90),       # 1ث
    "brain_trader.py":     ("brain_trader_status.json", 120),
    "radhi_mimic.py":      ("radhi_mimic_status.json", 120),
    "quant_desk.py":       ("quant_desk.json", 150),
    "gold_level_sentinel.py": ("gold_sentinel_status.json", 180),  # فاصل أبطأ
    "level_sentinel_multi.py": ("level_sentinel_multi_status.json", 300),
    "peak_watch.py":       ("peak_watch_state.json", 600),
    "real_lock.py":        ("real_lock_status.json", 120),
    "hand_guard.py":       ("hand_guard_status.json", 120),   # 🖐️ حرس اليد
    "meta_learner.py":     ("meta_learner_status.json", 120),  # 🧭📏 المتعلّم-الفوقيّ (حلقة ~30ث)
    "brain_bus.py":        ("brain_bus.json", 120),            # 🚌 ناقل العقل (حلقة ~2ث)
    "adaptive_sense.py":   ("market_sense.json", 120),         # 👁️🫀 عيون وإحساس (حلقة ~2.5ث)
    "hand_miner.py":       ("hand_edge.json", 4200),           # 🖐️⛏️ معدِّن اليد (حلقة ساعة، عتبة سخيّة)
    "conflict_resolver.py": ("conflict_resolver_status.json", 60),  # 🧩 المُعالِج (حلقة 5ث)
    "tradingview_bridge.py": ("tradingview_bridge_status.json", 90),  # 🌉 جسر TradingView (حلقة 30ث)
    "tv_tunnel_keeper.py":   ("tv_tunnel_status.json", 120),          # 🚇 نفق TradingView (نبض 30ث)
    "market_sweeper.py":     ("market_sweeper_status.json", 180),        # 🌍 نبض 30ث
    "r_hybrid_pilot.py":     ("r_hybrid_pilot_status.json", 120),        # 🧪 نبض 2ث
    "boundary_hunter.py":    ("boundary_hunter_status.json", 180),       # 🗡️ نبض 20ث
    "boundary_pilot.py":     ("boundary_pilot_status.json", 120),        # ⚔️ نبض 10ث
    "learning_pulse.py":     ("learning_pulse.json", 5400),              # 🎓 نبضة كل ساعة (سماحية 90د)
    "r_native.auto_ga_daemon": ("auto_ga_state.json", 2700),             # 🧬 تحديث كل 15د (سماحية 45د)
    "knowledge_grower.py":  ("knowledge_grower_status.json", 900),  # 🌱 منمّي المعرفة (حلقة 10د، عتبة سخيّة)
    "edge_scanner.py":      ("edge_scanner_status.json", 2100),     # 🔬 ماسح الحافّة (حلقة 30د، عتبة سخيّة)
    "trade_autopsy.py":     ("autopsy_summary.json", 120),          # 🔎 مشرّح الصفقات (حلقة 30ث)
    "edge_governor.py":     ("edge_governor_status.json", 300),      # 🚦 حاكم الحافّة (حلقة 120ث، عتبة سخيّة)
    "fabio_orb.py":         ("fabio_orb_status.json", 120),          # 🎯 نموذج Fabio ORB (حلقة 15ث)
}


def _kill_needle(needle: str) -> int:
    """يقتل كل عمليّات بايثون التي يطابق سطر أوامرها needle (عدا الوصيّ نفسه). يرجع العدد المقتول."""
    n = 0
    for p in psutil.process_iter(["name", "cmdline", "pid"]):
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "watchdog_guard" in cl or "shell-snapshot" in cl:
                continue
            if needle in cl:
                p.kill(); n += 1
        except Exception:
            pass
    return n


def _hung(counts: dict) -> list:
    """محرّكات حيّة (count>0) لكن ملفّ نبضها بائتٌ فوق العتبة ⇒ معلّقة (تحتاج قتلاً ثمّ إعادةً)."""
    out = []
    now = time.time()
    for needle, (fname, max_age) in HEARTBEAT.items():
        if counts.get(needle, 0) <= 0:
            continue                                # ميّتة أصلاً — تتكفّل بها حلقة dead
        try:
            age = now - os.path.getmtime(os.path.join(_RN_DIR, fname))
            if age > max_age:
                out.append((needle, int(age)))
        except Exception:
            pass                                    # لا ملفّ بعد ⇒ لا حكم (قد تكون تُقلع)
    return out


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    restarts: dict = {}
    print("[GUARD] watching", len(ENGINES), "engines — never stop", flush=True)
    while True:
        try:
            counts = _alive()
            # 💓 شفاء ذاتيّ: اقتل المعلّقة (حيّة لكن نبضها بائت) — تُعاد نظيفةً في نفس الدورة عبر منطق dead
            heals = {}
            for needle, age in _hung(counts):
                killed = _kill_needle(needle)
                if killed:
                    counts[needle] = 0                      # اعتبرها ميّتة ⇒ تُعاد أدناه
                    heals[needle] = age
                    print(f"[GUARD] 💓 healed HUNG {needle} (نبض بائت {age}ث، قُتل {killed})", flush=True)
            dead = [k for k, c in counts.items() if c == 0]
            for k in dead:
                args, cwd = ENGINES[k]
                try:
                    subprocess.Popen([PYW] + args, cwd=cwd, env=env, creationflags=FLAGS)
                    restarts[k] = restarts.get(k, 0) + 1
                    print(f"[GUARD] 🔄 respawned {k} (total restarts {restarts[k]})", flush=True)
                except Exception as e:
                    print(f"[GUARD] respawn {k} failed: {e}", flush=True)
            STATUS.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({
                "ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
                "alive": {k: c for k, c in counts.items()},
                "n_alive": sum(1 for c in counts.values() if c > 0),
                "n_total": len(ENGINES), "restarts": restarts,
                "heals": heals,                              # 💓 المعلّقة التي شُفيت هذه الدورة
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, STATUS)
        except Exception as e:
            print(f"[GUARD] err {e}", flush=True)
        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
