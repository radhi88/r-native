// FRIDAY Desktop — منطق الواجهة. العقل العميق = القلب. REST + WebSocket لحظي.
const BASE = location.origin.startsWith("http") ? location.origin : "http://127.0.0.1:8770";
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (v) => v == null ? "—" : "$" + fmt(v);
const DIRTXT = { "1": "↑", "-1": "↓", "0": "·" };

// ===== التنقّل =====
document.querySelectorAll(".navitem").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".navitem").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active"); $(t.dataset.tab).classList.add("active");
    if (t.dataset.tab === "projection") loadProjection();
    if (t.dataset.tab === "history") loadHistory();
  };
});

// ===== التحكّم =====
$("btnStart").onclick = async () => { await post("/api/start"); flash($("btnStart"), "… يبدأ"); };
$("btnStop").onclick = async () => { if (confirm("إيقاف كل المحرّكات؟ (الأرضية تبقى حارسة)")) { await post("/api/stop"); flash($("btnStop"), "… يوقف"); } };
async function post(p) { try { await fetch(BASE + p, { method: "POST" }); } catch (e) {} }
function flash(b, t) { const o = b.textContent; b.textContent = t; setTimeout(() => (b.textContent = o), 2500); }

// ===== KPIs + الحالة =====
function renderStatus(s) {
  const a = s.account || {}, fl = s.floor || {};
  const on = s.engines > 0 && !s.kill_switch;
  $("sysdot").className = "dot " + (s.kill_switch ? "off" : on ? "on" : "warn");
  $("systext").textContent = s.kill_switch ? "موقوف (أرضية/إيقاف)" : on ? "يعمل" : "خامل";
  $("kEquity").textContent = money(a.equity);
  setSigned($("kFloat"), a.floating);
  $("kPos").textContent = a.positions ?? "—";
  $("kEng").textContent = s.engines ?? "—";
  setSigned($("kFloor"), s.floor_dist, true);
  $("bPos").textContent = a.positions ?? 0;
  $("statRow").innerHTML = [
    stat("الحقوق", money(a.equity), a.balance != null ? "رصيد " + money(a.balance) : "", ""),
    stat("العائم", money(a.floating), (a.positions ?? 0) + " مركز مفتوح", a.floating >= 0 ? "g" : "r"),
    stat("الهامش الحرّ", money(a.margin_free), "نسبة " + fmt(a.margin_level, 0) + "%", "v"),
    stat("الأرضية", money(fl.floor), "قمة " + money(fl.peak), "a"),
    stat("فوق الأرضية", money(s.floor_dist), s.kill_switch ? "إيقاف فعّال" : "تداول مسموح", s.floor_dist >= 0 ? "g" : "r"),
  ].join("");
}
function setSigned(el, v, sign) {
  if (v == null) { el.textContent = "—"; el.className = "v mono"; return; }
  el.textContent = (sign && v >= 0 ? "+" : "") + money(v);
  el.className = "v mono " + (v >= 0 ? "g" : "r");
}
function stat(l, v, s, cls) {
  return `<div class="stat ${cls}"><div class="l">${l}</div><div class="v mono ${cls === "g" || cls === "r" ? cls : ""}">${v}</div><div class="s">${s}</div></div>`;
}

// ===== العقل العميق (القلب) =====
function renderDeep(d) {
  const L = d.learning || {};

  // 🥇 الذهب مباشر
  const gl = d.gold_live || {};
  if ($("goldSig")) {
    $("goldSig").textContent = gl.signal || "…";
    const gsell = gl.bias === "هبوط";
    $("goldStats").innerHTML = [
      stat("الاتجاه", gl.bias || "—", gl.call || "", gsell ? "r" : "g"),
      stat("RSI (H1)", fmt(gl.rsi_h1, 0), (gl.rsi_h1 > 70 ? "تشبّع شرائي" : gl.rsi_h1 < 30 ? "تشبّع بيعي" : "متعادل"), (gl.rsi_h1 > 70 || gl.rsi_h1 < 30) ? "a" : ""),
      stat("السعر", gl.price != null ? fmt(gl.price, 2) : "—", "", "v"),
    ].join("");
    const ML = { spread_b: "السبريد", tickimb_b: "تدفّق التيك", rvol_b: "تذبذب", vwapdev_b: "VWAP", round_b: "رقم مدوّر", struct_b: "بنية مجهرية", orpos_b: "موقع الجلسة" };
    const micro = gl.micro || {};
    $("goldMicro").innerHTML = Object.entries(ML).map(([k, lab]) =>
      `<span class="mchip"><span class="muted">${lab}</span> <b>${micro[k] ?? "—"}</b></span>`).join("");
  }

  // الآفاق (fast/mid/slow)
  const HZ = L.horizons || {}, HL = L.horizon_labels || {};
  if ($("hzRow")) $("hzRow").innerHTML = Object.entries(HL).map(([hn, lab]) => {
    const h = HZ[hn] || {};
    const sig = Math.abs(h.pooled_t || 0) > 2;
    const cls = !sig ? "a" : (h.pooled_expR || 0) >= 0 ? "g" : "r";
    return `<div class="hzcell ${cls}"><div class="hzl">${lab}</div>` +
      `<div class="hzv mono">n ${h.pooled_n ?? 0} · ${fmt(h.pooled_expR ?? 0, 3)}R</div>` +
      `<div class="hzt mono">t ${fmt(h.pooled_t ?? 0, 2)} · فوز ${h.pooled_win ?? 0}%</div></div>`;
  }).join("");

  // 🧲 جسر القناعة: التعلّم المُثبت → قوّة الدخول
  const green = d.green_lights || [], red = d.red_flags || [];
  if ($("convPill")) $("convPill").textContent = `${green.length} أخضر · ${red.length} فيتو`;
  if ($("convBox")) {
    if (green.length) {
      $("convBox").innerHTML = '<div class="muted" style="margin-bottom:8px">🟢 شروط ثبتت موجبة — يدخلها المنفّذ بقوّة (×حتى 2):</div>' +
        green.map(g => `<div class="callrow"><span class="sym">${g.sym}</span>` +
          `<span class="chip ${g.bias === "هبوط" ? "sell" : "buy"}">${g.call || g.bias}</span>` +
          `<span class="tag green">×${g.mult} قوّة</span><span class="meta">${g.tier}</span></div>`).join("");
    } else {
      $("convBox").innerHTML = `<span class="muted">لا أضواء خضراء بعد (لا شرط موجب مُثبت). ` +
        `${red.length} إعداد سالب-مُثبت → يُحجَّم للوت الأدنى (نزيف أقلّ). ` +
        `فور ثبوت شرط موجب (Bonferroni + عيّنات مستقلّة) يصير أخضر ويدخله المنفّذ بقوّة ×حتى 2 بثقة.</span>`;
    }
  }

  // لافتة الحُكم
  const proven = L.proven || {};
  const np = Object.keys(proven).length;
  const isProven = np > 0;
  $("verdictIcon").textContent = isProven ? "🟢" : "⏳";
  $("verdictText").textContent = isProven ? `مرشّح مُثبت! (${np})` : "يتعلّم — لا حافّة معنوية بعد";
  $("verdictSub").innerHTML = isProven
    ? `صمد لتصحيح Bonferroni عبر ${L.n_tests || 0} خلية مُختبَرة — انظر البطاقات الخضراء أدناه.`
    : `عيّنة مُحكَّمة ${L.pooled_n ?? 0} · ${L.n_conditions ?? 0} شرط · ${L.n_combos ?? 0} تركيب · يُختبَر ضدّ ${L.n_tests ?? 0} خلية (Bonferroni).`;
  $("verdictBox").className = "verdict" + (isProven ? " proven" : "");
  $("bVerdict").textContent = isProven ? `🟢${np}` : "⏳";

  // إحصاءات التعلّم
  $("learnStats").innerHTML = [
    stat("عيّنة مُحكَّمة", L.pooled_n ?? 0, "أفق 4 ساعات", "v"),
    stat("التوقّع المجمّع", fmt(L.pooled_expR ?? 0, 3) + "R", `نطاق ${fmt(L.pooled_ci_lo ?? 0, 2)}..${fmt(L.pooled_ci_hi ?? 0, 2)}`, (L.pooled_expR ?? 0) >= 0 ? "g" : "r"),
    stat("معنوية t", fmt(L.pooled_t ?? 0, 2), `فوز ${L.pooled_win ?? 0}% · ${Math.abs(L.pooled_t ?? 0) > 2 ? "معنوي" : "ضجيج"}`, Math.abs(L.pooled_t ?? 0) > 2 ? "g" : "a"),
  ].join("");

  // منحنى التعلّم
  const hist = (L.history || []).map(h => h[2]);  // expR
  if (hist.length >= 2) { spark("lcurve", hist, "#a78bfa"); $("lcurveRange").textContent = `${L.history.length} لقطة`; }
  else { $("lcurveRange").textContent = "يجمع…"; }

  // المرشّحات المُثبتة
  $("provenCount").textContent = np;
  $("provenBox").innerHTML = isProven ? Object.entries(proven).map(([k, v]) =>
    `<div class="proven-card"><div class="pc-name">🟢 ${k}</div>` +
    `<div class="pc-stats"><span>n=<b>${v.n}</b></span><span>توقّع <b class="g">${fmt(v.expR, 3)}R</b></span>` +
    `<span>t=<b>${fmt(v.t, 2)}</b></span><span>فوز <b>${v.win}%</b></span><span class="muted">نطاق ${fmt(v.ci_lo, 2)}..${fmt(v.ci_hi, 2)}</span></div></div>`).join("")
    : '<span class="muted">لا شيء بعد — أُبلّغك فوراً متى ظهر مرشّح يصمد لتصحيح Bonferroni.</span>';

  // نداءات عالية الثقة
  const hc = d.high_conf_now || {};
  $("hicalls").innerHTML = Object.entries(hc).map(([s, v]) => {
    const sell = (v.bias === "هبوط");
    return `<div class="callrow clk" data-sym="${s}"><span class="sym">${s}</span>` +
      `<span class="chip ${sell ? "sell" : "buy"}">${v.call}</span>` +
      `<span class="tag ${v.with_htf ? "green" : "amber"}">${v.with_htf ? "مع الاتجاه" : "ضد"}</span>` +
      `<span class="tag">${v.session}</span>` +
      `<span class="meta">محاذاة ${v.align} · score ${v.score}</span></div>`;
  }).join("") || '<span class="muted">لا نداءات عالية-الثقة الآن — السوق دون العتبة الانتقائية</span>';

  // شروط مفردة + تركيبات
  $("bestcond").innerHTML = condTbl(L.best_conditions, "الشرط");
  $("bestcombo").innerHTML = condTbl(L.best_combos, "التركيب");
  $("bysym").innerHTML = condTbl(L.by_symbol, "الرمز");

  // مصفوفة الرموز
  const syms = d.symbols || {};
  $("symCount").textContent = Object.keys(syms).length;
  $("allsyms").innerHTML = Object.entries(syms).map(([s, v]) => {
    const k = v.net_tf > 0 ? "buy" : v.net_tf < 0 ? "sell" : "neu";
    const heat = Object.values(v.tf_dirs || {}).map(dr =>
      `<span class="tfd ${dr > 0 ? "u" : dr < 0 ? "d" : "n"}">${DIRTXT[String(dr)] || "·"}</span>`).join("");
    const hcb = v.high_conf ? '<span class="hcdot" title="عالي الثقة"></span>' : "";
    return `<div class="symcell ${k} clk" data-sym="${s}"><div class="sc-top"><span class="s">${s}${hcb}</span>` +
      `<span class="muted">${v.bias}</span></div><div class="tfrow">${heat}</div>` +
      `<div class="muted sc-b">محاذاة ${v.align} · score ${v.score}</div></div>`;
  }).join("") || '<span class="muted">…يقرأ</span>';

  // ربط النقر للتفصيل
  document.querySelectorAll(".clk").forEach(el => el.onclick = () => openSymbol(el.dataset.sym));
}
function condTbl(obj, label) {
  obj = obj || {};
  const rows = Object.entries(obj).map(([k, v]) => {
    const sig = Math.abs(v.t) > 2;
    return `<tr><td title="${k}">${k.length > 34 ? k.slice(0, 33) + "…" : k}</td><td class="mono">${v.n}</td>` +
      `<td class="mono num ${v.expR >= 0 ? "g" : "r"}">${fmt(v.expR, 3)}</td>` +
      `<td class="mono ${sig ? "g" : ""}">${fmt(v.t, 2)}</td><td class="mono">${v.win}%</td></tr>`;
  }).join("");
  if (!rows) return '<span class="muted">يتراكم…</span>';
  return `<div class="tblwrap"><table><thead><tr><th>${label}</th><th>n</th><th>توقّع</th><th>t</th><th>فوز</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// ===== درج تفصيل الرمز =====
async function openSymbol(sym) {
  $("dsym").textContent = sym;
  $("drawerBody").innerHTML = '<span class="muted">…يجلب القراءة العميقة</span>';
  $("drawer").classList.add("open");
  try {
    const v = await fetch(BASE + "/api/deep_symbol?sym=" + encodeURIComponent(sym)).then(r => r.json());
    if (!v || !v.sym) { $("drawerBody").innerHTML = '<span class="muted">لا قراءة بعد لهذا الرمز (سيُقرأ في الدورة القادمة).</span>'; return; }
    const sell = v.bias === "هبوط";
    const pt = v.per_tf || {};
    const tfRows = Object.entries(pt).map(([tf, r]) => r ? `<tr><td><b>${tf}</b></td>` +
      `<td class="mono ${r.dir > 0 ? "g" : "r"}">${r.dir > 0 ? "↑ شراء" : "↓ بيع"}</td>` +
      `<td class="mono">${fmt(r.conf, 2)}</td><td class="mono">${fmt(r.rsi, 0)}</td>` +
      `<td class="mono">${fmt(r.roc, 2)}%</td><td class="mono">${fmt(r.pos, 2)}</td>` +
      `<td class="mono">${fmt(r.atr_pct, 2)}</td></tr>` : "").join("");
    const lv = v.levels || {};
    const lvItems = Object.entries(lv).filter(([k]) => !Array.isArray(lv[k])).map(([k, val]) =>
      `<span class="lvchip"><span class="muted">${k}</span> ${fmt(val, 4)}</span>`).join("");
    const f = v.features || {};
    const featChips = Object.entries(f).map(([k, val]) => `<span class="tag">${k}=${val}</span>`).join("");
    $("drawerBody").innerHTML =
      `<div class="dhead"><span class="chip ${sell ? "sell" : "buy"} big">${v.call}</span>` +
      `<span class="tag ${v.with_htf ? "green" : "amber"}">${v.with_htf ? "مع اتجاه HTF" : "ضد HTF"}</span>` +
      `<span class="tag">${v.session}</span>` +
      `<span class="muted">السعر ${fmt(v.price, 4)} · RSI(H1) ${fmt(v.rsi_h1, 0)} · محاذاة ${v.align} · score ${v.score}</span></div>` +
      `<div class="card-h" style="margin-top:14px">القراءة عبر الفريمات</div>` +
      `<div class="tblwrap"><table><thead><tr><th>فريم</th><th>الاتجاه</th><th>confluence</th><th>RSI</th><th>زخم</th><th>موقع</th><th>تذبذب%</th></tr></thead><tbody>${tfRows}</tbody></table></div>` +
      `<div class="card-h" style="margin-top:14px">الخصائص (بصمة التعلّم)</div><div class="chiprow">${featChips}</div>` +
      `<div class="card-h" style="margin-top:14px">المستويات المفتاحية</div><div class="chiprow">${lvItems || '<span class="muted">—</span>'}</div>`;
  } catch (e) { $("drawerBody").innerHTML = '<span class="muted">تعذّر الجلب.</span>'; }
}
$("drawerClose").onclick = () => $("drawer").classList.remove("open");
$("drawer").onclick = (e) => { if (e.target.id === "drawer") $("drawer").classList.remove("open"); };

// ===== المحرّكات =====
function renderEngines(e) {
  const eng = (e && e.engines) || [];
  const run = eng.filter(x => x.running).length;
  $("engCount").textContent = run + "/" + eng.length + " شغّال";
  $("enggrid").innerHTML = eng.map(x =>
    `<div class="engcell"><span class="dot ${x.running ? "on" : "off"}"></span>` +
    `<span class="nm">${x.name}</span><span class="st">${x.running ? "يعمل" : "متوقّف"}</span></div>`).join("");
  $("bEng").textContent = run;
}

// ===== الصفقات الحيّة =====
function renderPositions(p) {
  const ps = p.positions || [];
  $("posStats").innerHTML = [
    stat("مراكز مفتوحة", p.n ?? 0, "بوتاتنا فقط", ""),
    stat("العائم الكلّي", money(p.floating), "", p.floating >= 0 ? "g" : "r"),
    stat("الخاسرة", ps.filter(x => x.profit < 0).length, "من " + (p.n ?? 0), "r"),
  ].join("");
  const tb = $("posTbl").querySelector("tbody");
  tb.innerHTML = ps.length ? ps.map(x =>
    `<tr><td><b>${x.symbol}</b></td><td><span class="chip ${x.type.toLowerCase()}">${x.type}</span></td>` +
    `<td class="mono">${fmt(x.volume, 2)}</td><td class="mono">${fmt(x.price_open, 2)}</td>` +
    `<td class="mono">${fmt(x.price_current, 2)}</td>` +
    `<td class="mono num ${x.profit >= 0 ? "g" : "r"}">${x.profit >= 0 ? "+" : ""}${fmt(x.profit)}</td>` +
    `<td class="mono muted">${x.minutes}د</td><td class="mono muted">${x.magic}</td></tr>`).join("")
    : '<tr><td colspan="8" class="muted">لا مراكز مفتوحة لنا الآن</td></tr>';
}

// ===== إسبارك لاين =====
function spark(svgId, vals, color) {
  const svg = $(svgId); if (!svg || vals.length < 2) return;
  const W = 600, H = svgId === "projspark" ? 160 : 120, pad = 6;
  const mn = Math.min(...vals), mx = Math.max(...vals), rng = (mx - mn) || 1;
  const xs = (i) => pad + (W - 2 * pad) * (i / Math.max(vals.length - 1, 1));
  const ys = (v) => pad + (H - 2 * pad) * (1 - (v - mn) / rng);
  const pts = vals.map((v, i) => `${W - xs(i)},${ys(v)}`).join(" ");
  const area = `${W - xs(0)},${H - pad} ${pts} ${W - xs(vals.length - 1)},${H - pad}`;
  const zero = (mn < 0 && mx > 0) ? `<line x1="0" y1="${ys(0)}" x2="${W}" y2="${ys(0)}" stroke="#3b4350" stroke-width="1" stroke-dasharray="3 3"/>` : "";
  svg.innerHTML = `<polygon points="${area}" fill="${color}" opacity="0.08"/>${zero}` +
    `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
}
function renderEquity(e) {
  const hist = (e && e.hist) || [];
  if (hist.length < 2) { $("eqRange").textContent = "يجمع…"; return; }
  const vals = hist.map(p => p[1]);
  spark("spark", vals, "#3b82f6");
  $("eqRange").textContent = money(vals[0]) + " → " + money(vals[vals.length - 1]);
}

// ===== السجل =====
async function loadHistory() {
  try {
    const h = await fetch(BASE + "/api/history").then(r => r.json());
    $("histStats").innerHTML = [
      stat("صافي 7 أيام", money(h.net), h.n + " صفقة", h.net >= 0 ? "g" : "r"),
      stat("نسبة الفوز", (h.win_rate ?? 0) + "%", h.wins + " فائزة", "v"),
      stat("عدد الصفقات", h.n ?? 0, "بوتاتنا (محقّقة)", ""),
    ].join("");
    const tb = $("histTbl").querySelector("tbody");
    tb.innerHTML = (h.deals || []).length ? h.deals.map(d =>
      `<tr><td><b>${d.symbol}</b></td><td class="mono num ${d.profit >= 0 ? "g" : "r"}">${d.profit >= 0 ? "+" : ""}${fmt(d.profit)}</td>` +
      `<td class="mono muted">${d.magic}</td></tr>`).join("")
      : '<tr><td colspan="3" class="muted">لا صفقات مُغلقة لنا في آخر 7 أيام</td></tr>';
  } catch (e) {}
}

// ===== التقدير الصادق =====
async function loadProjection() {
  try {
    const p = await fetch(BASE + "/api/projection?start=1000").then(r => r.json());
    const endCls = p.significant ? (p.exp_end >= p.start ? "g" : "r") : "a";
    const range = p.band_end != null ? "±" + money(p.band_end) + " (نطاق 95%)" : "";
    $("projStats").innerHTML = [
      stat("البداية", money(p.start), "", ""),
      stat("المتوقّع بعد 30 يوم", money(p.exp_end), range, endCls),
      stat("معنوية الحافّة t", fmt(p.t, 2), p.significant ? "معنوي" : "ضجيج (لا يُميَّز عن صفر)", Math.abs(p.t) > 2 ? "g" : "a"),
    ].join("");
    drawProjection(p);
    $("projHonest").textContent = "⚠ " + p.honest;
  } catch (e) {}
}
function drawProjection(p) {
  const svg = $("projspark"); if (!svg) return;
  const W = 600, H = 160, pad = 8;
  const all = [...p.lo, ...p.hi, p.start];
  const mn = Math.min(...all), mx = Math.max(...all), rng = (mx - mn) || 1;
  const n = p.path.length;
  const xs = (i) => pad + (W - 2 * pad) * (i / Math.max(n - 1, 1));
  const ys = (v) => pad + (H - 2 * pad) * (1 - (v - mn) / rng);
  const line = (arr) => arr.map((v, i) => `${W - xs(i)},${ys(v)}`).join(" ");
  const band = `${line(p.hi)} ${[...p.lo].reverse().map((v, i) => `${W - xs(n - 1 - i)},${ys(v)}`).join(" ")}`;
  const y0 = ys(p.start);
  svg.innerHTML = `<polygon points="${band}" fill="#f59e0b" opacity="0.10"/>` +
    `<line x1="0" y1="${y0}" x2="${W}" y2="${y0}" stroke="#6b7785" stroke-width="1" stroke-dasharray="4 4"/>` +
    `<polyline points="${line(p.path)}" fill="none" stroke="#f59e0b" stroke-width="2.5"/>`;
}

// ===== WebSocket لحظي + احتياط REST =====
function apply(m) {
  if (m.status) renderStatus(m.status);
  if (m.deep) renderDeep(m.deep);
  if (m.positions) renderPositions(m.positions);
  if (m.engines) renderEngines(m.engines);
  if (m.equity) renderEquity(m.equity);
}
function connect() {
  let ws;
  try {
    ws = new WebSocket(BASE.replace("http", "ws") + "/ws");
    ws.onmessage = (e) => { try { apply(JSON.parse(e.data)); } catch (x) {} };
    ws.onclose = () => setTimeout(connect, 2500);
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  } catch (e) { setTimeout(connect, 2500); }
}
async function bootstrap() {
  try {
    const [s, dp, pos, eng, eq] = await Promise.all([
      fetch(BASE + "/api/status").then(r => r.json()),
      fetch(BASE + "/api/deep").then(r => r.json()),
      fetch(BASE + "/api/positions").then(r => r.json()),
      fetch(BASE + "/api/engines").then(r => r.json()),
      fetch(BASE + "/api/equity").then(r => r.json()),
    ]);
    renderStatus(s); renderDeep(dp); renderPositions(pos); renderEngines(eng); renderEquity(eq);
  } catch (e) {}
}
bootstrap();
connect();
