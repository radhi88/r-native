//+------------------------------------------------------------------+
//| Agentic_Profiled_Grid_GOLD_LIVE.mq5                               |
//|                                                                  |
//| ✦ نسخة الحساب الحقيقي — مبسطة وآمنة ✦                            |
//| - عطل DNA Evolution افتراضياً (ثبته يدوياً)                      |
//| - Basket TP/SL مناسبة للرصيد الصغير                              |
//| - Gap مناسب للذهب (100-300 نقطة)                                 |
//| - One-Way Trail SL يمنع Chop Loop                                |
//+------------------------------------------------------------------+
#property strict
#property version "7.33"

#include <Trade/Trade.mqh>

CTrade trade;

//====================================================================
// Inputs — مبسطة للحساب الحقيقي
//====================================================================
input string InpProfileCsv                    = "agent_profiles_mql5.csv";
input bool   InpUseCommonFiles                = true;   // ✅ true = يقرأ/يكتب في Common\Files

input string InpGoldSymbol                    = "XAUUSDm";
input bool   InpForceChartSymbolOnly          = true;   // ✅ true = لازم يكون الشارت XAUUSDm

input bool   InpAutoTrade                     = true;   // ✅ true = يدخل صفقات حقيقية
input bool   InpDryRunPrintOnly               = false;  // ❌ false = صفقات حقيقية (لا تغير!)

input int    InpTimeframe                     = PERIOD_M1;
input int    InpRealtimeHistoryBars           = 200;    // آخر 200 شمعة M1 للداشبورد

// ✦ DNA Evolution + live control — يبدأ من القيم الحية ولا يستخدم ذاكرة خاسرة
input bool   InpUseDNAEvolution               = true;
input bool   InpDNAMutateFromBest             = true;
input double InpDNAMutationStrength           = 0.10;
input bool   InpDNAUseElitism                 = true;
input bool   InpDNAVerboseReport              = true;
input bool   InpDNAUseOnlyProfitableMemory    = true;

// ✦ Claude/agents live control file — تعديلات صغيرة ومحدودة فقط
input bool   InpUseLiveControl                = true;
input string InpLiveControlCsv                = "claude_live_control.csv";
input int    InpLiveControlEverySeconds       = 5;
input int    InpLiveControlMaxAgeSeconds      = 21600;
input int    InpLiveControlGapStepPoints      = 25;
input double InpLiveControlMoneyStep          = 0.25;
input double InpLiveControlFactorStep         = 0.05;
input bool   InpSaveLiveDNASnapshots          = true;
input int    InpSaveLiveDNASnapshotBars       = 10;

// ✦ إعدادات آمنة للرصيد الصغير ($100-$500) ✦
input int    InpExtraTightGapPoints           = 150;    // 150 نقطة للذهب (مناسب)
input int    InpModifyStepPoints              = 1;

input bool   InpUseStopReversePair            = true;
input bool   InpManagePairEveryTick           = true;
input bool   InpUseAdaptiveStopReverse        = true;   // يتعلم من لمس الستوبات ويغير المسافة
input int    InpPairModifyEverySeconds        = 5;      // لا يعدل SL/Pending كل tick
input int    InpPairModifyMinStepPoints       = 120;    // أقل فرق قبل تعديل الستوب/الأمر
input double InpGapSpreadMultiplier           = 2.20;   // أقل مسافة = السبريد * هذا الرقم
input double InpGapAtrMultiplier              = 0.18;   // أقل مسافة = ATR M1 * هذا الرقم
input int    InpAdaptiveMinGapPoints          = 150;
input int    InpAdaptiveMaxGapPoints          = 1500;
input int    InpAdaptiveGapStepPoints         = 75;
input double InpAdaptiveGridFactorStep        = 0.25;
input int    InpAdaptiveWinsToTighten         = 2;
input int    InpAdaptiveNoReverseMinutes      = 2;      // بعد خسارة، يوقف عكس فوري قصير
input bool   InpOneWayTrailOnly               = true;   // SL يتحرك للربح فقط
input int    InpMinHoldSeconds                = 30;     // أدنى وقت قبل تعديل SL
input int    InpChopMaxFlipsPerMin            = 4;      // كشف التذبذب

input bool   InpPairPositionSLWithPending     = true;
input bool   InpPendingHasNoOwnSLTP           = true;   // البندنج بدون SL/TP خاص
input bool   InpDeleteSameSidePending         = true;
input bool   InpDeleteDuplicates              = true;
input int    InpMaxOpenPositionsPerSymbol     = 2;
input bool   InpResolveHedgeImmediately       = true;
input bool   InpResolveHedgeKeepLatest        = true;

// ✦ Basket — مناسب للرصيد الصغير ✦
input bool   InpUseBasketTakeProfit           = true;
input double InpBasketTakeProfitMoney         = 2.00;   // $2 ربح (2% من $100)
input bool   InpUseBasketStopLoss             = true;
input double InpBasketStopLossMoney           = 5.00;   // $5 خسارة (5% من $100)
input bool   InpUseBasketEquityLock           = true;
input double InpBasketLockStartMoney          = 3.00;   // لما يوصل $3 ربح
input double InpBasketLockGiveBackMoney       = 1.50;   // يسمح يرجع $1.5

// ✦ Profit-Lock SL — يؤمن ربح الصفقة بسرعة بدل رجوعها خسارة ✦
input bool   InpUseSecureProfitSL             = true;
input double InpSecureProfitStartMoney        = 0.50;   // يبدأ التأمين من ربح عائم 50 سنت
input double InpSecureProfitLockMoney         = 0.50;   // هدف الربح الذي يحاول الـ SL قفله

input bool   InpUseFallbackInitialSLTP        = false;
input int    InpFallbackSLPoints              = 5000;
input int    InpFallbackTPPoints              = 5000;

input int    InpMinSecondsBetweenOrders       = 5;      // 5 ثواني بين الأوامر
input int    InpDeviationPoints               = 50;
input int    InpExtraStopBufferPoints         = 3;

input bool   InpUseSpreadFilter               = false;  // ← false أولاً
input double InpMaxSpreadToAtrRatioOverride   = 0.00;
input bool   InpUseBlockedHours               = false;
input string InpBlockedHours                  = "0,8,9,11,12,20";
input bool   InpUseFridayCloseFilter          = true;
input int    InpFridayStopHour                = 20;

input bool   InpUseCooldown                   = false;  // false = يبدأ فوراً بعد TP/SL/chop
input int    InpCooldownAfterBasketTPMinutes  = 0;
input int    InpCooldownAfterBasketSLMinutes  = 0;
input int    InpCooldownAfterLargeLossMinutes = 0;

input double InpLargeSingleLossMoney          = 3.00;   // خسارة كبيرة = $3
input double InpLotReductionFactor            = 0.50;
input double InpMinLotFactor                  = 0.25;
input double InpGridWidenFactor               = 1.25;
input double InpMaxGridFactor                 = 4.0;

input bool   InpRecoverAfterWins              = true;
input int    InpWinsToRecover                 = 3;      // 3 انتصارات للتعافي
input double InpRecoveryLotStep               = 0.15;
input double InpRecoveryGridStep              = 0.25;

input string InpInitialDirection              = "AUTO";
input bool   InpVerboseLogs                   = true;

// ═══════════════════════════════════════════════════════════════════
// ✦ Smart Entry Filters — مرشحات الدخول الذكية
// ═══════════════════════════════════════════════════════════════════
input bool   InpUseSmartEntry               = true;   // تفعيل الفلاتر الذكية كلها
// ── EMA Trend Filter ──
input int    InpFastEMAPeriod               = 8;      // EMA السريع (اتجاه قصير)
input int    InpSlowEMAPeriod               = 21;     // EMA البطيء (اتجاه متوسط)
input int    InpTrendEMAPeriod              = 50;     // EMA الرئيسي (اتجاه عام)
input bool   InpRequireAllEMAsAligned       = true;   // يشترط تطابق الثلاثة EMAs
// ── RSI Momentum Filter ──
input bool   InpUseRSIFilter                = true;   // تفعيل فلتر RSI
input int    InpRSIPeriod                   = 14;     // فترة RSI
input double InpRSIBuyMax                   = 65.0;   // حد RSI للشراء (فوقه = overbought)
input double InpRSISellMin                  = 35.0;   // حد RSI للبيع (تحته = oversold)
// ── Candle Confirmation ──
input bool   InpUseCandleConfirm            = true;   // يشترط تأكيد بالكاندل
input double InpCandleBodyRatio             = 0.40;   // نسبة الجسم من الـ range (0=كل شيء, 1=جسم كامل)
// ── Market Regime Filter ──
input bool   InpUseRegimeFilter             = true;   // لا تدخل في سوق متذبذب
input double InpATRRangingThreshold         = 0.70;   // إذا ATR الحالي < 70% من المتوسط = تذبذب

// ═══════════════════════════════════════════════════════════════════
// ✦ SMC — Smart Money Concepts (Order Blocks · FVG · BOS · CHoCH)
// ═══════════════════════════════════════════════════════════════════
input bool   InpUseSMCFilter              = true;    // تفعيل نظام SMC كاملاً
input bool   InpSMCRequireOBorFVG         = true;    // الدخول فقط عند OB أو FVG
input bool   InpSMCRequireStructure       = true;    // يشترط وجود BOS أو CHoCH
input int    InpSMCLookback               = 80;      // عمق البحث عن OB/FVG (شمعة)
input int    InpSMCStructureLookback      = 35;      // عمق البحث عن الهيكل (شمعة)
input double InpSMCImpulseRatio           = 1.2;     // حجم الـ impulse = ATR * هذا الرقم
input double InpSMCMinFVGSizeRatio        = 0.25;    // حجم FVG أدنى = ATR * هذا الرقم
input double InpSMCZoneTouchPct           = 0.60;    // السعر داخل 60% من الزون = هيت
input bool   InpSMCDrawOB                 = true;    // ارسم Order Blocks على الشارت
input bool   InpSMCDrawFVG                = true;    // ارسم Fair Value Gaps
input bool   InpSMCDrawBOS                = true;    // ارسم BOS / CHoCH
input bool   InpSMCLogDecisions           = true;    // حفظ كل قرار SMC للتعلم

//====================================================================
// DNA Struct (يُحتفظ للتوافق — لكن لا يُستخدم لو InpUseDNAEvolution=false)
//====================================================================
struct AgentDNA
{
   int    ExtraTightGapPoints;
   int    ModifyStepPoints;
   double BasketTakeProfitMoney;
   double BasketStopLossMoney;
   double BasketLockStartMoney;
   double BasketLockGiveBackMoney;
   int    CooldownAfterTPMinutes;
   int    CooldownAfterSLMinutes;
   int    CooldownAfterLossMinutes;
   double LotReductionFactor;
   double MinLotFactor;
   double RecoveryLotStep;
   double GridWidenFactor;
   double MaxGridFactor;
   double RecoveryGridStep;
   int    WinsToRecover;
   int    AtrBars;
   double fitness;
   int    generation;
   double profit_factor;
   double max_drawdown_pct;
   double total_trades;
   double net_profit;
};

#define DNA_MEMORY_FILE  "gold_dna_memory.csv"
#define DNA_MAX_RECORDS  100
#define DNA_ELITE_COUNT  5
#define DNA_MUTATION_RATE 0.25

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
   int      chop_flip_count;
   datetime chop_window_start;
   datetime last_position_open_time;
   datetime last_pair_manage_time;
   datetime last_secure_sl_time;
   int      adaptive_loss_streak;
   int      adaptive_win_streak;
   datetime adaptive_no_reverse_until;
};

// ─────────────────────────────────────────────────────────────────
// SMC Structs
// ─────────────────────────────────────────────────────────────────
#define SMC_MAX_OB   8
#define SMC_MAX_FVG  8

struct SMCOrderBlock
{
   double   high, low;
   datetime t_start;
   bool     bullish;    // true = demand (BUY zone), false = supply (SELL zone)
   bool     mitigated;
   bool     valid;
};

struct SMCFVG
{
   double   top, bottom;
   datetime t_bar;
   bool     bullish;
   bool     filled;
   bool     valid;
};

// ─────────────────────────────────────────────────────────────────
// SMC Global State
// ─────────────────────────────────────────────────────────────────
SMCOrderBlock g_ob[SMC_MAX_OB];
int           g_ob_count          = 0;
SMCFVG        g_fvg[SMC_MAX_FVG];
int           g_fvg_count         = 0;
bool          g_smc_bias_bullish  = false;
bool          g_smc_has_bos       = false;
bool          g_smc_has_choch     = false;
double        g_smc_bos_level     = 0.0;
double        g_smc_swing_high    = 0.0;
double        g_smc_swing_low     = 0.0;
string        g_smc_status        = "SMC: init";
datetime      g_smc_last_scan     = 0;

AgentProfile g_profile;
AgentState   g_state;
AgentDNA     g_dna;
bool         g_loaded = false;
int          g_current_generation = 1;

// ── Agent-Gate globals (confluence_signal.json) ──────────────────────────────
string   g_ext_signal_dir      = "NONE";
bool     g_ext_signal_approved = false;   // scalp approval (2+ directional votes)
bool     g_ext_swing_approved  = false;   // swing approval (4+ votes + LLM>=7)
string   g_ext_signal_mode     = "BLOCKED"; // "SCALP" | "SWING" | "BLOCKED"
double   g_swing_lot_mult      = 2.5;     // lot multiplier for swing mode
datetime g_ext_signal_time     = 0;
int      g_ext_dir_agreement   = 0;
// ── Agent Pending Orders (limit orders at key S/R levels from Python agents) ──────────
#define MAX_AGENT_PENDING 4
struct AgentPendingLevel
{
   string   order_type;    // "BUY_LIMIT" or "SELL_LIMIT"
   double   price;
   string   reason;
   int      confidence;
   int      expiry_hours;
};
AgentPendingLevel g_agent_pending[MAX_AGENT_PENDING];
int               g_agent_pending_count  = 0;
datetime          g_agent_pending_placed = 0; // last time we checked/placed agent pending orders
// ─────────────────────────────────────────────────────────────────────────────

int          g_rt_bar_count  = 0;
double       g_rt_peak_bal   = 0.0;
double       g_rt_start_bal  = 0.0;
bool         g_rt_history_started = false;
datetime     g_last_control_check = 0;
long         g_last_control_epoch = 0;
int          g_last_dna_snapshot_bar = 0;
double       g_secure_profit_start = 0.0;
double       g_secure_profit_lock  = 0.0;
bool         g_trade_allowed = false;
string       g_trade_block_reason = "initializing";
datetime     g_trade_block_until = 0;

//====================================================================
// DNA Functions (للتوافق — تعمل لو InpUseDNAEvolution=true)
//====================================================================
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

#include <GridDNA_Common.mqh>   // PlutoBrain: shared Grid helpers

double MutateDouble(double val, double mn, double mx, double strength)
{
   if(MathRand() / 32767.0 > DNA_MUTATION_RATE) return val;
   double range = (mx - mn) * strength;
   double delta = (MathRand() / 32767.0 * 2.0 - 1.0) * range;
   return ClampD(val + delta, mn, mx);
}

int MutateInt(int val, int mn, int mx, double strength)
{
   if(MathRand() / 32767.0 > DNA_MUTATION_RATE) return val;
   double range = (mx - mn) * strength;
   int delta = (int)MathRound((MathRand() / 32767.0 * 2.0 - 1.0) * range);
   return ClampI(val + delta, mn, mx);
}

int StepIntToward(int current, int target, int maxStep, int mn, int mx)
{
   target = ClampI(target, mn, mx);
   if(current < target) return ClampI(current + MathMin(maxStep, target-current), mn, mx);
   if(current > target) return ClampI(current - MathMin(maxStep, current-target), mn, mx);
   return ClampI(current, mn, mx);
}

double StepDoubleToward(double current, double target, double maxStep, double mn, double mx)
{
   target = ClampD(target, mn, mx);
   if(current < target) return ClampD(current + MathMin(maxStep, target-current), mn, mx);
   if(current > target) return ClampD(current - MathMin(maxStep, current-target), mn, mx);
   return ClampD(current, mn, mx);
}

AgentDNA MutateDNA(const AgentDNA &parent, double strength)
{
   AgentDNA child = parent;
   double s = strength * InpDNAMutationStrength / 0.15;

   child.ExtraTightGapPoints     = MutateInt   (parent.ExtraTightGapPoints,   50,  500,  s);
   child.ModifyStepPoints        = MutateInt   (parent.ModifyStepPoints,         1,    5,  s);
   child.BasketTakeProfitMoney   = MutateDouble(parent.BasketTakeProfitMoney,   0.5, 10.0, s);
   child.BasketStopLossMoney     = MutateDouble(parent.BasketStopLossMoney,     1.0, 20.0, s);
   child.BasketLockStartMoney    = MutateDouble(parent.BasketLockStartMoney,    0.5, 10.0, s);
   child.BasketLockGiveBackMoney = MutateDouble(parent.BasketLockGiveBackMoney, 0.3,  5.0, s);
   child.CooldownAfterTPMinutes  = MutateInt   (parent.CooldownAfterTPMinutes,    1,  15,  s);
   child.CooldownAfterSLMinutes  = MutateInt   (parent.CooldownAfterSLMinutes,    5,  45,  s);
   child.CooldownAfterLossMinutes= MutateInt   (parent.CooldownAfterLossMinutes, 10,  90,  s);
   child.LotReductionFactor      = MutateDouble(parent.LotReductionFactor,      0.1,  0.9, s);
   child.MinLotFactor            = MutateDouble(parent.MinLotFactor,            0.1,  0.5, s);
   child.RecoveryLotStep         = MutateDouble(parent.RecoveryLotStep,         0.05, 0.5, s);
   child.GridWidenFactor         = MutateDouble(parent.GridWidenFactor,         1.0,  3.0, s);
   child.MaxGridFactor           = MutateDouble(parent.MaxGridFactor,           1.5,  6.0, s);
   child.RecoveryGridStep        = MutateDouble(parent.RecoveryGridStep,        0.05, 0.5, s);
   child.WinsToRecover           = MutateInt   (parent.WinsToRecover,             1,   8,  s);
   child.AtrBars                 = MutateInt   (parent.AtrBars,                  10,  80,  s);

   child.fitness          = 0.0;
   child.generation       = parent.generation + 1;
   child.profit_factor    = 0.0;
   child.max_drawdown_pct = 100.0;
   child.total_trades     = 0.0;
   child.net_profit       = 0.0;

   return child;
}

AgentDNA CrossoverDNA(const AgentDNA &a, const AgentDNA &b)
{
   AgentDNA child;
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

double CalcFitness(double pf, double dd_pct, double trades, double net_profit)
{
   if(trades < 3.0) return -999.0;
   if(net_profit <= 0.0) return -MathAbs(net_profit);
   double dd_factor = 1.0 - ClampD(dd_pct / 100.0, 0.0, 0.99);
   double pf_capped = MathMin(pf, 10.0);
   return pf_capped * MathSqrt(trades) * dd_factor;
}

string DNAToCSV(const AgentDNA &d)
{
   return IntegerToString(d.generation)             + "," +
          DoubleToString(d.fitness, 4)              + "," +
          DoubleToString(d.profit_factor, 4)        + "," +
          DoubleToString(d.max_drawdown_pct, 4)     + "," +
          DoubleToString(d.total_trades, 0)         + "," +
          DoubleToString(d.net_profit, 2)           + "," +
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

bool CSVToDNA(string line, AgentDNA &d)
{
   string parts[];
   int n = StringSplit(line, ',', parts);
   if(n < 23) return false;
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

int LoadDNAMemory(AgentDNA &records[], int &count)
{
   count = 0;
   ArrayResize(records, DNA_MAX_RECORDS);
   int flags = FILE_READ | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles) flags |= FILE_COMMON;
   int h = FileOpen(DNA_MEMORY_FILE, flags, ',');
   if(h == INVALID_HANDLE) return 0;
   for(int k=0; k<23 && !FileIsEnding(h); k++) FileReadString(h);
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
      for(int c=0; c<23; c++){ if(c>0) line += ","; line += parts[c]; }
      AgentDNA d;
      if(CSVToDNA(line, d)){ records[count] = d; count++; }
   }
   FileClose(h);
   return count;
}

void SaveDNAToMemory(const AgentDNA &newRecord)
{
   AgentDNA records[];
   int count = 0;
   LoadDNAMemory(records, count);
   if(count < DNA_MAX_RECORDS)
   {
      records[count] = newRecord;
      count++;
   }
   else
   {
      int worstIdx = 0;
      for(int i=1; i<count; i++)
         if(records[i].fitness < records[worstIdx].fitness) worstIdx = i;
      if(newRecord.fitness > records[worstIdx].fitness) records[worstIdx] = newRecord;
   }
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles) flags |= FILE_COMMON;
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

void SortDNAByFitness(AgentDNA &arr[], int n)
{
   for(int i=0; i<n-1; i++)
      for(int j=i+1; j<n; j++)
         if(arr[j].fitness > arr[i].fitness)
         { AgentDNA tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp; }
}

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
   if(InpDNAUseOnlyProfitableMemory && (records[0].fitness<=0.0 || records[0].net_profit<=0.0))
   {
      AgentDNA seed = DefaultDNA();
      seed.generation = g_current_generation;
      Print("[DNA] Best memory is not profitable — using live seed values and learning forward Gen", seed.generation);
      return seed;
   }

   if(!InpDNAMutateFromBest) return records[0];
   int eliteN = MathMin(DNA_ELITE_COUNT, count);
   if(count >= 2 && MathRand() % 3 == 0)
   {
      int idxA = MathRand() % eliteN;
      int idxB = MathRand() % eliteN;
      while(idxB == idxA && eliteN > 1) idxB = MathRand() % eliteN;
      AgentDNA child = CrossoverDNA(records[idxA], records[idxB]);
      child = MutateDNA(child, InpDNAMutationStrength);
      Print("[DNA] Strategy: CROSSOVER Gen(", records[idxA].generation, "+", records[idxB].generation, ") → Gen", child.generation);
      return child;
   }
   else
   {
      AgentDNA child = MutateDNA(records[0], InpDNAMutationStrength);
      Print("[DNA] Strategy: MUTATION from best Gen", records[0].generation, " → Gen", child.generation);
      return child;
   }
}

double OnTester()
{
   if(!InpUseDNAEvolution) return 0.0;
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd_pct = TesterStatistics(STAT_EQUITY_DD_RELATIVE);
   double trades = TesterStatistics(STAT_TRADES);
   double net_profit = TesterStatistics(STAT_PROFIT);
   double sharpe = TesterStatistics(STAT_SHARPE_RATIO);
   double fitness = CalcFitness(pf, dd_pct, trades, net_profit);
   AgentDNA result = g_dna;
   result.fitness = fitness;
   result.profit_factor = pf;
   result.max_drawdown_pct = dd_pct;
   result.total_trades = trades;
   result.net_profit = net_profit;
   result.generation = g_current_generation;
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

void Log(string msg)
{
   if(InpVerboseLogs) Print("[GOLD_LIVE] ", msg);
}

int ExactGapPoints(string symbol)
{
   int raw = BrokerMinimumStopPoints(symbol) + MathMax(0, g_dna.ExtraTightGapPoints);
   raw = (int)MathRound(raw * g_state.grid_factor);
   if(InpUseAdaptiveStopReverse)
   {
      double spr = SpreadPoints(symbol);
      if(spr > 0.0 && spr < 999999.0)
         raw = MathMax(raw, (int)MathCeil(spr * InpGapSpreadMultiplier));

      double atr = CalcATRPoints(symbol, 14);
      if(atr > 0.0)
         raw = MathMax(raw, (int)MathCeil(atr * InpGapAtrMultiplier));

      raw = ClampI(raw, MathMax(BrokerMinimumStopPoints(symbol), InpAdaptiveMinGapPoints), InpAdaptiveMaxGapPoints);
   }
   return MathMax(BrokerMinimumStopPoints(symbol), raw);
}

string BoolJson(bool v) { return v ? "true" : "false"; }

bool TradingAllowedNow(string symbol, string &reason)
{
   if(TimeCurrent() < g_trade_block_until)
   {
      reason = "trade_disabled_recent_retcode";
      return false;
   }

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
   {
      reason = "terminal_algo_disabled";
      return false;
   }

   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      reason = "ea_algo_disabled_on_chart";
      return false;
   }

   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   {
      reason = "account_trade_disabled";
      return false;
   }

   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
   {
      reason = "server_auto_trading_disabled";
      return false;
   }

   long tradeMode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED)
   {
      reason = "symbol_trade_disabled";
      return false;
   }

   if(tradeMode == SYMBOL_TRADE_MODE_CLOSEONLY)
   {
      reason = "symbol_close_only";
      return false;
   }

   reason = "ok";
   return true;
}

void RememberTradeResult(bool ok, string action)
{
   if(ok) return;
   int rc = (int)trade.ResultRetcode();
   if(rc == 10026 || rc == 10027)
   {
      g_trade_allowed = false;
      g_trade_block_reason = (rc == 10026 ? "server_auto_trading_disabled" : "terminal_algo_disabled");
      g_trade_block_until = TimeCurrent() + 15;
      Log(action+" blocked ret="+IntegerToString(rc)+" pause=15s");
   }
}

bool TradeActionAllowed(string action)
{
   string reason = "";
   if(!TradingAllowedNow(g_profile.symbol, reason))
   {
      g_trade_allowed = false;
      g_trade_block_reason = reason;
      Log(action+" skipped: "+reason);
      return false;
   }
   g_trade_allowed = true;
   g_trade_block_reason = "ok";
   return true;
}

bool CanSend()
{
   if((TimeCurrent()-g_state.last_order_time)<InpMinSecondsBetweenOrders) return false;
   return true;
}
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
   g_state.last_pair_manage_time=0; g_state.last_secure_sl_time=0;
   g_state.adaptive_loss_streak=0; g_state.adaptive_win_streak=0;
   g_state.adaptive_no_reverse_until=0;
   return true;
}

//--------------------------------------------------------------------
// CalcRSI — حساب RSI بسيط من الـ close prices
//--------------------------------------------------------------------
double CalcRSI(string symbol, int period)
{
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,0,period+30,rates);
   if(copied<period+5) return 50.0;
   double gain=0, loss=0;
   for(int i=1;i<=period;i++)
   {
      double diff=rates[i-1].close - rates[i].close;
      if(diff>0) gain+=diff; else loss-=diff;
   }
   gain/=period; loss/=period;
   if(loss==0) return 100.0;
   double rs=gain/loss;
   return 100.0 - 100.0/(1.0+rs);
}

//--------------------------------------------------------------------
// IsRangingMarket — هل السوق في تذبذب عشوائي؟
//--------------------------------------------------------------------
bool IsRangingMarket(string symbol)
{
   if(!InpUseRegimeFilter) return false;
   double cur_atr = CalcATRPoints(symbol, 14);
   double avg_atr = CalcATRPoints(symbol, g_dna.AtrBars);
   if(avg_atr<=0) return false;
   bool ranging = (cur_atr/avg_atr < InpATRRangingThreshold);
   if(ranging) Log("Regime: RANGING cur_atr="+DoubleToString(cur_atr,1)+" avg="+DoubleToString(avg_atr,1)+" ratio="+DoubleToString(cur_atr/avg_atr,2));
   return ranging;
}

//--------------------------------------------------------------------
// HasConfirmingCandle — هل الكاندل الأخيرة تؤكد الاتجاه؟
//--------------------------------------------------------------------
bool HasConfirmingCandle(string symbol, bool buy_signal)
{
   if(!InpUseCandleConfirm) return true;
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   if(CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,1,3,rates)<2) return true;
   double body  = MathAbs(rates[0].close - rates[0].open);
   double range = rates[0].high - rates[0].low;
   if(range<=0) return false;
   bool bullish = (rates[0].close > rates[0].open);
   bool strong  = (body/range >= InpCandleBodyRatio);
   bool momentum= buy_signal ? (rates[0].close > rates[1].close) : (rates[0].close < rates[1].close);
   if(buy_signal)  return (bullish && strong && momentum);
   else            return (!bullish && strong && momentum);
}

//--------------------------------------------------------------------
// SmartDirectionOf — اتجاه ذكي بثلاثة EMAs + RSI + كاندل
//--------------------------------------------------------------------
string SmartDirectionOf(string symbol)
{
   // إذا المستخدم حدد اتجاهاً يدوياً، احترمه
   string d=InpInitialDirection; StringToUpper(d);
   if(d=="BUY")  return "BUY";
   if(d=="SELL") return "SELL";

   // إذا الفلاتر الذكية مطفية، استخدم الدالة القديمة
   if(!InpUseSmartEntry)
   {
      double f=EMAFromCloses(symbol,9,40), s=EMAFromCloses(symbol,21,80);
      if(f==0||s==0) return "BUY";
      return (f>=s?"BUY":"SELL");
   }

   // ── حساب الثلاثة EMAs ──
   double fast  = EMAFromCloses(symbol, InpFastEMAPeriod,  100);
   double slow  = EMAFromCloses(symbol, InpSlowEMAPeriod,  120);
   double trend = EMAFromCloses(symbol, InpTrendEMAPeriod, 160);
   if(fast==0||slow==0||trend==0) return "NONE";

   bool buy_ema  = InpRequireAllEMAsAligned ? (fast>slow && slow>trend) : (fast>slow);
   bool sell_ema = InpRequireAllEMAsAligned ? (fast<slow && slow<trend) : (fast<slow);

   if(!buy_ema && !sell_ema)
   {
      Log("SmartDir: EMAs mixed fast="+DoubleToString(fast,2)+
          " slow="+DoubleToString(slow,2)+" trend="+DoubleToString(trend,2));
      return "NONE";
   }

   // ── فلتر RSI ──
   double rsi=50.0;
   if(InpUseRSIFilter) rsi=CalcRSI(symbol,InpRSIPeriod);

   if(buy_ema)
   {
      if(InpUseRSIFilter && rsi>=InpRSIBuyMax)
      {
         Log("SmartDir: BUY blocked RSI="+DoubleToString(rsi,1)+" >= max="+DoubleToString(InpRSIBuyMax,1));
         return "NONE";
      }
      return "BUY";
   }
   // sell_ema
   if(InpUseRSIFilter && rsi<=InpRSISellMin)
   {
      Log("SmartDir: SELL blocked RSI="+DoubleToString(rsi,1)+" <= min="+DoubleToString(InpRSISellMin,1));
      return "NONE";
   }
   return "SELL";
}

//--------------------------------------------------------------------
// DirectionOf — الدالة القديمة (تُستدعى من SmartDirectionOf إذا Smart=false)
//--------------------------------------------------------------------
//====================================================================
// ✦ SMC — Smart Money Concepts Engine
//====================================================================

//--------------------------------------------------------------------
// ScanOrderBlocks — آخر شمعة معاكسة قبل impulse = Order Block
//--------------------------------------------------------------------
void ScanOrderBlocks(string symbol, double atr)
{
   g_ob_count = 0;
   if(atr <= 0.0) return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, (ENUM_TIMEFRAMES)InpTimeframe, 0, InpSMCLookback + 10, rates);
   if(copied < 8) return;

   double impulse_min = atr * InpSMCImpulseRatio;
   double current     = rates[0].close;

   for(int i = 4; i < copied - 3 && g_ob_count < SMC_MAX_OB; i++)
   {
      // ── Bullish OB: آخر شمعة هابطة قبل ارتفاع قوي = demand zone ──
      if(rates[i].close < rates[i].open)
      {
         double move = 0;
         for(int j = i - 1; j >= MathMax(0, i - 4); j--)
            move += rates[j].high - rates[j].low;
         if(move >= impulse_min)
         {
            SMCOrderBlock ob;
            ob.high      = rates[i].high;
            ob.low       = rates[i].low;
            ob.t_start   = rates[i].time;
            ob.bullish   = true;
            ob.mitigated = (current < rates[i].low * 0.9995);
            ob.valid     = !ob.mitigated;
            if(ob.valid) g_ob[g_ob_count++] = ob;
         }
      }

      // ── Bearish OB: آخر شمعة صاعدة قبل هبوط قوي = supply zone ──
      if(rates[i].close > rates[i].open && g_ob_count < SMC_MAX_OB)
      {
         double fall = 0;
         for(int j = i - 1; j >= MathMax(0, i - 4); j--)
            fall += rates[j].high - rates[j].low;
         if(fall >= impulse_min)
         {
            SMCOrderBlock ob;
            ob.high      = rates[i].high;
            ob.low       = rates[i].low;
            ob.t_start   = rates[i].time;
            ob.bullish   = false;
            ob.mitigated = (current > rates[i].high * 1.0005);
            ob.valid     = !ob.mitigated;
            if(ob.valid) g_ob[g_ob_count++] = ob;
         }
      }
   }
}

//--------------------------------------------------------------------
// ScanFVG — Fair Value Gaps (فجوات سعرية غير مملوءة)
//--------------------------------------------------------------------
void ScanFVG(string symbol, double atr)
{
   g_fvg_count = 0;
   if(atr <= 0.0) return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, (ENUM_TIMEFRAMES)InpTimeframe, 0, InpSMCLookback + 5, rates);
   if(copied < 5) return;

   double min_gap = atr * InpSMCMinFVGSizeRatio;
   double current = rates[0].close;

   for(int i = 1; i < copied - 2 && g_fvg_count < SMC_MAX_FVG; i++)
   {
      // ── Bullish FVG: فجوة صاعدة لم تُملأ ──
      double bg = rates[i - 1].low - rates[i + 1].high;
      if(bg >= min_gap)
      {
         SMCFVG fvg;
         fvg.top    = rates[i - 1].low;
         fvg.bottom = rates[i + 1].high;
         fvg.t_bar  = rates[i].time;
         fvg.bullish = true;
         fvg.filled  = (current < fvg.bottom + (fvg.top - fvg.bottom) * 0.15);
         fvg.valid   = !fvg.filled;
         if(fvg.valid) g_fvg[g_fvg_count++] = fvg;
      }
      // ── Bearish FVG: فجوة هابطة لم تُملأ ──
      if(g_fvg_count < SMC_MAX_FVG)
      {
         double dbg = rates[i + 1].low - rates[i - 1].high;
         if(dbg >= min_gap)
         {
            SMCFVG fvg;
            fvg.top    = rates[i + 1].low;
            fvg.bottom = rates[i - 1].high;
            fvg.t_bar  = rates[i].time;
            fvg.bullish = false;
            fvg.filled  = (current > fvg.top - (fvg.top - fvg.bottom) * 0.15);
            fvg.valid   = !fvg.filled;
            if(fvg.valid) g_fvg[g_fvg_count++] = fvg;
         }
      }
   }
}

//--------------------------------------------------------------------
// ScanMarketStructure — BOS / CHoCH
//--------------------------------------------------------------------
void ScanMarketStructure(string symbol)
{
   g_smc_has_bos   = false;
   g_smc_has_choch = false;
   g_smc_bos_level = 0.0;
   g_smc_swing_high = 0.0;
   g_smc_swing_low  = 9999999.0;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, (ENUM_TIMEFRAMES)InpTimeframe, 0, InpSMCStructureLookback + 5, rates);
   if(copied < 10) { if(!InpSMCRequireStructure) g_smc_has_bos = true; return; }

   int sh_idx = -1, sl_idx = -1;
   for(int i = 2; i < copied - 2; i++)
   {
      if(rates[i].high > rates[i-1].high && rates[i].high > rates[i+1].high)
         if(rates[i].high > g_smc_swing_high) { g_smc_swing_high = rates[i].high; sh_idx = i; }
      if(rates[i].low < rates[i-1].low && rates[i].low < rates[i+1].low)
         if(rates[i].low < g_smc_swing_low)   { g_smc_swing_low  = rates[i].low;  sl_idx = i; }
   }

   double cur = rates[0].close;
   if(sh_idx > 0 && cur > g_smc_swing_high)
   {
      g_smc_bias_bullish = true;  g_smc_has_bos = true;
      g_smc_bos_level = g_smc_swing_high;
      g_smc_has_choch = (sl_idx > 0 && sl_idx < sh_idx);
   }
   else if(sl_idx > 0 && cur < g_smc_swing_low)
   {
      g_smc_bias_bullish = false; g_smc_has_bos = true;
      g_smc_bos_level = g_smc_swing_low;
      g_smc_has_choch = (sh_idx > 0 && sh_idx < sl_idx);
   }
   else
   {
      g_smc_bias_bullish = (cur > (g_smc_swing_high + g_smc_swing_low) * 0.5);
      if(!InpSMCRequireStructure) g_smc_has_bos = true;
   }
}

//--------------------------------------------------------------------
// IsAtSMCZone — السعر عند OB أو FVG مع تطابق الاتجاه
//--------------------------------------------------------------------
bool IsAtSMCZone(string sym, bool buy_signal, string &hit_type)
{
   if(!InpUseSMCFilter) { hit_type = "off"; return true; }
   double price = BidOf(sym);
   hit_type = "";

   for(int i = 0; i < g_ob_count; i++)
   {
      if(!g_ob[i].valid || g_ob[i].bullish != buy_signal) continue;
      double sz  = g_ob[i].high - g_ob[i].low;
      double mgn = sz * (1.0 - InpSMCZoneTouchPct);
      if(price >= g_ob[i].low - mgn && price <= g_ob[i].high + mgn)
         { hit_type = "OB"; return true; }
   }
   for(int i = 0; i < g_fvg_count; i++)
   {
      if(!g_fvg[i].valid || g_fvg[i].bullish != buy_signal) continue;
      double sz  = g_fvg[i].top - g_fvg[i].bottom;
      double mgn = sz * (1.0 - InpSMCZoneTouchPct);
      if(price >= g_fvg[i].bottom - mgn && price <= g_fvg[i].top + mgn)
         { hit_type = "FVG"; return true; }
   }

   if(InpSMCRequireStructure && !g_smc_has_bos)
      { hit_type = "noStr"; return false; }
   if(InpSMCRequireStructure && g_smc_has_bos && g_smc_bias_bullish != buy_signal)
      { hit_type = "struMismatch"; return false; }

   hit_type = "noZone";
   return false;
}

//--------------------------------------------------------------------
// DrawSMCZones — رسم المناطق على شارت MT5
//--------------------------------------------------------------------
void DrawSMCZones(string sym)
{
   ObjectsDeleteAll(0, "SMC_OB_");
   ObjectsDeleteAll(0, "SMC_FVG_");
   ObjectsDeleteAll(0, "SMC_BOS");

   int period_sec = PeriodSeconds((ENUM_TIMEFRAMES)InpTimeframe);
   datetime t_right = TimeCurrent() + (datetime)(period_sec * 20);

   if(InpSMCDrawOB)
   {
      for(int i = 0; i < g_ob_count; i++)
      {
         if(!g_ob[i].valid) continue;
         string nm = "SMC_OB_" + IntegerToString(i);
         color  c  = g_ob[i].bullish ? C'34,139,34' : C'178,34,34';
         ObjectCreate(0, nm, OBJ_RECTANGLE, 0, g_ob[i].t_start, g_ob[i].high, t_right, g_ob[i].low);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
         ObjectSetInteger(0, nm, OBJPROP_FILL, true);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         string lbl = "SMC_OB_L" + IntegerToString(i);
         ObjectCreate(0, lbl, OBJ_TEXT, 0, g_ob[i].t_start, g_ob[i].bullish ? g_ob[i].high : g_ob[i].low);
         ObjectSetString (0, lbl, OBJPROP_TEXT,    g_ob[i].bullish ? "▲OB" : "▼OB");
         ObjectSetInteger(0, lbl, OBJPROP_COLOR,   c);
         ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE, 7);
         ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
      }
   }

   if(InpSMCDrawFVG)
   {
      for(int i = 0; i < g_fvg_count; i++)
      {
         if(!g_fvg[i].valid) continue;
         string nm = "SMC_FVG_" + IntegerToString(i);
         color  c  = g_fvg[i].bullish ? C'0,100,200' : C'150,0,180';
         ObjectCreate(0, nm, OBJ_RECTANGLE, 0, g_fvg[i].t_bar, g_fvg[i].top, t_right, g_fvg[i].bottom);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
         ObjectSetInteger(0, nm, OBJPROP_FILL, true);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         string lbl = "SMC_FVG_L" + IntegerToString(i);
         ObjectCreate(0, lbl, OBJ_TEXT, 0, g_fvg[i].t_bar, g_fvg[i].bullish ? g_fvg[i].top : g_fvg[i].bottom);
         ObjectSetString (0, lbl, OBJPROP_TEXT,    g_fvg[i].bullish ? "FVG↑" : "FVG↓");
         ObjectSetInteger(0, lbl, OBJPROP_COLOR,   c);
         ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE, 7);
         ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
      }
   }

   if(InpSMCDrawBOS && g_smc_has_bos && g_smc_bos_level > 0)
   {
      datetime t0 = iTime(sym, (ENUM_TIMEFRAMES)InpTimeframe, InpSMCStructureLookback);
      color bc = g_smc_bias_bullish ? clrLimeGreen : clrOrangeRed;
      ObjectCreate(0, "SMC_BOS_line", OBJ_TREND, 0, t0, g_smc_bos_level, t_right, g_smc_bos_level);
      ObjectSetInteger(0, "SMC_BOS_line", OBJPROP_COLOR, bc);
      ObjectSetInteger(0, "SMC_BOS_line", OBJPROP_STYLE, STYLE_DASHDOT);
      ObjectSetInteger(0, "SMC_BOS_line", OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, "SMC_BOS_line", OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, "SMC_BOS_line", OBJPROP_SELECTABLE, false);
      ObjectCreate(0, "SMC_BOS_lbl", OBJ_TEXT, 0, t0, g_smc_bos_level);
      ObjectSetString (0, "SMC_BOS_lbl", OBJPROP_TEXT,
                        (g_smc_has_choch ? "⚡CHoCH " : "◆BOS ") + DoubleToString(g_smc_bos_level, 1));
      ObjectSetInteger(0, "SMC_BOS_lbl", OBJPROP_COLOR, bc);
      ObjectSetInteger(0, "SMC_BOS_lbl", OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, "SMC_BOS_lbl", OBJPROP_SELECTABLE, false);
   }

   ChartRedraw(0);
}

//--------------------------------------------------------------------
// UpdateSMC — مسح كامل عند كل شمعة جديدة
//--------------------------------------------------------------------
void UpdateSMC(string sym)
{
   if(!InpUseSMCFilter) return;
   double atr = CalcATRPoints(sym, 14);
   if(atr <= 0) return;
   ScanOrderBlocks(sym, atr);
   ScanFVG(sym, atr);
   ScanMarketStructure(sym);
   DrawSMCZones(sym);
   g_smc_status = "OB:" + IntegerToString(g_ob_count) +
                  " FVG:" + IntegerToString(g_fvg_count) +
                  " " + (g_smc_has_bos ? (g_smc_has_choch ? "CHoCH" : "BOS") : "---") +
                  (g_smc_bias_bullish ? " ↑Bias" : " ↓Bias");
   g_smc_last_scan = TimeCurrent();
}

//--------------------------------------------------------------------
// LogSMCDecision — تسجيل كل قرار للتعلم التراكمي
//--------------------------------------------------------------------
void LogSMCDecision(string sym, string dir, bool ob_hit, bool fvg_hit,
                    bool structure_ok, double rsi, string decision, string reason)
{
   if(!InpSMCLogDecisions) return;
   string fname  = "smc_decisions.csv";
   bool   is_new = !FileIsExist(fname, FILE_COMMON);
   int h = FileOpen(fname, FILE_WRITE|FILE_READ|FILE_SHARE_READ|FILE_ANSI|FILE_TXT|FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return;
   if(is_new)
      FileWrite(h, "datetime,symbol,direction,ob_hit,fvg_hit,structure_ok,"
                   "rsi,decision,reason,balance,equity,ob_count,fvg_count,bias");
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES) + "," +
               sym + "," + dir + "," +
               (ob_hit       ? "1":"0") + "," +
               (fvg_hit      ? "1":"0") + "," +
               (structure_ok ? "1":"0") + "," +
               DoubleToString(rsi, 1) + "," +
               decision + "," + reason + "," +
               DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "," +
               DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),  2) + "," +
               IntegerToString(g_ob_count) + "," +
               IntegerToString(g_fvg_count) + "," +
               (g_smc_bias_bullish ? "BUY" : "SELL"));
   FileClose(h);
}

bool MoneyToPriceDistance(string symbol, double volume, double money, double &distance)
{
   double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   if(tickValue<=0.0)
      tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);

   if(tickSize<=0.0 || tickValue<=0.0 || volume<=0.0 || money<=0.0)
      return false;

   distance = (money / (tickValue * volume)) * tickSize;
   return (distance>0.0);
}

double EstimateProfitAtPrice(string symbol, ENUM_POSITION_TYPE type, double openPrice, double price, double volume)
{
   double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   if(tickValue<=0.0)
      tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);

   if(tickSize<=0.0 || tickValue<=0.0 || volume<=0.0)
      return 0.0;

   double delta = (type==POSITION_TYPE_BUY) ? (price-openPrice) : (openPrice-price);
   if(delta<=0.0)
      return 0.0;

   return (delta / tickSize) * tickValue * volume;
}

struct LiveControl
{
   long   epoch;
   int    bar;
   string action;
   int    confidence;
   int    gap;
   double tp;
   double sl;
   double lock_start;
   double lock_giveback;
   double secure_start;
   double secure_lock;
   int    modify_step;
   double lot_factor;
   double grid_factor;
   double profit_factor;
   double drawdown_pct;
   double spread_points;
   string reason_code;
};

bool ReadLiveControl(LiveControl &c)
{
   int flags = FILE_READ | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles) flags |= FILE_COMMON;

   int h = FileOpen(InpLiveControlCsv, flags, ',');
   if(h == INVALID_HANDLE)
      return false;

   for(int i=0; i<18 && !FileIsEnding(h); i++)
      FileReadString(h);

   if(FileIsEnding(h))
   {
      FileClose(h);
      return false;
   }

   c.epoch         = (long)StringToInteger(FileReadString(h));
   c.bar           = (int)StringToInteger(FileReadString(h));
   c.action        = FileReadString(h);
   c.confidence    = (int)StringToInteger(FileReadString(h));
   c.gap           = (int)StringToInteger(FileReadString(h));
   c.tp            = StringToDouble(FileReadString(h));
   c.sl            = StringToDouble(FileReadString(h));
   c.lock_start    = StringToDouble(FileReadString(h));
   c.lock_giveback = StringToDouble(FileReadString(h));
   c.secure_start  = StringToDouble(FileReadString(h));
   c.secure_lock   = StringToDouble(FileReadString(h));
   c.modify_step   = (int)StringToInteger(FileReadString(h));
   c.lot_factor    = StringToDouble(FileReadString(h));
   c.grid_factor   = StringToDouble(FileReadString(h));
   c.profit_factor = StringToDouble(FileReadString(h));
   c.drawdown_pct  = StringToDouble(FileReadString(h));
   c.spread_points = StringToDouble(FileReadString(h));
   c.reason_code   = FileReadString(h);

   FileClose(h);
   return (c.confidence > 0);
}

bool LiveHistoryStats(double &trades, double &grossProfit, double &grossLoss)
{
   trades = 0.0;
   grossProfit = 0.0;
   grossLoss = 0.0;

   if(!HistorySelect(TimeCurrent()-86400*30, TimeCurrent()))
      return false;

   int total = HistoryDealsTotal();
   for(int i=0; i<total; i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(!deal) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != g_profile.symbol) continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != g_profile.magic) continue;

      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_INOUT && entry!=DEAL_ENTRY_OUT_BY)
         continue;

      double profit = HistoryDealGetDouble(deal, DEAL_PROFIT)
                    + HistoryDealGetDouble(deal, DEAL_SWAP)
                    + HistoryDealGetDouble(deal, DEAL_COMMISSION);

      trades += 1.0;
      if(profit > 0.0) grossProfit += profit;
      else if(profit < 0.0) grossLoss += MathAbs(profit);
   }

   return true;
}

void SaveLiveDNASnapshot(string reason, bool force=false)
{
   if(!InpSaveLiveDNASnapshots) return;
   if(!force && InpSaveLiveDNASnapshotBars>0 && (g_rt_bar_count-g_last_dna_snapshot_bar)<InpSaveLiveDNASnapshotBars)
      return;

   double trades=0.0, grossProfit=0.0, grossLoss=0.0;
   LiveHistoryStats(trades, grossProfit, grossLoss);

   double bal_now = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq_now  = AccountInfoDouble(ACCOUNT_EQUITY);
   double net     = (trades>0.0) ? (grossProfit-grossLoss) : (bal_now - (g_rt_start_bal>0.0 ? g_rt_start_bal : bal_now));
   double pf      = (grossLoss>0.0) ? (grossProfit/grossLoss) : (grossProfit>0.0 ? 10.0 : 0.0);
   double dd_pct  = (g_rt_peak_bal>0.0) ? MathMax(0.0, (g_rt_peak_bal-MathMin(bal_now,eq_now))/g_rt_peak_bal*100.0) : 0.0;

   AgentDNA rec = g_dna;
   rec.generation       = g_current_generation;
   rec.profit_factor    = pf;
   rec.max_drawdown_pct = dd_pct;
   rec.total_trades     = trades;
   rec.net_profit       = net;
   rec.fitness          = CalcFitness(pf, dd_pct, trades, net);

   SaveDNAToMemory(rec);
   g_last_dna_snapshot_bar = g_rt_bar_count;
   Log("Live DNA snapshot reason="+reason+
       " fit="+DoubleToString(rec.fitness,3)+
       " pf="+DoubleToString(pf,2)+
       " net="+DoubleToString(net,2));
}

void ApplyLiveControl()
{
   if(!InpUseLiveControl) return;
   if((TimeCurrent()-g_last_control_check) < InpLiveControlEverySeconds) return;
   g_last_control_check = TimeCurrent();

   LiveControl c;
   if(!ReadLiveControl(c)) return;

   if(InpLiveControlMaxAgeSeconds>0 && c.epoch>0 && MathAbs((long)TimeLocal()-c.epoch)>InpLiveControlMaxAgeSeconds)
      return;
   if(c.confidence < 50)
      return;

   int oldGap = g_dna.ExtraTightGapPoints;
   double oldTP = g_dna.BasketTakeProfitMoney;
   double oldSL = g_dna.BasketStopLossMoney;
   double oldSecureStart = g_secure_profit_start;
   double oldSecureLock = g_secure_profit_lock;
   double oldLotF = g_state.lot_factor;
   double oldGridF = g_state.grid_factor;

   int gapStep = MathMax(1, InpLiveControlGapStepPoints);
   double moneyStep = MathMax(0.01, InpLiveControlMoneyStep);
   double factorStep = MathMax(0.01, InpLiveControlFactorStep);

   if(c.gap > 0)
      g_dna.ExtraTightGapPoints = StepIntToward(g_dna.ExtraTightGapPoints, c.gap, gapStep, 50, 1000);
   if(c.modify_step > 0)
      g_dna.ModifyStepPoints = StepIntToward(g_dna.ModifyStepPoints, c.modify_step, 1, 1, 5);
   if(c.tp > 0.0)
      g_dna.BasketTakeProfitMoney = StepDoubleToward(g_dna.BasketTakeProfitMoney, c.tp, moneyStep, 0.5, 20.0);
   if(c.sl > 0.0)
      g_dna.BasketStopLossMoney = StepDoubleToward(g_dna.BasketStopLossMoney, c.sl, moneyStep, 1.0, 50.0);

   if(g_dna.BasketStopLossMoney <= g_dna.BasketTakeProfitMoney)
      g_dna.BasketStopLossMoney = ClampD(g_dna.BasketTakeProfitMoney + 0.50, 1.0, 50.0);

   if(c.lock_start > 0.0)
      g_dna.BasketLockStartMoney = StepDoubleToward(g_dna.BasketLockStartMoney, c.lock_start, moneyStep, 0.5, 20.0);
   if(c.lock_giveback > 0.0)
      g_dna.BasketLockGiveBackMoney = StepDoubleToward(g_dna.BasketLockGiveBackMoney, c.lock_giveback, moneyStep, 0.1, 10.0);
   if(c.secure_start > 0.0)
      g_secure_profit_start = StepDoubleToward(g_secure_profit_start, c.secure_start, moneyStep, 0.10, 5.0);
   if(c.secure_lock > 0.0)
      g_secure_profit_lock = StepDoubleToward(g_secure_profit_lock, c.secure_lock, moneyStep, 0.10, 5.0);
   if(c.lot_factor > 0.0)
      g_state.lot_factor = StepDoubleToward(g_state.lot_factor, c.lot_factor, factorStep, g_dna.MinLotFactor, 1.0);
   if(c.grid_factor > 0.0)
      g_state.grid_factor = StepDoubleToward(g_state.grid_factor, c.grid_factor, factorStep, 1.0, g_dna.MaxGridFactor);

   bool changed = (oldGap != g_dna.ExtraTightGapPoints) ||
                  (MathAbs(oldTP-g_dna.BasketTakeProfitMoney)>0.0001) ||
                  (MathAbs(oldSL-g_dna.BasketStopLossMoney)>0.0001) ||
                  (MathAbs(oldSecureStart-g_secure_profit_start)>0.0001) ||
                  (MathAbs(oldSecureLock-g_secure_profit_lock)>0.0001) ||
                  (MathAbs(oldLotF-g_state.lot_factor)>0.0001) ||
                  (MathAbs(oldGridF-g_state.grid_factor)>0.0001);

   if(changed)
   {
      g_last_control_epoch = c.epoch;
      Log("Live control "+c.action+
          " conf="+IntegerToString(c.confidence)+
          " gap="+IntegerToString(g_dna.ExtraTightGapPoints)+
          " tp="+DoubleToString(g_dna.BasketTakeProfitMoney,2)+
          " sl="+DoubleToString(g_dna.BasketStopLossMoney,2)+
          " secure="+DoubleToString(g_secure_profit_start,2)+"/"+DoubleToString(g_secure_profit_lock,2)+
          " lotF="+DoubleToString(g_state.lot_factor,2)+
          " gridF="+DoubleToString(g_state.grid_factor,2));
      SaveLiveDNASnapshot("control", false);
   }
}

void CancelOrders(int typeFilter=-1)
{
   if(!TradeActionAllowed("cancel_orders")) return;
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
      RememberTradeResult(InpDryRunPrintOnly || trade.ResultRetcode() == TRADE_RETCODE_DONE, "delete_order");
   }
}

void DeleteDuplicateOrdersKeepLatest(ENUM_ORDER_TYPE type)
{
   if(!InpDeleteDuplicates) return;
   if(!TradeActionAllowed("delete_duplicates")) return;
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
      RememberTradeResult(InpDryRunPrintOnly || trade.ResultRetcode() == TRADE_RETCODE_DONE, "delete_duplicate");
   }
}

bool ModifyPositionSLToPair(ulong positionTicket, double pairPrice, ENUM_POSITION_TYPE posType=POSITION_TYPE_BUY)
{
   if(!InpPairPositionSLWithPending) return true;
   if(!PositionSelectByTicket(positionTicket)) return false;
   string sym=g_profile.symbol; double pt=PointOf(sym);
   double curSL=PositionGetDouble(POSITION_SL), curTP=PositionGetDouble(POSITION_TP);
   datetime openTime=(datetime)PositionGetInteger(POSITION_TIME);
   if(InpMinHoldSeconds>0 && (TimeCurrent()-openTime)<InpMinHoldSeconds) return true;
   if(InpOneWayTrailOnly && curSL>0)
   {
      if(posType==POSITION_TYPE_BUY && pairPrice<=curSL) return true;
      if(posType==POSITION_TYPE_SELL && pairPrice>=curSL) return true;
   }
   int step=MathMax(MathMax(1,g_dna.ModifyStepPoints), InpPairModifyMinStepPoints);
   if(curSL>0&&MathAbs(curSL-pairPrice)<step*pt) return true;
   if(!TradeActionAllowed("modify_pair_sl")) return false;
   trade.SetExpertMagicNumber(g_profile.magic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   if(InpDryRunPrintOnly){ Log("DRY modify SL to pair="+DoubleToString(pairPrice,DigitsOf(sym))); return true; }
   bool ok=trade.PositionModify(positionTicket,pairPrice,curTP);
   RememberTradeResult(ok, "modify_pair_sl");
   if(!ok) Log("SL modify failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

bool ApplySecureProfitSLToTicket(ulong positionTicket)
{
   if(!InpUseSecureProfitSL) return true;
   if(!PositionSelectByTicket(positionTicket)) return false;

   string sym=g_profile.symbol;
   double pt=PointOf(sym);
   if(pt<=0.0) return true;

   ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double profit=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
   if(profit<g_secure_profit_start)
      return true;

   double volume=PositionGetDouble(POSITION_VOLUME);
   double openPrice=PositionGetDouble(POSITION_PRICE_OPEN);
   double curSL=PositionGetDouble(POSITION_SL);
   double curTP=PositionGetDouble(POSITION_TP);
   double lockMoney=MathMin(g_secure_profit_lock, profit);
   double distance=0.0;

   if(!MoneyToPriceDistance(sym, volume, lockMoney, distance))
      return true;

   int minStop=BrokerMinimumStopPoints(sym);
   double targetSL=0.0;

   if(type==POSITION_TYPE_BUY)
   {
      targetSL=NormalizePrice(sym, openPrice+distance);
      double maxValidSL=NormalizePrice(sym, BidOf(sym)-minStop*pt);
      if(targetSL>maxValidSL)
         targetSL=maxValidSL;
      targetSL=NormalizePrice(sym, targetSL);

      if(targetSL<=openPrice)
         return true;
      if(curSL>0.0 && targetSL<=curSL)
         return true;
   }
   else if(type==POSITION_TYPE_SELL)
   {
      targetSL=NormalizePrice(sym, openPrice-distance);
      double minValidSL=NormalizePrice(sym, AskOf(sym)+minStop*pt);
      if(targetSL<minValidSL)
         targetSL=minValidSL;
      targetSL=NormalizePrice(sym, targetSL);

      if(targetSL>=openPrice)
         return true;
      if(curSL>0.0 && targetSL>=curSL)
         return true;
   }
   else
      return true;

   int step=MathMax(MathMax(1,g_dna.ModifyStepPoints), InpPairModifyMinStepPoints);
   if(curSL>0.0 && MathAbs(curSL-targetSL)<step*pt)
      return true;

   double lockedProfit=EstimateProfitAtPrice(sym, type, openPrice, targetSL, volume);
   if(lockedProfit<=0.0)
      return true;

   trade.SetExpertMagicNumber(g_profile.magic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   if(InpDryRunPrintOnly)
   {
      Log("DRY secure profit SL ticket="+IntegerToString((int)positionTicket)+
          " sl="+DoubleToString(targetSL,DigitsOf(sym))+
          " lock_est=$"+DoubleToString(lockedProfit,2));
      return true;
   }

   bool ok=trade.PositionModify(positionTicket,targetSL,curTP);
   RememberTradeResult(ok, "secure_profit_sl");
   if(ok)
      Log("Secure profit SL ticket="+IntegerToString((int)positionTicket)+
          " sl="+DoubleToString(targetSL,DigitsOf(sym))+
          " lock_est=$"+DoubleToString(lockedProfit,2));
   else
      Log("Secure profit SL failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

void SecureProfitSL()
{
   if(!InpUseSecureProfitSL) return;
   if(InpPairModifyEverySeconds > 0 && (TimeCurrent() - g_state.last_secure_sl_time) < InpPairModifyEverySeconds)
      return;
   if(!TradeActionAllowed("secure_profit_sl")) return;
   g_state.last_secure_sl_time = TimeCurrent();

   string sym=g_profile.symbol; ulong mag=g_profile.magic;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      ApplySecureProfitSLToTicket(tk);
   }
}

bool ModifyPendingToPair(ENUM_ORDER_TYPE type, double targetPrice)
{
   ulong tk=LatestOrderTicket(type); if(!tk) return false;
   if(!OrderSelect(tk)) return false;
   string sym=g_profile.symbol; double pt=PointOf(sym);
   double oldPrice=OrderGetDouble(ORDER_PRICE_OPEN);
   int step=MathMax(MathMax(1,g_dna.ModifyStepPoints), InpPairModifyMinStepPoints);
   if(MathAbs(oldPrice-targetPrice)<step*pt) return true;
   if(!TradeActionAllowed("modify_pending_pair")) return false;
   double sl=OrderGetDouble(ORDER_SL), tp=OrderGetDouble(ORDER_TP);
   trade.SetExpertMagicNumber(g_profile.magic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   if(InpDryRunPrintOnly){ Log("DRY modify pending "+EnumToString(type)+" → "+DoubleToString(targetPrice,DigitsOf(sym))); return true; }
   bool ok=trade.OrderModify(tk,targetPrice,sl,tp,ORDER_TIME_GTC,0,0.0);
   RememberTradeResult(ok, "modify_pending_pair");
   if(!ok) Log("Pending modify failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

void CloseAllPositions(string reason)
{
   if(!TradeActionAllowed("close_all")) return;
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
      RememberTradeResult(InpDryRunPrintOnly || trade.ResultRetcode() == TRADE_RETCODE_DONE, "close_position");
   }
   g_state.basket_peak_profit=0; Log("CloseAll reason="+reason);
}

void ApplyCooldown(int minutes,string reason,bool reduceLot,bool widenGrid)
{
   if(!InpUseCooldown)
   {
      g_state.cooldown_until = 0;
      minutes = 0;
   }
   else if(minutes>0)
      g_state.cooldown_until = TimeCurrent() + (datetime)(minutes * 60);

   if(reduceLot) g_state.lot_factor=MathMax(g_dna.MinLotFactor, g_state.lot_factor*g_dna.LotReductionFactor);
   if(widenGrid) g_state.grid_factor=MathMin(g_dna.MaxGridFactor, g_state.grid_factor*g_dna.GridWidenFactor);
   CancelOrders();
   if(InpUseCooldown)
      Log("Cooldown "+reason+" "+IntegerToString(minutes)+"min until="+TimeToString(g_state.cooldown_until)+" lotF="+DoubleToString(g_state.lot_factor,2)+" gridF="+DoubleToString(g_state.grid_factor,2));
   else
      Log("Cooldown skipped "+reason+" lotF="+DoubleToString(g_state.lot_factor,2)+" gridF="+DoubleToString(g_state.grid_factor,2));
}

void AdaptiveStopReverseAfterDeal(double profit)
{
   if(!InpUseAdaptiveStopReverse) return;

   if(profit < 0.0)
   {
      g_state.adaptive_loss_streak++;
      g_state.adaptive_win_streak = 0;

      int oldGap = g_dna.ExtraTightGapPoints;
      double oldGrid = g_state.grid_factor;
      int step = InpAdaptiveGapStepPoints * MathMin(3, MathMax(1, g_state.adaptive_loss_streak));
      g_dna.ExtraTightGapPoints = ClampI(g_dna.ExtraTightGapPoints + step, InpAdaptiveMinGapPoints, InpAdaptiveMaxGapPoints);
      g_state.grid_factor = MathMin(g_dna.MaxGridFactor, g_state.grid_factor + InpAdaptiveGridFactorStep);

      if(InpAdaptiveNoReverseMinutes > 0)
         g_state.adaptive_no_reverse_until = TimeCurrent() + InpAdaptiveNoReverseMinutes * 60;

      Log("AdaptiveStopReverse LOSS profit="+DoubleToString(profit,2)+
          " gap "+IntegerToString(oldGap)+"->"+IntegerToString(g_dna.ExtraTightGapPoints)+
          " grid "+DoubleToString(oldGrid,2)+"->"+DoubleToString(g_state.grid_factor,2)+
          " no_reverse_sec="+IntegerToString((int)MathMax(0,g_state.adaptive_no_reverse_until-TimeCurrent())));
      SaveLiveDNASnapshot("adaptive_loss", false);
      return;
   }

   if(profit > 0.0)
   {
      g_state.adaptive_win_streak++;
      g_state.adaptive_loss_streak = 0;

      if(g_state.adaptive_win_streak >= InpAdaptiveWinsToTighten)
      {
         int oldGap = g_dna.ExtraTightGapPoints;
         double oldGrid = g_state.grid_factor;
         g_dna.ExtraTightGapPoints = ClampI(g_dna.ExtraTightGapPoints - InpAdaptiveGapStepPoints, InpAdaptiveMinGapPoints, InpAdaptiveMaxGapPoints);
         g_state.grid_factor = MathMax(1.0, g_state.grid_factor - InpAdaptiveGridFactorStep);
         g_state.adaptive_win_streak = 0;
         Log("AdaptiveStopReverse WIN gap "+IntegerToString(oldGap)+"->"+IntegerToString(g_dna.ExtraTightGapPoints)+
             " grid "+DoubleToString(oldGrid,2)+"->"+DoubleToString(g_state.grid_factor,2));
         SaveLiveDNASnapshot("adaptive_win", false);
      }
   }
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
      AdaptiveStopReverseAfterDeal(profit);
      g_state.last_processed_deal=deal;
   }
}

void BasketGuard()
{
   double pnl=BasketProfit(); int allPos=CountAllPositions();
   if(allPos<=0){ g_state.basket_peak_profit=0; return; }
   if(pnl>g_state.basket_peak_profit) g_state.basket_peak_profit=pnl;
   if(InpUseBasketTakeProfit&&pnl>=g_dna.BasketTakeProfitMoney)
      { CloseAllPositions("basket_tp"); ApplyCooldown(g_dna.CooldownAfterTPMinutes,"after_tp",false,false); return; }
   if(InpUseBasketEquityLock&&g_state.basket_peak_profit>=g_dna.BasketLockStartMoney)
   {
      if((g_state.basket_peak_profit-pnl)>=g_dna.BasketLockGiveBackMoney)
         { CloseAllPositions("equity_lock"); ApplyCooldown(g_dna.CooldownAfterTPMinutes,"after_lock",false,false); return; }
   }
   if(InpUseBasketStopLoss&&pnl<=-MathAbs(g_dna.BasketStopLossMoney))
      { CloseAllPositions("basket_sl"); ApplyCooldown(g_dna.CooldownAfterSLMinutes,"after_sl",true,true); return; }
}

bool OpenMarket(string side)
{
   if(!CanSend()) return false;
   string sym=g_profile.symbol;
   string blockReason="";
   if(!TradingAllowedNow(sym, blockReason))
   {
      g_trade_allowed = false;
      g_trade_block_reason = blockReason;
      Log("Trade blocked: "+blockReason);
      return false;
   }

   g_trade_allowed = true;
   g_trade_block_reason = "ok";
   double pt=PointOf(sym),ask=AskOf(sym),bid=BidOf(sym);
   if(ask<=0||bid<=0||pt<=0) return false;
   double lot=NormalizeVolume(sym,g_profile.base_lot*g_state.lot_factor);
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
      if(InpDryRunPrintOnly){ Log("DRY BUY lot="+DoubleToString(lot,2)); ok=true; }
      else ok=trade.Buy(lot,sym,0,sl,tp,"LIVE_BUY");
   }
   else
   {
      if(InpDryRunPrintOnly){ Log("DRY SELL lot="+DoubleToString(lot,2)); ok=true; }
      else ok=trade.Sell(lot,sym,0,sl,tp,"LIVE_SELL");
   }
   RememberTradeResult(ok, "open_market");
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
   string blockReason="";
   if(!TradingAllowedNow(sym, blockReason))
   {
      g_trade_allowed = false;
      g_trade_block_reason = blockReason;
      Log("Pending blocked: "+blockReason);
      return false;
   }

   g_trade_allowed = true;
   g_trade_block_reason = "ok";
   double pt=PointOf(sym),ask=AskOf(sym),bid=BidOf(sym);
   if(ask<=0||bid<=0||pt<=0) return false;
   int minStop=BrokerMinimumStopPoints(sym);
   double lot=NormalizeVolume(sym,g_profile.base_lot*g_state.lot_factor);
   double sl=0,tp=0;
   trade.SetExpertMagicNumber(g_profile.magic); trade.SetDeviationInPoints(InpDeviationPoints);
   bool ok=false;
   if(type==ORDER_TYPE_SELL_STOP)
   {
      price=NormalizePrice(sym,MathMin(price,bid-minStop*pt));
      if(!InpPendingHasNoOwnSLTP) sl=NormalizePrice(sym,price+ExactGapPoints(sym)*2*pt);
      if(InpDryRunPrintOnly){ Log("DRY SELL_STOP price="+DoubleToString(price,DigitsOf(sym))); ok=true; }
      else ok=trade.SellStop(lot,price,sym,sl,tp,ORDER_TIME_GTC,0,"LIVE_SELL_STOP");
   }
   else
   {
      price=NormalizePrice(sym,MathMax(price,ask+minStop*pt));
      if(!InpPendingHasNoOwnSLTP) sl=NormalizePrice(sym,price-ExactGapPoints(sym)*2*pt);
      if(InpDryRunPrintOnly){ Log("DRY BUY_STOP price="+DoubleToString(price,DigitsOf(sym))); ok=true; }
      else ok=trade.BuyStop(lot,price,sym,sl,tp,ORDER_TIME_GTC,0,"LIVE_BUY_STOP");
   }
   RememberTradeResult(ok, "place_reverse_pending");
   if(ok) MarkSent();
   else Log("PlacePending failed ret="+IntegerToString((int)trade.ResultRetcode()));
   return ok;
}

void ResolveHedgeIfNeeded()
{
   if(!InpResolveHedgeImmediately) return;
   if(CountPositions(POSITION_TYPE_BUY)<=0||CountPositions(POSITION_TYPE_SELL)<=0) return;
   if(!CanSend()) return;   // ✅ Rate-limit hedge resolution — prevents tick loop
   if(!TradeActionAllowed("resolve_hedge")) return;
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
      if(closeIt)
      {
         if(InpDryRunPrintOnly) Log("DRY resolve hedge close="+IntegerToString((int)tk));
         else trade.PositionClose(tk);
         RememberTradeResult(InpDryRunPrintOnly || trade.ResultRetcode() == TRADE_RETCODE_DONE, "resolve_hedge_close");
         MarkSent();   // ✅ Moved inside closeIt block — only resets timer when we actually tried
         break;        // ✅ Close one at a time, then wait for next CanSend() window
      }
   }
}

void ManageStopReversePair()
{
   if(!InpUseStopReversePair) return;
   string sym=g_profile.symbol;
   if(!IsFreshTick(sym)||!SpreadAllowed()) return;
   int buyPos=CountPositions(POSITION_TYPE_BUY), sellPos=CountPositions(POSITION_TYPE_SELL), allPos=buyPos+sellPos;
   if(allPos<=0){ CancelOrders(); return; }
   if((buyPos>0&&sellPos>0)||allPos>InpMaxOpenPositionsPerSymbol){ ResolveHedgeIfNeeded(); return; }

   int sellStopOrders = CountOrders(ORDER_TYPE_SELL_STOP);
   int buyStopOrders  = CountOrders(ORDER_TYPE_BUY_STOP);
   if(InpUseAdaptiveStopReverse && TimeCurrent() < g_state.adaptive_no_reverse_until)
   {
      if(sellStopOrders > 0 || buyStopOrders > 0)
         CancelOrders();
      return;
   }

   bool missingReverse = (buyPos>0 && sellStopOrders<=0) || (sellPos>0 && buyStopOrders<=0);
   if(!missingReverse && InpPairModifyEverySeconds > 0 && (TimeCurrent() - g_state.last_pair_manage_time) < InpPairModifyEverySeconds)
      return;
   g_state.last_pair_manage_time = TimeCurrent();

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
      if(sellStopOrders<=0)
      {
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
      if(buyStopOrders<=0) PlaceReversePending(ORDER_TYPE_BUY_STOP,pairPrice);
      else ModifyPendingToPair(ORDER_TYPE_BUY_STOP,pairPrice);
      return;
   }
}

//+------------------------------------------------------------------+
//| FetchExternalSignal — reads confluence_signal.json every 3s      |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Agent Pending Orders — parse, place, cancel                      |
//+------------------------------------------------------------------+

// Parse pending_N_* flat fields from confluence JSON raw string
void ParseAgentPendingOrders(const string &raw)
{
   g_agent_pending_count = 0;
   int pc = StringFind(raw, "\"pending_count\":");
   if(pc < 0) return;
   int count = (int)StringToInteger(StringSubstr(raw, pc + 16, 2));
   count = MathMin(count, MAX_AGENT_PENDING);
   for(int i = 0; i < count; i++)
   {
      string ptype = "\"pending_" + IntegerToString(i) + "_type\":";
      string pprice= "\"pending_" + IntegerToString(i) + "_price\":";
      string pconf = "\"pending_" + IntegerToString(i) + "_conf\":";
      string pexp  = "\"pending_" + IntegerToString(i) + "_expiry\":";
      // -- type --
      int pt = StringFind(raw, ptype);
      string otype = "";
      if(pt >= 0)
      {
         string scope = StringSubstr(raw, pt + StringLen(ptype), 16);
         int qs = StringFind(scope, "\"");
         if(qs >= 0) {
            string inner = StringSubstr(scope, qs+1, 12);
            int end2 = StringFind(inner, "\"");
            otype = (end2 > 0) ? StringSubstr(inner, 0, end2) : inner;
         }
      }
      if(otype != "BUY_LIMIT" && otype != "SELL_LIMIT") continue;
      // -- price --
      int pp2 = StringFind(raw, pprice);
      double tprice = 0;
      if(pp2 >= 0) tprice = StringToDouble(StringSubstr(raw, pp2 + StringLen(pprice), 10));
      if(tprice <= 0) continue;
      // -- confidence --
      int pc2 = StringFind(raw, pconf);
      int conf = 70;
      if(pc2 >= 0) conf = (int)StringToInteger(StringSubstr(raw, pc2 + StringLen(pconf), 3));
      // -- expiry --
      int pe = StringFind(raw, pexp);
      int expiry = 4;
      if(pe >= 0) expiry = (int)StringToInteger(StringSubstr(raw, pe + StringLen(pexp), 2));
      g_agent_pending[g_agent_pending_count].order_type   = otype;
      g_agent_pending[g_agent_pending_count].price        = tprice;
      g_agent_pending[g_agent_pending_count].reason       = "AGENT_P";
      g_agent_pending[g_agent_pending_count].confidence   = conf;
      g_agent_pending[g_agent_pending_count].expiry_hours = expiry;
      g_agent_pending_count++;
   }
   if(g_agent_pending_count > 0)
      Log("AGENT_PENDING: Parsed "+IntegerToString(g_agent_pending_count)+" levels");
}

// Cancel all agent-placed pending orders for this symbol
void CancelAgentPendingOrders()
{
   string sym = g_profile.symbol;
   int cancelled = 0;
   for(int j = OrdersTotal()-1; j >= 0; j--)
   {
      ulong ticket = OrderGetTicket(j);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != sym) continue;
      if(StringFind(OrderGetString(ORDER_COMMENT), "AGENT_P") >= 0)
      {
         if(trade.OrderDelete(ticket)) cancelled++;
      }
   }
   if(cancelled > 0)
      Log("AGENT_PENDING: Cancelled "+IntegerToString(cancelled)+" pending orders");
}

// Place agent pending orders at key S/R levels (only when no open position)
void ManageAgentPendingOrders()
{
   if(!InpAutoTrade || InpDryRunPrintOnly) return;
   if(g_agent_pending_count == 0)  return;
   // Only place when no position is open — avoid grid-reverse trap
   if(CountAllPositions() > 0)     return;
   // Throttle: once per 30 seconds
   if(TimeCurrent() - g_agent_pending_placed < 30) return;
   g_agent_pending_placed = TimeCurrent();

   string sym   = g_profile.symbol;
   double bid   = BidOf(sym);
   double ask   = AskOf(sym);
   int    stops = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   double min_dist = MathMax(stops + 10, 30) * point; // at least 30 points distance

   double atr = CalcATRPoints(sym, 14) * point;
   if(atr < 0.50) atr = 2.0; // fallback: 2$ minimum ATR

   for(int i = 0; i < g_agent_pending_count; i++)
   {
      AgentPendingLevel lvl = g_agent_pending[i];
      // Validate direction vs price
      double ref = (lvl.order_type == "BUY_LIMIT") ? bid : ask;
      if(MathAbs(lvl.price - ref) < min_dist)
      {
         Log("AGENT_PENDING: Skip "+lvl.order_type+" @ "+DoubleToString(lvl.price,2)+" (too close, dist="+DoubleToString(MathAbs(lvl.price-ref),1)+")");
         continue;
      }
      if(lvl.order_type == "BUY_LIMIT"  && lvl.price >= bid) continue;
      if(lvl.order_type == "SELL_LIMIT" && lvl.price <= ask) continue;
      // Check if already placed near this level
      bool exists = false;
      for(int j = OrdersTotal()-1; j >= 0; j--)
      {
         ulong tk = OrderGetTicket(j);
         if(tk == 0) continue;
         if(OrderGetString(ORDER_SYMBOL) != sym) continue;
         if(StringFind(OrderGetString(ORDER_COMMENT), "AGENT_P") < 0) continue;
         if(MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - lvl.price) < min_dist * 3) { exists = true; break; }
      }
      if(exists) continue;
      // Lot size: base lot only (no multiplier on pending — safety)
      double lot = g_profile.base_lot * MathMax(0.25, g_state.lot_factor);
      double lstep = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      double lmin  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double lmax  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
      if(lstep > 0) lot = MathFloor(lot / lstep) * lstep;
      lot = MathMax(lmin, MathMin(lmax, lot));
      // TP/SL: 1.5x ATR target, 1.0x ATR stop
      ENUM_ORDER_TYPE otype = (lvl.order_type == "BUY_LIMIT") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
      double tp, sl;
      if(otype == ORDER_TYPE_BUY_LIMIT)
      {
         tp = NormalizeDouble(lvl.price + atr * 1.5, DigitsOf(sym));
         sl = NormalizeDouble(lvl.price - atr * 1.0, DigitsOf(sym));
      }
      else
      {
         tp = NormalizeDouble(lvl.price - atr * 1.5, DigitsOf(sym));
         sl = NormalizeDouble(lvl.price + atr * 1.0, DigitsOf(sym));
      }
      datetime expiry = TimeCurrent() + lvl.expiry_hours * 3600;
      string comment  = "AGENT_P_" + IntegerToString(lvl.confidence) + "_" + IntegerToString(i);
      MqlTradeRequest req = {};
      MqlTradeResult  res = {};
      req.action     = TRADE_ACTION_PENDING;
      req.symbol     = sym;
      req.type       = otype;
      req.volume     = lot;
      req.price      = NormalizeDouble(lvl.price, DigitsOf(sym));
      req.sl         = sl;
      req.tp         = tp;
      req.expiration = expiry;
      req.type_time  = ORDER_TIME_SPECIFIED;
      req.comment    = comment;
      req.magic      = g_profile.magic;
      req.deviation  = 5;
      bool ok = OrderSend(req, res);
      Log("AGENT_PENDING: " + (ok ? "PLACED" : "FAILED") +
          " " + lvl.order_type + " @ " + DoubleToString(lvl.price, 2) +
          " lot=" + DoubleToString(lot, 2) +
          " tp=" + DoubleToString(tp, 2) + " sl=" + DoubleToString(sl, 2) +
          " conf=" + IntegerToString(lvl.confidence) +
          " err=" + (ok ? "0" : IntegerToString(GetLastError())));
   }
}

void FetchExternalSignal()
{
   static datetime s_last_fetch = 0;
   if(TimeCurrent() - s_last_fetch < 3) return;
   s_last_fetch = TimeCurrent();

   int h = FileOpen("confluence_signal.json",
                    FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      // Try local agents folder next to terminal
      h = FileOpen("confluence_signal.json", FILE_READ|FILE_TXT|FILE_ANSI);
      if(h == INVALID_HANDLE) { g_ext_signal_approved=false; g_ext_swing_approved=false; return; }
   }
   string raw = "";
   while(!FileIsEnding(h)) raw += FileReadString(h);
   FileClose(h);

   // Parse approved
   int pa = StringFind(raw,"\"approved\":");
   if(pa>=0) g_ext_signal_approved = (StringFind(StringSubstr(raw,pa,20),"true")>=0);

   // Parse swing_approved
   int ps = StringFind(raw,"\"swing_approved\":");
   if(ps>=0) g_ext_swing_approved = (StringFind(StringSubstr(raw,ps,25),"true")>=0);

   // Parse direction (handles both "direction":"SELL" and "direction": "SELL")
   int pd = StringFind(raw,"\"direction\":");
   if(pd>=0)
   {
      string scope = StringSubstr(raw,pd+12,12);
      int qs = StringFind(scope,"\"");          // find opening quote
      if(qs>=0)
      {
         string inner = StringSubstr(scope,qs+1,8);
         int end = StringFind(inner,"\"");
         g_ext_signal_dir = (end>0) ? StringSubstr(inner,0,end) : inner;
      }
   }

   // Parse mode (handles both "mode":"SCALP" and "mode": "SCALP")
   int pm = StringFind(raw,"\"mode\":");
   if(pm>=0)
   {
      string scope = StringSubstr(raw,pm+7,14);
      int qs = StringFind(scope,"\"");
      if(qs>=0)
      {
         string inner = StringSubstr(scope,qs+1,10);
         int end = StringFind(inner,"\"");
         g_ext_signal_mode = (end>0) ? StringSubstr(inner,0,end) : inner;
      }
   }

   // Parse dir_agreement
   int pda = StringFind(raw,"\"dir_agreement\":");
   if(pda>=0) g_ext_dir_agreement = (int)StringToInteger(StringSubstr(raw,pda+16,3));

   // Parse time (detect stale signal > 5 min)
   int pt = StringFind(raw,"\"time\":\"");
   if(pt>=0)
   {
      string ts = StringSubstr(raw,pt+8,19);
      g_ext_signal_time = StringToTime(ts);
   }

   // Invalidate if signal is stale (> 300 seconds)
   if(g_ext_signal_time > 0 && TimeCurrent() - g_ext_signal_time > 300)
   {
      g_ext_signal_approved = false;
      g_ext_swing_approved  = false;
      g_ext_signal_dir      = "NONE";
      g_ext_signal_mode     = "STALE";
   }

   // Parse pending order levels from JSON
   ParseAgentPendingOrders(raw);
   Log("AGENT_SIGNAL: "+g_ext_signal_mode+" dir="+g_ext_signal_dir
       +" scalp="+(g_ext_signal_approved?"✓":"✗")
       +" swing="+(g_ext_swing_approved?"✓":"✗")
       +" agree="+IntegerToString(g_ext_dir_agreement)
       +" pending="+IntegerToString(g_agent_pending_count));
}

void ManageInitialEntryOnNewBar()
{
   string sym=g_profile.symbol;
   datetime bt=iTime(sym,(ENUM_TIMEFRAMES)InpTimeframe,0);
   if(bt<=0||bt==g_state.last_bar_time) return;
   g_state.last_bar_time=bt;

   // ✅ SMC — مسح كامل عند كل شمعة جديدة
   UpdateSMC(sym);

   WriteRealtimeBar();
   DrawChartInfo();
   if(!IsFreshTick(sym)||!SpreadAllowed()||!EntryTimeAllowed()) return;
   if(CountAllPositions()>0) return;

   if(!InpUseCooldown)
      g_state.cooldown_until = 0;

   if(InpUseCooldown && TimeCurrent() < g_state.cooldown_until)
   {
      int secs_left = (int)(g_state.cooldown_until - TimeCurrent());
      if(secs_left % 60 == 0)
         Log("Cooldown: "+IntegerToString(secs_left/60)+"min remaining");
      return;
   }

   // ── AGENT GATE: تحقق من موافقة الوكلاء قبل أي فلتر آخر ─────────────────
   FetchExternalSignal();
   bool agentOK  = g_ext_signal_approved || g_ext_swing_approved;
   bool isSwing  = g_ext_swing_approved && (g_ext_signal_mode == "SWING");
   if(!agentOK)
   {
      Log("AGENT_GATE: BLOCKED — mode="+g_ext_signal_mode+" dir="+g_ext_signal_dir);
      LogSMCDecision(sym,"NONE",false,false,false,50,"BLOCKED","agent_gate");
      return;
   }
   if(g_ext_signal_dir != "BUY" && g_ext_signal_dir != "SELL")
   {
      Log("AGENT_GATE: BLOCKED — no clear direction ("+g_ext_signal_dir+")");
      LogSMCDecision(sym,"NONE",false,false,false,50,"BLOCKED","agent_no_dir");
      return;
   }
   // Swing mode: boost lot multiplier
   if(isSwing)
      g_state.lot_factor = MathMin(g_state.lot_factor * g_swing_lot_mult, 3.0);
   // Force direction from agents
   string agentDir = g_ext_signal_dir; // "BUY" or "SELL"
   // ─────────────────────────────────────────────────────────────────────────

   // ✅ REGIME FILTER — لا تدخل في سوق متذبذب (يتجاوز في وضع Swing أو Scalp مع موافقة الوكلاء)
   if(IsRangingMarket(sym) && !agentOK)
   {
      Log("BLOCKED: Ranging market — skip (no agent approval)");
      LogSMCDecision(sym,"NONE",false,false,false,50,"BLOCKED","ranging");
      return;
   }
   if(IsRangingMarket(sym) && agentOK)
      Log("AGENT_GATE: ranging market bypassed by agent approval");

   // ✅ SMART DIRECTION — agents override EMA+RSI when approved
   string dir = SmartDirectionOf(sym);
   // If agents approved a direction and EMA says NONE/opposite, trust the agents
   if(agentOK && (agentDir == "BUY" || agentDir == "SELL"))
   {
      if(dir == "NONE")
      {
         Log("AGENT_GATE: EMA=NONE but agents say "+agentDir+" — using agent direction");
         dir = agentDir;
      }
      else if(dir != agentDir && isSwing)
      {
         // Swing mode forces direction even against EMA
         Log("AGENT_GATE: SWING override EMA="+dir+" → "+agentDir);
         dir = agentDir;
      }
      // Scalp: if EMA disagrees, block (safety)
      else if(dir != agentDir && !isSwing)
      {
         Log("AGENT_GATE: SCALP dir conflict EMA="+dir+" agents="+agentDir+" — BLOCKED");
         LogSMCDecision(sym,"NONE",false,false,false,CalcRSI(sym,InpRSIPeriod),"BLOCKED","dir_conflict");
         if(isSwing) g_state.lot_factor = 1.0;
         return;
      }
   }
   else if(dir == "NONE")
   {
      Log("BLOCKED: SmartEntry — EMAs mixed / RSI extreme");
      LogSMCDecision(sym,"NONE",false,false,false,CalcRSI(sym,InpRSIPeriod),"BLOCKED","ema_mixed");
      return;
   }
   bool is_buy = (dir == "BUY");

   // ✅ SMC ZONE FILTER — Order Block أو FVG مطلوب (يتجاوز عند موافقة الوكلاء)
   string smc_hit = "";
   if(InpUseSMCFilter && InpSMCRequireOBorFVG && !agentOK)
   {
      if(!IsAtSMCZone(sym, is_buy, smc_hit))
      {
         Log("BLOCKED: SMC — "+smc_hit+" | "+g_smc_status);
         LogSMCDecision(sym, dir, false, false, g_smc_has_bos,
                        CalcRSI(sym,InpRSIPeriod), "BLOCKED", "smc_"+smc_hit);
         return;
      }
   }
   if(agentOK && !IsAtSMCZone(sym, is_buy, smc_hit))
      Log("AGENT_GATE: SMC zone bypassed (agentOK) — smc="+smc_hit);

   // ✅ CANDLE CONFIRMATION — كاندل قوية تؤكد الاتجاه (يتجاوز في وضع Swing)
   if(!HasConfirmingCandle(sym, is_buy) && !isSwing)
   {
      Log("BLOCKED: Candle — weak body for "+dir);
      LogSMCDecision(sym, dir, smc_hit=="OB", smc_hit=="FVG", g_smc_has_bos,
                     CalcRSI(sym,InpRSIPeriod), "BLOCKED", "weak_candle");
      return;
   }
   if(isSwing && !HasConfirmingCandle(sym, is_buy))
      Log("AGENT_GATE: Candle confirmation bypassed (SWING mode)");

   // ✅ كل الفلاتر اجتازها — ندخل
   string entry_log = "ENTRY: dir=" + dir +
                      " zone=" + (smc_hit==""?"bypass":smc_hit) +
                      " " + g_smc_status + " ✓";
   Log(entry_log);
   LogSMCDecision(sym, dir, smc_hit=="OB", smc_hit=="FVG", g_smc_has_bos,
                  CalcRSI(sym,InpRSIPeriod), "ENTRY", smc_hit==""?"no_smc":smc_hit);
   CancelOrders();
   CancelAgentPendingOrders(); // cancel pending levels when entering market
   if(OpenMarket(dir))
   {
      // وضع الوكلاء: لا grid reverse — صفقة واحدة نظيفة باتجاه الوكلاء فقط
      if(agentOK)
         Log("AGENT_MODE: StopReversePair disabled — pure agent direction");
      else
         ManageStopReversePair();
   }
}

void Process()
{
   if(!g_loaded) return;
   ApplyLiveControl();
   ProcessClosedDeals(); BasketGuard(); SecureProfitSL(); ResolveHedgeIfNeeded(); BasketGuard();
   // وضع الوكلاء: تعطيل Grid Reverse Pair تماماً — الوكلاء يقررون الاتجاه فقط
   bool agentModeOn = (g_ext_signal_approved || g_ext_swing_approved);
   if(InpManagePairEveryTick && !agentModeOn)
      { ManageStopReversePair(); SecureProfitSL(); }
   BasketGuard(); ManageInitialEntryOnNewBar(); BasketGuard();
   // Agent pending orders: place limit orders at key S/R levels when no position is open
   ManageAgentPendingOrders();
   WriteRealtimeStatusOnly();
}

void WriteRealtimeStatusOnly()
{
   string sym  = g_profile.symbol;
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl  = BasketProfit();
   double bid  = BidOf(sym);
   double ask  = AskOf(sym);
   double spr  = SpreadPoints(sym);
   int    allP = CountAllPositions();
   string blockReason="";
   g_trade_allowed = TradingAllowedNow(sym, blockReason);
   g_trade_block_reason = blockReason;

   if(bal > g_rt_peak_bal) g_rt_peak_bal = bal;

   int h = FileOpen("ea_realtime_status.json",
                    FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;

   MqlRates r[1];
   CopyRates(sym, PERIOD_M1, 0, 1, r);

   string j = "{";
   j += "\"bar\":"          + IntegerToString(g_rt_bar_count)            + ",";
   j += "\"time\":\""       + TimeToString(TimeCurrent())                + "\",";
   j += "\"symbol\":\""     + sym                                        + "\",";
   j += "\"account_login\":"+ IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   j += "\"account_server\":\""+ AccountInfoString(ACCOUNT_SERVER) +"\"" + ",";
   j += "\"account_currency\":\""+ AccountInfoString(ACCOUNT_CURRENCY) +"\"" + ",";
   j += "\"balance\":"      + DoubleToString(bal, 2)                     + ",";
   j += "\"equity\":"       + DoubleToString(eq,  2)                     + ",";
   j += "\"peak_balance\":" + DoubleToString(g_rt_peak_bal, 2)           + ",";
   j += "\"open_pnl\":"     + DoubleToString(pnl, 2)                     + ",";
   j += "\"basket_pnl\":"   + DoubleToString(pnl, 2)                     + ",";
   j += "\"bid\":"          + DoubleToString(bid, DigitsOf(sym))         + ",";
   j += "\"ask\":"          + DoubleToString(ask, DigitsOf(sym))         + ",";
   j += "\"spread_points\":"+ DoubleToString(spr, 1)                     + ",";
   j += "\"trade_allowed\":"+ BoolJson(g_trade_allowed)                  + ",";
   j += "\"trade_block_reason\":\""+ g_trade_block_reason +"\""          + ",";
   j += "\"terminal_trade_allowed\":"+ BoolJson((bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) + ",";
   j += "\"mql_trade_allowed\":"+ BoolJson((bool)MQLInfoInteger(MQL_TRADE_ALLOWED)) + ",";
   j += "\"account_trade_allowed\":"+ BoolJson((bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)) + ",";
   j += "\"account_expert_allowed\":"+ BoolJson((bool)AccountInfoInteger(ACCOUNT_TRADE_EXPERT)) + ",";
   j += "\"symbol_trade_mode\":"+ IntegerToString((int)SymbolInfoInteger(sym,SYMBOL_TRADE_MODE)) + ",";
   j += "\"positions\":"    + IntegerToString(allP)                      + ",";
   j += "\"lot_factor\":"   + DoubleToString(g_state.lot_factor, 4)      + ",";
   j += "\"grid_factor\":"  + DoubleToString(g_state.grid_factor, 4)     + ",";
   j += "\"win_streak\":"   + IntegerToString(g_state.closed_win_streak) + ",";
   j += "\"loss_streak\":"  + IntegerToString(g_state.closed_loss_streak)+ ",";
   j += "\"dna_gap\":"      + IntegerToString(g_dna.ExtraTightGapPoints) + ",";
   j += "\"effective_gap\":"+ IntegerToString(ExactGapPoints(sym))        + ",";
   j += "\"dna_tp\":"       + DoubleToString(g_dna.BasketTakeProfitMoney,2)+",";
   j += "\"dna_sl\":"       + DoubleToString(g_dna.BasketStopLossMoney,2)  +",";
   j += "\"dna_lock_start\":"+ DoubleToString(g_dna.BasketLockStartMoney,2)+",";
   j += "\"dna_lock_giveback\":"+ DoubleToString(g_dna.BasketLockGiveBackMoney,2)+",";
   j += "\"secure_profit_start\":"+ DoubleToString(g_secure_profit_start,2)+",";
   j += "\"secure_profit_lock\":"+ DoubleToString(g_secure_profit_lock,2)+",";
   j += "\"live_control_epoch\":"+ IntegerToString(g_last_control_epoch)+",";
   j += "\"dna_gen\":"      + IntegerToString(g_current_generation)      + ",";
   j += "\"generation\":"   + IntegerToString(g_current_generation)      + ",";
   j += "\"adaptive_loss_streak\":"+ IntegerToString(g_state.adaptive_loss_streak)+ ",";
   j += "\"adaptive_win_streak\":"+ IntegerToString(g_state.adaptive_win_streak)+ ",";
   j += "\"adaptive_no_reverse\":"+ IntegerToString((int)MathMax(0,g_state.adaptive_no_reverse_until-TimeCurrent()))+ ",";
   j += "\"cooldown_enabled\":" + (InpUseCooldown ? "true" : "false") + ",";
   j += "\"cooldown\":"     + IntegerToString(InpUseCooldown ? (int)MathMax(0,g_state.cooldown_until-TimeCurrent()) : 0)+",";
   // ── SMC Data ──
   j += "\"smc_enabled\":"    + (InpUseSMCFilter ? "true" : "false")         + ",";
   j += "\"smc_ob_count\":"   + IntegerToString(g_ob_count)                  + ",";
   j += "\"smc_fvg_count\":"  + IntegerToString(g_fvg_count)                 + ",";
   // ── FVG Fill Levels: nearest bullish FVG below price, nearest bearish FVG above price ──
   {
      double _fvg_bull_hi = 0, _fvg_bull_lo = 0, _fvg_bear_hi = 0, _fvg_bear_lo = 0;
      double _pnow = SymbolInfoDouble(sym, SYMBOL_BID);
      double _nb = 1e10, _nb2 = 1e10;
      for(int _fi = 0; _fi < g_fvg_count; _fi++)
      {
         if(!g_fvg[_fi].valid) continue;
         double _mid = (g_fvg[_fi].top + g_fvg[_fi].bottom) * 0.5;
         if(g_fvg[_fi].bullish && _mid < _pnow)
         {
            double _d = _pnow - _mid;
            if(_d < _nb) { _nb = _d; _fvg_bull_hi = g_fvg[_fi].top; _fvg_bull_lo = g_fvg[_fi].bottom; }
         }
         else if(!g_fvg[_fi].bullish && _mid > _pnow)
         {
            double _d2 = _mid - _pnow;
            if(_d2 < _nb2) { _nb2 = _d2; _fvg_bear_hi = g_fvg[_fi].top; _fvg_bear_lo = g_fvg[_fi].bottom; }
         }
      }
      j += "\"smc_fvg_bull_high\":" + DoubleToString(_fvg_bull_hi, 2) + ",";
      j += "\"smc_fvg_bull_low\":" + DoubleToString(_fvg_bull_lo, 2) + ",";
      j += "\"smc_fvg_bear_high\":" + DoubleToString(_fvg_bear_hi, 2) + ",";
      j += "\"smc_fvg_bear_low\":" + DoubleToString(_fvg_bear_lo, 2) + ",";
   }
   j += "\"smc_has_bos\":"    + (g_smc_has_bos    ? "true" : "false")        + ",";
   j += "\"smc_has_choch\":"  + (g_smc_has_choch  ? "true" : "false")        + ",";
   j += "\"smc_bias\":"       + "\"" + (g_smc_bias_bullish ? "BUY":"SELL")+"\"" + ",";
   j += "\"smc_bos_level\":"  + DoubleToString(g_smc_bos_level, 2)           + ",";
   j += "\"smc_swing_high\":" + DoubleToString(g_smc_swing_high, 2)          + ",";
   j += "\"smc_swing_low\":"  + DoubleToString(g_smc_swing_low == 9999999.0 ? 0 : g_smc_swing_low, 2) + ",";
   j += "\"smc_status\":\""   + g_smc_status + "\""                          + ",";
   // ── S/R Levels: Previous Day High/Low ──────────────────────────────────
   double pdh = iHigh(sym, PERIOD_D1, 1);
   double pdl = iLow (sym, PERIOD_D1, 1);
   double pdc = iClose(sym, PERIOD_D1, 1);
   j += "\"prev_day_high\":"  + DoubleToString(pdh > 0 ? pdh : 0, 2) + ",";
   j += "\"prev_day_low\":"   + DoubleToString(pdl > 0 ? pdl : 0, 2) + ",";
   j += "\"prev_day_close\":" + DoubleToString(pdc > 0 ? pdc : 0, 2) + ",";
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

string RealtimeHistoryEntryJson(const MqlRates &rate, int barNo, double bal, double eq, double pnl, double spr, int allP, string sym)
{
   string entry = "{";
   entry += "\"bar\":"       + IntegerToString(barNo) + ",";
   entry += "\"time\":\""    + TimeToString(rate.time, TIME_DATE|TIME_MINUTES) + "\",";
   entry += "\"b\":"         + DoubleToString(bal, 2) + ",";
   entry += "\"e\":"         + DoubleToString(eq,  2) + ",";
   entry += "\"p\":"         + DoubleToString(pnl, 2) + ",";
   entry += "\"spr\":"       + DoubleToString(spr, 1) + ",";
   entry += "\"pos\":"       + IntegerToString(allP) + ",";
   entry += "\"o\":"         + DoubleToString(rate.open,  DigitsOf(sym)) + ",";
   entry += "\"h\":"         + DoubleToString(rate.high,  DigitsOf(sym)) + ",";
   entry += "\"l\":"         + DoubleToString(rate.low,   DigitsOf(sym)) + ",";
   entry += "\"c\":"         + DoubleToString(rate.close, DigitsOf(sym));
   entry += "}";
   return entry;
}

void WriteRealtimeBar()
{
   string sym  = g_profile.symbol;
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl  = BasketProfit();
   double bid  = BidOf(sym);
   double ask  = AskOf(sym);
   double spr  = SpreadPoints(sym);
   int    allP = CountAllPositions();
   string blockReason="";
   g_trade_allowed = TradingAllowedNow(sym, blockReason);
   g_trade_block_reason = blockReason;
   if(bal > g_rt_peak_bal) g_rt_peak_bal = bal;
   g_rt_bar_count++;
   int h = FileOpen("ea_realtime_status.json",
                    FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h != INVALID_HANDLE)
   {
      MqlRates r[1];
      CopyRates(sym, PERIOD_M1, 0, 1, r);
      string j = "{";
      j += "\"bar\":"          + IntegerToString(g_rt_bar_count)            + ",";
      j += "\"time\":\""       + TimeToString(TimeCurrent())                + "\",";
      j += "\"symbol\":\""     + sym                                        + "\",";
      j += "\"account_login\":"+ IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
      j += "\"account_server\":\""+ AccountInfoString(ACCOUNT_SERVER) +"\"" + ",";
      j += "\"account_currency\":\""+ AccountInfoString(ACCOUNT_CURRENCY) +"\"" + ",";
      j += "\"balance\":"      + DoubleToString(bal, 2)                     + ",";
      j += "\"equity\":"       + DoubleToString(eq,  2)                     + ",";
      j += "\"peak_balance\":" + DoubleToString(g_rt_peak_bal, 2)          + ",";
      j += "\"open_pnl\":"     + DoubleToString(pnl, 2)                    + ",";
      j += "\"basket_pnl\":"   + DoubleToString(pnl, 2)                    + ",";
      j += "\"bid\":"          + DoubleToString(bid, DigitsOf(sym))         + ",";
      j += "\"ask\":"          + DoubleToString(ask, DigitsOf(sym))         + ",";
      j += "\"spread_points\":"+ DoubleToString(spr, 1)                     + ",";
      j += "\"trade_allowed\":"+ BoolJson(g_trade_allowed)                  + ",";
      j += "\"trade_block_reason\":\""+ g_trade_block_reason +"\""          + ",";
      j += "\"terminal_trade_allowed\":"+ BoolJson((bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) + ",";
      j += "\"mql_trade_allowed\":"+ BoolJson((bool)MQLInfoInteger(MQL_TRADE_ALLOWED)) + ",";
      j += "\"account_trade_allowed\":"+ BoolJson((bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)) + ",";
      j += "\"account_expert_allowed\":"+ BoolJson((bool)AccountInfoInteger(ACCOUNT_TRADE_EXPERT)) + ",";
      j += "\"symbol_trade_mode\":"+ IntegerToString((int)SymbolInfoInteger(sym,SYMBOL_TRADE_MODE)) + ",";
      j += "\"positions\":"    + IntegerToString(allP)                      + ",";
      j += "\"lot_factor\":"   + DoubleToString(g_state.lot_factor, 4)     + ",";
      j += "\"grid_factor\":"  + DoubleToString(g_state.grid_factor, 4)    + ",";
      j += "\"win_streak\":"   + IntegerToString(g_state.closed_win_streak) + ",";
      j += "\"loss_streak\":"  + IntegerToString(g_state.closed_loss_streak)+ ",";
      j += "\"dna_gap\":"      + IntegerToString(g_dna.ExtraTightGapPoints) + ",";
      j += "\"effective_gap\":"+ IntegerToString(ExactGapPoints(sym))        + ",";
      j += "\"dna_tp\":"       + DoubleToString(g_dna.BasketTakeProfitMoney,2)+",";
      j += "\"dna_sl\":"       + DoubleToString(g_dna.BasketStopLossMoney,2)  +",";
      j += "\"dna_lock_start\":"+ DoubleToString(g_dna.BasketLockStartMoney,2)+",";
      j += "\"dna_lock_giveback\":"+ DoubleToString(g_dna.BasketLockGiveBackMoney,2)+",";
      j += "\"secure_profit_start\":"+ DoubleToString(g_secure_profit_start,2)+",";
      j += "\"secure_profit_lock\":"+ DoubleToString(g_secure_profit_lock,2)+",";
      j += "\"live_control_epoch\":"+ IntegerToString(g_last_control_epoch)+",";
      j += "\"dna_gen\":"      + IntegerToString(g_current_generation)      + ",";
      j += "\"generation\":"   + IntegerToString(g_current_generation)      + ",";
      j += "\"adaptive_loss_streak\":"+ IntegerToString(g_state.adaptive_loss_streak)+ ",";
      j += "\"adaptive_win_streak\":"+ IntegerToString(g_state.adaptive_win_streak)+ ",";
      j += "\"adaptive_no_reverse\":"+ IntegerToString((int)MathMax(0,g_state.adaptive_no_reverse_until-TimeCurrent()))+ ",";
      j += "\"cooldown_enabled\":" + (InpUseCooldown ? "true" : "false") + ",";
      j += "\"cooldown\":"     + IntegerToString(InpUseCooldown ? (int)MathMax(0,g_state.cooldown_until-TimeCurrent()) : 0)+",";
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
   string histFile = "ea_bar_history.json";
   MqlRates hist[];
   ArraySetAsSeries(hist, true);
   int wanted = MathMax(20, InpRealtimeHistoryBars);
   int copied = CopyRates(sym, (ENUM_TIMEFRAMES)InpTimeframe, 0, wanted, hist);
   if(copied > 0)
   {
      int hw = FileOpen(histFile, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(hw != INVALID_HANDLE)
      {
         FileWriteString(hw, "[");
         int barNo = 1;
         for(int i = copied - 1; i >= 0; i--)
         {
            if(barNo > 1)
               FileWriteString(hw, ",");
            FileWriteString(hw, RealtimeHistoryEntryJson(hist[i], barNo, bal, eq, pnl, spr, allP, sym));
            barNo++;
         }
         FileWriteString(hw, "]");
         FileClose(hw);
         g_rt_history_started = true;
      }
   }
   SaveLiveDNASnapshot("bar", false);
}

void DrawChartInfo()
{
   string sym = g_profile.symbol;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl = BasketProfit();

   // ── حساب مؤشرات الـ Smart Entry للـ Dashboard ──
   double fast  = EMAFromCloses(sym, InpFastEMAPeriod,  100);
   double slow  = EMAFromCloses(sym, InpSlowEMAPeriod,  120);
   double trend = EMAFromCloses(sym, InpTrendEMAPeriod, 160);
   double rsi   = InpUseRSIFilter ? CalcRSI(sym, InpRSIPeriod) : 50.0;
   double cur_atr = CalcATRPoints(sym, 14);
   double avg_atr = CalcATRPoints(sym, g_dna.AtrBars);

   string ema_dir = "→ FLAT";
   color  ema_col = clrGray;
   if(fast>slow && slow>trend) { ema_dir = "↑ UP";   ema_col = clrLimeGreen; }
   if(fast<slow && slow<trend) { ema_dir = "↓ DOWN"; ema_col = clrOrangeRed; }

   string regime = "◆ NORMAL";
   color  reg_col = clrGold;
   if(avg_atr>0)
   {
      double ratio = cur_atr/avg_atr;
      if(ratio < InpATRRangingThreshold)          { regime = "⌀ RANGING"; reg_col = clrOrangeRed; }
      else if(ratio > 1.0/InpATRRangingThreshold) { regime = "▲ TRENDING";reg_col = clrLimeGreen; }
   }

   string rsi_str = "RSI: "+DoubleToString(rsi,1);
   color  rsi_col = clrDeepSkyBlue;
   if(rsi >= InpRSIBuyMax)  { rsi_col = clrOrangeRed;  rsi_str += " ⚠ OBOUGHT"; }
   if(rsi <= InpRSISellMin) { rsi_col = clrOrangeRed;  rsi_str += " ⚠ OSOLD";   }

   // cooldown indicator
   string cd_str = "";
   if(InpUseCooldown && TimeCurrent() < g_state.cooldown_until)
   {
      int secs = (int)(g_state.cooldown_until - TimeCurrent());
      cd_str = " | ❄ CD:"+IntegerToString(secs/60)+"m";
   }

   ObjectsDeleteAll(0, "RT_");
   // ── صف SMC ──
   color smc_col = clrGold;
   string smc_line = g_smc_status;
   if(g_smc_has_choch)     smc_col = clrHotPink;
   else if(g_smc_has_bos)  smc_col = (g_smc_bias_bullish ? clrLimeGreen : clrOrangeRed);
   else                    smc_col = clrGray;

   string all_labels[] = {
      "Bal: "    + DoubleToString(bal,2) + "$  Eq: " + DoubleToString(eq,2) + "$",
      "P&L: "    + DoubleToString(pnl,2) + "$  " + regime + cd_str,
      "EMA: "    + ema_dir + "  " + rsi_str,
      "ATR: "    + DoubleToString(cur_atr,1) + "  Gap: " + IntegerToString(g_dna.ExtraTightGapPoints) +
      "  Gen: "  + IntegerToString(g_current_generation) + "  Bar: " + IntegerToString(g_rt_bar_count),
      "SMC: "    + smc_line
   };
   color all_colors[] = {
      (bal >= 100.0 ? clrLimeGreen : clrOrangeRed),
      reg_col,
      ema_col,
      clrGold,
      smc_col
   };
   for(int i = 0; i < 5; i++)
   {
      string n = "RT_" + IntegerToString(i);
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, n, OBJPROP_YDISTANCE, 18 + i*17);
      ObjectSetString (0, n, OBJPROP_TEXT,      all_labels[i]);
      ObjectSetInteger(0, n, OBJPROP_COLOR,     all_colors[i]);
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
      { Print("[LIVE] Attach on ",GoldSymbol()," current=",_Symbol); return INIT_FAILED; }

   if(!LoadGoldProfile()) return INIT_FAILED;

   if(InpUseDNAEvolution)
   {
      MathSrand((int)TimeCurrent());
      g_dna=SelectNextDNA();
   }
   else
      g_dna=DefaultDNA();

   if(!InpUseCooldown)
   {
      g_state.cooldown_until = 0;
      g_dna.CooldownAfterTPMinutes = 0;
      g_dna.CooldownAfterSLMinutes = 0;
      g_dna.CooldownAfterLossMinutes = 0;
   }

   ApplyDNA(g_dna);

   g_rt_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_rt_peak_bal  = g_rt_start_bal;
   g_secure_profit_start = InpSecureProfitStartMoney;
   g_secure_profit_lock  = InpSecureProfitLockMoney;

   g_loaded=true;
   EventSetTimer(1);
   WriteRealtimeBar();
   DrawChartInfo();
   Log("LIVE V7.30 started on "+g_profile.symbol+" Gen="+IntegerToString(g_current_generation));
   
   // ⚠️ تحذير مهم للحساب الحقيقي
   if(!InpDryRunPrintOnly)
   {
      Print("╔══════════════════════════════════════════════════╗");
      Print("║  ⚠️  WARNING: LIVE TRADING ENABLED  ⚠️           ║");
      Print("║  DryRun = FALSE — Real orders will be sent!      ║");
      Print("║  Symbol: ", g_profile.symbol);
      Print("║  Base Lot: ", DoubleToString(g_profile.base_lot, 2));
      Print("║  Basket SL: $", DoubleToString(g_dna.BasketStopLossMoney, 2));
      Print("╚══════════════════════════════════════════════════╝");
   }
   
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(InpUseDNAEvolution && g_loaded)
   {
      SaveLiveDNASnapshot("deinit", true);
      Print("╔══════════════════════════════════════════╗");
      Print("║      DNA SAVED ON LIVE STOP — Gen ", g_current_generation, "      ║");
      Print("╚══════════════════════════════════════════╝");
   }
}
