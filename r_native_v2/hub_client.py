"""
hub_client.py — B3: first read-only client of the R Native 2 hub.

A tiny stdlib CLI that consumes the hub's GET /health and GET /state and prints a
tidy text status board. Proves the "one client → one front door" pattern with ZERO risk:
  • Read-only: only HTTP GET. Never POSTs, never touches an engine, never trades.
  • Zero dependencies (stdlib urllib/json only).
  • Does NOT modify any live dashboard — it is a brand-new, separate client.

Run:  python r_native_v2/hub_client.py          (one-shot)
      python r_native_v2/hub_client.py --watch  (refresh every 5s)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

HUB = "http://127.0.0.1:8800"


def _get(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{HUB}{path}", timeout=4) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"_error": str(exc)}


def _fmt_age(a) -> str:
    if a is None:
        return "—"
    a = float(a)
    if a < 90:
        return f"{a:.0f}s"
    if a < 5400:
        return f"{a/60:.0f}m"
    return f"{a/3600:.1f}h"


def render() -> str:
    health = _get("/health")
    state = _get("/state")
    out = []
    out.append("=" * 52)
    out.append(" R NATIVE 2 HUB — status board (read-only client)")
    out.append("=" * 52)
    if "_error" in health:
        out.append(f"  HUB UNREACHABLE: {health['_error']}")
        out.append("  (is the hub running? -> runtime/launch_hub.ps1)")
        return "\n".join(out)

    out.append(f"  hub      : {health.get('hub')}  v{health.get('version','?')}  "
               f"pid={health.get('pid')}  hb={_fmt_age(health.get('hub_heartbeat_age_s'))}")
    out.append(f"  mode     : {health.get('mode','?')}")
    out.append(f"  time     : {health.get('ts','?')}")
    out.append("  " + "-" * 48)
    out.append("  engines (liveness):")
    for name, info in (health.get("engines") or {}).items():
        mark = "●" if info.get("present") else "○"
        out.append(f"    {mark} {name:<12} age={_fmt_age(info.get('age_s')):<6} "
                   f"src={info.get('alive_source') or '—'}")
    out.append("  agent_bus heartbeats:")
    for name, info in (health.get("heartbeats") or {}).items():
        mark = "●" if info.get("present") else "○"
        out.append(f"    {mark} {name:<12} {_fmt_age(info.get('age_s'))}")
    if "_error" not in state:
        out.append("  " + "-" * 48)
        out.append("  state files:")
        for name, info in (state.get("files") or {}).items():
            ok = "ok " if info.get("ok") else "ERR"
            out.append(f"    [{ok}] {name:<12} age={_fmt_age(info.get('age_s'))}")
    out.append("=" * 52)
    return "\n".join(out)


def main(argv: list[str]) -> int:
    watch = "--watch" in argv
    if not watch:
        print(render())
        return 0
    try:
        while True:
            # clear screen (best-effort) then redraw
            sys.stdout.write("\x1b[2J\x1b[H")
            print(render())
            time.sleep(5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
