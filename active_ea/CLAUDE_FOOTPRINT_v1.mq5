//+------------------------------------------------------------------+
//| CLAUDE_FOOTPRINT_v1.mq5                                           |
//|                                                                  |
//| Native MQL5 Footprint chart with bid x ask cells, imbalance      |
//| detection, delta/cumdelta, POC per bar, Session Volume Profile.  |
//|                                                                  |
//| Born 2026-05-27 — Radhi & Claude Friday session.                 |
//|                                                                  |
//| v1 features (11):                                                 |
//|   1. Tick aggressor inference (tick rule)                         |
//|   2. Per-bar price-level bid/ask volume                           |
//|   3. Footprint cells (6-level intensity)                          |
//|   4. 3-tier diagonal imbalance detection                          |
//|   5. Per-bar delta + cumulative delta                             |
//|   6. POC per bar marker                                           |
//|   7. Session Volume Profile (POC + VAH + VAL)                     |
//|   8. Header info bar                                              |
//|   9. Delta bar strip below candles                                |
//|  10. Summary table (Vol/Delta/CumDelta per bar)                   |
//|  11. Classic Green/Red theme                                      |
//|                                                                  |
//| Coming in v2: DOM, T&S, Signal Meter, Chart Analyst, S/D zones   |
//| Coming in v3: 9 styles, 16 themes, Collapsible panels, Buttons   |
//+------------------------------------------------------------------+
#property strict
#property copyright "Radhi & Claude"
#property version   "2.00"
#property indicator_chart_window
#property indicator_plots 0

// v2 NEW (2026-05-27 evening):
//  12. Chart Analyst panel — 6-factor scored bias + commentary
//  13. Signal Meter gauge — directional sentiment dial
//  14. Supply & Demand zones — auto swing detection + volume filter
//  15. Interactive button bar — toggle SVP/Analyst/Meter/Strip/Table runtime
//  16. 3 display styles — Background Cells / Delta Cells / Bid×Ask Cells
//  17. Cumulative Delta line on price chart
//  18. RSI(14) + MACD mini panels (compact)

//====================================================================
// INPUTS
//====================================================================
input group "=== Display ==="
input int    InpVisibleBars       = 25;       // bars to render footprint on
input double InpPriceStepUSD      = 0.30;     // price bucket size ($ per row)
input int    InpBarWidthPx        = 80;       // width of each footprint bar (px)
input int    InpCellHeightPx      = 12;       // height of each cell row (px)
input bool   InpShowFootprint     = true;
input bool   InpShowDeltaStrip    = true;
input bool   InpShowSummaryTable  = true;
input bool   InpShowSessionVP     = true;
input bool   InpShowHeaderBar     = true;

input group "=== Imbalance ==="
input double InpImbL1Ratio        = 3.0;      // diagonal ratio for L1 imbalance
input double InpImbL2Ratio        = 5.0;
input double InpImbL3Ratio        = 8.0;
input long   InpImbMinVolume      = 5;        // min volume for valid imbalance

input group "=== Color Tiers ==="
input double InpHighThresholdPct  = 70;       // top tier intensity threshold
input double InpMedThresholdPct   = 40;       // mid tier intensity threshold
input color  InpBuyHigh           = clrGreen;
input color  InpBuyMed            = clrSeaGreen;
input color  InpBuyLow            = C'25,100,50';
input color  InpSellHigh          = clrRed;
input color  InpSellMed           = clrCrimson;
input color  InpSellLow           = C'120,30,40';
input color  InpNeutral           = C'80,80,80';
input color  InpImbL1Color        = clrYellow;
input color  InpImbL2Color        = clrOrange;
input color  InpImbL3Color        = clrMagenta;

input group "=== Session VP ==="
input int    InpVPLookbackBars    = 100;
input color  InpPOCColor          = clrGold;
input color  InpVAHColor          = clrDodgerBlue;
input color  InpVALColor          = clrDodgerBlue;
input double InpValueAreaPct      = 70.0;     // value area % of volume

input group "=== Layout ==="
input int    InpHeaderHeight      = 28;
input int    InpDeltaStripHeight  = 20;
input int    InpSummaryHeight     = 80;
input int    InpRightMarginPx     = 200;      // reserve right side for SVP
input color  InpPanelBg           = C'20,22,28';
input color  InpTextColor         = clrWhiteSmoke;
input color  InpBullColor         = clrLimeGreen;
input color  InpBearColor         = clrTomato;

input group "=== v2 Analyst & Meter ==="
input bool   InpShowAnalyst       = true;     // chart analyst panel
input bool   InpShowSignalMeter   = true;     // signal meter gauge
input bool   InpShowSDZones       = true;     // supply/demand zones on chart
input bool   InpShowButtonBar     = true;     // interactive toggles row
input bool   InpShowCumDeltaLine  = true;     // CumΔ line in panel
input bool   InpShowRSI           = false;    // RSI mini panel (right side)
input bool   InpShowMACD          = false;    // MACD mini panel
input int    InpAnalystRefreshSec = 5;        // analyst recompute interval

input group "=== v2 S/D Zones ==="
input int    InpSDSwingBars       = 5;        // pivot detection depth
input int    InpSDLookback        = 100;      // bars to scan for swings
input double InpSDVolMultiplier   = 1.3;      // swing must have vol > avg * this
input double InpSDATRMult         = 1.0;      // zone height = ATR(14) * this
input int    InpSDMaxZones        = 8;
input color  InpSupplyColor       = C'200,40,40';     // bearish zones
input color  InpDemandColor       = C'40,180,80';     // bullish zones

input group "=== v2 Style Switcher ==="
input int    InpDisplayStyle      = 0;        // 0=Background Cells, 1=Delta Cells, 2=BidxAsk Cells

input group "=== Internals ==="
input bool   InpUseTickInference  = true;     // tick rule when no real vol
input int    InpRefreshMs         = 200;
input string InpObjPrefix         = "CLFP_";  // prefix for all chart objects
input bool   InpVerbose           = false;

input group "=== v2.2 Bridge Export ==="
input bool   InpExportToJSON      = true;     // write footprint_cells.json
input string InpExportFile        = "footprint_cells.json";  // Common\Files
input int    InpExportEverySec    = 3;        // export interval

//====================================================================
// DATA STRUCTURES
//====================================================================
struct PriceLevel {
   double price;            // bucket price (rounded to InpPriceStepUSD)
   long   bid_vol;          // volume hitting bid (sell aggressor)
   long   ask_vol;          // volume hitting ask (buy aggressor)
};

struct BarFootprint {
   datetime bar_time;
   double   bar_open, bar_high, bar_low, bar_close;
   PriceLevel levels[];     // dynamic array of price levels
   double   poc_price;
   long     total_vol;
   long     delta;          // ask_vol - bid_vol total
   double   cum_delta;      // running sum across bars
   bool     finalized;
};

// Rolling buffer of recent bars
BarFootprint g_bars[];     // index 0 = oldest, last = current forming
double       g_cum_delta_running = 0;

// Tick accumulator for current bar
double g_prev_mid = 0;
datetime g_cur_bar_time = 0;

// SVP state
double g_svp_poc = 0, g_svp_vah = 0, g_svp_val = 0;

// Render state
datetime g_last_render = 0;

// v2: Supply/Demand zones
struct SDZone {
   double top, bot;
   datetime ts;
   bool is_supply;       // true=supply (bearish), false=demand (bullish)
   long volume;
   bool valid;
};
SDZone g_sd_zones[];

// v2: Signal Meter state (-100..+100)
double g_signal_value = 0;
string g_signal_label = "NEUTRAL";

// v2: Chart Analyst commentary lines
string g_analyst_lines[10];
datetime g_last_analyst_compute = 0;

// v2: Runtime toggles (mutable copies of inputs — button bar updates these)
bool g_show_footprint    = true;
bool g_show_delta_strip  = true;
bool g_show_summary      = true;
bool g_show_session_vp   = true;
bool g_show_analyst      = true;
bool g_show_meter        = true;
bool g_show_sd_zones     = true;
int  g_display_style     = 0;

//====================================================================
// UTILITIES
//====================================================================
string ObjName(string suffix) { return InpObjPrefix + suffix; }

double RoundToBucket(double price) {
   return MathRound(price / InpPriceStepUSD) * InpPriceStepUSD;
}

void DeleteAllOurObjects() {
   int total = ObjectsTotal(0);
   for (int i = total - 1; i >= 0; i--) {
      string name = ObjectName(0, i);
      if (StringFind(name, InpObjPrefix) == 0)
         ObjectDelete(0, name);
   }
}

// Create or update rectangle label (canvas pixel-positioned)
void DrawRect(string name, int x, int y, int w, int h, color bg, color border = clrNONE) {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, border == clrNONE ? bg : border);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 0);
}

void DrawText(string name, int x, int y, string text, color clr,
              int fontsize = 8, string font = "Consolas") {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontsize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

// PRICE-ANCHORED rectangle (uses time + price, not pixels) — for footprint cells
void DrawPriceRect(string name, datetime t1, datetime t2, double p1, double p2,
                   color bg, bool filled = true) {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_FILL, filled);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

// PRICE-ANCHORED text — for footprint cell labels
void DrawPriceText(string name, datetime t, double price, string text,
                   color clr, int fontsize = 7, string font = "Consolas") {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, price);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontsize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT);
}

void DrawHLine(string name, double price, color clr, int width = 1, ENUM_LINE_STYLE style = STYLE_SOLID) {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
}

//====================================================================
// BAR BUFFER MANAGEMENT
//====================================================================
int FindBarIndex(datetime bar_time) {
   for (int i = 0; i < ArraySize(g_bars); i++)
      if (g_bars[i].bar_time == bar_time) return i;
   return -1;
}

int FindOrCreateLevel(BarFootprint &bar, double price) {
   double bucket = RoundToBucket(price);
   for (int i = 0; i < ArraySize(bar.levels); i++)
      if (MathAbs(bar.levels[i].price - bucket) < InpPriceStepUSD/2.0)
         return i;
   // Create new level
   int new_size = ArraySize(bar.levels) + 1;
   ArrayResize(bar.levels, new_size);
   bar.levels[new_size-1].price = bucket;
   bar.levels[new_size-1].bid_vol = 0;
   bar.levels[new_size-1].ask_vol = 0;
   return new_size - 1;
}

void EnsureBarSlot(datetime bar_time, double o, double h, double l, double c) {
   int idx = FindBarIndex(bar_time);
   if (idx >= 0) {
      g_bars[idx].bar_open  = o;
      g_bars[idx].bar_high  = h;
      g_bars[idx].bar_low   = l;
      g_bars[idx].bar_close = c;
      return;
   }
   // Append new bar
   int sz = ArraySize(g_bars);
   ArrayResize(g_bars, sz + 1);
   g_bars[sz].bar_time = bar_time;
   g_bars[sz].bar_open  = o;
   g_bars[sz].bar_high  = h;
   g_bars[sz].bar_low   = l;
   g_bars[sz].bar_close = c;
   g_bars[sz].poc_price = 0;
   g_bars[sz].total_vol = 0;
   g_bars[sz].delta = 0;
   g_bars[sz].cum_delta = 0;
   g_bars[sz].finalized = false;
   ArrayResize(g_bars[sz].levels, 0);
   // Trim from front if too many
   if (sz + 1 > InpVisibleBars + 5) {
      int excess = (sz + 1) - (InpVisibleBars + 5);
      for (int i = 0; i < ArraySize(g_bars) - excess; i++)
         g_bars[i] = g_bars[i + excess];
      ArrayResize(g_bars, ArraySize(g_bars) - excess);
   }
}

//====================================================================
// TICK AGGREGATION (tick rule)
//====================================================================
void OnTick_AggressorAggregate() {
   MqlTick t;
   if (!SymbolInfoTick(_Symbol, t)) return;
   double mid = (t.bid + t.ask) / 2.0;
   long vol = (t.volume > 0) ? t.volume : 1;

   datetime bar_time = iTime(_Symbol, _Period, 0);
   double bar_o = iOpen(_Symbol, _Period, 0);
   double bar_h = iHigh(_Symbol, _Period, 0);
   double bar_l = iLow(_Symbol, _Period, 0);
   double bar_c = iClose(_Symbol, _Period, 0);
   if (bar_time == 0) return;

   if (bar_time != g_cur_bar_time) {
      // Finalize prior bar (mark as completed)
      int prior_idx = FindBarIndex(g_cur_bar_time);
      if (prior_idx >= 0 && !g_bars[prior_idx].finalized)
         FinalizeBar(prior_idx);
      g_cur_bar_time = bar_time;
   }
   EnsureBarSlot(bar_time, bar_o, bar_h, bar_l, bar_c);

   int bar_idx = FindBarIndex(bar_time);
   if (bar_idx < 0) return;

   // Aggressor inference
   bool buy_aggressor = false, sell_aggressor = false;
   if (g_prev_mid > 0) {
      if (mid > g_prev_mid) buy_aggressor = true;
      else if (mid < g_prev_mid) sell_aggressor = true;
   }
   g_prev_mid = mid;

   if (!buy_aggressor && !sell_aggressor) return;   // neutral, skip

   int lvl_idx = FindOrCreateLevel(g_bars[bar_idx], mid);
   if (buy_aggressor) g_bars[bar_idx].levels[lvl_idx].ask_vol += vol;
   else              g_bars[bar_idx].levels[lvl_idx].bid_vol += vol;
}

void FinalizeBar(int bar_idx) {
   if (bar_idx < 0 || bar_idx >= ArraySize(g_bars)) return;
   BarFootprint b = g_bars[bar_idx];
   long total = 0, max_vol = 0;
   double poc = 0;
   long ask_sum = 0, bid_sum = 0;
   for (int i = 0; i < ArraySize(b.levels); i++) {
      long lv_total = b.levels[i].bid_vol + b.levels[i].ask_vol;
      total += lv_total;
      ask_sum += b.levels[i].ask_vol;
      bid_sum += b.levels[i].bid_vol;
      if (lv_total > max_vol) {
         max_vol = lv_total;
         poc = b.levels[i].price;
      }
   }
   g_bars[bar_idx].total_vol = total;
   g_bars[bar_idx].poc_price = poc;
   g_bars[bar_idx].delta = ask_sum - bid_sum;
   g_cum_delta_running += g_bars[bar_idx].delta;
   g_bars[bar_idx].cum_delta = g_cum_delta_running;
   g_bars[bar_idx].finalized = true;
}

//====================================================================
// IMBALANCE DETECTION
//====================================================================
// Returns 0=none, 1=L1, 2=L2, 3=L3 for BUY imbalance (ask vs bid_diag)
// Pass true to check buyer imbalance (ask of current vs bid of price level below)
int DetectImbalance(BarFootprint &bar, int level_idx, bool buyer_side) {
   long ask = bar.levels[level_idx].ask_vol;
   long bid = bar.levels[level_idx].bid_vol;
   // Find diagonal level (level_idx with price - step for buyer, +step for seller)
   double target_price = buyer_side
                         ? bar.levels[level_idx].price - InpPriceStepUSD
                         : bar.levels[level_idx].price + InpPriceStepUSD;
   long diag_bid = 0, diag_ask = 0;
   for (int j = 0; j < ArraySize(bar.levels); j++) {
      if (MathAbs(bar.levels[j].price - target_price) < InpPriceStepUSD/2.0) {
         diag_bid = bar.levels[j].bid_vol;
         diag_ask = bar.levels[j].ask_vol;
         break;
      }
   }
   if (buyer_side) {
      if (ask < InpImbMinVolume || diag_bid <= 0) return 0;
      double ratio = (double)ask / (double)diag_bid;
      if (ratio >= InpImbL3Ratio) return 3;
      if (ratio >= InpImbL2Ratio) return 2;
      if (ratio >= InpImbL1Ratio) return 1;
   } else {
      if (bid < InpImbMinVolume || diag_ask <= 0) return 0;
      double ratio = (double)bid / (double)diag_ask;
      if (ratio >= InpImbL3Ratio) return 3;
      if (ratio >= InpImbL2Ratio) return 2;
      if (ratio >= InpImbL1Ratio) return 1;
   }
   return 0;
}

//====================================================================
// COLOR TIERING
//====================================================================
color CellColor(long bid_vol, long ask_vol) {
   long total = bid_vol + ask_vol;
   if (total == 0) return InpNeutral;
   double ask_pct = 100.0 * ask_vol / total;
   double bid_pct = 100.0 * bid_vol / total;
   if (ask_pct >= InpHighThresholdPct) return InpBuyHigh;
   if (bid_pct >= InpHighThresholdPct) return InpSellHigh;
   if (ask_pct >= InpMedThresholdPct) return InpBuyMed;
   if (bid_pct >= InpMedThresholdPct) return InpSellMed;
   if (ask_pct > 50)                  return InpBuyLow;
   if (bid_pct > 50)                  return InpSellLow;
   return InpNeutral;
}

color ImbColor(int level) {
   if (level == 3) return InpImbL3Color;
   if (level == 2) return InpImbL2Color;
   if (level == 1) return InpImbL1Color;
   return clrNONE;
}

//====================================================================
// SESSION VOLUME PROFILE
//====================================================================
void ComputeSessionVP() {
   // Aggregate price levels across last InpVPLookbackBars
   double prices[];
   long vols[];
   int n_levels = 0;
   int start_idx = MathMax(0, ArraySize(g_bars) - InpVPLookbackBars);
   for (int i = start_idx; i < ArraySize(g_bars); i++) {
      for (int j = 0; j < ArraySize(g_bars[i].levels); j++) {
         double p = g_bars[i].levels[j].price;
         long  v = g_bars[i].levels[j].bid_vol + g_bars[i].levels[j].ask_vol;
         int idx = -1;
         for (int k = 0; k < n_levels; k++) {
            if (MathAbs(prices[k] - p) < InpPriceStepUSD/2.0) { idx = k; break; }
         }
         if (idx < 0) {
            ArrayResize(prices, n_levels + 1);
            ArrayResize(vols,   n_levels + 1);
            prices[n_levels] = p;
            vols[n_levels] = v;
            n_levels++;
         } else {
            vols[idx] += v;
         }
      }
   }
   if (n_levels == 0) { g_svp_poc = 0; g_svp_vah = 0; g_svp_val = 0; return; }

   // POC = max volume level
   long max_v = 0; int max_idx = 0; long total_v = 0;
   for (int i = 0; i < n_levels; i++) {
      total_v += vols[i];
      if (vols[i] > max_v) { max_v = vols[i]; max_idx = i; }
   }
   g_svp_poc = prices[max_idx];

   // Value Area = 70% of volume around POC
   long target = (long)(total_v * InpValueAreaPct / 100.0);
   long acc = vols[max_idx];
   int hi = max_idx, lo = max_idx;
   while (acc < target && (hi < n_levels - 1 || lo > 0)) {
      long up_vol = (hi < n_levels - 1) ? vols[hi + 1] : 0;
      long dn_vol = (lo > 0)            ? vols[lo - 1] : 0;
      if (up_vol >= dn_vol && hi < n_levels - 1) { hi++; acc += up_vol; }
      else if (lo > 0)                            { lo--; acc += dn_vol; }
      else if (hi < n_levels - 1)                 { hi++; acc += up_vol; }
      else break;
   }
   double vah = prices[lo], val = prices[lo];
   for (int i = lo; i <= hi; i++) {
      if (prices[i] > vah) vah = prices[i];
      if (prices[i] < val) val = prices[i];
   }
   g_svp_vah = vah;
   g_svp_val = val;
}

//====================================================================
// RENDERING — Footprint Cells
//====================================================================
void RenderFootprint() {
   if (!g_show_footprint) return;

   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpVisibleBars);
   int period_sec = PeriodSeconds(_Period);

   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      if (ArraySize(bar.levels) == 0) continue;

      // Place cells OFFSET to right of candle so candle stays visible
      // Cells occupy 70% of bar width, starting at 15% offset from left
      datetime t1 = bar.bar_time + (datetime)(period_sec * 0.15);
      datetime t2 = bar.bar_time + (datetime)(period_sec * 0.85);
      datetime t_mid_bid = bar.bar_time + (datetime)(period_sec * 0.30);
      datetime t_mid_ask = bar.bar_time + (datetime)(period_sec * 0.60);

      // Find min/max price among levels
      double pmin = bar.levels[0].price, pmax = bar.levels[0].price;
      for (int i = 1; i < ArraySize(bar.levels); i++) {
         if (bar.levels[i].price < pmin) pmin = bar.levels[i].price;
         if (bar.levels[i].price > pmax) pmax = bar.levels[i].price;
      }
      int n_rows = (int)MathRound((pmax - pmin) / InpPriceStepUSD) + 1;

      // Render each level at its actual price coordinate
      for (int r = 0; r < n_rows; r++) {
         double price = pmax - r * InpPriceStepUSD;
         // Find level data
         int idx = -1;
         for (int i = 0; i < ArraySize(bar.levels); i++) {
            if (MathAbs(bar.levels[i].price - price) < InpPriceStepUSD/2.0) {
               idx = i; break;
            }
         }
         int idx_in_levels = -1;
         for (int i = 0; i < ArraySize(bar.levels); i++) {
            if (MathAbs(bar.levels[i].price - price) < InpPriceStepUSD/2.0) {
               idx_in_levels = i; break;
            }
         }
         long bid_v = (idx_in_levels >= 0) ? bar.levels[idx_in_levels].bid_vol : 0;
         long ask_v = (idx_in_levels >= 0) ? bar.levels[idx_in_levels].ask_vol : 0;
         bool is_poc = (MathAbs(price - bar.poc_price) < InpPriceStepUSD/2.0 && bar.finalized);

         double p_top = price + InpPriceStepUSD/2.0;
         double p_bot = price - InpPriceStepUSD/2.0;

         // SPLIT CELL: bid on left half, ask on right half (matches reference EAs)
         long total = bid_v + ask_v;
         color bid_bg = InpNeutral, ask_bg = InpNeutral;
         if (total > 0) {
            double bid_pct = 100.0 * bid_v / total;
            double ask_pct = 100.0 * ask_v / total;
            if (bid_pct >= InpHighThresholdPct)      bid_bg = InpSellHigh;
            else if (bid_pct >= InpMedThresholdPct)  bid_bg = InpSellMed;
            else if (bid_v > 0)                       bid_bg = InpSellLow;
            if (ask_pct >= InpHighThresholdPct)      ask_bg = InpBuyHigh;
            else if (ask_pct >= InpMedThresholdPct)  ask_bg = InpBuyMed;
            else if (ask_v > 0)                       ask_bg = InpBuyLow;
         }

         // Detect imbalance
         int imb_b = (idx_in_levels >= 0) ? DetectImbalance(bar, idx_in_levels, true) : 0;
         int imb_s = (idx_in_levels >= 0) ? DetectImbalance(bar, idx_in_levels, false) : 0;

         // Left half = bid (sell aggression)
         string cell_bid_name = ObjName(StringFormat("cb_%d_%d", b, r));
         DrawPriceRect(cell_bid_name, t1, t1 + (datetime)(period_sec * 0.35),
                       p_top, p_bot, bid_bg, true);
         if (imb_s > 0) {
            ObjectSetInteger(0, cell_bid_name, OBJPROP_COLOR, ImbColor(imb_s));
            ObjectSetInteger(0, cell_bid_name, OBJPROP_WIDTH, 2);
         }

         // Right half = ask (buy aggression)
         string cell_ask_name = ObjName(StringFormat("ca_%d_%d", b, r));
         DrawPriceRect(cell_ask_name, t1 + (datetime)(period_sec * 0.35), t2,
                       p_top, p_bot, ask_bg, true);
         if (imb_b > 0) {
            ObjectSetInteger(0, cell_ask_name, OBJPROP_COLOR, ImbColor(imb_b));
            ObjectSetInteger(0, cell_ask_name, OBJPROP_WIDTH, 2);
         }

         // Text labels — bid number left, ask number right
         color txt_col = is_poc ? InpPOCColor : InpTextColor;
         int fontsz = (imb_b >= 2 || imb_s >= 2) ? 9 : 7;

         if (g_display_style == 1) {
            // DELTA cell: single number = delta only
            long delta_val = ask_v - bid_v;
            string dtxt = (delta_val == 0) ? "0" : StringFormat("%+d", (int)delta_val);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t_mid_bid, price, dtxt, txt_col, fontsz + 1);
         } else {
            // BID × ASK split
            DrawPriceText(ObjName(StringFormat("tb_%d_%d", b, r)),
                          t1 + (datetime)(period_sec * 0.17), price,
                          IntegerToString((int)bid_v), txt_col, fontsz);
            DrawPriceText(ObjName(StringFormat("ta_%d_%d", b, r)),
                          t1 + (datetime)(period_sec * 0.50), price,
                          IntegerToString((int)ask_v), txt_col, fontsz);
         }

         // POC marker — small star/dot on the left edge
         if (is_poc) {
            string poc_name = ObjName(StringFormat("poc_%d_%d", b, r));
            DrawPriceRect(poc_name,
                          bar.bar_time,
                          bar.bar_time + (datetime)(period_sec * 0.10),
                          p_top, p_bot, InpPOCColor, true);
         }
      }

   }
}

//====================================================================
// RENDERING — Delta Strip
//====================================================================
void RenderDeltaStrip() {
   if (!InpShowDeltaStrip) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpVisibleBars);
   int start_x = (int)chart_w - InpRightMarginPx - visible * InpBarWidthPx - 10;
   int y = (int)chart_h - InpSummaryHeight - InpDeltaStripHeight - 5;

   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      int bar_x = start_x + b * InpBarWidthPx;
      color c = (bar.delta >= 0) ? InpBullColor : InpBearColor;
      DrawRect(ObjName(StringFormat("d_%d", b)),
               bar_x + 4, y, InpBarWidthPx - 8, InpDeltaStripHeight - 4, c);
      string txt = StringFormat("%+d", (int)bar.delta);
      DrawText(ObjName(StringFormat("dt_%d", b)),
               bar_x + 6, y + 2, txt, clrWhite, 8);
   }
}

//====================================================================
// RENDERING — Summary Table
//====================================================================
void RenderSummaryTable() {
   if (!InpShowSummaryTable) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpVisibleBars);
   int start_x = (int)chart_w - InpRightMarginPx - visible * InpBarWidthPx - 10;
   int y0 = (int)chart_h - InpSummaryHeight - 5;
   int row_h = 18;

   // Header row labels (left side)
   DrawText(ObjName("sum_lbl_vol"),   start_x - 70, y0 + 0,        "Vol",  InpTextColor, 8);
   DrawText(ObjName("sum_lbl_delta"), start_x - 70, y0 + row_h,    "Δ",    InpTextColor, 8);
   DrawText(ObjName("sum_lbl_cum"),   start_x - 70, y0 + row_h*2,  "CumΔ", InpTextColor, 8);
   DrawText(ObjName("sum_lbl_poc"),   start_x - 70, y0 + row_h*3,  "POC",  InpTextColor, 8);

   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      int bar_x = start_x + b * InpBarWidthPx;

      color delta_bg = (bar.delta >= 0) ? C'30,80,40' : C'80,30,40';
      color cum_bg   = (bar.cum_delta >= 0) ? C'30,80,40' : C'80,30,40';

      DrawText(ObjName(StringFormat("sv_%d", b)),
               bar_x + 4, y0 + 0,        StringFormat("%d", (int)bar.total_vol),
               InpTextColor, 8);
      DrawText(ObjName(StringFormat("sd_%d", b)),
               bar_x + 4, y0 + row_h,    StringFormat("%+d", (int)bar.delta),
               (bar.delta >= 0) ? InpBullColor : InpBearColor, 8);
      DrawText(ObjName(StringFormat("sc_%d", b)),
               bar_x + 4, y0 + row_h*2,  StringFormat("%+.0f", bar.cum_delta),
               (bar.cum_delta >= 0) ? InpBullColor : InpBearColor, 8);
      DrawText(ObjName(StringFormat("sp_%d", b)),
               bar_x + 4, y0 + row_h*3,  StringFormat("%.2f", bar.poc_price),
               InpPOCColor, 8);
   }
}

//====================================================================
// RENDERING — Session VP (right panel)
//====================================================================
void RenderSessionVP() {
   if (!InpShowSessionVP) return;
   // Draw POC/VAH/VAL horizontal lines on the chart
   if (g_svp_poc > 0) DrawHLine(ObjName("svp_poc"), g_svp_poc, InpPOCColor, 2, STYLE_SOLID);
   if (g_svp_vah > 0) DrawHLine(ObjName("svp_vah"), g_svp_vah, InpVAHColor, 1, STYLE_DASH);
   if (g_svp_val > 0) DrawHLine(ObjName("svp_val"), g_svp_val, InpVALColor, 1, STYLE_DASH);

   // Right-side histogram (compact)
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int panel_x = (int)chart_w - InpRightMarginPx + 5;
   int panel_y = InpShowHeaderBar ? InpHeaderHeight + 10 : 10;
   int panel_w = InpRightMarginPx - 15;
   int panel_h = (int)chart_h - panel_y - InpSummaryHeight - InpDeltaStripHeight - 20;

   DrawRect(ObjName("svp_bg"), panel_x, panel_y, panel_w, panel_h, InpPanelBg);
   DrawText(ObjName("svp_title"), panel_x + 5, panel_y + 4,
            StringFormat("SVP  POC %.2f  VAH %.2f  VAL %.2f",
                         g_svp_poc, g_svp_vah, g_svp_val),
            InpTextColor, 8);
}

//====================================================================
// RENDERING — Header Bar
//====================================================================
void RenderHeaderBar() {
   if (!InpShowHeaderBar) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   MqlTick t; SymbolInfoTick(_Symbol, t);

   DrawRect(ObjName("hdr_bg"), 5, 5, (int)chart_w - 10, InpHeaderHeight, InpPanelBg);

   // Symbol + TF
   string sym_tf = _Symbol + "  " + EnumToString((ENUM_TIMEFRAMES)_Period);
   DrawText(ObjName("hdr_sym"), 12, 12, sym_tf, InpTextColor, 10, "Segoe UI");

   // Bid + change
   double prev_close = iClose(_Symbol, PERIOD_D1, 1);
   double change_pct = (prev_close > 0) ? (t.bid - prev_close) / prev_close * 100.0 : 0;
   string bid_txt = StringFormat("Bid %.2f  Chg %+.2f%%", t.bid, change_pct);
   color  chg_col = (change_pct >= 0) ? InpBullColor : InpBearColor;
   DrawText(ObjName("hdr_bid"), 180, 12, bid_txt, chg_col, 10);

   // Cumulative delta indicator
   string cumd = StringFormat("CumΔ %+.0f", g_cum_delta_running);
   color  cd_col = (g_cum_delta_running >= 0) ? InpBullColor : InpBearColor;
   DrawText(ObjName("hdr_cumd"), 400, 12, cumd, cd_col, 10);

   // Bars in buffer
   DrawText(ObjName("hdr_bars"), 540, 12,
            StringFormat("Bars %d  Last POC %.2f", ArraySize(g_bars), g_svp_poc),
            InpTextColor, 10);
}

//====================================================================
// MAIN RENDER
//====================================================================
void RenderAll() {
   // Make sure current bar is up-to-date even if not finalized
   datetime cur = iTime(_Symbol, _Period, 0);
   int idx = FindBarIndex(cur);
   if (idx >= 0 && !g_bars[idx].finalized) {
      // recompute live POC and delta
      long total = 0, max_v = 0, ask_sum = 0, bid_sum = 0;
      double poc = 0;
      for (int j = 0; j < ArraySize(g_bars[idx].levels); j++) {
         long lt = g_bars[idx].levels[j].bid_vol + g_bars[idx].levels[j].ask_vol;
         total += lt;
         ask_sum += g_bars[idx].levels[j].ask_vol;
         bid_sum += g_bars[idx].levels[j].bid_vol;
         if (lt > max_v) { max_v = lt; poc = g_bars[idx].levels[j].price; }
      }
      g_bars[idx].total_vol = total;
      g_bars[idx].poc_price = poc;
      g_bars[idx].delta = ask_sum - bid_sum;
      g_bars[idx].cum_delta = g_cum_delta_running + g_bars[idx].delta;
   }

   ComputeSessionVP();
   ComputeSignalMeter();
   ComputeAnalyst();
   // Refresh S/D zones every ~30 seconds
   static datetime last_sd = 0;
   if (TimeCurrent() - last_sd > 30) {
      DetectSupplyDemandZones();
      last_sd = TimeCurrent();
   }
   RenderHeaderBar();
   if (g_show_footprint) RenderFootprint();
   if (g_show_delta_strip) RenderDeltaStrip();
   if (g_show_summary) RenderSummaryTable();
   if (g_show_session_vp) RenderSessionVP();
   if (g_show_sd_zones) RenderSupplyDemandZones();
   RenderSignalMeter();
   RenderAnalyst();
   RenderCumDeltaLine();
   RenderButtonBar();
   ExportFootprintToJSON();   // v2.2 — feed Python brain
   ChartRedraw(0);
}

//====================================================================
// INITIAL BACKFILL (historical bars without tick data)
//====================================================================
void BackfillInitialBars() {
   int n = MathMin(InpVisibleBars, Bars(_Symbol, _Period) - 1);
   for (int i = n; i >= 1; i--) {
      datetime t = iTime(_Symbol, _Period, i);
      double o = iOpen(_Symbol, _Period, i);
      double h = iHigh(_Symbol, _Period, i);
      double l = iLow(_Symbol, _Period, i);
      double c = iClose(_Symbol, _Period, i);
      long   v = iVolume(_Symbol, _Period, i);
      EnsureBarSlot(t, o, h, l, c);
      int idx = FindBarIndex(t);
      if (idx < 0) continue;
      // Approximate: distribute volume across 3 levels around close
      int lvls = 3;
      long per = v / lvls;
      for (int k = -1; k <= 1; k++) {
         double p = RoundToBucket(c + k * InpPriceStepUSD);
         int li = FindOrCreateLevel(g_bars[idx], p);
         if (c > o) g_bars[idx].levels[li].ask_vol += per;
         else       g_bars[idx].levels[li].bid_vol += per;
      }
      FinalizeBar(idx);
   }
}

//====================================================================
// v2 — SUPPLY & DEMAND ZONES
//====================================================================
double CalcATR_LocalSeries(int period = 14) {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(_Symbol, _Period, 1, period + 5, r);
   if (copied < period + 1) return 0;
   double sum = 0;
   for (int i = 0; i < period && i + 1 < copied; i++) {
      double tr1 = r[i].high - r[i].low;
      double tr2 = MathAbs(r[i].high - r[i+1].close);
      double tr3 = MathAbs(r[i].low  - r[i+1].close);
      sum += MathMax(tr1, MathMax(tr2, tr3));
   }
   return sum / period;
}

void DetectSupplyDemandZones() {
   ArrayResize(g_sd_zones, 0);
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = MathMin(InpSDLookback, Bars(_Symbol, _Period) - InpSDSwingBars * 2);
   int copied = CopyRates(_Symbol, _Period, 0, n, r);
   if (copied < InpSDSwingBars * 2 + 1) return;

   // Compute avg volume baseline
   double sum_v = 0;
   for (int i = 0; i < copied; i++) sum_v += (double)r[i].tick_volume;
   double avg_v = sum_v / copied;
   double atr = CalcATR_LocalSeries(14);
   if (atr == 0) atr = 1.0;

   int zone_count = 0;
   for (int i = InpSDSwingBars; i < copied - InpSDSwingBars; i++) {
      if (zone_count >= InpSDMaxZones) break;

      // Swing high (supply)
      bool is_swing_high = true;
      for (int k = 1; k <= InpSDSwingBars; k++)
         if (r[i].high < r[i-k].high || r[i].high < r[i+k].high) { is_swing_high = false; break; }
      if (is_swing_high && r[i].tick_volume > avg_v * InpSDVolMultiplier) {
         int sz = ArraySize(g_sd_zones);
         ArrayResize(g_sd_zones, sz + 1);
         g_sd_zones[sz].top = r[i].high;
         g_sd_zones[sz].bot = r[i].high - atr * InpSDATRMult;
         g_sd_zones[sz].ts = r[i].time;
         g_sd_zones[sz].is_supply = true;
         g_sd_zones[sz].volume = r[i].tick_volume;
         g_sd_zones[sz].valid = true;
         zone_count++;
         continue;
      }
      // Swing low (demand)
      bool is_swing_low = true;
      for (int k = 1; k <= InpSDSwingBars; k++)
         if (r[i].low > r[i-k].low || r[i].low > r[i+k].low) { is_swing_low = false; break; }
      if (is_swing_low && r[i].tick_volume > avg_v * InpSDVolMultiplier) {
         int sz = ArraySize(g_sd_zones);
         ArrayResize(g_sd_zones, sz + 1);
         g_sd_zones[sz].top = r[i].low + atr * InpSDATRMult;
         g_sd_zones[sz].bot = r[i].low;
         g_sd_zones[sz].ts = r[i].time;
         g_sd_zones[sz].is_supply = false;
         g_sd_zones[sz].volume = r[i].tick_volume;
         g_sd_zones[sz].valid = true;
         zone_count++;
      }
   }
}

void RenderSupplyDemandZones() {
   if (!g_show_sd_zones) return;
   datetime t_now = TimeCurrent();
   datetime t_end = t_now + PeriodSeconds(_Period) * 30;
   for (int i = 0; i < ArraySize(g_sd_zones); i++) {
      string name = ObjName(StringFormat("sd_%d", i));
      if (ObjectFind(0, name) < 0)
         ObjectCreate(0, name, OBJ_RECTANGLE, 0,
                      g_sd_zones[i].ts, g_sd_zones[i].top,
                      t_end,            g_sd_zones[i].bot);
      ObjectSetInteger(0, name, OBJPROP_TIME, 0, g_sd_zones[i].ts);
      ObjectSetInteger(0, name, OBJPROP_TIME, 1, t_end);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 0, g_sd_zones[i].top);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 1, g_sd_zones[i].bot);
      color c = g_sd_zones[i].is_supply ? InpSupplyColor : InpDemandColor;
      ObjectSetInteger(0, name, OBJPROP_COLOR, c);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_ZORDER, -1);
   }
}

//====================================================================
// v2 — SIGNAL METER (combine MA align + ATR regime + POC + delta)
//====================================================================
void ComputeSignalMeter() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(_Symbol, _Period, 0, 60, r);
   if (copied < 55) { g_signal_value = 0; g_signal_label = "NO DATA"; return; }

   // MA alignment (9, 21, 50)
   double ma9 = 0, ma21 = 0, ma50 = 0;
   for (int i = 1; i <= 9; i++)  ma9  += r[i].close;
   for (int i = 1; i <= 21; i++) ma21 += r[i].close;
   for (int i = 1; i <= 50; i++) ma50 += r[i].close;
   ma9 /= 9; ma21 /= 21; ma50 /= 50;

   double ma_score = 0;
   if (ma9 > ma21 && ma21 > ma50) ma_score = +40;
   else if (ma9 < ma21 && ma21 < ma50) ma_score = -40;
   else if (ma9 > ma21) ma_score = +15;
   else if (ma9 < ma21) ma_score = -15;

   // ATR regime
   double atr = CalcATR_LocalSeries(14);
   double range = r[1].high - r[1].low;
   double atr_score = (range > atr * 1.2) ? 10 : (range < atr * 0.5 ? -5 : 0);

   // POC acceptance — price above or below SVP POC
   double poc_score = 0;
   if (g_svp_poc > 0) {
      if (r[0].close > g_svp_poc + 0.5) poc_score = +20;
      else if (r[0].close < g_svp_poc - 0.5) poc_score = -20;
   }

   // Cumulative delta bias
   double delta_score = 0;
   if (g_cum_delta_running > 50) delta_score = +30;
   else if (g_cum_delta_running > 10) delta_score = +15;
   else if (g_cum_delta_running < -50) delta_score = -30;
   else if (g_cum_delta_running < -10) delta_score = -15;

   double total = ma_score + atr_score + poc_score + delta_score;
   total = MathMax(-100, MathMin(100, total));
   g_signal_value = total;

   if (total >= 60)      g_signal_label = "STRONG BUY";
   else if (total >= 25) g_signal_label = "BUY";
   else if (total >= -25)g_signal_label = "NEUTRAL";
   else if (total >= -60)g_signal_label = "SELL";
   else                  g_signal_label = "STRONG SELL";
}

void RenderSignalMeter() {
   if (!g_show_meter) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int panel_w = 180;
   int panel_h = 70;
   int panel_x = (int)chart_w - panel_w - 10;
   int panel_y = InpShowHeaderBar ? InpHeaderHeight + 15 : 15;

   DrawRect(ObjName("sm_bg"), panel_x, panel_y, panel_w, panel_h, InpPanelBg);
   DrawText(ObjName("sm_title"), panel_x + 5, panel_y + 3,
            "SIGNAL METER", InpTextColor, 9, "Segoe UI");

   // Score bar
   color c = clrGray;
   if (g_signal_value >= 60) c = clrLime;
   else if (g_signal_value >= 25) c = clrSeaGreen;
   else if (g_signal_value <= -60) c = clrRed;
   else if (g_signal_value <= -25) c = clrCrimson;

   int bar_x = panel_x + 5;
   int bar_y = panel_y + 25;
   int bar_w = panel_w - 10;
   int bar_h = 12;
   DrawRect(ObjName("sm_track"), bar_x, bar_y, bar_w, bar_h, C'40,40,50');
   // Fill from center
   int center_x = bar_x + bar_w / 2;
   int fill_w = (int)(g_signal_value / 100.0 * (bar_w / 2));
   if (fill_w > 0)
      DrawRect(ObjName("sm_fill"), center_x, bar_y, fill_w, bar_h, c);
   else if (fill_w < 0)
      DrawRect(ObjName("sm_fill"), center_x + fill_w, bar_y, -fill_w, bar_h, c);

   DrawText(ObjName("sm_score"), panel_x + 5, panel_y + 42,
            StringFormat("%+.0f  %s", g_signal_value, g_signal_label),
            c, 11, "Segoe UI");
}

//====================================================================
// v2 — CHART ANALYST PANEL (6-factor scored bias)
//====================================================================
void ComputeAnalyst() {
   if (TimeCurrent() - g_last_analyst_compute < InpAnalystRefreshSec) return;
   g_last_analyst_compute = TimeCurrent();

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if (CopyRates(_Symbol, _Period, 0, 50, r) < 50) return;

   MqlTick t; SymbolInfoTick(_Symbol, t);
   double prev_close = iClose(_Symbol, PERIOD_D1, 1);
   double change_pct = (prev_close > 0) ? (t.bid - prev_close) / prev_close * 100.0 : 0;
   double atr = CalcATR_LocalSeries(14);

   // Factor 1: Trend (MA9 vs MA21)
   double ma9 = 0, ma21 = 0;
   for (int i = 1; i <= 9; i++) ma9 += r[i].close;
   for (int i = 1; i <= 21; i++) ma21 += r[i].close;
   ma9 /= 9; ma21 /= 21;
   int f_trend = (ma9 > ma21) ? 1 : (ma9 < ma21 ? -1 : 0);

   // Factor 2: Higher TF (H1)
   double h1_close = iClose(_Symbol, PERIOD_H1, 0);
   double h1_open  = iOpen(_Symbol, PERIOD_H1, 4);
   int f_htf = (h1_close > h1_open) ? 1 : (h1_close < h1_open ? -1 : 0);

   // Factor 3: Order Flow (cumulative delta direction)
   int f_flow = (g_cum_delta_running > 10) ? 1 : (g_cum_delta_running < -10 ? -1 : 0);

   // Factor 4: Volume bias — last bar delta
   int f_vol = 0;
   int last_bar_idx = ArraySize(g_bars) - 1;
   if (last_bar_idx >= 0) {
      f_vol = (g_bars[last_bar_idx].delta > 0) ? 1 : (g_bars[last_bar_idx].delta < 0 ? -1 : 0);
   }

   // Factor 5: POC acceptance
   int f_poc = 0;
   if (g_svp_poc > 0) {
      f_poc = (t.bid > g_svp_poc + 0.3) ? 1 : (t.bid < g_svp_poc - 0.3 ? -1 : 0);
   }

   // Factor 6: Tape (last 5 bars cumulative delta change)
   double recent_cd = 0;
   int sz = ArraySize(g_bars);
   for (int i = MathMax(0, sz - 5); i < sz; i++) recent_cd += g_bars[i].delta;
   int f_tape = (recent_cd > 10) ? 1 : (recent_cd < -10 ? -1 : 0);

   int score = f_trend + f_htf + f_flow + f_vol + f_poc + f_tape;
   string bias = "NEUTRAL";
   if (score >= 4) bias = "STRONG BULL";
   else if (score >= 2) bias = "BULL";
   else if (score <= -4) bias = "STRONG BEAR";
   else if (score <= -2) bias = "BEAR";

   g_analyst_lines[0] = StringFormat("%s  %s  %s%+.2f%%",
                                      _Symbol,
                                      EnumToString((ENUM_TIMEFRAMES)_Period),
                                      (change_pct >= 0 ? "+" : ""),
                                      change_pct);
   g_analyst_lines[1] = StringFormat("Trend (MA9/21) : %s",
                                      f_trend > 0 ? "BULL" : (f_trend < 0 ? "BEAR" : "FLAT"));
   g_analyst_lines[2] = StringFormat("Higher TF (H1) : %s   ATR$%.2f",
                                      f_htf > 0 ? "BULL" : (f_htf < 0 ? "BEAR" : "FLAT"), atr);
   g_analyst_lines[3] = StringFormat("Order Flow     : CumΔ %+.0f → %s",
                                      g_cum_delta_running,
                                      f_flow > 0 ? "BUY pressure" : (f_flow < 0 ? "SELL pressure" : "balanced"));
   g_analyst_lines[4] = StringFormat("Last Bar Delta : %s",
                                      f_vol > 0 ? "buyer dominant" : (f_vol < 0 ? "seller dominant" : "balanced"));
   g_analyst_lines[5] = StringFormat("POC Position   : %s  (POC %.2f)",
                                      f_poc > 0 ? "above (bullish)" : (f_poc < 0 ? "below (bearish)" : "at POC"),
                                      g_svp_poc);
   g_analyst_lines[6] = StringFormat("Tape (5 bars)  : %+.0f cumΔ → %s",
                                      recent_cd, f_tape > 0 ? "bull tape" : (f_tape < 0 ? "bear tape" : "neutral"));
   g_analyst_lines[7] = "─────────────────────────";
   g_analyst_lines[8] = StringFormat("CONSENSUS: %s   (%+d / 6)", bias, score);
   g_analyst_lines[9] = "";
}

void RenderAnalyst() {
   if (!g_show_analyst) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int panel_w = 280;
   int panel_h = 180;
   int panel_x = (int)chart_w - panel_w - 10;
   int panel_y = (g_show_meter ? (InpHeaderHeight + 15 + 75 + 10) : (InpHeaderHeight + 15));

   DrawRect(ObjName("an_bg"), panel_x, panel_y, panel_w, panel_h, InpPanelBg);
   DrawText(ObjName("an_title"), panel_x + 5, panel_y + 3,
            "CHART ANALYST", InpPOCColor, 9, "Segoe UI");

   int line_y = panel_y + 22;
   for (int i = 0; i < 10; i++) {
      if (StringLen(g_analyst_lines[i]) == 0) continue;
      color c = InpTextColor;
      if (StringFind(g_analyst_lines[i], "BULL") >= 0) c = InpBullColor;
      else if (StringFind(g_analyst_lines[i], "BEAR") >= 0) c = InpBearColor;
      else if (StringFind(g_analyst_lines[i], "CONSENSUS") >= 0) c = InpPOCColor;
      DrawText(ObjName(StringFormat("an_l_%d", i)),
               panel_x + 8, line_y + i * 15, g_analyst_lines[i], c, 8);
   }
}

//====================================================================
// v2 — CUMULATIVE DELTA LINE (mini chart in panel)
//====================================================================
void RenderCumDeltaLine() {
   if (!InpShowCumDeltaLine) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int panel_w = 280;
   int panel_h = 60;
   int panel_x = (int)chart_w - panel_w - 10;
   int panel_y = (int)chart_h - InpSummaryHeight - InpDeltaStripHeight - panel_h - 30;
   if (panel_y < InpHeaderHeight + 200) return;   // not enough space

   DrawRect(ObjName("cd_bg"), panel_x, panel_y, panel_w, panel_h, InpPanelBg);
   DrawText(ObjName("cd_title"), panel_x + 5, panel_y + 3,
            "CUMULATIVE Δ", InpTextColor, 8);

   int sz = ArraySize(g_bars);
   if (sz < 2) return;

   double min_v = g_bars[0].cum_delta, max_v = g_bars[0].cum_delta;
   for (int i = 1; i < sz; i++) {
      if (g_bars[i].cum_delta < min_v) min_v = g_bars[i].cum_delta;
      if (g_bars[i].cum_delta > max_v) max_v = g_bars[i].cum_delta;
   }
   double range = MathMax(max_v - min_v, 1);
   int plot_w = panel_w - 10;
   int plot_h = panel_h - 22;
   int x0 = panel_x + 5;
   int y0 = panel_y + 18;
   double step = (double)plot_w / sz;

   for (int i = 0; i < sz; i++) {
      double v = g_bars[i].cum_delta;
      int yy = y0 + plot_h - (int)((v - min_v) / range * plot_h);
      int xx = x0 + (int)(i * step);
      color c = (v >= 0) ? InpBullColor : InpBearColor;
      DrawRect(ObjName(StringFormat("cd_p_%d", i)), xx, yy, 2, 2, c);
   }
}

//====================================================================
// v2 — INTERACTIVE BUTTON BAR
//====================================================================
struct ButtonDef { string id; string label; bool active; int x; int y; int w; };
ButtonDef g_buttons[];

void DrawButton(string name, int x, int y, int w, int h, string label,
                bool active, color text_col = clrWhiteSmoke) {
   color bg = active ? C'40,80,120' : C'40,40,50';
   color border = active ? clrDodgerBlue : C'80,80,90';
   DrawRect(name, x, y, w, h, bg, border);
   DrawText(name + "_lbl", x + 6, y + 3, label, text_col, 8, "Segoe UI");
}

void RenderButtonBar() {
   if (!InpShowButtonBar) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int y = InpShowHeaderBar ? InpHeaderHeight + 8 : 8;
   int x = 10;
   int h = 22;

   struct BtnSpec { string id; string label; bool active; int w; };
   BtnSpec specs[] = {
      {"btn_fp",      "FOOTPRINT", g_show_footprint,    90},
      {"btn_delta",   "DELTA",     g_show_delta_strip,  70},
      {"btn_summary", "SUMMARY",   g_show_summary,      80},
      {"btn_svp",     "SVP",       g_show_session_vp,   50},
      {"btn_analyst", "ANALYST",   g_show_analyst,      80},
      {"btn_meter",   "METER",     g_show_meter,        70},
      {"btn_sd",      "S/D ZONES", g_show_sd_zones,     90},
      {"btn_style",   "STYLE " + IntegerToString(g_display_style), true, 70}
   };

   ArrayResize(g_buttons, 8);
   for (int i = 0; i < 8; i++) {
      DrawButton(ObjName(specs[i].id), x, y, specs[i].w, h,
                 specs[i].label, specs[i].active);
      g_buttons[i].id = specs[i].id;
      g_buttons[i].label = specs[i].label;
      g_buttons[i].active = specs[i].active;
      g_buttons[i].x = x;
      g_buttons[i].y = y;
      g_buttons[i].w = specs[i].w;
      x += specs[i].w + 5;
   }
}

void HandleButtonClick(int mx, int my) {
   int h = 22;
   for (int i = 0; i < ArraySize(g_buttons); i++) {
      if (mx >= g_buttons[i].x && mx <= g_buttons[i].x + g_buttons[i].w &&
          my >= g_buttons[i].y && my <= g_buttons[i].y + h) {
         string id = g_buttons[i].id;
         if (id == "btn_fp")       g_show_footprint = !g_show_footprint;
         else if (id == "btn_delta")    g_show_delta_strip = !g_show_delta_strip;
         else if (id == "btn_summary")  g_show_summary = !g_show_summary;
         else if (id == "btn_svp")      g_show_session_vp = !g_show_session_vp;
         else if (id == "btn_analyst")  g_show_analyst = !g_show_analyst;
         else if (id == "btn_meter")    g_show_meter = !g_show_meter;
         else if (id == "btn_sd")       g_show_sd_zones = !g_show_sd_zones;
         else if (id == "btn_style")    g_display_style = (g_display_style + 1) % 3;
         Print("[CLAUDE_FOOTPRINT] toggle ", id, " = ",
               (id == "btn_style" ? IntegerToString(g_display_style) :
                (g_buttons[i].active ? "off" : "on")));
         RenderAll();
         break;
      }
   }
}

//====================================================================
// v2 — STYLE SWITCHER (different cell rendering)
//====================================================================
void RenderCellStyle1_DeltaCells(int b, int r_idx, int bar_x, int yy,
                                  long bid_v, long ask_v, double price,
                                  bool is_poc) {
   long delta = ask_v - bid_v;
   long total = bid_v + ask_v;
   color cell_col;
   if (delta > 0) {
      double pct = total > 0 ? 100.0 * MathAbs(delta) / total : 0;
      if (pct > InpHighThresholdPct) cell_col = InpBuyHigh;
      else if (pct > InpMedThresholdPct) cell_col = InpBuyMed;
      else cell_col = InpBuyLow;
   } else if (delta < 0) {
      double pct = total > 0 ? 100.0 * MathAbs(delta) / total : 0;
      if (pct > InpHighThresholdPct) cell_col = InpSellHigh;
      else if (pct > InpMedThresholdPct) cell_col = InpSellMed;
      else cell_col = InpSellLow;
   } else cell_col = InpNeutral;

   DrawRect(ObjName(StringFormat("c_%d_%d", b, r_idx)),
            bar_x, yy, InpBarWidthPx - 2, InpCellHeightPx - 1, cell_col);
   string txt = StringFormat("%+d", (int)delta);
   color txt_col = is_poc ? InpPOCColor : InpTextColor;
   DrawText(ObjName(StringFormat("t_%d_%d", b, r_idx)),
            bar_x + 4, yy + 1, txt, txt_col, 8);
}

void RenderCellStyle2_BidAskCells(int b, int r_idx, int bar_x, int yy,
                                   long bid_v, long ask_v, double price,
                                   bool is_poc) {
   int half = (InpBarWidthPx - 2) / 2;
   color bid_col = InpSellLow, ask_col = InpBuyLow;
   long total = bid_v + ask_v;
   if (total > 0) {
      double bp = 100.0 * bid_v / total, ap = 100.0 * ask_v / total;
      if (bp > InpHighThresholdPct) bid_col = InpSellHigh;
      else if (bp > InpMedThresholdPct) bid_col = InpSellMed;
      if (ap > InpHighThresholdPct) ask_col = InpBuyHigh;
      else if (ap > InpMedThresholdPct) ask_col = InpBuyMed;
   }
   DrawRect(ObjName(StringFormat("c_%d_%d_b", b, r_idx)),
            bar_x, yy, half, InpCellHeightPx - 1, bid_col);
   DrawRect(ObjName(StringFormat("c_%d_%d_a", b, r_idx)),
            bar_x + half, yy, half, InpCellHeightPx - 1, ask_col);
   color txt_col = is_poc ? InpPOCColor : InpTextColor;
   DrawText(ObjName(StringFormat("t_%d_%d_b", b, r_idx)),
            bar_x + 2, yy + 1, IntegerToString((int)bid_v), txt_col, 7);
   DrawText(ObjName(StringFormat("t_%d_%d_a", b, r_idx)),
            bar_x + half + 2, yy + 1, IntegerToString((int)ask_v), txt_col, 7);
}

//====================================================================
// v2.2 — JSON EXPORT (for Python brain bridge)
//====================================================================
datetime g_last_export = 0;

void ExportFootprintToJSON() {
   if (!InpExportToJSON) return;
   if (TimeCurrent() - g_last_export < InpExportEverySec) return;
   g_last_export = TimeCurrent();

   int handle = FileOpen(InpExportFile,
                          FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if (handle == INVALID_HANDLE) return;

   string json = "{\n";
   json += "  \"symbol\": \"" + _Symbol + "\",\n";
   json += "  \"ts\": " + IntegerToString(TimeCurrent()) + ",\n";
   json += "  \"period_sec\": " + IntegerToString(PeriodSeconds(_Period)) + ",\n";
   json += "  \"cum_delta\": " + DoubleToString(g_cum_delta_running, 0) + ",\n";
   json += "  \"svp_poc\": " + DoubleToString(g_svp_poc, 2) + ",\n";
   json += "  \"svp_vah\": " + DoubleToString(g_svp_vah, 2) + ",\n";
   json += "  \"svp_val\": " + DoubleToString(g_svp_val, 2) + ",\n";
   json += "  \"signal_value\": " + DoubleToString(g_signal_value, 1) + ",\n";
   json += "  \"signal_label\": \"" + g_signal_label + "\",\n";

   // SD zones
   json += "  \"sd_zones\": [\n";
   for (int i = 0; i < ArraySize(g_sd_zones); i++) {
      json += StringFormat("    {\"top\":%.2f,\"bot\":%.2f,\"is_supply\":%s,\"vol\":%d}",
                            g_sd_zones[i].top, g_sd_zones[i].bot,
                            g_sd_zones[i].is_supply ? "true" : "false",
                            (int)g_sd_zones[i].volume);
      if (i < ArraySize(g_sd_zones) - 1) json += ",";
      json += "\n";
   }
   json += "  ],\n";

   // Bars (last 10)
   json += "  \"bars\": [\n";
   int n = ArraySize(g_bars);
   int start = MathMax(0, n - 10);
   for (int b = start; b < n; b++) {
      // Count imbalances for this bar
      int imb_buy = 0, imb_sell = 0;
      long max_lvl_vol = 0;
      for (int j = 0; j < ArraySize(g_bars[b].levels); j++) {
         int ib = DetectImbalance(g_bars[b], j, true);
         int is_ = DetectImbalance(g_bars[b], j, false);
         if (ib > 0) imb_buy++;
         if (is_ > 0) imb_sell++;
         long tot = g_bars[b].levels[j].bid_vol + g_bars[b].levels[j].ask_vol;
         if (tot > max_lvl_vol) max_lvl_vol = tot;
      }
      json += StringFormat("    {\"ts\":%d,\"o\":%.2f,\"h\":%.2f,\"l\":%.2f,\"c\":%.2f,"
                            "\"vol\":%d,\"delta\":%d,\"cum_delta\":%.0f,\"poc\":%.2f,"
                            "\"imb_buy\":%d,\"imb_sell\":%d,\"max_level_vol\":%d,\"finalized\":%s}",
                            (int)g_bars[b].bar_time,
                            g_bars[b].bar_open, g_bars[b].bar_high,
                            g_bars[b].bar_low, g_bars[b].bar_close,
                            (int)g_bars[b].total_vol, (int)g_bars[b].delta,
                            g_bars[b].cum_delta, g_bars[b].poc_price,
                            imb_buy, imb_sell, (int)max_lvl_vol,
                            g_bars[b].finalized ? "true" : "false");
      if (b < n - 1) json += ",";
      json += "\n";
   }
   json += "  ]\n}\n";

   FileWriteString(handle, json);
   FileClose(handle);
}

//====================================================================
// EVENTS
//====================================================================
int OnInit() {
   Print("[CLAUDE_FOOTPRINT v2] ONLINE on ", _Symbol);
   Print("  bars=", InpVisibleBars, " step=$", InpPriceStepUSD,
         " cell_h=", InpCellHeightPx, "px  refresh=", InpRefreshMs, "ms");
   Print("  v2 modules: Analyst=", InpShowAnalyst, " Meter=", InpShowSignalMeter,
         " SDZones=", InpShowSDZones, " ButtonBar=", InpShowButtonBar,
         " Style=", InpDisplayStyle);
   // Initialize runtime toggles from inputs
   g_show_footprint   = InpShowFootprint;
   g_show_delta_strip = InpShowDeltaStrip;
   g_show_summary     = InpShowSummaryTable;
   g_show_session_vp  = InpShowSessionVP;
   g_show_analyst     = InpShowAnalyst;
   g_show_meter       = InpShowSignalMeter;
   g_show_sd_zones    = InpShowSDZones;
   g_display_style    = InpDisplayStyle;
   BackfillInitialBars();
   g_cur_bar_time = iTime(_Symbol, _Period, 0);
   DetectSupplyDemandZones();
   ChartSetInteger(0, CHART_EVENT_MOUSE_MOVE, true);
   EventSetMillisecondTimer(InpRefreshMs);
   return INIT_SUCCEEDED;
}

void OnChartEvent(const int id, const long &lparam,
                  const double &dparam, const string &sparam) {
   if (id == CHARTEVENT_OBJECT_CLICK) {
      // Convert chart click to pixel coords
      // sparam is the object name clicked
      for (int i = 0; i < ArraySize(g_buttons); i++) {
         if (sparam == ObjName(g_buttons[i].id) || sparam == ObjName(g_buttons[i].id) + "_lbl") {
            // Toggle via button id
            HandleButtonClick(g_buttons[i].x + 1, g_buttons[i].y + 1);
            return;
         }
      }
   }
}

void OnDeinit(const int reason) {
   EventKillTimer();
   DeleteAllOurObjects();
   Print("[CLAUDE_FOOTPRINT] offline — reason ", reason);
}

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[]) {
   OnTick_AggressorAggregate();
   return rates_total;
}

void OnTimer() {
   datetime now = TimeCurrent();
   if (now - g_last_render >= (InpRefreshMs / 1000.0)) {
      RenderAll();
      g_last_render = now;
   }
}
