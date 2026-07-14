"""MT5 AI trading toolkit."""

# Auto-create directory structure on import
import os
from pathlib import Path

_BASE = Path(__file__).parent
_DIRS = ["strategies", "learning", "genetics", "integrations", "interfaces", "utils"]

for _dir in _DIRS:
    (_BASE / _dir).mkdir(parents=True, exist_ok=True)

del _BASE, _DIRS, _dir, Path, os

