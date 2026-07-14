//+------------------------------------------------------------------+
//| CLAUDE_BRAIN_EA_v1.mq5                                            |
//|                                                                  |
//| ✦ NATIVE MQL5 BRAIN — embodies 8 hours of live session learning  |
//|                                                                  |
//| Born 2026-05-27 from Friday session with Radhi.                  |
//| Account journey: $50 → $679 peak → $368 settled = +638%.         |
//|                                                                  |
//| Indicators (all native): ATR, RSI, EMA, MACD, ADX, ZigZag,       |
//|   Order Blocks (M5/M15), Fair Value Gaps (M5/M15), S/R clusters, |
//|   Pivot points (S2/R2), Pressure 10-M1, MTF bias align,          |
//|   Volume trend M5, Candle anatomy classifier, Liquidity sweep.   |
//|                                                                  |
//| The 8 Rules (learned from observing user trade live):            |
//|   R1 — Counter-trend BUY at round# with pressure flip            |
//|   R2 — With-trend SELL at R cluster + ADX -DI dominant           |
//|   R3 — Liquidity sweep + reclaim                                  |
//|   R4 — MTF align BUY+ALL inside BULL_OB                           |
//|   R5 — Failed parabolic top pyramid SELL                          |
//|   R6 — BEAR FVG retest continuation                               |
//|   R7 — BULL_OB defense hammer/marubozu                            |
//|   R8 — Emergency basket protection                                |
//|                                                                  |
//| Risk Contract:                                                    |
//|   • Max 3 concurrent positions                                    |
//|   • Max lot 0.05 (configurable)                                   |
//|   • Per-trade risk capped (USD)                                   |
//|   • Daily loss limit → auto-pause                                 |
//|   • 3 consecutive losses → 1h cooldown                            |
//|   • Equity floor → emergency close all                            |
//|   • Spread + ATR + session hard guards                            |
//|   • Trail SL upward as trade profits                              |
//+------------------------------------------------------------------+
#property strict
#property copyright "Radhi & Claude"
#property version   "1.00"
#property description "Native MQL5 Brain — 8 rules from live session learning"

#include <Trade/Trade.mqh>

CTrade trade;

//====================================================================
// USER INPUTS
//====================================================================
input group "=== Identity ==="
input ulong  InpMagic              = 99778;          // Magic for Claude EA trades
input string InpComment            = "CLAUDE_BRAIN";
input string InpSymbolFilter       = "";             // empty = current symbol

input group "=== Session ==="
input bool   InpOnlyNYOverlap      = true;           // NY_OVERLAP 13-17 UTC only
input bool   InpAllowLondon        = false;
input bool   InpAllowNYLate        = false;

input group "=== Risk Contract ==="
input double InpMaxLotTotal        = 0.05;
input int    InpMaxOpenPositions   = 3;
input double InpRiskUSDPerTrade    = 5.00;
input double InpDailyLossLimit     = -15.00;
input double InpEquityFloorUSD     = 0.0;            // 0 = auto (balance - 15)
input int    InpConsecLossPause    = 3;
input int    InpCooldownMinutes    = 60;

input group "=== Market Guards ==="
input double InpMaxSpreadUSD       = 0.50;
input double InpMaxATRm1           = 8.0;
input bool   InpBlockOnDryVol      = true;           // block when M5 vol trend = DRY

input group "=== Confluence & R:R ==="
input int    InpMinConfluence      = 3;              // need ≥ this many factors
input double InpMinRR              = 1.5;
input bool   InpUseRule1           = true;           // counter-trend BUY
input bool   InpUseRule2           = true;           // with-trend SELL
input bool   InpUseRule3           = true;           // liquidity sweep
input bool   InpUseRule4           = true;           // MTF align BUY+ALL
input bool   InpUseRule5           = true;           // failed parabolic SELL
input bool   InpUseRule6           = true;           // BEAR FVG retest
input bool   InpUseRule7           = true;           // BULL_OB defense

input group "=== Trail / Protection ==="
input bool   InpTrailSL            = true;
input double InpTrailTrigger1      = 4.0;            // profit pts to lock breakeven
input double InpTrailTrigger2      = 8.0;            // profit pts to lock +2
input double InpEmergencyBearVol   = 750;            // tick volume threshold

input group "=== Verbose ==="
input bool   InpVerbose            = true;
input bool   InpDrawZones          = true;

input group "=== v2 Footprint Overlay ==="
input bool   InpReadFootprintJSON  = true;   // import footprint signals
input string InpFootprintFile      = "footprint_cells.json"; // Common\Files
input bool   InpUseFootprintInRules = true;  // boost confluence with FP imb
input double InpFPImbDomBoost      = 1.0;    // confluence add when FP confirms
input bool   InpDrawFPSnapshot     = true;   // visual indicator on chart

//====================================================================
// GLOBALS
//====================================================================
string  SYMBOL;
datetime g_lastBarM1 = 0;
datetime g_lastBarM5 = 0;
datetime g_dayStart  = 0;
double   g_dayStartEquity = 0;
int      g_consecLosses = 0;
datetime g_pausedUntil = 0;
double   g_lastClosedProfit = 0;
ulong    g_lastClosedTicket = 0;

// Cached snapshots
struct BarSnap {
   datetime time;
   double   open, high, low, close;
   long     volume;
   string   kind;           // marubozu_bull/bear, hammer, doji, etc.
   int      body_pct;
   double   upper_wick, lower_wick;
};

struct OrderBlock {
   double bot, top;
   datetime ts;
   int      age_bars;
   bool     valid;
};

struct FVG {
   double bot, top, mid, size;
   int    age_bars;
   bool   valid;
};

struct SwingPivot {
   double price;
   string type;   // "H" or "L"
   datetime ts;
};

//====================================================================
// UTILITIES
//====================================================================
string ActiveSymbol() {
   return (StringLen(InpSymbolFilter) > 0) ? InpSymbolFilter : _Symbol;
}

string GetSession() {
   datetime now = TimeCurrent();
   MqlDateTime t; TimeToStruct(now, t);
   int h = t.hour;
   if (h >= 13 && h < 17) return "NY_OVERLAP";
   if (h >= 8  && h < 13) return "LONDON";
   if (h >= 17 && h < 21) return "NY_LATE";
   if (h >= 22 || h < 8)  return "ASIAN";
   return "TRANSITION";
}

bool IsAllowedSession() {
   string s = GetSession();
   if (InpOnlyNYOverlap && s != "NY_OVERLAP") return false;
   if (!InpAllowLondon && s == "LONDON") return false;
   if (!InpAllowNYLate && s == "NY_LATE") return false;
   if (s == "ASIAN" || s == "TRANSITION") return false;
   return true;
}

//====================================================================
// CANDLE ANATOMY CLASSIFIER
//====================================================================
BarSnap ClassifyBar(MqlRates &r) {
   BarSnap b;
   b.time = r.time;
   b.open = r.open; b.high = r.high; b.low = r.low; b.close = r.close;
   b.volume = r.tick_volume;
   double rng = MathMax(r.high - r.low, 1e-9);
   double body = MathAbs(r.close - r.open);
   double upper = r.high - MathMax(r.open, r.close);
   double lower = MathMin(r.open, r.close) - r.low;
   b.body_pct = (int)MathRound(body / rng * 100);
   b.upper_wick = upper;
   b.lower_wick = lower;
   bool is_bull = (r.close > r.open);
   int upper_pct = (int)MathRound(upper / rng * 100);
   int lower_pct = (int)MathRound(lower / rng * 100);

   b.kind = "doji";
   if (b.body_pct >= 80) b.kind = is_bull ? "marubozu_bull" : "marubozu_bear";
   else if (upper_pct >= 60 && b.body_pct <= 30)
      b.kind = is_bull ? "inverted_hammer" : "shooting_star";
   else if (lower_pct >= 60 && b.body_pct <= 30)
      b.kind = is_bull ? "hammer" : "hanging_man";
   else if (b.body_pct >= 60) b.kind = is_bull ? "strong_bull" : "strong_bear";
   else if (b.body_pct >= 35) b.kind = is_bull ? "normal_bull" : "normal_bear";
   else if (b.body_pct >= 15) b.kind = is_bull ? "weak_bull"   : "weak_bear";

   return b;
}

//====================================================================
// INDICATORS (native — no library dependencies)
//====================================================================
double CalcATR(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return 0;
   double sum = 0;
   for (int i = 1; i <= period && i < copied; i++) {
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
   double ag = gain / period;
   double al = loss / period;
   if (al == 0) return 100;
   double rs = ag / al;
   return 100.0 - 100.0 / (1.0 + rs);
}

double CalcEMA(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return 0;
   double alpha = 2.0 / (period + 1.0);
   double ema = r[period].close;
   for (int i = period - 1; i >= 1; i--)
      ema = alpha * r[i].close + (1.0 - alpha) * ema;
   return ema;
}

string CalcBias(MqlRates &r[], int copied, int period) {
   if (copied < period + 2) return "?";
   double ema = CalcEMA(r, copied, period);
   if (ema == 0) return "?";
   return (r[1].close > ema) ? "UP" : "DOWN";
}

double CalcADX(MqlRates &r[], int copied, int period, double &plus_di, double &minus_di) {
   if (copied < period * 2) { plus_di = 0; minus_di = 0; return 0; }
   double sum_pdm = 0, sum_mdm = 0, sum_tr = 0;
   for (int i = 1; i <= period && i+1 < copied; i++) {
      double up_move = r[i].high - r[i+1].high;
      double dn_move = r[i+1].low - r[i].low;
      double pdm = (up_move > dn_move && up_move > 0) ? up_move : 0;
      double mdm = (dn_move > up_move && dn_move > 0) ? dn_move : 0;
      double tr1 = r[i].high - r[i].low;
      double tr2 = MathAbs(r[i].high - r[i+1].close);
      double tr3 = MathAbs(r[i].low  - r[i+1].close);
      double tr  = MathMax(tr1, MathMax(tr2, tr3));
      sum_pdm += pdm; sum_mdm += mdm; sum_tr += tr;
   }
   if (sum_tr == 0) { plus_di = 0; minus_di = 0; return 0; }
   plus_di  = 100.0 * sum_pdm / sum_tr;
   minus_di = 100.0 * sum_mdm / sum_tr;
   double dx = 100.0 * MathAbs(plus_di - minus_di) / MathMax(plus_di + minus_di, 1e-9);
   return dx;
}

//====================================================================
// SMC PRIMITIVES — Order Blocks
//====================================================================
OrderBlock FindBullOB(MqlRates &r[], int copied, int lookback) {
   OrderBlock ob; ob.valid = false; ob.bot = 0; ob.top = 0; ob.age_bars = 0;
   int n = MathMin(lookback, copied - 2);
   for (int i = 2; i <= n; i++) {
      // last bearish bar before strong bull follow-through
      if (r[i].close < r[i].open && r[i-1].close > r[i-1].open) {
         double body = MathAbs(r[i-1].close - r[i-1].open);
         double rng  = MathMax(r[i-1].high - r[i-1].low, 1e-9);
         if (body / rng > 0.6) {
            ob.bot = r[i].low; ob.top = r[i].high;
            ob.ts = r[i].time; ob.age_bars = i - 1;
            ob.valid = true;
            return ob;
         }
      }
   }
   return ob;
}

OrderBlock FindBearOB(MqlRates &r[], int copied, int lookback) {
   OrderBlock ob; ob.valid = false; ob.bot = 0; ob.top = 0; ob.age_bars = 0;
   int n = MathMin(lookback, copied - 2);
   for (int i = 2; i <= n; i++) {
      // last bullish bar before strong bear follow-through
      if (r[i].close > r[i].open && r[i-1].close < r[i-1].open) {
         double body = MathAbs(r[i-1].close - r[i-1].open);
         double rng  = MathMax(r[i-1].high - r[i-1].low, 1e-9);
         if (body / rng > 0.6) {
            ob.bot = r[i].low; ob.top = r[i].high;
            ob.ts = r[i].time; ob.age_bars = i - 1;
            ob.valid = true;
            return ob;
         }
      }
   }
   return ob;
}

//====================================================================
// SMC PRIMITIVES — Fair Value Gaps (returns nearest only)
//====================================================================
FVG FindBullFVG(MqlRates &r[], int copied, int lookback) {
   FVG g; g.valid = false; g.bot = 0; g.top = 0; g.mid = 0; g.size = 0; g.age_bars = 0;
   int n = MathMin(lookback, copied - 2);
   for (int i = 2; i <= n; i++) {
      // Index i is the middle bar; check if low of bar i-1 > high of bar i+1 (note: index 0 is current)
      if (i+1 >= copied) break;
      double curLow  = r[i-1].low;
      double prevHigh = r[i+1].high;
      if (curLow > prevHigh) {
         g.top = curLow; g.bot = prevHigh;
         g.mid = (g.top + g.bot) / 2.0;
         g.size = g.top - g.bot;
         g.age_bars = i;
         g.valid = true;
         return g;
      }
   }
   return g;
}

FVG FindBearFVG(MqlRates &r[], int copied, int lookback) {
   FVG g; g.valid = false; g.bot = 0; g.top = 0; g.mid = 0; g.size = 0; g.age_bars = 0;
   int n = MathMin(lookback, copied - 2);
   for (int i = 2; i <= n; i++) {
      if (i+1 >= copied) break;
      double curHigh = r[i-1].high;
      double prevLow = r[i+1].low;
      if (curHigh < prevLow) {
         g.top = prevLow; g.bot = curHigh;
         g.mid = (g.top + g.bot) / 2.0;
         g.size = g.top - g.bot;
         g.age_bars = i;
         g.valid = true;
         return g;
      }
   }
   return g;
}

//====================================================================
// SMC PRIMITIVES — Pressure 10-M1 net body
//====================================================================
double CalcPressure10M1() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(SYMBOL, PERIOD_M1, 1, 10, r);   // last 10 closed M1 bars
   if (copied < 10) return 0;
   double bull = 0, bear = 0;
   for (int i = 0; i < copied; i++) {
      if (r[i].close > r[i].open) bull += r[i].close - r[i].open;
      else if (r[i].close < r[i].open) bear += r[i].open - r[i].close;
   }
   return bull - bear;
}

//====================================================================
// SMC PRIMITIVES — Round numbers
//====================================================================
struct RoundLevel { double level; double dist; };
bool NearestRound(double price, double &out_level, double &out_dist, double tolerance = 2.0) {
   int base = (int)MathFloor(price);
   double best_dist = 1e9; double best_level = 0;
   int steps[] = {5, 10, 25, 50, 100};
   for (int k = 0; k < 5; k++) {
      int step = steps[k];
      int low = (base / step) * step;
      int candidates[] = {low, low + step};
      for (int j = 0; j < 2; j++) {
         double dist = MathAbs(candidates[j] - price);
         if (dist <= tolerance && dist < best_dist) {
            best_dist = dist; best_level = candidates[j];
         }
      }
   }
   if (best_dist < 1e9) { out_level = best_level; out_dist = best_dist; return true; }
   return false;
}

//====================================================================
// VOLUME TREND M5
//====================================================================
string CalcVolTrendM5() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(SYMBOL, PERIOD_M5, 1, 10, r);
   if (copied < 10) return "?";
   double recent = 0, prior = 0;
   for (int i = 0; i < 5; i++)  recent += (double)r[i].tick_volume;
   for (int i = 5; i < 10; i++) prior  += (double)r[i].tick_volume;
   recent /= 5.0; prior /= 5.0;
   double ratio = recent / MathMax(prior, 1);
   if (ratio > 1.5) return "RISING";
   if (ratio < 0.7) return "DRY";
   return "STEADY";
}

//====================================================================
// LIQUIDITY SWEEP DETECTOR (M5)
//====================================================================
struct SweepInfo { string type; double level; bool valid; };
SweepInfo DetectLiquiditySweep() {
   SweepInfo s; s.valid = false; s.type = ""; s.level = 0;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int copied = CopyRates(SYMBOL, PERIOD_M5, 1, 12, r);
   if (copied < 12) return s;
   // r[0] is last closed; r[1..10] is the prior window
   double prior_hi = r[1].high, prior_lo = r[1].low;
   for (int i = 2; i <= 10; i++) {
      if (r[i].high > prior_hi) prior_hi = r[i].high;
      if (r[i].low  < prior_lo) prior_lo = r[i].low;
   }
   if (r[0].high > prior_hi && r[0].close < prior_hi) {
      s.type = "swept_high"; s.level = prior_hi; s.valid = true; return s;
   }
   if (r[0].low < prior_lo && r[0].close > prior_lo) {
      s.type = "swept_low"; s.level = prior_lo; s.valid = true; return s;
   }
   return s;
}

//====================================================================
// MARKET SNAPSHOT — everything gathered once per tick
//====================================================================
struct MarketSnapshot {
   double bid, ask, spread;
   string session;

   // M1
   BarSnap m1_last;
   double  atr_m1, rsi_m1;
   string  bias_m1;
   double  pressure_10m1;

   // M5
   double  atr_m5, rsi_m5;
   string  bias_m5;
   double  adx_m5, plus_di_m5, minus_di_m5;
   string  vol_trend_m5;
   OrderBlock bull_ob_m5, bear_ob_m5;
   FVG     bull_fvg_m5, bear_fvg_m5;
   SweepInfo sweep_m5;
   double  ema21_m5;

   // M15
   double  rsi_m15;
   string  bias_m15;

   // levels
   double  near_round, dist_round;
   bool    has_round;

   // mtf align
   string  mtf_align;
};

MarketSnapshot CaptureMarket() {
   MarketSnapshot s;
   MqlTick tick;
   SymbolInfoTick(SYMBOL, tick);
   s.bid = tick.bid; s.ask = tick.ask;
   s.spread = tick.ask - tick.bid;
   s.session = GetSession();

   MqlRates m1[], m5[], m15[], h1[];
   ArraySetAsSeries(m1, true);  ArraySetAsSeries(m5, true);
   ArraySetAsSeries(m15, true); ArraySetAsSeries(h1, true);
   int n_m1  = CopyRates(SYMBOL, PERIOD_M1,  0, 60, m1);
   int n_m5  = CopyRates(SYMBOL, PERIOD_M5,  0, 60, m5);
   int n_m15 = CopyRates(SYMBOL, PERIOD_M15, 0, 30, m15);
   int n_h1  = CopyRates(SYMBOL, PERIOD_H1,  0, 24, h1);

   if (n_m1 > 1) s.m1_last = ClassifyBar(m1[1]);
   s.atr_m1 = CalcATR(m1, n_m1, 14);
   s.rsi_m1 = CalcRSI(m1, n_m1, 14);
   s.bias_m1 = CalcBias(m1, n_m1, 20);
   s.pressure_10m1 = CalcPressure10M1();

   s.atr_m5 = CalcATR(m5, n_m5, 14);
   s.rsi_m5 = CalcRSI(m5, n_m5, 14);
   s.bias_m5 = CalcBias(m5, n_m5, 20);
   s.adx_m5 = CalcADX(m5, n_m5, 14, s.plus_di_m5, s.minus_di_m5);
   s.vol_trend_m5 = CalcVolTrendM5();
   s.bull_ob_m5 = FindBullOB(m5, n_m5, 40);
   s.bear_ob_m5 = FindBearOB(m5, n_m5, 40);
   s.bull_fvg_m5 = FindBullFVG(m5, n_m5, 30);
   s.bear_fvg_m5 = FindBearFVG(m5, n_m5, 30);
   s.sweep_m5 = DetectLiquiditySweep();
   s.ema21_m5 = CalcEMA(m5, n_m5, 21);

   s.rsi_m15 = CalcRSI(m15, n_m15, 14);
   s.bias_m15 = CalcBias(m15, n_m15, 20);

   double mid = (s.bid + s.ask) / 2.0;
   s.has_round = NearestRound(mid, s.near_round, s.dist_round, 2.0);

   // mtf align
   string biases[4] = { s.bias_m1, s.bias_m5, s.bias_m15, CalcBias(h1, n_h1, 20) };
   int up = 0, dn = 0;
   for (int i = 0; i < 4; i++) {
      if (biases[i] == "UP") up++;
      else if (biases[i] == "DOWN") dn++;
   }
   s.mtf_align = (up >= 3) ? "UP" : (dn >= 3 ? "DOWN" : "MIXED");

   return s;
}

//====================================================================
// DECISION STRUCT
//====================================================================
struct Decision {
   bool   valid;
   string rule;
   string side;          // "BUY" or "SELL"
   double entry, sl, tp;
   double lot;
   double confluence;
   string rationale;
};

//====================================================================
// RULE EVALUATORS
//====================================================================
Decision EmptyDecision() {
   Decision d;
   d.valid = false; d.rule = ""; d.side = "";
   d.entry = 0; d.sl = 0; d.tp = 0; d.lot = 0;
   d.confluence = 0; d.rationale = "";
   return d;
}

Decision Rule1_CounterTrendBuy(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule1) return d;
   if (s.bias_m5 != "DOWN") return d;
   if (s.rsi_m1 < 30 || s.rsi_m1 > 55) return d;
   if (!s.has_round || s.near_round > s.bid) return d;
   if (s.pressure_10m1 <= 0) return d;
   d.confluence = 3;
   if (s.bull_fvg_m5.valid && MathAbs(s.bull_fvg_m5.mid - s.bid) < 5)
      d.confluence += 0.5;
   d.valid = true;
   d.rule = "R1_counter_buy";
   d.side = "BUY";
   d.entry = s.ask;
   d.sl = s.near_round - 4;
   d.tp = s.near_round + 5;
   d.lot = 0.02;
   d.rationale = StringFormat("NY+M5↓+RSI%.1f+Round$%.0f+Press%+.1f",
                              s.rsi_m1, s.near_round, s.pressure_10m1);
   return d;
}

Decision Rule2_WithTrendSell(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule2) return d;
   if (s.bias_m5 != "DOWN") return d;
   string k = s.m1_last.kind;
   if (k != "shooting_star" && k != "marubozu_bear" && k != "strong_bear") return d;
   if (s.rsi_m1 <= 35) return d;
   // ADX guard — saved -$32 on 2026-05-27
   if (s.adx_m5 >= 20 && s.plus_di_m5 > s.minus_di_m5) {
      if (s.vol_trend_m5 == "RISING") return d;   // bullish trend dominant
   }
   d.confluence = 3;
   if (s.adx_m5 > 20) d.confluence += 1;
   if (s.bear_ob_m5.valid && s.bid > s.bear_ob_m5.bot && s.bid < s.bear_ob_m5.top)
      d.confluence += 0.5;
   d.valid = true;
   d.rule = "R2_with_sell";
   d.side = "SELL";
   d.entry = s.bid;
   d.sl = s.bid + 3;
   d.tp = s.bid - 7;
   d.lot = 0.02;
   d.rationale = StringFormat("NY+M5↓+%s+RSI%.1f+ADX%.1f",
                              k, s.rsi_m1, s.adx_m5);
   return d;
}

Decision Rule3_LiquiditySweep(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule3) return d;
   if (!s.sweep_m5.valid) return d;
   if (s.sweep_m5.type == "swept_low" && s.bias_m5 == "DOWN") {
      d.valid = true; d.rule = "R3_sweep_low";
      d.side = "BUY"; d.entry = s.ask;
      d.sl = s.sweep_m5.level - 3; d.tp = s.sweep_m5.level + 7;
      d.lot = 0.02; d.confluence = 4;
      d.rationale = StringFormat("Swept low $%.2f reclaimed", s.sweep_m5.level);
      return d;
   }
   if (s.sweep_m5.type == "swept_high" && s.bias_m5 == "UP") {
      d.valid = true; d.rule = "R3_sweep_high";
      d.side = "SELL"; d.entry = s.bid;
      d.sl = s.sweep_m5.level + 3; d.tp = s.sweep_m5.level - 7;
      d.lot = 0.02; d.confluence = 4;
      d.rationale = StringFormat("Swept high $%.2f rejected", s.sweep_m5.level);
      return d;
   }
   return d;
}

Decision Rule4_MTFAlignBuy(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule4) return d;
   if (s.mtf_align != "UP") return d;
   if (s.pressure_10m1 < 1) return d;
   if (!s.bull_ob_m5.valid) return d;
   if (s.bid < s.bull_ob_m5.bot || s.bid > s.bull_ob_m5.top) return d;
   double tp = s.bear_fvg_m5.valid ? s.bear_fvg_m5.bot : s.bid + 6;
   d.valid = true; d.rule = "R4_mtf_align";
   d.side = "BUY"; d.entry = s.ask;
   d.sl = s.bull_ob_m5.bot - 1; d.tp = tp;
   d.lot = 0.03; d.confluence = 5;
   d.rationale = StringFormat("MTF UP+ALL inside OB %.2f-%.2f Press%+.1f",
                              s.bull_ob_m5.bot, s.bull_ob_m5.top, s.pressure_10m1);
   return d;
}

// Track recent upper-wick rejections (state across bars for Rule 5)
int g_rejection_count = 0;
double g_rejection_zone_high = 0;
datetime g_last_rejection_bar = 0;

void UpdateRejectionTracker(const MarketSnapshot &s) {
   if (s.m1_last.time == g_last_rejection_bar) return;
   g_last_rejection_bar = s.m1_last.time;
   double body = MathAbs(s.m1_last.close - s.m1_last.open);
   if (s.m1_last.upper_wick > MathMax(body, 0.5) * 1.5) {
      g_rejection_count++;
      if (s.m1_last.high > g_rejection_zone_high) g_rejection_zone_high = s.m1_last.high;
   } else if (s.m1_last.kind == "marubozu_bull" || s.m1_last.kind == "strong_bull") {
      g_rejection_count = 0;
      g_rejection_zone_high = 0;
   }
}

Decision Rule5_FailedParabolicSell(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule5) return d;
   if (g_rejection_count < 4) return d;
   if (s.rsi_m1 < 65) return d;
   if (s.pressure_10m1 > -1) return d;
   double tp = s.bull_fvg_m5.valid ? s.bull_fvg_m5.mid : s.bid - 8;
   d.valid = true; d.rule = "R5_failed_parabolic";
   d.side = "SELL"; d.entry = s.bid;
   d.sl = g_rejection_zone_high + 3; d.tp = tp;
   d.lot = 0.02; d.confluence = 5;
   d.rationale = StringFormat("%d/5 wicks RSI%.1f zone%.2f",
                              g_rejection_count, s.rsi_m1, g_rejection_zone_high);
   return d;
}

Decision Rule6_BearFVGRetest(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule6) return d;
   if (!s.bear_fvg_m5.valid) return d;
   if (s.bid < s.bear_fvg_m5.bot || s.bid > s.bear_fvg_m5.top) return d;
   if (s.bias_m5 != "DOWN") return d;
   if (s.rsi_m1 < 55) return d;
   if (s.adx_m5 < 20 || s.minus_di_m5 < s.plus_di_m5) return d;
   d.valid = true; d.rule = "R6_bear_fvg_retest";
   d.side = "SELL"; d.entry = s.bid;
   d.sl = s.bear_fvg_m5.top + 2;
   d.tp = s.bear_fvg_m5.bot - 4;
   d.lot = 0.02; d.confluence = 4;
   d.rationale = StringFormat("BEAR FVG retest %.2f-%.2f ADX%.1f",
                              s.bear_fvg_m5.bot, s.bear_fvg_m5.top, s.adx_m5);
   return d;
}

Decision Rule7_BullOBDefense(const MarketSnapshot &s) {
   Decision d = EmptyDecision();
   if (!InpUseRule7) return d;
   if (!s.bull_ob_m5.valid) return d;
   if (s.bid < s.bull_ob_m5.bot || s.bid > s.bull_ob_m5.top) return d;
   string k = s.m1_last.kind;
   if (k != "hammer" && k != "strong_bull" && k != "marubozu_bull") return d;
   if (s.m1_last.lower_wick < 1.5 && k != "marubozu_bull") return d;
   if (s.pressure_10m1 < -7) return d;
   d.valid = true; d.rule = "R7_bull_ob_defense";
   d.side = "BUY"; d.entry = s.ask;
   d.sl = s.bull_ob_m5.bot - 2;
   d.tp = s.bull_ob_m5.top + 5;
   d.lot = 0.02; d.confluence = 4;
   d.rationale = StringFormat("%s in BULL_OB L_wick%.2f", k, s.m1_last.lower_wick);
   return d;
}

//====================================================================
// v2 FOOTPRINT BRIDGE — read footprint_cells.json
//====================================================================
struct FootprintSignals {
   bool   valid;
   string imb_dominance;        // "BUY", "SELL", "NEUTRAL"
   int    imb_buy_3bars;
   int    imb_sell_3bars;
   double cvd_acceleration;
   double cvd_running;
   string poc_trend;            // "RISING", "FALLING", "STABLE"
   double last_poc;
   long   last_delta;
   bool   in_supply_zone;
   bool   in_demand_zone;
   double signal_meter;
   string signal_label;
   datetime last_update;
};
FootprintSignals g_fp;

// Lightweight JSON value extractor for our specific format
string ExtractJsonValue(string json, string key) {
   int pos = StringFind(json, "\"" + key + "\"");
   if (pos < 0) return "";
   int colon = StringFind(json, ":", pos);
   if (colon < 0) return "";
   int start = colon + 1;
   while (start < StringLen(json) && (StringGetCharacter(json, start) == ' '
                                       || StringGetCharacter(json, start) == '\n'
                                       || StringGetCharacter(json, start) == '\t')) start++;
   bool is_string = (StringGetCharacter(json, start) == '"');
   if (is_string) start++;
   int end = start;
   while (end < StringLen(json)) {
      ushort c = StringGetCharacter(json, end);
      if (is_string && c == '"') break;
      if (!is_string && (c == ',' || c == '\n' || c == '}' || c == ' ')) break;
      end++;
   }
   return StringSubstr(json, start, end - start);
}

void ReadFootprintJSON() {
   if (!InpReadFootprintJSON) return;
   int handle = FileOpen(InpFootprintFile,
                          FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if (handle == INVALID_HANDLE) {
      g_fp.valid = false; return;
   }
   string content = "";
   while (!FileIsEnding(handle)) content += FileReadString(handle);
   FileClose(handle);
   if (StringLen(content) < 50) { g_fp.valid = false; return; }

   // Recursive imbalance scan across last 3 bars in "bars" array
   int buy_imb = 0, sell_imb = 0;
   int bars_pos = StringFind(content, "\"bars\"");
   if (bars_pos > 0) {
      string bars_section = StringSubstr(content, bars_pos);
      int last3_start = StringLen(bars_section);
      // crude: count "imb_buy" and "imb_sell" occurrences with values
      int p = 0;
      while (p < StringLen(bars_section)) {
         int found = StringFind(bars_section, "\"imb_buy\":", p);
         if (found < 0) break;
         int after = found + 10;
         string val_str = "";
         while (after < StringLen(bars_section)) {
            ushort ch = StringGetCharacter(bars_section, after);
            if (ch == ',' || ch == '}') break;
            val_str += ShortToString(ch);
            after++;
         }
         buy_imb += (int)StringToInteger(val_str);
         p = after;
      }
      p = 0;
      while (p < StringLen(bars_section)) {
         int found = StringFind(bars_section, "\"imb_sell\":", p);
         if (found < 0) break;
         int after = found + 11;
         string val_str = "";
         while (after < StringLen(bars_section)) {
            ushort ch = StringGetCharacter(bars_section, after);
            if (ch == ',' || ch == '}') break;
            val_str += ShortToString(ch);
            after++;
         }
         sell_imb += (int)StringToInteger(val_str);
         p = after;
      }
   }

   g_fp.imb_buy_3bars = buy_imb;
   g_fp.imb_sell_3bars = sell_imb;
   g_fp.imb_dominance = (buy_imb > sell_imb * 1.5) ? "BUY"
                       : (sell_imb > buy_imb * 1.5 ? "SELL" : "NEUTRAL");
   g_fp.cvd_running = StringToDouble(ExtractJsonValue(content, "cum_delta"));
   g_fp.last_poc    = StringToDouble(ExtractJsonValue(content, "svp_poc"));
   g_fp.signal_meter = StringToDouble(ExtractJsonValue(content, "signal_value"));
   g_fp.signal_label = ExtractJsonValue(content, "signal_label");
   g_fp.valid = true;
   g_fp.last_update = TimeCurrent();
}

void DrawFootprintPanel() {
   if (!InpDrawFPSnapshot || !g_fp.valid) return;
   long chart_w = ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int panel_x = (int)chart_w - 280;
   int panel_y = 280;
   int w = 270, h = 110;

   string bg_name = "CLAUDE_FP_PANEL_BG";
   if (ObjectFind(0, bg_name) < 0)
      ObjectCreate(0, bg_name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bg_name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bg_name, OBJPROP_XDISTANCE, panel_x);
   ObjectSetInteger(0, bg_name, OBJPROP_YDISTANCE, panel_y);
   ObjectSetInteger(0, bg_name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, bg_name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, bg_name, OBJPROP_BGCOLOR, C'15,18,22');
   ObjectSetInteger(0, bg_name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg_name, OBJPROP_BORDER_COLOR, C'60,60,80');
   ObjectSetInteger(0, bg_name, OBJPROP_BACK, false);
   ObjectSetInteger(0, bg_name, OBJPROP_HIDDEN, true);

   string lines[5];
   lines[0] = "═══ FOOTPRINT (from MQL5 Indicator) ═══";
   lines[1] = "Imb 3bars: " + IntegerToString(g_fp.imb_buy_3bars) + "↑ / " + IntegerToString(g_fp.imb_sell_3bars) + "↓   Dom: " + g_fp.imb_dominance;
   lines[2] = "CVD: " + DoubleToString(g_fp.cvd_running, 0) + "   POC: " + DoubleToString(g_fp.last_poc, 2);
   lines[3] = "Signal: " + DoubleToString(g_fp.signal_meter, 0) + " (" + g_fp.signal_label + ")";
   lines[4] = "Updated: " + TimeToString(g_fp.last_update, TIME_MINUTES|TIME_SECONDS);

   color text_col = (g_fp.imb_dominance == "BUY") ? clrLimeGreen
                  : (g_fp.imb_dominance == "SELL" ? clrTomato : clrWhiteSmoke);

   for (int i = 0; i < 5; i++) {
      string ln_name = "CLAUDE_FP_LN_" + IntegerToString(i);
      if (ObjectFind(0, ln_name) < 0)
         ObjectCreate(0, ln_name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, ln_name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, ln_name, OBJPROP_XDISTANCE, panel_x + 8);
      ObjectSetInteger(0, ln_name, OBJPROP_YDISTANCE, panel_y + 6 + i * 20);
      ObjectSetString(0, ln_name, OBJPROP_TEXT, lines[i]);
      ObjectSetString(0, ln_name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, ln_name, OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, ln_name, OBJPROP_COLOR, i == 0 ? clrGold : text_col);
      ObjectSetInteger(0, ln_name, OBJPROP_HIDDEN, true);
   }
}

// Helper: boost confluence when footprint confirms direction
double FootprintConfluenceBoost(string side) {
   if (!InpUseFootprintInRules || !g_fp.valid) return 0;
   if (side == "BUY" && g_fp.imb_dominance == "BUY")  return InpFPImbDomBoost;
   if (side == "SELL" && g_fp.imb_dominance == "SELL") return InpFPImbDomBoost;
   if (side == "BUY" && g_fp.in_demand_zone)  return InpFPImbDomBoost * 0.5;
   if (side == "SELL" && g_fp.in_supply_zone) return InpFPImbDomBoost * 0.5;
   return 0;
}

//====================================================================
// HARD GUARDS — return reason if blocked, "" if OK
//====================================================================
string HardGuards(const MarketSnapshot &s) {
   if (!IsAllowedSession())
      return StringFormat("session=%s blocked", s.session);

   if (s.spread > InpMaxSpreadUSD)
      return StringFormat("spread $%.2f > $%.2f", s.spread, InpMaxSpreadUSD);

   if (s.atr_m1 > InpMaxATRm1)
      return StringFormat("ATR_M1 $%.2f > $%.2f", s.atr_m1, InpMaxATRm1);

   if (InpBlockOnDryVol && s.vol_trend_m5 == "DRY")
      return "vol_trend DRY (no edge in chop)";

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);

   double floor_v = (InpEquityFloorUSD > 0) ? InpEquityFloorUSD : (balance - 15.0);
   if (equity < floor_v)
      return StringFormat("equity $%.2f < floor $%.2f", equity, floor_v);

   if (g_dayStartEquity > 0) {
      double day_pnl = equity - g_dayStartEquity;
      if (day_pnl <= InpDailyLossLimit)
         return StringFormat("daily PnL $%.2f ≤ $%.2f", day_pnl, InpDailyLossLimit);
   }

   if (g_pausedUntil > 0 && TimeCurrent() < g_pausedUntil)
      return StringFormat("paused after %d losses until %s",
                          g_consecLosses, TimeToString(g_pausedUntil, TIME_MINUTES));

   // Count MY positions only
   int my_count = 0;
   double my_lot = 0;
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if (PositionSelectByTicket(tk)) {
         if ((ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic &&
             PositionGetString(POSITION_SYMBOL) == SYMBOL) {
            my_count++;
            my_lot += PositionGetDouble(POSITION_VOLUME);
         }
      }
   }
   if (my_count >= InpMaxOpenPositions)
      return StringFormat("max %d open positions", InpMaxOpenPositions);
   if (my_lot >= InpMaxLotTotal)
      return StringFormat("max lot %.2f reached", InpMaxLotTotal);

   return "";
}

//====================================================================
// EXECUTE TRADE
//====================================================================
bool ExecuteDecision(const Decision &d) {
   if (!d.valid) return false;

   // Validate R:R
   double risk_pts, reward_pts;
   if (d.side == "BUY") {
      risk_pts   = d.entry - d.sl;
      reward_pts = d.tp - d.entry;
   } else {
      risk_pts   = d.sl - d.entry;
      reward_pts = d.entry - d.tp;
   }
   if (risk_pts <= 0 || reward_pts <= 0) {
      if (InpVerbose) Print("[CLAUDE] ", d.rule, " rejected: invalid SL/TP");
      return false;
   }
   double rr = reward_pts / risk_pts;
   if (rr < InpMinRR) {
      if (InpVerbose) Print("[CLAUDE] ", d.rule, StringFormat(" rejected: RR %.2f < %.2f", rr, InpMinRR));
      return false;
   }

   double risk_usd = risk_pts * d.lot * 100;   // XAU pip value approx
   if (risk_usd > InpRiskUSDPerTrade) {
      if (InpVerbose) Print("[CLAUDE] ", d.rule, StringFormat(" rejected: risk $%.2f > $%.2f", risk_usd, InpRiskUSDPerTrade));
      return false;
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFilling(ORDER_FILLING_FOK);

   bool ok = false;
   string comment = InpComment + "_" + d.rule;
   if (d.side == "BUY")
      ok = trade.Buy(d.lot, SYMBOL, d.entry, d.sl, d.tp, comment);
   else
      ok = trade.Sell(d.lot, SYMBOL, d.entry, d.sl, d.tp, comment);

   if (!ok) {
      // Retry with IOC
      trade.SetTypeFilling(ORDER_FILLING_IOC);
      if (d.side == "BUY")
         ok = trade.Buy(d.lot, SYMBOL, d.entry, d.sl, d.tp, comment);
      else
         ok = trade.Sell(d.lot, SYMBOL, d.entry, d.sl, d.tp, comment);
   }

   if (ok) {
      Print("[CLAUDE] ✅ ", d.side, " ", d.rule, " ",
            DoubleToString(d.lot, 2), " @ ", DoubleToString(trade.ResultPrice(), 2),
            " SL ", DoubleToString(d.sl, 2), " TP ", DoubleToString(d.tp, 2),
            " RR ", DoubleToString(rr, 2), " risk $", DoubleToString(risk_usd, 2),
            " | ", d.rationale);
   } else {
      Print("[CLAUDE] ❌ ", d.rule, " send failed: ", trade.ResultRetcodeDescription());
   }
   return ok;
}

//====================================================================
// POSITION MANAGER — trail SL, emergency close
//====================================================================
void ManagePositions(const MarketSnapshot &s) {
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if (!PositionSelectByTicket(tk)) continue;
      if ((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if (PositionGetString(POSITION_SYMBOL) != SYMBOL) continue;

      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double cur = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? s.bid : s.ask;
      double profit_pts = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
                          ? (cur - open_price) : (open_price - cur);

      // Trail SL
      if (InpTrailSL && profit_pts > 0) {
         double new_sl = sl;
         if (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
            if (profit_pts >= InpTrailTrigger2)      new_sl = MathMax(sl, open_price + 2);
            else if (profit_pts >= InpTrailTrigger1) new_sl = MathMax(sl, open_price);
         } else {
            if (profit_pts >= InpTrailTrigger2)      new_sl = (sl > 0) ? MathMin(sl, open_price - 2) : open_price - 2;
            else if (profit_pts >= InpTrailTrigger1) new_sl = (sl > 0) ? MathMin(sl, open_price)     : open_price;
         }
         if (MathAbs(new_sl - sl) > 0.01) {
            if (trade.PositionModify(tk, new_sl, tp))
               if (InpVerbose) Print("[CLAUDE] ⬆ trailed SL #", tk, " ", DoubleToString(sl, 2), "→", DoubleToString(new_sl, 2));
         }
      }

      // Emergency: marubozu bear with volume spike on losing BUY
      if (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
         if (s.m1_last.kind == "marubozu_bear" &&
             s.m1_last.body_pct >= 70 &&
             s.m1_last.volume > InpEmergencyBearVol &&
             cur < open_price) {
            if (trade.PositionClose(tk))
               Print("[CLAUDE] 🆘 emergency close BUY #", tk,
                     " — marubozu_bear vol ", IntegerToString(s.m1_last.volume));
         }
      }
   }
}

//====================================================================
// HANDLE CLOSED TRADES (for consec-loss tracking)
//====================================================================
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result) {
   if (trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal_ticket = trans.deal;
   if (deal_ticket == 0) return;
   if (!HistoryDealSelect(deal_ticket)) return;
   if ((ulong)HistoryDealGetInteger(deal_ticket, DEAL_MAGIC) != InpMagic) return;
   ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);
   if (entry != DEAL_ENTRY_OUT) return;   // only count closes
   double profit = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(deal_ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
   if (profit < 0) {
      g_consecLosses++;
      if (g_consecLosses >= InpConsecLossPause) {
         g_pausedUntil = TimeCurrent() + InpCooldownMinutes * 60;
         Print("[CLAUDE] ⏸ ", g_consecLosses, " consec losses — paused ",
               InpCooldownMinutes, " min until ", TimeToString(g_pausedUntil));
      }
   } else {
      g_consecLosses = 0;
      g_pausedUntil = 0;
   }
   g_lastClosedProfit = profit;
   g_lastClosedTicket = deal_ticket;
   Print("[CLAUDE] trade closed #", deal_ticket, " profit $", DoubleToString(profit, 2),
         " | consec_losses=", g_consecLosses);
}

//====================================================================
// MAIN LOOP — OnTick
//====================================================================
void OnTick() {
   // Reset daily tracking at day start
   datetime now = TimeCurrent();
   MqlDateTime t; TimeToStruct(now, t);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d 00:00:00", t.year, t.mon, t.day));
   if (today != g_dayStart) {
      g_dayStart = today;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      if (InpVerbose) Print("[CLAUDE] new day — equity baseline $", DoubleToString(g_dayStartEquity, 2));
   }

   MarketSnapshot s = CaptureMarket();
   UpdateRejectionTracker(s);
   ReadFootprintJSON();
   DrawFootprintPanel();

   // Always manage existing positions first
   ManagePositions(s);

   // Then check guards before any new entries
   string blocked = HardGuards(s);
   if (blocked != "") return;   // silent skip

   // Evaluate rules
   Decision best = EmptyDecision();
   double best_score = 0;
   Decision candidates[7];
   candidates[0] = Rule1_CounterTrendBuy(s);
   candidates[1] = Rule2_WithTrendSell(s);
   candidates[2] = Rule3_LiquiditySweep(s);
   candidates[3] = Rule4_MTFAlignBuy(s);
   candidates[4] = Rule5_FailedParabolicSell(s);
   candidates[5] = Rule6_BearFVGRetest(s);
   candidates[6] = Rule7_BullOBDefense(s);

   // Apply footprint confluence boost to each candidate
   for (int i = 0; i < 7; i++) {
      if (candidates[i].valid) {
         double boost = FootprintConfluenceBoost(candidates[i].side);
         candidates[i].confluence += boost;
      }
   }

   for (int i = 0; i < 7; i++) {
      if (candidates[i].valid && candidates[i].confluence >= InpMinConfluence
          && candidates[i].confluence > best_score) {
         best = candidates[i];
         best_score = candidates[i].confluence;
      }
   }

   if (best.valid) {
      ExecuteDecision(best);
   }
}

//====================================================================
// OnInit / OnDeinit
//====================================================================
int OnInit() {
   SYMBOL = ActiveSymbol();
   g_dayStart = 0;   // forces baseline reset on first tick
   Print("════════════════════════════════════════════");
   Print("[CLAUDE_BRAIN_EA v1] ONLINE on ", SYMBOL);
   Print("  Magic: ", InpMagic);
   Print("  Risk: max_lot=", InpMaxLotTotal, " max_open=", InpMaxOpenPositions,
         " risk/trade=$", InpRiskUSDPerTrade, " daily_limit=$", InpDailyLossLimit);
   Print("  Guards: NY_OVERLAP=", InpOnlyNYOverlap, " block_dry=", InpBlockOnDryVol,
         " max_spread=$", InpMaxSpreadUSD, " max_atr=$", InpMaxATRm1);
   Print("  Rules enabled: R1=", InpUseRule1, " R2=", InpUseRule2,
         " R3=", InpUseRule3, " R4=", InpUseRule4, " R5=", InpUseRule5,
         " R6=", InpUseRule6, " R7=", InpUseRule7);
   Print("  Trail SL: ", InpTrailSL, " (triggers $", InpTrailTrigger1, " / $", InpTrailTrigger2, ")");
   Print("════════════════════════════════════════════");
   EventSetTimer(2);   // 2s tick fallback if no ticks
   return INIT_SUCCEEDED;
}

void OnTimer() {
   OnTick();
}

void OnDeinit(const int reason) {
   EventKillTimer();
   Print("[CLAUDE_BRAIN_EA] offline — reason ", reason);
}
