//+------------------------------------------------------------------+
//|  Stoch_Reversion_M3.mq5 — Stochastic Reversion EA for Gold M3  |
//|  Strategy: SELL on Stoch overbought / BUY on oversold           |
//|  TP: price reverts to midline (Stoch %D crosses back to 50)     |
//|  SL: ATR-based                                                  |
//|  Magic: 20260605                                                 |
//+------------------------------------------------------------------+
#property copyright   "R-Native v2"
#property version     "1.01"
#property strict

#include <Trade\Trade.mqh>
#include <Indicators\Trend.mqh>

//--- Input parameters
input double InpOB_Heavy    = 90.0;    // Overbought — heavy signal (%D)
input double InpOB_Light    = 85.0;    // Overbought — light signal (%D)
input double InpOS_Heavy    = 10.0;    // Oversold   — heavy signal (%D)
input double InpOS_Light    = 15.0;    // Oversold   — light signal (%D)
input double InpMidline     = 50.0;    // TP midline (%D cross)
input int    InpKPeriod     = 5;       // Stoch %K period
input int    InpDPeriod     = 3;       // Stoch %D period
input int    InpSlowing     = 3;       // Stoch slowing
input double InpLot         = 0.01;    // Lot size
input int    InpMaxTrades   = 2;       // Max concurrent trades
input bool   InpUseSL       = true;    // Use Stop-Loss
input double InpAtrSlMult   = 2.5;     // SL = ATR × multiplier
input int    InpAtrPeriod   = 14;      // ATR period
input int    InpMagic       = 20260605;// Magic number
input string InpComment     = "StochReversion";

//--- Globals
CTrade trade;
int    stochHandle, atrHandle;
double stochK[], stochD[], atrBuf[];
datetime lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30);

   stochHandle = iStochastic(_Symbol, PERIOD_CURRENT,
                              InpKPeriod, InpDPeriod, InpSlowing,
                              MODE_SMA, STO_LOWHIGH);
   if(stochHandle == INVALID_HANDLE)
     {
      Print("ERROR: iStochastic failed: ", GetLastError());
      return INIT_FAILED;
     }

   atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpAtrPeriod);
   if(atrHandle == INVALID_HANDLE)
     {
      Print("ERROR: iATR failed: ", GetLastError());
      return INIT_FAILED;
     }

   ArraySetAsSeries(stochK, true);
   ArraySetAsSeries(stochD, true);
   ArraySetAsSeries(atrBuf, true);

   Print("Stoch_Reversion_M3 initialized. Magic=", InpMagic,
         "  OB=", InpOB_Heavy, "/", InpOB_Light,
         "  OS=", InpOS_Heavy, "/", InpOS_Light);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
void OnTick()
  {
   //--- Only act on new bar
   datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barTime == lastBarTime) return;
   lastBarTime = barTime;

   //--- Copy indicators (3 bars enough)
   if(CopyBuffer(stochHandle, MAIN_LINE,    0, 3, stochK) < 3) return;
   if(CopyBuffer(stochHandle, SIGNAL_LINE,  0, 3, stochD) < 3) return;
   if(CopyBuffer(atrHandle,   0,            0, 2, atrBuf) < 2) return;

   double d0    = stochD[0];   // current closed bar
   double d1    = stochD[1];   // previous bar
   double atr   = atrBuf[1];
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   //--- Manage open positions: check TP (midline cross) and SL
   _ManagePositions(d1, d0);

   //--- Count existing positions
   int countBuy  = _CountPositions(ORDER_TYPE_BUY);
   int countSell = _CountPositions(ORDER_TYPE_SELL);
   int total     = countBuy + countSell;

   if(total >= InpMaxTrades) return;

   //--- SELL: %D ≥ OB_Heavy OR two consecutive bars ≥ OB_Light
   bool sellHeavy = (d0 >= InpOB_Heavy);
   bool sellLight = (d1 >= InpOB_Light && d0 >= InpOB_Light);
   if((sellHeavy || sellLight) && countSell == 0)
     {
      double sl = InpUseSL ? (price + atr * InpAtrSlMult) : 0.0;
      double tp = 0.0;  // TP handled by midline logic in ManagePositions
      if(trade.Sell(InpLot, _Symbol, price, sl, tp, InpComment))
         Print("OPEN SELL @ ", price, "  SL=", sl, "  D=", d0);
      return;
     }

   //--- BUY: %D ≤ OS_Heavy OR two consecutive bars ≤ OS_Light
   bool buyHeavy = (d0 <= InpOS_Heavy);
   bool buyLight = (d1 <= InpOS_Light && d0 <= InpOS_Light);
   if((buyHeavy || buyLight) && countBuy == 0)
     {
      double sl = InpUseSL ? (price - atr * InpAtrSlMult) : 0.0;
      double tp = 0.0;
      if(trade.Buy(InpLot, _Symbol, price, sl, tp, InpComment))
         Print("OPEN BUY  @ ", price, "  SL=", sl, "  D=", d0);
     }
  }

//+------------------------------------------------------------------+
void _ManagePositions(double dPrev, double dCur)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC)  != InpMagic)  continue;
      if(PositionGetString(POSITION_SYMBOL)  != _Symbol)   continue;

      long  posType = PositionGetInteger(POSITION_TYPE);

      //--- SELL: TP when %D crosses back below midline
      if(posType == POSITION_TYPE_SELL)
        {
         if(dPrev >= InpMidline && dCur < InpMidline)
           {
            double closePrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            if(trade.PositionClose(ticket))
               Print("CLOSE SELL (TP midline) @ ", closePrice, "  D=", dCur);
           }
        }
      //--- BUY: TP when %D crosses back above midline
      else if(posType == POSITION_TYPE_BUY)
        {
         if(dPrev <= InpMidline && dCur > InpMidline)
           {
            double closePrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            if(trade.PositionClose(ticket))
               Print("CLOSE BUY  (TP midline) @ ", closePrice, "  D=", dCur);
           }
        }
     }
  }

//+------------------------------------------------------------------+
int _CountPositions(ENUM_ORDER_TYPE orderType)
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)  continue;
      if((ENUM_ORDER_TYPE)PositionGetInteger(POSITION_TYPE) == orderType)
         count++;
     }
   return count;
  }
//+------------------------------------------------------------------+
