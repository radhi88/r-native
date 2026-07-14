from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5


ROOT = Path(r"C:\Users\Radhi\MT5")
AUTO_TRADER = ROOT / "scripts" / "friday_auto_trader.py"
LOG_DIR = ROOT / "demo_test_logs"

DEMO_KEYWORDS = ["demo", "trial", "practice", "contest"]


def ensure_demo() -> bool:
    if not mt5.initialize():
        print("ERROR: MT5 initialize failed")
        print("last_error:", mt5.last_error())
        return False

    try:
        account = mt5.account_info()

        if account is None:
            print("ERROR: No MT5 account info.")
            return False

        server = str(getattr(account, "server", "") or "")
        login = getattr(account, "login", "")
        balance = getattr(account, "balance", "")

        is_demo = any(k in server.lower() for k in DEMO_KEYWORDS)

        print("MT5 Account Check")
        print("Login:", login)
        print("Server:", server)
        print("Balance:", balance)
        print("Demo detected:", is_demo)

        if not is_demo:
            print("BLOCKED: الحساب الحالي ليس Demo.")
            return False

        return True

    finally:
        mt5.shutdown()


def main() -> int:
    if not AUTO_TRADER.exists():
        print(f"ERROR: Auto trader not found: {AUTO_TRADER}")
        return 1

    if not ensure_demo():
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"friday_demo_5min_{stamp}.log"

    print("")
    print("Starting FRIDAY guarded DEMO run for 5 minutes...")
    print("WARNING: هذا تشغيل Demo وقد يفتح صفقات وهمية فقط.")
    print("Log:", log_path)
    print("")

    cmd = [
        sys.executable,
        str(AUTO_TRADER),
        "--no-auto-live",
    ]

    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            for remaining in range(300, 0, -10):
                print(f"Running... remaining {remaining}s")
                time.sleep(10)

                if proc.poll() is not None:
                    print("FRIDAY exited early with code:", proc.returncode)
                    break

        finally:
            if proc.poll() is None:
                print("Stopping FRIDAY demo run...")
                proc.terminate()

                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

    print("")
    print("Done.")
    print("Log saved:", log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
