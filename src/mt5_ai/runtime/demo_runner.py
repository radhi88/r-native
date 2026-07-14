"""demo_runner.py — Single-cycle demo for manual testing.

Runs one full pipeline cycle on a single symbol/timeframe and prints results.
Does NOT place any real orders (uses DRY_RUN from config).

Usage:
    python -m mt5_ai.runtime.demo_runner
    python -m mt5_ai.runtime.demo_runner --symbol XAUUSDm --timeframe H1
"""
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

import os as _os
_env_root = _os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[3]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s %(message)s")
log = logging.getLogger("demo_runner")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",    default="EURUSDm")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    from mt5_ai.runtime.dry_run_runner import run_one_cycle
    log.info("Demo run: %s %s", args.symbol, args.timeframe)
    result = run_one_cycle(symbol=args.symbol, timeframe=args.timeframe)
    print("\n── DEMO RESULT ──────────────────────────────────────────────")
    for k, v in result.items():
        print(f"  {k:20s}: {v}")
    print("─────────────────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
