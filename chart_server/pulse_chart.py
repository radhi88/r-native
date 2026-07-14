# -*- coding: utf-8 -*-
"""chart_server/pulse_chart.py — واجهة «نبض السوق» العصريّة (كلّ العملات).

وحدة عرضٍ صِرفة (قراءة ملفّات فقط — لا MT5 هنا؛ محرّك النبض هو مالك الاتصال):
- get_pulse_data() ⇒ dict: يقرأ data/r_native/market_pulse.json + آخر 8 أسطر من market_pulse_feed.jsonl.
- PULSE_HTML ⇒ صفحة كاملة (عربي RTL، زجاجيّة داكنة، عدّادات دائريّة متحرّكة، شرائط إشارات، بلا مكتبات خارجيّة).

الربط في server.py (يقوم به المالك): /pulse ⇒ PULSE_HTML · /pulse/data ⇒ get_pulse_data().
"""
from __future__ import annotations
import json as _json
import os as _os
import time as _time

_PULSE = r"C:\Users\Radhi\MT5\data\r_native\market_pulse.json"
_FEED = r"C:\Users\Radhi\MT5\data\r_native\market_pulse_feed.jsonl"


def _tail_lines(path: str, n: int = 8, chunk: int = 32768):
    """آخر n أسطر من ملفٍ نصّي دون قراءته كاملاً (يكفي مقطع الذيل)."""
    try:
        size = _os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")
        lines = [x for x in raw.strip().splitlines() if x.strip()]
        return lines[-n:]
    except Exception:
        return []


def get_pulse_data():
    """حمولة الواجهة: النبض + آخر 8 إشارات + عمر البيانات بالثواني. مقاوِمٌ لغياب الملفّات."""
    out = {"pulse": None, "feed": [], "age_sec": None}
    try:
        with open(_PULSE, encoding="utf-8") as f:
            out["pulse"] = _json.load(f)
    except FileNotFoundError:
        out["error"] = "market_pulse.json غير موجود بعد — شغّل محرّك النبض أوّلاً"
        return out
    except Exception as e:  # ملف تالف/قيد الكتابة
        out["error"] = f"تعذّرت قراءة النبض: {e}"
        return out
    try:
        out["age_sec"] = round(max(0.0, _time.time() - _os.path.getmtime(_PULSE)), 1)
    except Exception:
        pass
    for ln in reversed(_tail_lines(_FEED, 8)):  # الأحدث أوّلاً
        try:
            out["feed"].append(_json.loads(ln))
        except Exception:
            continue
    return out


# ══════════════════════════════ الصفحة ══════════════════════════════
PULSE_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>نبض السوق</title>
<style>
:root{
  --bg:#0a0e17; --card:rgba(20,27,45,.55); --card2:rgba(28,36,60,.65);
  --line:rgba(255,255,255,.07); --txt:#e8ecf4; --dim:#8a93a6;
  --gold:#f5c518; --orange:#ff8c2e; --green:#22dd88; --red:#ff4d5e;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--txt);
  font-family:"Segoe UI",Tahoma,Arial,sans-serif;min-height:100vh;
  background-image:
    radial-gradient(900px 420px at 85% -10%, rgba(245,197,24,.10), transparent 60%),
    radial-gradient(800px 500px at 8% 110%, rgba(70,110,255,.10), transparent 60%);
  padding:18px 22px 40px;
}
/* ── الترويسة ── */
header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:16px}
h1{
  font-size:26px;font-weight:800;letter-spacing:.5px;
  background:linear-gradient(90deg,var(--gold),var(--orange));
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.hsub{color:var(--dim);font-size:12px}
.spacer{flex:1}
#clock{font-variant-numeric:tabular-nums;font-size:15px;color:var(--txt);
  background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:6px 14px;backdrop-filter:blur(12px)}
.conn{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);
  background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:6px 12px;backdrop-filter:blur(12px)}
#dot{width:10px;height:10px;border-radius:50%;background:var(--red);transition:background .4s}
#dot.on{background:var(--green);animation:beat 1.6s ease-in-out infinite}
@keyframes beat{0%,100%{box-shadow:0 0 0 0 rgba(34,221,136,.55)}55%{box-shadow:0 0 0 8px rgba(34,221,136,0)}}
/* ── شريط الإشارات ── */
#feedwrap{margin-bottom:18px}
.ftitle{font-size:12px;color:var(--dim);margin-bottom:6px;letter-spacing:1px}
#feed{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;scrollbar-width:thin}
.fitem{
  flex:0 0 auto;display:flex;align-items:center;gap:9px;
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:8px 13px;backdrop-filter:blur(14px);font-size:12.5px;white-space:nowrap;
}
.fitem.new{animation:slidein .5s cubic-bezier(.2,.9,.3,1.2)}
@keyframes slidein{from{transform:translateX(-26px);opacity:0}to{transform:none;opacity:1}}
.ftime{color:var(--dim);font-variant-numeric:tabular-nums;font-size:11px}
.fsym{font-weight:700}
.dchip{border-radius:999px;padding:2px 10px;font-size:11px;font-weight:700}
.dchip.buy{background:rgba(34,221,136,.16);color:var(--green);border:1px solid rgba(34,221,136,.35)}
.dchip.sell{background:rgba(255,77,94,.14);color:var(--red);border:1px solid rgba(255,77,94,.35)}
.ftxt{color:var(--dim);max-width:230px;overflow:hidden;text-overflow:ellipsis}
/* ── شبكة البطاقات ── */
#grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
.card{
  position:relative;border-radius:16px;padding:14px 15px 12px;cursor:pointer;
  background:linear-gradient(160deg,var(--card2),var(--card));
  border:1px solid var(--line);backdrop-filter:blur(16px);
  transition:transform .25s,border-color .5s,box-shadow .6s;
}
.card:hover{transform:translateY(-3px)}
.card.up{border-color:rgba(34,221,136,.4);box-shadow:0 0 22px -6px rgba(34,221,136,.35)}
.card.dn{border-color:rgba(255,77,94,.4);box-shadow:0 0 22px -6px rgba(255,77,94,.35)}
.chead{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.sym{font-weight:800;font-size:15px;letter-spacing:.4px}
.bos{font-size:15px;margin-inline-start:auto}
.bos.u{color:var(--green)} .bos.d{color:var(--red)} .bos.n{color:var(--dim)}
.cmid{display:flex;align-items:center;gap:12px}
.gwrap{position:relative;width:76px;height:76px;flex:0 0 auto}
.gwrap svg{transform:rotate(-90deg)}
.gtrack{fill:none;stroke:rgba(255,255,255,.08);stroke-width:7}
.garc{fill:none;stroke-width:7;stroke-linecap:round;transition:stroke-dashoffset .8s cubic-bezier(.3,.8,.3,1),stroke .8s}
.gnum{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;transition:color .6s}
.gnum.flash{animation:pop .5s}
@keyframes pop{40%{transform:scale(1.18)}}
.read{font-size:12.5px;line-height:1.7;color:var(--txt);opacity:.92;flex:1;min-height:40px}
.badges{display:flex;flex-wrap:wrap;gap:5px;margin:9px 0 7px}
.pill{font-size:10.5px;border-radius:999px;padding:2px 9px;border:1px solid var(--line);color:var(--dim);
  background:rgba(255,255,255,.04);animation:pin .4s}
@keyframes pin{from{transform:scale(.6);opacity:0}}
.pill.m1{border-color:rgba(245,197,24,.4);color:var(--gold)}
.pill.m5{border-color:rgba(255,140,46,.45);color:var(--orange)}
.spark{width:100%;height:30px;display:block;margin-top:2px}
.cfoot{display:flex;justify-content:space-between;font-size:11px;color:var(--dim);
  border-top:1px solid var(--line);margin-top:8px;padding-top:7px;font-variant-numeric:tabular-nums}
/* ── النافذة التفصيليّة ── */
#ovl{position:fixed;inset:0;display:none;align-items:center;justify-content:center;
  background:rgba(5,8,15,.6);backdrop-filter:blur(6px);z-index:50}
#ovl.show{display:flex}
#modal{
  width:min(780px,94vw);max-height:92vh;overflow-y:auto;border-radius:20px;padding:22px;
  background:linear-gradient(165deg,rgba(30,39,66,.92),rgba(16,22,38,.92));
  border:1px solid rgba(255,255,255,.12);box-shadow:0 30px 80px -20px #000;
  animation:mopen .3s cubic-bezier(.2,.9,.3,1.15);
}
@keyframes mopen{from{transform:scale(.85);opacity:0}}
#mhead{display:flex;align-items:center;margin-bottom:14px}
#msym{font-size:20px;font-weight:800;background:linear-gradient(90deg,var(--gold),var(--orange));
  -webkit-background-clip:text;background-clip:text;color:transparent}
#mclose{margin-inline-start:auto;cursor:pointer;color:var(--dim);font-size:20px;border:none;background:none}
#mclose:hover{color:var(--txt)}
#mread{font-size:13px;line-height:1.9;color:var(--txt);margin-bottom:14px;opacity:.95}
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.mrow{background:rgba(255,255,255,.045);border:1px solid var(--line);border-radius:12px;padding:9px 12px}
.mk{font-size:10.5px;color:var(--dim);margin-bottom:3px}
.mv{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.msec{grid-column:1/-1}
/* ── مخطّط SMC داخل النافذة ── */
#mchart svg{width:100%;height:auto;display:block;border-radius:12px;background:rgba(0,0,0,.28);border:1px solid var(--line)}
#mlegend{display:flex;flex-wrap:wrap;gap:11px;font-size:10.5px;color:var(--dim);margin:8px 0 12px}
#mlegend span{display:inline-flex;align-items:center;gap:4px}
.lg{width:14px;height:8px;border-radius:2px;display:inline-block}
#mfoot{font-size:10.5px;color:var(--dim);margin-top:12px;border-top:1px solid var(--line);padding-top:8px;text-align:center}
/* ── شريط SMC المصغّر على البطاقة ── */
.smcstrip{display:flex;align-items:center;gap:5px;margin-top:6px;font-size:10.5px;flex-wrap:wrap;min-height:18px}
.strend{font-weight:800;font-size:12px}
.strend.u{color:var(--green)} .strend.d{color:var(--red)} .strend.n{color:var(--dim)}
.schip{border-radius:999px;padding:1px 8px;border:1px solid rgba(160,120,255,.4);color:#b9a8ff;background:rgba(160,120,255,.08)}
.spoc{color:#35d6e8;font-variant-numeric:tabular-nums}
/* ── حالة الخطأ ── */
#err{display:none;margin:60px auto;max-width:420px;text-align:center;
  background:var(--card);border:1px solid rgba(255,77,94,.35);border-radius:18px;
  padding:28px;backdrop-filter:blur(14px);color:var(--dim);line-height:2}
#err b{color:var(--red);display:block;font-size:16px;margin-bottom:6px}
</style>
</head>
<body>
<header>
  <div>
    <h1>نبض السوق</h1>
    <div class="hsub">ضغط لحظي لكلّ العملات — قراءة عربيّة + أنماط M1/M5 + بنية BOS</div>
  </div>
  <div class="spacer"></div>
  <div class="conn"><span id="dot"></span><span id="conntxt">بانتظار البيانات…</span></div>
  <div id="clock">--:--:--</div>
</header>

<div id="feedwrap">
  <div class="ftitle">آخر الإشارات القويّة</div>
  <div id="feed"></div>
</div>

<div id="grid"></div>
<div id="err"><b>لا نبض</b><span id="errtxt"></span></div>

<div id="ovl"><div id="modal">
  <div id="mhead"><span id="msym"></span><button id="mclose">✕</button></div>
  <div id="mread"></div>
  <div id="mchart"></div>
  <div id="mlegend">
    <span><i class="lg" style="background:rgba(34,221,136,.35)"></i>OB شرائي</span>
    <span><i class="lg" style="background:rgba(255,77,94,.35)"></i>OB بيعي</span>
    <span><i class="lg" style="background:rgba(245,197,24,.3)"></i>FVG</span>
    <span><i class="lg" style="background:rgba(160,120,255,.35)"></i>IFVG</span>
    <span style="color:#35d6e8">‒ ‒ POC</span><span style="color:rgba(53,214,232,.8)">·· HVN</span>
    <span>·· $$$ سيولة</span><span style="color:var(--gold)">⚡ اصطياد</span>
    <span style="color:var(--green)">BOS▲</span><span style="color:#b9a8ff">CHoCH كسر هيكل</span>
  </div>
  <div class="mgrid" id="mgrid"></div>
  <div id="mfoot">سياقٌ بصريّ — SMC ليست إشارة آليّة (مُقاس: ~50% OOS)</div>
</div></div>

<script>
"use strict";
/* ─── أدوات ─── */
const $=id=>document.getElementById(id);
const N=(v,d)=> (v===null||v===undefined||isNaN(+v)) ? d : +v;
const fmt=(v,p)=> (v===null||v===undefined||isNaN(+v)) ? "—" : (+v).toFixed(p===undefined?2:p);
/* لون العدّاد: أحمر(0) → رمادي(50) → أخضر(100) */
function scoreColor(s){
  s=Math.max(0,Math.min(100,N(s,50)));
  const R=[255,77,94],G=[138,147,166],B=[34,221,136];
  const mix=(a,b,t)=>a.map((x,i)=>Math.round(x+(b[i]-x)*t));
  const c = s<=50 ? mix(R,G,s/50) : mix(G,B,(s-50)/50);
  return "rgb("+c.join(",")+")";
}
/* توحيد شكل الرموز وفق مخطّط المحرّك (market_pulse.json):
   {score, read, pattern_m1/{name,dir,strength}, structure/{bos,swing_*}, momentum/{stoch,rsi,trend}, volume/{z,spike}, volatility/{atr,spread}, spark, price} */
function patList(p){ // نمط مفرد {name,dir} أو قائمة أسماء — كلاهما يصير [{name,dir}]
  if(!p) return [];
  if(Array.isArray(p)) return p.map(x=>typeof x==="string"?{name:x,dir:0}:x).filter(x=>x&&x.name);
  return p.name ? [p] : [];
}
function symbolsOf(p){
  if(!p) return [];
  let s=p.symbols||p.pairs||p.data||p;
  let arr=[];
  if(Array.isArray(s)) arr=s.map(o=>({sym:o.symbol||o.sym||"?",...o}));
  else if(typeof s==="object")
    arr=Object.entries(s).filter(([k,v])=>v&&typeof v==="object")
        .map(([k,v])=>({sym:v.symbol||k,...v}));
  return arr.map(o=>{
    const st=o.structure||{}, mo=o.momentum||{}, vo=o.volume||{}, va=o.volatility||{};
    const bosN = typeof st==="object" ? N(st.bos,0) : 0;
    return {
      sym:String(o.sym), score:N(o.score??o.pressure,50),
      read:o.read||o.text||"", price:o.price,
      m1:patList(o.pattern_m1||o.patterns_m1), m5:patList(o.pattern_m5||o.patterns_m5),
      bos: bosN>0?"up":bosN<0?"down":String(o.bos||"none").toLowerCase(),
      swing_high:st.swing_high, swing_low:st.swing_low,
      spark:Array.isArray(o.spark)?o.spark:[],
      spread:va.spread??o.spread, atr:va.atr14_m5??o.atr, spread_atr:va.spread_atr_pct,
      stoch_k:mo.stoch_k, stoch_d:mo.stoch_d, rsi:mo.rsi9,
      trend_m1:N(mo.trend_m1,0), trend_m5:N(mo.trend_m5,0),
      vol_z:vo.z??o.vol_z, vol_spike:!!vo.spike,
      smc:(o.smc&&typeof o.smc==="object")?o.smc:null,
      candles:Array.isArray(o.candles_m5)?o.candles_m5:[],
      cfirst:N(o.candles_m5_first_idx,-1),
    };
  });
}

/* ─── الساعة ─── */
setInterval(()=>{ $("clock").textContent=new Date().toLocaleTimeString("en-GB"); },1000);

/* ─── بناء بطاقة (مرّة واحدة لكلّ رمز) ─── */
const CIRC=2*Math.PI*32;          // محيط قوس العدّاد r=32
const cards={}, last={};           // عناصر البطاقات + آخر بيانات لكلّ رمز (للنافذة)
function buildCard(sym){
  const gid="sg-"+sym.replace(/[^A-Za-z0-9]/g,"");
  const el=document.createElement("div");
  el.className="card"; el.dataset.sym=sym;
  el.innerHTML=
   '<div class="chead"><span class="sym"></span><span class="bos n">•</span></div>'+
   '<div class="cmid">'+
     '<div class="gwrap"><svg viewBox="0 0 76 76" width="76" height="76">'+
       '<circle class="gtrack" cx="38" cy="38" r="32"/>'+
       '<circle class="garc" cx="38" cy="38" r="32" stroke-dasharray="'+CIRC+'" stroke-dashoffset="'+CIRC+'"/>'+
     '</svg><div class="gnum">–</div></div>'+
     '<div class="read"></div>'+
   '</div>'+
   '<div class="badges"></div>'+
   '<div class="smcstrip"></div>'+
   '<svg class="spark" viewBox="0 0 110 30" preserveAspectRatio="none">'+
     '<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="110" y2="0" gradientUnits="userSpaceOnUse">'+
       '<stop offset="0" stop-color="#f5c518"/><stop offset="1" stop-color="#ff8c2e"/>'+
     '</linearGradient></defs>'+
     '<polyline fill="none" stroke="url(#'+gid+')" stroke-width="1.8" stroke-linejoin="round" points=""/>'+
   '</svg>'+
   '<div class="cfoot"><span class="fspread"></span><span class="fatr"></span></div>';
  el.querySelector(".sym").textContent=sym;
  el.addEventListener("click",()=>openModal(sym));
  $("grid").appendChild(el);
  cards[sym]=el;
  return el;
}

/* ─── تحديث بطاقة في مكانها (دون إعادة رسمٍ كاملة = لا وميض) ─── */
function updateCard(o){
  const el=cards[o.sym]||buildCard(o.sym);
  const col=scoreColor(o.score);
  // العدّاد الدائري
  const arc=el.querySelector(".garc"), num=el.querySelector(".gnum");
  arc.style.strokeDashoffset=(CIRC*(1-Math.max(0,Math.min(100,o.score))/100)).toFixed(1);
  arc.style.stroke=col; num.style.color=col;
  const stxt=String(Math.round(o.score));
  if(num.textContent!==stxt){ num.textContent=stxt; num.classList.remove("flash"); void num.offsetWidth; num.classList.add("flash"); }
  // القراءة العربيّة + سهم BOS
  const rd=el.querySelector(".read"); if(rd.textContent!==o.read) rd.textContent=o.read;
  const bos=el.querySelector(".bos");
  const up=/up|bull|صاعد/.test(o.bos), dn=/down|bear|هابط/.test(o.bos);
  bos.textContent = up?"⬈ BOS":dn?"⬊ BOS":"•";
  bos.className = "bos "+(up?"u":dn?"d":"n");
  // شارات الأنماط + سبايك الحجم (تُعاد فقط عند تغيّرها)
  const chips=[...o.m1.map(x=>["m1",x]),...o.m5.map(x=>["m5",x])];
  if(o.vol_spike) chips.push(["vz",{name:"سبايك حجم",dir:0}]);
  const key=JSON.stringify(chips), bd=el.querySelector(".badges");
  if(bd.dataset.k!==key){
    bd.dataset.k=key; bd.innerHTML="";
    for(const [tf,p] of chips.slice(0,6)){
      const s=document.createElement("span");
      s.className="pill "+tf;
      s.textContent=(tf==="m1"?"M1 ":tf==="m5"?"M5 ":"")+p.name+(p.dir>0?" ▲":p.dir<0?" ▼":"");
      bd.appendChild(s);
    }
  }
  // خطّ الشرارة
  const pl=el.querySelector(".spark polyline"), a=o.spark;
  if(a&&a.length>1){
    let mn=Math.min(...a), mx=Math.max(...a), rg=(mx-mn)||1e-9;
    pl.setAttribute("points",a.map((v,i)=>
      ((i/(a.length-1))*110).toFixed(1)+","+(27-((v-mn)/rg)*24).toFixed(1)).join(" "));
  }
  // التذييل + توهّج الإطار
  el.querySelector(".fspread").textContent="سبريد "+fmt(o.spread,2)+(o.spread_atr!==undefined?" ("+fmt(o.spread_atr,0)+"% ATR)":"");
  el.querySelector(".fatr").textContent="ATR "+fmt(o.atr,o.atr>=10?1:3);
  el.classList.toggle("up",o.score>=58);
  el.classList.toggle("dn",o.score<=42);
  smcStrip(el,o);
  last[o.sym]=o;
}

/* ─── شريط SMC المصغّر على البطاقة: سهم الاتجاه + رقاقتان + بُعد POC ─── */
function smcStrip(el,o){
  const box=el.querySelector(".smcstrip"), s=o.smc;
  if(!s){ if(box.innerHTML)box.innerHTML=""; return; }
  const t=N(s.trend,0);
  let h='<span class="strend '+(t>0?"u":t<0?"d":"n")+'">'+(t>0?"⬈":t<0?"⬊":"•")+"</span>";
  const chips=[];
  if((s.choch||[]).length){const e=s.choch[s.choch.length-1];chips.push("CHoCH"+(e.dir>0?"↑":"↓"));}
  else if((s.bos||[]).length){const e=s.bos[s.bos.length-1];chips.push("BOS"+(e.dir>0?"↑":"↓"));}
  if((s.fvg||[]).some(z=>z.inverted||z.filled<1)) chips.push("FVG");
  if((s.sweeps||[]).length) chips.push("$$$⚡"); else if((s.liq_pools||[]).length) chips.push("$$$");
  for(const c of chips.slice(0,2)) h+='<span class="schip">'+c+"</span>";
  if(s.poc!==undefined&&s.poc!==null&&o.price){
    const d=o.price-s.poc;
    h+='<span class="spoc">POC '+(d>=0?"+":"")+fmt(d,Math.abs(d)>=10?1:3)+"</span>";
  }
  if(box.dataset.k!==h){ box.dataset.k=h; box.innerHTML=h; }
}

/* ─── شريط الإشارات ─── */
let feedKeys=new Set();
function renderFeed(items){
  const box=$("feed"); box.innerHTML="";
  for(const it of (items||[])){
    const t=it.iso||it.time||it.ts||"", sym=it.symbol||it.sym||"؟";
    const dv=it.dir!==undefined?+it.dir:NaN;
    const buy=isNaN(dv)?/buy|long|شراء|up/.test(String(it.direction||it.side||"").toLowerCase()):dv>0;
    const k=t+"|"+sym+"|"+(buy?1:-1);
    const d=document.createElement("div");
    d.className="fitem"+(feedKeys.has(k)?"":" new");
    const note=it.read||it.pattern||it.note||"";
    d.innerHTML='<span class="ftime"></span><span class="fsym"></span>'+
      '<span class="dchip '+(buy?"buy":"sell")+'">'+(buy?"شراء ▲":"بيع ▼")+"</span>"+
      (note?'<span class="ftxt"></span>':"");
    d.querySelector(".ftime").textContent=String(t).slice(-8);
    d.querySelector(".fsym").textContent=sym+(it.score!==undefined?" · "+Math.round(it.score):"");
    const tx=d.querySelector(".ftxt"); if(tx) tx.textContent=note;
    box.appendChild(d);
    feedKeys.add(k);
  }
  if(feedKeys.size>300) feedKeys=new Set([...feedKeys].slice(-100));
}

/* ─── مخطّط SMC: شموع M5 حقيقيّة + مناطق مرسومة (SVG صِرف) ─── */
function smcSvg(o){
  const C=o.candles;
  if(!C||C.length<5) return '<div style="color:var(--dim);font-size:12px;padding:26px;text-align:center">لا شموع M5 بعد — بانتظار المحرّك</div>';
  const s=o.smc||{}, n=C.length, W=700,H=360,PL=8,PR=62,PT=12,PB=22,PW=W-PL-PR,PH=H-PT-PB;
  let lo=1/0,hi=-1/0; for(const c of C){ lo=Math.min(lo,+c[3]); hi=Math.max(hi,+c[2]); }
  const pad=(hi-lo)*.05||1e-9; lo-=pad; hi+=pad;
  const dp=hi>=1000?2:hi>=10?3:5, R=W-PR;
  const X=i=>PL+(Math.max(0,Math.min(n-1,i))+.5)*PW/n, Y=p=>PT+(hi-p)*PH/(hi-lo);
  // محاذاة الفهارس: المحرّك يُصدِّر فهرس أوّل شمعة (cfirst)؛ وإلا نقدّر من أحدث حدث (احتياط لملفّ قديم)
  const idxs=[].concat(s.bos||[],s.choch||[],s.ob||[],s.fvg||[],s.sweeps||[]).map(e=>N(e.idx,0));
  const off=o.cfirst>=0?o.cfirst:Math.max(0,(idxs.length?Math.max.apply(null,idxs):0)-(n-1));
  const xi=i=>X(N(i,0)-off), bw=Math.max(2,PW/n*.6);
  const T=(x,y,t,fill,fs,w)=>'<text x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" fill="'+fill+'" font-size="'+(fs||9)+'"'+(w?' font-weight="700"':"")+' stroke="#0a0e17" stroke-width="3" paint-order="stroke" font-family="Segoe UI">'+t+"</text>";
  let g="";
  // شبكة + محور السعر يميناً
  for(let k=0;k<=4;k++){ const p=lo+(hi-lo)*k/4, y=Y(p);
    g+='<line x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+R+'" y2="'+y.toFixed(1)+'" stroke="rgba(255,255,255,.05)"/>'
      +'<text x="'+(R+5)+'" y="'+(y+3.5).toFixed(1)+'" fill="#8a93a6" font-size="10">'+p.toFixed(dp)+"</text>"; }
  // مؤشّرات الوقت أسفلاً
  for(const i of [0,(n/3)|0,(2*n/3)|0,n-1]){ let t=+C[i][0]; if(t<2e10)t*=1000; const d=new Date(t);
    g+='<text x="'+X(i).toFixed(1)+'" y="'+(H-6)+'" fill="#8a93a6" font-size="9.5" text-anchor="middle">'
      +String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0")+"</text>"; }
  // مناطق OB: مستطيلات شفّافة تمتدّ يميناً (أحمر بيعي / أخضر شرائي، باهتة إن خُفِّفت)
  for(const z of (s.ob||[]).slice(-4)){ const zl=Math.max(z.lo,lo),zh=Math.min(z.hi,hi); if(zh<=zl)continue;
    const x=xi(z.idx), c=z.dir>0?"34,221,136":"255,77,94";
    g+='<rect x="'+x.toFixed(1)+'" y="'+Y(zh).toFixed(1)+'" width="'+(R-x).toFixed(1)+'" height="'+Math.max(1,Y(zl)-Y(zh)).toFixed(1)
      +'" fill="rgba('+c+',.12)" stroke="rgba('+c+',.4)" stroke-width=".7" opacity="'+(z.mitigated?"0.5":"1")+'"/>'
      +T(x+3,Y(zh)+10,"OB"+(z.mitigated?" ✓":""),"rgba("+c+",.9)");
  }
  // فجوات FVG (ذهبيّة) / IFVG المعكوسة (بنفسجيّة) — تُخفى المملوءة كلّياً
  for(const z of (s.fvg||[]).slice(-4)){ if(!z.inverted&&z.filled>=1)continue;
    const zl=Math.max(z.lo,lo),zh=Math.min(z.hi,hi); if(zh<=zl)continue;
    const x=xi(z.idx), c=z.inverted?"160,120,255":"245,197,24";
    g+='<rect x="'+x.toFixed(1)+'" y="'+Y(zh).toFixed(1)+'" width="'+(R-x).toFixed(1)+'" height="'+Math.max(1,Y(zl)-Y(zh)).toFixed(1)
      +'" fill="rgba('+c+',.13)" stroke="rgba('+c+',.4)" stroke-width=".7" stroke-dasharray="3 3"/>'
      +T(x+3,Y(zl)-3,z.inverted?"IFVG":"FVG","rgba("+c+",.95)");
  }
  // خطوط أفقيّة: POC متقطّع سماوي · HVN منقّط رفيع · بِرَك السيولة $$$ منقّط أبيض
  const hline=(p,col,dash,lbl,fs)=>{ if(!(p>=lo&&p<=hi))return""; const y=Y(p);
    return '<line x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+R+'" y2="'+y.toFixed(1)+'" stroke="'+col+'" stroke-dasharray="'+dash+'"/>'+(lbl?T(PL+3,y-3,lbl,col,fs||9.5,1):""); };
  for(const p of (s.hvn||[])) if(p!==s.poc) g+=hline(+p,"rgba(53,214,232,.3)","2 5","");
  if(s.poc!==undefined&&s.poc!==null) g+=hline(+s.poc,"#35d6e8","7 5","POC",10);
  for(const p of (s.liq_pools||[]).slice(-4)) g+=hline(+p.price,"rgba(255,255,255,.55)","2 4","$$$"+(p.count>2?"×"+p.count:""));
  // الشموع (فتيل + جسم)
  for(let i=0;i<n;i++){ const c=C[i],o1=+c[1],h1=+c[2],l1=+c[3],c1=+c[4],x=X(i),col=c1>=o1?"#22dd88":"#ff4d5e";
    g+='<line x1="'+x.toFixed(1)+'" y1="'+Y(h1).toFixed(1)+'" x2="'+x.toFixed(1)+'" y2="'+Y(l1).toFixed(1)+'" stroke="'+col+'" stroke-width="1"/>'
      +'<rect x="'+(x-bw/2).toFixed(1)+'" y="'+Y(Math.max(o1,c1)).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(1,Y(Math.min(o1,c1))-Y(Math.max(o1,c1))).toFixed(1)+'" fill="'+col+'"/>';
  }
  // علامات اصطياد السيولة ⚡ + أعلام BOS/CHoCH عند شمعتها (CHoCH أبرز)
  for(const sw of (s.sweeps||[]).slice(-6)) g+=T(xi(sw.idx)-4,Y(+sw.price)+(sw.side==="high"?-5:13),"⚡","#f5c518",12);
  for(const e of (s.bos||[]).slice(-3)) g+=T(xi(e.idx)-10,Y(+e.price)+(e.dir>0?-6:14),"BOS"+(e.dir>0?"▲":"▼"),e.dir>0?"#22dd88":"#ff4d5e",9);
  for(const e of (s.choch||[]).slice(-3)){ const x=xi(e.idx), y=Y(+e.price)+(e.dir>0?-9:17);
    g+='<line x1="'+x.toFixed(1)+'" y1="'+Y(+e.price).toFixed(1)+'" x2="'+x.toFixed(1)+'" y2="'+(y+(e.dir>0?2:-9)).toFixed(1)+'" stroke="#b9a8ff" stroke-width="1"/>'
      +T(x-16,y,"CHoCH"+(e.dir>0?"▲":"▼"),"#b9a8ff",10.5,1);
  }
  return '<svg viewBox="0 0 '+W+" "+H+'" xmlns="http://www.w3.org/2000/svg">'+g+"</svg>";
}

/* ─── النافذة التفصيليّة (تُعاد رسمتها في مكانها مع كلّ تحديث وهي مفتوحة) ─── */
let openSym=null;
function renderModal(o){
  $("msym").textContent=o.sym;
  $("mread").textContent=(o.read||"—")+(o.smc&&o.smc.summary?" · "+o.smc.summary:"");
  $("mchart").innerHTML=smcSvg(o);
  const tr=v=> v>0?"صاعد ▲":v<0?"هابط ▼":"محايد";
  const rows=[
    ["الضغط",Math.round(o.score)],["السعر",fmt(o.price,o.price>=1000?2:o.price>=10?3:5)],
    ["Stoch %K / %D",fmt(o.stoch_k,1)+" / "+fmt(o.stoch_d,1)],["RSI-9",fmt(o.rsi,1)],
    ["اتّجاه M1",tr(o.trend_m1)],["اتّجاه M5",tr(o.trend_m5)],
    ["BOS",o.bos==="up"?"كسر صاعد ⬈":o.bos==="down"?"كسر هابط ⬊":"—"],["حجم Z",fmt(o.vol_z)+(o.vol_spike?" ⚡":"")],
    ["قمّة سوينغ",fmt(o.swing_high,3)],["قاع سوينغ",fmt(o.swing_low,3)],
    ["السبريد",fmt(o.spread,2)+(o.spread_atr!==undefined?" ("+fmt(o.spread_atr,0)+"% ATR)":"")],["ATR14 M5",fmt(o.atr,3)],
  ];
  let h=rows.map(([k,v])=>'<div class="mrow"><div class="mk">'+k+'</div><div class="mv">'+v+"</div></div>").join("");
  const pn=a=>a.map(p=>p.name+(p.dir>0?" ▲":p.dir<0?" ▼":"")).join(" · ")||"—";
  h+='<div class="mrow msec"><div class="mk">أنماط M1</div><div class="mv" style="font-size:12.5px">'+pn(o.m1)+"</div></div>";
  h+='<div class="mrow msec"><div class="mk">أنماط M5</div><div class="mv" style="font-size:12.5px">'+pn(o.m5)+"</div></div>";
  $("mgrid").innerHTML=h;
}
function openModal(sym){
  const o=last[sym]; if(!o) return;
  openSym=sym; renderModal(o);
  $("ovl").classList.add("show");
}
function closeModal(){ openSym=null; $("ovl").classList.remove("show"); }
$("mclose").onclick=closeModal;
$("ovl").addEventListener("click",e=>{ if(e.target.id==="ovl") closeModal(); });

/* ─── دورة التحديث (كل 3 ثوانٍ، تحديث في المكان) ─── */
async function tick(){
  let d;
  try{ d=await (await fetch("/pulse/data",{cache:"no-store"})).json(); }
  catch(e){ setConn(false,"انقطاع عن الخادم"); return; }
  if(d.error){ $("err").style.display="block"; $("errtxt").textContent=d.error; setConn(false,"لا ملفّ نبض"); return; }
  $("err").style.display="none";
  const fresh = d.age_sec!==null && d.age_sec!==undefined && d.age_sec<10;
  setConn(fresh, fresh?"حيّ ("+d.age_sec+" ث)":"قديم ("+fmt(d.age_sec,0)+" ث)");
  const syms=symbolsOf(d.pulse);
  for(const o of syms) updateCard(o);
  // ترتيب: الأنشط أوّلاً (|الضغط−50| تنازلياً) — إعادة إلحاقٍ فقط عند تغيّر الترتيب
  const order=syms.slice().sort((a,b)=>Math.abs(b.score-50)-Math.abs(a.score-50)).map(o=>o.sym);
  const cur=[...$("grid").children].map(e=>e.dataset.sym);
  if(order.join()!==cur.join()) for(const s of order) if(cards[s]) $("grid").appendChild(cards[s]);
  renderFeed(d.feed);
  if(openSym&&last[openSym]) renderModal(last[openSym]);  // تحديث لحظي للمخطّط والنافذة وهي مفتوحة
}
function setConn(ok,txt){ $("dot").className=ok?"on":""; $("conntxt").textContent=txt; }
tick(); setInterval(tick,3000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    # فحص يدوي سريع: اطبع الحمولة (أو الخطأ) دون خادم
    print(_json.dumps(get_pulse_data(), ensure_ascii=False)[:1500])
