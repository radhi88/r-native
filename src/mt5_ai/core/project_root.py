"""project_root.py — Single source of truth for the FRIDAY project root path.

All modules that need an absolute path to project-level directories (logs, config,
data) must import from here instead of using hardcoded C:\\Users\\... strings.

Resolution order:
  1. FRIDAY_PROJECT_ROOT env var (set this for portable installs / EXE)
  2. Walk upward from __file__ until config/trading_runtime.yaml is found
  3. RuntimeError with helpful message if neither works
"""
from __future__ import annotations
import os
from pathlib import Path


def _find_project_root() -> Path:
    env = os.getenv("FRIDAY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    candidate = Path(__file__).resolve()
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "config" / "trading_runtime.yaml").exists():
            return candidate
    raise RuntimeError(
        "Cannot locate FRIDAY project root. "
        "Set the FRIDAY_PROJECT_ROOT environment variable to the MT5 directory."
    )


PROJECT_ROOT   = _find_project_root()
APPDATA_FRIDAY = Path.home() / "AppData" / "Local" / "FRIDAY"
APPDATA_ALGORY = Path.home() / "AppData" / "Local" / "Algory"
