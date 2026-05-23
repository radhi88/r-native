"""build_exe.py - PyInstaller build script for R Native standalone .exe

Usage:
    cd C:\\Users\\Radhi\\MT5
    python r_native\\build_exe.py

Output:
    dist/RNative/RNative.exe (single window, ~120MB with Qt + WebEngine bundled)

After build, COPY the entire dist/RNative/ folder to install on another machine.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Ensure PyInstaller
try:
    import PyInstaller
except ImportError:
    print("Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

# Clean previous builds (but preserve user data)
for d in ["build", "dist/RNative"]:
    p = Path(d)
    if p.exists():
        shutil.rmtree(p)

print()
print("=" * 60)
print("  Building R Native — Standalone .exe")
print("=" * 60)
print()

args = [
    "pyinstaller",
    "--name", "RNative",
    "--windowed",                       # no console
    "--noconfirm",
    "--clean",
    # Icon (use SVG via temp PNG; or skip if absent)
    # "--icon", "friday_v3/algory/r_logo.svg",

    # Hidden imports (PyInstaller can miss dynamic imports)
    "--hidden-import", "MetaTrader5",
    "--hidden-import", "numpy",
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--collect-submodules", "PySide6",

    # Include the friday_v3 package so existing helpers still work
    "--add-data", "friday_v3;friday_v3",
    "--add-data", "r_native;r_native",

    # Entry point
    "r_native/app.py",
]

print("Running:", " ".join(args[:5]) + " ...")
print()
result = subprocess.run(args)

if result.returncode != 0:
    print("\n[!] Build failed.")
    sys.exit(1)

exe = Path("dist/RNative/RNative.exe")
if not exe.exists():
    print(f"\n[!] Build finished but {exe} not found.")
    sys.exit(1)

size_mb = exe.stat().st_size / 1024 / 1024
folder_size_mb = sum(
    f.stat().st_size for f in Path("dist/RNative").rglob("*") if f.is_file()
) / 1024 / 1024

print()
print("=" * 60)
print("  ✓ BUILD SUCCESS")
print("=" * 60)
print(f"  Executable : {exe.absolute()}")
print(f"  exe size   : {size_mb:.1f} MB")
print(f"  folder size: {folder_size_mb:.1f} MB (bundle to ship)")
print()
print("  RUN:  " + str(exe.absolute()))
print()
print("  SHIP: copy entire dist/RNative/ folder to target machine")
print("        (target must have MT5 installed and MetaTrader5 Python lib)")
