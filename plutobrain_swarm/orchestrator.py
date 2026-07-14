"""
PlutoBrain Swarm — Orchestrator_Prime
=====================================
The never-sleeps loop. Honest implementation of the MEGA AGENT SWARM spec.

Each cycle (default 30s):
  1. Check cluster health (which workers errored)
  2. Dispatch every DUE deterministic worker
  3. Write per-agent status beacons      -> swarm_state/agent_status.json
  4. Update allocation map                -> swarm_state/agent_allocation_map.json
  5. Append a cycle record                -> swarm_state/orchestrator_log.json
  6. Raise alerts on real findings        -> swarm_state/alerts.json
  7. Promote "mission complete" clusters to the Active Pool

ESCALATE agents (judgment roles) are listed but not auto-run — their pending
questions land in swarm_state/escalations.json for the human / friday_decision.py.

Run:
    python -m plutobrain_swarm.orchestrator            # continuous
    python -m plutobrain_swarm.orchestrator --once     # single cycle (CI/cron)
    python -m plutobrain_swarm.orchestrator --cycles 5 # N cycles then stop
"""
from __future__ import annotations
import argparse
import json
import signal
import time
from pathlib import Path

from . import registry
from .registry import ESCALATE
from .workers import Context, WORKERS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                       # C:\Users\Radhi\MT5
STATE = HERE / "swarm_state"
ARTIFACTS = STATE / "artifacts"
STATE.mkdir(exist_ok=True)
ARTIFACTS.mkdir(exist_ok=True)

CYCLE_SECONDS = 30
_STOP = False


def _sig(*_):
    global _STOP
    _STOP = True
    print("\n[orchestrator] stop requested — finishing cycle…")


def _write(name: str, data) -> None:
    (STATE / name).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _due(agent, now: float) -> bool:
    if agent.worker == ESCALATE or agent.cluster == "ORCH":
        return False
    return (now - agent.last_run) >= agent.interval_sec


class Orchestrator:
    def __init__(self):
        self.agents = registry.roster()
        self.ctx = Context(root=ROOT, artifacts=ARTIFACTS)
        self.cycle = 0
        self.started = time.time()
        self.alerts: list[dict] = []
        self.mode = "run"          # run | pause | emergency (set via control.json)
        self._last_report_day = None

    # -- human interface: read control.json each cycle ---------------------
    def _read_control(self):
        ctl = STATE / "control.json"
        try:
            data = json.loads(ctl.read_text(encoding="utf-8"))
        except Exception:
            return
        mode = str(data.get("mode", "run")).lower()
        if mode in ("run", "pause", "emergency"):
            self.mode = mode
        # /reallocate {agent_id: cluster}
        for aid, cluster in (data.get("reallocate") or {}).items():
            for a in self.agents:
                if a.id == aid and a.cluster != "ORCH":
                    a.cluster = cluster.upper()
                    a.pool = "cluster"

    # -- one pass over the roster ------------------------------------------
    def run_cycle(self) -> dict:
        self.cycle += 1
        now = time.time()
        self._read_control()
        ran, errored, findings_total = 0, 0, 0

        for a in self.agents:
            if self.mode == "pause":
                break                                   # /pause — dispatch nothing
            if self.mode == "emergency" and a.cluster != "GAMMA":
                continue                                # /emergency — validation only
            if not _due(a, now):
                continue
            fn = WORKERS.get(a.worker)
            if fn is None:
                continue
            a.last_status = "running"
            try:
                res = fn(self.ctx)
                a.last_status = "ok"
                a.last_summary = res.get("summary", "")
                a.last_run = time.time()
                f = int(res.get("findings", 0))
                findings_total += f
                ran += 1
                # alert on the findings that actually matter
                self._maybe_alert(a, res)
            except Exception as e:
                a.last_status = "error"
                a.last_summary = f"{type(e).__name__}: {e}"
                a.last_run = time.time()
                errored += 1

        self._promote_clusters()
        self._flush_state(now, ran, errored, findings_total)
        return {"cycle": self.cycle, "ran": ran, "errored": errored, "findings": findings_total}

    # -- raise alerts on high-signal findings ------------------------------
    def _maybe_alert(self, a, res: dict):
        f = int(res.get("findings", 0))
        critical = {
            "magic_manager": ("collision", 1),       # any magic collision = real bug
            "compiler_guard": ("unbalanced", 1),      # syntax breakage
            "dependency_tracker": ("unresolved include", 1),
        }
        if a.worker in critical and f >= critical[a.worker][1]:
            # dedupe: one open alert per agent (a standing condition, not one-per-cycle).
            # drop any prior alert from this agent, keep only the latest.
            self.alerts = [x for x in self.alerts if x.get("agent") != a.id]
            self.alerts.append({"ts": time.time(), "agent": a.id, "role": a.role,
                                "severity": "high", "summary": a.last_summary,
                                "artifact": res.get("artifact", ""),
                                "since_cycle": self.cycle})

    # -- mission-complete promotion to Active Pool -------------------------
    def _promote_clusters(self):
        for cluster in ("ALPHA", "BETA", "GAMMA"):
            members = [a for a in self.agents if a.cluster == cluster and a.worker != ESCALATE]
            if members and all(a.last_status == "ok" for a in members):
                for a in members:
                    a.pool = "active_pool"

    # -- persist all the shared-state files --------------------------------
    def _flush_state(self, now, ran, errored, findings_total):
        # agent_status.json — the status beacon for every agent
        beacons = [{
            "id": a.id, "role": a.role, "cluster": a.cluster, "pool": a.pool,
            "worker": a.worker, "status": a.last_status,
            "summary": a.last_summary, "last_run": a.last_run,
        } for a in self.agents]
        _write("agent_status.json", {"generated": now, "cycle": self.cycle, "agents": beacons})

        # agent_allocation_map.json — who's where
        alloc = {"cluster": {}, "active_pool": [], "escalate": []}
        for a in self.agents:
            if a.worker == ESCALATE:
                alloc["escalate"].append(a.id)
            elif a.pool == "active_pool":
                alloc["active_pool"].append(a.id)
            else:
                alloc["cluster"].setdefault(a.cluster, []).append(a.id)
        _write("agent_allocation_map.json", {"generated": now, **alloc})

        # escalations.json — judgment roles awaiting human/LLM
        esc = [{"id": a.id, "role": a.role, "cluster": a.cluster, "skills": a.skills}
               for a in self.agents if a.worker == ESCALATE]
        _write("escalations.json", {"generated": now,
               "note": "These roles need judgment. Run `python -m plutobrain_swarm.orchestrator --escalate ID` "
                       "or ask Claude / friday_decision.py.", "pending": esc})

        # alerts.json — keep last 100
        _write("alerts.json", {"generated": now, "alerts": self.alerts[-100:]})

        # orchestrator_log.json — append cycle summary (keep last 500)
        log_path = STATE / "orchestrator_log.json"
        try:
            log = json.loads(log_path.read_text(encoding="utf-8")).get("cycles", [])
        except Exception:
            log = []
        active = sum(1 for a in self.agents if a.pool == "active_pool")
        log.append({"cycle": self.cycle, "ts": now, "ran": ran, "errored": errored,
                    "findings": findings_total, "active_pool": active, "mode": self.mode,
                    "uptime_s": round(now - self.started, 1)})
        _write("orchestrator_log.json", {"generated": now, "cycles": log[-500:]})

        # shared_context.json — consolidated snapshot all agents/consumers read
        by_cluster = {}
        for a in self.agents:
            by_cluster.setdefault(a.cluster, {"total": 0, "ok": 0, "active_pool": 0})
            by_cluster[a.cluster]["total"] += 1
            if a.last_status == "ok":
                by_cluster[a.cluster]["ok"] += 1
            if a.pool == "active_pool":
                by_cluster[a.cluster]["active_pool"] += 1
        _write("shared_context.json", {
            "generated": now, "cycle": self.cycle, "mode": self.mode,
            "uptime_min": round((now - self.started) / 60, 1),
            "agents_total": len(self.agents), "active_pool": active,
            "clusters": by_cluster, "open_alerts": len(self.alerts),
            "latest_findings": findings_total,
            "kpis": self._kpis()})

        # daily_report.md — once per calendar day
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self._last_report_day:
            self._last_report_day = day
            self._write_daily_report(day, now, active)

    def _kpis(self) -> dict:
        """Live KPI scoreboard pulled from worker artifacts (spec success metrics)."""
        def art(name):
            try:
                return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))
            except Exception:
                return {}
        magics = art("magic_map.json")
        syntax = art("syntax_balance.json")
        dups = art("duplicates.json")
        ver = art("version_clusters.json")
        classified = ver.get("classified", {})
        return {
            "magic_collisions": len(magics.get("collisions", {})),
            "unbalanced_files": len(syntax.get("unbalanced", [])),
            "duplicate_bodies": len(dups.get("duplicate_bodies", [])),
            "duplicate_names": len(dups.get("duplicate_names", {})),
            "ea_families_multi_version": len(ver.get("clusters", {})),
            "ea_consolidatable": ver.get("actionable", 0),
            "ea_divergent": sum(1 for v in classified.values() if v.get("kind") == "divergent"),
        }

    def _write_daily_report(self, day, now, active):
        k = self._kpis()
        lines = [
            f"# PlutoBrain Swarm — Daily Report {day}", "",
            f"- Cycle: {self.cycle} · uptime {round((now - self.started)/60,1)} min · mode `{self.mode}`",
            f"- Agents: {len(self.agents)} · active pool: {active} · open alerts: {len(self.alerts)}",
            "", "## KPI scoreboard (spec success metrics)",
            f"- Magic-number collisions: **{k['magic_collisions']}** (target 0)",
            f"- Files with unbalanced braces/parens: **{k['unbalanced_files']}** (target 0)",
            f"- Duplicate function names: **{k['duplicate_names']}** (target 0)",
            f"- EA families with multiple versions: **{k['ea_families_multi_version']}**",
            "", "## Open alerts",
        ]
        for a in self.alerts[-15:]:
            lines.append(f"- [{a.get('agent')}] {a.get('role')}: {a.get('summary')}")
        (STATE / "daily_report.md").write_text("\n".join(lines), encoding="utf-8")

    # -- main loop ----------------------------------------------------------
    def serve(self, max_cycles: int | None = None):
        det = registry.deterministic_count()
        esc = registry.escalate_count()
        print(f"[orchestrator] PlutoBrain Swarm online — root={ROOT}")
        print(f"[orchestrator] roster: {det} deterministic workers + {esc} ESCALATE roles "
              f"({det + esc + 1} agents incl. Orchestrator_Prime)")
        print(f"[orchestrator] cycle={CYCLE_SECONDS}s · state={STATE}")
        while not _STOP:
            t0 = time.time()
            r = self.run_cycle()
            print(f"[cycle {r['cycle']:>4}] ran={r['ran']:>2} err={r['errored']} "
                  f"findings={r['findings']:>4} alerts={len(self.alerts)}")
            if max_cycles and self.cycle >= max_cycles:
                break
            if _STOP:
                break
            time.sleep(max(0.0, CYCLE_SECONDS - (time.time() - t0)))
        print(f"[orchestrator] stopped after {self.cycle} cycles. "
              f"Artifacts in {ARTIFACTS}")


def main():
    global CYCLE_SECONDS
    ap = argparse.ArgumentParser(description="PlutoBrain Swarm orchestrator")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--cycles", type=int, default=None, help="run N cycles then stop")
    ap.add_argument("--interval", type=int, default=CYCLE_SECONDS, help="seconds per cycle")
    args = ap.parse_args()

    CYCLE_SECONDS = args.interval
    signal.signal(signal.SIGINT, _sig)
    try:
        signal.signal(signal.SIGTERM, _sig)
    except Exception:
        pass

    orch = Orchestrator()
    if args.once:
        r = orch.run_cycle()
        print(f"[once] ran={r['ran']} errored={r['errored']} findings={r['findings']}")
    else:
        orch.serve(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
