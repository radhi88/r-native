"""run_all_auto.py — يُشغّل كل خطوات الـhandoff تلقائياً من IDLE.

افتحه في IDLE ثم اضغط F5.
"""
import subprocess
import sys
import os
import json
from pathlib import Path

REPO    = Path(r"C:\Users\Radhi\MT5\r-native-pipflow")
VENV_PY = Path(r"C:\Users\Radhi\MT5\.venv\Scripts\python.exe")
DATA    = REPO / "data"
DATA.mkdir(exist_ok=True)

def run(cmd, cwd=REPO, check=True):
    print(f"\n>>> {' '.join(str(x) for x in cmd)}")
    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        capture_output=False,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"  ERROR: exit code {result.returncode}")
    return result.returncode == 0

print("=" * 60)
print(" R-Native v2 — Full Auto Setup")
print("=" * 60)

# ── Step 1: Tests ──────────────────────────────────────────────
print("\n[1/5] Running unit tests...")
ok = run([VENV_PY, "tests/run_all.py"])
print("  tests:", "PASS ✓" if ok else "FAIL ✗")

# ── Step 2: Export MT5 bars ────────────────────────────────────
print("\n[2/5] Exporting XAUUSDm M3 bars from MT5...")
bars_path = DATA / "gold_m3_live.json"
ok = run([VENV_PY, "tools/export_mt5_bars.py",
          "--symbol", "XAUUSDm", "--tf", "M3", "--bars", "8000",
          "--out", str(bars_path)])
if not bars_path.exists():
    print("  WARNING: export failed — bars file not created")

# ── Step 3: Stoch backtest with SL ────────────────────────────
if bars_path.exists():
    print("\n[3/5] Stoch Reversion backtest (with SL)...")
    run([VENV_PY, "tools/backtest_stoch_on_live_mt5.py",
         "--json", str(bars_path), "--use-sl", "1",
         "--out", str(DATA / "gold_real.png")])

    print("\n[4/5] Stoch Reversion backtest (no SL)...")
    run([VENV_PY, "tools/backtest_stoch_on_live_mt5.py",
         "--json", str(bars_path), "--use-sl", "0",
         "--out", str(DATA / "gold_no_sl.png")])
else:
    print("\n[3-4/5] Skipped — no bars data")

# ── Step 4: Copy EA ───────────────────────────────────────────
print("\n[5/5] Copying EA to MetaTrader Experts folder...")
import shutil, glob

src = REPO / "mql5_templates" / "Stoch_Reversion_M3.mq5"

# Find MetaTrader Experts folder
mt_roots = glob.glob(
    r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\*\MQL5\Experts"
)
if mt_roots:
    dst = Path(mt_roots[0]) / "Stoch_Reversion_M3.mq5"
    shutil.copy2(src, dst)
    print(f"  Copied to: {dst}")
else:
    print("  WARNING: MetaTrader Experts folder not found")

# ── Summary ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print(" DONE — Check data/ for PNG charts")
print("  data/gold_real.png    (with SL)")
print("  data/gold_no_sl.png   (no SL)")
print("\nNext: Open MetaEditor, open Stoch_Reversion_M3.mq5, press F7")
print("=" * 60)
