# -*- coding: utf-8 -*-
"""Root compatibility entrypoint for the real-data unified signal bridge."""
from __future__ import annotations

import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent / "agents"
sys.path.insert(0, str(AGENTS_DIR))

from unified_signal_bridge import main  # noqa: E402


if __name__ == "__main__":
    main()
