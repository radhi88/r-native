from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import MetaTrader5 as mt5


ROOT = Path(r"C:\Users\Radhi\MT5")
AUTO_TRADER = ROOT / "scripts" / "friday_auto_trader.py"

DEMO_KEYWORDS = [
    "demo",
    "trial",
    "practice",
    "contest",
]


def main() -> int:
    if not AUTO_TRADER.exists():
        print(f"ERROR: Auto trader not found: {AUTO_TRADER}")
        return 1

    if not mt5.initialize():
        print("ERROR: MT5 initialize failed")
        print("last_error:", mt5.last_error())
        return 1

    try:
        account = mt5.account_info()

        if account is None:
            print("ERROR: No MT5 account info. افتح MT5 وسجل دخولك على حساب Demo.")
            return 1

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
            print("BLOCKED: الحساب الحالي ليس Demo حسب اسم السيرفر.")
            print("افتح MT5 على حساب وهمي Demo فقط ثم أعد التشغيل.")
            return 2

    finally:
        mt5.shutdown()

    print("")
    print("Starting FRIDAY demo one-cycle test...")
    print("WARNING: هذا قد يفتح صفقة Demo إذا ظهرت إشارة مناسبة.")
    print("")

    cmd = [
        sys.executable,
        str(AUTO_TRADER),
        "--once",
        "--no-auto-live",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
    )

    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
