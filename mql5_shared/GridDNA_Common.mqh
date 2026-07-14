//+------------------------------------------------------------------+
//| GridDNA_Common.mqh                                               |
//| Shared utility library for the Agentic Grid GOLD EAs.            |
//|                                                                  |
//| Extracted by PlutoBrain swarm (A-05) — 31 functions that are     |
//| BYTE-EXACT in both the Tester (active_ea) and Live (live_ea) EAs.|
//| Only verified-identical pure helpers are here; functions that    |
//| differ between the two EAs were deliberately left in place.      |
//|                                                                  |
//| To adopt (after a MetaEditor compile-test):                      |
//|   1. #include "<path>/GridDNA_Common.mqh" near the top of the EA |
//|      (AFTER any globals/inputs these helpers reference).         |
//|   2. Delete the inline copies of the functions below from the EA.|
//+------------------------------------------------------------------+
#ifndef __GRIDDNA_COMMON_MQH__
#define __GRIDDNA_COMMON_MQH__

void ApplyDNA(const AgentDNA &d)
{
   Print("[DNA] Applying DNA Gen=", d.generation,
         " Gap=", d.ExtraTightGapPoints,
         " TP=", DoubleToString(d.BasketTakeProfitMoney, 2),
         " SL=", DoubleToString(d.BasketStopLossMoney, 2),
         " LockStart=", DoubleToString(d.BasketLockStartMoney, 2),
         " LotReduce=", DoubleToString(d.LotReductionFactor, 2),
         " GridWiden=", DoubleToString(d.GridWidenFactor, 2),
         " CoolSL=", d.CooldownAfterSLMinutes,
         " ATR=", d.AtrBars);
}

double AskOf(string symbol)  { double a=0; SymbolInfoDouble(symbol,SYMBOL_ASK,a); return a; }

double BasketProfit()
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic; double pnl=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      pnl+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
   }
   return pnl;
}

double BidOf(string symbol)  { double b=0; SymbolInfoDouble(symbol,SYMBOL_BID,b); return b; }

int BrokerMinimumStopPoints(string symbol)
{
   int stops  = (int)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   int freeze = (int)SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   return MathMax(1,MathMax(stops,freeze)) + InpExtraStopBufferPoints;
}

double CalcATRPoints(string symbol,int bars)
{
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,0,bars+2,rates);
   if(copied<5) return 0.0;
   double pt=PointOf(symbol); if(pt<=0) return 0.0;
   double sum=0; int count=0;
   for(int i=1;i<copied-1;i++)
   {
      double tr=MathMax(rates[i].high-rates[i].low,
                MathMax(MathAbs(rates[i].high-rates[i+1].close),
                        MathAbs(rates[i].low-rates[i+1].close)));
      sum+=tr/pt; count++;
   }
   return count>0 ? sum/count : 0.0;
}

double ClampD(double v, double mn, double mx) { return MathMax(mn, MathMin(mx, v)); }

int    ClampI(int v, int mn, int mx)          { return (int)MathMax(mn, MathMin(mx, v)); }

int CountAllPositions()
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic; int c=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      c++;
   }
   return c;
}

int CountOrders(ENUM_ORDER_TYPE type)
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic; int c=0;
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(!tk) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym) continue;
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=mag) continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE)==type) c++;
   }
   return c;
}

int CountPositions(ENUM_POSITION_TYPE type)
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic; int c=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)==type) c++;
   }
   return c;
}

string DNACSVHeader()
{
   return "generation,fitness,profit_factor,max_drawdown_pct,total_trades,net_profit,"
          "ExtraTightGapPoints,ModifyStepPoints,BasketTakeProfit,BasketStopLoss,"
          "BasketLockStart,BasketLockGiveBack,CooldownTP,CooldownSL,CooldownLoss,"
          "LotReductionFactor,MinLotFactor,RecoveryLotStep,GridWidenFactor,"
          "MaxGridFactor,RecoveryGridStep,WinsToRecover,AtrBars";
}

int    DigitsOf(string symbol){ return (int)SymbolInfoInteger(symbol,SYMBOL_DIGITS); }

string DirectionOf(string symbol)
{
   string d=InpInitialDirection; StringToUpper(d);
   if(d=="BUY") return "BUY";
   if(d=="SELL") return "SELL";
   double fast=EMAFromCloses(symbol,9,40), slow=EMAFromCloses(symbol,21,80);
   if(fast==0||slow==0) return "BUY";
   return (fast>=slow?"BUY":"SELL");
}

double EMAFromCloses(string symbol,int period,int bars)
{
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,(ENUM_TIMEFRAMES)InpTimeframe,0,bars,rates);
   if(copied<period+5) return 0.0;
   double k=2.0/(period+1.0), ema=rates[copied-1].close;
   for(int i=copied-2;i>=0;i--) ema=rates[i].close*k+ema*(1.0-k);
   return ema;
}

bool EntryTimeAllowed()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   if(IsHourBlocked(dt.hour)) return false;
   if(InpUseFridayCloseFilter&&dt.day_of_week==5&&dt.hour>=InpFridayStopHour) return false;
   return true;
}

string GoldSymbol() { return (InpGoldSymbol != "") ? InpGoldSymbol : _Symbol; }

bool IsFreshTick(string symbol)
{
   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) return false;
   return (tick.ask>0 && tick.bid>0);
}

bool IsHourBlocked(int hour)
{
   if(!InpUseBlockedHours) return false;
   string s=InpBlockedHours; StringReplace(s," ","");
   string parts[]; int n=StringSplit(s,',',parts);
   for(int i=0;i<n;i++) if((int)StringToInteger(parts[i])==hour) return true;
   return false;
}

ulong LatestOrderTicket(ENUM_ORDER_TYPE type)
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   ulong latest=0; datetime latestTime=0;
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(!tk) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym) continue;
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=mag) continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE)!=type) continue;
      datetime t=(datetime)OrderGetInteger(ORDER_TIME_SETUP);
      if(!latest||t>=latestTime){ latest=tk; latestTime=t; }
   }
   return latest;
}

ulong LatestPositionTicket()
{
   string sym=g_profile.symbol; ulong mag=g_profile.magic;
   ulong latest=0; datetime latestTime=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(!tk) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=mag) continue;
      datetime t=(datetime)PositionGetInteger(POSITION_TIME);
      if(!latest||t>=latestTime){ latest=tk; latestTime=t; }
   }
   return latest;
}

void MarkSent(){ g_state.last_order_time=TimeCurrent(); }

double NormalizePrice(string symbol,double price){ return NormalizeDouble(price,DigitsOf(symbol)); }

double NormalizeVolume(string symbol, double volume)
{
   double minLot  = SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   volume = MathMax(minLot, MathMin(maxLot, volume));
   if(stepLot>0.0) volume = MathFloor(volume/stepLot)*stepLot;
   return NormalizeDouble(volume,4);
}

double PointOf(string symbol){ double p=0; SymbolInfoDouble(symbol,SYMBOL_POINT,p); return p; }

void RecoverRiskIfNeeded()
{
   if(!InpRecoverAfterWins) return;
   if(g_state.closed_win_streak<g_dna.WinsToRecover) return;
   g_state.lot_factor=MathMin(1.0,g_state.lot_factor+g_dna.RecoveryLotStep);
   g_state.grid_factor=MathMax(1.0,g_state.grid_factor-g_dna.RecoveryGridStep);
   g_state.closed_win_streak=0;
   Log("Recover risk lotF="+DoubleToString(g_state.lot_factor,2)+" gridF="+DoubleToString(g_state.grid_factor,2));
}

double ReverseBuyStopPrice()
{
   string sym=g_profile.symbol;
   return NormalizePrice(sym, AskOf(sym) + ExactGapPoints(sym)*PointOf(sym));
}

double ReverseSellStopPrice()
{
   string sym=g_profile.symbol;
   return NormalizePrice(sym, BidOf(sym) - ExactGapPoints(sym)*PointOf(sym));
}

bool SelectSymbolSafe(string symbol)
{
   if(SymbolInfoInteger(symbol, SYMBOL_SELECT)) return true;
   return SymbolSelect(symbol, true);
}

bool SpreadAllowed()
{
   if(!InpUseSpreadFilter) return true;
   double atrp=CalcATRPoints(g_profile.symbol,g_dna.AtrBars);
   if(atrp<=0) return false;
   double maxRatio=g_profile.max_spread_to_atr_ratio;
   if(InpMaxSpreadToAtrRatioOverride>0) maxRatio=InpMaxSpreadToAtrRatioOverride;
   return (SpreadPoints(g_profile.symbol)/atrp<=maxRatio);
}

double SpreadPoints(string symbol)
{
   double ask=AskOf(symbol), bid=BidOf(symbol), pt=PointOf(symbol);
   if(ask<=0||bid<=0||pt<=0) return 999999.0;
   return MathAbs(ask-bid)/pt;
}

#endif // __GRIDDNA_COMMON_MQH__
