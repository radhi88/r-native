#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PlutoBrain-inspired agent memory layer.

This is a local markdown/JSON "brain" for the trading agents:
- agent minds: what each agent saw, voted, and told others
- message bus: agent-to-agent communication in plain text
- task queue: bounded tasks agents propose for each other
- dynamic blueprints: proposed agents, never arbitrary code execution
- typed edges: a compact graph for later lookup
"""
import csv
import json
import datetime
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
BRAIN = BASE / "brain_vault"
COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")

STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV = COMMON / "smc_decisions.csv"
VP_SIGNAL = BASE / "volume_profile_signal.json"

MIND_JSON = BRAIN / "agent_minds.json"
TASKS_JSON = BRAIN / "agent_tasks.json"
BLUEPRINTS_JSON = BRAIN / "agent_blueprints.json"
TYPED_EDGES = BRAIN / "typed-edges.jsonl"
AGENT_EDGES = BRAIN / "agent-edges.jsonl"
LOG_MD = BRAIN / "log.md"
INDEX_MD = BRAIN / "index.md"
AGENT_PAGES = BRAIN / "00 Notes" / "concepts" / "agents"
DYNAMIC_AGENT_PAGES = BRAIN / "03 Projects" / "MT5 Agent System" / "dynamic-agents"
PROJECT_DIR = BRAIN / "03 Projects" / "MT5 Agent System"
PLUTOBRAIN_SCRIPT = BASE.parent / "vendor" / "plutobrain" / "05 Skills" / "scripts" / "typed-links-extract.py"


def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_status():
    return _read_json(STATUS_JSON, {})


def _read_smc_tail(limit=80):
    rows = []
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
    except Exception:
        return []
    return rows[-limit:]


def _read_report(agent):
    try:
        report = agent["path"].parent / "report.md"
        if report.exists():
            return report.read_text(encoding="utf-8")[:700]
    except Exception:
        pass
    return ""


def _slug(text):
    keep = []
    for ch in str(text).lower():
        keep.append(ch if ch.isalnum() else "-")
    return "-".join("".join(keep).split("-"))[:80] or "item"


def _append_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_log(section):
    BRAIN.mkdir(parents=True, exist_ok=True)
    if not LOG_MD.exists():
        LOG_MD.write_text("# Agent Brain Timeline\n\n", encoding="utf-8")
    with open(LOG_MD, "a", encoding="utf-8") as f:
        f.write(section.rstrip() + "\n\n")


def _concept_page(slug, title, summary, truth, now):
    path = BRAIN / "00 Notes" / "concepts" / f"{slug}.md"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
type: concept
name: {title}
slug: {slug}
created: {now[:10]}
status: enriched
tier: 2
creator: codex
source: mt5-agent-brain
---

# {title}

> {summary}

## Compiled truth

{truth}

## Mentioned in

- [[Agent Brain Timeline]] - local trading agent memory ({now[:10]})

---

## Timeline

- {now}: Created while installing the real PlutoBrain vault into the MT5 project.
""", encoding="utf-8")
    return path


def _ensure_core_plutobrain_pages(now):
    _concept_page("mt5-live-ea", "MT5 Live EA", "The local MQL5 expert advisor that executes trades.", "The [[MT5 Live EA]] receives fast tick decisions locally and is observed by [[Mujammi]], [[Muraaqib]], and [[Haaris]].", now)
    _concept_page("agent-brain-timeline", "Agent Brain Timeline", "Append-only timeline for local trading agents.", "The [[Agent Brain Timeline]] records how agents communicate, delegate tasks, and evolve decisions.", now)
    _concept_page("xauusdm", "XAUUSDm", "The live gold symbol traded by the EA.", "[[XAUUSDm]] is the market observed by [[Mujalid]], [[Muraaqib]], and the [[MT5 Live EA]].", now)
    _concept_page("smc", "SMC", "Smart Money Concepts signal layer.", "[[SMC]] contributes bias, BOS, OB, and FVG context to [[Mujammi]].", now)
    _concept_page("volume-profile", "Volume Profile", "Local 200-bar profile built from MT5 candle history.", "[[Volume Profile]] is computed by [[Mujalid]] and passed to [[Mujammi]].", now)
    _concept_page("risk-management", "Risk Management", "Guardrails for live account execution.", "[[Risk Management]] is monitored by [[Haaris]] and [[Mudir]].", now)


def _run_typed_links():
    if not PLUTOBRAIN_SCRIPT.exists():
        return {"ok": False, "error": "typed-links-extract.py missing"}
    try:
        result = subprocess.run(
            [sys.executable, str(PLUTOBRAIN_SCRIPT), "--vault", str(BRAIN), "--quiet"],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-1200:],
            "stderr": result.stderr[-500:],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _decision_stats(rows):
    total = len(rows)
    blocked = sum(1 for r in rows if "BLOCK" in (r.get("decision") or ""))
    entries = sum(1 for r in rows if "ENTRY" in (r.get("decision") or ""))
    reasons = {}
    for r in rows:
        reason = (r.get("reason") or "unknown").strip() or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
    top_reason = max(reasons, key=reasons.get) if reasons else "none"
    return {"total": total, "blocked": blocked, "entries": entries, "top_reason": top_reason}


def _make_task(tasks, key, title, assigned_to, source, priority, evidence):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    existing = next((t for t in tasks if t.get("key") == key and t.get("status") == "open"), None)
    if existing:
        existing["updated"] = now
        existing["count"] = int(existing.get("count", 1)) + 1
        existing["evidence"] = evidence
        return existing
    task = {
        "key": key,
        "title": title,
        "assigned_to": assigned_to,
        "source": source,
        "priority": priority,
        "status": "open",
        "created": now,
        "updated": now,
        "count": 1,
        "evidence": evidence,
    }
    tasks.insert(0, task)
    return task


def _make_blueprint(blueprints, agent_id, name, role, reason):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    bp = blueprints.get(agent_id, {})
    bp.update({
        "id": agent_id,
        "name": name,
        "role": role,
        "reason": reason,
        "status": bp.get("status", "proposed"),
        "allowed_actions": ["observe", "write_report", "suggest_task"],
        "created": bp.get("created", now),
        "last_seen": now,
        "seen_count": int(bp.get("seen_count", 0)) + 1,
    })
    blueprints[agent_id] = bp
    return bp


def _agent_mind(agent, result, vote, status, vp, decisions):
    report = _read_report(agent)
    status_text = result.get("status", "?")
    top_reason = decisions.get("top_reason", "none")
    observation = "يراقب الحالة العامة."
    if agent["eng"] == "Mujalid":
        observation = f"VP={vp.get('trade_signal','N/A')} source={vp.get('source','N/A')} spread={vp.get('avg_spread_points','N/A')}"
    elif agent["eng"] == "Mujammi":
        observation = "يجمع الأصوات ويحوّلها إلى موافقة أو حظر."
    elif agent["eng"] == "Muhallib":
        observation = f"آخر قرارات SMC: blocked={decisions.get('blocked',0)} entries={decisions.get('entries',0)} reason={top_reason}"
    elif agent["eng"] == "Haaris":
        observation = f"trade_allowed={status.get('trade_allowed')} reason={status.get('trade_block_reason','ok')}"
    elif agent["eng"] == "Mutawwir":
        observation = f"DNA gen={status.get('generation', status.get('dna_gen'))} gap={status.get('dna_gap')} tp={status.get('dna_tp')} sl={status.get('dna_sl')}"

    if vote == 1:
        stance = "supports_entry"
    elif vote == 0 and agent["eng"] in ("Mujalid", "Mujammi", "Muhallib"):
        stance = "withholds_vote"
    else:
        stance = "observes"

    return {
        "name": agent["name"],
        "eng": agent["eng"],
        "emoji": agent["emoji"],
        "status": status_text,
        "vote": vote,
        "stance": stance,
        "observation": observation,
        "report_excerpt": report[:360],
    }


def _write_agent_pages(now, minds):
    AGENT_PAGES.mkdir(parents=True, exist_ok=True)
    for mind in minds:
        path = AGENT_PAGES / f"{_slug(mind['eng'])}.md"
        timeline = f"- {now}: stance={mind['stance']} vote={mind['vote']} observation={mind['observation']}"
        content = f"""---
type: concept
name: {mind['name']}
slug: {_slug(mind['eng'])}
eng: {mind['eng']}
status: {mind['status']}
creator: codex
source: mt5-agent-brain
---

# {mind['emoji']} {mind['name']} ({mind['eng']})

> Trading agent mind page compiled from the live orchestrator cycle.

## Compiled truth

Current role: {mind['observation']}

Current stance: **{mind['stance']}**.
Latest vote: **{mind['vote']}**.

This agent advises [[Mujammi]] and observes [[MT5 Live EA]], [[XAUUSDm]], [[SMC]], [[Volume Profile]], and [[Risk Management]] depending on its role.

## Mentioned in

- [[Agent Brain Timeline]] - latest orchestrator cycle ({now[:10]})

## Latest report excerpt
{mind['report_excerpt']}

---

## Timeline
{timeline}
"""
        path.write_text(content, encoding="utf-8")


def _write_dynamic_agent_pages(now, blueprints, tasks, status, vp, decisions):
    DYNAMIC_AGENT_PAGES.mkdir(parents=True, exist_ok=True)
    pages = []
    for bp in blueprints.values():
        assigned = [
            t for t in tasks
            if str(t.get("assigned_to", "")).lower() in (bp["id"].replace("-", " "), bp["name"].lower(), bp["id"].lower())
        ]
        if bp["id"] == "spread-sentinel":
            execution = (
                f"Observed avg spread={vp.get('avg_spread_points', status.get('spread_points'))} points. "
                f"Current gap={status.get('dna_gap')} effective_gap={status.get('effective_gap')}. "
                "Recommendation: keep stop-reverse distance comfortably above live spread and do not tighten pending stops while spread is elevated."
            )
        elif bp["id"] == "entry-gate-doctor":
            execution = (
                f"Observed blocked={decisions.get('blocked')} of {decisions.get('total')} recent decisions; "
                f"top reason={decisions.get('top_reason')}. "
                "Recommendation: verify the reloaded EA is using the new input defaults; change only one gate per cycle."
            )
        elif bp["id"] == "conflict-arbiter":
            execution = (
                f"Observed SMC bias={status.get('smc_bias')} and VP signal={vp.get('trade_signal')}. "
                "Recommendation: require written conflict note before changing direction."
            )
        else:
            execution = "Observed assigned context and wrote bounded report."

        task_lines = "\n".join(
            f"- [{t.get('priority')}] {t.get('title')} (count={t.get('count', 1)})"
            for t in assigned
        ) or "- No active direct tasks."
        path = DYNAMIC_AGENT_PAGES / f"{bp['id']}.md"
        path.write_text(f"""---
type: dynamic_agent
id: {bp['id']}
status: {bp['status']}
creator: codex
source: mt5-agent-brain
---

# {bp['name']}

Role: {bp['role']}

Reason created: {bp['reason']}

Allowed actions: {", ".join(bp.get("allowed_actions", []))}

## Last bounded execution
{execution}

This proposed agent reports to [[Mujammi]] and writes into [[Agent Brain Timeline]]. It does not execute arbitrary code.

## Assigned tasks
{task_lines}

Updated: {now}
""", encoding="utf-8")
        pages.append({"id": bp["id"], "name": bp["name"], "path": str(path), "execution": execution})
    return pages


def record_cycle(agents, results, confluence):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    BRAIN.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_core_plutobrain_pages(now)

    status = _read_status()
    vp = _read_json(VP_SIGNAL, {})
    smc_rows = _read_smc_tail()
    decisions = _decision_stats(smc_rows)
    agent_votes = confluence.get("agent_votes", {}) if isinstance(confluence, dict) else {}

    vote_by_agent = {
        "Mujalid": agent_votes.get("volume_profile"),
        "Mujammi": 1 if confluence.get("approved") else 0,
        "Muraaqib": agent_votes.get("monitor"),
        "Haaris": agent_votes.get("guard"),
        "Muhallib": agent_votes.get("analyst"),
    }

    minds = []
    for agent in agents:
        minds.append(_agent_mind(
            agent,
            results.get(agent["eng"], {}),
            vote_by_agent.get(agent["eng"], None),
            status,
            vp,
            decisions,
        ))

    messages = []
    direction = confluence.get("direction", "BLOCKED")
    if vp.get("trade_signal"):
        messages.append({
            "time": now,
            "from": "Mujalid",
            "to": "Mujammi",
            "type": "evidence",
            "body": f"Volume profile from {vp.get('source')} says {vp.get('trade_signal')} at price {vp.get('price')} with POC {vp.get('poc')}.",
        })
    if confluence.get("approved"):
        messages.append({
            "time": now,
            "from": "Mujammi",
            "to": "all",
            "type": "decision",
            "body": f"Confluence approved {direction} with {confluence.get('votes')}/{confluence.get('total')} votes.",
        })
    if status.get("smc_bias") and direction in ("BUY", "SELL") and status.get("smc_bias") != direction:
        messages.append({
            "time": now,
            "from": "Muhaqqiq",
            "to": "Mujammi",
            "type": "conflict",
            "body": f"SMC bias is {status.get('smc_bias')} while confluence direction is {direction}; require written conflict note.",
        })

    tasks = _read_json(TASKS_JSON, [])
    if confluence.get("approved"):
        _make_task(
            tasks,
            f"watch-approved-{direction.lower()}",
            f"راقب أول شمعة بعد موافقة {direction} وتحقق هل دخل EA أم بقي بلا صفقة",
            "Muraaqib",
            "Mujammi",
            "high",
            {"confluence": confluence, "positions": status.get("positions")},
        )
    if float(vp.get("avg_spread_points") or status.get("spread_points") or 0) >= 250:
        _make_task(
            tasks,
            "spread-shock-model",
            "ابنِ نموذج سبريد: متى نوسع gap ومتى نمنع الستوبات القريبة",
            "Spread Sentinel",
            "Mujalid",
            "high",
            {"spread_points": vp.get("avg_spread_points") or status.get("spread_points"), "bars": vp.get("bars")},
        )
    if status.get("smc_bias") and direction in ("BUY", "SELL") and status.get("smc_bias") != direction:
        _make_task(
            tasks,
            "smc-vp-conflict",
            "اكتب قرار ترجيح عندما SMC يخالف Volume Profile",
            "Conflict Arbiter",
            "Muhaqqiq",
            "medium",
            {"smc_bias": status.get("smc_bias"), "confluence_direction": direction, "vp_signal": vp.get("trade_signal")},
        )
    if decisions["total"] and decisions["blocked"] / max(1, decisions["total"]) > 0.8:
        _make_task(
            tasks,
            "entry-gate-audit",
            "راجع أسباب BLOCKED واطلب تعديل فلتر واحد فقط في كل دورة",
            "Mutawwir",
            "Muhallib",
            "medium",
            decisions,
        )
    _write_json(TASKS_JSON, tasks[:100])

    blueprints = _read_json(BLUEPRINTS_JSON, {})
    if float(vp.get("avg_spread_points") or status.get("spread_points") or 0) >= 250:
        _make_blueprint(blueprints, "spread-sentinel", "حارس السبريد", "يراقب صدمة السبريد ويقترح gap/SL distance", "spread above live threshold")
    if status.get("smc_bias") and direction in ("BUY", "SELL") and status.get("smc_bias") != direction:
        _make_blueprint(blueprints, "conflict-arbiter", "حَكَم التعارض", "يوفق بين SMC وVolume Profile وConfluence", "SMC bias conflicts with confluence")
    if decisions.get("top_reason") in ("ranging", "ema_mixed", "weak_candle"):
        _make_blueprint(blueprints, "entry-gate-doctor", "طبيب بوابة الدخول", "يشخص سبب الحظر المتكرر ويقترح تخفيفاً واحداً", f"top blocked reason is {decisions.get('top_reason')}")
    _write_json(BLUEPRINTS_JSON, blueprints)
    dynamic_pages = _write_dynamic_agent_pages(now, blueprints, tasks, status, vp, decisions)

    edges = []
    for msg in messages:
        edges.append({"time": now, "source": msg["from"], "relation": msg["type"], "target": msg["to"], "evidence": msg["body"]})
    for task in tasks[:6]:
        edges.append({"time": now, "source": task["source"], "relation": "assigns_task", "target": task["assigned_to"], "task": task["key"]})
    for bp in blueprints.values():
        edges.append({"time": now, "source": "agent_brain", "relation": "proposes_agent", "target": bp["id"], "reason": bp["reason"]})
    for page in dynamic_pages:
        edges.append({"time": now, "source": page["id"], "relation": "writes_report", "target": page["path"], "evidence": page["execution"]})
    _append_jsonl(AGENT_EDGES, edges)

    _write_agent_pages(now, minds)
    typed_links = _run_typed_links()

    snapshot = {
        "time": now,
        "confluence": confluence,
        "status": {
            "symbol": status.get("symbol"),
            "price": status.get("bid") or status.get("close"),
            "spread_points": status.get("spread_points"),
            "positions": status.get("positions"),
            "trade_allowed": status.get("trade_allowed"),
            "smc_bias": status.get("smc_bias"),
            "smc_status": status.get("smc_status"),
        },
        "volume_profile": vp,
        "decision_stats": decisions,
        "minds": minds,
        "messages": messages[-30:],
        "tasks": tasks[:20],
        "blueprints": list(blueprints.values()),
        "dynamic_agents": dynamic_pages,
        "typed_links": typed_links,
        "paths": {
            "log": str(LOG_MD),
            "typed_edges": str(TYPED_EDGES),
            "agent_edges": str(AGENT_EDGES),
            "tasks": str(TASKS_JSON),
            "blueprints": str(BLUEPRINTS_JSON),
            "dynamic_agents": str(DYNAMIC_AGENT_PAGES),
            "plutobrain_vendor": str(BASE.parent / "vendor" / "plutobrain"),
        },
    }
    _write_json(MIND_JSON, snapshot)

    msg_lines = "\n".join(f"- **{m['from']} → {m['to']}**: {m['body']}" for m in messages) or "- لا توجد رسائل جديدة."
    task_lines = "\n".join(f"- [{t['priority']}] {t['assigned_to']}: {t['title']}" for t in tasks[:6]) or "- لا توجد مهام."
    _append_log(f"""## {now}

Confluence: **{direction}** approved={confluence.get('approved')} votes={confluence.get('votes')}/{confluence.get('total')}

### Messages
{msg_lines}

### Tasks
{task_lines}
""")

    INDEX_MD.write_text(f"""# Agent Brain Index

Last update: {now}

## Current decision
- Confluence: **{direction}**
- Approved: **{confluence.get('approved')}**
- Votes: **{confluence.get('votes')}/{confluence.get('total')}**
- VP: **{vp.get('trade_signal', 'N/A')}** from `{vp.get('source', 'N/A')}`
- Spread: **{vp.get('avg_spread_points', status.get('spread_points', 'N/A'))}**

## Files
- `agent_minds.json` — dashboard snapshot
- `agent_tasks.json` — open delegated tasks
- `agent_blueprints.json` — proposed bounded agents
- `typed-edges.jsonl` — graph edges
- `agent-edges.jsonl` — agent communication/delegation edges
- `log.md` — append-only conversation timeline
- `00 Notes/concepts/agents/*.md` — compiled truth + timeline per agent
- `03 Projects/MT5 Agent System/dynamic-agents/*.md` — bounded dynamic-agent reports
""", encoding="utf-8")

    return {
        "time": now,
        "messages": len(messages),
        "tasks": len(tasks),
        "blueprints": len(blueprints),
        "path": str(BRAIN),
    }
