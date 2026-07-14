# UNIFIED RUNTIME — نظام تشغيل موحّد لـ R-Native
### One Supervisor · One Brain (:5055) · One Executor (magic 20260605)

> **الحالة:** وثيقة تصميم (DESIGN). لا تغيّر الكود الحيّ. الملف المرافق
> `C:\Users\Radhi\MT5\unified_launcher.py` هيكل غير-هدّام (`--dry-run` افتراضيّاً)
> يقرأ ما يعمل *قبل* أن يشغّل أي شيء، فلا يُضاعف مشرفاً ولا دماغاً.
>
> **Status:** DESIGN doc. Does NOT touch live trading code. The companion
> `unified_launcher.py` is a non-destructive skeleton (`--dry-run` default TRUE)
> that inspects what is already running *before* starting anything, so it never
> double-spawns a second supervisor or a second brain.

---

## 1. المشكلة — التشتّت الحاليّ / The current fragmentation

اليوم يوجد أكثر من "سلطة لا تتوقّف" واحدة تتنازع على نفس ناقل الملفّات
`data\r_native\*.json`، ونفس المنفذ `:5055`، ونفس الماجيك `20260605`:

Today there is **more than one "never-stop authority"** competing over the same
file bus `data\r_native\*.json`, the same port `:5055`, and the same magic
`20260605`:

| # | التشتّت / Fragmentation | الأثر / Impact |
|---|--------------------------|----------------|
| A | **مشرفان** — `watchdog_guard.py` (يحرس ~60 محرّك جذر) مقابل `dist\RNative` (RNativeLauncher→RNativeWorker) + `r_native\launcher.py` / `embedded_services.py` | كلاهما يكتب نفس ناقل JSON → منتجو حوكمة مزدوجون، لوت مُضاعَف، تاريخ لا يُميَّز |
| B | **دماغان على :5055** — `brain_server.py` (الجذر) مقابل `r_native.brain_server` (كلاهما مسجّل في `watchdog_guard.py` سطرا 36 و38) | تصادم منفذ `WSAEADDRINUSE`، الخاسر يموت في `embedded_brain.err`، وأحياناً `/api/r/*` تُرجِع 404 (انقسام الدماغ) |
| C | **سياسة executor متناقضة** — `20260605` **معطّل** في `r_native\launcher.py` (SERVICES) لكنه **حيّ** في `start_r.ps1` | نُسختا executor محتملتان على نفس الماجيك أو صفر executor |
| D | **سبع نقاط دخول** — `start_r.ps1`, `start_brain.ps1`, `RNative.bat`, `RNative_launcher.bat`, `R_TRADER.bat`, `START_FLEET.bat` (+ frozen) | تصادمات منافذ، سياسات متناقضة، لا مصدر حقيقة واحد للإقلاع |
| E | **بوّابة gate ثلاثيّة** — `trade_gate.py` في `friday_v3\`, `r_native\`, `r-native-pipflow\` | خطر انقسام الدماغ في البناء المجمّد (frozen split-brain) |
| F | **مخرجات حرّاس يتيمة** — `correlation_blocks.json`, `news_blocked_symbols.json`, `kill_switch.json` تُكتب لكن لا يقرؤها `r_executor` | طبقة الأمان المنسّقة (curated safety) لا تحمي الماجيك الحيّ فعليّاً |
| G | **مفتاح إيقاف منقسم** — `kill_switch.txt` (يُحترَم) مقابل `kill_switch.json` (يُكتَب من `drawdown_recovery` ويُتجاهَل) | الإيقاف الطارئ عند DD_LEVEL_4 يتيم |
| H | **تصادم كوكبيت :8020** — `r_trader\app.py` و `watchdog r_trader\gateway.py` كلاهما يطلب :8020 | أحدهما يفشل بالربط |

> **درس الذاكرة 2026-07-14 (frozen split-brain):** الووركر الحيّ يعمل من
> `dist\RNative\_internal` بينما التعديلات تصل الى المصدر. إن أطلق watchdog
> `brain_server.py` من المصدر بينما دماغ مجمّد ما زال يمسك :5055، فإن
> `embedded_services` يتبنّى الخطأ بصمت و `/api/r/*` تُرجِع 404. **يجب التأكّد
> من مالك المنفذ الوحيد قبل وبعد كل تغيير.**

---

## 2. الهدف الموحّد / The unified target

```
                    START_UNIFIED.bat
                          │
                          ▼
   .venv\Scripts\pythonw.exe watchdog_guard.py     ← المشرف الوحيد الذي يطلقه إنسان
   (SINGLE never-stop supervisor of record)          the only process a human launches
                          │
         ┌────────────────┼───────────────────────────────┐
         ▼                ▼                                 ▼
   brain_server.py   friday_v3.algory.r_executor    ~60 root ENGINES
   (ONE brain :5055) (ONE executor magic 20260605)  (sentinels, sweeper,
         │            57322 LIVE mutex, PAPER default   brain_bus, council,
         │                                              learners, feeds...)
         ├── mt5.initialize() مرّة واحدة عند الاستيراد
         ├── _updater thread
         ├── continuous_evolution
         └── orchestrator.start_all()  ← الوكلاء المنسّقون داخل-العملية (in-process threads)
             (5 core + guards + intelligence + signal advisors)
```

**القواعد الثلاث الثابتة / Three invariants:**

1. **مشرف واحد** — `watchdog_guard.py` فقط. يُتقاعَد `dist\RNative` والـ
   `r_native.launcher` / `embedded_services` كمشرفين منافسين.
2. **دماغ واحد على :5055** — `brain_server.py` (الجذر) فقط. تُزال إبرة
   `r_native.brain_server` من watchdog.
3. **executor واحد على 20260605** — `friday_v3\algory\r_executor.py` فقط، محميّ
   بقفل `127.0.0.1:57322` (LIVE mutex)، **PAPER افتراضيّاً**، و`--live` فقط
   بموافقة DEMO صريحة.

**جناح الوكلاء المنسّق ليس عملية منفصلة** — يعمل داخل الدماغ الواحد عبر
`r_native.agents.orchestrator.start_all()` (thread-per-agent).
The curated agent suite is **NOT** a separate process — it runs in-process
inside the single brain.

---

## 3. جدول المكوّنات / Component decision table

`keep` أبقِ · `deprecate` تقاعَد · `merge` ادمج · `wire-in` صِل

| المكوّن / Component | المسار / Path | القرار / Decision | السبب / Why |
|---|---|---|---|
| brain_server (root) | `brain_server.py` | **keep** | الدماغ الموحّد الوحيد على :5055؛ ما يطلقه الووركر المجمّد فعليّاً وما يثبّته `r_executor` (localhost:5055) ويستضيف `/api/r/trade_gate` |
| r_native.brain_server | `r_native\brain_server.py` | **deprecate** | الدماغ الثاني (إبرة watchdog سطر 36) يتنازع على نفس المنفذ = جوهر انقسام الدماغ. أزل الإبرة |
| r_executor (20260605) | `friday_v3\algory\r_executor.py` | **keep** | الـ executor الحيّ الوحيد، قفل 57322، PAPER افتراضيّ. لا تلمس دورة حلقته ولا رابط الـ gate |
| trade_gate | `friday_v3\algory\trade_gate.py` | **keep** | البوّابة الاستشاريّة المرجعيّة؛ نُسخ `r_native\` و`pipflow` مكرّرة. البناء يحزم هذه النسخة |
| gate libs | `friday_v3\algory\{r_levels,indicator_matrix,r_learning,r_multi_symbol,strategy_mirror}.py` | **keep** | مكتبات استيراد فقط (بلا عملية)؛ نسخ friday_v3 هي القانونيّة |
| decision_log | `r_native\decision_log.py` | **keep** | يوميّة صفقات لكل genome يستوردها executor (fail-soft)؛ احذف نسخ v2/runtime/shared/pipflow |
| watchdog_guard | `watchdog_guard.py` | **keep** | يُرقّى الى المشرف/نقطة الدخول الوحيدة. ادمج إبرتَي الدماغ في واحدة وأضِف إبرة executor |
| agents orchestrator | `r_native\agents\orchestrator.py` (+`base.py`,`llm.py`) | **keep** | منسّق الوكلاء داخل-العملية الحقيقيّ؛ يطلقه brain_server عند الإقلاع. هذا هو بيت الجناح الموحّد |
| curated agents | `r_native\agents\*` (guards+intel+advisors) | **wire-in** | تعمل كـ threads لكن مخرجاتها يتيمة؛ صِل executor ليقرأ `correlation_blocks.json` / `news_blocked_symbols.json` / `kill_switch.json` (fail-open) |
| agent_council | `agent_council.py` + `agents\agent_*.py` (90 fn) | **keep** | محرّك الإجماع الذي يطلقه watchdog يغذّي brain_trader (veto-only) |
| dist/RNative launcher | `dist\RNative\*` + `r_native\launcher_module\*` | **deprecate** | سلطة لا-تتوقّف منافسة على نفس الناقل/المنفذ/executor. تُبقى فقط كنافذة UI اختياريّة يطلقها watchdog |
| r_native launcher SERVICES | `r_native\launcher.py` + `embedded_services.py` | **merge** | ترتيب إقلاعه brain→executor→daemons جيّد؛ ادمجه في watchdog pre-flight ثم تقاعَده كمشرف مستقل |
| entry-point scripts | `start_r.ps1`, `start_brain.ps1`, `RNative*.bat`, `R_TRADER.bat`, `START_FLEET.bat` | **deprecate** | سبع نقاط متداخلة = تصادمات وتناقض سياسة. استبدلها بـ `START_UNIFIED.bat` واحد |
| legacy orchestrator stack | `agents\orchestrator.py`, `unified_orchestrator.py`, `pluto_brain.py`, `fast_autopilot_loop.py` | **deprecate** | مكدّس قديم يتيم لا يطلقه watchdog؛ أرشِفه لتفادي الالتباس مع سجلّ threads الحيّ |
| INSTALL one-command | `INSTALL.md` (`python -m r_native.app`) | **merge** | وثيقة تفترض دماغاً واحداً؛ وجّهها الى `START_UNIFIED.bat` |
| cockpit :8020 | `r_trader\app.py` + `r_trader\gateway.py` | **merge** | تطبيقان يطلبان :8020؛ أبقِ gateway وانقل app.py الى منفذ مغاير |
| friday.db | `friday.db` + `friday_db.py --record-loop` | **keep** | مصدر حقيقة SQLite للصفقات المغلقة (خارج ناقل JSON) — جوهر القياس-قبل-الثقة |

---

## 4. نقطة الدخول الوحيدة / The single entry point

```bat
:: C:\Users\Radhi\MT5\START_UNIFIED.bat  (الوحيد الذي يطلقه إنسان)
@echo off
cd /d C:\Users\Radhi\MT5
:: 1) حارس مستوى الذهب (كما هو حيّ اليوم)
start "" .venv\Scripts\pythonw.exe gold_level_sentinel.py
:: 2) المشرف الوحيد
start "" .venv\Scripts\pythonw.exe watchdog_guard.py
```

> Step 1 من الهجرة هو **إعادة تسمية no-op** لسلوك `START_FLEET` الحاليّ — لا تغيير
> وظيفيّ. Step-1 is a no-op rename of the current `START_FLEET` behavior.

---

## 5. تسلسل الإقلاع / Boot sequence (single supervisor)

0. **حارس نسخة واحدة** — `engine_lock.claim('watchdog_guard')`؛ إن كان مشرف ثانٍ
   أو `dist\RNative` قيد التشغيل → اخرج بصمت (لا مشرفان على الناقل المشترك).
1. **Pre-flight** — تأكّد من وجود أدلّة `data\r_native` الفرعيّة
   (`symbol_configs`, `hall_of_fame\by_symbol`, `decision_log`)؛ **أكّد DEMO**
   (اقرأ اسم خادم الطرفيّة، ارفض تسليح أي executor إن لم يحوِ `Trial`/`Demo`)؛
   تحقّق أن `kill_switch.txt` هو ملف الإيقاف الوحيد المُحترَم.
2. **دماغ واحد :5055** — أطلق `brain_server.py` فقط. عند الاستيراد يفعل
   `mt5.initialize()` مرّة ويبدأ `_updater`؛ تحت `__main__` (بلا `DASHBOARD_ONLY`)
   يسلّح `continuous_evolution` + `orchestrator.start_all()`. انتظر حتى يستجيب
   `GET http://localhost:5055/api/r/executor` قبل المتابعة.
3. **Gate** — الدماغ يخدم `/api/r/trade_gate` (`trade_gate.evaluate_gate` فوق
   اللقطة: account+regime+multi_tf+chart+matrix+levels+mirror+learning). نسخة
   البوّابة الوحيدة العاملة (friday_v3).
4. **Executor واحد (20260605)** — أطلق `friday_v3.algory.r_executor` بقفل
   `127.0.0.1:57322`، PAPER افتراضيّاً (`--live` فقط بموافقة DEMO). يستطلع :5055
   ويدير المراكز على إيقاع fast/slow/save.
5. **منتجو الحوكمة** — `portfolio_maestro.py`, `swarm_director.py`,
   `desk_scoreboard.py` → يطوون الأداء الحيّ في `engine_governance.json`؛
   الـ executors يقرؤون `gov_mult()`/`is_paused()`.
6. **الحاجز الكارثيّ** — `master_floor.py` (أرضيّة حقوق → `kill_switch.txt`)،
   الإيقاف الصلب الوحيد، خارج مسار المضاعفات.
7. **أسطول محرّكات الجذر** — watchdog يطلق باقي روستر ENGINES بلا نوافذ
   (sentinels, sweeper, brain_bus mirror, agent_council, unified_brain,
   learners, feeds)، مع تقليم `focus_youtube.flag`.
8. **إشراف دائم** — حلقة 60ث: `count==0` أعِد الإطلاق + كشف التعليق بعمر ملف
   الحالة (mtime) + اكتب `watchdog_status.json`.

---

## 6. حلّ ازدواج :5055 / Resolving the :5055 double-bind

```
قبل / BEFORE:
  watchdog_guard.py سطر 36 → r_native.brain_server ──┐
  watchdog_guard.py سطر 38 → brain_server.py (root) ──┴──► كلاهما يربط :5055
                                                          الخاسر → embedded_brain.err

بعد / AFTER:
  watchdog_guard.py → brain_server.py (root) فقط ──────► رابط واحد على :5055
  (إبرة r_native.brain_server مُعلَّقة/محذوفة)
```

**التسلسل الآمن (Step 2 في الهجرة):**
1. شغّل تدقيق Step-0: من يملك :5055؟ PID واحد أم اثنان؟
2. علّق إبرة `r_native.brain_server` فقط، أبقِ `brain_server.py` الجذر.
3. أكّد أن :5055 ما زال يملكه PID واحد بالضبط و `/api/r/executor` +
   `/api/r/trade_gate` يُرجعان 200.
4. **تراجع فوريّ** إن كان المسار المجمّد هو الرابط الحقيقيّ.

`embedded_services` يتبنّى-إن-وُجد، لذا الإبقاء على الإثنين يضمن أن الخاسر يموت
بصمت. إزالة الإبرة تُحقّق رابطاً واحداً.

---

## 7. المخاطر / Risks

1. **Frozen-vs-source split-brain** (ذاكرة 2026-07-14) — إن أطلق watchdog دماغ
   المصدر بينما دماغ مجمّد يمسك :5055، `/api/r/*` تُرجِع 404. أكّد رابطاً واحداً
   قبل وبعد كل تغيير.
2. **mt5.initialize() عند الاستيراد** — وكل حارس/وكيل يفتح handle خاصّاً به = خطر
   IPC-flood/wedge تاريخيّ. التوحيد يجب ألّا يزيد عدد مُستدعي `mt5.initialize()`
   المتزامنين ولا يفعل mass-kill (Exness يخنق عند القتل الجماعيّ).
3. **إزالة إبرة `r_native.brain_server`** بينما المسار المجمّد يتوقّعها قد يترك
   الأسطول بلا دماغ إن كان الخطأ هو الرابط الحيّ — تسلسل التغيير مع فحص مالك
   المنفذ المُتحقّق.
4. **تقاعُد `dist\RNative`** يخاطر بإزالة المشرف الحيّ حاليّاً — انقل الإشراف الى
   watchdog وتحقّق من تكافؤ heartbeat/RSS-restart قبل التقاعد.
5. **وصل ملفّات الحرّاس اليتيمة** (`correlation_blocks.json`,
   `news_blocked_symbols.json`, `kill_switch.json`) يغيّر سلوك بوّابة الـ executor
   الحيّ — قد يمنع الدخول فجأة. اشحنه خلف علم افتراضيّ-مطفأ وقِس قبل أن تثق.
6. **مشرفان يتعايشان لحظيّاً أثناء الهجرة** = منتجو حوكمة مزدوجون + executors
   مزدوجون على 20260605 (لوت مركّب). `engine_lock` + قفل 57322 يخفّفان لكن يجب
   التحقّق حيّاً.
7. **روستر watchdog** قاموس مسطّح بمطابقة needle-substring — تصادمات crc32/منفذ
   تاريخيّة سبّبت موتاً صامتاً للتوائم. إضافة executor + إزالة إبر الدماغ يجب أن
   تُبقي كل needle فريدة.
8. **DEMO-guard** مفروض في بعض المحرّكات فقط (profit_harvester, sentinels, pilot)
   لا في maestro/risk_manager/manual_manager — على حساب حقيقيّ ستتصرّف. الـ
   pre-flight الموحّد يضيف تأكيد DEMO على مستوى الأسطول.

---

## 8. خطوات الهجرة الآمنة والتدريجيّة / Safe incremental migration

كل خطوة قابلة للعكس بشكل مستقلّ. بعد كل خطوة أعِد تدقيق Step-0 وأكّد: دماغ واحد
على :5055، executor واحد على 20260605، مشرف واحد، سلوك PnL حيّ غير متغيّر. أي
تراجُع → اعكس تلك الخطوة وحدها.

| الخطوة | الوصف | التحقّق |
|---|---|---|
| **0** | تدقيق (بلا تغيير كود): اطبع مالك :5055، عدد المشرفين الأحياء، PID مالك قفل 57322. سجّل الأساس. | أساس مُسجَّل |
| **1** | أنشئ `START_UNIFIED.bat` يفعل ما هو حيّ فقط (sentinel ثم watchdog) — إعادة تسمية no-op لـ START_FLEET. | الأسطول مطابق للأساس جلسة كاملة |
| **2** | في watchdog علّق إبرة `r_native.brain_server`، أبقِ الجذر. | :5055 يملكه PID واحد؛ `/api/r/executor`+`/trade_gate` = 200 |
| **3** | أضِف `friday_v3.algory.r_executor` كإبرة watchdog صريحة (PAPER). لا تغيّر الفاصل ولا رابط الـ gate. | قفل 57322 يُبقي executor واحداً |
| **4** | تقاعَد المشرف الثاني — امنع `dist\RNative`/`embedded_services` من الإطلاق بأي .bat. | `engine_governance.json` منتِج واحد (mtime/PID) |
| **5** | أرشِف نقاط الدخول (`start_r.ps1`, `start_brain.ps1`, `RNative*.bat`, `R_TRADER.bat`) الى `scripts\_retired\`؛ حدّث INSTALL.md. | doc/entry-point فقط، بلا تغيير وقت-تشغيل |
| **6** | صِل مخرجات الأمان اليتيمة خلف أعلام افتراضيّة-مطفأة (`R_HONOR_NEWS_BLOCK`, `R_HONOR_CORR_BLOCK`, `R_HONOR_DD_KILLJSON`) fail-open. فعّل واحداً في PAPER وقِس ≥30 صفقة. | أثر مقيس قبل الثقة |
| **7** | وحّد مفتاح الإيقاف — اجعل `drawdown_recovery` يكتب `kill_switch.txt` أيضاً (أبقِ .json للتوافق). | master_floor + executor كلاهما يتوقّف |
| **8** | نظّف أشجار المصدر للبناء — احزم `trade_gate.py`/`r_executor.py`/algory libs/`decision_log.py` من مسارات friday_v3+r_native القانونيّة فقط؛ احذف نسخ pipflow/`r_native\friday_v3` من manifest. | المصدر هو ما يُشحَن |
| **9** | حلّ تصادم :8020 — انقل `r_trader\app.py` الى منفذ مغاير (أو watchdog يطلق gateway فقط). | تجميليّ/مراقبة فقط، آخِراً |
| **10** | بعد كل خطوة أعِد تدقيق Step-0. | لا انحدار؛ وإلّا اعكس الخطوة |

---

*نهاية الوثيقة — END. لا تُعدّل الكود الحيّ؛ نفّذ عبر الخطوات القابلة للعكس أعلاه.*
