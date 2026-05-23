"""build_exe.py - PyInstaller build script for R Native.

Usage:
    cd C:\\Users\\Radhi\\MT5
    python r_native\\build_exe.py                # legacy single-EXE (RNative.exe)
    python r_native\\build_exe.py --two-exe      # H.3: RNativeLauncher + RNativeWorker

Output:
    dist/RNative/RNative.exe               (single mode)
    dist/RNative/RNativeLauncher.exe       (two-exe mode — entry point user clicks)
    dist/RNative/RNativeWorker.exe         (two-exe mode — spawned by launcher)

After build, COPY the entire dist/RNative/ folder to install on another machine.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

TWO_EXE = "--two-exe" in sys.argv

PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Ensure PyInstaller
try:
    import PyInstaller
except ImportError:
    print("Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

# Build to a STAGING dir (dist_new) so we don't fight Explorer.exe / Defender
# locking the in-use dist/RNative folder. Swap atomically at the end.
def _force_remove(func, path, exc_info):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

# Always clear the staging dir
for d in ["build", "dist_new"]:
    p = Path(d)
    if p.exists():
        shutil.rmtree(p, onerror=_force_remove)

print()
print("=" * 60)
print("  Building R Native — Standalone .exe")
print("=" * 60)
print()

if TWO_EXE:
    # H.3: Launcher + Worker sharing one _internal/ — driven by spec file
    args = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--distpath", "dist_new",
        "RNative_TwoExe.spec",
    ]
    print(f"  mode: TWO-EXE (RNativeLauncher + RNativeWorker, shared _internal/)")
else:
    # Legacy single-EXE
    args = [
        "pyinstaller",
        "--name", "RNative",
        "--windowed",                       # no console
        "--noconfirm",
        "--clean",
        # Build into a staging path — old dist/RNative may be locked by Explorer/Defender
        "--distpath", "dist_new",
        # Icon — PyInstaller wants .ico for Windows (embeds into PE resource)
        "--icon", "friday_v3/algory/r_logo.ico",

        # Hidden imports (PyInstaller can miss dynamic imports)
        "--hidden-import", "MetaTrader5",
        "--hidden-import", "numpy",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "flask",
        "--hidden-import", "psutil",
        "--collect-submodules", "PySide6",

        # Bundle r_native source (panels, inspector, dna_widget, actions are imported dynamically)
        # NOTE: PyInstaller does NOT honor .gitignore — we pre-stage to a clean temp dir below
        "--add-data", "r_native;r_native",
        # friday_v3 is NOT bundled — actions.py uses absolute path to live MT5 directory.
        # Just include the algory subfolder (logo + helpers) at ~400KB instead of the 7.5GB data dump.
        "--add-data", "friday_v3/algory;friday_v3/algory",
        "--add-data", "friday_v3/__init__.py;friday_v3",

        # Entry point
        "r_native/app.py",
    ]
    print(f"  mode: SINGLE-EXE (legacy RNative.exe)")

print("Running:", " ".join(args[:5]) + " ...")
print()
result = subprocess.run(args)

if result.returncode != 0:
    print("\n[!] Build failed.")
    sys.exit(1)

# ── Atomic swap: rename old dist/RNative aside, move dist_new/RNative into place ──
staged = Path("dist_new/RNative")
final  = Path("dist/RNative")
if not staged.exists():
    print(f"\n[!] Staged build {staged} missing — PyInstaller didn't produce output.")
    sys.exit(1)

if final.exists():
    from datetime import datetime
    backup = Path(f"dist/_old_RNative_{datetime.now():%Y%m%d_%H%M%S}")
    try:
        final.rename(backup)
        print(f"  archived old build → {backup}")
    except OSError as e:
        # Lock still held — try removing the backup name and retry once
        print(f"  [warn] could not rename old build ({e}). Trying force-remove…")
        shutil.rmtree(final, onerror=_force_remove)

final.parent.mkdir(parents=True, exist_ok=True)
staged.rename(final)
print(f"  promoted {staged} → {final}")
# Clean staging parent if empty
try: staged.parent.rmdir()
except OSError: pass

expected_exes = ["RNativeLauncher.exe", "RNativeWorker.exe"] if TWO_EXE else ["RNative.exe"]
missing = [e for e in expected_exes if not (Path("dist/RNative") / e).exists()]
if missing:
    print(f"\n[!] Build finished but missing: {missing}")
    sys.exit(1)

folder_size_mb = sum(
    f.stat().st_size for f in Path("dist/RNative").rglob("*") if f.is_file()
) / 1024 / 1024

print()
print("=" * 60)
print("  ✓ BUILD SUCCESS")
print("=" * 60)
for name in expected_exes:
    exe = Path("dist/RNative") / name
    print(f"  {name:24s} {exe.stat().st_size / 1024 / 1024:6.1f} MB   {exe.absolute()}")
print(f"  folder total              {folder_size_mb:6.1f} MB (bundle to ship)")
print()
if TWO_EXE:
    print(f"  RUN:  {(Path('dist/RNative') / 'RNativeLauncher.exe').absolute()}")
    print(f"        (Launcher will spawn Worker automatically + show tray icon)")
else:
    print(f"  RUN:  {(Path('dist/RNative') / 'RNative.exe').absolute()}")
print()
print("  SHIP: copy entire dist/RNative/ folder to target machine")
print("        (target must have MT5 installed and MetaTrader5 Python lib)")
