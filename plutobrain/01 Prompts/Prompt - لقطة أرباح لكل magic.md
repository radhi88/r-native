---
type: prompt
created: 2026-07-07
updated: 2026-07-07
status: active
tags: [prompt, pnl, mt5, scoreboard]
---

# Prompt - لقطة أرباح لكل magic

**Summary:** نمط سكربت One-shot: اتصال MT5 واحد → history_deals_get → صفقات الإغلاق فقط (entry==1) → pl = profit + commission + swap → تجميع لكل magic. هذه هي «الحقيقة الأرضية» التي تُبنى عليها السبورة. [[evergreen]] [[high-value]]

## الغرض (Purpose)
كل جدل عن «مَن يربح ومَن يخسر» يُحسم بلقطة واحدة من الطرفية نفسها، لا من ادعاءات المحركات. عمود payoff في [[Workflow - محكمة السبورة (ترقية وتقاعد)]] يُشتق من هذا النمط.

## نص البرومبت (The Prompt)
```
اكتب سكربت Python واحد (one-shot، لا loop):

1. mt5.initialize() مرة واحدة فقط — ممنوع اتصال لكل عملية/لوب
   (درس IPC flood: الاتصالات المتراكمة أوقعت الأسطول كله).
2. deals = mt5.history_deals_get(from, to)
3. فلتر: خذ صفقات الإغلاق فقط — d.entry == 1
   (صفقات الفتح entry==0 ربحها صفر دائماً وتلوّث العد).
4. لكل صفقة: pl = d.profit + d.commission + d.swap
   (بدون commission وswap تكون الأرقام كذبة مجمّلة).
5. جمّع حسب d.magic واطبع جدولاً: magic | العدد | WR% | مجموع pl | payoff.
6. mt5.shutdown() في finally.
```

## متى يُستخدم (When to Use)
- بداية كل جلسة عمل: مَن نزف الليلة؟
- قبل وبعد أي قرار (تقاعد/ترقية/جراحة) — الرقم قبل وبعد هو الإثبات.
- كمدخل للخطوة 2 في [[Prompt - تشريح الصفقات (سبب الدخول وسبب الخسارة)]].

## مثال ناتج (Example Output)
- brain_trader: −$61 عبر 3 أيام ⇒ قاد إلى [[Decision - 2026-07-06 - تقاعد الرشاش وولادة R Core]].
- يد راضي اليدوية: +$50.86 اليوم بـ 83% WR ⇒ [[Customer Insight - يد راضي هي الحافة]].
- payoff الأسطول انقلب إلى 1.83 بعد [[Decision - 2026-07-07 - جراحة عدم التماثل]].

## تحذيرات
- Exness Trial يرجع trade_mode=0 (يبدو REAL) — كشف الديمو عبر اسم السيرفر Trial/Demo.
- magic 0 = يدوي؛ magics خارجية للمستخدم (2447، 20250418...) لا تُحسب على محركاتنا.

## Related Notes
- [[Internal Doc - خريطة الأسطول والحراس]] — جدول الـ magics الكامل.
- [[Workflow - محكمة السبورة (ترقية وتقاعد)]]

## Mentioned in
- [[Weekly Review - 2026-07-07]]
