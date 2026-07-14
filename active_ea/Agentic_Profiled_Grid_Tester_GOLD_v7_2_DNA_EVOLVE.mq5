//+------------------------------------------------------------------+
//| Agentic_Profiled_Grid_Tester_GOLD_v7_2_DNA_EVOLVE.mq5             |
//|                                                                  |
//| ✦ SELF-EVOLVING DNA SYSTEM ✦                                     |
//| - كل اختبار = جيل (Generation)                                  |
//| - يحسب Fitness Score من النتائج                                  |
//| - يحفظ أفضل DNA في ملف gold_dna_memory.csv                      |
//| - الجيل التالي يبدأ من أفضل DNA + طفرة ذكية (Mutation)          |
//| - يعرض تقرير التطور في كل بداية                                  |
//+------------------------------------------------------------------+
#property strict
#property version "7.20"

#include <Trade/Trade.mqh>

CTrade trade;

//====================================================================
// DNA STRUCT — كل المعاملات القابلة للتطور
//====================================================================
struct AgentDNA
{
   // --- Grid & Gap ---
   int    ExtraTightGapPoints;       // [3  .. 50]
   int    ModifyStepPoints;          // [1  .. 5]

   // --- Basket Safety ---
   double BasketTakeProfitMoney;     // [0.5 .. 20.0]
   double BasketStopLossMoney;       // [3.0 .. 50.0]
   double BasketLockStartMoney;      // [1.0 .. 20.0]
   double BasketLockGiveBackMoney;   // [0.5 .. 10.0]

   // --- Cooldowns ---
   int    CooldownAfterTPMinutes;    // [1  .. 30]
   int    CooldownAfterSLMinutes;    // [5  .. 60]
   int    CooldownAfterLossMinutes;  // [10 .. 120]

   // --- Lot Adaptation ---
   double LotReductionFactor;        // [0.1 .. 0.9]
   double MinLotFactor;              // [0.1 .. 0.5]
   double RecoveryLotStep;           // [0.05 .. 0.5]

   // --- Grid Adaptation ---
   double GridWidenFactor;           // [1.0 .. 3.0]
   double MaxGridFactor;             // [1.5 .. 8.0]
   double RecoveryGridStep;          // [0.05 .. 0.5]

   // --- Win Streak Recovery ---
   int    WinsToRecover;             // [1  .. 10]

   // --- ATR ---
   int    AtrBars;                   // [10 .. 100]

   // --- Fitness (يُحسب لاحقاً) ---
   double fitness;
   int    generation;
   double profit_factor;
   double max_drawdown_pct;
   double total_trades;
   double net_profit;
};

//====================================================================
// DNA Memory Record (للحفظ والقراءة)
//====================================================================
#define DNA_MEMORY_FILE  "gold_dna_memory.csv"
#define DNA_MAX_RECORDS  100
#define DNA_ELITE_COUNT  5          // أفضل 5 DNA تُستخدم للتزاوج
#define DNA_MUTATION_RATE 0.25      // احتمال تطفير كل جين

//====================================================================
// Inputs
//====================================================================
input string InpProfileCsv                    = "agent_profiles_mql5.csv";
input bool   InpUseCommonFiles                = true;

input string InpGoldSymbol                    = "XAUUSDm";
input bool   InpForceChartSymbolOnly          = true;

input bool   InpAutoTrade                     = true;
input bool   InpDryRunPrintOnly               = false;

input int    InpTimeframe                     = PERIOD_M1;

// DNA Evolution Controls
input bool   InpUseDNAEvolution               = true;      // تفعيل نظام DNA
input bool   InpDNAMutateFromBest             = true;      // ابدأ من أفضل DNA
input double InpDNAMutationStrength           = 0.15;      // قوة الطفرة (0.05-0.5)
input bool   InpDNAUseElitism                 = true;      // احتفظ بالنخبة
input bool   InpDNAVerboseReport              = true;      // اطبع تقرير DNA

// Fallback DNA (تُستخدم إن لم يوجد ملف ذاكرة)
input int    InpExtraTightGapPoints           = 500;
input int    InpModifyStepPoints              = 1;
input bool   InpUseStopReversePair            = true;
input bool   InpManagePairEveryTick           = true;
input bool   InpOneWayTrailOnly               = true;      // ✦ SL يتحرك في اتجاه واحد فقط (الربح) — يمنع Chop Loop
input int    InpMinHoldSeconds                = 30;        // ✦ أدنى وقت للصفقة قبل السماح بتعديل SL
input int    InpChopMaxFlipsPerMin            = 4;         // ✦ أقصى انعكاسات في الدقيقة قبل cooldown إجباري
input bool   InpPairPositionSLWithPending     = true;
input bool   InpPendingHasNoOwnSLTP           = true;
input bool   InpDeleteSameSidePending         = true;
input bool   InpDeleteDuplicates              = true;
input int    InpMaxOpenPositionsPerSymbol     = 2;
input bool   InpResolveHedgeImmediately       = true;
input bool   InpResolveHedgeKeepLatest        = true;

input bool   InpUseBasketTakeProfit           = true;
input double InpBasketTakeProfitMoney         = 2.00;
input bool   InpUseBasketStopLoss             = true;
input double InpBasketStopLossMoney           = 8.00;
input bool   InpUseBasketEquityLock           = true;
input double InpBasketLockStartMoney          = 7.00;
input double InpBasketLockGiveBackMoney       = 2.50;

// Confidence Boosts — تجربة محكومة: ارفع الربح/اللوت فقط مع اتجاه مؤكد
input bool   InpUseConfidenceBasketTPBoost    = true;
input int    InpConfidenceEntryMin            = 55;
input int    InpConfidenceAvoidMax            = 25;
input int    InpConfidenceAdxMin              = 20;
input int    InpConfidenceSigMin              = 45;
input double InpConfidenceTPBoostFactor       = 1.60;
input double InpConfidenceTPMaxFactor         = 2.50;
input bool   InpUseConfidenceLotBoost         = true;
input int    InpConfidenceLotMin              = 70;
input double InpConfidenceLotBoostFactor      = 1.20;
input double InpConfidenceLotMaxFactor        = 1.50;

input bool   InpUseFallbackInitialSLTP         = false;
input int    InpFallbackSLPoints              = 5000;
input int    InpFallbackTPPoints              = 5000;

input int    InpMinSecondsBetweenOrders       = 0;
input int    InpDeviationPoints               = 50;
input int    InpExtraStopBufferPoints         = 3;

input bool   InpUseSpreadFilter               = false;
input double InpMaxSpreadToAtrRatioOverride   = 0.00;
input bool   InpUseBlockedHours               = false;
input string InpBlockedHours                  = "0,8,9,11,12,20";
input bool   InpUseFridayCloseFilter          = true;
input int    InpFridayStopHour                = 20;

input int    InpCooldownAfterBasketTPMinutes  = 3;
input int    InpCooldownAfterBasketSLMinutes  = 20;
input int    InpCooldownAfterLargeLossMinutes = 30;

input double InpLargeSingleLossMoney          = 10.00;
input double InpLotReductionFactor            = 0.50;
input double InpMinLotFactor                  = 0.25;
input double InpGridWidenFactor               = 1.25;
input double InpMaxGridFactor                 = 4.0;

input bool   InpRecoverAfterWins              = true;
input int    InpWinsToRecover                 = 2;
input double InpRecoveryLotStep               = 0.15;
input double InpRecoveryGridStep              = 0.25;

input string InpInitialDirection              = "AUTO";
input bool   InpVerboseLogs                   = true;

//====================================================================
// Structs
//====================================================================
struct AgentProfile
{
   string symbol;
   bool   enabled;
   ulong  magic;
   string asset_class;
   double base_lot;
   double atr_grid_multiplier;
   double atr_trailing_multiplier;
   double spread_grid_multiplier;
   double stop_loss_atr_multiplier;
   double take_profit_atr_multiplier;
   double max_spread_to_atr_ratio;
};

struct AgentState
{
   datetime last_bar_time;
   datetime cooldown_until;
   datetime last_order_time;
   double   lot_factor;
   double   grid_factor;
   double   basket_peak_profit;
   int      closed_win_streak;
   int      closed_loss_streak;
   ulong    last_processed_deal;

   // Chop Detection
   int      chop_flip_count;
   datetime chop_window_start;
   datetime last_position_open_time;
};

struct IndicatorSnapshot
{
   double atr;
   double rsi;
   double adx;
   double macd;
   double mfi;
   double volp;
   double spr;
   double dchHi;
   double dchLo;
   double dchPos;
   double demandDist;
   double supplyDist;
   int    demand;
   int    supply;
   int    trend;
   double sig;
   double entryScore;
   double avoidScore;
};

AgentProfile g_profile;
AgentState   g_state;
AgentDNA     g_dna;
bool         g_loaded = false;
int          g_current_generation = 1;

// ── Real-Time Export ──
int          g_rt_bar_count  = 0;
double       g_rt_peak_bal   = 0.0;
bool         g_rt_history_started = false;

//====================================================================
// ════════════════════════════════════════
// DNA EVOLUTION ENGINE
// ════════════════════════════════════════
//====================================================================

// --- حدود الجينات ---
struct DNABounds
{
   double minVal;
   double maxVal;
};

AgentDNA DefaultDNA()
{
   AgentDNA d;
   d.ExtraTightGapPoints     = InpExtraTightGapPoints;
   d.ModifyStepPoints        = InpModifyStepPoints;
   d.BasketTakeProfitMoney   = InpBasketTakeProfitMoney;
   d.BasketStopLossMoney     = InpBasketStopLossMoney;
   d.BasketLockStartMoney    = InpBasketLockStartMoney;
   d.BasketLockGiveBackMoney = InpBasketLockGiveBackMoney;
   d.CooldownAfterTPMinutes  = InpCooldownAfterBasketTPMinutes;
   d.CooldownAfterSLMinutes  = InpCooldownAfterBasketSLMinutes;
   d.CooldownAfterLossMinutes= InpCooldownAfterLargeLossMinutes;
   d.LotReductionFactor      = InpLotReductionFactor;
   d.MinLotFactor            = InpMinLotFactor;
   d.RecoveryLotStep         = InpRecoveryLotStep;
   d.GridWidenFactor         = InpGridWidenFactor;
   d.MaxGridFactor           = InpMaxGridFactor;
   d.RecoveryGridStep        = InpRecoveryGridStep;
   d.WinsToRecover           = InpWinsToRecover;
   d.AtrBars                 = 40;
   d.fitness                 = 0.0;
   d.generation              = 0;
   d.profit_factor           = 0.0;
   d.max_drawdown_pct        = 100.0;
   d.total_trades            = 0.0;
   d.net_profit              = 0.0;
   return d;
}

// --- DNA → CSV سطر واحد ---
string DNAToCSV(const AgentDNA &d)
{
   return IntegerToString(d.generation)             + "," +
          DoubleToString(d.fitness, 4)              + "," +
          DoubleToString(d.profit_factor, 4)        + "," +
          DoubleToString(d.max_drawdown_pct, 4)     + "," +
          DoubleToString(d.total_trades, 0)         + "," +
          DoubleToString(d.net_profit, 2)           + "," +
          // Genes
          IntegerToString(d.ExtraTightGapPoints)    + "," +
          IntegerToString(d.ModifyStepPoints)       + "," +
          DoubleToString(d.BasketTakeProfitMoney,2) + "," +
          DoubleToString(d.BasketStopLossMoney,2)   + "," +
          DoubleToString(d.BasketLockStartMoney,2)  + "," +
          DoubleToString(d.BasketLockGiveBackMoney,2)+"," +
          IntegerToString(d.CooldownAfterTPMinutes) + "," +
          IntegerToString(d.CooldownAfterSLMinutes) + "," +
          IntegerToString(d.CooldownAfterLossMinutes)+"," +
          DoubleToString(d.LotReductionFactor,3)    + "," +
          DoubleToString(d.MinLotFactor,3)          + "," +
          DoubleToString(d.RecoveryLotStep,3)       + "," +
          DoubleToString(d.GridWidenFactor,3)       + "," +
          DoubleToString(d.MaxGridFactor,3)         + "," +
          DoubleToString(d.RecoveryGridStep,3)      + "," +
          IntegerToString(d.WinsToRecover)          + "," +
          IntegerToString(d.AtrBars);
}

#include <GridDNA_Common.mqh>   // PlutoBrain: shared Grid helpers

// --- CSV سطر → DNA ---
bool CSVToDNA(string line, AgentDNA &d)
{
   string parts[];
   int n = StringSplit(line, ',', parts);
   if(n < 23)
      return false;

   d.generation              = (int)StringToInteger(parts[0]);
   d.fitness                 = StringToDouble(parts[1]);
   d.profit_factor           = StringToDouble(parts[2]);
   d.max_drawdown_pct        = StringToDouble(parts[3]);
   d.total_trades            = StringToDouble(parts[4]);
   d.net_profit              = StringToDouble(parts[5]);
   d.ExtraTightGapPoints     = (int)StringToInteger(parts[6]);
   d.ModifyStepPoints        = (int)StringToInteger(parts[7]);
   d.BasketTakeProfitMoney   = StringToDouble(parts[8]);
   d.BasketStopLossMoney     = StringToDouble(parts[9]);
   d.BasketLockStartMoney    = StringToDouble(parts[10]);
   d.BasketLockGiveBackMoney = StringToDouble(parts[11]);
   d.CooldownAfterTPMinutes  = (int)StringToInteger(parts[12]);
   d.CooldownAfterSLMinutes  = (int)StringToInteger(parts[13]);
   d.CooldownAfterLossMinutes= (int)StringToInteger(parts[14]);
   d.LotReductionFactor      = StringToDouble(parts[15]);
   d.MinLotFactor            = StringToDouble(parts[16]);
   d.RecoveryLotStep         = StringToDouble(parts[17]);
   d.GridWidenFactor         = StringToDouble(parts[18]);
   d.MaxGridFactor           = StringToDouble(parts[19]);
   d.RecoveryGridStep        = StringToDouble(parts[20]);
   d.WinsToRecover           = (int)StringToInteger(parts[21]);
   d.AtrBars                 = (int)StringToInteger(parts[22]);

   return true;
}

//--- Clamp helper ---
//--- طفرة جين مزدوج ---
double MutateDouble(double val, double mn, double mx, double strength)
{
   if(MathRand() / 32767.0 > DNA_MUTATION_RATE)
      return val;

   double range = (mx - mn) * strength;
   double delta = (MathRand() / 32767.0 * 2.0 - 1.0) * range;
   return ClampD(val + delta, mn, mx);
}

int MutateInt(int val, int mn, int mx, double strength)
{
   if(MathRand() / 32767.0 > DNA_MUTATION_RATE)
      return val;

   double range = (mx - mn) * strength;
   int delta = (int)MathRound((MathRand() / 32767.0 * 2.0 - 1.0) * range);
   return ClampI(val + delta, mn, mx);
}

//--- طفرة DNA كاملة ---
AgentDNA MutateDNA(const AgentDNA &parent, double strength)
{
   AgentDNA child = parent;
   double s = strength * InpDNAMutationStrength / 0.15; // normalize

   child.ExtraTightGapPoints     = MutateInt   (parent.ExtraTightGapPoints,   100, 5000, s);  // XAUUSD needs large gap
   child.ModifyStepPoints        = MutateInt   (parent.ModifyStepPoints,         1,    5,  s);
   child.BasketTakeProfitMoney   = MutateDouble(parent.BasketTakeProfitMoney,   0.5, 20.0, s);
   child.BasketStopLossMoney     = MutateDouble(parent.BasketStopLossMoney,     3.0, 50.0, s);
   child.BasketLockStartMoney    = MutateDouble(parent.BasketLockStartMoney,    1.0, 20.0, s);
   child.BasketLockGiveBackMoney = MutateDouble(parent.BasketLockGiveBackMoney, 0.5, 10.0, s);
   child.CooldownAfterTPMinutes  = MutateInt   (parent.CooldownAfterTPMinutes,    1,  30,  s);
   child.CooldownAfterSLMinutes  = MutateInt   (parent.CooldownAfterSLMinutes,    5,  60,  s);
   child.CooldownAfterLossMinutes= MutateInt   (parent.CooldownAfterLossMinutes, 10, 120,  s);
   child.LotReductionFactor      = MutateDouble(parent.LotReductionFactor,      0.1,  0.9, s);
   child.MinLotFactor            = MutateDouble(parent.MinLotFactor,            0.1,  0.5, s);
   child.RecoveryLotStep         = MutateDouble(parent.RecoveryLotStep,         0.05, 0.5, s);
   child.GridWidenFactor         = MutateDouble(parent.GridWidenFactor,         1.0,  3.0, s);
   child.MaxGridFactor           = MutateDouble(parent.MaxGridFactor,           1.5,  8.0, s);
   child.RecoveryGridStep        = MutateDouble(parent.RecoveryGridStep,        0.05, 0.5, s);
   child.WinsToRecover           = MutateInt   (parent.WinsToRecover,             1,  10,  s);
   child.AtrBars                 = MutateInt   (parent.AtrBars,                  10, 100,  s);

   // صفر القيم التشغيلية
   child.fitness          = 0.0;
   child.generation       = parent.generation + 1;
   child.profit_factor    = 0.0;
   child.max_drawdown_pct = 100.0;
   child.total_trades     = 0.0;
   child.net_profit       = 0.0;

   return child;
}

//--- تهجين DNA (Crossover) بين والدين ---
AgentDNA CrossoverDNA(const AgentDNA &a, const AgentDNA &b)
{
   AgentDNA child;

   // كل جين يأخذ من أحد الوالدين عشوائياً
   child.ExtraTightGapPoints     = (MathRand()%2==0) ? a.ExtraTightGapPoints     : b.ExtraTightGapPoints;
   child.ModifyStepPoints        = (MathRand()%2==0) ? a.ModifyStepPoints        : b.ModifyStepPoints;
   child.BasketTakeProfitMoney   = (MathRand()%2==0) ? a.BasketTakeProfitMoney   : b.BasketTakeProfitMoney;
   child.BasketStopLossMoney     = (MathRand()%2==0) ? a.BasketStopLossMoney     : b.BasketStopLossMoney;
   child.BasketLockStartMoney    = (MathRand()%2==0) ? a.BasketLockStartMoney    : b.BasketLockStartMoney;
   child.BasketLockGiveBackMoney = (MathRand()%2==0) ? a.BasketLockGiveBackMoney : b.BasketLockGiveBackMoney;
   child.CooldownAfterTPMinutes  = (MathRand()%2==0) ? a.CooldownAfterTPMinutes  : b.CooldownAfterTPMinutes;
   child.CooldownAfterSLMinutes  = (MathRand()%2==0) ? a.CooldownAfterSLMinutes  : b.CooldownAfterSLMinutes;
   child.CooldownAfterLossMinutes= (MathRand()%2==0) ? a.CooldownAfterLossMinutes: b.CooldownAfterLossMinutes;
   child.LotReductionFactor      = (MathRand()%2==0) ? a.LotReductionFactor      : b.LotReductionFactor;
   child.MinLotFactor            = (MathRand()%2==0) ? a.MinLotFactor            : b.MinLotFactor;
   child.RecoveryLotStep         = (MathRand()%2==0) ? a.RecoveryLotStep         : b.RecoveryLotStep;
   child.GridWidenFactor         = (MathRand()%2==0) ? a.GridWidenFactor         : b.GridWidenFactor;
   child.MaxGridFactor           = (MathRand()%2==0) ? a.MaxGridFactor           : b.MaxGridFactor;
   child.RecoveryGridStep        = (MathRand()%2==0) ? a.RecoveryGridStep        : b.RecoveryGridStep;
   child.WinsToRecover           = (MathRand()%2==0) ? a.WinsToRecover           : b.WinsToRecover;
   child.AtrBars                 = (MathRand()%2==0) ? a.AtrBars                 : b.AtrBars;

   child.fitness          = 0.0;
   child.generation       = MathMax(a.generation, b.generation) + 1;
   child.profit_factor    = 0.0;
   child.max_drawdown_pct = 100.0;
   child.total_trades     = 0.0;
   child.net_profit       = 0.0;

   return child;
}

//--- حساب Fitness Score ---
// الصيغة: ProfitFactor * sqrt(Trades) * (1 - DrawdownPct/100) * sign(NetProfit)
double CalcFitness(double pf, double dd_pct, double trades, double net_profit)
{
   if(trades < 3.0)
      return -999.0;

   if(net_profit <= 0.0)
      return -MathAbs(net_profit);

   double dd_factor = 1.0 - ClampD(dd_pct / 100.0, 0.0, 0.99);
   double pf_capped = MathMin(pf, 10.0);

   return pf_capped * MathSqrt(trades) * dd_factor;
}

//====================================================================
// DNA FILE — قراءة / كتابة
//====================================================================
int LoadDNAMemory(AgentDNA &records[], int &count)
{
   count = 0;
   ArrayResize(records, DNA_MAX_RECORDS);

   int flags = FILE_READ | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;

   int h = FileOpen(DNA_MEMORY_FILE, flags, ',');
   if(h == INVALID_HANDLE)
      return 0;

   // Skip header row (23 columns)
   for(int k=0; k<23 && !FileIsEnding(h); k++)
      FileReadString(h);

   // Read records: FILE_CSV mode => each FileReadString = one field
   while(!FileIsEnding(h) && count < DNA_MAX_RECORDS)
   {
      string parts[23];
      bool rowOk = true;

      for(int c=0; c<23; c++)
      {
         if(FileIsEnding(h)){ rowOk=false; break; }
         parts[c] = FileReadString(h);
      }

      if(!rowOk) break;

      string line = "";
      for(int c=0; c<23; c++)
      {
         if(c>0) line += ",";
         line += parts[c];
      }

      AgentDNA d;
      if(CSVToDNA(line, d))
      {
         records[count] = d;
         count++;
      }
   }

   FileClose(h);
   return count;
}

void SaveDNAToMemory(const AgentDNA &newRecord)
{
   // اقرأ الموجود
   AgentDNA records[];
   int count = 0;
   LoadDNAMemory(records, count);

   // أضف الجديد
   if(count < DNA_MAX_RECORDS)
   {
      records[count] = newRecord;
      count++;
   }
   else
   {
      // احذف الأضعف
      int worstIdx = 0;
      for(int i=1; i<count; i++)
         if(records[i].fitness < records[worstIdx].fitness)
            worstIdx = i;

      if(newRecord.fitness > records[worstIdx].fitness)
         records[worstIdx] = newRecord;
   }

   // اكتب الملف
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;

   int h = FileOpen(DNA_MEMORY_FILE, flags, ',');
   if(h == INVALID_HANDLE)
   {
      Print("[DNA] Cannot write memory file error=", GetLastError());
      return;
   }

   FileWriteString(h, DNACSVHeader() + "\n");

   for(int i=0; i<count; i++)
      FileWriteString(h, DNAToCSV(records[i]) + "\n");

   FileClose(h);
   Print("[DNA] Memory saved — total records=", count);
}

//--- ترتيب تنازلي بالـ fitness ---
void SortDNAByFitness(AgentDNA &arr[], int n)
{
   for(int i=0; i<n-1; i++)
      for(int j=i+1; j<n; j++)
         if(arr[j].fitness > arr[i].fitness)
         {
            AgentDNA tmp = arr[i];
            arr[i] = arr[j];
            arr[j] = tmp;
         }
}

//--- اختر DNA للجيل القادم ---
AgentDNA SelectNextDNA()
{
   AgentDNA records[];
   int count = 0;
   LoadDNAMemory(records, count);

   if(count == 0)
   {
      Print("[DNA] No memory found — using default DNA");
      return DefaultDNA();
   }

   SortDNAByFitness(records, count);

   // الجيل الحالي
   g_current_generation = records[0].generation + 1;

   if(InpDNAVerboseReport)
   {
      Print("╔══════════════════════════════════════════╗");
      Print("║         DNA EVOLUTION REPORT              ║");
      Print("╠══════════════════════════════════════════╣");
      Print("║ Total Records in Memory: ", count);
      Print("║ Best Generation: ", records[0].generation);
      Print("║ Best Fitness:    ", DoubleToString(records[0].fitness, 4));
      Print("║ Best ProfitFactor: ", DoubleToString(records[0].profit_factor, 2));
      Print("║ Best Drawdown:   ", DoubleToString(records[0].max_drawdown_pct, 2), "%");
      Print("║ Best NetProfit:  $", DoubleToString(records[0].net_profit, 2));
      Print("║ Best Trades:     ", (int)records[0].total_trades);
      Print("╠══════════════════════════════════════════╣");
      Print("║ Top 3 DNA:");
      for(int i=0; i<MathMin(3,count); i++)
         Print("║  [", i+1, "] Gen=", records[i].generation,
               " Fit=", DoubleToString(records[i].fitness,3),
               " PF=", DoubleToString(records[i].profit_factor,2),
               " DD=", DoubleToString(records[i].max_drawdown_pct,1), "%");
      Print("╚══════════════════════════════════════════╝");
   }

   if(!InpDNAMutateFromBest)
      return records[0];

   // اختر استراتيجية التطور
   int eliteN = MathMin(DNA_ELITE_COUNT, count);

   if(count >= 2 && MathRand() % 3 == 0)
   {
      // Crossover: تهجين بين اثنين من النخبة
      int idxA = MathRand() % eliteN;
      int idxB = MathRand() % eliteN;
      while(idxB == idxA && eliteN > 1)
         idxB = MathRand() % eliteN;

      AgentDNA child = CrossoverDNA(records[idxA], records[idxB]);
      child = MutateDNA(child, InpDNAMutationStrength);
      Print("[DNA] Strategy: CROSSOVER Gen(", records[idxA].generation, "+", records[idxB].generation, ") → Gen", child.generation);
      return child;
   }
   else
   {
      // Mutation: طفرة من الأفضل
      AgentDNA child = MutateDNA(records[0], InpDNAMutationStrength);
      Print("[DNA] Strategy: MUTATION from best Gen", records[0].generation, " → Gen", child.generation);
      return child;
   }
}

//====================================================================
// تطبيق DNA على الـ EA
//====================================================================
//====================================================================
// OnTester — يُستدعى بعد كل اختبار في Strategy Tester
//====================================================================
double OnTester()
{
   if(!InpUseDNAEvolution)
      return 0.0;

   // اجمع إحصائيات الاختبار
   double pf         = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd_pct     = TesterStatistics(STAT_EQUITY_DD_RELATIVE);
   double trades     = TesterStatistics(STAT_TRADES);
   double net_profit = TesterStatistics(STAT_PROFIT);
   double sharpe     = TesterStatistics(STAT_SHARPE_RATIO);

   double fitness = CalcFitness(pf, dd_pct, trades, net_profit);

   // سجّل نتيجة هذا الجيل في DNA
   AgentDNA result = g_dna;
   result.fitness          = fitness;
   result.profit_factor    = pf;
   result.max_drawdown_pct = dd_pct;
   result.total_trades     = trades;
   result.net_profit       = net_profit;
   result.generation       = g_current_generation;

   Print("╔══════════════════════════════════════════╗");
   Print("║      DNA TEST COMPLETED — Gen ", g_current_generation, "         ║");
   Print("╠══════════════════════════════════════════╣");
   Print("║ Fitness:       ", DoubleToString(fitness, 4));
   Print("║ Profit Factor: ", DoubleToString(pf, 3));
   Print("║ Net Profit:    $", DoubleToString(net_profit, 2));
   Print("║ Max DD:        ", DoubleToString(dd_pct, 2), "%");
   Print("║ Trades:        ", (int)trades);
   Print("║ Sharpe:        ", DoubleToString(sharpe, 3));
   Print("╚══════════════════════════════════════════╝");

   SaveDNAToMemory(result);

   return fitness;
}

//====================================================================
// Logging
//====================================================================
void Log(string msg)
{
   if(InpVerboseLogs)
      Print("[GOLD_DNA_V7] ", msg);
}

//====================================================================
// Symbol helpers (نفس v6)
//====================================================================
int ExactGapPoints(string symbol)
{
   int raw = BrokerMinimumStopPoints(symbol) + MathMax(0, g_dna.ExtraTightGapPoints);
   raw = (int)MathRound(raw * g_state.grid_factor);
   return MathMax(BrokerMinimumStopPoints(symbol), raw);
}

bool CanSend()
{
   if((TimeCurrent()-g_state.last_order_time)<InpMinSecondsBetweenOrders) return false;
   if(TimeCurrent()<g_state.cooldown_until) return false;
   return true;
}
//====================================================================
// CSV Profile Loader
//====================================================================
bool LoadGoldProfile()
{
   string wanted = GoldSymbol();
   int flags = FILE_READ|FILE_CSV|FILE_ANSI;
   if(InpUseCommonFiles) flags|=FILE_COMMON;

   int h = FileOpen(InpProfileCsv, flags, ',');
   if(h==INVALID_HANDLE)
   {
      Print("[DNA] Cannot open profile CSV: ",InpProfileCsv," error=",GetLastError());
      return false;
   }

   for(int k=0;k<11&&!FileIsEnding(h);k++) FileReadString(h);

   bool found=false;
   while(!FileIsEnding(h))
   {
      AgentProfile p;
      p.symbol=FileReadString(h);
      if(p.symbol=="") break;
      p.enabled                    =(StringToInteger(FileReadString(h))==1);
      p.magic                      =(ulong)StringToInteger(FileReadString(h));
      p.asset_class                =FileReadString(h);
      p.base_lot                   =StringToDouble(FileReadString(h));
      p.atr_grid_multiplier        =StringToDouble(FileReadString(h));
      p.atr_trailing_multiplier    =StringToDouble(FileReadString(h));
      p.spread_grid_multiplier     =StringToDouble(FileReadString(h));
      p.stop_loss_atr_multiplier   =StringToDouble(FileReadString(h));
      p.take_profit_atr_multiplier =StringToDouble(FileReadString(h));
      p.max_spread_to_atr_ratio    =StringToDouble(FileReadString(h));
      if(!p.enabled||p.symbol!=wanted) continue;
      g_profile=p; found=true; break;
   }
   FileClose(h);

   if(!found){ Print("[DNA] Profile not found for ",wanted); return false; }
   if(!SelectSymbolSafe(g_profile.symbol)){ Print("[DNA] Cannot select symbol: ",g_profile.symbol); return false; }

   g_state.last_bar_time=0; g_state.cooldown_until=0; g_state.last_order_time=0;
   g_state.lot_factor=1.0; g_state.grid_factor=1.0;
   g_state.basket_peak_profit=0.0; g_state.closed_win_streak=0;
   g_state.closed_loss_streak=0; g_state.last_processed_deal=0;
   g_state.chop_flip_count=0; g_state.chop_window_start=0;
   g_state.last_position_open_time=0;

   return true;
}

//====================================================================
// Time / Spread Filters
//====================================================================
double BufferValue(int handle,int buffer,int shift)
{
   if(handle==INVALID_HANDLE) return 0.0;
   double arr[]; ArraySetAsSeries(arr,true);
   if(CopyBuffer(handle,buffer,shift,1,arr)<=0) return 0.0;
   return arr[0];
}

double IndicatorRSI(string symbol,int period=14)
{
   int h=iRSI(symbol,(ENUM_TIMEFRAMES)InpTimeframe,period,PRICE_CLOSE);
   double v=BufferValue(h,0,1);
   if(h!=INVALID_HANDLE) IndicatorRelease(h);
   return v;
}

double IndicatorADX(string symbol,int period=14)
{
   int h=iADX(symbol,(ENUM_TIMEFRAMES)InpTimeframe,period);
   double v=BufferValue(h,0,1);
   if(h!=INVALID_HANDLE) IndicatorRelease(h);
   return v;
}

double IndicatorMFI(string symbol,int period=14)
{
   int h=iMFI(symbol,(ENUM_TIMEFRAMES)InpTimeframe,period,VOLUME_TICK);
   double v=BufferValue(h,0,1);
   if(h!=INVALID_HANDLE) IndicatorRelease(h);
   return v;
}

double IndicatorMACDHist(string symbol)
{
   int h=iMACD(symbol,(ENUM_TIMEFRAMES)InpTimeframe,12,26,9,PRICE_CLOSE);
   double main=BufferValue(h,0,1);
   double sig =BufferValue(h,1,1);
   if(h!=INVALID_HANDLE) IndicatorRelease(h);
   return main-sig;
}

double VolumePercent(string symbol,int bars=50)
{
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,0,bars+2,rates);
   if(copied<10) return 0.0;
   double sum=0.0; int count=0;
   for(int i=2;i<copied;i++){ sum+=(double)rates[i].tick_volume; count++; }
   if(count<=0 || sum<=0.0) return 0.0;
   double avg=sum/count;
   return (double)rates[1].tick_volume/avg*100.0;
}

void DonchianStats(string symbol,int bars,double &hi,double &lo,double &pos)
{
   hi=0.0; lo=0.0; pos=50.0;
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,0,bars+2,rates);
   if(copied<bars/2) return;
   hi=rates[1].high; lo=rates[1].low;
   for(int i=1;i<copied;i++)
   {
      if(rates[i].high>hi) hi=rates[i].high;
      if(rates[i].low <lo) lo=rates[i].low;
   }
   double range=hi-lo;
   if(range>0.0) pos=(rates[1].close-lo)/range*100.0;
}

int TrendSignal(string symbol,double atrPoints)
{
   double fast=EMAFromCloses(symbol,9,40);
   double slow=EMAFromCloses(symbol,21,80);
   double pt=PointOf(symbol);
   if(fast<=0.0 || slow<=0.0 || pt<=0.0) return 0;
   double diffPoints=(fast-slow)/pt;
   double gate=MathMax(5.0,atrPoints*0.08);
   if(diffPoints>gate) return 1;
   if(diffPoints<-gate) return -1;
   return 0;
}

IndicatorSnapshot GetIndicatorSnapshot(string symbol)
{
   IndicatorSnapshot s;
   s.atr=CalcATRPoints(symbol,g_dna.AtrBars);
   s.rsi=IndicatorRSI(symbol,14);
   s.adx=IndicatorADX(symbol,14);
   s.macd=IndicatorMACDHist(symbol);
   s.mfi=IndicatorMFI(symbol,14);
   s.volp=VolumePercent(symbol,50);
   s.spr=SpreadPoints(symbol);
   s.dchHi=0.0; s.dchLo=0.0; s.dchPos=50.0;
   DonchianStats(symbol,20,s.dchHi,s.dchLo,s.dchPos);

   double pt=PointOf(symbol);
   double bid=BidOf(symbol);
   double ask=AskOf(symbol);
   double price=(bid+ask)*0.5;
   double atrPrice=(pt>0.0 ? s.atr*pt : 0.0);
   s.demandDist=(atrPrice>0.0 && s.dchLo>0.0) ? (price-s.dchLo)/atrPrice : 999.0;
   s.supplyDist=(atrPrice>0.0 && s.dchHi>0.0) ? (s.dchHi-price)/atrPrice : 999.0;
   s.demand=(s.demandDist>=0.0 && s.demandDist<=0.35) ? 1 : 0;
   s.supply=(s.supplyDist>=0.0 && s.supplyDist<=0.35) ? 1 : 0;
   s.trend=TrendSignal(symbol,s.atr);

   s.sig=0.0;
   s.sig += s.trend*25.0;
   if(s.adx>=22.0) s.sig += s.trend*15.0;
   if(s.macd>0.0) s.sig += 15.0; else if(s.macd<0.0) s.sig -= 15.0;
   if(s.rsi>55.0 && s.rsi<72.0) s.sig += 10.0;
   if(s.rsi<45.0 && s.rsi>28.0) s.sig -= 10.0;
   if(s.mfi>55.0 && s.mfi<80.0) s.sig += 8.0;
   if(s.mfi<45.0 && s.mfi>20.0) s.sig -= 8.0;
   if(s.demand) s.sig += 10.0;
   if(s.supply) s.sig -= 10.0;
   s.sig=ClampD(s.sig,-100.0,100.0);

   s.entryScore=MathAbs(s.sig);
   s.avoidScore=0.0;
   if(s.adx<14.0) s.avoidScore+=20.0;
   if(s.spr>MathMax(25.0,s.atr*0.18)) s.avoidScore+=25.0;
   if((s.trend>0 && s.supply) || (s.trend<0 && s.demand)) s.avoidScore+=20.0;
   if(s.rsi>=78.0 || s.rsi<=22.0) s.avoidScore+=15.0;
   if(s.mfi>=85.0 || s.mfi<=15.0) s.avoidScore+=10.0;
   s.avoidScore=ClampD(s.avoidScore,0.0,100.0);
   return s;
}

double ConfidenceScoreForSide(string side)
{
   IndicatorSnapshot s=GetIndicatorSnapshot(g_profile.symbol);
   int dir=0;
   string d=side; StringToUpper(d);
   if(d=="BUY") dir=1;
   if(d=="SELL") dir=-1;
   if(dir==0) return 0.0;
   if(s.trend!=dir) return 0.0;
   if(s.sig*dir<=0.0) return 0.0;
   if(s.avoidScore>InpConfidenceAvoidMax) return 0.0;
   if(s.adx<InpConfidenceAdxMin) return 0.0;
   if(s.entryScore<InpConfidenceEntryMin) return 0.0;

   double score=0.0;
   score+=MathMin(40.0,s.entryScore*0.40);
   score+=MathMin(25.0,s.adx);
   score+=MathMin(25.0,MathAbs(s.sig)*0.25);
   score+=MathMax(0.0,10.0-s.avoidScore*0.4);
   return ClampD(score,0.0,100.0);
}

double ConfidenceTPFactorForBasket()
{
   if(!InpUseConfidenceBasketTPBoost) return 1.0;
   double buyScore =(CountPositions(POSITION_TYPE_BUY)>0 && CountPositions(POSITION_TYPE_SELL)==0) ? ConfidenceScoreForSide("BUY") : 0.0;
   double sellScore=(CountPositions(POSITION_TYPE_SELL)>0 && CountPositions(POSITION_TYPE_BUY)==0) ? ConfidenceScoreForSide("SELL") : 0.0;
   double score=MathMax(buyScore,sellScore);
   if(score<=0.0) return 1.0;
   double strength=(score-InpConfidenceEntryMin)/MathMax(1.0,100.0-InpConfidenceEntryMin);
   double factor=1.0+(InpConfidenceTPBoostFactor-1.0)*ClampD(strength,0.0,1.0);
   return ClampD(factor,1.0,InpConfidenceTPMaxFactor);
}

double ConfidenceLotFactorForSide(string side)
{
   if(!InpUseConfidenceLotBoost) return 1.0;
   double score=ConfidenceScoreForSide(side);
   if(score<InpConfidenceLotMin) return 1.0;
   double strength=(score-InpConfidenceLotMin)/MathMax(1.0,100.0-InpConfidenceLotMin);
   double factor=1.0+(InpConfidenceLotBoostFactor-1.0)*ClampD(strength,0.0,1.0);
   return ClampD(factor,1.0,InpConfidenceLotMaxFactor);
}

string ConfidenceTelemetryJSON()
{
   double buyScore=ConfidenceScoreForSide("BUY");
   double sellScore=ConfidenceScoreForSide("SELL");
   return ",\"conf_buy\":"+DoubleToString(buyScore,1)+
          ",\"conf_sell\":"+DoubleToString(sellScore,1)+
          ",\"tp_factor\":"+DoubleToString(ConfidenceTPFactorForBasket(),3)+
          ",\"lot_factor_conf_buy\":"+DoubleToString(ConfidenceLotFactorForSide("BUY"),3)+
          ",\"lot_factor_conf_sell\":"+DoubleToString(ConfidenceLotFactorForSide("SELL"),3);
}

string IndicatorTelemetryJSON(string symbol,bool compact)
{
   IndicatorSnapshot s=GetIndicatorSnapshot(symbol);

   if(compact)
      return ",\"atr\":"+DoubleToString(s.atr,2)+
             ",\"sig\":"+DoubleToString(s.sig,1)+
             ",\"tr\":"+IntegerToString(s.trend)+
             ",\"rsi\":"+DoubleToString(s.rsi,1)+
             ",\"adx\":"+DoubleToString(s.adx,1)+
             ",\"macd\":"+DoubleToString(s.macd,5)+
             ",\"mfi\":"+DoubleToString(s.mfi,1)+
             ",\"volp\":"+DoubleToString(s.volp,1)+
             ",\"spr\":"+DoubleToString(s.spr,1)+
             ",\"dchp\":"+DoubleToString(s.dchPos,1)+
             ",\"dem\":"+IntegerToString(s.demand)+
             ",\"sup\":"+IntegerToString(s.supply)+
             ",\"entry\":"+DoubleToString(s.entryScore,1)+
             ",\"avoid\":"+DoubleToString(s.avoidScore,1)+
             ConfidenceTelemetryJSON();

   return ",\"atr_points\":"+DoubleToString(s.atr,2)+
          ",\"sig\":"+DoubleToString(s.sig,1)+
          ",\"trend\":"+IntegerToString(s.trend)+
          ",\"rsi\":"+DoubleToString(s.rsi,1)+
          ",\"adx\":"+DoubleToString(s.adx,1)+
          ",\"macd_hist\":"+DoubleToString(s.macd,5)+
          ",\"mfi\":"+DoubleToString(s.mfi,1)+
          ",\"vol_pct\":"+DoubleToString(s.volp,1)+
          ",\"spread_points\":"+DoubleToString(s.spr,1)+
          ",\"dch_high\":"+DoubleToString(s.dchHi,DigitsOf(symbol))+
          ",\"dch_low\":"+DoubleToString(s.dchLo,DigitsOf(symbol))+
          ",\"dch_pos\":"+DoubleToString(s.dchPos,1)+
          ",\"demand\":"+IntegerToString(s.demand)+
          ",\"supply\":"+IntegerToString(s.supply)+
          ",\"demand_dist_atr\":"+DoubleToString(s.demandDist,2)+
          ",\"supply_dist_atr\":"+DoubleToString(s.supplyDist,2)+
          ",\"entry_score\":"+DoubleToString(s.entryScore,1)+
          ",\"avoid_score\":"+DoubleToString(s.avoidScore,1)+
          ConfidenceTelemetryJSON();
}

//====================================================================
// Position / Order Scanners
//====================================================================
//====================================================================
// Pair Prices
//====================================================================
//====================================================================
// Order / Position Modifications
//====================================================================
void CancelOrders(int typeFilter=-1)
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   trade.SetExpertMagicNumber(mag);
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(!tk) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym) continue;
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=mag) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type!=ORDER_TYPE_BUY_STOP&&type!=ORDER_TYPE_SELL_STOP) continue;
      if(typeFilter>=0&&(int)type!=typeFilter) continue;
      if(InpDryRunPrintOnly) Log("DRY delete order ticket="+IntegerToString((int)tk));
      else trade.OrderDelete(tk);
   }
}

void DeleteDuplicateOrdersKeepLatest(ENUM_ORDER_TYPE type)
{
   if(!InpDeleteDuplicates) return;
   ulong keep=LatestOrderTicket(type); if(!keep) return;
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   trade.SetExpertMagicNumber(mag);
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(!tk||tk==keep) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym) continue;
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=mag) continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE)!=type) continue;
      if(InpDryRunPrintOnly) Log("DRY delete duplicate="+IntegerToString((int)tk));
      else trade.OrderDelete(tk);
   }
}

bool ModifyPositionSLToPair(ulong positionTicket, double pairPrice, ENUM_POSITION_TYPE posType=POSITION_TYPE_BUY)
{
   if(!InpPairPositionSLWithPending) return true;
   if(!PositionSelectByTicket(positionTicket)) return false;

   string sym=g_profile.symbol; double pt=PointOf(sym);
   double curSL=PositionGetDouble(POSITION_SL), curTP=PositionGetDouble(POSITION_TP);
   datetime openTime=(datetime)PositionGetInteger(POSITION_TIME);

   // ✦ FIX: حد أدنى لمدة الصفقة قبل تعديل الـ SL
   if(InpMinHoldSeconds>0 && (TimeCurrent()-openTime)<InpMinHoldSeconds)
      return true;

   // ✦ FIX: الـ SL يتحرك في اتجاه الربح فقط (One-Way Ratchet Trailing)
   if(InpOneWayTrailOnly && curSL>0)
   {
      // BUY: SL يتحرك للأعلى فقط (يحمي الربح)
      if(posType==POSITION_TYPE_BUY && pairPrice<=curSL)
         return true;   // لا تحرك SL للأسفل

      // SELL: SL يتحرك للأسفل فقط (يحمي الربح)
      if(posType==POSITION_TYPE_SELL && pairPrice>=curSL)
         return true;   // لا تحرك SL للأعلى
   }

   int step=MathMax(1,g_dna.ModifyStepPoints);
   if(curSL>0&&MathAbs(curSL-pairPrice)<step*pt) return true;

   trade.SetExpertMagicNumber(g_profile.magic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   if(InpDryRunPrintOnly){ Log("DRY modify SL to pair="+DoubleToString(pairPrice,DigitsOf(sym))); return true; }
   bool ok=trade.PositionModify(positionTicket,pairPrice,curTP);
   if(!ok) Log("SL modify failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

bool ModifyPendingToPair(ENUM_ORDER_TYPE type, double targetPrice)
{
   ulong tk=LatestOrderTicket(type); if(!tk) return false;
   if(!OrderSelect(tk)) return false;
   string sym=g_profile.symbol; double pt=PointOf(sym);
   double oldPrice=OrderGetDouble(ORDER_PRICE_OPEN);
   int step=MathMax(1,g_dna.ModifyStepPoints);
   if(MathAbs(oldPrice-targetPrice)<step*pt) return true;
   double sl=OrderGetDouble(ORDER_SL), tp=OrderGetDouble(ORDER_TP);
   trade.SetExpertMagicNumber(g_profile.magic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   if(InpDryRunPrintOnly){ Log("DRY modify pending "+EnumToString(type)+" → "+DoubleToString(targetPrice,DigitsOf(sym))); return true; }
   bool ok=trade.OrderModify(tk,targetPrice,sl,tp,ORDER_TIME_GTC,0,0.0);
   if(!ok) Log("Pending modify failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

//====================================================================
// Close / Cooldown / Adaptation — يستخدم DNA
//====================================================================
void CloseAllPositions(string reason)
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   trade.SetExpertMagicNumber(mag); trade.SetDeviationInPoints(InpDeviationPoints);
   CancelOrders();
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      if(InpDryRunPrintOnly) Log("DRY close ticket="+IntegerToString((int)tk));
      else trade.PositionClose(tk);
   }
   g_state.basket_peak_profit=0; Log("CloseAll reason="+reason);
}

void ApplyCooldown(int minutes,string reason,bool reduceLot,bool widenGrid)
{
   g_state.cooldown_until=TimeCurrent()+minutes*60;
   if(reduceLot) g_state.lot_factor=MathMax(g_dna.MinLotFactor, g_state.lot_factor*g_dna.LotReductionFactor);
   if(widenGrid) g_state.grid_factor=MathMin(g_dna.MaxGridFactor, g_state.grid_factor*g_dna.GridWidenFactor);
   CancelOrders();
   Log("Cooldown "+reason+" "+IntegerToString(minutes)+"min lotF="+DoubleToString(g_state.lot_factor,2)+" gridF="+DoubleToString(g_state.grid_factor,2));
}

void ProcessClosedDeals()
{
   if(!HistorySelect(TimeCurrent()-86400*7,TimeCurrent())) return;
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
   {
      ulong deal=HistoryDealGetTicket(i); if(!deal) continue;
      if(deal<=g_state.last_processed_deal) continue;
      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=g_profile.symbol) continue;
      if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=g_profile.magic) continue;
      ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT&&entry!=DEAL_ENTRY_INOUT&&entry!=DEAL_ENTRY_OUT_BY)
         { g_state.last_processed_deal=deal; continue; }
      double profit=HistoryDealGetDouble(deal,DEAL_PROFIT)+HistoryDealGetDouble(deal,DEAL_SWAP)+HistoryDealGetDouble(deal,DEAL_COMMISSION);
      if(profit>0){ g_state.closed_win_streak++; g_state.closed_loss_streak=0; RecoverRiskIfNeeded(); }
      else if(profit<0)
      {
         g_state.closed_loss_streak++; g_state.closed_win_streak=0;
         if(MathAbs(profit)>=InpLargeSingleLossMoney)
            ApplyCooldown(g_dna.CooldownAfterLossMinutes,"large_loss_"+DoubleToString(profit,2),true,true);
      }
      g_state.last_processed_deal=deal;
   }
}

//====================================================================
// Basket Guard — يستخدم DNA
//====================================================================
void BasketGuard()
{
   double pnl=BasketProfit(); int allPos=CountAllPositions();
   if(allPos<=0){ g_state.basket_peak_profit=0; return; }
   if(pnl>g_state.basket_peak_profit) g_state.basket_peak_profit=pnl;

   double tpTarget=g_dna.BasketTakeProfitMoney*ConfidenceTPFactorForBasket();
   if(InpUseBasketTakeProfit&&pnl>=tpTarget)
      { CloseAllPositions("basket_tp_conf_"+DoubleToString(tpTarget,2)); ApplyCooldown(g_dna.CooldownAfterTPMinutes,"after_tp",false,false); return; }

   if(InpUseBasketEquityLock&&g_state.basket_peak_profit>=g_dna.BasketLockStartMoney)
   {
      if((g_state.basket_peak_profit-pnl)>=g_dna.BasketLockGiveBackMoney)
         { CloseAllPositions("equity_lock"); ApplyCooldown(g_dna.CooldownAfterTPMinutes,"after_lock",false,false); return; }
   }

   if(InpUseBasketStopLoss&&pnl<=-MathAbs(g_dna.BasketStopLossMoney))
      { CloseAllPositions("basket_sl"); ApplyCooldown(g_dna.CooldownAfterSLMinutes,"after_sl",true,true); return; }
}

//====================================================================
// Execution
//====================================================================
bool OpenMarket(string side)
{
   if(!CanSend()) return false;
   string sym=g_profile.symbol;
   double pt=PointOf(sym),ask=AskOf(sym),bid=BidOf(sym);
   if(ask<=0||bid<=0||pt<=0) return false;
   double lotBoost=ConfidenceLotFactorForSide(side);
   double lot=NormalizeVolume(sym,g_profile.base_lot*g_state.lot_factor*lotBoost);
   double sl=0,tp=0;
   if(InpUseFallbackInitialSLTP)
   {
      if(side=="BUY"){ sl=NormalizePrice(sym,ask-InpFallbackSLPoints*pt); tp=NormalizePrice(sym,ask+InpFallbackTPPoints*pt); }
      else           { sl=NormalizePrice(sym,bid+InpFallbackSLPoints*pt); tp=NormalizePrice(sym,bid-InpFallbackTPPoints*pt); }
   }
   trade.SetExpertMagicNumber(g_profile.magic); trade.SetDeviationInPoints(InpDeviationPoints);
   bool ok=false;
   if(side=="BUY")
   {
      if(InpDryRunPrintOnly){ Log("DRY BUY lot="+DoubleToString(lot,2)+" confLot="+DoubleToString(lotBoost,2)); ok=true; }
      else ok=trade.Buy(lot,sym,0,sl,tp,"DNA_BUY");
   }
   else
   {
      if(InpDryRunPrintOnly){ Log("DRY SELL lot="+DoubleToString(lot,2)+" confLot="+DoubleToString(lotBoost,2)); ok=true; }
      else ok=trade.Sell(lot,sym,0,sl,tp,"DNA_SELL");
   }
   if(ok)
   {
      MarkSent();
      g_state.last_position_open_time=TimeCurrent();
   }
   else Log("OpenMarket failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

bool PlaceReversePending(ENUM_ORDER_TYPE type, double price)
{
   if(!CanSend()) return false;
   string sym=g_profile.symbol;
   double pt=PointOf(sym),ask=AskOf(sym),bid=BidOf(sym);
   if(ask<=0||bid<=0||pt<=0) return false;
   int minStop=BrokerMinimumStopPoints(sym);
   string pendingSide=(type==ORDER_TYPE_SELL_STOP ? "SELL" : "BUY");
   double lotBoost=ConfidenceLotFactorForSide(pendingSide);
   double lot=NormalizeVolume(sym,g_profile.base_lot*g_state.lot_factor*lotBoost);
   double sl=0,tp=0;
   trade.SetExpertMagicNumber(g_profile.magic); trade.SetDeviationInPoints(InpDeviationPoints);
   bool ok=false;
   if(type==ORDER_TYPE_SELL_STOP)
   {
      price=NormalizePrice(sym,MathMin(price,bid-minStop*pt));
      if(!InpPendingHasNoOwnSLTP) sl=NormalizePrice(sym,price+ExactGapPoints(sym)*2*pt);
      if(InpDryRunPrintOnly){ Log("DRY SELL_STOP price="+DoubleToString(price,DigitsOf(sym))); ok=true; }
      else ok=trade.SellStop(lot,price,sym,sl,tp,ORDER_TIME_GTC,0,"DNA_SELL_STOP");
   }
   else
   {
      price=NormalizePrice(sym,MathMax(price,ask+minStop*pt));
      if(!InpPendingHasNoOwnSLTP) sl=NormalizePrice(sym,price-ExactGapPoints(sym)*2*pt);
      if(InpDryRunPrintOnly){ Log("DRY BUY_STOP price="+DoubleToString(price,DigitsOf(sym))); ok=true; }
      else ok=trade.BuyStop(lot,price,sym,sl,tp,ORDER_TIME_GTC,0,"DNA_BUY_STOP");
   }
   if(ok) MarkSent();
   else Log("PlacePending failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

//====================================================================
// Hedge Resolver
//====================================================================
void ResolveHedgeIfNeeded()
{
   if(!InpResolveHedgeImmediately) return;
   if(CountPositions(POSITION_TYPE_BUY)<=0||CountPositions(POSITION_TYPE_SELL)<=0) return;
   CancelOrders();
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   ulong latest=LatestPositionTicket();
   trade.SetExpertMagicNumber(mag); trade.SetDeviationInPoints(InpDeviationPoints);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      bool closeIt=InpResolveHedgeKeepLatest?(tk!=latest):(PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP)<0);
      if(closeIt){ if(InpDryRunPrintOnly) Log("DRY resolve hedge close="+IntegerToString((int)tk)); else trade.PositionClose(tk); MarkSent(); }
   }
}

//====================================================================
// Stop-Reverse Pair Manager
//====================================================================
void ManageStopReversePair()
{
   if(!InpUseStopReversePair) return;
   string sym=g_profile.symbol;
   if(!IsFreshTick(sym)||TimeCurrent()<g_state.cooldown_until||!SpreadAllowed()) return;
   int buyPos=CountPositions(POSITION_TYPE_BUY), sellPos=CountPositions(POSITION_TYPE_SELL), allPos=buyPos+sellPos;
   if(allPos<=0){ CancelOrders(); return; }
   if((buyPos>0&&sellPos>0)||allPos>InpMaxOpenPositionsPerSymbol){ ResolveHedgeIfNeeded(); return; }

   // ✦ FIX: Chop Detection — إذا انعكست أكثر من N مرة في دقيقة → cooldown
   if(InpChopMaxFlipsPerMin>0)
   {
      datetime now=TimeCurrent();
      if(now-g_state.chop_window_start>60)
      {
         g_state.chop_window_start=now;
         g_state.chop_flip_count=0;
      }
   }

   ulong mag=g_profile.magic;

   if(buyPos>0&&sellPos==0)
   {
      if(InpDeleteSameSidePending) CancelOrders((int)ORDER_TYPE_BUY_STOP);
      DeleteDuplicateOrdersKeepLatest(ORDER_TYPE_SELL_STOP);
      double pairPrice=ReverseSellStopPrice();
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong tk=PositionGetTicket(i); if(!tk) continue;
         if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
         if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
         if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=POSITION_TYPE_BUY) continue;
         ModifyPositionSLToPair(tk,pairPrice,POSITION_TYPE_BUY);
      }
      if(CountOrders(ORDER_TYPE_SELL_STOP)<=0)
      {
         // Count flip
         if(InpChopMaxFlipsPerMin>0)
         {
            g_state.chop_flip_count++;
            if(g_state.chop_flip_count>=InpChopMaxFlipsPerMin)
            {
               Log("CHOP DETECTED — "+IntegerToString(g_state.chop_flip_count)+" flips/min — cooldown");
               g_state.chop_flip_count=0;
               ApplyCooldown(g_dna.CooldownAfterSLMinutes,"chop_detected",true,true);
               return;
            }
         }
         PlaceReversePending(ORDER_TYPE_SELL_STOP,pairPrice);
      }
      else ModifyPendingToPair(ORDER_TYPE_SELL_STOP,pairPrice);
      return;
   }

   if(sellPos>0&&buyPos==0)
   {
      if(InpDeleteSameSidePending) CancelOrders((int)ORDER_TYPE_SELL_STOP);
      DeleteDuplicateOrdersKeepLatest(ORDER_TYPE_BUY_STOP);
      double pairPrice=ReverseBuyStopPrice();
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong tk=PositionGetTicket(i); if(!tk) continue;
         if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
         if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
         if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=POSITION_TYPE_SELL) continue;
         ModifyPositionSLToPair(tk,pairPrice,POSITION_TYPE_SELL);
      }
      if(CountOrders(ORDER_TYPE_BUY_STOP)<=0) PlaceReversePending(ORDER_TYPE_BUY_STOP,pairPrice);
      else ModifyPendingToPair(ORDER_TYPE_BUY_STOP,pairPrice);
      return;
   }
}

//====================================================================
// Initial Entry
//====================================================================
void ManageInitialEntryOnNewBar()
{
   string sym=g_profile.symbol;
   datetime bt=iTime(sym,(ENUM_TIMEFRAMES)InpTimeframe,0);
   if(bt<=0||bt==g_state.last_bar_time) return;
   g_state.last_bar_time=bt;
   WriteRealtimeBar();   // ← كتابة بيانات الشمعة
   DrawChartInfo();      // ← رسم على الشارت
   if(TimeCurrent()<g_state.cooldown_until||!IsFreshTick(sym)||!SpreadAllowed()||!EntryTimeAllowed()) return;
   if(CountAllPositions()>0) return;
   CancelOrders();
   if(OpenMarket(DirectionOf(sym))) ManageStopReversePair();
}

//====================================================================
// Main Process
//====================================================================
void Process()
{
   if(!g_loaded) return;
   ProcessClosedDeals(); BasketGuard(); ResolveHedgeIfNeeded(); BasketGuard();
   if(InpManagePairEveryTick) ManageStopReversePair();
   BasketGuard(); ManageInitialEntryOnNewBar(); BasketGuard();
}


//====================================================================
// Real-Time Export — يكتب ملف JSON كل شمعة لـ ea_monitor.py
//====================================================================
void WriteRealtimeBar()
{
   string sym  = g_profile.symbol;
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl  = BasketProfit();
   int    allP = CountAllPositions();

   if(bal > g_rt_peak_bal) g_rt_peak_bal = bal;
   g_rt_bar_count++;

   // ─── ملف الحالة الحالية ──────────────────────────────
   int h = FileOpen("ea_realtime_status.json",
                    FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h != INVALID_HANDLE)
   {
      MqlRates r[1];
      CopyRates(sym, PERIOD_M1, 0, 1, r);

      string j = "{";
      j += "\"bar\":"          + IntegerToString(g_rt_bar_count)            + ",";
      j += "\"time\":\""       + TimeToString(TimeCurrent())                + "\",";
      j += "\"balance\":"      + DoubleToString(bal, 2)                     + ",";
      j += "\"equity\":"       + DoubleToString(eq,  2)                     + ",";
      j += "\"peak_balance\":" + DoubleToString(g_rt_peak_bal, 2)          + ",";
      j += "\"open_pnl\":"     + DoubleToString(pnl, 2)                    + ",";
      j += "\"positions\":"    + IntegerToString(allP)                      + ",";
      j += "\"lot_factor\":"   + DoubleToString(g_state.lot_factor, 4)     + ",";
      j += "\"grid_factor\":"  + DoubleToString(g_state.grid_factor, 4)    + ",";
      j += "\"win_streak\":"   + IntegerToString(g_state.closed_win_streak) + ",";
      j += "\"loss_streak\":"  + IntegerToString(g_state.closed_loss_streak)+ ",";
      j += "\"dna_gap\":"      + IntegerToString(g_dna.ExtraTightGapPoints) + ",";
      j += "\"dna_tp\":"       + DoubleToString(g_dna.BasketTakeProfitMoney,2)+",";
      j += "\"dna_sl\":"       + DoubleToString(g_dna.BasketStopLossMoney,2)  +",";
      j += "\"dna_gen\":"      + IntegerToString(g_current_generation)      + ",";
      j += "\"cooldown\":"     + IntegerToString((int)MathMax(0,g_state.cooldown_until-TimeCurrent()))+",";
      j += "\"indicators\":{"  + StringSubstr(IndicatorTelemetryJSON(sym,false),1) + "},";
      if(ArraySize(r) > 0)
      {
         j += "\"open\":"  + DoubleToString(r[0].open,  DigitsOf(sym)) + ",";
         j += "\"high\":"  + DoubleToString(r[0].high,  DigitsOf(sym)) + ",";
         j += "\"low\":"   + DoubleToString(r[0].low,   DigitsOf(sym)) + ",";
         j += "\"close\":" + DoubleToString(r[0].close, DigitsOf(sym));
      }
      else j += "\"open\":0,\"high\":0,\"low\":0,\"close\":0";
      j += "}";

      FileWriteString(h, j);
      FileClose(h);
   }

   // --- ملف تاريخ الشموع (مصفوفة JSON تتراكم) ----------
   string histFile = "ea_bar_history.json";
   MqlRates rh[1]; CopyRates(sym, PERIOD_M1, 0, 1, rh);

   string entry = "{\"bar\":" + IntegerToString(g_rt_bar_count) +
                  ",\"b\":"   + DoubleToString(bal, 2) +
                  ",\"e\":"   + DoubleToString(eq,  2) +
                  ",\"p\":"   + DoubleToString(pnl, 2) +
                  ",\"pos\":" + IntegerToString(allP) +
                  IndicatorTelemetryJSON(sym,true);
   if(ArraySize(rh) > 0)
      entry += ",\"o\":" + DoubleToString(rh[0].open,  2) +
               ",\"h\":" + DoubleToString(rh[0].high,  2) +
               ",\"l\":" + DoubleToString(rh[0].low,   2) +
               ",\"c\":" + DoubleToString(rh[0].close, 2);
   entry += "}";

   if(!g_rt_history_started)
   {
      // أول شمعة — ابدأ ملف جديد
      int hw = FileOpen(histFile, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(hw != INVALID_HANDLE)
      {
         FileWriteString(hw, "[" + entry + "]");
         FileClose(hw);
      }
      g_rt_history_started = true;
   }
   else
   {
      // الشموع التالية — اقرأ واضف في النهاية
      string existing = "";
      int hr = FileOpen(histFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(hr != INVALID_HANDLE)
      {
         while(!FileIsEnding(hr)) existing += FileReadString(hr);
         FileClose(hr);
      }

      // اشطب ] الأخير وأضف الشمعة الجديدة
      if(StringLen(existing) > 1)
         existing = StringSubstr(existing, 0, StringLen(existing)-1) + "," + entry + "]";
      else
         existing = "[" + entry + "]";

      // لا تحفظ أكثر من 500 شمعة (حد الحجم)
      // تجاهل التحقق — Python يتعامل مع الحجم

      int hw = FileOpen(histFile, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(hw != INVALID_HANDLE)
      {
         FileWriteString(hw, existing);
         FileClose(hw);
      }
   }
}

// ─── رسم معلومات مباشرة على الشارت ─────────────────────
void DrawChartInfo()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl = BasketProfit();

   // حذف القديم
   ObjectsDeleteAll(0, "RT_");

   string labels[] = {
      "Balance: "  + DoubleToString(bal, 2) + "$",
      "Equity: "   + DoubleToString(eq,  2) + "$",
      "Open P&L: " + DoubleToString(pnl, 2) + "$",
      "Gap: "      + IntegerToString(g_dna.ExtraTightGapPoints) +
      "  Gen: "    + IntegerToString(g_current_generation) +
      "  Bar: "    + IntegerToString(g_rt_bar_count)
   };
   color colors[] = {
      (bal >= 100.0 ? clrLimeGreen : clrOrangeRed),
      clrDeepSkyBlue,
      (pnl >= 0.0 ? clrLimeGreen : clrOrangeRed),
      clrGold
   };

   for(int i = 0; i < 4; i++)
   {
      string n = "RT_" + IntegerToString(i);
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, n, OBJPROP_YDISTANCE, 18 + i*17);
      ObjectSetString (0, n, OBJPROP_TEXT,      labels[i]);
      ObjectSetInteger(0, n, OBJPROP_COLOR,     colors[i]);
      ObjectSetInteger(0, n, OBJPROP_FONTSIZE,  9);
      ObjectSetString (0, n, OBJPROP_FONT,      "Courier New");
      ObjectSetInteger(0, n, OBJPROP_BACK,      false);
   }
   ChartRedraw(0);
}

//====================================================================
// Expert Events
//====================================================================
int OnInit()
{
   if(InpForceChartSymbolOnly&&_Symbol!=GoldSymbol())
      { Print("[DNA] Attach on ",GoldSymbol()," current=",_Symbol); return INIT_FAILED; }

   if(!LoadGoldProfile()) return INIT_FAILED;

   // ════ DNA EVOLUTION ════
   if(InpUseDNAEvolution)
   {
      MathSrand((int)TimeCurrent());
      g_dna=SelectNextDNA();
   }
   else
      g_dna=DefaultDNA();

   ApplyDNA(g_dna);

   g_loaded=true;
   EventSetTimer(1);
   Log("DNA V7 started on "+g_profile.symbol+" Gen="+IntegerToString(g_current_generation));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Log("Stopped reason="+IntegerToString(reason));
}

void OnTick()  { if(InpAutoTrade) Process(); }
void OnTimer() { if(InpAutoTrade) Process(); }
//+------------------------------------------------------------------+
