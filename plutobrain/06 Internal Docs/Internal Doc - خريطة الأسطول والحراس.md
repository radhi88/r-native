---
type: internal-doc
created: 2026-07-07
updated: 2026-07-07
status: active
tags: [internal-doc, fleet, watchdog, magics, infrastructure]
---

# Internal Doc - خريطة الأسطول والحراس

**Summary:** الخريطة المرجعية لأسطول FRIDAY/R Trader على MT5 (ديمو): ~30 محركاً بلا نوافذ يحرسها watchdog_guard.py، موحّدة خلف بوابة R Trader على :8020 (cockpit + scoreboard + تحكم بالمحركات) مع نفق عام. [[evergreen]] [[high-value]]

## البنية (Architecture)
- **المحركات:** ~30 عملية Python بلا نوافذ (pythonw) تعمل على طرفية MT5 ديمو (كشف الديمو عبر اسم السيرفر Trial/Demo — Exness يرجع trade_mode=0 حتى للتجريبي).
- **الحارس:** `watchdog_guard.py` — يحيي الميت **والمعلّق** (alive-but-stale)، بقوائم ENGINES + _FOCUS_KEEP + HEARTBEAT. درس تاريخي: افحص **عمر ملف الحالة** لا عدد العمليات.
- **البوابة:** R Trader gateway على **:8020** — cockpit + scoreboard + تشغيل/إيقاف المحركات، منشورة بنفق عام (Cloudflare tunnel).
- **الأقفال:** engine_lock ببورت صريح لكل محرك — **ماسك القفل** هو الحقيقة، لا عدد العمليات (توائم venv: pythonw وسيط + ابن يبدوان اثنين).
- **الحالة:** كتابات atomic لملفات JSON في data/r_native/؛ kill-switch heartbeat حتى في الخمول.

## جدول الـ Magics (Ours)
| المحرك | magic | الحالة | ملاحظات |
|---|---|---|---|
| R Core (ذهب فقط) | 20260706 | متحدٍ جديد | وريث brain_trader — revenge_logic + Pine trigger + no-stack-on-red |
| Multi-symbol sentinel | 20260709 | متحدٍ مضبوط الخسارة | 1.5%/صفقة، تجميد −5% يومي، أرضية ستوب 3x سبريد |
| Gold level sentinel | 20260701 | فعال | تنبيهات تفاعل مستويات + منفّذ مبوّب؛ فتيل x15 منزوع بـ risk_cap 0.008 |
| YouTube analyst | 20260631 | تجربة صغيرة | ~48% — يُبقى صغيراً |
| brain_trader (رشاش 17 عملة) | — | **متقاعد** | −$61/3 أيام — [[Decision - 2026-07-06 - تقاعد الرشاش وولادة R Core]] |

**خارجية — لا تُلمس:** magics المستخدم {2447، 20250418، 20250421/22، 20250618} وmagic 0 = يده اليدوية.

## السبورة (Scoreboard)
- desk_scoreboard مع NAME_MAP لكل magic؛ عمود **payoff** هو القاضي ([[Workflow - محكمة السبورة (ترقية وتقاعد)]]).
- المصدر الأرضي للأرقام: [[Prompt - لقطة أرباح لكل magic]].
- طبقة الإدارة المشتركة: profit_harvester أصبح R-aware (arm = max($1, 0.8R)) بعد [[Decision - 2026-07-07 - جراحة عدم التماثل]].

## قواعد التشغيل الذهبية
1. ولادة محرك = [[Workflow - ولادة محرك جديد (قائمة الفحص)]] كاملة، بلا استثناء.
2. إعادة تشغيل = [[Workflow - إعادة تشغيل آمنة (اقتل ثم أحيِ)]] — ممنوع mass-kill (درس خنق Exness وIPC flood).
3. اتصال MT5 واحد لكل عملية قصيرة — لا initialize() داخل لوبات.
4. أي تعديل يدوي على كود محرك حي يمر عبر [[Prompt - ورشة بناء بتدقيق خصمي]].

## Related Notes
- [[Project - R Trader]]
- [[Meeting - 2026-07-07 - يوم الجراحة والمتحدين]]
