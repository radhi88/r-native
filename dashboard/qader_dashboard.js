const stateUrl = "qader_live_state.json";
const maxRows = 24;
const maxChartPoints = 240;
let chartSeries = [];

const $ = (id) => document.getElementById(id);

function fmt(value, fallback = "-") {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(value % 1 === 0 ? 0 : 3);
  return String(value);
}

function setDecision(action) {
  const node = $("finalAction");
  const value = fmt(action, "HOLD");
  node.textContent = value;
  node.className = `decision ${value.toLowerCase()}`;
}

function appendRow(tbody, cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    td.textContent = fmt(cell);
    tr.appendChild(td);
  }
  tbody.appendChild(tr);
  while (tbody.children.length > maxRows) tbody.removeChild(tbody.firstElementChild);
}

function riskWidth(latest) {
  const risk = String(latest.risk_status || "");
  if (risk === "approved") return 28;
  if (risk.includes("blocked")) return 84;
  if (["BUY", "SELL"].includes(latest.final_action)) return 45;
  return 12;
}

function normalizePoint(point) {
  const bid = Number(point.bid || 0);
  const ask = Number(point.ask || 0);
  const mid = Number(point.mid || ((bid + ask) / 2));
  if (!Number.isFinite(mid) || mid <= 0) return null;
  return {
    timestamp: point.timestamp || "",
    cycle_number: Number(point.cycle_number || 0),
    bid,
    ask,
    mid,
    spread: Number(point.spread || 0),
    confidence: Math.max(0, Math.min(1, Number(point.confidence || 0))),
    final_action: point.final_action || "HOLD",
    arbiter_result: point.arbiter_result || point.final_action || "HOLD",
    risk_status: point.risk_status || "",
    execution_status: point.execution_status || "",
  };
}

function updateChartSeries(state, latest) {
  if (Array.isArray(state.chart_history) && state.chart_history.length) {
    chartSeries = state.chart_history.map(normalizePoint).filter(Boolean).slice(-maxChartPoints);
    return;
  }
  const point = normalizePoint(latest);
  if (!point) return;
  const previous = chartSeries[chartSeries.length - 1];
  if (!previous || previous.cycle_number !== point.cycle_number) {
    chartSeries.push(point);
  } else {
    chartSeries[chartSeries.length - 1] = point;
  }
  chartSeries = chartSeries.slice(-maxChartPoints);
}

function chartLatencyLabel(latest) {
  const stamp = Date.parse(latest.timestamp || "");
  if (!Number.isFinite(stamp)) return "latency -";
  const seconds = Math.max(0, Math.round((Date.now() - stamp) / 1000));
  return `latency ${seconds}s`;
}

function drawLiveChart() {
  const canvas = $("liveChart");
  if (!canvas) return;
  const box = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(640, Math.floor(box.width || canvas.clientWidth || 900));
  const height = Math.max(300, Math.floor(box.height || canvas.clientHeight || 320));
  if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0f1b2d");
  gradient.addColorStop(1, "#020617");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const pad = { left: 62, right: 24, top: 28, bottom: 38 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  ctx.strokeStyle = "rgba(148, 163, 184, 0.14)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (i / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }
  for (let i = 0; i <= 6; i += 1) {
    const x = pad.left + (i / 6) * plotW;
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, height - pad.bottom);
    ctx.stroke();
  }

  if (chartSeries.length < 2) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "700 15px Segoe UI, Arial";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for live chart data", width / 2, height / 2);
    return;
  }

  const prices = chartSeries.map((point) => point.mid);
  let min = Math.min(...prices);
  let max = Math.max(...prices);
  if (max - min < 0.01) {
    min -= 0.01;
    max += 0.01;
  }
  const xFor = (index) => pad.left + (index / Math.max(1, chartSeries.length - 1)) * plotW;
  const yForPrice = (price) => pad.top + (1 - ((price - min) / (max - min))) * plotH;
  const yForConfidence = (confidence) => pad.top + (1 - confidence) * plotH;

  ctx.lineWidth = 2.4;
  ctx.strokeStyle = "#22d3ee";
  ctx.beginPath();
  chartSeries.forEach((point, index) => {
    const x = xFor(index);
    const y = yForPrice(point.mid);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.lineWidth = 1.8;
  ctx.setLineDash([7, 6]);
  ctx.strokeStyle = "#f59e0b";
  ctx.beginPath();
  chartSeries.forEach((point, index) => {
    const x = xFor(index);
    const y = yForConfidence(point.confidence);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.setLineDash([]);

  chartSeries.forEach((point, index) => {
    const action = point.arbiter_result || point.final_action;
    if (!["BUY", "SELL"].includes(action)) return;
    const x = xFor(index);
    const y = yForPrice(point.mid);
    ctx.fillStyle = action === "BUY" ? "#34d399" : "#ef4444";
    ctx.strokeStyle = "#020617";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  const latest = chartSeries[chartSeries.length - 1];
  ctx.fillStyle = "#dbeafe";
  ctx.font = "800 13px Segoe UI, Arial";
  ctx.textAlign = "left";
  ctx.fillText("XAUUSDm M1 live mid", pad.left, 18);
  ctx.textAlign = "right";
  ctx.fillText(`${latest.mid.toFixed(3)} | spread ${latest.spread.toFixed(0)}`, width - pad.right, 18);
  ctx.fillStyle = "#94a3b8";
  ctx.textAlign = "left";
  ctx.fillText(max.toFixed(3), 12, pad.top + 4);
  ctx.fillText(min.toFixed(3), 12, height - pad.bottom);
  ctx.fillStyle = "#22d3ee";
  ctx.fillText("price", pad.left, height - 12);
  ctx.fillStyle = "#f59e0b";
  ctx.fillText("confidence", pad.left + 56, height - 12);
}

function render(state) {
  const loop = state.loop || {};
  const latest = state.latest_record || {};
  updateChartSeries(state, latest);

  $("loopState").textContent = fmt(loop.state, "STANDBY");
  $("cycleCount").textContent = fmt(loop.cycle_count || latest.cycle_number || 0);
  $("tradeCount").textContent = fmt(loop.demo_trades_opened || 0);
  $("managedCount").textContent = fmt(loop.demo_trades_managed || 0);
  $("confidence").textContent = Number(latest.confidence || 0).toFixed(3);
  $("spread").textContent = fmt(latest.spread);
  $("heartbeatBadge").textContent = loop.thread_alive ? "HEARTBEAT LIVE" : "HEARTBEAT STANDBY";
  $("dataBadge").textContent = Number(latest.bars_received || 0) > 0 ? "DATA OK" : "DATA WAITING";

  $("accountPanel").innerHTML = `
    <dt>Status</dt><dd>${fmt(loop.state, "standby")}</dd>
    <dt>Reason</dt><dd>${fmt(loop.reason)}</dd>
    <dt>Log</dt><dd>${fmt(state.log_path)}</dd>
    <dt>Journal</dt><dd>${fmt(state.journal_path)}</dd>
  `;

  $("fractalSignal").textContent = fmt(latest.fractal_result);
  $("smcSignal").textContent = fmt(latest.smc_result);
  $("ictSignal").textContent = fmt(latest.ict_result);
  setDecision(latest.final_action || "HOLD");
  $("arbiterReason").textContent = `${fmt(latest.arbiter_result)} | ${fmt(latest.reason)}`;
  $("riskMeter").style.width = `${riskWidth(latest)}%`;
  $("riskStatus").textContent = `${fmt(latest.risk_status)} | ${fmt(latest.execution_status)}`;
  const learning = state.learning_state || {};
  const application = learning.application || {};
  const dnaMode = application.applied ? "last proposal applied to Strategy DNA" : "proposals guarded until eligible";
  $("dnaStatus").textContent = `Live performance samples: ${fmt(loop.demo_trades_opened || 0)}. ${dnaMode}; source self-modification is disabled.`;
  const latestPoint = chartSeries[chartSeries.length - 1];
  $("chartPrice").textContent = latestPoint ? `mid ${latestPoint.mid.toFixed(3)}` : "mid -";
  $("chartConfidence").textContent = latestPoint ? `conf ${latestPoint.confidence.toFixed(3)}` : "conf -";
  $("chartLatency").textContent = chartLatencyLabel(latest);
  drawLiveChart();

  if (latest.cycle_number !== undefined) {
    appendRow($("scannerRows"), [
      latest.cycle_number,
      latest.symbol,
      latest.timeframe,
      latest.bid,
      latest.ask,
      latest.bars_received,
      latest.final_action,
      latest.execution_status,
    ]);
    appendRow($("positionRows"), [
      latest.open_positions,
      latest.open_positions_total,
      latest.order,
      latest.deal,
      latest.reason,
    ]);
  }

  $("logsConsole").textContent = JSON.stringify({ loop, latest_record: latest }, null, 2);
}

async function loadState() {
  try {
    const response = await fetch(`${stateUrl}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("logsConsole").textContent = `Waiting for dashboard/qader_live_state.json\n${error.message}\n\nIf opened as file:// and the browser blocks local fetch, use the PyQt Web dashboard tab or serve this folder locally.`;
  }
}

loadState();
setInterval(loadState, 1000);
window.addEventListener("resize", drawLiveChart);
