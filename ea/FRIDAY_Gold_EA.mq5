#property strict
#property version "1.01"
#property description "FRIDAY Gold signal-only boundary file. It writes analysis only."

input string          InpSymbol           = "";
input ENUM_TIMEFRAMES InpTimeframe        = PERIOD_M1;
input int             InpLookbackBars     = 300;
input int             InpEMAPeriod        = 200;
input int             InpTimerSeconds     = 5;
input bool            InpUseCommonFiles   = true;
input string          InpFolder           = "FRIDAY";
input string          InpFileName         = "FRIDAY_Gold_signal.json";
input bool            InpShowComment      = true;
input bool            InpDrawLabel        = true;

string ActiveSymbol()
{
   if(StringLen(InpSymbol) > 0)
      return InpSymbol;
   return _Symbol;
}

string TFToText(ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M1)  return "M1";
   if(tf == PERIOD_M5)  return "M5";
   if(tf == PERIOD_M15) return "M15";
   if(tf == PERIOD_M30) return "M30";
   if(tf == PERIOD_H1)  return "H1";
   if(tf == PERIOD_H4)  return "H4";
   if(tf == PERIOD_D1)  return "D1";
   return "TF";
}

string EscapeJson(string s)
{
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\r", "\\r");
   StringReplace(s, "\n", "\\n");
   return s;
}

double CalcEMA(MqlRates &rates[], int copied, int period)
{
   if(copied <= period + 5)
      return 0.0;

   double alpha = 2.0 / (period + 1.0);
   double ema = rates[copied - 1].close;

   for(int i = copied - 2; i >= 1; i--)
      ema = alpha * rates[i].close + (1.0 - alpha) * ema;

   return ema;
}

double CalcATR(MqlRates &rates[], int copied, int period)
{
   if(copied <= period + 3)
      return 0.0;

   double sum = 0.0;
   int count = 0;

   for(int i = 1; i <= period; i++)
   {
      double tr1 = rates[i].high - rates[i].low;
      double tr2 = MathAbs(rates[i].high - rates[i + 1].close);
      double tr3 = MathAbs(rates[i].low - rates[i + 1].close);
      double tr = MathMax(tr1, MathMax(tr2, tr3));

      sum += tr;
      count++;
   }

   if(count <= 0)
      return 0.0;

   return sum / count;
}

bool FractalHigh(MqlRates &rates[], int copied, int shift)
{
   if(shift < 2 || shift + 2 >= copied)
      return false;

   double h = rates[shift].high;

   return (
      h > rates[shift - 1].high &&
      h > rates[shift - 2].high &&
      h > rates[shift + 1].high &&
      h > rates[shift + 2].high
   );
}

bool FractalLow(MqlRates &rates[], int copied, int shift)
{
   if(shift < 2 || shift + 2 >= copied)
      return false;

   double l = rates[shift].low;

   return (
      l < rates[shift - 1].low &&
      l < rates[shift - 2].low &&
      l < rates[shift + 1].low &&
      l < rates[shift + 2].low
   );
}

double LastFractalHigh(MqlRates &rates[], int copied)
{
   for(int i = 3; i < copied - 3; i++)
   {
      if(FractalHigh(rates, copied, i))
         return rates[i].high;
   }

   return 0.0;
}

double LastFractalLow(MqlRates &rates[], int copied)
{
   for(int i = 3; i < copied - 3; i++)
   {
      if(FractalLow(rates, copied, i))
         return rates[i].low;
   }

   return 0.0;
}

void WriteTextFile(string text)
{
   int file_flags = FILE_WRITE | FILE_TXT | FILE_ANSI;

   if(InpUseCommonFiles)
      file_flags = file_flags | FILE_COMMON;

   if(StringLen(InpFolder) > 0)
      FolderCreate(InpFolder, InpUseCommonFiles ? FILE_COMMON : 0);

   string file_path = InpFileName;

   if(StringLen(InpFolder) > 0)
      file_path = InpFolder + "\\" + InpFileName;

   int handle = FileOpen(file_path, file_flags);

   if(handle == INVALID_HANDLE)
   {
      Print("FRIDAY signal file open failed. error=", GetLastError());
      return;
   }

   FileWriteString(handle, text);
   FileClose(handle);
}

void DrawStatusLabel(string direction, double confidence, string reason)
{
   if(!InpDrawLabel)
      return;

   string name = "FRIDAY_GOLD_SIGNAL_ONLY_LABEL";

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 20);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   }

   color c = clrSilver;

   if(direction == "BUY")
      c = clrLime;
   else if(direction == "SELL")
      c = clrTomato;

   string txt =
      "FRIDAY Gold Signal Only\n" +
      "Direction: " + direction + "\n" +
      "Confidence: " + DoubleToString(confidence, 2) + "\n" +
      "Reason: " + reason + "\n" +
      "Direct trading: disabled";

   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
}

void PublishSignal()
{
   string symbol = ActiveSymbol();

   if(!SymbolSelect(symbol, true))
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);

   int need = MathMax(InpLookbackBars, InpEMAPeriod + 50);
   int copied = CopyRates(symbol, InpTimeframe, 0, need, rates);

   string direction = "HOLD";
   string reason = "insufficient_data";
   double confidence = 0.0;
   double ema = 0.0;
   double atr = 0.0;
   double fh = 0.0;
   double fl = 0.0;
   double close_price = 0.0;

   if(copied > InpEMAPeriod + 20)
   {
      ema = CalcEMA(rates, copied, InpEMAPeriod);
      atr = CalcATR(rates, copied, 14);
      fh = LastFractalHigh(rates, copied);
      fl = LastFractalLow(rates, copied);
      close_price = rates[1].close;

      bool ema_up = close_price > ema;
      bool ema_down = close_price < ema;
      bool bos_up = fh > 0.0 && close_price > fh;
      bool bos_down = fl > 0.0 && close_price < fl;

      if(bos_up && ema_up)
      {
         direction = "BUY";
         confidence = 0.70;
         reason = "BOS_UP_EMA_UP";
      }
      else if(bos_down && ema_down)
      {
         direction = "SELL";
         confidence = 0.70;
         reason = "BOS_DOWN_EMA_DOWN";
      }
      else
      {
         direction = "HOLD";
         confidence = 0.0;
         reason = "NO_ALIGNMENT";
      }
   }

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

   string json = "{\n";
   json += "  \"source\": \"FRIDAY_Gold_EA_signal_only\",\n";
   json += "  \"can_execute\": false,\n";
   json += "  \"symbol\": \"" + EscapeJson(symbol) + "\",\n";
   json += "  \"timeframe\": \"" + TFToText(InpTimeframe) + "\",\n";
   json += "  \"direction\": \"" + direction + "\",\n";
   json += "  \"confidence\": " + DoubleToString(confidence, 4) + ",\n";
   json += "  \"reason\": \"" + EscapeJson(reason) + "\",\n";
   json += "  \"timestamp_text\": \"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\",\n";
   json += "  \"bid\": " + DoubleToString(bid, digits) + ",\n";
   json += "  \"ask\": " + DoubleToString(ask, digits) + ",\n";
   json += "  \"close_price\": " + DoubleToString(close_price, digits) + ",\n";
   json += "  \"ema\": " + DoubleToString(ema, digits) + ",\n";
   json += "  \"atr\": " + DoubleToString(atr, digits) + ",\n";
   json += "  \"last_fractal_high\": " + DoubleToString(fh, digits) + ",\n";
   json += "  \"last_fractal_low\": " + DoubleToString(fl, digits) + "\n";
   json += "}\n";

   WriteTextFile(json);
   DrawStatusLabel(direction, confidence, reason);

   if(InpShowComment)
   {
      Comment(
         "FRIDAY Gold Signal Only\n",
         "Direct trading: disabled\n",
         "Symbol: ", symbol, "\n",
         "Direction: ", direction, "\n",
         "Confidence: ", DoubleToString(confidence, 2), "\n",
         "Reason: ", reason
      );
   }

   Print("FRIDAY signal only: ", symbol, " ", direction, " ", DoubleToString(confidence, 2), " ", reason);
}

int OnInit()
{
   EventSetTimer(MathMax(1, InpTimerSeconds));
   PublishSignal();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectDelete(0, "FRIDAY_GOLD_SIGNAL_ONLY_LABEL");
   Comment("");
}

void OnTimer()
{
   PublishSignal();
}

void OnTick()
{
}
