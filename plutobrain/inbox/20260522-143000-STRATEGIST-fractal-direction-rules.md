# قواعد اتجاه السوق — Fractal Direction Rules
**Agent**: STRATEGIST | **Task**: b7dca5f9 | **Date**: 2026-05-22

---

## المصدر
بناءً على `friday_fractals_spec.json` (RESEARCHER v1.0.0) + Bill Williams Fractals الكلاسيكي + SMC context الموجود + Footprint delta.

---

## تعريف الـ Fractal (5-bar window)

```
UP Fractal   : high[i] > max(high[i-2:i])  AND  high[i] > max(high[i+1:i+3])
DOWN Fractal : low[i]  < min(low[i-2:i])   AND  low[i]  < min(low[i+1:i+3])
مُؤكَّد بعد: إغلاق bar[i+2]
```

---

## قواعد الاتجاه (Direction Rules)

| الحالة | الشرط | الإشارة |
|--------|-------|---------|
| **BULL ↑** | `close > last_fractal_high` AND `fractal_high_age ≤ 20` AND `fractal_range ≥ 900pt` | BUY bias |
| **BEAR ↓** | `close < last_fractal_low`  AND `fractal_low_age  ≤ 20` AND `fractal_range ≥ 900pt` | SELL bias |
| **FLAT (range)** | السعر بين last_fractal_high و last_fractal_low (لا كسر) | لا تداول |
| **UNCERTAIN (conflict)** | كسر high ثم كسر low (أو العكس) في آخر 5 bars | انتظار |
| **STALE** | آخر كسر قبل > 20 bar | أهمل الإشارة |
| **RANGE_TIGHT** | `fractal_range < 900pt` (أقل من 3× spread) | لا تداول — السبريد يأكل الميزة |
| **ALLIGATOR_SLEEP** | المسافة بين خطوط الـ Alligator < 5pt | لا تداول — السوق راكد |

### ملاحظة المنطق:
- **الكسر الأحدث يكسب**: لو السعر كسر high ثم كسر low في وقت أقرب → BEAR.
- **صلاحية الإشارة**: 10 bars فقط بعد تأكيد الـ fractal. أبعد من ذلك → `fractal_signal_active=false`.

---

## دمج Fractal Direction مع SMC Bias

| Fractal Dir | SMC Bias | النتيجة | الثقة | توجيه للعمل |
|-------------|---------|---------|-------|-------------|
| BULL | BUY | **STRONG BUY** | 0.85+ | HUNTER يضع Stop Buy فوق last_fractal_high |
| BULL | BUY + CHoCH | **REVERSAL — صبر** | 0.40 | انتظر CHoCH يتأكد قبل الدخول |
| BULL | SELL | **CONFLICT** | 0.30 | لا تداول — انتظر SMC أو fractal يتوافق |
| BULL | — (neutral) | BUY | 0.60 | HUNTER BUY بحذر، lot أصغر |
| BEAR | SELL | **STRONG SELL** | 0.85+ | HUNTER يضع Stop Sell تحت last_fractal_low |
| BEAR | SELL + CHoCH | **REVERSAL — صبر** | 0.40 | انتظر CHoCH يتأكد قبل الدخول |
| BEAR | BUY | **CONFLICT** | 0.30 | لا تداول — انتظر توافق |
| BEAR | — (neutral) | SELL | 0.60 | HUNTER SELL بحذر |
| NEUTRAL | BUY | SMC-only BUY | 0.45 | ثقة منخفضة — targets ضيقة |
| NEUTRAL | SELL | SMC-only SELL | 0.45 | ثقة منخفضة — targets ضيقة |
| NEUTRAL | — | **NO TRADE** | 0.0 | تخطَّ الدورة |

---

## دمج مع Footprint Delta

| Fractal Dir | cumulative Δ | bar Δ | التفسير | التوجيه |
|-------------|-------------|-------|---------|---------|
| BULL | > 0 | > 0 | شراء مؤسسي نشط | ادعم BUY بقوة (+0.15 ثقة) |
| BULL | > 0 | < 0 | شراء مؤسسي لكن بيع قصير الأمد | BUY محافظ — SL أوسع |
| BULL | < 0 | < 0 | توزيع محتمل على القمة | **قلل الثقة −0.20**، انتظر delta انعكاس |
| BEAR | < 0 | < 0 | بيع مؤسسي نشط | ادعم SELL بقوة (+0.15 ثقة) |
| BEAR | < 0 | > 0 | بيع مؤسسي لكن شراء قصير الأمد | SELL محافظ — SL أوسع |
| BEAR | > 0 | > 0 | تراكم محتمل عند القاع | **قلل الثقة −0.20**، انتظر انعكاس |
| NEUTRAL | any | any | لا اتجاه fractal | انتظر — delta وحده لا يكفي |

---

## مصفوفة القرار النهائي (Combined Score)

```
final_confidence = fractal_base_conf
                 + smc_bonus          # +0.20 if smc_bias aligns
                 - conflict_penalty   # −0.30 if fractal ≠ smc_bias
                 + delta_bonus        # +0.15 if cumDelta aligns
                 - delta_penalty      # −0.20 if cumDelta opposes
                 + htf_bonus          # +0.15 if M15 bias aligns (from spec)
                 + alligator_bonus    # +0.10 if alligator expanding in direction

threshold_to_trade = 0.55  (من recommended_config)
```

---

## شروط الدخول الكاملة (Entry Checklist)

### BUY Setup:
1. ✅ `fractal_direction_bias = bull`
2. ✅ `fractal_high_age ≤ 20` bars
3. ✅ `fractal_signal_active = true` (أقل من 10 bars منذ التأكيد)
4. ✅ `fractal_range ≥ 900pt`
5. ✅ `smc_bias = BUY` أو SMC neutral (لا CHoCH ضد الاتجاه)
6. ✅ `alligator_expanding = bull` (اختياري لكن مقوّي)
7. ✅ `cumDelta ≥ 0` (اختياري — تأكيد مؤسسي)
8. ✅ Entry: Stop Buy عند `last_fractal_high + 1pt`
9. ✅ SL: أدنى fractal low قريب (min 300pt من entry, ≥ 1× ATR)
10. ✅ TP: entry + `fractal_range × 0.618` (على الأقل 3× spread)

### SELL Setup:
1. ✅ `fractal_direction_bias = bear`
2. ✅ `fractal_low_age ≤ 20` bars
3. ✅ `fractal_signal_active = true`
4. ✅ `fractal_range ≥ 900pt`
5. ✅ `smc_bias = SELL` أو SMC neutral
6. ✅ `alligator_expanding = bear` (اختياري)
7. ✅ `cumDelta ≤ 0` (اختياري — تأكيد مؤسسي)
8. ✅ Entry: Stop Sell عند `last_fractal_low - 1pt`
9. ✅ SL: أعلى fractal high قريب (min 300pt, ≥ 1× ATR)
10. ✅ TP: entry - `fractal_range × 0.618`

---

## تحديثات AGENT_DEFS المطلوبة لـ friday_brain.py

### STRUCTURE (النص الجديد كاملاً):
```
أنت STRUCTURE — محلل البنية. تفسّر SMC (Smart Money Concepts): BOS, CHoCH, order blocks, fair value gaps.
تؤكد أو ترفض اقتراحات HUNTER بناءً على بنية السوق.

## قراءة Fractal Direction (أولوية عالية)
بيانات السوق تحتوي الآن على: fractal_dir (bull/bear/neutral), fractal_last_high, fractal_last_low, fractal_high_age, fractal_low_age, fractal_signal_active, fractal_confidence.

قواعد الدمج:
- fractal=bull + smc_bias=BUY → STRONG BUY (ثقة عالية) — ادعم HUNTER بقوة
- fractal=bull + smc_bias=SELL → CONFLICT — قل "انتظر CHoCH أو BOS تأكيد"
- fractal=bear + smc_bias=SELL → STRONG SELL (ثقة عالية) — ادعم SELL بقوة
- fractal=bear + smc_bias=BUY → CONFLICT — قل "انتظر BOS لأعلى يؤكد"
- fractal=neutral + أي smc_bias → ثقة منخفضة، أشر لذلك

## دمج Footprint Delta:
- fractal=bull + cumDelta>0 → تأكيد مؤسسي، ادعم BUY بقوة
- fractal=bull + cumDelta<0 → تحذير توزيع، نبّه HUNTER
- fractal=bear + cumDelta<0 → تأكيد مؤسسي، ادعم SELL بقوة
- fractal=bear + cumDelta>0 → تحذير تراكم، نبّه HUNTER

## البنية الكلاسيكية (تبقى مهمة):
- BOS لأعلى → دعم BUY عند OB/FVG أو swing low القريب
- CHoCH لأسفل → دعم SELL، ابحث عن OB للبيع
- لو fractal يتعارض مع BOS/CHoCH → أعطِ الأولوية للـ CHoCH (أقوى إشارة انعكاس)
أعطِ مستوى واحد دعماً للبنية الحالية، مع إشارة واضحة للـ fractal_confidence.
```

### HUNTER (النص الجديد كاملاً):
```
أنت HUNTER — صياد المستويات. تدرس الشموع، تحدد المستويات السعرية القوية،
وتقترح أوامر pending عند هذه المستويات. تتوقع أن السعر سيلامسها.

## مستويات Fractal (أولوية أولى):
بيانات السوق تحتوي على: fractal_dir (bull/bear/neutral), fractal_last_high, fractal_last_low, fractal_high_age, fractal_low_age, fractal_signal_active.

- إذا fractal_dir=bull AND fractal_signal_active=true → Stop Buy فوق fractal_last_high + 1pt
  (السيولة فوق الـ fractal high مُحشودة — الكسر يشغّلها كوقود للصعود)
- إذا fractal_dir=bear AND fractal_signal_active=true → Stop Sell تحت fractal_last_low - 1pt
- إذا fractal_high_age أو fractal_low_age > 20 → الـ fractal قديم، ابحث عن غيره
- إذا fractal_signal_active=false → لا تدخل على هذا الـ fractal، الفرصة انتهت

## المستويات الأخرى (أولوية ثانية):
- swing high/low (خاصةً إذا تزامن مع fractal level — منطقة قوة مضاعفة)
- previous day H/L
- order blocks قريبة من fractal level

لا تخف من السبريد العالي — اقترح TP واسع يتجاوز السبريد بـ 3× على الأقل.
اختر مستويين كحد أقصى. الأولوية دائماً للمستوى الذي يتوافق فيه fractal + SMC.
```

---

## الحقول الجديدة المطلوبة في `read_market_context()`

```python
"fractal_dir"         : "bull" | "bear" | "neutral"
"fractal_last_high"   : float   # last confirmed fractal high price
"fractal_last_low"    : float   # last confirmed fractal low price
"fractal_high_age"    : int     # bars since last fractal high
"fractal_low_age"     : int     # bars since last fractal low
"fractal_signal_active": bool   # True if min(high_age, low_age) <= 10
"fractal_confidence"  : float   # 0-1 from smc_fractal_confidence
```

---

## ملخص القرار بكلمة واحدة

```
fractal=bull + smc=BUY + cumDelta>0   → STRONG_BUY   (ثقة ≥ 0.85)
fractal=bull + smc=BUY + cumDelta<0   → BUY           (ثقة 0.65)
fractal=bull + smc=SELL               → CONFLICT/WAIT (ثقة 0.30)
fractal=bear + smc=SELL + cumDelta<0  → STRONG_SELL  (ثقة ≥ 0.85)
fractal=bear + smc=SELL + cumDelta>0  → SELL          (ثقة 0.65)
fractal=bear + smc=BUY                → CONFLICT/WAIT (ثقة 0.30)
fractal=neutral                       → NO_TRADE      (ثقة < 0.45)
```
