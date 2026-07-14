"""runtime/supervisor.py — Professional process supervisor.

Born 2026-05-28: "اربط الدنيا ببعض ... وتسلسلها وتبعياتها".

Reads system_manifest.launch_order() (dependency-sorted) and:
  1. LAUNCH  — starts each v2 service in dependency order (skip already-running)
  2. MONITOR — every CHECK_S, verifies each is alive (process + file-freshness)
  3. HEAL    — auto-restarts CRITICAL services that died or went stale
  4. REPORT  — writes data/supervisor_status.json for the UI

Dedup-safe (psutil cmdline scan, matches python.exe AND pythonw.exe).
Never launches: shared_libs, rnative_agents, the supervisor itself.

Run:
  python -m runtime.supervisor              # supervise forever
  python -m runtime.supervisor --once       # launch + one health pass, exit
  python -m runtime.supervisor --status     # print status, exit
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.system_manifest import launch_order, all_components, Component
from runtime.shared.tokens import PATHS

ROOT = PATHS["brain_live"].parent.parent          # r_native_v2/
LOG_DIR = PATHS["brain_decisions"].parent / "logs"
STATUS_FILE = PATHS["brain_decisions"].parent / "supervisor_status.json"
CHECK_S = 20.0
RESTART_GRACE_S = 30.0          # don't restart a service within 30s of launching it


def _running_modules() -> set[str]:
    out: set[str] = set()
    try:
        import psutil
        svc_modules = {c.module: c.id for c in launch_order()}
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                nm = (p.info["name"] or "").lower()
                if "python" not in nm:
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                for mod, cid in svc_modules.items():
                    if mod and mod in cmd:
                        out.add(cid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return out


def _fresh(c: Component) -> bool | None:
    """True/False if component writes files (freshness check), None if not checkable."""
    if not c.writes:
        return None
    # stale_after = max(cadence*3, 60s); event-driven (cadence 0) → skip
    if c.cadence_s <= 0:
        return None
    lim = max(c.cadence_s * 3, 60)
    for key in c.writes:
        p = PATHS.get(key)
        if p is None or not p.exists():
            continue
        age = time.time() - p.stat().st_mtime
        if age < lim:
            return True
    return False


def _spawn(c: Component) -> int | None:
    if not c.module:
        return None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
    logf = open(LOG_DIR / f"{c.id}.log", "a", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", c.module], cwd=str(ROOT),
        stdout=logf, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True,
    )
    return p.pid


def launch_all() -> dict:
    """Launch every not-running v2 service in dependency order."""
    # champion seeder first (boot guard)
    try:
        from runtime.champion_seeder import seed
        seed()
    except Exception:
        pass

    running = _running_modules()
    started, skipped = [], []
    launched_at: dict[str, float] = {}
    for c in launch_order():
        if c.id == "supervisor":          # never spawn self
            continue
        if c.id in running:
            skipped.append(c.id); continue
        try:
            _spawn(c); started.append(c.id); launched_at[c.id] = time.time()
            time.sleep(0.6)               # let producers come up before consumers
        except Exception as e:
            print(f"[supervisor] failed to launch {c.id}: {e}", flush=True)
    return {"started": started, "skipped": skipped, "launched_at": launched_at}


def health_pass(launched_at: dict[str, float]) -> dict:
    """Check every service; restart CRITICAL ones that are down/stale."""
    running = _running_modules()
    report, restarted = {}, []
    for c in launch_order():
        if c.id == "supervisor":
            continue
        alive = c.id in running
        fresh = _fresh(c)
        ok = alive and (fresh is not False)
        report[c.id] = {"alive": alive, "fresh": fresh, "crit": c.crit}
        # Heal CRITICAL that died (respect grace period after launch)
        if not alive and c.crit == "CRITICAL":
            since = time.time() - launched_at.get(c.id, 0)
            if since > RESTART_GRACE_S:
                try:
                    _spawn(c); launched_at[c.id] = time.time(); restarted.append(c.id)
                    print(f"[supervisor] 🔧 restarted CRITICAL {c.id}", flush=True)
                except Exception as e:
                    print(f"[supervisor] restart {c.id} failed: {e}", flush=True)
    up = sum(1 for v in report.values() if v["alive"])
    total = len(report)
    status = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "up": up, "total": total, "restarted": restarted, "report": report,
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        if STATUS_FILE.exists():
            s = json.loads(STATUS_FILE.read_text())
            print(f"supervisor: {s['up']}/{s['total']} up · {s['ts']}")
            for cid, r in s["report"].items():
                mk = "🟢" if r["alive"] else "🔴"
                fr = "" if r["fresh"] is None else (" fresh" if r["fresh"] else " STALE")
                print(f"  {mk} {cid:24s} {r['crit']}{fr}")
        else:
            print("no supervisor status yet")
        return

    print("═══ 🎛️ SUPERVISOR — professional process orchestration ═══")
    r = launch_all()
    print(f"  launched: {r['started']}")
    print(f"  already up: {len(r['skipped'])}")
    launched_at = r["launched_at"]

    if args.once:
        s = health_pass(launched_at)
        print(f"  health: {s['up']}/{s['total']} up")
        return

    print(f"  monitoring every {CHECK_S}s — Ctrl+C to stop supervising")
    while True:
        try:
            time.sleep(CHECK_S)
            s = health_pass(launched_at)
            if s["restarted"]:
                print(f"[{datetime.now():%H:%M:%S}] restarted {s['restarted']} · {s['up']}/{s['total']} up")
        except KeyboardInterrupt:
            print("\n[supervisor] stopped supervising (services keep running)"); break
        except Exception as e:
            print(f"[supervisor] err: {e}"); time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
