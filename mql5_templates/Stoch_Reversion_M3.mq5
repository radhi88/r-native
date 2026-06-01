//+------------------------------------------------------------------+
//|  Stoch_Reversion_M3.mq5                                          |
//|  Gold M3 Stochastic Mean-Reversion EA                            |
//|                                                                  |
//|  Reverse-engineered from a chart screenshot showing:             |
//|    • XAUUSD on M3                                                |
//|    • Stochastic with histogram + signal line                     |
//|    • SELL entries near %D = 85 and 90 (pyramid)                  |
//|    • BUY entries near %D = 10 and 15                             |
//|    • TP at %D = 50 (mean reversion)                              |
//|                                                                  |
//|  Adds a conservative ATR stop-loss the screenshot lacked,        |
//|  so a runaway candle can't blow the account while Stochastic     |
//|  lingers at an extreme.                                          |
//+------------------------------------------------------------------+
#property copyright "R-Native"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//=== Inputs ========================================================
input group           "── Strategy thresholds"
input double InpOB_Heavy   = 90.0;   // SELL trigger (heavy)
input double InpOB_Light   = 85.0;   // SELL trigger (light, pyramid)
input double InpOS_Heavy   = 10.0;   // BUY trigger (heavy)
input double InpOS_Light   = 15.0;   // BUY trigger (light, pyramid)
input double InpMidline    = 50.0;   // Exit on %D crossing this

input group           "── Stochastic settings (MT5 defaults)"
input int    InpKPeriod    = 14;
input int    InpDPeriod    = 3;
input int    InpSlowing    = 3;
input ENUM_MA_METHOD InpMaMethod = MODE_SMA;
input ENUM_STO_PRICE InpStoPrice = STO_LOWHIGH;

input group           "── Risk"
input double InpLot        = 0.01;     // Lot per entry
input int    InpMaxTrades  = 2;        // Pyramid cap (per side)
input double InpAtrSlMult  = 2.5;      // SL distance = mult x ATR(14)
input int    InpAtrPeriod  = 14;
input bool   InpUseSL      = true;     // Set false to mirror the screenshot exactly

input group           "── Identity"
input ulong  InpMagic      = 20260605; // R magic
input string InpComment    = "R-Stoch-Rev";

//=== Internals =====================================================
int    g_hStoch  = INVALID_HANDLE;
int    g_hAtr    = INVALID_HANDLE;
double g_prevD   = EMPTY_VALUE;
datetime g_lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_hStoch = iStochastic(_Symbol, _Period, InpKPeriod, InpDPeriod, InpSlowing,
                          InpMaMethod, InpStoPrice);
   g_hAtr   = iATR(_Symbol, _Period, InpAtrPeriod);
   if(g_hStoch == INVALID_HANDLE || g_hAtr == INVALID_HANDLE)
   {
      Print("ERR: failed to create indicator handle, err=", GetLastError());
      return INIT_FAILED;
   }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   PrintFormat("Stoch-Reversion ready: K=%d D=%d slow=%d  | SELL@%.0f/%.0f  "
               "BUY@%.0f/%.0f  TP=%.0f  | SL=%s%.1fxATR  | maxTrades=%d",
               InpKPeriod, InpDPeriod, InpSlowing,
               InpOB_Heavy, InpOB_Light, InpOS_Heavy, InpOS_Light, InpMidline,
               (InpUseSL ? "" : "OFF (screenshot mode)  "),
               InpAtrSlMult, InpMaxTrades);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_hStoch != INVALID_HANDLE) IndicatorRelease(g_hStoch);
   if(g_hAtr   != INVALID_HANDLE) IndicatorRelease(g_hAtr);
}

//+------------------------------------------------------------------+
//  Read %D for the LAST CLOSED bar (shift = 1) and the prior one.
//+------------------------------------------------------------------+
bool ReadStoch(double &d_now, double &d_prev)
{
   double d[];
   if(CopyBuffer(g_hStoch, 1 /* %D buffer */, 1, 2, d) < 2)
      return false;
   // CopyBuffer: index 0 = oldest of the range, index 1 = newest
   d_prev = d[0];   // bar shift 2
   d_now  = d[1];   // bar shift 1 (just closed)
   return true;
}

bool ReadAtr(double &atr_v)
{
   double a[];
   if(CopyBuffer(g_hAtr, 0, 1, 1, a) < 1) return false;
   atr_v = a[0];
   return true;
}

//+------------------------------------------------------------------+
//  Helpers: count my open positions per side
//+------------------------------------------------------------------+
int CountPositions(int trade_type)
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)   continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;
      if((int)PositionGetInteger(POSITION_TYPE) == trade_type) n++;
   }
   return n;
}

void CloseAllMyPositions(const string why)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)   continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;
      if(trade.PositionClose(tk))
         PrintFormat("CLOSE #%I64u  reason=%s", tk, why);
      else
         PrintFormat("CLOSE FAIL #%I64u  err=%d", tk, GetLastError());
   }
}

//+------------------------------------------------------------------+
//  OnTick: only act on new-bar close, then evaluate %D crossings.
//+------------------------------------------------------------------+
void OnTick()
{
   datetime bar_time = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(bar_time == g_lastBarTime) return;     // not a new bar yet
   g_lastBarTime = bar_time;

   double d_now, d_prev;
   if(!ReadStoch(d_now, d_prev)) return;
   if(d_now == EMPTY_VALUE || d_prev == EMPTY_VALUE) return;

   //── Exit: %D crossed the midline (in either direction) ─────────
   bool crossed_mid_down = (d_prev > InpMidline && d_now <= InpMidline);
   bool crossed_mid_up   = (d_prev < InpMidline && d_now >= InpMidline);
   if(crossed_mid_down || crossed_mid_up)
   {
      if(PositionsTotal() > 0)
         CloseAllMyPositions(StringFormat("D %.1f -> %.1f cross 50", d_prev, d_now));
      return;
   }

   //── Entries ────────────────────────────────────────────────────
   bool sell_heavy = (d_prev >= InpOB_Heavy && d_now < InpOB_Heavy);
   bool sell_light = (d_prev >= InpOB_Light && d_now < InpOB_Light && !sell_heavy);
   bool buy_heavy  = (d_prev <= InpOS_Heavy && d_now > InpOS_Heavy);
   bool buy_light  = (d_prev <= InpOS_Light && d_now > InpOS_Light && !buy_heavy);

   if(sell_heavy || sell_light)
   {
      if(CountPositions(POSITION_TYPE_SELL) >= InpMaxTrades) return;
      OpenTrade(ORDER_TYPE_SELL, sell_heavy ? "H" : "L", d_now);
   }
   else if(buy_heavy || buy_light)
   {
      if(CountPositions(POSITION_TYPE_BUY) >= InpMaxTrades) return;
      OpenTrade(ORDER_TYPE_BUY, buy_heavy ? "H" : "L", d_now);
   }
}

//+------------------------------------------------------------------+
void OpenTrade(ENUM_ORDER_TYPE type, string tier, double d_now)
{
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double price = (type == ORDER_TYPE_BUY) ? tk.ask : tk.bid;
   double sl = 0.0;
   if(InpUseSL)
   {
      double atrv = 0.0;
      if(!ReadAtr(atrv) || atrv <= 0) atrv = (tk.ask - tk.bid) * 50.0;
      double dist = InpAtrSlMult * atrv;
      sl = (type == ORDER_TYPE_BUY) ? (price - dist) : (price + dist);
   }
   string cmt = StringFormat("%s-%s-D%.0f", InpComment,
                              (type == ORDER_TYPE_SELL) ? "S" : "B", d_now);
   bool ok = (type == ORDER_TYPE_BUY)
             ? trade.Buy (InpLot, _Symbol, price, sl, 0.0, cmt)
             : trade.Sell(InpLot, _Symbol, price, sl, 0.0, cmt);
   if(ok)
      PrintFormat("OPEN  %s  tier=%s  %s@%.5f  SL=%.5f  D=%.1f",
                  (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
                  tier, _Symbol, price, sl, d_now);
   else
      PrintFormat("OPEN FAIL  %s  err=%d  comment=%s",
                  (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
                  GetLastError(), trade.ResultComment());
}
//+------------------------------------------------------------------+
