"""Native workflow runner for the geometric desk.

A dependency-free executor that runs a JSON workflow definition with ordered
steps and validation gates — the same shape as the workflow-automation skill
(``name`` / ``steps`` / ``depends`` / gates) but executed locally and
reliably, with no external orchestrator or token cost.

Usage:
    python scripts/run_workflow.py list
    python scripts/run_workflow.py run --name desk-lifecycle
    python scripts/run_workflow.py status
    python scripts/run_workflow.py export --format yaml
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WF_DIR = os.path.join(_ROOT, "workflows")
_STATUS = os.path.join(_WF_DIR, ".status.json")
sys.path.insert(0, _ROOT)


# ─── Step actions ────────────────────────────────────────────────────
def _run(cmd: list[str], needle: str | None = None) -> tuple[bool, str]:
    """Run a subprocess; success on exit 0 (and ``needle`` present if given)."""
    try:
        r = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    ok = r.returncode == 0 and (needle is None or needle in (r.stdout + r.stderr))
    return ok, tail[0][:140]


def act_compile(_: dict) -> tuple[bool, str]:
    """Byte-compile every module."""
    return _run([sys.executable, "-c",
                 "import glob,py_compile;"
                 "[py_compile.compile(f,doraise=True) for f in glob.glob('**/*.py',recursive=True)];"
                 "print('compiled OK')"], "compiled OK")


def act_pytest(_: dict) -> tuple[bool, str]:
    """Run the unit test suite."""
    return _run([sys.executable, "-m", "pytest", "-q"], "passed")


def act_selftest(_: dict) -> tuple[bool, str]:
    """Run the offline pipeline self-test."""
    return _run([sys.executable, "run.py", "--selftest"], "VERDICT")


def _port_free(port: int) -> bool:
    """True if the singleton watchdog port is not yet held."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def act_launch(_: dict) -> tuple[bool, str]:
    """Start the detached supervisor if not already running (idempotent)."""
    if not _port_free(8626):
        return True, "supervisor already running (:8626 held)"
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    flags = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    try:
        subprocess.Popen([exe, os.path.join(_ROOT, "scripts", "watchdog.py")],
                         cwd=_ROOT, creationflags=flags, close_fds=True)
        time.sleep(8)
        return True, "supervisor launched detached"
    except Exception as exc:  # noqa: BLE001
        return False, f"launch failed: {exc}"


def act_verify(_: dict) -> tuple[bool, str]:
    """Confirm the dashboard is live and agents publish to the bus."""
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            d = json.load(urllib.request.urlopen("http://127.0.0.1:8780/state", timeout=5))
            slices = d.get("slices", {})
            have = [k for k in ("desk", "hr", "evo") if k in slices]
            if "desk" in have and d.get("account"):
                return True, f"dashboard live, agents publishing: {have}"
        except Exception:
            pass
        time.sleep(5)
    return False, "dashboard/agents did not come up within 90s"


def act_report(_: dict) -> tuple[bool, str]:
    """Generate the transparency report."""
    try:
        from reports.report import generate
        generate()
        return True, "report written to reports/out/"
    except Exception as exc:  # noqa: BLE001
        return False, f"report failed: {exc}"


_ACTIONS = {"compile": act_compile, "pytest": act_pytest, "selftest": act_selftest,
            "launch": act_launch, "verify": act_verify, "report": act_report}


# ─── Engine ──────────────────────────────────────────────────────────
def _load(name: str) -> dict:
    """Load a workflow definition by name."""
    with open(os.path.join(_WF_DIR, f"{name}.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _order(steps: list[dict]) -> list[dict]:
    """Topologically sort steps by their ``depends`` lists."""
    done, out = set(), []
    while len(out) < len(steps):
        progressed = False
        for s in steps:
            if s["name"] in done:
                continue
            if all(d in done for d in s.get("depends", [])):
                out.append(s)
                done.add(s["name"])
                progressed = True
        if not progressed:
            raise ValueError("cyclic or unresolved dependencies")
    return out


def run_workflow(name: str) -> int:
    """Execute a workflow, halting on a failed gated step."""
    wf = _load(name)
    print(f"▶ workflow '{wf['name']}' — {wf['description']}\n")
    results, halted = [], False
    for step in _order(wf["steps"]):
        if halted:
            print(f"  ⏭  {step['name']:9} skipped (upstream gate failed)")
            results.append({"step": step["name"], "ok": None, "detail": "skipped"})
            continue
        action = _ACTIONS.get(step["action"])
        print(f"  ▷ {step['name']:9} {step['task']}")
        ok, detail = action(step) if action else (False, "unknown action")
        mark = "✓" if ok else "✗"
        print(f"    {mark} {detail}")
        results.append({"step": step["name"], "ok": ok, "detail": detail})
        if not ok and step.get("gate"):
            print(f"    ⛔ gate '{step['name']}' failed — halting pipeline")
            halted = True
    _save_status(name, results)
    passed = sum(1 for r in results if r["ok"])
    print(f"\n■ done: {passed}/{len(results)} steps passed"
          + (" — HALTED" if halted else " — OK"))
    return 1 if halted else 0


def _save_status(name: str, results: list[dict]) -> None:
    """Persist the last run's per-step results."""
    os.makedirs(_WF_DIR, exist_ok=True)
    with open(_STATUS, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "results": results}, fh, indent=2)


def list_workflows() -> None:
    """Print available workflow definitions."""
    for f in sorted(os.listdir(_WF_DIR)):
        if f.endswith(".json"):
            wf = _load(f[:-5])
            print(f"  {wf['name']:16} {len(wf['steps'])} steps — {wf['description'][:70]}")


def show_status() -> None:
    """Print the last run's status."""
    try:
        with open(_STATUS, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except OSError:
        print("no runs yet")
        return
    print(f"last run: {st['name']} @ {st['ts']}")
    for r in st["results"]:
        mark = "✓" if r["ok"] else ("⏭" if r["ok"] is None else "✗")
        print(f"  {mark} {r['step']:9} {r['detail']}")


def export_yaml(name: str) -> None:
    """Print a YAML view of a workflow (no pyyaml dependency)."""
    wf = _load(name)
    print(f"name: {wf['name']}")
    print(f"description: {wf['description']}")
    print("steps:")
    for s in wf["steps"]:
        print(f"  - name: {s['name']}")
        print(f"    action: {s['action']}")
        print(f"    task: \"{s['task']}\"")
        print(f"    depends: [{', '.join(s.get('depends', []))}]")
        print(f"    gate: {str(s.get('gate', False)).lower()}")


def main() -> int:
    """CLI entry point."""
    p = argparse.ArgumentParser(description="Native desk workflow runner")
    p.add_argument("command", choices=["run", "list", "status", "export"])
    p.add_argument("--name", default="desk-lifecycle")
    p.add_argument("--format", default="yaml")
    args = p.parse_args()
    if args.command == "list":
        list_workflows()
    elif args.command == "status":
        show_status()
    elif args.command == "export":
        export_yaml(args.name)
    else:
        return run_workflow(args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
