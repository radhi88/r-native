"""r_native/v2_stack.py — Launch & supervise the unified v2 trading stack.

Born 2026-05-28: "الحل 3 — جعل R Native نفسه يطلق كل شي".

When R Native (app.py) boots, it calls start_all() here, which spawns
the 8 unified-stack processes as detached subprocesses. The user just
opens R Native — the whole trading brain comes up automatically.

DESIGN:
  • dedup-safe — never spawns a service that's already running
    (checks running python.exe command lines via psutil)
  • silent — each service logs to data/logs/<service>.log (CREATE_NO_WINDOW)
  • crash-tolerant — a service that fails to spawn doesn't block the others
  • clean shutdown — stop_all() terminates only what we own

The 8 services (run from r_native_v2/ so `python -m runtime.X` resolves):
  brain_v1, regime_classifier, trader_orchestrator, genome_promoter,
  genome_evolver, unified_trader, trailing_stop_manager,
  decision_outcome_filler
"""
from __future__ import annotations
import subprocess
import sys
import os
from pathlib import Path

# The v2 runtime lives in the sibling r_native_v2 (data paths are absolute there).
R_NATIVE_V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2")
MT5_ROOT    = Path(r"C:\Users\Radhi\MT5")
LOG_DIR = R_NATIVE_V2 / "data" / "logs"

# Order matters: producers before consumers.
SERVICES = [
    "brain_v1",                 # market snapshot
    "regime_classifier",        # TREND/CHOP
    "trader_orchestrator",      # regime gate
    "genome_promoter",          # promote best gene
    "genome_evolver",           # breed genes
    "r_native_brain_link",      # feed: writes genome_signals.jsonl (council eats this)
    # "unified_trader",         # ⛔ STOPPED 2026-05-29 by user ("أوقف الولد كله") —
    #                             gold genome was buying against TREND_DOWN → losses.
    #                             Re-enable ONLY after the strategy review.
    "palace_council",           # 5-expert vote → enters its own approved trades (99779)
    "trailing_stop_manager",    # SL trail
    "decision_outcome_filler",  # PnL backfill
    "trade_sync",               # MT5 history → db (manual trades feed learning)
    "champion_evolution",       # our son keeps getting smarter (re-breed + crown)
    "genome_academy",           # evolution lab: breed+gauntlet+panel+multi-symbol
]

# The LLM brain (FRIDAY) is a standalone script at MT5 root, not a runtime
# module — it gets its own launch entry. `--live` makes it place real orders;
# its own kill_switch.txt + friday_config caps (MAX_LOT, MAX_OPEN) still apply.
LLM_BRAIN = {
    "name": "friday_brain",
    "cmd":  [sys.executable, "friday_brain.py", "--live"],
    "cwd":  str(MT5_ROOT),
    "match": "friday_brain.py",   # dedupe token in cmdline
}

_spawned: dict[str, int] = {}   # service -> pid we started


def _running_modules() -> set[str]:
    """Return the set of runtime.<module> names currently running."""
    running: set[str] = set()
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if not p.info["name"] or "python" not in p.info["name"].lower():
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                for svc in SERVICES:
                    if f"runtime.{svc}" in cmd:
                        running.add(svc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return running


def start_all() -> dict:
    """Spawn any of the 8 services that aren't already running.

    Returns {"started": [...], "already_running": [...], "failed": [...]}.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 🛡️ Restore our son BEFORE spawning evolver/promoter (so the GA can't
    # touch the pool before the champion is re-seeded).
    try:
        import sys as _sys
        _sys.path.insert(0, str(R_NATIVE_V2))
        from runtime.champion_seeder import seed as _seed
        _r = _seed()
        print(f"[v2_stack] champion: {_r.get('champion')} — {_r.get('actions')}", flush=True)
    except Exception as _e:
        print(f"[v2_stack] champion seed skipped: {_e}", flush=True)

    already = _running_modules()

    started, skipped, failed = [], [], []
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW — silent background, no console popups
        creationflags = 0x08000000

    for svc in SERVICES:
        if svc in already:
            skipped.append(svc)
            continue
        try:
            logf = open(LOG_DIR / f"{svc}.log", "a", encoding="utf-8")
            p = subprocess.Popen(
                [sys.executable, "-m", f"runtime.{svc}"],
                cwd=str(R_NATIVE_V2),
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=True,
            )
            _spawned[svc] = p.pid
            started.append(svc)
        except Exception as e:
            failed.append((svc, str(e)))

    # ── LLM brain (FRIDAY) — standalone script, separate launch ──────────────
    try:
        if _llm_brain_running():
            skipped.append(LLM_BRAIN["name"])
        else:
            logf = open(LOG_DIR / f"{LLM_BRAIN['name']}.log", "a", encoding="utf-8")
            p = subprocess.Popen(
                LLM_BRAIN["cmd"], cwd=LLM_BRAIN["cwd"],
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=creationflags, close_fds=True,
            )
            _spawned[LLM_BRAIN["name"]] = p.pid
            started.append(LLM_BRAIN["name"])
    except Exception as e:
        failed.append((LLM_BRAIN["name"], str(e)))

    return {"started": started, "already_running": skipped, "failed": failed}


def _llm_brain_running() -> bool:
    """True if the FRIDAY LLM brain script is already running."""
    try:
        import psutil
        token = LLM_BRAIN["match"]
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if not p.info["name"] or "python" not in p.info["name"].lower():
                    continue
                if token in " ".join(p.info["cmdline"] or []):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def stop_all() -> int:
    """Terminate every running v2 service (ours + any leaked copies). Returns count."""
    killed = 0
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if not p.info["name"] or "python" not in p.info["name"].lower():
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                if any(f"runtime.{svc}" in cmd for svc in SERVICES) \
                        or LLM_BRAIN["match"] in cmd:
                    p.terminate()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    _spawned.clear()
    return killed


def status() -> dict:
    """Which services are alive right now (incl. the LLM brain)."""
    running = _running_modules()
    out = {svc: (svc in running) for svc in SERVICES}
    out[LLM_BRAIN["name"]] = _llm_brain_running()
    return out


def summary_line() -> str:
    s = status()
    up = sum(1 for v in s.values() if v)
    return f"v2 stack: {up}/{len(s)} services up"


__all__ = ["start_all", "stop_all", "status", "summary_line", "SERVICES"]
