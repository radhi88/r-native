"""build_exe.py - One-command PyInstaller build for R Factory Desktop.

Output: dist/RFactory.exe (single file ~150MB, includes Python + Qt + WebEngine)

Usage:
  cd C:\\Users\\Radhi\\MT5
  python r_desktop\\build_exe.py
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Ensure PyInstaller is available
try:
    import PyInstaller
except ImportError:
    print("Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

# Clean previous builds
for d in ["build", "dist"]:
    if Path(d).exists(): shutil.rmtree(d)

# Build args
args = [
    "pyinstaller",
    "--name", "RFactory",
    "--icon", "friday_v3/algory/r_logo.svg",
    "--windowed",
    "--noconfirm",
    # Hidden imports (modules PyInstaller may miss)
    "--hidden-import", "MetaTrader5",
    "--hidden-import", "numpy",
    "--hidden-import", "flask",
    "--hidden-import", "psutil",
    "--hidden-import", "PySide6.QtWebEngineCore",
    "--hidden-import", "PySide6.QtWebEngineWidgets",
    # Data files (everything the app needs at runtime)
    "--add-data", "brain_server.py;.",
    "--add-data", "friday_v3;friday_v3",
    "--add-data", "dashboard;dashboard",
    "--add-data", "friday_memory.py;.",
    "--add-data", "friday_regime.py;.",
    # Entry point
    "r_desktop/r_app.py",
]

print("\n" + "="*60)
print("  Building R Factory Desktop App")
print("="*60)
print(f"  cwd:    {PROJECT_ROOT}")
print(f"  output: dist/RFactory.exe (single window)")
print()

result = subprocess.run(args)
if result.returncode != 0:
    print("\n[!] Build failed.")
    sys.exit(1)

exe_path = Path("dist") / "RFactory" / "RFactory.exe"
if exe_path.exists():
    size_mb = exe_path.stat().st_size / 1024 / 1024
    print("\n" + "="*60)
    print(f"  ✓ BUILD SUCCESS")
    print("="*60)
    print(f"  Executable: {exe_path.absolute()}")
    print(f"  Size:       {size_mb:.1f} MB")
    print()
    print("  Test:    " + str(exe_path.absolute()))
    print("  Copy:    copy entire dist/RFactory/ folder to install on another machine")
