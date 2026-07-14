"""Smart Algorithm Pro single-command launcher.

This intentionally reuses scripts/run_gader.py so the project has one trading
runtime instead of two competing implementations. Live trading remains blocked
by the MT5 gateway; use --mode demo for MT5 demo execution or --mode paper for
fully virtual execution.
"""

from __future__ import annotations

import sys
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from run_gader import main


if __name__ == "__main__":
    main()
