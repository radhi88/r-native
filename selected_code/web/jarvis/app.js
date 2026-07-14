// ── Trading Panel (Heat Map + Book Map + Trade Entry) ─────────────────────────

let chartVisible   = false;
let hmData         = null;
let chartRefreshId = null;

const tradingPanel = document.getElementById("tradingPanel");
const hmCanvas     = document.getElementById("hmCanvas");
const bmCanvas     = document.getElementById("bmCanvas");
const hmCtx        = hmCanvas.getContext("2d");
const bmCtx        = bmCanvas.getContext("2d");

// ── canvas sizing ──────────────────────────────────────────────────────────────
function resizeCanvases() {
  [hmCanvas, bmCanvas].forEach((c) => {
    const rect = c.getBoundingClientRect();
    c.width  = rect.width  || 300;
    c.height = rect.height || 360;
  });
}

// ── Heat Map renderer ──────────────────────────────────────────────────────────
function drawHeatmap(data) {
  const { width: W, height: H } = hmCanvas;
  hmCtx.clearRect(0, 0, W, H);
  if (!data?.volume_profile?.length) return;

  const profile  = data.volume_profile;
  const prices   = profile.map((p) => p.price);
  const priceMin = Math.min(...prices);
  const priceMax = Math.max(...prices);
  const priceRange = priceMax - priceMin || 1;

  const barH  = H / profile.length;
  const maxW  = W - 60;  // leave space for price labels

  profile.forEach(({ price, intensity }) => {
    const y     = H - ((price - priceMin) / priceRange) * H;
    const barW  = intensity * maxW;

    // Colour: cold (blue→cyan) at low volume, hot (amber→red) at high
    const r = Math.round(intensity * 251 + (1 - intensity) * 47);
    const g = Math.round(intensity * 107 + (1 - intensity) * 155);
    const b = Math.round(intensity * 125 + (1 - intensity) * 255);
    hmCtx.fillStyle = `rgba(${r},${g},${b},0.65)`;
    hmCtx.fillRect(0, y - barH / 2, barW, barH);
  });

  // Price labels (every ~10%)
  hmCtx.fillStyle = "rgba(125,145,160,0.9)";
  hmCtx.font      = "10px monospace";
  hmCtx.textAlign = "right";
  for (let i = 0; i <= 5; i++) {
    const price = priceMin + (priceRange * i) / 5;
    const y     = H - (i / 5) * H;
    hmCtx.fillText(price.toFixed(2), W - 2, y + 4);
  }

  // Current price line
  const cp  = data.current_price;
  const cpy = H - ((cp - priceMin) / priceRange) * H;
  hmCtx.strokeStyle = "rgba(34,211,238,0.9)";
  hmCtx.lineWidth   = 1.5;
  hmCtx.setLineDash([4, 3]);
  hmCtx.beginPath();
  hmCtx.moveTo(0, cpy);
  hmCtx.lineTo(W - 60, cpy);
  hmCtx.stroke();
  hmCtx.setLineDash([]);
  hmCtx.fillStyle = "var(--cyan)";
  hmCtx.font = "10px monospace";
  hmCtx.fillText(cp.toFixed(2), W - 2, cpy + 4);

  // Click → fill trade price
  hmCanvas.onclick = (e) => {
    const rect  = hmCanvas.getBoundingClientRect();
    const relY  = e.clientY - rect.top;
    const price = priceMax - (relY / H) * priceRange;
    document.getElementById("tePrice").value = price.toFixed(2);
    document.getElementById("tePriceRow").style.display = "flex";
  };
}

// ── Book Map renderer (SMC) ────────────────────────────────────────────────────
function drawBookmap(data) {
  const { width: W, height: H } = bmCanvas;
  bmCtx.clearRect(0, 0, W, H);
  if (!data) return;

  const profile   = data.volume_profile || [];
  const prices    = profile.map((p) => p.price);
  const priceMin  = Math.min(...prices);
  const priceMax  = Math.max(...prices);
  const priceRange = priceMax - priceMin || 1;

  const toY = (p) => H - ((p - priceMin) / priceRange) * H;

  // OB zones
  (data.ob_zones || []).forEach(({ type, low, high, label }) => {
    const y1  = toY(high);
    const y2  = toY(low);
    const col = type === "bull_ob" ? "rgba(53,208,138,0.18)" : "rgba(251,107,125,0.18)";
    const brd = type === "bull_ob" ? "#35d08a" : "#fb6b7d";
    bmCtx.fillStyle   = col;
    bmCtx.strokeStyle = brd;
    bmCtx.lineWidth   = 1;
    bmCtx.fillRect(0, y1, W - 70, y2 - y1);
    bmCtx.strokeRect(0, y1, W - 70, y2 - y1);
    bmCtx.fillStyle = brd;
    bmCtx.font      = "9px monospace";
    bmCtx.textAlign = "left";
    bmCtx.fillText(label, 4, y1 + 11);
  });

  // FVG zones
  (data.fvg_zones || []).forEach(({ type, low, high, filled }) => {
    if (filled) return;
    const y1  = toY(high);
    const y2  = toY(low);
    const col = type === "bull_fvg" ? "rgba(241,183,67,0.18)" : "rgba(241,183,67,0.10)";
    bmCtx.fillStyle   = col;
    bmCtx.strokeStyle = "#f1b743";
    bmCtx.lineWidth   = 0.8;
    bmCtx.setLineDash([3, 3]);
    bmCtx.fillRect(0, y1, W - 70, y2 - y1);
    bmCtx.strokeRect(0, y1, W - 70, y2 - y1);
    bmCtx.setLineDash([]);
  });

  // Liquidity lines
  (data.liquidity || []).forEach(({ type, price, label, swept }) => {
    const y   = toY(price);
    const col = swept ? "#7d91a0" : (type.includes("buy") ? "#35d08a" : "#fb6b7d");
    bmCtx.strokeStyle = col;
    bmCtx.lineWidth   = 1.2;
    bmCtx.setLineDash(swept ? [2, 4] : []);
    bmCtx.beginPath();
    bmCtx.moveTo(0, y);
    bmCtx.lineTo(W - 70, y);
    bmCtx.stroke();
    bmCtx.setLineDash([]);
    bmCtx.fillStyle = col;
    bmCtx.font      = "9px monospace";
    bmCtx.textAlign = "left";
    bmCtx.fillText(`${label} ${price.toFixed(2)}`, 4, y - 2);
  });

  // Current price
  const cp  = data.current_price;
  const cpy = toY(cp);
  bmCtx.strokeStyle = "rgba(34,211,238,0.9)";
  bmCtx.lineWidth   = 1.5;
  bmCtx.beginPath(); bmCtx.moveTo(0, cpy); bmCtx.lineTo(W - 70, cpy); bmCtx.stroke();

  // Price axis labels
  bmCtx.fillStyle = "rgba(125,145,160,0.9)";
  bmCtx.font      = "10px monospace";
  bmCtx.textAlign = "right";
  for (let i = 0; i <= 5; i++) {
    const price = priceMin + (priceRange * i) / 5;
    const y     = H - (i / 5) * H;
    bmCtx.fillText(price.toFixed(2), W - 2, y + 4);
  }

  // Bias badge
  const biasEl = document.getElementById("hmBias");
  const bias   = data.bias || 0;
  biasEl.textContent = bias > 0 ? "BULL" : bias < 0 ? "BEAR" : "NEUTRAL";
  biasEl.className   = "tp-badge " + (bias > 0 ? "bull" : bias < 0 ? "bear" : "");
}

async function refreshChart() {
  try {
    document.getElementById("hmPrice").textContent = "loading…";
    hmData = await api("/api/heatmap");
    document.getElementById("hmPrice").textContent = hmData.current_price?.toFixed(2) || "—";
    resizeCanvases();
    drawHeatmap(hmData);
    drawBookmap(hmData);
    renderPositions();
  } catch (e) {
    document.getElementById("hmPrice").textContent = "error";
  }
}

function renderPositions() {
  const el = document.getElementById("tpPositions");
  const status = hmData;
  if (!status) { el.innerHTML = ""; return; }
  // will be populated by agent status
}

// ── Trade entry wiring ─────────────────────────────────────────────────────────
document.getElementById("teType").addEventListener("change", function () {
  document.getElementById("tePriceRow").style.display =
    this.value === "MARKET" ? "none" : "flex";
});

async function submitTrade(side) {
  const type  = document.getElementById("teType").value;
  const lot   = parseFloat(document.getElementById("teLot").value) || 0.01;
  const price = parseFloat(document.getElementById("tePrice").value) || null;
  const sl    = parseFloat(document.getElementById("teSL").value)    || null;
  const tp    = parseFloat(document.getElementById("teTP").value)    || null;
  const res   = document.getElementById("teResult");

  try {
    let result;
    if (type === "MARKET") {
      result = await api("/api/trade/market", { side, lot, sl, tp });
    } else {
      result = await api("/api/trade/pending", {
        side, order_type: type, limit_price: price, lot, sl, tp,
      });
    }
    res.textContent = `✓ ${side} ${type} sent`;
    res.style.color = "var(--green)";
    refreshChart();
  } catch (e) {
    res.textContent = `✗ ${e.message}`;
    res.style.color = "var(--red)";
  }
}

document.getElementById("teBuy").addEventListener("click",  () => submitTrade("BUY"));
document.getElementById("teSell").addEventListener("click", () => submitTrade("SELL"));

// ── eDEX Live Panel ───────────────────────────────────────────────────────────

let edexVisible    = false;
let edexIntervalId = null;
const edexPanel    = document.getElementById("edexPanel");
const edexBtn      = document.getElementById("edexBtn");

edexBtn.addEventListener("click", () => {
  edexVisible = !edexVisible;
  edexPanel.classList.toggle("hidden", !edexVisible);
  edexBtn.textContent = edexVisible ? "eDEX ON" : "eDEX";
  if (edexVisible) {
    refreshEdex();
    if (!edexIntervalId) edexIntervalId = setInterval(refreshEdex, 1500);
  } else {
    clearInterval(edexIntervalId);
    edexIntervalId = null;
  }
});

async function refreshEdex() {
  let data;
  try {
    data = await fetch("/api/mt5/stream").then((r) => r.json());
  } catch (_) { return; }
  if (data.error) return;

  const fmt = (v, d = 3) => (v != null ? Number(v).toFixed(d) : "—");

  document.getElementById("edexBid").textContent    = fmt(data.bid);
  document.getElementById("edexAsk").textContent    = fmt(data.ask);
  document.getElementById("edexSpread").textContent = data.spread_pts != null ? data.spread_pts : "—";
  document.getElementById("edexEquity").textContent = fmt(data.equity, 2);
  document.getElementById("edexSrc").textContent    = data.symbol || "MT5";

  // Delta bar
  const up    = data.buy_ticks  || 0;
  const down  = data.sell_ticks || 0;
  const total = up + down || 1;
  const pct   = (up / total) * 100;
  const fill  = document.getElementById("edexDeltaFill");
  fill.style.width      = `${pct}%`;
  fill.style.background = pct >= 50 ? "var(--green)" : "var(--red)";
  document.getElementById("edexDelta").textContent = data.tick_delta != null
    ? (data.tick_delta >= 0 ? "+" : "") + data.tick_delta
    : "0";
  document.getElementById("edexSpeed").textContent = data.ticks_per_sec != null
    ? data.ticks_per_sec.toFixed(1)
    : "—";

  // Fields from last_state (model output)
  const ls = data.last_state || {};
  document.getElementById("edexProb").textContent = ls.probability != null
    ? (ls.probability * 100).toFixed(1) + "%"
    : "—";
  document.getElementById("edexSmc").textContent  = ls.smc_buy_score != null
    ? ls.smc_buy_score.toFixed(0)
    : "—";
  document.getElementById("edexAdx").textContent  = ls.adx != null
    ? ls.adx.toFixed(1)
    : "—";
  document.getElementById("edexRsi").textContent  = ls.rsi != null
    ? ls.rsi.toFixed(1)
    : "—";
  document.getElementById("edexOb").textContent   = ls.in_bullish_ob
    ? "BULL"
    : ls.in_bearish_ob
    ? "BEAR"
    : "—";

  // Color prob
  const probEl  = document.getElementById("edexProb");
  const probVal = ls.probability || 0.5;
  probEl.style.color = probVal >= 0.68
    ? "var(--green)"
    : probVal <= 0.32
    ? "var(--red)"
    : "var(--muted)";

  // Tape
  const tape    = data.tape || [];
  const tapeEl  = document.getElementById("edexTape");
  tapeEl.innerHTML = "";
  tape.slice(-12).reverse().forEach(({ bid, ask, spread }) => {
    const div = document.createElement("div");
    div.className = "edex-tick";
    div.textContent = `${bid.toFixed(3)} / ${ask.toFixed(3)}  [${spread}]`;
    tapeEl.appendChild(div);
  });

  // Also update hmPrice if chart visible
  if (ls.price) document.getElementById("hmPrice").textContent = ls.price.toFixed(2);

  refreshMt5Process();
  refreshMt5Log();
}

let _lastProcessRefresh = 0;
async function refreshMt5Process() {
  const now = Date.now();
  if (now - _lastProcessRefresh < 7000) return;
  _lastProcessRefresh = now;
  try {
    const p = await fetch("/api/mt5/process").then((r) => r.json());
    if (p.error) return;
    document.getElementById("sysPid").textContent     = p.pid || "—";
    document.getElementById("sysCpu").textContent     = p.cpu_pct != null ? p.cpu_pct + "%" : "—";
    document.getElementById("sysRam").textContent     = p.ram_mb  != null ? p.ram_mb  + "M" : "—";
    document.getElementById("sysThreads").textContent = p.threads || "—";
    document.getElementById("sysUptime").textContent  = p.uptime_min != null ? p.uptime_min + "m" : "—";
    document.getElementById("sysConns").textContent   = (p.connections || []).length;
  } catch (_) {}
}

let _lastLogRefresh = 0;
let _lastLogLine    = "";
async function refreshMt5Log() {
  const now = Date.now();
  if (now - _lastLogRefresh < 3000) return;
  _lastLogRefresh = now;
  try {
    const data = await fetch("/api/mt5/log?n=50").then((r) => r.json());
    if (data.error || !data.lines) return;
    document.getElementById("edexLogFile").textContent = data.file || "";
    const logEl  = document.getElementById("edexLog");
    const newest = (data.lines[data.lines.length - 1] || {}).message || "";
    if (newest === _lastLogLine) return;  // no new lines
    _lastLogLine = newest;
    logEl.innerHTML = "";
    for (const rec of data.lines) {
      const msg = rec.message || rec.raw || "";
      if (!msg) continue;
      const div = document.createElement("div");
      div.className = "edex-log-line";
      const lo = msg.toLowerCase();
      if (lo.includes("deal") || lo.includes("done") || lo.includes("filled")) div.classList.add("deal");
      else if (lo.includes("market") || lo.includes("order") || lo.includes("trade")) div.classList.add("trade");
      else if (lo.includes("error") || lo.includes("fail")) div.classList.add("error");
      else if (lo.includes("warn") || lo.includes("disconn")) div.classList.add("warn");
      div.textContent = `${rec.time || ""} ${msg}`;
      logEl.appendChild(div);
    }
  } catch (_) {}
}

// ── Scanner Panel ────────────────────────────────────────────────────────────

let scannerVisible = false;
const scannerPanel = document.getElementById("scannerPanel");
const scannerBtn   = document.getElementById("scannerBtn");

scannerBtn.addEventListener("click", () => {
  scannerVisible = !scannerVisible;
  scannerPanel.classList.toggle("hidden", !scannerVisible);
  scannerBtn.textContent = scannerVisible ? "SCANNER ON" : "SCANNER";
  if (scannerVisible) { refreshPolymarket(); }
});

function renderScanRow(r, cls) {
  const div = document.createElement("div");
  div.className = `scanner-row ${cls}`;
  div.innerHTML = `<span class="sym">${r.symbol}</span><span class="price">${r.price}</span><span class="smc">SMC${cls==="buy"?r.smc_buy:r.smc_sell} ADX${r.adx} RSI${r.rsi}</span>`;
  div.onclick = () => { document.getElementById("teType").value = "MARKET"; submitTrade(cls.toUpperCase()); };
  return div;
}

function handleMultiScan(payload) {
  if (!scannerVisible) return;
  document.getElementById("scanBuyCount").textContent  = payload.buys?.length  || 0;
  document.getElementById("scanSellCount").textContent = payload.sells?.length || 0;
  const buyEl  = document.getElementById("scanBuys");
  const sellEl = document.getElementById("scanSells");
  buyEl.innerHTML  = "";
  sellEl.innerHTML = "";
  (payload.buys  || []).forEach(r => buyEl.appendChild(renderScanRow(r,  "buy")));
  (payload.sells || []).forEach(r => sellEl.appendChild(renderScanRow(r, "sell")));
}

let _polyTs = 0;
async function refreshPolymarket() {
  if (Date.now() - _polyTs < 55000) return;
  _polyTs = Date.now();
  try {
    const d = await fetch("/api/polymarket").then(r => r.json());
    if (d.error) return;
    const sent = d.btc_sentiment || {};
    const sigEl = document.getElementById("polySignal");
    sigEl.textContent  = sent.signal || "—";
    sigEl.className    = "tp-badge " + (sent.signal === "BULL" ? "bull" : sent.signal === "BEAR" ? "bear" : "");
    document.getElementById("polyBull").innerHTML =
      `<span style="color:var(--green)">BULL ${sent.bull_pct ?? "—"}%</span> &nbsp;
       <span style="color:var(--red)">BEAR ${sent.bear_pct ?? "—"}%</span>
       <span style="color:var(--muted)"> (${sent.markets_used || 0} mkts)</span>`;
    const el = document.getElementById("polyMarkets");
    el.innerHTML = "";
    (d.markets || []).slice(0, 12).forEach(m => {
      const row = document.createElement("div");
      row.className = "poly-row";
      const odds = (m.outcomes || []).map(o =>
        `<span class="${(o.outcome||"").toLowerCase().includes("yes")?"yes":"no"}">${o.outcome} ${o.probability_pct ?? "?"}%</span>`
      ).join("");
      row.innerHTML = `<div class="poly-q">${m.question}</div><div class="poly-odds">${odds}</div>`;
      el.appendChild(row);
    });
  } catch (_) {}
}

// ── Chart toggle ───────────────────────────────────────────────────────────────

// ── Agents tab ────────────────────────────────────────────────────────────────
let agentsRunning = false;

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
    if (btn.dataset.tab === "agents") refreshAgents();
  });
});

function renderAgentCard(agent) {
  const pos = agent.has_open_trade;
  const wr  = agent.win_rate != null ? (agent.win_rate * 100).toFixed(1) + "%" : "—";
  const pf  = agent.profit_factor != null ? agent.profit_factor.toFixed(2) : "—";
  const ar  = agent.avg_r != null ? agent.avg_r.toFixed(2) : "—";
  const thr = agent.thresholds || {};
  const bt  = thr.buy_threshold  != null ? thr.buy_threshold.toFixed(2)  : "—";
  const st  = thr.sell_threshold != null ? thr.sell_threshold.toFixed(2) : "—";
  const smc = thr.min_smc_score  != null ? thr.min_smc_score              : "—";
  const trades = agent.trades || 0;

  let posHtml = '<span class="agent-position">idle</span>';
  if (pos) {
    posHtml = `<span class="agent-position ${(agent.side||'').toLowerCase()}">${agent.side || ''} open</span>`;
  }

  return `
    <div class="agent-card${pos ? " has-trade" : ""}">
      <div class="agent-card-header">
        <span class="agent-name">${agent.name}</span>
        <span class="agent-status-dot${pos ? " active" : ""}"></span>
      </div>
      ${posHtml}
      <div class="agent-metrics">
        <div class="agent-metric"><span>trades</span><span>${trades}</span></div>
        <div class="agent-metric"><span>win rate</span><span>${wr}</span></div>
        <div class="agent-metric"><span>PF</span><span>${pf}</span></div>
        <div class="agent-metric"><span>avg-R</span><span>${ar}</span></div>
      </div>
      <div class="agent-threshold">
        <span>buy≥${bt}</span>
        <span>sell≤${st}</span>
        <span>SMC≥${smc}</span>
      </div>
    </div>`;
}

async function refreshAgents() {
  try {
    const data = await api("/api/agents/status");
    agentsRunning = Boolean(data.running);
    const badge  = document.getElementById("agentsRunning");
    const barEl  = document.getElementById("agentsBarCount");
    const cards  = document.getElementById("agentCards");
    badge.textContent = agentsRunning ? "LIVE" : "OFFLINE";
    badge.className   = "agents-badge " + (agentsRunning ? "on" : "off");
    barEl.textContent = `bar ${data.bar_count || 0}`;
    agentsBtn.textContent = agentsRunning ? "AGENTS ON" : "AGENTS OFF";
    if (data.agents) {
      cards.innerHTML = data.agents.map(renderAgentCard).join("");
    }
  } catch (_) {}
}

function addAgentLogEntry(text, cls = "") {
  const log = document.getElementById("agentsLog");
  const div = document.createElement("div");
  div.className = `agent-log-entry ${cls}`;
  div.textContent = text;
  log.prepend(div);
  while (log.children.length > 30) log.lastChild.remove();
}

setInterval(() => { if (agentsRunning) refreshAgents(); }, 5000);

// ── Main app ──────────────────────────────────────────────────────────────────
const chat = document.getElementById("chat");
const form = document.getElementById("chatForm");
const input = document.getElementById("textInput");
const voiceToggle = document.getElementById("voiceToggle");
const scanBtn = document.getElementById("scanBtn");
const autoPaperBtn = document.getElementById("autoPaperBtn");
const demoMt5Btn = document.getElementById("demoMt5Btn");
const agentsBtn = document.getElementById("agentsBtn");
const analyzeBtn = document.getElementById("analyzeBtn");
const tradeBtn = document.getElementById("tradeBtn");
const decisionBox = document.getElementById("decisionBox");
const decisionPill = document.getElementById("decisionPill");
const mindBox = document.getElementById("mindBox");
const statusLine = document.getElementById("statusLine");
const statusDot = document.getElementById("statusDot");
const profileSelect = document.getElementById("profileSelect");
const sourceSelect = document.getElementById("sourceSelect");
const pulseCore = document.getElementById("pulseCore");
const coreState = document.getElementById("coreState");
const coreSub = document.getElementById("coreSub");
const voiceStatus = document.getElementById("voiceStatus");
const llmStatus = document.getElementById("llmStatus");

let voiceRunning = false;
let autoPaperRunning = false;
let pendingChat = false;
let welcomed = false;

function setState(state, sub = "") {
  pulseCore.classList.remove("sleeping", "listening", "thinking", "speaking");
  pulseCore.classList.add(state);
  const labels = {
    sleeping: "نائم",
    listening: "أسمعك",
    thinking: "أفكر",
    speaking: "أتحدث"
  };
  coreState.textContent = labels[state] || "نائم";
  coreSub.textContent = sub || "كلمة التنبيه: Friday / فرايدي / جارفيس";
}

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function api(path, payload = null) {
  const options = payload
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    : {};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function updateDecision(data) {
  const decision = data?.decision || data;
  if (!decision || typeof decision !== "object") return;
  decisionBox.textContent = JSON.stringify(decision, null, 2);
  const action = decision.action || decision.decision?.action || "NO DATA";
  decisionPill.textContent = action;
  decisionPill.className = "";
  if (action === "BUY") decisionPill.classList.add("buy");
  if (action === "SELL") decisionPill.classList.add("sell");
}

async function sendText(text) {
  const clean = text.trim();
  if (!clean) return;

  addMessage("user", clean);
  input.value = "";
  pendingChat = true;
  setState("thinking", "أربط الأمر بالذاكرة والأدوات");
  const thinking = addMessage("friday", "processing...");

  try {
    const data = await api("/api/chat", { text: clean });
    thinking.textContent = data.answer;
    mindBox.textContent = JSON.stringify(data.mind, null, 2);

    if (data.tool_result?.data?.decision) updateDecision(data.tool_result.data.decision);
    else if (data.tool_result?.data?.action) updateDecision(data.tool_result.data);
    else if (data.tool_result?.data) updateDecision(data.tool_result.data);

    setState("speaking", "تم إصدار الرد المحلي");
    setTimeout(() => setState(voiceRunning ? "listening" : "sleeping"), 1100);
  } catch (error) {
    thinking.textContent = `error: ${error.message}`;
    setState("sleeping", "حدث خطأ");
  } finally {
    pendingChat = false;
  }
}

async function refreshStatus() {
  try {
    const data = await api("/api/status");
    mindBox.textContent = JSON.stringify(data, null, 2);
    const assistant = data.assistant || {};
    const mind = data.mind || {};
    const voice = data.voice || {};
    const speaker = data.speaker || {};
    const autoPaper = data.auto_paper || {};
    const execMode = autoPaper.execution_mode || "paper";
    const spreadMode = assistant.ignore_spread_filter ? "spread override" : "spread filter";
    statusLine.textContent = `${assistant.mode || "paper"} | ${assistant.profile || "profile"} | ${assistant.source || "source"} | ${spreadMode} | mic ${voice.running ? "on" : "off"} | auto ${autoPaper.running ? execMode : "off"}`;
    llmStatus.textContent = mind.llama_cpp_available ? mind.llama_cpp_model : "llama.cpp offline";
    voiceStatus.textContent = voice.available
      ? (voice.running ? "always listening locally" : "offline voice ready")
      : "offline voice missing";
    if (assistant.profile) profileSelect.value = assistant.profile;
    if (assistant.source) sourceSelect.value = assistant.source;
    voiceRunning = Boolean(voice.running);
    autoPaperRunning = Boolean(autoPaper.running);
    voiceToggle.textContent = voiceRunning ? "MIC ON" : "WAKE WORD";
    autoPaperBtn.textContent = autoPaperRunning ? "AUTO ON" : "AUTO PAPER";
    demoMt5Btn.textContent = execMode === "demo" ? "DEMO ON" : "DEMO MT5";
    setState(voiceRunning ? "listening" : "sleeping");
    statusDot.classList.add("online");
    if (!welcomed && chat.children.length === 0) {
      const voiceText = voice.available
        ? (voice.running
          ? "المايك شغال محليًا. تكلم بعد كلمة التنبيه."
          : "الصوت المحلي جاهز. اضغط WAKE WORD وتكلم بعد كلمة التنبيه.")
        : "الصوت المحلي يحتاج Vosk model؛ حتى ذلك الوقت استخدم مربع الأوامر.";
      addMessage("friday", `FRIDAY online. ${voiceText}`);
      welcomed = true;
    }
  } catch (error) {
    statusLine.textContent = error.message;
    statusDot.classList.remove("online");
  }
}

function wireEvents() {
  const events = new EventSource("/api/events");
  events.addEventListener("thinking", () => setState("thinking", "أفكر محليًا"));
  events.addEventListener("speaking", (event) => {
    setState("speaking", "تم تجهيز الرد");
    try {
      const data = JSON.parse(event.data);
      if (!pendingChat && data.payload?.answer) addMessage("friday", data.payload.answer);
    } catch {}
  });
  events.addEventListener("analysis", (event) => {
    const data = JSON.parse(event.data);
    updateDecision(data.payload);
  });
  events.addEventListener("market_scan", (event) => {
    const data = JSON.parse(event.data);
    decisionBox.textContent = JSON.stringify(data.payload, null, 2);
    decisionPill.textContent = data.payload?.tradable?.length ? "SETUPS" : "NO SETUP";
  });
  events.addEventListener("market_scan_trade", (event) => {
    const data = JSON.parse(event.data);
    decisionBox.textContent = JSON.stringify(data.payload, null, 2);
    decisionPill.textContent = data.payload?.executions?.length ? "PAPER" : "NO TRADE";
  });
  events.addEventListener("autopaper_scan", (event) => {
    const data = JSON.parse(event.data);
    decisionBox.textContent = JSON.stringify(data.payload, null, 2);
    decisionPill.textContent = "AUTO SCAN";
  });
  events.addEventListener("autopaper_open", (event) => {
    const data = JSON.parse(event.data);
    addMessage("friday", `AUTO PAPER OPEN: ${data.payload?.position?.symbol} ${data.payload?.position?.side}`);
    decisionPill.textContent = "AUTO OPEN";
    refreshStatus();
  });
  events.addEventListener("autodemo_open", (event) => {
    const data = JSON.parse(event.data);
    const position = data.payload?.position || {};
    const broker = data.payload?.broker_result || {};
    addMessage("friday", `DEMO MT5 ORDER: ${position.symbol} ${position.side} sent=${broker.executed || broker.result?.sent || false}`);
    decisionPill.textContent = "DEMO MT5";
    refreshStatus();
  });
  events.addEventListener("autopaper_close", (event) => {
    const data = JSON.parse(event.data);
    const position = data.payload?.position || {};
    addMessage("friday", `AUTO PAPER CLOSE: ${position.symbol} ${position.side} points=${position.points}`);
    decisionPill.textContent = position.won ? "AUTO WIN" : "AUTO LOSS";
    refreshStatus();
  });
  events.addEventListener("agent_trade_open", (event) => {
    const d = JSON.parse(event.data).payload;
    addAgentLogEntry(
      `▲ ${d.agent.toUpperCase()} ${d.side} ${d.order_type} @ ${d.price?.toFixed(2)}`,
      "open"
    );
    refreshAgents();
  });
  events.addEventListener("agent_trade_close", (event) => {
    const d = JSON.parse(event.data).payload;
    const cls = d.won ? "win" : "loss";
    addAgentLogEntry(
      `${d.won ? "✓" : "✗"} ${d.agent.toUpperCase()} ${d.side} pts=${d.points?.toFixed(2)}`,
      cls
    );
    refreshAgents();
  });
  events.addEventListener("agent_sl_update", (event) => {
    const d = JSON.parse(event.data).payload;
    addAgentLogEntry(
      `↑ SL ${d.agent.toUpperCase()} ${d.old_sl?.toFixed(2)} → ${d.new_sl?.toFixed(2)} @ ${d.price?.toFixed(2)}`,
      "open"
    );
  });
  events.addEventListener("agent_learning_update", (event) => {
    const d = JSON.parse(event.data).payload;
    (d.agents || []).forEach((a) => {
      if (a.trades > 0) {
        addAgentLogEntry(
          `◆ ${a.name} wr=${(a.win_rate * 100).toFixed(0)}% pf=${a.profit_factor?.toFixed(2)} buy≥${a.thresholds?.buy_threshold?.toFixed(2)}`,
          ""
        );
      }
    });
    refreshAgents();
  });

  events.addEventListener("multi_scan", (event) => {
    const d = JSON.parse(event.data).payload;
    handleMultiScan(d);
    if (scannerVisible) refreshPolymarket();
  });

  events.addEventListener("agent_data_source", (event) => {
    const d = JSON.parse(event.data).payload;
    const src = d.source || "unknown";
    addAgentLogEntry(`◉ DATA SOURCE → ${src.toUpperCase()}`, src === "mt5_live" ? "win" : "");
    if (src === "mt5_live") {
      document.getElementById("edexSrc").textContent = "MT5 LIVE";
      if (!edexVisible) {
        edexBtn.textContent = "eDEX LIVE";
        edexBtn.style.color = "var(--green)";
      }
    }
  });

  events.addEventListener("agent_bar", (event) => {
    const d = JSON.parse(event.data).payload;
    if (edexVisible) {
      const prob = d.prob || 0.5;
      const probEl = document.getElementById("edexProb");
      if (!probEl.textContent.includes("%")) {
        probEl.textContent = (prob * 100).toFixed(1) + "%";
      }
    }
  });

  events.addEventListener("voice_started", () => {
    voiceRunning = true;
    setState("listening", "كلمة التنبيه مفعلة");
    refreshStatus();
  });
  events.addEventListener("voice_stopped", () => {
    voiceRunning = false;
    setState("sleeping", "الصوت متوقف");
    refreshStatus();
  });
  events.addEventListener("voice_unavailable", (event) => {
    const data = JSON.parse(event.data);
    addMessage("friday", `offline voice unavailable: ${JSON.stringify(data.payload.dependencies || data.payload)}`);
    setState("sleeping", "ثبّت Vosk ونموذج الصوت");
    refreshStatus();
  });
  events.addEventListener("wake_word", (event) => {
    const data = JSON.parse(event.data);
    setState("listening", `wake word: ${data.payload.word}`);
  });
  events.addEventListener("voice_text", (event) => {
    const data = JSON.parse(event.data);
    if (data.payload?.text) addMessage("user", data.payload.text);
  });
  events.addEventListener("voice_answer", (event) => {
    const data = JSON.parse(event.data);
    if (data.payload?.answer) addMessage("friday", data.payload.answer);
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendText(input.value);
});

const chartBtn = document.getElementById("chartBtn");
chartBtn.addEventListener("click", () => {
  chartVisible = !chartVisible;
  tradingPanel.classList.toggle("hidden", !chartVisible);
  chartBtn.textContent = chartVisible ? "CHART ON" : "CHART";
  if (chartVisible) {
    refreshChart();
    if (!chartRefreshId) chartRefreshId = setInterval(refreshChart, 30000);
  } else {
    clearInterval(chartRefreshId);
    chartRefreshId = null;
  }
});

agentsBtn.addEventListener("click", async () => {
  const path = agentsRunning ? "/api/agents/stop" : "/api/agents/start";
  await api(path, {});
  await refreshAgents();
  // Switch to agents tab automatically
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
  document.querySelector('[data-tab="agents"]').classList.add("active");
  document.getElementById("tab-agents").classList.remove("hidden");
});

analyzeBtn.addEventListener("click", () => sendText("فرايدي حللي السوق الآن"));
scanBtn.addEventListener("click", () => sendText("فرايدي امسحي جميع الأسواق"));
autoPaperBtn.addEventListener("click", async () => {
  const path = autoPaperRunning ? "/api/autopaper/stop" : "/api/autopaper/start";
  await api(path, {});
  refreshStatus();
});
demoMt5Btn.addEventListener("click", async () => {
  const status = await api("/api/autopaper/status", {});
  const current = status.execution_mode || "paper";
  await api("/api/autopaper/mode", { mode: current === "demo" ? "paper" : "demo" });
  await api("/api/mode", { mode: current === "demo" ? "paper" : "demo" });
  await api("/api/autopaper/start", {});
  refreshStatus();
});
tradeBtn.addEventListener("click", () => sendText("فرايدي نفذي Paper إذا الصفقة مناسبة"));

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => sendText(button.dataset.command));
});

voiceToggle.addEventListener("click", async () => {
  const path = voiceRunning ? "/api/voice/stop" : "/api/voice/start";
  const data = await api(path, {});
  if (!data.started && !data.stopped) {
    addMessage("friday", data.reason || "voice service did not start");
  }
  refreshStatus();
});

profileSelect.addEventListener("change", async () => {
  const data = await api("/api/profile", { profile: profileSelect.value });
  addMessage("friday", data.message);
  refreshStatus();
});

sourceSelect.addEventListener("change", async () => {
  const data = await api("/api/source", { source: sourceSelect.value });
  addMessage("friday", data.message);
  refreshStatus();
});

wireEvents();
refreshStatus();

// ── Auto-start: open eDEX + switch to DEMO MT5 on page load ───────────────────
window.addEventListener("load", async () => {
  // Open eDEX panel immediately
  setTimeout(() => {
    edexBtn.click();
  }, 800);

  // Switch auto-paper to demo MT5 mode automatically
  try {
    await api("/api/autopaper/mode", { mode: "demo" });
    await api("/api/mode", { mode: "demo" });
    await api("/api/autopaper/start", {});
  } catch (_) {}

  // Show agents tab
  setTimeout(() => {
    document.querySelector('[data-tab="agents"]')?.click();
    refreshAgents();
  }, 1200);
});
