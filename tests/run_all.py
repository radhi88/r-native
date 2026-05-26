"""Run every test module in this folder. Used by CI / pre-commit / by hand.

    python tests/run_all.py

Exit code 0 = all passed, 1 = at least one failed.
"""
from __future__ import annotations

import os
import sys
import importlib
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # repo root on path


def _discover_test_modules():
    out = []
    for name in sorted(os.listdir(HERE)):
        if not name.startswith("test_") or not name.endswith(".py"): continue
        out.append("tests." + name[:-3])
    return out


def main():
    modules = _discover_test_modules()
    failed = []
    for modname in modules:
        print(f"\n=== {modname} ===")
        try:
            mod = importlib.import_module(modname)
            tests = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
            for t in tests:
                try:
                    t()
                except AssertionError as e:
                    print(f"  FAIL {t.__name__}: {e}")
                    failed.append(f"{modname}.{t.__name__}")
                except Exception as e:
                    print(f"  ERROR {t.__name__}: {e}")
                    traceback.print_exc()
                    failed.append(f"{modname}.{t.__name__}")
        except Exception as e:
            print(f"  import error: {e}")
            traceback.print_exc()
            failed.append(modname)
    print()
    if failed:
        print(f"✗ {len(failed)} test(s) failed:")
        for f in failed: print(f"  - {f}")
        sys.exit(1)
    print("✓ all tests passed")


if __name__ == "__main__":
    main()
