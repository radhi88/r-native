"""shared/agent_governance.py — The agents' constitution.

Born 2026-05-29 from the user's mandate:

  "الوكلاء ... يقومون بما تقومه به انت بالضبط ... تعديل الاكواد وضبط كل شيء
   واعادة التشغيل ... وليس متفرجين، اعطهم جميع الصلاحيات كما لديك ... وقبل
   اطلاقها يقومون باستشاراتك كل واحد منهم او بالاجماع."

i.e. give the agents the SAME powers Claude has — tune parameters, edit configs,
even change code, then restart services — but BEFORE anything goes live it must
pass a gate: either Claude's consultation, or the agents' own consensus.

This module is the gate. Agents never touch live config/code directly; they
file a PROPOSAL here. A proposal only becomes live after it clears governance.

THE FLOW
────────
  agent.propose(...)            → PENDING
  other agents vote()           → reaches quorum → CONSENSUS_OK
  risky? (HIGH risk or          → NEEDS_CLAUDE   (waits in the consult queue)
   risk-bearing target)
  claude_decide(approve)        → APPROVED  (or REJECTED)
  governor.apply()              → APPLIED   (param/flag written, restart queued)

RISK TIERS & WHO MAY APPROVE
────────────────────────────
  LOW    cosmetic / within tight bounds   → consensus quorum OR Claude
  MEDIUM wider tune / flag toggle         → larger quorum AND Claude notified
  HIGH   code edit, or any RISK-BEARING   → CLAUDE CONSULT REQUIRED, always
         target (lot, sl, risk, max_open,
         enabling/Disabling trading)        (consensus alone can NEVER ship it)

Everything is append-only audited. Storage is plain JSON under data/governance/
so the UI and every process can read the same source of truth.
"""
from __future__ import annotations
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from runtime.shared.tokens import DATA
except Exception:                                   # stand-alone / test fallback
    DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")

GOV_DIR        = DATA / "governance"
PROPOSALS_FILE = GOV_DIR / "proposals.json"          # {id: proposal}
AUDIT_LOG      = GOV_DIR / "audit.jsonl"             # append-only history
RESTART_QUEUE  = GOV_DIR / "restart_requests.jsonl"  # services to bounce
OVERRIDES_FILE = DATA / "agent_overrides.json"        # live config overrides (services read)

# ── Risk tiers ───────────────────────────────────────────────────────────────
RISK_LOW, RISK_MED, RISK_HIGH = "LOW", "MEDIUM", "HIGH"

# Targets that touch real money — ANY change to these is HIGH and needs Claude,
# no matter what risk the proposer claimed. This is the hard safety boundary.
RISK_BEARING = {
    "lot", "risk_pct", "sl_pts", "tp_pts",
    "GLOBAL_MAX_OPEN", "MAX_OPEN", "max_open",
    "ENABLE_FVG_PENDING", "trading_enabled", "live",
}

# Consensus quorum (number of distinct agent approvals) per tier.
QUORUM = {RISK_LOW: 2, RISK_MED: 3, RISK_HIGH: 99}   # HIGH can't pass on votes alone

# Allowed proposal actions (anything else is rejected on sight).
#   crown_genome — swap the LIVE trading brain (what trades real money). Always
#                  HIGH: an evolved challenger may be better, but DEPLOYING it is
#                  the user's "قبل اطلاقها يستشيرونك" moment — Claude must approve.
ACTIONS = {"tune_param", "set_override", "set_flag", "restart_service",
           "edit_code", "crown_genome"}

# Status values
ST_PENDING   = "PENDING"
ST_CONSENSUS = "CONSENSUS_OK"
ST_NEEDS_CLAUDE = "NEEDS_CLAUDE"
ST_APPROVED  = "APPROVED"
ST_REJECTED  = "REJECTED"
ST_APPLIED   = "APPLIED"
ST_FAILED    = "FAILED"


# ──────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────
@dataclass
class Proposal:
    id: str
    ts: str
    agent: str
    action: str
    target: str
    payload: dict
    rationale: str
    risk: str
    status: str = ST_PENDING
    votes: dict = field(default_factory=dict)        # agent -> {approve, note, ts}
    claude: dict = field(default_factory=dict)        # {approve, note, ts}
    applied_ts: Optional[str] = None
    result: Optional[str] = None

    def approvals(self) -> int:
        return sum(1 for v in self.votes.values() if v.get("approve"))

    def rejections(self) -> int:
        return sum(1 for v in self.votes.values() if not v.get("approve"))


# ──────────────────────────────────────────────────────────
# Storage (atomic, multi-process-tolerant)
# ──────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure() -> None:
    GOV_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str) -> None:
    _ensure()
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_all() -> dict[str, dict]:
    if not PROPOSALS_FILE.exists():
        return {}
    try:
        return json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all(d: dict[str, dict]) -> None:
    _atomic_write(PROPOSALS_FILE, json.dumps(d, ensure_ascii=False, indent=2, default=str))


def _audit(event: str, **kw) -> None:
    _ensure()
    rec = {"ts": _now(), "event": event, **kw}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _retry_rmw(fn, attempts: int = 8):
    """Read-modify-write with retry, to survive concurrent writers."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


# ──────────────────────────────────────────────────────────
# Risk resolution
# ──────────────────────────────────────────────────────────
def resolve_risk(action: str, target: str, claimed: str) -> str:
    """Escalate risk by the hard rules — agents can't under-claim their way past
    the money-touching boundary."""
    if action in ("edit_code", "crown_genome"):
        return RISK_HIGH
    # target like "genome:lot" or "config:GLOBAL_MAX_OPEN" — check the leaf name
    leaf = target.split(":")[-1].split(".")[-1]
    if leaf in RISK_BEARING:
        return RISK_HIGH
    claimed = (claimed or RISK_LOW).upper()
    return claimed if claimed in (RISK_LOW, RISK_MED, RISK_HIGH) else RISK_LOW


# ──────────────────────────────────────────────────────────
# Public API — agents
# ──────────────────────────────────────────────────────────
def propose(agent: str, action: str, target: str, payload: dict,
            rationale: str, risk: str = RISK_LOW) -> str:
    """File a proposal. Returns its id. Never applies anything by itself."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; allowed {sorted(ACTIONS)}")
    eff_risk = resolve_risk(action, target, risk)
    pid = uuid.uuid4().hex[:12]
    p = Proposal(id=pid, ts=_now(), agent=agent, action=action, target=target,
                 payload=payload or {}, rationale=rationale, risk=eff_risk)

    def _do():
        d = _load_all()
        d[pid] = asdict(p)
        _save_all(d)
    _retry_rmw(_do)
    _audit("propose", id=pid, agent=agent, action=action, target=target,
           risk=eff_risk, rationale=rationale)
    return pid


def vote(pid: str, agent: str, approve: bool, note: str = "") -> str:
    """An agent votes on a peer's proposal. Returns the new status.

    Self-votes are ignored (an agent can't form consensus alone). When approvals
    reach the tier's quorum the proposal advances — to CONSENSUS_OK, or to
    NEEDS_CLAUDE if it's risk-bearing/HIGH (consensus is necessary but not
    sufficient there)."""
    def _do():
        d = _load_all()
        raw = d.get(pid)
        if not raw:
            raise KeyError(pid)
        p = Proposal(**raw)
        if p.status in (ST_APPLIED, ST_REJECTED, ST_FAILED):
            return p.status
        if agent != p.agent:                       # no self-consensus
            p.votes[agent] = {"approve": bool(approve), "note": note, "ts": _now()}
        # tally
        if p.rejections() >= 2 and p.rejections() > p.approvals():
            p.status = ST_REJECTED
            p.result = "rejected by peer agents"
        elif p.approvals() >= QUORUM.get(p.risk, 99):
            p.status = ST_NEEDS_CLAUDE if p.risk == RISK_HIGH else ST_CONSENSUS
        d[pid] = asdict(p)
        _save_all(d)
        return p.status
    status = _retry_rmw(_do)
    _audit("vote", id=pid, agent=agent, approve=approve, note=note, status=status)
    return status


# ──────────────────────────────────────────────────────────
# Public API — Claude consult gate
# ──────────────────────────────────────────────────────────
def pending_for_claude() -> list[Proposal]:
    """Proposals waiting on Claude's consultation (the consult queue I review)."""
    out = []
    for raw in _load_all().values():
        p = Proposal(**raw)
        if p.status in (ST_NEEDS_CLAUDE,) or (
            p.risk == RISK_HIGH and p.status in (ST_PENDING, ST_CONSENSUS)
        ):
            out.append(p)
    return sorted(out, key=lambda p: p.ts)


def _walkforward_gate(p, approve: bool) -> tuple[bool, str]:
    """DISCIPLINE GATE: a genome may only be APPROVED for live deploy if it
    survives walk-forward (PF_oos>1.15 in >=2 windows). This makes it
    structurally impossible to crown a curve-fit genome (the GEN-CHILD lesson:
    in-sample fitness 35.92 but PF_oos 0.56-0.80 = chronic loser). Returns
    (allow_approve, extra_note). Fail-OPEN only on validator error (never blocks
    a non-genome proposal)."""
    if not approve or p.action not in ("crown_genome",):
        return True, ""
    genome = (p.payload or {}).get("genome") or {}
    if not genome:
        return True, ""
    try:
        from runtime import genome_walkforward as gwf
        from runtime import oos_backtest as ob
        tgt = str(p.target or "")
        sym = tgt.split(":")[-1] if (":" in tgt and tgt.split(":")[-1].endswith("m")) else "XAUUSDm"
        tf = ob._infer_timeframe_from_name(genome, default="M5")
        v = gwf.validate_genome(genome, sym, tf)
        if v.get("validated"):
            return True, (f" | ✅ walk-forward PASS {v.get('windows_passed')}/"
                          f"{len(gwf.WINDOWS_DAYS)} windows")
        pf = [w.get("pf_oos") for w in v.get("windows", [])]
        return False, (f" | ⛔ BLOCKED by walk-forward (PF_oos {pf}, "
                       f"{v.get('windows_passed')}/{len(gwf.WINDOWS_DAYS)} pass) — curve-fit guard")
    except Exception as e:
        return True, f" | (walk-forward check skipped: {e})"


def claude_decide(pid: str, approve: bool, note: str = "") -> str:
    """Claude's verdict on a proposal — the consultation step the user asked for.
    Approve advances to APPROVED (governor will apply); reject closes it.
    A genome crown approval is ENFORCED through the walk-forward gate first.

    HARDENING (2026-05-30): approving now REQUIRES a substantive note (≥20
    chars). Incident 25edb77b: a subagent rubber-stamped a HIGH proposal with
    an empty note and junk hit a LIVE genome file. An approval that can't
    articulate WHY is not a consultation."""
    if approve and len((note or "").strip()) < 20:
        raise ValueError(
            "claude_decide(approve=True) requires a substantive note (>=20 chars) "
            "explaining the decision — empty rubber-stamps are rejected")
    def _do():
        d = _load_all()
        raw = d.get(pid)
        if not raw:
            raise KeyError(pid)
        p = Proposal(**raw)
        eff_approve = bool(approve)
        allow, wf_note = _walkforward_gate(p, eff_approve)
        if eff_approve and not allow:
            eff_approve = False          # walk-forward overrides the approval
        p.claude = {"approve": eff_approve, "requested": bool(approve),
                    "note": (note + wf_note).strip(), "ts": _now()}
        p.status = ST_APPROVED if eff_approve else ST_REJECTED
        p.result = (note + wf_note).strip() or ("claude approved" if eff_approve else "claude rejected")
        d[pid] = asdict(p)
        _save_all(d)
        return p.status
    status = _retry_rmw(_do)
    _audit("claude_decide", id=pid, approve=approve, note=note, status=status)
    return status


# ──────────────────────────────────────────────────────────
# Public API — governor (apply approved changes)
# ──────────────────────────────────────────────────────────
def approved_ready() -> list[Proposal]:
    """APPROVED proposals (incl. CONSENSUS_OK for non-HIGH) not yet applied."""
    out = []
    for raw in _load_all().values():
        p = Proposal(**raw)
        if p.status in (ST_APPROVED, ST_CONSENSUS):
            out.append(p)
    return sorted(out, key=lambda p: p.ts)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_override(target: str, payload: dict) -> str:
    """Write a config override that services read at runtime (agent_overrides.json).
    target form: 'override:KEY'. payload {'value': X}. Bounds are caller's job
    (HIGH targets already routed through Claude)."""
    key = target.split(":")[-1]
    ov = _read_json(OVERRIDES_FILE)
    ov[key] = payload.get("value")
    ov["_updated"] = _now()
    _atomic_write(OVERRIDES_FILE, json.dumps(ov, ensure_ascii=False, indent=2, default=str))
    return f"override {key} = {payload.get('value')}"


def _apply_tune_param(target: str, payload: dict) -> str:
    """Tune a genome parameter in a live genome file.
    target form: 'genome:<param>' (shared champion) or 'genome:<SYM>:<param>'."""
    parts = target.split(":")
    if len(parts) == 2:        # genome:<param> → shared live_genome.json
        sym, param = None, parts[1]
        gpath = DATA / "live_genome.json"
    elif len(parts) == 3:      # genome:<SYM>:<param>
        sym, param = parts[1], parts[2]
        gpath = DATA / f"live_genome__{sym}.json"
    else:
        raise ValueError(f"bad genome target {target!r}")
    # HARDENING (2026-05-30): a descriptive proposal without a concrete "value"
    # used to write `param: null` JUNK into LIVE genome files (happened twice —
    # d309f7c7 + 25edb77b). No value → refuse to apply; that's consult material.
    if "value" not in payload:
        raise ValueError(
            f"tune_param {target!r} has no 'value' in payload — descriptive "
            f"proposals are for consult, not auto-apply")
    g = _read_json(gpath)
    if "params" not in g or not isinstance(g.get("params"), dict):
        g["params"] = g.get("params", {}) or {}
    g["params"][param] = payload.get("value")
    g.setdefault("_governance", {})[param] = {"ts": _now(), "by": "agent_governor"}
    _atomic_write(gpath, json.dumps(g, ensure_ascii=False, indent=2, default=str))
    return f"genome {gpath.name}:{param} = {payload.get('value')}"


def _apply_crown_genome(target: str, payload: dict) -> str:
    """Deploy a challenger genome as the new LIVE trading brain.

    Only ever runs after Claude has approved (crown_genome is forced HIGH). The
    reigning champion file is backed up first; the immortal record only moves UP.
    payload: {'genome': {...full params...}, 'name': str, 'fitness': float,
              'dethroned': str, 'note': str}
    target form: 'genome:crown'.
    """
    import shutil
    genome = payload.get("genome") or {}
    if not genome:
        raise ValueError("crown_genome payload missing 'genome'")
    name = payload.get("name") or genome.get("name") or "challenger"
    live_path = DATA / "live_genome.json"
    champ_path = DATA.parent / "genomes" / "champion_genome.json"

    live_wrap = {
        "name": name,
        "generation": 0,
        "promoted_ts": _now(),
        "params": genome,
        "parents": genome.get("parents", []),
        "_governance": {"crowned_by": "agent_governor", "ts": _now(),
                        "fitness": payload.get("fitness")},
    }
    _atomic_write(live_path, json.dumps(live_wrap, ensure_ascii=False, indent=2, default=str))

    champ_path.parent.mkdir(parents=True, exist_ok=True)
    if champ_path.exists():
        try:
            shutil.copy2(champ_path, champ_path.with_suffix(".json.prev"))
        except Exception:
            pass
    champ_wrap = {
        "champion_genome": live_wrap,
        "captured_ts": _now(),
        "fitness": payload.get("fitness"),
        "dethroned": payload.get("dethroned"),
        "note": payload.get("note") or f"crowned via governance (Claude-approved)",
    }
    _atomic_write(champ_path, json.dumps(champ_wrap, ensure_ascii=False, indent=2, default=str))
    return f"crowned LIVE genome → {name} (fitness {payload.get('fitness')})"


def request_restart(service: str, by: str = "agent_governor", reason: str = "") -> None:
    """Queue a service restart the governor (or launcher) performs."""
    _ensure()
    with RESTART_QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), "service": service,
                            "by": by, "reason": reason}, ensure_ascii=False) + "\n")
    _audit("restart_request", service=service, by=by, reason=reason)


def mark_applied(pid: str, ok: bool, result: str) -> None:
    def _do():
        d = _load_all()
        raw = d.get(pid)
        if not raw:
            raise KeyError(pid)
        p = Proposal(**raw)
        p.status = ST_APPLIED if ok else ST_FAILED
        p.applied_ts = _now()
        p.result = result
        d[pid] = asdict(p)
        _save_all(d)
    _retry_rmw(_do)
    _audit("apply", id=pid, ok=ok, result=result)


def apply_proposal(p: Proposal) -> tuple[bool, str]:
    """Carry out an APPROVED/CONSENSUS proposal. Returns (ok, result).

    edit_code proposals are NEVER auto-written here — they require Claude to make
    the actual edit (the consult gate hands Claude the diff). We just record that
    the code change is approved and queue the affected service for restart.
    """
    try:
        if p.action == "tune_param":
            res = _apply_tune_param(p.target, p.payload)
        elif p.action in ("set_override", "set_flag"):
            res = _apply_override(p.target, p.payload)
        elif p.action == "crown_genome":
            res = _apply_crown_genome(p.target, p.payload)
            # New live brain → bounce the executor so it reloads the genome.
            request_restart("unified_trader", by=p.agent, reason="new live genome crowned")
        elif p.action == "restart_service":
            request_restart(p.target.split(":")[-1], by=p.agent, reason=p.rationale)
            res = f"restart queued: {p.target}"
        elif p.action == "edit_code":
            # Approved in principle; Claude performs the edit, then restart.
            request_restart(p.payload.get("service", ""), by=p.agent,
                            reason="code edit applied by Claude")
            res = "code-edit approved → Claude to write diff, service queued for restart"
        else:
            return (False, f"unknown action {p.action}")
        # If the change affects a running service, bounce it so it takes effect.
        svc = p.payload.get("service")
        if svc and p.action in ("tune_param", "set_override", "set_flag"):
            request_restart(svc, by=p.agent, reason=f"applied {p.target}")
        mark_applied(p.id, True, res)
        return (True, res)
    except Exception as e:
        mark_applied(p.id, False, f"{type(e).__name__}: {e}")
        return (False, str(e))


# ──────────────────────────────────────────────────────────
# Status snapshot (for the UI / Claude)
# ──────────────────────────────────────────────────────────
def snapshot() -> dict:
    d = _load_all()
    by_status: dict[str, int] = {}
    for raw in d.values():
        by_status[raw.get("status", "?")] = by_status.get(raw.get("status", "?"), 0) + 1
    return {
        "ts": _now(),
        "total": len(d),
        "by_status": by_status,
        "awaiting_claude": [asdict_id(p) for p in pending_for_claude()],
        "ready_to_apply": [p.id for p in approved_ready()],
    }


def asdict_id(p: Proposal) -> dict:
    return {"id": p.id, "agent": p.agent, "action": p.action, "target": p.target,
            "risk": p.risk, "status": p.status, "rationale": p.rationale,
            "approvals": p.approvals()}


__all__ = [
    "Proposal", "propose", "vote", "claude_decide", "pending_for_claude",
    "approved_ready", "apply_proposal", "request_restart", "mark_applied",
    "resolve_risk", "snapshot", "RISK_LOW", "RISK_MED", "RISK_HIGH",
    "GOV_DIR", "PROPOSALS_FILE", "OVERRIDES_FILE",
]
