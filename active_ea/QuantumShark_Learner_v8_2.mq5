//+------------------------------------------------------------------+
//|                              QuantumShark_Learner_v8_2.mq5       |
//|                    Self-Healing Scalper - Learns From Every Trade|
//+------------------------------------------------------------------+
#property copyright "QuantumShark AI"
#property version   "8.20"
#property description "🧠 Learns from trades | Smart Exit | No Panic"
#property description "🔧 Auto-fix bad DNA | Flexible RSI | Always enters"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                           |
//+------------------------------------------------------------------+
input group "=== ⚡ CORE ==="
input bool   EnableTrading = true;
input int    MagicNumber = 20250422;
input int    MaxPositions = 5;
input int    MinSecondsBetweenTrades = 2;

input group "=== 📊 INDICATORS ==="
input int    EMA_Fast = 8;
input int    EMA_Slow = 21;
input int    RSI_Period = 14;
input int    RSI_Overbought = 70;
input int    RSI_Oversold = 30;
input int    ATR_Period = 10;

input group "=== 💰 RISK (Auto-Tuned) ==="
input double BaseRiskPercent = 1.5;
input double MaxLot = 2.0;
input double MinLot = 0.01;

input group "=== 🎯 SL / TP ==="
input double SL_ATR_Mult = 1.2;
input double TP_ATR_Mult = 2.0;
input bool   EnableBE = true;
input double BE_ATR = 0.6;
input bool   EnableTrail = true;
input double Trail_ATR = 0.6;
input double TrailStep_ATR = 0.25;

input group "=== 📈 FILTERS ==="
input bool   UseTrendFilter = true;
input bool   UseRSIFilter = false;        // 🔥 OFF by default for more entries
input bool   ForceResetDNA = true;        // 🔥 Reset corrupted DNA on start

input group "=== 🛡️ SAFETY ==="
input double MaxDailyLossPct = 8.0;
input int    CooldownMinutes = 3;
input bool   EnableLogs = true;

//+------------------------------------------------------------------+
//| DNA STRUCT                                                       |
//+------------------------------------------------------------------+
struct DNA
{
   double sl_mult;
   double tp_mult;
   double risk_pct;
   double be_atr;
   double trail_atr;
   double trail_step;
   int    ema_zone;

   void Init()
   {
      sl_mult = SL_ATR_Mult;
      tp_mult = TP_ATR_Mult;
      risk_pct = BaseRiskPercent;
      be_atr = BE_ATR;
      trail_atr = Trail_ATR;
      trail_step = TrailStep_ATR;
      ema_zone = 400;
   }

   void Clamp()
   {
      sl_mult = MathMax(0.5, MathMin(3.0, sl_mult));
      tp_mult = MathMax(1.0, MathMin(4.0, tp_mult));
      risk_pct = MathMax(0.3, MathMin(4.0, risk_pct));
      be_atr = MathMax(0.2, MathMin(2.0, be_atr));
      trail_atr = MathMax(0.2, MathMin(2.0, trail_atr));
      trail_step = MathMax(0.1, MathMin(1.0, trail_step));
      ema_zone = MathMax(200, MathMin(1200, ema_zone));
   }

   bool IsCorrupt()
   {
      // DNA فاسدة إذا SL أكبر من TP بكثير أو SL > 3.0
      return (sl_mult > 3.0 || tp_mult < 1.0 || sl_mult > tp_mult * 1.5);
   }
};

//+------------------------------------------------------------------+
//| TRADE MEMORY                                                     |
//+------------------------------------------------------------------+
struct TradeMem
{
   ulong  ticket;
   string type;
   double profit;
   double lot;
   datetime time;
};

//+------------------------------------------------------------------+
//| GLOBALS                                                          |
//+------------------------------------------------------------------+
CTrade       Trade;
CPositionInfo PosInfo;

string       gSymbol;
double       gPoint;
int          gDigits;
double       gDailyEquity = 0;
datetime     gLastTradeTime = 0;
datetime     gCooldownUntil = 0;
bool         gHalted = false;
bool         gDidCloseToday = false;

DNA          gDNA;
TradeMem     gHistory[];
int          gHistoryCount = 0;

int          hEMAf, hEMAs, hRSI, hATR;

string       FILE_MEMORY = "QS_LearnMemory_v82.csv";
string       FILE_DNA = "QS_DNA_v82.cfg";

//+------------------------------------------------------------------+
void Log(string msg)
{
   if(EnableLogs) Print("[🧠QSv8.2] ", msg);
}

//+------------------------------------------------------------------+
//| SAVE / LOAD DNA                                                  |
//+------------------------------------------------------------------+
void SaveDNA()
{
   int h = FileOpen(FILE_DNA, FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
   if(h != INVALID_HANDLE)
   {
      FileWrite(h, gDNA.sl_mult, gDNA.tp_mult, gDNA.risk_pct, gDNA.be_atr, gDNA.trail_atr, gDNA.trail_step, gDNA.ema_zone);
      FileClose(h);
   }
}

//+------------------------------------------------------------------+
void LoadDNA()
{
   int h = FileOpen(FILE_DNA, FILE_READ|FILE_CSV|FILE_COMMON, ',');
   if(h != INVALID_HANDLE && !ForceResetDNA)
   {
      gDNA.sl_mult = StringToDouble(FileReadString(h));
      gDNA.tp_mult = StringToDouble(FileReadString(h));
      gDNA.risk_pct = StringToDouble(FileReadString(h));
      gDNA.be_atr = StringToDouble(FileReadString(h));
      gDNA.trail_atr = StringToDouble(FileReadString(h));
      gDNA.trail_step = StringToDouble(FileReadString(h));
      gDNA.ema_zone = (int)StringToInteger(FileReadString(h));
      FileClose(h);
      gDNA.Clamp();

      if(gDNA.IsCorrupt())
      {
         Log("⚠️ DNA corrupted (SL:" + DoubleToString(gDNA.sl_mult,2) + " > TP:" + DoubleToString(gDNA.tp_mult,2) + "). Resetting...");
         gDNA.Init();
         SaveDNA();
      }
      else
      {
         Log("📂 DNA loaded. SL:" + DoubleToString(gDNA.sl_mult,2) + "x TP:" + DoubleToString(gDNA.tp_mult,2) + "x");
      }
   }
   else
   {
      if(ForceResetDNA) Log("🔄 ForceResetDNA = true. Creating fresh DNA...");
      else Log("🆕 No DNA file found. Creating new...");
      gDNA.Init();
      SaveDNA();
   }
}

//+------------------------------------------------------------------+
void LogToMemory(TradeMem &t)
{
   int h = FileOpen(FILE_MEMORY, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
   if(h == INVALID_HANDLE)
   {
      h = FileOpen(FILE_MEMORY, FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
      if(h != INVALID_HANDLE) { FileWrite(h,"Ticket","Type","Profit","Lot","Time"); FileClose(h); }
      h = FileOpen(FILE_MEMORY, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
   }
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, IntegerToString(t.ticket), t.type, DoubleToString(t.profit,2), DoubleToString(t.lot,2), TimeToString(t.time));
      FileClose(h);
   }
}

//+------------------------------------------------------------------+
//| LEARNING ENGINE                                                  |
//+------------------------------------------------------------------+
void LearnFromHistory()
{
   if(gHistoryCount < 5) return;

   int wins = 0, losses = 0;
   double recent_profit = 0;
   int check = MathMin(10, gHistoryCount);

   for(int i = gHistoryCount - 1; i >= gHistoryCount - check; i--)
   {
      if(gHistory[i].profit > 0) wins++;
      else losses++;
      recent_profit += gHistory[i].profit;
   }

   double win_rate = (double)wins / check;
   Log("🧠 LEARN | Last" + IntegerToString(check) + " WR:" + DoubleToString(win_rate*100,1) + "% P/L:$" + DoubleToString(recent_profit,2));

   if(losses >= 4)
   {
      gDNA.sl_mult += 0.15;
      gDNA.risk_pct -= 0.2;
      gDNA.tp_mult -= 0.1;
      Log("🔧 CONSERVATIVE: SL↑ Risk↓");
   }
   else if(wins >= 4)
   {
      gDNA.tp_mult += 0.15;
      gDNA.sl_mult -= 0.1;
      gDNA.risk_pct += 0.15;
      Log("🔧 AGGRESSIVE: TP↑ Risk↑");
   }
   else
   {
      gDNA.ema_zone += 30;
      Log("🔧 EXPAND: Zone↑");
   }

   gDNA.Clamp();
   SaveDNA();
   PrintDNA();
}

//+------------------------------------------------------------------+
void PrintDNA()
{
   Log("🧬 DNA | SL:" + DoubleToString(gDNA.sl_mult,2) + "x | TP:" + DoubleToString(gDNA.tp_mult,2) + "x | Risk:" + DoubleToString(gDNA.risk_pct,2) + "% | Trail:" + DoubleToString(gDNA.trail_atr,2) + "/" + DoubleToString(gDNA.trail_step,2) + " | Zone:" + IntegerToString(gDNA.ema_zone));
}

//+------------------------------------------------------------------+
//| TRADING UTILS                                                    |
//+------------------------------------------------------------------+
double GetValidLot(double lot)
{
   double min_lot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP);
   if(lot_step <= 0) lot_step = 0.01;
   int d = (int)MathRound(-MathLog10(lot_step));
   double v = MathFloor(lot / lot_step) * lot_step;
   v = NormalizeDouble(v, d);
   return MathMax(min_lot, MathMin(max_lot, v));
}

//+------------------------------------------------------------------+
double CalcLot(double sl_dist)
{
   if(sl_dist <= 0) return MinLot;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_amt = equity * gDNA.risk_pct / 100.0;
   double tick_val = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0 || tick_val <= 0) return MinLot;
   double ticks = sl_dist / tick_size;
   if(ticks <= 0) return MinLot;
   return GetValidLot(risk_amt / (ticks * tick_val));
}

//+------------------------------------------------------------------+
int CountPos()
{
   int c = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(PosInfo.SelectByIndex(i))
         if(PosInfo.Symbol() == gSymbol && PosInfo.Magic() == MagicNumber)
            c++;
   return c;
}

//+------------------------------------------------------------------+
double GetOpenPL()
{
   double pl = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(PosInfo.SelectByIndex(i))
         if(PosInfo.Symbol() == gSymbol && PosInfo.Magic() == MagicNumber)
            pl += PosInfo.Profit() + PosInfo.Swap() + PosInfo.Commission();
   return pl;
}

//+------------------------------------------------------------------+
void CloseAllOnce(string reason)
{
   if(gDidCloseToday) return;
   gDidCloseToday = true;

   Log("🛑 HALT & CLOSE: " + reason);
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(PosInfo.SelectByIndex(i))
         if(PosInfo.Symbol() == gSymbol && PosInfo.Magic() == MagicNumber)
            Trade.PositionClose(PosInfo.Ticket());
   }

   gHalted = true;
   gCooldownUntil = TimeCurrent() + CooldownMinutes * 60;
   Log("⏸️ COOLDOWN for " + IntegerToString(CooldownMinutes) + " min");
}

//+------------------------------------------------------------------+
bool CheckDailyLoss()
{
   if(gHalted) return true;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(gDailyEquity <= 0) return false;

   double loss_pct = (gDailyEquity - equity) / gDailyEquity * 100.0;

   if(loss_pct >= MaxDailyLossPct)
   {
      CloseAllOnce("Daily Loss: " + DoubleToString(loss_pct,2) + "%");
      return true;
   }

   return false;
}

//+------------------------------------------------------------------+
bool GetIndis(double &ema_f, double &ema_s, double &rsi, double &atr, double &ema_fp, double &ema_sp)
{
   double b[2];
   if(CopyBuffer(hEMAf, 0, 0, 2, b) <= 0) return false;
   ema_f = b[0]; ema_fp = b[1];
   if(CopyBuffer(hEMAs, 0, 0, 2, b) <= 0) return false;
   ema_s = b[0]; ema_sp = b[1];
   if(CopyBuffer(hRSI, 0, 0, 1, b) <= 0) return false;
   rsi = b[0];
   if(CopyBuffer(hATR, 0, 0, 1, b) <= 0) return false;
   atr = b[0];
   return true;
}

//+------------------------------------------------------------------+
bool ValidLevels(double price, double sl, double tp, bool buy)
{
   long st = SymbolInfoInteger(gSymbol, SYMBOL_TRADE_STOPS_LEVEL);
   double md = (double)st * gPoint;
   if(md < 50 * gPoint) md = 50 * gPoint;
   int d = gDigits;
   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);

   if(buy)
   {
      if(sl >= price || NormalizeDouble(ask - sl, d) <= md) return false;
      if(tp <= price || NormalizeDouble(tp - ask, d) <= md) return false;
   }
   else
   {
      if(sl <= price || NormalizeDouble(sl - bid, d) <= md) return false;
      if(tp >= price || NormalizeDouble(bid - tp, d) <= md) return false;
   }
   return true;
}

//+------------------------------------------------------------------+
void OpenBuy(double atr, string reason)
{
   if(CountPos() >= MaxPositions) return;
   if(TimeCurrent() < gCooldownUntil) return;

   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   if(ask <= 0) return;

   double sl_dist = atr * gDNA.sl_mult;
   if(sl_dist < 80 * gPoint) sl_dist = 80 * gPoint;
   double tp_dist = atr * gDNA.tp_mult;
   if(tp_dist < 120 * gPoint) tp_dist = 120 * gPoint;

   int d = gDigits;
   double sl = NormalizeDouble(ask - sl_dist, d);
   double tp = NormalizeDouble(ask + tp_dist, d);
   if(!ValidLevels(ask, sl, tp, true)) return;

   double lot = CalcLot(sl_dist);
   if(lot < MinLot) return;

   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);

   if(Trade.Buy(lot, gSymbol, ask, sl, tp, "QSv8.2 BUY | " + reason))
   {
      gLastTradeTime = TimeCurrent();
      Log("✅ BUY | " + reason + " | Lot:" + DoubleToString(lot,2) + " | SL:" + DoubleToString(sl,d) + " | TP:" + DoubleToString(tp,d));
   }
}

//+------------------------------------------------------------------+
void OpenSell(double atr, string reason)
{
   if(CountPos() >= MaxPositions) return;
   if(TimeCurrent() < gCooldownUntil) return;

   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   if(bid <= 0) return;

   double sl_dist = atr * gDNA.sl_mult;
   if(sl_dist < 80 * gPoint) sl_dist = 80 * gPoint;
   double tp_dist = atr * gDNA.tp_mult;
   if(tp_dist < 120 * gPoint) tp_dist = 120 * gPoint;

   int d = gDigits;
   double sl = NormalizeDouble(bid + sl_dist, d);
   double tp = NormalizeDouble(bid - tp_dist, d);
   if(!ValidLevels(bid, sl, tp, false)) return;

   double lot = CalcLot(sl_dist);
   if(lot < MinLot) return;

   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);

   if(Trade.Sell(lot, gSymbol, bid, sl, tp, "QSv8.2 SELL | " + reason))
   {
      gLastTradeTime = TimeCurrent();
      Log("✅ SELL | " + reason + " | Lot:" + DoubleToString(lot,2) + " | SL:" + DoubleToString(sl,d) + " | TP:" + DoubleToString(tp,d));
   }
}

//+------------------------------------------------------------------+
//| MANAGE OPEN POSITIONS                                            |
//+------------------------------------------------------------------+
void ManagePositions()
{
   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;

   double ab[1];
   if(CopyBuffer(hATR, 0, 0, 1, ab) <= 0) return;
   double atr = ab[0];
   if(atr <= 0) return;

   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!PosInfo.SelectByIndex(i)) continue;
      if(PosInfo.Symbol() != gSymbol || PosInfo.Magic() != MagicNumber) continue;

      double op = PosInfo.PriceOpen();
      double csl = PosInfo.StopLoss();
      double ctp = PosInfo.TakeProfit();
      int d = gDigits;
      double min_dist = 50 * gPoint;

      if(PosInfo.PositionType() == POSITION_TYPE_BUY)
      {
         double profit_pts = (bid - op) / gPoint;

         if(EnableBE && profit_pts >= gDNA.be_atr * atr / gPoint && csl < op)
         {
            double nsl = NormalizeDouble(op + 20 * gPoint, d);
            if(nsl < bid - min_dist && nsl > csl)
               Trade.PositionModify(PosInfo.Ticket(), nsl, ctp);
         }

         if(EnableTrail && profit_pts > 0)
         {
            double nsl = NormalizeDouble(bid - gDNA.trail_atr * atr, d);
            double step = gDNA.trail_step * atr;
            if(nsl > op && nsl > csl + step && nsl < bid - min_dist)
               Trade.PositionModify(PosInfo.Ticket(), nsl, ctp);
         }
      }
      else
      {
         double profit_pts = (op - ask) / gPoint;

         if(EnableBE && profit_pts >= gDNA.be_atr * atr / gPoint && (csl > op || csl == 0))
         {
            double nsl = NormalizeDouble(op - 20 * gPoint, d);
            if(nsl > ask + min_dist && (csl == 0 || nsl < csl))
               Trade.PositionModify(PosInfo.Ticket(), nsl, ctp);
         }

         if(EnableTrail && profit_pts > 0)
         {
            double nsl = NormalizeDouble(ask + gDNA.trail_atr * atr, d);
            double step = gDNA.trail_step * atr;
            if(nsl < op && (csl == 0 || nsl < csl - step) && nsl > ask + min_dist)
               Trade.PositionModify(PosInfo.Ticket(), nsl, ctp);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| ONTRADE - Learning                                               |
//+------------------------------------------------------------------+
void OnTrade()
{
   static datetime last_check = 0;
   if(TimeCurrent() - last_check < 2) return;
   last_check = TimeCurrent();

   HistorySelect(0, TimeCurrent());
   int total = HistoryDealsTotal();

   for(int i = total - 1; i >= MathMax(0, total - 5); i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != gSymbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      datetime ttime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      if(gHistoryCount > 0 && ttime <= gHistory[gHistoryCount-1].time) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);

      ArrayResize(gHistory, gHistoryCount + 1);
      gHistory[gHistoryCount].ticket = ticket;
      gHistory[gHistoryCount].type = (HistoryDealGetInteger(ticket, DEAL_TYPE) == DEAL_TYPE_BUY) ? "BUY" : "SELL";
      gHistory[gHistoryCount].profit = profit;
      gHistory[gHistoryCount].lot = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      gHistory[gHistoryCount].time = ttime;
      gHistoryCount++;

      LogToMemory(gHistory[gHistoryCount-1]);
      Log("📊 CLOSED | P/L:$" + DoubleToString(profit,2) + " | Mem:" + IntegerToString(gHistoryCount));

      LearnFromHistory();
   }
}

//+------------------------------------------------------------------+
//| EXPERT INIT                                                      |
//+------------------------------------------------------------------+
int OnInit()
{
   gSymbol = Symbol();
   gPoint = SymbolInfoDouble(gSymbol, SYMBOL_POINT);
   gDigits = (int)SymbolInfoInteger(gSymbol, SYMBOL_DIGITS);

   Log("🧠 QuantumShark Learner v8.2 initializing...");
   Log("💎 " + gSymbol + " M1 | Flexible RSI | Auto-Fix DNA");

   hEMAf = iMA(gSymbol, PERIOD_M1, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   hEMAs = iMA(gSymbol, PERIOD_M1, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI = iRSI(gSymbol, PERIOD_M1, RSI_Period, PRICE_CLOSE);
   hATR = iATR(gSymbol, PERIOD_M1, ATR_Period);

   if(hEMAf == INVALID_HANDLE || hEMAs == INVALID_HANDLE || hRSI == INVALID_HANDLE || hATR == INVALID_HANDLE)
   {
      Log("❌ Indicator init failed");
      return INIT_FAILED;
   }

   LoadDNA();
   Trade.SetExpertMagicNumber(MagicNumber);
   gDailyEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   gHalted = false;
   gDidCloseToday = false;
   gCooldownUntil = 0;

   Log("✅ Ready. Equity: $" + DoubleToString(gDailyEquity,2));
   PrintDNA();

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   SaveDNA();
   if(hEMAf != INVALID_HANDLE) IndicatorRelease(hEMAf);
   if(hEMAs != INVALID_HANDLE) IndicatorRelease(hEMAs);
   if(hRSI != INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hATR != INVALID_HANDLE) IndicatorRelease(hATR);
   Log("🛑 Stopped. Trades: " + IntegerToString(gHistoryCount));
}

//+------------------------------------------------------------------+
void OnTick()
{
   static int last_day = -1;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(last_day != dt.day)
   {
      last_day = dt.day;
      gDailyEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      gHalted = false;
      gDidCloseToday = false;
      gCooldownUntil = 0;
      Log("🌅 NEW DAY | Equity: $" + DoubleToString(gDailyEquity,2));
   }

   if(!EnableTrading || gHalted) return;
   if(TimeCurrent() < gCooldownUntil)
   {
      static datetime last_cd = 0;
      if(TimeCurrent() - last_cd > 60)
      {
         last_cd = TimeCurrent();
         Log("⏳ COOLDOWN: " + IntegerToString((int)(gCooldownUntil - TimeCurrent())) + "s left");
      }
      return;
   }

   if(CheckDailyLoss()) return;

   ManagePositions();

   if(TimeCurrent() - gLastTradeTime < MinSecondsBetweenTrades) return;

   double ema_f, ema_s, rsi, atr, ema_fp, ema_sp;
   if(!GetIndis(ema_f, ema_s, rsi, atr, ema_fp, ema_sp)) return;
   if(atr <= 0) return;

   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;

   int d = gDigits;
   datetime cb = iTime(gSymbol, PERIOD_M1, 0);
   static datetime lb = 0;
   bool nb = (cb != lb);
   if(nb) lb = cb;

   double dist = (bid - ema_f) / gPoint;
   bool up = (ema_f > ema_s);
   bool down = (ema_f < ema_s);

   // 🔥 RSI مرن — يدخل في أي مكان ما عدا الذروة القصوى
   bool rsi_buy = (!UseRSIFilter) || (rsi < RSI_Overbought - 5);   // < 65
   bool rsi_sell = (!UseRSIFilter) || (rsi > RSI_Oversold + 5);    // > 35

   bool trend_ok_buy = (!UseTrendFilter) || up;
   bool trend_ok_sell = (!UseTrendFilter) || down;

   // إشارات الدخول
   bool cross_up = nb && (ema_fp <= ema_sp && ema_f > ema_s);
   bool cross_down = nb && (ema_fp >= ema_sp && ema_f < ema_s);

   // Pullback: السعر قريب من EMA (ضمن النطاق)
   bool pull_buy = (dist >= -gDNA.ema_zone && dist <= 150);        // تحت أو قريب من EMA
   bool pull_sell = (dist <= gDNA.ema_zone && dist >= -150);       // فوق أو قريب من EMA

   // Breakout: السعر يبتعد بقوة
   bool break_buy = (bid > ema_f + 40 * gPoint);
   bool break_sell = (bid < ema_f - 40 * gPoint);

   // Counter-trend: ارتداد عنيف عند الذروة
   bool counter_buy = down && (rsi < RSI_Oversold + 15) && (dist < -200);  // هابط لكن في ذروة بيع
   bool counter_sell = up && (rsi > RSI_Overbought - 15) && (dist > 200);  // صاعد لكن في ذروة شراء

   bool buy = (cross_up || pull_buy || break_buy || counter_buy) && trend_ok_buy && rsi_buy;
   bool sell = (cross_down || pull_sell || break_sell || counter_sell) && trend_ok_sell && rsi_sell;

   static datetime ld = 0;
   if(!buy && !sell && TimeCurrent() - ld > 15)
   {
      ld = TimeCurrent();
      string why = "T:" + (up?"UP":(down?"DOWN":"FLAT")) + " RSI:" + DoubleToString(rsi,1) + " D:" + DoubleToString(dist,0) + " R:" + DoubleToString(gDNA.risk_pct,1) + "%";
      if(!trend_ok_buy) why += " [NO-TREND-BUY]";
      if(!trend_ok_sell) why += " [NO-TREND-SELL]";
      if(!rsi_buy) why += " [RSI-BLOCK]";
      Log("🔍 " + why);
   }

   if(buy && !sell)
   {
      string r = cross_up ? "CROSS" : (pull_buy ? "PULL" : (break_buy ? "BREAK" : "COUNTER"));
      OpenBuy(atr, r);
   }
   else if(sell && !buy)
   {
      string r = cross_down ? "CROSS" : (pull_sell ? "PULL" : (break_sell ? "BREAK" : "COUNTER"));
      OpenSell(atr, r);
   }
}
//+------------------------------------------------------------------+
