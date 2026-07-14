from __future__ import annotations

import json
import math
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pymysql
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


ROOT = Path(r"C:\Users\Radhi\MT5")
BRAIN_FILE = ROOT / "friday_brain_memory.json"
GENES_FILE = ROOT / "friday_strategy_genes.json"
PROJECT_MAP_FILE = ROOT / "friday_project_map.json"
DISPATCH_LOG_DIR = ROOT / "gateway_dispatch_logs"

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "agents_app"

app = FastAPI(title="FRIDAY Agents Browser", version="0.1")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "friday_agents_browser",
    }


def make_json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(v) for v in value]

    return value


def safe_read_json(path: Path, default: Any):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def db_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def db_fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return list(rows or [])
    except Exception:
        return []


def db_fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row
    except Exception:
        return None


def latest_dispatch_log_tail(limit_lines: int = 80) -> str:
    try:
        files = list(DISPATCH_LOG_DIR.glob("dispatch_*.log"))
        if not files:
            return ""
        latest = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-limit_lines:])
    except Exception:
        return ""


def extract_brain_status(brain: dict[str, Any]) -> dict[str, Any]:
    patch_quality = brain.get("patch_quality", {}) or {}
    if isinstance(patch_quality, dict):
        good = int(patch_quality.get("Good", patch_quality.get("good", 0)) or 0)
        fair = int(patch_quality.get("Fair", patch_quality.get("fair", 0)) or 0)
        poor = int(patch_quality.get("Poor", patch_quality.get("poor", 0)) or 0)
    else:
        good = fair = poor = 0

    latest_job = brain.get("latest_job", {}) or {}

    return {
        "version": brain.get("brain_version", "-"),
        "generated_at": brain.get("generated_at", brain.get("generated", "-")),
        "jobs_stored": int(brain.get("jobs_stored", brain.get("jobs_count", len(brain.get("jobs", []) or []))) or 0),
        "patches_stored": int(brain.get("patches_stored", brain.get("patches_count", len(brain.get("patches", []) or []))) or 0),
        "agent_runs_stored": int(brain.get("agent_runs_stored", brain.get("agent_runs_count", len(brain.get("agent_runs", []) or []))) or 0),
        "latest_job": latest_job,
        "patch_quality": {"good": good, "fair": fair, "poor": poor},
        "rules": brain.get("rules", {}),
        "next_steps": brain.get("next_steps", []),
        "rejected_patches": brain.get("rejected_patch_candidates", []),
        "agent_scoreboard": brain.get("agent_scoreboard", []),
        "learned": brain.get("learned", brain.get("what_friday_learned", [])),
    }


def top_genes(genes: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    gene_map = genes.get("genes", {}) if isinstance(genes, dict) else {}
    if isinstance(gene_map, dict):
        for gene_id, value in gene_map.items():
            if isinstance(value, dict):
                rows.append(
                    {
                        "gene_id": gene_id,
                        "score": float(value.get("score", 0.0) or 0.0),
                        "confidence_boost": float(value.get("confidence_boost", 0.0) or 0.0),
                        "seen": int(value.get("seen", 0) or 0),
                        "wins": int(value.get("wins", 0) or 0),
                        "losses": int(value.get("losses", 0) or 0),
                        "neutral": int(value.get("neutral", 0) or 0),
                    }
                )
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:limit]


def get_overview() -> dict[str, Any]:
    brain_raw = safe_read_json(BRAIN_FILE, {})
    genes_raw = safe_read_json(GENES_FILE, {})
    project_map = safe_read_json(PROJECT_MAP_FILE, {})

    brain = extract_brain_status(brain_raw)

    jobs = db_fetch_all(
        """
        SELECT id, status, model, report_path, created_at, updated_at
        FROM dispatch_jobs
        ORDER BY id DESC
        LIMIT 12
        """
    )

    active_runs = db_fetch_all(
        """
        SELECT id, job_id, agent_name, agent_role, status, created_at
        FROM dispatch_agent_runs
        WHERE status IN ('running', 'queued')
        ORDER BY id DESC
        LIMIT 20
        """
    )

    recent_runs = db_fetch_all(
        """
        SELECT id, job_id, agent_name, agent_role, status, created_at
        FROM dispatch_agent_runs
        ORDER BY id DESC
        LIMIT 40
        """
    )

    agents = db_fetch_all(
        """
        SELECT id, name, role
        FROM agents
        ORDER BY id ASC
        """
    )

    recent_patches = db_fetch_all(
        """
        SELECT id, job_id, agent_name, agent_role, target_file, risk, approved, applied, created_at
        FROM dispatch_patch_proposals
        ORDER BY id DESC
        LIMIT 16
        """
    )

    patch_stats = db_fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN risk='Low' THEN 1 ELSE 0 END) AS low_count,
            SUM(CASE WHEN risk='Medium' THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN risk='High' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN approved=1 THEN 1 ELSE 0 END) AS approved_count,
            SUM(CASE WHEN applied=1 THEN 1 ELSE 0 END) AS applied_count
        FROM dispatch_patch_proposals
        """
    ) or {}

    run_status_map: dict[str, str] = {}
    for row in active_runs:
        key = f'{row.get("agent_name","")}|{row.get("agent_role","")}'
        run_status_map[key] = row.get("status", "idle")

    scoreboard_map = {}
    for item in brain.get("agent_scoreboard", []) or []:
        if isinstance(item, dict):
            key = f'{item.get("agent","")}|{item.get("role","")}'
            scoreboard_map[key] = item

    agent_nodes = []
    for agent in agents[:40]:
        key = f'{agent.get("name","")}|{agent.get("role","")}'
        sb = scoreboard_map.get(key, {})
        agent_nodes.append(
            {
                "id": int(agent.get("id") or 0),
                "name": agent.get("name") or f"A{agent.get('id')}",
                "role": agent.get("role") or "-",
                "status": run_status_map.get(key, "idle"),
                "reliability": int(sb.get("reliability", 0) or 0),
                "level": int(sb.get("level", 0) or 0),
                "done": int(sb.get("done", 0) or 0),
                "failed": int(sb.get("failed", 0) or 0),
            }
        )

    return {
        "brain": brain,
        "genes": top_genes(genes_raw, limit=12),
        "jobs": jobs,
        "active_runs": active_runs,
        "recent_runs": recent_runs,
        "agents": agent_nodes,
        "recent_patches": recent_patches,
        "patch_stats": {
            "total": int(patch_stats.get("total", 0) or 0),
            "low": int(patch_stats.get("low_count", 0) or 0),
            "medium": int(patch_stats.get("medium_count", 0) or 0),
            "high": int(patch_stats.get("high_count", 0) or 0),
            "approved": int(patch_stats.get("approved_count", 0) or 0),
            "applied": int(patch_stats.get("applied_count", 0) or 0),
        },
        "project_map": project_map,
        "log_tail": latest_dispatch_log_tail(80),
    }


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE


@app.get("/api/overview")
def api_overview():
    return JSONResponse(make_json_safe(get_overview()))


HTML_PAGE = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>FRIDAY Agents Browser</title>
  <style>
    :root{
      --bg:#07111f;
      --card:#0d1728;
      --card2:#0b1322;
      --line:#1f3048;
      --text:#eaf2ff;
      --muted:#8ea4c5;
      --green:#22c55e;
      --red:#ef4444;
      --yellow:#eab308;
      --blue:#38bdf8;
      --violet:#8b5cf6;
      --pink:#ec4899;
      --cyan:#06b6d4;
    }
    *{box-sizing:border-box}
    html,body{
      margin:0;
      padding:0;
      width:100%;
      height:100%;
      overflow:hidden;
      background:
        radial-gradient(circle at 20% 20%, rgba(56,189,248,.10), transparent 35%),
        radial-gradient(circle at 80% 25%, rgba(139,92,246,.10), transparent 30%),
        radial-gradient(circle at 50% 80%, rgba(34,197,94,.08), transparent 35%),
        var(--bg);
      color:var(--text);
      font-family:Arial, sans-serif;
    }
    .topbar{
      height:58px;
      display:flex;
      align-items:center;
      gap:12px;
      padding:0 16px;
      border-bottom:1px solid var(--line);
      background:rgba(7,17,31,.75);
      backdrop-filter: blur(10px);
    }
    .brand{
      font-size:30px;
      font-weight:900;
      letter-spacing:.5px;
      margin-left:auto;
      text-shadow:0 0 14px rgba(56,189,248,.18);
    }
    .subtitle{
      color:var(--muted);
      font-size:13px;
    }
    .btn{
      background:#0f1c31;
      color:var(--text);
      border:1px solid var(--line);
      border-radius:10px;
      padding:8px 12px;
      cursor:pointer;
      font-weight:700;
    }
    .status{
      font-size:13px;
      color:var(--muted);
    }
    .layout{
      display:grid;
      grid-template-columns: 1.2fr .8fr;
      gap:12px;
      padding:12px;
      height:calc(100vh - 58px);
    }
    .left,.right{
      display:grid;
      gap:12px;
      min-height:0;
    }
    .left{
      grid-template-rows: 1.1fr .9fr;
    }
    .right{
      grid-template-rows: auto auto auto 1fr;
      min-width:380px;
    }
    .card{
      background:linear-gradient(180deg, rgba(13,23,40,.96), rgba(10,17,30,.96));
      border:1px solid var(--line);
      border-radius:18px;
      padding:14px;
      box-shadow:0 12px 30px rgba(0,0,0,.22);
      min-height:0;
      overflow:hidden;
      position:relative;
    }
    .card:before{
      content:"";
      position:absolute;
      inset:0;
      pointer-events:none;
      background:linear-gradient(180deg, rgba(255,255,255,.02), transparent 30%);
    }
    .card h3{
      margin:0 0 10px;
      font-size:20px;
      font-weight:900;
      display:flex;
      align-items:center;
      gap:10px;
    }
    .grid-stats{
      display:grid;
      grid-template-columns:repeat(4,1fr);
      gap:10px;
    }
    .stat{
      padding:12px;
      border:1px solid var(--line);
      border-radius:14px;
      background:rgba(7,17,31,.55);
    }
    .stat .label{
      font-size:12px;
      color:var(--muted);
      margin-bottom:6px;
    }
    .stat .value{
      font-size:24px;
      font-weight:900;
    }
    .brain-meta{
      display:grid;
      grid-template-columns:repeat(2,1fr);
      gap:10px;
      margin-top:10px;
    }
    .mini{
      padding:10px 12px;
      border:1px solid var(--line);
      border-radius:12px;
      background:rgba(7,17,31,.45);
      font-size:13px;
    }
    .network-wrap{
      position:relative;
      height:100%;
      min-height:360px;
      border:1px solid var(--line);
      border-radius:16px;
      background:
        linear-gradient(rgba(255,255,255,.02), rgba(255,255,255,0)),
        radial-gradient(circle at 50% 50%, rgba(56,189,248,.06), transparent 40%),
        #06101c;
      overflow:hidden;
    }
    #network{
      width:100%;
      height:100%;
      display:block;
    }
    .list{
      overflow:auto;
      max-height:100%;
      padding-left:2px;
    }
    .row{
      display:grid;
      grid-template-columns:1fr auto auto auto;
      gap:10px;
      align-items:center;
      padding:10px 8px;
      border-bottom:1px solid rgba(31,48,72,.65);
      font-size:13px;
    }
    .row:last-child{border-bottom:none}
    .pill{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:4px 8px;
      min-width:66px;
      border-radius:999px;
      font-size:11px;
      font-weight:800;
      border:1px solid rgba(255,255,255,.08);
      background:#07111f;
    }
    .pill.running{color:#fff;background:rgba(6,182,212,.15);border-color:rgba(6,182,212,.25)}
    .pill.done{color:#fff;background:rgba(34,197,94,.15);border-color:rgba(34,197,94,.25)}
    .pill.failed{color:#fff;background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.25)}
    .pill.queued{color:#fff;background:rgba(234,179,8,.15);border-color:rgba(234,179,8,.25)}
    .pill.cancelled{color:#fff;background:rgba(148,163,184,.15);border-color:rgba(148,163,184,.25)}
    .risk-low{color:#8bffbf}
    .risk-medium{color:#ffd66b}
    .risk-high{color:#ff8c8c}
    .mono{
      font-family:Consolas, monospace;
      font-size:12px;
    }
    .genes-grid{
      display:grid;
      grid-template-columns:repeat(2,1fr);
      gap:10px;
      overflow:auto;
      max-height:100%;
      padding-right:4px;
    }
    .gene{
      border:1px solid var(--line);
      border-radius:14px;
      padding:10px;
      background:rgba(7,17,31,.5);
    }
    .gene .score{
      font-size:22px;
      font-weight:900;
      color:#8fdcff;
    }
    .gene .id{
      font-size:12px;
      color:var(--muted);
      word-break:break-word;
      margin-top:6px;
    }
    .console{
      height:100%;
      overflow:auto;
      white-space:pre-wrap;
      font-family:Consolas, monospace;
      font-size:12px;
      line-height:1.5;
      background:#040a14;
      border:1px solid var(--line);
      border-radius:12px;
      padding:12px;
    }
    .rules{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:8px;
    }
    .rule{
      padding:6px 10px;
      border-radius:999px;
      background:#09172a;
      border:1px solid var(--line);
      font-size:12px;
      color:#cce7ff;
    }
    .steps{
      margin:0;
      padding-right:18px;
      font-size:13px;
      color:#d8e6ff;
      line-height:1.8;
    }
    .glow{
      animation: glowPulse 2.2s ease-in-out infinite;
    }
    @keyframes glowPulse{
      0%,100%{box-shadow:0 0 0 rgba(56,189,248,.0)}
      50%{box-shadow:0 0 25px rgba(56,189,248,.22)}
    }
  </style>
</head>
<body>
  <div class="topbar">
    <button class="btn" onclick="refreshAll()">تحديث</button>
    <div class="status" id="refreshStatus">starting...</div>
    <div class="subtitle">متصفح حي للوكلاء + الدماغ + الجينات + الوظائف + الـ patches</div>
    <div class="brand">FRIDAY AGENTS BROWSER</div>
  </div>

  <div class="layout">
    <div class="left">
      <div class="card glow">
        <h3>🧠 عقل FRIDAY وتشغيل الوكلاء</h3>
        <div class="network-wrap">
          <canvas id="network"></canvas>
        </div>
      </div>

      <div class="card">
        <h3>📜 آخر نشاط حي</h3>
        <div class="console" id="consoleBox">loading...</div>
      </div>
    </div>

    <div class="right">
      <div class="card">
        <h3>⚡ حالة الدماغ</h3>
        <div class="grid-stats">
          <div class="stat"><div class="label">Version</div><div class="value" id="brainVersion">-</div></div>
          <div class="stat"><div class="label">Jobs</div><div class="value" id="jobsStored">-</div></div>
          <div class="stat"><div class="label">Patches</div><div class="value" id="patchesStored">-</div></div>
          <div class="stat"><div class="label">Agent Runs</div><div class="value" id="agentRunsStored">-</div></div>
        </div>
        <div class="brain-meta">
          <div class="mini">آخر توليد: <span id="brainGenerated">-</span></div>
          <div class="mini">آخر Job: <span id="latestJob">-</span></div>
          <div class="mini">Patch Quality: <span id="patchQuality">-</span></div>
          <div class="mini">Project Files: <span id="projectFiles">-</span></div>
        </div>
        <div class="rules" id="rulesBox"></div>
      </div>

      <div class="card">
        <h3>🧬 الجينات والاستراتيجيات</h3>
        <div class="genes-grid" id="genesBox"></div>
      </div>

      <div class="card">
        <h3>🚀 آخر الوظائف والـ patches</h3>
        <div class="list" id="jobsBox"></div>
      </div>

      <div class="card">
        <h3>✅ الخطوات القادمة</h3>
        <ol class="steps" id="stepsBox"></ol>
      </div>
    </div>
  </div>

<script>
let latestData = null;

function text(v){
  if(v === null || v === undefined || v === "") return "-";
  return String(v);
}

function escapeHtml(value){
  return String(value ?? "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;");
}

function statusClass(s){
  const x = String(s || "").toLowerCase();
  if (["running","done","failed","queued","cancelled"].includes(x)) return x;
  return "";
}

function refreshAll(){
  fetch("/api/overview")
    .then(r => r.json())
    .then(data => {
      latestData = data;
      renderBrain(data);
      renderGenes(data);
      renderJobs(data);
      renderConsole(data);
      drawNetwork(data);
      document.getElementById("refreshStatus").textContent = "updated " + new Date().toLocaleTimeString();
    })
    .catch(err => {
      document.getElementById("refreshStatus").textContent = "ERROR: " + err;
    });
}

function renderBrain(data){
  const b = data.brain || {};
  const pq = b.patch_quality || {};
  const latestJob = b.latest_job || {};
  const projectMap = data.project_map || {};
  const rules = b.rules || {};

  document.getElementById("brainVersion").textContent = text(b.version);
  document.getElementById("jobsStored").textContent = text(b.jobs_stored);
  document.getElementById("patchesStored").textContent = text(b.patches_stored);
  document.getElementById("agentRunsStored").textContent = text(b.agent_runs_stored);
  document.getElementById("brainGenerated").textContent = text(b.generated_at);
  document.getElementById("latestJob").textContent = latestJob.id ? ("#" + latestJob.id + " | " + text(latestJob.status || "")) : "-";
  document.getElementById("patchQuality").textContent = "G:" + text(pq.good) + " | F:" + text(pq.fair) + " | P:" + text(pq.poor);
  document.getElementById("projectFiles").textContent = text(projectMap.total_files || "-");

  const rulesBox = document.getElementById("rulesBox");
  rulesBox.innerHTML = "";
  Object.entries(rules).forEach(([k,v]) => {
    const div = document.createElement("div");
    div.className = "rule";
    div.textContent = k + ": " + v;
    rulesBox.appendChild(div);
  });

  const steps = document.getElementById("stepsBox");
  steps.innerHTML = "";
  (b.next_steps || []).forEach(step => {
    const li = document.createElement("li");
    li.textContent = String(step);
    steps.appendChild(li);
  });
}

function renderGenes(data){
  const genes = data.genes || [];
  const box = document.getElementById("genesBox");
  if (!genes.length){
    box.innerHTML = '<div class="gene">لا توجد جينات بعد</div>';
    return;
  }

  box.innerHTML = genes.map(g => `
    <div class="gene">
      <div class="score">${Number(g.score || 0).toFixed(2)}</div>
      <div>boost=${Number(g.confidence_boost || 0).toFixed(3)} | seen=${g.seen || 0}</div>
      <div>W/L/N = ${g.wins || 0}/${g.losses || 0}/${g.neutral || 0}</div>
      <div class="id">${escapeHtml(g.gene_id || "")}</div>
    </div>
  `).join("");
}

function renderJobs(data){
  const jobs = data.jobs || [];
  const patches = data.recent_patches || [];
  const patchStats = data.patch_stats || {};

  const jobsHtml = jobs.map(j => `
    <div class="row">
      <div>
        <b>Job #${j.id}</b><br>
        <span class="mono">${escapeHtml(j.model || "-")}</span>
      </div>
      <div class="pill ${statusClass(j.status)}">${escapeHtml(j.status || "-")}</div>
      <div class="mono">${escapeHtml(j.updated_at || j.created_at || "-")}</div>
      <div class="mono">${j.report_path ? "report" : "-"}</div>
    </div>
  `).join("");

  const patchesHtml = patches.slice(0, 8).map(p => `
    <div class="row">
      <div>
        <b>Patch #${p.id}</b><br>
        <span class="mono">${escapeHtml((p.target_file || "").split("\\\\").pop())}</span>
      </div>
      <div class="mono">${escapeHtml(p.agent_name || "-")}/${escapeHtml(p.agent_role || "-")}</div>
      <div class="risk-${String(p.risk || "").toLowerCase()}">${escapeHtml(p.risk || "-")}</div>
      <div class="mono">A:${p.approved} / P:${p.applied}</div>
    </div>
  `).join("");

  document.getElementById("jobsBox").innerHTML =
    `<div class="mini" style="margin-bottom:8px">
      Patch Stats → total=${patchStats.total || 0}, low=${patchStats.low || 0}, medium=${patchStats.medium || 0}, high=${patchStats.high || 0}, approved=${patchStats.approved || 0}, applied=${patchStats.applied || 0}
    </div>` +
    jobsHtml +
    `<div style="height:10px"></div>` +
    patchesHtml;
}

function renderConsole(data){
  const activeRuns = data.active_runs || [];
  const recentRuns = data.recent_runs || [];
  const b = data.brain || {};
  const learned = b.learned || [];
  const rejected = b.rejected_patches || [];
  const logTail = data.log_tail || "";

  let out = "";
  out += "=== ACTIVE AGENTS ===\n";
  if (!activeRuns.length) {
    out += "No active agent runs.\n";
  } else {
    activeRuns.forEach(r => {
      out += `Job #${r.job_id} | ${r.agent_name}/${r.agent_role} | ${r.status} | ${r.created_at}\n`;
    });
  }

  out += "\n=== RECENT AGENT RUNS ===\n";
  recentRuns.slice(0, 12).forEach(r => {
    out += `#${r.id} | Job ${r.job_id} | ${r.agent_name}/${r.agent_role} | ${r.status}\n`;
  });

  out += "\n=== FRIDAY LEARNED ===\n";
  if (Array.isArray(learned) && learned.length){
    learned.forEach(x => out += "- " + x + "\n");
  } else {
    out += "- no structured learned lines stored\n";
  }

  out += "\n=== REJECTED PATCHES ===\n";
  if (Array.isArray(rejected) && rejected.length){
    rejected.slice(0, 8).forEach(x => {
      if (typeof x === "string") out += "- " + x + "\n";
      else out += "- " + JSON.stringify(x) + "\n";
    });
  } else {
    out += "- none\n";
  }

  out += "\n=== DISPATCH LOG TAIL ===\n";
  out += logTail || "(empty)";

  document.getElementById("consoleBox").textContent = out;
}

function drawNetwork(data){
  const canvas = document.getElementById("network");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = rect.height * devicePixelRatio;
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";

  const ctx = canvas.getContext("2d");
  ctx.scale(devicePixelRatio, devicePixelRatio);

  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0,0,w,h);

  const center = {x: w/2, y: h/2};
  const t = Date.now() / 1000;

  for(let i=0;i<60;i++){
    const x = (i * 137.5) % w;
    const y = (i * 91.3) % h;
    ctx.fillStyle = "rgba(148,163,184,0.10)";
    ctx.beginPath();
    ctx.arc(x, y, 1.2 + ((i % 5) * 0.25), 0, Math.PI*2);
    ctx.fill();
  }

  const agents = (data.agents || []).slice(0, 24);
  const runningNames = new Set((data.active_runs || []).map(x => (x.agent_name || "") + "|" + (x.agent_role || "")));

  const radius = Math.min(w, h) * 0.34;
  const nodes = [];

  agents.forEach((a, i) => {
    const ang = (Math.PI * 2 * i / Math.max(agents.length,1)) + t * 0.07;
    const x = center.x + Math.cos(ang) * radius;
    const y = center.y + Math.sin(ang) * (radius * 0.78);

    const key = (a.name || "") + "|" + (a.role || "");
    const running = runningNames.has(key);
    const failed = Number(a.failed || 0) > Number(a.done || 0) && !running;

    let color = "#38bdf8";
    if (running) color = "#06b6d4";
    else if (failed) color = "#ef4444";
    else if ((a.reliability || 0) >= 95) color = "#22c55e";
    else if ((a.reliability || 0) > 0) color = "#eab308";

    nodes.push({...a, x, y, color, running});
  });

  nodes.forEach((n, idx) => {
    const pulse = n.running ? 0.5 + 0.5 * Math.sin(t*5 + idx) : 0.25;
    ctx.strokeStyle = n.color.replace(")", "," + (0.15 + pulse*0.25) + ")");
    ctx.strokeStyle = "rgba(56,189,248," + (0.10 + pulse*0.18) + ")";
    ctx.lineWidth = n.running ? 2 : 1;

    ctx.beginPath();
    ctx.moveTo(center.x, center.y);
    ctx.lineTo(n.x, n.y);
    ctx.stroke();

    if (n.running){
      const px = center.x + (n.x - center.x) * ((Math.sin(t*3 + idx)+1)/2);
      const py = center.y + (n.y - center.y) * ((Math.sin(t*3 + idx)+1)/2);
      ctx.fillStyle = "#8b5cf6";
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI*2);
      ctx.fill();
    }
  });

  const brainPulse = 18 + Math.sin(t*2.5)*5;
  ctx.fillStyle = "rgba(56,189,248,0.18)";
  ctx.beginPath();
  ctx.arc(center.x, center.y, 62 + brainPulse, 0, Math.PI*2);
  ctx.fill();

  ctx.fillStyle = "rgba(139,92,246,0.20)";
  ctx.beginPath();
  ctx.arc(center.x, center.y, 44 + Math.sin(t*4)*3, 0, Math.PI*2);
  ctx.fill();

  ctx.fillStyle = "#38bdf8";
  ctx.beginPath();
  ctx.arc(center.x, center.y, 34, 0, Math.PI*2);
  ctx.fill();

  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 20px Arial";
  ctx.textAlign = "center";
  ctx.fillText("FRIDAY", center.x, center.y - 4);
  ctx.font = "12px Arial";
  ctx.fillStyle = "#dbeafe";
  ctx.fillText("Brain", center.x, center.y + 16);

  nodes.forEach((n) => {
    ctx.fillStyle = n.color;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.running ? 14 : 11, 0, Math.PI*2);
    ctx.fill();

    if (n.running){
      ctx.strokeStyle = "rgba(6,182,212,0.65)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(n.x, n.y, 20 + Math.sin(t*6)*2, 0, Math.PI*2);
      ctx.stroke();
    }

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px Arial";
    ctx.textAlign = "center";
    ctx.fillText(n.name || "A", n.x, n.y + 32);
    ctx.fillStyle = "#9fb6d8";
    ctx.font = "11px Arial";
    ctx.fillText((n.role || "").slice(0, 14), n.x, n.y + 46);
  });
}

refreshAll();
setInterval(refreshAll, 2500);
setInterval(() => {
  if (latestData) drawNetwork(latestData);
}, 80);
</script>
</body>
</html>
"""


def main():
    uvicorn.run(
        "friday_agents_browser:app",
        host="127.0.0.1",
        port=8833,
        reload=False,
    )


if __name__ == "__main__":
    main()
