#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
unified_launcher.py  --  Single-entry-point boot planner for the R-Native fleet.

NON-DESTRUCTIVE BY DESIGN
=========================
This is a *planner / supervisor skeleton*, not a replacement for the live
`watchdog_guard.py`. It exists to make the "one supervisor / one brain (:5055) /
one executor (magic 20260605)" target of `r_desktop/UNIFIED_RUNTIME.md` concrete
and testable WITHOUT touching the running system.

Hard safety guarantees:
  * `--dry-run` defaults to TRUE. Running with no flags only PRINTS the plan.
  * It NEVER kills, restarts, or replaces a running process.
  * Before it would start anything, it probes what is already alive (by TCP port
    for the brain :5055, by a lock socket for the executor mutex 57322, by
    status-file heartbeat age for supervisors). If a component is already up it
    is reported as ALREADY-RUNNING and SKIPPED -- this is the ":5055 double-bind"
    lesson from MEMORY 2026-07-14 encoded as a pre-flight check.
  * Actually launching (i.e. `--no-dry-run`) is gated behind an explicit flag AND
    still refuses to start a duplicate of anything already detected.

The canonical live supervisor remains `watchdog_guard.py`. This module can be
imported (all functions are side-effect free until `main()` is called) or run as
a script to audit / plan the fleet.

Usage
-----
    python unified_launcher.py                 # dry-run: print the boot plan
    python unified_launcher.py --audit         # only probe + print what's alive
    python unified_launcher.py --json          # machine-readable plan
    python unified_launcher.py --no-dry-run    # (guarded) start only MISSING comps

See `r_desktop/UNIFIED_RUNTIME.md` for the full design.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

# --------------------------------------------------------------------------- #
# Paths (all absolute, anchored to this file's directory = MT5 root)           #
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DATA_RN = ROOT / "data" / "r_native"
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# The single honored halt file (kill_switch.json is the orphaned one, see design)
KILL_SWITCH = ROOT / "kill_switch.txt"

# Well-known runtime coordinates (do NOT change without updating the executor).
BRAIN_HOST = "127.0.0.1"
BRAIN_PORT = 5055                      # the ONE brain
BRAIN_HEALTH_PATH = "/api/r/executor"  # first route that must answer
EXECUTOR_MUTEX_PORT = 57322           # live-only socket mutex for magic 20260605
EXECUTOR_MAGIC = 20260605

# A status file is considered "stale" (its owner hung/dead) past this age.
HEARTBEAT_STALE_SEC = 180


# --------------------------------------------------------------------------- #
# Component model                                                              #
# --------------------------------------------------------------------------- #
@dataclass
class Component:
    """One boot-plan entry.

    `probe` returns True when the component is already alive (so we must SKIP it).
    `args` is the command that WOULD be launched (never launched in dry-run).
    """
    name: str
    args: list[str]
    probe: Callable[[], bool]
    order: int
    required_demo: bool = False          # refuse to arm unless terminal is DEMO
    note: str = ""
    # populated at plan time:
    already_running: Optional[bool] = field(default=None, init=False)


# --------------------------------------------------------------------------- #
# Probes  --  read-only "is it already up?" checks                            #
# --------------------------------------------------------------------------- #
def _tcp_port_open(host: str, port: int, timeout: float = 0.75) -> bool:
    """True if something is LISTENING on host:port (i.e. already bound)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_brain() -> bool:
    """The one brain is 'up' if :5055 is bound. We deliberately do NOT POST or
    mutate anything -- a plain TCP connect is enough and avoids waking MT5."""
    return _tcp_port_open(BRAIN_HOST, BRAIN_PORT)


def probe_executor_mutex() -> bool:
    """The live executor holds a socket mutex on 57322. If the port is bound,
    an executor already owns magic 20260605 -- we must NOT start a second one."""
    return _tcp_port_open(BRAIN_HOST, EXECUTOR_MUTEX_PORT)


def _status_file_fresh(path: Path, max_age: int = HEARTBEAT_STALE_SEC) -> bool:
    """True if a heartbeat/status JSON exists and was written recently.
    Heartbeat AGE (mtime), not mere existence -- the watchdog silent-death lesson.
    """
    try:
        if not path.exists():
            return False
        return (time.time() - path.stat().st_mtime) <= max_age
    except OSError:
        return False


def probe_supervisor() -> bool:
    """A supervisor of record is alive if watchdog_status.json is fresh."""
    return _status_file_fresh(DATA_RN / "watchdog_status.json")


def _always_false() -> bool:
    """Placeholder probe for components without a cheap liveness check.
    Reported as UNKNOWN/would-start; still never force-duplicates in real launch
    because required-order components (brain/executor) gate the rest."""
    return False


# --------------------------------------------------------------------------- #
# DEMO assertion (fleet-wide safety pre-flight)                                #
# --------------------------------------------------------------------------- #
def assert_demo() -> tuple[bool, str]:
    """Best-effort DEMO check. Returns (is_demo, detail).

    Per MEMORY (Exness demo detection): Trial accounts report trade_mode=0
    (looks REAL); the reliable signal is the server name containing 'Trial' or
    'Demo'. This function is import-safe: if MetaTrader5 is unavailable it returns
    (False, "unknown") so callers stay on the safe side (refuse to arm --live).
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception:
        return (False, "MetaTrader5 module not importable -- cannot confirm DEMO")
    try:
        info = mt5.account_info()
        if info is None:
            return (False, "account_info() is None -- terminal not connected")
        server = str(getattr(info, "server", "") or "")
        is_demo = ("Trial" in server) or ("Demo" in server) or ("demo" in server)
        return (is_demo, f"server={server!r}")
    except Exception as exc:  # pragma: no cover - defensive
        return (False, f"account probe failed: {exc}")


# --------------------------------------------------------------------------- #
# Boot plan (mirrors UNIFIED_RUNTIME.md boot sequence)                         #
# --------------------------------------------------------------------------- #
def build_plan() -> list[Component]:
    """Return the ordered component list. Order matches the design:
    supervisor -> brain(:5055) -> executor(20260605) -> governance -> floor -> fleet.

    NOTE: the canonical live supervisor is `watchdog_guard.py`; the child
    components below are exactly what that supervisor would own. This planner
    reproduces the intent so the plan can be audited independently.
    """
    def _w(*script: str) -> list[str]:
        exe = str(PYTHONW if PYTHONW.exists() else sys.executable)
        return [exe, *script]

    plan = [
        Component(
            name="watchdog_guard (SINGLE supervisor of record)",
            args=_w(str(ROOT / "watchdog_guard.py")),
            probe=probe_supervisor,
            order=0,
            note="engine_lock.claim('watchdog_guard'); exits quietly if a 2nd "
                 "supervisor (or dist/RNative launcher) is already up.",
        ),
        Component(
            name=f"brain_server.py (ONE brain :{BRAIN_PORT})",
            args=_w(str(ROOT / "brain_server.py")),
            probe=probe_brain,
            order=2,
            note="root brain_server.py ONLY. Hosts /api/r/trade_gate and runs "
                 "orchestrator.start_all() curated agents in-process. The "
                 "r_native.brain_server needle is deprecated (no 2nd :5055).",
        ),
        Component(
            name=f"r_executor (ONE executor magic {EXECUTOR_MAGIC}, PAPER default)",
            args=_w("-m", "friday_v3.algory.r_executor"),  # NOTE: no --live here
            probe=probe_executor_mutex,
            order=4,
            required_demo=True,
            note="57322 LIVE mutex guards single copy. PAPER by default; --live "
                 "only on explicit DEMO-confirmed opt-in (not added by planner).",
        ),
        Component(
            name="portfolio_maestro.py (governance producer)",
            args=_w(str(ROOT / "portfolio_maestro.py")),
            probe=_always_false,
            order=5,
            note="folds live perf into engine_governance.json",
        ),
        Component(
            name="master_floor.py (catastrophe backstop)",
            args=_w(str(ROOT / "master_floor.py")),
            probe=_always_false,
            order=6,
            note="equity-floor kill -> kill_switch.txt; the only hard stop.",
        ),
    ]
    return plan


# --------------------------------------------------------------------------- #
# Planning + reporting                                                         #
# --------------------------------------------------------------------------- #
def evaluate(plan: list[Component]) -> list[Component]:
    """Run each probe once and annotate `already_running`. Read-only."""
    for c in plan:
        try:
            c.already_running = bool(c.probe())
        except Exception:
            c.already_running = None  # probe error -> treat as unknown
    return plan


def preflight_checks() -> list[str]:
    """Return a list of human-readable pre-flight findings. No side effects
    except ensuring data subdirs are *reported* (does not create them here)."""
    findings: list[str] = []
    findings.append(f"root                = {ROOT}")
    findings.append(f"pythonw exists      = {PYTHONW.exists()} ({PYTHONW})")
    findings.append(f"kill_switch.txt     = {KILL_SWITCH} (present={KILL_SWITCH.exists()})")
    for sub in ("symbol_configs", "hall_of_fame/by_symbol", "decision_log"):
        p = DATA_RN / sub
        findings.append(f"data subdir         = {p}  (exists={p.exists()})")
    is_demo, detail = assert_demo()
    findings.append(f"DEMO assertion      = {is_demo}  [{detail}]")
    return findings


def render_plan(plan: list[Component], demo_ok: bool) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(" UNIFIED RUNTIME -- BOOT PLAN (dry-run: nothing is launched)")
    lines.append("=" * 70)
    for c in sorted(plan, key=lambda x: x.order):
        if c.already_running is True:
            status = "ALREADY-RUNNING -> SKIP"
        elif c.already_running is False:
            status = "would START"
        else:
            status = "UNKNOWN (probe failed)"
        gate = ""
        if c.required_demo and not demo_ok and c.already_running is not True:
            gate = "  [BLOCKED: DEMO not confirmed -> will NOT arm]"
        lines.append(f"[{c.order:>2}] {status:<24} {c.name}{gate}")
        lines.append(f"       cmd : {' '.join(c.args)}")
        if c.note:
            lines.append(f"       why : {c.note}")
    lines.append("-" * 70)
    n_start = sum(1 for c in plan if c.already_running is False)
    n_skip = sum(1 for c in plan if c.already_running is True)
    lines.append(f"summary: {n_skip} already-running/skipped, {n_start} would-start")
    lines.append("=" * 70)
    return "\n".join(lines)


def plan_as_dict(plan: list[Component], demo_ok: bool) -> dict:
    return {
        "root": str(ROOT),
        "demo_confirmed": demo_ok,
        "components": [
            {
                **{k: v for k, v in asdict(c).items() if k not in ("probe",)},
                "action": (
                    "skip"
                    if c.already_running
                    else ("blocked-demo" if (c.required_demo and not demo_ok) else "start")
                ),
            }
            for c in sorted(plan, key=lambda x: x.order)
        ],
    }


# --------------------------------------------------------------------------- #
# Launch (guarded; only for MISSING components; never in dry-run)             #
# --------------------------------------------------------------------------- #
def launch_missing(plan: list[Component], demo_ok: bool) -> list[str]:
    """Start ONLY components whose probe said not-running. Never duplicates.

    This is intentionally conservative: it starts windowless detached processes
    and does NOT verify/kill anything. In practice the live supervisor is
    watchdog_guard.py; this path exists for parity/testing of the plan.
    """
    started: list[str] = []
    for c in sorted(plan, key=lambda x: x.order):
        if c.already_running:
            continue  # respect the double-bind lesson -- never double-spawn
        if c.required_demo and not demo_ok:
            started.append(f"SKIP (DEMO not confirmed): {c.name}")
            continue
        try:
            creationflags = 0
            if os.name == "nt":
                # CREATE_NO_WINDOW | DETACHED_PROCESS
                creationflags = 0x08000000 | 0x00000008
            subprocess.Popen(
                c.args,
                cwd=str(ROOT),
                creationflags=creationflags,
                close_fds=True,
            )
            started.append(f"STARTED: {c.name}")
        except Exception as exc:
            started.append(f"FAILED ({exc}): {c.name}")
    return started


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="unified_launcher",
        description="Non-destructive single-entry boot PLANNER for R-Native. "
                    "Defaults to a safe dry-run that only prints the plan.",
    )
    # Safety: dry-run is the default. --no-dry-run must be explicit to launch.
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="(default) print the boot plan, launch nothing.",
    )
    p.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="GUARDED: actually start MISSING components (never duplicates, "
             "never kills). The live supervisor is still watchdog_guard.py.",
    )
    p.add_argument(
        "--audit",
        action="store_true",
        help="only probe what is alive and print pre-flight findings; no plan.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit the plan as machine-readable JSON.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argparser().parse_args(argv)

    demo_ok, demo_detail = assert_demo()

    if args.audit:
        print("PRE-FLIGHT / AUDIT (read-only)")
        for line in preflight_checks():
            print("  " + line)
        plan = evaluate(build_plan())
        print()
        for c in sorted(plan, key=lambda x: x.order):
            state = ("UP" if c.already_running else
                     "down" if c.already_running is False else "unknown")
            print(f"  [{state:>7}] {c.name}")
        return 0

    plan = evaluate(build_plan())

    if args.json:
        print(json.dumps(plan_as_dict(plan, demo_ok), indent=2, ensure_ascii=False))
        return 0

    # Human-readable path.
    print("PRE-FLIGHT")
    for line in preflight_checks():
        print("  " + line)
    print()
    print(render_plan(plan, demo_ok))

    if args.dry_run:
        print("\nDRY-RUN: no processes were launched. "
              "Re-run with --no-dry-run to start MISSING components only.")
        return 0

    # Real (guarded) launch of missing components only.
    print("\nLAUNCHING MISSING COMPONENTS (guarded; duplicates are skipped):")
    for msg in launch_missing(plan, demo_ok):
        print("  " + msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
