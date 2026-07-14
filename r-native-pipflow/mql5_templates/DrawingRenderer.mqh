//+------------------------------------------------------------------+
//|                DrawingRenderer.mqh                                |
//|   Python brain -> MT5 chart bridge                                |
//|                                                                   |
//|   Public API:                                                     |
//|     DrawingRenderer_Init(chart_symbol)                            |
//|     DrawingRenderer_Render(json_drawings_array_string)            |
//|     DrawingRenderer_ClearAll()                                    |
//|                                                                   |
//|   Renders SMC zones (OB, FVG, BOS/CHoCH, sweeps, IDM, liquidity)  |
//|   plus trade overlays (entry, SL, TP) per the schema in           |
//|   docs/smc/02_DRAWING_BRIDGE.md.                                  |
//|                                                                   |
//|   Requires: JAson.mqh (https://www.mql5.com/en/code/13663)        |
//+------------------------------------------------------------------+
#property strict

#include <JAson.mqh>

#define DR_PREFIX        "FRIDAY_"
#define DR_MAX_OBJECTS   250

string  g_chart_symbol = "";
string  g_alive_ids[];           // ids seen in the last payload (without prefix)
int     g_broker_offset_s = 0;
bool    g_offset_initialized = false;

//==================================================================
// Helpers
//==================================================================
color DR_HexToColor(string hex)
{
   if(StringLen(hex) != 7 || StringGetCharacter(hex,0) != '#') return clrWhite;
   int r = (int)StringToInteger("0x"+StringSubstr(hex,1,2));
   int g = (int)StringToInteger("0x"+StringSubstr(hex,3,2));
   int b = (int)StringToInteger("0x"+StringSubstr(hex,5,2));
   return (color)(r | (g<<8) | (b<<16));
}

ENUM_LINE_STYLE DR_LineStyle(string s)
{
   if(s=="dash")    return STYLE_DASH;
   if(s=="dot")     return STYLE_DOT;
   if(s=="dashdot") return STYLE_DASHDOT;
   return STYLE_SOLID;
}

void DR_EnsureOffset()
{
   if(g_offset_initialized) return;
   g_broker_offset_s = (int)(TimeTradeServer() - TimeGMT());
   g_offset_initialized = true;
}

datetime DR_EpochToBroker(long epoch_utc)
{
   DR_EnsureOffset();
   return (datetime)(epoch_utc + g_broker_offset_s);
}

bool DR_AlreadyAlive(string id)
{
   int n = ArraySize(g_alive_ids);
   for(int i=0; i<n; i++) if(g_alive_ids[i] == id) return true;
   return false;
}

void DR_MarkAlive(string id)
{
   if(DR_AlreadyAlive(id)) return;
   int n = ArraySize(g_alive_ids);
   ArrayResize(g_alive_ids, n+1);
   g_alive_ids[n] = id;
}

bool DR_Touch(string name, ENUM_OBJECT type, int sub_window=0)
{
   if(ObjectFind(0,name) < 0)
      return ObjectCreate(0, name, type, sub_window, 0, 0);
   return true;
}

void DR_ApplyCommonStyle(string name, CJAVal *style)
{
   if(style == NULL) return;
   string c = style["color"].ToStr();
   if(StringLen(c) > 0)
      ObjectSetInteger(0,name,OBJPROP_COLOR, DR_HexToColor(c));
   if(style["width"].m_type != jtUNDEF)
      ObjectSetInteger(0,name,OBJPROP_WIDTH, (int)style["width"].ToInt());
   string ls = style["line_style"].ToStr();
   if(StringLen(ls) > 0)
      ObjectSetInteger(0,name,OBJPROP_STYLE, DR_LineStyle(ls));
   if(style["zorder"].m_type != jtUNDEF)
      ObjectSetInteger(0,name,OBJPROP_ZORDER, (int)style["zorder"].ToInt());
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0,name,OBJPROP_HIDDEN, true);
}

//==================================================================
// Drawers (one per drawing type)
//==================================================================
void DR_DrawRectangle(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_RECTANGLE);
   datetime t1 = DR_EpochToBroker(d["ts_start"].ToInt());
   datetime t2 = DR_EpochToBroker(d["ts_end"].ToInt());
   ObjectSetInteger(0,name,OBJPROP_TIME, 0, t1);
   ObjectSetInteger(0,name,OBJPROP_TIME, 1, t2);
   ObjectSetDouble (0,name,OBJPROP_PRICE,0, d["price_high"].ToDbl());
   ObjectSetDouble (0,name,OBJPROP_PRICE,1, d["price_low"].ToDbl());
   bool fill = d["style"]["fill"].ToBool();
   ObjectSetInteger(0,name,OBJPROP_FILL, fill);
   ObjectSetInteger(0,name,OBJPROP_BACK, true);
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

void DR_DrawHLine(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_HLINE);
   ObjectSetDouble(0,name,OBJPROP_PRICE,0, d["price"].ToDbl());
   string label = d["label"].ToStr();
   if(StringLen(label) > 0)
      ObjectSetString(0,name,OBJPROP_TEXT, label);
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

void DR_DrawTrendline(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_TREND);
   ObjectSetInteger(0,name,OBJPROP_TIME, 0, DR_EpochToBroker(d["ts1"].ToInt()));
   ObjectSetInteger(0,name,OBJPROP_TIME, 1, DR_EpochToBroker(d["ts2"].ToInt()));
   ObjectSetDouble (0,name,OBJPROP_PRICE,0, d["price1"].ToDbl());
   ObjectSetDouble (0,name,OBJPROP_PRICE,1, d["price2"].ToDbl());
   ObjectSetInteger(0,name,OBJPROP_RAY_RIGHT, false);
   string label = d["label"].ToStr();
   if(StringLen(label) > 0)
      ObjectSetString(0,name,OBJPROP_TEXT, label);
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

void DR_DrawArrow(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_ARROW);
   ObjectSetInteger(0,name,OBJPROP_TIME, 0, DR_EpochToBroker(d["ts"].ToInt()));
   ObjectSetDouble (0,name,OBJPROP_PRICE,0, d["price"].ToDbl());
   int code = (int)d["arrow_code"].ToInt();
   if(code <= 0) code = 233;
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE, code);
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

void DR_DrawLabel(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_TEXT);
   ObjectSetInteger(0,name,OBJPROP_TIME, 0, DR_EpochToBroker(d["ts"].ToInt()));
   ObjectSetDouble (0,name,OBJPROP_PRICE,0, d["price"].ToDbl());
   string text = d["text"].ToStr();
   ObjectSetString (0,name,OBJPROP_TEXT, text);
   string font = d["meta"]["font"].ToStr();
   if(StringLen(font) == 0) font = "Tahoma";
   ObjectSetString (0,name,OBJPROP_FONT, font);
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

void DR_DrawFib(string id, CJAVal *d)
{
   string name = DR_PREFIX + id;
   DR_Touch(name, OBJ_FIBO);
   ObjectSetInteger(0,name,OBJPROP_TIME, 0, DR_EpochToBroker(d["ts1"].ToInt()));
   ObjectSetInteger(0,name,OBJPROP_TIME, 1, DR_EpochToBroker(d["ts2"].ToInt()));
   ObjectSetDouble (0,name,OBJPROP_PRICE,0, d["price1"].ToDbl());
   ObjectSetDouble (0,name,OBJPROP_PRICE,1, d["price2"].ToDbl());
   CJAVal *lv = GetPointer(d["levels"]);
   if(lv != NULL)
   {
      int n = (int)lv.Size();
      ObjectSetInteger(0,name,OBJPROP_LEVELS, n);
      for(int i=0; i<n; i++)
         ObjectSetDouble(0,name,OBJPROP_LEVELVALUE, i, lv[i].ToDbl());
   }
   DR_ApplyCommonStyle(name, GetPointer(d["style"]));
}

//==================================================================
// Public API
//==================================================================
void DrawingRenderer_Init(string chart_symbol)
{
   g_chart_symbol = chart_symbol;
   ArrayResize(g_alive_ids, 0);
   DR_EnsureOffset();
}

void DrawingRenderer_PruneRemoved()
{
   int total = ObjectsTotal(0, -1, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, DR_PREFIX) != 0) continue;
      string bare = StringSubstr(name, StringLen(DR_PREFIX));
      if(!DR_AlreadyAlive(bare))
         ObjectDelete(0, name);
   }
}

void DrawingRenderer_ClearAll()
{
   int total = ObjectsTotal(0, -1, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, DR_PREFIX) == 0)
         ObjectDelete(0, name);
   }
   ArrayResize(g_alive_ids, 0);
   ChartRedraw(0);
}

// Render drawings from a JSON array string (the value of brain.json[drawings]).
void DrawingRenderer_Render(string json_drawings)
{
   CJAVal arr;
   if(!arr.Deserialize(json_drawings)) return;

   ArrayResize(g_alive_ids, 0);
   int count = (int)arr.Size();
   if(count > DR_MAX_OBJECTS) count = DR_MAX_OBJECTS;

   for(int i = 0; i < count; i++)
   {
      CJAVal *d = GetPointer(arr[i]);
      if(d == NULL) continue;

      string sym = d["symbol"].ToStr();
      if(sym != g_chart_symbol) continue;       // per-chart filtering

      string id   = d["id"].ToStr();
      string type = d["type"].ToStr();
      if(StringLen(id) == 0 || StringLen(type) == 0) continue;

      DR_MarkAlive(id);

      if(type == "rectangle")       DR_DrawRectangle(id, d);
      else if(type == "hline")      DR_DrawHLine    (id, d);
      else if(type == "trendline")  DR_DrawTrendline(id, d);
      else if(type == "arrow")      DR_DrawArrow    (id, d);
      else if(type == "label")      DR_DrawLabel    (id, d);
      else if(type == "fib_levels") DR_DrawFib      (id, d);
      // unknown types silently skipped
   }
   DrawingRenderer_PruneRemoved();
   ChartRedraw(0);
}
