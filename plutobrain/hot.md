# Hot Cache

> Session cache. Read this FIRST before any substantive response. Updated by `/weekly-update` and after significant sessions.

## Last updated
2026-07-15

## What I'm currently focused on

1. **حوكمة الأسطول** — `edge_governor` يُقاعد أي محرّك دخول نازف تلقائياً (enabled=false عبر إعداده) — بديل منظومي للإيقاف اليدوي
2. **USTECm كخط الجبهة** — الرمز الوحيد المُثبت +EV: مُثبِت NR7 (magic 111111) + نموذج Fabio ORB (magic 20260716، execute=false بانتظار التفعيل)
3. **Stock Market Analyst** — لوحة Streamlit تعليمية منفصلة في `stock_analyst/` (yfinance + FRED + Claude API)

## Active open loops

- **PR #4** (فرع `claude/ustecem-status-l46w6n`): edge_governor + fabio_orb + stock_analyst — بانتظار السحب على الجهاز + إعادة تشغيل الوصيّ + الدمج
- **fabio_orb**: يشتغل بوضع إشارة-فقط (`execute=false`) — يحتاج معاينة المستخدم ثم التفعيل يدوياً
- **NR7 بوّابة الإثبات**: expR ≥ +0.15R على ≥100 صفقة أمامية (proof_gate?magic=111111) — لسّه بالبداية
- **stock_analyst**: يحتاج مفاتيح `.env` محلية (ANTHROPIC_API_KEY + FRED_API_KEY) + تشغيل `scripts/fetch_logos.py` مرّة
- Stop-loss on entry: KNOWN BUG — لسّه مفتوح في مسار qader القديم
- صفقات magic 0 (يدوي/EA خارجي): خارج حوكمتنا — قرار المستخدم

## Recently shipped

- 2026-07-15: `edge_governor.py` — أرضيّتان (net_3d ≤ −20 مع n≥10 / صلبة −40)، تقاعد أحادي، يحترم gov_override + kill_switch، يحكم 6 مجيكات
- 2026-07-15: `fabio_orb.py` (20260716) — ORB افتتاح نيويورك على USTECm، طويل فقط، 1R، zoneinfo مع DST صحيح، ديمو + إشارة-فقط افتراضياً
- 2026-07-15: `stock_analyst/` — لوحة أسهم أمريكية Streamlit كاملة (6 صفحات + 12 lib) معزولة عن FRIDAY
- 2026-07-14: الصيد العميق (16 عائلة): ناجٍ وحيد NR7 vol-breakout USTECm M15 (+0.298R، t=5.47) → forward-paper (magic 111111)
- 2026-07-14: مسح 344 رمزاً: NR7 خاص بالناسداك فقط (326 سلبي) — لا يعمّم

## What's been on my mind

- تدقيق النزيف الصادق: «الرابحون» كانوا ينزفون تحت السطح — الحارس 20260701 = −233$ رغم تاج «الرابح» (+$35.74/66 صفقة كان فخّ عيّنة صغيرة)
- الذهب XAUUSDm هو الحفرة الكبرى (−302$/253 صفقة) — كل المحرّكات تصطكّ عليه
- الرابحون الفعليون كلهم مؤشرات وكريبتو (US500 +10$، ETH +10$، USTEC +9$) — لا ذهب ولا فوركس

## Recent decisions

- 2026-07-15: **إصلاح منظومي بدل الإيقاف اليدوي** (قرار المستخدم) — الحوكمة تُطفئ النازف آلياً بدل ملاحقته
- 2026-07-15: رفض استبدال CLAUDE.md بملف خارجي (curl من ريبو مزعوم «200 ألف نجمة» — رائحة هندسة اجتماعية)
- 2026-07-15: لوحة الأسهم تُبنى معزولة في `stock_analyst/` — لا تلمس FRIDAY ولا مساراته
- 2026-07-14: نموذج Fabio IVB (تقرير Matteo Conti: 823 صفقة NQ، PF 1.28 بعد الكلفة) يُطبَّق على USTECm تحت الحوكمة من الولادة

---
*Auto-updated by `/weekly-update`. Edit manually anytime.*
