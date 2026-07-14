# FRIDAY / R-Native + ICA Risk Management — النظام المتكامل المستدام
> دمج: FRIDAY Trading System + ICA Risk Framework + DNA/Genetics Evolution + Infinite Sustainability Loop
> التاريخ: 2026-06-11 | الحالة: DEMO فقط | الهدف: نظام ذاتي التطوّر بلا نهاية

---

## الفلسفة الجديدة: "النظام الحيّ" (The Living System)

النظام ليس برنامجاً — هو **كائن حيّ رقمي** يتنفس، يتعلّم، يتطوّر، ويُدير مخاطره بنفسه إلى الأبد.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    الحلقة الأبدية (The Infinite Loop)                        │
│                                                                             │
│   ┌─────────────┐      ┌─────────────┐      ┌─────────────┐               │
│   │   SENSE     │ ──►  │   THINK     │ ──►  │   ACT       │               │
│   │  (استشعار)   │      │  (تفكير)    │      │  (فعل)      │               │
│   └──────┬──────┘      └──────┬──────┘      └──────┬──────┘               │
│          │                    │                    │                         │
│          │     ┌──────────────┘                    │                         │
│          │     │                                   │                         │
│          │     ▼                                   │                         │
│          │  ┌─────────────┐      ┌─────────────┐  │                         │
│          │  │   LEARN     │ ──►  │   EVOLVE    │  │                         │
│          │  │  (تعلّم)     │      │  (تطوّر)    │  │                         │
│          │  └─────────────┘      └──────┬──────┘  │                         │
│          │                             │         │                         │
│          └─────────────────────────────┴─────────┘                         │
│                                                                             │
│   كل دورة = جيل (Generation) → DNA مُحسّن → أداء أفضل → بقاء أقوى          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## الطبقة الأولى: تأسيس السياق (Establish Context) — ICA Step 1

### 1.1 سياق النظام الكلي

| البُعد | التعريف | المؤشرات |
|--------|---------|----------|
| **السوق** | بيئة التداول الحالية | volatility regime · liquidity · session |
| **المحفظة** | حالة الحساب الحالية | equity · margin · exposure · correlation |
| **الاستراتيجيات** | الأوضاع النشطة | mode_weights · genome fitness · win rate |
| **البيئة الخارجية** | أخبار · ترابط · ماكرو | news_signals · intermarket · directive |
| **النظام الداخلي** | صحة الخدمات · الأداء | service health · latency · error rate |

### 1.2 ملف السياق الديناميكي (`context_dna.json`)

```json
{
  "timestamp": "2026-06-11T03:57:00Z",
  "generation": 847,
  "market_context": {
    "regime": "trending_bullish",
    "volatility": "expanded",
    "liquidity": "normal",
    "session": "NY",
    "spread_status": "acceptable"
  },
  "portfolio_context": {
    "equity": 92.61,
    "peak": 679.00,
    "drawdown_pct": 86.4,
    "margin_level": 245.0,
    "open_exposure": 0.0,
    "daily_pnl": -2156.00,
    "daily_limit_remaining": -10.0
  },
  "strategy_context": {
    "active_modes": ["macro", "wick_rev"],
    "disabled_modes": ["gap_pend", "srlim"],
    "genome_fitness": {
      "XAUUSD_NY": 0.73,
      "BTCUSD": 0.61,
      "XAGUSD": 0.44
    }
  },
  "external_context": {
    "news_sentiment": "neutral",
    "intermarket_stress": false,
    "directive": "TRADE_LIGHT",
    "risk_level": "MEDIUM"
  },
  "system_context": {
    "services_up": 0,
    "services_down": 7,
    "last_heartbeat": "2026-05-15T20:59:51Z",
    "mt5_status": "BLOCKED"
  }
}
```

---

## الطبقة الثانية: تحديد المخاطر (Identify Risk) — ICA Step 2

### 2.1 سجل المخاطر الشامل (`risk_register.json` — ICA Format)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    سجل المخاطر (Risk Register) — 13 مخاطر                   │
├────┬─────────────────────────┬──────────┬────────┬─────────────────────────┤
│ ID │ الخطر                   │ الاحتمال │ الأثر  │ التصنيف                 │
├────┼─────────────────────────┼──────────┼────────┼─────────────────────────┤
│ R1 │ خسارة يومية > 10%       │   0.15   │  CRIT  │ مالي — قتل تلقائي       │
│ R2 │ مارتينجيل/تكديس خاطئ    │   0.25   │  HIGH  │ سلوكي — منع تلقائي      │
│ R3 │ سبريد مرتفع يقتل الربح  │   0.40   │  HIGH  │ سوقي — بوّابة سيولة      │
│ R4 │ أخبار عالية التأثير     │   0.20   │  HIGH  │ خارجي — فيتو أخبار       │
│ R5 │ تداول ليلي ضعيف         │   0.30   │  MED   │ زمني — جدولة جلسات       │
│ R6 │ انزلاق (سليباج) كبير    │   0.35   │  MED   │ تنفيذي — حماية بلا-وقف   │
│ R7 │ فشل خدمة حرج            │   0.10   │  CRIT  │ تقني — watchdog إحياء    │
│ R8 │ EAs قديمة تخسر خارج الحكم│  0.50   │  HIGH  │ حوكمة — عزل تلقائي       │
│ R9 │ تضخّم مؤشرات بلا حافة    │   0.60   │  LOW   │ كفاءة — تقليم آلي        │
│ R10│ قرار DNA معيب           │   0.20   │  HIGH  │ تعلّمي — تنويع جيني      │
│ R11│ ارتباط محفظي متراكز     │   0.30   │  HIGH  │ محفظي — سقف كتلي         │
│ R12│ نقطة فشل MT5/AutoTrading│   0.25   │  HIGH  │ تقني — فحص صحّة          │
│ R13│ عدم موثوقية البيانات    │   0.20   │  MED   │ بيانات — تحقّق متعدد     │
└────┴─────────────────────────┴──────────┴────────┴─────────────────────────┘
```

### 2.2 آلية التحديد المستمر (Continuous Risk Identification)

كل 60 ثانية:
- risk_scanner يفحص 13 مخاطر
- MT5 health check (R12)
- Portfolio correlation matrix (R11)
- Service heartbeat (R7)
- News calendar scan (R4)
- Spread vs ATR ratio (R3)
- Equity drawdown trajectory (R1)
- EA magic number audit (R8)
- يُحدّث risk_register.json تلقائياً

---

## الطبقة الثالثة: تحليل المخاطر (Analyze Risk) — ICA Step 3

### 3.1 مصفوفة التحليل (Risk Analysis Matrix)

| الاحتمال / الأثر | منخفض (1) | متوسط (2) | عالٍ (3) | حرج (4) |
|-----------------|-----------|-----------|----------|---------|
| نادر (<0.1)     | 1         | 2         | 3        | 4       |
| غير محتمل (0.1-0.3) | 2     | 4         | 6        | 8       |
| محتمل (0.3-0.5) | 3         | 6         | 9        | 12      |
| مرجّح (>0.5)    | 4         | 8         | 12       | 16      |

- 12+ = يتطلب معالجة فورية
- 16 = إيقاف تداول فوري + إشعار

### 3.2 التحليل الجماعي (Team Analysis Simulation)

محاكاة "العمل الجماعي" في النظام:
- 31 وكيل + 46 PlutoBrain + LLM Analyst + Genome Factory
- كل واحد يُحلّل من زاوية مختلفة → تصويت مرجّح

```
def analyze_risk_collective(risk_id, context):
    votes = {}
    for agent in active_agents:
        if agent.can_assess(risk_id):
            votes[agent.id] = agent.assess(risk_id, context)

    weighted_score = weighted_average(votes, weights=agent_accuracy)
    confidence = vote_consensus(votes)

    return {
        "score": weighted_score,
        "confidence": confidence,
        "dissenters": find_outliers(votes),
        "recommended_action": derive_action(weighted_score, confidence)
    }
```

---

## الطبقة الرابعة: تقدير الأولويات (Assess & Prioritize) — ICA Step 4

### 4.1 نظام الأولويات الديناميكي

**PRIORITY 1: إيقاف فوري (STOP NOW)**
- الاحتمال × الأثر >= 12 (أحمر داكن)
- الإجراء: إيقاف كل الدخول + إغلاق جزئي + إشعار فوري
- المخاطر: R1, R7, R11

**PRIORITY 2: تقليل فوري (REDUCE NOW)**
- الاحتمال × الأثر = 8-9 (أحمر فاتح)
- الإجراء: تقليل لوت 50% + تعطيل أوضاع عالية الخطورة
- المخاطر: R2, R3, R4, R8

**PRIORITY 3: مراقبة مُشدّدة (WATCH CLOSELY)**
- الاحتمال × الأثر = 4-6 (أصفر)
- الإجراء: تسجيل مُفصّل + تجهيز خطة طوارئ
- المخاطر: R5, R6, R10, R12

**PRIORITY 4: مراقبة روتينية (MONITOR)**
- الاحتمال × الأثر <= 3 (أخضر)
- الإجراء: تسجيل دوري + تحسين تدريجي
- المخاطر: R9, R13

### 4.2 آلية التحديث الذاتي للأولويات

كل 10 دقائق:
- evolution_director يُعيد حساب دقّة كل وكيل في التنبؤ بالمخاطر
- أوزان المخاطر حسب النتائج الحيّة
- أي مخاطر "جديدة" ظهرت ولم تُسجَّل
- تحديث risk_register + إعادة ترتيب الأولويات

---

## الطبقة الخامسة: التعامل مع المخاطر (Treat Risk) — ICA Step 5

### 5.1 خطة المعالجة لكل خطر (Treatment Plans)

| ID | الخطة | التنفيذ | المراقبة | التوثيق |
|----|-------|--------|----------|---------|
| R1 | قتل يومي -10% + أرضية حقوق + تهدئة | risk_sentinel يُراقب equity كل ثانية | live_terminal drawdown | DIGEST + CHANGELOG |
| R2 | ممنوع التكديس فوق الخاسر + conviction فوق الرابح | coordinator يفحص basket>=0 | scalp_evolver | evolution_log |
| R3 | بوّابة سيولة (سبريد <= 40% ATR) | كل منفّذ يفحص spread قبل الدخول | algory_chart_dashboard | gap_fill_validator |
| R4 | فيتو أخبار ±15-20 دقيقة | news_engine يُبلّغ risk_manager | news_signals.json | straddle_journal |
| R5 | جدولة جلسات — ASIAN مراقبة فقط | multi_trader يُفعّل حسب الجلسة | evolution_director | mode_weights.json |
| R6 | حماية بلا-وقف 12% + وقف متحرّك + خروج الذيل | كل صفقة SL صلب + trailing | live_terminal SL distance | scalp_evolver |
| R7 | watchdog يُحيي 21 محرّكاً | watchdog يفحص كل خدمة | live_terminal 7 خدمات | system_health_log |
| R8 | عزل EAs القديمة + magic 0 مُعفى | coordinator يتجاهل magic غير معروف | truth_tracker حسب magic | تقرير حقيقة منفصل |
| R9 | تقليم آلي — حذف مؤشر وزنه <0.1 | accuracy_updater يحذف | chart_read عدد مؤشرات | evolution_log |
| R10 | تنويع جيني — 50 جينوم + تهجين | genome_factory يُنتج جيل جديد | market_gate OOS | genome_registry |
| R11 | سقف ارتباط كتلي <=15% حقوق | portfolio_correlation يحسب matrix | risk_manager كل دقيقة | risk_register |
| R12 | فحص AutoTrading كل 60ث | mt5_health_monitor | watchdog live_terminal | system_health_log |
| R13 | تحقّق متعدد المصادر | data_validator يقارن 3 مصادر | data_quality_score | data_integrity_log |

### 5.2 خطة الطوارئ (Emergency Plan)

**TRIGGER:**
- equity < 50% من البيك (أي < $339.5)
- 3 خدمات حرجة DOWN لأكثر من 5 دقائق
- MT5 AutoTrading OFF + لا يمكن الإصلاح خلال 2 دقيقة
- ارتباط محفظي > 80% مع drawdown > 20%

**PROTOCOL:**
1. إيقاف كل الدخول الجديد فوراً
2. إغلاق 50% من المراكز المفتوحة (الأكثر خسارة أولاً)
3. تفعيل "وضع الحماية": lot_mult = 0.1 فقط
4. إرسال إشعار طوارئ للمستخدم (SMS + Email + Dashboard)
5. تسجيل الحدث في EMERGENCY_LOG.md
6. تشغيل "وضع التشخيص": تجميع كل البيانات
7. انتظار موافقة المستخدم للعودة (أو 24 ساعة تلقائياً)

**RECOVERY:**
- إذا نجحت: توثيق + تدريب DNA (تعلّم من الطوارئ)
- إذا فشلت: "وضع السبات" — إيقاف كل شيء + انتظار تدخّل يدوي

---

## الطبقة السادسة: DNA والجينات (The Genetic Engine)

### 6.1 هيكل DNA التداول (Trading DNA Structure)

**CHROMOSOME 1: إدخال السوق (Entry)**
- gene_entry_conf_gate (0.50 - 0.85) — بوّابة التوافق
- gene_entry_rsi_buy (20 - 45) — شرط RSI شراء
- gene_entry_rsi_sell (55 - 80) — شرط RSI بيع
- gene_entry_macd_align (true/false) — محاذاة MACD
- gene_entry_smc_confirm (true/false) — تأكيد SMC
- gene_entry_markov_veto (true/false) — فيتو Markov D1

**CHROMOSOME 2: إدارة المركز (Position Management)**
- gene_stop_atr_mult (1.0 - 3.0) — مضاعف ATR للوقف
- gene_target_atr_mult (1.5 - 4.0) — مضاعف ATR للهدف
- gene_trail_atr_mult (0.5 - 2.0) — مضاعف ATR للتريل
- gene_be_trigger_pct (30 - 70) — % للتحويل لـ BE
- gene_max_hold_minutes (5 - 120) — أقصى مدة مسكة

**CHROMOSOME 3: حجم المركز (Sizing)**
- gene_base_lot (0.01 - 0.10) — اللوت الأساسي
- gene_conviction_mult (1.0 - 2.0) — مضاعف القناعة
- gene_risk_pct_per_trade (0.5 - 3.0) — % مخاطرة لكل صفقة
- gene_max_concurrent (1 - 10) — أقصى صفقات متزامنة

**CHROMOSOME 4: إدارة المخاطر (Risk) — ICA Integrated**
- gene_daily_kill_pct (5 - 15) — % قتل يومي
- gene_max_drawdown_pct (20 - 50) — % أقصى انحدار
- gene_correlation_limit (0.5 - 0.9) — حد الارتباط
- gene_news_veto_minutes (10 - 30) — دقائق فيتو أخبار
- gene_emergency_equity (30 - 60) — % equity للطوارئ

**CHROMOSOME 5: التعلّم (Learning)**
- gene_learning_rate (0.01 - 0.3) — سرعة التعلّم
- gene_ewma_alpha (0.1 - 0.5) — معامل EWMA
- gene_exploration_rate (0.05 - 0.3) — نسبة الاستكشاف
- gene_memory_window (50 - 500) — نافذة الذاكرة

TOTAL: 22 genes per genome | POPULATION: 50 genomes per symbol/session | GENERATIONS: Infinite

### 6.2 دورة الحياة الجينية (Genetic Life Cycle)

```
BIRTH (ولادة)
    ↓
 genome_factory يُنتج 50 جينوم عشوائي (أو تهجين من الأبوين الأفضل)
    ↓
VALIDATION (تحقّق)
    ↓
 market_gate يُحقّق OOS على 50k شمعة + سبريد حقيقي
 · Sharpe > 0.2 · PF > 1.0 · Max DD < 30% · Trades > 100
    ↓
DEPLOYMENT (نشر)
    ↓
 deploy_genomes ينشر الأفضل إلى symbol_configs (Top 3 per symbol/session)
    ↓
LIVE TEST (اختبار)
    ↓
 paper_prover يُجري إثبات أمامي: 50 صفقة · PF > 1.2 · Net positive
    ↓
MATING (تزاوج)
    ↓
 الأفضل يتزاوج + طفرات عشوائية (Crossover 0.7 · Mutation 0.05)
    ↓
DEATH (موت)
    ↓
 الجينات الضعيفة تُبنّح (fitness < 0.3 لمدة أسبوع → حذف)
    ↓
 (back to BIRTH)
```

CYCLE TIME: 3 ساعات (reoptimize) + يومياً (تحقّق كامل)
LIFESPAN: جين ناجح = يعيش أسبوعين → يصير "أسطورة" → DNA مرجعي

### 6.3 DNA المرجعي (Legendary Genomes Archive)

عندما جينوم يحقّق:
- 100 صفقة حيّة + PF > 1.5 + Sharpe > 0.5 + Max DD < 20%

→ يُحفظ في LEGENDARY_DNA/ باسم: {symbol}_{session}_{timestamp}_{fitness}.json
→ يُستخدم كـ "أب" مفضّل في التهجين (80% chance)
→ يُعرض في ARENA تبويب "الأساطير"
→ يُدرّس للوكلاء الجدد (transfer learning)

CURRENT LEGENDS (مثال):
- XAUUSD_NY_20260601_0.847.json — 147 صفقة · PF 1.63 · Sharpe 0.58
- BTCUSD_24H_20260528_0.721.json — 89 صفقة · PF 1.41 · Sharpe 0.44

---

## الطبقة السابعة: الحلقة الأبدية (The Infinite Sustainability Loop)

### 7.1 الحلقة الكبرى (The Grand Loop)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    الحلقة الأبدية (Infinite Sustainability Loop)            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────┐           │
│   │ SENSE    │───►│ IDENTIFY │───►│ ANALYZE  │───►│ ASSESS │           │
│   │ استشعار  │    │ تحديد    │    │ تحليل    │    │ تقدير  │           │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘    └───┬────┘           │
│        │               │               │              │                 │
│        │               │               │              │                 │
│   ┌────┴─────┐    ┌────┴─────┐    ┌────┴─────┐    ┌┴─────┐             │
│   │ CONTEXT  │    │ RISK     │    │ TEAM     │    │ PRIOR- │             │
│   │ سياق     │    │ REGISTER │    │ ANALYSIS │    │ ITIZE  │             │
│   └──────────┘    └──────────┘    └──────────┘    └────────┘             │
│        ▲                                               │                   │
│        │                                               ▼                   │
│   ┌────┴─────┐    ┌──────────┐    ┌──────────┐    ┌────────┐           │
│   │ LEARN    │◄───│ EVOLVE   │◄───│ MONITOR  │◄───│ TREAT  │           │
│   │ تعلّم    │    │ تطوّر    │    │ مراقبة   │    │ تعامل│           │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘    └───┬────┘           │
│        │               │               │              │                 │
│   ┌────┴─────┐    ┌────┴─────┐    ┌────┴─────┐    ┌┴─────┐             │
│   │ DNA      │    │ GENOME   │    │ TRUTH    │    │ PLAN   │             │
│   │ UPDATE   │    │ FACTORY  │    │ TRACKER  │    │ EXEC   │             │
│   └──────────┘    └──────────┘    └──────────┘    └────────┘             │
│                                                                             │
│   ═══════════════════════════════════════════════════════════════════════   │
│   COMMUNICATION (التواصل) wraps everything — left pillar                     │
│   MONITORING & REVIEW (المراقبة والمراجعة) wraps everything — right pillar │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│   CYCLE FREQUENCY:                                                          │
│   · SENSE → every tick (MT5 data)                                         │
│   · IDENTIFY → every 60 seconds (risk_scanner)                              │
│   · ANALYZE → every 10 minutes (agent consensus)                            │
│   · ASSESS → every 10 minutes (evolution_director)                        │
│   · TREAT → immediate (event-driven)                                      │
│   · MONITOR → continuous (live_terminal)                                  │
│   · EVOLVE → every 3 hours (_reoptimize_loop)                             │
│   · LEARN → every trade (scalp_evolver) + every hour (secure_learner)     │
│                                                                             │
│   NO END. NO STOP. FOREVER.                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 لوحة الحقيقة (Truth Tracker)

كل 10 دقائق، truth_tracker يُصدر حكمه:

| METRIC | VALUE | THRESHOLD | STATUS |
|--------|-------|-----------|--------|
| Weekly P&L (all sources) | -$X.XX | > +$10 | FAIL / PASS |
| Win Rate (live trades) | XX.X% | > 45% | FAIL / PASS |
| Profit Factor (live) | X.XX | > 1.2 | FAIL / PASS |
| Max Drawdown (live) | XX.X% | < 20% | FAIL / PASS |
| Sharpe Ratio (live) | X.XX | > 0.3 | FAIL / PASS |
| Service Uptime | XX.X% | > 95% | FAIL / PASS |
| Risk Register Health | X/13 | = 13/13 | FAIL / PASS |
| DNA Evolution Rate | X.XX | > 0.1 | FAIL / PASS |

VERDICT:
- 6/8 PASS → HEALTHY → استمرار طبيعي
- 4-5/8 PASS → CAUTION → تقليل لوت 50% + مراقبة مُشدّدة
- <4/8 PASS → CRITICAL → إيقاف تداول + تشخيص + طوارئ

الأسبوع القياس (Measurement Week):
- كل مصدر تداول يُقاس منفرداً لمدة أسبوع
- ما يثبت (>=6/8 PASS) → يتوسّع
- ما يفشل (<4/8 PASS) → يُبنّح آلياً

---

## الطبقة الثامنة: التواصل والمراقبة (Communication & Monitoring)

### 8.1 التواصل (Communication) — العمود الأيسر

داخلي (System-to-System):
- JSON files: market_directive · risk_register · mode_weights · news
- HTTP APIs: /api/decision · /api/scalp_status · /api/risk_status
- ZMQ: MT5 ↔ Python real-time tick data

خارجي (System-to-User):
- ARENA :8870 → لوحة تفاعلية
- live_terminal.py → كونسول كل 2 ثانية
- DIGEST_YYYY-MM-DD.md → تقرير ليلي تلقائي
- UPDATE_PENDING.md → بيان التحديث القادم
- إشعارات طوارئ → SMS/Email (عند CRITICAL)

بين الوكلاء (Agent-to-Agent):
- 31 وكيل داخلي → consensus voting
- 46 PlutoBrain → تحليل كود وتحسين
- LLM Analyst → market_directive.json

### 8.2 المراقبة والمراجعة (Monitoring & Review) — العمود الأيمن

مراقبة لحظية (Real-time):
- live_terminal.py (كل 2 ثانية): Equity · P&L · Open trades · Spread · Services · Agents
- algory_chart_dashboard (:8866): شموع إسقاط · أهداف ليزر · حالة السكالبر
- friday_brain_view (:5056): حالة الدماغ · رؤى الوكلاء · رؤى LLM

مراجعة دورية (Periodic Review):
- كل 10 دقائق: truth_tracker → حكم
- كل 30 دقيقة: evolution_director → أوضاع
- كل ساعة: secure_learner · risk_manager
- كل 3 ساعات: _reoptimize_loop → جينات
- يومياً: evolution_director → جلسات + اكتشاف + digest_writer
- أسبوعياً: تقرير شامل → أداء كل مصدر + قرارات توسيع/تقليص

قياس الامتثال (Compliance Measurement):
- هل كل منفّذ يقرأ risk_register قبل الدخول؟
- هل كل صفقة لها SL صلب؟
- هل magic 0 (اليدوي) لم يُلمس؟
- هل EAs القديمة معزولة؟
- هل الارتباط المحفظي < 80%؟
- هل AutoTrading = ON؟

كل قياس فاشل = إشعار + تصحيح تلقائي أو إيقاف + إشعار مستخدم

---

## خارطة الطريق النهائية (The Infinite Roadmap)

PHASE 0: الأساس (مُنجز)
- اكتشاف السوق (238 رمز)
- بوّابة OOS + سبريد حقيقي
- مصنع جينات + متخصّصي جلسات
- حوكمة (محلّل+مخاطر+أوضاع)

PHASE 1: التوحيد والقياس (الآن — 2026-06-11)
- توحيد الحوكمة (الكل يقرأ directive/risk/mode)
- تفعيل truth_tracker + أسبوع قياس نظيف
- عزل EAs القديمة + إطفاء stacker 99790
- إضافة R11 (سقف ارتباط) + R12 (MT5 health) + R13 (بيانات)
- تفعيل digest_writer (تقرير ليلي)

PHASE 2: الاستدامة الجينية (2026-06-18)
- تقليم مؤشرات آلي (أوزان <0.1)
- DNA مرجعي (Legendary Genomes Archive)
- توسيع الصيّاد (قاعدة الترقية 10 محاولات +$3)
- بطاقة "قرارات المدير" في ARENA

PHASE 3: التوسّع الذكي (2026-07-01)
- قرار الذهب المزدوج (قصر unified على NY أو إخضاعه)
- إضافة رموز جديدة تلقائياً
- تفعيل straddle_hunter على أخبار حقيقية
- توسيع multi_trader إلى 5 أزواج إضافية

PHASE 4: الانتقال للحقيقي (بإذنك فقط — بعد إثبات)
- scalp_proof: >=50 صفقة + PF>1.2 + صافي موجب بعد السبريد
- truth_tracker: 4 أسابيع متتالية HEALTHY
- DNA مرجعي: 3 أساطير على الأقل
- GO LIVE (بإذن صريح منك فقط)

PHASE 5: النظام الحيّ (ما بعد الحقيقي — إلى الأبد)
- التعلّم المستمر من كل صفقة (scalp_evolver)
- التطوّر الجيني المستمر (_reoptimize_loop)
- اكتشاف رموز جديدة تلقائياً (evolution_director)
- تحديث risk_register تلقائياً (risk_scanner)
- تقارير ليلية مستمرة (digest_writer)
- تحديثات ذاتية بإذن المستخدم (update_manager)
- ... إلى ما لا نهاية ...

---

## ملخّص الفعل الفوري (Immediate Action Plan)

### هذا الأسبوع (2026-06-11 → 2026-06-18):

| # | الفعل | الملف | الأولوية | الوقت |
|---|-------|-------|----------|-------|
| 1 | إعادة تشغيل الخدمات | start_friday_all.ps1 | P0 — فوري | 10 دق |
| 2 | تفعيل truth_tracker | truth_tracker.py | P0 — فوري | 30 دق |
| 3 | عزل EAs القديمة | coordinator.py (magic filter) | P0 — فوري | 15 دق |
| 4 | إضافة R11 (سقف ارتباط) | risk_manager.py | P1 — اليوم | 1 ساعة |
| 5 | إضافة R12 (MT5 health) | mt5_health_monitor.py | P1 — اليوم | 1 ساعة |
| 6 | توحيد الحوكمة | coordinator.py + كل منفّذ | P1 — غداً | 2 ساعة |
| 7 | تفعيل digest_writer | digest_writer.py | P2 — هذا الأسبوع | 2 ساعة |
| 8 | DNA مرجعي (Legendary) | genome_factory.py (archive) | P2 — هذا الأسبوع | 1 ساعة |

---

> **الحقيقة العلمية النهائية:**
> لا يوجد نظام تداول "مثالي". الحافة الحقيقية = **الانضباط المُفرَط** + **إدارة المخاطر الصارمة** + **التعلّم المستمر** + **الصبر**.
> هذا النظام لا يُعدّك بالثراء السريع — يُعدّك **بالبقاء** حتى تصل.
> "الربحية ليست هدفاً — هي نتيجة طبيعية لإدارة مخاطر ممتازة على مدى زمني طويل."
