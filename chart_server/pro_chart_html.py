# -*- coding: utf-8 -*-
"""chart_server/pro_chart_html.py — واجهة «قمرة الشارتات الاحترافيّة» (النصف البصريّ لـ pro_chart.py).

صفحة HTML واحدة (عربي RTL · زجاج داكن · ذهبي) تجلب /pro/data?sym=SYM وترسم:
- يسار: Index Chart (سلّة مُعاد تأسيسها على 100) + أشرطة الارتباط الحيّة.
- يمين: ثلاث لوحات شموع D1/H4/H1 مع EMA50/200 وPOC/HVN/VWAP وطبقات SMC كاملة
  (OB/FVG/IFVG/برك السيولة $$$/⚡ اصطياد/BOS/CHoCH) + مستويات الفترات.
- تفاعليّ: Crosshair + Tooltip لكل شمعة، نقرة على اللوحة = تكبير ملء الشاشة،
  قائمة رموز (15 رمزاً)، تحديث ذاتيّ كل 3 ثوانٍ في المكان (بلا وميض).
- MAX: شريط أخبار بعدّادات ثانية + خطوط أحداث على H1/M4 (امتداد 12% للمستقبل)
  + علامات صفقات ▲▼✕ + تظليل جلسات + بثّ موحّد بصوت 🔊 + Sparkline حقوق الملكيّة
  + مسطرة قياس (Shift+سحب) + وضع TV 🖥️ (ESC للخروج).

JS/SVG خالص — بلا أيّ مكتبة خارجيّة (يعمل دون إنترنت).
⚖️ الصدق: SMC/POC سياقٌ بصريّ فقط (~50% OOS كتنبّؤ) — للعين البشريّة لا للإشارة الآليّة."""

PRO_HTML = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>قمرة الشارتات الاحترافيّة</title>
<style>
:root{--bg:#0b0e13;--panel:rgba(23,27,34,.72);--line:#232833;--txt:#e6e9ef;--dim:#9aa3b2;
--gold:#f5c518;--up:#26a67a;--dn:#e05a5a;--cyan:#4fd0e0;--violet:#b57ae0;--orange:#f0a030;--blue:#4f8fe0}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#1a2030 0%,var(--bg) 55%);
color:var(--txt);font-family:'Segoe UI',Tahoma,sans-serif;min-height:100vh}
header{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
padding:10px 16px;border-bottom:1px solid var(--line);background:rgba(11,14,19,.82);backdrop-filter:blur(10px)}
h1{font-size:17px;margin:0;color:var(--gold);text-shadow:0 0 18px rgba(245,197,24,.25)}
.pill{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:4px 12px;
font-size:12px;color:var(--dim);backdrop-filter:blur(8px)}
.pill b{color:var(--txt)}
#dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-inline-start:5px;vertical-align:-1px}
select{background:#12161d;color:var(--gold);border:1px solid var(--line);border-radius:9px;
padding:5px 10px;font-size:13px;font-family:inherit;cursor:pointer}
.wrap{display:grid;grid-template-columns:2fr 3fr;gap:12px;padding:12px}
@media(max-width:1000px){.wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 12px;
backdrop-filter:blur(10px);box-shadow:0 8px 26px rgba(0,0,0,.35)}
.card h2{font-size:13px;margin:0 0 6px;color:var(--dim);font-weight:600;display:flex;justify-content:space-between;align-items:center}
.card h2 .zoom{cursor:pointer;color:var(--gold);font-size:12px;opacity:.75}
.card h2 .zoom:hover{opacity:1}
.tf-card{margin-bottom:12px;cursor:zoom-in;transition:border-color .2s}
.tf-card:hover{border-color:rgba(245,197,24,.45)}
svg{display:block;width:100%;direction:ltr}
.legend{display:flex;flex-wrap:wrap;gap:9px;margin-top:5px;font-size:11.5px}
.legend span{display:inline-flex;align-items:center;gap:4px;cursor:pointer;opacity:.9}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block}
.off{opacity:.3;text-decoration:line-through}
.corr-row{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12px}
.corr-name{width:88px}
.corr-bar{flex:1;height:13px;background:#0c0f14;border-radius:4px;position:relative;overflow:hidden}
.corr-fill{position:absolute;top:0;height:100%;border-radius:3px}
.corr-val{width:42px;text-align:left;font-variant-numeric:tabular-nums}
.muted{color:var(--dim);font-size:11.5px}
/* ─── 🧮 مكتب الحسابات ─── */
.dz-gauge{direction:ltr;position:relative;height:15px;border-radius:8px;margin:9px 2px 4px;
background:linear-gradient(90deg,rgba(224,90,90,.8),rgba(58,63,75,.55) 50%,rgba(38,166,122,.8))}
.dz-needle{position:absolute;top:-4px;width:3px;height:23px;background:var(--gold);border-radius:2px;
box-shadow:0 0 8px rgba(245,197,24,.85);transform:translateX(-50%);transition:left .6s}
.dz-scale{direction:ltr;display:flex;justify-content:space-between;font-size:9.5px;color:#7a8090;padding:0 2px}
.dz-verdict{text-align:center;font-size:14px;font-weight:700;margin:3px 0 6px}
.dz-frow{display:flex;align-items:center;gap:7px;margin:3px 0;font-size:11.5px}
.dz-fname{width:126px}
.dz-fw{width:34px;color:var(--dim);font-variant-numeric:tabular-nums}
.dz-fbar{flex:1;height:11px;background:#0c0f14;border-radius:4px;position:relative;overflow:hidden;direction:ltr}
.dz-ffill{position:absolute;top:0;height:100%;border-radius:3px}
.dz-fc{width:44px;text-align:left;font-variant-numeric:tabular-nums;direction:ltr}
.dz-chips{display:flex;flex-wrap:wrap;gap:6px;margin:7px 0 2px}
.dz-chip{background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:14px;padding:2px 9px;font-size:11px}
.dz-rank{display:flex;flex-wrap:wrap;gap:6px;margin-top:5px}
.rank-chip{cursor:pointer;background:rgba(245,197,24,.07);border:1px solid rgba(245,197,24,.3);border-radius:14px;
padding:2px 9px;font-size:11px;transition:background .2s}
.rank-chip:hover{background:rgba(245,197,24,.22)}
.dz-pnl{width:100%;border-collapse:collapse;font-size:11px;margin-top:5px}
.dz-pnl td,.dz-pnl th{padding:2.5px 4px;border-bottom:1px solid rgba(255,255,255,.05);text-align:center}
.dz-pnl th{color:var(--dim);font-weight:600}
.dz-pnl td:first-child,.dz-pnl th:first-child{text-align:right}
.dz-sec{font-size:11px;color:var(--dim);margin:8px 0 2px;font-weight:600}
/* ─── 🤖 محلّل Fable ─── */
#anabtn,#anasend{background:rgba(245,197,24,.12);border:1px solid rgba(245,197,24,.4);color:var(--gold);
border-radius:9px;padding:4px 10px;font-size:11.5px;font-family:inherit;cursor:pointer;white-space:nowrap}
#anabtn:disabled,#anasend:disabled{opacity:.45;cursor:wait}
.ana-news{display:flex;flex-wrap:wrap;gap:6px;margin:7px 0 4px}
.ana-chip{border-radius:14px;padding:2px 9px;font-size:11px;border:1px solid}
.ana-hi{background:rgba(224,90,90,.12);border-color:rgba(224,90,90,.5);color:#f0908a}
.ana-md{background:rgba(240,160,48,.1);border-color:rgba(240,160,48,.45);color:var(--orange)}
.ana-body{max-height:340px;overflow-y:auto;font-size:12.5px;line-height:2;padding-inline-end:4px}
.ana-body .ana-sec{margin:8px 0 2px;font-weight:700;color:var(--gold)}
.ana-ask{display:flex;gap:6px;margin-top:9px}
.ana-ask input{flex:1;min-width:0;background:#12161d;border:1px solid var(--line);border-radius:9px;
color:var(--txt);padding:5px 10px;font-size:12px;font-family:inherit}
.ana-bub{border-radius:10px;padding:5px 10px;margin-top:6px;font-size:12px;line-height:1.9}
.ana-q{border:1px solid rgba(245,197,24,.5);background:rgba(245,197,24,.06)}
.ana-a{border:1px solid var(--line);background:rgba(255,255,255,.04);backdrop-filter:blur(6px)}
.ana-spin{display:inline-block;animation:anasp 1s linear infinite}
@keyframes anasp{to{transform:rotate(360deg)}}
/* ─── 🕐 شريط الأخبار العلويّ (عدّادات حيّة بالثانية) ─── */
#newsbar{display:none;gap:8px;overflow-x:auto;padding:6px 14px;border-bottom:1px solid var(--line);
background:rgba(11,14,19,.6);white-space:nowrap;backdrop-filter:blur(8px)}
.nchip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:16px;
padding:3px 10px;font-size:11.5px;cursor:pointer;background:var(--panel);flex:none}
.nchip b{color:var(--gold);font-variant-numeric:tabular-nums;direction:ltr}
.nchip.soon{border-color:var(--dn);animation:npulse 1.2s infinite}
.nchip.now{animation:nflash .5s infinite}
@keyframes npulse{50%{box-shadow:0 0 12px rgba(224,90,90,.75)}}
@keyframes nflash{50%{background:rgba(224,90,90,.4)}}
/* ─── 📢 البثّ الموحّد + 🔊 ─── */
#sndbtn{background:rgba(245,197,24,.1);border:1px solid rgba(245,197,24,.35);border-radius:9px;
padding:2px 9px;cursor:pointer;font-size:13px;font-family:inherit}
.feed-it{display:flex;gap:7px;align-items:flex-start;border-bottom:1px solid rgba(255,255,255,.05);
padding:4px 0;font-size:11.5px;line-height:1.7}
.feed-it .ft{color:var(--dim);font-size:10px;flex:none;direction:ltr}
.feed-new{animation:fslide .45s ease}
@keyframes fslide{from{transform:translateX(30px);opacity:0}to{transform:none;opacity:1}}
/* ─── 🖥️ وضع TV: إخفاء العمود الأيسر وملء الشاشة بالشارتات ─── */
#tvbtn{cursor:pointer;user-select:none}
body.tv #leftcol,body.tv #newsbar{display:none!important}
body.tv .wrap{grid-template-columns:1fr}
#tip{position:fixed;z-index:60;pointer-events:none;display:none;background:rgba(12,15,20,.94);
border:1px solid var(--gold);border-radius:9px;padding:7px 10px;font-size:11.5px;line-height:1.8;
direction:rtl;box-shadow:0 6px 18px rgba(0,0,0,.5);min-width:130px}
#tip b{color:var(--gold)}
#ovl{position:fixed;inset:0;z-index:50;display:none;background:rgba(8,10,14,.9);backdrop-filter:blur(8px);padding:3vh 3vw}
#ovl .box{background:var(--panel);border:1px solid var(--gold);border-radius:16px;padding:12px;height:94vh;display:flex;flex-direction:column}
#ovl h2{font-size:15px;margin:0 0 8px;color:var(--gold);display:flex;justify-content:space-between}
#ovl .x{cursor:pointer;color:var(--dn);font-size:18px;padding:0 8px}
#ovl .body{flex:1;min-height:0}
footer{padding:10px 16px 18px;text-align:center;color:var(--dim);font-size:11.5px;border-top:1px solid var(--line);margin-top:6px}
#err{display:none;margin:10px 14px;padding:8px 12px;border:1px solid var(--dn);border-radius:9px;color:var(--dn);font-size:12.5px}
</style></head><body>
<header>
  <h1>👑 قمرة الشارتات الاحترافيّة</h1>
  <select id="symsel" title="اختر الرمز"></select>
  <span class="pill">السعر <b id="price">—</b><span id="dot" style="background:#666"></span></span>
  <span class="pill">🕐 <b id="clock">—</b></span>
  <span class="pill" id="smcsum">—</span>
  <span class="pill" id="tvbtn" title="ملء الشاشة بالشارتات — ESC للخروج">🖥️ TV</span>
  <span class="pill" id="planbtn" title="إظهار/إخفاء الخطط الآليّة — تأطيرٌ بصريّ لا توصية" style="cursor:pointer;user-select:none">🎯 خطط آليّة</span>
</header>
<div id="newsbar"></div>
<div id="err"></div>
<div class="wrap">
  <div id="leftcol">
    <div class="card"><h2>Index Chart — السلّة مُعاد تأسيسها على 100 (الذهب بالعريض)</h2>
      <svg id="idxsvg" height="330"></svg><div class="legend" id="idxlegend"></div></div>
    <div class="card" style="margin-top:12px"><h2>الارتباط الحيّ مع الذهب (عوائد H1)</h2><div id="corr"></div>
      <p class="muted">أخضر = يتحرّك معه · أحمر = عكسه · قرب ±1 أقوى.</p></div>
    <div class="card" id="eqcard" style="margin-top:12px;display:none">
      <h2><span>📈 حقوق الملكيّة اليوم</span><span id="eqpnl" style="font-size:13px;font-weight:700"></span></h2>
      <svg id="eqsvg" height="70"></svg></div>
    <div class="card" id="feedcard" style="margin-top:12px;display:none">
      <h2><span>📢 البثّ الحيّ الموحّد</span><button id="sndbtn" title="صوت التنبيهات (نغمة لكلّ جديد + ثلاثيّ عاجل لإنذار الأخبار)">🔇</button></h2>
      <div id="feedlist"></div></div>
    <div class="card" id="unifiedcard" style="margin-top:12px;display:none;border:1px solid var(--gold)">
      <h2><span>🧠 المخ الواحد — <span id="unisym"></span></span><span class="pill" style="font-size:9px;padding:1px 7px">صهر كل العيون</span></h2>
      <div id="unibody"></div></div>
    <div class="card" id="mtfcard" style="margin-top:12px;display:none">
      <h2><span>🦅 لوحة الفريمات — تقلب كوانتي</span><span class="pill" style="font-size:9px;padding:1px 7px">أرقامنا لا دعايتهم</span></h2>
      <div id="mtfbody"></div></div>
    <div class="card" id="deskcard" style="margin-top:12px;display:none">
      <h2><span>🧮 مكتب الحسابات — لحظيّ</span><span class="muted" id="deskts"></span></h2>
      <div id="deskbody"></div></div>
    <div class="card" id="deepcard" style="margin-top:12px;display:none">
      <h2><span>🧠 العقل العميق — <span id="deepsym"></span></span><span class="muted" id="deepts"></span></h2>
      <div id="deepbody"></div></div>
    <div class="card" id="braincard" style="margin-top:12px;display:none">
      <h2><span>🕸️ خريطة العقل الحيّة</span>
        <span style="display:flex;gap:7px;align-items:center">
          <span class="muted" id="braints"></span>
          <a href="/pro/graphmap" target="_blank" class="pill" style="font-size:10px;padding:2px 8px;text-decoration:none;cursor:pointer">↗ افتح كاملاً</a></span></h2>
      <iframe src="/pro/graphmap" style="width:100%;height:360px;border:1px solid var(--line);border-radius:10px;background:#0c0f14" loading="lazy"></iframe>
      <div id="brainbody" class="muted" style="margin-top:6px"></div></div>
    <div class="card" id="anacard" style="margin-top:12px;display:none">
      <h2><span>🤖 محلّل Fable — أقوى قراءة</span>
        <span style="display:flex;gap:7px;align-items:center">
          <span class="pill" id="anamodel" style="font-size:10px;padding:2px 8px">—</span>
          <span class="muted" id="anaage"></span>
          <button id="anabtn">⚡ حلّل الآن</button></span></h2>
      <div class="ana-news" id="ananews"></div>
      <div class="ana-body" id="anabody"></div>
      <div class="ana-ask"><input id="anaq" placeholder="اسأل الشارت عن أيّ شيء…" maxlength="400">
        <button id="anasend">اسأل الشارت</button></div>
      <div id="anathread"></div></div>
    <div class="card" id="cncard" style="margin-top:12px;display:none">
      <h2><span>🏛️ مجلس العقول المحليّ <span class="pill" style="font-size:9px;padding:1px 7px">$0 · بلا اشتراك</span></span>
        <span style="display:flex;gap:7px;align-items:center">
          <span class="pill" id="cnagree" style="font-size:10px;padding:2px 8px">—</span>
          <span class="muted" id="cnage"></span>
          <button id="cnbtn">⚡ اجتماع الآن</button></span></h2>
      <div id="cnverdict" style="font-size:12.5px;line-height:1.9;padding:6px 2px"></div>
      <div id="cnroles"></div>
      <p class="muted" id="cnhonesty" style="font-size:10px;margin:7px 0 0"></p></div>
  </div>
  <div id="tfcol"></div>
</div>
<div id="tip"></div>
<div id="ovl"><div class="box"><h2><span id="ovltitle">—</span><span class="x" onclick="closeOvl()">✕</span></h2>
  <div class="body"><svg id="ovlsvg"></svg></div></div></div>
<footer>⚖️ SMC/POC سياقٌ بصريّ لعينك — لا إشارة آليّة (مُقاس ~50% OOS)</footer>
<script>
"use strict";
/* ─── الرموز الخمسة عشر (احتياط إن لم يُرسلها الخادم في d.symbols) ─── */
const FALLBACK_SYMS=[["XAUUSDm","الذهب"],["XAGUSDm","الفضّة"],["EURUSDm","اليورو"],["GBPUSDm","الباوند"],
["USDJPYm","الين"],["USDCHFm","الفرنك"],["USDCADm","الكندي"],["AUDUSDm","الأسترالي"],["NZDUSDm","النيوزلندي"],
["EURJPYm","يورو-ين"],["GBPJPYm","باوند-ين"],["BTCUSDm","بتكوين"],["ETHUSDm","إيثيريوم"],["USOILm","النفط"],["US30m","داو US30"]];
const TFS=[["D1","🕯️ شمعة اليوم D1"],["H4","⏳ الأربع ساعات H4"],["H1","⏱️ الساعة H1"],["M4","⚡ الدقيقة 4 M4"]];
const TFSEC={D1:86400,H4:14400,H1:3600,M4:240};   // مدّة الشمعة بالثواني (لنسبة اكتمال الشمعة الحيّة)
let DATA=null,SYM=(new URLSearchParams(location.search).get('sym'))||localStorage.getItem('pro_sym')||'XAUUSDm',lastOK=0,IDXOFF=new Set(),OVLTF=null;
let PLANON=localStorage.getItem('pro_plan')!=='0';   // 🎯 مفتاح الخطط الآليّة (ظاهر افتراضيّاً)

/* ─── أدوات ─── */
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
function digits(){return (DATA&&Number.isFinite(DATA.digits))?DATA.digits:2}
function fmt(p){return Number(p).toFixed(Math.min(digits(),5))}
function tfObj(k){return (DATA&&DATA.tfs&&DATA.tfs[k])||null}
function smcOf(tf){return tf.smc||tf}
function emaOf(tf,key,ck){ if(Array.isArray(tf[key]))return tf[key];
  const c=tf.candles||[]; if(c.length&&c[0][ck]!==undefined)return c.map(x=>x[ck]); return null }
function lvColor(L){const k=((L.cls||'')+' '+(L.name||'')).toLowerCase();
  if(k.includes('round')||k.includes('دائري'))return '#7a8090';
  if(k.includes('week')||k.includes('الأسبوع'))return 'var(--cyan)';
  if(k.includes('month')||k.includes('الشهر'))return '#e07ad0';
  if(k.includes('conf')||k.includes('التقاء'))return '#5ae0a0';
  return 'var(--gold)'} /* day/اليوم/الأمس = ذهبي */

/* ═══ drawCandles(svgEl, tf, opts) — الرسّام القابل لإعادة الاستخدام ═══ */
function drawCandles(svg,tf,opts){
  opts=opts||{};
  const C=tf.candles||[]; if(!C.length){svg.innerHTML='';return}
  const W=opts.w||svg.clientWidth||760, H=opts.h||opts.compactH||250;
  svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.setAttribute('height',H);
  const M={t:12,r:72,b:22,l:6}, pw=W-M.l-M.r, ph=H-M.t-M.b, n=C.length;
  const deco=(opts.tfk==='H1'||opts.tfk==='M4'), EXT=deco?0.88:1;  // مدّ المحور 12% نحو المستقبل (H1/M4)
  let lo=Infinity,hi=-Infinity;
  for(const c of C){ if(c.l<lo)lo=c.l; if(c.h>hi)hi=c.h }
  const pad=(hi-lo)*.05||1; lo-=pad; hi+=pad;
  const X=i=>M.l+(i+.5)*pw*EXT/n, Y=p=>M.t+(hi-p)/(hi-lo)*ph, cw=Math.max(1.6,pw*EXT/n*.62);
  const inR=p=>p>lo&&p<hi;
  /* تحويل زمن→فهرس كسريّ (يحترم الفجوات لأنّه يمسح الشموع الفعليّة) */
  const tsec=TFSEC[opts.tfk]||3600, T0=C[0].ts||0, TL=C[n-1].ts||0;
  function idxT(t){ if(t<=T0)return 0; if(t>=TL)return (n-1)+(t-TL)/tsec;
    for(let i=1;i<n;i++)if(C[i].ts>t)return i-1+(t-C[i-1].ts)/Math.max(C[i].ts-C[i-1].ts,1); return n-1 }
  const Xf=f=>M.l+f*pw*EXT/n;
  let g='';
  /* شبكة + محور السعر (يمين) */
  for(let k=0;k<=4;k++){const p=lo+(hi-lo)*k/4,y=Y(p);
    g+='<line x1="'+M.l+'" x2="'+(W-M.r)+'" y1="'+y+'" y2="'+y+'" stroke="#20242e" stroke-width="1"/>';
    g+='<text x="'+(W-M.r+6)+'" y="'+(y+3.5)+'" fill="#9aa3b2" font-size="10">'+fmt(p)+'</text>'}
  /* تكّات الزمن */
  const nt=Math.min(5,n);
  for(let k=0;k<nt;k++){const i=Math.floor(k*(n-1)/Math.max(nt-1,1));
    g+='<text x="'+X(i)+'" y="'+(H-6)+'" fill="#7a8090" font-size="9" text-anchor="middle">'+esc(C[i].t||'')+'</text>'}
  const S=smcOf(tf), xe=W-M.r;
  /* 🎯 الخطّة الآليّة (H1/M4 فقط · مفتاح الرأس) — تأطيرٌ بصريّ لا توصية مثبتة */
  const PL=(PLANON&&deco&&tf.plan&&Number.isFinite(tf.plan.entry))?tf.plan:null;
  /* 🌍 تظليل الجلسات — آسيا رماديّ / لندن أزرق عميق / نيويورك دافئ */
  if(deco&&DATA&&Array.isArray(DATA.sessions))for(const s of DATA.sessions){
    const a=Number(s.start!=null?s.start:(s.t0!=null?s.t0:s.start_epoch)),
          b2=Number(s.end!=null?s.end:(s.t1!=null?s.t1:s.end_epoch));
    if(!Number.isFinite(a)||!Number.isFinite(b2)||b2<T0||a>TL+tsec)continue;
    const sn=String(s.name||s.label||''),
          sc=sn.indexOf('آسيا')>=0?'rgba(100,116,139,.10)':(sn.indexOf('لندن')>=0?'rgba(63,102,190,.11)':(sn.indexOf('نيويورك')>=0?'rgba(240,160,48,.07)':'rgba(255,255,255,.03)'));
    const x1=Xf(Math.max(0,idxT(Math.max(a,T0)))), x2=Xf(Math.min(n,idxT(Math.min(b2,TL))+1));
    if(x2-x1<3)continue;
    g+='<rect x="'+x1+'" y="'+M.t+'" width="'+(x2-x1)+'" height="'+ph+'" fill="'+sc+'"/>';
    g+='<text x="'+((x1+x2)/2)+'" y="'+(M.t+8)+'" fill="#7a8090" font-size="7.5" text-anchor="middle">'+esc(sn)+'</text>'}
  /* 🎯 مناطق Premium/Discount من الخطّة — شرائط شفّافة + خطّ توازن منقّط (خلف الشموع) */
  if(PL&&PL.pd){const q=PL.pd,cl=p=>Math.max(lo,Math.min(hi,Number(p)));
    const yh=Y(cl(q.hi)),yp=Y(cl(q.p_line)),yd=Y(cl(q.d_line)),yl=Y(cl(q.lo));
    if(yp-yh>2)g+='<rect x="'+M.l+'" y="'+yh+'" width="'+(xe-M.l)+'" height="'+(yp-yh)+'" fill="rgba(224,90,90,.08)"/>'+
      '<text x="'+(M.l+4)+'" y="'+(yh+11)+'" fill="rgba(224,90,90,.65)" font-size="9">Premium</text>';
    if(yl-yd>2)g+='<rect x="'+M.l+'" y="'+yd+'" width="'+(xe-M.l)+'" height="'+(yl-yd)+'" fill="rgba(38,166,122,.08)"/>'+
      '<text x="'+(M.l+4)+'" y="'+(yl-4)+'" fill="rgba(38,166,122,.7)" font-size="9">Discount</text>';
    if(inR(q.e_line)){const ye=Y(q.e_line);
      g+='<line x1="'+M.l+'" x2="'+xe+'" y1="'+ye+'" y2="'+ye+'" stroke="#8a92a6" stroke-opacity=".6" stroke-width="1" stroke-dasharray="1,3"/>'+
         '<text x="'+(M.l+4)+'" y="'+(ye-3)+'" fill="#8a92a6" font-size="8">EQ توازن</text>'}}
  /* 🕐 خطوط الأحداث الإخباريّة القادمة — كهرمانيّ متقطّع داخل الامتداد */
  if(deco&&DATA&&Array.isArray(DATA.news_events)){
    const now=Date.now()/1000, fmax=n/EXT-0.6, hor=TL+(fmax-(n-1))*tsec;
    for(const e of DATA.news_events){
      const t=Number(e.epoch!=null?e.epoch:(e.ts!=null?e.ts:e.time));
      if(!Number.isFinite(t)||t<now||t>hor)continue;
      const x=X(Math.min(fmax,idxT(t)));
      g+='<line x1="'+x+'" x2="'+x+'" y1="'+M.t+'" y2="'+(M.t+ph)+'" stroke="#f0a030" stroke-width="1.2" stroke-opacity=".75" stroke-dasharray="5,4"/>';
      g+='<text x="'+(x-3)+'" y="'+(M.t+ph-4)+'" fill="#f0a030" fill-opacity=".9" font-size="8" text-anchor="start" transform="rotate(-90 '+(x-3)+' '+(M.t+ph-4)+')">'+esc(String(e.title||'').slice(0,20))+'</text>'}}
  /* OB — مستطيلات شفّافة (صاعد أخضر/هابط أحمر · مُخفَّف+✓ إن خُفِّف) */
  for(const z of (S.ob||[])){ if(!(inR(z.lo)||inR(z.hi)))continue;
    const y1=Y(Math.min(z.hi,hi)),y2=Y(Math.max(z.lo,lo)),x0=X(Math.max(0,Math.min(z.idx,n-1)))-cw/2;
    const col=z.dir>0?'38,166,122':'224,90,90', op=z.mitigated?.06:.15;
    g+='<rect x="'+x0+'" y="'+y1+'" width="'+Math.max(4,xe-x0)+'" height="'+Math.max(2,y2-y1)+
       '" fill="rgba('+col+','+op+')" stroke="rgba('+col+',.4)" stroke-width="1"'+(z.mitigated?' stroke-dasharray="2,3"':'')+'/>';
    g+='<text x="'+(xe-4)+'" y="'+(y1+10)+'" fill="rgba('+col+',.85)" font-size="9" text-anchor="end">OB'+(z.mitigated?' ✓':'')+'</text>'}
  /* FVG ذهبيّة / IFVG بنفسجيّة */
  for(const z of (S.fvg||[])){ if(!(inR(z.lo)||inR(z.hi)))continue;
    const y1=Y(Math.min(z.hi,hi)),y2=Y(Math.max(z.lo,lo)),x0=X(Math.max(0,Math.min(z.idx,n-1)))-cw/2;
    const inv=!!z.inverted, fill=inv?'rgba(181,122,224,.16)':'rgba(245,197,24,.13)',
          st=inv?'rgba(181,122,224,.5)':'rgba(245,197,24,.4)';
    g+='<rect x="'+x0+'" y="'+y1+'" width="'+Math.max(4,xe-x0)+'" height="'+Math.max(2,y2-y1)+
       '" fill="'+fill+'" stroke="'+st+'" stroke-width="1"/>';
    g+='<text x="'+(xe-4)+'" y="'+(y2-3)+'" fill="'+st+'" font-size="9" text-anchor="end">'+(inv?'IFVG':'FVG')+'</text>'}
  /* برك السيولة $$$ — منقّطة بيضاء */
  for(const p of (S.liq_pools||[])){ if(!inR(p.price))continue;
    const x0=X(Math.max(0,Math.min(Math.min.apply(null,p.idxs||[0]),n-1))),y=Y(p.price);
    g+='<line x1="'+x0+'" x2="'+xe+'" y1="'+y+'" y2="'+y+'" stroke="rgba(255,255,255,.55)" stroke-width="1" stroke-dasharray="2,4"/>';
    g+='<text x="'+(xe-4)+'" y="'+(y-3)+'" fill="rgba(255,255,255,.75)" font-size="9.5" text-anchor="end">$$$ '+(p.side==='high'?'قمم':'قيعان')+'×'+(p.count||2)+'</text>'}
  /* مستويات الفترات (يوم ذهبي · أسبوع سماوي · دائري رمادي) */
  for(const L of (tf.levels||[])){ if(!inR(L.price))continue;
    const y=Y(L.price),col=lvColor(L);
    g+='<line x1="'+M.l+'" x2="'+xe+'" y1="'+y+'" y2="'+y+'" stroke="'+col+'" stroke-opacity=".45" stroke-dasharray="5,4"/>';
    g+='<text x="'+(M.l+3)+'" y="'+(y-3)+'" fill="'+col+'" fill-opacity=".8" font-size="9">'+esc(L.name||'')+' '+fmt(L.price)+'</text>'}
  /* HVN منقّطة رفيعة ثم POC سماويّ عريض متقطّع (خط الوسط) */
  for(const hv of (S.hvn||[])){ if(!inR(hv)||hv===S.poc)continue; const y=Y(hv);
    g+='<line x1="'+M.l+'" x2="'+xe+'" y1="'+y+'" y2="'+y+'" stroke="var(--cyan)" stroke-opacity=".35" stroke-width="1" stroke-dasharray="1,4"/>'}
  if(Number.isFinite(S.poc)&&inR(S.poc)){const y=Y(S.poc);
    g+='<line x1="'+M.l+'" x2="'+xe+'" y1="'+y+'" y2="'+y+'" stroke="var(--cyan)" stroke-width="2" stroke-dasharray="8,5"/>';
    g+='<text x="'+(xe-4)+'" y="'+(y-4)+'" fill="var(--cyan)" font-size="10" font-weight="bold" text-anchor="end">POC '+fmt(S.poc)+'</text>'}
  /* VWAP بنفسجيّ متقطّع (رقم أو سلسلة) */
  const vw=tf.vwap;
  if(Array.isArray(vw)&&vw.length===n){let pts='';for(let i=0;i<n;i++)if(Number.isFinite(vw[i]))pts+=X(i)+','+Y(Math.max(lo,Math.min(hi,vw[i])))+' ';
    g+='<polyline points="'+pts+'" fill="none" stroke="var(--violet)" stroke-width="1.4" stroke-dasharray="6,4"/>';
    g+='<text x="'+(xe-4)+'" y="'+(Y(vw[n-1])+11)+'" fill="var(--violet)" font-size="9" text-anchor="end">VWAP</text>'}
  else if(Number.isFinite(vw)&&inR(vw)){const y=Y(vw);
    g+='<line x1="'+M.l+'" x2="'+xe+'" y1="'+y+'" y2="'+y+'" stroke="var(--violet)" stroke-width="1.4" stroke-dasharray="6,4"/>';
    g+='<text x="'+(xe-4)+'" y="'+(y+11)+'" fill="var(--violet)" font-size="9" text-anchor="end">VWAP '+fmt(vw)+'</text>'}
  /* الشموع */
  for(let i=0;i<n;i++){const c=C[i],up=c.c>=c.o,col=up?'var(--up)':'var(--dn)',x=X(i);
    g+='<line x1="'+x+'" x2="'+x+'" y1="'+Y(c.h)+'" y2="'+Y(c.l)+'" stroke="'+col+'" stroke-width="1"/>';
    const by=Y(Math.max(c.o,c.c)),bh=Math.max(1,Math.abs(Y(c.o)-Y(c.c)));
    g+='<rect x="'+(x-cw/2)+'" y="'+by+'" width="'+cw+'" height="'+bh+'" fill="'+col+'" rx="0.5"/>'}
  /* EMA50 برتقالي · EMA200 أزرق */
  for(const [key,ck,col,w2,lab] of [['ema50','e50','var(--orange)',1.5,'EMA50'],['ema200','e200','var(--blue)',1.8,'EMA200']]){
    const E=emaOf(tf,key,ck); if(!E)continue; let pts='';
    for(let i=0;i<n&&i<E.length;i++)if(Number.isFinite(E[i]))pts+=X(i)+','+Y(Math.max(lo,Math.min(hi,E[i])))+' ';
    g+='<polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="'+w2+'"/>';
    if(Number.isFinite(E[n-1])&&inR(E[n-1]))
      g+='<text x="'+(xe+2)+'" y="'+(Y(E[n-1])+3)+'" fill="'+col+'" font-size="8.5">'+lab+'</text>'}
  /* BOS/CHoCH — أعلام بأسهم (CHoCH أعرض وأجرأ) */
  for(const kind of ['bos','choch']){
    for(const e of (S[kind]||[])){ if(!inR(e.price))continue;
      const x=X(Math.max(0,Math.min(e.idx,n-1))),y=Y(e.price),upd=e.dir>0,col=upd?'var(--up)':'var(--dn)',
            ch=kind==='choch',fs=ch?11:9.5,fw=ch?'bold':'normal',dy=upd?-7:14,ar=upd?'↑':'↓';
      g+='<line x1="'+x+'" x2="'+x+'" y1="'+(y-16)+'" y2="'+(y+16)+'" stroke="'+col+'" stroke-opacity=".45" stroke-width="'+(ch?1.6:1)+'" stroke-dasharray="3,3"/>';
      g+='<text x="'+x+'" y="'+(y+dy)+'" fill="'+col+'" font-size="'+fs+'" font-weight="'+fw+'" text-anchor="middle">'+
         ar+' '+(ch?'CHoCH':'BOS')+'</text>'}}
  /* ⚡ اصطيادات السيولة */
  for(const s of (S.sweeps||[])){ if(!inR(s.price))continue;
    const x=X(Math.max(0,Math.min(s.idx,n-1))),y=Y(s.price)+(s.side==='high'?-6:12);
    g+='<text x="'+x+'" y="'+y+'" font-size="12" text-anchor="middle">⚡</text>'}
  /* 💹 علامات صفقات اليوم: ▲ شراء · ▼ بيع · ✕ خروج — حدّها بلون المجموعة + Tooltip */
  if(deco&&DATA&&Array.isArray(DATA.trades))for(const tr of DATA.trades){
    const t=Number(tr.t),p=Number(tr.price);
    if(!Number.isFinite(t)||!Number.isFinite(p)||t<T0-tsec||t>TL+tsec||!inR(p))continue;
    const x=X(Math.max(0,Math.min(n-1,Math.round(idxT(t))))), y=Y(p),
          col=GCOL[tr.magic_group]||'#c8cdd8', lab=esc(tr.magic_group||''), pnl=Number(tr.pnl);
    let mk;
    if(tr.kind==='in')mk=(tr.dir>0)
      ?'<polygon points="'+x+','+(y-7)+' '+(x-4.5)+','+(y+2)+' '+(x+4.5)+','+(y+2)+'" fill="var(--up)" stroke="'+col+'" stroke-width="1"/>'
      :'<polygon points="'+x+','+(y+7)+' '+(x-4.5)+','+(y-2)+' '+(x+4.5)+','+(y-2)+'" fill="var(--dn)" stroke="'+col+'" stroke-width="1"/>';
    else mk='<text x="'+x+'" y="'+(y+4)+'" fill="'+col+'" font-size="11" font-weight="bold" text-anchor="middle">✕</text>';
    g+='<g style="cursor:help">'+mk+'<text x="'+x+'" y="'+(y+(tr.kind==='in'&&tr.dir>0?13:-10))+'" fill="'+col+'" font-size="7" text-anchor="middle">'+lab+'</text>'+
       '<title>'+lab+' · '+fmt(p)+(Number.isFinite(pnl)?' · '+(pnl>=0?'+':'')+pnl.toFixed(2)+'$':'')+'</title></g>'}
  /* 🎯 حبوب الخطّة على الحافّة اليمنى + خطوطها الأفقيّة — تكديسٌ بلا تداخل، تتجدّد كلّ 3ث */
  if(PL){
    const xin=X(n-1), tps=Array.isArray(PL.tps)?PL.tps:[], clY=p=>Y(Math.max(lo,Math.min(hi,p)));
    const items=[{p:PL.entry,y:clY(PL.entry),h:14,fs:9,col:'var(--cyan)',txt:'دخول ENTRY '+fmt(PL.entry),ln:'solid',x1:xin}];
    if(Number.isFinite(PL.sl)){
      items.push({p:PL.sl,y:clY(PL.sl),h:14,fs:9,col:'var(--dn)',txt:'وقف SL '+fmt(PL.sl),ln:'solid',x1:M.l});
      if(Number.isFinite(PL.trailing))  /* حبّة Trailing الكهرمانيّة الصغيرة تحت/فوق حبّة الوقف */
        items.push({p:PL.trailing,y:clY(PL.sl)+(PL.dir>0?15:-15),h:11,fs:7.5,col:'var(--orange)',txt:'Trailing '+fmt(PL.trailing),ln:null})}
    for(let q=0;q<tps.length&&q<3;q++)if(Number.isFinite(tps[q]))
      items.push({p:tps[q],y:clY(tps[q]),h:14,fs:9,col:'var(--up)',txt:'TP'+(q+1)+' '+fmt(tps[q]),ln:'dash',x1:M.l});
    items.sort((a,b)=>a.y-b.y);              /* إزاحة عموديّة دنيا كي لا تتراكب الحبوب */
    for(let q=1;q<items.length;q++){const need=(items[q-1].h+items[q].h)/2+2;
      if(items[q].y<items[q-1].y+need)items[q].y=items[q-1].y+need}
    for(const it of items){
      if(it.ln&&inR(it.p)){const yl2=Y(it.p);
        g+='<line x1="'+it.x1+'" x2="'+xe+'" y1="'+yl2+'" y2="'+yl2+'" stroke="'+it.col+'" stroke-width="1.3" stroke-opacity=".85"'+(it.ln==='dash'?' stroke-dasharray="6,4"':'')+'/>'}
      const wpx=it.txt.length*it.fs*.62+14;
      g+='<rect x="'+(xe-wpx)+'" y="'+(it.y-it.h/2)+'" width="'+wpx+'" height="'+it.h+'" rx="'+(it.h/2)+'" fill="rgba(12,15,20,.92)" stroke="'+it.col+'" stroke-width="1"/>'+
         '<text x="'+(xe-7)+'" y="'+(it.y+it.fs*.36)+'" fill="'+it.col+'" font-size="'+it.fs+'" text-anchor="end">'+esc(it.txt)+'</text>'}
    /* شارة الاتجاه قرب الدخول + سطر الصدق (خطّة آليّة — تأطيرٌ لا توصية مثبتة) */
    const buy=PL.dir>0, bcol=buy?'var(--up)':'var(--dn)',
          by2=Math.max(M.t+14,Math.min(M.t+ph-16,clY(PL.entry)+(buy?27:-27)));
    g+='<text x="'+(xe-8)+'" y="'+by2+'" fill="'+bcol+'" font-size="10" font-weight="bold" text-anchor="end">'+
       (buy?'🟢 خطّة شراء آليّة':'🔴 خطّة بيع آليّة')+(Number.isFinite(PL.r)?' · R '+Number(PL.r).toFixed(2):'')+'</text>'+
       '<text x="'+(xe-8)+'" y="'+(by2+11)+'" fill="#7a8090" font-size="8" text-anchor="end">'+
       esc(String(PL.note||'خطّة آليّة — تأطيرٌ لا توصية مثبتة').slice(0,70))+'</text>'}
  /* مجموعة الكروس-هير + مسطرة القياس + مستطيل الالتقاط */
  g+='<g id="__ms"></g>';
  g+='<g id="__ch" style="display:none">'+
     '<line id="__chv" y1="'+M.t+'" y2="'+(M.t+ph)+'" stroke="rgba(245,197,24,.55)" stroke-width="1" stroke-dasharray="3,3"/>'+
     '<line id="__chh" x1="'+M.l+'" x2="'+(W-M.r)+'" stroke="rgba(245,197,24,.55)" stroke-width="1" stroke-dasharray="3,3"/>'+
     '<rect id="__chpx" x="'+(W-M.r+2)+'" width="'+(M.r-4)+'" height="14" rx="3" fill="var(--gold)"/>'+
     '<text id="__chpt" x="'+(W-M.r+6)+'" fill="#0b0e13" font-size="10" font-weight="bold"></text></g>'+
     '<rect x="'+M.l+'" y="'+M.t+'" width="'+pw+'" height="'+ph+'" fill="transparent" class="__cap"/>';
  svg.innerHTML=g;
  svg.__px={M,pw,ph,n,C,X,Y,lo,hi,ext:EXT};
  const cap=svg.querySelector('.__cap');
  cap.addEventListener('mousedown',ev=>{ if(ev.shiftKey){ev.preventDefault();svg.__msA=msPt(svg,ev)} });
  cap.addEventListener('mouseup',()=>{svg.__msA=null});
  cap.addEventListener('mousemove',ev=>{ if(svg.__msA&&ev.buttons)msMove(svg,ev); else crosshair(svg,ev) });
  cap.addEventListener('mouseleave',()=>{svg.__msA=null;svg.querySelector('#__ch').style.display='none';$('tip').style.display='none'});
}

/* ─── 📏 مسطرة القياس: Shift+سحب ⇒ Δ$ · Δ% · عدد الشموع (تختفي بعد 4ث) ─── */
function msPt(svg,ev){const P=svg.__px,r=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal,
  sx=(ev.clientX-r.left)*vb.width/r.width, sy=(ev.clientY-r.top)*vb.height/r.height;
  const i=Math.max(0,Math.min(P.n-1,Math.floor((sx-P.M.l)/(P.pw*(P.ext||1)/P.n))));
  return {sx,sy,i,price:P.hi-(sy-P.M.t)/P.ph*(P.hi-P.lo)}}
function msMove(svg,ev){
  const a=svg.__msA,b=msPt(svg,ev),G=svg.querySelector('#__ms'); if(!a||!G)return;
  const d=b.price-a.price, pc=a.price?d/a.price*100:0, bars=Math.abs(b.i-a.i),
        col=d>=0?'var(--up)':'var(--dn)', mx=(a.sx+b.sx)/2, my=Math.min(a.sy,b.sy)-8;
  G.innerHTML='<line x1="'+a.sx+'" y1="'+a.sy+'" x2="'+b.sx+'" y2="'+b.sy+'" stroke="'+col+'" stroke-width="1.5" stroke-dasharray="6,3"/>'+
    '<circle cx="'+a.sx+'" cy="'+a.sy+'" r="2.5" fill="'+col+'"/><circle cx="'+b.sx+'" cy="'+b.sy+'" r="2.5" fill="'+col+'"/>'+
    '<rect x="'+(mx-72)+'" y="'+(my-14)+'" width="144" height="16" rx="4" fill="rgba(12,15,20,.92)" stroke="'+col+'"/>'+
    '<text x="'+mx+'" y="'+(my-2)+'" fill="'+col+'" font-size="10" text-anchor="middle">Δ '+(d>=0?'+':'')+d.toFixed(Math.min(digits(),5))+' · '+(pc>=0?'+':'')+pc.toFixed(2)+'% · '+bars+' شمعة</text>';
  if(svg.__msT)clearTimeout(svg.__msT);
  svg.__msT=setTimeout(()=>{G.innerHTML=''},4000)}

/* ─── Crosshair + Tooltip ─── */
function crosshair(svg,ev){
  const P=svg.__px; if(!P)return;
  const r=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal,
        sx=(ev.clientX-r.left)*vb.width/r.width, sy=(ev.clientY-r.top)*vb.height/r.height;
  let i=Math.floor((sx-P.M.l)/(P.pw*(P.ext||1)/P.n)); i=Math.max(0,Math.min(P.n-1,i));
  const c=P.C[i],x=P.X(i),price=P.hi-(sy-P.M.t)/P.ph*(P.hi-P.lo);
  const G=svg.querySelector('#__ch'); G.style.display='';
  G.querySelector('#__chv').setAttribute('x1',x); G.querySelector('#__chv').setAttribute('x2',x);
  G.querySelector('#__chh').setAttribute('y1',sy); G.querySelector('#__chh').setAttribute('y2',sy);
  G.querySelector('#__chpx').setAttribute('y',sy-7);
  const pt=G.querySelector('#__chpt'); pt.setAttribute('y',sy+3.5); pt.textContent=fmt(price);
  const up=c.c>=c.o,t=$('tip');
  t.innerHTML='<b>'+esc(c.t||'')+'</b><br>افتتاح '+fmt(c.o)+' · أعلى '+fmt(c.h)+
    '<br>أدنى '+fmt(c.l)+' · إغلاق <span style="color:'+(up?'var(--up)':'var(--dn)')+'">'+fmt(c.c)+'</span>';
  t.style.display='block';
  const tw=t.offsetWidth||150;
  t.style.left=Math.min(window.innerWidth-tw-10,ev.clientX+14)+'px';
  t.style.top=Math.max(8,ev.clientY-t.offsetHeight-12)+'px';
}

/* ─── Index Chart (SVG خطّي خالص) ─── */
function renderIndex(){
  const IX=(DATA&&DATA.index)||null,svg=$('idxsvg'),lg=$('idxlegend'),cr=$('corr');
  if(!IX||!IX.series||!IX.series.length){svg.innerHTML='';lg.innerHTML='<span class="muted">لا بيانات مؤشّر</span>';return}
  const W=svg.clientWidth||520,H=330,M={t:12,r:14,b:22,l:40},pw=W-M.l-M.r,ph=H-M.t-M.b;
  svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.setAttribute('height',H);
  const vis=IX.series.filter(s=>!IDXOFF.has(s.sym));
  let lo=Infinity,hi=-Infinity;
  for(const s of vis)for(const v of s.index){if(v<lo)lo=v;if(v>hi)hi=v}
  if(!vis.length||!isFinite(lo)){svg.innerHTML='';}
  else{
    const pad=(hi-lo)*.04||1; lo-=pad; hi+=pad;
    const n=vis[0].index.length,X=i=>M.l+i*pw/Math.max(n-1,1),Y=v=>M.t+(hi-v)/(hi-lo)*ph;
    let g='';
    for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4,y=Y(v);
      g+='<line x1="'+M.l+'" x2="'+(W-M.r)+'" y1="'+y+'" y2="'+y+'" stroke="#20242e"/>'+
         '<text x="'+(M.l-5)+'" y="'+(y+3.5)+'" fill="#9aa3b2" font-size="10" text-anchor="end">'+v.toFixed(1)+'</text>'}
    if(100>lo&&100<hi){const y=Y(100);
      g+='<line x1="'+M.l+'" x2="'+(W-M.r)+'" y1="'+y+'" y2="'+y+'" stroke="#3a3f4b" stroke-dasharray="4,4"/>'}
    const times=IX.times||[],nt=Math.min(5,times.length);
    for(let k=0;k<nt;k++){const i=Math.floor(k*(times.length-1)/Math.max(nt-1,1));
      g+='<text x="'+X(i*(n-1)/Math.max(times.length-1,1))+'" y="'+(H-6)+'" fill="#7a8090" font-size="9" text-anchor="middle">'+esc(String(times[i]).slice(0,5))+'</text>'}
    for(const s of vis){const gold=s.sym==='XAUUSDm';let pts='';
      for(let i=0;i<s.index.length;i++)pts+=X(i)+','+Y(s.index[i])+' ';
      g+='<polyline points="'+pts+'" fill="none" stroke="'+s.color+'" stroke-width="'+(gold?2.8:1.3)+'"'+
         (gold?' style="filter:drop-shadow(0 0 4px rgba(245,197,24,.5))"':' stroke-opacity=".85"')+'/>'}
    svg.innerHTML=g;
  }
  lg.innerHTML='';
  for(const s of IX.series){const el=document.createElement('span');
    el.className=IDXOFF.has(s.sym)?'off':'';
    el.innerHTML='<i style="background:'+s.color+'"></i>'+esc(s.label)+' <span class="muted">'+(s.corr>=0?'+':'')+s.corr+'</span>';
    el.onclick=()=>{IDXOFF.has(s.sym)?IDXOFF.delete(s.sym):IDXOFF.add(s.sym);renderIndex()};
    lg.append(el)}
  cr.innerHTML='';
  const sorted=IX.series.filter(s=>s.sym!=='XAUUSDm').slice().sort((a,b)=>b.corr-a.corr);
  for(const s of sorted){const pos=s.corr>=0,w=Math.min(Math.abs(s.corr)*50,50),row=document.createElement('div');
    row.className='corr-row';
    row.innerHTML='<span class="corr-name">'+esc(s.label.replace('‏ (معكوس)',''))+'</span>'+
      '<span class="corr-bar"><span class="corr-fill" style="'+(pos?'right:50%':'left:50%')+';width:'+w+
      '%;background:'+(pos?'var(--up)':'var(--dn)')+'"></span>'+
      '<span style="position:absolute;left:50%;top:0;height:100%;width:1px;background:#3a3f4b"></span></span>'+
      '<span class="corr-val" style="color:'+(pos?'var(--up)':'var(--dn)')+'">'+(pos?'+':'')+s.corr+'</span>';
    cr.append(row)}
}

/* ─── 🧮 مكتب الحسابات — d.desk من quant_desk.json (تجميعٌ شفّاف للقراءة، لا إشارة) ─── */
const FLBL={trend_mtf:'الترند متعدّد الفريمات',mtf_trend:'الترند متعدّد الفريمات',trend:'الترند متعدّد الفريمات',
momentum:'الزخم',smc:'بنية SMC',smc_structure:'بنية SMC',structure:'بنية SMC',
poc:'موقع POC',poc_position:'موقع POC',basket:'تأكيد السلّة',basket_confirm:'تأكيد السلّة',index_confirm:'تأكيد السلّة',
candles:'الشموع',candle:'الشموع',patterns:'الشموع'};
const GLBL={youtube:'يوتيوب',yt:'يوتيوب',sentinel:'حارس',gold_sentinel:'حارس',multi:'multi',multi_trader:'multi',
warroom:'warroom',army_warroom:'warroom',manual:'يدويّ',user:'يدويّ'};
/* لون كلّ مجموعة ماجيك (علامات الصفقات على الشموع) */
const GCOL={'يوتيوب':'#e07ad0','حارس':'#4fd0e0','multi':'#f5c518','warroom':'#b57ae0','news':'#f0a030','يدويّ':'#ffffff','آخر':'#9aa3b2'};
const money=v=>{const x=Number(v)||0;return '<span style="direction:ltr;display:inline-block;color:'+(x>=0?'var(--up)':'var(--dn)')+'">'+(x>=0?'+':'')+x.toFixed(2)+'</span>'};
/* ─── 🧠 المخ الواحد — d.unified (صهر كل العيون في حكمٍ واحد + أفضل الفرص) ─── */
function renderUnified(){
  const card=$('unifiedcard'); if(!card)return;
  const U=DATA&&DATA.unified;
  if(!U){card.style.display='none';return}
  card.style.display='';
  $('unisym').textContent=U.sym||SYM;
  const dir=U.dir||0, vcol=dir>0?'var(--up)':(dir<0?'var(--dn)':'var(--dim)');
  const conv=Math.round((Number(U.conviction)||0)*100);
  let h='<div style="text-align:center;margin-bottom:8px">'+
    '<span style="display:inline-block;padding:6px 30px;border-radius:22px;font-weight:800;font-size:17px;'+
    'background:'+vcol+'26;color:'+vcol+';border:1px solid '+vcol+'">'+esc(U.verdict||'—')+'</span></div>'+
    '<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--dim);margin-bottom:3px">'+
    '<span>قناعة المخ</span><span style="color:'+vcol+';font-weight:700">'+conv+'% · اتّفاق '+(U.agree||0)+'/4</span></div>'+
    '<div style="height:7px;background:#23262e;border-radius:4px;overflow:hidden;margin-bottom:8px">'+
    '<div style="height:100%;width:'+conv+'%;background:'+vcol+'"></div></div>';
  /* أصوات العيون */
  h+='<div style="font-size:11px;color:var(--dim);margin-bottom:3px">أصوات العيون (شفّافة):</div>';
  const V=U.voices||{};
  for(const k in V){const val=Number(V[k])||0, c=val>0?'var(--up)':(val<0?'var(--dn)':'var(--dim)'),
      w=Math.min(Math.abs(val)*50,50);
    h+='<div style="display:flex;align-items:center;gap:6px;font-size:11px;padding:1px 0">'+
       '<span style="width:38px;color:var(--dim)">'+esc(k)+'</span>'+
       '<span style="flex:1;height:8px;background:#1c1f27;border-radius:3px;position:relative">'+
       '<span style="position:absolute;'+(val>=0?'left:50%':'right:50%')+';width:'+w+'%;height:100%;background:'+c+';border-radius:3px"></span>'+
       '<span style="position:absolute;left:50%;top:0;height:100%;width:1px;background:#3a3f4b"></span></span>'+
       '<span style="width:34px;text-align:left;direction:ltr;color:'+c+'">'+(val>=0?'+':'')+val.toFixed(2)+'</span></div>';}
  /* أفضل الفرص عبر كل العملات — نقرة = تبديل */
  const top=Array.isArray(U.top)?U.top:[];
  if(top.length){h+='<div style="font-size:11px;color:var(--dim);margin:7px 0 3px">🏆 أفضل الفرص (كل العملات · انقر):</div><div class="dz-rank">';
    for(const t of top){const tc=/شراء/.test(t.verdict)?'var(--up)':(/بيع/.test(t.verdict)?'var(--dn)':'var(--dim)');
      h+='<span class="rank-chip" data-sym="'+esc(t.sym)+'" style="border-color:'+tc+'55" title="قناعة '+Math.round((t.conviction||0)*100)+'%">'+
         esc(t.sym)+' <b style="color:'+tc+'">'+(t.verdict||'').replace(/🟢|🔴|⚪/g,'').trim()+'</b></span>';}
    h+='</div>'}
  const ev=U.evolver||{};
  h+='<div style="font-size:10px;color:var(--dim);margin-top:7px;border-top:1px solid #23262e;padding-top:5px">'+
     '🧬 المطوّر الذاتيّ: '+(ev.candidates||0)+' مرشّح · '+esc((ev.last_verdict||'—').slice(0,44))+'</div>'+
     '<div style="font-size:9px;color:var(--dim);margin-top:3px">الصهر تنسيقٌ لا تنبّؤ — سياقٌ موحّد وبوّابة، لا آلة ربح.</div>';
  $('unibody').innerHTML=h;
}
/* ─── 🦅 لوحة MTF (بأسلوب إعلان الصقر لكن من بياناتنا الحيّة) — d.mtf ─── */
function renderMTF(){
  const card=$('mtfcard'); if(!card)return;
  const M=DATA&&DATA.mtf;
  if(!M){card.style.display='none';return}
  card.style.display='';
  const B=M.biases||{};
  let chips='<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px">';
  for(const tf of ['M1','M5','M15','M30','H1','H4','D1']){
    const b=B[tf]||0, col=b>0?'var(--up)':(b<0?'var(--dn)':'#5a6070');
    chips+='<span style="flex:1;text-align:center;padding:4px 2px;border-radius:7px;font-size:10px;font-weight:700;'+
           'background:'+col+'22;color:'+col+';border:1px solid '+col+'55">'+tf+'<br>'+(b>0?'▲':(b<0?'▼':'—'))+'</span>';
  }
  chips+='</div>';
  const pos=M.position||'حياد',
        pcol=pos==='شراء'?'var(--up)':(pos==='بيع'?'var(--dn)':'var(--dim)');
  let h=chips+'<div style="text-align:center;margin-bottom:8px"><span style="display:inline-block;padding:5px 26px;'+
    'border-radius:20px;font-weight:800;font-size:15px;background:'+pcol+'26;color:'+pcol+';border:1px solid '+pcol+'">'+
    esc(pos)+(pos!=='حياد'?' الآن':'')+' · أصوات '+(M.vote>0?'+':'')+M.vote+'/7</span></div>';
  const V=M.vol||{};
  const rows=[
    ['🔥 حالة السوق', M.market_state||'—'],
    ['📏 التقلب المحقق اليومي (σ√T)', V.realized_daily_pct!=null?V.realized_daily_pct+'%':'—'],
    ['🌡️ نظام التقلب (30 يوماً)', (V.regime||'—')+(V.pctile_30d!=null?' · pct '+V.pctile_30d:'')],
    ['🌀 عنقدة التقلب (GARCH-lite)', V.clustering||'—'],
    ['🏦 نشاط المؤسسات', M.institutional||'—'],
    ['🕐 الجلسة', M.session||'—'],
    ['💨 ضغط الترند (H4+D1)', M.trend_pressure||'—']];
  for(const [k,v] of rows)
    h+='<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid #23262e;font-size:12px">'+
       '<span style="color:var(--dim)">'+k+'</span><span style="font-weight:600">'+esc(String(v))+'</span></div>';
  h+='<div style="margin-top:7px;padding:6px 9px;border-radius:9px;background:#f5c51815;border:1px solid #f5c51840;'+
     'font-size:12px;color:var(--gold)">🚦 فلتر التقلب: '+esc(V.filter||'—')+'</div>';
  /* 🕯️ عين تشريح الشموع — نفس معادلات المحرّك حرفياً */
  const C=M.candles;
  if(C){
    const bcol=C.bias>=1?'var(--up)':(C.bias<=-1?'var(--dn)':'var(--dim)');
    h+='<div style="margin-top:9px;border-top:1px solid #2a2e38;padding-top:7px">'+
       '<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">'+
       '<span style="color:var(--dim)">🕯️ عين تشريح الشموع (M1)</span>'+
       '<span style="font-weight:700;color:'+bcol+'">'+esc(C.verdict)+' ('+(C.bias>0?'+':'')+C.bias+')</span></div>';
    for(const n of (C.notes||[]))
      h+='<div style="font-size:11px;color:var(--dim);padding:1px 0">• '+esc(n)+'</div>';
    h+='<div style="overflow-x:auto"><table style="width:100%;font-size:10px;border-collapse:collapse;margin-top:4px;direction:rtl">'+
       '<tr style="color:var(--dim)"><th>وقت</th><th>لون</th><th>جسم$</th><th>مدى$</th><th>ذيل↑%</th><th>ذيل↓%</th><th>مدى/ATR</th></tr>';
    for(const r of (C.rows||[])){
      const cc=r['لون']==='أخضر'?'var(--up)':(r['لون']==='أحمر'?'var(--dn)':'var(--dim)');
      h+='<tr style="text-align:center;border-top:1px solid #23262e">'+
         '<td>'+esc(r.t)+'</td><td style="color:'+cc+'">'+esc(r['لون'])+'</td>'+
         '<td style="direction:ltr">'+r['جسم$']+'</td><td>'+r['مدى$']+'</td>'+
         '<td>'+r['ذيل_علوي%']+'</td><td>'+r['ذيل_سفلي%']+'</td><td>'+r['مدى/ATR']+'</td></tr>';
    }
    h+='</table></div><div style="font-size:10px;color:var(--dim);margin-top:3px">ATR-M1 = '+C.atr_m1+
       '$ · هذه الأرقام نفسها التي يقرؤها المحرّك (radhi_mimic._candle_read) قبل كل قرار.</div></div>';
  }
  $('mtfbody').innerHTML=h;
}
function symGauge(comp,verdict){
  const c=Math.max(-100,Math.min(100,Number(comp)||0)), pos=(c+100)/2,
        vcol=c>15?'var(--up)':(c<-15?'var(--dn)':'var(--dim)');
  return '<div class="dz-gauge"><div class="dz-needle" style="left:'+pos+'%"></div></div>'+
    '<div class="dz-scale"><span>بيع −100</span><span>0</span><span>شراء +100</span></div>'+
    '<div class="dz-verdict" style="color:'+vcol+'">'+esc(verdict||'—')+
    ' <span style="font-size:12px;direction:ltr;display:inline-block">('+(c>=0?'+':'')+c.toFixed(0)+')</span></div>';
}
function renderDesk(){
  const card=$('deskcard'); if(!card)return;
  const D=(DATA&&DATA.desk)||null, G=D&&D.gold;
  const DS=DATA&&DATA.desk_sym;
  /* 🌍 رمز غير الذهب: بطاقة مكتب مخصّصة له (مركّب + نسبة معرفتنا) — «القمرة لكل العملات» */
  if(DS && !DS.is_gold){
    card.style.display='';
    $('deskts').textContent=DS.sym;
    let h=symGauge(DS.composite, DS.read||'—');
    const K=DS.knowledge;
    if(K){
      const kcol=K.t_stat>=2?'var(--up)':(K.t_stat<=-2?'var(--dn)':'var(--dim)');
      h+='<div class="dz-sec">📚 معرفتنا لهذا الرمز:</div>'+
         '<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0">'+
         '<span style="color:var(--dim)">نسبة المعرفة</span><span style="font-weight:700">'+(K.pct!=null?K.pct+'%':'—')+'</span></div>'+
         '<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0">'+
         '<span style="color:var(--dim)">صفقات مقيسة · t</span><span style="direction:ltr;color:'+kcol+'">'+
         (K.n_trades!=null?K.n_trades:'—')+' · t='+(K.t_stat!=null?K.t_stat:'—')+'</span></div>'+
         '<div style="font-size:11px;color:'+kcol+';margin-top:4px">'+esc(K.verdict||'')+'</div>';
    }
    h+='<div style="font-size:10px;color:var(--dim);margin-top:6px">مركّب المكتب لكل العملات — التفصيل الكامل بالعوامل متاحٌ للذهب. بدّل للذهب لرؤية تشريح الأوزان.</div>';
    $('deskbody').innerHTML=h;
    return;
  }
  if(!G){card.style.display='none';return}        /* غياب الملفّ ⇒ إخفاءٌ رشيق */
  card.style.display='';
  $('deskts').textContent=D.iso?String(D.iso).slice(11,19):'';
  /* عدّاد المركّب −100..+100: إبرة على تدرّج أحمر→رمادي→أخضر + الحكم العربيّ */
  const comp=Math.max(-100,Math.min(100,Number(G.composite)||0)), pos=(comp+100)/2;
  const vcol=comp>15?'var(--up)':(comp<-15?'var(--dn)':'var(--dim)');
  let h='<div class="dz-gauge"><div class="dz-needle" style="left:'+pos+'%"></div></div>'+
    '<div class="dz-scale"><span>بيع −100</span><span>0</span><span>شراء +100</span></div>'+
    '<div class="dz-verdict" style="color:'+vcol+'">'+esc(G.verdict||'—')+
    ' <span style="font-size:12px;direction:ltr;display:inline-block">('+(comp>=0?'+':'')+comp.toFixed(0)+')</span></div>';
  /* جدول العوامل — الأوزان معلنة ليحسب المستخدم بنفسه: وزن% · شريط قيمة ±1 · مساهمة */
  h+='<div class="dz-sec">العوامل (الأوزان معلنة — تُحسب أمامك):</div>';
  for(const k in (G.factors||{})){const f=G.factors[k]; if(!f)continue;
    const v=Math.max(-1,Math.min(1,Number(f.value)||0)), wRaw=Number(f.weight)||0,
          w=wRaw>1.5?wRaw:wRaw*100, ctr=Number(f.contrib)||0,
          bw=Math.min(Math.abs(v)*50,50), bcol=v>=0?'var(--up)':'var(--dn)';
    h+='<div class="dz-frow"><span class="dz-fname">'+esc(FLBL[k]||k)+'</span>'+
       '<span class="dz-fw">'+w.toFixed(0)+'%</span>'+
       '<span class="dz-fbar"><span class="dz-ffill" style="'+(v>=0?'left:50%':'right:50%')+';width:'+bw+'%;background:'+bcol+'"></span>'+
       '<span style="position:absolute;left:50%;top:0;height:100%;width:1px;background:#3a3f4b"></span></span>'+
       '<span class="dz-fc" style="color:'+(ctr>=0?'var(--up)':'var(--dn)')+'">'+(ctr>=0?'+':'')+ctr.toFixed(1)+'</span></div>'}
  /* شرائح النظام: Risk-on/off · ضغط الدولار · التقلّب · الجلسة */
  const R=D.regime||{}, ro=String(R.risk_onoff||'').toLowerCase(),
        roTxt=(ro.includes('off'))?'🔴 Risk-OFF':(ro.includes('on')?'🟢 Risk-ON':'⚪ '+(ro||'—')),
        dp=R.dollar_pressure,
        dps=(typeof dp==='number')?(dp>0?'↑':(dp<0?'↓':'→')):(/up|صاعد|strong/i.test(String(dp||''))?'↑':(/down|هابط|weak/i.test(String(dp||''))?'↓':'→'));
  h+='<div class="dz-chips"><span class="dz-chip">'+esc(roTxt)+'</span>'+
     '<span class="dz-chip">ضغط الدولار '+dps+'</span>'+
     '<span class="dz-chip">التقلّب: '+esc(R.vol_state||'—')+'</span>'+
     '<span class="dz-chip">الجلسة: '+esc(R.session||'—')+'</span></div>';
  /* أقوى 5 رموز — نقرة = تبديل قائمة الرمز */
  const rank=Array.isArray(D.rank)?D.rank.slice(0,5):[];
  if(rank.length){h+='<div class="dz-sec">أقوى 5 رموز (انقر للانتقال):</div><div class="dz-rank">';
    for(const r of rank)h+='<span class="rank-chip" data-sym="'+esc(r.sym||'')+'" title="'+esc(r.read||'')+'">'+
      esc(r.sym||'')+' <b>'+Math.round(Number(r.score)||0)+'</b></span>';
    h+='</div>'}
  /* شريط الأرباح الحيّ لكلّ مجموعة + السبريد المدفوع + الرصيد */
  const P=D.pnl||{}, gr=P.groups||{}, gks=Object.keys(gr);
  if(gks.length){h+='<div class="dz-sec">أرباح/خسائر حيّة:</div>'+
    '<table class="dz-pnl"><tr><th>المجموعة</th><th>محقّق</th><th>WR</th><th>عائم</th><th>صفقات</th></tr>';
    for(const k of gks){const g=gr[k]||{}, wr=Number(g.win_rate!=null?g.win_rate:g.wr);
      h+='<tr><td>'+esc(GLBL[k]||k)+'</td><td>'+money(g.realized)+'</td>'+
         '<td>'+(Number.isFinite(wr)?((wr>1?wr:wr*100).toFixed(0)+'%'):'—')+'</td>'+
         '<td>'+money(g.floating)+'</td><td>'+(g.trades!=null?g.trades:'—')+'</td></tr>'}
    h+='</table>'}
  const AC=P.account||{};
  const _sp=P.spread_paid_today, _spv=(_sp&&typeof _sp==='object')?_sp.value:(_sp!=null?_sp:P.spread_paid_est);
  h+='<div class="dz-chips"><span class="dz-chip">سبريد مدفوع ≈ <b style="color:var(--dn)">'+(Number(_spv)||0).toFixed(2)+'</b></span>'+
     '<span class="dz-chip">Equity <b>'+(Number(AC.equity!=null?AC.equity:P.equity)||0).toFixed(2)+'</b></span>'+
     '<span class="dz-chip">هامش حرّ <b>'+(Number(AC.margin_free!=null?AC.margin_free:P.margin_free)||0).toFixed(2)+'</b></span></div>';
  h+='<p class="muted" style="margin:7px 0 0">'+esc(D.honesty||'⚖️ تجميعٌ شفّاف للقراءة البشريّة فقط — لا أفضليّة تنبّؤيّة مقاسة (~50% OOS)، لا يوصَل بأيّ مسار أوامر.')+'</p>';
  $('deskbody').innerHTML=h;
  for(const el of card.querySelectorAll('.rank-chip'))
    el.onclick=()=>{const s=el.getAttribute('data-sym'); if(!s)return;
      SYM=s; localStorage.setItem('pro_sym',SYM);
      const sel=$('symsel'); if(sel)sel.value=s;
      DATA=null; renderTop(); load()};
}
/* ─── 🧠 العقل العميق — DATA.deep_brain (قراءةٌ لحظيّة، لا إشارة) ─── */
function renderDeep(){
  const card=$('deepcard'); if(!card)return;
  const D=DATA&&DATA.deep_brain;
  if(!D){card.style.display='none';return}          /* غياب الملفّ ⇒ إخفاءٌ رشيق */
  card.style.display='';
  $('deepsym').textContent=D.sym||SYM;
  $('deepts').textContent=D.updated?('قبل '+anaAge(D.updated)):'';
  const call=String(D.call||D.bias||'—'),
        buy=/buy|شراء|صاعد|long/i.test(call), sell=/sell|بيع|هابط|short/i.test(call),
        col=buy?'var(--up)':(sell?'var(--dn)':'var(--dim)');
  let h='<div style="text-align:center;margin-bottom:8px"><span style="display:inline-block;padding:5px 26px;'+
    'border-radius:20px;font-weight:800;font-size:15px;background:'+col+'26;color:'+col+';border:1px solid '+col+'">'+
    esc(call)+'</span></div>';
  /* شريط ثقة score 0..1 */
  const sc=Math.max(0,Math.min(1,Number(D.score)||0)), scpc=(sc*100).toFixed(0);
  h+='<div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--dim);margin:2px 0">'+
     '<span>ثقة</span><span style="font-weight:700;color:'+col+'">'+scpc+'%</span></div>'+
     '<div style="height:11px;background:#0c0f14;border-radius:6px;overflow:hidden;direction:ltr">'+
     '<div style="height:100%;width:'+scpc+'%;background:'+col+';border-radius:6px"></div></div>';
  /* محاذاة HTF + الجلسة */
  const wh=D.with_htf, whTxt=(wh===true||/with|مع|align|موافق/i.test(String(wh)))?'🟢 مع الفريم الأعلى':
        ((wh===false||/against|عكس|ضد/i.test(String(wh)))?'🔴 عكس الفريم الأعلى':'⚪ '+(wh!=null?esc(String(wh)):'—'));
  const rows=[
    ['🧭 الانحياز', D.bias||'—'],
    ['📐 محاذاة HTF', D.align||'—'],
    ['🕐 الجلسة', D.session||'—']];
  h+='<div style="margin-top:8px">';
  for(const [k,v] of rows)
    h+='<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid #23262e;font-size:12px">'+
       '<span style="color:var(--dim)">'+k+'</span><span style="font-weight:600">'+esc(String(v))+'</span></div>';
  h+='</div>';
  h+='<div style="margin-top:7px;padding:6px 9px;border-radius:9px;background:'+col+'15;border:1px solid '+col+'40;'+
     'font-size:12px;color:'+col+'">'+whTxt+'</div>';
  $('deepbody').innerHTML=h;
}
/* ─── 🕸️ خريطة العقل الحيّة — DATA.brain_meta (إحصاء تحت iframe الخريطة D3) ─── */
function renderBrain(){
  const card=$('braincard'); if(!card)return;
  const B=DATA&&DATA.brain_meta;
  if(!B){card.style.display='none';return}           /* غياب الملفّ ⇒ إخفاءٌ رشيق */
  card.style.display='';
  $('braints').textContent=B.updated?('قبل '+anaAge(B.updated)):'';
  const nn=Number(B.n_nodes)||0, ne=Number(B.n_edges)||0;
  let h='<span style="color:var(--up)">'+nn+'</span> عقدة · '+
        '<span style="color:var(--cyan)">'+ne+'</span> سلك';
  const kinds=B.kinds;
  if(kinds&&typeof kinds==='object'){
    const ks=Array.isArray(kinds)?kinds:Object.keys(kinds).map(k=>k+':'+kinds[k]);
    if(ks.length)h+=' · '+esc(ks.join(' · '));
  }
  const hubs=Array.isArray(B.hubs)?B.hubs.slice(0,5):[];
  if(hubs.length){h+='<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">أقوى المحاور: ';
    for(const hb of hubs)h+='<span class="dz-chip" style="direction:ltr">'+esc(hb.name||'')+
      ' <b style="color:var(--gold)">'+(Number(hb.deg)||0)+'</b></span>';
    h+='</div>'}
  $('brainbody').innerHTML=h;
}

/* ─── لوحات الأُطُر الثلاثة ─── */
function buildTFCards(){
  const col=$('tfcol'); col.innerHTML='';
  for(const [k,lab] of TFS){
    const card=document.createElement('div');
    card.className='card tf-card'; card.id='card_'+k;
    if(k==='M4'){  // ⚡ لوحة M4 + شريط الشموع الحيّة D1/H4/H1 بجانبها (طلب المستخدم)
      card.innerHTML='<h2><span>'+lab+'</span><span class="zoom">⤢ تكبير</span></h2>'+
        '<div style="display:flex;gap:10px;align-items:stretch">'+
        '<svg id="svg_'+k+'" style="flex:1;min-width:0"></svg>'+
        '<div id="livecans" style="display:flex;flex-direction:column;gap:6px;width:118px;flex:none"></div></div>';
    } else {
      card.innerHTML='<h2><span>'+lab+'</span><span class="zoom">⤢ تكبير</span></h2><svg id="svg_'+k+'"></svg>';
    }
    card.querySelector('h2').onclick=()=>openOvl(k);
    col.append(card)}
}
/* ─── الشمعة الحيّة الكبيرة: آخر شمعة (تتكوّن الآن) لفريمٍ أعلى ─── */
function bigCandle(k,lab){
  const tf=tfObj(k); if(!tf||!tf.candles||!tf.candles.length)return '';
  const c=tf.candles[tf.candles.length-1], up=c.c>=c.o, col=up?'var(--up)':'var(--dn)';
  const rng=(c.h-c.l)||1e-9, W=110,H=118,pad=16;
  const Y=v=>pad+(c.h-v)/rng*(H-2*pad);
  const by=Y(Math.max(c.o,c.c)), bh=Math.max(2,Math.abs(Y(c.o)-Y(c.c)));
  const el=Math.min(100,Math.round(100*((Date.now()/1000)-(c.ts||0))/TFSEC[k]));   // نسبة اكتمال الشمعة
  const pct=((c.c-c.o)/(c.o||1)*100).toFixed(2);
  return '<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:4px 6px;text-align:center">'+
    '<div style="font-size:10px;color:#9aa3b2">'+lab+' <b style="color:'+col+'">'+(up?'+':'')+pct+'%</b></div>'+
    '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:'+H+'px">'+
    '<line x1="'+(W/2)+'" y1="'+Y(c.h)+'" x2="'+(W/2)+'" y2="'+Y(c.l)+'" stroke="'+col+'" stroke-width="2"/>'+
    '<rect x="'+(W/2-14)+'" y="'+by+'" width="28" height="'+bh+'" rx="2" fill="'+col+'"/>'+
    '<text x="'+(W/2+20)+'" y="'+(Y(c.h)+4)+'" fill="#9aa3b2" font-size="9">H '+fmt(c.h)+'</text>'+
    '<text x="'+(W/2+20)+'" y="'+(Y(c.l)+2)+'" fill="#9aa3b2" font-size="9">L '+fmt(c.l)+'</text>'+
    '<text x="4" y="'+(Y(c.o)+3)+'" fill="#7a8090" font-size="9">O</text>'+
    '<text x="4" y="'+(Y(c.c)+3)+'" fill="'+col+'" font-size="9">C</text></svg>'+
    '<div style="height:4px;background:#1a1f2b;border-radius:2px;overflow:hidden"><div style="height:100%;width:'+el+'%;background:linear-gradient(90deg,var(--gold),#f0a030)"></div></div>'+
    '<div style="font-size:9px;color:#7a8090;margin-top:2px">اكتملت '+el+'%</div></div>';
}
function renderTFs(){
  const hh=document.body.classList.contains('tv')?Math.max(210,Math.floor((window.innerHeight-170)/4)):242;
  for(const [k] of TFS){const tf=tfObj(k),svg=$('svg_'+k);
    if(!svg)continue;
    if(tf&&tf.candles&&tf.candles.length)drawCandles(svg,tf,{h:hh,tfk:k});
    else svg.innerHTML='<text x="20" y="30" fill="#7a8090" font-size="12">لا بيانات '+k+'</text>'}
  const lc=$('livecans');
  if(lc)lc.innerHTML=bigCandle('D1','اليوم')+bigCandle('H4','4س')+bigCandle('H1','1س');
}

/* ─── التكبير ملء الشاشة ─── */
function openOvl(k){OVLTF=k;$('ovl').style.display='block';
  const lab=(TFS.find(t=>t[0]===k)||[k,k])[1];
  $('ovltitle').textContent=lab+' — '+SYM;renderOvl()}
function renderOvl(){ if(!OVLTF)return; const tf=tfObj(OVLTF);
  if(tf&&tf.candles)drawCandles($('ovlsvg'),tf,{w:$('ovlsvg').clientWidth||1200,h:$('ovlsvg').parentElement.clientHeight||620,tfk:OVLTF})}
function closeOvl(){OVLTF=null;$('ovl').style.display='none';$('tip').style.display='none'}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeOvl();
  if(document.body.classList.contains('tv')){document.body.classList.remove('tv');renderTFs()}}});
/* 🖥️ وضع TV */
$('tvbtn').onclick=()=>{document.body.classList.toggle('tv');renderTFs()};
/* 🎯 مفتاح الخطط الآليّة — يظهر افتراضيّاً ويُحفظ في localStorage */
function planBtnUI(){const b=$('planbtn'); if(b)b.style.opacity=PLANON?'1':'.4'}
$('planbtn').onclick=()=>{PLANON=!PLANON;localStorage.setItem('pro_plan',PLANON?'1':'0');
  planBtnUI();renderTFs();if(OVLTF)renderOvl()};
planBtnUI();

/* ─── الرأس والحالة ─── */
function renderTop(){
  const d=DATA||{};
  const tf1=tfObj('H1'),last=(Number.isFinite(d.price)?d.price:(tf1&&tf1.candles&&tf1.candles.length?tf1.candles[tf1.candles.length-1].c:null));
  $('price').textContent=last!=null?fmt(last):'—';
  const S1=tf1?smcOf(tf1):null;
  $('smcsum').textContent=(S1&&S1.summary)?S1.summary:'—';
  const fresh=(Date.now()-lastOK)<12000&&!(d&&d.error);
  $('dot').style.background=fresh?'var(--up)':'var(--dn)';
  $('dot').title=fresh?'حيّ':'قديم/منقطع';
  const e=$('err');
  if(d&&d.error){e.style.display='block';e.textContent='خطأ من الخادم: '+d.error}else e.style.display='none';
}

/* ─── قائمة الرموز ─── */
function buildSymSel(){
  const sel=$('symsel'),list=(DATA&&Array.isArray(DATA.symbols)&&DATA.symbols.length)
    ?DATA.symbols.map(s=>Array.isArray(s)?s:[s.sym||s,s.label||s.sym||s]):FALLBACK_SYMS;
  const cur=sel.value; sel.innerHTML='';
  for(const [s,lab] of list){const o=document.createElement('option');o.value=s;o.textContent=lab+' · '+s;sel.append(o)}
  sel.value=list.some(x=>x[0]===SYM)?SYM:list[0][0]; if(cur!==sel.value&&cur)sel.value=SYM;
}
$('symsel').addEventListener('change',ev=>{SYM=ev.target.value;localStorage.setItem('pro_sym',SYM);DATA=null;renderTop();load()});

/* ─── تطبيع الشموع: المحرّك يصدّر مصفوفات [[t,o,h,l,c,v]] والرسّام يقرأ كائنات {t,o,h,l,c} ─── */
function fmtT(ts,tfk){const d=new Date(ts*1000),p=n=>String(n).padStart(2,'0');
  return tfk==='D1'?(p(d.getMonth()+1)+'-'+p(d.getDate())):(p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes()))}
function normData(d){ if(!d||!d.tfs)return d;
  for(const k in d.tfs){const tf=d.tfs[k]; if(tf&&Array.isArray(tf.candles)&&tf.candles.length&&Array.isArray(tf.candles[0]))
      tf.candles=tf.candles.map(a=>({ts:a[0],t:fmtT(a[0],k),o:a[1],h:a[2],l:a[3],c:a[4],v:a[5]}))}
  return d }
/* ═══ 🕐 شريط الأخبار: عدّادات حيّة كلّ ثانية + نبض <10د + وميض <1د + إنذار T-60 صوتيّ ═══ */
let NEWSEV=[],T60FIRED=new Set(),NBSIG='';
function buildNewsBar(){
  const bar=$('newsbar'); if(!bar)return;
  NEWSEV=((DATA&&DATA.news_events)||[]).map(e=>({t:Number(e.epoch!=null?e.epoch:(e.ts!=null?e.ts:e.time)),
      title:String(e.title||''),imp:String(e.impact||''),cur:String(e.currency||'')}))
    .filter(e=>Number.isFinite(e.t)&&e.t>Date.now()/1000-300).sort((a,b)=>a.t-b.t).slice(0,10);
  if(!NEWSEV.length){bar.style.display='none';NBSIG='';return}
  const sig=JSON.stringify(NEWSEV); if(sig===NBSIG){bar.style.display='flex';return} NBSIG=sig;
  bar.style.display='flex'; let h='';
  for(const e of NEWSEV){const hi=/high|عال/i.test(e.imp);
    h+='<span class="nchip">'+(hi?'🔴':'🟠')+' '+esc(e.cur)+' '+esc(e.title.slice(0,34))+' <b data-ep="'+e.t+'">—</b></span>'}
  bar.innerHTML=h; tickNews();
  for(const el of bar.querySelectorAll('.nchip'))el.onclick=()=>{const c=$('card_H1');
    if(c){c.scrollIntoView({behavior:'smooth',block:'center'});
      c.style.borderColor='var(--gold)';setTimeout(()=>{c.style.borderColor=''},1600)}};
}
function tickNews(){
  const now=Date.now()/1000,p=x=>String(x).padStart(2,'0');
  for(const el of document.querySelectorAll('#newsbar b[data-ep]')){
    const t=Number(el.getAttribute('data-ep')),s=t-now,chip=el.parentElement;
    if(s<=0){el.textContent='الآن!';chip.classList.add('now');continue}
    el.textContent='بعد '+p(Math.floor(s/3600))+':'+p(Math.floor(s%3600/60))+':'+p(Math.floor(s%60));
    chip.classList.toggle('soon',s<600); chip.classList.toggle('now',s<60);
    if(s<60&&!T60FIRED.has(t)){T60FIRED.add(t);beep(1)}  /* إنذار T-60: ثلاثيّ عاجل */
  }
}
/* ═══ 📈 حقوق الملكيّة اليوم — Sparkline بتعبئة متدرّجة + رقم P&L ═══ */
function renderEquity(){
  const card=$('eqcard'),E=(DATA&&DATA.equity_curve)||[]; if(!card)return;
  if(!Array.isArray(E)||E.length<2){card.style.display='none';return}
  card.style.display='';
  const svg=$('eqsvg'),W=svg.clientWidth||480,H=70,mg=6;
  svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.setAttribute('height',H);
  let lo=Infinity,hi=-Infinity; for(const q of E){const v=Number(q[1]);if(v<lo)lo=v;if(v>hi)hi=v}
  const pd=(hi-lo)*.1||1; lo-=pd; hi+=pd;
  const X2=i=>mg+i*(W-2*mg)/Math.max(E.length-1,1), Y2=v=>mg+(hi-v)/(hi-lo)*(H-2*mg);
  const pnl=Number(E[E.length-1][1])-Number(E[0][1]), col=pnl>=0?'#26a67a':'#e05a5a';
  let pts='',area='M '+X2(0)+' '+(H-mg);
  for(let i=0;i<E.length;i++){const x=X2(i),y=Y2(Number(E[i][1]));pts+=x+','+y+' ';area+=' L '+x+' '+y}
  area+=' L '+X2(E.length-1)+' '+(H-mg)+' Z';
  svg.innerHTML='<defs><linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1">'+
    '<stop offset="0%" stop-color="'+col+'" stop-opacity=".4"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+
    '<path d="'+area+'" fill="url(#eqg)"/><polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="1.6"/>';
  $('eqpnl').innerHTML='<span style="direction:ltr;display:inline-block;color:'+col+'">'+(pnl>=0?'+':'')+pnl.toFixed(2)+' $</span>';
}
/* ═══ 📢 البثّ الموحّد + 🔊 Web Audio (نغمتان للجديد · ثلاثيّ عاجل لإنذار خبر) ═══ */
const FICON={gold_sentinel:'🔔',sentinel:'🔔',market_pulse:'🫀',pulse:'🫀',quant_desk:'🧮',desk:'🧮',news_alarm:'📰',news:'📰'};
let FSEEN=new Set(),SND=localStorage.getItem('pro_snd')==='1',AC=null;
function beep(urgent){ if(!SND)return;
  try{ AC=AC||new (window.AudioContext||window.webkitAudioContext)();
    const seq=urgent?[[880,0],[660,.15],[880,.3]]:[[660,0],[880,.12]];
    for(const [f,dt] of seq){const o=AC.createOscillator(),gn=AC.createGain();
      o.frequency.value=f;o.type='sine';o.connect(gn);gn.connect(AC.destination);
      const t=AC.currentTime+dt; gn.gain.setValueAtTime(.001,t);
      gn.gain.exponentialRampToValueAtTime(.18,t+.02); gn.gain.exponentialRampToValueAtTime(.001,t+.11);
      o.start(t); o.stop(t+.13)}
  }catch(e){}}
$('sndbtn').textContent=SND?'🔊':'🔇';
$('sndbtn').onclick=()=>{SND=!SND;localStorage.setItem('pro_snd',SND?'1':'0');
  $('sndbtn').textContent=SND?'🔊':'🔇'; if(SND)beep(0)};
function renderFeed(){
  const card=$('feedcard'),F=(DATA&&DATA.feeds)||[]; if(!card)return;
  if(!Array.isArray(F)||!F.length){card.style.display='none';return}
  card.style.display='';
  const key=it=>(it.src||'')+'|'+(it.ts||'')+'|'+String(it.text||'').slice(0,40);
  let fresh=0,urgent=0,h='';
  for(const it of F){const nw=FSEEN.size>0&&!FSEEN.has(key(it));
    if(nw){fresh++; if(/news/i.test(String(it.src||''))&&/T-?60|60 ?ثانية|إنذار|alarm/i.test(String(it.text||'')))urgent++}
    h+='<div class="feed-it'+(nw?' feed-new':'')+'"><span>'+(FICON[it.src]||'📌')+'</span>'+
       '<span style="flex:1">'+esc(String(it.text||'').slice(0,150))+'</span>'+
       '<span class="ft">'+esc(String(it.iso||'').slice(11,19))+'</span></div>'}
  const had=FSEEN.size; FSEEN=new Set(F.map(key));
  $('feedlist').innerHTML=h;
  if(had&&fresh)beep(urgent?1:0);
}
/* ─── الجلب والتحديث كل 3 ثوانٍ (إعادة رسم في المكان — بلا وميض) ─── */
async function load(){
  try{const r=await fetch('/pro/data?sym='+encodeURIComponent(SYM));
    const d=await r.json(); DATA=normData(d); if(!d.error)lastOK=Date.now();
  }catch(e){/* نُبقي آخر بيانات ونعلّم النقطة حمراء */}
  buildSymSel(); renderTop(); renderIndex(); renderUnified(); renderMTF(); renderDesk(); renderDeep(); renderBrain(); renderTFs();
  buildNewsBar(); renderEquity(); renderFeed(); renderCouncil(); if(OVLTF)renderOvl();
}
/* ═══ 🏛️ مجلس العقول المحليّ (Ollama $0) — يأتي مضمّناً في DATA.council ═══ */
const CNROLES=[['eyes','👁️ العيون'],['analyst','🧠 المحلّل'],['critic','🗡️ الناقد'],['judge','⚖️ الحكم'],
               ['ops','🔧 المهندس'],['runner','⚡ العدّاء'],['tagger','🏷️ المصنّف']];
let CNBUSY=false, CNLAST=0;
function renderCouncil(){
  const card=$('cncard'); if(!card)return;
  const C=DATA&&DATA.council;
  if(!C||!C.ts){card.style.display='none';return}
  card.style.display='';
  const ag=C.agreement;
  $('cnagree').textContent=(ag!=null?('اتفاق '+ag+'/100'):'اتفاق —');
  $('cnagree').style.color=(ag==null?'':(ag>=70?'var(--up)':(ag>=45?'var(--gold)':'var(--dn)')));
  $('cnage').textContent='قبل '+anaAge(C.ts)+' · '+(C.round_seconds||'—')+'ث';
  $('cnverdict').innerHTML='<b style="color:var(--gold)">حكم المجلس:</b> '+esc(C.verdict||'').replace(/\n/g,'<br>');
  const R=C.roles||{}; let h='';
  for(const [k,lab] of CNROLES){const r=R[k]; if(!r)continue;
    const body=r.error?('<span style="color:var(--dn)">'+esc(r.error)+'</span>'):esc(r.text||'').replace(/\n/g,'<br>');
    const xtra=r.cross_check?(' <span class="pill" style="font-size:9px;padding:1px 6px">'+esc(r.cross_check)+'</span>'):'';
    h+='<details style="margin:4px 0;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:9px;padding:5px 9px">'+
       '<summary style="cursor:pointer;font-size:12px">'+lab+xtra+
       ' <span class="muted" style="font-size:10px">'+esc(r.model||'')+' · '+(r.seconds||0)+'ث</span></summary>'+
       '<div style="font-size:11.5px;line-height:1.8;padding:5px 2px">'+body+'</div></details>'}
  $('cnroles').innerHTML=h;
  $('cnhonesty').textContent=C.honesty||'';
  if(CNBUSY&&C.ts>CNLAST){CNBUSY=false;const b=$('cnbtn');b.disabled=false;b.textContent='⚡ اجتماع الآن'}
}
$('cnbtn').onclick=async function(){
  const b=$('cnbtn'); CNLAST=(DATA&&DATA.council&&DATA.council.ts)||0; CNBUSY=true;
  b.disabled=true; b.innerHTML='<span class="ana-spin">⏳</span> يجتمعون…';
  try{await fetch('/council/refresh',{method:'POST'})}catch(e){}
  setTimeout(()=>{if(CNBUSY){CNBUSY=false;b.disabled=false;b.textContent='⚡ اجتماع الآن'}},420000);
};
/* ═══ 🤖 محلّل Fable — /analyst/data + «حلّل الآن» + «اسأل الشارت» ═══ */
let ANA=null,ANAPOLL=null,ANATHREAD=[];   // آخر تقرير · مؤقّت الاستقصاء · خيط الأسئلة (آخر 6)
function anaAge(ts){const s=Math.max(0,Date.now()/1000-Number(ts)||0);
  return s<90?Math.round(s)+' ث':(s<5400?Math.round(s/60)+' د':(s/3600).toFixed(1)+' س')}
/* ماركداون خفيف: **غامق** + سطرٌ يبدأ برمز تعبيريّ = رأس فقرة جديد */
const ANAEMO=/^\s*[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/u;
function anaMd(txt){const out=[];
  for(const ln of String(txt||'').split('\n')){ if(!ln.trim())continue;
    const h=esc(ln).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
    out.push(ANAEMO.test(ln)?'<div class="ana-sec">'+h+'</div>':'<div>'+h+'</div>')}
  return out.join('')}
function renderAna(){
  const card=$('anacard'); if(!card)return;
  if(!ANA||!ANA.ts){card.style.display='none';return}   // لا تقرير بعد ⇒ إخفاءٌ رشيق
  card.style.display='';
  $('anamodel').textContent=ANA.model||'fable';
  $('anaage').textContent='قبل '+anaAge(ANA.ts);
  const N=(Array.isArray(ANA.news)?ANA.news:[]).slice()
    .sort((a,b)=>(Number.isFinite(a.hours_to)?a.hours_to:99)-(Number.isFinite(b.hours_to)?b.hours_to:99));
  let nh='';
  for(const e of N){const hi=/high|عال/i.test(String(e.impact||''));
    nh+='<span class="ana-chip '+(hi?'ana-hi':'ana-md')+'">'+(hi?'🔴':'🟠')+' '+esc(e.title||'')+
        (Number.isFinite(e.hours_to)?' بعد '+Number(e.hours_to).toFixed(1)+'س':(e.time_str?' '+esc(e.time_str):''))+'</span>'}
  $('ananews').innerHTML=nh||'<span class="muted">لا أخبار عالية الأثر قريبة</span>';
  $('anabody').innerHTML=anaMd(ANA.report);
}
async function loadAna(){
  try{const r=await fetch('/analyst/data'); if(!r.ok)throw new Error('http');
    const d=await r.json(); if(d&&d.ts)ANA=d;
  }catch(e){/* نُبقي آخر تقرير؛ إن لم يوجد أيّ تقرير تبقى البطاقة مخفيّة */}
  renderAna()}
/* زرّ «⚡ حلّل الآن»: POST /analyst/refresh ثم استقصاء كلّ 5 ثوانٍ حتى يتغيّر ts (حدّ 150ث) */
$('anabtn').onclick=async function(){
  const btn=$('anabtn'), old=(ANA&&ANA.ts)||0;
  btn.disabled=true; btn.innerHTML='<span class="ana-spin">⏳</span> يُحلّل…';
  try{await fetch('/analyst/refresh',{method:'POST'})}catch(e){}
  const t0=Date.now(); clearInterval(ANAPOLL);
  ANAPOLL=setInterval(async()=>{ await loadAna();
    if((ANA&&ANA.ts>old)||(Date.now()-t0>150000)){
      clearInterval(ANAPOLL); ANAPOLL=null; btn.disabled=false; btn.textContent='⚡ حلّل الآن'}},5000);
};
/* «اسأل الشارت»: POST /analyst/ask {q} — فقاعات Q/A (آخر 6) · مهلة 90ث برسالة رقيقة */
function renderThread(){let h='';
  for(const m of ANATHREAD)h+='<div class="ana-bub '+(m.q?'ana-q':'ana-a')+'">'+anaMd(m.t)+'</div>';
  $('anathread').innerHTML=h}
async function anaAsk(){
  const inp=$('anaq'), q=inp.value.trim(); if(!q||inp.disabled)return;
  inp.disabled=true; $('anasend').disabled=true;
  ANATHREAD.push({q:1,t:q}); ANATHREAD=ANATHREAD.slice(-6); renderThread(); inp.value='';
  try{const ctl=new AbortController(), tm=setTimeout(()=>ctl.abort(),90000);
    const r=await fetch('/analyst/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({q:q}),signal:ctl.signal});
    clearTimeout(tm); const d=await r.json();
    ANATHREAD.push({q:0,t:(d&&d.answer)?d.answer:'لا إجابة من المحلّل.'});
  }catch(e){ANATHREAD.push({q:0,t:'⚠️ تعذّر الوصول للمحلّل الآن — حاول بعد قليل.'})}
  ANATHREAD=ANATHREAD.slice(-6); renderThread();
  inp.disabled=false; $('anasend').disabled=false; inp.focus();
}
$('anasend').onclick=anaAsk;
$('anaq').addEventListener('keydown',e=>{if(e.key==='Enter')anaAsk()});

setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-GB');tickNews()},1000);
buildTFCards(); buildSymSel(); load(); setInterval(load,3000);
loadAna(); setInterval(loadAna,10000);
window.addEventListener('resize',()=>{clearTimeout(window.__rz);window.__rz=setTimeout(()=>{renderIndex();renderTFs();if(OVLTF)renderOvl()},250)});
</script></body></html>"""
