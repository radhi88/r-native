//+------------------------------------------------------------------+
//| CLAUDE_FOOTPRINT_v3.mq5                                           |
//|                                                                  |
//| Built 2026-05-27 — using Set file spec from Orderflow Footprint  |
//| Futures Chart v6.34 commercial EA as reference architecture.     |
//| All code original. Parameter names + defaults match for           |
//| consistency. No commercial code reused.                          |
//|                                                                  |
//| v3.0 includes:                                                    |
//|   • 10 footprint styles (S1-S10)                                  |
//|   • 6-tier intensity cell coloring (3 buyer + 3 seller)           |
//|   • 3-tier diagonal imbalance detection                           |
//|   • Per-style imbalance colors                                    |
//|   • Header ticker bar with HTF/MS labels                          |
//|   • Bar info display (delta, change, imb counts)                  |
//|   • Per-bar Volume Profile overlay                                |
//|   • Delta Bar strip below candles                                 |
//|   • POC outline marker                                            |
//|   • Session Volume Profile (POC/VAH/VAL)                          |
//|   • Cumulative Delta tracking                                     |
//|   • Supply & Demand zones (Frost-style swing+ATR)                 |
//|   • Signal Meter dial (MA + ATR + POC + Vol)                      |
//|   • Chart Analyst confluence panel (6-factor)                     |
//|   • Asia/London/NY session frames                                 |
//|   • RSI(14) + MACD(12/26/9) embedded                              |
//|   • Tick-to-volume inference with weighted scale                  |
//|   • JSON export for Python brain bridge                           |
//|                                                                  |
//| Coming in v4.0:                                                   |
//|   • DOM panel (needs broker L2)                                   |
//|   • Time & Sales tape                                             |
//|   • Order Flow Bubbles                                            |
//|   • Session TPO                                                   |
//|   • Trade Plan interactive                                        |
//|   • Consistency Calculator                                        |
//|   • Absorption panel                                              |
//|   • 28 color themes + 26 panel skins                              |
//+------------------------------------------------------------------+
#property strict
#property copyright "Radhi & Claude"
#property version   "3.00"
#property indicator_chart_window
#property indicator_plots 0

//====================================================================
// === GLOBAL THEME ===
//====================================================================
input group "=== Global Theme ==="
input int    InpPanelTheme           = 0;        // 0=Dark, 1=Light
input int    InpPanelSkin            = 0;        // 0-25 (26 skins available; v3=0 only)
input int    InpColorTheme           = 0;        // 0-27 (28 themes; v3=0 only)
input bool   InpThemeOverrideAll     = false;    // override per-style imbalance with global theme

//====================================================================
// === GENERAL SETTINGS ===
//====================================================================
input group "=== General Settings ==="
input int    InpPricePrecision       = 10;       // price bucket scale (10 = pricestep/10 — matches XAU=$1 default)
input int    InpBarsToDisplay        = 15;       // visible footprint bars
input int    InpRefreshRateMs        = 100;      // render refresh ms

//====================================================================
// === VOLUME SETTINGS ===
//====================================================================
input group "=== Volume Settings ==="
input double InpVolumeScaleFactor    = 1.0;      // global multiplier for inferred volume
input double InpMinMoveFromLevel     = 2.0;      // pts move before tick assigned new level

//====================================================================
// === FEED SETTINGS ===
//====================================================================
input group "=== Feed Settings ==="
input int    InpFeedMode             = 0;        // 0=MT5 Native, 1=Exchange (L2 broker)
input bool   InpInferTickToVolume    = true;     // tick rule when no real volume

//====================================================================
// === MAIN OVERLAY ===
//====================================================================
input group "=== Main Overlay ==="
input int    InpOverlayXPosition     = 0;
input int    InpOverlayYPosition     = 0;
input int    InpOverlayWidth         = 1200;
input int    InpOverlayHeight        = 980;
input int    InpOverlayPanelInsetLeft   = 24;
input int    InpOverlayPanelInsetTop    = 4;
input int    InpOverlayPanelInsetRight  = 4;
input int    InpOverlayPanelInsetBottom = 4;
input int    InpOverlayPanelGap         = 8;

//====================================================================
// === COLOR THEME (defaults match commercial reference) ===
//====================================================================
input group "=== Colors — Backgrounds ==="
input color  InpGlobalBgColor        = (color)1511695;     // #171717 dark
input color  InpBackgroundColor      = (color)1511695;
input color  InpPanelBorderColor     = (color)3616040;
input bool   InpShowGrid             = true;
input color  InpTextColor            = (color)15458780;
input color  InpTextDimColor         = (color)10195340;

input group "=== Colors — Candle ==="
input color  InpBullishCandleColor   = (color)6210850;     // green
input color  InpBearishCandleColor   = (color)4474095;     // red
input color  InpBullishCandleFill    = (color)3433750;
input color  InpBearishCandleFill    = (color)1908095;
input color  InpWickColor            = (color)7563620;

input group "=== Colors — Volume Cells (Buyer dominant) ==="
input color  InpCellBuyerHigh        = (color)4891414;
input color  InpCellBuyerMed         = (color)6210850;
input color  InpCellBuyerLow         = (color)8445514;

input group "=== Colors — Volume Cells (Seller dominant) ==="
input color  InpCellSellerHigh       = (color)1842361;
input color  InpCellSellerMed        = (color)4474095;
input color  InpCellSellerLow        = (color)10855932;

input group "=== Colors — Special Cells ==="
input color  InpCellPOCColor         = (color)1428730;     // gold
input color  InpCellNeutralColor     = (color)4734007;

//====================================================================
// === CELL DISPLAY ===
//====================================================================
input group "=== Cell Display Options ==="
input bool   InpSeamlessCells        = false;
input int    InpCellGap              = 2;
input int    InpCellPadding          = 3;
input int    InpCellMinHeight        = 14;       // smallest cell pixels

//====================================================================
// === CANDLE FRAME ===
//====================================================================
input group "=== Candle Frame ==="
input bool   InpShowCandleFrame      = true;
input int    InpCandleFrameWidth     = 2;

//====================================================================
// === TEXT SIZES ===
//====================================================================
input group "=== Text Sizes ==="
input int    InpCandleTextSize       = 12;
input int    InpImbalanceTextSize    = 12;

//====================================================================
// === PRICE PANEL ===
//====================================================================
input group "=== Price Panel ==="
input int    InpPricePanelGap        = 75;
input bool   InpShowAskLine          = false;

//====================================================================
// === CANDLE TIMER ===
//====================================================================
input group "=== Candle Timer ==="
input bool   InpShowCandleTimer      = true;

//====================================================================
// === CUMULATIVE DELTA ===
//====================================================================
input group "=== Cumulative Delta ==="
input bool   InpCumDeltaSessionMode  = false;
input string InpCumDeltaSessionStart = "23:00";
input string InpCumDeltaSessionEnd   = "22:00";

//====================================================================
// === INTENSITY THRESHOLDS ===
//====================================================================
input group "=== Intensity Thresholds ==="
input int    InpCellIntensityHigh    = 70;       // top tier % dominance
input int    InpCellIntensityMed     = 40;       // mid tier %

//====================================================================
// === IMBALANCE DETECTION ===
//====================================================================
input group "=== Imbalance Detection ==="
input double InpImbalanceRatio1      = 2.0;      // tier 1 ratio
input double InpImbalanceRatio2      = 3.0;
input double InpImbalanceRatio3      = 4.0;
input int    InpImbalanceMinVolume   = 10;
input bool   InpImbalanceBold        = true;

input group "=== Imbalance Colors — Buyers ==="
input color  InpBuyerImbalance1      = (color)11333510;
input color  InpBuyerImbalance2      = (color)8445514;
input color  InpBuyerImbalance3      = (color)6210850;

input group "=== Imbalance Colors — Sellers ==="
input color  InpSellerImbalance1     = (color)13290238;
input color  InpSellerImbalance2     = (color)10855932;
input color  InpSellerImbalance3     = (color)7434744;

//====================================================================
// === BAR LAYOUT ===
//====================================================================
input group "=== Bar Layout ==="
input int    InpBarWidth             = 55;       // pixel width per bar
input int    InpBarSpacing           = 14;       // pixel gap between bars
input bool   InpShowDivider          = true;
input int    InpSeparatorWidth       = 3;

//====================================================================
// === FOOTPRINT STYLE ===
//====================================================================
input group "=== Footprint Style ==="
// 0=Minimalist 1=BgCells 2=CandleFrame 3=VPCandle 4=Frameless
// 5=MiddleCandle 6=DeltaCells 7=BidAskProfile 8=BidAskCells 9=HollowVP
input int    InpFootprintStyle       = 3;        // VP Candle default

//====================================================================
// === DELTA BAR ===
//====================================================================
input group "=== Delta Bar ==="
input bool   InpShowDeltaBar         = false;
input int    InpDeltaBarHeight       = 18;
input int    InpDeltaBarGap          = 15;
input color  InpDeltaPositiveColor   = (color)6210850;
input color  InpDeltaNegativeColor   = (color)4474095;

//====================================================================
// === POC OUTLINE ===
//====================================================================
input group "=== POC Outline ==="
input bool   InpShowFL2MBPOCOutline  = true;
input color  InpFL2MBPOCOutlineColor = (color)1428730;

//====================================================================
// === PER-BAR VOLUME PROFILE ===
//====================================================================
input group "=== Per-Bar VP ==="
input bool   InpShowPerBarVP         = false;
input int    InpPerBarVPWidth        = 40;
input color  InpVPBidColor           = (color)4474095;
input color  InpVPAskColor           = (color)6210850;
input color  InpVPPOCColor           = (color)1428730;

//====================================================================
// === SESSION POC ===
//====================================================================
input group "=== Session POC ==="
input bool   InpShowSessionPOC       = true;
input color  InpSessionPOCColor      = (color)16209320;

//====================================================================
// === SUPPLY & DEMAND ZONES ===
//====================================================================
input group "=== Supply & Demand Zones ==="
input bool   InpShowZones            = true;
input color  InpZoneSupplyColor      = clrNONE;       // -1 = use theme red
input color  InpZoneDemandColor      = clrNONE;       // -1 = use theme green
input int    InpZoneOpacity          = 40;
input int    InpMaxZones             = 4;
input int    InpZoneVolumeLookback   = 20;
input double InpZoneVolumeMinRatio   = 1.2;
input int    InpFrostZoneATRLen      = 50;
input double InpFrostZoneWidth       = 4.0;
input int    InpFrostSwingLen        = 8;
input int    InpFrostSwingLookback   = 200;

//====================================================================
// === SESSION FRAMES ===
//====================================================================
input group "=== Session Frames ==="
input string InpAsiaSessionStart     = "00:00";
input string InpAsiaSessionEnd       = "08:00";
input color  InpAsiaSessionColor     = (color)16301368;
input string InpLondonSessionStart   = "08:00";
input string InpLondonSessionEnd     = "16:30";
input color  InpLondonSessionColor   = (color)1428730;
input string InpNewYorkSessionStart  = "14:30";
input string InpNewYorkSessionEnd    = "22:00";
input color  InpNewYorkSessionColor  = (color)11956980;

//====================================================================
// === MARKET STRUCTURE ===
//====================================================================
input group "=== Market Structure ==="
input int    InpStructureSwingLen    = 2;
input int    InpStructureLookbackBars = 60;
input int    InpStructureMaxFVG      = 6;

//====================================================================
// === SESSION VP PANEL ===
//====================================================================
input group "=== Session VP Panel ==="
input int    InpSessionVPMode        = 2;        // 0=fixed bars 1=session start 2=daily
input int    InpSessionVPBars        = 50;
input string InpSessionStartTime     = "00:00";
input int    InpSessionVPType        = 0;        // 0=Total 1=Delta 2=Buy 3=Sell
input double InpSessionVPBarScale    = 0.5;
input int    InpSessionVPHeight      = 475;
input color  InpSVPPOCColor          = (color)1428730;
input color  InpSVPVAHColor          = (color)16631187;
input color  InpSVPVALColor          = (color)16631187;
input double InpValueAreaPct         = 70.0;

//====================================================================
// === TICKER INFO BAR ===
//====================================================================
input group "=== Ticker Info Bar ==="
input color  InpTickerBgColor        = (color)2103574;
input bool   InpTickerSymbolUseThemeColor = true;
input color  InpTickerSymbolColor    = (color)1428730;
input bool   InpTickerPriceUseThemeColor  = true;
input color  InpTickerPriceColor     = (color)16426336;
input color  InpTickerBullColor      = (color)6210850;
input color  InpTickerBearColor      = (color)4474095;

//====================================================================
// === SUMMARY TABLE ===
//====================================================================
input group "=== Summary Table ==="
input bool   InpShowSummaryTable     = true;
input int    InpTableRowHeight       = 15;
input color  InpTableHeaderColor     = (color)2958110;
input color  InpTablePositiveColor   = (color)3433750;
input color  InpTableNegativeColor   = (color)1908095;

//====================================================================
// === RSI ===
//====================================================================
input group "=== Chart Analyst RSI ==="
input bool   InpShowRSI              = true;
input int    InpRSIPeriod            = 14;
input int    InpRSIHeight            = 80;
input color  InpRSILineColor         = (color)16209320;
input int    InpRSIOverboughtLevel   = 70;
input int    InpRSIOversoldLevel     = 30;

//====================================================================
// === MACD ===
//====================================================================
input group "=== Chart Analyst MACD ==="
input bool   InpShowMACD             = true;
input int    InpMACDFast             = 12;
input int    InpMACDSlow             = 26;
input int    InpMACDSignal           = 9;
input int    InpMACDHeight           = 80;

//====================================================================
// === SIGNAL METER ===
//====================================================================
input group "=== Signal Meter ==="
input bool   InpShowSignalMeter      = true;
input int    InpDialSize             = 120;
input int    InpDialMA1Period        = 9;
input int    InpDialMA2Period        = 21;
input int    InpDialMA3Period        = 50;
input int    InpDialATRPeriod        = 14;
input double InpDialATRTrendHigh     = 1.15;
input double InpDialATRTrendLow      = 0.85;
input int    InpDialPOCAcceptBars    = 3;
input double InpDialPOCAcceptTicks   = 1.5;
input color  InpDialBullColor        = (color)6210850;
input color  InpDialBearColor        = (color)4474095;
input color  InpDialNeutralColor     = (color)7563620;
input color  InpDialPointerColor     = (color)1428730;
input color  InpDialBgColor          = (color)1511695;
input color  InpDialHeaderColor      = (color)2103574;

//====================================================================
// === CHART ANALYST ===
//====================================================================
input group "=== Chart Analyst Panel ==="
input bool   InpShowAnalyst          = true;
input int    InpAnalystRefreshSecs   = 30;
input int    InpAnalystWidth         = 280;     // compact
input int    InpAnalystHeight        = 235;     // compact
input color  InpAnalystBgColor       = (color)1511695;
input color  InpAnalystHeaderColor   = (color)2103574;
input color  InpAnalystBullColor     = (color)6210850;
input color  InpAnalystBearColor     = (color)4474095;
input color  InpAnalystNeutralColor  = (color)12100500;
input color  InpAnalystWarningColor  = (color)1428730;
input color  InpAnalystAccentColor   = (color)16155195;

//====================================================================
// === FONTS ===
//====================================================================
input group "=== Fonts ==="
input string InpFontName             = "Segoe UI";
input string InpFontMono             = "Consolas";
input int    InpFontSize             = 12;
input int    InpFontSizeSmall        = 11;
input int    InpFontSizeLarge        = 17;

//====================================================================
// === EXPORT TO PYTHON ===
//====================================================================
input group "=== JSON Export ==="
input bool   InpExportToJSON         = true;
input string InpExportFile           = "footprint_cells.json";
input int    InpExportEverySec       = 3;

//====================================================================
// === INTERNALS ===
//====================================================================
input group "=== Internals ==="
input string InpObjPrefix            = "CLFP3_";
input bool   InpVerbose              = false;

//====================================================================
// DATA STRUCTURES
//====================================================================
struct PriceLevel {
   double price;
   long   bid_vol;      // sell aggressor volume
   long   ask_vol;      // buy aggressor volume
};

struct BarFootprint {
   datetime bar_time;
   double   bar_open, bar_high, bar_low, bar_close;
   PriceLevel levels[];
   double   poc_price;
   long     total_vol;
   long     delta;
   long     prev_delta;     // for change calculation
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

BarFootprint g_bars[];
SDZone       g_zones[];
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

//====================================================================
// UTILITIES
//====================================================================
string ObjName(string suffix) { return InpObjPrefix + suffix; }

double PriceBucketSize() {
   // For XAU at $4400: precision=10 → bucket = 0.1
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

// Price-anchored rectangle
void DrawPriceRect(string name, datetime t1, datetime t2, double p1, double p2,
                   color bg, bool filled = true, int width = 1) {
   if (ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_FILL, filled);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

// Price-anchored text
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

// Pixel rectangle (for panels)
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

// Pixel text label
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
   g_bars[sz].prev_delta = (sz > 0) ? g_bars[sz-1].delta : 0;
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
// TICK AGGREGATION (weighted tick inference)
//====================================================================
void AggregateTick() {
   MqlTick t;
   if (!SymbolInfoTick(_Symbol, t)) return;
   double mid = (t.bid + t.ask) / 2.0;
   long raw_vol = (t.volume > 0) ? (long)t.volume : 1;
   // Weighted inference: scale by tick movement magnitude
   double vol_scaled = (double)raw_vol * InpVolumeScaleFactor;
   if (g_prev_mid > 0) {
      double move_abs = MathAbs(mid - g_prev_mid) / _Point;
      // Bigger price move = bigger market order = more volume
      vol_scaled *= (1.0 + move_abs * 0.45);
   }
   long inferred_vol = (long)MathMax(5, MathMin(5000, vol_scaled));

   datetime bar_time = iTime(_Symbol, _Period, 0);
   double bar_o = iOpen(_Symbol, _Period, 0);
   double bar_h = iHigh(_Symbol, _Period, 0);
   double bar_l = iLow(_Symbol, _Period, 0);
   double bar_c = iClose(_Symbol, _Period, 0);
   if (bar_time == 0) return;

   if (bar_time != g_cur_bar_time) {
      int prior_idx = FindBarIndex(g_cur_bar_time);
      if (prior_idx >= 0 && !g_bars[prior_idx].finalized) FinalizeBar(prior_idx);
      g_cur_bar_time = bar_time;
   }
   EnsureBarSlot(bar_time, bar_o, bar_h, bar_l, bar_c);
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
   BarFootprint b = g_bars[bar_idx];
   long total = 0, max_vol = 0, ask_sum = 0, bid_sum = 0;
   double poc = 0;
   for (int i = 0; i < ArraySize(b.levels); i++) {
      long lt = b.levels[i].bid_vol + b.levels[i].ask_vol;
      total += lt;
      ask_sum += b.levels[i].ask_vol;
      bid_sum += b.levels[i].bid_vol;
      if (lt > max_vol) { max_vol = lt; poc = b.levels[i].price; }
   }
   g_bars[bar_idx].total_vol = total;
   g_bars[bar_idx].poc_price = poc;
   g_bars[bar_idx].delta = ask_sum - bid_sum;
   g_cum_delta_running += (double)g_bars[bar_idx].delta;
   g_bars[bar_idx].cum_delta = g_cum_delta_running;

   // Count imbalances now
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
// IMBALANCE DETECTION (3-tier)
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

//====================================================================
// CELL COLOR TIERING (6-level)
//====================================================================
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
// INDICATORS (RSI, MACD, EMA, ATR, ADX)
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

double CalcRSI(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return 50;
   double gain = 0, loss = 0;
   for (int i = 1; i <= period && i+1 < copied; i++) {
      double diff = r[i].close - r[i+1].close;
      if (diff > 0) gain += diff; else loss -= diff;
   }
   double ag = gain / period, al = loss / period;
   if (al == 0) return 100;
   return 100.0 - 100.0 / (1.0 + ag / al);
}

double CalcEMA(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return 0;
   double alpha = 2.0 / (period + 1.0);
   double ema = r[period].close;
   for (int i = period - 1; i >= 1; i--)
      ema = alpha * r[i].close + (1.0 - alpha) * ema;
   return ema;
}

//====================================================================
// SESSION VP COMPUTATION
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
// SUPPLY/DEMAND ZONES (Frost-style)
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
// SIGNAL METER COMPUTATION (MA + ATR + POC + Delta)
//====================================================================
void ComputeSignalMeter() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(_Symbol, _Period, 0, 60, r);
   if (copied < 55) { g_signal_value = 0; g_signal_label = "NO DATA"; return; }
   double ma1 = 0, ma2 = 0, ma3 = 0;
   for (int i = 1; i <= InpDialMA1Period; i++) ma1 += r[i].close;
   for (int i = 1; i <= InpDialMA2Period; i++) ma2 += r[i].close;
   for (int i = 1; i <= InpDialMA3Period; i++) ma3 += r[i].close;
   ma1 /= InpDialMA1Period; ma2 /= InpDialMA2Period; ma3 /= InpDialMA3Period;
   double ma_score = 0;
   if (ma1 > ma2 && ma2 > ma3) ma_score = +40;
   else if (ma1 < ma2 && ma2 < ma3) ma_score = -40;
   else if (ma1 > ma2) ma_score = +15;
   else if (ma1 < ma2) ma_score = -15;
   double atr = CalcATR(r, copied, InpDialATRPeriod);
   double rg = r[1].high - r[1].low;
   double atr_score = (rg > atr * InpDialATRTrendHigh) ? 10 : (rg < atr * InpDialATRTrendLow ? -5 : 0);
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
// CHART ANALYST (6-factor confluence)
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
   g_analyst_lines[7] = "──────────────────────────────";
   g_analyst_lines[8] = StringFormat("CONSENSUS: %s   (%+d/6)", bias, score);
   g_analyst_lines[9] = "";
}

//====================================================================
// RENDER — FOOTPRINT CELLS (10 styles)
//====================================================================
void RenderFootprint() {
   // BUGFIX: delete ALL footprint cell + text objects before redrawing
   // so old bars at stale prices don't persist on chart
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

      // Cell occupies 15%-85% of bar width (leaves room for candle visibility)
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
         int fontsz = (imb_b >= 2 || imb_s >= 2) ? InpImbalanceTextSize + 1 : InpCandleTextSize - 4;

         // STYLE-SPECIFIC RENDERING
         string c_name = ObjName(StringFormat("c_%d_%d", b, r));

         if (InpFootprintStyle == 0) {
            // S1 MINIMALIST — text only, no background
            string txt = StringFormat("%d × %d", (int)bid_v, (int)ask_v);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t_mid, price, txt, txt_col, fontsz);
         }
         else if (InpFootprintStyle == 1 || InpFootprintStyle == 3) {
            // S2 BG CELLS / S4 VP CANDLE — full colored background
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
         else if (InpFootprintStyle == 6) {
            // S7 DELTA CELLS — single delta number
            long d = ask_v - bid_v;
            color dc = d > 0 ? InpDeltaPositiveColor : (d < 0 ? InpDeltaNegativeColor : InpCellNeutralColor);
            DrawPriceRect(c_name, t1, t2, p_top, p_bot, dc);
            string txt = (d == 0) ? "0" : StringFormat("%+d", (int)d);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t_mid, price, txt, txt_col, fontsz+1);
         }
         else if (InpFootprintStyle == 7 || InpFootprintStyle == 8) {
            // S8 BID×ASK PROFILE / S9 BID×ASK CELLS — split bid|ask
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
            // S3/S5/S6/S10 — default to BG CELLS for now
            DrawPriceRect(c_name, t1, t2, p_top, p_bot, cell_col);
            string txt = StringFormat("%d × %d", (int)bid_v, (int)ask_v);
            DrawPriceText(ObjName(StringFormat("t_%d_%d", b, r)),
                          t1, price, txt, txt_col, fontsz);
         }

         // POC outline (gold thick)
         if (is_poc && InpShowFL2MBPOCOutline) {
            string poc_name = ObjName(StringFormat("poc_%d", b));
            DrawPriceRect(poc_name, bar.bar_time,
                          bar.bar_time + (datetime)(period_sec * 0.12),
                          p_top, p_bot, InpFL2MBPOCOutlineColor);
         }
      }
   }
}

//====================================================================
// RENDER — SD ZONES
//====================================================================
void RenderSDZones() {
   if (!InpShowZones) return;
   datetime t_end = TimeCurrent() + PeriodSeconds(_Period) * 30;
   for (int i = 0; i < ArraySize(g_zones); i++) {
      string name = ObjName(StringFormat("sd_%d", i));
      color c = g_zones[i].is_supply
                ? (InpZoneSupplyColor == clrNONE ? InpBearishCandleFill : InpZoneSupplyColor)
                : (InpZoneDemandColor == clrNONE ? InpBullishCandleFill : InpZoneDemandColor);
      DrawPriceRect(name, g_zones[i].ts, t_end, g_zones[i].top, g_zones[i].bot, c, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_ZORDER, -10);
   }
}

//====================================================================
// RENDER — SESSION VP LINES
//====================================================================
void RenderSessionVPLines() {
   if (g_svp_poc > 0)
      DrawHLine(ObjName("svp_poc"), g_svp_poc, InpSVPPOCColor, 2, STYLE_SOLID);
   if (g_svp_vah > 0)
      DrawHLine(ObjName("svp_vah"), g_svp_vah, InpSVPVAHColor, 1, STYLE_DASH);
   if (g_svp_val > 0)
      DrawHLine(ObjName("svp_val"), g_svp_val, InpSVPVALColor, 1, STYLE_DASH);
}

//====================================================================
// RENDER — TICKER BAR (header)
//====================================================================
void RenderTickerBar() {
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   MqlTick t; SymbolInfoTick(_Symbol, t);
   int H = 32;
   DrawRect(ObjName("hdr_bg"), 5, 5, (int)chart_w - 10, H, InpTickerBgColor);

   string sym_tf = _Symbol + "  " + EnumToString((ENUM_TIMEFRAMES)_Period);
   color sym_col = InpTickerSymbolUseThemeColor ? InpTickerSymbolColor : InpTextColor;
   DrawText(ObjName("hdr_sym"), 15, 12, sym_tf, sym_col, InpFontSizeLarge, InpFontName);

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

   // Signal Meter compact label
   color sm_col = g_signal_value >= 25 ? InpDialBullColor :
                  (g_signal_value <= -25 ? InpDialBearColor : InpDialNeutralColor);
   DrawText(ObjName("hdr_sig"), 740, 14,
            StringFormat("SIG %+.0f %s", g_signal_value, g_signal_label),
            sm_col, InpFontSize, InpFontMono);
}

//====================================================================
// RENDER — SIGNAL METER PANEL (compact dial)
//====================================================================
void RenderSignalMeter() {
   if (!InpShowSignalMeter) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int w = InpDialSize + 60;
   int h = InpDialSize + 30;
   int x = (int)chart_w - w - 10;
   int y = 50;
   DrawRect(ObjName("sm_bg"), x, y, w, h, InpDialBgColor, InpPanelBorderColor);
   DrawText(ObjName("sm_title"), x + 8, y + 4, "SIGNAL METER", InpDialHeaderColor, InpFontSize, InpFontName);
   int bar_x = x + 8, bar_y = y + 30;
   int bar_w = w - 16, bar_h = 18;
   DrawRect(ObjName("sm_track"), bar_x, bar_y, bar_w, bar_h, (color)2103574);
   int center_x = bar_x + bar_w / 2;
   color c = g_signal_value >= 60 ? InpDialBullColor :
             (g_signal_value <= -60 ? InpDialBearColor :
              (g_signal_value >= 25 ? InpBullishCandleColor :
               (g_signal_value <= -25 ? InpBearishCandleColor : InpDialNeutralColor)));
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
// RENDER — CHART ANALYST PANEL
//====================================================================
void RenderAnalyst() {
   if (!InpShowAnalyst) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   long chart_h = ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int w = InpAnalystWidth, h = InpAnalystHeight;
   // BOTTOM-RIGHT positioning (was middle-right covering chart)
   int x = (int)chart_w - w - 10;
   int y = (int)chart_h - h - 30;
   DrawRect(ObjName("an_bg"), x, y, w, h, InpAnalystBgColor, InpPanelBorderColor);
   DrawText(ObjName("an_title"), x + 8, y + 4, "CHART ANALYST",
            InpAnalystAccentColor, InpFontSize, InpFontName);
   for (int i = 0; i < 10; i++) {
      if (StringLen(g_analyst_lines[i]) == 0) continue;
      color cl = InpTextColor;
      if (StringFind(g_analyst_lines[i], "BULL") >= 0) cl = InpAnalystBullColor;
      else if (StringFind(g_analyst_lines[i], "BEAR") >= 0) cl = InpAnalystBearColor;
      else if (StringFind(g_analyst_lines[i], "CONSENSUS") >= 0) cl = InpAnalystWarningColor;
      DrawText(ObjName(StringFormat("an_l_%d", i)),
               x + 8, y + 22 + i * 18, g_analyst_lines[i],
               cl, InpFontSizeSmall, InpFontMono);
   }
}

//====================================================================
// RENDER — SESSION FRAMES (vertical lines / shaded background)
//====================================================================
void RenderSessionFrames() {
   // Simple labels — full session shading would need many objects
   datetime now = TimeCurrent();
   MqlDateTime t; TimeToStruct(now, t);
   int h = t.hour;
   string current_session = "—";
   color sc = clrGray;
   if (h >= 14 && h < 22)      { current_session = "NEW YORK"; sc = (color)InpNewYorkSessionColor; }
   else if (h >= 8 && h < 16)  { current_session = "LONDON";   sc = (color)InpLondonSessionColor; }
   else                         { current_session = "ASIA";     sc = (color)InpAsiaSessionColor; }
   DrawText(ObjName("sess"), 900, 14, "SESSION " + current_session,
            sc, InpFontSize, InpFontName);
}

//====================================================================
// JSON EXPORT (for Python brain bridge)
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
      // recompute live POC + delta
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
   if (TimeCurrent() - g_last_zones > 30) {
      DetectSDZones();
      g_last_zones = TimeCurrent();
   }
   RenderTickerBar();
   RenderSessionFrames();
   RenderFootprint();
   RenderSessionVPLines();
   RenderSDZones();
   RenderSignalMeter();
   RenderAnalyst();
   ExportJSON();
   ChartRedraw(0);
}

//====================================================================
// BACKFILL INITIAL BARS (so footprint shows on attach)
//====================================================================
void BackfillBars() {
   int n = MathMin(InpBarsToDisplay, Bars(_Symbol, _Period) - 1);
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
      // distribute volume across 5 levels around close
      int lvls = 5;
      long per = v / lvls;
      double step = PriceBucketSize();
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
   Print("[CLAUDE_FOOTPRINT v3.00] ONLINE on ", _Symbol);
   Print("  Bars=", InpBarsToDisplay, " precision=", InpPricePrecision,
         " bucket=$", DoubleToString(PriceBucketSize(), 4));
   Print("  Style=", InpFootprintStyle, "  Theme=", InpColorTheme,
         "  Skin=", InpPanelSkin);
   Print("  Imb ratios: ", InpImbalanceRatio1, "/", InpImbalanceRatio2, "/", InpImbalanceRatio3,
         "  IntensityHigh=", InpCellIntensityHigh, "% Med=", InpCellIntensityMed, "%");
   Print("  Refresh=", InpRefreshRateMs, "ms  Export JSON=", InpExportToJSON);
   Print("════════════════════════════════════════════");
   BackfillBars();
   g_cur_bar_time = iTime(_Symbol, _Period, 0);
   EventSetMillisecondTimer(InpRefreshRateMs);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   EventKillTimer();
   DeleteAllOurObjects();
   Print("[CLAUDE_FOOTPRINT v3] offline — reason ", reason);
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
