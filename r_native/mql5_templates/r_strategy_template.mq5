//+------------------------------------------------------------------+
//|  {{GENOME_ID}} — R Native Generated EA                          |
//|  Symbol: {{SYMBOL}}  TF: {{TIMEFRAME}}                          |
//|  PF: {{PF}}  WR: {{WIN_RATE}}%  Trades: {{TRADES}}              |
//|  Generated: {{GENERATED_AT}}                                    |
//+------------------------------------------------------------------+
#property copyright "R Native — Generated EA"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

// ── Inputs (auto-generated from genome) ─────────────────────────
input double SL_ATR_MULT       = {{SL_ATR_MULT}};
input double TP_ATR_MULT       = {{TP_ATR_MULT}};
input int    START_HOUR        = {{START_HOUR}};
input int    END_HOUR          = {{END_HOUR}};
input int    RSI_PERIOD        = {{RSI_PERIOD}};
input int    EMA_FAST          = {{EMA_FAST}};
input int    EMA_SLOW          = {{EMA_SLOW}};
input int    ATR_PERIOD        = {{ATR_PERIOD}};
input int    BREAKOUT_LOOKBACK = {{BREAKOUT_LOOKBACK}};
input double LOT_SIZE          = 0.01;
input int    MAGIC             = 20260605;
input int    MAX_POSITIONS     = 1;
input bool   USE_BREAKEVEN     = {{USE_BREAKEVEN}};
input bool   USE_FRIDAY_CLOSE  = {{USE_FRIDAY_CLOSE}};
input int    FRIDAY_CLOSE_HOUR = 19;
input bool   ENABLE_TRADING    = false;   // SAFETY: must be set true manually

// ── Active gene flags (1 = on, 0 = off) ──────────────────────────
#define SIG_BREAKOUT     {{SIG_BREAKOUT}}
#define SIG_RSI          {{SIG_RSI}}
#define SIG_MACD         {{SIG_MACD}}
#define SIG_ENGULFING    {{SIG_ENGULFING}}
#define SIG_MOM_BREAK    {{SIG_MOM_BREAK}}
#define BIAS_RSI         {{BIAS_RSI}}
#define BIAS_EMA         {{BIAS_EMA}}
#define BIAS_SMA         {{BIAS_SMA}}
#define FILT_ADX         {{FILT_ADX}}
#define FILT_CONSEC      {{FILT_CONSEC}}

// ── Indicator handles ────────────────────────────────────────────
int rsi_handle, ema_fast_handle, ema_slow_handle, atr_handle, adx_handle;

int OnInit()
{
   trade.SetExpertMagicNumber(MAGIC);
   rsi_handle      = iRSI(_Symbol, PERIOD_CURRENT, RSI_PERIOD, PRICE_CLOSE);
   ema_fast_handle = iMA(_Symbol, PERIOD_CURRENT, EMA_FAST, 0, MODE_EMA, PRICE_CLOSE);
   ema_slow_handle = iMA(_Symbol, PERIOD_CURRENT, EMA_SLOW, 0, MODE_EMA, PRICE_CLOSE);
   atr_handle      = iATR(_Symbol, PERIOD_CURRENT, ATR_PERIOD);
   adx_handle      = iADX(_Symbol, PERIOD_CURRENT, 14);

   if(rsi_handle == INVALID_HANDLE || ema_fast_handle == INVALID_HANDLE ||
      atr_handle == INVALID_HANDLE)
   {
      Print("Init failed: indicator handle invalid");
      return INIT_FAILED;
   }
   Print("R Native EA loaded: ", "{{GENOME_ID}}", " on ", _Symbol);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(rsi_handle);
   IndicatorRelease(ema_fast_handle);
   IndicatorRelease(ema_slow_handle);
   IndicatorRelease(atr_handle);
   IndicatorRelease(adx_handle);
}

//+------------------------------------------------------------------+
//| Main tick handler                                                |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!ENABLE_TRADING) return;
   if(!IsNewBar()) return;

   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   // Session window
   if(now.hour < START_HOUR || now.hour >= END_HOUR) return;

   // Friday close
   if(USE_FRIDAY_CLOSE && now.day_of_week == 5 && now.hour >= FRIDAY_CLOSE_HOUR)
   {
      CloseAllPositions();
      return;
   }

   // Already at max positions?
   if(CountOpenPositions() >= MAX_POSITIONS) {
      ManageOpenPositions();
      return;
   }

   // Get indicator values
   double rsi[], ema_fast[], ema_slow[], atr[], adx[];
   if(CopyBuffer(rsi_handle,      0, 0, 3, rsi)      < 3) return;
   if(CopyBuffer(ema_fast_handle, 0, 0, 3, ema_fast) < 3) return;
   if(CopyBuffer(ema_slow_handle, 0, 0, 3, ema_slow) < 3) return;
   if(CopyBuffer(atr_handle,      0, 0, 3, atr)      < 3) return;
   if(CopyBuffer(adx_handle,      0, 0, 3, adx)      < 3) return;

   double cur_atr = atr[1];
   double cur_rsi = rsi[1];
   double price   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point   = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   // Bias check (any active bias gene must agree)
   bool bias_ok = true;
   #if BIAS_RSI
      bias_ok &= (cur_rsi > 50);
   #endif
   #if BIAS_EMA
      bias_ok &= (ema_fast[1] > ema_slow[1]);
   #endif
   #if FILT_ADX
      if(adx[1] < 20) return;
   #endif

   // Signal detection
   bool buy_signal = false, sell_signal = false;
   #if SIG_RSI
      if(cur_rsi < 30) buy_signal = true;
      if(cur_rsi > 70) sell_signal = true;
   #endif
   #if SIG_BREAKOUT
   {
      double recent_high = iHigh(_Symbol, PERIOD_CURRENT, iHighest(_Symbol, PERIOD_CURRENT, MODE_HIGH, BREAKOUT_LOOKBACK, 1));
      double recent_low  = iLow(_Symbol,  PERIOD_CURRENT, iLowest(_Symbol,  PERIOD_CURRENT, MODE_LOW,  BREAKOUT_LOOKBACK, 1));
      if(price > recent_high) buy_signal = true;
      if(price < recent_low)  sell_signal = true;
   }
   #endif

   if(!bias_ok) return;

   // Place trade
   double sl_dist = cur_atr * SL_ATR_MULT;
   double tp_dist = cur_atr * TP_ATR_MULT;
   if(buy_signal)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      trade.Buy(LOT_SIZE, _Symbol, ask, ask - sl_dist, ask + tp_dist,
                "R_Native " + "{{GENOME_ID}}");
   }
   else if(sell_signal)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      trade.Sell(LOT_SIZE, _Symbol, bid, bid + sl_dist, bid - tp_dist,
                 "R_Native " + "{{GENOME_ID}}");
   }
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) && PositionGetInteger(POSITION_MAGIC) == MAGIC)
         count++;
   }
   return count;
}

void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) && PositionGetInteger(POSITION_MAGIC) == MAGIC)
         trade.PositionClose(ticket);
   }
}

void ManageOpenPositions()
{
   if(!USE_BREAKEVEN) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MAGIC) continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double cur  = PositionGetDouble(POSITION_PRICE_CURRENT);
      double sl   = PositionGetDouble(POSITION_SL);
      double atr_v[];
      if(CopyBuffer(atr_handle, 0, 0, 2, atr_v) < 2) continue;
      bool is_buy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double dist = is_buy ? (cur - open) : (open - cur);
      if(dist > atr_v[1] * 1.5 && (is_buy ? sl < open : sl > open))
      {
         double new_sl = is_buy ? (open + atr_v[1] * 0.1) : (open - atr_v[1] * 0.1);
         trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP));
      }
   }
}

bool IsNewBar()
{
   static datetime last = 0;
   datetime cur = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(cur != last) { last = cur; return true; }
   return false;
}
//+------------------------------------------------------------------+
