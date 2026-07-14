//+------------------------------------------------------------------+
//|                                      QuantumShark_Safe_v9.mq5     |
//|         إعادة كتابة آمنة — انضباط ومخاطرة محكومة، بلا تفجير حساب   |
//+------------------------------------------------------------------+
//  ⚠️ صدق علمي: هذه النسخة تُصلح المخاطرة والانضباط في v8.2، لكنها
//  لا تَعِد بالربح. صنف EMA/RSI سكالبينج اختبرناه OOS = بلا حافّة مؤكدة.
//  الهدف: ألّا ينفجر الحساب، وأن يتداول بانضباط — لا أن يكون عرّافاً.
//
//  ما تغيّر عن v8.2 (المشاكل الخطيرة التي رُصدت بالأرقام):
//   1) حُذف "التعلّم" الذي يرفع المخاطرة بعد الفوز (مارتينجال معكوس) —
//      هو سبب وصول اللوت إلى 2.46 على حساب ~$1900. الآن: مخاطرة ثابتة،
//      وتُخفَّض فقط بعد سلسلة خسائر (دفاعياً)، ولا تُرفع أبداً فوق الأساس.
//   2) سقف خسارة صارم لكل صفقة = 2% من الحقوق (مهما كان) + سقف لوت صلب
//      + حارس هامش (OrderCalcMargin) — يستحيل أن تبتلع صفقة الحساب.
//   3) فلتر جلسة: لا دخول 22:00–07:00 UTC (نافذة الليل التي أثبت تشريح
//      تداولك أنها كارثية — تصفيات الهامش كانت ليلاً).
//   4) دخول انتقائي (تقاطع EMA أو ارتداد ضيّق في اتجاه الترند + RSI غير
//      متطرف) بدل "يدخل دائماً"، وحُذف الدخول عكس الترند.
//   5) فلتر سبريد (لا تتداول وقت السبريد الواسع/الأخبار).
//+------------------------------------------------------------------+
#property copyright "QuantumShark AI (safe rewrite)"
#property version   "9.00"
#property description "Risk-controlled scalper — fixed small size, session filter, no risk-escalation"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//============================ INPUTS ===============================
input group "=== ⚡ CORE ==="
input bool   EnableTrading            = true;
input int    MagicNumber              = 20250423;   // مغاير لـ v8.2 (20250422) ليعملا منفصلين
input int    MaxPositions             = 2;          // كان 5
input int    MinSecondsBetweenTrades  = 10;

input group "=== 📊 INDICATORS (M1) ==="
input int    EMA_Fast        = 8;
input int    EMA_Slow        = 21;
input int    RSI_Period      = 14;
input int    RSI_Overbought  = 70;
input int    RSI_Oversold    = 30;
input int    ATR_Period      = 14;

input group "=== 💰 RISK (ثابتة — بلا تصعيد) ==="
input double RiskPercent          = 0.5;   // مخاطرة أساس ثابتة (كان يصل 4%)
input double MaxTradeLossPct       = 2.0;   // 🛑 سقف صارم: لا صفقة تخسر > هذا % من الحقوق
input double MaxLotHard            = 0.10;  // 🛑 سقف لوت صلب مهما حسبت الصيغة (كان 2.0)
input double MaxMarginPctPerTrade  = 10.0;  // 🛑 لا صفقة تستهلك هامشاً > هذا % من الحقوق

input group "=== 🎯 SL / TP / إدارة ==="
input double SL_ATR_Mult   = 1.5;
input double TP_ATR_Mult   = 2.0;
input bool   EnableBE      = true;
input double BE_ATR        = 0.7;
input bool   EnableTrail   = true;
input double Trail_ATR     = 0.7;
input double TrailStep_ATR = 0.3;

input group "=== 📈 الدخول الانتقائي ==="
input bool   UseTrendFilter   = true;    // لا تتداول عكس اتجاه EMA
input bool   UseRSIFilter     = true;    // تجنّب الذروة المتطرفة
input double PullbackATR      = 0.5;     // الارتداد = ضمن هذا × ATR من EMA السريع (نطاق ضيّق)
input int    MaxSpreadPoints  = 60;      // تخطَّ الدخول إذا اتسع السبريد (أخبار)

input group "=== 🕐 فلتر الجلسة (UTC) ==="
input bool   UseSessionFilter = true;
input int    NoTradeStartUTC  = 22;      // لا دخول من 22:00
input int    NoTradeEndUTC    = 7;       // حتى 07:00 UTC

input group "=== 🛡️ SAFETY ==="
input double MaxDailyLossPct  = 5.0;     // كان 8% — أضيق
input int    CooldownMinutes  = 5;
input bool   EnableLogs       = true;

//============================ GLOBALS ==============================
CTrade        Trade;
CPositionInfo PosInfo;

string   gSymbol;
double   gPoint;
int      gDigits;
double   gDailyEquity = 0;
datetime gLastTradeTime = 0;
datetime gCooldownUntil = 0;
bool     gHalted = false;
bool     gClosedToday = false;
int      gLossStreak = 0;          // لتخفيض المخاطرة دفاعياً فقط
double   gRiskNow = 0;             // المخاطرة الحالية (تبدأ = RiskPercent)

int      hEMAf, hEMAs, hRSI, hATR;

void Log(string m){ if(EnableLogs) Print("[🛡️QS-Safe] ", m); }

//============================ UTILS ===============================
double GetValidLot(double lot)
{
   double mn = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP);
   if(st <= 0) st = 0.01;
   int d = (int)MathRound(-MathLog10(st));
   double v = MathFloor(lot/st)*st;
   v = NormalizeDouble(v, d);
   return MathMax(mn, MathMin(mx, v));
}

//--- حجم آمن: أقل من (مخاطرة الأساس، سقف 2%) ثم سقف لوت صلب ثم حارس هامش
double CalcLot(double sl_dist)
{
   if(sl_dist <= 0) return 0;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double tv = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return 0;
   double ticks = sl_dist/ts;
   if(ticks <= 0) return 0;

   double risk_amt = eq * gRiskNow/100.0;             // مخاطرة الأساس (قد تكون مخفّضة دفاعياً)
   double cap_amt  = eq * MaxTradeLossPct/100.0;      // 🛑 السقف الصارم
   double use_amt  = MathMin(risk_amt, cap_amt);

   double lot = use_amt/(ticks*tv);
   lot = MathMin(lot, MaxLotHard);                    // 🛑 سقف اللوت الصلب
   lot = GetValidLot(lot);

   double min_lot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
   double step    = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP); if(step<=0) step=0.01;

   // 🛑 حارس الهامش: قلّل اللوت حتى لا تتجاوز الصفقة الحد المسموح من الهامش
   double price = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   double need=0, maxm = eq * MaxMarginPctPerTrade/100.0;
   for(int g=0; g<50; g++)
   {
      if(!OrderCalcMargin(ORDER_TYPE_BUY, gSymbol, lot, price, need)) break;
      if(need <= maxm || lot <= min_lot) break;
      lot = GetValidLot(lot - step);
   }
   if(lot < min_lot) { Log("⚠️ الحساب أصغر من أن يتداول هذا الرمز بأمان — تخطّي."); return 0; }
   // تحقّق نهائي: هل خسارة هذا اللوت على SL ضمن السقف؟
   double loss_at_sl = ticks*tv*lot;
   if(loss_at_sl > cap_amt*1.05) { Log("⚠️ اللوت يتجاوز سقف 2% — تخطّي."); return 0; }
   return lot;
}

int CountPos()
{
   int c=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
      if(PosInfo.SelectByIndex(i) && PosInfo.Symbol()==gSymbol && PosInfo.Magic()==MagicNumber) c++;
   return c;
}

bool SessionBlocked()
{
   if(!UseSessionFilter) return false;
   MqlDateTime g; TimeToStruct(TimeGMT(), g);
   int h = g.hour;
   if(NoTradeStartUTC <= NoTradeEndUTC) return (h >= NoTradeStartUTC && h < NoTradeEndUTC);
   return (h >= NoTradeStartUTC || h < NoTradeEndUTC);   // نافذة تعبر منتصف الليل (22..07)
}

bool SpreadOK()
{
   long sp = SymbolInfoInteger(gSymbol, SYMBOL_SPREAD);
   return (sp <= MaxSpreadPoints);
}

bool ValidLevels(double price, double sl, double tp, bool buy)
{
   long st = SymbolInfoInteger(gSymbol, SYMBOL_TRADE_STOPS_LEVEL);
   double md = (double)st*gPoint; if(md < 50*gPoint) md = 50*gPoint;
   int d = gDigits;
   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID), ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   if(buy){ if(sl>=price||NormalizeDouble(ask-sl,d)<=md) return false; if(tp<=price||NormalizeDouble(tp-ask,d)<=md) return false; }
   else   { if(sl<=price||NormalizeDouble(sl-bid,d)<=md) return false; if(tp>=price||NormalizeDouble(bid-tp,d)<=md) return false; }
   return true;
}

//============================ ENTRIES =============================
void Open(bool buy, double atr, string reason)
{
   if(CountPos() >= MaxPositions) return;
   if(TimeCurrent() < gCooldownUntil) return;
   if(!SpreadOK()) { Log("سبريد واسع — تخطّي الدخول"); return; }

   double px = buy ? SymbolInfoDouble(gSymbol,SYMBOL_ASK) : SymbolInfoDouble(gSymbol,SYMBOL_BID);
   if(px <= 0) return;

   double sl_dist = atr*SL_ATR_Mult; if(sl_dist < 80*gPoint) sl_dist = 80*gPoint;
   double tp_dist = atr*TP_ATR_Mult; if(tp_dist < 120*gPoint) tp_dist = 120*gPoint;
   int d = gDigits;
   double sl = NormalizeDouble(buy ? px-sl_dist : px+sl_dist, d);
   double tp = NormalizeDouble(buy ? px+tp_dist : px-tp_dist, d);
   if(!ValidLevels(px, sl, tp, buy)) return;

   double lot = CalcLot(sl_dist);
   if(lot <= 0) return;

   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);
   bool ok = buy ? Trade.Buy(lot,gSymbol,px,sl,tp,"QS-Safe BUY|"+reason)
                 : Trade.Sell(lot,gSymbol,px,sl,tp,"QS-Safe SELL|"+reason);
   if(ok){ gLastTradeTime = TimeCurrent();
           Log((buy?"✅ BUY":"✅ SELL")+" | "+reason+" | Lot:"+DoubleToString(lot,2)+" Risk:"+DoubleToString(gRiskNow,2)+"%"); }
}

//============================ MANAGE ==============================
void ManagePositions()
{
   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID), ask=SymbolInfoDouble(gSymbol,SYMBOL_ASK);
   if(bid<=0||ask<=0) return;
   double ab[1]; if(CopyBuffer(hATR,0,0,1,ab)<=0) return; double atr=ab[0]; if(atr<=0) return;
   int d=gDigits; double min_dist=50*gPoint;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      if(!PosInfo.SelectByIndex(i)) continue;
      if(PosInfo.Symbol()!=gSymbol||PosInfo.Magic()!=MagicNumber) continue;
      double op=PosInfo.PriceOpen(), csl=PosInfo.StopLoss(), ctp=PosInfo.TakeProfit();

      if(PosInfo.PositionType()==POSITION_TYPE_BUY)
      {
         double prof=(bid-op)/gPoint;
         if(EnableBE && prof>=BE_ATR*atr/gPoint && (csl<op||csl==0)){
            double nsl=NormalizeDouble(op+20*gPoint,d);
            if(nsl<bid-min_dist && (csl==0||nsl>csl)) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp);}
         if(EnableTrail && prof>0){
            double nsl=NormalizeDouble(bid-Trail_ATR*atr,d); double step=TrailStep_ATR*atr;
            if(nsl>op && nsl>csl+step && nsl<bid-min_dist) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp);}
      }
      else
      {
         double prof=(op-ask)/gPoint;
         if(EnableBE && prof>=BE_ATR*atr/gPoint && (csl>op||csl==0)){
            double nsl=NormalizeDouble(op-20*gPoint,d);
            if(nsl>ask+min_dist && (csl==0||nsl<csl)) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp);}
         if(EnableTrail && prof>0){
            double nsl=NormalizeDouble(ask+Trail_ATR*atr,d); double step=TrailStep_ATR*atr;
            if(nsl<op && (csl==0||nsl<csl-step) && nsl>ask+min_dist) Trade.PositionModify(PosInfo.Ticket(),nsl,ctp);}
      }
   }
}

//============================ DAILY GUARD =========================
void CloseAllHalt(string why)
{
   if(gClosedToday) return; gClosedToday=true;
   Log("🛑 HALT & CLOSE: "+why);
   for(int i=PositionsTotal()-1;i>=0;i--)
      if(PosInfo.SelectByIndex(i) && PosInfo.Symbol()==gSymbol && PosInfo.Magic()==MagicNumber)
         Trade.PositionClose(PosInfo.Ticket());
   gHalted=true; gCooldownUntil=TimeCurrent()+CooldownMinutes*60;
}

bool DailyLossHit()
{
   if(gHalted) return true;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(gDailyEquity<=0) return false;
   double loss=(gDailyEquity-eq)/gDailyEquity*100.0;
   if(loss>=MaxDailyLossPct){ CloseAllHalt("Daily loss "+DoubleToString(loss,1)+"%"); return true; }
   return false;
}

//--- تخفيض دفاعي فقط: بعد 4 خسائر متتالية قلّل المخاطرة، ولا ترفعها فوق الأساس أبداً
void OnTrade()
{
   HistorySelect(0, TimeCurrent());
   int total=HistoryDealsTotal();
   static ulong last_seen=0;
   for(int i=total-1;i>=MathMax(0,total-5);i--)
   {
      ulong tk=HistoryDealGetTicket(i); if(tk==0||tk<=last_seen) continue;
      if(HistoryDealGetInteger(tk,DEAL_MAGIC)!=MagicNumber) continue;
      if(HistoryDealGetString(tk,DEAL_SYMBOL)!=gSymbol) continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY)!=DEAL_ENTRY_OUT) continue;
      last_seen=tk;
      double p=HistoryDealGetDouble(tk,DEAL_PROFIT)+HistoryDealGetDouble(tk,DEAL_SWAP)+HistoryDealGetDouble(tk,DEAL_COMMISSION);
      if(p<0) gLossStreak++; else gLossStreak=0;
      if(gLossStreak>=4){ gRiskNow=MathMax(0.2, gRiskNow*0.6); gLossStreak=0;
                          Log("🔧 دفاعي: خفض المخاطرة إلى "+DoubleToString(gRiskNow,2)+"% بعد سلسلة خسائر"); }
      else if(gLossStreak==0 && gRiskNow<RiskPercent){ gRiskNow=MathMin(RiskPercent, gRiskNow+0.1); } // تعافٍ بطيء، لا يتجاوز الأساس
   }
}

//============================ INIT ================================
int OnInit()
{
   gSymbol=Symbol(); gPoint=SymbolInfoDouble(gSymbol,SYMBOL_POINT); gDigits=(int)SymbolInfoInteger(gSymbol,SYMBOL_DIGITS);
   gRiskNow=RiskPercent;
   hEMAf=iMA(gSymbol,PERIOD_M1,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
   hEMAs=iMA(gSymbol,PERIOD_M1,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
   hRSI =iRSI(gSymbol,PERIOD_M1,RSI_Period,PRICE_CLOSE);
   hATR =iATR(gSymbol,PERIOD_M1,ATR_Period);
   if(hEMAf==INVALID_HANDLE||hEMAs==INVALID_HANDLE||hRSI==INVALID_HANDLE||hATR==INVALID_HANDLE){ Log("❌ indicators"); return INIT_FAILED; }
   Trade.SetExpertMagicNumber(MagicNumber);
   gDailyEquity=AccountInfoDouble(ACCOUNT_EQUITY);
   gHalted=false; gClosedToday=false; gCooldownUntil=0;
   Log("✅ QS-Safe v9 ready | "+gSymbol+" | Risk "+DoubleToString(RiskPercent,2)+"% cap "+DoubleToString(MaxTradeLossPct,1)+"% MaxLot "+DoubleToString(MaxLotHard,2));
   Log("   فلتر الجلسة: "+(UseSessionFilter?("لا دخول "+IntegerToString(NoTradeStartUTC)+"-"+IntegerToString(NoTradeEndUTC)+" UTC"):"معطّل"));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int r)
{
   if(hEMAf!=INVALID_HANDLE) IndicatorRelease(hEMAf);
   if(hEMAs!=INVALID_HANDLE) IndicatorRelease(hEMAs);
   if(hRSI!=INVALID_HANDLE)  IndicatorRelease(hRSI);
   if(hATR!=INVALID_HANDLE)  IndicatorRelease(hATR);
}

//============================ TICK ================================
void OnTick()
{
   static int last_day=-1; MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   if(last_day!=dt.day){ last_day=dt.day; gDailyEquity=AccountInfoDouble(ACCOUNT_EQUITY);
                         gHalted=false; gClosedToday=false; gCooldownUntil=0; Log("🌅 يوم جديد | Equity $"+DoubleToString(gDailyEquity,2)); }

   if(!EnableTrading || gHalted) return;
   if(TimeCurrent() < gCooldownUntil) return;
   if(DailyLossHit()) return;

   ManagePositions();                                   // إدارة المراكز تعمل دائماً

   if(SessionBlocked()) return;                         // 🕐 لا دخول جديد ليلاً
   if(TimeCurrent()-gLastTradeTime < MinSecondsBetweenTrades) return;

   double bf[2]; if(CopyBuffer(hEMAf,0,0,2,bf)<=0) return; double ema_f=bf[0], ema_fp=bf[1];
   double bs[2]; if(CopyBuffer(hEMAs,0,0,2,bs)<=0) return; double ema_s=bs[0], ema_sp=bs[1];
   double br[1]; if(CopyBuffer(hRSI,0,0,1,br)<=0) return; double rsi=br[0];
   double ba[1]; if(CopyBuffer(hATR,0,0,1,ba)<=0) return; double atr=ba[0]; if(atr<=0) return;

   double bid=SymbolInfoDouble(gSymbol,SYMBOL_BID); if(bid<=0) return;
   datetime cb=iTime(gSymbol,PERIOD_M1,0); static datetime lb=0; bool newbar=(cb!=lb); if(newbar) lb=cb;
   if(!newbar) return;                                  // دخول مرة واحدة لكل شمعة فقط (انتقائي)

   bool up=(ema_f>ema_s), dn=(ema_f<ema_s);
   bool trend_buy  = (!UseTrendFilter)||up;
   bool trend_sell = (!UseTrendFilter)||dn;
   bool rsi_buy  = (!UseRSIFilter)||(rsi<RSI_Overbought && rsi>45);   // ليس متطرفاً، وزخم صاعد
   bool rsi_sell = (!UseRSIFilter)||(rsi>RSI_Oversold  && rsi<55);

   // إشارتان فقط (لا "يدخل دائماً"، لا عكس ترند):
   bool cross_up = (ema_fp<=ema_sp && ema_f>ema_s);
   bool cross_dn = (ema_fp>=ema_sp && ema_f<ema_s);
   bool pull_buy  = up && MathAbs(bid-ema_f) <= PullbackATR*atr;       // ارتداد ضيّق للـEMA في ترند صاعد
   bool pull_sell = dn && MathAbs(bid-ema_f) <= PullbackATR*atr;

   bool buy  = (cross_up || pull_buy)  && trend_buy  && rsi_buy;
   bool sell = (cross_dn || pull_sell) && trend_sell && rsi_sell;

   if(buy && !sell)      Open(true,  atr, cross_up?"CROSS":"PULL");
   else if(sell && !buy) Open(false, atr, cross_dn?"CROSS":"PULL");
}
//+------------------------------------------------------------------+
