/* ═══════════════════════════════════════════════════════
   FRIDAY Live Insight  app.js  v3.0
   Dark Pro — proper candlesticks, RSI, entry zones, SL/TP
   ═══════════════════════════════════════════════════════ */
'use strict';

const S = { data: null, last_update: 0 };
const $ = id => document.getElementById(id);

/* ── helpers ── */
function fmt(v, d = 3) {
  if (v === null || v === undefined || !isFinite(+v)) return '--';
  return (+v).toFixed(d);
}
function fmtPct(v) { return fmt(v * 100, 1) + '%'; }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function ts2date(ts) {
  if (!ts) return '--';
  const d = new Date(ts);
  return isNaN(d) ? ts : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/* ═══════════════════════════════════════════════════════
   PRICE CHART  (dark, proper candles, OB zones, FVG,
                 SL/TP lines per position)
   ═══════════════════════════════════════════════════════ */
function drawPriceChart(data) {
  const canvas = $('priceChart');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = Math.max(800, rect.width * dpr);
  const H = Math.max(460, rect.height * dpr);
  canvas.width = W; canvas.height = H;

  const bars = data.bars || [];
  if (bars.length < 3) return;

  const pad = { l: 68, r: 72, t: 20, b: 36 };
  const pw = W - pad.l - pad.r;
  const ph = H - pad.t - pad.b;

  const n = bars.length;
  const bw = Math.max(2, Math.floor(pw / n));
  const gap = Math.max(1, Math.floor(bw * 0.15));
  const body = bw - gap * 2;

  const lows  = bars.map(b => b.low);
  const highs = bars.map(b => b.high);
  const minP  = Math.min(...lows);
  const maxP  = Math.max(...highs);
  const span  = Math.max(maxP - minP, 0.01);
  const yMin  = minP - span * 0.07;
  const yMax  = maxP + span * 0.10;

  const fi = bars[0].i, li = bars[n - 1].i;
  const xFor = i  => pad.l + ((i - fi) / Math.max(1, li - fi)) * pw;
  const yFor = p  => pad.t + ((yMax - p) / (yMax - yMin)) * ph;

  /* background */
  ctx.fillStyle = '#111827';
  ctx.fillRect(0, 0, W, H);

  /* ── grid ── */
  ctx.strokeStyle = 'rgba(255,255,255,.04)';
  ctx.lineWidth = 1;
  ctx.font = `${11 * dpr}px 'Segoe UI',sans-serif`;
  ctx.fillStyle = '#64748b';
  const gridRows = 7;
  for (let k = 0; k <= gridRows; k++) {
    const y = pad.t + (ph * k) / gridRows;
    const p = yMax - ((yMax - yMin) * k) / gridRows;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillText(p.toFixed(2), 6, y + 4);
  }
  /* vertical time grid */
  const step = Math.max(1, Math.floor(n / 8));
  for (let i = 0; i < n; i += step) {
    const x = xFor(bars[i].i);
    const t = bars[i].time ? new Date(bars[i].time) : null;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H - pad.b); ctx.stroke();
    if (t && !isNaN(t)) {
      ctx.fillText(t.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
        x - 14 * dpr, H - pad.b + 14 * dpr);
    }
  }

  /* ── OB + FVG zones ── */
  for (const z of data.zones || []) {
    const iFrom = Math.max(z.from, fi);
    const iTo   = Math.min(z.to ?? li + 10, li + 20);
    const x1 = xFor(iFrom);
    const x2 = Math.max(x1 + 3, xFor(iTo));
    const y1 = yFor(z.high);
    const y2 = yFor(z.low);
    const h  = Math.max(2, y2 - y1);
    const isBull = z.type === 'bullish_ob' || z.type === 'demand';
    const isFvg  = z.type?.includes('fvg');
    if (isBull) {
      ctx.fillStyle   = 'rgba(139,92,246,.14)';
      ctx.strokeStyle = 'rgba(139,92,246,.55)';
    } else if (isFvg) {
      ctx.fillStyle   = 'rgba(245,158,11,.12)';
      ctx.strokeStyle = 'rgba(245,158,11,.50)';
    } else {
      ctx.fillStyle   = 'rgba(239,68,68,.10)';
      ctx.strokeStyle = 'rgba(239,68,68,.45)';
    }
    ctx.lineWidth = 1;
    ctx.fillRect(x1, y1, x2 - x1, h);
    ctx.strokeRect(x1, y1, x2 - x1, h);
    /* label */
    ctx.font = `${9 * dpr}px 'Segoe UI',sans-serif`;
    ctx.fillStyle = isBull ? '#8b5cf6' : isFvg ? '#f59e0b' : '#ef4444';
    ctx.fillText(z.type?.replace('_', ' ').toUpperCase() ?? '', x1 + 3, y1 + 9 * dpr);
  }

  /* ── Candlesticks ── */
  for (let i = 0; i < n; i++) {
    const b = bars[i];
    const cx = pad.l + (i / n) * pw + bw / 2;
    const open  = yFor(b.open);
    const close = yFor(b.close);
    const high  = yFor(b.high);
    const low   = yFor(b.low);
    const up = b.close >= b.open;
    const bodyTop = Math.min(open, close);
    const bodyH   = Math.max(1, Math.abs(close - open));

    /* wick */
    ctx.strokeStyle = up ? '#10b981' : '#ef4444';
    ctx.lineWidth = Math.max(1, dpr * .8);
    ctx.beginPath();
    ctx.moveTo(cx, high); ctx.lineTo(cx, low);
    ctx.stroke();

    /* body */
    ctx.fillStyle = up ? '#10b981' : '#ef4444';
    if (bodyH <= 1) {
      /* doji */
      ctx.strokeStyle = up ? '#10b981' : '#ef4444';
      ctx.lineWidth = Math.max(1, dpr);
      ctx.beginPath(); ctx.moveTo(cx - body / 2, open); ctx.lineTo(cx + body / 2, open); ctx.stroke();
    } else {
      ctx.fillRect(cx - body / 2, bodyTop, body, bodyH);
    }
  }

  /* ── SMC events (BOS, ChoCH, sweeps) ── */
  ctx.font = `${10 * dpr}px 'Segoe UI',sans-serif`;
  for (const ev of data.events || []) {
    if (ev.i < fi || ev.i > li) continue;
    const x = xFor(ev.i);
    const y = yFor(ev.price);
    const up = ev.type?.includes('+') || ev.type === 'SSL sweep' || ev.type === 'Demand';
    const col = up ? '#10b981' :
      (ev.type?.includes('FVG') ? '#f59e0b' : '#ef4444');
    ctx.fillStyle = col;
    ctx.beginPath();
    if (!up) {
      ctx.moveTo(x, y + 8 * dpr); ctx.lineTo(x - 6 * dpr, y - 4 * dpr); ctx.lineTo(x + 6 * dpr, y - 4 * dpr);
    } else {
      ctx.moveTo(x, y - 8 * dpr); ctx.lineTo(x - 6 * dpr, y + 4 * dpr); ctx.lineTo(x + 6 * dpr, y + 4 * dpr);
    }
    ctx.closePath(); ctx.fill();
    ctx.fillText(ev.type, x + 7 * dpr, y + 4 * dpr);
  }

  /* ── SL / TP lines for open positions ── */
  for (const pos of data.positions || []) {
    if (!pos.sl && !pos.tp) continue;
    /* entry */
    const ye = yFor(pos.entry);
    ctx.setLineDash([]);
    ctx.strokeStyle = pos.side === 'BUY' ? '#10b981' : '#ef4444';
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath(); ctx.moveTo(pad.l, ye); ctx.lineTo(W - pad.r, ye); ctx.stroke();
    ctx.fillStyle = pos.side === 'BUY' ? '#10b981' : '#ef4444';
    ctx.font = `bold ${10 * dpr}px 'Segoe UI',sans-serif`;
    ctx.fillText(`ENTRY ${fmt(pos.entry, 3)}`, W - pad.r + 3, ye + 4 * dpr);

    if (pos.sl) {
      const ys = yFor(pos.sl);
      ctx.setLineDash([5 * dpr, 4 * dpr]);
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 1 * dpr;
      ctx.beginPath(); ctx.moveTo(pad.l, ys); ctx.lineTo(W - pad.r, ys); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ef4444';
      ctx.font = `${10 * dpr}px 'Segoe UI',sans-serif`;
      ctx.fillText(`SL ${fmt(pos.sl, 3)}`, W - pad.r + 3, ys + 4 * dpr);
    }
    if (pos.tp) {
      const yt = yFor(pos.tp);
      ctx.setLineDash([5 * dpr, 4 * dpr]);
      ctx.strokeStyle = '#4ade80';
      ctx.lineWidth = 1 * dpr;
      ctx.beginPath(); ctx.moveTo(pad.l, yt); ctx.lineTo(W - pad.r, yt); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#4ade80';
      ctx.fillText(`TP ${fmt(pos.tp, 3)}`, W - pad.r + 3, yt + 4 * dpr);
    }
  }

  /* ── Trade dots ── */
  const trades = [...(data.paper_trades || []), ...(data.auto_trades || [])];
  for (const tr of trades.slice(-80)) {
    const price = tr.entry || tr.price;
    if (!price) continue;
    const tIdx = nearestBar(bars, tr.opened_at || tr.timestamp);
    if (tIdx === null) continue;
    const x = xFor(tIdx);
    const y = yFor(price);
    const side = (tr.side || tr.action || '').toUpperCase();
    ctx.fillStyle   = side === 'BUY' ? '#10b981' : '#ef4444';
    ctx.strokeStyle = '#0b0e17';
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.arc(x, y, 6 * dpr, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }

  /* ── Current price line ── */
  const last = bars[n - 1];
  const yL = yFor(last.close);
  ctx.setLineDash([8 * dpr, 6 * dpr]);
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath(); ctx.moveTo(pad.l, yL); ctx.lineTo(W - pad.r, yL); ctx.stroke();
  ctx.setLineDash([]);

  /* price label box */
  const labelW = 62 * dpr;
  ctx.fillStyle = '#3b82f6';
  ctx.fillRect(W - pad.r - labelW, yL - 9 * dpr, labelW, 18 * dpr);
  ctx.fillStyle = '#fff';
  ctx.font = `bold ${11 * dpr}px 'Segoe UI',sans-serif`;
  ctx.textAlign = 'center';
  ctx.fillText(fmt(last.close, 3), W - pad.r - labelW / 2, yL + 4 * dpr);
  ctx.textAlign = 'left';
}

/* ═══════════════════════════════════════════════════════
   RSI sub-chart
   ═══════════════════════════════════════════════════════ */
function drawRsiChart(data) {
  const canvas = $('rsiChart');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = Math.max(800, rect.width * dpr);
  const H = Math.max(80, rect.height * dpr);
  canvas.width = W; canvas.height = H;

  const bars = data.bars || [];
  if (bars.length < 5) return;

  const pad = { l: 68, r: 72, t: 4, b: 4 };
  const pw = W - pad.l - pad.r;
  const ph = H - pad.t - pad.b;
  const n = bars.length;

  ctx.fillStyle = '#0b0e17';
  ctx.fillRect(0, 0, W, H);

  /* OB / OS zones */
  const y70 = pad.t + ((100 - 70) / 100) * ph;
  const y30 = pad.t + ((100 - 30) / 100) * ph;
  ctx.fillStyle = 'rgba(239,68,68,.07)';
  ctx.fillRect(pad.l, pad.t, pw, y70 - pad.t);
  ctx.fillStyle = 'rgba(16,185,129,.07)';
  ctx.fillRect(pad.l, y30, pw, H - pad.b - y30);

  /* lines at 70 / 50 / 30 */
  for (const lvl of [70, 50, 30]) {
    const y = pad.t + ((100 - lvl) / 100) * ph;
    ctx.strokeStyle = lvl === 50 ? 'rgba(255,255,255,.08)' : 'rgba(255,255,255,.12)';
    ctx.lineWidth = 1;
    ctx.setLineDash(lvl === 50 ? [] : [4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#64748b';
    ctx.font = `${9 * dpr}px 'Segoe UI',sans-serif`;
    ctx.fillText(lvl, 4, y + 4);
  }

  /* compute RSI 14 from bars */
  const closes = bars.map(b => b.close);
  const rsis = computeRsi(closes, 14);

  /* draw RSI line */
  ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < n; i++) {
    const r = rsis[i];
    if (r === null) continue;
    const x = pad.l + (i / n) * pw;
    const y = pad.t + ((100 - r) / 100) * ph;
    if (!started) { ctx.moveTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  }
  /* colour by overbought/oversold */
  const lastRsi = rsis[n - 1] ?? 50;
  ctx.strokeStyle = lastRsi > 70 ? '#ef4444' : lastRsi < 30 ? '#10b981' : '#3b82f6';
  ctx.stroke();

  /* RSI label */
  ctx.fillStyle = ctx.strokeStyle;
  ctx.font = `bold ${10 * dpr}px 'Segoe UI',sans-serif`;
  ctx.fillText(`RSI ${fmt(lastRsi, 1)}`, W - pad.r + 3, H / 2 + 4);
}

function computeRsi(closes, period = 14) {
  const rsi = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return rsi;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gain += d; else loss -= d;
  }
  let avgG = gain / period, avgL = loss / period;
  rsi[period] = 100 - 100 / (1 + (avgL === 0 ? Infinity : avgG / avgL));
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgG = (avgG * (period - 1) + Math.max(0, d)) / period;
    avgL = (avgL * (period - 1) + Math.max(0, -d)) / period;
    rsi[i] = 100 - 100 / (1 + (avgL === 0 ? Infinity : avgG / avgL));
  }
  return rsi;
}

/* ── util ── */
function nearestBar(bars, iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!isFinite(t)) return null;
  let best = null, bestD = Infinity;
  for (const b of bars) {
    const d = Math.abs(Date.parse(b.time) - t);
    if (d < bestD) { bestD = d; best = b.i; }
  }
  return bestD <= 20 * 60 * 1000 ? best : null;
}

/* ═══════════════════════════════════════════════════════
   RENDER FUNCTIONS
   ═══════════════════════════════════════════════════════ */

function renderHUD(data) {
  const acc = data.account || {};
  const snap = data.symbol_snapshot || {};
  const pnl = data.positions_profit ?? 0;

  $('hSymbol').textContent  = data.symbol || '--';
  $('hProfile').textContent = data.profile || '--';
  $('hPrice').textContent   = fmt(snap.bid, 3);
  $('hSpread').textContent  = snap.spread ?? '--';
  $('hBalance').textContent = acc.balance ? `${fmt(acc.balance, 2)} ${acc.currency || ''}` : '--';
  $('hEquity').textContent  = acc.equity  ? `${fmt(acc.equity,  2)} ${acc.currency || ''}` : '--';

  const pnlEl = $('hPnl');
  pnlEl.textContent = fmt(pnl, 2);
  $('hPnlCard').className = `hud-card ${pnl >= 0 ? 'green' : 'red'}`;
  $('hEquityCard').className = `hud-card ${(acc.equity ?? 0) >= (acc.balance ?? 0) ? 'green' : 'red'}`;

  const demo = acc.demo_detected;
  $('subtitle').textContent = demo
    ? '🟡 DEMO account — auto-trade enabled'
    : '🔴 LIVE account — read-only mode';

  const smc = data.latest_smc || {};
  const rsi = smc.rsi ?? null;
  const adx = smc.adx ?? null;
  const atr = smc.atr ?? null;
  const trend = smc.trend ?? null;

  const rsiEl = $('oscRsi');
  rsiEl.textContent = fmt(rsi, 1);
  rsiEl.className = `ov ${rsi > 70 ? 'dn' : rsi < 30 ? 'up' : 'mid'}`;

  const adxEl = $('oscAdx');
  adxEl.textContent = fmt(adx, 1);
  adxEl.className = `ov ${adx > 25 ? 'up' : 'mid'}`;

  $('oscAtr').textContent = atr ? atr.toFixed(4) : '--';
  const trendEl = $('oscTrend');
  trendEl.textContent = trend !== null ? (trend > 0 ? '▲ UP' : '▼ DN') : '--';
  trendEl.className = `ov ${trend > 0 ? 'up' : 'dn'}`;

  $('chartTitle').textContent = `M1 — ${data.symbol || ''}`;
  $('chartMeta').textContent =
    `Updated ${ts2date(data.generated_at)} · P/L ${fmt(pnl, 2)} USD`;
}

function renderDecision(data) {
  const d = data.decision || {};
  const action = d.action || '--';
  const badge = $('decBadge');
  badge.textContent = action;
  badge.className = `dec-badge ${action === 'BUY' ? 'buy' : action === 'SELL' ? 'sell' : 'flat'}`;

  const prob = d.probability ?? null;
  const conf = d.confidence ?? null;
  const probEl = $('kProb');
  probEl.textContent = fmt(prob, 3);
  probEl.className = `kv ${prob > 0.65 ? 'up' : prob < 0.45 ? 'dn' : ''}`;

  const confEl = $('kConf');
  confEl.textContent = fmt(conf, 3);
  confEl.className = `kv ${conf > 0.5 ? 'up' : ''}`;

  $('kBias').textContent = fmt(d.smc_bias, 0);
  $('kCtx').textContent  = d.context_score ?? '0';
  $('decReason').textContent = d.reason || '--';
}

function renderMtf(data) {
  const grid = $('mtfGrid');
  grid.innerHTML = '';
  const mtf = data.mtf || {};
  const order = ['M1','M5','M15','H1','H4'];
  const keys = [...order.filter(k => mtf[k]), ...Object.keys(mtf).filter(k => !order.includes(k))];
  for (const tf of keys) {
    const item = mtf[tf];
    const bias = item.bias ?? 0;
    const bos  = item.bos_up ? 'BOS+' : item.bos_down ? 'BOS-' :
                 item.choch_up ? 'CH+' : item.choch_down ? 'CH-' : 'flat';
    const cls  = bias > 0 ? 'up' : bias < 0 ? 'dn' : 'flat';
    const row = document.createElement('div');
    row.className = 'mtf-row';
    row.innerHTML = `
      <span class="mtf-tf">${tf}</span>
      <span class="mtf-sig ${cls}">B:${item.smc_buy ?? 0} S:${item.smc_sell ?? 0} bias:${bias}</span>
      <span class="mtf-str ${bias > 0 ? 'up' : bias < 0 ? 'dn' : 'flat'}">${bos}</span>
    `;
    grid.appendChild(row);
  }
}

function renderSmc(data) {
  const smc = data.latest_smc || {};
  const flags = [
    ['BOS+',     smc.bos_up,                    'buy'],
    ['BOS-',     smc.bos_down,                   'sell'],
    ['CH+',      smc.choch_up,                   'buy'],
    ['CH-',      smc.choch_down,                 'sell'],
    ['FVG+',     smc.bullish_fvg,                'buy'],
    ['FVG-',     smc.bearish_fvg,                'sell'],
    ['IFVG+',    smc.ifvg_bull,                  'amber'],
    ['IFVG-',    smc.ifvg_bear,                  'sell'],
    ['Bull OB',  smc.in_bullish_ob,              'buy'],
    ['Bear OB',  smc.in_bearish_ob,              'sell'],
    ['BSL Sweep',smc.buy_side_liquidity_sweep,   'sell'],
    ['SSL Sweep',smc.sell_side_liquidity_sweep,  'buy'],
    ['Demand',   smc.demand_zone,                'buy'],
    ['Supply',   smc.supply_zone,                'sell'],
  ];
  const box = $('smcFlags');
  box.innerHTML = '';
  flags.forEach(([label, on, side]) => {
    const el = document.createElement('span');
    el.className = `flag${on ? ` on ${side}` : ''}`;
    el.textContent = label;
    box.appendChild(el);
  });
}

function renderPositions(data) {
  const tbody = $('posBody');
  tbody.innerHTML = '';
  const positions = data.positions || [];
  if (!positions.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:#64748b">No open positions</td></tr>`;
    return;
  }
  for (const p of positions) {
    const cls = Number(p.profit) >= 0 ? 'p-pos' : 'p-neg';
    const sideCls = (p.side || '').toUpperCase() === 'BUY' ? 'buy' : 'sell';
    tbody.innerHTML += `<tr>
      <td>${p.ticket}</td>
      <td><span class="badge ${sideCls}">${p.side}</span></td>
      <td>${fmt(p.volume, 2)}</td>
      <td>${fmt(p.entry, 3)}</td>
      <td style="color:#ef4444">${fmt(p.sl, 3)}</td>
      <td style="color:#4ade80">${fmt(p.tp, 3)}</td>
      <td class="${cls}">${fmt(p.profit, 2)}</td>
    </tr>`;
  }
}

function renderActivity(data) {
  const feed = $('actFeed');
  feed.innerHTML = '';
  const items = [
    ...(data.auto_trades  || []).map(x => ({ ...x, src: 'DEMO'  })),
    ...(data.paper_trades || []).map(x => ({ ...x, src: 'PAPER' })),
  ].sort((a, b) =>
    Date.parse(b.timestamp || b.opened_at || 0) - Date.parse(a.timestamp || a.opened_at || 0)
  ).slice(0, 25);

  if (!items.length) {
    feed.innerHTML = `<div class="feed-item" style="color:#64748b">No recent activity</div>`;
    return;
  }
  for (const it of items) {
    const action = it.action || it.event || it.type || '--';
    const side   = it.side   || it.action || '--';
    const price  = it.price  || it.entry  || it.decision?.close;
    const reason = it.decision?.reason || it.reason || '';
    const ts     = ts2date(it.timestamp || it.opened_at || it.closed_at);
    const srcCls = it.src === 'DEMO' ? 'src-demo' : 'src-paper';
    const sideCls = (side || '').toUpperCase() === 'BUY' ? 'up' : 'dn';
    const div = document.createElement('div');
    div.className = 'feed-item';
    div.innerHTML = `
      <div class="fh">
        <span class="fa ${sideCls}">${action} ${side} @ ${fmt(price, 3)}</span>
        <span class="${srcCls}">${it.src}</span>
      </div>
      ${reason ? `<div class="fr">${reason}</div>` : ''}
      <div class="ft">${ts}</div>
    `;
    feed.appendChild(div);
  }
}

function renderZones(data) {
  const tbody = $('zonesBody');
  tbody.innerHTML = '';
  const zones = data.zones || [];
  if (!zones.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:#64748b">No active zones</td></tr>`;
    return;
  }
  for (const z of zones.slice(-15)) {
    const isBull = z.type?.includes('bull') || z.type === 'demand';
    const cls = isBull ? 'p-pos' : 'p-neg';
    tbody.innerHTML += `<tr>
      <td class="${cls}">${(z.type || '--').replace('_', ' ')}</td>
      <td>${fmt(z.high, 3)}</td>
      <td>${fmt(z.low,  3)}</td>
      <td>${z.active ? '✅' : '❌'}</td>
    </tr>`;
  }
}

/* ═══════════════════════════════════════════════════════
   MAIN REFRESH LOOP
   ═══════════════════════════════════════════════════════ */
async function refresh() {
  try {
    const res  = await fetch('/api/state?bars=260', { cache: 'no-store' });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'API error');
    S.data = data;
    renderHUD(data);
    renderDecision(data);
    renderMtf(data);
    renderSmc(data);
    renderPositions(data);
    renderActivity(data);
    renderZones(data);
    drawPriceChart(data);
    drawRsiChart(data);
  } catch (e) {
    $('chartMeta').textContent = `⚠ ${e.message}`;
  }
}

window.addEventListener('resize', () => {
  if (S.data) { drawPriceChart(S.data); drawRsiChart(S.data); }
});

refresh();
setInterval(refresh, 4000);
