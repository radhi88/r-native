# أبحاث Fractals لـ XAUUSDm M1 — RESEARCHER
**Task**: 018c5755 | **Date**: 2026-05-22 | **Symbol**: XAUUSDm M1

---

## 1. Bill Williams Classic Fractals (5-bar)

### التعريف الدقيق
- **UP fractal**: `high[i] > max(high[i-2], high[i-1])` AND `high[i] > max(high[i+1], high[i+2])`
- **DOWN fractal**: `low[i] < min(low[i-2], low[i-1])` AND `low[i] < min(low[i+1], low[i+2])`
- **Period default**: left=2, right=2 (نافذة 5 شموع)

### الإعدادات
| الإعداد | القيمة | السبب |
|---|---|---|
| left bars | 2 | كلاسيكي Bill Williams |
| right bars | 2 | كلاسيكي Bill Williams |
| تأكيد الإشارة | 2 شمعة بعد fractal bar | انتظار إغلاق right bars |
| حد العمر (M1) | 20 شمعة = 20 دقيقة | بعدها يُعتبر stale |
| نافذة protected | آخر 20 fractal في الاتجاهين | للكشف عن السوينق |

### قاعدة الاتجاه — Last Broken Fractal
```
direction = BULL  إذا أغلق السعر فوق آخر fractal_high مؤكد
direction = BEAR  إذا أغلق السعر تحت آخر fractal_low  مؤكد
direction = NEUTRAL  إذا لم يُكسر أي fractal بعد
```

### قاعدة الإلغاء (Invalidation)
1. عمر الـ fractal > 20 شمعة (M1) → stale، لا يُتداول
2. تكوّن fractal جديد في الاتجاه المعاكس قبل اختراق الأول → يلغي الإشارة القديمة
3. `fractal_range` (high - low) < 3 × spread (900 pt) → لا توجد مساحة للتداول على XAUUSDm

### تحذير: High Spread
- سبريد XAUUSDm: 280-308 pt
- الحد الأدنى لـ fractal_range القابل للتداول: **900 pt** (3× سبريد)
- إذا كان الـ fractal_range أقل → تجاهل الإشارة

---

## 2. Adaptive Fractals

### المفهوم
period ديناميكي مبني على نسبة ATR بدلاً من ثابت 2.

```python
atr_ratio = ATR(14) / ATR(50)
adaptive_left = max(1, min(5, round(2 * atr_ratio)))
adaptive_right = adaptive_left  # symmetric
```

### جدول الإعدادات
| حالة السوق | ATR(14)/ATR(50) | period | تأثير |
|---|---|---|---|
| هادئ (آسيا) | ≤ 0.8 | 1 | إشارات أكثر، أكثر ضوضاء |
| عادي | 0.8 - 1.2 | 2 (classic) | متوازن |
| متقلب (London/NY) | 1.2 - 1.8 | 3 | إشارات أقل وأنظف |
| شديد التقلب | > 1.8 | 4-5 | إشارات نادرة وعالية الجودة |

### مزايا على الكلاسيكي لـ Gold M1
- يقلل الإشارات الكاذبة خلال جلسات London/NY (حيث يرتفع ATR)
- يعطي إشارات أكثر خلال الجلسة الآسيوية الهادئة
- يتكيف مع طبيعة الذهب المتقلبة

### نقطة ضعف
- يحتاج 50 شمعة على الأقل لحساب ATR(50)
- في الـ M1 قد يتغير كثيراً مما يسبب إشارات متضاربة

---

## 3. Williams Alligator + Fractals

### مكونات Alligator
| الخط | الإعداد | المعنى |
|---|---|---|
| Jaw (أزرق) | SMA(13) mid-price، offset +8 | بطيء — تيار الرئيسي |
| Teeth (أحمر) | SMA(8) mid-price، offset +5 | متوسط — قوة الاتجاه |
| Lips (أخضر) | SMA(5) mid-price، offset +2 | سريع — تأكيد مبكر |
| mid-price | (High + Low) / 2 | |

### قاعدة صحة الإشارة — المفتاح الأساسي
```
UP fractal VALID   ← fractal_high > teeth_at[i]    (يتشكل فوق الـ Teeth)
DOWN fractal VALID ← fractal_low  < teeth_at[i]    (يتشكل تحت الـ Teeth)

أي fractal يلمس أو يتقاطع مع خطوط Alligator → INVALID
```

### شروط الدخول
```
BUY:  valid_up_fractal + alligator_expanding (lips > teeth > jaw) → Stop Buy فوق fractal_high بـ 1 tick
SELL: valid_down_fractal + alligator_contracting (lips < teeth < jaw) → Stop Sell تحت fractal_low بـ 1 tick
```

### Alligator Sleeping (لا تداول)
إذا كانت الخطوط الثلاثة متشابكة (أقل من 5 pt بين أي خطين) → لا إشارة

### صلاحية نافذة الإشارة (M1)
- أمر الدخول (Stop Buy/Sell) ينتهي بعد **10 شموع** من تأكيد الـ fractal
- إذا لم يُلاس السعر للمستوى خلال 10 دقائق → يُلغى

### تحذير M1
الاستخدام على M1 يعطي إشارات كاذبة كثيرة — يجب إضافة فلتر HTF.
أفضل timeframe للـ Alligator+Fractals الخام: M30, H1.

---

## 4. Higher-Timeframe Fractal Confluence

### الهيكل الموصى به لـ XAUUSDm M1
```
Bias TF:     H1  — اتجاه عام (bullish / bearish)
Structure TF: M15 — بنية المؤشر (آخر fractal مكسور)
Entry TF:    M1  — نقطة الدخول الدقيقة
```

### قواعد الـ Confluence
```python
# تداول BUY فقط إذا:
m15_structure_bias == "bullish"   # آخر كسر على M15 كان لـ fractal_high
h1_fractal_bias   == "bullish"    # السعر فوق آخر fractal_high على H1

# تداول SELL فقط إذا:
m15_structure_bias == "bearish"
h1_fractal_bias   == "bearish"

# لا تداول:
if m15_bias != m1_signal_direction → skip
```

### نقاط القوة (Confluence Zones)
- إذا كان M15 fractal_high وM1 fractal_high ضمن **20 pt** من بعض → منطقة مقاومة قوية
- إذا كان M15 fractal_low وM1 fractal_low ضمن 20 pt → منطقة دعم قوية
- هذه المناطق تحمل weight إضافي في الـ confidence score

### أوزان Confidence
| مصدر | Weight |
|---|---|
| إشارة M1 وحدها | 30% |
| M5 alignment | +25% |
| M15 alignment | +30% |
| H1 alignment | +15% |
| Confluence zone (≤20 pt) | bonus +10% |
| **مجموع الكل** | **110% max → clamp 100%** |

---

## 5. مقارنة الأساليب لـ XAUUSDm M1 (High Spread)

| المعيار | Classic 5-bar | Adaptive | Alligator+Fractals | HTF Confluence |
|---|---|---|---|---|
| تأخر الإشارة | 2 شمعة | 1-5 شمعة | 2+ شمعة | 2+ شمعة |
| معدل الإشارات | متوسط | عالٍ/منخفض | منخفض | منخفض جداً |
| جودة الإشارة | متوسطة | جيدة | جيدة-ممتازة | ممتازة |
| تعقيد التطبيق | بسيط | متوسط | متوسط-عالي | عالٍ |
| مناسب للـ High Spread | ⚠️ يحتاج فلتر | ✅ أفضل | ✅ مناسب | ✅✅ الأفضل |
| خطر إشارات كاذبة | عالٍ | متوسط | منخفض | منخفض جداً |

---

## 6. FRIDAY Recommended Toolkit

### الـ Stack الموصى به
1. **Detector**: Classic left=3, right=3 (7-bar) — أكثر صرامة من الافتراضي
2. **Adaptive switch**: إذا ATR(14)/ATR(50) > 1.5 → left=right=3، وإلا → left=right=2
3. **Alligator filter**: Fractal يُقبل فقط فوق/تحت Teeth
4. **HTF gate**: M15 structure_bias يجب أن يوافق اتجاه M1
5. **Spread filter**: fractal_range ≥ 900 pt

### أرقام محددة للتطبيق
```
lookback_left:              2  (default), 3 (high volatility)
lookback_right:             2  (default), 3 (high volatility)
confirmation_bars:          2  (right bars must close)
signal_validity_bars:       10 (M1 = 10 minutes)
fractal_age_limit_bars:     20 (M1 = 20 minutes)
protected_window_bars:      20
spread_filter_min_pt:       900
alligator_jaw_period:       13, offset=8
alligator_teeth_period:     8,  offset=5
alligator_lips_period:      5,  offset=2
alligator_sleeping_thresh:  5.0  (pt between any two lines)
htf_confluence_zone_pt:     20
atr_short:                  14
atr_long:                   50
atr_volatility_threshold:   1.5
```

---

## المصادر

- [Tradeciety — Fractals & Alligator](https://tradeciety.com/fractals-trading-use-alligator-williams-chaos-theory)
- [FXOpen — How to Trade Williams Fractals](https://fxopen.com/blog/en/how-to-trade-with-williams-fractals/)
- [MQL5 — MQL5 Wizard Fractals (Part 56)](https://www.mql5.com/en/articles/17334)
- [MQL5 — Fractals Multi-Timeframe Indicator MT5 (Aug 2025)](https://www.mql5.com/en/blogs/post/763810)
- [RoboForex — Trading the Alligator+Fractals Strategy](https://blog.roboforex.com/blog/2020/05/20/trading-the-alligator-fractals-strategy/)
- [LiteFinance — Alligator Indicator Explained](https://www.litefinance.org/blog/for-beginners/best-technical-indicators/alligator-indicator/)
- [Pocket Option — Fractal Trading Strategies](https://pocketoption.com/blog/en/knowledge-base/trading/fractal-trading/)
- [MetaTrader5 Official Help — Fractals](https://www.metatrader5.com/en/terminal/help/indicators/bw_indicators/fractals)
- [QuantifiedStrategies — Fractal Backtest](https://www.quantifiedstrategies.com/fractal-indicator-trading-strategy/)
- [IndicatorForest — Fractal Adjustable MT5](https://indicatorforest.com/items/fractal-adjustable-indicator)
