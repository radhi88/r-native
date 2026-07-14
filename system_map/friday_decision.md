---
tags: [agents, decision]
---
# 🤖 friday_decision

محرّك القرار الاستشاري المحلّي ($0، يعمل دائمًا). البديل النظيف لتنسيق ٤ وكلاء.

**يكتب:** `sdk_decision.json` (انحياز + ثقة + ريجيم) → يقرأه [[gold_live]] كنكزة ±0.20
**يحاول:** Claude API (structured outputs) — لكن رصيد API = $0 → يسقط لـ**المُصنّف الحتمي** (EMA/RSI/ER) مجانًا
**مُجدوَل بـ:** sdk_scheduler.py كل 5 دقائق

## المنطق
- ليلاً ([[night-discipline]]) → WAIT بلا نداء
- نهارًا → TREND_UP/BUY · TREND_DOWN/SELL · CHOP/WAIT حسب EMA9/EMA50/RSI/ATR
- يخفّض الثقة عند النزيف (net_24h سالب)

يظهر في [[dashboards]] · [[LIVE STATUS]].
