# Handoff to Local Claude — Apply R-Native v2 on Windows + MT5

> **مَن يقرأ هذا**: نسخة Claude تشتغل على جهاز ويندوز عند Radhi، عندها صلاحيات
> ملفات + شِل + قادرة تشغّل MetaTrader 5. أنا (Claude في السحابة) بنيت كل
> الكود واختبرته (142 unit test يمر). دورك: تطبّق على الجهاز وتتحقق على بيانات
> حية. لا تكتب كود جديد إلا إذا اكتشفت bug فعلي — مهمتك الأساسية تفعيل + اختبار.

> **All paths use `C:\Users\Radhi\` and `XAUUSDm` because that's the project's
> hard-coded broker setup. Adjust if Radhi's MT5 install differs.**

---

## 0 · Quick TL;DR (إذا تستعجل)

```powershell
# الفرع
cd C:\Users\Radhi\path\to\r-native    # ← غيّر للمسار الصحيح
git fetch origin
git checkout claude/genome-calculation-error-4NgXI
git pull

# Python
pip install MetaTrader5 numpy matplotlib flask requests

# تأكد كل شي مظبوط
python tests/run_all.py                   # ← لازم 142/142 ✓

# شغّل
python brain_server.py                    # ← يفتح http://localhost:5055
```

ثم افتح في المتصفح:
- http://localhost:5055/r/indicators  (لوحة المؤشرات الـ11)
- http://localhost:5055/r/strategies   (بناء استراتيجية بالذكاء)
- http://localhost:5055/r/analyze       (تحليل الشارت)
- http://localhost:5055/r/monitor       (المتابعة المباشرة)

---

## 1 · Project structure (ما هو موجود)

### 📂 الـbranch: `claude/genome-calculation-error-4NgXI`
- **22 commit** على الفرع
- **6,800+ سطر كود** جديد
- **142/142 unit test** يمر

### 📋 الاستراتيجيات (2)

| # | الاسم | الملف | الوصف |
|---|---|---|---|
| 1 | **Stoch Reversion** (Gold M3) | `strategies/stoch_reversion.py` | SELL عند Stoch %D≥85/90 · BUY عند 10/15 · TP عند 50 |
| 2 | **Supply Zone + COT** | `strategies/supply_zone_cot.py` | smc_engine OB zones مُفلتر بـCFTC weekly data |

### 📊 المؤشرات الـ11 (لوحة Pipflow في `live_indicators.py`)

```
SMA Cross · EMA Cross · MACD · RSI · Supertrend · Stochastic
Bollinger · Awesome Osc · Parabolic SAR · CCI · ADX
```

### 🎯 SMC detectors (`smc_engine.py` — 8 كاشفات)

```
detect_pivots · detect_bos · detect_choch · detect_sweep
detect_idm · detect_ob · detect_fvg · detect_liquidity_pools
```

### 🧬 Genome decision units (`genome_signal.py`)

```
29 Signal Evaluators  (منها 6 SMC: ob/fvg/bos/choch/liq_sweep/idm)
14 Filter Evaluators  (منها 3 SMC: fresh_only/htf_alignment/idm_required)
15 Bias Evaluators
─────────────
58 unit وحدة قرار للجينوم
```

### ⚙ Infrastructure (لا تلمسها — يستخدمها كل شي)

```
brain_server.py          — Flask + MT5 bridge (5055)
chart_drawings.py        — رسم SMC zones على MT5
smc_neural.py            — quality scorer (heuristic + قابل للتدريب)
sl_tp_resolver.py        — SL/TP مربوط بـSMC structure
agent_governance.py      — rate limits + drawdown halt
genome_rollback.py       — auto-revert لو الـgenome يخسر
combo_fitness.py         — يتعلم من كل صفقة
hall_of_fame.py          — SMC lane + classic lane
agents/smc_narrator.py   — شرح عربي لكل صفقة
```

### 🔧 Tools (سكربتات منفصلة)

```
tools/render_trade_chart.py        — PNG لصفقاتك مع P/L
tools/export_mt5_bars.py            — يحفظ M3 ذهب في JSON
tools/backtest_stoch_on_live_mt5.py — يشغّل Stoch backtest
```

### 💎 MQ5 EAs (في `mql5_templates/`)

```
Stoch_Reversion_M3.mq5    — EA الاستراتيجية الأولى، جاهز للترجمة
DrawingRenderer.mqh        — include file لرسم SMC zones من brain.json
r_strategy_template.mq5   — قالب EA يتولد من genomes
```

---

## 2 · Setup checklist (افعل بالترتيب)

### 2.1 · Python dependencies

```powershell
pip install MetaTrader5 numpy matplotlib flask requests
```

تحقق:
```powershell
python -c "import MetaTrader5; print('MT5 ok')"
python -c "import numpy, matplotlib, flask; print('deps ok')"
```

### 2.2 · MT5 terminal

1. MT5 شغّال ومسجّل دخول على حساب broker.
2. **Tools → Options → Expert Advisors**:
   - ✅ Allow Algo Trading
   - ✅ Allow DLL imports
3. **View → Market Watch**: تأكد إن `XAUUSDm` ظاهر (right-click → Show All لو مخفي)
4. **File → Open Data Folder** ← هذا المسار اللي الكود يكتب فيه. اكتبه:
   - عادة: `C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\<ID>\`
   - لو الكود مكتوب فيه `C:\Users\Radhi\MT5\data\r_native\`، أنشئ الفولدر يدوياً:
     ```powershell
     mkdir C:\Users\Radhi\MT5\data\r_native\agents
     mkdir C:\Users\Radhi\MT5\data\r_native\strategies
     mkdir C:\Users\Radhi\MT5\data\r_native\symbol_configs
     mkdir C:\Users\Radhi\MT5\data\r_native\decision_log
     mkdir C:\Users\Radhi\MT5\data\r_native\models
     ```

### 2.3 · LLM backend (اختياري لكن موصى به)

**خيار A — Ollama محلي (مجاني):**
```powershell
# https://ollama.com/download
ollama pull qwen2.5:7b
# تأكد إنه شغّال:
curl http://127.0.0.1:11434/api/tags
```

**خيار B — Claude API key:**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# اختبر:
python -c "from r_native.agents.llm import ask; print(ask('hi','be brief'))"
```

بدون LLM، الـ"Polish with AI" يستخدم fallback افتراضي + الـSMC narrator يكتب template عربي.

### 2.4 · Branch + Tests

```powershell
cd C:\Users\Radhi\<r-native-folder>
git fetch origin
git checkout claude/genome-calculation-error-4NgXI
git pull

python tests/run_all.py
```

**يجب أن يظهر:** `✓ all tests passed` و `142` OK lines.

لو فشل اختبار، **توقف وأبلغ المستخدم** — لا تكمّل.

---

## 3 · ما لازم تطبّق (بالترتيب)

### Step 1 · شغّل brain_server وتحقّق

```powershell
python brain_server.py
```

افتح في المتصفح:
```
http://localhost:5055/r/indicators?symbol=XAUUSDm&tf=15m
```

**التحقق:** يجب تشاهد:
- 11 indicator status بـBULLISH/BEARISH/NEUTRAL
- Aggregate signal (LONG/SHORT/NONE)
- Performance KPIs (إن في صفقات تاريخية)

لو فشل → تحقق إن MT5 شغّال + symbol ظاهر في Market Watch.

### Step 2 · ثبّت Stoch Reversion EA

1. افتح MetaEditor (F4 من MT5)
2. File → Open Data Folder → MQL5 → Experts
3. انسخ هذا الملف:
   ```
   من: mql5_templates/Stoch_Reversion_M3.mq5
   إلى: <MT5 Data>\MQL5\Experts\
   ```
4. في MetaEditor: افتحه، اضغط **F7**
   - يجب يظهر: `0 errors, 0 warnings`
5. في MT5: Ctrl+N (Navigator) → Expert Advisors → Stoch_Reversion_M3
6. اسحب على شارت **XAUUSDm M3**
7. في الـdialog:
   - ✅ Allow algo trading
   - راجع inputs (defaults صحيحة):
     ```
     OB_Heavy=90  OB_Light=85  OS_Heavy=10  OS_Light=15  Midline=50
     Lot=0.01  MaxTrades=2  UseSL=true  AtrSlMult=2.5
     Magic=20260605
     ```
   - OK
8. الزاوية اليمنى العليا تصير ☺️ = EA شغّال

### Step 3 · ثبّت Drawing Renderer (لرسم SMC zones)

1. حمّل `JAson.mqh`:
   ```
   https://www.mql5.com/en/code/13663
   احفظه في: <MT5 Data>\MQL5\Include\
   ```
2. انسخ `mql5_templates/DrawingRenderer.mqh` إلى نفس المجلد `MQL5\Include\`
3. (اختياري للاندماج الكامل) عدّل `FRIDAY_Brain_Executor.mq5` لو موجود
   لإضافة:
   ```mql5
   #include <DrawingRenderer.mqh>
   #include <JAson.mqh>

   int OnInit() {
      DrawingRenderer_Init(_Symbol);
      EventSetTimer(1);
      return INIT_SUCCEEDED;
   }
   void OnTimer() {
      string json = ReadBrainJsonFile();
      if (json == "") return;
      CJAVal root;
      if (!root.Deserialize(json)) return;
      DrawingRenderer_Render(root["drawings"].Serialize());
   }
   ```

### Step 4 · Export بيانات MT5 وشغّل backtest

```powershell
# 1. اسحب 8000 شمعة M3 من MT5
python tools/export_mt5_bars.py --symbol XAUUSDm --bars 8000

# المتوقع:
# ✓ wrote data/gold_m3_live.json
#   bars: 8000  span: 2026-MM-DD -> 2026-MM-DD
#   broker: <broker_name>  contract: 100.0

# 2. شغّل Stochastic backtest على بياناتك
python tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --out gold_real.png

# 3. شغّل نسخة بدون SL (طبق screenshot الأصل)
python tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --use-sl 0 --out gold_no_sl.png
```

أرسل لـRadhi الـPNGs + ملخص الـterminal output.

### Step 5 · CFTC COT data (للاستراتيجية الثانية)

```powershell
# ادخل https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed
# نزّل: fut86_25.zip   (Legacy futures-only, 2025)
# استخرج fut86_25.txt إلى: data/cot_gold_2025.txt

# اختبره
python -c "
import sys; sys.path.insert(0, '.')
from strategies.supply_zone_cot import load_cot_weekly, cot_regime
rows = load_cot_weekly('data/cot_gold_2025.txt', 'GOLD - COMMODITY EXCHANGE INC.')
print(f'Loaded {len(rows)} weeks. Latest:', rows[-1]['date'])
print(f'  comm_idx={rows[-1][\"comm_idx\"]:.1f}  noncomm_idx={rows[-1][\"noncomm_idx\"]:.1f}')
print(f'  current regime: {cot_regime(rows[-1][\"comm_idx\"], rows[-1][\"noncomm_idx\"])}')
"
```

### Step 6 · Combined Supply Zone + COT backtest

اكتب سكربت بسيط (لا تنسخه إلى الـrepo — مؤقت في `/tmp` أو cwd):

```python
# backtest_supply_cot.py
import json, sys
sys.path.insert(0, '.')
from strategies.supply_zone_cot import load_cot_weekly, backtest

bars = json.load(open('data/gold_m3_live.json'))['bars']
cot = load_cot_weekly('data/cot_gold_2025.txt', 'GOLD - COMMODITY EXCHANGE INC.')

for name, cfg in [
    ("A · no COT", dict(require_cot=False)),
    ("B · COT gating", dict(require_cot=True)),
    ("C · COT + tight SL", dict(require_cot=True, atr_sl_mult=1.0)),
]:
    r = backtest(bars, cot, **cfg)
    s = r['summary']
    print(f"=== {name} ===  trades={s['trades']} WR={s['win_rate']}% PF={s['profit_factor']} net=${s['net_pnl']}")
```

شغّله، أرسل النتائج لـRadhi.

---

## 4 · UI Dashboards — افتحها وخلّي Radhi يراها

| الصفحة | الـURL | تستخدم |
|---|---|---|
| المؤشرات + الأداء | http://localhost:5055/r/indicators | live MT5 |
| بناء استراتيجية بالذكاء | http://localhost:5055/r/strategies | Claude/Ollama |
| تحليل الشارت | http://localhost:5055/r/analyze | Claude/Ollama + MT5 |
| المتابعة المباشرة | http://localhost:5055/r/monitor | live MT5 |

---

## 5 · أوامر تشخيص سريعة

```powershell
# تحقّق MT5 يستجيب
python -c "import MetaTrader5 as mt5; mt5.initialize(); print(mt5.account_info())"

# تحقّق الـsymbols
python -c "import MetaTrader5 as mt5; mt5.initialize(); print([s.name for s in mt5.symbols_get('*XAU*')])"

# عدّ صفقات الـEA المفتوحة (Magic 20260605)
python -c "
import MetaTrader5 as mt5; mt5.initialize()
pos = mt5.positions_get() or []
mine = [p for p in pos if p.magic == 20260605]
print(f'{len(mine)} R-Native positions open')
for p in mine: print(f'  #{p.ticket} {p.symbol} {p.type} {p.volume}@{p.price_open} P/L=${p.profit:+.2f}')
"

# آخر 5 صفقات مغلقة
python -c "
import MetaTrader5 as mt5
from datetime import datetime, timedelta
mt5.initialize()
deals = mt5.history_deals_get(datetime.now()-timedelta(days=7), datetime.now())
mine = [d for d in deals if d.magic == 20260605 and d.entry == 1]
for d in mine[-5:]:
    print(f'  {d.symbol} P/L=\${d.profit:+.2f}')
"
```

---

## 6 · ما لا تفعله أبداً

1. **لا تشغّل live trading بدون إذن صريح من Radhi.** الـEA افتراضياً `Allow algo trading` يتطلب موافقة. أكّد كل شي على demo أولاً.
2. **لا تحذف أو تعدّل** الملفات في `friday_v3/algory/` بدون اختبار شامل — هذا الكود الـlegacy المتشابك مع MT5 bridge.
3. **لا تكتب كود لـrepo** إلا إذا اكتشفت bug فعلي. مهمتك التطبيق + الاختبار + التقرير.
4. **لا تنشر pull request** أو merge إلى main بدون إذن.
5. **لا تكتب على branch `main`** — كل العمل على `claude/genome-calculation-error-4NgXI`.
6. **لا تخبر Radhi إن شي شغّال** قبل ما تتأكد بالاختبار الفعلي (تجنّب hallucinations).

---

## 7 · ما تفعله إذا اكتشفت مشكلة

ترتيب:
1. **حدّد بالضبط** أي ملف، أي سطر، أي رسالة خطأ
2. **اعرض على Radhi قبل الإصلاح** — مهم لأن بعض المسارات Hard-coded
3. لو الإصلاح بسيط (typo, missing path, version skew): اعمل commit صغير بعد إذنه
4. لو الإصلاح معماري: **توقف**، اكتب الاكتشاف، خلّي القرار له

---

## 8 · ملفات وثائق مرجعية في الـrepo

| الملف | لماذا تقرأه |
|---|---|
| `docs/smc/00_VISION.md` | الرؤية الكاملة + الـ8 phases |
| `docs/smc/01_SMC_ALGORITHMS.md` | تعريف SMC patterns الرياضي |
| `docs/smc/02_DRAWING_BRIDGE.md` | كيف يُرسم على MT5 |
| `docs/smc/03_GENOME_INTEGRATION.md` | كيف تتعلم الجينات SMC |
| `docs/smc/04_AGENTIC_AI_LAYERS.md` | Agentic AI framework mapping |
| `docs/PIPFLOW_INTEGRATION.md` | الـ4 ميزات Pipflow + endpoints |
| `docs/STOCH_REVERSION_EA.md` | دليل تركيب الـEA الأول |

---

## 9 · الأرقام التي يجب تأكيدها على Radhi

عند الانتهاء، اكتب له تقريراً يحوي:

```
□ python tests/run_all.py         : ___ / 142 passed
□ brain_server.py boots           : YES / NO
□ /r/indicators يطلع 11 indicators : YES / NO
□ Stoch_Reversion_M3.mq5 compiled  : 0 err / N err
□ EA يطبع OPEN/CLOSE في Experts tab : YES / NO
□ MT5 export bars                  : ___ bars saved
□ Stoch backtest على بياناته       : trades=__ WR=__% PF=__ net=$__
□ CFTC COT loaded                  : ___ weeks
□ Supply Zone + COT backtest       : trades=__ WR=__% PF=__ net=$__
□ أي errors؟                       : (وصفها بدقة)
```

ابعث له هذا الجدول + 3 PNGs (Stoch with SL · Stoch no-SL · Supply+COT).

---

## 10 · سياق Radhi (لتفهم المسار اللي وصلنا له)

- بنينا النظام عبر **22 commits** على الفرع
- المشروع أصلاً **Genome trading + R-Native v2** — استراتيجيات جينية تتطور
- في الجلسة الحالية أضفنا:
  - SMC engine (Phase 1-5)
  - 4 ميزات Pipflow (Prompt Trading, Dashboards, Chart AI, Live Monitor)
  - استراتيجيتا Stoch Reversion + Supply Zone + COT
- Radhi يجرّب على **Gold (XAUUSDm)** بـ**0.01 lot demo**
- مشكلة سحابة Anthropic: لا تصل لـMT5 ولا CFTC، فطلب منك تطبّق على جهازه
- يستحق صراحة: حتى الـbacktests على البيانات الاصطناعية، الـStoch Reversion PF ≈ 1.0 (محايد). لا توعد بأرباح.

---

**انتهى الـhandoff.** ابدأ من Section 0 وسر بالترتيب. لو وقعت في أي شي غير واضح، اسأل Radhi مباشرة — لا تخمّن.
