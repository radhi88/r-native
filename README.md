# R-Native — FRIDAY Algorithmic Trading System

نظام تداول خوارزميّ **محلّي بالكامل** فوق MetaTrader 5 (Python). جوهره ليس التنبّؤ بالاتجاه —
بل **فرض الانضباط، ضبط الحجم، إدارة الصفقة، وتقليل الكلفة**.

> **Mirror scope (نسخة كود ووثائق كاملة):** كامل كود مشروع FRIDAY/R-native ووثائقه.
> مُستبعَد عمداً: `data/` (17GB حالة حيّة)، `logs/`، `dist/`، `.venv/`، `.env` (أسرار)،
> والمشروع غير المرتبط `OpenJarvis/`. رقم الحساب مُنقّح. النمط الحاليّ **DEMO فقط**.

📊 **دوسيه المشروع التفاعليّ:** https://claude.ai/code/artifact/ad2399ac-0ab6-459b-a0b5-fcc19b6139e5

## الأطروحة الصادقة
بعد 20+ دراسة walk-forward: **لا حافّة تنبّؤيّة قابلة للتداول**. الحافّة في التنفيذ لا التوقّع:
- ✅ **الانضباط**: يدويّ 453 صفقة 72%WR؛ باستبعاد الليل → +$904 PF 3.36
- ✅ **الحجم** (أقوى رافعة): ذهب ≥0.2 لوت = −$45.6k مقابل <0.2 لوت = +$30.5k
- ✅ **الإدارة**: دع الرابح يجري، اخرج على انعكاس واضح، لا تكديس على الأحمر
- ⚠️ **الكلفة** (عنق الزجاجة): سبريد BTC > الحافّة → تاجر نادراً

## الطبقات
- **Logic** — `friday_v3/algory/` (r_executor · trade_gate · r_levels · indicator_matrix ·
  r_learning · r_multi_symbol) + `r_native/` + محرّكات الجذر (brain_server · watchdog_guard ·
  gold_level_sentinel · news_straddle · portfolio_maestro · profit_harvester · market_sweeper …)
- **Roadmap** — `r_desktop/ROADMAP.md` (30/48) · `MATURITY_ROADMAP.md` (M0→M5, $500→$1000)
- **Workflow** — `workflow/r-factory-evolution.SKILL.md` (تطوّر مجدول كلّ 15د) · `CLAUDE.md`
- **Endpoints** — `ENDPOINTS.md` (54 واجهة `/api/r/*` على :5055)
- **Variants** — `r_native_v2/` · `r-native-pipflow/` · `ai-geometric-agentic-desk/` · `plutobrain/`

## المعمارية
```
MT5 <-> جسر mt5 مشترك <-> brain_server(:5055) <-> محرّكات(magics) <-> واجهات/مدراء
                                  ^ watchdog_guard (يحرس الكلّ)
```

## حواجز الأمان
DEMO فقط · لوت 0.01 · سقف يوميّ $10 · حدّ 3 صفقات · kill_switch · master_floor · حارس هامش
200% · حارس حجم 2% · حظر ليليّ · بوّابة إثبات (n≥30, t≥2, net>0) · حارس ضدّ التحوّط.

## تشغيل (مرجعيّ — DEMO)
```bash
python brain_server.py                    # العقل :5055
python -m friday_v3.algory.r_executor     # التنفيذ
python watchdog_guard.py                  # الحارس
```
> ⚠️ لا مال حقيقيّ. للأرشفة والمراجعة. البيانات الحيّة والأسرار خارج المستودع.
