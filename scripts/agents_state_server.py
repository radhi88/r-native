"""agents_state_server.py — Updates agents_state.json every 5 s from live data."""
from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE_STATE = ROOT / "data" / "qader" / "qader_live_state.json"
AGENTS_STATE = ROOT / "dashboard" / "agents_state.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _patch_agents_state(live: dict) -> None:
    state = _read_json(AGENTS_STATE)
    if not state:
        return

    cycle = int(live.get("cycle_count") or 0)
    trades = int(live.get("demo_trades_opened") or 0)
    signal = str(live.get("last_signal") or "HOLD")
    conf = float(live.get("last_confidence") or 0.0)
    exec_status = str(live.get("execution_status") or "idle")
    allow = bool(live.get("allow_new_entries", True))

    # Derive per-agent activity from live data
    activity_map = {
        "QaderLoop":       min(100, cycle % 100),
        "FractalAgent":    min(100, cycle % 100) if signal != "HOLD" else 20,
        "SmcAgent":        min(100, cycle % 100) if signal != "HOLD" else 20,
        "IctSweepAgent":   min(100, cycle % 100) if signal != "HOLD" else 15,
        "SignalArbiter":   int(conf * 100),
        "RiskManager":     80 if allow else 30,
        "ExecutionManager": 90 if exec_status == "executed" else 20,
        "PositionManager": 70 if trades > 0 else 10,
        "LearningService": min(100, trades * 20),
        "DnaFeedback":     50,
        "EventBus":        min(100, cycle % 50 * 2),
    }

    for agent in state.get("agents", []):
        name = agent.get("name", "")
        if name in activity_map:
            agent["activity"] = activity_map[name]
            agent["status"] = "active" if activity_map[name] > 20 else "idle"

    # Update global stats
    state["meta"] = {
        "cycle": cycle,
        "trades": trades,
        "signal": signal,
        "confidence": round(conf, 4),
        "exec_status": exec_status,
        "allow_new_entries": allow,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    AGENTS_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    print(f"[AgentsServer] Watching {LIVE_STATE}")
    print(f"[AgentsServer] Updating {AGENTS_STATE}")
    while True:
        try:
            live = _read_json(LIVE_STATE)
            _patch_agents_state(live)
        except Exception as exc:
            print(f"[AgentsServer] Error: {exc}")
        time.sleep(5)


if __name__ == "__main__":
    main()
