# لماذا FRIDAY-Algory++ سيكون أفضل من Algory الأصلي

## ما تعلمناه من Algory (مراقبة 16 process، 79 strategy، 124+ تجربة OOS)

### 🟢 الجينات التي تربح فعلياً (XAU H1)
1. `use_sig_breakout` — **100%** pass rate (8/0) → كسر النطاق هو الإشارة الأقوى
2. `use_sig_mom_break` — 80% pass (4/1) → كسر الزخم
3. `use_filt_rsi` — 66% → RSI كفلتر
4. `use_filt_receding` — 53% → فلتر التراجع
5. `use_bias_chandelier` — 40% → Chandelier exit
6. `use_bias_sma` — 35% (28 wins absolute) → SMA bias

### 🔴 الجينات التي تخسر دائماً (تجنّب)
- `use_bias_psar` (0/6), `use_filt_doji` (0/13), `use_filt_keltner` (0/7)
- `use_partial_tp` (0/15), `use_bias_trailing` (2/23)
- `use_sl_lock` (1/17), `use_sl_reduce` (1/16), `use_filt_adr_exhaust` (0/12)

### 🏆 خلاصة Top 5 (returns 359%-486%)
- **Sessions:** 08:00-20:00 UTC (London+NY فقط، اترك Asia)
- **Friday close:** 17:00-19:00 UTC
- **R:R:** 4:1 إلى 5:1 (TP=7-10×ATR، SL=1.95-2.2×ATR)
- **Win Rate:** 55-60%، **PF:** 2.3-2.5، **DD:** 11-15%
- **News filter + daily DD + symbol lock** كلها مفعّلة دائماً
- **win_mechanism:** FRIDAY_DRIFTER (التقاط حركات نهاية الأسبوع)

---

## 7 أسباب لماذا نسختنا أفضل من Algory الأصلي

| # | Algory | FRIDAY-Algory++ |
|---|---|---|
| 1 | **مغلق** (binary 57MB) — لا يمكن تعديله | **مفتوح كلياً** — كل سطر Python نقرأه ونعدّله |
| 2 | **Offline factory فقط** — يولّد ثم يصدّر EAs | **Live integration** — يقرأ MT5 الحي + spread الحقيقي + الأخبار |
| 3 | **Per-TF training منفصل** | **Multi-TF coordinated** (5 frames في snapshot واحد) |
| 4 | **لا AI advisory** — قرار رياضي بحت | **5 وكلاء LLM** يصدّقون كل setup قبل التنفيذ |
| 5 | **Historical spread** (2023 data, 9pt spread) | **Live spread regime gate** (308pt الآن → DEAD = لا تداول) |
| 6 | **One-shot training** ثم EA ثابت | **Continuous learning** — كل 60s يقرأ vault الجديد |
| 7 | **No news awareness** في الـ EA المولّد | **FF parser مدمج** + خصم نوافذ الأخبار |

---

## ما تم بناؤه الآن (read-only، لا يلمس EA الشغّال)

### 1. `friday_v3/algory/algory_watcher.py`
- يراقب 16 process من Algory/Engine
- يستخرج vault + gene_fitness + diagnostics
- يحدّث `data/algory_report.json` كل 60s
- يصنع mirror محلي لـ vault للتحليل المستقبلي

### 2. `friday_v3/algory/strategy_mirror.py`
- `TRUSTED_GENES` + `BLACKLISTED_GENES` (مع التبرير)
- 4 archetype templates (BREAKOUT_HUNTER, MEAN_REVERTER, MULTI_SIGNAL, PATTERN_SPOTTER)
- `evaluate_setup(snapshot, archetype)` — يحكم على السوق الحالي

### 3. brain_server endpoints جديدة
- `GET /api/algory` → snapshot كامل (procs, vault, fitness, recommendations)
- `GET /api/algory/strategy` → archetype eval حي للسوق الآن

### 4. Dashboard panels جديدة
- **🧬 ALGORY INTEL panel** — KPIs + whitelist/blacklist + top 5 + archetypes
- **⚖ LIVE EVALUATION** — هل أحد الـ archetypes يتطابق مع السوق الآن؟
- **🤝 TEAM DECISION ENGINE** (موجود مسبقاً) — يقرأ كل أرقام الصفحة + يستشير 5 وكلاء

---

## الخطوات التالية المقترحة

### Phase A — Validation (paper-only)
1. شغّل `friday_v4/paper_trader.py` يستخدم BREAKOUT_HUNTER archetype مع شروط whitelist
2. سجل كل صفقة paper لأسبوع كامل في dashboard
3. قارن النتائج مع Algory أصلي (نفس الفترة، نفس symbol)

### Phase B — Continuous retraining
4. اربط watcher بـ MT5 — كل ساعة، اقرأ آخر 100 شمعة H1 وأعد scoring الجينات
5. حدّث whitelist تلقائياً عند ظهور gene جديد ≥50% pass rate

### Phase C — News awareness (ميزة فوق Algory)
6. الـ news straddle (موجود) يصبح أولوية أعلى من dip-buyer
7. blackout window حول HIGH impact news (±15min)

### Phase D — Live execution (فقط بعد paper validation 7+ أيام)
8. Magic جديد 20260605 لـ FRIDAY-Algory++
9. حجم lot يبدأ 0.01، يتدرج لـ Kelly بعد 30 صفقة
10. Daily cap صارم: -$3 يومياً → kill_switch

---

**صفر تأثير على EA الشغّال** (`FRIDAY_Brain_Executor.mq5` لم يُلمس).
**صفر تنفيذ صفقات تلقائي** (المحرّك استشاري فقط).
**Algory.exe يكمل عمله** بدون تشويش.
