//+------------------------------------------------------------------+
//|  v7_2_DNA_EVOLVE_TESTER.mq5                                      |
//|  GOLD DNA Evolution EA — Strategy Tester optimised build         |
//|  No indicator handles. Entry: buy even bars / sell odd bars.     |
//|  Keeps full DNA evolution + JSON writing for parameter sweeps.   |
//+------------------------------------------------------------------+
#property copyright "FRIDAY × Claude"
#property version   "7.20"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        g_trade;
CPositionInfo g_pos;

//──────────────────────────────────────────────────────────────────
// INPUTS (only the parameters that matter for optimisation)
//──────────────────────────────────────────────────────────────────
input group "═══ DNA CORE ═══"
input int    InpBasketGap    = 500;    // Gap between grid levels (points)
input double InpBasketTP     = 50.0;  // Basket take-profit ($)
input double InpBasketSL     = 150.0; // Basket stop-loss ($)
input double InpLotBase      = 0.01;  // Base lot
input double InpLotFactor    = 1.5;   // Lot multiplier per level
input int    InpMaxLevels    = 6;     // Max grid levels

input group "═══ DNA EVOLUTION ═══"
input int    InpGenSize      = 30;    // Closed trades per generation
input bool   InpAutoEvolve   = true;  // Auto-mutate DNA each generation
input double InpMutateStep   = 0.08;  // Mutation step (8%)
input bool   InpRollback     = true;  // Rollback if new gen worse

input group "═══ RISK ═══"
input int    InpCooldownBars = 3;     // Bars cooldown after SL hit
input int    InpMagic        = 72001; // Magic (different from live build)

input group "═══ MONITOR ═══"
input bool   InpWriteFiles   = false; // Disable file writes in tester by default

//──────────────────────────────────────────────────────────────────
// DNA STATE
//──────────────────────────────────────────────────────────────────
double g_gap;
double g_tp;
double g_sl;
double g_lot;
double g_factor;

//──────────────────────────────────────────────────────────────────
// GENERATION TRACKING
//──────────────────────────────────────────────────────────────────
int    g_generation    = 1;
int    g_gen_trades    = 0;
double g_gen_start_bal = 0;
double g_best_fitness  = -9999;
double g_prev_gap, g_prev_tp, g_prev_sl, g_prev_lot, g_prev_factor;

// Fitness history (rolling 10)
double g_gen_history[10];
int    g_gen_history_count = 0;

//──────────────────────────────────────────────────────────────────
// PERFORMANCE COUNTERS
//──────────────────────────────────────────────────────────────────
int    g_total_trades  = 0;
int    g_total_wins    = 0;
int    g_total_losses  = 0;
int    g_win_streak    = 0;
int    g_loss_streak   = 0;
int    g_consec_losses = 0;
double g_max_balance   = 0;
double g_min_balance   = 999999;
int    g_cooldown_bars = 0;
int    g_bar_count     = 0;
datetime g_last_bar    = 0;

// Stop-trading protection
bool   g_stop_trading   = false;
int    g_consec_sl_hits = 0;

// Grid state
int    g_direction     = 0;
int    g_levels_open   = 0;

// File names
string FILE_STATUS  = "ea_tester_status.json";
string FILE_DNA     = "ea_tester_dna.json";

//──────────────────────────────────────────────────────────────────
// INIT
//──────────────────────────────────────────────────────────────────
int OnInit()
{
   g_gap    = InpBasketGap;
   g_tp     = InpBasketTP;
   g_sl     = InpBasketSL;
   g_lot    = InpLotBase;
   g_factor = InpLotFactor;

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_gen_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_max_balance   = g_gen_start_bal;
   g_min_balance   = g_gen_start_bal;

   HistorySelect(0, TimeCurrent());

   Print("[TESTER] DNA EVOLVE v7.2 — Tester build | Gap=", g_gap,
         " TP=", g_tp, " SL=", g_sl, " LotFactor=", g_factor);

   return INIT_SUCCEEDED;
}

//──────────────────────────────────────────────────────────────────
// DEINIT
//──────────────────────────────────────────────────────────────────
void OnDeinit(const int reason)
{
   SaveDNAState();

   double wr = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 0;
   Print("[TESTER] Final: Gen=", g_generation,
         " Trades=", g_total_trades,
         " WR=", DoubleToString(wr, 1), "%",
         " BestFitness=", DoubleToString(g_best_fitness, 2),
         " Gap=", DoubleToString(g_gap, 0),
         " TP=", DoubleToString(g_tp, 1),
         " SL=", DoubleToString(g_sl, 1));
}

//──────────────────────────────────────────────────────────────────
// TICK
//──────────────────────────────────────────────────────────────────
void OnTick()
{
   datetime cur_bar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(cur_bar == g_last_bar)
   {
      CheckBasketExit();
      return;
   }
   g_last_bar = cur_bar;
   g_bar_count++;

   if(g_cooldown_bars > 0)
   {
      g_cooldown_bars--;
      return;
   }

   g_levels_open = CountOurPositions();

   if(g_levels_open > 0 && g_levels_open < InpMaxLevels)
      CheckAddLevel(g_direction);

   if(g_levels_open == 0)
      TryNewEntry();

   CheckBasketExit();
   UpdateStats();

   if(InpWriteFiles)
      WriteStatus();
}

//──────────────────────────────────────────────────────────────────
// TRADE EVENT
//──────────────────────────────────────────────────────────────────
void OnTrade()
{
   HistorySelect(0, TimeCurrent());
   static int last_history = 0;
   int cur_history = HistoryDealsTotal();
   if(cur_history <= last_history) return;

   for(int i = last_history; i < cur_history; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      if(profit == 0) continue;

      g_total_trades++;
      g_gen_trades++;

      if(profit > 0)
      {
         g_total_wins++;
         g_win_streak++;
         g_loss_streak   = 0;
         g_consec_losses = 0;
      }
      else
      {
         g_total_losses++;
         g_loss_streak++;
         g_win_streak    = 0;
         g_consec_losses++;
      }

      if(InpAutoEvolve && g_gen_trades >= InpGenSize)
         EvolveGeneration();
   }
   last_history = cur_history;
}

//──────────────────────────────────────────────────────────────────
// ENTRY — buy on even bars, sell on odd bars (tester signal proxy)
//──────────────────────────────────────────────────────────────────
void TryNewEntry()
{
   if(g_stop_trading) return;

   if(g_bar_count % 2 == 0)
   {
      OpenBuy(g_lot, "T_L1_BUY");
      g_direction = 1;
   }
   else
   {
      OpenSell(g_lot, "T_L1_SELL");
      g_direction = -1;
   }
}

//──────────────────────────────────────────────────────────────────
// GRID LEVEL ADD
//──────────────────────────────────────────────────────────────────
void CheckAddLevel(int dir)
{
   if(dir == 0) return;
   double gap_price = g_gap * _Point;

   if(dir == 1)
   {
      double worst = GetWorstBuyPrice();
      double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(worst > 0 && (worst - ask) >= gap_price)
      {
         double next_lot = NormalizeLot(g_lot * MathPow(g_factor, g_levels_open));
         OpenBuy(next_lot, "T_L" + IntegerToString(g_levels_open + 1) + "_BUY");
      }
   }
   else
   {
      double worst = GetWorstSellPrice();
      double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(worst > 0 && (bid - worst) >= gap_price)
      {
         double next_lot = NormalizeLot(g_lot * MathPow(g_factor, g_levels_open));
         OpenSell(next_lot, "T_L" + IntegerToString(g_levels_open + 1) + "_SELL");
      }
   }
}

//──────────────────────────────────────────────────────────────────
// BASKET EXIT
//──────────────────────────────────────────────────────────────────
void CheckBasketExit()
{
   if(CountOurPositions() == 0) return;
   double bp = GetBasketProfit();

   if(bp >= g_tp)
   {
      CloseAll("TP");
      g_consec_sl_hits = 0;
      return;
   }

   if(bp <= -g_sl)
   {
      CloseAll("SL");
      g_cooldown_bars = InpCooldownBars;
      g_consec_losses++;
      g_consec_sl_hits++;
      if(g_consec_sl_hits >= 3)
         g_stop_trading = true;
   }
}

//──────────────────────────────────────────────────────────────────
// DNA EVOLUTION
//──────────────────────────────────────────────────────────────────
void EvolveGeneration()
{
   double cur_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double gen_return  = cur_balance - g_gen_start_bal;
   double fitness     = ComputeFitness(gen_return);

   if(g_gen_history_count < 10)
   {
      g_gen_history[g_gen_history_count] = fitness;
      g_gen_history_count++;
   }
   else
   {
      for(int _i = 0; _i < 9; _i++) g_gen_history[_i] = g_gen_history[_i + 1];
      g_gen_history[9] = fitness;
   }

   Print("[TESTER] GEN ", g_generation, " fitness=", DoubleToString(fitness, 2),
         " return=$", DoubleToString(gen_return, 2),
         " trades=", g_gen_trades);

   if(fitness > g_best_fitness)
   {
      g_best_fitness = fitness;
      SaveBestDNA();
   }
   else if(InpRollback && fitness < g_best_fitness * 0.8)
   {
      LoadBestDNA();
   }
   else
   {
      MutateDNA(fitness);
   }

   g_generation++;
   g_gen_trades     = 0;
   g_gen_start_bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   g_stop_trading   = false;
   g_consec_sl_hits = 0;

   SaveDNAState();
}

//──────────────────────────────────────────────────────────────────
// MUTATE DNA
//──────────────────────────────────────────────────────────────────
void MutateDNA(double fitness)
{
   double m         = InpMutateStep;
   g_prev_gap    = g_gap;
   g_prev_tp     = g_tp;
   g_prev_sl     = g_sl;
   g_prev_lot    = g_lot;
   g_prev_factor = g_factor;

   double rand_sign = (MathRand() % 2 == 0) ? 1.0 : -1.0;

   if(g_consec_losses >= 3)
   {
      g_gap  *= (1.0 + m);
      g_lot  *= (1.0 - m * 0.5);
      g_sl   *= (1.0 + m * 0.5);
   }
   else if(g_win_streak >= 5)
   {
      g_tp   *= (1.0 - m * 0.3);
      g_lot  *= (1.0 + m * 0.3);
   }
   else
   {
      g_gap  *= (1.0 + rand_sign * m * 0.5);
      g_tp   *= (1.0 + rand_sign * m * 0.3);
      g_sl   *= (1.0 + rand_sign * m * 0.2);
   }

   g_gap    = MathMax(300, MathMin(3000, g_gap));
   g_tp     = MathMax(10,  MathMin(500,  g_tp));
   g_sl     = MathMax(50,  MathMin(1000, g_sl));
   g_lot    = MathMax(0.01,MathMin(1.0,  g_lot));
   g_factor = MathMax(1.1, MathMin(3.0,  g_factor));
}

double ComputeFitness(double gen_return)
{
   double wr  = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 50.0;
   double dd  = (g_max_balance > 0)  ? ((g_max_balance - g_min_balance) / g_max_balance * 100.0) : 0;
   return gen_return + (wr - 50) * 0.5 - dd * 0.3;
}

//──────────────────────────────────────────────────────────────────
// HELPERS
//──────────────────────────────────────────────────────────────────
bool OpenBuy(double lot, string comment)
{
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool ok = g_trade.Buy(lot, _Symbol, price, 0, 0, comment);
   if(!ok) Print("[TESTER] BUY FAIL: ", g_trade.ResultRetcodeDescription());
   return ok;
}

bool OpenSell(double lot, string comment)
{
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool ok = g_trade.Sell(lot, _Symbol, price, 0, 0, comment);
   if(!ok) Print("[TESTER] SELL FAIL: ", g_trade.ResultRetcodeDescription());
   return ok;
}

void CloseAll(string reason)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            g_trade.PositionClose(g_pos.Ticket());
   }
   g_direction   = 0;
   g_levels_open = 0;
}

int CountOurPositions()
{
   int n = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            n++;
   return n;
}

double GetBasketProfit()
{
   double p = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            p += g_pos.Profit() + g_pos.Swap() + g_pos.Commission();
   return p;
}

double GetWorstBuyPrice()
{
   double w = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol
            && g_pos.PositionType() == POSITION_TYPE_BUY)
            if(w == 0 || g_pos.PriceOpen() < w) w = g_pos.PriceOpen();
   return w;
}

double GetWorstSellPrice()
{
   double w = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol
            && g_pos.PositionType() == POSITION_TYPE_SELL)
            if(w == 0 || g_pos.PriceOpen() > w) w = g_pos.PriceOpen();
   return w;
}

double NormalizeLot(double lot)
{
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathRound(lot / lot_step) * lot_step;
   return MathMax(min_lot, MathMin(max_lot, lot));
}

void UpdateStats()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance > g_max_balance) g_max_balance = balance;
   if(balance < g_min_balance) g_min_balance = balance;
}

//──────────────────────────────────────────────────────────────────
// JSON STATUS WRITE (optional, off by default in tester)
//──────────────────────────────────────────────────────────────────
void WriteStatus()
{
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   double wr_pct    = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 0.0;

   string json = "{";
   json += "\"bar\":"         + IntegerToString(g_bar_count)          + ",";
   json += "\"balance\":"     + DoubleToString(balance, 2)            + ",";
   json += "\"equity\":"      + DoubleToString(equity, 2)             + ",";
   json += "\"generation\":"  + IntegerToString(g_generation)         + ",";
   json += "\"gen_trades\":"  + IntegerToString(g_gen_trades)         + ",";
   json += "\"total_trades\":" + IntegerToString(g_total_trades)      + ",";
   json += "\"win_rate\":"    + DoubleToString(wr_pct, 1)             + ",";
   json += "\"best_fitness\":" + DoubleToString(g_best_fitness, 2)    + ",";
   json += "\"dna_gap\":"     + DoubleToString(g_gap, 0)              + ",";
   json += "\"dna_tp\":"      + DoubleToString(g_tp, 2)               + ",";
   json += "\"dna_sl\":"      + DoubleToString(g_sl, 2)               + ",";
   json += "\"stop_trading\":" + (g_stop_trading ? "true" : "false")  + ",";
   json += "\"gen_history\":[";
   int hc = MathMin(g_gen_history_count, 10);
   for(int _h = 0; _h < hc; _h++)
   {
      if(_h > 0) json += ",";
      json += DoubleToString(g_gen_history[_h], 2);
   }
   json += "],";
   json += "\"version\":\"7.2T\"";
   json += "}";

   int fh = FileOpen(FILE_STATUS, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, json); FileClose(fh); }

   Print("[TESTER] Gen=", g_generation,
         " Trades=", g_total_trades,
         " WR=", DoubleToString(wr_pct, 1), "%",
         " Fitness=", DoubleToString(g_best_fitness, 2),
         " Gap=", DoubleToString(g_gap, 0),
         " TP=", DoubleToString(g_tp, 1),
         " SL=", DoubleToString(g_sl, 1));
}

//──────────────────────────────────────────────────────────────────
// DNA PERSISTENCE
//──────────────────────────────────────────────────────────────────
double ExtractDouble(string json, string key)
{
   int pos = StringFind(json, key);
   if(pos < 0) return -1;
   pos += StringLen(key) + 1;
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == ':'))
      pos++;
   string num = "";
   while(pos < StringLen(json))
   {
      ushort c = StringGetCharacter(json, pos);
      if((c >= '0' && c <= '9') || c == '.' || c == '-')
         num += ShortToString(c);
      else if(StringLen(num) > 0)
         break;
      pos++;
   }
   if(StringLen(num) == 0) return -1;
   return StringToDouble(num);
}

void SaveDNAState()
{
   string json = "{";
   json += "\"generation\":"   + IntegerToString(g_generation)      + ",";
   json += "\"best_fitness\":" + DoubleToString(g_best_fitness, 4)  + ",";
   json += "\"gap\":"          + DoubleToString(g_gap, 2)           + ",";
   json += "\"tp\":"           + DoubleToString(g_tp, 2)            + ",";
   json += "\"sl\":"           + DoubleToString(g_sl, 2)            + ",";
   json += "\"lot\":"          + DoubleToString(g_lot, 4)           + ",";
   json += "\"factor\":"       + DoubleToString(g_factor, 4)        + ",";
   json += "\"total_trades\":" + IntegerToString(g_total_trades)    + ",";
   json += "\"total_wins\":"   + IntegerToString(g_total_wins)      + ",";
   json += "\"total_losses\":" + IntegerToString(g_total_losses)    + "}";

   int fh = FileOpen(FILE_DNA, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, json); FileClose(fh); }
}

void SaveBestDNA()
{
   string json = "{";
   json += "\"gap\":"    + DoubleToString(g_gap, 2)    + ",";
   json += "\"tp\":"     + DoubleToString(g_tp, 2)     + ",";
   json += "\"sl\":"     + DoubleToString(g_sl, 2)     + ",";
   json += "\"lot\":"    + DoubleToString(g_lot, 4)    + ",";
   json += "\"factor\":" + DoubleToString(g_factor, 4) + "}";

   int fh = FileOpen("ea_tester_best_dna.json", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, json); FileClose(fh); }
}

void LoadBestDNA()
{
   if(!FileIsExist("ea_tester_best_dna.json", FILE_COMMON)) return;
   int fh = FileOpen("ea_tester_best_dna.json", FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh == INVALID_HANDLE) return;
   string json = "";
   while(!FileIsEnding(fh)) json += FileReadString(fh);
   FileClose(fh);
   double v;
   v = ExtractDouble(json, "\"gap\"");    if(v > 0) g_gap    = v;
   v = ExtractDouble(json, "\"tp\"");     if(v > 0) g_tp     = v;
   v = ExtractDouble(json, "\"sl\"");     if(v > 0) g_sl     = v;
   v = ExtractDouble(json, "\"lot\"");    if(v > 0) g_lot    = v;
   v = ExtractDouble(json, "\"factor\""); if(v > 0) g_factor = v;
}
//+------------------------------------------------------------------+
