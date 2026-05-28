"""runtime/health_monitor.py — Watches every service for staleness.

Born 2026-05-28 via /design-system Phase 4.

Reads the service registry from runtime.services, checks the
mtime of every IPC file each service is supposed to write,
and prints a color-coded health table every 10s.

CRITICAL services that go stale → red alert + writes to data/alerts.jsonl.

Run in its own terminal:
    python -m runtime.health_monitor

Output example:
  ┌─ HEALTH MONITOR  2026-05-28 04:12:33 ────────────────────┐
  │ CAPTURE                                                  │
  │   ✓ brain_capture            brain_live           1s     │
  │ ANALYSIS                                                 │
  │   ✓ regime_classifier        market_regime        3s     │
  │   ✗ performance_coordinator  engine_performance   STALE  │ ← critical alert
  │ DECISION                                                 │
  │   ✓ trader_orchestrator      active_engines      14s     │
  │ EXECUTION                                                │
  │   ⌛ claude_genome_trader     (heartbeat-only)            │
  └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.services import SERVICES, by_category, Service
from runtime.shared.tokens import PATHS

ALERTS = PATHS["brain_decisions"].parent / "alerts.jsonl"
POLL_S = 10.0


def _file_age_seconds(p: Path) -> float | None:
    if not p.exists(): return None
    try: return time.time() - p.stat().st_mtime
    except Exception: return None


def _status_for(svc: Service) -> tuple[str, str]:
    """Return (icon, description). Icons: ✓ ✗ ⌛"""
    if not svc.writes:
        return ("⌛", "(no state file — heartbeat-only)")
    ages: list[tuple[str, float | None]] = []
    for key in svc.writes:
        p = PATHS.get(key)
        if p is None:
            ages.append((key, None)); continue
        ages.append((key, _file_age_seconds(p)))

    # any file missing or stale?
    worst: str | None = None
    worst_age: float = -1
    any_alive = False
    for key, age in ages:
        if age is None:
            worst = f"{key} MISSING"
            continue
        if age > svc.stale_after_s:
            if age > worst_age:
                worst = f"{key} STALE {int(age)}s"
                worst_age = age
        else:
            any_alive = True
    if worst:
        return ("✗", worst)
    # all healthy — report youngest
    youngest = min((a for _, a in ages if a is not None), default=None)
    if youngest is None:
        return ("✗", "unknown")
    return ("✓", f"{int(youngest)}s")


def _alert(svc: Service, status: str) -> None:
    """Persist a critical alert when something breaks."""
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": svc.name,
            "category": svc.category,
            "status": status,
            "critical": svc.critical,
            "description": svc.description,
        }, ensure_ascii=False) + "\n")


def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def render():
    cats = by_category()
    width = 60
    _clear()
    print("┌─ HEALTH MONITOR " + f"{datetime.now():%Y-%m-%d %H:%M:%S}".ljust(width - 17) + "─┐")

    last_alerts: list[tuple[Service, str]] = []
    for cat in ["CAPTURE", "ANALYSIS", "DECISION", "EXECUTION", "EVOLUTION", "INFRASTRUCTURE"]:
        services = cats.get(cat, [])
        if not services: continue
        print(f"│ {cat}".ljust(width + 1) + " │")
        for svc in services:
            icon, status = _status_for(svc)
            crit = "!" if svc.critical else " "
            line = f"  {icon}{crit} {svc.name:26s}  {status[:24]:24s}"
            print(f"│ {line:{width}s} │")
            if icon == "✗" and svc.critical:
                last_alerts.append((svc, status))

    print("└" + "─" * (width + 2) + "┘")
    if last_alerts:
        print(f"\n🚨 {len(last_alerts)} CRITICAL service(s) down:")
        for svc, status in last_alerts:
            print(f"  • {svc.name}: {status}")
            _alert(svc, status)
    print(f"\n  Refresh {POLL_S}s · Ctrl+C to exit")


def main():
    print("[health_monitor] starting...")
    time.sleep(1)
    while True:
        try:
            render()
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            print("\n[health_monitor] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(POLL_S)


if __name__ == "__main__":
    main()
