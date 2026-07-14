//+------------------------------------------------------------------+
//|  v7_2_DNA_EVOLVE.mq5                                             |
//|  GOLD Stop-Reverse DNA Evolution EA — v7.2                       |
//|  كل جيل يتعلم من السابق — Claude يراقب ويقترح                  |
//+------------------------------------------------------------------+
#property copyright "FRIDAY × Claude"
#property version   "7.20"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade  g_trade;
CPositionInfo g_pos;

//──────────────────────────────────────────────────────────────────
// INPUT GROUPS
//──────────────────────────────────────────────────────────────────
input group "═══ DNA CORE ═══"
input int    InpBasketGap    = 500;    // Gap between grid levels (points)
input double InpBasketTP     = 50.0;  // Basket take-profit ($)
input double InpBasketSL     = 150.0; // Basket stop-loss / max drawdown ($)
input double InpLotBase      = 0.01;  // Base lot
input double InpLotFactor    = 1.5;   // Lot multiplier per level
input int    InpMaxLevels    = 6;     // Max grid levels

input group "═══ DNA EVOLUTION ═══"
input int    InpGenSize      = 30;    // Closed trades per generation
input bool   InpAutoEvolve   = true;  // Auto-mutate DNA each generation
input double InpMutateStep   = 0.08;  // Mutation step (8%)
input bool   InpRollback     = true;  // Rollback if new gen worse

input group "═══ ENTRY FILTERS ═══"
input bool   InpUseRSI       = true;  // Enable RSI filter
input int    InpRSIPeriod    = 14;    // RSI period
input int    InpRSIOB        = 70;    // RSI overbought
input int    InpRSIOS        = 30;    // RSI oversold
input bool   InpUseTrend     = true;  // Enable EMA trend filter
input int    InpEMAPeriod    = 200;   // EMA trend period
input bool   InpUseSession   = true;  // Session filter
input int    InpSessionStart = 8;     // Session open (UTC hour)
input int    InpSessionEnd   = 20;    // Session close (UTC hour)

input group "═══ RISK ═══"
input int    InpCooldownBars = 3;     // Bars cooldown after SL hit
input int    InpMagic        = 72000; // Magic number

input group "═══ MONITOR ═══"
input bool   InpWriteFiles   = true;  // Write ea_realtime_status.json
input bool   InpReadCmds     = true;  // Read Claude command file

//──────────────────────────────────────────────────────────────────
// DNA STATE — live parameters (Claude can override these)
//──────────────────────────────────────────────────────────────────
double g_gap;
double g_tp;
double g_sl;
double g_lot;
double g_factor;
int    g_rsi_ob;
int    g_rsi_os;

//──────────────────────────────────────────────────────────────────
// GENERATION TRACKING
//──────────────────────────────────────────────────────────────────
int    g_generation    = 1;
int    g_gen_trades    = 0;
double g_gen_start_bal = 0;
double g_gen_profit    = 0;
double g_best_fitness  = -9999;
double g_prev_gap, g_prev_tp, g_prev_sl, g_prev_lot, g_prev_factor;

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
double g_last_balance  = 0;

// Stop-trading protection — 3 consecutive basket SL hits
bool   g_stop_trading   = false;
int    g_consec_sl_hits = 0;

// Generation fitness history (rolling last 10)
double g_gen_history[10];
int    g_gen_history_count = 0;

// Direction tracking
int    g_direction     = 0; // 1=BUY -1=SELL 0=none
int    g_levels_open   = 0;

//──────────────────────────────────────────────────────────────────
// INDICATOR HANDLES
//──────────────────────────────────────────────────────────────────
int g_rsi_handle  = INVALID_HANDLE;
int g_ema_handle  = INVALID_HANDLE;

//──────────────────────────────────────────────────────────────────
// FILE PATHS (MT5 Common Files)
//──────────────────────────────────────────────────────────────────
string FILE_STATUS  = "ea_realtime_status.json";
string FILE_HISTORY = "ea_bar_history.json";
string FILE_CMD     = "ea_claude_command.json";
string FILE_DNA     = "ea_dna_state.json";

//──────────────────────────────────────────────────────────────────
// INIT
//──────────────────────────────────────────────────────────────────
int OnInit()
{
   // Load DNA from inputs
   g_gap    = InpBasketGap;
   g_tp     = InpBasketTP;
   g_sl     = InpBasketSL;
   g_lot    = InpLotBase;
   g_factor = InpLotFactor;
   g_rsi_ob = InpRSIOB;
   g_rsi_os = InpRSIOS;

   // Create indicator handles
   if(InpUseRSI)
   {
      g_rsi_handle = iRSI(_Symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);
      if(g_rsi_handle == INVALID_HANDLE)
      {
         Print("[DNA v7.2] RSI handle failed: ", GetLastError());
         return INIT_FAILED;
      }
   }
   if(InpUseTrend)
   {
      g_ema_handle = iMA(_Symbol, PERIOD_CURRENT, InpEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(g_ema_handle == INVALID_HANDLE)
      {
         Print("[DNA v7.2] EMA handle failed: ", GetLastError());
         return INIT_FAILED;
      }
   }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_gen_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_last_balance  = g_gen_start_bal;
   g_max_balance   = g_gen_start_bal;
   g_min_balance   = g_gen_start_bal;

   // Load saved DNA state if exists
   LoadDNAState();

   // Timer fires every second for intra-bar basket monitoring
   EventSetTimer(1);

   // Pre-load deal history so OnTrade sees existing deals
   HistorySelect(0, TimeCurrent());

   // Initial status write
   if(InpWriteFiles)
      WriteStatus();

   Print("╔═══════════════════════════════════════╗");
   Print("║  DNA EVOLVE v7.2 — GOLD Stop-Reverse  ║");
   Print("╠═══════════════════════════════════════╣");
   Print("║  Gap: ", g_gap, "  TP: $", g_tp, "  SL: $", g_sl);
   Print("║  Lot: ", g_lot, "  Factor: ", g_factor);
   Print("║  Generation: ", g_generation);
   Print("╚═══════════════════════════════════════╝");

   return INIT_SUCCEEDED;
}

//──────────────────────────────────────────────────────────────────
// DEINIT
//──────────────────────────────────────────────────────────────────
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_rsi_handle != INVALID_HANDLE)  IndicatorRelease(g_rsi_handle);
   if(g_ema_handle != INVALID_HANDLE)  IndicatorRelease(g_ema_handle);
   SaveDNAState();
   Print("[DNA v7.2] Deinitialized. Generation: ", g_generation, " | Best fitness: ", g_best_fitness);
}

//──────────────────────────────────────────────────────────────────
// TICK
//──────────────────────────────────────────────────────────────────
void OnTick()
{
   // Only process on new bar
   datetime cur_bar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(cur_bar == g_last_bar)
   {
      // Still check basket TP/SL intra-bar
      CheckBasketExit();
      return;
   }
   g_last_bar = cur_bar;
   g_bar_count++;

   // Cooldown management
   if(g_cooldown_bars > 0)
   {
      g_cooldown_bars--;
      UpdateStats();
      if(InpWriteFiles) WriteStatus();
      return;
   }

   // Read Claude commands
   if(InpReadCmds)
      ReadClaudeCommand();

   // Count and manage grid
   g_levels_open = CountOurPositions();
   int dir       = GetCurrentDirection();

   // Check if we should add to grid
   if(g_levels_open > 0 && g_levels_open < InpMaxLevels)
      CheckAddLevel(dir);

   // New entry if flat
   if(g_levels_open == 0)
      TryNewEntry();

   // Check basket exit conditions
   CheckBasketExit();

   // Update stats + write files
   UpdateStats();
   if(InpWriteFiles)
      WriteStatus();

   // Draw dashboard comment
   UpdateComment();
}

//──────────────────────────────────────────────────────────────────
// TRADE EVENT — track wins/losses for DNA evolution
//──────────────────────────────────────────────────────────────────
void OnTrade()
{
   // Must call HistorySelect before HistoryDealsTotal/HistoryDealGetTicket
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
         g_loss_streak    = 0;
         g_consec_losses  = 0;
      }
      else
      {
         g_total_losses++;
         g_loss_streak++;
         g_win_streak     = 0;
         g_consec_losses++;
      }

      // Check if generation complete
      if(InpAutoEvolve && g_gen_trades >= InpGenSize)
         EvolveGeneration();
   }

   last_history = cur_history;
}

//──────────────────────────────────────────────────────────────────
// TIMER — check basket P&L every second (not just on new bar)
//──────────────────────────────────────────────────────────────────
void OnTimer()
{
   if(CountOurPositions() > 0)
   {
      CheckBasketExit();
      UpdateStats();
   }
}

//──────────────────────────────────────────────────────────────────
// NEW ENTRY LOGIC
//──────────────────────────────────────────────────────────────────
void TryNewEntry()
{
   if(g_stop_trading)
   {
      static datetime last_warn = 0;
      if(TimeCurrent() - last_warn > 60)
      {
         Print("[DNA v7.2] STOP-TRADING active (", g_consec_sl_hits, " consec SL hits) — waiting for next generation");
         last_warn = TimeCurrent();
      }
      return;
   }
   if(!IsSessionOpen()) return;

   double rsi_val = GetRSI();
   double ema_val = GetEMA();
   double bid     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask     = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   bool buy_signal  = true;
   bool sell_signal = true;

   // RSI filter
   if(InpUseRSI && rsi_val > 0)
   {
      buy_signal  = buy_signal  && (rsi_val < g_rsi_ob);
      sell_signal = sell_signal && (rsi_val > g_rsi_os);
   }

   // EMA trend filter
   if(InpUseTrend && ema_val > 0)
   {
      buy_signal  = buy_signal  && (ask > ema_val);
      sell_signal = sell_signal && (bid < ema_val);
   }

   // Enter on whichever signal fires, priority to RSI extremes
   if(buy_signal && rsi_val > 0 && rsi_val < 45)
   {
      OpenBuy(g_lot, "DNA_L1_BUY");
      g_direction = 1;
   }
   else if(sell_signal && rsi_val > 0 && rsi_val > 55)
   {
      OpenSell(g_lot, "DNA_L1_SELL");
      g_direction = -1;
   }
   else if(buy_signal && !sell_signal)
   {
      OpenBuy(g_lot, "DNA_L1_BUY");
      g_direction = 1;
   }
   else if(sell_signal && !buy_signal)
   {
      OpenSell(g_lot, "DNA_L1_SELL");
      g_direction = -1;
   }
}

//──────────────────────────────────────────────────────────────────
// ADD GRID LEVEL — when price moves against us
//──────────────────────────────────────────────────────────────────
void CheckAddLevel(int dir)
{
   if(dir == 0) return;

   double first_price  = GetFirstLevelPrice(dir);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double gap_price = g_gap * _Point;

   if(dir == 1) // BUY grid: add when price drops by gap
   {
      double worst_buy = GetWorstBuyPrice();
      if(worst_buy > 0 && (worst_buy - ask) >= gap_price)
      {
         double next_lot = g_lot * MathPow(g_factor, g_levels_open);
         next_lot = NormalizeLot(next_lot);
         OpenBuy(next_lot, "DNA_L" + IntegerToString(g_levels_open + 1) + "_BUY");
      }
   }
   else // SELL grid: add when price rises by gap
   {
      double worst_sell = GetWorstSellPrice();
      if(worst_sell > 0 && (bid - worst_sell) >= gap_price)
      {
         double next_lot = g_lot * MathPow(g_factor, g_levels_open);
         next_lot = NormalizeLot(next_lot);
         OpenSell(next_lot, "DNA_L" + IntegerToString(g_levels_open + 1) + "_SELL");
      }
   }
}

//──────────────────────────────────────────────────────────────────
// BASKET EXIT — TP or SL on total basket profit
//──────────────────────────────────────────────────────────────────
void CheckBasketExit()
{
   if(CountOurPositions() == 0) return;

   double basket_profit = GetBasketProfit();
   double balance       = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity        = AccountInfoDouble(ACCOUNT_EQUITY);
   double open_pnl      = equity - balance;

   // TP hit — close all, reverse
   if(basket_profit >= g_tp)
   {
      CloseAll("BASKET_TP");
      g_consec_sl_hits = 0; // TP resets SL hit streak
      Print("[DNA v7.2] BASKET TP HIT: +$", DoubleToString(basket_profit, 2),
            " | Gen: ", g_generation, " | Bar: ", g_bar_count);
      return; // let new bar handle re-entry
   }

   // SL hit — close all, cooldown, then reverse
   if(basket_profit <= -g_sl)
   {
      CloseAll("BASKET_SL");
      g_cooldown_bars = InpCooldownBars;
      g_consec_losses++;
      g_consec_sl_hits++;

      Print("[DNA v7.2] BASKET SL HIT #", g_consec_sl_hits, ": -$",
            DoubleToString(MathAbs(basket_profit), 2),
            " | Cooldown: ", InpCooldownBars, " bars");

      if(g_consec_sl_hits >= 3)
      {
         g_stop_trading = true;
         Print("[DNA v7.2] *** STOP-TRADING TRIGGERED *** 3 consecutive SL hits — no new entries until next generation");
      }
   }
}

//──────────────────────────────────────────────────────────────────
// DNA EVOLUTION — called each generation end
//──────────────────────────────────────────────────────────────────
void EvolveGeneration()
{
   double cur_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double gen_return  = cur_balance - g_gen_start_bal;
   double fitness     = ComputeFitness(gen_return);

   // Store fitness in rolling history
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

   Print("┌────────────────────────────────────────");
   Print("│ GEN ", g_generation, " COMPLETE → Fitness: ", DoubleToString(fitness, 2));
   Print("│ Return: $", DoubleToString(gen_return, 2),
         " | Trades: ", g_gen_trades,
         " | WR: ", (g_gen_trades > 0 ? DoubleToString(g_total_wins * 100.0 / g_total_trades, 1) : "0"), "%");

   if(fitness > g_best_fitness)
   {
      g_best_fitness = fitness;
      Print("│ ★ NEW BEST — saving DNA");
      SaveBestDNA();
   }
   else if(InpRollback && fitness < g_best_fitness * 0.8)
   {
      Print("│ ↩ ROLLBACK — fitness dropped, restoring best DNA");
      LoadBestDNA();
   }
   else
   {
      // Mutate parameters
      MutateDNA(fitness);
   }

   // Next generation — reset per-gen state
   g_generation++;
   g_gen_trades    = 0;
   g_gen_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_gen_profit    = 0;
   g_stop_trading  = false;
   g_consec_sl_hits = 0;

   Print("│ Next Gen DNA: Gap=", g_gap, " TP=", g_tp, " SL=", g_sl, " Lot=", g_lot);
   Print("└────────────────────────────────────────");

   SaveDNAState();
}

//──────────────────────────────────────────────────────────────────
// MUTATE DNA — intelligent parameter evolution
//──────────────────────────────────────────────────────────────────
void MutateDNA(double fitness)
{
   double m = InpMutateStep;

   // Save previous
   g_prev_gap    = g_gap;
   g_prev_tp     = g_tp;
   g_prev_sl     = g_sl;
   g_prev_lot    = g_lot;
   g_prev_factor = g_factor;

   double rand_sign = (MathRand() % 2 == 0) ? 1.0 : -1.0;

   // Smart mutations based on performance
   if(g_consec_losses >= 3)
   {
      // Too many losses — widen gap, reduce lot
      g_gap    *= (1.0 + m);
      g_lot    *= (1.0 - m * 0.5);
      g_sl     *= (1.0 + m * 0.5);
      Print("[DNA] Consecutive losses → widening gap, reducing lot");
   }
   else if(g_win_streak >= 5)
   {
      // Winning — slightly tighten TP, increase lot
      g_tp     *= (1.0 - m * 0.3);
      g_lot    *= (1.0 + m * 0.3);
      Print("[DNA] Win streak → tightening TP, increasing lot");
   }
   else
   {
      // Random walk mutation
      g_gap    *= (1.0 + rand_sign * m * 0.5);
      g_tp     *= (1.0 + rand_sign * m * 0.3);
      g_sl     *= (1.0 + rand_sign * m * 0.2);
   }

   // Clamp to safe ranges for GOLD
   g_gap    = MathMax(300, MathMin(3000, g_gap));
   g_tp     = MathMax(10,  MathMin(500,  g_tp));
   g_sl     = MathMax(50,  MathMin(1000, g_sl));
   g_lot    = MathMax(0.01,MathMin(1.0,  g_lot));
   g_factor = MathMax(1.1, MathMin(3.0,  g_factor));
}

//──────────────────────────────────────────────────────────────────
// FITNESS FUNCTION
//──────────────────────────────────────────────────────────────────
double ComputeFitness(double gen_return)
{
   double wr  = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 50.0;
   double dd  = (g_max_balance > 0)  ? ((g_max_balance - g_min_balance) / g_max_balance * 100.0) : 0;
   double fitness = gen_return + (wr - 50) * 0.5 - dd * 0.3;
   return fitness;
}

//──────────────────────────────────────────────────────────────────
// READ CLAUDE COMMAND — apply suggestions from ea_monitor.py
//──────────────────────────────────────────────────────────────────
void ReadClaudeCommand()
{
   if(!FileIsExist(FILE_CMD, FILE_COMMON)) return;

   int fh = FileOpen(FILE_CMD, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh == INVALID_HANDLE) return;

   string content = "";
   while(!FileIsEnding(fh))
      content += FileReadString(fh);
   FileClose(fh);

   // Parse key parameters from JSON (simple extraction)
   double new_gap = ExtractDouble(content, "\"BasketGap\"");
   double new_tp  = ExtractDouble(content, "\"BasketTP\"");
   double new_sl  = ExtractDouble(content, "\"BasketSL\"");
   double new_lot = ExtractDouble(content, "\"LotBase\"");

   bool changed = false;

   if(new_gap > 0 && MathAbs(new_gap - g_gap) > 1)
   {
      Print("[Claude→DNA] Gap: ", g_gap, " → ", new_gap);
      g_gap   = MathMax(300, MathMin(3000, new_gap));
      changed = true;
   }
   if(new_tp > 0 && MathAbs(new_tp - g_tp) > 0.1)
   {
      Print("[Claude→DNA] TP: ", g_tp, " → ", new_tp);
      g_tp    = MathMax(10, MathMin(500, new_tp));
      changed = true;
   }
   if(new_sl > 0 && MathAbs(new_sl - g_sl) > 0.1)
   {
      Print("[Claude→DNA] SL: ", g_sl, " → ", new_sl);
      g_sl    = MathMax(50, MathMin(1000, new_sl));
      changed = true;
   }
   if(new_lot > 0 && MathAbs(new_lot - g_lot) > 0.001)
   {
      Print("[Claude→DNA] Lot: ", g_lot, " → ", new_lot);
      g_lot   = MathMax(0.01, MathMin(1.0, new_lot));
      changed = true;
   }

   if(changed)
   {
      Print("[DNA v7.2] Parameters updated by Claude ✓");
      // Delete command file so we don't re-apply
      FileDelete(FILE_CMD, FILE_COMMON);
   }
}

//──────────────────────────────────────────────────────────────────
// WRITE STATUS JSON — for ea_monitor.py dashboard
//──────────────────────────────────────────────────────────────────
void WriteStatus()
{
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double open_pnl = equity - balance;
   int    positions = CountOurPositions();
   double basket_pnl = GetBasketProfit();

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, PERIOD_CURRENT, 0, 2, rates);

   string json = "{";
   json += "\"bar\":"        + IntegerToString(g_bar_count)        + ",";
   json += "\"time\":\""     + TimeToString(TimeCurrent())         + "\",";
   json += "\"symbol\":\""   + _Symbol                            + "\",";
   json += "\"balance\":"    + DoubleToString(balance, 2)         + ",";
   json += "\"equity\":"     + DoubleToString(equity, 2)          + ",";
   json += "\"open_pnl\":"   + DoubleToString(open_pnl, 2)        + ",";
   json += "\"basket_pnl\":" + DoubleToString(basket_pnl, 2)      + ",";
   json += "\"positions\":"  + IntegerToString(positions)         + ",";
   json += "\"direction\":"  + IntegerToString(g_direction)       + ",";
   json += "\"levels\":"     + IntegerToString(g_levels_open)     + ",";
   json += "\"win_streak\":"    + IntegerToString(g_win_streak)   + ",";
   json += "\"loss_streak\":"   + IntegerToString(g_loss_streak)  + ",";
   json += "\"total_trades\":"  + IntegerToString(g_total_trades) + ",";
   json += "\"wins\":"          + IntegerToString(g_total_wins)   + ",";
   json += "\"losses\":"        + IntegerToString(g_total_losses) + ",";
   json += "\"generation\":"    + IntegerToString(g_generation)   + ",";
   json += "\"gen_trades\":"    + IntegerToString(g_gen_trades)   + ",";
   json += "\"best_fitness\":"  + DoubleToString(g_best_fitness, 2) + ",";
   json += "\"dna_gap\":"       + DoubleToString(g_gap, 0)        + ",";
   json += "\"dna_tp\":"        + DoubleToString(g_tp, 2)         + ",";
   json += "\"dna_sl\":"        + DoubleToString(g_sl, 2)         + ",";
   json += "\"lot_factor\":"    + DoubleToString(g_factor, 2)     + ",";
   json += "\"cooldown\":"      + IntegerToString(g_cooldown_bars)+ ",";

   if(copied > 1)
   {
      json += "\"open\":"   + DoubleToString(rates[1].open, _Digits)  + ",";
      json += "\"high\":"   + DoubleToString(rates[1].high, _Digits)  + ",";
      json += "\"low\":"    + DoubleToString(rates[1].low, _Digits)   + ",";
      json += "\"close\":"  + DoubleToString(rates[1].close, _Digits) + ",";
   }

   json += "\"max_balance\":" + DoubleToString(g_max_balance, 2)  + ",";
   json += "\"min_balance\":" + DoubleToString(g_min_balance, 2)  + ",";
   json += "\"stop_trading\":" + (g_stop_trading ? "true" : "false") + ",";
   json += "\"consec_sl_hits\":" + IntegerToString(g_consec_sl_hits) + ",";

   // Generation fitness history array
   json += "\"gen_history\":[";
   int hist_count = MathMin(g_gen_history_count, 10);
   for(int _h = 0; _h < hist_count; _h++)
   {
      if(_h > 0) json += ",";
      json += DoubleToString(g_gen_history[_h], 2);
   }
   json += "],";

   json += "\"version\":\"7.2\"";
   json += "}";

   // Tester-specific structured logging
   if((bool)MQLInfoInteger(MQL_TESTER))
   {
      double wr_pct = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 0.0;
      Print("[TESTER] Gen=", g_generation,
            " Trades=", g_total_trades,
            " WR=", DoubleToString(wr_pct, 1), "%",
            " Fitness=", DoubleToString(g_best_fitness, 2),
            " Gap=", DoubleToString(g_gap, 0),
            " TP=", DoubleToString(g_tp, 1),
            " SL=", DoubleToString(g_sl, 1),
            " StopTrade=", g_stop_trading);
   }

   int fh = FileOpen(FILE_STATUS, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE)
   {
      FileWriteString(fh, json);
      FileClose(fh);
   }

   // Append to history (JSON array)
   AppendHistory(json);
}

//──────────────────────────────────────────────────────────────────
// HELPER FUNCTIONS
//──────────────────────────────────────────────────────────────────

bool OpenBuy(double lot, string comment)
{
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool ok = g_trade.Buy(lot, _Symbol, price, 0, 0, comment);
   if(ok) Print("[DNA] BUY ", lot, " @ ", price, " | ", comment);
   else   Print("[DNA] BUY FAILED: ", g_trade.ResultRetcodeDescription());
   return ok;
}

bool OpenSell(double lot, string comment)
{
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool ok = g_trade.Sell(lot, _Symbol, price, 0, 0, comment);
   if(ok) Print("[DNA] SELL ", lot, " @ ", price, " | ", comment);
   else   Print("[DNA] SELL FAILED: ", g_trade.ResultRetcodeDescription());
   return ok;
}

void CloseAll(string reason)
{
   Print("[DNA v7.2] Closing all | Reason: ", reason);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(g_pos.SelectByIndex(i))
      {
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            g_trade.PositionClose(g_pos.Ticket());
      }
   }
   g_direction   = 0;
   g_levels_open = 0;
}

int CountOurPositions()
{
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            count++;
   }
   return count;
}

int GetCurrentDirection()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
      {
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            return (g_pos.PositionType() == POSITION_TYPE_BUY) ? 1 : -1;
      }
   }
   return 0;
}

double GetBasketProfit()
{
   double profit = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
            profit += g_pos.Profit() + g_pos.Swap() + g_pos.Commission();
   }
   return profit;
}

double GetWorstBuyPrice()
{
   double worst = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
      {
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol
            && g_pos.PositionType() == POSITION_TYPE_BUY)
         {
            if(worst == 0 || g_pos.PriceOpen() < worst)
               worst = g_pos.PriceOpen();
         }
      }
   }
   return worst;
}

double GetWorstSellPrice()
{
   double worst = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
      {
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol
            && g_pos.PositionType() == POSITION_TYPE_SELL)
         {
            if(worst == 0 || g_pos.PriceOpen() > worst)
               worst = g_pos.PriceOpen();
         }
      }
   }
   return worst;
}

double GetFirstLevelPrice(int dir)
{
   double price = 0;
   datetime oldest = TimeCurrent();
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(g_pos.SelectByIndex(i))
      {
         if(g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
         {
            if(g_pos.Time() <= oldest)
            {
               oldest = g_pos.Time();
               price  = g_pos.PriceOpen();
            }
         }
      }
   }
   return price;
}

double NormalizeLot(double lot)
{
   double min_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathRound(lot / lot_step) * lot_step;
   return MathMax(min_lot, MathMin(max_lot, lot));
}

double GetRSI()
{
   if(g_rsi_handle == INVALID_HANDLE) return 50.0;
   double buf[];
   if(CopyBuffer(g_rsi_handle, 0, 1, 1, buf) <= 0) return 50.0;
   return buf[0];
}

double GetEMA()
{
   if(g_ema_handle == INVALID_HANDLE) return 0.0;
   double buf[];
   if(CopyBuffer(g_ema_handle, 0, 1, 1, buf) <= 0) return 0.0;
   return buf[0];
}

bool IsSessionOpen()
{
   if(!InpUseSession) return true;
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   return (dt.hour >= InpSessionStart && dt.hour < InpSessionEnd);
}

void UpdateStats()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance > g_max_balance) g_max_balance = balance;
   if(balance < g_min_balance) g_min_balance = balance;
   g_last_balance = balance;
}

void AppendHistory(string bar_json)
{
   // Read existing, append, save (capped at 500 entries)
   // For performance in tester we only write every 10 bars
   if(g_bar_count % 10 != 0) return;

   int fh = FileOpen(FILE_HISTORY, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   string existing = "";
   if(fh != INVALID_HANDLE)
   {
      while(!FileIsEnding(fh))
         existing += FileReadString(fh);
      FileClose(fh);
   }

   // Parse existing array and add entry
   // Simple approach: maintain as JSON lines
   fh = FileOpen(FILE_HISTORY, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE)
   {
      if(StringLen(existing) > 10)
         FileWriteString(fh, existing + "\n" + bar_json);
      else
         FileWriteString(fh, bar_json);
      FileClose(fh);
   }
}

double ExtractDouble(string json, string key)
{
   int pos = StringFind(json, key);
   if(pos < 0) return -1;
   pos += StringLen(key) + 1; // skip key + ':'
   // Skip whitespace and colon
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

void UpdateComment()
{
   double wr = (g_total_trades > 0) ? (g_total_wins * 100.0 / g_total_trades) : 0;
   string dir_str = (g_direction == 1) ? "▲ BUY" : (g_direction == -1) ? "▼ SELL" : "— FLAT";

   string comment_str =
      "╔═══ DNA EVOLVE v7.2 ═══════════════╗\n" +
      "║ Gen: " + IntegerToString(g_generation) +
      "  Trades: " + IntegerToString(g_gen_trades) + "/" + IntegerToString(InpGenSize) + "\n" +
      "║ Direction: " + dir_str +
      "  Levels: " + IntegerToString(g_levels_open) + "\n" +
      "║ Basket P&L: $" + DoubleToString(GetBasketProfit(), 2) + "\n" +
      "╠═══ DNA PARAMS ════════════════════╣\n" +
      "║ Gap: " + DoubleToString(g_gap, 0) +
      "  TP: $" + DoubleToString(g_tp, 1) +
      "  SL: $" + DoubleToString(g_sl, 1) + "\n" +
      "║ Lot: " + DoubleToString(g_lot, 3) +
      "  ×" + DoubleToString(g_factor, 2) + "\n" +
      "╠═══ STATS ═════════════════════════╣\n" +
      "║ WR: " + DoubleToString(wr, 1) + "%" +
      "  W:" + IntegerToString(g_total_wins) +
      " L:" + IntegerToString(g_total_losses) + "\n" +
      "║ Best Fitness: " + DoubleToString(g_best_fitness, 1) + "\n" +
      "╚═══════════════════════════════════╝";

   Comment(comment_str);
}

//──────────────────────────────────────────────────────────────────
// DNA PERSISTENCE
//──────────────────────────────────────────────────────────────────
void SaveDNAState()
{
   string json = "{";
   json += "\"generation\":"  + IntegerToString(g_generation)      + ",";
   json += "\"best_fitness\":" + DoubleToString(g_best_fitness, 4) + ",";
   json += "\"gap\":"          + DoubleToString(g_gap, 2)          + ",";
   json += "\"tp\":"           + DoubleToString(g_tp, 2)           + ",";
   json += "\"sl\":"           + DoubleToString(g_sl, 2)           + ",";
   json += "\"lot\":"          + DoubleToString(g_lot, 4)          + ",";
   json += "\"factor\":"       + DoubleToString(g_factor, 4)       + ",";
   json += "\"total_trades\":" + IntegerToString(g_total_trades)   + ",";
   json += "\"total_wins\":"   + IntegerToString(g_total_wins)     + ",";
   json += "\"total_losses\":" + IntegerToString(g_total_losses)   + "}";

   int fh = FileOpen(FILE_DNA, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE)
   {
      FileWriteString(fh, json);
      FileClose(fh);
   }
}

void LoadDNAState()
{
   if(!FileIsExist(FILE_DNA, FILE_COMMON)) return;
   int fh = FileOpen(FILE_DNA, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh == INVALID_HANDLE) return;
   string json = "";
   while(!FileIsEnding(fh)) json += FileReadString(fh);
   FileClose(fh);

   double saved_fitness = ExtractDouble(json, "\"best_fitness\"");
   double saved_gap     = ExtractDouble(json, "\"gap\"");
   double saved_tp      = ExtractDouble(json, "\"tp\"");
   double saved_sl      = ExtractDouble(json, "\"sl\"");

   if(saved_fitness > -9999) g_best_fitness = saved_fitness;
   if(saved_gap > 0)         g_gap          = saved_gap;
   if(saved_tp > 0)          g_tp           = saved_tp;
   if(saved_sl > 0)          g_sl           = saved_sl;

   Print("[DNA v7.2] State loaded from file. Best fitness: ", g_best_fitness);
}

void SaveBestDNA()
{
   string json = "{";
   json += "\"gap\":"    + DoubleToString(g_gap, 2)    + ",";
   json += "\"tp\":"     + DoubleToString(g_tp, 2)     + ",";
   json += "\"sl\":"     + DoubleToString(g_sl, 2)     + ",";
   json += "\"lot\":"    + DoubleToString(g_lot, 4)    + ",";
   json += "\"factor\":" + DoubleToString(g_factor, 4) + "}";

   int fh = FileOpen("ea_best_dna.json", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, json); FileClose(fh); }
}

void LoadBestDNA()
{
   if(!FileIsExist("ea_best_dna.json", FILE_COMMON)) return;
   int fh = FileOpen("ea_best_dna.json", FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
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
