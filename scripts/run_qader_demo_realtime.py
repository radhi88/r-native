"""Run Qader realtime demo execution until a target trade count or blocker."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from qader_app.services.real_mode_service import RealModeService
from qader_app.services.real_time_loop_service import RealTimeLoopService
from qader_app.storage.settings_store import REAL_UNLOCK_PHRASE


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Qader demo realtime loop.")
    parser.add_argument("--target", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--stop-after-target", action="store_true")
    parser.add_argument("--keep-running-after-target", action="store_true")
    args = parser.parse_args()

    real_mode = RealModeService()
    lockdown = real_mode.run_lockdown_check()
    unlock = real_mode.unlock(REAL_UNLOCK_PHRASE) if lockdown.get("ok") else {"ok": False, "reason": "lockdown_failed"}
    loop = RealTimeLoopService()
    start = loop.start(final_confirmation=True) if unlock.get("ok") else {"ok": False, "reason": "unlock_failed", "unlock": unlock}
    started = time.monotonic()
    final_reason = ""

    while start.get("ok"):
        status = loop.status()
        if int(status.get("demo_trades_opened", 0) or 0) >= args.target:
            final_reason = f"target_demo_trades_reached:{status.get('demo_trades_opened')}"
            if args.stop_after_target:
                loop.stop(final_reason)
                break
            if args.keep_running_after_target:
                time.sleep(1.0)
                continue
            break
        if status.get("state") in {"BLOCKED", "EMERGENCY_STOP"}:
            final_reason = str(status.get("reason", status.get("state")))
            break
        if time.monotonic() - started >= args.timeout_seconds:
            final_reason = f"timeout_waiting_for_{args.target}_demo_trades"
            break
        time.sleep(1.0)

    status = loop.status()
    summary = {
        "lockdown_ok": lockdown.get("ok"),
        "unlock_ok": unlock.get("ok"),
        "start": start,
        "status": status,
        "target": args.target,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "final_reason": final_reason or start.get("reason", ""),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if start.get("ok") and int(status.get("demo_trades_opened", 0) or 0) >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())
