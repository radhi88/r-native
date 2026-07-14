# Python → MT5 Strategy Tester Bridge

## الملفات

1. `Build_MT5_Tester_Profile_CSV.py`
   - يقرأ `agent_profiles.json`
   - يطلع `agent_profiles_mql5.csv`
   - يحفظه في Common Files حتى يقدر Strategy Tester يقرأه

2. `Agentic_Profiled_Grid_Tester.mq5`
   - EA للتستر داخل MT5
   - يقرأ `agent_profiles_mql5.csv`
   - يشغل نفس فكرة Grid/Hedge Stops باستخدام إعدادات Python المدربة

## طريقة التشغيل

### 1) بعد التدريب
```powershell
cd C:\Users\Radhi\MT5
.\.venv\Scripts\python.exe Build_MT5_Tester_Profile_CSV.py
```

لازم يطبع لك مسار مثل:
```text
...\MetaQuotes\Terminal\Common\Files\agent_profiles_mql5.csv
```

### 2) انسخ EA
انسخ:
```text
Agentic_Profiled_Grid_Tester.mq5
```

إلى:
```text
MQL5\Experts\
```

ثم افتحه في MetaEditor واضغط Compile.

### 3) افتح Strategy Tester
- Expert: `Agentic_Profiled_Grid_Tester`
- Symbol: يفضل تبدأ بـ `XAUUSDm`
- Timeframe: M1
- Model: Every tick based on real ticks
- Date: سنة
- Inputs:
  - `InpProfileCsv = agent_profiles_mql5.csv`
  - `InpUseCommonFiles = true`
  - `InpTradeAllProfileSymbols = false` للبداية
  - `InpSingleSymbol = XAUUSDm`
  - `InpForceChartSymbolOnly = true` للبداية
  - `InpDryRunPrintOnly = false`

بعد ما ينجح على رمز واحد، جرب:
```text
InpTradeAllProfileSymbols = true
InpForceChartSymbolOnly = false
```

## ملاحظة مهمة
Strategy Tester لا يشغل كود Python مباشرة كـ EA. الطريق الصحيح:
Python يدرّب ويصدر profiles → MQL5 EA يقرأ profiles → MT5 Strategy Tester يختبر التنفيذ.
