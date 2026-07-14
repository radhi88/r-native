# -*- coding: utf-8 -*-
"""brain_graph.py — «المخّ الحيّ الضخم» لـ R Trader: خمس طبقات حقيقية في مجرّة واحدة تتنفّس وتتحرّك.

كلّ عقدة وكلّ رابط هنا حقيقيّ (لا حشو):
  0 معرفة  (ذهبي)   : خزنة plutobrain — ملاحظات + أشباح [[الروابط]].
  1 أسطول  (أخضر)   : محرّكات ENGINES من نصّ watchdog_guard.py (regex، بلا استيراد) + الماجيك.
  2 المجلس (بنفسجي) : ~96 وكيلاً × رموز agent_council.json — كلّ وكيل يقيّم كلّ رمز فعلاً كلّ 2ث.
  3 صفقات  (أحمر/أخضر): آخر ذيل محدود من friday.db، مثبّتة على رمزها تسبح معه (غبار حيّ).
  4 كود    (أزرق فولاذي): ملفات *.py الجذرية + روابط الاستيراد بينها.

⚙️ محرّك حيّ (2026-07-08، طلب المستخدم «إلى أقصى حدّ + كفاءة عالية»): تخطيط مجرّي حتميّ على الخادم
يعطي «الوطن» (home) لكلّ عقدة؛ العميل يشغّل محاكاة قوى حقيقيّة على العقد البنيويّة (~600) فقط:
تنافرٌ محلّيّ عبر شبكة مكانيّة O(n)، زنبركات على الروابط الحقيقيّة، ومرساةُ-وطنٍ تحفظ الطبقات الخمس.
غبار الصفقات مثبّتٌ بإزاحةٍ ثابتة على عقدة رمزه ⇒ يسبح مع الرمز بلا كلفة فيزياء. النبضات
الحيّة تسافر على الروابط عند كلّ رسالة حقيقيّة وتَنكز العقدَ فتتفاعل. فشل-ناعم: طبقة تفشل تُتخطّى؛
فشل كلّيّ ⇒ صفحة خطأ عربية (لا رفع استثناء أبداً — عقد الـgateway).
"""
import json
import math
import re
import sqlite3
from pathlib import Path

MT5 = Path(r"C:\Users\Radhi\MT5")
VAULT = MT5 / "plutobrain"
RN = MT5 / "data" / "r_native"
DB = MT5 / "data" / "friday.db"
ROOT_NOTE = "Company Brain - الدليل.md"
GA = 2.39996322972865           # الزاوية الذهبية (راديان)
GHOST_CAP = 80
TRADE_CAP = 1500
_PENT_R = 950                   # نصف قطر خماسيّ مراكز الطبقات
_LC = [(round(_PENT_R * math.cos(-math.pi / 2 + k * 2 * math.pi / 5), 1),
        round(_PENT_R * math.sin(-math.pi / 2 + k * 2 * math.pi / 5), 1)) for k in range(5)]
LAYERS = [("معرفة", "#f5c518"), ("أسطول", "#3ddc84"), ("المجلس العصبيّ", "#b58cff"),
          ("صفقات", "#e0455a"), ("كود", "#7a9cc4")]
MAGIC_ENGINE = {20260701: "gold_level_sentinel.py", 20260706: "brain_trader.py",
                20260707: "council_sniper.py", 20260709: "level_sentinel_multi.py",
                20260631: "youtube_analyst_agent.py", 20260600: "friday_mcp_server"}

_FENCE_RE = re.compile(r"```.*?```", re.S)
_CODE_RE = re.compile(r"`[^`\n]*`")
_LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
_IMP_RE = re.compile(r"^[ \t]*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)

_ERR_PAGE = """<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>مخّ R Trader</title><style>body{background:#04050a;color:#e8e8e8;font-family:Tahoma,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#12151c;border:1px solid #6b2d2d;border-radius:12px;padding:28px 44px;text-align:center}
h2{color:#f5c518;margin:0 0 8px}</style></head><body><div class="card">
<h2>🧠 المخّ غير متاح</h2><p>تعذّر بناء أيّ طبقة من طبقات المخّ — تأكّد من المجلدات ثم حدّث الصفحة.</p>
</div></body></html>"""

_PAGE = r"""<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>مخّ R Trader الحيّ</title><style>
html,body{margin:0;height:100%;background:#04050a;overflow:hidden}
#c{display:block;cursor:default}
#t{position:fixed;top:12px;right:16px;color:#e8ddb0;font:15px Tahoma,Arial,sans-serif;
   text-shadow:0 0 14px rgba(245,197,24,.35);pointer-events:none}
#s{position:fixed;bottom:10px;right:16px;color:#5f6a7c;font:11px Tahoma,Arial,sans-serif;pointer-events:none}
#lg{position:fixed;top:12px;left:14px;display:flex;flex-direction:column;gap:6px;font:12px Tahoma,Arial,sans-serif}
.lb{display:flex;align-items:center;gap:8px;background:rgba(10,14,22,.72);border:1px solid #1d2635;
    border-radius:9px;padding:5px 11px;color:#cdd8e8;cursor:pointer;user-select:none}
.lb.off{opacity:.32}.dot{width:9px;height:9px;border-radius:50%;flex:none}
#hud{position:fixed;top:36px;right:16px;color:#9fb0c6;font:12px Consolas,Tahoma,monospace;
   pointer-events:none;text-shadow:0 0 8px rgba(0,0,0,.6);direction:rtl}
#hud .no{color:#e6a15a}#hud .ok{color:#59d98c}#hud .v{color:#e8ddb0}
#fps{position:fixed;bottom:10px;left:14px;color:#3f4a5c;font:11px Consolas,monospace;pointer-events:none}
#bus{position:fixed;bottom:34px;left:14px;width:min(38vw,430px);max-height:44vh;overflow:hidden;
   display:flex;flex-direction:column;gap:3px;direction:rtl;pointer-events:none;font:12px Tahoma,Arial,sans-serif}
#bus .bh{color:#7f8da0;font:11px Tahoma;opacity:.8;margin-bottom:2px}
#bus .m{background:rgba(9,13,21,.66);border-right:2px solid #444;border-radius:7px;
   padding:3px 9px;color:#c8d4e6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#bus .m b{color:#eef3fb;font-weight:600}#bus .m .k{opacity:.7;font-size:11px}
#bus .m.k-trigger{border-right-color:#f5c518}#bus .m.k-consensus{border-right-color:#49d8ff}
#bus .m.k-govern{border-right-color:#49ffa8}#bus .m.k-veto{border-right-color:#ff5468}
/* 🆕 لوحة تفاصيل العقدة عند التمرير (أعلى-الوسط، لا تتداخل مع #lg يساراً ولا #hud/#t يميناً) */
#tip{position:fixed;top:12px;left:50%;transform:translateX(-50%);background:rgba(9,13,21,.92);
   border:1px solid #2a3547;border-radius:9px;padding:6px 14px;color:#dce6f5;
   font:12px Tahoma,Arial,sans-serif;pointer-events:none;display:none;z-index:6;white-space:nowrap;
   box-shadow:0 2px 16px rgba(0,0,0,.55)}
#tip b{color:#ffe9a8}#tip .ly{color:#8ea3bf}#tip .orph{color:#e06666;font-weight:600}
/* 🆕 مفتاح ألوان أنواع الرسائل السبعة (KIND_COL) — أسفل-يمين فوق #s */
#legend{position:fixed;bottom:30px;right:16px;display:flex;flex-direction:column;gap:3px;
   font:11px Tahoma,Arial,sans-serif;pointer-events:none;background:rgba(9,13,21,.55);
   border:1px solid #1a2231;border-radius:8px;padding:6px 10px}
#legend .lh{color:#7f8da0;margin-bottom:2px}#legend .lr{display:flex;align-items:center;gap:7px;color:#aeb9c9}
#legend .ld{width:15px;height:3px;border-radius:2px;flex:none}
/* 🆕 شريط تحذير تعارض القرارات (مخفيّ افتراضيّاً — البيانات متّسقة، حارسٌ استقباليّ) */
#warn{position:fixed;top:0;left:0;right:0;background:rgba(199,42,52,.94);color:#fff;font:13px Tahoma,Arial,sans-serif;
   text-align:center;padding:7px 12px;display:none;z-index:9;box-shadow:0 2px 18px rgba(220,40,50,.6)}
#lg .lb.orphan-tgl{margin-top:4px;border-color:#3a2a3a}
</style></head><body>
<div id="warn"></div>
<div id="t">🧠 مخّ R Trader الحيّ — __NN__ عقدة · __NE__ رابطاً (يتحرّك ويتنفّس)</div>
<div id="hud">🧠 المتعلّم: <span class="v">—</span></div>
<div id="tip"></div>
<div id="legend"></div>
<div id="s">اسحب للتحريك · العجلة للتقريب · مرّر فوق أيّ عقدة لترى روابطها · مسافة=إيقاف الحركة · أزرار اليسار تعزل الطبقات</div>
<div id="fps"></div>
<div id="lg"></div>
<div id="bus"><div class="bh">🚌 تبادل المعلومات الحيّ (رسائل حقيقيّة بين المحرّكات)</div></div>
<canvas id="c"></canvas><script>
const N=__NODES__,E=__EDGES__,LY=__LAYERS__,SY=__SYM__,AG=__AG__,LBL=__LBL__,CONF=__CONF__,WR=__WR__;
const cv=document.getElementById('c'),cx=cv.getContext('2d',{alpha:false});
const NN=N.length;
/* ===== حالة الفيزياء: مصفوفات مسطّحة (Float32) للسرعة ===== */
const px=new Float32Array(NN),py=new Float32Array(NN),vx=new Float32Array(NN),vy=new Float32Array(NN),
      hx=new Float32Array(NN),hy=new Float32Array(NN),rad=new Float32Array(NN),lay=new Int8Array(NN);
const dyn=[],pinned=[],par=new Int32Array(NN),offx=new Float32Array(NN),offy=new Float32Array(NN);
for(let i=0;i<NN;i++){const n=N[i];px[i]=hx[i]=n.x;py[i]=hy[i]=n.y;rad[i]=n.r;lay[i]=n.layer;par[i]=-1;
  if(n.p!==undefined&&n.p>=0){pinned.push(i);par[i]=n.p}else dyn.push(i)}
for(const i of pinned){const p=par[i];offx[i]=hx[i]-hx[p];offy[i]=hy[i]-hy[p]}
/* الجيران (لإبراز الروابط عند التمرير) */
const nbr=N.map(()=>[]);for(const [a,b] of E){nbr[a].push(b);nbr[b].push(a)}
/* روابط الزنبرك = الروابط بين عقدتين ديناميّتين (الغبار المثبّت لا يشدّ) */
const springs=[];for(const [a,b] of E){if(par[a]<0&&par[b]<0)springs.push([a,b])}
/* 🆕 DPR: مخزن الرسم = أبعاد CSS × كثافة البكسل (حدّ 2.5 للأداء)، وحجم العرض ثابت عبر CSS.
   W,H تبقى بكسلات CSS منطقيّة؛ الأساس dpr يُضبط في frame() فيرسم كلّ شيء حادّاً دون ضبابيّة. */
let W,H,dpr=1;function rs(){dpr=Math.max(1,Math.min(window.devicePixelRatio||1,2.5));
 W=innerWidth;H=innerHeight;cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
 cv.style.width=W+'px';cv.style.height=H+'px'}rs();
let zoom=Math.min(W,H)/(2.15*WR),ox=0,oy=0,hov=-1,running=true;const act=[1,1,1,1,1];
onresize=rs;
const conf=N.map(()=>null),confAnim=new Float32Array(NN).fill(0.5);let confSeen=false;
/* ===== شبكة مكانيّة للتنافر المحلّيّ O(n) — تُعاد كلّ إطار على العقد الديناميّة فقط ===== */
const RCELL=34;let gcell={};
function rebuildGrid(){gcell={};for(const i of dyn){const k=((px[i]/RCELL)|0)+','+((py[i]/RCELL)|0);
  (gcell[k]||(gcell[k]=[])).push(i)}}
/* ===== خطوة الفيزياء: تنافر محلّيّ + زنبرك روابط + مرساة وطن + تخميد ===== */
const REP=52,SPR=0.010,REST=17,HOME=0.020,DAMP=0.90,VMAX=42;
function physics(dt){
 if(!running)return;
 rebuildGrid();
 const fx=new Float32Array(NN),fy=new Float32Array(NN);
 /* تنافر: لكلّ عقدة، ادفعها بعيداً عن جيران خلاياها الـ9 (محلّيّ ⇒ يمنع التراكب) */
 for(const i of dyn){const cxk=(px[i]/RCELL)|0,cyk=(py[i]/RCELL)|0;
  for(let gx=cxk-1;gx<=cxk+1;gx++)for(let gy=cyk-1;gy<=cyk+1;gy++){
   const cell=gcell[gx+','+gy];if(!cell)continue;
   for(const jjj of cell){if(jjj<=i)continue;
    let dx=px[i]-px[jjj],dy=py[i]-py[jjj];let d2=dx*dx+dy*dy;
    if(d2>RCELL*RCELL*2||d2<1e-4){if(d2<1e-4){dx=(Math.random()-.5);dy=(Math.random()-.5);d2=dx*dx+dy*dy+1e-4}else continue}
    const f=REP/d2,inv=1/Math.sqrt(d2),ux=dx*inv*f,uy=dy*inv*f;
    fx[i]+=ux;fy[i]+=uy;fx[jjj]-=ux;fy[jjj]-=uy}}}
 /* زنبرك الروابط الحقيقيّة: تقارب العقد الموصولة نحو طول راحةٍ قصير */
 for(const [a,b] of springs){const dx=px[b]-px[a],dy=py[b]-py[a];
  const d=Math.sqrt(dx*dx+dy*dy)+1e-6,f=SPR*(d-REST)/d;
  fx[a]+=dx*f;fy[a]+=dy*f;fx[b]-=dx*f;fy[b]-=dy*f}
 /* مرساة الوطن: تحفظ المجرّة الخماسيّة (بلا انفجار/انجراف) */
 for(const i of dyn){fx[i]+=(hx[i]-px[i])*HOME;fy[i]+=(hy[i]-py[i])*HOME;
  vx[i]=(vx[i]+fx[i])*DAMP;vy[i]=(vy[i]+fy[i])*DAMP;
  const sp=Math.hypot(vx[i],vy[i]);if(sp>VMAX){const s=VMAX/sp;vx[i]*=s;vy[i]*=s}
  px[i]+=vx[i]*dt;py[i]+=vy[i]*dt}
 /* الغبار المثبّت يتبع رمزه الحيّ بإزاحته الثابتة (يسبح مع العنقود) */
 for(const i of pinned){const p=par[i];px[i]=px[p]+offx[i];py[i]=py[p]+offy[i]}
}
/* نكزة تفاعليّة: عند إطلاق عقدةٍ نمنحها دفعة صغيرة (تتفاعل مرئيّاً) */
function nudge(i,m){if(par[i]>=0||i<0||i>=NN)return;const a=Math.random()*6.283;
 vx[i]+=Math.cos(a)*m;vy[i]+=Math.sin(a)*m}
/* ===== النبضات: مجلس (وكيل→رمز) + ناقل (frm→to) — تسافر على المواضع الحيّة ===== */
const pulses=[],bpulses=[],SYK=Object.values(SY);let amb=0,ambBus=0;
function fire(si,dir,n){if(!act[2]||!AG.length||si===undefined)return;
 const c=dir>0?'#49ffa8':(dir<0?'#ff5468':'#9ad8ff');nudge(si,3);
 for(let i=0;i<n;i++){const A=AG[(Math.random()*AG.length)|0];
  pulses.push({a:A,b:si,t:performance.now()+Math.random()*700,d:900+Math.random()*700,c:c})}
 if(pulses.length>420)pulses.splice(0,pulses.length-420)}
const KIND_COL={trigger:'#f5c518',consensus:'#49d8ff',govern:'#49ffa8',veto:'#ff5468',
                fuse:'#8fd9ff',entry:'#f5c518',exit:'#ffb057'};
const busEdges=[],busEdgeSeen=new Set();
function anchor(name){if(name==null)return undefined;
 if(LBL[name]!==undefined)return LBL[name];const k=SY[name];return k!==undefined?k:undefined}
function firePath(ai,bi,kind,label,rev){if(ai<0||bi<0||ai>=NN||bi>=NN)return;
 const c=KIND_COL[kind]||'#9ad8ff';nudge(bi,2);
 bpulses.push({a:ai,b:bi,t:performance.now()+(rev?170:0),d:(rev?1250:1550)+Math.random()*450,
   c:c,label:(rev?'':(label||kind||'')),rev:!!rev,bend:(rev?-0.16:0.16)});
 if(bpulses.length>140)bpulses.splice(0,bpulses.length-140)}
function fireBurst(ai,bi,kind,label){firePath(ai,bi,kind,label,false);
 const extra=1+((Math.random()*2)|0);
 for(let i=0;i<extra;i++)setTimeout(()=>firePath(ai,bi,kind,'',false),120+i*140);
 setTimeout(()=>firePath(bi,ai,kind,'',true),620+Math.random()*260);
 const k=ai+'>'+bi;if(!busEdgeSeen.has(k)){busEdgeSeen.add(k);busEdges.push([ai,bi,kind])}}
/* ===== المجلس الحيّ: /live/data (المصدر الصحيح — /council أُزيل، كان 404) ===== */
let prev={};
async function poll(){if(document.hidden)return;let rows=null;
 try{const d=await(await fetch('/live/data',{cache:'no-store'})).json();
  if(d&&d.symbols)rows=Object.entries(d.symbols).map(([s,o])=>({s:s,dir:o.dir||0,p:o.agreement_pct||0}));
  else if(d&&d.council)rows=d.council.map(r=>({s:r.sym,dir:r.dir||0,p:r.pct||0}))}catch(e){}
 if(!rows)return;
 for(const r of rows){const k=SY[r.s];if(k===undefined)continue;const pv=prev[r.s];
  if(pv&&(pv.dir!==r.dir||pv.p!==r.p))fire(k,r.dir,20+Math.floor(Math.random()*21));
  prev[r.s]=r}}
setInterval(poll,2500);poll();
/* ===== 🚌 الناقل الحيّ: رسائل حقيقيّة → شريط + نبضات حاملة نصّاً ===== */
const busEl=document.getElementById('bus');
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function busKey(m){return (m.ts||'')+'|'+(m.frm||'')+'|'+(m.to||'')+'|'+(m.text||'')}
let busSeen=new Set(),busFirst=true;
function renderTicker(msgs){const view=msgs.slice(-12).reverse();
 while(busEl.children.length>1)busEl.removeChild(busEl.lastChild);
 view.forEach((m,idx)=>{const d=document.createElement('div');const kind=(m.kind||'').toString();
  d.className='m'+(KIND_COL[kind]?' k-'+kind:'');d.style.opacity=(1-idx*0.07).toFixed(2);
  d.innerHTML='<b>'+esc(m.frm||'?')+'</b> → <b>'+esc(m.to||'?')+'</b>'
   +(kind?' · <span class="k">'+esc(kind)+'</span>':'')+((m.text)?' · '+esc(m.text):'');
  busEl.appendChild(d)})}
async function pollBus(){if(document.hidden)return;let d=null;try{d=await(await fetch('/rt/bus',{cache:'no-store'})).json()}catch(e){return}
 if(!d)return;const msgs=Array.isArray(d)?d:(d.messages||[]);if(!msgs.length)return;
 renderTicker(msgs);
 for(const m of msgs){const key=busKey(m);if(busSeen.has(key))continue;busSeen.add(key);
  if(busFirst)continue;const ai=anchor(m.frm),bi=anchor(m.to);
  if(ai!==undefined&&bi!==undefined&&ai!==bi){const txt=(m.text||'').toString();
   fireBurst(ai,bi,(m.kind||'').toString(),(m.frm||'?')+'→'+(m.to||'?')+(txt?' '+txt:''))}}
 if(busSeen.size>400)busSeen=new Set(msgs.slice(-80).map(busKey));busFirst=false}
setInterval(pollBus,2500);pollBus();
function ambientBus(dt){if(!busEdges.length)return;ambBus+=dt*6;
 while(ambBus>=1){ambBus--;const e=busEdges[(Math.random()*busEdges.length)|0];
  const rev=Math.random()<0.5,a=rev?e[1]:e[0],b=rev?e[0]:e[1];
  bpulses.push({a:a,b:b,t:performance.now(),d:1400+Math.random()*500,
   c:KIND_COL[e[2]]||'#9ad8ff',label:'',rev:rev,bend:rev?-0.16:0.16,dim:true});
  if(bpulses.length>140)bpulses.splice(0,bpulses.length-140)}}
/* ===== 🧠 المتعلّم-الفوقيّ الصادق ===== */
const hudEl=document.getElementById('hud');
function fmt(x){return (x===null||x===undefined||isNaN(+x))?'—':(+x).toFixed(3)}
const VERD_AR={no_edge:'لا حافّة',no_data:'لا بيانات',insufficient_data:'بيانات غير كافية',flat:'مسطّح',learning:'إشارة قابلة للقياس'};
const CONF_AR={low:'ثقة منخفضة',med:'ثقة متوسّطة',high:'ثقة عالية',none:'—'};
const CAL_AR={calibrated:'الثقة مُعايَرة',anti_calibrated:'الثقة مُضلّلة',uncorrelated:'الثقة لا تتنبّأ',insufficient:'محرّكات قليلة',unobserved:'لا ملفّ ثقة',flat:'—'};
async function pollMeta(){if(document.hidden)return;let d=null;try{d=await(await fetch('/rt/meta',{cache:'no-store'})).json()}catch(e){return}
 if(!d){hudEl.innerHTML='🧠 المتعلّم: <span class="v">—</span>';return}
 const v=(d.verdict||'no_data').toString();const no=/no_edge|no_data|flat|neg|insufficient/i.test(v);
 const cls=no?'no':(/learning|edge|good|pos/i.test(v)?'ok':'v');const vAr=VERD_AR[v]||v;
 const br=(d.brier!=null)?fmt(d.brier):'—';
 const et=(d.edge_tstat!=null)?fmt(d.edge_tstat):((d.edge_t!==undefined)?fmt(d.edge_t):((d.t!==undefined)?fmt(d.t):'—'));
 const noos=(d.n_oos!=null)?d.n_oos:((d.n!==undefined)?d.n:null);const nStr=(noos!==null)?(' · n_oos='+noos):'';
 const confLvl=(d.confidence&&CONF_AR[d.confidence])?(' <span class="'+(d.confidence==='low'?'no':'v')+'">['+CONF_AR[d.confidence]+']</span>'):'';
 let cal='';const cc=d.confidence_calibration;
 if(cc&&cc.status){const cvd=(cc.verdict&&CAL_AR[cc.verdict])?CAL_AR[cc.verdict]:(CAL_AR[cc.status]||cc.status);
  const good=cc.verdict==='calibrated',bad=(cc.verdict==='anti_calibrated'||cc.verdict==='uncorrelated');
  const ccls=good?'ok':(bad?'no':'v'),rr=(cc.pearson_r!=null)?(' r='+fmt(cc.pearson_r)):'';
  cal=' · 🔭 <span class="'+ccls+'">'+esc(cvd)+'</span><span class="v">'+esc(rr)+'</span>'}
 hudEl.innerHTML='🧠 المتعلّم: <span class="'+cls+'">'+esc(vAr)+'</span>'+confLvl
  +' · brier <span class="v">'+br+'</span> · t=<span class="v">'+et+'</span>'+esc(nStr)+cal}
setInterval(pollMeta,2500);pollMeta();
/* ===== 🔭 تنفّس الثقة الحيّة ===== */
async function pollSense(){if(document.hidden)return;let d=null;try{d=await(await fetch('/rt/sense',{cache:'no-store'})).json()}catch(e){return}
 if(!d||!d.confidence)return;const cmap=d.confidence;let any=false;
 for(const k in cmap){const idx=CONF[k];if(idx===undefined)continue;const c=+cmap[k];if(isNaN(c))continue;
  conf[idx]=Math.max(0,Math.min(1,c));any=true}if(any)confSeen=true}
setInterval(pollSense,3000);pollSense();
/* ===== أزرار الطبقات ===== */
const lg=document.getElementById('lg');
LY.forEach((L,i)=>{const b=document.createElement('div');b.className='lb';
 b.innerHTML='<span class="dot" style="background:'+L.c+'"></span>'+L.n+' · '+L.k.toLocaleString();
 b.onclick=()=>{act[i]=act[i]?0:1;b.classList.toggle('off',!act[i]);if(hov>=0&&!act[lay[hov]])hov=-1};
 lg.appendChild(b)});
addEventListener('keydown',e=>{if(e.code==='Space'){e.preventDefault();running=!running}});
/* ===== 🆕 العقد اليتيمة (بلا رابط): عدّها + زرّ إظهار/إخفاء (معتّمة افتراضيّاً لتنظيف المشهد) ===== */
let showOrphans=false;
const _orphanN=N.reduce((s,_,i)=>s+(nbr[i].length===0?1:0),0);
(function(){const b=document.createElement('div');b.className='lb orphan-tgl';
 const upd=()=>{b.innerHTML='<span class="dot" style="background:#6f6a55"></span>عقد يتيمة · '
   +_orphanN.toLocaleString()+(showOrphans?' (ظاهرة)':' (معتّمة)');b.classList.toggle('off',!showOrphans)};
 b.onclick=()=>{showOrphans=!showOrphans;upd();if(hov>=0&&nbr[hov].length===0&&!showOrphans)hov=-1};
 upd();lg.appendChild(b)})();
/* ===== 🆕 مفتاح ألوان أنواع الرسائل السبعة (KIND_COL) ===== */
(function(){const el=document.getElementById('legend');
 const AR={trigger:'زناد',consensus:'إجماع',govern:'حوكمة',veto:'فيتو',fuse:'دمج',entry:'دخول',exit:'خروج'};
 let h='<div class="lh">🚦 أنواع الرسائل</div>';
 for(const k in AR)h+='<div class="lr"><span class="ld" style="background:'+KIND_COL[k]+'"></span>'+AR[k]+'</div>';
 el.innerHTML=h})();
/* ===== 🆕 لوحة تفاصيل العقدة عند التمرير (اسم · طبقة عربيّة · عدد روابط · يتيمة؟) — تُحدَّث فقط عند تغيّر العقدة ===== */
const tipEl=document.getElementById('tip');let _tipHov=-2;
function renderTip(){
 if(hov===_tipHov)return;_tipHov=hov;
 if(hov<0){tipEl.style.display='none';return}
 const deg=nbr[hov].length,lyn=(LY[lay[hov]]&&LY[lay[hov]].n)||('طبقة '+lay[hov]);
 tipEl.innerHTML='<b>'+esc(N[hov].id)+'</b> · <span class="ly">'+esc(lyn)+'</span> · '
  +deg.toLocaleString()+' رابط'+(deg===0?' <span class="orph">(يتيمة)</span>':'');
 tipEl.style.display='block'}
/* ===== 🆕 حارس تعارض القرارات: يقرأ الناقل كل ~500ms ويكشف (أ) خلاف محرّكين على رمز (شراء مقابل بيع)،
   (ب) تعارض اقتصاديّ مع الدولار DXY. عند تعارضٍ ⇒ شريطٌ أحمر يسمّي الرموز. البيانات الحاليّة متّسقة ⇒ صامت. ===== */
const warnEl=document.getElementById('warn');
const _USD_QUOTE={EURUSDm:1,GBPUSDm:1,AUDUSDm:1,NZDUSDm:1};      /* الدولار مقوّمٌ: صعود الزوج ⇒ دولار ضعيف */
const _USD_BASE={USDJPYm:1,USDCADm:1,USDCHFm:1};                 /* الدولار أساسٌ: صعود الزوج ⇒ دولار قويّ */
function _msgDir(t){t=(t||'').toString();return /شراء|buy|صعود|↑/i.test(t)?1:(/بيع|sell|هبوط|↓/i.test(t)?-1:0)}
function _msgSym(t){const m=(t||'').toString().match(/\b([A-Z]{6}m|DXYm?)\b/);return m?m[1]:null}
/* 🆕 2026-07-08: المخّ لم يعد يكتفي بالكشف — يعرض «المُعالِج الذاتيّ» (conflict_resolver) وهو يحلّ:
   يمنع الدخول المتعارض مع الدولار (وقائيّ) ويقصّ مراكزنا المتعارضة الخاسرة. الشريط أخضرُ مُطمئن
   (يُعالَج بنفسه) لا أحمرُ سلبيّ. غياب المُعالِج ⇒ رجوعٌ ناعمٌ لكشف العميل (debounce) الأحمر. */
let _confSeen={};
function _clientDetect(msgs){
 const bySym={};
 for(const m of msgs){const s=_msgSym(m.text),dir=_msgDir(m.text);if(!s||!dir)continue;
  (bySym[s]||(bySym[s]={}))[m.frm||'?']=dir}
 const dom=o=>{if(!o)return 0;const v=Object.values(o),u=v.filter(x=>x>0).length,dn=v.filter(x=>x<0).length;
  return u>dn?1:(dn>u?-1:0)};
 const bad=[];
 for(const s in bySym){const v=Object.values(bySym[s]);if(v.includes(1)&&v.includes(-1))bad.push(s+' (شراء+بيع)')}
 const dxy=dom(bySym.DXYm||bySym.DXY);
 if(dxy){for(const s in bySym){const dir=dom(bySym[s]);if(!dir)continue;
  if(_USD_QUOTE[s]&&Math.sign(dir)===Math.sign(dxy))bad.push(s+' ضدّ الدولار');
  if(_USD_BASE[s]&&Math.sign(dir)!==Math.sign(dxy))bad.push(s+' ضدّ الدولار')}}
 const uniq=[...new Set(bad)],now=performance.now(),stable=[];
 for(const b of uniq){if(!_confSeen[b])_confSeen[b]=now;if(now-_confSeen[b]>=1500)stable.push(b)}
 for(const k in _confSeen)if(uniq.indexOf(k)<0)delete _confSeen[k];
 return stable;
}
async function checkConflicts(){if(document.hidden)return;
 let c=null;try{c=await(await fetch('/rt/coherence',{cache:'no-store'})).json()}catch(e){}
 if(c&&c.active){                                        /* 🧩 المُعالِج يعمل ⇒ اعرض حلّه (أخضر مُطمئن) */
  const vetoed=c.vetoed||[],resolved=c.resolved_now||0,conflicts=c.conflicts||[];
  if(!vetoed.length&&!resolved&&!conflicts.length){warnEl.style.display='none';return}
  const parts=[];
  if(vetoed.length)parts.push('منع الدخول ضدّ الدولار: '+vetoed.join('، '));
  if(resolved)parts.push('قصّ '+resolved+' مركزاً متعارضاً خاسراً');
  if(!parts.length&&conflicts.length)parts.push('يعالج: '+conflicts.join('، '));
  warnEl.textContent='🧩 المُعالِج الذاتيّ يحلّ: '+parts.join(' · ');
  warnEl.style.background='rgba(38,150,92,.93)';         /* أخضر = يُعالَج بنفسه */
  warnEl.style.display='block';return;
 }
 /* رجوعٌ ناعم: المُعالِج غير مُشغَّل ⇒ كشف العميل (أحمر) كما كان */
 let d=null;try{d=await(await fetch('/rt/bus',{cache:'no-store'})).json()}catch(e){return}
 const msgs=(d&&(Array.isArray(d)?d:d.messages))||[];
 if(!msgs.length){warnEl.style.display='none';_confSeen={};return}
 const stable=_clientDetect(msgs);
 if(stable.length){warnEl.textContent='⚠️ تعارض قرارات (مستمرّ): '+stable.join(' · ');
  warnEl.style.background='rgba(199,42,52,.94)';warnEl.style.display='block'}
 else warnEl.style.display='none'}
setInterval(checkConflicts,1000);checkConflicts();
/* ===== حلقة الرسم: مواضع حيّة + فيزياء + طبقات نبض ===== */
const fpsEl=document.getElementById('fps');let last=performance.now(),facc=0,ffr=0,fps=0,rafActive=false;
function scheduleFrame(){if(rafActive||document.hidden)return;rafActive=true;requestAnimationFrame(frame)}
document.addEventListener('visibilitychange',()=>{if(!document.hidden){last=performance.now();poll();pollBus();pollMeta();pollSense();checkConflicts();scheduleFrame()}});
function frame(now){
 rafActive=false;if(document.hidden)return;
 const dt=Math.min((now-last)/1000,.05);last=now;
 physics(dt);
 facc+=dt;ffr++;if(facc>=0.5){fps=Math.round(ffr/facc);ffr=0;facc=0;fpsEl.textContent=fps+' fps · '+running+' حركة'}
 /* 🆕 إعادة الالتقاط أثناء الفيزياء الحيّة فقط (العقد تتحرّك) — لا في كلّ إطارٍ عبثاً */
 if(running&&!drag&&mcx>=0)hov=pick(mcx,mcy);
 renderTip();
 /* 🆕 الأساس dpr: المسح والكاميرا والتسميات تُرسم فوقه فتخرج حادّةً وتُمسح كاملةً (لا بقايا) */
 cx.setTransform(dpr,0,0,dpr,0,0);cx.fillStyle='#04050a';cx.fillRect(0,0,W,H);
 const vg=cx.createRadialGradient(W/2,H/2,Math.min(W,H)*.3,W/2,H/2,Math.max(W,H)*.78);
 vg.addColorStop(0,'rgba(0,0,0,0)');vg.addColorStop(1,'rgba(0,0,0,.5)');cx.fillStyle=vg;cx.fillRect(0,0,W,H);
 cx.save();cx.translate(W/2+ox,H/2+oy);cx.scale(zoom,zoom);cx.globalCompositeOperation='lighter';
 /* الروابط: مسارٌ واحد خافت (سريع) — الغبار أخفت */
 cx.lineWidth=0.6/zoom;cx.globalAlpha=1;cx.strokeStyle='rgba(120,150,200,0.10)';cx.beginPath();
 for(const [a,b] of E){if(!act[lay[a]]||!act[lay[b]])continue;if(lay[a]===3||lay[b]===3)continue;
  cx.moveTo(px[a],py[a]);cx.lineTo(px[b],py[b])}cx.stroke();
 cx.strokeStyle='rgba(160,90,110,0.05)';cx.beginPath();
 for(const [a,b] of E){if(!act[lay[a]]||!act[lay[b]])continue;if(lay[a]!==3&&lay[b]!==3)continue;
  cx.moveTo(px[a],py[a]);cx.lineTo(px[b],py[b])}cx.stroke();
 /* الغبار (صفقات): نقاط صغيرة مجمّعة */
 if(act[3]){for(const i of pinned){cx.globalAlpha=.5;cx.fillStyle=N[i].color;
   cx.fillRect(px[i]-rad[i],py[i]-rad[i],rad[i]*2,rad[i]*2)}}
 /* العُقد البنيويّة: توهّجٌ للكبيرة، قرصٌ للصغيرة، + تنفّس الثقة الحيّة */
 const pul=1+0.12*Math.sin(now*0.0022);
 for(const i of dyn){if(!act[lay[i]])continue;const n=N[i];let r=rad[i];
  const od=(nbr[i].length===0&&!showOrphans)?0.18:1;   /* 🆕 عتمة العقد اليتيمة (بلا رابط) افتراضيّاً */
  let a=1;if(confSeen&&conf[i]!==null){confAnim[i]+=(conf[i]-confAnim[i])*Math.min(1,dt*3.2);
   const cf=confAnim[i];r=rad[i]*(0.9+1.9*cf)*pul;a=0.5+0.5*cf}
  if(r>=2.5){cx.globalAlpha=.30*a*od;let g=cx.createRadialGradient(px[i],py[i],0,px[i],py[i],r*4.2);
   g.addColorStop(0,n.color);g.addColorStop(1,'rgba(0,0,0,0)');cx.fillStyle=g;
   cx.beginPath();cx.arc(px[i],py[i],r*4.2,0,7);cx.fill();
   cx.globalAlpha=.95*od;g=cx.createRadialGradient(px[i],py[i],0,px[i],py[i],r);
   g.addColorStop(0,'#fff');g.addColorStop(.45,n.color);g.addColorStop(1,'rgba(0,0,0,0)');cx.fillStyle=g;
   cx.beginPath();cx.arc(px[i],py[i],r,0,7);cx.fill();
   if(conf[i]!==null&&confAnim[i]>0.6){cx.globalAlpha=(confAnim[i]-0.6)*1.6*(0.6+0.4*Math.sin(now*0.006+i));
    cx.fillStyle='#fff';cx.beginPath();cx.arc(px[i],py[i],rad[i]*0.7,0,7);cx.fill()}}
  else{cx.globalAlpha=.6*od;cx.fillStyle=n.color;cx.beginPath();cx.arc(px[i],py[i],r,0,7);cx.fill()}}
 /* نبضات المجلس */
 ambientBus(dt);amb+=dt*4;while(amb>=1){amb--;if(SYK.length)fire(SYK[(Math.random()*SYK.length)|0],0,1)}
 for(let i=pulses.length-1;i>=0;i--){const p=pulses[i],t=(now-p.t)/p.d;
  if(t>=1){pulses.splice(i,1);continue}if(t<0)continue;
  const e=t*t*(3-2*t),ax=px[p.a],ay=py[p.a],bx=px[p.b],by=py[p.b];
  const x=ax+(bx-ax)*e,y=ay+(by-ay)*e;cx.globalAlpha=.9*Math.sin(Math.PI*t);cx.fillStyle=p.c;
  cx.beginPath();cx.arc(x,y,2.4/zoom,0,7);cx.fill();const e2=Math.max(0,e-.06);
  cx.globalAlpha*=.4;cx.beginPath();cx.arc(ax+(bx-ax)*e2,ay+(by-ay)*e2,1.5/zoom,0,7);cx.fill()}
 /* نبضات الناقل: قوسٌ مضيء frm→to على المواضع الحيّة */
 for(let i=bpulses.length-1;i>=0;i--){const p=bpulses[i];if(now<p.t)continue;const t=(now-p.t)/p.d;
  if(t>=1){bpulses.splice(i,1);continue}
  const ax=px[p.a],ay=py[p.a],bx=px[p.b],by=py[p.b];
  const mx=(ax+bx)/2,my=(ay+by)/2,dx=bx-ax,dy=by-ay,bnd=(p.bend===undefined?0.16:p.bend);
  const cxp=mx-dy*bnd,cyp=my+dx*bnd;
  cx.strokeStyle=p.c;cx.lineWidth=(p.dim?0.6:1.2)/zoom;cx.globalAlpha=(p.dim?.14:.30)*Math.sin(Math.PI*t);
  cx.beginPath();cx.moveTo(ax,ay);cx.quadraticCurveTo(cxp,cyp,bx,by);cx.stroke();
  const u=1-t,qx=u*u*ax+2*u*t*cxp+t*t*bx,qy=u*u*ay+2*u*t*cyp+t*t*by;
  cx.globalAlpha=(p.dim?.5:.95)*Math.sin(Math.PI*t);const rr=(p.dim?3.4:6)/zoom;
  const g=cx.createRadialGradient(qx,qy,0,qx,qy,rr);
  g.addColorStop(0,'#fff');g.addColorStop(.4,p.c);g.addColorStop(1,'rgba(0,0,0,0)');
  cx.fillStyle=g;cx.beginPath();cx.arc(qx,qy,rr,0,7);cx.fill();p._sx=qx;p._sy=qy}
 /* إبراز جيران العقدة الملموسة */
 if(hov>=0){const nb=nbr[hov],mx=Math.min(nb.length,350);cx.lineWidth=1.4/zoom;
  cx.strokeStyle='#49d8ff';cx.globalAlpha=.55;cx.beginPath();      /* 🆕 روابط مباشرة سماويّة (مسارٌ واحد سريع) */
  for(let q=0;q<mx;q++){const b=nb[q];if(!act[lay[b]])continue;cx.moveTo(px[hov],py[hov]);cx.lineTo(px[b],py[b])}
  cx.stroke();cx.globalAlpha=.9;                                   /* عقد الجيران: نقاطٌ بلونها الأصليّ */
  for(let q=0;q<mx;q++){const b=nb[q];if(!act[lay[b]])continue;cx.fillStyle=N[b].color;
   cx.beginPath();cx.arc(px[b],py[b],Math.max(rad[b],2.4/zoom),0,7);cx.fill()}
  cx.globalAlpha=1;const rr=Math.max(rad[hov]*3,10/zoom);
  const g=cx.createRadialGradient(px[hov],py[hov],0,px[hov],py[hov],rr);
  g.addColorStop(0,'#fff');g.addColorStop(.4,N[hov].color);g.addColorStop(1,'rgba(0,0,0,0)');
  cx.fillStyle=g;cx.beginPath();cx.arc(px[hov],py[hov],rr,0,7);cx.fill()}
 cx.restore();
 /* التسميات (فضاء الشاشة) */
 cx.globalCompositeOperation='source-over';cx.font='11px Consolas,Tahoma,monospace';
 /* 🆕 إزالة تكدّس التسميات: أولويّة (الملموسة+جيرانها ← عقد lb ← الأعلى اتصالاً عند التقريب)،
    ثمّ فحص تصادم المستطيلات (لا تُرسم تسميةٌ تتراكب مع أخرى رُسمت قبلها). */
 const cand=[];
 if(hov>=0){cand.push(hov);const nb=nbr[hov];for(let q=0;q<Math.min(nb.length,24);q++)cand.push(nb[q])}
 for(let i=0;i<NN;i++){if(N[i].lb&&i!==hov)cand.push(i)}
 if(zoom>0.9){for(let i=0;i<NN;i++){if(!N[i].lb&&i!==hov&&nbr[i].length>=6)cand.push(i)}}
 const drawn=[],seenL=new Set();
 for(const i of cand){
  if(seenL.has(i)||!act[lay[i]])continue;seenL.add(i);
  if(nbr[i].length===0&&!showOrphans&&i!==hov)continue;
  const sx=px[i]*zoom+W/2+ox,sy=py[i]*zoom+H/2+oy;
  if(sx<-120||sx>W+120||sy<-20||sy>H+20)continue;
  const txt=N[i].id.length>42?N[i].id.slice(0,40)+'…':N[i].id;
  const x0=sx+8,y0=sy-8,w=txt.length*6.6+6;                          /* مستطيلٌ تقريبيّ للنصّ */
  let hit=false;for(const d of drawn){if(x0<d[0]+d[2]&&x0+w>d[0]&&y0<d[1]+15&&y0+15>d[1]){hit=true;break}}
  if(hit&&i!==hov)continue;                                          /* تصادم ⇒ تخطَّ (الملموسة تُرسم دائماً) */
  drawn.push([x0,y0,w]);
  cx.globalAlpha=i===hov?1:(hov>=0?.3:.62);cx.fillStyle=i===hov?'#ffe9a8':'#b9c8de';
  cx.fillText(txt,sx+8,sy+3)}
 for(const p of bpulses){if(p._sx===undefined||!p.label)continue;const t=(now-p.t)/p.d;
  const sx=p._sx*zoom+W/2+ox,sy=p._sy*zoom+H/2+oy;if(sx<-60||sx>W+60||sy<-20||sy>H+20)continue;
  cx.globalAlpha=.9*Math.sin(Math.PI*t);cx.fillStyle=p.c;cx.fillText(p.label,sx+7,sy-5)}
 cx.globalAlpha=1;scheduleFrame()}
scheduleFrame();
/* ===== الفأرة: التقاط على المواضع الحيّة (كنسٌ مباشر) ===== */
function pick(mx,my){const x=(mx-W/2-ox)/zoom,y=(my-H/2-oy)/zoom;
 let best=-1,bDeg=-1,bd=1e18;for(let i=0;i<NN;i++){if(!act[lay[i]])continue;
  if(nbr[i].length===0&&!showOrphans)continue;                 /* 🆕 اليتيمة المعتّمة لا تُلتقط */
  const dx=px[i]-x,dy=py[i]-y,d2=dx*dx+dy*dy;const rr=Math.max(rad[i]+3,9/zoom);
  if(d2<rr*rr){const deg=nbr[i].length;                        /* 🆕 عند التراكب: الأعلى اتصالاً ثمّ الأقرب */
   if(deg>bDeg||(deg===bDeg&&d2<bd)){bDeg=deg;bd=d2;best=i}}}return best}
let drag=false,lx=0,ly=0,mcx=-1,mcy=-1;                        /* 🆕 mcx/mcy: آخر موضع ماوس (لإعادة الالتقاط أثناء الحركة) */
cv.onmousedown=e=>{drag=true;lx=e.clientX;ly=e.clientY};
onmouseup=()=>drag=false;
onmousemove=e=>{mcx=e.clientX;mcy=e.clientY;if(drag){ox+=e.clientX-lx;oy+=e.clientY-ly;lx=e.clientX;ly=e.clientY;return}
 hov=pick(mcx,mcy);cv.style.cursor=hov>=0?'pointer':'default'};
cv.onwheel=e=>{e.preventDefault();const f=e.deltaY<0?1.12:.89;zoom=Math.min(6,Math.max(.04,zoom*f))};
</script></body></html>"""


def _read(path: Path) -> str:
    """قراءة دفاعيّة (utf-8-sig يبتلع BOM؛ errors=replace لا يرمي أبداً)."""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def _pol(cx, cy, ang, rad):
    return cx + rad * math.cos(ang), cy + rad * math.sin(ang)


def _phyl(cx, cy, i, k):
    """لولب phyllotaxis: العقدة i على زاوية i·GA ونصف قطر k·√i."""
    a = i * GA
    r = k * math.sqrt(i)
    return cx + r * math.cos(a), cy + r * math.sin(a)


class _G:
    """مجمّع العقد/الروابط — كلّ عقدة {id,x,y,color,r,layer,lb, p?}."""

    def __init__(self):
        self.nodes, self.edges = [], []

    def add(self, nid, x, y, color, r, layer, lb=0, p=None):
        nd = {"id": str(nid), "x": round(x, 1), "y": round(y, 1),
              "color": color, "r": round(r, 2), "layer": layer, "lb": lb}
        if p is not None:
            nd["p"] = p
        self.nodes.append(nd)
        return len(self.nodes) - 1


def _layer_vault(g, C):
    """0 معرفة: مسح خزنة plutobrain (ملاحظات + أشباح بسقف 80). يرجع {مجلد: [عقد]}."""
    files = []
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT)
        if any(s.startswith(".") for s in rel.parts):
            continue
        files.append((str(rel).lower(), p, rel))
    files.sort()
    idx, texts, fidx, members, cnt = {}, [], {}, {}, {}
    for _, p, rel in files:
        stem = p.stem
        if stem in idx:
            continue
        gname = rel.parts[0] if len(rel.parts) > 1 else "_root"
        fi = fidx.setdefault(gname, len(fidx))
        i = cnt.get(gname, 0)
        cnt[gname] = i + 1
        ax, ay = _pol(C[0], C[1], fi * GA, 70 + (fi * 61) % 170)
        x, y = _phyl(ax, ay, i, 10.0)
        if len(rel.parts) == 1 and rel.name == ROOT_NOTE:
            x, y, col, r, lb = C[0], C[1], "#f5c518", 4.0, 1
        else:
            col = "hsl(%d,80%%,%d%%)" % (38 + (fi * 4) % 23, 50 + (fi * 7) % 18)
            r, lb = 2.3, 0
        j = g.add(stem, x, y, col, r, 0, lb)
        idx[stem] = j
        members.setdefault(gname, []).append(j)
        texts.append((j, _read(p)))
    eset, ghosts = set(), {}
    for j, raw in texts:
        txt = _CODE_RE.sub(" ", _FENCE_RE.sub(" ", raw))
        for m in _LINK_RE.finditer(txt):
            t = m.group(1).split("|")[0].split("#")[0].strip()
            if not t:
                continue
            k = idx.get(t)
            if k is not None:
                key = (min(j, k), max(j, k))
                if k != j and key not in eset:
                    eset.add(key)
                    g.edges.append([j, k])
            else:
                ghosts.setdefault(t, []).append(j)
    ranked = sorted(ghosts.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:GHOST_CAP]
    for go, (t, srcs) in enumerate(ranked):
        src = g.nodes[srcs[0]]
        x, y = _phyl(src["x"], src["y"], 3 + go % 15, 6.0)
        gi = g.add(t, x, y, "#6f6a55", 1.5, 0)
        for s in dict.fromkeys(srcs):
            g.edges.append([s, gi])
    return members


def _layer_fleet(g, C):
    """1 أسطول: مفاتيح ENGINES من نصّ watchdog_guard.py (regex) → محرّكات مربوطة بمحور
    watchdog + عقد الماجيك من السبورة."""
    src = _read(MT5 / "watchdog_guard.py")
    m = re.search(r"^ENGINES\s*=\s*\{(.*?)^\}", src, re.S | re.M)
    keys = []
    for ln in (m.group(1) if m else "").splitlines():
        ln = ln.strip()
        if ln.startswith("#"):
            continue
        km = re.match(r'"([^"]+)"\s*:\s*\(', ln)
        if km:
            keys.append(km.group(1))
    eng = {}
    if keys:
        hub = g.add("watchdog", C[0], C[1], "#a8ffc9", 5.0, 1, 1)
        for i, k in enumerate(keys):
            x, y = _phyl(C[0], C[1], i + 4, 15.0)
            eng[k] = g.add(k, x, y, "hsl(142,66%,55%)", 2.2, 1)
            g.edges.append([eng[k], hub])
    mag = {}
    try:
        rows = json.loads(_read(RN / "desk_scoreboard.json")).get("magics") or []
        for i, row in enumerate(rows):
            x, y = _pol(C[0], C[1], i * 2 * math.pi / max(len(rows), 1), 195)
            name = str(row.get("name") or row.get("magic"))
            j = g.add(name, x, y, "hsl(96,72%,58%)", 3.0, 1, 1)
            try:
                mag[int(row.get("magic"))] = j
            except Exception:
                pass
        for mg, ename in MAGIC_ENGINE.items():
            tgt = eng.get(ename) or eng.get(ename + ".py") or eng.get(ename.replace(".py", ""))
            if mg in mag and tgt is not None:
                g.edges.append([mag[mg], tgt])
    except Exception:
        pass
    return eng, mag, C


def _layer_council(g, C):
    """2 المجلس العصبيّ: ~96 وكيلاً × رموز agent_council.json — كلّ وكيل→كلّ رمز."""
    agents = []
    for p in sorted((MT5 / "agents").glob("agent_*.py")):
        m = re.search(r"^AGENTS\s*=\s*\[(.*?)^\]", _read(p), re.S | re.M)
        if m:
            agents += re.findall(r'\(\s*["\']([A-Za-z0-9_]+)["\']', m.group(1))
    syms = []
    try:
        syms = list((json.loads(_read(RN / "agent_council.json")).get("symbols") or {}).keys())
    except Exception:
        pass
    aidx = []
    for i, a in enumerate(agents):
        x, y = _phyl(C[0], C[1], i, 11.5)
        aidx.append(g.add(a, x, y, "hsl(268,72%,66%)", 1.6, 2))
    sidx = {}
    for i, s in enumerate(syms):
        x, y = _pol(C[0], C[1], i * GA, 250 + (i * 73) % 150)
        sidx[s] = g.add(s, x, y, "hsl(188,86%,62%)", 4.2, 2, 1)
    for ai in aidx:
        for si in sidx.values():
            g.edges.append([ai, si])
    return aidx, sidx


def _layer_trades(g, C, sidx, mag, FC):
    """3 صفقات: آخر 4000 صفّ من friday.db (قراءة فقط) — كلّ صفقة عقدةٌ مثبّتة (p) على
    عقدة رمزها ⇒ تسبح مع الرمز بلا كلفة فيزياء، ومربوطة برمزها وبماجيكها الحقيقيّ."""
    con = sqlite3.connect("file:%s?mode=ro" % DB.as_posix(), uri=True)
    try:
        rows = con.execute(
            "SELECT magic,symbol,ts,side,pnl FROM trades ORDER BY rowid DESC LIMIT %d" % TRADE_CAP).fetchall()
    finally:
        con.close()
    created, counter = {}, {}
    for mg, sym, _ts, _side, pnl in rows:
        sym = str(sym or "?")
        si = sidx.get(sym)
        if si is None:
            si = created.get(sym)
            if si is None:
                c = len(created)
                x, y = _pol(C[0], C[1], c * GA, 120 + (c * 67) % 160)
                si = created[sym] = g.add(sym, x, y, "hsl(200,42%,56%)", 3.5, 3, 1)
        base = g.nodes[si]
        i = counter.get(sym, 0)
        counter[sym] = i + 1
        x, y = _phyl(base["x"], base["y"], i + 6, 4.0)
        pnl = float(pnl or 0)
        col = "#2fbf71" if pnl > 0 else "#e0455a"
        j = g.add("%s %+.2f$" % (sym, pnl), x, y, col, 0.8 + min(0.7, abs(pnl) * 0.15), 3, 0, p=si)
        g.edges.append([j, si])
        try:
            mgi = int(mg)
        except Exception:
            mgi = None
        if mgi is not None and mgi != 0:
            mgt = mag.get(mgi)
            if mgt is None:
                c = len(mag)
                mx, my = _pol(FC[0], FC[1], c * GA, 210 + (c * 59) % 90)
                mgt = mag[mgi] = g.add("magic %d" % mgi, mx, my, "hsl(112,64%,52%)", 2.6, 1, 1)
            g.edges.append([j, mgt])


def _layer_code(g, C):
    """4 كود: ملفات *.py الجذرية + روابط ^import/^from بين وحدات الجذر."""
    files = sorted(MT5.glob("*.py"))
    stems = {p.stem for p in files}
    mods = {}
    for i, p in enumerate(files):
        x, y = _phyl(C[0], C[1], i, 13.0)
        mods[p.stem] = g.add(p.name, x, y, "#7a9cc4", 1.9, 4)
    eset = set()
    for p in files:
        a = mods[p.stem]
        for m in _IMP_RE.finditer(_read(p)):
            t = m.group(1)
            if t in stems and t != p.stem:
                key = (min(a, mods[t]), max(a, mods[t]))
                if key not in eset:
                    eset.add(key)
                    g.edges.append(list(key))
    return list(mods.values())


def _layer_bridges(g, mag):
    """🌉 جسور بين الطبقات: كود↔محرّكه، ملاحظة↔ماجيكها، ملاحظة↔ملفّ الكود الذي تسمّيه."""
    by, code_by_stem, vault_idx = {}, {}, []
    for i, n in enumerate(g.nodes):
        by[(n["id"], n["layer"])] = i
        if n["layer"] == 4:
            code_by_stem[n["id"][:-3] if n["id"].endswith(".py") else n["id"]] = i
        elif n["layer"] == 0:
            vault_idx.append((i, n["id"]))
    seen = set()

    def link(a, b):
        if a == b:
            return
        k = (min(a, b), max(a, b))
        if k not in seen:
            seen.add(k); g.edges.append([a, b])
    for (nid, layer), idx in list(by.items()):
        if layer == 4:
            f = by.get((nid, 1))
            if f is not None:
                link(idx, f)
    import re as _re
    for vi, stem in vault_idx:
        txt = ""
        for cand in VAULT.rglob(stem + ".md"):
            txt = _read(cand); break
        if not txt:
            continue
        for num in set(_re.findall(r"\b\d{3,8}\b", txt)):
            try:
                mi = mag.get(int(num))
            except Exception:
                mi = None
            if mi is not None:
                link(vi, mi)
        for cs, ci in code_by_stem.items():
            if len(cs) >= 5 and (cs + ".py") in txt:
                link(vi, ci)


_MAGIC_NAME = {"20260701": "الحارس", "20260706": "R Core", "20260707": "قنّاص المجلس",
               "20260709": "حارس العملات", "20260703": "محاكي راضي", "20260631": "يوتيوب",
               "20260600": "المخّ الواحد"}


def _confidence_anchors(g, mag, lbl):
    """🔭 {مفتاح-ثقة: فهرس-عقدة} — كلّ ترسيخ يشير لعقدة موجودة فعلاً (لا تنفّس كاذب)."""
    out = {}
    for mg_str, name in _MAGIC_NAME.items():
        node = None
        try:
            node = mag.get(int(mg_str))
        except Exception:
            node = None
        if node is None and name in lbl:
            node = lbl[name]
        if node is None:
            continue
        out[mg_str] = node
        out.setdefault(name, node)
    for name, node in lbl.items():
        out.setdefault(name, node)
    return out


def _bus_anchors(g):
    """{تسمية-عنقود: فهرس-عقدة} — تُربط كلّ تسمية بأقرب عقدة حقيقيّة (بلا اختلاق)."""
    by_id, code_by_stem, first_of_layer, watchdog_i = {}, {}, {}, None
    for i, n in enumerate(g.nodes):
        lid = str(n["id"]).lower()
        by_id.setdefault(lid, i)
        first_of_layer.setdefault(n["layer"], i)
        if n["layer"] == 4:
            stem = n["id"][:-3] if str(n["id"]).endswith(".py") else n["id"]
            code_by_stem.setdefault(stem, i)
        if n["layer"] == 1 and lid == "watchdog":
            watchdog_i = i

    def code(stem):
        return code_by_stem.get(stem)

    def any_of(*cands):
        for c in cands:
            if c is not None:
                return c
        return None

    raw = {
        "الحارس": any_of(watchdog_i, code("watchdog_guard"), code("watchdog")),
        "R Core": any_of(code("brain_trader"), code("r_executor"), watchdog_i, first_of_layer.get(1)),
        "قنّاص المجلس": any_of(code("council_sniper"), first_of_layer.get(2)),
        "المجلس(96)": any_of(code("agent_council"), first_of_layer.get(2)),
        "العقل الجماعيّ": any_of(code("unified_brain"), code("fleet_mind"), first_of_layer.get(1)),
        "السبورة": any_of(code("desk_scoreboard"), watchdog_i, first_of_layer.get(1)),
        "المخّ الواحد": any_of(code("unified_brain"), watchdog_i),
    }
    return {k: v for k, v in raw.items() if v is not None}


def build_graph():
    """يبني الرسم من مسح حيّ للطبقات الخمس ويرجع payload dict (nodes/edges/layers/…).
    مصدرٌ واحد صادق لكلٍّ من صفحة HTML ونقطة البيانات /rt/brain/data. فشل-ناعم لكلّ طبقة."""
    g = _G()
    members, code_nodes, aidx, sidx, mag = {}, [], [], {}, {}
    fc = _LC[1]
    try:
        if VAULT.is_dir():
            members = _layer_vault(g, _LC[0])
    except Exception:
        pass
    try:
        _eng, mag, fc = _layer_fleet(g, _LC[1])
    except Exception:
        mag = {}
    try:
        aidx, sidx = _layer_council(g, _LC[2])
    except Exception:
        aidx, sidx = [], {}
    try:
        _layer_trades(g, _LC[3], sidx, mag, fc)
    except Exception:
        pass
    try:
        code_nodes = _layer_code(g, _LC[4])
    except Exception:
        code_nodes = []
    try:
        _layer_bridges(g, mag)
    except Exception:
        pass
    if not g.nodes:
        return None
    deg = [0] * len(g.nodes)
    for a, b in g.edges:
        deg[a] += 1
        deg[b] += 1
    for ids in members.values():
        if ids:
            g.nodes[max(ids, key=lambda i: deg[i])]["lb"] = 1
    for i in sorted(code_nodes, key=lambda i: -deg[i])[:5]:
        g.nodes[i]["lb"] = 1
    counts = [0] * 5
    for n in g.nodes:
        counts[n["layer"]] += 1
    ly = [{"n": nm, "c": cl, "k": counts[i]} for i, (nm, cl) in enumerate(LAYERS)]
    wr = int(40 + max(max(abs(n["x"]), abs(n["y"])) for n in g.nodes))
    try:
        lbl = _bus_anchors(g)
    except Exception:
        lbl = {}
    try:
        conf = _confidence_anchors(g, mag, lbl)
    except Exception:
        conf = {}
    return {"nodes": g.nodes, "edges": g.edges, "layers": ly, "sym": sidx,
            "ag": aidx, "lbl": lbl, "conf": conf, "wr": wr,
            "n_nodes": len(g.nodes), "n_edges": len(g.edges)}


def render_html() -> str:
    """يبني صفحة المخّ الحيّ. فشل-ناعم: أيّ خلل ⇒ صفحة خطأ عربية (لا يرمي استثناءً أبداً)."""
    try:
        p = build_graph()
        if not p:
            return _ERR_PAGE
        esc = lambda s: s.replace("</", "<\\/")
        j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
        return (_PAGE
                .replace("__NN__", "{:,}".format(p["n_nodes"]))
                .replace("__NE__", "{:,}".format(p["n_edges"]))
                .replace("__NODES__", esc(j(p["nodes"])))
                .replace("__EDGES__", j(p["edges"]))
                .replace("__LAYERS__", esc(j(p["layers"])))
                .replace("__SYM__", esc(j(p["sym"])))
                .replace("__AG__", j(p["ag"]))
                .replace("__LBL__", esc(j(p["lbl"])))
                .replace("__CONF__", esc(j(p["conf"])))
                .replace("__WR__", str(p["wr"])))
    except Exception:
        return _ERR_PAGE


if __name__ == "__main__":
    import time
    t = time.time()
    p = build_graph()
    dt = (time.time() - t) * 1000
    if not p:
        print("build FAILED (no nodes)")
    else:
        html = render_html()
        # فحص سلامة بنيويّ: كلّ رابط يشير لعقدتين صحيحتين؛ كلّ مرساة/غبار صحيح
        nn = p["n_nodes"]
        bad_e = sum(1 for a, b in p["edges"] if not (0 <= a < nn and 0 <= b < nn))
        pins = [i for i, n in enumerate(p["nodes"]) if "p" in n]
        bad_p = sum(1 for i in pins if not (0 <= p["nodes"][i]["p"] < nn))
        bad_anchor = sum(1 for v in list(p["conf"].values()) + list(p["lbl"].values())
                         if not (0 <= v < nn))
        print("build=%.0fms nodes=%d edges=%d pinned=%d html=%dKB" %
              (dt, nn, p["n_edges"], len(pins), len(html) // 1024))
        print("integrity: bad_edges=%d bad_pins=%d bad_anchors=%d unreplaced=%s" %
              (bad_e, bad_p, bad_anchor, any(t in html for t in ("__NODES__", "__EDGES__", "__WR__"))))
