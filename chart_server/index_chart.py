# -*- coding: utf-8 -*-
"""chart_server/index_chart.py — «Index Chart» حيّ للذهب وسلّته المرتبطة (طلب المستخدم، أسلوب Observable Plot).

يعرض عدّة أصولٍ مُعاد تأسيسها على 100 (index chart) لمقارنة حركتها النسبيّة مع الذهب:
- ارتباطاتٌ حقيقيّة مُحاذاة زمنياً (تُحسب حيّاً): الفضّة +0.87 · DXY −0.64 · اليورو +0.63 · الأسترالي +0.70 ...
- الأصول العكسيّة (DXY/الين/الفرنك/النفط) تُقلَب لعرضٍ «مُحاذٍ للذهب» (ارتفاعها = داعمٌ للذهب).
- + شموع الذهب ومستوياته (level_map) + لوحة ارتباطاتٍ حيّة.

قراءة-فقط من MT5 (يعيد استخدام اتصال الخادم — لا mt5.initialize مستقلّ). لا استراتيجيّة تنفيذٍ هنا؛ هذا العرض
والسياق الحيّ. النقطتان: get_index_data() ⇒ JSON · INDEX_HTML ⇒ الصفحة."""
from __future__ import annotations
import datetime as _dt
import json as _json

import numpy as np
import MetaTrader5 as mt5

_SENT_STATUS = r"C:\Users\Radhi\MT5\data\r_native\gold_sentinel_status.json"
_SENT_FEED = r"C:\Users\Radhi\MT5\data\r_native\gold_sentinel_feed.jsonl"


def _read_sentinel():
    """حالة حارس المستويات + آخر تنبيهاته (للوحة الداشبورد)."""
    try:
        st = _json.load(open(_SENT_STATUS, encoding="utf-8"))
    except Exception:
        return None
    try:
        lines = open(_SENT_FEED, encoding="utf-8").read().strip().splitlines()[-6:]
        st["feed"] = [_json.loads(x) for x in reversed(lines) if x.strip()]
    except Exception:
        st["feed"] = []
    return st

# (رمز, تسمية, عكسيّ؟, لون) — عكسيّ=مرتبطٌ سلبياً بالذهب ⇒ نقلبه للعرض المُحاذي
BASKET = [
    ("XAUUSDm", "الذهب",         False, "#f5c518"),
    ("XAGUSDm", "الفضّة",         False, "#cfd2d6"),
    ("DXYm",    "الدولار DXY",    True,  "#e05a5a"),
    ("EURUSDm", "اليورو",         False, "#5a8fe0"),
    ("USDJPYm", "الين",           True,  "#e0995a"),
    ("USDCHFm", "الفرنك",         True,  "#b57ae0"),
    ("AUDUSDm", "الأسترالي",      False, "#5ae0a0"),
    ("US30m",   "داو US30",       False, "#8fe05a"),
    ("BTCUSDm", "بتكوين",         False, "#e0c85a"),
    ("USOILm",  "النفط",          True,  "#9aa0a6"),
]
_INV = {s for s, _, inv, _ in BASKET if inv}


def _iso(ts):
    return _dt.datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M")


def _rets(a):
    a = np.asarray(a, float)
    return np.diff(np.log(np.clip(a, 1e-9, None)))


def _ema(a, p):
    a = np.asarray(a, float)
    k = 2.0 / (p + 1.0)
    e = np.empty(len(a)); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _stoch(h, l, c, kp=14, slow=3, dp=3):
    """Stochastic بإعدادات المستخدم: %K=14 · تنعيم(slowing)=3 · %D=3 · طريقة EMA · مجال Low/High."""
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float); n = len(c)
    raw = np.full(n, 50.0)
    for i in range(kp - 1, n):
        hh = h[i - kp + 1:i + 1].max(); ll = l[i - kp + 1:i + 1].min()
        raw[i] = 100.0 * (c[i] - ll) / ((hh - ll) or 1e-9)
    k = _ema(raw, slow)            # التنعيم (EMA)
    d = _ema(k, dp)               # %D (EMA)
    return k, d


def _period_levels():
    """قمم/قيعان تاريخيّة: شمعة اليوم/الأمس (D1) + الأسبوع (W1) + الشهر (MN1)."""
    out = []
    P = [("D1", mt5.TIMEFRAME_D1, 2, ["اليوم", "الأمس"]),
         ("W1", mt5.TIMEFRAME_W1, 2, ["الأسبوع", "الأسبوع الماضي"]),
         ("MN1", mt5.TIMEFRAME_MN1, 2, ["الشهر", "الشهر الماضي"])]
    for _, tf, n, labels in P:
        try:
            r = mt5.copy_rates_from_pos("XAUUSDm", tf, 0, n)
            if r is None:
                continue
            for j, lab in enumerate(labels):
                idx = len(r) - 1 - j
                if idx < 0:
                    continue
                cls = "cur" if j == 0 else "prev"
                out.append({"price": round(float(r[idx]["high"]), 2), "name": f"قمّة {lab}", "cls": cls})
                out.append({"price": round(float(r[idx]["low"]), 2), "name": f"قاع {lab}", "cls": cls})
        except Exception:
            pass
    return out


def _gold_levels(last_price):
    """قمم/قيعان تاريخيّة (اليوم/الأمس/الأسبوع/الشهر) + مناطق التقاء level_map إن توفّرت."""
    out = _period_levels()
    try:
        import level_map
        for z in (level_map.confluence_zones("XAUUSDm") or [])[:6]:
            price = z.get("price") if isinstance(z, dict) else getattr(z, "price", None)
            name = z.get("name", "") if isinstance(z, dict) else getattr(z, "name", "")
            if price:
                out.append({"price": round(float(price), 2), "name": str(name)[:18], "cls": "conf"})
    except Exception:
        pass
    return sorted(out, key=lambda x: x["price"])


def get_index_data(window: int = 168):
    """يبني حمولة الـIndex Chart: سلاسل مُعاد تأسيسها 100 + ارتباطات + شموع ذهب + مستويات. window = شموع H1."""
    try:
        if mt5.terminal_info() is None:            # غير متّصل ⇒ هيّئ (idempotent — نفس عمليّة الخادم، لا فيضان)
            mt5.initialize()
        raw = {}
        for sym, _, _, _ in BASKET:
            try:
                mt5.symbol_select(sym, True)
                r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, window)
            except Exception:
                r = None
            if r is not None and len(r) > 10:
                raw[sym] = r
        if "XAUUSDm" not in raw:
            return {"error": "لا بيانات ذهب من MT5"}
        gt = [int(t) for t in raw["XAUUSDm"]["time"]]                  # جدول الذهب الزمنيّ = الأساس
        g_close = [float(c) for c in raw["XAUUSDm"]["close"]]
        g_ret = _rets(g_close)
        series = []
        for sym, label, inv, color in BASKET:
            if sym not in raw:
                continue
            d = {int(t): float(c) for t, c in zip(raw[sym]["time"], raw[sym]["close"])}
            vals, last = [], None
            for t in gt:                                              # اسقاط على جدول الذهب + تعبئة أماميّة
                if t in d:
                    last = d[t]
                vals.append(last if last is not None else float(raw[sym]["close"][0]))
            base = vals[0] or 1e-9
            idx = [100.0 * base / v for v in vals] if inv else [100.0 * v / base for v in vals]  # عكسيّ ⇒ اقلب
            xr = _rets(vals)
            m = min(len(g_ret), len(xr))
            cc = float(np.corrcoef(g_ret[-m:], xr[-m:])[0, 1]) if m > 5 else 0.0
            series.append({"sym": sym, "label": label + ("‏ (معكوس)" if inv else ""),
                           "inverse": inv, "color": color, "corr": round(cc if cc == cc else 0.0, 2),
                           "index": [round(v, 2) for v in idx]})
        times = [_iso(t) for t in gt]
        # ── تفصيل الذهب (280 شمعة) لحساب EMA50/EMA200 وStoch ثم عرض آخر 168 ──
        gd = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_H1, 0, 280)
        SHOW = 168
        if gd is not None and len(gd) > 210:
            e50 = _ema(gd["close"], 50); e200 = _ema(gd["close"], 200)
            sk, sd = _stoch(gd["high"], gd["low"], gd["close"])
            sl = slice(len(gd) - SHOW, len(gd))
            candles = [{"t": _iso(int(t)), "o": float(o), "h": float(h), "l": float(l), "c": float(c),
                        "e50": round(float(a), 2), "e200": round(float(b), 2)}
                       for t, o, h, l, c, a, b in zip(gd["time"][sl], gd["open"][sl], gd["high"][sl],
                                                      gd["low"][sl], gd["close"][sl], e50[sl], e200[sl])]
            stoch = {"t": [_iso(int(t)) for t in gd["time"][sl]],
                     "k": [round(float(x), 1) for x in sk[sl]], "d": [round(float(x), 1) for x in sd[sl]]}
            last_c = float(gd["close"][-1])
        else:                                     # احتياطيّ: من سلسلة السلّة
            g = raw["XAUUSDm"]
            candles = [{"t": _iso(int(t)), "o": float(o), "h": float(h), "l": float(l), "c": float(c)}
                       for t, o, h, l, c in zip(g["time"], g["open"], g["high"], g["low"], g["close"])]
            stoch = None; last_c = g_close[-1]
        return {"times": times, "series": series, "candles": candles, "stoch": stoch,
                "stoch_levels": [90, 85, 50, 15, 10], "sentinel": _read_sentinel(),
                "levels": _gold_levels(last_c), "gold_last": round(last_c, 2),
                "updated": _dt.datetime.now().strftime("%H:%M:%S")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


INDEX_HTML = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Index Chart — الذهب وسلّته</title>
<style>
:root{--bg:#0e1116;--panel:#171b22;--line:#232833;--txt:#e6e9ef;--dim:#9aa3b2;--gold:#f5c518;--up:#26a67a;--dn:#e05a5a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:'Segoe UI',Tahoma,sans-serif}
header{padding:12px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:17px;margin:0;color:var(--gold)}
.pill{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:4px 12px;font-size:12px;color:var(--dim)}
.wrap{display:grid;grid-template-columns:1fr 300px;gap:14px;padding:14px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.card h2{font-size:13px;margin:0 0 8px;color:var(--dim);font-weight:600}
.corr-row{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:13px}
.corr-name{width:96px;color:var(--txt)}
.corr-bar{flex:1;height:16px;background:#0c0f14;border-radius:4px;position:relative;overflow:hidden}
.corr-fill{position:absolute;top:0;height:100%;border-radius:4px}
.corr-val{width:44px;text-align:left;font-variant-numeric:tabular-nums}
.muted{color:var(--dim);font-size:12px}
#idxchart,#candles{width:100%}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;font-size:12px}
.legend span{display:inline-flex;align-items:center;gap:5px;cursor:pointer;opacity:.9}
.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.off{opacity:.32;text-decoration:line-through}
</style></head><body>
<header>
  <h1>📈 Index Chart — الذهب وسلّته المرتبطة</h1>
  <span class="pill" id="gold">—</span>
  <span class="pill" id="upd">—</span>
  <span class="pill">مُعاد التأسيس على 100 · الأصول العكسيّة مقلوبة (ارتفاعها = داعمٌ للذهب)</span>
</header>
<div class="wrap">
  <div>
    <div class="card"><h2>الحركة النسبيّة (كلّها بدأت من 100)</h2><div id="idxchart"></div><div class="legend" id="legend"></div></div>
    <div class="card" style="margin-top:14px"><h2>شموع الذهب + EMA50/EMA200 + المستويات (يوميّ/أسبوعيّ/شهريّ)</h2><div id="candles"></div></div>
    <div class="card" style="margin-top:14px"><h2>Stochastic (14,3,3 EMA) <span id="stochlbl" class="muted"></span></h2><div id="stoch"></div>
      <p class="muted">🔴 90/85 تشبّع بيعيّ · 🟢 15/10 تشبّع شرائيّ · 50 الوسط (إعداداتك بالضبط)</p></div>
  </div>
  <div>
    <div class="card"><h2>الارتباط الحيّ مع الذهب (عوائد H1)</h2><div id="corr"></div>
      <p class="muted" id="note">أخضر = يتحرّك مع الذهب · أحمر = عكسه. القيمة قرب ±1 = ارتباطٌ أقوى.</p>
    </div>
    <div class="card" style="margin-top:14px"><h2>🔔 حارس المستويات <span id="sentmode" class="muted"></span></h2>
      <div id="sentstate" class="muted" style="font-size:12px;line-height:1.8"></div>
      <div id="sentalerts" style="margin-top:8px"></div>
      <p id="senthonesty" class="muted" style="font-size:10px;margin-top:8px;border-top:1px solid var(--line);padding-top:6px"></p>
    </div>
  </div>
</div>
<script type="module">
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";
const off = new Set();
async function load(){
  let d; try{ d = await (await fetch('/index/data')).json(); }catch(e){ return; }
  if(d.error){ document.getElementById('note').textContent = 'خطأ: '+d.error; return; }
  document.getElementById('gold').textContent = 'الذهب: '+d.gold_last;
  document.getElementById('upd').textContent = 'تحديث '+d.updated;
  // ---- Index chart (Observable Plot) ----
  const long=[];
  for(const s of d.series){ if(off.has(s.sym)) continue;
    for(let i=0;i<s.index.length;i++) long.push({t:d.times[i],v:s.index[i],k:s.label,c:s.color,sym:s.sym}); }
  const idxEl=document.getElementById('idxchart'); idxEl.innerHTML='';
  idxEl.append(Plot.plot({
    width: idxEl.clientWidth||820, height: 340, marginLeft:44, marginRight:60,
    style:{background:'transparent',color:'#e6e9ef',fontSize:'11px'},
    x:{ticks:6,grid:false,label:null,tickFormat:t=>t.slice(0,5)},
    y:{grid:true,label:'المؤشّر (=100 بداية)'},
    color:{domain:d.series.map(s=>s.label),range:d.series.map(s=>s.color)},
    marks:[
      Plot.ruleY([100],{stroke:'#3a3f4b',strokeDasharray:'3,3'}),
      Plot.line(long,{x:'t',y:'v',stroke:'c',strokeWidth:s=>s==='الذهب'?3:1.4,z:'k'}),
      Plot.text(long, Plot.selectLast({x:'t',y:'v',z:'k',text:'k',fill:'c',dx:6,fontSize:10,textAnchor:'start'}))
    ]
  }));
  // ---- Legend (toggle) ----
  const lg=document.getElementById('legend'); lg.innerHTML='';
  for(const s of d.series){ const el=document.createElement('span'); el.className=off.has(s.sym)?'off':'';
    el.innerHTML='<i style="background:'+s.color+'"></i>'+s.label;
    el.onclick=()=>{ off.has(s.sym)?off.delete(s.sym):off.add(s.sym); load(); }; lg.append(el); }
  // ---- Correlation bars ----
  const cr=document.getElementById('corr'); cr.innerHTML='';
  const sorted=[...d.series].filter(s=>s.sym!=='XAUUSDm').sort((a,b)=>b.corr-a.corr);
  for(const s of sorted){ const pos=s.corr>=0, w=Math.min(Math.abs(s.corr)*50,50);
    const row=document.createElement('div'); row.className='corr-row';
    row.innerHTML='<span class="corr-name">'+s.label.replace('‏ (معكوس)','')+'</span>'+
      '<span class="corr-bar"><span class="corr-fill" style="'+(pos?'right:50%':'left:50%')+
      ';width:'+w+'%;background:'+(pos?'var(--up)':'var(--dn)')+'"></span>'+
      '<span style="position:absolute;left:50%;top:0;height:100%;width:1px;background:#3a3f4b"></span></span>'+
      '<span class="corr-val" style="color:'+(pos?'var(--up)':'var(--dn)')+'">'+(pos?'+':'')+s.corr+'</span>';
    cr.append(row); }
  // ---- Gold candles + EMA50/EMA200 + levels ----
  const c=d.candles, cEl=document.getElementById('candles'); cEl.innerHTML='';
  const lvColor=n=>(n.includes('اليوم')||n.includes('الأمس'))?'#f5c518':n.includes('الأسبوع')?'#4fd0e0':n.includes('الشهر')?'#e07ad0':'#5a6070';
  cEl.append(Plot.plot({
    width:cEl.clientWidth||820, height:300, marginLeft:46, marginRight:120,
    style:{background:'transparent',color:'#e6e9ef',fontSize:'11px'},
    x:{ticks:6,label:null,tickFormat:t=>t.slice(0,5)}, y:{grid:true,label:null},
    marks:[
      ...d.levels.map(L=>Plot.ruleY([L.price],{stroke:lvColor(L.name),strokeOpacity:.5,strokeDasharray:'3,3'})),
      ...d.levels.map(L=>Plot.text([L],{x:c[c.length-1]?.t,y:'price',text:D=>D.name+' '+D.price,fill:lvColor(L.name),dx:6,fontSize:9,textAnchor:'start'})),
      Plot.ruleX(c,{x:'t',y1:'l',y2:'h',stroke:o=>o.c>=o.o?'#26a67a':'#e05a5a'}),
      Plot.rectY(c,{x:'t',y1:'o',y2:'c',fill:o=>o.c>=o.o?'#26a67a':'#e05a5a',width:5}),
      Plot.line(c,{x:'t',y:'e50',stroke:'#f0a030',strokeWidth:1.5}),
      Plot.line(c,{x:'t',y:'e200',stroke:'#4f8fe0',strokeWidth:1.8}),
      Plot.text([c[c.length-1]],{x:'t',y:'e50',text:()=>'EMA50',fill:'#f0a030',dx:6,fontSize:9,textAnchor:'start'}),
      Plot.text([c[c.length-1]],{x:'t',y:'e200',text:()=>'EMA200',fill:'#4f8fe0',dx:6,fontSize:9,textAnchor:'start'})
    ]
  }));
  // ---- Stochastic (14,3,3 EMA) ----
  const sEl=document.getElementById('stoch'); sEl.innerHTML='';
  if(d.stoch && d.stoch.t && d.stoch.t.length){
    const S=d.stoch.t.map((t,i)=>({t,k:d.stoch.k[i],dd:d.stoch.d[i]}));
    const kNow=d.stoch.k[d.stoch.k.length-1], dNow=d.stoch.d[d.stoch.d.length-1];
    const zone=kNow>=85?'🔴 تشبّع بيعيّ':kNow<=15?'🟢 تشبّع شرائيّ':'⚪ محايد';
    sEl.append(Plot.plot({
      width:sEl.clientWidth||820, height:150, marginLeft:46, marginRight:120,
      style:{background:'transparent',color:'#e6e9ef',fontSize:'11px'},
      x:{ticks:6,label:null,tickFormat:t=>t.slice(0,5)}, y:{domain:[0,100],grid:false,ticks:[10,15,50,85,90]},
      marks:[
        Plot.areaY(S,{x:'t',y1:85,y2:100,fill:'#e05a5a',fillOpacity:.07}),
        Plot.areaY(S,{x:'t',y1:0,y2:15,fill:'#26a67a',fillOpacity:.07}),
        ...[90,85,50,15,10].map(v=>Plot.ruleY([v],{stroke:v===50?'#5a6070':(v>=85?'#e05a5a':'#26a67a'),strokeOpacity:.5,strokeDasharray:'2,3'})),
        Plot.line(S,{x:'t',y:'k',stroke:'#f5c518',strokeWidth:1.6}),
        Plot.line(S,{x:'t',y:'dd',stroke:'#5a8fe0',strokeWidth:1.4}),
        Plot.text([S[S.length-1]],{x:'t',y:'k',text:()=>'%K '+kNow,fill:'#f5c518',dx:6,fontSize:9,textAnchor:'start'}),
        Plot.text([S[S.length-1]],{x:'t',y:'dd',text:()=>'%D '+dNow,fill:'#5a8fe0',dx:6,fontSize:9,textAnchor:'start'})
      ]
    }));
    document.getElementById('stochlbl').textContent='— الآن %K='+kNow+' %D='+dNow+' · '+zone;
  }
  // ---- Level Sentinel panel ----
  const SN=d.sentinel;
  if(SN){
    document.getElementById('sentmode').textContent = SN.execute?('— تنفيذ ON (توافق≥'+SN.min_exec_score+' · ديمو · ≤3%)'):'— تنبيه فقط';
    document.getElementById('sentstate').innerHTML =
      'السعر <b>'+SN.price+'</b> · Stoch '+SN.stoch_k+' · ترند '+SN.trend+'<br>'+
      'EMA50 '+SN.ema50+' · EMA200 '+SN.ema200+' · 🕯️ '+(SN.candle||'—')+'<br>'+
      SN.basket+' · لوت مقترح ≤3%: <b>'+SN.rec_lot+'</b>';
    const fa=document.getElementById('sentalerts'); fa.innerHTML='';
    const feed=SN.feed||[];
    if(!feed.length){ fa.innerHTML='<span class="muted" style="font-size:12px">لا تنبيهات الآن — ينتظر لمسة مستوى + توافق</span>'; }
    for(const a of feed){
      const clr=(a.kind.includes('شراء')||a.kind.includes('صعود'))?'#26a67a':'#e05a5a';
      const el=document.createElement('div');
      el.style.cssText='border-right:3px solid '+clr+';padding:5px 8px;margin:5px 0;background:#0c0f14;border-radius:5px;font-size:12px';
      el.innerHTML='<b style="color:'+clr+'">'+a.kind+'</b> @ '+a.level+' ('+a.level_price+') · توافق '+a.score+'/6 · '+a.iso+
        '<br><span class="muted">'+a.reasons+' · لوت≤'+a.rec_lot+'</span>';
      fa.append(el);
    }
    document.getElementById('senthonesty').textContent='⚖️ '+(SN.honesty||'');
  }
}
load(); setInterval(load, 15000);
window.addEventListener('resize',()=>{clearTimeout(window._rz);window._rz=setTimeout(load,300)});
</script></body></html>"""
