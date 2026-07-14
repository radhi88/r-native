"""
PlutoBrain Swarm — Human Interface (the spec's command console)
===============================================================
Writes control.json (the orchestrator reads it every cycle) and reads the
live status beacons. No restart needed — commands take effect within one cycle.

    python -m plutobrain_swarm.swarm_ctl status
    python -m plutobrain_swarm.swarm_ctl pause
    python -m plutobrain_swarm.swarm_ctl resume
    python -m plutobrain_swarm.swarm_ctl emergency          # all validation (GAMMA only)
    python -m plutobrain_swarm.swarm_ctl reallocate A-05 BETA
    python -m plutobrain_swarm.swarm_ctl report             # print today's daily report
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

STATE = Path(__file__).resolve().parent / "swarm_state"
CONTROL = STATE / "control.json"


def _load(name, d=None):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except Exception:
        return d


def _set_mode(mode: str):
    ctl = _load("control.json", {}) or {}
    ctl["mode"] = mode
    ctl["updated"] = time.time()
    CONTROL.write_text(json.dumps(ctl, indent=2), encoding="utf-8")
    print(f"[ctl] mode -> {mode} (takes effect next cycle)")


def cmd_status():
    st = _load("agent_status.json", {}) or {}
    sc = _load("shared_context.json", {}) or {}
    agents = st.get("agents", [])
    if not agents:
        print("[ctl] no status yet — is the orchestrator running?")
        return
    print(f"=== PlutoBrain Swarm — cycle {st.get('cycle','?')} · mode {sc.get('mode','run')} "
          f"· uptime {sc.get('uptime_min','?')}min ===")
    for cl, c in (sc.get("clusters") or {}).items():
        print(f"  {cl:6} {c['ok']:>2}/{c['total']:>2} ok · active_pool {c['active_pool']}")
    k = sc.get("kpis", {})
    if k:
        print(f"  KPIs: collisions={k.get('magic_collisions')} unbalanced={k.get('unbalanced_files')} "
              f"dup_names={k.get('duplicate_names')} ea_versions={k.get('ea_families_multi_version')}")
    al = _load("alerts.json", {}) or {}
    for a in (al.get("alerts") or [])[-5:]:
        print(f"  ⚠ [{a['agent']}] {a['summary']}")


def cmd_reallocate(agent_id: str, cluster: str):
    ctl = _load("control.json", {}) or {}
    ctl.setdefault("reallocate", {})[agent_id] = cluster.upper()
    ctl["updated"] = time.time()
    CONTROL.write_text(json.dumps(ctl, indent=2), encoding="utf-8")
    print(f"[ctl] reallocate {agent_id} -> {cluster.upper()} (next cycle)")


def cmd_report():
    p = STATE / "daily_report.md"
    print(p.read_text(encoding="utf-8") if p.exists() else "[ctl] no daily report yet")


def main():
    args = sys.argv[1:]
    cmd = (args[0] if args else "status").lower()
    if cmd == "status":
        cmd_status()
    elif cmd == "pause":
        _set_mode("pause")
    elif cmd == "resume":
        _set_mode("run")
    elif cmd == "emergency":
        _set_mode("emergency")
    elif cmd == "reallocate" and len(args) == 3:
        cmd_reallocate(args[1], args[2])
    elif cmd == "report":
        cmd_report()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
