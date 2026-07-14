//+------------------------------------------------------------------+
//|                              QuantumShark_Learner_v8_3.mq5       |
//|        Multi-Gene Self-Learning Scalper                          |
//|  Each GENE has its own indicators, session, signal-weights, DNA. |
//|  Trades are attributed per-gene (magic = base+gene). Each gene   |
//|  learns from its own wins/losses and evolves. Spread filter +    |
//|  entry throttle added. Genes persist to a CSV "vault".           |
//+------------------------------------------------------------------+
#property copyright "QuantumShark AI"
#property version   "8.31"
#property description "🧬 Multi-gene learner: per-gene indicators/times/weights"
#property description "🌙 Night discipline | 🕯️ rejection-wick reversal (buy instead of sell)"
#property description "🔧 Per-SIGNAL weight learning saved per gene | spread filter | throttle"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                           |
//+------------------------------------------------------------------+
input group "=== ⚡ CORE ==="
input bool   EnableTrading        = true;
input int    MagicBase            = 20250430;   // gene g uses MagicBase+g
input int    NumGenes             = 6;          // 1..MAX_GENES
input int    MaxPositions         = 5;          // total across all genes

input group "=== 🚦 THROTTLE / SPREAD (new) ==="
input double MaxSpreadPoints      = 350;        // block entries when spread wider than this
input int    MinSecondsBetween    = 5;          // min seconds between ANY two entries
input int    MaxEntriesPerMinute  = 4;          // hard cap on entry rate
input int    MaxEntriesPerBar     = 1;          // at most this many new entries per M1 bar

input group "=== 💰 RISK ==="
input double BaseRiskPercent      = 1.0;
input double MaxLot               = 2.0;
input double MinLot               = 0.01;

input group "=== 🌙 NIGHT DISCIPLINE (your real edge) ==="
input bool   BlockNight           = true;       // no entries during the losing night window
input int    NightStartHour       = 22;         // server hour the night block starts
input int    NightEndHour         = 8;          // server hour it ends (block = [start..end))

input group "=== 🕯️ REVERSAL (rejection wick) ==="
input bool   UseRejectionWick     = true;       // long-tail rejection can flip BUY<->SELL counter-trend
input double WickBodyRatio        = 1.5;        // tail must exceed body by this factor
input double WickRangeFrac        = 0.5;        // tail must be >= this fraction of the candle range

input group "=== 🛡️ SAFETY ==="
input double MaxGeneDailyLoss     = 50.0;       // $ per-gene daily loss cap — benches a bleeding gene (0=off)
input double MaxDailyLossPct      = 8.0;
input int    CooldownMinutes      = 3;
input bool   ForceResetGenes      = false;      // wipe vault and reseed on start
input bool   EnableLogs           = true;

#define MAX_GENES 8

//+------------------------------------------------------------------+
//| GENE — own indicators, session, signal-weights, risk DNA, record |
//+------------------------------------------------------------------+
struct Gene
{
   int    id;
   // --- own indicators ---
   int    ema_fast, ema_slow, rsi_period, atr_period;
   // --- own session window (server hours) ---
   int    start_hour, end_hour;
   // --- own signal weights (which setups this gene trusts) ---
   double w_cross, w_pull, w_break, w_counter, w_reject;
   double entry_threshold;        // weighted score needed to fire
   int    ema_zone;               // pullback band (points)
   // --- own risk DNA ---
   double sl_mult, tp_mult, risk_pct, be_atr, trail_atr, trail_step;
   // --- learned record ---
   int    wins, losses;
   double net;
   double score;                  // fitness -> selection priority
   // --- runtime only (not persisted) ---
   double day_net;                // this gene's P&L so far today
   bool   benched;                // disabled for the day after hitting its loss cap
   int    hEMAf, hEMAs, hRSI, hATR;
};

Gene gGenes[MAX_GENES];
int  gNum = 0;

//+------------------------------------------------------------------+
//| GLOBALS                                                          |
//+------------------------------------------------------------------+
CTrade        Trade;
CPositionInfo PosInfo;

string   gSymbol;
double   gPoint;
int      gDigits;
double   gDailyEquity = 0;
datetime gCooldownUntil = 0;
bool     gHalted = false;
bool     gDidCloseToday = false;

datetime gEntryTimes[64];          // ring buffer of recent entry timestamps (throttle)
int      gEntryIdx = 0;
datetime gLastBar = 0;
int      gEntriesThisBar = 0;

string   FILE_VAULT = "QS_GeneVault_v83.csv";

//+------------------------------------------------------------------+
void Log(string m){ if(EnableLogs) Print("[🧬QSv8.3] ", m); }

double Clampd(double v,double lo,double hi){ return MathMax(lo, MathMin(hi, v)); }
int    Clampi(int v,int lo,int hi){ return (int)MathMax(lo, MathMin(hi, v)); }

// 🌙 night-discipline window (server hours); handles the midnight wrap
bool IsNight(int hour)
{
   if(NightStartHour==NightEndHour) return false;
   if(NightStartHour < NightEndHour) return (hour>=NightStartHour && hour<NightEndHour);
   return (hour>=NightStartHour || hour<NightEndHour);
}

//+------------------------------------------------------------------+
//| SEED a diverse gene (different indicators/times/weights each)    |
//+------------------------------------------------------------------+
void SeedGene(Gene &g, int id)
{
   g.id = id;
   // diversify indicators across genes
   g.ema_fast   = 5 + (id * 2) % 10;          // 5,7,9,...
   g.ema_slow   = 18 + (id * 5) % 30;         // spread out slow EMA
   g.rsi_period = 10 + (id * 3) % 12;
   g.atr_period = 8 + (id * 2) % 10;
   // diversify sessions: split the day so genes specialise in different hours
   int span = 24 / MathMax(1, NumGenes);
   g.start_hour = Clampi((id * span) % 24, 0, 23);
   g.end_hour   = Clampi(g.start_hour + span + 2, 0, 23);
   if(g.end_hour <= g.start_hour) g.end_hour = 23;
   // diversify which setups it trusts
   g.w_cross   = 0.4 + 0.1 * ((id)   % 4);
   g.w_pull    = 0.3 + 0.1 * ((id+1) % 4);
   g.w_break   = 0.3 + 0.1 * ((id+2) % 4);
   g.w_counter = 0.2 + 0.1 * ((id+3) % 4);
   g.w_reject  = 0.5 + 0.1 * ((id+2) % 4);   // rejection-wick trust (reversal)
   g.entry_threshold = 0.5;
   g.ema_zone = 300 + (id * 60) % 600;
   // risk DNA
   g.sl_mult = 1.2; g.tp_mult = 2.0; g.risk_pct = BaseRiskPercent;
   g.be_atr = 0.6;  g.trail_atr = 0.6; g.trail_step = 0.25;
   // record
   g.wins = 0; g.losses = 0; g.net = 0; g.score = 0;
   g.day_net = 0; g.benched = false;
   g.hEMAf = g.hEMAs = g.hRSI = g.hATR = INVALID_HANDLE;
}

void ClampGene(Gene &g)
{
   g.sl_mult   = Clampd(g.sl_mult, 0.5, 3.0);
   g.tp_mult   = Clampd(g.tp_mult, 1.0, 4.0);
   g.risk_pct  = Clampd(g.risk_pct, 0.3, 3.0);
   g.be_atr    = Clampd(g.be_atr, 0.2, 2.0);
   g.trail_atr = Clampd(g.trail_atr, 0.2, 2.0);
   g.trail_step= Clampd(g.trail_step, 0.1, 1.0);
   g.ema_zone  = Clampi(g.ema_zone, 150, 1200);
   g.entry_threshold = Clampd(g.entry_threshold, 0.3, 2.0);
   g.w_cross   = Clampd(g.w_cross, 0.0, 1.5);
   g.w_pull    = Clampd(g.w_pull, 0.0, 1.5);
   g.w_break   = Clampd(g.w_break, 0.0, 1.5);
   g.w_counter = Clampd(g.w_counter, 0.0, 1.5);
   g.w_reject  = Clampd(g.w_reject, 0.0, 1.5);
}

void RecomputeScore(Gene &g)
{
   int n = g.wins + g.losses;
   double wr = (n > 0) ? (double)g.wins / n : 0.5;
   // fitness: net dollars weighted by win-rate confidence; unknown genes ~0
   g.score = g.net * (0.5 + wr) + (n < 3 ? 0.0 : 0.0);
}

//+------------------------------------------------------------------+
//| VAULT: save / load all genes                                     |
//+------------------------------------------------------------------+
void SaveVault()
{
   int h = FileOpen(FILE_VAULT, FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return;
   FileWrite(h,"id","ema_fast","ema_slow","rsi","atr","sh","eh",
             "w_cross","w_pull","w_break","w_counter","w_reject","thresh","zone",
             "sl","tp","risk","be","trail","tstep","wins","losses","net","score");
   for(int i=0;i<gNum;i++)
   {
      Gene g = gGenes[i];
      FileWrite(h, g.id, g.ema_fast, g.ema_slow, g.rsi_period, g.atr_period,
                g.start_hour, g.end_hour,
                DoubleToString(g.w_cross,3), DoubleToString(g.w_pull,3),
                DoubleToString(g.w_break,3), DoubleToString(g.w_counter,3),
                DoubleToString(g.w_reject,3),
                DoubleToString(g.entry_threshold,3), g.ema_zone,
                DoubleToString(g.sl_mult,3), DoubleToString(g.tp_mult,3),
                DoubleToString(g.risk_pct,3), DoubleToString(g.be_atr,3),
                DoubleToString(g.trail_atr,3), DoubleToString(g.trail_step,3),
                g.wins, g.losses, DoubleToString(g.net,2), DoubleToString(g.score,2));
   }
   FileClose(h);
}

bool LoadVault()
{
   int h = FileOpen(FILE_VAULT, FILE_READ|FILE_CSV|FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return false;
   // skip header (24 fields)
   for(int k=0;k<24 && !FileIsEnding(h);k++) FileReadString(h);
   gNum = 0;
   while(!FileIsEnding(h) && gNum < MAX_GENES && gNum < NumGenes)
   {
      Gene g;
      g.id         = (int)StringToInteger(FileReadString(h));
      g.ema_fast   = (int)StringToInteger(FileReadString(h));
      g.ema_slow   = (int)StringToInteger(FileReadString(h));
      g.rsi_period = (int)StringToInteger(FileReadString(h));
      g.atr_period = (int)StringToInteger(FileReadString(h));
      g.start_hour = (int)StringToInteger(FileReadString(h));
      g.end_hour   = (int)StringToInteger(FileReadString(h));
      g.w_cross    = StringToDouble(FileReadString(h));
      g.w_pull     = StringToDouble(FileReadString(h));
      g.w_break    = StringToDouble(FileReadString(h));
      g.w_counter  = StringToDouble(FileReadString(h));
      g.w_reject   = StringToDouble(FileReadString(h));
      g.entry_threshold = StringToDouble(FileReadString(h));
      g.ema_zone   = (int)StringToInteger(FileReadString(h));
      g.sl_mult    = StringToDouble(FileReadString(h));
      g.tp_mult    = StringToDouble(FileReadString(h));
      g.risk_pct   = StringToDouble(FileReadString(h));
      g.be_atr     = StringToDouble(FileReadString(h));
      g.trail_atr  = StringToDouble(FileReadString(h));
      g.trail_step = StringToDouble(FileReadString(h));
      g.wins       = (int)StringToInteger(FileReadString(h));
      g.losses     = (int)StringToInteger(FileReadString(h));
      g.net        = StringToDouble(FileReadString(h));
      g.score      = StringToDouble(FileReadString(h));
      g.day_net = 0; g.benched = false;
      g.hEMAf = g.hEMAs = g.hRSI = g.hATR = INVALID_HANDLE;
      if(g.ema_fast <= 0 || g.ema_slow <= 0) break;   // malformed row
      ClampGene(g);
      gGenes[gNum] = g; gNum++;
   }
   FileClose(h);
   return (gNum > 0);
}

//+------------------------------------------------------------------+
//| Build indicator handles for one gene                             |
//+------------------------------------------------------------------+
bool InitGeneHandles(Gene &g)
{
   g.hEMAf = iMA(gSymbol, PERIOD_M1, g.ema_fast, 0, MODE_EMA, PRICE_CLOSE);
   g.hEMAs = iMA(gSymbol, PERIOD_M1, g.ema_slow, 0, MODE_EMA, PRICE_CLOSE);
   g.hRSI  = iRSI(gSymbol, PERIOD_M1, g.rsi_period, PRICE_CLOSE);
   g.hATR  = iATR(gSymbol, PERIOD_M1, g.atr_period);
   return (g.hEMAf != INVALID_HANDLE && g.hEMAs != INVALID_HANDLE &&
           g.hRSI != INVALID_HANDLE && g.hATR != INVALID_HANDLE);
}

//+------------------------------------------------------------------+
//| TRADING UTILS                                                    |
//+------------------------------------------------------------------+
double GetValidLot(double lot)
{
   double mn = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP);
   if(st <= 0) st = 0.01;
   int d = (int)MathRound(-MathLog10(st));
   double v = NormalizeDouble(MathFloor(lot/st)*st, d);
   return MathMax(mn, MathMin(mx, MathMax(MinLot, v)));
}

double CalcLot(double sl_dist, double risk_pct)
{
   if(sl_dist <= 0) return MinLot;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_amt = eq * risk_pct / 100.0;
   double tv = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0 || tv <= 0) return MinLot;
   double ticks = sl_dist / ts;
   if(ticks <= 0) return MinLot;
   double lot = MathMin(MaxLot, risk_amt / (ticks * tv));
   return GetValidLot(lot);
}

int CountAllPos()
{
   int c=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
      if(PosInfo.SelectByIndex(i))
      {
         long m = PosInfo.Magic();
         if(PosInfo.Symbol()==gSymbol && m>=MagicBase && m<MagicBase+gNum) c++;
      }
   return c;
}

//+------------------------------------------------------------------+
//| THROTTLE: spread ok + entry-rate ok                              |
//+------------------------------------------------------------------+
double SpreadPts()
{
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID), ask=SymbolInfoDouble(gSymbol,SYMBOL_ASK);
   if(gPoint<=0) return 1e9;
   return (ask-bid)/gPoint;
}

bool ThrottleOK()
{
   if(SpreadPts() > MaxSpreadPoints) return false;
   if(gEntriesThisBar >= MaxEntriesPerBar) return false;
   datetime now = TimeCurrent();
   // min seconds since most recent entry + cap per rolling minute
   int recent=0; datetime newest=0;
   for(int i=0;i<64;i++)
   {
      if(gEntryTimes[i]==0) continue;
      if(now - gEntryTimes[i] <= 60) recent++;
      if(gEntryTimes[i] > newest) newest = gEntryTimes[i];
   }
   if(newest>0 && (now-newest) < MinSecondsBetween) return false;
   if(recent >= MaxEntriesPerMinute) return false;
   return true;
}

void MarkEntry()
{
   gEntryTimes[gEntryIdx % 64] = TimeCurrent();
   gEntryIdx++;
   gEntriesThisBar++;
}

//+------------------------------------------------------------------+
bool ValidLevels(double price,double sl,double tp,bool buy)
{
   long st=SymbolInfoInteger(gSymbol,SYMBOL_TRADE_STOPS_LEVEL);
   double md=(double)st*gPoint; if(md<50*gPoint) md=50*gPoint;
   int d=gDigits;
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID), ask=SymbolInfoDouble(gSymbol,SYMBOL_ASK);
   if(buy){ if(sl>=price||NormalizeDouble(ask-sl,d)<=md) return false;
            if(tp<=price||NormalizeDouble(tp-ask,d)<=md) return false; }
   else   { if(sl<=price||NormalizeDouble(sl-bid,d)<=md) return false;
            if(tp>=price||NormalizeDouble(bid-tp,d)<=md) return false; }
   return true;
}

//+------------------------------------------------------------------+
//| OPEN with a specific gene (tags magic = base+gene.id)            |
//+------------------------------------------------------------------+
void OpenTrade(Gene &g, bool buy, double atr, string reason)
{
   if(CountAllPos() >= MaxPositions) return;
   if(!ThrottleOK()) return;
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID), ask=SymbolInfoDouble(gSymbol,SYMBOL_ASK);
   double px = buy ? ask : bid;
   if(px<=0) return;
   double sl_dist=atr*g.sl_mult; if(sl_dist<80*gPoint) sl_dist=80*gPoint;
   double tp_dist=atr*g.tp_mult; if(tp_dist<120*gPoint) tp_dist=120*gPoint;
   int d=gDigits;
   double sl = buy ? NormalizeDouble(px-sl_dist,d) : NormalizeDouble(px+sl_dist,d);
   double tp = buy ? NormalizeDouble(px+tp_dist,d) : NormalizeDouble(px-tp_dist,d);
   if(!ValidLevels(px,sl,tp,buy)) return;
   double lot=CalcLot(sl_dist, g.risk_pct);
   if(lot<MinLot) return;
   Trade.SetExpertMagicNumber(MagicBase + g.id);
   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);
   bool ok = buy ? Trade.Buy(lot,gSymbol,px,sl,tp,"QSv83 G"+IntegerToString(g.id)+" "+reason)
                 : Trade.Sell(lot,gSymbol,px,sl,tp,"QSv83 G"+IntegerToString(g.id)+" "+reason);
   if(ok){ MarkEntry();
      Log((buy?"✅BUY ":"✅SELL ")+"G"+IntegerToString(g.id)+" "+reason+
          " lot="+DoubleToString(lot,2)+" spr="+DoubleToString(SpreadPts(),0)); }
}

//+------------------------------------------------------------------+
//| MANAGE all positions (BE + trail, using the owning gene's DNA)   |
//+------------------------------------------------------------------+
void ManagePositions()
{
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID), ask=SymbolInfoDouble(gSymbol,SYMBOL_ASK);
   if(bid<=0||ask<=0) return;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      if(!PosInfo.SelectByIndex(i)) continue;
      long m=PosInfo.Magic();
      if(PosInfo.Symbol()!=gSymbol || m<MagicBase || m>=MagicBase+gNum) continue;
      int gi = (int)(m - MagicBase);
      if(gi<0 || gi>=gNum) continue;
      Gene g = gGenes[gi];
      double ab[1];
      if(CopyBuffer(g.hATR,0,0,1,ab)<=0) continue;
      double atr=ab[0]; if(atr<=0) continue;
      double op=PosInfo.PriceOpen(), csl=PosInfo.StopLoss(), ctp=PosInfo.TakeProfit();
      int d=gDigits; double mind=50*gPoint;
      if(PosInfo.PositionType()==POSITION_TYPE_BUY)
      {
         double pp=(bid-op)/gPoint;
         if(pp >= g.be_atr*atr/gPoint && csl<op)
         { double nsl=NormalizeDouble(op+20*gPoint,d);
           if(nsl<bid-mind && nsl>csl) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp); }
         if(pp>0)
         { double nsl=NormalizeDouble(bid-g.trail_atr*atr,d), step=g.trail_step*atr;
           if(nsl>op && nsl>csl+step && nsl<bid-mind) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp); }
      }
      else
      {
         double pp=(op-ask)/gPoint;
         if(pp >= g.be_atr*atr/gPoint && (csl>op||csl==0))
         { double nsl=NormalizeDouble(op-20*gPoint,d);
           if(nsl>ask+mind && (csl==0||nsl<csl)) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp); }
         if(pp>0)
         { double nsl=NormalizeDouble(ask+g.trail_atr*atr,d), step=g.trail_step*atr;
           if(nsl<op && (csl==0||nsl<csl-step) && nsl>ask+mind) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp); }
      }
   }
}

//+------------------------------------------------------------------+
//| Per-gene learning: evolve a gene from its own outcome            |
//+------------------------------------------------------------------+
void EvolveGene(Gene &g, double profit)
{
   if(profit > 0)
   {
      g.tp_mult += 0.10; g.sl_mult -= 0.05; g.entry_threshold -= 0.03;
   }
   else
   {
      g.sl_mult += 0.10; g.risk_pct -= 0.10; g.entry_threshold += 0.05;
   }
   ClampGene(g);
   RecomputeScore(g);
}

//+------------------------------------------------------------------+
//| Find which setup opened a position (reads the entry deal comment) |
//+------------------------------------------------------------------+
string EntryReasonOf(long posid)
{
   int total=HistoryDealsTotal();
   for(int j=0;j<total;j++)
   {
      ulong jt=HistoryDealGetTicket(j);
      if(jt==0) continue;
      if(HistoryDealGetInteger(jt,DEAL_POSITION_ID)!=posid) continue;
      if(HistoryDealGetInteger(jt,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
      string cm=HistoryDealGetString(jt,DEAL_COMMENT);
      string keys[5]={"REJECT","COUNTER","CROSS","BREAK","PULL"};
      for(int k=0;k<5;k++) if(StringFind(cm,keys[k])>=0) return keys[k];
      return "";
   }
   return "";
}

//+------------------------------------------------------------------+
//| Reinforce the specific signal-weight that opened the trade       |
//| (this is HOW the gene "saves the lesson" — e.g. learns to trust  |
//|  rejection wicks more when they win, less when they lose)        |
//+------------------------------------------------------------------+
void BumpWeight(Gene &g, string reason, bool win)
{
   double d = win ? 0.05 : -0.05;
   if(reason=="REJECT")       g.w_reject  += d;
   else if(reason=="CROSS")   g.w_cross   += d;
   else if(reason=="BREAK")   g.w_break   += d;
   else if(reason=="COUNTER") g.w_counter += d;
   else if(reason=="PULL")    g.w_pull    += d;
   ClampGene(g);
}

//+------------------------------------------------------------------+
//| ONTRADE — attribute closed deals to their gene, learn, persist   |
//+------------------------------------------------------------------+
datetime gLastDealTime = 0;
void OnTrade()
{
   HistorySelect(TimeCurrent()-7*24*3600, TimeCurrent());
   int total=HistoryDealsTotal();
   bool changed=false;
   for(int i=total-1;i>=MathMax(0,total-10);i--)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(tk==0) continue;
      long m=HistoryDealGetInteger(tk,DEAL_MAGIC);
      if(m<MagicBase || m>=MagicBase+gNum) continue;
      if(HistoryDealGetString(tk,DEAL_SYMBOL)!=gSymbol) continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY)!=DEAL_ENTRY_OUT) continue;
      datetime dt=(datetime)HistoryDealGetInteger(tk,DEAL_TIME);
      if(dt <= gLastDealTime) continue;
      gLastDealTime = dt;
      int gi=(int)(m-MagicBase); if(gi<0||gi>=gNum) continue;
      double profit=HistoryDealGetDouble(tk,DEAL_PROFIT)
                   +HistoryDealGetDouble(tk,DEAL_SWAP)
                   +HistoryDealGetDouble(tk,DEAL_COMMISSION);
      if(profit>0) gGenes[gi].wins++; else gGenes[gi].losses++;
      gGenes[gi].net += profit;
      gGenes[gi].day_net += profit;
      if(MaxGeneDailyLoss>0 && gGenes[gi].day_net <= -MaxGeneDailyLoss && !gGenes[gi].benched)
      {
         gGenes[gi].benched = true;
         Log("⛔ G"+IntegerToString(gi)+" BENCHED for today — daily loss $"+
             DoubleToString(gGenes[gi].day_net,2)+" hit cap $"+DoubleToString(MaxGeneDailyLoss,2));
      }
      long posid=HistoryDealGetInteger(tk,DEAL_POSITION_ID);
      string reason=EntryReasonOf(posid);
      BumpWeight(gGenes[gi], reason, profit>0);   // learn which SIGNAL worked
      EvolveGene(gGenes[gi], profit);
      changed=true;
      Log("📊 G"+IntegerToString(gi)+" "+reason+" closed P/L=$"+DoubleToString(profit,2)+
          " | W:"+IntegerToString(gGenes[gi].wins)+" L:"+IntegerToString(gGenes[gi].losses)+
          " net=$"+DoubleToString(gGenes[gi].net,2)+" score="+DoubleToString(gGenes[gi].score,2));
   }
   if(changed) SaveVault();
}

//+------------------------------------------------------------------+
//| Pick the best in-session gene right now (highest score)          |
//+------------------------------------------------------------------+
int PickGene(int hour)
{
   int best=-1; double bs=-1e18;
   for(int i=0;i<gNum;i++)
   {
      Gene g=gGenes[i];
      if(g.benched) continue;                 // gene hit its daily loss cap — sit out today
      bool in_sess = (g.start_hour<=g.end_hour) ? (hour>=g.start_hour && hour<=g.end_hour)
                                                : (hour>=g.start_hour || hour<=g.end_hour);
      if(!in_sess) continue;
      // exploration: unproven genes (n<3) get a small positive bias so they get tried
      int n=g.wins+g.losses;
      double s = g.score + (n<3 ? 1.0 : 0.0);
      if(s>bs){ bs=s; best=i; }
   }
   return best;
}

//+------------------------------------------------------------------+
//| Weighted entry decision for one gene                             |
//+------------------------------------------------------------------+
bool DecideEntry(Gene &g, bool &out_buy, double &out_atr, string &out_reason)
{
   double ef[2], es[2], rb[1], ab[1];
   if(CopyBuffer(g.hEMAf,0,0,2,ef)<=0) return false;
   if(CopyBuffer(g.hEMAs,0,0,2,es)<=0) return false;
   if(CopyBuffer(g.hRSI,0,0,1,rb)<=0) return false;
   if(CopyBuffer(g.hATR,0,0,1,ab)<=0) return false;
   double ema_f=ef[0], ema_fp=ef[1], ema_s=es[0], ema_sp=es[1], rsi=rb[0], atr=ab[0];
   if(atr<=0) return false;
   out_atr=atr;
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID);
   if(bid<=0) return false;

   datetime cb=iTime(gSymbol,PERIOD_M1,0);
   static datetime lb=0; bool nb=(cb!=lb); if(nb) lb=cb;
   double dist=(bid-ema_f)/gPoint;
   bool up=(ema_f>ema_s), down=(ema_f<ema_s);

   bool cross_up=nb&&(ema_fp<=ema_sp && ema_f>ema_s);
   bool cross_dn=nb&&(ema_fp>=ema_sp && ema_f<ema_s);
   bool pull_buy=(dist>=-g.ema_zone && dist<=150);
   bool pull_sell=(dist<=g.ema_zone && dist>=-150);
   bool brk_buy=(bid>ema_f+40*gPoint);
   bool brk_sell=(bid<ema_f-40*gPoint);
   bool cnt_buy=down&&(rsi<35)&&(dist<-200);
   bool cnt_sell=up&&(rsi>65)&&(dist>200);

   // --- rejection wick on the LAST CLOSED M1 candle (the reversal you described) ---
   bool rej_buy=false, rej_sell=false;
   if(UseRejectionWick)
   {
      double o=iOpen(gSymbol,PERIOD_M1,1),  hh=iHigh(gSymbol,PERIOD_M1,1);
      double ll=iLow(gSymbol,PERIOD_M1,1),  cc=iClose(gSymbol,PERIOD_M1,1);
      double range=hh-ll, body=MathAbs(cc-o);
      if(range>0)
      {
         double lower=MathMin(o,cc)-ll;    // long LOWER tail = price dipped then snapped back up
         double upper=hh-MathMax(o,cc);    // long UPPER tail = price spiked then fell back
         rej_buy  = (lower >= body*WickBodyRatio) && (lower >= range*WickRangeFrac) && (cc>=o);
         rej_sell = (upper >= body*WickBodyRatio) && (upper >= range*WickRangeFrac) && (cc<=o);
      }
   }

   // trend-following setups only count WITH the trend...
   double tbuy = up   ? (g.w_cross*(cross_up?1:0)+g.w_pull*(pull_buy?1:0)+g.w_break*(brk_buy?1:0)) : 0;
   double tsell= down ? (g.w_cross*(cross_dn?1:0)+g.w_pull*(pull_sell?1:0)+g.w_break*(brk_sell?1:0)) : 0;
   // ...but REVERSAL setups (counter + rejection wick) fire AGAINST it -> "buy instead of sell"
   double rbuy = g.w_counter*(cnt_buy?1:0) + g.w_reject*(rej_buy?1:0);
   double rsell= g.w_counter*(cnt_sell?1:0)+ g.w_reject*(rej_sell?1:0);
   double buy_s = tbuy + rbuy;
   double sell_s= tsell + rsell;

   if(buy_s>=g.entry_threshold && buy_s>sell_s)
   { out_buy=true;
     out_reason = rej_buy?"REJECT":(cross_up?"CROSS":(brk_buy?"BREAK":(cnt_buy?"COUNTER":"PULL")));
     return true; }
   if(sell_s>=g.entry_threshold && sell_s>buy_s)
   { out_buy=false;
     out_reason = rej_sell?"REJECT":(cross_dn?"CROSS":(brk_sell?"BREAK":(cnt_sell?"COUNTER":"PULL")));
     return true; }
   return false;
}

//+------------------------------------------------------------------+
bool CheckDailyLoss()
{
   if(gHalted) return true;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(gDailyEquity<=0) return false;
   double lp=(gDailyEquity-eq)/gDailyEquity*100.0;
   if(lp>=MaxDailyLossPct)
   {
      if(!gDidCloseToday)
      {
         gDidCloseToday=true;
         for(int i=PositionsTotal()-1;i>=0;i--)
            if(PosInfo.SelectByIndex(i))
            { long m=PosInfo.Magic();
              if(PosInfo.Symbol()==gSymbol && m>=MagicBase && m<MagicBase+gNum)
                 Trade.PositionClose(PosInfo.Ticket()); }
         gHalted=true; gCooldownUntil=TimeCurrent()+CooldownMinutes*60;
         Log("🛑 Daily loss "+DoubleToString(lp,2)+"% — halted");
      }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| GENE MONITOR — live on-chart panel (no separate file)            |
//+------------------------------------------------------------------+
void UpdateMonitor()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   bool night = BlockNight && IsNight(dt.hour);
   string s = "🧬 QuantumShark v8.3 — Gene Monitor\n";
   s += "Equity $"+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)+
        "   Spread "+DoubleToString(SpreadPts(),0)+"pts   Open "+IntegerToString(CountAllPos())+"\n";
   s += "Server hour "+IntegerToString(dt.hour)+(night?"  🌙 NIGHT (entries blocked)":"  ☀ active")+"\n";
   s += "───────────────────────────────────────────\n";
   s += "ID  sess    W/L     net$    day$   score  Wrej  state\n";
   for(int i=0;i<gNum;i++)
   {
      Gene g=gGenes[i];
      bool insess = (g.start_hour<=g.end_hour) ? (dt.hour>=g.start_hour && dt.hour<=g.end_hour)
                                               : (dt.hour>=g.start_hour || dt.hour<=g.end_hour);
      string state = g.benched ? "⛔BENCH" : (insess ? "● LIVE" : "– idle");
      s += StringFormat("G%d  %02d-%02d  %d/%d  %7.1f %7.1f  %5.1f  %.2f  %s\n",
                        g.id, g.start_hour, g.end_hour, g.wins, g.losses,
                        g.net, g.day_net, g.score, g.w_reject, state);
   }
   Comment(s);
}

//+------------------------------------------------------------------+
int OnInit()
{
   gSymbol=Symbol();
   gPoint=SymbolInfoDouble(gSymbol,SYMBOL_POINT);
   gDigits=(int)SymbolInfoInteger(gSymbol,SYMBOL_DIGITS);
   ArrayInitialize(gEntryTimes,0);

   int want=Clampi(NumGenes,1,MAX_GENES);
   bool loaded = (!ForceResetGenes) && LoadVault();
   if(!loaded)
   {
      gNum=want;
      for(int i=0;i<gNum;i++) SeedGene(gGenes[i], i);
      Log("🌱 Seeded "+IntegerToString(gNum)+" fresh genes");
   }
   else Log("📂 Loaded "+IntegerToString(gNum)+" genes from vault");

   for(int i=0;i<gNum;i++)
   {
      if(!InitGeneHandles(gGenes[i]))
      { Log("❌ Gene "+IntegerToString(i)+" indicator init failed"); return INIT_FAILED; }
      RecomputeScore(gGenes[i]);
      Log("🧬 G"+IntegerToString(i)+" emaF="+IntegerToString(gGenes[i].ema_fast)+
          " emaS="+IntegerToString(gGenes[i].ema_slow)+" rsi="+IntegerToString(gGenes[i].rsi_period)+
          " sess="+IntegerToString(gGenes[i].start_hour)+"-"+IntegerToString(gGenes[i].end_hour)+
          " score="+DoubleToString(gGenes[i].score,1));
   }
   gDailyEquity=AccountInfoDouble(ACCOUNT_EQUITY);
   gHalted=false; gDidCloseToday=false; gCooldownUntil=0;
   Log("✅ v8.3 ready. Equity $"+DoubleToString(gDailyEquity,2)+
       " | spread<="+DoubleToString(MaxSpreadPoints,0)+"pts, max "+
       IntegerToString(MaxEntriesPerMinute)+"/min");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   SaveVault();
   for(int i=0;i<gNum;i++)
   {
      if(gGenes[i].hEMAf!=INVALID_HANDLE) IndicatorRelease(gGenes[i].hEMAf);
      if(gGenes[i].hEMAs!=INVALID_HANDLE) IndicatorRelease(gGenes[i].hEMAs);
      if(gGenes[i].hRSI!=INVALID_HANDLE)  IndicatorRelease(gGenes[i].hRSI);
      if(gGenes[i].hATR!=INVALID_HANDLE)  IndicatorRelease(gGenes[i].hATR);
   }
   Comment("");
   Log("🛑 Stopped. Genes saved.");
}

//+------------------------------------------------------------------+
void OnTick()
{
   static int last_day=-1;
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   if(last_day!=dt.day)
   { last_day=dt.day; gDailyEquity=AccountInfoDouble(ACCOUNT_EQUITY);
     gHalted=false; gDidCloseToday=false; gCooldownUntil=0;
     for(int i=0;i<gNum;i++){ gGenes[i].day_net=0; gGenes[i].benched=false; }  // fresh day: un-bench
     Log("🌅 New day. Equity $"+DoubleToString(gDailyEquity,2)+" — all genes un-benched"); }

   // refresh the on-chart gene monitor (throttled to ~2s)
   static datetime lmon=0;
   if(TimeCurrent()-lmon>=2){ lmon=TimeCurrent(); UpdateMonitor(); }

   // reset per-bar entry counter on a new M1 bar
   datetime cb=iTime(gSymbol,PERIOD_M1,0);
   if(cb!=gLastBar){ gLastBar=cb; gEntriesThisBar=0; }

   if(!EnableTrading || gHalted) return;
   if(TimeCurrent()<gCooldownUntil) return;
   if(CheckDailyLoss()) return;

   ManagePositions();                     // always manage/protect open trades

   // 🌙 NIGHT DISCIPLINE — block NEW entries during the proven-losing window
   if(BlockNight && IsNight(dt.hour))
   {
      static datetime lnw=0;
      if(TimeCurrent()-lnw>300){ lnw=TimeCurrent();
         Log("🌙 Night window ("+IntegerToString(NightStartHour)+"-"+IntegerToString(NightEndHour)+
             ") — no new entries (managing open only)"); }
      return;
   }

   int gi=PickGene(dt.hour);
   if(gi<0) return;                       // no gene owns this hour
   bool buy; double atr; string reason;
   if(DecideEntry(gGenes[gi], buy, atr, reason))
      OpenTrade(gGenes[gi], buy, atr, reason);
}
//+------------------------------------------------------------------+
