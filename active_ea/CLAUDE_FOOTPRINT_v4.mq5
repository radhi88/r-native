//+------------------------------------------------------------------+
//| CLAUDE_FOOTPRINT_v4.mq5                                           |
//|                                                                  |
//| Merged v1 + v3. Best of both worlds.                             |
//|                                                                  |
//| Built 2026-05-27 by Radhi & Claude.                              |
//| All code original; commercial .set file used only as parameter   |
//| naming/defaults reference (no commercial code copied).            |
//|                                                                  |
//| v4 features (full list):                                          |
//|   1.  Weighted tick-to-volume inference (move-impact scaled)      |
//|   2.  Price-anchored footprint cells (10 styles)                  |
//|   3.  6-tier intensity cell coloring (3 buyer + 3 seller)         |
//|   4.  3-tier diagonal imbalance detection                         |
//|   5.  Per-style imbalance border colors                           |
//|   6.  POC outline marker (gold thick)                             |
//|   7.  Session Volume Profile (POC + VAH + VAL on chart)           |
//|   8.  Cumulative delta tracking + per-bar delta                   |
//|   9.  Header ticker bar (Sym/TF/Bid/Chg/CumΔ/SIG/SESSION)         |
//|   10. Interactive Button Bar (8 toggles + style cycle)            |
//|   11. Chart Analyst panel — 6-factor scored bias (compact)        |
//|   12. Signal Meter panel — MA + ATR + POC + Delta dial            |
//|   13. Supply & Demand zones (Frost-style swing+ATR)               |
//|   14. Cumulative Delta line mini chart                            |
//|   15. Delta bar strip below candles                               |
//|   16. Summary table (Vol/Δ/CumΔ/POC)                              |
//|   17. Session frame label (Asia/London/NY)                        |
//|   18. Auto-delete old cells (no stale visuals)                    |
//|   19. JSON export to Common\Files for Python brain bridge         |
//|   20. Runtime toggles for all panels (click buttons)              |
//+------------------------------------------------------------------+
#property strict
#property copyright "Radhi & Claude"
#property version   "4.00"
#property indicator_chart_window
#property indicator_plots 0

//====================================================================
// === GLOBAL THEME ===
//====================================================================
input group "=== Global Theme ==="
input int    InpPanelTheme           = 0;        // 0=Dark, 1=Light
input int    InpPanelSkin            = 0;        // skin index (0-25)
input int    InpColorTheme           = 0;        // theme index (0-27)

//====================================================================
// === GENERAL ===
//====================================================================
input group "=== General Settings ==="
input int    InpPricePrecision       = 10;       // tick_size * this = bucket
input int    InpBarsToDisplay        = 15;
input int    InpRefreshRateMs        = 200;

//====================================================================
// === VOLUME & TICK INFERENCE ===
//====================================================================
input group "=== Volume / Tick Inference ==="
input double InpVolumeScaleFactor    = 1.0;
input double InpTickMoveImpact       = 0.45;     // scale per point of move
input long   InpTickInferMin         = 5;
input long   InpTickInferMax         = 5000;
input bool   InpInferTickToVolume    = true;

//====================================================================
// === COLORS ===
//====================================================================
input group "=== Colors — Backgrounds ==="
input color  InpGlobalBgColor        = (color)1511695;
input color  InpPanelBg              = (color)1511695;
input color  InpPanelBorderColor     = (color)3616040;
input color  InpTextColor            = (color)15458780;
input color  InpTextDimColor         = (color)10195340;

input group "=== Colors — Volume Cells (Buyer) ==="
input color  InpCellBuyerHigh        = (color)4891414;
input color  InpCellBuyerMed         = (color)6210850;
input color  InpCellBuyerLow         = (color)8445514;

input group "=== Colors — Volume Cells (Seller) ==="
input color  InpCellSellerHigh       = (color)1842361;
input color  InpCellSellerMed        = (color)4474095;
input color  InpCellSellerLow        = (color)10855932;

input group "=== Colors — Special ==="
input color  InpCellPOCColor         = (color)1428730;
input color  InpCellNeutralColor     = (color)4734007;

//====================================================================
// === INTENSITY / IMBALANCE ===
//====================================================================
input group "=== Intensity Thresholds ==="
input int    InpCellIntensityHigh    = 70;
input int    InpCellIntensityMed     = 40;

input group "=== Imbalance Detection ==="
input double InpImbalanceRatio1      = 2.0;
input double InpImbalanceRatio2      = 3.0;
input double InpImbalanceRatio3      = 4.0;
input int    InpImbalanceMinVolume   = 10;

input group "=== Imbalance Colors — Buyer ==="
input color  InpBuyerImbalance1      = (color)11333510;
input color  InpBuyerImbalance2      = (color)8445514;
input color  InpBuyerImbalance3      = (color)6210850;

input group "=== Imbalance Colors — Seller ==="
input color  InpSellerImbalance1     = (color)13290238;
input color  InpSellerImbalance2     = (color)10855932;
input color  InpSellerImbalance3     = (color)7434744;

//====================================================================
// === LAYOUT ===
//====================================================================
input group "=== Layout ==="
input int    InpBarWidth             = 55;
input int    InpBarSpacing           = 14;
input int    InpHeaderHeight         = 32;
input int    InpDeltaStripHeight     = 20;
input int    InpSummaryHeight        = 80;
input int    InpRightMarginPx        = 200;

//====================================================================
// === FOOTPRINT STYLE ===
//====================================================================
input group "=== Footprint Style ==="
// 0=Minimalist 1=BgCells 2=CandleFrame 3=VPCandle 4=Frameless
// 5=MiddleCandle 6=DeltaCells 7=BidAskProfile 8=BidAskCells 9=HollowVP
input int    InpFootprintStyle       = 1;        // BG Cells default

//====================================================================
// === DELTA BAR ===
//====================================================================
input group "=== Delta Bar ==="
input bool   InpShowDeltaBar         = true;
input color  InpDeltaPositiveColor   = (color)6210850;
input color  InpDeltaNegativeColor   = (color)4474095;

//====================================================================
// === POC OUTLINE ===
//====================================================================
input group "=== POC Outline ==="
input bool   InpShowPOCOutline       = true;

//====================================================================
// === SUPPLY & DEMAND ZONES ===
//====================================================================
input group "=== Supply & Demand Zones ==="
input bool   InpShowZones            = true;
input color  InpZoneSupplyColor      = (color)1908095;
input color  InpZoneDemandColor      = (color)3433750;
input int    InpMaxZones             = 4;
input double InpZoneVolumeMinRatio   = 1.2;
input int    InpFrostZoneATRLen      = 50;
input double InpFrostZoneWidth       = 4.0;
input int    InpFrostSwingLen        = 8;
input int    InpFrostSwingLookback   = 200;

//====================================================================
// === SESSION VP ===
//====================================================================
input group "=== Session VP ==="
input bool   InpShowSessionVP        = true;
input int    InpSessionVPBars        = 50;
input color  InpSVPPOCColor          = (color)1428730;
input color  InpSVPVAHColor          = (color)16631187;
input color  InpSVPVALColor          = (color)16631187;
input double InpValueAreaPct         = 70.0;

//====================================================================
// === TICKER ===
//====================================================================
input group "=== Ticker Bar ==="
input bool   InpShowHeaderBar        = true;
input color  InpTickerBgColor        = (color)2103574;
input color  InpTickerSymbolColor    = (color)1428730;
input color  InpTickerBullColor      = (color)6210850;
input color  InpTickerBearColor      = (color)4474095;

//====================================================================
// === SIGNAL METER ===
//====================================================================
input group "=== Signal Meter ==="
input bool   InpShowSignalMeter      = true;
input int    InpDialSize             = 120;
input color  InpDialBullColor        = (color)6210850;
input color  InpDialBearColor        = (color)4474095;
input color  InpDialNeutralColor     = (color)7563620;

//====================================================================
// === CHART ANALYST ===
//====================================================================
input group "=== Chart Analyst ==="
input bool   InpShowAnalyst          = true;
input int    InpAnalystRefreshSecs   = 5;
input int    InpAnalystWidth         = 280;
input int    InpAnalystHeight        = 230;
input color  InpAnalystAccentColor   = (color)16155195;

//====================================================================
// === CUMULATIVE DELTA LINE ===
//====================================================================
input group "=== Cum Delta Line ==="
input bool   InpShowCumDeltaLine     = true;

//====================================================================
// === SUMMARY TABLE ===
//====================================================================
input group "=== Summary Table ==="
input bool   InpShowSummaryTable     = true;

//====================================================================
// === BUTTON BAR ===
//====================================================================
input group "=== Button Bar ==="
input bool   InpShowButtonBar        = true;

//====================================================================
// === FONTS ===
//====================================================================
input group "=== Fonts ==="
input string InpFontName             = "Segoe UI";
input string InpFontMono             = "Consolas";
input int    InpFontSize             = 12;
input int    InpFontSizeSmall        = 10;
input int    InpFontSizeLarge        = 15;

//====================================================================
// === EXPORT ===
//====================================================================
input group "=== JSON Export ==="
input bool   InpExportToJSON         = true;
input string InpExportFile           = "footprint_cells.json";
input int    InpExportEverySec       = 3;

//====================================================================
// === INTERNALS ===
//====================================================================
input group "=== Internals ==="
input string InpObjPrefix            = "CLFP4_";
input bool   InpVerbose              = false;

//====================================================================
// DATA STRUCTURES
//====================================================================
struct PriceLevel {
   double price;
   long   bid_vol;
   long   ask_vol;
};

struct BarFootprint {
   datetime bar_time;
   double   bar_open, bar_high, bar_low, bar_close;
   PriceLevel levels[];
   double   poc_price;
   long     total_vol;
   long     delta;
   double   cum_delta;
   int      imb_buy_count;
   int      imb_sell_count;
   bool     finalized;
};

struct SDZone {
   double top, bot;
   datetime ts;
   bool is_supply;
   long volume;
};

struct ButtonDef {
   string id;
   string label;
   bool   active;
   int    x, y, w;
};

BarFootprint g_bars[];
SDZone       g_zones[];
ButtonDef    g_buttons[];
double g_cum_delta_running = 0;
double g_prev_mid = 0;
datetime g_cur_bar_time = 0;
double g_svp_poc = 0, g_svp_vah = 0, g_svp_val = 0;
double g_signal_value = 0;
string g_signal_label = "NEUTRAL";
string g_analyst_lines[10];
datetime g_last_analyst_compute = 0;
datetime g_last_render = 0;
datetime g_last_export = 0;
datetime g_last_zones = 0;

// Runtime toggles (mutable from buttons)
bool g_show_footprint;
bool g_show_delta_bar;
bool g_show_summary;
bool g_show_session_vp;
bool g_show_analyst;
bool g_show_meter;
bool g_show_sd_zones;
bool g_show_cum_delta;
int  g_display_style;

//====================================================================
// UTILITIES
//====================================================================
string ObjName(string suffix) { return InpObjPrefix + suffix; }

double PriceBucketSize() {
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if (tick <= 0) tick = _Point * 10;
   return tick * InpPricePrecision;
}

double RoundToBucket(double price) {
   double step = PriceBucketSize();
   return MathRound(price / step) * step;
}

void DeleteAllOurObjects() {
   int total = ObjectsTotal(0);
   for (int i = total - 1; i >= 0; i--) {
      string name = ObjectName(0, i);
      if (StringFind(name, InpObjPrefix) == 0)
         ObjectDelete(0, name);
   }
}

void DeleteObjectsByPrefix(string prefix) {
   int total = ObjectsTotal(0);
   for (int i = total - 1; i >= 0; i--) {
      string name = ObjectName(0, i);
      if (StringFind(name, prefix) == 0) ObjectDelete(0, name);
   }
}

void DrawPriceRect(string name, datetime t1, datetime t2, double p1, double p2,
                   color bg, int width = 1) {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

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
}

void DrawText(string name, int x, int y, string text, color clr,
              int fontsize = 0, string font = "") {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, font == "" ? InpFontName : font);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontsize == 0 ? InpFontSize : fontsize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void DrawHLine(string name, double price, color clr, int width = 1,
               ENUM_LINE_STYLE style = STYLE_SOLID) {
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

void DrawButton(string name, int x, int y, int w, int h, string label,
                bool active) {
   color bg = active ? (color)6584097 : (color)2629905;
   color border = active ? (color)10066329 : (color)4210752;
   DrawRect(name, x, y, w, h, bg, border);
   DrawText(name + "_lbl", x + 6, y + 3, label, InpTextColor, InpFontSizeSmall, InpFontName);
}

//====================================================================
// BAR BUFFER
//====================================================================
int FindBarIndex(datetime bar_time) {
   for (int i = 0; i < ArraySize(g_bars); i++)
      if (g_bars[i].bar_time == bar_time) return i;
   return -1;
}

int FindOrCreateLevel(BarFootprint &bar, double price) {
   double bucket = RoundToBucket(price);
   double step = PriceBucketSize();
   for (int i = 0; i < ArraySize(bar.levels); i++)
      if (MathAbs(bar.levels[i].price - bucket) < step/2.0)
         return i;
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
      g_bars[idx].bar_open = o; g_bars[idx].bar_high = h;
      g_bars[idx].bar_low = l;  g_bars[idx].bar_close = c;
      return;
   }
   int sz = ArraySize(g_bars);
   ArrayResize(g_bars, sz + 1);
   g_bars[sz].bar_time = bar_time;
   g_bars[sz].bar_open = o; g_bars[sz].bar_high = h;
   g_bars[sz].bar_low = l;   g_bars[sz].bar_close = c;
   g_bars[sz].poc_price = 0;
   g_bars[sz].total_vol = 0;
   g_bars[sz].delta = 0;
   g_bars[sz].cum_delta = 0;
   g_bars[sz].imb_buy_count = 0;
   g_bars[sz].imb_sell_count = 0;
   g_bars[sz].finalized = false;
   ArrayResize(g_bars[sz].levels, 0);
   if (sz + 1 > InpBarsToDisplay + 10) {
      int excess = (sz + 1) - (InpBarsToDisplay + 10);
      for (int i = 0; i < ArraySize(g_bars) - excess; i++)
         g_bars[i] = g_bars[i + excess];
      ArrayResize(g_bars, ArraySize(g_bars) - excess);
   }
}

//====================================================================
// IMBALANCE
//====================================================================
int DetectImbalance(BarFootprint &bar, int level_idx, bool buyer_side) {
   if (level_idx < 0 || level_idx >= ArraySize(bar.levels)) return 0;
   double step = PriceBucketSize();
   long ask = bar.levels[level_idx].ask_vol;
   long bid = bar.levels[level_idx].bid_vol;
   double target = buyer_side ? bar.levels[level_idx].price - step
                              : bar.levels[level_idx].price + step;
   long diag_bid = 0, diag_ask = 0;
   for (int j = 0; j < ArraySize(bar.levels); j++) {
      if (MathAbs(bar.levels[j].price - target) < step/2.0) {
         diag_bid = bar.levels[j].bid_vol;
         diag_ask = bar.levels[j].ask_vol;
         break;
      }
   }
   if (buyer_side) {
      if (ask < InpImbalanceMinVolume || diag_bid <= 0) return 0;
      double r = (double)ask / (double)diag_bid;
      if (r >= InpImbalanceRatio3) return 3;
      if (r >= InpImbalanceRatio2) return 2;
      if (r >= InpImbalanceRatio1) return 1;
   } else {
      if (bid < InpImbalanceMinVolume || diag_ask <= 0) return 0;
      double r = (double)bid / (double)diag_ask;
      if (r >= InpImbalanceRatio3) return 3;
      if (r >= InpImbalanceRatio2) return 2;
      if (r >= InpImbalanceRatio1) return 1;
   }
   return 0;
}

color BuyerImbColor(int level) {
   if (level == 3) return InpBuyerImbalance3;
   if (level == 2) return InpBuyerImbalance2;
   if (level == 1) return InpBuyerImbalance1;
   return clrNONE;
}

color SellerImbColor(int level) {
   if (level == 3) return InpSellerImbalance3;
   if (level == 2) return InpSellerImbalance2;
   if (level == 1) return InpSellerImbalance1;
   return clrNONE;
}

color CellColor(long bid_vol, long ask_vol) {
   long total = bid_vol + ask_vol;
   if (total == 0) return InpCellNeutralColor;
   double ask_pct = 100.0 * ask_vol / total;
   double bid_pct = 100.0 * bid_vol / total;
   if (ask_pct >= InpCellIntensityHigh) return InpCellBuyerHigh;
   if (bid_pct >= InpCellIntensityHigh) return InpCellSellerHigh;
   if (ask_pct >= InpCellIntensityMed)  return InpCellBuyerMed;
   if (bid_pct >= InpCellIntensityMed)  return InpCellSellerMed;
   if (ask_pct > 50)                    return InpCellBuyerLow;
   if (bid_pct > 50)                    return InpCellSellerLow;
   return InpCellNeutralColor;
}

//====================================================================
// TICK AGGREGATION (weighted inference)
//====================================================================
void AggregateTick() {
   MqlTick t;
   if (!SymbolInfoTick(_Symbol, t)) return;
   double mid = (t.bid + t.ask) / 2.0;
   long raw_vol = (t.volume > 0) ? (long)t.volume : 1;
   double vol_scaled = (double)raw_vol * InpVolumeScaleFactor;
   if (g_prev_mid > 0 && InpInferTickToVolume) {
      double move_abs = MathAbs(mid - g_prev_mid) / _Point;
      vol_scaled *= (1.0 + move_abs * InpTickMoveImpact);
   }
   long inferred_vol = (long)MathMax((double)InpTickInferMin,
                                      MathMin((double)InpTickInferMax, vol_scaled));

   datetime bar_time = iTime(_Symbol, _Period, 0);
   if (bar_time == 0) return;

   if (bar_time != g_cur_bar_time) {
      int prior_idx = FindBarIndex(g_cur_bar_time);
      if (prior_idx >= 0 && !g_bars[prior_idx].finalized) FinalizeBar(prior_idx);
      g_cur_bar_time = bar_time;
   }
   EnsureBarSlot(bar_time,
                  iOpen(_Symbol, _Period, 0),
                  iHigh(_Symbol, _Period, 0),
                  iLow(_Symbol, _Period, 0),
                  iClose(_Symbol, _Period, 0));
   int bar_idx = FindBarIndex(bar_time);
   if (bar_idx < 0) return;

   bool buy_agg = false, sell_agg = false;
   if (g_prev_mid > 0) {
      if (mid > g_prev_mid) buy_agg = true;
      else if (mid < g_prev_mid) sell_agg = true;
   }
   g_prev_mid = mid;
   if (!buy_agg && !sell_agg) return;

   int lvl = FindOrCreateLevel(g_bars[bar_idx], mid);
   if (buy_agg) g_bars[bar_idx].levels[lvl].ask_vol += inferred_vol;
   else        g_bars[bar_idx].levels[lvl].bid_vol += inferred_vol;
}

void FinalizeBar(int bar_idx) {
   if (bar_idx < 0 || bar_idx >= ArraySize(g_bars)) return;
   long total = 0, max_vol = 0, ask_sum = 0, bid_sum = 0;
   double poc = 0;
   for (int i = 0; i < ArraySize(g_bars[bar_idx].levels); i++) {
      long lt = g_bars[bar_idx].levels[i].bid_vol + g_bars[bar_idx].levels[i].ask_vol;
      total += lt;
      ask_sum += g_bars[bar_idx].levels[i].ask_vol;
      bid_sum += g_bars[bar_idx].levels[i].bid_vol;
      if (lt > max_vol) { max_vol = lt; poc = g_bars[bar_idx].levels[i].price; }
   }
   g_bars[bar_idx].total_vol = total;
   g_bars[bar_idx].poc_price = poc;
   g_bars[bar_idx].delta = ask_sum - bid_sum;
   g_cum_delta_running += (double)g_bars[bar_idx].delta;
   g_bars[bar_idx].cum_delta = g_cum_delta_running;
   int imb_b = 0, imb_s = 0;
   for (int i = 0; i < ArraySize(g_bars[bar_idx].levels); i++) {
      if (DetectImbalance(g_bars[bar_idx], i, true) > 0) imb_b++;
      if (DetectImbalance(g_bars[bar_idx], i, false) > 0) imb_s++;
   }
   g_bars[bar_idx].imb_buy_count = imb_b;
   g_bars[bar_idx].imb_sell_count = imb_s;
   g_bars[bar_idx].finalized = true;
}

//====================================================================
// INDICATORS
//====================================================================
double CalcATR(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return 0;
   double sum = 0;
   for (int i = 1; i <= period && i+1 < copied; i++) {
      double tr1 = r[i].high - r[i].low;
      double tr2 = MathAbs(r[i].high - r[i+1].close);
      double tr3 = MathAbs(r[i].low  - r[i+1].close);
      sum += MathMax(tr1, MathMax(tr2, tr3));
   }
   return sum / period;
}

//====================================================================
// SESSION VP
//====================================================================
void ComputeSessionVP() {
   double prices[]; long vols[]; int n = 0;
   double step = PriceBucketSize();
   int start = MathMax(0, ArraySize(g_bars) - InpSessionVPBars);
   for (int i = start; i < ArraySize(g_bars); i++) {
      for (int j = 0; j < ArraySize(g_bars[i].levels); j++) {
         double p = g_bars[i].levels[j].price;
         long v = g_bars[i].levels[j].bid_vol + g_bars[i].levels[j].ask_vol;
         int idx = -1;
         for (int k = 0; k < n; k++)
            if (MathAbs(prices[k] - p) < step/2.0) { idx = k; break; }
         if (idx < 0) {
            ArrayResize(prices, n+1); ArrayResize(vols, n+1);
            prices[n] = p; vols[n] = v; n++;
         } else vols[idx] += v;
      }
   }
   if (n == 0) { g_svp_poc = 0; g_svp_vah = 0; g_svp_val = 0; return; }
   long max_v = 0, total_v = 0; int max_idx = 0;
   for (int i = 0; i < n; i++) {
      total_v += vols[i];
      if (vols[i] > max_v) { max_v = vols[i]; max_idx = i; }
   }
   g_svp_poc = prices[max_idx];
   long target = (long)(total_v * InpValueAreaPct / 100.0);
   long acc = vols[max_idx]; int hi = max_idx, lo = max_idx;
   while (acc < target && (hi < n - 1 || lo > 0)) {
      long up = (hi < n - 1) ? vols[hi+1] : 0;
      long dn = (lo > 0) ? vols[lo-1] : 0;
      if (up >= dn && hi < n - 1) { hi++; acc += up; }
      else if (lo > 0) { lo--; acc += dn; }
      else if (hi < n - 1) { hi++; acc += up; }
      else break;
   }
   double vah = prices[lo], val = prices[lo];
   for (int i = lo; i <= hi; i++) {
      if (prices[i] > vah) vah = prices[i];
      if (prices[i] < val) val = prices[i];
   }
   g_svp_vah = vah; g_svp_val = val;
}

//====================================================================
// SD ZONES
//====================================================================
void DetectSDZones() {
   ArrayResize(g_zones, 0);
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = MathMin(InpFrostSwingLookback, Bars(_Symbol, _Period) - InpFrostSwingLen * 2);
   int copied = CopyRates(_Symbol, _Period, 0, n, r);
   if (copied < InpFrostSwingLen * 2 + 1) return;
   double sum_v = 0;
   for (int i = 0; i < copied; i++) sum_v += (double)r[i].tick_volume;
   double avg_v = sum_v / copied;
   double atr = CalcATR(r, copied, MathMin(InpFrostZoneATRLen, copied - 2));
   if (atr == 0) atr = _Point * 100;
   double zone_w = atr * InpFrostZoneWidth / 10.0;
   int cnt = 0;
   for (int i = InpFrostSwingLen; i < copied - InpFrostSwingLen; i++) {
      if (cnt >= InpMaxZones) break;
      bool is_high = true, is_low = true;
      for (int k = 1; k <= InpFrostSwingLen; k++) {
         if (r[i].high < r[i-k].high || r[i].high < r[i+k].high) is_high = false;
         if (r[i].low  > r[i-k].low  || r[i].low  > r[i+k].low ) is_low = false;
      }
      if (is_high && r[i].tick_volume > avg_v * InpZoneVolumeMinRatio) {
         int sz = ArraySize(g_zones);
         ArrayResize(g_zones, sz+1);
         g_zones[sz].top = r[i].high;
         g_zones[sz].bot = r[i].high - zone_w;
         g_zones[sz].ts = r[i].time;
         g_zones[sz].is_supply = true;
         g_zones[sz].volume = r[i].tick_volume;
         cnt++;
      } else if (is_low && r[i].tick_volume > avg_v * InpZoneVolumeMinRatio) {
         int sz = ArraySize(g_zones);
         ArrayResize(g_zones, sz+1);
         g_zones[sz].top = r[i].low + zone_w;
         g_zones[sz].bot = r[i].low;
         g_zones[sz].ts = r[i].time;
         g_zones[sz].is_supply = false;
         g_zones[sz].volume = r[i].tick_volume;
         cnt++;
      }
   }
}

//====================================================================
// SIGNAL METER
//====================================================================
void ComputeSignalMeter() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(_Symbol, _Period, 0, 60, r);
   if (copied < 55) { g_signal_value = 0; g_signal_label = "NO DATA"; return; }
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
   double atr = CalcATR(r, copied, 14);
   double rg = r[1].high - r[1].low;
   double atr_score = (rg > atr * 1.15) ? 10 : (rg < atr * 0.85 ? -5 : 0);
   double poc_score = 0;
   if (g_svp_poc > 0) {
      if (r[0].close > g_svp_poc + 0.5) poc_score = +20;
      else if (r[0].close < g_svp_poc - 0.5) poc_score = -20;
   }
   double delta_score = 0;
   if (g_cum_delta_running > 200)   delta_score = +30;
   else if (g_cum_delta_running > 50) delta_score = +15;
   else if (g_cum_delta_running < -200) delta_score = -30;
   else if (g_cum_delta_running < -50) delta_score = -15;
   double total = ma_score + atr_score + poc_score + delta_score;
   total = MathMax(-100, MathMin(100, total));
   g_signal_value = total;
   if (total >= 60)      g_signal_label = "STRONG BUY";
   else if (total >= 25) g_signal_label = "BUY";
   else if (total >= -25) g_signal_label = "NEUTRAL";
   else if (total >= -60) g_signal_label = "SELL";
   else                  g_signal_label = "STRONG SELL";
}

//====================================================================
// CHART ANALYST
//====================================================================
void ComputeAnalyst() {
   if (TimeCurrent() - g_last_analyst_compute < InpAnalystRefreshSecs) return;
   g_last_analyst_compute = TimeCurrent();
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if (CopyRates(_Symbol, _Period, 0, 50, r) < 50) return;
   MqlTick t; SymbolInfoTick(_Symbol, t);
   double prev_close = iClose(_Symbol, PERIOD_D1, 1);
   double chg_pct = (prev_close > 0) ? (t.bid - prev_close) / prev_close * 100.0 : 0;
   double atr = CalcATR(r, 50, 14);

   double ma1 = 0, ma2 = 0;
   for (int i = 1; i <= 9; i++) ma1 += r[i].close;
   for (int i = 1; i <= 21; i++) ma2 += r[i].close;
   ma1 /= 9; ma2 /= 21;
   int f_trend = (ma1 > ma2) ? 1 : (ma1 < ma2 ? -1 : 0);
   double h1_c = iClose(_Symbol, PERIOD_H1, 0);
   double h1_o = iOpen(_Symbol, PERIOD_H1, 4);
   int f_htf = (h1_c > h1_o) ? 1 : (h1_c < h1_o ? -1 : 0);
   int f_flow = (g_cum_delta_running > 50) ? 1 : (g_cum_delta_running < -50 ? -1 : 0);
   int f_vol = 0;
   int last_idx = ArraySize(g_bars) - 1;
   if (last_idx >= 0) {
      long d = g_bars[last_idx].delta;
      f_vol = (d > 0) ? 1 : (d < 0 ? -1 : 0);
   }
   int f_poc = 0;
   if (g_svp_poc > 0)
      f_poc = (t.bid > g_svp_poc + 0.3) ? 1 : (t.bid < g_svp_poc - 0.3 ? -1 : 0);
   double recent_cd = 0;
   int sz = ArraySize(g_bars);
   for (int i = MathMax(0, sz - 5); i < sz; i++) recent_cd += (double)g_bars[i].delta;
   int f_tape = (recent_cd > 30) ? 1 : (recent_cd < -30 ? -1 : 0);
   int score = f_trend + f_htf + f_flow + f_vol + f_poc + f_tape;
   string bias = "NEUTRAL";
   if (score >= 4)       bias = "STRONG BULL";
   else if (score >= 2)  bias = "BULL";
   else if (score <= -4) bias = "STRONG BEAR";
   else if (score <= -2) bias = "BEAR";

   g_analyst_lines[0] = StringFormat("%s  %s   %s%.2f%%",
                                      _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period),
                                      chg_pct >= 0 ? "+" : "", chg_pct);
   g_analyst_lines[1] = StringFormat("TREND   : %s   (MA9/21)",
                                      f_trend>0?"BULL":(f_trend<0?"BEAR":"FLAT"));
   g_analyst_lines[2] = StringFormat("HTF (H1): %s   ATR $%.2f",
                                      f_htf>0?"BULL":(f_htf<0?"BEAR":"FLAT"), atr);
   g_analyst_lines[3] = StringFormat("FLOW    : CumΔ %+.0f → %s",
                                      g_cum_delta_running,
                                      f_flow>0?"BUY pressure":(f_flow<0?"SELL pressure":"balanced"));
   g_analyst_lines[4] = StringFormat("LAST BAR: Δ %+d → %s",
                                      last_idx>=0?(int)g_bars[last_idx].delta:0,
                                      f_vol>0?"buyer dom":(f_vol<0?"seller dom":"balanced"));
   g_analyst_lines[5] = StringFormat("POC     : %s  (POC %.2f)",
                                      f_poc>0?"above":(f_poc<0?"below":"at"), g_svp_poc);
   g_analyst_lines[6] = StringFormat("TAPE (5): %+.0f cumΔ → %s",
                                      recent_cd, f_tape>0?"bull tape":(f_tape<0?"bear tape":"neutral"));
   g_analyst_lines[7] = "──────────────────────────";
   g_analyst_lines[8] = StringFormat("CONSENSUS: %s   (%+d/6)", bias, score);
   g_analyst_lines[9] = "";
}

//====================================================================
// RENDER — FOOTPRINT CELLS (10 styles + delete old)
//====================================================================
void RenderFootprint() {
   if (!g_show_footprint) {
      DeleteObjectsByPrefix(InpObjPrefix + "c_");
      DeleteObjectsByPrefix(InpObjPrefix + "t_");
      DeleteObjectsByPrefix(InpObjPrefix + "cb_");
      DeleteObjectsByPrefix(InpObjPrefix + "ca_");
      DeleteObjectsByPrefix(InpObjPrefix + "tb_");
      DeleteObjectsByPrefix(InpObjPrefix + "ta_");
      DeleteObjectsByPrefix(InpObjPrefix + "poc_");
      return;
   }

   // Delete ALL footprint cells/texts before redraw — no stale cells
   int total_objs = ObjectsTotal(0);
   for (int i = total_objs - 1; i >= 0; i--) {
      string nm = ObjectName(0, i);
      if (StringFind(nm, InpObjPrefix + "c_") == 0  || StringFind(nm, InpObjPrefix + "t_") == 0
       || StringFind(nm, InpObjPrefix + "cb_") == 0 || StringFind(nm, InpObjPrefix + "ca_") == 0
       || StringFind(nm, InpObjPrefix + "tb_") == 0 || StringFind(nm, InpObjPrefix + "ta_") == 0
       || StringFind(nm, InpObjPrefix + "poc_") == 0)
         ObjectDelete(0, nm);
   }

   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpBarsToDisplay);
   int period_sec = PeriodSeconds(_Period);
   double step = PriceBucketSize();

   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      if (ArraySize(bar.levels) == 0) continue;

      datetime t1 = bar.bar_time + (datetime)(period_sec * 0.15);
      datetime t2 = bar.bar_time + (datetime)(period_sec * 0.85);
      datetime t_mid = bar.bar_time + (datetime)(period_sec * 0.50);
      datetime t_bid = bar.bar_time + (datetime)(period_sec * 0.30);
      datetime t_ask = bar.bar_time + (datetime)(period_sec * 0.60);

      double pmin = bar.levels[0].price, pmax = bar.levels[0].price;
      for (int i = 1; i < ArraySize(bar.levels); i++) {
         if (bar.levels[i].price < pmin) pmin = bar.levels[i].price;
         if (bar.levels[i].price > pmax) pmax = bar.levels[i].price;
      }
      int n_rows = (int)MathRound((pmax - pmin) / step) + 1;

      for (int r = 0; r < n_rows; r++) {
         double price = pmax - r * step;
         int idx = -1;
         for (int i = 0; i < ArraySize(bar.levels); i++)
            if (MathAbs(bar.levels[i].price - price) < step/2.0) { idx = i; break; }
         long bid_v = (idx >= 0) ? bar.levels[idx].bid_vol : 0;
         long ask_v = (idx >= 0) ? bar.levels[idx].ask_vol : 0;
         bool is_poc = (MathAbs(price - bar.poc_price) < step/2.0 && bar.finalized);
         double p_top = price + step/2.0, p_bot = price - step/2.0;
         int imb_b = (idx >= 0) ? DetectImbalance(bar, idx, true) : 0;
         int imb_s = (idx >= 0) ? DetectImbalance(bar, idx, false) : 0;

         color cell_col = CellColor(bid_v, ask_v);
         color txt_col = is_poc ? InpCellPOCColor : InpTextColor;
         int fontsz = (imb_b >= 2 || imb_s >= 2) ? InpFontSize : InpFontSizeSmall;

         string c_name = ObjName(StringFormat("c_%d_%d", b, r));
         int style = g_display_style;

         if (style == 0) {
            // S1 MINIMALIST — text only
            string txt = StringFormat("%d × %d", (int)bid_v, (int)ask_v);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t_mid, price, txt, txt_col, fontsz);
         }
         else if (style == 1 || style == 3) {
            // S2/S4 BG CELLS / VP CANDLE
            DrawPriceRect(c_name, t1, t2, p_top, p_bot, cell_col);
            if (imb_b > 0) {
               ObjectSetInteger(0, c_name, OBJPROP_COLOR, BuyerImbColor(imb_b));
               ObjectSetInteger(0, c_name, OBJPROP_WIDTH, 2);
            } else if (imb_s > 0) {
               ObjectSetInteger(0, c_name, OBJPROP_COLOR, SellerImbColor(imb_s));
               ObjectSetInteger(0, c_name, OBJPROP_WIDTH, 2);
            }
            string txt = StringFormat("%d × %d", (int)bid_v, (int)ask_v);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t1, price, txt, txt_col, fontsz);
         }
         else if (style == 6) {
            // S7 DELTA CELLS — single Δ number
            long d = ask_v - bid_v;
            color dc = d > 0 ? InpDeltaPositiveColor : (d < 0 ? InpDeltaNegativeColor : InpCellNeutralColor);
            DrawPriceRect(c_name, t1, t2, p_top, p_bot, dc);
            string txt = (d == 0) ? "0" : StringFormat("%+d", (int)d);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t_mid, price, txt, txt_col, fontsz+1);
         }
         else if (style == 7 || style == 8) {
            // S8/S9 BID×ASK split
            long total = bid_v + ask_v;
            color bid_bg = InpCellNeutralColor, ask_bg = InpCellNeutralColor;
            if (total > 0) {
               double bp = 100.0 * bid_v / total, ap = 100.0 * ask_v / total;
               if (bp >= InpCellIntensityHigh)      bid_bg = InpCellSellerHigh;
               else if (bp >= InpCellIntensityMed)  bid_bg = InpCellSellerMed;
               else if (bid_v > 0)                   bid_bg = InpCellSellerLow;
               if (ap >= InpCellIntensityHigh)      ask_bg = InpCellBuyerHigh;
               else if (ap >= InpCellIntensityMed)  ask_bg = InpCellBuyerMed;
               else if (ask_v > 0)                   ask_bg = InpCellBuyerLow;
            }
            string bid_name = ObjName(StringFormat("cb_%d_%d", b, r));
            string ask_name = ObjName(StringFormat("ca_%d_%d", b, r));
            DrawPriceRect(bid_name, t1, t_mid, p_top, p_bot, bid_bg);
            DrawPriceRect(ask_name, t_mid, t2, p_top, p_bot, ask_bg);
            if (imb_s > 0) {
               ObjectSetInteger(0, bid_name, OBJPROP_COLOR, SellerImbColor(imb_s));
               ObjectSetInteger(0, bid_name, OBJPROP_WIDTH, 2);
            }
            if (imb_b > 0) {
               ObjectSetInteger(0, ask_name, OBJPROP_COLOR, BuyerImbColor(imb_b));
               ObjectSetInteger(0, ask_name, OBJPROP_WIDTH, 2);
            }
            DrawPriceText(ObjName(StringFormat("tb_%d_%d", b, r)),
                          t_bid, price, IntegerToString((int)bid_v), txt_col, fontsz);
            DrawPriceText(ObjName(StringFormat("ta_%d_%d", b, r)),
                          t_ask, price, IntegerToString((int)ask_v), txt_col, fontsz);
         }
         else {
            // S3/S5/S6/S10 — default to BG CELLS
            DrawPriceRect(c_name, t1, t2, p_top, p_bot, cell_col);
            string txt = StringFormat("%d × %d", (int)bid_v, (int)ask_v);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t1, price, txt, txt_col, fontsz);
         }

         if (is_poc && InpShowPOCOutline) {
            string poc_name = ObjName(StringFormat("poc_%d", b));
            DrawPriceRect(poc_name, bar.bar_time,
                          bar.bar_time + (datetime)(period_sec * 0.12),
                          p_top, p_bot, InpCellPOCColor);
         }
      }
   }
}

//====================================================================
// RENDER — SD ZONES
//====================================================================
void RenderSDZones() {
   if (!g_show_sd_zones) { DeleteObjectsByPrefix(InpObjPrefix + "sd_"); return; }
   datetime t_end = TimeCurrent() + PeriodSeconds(_Period) * 30;
   for (int i = 0; i < ArraySize(g_zones); i++) {
      string name = ObjName(StringFormat("sd_%d", i));
      color c = g_zones[i].is_supply ? InpZoneSupplyColor : InpZoneDemandColor;
      DrawPriceRect(name, g_zones[i].ts, t_end, g_zones[i].top, g_zones[i].bot, c);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_ZORDER, -10);
   }
}

//====================================================================
// RENDER — SVP LINES
//====================================================================
void RenderSVPLines() {
   if (!g_show_session_vp) {
      ObjectDelete(0, ObjName("svp_poc"));
      ObjectDelete(0, ObjName("svp_vah"));
      ObjectDelete(0, ObjName("svp_val"));
      return;
   }
   if (g_svp_poc > 0) DrawHLine(ObjName("svp_poc"), g_svp_poc, InpSVPPOCColor, 2, STYLE_SOLID);
   if (g_svp_vah > 0) DrawHLine(ObjName("svp_vah"), g_svp_vah, InpSVPVAHColor, 1, STYLE_DASH);
   if (g_svp_val > 0) DrawHLine(ObjName("svp_val"), g_svp_val, InpSVPVALColor, 1, STYLE_DASH);
}

//====================================================================
// RENDER — TICKER BAR
//====================================================================
void RenderTickerBar() {
   if (!InpShowHeaderBar) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   MqlTick t; SymbolInfoTick(_Symbol, t);
   int H = InpHeaderHeight;
   DrawRect(ObjName("hdr_bg"), 5, 5, (int)chart_w - 10, H, InpTickerBgColor);
   string sym_tf = _Symbol + "  " + EnumToString((ENUM_TIMEFRAMES)_Period);
   DrawText(ObjName("hdr_sym"), 15, 12, sym_tf, InpTickerSymbolColor, InpFontSizeLarge, InpFontName);

   double prev_d = iClose(_Symbol, PERIOD_D1, 1);
   double chg = (prev_d > 0) ? (t.bid - prev_d) / prev_d * 100.0 : 0;
   color chg_col = chg >= 0 ? InpTickerBullColor : InpTickerBearColor;
   string bid_txt = StringFormat("%.2f  %s%.2f%%", t.bid, chg>=0?"+":"", chg);
   DrawText(ObjName("hdr_bid"), 200, 14, bid_txt, chg_col, InpFontSize, InpFontMono);

   string cumd = StringFormat("CumΔ %+.0f", g_cum_delta_running);
   color cd_col = g_cum_delta_running >= 0 ? InpTickerBullColor : InpTickerBearColor;
   DrawText(ObjName("hdr_cumd"), 380, 14, cumd, cd_col, InpFontSize, InpFontMono);

   DrawText(ObjName("hdr_bars"), 520, 14,
            StringFormat("Bars %d  POC %.2f", ArraySize(g_bars), g_svp_poc),
            InpTextColor, InpFontSize, InpFontMono);

   color sm_col = g_signal_value >= 25 ? InpDialBullColor :
                  (g_signal_value <= -25 ? InpDialBearColor : InpDialNeutralColor);
   DrawText(ObjName("hdr_sig"), 740, 14,
            StringFormat("SIG %+.0f %s", g_signal_value, g_signal_label),
            sm_col, InpFontSize, InpFontMono);

   datetime now = TimeCurrent();
   MqlDateTime tt; TimeToStruct(now, tt);
   int h = tt.hour;
   string current_session = (h>=14 && h<22) ? "NEW YORK" : ((h>=8 && h<16) ? "LONDON" : "ASIA");
   DrawText(ObjName("hdr_sess"), 920, 14, "SESSION " + current_session,
            InpAnalystAccentColor, InpFontSize, InpFontName);
}

//====================================================================
// RENDER — SIGNAL METER
//====================================================================
void RenderSignalMeter() {
   if (!g_show_meter) {
      DeleteObjectsByPrefix(InpObjPrefix + "sm_");
      return;
   }
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int w = InpDialSize + 60, h = InpDialSize + 30;
   int x = (int)chart_w - w - 10;
   int y = (InpShowHeaderBar ? InpHeaderHeight + 15 : 15) + 25;  // below button bar
   DrawRect(ObjName("sm_bg"), x, y, w, h, InpPanelBg, InpPanelBorderColor);
   DrawText(ObjName("sm_title"), x + 8, y + 4, "SIGNAL METER", InpAnalystAccentColor, InpFontSize, InpFontName);
   int bar_x = x + 8, bar_y = y + 30, bar_w = w - 16, bar_h = 18;
   DrawRect(ObjName("sm_track"), bar_x, bar_y, bar_w, bar_h, (color)2103574);
   int center_x = bar_x + bar_w / 2;
   color c = g_signal_value >= 60 ? clrLime :
             (g_signal_value <= -60 ? clrRed :
              (g_signal_value >= 25 ? InpDialBullColor :
               (g_signal_value <= -25 ? InpDialBearColor : InpDialNeutralColor)));
   int fill_w = (int)(g_signal_value / 100.0 * (bar_w / 2));
   if (fill_w > 0)
      DrawRect(ObjName("sm_fill"), center_x, bar_y, fill_w, bar_h, c);
   else if (fill_w < 0)
      DrawRect(ObjName("sm_fill"), center_x + fill_w, bar_y, -fill_w, bar_h, c);
   DrawText(ObjName("sm_val"), x + 8, y + 55,
            StringFormat("%+.0f  %s", g_signal_value, g_signal_label),
            c, InpFontSizeLarge, InpFontName);
}

//====================================================================
// RENDER — CHART ANALYST (compact bottom-right)
//====================================================================
void RenderAnalyst() {
   if (!g_show_analyst) {
      DeleteObjectsByPrefix(InpObjPrefix + "an_");
      return;
   }
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int w = InpAnalystWidth, h = InpAnalystHeight;
   int x = (int)chart_w - w - 10;
   int y = (int)chart_h - h - (InpShowSummaryTable ? InpSummaryHeight + 30 : 30);
   DrawRect(ObjName("an_bg"), x, y, w, h, InpPanelBg, InpPanelBorderColor);
   DrawText(ObjName("an_title"), x + 8, y + 4, "CHART ANALYST",
            InpAnalystAccentColor, InpFontSize, InpFontName);
   for (int i = 0; i < 10; i++) {
      if (StringLen(g_analyst_lines[i]) == 0) continue;
      color cl = InpTextColor;
      if (StringFind(g_analyst_lines[i], "BULL") >= 0) cl = InpTickerBullColor;
      else if (StringFind(g_analyst_lines[i], "BEAR") >= 0) cl = InpTickerBearColor;
      else if (StringFind(g_analyst_lines[i], "CONSENSUS") >= 0) cl = InpCellPOCColor;
      DrawText(ObjName(StringFormat("an_l_%d", i)),
               x + 8, y + 22 + i * 18, g_analyst_lines[i],
               cl, InpFontSizeSmall, InpFontMono);
   }
}

//====================================================================
// RENDER — CUMULATIVE DELTA LINE
//====================================================================
void RenderCumDeltaLine() {
   if (!g_show_cum_delta) {
      DeleteObjectsByPrefix(InpObjPrefix + "cd_");
      return;
   }
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int w = InpAnalystWidth, h = 60;
   int x = (int)chart_w - w - 10;
   int y = (int)chart_h - h - (InpShowSummaryTable ? InpSummaryHeight + 30 : 30)
                              - InpAnalystHeight - 10;
   if (y < InpHeaderHeight + 100) return;
   DrawRect(ObjName("cd_bg"), x, y, w, h, InpPanelBg, InpPanelBorderColor);
   DrawText(ObjName("cd_title"), x + 6, y + 4, "CUMULATIVE Δ", InpTextColor, InpFontSizeSmall);

   int sz = ArraySize(g_bars);
   if (sz < 2) return;
   double mn = g_bars[0].cum_delta, mx = g_bars[0].cum_delta;
   for (int i = 1; i < sz; i++) {
      if (g_bars[i].cum_delta < mn) mn = g_bars[i].cum_delta;
      if (g_bars[i].cum_delta > mx) mx = g_bars[i].cum_delta;
   }
   double rng = MathMax(mx - mn, 1);
   int pw = w - 10, ph = h - 22;
   int x0 = x + 5, y0 = y + 18;
   double step = (double)pw / sz;
   for (int i = 0; i < sz; i++) {
      double v = g_bars[i].cum_delta;
      int yy = y0 + ph - (int)((v - mn) / rng * ph);
      int xx = x0 + (int)(i * step);
      color cc = (v >= 0) ? InpTickerBullColor : InpTickerBearColor;
      DrawRect(ObjName(StringFormat("cd_p_%d", i)), xx, yy, 2, 2, cc);
   }
}

//====================================================================
// RENDER — DELTA STRIP (pixel-based below cells)
//====================================================================
void RenderDeltaStrip() {
   if (!g_show_delta_bar) {
      DeleteObjectsByPrefix(InpObjPrefix + "d_");
      DeleteObjectsByPrefix(InpObjPrefix + "dt_");
      return;
   }
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpBarsToDisplay);
   int start_x = (int)chart_w - InpRightMarginPx - visible * InpBarWidth - 10;
   int y = (int)chart_h - InpSummaryHeight - InpDeltaStripHeight - 5;
   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      int bar_x = start_x + b * InpBarWidth;
      color c = (bar.delta >= 0) ? InpDeltaPositiveColor : InpDeltaNegativeColor;
      DrawRect(ObjName(StringFormat("d_%d", b)),
               bar_x + 4, y, InpBarWidth - 8, InpDeltaStripHeight - 4, c);
      DrawText(ObjName(StringFormat("dt_%d", b)),
               bar_x + 6, y + 2, StringFormat("%+d", (int)bar.delta),
               clrWhite, InpFontSizeSmall);
   }
}

//====================================================================
// RENDER — SUMMARY TABLE (bottom)
//====================================================================
void RenderSummaryTable() {
   if (!g_show_summary) {
      DeleteObjectsByPrefix(InpObjPrefix + "sum_");
      DeleteObjectsByPrefix(InpObjPrefix + "sv_");
      DeleteObjectsByPrefix(InpObjPrefix + "sd_t");
      DeleteObjectsByPrefix(InpObjPrefix + "sc_");
      DeleteObjectsByPrefix(InpObjPrefix + "sp_");
      return;
   }
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int n_bars = ArraySize(g_bars);
   int visible = MathMin(n_bars, InpBarsToDisplay);
   int start_x = (int)chart_w - InpRightMarginPx - visible * InpBarWidth - 10;
   int y0 = (int)chart_h - InpSummaryHeight - 5;
   int row_h = 18;
   DrawText(ObjName("sum_lbl_vol"),   start_x - 70, y0,            "Vol",  InpTextColor, InpFontSizeSmall);
   DrawText(ObjName("sum_lbl_delta"), start_x - 70, y0 + row_h,    "Δ",    InpTextColor, InpFontSizeSmall);
   DrawText(ObjName("sum_lbl_cum"),   start_x - 70, y0 + row_h*2,  "CumΔ", InpTextColor, InpFontSizeSmall);
   DrawText(ObjName("sum_lbl_poc"),   start_x - 70, y0 + row_h*3,  "POC",  InpTextColor, InpFontSizeSmall);
   for (int b = 0; b < visible; b++) {
      int bar_idx = n_bars - visible + b;
      if (bar_idx < 0) continue;
      BarFootprint bar = g_bars[bar_idx];
      int bar_x = start_x + b * InpBarWidth;
      DrawText(ObjName(StringFormat("sv_%d", b)),
               bar_x + 4, y0, StringFormat("%d", (int)bar.total_vol),
               InpTextColor, InpFontSizeSmall);
      DrawText(ObjName(StringFormat("sd_t%d", b)),
               bar_x + 4, y0 + row_h, StringFormat("%+d", (int)bar.delta),
               (bar.delta >= 0) ? InpTickerBullColor : InpTickerBearColor, InpFontSizeSmall);
      DrawText(ObjName(StringFormat("sc_%d", b)),
               bar_x + 4, y0 + row_h*2, StringFormat("%+.0f", bar.cum_delta),
               (bar.cum_delta >= 0) ? InpTickerBullColor : InpTickerBearColor, InpFontSizeSmall);
      DrawText(ObjName(StringFormat("sp_%d", b)),
               bar_x + 4, y0 + row_h*3, StringFormat("%.2f", bar.poc_price),
               InpCellPOCColor, InpFontSizeSmall);
   }
}

//====================================================================
// RENDER — BUTTON BAR (interactive toggles)
//====================================================================
void RenderButtonBar() {
   if (!InpShowButtonBar) return;
   int y = (InpShowHeaderBar ? InpHeaderHeight + 8 : 8);
   int x = 10, h = 22;
   struct BtnSpec { string id; string label; bool active; int w; };
   BtnSpec specs[9];
   specs[0].id="btn_fp";      specs[0].label="FOOTPRINT"; specs[0].active=g_show_footprint;   specs[0].w=90;
   specs[1].id="btn_delta";   specs[1].label="DELTA";     specs[1].active=g_show_delta_bar;   specs[1].w=65;
   specs[2].id="btn_summary"; specs[2].label="SUMMARY";   specs[2].active=g_show_summary;     specs[2].w=80;
   specs[3].id="btn_svp";     specs[3].label="SVP";       specs[3].active=g_show_session_vp;  specs[3].w=50;
   specs[4].id="btn_analyst"; specs[4].label="ANALYST";   specs[4].active=g_show_analyst;     specs[4].w=80;
   specs[5].id="btn_meter";   specs[5].label="METER";     specs[5].active=g_show_meter;       specs[5].w=70;
   specs[6].id="btn_sd";      specs[6].label="S/D";       specs[6].active=g_show_sd_zones;    specs[6].w=55;
   specs[7].id="btn_cumd";    specs[7].label="CUMΔ";      specs[7].active=g_show_cum_delta;   specs[7].w=55;
   specs[8].id="btn_style";   specs[8].label="ST "+IntegerToString(g_display_style); specs[8].active=true; specs[8].w=55;
   ArrayResize(g_buttons, 9);
   for (int i = 0; i < 9; i++) {
      DrawButton(ObjName(specs[i].id), x, y, specs[i].w, h, specs[i].label, specs[i].active);
      g_buttons[i].id = specs[i].id;
      g_buttons[i].label = specs[i].label;
      g_buttons[i].active = specs[i].active;
      g_buttons[i].x = x; g_buttons[i].y = y; g_buttons[i].w = specs[i].w;
      x += specs[i].w + 4;
   }
}

void HandleButtonClick(string id) {
   if      (id == "btn_fp")      g_show_footprint  = !g_show_footprint;
   else if (id == "btn_delta")   g_show_delta_bar  = !g_show_delta_bar;
   else if (id == "btn_summary") g_show_summary    = !g_show_summary;
   else if (id == "btn_svp")     g_show_session_vp = !g_show_session_vp;
   else if (id == "btn_analyst") g_show_analyst    = !g_show_analyst;
   else if (id == "btn_meter")   g_show_meter      = !g_show_meter;
   else if (id == "btn_sd")      g_show_sd_zones   = !g_show_sd_zones;
   else if (id == "btn_cumd")    g_show_cum_delta  = !g_show_cum_delta;
   else if (id == "btn_style")   g_display_style   = (g_display_style + 1) % 10;
   Print("[FP4] toggle ", id, " — style=", g_display_style);
}

//====================================================================
// JSON EXPORT
//====================================================================
void ExportJSON() {
   if (!InpExportToJSON) return;
   if (TimeCurrent() - g_last_export < InpExportEverySec) return;
   g_last_export = TimeCurrent();
   int handle = FileOpen(InpExportFile, FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
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
   json += "  \"display_style\": " + IntegerToString(g_display_style) + ",\n";
   json += "  \"sd_zones\": [\n";
   for (int i = 0; i < ArraySize(g_zones); i++) {
      json += StringFormat("    {\"top\":%.2f,\"bot\":%.2f,\"is_supply\":%s,\"vol\":%d}",
                            g_zones[i].top, g_zones[i].bot,
                            g_zones[i].is_supply ? "true" : "false",
                            (int)g_zones[i].volume);
      if (i < ArraySize(g_zones) - 1) json += ",";
      json += "\n";
   }
   json += "  ],\n";
   json += "  \"bars\": [\n";
   int n = ArraySize(g_bars);
   int start = MathMax(0, n - 10);
   for (int b = start; b < n; b++) {
      json += StringFormat("    {\"ts\":%d,\"o\":%.2f,\"h\":%.2f,\"l\":%.2f,\"c\":%.2f,"
                            "\"vol\":%d,\"delta\":%d,\"cum_delta\":%.0f,\"poc\":%.2f,"
                            "\"imb_buy\":%d,\"imb_sell\":%d,\"finalized\":%s}",
                            (int)g_bars[b].bar_time,
                            g_bars[b].bar_open, g_bars[b].bar_high,
                            g_bars[b].bar_low, g_bars[b].bar_close,
                            (int)g_bars[b].total_vol, (int)g_bars[b].delta,
                            g_bars[b].cum_delta, g_bars[b].poc_price,
                            g_bars[b].imb_buy_count, g_bars[b].imb_sell_count,
                            g_bars[b].finalized ? "true" : "false");
      if (b < n - 1) json += ",";
      json += "\n";
   }
   json += "  ]\n}\n";
   FileWriteString(handle, json);
   FileClose(handle);
}

//====================================================================
// MAIN RENDER
//====================================================================
void RenderAll() {
   datetime cur = iTime(_Symbol, _Period, 0);
   int idx = FindBarIndex(cur);
   if (idx >= 0 && !g_bars[idx].finalized) {
      long total = 0, max_v = 0, ask_sum = 0, bid_sum = 0;
      double poc = 0;
      for (int j = 0; j < ArraySize(g_bars[idx].levels); j++) {
         long lt = g_bars[idx].levels[j].bid_vol + g_bars[idx].levels[j].ask_vol;
         total += lt; ask_sum += g_bars[idx].levels[j].ask_vol; bid_sum += g_bars[idx].levels[j].bid_vol;
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
   if (TimeCurrent() - g_last_zones > 30) {
      DetectSDZones();
      g_last_zones = TimeCurrent();
   }
   RenderTickerBar();
   RenderButtonBar();
   RenderFootprint();
   RenderSVPLines();
   RenderSDZones();
   RenderSignalMeter();
   RenderAnalyst();
   RenderCumDeltaLine();
   RenderDeltaStrip();
   RenderSummaryTable();
   ExportJSON();
   ChartRedraw(0);
}

//====================================================================
// BACKFILL
//====================================================================
void BackfillBars() {
   int n = MathMin(InpBarsToDisplay, Bars(_Symbol, _Period) - 1);
   double step = PriceBucketSize();
   for (int i = n; i >= 1; i--) {
      datetime t = iTime(_Symbol, _Period, i);
      double o = iOpen(_Symbol, _Period, i);
      double h = iHigh(_Symbol, _Period, i);
      double l = iLow(_Symbol, _Period, i);
      double c = iClose(_Symbol, _Period, i);
      long v = iVolume(_Symbol, _Period, i);
      EnsureBarSlot(t, o, h, l, c);
      int idx = FindBarIndex(t);
      if (idx < 0) continue;
      long per = v / 5;
      for (int k = -2; k <= 2; k++) {
         double p = RoundToBucket(c + k * step);
         int li = FindOrCreateLevel(g_bars[idx], p);
         if (c > o) g_bars[idx].levels[li].ask_vol += per;
         else       g_bars[idx].levels[li].bid_vol += per;
      }
      FinalizeBar(idx);
   }
}

//====================================================================
// EVENTS
//====================================================================
int OnInit() {
   Print("════════════════════════════════════════════");
   Print("[CLAUDE_FOOTPRINT v4.00] ONLINE on ", _Symbol);
   Print("  Merged v1+v3 — all features in one file");
   Print("  Bars=", InpBarsToDisplay, " precision=", InpPricePrecision,
         " bucket=$", DoubleToString(PriceBucketSize(), 4));
   Print("  Style=", InpFootprintStyle, "  Refresh=", InpRefreshRateMs, "ms");
   Print("  Imb ratios: ", InpImbalanceRatio1, "/", InpImbalanceRatio2, "/", InpImbalanceRatio3);
   Print("════════════════════════════════════════════");
   // init runtime toggles from inputs
   g_show_footprint  = true;
   g_show_delta_bar  = InpShowDeltaBar;
   g_show_summary    = InpShowSummaryTable;
   g_show_session_vp = InpShowSessionVP;
   g_show_analyst    = InpShowAnalyst;
   g_show_meter      = InpShowSignalMeter;
   g_show_sd_zones   = InpShowZones;
   g_show_cum_delta  = InpShowCumDeltaLine;
   g_display_style   = InpFootprintStyle;
   BackfillBars();
   g_cur_bar_time = iTime(_Symbol, _Period, 0);
   EventSetMillisecondTimer(InpRefreshRateMs);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   EventKillTimer();
   DeleteAllOurObjects();
   Print("[CLAUDE_FOOTPRINT v4] offline — reason ", reason);
}

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[]) {
   AggregateTick();
   return rates_total;
}

void OnTimer() {
   datetime now = TimeCurrent();
   if (now - g_last_render >= (InpRefreshRateMs / 1000.0)) {
      RenderAll();
      g_last_render = now;
   }
}

void OnChartEvent(const int id, const long &lparam,
                  const double &dparam, const string &sparam) {
   if (id == CHARTEVENT_OBJECT_CLICK) {
      for (int i = 0; i < ArraySize(g_buttons); i++) {
         if (sparam == ObjName(g_buttons[i].id)
          || sparam == ObjName(g_buttons[i].id) + "_lbl") {
            HandleButtonClick(g_buttons[i].id);
            RenderAll();
            return;
         }
      }
   }
}
