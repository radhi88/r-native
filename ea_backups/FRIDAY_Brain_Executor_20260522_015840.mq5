//+------------------------------------------------------------------+
//|  FRIDAY_Brain_Executor.mq5                                       |
//|  Pure executor — reads orders + drawings from FRIDAY Brain v2    |
//|  Places trades, draws agent objects on chart, shows indicators   |
//|                                                                  |
//|  Brain endpoint (informational): http://localhost:5055/api/brain |
//|  Brain writes JSON: <Common>/Files/friday_brain_orders.json      |
//+------------------------------------------------------------------+
#property copyright "FRIDAY 2026 — Radhi Amash"
#property version   "1.00"
#property strict
#property description "Executes trades dictated by the FRIDAY LLM Brain. Magic=20260600. Listens to Common/Files/friday_brain_orders.json."

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/OrderInfo.mqh>
#include <Trade/SymbolInfo.mqh>

CTrade        Trade;
CPositionInfo Pos;
COrderInfo    Ord;
CSymbolInfo   Sym;

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group  "═══ Identity ═══"
input string  InpSymbol            = "XAUUSDm";
input long    InpMagic             = 20260600;
input string  InpComment           = "FRIDAY-Brain";

input group  "═══ Brain bridge ═══"
input string  InpBrainJson         = "friday_brain_orders.json";
input string  InpKillFile          = "kill_switch.txt";
input bool    InpUseCommonFiles    = true;
input int     InpCheckEverySeconds = 3;
input bool    InpDryRun            = false;        // true = simulate only
input int     InpMaxEpochAgeSec    = 60;            // ignore brain JSON older than this

input group  "═══ Risk caps ═══"
input double  InpMaxLot            = 0.05;
input double  InpMinLot            = 0.01;
input int     InpMaxOpenOrders     = 4;             // pendings + positions
input int     InpMinSecondsBetween = 20;
input int     InpMaxSpreadPoints   = 600;
input bool    InpRequireSL         = true;

input group  "═══ Drawing ═══"
input bool    InpDrawAgentObjects  = true;
input bool    InpDrawLevels        = true;
input bool    InpDrawTradeBox      = true;          // entry/SL/TP box

input group  "═══ Indicators ═══"
input bool    InpShowEMA           = true;          // EMA 8/21/55/200
input bool    InpShowBB            = true;          // Bollinger 20,2
input bool    InpShowVWAP          = false;
input bool    InpShowDashboard     = true;

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
long          g_last_epoch_processed = 0;
datetime      g_last_order_time      = 0;
string        g_obj_prefix           = "FRIDAY_BRAIN_";

int           h_ema8 = INVALID_HANDLE, h_ema21 = INVALID_HANDLE;
int           h_ema55 = INVALID_HANDLE, h_ema200 = INVALID_HANDLE;
int           h_atr  = INVALID_HANDLE, h_rsi   = INVALID_HANDLE;
int           h_bb   = INVALID_HANDLE;

// Stats
long          g_orders_placed = 0;
long          g_orders_rejected = 0;
string        g_last_reason = "";
string        g_last_action = "—";

//+------------------------------------------------------------------+
//| Helpers — file I/O                                               |
//+------------------------------------------------------------------+
bool ReadCommonFile(const string fname, string &out) {
   int flags = FILE_READ | FILE_TXT | FILE_ANSI;
   if (InpUseCommonFiles) flags |= FILE_COMMON;
   int h = FileOpen(fname, flags);
   if (h == INVALID_HANDLE) return false;
   out = "";
   while (!FileIsEnding(h)) out += FileReadString(h) + "\n";
   FileClose(h);
   return StringLen(out) > 0;
}

bool KillSwitchActive() {
   int flags = FILE_READ;
   if (InpUseCommonFiles) flags |= FILE_COMMON;
   int h = FileOpen(InpKillFile, flags);
   if (h != INVALID_HANDLE) { FileClose(h); return true; }
   // Also check non-common path (the brain creates it in C:\Users\Radhi\MT5\)
   h = FileOpen(InpKillFile, FILE_READ);
   if (h != INVALID_HANDLE) { FileClose(h); return true; }
   return false;
}

//+------------------------------------------------------------------+
//| Minimal JSON extractors (no nested-array parser needed for       |
//| our flat schema; objects extracted by brace counting).           |
//+------------------------------------------------------------------+
string JsonObj(const string &text, const string key) {
   string pat = "\""+key+"\":";
   int i = StringFind(text, pat);
   if (i < 0) return "";
   i += StringLen(pat);
   // Skip whitespace
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++; else break;
   }
   if (i >= StringLen(text) || StringGetCharacter(text, i) != '{') return "";
   int start = i;
   int depth = 0;
   bool in_str = false;
   bool esc = false;
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (esc) { esc = false; i++; continue; }
      if (c == '\\') { esc = true; i++; continue; }
      if (c == '"') { in_str = !in_str; i++; continue; }
      if (in_str)  { i++; continue; }
      if (c == '{') depth++;
      else if (c == '}') { depth--; if (depth == 0) return StringSubstr(text, start, i - start + 1); }
      i++;
   }
   return "";
}

string JsonArray(const string &text, const string key) {
   string pat = "\""+key+"\":";
   int i = StringFind(text, pat);
   if (i < 0) return "";
   i += StringLen(pat);
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++; else break;
   }
   if (i >= StringLen(text) || StringGetCharacter(text, i) != '[') return "";
   int start = i;
   int depth = 0;
   bool in_str = false, esc = false;
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (esc) { esc = false; i++; continue; }
      if (c == '\\') { esc = true; i++; continue; }
      if (c == '"') { in_str = !in_str; i++; continue; }
      if (in_str)  { i++; continue; }
      if (c == '[') depth++;
      else if (c == ']') { depth--; if (depth == 0) return StringSubstr(text, start, i - start + 1); }
      i++;
   }
   return "";
}

string JsonStr(const string &text, const string key) {
   string pat = "\""+key+"\":\"";
   int i = StringFind(text, pat);
   if (i < 0) return "";
   i += StringLen(pat);
   string out = "";
   bool esc = false;
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (esc) { out += ShortToString(c); esc = false; i++; continue; }
      if (c == '\\') { esc = true; i++; continue; }
      if (c == '"') break;
      out += ShortToString(c);
      i++;
   }
   return out;
}

double JsonNum(const string &text, const string key) {
   string pat = "\""+key+"\":";
   int i = StringFind(text, pat);
   if (i < 0) return 0.0;
   i += StringLen(pat);
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++; else break;
   }
   string num = "";
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      bool ok = (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E';
      if (!ok) break;
      num += ShortToString(c);
      i++;
   }
   return (StringLen(num) > 0) ? StringToDouble(num) : 0.0;
}

bool JsonBool(const string &text, const string key) {
   string pat = "\""+key+"\":";
   int i = StringFind(text, pat);
   if (i < 0) return false;
   i += StringLen(pat);
   while (i < StringLen(text)) {
      ushort c = StringGetCharacter(text, i);
      if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++; else break;
   }
   return (i+4 <= StringLen(text)) && (StringSubstr(text, i, 4) == "true");
}

//+------------------------------------------------------------------+
//| Order management                                                 |
//+------------------------------------------------------------------+
int CountOurOrders() {
   int n = 0;
   for (int i = OrdersTotal() - 1; i >= 0; i--) {
      ulong t = OrderGetTicket(i);
      if (!t) continue;
      if (OrderGetString(ORDER_SYMBOL) != InpSymbol) continue;
      if ((long)OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      n++;
   }
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong t = PositionGetTicket(i);
      if (!t) continue;
      if (PositionGetString(POSITION_SYMBOL) != InpSymbol) continue;
      if ((long)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      n++;
   }
   return n;
}

void CancelAllOurs() {
   for (int i = OrdersTotal() - 1; i >= 0; i--) {
      ulong t = OrderGetTicket(i);
      if (!t) continue;
      if (OrderGetString(ORDER_SYMBOL) != InpSymbol) continue;
      if ((long)OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      if (InpDryRun) Print("[DRY] cancel #", t);
      else { Trade.OrderDelete(t); }
   }
}

bool AlreadyPlacedAtPrice(double price, double tol = 1.0) {
   for (int i = OrdersTotal() - 1; i >= 0; i--) {
      ulong t = OrderGetTicket(i);
      if (!t) continue;
      if (OrderGetString(ORDER_SYMBOL) != InpSymbol) continue;
      if ((long)OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      double p = OrderGetDouble(ORDER_PRICE_OPEN);
      if (MathAbs(p - price) <= tol) return true;
   }
   return false;
}

double ClampLot(double lot) {
   double minL = MathMax(InpMinLot, Sym.LotsMin());
   double maxL = MathMin(InpMaxLot, Sym.LotsMax());
   double step = Sym.LotsStep();
   lot = MathMax(minL, MathMin(maxL, lot));
   lot = MathRound(lot / step) * step;
   return NormalizeDouble(lot, 2);
}

bool PlaceBrainOrder(string side, double entry, double sl, double tp, double lot, string reason) {
   side = side;  // upper
   StringToUpper(side);

   if (CountOurOrders() >= InpMaxOpenOrders) {
      g_last_reason = "max_orders_reached"; return false;
   }
   if (TimeCurrent() - g_last_order_time < InpMinSecondsBetween) {
      g_last_reason = StringFormat("cooldown %ds", (int)(TimeCurrent() - g_last_order_time));
      return false;
   }
   Sym.RefreshRates();
   double spreadPt = (Sym.Ask() - Sym.Bid()) / Sym.Point();
   if (spreadPt > InpMaxSpreadPoints) {
      g_last_reason = StringFormat("spread %dpt > %dpt", (int)spreadPt, InpMaxSpreadPoints);
      return false;
   }
   if (InpRequireSL && sl <= 0) {
      g_last_reason = "no SL — refused (safety)";
      return false;
   }
   if (AlreadyPlacedAtPrice(entry)) {
      g_last_reason = "already placed";
      return false;
   }

   lot = ClampLot(lot);
   if (lot <= 0) { g_last_reason = "lot=0"; return false; }

   double minStop = Sym.StopsLevel() * Sym.Point();
   ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)-1;

   if (side == "BUY") {
      if (entry > Sym.Ask() + minStop)        type = ORDER_TYPE_BUY_STOP;
      else if (entry < Sym.Ask() - minStop)   type = ORDER_TYPE_BUY_LIMIT;
      else { g_last_reason = "BUY too close to ask"; return false; }
      if (sl >= entry || (tp > 0 && tp <= entry)) { g_last_reason = "BUY invalid SL/TP"; return false; }
   } else if (side == "SELL") {
      if (entry < Sym.Bid() - minStop)        type = ORDER_TYPE_SELL_STOP;
      else if (entry > Sym.Bid() + minStop)   type = ORDER_TYPE_SELL_LIMIT;
      else { g_last_reason = "SELL too close to bid"; return false; }
      if (sl <= entry || (tp > 0 && tp >= entry)) { g_last_reason = "SELL invalid SL/TP"; return false; }
   } else {
      g_last_reason = "bad side: " + side; return false;
   }

   string note = InpComment + " " + StringSubstr(reason, 0, 20);

   if (InpDryRun) {
      Print("[DRY] ", side, " ", DoubleToString(entry,2),
            "  SL=", DoubleToString(sl,2),
            "  TP=", DoubleToString(tp,2),
            "  lot=", DoubleToString(lot,2),
            "  type=", EnumToString(type),
            "  | ", note);
      g_orders_placed++;
      g_last_order_time = TimeCurrent();
      g_last_reason = "DRY-RUN ok";
      return true;
   }

   Trade.SetExpertMagicNumber(InpMagic);
   bool ok = Trade.OrderOpen(InpSymbol, type, lot, 0.0, entry, sl, tp,
                              ORDER_TIME_GTC, 0, note);
   if (ok && Trade.ResultRetcode() == TRADE_RETCODE_DONE) {
      Print("[LIVE] ", side, " ", DoubleToString(entry,2),
            " SL=", DoubleToString(sl,2),
            " TP=", DoubleToString(tp,2),
            " lot=", DoubleToString(lot,2),
            " ticket=", Trade.ResultOrder(),
            " | ", note);
      g_orders_placed++;
      g_last_order_time = TimeCurrent();
      g_last_reason = "OK ticket=" + IntegerToString((long)Trade.ResultOrder());
      return true;
   } else {
      g_orders_rejected++;
      g_last_reason = StringFormat("retcode=%d %s", (int)Trade.ResultRetcode(), Trade.ResultRetcodeDescription());
      Print("[FAIL] ", side, " ", DoubleToString(entry,2), " | ", g_last_reason);
      return false;
   }
}

//+------------------------------------------------------------------+
//| Drawing — render brain drawings as MQL5 chart objects            |
//+------------------------------------------------------------------+
void DeleteOurObjects() {
   for (int i = ObjectsTotal(0) - 1; i >= 0; i--) {
      string n = ObjectName(0, i);
      if (StringFind(n, g_obj_prefix) == 0) ObjectDelete(0, n);
   }
}

uint ColorFromHex(string hex) {
   // "#RRGGBB" → BGR (MQL5)
   if (StringGetCharacter(hex,0) == '#') hex = StringSubstr(hex, 1);
   if (StringLen(hex) < 6) return clrAqua;
   int r = (int)StringToInteger("0x" + StringSubstr(hex,0,2));
   int g = (int)StringToInteger("0x" + StringSubstr(hex,2,2));
   int b = (int)StringToInteger("0x" + StringSubstr(hex,4,2));
   return (uint)((b << 16) | (g << 8) | r);
}

datetime BarTimeAgo(int bars_ago) {
   return iTime(InpSymbol, PERIOD_CURRENT, bars_ago);
}

void DrawBrainObjects(const string &drawings_json) {
   if (!InpDrawAgentObjects || StringLen(drawings_json) < 4) return;

   // Iterate { ... } objects inside the array
   int pos = 0;
   int idx = 0;
   while (pos < StringLen(drawings_json)) {
      int s = StringFind(drawings_json, "{", pos);
      if (s < 0) break;
      // Brace-count to find end
      int depth = 0;
      bool in_str = false, esc = false;
      int e = s;
      while (e < StringLen(drawings_json)) {
         ushort c = StringGetCharacter(drawings_json, e);
         if (esc) { esc = false; e++; continue; }
         if (c == '\\') { esc = true; e++; continue; }
         if (c == '"') { in_str = !in_str; e++; continue; }
         if (in_str)  { e++; continue; }
         if (c == '{') depth++;
         else if (c == '}') { depth--; if (depth == 0) break; }
         e++;
      }
      if (e >= StringLen(drawings_json)) break;
      string item = StringSubstr(drawings_json, s, e - s + 1);
      pos = e + 1;

      string type = JsonStr(item, "type");
      string label = JsonStr(item, "label");
      string colorHex = JsonStr(item, "color");
      uint col = StringLen(colorHex) > 0 ? ColorFromHex(colorHex) : clrAqua;
      string objName = g_obj_prefix + IntegerToString(idx) + "_" + type;
      idx++;

      if (type == "hline") {
         double p = JsonNum(item, "price");
         if (p > 0) {
            ObjectCreate(0, objName, OBJ_HLINE, 0, 0, p);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetInteger(0, objName, OBJPROP_WIDTH, 1);
            ObjectSetString(0, objName, OBJPROP_TEXT, "🎨 " + label);
            ObjectSetString(0, objName, OBJPROP_TOOLTIP, label);
         }
      }
      else if (type == "trendline") {
         string fr = JsonObj(item, "from");
         string to = JsonObj(item, "to");
         int b1 = (int)JsonNum(fr, "bars_ago");
         int b2 = (int)JsonNum(to, "bars_ago");
         double p1 = JsonNum(fr, "price");
         double p2 = JsonNum(to, "price");
         datetime t1 = BarTimeAgo(b1);
         datetime t2 = BarTimeAgo(b2);
         if (t1 > 0 && t2 > 0 && p1 > 0 && p2 > 0) {
            ObjectCreate(0, objName, OBJ_TREND, 0, t1, p1, t2, p2);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetInteger(0, objName, OBJPROP_WIDTH, 2);
            ObjectSetInteger(0, objName, OBJPROP_RAY_RIGHT, false);
            ObjectSetString(0, objName, OBJPROP_TEXT, label);
            ObjectSetString(0, objName, OBJPROP_TOOLTIP, "trend " + label);
         }
      }
      else if (type == "zone") {
         double top    = JsonNum(item, "top");
         double bottom = JsonNum(item, "bottom");
         datetime t1 = BarTimeAgo(30);
         datetime t2 = BarTimeAgo(-10);  // extend a bit right
         if (top > 0 && bottom > 0) {
            ObjectCreate(0, objName, OBJ_RECTANGLE, 0, t1, top, t2, bottom);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetInteger(0, objName, OBJPROP_FILL, true);
            ObjectSetInteger(0, objName, OBJPROP_BACK, true);
            ObjectSetInteger(0, objName, OBJPROP_WIDTH, 1);
            ObjectSetString(0, objName, OBJPROP_TEXT, label);
            ObjectSetString(0, objName, OBJPROP_TOOLTIP, "zone " + label);
         }
      }
      else if (type == "fib") {
         double hi = JsonNum(item, "high");
         double lo = JsonNum(item, "low");
         datetime t1 = BarTimeAgo(40);
         datetime t2 = BarTimeAgo(0);
         if (hi > 0 && lo > 0) {
            ObjectCreate(0, objName, OBJ_FIBO, 0, t1, hi, t2, lo);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetString(0, objName, OBJPROP_TEXT, label);
         }
      }
      else if (type == "marker") {
         int ba = (int)JsonNum(item, "bars_ago");
         string shape = JsonStr(item, "shape");
         datetime t  = BarTimeAgo(ba);
         double p    = iClose(InpSymbol, PERIOD_CURRENT, ba);
         if (t > 0) {
            int arrowCode = 159;  // dot
            if      (shape == "arrowUp")   arrowCode = 233;
            else if (shape == "arrowDown") arrowCode = 234;
            else if (shape == "circle")    arrowCode = 159;
            ObjectCreate(0, objName, OBJ_ARROW, 0, t, p);
            ObjectSetInteger(0, objName, OBJPROP_ARROWCODE, arrowCode);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetInteger(0, objName, OBJPROP_WIDTH, 2);
            ObjectSetString(0, objName, OBJPROP_TEXT, label);
         }
      }
      else if (type == "channel") {
         string fr = JsonObj(item, "from");
         string to = JsonObj(item, "to");
         int b1 = (int)JsonNum(fr, "bars_ago");
         int b2 = (int)JsonNum(to, "bars_ago");
         double p1 = JsonNum(fr, "price");
         double p2 = JsonNum(to, "price");
         double w  = JsonNum(item, "width");
         datetime t1 = BarTimeAgo(b1);
         datetime t2 = BarTimeAgo(b2);
         if (t1 > 0 && t2 > 0) {
            ObjectCreate(0, objName, OBJ_CHANNEL, 0, t1, p1 + w/2, t2, p2 + w/2, t1, p1 - w/2);
            ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
            ObjectSetInteger(0, objName, OBJPROP_WIDTH, 2);
            ObjectSetString(0, objName, OBJPROP_TEXT, label);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Draw planned trade box                                           |
//+------------------------------------------------------------------+
void DrawTradeBox(double entry, double sl, double tp, string side) {
   string box = g_obj_prefix + "TRADE_";
   for (int i = ObjectsTotal(0) - 1; i >= 0; i--) {
      string n = ObjectName(0, i);
      if (StringFind(n, box) == 0) ObjectDelete(0, n);
   }
   if (!InpDrawTradeBox) return;
   if (entry <= 0) return;
   datetime t1 = BarTimeAgo(10);
   datetime t2 = BarTimeAgo(-20);

   // entry line (blue, solid, thick)
   string e = box + "entry";
   ObjectCreate(0, e, OBJ_HLINE, 0, 0, entry);
   ObjectSetInteger(0, e, OBJPROP_COLOR, clrDodgerBlue);
   ObjectSetInteger(0, e, OBJPROP_WIDTH, 2);
   ObjectSetString(0, e, OBJPROP_TEXT, "🧠 ENTRY " + side);

   if (sl > 0) {
      string ss = box + "sl";
      ObjectCreate(0, ss, OBJ_HLINE, 0, 0, sl);
      ObjectSetInteger(0, ss, OBJPROP_COLOR, clrRed);
      ObjectSetInteger(0, ss, OBJPROP_WIDTH, 2);
      ObjectSetString(0, ss, OBJPROP_TEXT, "SL");
   }
   if (tp > 0) {
      string tt = box + "tp";
      ObjectCreate(0, tt, OBJ_HLINE, 0, 0, tp);
      ObjectSetInteger(0, tt, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, tt, OBJPROP_WIDTH, 2);
      ObjectSetString(0, tt, OBJPROP_TEXT, "TP");
   }
}

//+------------------------------------------------------------------+
//| Indicators — EMA stack, BB                                       |
//+------------------------------------------------------------------+
int InitIndicators() {
   if (InpShowEMA) {
      h_ema8   = iMA(InpSymbol, _Period, 8,   0, MODE_EMA, PRICE_CLOSE);
      h_ema21  = iMA(InpSymbol, _Period, 21,  0, MODE_EMA, PRICE_CLOSE);
      h_ema55  = iMA(InpSymbol, _Period, 55,  0, MODE_EMA, PRICE_CLOSE);
      h_ema200 = iMA(InpSymbol, _Period, 200, 0, MODE_EMA, PRICE_CLOSE);
      ChartIndicatorAdd(0, 0, h_ema8);
      ChartIndicatorAdd(0, 0, h_ema21);
      ChartIndicatorAdd(0, 0, h_ema55);
      ChartIndicatorAdd(0, 0, h_ema200);
   }
   if (InpShowBB) {
      h_bb = iBands(InpSymbol, _Period, 20, 0, 2.0, PRICE_CLOSE);
      ChartIndicatorAdd(0, 0, h_bb);
   }
   h_atr = iATR(InpSymbol, _Period, 14);
   h_rsi = iRSI(InpSymbol, _Period, 14, PRICE_CLOSE);
   return INIT_SUCCEEDED;
}

double LastBuf(int handle, int shift = 0) {
   if (handle == INVALID_HANDLE) return 0;
   double b[]; ArraySetAsSeries(b, true);
   if (CopyBuffer(handle, 0, shift, 1, b) <= 0) return 0;
   return b[0];
}

//+------------------------------------------------------------------+
//| Dashboard panel (comment + label)                                |
//+------------------------------------------------------------------+
void RenderDashboard(string brain_text) {
   if (!InpShowDashboard) { Comment(""); return; }

   Sym.RefreshRates();
   double spreadPt = (Sym.Ask() - Sym.Bid()) / Sym.Point();
   double atr      = LastBuf(h_atr);
   double rsi      = LastBuf(h_rsi);
   double ema8     = LastBuf(h_ema8);
   double ema21    = LastBuf(h_ema21);
   double ema200   = LastBuf(h_ema200);

   double brain_epoch  = JsonNum(brain_text, "epoch");
   double brain_cycle  = JsonNum(brain_text, "cycle");
   int    brain_age    = brain_epoch > 0 ? (int)(TimeCurrent() - (datetime)brain_epoch) : -1;
   string decObj       = JsonObj(brain_text, "decision");
   string final_action = JsonStr(decObj, "final_action");
   string side         = JsonStr(decObj, "side");
   double entry        = JsonNum(decObj, "entry");
   double sl           = JsonNum(decObj, "sl");
   double tp           = JsonNum(decObj, "tp");
   string reason       = JsonStr(decObj, "reason");

   string emaTrend = "—";
   if (ema8 > 0 && ema21 > 0 && ema200 > 0) {
      if (ema8 > ema21 && ema21 > ema200) emaTrend = "↑ صاعد قوي";
      else if (ema8 < ema21 && ema21 < ema200) emaTrend = "↓ هابط قوي";
      else emaTrend = "⇆ متذبذب";
   }

   string txt = StringFormat(
      "═════ FRIDAY Brain Executor ═════\n" +
      "Symbol: %s   Magic: %d   Mode: %s\n" +
      "Spread: %dpt   ATR: %.0fpt   RSI: %.1f   Trend: %s\n" +
      "─────────────────────────────────\n" +
      "Brain Cycle: C%d   Age: %ds %s\n" +
      "Decision: %s %s\n" +
      "Entry: %s   SL: %s   TP: %s\n" +
      "Reason: %s\n" +
      "─────────────────────────────────\n" +
      "Open Orders: %d/%d   Placed: %d   Rejected: %d\n" +
      "Last: %s — %s",
      InpSymbol, (int)InpMagic, (InpDryRun ? "DRY-RUN" : "LIVE"),
      (int)spreadPt, atr/Sym.Point(), rsi, emaTrend,
      (int)brain_cycle, brain_age, (brain_age > InpMaxEpochAgeSec ? "⚠STALE" : "✓"),
      final_action, side,
      (entry > 0 ? DoubleToString(entry,2) : "—"),
      (sl    > 0 ? DoubleToString(sl,2)    : "—"),
      (tp    > 0 ? DoubleToString(tp,2)    : "—"),
      StringSubstr(reason, 0, 80),
      CountOurOrders(), InpMaxOpenOrders, (int)g_orders_placed, (int)g_orders_rejected,
      g_last_action, g_last_reason
   );
   Comment(txt);
}

//+------------------------------------------------------------------+
//| Main brain JSON processor                                        |
//+------------------------------------------------------------------+
void ProcessBrainJson() {
   string txt;
   if (!ReadCommonFile(InpBrainJson, txt)) {
      g_last_reason = "brain JSON not found";
      RenderDashboard("");
      return;
   }

   // Epoch check
   long epoch = (long)JsonNum(txt, "epoch");
   long now   = (long)TimeCurrent();
   if (epoch > 0 && (now - epoch) > InpMaxEpochAgeSec) {
      g_last_reason = StringFormat("brain stale: %ds", (int)(now - epoch));
      RenderDashboard(txt);
      return;
   }

   // Killed?
   if (JsonBool(txt, "killed")) {
      g_last_reason = "brain says killed";
      RenderDashboard(txt);
      return;
   }

   // Draw drawings + levels + trade box
   string drawings = JsonArray(txt, "drawings");
   DeleteOurObjects();
   DrawBrainObjects(drawings);

   string decObj    = JsonObj(txt, "decision");
   string action    = JsonStr(decObj, "final_action");
   string side      = JsonStr(decObj, "side");
   double entry     = JsonNum(decObj, "entry");
   double sl        = JsonNum(decObj, "sl");
   double tp        = JsonNum(decObj, "tp");
   double lot       = JsonNum(decObj, "lot");
   string reason    = JsonStr(decObj, "reason");

   if (entry > 0) DrawTradeBox(entry, sl, tp, side);

   g_last_action = action + " " + side;

   // Process only if NEW epoch
   if (epoch > 0 && epoch == g_last_epoch_processed) {
      RenderDashboard(txt);
      return;
   }

   if (action == "PLACE" && entry > 0 && sl > 0) {
      double useLot = (lot > 0) ? lot : InpMinLot;
      bool ok = PlaceBrainOrder(side, entry, sl, tp, useLot, reason);
      if (ok) g_last_epoch_processed = epoch;
   } else if (action == "CANCEL_ALL") {
      CancelAllOurs();
      g_last_epoch_processed = epoch;
      g_last_reason = "cancelled all";
   }
   // WAIT → do nothing

   RenderDashboard(txt);
}

//+------------------------------------------------------------------+
//| OnInit / OnDeinit / OnTimer                                      |
//+------------------------------------------------------------------+
int OnInit() {
   if (!Sym.Name(InpSymbol)) {
      Print("✗ failed to attach symbol ", InpSymbol);
      return INIT_FAILED;
   }
   Trade.SetExpertMagicNumber(InpMagic);
   Trade.SetDeviationInPoints(50);
   Trade.SetTypeFillingBySymbol(InpSymbol);

   InitIndicators();

   EventSetTimer(InpCheckEverySeconds);

   Print("═══════════════════════════════════════════════");
   Print("  FRIDAY Brain Executor v1.0");
   Print("═══════════════════════════════════════════════");
   Print("  Symbol:  ", InpSymbol);
   Print("  Magic:   ", InpMagic);
   Print("  Mode:    ", (InpDryRun ? "🟢 DRY-RUN (no real orders)" : "🔴 LIVE"));
   Print("  Bridge:  ", InpBrainJson, " (Common Files)");
   Print("  Period:  every ", InpCheckEverySeconds, "s");
   Print("  Safety:  max=", InpMaxOpenOrders, " orders, ",
         "min ", InpMinSecondsBetween, "s between, ",
         "max spread ", InpMaxSpreadPoints, "pt");
   Print("═══════════════════════════════════════════════");

   ChartSetInteger(0, CHART_SHOW_GRID, false);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   EventKillTimer();
   DeleteOurObjects();
   Comment("");
   if (h_ema8   != INVALID_HANDLE) IndicatorRelease(h_ema8);
   if (h_ema21  != INVALID_HANDLE) IndicatorRelease(h_ema21);
   if (h_ema55  != INVALID_HANDLE) IndicatorRelease(h_ema55);
   if (h_ema200 != INVALID_HANDLE) IndicatorRelease(h_ema200);
   if (h_bb     != INVALID_HANDLE) IndicatorRelease(h_bb);
   if (h_atr    != INVALID_HANDLE) IndicatorRelease(h_atr);
   if (h_rsi    != INVALID_HANDLE) IndicatorRelease(h_rsi);
   Print("FRIDAY Brain Executor stopped.");
}

void OnTimer() {
   if (KillSwitchActive()) {
      g_last_reason = "🛑 KILL_SWITCH";
      Comment("🛑 KILL SWITCH ACTIVE — no trading\nDelete kill_switch.txt to resume.");
      return;
   }
   if (!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) {
      g_last_reason = "terminal trading disabled";
      Comment("⚠ AutoTrading button is OFF in MT5. Click it to enable.");
      return;
   }
   ProcessBrainJson();
}

void OnTick() {
   // Light work only — most logic lives in OnTimer
   // Refresh chart objects so they stay anchored to current bars
}
