# -*- coding: utf-8 -*-
"""
friday_dashboard.py — FRIDAY لوحة ويب احترافية تفاعلية (READ-ONLY)
==================================================================
لوحة ويب عربية RTL سليمة (المتصفّح يعرض العربي صح)، تبويبات + مخططات + تحديث تلقائي:
نظرة عامة · التداول · التعلّم والعقول · الانضباط · التطوّر · ruflo (هل يطوّر فعلاً؟).
تشغيل:  python friday_dashboard.py  →  http://127.0.0.1:8900   |  friday_dashboard.bat
قراءة فقط — لا order_send، لا تعديل.
"""
from __future__ import annotations
import glob, json, math, os, time
from collections import defaultdict
from datetime import datetime, timezone
from flask import Flask, jsonify, Response

ROOT = os.path.dirname(os.path.abspath(__file__))
RN = os.path.join(ROOT, "data", "r_native")
V2D = os.path.join(ROOT, "r_native_v2", "data")
PORT = 8900
app = Flask(__name__)


def _j(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _age(ts):
    try:
        return max(0.0, time.time() - float(ts))
    except Exception:
        return None


def _mtime_age(path):
    return _age(os.path.getmtime(path)) if os.path.exists(path) else None


def gather():
    ap = _j(os.path.join(RN, "autopilot_status.json")) or {}
    pnl = _j(os.path.join(RN, "pnl_scoreboard.json")) or {}
    dd = _j(os.path.join(RN, "dd_recovery_state.json")) or {}
    mg = _j(os.path.join(RN, "margin_usage.json")) or {}
    fl = _j(os.path.join(RN, "master_floor_state.json")) or {}
    army = _j(os.path.join(RN, "army_scoreboard.json")) or {}
    eg = _j(os.path.join(RN, "edge_guard.json")) or {}
    hof = _j(os.path.join(RN, "hall_of_fame", "index.json")) or {}
    wd = _j(os.path.join(RN, "watchdog_status.json")) or {}
    hist = _j(os.path.join(RN, "pnl_history.json")) or {}

    equity = ap.get("equity", pnl.get("equity"))
    balance = ap.get("balance", pnl.get("balance"))
    floating = ap.get("float", pnl.get("floating"))
    eq = equity or 0

    acct = {"equity": equity, "balance": balance, "float": floating,
            "float_pct": (100.0 * floating / eq) if (floating is not None and eq) else None,
            "dd_pct": dd.get("drawdown_pct"),
            "margin_level": ap.get("margin_level", mg.get("margin_level")),
            "positions": ap.get("open_positions")}

    peak, floor = fl.get("peak"), fl.get("floor")
    floor_age = _mtime_age(os.path.join(RN, "master_floor_state.json"))
    floor_d = {"peak": peak, "floor": floor,
               "dist_pct": (100.0 * (eq - floor) / eq) if (floor is not None and eq) else None,
               "room_pct": (100.0 * (eq - floor) / (peak - floor)) if (peak and floor is not None and (peak - floor) > 0) else None,
               "breached": bool(floor is not None and eq and eq <= floor),
               "kill": os.path.exists(os.path.join(ROOT, "kill_switch.txt")),
               "alive": bool(floor_age is not None and floor_age < 60)}

    stats = army.get("stats", {}) or {}
    pn = ps = 0.0
    proven = explore = banned = 0
    rows = []
    for sym, v in stats.items():
        nn = v.get("n", 0); sr = v.get("sumR", 0.0)
        pn += nn; ps += sr
        e = (sr / nn) if nn else 0.0
        if nn >= 15 and e * math.sqrt(nn) > 2.0:
            proven += 1
        elif nn >= 4 and e < -0.05:
            banned += 1
        else:
            explore += 1
        rows.append({"sym": sym, "n": nn, "expR": round(e, 3)})
    pe = (ps / pn) if pn else 0.0
    pt = pe * math.sqrt(pn) if pn else 0.0
    rows.sort(key=lambda r: -r["expR"])
    learning = {"pooled_n": int(pn), "expR": round(pe, 4), "t": round(pt, 2),
                "verdict": ("EDGE" if pt > 2 else ("LOSER" if pt < -2 else "NO_EDGE")),
                "proven": proven, "explore": explore, "banned": banned, "top": rows[:8]}

    agg = defaultdict(lambda: [0, 0.0, 0]); nsym = 0
    for f in glob.glob(os.path.join(V2D, "indicator_accuracy_*.json")):
        d = _j(f)
        if not d:
            continue
        nsym += 1
        for ind, vv in (d.get("accuracy") or {}).items():
            agg[ind][0] += 1; agg[ind][1] += vv.get("hit_rate", 0.0); agg[ind][2] += vv.get("votes", 0)
    mrows = sorted([{"ind": k, "acc": round(100 * s[1] / s[0], 1), "votes": s[2]}
                    for k, s in agg.items() if s[0]], key=lambda r: -r["acc"])
    minds = {"n_symbols": nsym, "top": mrows[:10],
             "n_over52": sum(1 for r in mrows if r["acc"] >= 52.0), "total": len(mrows),
             "best": mrows[0]["acc"] if mrows else None}

    disc = {"score": eg.get("discipline_score"), "violations": eg.get("active_violations") or [],
            "reminder": eg.get("edge_reminder"), "n_manual": eg.get("n_manual"),
            "recent_opens": eg.get("recent_opens_15m")}

    genomes = list(hof.values()) if isinstance(hof, dict) else []
    gens = [g.get("generation", 0) for g in genomes if isinstance(g, dict)]
    fleet = {"alive": wd.get("n_alive"), "total": wd.get("n_total"),
             "genomes": len(genomes), "max_gen": max(gens) if gens else 0}

    curve = (hist.get("curve") or [])[-80:]
    feed = []
    try:
        with open(os.path.join(RN, "agents", "insights.jsonl"), encoding="utf-8-sig") as f:
            for ln in f.readlines()[-7:]:
                it = json.loads(ln)
                feed.append({"agent": it.get("agent", "?"), "msg": (it.get("message", "") or "")[:90],
                             "level": it.get("level", "")})
    except Exception:
        pass

    # ruflo honest status
    ruflo = {"plugins": [], "procs": 0, "data_active": False, "skills": 0, "mem_kb": 0, "agents_available": 89}
    try:
        ip = _j(os.path.join(os.path.expanduser("~"), ".claude", "plugins", "installed_plugins.json")) or {}
        ruflo["plugins"] = [k for k in (ip.get("plugins") or {}) if "ruflo" in k]
    except Exception:
        pass
    try:
        sk = os.path.join(os.path.expanduser("~"), ".claude", "skills")
        ruflo["skills"] = sum(1 for s in ("agent-workflow", "workflow-automation", "security-audit",
                                          "github-workflow-automation", "memory-management", "github-automation")
                              if os.path.isdir(os.path.join(sk, s)))
    except Exception:
        pass
    try:
        import psutil
        c = 0
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                nm = (p.info["name"] or "").lower(); cl = " ".join(p.info["cmdline"] or [])
                if ("node" in nm or "pythonw" in nm) and ("claude-flow" in cl or ".claude-flow" in cl):
                    c += 1
            except Exception:
                pass
        ruflo["procs"] = c
    except Exception:
        pass
    try:
        logs = os.path.join(ROOT, ".claude-flow", "logs")
        ruflo["data_active"] = bool(os.path.isdir(logs) and os.listdir(logs))
        sw = os.path.join(ROOT, ".swarm", "memory.db")
        ruflo["mem_kb"] = round(os.path.getsize(sw) / 1024, 1) if os.path.exists(sw) else 0
    except Exception:
        pass
    ruflo["running"] = ruflo["procs"] > 0 and ruflo["data_active"]

    return {"ts": time.time(), "iso": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            "account": acct, "floor": floor_d, "learning": learning, "minds": minds,
            "discipline": disc, "fleet": fleet, "curve": curve, "feed": feed, "ruflo": ruflo}


@app.route("/api/data")
def api_data():
    try:
        return jsonify(gather())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FRIDAY — لوحة القيادة</title>
<style>
:root{--card:#141b2d;--card2:#1b2438;--bd:#243049;--tx:#e6edf7;--dim:#8a98b5;
--grn:#34d399;--red:#f87171;--ylw:#fbbf24;--cy:#38bdf8;--mag:#c084fc;}
*{box-sizing:border-box;font-family:"Segoe UI","Tahoma",sans-serif}
body{margin:0;background:linear-gradient(160deg,#0b0f1a,#0d1322);color:var(--tx);padding:14px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px}
.top h1{font-size:18px;margin:0;color:var(--cy)}
.badge{font-size:12px;color:var(--dim)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tabs button{background:var(--card);border:1px solid var(--bd);color:var(--dim);border-radius:20px;
padding:7px 14px;font-size:13px;cursor:pointer;font-family:inherit;transition:.15s}
.tabs button:hover{color:var(--tx)}
.tabs button.on{background:var(--cy);color:#05101e;border-color:var(--cy);font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.panel{display:none}.panel.on{display:block}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px;box-shadow:0 6px 20px rgba(0,0,0,.25)}
.card.wide{grid-column:1/-1}
.card h2{font-size:14px;margin:0 0 10px;color:var(--cy)}
.kv{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.kv .b{background:var(--card2);border-radius:9px;padding:8px 10px}
.kv .b small{color:var(--dim);font-size:11px;display:block;margin-bottom:3px}
.kv .b b{font-size:17px}
.grn{color:var(--grn)}.red{color:var(--red)}.ylw{color:var(--ylw)}.cy{color:var(--cy)}.mag{color:var(--mag)}.dim{color:var(--dim)}
.bar{height:10px;background:var(--card2);border-radius:6px;overflow:hidden;margin:8px 0}
.bar>i{display:block;height:100%;border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:5px 8px;text-align:right;border-bottom:1px solid var(--bd)}
th{color:var(--dim);font-weight:600;font-size:11px}
.feed div{font-size:12px;padding:4px 0;border-bottom:1px solid var(--bd);color:var(--dim)}
.big{font-size:26px;font-weight:800}
.note{font-size:11px;color:var(--dim);margin-top:8px;line-height:1.5}
svg{width:100%}
.verdict{font-size:13px;font-weight:800;padding:6px 10px;border-radius:9px;display:inline-block}
.hb{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px}
.hb .lbl{width:90px;color:var(--dim);flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb .tr{flex:1;background:var(--card2);border-radius:5px;height:16px;overflow:hidden}
.hb .tr>i{display:block;height:100%;border-radius:5px}
.hb .vl{width:60px;text-align:left;flex-shrink:0}
</style></head><body>
<div class="top"><h1>⚡ FRIDAY — لوحة القيادة الموحّدة</h1><span class="badge" id="upd">يحمّل…</span></div>
<div class="tabs" id="tabs"></div><div id="panels"></div>
<script>
const $=(h)=>{const d=document.createElement('div');d.innerHTML=h;return d.firstElementChild};
function col(v,g,r){return v==null?'dim':(v>=g?'grn':(v<=r?'red':'ylw'))}
function cc(v,g,r){return v==null?'#8a98b5':(v>=g?'#34d399':(v<=r?'#f87171':'#fbbf24'))}
function money(v){return v==null?'—':(v>=0?'+':'')+Number(v).toLocaleString(undefined,{maximumFractionDigits:2})}
function spark(curve){if(!curve||curve.length<2)return '<svg height=90></svg>';
const ys=curve.map(p=>p[1]),lo=Math.min(...ys),hi=Math.max(...ys),rng=(hi-lo)||1,W=600,H=90;
const pts=curve.map((p,i)=>(i/(curve.length-1)*W).toFixed(1)+','+(H-(p[1]-lo)/rng*H).toFixed(1)).join(' ');
const up=ys[ys.length-1]>=ys[0];
return '<svg viewBox="0 0 '+W+' '+H+'" height=90 preserveAspectRatio="none"><polyline points="'+pts+'" fill="none" stroke="'+(up?'#34d399':'#f87171')+'" stroke-width="2"/></svg>';}
function hbars(items){return items.map(it=>'<div class="hb"><span class="lbl">'+it.lbl+'</span><span class="tr"><i style="width:'+Math.max(2,Math.min(100,it.frac*100)).toFixed(0)+'%;background:'+it.color+'"></i></span><span class="vl" style="color:'+it.color+'">'+it.disp+'</span></div>').join('')}
const TABS=[['ov','نظرة عامة'],['tr','التداول'],['lr','التعلّم والعقول'],['di','الانضباط'],['ev','التطوّر'],['rf','ruflo']];
function setTab(t){document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t==t));
document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id=='p_'+t));}
function initTabs(){const tb=document.getElementById('tabs'),pn=document.getElementById('panels');
TABS.forEach(([t,n])=>{const b=document.createElement('button');b.textContent=n;b.dataset.t=t;b.onclick=()=>setTab(t);tb.appendChild(b);
const p=document.createElement('div');p.className='panel';p.id='p_'+t;p.innerHTML='<div class="grid" id="g_'+t+'"></div>';pn.appendChild(p);});
setTab('ov');}
initTabs();

function cAcc(d){const a=d.account,f=d.floor;return '<div class="card wide"><h2>💰 الحساب + 🛑 حاجز الكارثة</h2><div class="kv">'+
'<div class="b"><small>الحقوق</small><b class="cy">$'+(a.equity!=null?a.equity.toFixed(2):'—')+'</b></div>'+
'<div class="b"><small>الرصيد</small><b>$'+(a.balance!=null?a.balance.toFixed(2):'—')+'</b></div>'+
'<div class="b"><small>العائم</small><b class="'+col(a.float_pct,0,-100)+'">'+money(a.float)+'</b></div>'+
'<div class="b"><small>السحب%</small><b class="'+(a.dd_pct==null?'dim':(a.dd_pct<10?'grn':a.dd_pct<15?'ylw':'red'))+'">'+(a.dd_pct!=null?a.dd_pct.toFixed(2)+'%':'—')+'</b></div>'+
'<div class="b"><small>هامش%</small><b>'+(a.margin_level!=null?Math.round(a.margin_level)+'%':'—')+'</b></div>'+
'<div class="b"><small>مراكز</small><b>'+(a.positions!=null?a.positions:'—')+'</b></div></div>'+spark(d.curve)+
'<div class="note">القمة <span class="cy">$'+(f.peak!=null?f.peak.toFixed(2):'—')+'</span> · الأرضية <span class="red">$'+(f.floor!=null?f.floor.toFixed(2):'—')+'</span>'+
(f.dist_pct!=null?' · المسافة <b class="'+(f.dist_pct>10?'grn':'red')+'">'+f.dist_pct.toFixed(1)+'%</b>':'')+'</div>'+
'<div class="bar"><i style="width:'+(f.room_pct!=null?Math.max(0,Math.min(100,f.room_pct)):0)+'%;background:'+(f.breached?'#f87171':'#34d399')+'"></i></div>'+
'<div class="note">master_floor: '+(f.alive?'<span class="grn">حيّ</span>':'<span class="red">لا نبض</span>')+' · الإيقاف: '+(f.kill?'<span class="red">مفعّل</span>':'<span class="grn">خامل</span>')+' · تتبّع 50% من القمة (يُقفل الربح)</div></div>';}

function cScore(d){const l=d.learning;const items=l.top.map(r=>({lbl:r.sym,disp:(r.expR>=0?'+':'')+r.expR,color:cc(r.expR,0.0001,-0.0001),frac:Math.min(1,Math.abs(r.expR)/0.5)}));
return '<div class="card"><h2>📊 توقّع الفرق (expR)</h2>'+hbars(items)+'<div class="note">أعلى الفرق (إجمالي/داخل-عيّنة). أخضر=موجب — لكن لا أحد معنوي net-of-cost.</div></div>';}

function cMinds(d){const m=d.minds;const items=m.top.map(r=>({lbl:r.ind,disp:r.acc+'%',color:r.acc>=55?'#34d399':r.acc>=52?'#fbbf24':r.acc<48?'#f87171':'#8a98b5',frac:(r.acc-45)/15}));
return '<div class="card"><h2>🎯 دقّة القراءات (الحقيقة)</h2>'+hbars(items)+'<div class="note">عبر <b>'+m.n_symbols+'</b> رمز · فوق 52% = <b class="'+(m.n_over52?'grn':'red')+'">'+m.n_over52+'/'+m.total+'</b> · 50%=رمية عملة → القراءات ≈ صدفة.</div></div>';}

function cLearn(d){const l=d.learning;return '<div class="card"><h2>🧠 التعلّم الذاتي (السبورة الظلّية)</h2>'+
'<div class="big cy">t ≈ '+l.t+'</div><div class="note">إجمالي/داخل-العيّنة (gross بلا سبريد) · n=<b>'+l.pooled_n+'</b> · expR=<b class="'+col(l.expR,0.0001,-0.0001)+'">'+(l.expR>=0?'+':'')+l.expR+'R</b></div>'+
'<div class="verdict" style="background:#3a1d1d;color:#f87171;margin-top:6px">الاختبار الصارم (OOS صافي): لا حافّة مُثبتة</div>'+
'<div class="note">⚠ حتى لو t&gt;2 هنا فهو إجمالي ويتأثّر بالسلسلة الرابحة (ضوضاء). كل المختبرات الصارمة = NO_EDGE.</div>'+
'<div class="kv" style="margin-top:8px"><div class="b"><small>🏅 PROVEN</small><b class="grn">'+l.proven+'</b></div><div class="b"><small>⚪ EXPLORE</small><b class="ylw">'+l.explore+'</b></div><div class="b"><small>🚫 BANNED</small><b class="red">'+l.banned+'</b></div></div></div>';}

function cDisc(d){const di=d.discipline,ds=di.score;return '<div class="card"><h2>🛡️ حارس الانضباط (حافّتك الحقيقية)</h2>'+
'<div class="big '+(ds==null?'dim':(ds>=80?'grn':ds>=50?'ylw':'red'))+'">'+(ds!=null?ds:'—')+'<span style="font-size:13px">/100</span></div>'+
'<div class="bar"><i style="width:'+(ds||0)+'%;background:'+(ds>=80?'#34d399':ds>=50?'#fbbf24':'#f87171')+'"></i></div>'+
'<div class="note">يدوي مفتوح: '+(di.n_manual!=null?di.n_manual:'—')+' · فتح 15د: '+(di.recent_opens!=null?di.recent_opens:'—')+' · على كل العملات</div>'+
((di.violations&&di.violations.length)?'<table style="margin-top:6px"><tr><th>مخالفة نشطة</th><th>الرمز</th></tr>'+di.violations.map(v=>'<tr><td class="red">'+v.tag+'</td><td>'+v.sym+'</td></tr>').join('')+'</table>':'<div class="note grn">✓ لا مخالفات — منضبط</div>')+
'<div class="note">'+(di.reminder||'')+'</div></div>';}

function cFleet(d){const fl=d.fleet;return '<div class="card wide"><h2>🚀 الأسطول + 🧬 التطوّر</h2><div class="kv">'+
'<div class="b"><small>محرّكات حيّة</small><b class="'+((fl.alive>=fl.total)?'grn':'ylw')+'">'+(fl.alive!=null?fl.alive:'—')+'/'+(fl.total!=null?fl.total:'—')+'</b></div>'+
'<div class="b"><small>جينومات</small><b class="mag">'+fl.genomes+'</b></div>'+
'<div class="b"><small>أقصى جيل</small><b>'+fl.max_gen+'</b></div></div>'+
'<div class="feed" style="margin-top:8px">'+d.feed.map(x=>'<div><b class="'+(x.level=='ACT'?'ylw':x.level=='WARN'?'red':'cy')+'">'+x.agent+'</b> '+x.msg+'</div>').join('')+'</div></div>';}

function cRuflo(d){const r=d.ruflo||{};const run=r.running;return '<div class="card wide"><h2>🤖 حالة ruflo — هل يطوّر فعلاً؟</h2>'+
'<div class="big '+(run?'grn':'red')+'">'+(run?'يعمل ويطوّر':'لا يعمل / لا يطوّر')+'</div><div class="kv" style="margin-top:8px">'+
'<div class="b"><small>عمليات حيّة</small><b class="'+(r.procs>0?'grn':'red')+'">'+r.procs+'</b></div>'+
'<div class="b"><small>إضافات مثبّتة</small><b>'+(r.plugins||[]).length+'</b></div>'+
'<div class="b"><small>مهارات متاحة</small><b class="cy">'+(r.skills||0)+'</b></div>'+
'<div class="b"><small>نشاط (logs)</small><b class="'+(r.data_active?'grn':'red')+'">'+(r.data_active?'نعم':'لا')+'</b></div>'+
'<div class="b"><small>ذاكرة swarm</small><b>'+(r.mem_kb||0)+' KB</b></div>'+
'<div class="b"><small>وكلاء كقوالب</small><b class="mag">'+(r.agents_available||0)+'</b></div></div>'+
'<div class="verdict" style="background:'+(run?'#1d3a28':'#3a1d1d')+';color:'+(run?'#34d399':'#f87171')+';margin-top:8px">'+
(run?'ruflo نشِط':'ruflo لا يطوّر/يضيف استراتيجيات — محرّكه (daemon/MCP) لا يعمل على ويندوز')+'</div>'+
'<div class="note">المثبّت: '+((r.plugins||[]).join(', ')||'لا شيء')+'. الوكلاء/المهارات قوالب أستدعيها يدوياً عبر Workflow، لا عملية ذاتية تقرأ السوق أو تضيف استراتيجيات. <b>اللي يطوّر فعلاً = محرّكات FRIDAY ('+d.fleet.genomes+' جينوم، السبورة، الأسطول).</b></div></div>';}

const LAYOUT={ov:[cAcc,cDisc,cLearn],tr:[cAcc,cScore],lr:[cLearn,cMinds,cScore],di:[cDisc],ev:[cFleet],rf:[cRuflo]};
async function tick(){let d;try{d=await(await fetch('/api/data')).json()}catch(e){return}
if(d.error){document.getElementById('upd').textContent='خطأ: '+d.error;return}
const r=d.ruflo||{};document.getElementById('upd').textContent='آخر تحديث '+d.iso+' · تحديث 3ث · ruflo: '+(r.running?'يعمل':'لا يعمل');
for(const t in LAYOUT){const g=document.getElementById('g_'+t);if(!g)continue;g.innerHTML='';
LAYOUT[t].forEach(fn=>{try{g.appendChild($(fn(d)))}catch(e){}});}}
tick();setInterval(tick,3000);
</script></body></html>"""


if __name__ == "__main__":
    print(f"[DASHBOARD] FRIDAY web dashboard -> http://127.0.0.1:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
