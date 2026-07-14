from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def bootstrap():
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)
    return PROJECT_ROOT
