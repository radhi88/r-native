# -*- coding: utf-8 -*-
"""SMC + Agents Dashboard — port 5050"""
import json, csv, datetime
from collections import deque
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"
AGENTS_DIR  = Path(r"C:\Users\Radhi\MT5\agents")
BRAIN_DIR   = AGENTS_DIR / "brain_vault"
BRAIN_JSON  = BRAIN_DIR / "agent_minds.json"
TASKS_JSON  = BRAIN_DIR / "agent_tasks.json"
BLUEPRINTS_JSON = BRAIN_DIR / "agent_blueprints.json"
AUTOPILOT_JSON = BRAIN_DIR / "autopilot_status.json"
UNIFIED_JSON = AGENTS_DIR / "unified_signal.json"
LOG_MD      = BRAIN_DIR / "log.md"

PORT = 5050
DECISION_WINDOW_ROWS = 500

HTML = r"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🥇 SMC Gold Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,sans-serif;background:#0d1117;color:#e6edf3;direction:rtl}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #21262d}
.header h1{font-size:1.4rem;color:#f0c040}
.badge{background:#21262d;border-radius:20px;padding:4px 14px;font-size:.8rem;color:#8b949e}
#live-dot{width:10px;height:10px;border-radius:50%;background:#2ea043;display:inline-block;margin-left:6px;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;padding:16px}
.card{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:16px}
.card h2{font-size:1rem;color:#58a6ff;margin-bottom:12px;border-bottom:1px solid #21262d;padding-bottom:8px}
.stat-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #0d1117;font-size:.875rem}
.stat-row:last-child{border-bottom:none}
.stat-label{color:#8b949e}
.stat-val{font-weight:700;color:#e6edf3}
.green{color:#3fb950}.red{color:#f85149}.gold{color:#f0c040}.blue{color:#58a6ff}.purple{color:#bc8cff}
.chip{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.75rem;font-weight:700}
.chip-green{background:#1a3a1a;color:#3fb950;border:1px solid #3fb950}
.chip-red{background:#3a1a1a;color:#f85149;border:1px solid #f85149}
.chip-blue{background:#1a1a3a;color:#58a6ff;border:1px solid #58a6ff}
.chip-gray{background:#21262d;color:#8b949e}
.chip-yellow{background:#3a3000;color:#f0c040;border:1px solid #f0c040}
.progress-bar{height:6px;background:#21262d;border-radius:3px;margin-top:4px}
.progress-fill{height:6px;border-radius:3px;background:linear-gradient(90deg,#1158a6,#58a6ff)}
.stat-box{text-align:center;padding:12px;background:#0d1117;border-radius:8px;flex:1;margin:0 4px}
.stat-box .num{font-size:1.6rem;font-weight:700}
.stat-boxes{display:flex;margin-bottom:12px}
.table-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.78rem}
th{background:#21262d;padding:6px 8px;text-align:right;color:#8b949e;font-weight:600}
td{padding:5px 8px;border-bottom:1px solid #161b22}
tr:hover{background:#1c2128}
.bar-chart{display:flex;align-items:flex-end;gap:2px;height:40px;margin-top:8px}
.bar{background:#1158a6;border-radius:2px 2px 0 0;min-width:6px;flex:1;transition:all .3s}
.bar.entry{background:#3fb950}.bar.blocked{background:#f85149}.bar.other{background:#8b949e}
/* Agents panel */
.agent-card{display:flex;align-items:center;justify-content:space-between;padding:8px;background:#0d1117;border-radius:8px;margin-bottom:8px}
.agent-name{font-weight:700;font-size:.9rem}
.agent-role{font-size:.75rem;color:#8b949e}
.agent-status{font-size:.75rem}
.brain-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:8px}
.brain-item{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px}
.brain-title{font-weight:700;color:#e6edf3;margin-bottom:4px}
.brain-meta{font-size:.72rem;color:#8b949e}
.brain-msg{border-right:3px solid #58a6ff;padding:8px;margin:6px 0;background:#0d1117;border-radius:6px;font-size:.82rem}
.brain-task{border-right:3px solid #f0c040;padding:8px;margin:6px 0;background:#0d1117;border-radius:6px;font-size:.82rem}
.risk-green{color:#3fb950}.risk-yellow{color:#f0c040}.risk-red{color:#f85149}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🥇 SMC Gold — نظام التداول الذكي</h1>
    <span class="badge"><span id="live-dot"></span> تحديث كل ثانية</span>
  </div>
  <div style="text-align:left">
    <div style="font-size:.8rem;color:#8b949e" id="last-update">---</div>
    <div style="font-size:.75rem;color:#8b949e" id="data-source">XAUUSDm M1</div>
  </div>
</div>

<div class="grid">
<!-- EA Status -->
<div class="card">
  <h2>📈 حالة الـ EA</h2>
  <div class="stat-row"><span class="stat-label">الرصيد</span><span class="stat-val gold" id="balance">---</span></div>
  <div class="stat-row"><span class="stat-label">Equity</span><span class="stat-val" id="equity">---</span></div>
  <div class="stat-row"><span class="stat-label">P&L</span><span class="stat-val" id="pnl">---</span></div>
  <div class="stat-row"><span class="stat-label">Spread</span><span class="stat-val" id="spread">---</span></div>
  <div class="stat-row"><span class="stat-label">ATR</span><span class="stat-val" id="atr">---</span></div>
  <div class="stat-row"><span class="stat-label">EMA Direction</span><span class="stat-val" id="ema_dir">---</span></div>
  <div class="stat-row"><span class="stat-label">RSI</span><span class="stat-val" id="rsi">---</span></div>
  <div class="stat-row"><span class="stat-label">Regime</span><span class="stat-val" id="regime">---</span></div>
  <div class="stat-row"><span class="stat-label">Positions</span><span class="stat-val" id="positions">---</span></div>
  <div class="stat-row"><span class="stat-label">DNA Generation</span><span class="stat-val purple" id="generation">---</span></div>
  <div class="stat-row"><span class="stat-label">Bar Count</span><span class="stat-val" id="bar_count">---</span></div>
</div>

<!-- SMC Zones -->
<div class="card">
  <h2>🎯 مناطق SMC</h2>
  <div class="stat-row"><span class="stat-label">Order Blocks</span><span class="stat-val" id="ob_count">---</span></div>
  <div id="ob_bar" class="progress-bar"><div class="progress-fill" id="ob_fill" style="width:0%"></div></div>
  <div class="stat-row" style="margin-top:8px"><span class="stat-label">Fair Value Gaps</span><span class="stat-val" id="fvg_count">---</span></div>
  <div id="fvg_bar" class="progress-bar"><div class="progress-fill" id="fvg_fill" style="width:0%;background:linear-gradient(90deg,#8b3fa6,#bc8cff)"></div></div>
  <div class="stat-row" style="margin-top:12px">
    <span class="stat-label">BOS</span>
    <span id="bos_chip" class="chip chip-gray">---</span>
  </div>
  <div class="stat-row">
    <span class="stat-label">CHoCH</span>
    <span id="choch_chip" class="chip chip-gray">---</span>
  </div>
  <div class="stat-row">
    <span class="stat-label">Market Bias</span>
    <span id="bias_chip" class="chip chip-gray" style="font-size:1rem;padding:4px 16px">---</span>
  </div>
  <div class="stat-row"><span class="stat-label">BOS Level</span><span class="stat-val" id="bos_level">---</span></div>
  <div class="stat-row"><span class="stat-label">Swing High</span><span class="stat-val green" id="swing_high">---</span></div>
  <div class="stat-row"><span class="stat-label">Swing Low</span><span class="stat-val red" id="swing_low">---</span></div>
  <div class="stat-row"><span class="stat-label">SMC Status</span><span class="stat-val blue" id="smc_status">---</span></div>
</div>

<!-- Agents Panel -->
<div class="card">
  <h2>🤖 الوكلاء الذكيون</h2>
  <div id="agents-list">
    <div style="color:#8b949e;text-align:center;padding:20px">جاري التحميل...</div>
  </div>
  <div style="margin-top:12px;font-size:.78rem;color:#8b949e;text-align:center" id="agents-last-run">---</div>
  <div class="stat-row" style="margin-top:8px">
    <span class="stat-label">آخر تشغيل</span>
    <span class="stat-val" id="orch-last-run">---</span>
  </div>
</div>

<!-- PlutoBrain Agent Mind -->
<div class="card" style="grid-column:1/-1">
  <h2>🧠 عقل الوكلاء — PlutoBrain محلي</h2>
  <div class="stat-boxes">
    <div class="stat-box"><div class="num blue" id="brain_msgs">0</div><div style="font-size:.7rem;color:#8b949e">رسائل</div></div>
    <div class="stat-box"><div class="num gold" id="brain_tasks">0</div><div style="font-size:.7rem;color:#8b949e">مهام مفتوحة</div></div>
    <div class="stat-box"><div class="num purple" id="brain_blueprints">0</div><div style="font-size:.7rem;color:#8b949e">وكلاء مقترحون</div></div>
    <div class="stat-box"><div class="num green" id="brain_decision">---</div><div style="font-size:.7rem;color:#8b949e">قرار التقاطع</div></div>
    <div class="stat-box"><div class="num gold" id="brain_unified">---</div><div style="font-size:.7rem;color:#8b949e">Unified</div></div>
    <div class="stat-box"><div class="num blue" id="brain_autopilot">---</div><div style="font-size:.7rem;color:#8b949e">Fast Autopilot</div></div>
    <div class="stat-box"><div class="num gold" id="brain_llm">---</div><div style="font-size:.7rem;color:#8b949e">LLM</div></div>
  </div>
  <div class="brain-grid">
    <div class="brain-item">
      <div class="brain-title">ماذا تفكر الوكلاء الآن</div>
      <div id="brain_minds" class="brain-meta">جاري التحميل...</div>
    </div>
    <div class="brain-item">
      <div class="brain-title">رسائل بينهم</div>
      <div id="brain_messages" class="brain-meta">---</div>
    </div>
    <div class="brain-item">
      <div class="brain-title">المهام المسندة</div>
      <div id="brain_task_list" class="brain-meta">---</div>
    </div>
    <div class="brain-item">
      <div class="brain-title">وكلاء ينشأون كتصميم</div>
      <div id="brain_blueprint_list" class="brain-meta">---</div>
    </div>
  </div>
  <div style="margin-top:10px;font-size:.72rem;color:#8b949e" id="brain_paths">---</div>
</div>

<!-- Decision Stats -->
<div class="card">
  <h2>📊 إحصاءات القرارات</h2>
  <div class="stat-boxes">
    <div class="stat-box"><div class="num gold" id="total_dec">0</div><div style="font-size:.7rem;color:#8b949e">إجمالي</div></div>
    <div class="stat-box"><div class="num green" id="entry_dec">0</div><div style="font-size:.7rem;color:#8b949e">دخول</div></div>
    <div class="stat-box"><div class="num red" id="blocked_dec">0</div><div style="font-size:.7rem;color:#8b949e">محجوب</div></div>
    <div class="stat-box"><div class="num blue" id="entry_pct">0%</div><div style="font-size:.7rem;color:#8b949e">نسبة الدخول</div></div>
  </div>
  <div class="stat-row"><span class="stat-label">OB Hits</span><span class="stat-val" id="ob_hits">---</span></div>
  <div class="stat-row"><span class="stat-label">FVG Hits</span><span class="stat-val" id="fvg_hits">---</span></div>
  <div style="margin-top:8px;font-size:.75rem;color:#8b949e">آخر 40 قرار:</div>
  <div class="bar-chart" id="decision_chart"></div>
</div>

<!-- Decision Log -->
<div class="card" style="grid-column:1/-1">
  <h2>📋 سجل القرارات الأخيرة</h2>
  <div class="table-wrap">
    <table id="dec_table">
      <thead><tr>
        <th>الوقت</th><th>الاتجاه</th><th>OB</th><th>FVG</th><th>BOS</th><th>RSI</th><th>القرار</th><th>السبب</th><th>الرصيد</th><th>OBs</th><th>FVGs</th>
      </tr></thead>
      <tbody id="dec_body"></tbody>
    </table>
  </div>
</div>
</div>

<script>
async function refresh(){
  try{
    const s=await fetch('/api/status').then(r=>r.json());
    document.getElementById('last-update').textContent='آخر تحديث: '+new Date().toLocaleTimeString('ar');
    // EA
    const bal=parseFloat(s.balance||0);
    const eq=parseFloat(s.equity||bal);
    const pnl=eq-bal;
    document.getElementById('balance').textContent=(bal>0?bal.toFixed(2):'---')+'$';
    document.getElementById('equity').textContent=(eq>0?eq.toFixed(2):'---')+'$';
    const pnlEl=document.getElementById('pnl');
    pnlEl.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+'$';
    pnlEl.className='stat-val '+(pnl>=0?'green':'red');
    document.getElementById('spread').textContent=s.spread||'---';
    document.getElementById('atr').textContent=s.atr?parseFloat(s.atr).toFixed(2):'---';
    document.getElementById('ema_dir').textContent=s.ema_dir||'---';
    const rsi=parseFloat(s.rsi||0);
    const rsiEl=document.getElementById('rsi');
    rsiEl.textContent=rsi?rsi.toFixed(1):'---';
    rsiEl.className='stat-val '+(rsi>70?'red':rsi<30?'green':'');
    document.getElementById('regime').textContent=s.regime||'---';
    document.getElementById('positions').textContent=s.positions||'0';
    document.getElementById('generation').textContent=s.generation||'0';
    document.getElementById('bar_count').textContent=s.bar_count||'---';
    // SMC
    const ob=parseInt(s.smc_ob_count||0);
    const fvg=parseInt(s.smc_fvg_count||0);
    document.getElementById('ob_count').textContent=ob+' / 8';
    document.getElementById('fvg_count').textContent=fvg+' / 8';
    document.getElementById('ob_fill').style.width=(ob/8*100)+'%';
    document.getElementById('fvg_fill').style.width=(fvg/8*100)+'%';
    const bos=s.smc_has_bos;
    const choch=s.smc_has_choch;
    document.getElementById('bos_chip').className='chip '+(bos?'chip-green':'chip-gray');
    document.getElementById('bos_chip').textContent=bos?'✅ BOS نشط':'❌ BOS';
    document.getElementById('choch_chip').className='chip '+(choch?'chip-yellow':'chip-gray');
    document.getElementById('choch_chip').textContent=choch?'🔄 CHoCH':'— CHoCH';
    const bias=s.smc_bias||'NEUTRAL';
    const biasEl=document.getElementById('bias_chip');
    biasEl.textContent=bias==='BUY'?'🟢 BULLISH':bias==='SELL'?'🔴 BEARISH':'⚪ NEUTRAL';
    biasEl.className='chip '+(bias==='BUY'?'chip-green':bias==='SELL'?'chip-red':'chip-gray');
    document.getElementById('bos_level').textContent=parseFloat(s.smc_bos_level||0).toFixed(3)||'---';
    document.getElementById('swing_high').textContent=parseFloat(s.smc_swing_high||0).toFixed(3)||'---';
    document.getElementById('swing_low').textContent=parseFloat(s.smc_swing_low||0).toFixed(3)||'---';
    document.getElementById('smc_status').textContent=s.smc_status||'---';
  }catch(e){console.error(e)}
  
  // Agents
  try{
    const ag=await fetch('/api/agents').then(r=>r.json());
    if(ag&&ag.agents){
      let html='';
      for(const a of ag.agents){
        const ok=a.status==='ok';
        html+=`<div class="agent-card">
          <div><div class="agent-name">${a.emoji} ${a.name}</div><div class="agent-role">${a.eng}</div></div>
          <div class="agent-status">
            <span class="chip ${ok?'chip-green':'chip-gray'}">${ok?'✅ نشط':'⏳'}</span>
            <div style="font-size:.7rem;color:#8b949e;margin-top:2px">${a.elapsed}s</div>
          </div>
        </div>`;
      }
      document.getElementById('agents-list').innerHTML=html;
      document.getElementById('orch-last-run').textContent=ag.last_run?ag.last_run.replace('T',' ').substring(0,16):'---';
    }
  }catch(e){document.getElementById('agents-list').innerHTML='<div style="color:#8b949e;text-align:center">لا وكلاء — شغّل start_all.bat</div>'}

  // PlutoBrain local mind
  try{
    const brain=await fetch('/api/brain').then(r=>r.json());
    const conf=brain.confluence||{};
    const msgs=brain.messages||[];
    const tasks=brain.tasks||[];
    const blueprints=brain.blueprints||[];
    const dynamicAgents=brain.dynamic_agents||[];
    const minds=brain.minds||[];
    document.getElementById('brain_msgs').textContent=msgs.length;
    document.getElementById('brain_tasks').textContent=tasks.length;
    document.getElementById('brain_blueprints').textContent=blueprints.length;
    document.getElementById('brain_decision').textContent=conf.direction||'---';
    document.getElementById('brain_decision').className='num '+(conf.approved?'green':'red');
    const ap=brain.autopilot||{};
    const apDecision=(ap.decision||{});
    const unified=brain.unified||{};
    const unifiedSignal=unified.final_signal||'---';
    document.getElementById('brain_unified').textContent=unifiedSignal+(unified.confidence?' '+Number(unified.confidence).toFixed(0)+'%':'');
    document.getElementById('brain_unified').className='num '+(unifiedSignal==='BUY'?'green':unifiedSignal==='SELL'?'red':unifiedSignal==='HOLD'?'gold':'');
    document.getElementById('brain_autopilot').textContent=apDecision.confidence?apDecision.confidence+'%':'---';
    document.getElementById('brain_llm').textContent=(ap.provider||((ap.llm||{}).provider)||'---');
    document.getElementById('brain_minds').innerHTML=minds.slice(0,9).map(m=>
      `<div class="brain-msg"><b>${m.emoji||''} ${m.name}</b>
       <div>${m.observation||''}</div>
       <div class="brain-meta">stance=${m.stance||'observe'} | vote=${m.vote===null?'—':m.vote}</div></div>`
    ).join('') || 'لا توجد عقول بعد.';
    document.getElementById('brain_messages').innerHTML=msgs.slice(-8).reverse().map(m=>
      `<div class="brain-msg"><b>${m.from} → ${m.to}</b><div>${m.body}</div><div class="brain-meta">${m.type||''}</div></div>`
    ).join('') || 'لا توجد رسائل جديدة.';
    document.getElementById('brain_task_list').innerHTML=tasks.slice(0,8).map(t=>
      `<div class="brain-task"><b>${t.assigned_to}</b>: ${t.title}<div class="brain-meta">${t.priority} | ${t.source} | ${t.status} | مرة ${t.count||1}</div></div>`
    ).join('') || 'لا توجد مهام.';
    document.getElementById('brain_blueprint_list').innerHTML=(dynamicAgents.length?dynamicAgents:blueprints).slice(0,8).map(b=>
      `<div class="brain-msg"><b>${b.name}</b><div>${b.execution||b.role||''}</div><div class="brain-meta">${b.status||'report'} | ${b.reason||b.path||''}</div></div>`
    ).join('') || 'لا يوجد وكلاء مقترحون.';
    const paths=brain.paths||{};
    document.getElementById('brain_paths').textContent='Brain files: '+(paths.log||'agents/brain_vault/log.md');
  }catch(e){
    document.getElementById('brain_minds').textContent='لم يتم إنشاء brain_vault بعد. شغل agents/orchestrator.py.';
  }
  
  // Decisions
  try{
    const d=await fetch('/api/decisions').then(r=>r.json());
    if(d&&d.length){
      const entries=d.filter(r=>r.decision&&r.decision.includes('ENTRY')).length;
      const blocked=d.filter(r=>r.decision&&r.decision.includes('BLOCK')).length;
      const obhits=d.filter(r=>r.ob_hit==='1').length;
      const fvghits=d.filter(r=>r.fvg_hit==='1').length;
      document.getElementById('total_dec').textContent=d.length;
      document.getElementById('entry_dec').textContent=entries;
      document.getElementById('blocked_dec').textContent=blocked;
      document.getElementById('entry_pct').textContent=(d.length>0?Math.round(entries/d.length*100):0)+'%';
      document.getElementById('ob_hits').textContent=obhits+' ('+Math.round(obhits/d.length*100)+'%)';
      document.getElementById('fvg_hits').textContent=fvghits+' ('+Math.round(fvghits/d.length*100)+'%)';
      // Bar chart (last 40)
      const last40=d.slice(-40);
      let bars='';
      const maxH=40;
      last40.forEach(r=>{
        const cls=r.decision&&r.decision.includes('ENTRY')?'entry':r.decision&&r.decision.includes('BLOCK')?'blocked':'other';
        bars+=`<div class="bar ${cls}" style="height:${maxH}px" title="${r.decision||''}"></div>`;
      });
      document.getElementById('decision_chart').innerHTML=bars;
      // Table (last 50)
      const last50=d.slice(-50).reverse();
      let rows='';
      last50.forEach(r=>{
        const isEntry=r.decision&&r.decision.includes('ENTRY');
        const isBlock=r.decision&&r.decision.includes('BLOCK');
        const decBadge=isEntry?`<span class="chip chip-green">${r.decision}</span>`:isBlock?`<span class="chip chip-red">${r.decision}</span>`:`<span class="chip chip-gray">${r.decision||'---'}</span>`;
        const obChip=r.ob_hit==='1'?'<span class="chip chip-green">✓</span>':'<span class="chip chip-gray">—</span>';
        const fvgChip=r.fvg_hit==='1'?'<span class="chip chip-blue">✓</span>':'<span class="chip chip-gray">—</span>';
        const bosChip=r.structure_ok==='1'?'<span class="green">✓</span>':'—';
        rows+=`<tr>
          <td style="font-size:.7rem;color:#8b949e">${(r.datetime||'').substring(5,16)}</td>
          <td><span class="chip ${r.direction==='BUY'?'chip-green':'chip-red'}">${r.direction||'---'}</span></td>
          <td>${obChip}</td><td>${fvgChip}</td><td>${bosChip}</td>
          <td style="color:${parseFloat(r.rsi||50)>70?'#f85149':parseFloat(r.rsi||50)<30?'#3fb950':'#e6edf3'}">${parseFloat(r.rsi||0).toFixed(1)}</td>
          <td>${decBadge}</td>
          <td style="font-size:.7rem;max-width:200px;overflow:hidden">${r.reason||''}</td>
          <td class="gold">${parseFloat(r.balance||0).toFixed(2)}</td>
          <td>${r.ob_count||'—'}</td><td>${r.fvg_count||'—'}</td>
        </tr>`;
      });
      document.getElementById('dec_body').innerHTML=rows;
    } else {
      document.getElementById('total_dec').textContent='0';
      document.getElementById('entry_dec').textContent='0';
      document.getElementById('blocked_dec').textContent='0';
      document.getElementById('entry_pct').textContent='0%';
      document.getElementById('ob_hits').textContent='0 (0%)';
      document.getElementById('fvg_hits').textContent='0 (0%)';
      document.getElementById('decision_chart').innerHTML='';
      document.getElementById('dec_body').innerHTML='';
    }
  }catch(e){console.error('decisions error',e)}
}

refresh();
setInterval(refresh,1000);
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    
    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        if self.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        
        elif self.path == "/api/status":
            try:
                data = json.loads(STATUS_JSON.read_text(encoding="utf-8")) if STATUS_JSON.exists() else {}
            except: data = {}
            self.send_json(data)
        
        elif self.path == "/api/decisions":
            rows = deque(maxlen=DECISION_WINDOW_ROWS)
            try:
                if SMC_CSV.exists():
                    with open(SMC_CSV, encoding="utf-8-sig") as f:
                        reader = csv.DictReader(f)
                        for row in reader: rows.append(row)
            except: pass
            self.send_json(list(rows))
        
        elif self.path == "/api/agents":
            try:
                agents_info = AGENTS_DIR / "agents_status.json"
                if agents_info.exists():
                    data = json.loads(agents_info.read_text(encoding="utf-8"))
                else:
                    data = {"agents": [], "last_run": None}
            except: data = {"agents": [], "last_run": None}
            self.send_json(data)

        elif self.path == "/api/brain":
            try:
                if BRAIN_JSON.exists():
                    data = json.loads(BRAIN_JSON.read_text(encoding="utf-8"))
                else:
                    data = {"minds": [], "messages": [], "tasks": [], "blueprints": [], "confluence": {}, "paths": {}}
                if TASKS_JSON.exists():
                    data["tasks"] = json.loads(TASKS_JSON.read_text(encoding="utf-8"))[:30]
                if BLUEPRINTS_JSON.exists():
                    data["blueprints"] = list(json.loads(BLUEPRINTS_JSON.read_text(encoding="utf-8")).values())
                if AUTOPILOT_JSON.exists():
                    data["autopilot"] = json.loads(AUTOPILOT_JSON.read_text(encoding="utf-8"))
                if UNIFIED_JSON.exists():
                    data["unified"] = json.loads(UNIFIED_JSON.read_text(encoding="utf-8"))
                # ── Inject live confluence signal so EA FetchExternalSignal() works ──
                conf_file = AGENTS_DIR / "confluence_signal.json"
                if conf_file.exists():
                    try:
                        data["confluence"] = json.loads(conf_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                data.setdefault("paths", {})
                data["paths"].update({
                    "brain": str(BRAIN_DIR),
                    "log": str(LOG_MD),
                    "tasks": str(TASKS_JSON),
                    "blueprints": str(BLUEPRINTS_JSON),
                    "autopilot": str(AUTOPILOT_JSON),
                    "unified": str(UNIFIED_JSON)
                })
            except Exception as e:
                data = {"error": str(e), "minds": [], "messages": [], "tasks": [], "blueprints": []}
            self.send_json(data)
        
        elif self.path.startswith("/api/agent/"):
            agent_name = self.path.split("/")[-1]
            report_file = AGENTS_DIR / agent_name / "report.md"
            try:
                text = report_file.read_text(encoding="utf-8") if report_file.exists() else "No report"
            except: text = "Error reading report"
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        
        elif self.path == "/api/paths":
            self.send_json({
                "status_json": str(STATUS_JSON),
                "status_exists": STATUS_JSON.exists(),
                "smc_csv": str(SMC_CSV),
                "smc_exists": SMC_CSV.exists(),
                "agents_dir": str(AGENTS_DIR),
                "agents_exists": AGENTS_DIR.exists()
            })
        
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🚀 SMC Dashboard: http://localhost:{PORT}")
    print(f"📁 Status: {STATUS_JSON}")
    print(f"📊 CSV: {SMC_CSV}")
    server.serve_forever()
