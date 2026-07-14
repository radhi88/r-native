# R-Native — FRIDAY Algorithmic Trading System (private)

نظام تداول خوارزميّ **محلّي بالكامل** فوق MetaTrader 5 (Python). الحافّة ليست التنبّؤ —
بل **الانضباط + الحجم + الإدارة + الكلفة**.

> **هذا المستودع = العقل** (كود + أفكار + وثائق). **جهازك = الجسد** (`data/`، `.env`،
> `api_keys.json`، حالة الصفقات) — لا تُرفع أبداً. حدّثه بأمر واحد: `python sync_to_repo.py --push`.

📊 الدوسيه التفاعليّ: https://claude.ai/code/artifact/ad2399ac-0ab6-459b-a0b5-fcc19b6139e5

## الطبقات
- **Logic** — `friday_v3/algory/` (r_executor · trade_gate · r_levels · indicator_matrix ·
  r_learning · r_multi_symbol) + `r_native/` + محرّكات الجذر (`brain_server.py` :5055 ·
  `watchdog_guard.py` · gold_level_sentinel · news_straddle · portfolio_maestro · market_sweeper)
- **Roadmap** — `r_desktop/ROADMAP.md` · `MATURITY_ROADMAP.md` (M0→M5، $500→$1000)
- **Workflow** — `workflow/` (تطوّر مجدول) · `CLAUDE.md`
- **Endpoints** — `ENDPOINTS.md` (54 واجهة `/api/r/*`)
- **AI onboarding** — `AI_CONTEXT.md`

## المعمارية
```
MT5 <-> جسر mt5 مشترك <-> brain_server(:5055) <-> محرّكات(magics) <-> واجهات/مدراء
                                  ^ watchdog_guard
```

## أمان
DEMO فقط · لوت 0.01 · سقف يوميّ $10 · حدّ 3 صفقات · kill_switch · حظر ليليّ · بوّابة إثبات
(n≥30, t≥2, net>0). البيانات الحيّة والأسرار خارج المستودع.
