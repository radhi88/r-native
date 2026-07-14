"""friday_brain_view.py — لوحة بصريّة حيّة: الوكلاء وهم يعملون + الجينات وهي تتطوّر.

تقرأ ملفات البيانات الحيّة وتعرضها على http://127.0.0.1:5056 (تحديث كل 2ث):
  • 🧬 الجين الحيّ (specialist/XAUUSDm/memory.json): عدّاد الجيل يصعد لحظيًّا + الحالة + الأداء + سبارك‑لاين.
  • 🤖 الوكلاء: محرّك القرار (friday_decision) + gold_live (الصفقات) + brain (مع وسم "متجمّد" لو قديم).

تشغيل:  python friday_brain_view.py     ثم افتح http://127.0.0.1:5056
"""
from flask import Flask, jsonify, Response
import json, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\Radhi\MT5")
D = ROOT / "r_native_v2" / "data"
GENE = D / "specialist" / "XAUUSDm" / "memory.json"
SDK = D / "sdk_decision.json"
BRAIN = D / "brain_live__XAUUSDm.json"
GOLDOUT = D / "gold_live.out"
LINEAGE = D / "genome_lineage.jsonl"
LIVECFG = D / "scalp_live_config.json"   # ما يتداول به gold_live فعلاً (scalp_evolver)

app = Flask(__name__)
_gen_hist = []  # [(ts, generation)] — لرسم تطوّر الجيل حيًّا


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age_epoch(ts):
    try:
        return round(time.time() - float(ts))
    except Exception:
        return None


def _age_iso(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - d).total_seconds())
    except Exception:
        return None


@app.route("/api/brain")
def api_brain():
    out = {"now": datetime.now(timezone.utc).strftime("%H:%M:%S")}

    # ── 🧬 الجين ──
    g = _load(GENE)
    gen = g.get("generation")
    if gen is not None:
        if not _gen_hist or _gen_hist[-1][1] != gen:
            _gen_hist.append((time.time(), gen))
            del _gen_hist[:-150]
    best = g.get("best", {}) or {}
    gcfg = best.get("config", {}) or {}
    h1 = best.get("h1", {}) or {}; h2 = best.get("h2", {}) or {}
    out["gene"] = {
        "generation": gen, "state": g.get("state"), "tested": g.get("tested"),
        "score": best.get("score"), "config": gcfg,
        "pf_h1": h1.get("pf"), "pf_h2": h2.get("pf"),
        "exp_h1": h1.get("expectancy"), "exp_h2": h2.get("expectancy"),
        "trades": (h1.get("trades") or 0) + (h2.get("trades") or 0),
        "updated_age": _age_epoch(g.get("updated")),
        "hist": [v for _, v in _gen_hist],
    }

    # ── الإعداد الفعّال الذي يتداول به gold_live (من _scalp_over) + هل الجين مُستخدم؟ ──
    lc = _load(LIVECFG)
    active = {}
    try:
        import gold_live as _gl
        active = {k: v for k, v in _gl._scalp_over().items() if not k.startswith("_")}
    except Exception:
        active = lc.get("config", {}) or {}
    out["live_cfg"] = {"config": active, "recent_net": lc.get("recent_net"),
                       "note": lc.get("note"), "age": _age_epoch(lc.get("updated"))}
    out["gene_used"] = bool(active and gcfg and active.get("tf") == gcfg.get("tf")
                            and str(active.get("ema")) == str(gcfg.get("ema")))

    # ── 📊 مؤشرات لحظيّة حقيقيّة (محرّكاتنا) ──
    ind = {}
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        import chart_read as _cr
        cd = _cr.read_local(mt5, "XAUUSDm", "M15")
        if cd:
            ind.update({"dir": cd.get("dir"), "confluence": cd.get("confluence"),
                        "regime": cd.get("regime"), "votes": cd.get("votes", {}),
                        "price": cd.get("price")})
        r = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_M15, 0, 200)
        if r is not None and len(r) > 40:
            closes = [float(x["close"]) for x in r]
            import live_quant as _lq
            er = _lq.efficiency_ratio(closes, len(closes) - 1, 20)
            ind["er"] = round(er, 3); ind["chop"] = er < 0.30
        import live_structure as _ls
        st = _ls.read(mt5, "XAUUSDm", mt5.TIMEFRAME_M15)
        if st:
            ind["nr"] = st.get("nearest_resistance"); ind["ns"] = st.get("nearest_support")
    except Exception as e:
        ind["err"] = str(e)[:90]
    out["ind"] = ind

    # ── 🤖 محرّك القرار (friday_decision) ──
    sd = _load(SDK)
    out["sdk"] = {"bias": sd.get("bias"), "confidence": sd.get("confidence"),
                  "regime": sd.get("regime"), "engine": sd.get("engine"),
                  "reason": (sd.get("reason") or "")[:160], "age": _age_epoch(sd.get("ts"))}

    # ── 🤖 وكلاء brain ──
    b = _load(BRAIN)
    out["brain"] = {"session": b.get("session"), "bid": b.get("bid"), "spread": b.get("spread"),
                    "age": _age_iso(b.get("ts"))}

    # ── 🤖 gold_live (الصفقات الحيّة) ──
    gold = {}
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        pos = [p for p in (mt5.positions_get() or []) if p.magic == 99791]
        a = mt5.account_info()
        gold = {"count": len(pos), "float": round(sum(p.profit for p in pos), 2),
                "equity": round(a.equity, 2) if a else None,
                "pos": [{"side": "BUY" if p.type == 0 else "SELL", "vol": p.volume,
                         "open": p.price_open, "float": round(p.profit, 2)} for p in pos]}
    except Exception:
        pass
    try:
        gold["last"] = [l for l in GOLDOUT.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()][-1]
    except Exception:
        pass
    out["gold"] = gold
    return jsonify(out)


HTML = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FRIDAY · الوكلاء والجينات</title>
<style>
:root{--bg:#0b0e14;--fg:#e6edf3;--dim:#8b949e;--g:#3fb950;--r:#f85149;--y:#d29922;--acc:#58a6ff;--p:#bc8cff;--card:#11151c;--bd:#1f2630}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Segoe UI,Arial}
.wrap{max-width:1040px;margin:0 auto;padding:16px}
h1{font-size:16px;color:var(--dim);font-weight:700;margin:4px 0 12px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-inline-start:6px;vertical-align:middle}
.row{display:grid;gap:12px}.r3{grid-template-columns:repeat(3,1fr)}.r2{grid-template-columns:1.3fr 1fr}
@media(max-width:780px){.r3,.r2{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px}
.card h2{font-size:12px;color:var(--dim);margin:0 0 8px;font-weight:600;letter-spacing:.3px}
.gen{font-size:64px;font-weight:800;letter-spacing:-2px;line-height:1}
.gen .lbl{font-size:13px;color:var(--dim);font-weight:600}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
.b-prov{background:#1f2d1f;color:var(--g);border:1px solid #2ea04333}
.b-stale{background:#2d1f1f;color:var(--r);border:1px solid #f8514933}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:#0d1117;border:1px solid var(--bd);border-radius:8px;padding:3px 8px;font-size:12px;color:var(--dim)}
.chip b{color:var(--fg)}
.kv{display:flex;justify-content:space-between;margin:4px 0;font-size:13px}.kv .k{color:var(--dim)}
.big{font-size:28px;font-weight:800}
.bar{height:8px;background:#0d1117;border-radius:6px;overflow:hidden;margin-top:6px;border:1px solid var(--bd)}
.bar>i{display:block;height:100%;border-radius:6px}
.up{color:var(--g)}.down{color:var(--r)}.neu{color:var(--y)}
canvas{width:100%;height:90px;margin-top:8px}
.muted{color:var(--dim);font-size:12px}
.live{font-size:11px;color:var(--dim)}
</style></head><body><div class="wrap">
<h1>🧬🤖 FRIDAY · الوكلاء والجينات حيًّا <span id="dot" class="dot"></span> <span id="now" class="live"></span></h1>

<div class="card" id="usecard" style="margin-bottom:12px;border-width:2px">
  <h2>❓ هل الجين المُتطوّر مُستخدم في الصفقات الحيّة؟</h2>
  <div class="big" id="useans" style="font-size:32px">—</div>
  <div class="muted" id="usewhy" style="margin-top:6px"></div>
</div>

<div class="row r2" style="margin-bottom:12px">
  <div class="card">
    <h2>🧬 أداء الجين وكفاءته — XAUUSDm <span id="gdot" class="dot"></span></h2>
    <div class="row r3" style="margin-bottom:8px">
      <div><div class="muted">PF · نصف1</div><div class="big" id="pf1">—</div></div>
      <div><div class="muted">PF · نصف2</div><div class="big" id="pf2">—</div></div>
      <div><div class="muted">النقاط</div><div class="big" id="score">—</div></div>
    </div>
    <div class="kv"><span class="k">التوقّع/صفقة (expectancy) نصف1 · نصف2</span><b id="exp">—</b></div>
    <div class="kv"><span class="k">عدد صفقات الاختبار</span><b id="trades">—</b></div>
    <div class="kv"><span class="k">إعداد الجين</span><b id="gcfg" style="font-size:12px">—</b></div>
    <div class="muted" id="gline" style="margin-top:6px"></div>
    <canvas id="spark" style="height:60px"></canvas>
  </div>
  <div class="card">
    <h2>▶ ما يتداول به gold_live فعلاً <span id="ldot" class="dot"></span></h2>
    <div class="muted" style="margin-bottom:6px">مصدره scalp_evolver (لا الجين)</div>
    <div class="chips" id="lconf"></div>
    <div class="kv" style="margin-top:8px"><span class="k">صافي حديث (recent_net)</span><b id="lnet">—</b></div>
    <div class="muted" id="lnote"></div>
    <div class="muted" id="lage" class="live"></div>
  </div>
</div>

<div class="row r3">
  <div class="card">
    <h2>🤖 محرّك القرار (friday_decision) <span id="sdot" class="dot"></span></h2>
    <div class="big" id="sbias">—</div>
    <div class="muted">ريجيم: <span id="sreg">—</span> · محرّك: <span id="seng">—</span> · <span id="sage" class="live"></span></div>
    <div class="bar"><i id="sbar" style="width:0;background:var(--acc)"></i></div>
    <div class="muted" id="sreason" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>🤖 gold_live — التداول الحيّ <span id="godot" class="dot"></span></h2>
    <div class="big">صفقات: <span id="gocount">—</span></div>
    <div class="kv"><span class="k">عائم</span><b id="gofloat">—</b></div>
    <div class="kv"><span class="k">إكويتي</span><b id="goeq">—</b></div>
    <div id="gopos" class="muted"></div>
    <div class="muted" id="golast" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>🤖 وكلاء brain (٣١) <span id="bdot" class="dot"></span></h2>
    <div id="bbadge"></div>
    <div class="kv"><span class="k">الجلسة</span><b id="bsess">—</b></div>
    <div class="kv"><span class="k">سعر brain</span><b id="bbid">—</b></div>
    <div class="kv"><span class="k">سبريد</span><b id="bspr">—</b></div>
    <div class="muted" id="bage" style="margin-top:8px"></div>
  </div>
</div>
<div class="card" style="margin-top:12px">
  <h2>📊 مؤشرات لحظيّة — XAUUSDm M15 <span id="idot" class="dot"></span></h2>
  <div class="row r3" style="margin-bottom:8px">
    <div><div class="muted">القرار الموحّد (chart_read)</div><div class="big" id="icdir">—</div><div class="bar"><i id="icbar" style="width:0"></i></div></div>
    <div><div class="muted">كفاءة الحركة ER</div><div class="big" id="ier">—</div><div class="muted" id="ierb"></div></div>
    <div><div class="muted">ريجيم Markov</div><div class="big" id="ireg">—</div></div>
  </div>
  <div class="muted">أصوات المؤشرات (كل مؤشّر منفردًا · ▲ شراء ▼ بيع • محايد):</div>
  <div class="chips" id="ivotes" style="margin-top:6px"></div>
  <div class="row r2" style="margin-top:10px">
    <div class="kv"><span class="k">أقرب مقاومة</span><b id="inr" class="down">—</b></div>
    <div class="kv"><span class="k">أقرب دعم</span><b id="ins" class="up">—</b></div>
  </div>
  <div class="muted" id="ierr"></div>
</div>
<div class="muted" style="margin-top:10px">🟢 حيّ (محدّث الآن) · 🔴 متجمّد. اللوحة تقرأ محرّكات النظام الفعليّة مباشرة كل ٢ث.</div>
</div>
<script>
const $=id=>document.getElementById(id);
function dot(el,ok){el.style.background=ok?'var(--g)':'var(--r)'}
function fmt(n,d=2){return (n==null||isNaN(n))?'—':Number(n).toFixed(d)}
function ageTxt(a){return a==null?'—':(a<90?('منذ '+a+'ث'):a<5400?('منذ '+Math.round(a/60)+'د'):('منذ '+Math.round(a/3600)+'س ⚠'))}
let prevGen=null;
async function tick(){
 try{
  const d=await(await fetch('/api/brain',{cache:'no-store'})).json();
  $('now').textContent='UTC '+d.now; dot($('dot'),true);
  // ❓ الاستخدام
  const used=d.gene_used;
  $('useans').textContent = used ? '✅ نعم — الجين يقود الصفقات' : '❌ لا — الجين لا يُستخدم في التداول';
  $('useans').className = 'big '+(used?'up':'down');
  $('usewhy').textContent = used
    ? 'إعداد التداول الحيّ يطابق الجين المُتطوّر.'
    : 'gold_live في وضع SCALP يتداول بإعداد scalp_evolver (M1) — الجين المُتطوّر (M15) نائم رغم أن أداءه أفضل.';
  $('usecard').style.borderColor = used ? '#2ea04355' : '#f8514955';
  // 🧬 الجين — الأداء والكفاءة
  const g=d.gene||{};
  prevGen=g.generation;
  dot($('gdot'), g.updated_age!=null && g.updated_age<180);
  $('pf1').textContent=fmt(g.pf_h1,3); $('pf1').className='big '+(g.pf_h1>=1?'up':'down');
  $('pf2').textContent=fmt(g.pf_h2,3); $('pf2').className='big '+(g.pf_h2>=1?'up':'down');
  $('score').textContent=fmt(g.score,3); $('score').className='big '+(g.score>=1?'up':'down');
  $('exp').textContent='+'+fmt(g.exp_h1,3)+' · +'+fmt(g.exp_h2,3);
  $('exp').className=((g.exp_h1>0&&g.exp_h2>0)?'up':'neu');
  $('trades').textContent=g.trades??'—';
  const c=g.config||{};
  $('gcfg').textContent=Object.entries(c).map(([k,v])=>k+':'+v).join('  ');
  $('gline').textContent='جيل '+(g.generation??'—')+' · '+(g.state||'')+' · محدّث '+ageTxt(g.updated_age);
  spark(g.hist||[]);
  // ▶ ما يتداول به فعلاً
  const lc=d.live_cfg||{}, lcfg=lc.config||{};
  $('lconf').innerHTML=Object.entries(lcfg).map(([k,v])=>`<span class="chip">${k} <b>${v}</b></span>`).join('');
  $('lnet').textContent='$'+fmt(lc.recent_net); $('lnet').className=(lc.recent_net>=0?'up':'down');
  $('lnote').textContent=lc.note||''; $('lage').textContent='محدّث '+ageTxt(lc.age);
  dot($('ldot'), lc.age!=null && lc.age<600);
  // 🤖 friday_decision
  const s=d.sdk||{}; const sb=(s.bias||'—');
  $('sbias').textContent=sb; $('sbias').className='big '+(sb=='BUY'?'up':sb=='SELL'?'down':'neu');
  $('sreg').textContent=s.regime||'—'; $('seng').textContent=s.engine||'—';
  $('sage').textContent=ageTxt(s.age); dot($('sdot'), s.age!=null && s.age<420);
  $('sbar').style.width=Math.round((s.confidence||0)*100)+'%';
  $('sbar').style.background=sb=='BUY'?'var(--g)':sb=='SELL'?'var(--r)':'var(--y)';
  $('sreason').textContent=s.reason||'';
  // 🤖 gold_live
  const go=d.gold||{};
  $('gocount').textContent=go.count??'—';
  $('gofloat').textContent='$'+fmt(go.float); $('gofloat').className=(go.float>=0?'up':'down');
  $('goeq').textContent='$'+fmt(go.equity);
  $('gopos').innerHTML=(go.pos||[]).map(p=>`<div class="kv"><span class="k">${p.side} ${p.vol} @ ${fmt(p.open)}</span><b class="${p.float>=0?'up':'down'}">$${fmt(p.float)}</b></div>`).join('');
  $('golast').textContent=(go.last||'').replace('[GOLD-LIVE]','▶');
  dot($('godot'), !!go.last);
  // 📊 مؤشرات لحظيّة
  const ic=d.ind||{};
  const dirTxt=ic.dir==1?'BUY':ic.dir==-1?'SELL':'NEUTRAL';
  $('icdir').textContent=dirTxt; $('icdir').className='big '+(ic.dir==1?'up':ic.dir==-1?'down':'neu');
  $('icbar').style.width=Math.round((ic.confluence||0)*100)+'%';
  $('icbar').style.background=ic.dir==1?'var(--g)':ic.dir==-1?'var(--r)':'var(--y)';
  $('ier').textContent=fmt(ic.er,3); $('ier').className='big '+(ic.chop?'down':'up');
  $('ierb').textContent=(ic.er==null)?'':(ic.chop?'عرضي — لا دخول':'ترند ✓');
  $('ireg').textContent=ic.regime||'—'; $('ireg').className='big '+(ic.regime=='Bull'?'up':ic.regime=='Bear'?'down':'neu');
  const V=ic.votes||{};
  $('ivotes').innerHTML=Object.entries(V).map(([k,v])=>{const col=v>0?'var(--g)':v<0?'var(--r)':'var(--dim)';const a=v>0?'▲':v<0?'▼':'•';return `<span class="chip" style="border-color:${col};color:${col}">${k} ${a}</span>`;}).join('')||'—';
  const fmtSR=x=>{if(x==null)return '—';if(typeof x=='number')return fmt(x);if(Array.isArray(x))return fmt(x[0]);if(typeof x=='object')return fmt(x.price??x.level??x.value);return String(x);};
  $('inr').textContent=fmtSR(ic.nr); $('ins').textContent=fmtSR(ic.ns);
  dot($('idot'), !ic.err); $('ierr').textContent=ic.err?('⚠ '+ic.err):'';
  // 🤖 brain
  const b=d.brain||{}; const bstale=(b.age==null||b.age>600);
  $('bbadge').innerHTML=bstale?'<span class="badge b-stale">🔴 متجمّد — لا يكتب منذ يومين</span>':'<span class="badge b-prov">🟢 حيّ</span>';
  $('bsess').textContent=b.session||'—'; $('bbid').textContent=fmt(b.bid); $('bspr').textContent=fmt(b.spread);
  $('bage').textContent='آخر كتابة: '+ageTxt(b.age); dot($('bdot'), !bstale);
 }catch(e){ dot($('dot'),false); }
}
function spark(h){
 const c=$('spark'),dpr=devicePixelRatio||1; c.width=c.clientWidth*dpr; c.height=90*dpr;
 const x=c.getContext('2d'); x.clearRect(0,0,c.width,c.height);
 if(h.length<2){x.fillStyle='#8b949e';x.font=(12*dpr)+'px system-ui';x.fillText('يُجمّع تاريخ الجيل…',8*dpr,40*dpr);return;}
 const lo=Math.min(...h),hi=Math.max(...h),rng=(hi-lo)||1,W=c.width,H=c.height,pad=8*dpr;
 x.strokeStyle='#bc8cff';x.lineWidth=2*dpr;x.beginPath();
 h.forEach((v,i)=>{const px=pad+(W-2*pad)*i/(h.length-1),py=pad+(H-2*pad)*(1-(v-lo)/rng);i?x.lineTo(px,py):x.moveTo(px,py);});
 x.stroke();
 x.fillStyle='#8b949e';x.font=(11*dpr)+'px system-ui';x.fillText('جيل '+hi,pad,pad+11*dpr);x.fillText('جيل '+lo,pad,H-pad);
}
tick(); setInterval(tick,2000);
</script></body></html>"""


@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


if __name__ == "__main__":
    print("لوحة الوكلاء والجينات → http://127.0.0.1:5056", flush=True)
    app.run(host="127.0.0.1", port=5056, threaded=True)
