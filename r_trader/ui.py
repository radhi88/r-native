# -*- coding: utf-8 -*-
"""R Trader — صدفة الواجهة الموحّدة (SHELL_HTML).

صفحة RTL عربية داكنة تُقدَّم على "/" من بوّابة :8020:
- شريط علويّ ثابت: شعار «R Trader 👑» + تبويبات (الرئيسية/القمرة/الحيّ/الخريطة/FRIDAY) + ساعة حيّة.
- ثلاثة iframes كسولة (/pro و /live و /map) تُنشأ عند أوّل فتح — إظهار/إخفاء بلا إعادة تحميل.
- تبويب الرئيسية: بطاقات تُحدَّث كل 3 ثوانٍ من /live/data و /api/status (عبر البوّابة نفسها).
- تبويب FRIDAY: قائمة المحرّكات من /api/engines + حالة الحساب من /api/status.
- ⚙️ لوحة تحكّم المحرّكات (الرئيسية): قائمة /rt/engines كل 10ث + أوامر start/stop/restart
  برأس X-RT-Token (التوكن من /rt/token، متاح محليّاً فقط — عبر النفق تنحدر اللوحة
  إلى «عرض فقط (عن بُعد)»). إيقاف/إعادة تتطلّبان نقرة تأكيد ثانية خلال 4 ثوانٍ.
- دفاعيّ: أيّ fetch يفشل ⇒ بطاقته تعرض «غير متاح» ولا تكسر البقيّة.
- بلا مكتبات خارجية إطلاقاً (CSP النفق) — خطّ system-ui فقط.
⚖️ الصدق: لا تُصدِر أيّ أمر تداول — التحكّم الوحيد هو تشغيل/إيقاف عمليّات الطاقم
عبر توكن محليّ (قائمة الخادم البيضاء هي الحَكَم النهائيّ).
"""

SHELL_HTML = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>R Trader 👑</title>
<style>
/* ── متغيّرات الثيم (داكن افتراضيّ) — توحيد بصريّ كامل ── */
:root{
 --bg:#0b0d12; --bar:#0e1118; --card:#12151c; --card2:#161a23; --line:#232833; --line2:#1c202a;
 --line3:#2a3240; --pill:#1c2230; --pillbar:#1a1e27; --txt:#e6e9ef; --txt2:#9aa3b2; --dim:#7a828f;
 --dim2:#5a6270; --gold:#f5c518; --green:#3ddc84; --red:#ff5c6c;
 --sec-bg:#1a3a24; --sec-fg:#3ddc84; --kill-bg:#3a1a1e; --kill-fg:#ff5c6c;
 --badge-on-bd:#1a3a24; --badge-on-bg:#12241a;
 --radius:12px; --radius-sm:9px; --shadow:0 1px 3px rgba(0,0,0,.35); --ease:.2s ease;
}
:root[data-theme="light"]{
 --bg:#f4f6fa; --bar:#ffffff; --card:#ffffff; --card2:#eef1f6; --line:#dbe0ea; --line2:#e6eaf1;
 --line3:#cbd3e0; --pill:#eef1f6; --pillbar:#e2e7f0; --txt:#1a2230; --txt2:#4a5568; --dim:#6b7688;
 --dim2:#8b96a8; --gold:#b8860b; --green:#1a9c5b; --red:#d64550;
 --sec-bg:#d6f2e0; --sec-fg:#1a7c47; --kill-bg:#fbe0e2; --kill-fg:#c0323c;
 --badge-on-bd:#b8e6c8; --badge-on-bg:#e2f6ea;
 --shadow:0 1px 3px rgba(20,30,50,.10);
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{background:var(--bg);color:var(--txt);font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
 overflow:hidden;transition:background var(--ease),color var(--ease)}
/* ── الشريط العلويّ الثابت ── */
#topbar{position:fixed;top:0;right:0;left:0;height:52px;z-index:50;display:flex;align-items:center;
 gap:10px;padding:0 12px;background:var(--bar);border-bottom:1px solid var(--line);transition:background var(--ease),border-color var(--ease)}
#logo{font-size:17px;font-weight:800;color:var(--gold);white-space:nowrap;letter-spacing:.3px}
#logo .ver{font-size:10px;color:var(--dim);font-weight:400;margin-right:5px}
#tabs{display:flex;gap:4px;flex:1;overflow-x:auto;scrollbar-width:none}
#tabs::-webkit-scrollbar{display:none}
.tab{flex-shrink:0;border:1px solid transparent;background:transparent;color:var(--txt2);font:inherit;
 font-size:13px;padding:6px 12px;border-radius:var(--radius-sm);cursor:pointer;white-space:nowrap;transition:all var(--ease)}
.tab:hover{color:var(--txt);background:var(--card2)}
.tab.active{background:var(--pill);color:var(--gold);border-color:var(--line3);font-weight:700}
#clock{font-variant-numeric:tabular-nums;direction:ltr;font-size:13px;color:var(--txt2);white-space:nowrap}
/* أزرار الأدوات (كتم/ثيم) */
.tool{flex-shrink:0;width:32px;height:32px;display:flex;align-items:center;justify-content:center;
 border:1px solid var(--line3);background:var(--pill);color:var(--txt2);font-size:15px;line-height:1;
 border-radius:var(--radius-sm);cursor:pointer;transition:all var(--ease)}
.tool:hover{border-color:var(--gold);color:var(--gold)}
.tool.off{opacity:.5}
/* ── اللوحات ── */
.panel{position:fixed;top:52px;bottom:0;right:0;left:0;overflow-y:auto;padding:12px;display:none}
.panel.active{display:block}
#frames{position:fixed;top:52px;bottom:0;right:0;left:0;display:none;background:var(--bg)}
#frames.active{display:block}
#frames iframe{width:100%;height:100%;border:0;display:none;background:var(--bg)}
#frames iframe.active{display:block}
/* ── شبكة البطاقات (جوّال-أولاً) ── */
.grid{display:grid;grid-template-columns:1fr;gap:10px;max-width:1100px;margin:0 auto}
@media(min-width:720px){.grid{grid-template-columns:1fr 1fr}}
@media(min-width:1080px){.grid{grid-template-columns:1fr 1fr 1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:12px;
 min-width:0;box-shadow:var(--shadow);transition:background var(--ease),border-color var(--ease)}
.card.wide{grid-column:1/-1}
.h2{font-size:13px;color:var(--txt2);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.up{color:var(--green)}.dn{color:var(--red)}.dim{color:var(--dim)}.gold{color:var(--gold)}
.na{color:var(--dim);font-size:13px}
/* بطاقة الحساب */
#eq{font-size:34px;font-weight:800;line-height:1.2}
#accsub{font-size:12px;color:var(--dim);margin-top:4px}
#accexec{font-size:12px;color:var(--txt2);margin-top:6px}
/* أشرطة المجلس (كما في /live) */
.crow{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line2);font-size:13px}
.crow:first-child{border-top:0}
.csym{width:72px;font-weight:700;flex-shrink:0}
.cbar{flex:1;height:18px;background:var(--pillbar);border-radius:5px;position:relative;overflow:hidden}
.cfill{position:absolute;top:0;bottom:0;border-radius:5px;opacity:.85;transition:width var(--ease)}
.cpct{width:44px;text-align:left;direction:ltr;font-weight:700;flex-shrink:0}
.tradeable{box-shadow:0 0 0 1px var(--green) inset;border-radius:7px;padding-right:4px;padding-left:4px}
/* 🆕 خطّ عتبة 75% على شريط الإجماع (المقياس 0-100% فعليّاً ⇒ left:75% مباشرةً، لا صيغة 65%) */
.cthr{position:absolute;top:0;bottom:0;left:75%;width:2px;background:rgba(255,255,255,.4);pointer-events:none;z-index:2}
/* 🆕 بطاقة المسافة فوق أرضيّة master_floor (الحاجز الوحيد الآن) — بدل «مخاطرة —% رضا —%» الفارغة */
#rt-risk-card{margin-top:8px;padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.08);font-size:12.5px;display:flex;align-items:center;gap:10px}
#rt-risk-bar{flex:1;height:8px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden}
#rt-risk-fill{height:100%;width:0;transition:width .4s ease,background .4s ease;border-radius:6px}
#rt-risk-lbl{white-space:nowrap;opacity:.92;font-variant-numeric:tabular-nums}
/* 🆕 فلاتر صفقات اليوم (الكل/رابح/خاسر) */
#rt-trade-tools{display:flex;gap:6px;margin:0 0 6px;flex-wrap:wrap}
#rt-trade-tools button{font:11px Tahoma,Arial,sans-serif;padding:3px 11px;border-radius:14px;cursor:pointer;
  border:1px solid var(--line3);background:transparent;color:inherit;opacity:.6}
#rt-trade-tools button.on{opacity:1;background:var(--pill)}
.trow.rt-hidden{display:none}
/* الصفقات */
.prow{padding:7px 0;border-top:1px solid var(--line2);font-size:13px}
.prow:first-child{border-top:0}
.phead{display:flex;justify-content:space-between;gap:8px}
.pplan{font-size:11px;color:var(--dim);margin-top:2px}
.chip{font-size:10px;padding:1px 7px;border-radius:20px;background:var(--pill);color:var(--txt2)}
.chip.sec{background:var(--sec-bg);color:var(--sec-fg)}
.chip.kill{background:var(--kill-bg);color:var(--kill-fg);font-weight:700}
/* المحرّكات */
#engnum{font-size:28px;font-weight:800}
.badges{display:flex;flex-wrap:wrap;gap:6px}
.badge{font-size:12px;padding:4px 10px;border-radius:20px;border:1px solid var(--line);background:var(--card2);
 color:var(--dim);transition:all var(--ease)}
.badge.on{border-color:var(--badge-on-bd);background:var(--badge-on-bg);color:var(--green);font-weight:700}
/* روابط سريعة */
.links{display:flex;flex-wrap:wrap;gap:8px}
.lbtn{border:1px solid var(--line3);background:var(--pill);color:var(--txt);font:inherit;font-size:13px;
 padding:8px 14px;border-radius:var(--radius-sm);cursor:pointer;transition:all var(--ease)}
.lbtn:hover{border-color:var(--gold);color:var(--gold)}
.foot{text-align:center;font-size:11px;color:var(--dim2);margin-top:12px}
/* ── 🔔 نظام الإشعارات (toast) أعلى-يسار ── */
#toasts{position:fixed;top:60px;left:12px;z-index:200;display:flex;flex-direction:column;gap:8px;
 max-width:min(320px,80vw);pointer-events:none}
.toast{pointer-events:auto;background:var(--card);border:1px solid var(--line3);border-right:3px solid var(--txt2);
 border-radius:var(--radius);padding:10px 12px;font-size:13px;color:var(--txt);box-shadow:0 6px 20px rgba(0,0,0,.35);
 opacity:0;transform:translateX(-14px);transition:opacity var(--ease),transform var(--ease);direction:rtl;line-height:1.45}
.toast.show{opacity:1;transform:translateX(0)}
.toast.ok{border-right-color:var(--green)}
.toast.up{border-right-color:var(--gold)}
.toast.dn{border-right-color:var(--red)}
/* ── 🧠 سبورة المخّ الواحد (جدول المحرّكات المقيسة) ── */
.sbscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -2px}
table.sb{width:100%;border-collapse:collapse;font-size:12.5px;min-width:560px}
table.sb th{text-align:right;color:var(--dim);font-weight:600;font-size:11px;padding:5px 8px;
 border-bottom:1px solid var(--line);white-space:nowrap}
table.sb th.n,table.sb td.n{text-align:left;direction:ltr;font-variant-numeric:tabular-nums}
table.sb td{padding:7px 8px;border-top:1px solid var(--line2);white-space:nowrap;vertical-align:middle}
table.sb tr.win td{background:linear-gradient(90deg,rgba(61,220,132,.06),transparent 60%)}
table.sb tr.win td:first-child{box-shadow:inset 3px 0 0 var(--green)}
table.sb tr.ret td{opacity:.5}
table.sb tr:hover td{background:var(--card2)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex-shrink:0;vertical-align:middle;
 margin-left:2px;box-shadow:0 0 0 2px rgba(255,255,255,.03)}
.dot.win{background:var(--green);box-shadow:0 0 6px rgba(61,220,132,.6)}
.dot.ret{background:var(--red);opacity:.55}
.dot.watch{background:var(--gold);box-shadow:0 0 6px rgba(245,197,24,.5)}
.engname{font-weight:700;color:var(--txt)}
.engmagic{font-size:10px;color:var(--dim2);direction:ltr;margin-right:5px}
.chip.ret{background:var(--kill-bg);color:var(--kill-fg);font-weight:700}
.chip.win{background:var(--sec-bg);color:var(--sec-fg);font-weight:700}
.openbadge{font-size:10px;padding:1px 6px;border-radius:20px;background:var(--pill);
 color:var(--gold);font-weight:700;border:1px solid var(--line3);margin-right:4px}
/* م.ربح/م.خسارة: سطران صغيران متراصّان (أخضر فوق أحمر) */
.wl{display:inline-block;font-size:11px;line-height:1.35;direction:ltr;text-align:left;
 font-variant-numeric:tabular-nums}
.wl .w{display:block;color:var(--green)}
.wl .l{display:block;color:var(--red)}
/* حبّة العائد (payoff): أخضر ≥1، ذهبيّ 0.5–1، أحمر <0.5، ∞ بلا خسائر */
.po{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 8px;border-radius:20px;
 direction:ltr;font-variant-numeric:tabular-nums}
.po.good{background:var(--sec-bg);color:var(--sec-fg)}
.po.mid{background:var(--pill);color:var(--gold);border:1px solid var(--line3)}
.po.bad{background:var(--kill-bg);color:var(--kill-fg)}
.po.inf{background:var(--pill);color:var(--txt2);border:1px solid var(--line2)}
/* ── 📈 منحنى الحقوق (SVG سطر-داخليّ) ── */
.spark-wrap{position:relative;width:100%;height:60px}
.spark-wrap svg{display:block;width:100%;height:60px;overflow:visible}
.spark-last{position:absolute;top:2px;left:2px;font-size:12px;font-weight:800;color:var(--gold);
 direction:ltr;background:var(--card);padding:1px 6px;border-radius:6px;border:1px solid var(--line3)}
.spark-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--dim);margin-top:6px;direction:ltr}
/* ── 🧾 صفقات اليوم (قائمة قابلة للتمرير) ── */
.tlist{max-height:180px;overflow-y:auto;-webkit-overflow-scrolling:touch;margin:0 -2px}
.trow{display:flex;align-items:center;gap:8px;padding:6px 6px;border-top:1px solid var(--line2);font-size:12.5px}
.trow:first-child{border-top:0}
.ttime{color:var(--dim);font-size:11px;direction:ltr;width:56px;flex-shrink:0;font-variant-numeric:tabular-nums}
.tdir{font-size:10px;padding:1px 8px;border-radius:20px;font-weight:700;flex-shrink:0}
.tdir.buy{background:var(--sec-bg);color:var(--sec-fg)}
.tdir.sell{background:var(--kill-bg);color:var(--kill-fg)}
.tsym{font-weight:700;flex-shrink:0}
.teng{color:var(--dim);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tnet{direction:ltr;font-variant-numeric:tabular-nums;font-weight:700;flex-shrink:0}
/* ── ⚙️ لوحة تحكّم المحرّكات (بطاقة الرئيسية) ── */
#engpanel{margin-top:8px;max-height:280px;overflow-y:auto;-webkit-overflow-scrolling:touch}
.erow{display:flex;align-items:center;gap:7px;padding:5px 2px;border-top:1px solid var(--line2);font-size:12.5px}
.erow:first-child{border-top:0}
.edot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.edot.alive{background:var(--green);animation:epulse 2s ease-out infinite}
.edot.dead{background:var(--red);opacity:.75}
@keyframes epulse{0%{box-shadow:0 0 0 0 rgba(61,220,132,.55)}70%{box-shadow:0 0 0 6px rgba(61,220,132,0)}
 100%{box-shadow:0 0 0 0 rgba(61,220,132,0)}}
.ename{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.eprocs{font-size:10px;color:var(--dim);direction:ltr;flex-shrink:0}
.ebtn{flex-shrink:0;border:1px solid var(--line3);background:var(--pill);color:var(--txt2);font:inherit;
 font-size:11px;line-height:1.3;padding:3px 8px;border-radius:var(--radius-sm);cursor:pointer;
 white-space:nowrap;transition:all var(--ease)}
.ebtn:hover{border-color:var(--gold);color:var(--gold)}
.ebtn.go{color:var(--sec-fg);border-color:var(--badge-on-bd);background:var(--badge-on-bg)}
.ebtn.crit{color:var(--kill-fg);border-color:var(--kill-bg)}
.ebtn.confirm,.ebtn.confirm:hover{background:var(--kill-bg);color:var(--kill-fg);
 border-color:var(--kill-fg);font-weight:700}
.romode{font-size:10px;padding:2px 8px;border-radius:20px;background:var(--pill);color:var(--dim);
 border:1px solid var(--line2);white-space:nowrap}
/* ── 🖐️🛑 شريط إنذار حرس اليد (ثابت تحت الشريط العلويّ، أحمر نابض) ── */
#handalert{position:fixed;top:52px;right:0;left:0;z-index:60;display:none;padding:9px 14px;
 text-align:center;font-size:14px;font-weight:800;color:#fff;
 background:linear-gradient(90deg,#6b1220,#a3172a,#6b1220);
 border-bottom:1px solid var(--red);box-shadow:0 4px 14px rgba(255,92,108,.25);
 animation:handpulse 1.2s ease-in-out infinite}
#handalert.show{display:block}
@keyframes handpulse{0%,100%{opacity:1}50%{opacity:.6}}
/* ── 🚀 بطاقة الانطلاقة (حرس اليد) ── */
#launcheq{font-size:38px;font-weight:800;line-height:1.15;direction:ltr;text-align:right}
.lmeta{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--txt2);margin-top:6px;align-items:baseline}
.lmeta b{direction:ltr;font-variant-numeric:tabular-nums;unicode-bidi:embed}
.lpct{font-size:16px;font-weight:800;direction:ltr;unicode-bidi:embed}
.lstrip{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid var(--line2)}
.lpill{font-size:12px;padding:4px 12px;border-radius:20px;background:var(--pill);
 border:1px solid var(--line3);color:var(--txt2);white-space:nowrap}
.lpill b{direction:ltr;font-variant-numeric:tabular-nums;unicode-bidi:embed;color:var(--txt)}
</style></head><body>

<header id="topbar">
 <div id="logo">R Trader <span>👑</span><span class="ver">v1</span></div>
 <nav id="tabs">
  <button class="tab active" data-tab="home">🏠 الرئيسية</button>
  <button class="tab" data-tab="pro">👑 القمرة</button>
  <button class="tab" data-tab="live">📱 الحيّ</button>
  <button class="tab" data-tab="map">🕸️ الخريطة</button>
  <button class="tab" data-tab="friday">🤖 FRIDAY</button>
 </nav>
 <div id="clock">--:--:--</div>
 <button id="btnmute" class="tool" title="كتم الصوت">🔔</button>
 <button id="btntheme" class="tool" title="تبديل الثيم">🌙</button>
 <button id="btnbrain" class="tool" title="مخ الشركة">🧠</button>
</header>

<!-- ── 🔔 حاوية الإشعارات ── -->
<div id="toasts"></div>

<!-- ── 🖐️🛑 شريط إنذار حرس اليد (يظهر فقط عند حدّ اليوم / وضع الرش) ── -->
<div id="handalert"></div>

<!-- ── تبويب الرئيسية (افتراضيّ) ── -->
<section id="panel-home" class="panel active">
 <div class="grid">
  <!-- 0) 🚀 الانطلاقة — بطاقة حرس اليد (تُحدَّث كل 3ث من /rt/launch) -->
  <div class="card wide">
   <div class="h2"><span>🚀 الانطلاقة</span><span class="dim" id="launchdays">—</span></div>
   <div id="launcheq" class="gold">—</div>
   <div class="lmeta" id="launchmeta">يحمّل…</div>
   <div class="lstrip" id="launchstrip"></div>
  </div>
  <!-- 0b) 🧠 العقل الجماعيّ — fleet_mind (يديرون بعضهم) -->
  <div class="card wide">
   <div class="h2"><span>🧠 العقل الجماعيّ</span><span class="dim" id="fmstate">—</span></div>
   <div id="fleetmind" class="na">يحمّل…</div>
  </div>
  <!-- 1) سبورة المخّ الواحد -->
  <div class="card wide">
   <div class="h2"><span>🧠 سبورة المخّ الواحد</span><span class="dim" id="sbage">الرابحون المقيسون مقابل المتقاعدين</span></div>
   <div id="scoreboard" class="na">يحمّل…</div>
  </div>
  <!-- 2) منحنى الحقوق -->
  <div class="card wide">
   <div class="h2"><span>📈 منحنى الحقوق</span><span class="dim" id="eqcnt"></span></div>
   <div id="equitycurve" class="na">يحمّل…</div>
  </div>
  <!-- 3) صفقات اليوم -->
  <div class="card wide">
   <div class="h2"><span>🧾 صفقات اليوم</span><span class="dim" id="ttcnt"></span></div>
   <!-- 🆕 فلاتر: الكل/رابح/خاسر (تُطبَّق بعد كلّ إعادة رسم) -->
   <div id="rt-trade-tools">
     <button data-f="all" class="on">الكل</button><button data-f="win">رابح</button><button data-f="loss">خاسر</button>
   </div>
   <div id="todaytrades" class="na">يحمّل…</div>
  </div>
  <!-- 4) الحساب + المجلس + المفتوحة + المحرّكات + روابط (كما كانت) -->
  <div class="card wide">
   <div class="h2"><span>💰 الحساب</span><span class="dim" id="accts">—</span></div>
   <div id="eq" class="gold">—</div>
   <div id="accsub">يحمّل…</div>
   <div id="accexec"></div>
   <!-- 🆕 المسافة فوق أرضيّة master_floor (الحاجز الوحيد بعد إزالة الحدّ اليوميّ) -->
   <div id="rt-risk-card"><span id="rt-risk-lbl">المسافة فوق الأرضيّة …</span>
     <div id="rt-risk-bar"><div id="rt-risk-fill"></div></div></div>
  </div>
  <div class="card">
   <div class="h2"><span>🏛️ أعلى إجماعات الوكلاء</span><span class="dim" id="cage"></span></div>
   <div id="council" class="na">يحمّل…</div>
  </div>
  <div class="card">
   <div class="h2"><span>🌍 الصفقات المفتوحة</span><span class="dim" id="posn"></span></div>
   <div id="positions" class="na">يحمّل…</div>
  </div>
  <div class="card">
   <div class="h2"><span>⚙️ المحرّكات</span>
    <span style="display:flex;gap:6px;align-items:center"><span id="engmode"></span><span id="killbadge"></span></span></div>
   <div id="engnum" class="gold">—</div>
   <div class="dim" style="font-size:12px" id="engsub">محرّكاً حيّاً الآن</div>
   <div id="engpanel" class="na">يحمّل…</div>
  </div>
  <div class="card">
   <div class="h2"><span>⚡ روابط سريعة</span></div>
   <div class="links">
    <button class="lbtn" data-go="pro">👑 القمرة</button>
    <button class="lbtn" data-go="live">📱 الحيّ</button>
    <button class="lbtn" data-go="map">🕸️ الخريطة</button>
    <button class="lbtn" data-go="friday">🤖 FRIDAY</button>
   </div>
  </div>
 </div>
 <div class="foot">R Trader — واجهة توحيد وقراءة فقط · تحديث كل 3 ثوانٍ · 🟢 إطار أخضر = إجماع ≥75%</div>
</section>

<!-- ── تبويب FRIDAY ── -->
<section id="panel-friday" class="panel">
 <div class="grid">
  <div class="card wide">
   <div class="h2"><span>🤖 حالة FRIDAY</span><span id="fkill"></span></div>
   <div id="fstatus" class="na">يحمّل…</div>
  </div>
  <div class="card wide">
   <div class="h2"><span>⚙️ المحرّكات</span><span class="dim" id="fengn"></span></div>
   <div id="fengines" class="na">يحمّل…</div>
  </div>
 </div>
</section>

<!-- ── حاوية الـiframes الكسولة ── -->
<div id="frames"></div>

<script>
'use strict';
const $ = id => document.getElementById(id);
const IFRAMES = {pro:'/pro', live:'/live', map:'/map'};
let active = 'home';
const NA = '<span class="na">غير متاح</span>';

/* ── التبويبات: إظهار/إخفاء بلا إعادة تحميل، iframes كسولة ── */
function showTab(t){
 active = t;
 document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
 $('panel-home').classList.toggle('active', t === 'home');
 $('panel-friday').classList.toggle('active', t === 'friday');
 const fr = $('frames');
 fr.classList.toggle('active', !!IFRAMES[t]);
 for(const k of Object.keys(IFRAMES)){
  let f = $('frame-' + k);
  if(t === k && !f){                       // إنشاء كسول عند أوّل فتح فقط
   f = document.createElement('iframe');
   f.id = 'frame-' + k; f.src = IFRAMES[k];
   fr.appendChild(f);
  }
  if(f) f.classList.toggle('active', t === k);
 }
 if(t === 'home') refreshHome();
 if(t === 'friday') refreshFriday();
}
document.querySelectorAll('.tab').forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.querySelectorAll('.lbtn').forEach(b => b.onclick = () => showTab(b.dataset.go));

/* ── 🎨 تبديل الثيم (داكن افتراضيّ، محفوظ محليّاً) ── */
function applyTheme(t){
 document.documentElement.setAttribute('data-theme', t);
 $('btntheme').textContent = (t === 'light') ? '☀️' : '🌙';
}
let theme = 'dark';
try{ theme = localStorage.getItem('rt_theme') || 'dark'; }catch(e){}
applyTheme(theme);
$('btntheme').onclick = () => {
 theme = (theme === 'light') ? 'dark' : 'light';
 applyTheme(theme);
 try{ localStorage.setItem('rt_theme', theme); }catch(e){}
};

/* ── 🧠 مخ الشركة — يفتح /rt/brain في تبويب جديد ── */
$('btnbrain').onclick = () => { try{ window.open('/rt/brain', '_blank'); }catch(e){} };

/* ── 🔔 نظام الإشعارات + الصوت ── */
let muted = false;
try{ muted = localStorage.getItem('rt_muted') === '1'; }catch(e){}
function applyMute(){
 $('btnmute').textContent = muted ? '🔕' : '🔔';
 $('btnmute').classList.toggle('off', muted);
 $('btnmute').title = muted ? 'الصوت مكتوم' : 'كتم الصوت';
}
applyMute();
$('btnmute').onclick = () => {
 muted = !muted; applyMute();
 try{ localStorage.setItem('rt_muted', muted ? '1' : '0'); }catch(e){}
};
let _ac = null;
function beep(){
 if(muted) return;
 try{
  _ac = _ac || new (window.AudioContext || window.webkitAudioContext)();
  if(_ac.state === 'suspended') _ac.resume();
  const o = _ac.createOscillator(), g = _ac.createGain();
  o.type = 'sine'; o.frequency.value = 880;
  g.gain.setValueAtTime(0.0001, _ac.currentTime);
  g.gain.exponentialRampToValueAtTime(0.12, _ac.currentTime + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, _ac.currentTime + 0.22);
  o.connect(g); g.connect(_ac.destination);
  o.start(); o.stop(_ac.currentTime + 0.23);
 }catch(e){}
}
function toast(msg, kind){
 try{
  const box = $('toasts'); if(!box) return;
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.innerHTML = msg;
  box.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
   el.classList.remove('show');
   setTimeout(() => { if(el.parentNode) el.parentNode.removeChild(el); }, 250);
  }, 8000);
 }catch(e){}
}

/* ── 🔔 استطلاع كل 4ث: فرص إجماع ≥80% + دخول/خروج الصفقات ── */
const seenOpps = new Set();     // sym|dir لتفادي التكرار
const engStatus = {};           // magic → آخر حالة (رابح/متقاعد/مراقَب) لإشعارات التحوّل
let lastPosCount = null;        // عدد الصفقات المفتوحة السابق
let notifPrimed = false;        // أوّل قراءة تُهيّئ فقط (بلا إشعار)
async function pollNotifs(){
 try{
  const d = await (await fetch('/live/data', {cache:'no-store'})).json();
  // فرص إجماع الوكلاء ≥80%
  const C = d.council || [];
  const opps = [];
  for(const r of C){
   const pct = r.pct || 0;
   if(pct >= 80 && r.dir){
    const sym = String(r.sym || '').replace('m','');
    const dir = r.dir > 0 ? 1 : -1;
    const key = sym + '|' + dir;
    if(!seenOpps.has(key)){
     seenOpps.add(key);
     opps.push({sym, verdict: dir > 0 ? 'شراء' : 'بيع', pct, cls: dir > 0 ? 'up' : 'dn'});
    }
   }
  }
  // عدد الصفقات المفتوحة
  const pc = (d.positions || []).length;
  if(!notifPrimed){          // القراءة الأولى: تهيئة الحالة فقط
   lastPosCount = pc; notifPrimed = true;
   return;
  }
  for(const o of opps){
   toast('🏛️ فرصة: <b>' + esc(o.sym) + '</b> <span class="' + o.cls + '">' +
     o.verdict + '</span> ' + o.pct + '%', 'ok');
  }
  if(opps.length) beep();
  if(lastPosCount != null && pc !== lastPosCount){
   if(pc > lastPosCount) toast('📈 صفقة جديدة', 'up');
   else toast('📉 أُغلقت صفقة', 'dn');
  }
  lastPosCount = pc;
  // 🏆 تحوّلات حالة المحرّكات (رابح/متقاعد) من سبورة نفس النبضة
  const BM = (d.board || {}).magics || [];
  for(const m of BM){
   const k = String(m.magic), st = m.status || 'watch';
   const prev = engStatus[k];
   if(prev && prev !== st){
    if(st === 'winner') toast('🏆 <b>' + esc(m.name || k) + '</b> صار <span class="up">رابحاً</span>', 'ok');
    else if(st === 'retired') toast('🔴 <b>' + esc(m.name || k) + '</b> <span class="dn">تقاعد</span>', 'dn');
   }
   engStatus[k] = st;
  }
 }catch(e){ /* دفاعيّ: أي فشل لا يكسر شيئاً */ }
}
setInterval(pollNotifs, 4000);
pollNotifs();

/* ── الساعة الحيّة ── */
setInterval(() => { $('clock').textContent = new Date().toLocaleTimeString('en-GB'); }, 1000);
$('clock').textContent = new Date().toLocaleTimeString('en-GB');

const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
 c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num = v => (v == null ? '—' : v);
/* رقمٌ ملوّن ±: يرجع {html} — أخضر للموجب أحمر للسالب */
const fnum = v => (typeof v === 'number' && isFinite(v)) ? v : null;
function money(v, dp){
 const n = fnum(v); if(n == null) return '<span class="dim">—</span>';
 dp = (dp == null) ? 2 : dp;
 const c = n >= 0 ? 'up' : 'dn';
 return '<span class="' + c + '">' + (n >= 0 ? '+' : '') + n.toFixed(dp) + '</span>';
}
/* حوّل طابعاً زمنياً (ثوان أو iso) إلى HH:MM:SS محلّي — دفاعيّ */
function hhmmss(row){
 try{
  if(row && typeof row.iso === 'string' && row.iso.length >= 19)
   return row.iso.slice(11, 19);
  const ts = fnum(row && (row.ts != null ? row.ts : row.time));
  if(ts != null){
   const d = new Date(ts > 1e12 ? ts : ts * 1000);
   if(!isNaN(d)) return d.toLocaleTimeString('en-GB');
  }
 }catch(e){}
 return '';
}
/* التقط أوّل حقلٍ موجودٍ من مفاتيح مرشّحة (مرونة مقابل تسميات الخادم) */
function pick(o, keys, dflt){
 if(!o) return dflt;
 for(const k of keys){ if(o[k] != null) return o[k]; }
 return dflt;
}

/* ── 1) سبورة المخّ الواحد — GET /rt/scoreboard ── */
async function refreshScoreboard(){
 try{
  const d = await (await fetch('/rt/scoreboard', {cache:'no-store'})).json();
  // صفّ المحرّكات: مرن على تسمية الحاوية ('magics' هو المفتاح الفعليّ من desk_scoreboard)
  let E = pick(d, ['magics', 'engines', 'board', 'rows', 'scoreboard'], []);
  if(!Array.isArray(E)) E = [];
  // ترتيب تنازليّ حسب net_3d
  E = E.slice().sort((a, b) =>
   (fnum(pick(b, ['net_3d', 'net3d'], 0)) || 0) - (fnum(pick(a, ['net_3d', 'net3d'], 0)) || 0));
  if(E.length){
   let rows = '';
   for(const e of E){
    const st = String(pick(e, ['status', 'state'], 'watch')).toLowerCase();
    const isWin = st === 'winner' || st === 'win';
    const isRet = st === 'retired' || st === 'ret' || st === 'dead';
    const trCls = isWin ? 'win' : (isRet ? 'ret' : '');
    const dotCls = isWin ? 'win' : (isRet ? 'ret' : 'watch');
    const nm = pick(e, ['ar_name', 'name_ar', 'name', 'engine'], '؟');
    const magic = pick(e, ['magic', 'id'], null);
    const nt = fnum(pick(e, ['net_today', 'today', 'netToday'], null));
    const n3 = fnum(pick(e, ['net_3d', 'net3d'], null));
    const nToday = pick(e, ['n_today', 'trades_today', 'nToday'], null);
    const wr = fnum(pick(e, ['wr_today', 'winrate_today', 'wr'], null));
    const nOpen = fnum(pick(e, ['n_open', 'open', 'nOpen'], 0)) || 0;
    // م.ربح/م.خسارة — دفاعيّ: الحقول قد تغيب في حمولات قديمة ⇒ «—»
    const aw = fnum(pick(e, ['avg_win', 'avgWin'], null));
    const al = fnum(pick(e, ['avg_loss', 'avgLoss'], null));
    let wl = '<span class="dim">—</span>';
    if(aw != null || al != null){
     wl = '<span class="wl">' +
       '<span class="w">' + (aw != null ? '+' + Math.abs(aw).toFixed(2) : '—') + '</span>' +
       '<span class="l">' + (al != null ? '−' + Math.abs(al).toFixed(2) : '—') + '</span>' +
       '</span>';
    }
    // العائد (payoff): null صراحةً = لا خسائر بعد ⇒ ∞؛ غياب المفتاح كلّياً ⇒ «—»
    const po = fnum(pick(e, ['payoff', 'payoff_ratio'], null));
    let poCell = '<span class="dim">—</span>';
    if(po != null){
     const poCls = po >= 1 ? 'good' : (po >= 0.5 ? 'mid' : 'bad');
     poCell = '<span class="po ' + poCls + '">' + po.toFixed(2) + '</span>';
    } else if(e && typeof e === 'object' && ('payoff' in e || 'payoff_ratio' in e)){
     poCell = '<span class="po inf" title="لا خسائر بعد ⇒ عائد لا نهائيّ (مقصود، ليس خطأً)">∞</span>';
    }
    let chip = '';
    if(isRet) chip = ' <span class="chip ret">متقاعد</span>';
    else if(isWin) chip = ' <span class="chip win">رابح</span>';
    const openB = nOpen > 0 ? ' <span class="openbadge">' + nOpen + ' مفتوح</span>' : '';
    rows += '<tr class="' + trCls + '">' +
      '<td><span class="dot ' + dotCls + '"></span> <span class="engname">' + esc(nm) + '</span>' +
        chip + openB + '</td>' +
      '<td class="n"><span class="engmagic">' + (magic != null ? esc(magic) : '—') + '</span></td>' +
      '<td class="n">' + money(nt) + '</td>' +
      '<td class="n">' + money(n3) + '</td>' +
      '<td class="n">' + (nToday != null ? esc(nToday) : '—') + '</td>' +
      '<td class="n">' + (wr != null ? wr.toFixed(0) + '%' : '—') + '</td>' +
      '<td class="n">' + wl + '</td>' +
      '<td class="n">' + poCell + '</td>' +
      '</tr>';
   }
   $('scoreboard').innerHTML =
    '<div class="sbscroll"><table class="sb"><thead><tr>' +
    '<th>المحرّك</th><th class="n">المجيك</th><th class="n">اليوم</th>' +
    '<th class="n">٣ أيّام</th><th class="n">صفقات</th><th class="n">فوز</th>' +
    '<th class="n">م.ربح/م.خسارة</th><th class="n">العائد</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  } else {
   $('scoreboard').innerHTML = '<span class="na">لا بيانات سبورة بعد</span>';
  }
  // صفقات اليوم من نفس الرَّد — يُصيّرها راسم مشترك (فارغ إن غاب المفتاح)
  const T = pick(d, ['today_trades', 'todays_trades', 'trades'], null);
  renderTodayTrades(Array.isArray(T) ? T : []);
 }catch(err){
  $('scoreboard').innerHTML = NA;
  $('todaytrades').innerHTML = '<span class="na">لا صفقات مغلقة اليوم بعد</span>';
  $('ttcnt').textContent = '';
 }
}

/* راسم مشترك لصفقات اليوم (يُستدعى من scoreboard) — الأحدث أوّلاً */
function renderTodayTrades(T){
 try{
  if(!Array.isArray(T) || !T.length){
   $('todaytrades').innerHTML = '<span class="na">لا صفقات مغلقة اليوم بعد</span>';
   $('ttcnt').textContent = '';
   return;
  }
  // الأحدث أوّلاً (نسخة معكوسة حسب ts إن وُجد، وإلا عكس ترتيب الورود)
  const rows = T.slice().sort((a, b) =>
   (fnum(b && b.ts) || 0) - (fnum(a && a.ts) || 0));
  $('ttcnt').textContent = rows.length + ' حدث';
  let h = '';
  for(const t of rows){
   const rawDir = String(pick(t, ['dir', 'side', 'type'], '')).toLowerCase();
   const isBuy = rawDir.indexOf('buy') >= 0 || rawDir === '1' || rawDir.indexOf('شراء') >= 0;
   const isSell = rawDir.indexOf('sell') >= 0 || rawDir === '-1' || rawDir.indexOf('بيع') >= 0;
   const dCls = isBuy ? 'buy' : (isSell ? 'sell' : '');
   const dTxt = isBuy ? 'شراء' : (isSell ? 'بيع' : esc(rawDir || '—'));
   const sym = esc(String(pick(t, ['sym', 'symbol'], '')).replace('m', ''));
   const eng = esc(pick(t, ['ar_name', 'name_ar', 'engine', 'name', 'type'], ''));
   const net = fnum(pick(t, ['net', 'pnl', 'profit'], null));
   h += '<div class="trow">' +
     '<span class="ttime">' + esc(hhmmss(t)) + '</span>' +
     '<span class="tdir ' + dCls + '">' + dTxt + '</span>' +
     '<span class="tsym">' + sym + '</span>' +
     '<span class="teng">' + eng + '</span>' +
     '<span class="tnet">' + (net != null ? money(net) : '<span class="dim">—</span>') + '</span>' +
     '</div>';
  }
  $('todaytrades').innerHTML = h; rtApplyTradeFilter();   /* 🆕 أعِد تطبيق الفلتر بعد كلّ رسم */
 }catch(e){ $('todaytrades').innerHTML = NA; }
}

/* ── 🆕 فلاتر صفقات اليوم (الكل/رابح/خاسر) — تقرأ .tnet وتُطبَّق بعد كلّ إعادة رسم ── */
var rtTradeFilter='all';
function rtTradeNet(row){var n=row.querySelector('.tnet');if(!n)return 0;
 return parseFloat((n.textContent||'').replace(/[^0-9.-]/g,''))||0;}
function rtApplyTradeFilter(){var tt=$('todaytrades');if(!tt)return;
 var rows=tt.querySelectorAll('.trow');for(var i=0;i<rows.length;i++){var net=rtTradeNet(rows[i]),show=true;
  if(rtTradeFilter==='win')show=net>0;else if(rtTradeFilter==='loss')show=net<0;
  rows[i].classList.toggle('rt-hidden',!show);}}
(function(){var bar=$('rt-trade-tools');if(!bar)return;var btns=bar.querySelectorAll('button');
 for(var i=0;i<btns.length;i++){(function(b){b.onclick=function(){rtTradeFilter=b.dataset.f;
  for(var j=0;j<btns.length;j++)btns[j].classList.toggle('on',btns[j].dataset.f===rtTradeFilter);
  rtApplyTradeFilter();};})(btns[i]);}})();
/* ── 🆕 المسافة فوق أرضيّة master_floor (الحاجز الوحيد بعد إزالة الحدّ اليوميّ) ── */
function rtRiskColor(safe){var h=Math.max(0,Math.min(120,safe*120));return 'hsl('+h+',70%,45%)';}
async function updateRiskCushion(){
 var fill=$('rt-risk-fill'),lbl=$('rt-risk-lbl');if(!fill||!lbl)return;
 try{var j=await(await fetch('/api/status',{cache:'no-store'})).json();
  var floor=j&&j.floor&&j.floor.floor, eqEl=$('eq');
  var eq=eqEl?parseFloat((eqEl.textContent||'').replace(/[^0-9.-]/g,'')):NaN;
  if(!isFinite(floor)||!isFinite(eq)||eq<=floor){lbl.textContent='المسافة فوق الأرضيّة —';
   fill.style.width='3%';fill.style.background='#c22a34';return;}
  var safe=Math.max(0,Math.min(1,(eq-floor)/eq));        /* وسادة صادقة من الحقوق (لا تشوّهها القمّة المتضخّمة بالإيداعات) */
  fill.style.width=Math.max(4,safe*100).toFixed(0)+'%';fill.style.background=rtRiskColor(safe);
  lbl.textContent='فوق الأرضيّة $'+(eq-floor).toFixed(0)+' ('+(safe*100).toFixed(0)+'%) · أرضيّة $'+floor.toFixed(0);
 }catch(e){}}

/* ── 2) منحنى الحقوق — GET /rt/home .equity_curve = [[ts, eq], …] ── */
function renderSparkline(curve){
 try{
  const pts = (Array.isArray(curve) ? curve : [])
   .filter(p => Array.isArray(p) && p.length >= 2 && fnum(p[1]) != null)
   .map(p => [fnum(p[0]) || 0, fnum(p[1])]);
  if(pts.length < 2){
   $('equitycurve').innerHTML = '<span class="na">لا بيانات بعد</span>';
   $('eqcnt').textContent = '';
   return;
  }
  const W = 600, H = 60, PAD = 3;   // إحداثيّات فيرتشوال؛ الـsvg يتمدّد 100%
  const ys = pts.map(p => p[1]);
  let lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
  if(hi === lo){ hi += 1; lo -= 1; }
  const n = pts.length;
  const sx = i => PAD + (i / (n - 1)) * (W - 2 * PAD);
  const sy = v => PAD + (1 - (v - lo) / (hi - lo)) * (H - 2 * PAD);
  let dLine = '', dArea = '';
  for(let i = 0; i < n; i++){
   const x = sx(i).toFixed(1), y = sy(pts[i][1]).toFixed(1);
   dLine += (i ? 'L' : 'M') + x + ' ' + y + ' ';
   dArea += (i ? 'L' : 'M') + x + ' ' + y + ' ';
  }
  dArea += 'L' + sx(n - 1).toFixed(1) + ' ' + (H - PAD) + ' L' + sx(0).toFixed(1) + ' ' + (H - PAD) + ' Z';
  const first = pts[0][1], last = pts[n - 1][1];
  const trend = last >= first ? 'var(--green)' : 'var(--red)';
  const svg =
   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="منحنى الحقوق">' +
   '<path d="' + dArea + '" fill="var(--gold)" fill-opacity="0.08" stroke="none"></path>' +
   '<path d="' + dLine + '" fill="none" stroke="var(--gold)" stroke-width="1.6" ' +
     'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></path>' +
   '<circle cx="' + sx(n - 1).toFixed(1) + '" cy="' + sy(last).toFixed(1) + '" r="2.4" ' +
     'fill="' + trend + '"></circle>' +
   '</svg>';
  $('equitycurve').innerHTML =
   '<div class="spark-wrap">' + svg +
   '<span class="spark-last">$' + last.toFixed(2) + '</span></div>' +
   '<div class="spark-meta"><span>أدنى $' + lo.toFixed(2) + '</span>' +
   '<span>' + (last >= first ? '▲' : '▼') + ' ' + (last - first >= 0 ? '+' : '') +
     (last - first).toFixed(2) + '</span>' +
   '<span>أعلى $' + hi.toFixed(2) + '</span></div>';
  $('eqcnt').textContent = n + ' نقطة';
 }catch(e){ $('equitycurve').innerHTML = NA; $('eqcnt').textContent = ''; }
}

/* ── 2b) جلب منحنى الحقوق — GET /rt/home ── */
async function refreshEquityCurve(){
 try{
  const d = await (await fetch('/rt/home', {cache:'no-store'})).json();
  const curve = pick(d, ['equity_curve', 'curve', 'equityCurve'], []);
  renderSparkline(curve);
 }catch(err){ $('equitycurve').innerHTML = NA; $('eqcnt').textContent = ''; }
}

/* ── الرئيسية: /live/data (حساب + مجلس + صفقات) — كلّ بطاقة تفشل وحدها ── */
async function refreshHome(){
 // الأقسام الجديدة (سبورة/منحنى/صفقات) — كلٌّ دفاعيّ ومستقلّ
 refreshScoreboard();
 refreshEquityCurve();
 updateRiskCushion();          /* 🆕 المسافة فوق أرضيّة master_floor */
 try{
  const d = await (await fetch('/live/data', {cache:'no-store'})).json();
  $('accts').textContent = '⏱️ ' + (d.ts || '');
  const a = d.account || {};
  $('eq').textContent = a.equity != null ? '$' + a.equity : 'غير متاح';
  $('accsub').textContent = a.equity != null
   ? ('رصيد $' + num(a.balance) + ' · هامش ' + num(a.margin_level) + '% · ' + (a.server || ''))
   : 'غير متاح';
  const e = d.exec || {};
  $('accexec').innerHTML = (e.frozen ? '🧊 المنفّذ مجمّد' : '🟢 المنفّذ نشط') +
   ' · مخاطرة ' + num(e.risk_pct) + '% · رضا ' + num(e.satisfaction) + '%' +
   (e.floating != null ? ' · عائم <span class="' + (e.floating >= 0 ? 'up' : 'dn') + '">' +
     (e.floating >= 0 ? '+' : '') + e.floating + '</span>' : '');
  // أعلى 6 إجماعات — أشرطة ملوّنة كما في /live
  const C = (d.council || []).slice(0, 6);
  $('cage').textContent = d.council_age != null ? 'عمر ' + d.council_age + 'ث' : '';
  if(C.length){
   let h = '';
   for(const r of C){
    const col = r.dir > 0 ? '#3ddc84' : (r.dir < 0 ? '#ff5c6c' : '#7a828f');
    const trad = (r.pct >= 75) ? ' tradeable' : '';
    h += '<div class="crow' + trad + '"><span class="csym" style="color:' + col + '">' +
      esc(String(r.sym || '').replace('m','')) + '</span>' +
      '<span class="cbar"><span class="cfill" style="' + (r.dir > 0 ? 'right:0' : 'left:0') +
      ';width:' + (r.pct || 0) + '%;background:' + col + '"></span><i class="cthr" title="عتبة التداول 75%"></i></span>' +
      '<span class="cpct" style="color:' + col + '">' + (r.pct || 0) + '%</span></div>';
   }
   $('council').innerHTML = h;
  } else $('council').innerHTML = NA;
  // الصفقات المفتوحة + خطط الإغلاق
  const P = d.positions || [];
  $('posn').textContent = P.length + ' مركز';
  if(P.length){
   let ph = '', tot = 0;
   for(const p of P){
    tot += (p.pnl || 0);
    const c = (p.pnl || 0) >= 0 ? 'up' : 'dn';
    ph += '<div class="prow"><div class="phead"><span>' + (p.mom ? '🏇 ' : '') +
      esc(String(p.sym || '').replace('m','')) + ' ' + esc(p.dir) + ' ' + num(p.lot) +
      (p.secured ? ' <span class="chip sec">🌾 مؤمَّن</span>' : '') + '</span>' +
      '<span class="' + c + '">' + ((p.pnl || 0) >= 0 ? '+' : '') + (p.pnl || 0).toFixed(2) + '</span></div>' +
      '<div class="pplan">🎯 هدف ' + num(p.tp) + ' (بُعد ' + num(p.to_tp) + ') · 🛑 وقف ' +
      num(p.sl) + ' (بُعد ' + num(p.to_sl) + ')' + (p.mom ? ' · 🏇 تريلينغ' : '') + '</div></div>';
   }
   ph += '<div class="prow phead" style="border-top:1px solid #2a3240"><b>الإجماليّ</b><b class="' +
     (tot >= 0 ? 'up' : 'dn') + '">' + (tot >= 0 ? '+' : '') + tot.toFixed(2) + '</b></div>';
   $('positions').innerHTML = ph;
  } else $('positions').innerHTML = '<span class="na">لا صفقات مفتوحة</span>';
 }catch(err){
  $('eq').textContent = 'غير متاح'; $('accsub').textContent = 'غير متاح';
  $('accexec').textContent = ''; $('council').innerHTML = NA; $('positions').innerHTML = NA;
 }
 try{
  const s = await (await fetch('/api/status', {cache:'no-store'})).json();
  $('engnum').textContent = num(s.engines);
  $('killbadge').innerHTML = s.kill_switch
   ? '<span class="chip kill">⛔ kill_switch مفعّل</span>' : '<span class="chip">✅ طبيعي</span>';
 }catch(err){
  $('engnum').textContent = '—';
  $('killbadge').innerHTML = '<span class="na">غير متاح</span>';
 }
}

/* ── تبويب FRIDAY: /api/engines + /api/status ── */
async function refreshFriday(){
 try{
  const s = await (await fetch('/api/status', {cache:'no-store'})).json();
  const a = s.account || {};
  $('fkill').innerHTML = s.kill_switch
   ? '<span class="chip kill">⛔ kill_switch مفعّل</span>' : '<span class="chip">✅ طبيعي</span>';
  $('fstatus').innerHTML =
   '<div style="font-size:22px;font-weight:800" class="gold">$' + num(a.equity) + '</div>' +
   '<div class="dim" style="font-size:12px;margin-top:4px">رصيد $' + num(a.balance) +
   ' · هامش حرّ $' + num(a.margin_free) + ' · مستوى ' + num(a.margin_level) + '% · ' +
   esc(a.server || '') + ' · مراكز ' + num(a.positions) +
   (a.floating != null ? ' · عائم <span class="' + (a.floating >= 0 ? 'up' : 'dn') + '">' +
     (a.floating >= 0 ? '+' : '') + a.floating + '</span>' : '') + '</div>' +
   (s.floor_dist != null ? '<div class="dim" style="font-size:12px;margin-top:2px">🛡️ بُعد عن الأرضيّة $' +
     s.floor_dist + '</div>' : '');
 }catch(err){ $('fstatus').innerHTML = NA; $('fkill').innerHTML = ''; }
 try{
  const g = await (await fetch('/api/engines', {cache:'no-store'})).json();
  const E = g.engines || [];
  $('fengn').textContent = (g.total_running != null ? g.total_running : '—') + ' شغّال';
  $('fengines').innerHTML = E.length
   ? '<div class="badges">' + E.map(x =>
      '<span class="badge' + (x.running ? ' on' : '') + '">' + (x.running ? '🟢 ' : '⚪ ') +
      esc(x.name) + (x.procs > 1 ? ' ×' + x.procs : '') + '</span>').join('') + '</div>'
   : NA;
 }catch(err){ $('fengines').innerHTML = NA; $('fengn').textContent = ''; }
}

/* ── ⚙️ لوحة تحكّم المحرّكات — /rt/token (محليّ فقط) + /rt/engines كل 10ث ── */
const AR_ENG = {
 unified_brain: 'المخّ الموحّد', brain_trader: 'متداول المخّ', agent_council: 'مجلس الوكلاء',
 market_pulse: 'نبض السوق', quant_desk: 'مكتب الكمّ', radhi_mimic: 'محاكي راضي',
 profit_harvester: 'حاصد الأرباح', news_alarm: 'إنذار الأخبار', order_janitor: 'منظّف الأوامر',
 real_lock: 'قفل الحقيقي', master_floor: 'الأرضيّة الرئيسة', peak_watch: 'مراقب الذروة',
 gold_level_sentinel: 'حارس مستويات الذهب', self_evolver: 'المتطوّر الذاتي',
 brain_watch: 'مراقب المخّ', watchdog_guard: 'الوصيّ الحارس'
};
const CRIT_ENG = {watchdog_guard: 1, master_floor: 1, real_lock: 1};   // حرجة ⇒ تحذير أشدّ
let rtToken = null;            // 🔑 في متغيّر JS فقط — لا localStorage أبداً
let controlMode = false;       // true = محليّ ومعه توكن؛ false = عرض فقط
let engPendingKey = null, engPendingBtn = null, engPendingTimer = null;

const engLabel = n => AR_ENG[String(n || '')] || String(n || '؟');

/* عند الإقلاع: جرّب /rt/token — ينجح محليّاً فقط (403 عبر النفق ⇒ عرض فقط) */
async function initRtToken(){
 try{
  const r = await fetch('/rt/token', {cache: 'no-store'});
  if(r.ok){
   const j = await r.json();
   if(j && j.token){ rtToken = String(j.token); controlMode = true; }
  }
 }catch(e){ /* نفق أو فشل شبكة ⇒ انحدار صامت إلى قراءة فقط */ }
 try{
  $('engmode').innerHTML = controlMode ? '' : '<span class="romode">عرض فقط (عن بُعد)</span>';
 }catch(e){}
}

function renderEngines(d){
 try{
  const box = $('engpanel'); if(!box) return;
  const E = (d && Array.isArray(d.engines)) ? d.engines : [];
  try{
   $('engsub').textContent = (d && d.n_alive != null && d.n_total != null)
    ? (d.n_alive + ' من ' + d.n_total + ' حيّ الآن') : 'محرّكاً حيّاً الآن';
  }catch(e){}
  if(!E.length){ box.innerHTML = '<span class="na">لا محرّكات</span>'; return; }
  let h = '';
  for(const en of E){
   const nm = String((en && en.name) || '');
   const alive = !!(en && en.alive);
   const procs = fnum(en && en.procs) || 0;
   const crit = CRIT_ENG[nm] ? '1' : '0';
   let btns = '';
   if(controlMode){
    if(alive){
     btns = '<button class="ebtn' + (CRIT_ENG[nm] ? ' crit' : '') + '" data-eng="' + esc(nm) +
        '" data-act="stop" data-crit="' + crit + '">⏹ إيقاف</button>' +
      '<button class="ebtn" data-eng="' + esc(nm) + '" data-act="restart" data-crit="' + crit +
        '">⟳ إعادة</button>';
    } else {
     btns = '<button class="ebtn go" data-eng="' + esc(nm) + '" data-act="start" data-crit="0">▶ تشغيل</button>';
    }
   }
   h += '<div class="erow"><span class="edot ' + (alive ? 'alive' : 'dead') + '"></span>' +
     '<span class="ename" title="' + esc(nm) + '">' + esc(engLabel(nm)) + '</span>' +
     (procs > 0 ? '<span class="eprocs">×' + procs + '</span>' : '') + btns + '</div>';
  }
  box.className = '';
  box.innerHTML = h;
 }catch(e){}
}

async function refreshEngines(){
 try{
  if(engPendingKey) return;              // لا تُعِد الرسم وثمّة «تأكيد؟» معلّق
  const r = await fetch('/rt/engines', {cache: 'no-store'});
  if(!r.ok) throw new Error('http ' + r.status);
  renderEngines(await r.json());
 }catch(e){
  try{                                   // انحدار صامت: أبقِ آخر قائمة إن وُجدت
   const box = $('engpanel');
   if(box && !box.querySelector('.erow')) box.innerHTML = NA;
  }catch(e2){}
 }
}

/* أرجِع أيّ زرّ تأكيدٍ معلّقٍ إلى حالته الأصليّة */
function engRevert(){
 try{
  if(engPendingTimer){ clearTimeout(engPendingTimer); engPendingTimer = null; }
  if(engPendingBtn){
   engPendingBtn.dataset.confirm = '';
   if(engPendingBtn.dataset.orig) engPendingBtn.textContent = engPendingBtn.dataset.orig;
   engPendingBtn.classList.remove('confirm');
  }
 }catch(e){}
 engPendingBtn = null; engPendingKey = null;
}

/* إيقاف/إعادة = نقرتان: الأولى تُحوّل الزرّ إلى «تأكيد؟» 4ث، الثانية تنفّذ (لا window.confirm) */
function engBtnClick(btn, name, action, crit){
 try{
  if(!controlMode || !name || !action) return;
  if(action === 'start'){ engRevert(); execEngine(name, 'start'); return; }
  const key = name + '|' + action;
  if(engPendingKey === key && btn.dataset.confirm === '1'){   // النقرة الثانية ⇒ تنفيذ
   engRevert();
   execEngine(name, action);
   return;
  }
  engRevert();                                                // أبطل أيّ تأكيد آخر
  engPendingKey = key; engPendingBtn = btn;
  btn.dataset.confirm = '1';
  btn.dataset.orig = btn.textContent;
  btn.textContent = (crit && action === 'stop') ? 'متأكّد؟ حارس حرج' : 'تأكيد؟';
  btn.classList.add('confirm');
  engPendingTimer = setTimeout(engRevert, 4000);              // مهلة 4ث ثم رجوع
 }catch(e){ engRevert(); }
}

/* التنفيذ الفعليّ: POST /rt/engines/{name}/{action} برأس X-RT-Token ثم toast عربيّ */
async function execEngine(name, action){
 try{
  const r = await fetch('/rt/engines/' + encodeURIComponent(name) + '/' + encodeURIComponent(action),
   {method: 'POST', headers: {'X-RT-Token': rtToken || ''}, cache: 'no-store'});
  let j = null;
  try{ j = await r.json(); }catch(e){}
  if(r.status === 401 || r.status === 403){
   controlMode = false;
   try{ $('engmode').innerHTML = '<span class="romode">عرض فقط (عن بُعد)</span>'; }catch(e){}
   toast('🔒 رُفض التفويض — تحوّلت اللوحة إلى عرض فقط', 'dn');
   setTimeout(refreshEngines, 1500);
   return;
  }
  const label = '<b>' + esc(engLabel(name)) + '</b>';
  if(!r.ok || (j && (j.ok === false || j.error))){
   const why = (j && (j.error || j.detail)) ? ' (' + esc(j.error || j.detail) + ')' : '';
   toast('⚠️ خطأ في الأمر: ' + label + why, 'dn');
  } else if(j && j.already){
   toast('ℹ️ يعمل مسبقاً: ' + label, '');
  } else if(action === 'stop'){
   toast((j && j.killed) ? ('⏹ أُوقف: ' + label + ' (عمليّات ' + j.killed + ')')
                         : ('ℹ️ لم يكن يعمل: ' + label), 'dn');
  } else if(action === 'restart'){
   toast('⟳ أُعيد تشغيله: ' + label, 'ok');
  } else {
   toast('▶️ شُغِّل: ' + label, 'ok');
  }
  setTimeout(refreshEngines, 1500);
 }catch(e){
  toast('⚠️ تعذّر تنفيذ الأمر — شبكة أو بوّابة', 'dn');
  try{ setTimeout(refreshEngines, 1500); }catch(e2){}
 }
}

/* تفويض نقرات أزرار المحرّكات (الصفوف تُعاد بناؤها بـinnerHTML) */
try{
 $('engpanel').addEventListener('click', ev => {
  try{
   let b = ev.target;
   while(b && b !== ev.currentTarget && !(b.tagName === 'BUTTON' && b.dataset && b.dataset.act))
    b = b.parentNode;
   if(!b || b === ev.currentTarget || !b.dataset || !b.dataset.act) return;
   engBtnClick(b, b.dataset.eng, b.dataset.act, b.dataset.crit === '1');
  }catch(e){}
 });
}catch(e){}

/* إقلاع اللوحة: التوكن أوّلاً ثم أوّل جلب — وتحديث كل 10ث (منفصل عن نبضة الـ3ث) */
initRtToken().then(refreshEngines);
setInterval(refreshEngines, 10000);

/* ── 🚀 الانطلاقة (حرس اليد 🖐️) — GET /rt/launch كل 3ث + شريط الإنذار الثابت ── */
function launchBanner(g){
 try{
  const ba = $('handalert'); if(!ba) return;
  let msg = '';
  if(g && g.day_limit_hit) msg = '🖐️🛑 حد اليوم — قاعدتك تقول قف';
  else if(g && g.spray_mode) msg = '🖐️⚠️ وضع الرش';
  ba.textContent = msg;
  ba.classList.toggle('show', !!msg);
 }catch(e){}
}
async function refreshLaunch(){
 let d = null;
 try{ d = await (await fetch('/rt/launch', {cache:'no-store'})).json(); }catch(e){}
 try{
  if(!d || typeof d !== 'object') d = {stale: true};
  launchBanner(d.guards || {});                       // الشريط يظهر فقط عند تفعيل الحرس
  const eq = fnum(pick(d, ['equity', 'eq'], null));
  const start = fnum(pick(d, ['start_equity', 'launch_equity', 'start', 'start_balance'], null));
  const peak = fnum(pick(d, ['peak_equity', 'peak'], null));
  $('launcheq').textContent = eq != null ? '$' + eq.toFixed(2) : 'غير متاح';
  // النسبة الملوّنة مقابل البداية + القمّة + الهبوط من القمّة
  const parts = [];
  if(eq != null && start != null && start > 0){
   const pct = (eq - start) / start * 100;
   parts.push('<span class="lpct ' + (pct >= 0 ? 'up' : 'dn') + '">' + (pct >= 0 ? '+' : '') +
     pct.toFixed(1) + '%</span> <span>من $' + start.toFixed(2) + '</span>');
  }
  if(peak != null){
   parts.push('🏔️ القمّة <b>$' + peak.toFixed(2) + '</b>');
   if(eq != null && peak > 0){
    const dd = Math.max(0, (peak - eq) / peak * 100);
    parts.push('هبوط من القمّة <b class="' + (dd >= 5 ? 'dn' : (dd > 0.5 ? 'gold' : 'up')) +
      '">−' + dd.toFixed(1) + '%</b>');
   }
  }
  $('launchmeta').innerHTML = parts.length
   ? parts.map(p => '<span>' + p + '</span>').join('')
   : '<span class="na">' + (d.stale ? 'حرس اليد لم يكتب حالته بعد' : 'لا بيانات') + '</span>';
  // أيّام منذ الانطلاقة (حقل جاهز أو حساب من طابع الانطلاقة)
  let days = fnum(pick(d, ['days_since_launch', 'launch_days', 'days'], null));
  if(days == null){
   const lts = fnum(pick(d, ['launch_ts', 'start_ts', 'since_ts'], null));
   if(lts != null && lts > 0)
    days = Math.max(0, (Date.now() - (lts > 1e12 ? lts : lts * 1000)) / 86400000);
  }
  $('launchdays').textContent = days != null
   ? ('📅 اليوم ' + (Math.floor(days) + 1) + ' منذ الانطلاقة')
   : (d.stale ? 'غير متاح' : '');
  // شريط اليد اليوميّ: صفقات اليوم/الساعة + صافي اليد
  const m = (d.manual && typeof d.manual === 'object') ? d.manual : d;
  const tDay = fnum(pick(m, ['trades_today', 'n_today', 'day_trades', 'manual_trades_today'], null));
  const tHour = fnum(pick(m, ['trades_hour', 'n_hour', 'trades_this_hour', 'hour_trades'], null));
  const mNet = fnum(pick(m, ['net_today', 'manual_net_today', 'manual_net', 'day_net'], null));
  $('launchstrip').innerHTML =
   '<span class="lpill">🧾 صفقات اليوم <b>' + (tDay != null ? tDay : '—') + '</b></span>' +
   '<span class="lpill">⏱️ هذه الساعة <b>' + (tHour != null ? tHour : '—') + '</b></span>' +
   '<span class="lpill">🖐️ صافي اليد ' + (mNet != null ? money(mNet) : '<b>—</b>') + '</span>';
 }catch(e){
  try{ $('launchmeta').innerHTML = NA; }catch(e2){}
 }
}
setInterval(refreshLaunch, 3000);
refreshLaunch();

/* ── 🧠 العقل الجماعيّ (fleet_mind) — GET /rt/fleet كل 5ث: حالة + ميزانيّة + مضاعِف كل محرّك ── */
async function refreshFleet(){
 let d=null;
 try{ d = await (await fetch('/rt/fleet', {cache:'no-store'})).json(); }catch(e){}
 const box=$('fleetmind'); if(!box) return;
 if(!d || d.stale){ box.className='na'; box.textContent='لا بيانات العقل بعد…'; return; }
 const st=String(d.fleet_state||'—'), bud=Number(d.budget_factor||0);
 const sc = st==='healthy'?'up':(st==='deep'||st==='derisk'?'dn':'gold');
 const stAr={healthy:'صحّيّ 🟢',mild:'تراجع خفيف 🟡',deep:'تراجع عميق 🔴',derisk:'خفض مخاطرة 🔴'}[st]||st;
 $('fmstate').innerHTML='الحالة <span class="'+sc+'">'+esc(stAr)+'</span> · ميزانيّة '+bud.toFixed(2);
 const eng=d.engines||{};
 let rows='<div class="sbscroll"><table class="sb"><tr><th>المحرّك</th><th>مضاعِف اللوت</th><th>الوقوف</th></tr>';
 const keys=Object.keys(eng);
 if(!keys.length){ box.className='na'; box.textContent='لا محرّكات مُدارة الآن'; return; }
 for(const k of keys){
  const e=eng[k]||{}; const m=Number(e.mult!=null?e.mult:(e.lot_mult!=null?e.lot_mult:1));
  const mc=m>=1?'up':(m>=0.6?'gold':'dn'); const w=Math.max(6,Math.min(100,m*55));
  rows+='<tr><td>'+esc(e.engine||k)+'</td>'+
   '<td><span class="cbar" style="display:inline-block;width:120px;vertical-align:middle"><span class="cfill '+mc+'" style="width:'+w+'%;background:currentColor"></span></span> <span class="'+mc+'">×'+m.toFixed(2)+'</span></td>'+
   '<td class="dim" style="font-size:11px">'+esc(String(e.stand||e.tier||e.why||'—')).slice(0,26)+'</td></tr>';
 }
 rows+='</table></div>';
 box.className=''; box.innerHTML=rows;
}
setInterval(refreshFleet, 5000);
refreshFleet();

/* ── نبضة كل 3 ثوانٍ للتبويب المرئيّ فقط (توفير) ── */
setInterval(() => {
 if(active === 'home') refreshHome();
 else if(active === 'friday') refreshFriday();
}, 3000);
refreshHome();
</script></body></html>"""
